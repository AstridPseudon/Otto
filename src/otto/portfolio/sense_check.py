"""Pure hourly portfolio sense-check for the existing manager route.

ORC-05 is intentionally smaller than a scheduler.  It compares two supplied
manager snapshots, filters observation-only timestamps, and either stays
quiet when nothing meaningful changed or emits one idempotent same-manager
action.  It does not persist status, launch work, notify externally, or grant
owner/project acceptance.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


class SenseCheckError(ValueError):
    """The supplied status, mandate, or custody is outside ORC-05 scope."""


_TRUSTED_SOURCES = frozenset({"user", "root_transport", "owner"})
_OBSERVATION_KEYS = frozenset({"observed_at", "checked_at", "receipt_at", "captured_at"})
_RESULT_SCHEMA = "otto.orchestrator.orc05.hourly_sense_check.v1"


def _copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise SenseCheckError("values must be JSON-compatible") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise SenseCheckError(f"{field} must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SenseCheckError(f"{field} must be a reference object")
    result = _copy(dict(value))
    _text(result.get("id"), f"{field}.id")
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _status_projection(value: Any) -> Any:
    """Remove observation-only timestamps recursively before comparison."""

    if isinstance(value, Mapping):
        return {key: _status_projection(item) for key, item in value.items() if key not in _OBSERVATION_KEYS}
    if isinstance(value, list):
        return [_status_projection(item) for item in value]
    return value


def _same_ref(actual: Mapping[str, Any], expected: Mapping[str, Any], field: str) -> None:
    observed = _ref(actual, field)
    pinned = _ref(expected, f"expected_{field}")
    for key in ("authority", "kind", "id", "revision"):
        if key in pinned and observed.get(key) != pinned[key]:
            raise SenseCheckError(f"{field} does not match the pinned custody")


def _validate_custody(
    *,
    expected_project_ref: Mapping[str, Any],
    expected_task_ref: Mapping[str, Any],
    expected_assignment_ref: Mapping[str, Any],
    expected_generation: int,
    observed_custody: Mapping[str, Any],
    manager_ref: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
        raise SenseCheckError("expected_generation must be a positive integer")
    if not isinstance(observed_custody, Mapping):
        raise SenseCheckError("observed_custody must be an object")
    project = _ref(expected_project_ref, "expected_project_ref")
    task = _ref(expected_task_ref, "expected_task_ref")
    assignment = _ref(expected_assignment_ref, "expected_assignment_ref")
    manager = _ref(manager_ref, "manager_ref")
    for value, field in ((project, "project_ref"), (task, "task_ref"), (assignment, "assignment_ref")):
        if "revision" not in value:
            raise SenseCheckError(f"{field} must include a pinned revision")
    _same_ref(observed_custody.get("project_ref"), project, "project_ref")
    _same_ref(observed_custody.get("task_ref"), task, "task_ref")
    _same_ref(observed_custody.get("assignment_ref"), assignment, "assignment_ref")
    if observed_custody.get("generation") != expected_generation:
        raise SenseCheckError("observed custody generation does not match the pinned assignment")
    return project, task, assignment, manager


def _validate_worker(worker_observation: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(worker_observation, Mapping):
        raise SenseCheckError("worker_observation must be an object")
    worker = _copy(dict(worker_observation))
    for field in ("native_id", "requested_model", "requested_reasoning", "observed_model", "observed_reasoning"):
        _text(worker.get(field), f"worker_observation.{field}")
    if worker.get("role") != "worker" or worker.get("owner_write") is not False:
        raise SenseCheckError("reused context must remain a worker without owner-write custody")
    return worker


def hourly_sense_check(
    *,
    previous_status: Mapping[str, Any],
    current_status: Mapping[str, Any],
    mandate: Mapping[str, Any],
    action: Mapping[str, Any],
    expected_project_ref: Mapping[str, Any],
    expected_task_ref: Mapping[str, Any],
    expected_assignment_ref: Mapping[str, Any],
    expected_generation: int,
    observed_custody: Mapping[str, Any],
    manager_ref: Mapping[str, Any],
    worker_observation: Mapping[str, Any],
    orc04_prerequisite: Mapping[str, Any],
    brief_sha256: str,
    prior_results: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Compare one manager snapshot and route at most one same-manager action."""

    if not isinstance(previous_status, Mapping) or not isinstance(current_status, Mapping):
        raise SenseCheckError("status snapshots must be objects")
    if not isinstance(mandate, Mapping):
        raise SenseCheckError("mandate must be an object")
    if mandate.get("trusted") is not True or mandate.get("source") not in _TRUSTED_SOURCES:
        raise SenseCheckError("mandate is not trusted")
    if mandate.get("state") not in {"active", "execute"}:
        raise SenseCheckError("mandate is not active")
    if mandate.get("mode") not in {"coordination", "execution"}:
        raise SenseCheckError("mandate mode is outside the sense-check boundary")
    action_value = _copy(dict(action)) if isinstance(action, Mapping) else None
    if not action_value or not action_value.get("id") or action_value.get("admitted") is not True:
        raise SenseCheckError("action must be one already-admitted bounded action")
    _text(action_value.get("id"), "action.id")
    _text(action_value.get("operation"), "action.operation")
    if action_value.get("route") != "existing_manager_worker_path" or action_value.get("bounded") is not True:
        raise SenseCheckError("action must use the existing bounded manager/worker route")
    project, task, assignment, manager = _validate_custody(
        expected_project_ref=expected_project_ref,
        expected_task_ref=expected_task_ref,
        expected_assignment_ref=expected_assignment_ref,
        expected_generation=expected_generation,
        observed_custody=observed_custody,
        manager_ref=manager_ref,
    )
    worker = _validate_worker(worker_observation)
    prerequisite = _ref(orc04_prerequisite, "orc04_prerequisite")
    previous = _status_projection(previous_status)
    current = _status_projection(current_status)
    previous_digest = _digest(previous)
    current_digest = _digest(current)
    changed = previous != current
    changed_fields = sorted(set(previous) | set(current)) if changed else []
    stable = {
        "schema": _RESULT_SCHEMA,
        "brief_sha256": _text(brief_sha256, "brief_sha256"),
        "action": action_value,
        "project_ref": project,
        "task_ref": task,
        "assignment_ref": assignment,
        "generation": expected_generation,
        "manager_ref": manager,
        "worker": worker,
        "orc04_prerequisite": prerequisite,
        "previous_digest": previous_digest,
        "current_digest": current_digest,
        "changed_fields": changed_fields,
    }
    operation_digest = _digest(stable)
    idempotency_key = "orc05-sense-check-" + operation_digest
    prior_keys = {item.get("idempotency_key") for item in prior_results if isinstance(item, Mapping)}
    replayed = idempotency_key in prior_keys
    if prerequisite.get("task_id") != "task-e0716950bd89bca14264f45a5cec" or prerequisite.get("state") != "completed":
        if not changed:
            outcome = "held_dependency_quiet"
            notify = False
        elif replayed:
            outcome = "held_dependency_replayed_noop"
            notify = False
        else:
            outcome = "held_dependency"
            notify = True
        result = {
            **stable,
            "idempotency_key": idempotency_key,
            "operation_sha256": operation_digest,
            "outcome": outcome,
            "replayed": replayed,
            "status_review": {"changed": changed, "previous_digest": previous_digest, "current_digest": current_digest, "changed_fields": changed_fields},
            "manager_action": None,
            "owner_disposition": {"status": "pending", "responsible_owner": manager, "next_resume_event": "ORC-04 completion is observed by the P2 manager"},
            "project_acceptance": False,
            "global_project_acceptance": False,
            "notify_manager": notify,
            "dispatch": False,
            "schedule_mutation": False,
            "live_controller_mutation": False,
            "p1_owner_writes_parked": True,
            "p1_open_obligations": ["BK-C06", "BK-C07"],
            "p2_code_oracle_used": 0,
        }
        result["result_sha256"] = _digest(result)
        return result
    if not changed:
        outcome = "unchanged_quiet"
        manager_action = None
        notify = False
    elif replayed:
        outcome = "replayed_noop"
        manager_action = None
        notify = False
    else:
        outcome = "manager_action_admitted"
        manager_action = {
            "id": action_value["id"],
            "operation": action_value["operation"],
            "route": "existing_manager_worker_path",
            "manager_ref": manager,
            "worker_native_id": worker["native_id"],
            "dispatch": False,
            "launch": False,
            "scope": "one bounded same-manager sense-check follow-up",
        }
        notify = True
    result = {
        **stable,
        "idempotency_key": idempotency_key,
        "operation_sha256": operation_digest,
        "outcome": outcome,
        "replayed": replayed,
        "status_review": {"changed": changed, "previous_digest": previous_digest, "current_digest": current_digest, "changed_fields": changed_fields},
        "manager_action": manager_action,
        "owner_disposition": {"status": "pending", "responsible_owner": manager, "next_resume_event": "P2 manager verifies the sense-check result and performs guarded disposition"},
        "project_acceptance": False,
        "global_project_acceptance": False,
        "notify_manager": notify,
        "dispatch": False,
        "schedule_mutation": False,
        "live_controller_mutation": False,
        "p1_owner_writes_parked": True,
        "p1_open_obligations": ["BK-C06", "BK-C07"],
        "p2_code_oracle_used": 0,
    }
    result["result_sha256"] = _digest(result)
    return result


__all__ = ["SenseCheckError", "hourly_sense_check"]
