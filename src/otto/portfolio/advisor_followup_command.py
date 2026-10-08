"""Thin owner IPC adapter for an existing advisor effect-follow-up schedule."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .advisor_delivery import effect_followup_schedule_id


def advisor_followup_from_command(
    *, request: Mapping[str, Any], project_ref: Mapping[str, Any],
    read_due: Callable[[str], Any], dispatch: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    """Read by default; explicit dispatch uses only the supplied owner operation.

    The adapter creates no schedule, changes no runtime pins, and grants no
    admission. Dispatch retains the existing Due and allowance guards. A paused
    canonical host/configuration blocks dispatch even if explicitly requested.
    """
    operation = request.get("operation", "status")
    if operation not in {"status", "dispatch"}:
        raise ValueError("operation must be status or dispatch")
    schedule_id, decision_id = request.get("schedule_id"), request.get("decision_id")
    for name, value in (("schedule_id", schedule_id), ("decision_id", decision_id)):
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or "\x00" in value):
            raise ValueError(name + " must be exact non-blank text")
    if schedule_id != effect_followup_schedule_id(project_ref, decision_id):
        raise ValueError("schedule_id does not identify this project's decision follow-up")
    base = {"schema": "otto.advisor-followup-command.v1", "schedule_id": schedule_id,
            "decision_id": decision_id, "operation": operation, "retry": False}
    try:
        record = read_due(schedule_id)
    except Exception as exc:
        return {**base, "outcome": "unknown", "dispatch_called": False, "provider_called": False,
                "error": {"code": "followup_read_failed", "message": str(exc)}}
    if (not isinstance(record, Mapping) or record.get("schedule_id") != schedule_id
            or record.get("project_ref") != project_ref["id"]
            or record.get("role") != "project_advisor"
            or record.get("purpose") != "advisor-effect-followup"):
        return {**base, "outcome": "unknown", "dispatch_called": False, "provider_called": False,
                "error": {"code": "followup_unavailable_or_foreign"}}
    if operation == "status":
        return {**base, "outcome": "read", "read_only": True, "dispatch_called": False,
                "provider_called": False, "record": dict(record)}
    target = record.get("target") or {}
    automation = target.get("automation") if isinstance(target, Mapping) else None
    if (record.get("host_state") in {"paused", "pending", "failed"}
            or (automation is not None and
                (not isinstance(automation, Mapping) or automation.get("status") != "ACTIVE"))):
        return {**base, "outcome": "held", "dispatch_called": False, "provider_called": False,
                "reason": "canonical host trigger is paused or not ready"}
    try:
        result = dispatch(schedule_id=schedule_id, decision_id=decision_id)
    except Exception as exc:
        # Preparation may reject a stale/in-flight occurrence, or dispatch may
        # have lost its response. Never infer success or authorize another call.
        return {**base, "outcome": "unknown", "dispatch_called": True,
                "error": {"code": "followup_dispatch_requires_inspection", "message": str(exc)}}
    if not isinstance(result, Mapping):
        return {**base, "outcome": "unknown", "dispatch_called": True,
                "error": {"code": "followup_dispatch_result_invalid"}}
    return {**dict(result), **base, "dispatch_called": True}
