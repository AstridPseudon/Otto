"""Read-only, project-scoped manager inventory.

The inventory is a projection over the existing pending-project, project-sheet,
and assignment readers.  It owns no roster, cache, native session, or
authority store.  A native observer is injected by the supported host and is
never called to create, resume, close, or send anything.
"""

from __future__ import annotations

from inspect import Parameter, signature
import json
from typing import Any, Callable, Mapping, Optional, Sequence


class ManagerInventoryError(ValueError):
    """An injected public reader or observation value is not admissible."""


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    return str(value)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    value = _json_value(value)
    if not isinstance(value, Mapping):
        raise ManagerInventoryError(f"{field} must be an object")
    return dict(value)


def _ref(value: Any) -> Optional[dict[str, Any]]:
    value = _json_value(value)
    if not isinstance(value, Mapping):
        return None
    if not all(value.get(key) for key in ("authority", "kind", "id")):
        return None
    return dict(value)


def _identity(value: Any) -> Optional[tuple[str, str, str]]:
    ref = _ref(value)
    return None if ref is None else (str(ref["authority"]), str(ref["kind"]), str(ref["id"]))


def _same_identity(left: Any, right: Any) -> bool:
    return _identity(left) == _identity(right) and _identity(left) is not None


def _value(value: Any, *keys: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for key in keys:
            if key in value:
                return value[key]
        payload = value.get("payload")
        if isinstance(payload, Mapping):
            for key in keys:
                if key in payload:
                    return payload[key]
    else:
        for key in keys:
            selected = getattr(value, key, None)
            if selected is not None:
                return selected
    return default


def _project_ref(record: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    return _ref(record.get("project_ref") or record.get("ref"))


def _project_lifecycle(record: Mapping[str, Any]) -> Optional[str]:
    value = _value(record, "lifecycle", "status")
    return None if value is None else str(value).lower()


def _is_completed(record: Mapping[str, Any]) -> bool:
    lifecycle = _project_lifecycle(record)
    return lifecycle in {"completed", "closed", "done", "retired"}


def _assignment_ref(value: Any) -> Optional[dict[str, Any]]:
    value = _json_value(value)
    if not isinstance(value, Mapping):
        return None
    return _ref(value.get("assignment_ref") or value.get("ref") or value)


def _assignment_items(exported: Any) -> list[Any]:
    value = _json_value(exported)
    candidates: list[Any] = [value]
    visited: set[int] = set()
    while candidates:
        candidate = candidates.pop(0)
        if not isinstance(candidate, Mapping) or id(candidate) in visited:
            continue
        visited.add(id(candidate))
        assignments = candidate.get("assignments")
        if isinstance(assignments, (list, tuple)):
            return list(assignments)
        for key in ("project", "observed", "payload"):
            nested = candidate.get(key)
            if isinstance(nested, Mapping):
                candidates.append(nested)
    return []


def _metadata_bindings(record: Mapping[str, Any], exported: Any) -> list[dict[str, Any]]:
    sources: list[Any] = [record, record.get("payload") if isinstance(record, Mapping) else None]
    payload = record.get("payload") if isinstance(record, Mapping) else None
    if isinstance(payload, Mapping):
        sources.extend((payload.get("metadata"), payload.get("fields")))
        fields = payload.get("fields")
        if isinstance(fields, Mapping):
            sources.append(fields.get("metadata"))
    exported_value = _json_value(exported)
    sources.append(exported_value)
    bindings: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        raw = source.get("manager_binding")
        if raw is None:
            metadata = source.get("metadata")
            raw = metadata.get("manager_binding") if isinstance(metadata, Mapping) else None
        if raw is None:
            continue
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            if isinstance(value, Mapping):
                binding = dict(value)
                if not any(_same_binding(binding, prior) for prior in bindings):
                    bindings.append(binding)
    return bindings


def _same_binding(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return json.dumps(_json_value(left), sort_keys=True, separators=(",", ":")) == json.dumps(_json_value(right), sort_keys=True, separators=(",", ":"))


def _assignment_scope(assignment: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    scope = assignment.get("scope")
    if scope is None:
        scope = (assignment.get("payload") or {}).get("scope") if isinstance(assignment.get("payload"), Mapping) else None
    return _ref(scope)


def _assignment_role(assignment: Mapping[str, Any]) -> Optional[str]:
    role = _value(assignment, "role")
    return None if role is None else str(role).lower()


def _native_binding(assignment: Mapping[str, Any], metadata: Sequence[Mapping[str, Any]]) -> Any:
    for source in (assignment, assignment.get("payload")):
        if not isinstance(source, Mapping):
            continue
        for key in ("native_binding", "native_identity", "physical_session_id", "session_id", "session"):
            value = source.get(key)
            if value is not None:
                return _json_value(value)
    for item in metadata:
        for key in ("native_binding", "native_identity", "physical_session_id", "session_id", "session"):
            value = item.get(key)
            if value is not None:
                return _json_value(value)
    return None


def _native_id(binding: Any) -> Optional[str]:
    if isinstance(binding, str) and binding.strip():
        return binding
    if isinstance(binding, Mapping):
        for key in ("native_id", "physical_session_id", "session_id", "thread_id", "agent_id", "id"):
            value = binding.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _state(value: Any, *, default: str = "unknown") -> str:
    if value is None:
        return default
    selected = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "running": "active",
        "in_progress": "active",
        "notloaded": "not_loaded",
        "not_loaded": "not_loaded",
        "unavailable": "unavailable",
        "unknown": "unknown",
        "conflict": "conflict",
        "idle": "idle",
        "active": "active",
        "completed": "completed",
        "closed": "completed",
        "dead": "unknown",
    }.get(selected, "unknown")


def _call_observer(observer: Any, binding: Any, context: Mapping[str, Any]) -> Any:
    method = getattr(observer, "observe", observer)
    if not callable(method):
        raise ManagerInventoryError("native observer is not callable")
    try:
        parameters = signature(method).parameters.values()
    except (TypeError, ValueError):
        return method(binding)
    accepts_kwargs = any(item.kind == Parameter.VAR_KEYWORD for item in parameters)
    accepted = {item.name for item in parameters}
    kwargs = dict(context) if accepts_kwargs else {key: value for key, value in context.items() if key in accepted}
    return method(binding, **kwargs)


def _native_view(observer: Any, binding: Any, *, project_ref: Mapping[str, Any], assignment: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, Any]:
    native_id = _native_id(binding)
    if binding is None:
        return {"state": "unknown", "reason": "native_binding_missing", "native_binding": None, "observed_at": None, "provider": None}
    if observer is None:
        return {"state": "unavailable", "reason": "native_observer_unavailable", "native_binding": binding, "native_id": native_id, "observed_at": None, "provider": None}
    try:
        observed = _json_value(_call_observer(observer, binding, {
            "project_ref": project_ref,
            "assignment_ref": assignment.get("assignment_ref") or assignment.get("ref"),
            "assignment": assignment,
            "project": project,
        }))
    except Exception as exc:
        return {"state": "unknown", "reason": "native_observation_error", "error": str(exc), "native_binding": binding, "native_id": native_id, "observed_at": None, "provider": None}
    if not isinstance(observed, Mapping):
        return {"state": "unknown", "reason": "native_observation_malformed", "native_binding": binding, "native_id": native_id, "observed_at": None, "provider": None}
    observed_id = _native_id(observed.get("native_binding") or observed.get("native_identity") or observed.get("native_id") or observed.get("id"))
    if native_id is not None and observed_id is not None and native_id != observed_id:
        return {"state": "conflict", "reason": "native_identity_mismatch", "native_binding": binding, "native_id": native_id, "observed_native_id": observed_id, "observed_at": observed.get("observed_at"), "provider": observed.get("provider")}
    view = dict(observed)
    view["state"] = _state(observed.get("state", observed.get("status")))
    view["native_binding"] = binding
    view["native_id"] = observed_id or native_id
    view.setdefault("observed_at", None)
    view.setdefault("provider", None)
    return view


def _routability(observed: Mapping[str, Any]) -> dict[str, Any]:
    raw = observed.get("routability")
    if isinstance(raw, Mapping):
        result = dict(raw)
        state = raw.get("state", raw.get("status"))
    else:
        result = {}
        state = raw
    if state is None and isinstance(observed.get("routable"), bool):
        state = "routable" if observed["routable"] else "not_routable"
    state_value = _state(state, default="unknown") if state not in {"routable", "not_routable"} else state
    result["state"] = state_value
    if "capabilities" in observed:
        result["capabilities"] = _json_value(observed["capabilities"])
    if "missing_capabilities" in observed:
        result["missing_capabilities"] = _json_value(observed["missing_capabilities"])
    result.setdefault("capabilities", [])
    result.setdefault("missing_capabilities", [])
    return result


def _assignment_projection(
    item: Any,
    *,
    project_ref: Mapping[str, Any],
    project: Mapping[str, Any],
    metadata: Sequence[Mapping[str, Any]],
    assignment_reader: Optional[Callable[[Any], Any]],
    native_observer: Any,
    multiple: bool,
) -> dict[str, Any]:
    assignment_ref = _assignment_ref(item)
    assignment: Optional[dict[str, Any]] = None
    read_state = "read"
    if assignment_ref is not None and assignment_reader is not None:
        try:
            value = assignment_reader(assignment_ref)
            assignment = None if value is None else _mapping(value, "assignment")
            if assignment is None:
                read_state = "unavailable"
        except Exception as exc:
            read_state = "unavailable"
            assignment = {"assignment_ref": assignment_ref, "read_error": str(exc)}
    elif isinstance(item, Mapping):
        assignment = dict(item)
    else:
        read_state = "unavailable"
        assignment = {"assignment_ref": assignment_ref}
    assignment = assignment or {"assignment_ref": assignment_ref}
    assignment_ref = _assignment_ref(assignment) or assignment_ref
    principal = _value(assignment, "principal", "manager")
    generation = _value(assignment, "generation")
    scope = _assignment_scope(assignment)
    role = _assignment_role(assignment)
    issues: list[dict[str, Any]] = []
    if read_state != "read":
        issues.append({"code": "assignment_unavailable", "message": "canonical assignment reader did not return the assignment"})
    if assignment_ref is None:
        issues.append({"code": "assignment_ref_missing", "message": "manager projection has no exact assignment reference"})
    if role not in {"manager", None}:
        issues.append({"code": "non_manager_assignment", "message": "project sheet assignment is not a manager assignment", "role": role})
    if scope is not None and not _same_identity(scope, project_ref):
        issues.append({"code": "foreign_project_scope", "message": "assignment scope is outside the project"})
    if principal is None or generation is None:
        issues.append({"code": "assignment_identity_incomplete", "message": "exact principal and generation are required"})
    matching_metadata = [entry for entry in metadata if _same_identity(entry.get("assignment_ref") or entry.get("ref"), assignment_ref)]
    if metadata and not matching_metadata:
        issues.append({"code": "stale_manager_binding_metadata", "message": "project metadata does not name this canonical assignment"})
    if matching_metadata:
        declared = matching_metadata[0]
        if declared.get("generation") is not None and generation is not None and declared.get("generation") != generation:
            issues.append({"code": "generation_conflict", "message": "metadata and canonical assignment generations differ"})
        declared_principal = declared.get("principal") or declared.get("manager")
        if declared_principal is not None and principal is not None and _json_value(declared_principal) != _json_value(principal):
            issues.append({"code": "principal_conflict", "message": "metadata and canonical assignment principals differ"})
    status = str(_value(assignment, "status", default="unknown")).lower()
    if status in {"completed", "closed", "done"}:
        binding_state = "completed"
    elif multiple or any(issue["code"] in {"foreign_project_scope", "generation_conflict", "principal_conflict"} for issue in issues):
        binding_state = "conflict"
    elif read_state != "read":
        binding_state = "unavailable"
    elif assignment_ref is None or principal is None or generation is None:
        binding_state = "unknown"
    else:
        binding_state = "canonical"
    native_binding = _native_binding(assignment, matching_metadata or metadata)
    native = _native_view(native_observer, native_binding, project_ref=project_ref, assignment=assignment, project=project)
    if native.get("state") == "conflict":
        binding_state = "conflict"
        issues.append({"code": "native_identity_conflict", "message": "native observation conflicts with the exact binding"})
    return {
        "assignment_ref": assignment_ref,
        "principal": _json_value(principal),
        "generation": generation,
        "role": role,
        "scope": scope,
        "assignment_status": status,
        "read_state": read_state,
        "binding_state": binding_state,
        "native": native,
        "routability": _routability(native),
        "issues": issues,
        "history": _json_value(assignment.get("history", ())),
    }


class ManagerInventoryReader:
    """Compose one read-only inventory from finite injected readers."""

    def __init__(
        self,
        *,
        pending_reader: Callable[[str], Mapping[str, Any]],
        project_reader: Callable[[Any], Any],
        assignment_reader: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.pending_reader = pending_reader
        self.project_reader = project_reader
        self.assignment_reader = assignment_reader

    def read(self, *, actor: str, native_observer: Any = None) -> dict[str, Any]:
        try:
            pending = _mapping(self.pending_reader(actor), "pending reader result")
        except Exception as exc:
            return {
                "outcome": "unavailable",
                "read_only": True,
                "writes": 0,
                "native_calls": 0,
                "error": {"code": "pending_reader_unavailable", "message": str(exc)},
                "projects": [],
                "excluded_completed": [],
            }
        raw_records = pending.get("records", ())
        if not isinstance(raw_records, (list, tuple)):
            return {"outcome": "unavailable", "read_only": True, "writes": 0, "native_calls": 0, "error": {"code": "pending_reader_malformed", "message": "records must be an array"}, "projects": [], "excluded_completed": []}
        projects: list[dict[str, Any]] = []
        excluded_completed: list[dict[str, Any]] = []
        for raw_record in raw_records:
            try:
                record = _mapping(raw_record, "project record")
            except ManagerInventoryError as exc:
                projects.append({"project_ref": None, "state": "unknown", "error": {"code": "project_record_malformed", "message": str(exc)}})
                continue
            project_ref = _project_ref(record)
            if project_ref is None:
                projects.append({"project_ref": None, "state": "unknown", "error": {"code": "project_ref_missing", "message": "pending record has no exact project reference"}})
                continue
            if _is_completed(record):
                excluded_completed.append({"project_ref": project_ref, "reason": "completed"})
                continue
            try:
                exported = self.project_reader(project_ref)
                project = _mapping(exported, "project export")
            except Exception as exc:
                projects.append({
                    "project_ref": project_ref,
                    "state": "unavailable",
                    "lifecycle": _project_lifecycle(record),
                    "manager_bindings": [],
                    "native": {"state": "unknown", "reason": "project_reader_unavailable"},
                    "routability": {"state": "unavailable", "capabilities": [], "missing_capabilities": ["project_sheet_reader"]},
                    "issues": [{"code": "project_reader_unavailable", "message": str(exc)}],
                })
                continue
            metadata = _metadata_bindings(record, project)
            items = [item for item in _assignment_items(project) if _assignment_role(_json_value(item) if isinstance(_json_value(item), Mapping) else {}) in {"manager", None}]
            if not items and metadata:
                items = [{"assignment_ref": entry.get("assignment_ref") or entry.get("ref"), "principal": entry.get("principal") or entry.get("manager"), "generation": entry.get("generation"), "native_binding": entry.get("native_binding") or entry.get("native_identity"), "role": "manager", "status": "unknown"} for entry in metadata]
            multiple = len(items) > 1
            bindings = [_assignment_projection(item, project_ref=project_ref, project=project, metadata=metadata, assignment_reader=self.assignment_reader, native_observer=native_observer, multiple=multiple) for item in items]
            if not bindings:
                bindings = [{
                    "assignment_ref": None,
                    "principal": None,
                    "generation": None,
                    "role": "manager",
                    "scope": project_ref,
                    "assignment_status": "missing",
                    "read_state": "read",
                    "binding_state": "missing",
                    "native": {"state": "unknown", "reason": "manager_assignment_missing", "native_binding": None, "observed_at": None, "provider": None},
                    "routability": {"state": "unavailable", "capabilities": [], "missing_capabilities": ["manager_assignment"]},
                    "issues": [{"code": "manager_assignment_missing", "message": "no project-scoped manager assignment was found"}],
                    "history": [],
                }]
            if metadata and not any(_same_identity(entry.get("assignment_ref") or entry.get("ref"), binding.get("assignment_ref")) for entry in metadata for binding in bindings):
                for entry in metadata:
                    bindings.append(_assignment_projection({"assignment_ref": entry.get("assignment_ref") or entry.get("ref"), "principal": entry.get("principal") or entry.get("manager"), "generation": entry.get("generation"), "native_binding": entry.get("native_binding") or entry.get("native_identity"), "role": "manager", "status": "stale"}, project_ref=project_ref, project=project, metadata=metadata, assignment_reader=self.assignment_reader, native_observer=None, multiple=True))
            projects.append({
                "project_ref": project_ref,
                "state": "unfinished",
                "lifecycle": _project_lifecycle(record),
                "manager_bindings": bindings,
            })
        projects.sort(key=lambda item: json.dumps(item.get("project_ref"), sort_keys=True))
        return {
            "outcome": "inventoried",
            "read_only": True,
            "writes": 0,
            "native_calls": 0,
            "projects": projects,
            "excluded_completed": excluded_completed,
            "native_observation": "injected_observer_only",
            "historical_reuse": False,
        }


__all__ = ["ManagerInventoryError", "ManagerInventoryReader"]
