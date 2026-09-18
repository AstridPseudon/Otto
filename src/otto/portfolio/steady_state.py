"""Pure steady-state guards for the ORC-06 manager handoff.

The functions here model the boundary the existing owner must use later:
generation fencing, failed-replacement rollback, and a single exact action
packet. They return records and never mutate the canonical owner, installed
binding, scheduler, or controller.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


class SteadyStateError(ValueError):
    """The proposed replacement or manager packet is outside ORC-06 scope."""


_RESULT_SCHEMA = "otto.orchestrator.orc06.steady_state_guard.v1"
_PACKET_SCHEMA = "otto.orchestrator.orc06.manager_action_packet.v1"


def _copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise SteadyStateError("values must be JSON-compatible") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise SteadyStateError(f"{field} must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SteadyStateError(f"{field} must be a reference object")
    result = _copy(dict(value))
    _text(result.get("id"), f"{field}.id")
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_generation(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SteadyStateError(f"{field} must be a positive integer")
    return value


def fence_replacement(
    *,
    current_binding: Mapping[str, Any],
    replacement_attempt: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    requested_generation: int,
    action_key: str,
    prior_results: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Hold late writers and preserve a qualified binding after failure."""

    binding = _copy(dict(current_binding)) if isinstance(current_binding, Mapping) else None
    attempt = _copy(dict(replacement_attempt)) if isinstance(replacement_attempt, Mapping) else None
    if not binding or not attempt:
        raise SteadyStateError("binding and replacement attempt must be objects")
    binding_id = _text(binding.get("binding_id"), "current_binding.binding_id")
    current_generation = _positive_generation(binding.get("generation"), "current_binding.generation")
    requested = _positive_generation(requested_generation, "requested_generation")
    attempt_generation = _positive_generation(attempt.get("generation"), "replacement_attempt.generation")
    key = _text(action_key, "action_key")
    if binding.get("status") not in {"qualified", "installed", "active"}:
        raise SteadyStateError("current binding is not a qualified installed binding")
    if attempt.get("binding_id") == binding_id:
        raise SteadyStateError("replacement must identify a distinct binding")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise SteadyStateError("history must be a sequence")
    preserved_history = _copy(list(history))
    stable = {
        "schema": _RESULT_SCHEMA,
        "action_key": key,
        "current_binding": binding,
        "replacement_attempt": attempt,
        "requested_generation": requested,
        "history": preserved_history,
    }
    operation_sha = _digest(stable)
    idempotency_key = "orc06-fence-" + operation_sha
    replayed = idempotency_key in {item.get("idempotency_key") for item in prior_results if isinstance(item, Mapping)}
    if requested != current_generation:
        outcome = "held_stale_generation"
        reason = "requested generation is not the current qualified binding generation"
        selected = binding
    elif attempt_generation <= current_generation:
        outcome = "held_late_writer"
        reason = "replacement attempt is from an old or already-consumed generation"
        selected = binding
    elif replayed:
        outcome = "replayed_noop"
        reason = "the same replacement decision was already recorded"
        selected = binding
    elif attempt.get("status") == "failed":
        outcome = "rollback_preserved"
        reason = "failed replacement is fenced and prior qualified binding remains selected"
        selected = binding
    else:
        outcome = "held_unqualified_replacement"
        reason = "replacement has no qualified success proof"
        selected = binding
    result = {
        **stable,
        "idempotency_key": idempotency_key,
        "operation_sha256": operation_sha,
        "outcome": outcome,
        "replayed": replayed,
        "reason": reason,
        "selected_binding": selected,
        "history_preserved": preserved_history,
        "canonical_mutation": False,
        "rollback_performed": outcome == "rollback_preserved",
        "schedule_mutation": False,
        "live_controller_mutation": False,
    }
    result["result_sha256"] = _digest(result)
    return result


def build_manager_action_packet(
    *,
    owner_api: str,
    project_ref: Mapping[str, Any],
    task_ref: Mapping[str, Any],
    assignment_ref: Mapping[str, Any],
    generation: int,
    manager_ref: Mapping[str, Any],
    action_key: str,
    qualified_binding: Mapping[str, Any],
    expected_evidence: Sequence[Mapping[str, Any]],
    rollback_disposition: Mapping[str, Any],
    retirement_disposition: Mapping[str, Any],
    source_lineage: Mapping[str, Any],
) -> dict[str, Any]:
    """Render one later owner action without executing it."""

    api = _text(owner_api, "owner_api")
    project = _ref(project_ref, "project_ref")
    task = _ref(task_ref, "task_ref")
    assignment = _ref(assignment_ref, "assignment_ref")
    manager = _ref(manager_ref, "manager_ref")
    gen = _positive_generation(generation, "generation")
    key = _text(action_key, "action_key")
    binding = _copy(dict(qualified_binding)) if isinstance(qualified_binding, Mapping) else None
    if not binding or binding.get("status") != "qualified_installed":
        raise SteadyStateError("qualified_binding must be a qualified installed origin")
    _text(binding.get("binding_id"), "qualified_binding.binding_id")
    _text(binding.get("origin"), "qualified_binding.origin")
    if not isinstance(expected_evidence, Sequence) or isinstance(expected_evidence, (str, bytes)) or not expected_evidence:
        raise SteadyStateError("expected_evidence must contain at least one item")
    evidence = [_copy(dict(item)) for item in expected_evidence]
    rollback = _copy(dict(rollback_disposition)) if isinstance(rollback_disposition, Mapping) else None
    retirement = _copy(dict(retirement_disposition)) if isinstance(retirement_disposition, Mapping) else None
    lineage = _copy(dict(source_lineage)) if isinstance(source_lineage, Mapping) else None
    if not rollback or not retirement or not lineage:
        raise SteadyStateError("rollback, retirement, and source lineage dispositions are required")
    stable = {
        "schema": _PACKET_SCHEMA,
        "owner_api": api,
        "project_ref": project,
        "task_ref": task,
        "assignment_ref": assignment,
        "generation": gen,
        "manager_ref": manager,
        "action_key": key,
        "qualified_binding": binding,
        "expected_evidence": evidence,
        "rollback_disposition": rollback,
        "retirement_disposition": retirement,
        "source_lineage": lineage,
    }
    packet_sha = _digest(stable)
    return {
        **stable,
        "packet_sha256": packet_sha,
        "idempotency_key": "orc06-owner-action-" + packet_sha,
        "route": "supported_existing_owner_api",
        "execute_now": False,
        "owner_acceptance": False,
        "status_separation": {
            "built": True,
            "tested": True,
            "installed": True,
            "selected": True,
            "active": False,
            "used": False,
            "heartbeat": False,
            "schedule": False,
            "project_acceptance": False,
        },
        "generation_fence": {"required": True, "expected_generation": gen, "late_writer": "hold"},
        "canonical_mutation": False,
    }


__all__ = ["SteadyStateError", "build_manager_action_packet", "fence_replacement"]
