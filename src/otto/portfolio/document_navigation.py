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
from urllib.parse import urlsplit


MAX_SEARCH_DOCUMENTS = 500
MAX_BUNDLE_DOCUMENTS = 50
MAX_DOCUMENT_TEXT_BYTES = 1_000_000


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

    def __init__(self, *, document_reader: Any, authoring: Any, context_reader: Any, sheet_reader: Any = None):
        if document_reader is None or authoring is None or context_reader is None:
            raise ValueError("O03 document, DAT authoring, and DAT context readers are required")
        self.document_reader = document_reader
        self.authoring = authoring
        self.context_reader = context_reader
        self.sheet_reader = sheet_reader

    def search_documents(
        self,
        project_ref: Any,
        query: str,
        *,
        actor: Any,
        roles: Sequence[str] = (),
        task_refs: Optional[Sequence[Any]] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Find visible documents by title, text, role, path key, or task name."""
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

        documents = listed.get("documents", ())
        if len(documents) > MAX_SEARCH_DOCUMENTS:
            return {
                "outcome": "rejected",
                "matches": [],
                "error": {"code": "search_scope_limit_exceeded", "limit": MAX_SEARCH_DOCUMENTS},
                "read_only": True,
            }
        matches = []
        for item in documents:
            document_ref = item.get("document_ref")
            read = self.document_reader.read_document(project, document_ref, actor=actor, roles=roles, task_refs=task_refs)
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
        if parts.scheme or parts.netloc or parts.path.startswith("/") or "\\" in parts.path:
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
        if source_path is not None:
            source_path = _text(source_path, "source_path").strip()
            path_members = [member for member in path_members if member.get("key") == source_path]
        elif len(path_members) != 1:
            return {"outcome": "ambiguous_source_path", "candidates": [item.get("key") for item in path_members], "read_only": True}
        if len(path_members) != 1:
            return {"outcome": "unavailable", "read_only": True}
        source_path = path_members[0]["key"]
        normalized = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), parts.path))
        if normalized in {"", ".", ".."} or normalized.startswith("../"):
            return {"outcome": "unavailable", "reason": "relative_link_escapes_project", "read_only": True}
        candidates = []
        for item in listed.get("documents", ()):
            for member in item.get("memberships", ()):
                if member.get("key") == normalized:
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
        listed = self.document_reader.list_documents(project, actor=actor, roles=roles, task_refs=task_refs)
        if listed.get("outcome") != "listed":
            return {"outcome": "unavailable", "read_only": True}
        listed_item = next(
            (item for item in listed.get("documents", ()) if _identity(item.get("document_ref")) == _identity(document)),
            None,
        )
        if listed_item is None:
            return {"outcome": "unavailable", "read_only": True}
        try:
            current = _ref(listed_item.get("current_revision_ref"), field="current_revision_ref")
        except DocumentNavigationError:
            return {"outcome": "unavailable", "read_only": True}
        if document.revision is not None and document.revision != current.revision:
            return {"outcome": "conflict", "current_revision_ref": current.to_dict(), "read_only": True}
        read = self.document_reader.read_document(project, document, actor=actor, roles=roles, task_refs=task_refs)
        if read.get("outcome") != "read":
            return {"outcome": "unavailable", "read_only": True}
        materialisation = self.authoring.materialise(
            document,
            actor,
            request_id=request_id,
            base_revision=current.revision,
            initial_content=_json(read.get("content")),
        )
        if getattr(getattr(materialisation, "open_result", None), "handle", None) is None:
            opened = getattr(materialisation, "open_result", None)
            return {"outcome": "unavailable", "authoring_status": getattr(opened, "status", "no_session"), "read_only": True}
        # Preserve the actual owner-issued ephemeral materialisation object;
        # no Otto token/session registry is introduced.
        return materialisation

    def finish_edit(self, materialisation: Any, draft: Any, *, request_id: str) -> dict[str, Any]:
        """Validate and finish through DocumentAuthoringHandler's edit token."""
        if not hasattr(materialisation, "handle") or not hasattr(materialisation, "target"):
            raise DocumentNavigationError("materialisation must be the owner-issued document edit session")
        # Run the same public owner validator before claiming/finishing the
        # edit session. This leaves the owner-issued session available for a
        # corrected draft instead of turning a schema typo into a durable
        # recovery state.
        from herzchen.content.authoring import SchemaValidationError

        try:
            self.authoring.validate(
                draft,
                target=materialisation.target,
                document=getattr(materialisation, "document", None),
            )
        except SchemaValidationError as exc:
            return {
                "outcome": "rejected_input",
                "target_ref": _json(getattr(materialisation, "target", None)),
                "finish_status": "not_attempted",
                "schema_errors": list(exc.errors),
                "error": str(exc),
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }
        if isinstance(draft, (str, bytes, bytearray)):
            raw = draft
        else:
            raw = json.dumps(_json(draft), ensure_ascii=False, sort_keys=True)
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
                "receipt_refs": [_json(getattr(receipt, "result_ref", None)) for receipt in getattr(applied, "receipts", ())],
                "read_only": False,
                "dispatch": False,
                "launch": False,
            }
        errors = list(getattr(result, "schema_errors", ()) or ())
        status = getattr(finish, "status", "unknown")
        error = getattr(finish, "error", None)
        outcome = "rejected_input" if errors else "conflict" if "base revision" in str(error or "").casefold() else "rejected"
        return {
            "outcome": outcome,
            "target_ref": _json(getattr(materialisation, "target", None)),
            "finish_status": status,
            "schema_errors": errors,
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
        """Return a selected readable JSON bundle with canonical refs/hashes."""
        if isinstance(document_refs, (str, bytes)) or not isinstance(document_refs, Sequence):
            raise DocumentNavigationError("document_refs must be a sequence of ResourceRefs")
        if len(document_refs) > MAX_BUNDLE_DOCUMENTS:
            return {
                "outcome": "rejected",
                "files": [],
                "error": {"code": "bundle_selection_limit_exceeded", "limit": MAX_BUNDLE_DOCUMENTS},
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
            read = self.document_reader.read_document(project, requested, actor=actor, roles=roles, task_refs=task_refs)
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


__all__ = [
    "DocumentNavigationError",
    "MAX_BUNDLE_DOCUMENTS",
    "MAX_DOCUMENT_TEXT_BYTES",
    "MAX_SEARCH_DOCUMENTS",
    "ProjectDocumentOperations",
]
