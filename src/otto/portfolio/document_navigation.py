"""Finite navigation, diff, authoring, and bundle views over canonical docs.

This module composes the accepted O03 document reader with Herzchen's
DocumentAuthoringHandler and ContextPacketService. It stores no document data,
link index, session token, or export file of its own.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import posixpath
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit, unquote

from herzchen.authoring import DEFAULT_IDLE_SECONDS


# Per-REQUEST bounds: a call scans/exports at most this many documents and
# returns a continuation for the rest. A project itself is not limited.
MAX_SEARCH_DOCUMENTS = 500
MAX_BUNDLE_DOCUMENTS = 50
MAX_DOCUMENT_TEXT_BYTES = 10 * 1024 * 1024  # one document's text, as project_folder.MAX_FILE_BYTES


class DocumentNavigationError(ValueError):
    """A bounded document-navigation request is invalid."""


def _ref(value: Any, *, field: str = "reference") -> Any:
    from herzchen.contracts import ResourceRef

    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise DocumentNavigationError(f"{field} must be a ResourceRef mapping")
    try:
        return ResourceRef.from_dict(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise DocumentNavigationError(f"{field} is invalid") from exc


def _identity(value: Any) -> tuple[str, str, str]:
    ref = _ref(value)
    return ref.authority, ref.kind, ref.id


def _json(value: Any) -> Any:
    from herzchen.contracts import ResourceRef

    if isinstance(value, ResourceRef):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DocumentNavigationError(f"{field} must be non-blank text")
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_TEXT_BYTES:
        raise DocumentNavigationError(f"{field} exceeds the {MAX_DOCUMENT_TEXT_BYTES}-byte limit")
    return value


def _body_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for field in ("body", "text", "markdown"):
            candidate = value.get(field)
            if isinstance(candidate, str):
                return candidate
    return json.dumps(_json(value), ensure_ascii=False, sort_keys=True, indent=2)


def _diff_text(value: Any) -> str:
    """Render the complete immutable content value for an exact diff."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        text_field = next(
            (field for field in ("body", "text", "markdown") if isinstance(value.get(field), str)),
            None,
        )
        if text_field is not None:
            lines = []
            for key in sorted(value):
                item = value[key]
                if key == text_field:
                    lines.append(f"{key}:")
                    lines.extend(item.splitlines())
                else:
                    rendered = json.dumps(_json(item), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    lines.append(f"{key}: {rendered}")
            return "\n".join(lines)
    return json.dumps(_json(value), ensure_ascii=False, sort_keys=True, indent=2)


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


class ProjectDocumentOperations:
    """Read/search/edit/export documents through the existing owner ports.

    ``document_reader`` is O03's project-scoped composition. ``authoring`` is
    Herzchen's DocumentAuthoringHandler public port, and ``context_reader`` is
    ContextPacketService's visibility-aware backlink port.
    """

    def __init__(self, *, document_reader: Any, authoring: Any, context_reader: Any,
                 sheet_reader: Any = None, idle_lifecycle: Any = None):
        if document_reader is None or authoring is None or context_reader is None:
            raise ValueError("O03 document, DAT authoring, and DAT context readers are required")
        self.document_reader = document_reader
        self.authoring = authoring
        self.context_reader = context_reader
        self.sheet_reader = sheet_reader
        # The host supplies the already-composed lifecycle so this navigation
        # facade never creates a second scheduler, Store, lease authority, or
        # authoring history.  A missing lifecycle is an honest composition
        # limitation, not permission to fall back to direct publication.
        self.idle_lifecycle = idle_lifecycle

    @staticmethod
    def _notification(
        status: str,
        *,
        receipt: Any = None,
        error: Optional[str] = None,
        durable: bool = False,
        actions: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Build a host notification only from an owner-durable outcome."""
        receipt_value = _json(receipt)
        receipt_status = receipt_value.get("status") if isinstance(receipt_value, Mapping) else None
        receipt_durable = receipt_status in {"committed", "no-op"}
        is_durable = bool(durable or receipt_durable)
        return {
            "status": status,
            "durable": is_durable,
            "receipt": receipt_value if is_durable else None,
            "error": error if is_durable else None,
            "actions": list(actions),
            "retryable": bool(actions),
            "available": is_durable,
        }

    @staticmethod
    def _publication_boundary(
        status: str,
        *,
        revision_ref: Any = None,
        receipt: Any = None,
        receipt_refs: Sequence[Any] = (),
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Describe DAT publication without implying any later adoption.

        Check-in ends at the immutable DAT revision and its durable receipt.
        Direction, assignment/resource, and invocation-context adoption stay
        separate owner operations; this projection keeps a host notification
        or portable bundle from being mistaken for an adoption event.
        """
        result = {
            "status": status,
            "dat_revision_ref": _json(revision_ref),
            "receipt": _json(receipt),
            "receipt_refs": [_json(value) for value in receipt_refs],
            "direction_adoption": "not_performed",
            "assignment_adoption": "not_performed",
            "resource_adoption": "not_performed",
            "invocation_context": "unchanged",
        }
        if reason is not None:
            result["reason"] = reason
        return result

    def search_documents(
        self,
        project_ref: Any,
        query: str,
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
        limit: int = 100,
        cursor: int = 0,
    ) -> dict[str, Any]:
        """Find visible documents by title, text, role, path key, or task name.

        One call scans at most MAX_SEARCH_DOCUMENTS documents (in document-id
        order) starting at ``cursor``; ``next_cursor`` continues the scan.
        """
        from herzchen.contracts import ResourceRef

        query = _text(query, "query").casefold()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_SEARCH_DOCUMENTS:
            raise DocumentNavigationError(f"limit must be between 1 and {MAX_SEARCH_DOCUMENTS}")
        project = _ref(project_ref, field="project_ref")
        listed = self.document_reader.list_documents(project, actor=actor, roles=roles, task_refs=task_refs)
        if listed.get("outcome") != "listed":
            return {"outcome": "unavailable", "matches": [], "read_only": True}

        task_titles: dict[tuple[str, str, str], str] = {}
        if self.sheet_reader is not None:
            try:
                view = self.sheet_reader.export(project, **({"task_refs": tuple(task_refs)} if task_refs is not None else {}))
                view = _json(view)
                for task in view.get("tasks", ()) if isinstance(view, Mapping) else ():
                    if not isinstance(task, Mapping):
                        continue
                    ref_value = task.get("ref")
                    authored = task.get("authored", {})
                    authored = authored if isinstance(authored, Mapping) else {}
                    title = task.get("title") or task.get("name") or authored.get("title") or authored.get("name") or ""
                    if ref_value and isinstance(title, str):
                        task_titles[_identity(ref_value)] = title
            except Exception:
                # Search remains useful from path/ref/content alone; task
                # aliases are simply unavailable if the scoped sheet read is.
                task_titles = {}

        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise DocumentNavigationError("cursor must be a non-negative document offset")
        documents = sorted(listed.get("documents", ()), key=lambda item: str((item.get("document_ref") or {}).get("id", "")))
        window = documents[cursor:cursor + MAX_SEARCH_DOCUMENTS]
        next_cursor = cursor + len(window) if cursor + len(window) < len(documents) else None
        matches = []
        for item in window:
            document_ref = item.get("document_ref")
            read = self.document_reader.read_document(project, document_ref, actor=actor, roles=roles, task_refs=task_refs,
                                                      listed=listed)
            if read.get("outcome") != "read":
                continue
            doc = item.get("document", {})
            membership_text = []
            task_names = []
            for member in item.get("memberships", ()):
                membership_text.extend((str(member.get("namespace", "")), str(member.get("key", ""))))
                subject = member.get("subject_ref")
                if subject:
                    task_names.extend((str(subject.get("id", "")), task_titles.get(_identity(subject), "")))
            searchable = "\n".join(
                [
                    str(document_ref.get("id", "")),
                    str(doc.get("title", "")) if isinstance(doc, Mapping) else "",
                    str(doc.get("name", "")) if isinstance(doc, Mapping) else "",
                    str(doc.get("role", "")) if isinstance(doc, Mapping) else "",
                    *tuple(_walk_strings(read.get("content"))),
                    *membership_text,
                    *task_names,
                ]
            ).casefold()
            if query in searchable:
                matches.append({
                    "document_ref": _json(document_ref),
                    "revision_ref": _json(read.get("revision_ref")),
                    "content_digest": read.get("content_digest"),
                    "memberships": _json(item.get("memberships", [])),
                    "matched_query": query,
                })
        matches.sort(key=lambda row: (row["document_ref"].get("id", ""), row["revision_ref"].get("revision", "")))
        return {
            "outcome": "listed",
            "project_ref": project.to_dict(),
            "query": query,
            "matches": matches[:limit],
            "count": min(len(matches), limit),
            "truncated": len(matches) > limit,
            "scanned": len(window),
            "next_cursor": next_cursor,
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def resolve_relative_link(
        self,
        project_ref: Any,
        source_document_ref: Any,
        relative_link: str,
        *,
        actor: Any,
        source_path: Optional[str] = None,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> dict[str, Any]:
        """Resolve a preserved relative href against a project membership key."""
        from herzchen.contracts import ResourceRef

        href = _text(relative_link, "relative_link")
        parts = urlsplit(href)
        try:
            link_path = unquote(parts.path, errors="strict")
        except UnicodeError:
            return {"outcome": "unavailable", "reason": "relative_link_required", "read_only": True}
        if parts.scheme or parts.netloc or link_path.startswith("/") or "\\" in link_path or any(ord(char) < 32 for char in link_path):
            return {"outcome": "unavailable", "reason": "relative_link_required", "read_only": True}
        source = _ref(source_document_ref, field="source_document_ref")
        project = _ref(project_ref, field="project_ref")
        listed = self.document_reader.list_documents(project, actor=actor, roles=roles, task_refs=task_refs)
        if listed.get("outcome") != "listed":
            return {"outcome": "unavailable", "read_only": True}
        source_item = next((item for item in listed.get("documents", ()) if _identity(item.get("document_ref")) == _identity(source)), None)
        if source_item is None:
            return {"outcome": "unavailable", "read_only": True}
        path_members = [
            member for member in source_item.get("memberships", ())
            if isinstance(member.get("key"), str) and member.get("key", "").strip()
        ]
        file_members = [member for member in path_members if member.get("namespace") == "project.files"]
        if file_members:
            path_members = file_members
        if source_path is not None:
            source_path = _text(source_path, "source_path").strip()
            path_members = [member for member in path_members if member.get("key") == source_path]
        elif len(path_members) != 1:
            return {"outcome": "ambiguous_source_path", "candidates": [item.get("key") for item in path_members], "read_only": True}
        if len(path_members) != 1:
            return {"outcome": "unavailable", "read_only": True}
        source_path = path_members[0]["key"]
        normalized = (source_path if not link_path else
                      posixpath.normpath(posixpath.join(posixpath.dirname(source_path), link_path)))
        if normalized in {"", ".", ".."} or normalized.startswith("../"):
            return {"outcome": "unavailable", "reason": "relative_link_escapes_project", "read_only": True}
        candidates = []
        for item in listed.get("documents", ()):
            for member in item.get("memberships", ()):
                if member.get("key") == normalized and (not file_members or member.get("namespace") == "project.files"):
                    candidate_ref = _ref(item.get("document_ref"))
                    if _identity(candidate_ref) not in {_identity(value) for value in candidates}:
                        candidates.append(candidate_ref)
        if len(candidates) != 1:
            return {
                "outcome": "unavailable" if not candidates else "ambiguous_link",
                "source_document_ref": source.to_dict(),
                "source_path": source_path,
                "relative_link": href,
                "resolved_path": normalized,
                "read_only": True,
            }
        target_ref = candidates[0]
        read = self.document_reader.read_document(project, target_ref, actor=actor, roles=roles, task_refs=task_refs)
        if read.get("outcome") != "read":
            return {"outcome": "unavailable", "read_only": True}
        backlinks = self.context_reader.visible_backlinks(target_ref, actor=actor, roles=roles, scopes=(project,))
        return {
            "outcome": "resolved",
            "relative_link": href,
            "source_document_ref": source.to_dict(),
            "source_membership_ref": _json(path_members[0].get("association_ref")),
            "resolved_path": normalized,
            "document_ref": target_ref.to_dict(),
            "revision_ref": _json(read.get("revision_ref")),
            "content": _json(read.get("content")),
            "content_digest": read.get("content_digest"),
            "membership_refs": [_json(member.get("association_ref")) for member in read.get("memberships", ())],
            "visible_backlink_count": len(backlinks),
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def diff_revisions(
        self,
        project_ref: Any,
        document_ref: Any,
        older_revision_ref: Any,
        newer_revision_ref: Any,
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> dict[str, Any]:
        """Compare exact authorized immutable revisions as text/JSON lines."""
        document = _ref(document_ref, field="document_ref")
        older = _ref(older_revision_ref, field="older_revision_ref")
        newer = _ref(newer_revision_ref, field="newer_revision_ref")
        if _identity(older) != _identity(document) or _identity(newer) != _identity(document) or not older.revision or not newer.revision:
            raise DocumentNavigationError("both revision refs must be exact revisions of document_ref")
        project = _ref(project_ref, field="project_ref")
        before = self.document_reader.read_document(project, older, actor=actor, roles=roles, task_refs=task_refs)
        after = self.document_reader.read_document(project, newer, actor=actor, roles=roles, task_refs=task_refs)
        if before.get("outcome") != "read" or after.get("outcome") != "read":
            return {"outcome": "unavailable", "read_only": True}
        old_lines = _diff_text(before.get("content")).splitlines()
        new_lines = _diff_text(after.get("content")).splitlines()
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"{document.id}@{older.revision}",
            tofile=f"{document.id}@{newer.revision}",
            lineterm="",
        ))
        encoded = "\n".join(diff)
        return {
            "outcome": "compared",
            "document_ref": document.to_dict(),
            "older_revision_ref": older.to_dict(),
            "newer_revision_ref": newer.to_dict(),
            "older_content_digest": before.get("content_digest"),
            "newer_content_digest": after.get("content_digest"),
            "changed": old_lines != new_lines,
            "added_lines": sum(line.startswith("+") and not line.startswith("+++") for line in diff),
            "removed_lines": sum(line.startswith("-") and not line.startswith("---") for line in diff),
            "diff": encoded,
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def visible_backlinks(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: Any,
        roles: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Use ContextPacketService's permission-filtered backlink operation."""
        project = _ref(project_ref, field="project_ref")
        document = _ref(document_ref, field="document_ref")
        refs = self.context_reader.visible_backlinks(document, actor=actor, roles=roles, scopes=(project,))
        return {"outcome": "listed", "document_ref": document.to_dict(), "backlinks": _json(refs), "count": len(refs), "read_only": True}

    def open_edit(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: Any,
        request_id: str,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> Any:
        """Open one existing Herzchen authoring session for a visible document."""
        project = _ref(project_ref, field="project_ref")
        document = _ref(document_ref, field="document_ref")

        def refuse_scope() -> dict[str, Any]:
            # Keep invisible/missing/foreign inputs indistinguishable at this
            # project boundary, while retaining the refusal in EDT evidence.
            receipt = self.authoring.refuse_edit(
                document, actor, request_id=request_id, reason="scope_ineligible",
            )
            return {"outcome": "ineligible", "reason": "scope_ineligible",
                    "receipt": _json(receipt), "read_only": True,
                    "dispatch": False, "launch": False}

        listed = self.document_reader.list_documents(project, actor=actor, roles=roles, task_refs=task_refs)
        if listed.get("outcome") != "listed":
            return refuse_scope()
        listed_item = next(
            (item for item in listed.get("documents", ()) if _identity(item.get("document_ref")) == _identity(document)),
            None,
        )
        if listed_item is None:
            return refuse_scope()
        read = self.document_reader.read_document(project, document, actor=actor, roles=roles, task_refs=task_refs)
        if read.get("outcome") != "read":
            return refuse_scope()
        materialisation = self.authoring.open_owned(
            document,
            actor,
            request_id=request_id,
        )
        if getattr(getattr(materialisation, "open_result", None), "handle", None) is None:
            opened = getattr(materialisation, "open_result", None)
            if getattr(opened, "status", None) == "ineligible":
                return {"outcome": "ineligible", "reason": opened.error,
                        "projection": _json(materialisation.projection),
                        "receipt": _json(materialisation.refusal_receipt),
                        "read_only": True, "dispatch": False, "launch": False}
            return {"outcome": "unavailable", "authoring_status": getattr(opened, "status", "no_session"), "read_only": True}
        # Preserve the actual owner-issued ephemeral materialisation object;
        # no Otto token/session registry is introduced.
        return materialisation

    def edit_status(self, materialisation: Any, *, actor: Any) -> dict[str, Any]:
        """Read the holder's current owner capability without changing activity."""
        return _json(self.authoring.edit_status(materialisation, actor))

    def session_inventory(self, *, actor: Any, handles: Sequence[Any] = (), project_ref: Any = None) -> dict[str, Any]:
        """Project open/recovery sessions from the canonical authoring owner."""
        inventory = dict(_json(self.authoring.session_inventory(actor, handles=handles)))
        if project_ref is None:
            return inventory
        project = _ref(project_ref, field="project_ref")
        sessions = []
        for item in inventory.get("sessions", ()):
            scope = item.get("scope_ref", {})
            target = item.get("target_ref", {})
            if _identity(scope) == _identity(project) or _identity(target) == _identity(project):
                sessions.append(item)
        inventory["sessions"] = sessions
        inventory["count"] = len(sessions)
        inventory["project_ref"] = project.to_dict()
        return inventory

    def resume_edit(self, document_ref: Any, *, actor: Any, handle: Any, project_ref: Any = None) -> Any:
        """Resume only with the exact owner-issued handle; never take over."""
        document = _ref(document_ref, field="document_ref")
        parent = _ref(project_ref, field="project_ref") if project_ref is not None else None
        return self.authoring.resume(document, actor, handle, parent_scope=parent)

    def discard_edit(self, materialisation: Any, *, actor: Any, request_id: str) -> dict[str, Any]:
        """Explicit nonpublishing discard; retained draft cleanup is separate."""
        result = self.authoring.discard(materialisation, actor, request_id=request_id)
        return {
            "outcome": "discarded" if result.status == "discarded" else result.status,
            "scope_ref": _json(result.scope),
            "session_id": result.session_id,
            "receipt": _json(result.receipt),
            "cleanup_status": result.cleanup.value,
            "nonpublishing": True,
            "dat_revision_advanced": False,
            "recovery_pending": False,
            "failure_status": "discarded",
            "recovery_actions": ["recover_retained_draft"],
            "notification": self._notification("discarded", receipt=result.receipt, durable=bool(result.durable), actions=("recover_retained_draft",)),
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def release_edit(self, materialisation: Any, *, actor: Any, request_id: str) -> dict[str, Any]:
        """Release through EDT's existing owner authority without publication."""
        result = self.authoring.release(materialisation, actor, request_id=request_id)
        return {
            "outcome": result.status,
            "scope_ref": _json(result.scope),
            "session_id": result.session_id,
            "receipt": _json(result.receipt),
            "cleanup_status": result.cleanup.value,
            "nonpublishing": True,
            "dat_revision_advanced": False,
            "failure_status": result.failure_status,
            "recovery_actions": list(result.recovery_actions),
            "notification": self._notification(result.failure_status or result.status, receipt=result.receipt, durable=bool(result.durable), actions=result.recovery_actions),
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def recover_edit(self, materialisation: Any, *, actor: Any) -> dict[str, Any]:
        """Read retained recovery state; recovery never auto-publishes."""
        return dict(_json(self.authoring.recover(materialisation, actor)))

    def recover_session(self, *, actor: Any, session_id: str) -> dict[str, Any]:
        """Recover a named lost-handle session only by explicit owner action."""
        return dict(_json(self.authoring.recover_session(actor, session_id)))

    def discard_session(self, *, actor: Any, session_id: str, request_id: str) -> dict[str, Any]:
        """Discard a named lost-handle session without publication."""
        result = self.authoring.discard_session(actor, session_id, request_id=request_id)
        return {
            "outcome": result.status,
            "scope_ref": _json(result.scope),
            "session_id": result.session_id,
            "receipt": _json(result.receipt),
            "cleanup_status": result.cleanup.value,
            "nonpublishing": True,
            "dat_revision_advanced": False,
            "failure_status": "discarded",
            "recovery_actions": ["recover_retained_draft"],
            "notification": self._notification("discarded", receipt=result.receipt, durable=bool(result.durable), actions=("recover_retained_draft",)),
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def release_session(self, *, actor: Any, session_id: str, request_id: str) -> dict[str, Any]:
        """Release a named lost-handle session without publication."""
        result = self.authoring.release_session(actor, session_id, request_id=request_id)
        return {
            "outcome": result.status,
            "scope_ref": _json(result.scope),
            "session_id": result.session_id,
            "receipt": _json(result.receipt),
            "cleanup_status": result.cleanup.value,
            "nonpublishing": True,
            "dat_revision_advanced": False,
            "failure_status": result.failure_status,
            "recovery_actions": list(result.recovery_actions),
            "notification": self._notification(result.failure_status or result.status, receipt=result.receipt, durable=bool(result.durable), actions=result.recovery_actions),
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def autosave_edit(
        self,
        materialisation: Any,
        editor_buffer: Any,
        *,
        request_id: str,
        content_edit_at: Optional[float] = None,
        activity: str = "editing",
    ) -> dict[str, Any]:
        """Save the editor buffer as a recoverable draft, never as check-in."""
        if not hasattr(materialisation, "handle") or not hasattr(materialisation, "target"):
            raise DocumentNavigationError("materialisation must be the owner-issued document edit session")
        result = self.authoring.autosave(
            materialisation, editor_buffer, request_id=request_id,
            content_edit_at=content_edit_at, activity=activity,
        )
        return {
            "outcome": "autosaved" if result.status == "saved" else result.status,
            "operation": "draft_autosave",
            "target_ref": _json(result.target),
            "scope_ref": _json(result.scope),
            "session_id": result.session_id,
            "changed": result.changed,
            "snapshot_ref": _json(result.snapshot_ref),
            "snapshot_digest": result.snapshot_digest,
            "last_content_edit": result.last_content_edit,
            "nonpublishing": result.nonpublishing,
            "dat_revision_advanced": False,
            "check_in_required": True,
            "publication": self._publication_boundary(
                "not_published", reason="draft_autosave",
            ),
            "recovery_pending": result.recovery_pending,
            "notification": self._notification(
                "draft_autosaved" if result.status in {"saved", "unchanged"} else "recovery_pending",
                receipt=result.receipt, durable=bool(result.durable),
                error=result.error, actions=("retry_autosave", "recover_retained_draft") if result.recovery_pending else (),
            ),
            "error": result.error,
            "read_only": result.status == "unchanged" or result.recovery_pending,
            "dispatch": False,
            "launch": False,
        }

    def idle_close_edit(
        self,
        materialisation: Any,
        *,
        actor: Any,
        request_id: str,
        checkout_root: Any = None,
        registered_files: Optional[Sequence[Any]] = None,
        inactivity_seconds: float = DEFAULT_IDLE_SECONDS,
        last_content_edit: Optional[Any] = None,
        now: Optional[Any] = None,
        quiesce: Any = None,
        writer_check: Any = None,
        settled: Any = True,
        capture_barrier: Any = None,
        fresh_capture: bool = False,
        pending: Optional[bool] = None,
        expected_base_revision: Optional[str] = None,
        writer_identity: Optional[str] = None,
        hook_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Run one host timer/poller attempt through the existing idle boundary.

        This method is intentionally one-shot: the caller owns the timer or
        poll loop.  It never waits, starts a scheduler, or creates a second
        authoring path.  Missing lifecycle, checkout, or quiescence evidence
        inhibits publication and is returned as durable recovery state.
        """
        if not hasattr(materialisation, "handle") or not hasattr(materialisation, "target"):
            raise DocumentNavigationError("materialisation must be the owner-issued document edit session")
        if not isinstance(request_id, str) or not request_id.strip():
            raise DocumentNavigationError("request_id must be non-blank")
        handle = materialisation.handle
        if actor != handle.actor:
            raise DocumentNavigationError("idle check-in actor does not hold the edit session")

        def inhibited(status: str, error: str) -> dict[str, Any]:
            return {
                "outcome": status,
                "status": status,
                "target_ref": _json(materialisation.target),
                "scope_ref": _json(handle.scope),
                "session_id": handle.session_id,
                "idle_seconds": 0.0,
                "last_content_edit": None,
                "durable_checked_in": False,
                "cleanup_pending": False,
                "recovery_pending": True,
                "nonpublishing": True,
                "dat_revision_advanced": False,
                "publication": self._publication_boundary(
                    "not_published", reason=status,
                ),
                "failure_status": status,
                "recovery_actions": ["inspect_recovery", "retry", "discard"],
                "notification": self._notification(status, error=error, durable=False, actions=("inspect_recovery", "retry", "discard")),
                "error": error,
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }

        lifecycle = self.idle_lifecycle
        if lifecycle is None or not callable(getattr(lifecycle, "idle_close", None)):
            return inhibited("recovery_pending", "idle host lifecycle is not composed")
        # An idle poll cannot prove that an editor has stopped writing.  The
        # existing one-shot service accepts either host quiescence contract;
        # require one here rather than treating absent evidence as safe.
        if quiesce is None and writer_check is None:
            return inhibited("writer_active", "writer quiescence is not declared")

        root = checkout_root or getattr(handle, "checkout_path", None)
        if root is None:
            return inhibited("recovery_pending", "checkout root is unavailable")

        try:
            result = lifecycle.idle_close(
                handle,
                request_id=request_id,
                checkout_root=root,
                registered_files=registered_files,
                handler=self.authoring.lifecycle_handler(materialisation, request_id=request_id),
                writer_identity=writer_identity,
                inactivity_seconds=inactivity_seconds,
                last_content_edit=last_content_edit,
                now=now,
                quiesce=quiesce,
                writer_check=writer_check,
                settled=settled,
                capture_barrier=capture_barrier,
                fresh_capture=fresh_capture,
                pending=pending,
                expected_base_revision=expected_base_revision,
                hook_kwargs=hook_kwargs,
            )
        except BaseException as exc:
            return inhibited("recovery_pending", str(exc) or "idle check-in could not be attempted")

        raw_status = getattr(result, "status", "recovery_pending")
        finish = getattr(result, "finish", None)
        finish_status = getattr(finish, "status", None)
        cleanup = getattr(result, "cleanup", None)
        cleanup_status = getattr(getattr(cleanup, "status", None), "value", getattr(cleanup, "status", None))
        failure_status = getattr(result, "failure_status", None) or getattr(getattr(finish, "finish", None), "failure_status", None)
        # ``pending_released`` and ``rejected`` can still reach exact cleanup,
        # but neither advanced the DAT head.  Only a semantic publication (or
        # its durable replay) is reported as a check-in.
        durable_commit = finish_status in {"finished", "already_finished", "replayed"}
        cleanup_pending = raw_status == "cleanup_pending" or (
            durable_commit and cleanup_status not in {None, "complete"}
        )
        checked_in = durable_commit and not cleanup_pending
        if checked_in:
            outcome = "checked_in"
        elif cleanup_pending:
            outcome = "cleanup_pending"
        elif raw_status in {"rejected", "validation_failed"}:
            outcome = "validation_failed"
        elif failure_status == "conflict":
            outcome = "conflict"
        elif failure_status == "writer_active":
            outcome = "writer_active"
        elif finish_status == "pending_released":
            outcome = "released"
        elif finish_status == "rejected":
            outcome = "validation_failed"
        elif raw_status == "writer_active":
            outcome = "writer_active"
        elif raw_status == "not_idle":
            outcome = "not_idle"
        elif raw_status == "already_closed":
            outcome = "already_closed"
        else:
            outcome = "recovery_pending"
        application = getattr(finish, "application", None)
        applied_document = getattr(application, "document", None)
        applied_revision = getattr(application, "revision", None)
        return {
            "outcome": outcome,
            "status": raw_status,
            "target_ref": _json(materialisation.target),
            "scope_ref": _json(handle.scope),
            "session_id": handle.session_id,
            "idle_seconds": getattr(result, "idle_seconds", 0.0),
            "last_content_edit": getattr(result, "last_content_edit", None),
            "finish_status": finish_status,
            "finish": _json(finish),
            "cleanup_status": cleanup_status,
            "cleanup": _json(cleanup),
            "durable_checked_in": checked_in or (cleanup_pending and durable_commit),
            "cleanup_pending": cleanup_pending,
            "recovery_pending": bool(getattr(result, "recovery_pending", False)) or not checked_in and not (cleanup_pending and durable_commit),
            "nonpublishing": not (checked_in or (cleanup_pending and durable_commit)),
            "dat_revision_advanced": bool(durable_commit),
            "publication": self._publication_boundary(
                "committed" if durable_commit else "not_published",
                revision_ref=(
                    {
                        **_json(getattr(applied_document, "ref", None)),
                        "revision": getattr(applied_revision, "revision", None),
                    }
                    if applied_document is not None and applied_revision is not None else None
                ),
                receipt=(getattr(getattr(finish, "finish", None), "receipt", None)),
                receipt_refs=getattr(application, "receipts", ()),
                reason=None if durable_commit else (failure_status or outcome),
            ),
            "failure_status": "checked_in" if checked_in else ("cleanup_pending" if cleanup_pending else failure_status or outcome),
            "recovery_actions": list(getattr(result, "recovery_actions", ()) or getattr(getattr(finish, "finish", None), "recovery_actions", ()) or ()),
            "receipt": _json(getattr(finish, "finish", None) and getattr(getattr(finish, "finish", None), "receipt", None)),
            "notification": self._notification(
                "checked_in" if checked_in else ("cleanup_pending" if cleanup_pending else failure_status or outcome),
                receipt=getattr(getattr(finish, "finish", None), "receipt", None),
                error=getattr(result, "error", None),
                durable=bool(getattr(result, "durable", False) or durable_commit or cleanup_pending),
                actions=tuple(getattr(result, "recovery_actions", ()) or getattr(getattr(finish, "finish", None), "recovery_actions", ()) or ()),
            ),
            "error": getattr(result, "error", None),
            "read_only": not checked_in,
            "dispatch": False,
            "launch": False,
        }

    # Host terminology uses both names in existing design documents.  Both
    # remain the same one-shot boundary; neither starts a background worker.
    idle_checkin_edit = idle_close_edit

    def finish_edit(self, materialisation: Any, draft: Any, *, request_id: str) -> dict[str, Any]:
        """Validate and finish through DocumentAuthoringHandler's edit token."""
        if not hasattr(materialisation, "handle") or not hasattr(materialisation, "target"):
            raise DocumentNavigationError("materialisation must be the owner-issued document edit session")
        # Run the same public owner validator before claiming/finishing the
        # edit session. This leaves the owner-issued session available for a
        # corrected draft instead of turning a schema typo into a durable
        # recovery state.
        from herzchen.content.authoring import SchemaValidationError

        if isinstance(draft, (str, bytes, bytearray)):
            raw = draft
        else:
            raw = json.dumps(_json(draft), ensure_ascii=False, sort_keys=True)

        try:
            self.authoring.validate(
                draft,
                target=materialisation.target,
                document=getattr(materialisation, "document", None),
            )
        except SchemaValidationError as exc:
            retained = None
            failure_receipt = None
            try:
                retained = self.authoring.autosave(
                    materialisation, raw, request_id=request_id + ":rejected-draft",
                    activity="validation_failed",
                )
                if getattr(retained, "durable", False):
                    failure = self.authoring.authoring.record_failure(
                        materialisation.handle,
                        request_id=request_id + ":validation-failure",
                        status="validation_failed",
                        error=str(exc),
                        recovery_actions=("correct_draft", "retry"),
                    )
                    failure_receipt = failure.get("receipt")
            except BaseException:
                retained = None
            return {
                "outcome": "rejected_input",
                "target_ref": _json(getattr(materialisation, "target", None)),
                "finish_status": "not_attempted",
                "schema_errors": list(exc.errors),
                "failure_status": "validation_failed",
                "recovery_actions": ["correct_draft", "retry"],
                "draft_snapshot_ref": _json(getattr(retained, "snapshot_ref", None)),
                "publication": self._publication_boundary(
                    "not_published", reason="validation_failed",
                ),
                "notification": self._notification("validation_failed", receipt=failure_receipt or getattr(retained, "receipt", None), error=str(exc), durable=bool(failure_receipt or getattr(retained, "durable", False)), actions=("correct_draft", "retry")),
                "error": str(exc),
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }
        result = self.authoring.finish(materialisation, request_id=request_id, draft=raw)
        applied = getattr(result, "applied", None)
        finish = getattr(result, "finish", None)
        if applied is not None:
            return {
                "outcome": "applied",
                "target_ref": _json(getattr(applied, "target", None)),
                "scope_ref": _json(getattr(applied, "scope", None)),
                "document_ref": _json(getattr(getattr(applied, "document", None), "ref", None)),
                "revision_ref": {
                    **_json(getattr(getattr(applied, "document", None), "ref", None)),
                    "revision": getattr(getattr(applied, "revision", None), "revision", None),
                },
                "content_digest": getattr(getattr(applied, "revision", None), "content_digest", None),
                "finish_status": getattr(finish, "status", None),
                "cleanup_status": getattr(getattr(finish, "cleanup", None), "value", getattr(finish, "cleanup", None)),
                "cleanup_pending": getattr(getattr(finish, "cleanup", None), "value", getattr(finish, "cleanup", None)) not in {None, "not_requested", "complete"},
                "receipt": _json(getattr(finish, "receipt", None)),
                "receipt_refs": [_json(getattr(receipt, "result_ref", None)) for receipt in getattr(applied, "receipts", ())],
                "publication": self._publication_boundary(
                    "committed",
                    revision_ref={
                        **_json(getattr(getattr(applied, "document", None), "ref", None)),
                        "revision": getattr(getattr(applied, "revision", None), "revision", None),
                    },
                    receipt=getattr(finish, "receipt", None),
                    receipt_refs=getattr(applied, "receipts", ()),
                ),
                "failure_status": "checked_in",
                "notification": self._notification("checked_in", receipt=getattr(finish, "receipt", None), durable=bool(getattr(finish, "durable", False)), actions=()),
                "read_only": False,
                "dispatch": False,
                "launch": False,
            }
        # An exact retry after a lost response is a durable owner replay, not
        # a rejected draft.  Reuse the current canonical DAT head and the
        # retained finish receipt; never invoke the document writer again.
        if finish is not None and getattr(finish, "status", None) in {"replayed", "already_finished"}:
            current = self.authoring.read(materialisation.target).get("content", {})
            current_revision = current.get("current_revision") if isinstance(current, Mapping) else None
            revision_ref = _json(current_revision)
            return {
                "outcome": "replayed" if finish.status == "replayed" else "already_finished",
                "target_ref": _json(getattr(materialisation, "target", None)),
                "scope_ref": _json(getattr(materialisation, "scope", None)),
                "finish_status": finish.status,
                "revision_ref": revision_ref,
                "cleanup_status": getattr(getattr(finish, "cleanup", None), "value", getattr(finish, "cleanup", None)),
                "cleanup_pending": getattr(getattr(finish, "cleanup", None), "value", getattr(finish, "cleanup", None)) not in {None, "not_requested", "complete"},
                "receipt": _json(getattr(finish, "receipt", None)),
                "publication": self._publication_boundary(
                    "committed", revision_ref=current_revision,
                    receipt=getattr(finish, "receipt", None),
                ),
                "failure_status": "checked_in",
                "recovery_actions": [],
                "notification": self._notification(
                    "checked_in", receipt=getattr(finish, "receipt", None),
                    durable=True, actions=(),
                ),
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }
        errors = list(getattr(result, "schema_errors", ()) or ())
        status = getattr(finish, "status", "unknown")
        error = getattr(finish, "error", None)
        failure_status = "validation_failed" if errors else (getattr(finish, "failure_status", None) or ("conflict" if "base revision" in str(error or "").casefold() else "recovery_pending"))
        outcome = "rejected_input" if errors else "conflict" if failure_status == "conflict" else "rejected"
        return {
            "outcome": outcome,
            "target_ref": _json(getattr(materialisation, "target", None)),
            "finish_status": status,
            "schema_errors": errors,
            "failure_status": failure_status,
            "recovery_actions": list(getattr(finish, "recovery_actions", ()) or (("correct_draft", "retry") if failure_status == "validation_failed" else ("inspect_current_revision", "merge_or_retry") if failure_status == "conflict" else ("inspect_recovery", "retry", "discard"))),
            "publication": self._publication_boundary(
                "not_published", reason=failure_status,
            ),
            "notification": self._notification(failure_status, receipt=getattr(finish, "receipt", None), error=error, durable=bool(getattr(finish, "durable", False)), actions=tuple(getattr(finish, "recovery_actions", ()) or ())),
            "error": error,
            "read_only": True,
            "dispatch": False,
            "launch": False,
        }

    def export_bundle(
        self,
        project_ref: Any,
        document_refs: Sequence[Any],
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
    ) -> dict[str, Any]:
        """Return a selected readable JSON bundle with canonical refs/hashes.

        One call exports at most MAX_BUNDLE_DOCUMENTS selected documents; a
        caller with a larger selection pages it (see ``export_bundle_pages``).
        """
        if isinstance(document_refs, (str, bytes)) or not isinstance(document_refs, Sequence):
            raise DocumentNavigationError("document_refs must be a sequence of ResourceRefs")
        if len(document_refs) > MAX_BUNDLE_DOCUMENTS:
            return {
                "outcome": "rejected",
                "files": [],
                "error": {"code": "bundle_selection_limit_exceeded", "limit": MAX_BUNDLE_DOCUMENTS,
                          "message": "page the selection; export_bundle_pages does this"},
                "read_only": True,
            }
        project = _ref(project_ref, field="project_ref")
        listed = self.document_reader.list_documents(project, actor=actor, roles=roles, task_refs=task_refs)
        if listed.get("outcome") != "listed":
            return {"outcome": "unavailable", "files": [], "read_only": True}
        entries = []
        exclusions = {
            "historical_revisions": True,
            "external_assets": True,
            "unselected_documents": True,
            "excluded_historical_revisions": [],
            "unavailable_selected_documents": [],
        }
        seen: set[tuple[str, str, str, Optional[str]]] = set()
        for raw_ref in document_refs:
            requested = _ref(raw_ref, field="document_ref")
            token = (*_identity(requested), requested.revision)
            if token in seen:
                continue
            seen.add(token)
            if requested.revision is not None:
                exclusions["excluded_historical_revisions"].append({
                    "document_ref": requested.to_dict(),
                    "reason": "historical_revision_excluded",
                })
                continue
            item = next((value for value in listed.get("documents", ()) if _identity(value.get("document_ref")) == _identity(requested)), None)
            if item is None:
                exclusions["unavailable_selected_documents"].append({"document_ref": requested.to_dict(), "reason": "not_visible_in_project_scope"})
                continue
            read = self.document_reader.read_document(project, requested, actor=actor, roles=roles, task_refs=task_refs,
                                                      listed=listed)
            if read.get("outcome") != "read":
                exclusions["unavailable_selected_documents"].append({"document_ref": requested.to_dict(), "reason": "unavailable"})
                continue
            content = _json(read.get("content"))
            aliases = sorted({str(member.get("key")) for member in item.get("memberships", ()) if member.get("key")})
            entries.append({
                "paths": aliases or [requested.id],
                "document_ref": _json(read.get("document_ref")),
                "revision_ref": _json(read.get("revision_ref")),
                "content_sha256": hashlib.sha256(_canonical_bytes(content)).hexdigest(),
                "content": content,
                "membership_refs": [_json(member.get("association_ref")) for member in item.get("memberships", ())],
            })
        entries.sort(key=lambda value: (value["paths"][0], value["document_ref"].get("id", "")))
        manifest = {"schema": "otto.project-document-bundle.v1", "project_ref": project.to_dict(), "files": entries, "exclusions": exclusions}
        bundle_hash = hashlib.sha256(_canonical_bytes(manifest)).hexdigest()
        return {"outcome": "exported", **manifest, "bundle_sha256": bundle_hash, "read_only": True, "dispatch": False, "launch": False}


def export_bundle_pages(operations: Any, project_ref: Any, document_refs: Sequence[Any], **options: Any) -> dict[str, Any]:
    """Export any selection in MAX_BUNDLE_DOCUMENTS pages, merged into one bundle.

    Each page is an ordinary export_bundle call. The merged manifest has the
    same schema; its hash covers every page's files and exclusions.
    """
    refs = list(document_refs)
    pages = [refs[index:index + MAX_BUNDLE_DOCUMENTS] for index in range(0, len(refs), MAX_BUNDLE_DOCUMENTS)] or [[]]
    files: list[Any] = []
    exclusions: dict[str, Any] = {}
    project = None
    for page in pages:
        result = operations.export_bundle(project_ref, page, **options)
        if result.get("outcome") != "exported":
            return {**result, "pages_completed": pages.index(page)}
        project = result["project_ref"]
        files.extend(result["files"])
        for key, value in result["exclusions"].items():
            if isinstance(value, list):
                exclusions.setdefault(key, []).extend(value)
            else:
                exclusions[key] = value
    files.sort(key=lambda value: (value["paths"][0], value["document_ref"].get("id", "")))
    manifest = {"schema": "otto.project-document-bundle.v1", "project_ref": project, "files": files,
                "exclusions": exclusions}
    return {"outcome": "exported", **manifest, "bundle_sha256": hashlib.sha256(_canonical_bytes(manifest)).hexdigest(),
            "pages": len(pages), "read_only": True, "dispatch": False, "launch": False}


__all__ = [
    "DocumentNavigationError",
    "export_bundle_pages",
    "MAX_BUNDLE_DOCUMENTS",
    "MAX_DOCUMENT_TEXT_BYTES",
    "MAX_SEARCH_DOCUMENTS",
    "ProjectDocumentOperations",
]
