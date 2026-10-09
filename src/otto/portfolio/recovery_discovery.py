"""Bounded owner-backed discovery for recovery and continuation.

This module is deliberately a projection, not a registry.  It joins only
records reachable from an explicitly supplied project, retained checkout, or
retained session locator.  It never searches the filesystem, history, or a
provider transcript and it never performs a resume, replacement, or rebind.
Those actions remain existing owner operations after this read resolves
custody.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Callable, Mapping, Optional, Sequence


SCHEMA = "otto.recovery.find-and-continue.v1"
MAX_LIMIT = 100
MAX_MATCHES = 1000


class RecoveryDiscoveryError(ValueError):
    """A bounded discovery request is malformed."""


def _json(value: Any) -> Any:
    enum_value = getattr(value, "value", None)
    if enum_value is not None and enum_value is not value and isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json(to_dict())
    return str(value)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    value = _json(value)
    if not isinstance(value, Mapping):
        raise RecoveryDiscoveryError(f"{field} must be an object")
    return dict(value)


def _ref(value: Any, field: str = "reference") -> Optional[dict[str, Any]]:
    value = _json(value)
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(value.get(key), str) and value[key].strip()
               for key in ("authority", "kind", "id")):
        return None
    return {key: value[key] for key in ("authority", "kind", "id", "revision")
            if key in value}


def _identity(value: Any) -> Optional[tuple[str, str, str]]:
    ref = _ref(value)
    return None if ref is None else (ref["authority"], ref["kind"], ref["id"])


def _same(left: Any, right: Any) -> bool:
    return _identity(left) is not None and _identity(left) == _identity(right)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        _json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _encode_cursor(*, scope: Any, snapshot: str, offset: int) -> str:
    value = {"scope": _digest(scope), "snapshot": snapshot, "offset": offset}
    return base64.urlsafe_b64encode(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: Optional[str], *, scope: Any, snapshot: str) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor.strip():
        raise RecoveryDiscoveryError("cursor must be non-blank text when supplied")
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RecoveryDiscoveryError("cursor is invalid") from exc
    if (not isinstance(value, Mapping) or value.get("scope") != _digest(scope)
            or value.get("snapshot") != snapshot
            or isinstance(value.get("offset"), bool)
            or not isinstance(value.get("offset"), int)
            or value["offset"] < 0):
        raise RecoveryDiscoveryError("cursor is stale or outside this discovery scope")
    return value["offset"]


def _assignment_ref(value: Any) -> Optional[dict[str, Any]]:
    value = _json(value)
    if not isinstance(value, Mapping):
        return None
    return _ref(value.get("assignment_ref") or value.get("ref") or value)


def _assignment_row(value: Any, *, fallback_ref: Any = None) -> dict[str, Any]:
    payload = _json(getattr(value, "payload", None))
    payload = payload if isinstance(payload, Mapping) else {}
    ref = _ref(getattr(value, "ref", None)) or _assignment_ref(value) or _ref(fallback_ref)
    row = {
        "ref": ref,
        "scope": _ref(getattr(value, "scope", None)) or _ref(payload.get("scope")),
        "role": getattr(value, "role", None) or payload.get("role"),
        "principal": getattr(value, "principal", None) or payload.get("principal"),
        "generation": getattr(value, "generation", None) or payload.get("generation"),
        "status": _json(getattr(value, "status", None) or payload.get("status")),
        "session": _json(getattr(value, "session", None) or payload.get("session")),
        "history": _json(getattr(value, "history", None) or payload.get("history", ())),
    }
    row["ref"] = _json(row["ref"])
    row["scope"] = _json(row["scope"])
    return row


def _location_state(value: Mapping[str, Any]) -> str:
    for key in ("location_state", "verification_state", "state"):
        selected = value.get(key)
        if isinstance(selected, str) and selected.strip():
            normalized = selected.strip().lower().replace("-", "_")
            if normalized in {"verified", "current", "held", "ambiguous", "missing", "moved", "unknown"}:
                return normalized
    if value.get("missing") is True:
        return "missing"
    if value.get("moved") is True:
        return "moved"
    if value.get("verified") is True:
        return "verified"
    return "unknown"


def _location_values(value: Any, *, path: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Extract explicit locator-shaped metadata, never inspect the locator."""
    found: list[dict[str, Any]] = []
    value = _json(value)
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower()
            next_path = f"{path}.{key}" if path else str(key)
            key_parts = set(re.split(r"[^a-z0-9]+", name))
            if key_parts.intersection({"source", "worktree", "checkout", "workspace"}):
                if isinstance(item, Mapping):
                    row = dict(item)
                    row.setdefault("field", next_path)
                    row.setdefault("state", _location_state(row))
                    found.append(row)
                elif isinstance(item, str) and item.strip():
                    found.append({"field": next_path, "locator": item, "state": "unknown"})
            if len(found) >= limit:
                break
            if isinstance(item, (Mapping, list, tuple)):
                found.extend(_location_values(item, path=next_path, limit=limit - len(found)))
                if len(found) >= limit:
                    break
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_location_values(item, path=f"{path}[{index}]", limit=limit - len(found)))
            if len(found) >= limit:
                break
    return found[:limit]


def _native_observation(observer: Any, binding: Any, *, context: Mapping[str, Any]) -> dict[str, Any]:
    if binding is None:
        return {"state": "unknown", "reason": "native_binding_missing", "observed_at": None}
    if observer is None:
        return {"state": "unknown", "reason": "native_observer_unavailable", "observed_at": None}
    try:
        method = getattr(observer, "observe", observer)
        observed = _json(method(binding, **dict(context)))
    except Exception as exc:
        return {"state": "unknown", "reason": "native_observation_error", "error": str(exc), "observed_at": None}
    if not isinstance(observed, Mapping):
        return {"state": "unknown", "reason": "native_observation_malformed", "observed_at": None}
    result = dict(observed)
    result.setdefault("state", "unknown")
    result.setdefault("observed_at", None)
    return result


class BoundedRecoveryDiscovery:
    """Join current owner records for one explicit recovery locator."""

    def __init__(self, *, operations: Any, document_operations: Any = None,
                 due_port: Any = None, occurrence_reader: Optional[Callable[..., Any]] = None):
        self.operations = operations
        self.document_operations = document_operations
        self.due_port = due_port
        self.occurrence_reader = occurrence_reader

    def _grant_allows(self, project: Mapping[str, Any], actor: str) -> bool:
        ref = _ref(project)
        grant = getattr(self.operations, "project_read_grant", None)
        if ref is None or ref.get("kind") != "work.project":
            return False
        if getattr(grant, "principal", None) is None:
            return False
        try:
            from herzchen.contracts import ResourceRef

            return grant.principal == self.operations.binding.authenticated_actor(actor) and grant.allows(
                ResourceRef.from_dict(ref)
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _session_inventory(self, actor: str) -> list[dict[str, Any]]:
        port = getattr(self.operations, "authoring_port", None)
        if port is None or not callable(getattr(port, "session_inventory", None)):
            return []
        try:
            result = _mapping(port.session_inventory(self.operations.binding.authenticated_actor(actor)), "session inventory")
        except Exception:
            return []
        return [dict(item) for item in result.get("sessions", ()) if isinstance(item, Mapping)]

    def _resolve_sessions(self, *, actor: str, project: Optional[Mapping[str, Any]],
                          checkout_ref: Optional[Mapping[str, Any]], session_id: Optional[str]) -> list[dict[str, Any]]:
        rows = self._session_inventory(actor)
        result = []
        for row in rows:
            scope = row.get("scope_ref")
            target = row.get("target_ref")
            if checkout_ref is not None and not _same(scope, checkout_ref):
                continue
            if session_id is not None and row.get("session_id") != session_id:
                continue
            if project is not None and not (_same(scope, project) or _same(target, project)):
                continue
            result.append(_json(row))
        return result

    def _project_ref_from_session(self, row: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        for value in (row.get("target_ref"), row.get("scope_ref")):
            ref = _ref(value)
            if ref is not None and ref.get("kind") == "work.project":
                return ref
        return None

    def _read_project(self, project: Mapping[str, Any], *, actor: str,
                      sessions: Sequence[Mapping[str, Any]], native_observer: Any) -> dict[str, Any]:
        from herzchen.contracts import ResourceRef

        project_ref = _ref(project, "project_ref")
        if project_ref is None or not self._grant_allows(project_ref, actor):
            return {"project_ref": project_ref, "state": "held", "issues": [{"code": "project_scope_denied"}]}
        current = self.operations.reader.get_record(ResourceRef.from_dict(project_ref))
        if current is None:
            return {"project_ref": project_ref, "state": "missing", "issues": [{"code": "project_record_missing"}]}
        try:
            view = _json(self.operations.sheet_port.export(ResourceRef.from_dict(project_ref)))
        except Exception as exc:
            return {"project_ref": project_ref, "state": "unknown",
                    "issues": [{"code": "project_read_failed", "message": str(exc)}]}
        view = view if isinstance(view, Mapping) else {}
        project_view = _mapping(view.get("project", {}), "project view")
        observed = _mapping(project_view.get("observed", {}), "project observed")
        authored = _mapping(project_view.get("authored", {}), "project authored")

        assignment_refs: list[dict[str, Any]] = []
        for source in [observed, *[task.get("observed", {}) for task in view.get("tasks", ()) if isinstance(task, Mapping)]]:
            for item in source.get("assignments", ()) if isinstance(source, Mapping) else ():
                ref = _assignment_ref(item)
                if ref is not None and ref not in assignment_refs:
                    assignment_refs.append(ref)
        assignments = []
        for ref in assignment_refs:
            try:
                value = self.operations.assignments_port.get(ResourceRef.from_dict(ref))
                assignments.append(_assignment_row(value, fallback_ref=ref))
            except Exception as exc:
                assignments.append({"ref": ref, "state": "unavailable", "error": str(exc), "generation": None})

        associations = []
        for raw in view.get("documents", ()) if isinstance(view.get("documents", ()), (list, tuple)) else ():
            item = _json(raw)
            if not isinstance(item, Mapping):
                continue
            association = _ref(item.get("association"))
            binding = _json(item.get("binding"))
            association_value = item.get("association") if isinstance(item.get("association"), Mapping) else {}
            namespace = association_value.get("namespace")
            key = association_value.get("key")
            label = f"{namespace} {key}".lower()
            kind = "worktree" if "worktree" in label else "source" if "source" in label else "document"
            location = _location_values(item, limit=5)
            associations.append({"association_ref": association, "document_ref": _ref(item.get("binding", {}).get("ref") if isinstance(item.get("binding"), Mapping) else None),
                "namespace": namespace, "key": key, "kind": kind, "binding": binding,
                "location": location, "state": "current" if association is not None else "unknown"})

        locations = _location_values({"project": authored, "tasks": view.get("tasks", ()), "documents": associations})
        locations.extend(item for association in associations for item in association.get("location", ()))
        unique_locations = []
        seen_locations = set()
        for item in locations:
            marker = json.dumps(_json(item), sort_keys=True, separators=(",", ":"))
            if marker not in seen_locations:
                seen_locations.add(marker)
                unique_locations.append(_json(item))

        occurrences = self._occurrences(project_ref, assignments, native_observer)
        chats = self._chats(occurrences, assignments)
        session_rows = [dict(row) for row in sessions if _same(row.get("scope_ref"), project_ref) or _same(row.get("target_ref"), project_ref)]
        issues = []
        for location in unique_locations:
            if location.get("state") in {"missing", "moved", "ambiguous"}:
                issues.append({"code": "location_" + location["state"], "location": location})
        if len(assignments) > 1:
            issues.append({"code": "multiple_responsibilities", "count": len(assignments)})
        state = "current"
        if any(item.get("state") in {"held", "unknown"} for item in occurrences):
            state = "held"
        if any(item.get("state") in {"missing", "moved", "ambiguous"} for item in unique_locations):
            state = "held"
        return {
            "project_ref": project_ref,
            "project": {"ref": _ref(project_view.get("ref")) or project_ref,
                         "authored": authored, "lifecycle": authored.get("lifecycle") or _json(getattr(current, "payload", {}).get("lifecycle"))},
            "state": state,
            "checkout_sessions": session_rows,
            "responsibilities": assignments,
            "document_associations": associations,
            "source_worktree_associations": [item for item in associations if item["kind"] in {"source", "worktree"}],
            "locations": unique_locations,
            "native_chats": chats,
            "occurrences": occurrences,
            "cardinality": {"checkout_sessions": len(session_rows), "responsibilities": len(assignments),
                             "document_associations": len(associations), "source_worktree_associations": sum(item["kind"] in {"source", "worktree"} for item in associations),
                             "native_chats": len(chats), "occurrences": len(occurrences), "locations": len(unique_locations)},
            "issues": issues,
        }

    def _occurrences(self, project: Mapping[str, Any], assignments: Sequence[Mapping[str, Any]], observer: Any) -> list[dict[str, Any]]:
        rows = []
        if self.occurrence_reader is not None:
            try:
                values = self.occurrence_reader(project_ref=project, assignment_refs=[item.get("ref") for item in assignments])
            except TypeError:
                values = self.occurrence_reader(project)
        elif self.due_port is not None and callable(getattr(self.due_port, "list_due", None)):
            try:
                values = self.due_port.list_due({"project_ref": project["id"]})
            except (TypeError, ValueError):
                values = ()
        else:
            values = ()
        assignment_map = {_identity(item.get("ref")): item for item in assignments if _identity(item.get("ref"))}
        for raw in values or ():
            due = _json(raw)
            if not isinstance(due, Mapping):
                continue
            target = due.get("target") if isinstance(due.get("target"), Mapping) else {}
            due_project = due.get("project_ref") or target.get("project_ref")
            assignment_ref = _assignment_ref(due.get("assignment_ref") or target.get("assignment_ref"))
            due_matches = (
                due_project == project.get("id")
                if isinstance(due_project, str)
                else _same(due_project, project)
            )
            if due_project is not None and not due_matches:
                continue
            if due_project is None and assignment_ref is not None and _identity(assignment_ref) not in assignment_map:
                continue
            current_assignment = assignment_map.get(_identity(assignment_ref))
            current = current_assignment is not None and due.get("generation") == current_assignment.get("generation")
            native_id = target.get("native_id") or target.get("native_session_id")
            state = "current" if current else "held"
            if due.get("stop_state") in {"stopped", "paused"} or due.get("completion_state") == "unknown":
                state = "held"
            observation = _native_observation(observer, native_id, context={"project_ref": project, "occurrence": due})
            rows.append({"occurrence_ref": {"schedule_id": due.get("schedule_id"),
                                               "logical_request_key": due.get("in_flight_request") or due.get("last_completed_request")},
                         "schedule_id": due.get("schedule_id"), "assignment_ref": assignment_ref,
                         "generation": due.get("generation"), "native_session_id": native_id,
                         "role": due.get("role"), "recipient": due.get("recipient"),
                         "state": state, "stop_state": due.get("stop_state"),
                         "completion_state": due.get("completion_state"), "native": observation})
        rows.sort(key=lambda item: (str(item.get("schedule_id")), json.dumps(item.get("assignment_ref"), sort_keys=True)))
        return rows[:MAX_MATCHES]

    @staticmethod
    def _chats(occurrences: Sequence[Mapping[str, Any]], assignments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        chats: dict[str, dict[str, Any]] = {}
        for item in assignments:
            native = item.get("session")
            native_id = native if isinstance(native, str) else (native or {}).get("native_id") if isinstance(native, Mapping) else None
            if isinstance(native_id, str) and native_id.strip():
                chats.setdefault(native_id, {"native_session_id": native_id, "occurrences": [], "states": set(), "assignment_refs": []})
                if item.get("ref") not in chats[native_id]["assignment_refs"]:
                    chats[native_id]["assignment_refs"].append(item.get("ref"))
        for occurrence in occurrences:
            native_id = occurrence.get("native_session_id")
            if not isinstance(native_id, str) or not native_id.strip():
                continue
            chat = chats.setdefault(native_id, {"native_session_id": native_id, "occurrences": [], "states": set(), "assignment_refs": []})
            chat["occurrences"].append(occurrence.get("occurrence_ref"))
            chat["states"].add(occurrence.get("state"))
            if occurrence.get("assignment_ref") not in chat["assignment_refs"]:
                chat["assignment_refs"].append(occurrence.get("assignment_ref"))
        result = []
        for native_id in sorted(chats):
            row = dict(chats[native_id])
            states = row.pop("states")
            row["state"] = "held" if "held" in states else "current" if "current" in states else "unknown"
            row["occurrence_count"] = len(row["occurrences"])
            result.append(row)
        return result

    def read(self, *, actor: str, project_ref: Any = None, checkout_ref: Any = None,
             session_id: Optional[str] = None, cursor: Optional[str] = None,
             limit: int = 25, native_observer: Any = None) -> dict[str, Any]:
        if not isinstance(actor, str) or not actor.strip():
            raise RecoveryDiscoveryError("actor must be non-blank text")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_LIMIT:
            raise RecoveryDiscoveryError(f"limit must be between 1 and {MAX_LIMIT}")
        if project_ref is None and checkout_ref is None and session_id is None:
            raise RecoveryDiscoveryError("supply project_ref, checkout_ref, or session_id")
        project = _ref(project_ref, "project_ref") if project_ref is not None else None
        checkout = _ref(checkout_ref, "checkout_ref") if checkout_ref is not None else None
        if project is not None and project.get("kind") != "work.project":
            raise RecoveryDiscoveryError("project_ref must identify work.project")
        if checkout is not None and checkout.get("kind") != "authoring-scope":
            raise RecoveryDiscoveryError("checkout_ref must identify an existing authoring-scope")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise RecoveryDiscoveryError("session_id must be non-blank text")

        sessions = self._resolve_sessions(actor=actor, project=project, checkout_ref=checkout, session_id=session_id)
        project_refs = [] if project is None else [project]
        if project is None:
            for row in sessions:
                candidate = self._project_ref_from_session(row)
                if (candidate is not None and self._grant_allows(candidate, actor)
                        and candidate not in project_refs):
                    project_refs.append(candidate)
        project_refs.sort(key=lambda item: json.dumps(item, sort_keys=True))
        scope = {"project_ref": project, "checkout_ref": checkout, "session_id": session_id}
        snapshot = _digest({"projects": project_refs, "sessions": sessions})
        try:
            offset = _decode_cursor(cursor, scope=scope, snapshot=snapshot)
        except RecoveryDiscoveryError as exc:
            return {"outcome": "error", "schema": SCHEMA, "read_only": True, "dispatch": False,
                    "launch": False, "matches": [], "error": {"code": "invalid_or_stale_cursor", "message": str(exc)}}
        page_refs = project_refs[offset:offset + limit]
        matches = [self._read_project(ref, actor=actor, sessions=sessions, native_observer=native_observer) for ref in page_refs]
        has_more = offset + len(page_refs) < len(project_refs)
        selection_state = "missing" if not sessions and project is None else "ambiguous" if len(project_refs) > 1 or len(sessions) > 1 and project is None else "current"
        if any(item.get("state") == "held" for item in matches):
            selection_state = "held" if selection_state == "current" else selection_state
        if not matches and project is not None:
            selection_state = "missing"
        continuation = self._continuation(matches, selection_state)
        return {
            "outcome": "read",
            "schema": SCHEMA,
            "read_only": True,
            "dispatch": False,
            "launch": False,
            "selection": {"state": selection_state, "project_ref": project, "checkout_ref": checkout,
                           "session_id": session_id, "candidate_count": len(project_refs),
                           "matched_session_count": len(sessions)},
            "matches": matches,
            "cardinality": {"projects": len(project_refs), "returned_projects": len(matches),
                             "checkout_sessions": len(sessions), "ambiguous": len(project_refs) > 1 or (project is None and len(sessions) > 1)},
            "pagination": {"limit": limit, "offset": offset, "has_more": has_more,
                           "cursor": _encode_cursor(scope=scope, snapshot=snapshot, offset=offset + len(page_refs)) if has_more else None,
                           "snapshot_digest": snapshot},
            "continuation": continuation,
            "supported_actions": {"resume_same_chat": continuation.get("operation"),
                                   "replace_or_reassign": "existing_owner_operation_after_custody_resolution",
                                   "exact_rebind": "existing_supported_rebind_only"},
        }

    @staticmethod
    def _continuation(matches: Sequence[Mapping[str, Any]], selection_state: str) -> dict[str, Any]:
        chats = [chat for match in matches for chat in match.get("native_chats", ()) if isinstance(chat, Mapping)]
        current = [chat for chat in chats if chat.get("state") == "current"]
        if selection_state == "ambiguous" or len(current) != 1:
            return {"state": "ambiguous" if selection_state == "ambiguous" or len(current) > 1 else "held",
                    "operation": None, "execute": False,
                    "reason": "resolve one current responsibility and native chat before continuation"}
        chat = current[0]
        return {"state": "eligible", "operation": "existing_execution_application.resume",
                "execute": False, "fresh_authenticated_process": True,
                "same_native_session_id": chat.get("native_session_id"),
                "occurrence_refs": chat.get("occurrences", []),
                "reason": "read resolved one current chat; explicit owner resume is still required"}


__all__ = ["BoundedRecoveryDiscovery", "RecoveryDiscoveryError", "SCHEMA"]
