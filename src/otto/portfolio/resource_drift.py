"""Exception-only resource delivery comparison over existing owner projections.

This selector reads a current manager-inbox projection and produces at most one
attention-only revisit proposal. It creates no ledger or schedule. A revisit
records attention, not a resource correction; a later fresh owner projection
must prove alignment before resource_sync_verified is true.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

from .resource_sync import ResourceSyncError, validate_resource_evidence


class ResourceDriftError(ValueError):
    """A supplied owner projection is malformed or outside the narrow contract."""


_RUNTIME_FIELDS = (
    "expected_manifest_digest", "observed_manifest_digest",
    "expected_module_origin", "observed_module_origin",
    "expected_module_sha256", "observed_module_sha256",
)
_SUCCESS_DELIVERY = frozenset({"completed", "attributed", "accepted"})


def _copy(value: Any, field: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ResourceDriftError(f"{field} must be JSON-compatible") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ResourceDriftError(f"{field} must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise ResourceDriftError(f"{field} must be a pinned reference")
    result = _copy(dict(value), field)
    for name in ("authority", "kind", "id", "revision"):
        _text(result.get(name), f"{field}.{name}")
    return {name: result[name] for name in ("authority", "kind", "id", "revision")}


def _identity(ref: Mapping[str, Any]) -> tuple[str, str, str]:
    return ref["authority"], ref["kind"], ref["id"]


def _identity_ref(value: Any, field: str) -> dict[str, str]:
    """Normalize an intentional identity-only owner operation reference."""
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise ResourceDriftError(f"{field} must be an owner reference")
    result = _copy(dict(value), field)
    return {name: _text(result.get(name), f"{field}.{name}") for name in ("authority", "kind", "id")}


def _same_pinned(left: Any, right: Any) -> bool:
    try:
        return _ref(left, "left_ref") == _ref(right, "right_ref")
    except ResourceDriftError:
        return False


def _digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _runtime_pair(value: Any) -> Optional[dict[str, str]]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ResourceDriftError("runtime_observation must be an object")
    return {name: _text(value.get(name), f"runtime_observation.{name}") for name in _RUNTIME_FIELDS}


def _key(material: Mapping[str, Any]) -> str:
    return "resource-drift-" + _digest(material)[:32]


def _scope_readiness(inbox: Mapping[str, Any], project_ref: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    scope = inbox.get("scope")
    observed_ref = scope.get("ref") if isinstance(scope, Mapping) else None
    if not isinstance(observed_ref, Mapping) or _identity(_ref(observed_ref, "inbox.scope.ref")) != _identity(project_ref):
        raise ResourceDriftError("manager inbox does not match the requested project scope")
    readiness = inbox.get("readiness")
    return readiness if isinstance(readiness, Mapping) else None


def _same_attention(readiness: Optional[Mapping[str, Any]], project_ref: Mapping[str, Any], key: str) -> bool:
    if not isinstance(readiness, Mapping) or readiness.get("kind") != "revisit" or readiness.get("dispatch") is not False:
        return False
    payload = readiness.get("payload")
    if not isinstance(payload, Mapping) or payload.get("attention_only") is not True:
        return False
    scope_ref = payload.get("project_ref")
    revisit = payload.get("revisit")
    return (
        isinstance(scope_ref, Mapping)
        and tuple(_identity_ref(scope_ref, "readiness.project_ref").values()) == _identity(project_ref)
        and isinstance(revisit, Mapping)
        and revisit.get("kind") == "resource_runtime_sync_drift"
        and revisit.get("discrepancy_key") == key
    )


def _owner_attention_receipt(inbox: Mapping[str, Any], project_ref: Mapping[str, Any], key: str) -> bool:
    """Find an exact owner-written revisit marker in the current event page."""
    reconciliation = inbox.get("reconciliation")
    events = reconciliation.get("events") if isinstance(reconciliation, Mapping) else None
    if isinstance(events, (str, bytes)) or not isinstance(events, Sequence):
        return False
    for event in events:
        if not isinstance(event, Mapping) or event.get("operation") != "work.revise":
            continue
        subject = event.get("subject")
        if not isinstance(subject, Mapping) or _identity(_ref(subject, "event.subject")) != _identity(project_ref):
            continue
        effects = event.get("effects")
        result_payload = effects.get("result_payload") if isinstance(effects, Mapping) else None
        readiness = result_payload.get("readiness") if isinstance(result_payload, Mapping) else None
        if _same_attention(readiness, project_ref, key):
            return True
    return False


def _dependency_result(outcome: str, key: str, dependency: str, material: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "otto.resource-drift.selection.v1",
        "outcome": outcome,
        "discrepancy_key": key,
        "dependency": dependency,
        "action": None,
        "resource_sync_verified": False,
        "verified_progress": False,
        "dispatch": False,
        "notify": False,
        "material": _copy(dict(material), "discrepancy_material"),
    }


def select_resource_sync_action(
    *,
    inbox: Mapping[str, Any],
    project_ref: Mapping[str, Any],
    task_ref: Mapping[str, Any],
    assignment_ref: Mapping[str, Any],
    attempt_ref: Mapping[str, Any],
    expected_generation: int,
    runtime_observation: Optional[Mapping[str, Any]],
    lifecycle: str,
) -> dict[str, Any]:
    """Select one safe exception response from a fresh manager-inbox read.

    `runtime_observation` is supplied by the host's source-pair probe; the
    selector compares expected/observed manifest and imported module origin
    digests, but does not itself inspect or attest a Python environment.
    """
    if lifecycle == "callback":
        return {
            "schema": "otto.resource-drift.selection.v1", "outcome": "unsupported_callback",
            "discrepancy_key": None, "dependency": "owner_due_record_callback_admission",
            "action": None, "resource_sync_verified": False, "verified_progress": False,
            "dispatch": False,
        }
    if lifecycle not in {"create", "child", "launch", "replace", "resume"}:
        raise ResourceDriftError("lifecycle is unsupported")
    if not isinstance(inbox, Mapping) or inbox.get("schema") != "otto.manager-inbox.v1":
        raise ResourceDriftError("inbox must be a current otto.manager-inbox.v1 projection")
    if inbox.get("read_side_effects") is not False or inbox.get("dispatch") is not False or inbox.get("launch") is not False:
        raise ResourceDriftError("manager inbox must be a read-only non-dispatching projection")
    project = _ref(project_ref, "project_ref")
    task = _ref(task_ref, "task_ref")
    assignment = _ref(assignment_ref, "assignment_ref")
    attempt_pin = _ref(attempt_ref, "attempt_ref")
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 1:
        raise ResourceDriftError("expected_generation must be a positive integer")
    readiness = _scope_readiness(inbox, project)
    scope = inbox["scope"]
    material_base: dict[str, Any] = {
        "project_identity": {key: project[key] for key in ("authority", "kind", "id")},
        "task_ref": task,
        "assignment_ref": assignment,
        # A DueRecord is the mutable carrier for the existing attempt. Host
        # acknowledgement/reconciliation changes its revision without changing
        # that attempt, so use its stable identity in discrepancy keys while
        # retaining the exact current pin for upstream owner readback checks.
        "attempt_ref": ({key: attempt_pin[key] for key in ("authority", "kind", "id")}
                        if attempt_pin.get("kind") == "otto.due-record" else attempt_pin),
        "generation": expected_generation,
        "lifecycle": lifecycle,
    }

    assignments = inbox.get("assignments")
    if isinstance(assignments, (str, bytes)) or not isinstance(assignments, Sequence):
        raise ResourceDriftError("inbox.assignments must be a list")
    binding = next((item for item in assignments if isinstance(item, Mapping) and _same_pinned(item.get("source_ref"), assignment)), None)
    if binding is None:
        material = {**material_base, "state": "assignment_missing"}
        return _dependency_result("held_assignment_missing", _key(material), "current_assignment_readback", material)
    if binding.get("generation") != expected_generation or not _same_pinned(binding.get("source_ref"), assignment):
        material = {**material_base, "state": "stale_assignment", "observed_assignment": binding.get("source_ref"), "observed_generation": binding.get("generation")}
        return _dependency_result("held_stale_assignment", _key(material), "refresh_current_assignment", material)
    if binding.get("status") not in {"queued", "in-flight", "reassigned", "active", "in_progress", "pending"}:
        material = {**material_base, "state": "assignment_not_live", "observed_status": binding.get("status")}
        return _dependency_result("held_assignment_not_live", _key(material), "refresh_current_assignment", material)
    role = binding.get("role")
    if role not in {"orchestrator", "manager", "executor", "worker"}:
        material = {**material_base, "state": "assignment_role_unknown", "observed_role": role}
        return _dependency_result("held_assignment_role_unknown", _key(material), "refresh_current_assignment", material)
    scope_ref = binding.get("scope_ref")
    if not isinstance(scope_ref, Mapping) or _identity(_ref(scope_ref, "assignment.scope_ref")) not in {_identity(project), _identity(task)}:
        material = {**material_base, "state": "assignment_scope_mismatch", "observed_scope_ref": scope_ref}
        return _dependency_result("held_assignment_scope_mismatch", _key(material), "refresh_current_assignment_scope", material)
    tasks = inbox.get("tasks")
    if isinstance(tasks, (str, bytes)) or not isinstance(tasks, Sequence):
        raise ResourceDriftError("inbox.tasks must be a list")
    if not any(isinstance(item, Mapping) and _same_pinned(item.get("ref"), task) for item in tasks):
        material = {**material_base, "state": "task_missing_or_stale"}
        return _dependency_result("held_task_missing_or_stale", _key(material), "refresh_current_task", material)
    pins_raw = binding.get("pins", ())
    if isinstance(pins_raw, (str, bytes)) or not isinstance(pins_raw, Sequence):
        raise ResourceDriftError("assignment pins are malformed")
    pins = sorted((_ref(item, "assignment.pin") for item in pins_raw), key=lambda item: (item["authority"], item["kind"], item["id"], item["revision"]))
    material_base["adopted_resource_refs"] = pins

    attempts = inbox.get("attempts")
    if isinstance(attempts, (str, bytes)) or not isinstance(attempts, Sequence):
        raise ResourceDriftError("inbox.attempts must be a list")
    observed = next((item for item in attempts if isinstance(item, Mapping) and _same_pinned(item.get("source_ref"), attempt_pin)), None)
    if observed is None:
        material = {**material_base, "state": "attempt_missing"}
        return _dependency_result("held_attempt_missing", _key(material), "read_current_attempt", material)
    if not _same_pinned(observed.get("assignment_ref"), assignment) or observed.get("generation") != expected_generation:
        material = {**material_base, "state": "attempt_custody_mismatch", "observed_assignment": observed.get("assignment_ref"), "observed_generation": observed.get("generation")}
        return _dependency_result("held_stale_attempt", _key(material), "reconcile_attempt_custody", material)
    if observed.get("task_ref") is None or not _same_pinned(observed.get("task_ref"), task):
        material = {**material_base, "state": "attempt_task_mismatch", "observed_task_ref": observed.get("task_ref")}
        return _dependency_result("held_stale_attempt", _key(material), "reconcile_attempt_scope", material)
    attempt = observed.get("attempt")
    attempt = attempt if isinstance(attempt, Mapping) else observed
    evidence_value = attempt.get("resource_evidence") if isinstance(attempt, Mapping) else None
    runtime = _runtime_pair(runtime_observation)
    material_base["runtime_observation"] = runtime
    material_base["attempt_state"] = {
        "outcome": attempt.get("outcome"),
        "delivery_state": evidence_value.get("delivery_state") if isinstance(evidence_value, Mapping) else None,
        "request_fingerprint": attempt.get("request_fingerprint"),
        "resource_evidence_sha256": evidence_value.get("brief_sha256") if isinstance(evidence_value, Mapping) else None,
        "resource_set_digest": evidence_value.get("resource_set_digest") if isinstance(evidence_value, Mapping) else None,
    }
    if runtime is None:
        material = {**material_base, "state": "runtime_probe_missing"}
        return _dependency_result("held_runtime_probe_missing", _key(material), "runtime_source_pair_probe", material)
    runtime_matches = (
        runtime["expected_manifest_digest"] == runtime["observed_manifest_digest"]
        and runtime["expected_module_origin"] == runtime["observed_module_origin"]
        and runtime["expected_module_sha256"] == runtime["observed_module_sha256"]
    )
    if not runtime_matches:
        material = {**material_base, "state": "runtime_source_pair_mismatch"}
        return _dependency_result("held_runtime_source_mismatch", _key(material), "runtime_origin_match_before_operation", material)
    if not isinstance(evidence_value, Mapping):
        material = {**material_base, "state": "resource_delivery_evidence_missing"}
        return _dependency_result("held_resource_evidence_missing", _key(material), "reconcile_delivery_evidence", material)
    fingerprint = attempt.get("request_fingerprint")
    if attempt.get("outcome") != "succeeded" or evidence_value.get("delivery_state") not in _SUCCESS_DELIVERY or not isinstance(fingerprint, str) or not fingerprint.strip():
        material = {**material_base, "state": "attempt_not_verified_success"}
        return _dependency_result("held_attempt_not_verified", _key(material), "reconcile_attempt_before_retry", material)
    try:
        evidence = validate_resource_evidence(
            evidence_value,
            role="worker" if binding.get("role") == "executor" else binding.get("role"),
            responsibility_ref=assignment,
            generation=expected_generation,
        )
    except ResourceSyncError as exc:
        material = {**material_base, "state": "resource_evidence_invalid", "reason": str(exc)}
        return _dependency_result("held_resource_evidence_invalid", _key(material), "reconcile_resource_evidence", material)
    delivered = sorted(
        (_ref(item.get("resource_ref"), "delivered.resource_ref") for item in evidence.get("resources", ()) if isinstance(item, Mapping)),
        key=lambda item: (item["authority"], item["kind"], item["id"], item["revision"]),
    )
    material_base["delivered_resource_refs"] = delivered
    material_base["resource_set_digest"] = evidence["resource_set_digest"]
    material_base["brief_sha256"] = evidence["brief_sha256"]
    if delivered == pins:
        return {
            "schema": "otto.resource-drift.selection.v1", "outcome": "resource_sync_aligned",
            "discrepancy_key": _key(material_base), "dependency": None, "action": None,
            "resource_sync_verified": True, "verified_progress": False, "dispatch": False, "notify": False,
        }
    key = _key(material_base)
    if _same_attention(readiness, project, key) or _owner_attention_receipt(inbox, project, key):
        return {
            "schema": "otto.resource-drift.selection.v1", "outcome": "already_attentioned",
            "discrepancy_key": key, "dependency": None, "action": None,
            "resource_sync_verified": False, "verified_progress": False, "dispatch": False, "notify": False,
        }
    reconciliation = inbox.get("reconciliation")
    if not isinstance(reconciliation, Mapping) or reconciliation.get("gap") is True or reconciliation.get("has_more") is True or reconciliation.get("status") == "advanced":
        material = {**material_base, "state": "owner_event_history_incomplete"}
        return _dependency_result("held_owner_event_history_incomplete", _key(material), "refresh_manager_inbox_safety_scan", material)
    request_id = "resource-drift-action-" + _digest({"key": key})[:32]
    action = {
        "operation": "work.pending.revisit",
        "request_id": request_id,
        "revisit": {
            "kind": "resource_runtime_sync_drift",
            "discrepancy_key": key,
            "task_ref": task,
            "assignment_ref": assignment,
            "generation": expected_generation,
            "expected_resource_refs": pins,
            "delivered_resource_refs": delivered,
            "resource_set_digest": evidence["resource_set_digest"],
            "brief_sha256": evidence["brief_sha256"],
            "runtime_observation": runtime,
            "dispatch": False,
            "launch": False,
        },
        "project_ref": {name: project[name] for name in ("authority", "kind", "id")},
    }
    return {
        "schema": "otto.resource-drift.selection.v1", "outcome": "selected_revisit",
        "discrepancy_key": key, "dependency": None, "action": action,
        "resource_sync_verified": False, "verified_progress": False, "dispatch": False, "notify": True,
    }


def apply_resource_sync_action(*, portfolio: Any, project_ref: Any, actor: str, selection: Mapping[str, Any]) -> dict[str, Any]:
    """Record one selected attention-only revisit and verify its owner readback.

    This operation does not correct a resource pin or attest task progress.
    """
    if not isinstance(selection, Mapping) or selection.get("outcome") != "selected_revisit" or not isinstance(selection.get("action"), Mapping):
        raise ResourceDriftError("only one selected revisit may be applied")
    action = selection["action"]
    if action.get("operation") != "work.pending.revisit":
        raise ResourceDriftError("selected action is not the supported owner revisit")
    selected_project = _identity_ref(action.get("project_ref"), "selection.project_ref")
    requested_project = _ref(project_ref, "project_ref")
    if tuple(selected_project[name] for name in ("authority", "kind", "id")) != _identity(requested_project):
        raise ResourceDriftError("project_ref does not match the selected revisit scope")
    operation_project_ref = dict(selected_project)
    result = portfolio.revisit(operation_project_ref, action.get("revisit"), actor=actor, request_id=action.get("request_id"))
    readback = portfolio.read_pending(operation_project_ref, actor=actor)
    record = readback.get("record") if isinstance(readback, Mapping) else None
    payload = record.get("payload") if isinstance(record, Mapping) else None
    readiness = payload.get("readiness") if isinstance(payload, Mapping) else None
    ready_payload = readiness.get("payload") if isinstance(readiness, Mapping) else None
    revisit = ready_payload.get("revisit") if isinstance(ready_payload, Mapping) else None
    scope = ready_payload.get("project_ref") if isinstance(ready_payload, Mapping) else None
    receipt = result.get("receipt") if isinstance(result, Mapping) else None
    current_project = record.get("project_ref") if isinstance(record, Mapping) else None
    recorded = bool(
        isinstance(result, Mapping) and result.get("outcome") in {"attention-created", "replayed"}
        and isinstance(receipt, Mapping) and receipt.get("logical_request_key") == action.get("request_id")
        and receipt.get("operation") == "work.revise"
        and _same_pinned(receipt.get("result_ref"), current_project)
        and isinstance(readiness, Mapping) and readiness.get("kind") == "revisit"
        and readiness.get("dispatch") is False
        and isinstance(ready_payload, Mapping) and ready_payload.get("attention_only") is True
        and isinstance(scope, Mapping) and tuple(_identity_ref(scope, "readback.project_ref").values()) == _identity(requested_project)
        and isinstance(revisit, Mapping) and revisit.get("discrepancy_key") == selection.get("discrepancy_key")
    )
    return {
        "outcome": "attention_recorded" if recorded else "attention_readback_unknown",
        "discrepancy_key": selection.get("discrepancy_key"),
        "owner_result": _copy(dict(result), "owner_result") if isinstance(result, Mapping) else None,
        "readback_project_ref": record.get("project_ref") if isinstance(record, Mapping) else None,
        "attention_recorded": recorded,
        "resource_sync_verified": False,
        "verified_progress": False,
        "dispatch": False,
    }


__all__ = ["ResourceDriftError", "apply_resource_sync_action", "select_resource_sync_action"]
