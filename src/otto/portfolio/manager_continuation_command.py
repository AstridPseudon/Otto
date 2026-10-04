"""Consume explicit durable reports through the existing same-manager operation."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .execution_operations import derive_manager_continuation_request


def manager_continuation_from_command(
    *, request: Mapping[str, Any], execution: Any, anchor_schedule_id: str,
    current_schedule_id: str, task_refs: Mapping[str, Any], native_session_id: str,
    read_reports: Callable[[], list[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Prepare by default. Unknown current native effects always block dispatch.

    A trusted controller chooses the last verified anchor. Only an explicit
    report on the same owner manager/project can create a new continuation;
    the historical unknown is never recovered with execute=True or rewritten.
    """
    operation = request.get("operation", "prepare")
    key = request.get("report_key")
    if operation not in {"status", "prepare", "dispatch"}:
        raise ValueError("operation must be status, prepare or dispatch")
    if not isinstance(key, str) or not key.strip() or key != key.strip():
        raise ValueError("report_key must identify one exact durable manager report")
    anchor = execution._read(anchor_schedule_id)
    current = execution._read(current_schedule_id)
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
        return {**base, "outcome": "read", "request": selected,
                "current_unknown_effect": unknown, "provider_called": False}
    if operation == "dispatch" and unknown:
        return {**base, "outcome": "held", "request": selected,
                "provider_called": False, "reason": "current manager unknown effect requires owner disposition"}
    result = execution.continue_manager(schedule_id=anchor_schedule_id, report_key=key,
        task_ref=task, execute=operation == "dispatch", reports=reports)
    return {**base, "outcome": result.get("outcome"), "continuation": result,
            "request": selected, "current_unknown_effect": unknown,
            **({"provider_called": False} if operation != "dispatch" else {})}
