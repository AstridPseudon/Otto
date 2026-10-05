"""Append-only owner disposition of an exact retained recipient-context failure."""
from __future__ import annotations

from typing import Any, Mapping
from herzchen.contracts import ResourceRef
from .execution import _digest
from .execution_operations import manager_continuation_schedule_id


def _mapping(value):
    if not isinstance(value, Mapping):
        raise ValueError("retained callback transport evidence is malformed")
    return value


def _scope(execution, anchor, current, selected, native_session_id):
    callback = execution._read(manager_continuation_schedule_id(
        anchor.assignment_ref, selected["logical_request_key"]))
    assignment = execution._current(callback.assignment_ref, callback.generation)
    execution._verify_native_binding(assignment, native_session_id, anchor.schedule_id)
    attempt = _mapping((callback.host_evidence or {}).get("gateway_attempt") or {})
    result = _mapping(attempt.get("result") or {})
    raw = _mapping(result.get("raw_result") or {})
    receipt = _mapping(raw.get("work_receipt") or {})
    envelope = _mapping(raw.get("work_envelope") or {})
    authorization = _mapping(raw.get("owner_delivery_authorization") or {})
    identity = _mapping(receipt.get("identity") or {})
    expected_authorization = {"status": "authorized", "logical_request_key": selected["logical_request_key"],
        "physical_session_id": native_session_id, "project_ref": callback.target["project_ref"],
        "task_ref": callback.target["task_ref"], "assignment_ref": callback.assignment_ref,
        "generation": callback.generation, "role": "manager", "principal": assignment.principal,
        "lifecycle_owner": execution.actor}
    diagnostic = execution.inspect_mandate(schedule_id=callback.schedule_id)
    contract = diagnostic["instruction_contract_scope"]
    if (assignment.role != "manager" or assignment.principal != execution.manager_actor
            or assignment.scope.id != callback.project_ref
            or callback.role != "manager" or callback.project_ref != current.project_ref
            or callback.assignment_ref["id"] != anchor.assignment_ref["id"]
            or callback.generation != anchor.generation
            or callback.target.get("native_id") != native_session_id
            or callback.target.get("task_ref") != anchor.target.get("task_ref")
            or callback.target.get("mandate_ref") != anchor.target.get("mandate_ref")
            or callback.in_flight_request != selected["logical_request_key"]
            or attempt.get("logical_request_key") != selected["logical_request_key"]
            or attempt.get("assignment_ref") != callback.assignment_ref
            or type(attempt.get("generation")) is not int or attempt.get("generation") != callback.generation
            or result.get("logical_request_key") != selected["logical_request_key"]
            or result.get("assignment_ref") != callback.assignment_ref
            or type(result.get("generation")) is not int or result.get("generation") != callback.generation
            or result.get("logical_agent_id") != assignment.principal
            or result.get("project_ref") != callback.target["project_ref"]
            or result.get("task_ref") != callback.target["task_ref"]
            or result.get("operation") != "resume"
            or result.get("request_fingerprint") != attempt.get("request_fingerprint")
            or attempt.get("delivery_authorization") != authorization
            or diagnostic["scope_mismatches"]
            or contract != {"task_ref": callback.target["task_ref"], "source": "canonical_owner",
                            "owner_actor": assignment.principal, "effect_profile": "workspace-write-manager"}
            or any(type(authorization.get(k)) is not type(v) or authorization.get(k) != v
                   for k, v in expected_authorization.items())):
        raise ValueError("retained callback identity, mandate or owner authorization is not exact")
    # These explicit transport diagnostics come from the maintained host's
    # exception boundary before Popen/provider launch. An existing roster
    # identity is allowed; it is not evidence of a newly started native turn.
    if (callback.stop_state != "active" or callback.completion_state != "none"
            or attempt.get("state") != "result" or attempt.get("process_created") is not False
            or _mapping(attempt.get("delivery_admission") or {}).get("native_turn_started") is not None
            or result.get("outcome") != "unknown" or result.get("delivery_state") != "unknown"
            or "observed_turn_id" not in result or result["observed_turn_id"] is not None
            or result.get("context_digest_verified") is not False
            or raw.get("transport_operation") != "resume"
            or raw.get("initialization_receipt") is not None or raw.get("initialization_envelope") is not None
            or receipt.get("operation") != "resume" or receipt.get("outcome") != "unknown"
            or receipt.get("unsupported_reason") != "recipient_context_unavailable"
            or envelope.get("unsupported_error") != "recipient_context_unavailable"
            or envelope.get("reconciliation") != "app_server_cleanup_failed"
            or envelope.get("delivery_state") != "not_started"
            or envelope.get("fnd_receipt") != receipt
            or identity.get("logical_agent_id") != assignment.principal
            or receipt.get("logical_request_key") != assignment.principal
            or envelope.get("logical_agent_id") != assignment.principal
            or identity.get("physical_session_id") not in (None, native_session_id)
            or envelope.get("physical_session_id") not in (None, native_session_id)
            or raw.get("task_bound_evidence") is not None or raw.get("native_candidate") is not None
            or raw.get("worker_content") != []
            or any(field not in body or body[field] is not None
                   for body in (receipt, envelope) for field in ("process_id", "result_ref"))
            or any(body.get(field) is not None and body.get(field) is not False
                   for body in (attempt, result, raw, receipt, envelope)
                   for field in ("provider_called", "native_session_created", "native_turn_started"))
            or any(body.get(field) is not None for body in (result, receipt, envelope)
                   for field in ("observed_model", "observed_reasoning", "observed_profile"))
            or any(body.get("observed_turn_id") is not None for body in (attempt, receipt, envelope))):
        raise ValueError("retained callback does not prove exact recipient_context_unavailable before provider execution")
    return {"project_ref": callback.target["project_ref"], "callback_schedule_id": callback.schedule_id,
        "callback_version": callback.version, "callback_due_sha256": _digest(callback.to_dict()),
        "attempt_sha256": _digest(attempt), "report_key": selected["logical_request_key"],
        "report_ref": selected["report_ref"], "anchor_schedule_id": anchor.schedule_id,
        "current_schedule_id": current.schedule_id, "current_version": current.version,
        "current_due_sha256": _digest(current.to_dict()), "assignment_ref": callback.assignment_ref,
        "manager_principal": assignment.principal, "generation": callback.generation,
        "native_session_id": native_session_id, "task_ref": callback.target["task_ref"],
        "mandate_ref": callback.target["mandate_ref"], "mandate_content_sha256": diagnostic["mandate_content_sha256"],
        "unsupported_error": "recipient_context_unavailable", "reconciliation": "app_server_cleanup_failed",
        "provider_called": False, "native_turn_started": False, "unknown_attempt_preserved": True}


def _pins(scope):
    return {"expected_continuation_schedule_id": scope["callback_schedule_id"],
        "expected_continuation_version": scope["callback_version"],
        "expected_current_schedule_id": scope["current_schedule_id"], "expected_current_version": scope["current_version"],
        "expected_project_id": scope["project_ref"]["id"], "expected_manager": scope["manager_principal"],
        "expected_generation": scope["generation"], "expected_native_session_id": scope["native_session_id"],
        "expected_execution_task_ref": scope["task_ref"], "expected_mandate_ref": scope["mandate_ref"],
        "expected_assignment_ref": scope["assignment_ref"], "expected_report_ref": scope["report_ref"],
        "expected_attempt_sha256": scope["attempt_sha256"], "expected_callback_due_sha256": scope["callback_due_sha256"],
        "expected_mandate_sha256": scope["mandate_content_sha256"]}


def preprovider_disposition(request, execution, anchor, current, selected, native_session_id, reports):
    try:
        scope = _scope(execution, anchor, current, selected, native_session_id)
    except ValueError as exc:
        return {"outcome": "rejected", "provider_called": False, "retry": False, "reason": str(exc)}
    base = {"provider_called": False, "retry": False, "dispatch_authorized": False,
            "same_callback_replay_allowed": False, "unknown_attempt_preserved": True}
    if request["operation"] == "preprovider-status":
        refs = [row["ref"] for row in reports if row.get("kind") == "report"
                and (row.get("assignment") or {}).get("id") == scope["assignment_ref"]["id"]
                and (row.get("value") or {}).get("schema") == "otto.manager-preprovider-disposition.v1"
                and (row.get("value") or {}).get("scope") == scope]
        return {**base, "outcome": "read", "scope": scope, "expected_preprovider_disposition_pins": _pins(scope),
                "retained_disposition_refs": refs}
    for field, value in _pins(scope).items():
        if type(request.get(field)) is not type(value) or request.get(field) != value:
            return {**base, "outcome": "rejected", "error": {"code": "stale_or_foreign_preprovider_disposition",
                "field": field, "requested": request.get(field), "actual": value}}
    key, action = request.get("request_key"), request.get("disposition")
    if not isinstance(key, str) or not key.strip() or key != key.strip():
        raise ValueError("request_key must be exact non-blank text")
    if action not in {"root-host-recovery", "fresh-explicit-manager-continuation"}:
        return {**base, "outcome": "rejected", "reason": "explicit supported disposition is required"}
    next_key = request.get("new_report_key")
    if action == "fresh-explicit-manager-continuation":
        if (not isinstance(next_key, str) or not next_key.strip() or next_key != next_key.strip()
                or next_key in {scope["report_key"], key}
                or execution.due_port.read_due(manager_continuation_schedule_id(anchor.assignment_ref, next_key)) is not None):
            return {**base, "outcome": "rejected", "reason": "fresh continuation requires a distinct new owner report key without an existing callback"}
    elif next_key is not None:
        return {**base, "outcome": "rejected", "reason": "root-host recovery does not create or reserve a report"}
    body = {"schema": "otto.manager-preprovider-disposition.v1", "project_ref": scope["project_ref"],
        "logical_request_key": key, "scope": scope, "disposition": action,
        "new_report_key": next_key, **base}
    prior = next((row for row in reports if (row.get("value") or {}).get("logical_request_key") == key), None)
    if prior is not None:
        if prior.get("value") != body:
            return {**base, "outcome": "rejected", "error": {"code": "input_changed"}}
        outcome, ref = "replayed", prior["ref"]
    else:
        # Recheck both retained records immediately before the authentic owner
        # report append. The command owner serializes mutations; no Due writes.
        if (_digest(execution._read(scope["callback_schedule_id"]).to_dict()) != scope["callback_due_sha256"]
                or _digest(execution._read(current.schedule_id).to_dict()) != scope["current_due_sha256"]):
            return {**base, "outcome": "rejected", "reason": "retained owner evidence changed before disposition"}
        observed = execution.assignments.append_report(ResourceRef.from_dict(scope["assignment_ref"]), body,
            expected_generation=scope["generation"], logical_request_key=key,
            actor=execution.binding.authenticated_actor(execution.actor))
        outcome, ref = "committed", observed.ref.to_dict()
    return {**base, "outcome": outcome, "disposition_ref": ref, "scope": scope,
        "new_owner_report_key_required": True, "new_report_key": next_key,
        "next_action": "restore recipient context at the root host; any fresh continuation requires a new explicit owner report and ordinary guarded admission"}
