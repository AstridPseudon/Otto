"""Per-request identity projection at an explicitly trusted host ingress.

The host authenticates its connection/session independently of the JSON body
and supplies HostCallerBinding. This module joins existing owner records; it
does not authenticate arbitrary file writers, issue credentials or cache an
agent roster. Visible launch IDs and native correlation alone are not grants.
"""
from dataclasses import dataclass
from typing import Any, Mapping

from herzchen.contracts import AuthenticatedActor, ResourceRef, canonical_json
from .owner_readers import json_value


@dataclass(frozen=True)
class HostIngress:
    transport: str
    handle: Any


@dataclass(frozen=True)
class HostCallerBinding:
    actor: AuthenticatedActor
    assignment_ref: ResourceRef
    generation: int
    adapter: str
    native_session_id: str
    schedule_id: str


def resolve_caller_context(application: Any, binding: HostCallerBinding) -> dict[str, Any]:
    """Reconstruct on every call/reopen; no identity comes from prompt memory."""
    if not isinstance(binding, HostCallerBinding) or not isinstance(binding.actor, AuthenticatedActor):
        raise PermissionError("unbound caller; establish a trusted host session binding")
    if (not isinstance(binding.assignment_ref, ResourceRef) or not binding.assignment_ref.revision
            or type(binding.generation) is not int or binding.generation < 1
            or binding.actor.authority != application.binding.authority
            or binding.actor.credential_ref != application.binding.credential_ref
            or binding.adapter != application.native_adapter_identity()):
        raise PermissionError("caller binding does not belong to this owner/adapter")
    current = application.assignments.get(binding.assignment_ref)
    assignment = application._current(current.ref.to_dict(), binding.generation)
    if (assignment.ref != binding.assignment_ref
            and assignment.payload.get("resource_adoption_base_ref") != binding.assignment_ref.to_dict()):
        raise PermissionError("caller assignment pin changed outside supported resource adoption; refresh host binding")
    if binding.actor.actor != assignment.principal or assignment.status in {"retired", "cancelled"}:
        raise PermissionError("caller principal differs from current assignment")
    due = application._read(binding.schedule_id).to_dict()
    target = due.get("target") or {}
    attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
    authorization = attempt.get("delivery_authorization") or {}
    admission = attempt.get("delivery_admission") or {}
    role = "worker" if assignment.role == "executor" else assignment.role
    if (due.get("generation") != binding.generation or due.get("recipient") != binding.actor.actor
            or due.get("role") != role or due.get("assignment_ref") != binding.assignment_ref.to_dict()
            or target.get("assignment_ref") != binding.assignment_ref.to_dict()
            or target.get("principal") != binding.actor.actor or target.get("role") != role
            or (target.get("native_id") or authorization.get("physical_session_id")) != binding.native_session_id
            or target.get("native_adapter") != binding.adapter
            or due.get("stop_state") not in {"active", "completed"}
            or due.get("lifecycle_owner") != application.actor):
        raise PermissionError("caller occurrence/session is stale or belongs to another responsibility")
    if (authorization.get("status") != "authorized"
            or authorization.get("assignment_ref") != binding.assignment_ref.to_dict()
            or authorization.get("generation") != binding.generation
            or authorization.get("principal") != binding.actor.actor
            or authorization.get("physical_session_id") != binding.native_session_id
            or authorization.get("project_ref") != target.get("project_ref")
            or authorization.get("task_ref") != target.get("task_ref")
            or authorization.get("logical_request_key") not in {
                due.get("in_flight_request"), due.get("last_completed_request")}
            ):
        raise PermissionError("caller has no exact admitted native occurrence; use owner binding/recovery")
    result = attempt.get("result") or {}
    evidence = result.get("task_bound_evidence") or {}
    observed = (admission.get("native_turn_started") is True
                and admission.get("physical_session_id") == binding.native_session_id)
    retained = (result.get("outcome") == "succeeded" and result.get("context_digest_verified") is True
        and evidence.get("session_id") == binding.native_session_id
        and evidence.get("assignment_ref") == binding.assignment_ref.to_dict()
        and evidence.get("generation") == binding.generation
        and evidence.get("owner_delivery_authorization") == authorization
        and evidence.get("delivered_brief_digest") == authorization.get("brief_sha256"))
    if not observed and not retained:
        raise PermissionError("caller native occurrence has no verified admission/readback")
    application._verify_native_binding(assignment, binding.native_session_id, binding.schedule_id)
    # Detect reuse from existing current occurrence/assignment records. IDs are
    # adapter-qualified; historical replaced generations are not new callers.
    for other in application.due_port.list_due({"native_adapter": binding.adapter,
                                               "native_session_id": binding.native_session_id}):
        if other.get("schedule_id") == binding.schedule_id:
            continue
        other_target = other.get("target") or {}
        other_attempt = (other.get("host_evidence") or {}).get("gateway_attempt") or {}
        other_auth = other_attempt.get("delivery_authorization") or {}
        if (other_target.get("native_adapter") != binding.adapter
                or other_auth.get("physical_session_id") != binding.native_session_id
                or other_auth.get("status") != "authorized" or other.get("generation") is None
                or not isinstance(other.get("assignment_ref"), Mapping)):
            continue
        other_pin = ResourceRef.from_dict(other["assignment_ref"])
        if (other_pin.authority, other_pin.kind, other_pin.id) == (
                binding.assignment_ref.authority, binding.assignment_ref.kind, binding.assignment_ref.id):
            continue
        current = application.assignments.get(other_pin)
        if current.generation == other["generation"]:
            raise PermissionError("native session is reused by another current responsibility; reconcile owner bindings")
    # Caller identity is not an admission of the historical turn's task
    # effects. Ordinary project/task edits must not revoke a valid caller.
    # Read current membership/access; each command still checks its own pins.
    from .owner_readers import project_reader, task_reader
    operations = application.portfolio.operations
    identity = lambda ref: {key: ref[key] for key in ("authority", "kind", "id")}
    project = project_reader(operations, target["project_ref"])(identity(target["project_ref"]))
    task = task_reader(operations, project["ref"], target["task_ref"])(identity(target["task_ref"]))
    reader = getattr(application.portfolio.operations, "direction_context_reader", None)
    directions = [] if reader is None else reader(assignment_ref=assignment.ref.to_dict(),
        generation=assignment.generation, project_ref=project["ref"], task_ref=task["ref"])
    return {"schema": "otto.caller-context.v1", "source": "trusted host binding and current canonical records",
        "principal": assignment.principal, "role": role,
        "responsibility_ref": json_value(assignment.payload["responsibility_ref"]),
        "assignment_ref": assignment.ref.to_dict(), "generation": assignment.generation,
        "project_ref": project["ref"], "task_ref": task["ref"],
        "native_session": {"adapter": binding.adapter, "id": binding.native_session_id},
        "occurrence_ref": {"schedule_id": binding.schedule_id,
                           "assignment_ref": binding.assignment_ref.to_dict(),
                           "logical_request_key": authorization["logical_request_key"]},
        "direction_context": directions, "read_only": True,
        "authority": "caller identity only; commands retain their existing authorization"}


def check_caller_claims(context: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Optional claims may agree with a binding; they cannot choose one.

    `principal`/`assignment_ref` in ordinary commands remain explicit targets.
    Caller claims use distinct names and are removed before the command handler.
    """
    expected = {"caller_principal": context["principal"],
        "logical_agent_id": context["principal"], "caller_assignment_ref": context["assignment_ref"],
        "caller_generation": context["generation"], "caller_native_session_id": context["native_session"]["id"]}
    if any(key in request and canonical_json(request[key]) != canonical_json(value) for key, value in expected.items()):
        raise PermissionError("claimed caller identity conflicts with trusted host binding")
    if "caller_context" in request or "host_caller_binding" in request:
        raise PermissionError("caller context must come from host ingress, never request JSON")
    return {key: value for key, value in request.items() if key not in expected}
