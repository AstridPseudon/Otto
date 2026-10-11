"""Bounded Vision relationship reads over the existing DAT/EDT surface.

The Vision graph is authored in ordinary document revisions.  This module
only resolves one authorized root roster into an exact, per-request projection
and calculates the finite views from that projection.  It deliberately has no
Store, SQL, event, cache, or graph-writing capability.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from herzchen.contracts import (
    AuthenticatedActor,
    ReferenceBinding,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
)
from .model import DocumentAssociation


QUERY_SCHEMA = "vision.query.v1"
PROJECT_DOCUMENTS_NAMESPACE = "project.documents"
MAX_MEMBERS = 128
MAX_SCAN_NODES = MAX_MEMBERS + 1
MAX_CONTENT_BYTES = MAX_SCAN_NODES * 32768
DEFAULT_LIMIT = 32
MAX_LIMIT = 64
MAX_RESPONSE_BYTES = 128 * 1024
PRESETS = (
    "outline",
    "related",
    "by_repository",
    "repositories_for",
    "shared_concepts",
    "search",
    "audit",
)


class VisionQueryError(ValueError):
    """A finite Vision query or projection request is invalid."""


class VisionAuthorizationError(VisionQueryError):
    """The supplied actor, grant, membership, or DAT visibility is invalid."""


def _ref(value: Any, field: str = "reference") -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise VisionQueryError(f"{field} is not a valid ResourceRef") from exc
    raise VisionQueryError(f"{field} is not a valid ResourceRef")


def _binding(value: Any, field: str) -> ReferenceBinding:
    if isinstance(value, ReferenceBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return ReferenceBinding.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise VisionQueryError(f"{field} is not a valid ReferenceBinding") from exc
    raise VisionQueryError(f"{field} is not a valid ReferenceBinding")


def _identity(value: Any) -> tuple[str, str, str]:
    ref = _ref(value)
    return ref.authority, ref.kind, ref.id


def _identity_key(value: Any) -> str:
    authority, kind, ident = _identity(value)
    return canonical_json({"authority": authority, "kind": kind, "id": ident})


def _copy(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if isinstance(value, ReferenceBinding):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_copy(item) for item in value]
    if isinstance(value, AuthenticatedActor):
        return value.to_dict()
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _node_ref(node: Mapping[str, Any]) -> ResourceRef:
    return _ref(node["ref"], "node.ref")


def _target_ref(value: Any) -> ResourceRef:
    return _binding(value, "target").ref


def _authoring_content(read: Any) -> Optional[Mapping[str, Any]]:
    """Extract current or pinned content from both existing DAT read shapes."""
    if not isinstance(read, Mapping) or not isinstance(read.get("content"), Mapping):
        return None
    payload = read["content"]
    direct = payload.get("content")
    if isinstance(direct, Mapping):
        return direct
    revision = payload.get("revision")
    if isinstance(revision, Mapping) and isinstance(revision.get("content"), Mapping):
        return revision["content"]
    return None


def _safe_call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a supplied narrow reader without accepting arbitrary call shapes."""
    try:
        return function(*args, **kwargs)
    except TypeError as first:
        # Test doubles and the existing finite readers expose either the
        # keyword-rich or positional form.  Do not introspect or call twice
        # when the callable accepted the first form and failed internally.
        try:
            signature = inspect.signature(function)
            signature.bind(*args)
        except (TypeError, ValueError):
            raise first
        return function(*args)


@dataclass(frozen=True)
class VisionProjection:
    """One exact authorized root-plus-roster read."""

    root_ref: ResourceRef
    root_revision: ResourceRef
    nodes: Mapping[str, Mapping[str, Any]]
    basis_digest: str
    coverage: Mapping[str, Any]
    metrics: Mapping[str, Any]
    diagnostics: tuple[Mapping[str, Any], ...] = ()


class VisionQueryService:
    """Finite relationship views over one authorized bounded projection.

    ``resolver`` is normally the existing ``ContextPacketService``.  It must
    enforce DAT visibility and return an exact ``resolved`` revision.  For a
    project-scoped agent, ``grant`` and ``membership_reader`` are both
    required; naming a project alone never grants access.
    """

    def __init__(
        self,
        resolver: Any,
        *,
        actor: Any = None,
        roles: Sequence[str] = (),
        scopes: Sequence[ResourceRef] = (),
        grant: Any = None,
        membership_reader: Optional[Callable[..., Any]] = None,
    ) -> None:
        if resolver is None or not callable(getattr(resolver, "resolve_reference", None)):
            raise TypeError("VisionQueryService requires the existing authorized reference resolver")
        self.resolver = resolver
        self.actor = actor
        self.roles = tuple(roles)
        self.scopes = tuple(scopes)
        self.grant = grant
        self.membership_reader = membership_reader
        self._seen_bases: set[str] = set()

    def _grant_allows(self, project_ref: ResourceRef) -> bool:
        grant = self.grant
        if grant is None:
            return False
        allows = getattr(grant, "allows", None)
        if callable(allows):
            return bool(allows(project_ref))
        ids = grant.get("project_ids") if isinstance(grant, Mapping) else getattr(grant, "project_ids", None)
        principal = grant.get("principal") if isinstance(grant, Mapping) else getattr(grant, "principal", None)
        actor_matches = (
            self.actor is None
            or principal is None
            or principal == self.actor
            or principal == getattr(self.actor, "actor", None)
        )
        return (
            project_ref.kind == "work.project"
            and isinstance(ids, (tuple, list))
            and project_ref.id in ids
            and actor_matches
        )

    def _membership_allows(self, project_ref: ResourceRef, document_ref: ResourceRef) -> bool:
        if self.membership_reader is None:
            return False
        result = _safe_call(self.membership_reader, project_ref, document_ref, self.actor)
        if isinstance(result, Mapping):
            if result.get("active") is False:
                return False
            if "allowed" in result:
                return bool(result["allowed"])
            if "outcome" in result:
                return result["outcome"] in {"listed", "read", "active", "allowed"}
        return bool(result)

    def _resolve(
        self,
        requested: ResourceRef,
        *,
        project_ref: Optional[ResourceRef],
    ) -> Optional[Mapping[str, Any]]:
        resolver_reader = getattr(self.resolver, "reader", None)
        resolver_authority = getattr(resolver_reader, "authority", None)
        if resolver_authority is None:
            resolver_authority = getattr(self.resolver, "authority", None)
        if resolver_authority is not None and requested.authority != resolver_authority:
            return None
        if project_ref is not None:
            if project_ref.kind != "work.project" or not self._grant_allows(project_ref):
                raise VisionAuthorizationError("unsupported_scope: project grant is required")
            if not self._membership_allows(project_ref, ResourceRef(requested.authority, requested.kind, requested.id)):
                return None
            scopes = tuple(dict.fromkeys((*self.scopes, project_ref)))
        else:
            scopes = self.scopes
        try:
            result = self.resolver.resolve_reference(
                requested,
                actor=self.actor,
                roles=self.roles,
                scopes=scopes,
            )
        except Exception:
            # Missing, denied, revoked, malformed, and foreign references have
            # one intentionally non-disclosing query result.
            return None
        if not isinstance(result, Mapping) or result.get("foreign"):
            return None
        resolved = result.get("resolved")
        try:
            exact = _ref(resolved, "resolved")
        except VisionQueryError:
            return None
        if exact.revision is None or _identity(exact) != _identity(requested):
            return None
        document = result.get("document")
        content = result.get("content")
        if not isinstance(document, Mapping) or not isinstance(content, Mapping):
            return None
        if document.get("role") != "vision" or content.get("schema") != "vision.node.v1":
            return None
        revision = result.get("revision")
        digest = revision.get("content_digest") if isinstance(revision, Mapping) else None
        if not isinstance(digest, str) or not digest:
            digest = _digest(content)
        return {
            "ref": ResourceRef(exact.authority, exact.kind, exact.id),
            "revision_ref": exact,
            "document": _copy(document),
            "content": _copy(content),
            "digest": digest,
        }

    def project(
        self,
        root_ref: Any,
        *,
        project_ref: Any = None,
    ) -> VisionProjection:
        started = time.perf_counter()
        root = _ref(root_ref, "root_ref")
        project = None if project_ref is None else _ref(project_ref, "project_ref")
        if root.kind != "dat.content.document":
            raise VisionQueryError("root_ref must identify a DAT content document")
        root_item = self._resolve(root, project_ref=project)
        if root_item is None:
            raise VisionAuthorizationError("document_unavailable: root is not visible")
        if root_item["content"].get("kind") != "product":
            raise VisionQueryError("bad_request: root_ref must identify a product root")
        members = root_item["content"].get("members")
        if not isinstance(members, list):
            raise VisionQueryError("schema_invalid: product root has no collection roster")
        if len(members) > MAX_MEMBERS:
            raise VisionQueryError("collection_limit_exceeded: root plus 128 members is the admitted scan bound")

        nodes: dict[str, Mapping[str, Any]] = {_identity_key(root_item["ref"]): root_item}
        omissions: list[Mapping[str, Any]] = []
        for index, raw_binding in enumerate(members):
            binding = _binding(raw_binding, f"members[{index}]")
            if binding.mode != "current" or binding.ref.revision is not None:
                omissions.append({"code": "partial_coverage", "field": f"members[{index}]"})
                continue
            item = self._resolve(binding.ref, project_ref=project)
            if item is None:
                # The authored binding is already visible in the root.  Do not
                # add hidden title, existence, or count data to the response.
                omissions.append({"code": "document_unavailable", "field": f"members[{index}]"})
                continue
            nodes[_identity_key(item["ref"])] = item

        ordered = [nodes[key] for key in sorted(nodes)]
        basis = [
            {
                "ref": item["ref"].to_dict(),
                "revision": item["revision_ref"].to_dict(),
                "digest": item["digest"],
            }
            for item in ordered
        ]
        basis_digest = _digest(basis)
        content_bytes = sum(len(canonical_json(item["content"]).encode("utf-8")) for item in ordered)
        metadata_bytes = sum(len(canonical_json(item["document"]).encode("utf-8")) for item in ordered)
        if content_bytes > MAX_CONTENT_BYTES:
            raise VisionQueryError("collection_limit_exceeded: declared content byte bound exceeded")
        cold_warm = "warm" if basis_digest in self._seen_bases else "cold"
        self._seen_bases.add(basis_digest)
        elapsed = (time.perf_counter() - started) * 1000
        metrics = {
            "read_class": cold_warm,
            "content_reads": len(ordered),
            "metadata_reads": len(ordered),
            "content_bytes_read": content_bytes,
            "metadata_bytes_read": metadata_bytes,
            "bytes_read": content_bytes + metadata_bytes,
            "owner_round_trips": len(ordered),
            "storage_round_trips": len(ordered),
            "event_scans": 0,
            "project_history_scanned": False,
            "latency_ms": round(elapsed, 3),
            "declared_node_limit": MAX_SCAN_NODES,
            "declared_content_bytes": MAX_CONTENT_BYTES,
        }
        coverage = {
            "scope": "root_plus_roster",
            "complete": not omissions,
            "partial": bool(omissions),
            "authorized_nodes": len(ordered),
            "omissions": tuple(omissions),
            "output_truncated": False,
        }
        diagnostics = tuple(diagnose_projection(nodes))
        return VisionProjection(
            ResourceRef(root.authority, root.kind, root.id),
            root_item["revision_ref"],
            nodes,
            basis_digest,
            coverage,
            metrics,
            diagnostics,
        )

    @staticmethod
    def _node_rows(projection: VisionProjection) -> list[dict[str, Any]]:
        rows = []
        for key, item in projection.nodes.items():
            content = item["content"]
            parent = content.get("navigation_parent")
            rows.append({
                "key": key,
                "ref": item["ref"].to_dict(),
                "revision_ref": item["revision_ref"].to_dict(),
                "digest": item["digest"],
                "kind": content.get("kind"),
                "title": content.get("title"),
                "summary": content.get("summary"),
                "parent_ref": _target_ref(parent).to_dict() if parent else None,
                "applies_to": [_target_ref(value).to_dict() for value in content.get("applies_to", ())],
            })
        return sorted(rows, key=lambda row: (str(row["title"]).casefold(), row["key"]))

    @staticmethod
    def _visible_target(projection: VisionProjection, target: ResourceRef) -> Optional[Mapping[str, Any]]:
        return projection.nodes.get(_identity_key(target))

    def _related_rows(self, projection: VisionProjection, node_ref: Any, direction: str, relations: Optional[Iterable[str]]) -> list[dict[str, Any]]:
        target = _ref(node_ref, "node_ref")
        node = projection.nodes.get(_identity_key(target))
        if node is None:
            raise VisionQueryError("document_unavailable: node is outside the authorized projection")
        if direction not in {"in", "out", "both"}:
            raise VisionQueryError("bad_request: direction must be in, out, or both")
        allowed = None if relations is None else set(relations)
        if allowed is not None and not allowed.issubset({"parent", "applies_to", "refines", "contributes_to", "depends_on", "in_tension_with", "supersedes"}):
            raise VisionQueryError("bad_request: relation filter contains an unsupported relation")
        result: dict[str, dict[str, Any]] = {}

        def add(source: Mapping[str, Any], relation: str, edge_id: str, target_value: Any, side: str) -> None:
            if allowed is not None and relation not in allowed:
                return
            destination = _target_ref(target_value)
            visible = self._visible_target(projection, destination)
            key = canonical_json({"source": source["ref"], "relation": relation, "edge_id": edge_id, "target": destination})
            row = {
                "key": key,
                "side": side,
                "relation": relation,
                "edge_id": edge_id,
                "source_ref": source["ref"].to_dict(),
                "target_ref": destination.to_dict(),
                "source_revision_ref": source["revision_ref"].to_dict(),
                "target_visible": visible is not None,
            }
            if visible is not None:
                row["target_title"] = visible["content"].get("title")
                row["target_kind"] = visible["content"].get("kind")
            result[key] = row

        for source in projection.nodes.values():
            content = source["content"]
            source_is_target = _identity(source["ref"]) == _identity(node["ref"])
            parent = content.get("navigation_parent")
            if parent:
                parent_ref = _target_ref(parent)
                if source_is_target and direction in {"out", "both"}:
                    add(source, "parent", "navigation-parent", parent, "out")
                if _identity(parent_ref) == _identity(node["ref"]) and direction in {"in", "both"}:
                    add(source, "parent", "navigation-parent", parent, "in")
            for index, applies in enumerate(content.get("applies_to", ())):
                applies_ref = _target_ref(applies)
                if source_is_target and direction in {"out", "both"}:
                    add(source, "applies_to", f"applies-to-{index}", applies, "out")
                if _identity(applies_ref) == _identity(node["ref"]) and direction in {"in", "both"}:
                    add(source, "applies_to", f"applies-to-{index}", applies, "in")
            for edge in content.get("relationships", ()):
                destination = _target_ref(edge["target"])
                relation = edge["relation"]
                if source_is_target and direction in {"out", "both"}:
                    add(source, relation, edge["id"], edge["target"], "out")
                if _identity(destination) == _identity(node["ref"]) and direction in {"in", "both"}:
                    add(source, relation, edge["id"], edge["target"], "in")
        return sorted(result.values(), key=lambda row: row["key"])

    def _query_rows(self, projection: VisionProjection, preset: str, arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
        if preset == "outline":
            rows = self._node_rows(projection)
            parents = {row["key"]: row["parent_ref"] for row in rows}
            for row in rows:
                depth, current, seen = 0, row["parent_ref"], set()
                while current is not None and _identity_key(current) in parents and _identity_key(current) not in seen:
                    seen.add(_identity_key(current)); depth += 1; current = parents[_identity_key(current)]
                row["depth"] = depth
                row["unplaced"] = row["parent_ref"] is not None and _identity_key(row["parent_ref"]) not in parents
                row["cyclic"] = current is not None and _identity_key(current) == row["key"]
            return rows
        if preset == "related":
            return self._related_rows(projection, arguments.get("node_ref"), arguments.get("direction", "both"), arguments.get("relations"))
        if preset == "by_repository":
            values = arguments.get("repository_refs", arguments.get("repositories"))
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not 1 <= len(values) <= 16:
                raise VisionQueryError("bad_request: by_repository requires 1..16 repository_refs")
            selected = {_identity(value) for value in values}
            match = arguments.get("match", "any")
            if match not in {"any", "all"}:
                raise VisionQueryError("bad_request: match must be any or all")
            kind = arguments.get("kind")
            rows = []
            for row in self._node_rows(projection):
                if kind is not None and row["kind"] != kind:
                    continue
                applied = {_identity(value) for value in row["applies_to"]}
                if (selected & applied and match == "any") or (selected <= applied and match == "all"):
                    row["matched_repository_refs"] = [value for value in row["applies_to"] if _identity(value) in selected]
                    rows.append(row)
            return rows
        if preset == "repositories_for":
            target = _ref(arguments.get("node_ref"), "node_ref")
            item = projection.nodes.get(_identity_key(target))
            if item is None:
                raise VisionQueryError("document_unavailable: node is outside the authorized projection")
            rows = []
            for value in item["content"].get("applies_to", ()):
                repository = self._visible_target(projection, _target_ref(value))
                row = {"key": _identity_key(_target_ref(value)), "repository_ref": _target_ref(value).to_dict(), "visible": repository is not None}
                if repository is not None:
                    row.update(title=repository["content"].get("title"), kind=repository["content"].get("kind"))
                rows.append(row)
            return sorted(rows, key=lambda row: row["key"])
        if preset == "shared_concepts":
            values = arguments.get("repository_refs", arguments.get("repositories"))
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not 2 <= len(values) <= 16:
                raise VisionQueryError("bad_request: shared_concepts requires 2..16 repository_refs")
            selected = {_identity(value) for value in values}
            rows = []
            for item in projection.nodes.values():
                if item["content"].get("kind") != "concept":
                    continue
                matched = [_target_ref(value) for value in item["content"].get("applies_to", ()) if _identity(_target_ref(value)) in selected]
                if len({_identity(value) for value in matched}) >= 2:
                    rows.append({"key": _identity_key(item["ref"]), "ref": item["ref"].to_dict(), "revision_ref": item["revision_ref"].to_dict(), "title": item["content"].get("title"), "matched_repository_refs": [value.to_dict() for value in matched]})
            return sorted(rows, key=lambda row: row["key"])
        if preset == "search":
            text = arguments.get("text", arguments.get("query", arguments.get("q")))
            if not isinstance(text, str) or not 1 <= len(text) <= 160:
                raise VisionQueryError("bad_request: search text must be 1..160 characters")
            needle = text.casefold()
            return [row for row in self._node_rows(projection) if needle in row["title"].casefold() or needle in row["summary"].casefold()]
        if preset == "audit":
            rows = []
            for finding in projection.diagnostics:
                row = {"key": _digest(finding), **_copy(finding)}
                rows.append(row)
            return sorted(rows, key=lambda row: row["key"])
        raise VisionQueryError("bad_request: unsupported Vision query preset")

    @staticmethod
    def _page(rows: list[dict[str, Any]], *, limit: int, after_key: Any, basis_digest: str) -> tuple[list[dict[str, Any]], Any]:
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise VisionQueryError(f"bad_request: limit must be between 1 and {MAX_LIMIT}")
        start = 0
        if after_key is not None:
            if isinstance(after_key, Mapping):
                if after_key.get("basis_digest") != basis_digest:
                    return [], {"status": "basis_changed", "basis_digest": basis_digest}
                token = after_key.get("key")
            else:
                token = after_key
            keys = [row.get("key") for row in rows]
            if token not in keys:
                return [], {"status": "basis_changed", "basis_digest": basis_digest}
            start = keys.index(token) + 1
        page = rows[start:start + limit]
        next_key = None
        if start + len(page) < len(rows) and page:
            next_key = {"basis_digest": basis_digest, "key": page[-1].get("key")}
        return page, next_key

    def query(self, root_ref: Any, preset: str, *, project_ref: Any = None,
              limit: int = DEFAULT_LIMIT, after_key: Any = None,
              basis_digest: Optional[str] = None, arguments: Optional[Mapping[str, Any]] = None,
              snapshot_ref: Any = None,
              **keyword_arguments: Any) -> Mapping[str, Any]:
        if snapshot_ref is not None:
            from .vision_context import VisionContextService
            return VisionContextService(self, packets=self.resolver, actor=self.actor,
                                        roles=self.roles, scopes=self.scopes).query_snapshot(
                snapshot_ref, preset, root_ref=root_ref, project_ref=project_ref,
                limit=limit, after_key=after_key, basis_digest=basis_digest,
                arguments=arguments, **keyword_arguments)
        if preset not in PRESETS:
            raise VisionQueryError("bad_request: unsupported Vision query preset")
        if arguments is not None and not isinstance(arguments, Mapping):
            raise VisionQueryError("bad_request: arguments must be an object")
        query_arguments = dict(arguments or {})
        query_arguments.update(keyword_arguments)
        projection = self.project(root_ref, project_ref=project_ref)
        if basis_digest is not None and basis_digest != projection.basis_digest:
            return self._error_result(projection, "basis_changed", "query basis changed; restart from the first page")
        rows = self._query_rows(projection, preset, query_arguments)
        page, next_key = self._page(rows, limit=limit, after_key=after_key, basis_digest=projection.basis_digest)
        response = self._result(projection, page, next_key)
        if len(canonical_json(response).encode("utf-8")) > MAX_RESPONSE_BYTES:
            return self._error_result(projection, "response_limit_exceeded", "query response exceeded the admitted 128 KiB bound")
        return response

    def _result(self, projection: VisionProjection, rows: Sequence[Mapping[str, Any]], next_key: Any) -> Mapping[str, Any]:
        return {
            "schema": QUERY_SCHEMA,
            "status": "ok",
            "rows": [_copy(row) for row in rows],
            "basis_digest": projection.basis_digest,
            "coverage": _copy(projection.coverage),
            "diagnostics": [_copy(value) for value in projection.diagnostics],
            "next_after_key": _copy(next_key),
            "metrics": _copy(projection.metrics),
            "provider_called": False,
            "effects_started": False,
        }

    def _error_result(self, projection: VisionProjection, code: str, message: str) -> Mapping[str, Any]:
        value = dict(self._result(projection, (), None))
        value["status"] = code
        value["error"] = {"code": code, "message": message}
        value["coverage"] = {**_copy(projection.coverage), "complete": False, "partial": True}
        return value

    def read(self, document_ref: Any, *, project_ref: Any = None) -> Mapping[str, Any]:
        """Read one current Vision node through the same authorized resolver."""
        requested = _ref(document_ref, "document_ref")
        item = self._resolve(requested, project_ref=None if project_ref is None else _ref(project_ref, "project_ref"))
        if item is None:
            raise VisionAuthorizationError("document_unavailable: document is not visible")
        return {
            "schema": "vision.read.v1",
            "status": "ok",
            "ref": item["ref"].to_dict(),
            "revision_ref": item["revision_ref"].to_dict(),
            "digest": item["digest"],
            "document": _copy(item["document"]),
            "content": _copy(item["content"]),
            "read_only": True,
            "provider_called": False,
            "effects_started": False,
        }

    read_node = read

    def context(self, root_ref: Any, focus_refs: Sequence[Any], question: str, **kwargs: Any) -> Mapping[str, Any]:
        """Compose the D04 context surface without adding a second query store."""
        from .vision_context import VisionContextService
        return VisionContextService(self, packets=self.resolver, actor=self.actor,
                                    roles=self.roles, scopes=self.scopes).context(
            root_ref, focus_refs, question, **kwargs)

    read_context = context

    def history(self, document_ref: Any, **kwargs: Any) -> Mapping[str, Any]:
        from .vision_context import VisionContextService
        return VisionContextService(self, packets=self.resolver, actor=self.actor,
                                    roles=self.roles, scopes=self.scopes).history(document_ref, **kwargs)

    read_history = history

    def snapshot(self, **kwargs: Any) -> Mapping[str, Any]:
        from .vision_context import VisionContextService
        return VisionContextService(self, packets=self.resolver, actor=self.actor,
                                    roles=self.roles, scopes=self.scopes).save_snapshot(**kwargs)

    save_snapshot = snapshot
    create_checkpoint = snapshot

    def read_snapshot(self, snapshot_ref: Any, **kwargs: Any) -> Mapping[str, Any]:
        from .vision_context import VisionContextService
        return VisionContextService(self, packets=self.resolver, actor=self.actor,
                                    roles=self.roles, scopes=self.scopes).read_snapshot(snapshot_ref, **kwargs)


def diagnose_projection(nodes: Mapping[str, Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    """Return structural findings without resolving or hydrating any target."""
    if len(nodes) > MAX_SCAN_NODES:
        raise VisionQueryError("collection_limit_exceeded: root plus 128 members exceeded")
    findings: list[Mapping[str, Any]] = []
    parents: dict[str, str] = {}
    for source_key, item in nodes.items():
        content = item["content"]
        parent = content.get("navigation_parent")
        links = [("navigation_parent", parent)] if parent else []
        links += [("applies_to", value) for value in content.get("applies_to", ())]
        links += [(edge["id"], edge["target"]) for edge in content.get("relationships", ())]
        for field, value in links:
            destination = _target_ref(value)
            destination_key = _identity_key(destination)
            if destination_key not in nodes:
                findings.append({"source_ref": item["ref"].to_dict(), "field": field,
                                 "code": "unresolved_or_outside_collection",
                                 "target_ref": destination.to_dict()})
            if field == "navigation_parent":
                parents[source_key] = destination_key
    for source_key in sorted(parents):
        visited: set[str] = set()
        current = source_key
        while current in parents and current not in visited:
            visited.add(current)
            current = parents[current]
        if current == source_key:
            findings.append({"source_ref": nodes[source_key]["ref"].to_dict(), "code": "navigation_cycle"})
    return tuple(findings)


def vision_attachment_key(document_ref: Any) -> str:
    """Stable ordinary-association key; it grants no visibility."""
    ref = _ref(document_ref, "document_ref")
    return "vision-" + hashlib.sha256(canonical_json({"authority": ref.authority, "kind": ref.kind, "id": ref.id}).encode()).hexdigest()[:32]


class VisionAttachment:
    """Owner-composed optional project attachment using existing DAT links."""

    def __init__(self, content: Any, actor: AuthenticatedActor):
        self.content = content
        self.actor = actor

    def apply(self, project_ref: Any, document_refs: Sequence[Any], *, request_id: str, remove: bool = False) -> Mapping[str, Any]:
        project = _ref(project_ref, "project_ref")
        if project.kind != "work.project" or not isinstance(request_id, str) or not request_id.strip():
            raise VisionQueryError("attach requires an owner-local work.project and request_id")
        receipts, pending = [], []
        for index, value in enumerate(document_refs):
            document = _ref(value, f"document_refs[{index}]")
            if document.authority != project.authority:
                pending.append({"document_ref": document.to_dict(), "error": "unsupported_scope"})
                continue
            association = DocumentAssociation(
                ResourceRef(project.authority, project.kind, project.id),
                PROJECT_DOCUMENTS_NAMESPACE,
                vision_attachment_key(document),
                ReferenceBinding(ResourceRef(document.authority, document.kind, document.id), "current"),
            )
            target = ResourceRef(project.authority, "document-association", association.identity)
            operation = "dat.content.unlink" if remove else "dat.content.link"
            payload = {"association": association, "active": not remove}
            digest = canonical_request_digest(
                logical_request_key=f"{request_id}:{index}", operation=operation,
                schema_revision="dat-content.v1", target=target, actor=self.actor,
                payload=payload, context=None,
            )
            context = TransactionContext(self.actor, f"{request_id}:{index}", digest)
            envelope = (self.content.build_unlink if remove else self.content.build_link)(context, association)
            try:
                receipts.append(self.content.execute(envelope))
            except Exception as exc:
                pending.append({"document_ref": document.to_dict(), "error": type(exc).__name__})
        return {
            "schema": "vision.attachment.v1",
            "outcome": "partial" if pending and receipts else "failed" if pending else "removed" if remove else "attached",
            "receipts": tuple(_copy(receipt) for receipt in receipts),
            "pending": tuple(pending),
            "visibility_changed": False,
            "dispatch": False,
        }


class VisionReorganizer:
    """Thin D03 edit helper that keeps CAS and identity in EDT/DAT.

    It changes only the supplied Vision content fields.  Alias movement and
    collection membership remain ordinary association operations owned by the
    existing project/document services; this class never mirrors them into a
    second graph.
    """

    EDITABLE_FIELDS = frozenset({
        "title", "summary", "maturity", "as_of", "horizon", "body_markdown",
        "navigation_parent", "applies_to", "relationships", "sources", "work_refs",
        "repository", "members",
    })

    def __init__(self, authoring: Any, actor: AuthenticatedActor):
        if authoring is None or not callable(getattr(authoring, "open_owned", None)):
            raise TypeError("VisionReorganizer requires the existing EDT authoring handler")
        self.authoring = authoring
        self.actor = actor

    def update(self, document_ref: Any, changes: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        ref = _ref(document_ref, "document_ref")
        if ref.revision is not None or not isinstance(changes, Mapping) or not changes:
            raise VisionQueryError("reorganization requires an unpinned document and nonempty changes")
        unknown = set(changes) - self.EDITABLE_FIELDS
        if unknown:
            raise VisionQueryError("reorganization cannot change schema, definition, kind, or document identity")
        material = self.authoring.open_owned(ref, self.actor, request_id=request_id + ":open")
        if getattr(material.open_result, "handle", None) is None:
            return {
                "schema": "vision.reorganization.v1", "outcome": "unavailable",
                "document_ref": ref.to_dict(), "pending": True,
                "error": _copy(getattr(material, "refusal_receipt", None)),
            }
        current = _authoring_content(self.authoring.read(ref, self.actor))
        if not isinstance(current, Mapping) or current.get("schema") != "vision.node.v1":
            raise VisionQueryError("document_unavailable: current document is not a Vision node")
        proposed = dict(current)
        proposed.update(_copy(changes))
        result = self.authoring.finish(material, draft={"content": proposed}, request_id=request_id + ":finish")
        applied = getattr(result, "applied", None)
        finish = getattr(result, "finish", None)
        status = getattr(finish, "status", None)
        failure = getattr(finish, "failure_status", None)
        if applied is None:
            return {
                "schema": "vision.reorganization.v1", "outcome": "conflict" if failure == "conflict" else "rejected",
                "document_ref": ref.to_dict(), "base_revision_ref": material.handle.base_revision,
                "pending": True, "error": failure or status,
                "stable_id_preserved": True, "permissions_unchanged": True,
            }
        new_revision = applied.revision.ref
        return {
            "schema": "vision.reorganization.v1", "outcome": "updated",
            "document_ref": ref.to_dict(),
            "old_revision_ref": ResourceRef(ref.authority, ref.kind, ref.id, material.handle.base_revision).to_dict(),
            "new_revision_ref": new_revision.to_dict(),
            "stable_id_preserved": True,
            "permissions_unchanged": True,
            "incoming_links_retargeted_by_identity": True,
            "receipt": _copy(getattr(applied, "receipt", None)),
            "partial": False,
        }

    def move_alias(
        self,
        alias_service: Any,
        *,
        project_ref: Any,
        from_alias: str,
        to_alias: str,
        request_id: str,
        interrupt_at: Optional[str] = None,
    ) -> Mapping[str, Any]:
        """Use the existing ordinary alias port without changing Vision content.

        The alias implementation remains owned by its existing host service;
        this adapter only supplies the authenticated actor and preserves the
        service's moved/partial receipt.  An alias is a locator, never a
        semantic Vision edge or a visibility grant.
        """
        mover = getattr(alias_service, "move_alias", None)
        if not callable(mover):
            raise VisionQueryError("alias move requires the existing alias operation")
        if not isinstance(from_alias, str) or not isinstance(to_alias, str) or not from_alias or not to_alias:
            raise VisionQueryError("alias move requires nonempty aliases")
        result = mover(
            project_ref=_ref(project_ref, "project_ref"),
            from_alias=from_alias,
            to_alias=to_alias,
            actor=self.actor,
            logical_request_key=request_id,
            interrupt_at=interrupt_at,
        )
        if not isinstance(result, Mapping):
            raise VisionQueryError("alias operation returned no receipt")
        return {
            "schema": "vision.reorganization.v1",
            "operation": "alias_move",
            "outcome": result.get("outcome", "unknown"),
            "from_alias": from_alias,
            "to_alias": to_alias,
            "canonical_preserved": result.get("canonical_preserved", True),
            "stable_id_preserved": True,
            "permissions_unchanged": True,
            "receipt": _copy(result),
            "partial_receipts_are_truthful": result.get("outcome") == "partial" or result.get("outcome") == "moved",
        }

    def transfer_collection(
        self,
        source_root: Any,
        target_root: Any,
        document_ref: Any,
        *,
        request_id: str,
    ) -> Mapping[str, Any]:
        """Transfer roster membership using two ordinary root CAS revisions.

        Inclusion commits first.  If removal cannot commit, the returned
        receipt truthfully leaves the document in both roots and names the
        remaining step; no document or semantic link is deleted.
        """
        source = _ref(source_root, "source_root")
        target = _ref(target_root, "target_root")
        document = _ref(document_ref, "document_ref")
        if source.authority != target.authority or source.kind != target.kind or source.id == target.id:
            raise VisionQueryError("collection transfer requires distinct roots in one authority")
        if document.revision is not None:
            raise VisionQueryError("collection transfer requires a current document identity")
        binding = ReferenceBinding(document, "current").to_dict()
        receipts: list[Mapping[str, Any]] = []

        def edit_root(root: ResourceRef, operation: str) -> Mapping[str, Any]:
            material = self.authoring.open_owned(root, self.actor, request_id=f"{request_id}:{operation}:open")
            if getattr(material.open_result, "handle", None) is None:
                return {"operation": operation, "outcome": "unavailable", "pending": True,
                        "error": _copy(getattr(material, "refusal_receipt", None))}
            base = ResourceRef(root.authority, root.kind, root.id, material.handle.base_revision)
            read = self.authoring.read(base, self.actor)
            current = _authoring_content(read)
            if not isinstance(current, Mapping) or current.get("kind") != "product" or not isinstance(current.get("members"), list):
                raise VisionQueryError("schema_invalid: collection transfer requires product roots")
            members = list(current["members"])
            identities = {_identity(_binding(item, "root member").ref) for item in members}
            document_identity = _identity(document)
            if operation == "include":
                if document_identity not in identities:
                    members.append(binding)
            elif operation == "remove":
                members = [item for item in members if _identity(_binding(item, "root member").ref) != document_identity]
            else:
                raise VisionQueryError("unsupported collection transfer operation")
            proposed = dict(current)
            proposed["members"] = members
            finished = self.authoring.finish(
                material, draft={"content": proposed}, request_id=f"{request_id}:{operation}:finish"
            )
            applied = getattr(finished, "applied", None)
            finish = getattr(finished, "finish", None)
            if applied is None:
                return {"operation": operation, "outcome": "conflict", "pending": True,
                        "error": getattr(finish, "failure_status", None) or getattr(finish, "status", None),
                        "root_ref": root.to_dict()}
            return {"operation": operation, "outcome": "applied", "pending": False,
                    "root_ref": root.to_dict(), "receipt": _copy(getattr(applied, "receipt", None))}

        included = edit_root(target, "include")
        receipts.append(included)
        if included["outcome"] != "applied":
            return {"schema": "vision.reorganization.v1", "operation": "collection_transfer",
                    "outcome": "partial", "document_ref": document.to_dict(),
                    "receipts": tuple(receipts), "pending_step": "include", "stable_id_preserved": True,
                    "partial_receipts_are_truthful": True}
        removed = edit_root(source, "remove")
        receipts.append(removed)
        return {"schema": "vision.reorganization.v1", "operation": "collection_transfer",
                "outcome": "transferred" if removed["outcome"] == "applied" else "partial",
                "document_ref": document.to_dict(), "receipts": tuple(receipts),
                "pending_step": None if removed["outcome"] == "applied" else "remove",
                "stable_id_preserved": True, "partial_receipts_are_truthful": True}

    @staticmethod
    def collection_transfer_plan(source_root: Any, target_root: Any, document_ref: Any) -> Mapping[str, Any]:
        """Describe the two existing CAS edits without performing either write."""
        source = _ref(source_root, "source_root")
        target = _ref(target_root, "target_root")
        document = _ref(document_ref, "document_ref")
        return {
            "schema": "vision.reorganization.v1",
            "operation": "collection_transfer",
            "document_ref": document.to_dict(),
            "steps": [
                {"operation": "include", "root_ref": target.to_dict(), "document_ref": document.to_dict()},
                {"operation": "remove", "root_ref": source.to_dict(), "document_ref": document.to_dict()},
            ],
            "stable_id_preserved": True,
            "partial_receipts_are_truthful": True,
            "writes_performed": False,
        }


__all__ = [
    "DEFAULT_LIMIT", "MAX_CONTENT_BYTES", "MAX_LIMIT", "MAX_MEMBERS", "MAX_RESPONSE_BYTES",
    "PRESETS", "PROJECT_DOCUMENTS_NAMESPACE", "QUERY_SCHEMA", "VisionAttachment",
    "VisionAuthorizationError", "VisionProjection", "VisionQueryError", "VisionQueryService",
    "VisionReorganizer", "diagnose_projection", "vision_attachment_key",
]
