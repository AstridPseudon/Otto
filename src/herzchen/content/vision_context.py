"""Bounded Vision context, history, and exact DAT context packets.

This is deliberately a small composition over :mod:`vision_queries` and the
existing ``ContextPacketService``.  It owns no graph, cache, table, or
checkpoint registry.  Current reads use one bounded Vision projection; saved
packets contain the exact DAT revision vector observed by that read.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

from herzchen.contracts import (
    AuthenticatedActor,
    ReferenceBinding,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.content.model import revision_identity
from herzchen.content.packets import (
    AccessDeniedError,
    PacketError,
    UnresolvedReferenceError,
)

from .vision_queries import (
    PRESETS,
    VisionAuthorizationError,
    VisionProjection,
    VisionQueryError,
    VisionQueryService,
    _copy,
    _digest,
    _identity,
    _identity_key,
    _ref,
    _target_ref,
)


CONTEXT_SCHEMA = "vision.context.v1"
SNAPSHOT_SCHEMA = "vision.snapshot.v1"
MAX_CONTEXT_NODES = 8
MAX_CONTEXT_EDGES = 24
MAX_RENDERED_BYTES = 12 * 1024
MAX_CONTEXT_JSON_BYTES = 64 * 1024
MAX_FOCUS = 3
MAX_HISTORICAL_INPUTS = 8
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 50


class VisionContextError(VisionQueryError):
    """A bounded context, history, or packet operation is invalid."""


class VisionSnapshotUnavailable(VisionContextError):
    """A packet or one of its explicitly referenced sources is unavailable."""


def _json_copy(value: Any) -> Any:
    """Copy a value through the declared contract representation."""
    return json.loads(canonical_json(_copy(value)))


def _request_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _exact_ref(value: Any, field: str) -> ResourceRef:
    ref = _ref(value, field)
    if ref.revision is None:
        raise VisionContextError(f"bad_request: {field} must be an exact revision reference")
    return ref


def _revision_ref(ref: ResourceRef, revision: str) -> ResourceRef:
    return replace(ref, revision=revision)


def _content_item(item: Mapping[str, Any], *, reason: str, excerpt: str = "", truncated: bool = False) -> dict[str, Any]:
    content = item["content"]
    return {
        "ref": item["ref"].to_dict(),
        "revision_ref": item["revision_ref"].to_dict(),
        "digest": item["digest"],
        "kind": content.get("kind"),
        "title": content.get("title"),
        "summary": content.get("summary"),
        "excerpt": excerpt,
        "excerpt_truncated": truncated,
        "inclusion_reason": reason,
    }


def _excerpt(content: Mapping[str, Any], remaining: int) -> tuple[str, bool]:
    """Render a deterministic, byte-bounded advisory passage."""
    if remaining <= 0:
        return "", True
    title = str(content.get("title", ""))
    summary = str(content.get("summary", ""))
    body = str(content.get("body_markdown", ""))
    value = f"{title}\n{summary}\n{body}".strip()
    raw = value.encode("utf-8")
    if len(raw) <= remaining:
        return value, False
    clipped = raw[: max(0, remaining - len("…".encode("utf-8")))].decode("utf-8", "ignore") + "…"
    return clipped, True


class VisionContextService:
    """Authenticated, read-only Vision context plus ordinary DAT snapshots."""

    def __init__(
        self,
        queries: VisionQueryService,
        *,
        packets: Any = None,
        actor: Any = None,
        roles: Sequence[str] = (),
        scopes: Sequence[ResourceRef] = (),
    ) -> None:
        if not isinstance(queries, VisionQueryService):
            raise TypeError("VisionContextService requires a VisionQueryService")
        self.queries = queries
        self.packets = packets or getattr(queries, "resolver", None)
        if self.packets is None or not callable(getattr(self.packets, "read_packet", None)):
            raise TypeError("VisionContextService requires the existing ContextPacketService")
        self.actor = actor if actor is not None else queries.actor
        if self.actor is None:
            raise TypeError("VisionContextService requires an authenticated actor")
        self.roles = tuple(roles or queries.roles)
        self.scopes = tuple(scopes or queries.scopes)

    def _access(self, *, project_ref: Any = None) -> tuple[Any, tuple[ResourceRef, ...]]:
        project = None if project_ref is None else _ref(project_ref, "project_ref")
        if project is None:
            return self.actor, self.scopes
        if not self.queries._grant_allows(project):
            raise VisionAuthorizationError("unsupported_scope: project grant is required")
        return self.actor, tuple(dict.fromkeys((*self.scopes, project)))

    def _read_exact(self, ref: ResourceRef, *, project_ref: Any = None) -> Optional[Mapping[str, Any]]:
        """Read one exact Vision revision with current authorization recheck."""
        project = None if project_ref is None else _ref(project_ref, "project_ref")
        if project is not None and not self.queries._membership_allows(project, ref):
            return None
        try:
            item = self.queries._resolve(ref, project_ref=project)
        except VisionQueryError:
            return None
        return item

    def _projection_from_items(
        self,
        root_ref: ResourceRef,
        items: Sequence[Mapping[str, Any]],
        *,
        scope: str,
        omissions: Sequence[Mapping[str, Any]] = (),
    ) -> VisionProjection:
        nodes = {_identity_key(item["ref"]): item for item in items}
        ordered = [nodes[key] for key in sorted(nodes)]
        basis = [{"ref": i["ref"].to_dict(), "revision": i["revision_ref"].to_dict(), "digest": i["digest"]} for i in ordered]
        content_bytes = sum(len(canonical_json(i["content"]).encode("utf-8")) for i in ordered)
        metadata_bytes = sum(len(canonical_json(i["document"]).encode("utf-8")) for i in ordered)
        if len(ordered) > 129 or content_bytes > 129 * 32768:
            raise VisionContextError("collection_limit_exceeded: exact snapshot exceeds the admitted scan bound")
        coverage = {
            "scope": scope,
            "complete": not omissions,
            "partial": bool(omissions),
            "authorized_nodes": len(ordered),
            "omissions": tuple(_json_copy(item) for item in omissions),
            "output_truncated": False,
        }
        return VisionProjection(
            root_ref,
            next((item["revision_ref"] for item in ordered if _identity(item["ref"]) == _identity(root_ref)), root_ref),
            nodes,
            _digest(basis),
            coverage,
            {
                "read_class": "snapshot",
                "content_reads": len(ordered),
                "metadata_reads": len(ordered),
                "content_bytes_read": content_bytes,
                "metadata_bytes_read": metadata_bytes,
                "bytes_read": content_bytes + metadata_bytes,
                "owner_round_trips": len(ordered),
                "storage_round_trips": len(ordered),
                "event_scans": 0,
                "project_history_scanned": False,
                "latency_ms": 0,
                "declared_node_limit": 129,
                "declared_content_bytes": 129 * 32768,
            },
            tuple(),
        )

    def _current_projection(self, root_ref: Any, *, project_ref: Any = None) -> VisionProjection:
        return self.queries.project(root_ref, project_ref=project_ref)

    def _packet_content(self, snapshot_ref: Any, *, project_ref: Any = None) -> Mapping[str, Any]:
        packet_ref = _exact_ref(snapshot_ref, "snapshot_ref")
        try:
            _, scopes = self._access(project_ref=project_ref)
            read = self.packets.read_packet(packet_ref, actor=self.actor, roles=self.roles, scopes=scopes)
        except (AccessDeniedError, UnresolvedReferenceError, PacketError) as exc:
            raise VisionSnapshotUnavailable("document_unavailable: snapshot is not readable") from exc
        content = read.get("content") if isinstance(read, Mapping) else None
        if not isinstance(content, Mapping) or content.get("record_type") != "dat.context.packet":
            raise VisionSnapshotUnavailable("bad_request: snapshot_ref is not a Vision context packet")
        vision = content.get("responsibility", {}).get("vision") if isinstance(content.get("responsibility"), Mapping) else None
        if not isinstance(vision, Mapping) or vision.get("schema") != SNAPSHOT_SCHEMA:
            raise VisionSnapshotUnavailable("bad_request: snapshot_ref is not a Vision snapshot")
        return content

    def _projection_from_snapshot(self, snapshot_ref: Any, *, root_ref: Any = None, project_ref: Any = None) -> VisionProjection:
        packet = self._packet_content(snapshot_ref, project_ref=project_ref)
        vision = packet["responsibility"]["vision"]
        stored_root = vision.get("root_ref")
        if root_ref is not None and stored_root is not None:
            requested_root = _ref(root_ref, "root_ref")
            if _identity(requested_root) != _identity(_ref(stored_root, "snapshot.root_ref")):
                raise VisionContextError("bad_request: root_ref does not match snapshot root")
        inputs = list(packet.get("inputs", ()))
        items: list[Mapping[str, Any]] = []
        omissions: list[Mapping[str, Any]] = []
        for index, raw in enumerate(inputs):
            value = raw.get("resolved_ref") if isinstance(raw, Mapping) else None
            try:
                exact = _exact_ref(value, f"snapshot.inputs[{index}]")
            except VisionContextError:
                omissions.append({"code": "partial_coverage", "field": f"inputs[{index}]"})
                continue
            item = self._read_exact(exact, project_ref=project_ref)
            if item is None:
                omissions.append({"code": "document_unavailable", "field": f"inputs[{index}]"})
            else:
                items.append(item)
        if not items:
            raise VisionSnapshotUnavailable("document_unavailable: no snapshot sources are currently readable")
        root = _ref(stored_root, "snapshot.root_ref") if stored_root is not None else items[0]["ref"]
        root_item = next((item for item in items if _identity(item["ref"]) == _identity(root)), None)
        if root_item is None:
            raise VisionSnapshotUnavailable("document_unavailable: snapshot root is not currently readable")
        # A root-only packet intentionally keeps the old root exact while
        # following its current child bindings. A collection packet uses only
        # its stored exact vector and therefore remains historically stable.
        if vision.get("root_only"):
            current_children: list[Mapping[str, Any]] = [root_item]
            for index, raw in enumerate(root_item["content"].get("members", ())):
                binding = ReferenceBinding.from_dict(raw)
                child = self._read_exact(binding.ref, project_ref=project_ref)
                if child is not None:
                    current_children.append(child)
                else:
                    omissions.append({"code": "document_unavailable", "field": f"root.members[{index}]"})
            items = current_children
        return self._projection_from_items(root, items, scope=str(vision.get("scope", "snapshot")), omissions=omissions)

    @staticmethod
    def _candidate_order(projection: VisionProjection, focus_refs: Sequence[ResourceRef], repository_refs: Sequence[ResourceRef]) -> tuple[list[tuple[str, Mapping[str, Any], str]], list[Mapping[str, Any]]]:
        nodes = projection.nodes
        ordered: list[tuple[str, Mapping[str, Any], str]] = []
        included: set[str] = set()
        omitted: list[Mapping[str, Any]] = []

        def add(ref: ResourceRef, reason: str) -> None:
            key = _identity_key(ref)
            item = nodes.get(key)
            if item is None or key in included:
                return
            included.add(key)
            ordered.append((key, item, reason))

        add(projection.root_ref, "root")
        for focus in focus_refs:
            add(focus, "focus")
        # At most three navigation ancestors per focus.
        for focus in focus_refs:
            current = focus
            for distance in range(1, 4):
                item = nodes.get(_identity_key(current))
                parent = item["content"].get("navigation_parent") if item else None
                if not parent:
                    break
                current = _target_ref(parent)
                add(current, f"navigation_ancestor:{distance}")
        # Direct semantic links from selected focus pages.
        for focus in focus_refs:
            item = nodes.get(_identity_key(focus))
            if not item:
                continue
            content = item["content"]
            for edge in content.get("relationships", ()):
                add(_target_ref(edge["target"]), f"related:{edge['relation']}")
            for repo in content.get("applies_to", ()):
                add(_target_ref(repo), "applicable_repository")
        for repo in repository_refs:
            add(repo, "selected_repository")
        return ordered, omitted

    @staticmethod
    def _edges(projection: VisionProjection, selected: set[str]) -> list[dict[str, Any]]:
        edges: dict[str, dict[str, Any]] = {}
        for item in projection.nodes.values():
            source_key = _identity_key(item["ref"])
            if source_key not in selected:
                continue
            content = item["content"]
            links: list[tuple[str, str, Any]] = []
            if content.get("navigation_parent"):
                links.append(("parent", "navigation-parent", content["navigation_parent"]))
            links.extend(("applies_to", f"applies-to-{index}", value) for index, value in enumerate(content.get("applies_to", ())))
            links.extend((edge["relation"], edge["id"], edge["target"]) for edge in content.get("relationships", ()))
            for relation, edge_id, binding in links:
                target = _target_ref(binding)
                target_key = _identity_key(target)
                if target_key not in selected:
                    continue
                key = canonical_json({"source": item["ref"], "relation": relation, "edge_id": edge_id, "target": target})
                edges[key] = {
                    "edge_id": edge_id,
                    "relation": relation,
                    "source_ref": item["ref"].to_dict(),
                    "source_revision_ref": item["revision_ref"].to_dict(),
                    "target_ref": target.to_dict(),
                    "target_visible": True,
                }
        return [edges[key] for key in sorted(edges)]

    def _context_from_projection(
        self,
        projection: VisionProjection,
        *,
        focus_refs: Sequence[Any],
        question: str,
        repository_refs: Sequence[Any] = (),
        implementation_context: Any = None,
        direction_context: Any = None,
        task_context: Any = None,
    ) -> Mapping[str, Any]:
        if not isinstance(question, str) or len(question) > 2000:
            raise VisionContextError("bad_request: question must be at most 2000 characters")
        if not isinstance(focus_refs, Sequence) or isinstance(focus_refs, (str, bytes)) or not 1 <= len(focus_refs) <= MAX_FOCUS:
            raise VisionContextError("bad_request: context requires 1..3 focus_refs")
        focus = [_ref(value, f"focus_refs[{index}]") for index, value in enumerate(focus_refs)]
        repositories = [_ref(value, f"repository_refs[{index}]") for index, value in enumerate(repository_refs)]
        if len(repositories) > 3:
            raise VisionContextError("bad_request: at most three repository_refs are supported")
        if any(_identity_key(value) not in projection.nodes for value in focus):
            raise VisionContextError("document_unavailable: focus is outside the authorized context projection")
        ordered, _ = self._candidate_order(projection, focus, repositories)
        omissions: list[Mapping[str, Any]] = []
        selected = ordered[:MAX_CONTEXT_NODES]
        for key, item, reason in ordered[MAX_CONTEXT_NODES:]:
            omissions.append({"code": "context_node_limit", "ref": item["ref"].to_dict(), "reason": reason})
        selected_keys = {key for key, _, _ in selected}
        edges = self._edges(projection, selected_keys)
        if len(edges) > MAX_CONTEXT_EDGES:
            for edge in edges[MAX_CONTEXT_EDGES:]:
                omissions.append({"code": "context_edge_limit", "ref": edge["source_ref"], "reason": "edge_budget"})
            edges = edges[:MAX_CONTEXT_EDGES]
        rendered_parts: list[str] = []
        nodes: list[dict[str, Any]] = []
        remaining = MAX_RENDERED_BYTES
        for key, item, reason in selected:
            excerpt, truncated = _excerpt(item["content"], remaining)
            rendered_parts.append(excerpt)
            remaining -= len(excerpt.encode("utf-8"))
            nodes.append(_content_item(item, reason=reason, excerpt=excerpt, truncated=truncated))
        rendered = "\n\n".join(part for part in rendered_parts if part)
        rendered_raw = rendered.encode("utf-8")
        if len(rendered_raw) > MAX_RENDERED_BYTES:
            rendered = rendered_raw[:MAX_RENDERED_BYTES].decode("utf-8", "ignore")
        result: dict[str, Any] = {
            "schema": CONTEXT_SCHEMA,
            "status": "partial" if projection.coverage.get("partial") or omissions else "ok",
            "question": question,
            "root_ref": projection.root_ref.to_dict(),
            "root_revision_ref": projection.root_revision.to_dict(),
            "nodes": nodes,
            "edges": edges,
            "basis_digest": projection.basis_digest,
            "coverage": _json_copy(projection.coverage),
            "omissions": [_json_copy(value) for value in omissions],
            "rendered_intent": rendered,
            "rendered_intent_bytes": len(rendered.encode("utf-8")),
            "implementation_context": _json_copy(implementation_context or {"status": "not_supplied", "items": []}),
            "direction_context": _json_copy(direction_context or {"status": "not_supplied", "items": []}),
            "task_context": _json_copy(task_context or {"status": "not_supplied", "items": []}),
            "latest_only": True,
            "child_view": "latest",
            "history_actions": ["show_history", "create_checkpoint"],
            "root_actions": ["show_history", "create_checkpoint"],
            "root_actions_prominent": True,
            "provider_called": False,
            "effects_started": False,
            "metrics": _json_copy(projection.metrics),
        }
        if len(canonical_json(result).encode("utf-8")) > MAX_CONTEXT_JSON_BYTES:
            raise VisionContextError("response_limit_exceeded: context JSON exceeded the admitted 64 KiB bound")
        return result

    def context(
        self,
        root_ref: Any,
        focus_refs: Sequence[Any],
        question: str,
        *,
        repository_refs: Sequence[Any] = (),
        project_ref: Any = None,
        snapshot_ref: Any = None,
        implementation_context: Any = None,
        direction_context: Any = None,
        task_context: Any = None,
        implementation: Any = None,
        direction: Any = None,
        task: Any = None,
    ) -> Mapping[str, Any]:
        if snapshot_ref is None:
            projection = self._current_projection(root_ref, project_ref=project_ref)
        else:
            projection = self._projection_from_snapshot(snapshot_ref, root_ref=root_ref, project_ref=project_ref)
        result = self._context_from_projection(
            projection,
            focus_refs=focus_refs,
            question=question,
            repository_refs=repository_refs,
            implementation_context=implementation_context if implementation_context is not None else implementation,
            direction_context=direction_context if direction_context is not None else direction,
            task_context=task_context if task_context is not None else task,
        )
        return result

    read_context = context

    def query_snapshot(self, snapshot_ref: Any, preset: str, *, root_ref: Any = None, project_ref: Any = None, limit: int = 32, after_key: Any = None, basis_digest: Optional[str] = None, arguments: Optional[Mapping[str, Any]] = None, **keyword_arguments: Any) -> Mapping[str, Any]:
        projection = self._projection_from_snapshot(snapshot_ref, root_ref=root_ref, project_ref=project_ref)
        if root_ref is None:
            root_ref = projection.root_ref
        if preset not in PRESETS:
            raise VisionContextError("bad_request: unsupported Vision query preset")
        query_arguments = dict(arguments or {})
        query_arguments.update(keyword_arguments)
        if basis_digest is not None and basis_digest != projection.basis_digest:
            return self.queries._error_result(projection, "basis_changed", "query basis changed; restart from the first page")
        rows = self.queries._query_rows(projection, preset, query_arguments)
        page, next_key = self.queries._page(rows, limit=limit, after_key=after_key, basis_digest=projection.basis_digest)
        response = self.queries._result(projection, page, next_key)
        if len(canonical_json(response).encode("utf-8")) > 128 * 1024:
            return self.queries._error_result(projection, "response_limit_exceeded", "query response exceeded the admitted 128 KiB bound")
        return response

    def history(self, document_ref: Any, *, before_revision: Any = None, limit: int = DEFAULT_HISTORY_LIMIT, project_ref: Any = None) -> Mapping[str, Any]:
        if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise VisionContextError(f"bad_request: history limit must be between 1 and {MAX_HISTORY_LIMIT}")
        document = _ref(document_ref, "document_ref")
        current = self._read_exact(document, project_ref=project_ref)
        if current is None:
            raise VisionSnapshotUnavailable("document_unavailable: document is not readable")
        if before_revision is None:
            cursor = current["revision_ref"]
        elif isinstance(before_revision, ResourceRef):
            cursor = _exact_ref(before_revision, "before_revision")
        elif isinstance(before_revision, Mapping):
            cursor = _exact_ref(before_revision, "before_revision")
        else:
            cursor = _exact_ref(replace(document, revision=before_revision), "before_revision")
        if _identity(cursor) != _identity(document):
            raise VisionContextError("bad_request: before_revision must identify document_ref")
        reader = getattr(self.queries.resolver, "reader", None)
        revisions: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        while cursor is not None and len(revisions) < limit:
            if cursor.revision in seen:
                raise VisionContextError("revision_history_invalid: revision chain cycles")
            seen.add(cursor.revision)
            record = reader.get_record(revision_identity(document, cursor.revision)) if reader is not None else None
            payload = getattr(record, "payload", None)
            if not isinstance(payload, Mapping):
                raise VisionContextError("revision_history_unavailable: immutable revision is missing")
            revisions.append({
                "revision_ref": cursor.to_dict(),
                "parent_ref": _revision_ref(document, payload["parent_revision"]).to_dict() if payload.get("parent_revision") else None,
                "content_digest": payload.get("content_digest"),
                "author": _json_copy(payload.get("author")),
                "initial": bool(payload.get("initial", False)),
            })
            parent = payload.get("parent_revision")
            cursor = _revision_ref(document, parent) if isinstance(parent, str) and parent else None
        return {
            "schema": "vision.history.v1",
            "status": "ok",
            "document_ref": document.to_dict(),
            "latest_ref": current["revision_ref"].to_dict(),
            "revisions": revisions,
            "count": len(revisions),
            "complete": cursor is None,
            "next_before_revision": cursor.to_dict() if cursor is not None else None,
            "latest_only_default": before_revision is None and limit == DEFAULT_HISTORY_LIMIT,
            "read_only": True,
            "provider_called": False,
            "effects_started": False,
        }

    read_history = history

    def _requested_fingerprint(self, *, scope: str, root_ref: Any, focus_refs: Sequence[Any], document_ref: Any, input_refs: Sequence[Any], label: str) -> str:
        return _request_digest({
            "scope": scope,
            "root_ref": _copy(root_ref),
            "focus_refs": [_copy(value) for value in focus_refs],
            "document_ref": _copy(document_ref),
            "input_refs": [_copy(value) for value in input_refs],
            "label": label,
        })

    def _existing_request(self, request_key: str, fingerprint: str) -> Optional[Mapping[str, Any]]:
        reader = getattr(self.packets, "reader", None)
        receipt = reader.get_receipt(request_key) if reader is not None else None
        if receipt is None:
            return None
        result_ref = getattr(receipt, "result_ref", None)
        if result_ref is None:
            return None
        packet = self._packet_content(result_ref)
        vision = packet["responsibility"]["vision"]
        if vision.get("request_fingerprint") != fingerprint:
            raise VisionContextError("replay_conflict: request key was already bound to a different snapshot input")
        return {"outcome": "replayed", "snapshot_ref": result_ref.to_dict(), "packet": packet, "coverage": vision.get("coverage", {})}

    def save_snapshot(
        self,
        *,
        scope: str,
        request_key: str,
        label: str = "",
        root_ref: Any = None,
        focus_refs: Sequence[Any] = (),
        document_ref: Any = None,
        input_refs: Sequence[Any] = (),
        project_ref: Any = None,
        allow_partial: bool = False,
    ) -> Mapping[str, Any]:
        if scope not in {"document", "decision", "collection"}:
            raise VisionContextError("unsupported_scope: snapshot scope must be document, decision, or collection")
        if not isinstance(request_key, str) or not request_key.strip():
            raise VisionContextError("bad_request: snapshot request_key is required")
        if not isinstance(label, str) or len(label) > 160:
            raise VisionContextError("bad_request: snapshot label must be at most 160 characters")
        focus = tuple(focus_refs or ())
        explicit = tuple(input_refs or ())
        fingerprint = self._requested_fingerprint(scope=scope, root_ref=root_ref, focus_refs=focus, document_ref=document_ref, input_refs=explicit, label=label)
        replay = self._existing_request(request_key, fingerprint)
        if replay is not None:
            return replay

        omissions: list[Mapping[str, Any]] = []
        root = None if root_ref is None else _ref(root_ref, "root_ref")
        if scope == "document":
            target = _ref(document_ref if document_ref is not None else (focus[0] if len(focus) == 1 else root), "document_ref")
            item = self._read_exact(target, project_ref=project_ref)
            if item is None:
                raise VisionSnapshotUnavailable("document_unavailable: document input is not readable")
            items = [item]
            stored_root = root.to_dict() if root is not None else target.to_dict()
            root_only = root is not None and _identity(root) == _identity(target)
        elif scope == "decision":
            refs = explicit or focus
            if not refs or len(refs) > MAX_CONTEXT_NODES:
                raise VisionContextError("bad_request: decision snapshot requires 1..8 input_refs or focus_refs")
            identities = {_identity(_ref(value, f"input_refs[{index}]")) for index, value in enumerate(refs)}
            if len(identities) != len(refs):
                raise VisionContextError("bad_request: decision snapshot inputs must be unique")
            items = []
            for index, value in enumerate(refs):
                item = self._read_exact(_ref(value, f"input_refs[{index}]"), project_ref=project_ref)
                if item is None:
                    omissions.append({"code": "document_unavailable", "field": f"input_refs[{index}]"})
                else:
                    items.append(item)
            stored_root = root.to_dict() if root is not None else (items[0]["ref"].to_dict() if items else None)
            root_only = False
        else:
            if root is None:
                raise VisionContextError("bad_request: collection snapshot requires root_ref")
            projection = self._current_projection(root, project_ref=project_ref)
            items = list(projection.nodes.values())
            omissions.extend(projection.coverage.get("omissions", ()))
            stored_root = projection.root_ref.to_dict()
            root_only = False
        if omissions and not allow_partial:
            raise VisionSnapshotUnavailable("partial_coverage: snapshot inputs are unavailable; set allow_partial to save a partial packet")
        if not items:
            raise VisionSnapshotUnavailable("document_unavailable: no authorized snapshot inputs")
        if len(items) > MAX_HISTORICAL_INPUTS and scope != "collection":
            raise VisionContextError("collection_limit_exceeded: decision snapshot may pin at most 8 inputs")
        exact_inputs = [item["revision_ref"] for item in sorted(items, key=lambda item: _identity_key(item["ref"]))]
        coverage = {
            "scope": scope,
            "complete": not omissions,
            "partial": bool(omissions),
            "authorized_nodes": len(exact_inputs),
            "omissions": [_json_copy(value) for value in omissions],
            "global_instant_claim": False,
            "roster_resolved_first": scope == "collection",
        }
        manifest = [
            {"ref": item.to_dict(), "digest": next(source["digest"] for source in items if source["revision_ref"] == item)}
            for item in exact_inputs
        ]
        vision = {
            "schema": SNAPSHOT_SCHEMA,
            "scope": scope,
            "label": label,
            "root_ref": stored_root,
            "root_only": root_only,
            "manifest": manifest,
            "coverage": coverage,
            "request_fingerprint": fingerprint,
            "capture_basis": _digest(manifest),
        }
        responsibility = {
            "vision": vision,
            "scope_coverage": coverage,
            "omissions": coverage["omissions"],
        }
        provenance = {
            "source": "dat.context.packet",
            "schema": SNAPSHOT_SCHEMA,
            "exact_refs_and_digests": manifest,
            "observed_revision_vector": manifest,
            "global_instant_claim": False,
        }
        actor = self.actor
        if not isinstance(actor, AuthenticatedActor):
            raise VisionContextError("unauthorized: snapshot save requires an authenticated actor")
        packet_id = "vision-snapshot-" + hashlib.sha256(request_key.encode("utf-8")).hexdigest()[:40]
        context = TransactionContext(actor, request_key, _request_digest({"fingerprint": fingerprint, "manifest": manifest}))
        try:
            result = self.packets.create_packet(
                packet_id,
                context,
                exact_inputs,
                responsibility=responsibility,
                provenance=provenance,
                visibility="private",
                maintainer=actor.actor,
                roles=self.roles,
                scopes=self.scopes,
            )
        except Exception as exc:
            # The ordinary DAT command path owns replay/conflict classification;
            # keep the Vision surface explicit without swallowing the cause.
            if "replay" in str(exc).lower() or "changed" in str(exc).lower():
                raise VisionContextError("replay_conflict: snapshot request key was reused with changed input") from exc
            raise
        return {
            "schema": SNAPSHOT_SCHEMA,
            "outcome": "created",
            "snapshot_ref": result["packet_ref"].to_dict(),
            "packet_ref": result["packet_ref"].to_dict(),
            "scope": scope,
            "coverage": coverage,
            "manifest": manifest,
            "global_instant_claim": False,
            "receipt": _json_copy(result.get("receipt")),
            "provider_called": False,
            "effects_started": True,
        }

    create_checkpoint = save_snapshot
    checkpoint = save_snapshot
    snapshot = save_snapshot

    def read_snapshot(self, snapshot_ref: Any, *, project_ref: Any = None) -> Mapping[str, Any]:
        packet = self._packet_content(snapshot_ref, project_ref=project_ref)
        vision = packet["responsibility"]["vision"]
        items = []
        omissions = []
        for index, raw in enumerate(packet.get("inputs", ())):
            exact = _exact_ref(raw.get("resolved_ref"), f"snapshot.inputs[{index}]")
            item = self._read_exact(exact, project_ref=project_ref)
            if item is None:
                omissions.append({"code": "document_unavailable", "field": f"inputs[{index}]"})
            else:
                items.append(item)
        if omissions:
            return {
                "schema": SNAPSHOT_SCHEMA,
                "status": "partial",
                "snapshot_ref": _exact_ref(snapshot_ref, "snapshot_ref").to_dict(),
                "scope": vision.get("scope"),
                "coverage": {**_json_copy(vision.get("coverage", {})), "complete": False, "partial": True, "omissions": omissions},
                "omissions": omissions,
                "content": [],
                "read_only": True,
                "provider_called": False,
                "effects_started": False,
            }
        return {
            "schema": SNAPSHOT_SCHEMA,
            "status": "ok",
            "snapshot_ref": _exact_ref(snapshot_ref, "snapshot_ref").to_dict(),
            "scope": vision.get("scope"),
            "coverage": _json_copy(vision.get("coverage", {})),
            "manifest": _json_copy(vision.get("manifest", [])),
            "content": [
                {"ref": item["ref"].to_dict(), "revision_ref": item["revision_ref"].to_dict(), "digest": item["digest"], "content": _json_copy(item["content"])}
                for item in items
            ],
            "read_only": True,
            "provider_called": False,
            "effects_started": False,
        }


__all__ = [
    "CONTEXT_SCHEMA", "DEFAULT_HISTORY_LIMIT", "MAX_CONTEXT_EDGES", "MAX_CONTEXT_JSON_BYTES",
    "MAX_CONTEXT_NODES", "MAX_HISTORICAL_INPUTS", "MAX_RENDERED_BYTES", "SNAPSHOT_SCHEMA",
    "VisionContextError", "VisionContextService", "VisionSnapshotUnavailable",
]
