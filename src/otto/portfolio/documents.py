"""Finite, permission-aware project document reads over Herzchen owners.

This adapter owns no document data.  ``ProjectSheet.export`` supplies the
project/task membership edges, ``ContextPacketService`` applies the existing
visibility policy and resolves current/pinned bindings, and
``ContentCommandHandler.read`` returns the exact immutable revision bytes.
Revision history follows the owner's immutable ``parent_revision`` chain and
is always bounded by the caller's requested limit.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence


MAX_READ_MANY = 50
MAX_REVISION_PAGE = 100


class ProjectDocumentError(ValueError):
    """Invalid finite document request."""


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return result if isinstance(result, Mapping) else {}
    return {}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    if hasattr(value, "value"):
        return _json_value(value.value)
    return str(value)


def _resource_ref(value: Any, *, field: str = "reference") -> Any:
    """Convert a public ref-shaped value to the paired owner's ResourceRef."""
    from herzchen.contracts import ResourceRef

    if isinstance(value, ResourceRef):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if not isinstance(value, Mapping):
        raise ProjectDocumentError(f"{field} must be a ResourceRef mapping")
    try:
        return ResourceRef.from_dict(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectDocumentError(f"{field} is invalid") from exc


def _identity(ref: Any) -> tuple[str, str, str]:
    return (ref.authority, ref.kind, ref.id)


def _unavailable(code: str = "document_unavailable") -> dict[str, Any]:
    # Keep the response deliberately indistinguishable for foreign, missing,
    # cross-project and private documents; the reason could disclose existence.
    return {
        "outcome": "unavailable",
        "read_only": True,
        "dispatch": False,
        "launch": False,
        "error": {
            "code": code,
            "message": "the document is not available in this project and visibility scope",
        },
    }


class ProjectDocumentReader:
    """Read a finite project document collection through canonical owners.

    ``sheet_reader`` is Herzchen's ProjectSheet public read port,
    ``content_reader`` is DAT's ContentCommandHandler public read port, and
    ``visibility_reader`` is Herzchen's ContextPacketService public resolver.
    They are injected by the owner bootstrap; this class never opens a Store.
    """

    def __init__(self, *, sheet_reader: Any, content_reader: Any, visibility_reader: Any):
        if sheet_reader is None or content_reader is None or visibility_reader is None:
            raise ValueError("ProjectSheet, ContentCommandHandler, and visibility readers are required")
        self.sheet_reader = sheet_reader
        self.content_reader = content_reader
        self.visibility_reader = visibility_reader

    @staticmethod
    def _sheet_view(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            result = to_dict()
            if isinstance(result, Mapping):
                return result
        raise ProjectDocumentError("ProjectSheet returned no readable view")

    def _export(self, project_ref: Any, task_refs: Optional[Sequence[Any]]) -> tuple[Any, Mapping[str, Any]]:
        ref = _resource_ref(project_ref, field="project_ref")
        kwargs = {} if task_refs is None else {"task_refs": tuple(task_refs)}
        view = self._sheet_view(self.sheet_reader.export(ref, **kwargs))
        return ref, view

    @staticmethod
    def _binding(value: Any) -> tuple[Any, str]:
        from herzchen.contracts import ReferenceBinding

        if isinstance(value, ReferenceBinding):
            binding = value
        else:
            data = _mapping(value)
            try:
                binding = ReferenceBinding.from_dict(data)
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectDocumentError("ProjectSheet returned an invalid document binding") from exc
        return binding.ref, binding.mode

    def _resolve(self, value: Any, *, actor: Any, roles: Sequence[str], scopes: Sequence[Any]) -> Mapping[str, Any]:
        return _mapping(self.visibility_reader.resolve_reference(value, actor=actor, roles=tuple(roles), scopes=tuple(scopes)))

    @staticmethod
    def _membership_scopes(project_ref: Any, memberships: Sequence[Mapping[str, Any]]) -> list[Any]:
        scopes = [_resource_ref(project_ref, field="project_ref")]
        for membership in memberships:
            try:
                subject = _resource_ref(membership.get("subject_ref"), field="subject_ref")
            except ProjectDocumentError:
                continue
            if _identity(subject) not in {_identity(value) for value in scopes}:
                scopes.append(subject)
        return scopes

    def _association(self, association_ref: Any) -> Mapping[str, Any]:
        from herzchen.contracts import ResourceRef

        ref = _resource_ref(association_ref, field="association_ref")
        # Association rows are mutable link identities, not DAT content
        # revisions. ProjectSheet returns the current identity ref carrying
        # its owner revision; read the identity projection without that token.
        result = _mapping(self.content_reader.read(ResourceRef(ref.authority, ref.kind, ref.id)))
        payload = _mapping(result.get("payload"))
        association = _mapping(payload.get("association"))
        if not association:
            # WRK task-sheet links use the DAT public payload's flat shape;
            # legacy project links wrap the same fields in "association".
            association = payload
        return {"ref": ref, "payload": payload, "association": association}

    @staticmethod
    def _subject_allowed(subject: Any, project_ref: Any, task_refs: set[tuple[str, str, str]]) -> bool:
        try:
            ref = _resource_ref(subject, field="subject_ref")
        except ProjectDocumentError:
            return False
        return _identity(ref) == _identity(project_ref) or _identity(ref) in task_refs

    def list_documents(
        self,
        project_ref: Any,
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> dict[str, Any]:
        """Return all visible project/task-linked documents, deduplicated.

        The output contains every active association as membership provenance,
        including each current or exact-pinned binding. Documents failing the
        owner visibility resolver are omitted; callers can use ``read_document``
        to receive a non-disclosing explicit unavailable result.
        """
        from herzchen.contracts import ResourceRef

        try:
            project, view = self._export(project_ref, task_refs)
        except Exception:
            return {**_unavailable("project_or_task_unavailable"), "documents": []}

        project_view = _mapping(view.get("project"))
        project_view_ref = project_view.get("ref")
        if project_view_ref is not None:
            try:
                project = _resource_ref(project_view_ref, field="project_ref")
            except ProjectDocumentError:
                pass

        tasks = view.get("tasks", ())
        task_scope_refs: list[Any] = []
        task_identities: set[tuple[str, str, str]] = set()
        if isinstance(tasks, (tuple, list)):
            for task in tasks:
                task_ref_value = _mapping(task).get("ref")
                try:
                    task_ref = _resource_ref(task_ref_value, field="task_ref")
                except ProjectDocumentError:
                    continue
                task_scope_refs.append(task_ref)
                task_identities.add(_identity(task_ref))
        scopes = (project, *task_scope_refs)

        docs: dict[tuple[str, str, str], dict[str, Any]] = {}
        raw_documents = view.get("documents", ())
        if not isinstance(raw_documents, (tuple, list)):
            return {**_unavailable("project_documents_unavailable"), "documents": []}
        for raw in raw_documents:
            item = _mapping(raw)
            try:
                association = self._association(item.get("association"))
                assoc_data = association["association"]
                if association["payload"].get("active") is False:
                    continue
                subject_value = assoc_data.get("subject")
                if not self._subject_allowed(subject_value, project, task_identities):
                    continue
                binding_ref, binding_mode = self._binding(assoc_data.get("document", item.get("binding")))
                if binding_mode == "current" and binding_ref.revision is not None:
                    continue
                if binding_mode == "pinned" and binding_ref.revision is None:
                    continue
                resolved = self._resolve(
                    {"ref": binding_ref.to_dict(), "mode": binding_mode},
                    actor=actor, roles=roles, scopes=scopes,
                )
                if resolved.get("foreign"):
                    # Owner-local content cannot authenticate or return a
                    # foreign read. Keep only the authorized local membership.
                    visible_document: Mapping[str, Any] = {}
                    exact_ref = binding_ref
                    external = True
                else:
                    visible_document = _mapping(resolved.get("document"))
                    exact_value = resolved.get("resolved")
                    exact_ref = _resource_ref(exact_value, field="resolved_revision")
                    external = False
                base_ref = ResourceRef(binding_ref.authority, binding_ref.kind, binding_ref.id)
                key = _identity(base_ref)
                target = docs.setdefault(key, {
                    "document_ref": base_ref.to_dict(),
                    "current_revision_ref": None,
                    "document": _json_value(visible_document),
                    "memberships": [],
                    "read_state": "unavailable_external_owner" if external else "available",
                })
                if not external:
                    # Resolve the actual current head independently of a
                    # membership's pinned historical version.
                    current = self._resolve(base_ref, actor=actor, roles=roles, scopes=scopes)
                    current_ref = _resource_ref(current.get("resolved"), field="current_revision")
                    target["current_revision_ref"] = current_ref.to_dict()
                    target["document"] = _json_value(_mapping(current.get("document")))
                membership = {
                    "association_ref": _json_value(association["ref"]),
                    "subject_ref": _json_value(_resource_ref(subject_value, field="subject_ref")),
                    "subject_kind": "project" if _identity(_resource_ref(subject_value)) == _identity(project) else "task",
                    "namespace": assoc_data.get("namespace"),
                    "key": assoc_data.get("key"),
                    "access_mode": assoc_data.get("access_mode"),
                    "binding": {"ref": binding_ref.to_dict(), "mode": binding_mode},
                    "resolved_revision_ref": exact_ref.to_dict(),
                    "membership_kind": "evidence_link" if "evidence" in str(assoc_data.get("namespace", "")).lower() or "evidence" in str(assoc_data.get("key", "")).lower() or _mapping(visible_document).get("role") == "evidence" else "document_link",
                }
                if membership not in target["memberships"]:
                    target["memberships"].append(membership)
            except Exception:
                # Do not disclose a malformed, missing or inaccessible target.
                # The explicit read operation below reports unavailable to a
                # caller who already has a reference.
                continue
        return {
            "outcome": "listed",
            "project_ref": project.to_dict(),
            "documents": [docs[key] for key in sorted(docs)],
            "count": len(docs),
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def list_metadata(self, project_ref: Any, *, actor: Any, exact_role: str,
                      representation=None, format=None, cursor: str = "", limit: int = 50,
                      roles: Sequence[str] = (), task_refs: Sequence[Any] = ()) -> dict[str, Any]:
        """Shared bounded listing; no ProjectSheet export or body resolver."""
        try:
            return _json_value(self.content_reader.list_metadata(_resource_ref(project_ref),
                actor=actor, exact_role=exact_role, representation=representation, format=format,
                cursor=cursor, limit=limit, roles=tuple(roles), task_refs=tuple(task_refs)))
        except PermissionError:
            return {**_unavailable(), "documents": []}

    def _visible_document(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: Any,
        roles: Sequence[str],
        task_refs: Optional[Sequence[Any]],
    ) -> tuple[Any, Any, Mapping[str, Any]] | None:
        from herzchen.contracts import ResourceRef

        try:
            requested = _resource_ref(document_ref, field="document_ref")
            listed = self.list_documents(project_ref, actor=actor, roles=roles, task_refs=task_refs)
            if listed.get("outcome") != "listed":
                return None
            item = next((item for item in listed["documents"] if _identity(_resource_ref(item["document_ref"])) == _identity(requested)), None)
            if item is None:
                return None
            return requested, item, {"document": item.get("document", {}), "memberships": item.get("memberships", [])}
        except Exception:
            return None

    def read_document(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> dict[str, Any]:
        """Read the current or exact pinned revision of a visible project doc."""
        visible = self._visible_document(project_ref, document_ref, actor=actor, roles=roles, task_refs=task_refs)
        if visible is None:
            return _unavailable()
        requested, item, provenance = visible
        scopes = self._membership_scopes(project_ref, provenance["memberships"])
        if requested.revision is None:
            permission_ref: Any = requested
        else:
            permission_ref = requested
        try:
            resolved = self._resolve(permission_ref, actor=actor, roles=roles, scopes=scopes)
            if resolved.get("foreign"):
                return _unavailable()
            exact = _resource_ref(resolved.get("resolved"), field="resolved_revision")
            if _identity(exact) != _identity(requested) or exact.revision is None:
                return _unavailable()
            content = _mapping(self.content_reader.read(exact))
            if not content or content.get("content") is None and content.get("revision") is None:
                return _unavailable()
            revision_payload = _mapping(content.get("revision"))
            body = _json_value(content.get("content", revision_payload.get("content")))
            digest = revision_payload.get("content_digest")
            if not isinstance(digest, str) or not digest:
                digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            memberships = [m for m in item.get("memberships", ()) if m.get("resolved_revision_ref", {}).get("revision") == requested.revision] if requested.revision else item.get("memberships", ())
            return {
                "outcome": "read",
                "document_ref": requested.to_dict() if requested.revision is None else {"authority": requested.authority, "kind": requested.kind, "id": requested.id},
                "revision_ref": exact.to_dict(),
                "content": body,
                "content_digest": digest,
                "memberships": _json_value(memberships or provenance["memberships"]),
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }
        except Exception:
            return _unavailable()

    def read_many(
        self,
        project_ref: Any,
        document_refs: Sequence[Any],
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> dict[str, Any]:
        """Read a bounded ordered batch; each denied/missing item is explicit."""
        if isinstance(document_refs, (str, bytes)) or not isinstance(document_refs, Sequence):
            raise ProjectDocumentError("document_refs must be a sequence")
        if len(document_refs) > MAX_READ_MANY:
            return {
                "outcome": "rejected",
                "items": [],
                "read_only": True,
                "error": {"code": "read_many_limit_exceeded", "message": f"at most {MAX_READ_MANY} document references may be read at once"},
            }
        items = []
        for index, ref in enumerate(document_refs):
            result = self.read_document(project_ref, ref, actor=actor, roles=roles, task_refs=task_refs)
            items.append({"position": index, **result})
        return {"outcome": "read_many", "items": items, "count": len(items), "read_only": True, "dispatch": False, "launch": False}

    def list_revisions(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
        limit: int = MAX_REVISION_PAGE,
        start_revision_ref: Any = None,
    ) -> dict[str, Any]:
        """Enumerate the immutable parent chain with a hard cap and resume ref.

        Pass the prior page's ``next_revision_ref`` as ``start_revision_ref``
        to continue. Each page revalidates exact revision access through the
        existing visibility/content owners and never scans beyond its limit.
        """
        from herzchen.contracts import ResourceRef

        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_REVISION_PAGE:
            raise ProjectDocumentError(f"limit must be between 1 and {MAX_REVISION_PAGE}")
        visible = self._visible_document(project_ref, document_ref, actor=actor, roles=roles, task_refs=task_refs)
        if visible is None:
            return {**_unavailable(), "revisions": []}
        requested, _item, provenance = visible
        base = ResourceRef(requested.authority, requested.kind, requested.id)
        scopes = self._membership_scopes(project_ref, provenance["memberships"])
        try:
            current = self._resolve(base, actor=actor, roles=roles, scopes=scopes)
            if current.get("foreign"):
                return {**_unavailable(), "revisions": []}
            head = _resource_ref(current.get("resolved"), field="current_revision")
            if _identity(head) != _identity(base) or head.revision is None:
                return {**_unavailable(), "revisions": []}
            if start_revision_ref is None:
                cursor = head
            else:
                cursor = _resource_ref(start_revision_ref, field="start_revision_ref")
                if _identity(cursor) != _identity(base) or cursor.revision is None:
                    return {**_unavailable("revision_cursor_unavailable"), "revisions": []}
            revisions = []
            seen = set()
            while cursor is not None and len(revisions) < limit:
                if cursor.revision in seen:
                    return {**_unavailable("revision_history_invalid"), "revisions": revisions}
                seen.add(cursor.revision)
                permitted = self._resolve(cursor, actor=actor, roles=roles, scopes=scopes)
                if permitted.get("foreign"):
                    return {**_unavailable(), "revisions": revisions}
                read = _mapping(self.content_reader.read(cursor))
                if not read:
                    return {**_unavailable("revision_history_unavailable"), "revisions": revisions}
                # The public ContentCommandHandler read projection intentionally
                # exposes ``revision`` as a revision-name string. The paired
                # visibility resolver returns the canonical immutable revision
                # payload after enforcing actor/role/scope access; use it for
                # ancestry metadata while requiring the public content read to
                # confirm the exact bytes/ref requested.
                revision = _mapping(permitted.get("revision"))
                try:
                    read_ref = _resource_ref(read.get("identity"), field="read_revision")
                except ProjectDocumentError:
                    return {**_unavailable("revision_history_unavailable"), "revisions": revisions}
                if (
                    not revision
                    or _identity(read_ref) != _identity(cursor)
                    or read_ref.revision != cursor.revision
                    or read.get("revision") != cursor.revision
                    or _identity(_resource_ref(revision.get("document"))) != _identity(base)
                    or revision.get("revision") != cursor.revision
                ):
                    return {**_unavailable("revision_history_invalid"), "revisions": revisions}
                revisions.append({
                    "revision_ref": cursor.to_dict(),
                    "parent_revision": revision.get("parent_revision"),
                    "content_digest": revision.get("content_digest"),
                    "author": _json_value(revision.get("author")),
                    "initial": revision.get("initial"),
                })
                parent = revision.get("parent_revision")
                cursor = ResourceRef(base.authority, base.kind, base.id, parent) if isinstance(parent, str) and parent else None
            return {
                "outcome": "listed",
                "document_ref": base.to_dict(),
                "revisions": revisions,
                "count": len(revisions),
                "complete": cursor is None,
                "next_revision_ref": cursor.to_dict() if cursor is not None else None,
                "memberships": _json_value(provenance["memberships"]),
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }
        except Exception:
            return {**_unavailable("revision_history_unavailable"), "revisions": []}


__all__ = ["MAX_READ_MANY", "MAX_REVISION_PAGE", "ProjectDocumentError", "ProjectDocumentReader"]
