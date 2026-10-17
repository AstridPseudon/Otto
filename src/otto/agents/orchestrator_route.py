"""Owner-authorized preparation for one resource-aware host operation.

This is the narrow bridge between durable assignment state and the neutral
gateway.  It does not dispatch by itself: the caller supplies the current
assignment reader, canonical content reader, gateway, and host request.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from otto.portfolio.resource_sync import (
    ResourceSyncError,
    brief_resource_evidence,
    compose_role_brief,
    normalize_instruction_contract,
    resolve_assignment_attachments,
)

from .gateway import OttoGateway, Responsibility
from otto.portfolio.operating_brief import OperatingBriefError, prepare_canonical_operating_brief
from .herzchen_adapter import HerzchenCodexAdapter
from .codex_host_reader import CodexAppServerThreadReader


class OrchestratorRouteError(ValueError):
    """The owner route cannot prepare a current assignment-bound operation."""


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if hasattr(value, "payload") and hasattr(value, "ref"):
        value = dict(value.payload, assignment_ref=value.ref.to_dict())
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise OrchestratorRouteError(f"{field} must be an object")
    result = dict(value)
    payload = result.get("payload")
    if isinstance(payload, Mapping) and "resource_adoptions" in payload:
        for key in ("resource_adoptions", "resource_adoption_revision", "resource_adoption_digest"):
            if key in result and result[key] != payload.get(key):
                raise OrchestratorRouteError("assignment instruction adoption projections conflict")
            result[key] = payload.get(key)
    return result


def _same_value(left: Any, right: Any) -> bool:
    return json.dumps(left.to_dict() if hasattr(left, "to_dict") else left, sort_keys=True, separators=(",", ":"), default=str) == json.dumps(right.to_dict() if hasattr(right, "to_dict") else right, sort_keys=True, separators=(",", ":"), default=str)


def _same_ref(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    keys = ("authority", "kind", "id", "revision")
    return all(key not in left or left.get(key) == right.get(key) for key in keys)


def prepare_assignment_role_brief(
    *,
    assignment_ref: Mapping[str, Any],
    assignment_reader: Callable[[Any], Any],
    resource_reader: Any,
    lifecycle: str,
    operating_core: Mapping[str, Any],
    context: Mapping[str, Any],
    required_resource_names: Sequence[str],
    expected_generation: int,
    delivery_state: str = "prepared",
    native_identity: str | None = None,
) -> dict[str, Any]:
    """Read current assignment pins, compose its brief, and make evidence."""

    if not callable(assignment_reader):
        raise OrchestratorRouteError("assignment_reader is required")
    if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
        raise OrchestratorRouteError("expected_generation must be a positive integer")
    try:
        assignment = _mapping(assignment_reader(assignment_ref), "assignment")
    except OrchestratorRouteError:
        raise
    except Exception as exc:
        raise OrchestratorRouteError("current assignment could not be read") from exc
    current_ref = assignment.get("assignment_ref", assignment.get("ref"))
    if not isinstance(current_ref, Mapping) or not _same_ref(assignment_ref, current_ref):
        raise OrchestratorRouteError("assignment identity changed while preparing the brief")
    generation = assignment.get("generation")
    if generation != expected_generation:
        raise OrchestratorRouteError("assignment generation is stale before preparing the brief")
    role = assignment.get("role")
    if role == "executor":
        role = "worker"
    try:
        attachments = resolve_assignment_attachments(assignment, resource_reader, role=role)
        brief = compose_role_brief(
            role=role,
            responsibility_ref=current_ref,
            generation=generation,
            lifecycle=lifecycle,
            operating_core=operating_core,
            context=context,
            attachments=attachments,
            required_resource_names=required_resource_names,
            reader=resource_reader,
            resource_adoption={"revision": assignment.get("resource_adoption_revision"),
                               "digest": assignment.get("resource_adoption_digest")},
        )
        evidence = brief_resource_evidence(
            brief,
            delivery_state=delivery_state,
            native_identity=native_identity,
        )
    except ResourceSyncError as exc:
        raise OrchestratorRouteError(str(exc)) from exc
    refreshed = _mapping(assignment_reader(assignment_ref), "assignment")
    refreshed_ref = refreshed.get("assignment_ref", refreshed.get("ref"))
    if not isinstance(refreshed_ref, Mapping) or not _same_value(current_ref, refreshed_ref) or refreshed.get("generation") != expected_generation or not _same_value(assignment, refreshed):
        raise OrchestratorRouteError("assignment changed while preparing the brief")
    return {"assignment": assignment, "brief": brief, "resource_evidence": evidence}


def invoke_assignment(
    *,
    gateway: OttoGateway,
    assignment_ref: Mapping[str, Any],
    assignment_reader: Callable[[Any], Any],
    resource_reader: Any,
    owner: str,
    logical_agent_id: str,
    operation: str,
    packet_digest: str,
    project_ref: Any,
    task_ref: Any,
    logical_request_key: str,
    request: Mapping[str, Any],
    lifecycle: str,
    operating_core: Mapping[str, Any],
    context: Mapping[str, Any],
    required_resource_names: Sequence[str],
    expected_generation: int,
    physical_session_id: str | None = None,
    requested_model: str = "gpt-5.6-luna",
    requested_reasoning: str = "high",
    requested_profile: str = "default",
) -> Any:
    """Prepare the exact role brief and invoke the existing gateway once."""

    if not isinstance(request, Mapping):
        raise OrchestratorRouteError("request must be an object")
    if gateway.attempt_capture is None or not callable(getattr(gateway.attempt_capture, "validate_generation", None)):
        raise OrchestratorRouteError("owner generation/replay gate is unavailable")
    prepared = prepare_assignment_role_brief(
        assignment_ref=assignment_ref,
        assignment_reader=assignment_reader,
        resource_reader=resource_reader,
        lifecycle=lifecycle,
        operating_core=operating_core,
        context=context,
        required_resource_names=required_resource_names,
        expected_generation=expected_generation,
        native_identity=physical_session_id,
    )
    evidence = prepared["resource_evidence"]
    bound_request = dict(request)
    # Evidence stores the immutable brief body without its self-referential
    # digest and idempotency key; this exact body is what the gateway requires
    # at the adapter boundary.
    bound_request["resource_brief"] = evidence["brief"]
    bound_request["resource_brief_sha256"] = evidence["brief_sha256"]
    expected_fields = {
        "logical_agent_id": logical_agent_id,
        "physical_session_id": physical_session_id,
        "requested_profile": requested_profile,
        "target_ref": task_ref,
    }
    for field, expected in expected_fields.items():
        if field in bound_request and bound_request[field] is not None and not _same_value(bound_request[field], expected):
            raise OrchestratorRouteError(f"request {field} conflicts with the fenced responsibility")
        bound_request[field] = expected
    assignment = prepared["assignment"]
    responsibility = Responsibility(
        owner,
        logical_agent_id,
        operation,
        packet_digest,
        physical_session_id=physical_session_id,
        requested_model=requested_model,
        requested_reasoning=requested_reasoning,
        requested_profile=requested_profile,
        logical_request_key=logical_request_key,
        project_ref=project_ref,
        task_ref=task_ref,
        assignment_ref=assignment.get("assignment_ref", assignment.get("ref")),
        generation=assignment["generation"],
        resource_evidence=evidence,
    )
    return gateway.operation(responsibility, bound_request)


def compose_owner_resource_herzchen_adapter(
    *,
    owner: str,
    source: str,
    worktree: str,
    launcher: str,
    host_context_path: str,
    native_trace_path: str | None = None,
    trusted_thread_reader: Callable[[str], Mapping[str, Any]] | None = None,
    trusted_sessions_root: str | None = None,
    requested_model: str = "gpt-5.6-luna",
    requested_reasoning: str = "high",
) -> HerzchenCodexAdapter:
    """Compose the production bridge with a host-owned context capture.

    The scheduled owner-resource path must bind the concrete JSONL reader at
    composition time.  A caller cannot accidentally construct the bridge in
    its permissive fixture mode and then claim that a native result was
    host-attested.
    """

    if (not isinstance(host_context_path, str) or not Path(host_context_path).is_absolute()
            or ".." in Path(host_context_path).parts):
        raise OrchestratorRouteError("absolute host_context_path is required for the owner-resource host path")
    if trusted_thread_reader is None:
        trusted_thread_reader = CodexAppServerThreadReader(
            launcher=launcher, sessions_root=trusted_sessions_root,
            scope_latch_path=host_context_path + ".metadata-reader-scope.json",
        )
    return HerzchenCodexAdapter(
        owner=owner,
        source=source,
        worktree=worktree,
        launcher=launcher,
        requested_model=requested_model,
        requested_reasoning=requested_reasoning,
        host_context_path=host_context_path,
        native_trace_path=native_trace_path,
        trusted_thread_reader=trusted_thread_reader,
        require_host_context=True,
    )


def prepare_canonical_assignment_role_brief(
    *, role: str, project_ref: Mapping[str, Any], assignment_ref: Mapping[str, Any],
    mandate_ref: Mapping[str, Any], expected_generation: int,
    project_reader: Callable[[Mapping[str, Any]], Any],
    assignment_reader: Callable[[Mapping[str, Any]], Any],
    mandate_reader: Callable[[Mapping[str, Any]], Any], resource_reader: Any,
    lifecycle: str, as_of: str, required_resource_names: Sequence[str] = (),
    task_ref: Mapping[str, Any] | None = None,
    task_reader: Callable[[Mapping[str, Any]], Any] | None = None,
    operating_context_reader: Callable[[], Mapping[str, Any] | None] | None = None,
    supervisor_reader: Callable[[], Mapping[str, Any] | None] | None = None,
    include_role_context: bool = True,
    direction_context_reader: Any = None,
    completed_support_refs: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    """Prepare role instructions only from current canonical owner reads.

    Canonical inputs are reread after potentially slow resource resolution.
    This detects observed changes but does not replace the final owner CAS
    needed when delivering to a host. Child resources come only from that
    child's explicit assignment pins. Callback preparation does not dispatch.
    """
    def canonical_read() -> dict[str, Any]:
        try:
            return prepare_canonical_operating_brief(
                role=role, project_ref=project_ref, assignment_ref=assignment_ref,
                mandate_ref=mandate_ref, expected_generation=expected_generation,
                project_reader=project_reader, assignment_reader=assignment_reader,
                mandate_reader=mandate_reader, resource_reader=resource_reader, as_of=as_of,
                task_ref=task_ref, task_reader=task_reader,
                direction_context_reader=direction_context_reader,
                completed_support_refs=completed_support_refs,
            )
        except OperatingBriefError as exc:
            raise OrchestratorRouteError(str(exc)) from exc

    canonical = canonical_read()
    # Detach the first observation: a reader may reuse a mutable projection.
    operating_context = None if operating_context_reader is None else json.loads(json.dumps(operating_context_reader()))
    render = canonical["render"]
    adopted = render["brief"]
    core = {
        "role": role,
        "operating_contract": render["role_instructions"],
        "mandate": adopted["mandate"],
        "user_constraints": adopted["user_constraints"],
        "priorities": adopted["priorities"],
        "operational_constraints": adopted["operational_constraints"],
        "continuation": adopted["continuation"],
        "links": adopted["links"],
    }
    context = {"canonical_snapshot": render["snapshot"], "project_state": render["project_state"]}
    # Mandatory on all routes, including callback/override preparation which
    # omits the optional generic role introduction.
    context["direction_context"] = canonical["direction_context"]
    from otto.portfolio.role_context import selected_configuration
    configuration = selected_configuration(canonical["supporting_context"])
    required_manager_context = role == "manager" and ((configuration is not None and configuration["content"].get("manager_context_required") is True) or isinstance(render["project_state"]["project"].get("payload", {}).get("metadata", {}).get("otto_orchestrator"), Mapping))
    supervisor = None
    observed_supervisor = None
    if include_role_context or required_manager_context:
        from otto.portfolio.role_context import role_introduction, selected_configuration
        context["supporting_context"] = canonical["supporting_context"]
        context["selected_configuration"] = selected_configuration(canonical["supporting_context"])
        recipient = ((operating_context or {}).get("operational_help") or {}).get("recipient")
        observed_supervisor = None if supervisor_reader is None else supervisor_reader()
        supervisor = observed_supervisor
        if supervisor is None and role == "manager" and isinstance(recipient, Mapping):
            supervisor = {"project_ref": render["project_state"]["project"]["ref"],
                          **{k: recipient[k] for k in ("assignment_ref", "generation", "principal", "conversation_ref")}}
        core["introduction"] = role_introduction(canonical, operational_supervisor=supervisor)
    if operating_context is not None:
        context["operating_setup"] = operating_context
    if "mandate_instruction_contract" in canonical:
        context["mandate_instruction_contract"] = canonical["mandate_instruction_contract"]

    def read_current_assignment(_ref: Mapping[str, Any]) -> Any:
        # The low-level preparation seam accepts a pinned reference for
        # comparison. Keep that fence locally while giving the owner only a
        # detached identity lookup, matching the canonical-reader contract.
        identity_ref = {key: assignment_ref[key] for key in ("authority", "kind", "id")}
        return assignment_reader(json.loads(json.dumps(identity_ref)))

    prepared = prepare_assignment_role_brief(
        assignment_ref=assignment_ref, assignment_reader=read_current_assignment,
        resource_reader=resource_reader, lifecycle=lifecycle,
        operating_core=core, context=context,
        required_resource_names=required_resource_names,
        expected_generation=expected_generation,
    )
    fresh = canonical_read()
    if fresh["evidence_sha256"] != canonical["evidence_sha256"]:
        raise OrchestratorRouteError("canonical owner state changed during resource resolution")
    if role == "manager" and (include_role_context or required_manager_context) and supervisor_reader is not None and not _same_value(observed_supervisor, supervisor_reader()):
        raise OrchestratorRouteError("manager supervisor changed during resource resolution")
    if operating_context_reader is not None and not _same_value(operating_context, operating_context_reader()):
        raise OrchestratorRouteError("operating role context changed during resource resolution")
    prepared["canonical_evidence"] = canonical
    return prepared


def prepare_canonical_callback(**kwargs: Any) -> dict[str, Any]:
    """Prepare callback evidence for an owner callback caller; never dispatch."""
    if kwargs.get("lifecycle") != "callback":
        raise OrchestratorRouteError("callback preparation requires lifecycle='callback'")
    prepared = prepare_canonical_assignment_role_brief(**kwargs)
    return {**prepared, "dispatch": False, "callback_admission": "unsupported_without_owner_due_record"}


def _canonical_operation_evidence(prepared: Mapping[str, Any], *, owner: str,
                                  task_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Bind adopted role context to one read-only operation, never task effects.

    Explicit contracts come from current task metadata or scoped execution mandate evidence.
    Otherwise this route inspects the delivered owner context. It invents
    neither filesystem targets nor host observation evidence.
    """
    render = prepared["canonical_evidence"]["render"]
    task = render["project_state"].get("task")
    if not isinstance(task, Mapping) or task.get("ref") != task_ref:
        raise OrchestratorRouteError("operation contract requires the exact canonical task")
    payload = task.get("payload", {})
    metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
    explicit = metadata.get("instruction_contract") if isinstance(metadata, Mapping) else None
    mandate_source = prepared["canonical_evidence"].get("mandate_instruction_contract")
    if mandate_source is not None:
        snapshot = render["snapshot"]
        if (not isinstance(mandate_source, Mapping)
                or mandate_source.get("source_ref") != prepared["canonical_evidence"]["source_refs"]["mandate"]
                or mandate_source.get("task_ref") != task_ref
                or mandate_source.get("assignment_ref") != snapshot["assignment_ref"]
                or mandate_source.get("generation") != snapshot["generation"]
                or mandate_source.get("dispatch_enabled") is not True):
            raise OrchestratorRouteError("execution mandate contract evidence is not exact")
        try:
            mandate_contract = normalize_instruction_contract(mandate_source.get("instruction_contract"))
            if explicit is not None and normalize_instruction_contract(explicit) != mandate_contract:
                raise OrchestratorRouteError("task and execution mandate contracts conflict")
        except ResourceSyncError as exc:
            raise OrchestratorRouteError(str(exc)) from exc
        explicit = mandate_contract
    if explicit is None:
        explicit = {
            "task_ref": dict(task_ref),
            "objective": payload.get("title") or render["brief"]["mandate"],
            "bounded_operation": (
                "Inspect the delivered canonical task, adopted role instructions, mandate and "
                "continuation. Return observations and a proposed next step; do not execute task effects."
            ),
            "allowed_operations": ["read_only_inspection", "return_evidence"],
            "acceptance_criteria": [
                "Identify the current task and assignment from the delivered owner snapshot.",
                "Report observations and missing evidence; keep proposed actions unexecuted.",
            ],
            "authority": {
                "source": "canonical_owner", "owner_actor": owner,
                "gateway_claim_required": True, "owner_write": False, "dispatch": False,
                "permitted_effects": ["read_delivered_context", "return_result"],
                "forbidden_effects": ["file_write", "owner_write", "dispatch", "publication", "package_adoption"],
            },
        }
    try:
        contract = normalize_instruction_contract(explicit)
    except ResourceSyncError as exc:
        raise OrchestratorRouteError(str(exc)) from exc
    if (contract["task_ref"] != task_ref or contract["authority"]["owner_actor"] != owner
            or contract["authority"]["source"] != "canonical_owner"):
        raise OrchestratorRouteError("operation instruction contract conflicts with canonical owner/task")
    body = dict(prepared["resource_evidence"]["brief"])
    body["instruction_contract"] = contract
    if mandate_source is not None:
        body["instruction_contract_source"] = dict(mandate_source)
    body["brief_sha256"] = hashlib.sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    body["idempotency_key"] = "otto-role-brief-" + body["brief_sha256"]
    return brief_resource_evidence(body)


def invoke_canonical_assignment(
    *, gateway: OttoGateway, role: str, project_ref: Mapping[str, Any],
    assignment_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any],
    assignment_reader: Callable[[Mapping[str, Any]], Any],
    project_reader: Callable[[Mapping[str, Any]], Any],
    mandate_reader: Callable[[Mapping[str, Any]], Any], resource_reader: Any,
    owner: str, logical_agent_id: str, operation: str, packet_digest: str,
    task_ref: Mapping[str, Any], logical_request_key: str,
    request: Mapping[str, Any], lifecycle: str, as_of: str,
    expected_generation: int, required_resource_names: Sequence[str] = (),
    task_reader: Callable[[Mapping[str, Any]], Any] | None = None,
    physical_session_id: str | None = None,
    requested_model: str = "gpt-5.6-luna", requested_reasoning: str = "high",
    requested_profile: str = "default",
    direction_context_reader: Any = None,
    operating_context_reader: Callable[[], Mapping[str, Any] | None] | None = None,
    supervisor_reader: Callable[[], Mapping[str, Any] | None] | None = None,
) -> Any:
    """Prepare and deliver from canonical role/project/assignment records."""
    valid_pairs = {"invoke": {"launch", "replace"}, "resume": {"resume"}, "send": {"resume"}}
    if operation not in valid_pairs or lifecycle not in valid_pairs[operation]:
        raise OrchestratorRouteError("lifecycle is not supported by this host operation")
    prepared = prepare_canonical_assignment_role_brief(
        role=role, project_ref=project_ref, assignment_ref=assignment_ref,
        mandate_ref=mandate_ref, expected_generation=expected_generation,
        project_reader=project_reader, assignment_reader=assignment_reader,
        mandate_reader=mandate_reader, resource_reader=resource_reader,
        lifecycle=lifecycle, as_of=as_of,
        required_resource_names=required_resource_names,
        task_ref=task_ref, task_reader=task_reader,
        operating_context_reader=operating_context_reader, supervisor_reader=supervisor_reader,
        direction_context_reader=direction_context_reader,
    )
    assignment = prepared["assignment"]
    from otto.portfolio.operating_setup import validate_execution_contract
    validate_execution_contract(prepared, requested_profile)
    evidence = _canonical_operation_evidence(prepared, owner=owner, task_ref=task_ref)
    if not isinstance(request, Mapping):
        raise OrchestratorRouteError("request must be an object")
    if gateway.attempt_capture is None or not callable(getattr(gateway.attempt_capture, "validate_generation", None)):
        raise OrchestratorRouteError("owner generation/replay gate is unavailable")
    bound = dict(request)
    bound["resource_brief"] = evidence["brief"]
    bound["resource_brief_sha256"] = evidence["brief_sha256"]
    for field, expected in {
        "logical_agent_id": logical_agent_id, "physical_session_id": physical_session_id,
        "requested_profile": requested_profile, "target_ref": task_ref,
    }.items():
        if field in bound and bound[field] is not None and not _same_value(bound[field], expected):
            raise OrchestratorRouteError(f"request {field} conflicts with the fenced responsibility")
        bound[field] = expected
    return gateway.operation(Responsibility(
        owner, logical_agent_id, operation, packet_digest,
        physical_session_id=physical_session_id,
        requested_model=requested_model, requested_reasoning=requested_reasoning,
        requested_profile=requested_profile, logical_request_key=logical_request_key,
        project_ref=project_ref, task_ref=task_ref,
        assignment_ref=assignment.get("assignment_ref", assignment.get("ref")),
        generation=assignment["generation"], resource_evidence=evidence,
    ), bound)


__all__ = [
    'prepare_canonical_assignment_role_brief',
    'prepare_canonical_callback',
    'invoke_canonical_assignment',

    "OrchestratorRouteError",
    "compose_owner_resource_herzchen_adapter",
    "invoke_assignment",
    "prepare_assignment_role_brief",
]
