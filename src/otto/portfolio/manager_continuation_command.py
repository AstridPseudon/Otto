"""Consume explicit durable reports through the existing same-manager operation."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .execution_operations import derive_manager_continuation_request


def manager_continuation_from_command(
    *, request: Mapping[str, Any], execution: Any, anchor_schedule_id: str,
    current_schedule_id: str, task_refs: Mapping[str, Any], native_session_id: str,
    read_reports: Callable[[], list[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Prepare by default. Unknown current effects require a scoped owner disposition before dispatch.

    A trusted controller chooses the last verified anchor. Only an explicit
    report on the same owner manager/project can create a new continuation;
    the historical unknown is never recovered with execute=True or rewritten.
    """
    operation = request.get("operation", "prepare")
    key = request.get("report_key")
    if operation not in {"status", "prepare", "dispatch", "dispose-no-overlap"}:
        raise ValueError("operation must be status, prepare, dispatch or dispose-no-overlap")
    if not isinstance(key, str) or not key.strip() or key != key.strip():
        raise ValueError("report_key must identify one exact durable manager report")
    try:
        anchor = execution._read(anchor_schedule_id)
        current = execution._read(current_schedule_id)
    except ValueError as exc:
        if operation != "dispose-no-overlap":
            raise
        return {"outcome": "rejected", "provider_called": False, "retry": False,
                "error": {"code": "owner_scope_unavailable", "message": str(exc)}}
    if (anchor.role != "manager" or current.role != "manager"
            or anchor.generation != current.generation
            or anchor.assignment_ref["id"] != current.assignment_ref["id"]
            or anchor.target.get("native_id", (anchor.last_result or {}).get("physical_session_id")) != native_session_id
            or (anchor.last_result or {}).get("physical_session_id") != native_session_id):
        raise ValueError("verified anchor and current manager identity differ")
    # The owner event reader includes immutable reports across assignment
    # resource revisions; a revision-local observation listing loses them.
    reports = read_reports()
    selected = derive_manager_continuation_request(anchor, reports, report_key=key)
    base = {"schema": "otto.manager-service-continuation.v1", "report_key": key,
            "anchor_schedule_id": anchor_schedule_id, "current_schedule_id": current_schedule_id,
            "native_session_id": native_session_id, "operation": operation, "retry": False}
    if selected is None:
        return {**base, "outcome": "idle", "provider_called": False}
    task = task_refs.get(selected.get("task_alias"))
    if task is None:
        raise ValueError("continuation report selects an unknown task")
    report = next(value["value"] for value in reports
                  if value["ref"] == selected["report_ref"])
    if report.get("task_ref") != task:
        return {**base, "outcome": "held", "provider_called": False, "reason": "report task revision is stale"}
    unknown = current.completion_state == "unknown" or (
        isinstance(current.host_evidence, Mapping)
        and ((current.host_evidence.get("gateway_attempt") or {}).get("result") or {}).get("outcome") == "unknown")
    if operation == "status":
        scope, retained, error = None, None, None
        if unknown:
            try:
                scope = _no_overlap_scope(execution, anchor, current, selected, native_session_id, task)
                retained = _retained_no_overlap(scope, reports)
            except ValueError as exc:
                error = str(exc)
        return {**base, "outcome": "read", "request": selected,
                "current_unknown_effect": unknown, "provider_called": False,
                "expected_disposition_pins": None if scope is None else _disposition_pins(scope),
                "no_overlap_disposition_ref": None if retained is None else retained["ref"],
                "no_overlap_evidence_error": error,
                "dispatch_held_by_current_unknown": unknown and retained is None}
    disposition = None
    if operation == "dispose-no-overlap" or (operation == "dispatch" and unknown):
        try:
            scope = _no_overlap_scope(execution, anchor, current, selected, native_session_id, task)
        except ValueError as exc:
            return {**base, "outcome": "rejected" if operation == "dispose-no-overlap" else "held",
                    "provider_called": False, "reason": str(exc),
                    "current_unknown_effect": unknown}
        if operation == "dispose-no-overlap":
            recorded = _record_no_overlap(request, execution, scope, reports)
            return {**base, **recorded, "provider_called": False, "current_unknown_effect": unknown,
                    "historical_unknown_preserved": True}
        disposition = _retained_no_overlap(scope, reports)
        if disposition is None:
            return {**base, "outcome": "held", "request": selected,
                    "provider_called": False, "reason": "current manager unknown effect requires owner disposition"}
    result = execution.continue_manager(schedule_id=anchor_schedule_id, report_key=key,
        task_ref=task, execute=operation == "dispatch", reports=reports)
    return {**base, "outcome": result.get("outcome"), "continuation": result,
            "request": selected, "current_unknown_effect": unknown,
            "no_overlap_disposition_ref": None if disposition is None else disposition["ref"],
            **({"provider_called": False} if operation != "dispatch" else {})}


def _no_overlap_scope(execution, anchor, current, selected, native_session_id, task):
    """Read-only evidence for one new intent; never resolves the old effect."""
    from herzchen.contracts import ResourceRef
    from otto.attention import DueRecord
    from .execution import _digest
    from .execution_operations import manager_continuation_schedule_id
    assignment = execution.assignments.get(ResourceRef.from_dict(current.assignment_ref))
    attempt = (current.host_evidence or {}).get("gateway_attempt") or {}
    prior_result = current.last_result or {}
    observed = attempt.get("result") or {}
    if (assignment.role != "manager" or assignment.principal != execution.actor
            or assignment.generation != current.generation
            or assignment.scope.id != current.project_ref
            or current.target.get("native_id") != native_session_id
            or attempt.get("physical_session_id") != native_session_id
            or observed.get("physical_session_id") != native_session_id
            or prior_result.get("physical_session_id") != native_session_id):
        raise ValueError("current owner manager identity does not match")
    execution._verify_native_binding(assignment, native_session_id, anchor.schedule_id)
    if (current.stop_state != "completed" or current.in_flight_request is not None
            or current.completion_state != "unknown" or current.delivery_state != "unknown"
            or attempt.get("state") != "result" or attempt.get("process_created") is not False
            or prior_result.get("native_session_created") is not False
            or observed.get("observed_turn_id") is not None
            or observed.get("outcome") != "unknown" or prior_result.get("outcome") != "unknown"
            or prior_result.get("retry_allowed") is not False
            or prior_result.get("delivery_state") != "preprovider_unknown"
            or (attempt.get("delivery_admission") or {}).get("native_turn_started") is True):
        raise ValueError("current readback does not establish the bounded no-overlap condition")
    turn = selected.get("settled_turn_id")
    if not isinstance(turn, str) or not turn.strip():
        raise ValueError("verified anchor has no completed native turn")
    callback_id = manager_continuation_schedule_id(anchor.assignment_ref, selected["logical_request_key"])
    value = execution.due_port.read_due(callback_id)
    if value is None:
        raise ValueError("same report-key continuation must already be prepared")
    callback = DueRecord.from_dict(value)
    if (callback.role != "manager" or callback.generation != current.generation
            or callback.assignment_ref["id"] != current.assignment_ref["id"]
            or callback.target.get("native_id") != native_session_id
            or callback.target.get("task_ref") != task
            or callback.project_ref != current.project_ref
            or callback.in_flight_request != selected["logical_request_key"]
            or callback.stop_state != "active" or callback.completion_state != "none"
            or (callback.host_evidence or {}).get("gateway_attempt") is not None):
        raise ValueError("new continuation is no longer the exact unexecuted owner intent")
    return {"project_ref": dict(anchor.target["project_ref"]), "task_ref": dict(task),
            "report_key": selected["logical_request_key"], "report_ref": selected["report_ref"],
            "anchor_schedule_id": anchor.schedule_id, "latest_completed_turn_id": turn,
            "current_schedule_id": current.schedule_id, "current_version": current.version,
            "current_due_sha256": _digest(current.to_dict()),
            "continuation_schedule_id": callback_id, "continuation_version": callback.version,
            "manager_assignment_ref": assignment.ref.to_dict(), "manager_principal": assignment.principal,
            "generation": assignment.generation, "native_session_id": native_session_id,
            "process_created": False, "native_session_created": False, "in_flight_request": None}


def _disposition_pins(scope):
    return {"expected_current_schedule_id": scope["current_schedule_id"],
            "expected_current_version": scope["current_version"],
            "expected_continuation_schedule_id": scope["continuation_schedule_id"],
            "expected_continuation_version": scope["continuation_version"],
            "expected_project_id": scope["project_ref"]["id"],
            "expected_manager": scope["manager_principal"], "expected_generation": scope["generation"],
            "expected_native_session_id": scope["native_session_id"],
            "expected_latest_turn_id": scope["latest_completed_turn_id"]}


def _record_no_overlap(request, execution, scope, reports):
    from herzchen.contracts import ResourceRef
    pins = _disposition_pins(scope)
    for field, value in pins.items():
        if type(request.get(field)) is not type(value) or request.get(field) != value:
            return {"outcome": "rejected", "error": {"code": "stale_or_foreign_disposition", "field": field}}
    key = request.get("request_key")
    if not isinstance(key, str) or not key.strip() or key != key.strip():
        raise ValueError("request_key must be exact non-blank text")
    body = {"schema": "otto.manager-no-overlap-disposition.v1", "project_ref": scope["project_ref"],
            "logical_request_key": key, "disposition": "allow-new-explicit-intent-without-replaying-unknown",
            "scope": scope, "historical_unknown_preserved": True, "provider_called": False}
    prior = next((row for row in reports if (row.get("value") or {}).get("logical_request_key") == key), None)
    if prior is not None:
        if prior.get("value") != body:
            return {"outcome": "rejected", "error": {"code": "input_changed"}}
        return {"outcome": "replayed", "disposition_ref": prior["ref"], "scope": scope}
    observation = execution.assignments.append_report(ResourceRef.from_dict(scope["manager_assignment_ref"]),
        body, expected_generation=scope["generation"], logical_request_key=key,
        actor=execution.binding.authenticated_actor(execution.actor))
    return {"outcome": "committed", "disposition_ref": observation.ref.to_dict(), "scope": scope}


def _retained_no_overlap(scope, reports):
    return next((row for row in reports if row.get("kind") == "report"
        and (row.get("assignment") or {}).get("id") == scope["manager_assignment_ref"]["id"]
        and (row.get("value") or {}).get("schema") == "otto.manager-no-overlap-disposition.v1"
        and (row.get("value") or {}).get("scope") == scope), None)
