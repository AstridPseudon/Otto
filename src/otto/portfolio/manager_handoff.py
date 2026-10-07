"""Bounded, read-only manager handoff over existing owner projections.

This module deliberately has no owner, Store, scheduler, or persistence
dependency.  Callers supply fresh views from the maintained owner readers and
this module keeps only exact references, small status fields, and digests.
Large receipts, transcripts, and native evidence remain behind their source
references.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


class ManagerHandoffError(ValueError):
    """A handoff input cannot be projected without losing its meaning."""


_MAX_ITEMS = 128
_MAX_NOTES = 32
_MAX_TEXT = 512
_TERMINAL = {"completed", "closed", "done", "terminal", "succeeded", "success"}
_ACCEPTED = {"accepted", "accepted_for_task", "accepted_for_project", "accept"}
_UNKNOWN = {"unknown", "uncertain", "lost", "lost_response", "timeout", "conflict"}
_PENDING = {"pending", "prepared", "ready", "active", "running", "in_flight", "queued"}


def _json(value: Any) -> Any:
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


def _digest(value: Any) -> str:
    raw = json.dumps(_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _ref(value: Any, *, required: bool = False) -> dict[str, Any] | None:
    value = _json(value)
    if not isinstance(value, Mapping) or not all(
        isinstance(value.get(key), str) and value[key].strip()
        for key in ("authority", "kind", "id")
    ):
        if required:
            raise ManagerHandoffError("handoff requires complete owner references")
        return None
    result = {key: value[key] for key in ("authority", "kind", "id")}
    if value.get("revision") is not None:
        if not isinstance(value["revision"], str) or not value["revision"].strip():
            raise ManagerHandoffError("handoff reference revision is malformed")
        result["revision"] = value["revision"]
    return result


def _text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:_MAX_TEXT]


def _state(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("state", value.get("status", value.get("lifecycle", value.get("outcome"))))
    selected = str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    if selected in _TERMINAL:
        return "terminal"
    if selected in _ACCEPTED:
        return "accepted"
    if selected in _UNKNOWN:
        return "unknown"
    if selected in _PENDING:
        return "pending"
    if selected in {"none", "not_started", "idle"}:
        return "pending"
    return selected or "unknown"


def _bounded_refs(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, (list, tuple)):
        return []
    return [ref for ref in (_ref(item) for item in values[:_MAX_ITEMS]) if ref is not None]


def _source(value: Any, *, ref_value: Any = None) -> dict[str, Any]:
    normalized = _json(value)
    result: dict[str, Any] = {"sha256": _digest(normalized)}
    source_ref = _ref(ref_value if ref_value is not None else normalized)
    if source_ref is not None:
        result["ref"] = source_ref
    return result


def _occurrence(value: Any, *, current: bool = False) -> dict[str, Any]:
    raw = _json(value)
    if not isinstance(raw, Mapping):
        return {"state": "unknown", "current": current, "reason": "occurrence_not_available"}
    target = raw.get("target") if isinstance(raw.get("target"), Mapping) else {}
    host = raw.get("host_evidence") if isinstance(raw.get("host_evidence"), Mapping) else {}
    attempt = host.get("gateway_attempt", raw.get("gateway_attempt"))
    attempt = attempt if isinstance(attempt, Mapping) else None
    last_result = raw.get("last_result") if isinstance(raw.get("last_result"), Mapping) else {}
    retained_result = attempt.get("result") if attempt and isinstance(attempt.get("result"), Mapping) else {}
    result = {
        "current": current,
        "schedule_id": raw.get("schedule_id"),
        "version": raw.get("version"),
        "state": _state(raw.get("completion_state") or raw.get("delivery_state") or raw.get("stop_state")),
        "delivery_state": raw.get("delivery_state"),
        "completion_state": raw.get("completion_state"),
        "stop_state": raw.get("stop_state"),
        "role": raw.get("role"),
        "purpose": _text(raw.get("purpose")),
        "generation": raw.get("generation"),
        "assignment_ref": _ref(raw.get("assignment_ref")),
        "project_ref": _ref(target.get("project_ref") or raw.get("project_ref")),
        "task_ref": _ref(target.get("task_ref") or raw.get("task_ref")),
        "mandate_ref": _ref(target.get("mandate_ref") or raw.get("mandate_ref")),
        "context_refs": _bounded_refs(raw.get("context_refs")),
        "in_flight_request": raw.get("in_flight_request"),
        "last_completed_request": raw.get("last_completed_request"),
        "provider_called": attempt is not None or bool(raw.get("provider_called")),
        "provider_called_scope": "retained_occurrence_attempt",
        "physical_session_id": last_result.get("physical_session_id") or target.get("native_id"),
        "result_ref": _ref(raw.get("result_ref") or last_result.get("result_ref")),
        "observed_turn_id": last_result.get("observed_turn_id") or retained_result.get("observed_turn_id"),
        "result_sha256": _digest(last_result) if last_result else None,
        "source_sha256": _digest(raw),
    }
    if result["result_ref"] is None:
        result["result_ref_reason"] = ("manager_occurrence_has_no_analytical_result_ref"
                                       if raw.get("role") == "manager" else "not_exposed_by_occurrence")
    if result["state"] == "pending" and raw.get("in_flight_request") is None and attempt is not None:
        result["state"] = "unknown"
        result["reason"] = "retained_attempt_without_terminal_result"
    result["retained_command"] = {
        "state": result["state"],
        "request_id": result["in_flight_request"] or result["last_completed_request"],
        "provider_called": result["provider_called"],
        "provider_called_scope": result["provider_called_scope"],
        "result_ref": result["result_ref"],
    }
    return result


def _assignment(value: Any, fallback_ref: Any = None) -> dict[str, Any]:
    raw = _json(value)
    if not isinstance(raw, Mapping):
        raw = {}
    payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
    result = {
        "ref": _ref(raw.get("ref") or raw.get("assignment_ref") or fallback_ref),
        "role": payload.get("role", raw.get("role")),
        "principal": payload.get("principal", raw.get("principal")),
        "generation": payload.get("generation", raw.get("generation")),
        "status": payload.get("status", raw.get("status")),
        "scope": _ref(payload.get("scope") or payload.get("scope_ref")),
        "session": payload.get("session") or payload.get("native_binding") or raw.get("session"),
        "history": [],
    }
    history = payload.get("history", raw.get("history", ()))
    if isinstance(history, (list, tuple)):
        result["history"] = [
            {key: item[key] for key in ("ref", "generation", "principal", "status") if key in item}
            for item in history[:_MAX_ITEMS] if isinstance(item, Mapping)
        ]
    return result


def _task_rows(tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(tasks, (list, tuple)):
        return []
    rows: list[dict[str, Any]] = []
    for item in tasks[:_MAX_ITEMS]:
        raw = _json(item)
        if not isinstance(raw, Mapping):
            continue
        authored = raw.get("authored") if isinstance(raw.get("authored"), Mapping) else {}
        observed = raw.get("observed") if isinstance(raw.get("observed"), Mapping) else {}
        readiness = (raw.get("readiness") if isinstance(raw.get("readiness"), Mapping)
                     else observed.get("readiness") if isinstance(observed.get("readiness"), Mapping)
                     else {})
        if isinstance(readiness.get("value"), Mapping):
            readiness = {**readiness["value"], **{key: readiness[key] for key in ("eligibility", "stale") if key in readiness}}
        result_rows = observed.get("results") if isinstance(observed.get("results"), list) else []
        result_refs = raw.get("result_refs") or [row.get("ref") for row in result_rows if isinstance(row, Mapping)]
        evidence_refs = raw.get("evidence_refs") or authored.get("evidence_refs")
        lifecycle = raw.get("lifecycle") or observed.get("lifecycle") or authored.get("lifecycle")
        if isinstance(lifecycle, Mapping):
            lifecycle = lifecycle.get("value")
        accepted = raw.get("accepted_current_evidence") or observed.get("accepted_current_evidence")
        accepted_projection = None
        if isinstance(accepted, Mapping):
            accepted_projection = {
                "state": _state(accepted),
                "value": accepted.get("value"),
                "reason": _text(accepted.get("reason")),
                "refs": _bounded_refs(accepted.get("evidence_refs") or accepted.get("refs")),
                "sha256": _digest(accepted),
            }
            evidence = accepted.get("evidence")
            if isinstance(evidence, Mapping):
                accepted_projection["evidence"] = {
                    "decision_ref": _ref(evidence.get("decision_ref")),
                    "decision_refs": _bounded_refs(evidence.get("decision_refs")),
                    "result_ref": _ref(evidence.get("result_ref")),
                    "evidence_refs": _bounded_refs(evidence.get("evidence_refs")),
                    "disposition": evidence.get("disposition"),
                }
        elif accepted is not None:
            accepted_projection = _text(accepted)
        rows.append({
            "ref": _ref(raw.get("ref")),
            "title": _text(raw.get("title") or raw.get("name") or authored.get("title") or authored.get("name")),
            "lifecycle": lifecycle,
            "state": _state(lifecycle or readiness.get("status")),
            "readiness": {key: readiness[key] for key in ("status", "eligibility", "stale") if key in readiness},
            "result_refs": _bounded_refs(result_refs),
            "evidence_refs": _bounded_refs(evidence_refs),
            "accepted_current_evidence": accepted_projection,
            "source_refs": _json(raw.get("source_refs") or {"task": raw.get("ref")}),
        })
    return rows


def _observations(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, (list, tuple)):
        return []
    rows: list[dict[str, Any]] = []
    for item in values[:_MAX_ITEMS]:
        raw = _json(item)
        if not isinstance(raw, Mapping):
            continue
        rows.append({
            "source_ref": _ref(raw.get("source_ref") or raw.get("ref")),
            "result_ref": _ref(raw.get("result_ref")),
            "assignment_ref": _ref(raw.get("assignment_ref")),
            "task_ref": _ref(raw.get("task_ref")),
            "generation": raw.get("generation"),
            "status": _state(raw.get("status") or raw.get("outcome")),
            "terminal": raw.get("terminal"),
            "assessed": raw.get("assessed"),
            "assessment_disposition": raw.get("assessment_disposition"),
            "native_id": raw.get("native_id"),
            "native_handle_state": raw.get("native_handle_state"),
            "evidence_refs": _bounded_refs(raw.get("evidence_refs")),
            "source_sha256": _digest(raw),
        })
    return rows


def _notes(status: Mapping[str, Any], reports: Any) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for report in reports if isinstance(reports, (list, tuple)) else ():
        raw = _json(report)
        value = raw.get("value") if isinstance(raw, Mapping) and isinstance(raw.get("value"), Mapping) else raw
        if not isinstance(value, Mapping):
            continue
        note = _text(value.get("next_action") or value.get("summary") or value.get("note"))
        if note:
            values.append({"authority": "attributed_suggestion", "text": note,
                           "source_ref": _ref(raw.get("ref") if isinstance(raw, Mapping) else None),
                           "recorded_at": value.get("recorded_at")})
    suggestion = _text(status.get("agent_suggestion"))
    if suggestion:
        values.append({"authority": "attributed_suggestion", "text": suggestion,
                       "source_ref": None, "recorded_at": None})
    return values[-_MAX_NOTES:]


def _decision_rows(values: Any) -> list[dict[str, Any]]:
    """Keep decisions attributable without copying their full evidence body."""
    if not isinstance(values, (list, tuple)):
        return []
    rows: list[dict[str, Any]] = []
    selected: list[tuple[Any, Any]] = []
    for item in values[:_MAX_ITEMS]:
        group = _json(item)
        if isinstance(group, Mapping) and isinstance(group.get("decisions"), (list, tuple)):
            selected.extend((decision, group.get("subject")) for decision in group["decisions"][:_MAX_ITEMS])
        else:
            selected.append((item, None))
    for item, subject in selected[:_MAX_ITEMS]:
        raw = _json(item)
        if not isinstance(raw, Mapping):
            continue
        value = raw.get("value") if isinstance(raw.get("value"), Mapping) else raw
        rows.append({
            "ref": _ref(raw.get("ref") or value.get("ref")),
            "task_ref": _ref(raw.get("task_ref") or value.get("task_ref") or subject),
            "assignment_ref": _ref(raw.get("assignment_ref") or value.get("assignment_ref")),
            "generation": raw.get("generation", value.get("generation")),
            "status": _state(raw.get("status") or value.get("status") or value.get("outcome") or value.get("disposition")),
            "disposition": value.get("disposition"),
            "candidate_ref": _ref(value.get("candidate_ref")),
            "criterion_ref": _ref(value.get("criterion_ref")),
            "assessment_result_ref": _ref(value.get("assessment_result_ref")),
            "accepted": value.get("accepted"),
            "evidence_refs": _bounded_refs(value.get("evidence_refs")),
            "source_sha256": _digest(raw),
        })
    return rows


def _bounded_items(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[Any] = []
    for item in value[:_MAX_ITEMS]:
        raw = _json(item)
        if isinstance(raw, Mapping):
            result.append({
                key: raw[key] for key in ("code", "source", "message", "reason", "state", "status",
                                           "issue_id", "delivery_id", "schedule_id", "request_id", "ref",
                                           "source_ref", "effect", "operation") if key in raw
            })
        elif isinstance(raw, (str, int, float, bool)) or raw is None:
            result.append(raw)
    return result


def _effective_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("state", "role", "generation", "instruction_sha256", "evidence_sha256",
                "source_refs", "base_resource", "mandate_instruction_contract"):
        if key in value and isinstance(value[key], (str, bool, int, type(None), dict, list)):
            result[key] = _json(value[key])
    instructions = value.get("role_instructions")
    if isinstance(instructions, str):
        result["role_instructions"] = instructions[:2048]
        result["role_instructions_truncated"] = value.get("role_instructions_truncated") is True or len(instructions) > 2048
        result.setdefault("instruction_sha256", _digest(instructions))
    if value.get("state") == "unknown" and "reason" in value:
        result["reason"] = _text(value.get("reason"))
    return result


def _inventory_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value[key] for key in
              ("state", "outcome", "read_only", "native_observation", "historical_reuse")
              if key in value and isinstance(value[key], (str, bool, int, type(None)))}
    project = value.get("project")
    if isinstance(project, Mapping):
        result["project"] = {
            key: project[key] for key in ("project_ref", "state", "lifecycle")
            if key in project and isinstance(project[key], (str, bool, int, type(None), dict))
        }
        bindings = project.get("manager_bindings")
        if isinstance(bindings, list):
            result["project"]["manager_bindings"] = [{
                key: binding[key] for key in ("assignment_ref", "principal", "generation", "role",
                                                "assignment_status", "binding_state", "native", "routability")
                if key in binding and isinstance(binding[key], (str, bool, int, type(None), dict, list))
            } for binding in bindings[:_MAX_ITEMS] if isinstance(binding, Mapping)]
    result["source_sha256"] = _digest(value)
    return result


def compose_manager_handoff(
    *,
    project_ref: Mapping[str, Any],
    project: Mapping[str, Any] | None = None,
    assignment: Mapping[str, Any] | None = None,
    assignment_ref: Mapping[str, Any] | None = None,
    current_occurrence: Mapping[str, Any] | None = None,
    historical_occurrences: Sequence[Mapping[str, Any]] = (),
    effective_context: Mapping[str, Any] | None = None,
    status: Mapping[str, Any] | None = None,
    tasks: Sequence[Mapping[str, Any]] = (),
    results: Sequence[Mapping[str, Any]] = (),
    reports: Sequence[Mapping[str, Any]] = (),
    decisions: Sequence[Mapping[str, Any]] = (),
    help_state: Mapping[str, Any] | None = None,
    budget: Mapping[str, Any] | None = None,
    inventory: Mapping[str, Any] | None = None,
    as_of: str,
) -> dict[str, Any]:
    """Compose one bounded current handoff from already-authorized reads."""
    project_pin = _ref(project_ref, required=True)
    status_value = _json(status or {})
    if not isinstance(status_value, Mapping):
        raise ManagerHandoffError("status must be an object")
    assignment_value = _assignment(assignment, assignment_ref)
    current = _occurrence(current_occurrence, current=True)
    history = [_occurrence(item, current=False) for item in list(historical_occurrences)[:_MAX_ITEMS]]
    current_schedule = current.get("schedule_id")
    history = [item for item in history if item.get("schedule_id") != current_schedule]
    effective_raw = _json(effective_context or {})
    effective = _effective_projection(effective_raw) if isinstance(effective_raw, Mapping) else {}
    help_value = _json(help_state or {"state": "unknown", "reason": "help reader unavailable"})
    budget_value = _json(budget or {"state": "unknown", "reason": "budget reader unavailable"})
    inventory_raw = _json(inventory or {"state": "unknown", "reason": "inventory reader unavailable"})
    inventory_value = _inventory_projection(inventory_raw) if isinstance(inventory_raw, Mapping) else {
        "state": "unknown", "reason": "inventory reader unavailable"
    }
    operation_status = status_value.get("operation_status") if isinstance(status_value.get("operation_status"), Mapping) else status_value
    next_action = operation_status.get("supported_next_remedy") if isinstance(operation_status, Mapping) else None
    envelope: dict[str, Any] = {
        "schema": "otto.manager-handoff.v1",
        "as_of": as_of,
        "project_ref": project_pin,
        "lifecycle": status_value.get("canonical_lifecycle", status_value.get("lifecycle")),
        "manager_assignment": assignment_value,
        "current_occurrence": current,
        "historical_occurrences": history,
        "effective_context": {
            "state": effective.get("state", "known") if effective else "unknown",
            "value": effective if effective else None,
            "source_sha256": _digest(effective),
        },
        "tasks": _task_rows(tasks),
        "results": _observations(results),
        "reports": _observations(reports),
        "decisions": _decision_rows(decisions),
        "outstanding": {
            "effects": _bounded_items(status_value.get("historical_uncertain_effects", [])),
            "help": _bounded_items(help_value.get("issues", [])) if isinstance(help_value, Mapping) else [],
            "help_state": {key: help_value[key] for key in ("state", "status", "reason") if key in help_value}
                if isinstance(help_value, Mapping) else {"state": "unknown"},
            "blockers": _bounded_items(status_value.get("blockers", [])),
        },
        "budget": budget_value,
        "inventory": inventory_value,
        "attributed_notes": _notes(status_value, reports),
        "next_action": _json(next_action) if isinstance(next_action, Mapping) else {
            "supported": True, "operation": "status", "reason": "read current canonical state"
        },
        "authority": {"read_only": True, "dispatch": False, "owner_write": False,
                      "suggestions_are_authority": False},
        "sources": {
            "project": _source(project or {}, ref_value=project_pin),
            "assignment": _source(assignment_value, ref_value=assignment_value.get("ref")),
            "current_occurrence": {"sha256": current.get("source_sha256"), "schedule_id": current.get("schedule_id"), "version": current.get("version")},
            "status": _source(status_value),
            "effective_context": _source(effective),
            "inventory": _source(inventory_value),
            "help": _source(help_value),
            "budget": _source(budget_value),
        },
    }
    envelope["envelope_sha256"] = _digest(envelope)
    return envelope


__all__ = ["ManagerHandoffError", "compose_manager_handoff"]
