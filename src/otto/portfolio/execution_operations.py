"""Owner-side preparation for one canonical role occurrence.

This module composes the existing assignment and DueRecord command ports. It
does not own a scheduler, Store, provider, or second execution ledger.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from herzchen.contracts import ResourceRef


class OccurrencePreparationError(ValueError):
    """The requested occurrence cannot be joined to current owner state."""


_MODES = {
    ("invoke", "launch"): "fresh_bounded_worker",
    ("resume", "resume"): "continue_existing",
    ("resume", "callback"): "continue_existing",
}


def prepare_current_assignment_occurrence(
    *, due_port: Any, assignments: Any, binding: Any, due: Any,
    assignment_ref: Mapping[str, Any], assignment_owner: str,
    operation: str, lifecycle: str, request_key: str,
) -> dict[str, Any]:
    """Create a Due on the adoption base, then reconcile it to current refs.

    Both committed stages are returned so a caller can distinguish a partial
    effect from a failure before any owner mutation.
    """

    if not isinstance(request_key, str) or not request_key.strip():
        raise OccurrencePreparationError("request_key is required")
    expected_mode = _MODES.get((operation, lifecycle))
    if expected_mode is None:
        raise OccurrencePreparationError("unsupported operation/lifecycle pair")
    if getattr(due, "execution_mode", None) != expected_mode:
        raise OccurrencePreparationError(
            "execution_mode must be " + expected_mode + " for " + operation + "/" + lifecycle
        )
    target = getattr(due, "target", None)
    if not isinstance(target, Mapping):
        raise OccurrencePreparationError("due target is unavailable")
    native_id = target.get("native_id")
    if expected_mode == "continue_existing" and not isinstance(native_id, str):
        raise OccurrencePreparationError("continue_existing requires target.native_id")
    if expected_mode != "continue_existing" and native_id is not None:
        raise OccurrencePreparationError("fresh occurrence cannot claim an existing native session")

    try:
        current = assignments.get(ResourceRef.from_dict(assignment_ref))
        actor = binding.authenticated_actor(assignment_owner)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise OccurrencePreparationError("current assignment or owner actor is unavailable") from exc
    if actor.actor != assignment_owner:
        raise OccurrencePreparationError("authenticated actor differs from assignment owner")
    if assignment_owner not in {getattr(current, "manager", None), getattr(current, "principal", None)}:
        raise OccurrencePreparationError("resource adoption actor is not assignment owner")

    base_value = getattr(current, "payload", {}).get("resource_adoption_base_ref")
    base_ref = ResourceRef.from_dict(base_value) if isinstance(base_value, Mapping) else current.ref
    target_value = dict(target)
    target_value["assignment_ref"] = base_ref.to_dict()
    prepared = replace(due, assignment_ref=base_ref.to_dict(), target=target_value)
    created = due_port.save_due(
        due.schedule_id, prepared.to_dict(), request_id=request_key + ":create", expected_version=0,
    )
    result = {
        "outcome": "partial", "stage": "due_created", "schedule_id": due.schedule_id,
        "assignment_base_ref": base_ref.to_dict(), "assignment_current_ref": current.ref.to_dict(),
        "due_version": created["version"], "replay_key": request_key,
        "execution_mode": expected_mode, "actor": actor.actor,
    }
    try:
        reconciled = due_port.reconcile_assignment_resources(
            due.schedule_id, assignment_ref=current.ref.to_dict(),
            expected_version=created["version"], request_id=request_key + ":resources",
        )
    except Exception as exc:
        return {
            **result, "error": {"code": type(exc).__name__, "message": str(exc)},
            "next_action": "inspect the named Due before retrying resource reconciliation",
        }
    return {
        **result, "outcome": "committed", "stage": "resources_reconciled",
        "due_version": reconciled["version"],
        "next_action": "invoke the admitted role against this exact occurrence",
    }


__all__ = ["OccurrencePreparationError", "prepare_current_assignment_occurrence"]
