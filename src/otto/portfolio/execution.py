"""Maintained owner composition for assignment, execution and continuation.

The existing assignment receipts and DueRecords are the recovery ledger. A host
supplies its adapter and keeps this application alive through admitted work.
No run paths, models, pilot budgets or cadence are selected here.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Mapping

from herzchen.contracts import ResourceRef
from herzchen.content.instructions import validate_instruction_content
from otto.attention import DueRecord
from .execution_operations import (
    OccurrencePreparationError, build_manager_callback_due,
    derive_manager_continuation_request, manager_continuation_schedule_id, prepare_current_assignment_occurrence,
    validate_owner_timeout_seconds,
)
from .owner_readers import json_value, owner_ref, task_reader
from .operating_brief import OperatingBrief
from .resource_sync import normalize_instruction_contract


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True,
                                   separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OccurrencePreparationError(name + " must be non-blank text")
    return value


def _identity(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {key: ref[key] for key in ("authority", "kind", "id")}


class ExecutionApplication:
    """Finite owner-issued commands; holds neither Store nor owner bootstrap.

    A returned partial operation names every committed handle. Calling the same
    request again completes preparation from public idempotent receipts. An
    existing gateway attempt is read/settled, never dispatched a second time.
    """

    def __init__(self, *, portfolio: Any, assignments: Any, due_port: Any,
                 binding: Any, actor: str, runtime: Any,
                 manager_actor: str | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.portfolio, self.assignments, self.due_port = portfolio, assignments, due_port
        self.binding, self.actor, self.runtime, self.clock = binding, actor, runtime, clock
        self.manager_actor = actor if manager_actor is None else _text(manager_actor, "manager_actor")
        self.binding.authenticated_actor(self.manager_actor)

    def _now(self) -> str:
        return self.clock().isoformat().replace("+00:00", "Z")

    def _current(self, ref: Mapping[str, Any], generation: int) -> Any:
        current = self.assignments.get(ResourceRef.from_dict(ref))
        if current.ref.to_dict() != dict(ref) or current.generation != generation:
            raise OccurrencePreparationError("assignment reference or generation is stale")
        if not {self.actor, self.manager_actor}.intersection({current.payload.get("manager"), current.principal}):
            raise OccurrencePreparationError("execution actor does not own the assignment")
        return current

    def assign_worker(self, *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                      principal: str, request_key: str, instructions: str,
                      instruction_contract: Mapping[str, Any], brief: Mapping[str, Any],
                      model: str, reasoning: str, profile: str = "workspace-write",
                      timeout_seconds: int = 1200) -> dict[str, Any]:
        """Assign and prepare a worker using the existing public owner commands."""
        project = owner_ref(project_ref, "project_ref")
        task = owner_ref(task_ref, "task_ref")
        for value, name in ((principal, "principal"), (request_key, "request_key"),
                            (instructions, "instructions"), (model, "model"), (reasoning, "reasoning")):
            _text(value, name)
        validate_owner_timeout_seconds(timeout_seconds)
        observed = task_reader(self.portfolio.operations, project, task)(_identity(task))
        if observed["ref"] != task or observed["project_ref"] != project:
            raise OccurrencePreparationError("project or task revision is stale")
        if not isinstance(instruction_contract, Mapping) or instruction_contract.get("task_ref") != task:
            raise OccurrencePreparationError("worker contract must select this exact task")
        if not isinstance(brief, Mapping):
            raise OccurrencePreparationError("worker operating brief is required")
        normalize_instruction_contract(instruction_contract)
        OperatingBrief.from_mapping(brief, role="worker")
        schedule = "worker-" + _digest([project, request_key])[:28]
        semantic = _digest([project, task, principal, instructions, instruction_contract,
                            brief, model, reasoning, profile, timeout_seconds])
        existing = self.due_port.read_due(schedule)
        if existing is not None:
            if (existing.get("invocation_identity") != request_key + ":" + semantic
                    or existing.get("recipient") != principal):
                raise OccurrencePreparationError("request key was reused with changed worker input")
            return {**self.recover(schedule_id=schedule, execute=False),
                    "guide_ref": existing["context_refs"][0], "mandate_ref": existing["target"]["mandate_ref"]}
        handles: dict[str, Any] = {"schedule_id": schedule, "request_key": request_key}
        stage = "guide"
        try:
            name = "worker-" + _digest([project, principal, request_key])[:24]
            content = {"schema": "herzchen.instructions.v1", "name": name,
                       "entrypoint": "WORKER_BRIEF.md", "bundle_digest": hashlib.sha256(instructions.encode()).hexdigest(),
                       "export_manifest_digest": semantic, "required": True,
                       "supporting_refs": [], "instructions": instructions}
            guide = self.portfolio.create_document(project, actor=self.actor,
                request_id=request_key + ":guide", document_id=name, content=content)
            guide_ref = guide["record"]["payload"]["current_revision"]
            handles["guide_ref"] = guide_ref
            stage = "assignment"
            actor = self.binding.authenticated_actor(self.manager_actor)
            base = self.assignments.assign(ResourceRef.from_dict(task), role="executor",
                principal=principal, manager=self.manager_actor, pins=[ResourceRef.from_dict(guide_ref)],
                logical_request_key=request_key + ":assign", actor=actor)
            handles.update(assignment_ref=base.ref.to_dict(), generation=base.generation)
            stage = "adoption"
            resources = [{"resource_ref": guide_ref, "resource_name": name,
                          "content_digest": validate_instruction_content(content), "required": True}]
            if base.generation != 1:
                raise OccurrencePreparationError("original assignment has been reassigned")
            adopted = base.payload.get("resource_adoptions")
            if adopted:
                if adopted != resources:
                    raise OccurrencePreparationError("original assignment now has different adopted resources")
                assignment = base
            else:
                assignment = self.assignments.adopt_resources(base.ref, resources=resources,
                    expected_revision=base.revision, expected_generation=base.generation,
                    logical_request_key=request_key + ":adopt", actor=actor)
            handles["assignment_ref"] = assignment.ref.to_dict()
            stage = "mandate"
            mandate = self.portfolio.create_document(project, actor=self.actor,
                request_id=request_key + ":mandate", document_id=name + "-mandate", role="mandate",
                content={"role": "worker", "scope_ref": project, "status": "active",
                         "dispatch_enabled": True, "task_ref": task,
                         "assignment_ref": assignment.ref.to_dict(), "generation": assignment.generation,
                         "brief": dict(brief), "instruction_contract": dict(instruction_contract)})
            mandate_ref = mandate["record"]["payload"]["current_revision"]
            handles["mandate_ref"] = mandate_ref
            stage = "due"
            at = self._now()
            target = {"host": "local", "project_ref": project, "task_ref": task,
                      "assignment_ref": assignment.ref.to_dict(), "mandate_ref": mandate_ref,
                      "role": "worker", "principal": principal, "requested_model": model,
                      "requested_reasoning": reasoning, "requested_profile": profile}
            due = DueRecord(schedule_id=schedule, recipient=principal, instruction=instructions,
                profile=profile, anchor=at, due_at=at, last_covered_slot=0,
                invocation_identity=request_key + ":" + semantic,
                in_flight_request=request_key + ":launch", delivery_state="ready",
                owner=self.actor, project_ref=project["id"], manager_ref=self.actor,
                assignment_ref=assignment.ref.to_dict(), generation=assignment.generation,
                target=target, role="worker", purpose="delegated-worker", lifecycle_owner=self.actor,
                execution_mode="fresh_bounded_worker", requested_model=model,
                requested_reasoning=reasoning, context_refs=(guide_ref, mandate_ref),
                result_owner=self.actor, timeout_seconds=timeout_seconds)
            prepared = prepare_current_assignment_occurrence(due_port=self.due_port,
                assignments=self.assignments, binding=self.binding, due=due,
                assignment_ref=assignment.ref.to_dict(), assignment_owner=self.manager_actor,
                operation="invoke", lifecycle="launch", request_key=request_key + ":due")
            return {**handles, **prepared, "required_resource_names": [name]}
        except Exception as exc:
            return {**handles, "outcome": "partial", "stage": stage,
                    "error": {"code": type(exc).__name__, "message": str(exc)},
                    "next_action": "retry this exact assignment request to finish preparation"}

    def assign_and_start(self, **request: Any) -> dict[str, Any]:
        prepared = self.assign_worker(**request)
        if prepared["outcome"] not in {"committed", "prepared"}:
            return prepared
        return self.start(schedule_id=prepared["schedule_id"])

    def prepare_role(self, *, role: str, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                     assignment_ref: Mapping[str, Any], generation: int, mandate_ref: Mapping[str, Any],
                     context_refs: tuple[Mapping[str, Any], ...], request_key: str, instruction: str,
                     model: str, reasoning: str, profile: str, native_session_id: str | None = None,
                     binding_schedule_id: str | None = None,
                     allowance_ref: Mapping[str, Any] | None = None,
                     timeout_seconds: int = 1200) -> dict[str, Any]:
        """Prepare an already-assigned role from exact public owner handles.

        Native identity for a continuation is checked against the assignment's
        host binding or a prior owner-authorized occurrence, never roster text.
        """
        if role not in {"worker", "manager", "orchestrator", "project_advisor"}:
            raise OccurrencePreparationError("unsupported execution role")
        assignment = self._current(assignment_ref, generation)
        actual_role = "worker" if assignment.role == "executor" else assignment.role
        if actual_role != role:
            raise OccurrencePreparationError("execution role differs from current assignment")
        _text(request_key, "request_key")
        _text(instruction, "instruction")
        validate_owner_timeout_seconds(timeout_seconds)
        semantic = _digest([role, project_ref, task_ref, assignment_ref, generation, mandate_ref,
                            context_refs, instruction, model, reasoning, profile, native_session_id, timeout_seconds, allowance_ref])
        schedule = "role-" + _digest([project_ref, assignment_ref, request_key])[:28]
        prior = self.due_port.read_due(schedule)
        if prior is not None:
            if prior.get("invocation_identity") != request_key + ":" + semantic:
                raise OccurrencePreparationError("request key was reused with changed role input")
            return self.recover(schedule_id=schedule, execute=False)
        if native_session_id is not None:
            self._verify_native_binding(assignment, native_session_id, binding_schedule_id)
        elif role == "manager":
            raise OccurrencePreparationError("manager requires its existing native session")
        at = self._now()
        target = {"host": "local", "project_ref": dict(project_ref), "task_ref": dict(task_ref),
                  "assignment_ref": dict(assignment_ref), "mandate_ref": dict(mandate_ref),
                  "role": role, "principal": assignment.principal, "requested_model": model,
                  "requested_reasoning": reasoning, "requested_profile": profile}
        if native_session_id is not None:
            target["native_id"] = native_session_id
        due = DueRecord(schedule_id=schedule, recipient=assignment.principal, instruction=instruction,
            profile=profile, anchor=at, due_at=at, last_covered_slot=0,
            invocation_identity=request_key + ":" + semantic, in_flight_request=request_key,
            delivery_state="ready", owner=self.actor, project_ref=project_ref["id"], manager_ref=self.actor,
            assignment_ref=dict(assignment_ref), generation=generation, target=target, role=role,
            purpose="role-execution", lifecycle_owner=self.actor,
            allowance_ref=None if allowance_ref is None else dict(allowance_ref),
            execution_mode="continue_existing" if native_session_id else
                "fresh_bounded_worker" if role == "worker" else "fresh_bounded_role",
            requested_model=model, requested_reasoning=reasoning, context_refs=context_refs,
            result_owner=self.actor, timeout_seconds=timeout_seconds)
        return prepare_current_assignment_occurrence(due_port=self.due_port, assignments=self.assignments,
            binding=self.binding, due=due, assignment_ref=assignment_ref, assignment_owner=self.manager_actor,
            operation="resume" if native_session_id else "invoke",
            lifecycle="resume" if native_session_id else "launch", request_key=request_key)

    def _verify_native_binding(self, assignment: Any, session: str, schedule_id: str | None) -> None:
        _text(session, "native_session_id")
        stored = assignment.session
        if stored == session or (isinstance(stored, Mapping) and session in {
                stored.get("physical_session_id"), stored.get("native_id")}):
            return
        if schedule_id is not None:
            value = self._read(schedule_id).to_dict()
            attempt = (value.get("host_evidence") or {}).get("gateway_attempt") or {}
            authorization = attempt.get("delivery_authorization") or {}
            admission = attempt.get("delivery_admission") or {}
            prior_ref = value.get("assignment_ref") or {}
            result = attempt.get("result") or {}
            evidence = result.get("task_bound_evidence") or {}
            records = evidence.get("host_records") or {}
            turn = evidence.get("turn_id")
            final_record = records.get("final_answer") or {}
            verified_turn = ((result.get("context_digest_verified") is True
                              and result.get("observed_turn_id") == turn)
                             or (final_record.get("session_id") == session
                                 and final_record.get("turn_id") == turn
                                 and isinstance(final_record.get("raw_line_sha256"), str)
                                 and len(final_record["raw_line_sha256"]) == 64))
            # Older gateway envelopes retained parsed native evidence before
            # the dedicated admission field existed. Require its actual user,
            # turn context and final message, all bound to the owner brief.
            retained_native_result = (result.get("outcome") == "succeeded"
                and evidence.get("assignment_ref") == prior_ref
                and evidence.get("generation") == assignment.generation
                and evidence.get("owner_delivery_authorization") == authorization
                and evidence.get("delivered_brief_digest") == authorization.get("brief_sha256")
                and evidence.get("session_id") == session and isinstance(turn, str)
                and verified_turn
                and all(isinstance(records.get(name), Mapping)
                    and records[name].get("session_id") == session and records[name].get("turn_id") == turn
                    and isinstance(records[name].get("raw_line_sha256"), str)
                    and len(records[name]["raw_line_sha256"]) == 64
                    for name in ("user_message", "turn_context")))
            native_observed = ((admission.get("native_turn_started") is True
                               and admission.get("physical_session_id") == session)
                              or retained_native_result)
            if (all(prior_ref.get(name) == getattr(assignment.ref, name) for name in ("authority", "kind", "id"))
                    and value.get("generation") == assignment.generation
                    and value.get("recipient") == assignment.principal
                    and value.get("role") == ("worker" if assignment.role == "executor" else assignment.role)
                    and authorization.get("status") == "authorized"
                    and authorization.get("assignment_ref") == prior_ref
                    and authorization.get("generation") == assignment.generation
                    and authorization.get("principal") == assignment.principal
                    and authorization.get("physical_session_id") == session
                    and native_observed):
                return
        raise OccurrencePreparationError("native session has no current owner assignment binding")

    def prepare_manager_delivery(self, *, delivery: Mapping[str, Any], project_ref: Mapping[str, Any],
                                 task_ref: Mapping[str, Any], assignment_ref: Mapping[str, Any],
                                 generation: int, mandate_ref: Mapping[str, Any],
                                 context_refs: tuple[Mapping[str, Any], ...], model: str, reasoning: str,
                                 binding_schedule_id: str | None = None,
                                 timeout_seconds: int = 1200) -> dict[str, Any]:
        """Persist one exact-session advisor message before admitting its child.

        The delivery identity is shared with the advisor's canonical intent.
        Recovery can adopt a legacy occurrence without replacing that identity.
        """
        assignment = self._current(assignment_ref, generation)
        if assignment.role != "manager":
            raise OccurrencePreparationError("delivery recipient is not a current manager")
        from otto.attention import native_target_identity
        session = _text(delivery.get("physical_session_id"), "physical_session_id")
        if native_target_identity(delivery.get("recipient")) != session:
            raise OccurrencePreparationError("delivery recipient differs from the exact native session")
        self._verify_native_binding(assignment, session, binding_schedule_id)
        delivery_id = _text(delivery.get("delivery_id"), "delivery_id")
        key = _text(delivery.get("logical_request_key"), "logical_request_key")
        if not isinstance(delivery.get("message"), Mapping):
            raise OccurrencePreparationError("delivery message is required")
        message = json.dumps(json_value(delivery["message"]), ensure_ascii=False, sort_keys=True)
        schedule = "advisor-manager-delivery-" + hashlib.sha256(delivery_id.encode()).hexdigest()[:20]
        existing = self.due_port.read_due(schedule)
        if existing is not None:
            due = self._read(schedule)
            target = due.target or {}
            if (key not in {due.in_flight_request, due.last_completed_request}
                    or due.message != message or target.get("native_id") != session
                    or target.get("delivery_id") != delivery_id or due.generation != generation
                    or due.assignment_ref["id"] != assignment.id
                    or target.get("project_ref") != dict(project_ref)
                    or target.get("task_ref") != dict(task_ref)
                    or target.get("mandate_ref") != dict(mandate_ref)):
                raise OccurrencePreparationError("existing manager delivery differs from the requested effect")
            return {"outcome": "prepared", "schedule_id": schedule, "record": existing}
        validate_owner_timeout_seconds(timeout_seconds)
        at = self._now()
        target = {"host": "local", "native_id": session, "delivery_id": delivery_id,
                  "project_ref": dict(project_ref), "task_ref": dict(task_ref),
                  "assignment_ref": assignment.ref.to_dict(), "mandate_ref": dict(mandate_ref),
                  "role": "manager", "principal": assignment.principal,
                  "requested_model": model, "requested_reasoning": reasoning,
                  "requested_profile": "workspace-write"}
        due = DueRecord(schedule_id=schedule, recipient=assignment.principal,
            instruction="Receive this persisted Project Advisor message on the current manager session:",
            message=message, profile="workspace-write", anchor=at, due_at=at,
            last_covered_slot=0, invocation_identity=key, in_flight_request=key,
            delivery_state="ready", owner=self.actor, project_ref=project_ref["id"],
            manager_ref=self.actor, assignment_ref=assignment.ref.to_dict(), generation=generation,
            target=target, role="manager", purpose="Project Advisor exact-session delivery",
            lifecycle_owner=self.actor, execution_mode="continue_existing",
            requested_model=model, requested_reasoning=reasoning, context_refs=context_refs,
            result_owner=self.actor, timeout_seconds=timeout_seconds)
        return prepare_current_assignment_occurrence(due_port=self.due_port, assignments=self.assignments,
            binding=self.binding, due=due, assignment_ref=assignment.ref.to_dict(),
            assignment_owner=self.manager_actor, operation="resume", lifecycle="callback", request_key=schedule)

    def correct_worker(self, *, schedule_id: str, request_key: str, instruction: str,
                       execute: bool = True) -> dict[str, Any]:
        """Request correction in the worker's authenticated existing conversation."""
        prior = self._read(schedule_id)
        if prior.role != "worker" or prior.stop_state != "completed" or prior.completion_state != "succeeded":
            raise OccurrencePreparationError("worker correction requires a settled inspected result")
        target = prior.target
        prepared = self.prepare_role(role="worker", project_ref=target["project_ref"], task_ref=target["task_ref"],
            assignment_ref=prior.assignment_ref, generation=prior.generation, mandate_ref=target["mandate_ref"],
            context_refs=prior.context_refs, request_key=request_key, instruction=instruction,
            model=prior.requested_model, reasoning=prior.requested_reasoning, profile=prior.profile,
            native_session_id=prior.last_result["physical_session_id"], binding_schedule_id=schedule_id,
            timeout_seconds=prior.timeout_seconds)
        return self.start(schedule_id=prepared["schedule_id"]) if execute and prepared["outcome"] in {"committed", "prepared"} else prepared

    def _read(self, schedule_id: str) -> DueRecord:
        value = self.due_port.read_due(_text(schedule_id, "schedule_id"))
        if value is None:
            raise OccurrencePreparationError("execution occurrence is unavailable")
        due = DueRecord.from_dict(value)
        if due.lifecycle_owner != self.actor or due.manager_ref != self.actor:
            raise OccurrencePreparationError("execution occurrence belongs to another owner")
        return due

    def _resources(self, due: DueRecord) -> DueRecord:
        current = self.assignments.get(ResourceRef.from_dict(due.assignment_ref))
        if current.generation != due.generation:
            raise OccurrencePreparationError("execution assignment generation is stale")
        if due.assignment_ref != current.ref.to_dict():
            value = self.due_port.reconcile_assignment_resources(due.schedule_id,
                assignment_ref=current.ref.to_dict(), expected_version=due.version,
                request_id=due.invocation_identity + ":resources")
            due = DueRecord.from_dict(value)
        self._current(due.assignment_ref, due.generation)
        return due

    def _kwargs(self, due: DueRecord) -> dict[str, Any]:
        target = due.target
        if not isinstance(target, Mapping):
            raise OccurrencePreparationError("execution target is unavailable")
        assignment = self._current(due.assignment_ref, due.generation)
        names = [item["resource_name"] for item in assignment.payload.get("resource_adoptions", ())
                 if item.get("required")]
        resume = due.execution_mode == "continue_existing"
        prompt = due.instruction + ("\n" + due.message if due.message is not None else "")
        return dict(project_ref=target["project_ref"], task_ref=target["task_ref"],
            assignment_ref=due.assignment_ref, mandate_ref=target["mandate_ref"],
            schedule_id=due.schedule_id, logical_request_key=due.in_flight_request,
            expected_generation=due.generation, operation="resume" if resume else "invoke",
            lifecycle="resume" if resume else "launch", packet_digest=_digest(prompt),
            request={"prompt": prompt}, as_of=due.anchor, required_resource_names=names)

    def prepare_instruction(self, *, schedule_id: str, request_key: str, instruction: str) -> dict[str, Any]:
        """Persist host policy on an existing unattempted occurrence.

        Bootstrap callers may prepare pins before their final prompt exists.
        Once gateway custody exists, the original prompt is immutable.
        """
        due = self._read(schedule_id)
        _text(request_key, "request_key")
        _text(instruction, "instruction")
        if due.instruction == instruction:
            return {"outcome": "prepared", "schedule_id": schedule_id}
        if due.stop_state != "active" or (due.host_evidence or {}).get("gateway_attempt") is not None:
            raise OccurrencePreparationError("attempted occurrence instruction cannot be changed")
        self._resources(due)
        due = self._read(schedule_id)
        saved = self.due_port.save_due(schedule_id, replace(due, instruction=instruction).to_dict(),
            request_id="execution-instruction:" + request_key, expected_version=due.version)
        return {"outcome": "prepared", "schedule_id": schedule_id, "due_version": saved["version"]}

    def start(self, *, schedule_id: str, settle: bool = True) -> dict[str, Any]:
        """Invoke a prepared occurrence or recover its existing effect/result."""
        due = self._read(schedule_id)
        attempt = (due.host_evidence or {}).get("gateway_attempt")
        if attempt is not None or due.stop_state != "active":
            return self.recover(schedule_id=schedule_id, execute=False)
        try:
            due = self._resources(due)
            kwargs = self._kwargs(due)
            result = self.runtime.invoke_role(role=due.role, mode="direct", **kwargs)
        except Exception as exc:
            observed = self._read(schedule_id)
            attempt = (observed.host_evidence or {}).get("gateway_attempt")
            return {"outcome": "unknown" if attempt else "partial", "stage": "runtime",
                    "schedule_id": schedule_id, "assignment_ref": observed.assignment_ref,
                    "generation": observed.generation,
                    "error": {"code": type(exc).__name__, "message": str(exc)},
                    "next_action": "recover this occurrence; reconcile retained evidence before replay" if attempt
                        else "retry start on this exact prepared occurrence"}
        if not settle:
            return json_value(result)
        settled = self.recover(schedule_id=schedule_id, execute=False)
        return {**settled, "runtime_result": json_value(result)}

    def recover(self, *, schedule_id: str, execute: bool = False) -> dict[str, Any]:
        """Reconstruct from owner records after parent exit or application restart."""
        due = self._read(schedule_id)
        attempt = (due.host_evidence or {}).get("gateway_attempt")
        result = attempt.get("result") if isinstance(attempt, Mapping) else None
        handle = {"schedule_id": schedule_id, "assignment_ref": due.assignment_ref,
                  "generation": due.generation, "due_version": due.version}
        if due.stop_state == "completed":
            self._current(due.assignment_ref, due.generation)
            return {**handle, "outcome": "replayed", "completion_state": due.completion_state,
                    "result": result or due.last_result, "next_action": "inspect result and accept or correct the task"}
        if attempt is None:
            due = self._resources(due)
            if execute:
                return self.start(schedule_id=schedule_id)
            return {**handle, "assignment_ref": due.assignment_ref, "due_version": due.version,
                    "outcome": "prepared", "next_action": "start this exact occurrence"}
        self._current(due.assignment_ref, due.generation)
        if not isinstance(result, Mapping):
            return {**handle, "outcome": "pending", "physical_session_id": attempt.get("physical_session_id"),
                    "next_action": "await the admitted worker or reconcile its retained host evidence"}
        if result.get("outcome") == "succeeded":
            kwargs = self._kwargs(due)
            kwargs.pop("packet_digest")
            kwargs.pop("request")
            kwargs.pop("operation")
            try:
                self.runtime.accept_role_result(role=due.role, **kwargs)
            except Exception as exc:
                return {**handle, "outcome": "partial", "stage": "settlement", "result": dict(result),
                        "error": {"code": type(exc).__name__, "message": str(exc)},
                        "next_action": "reconcile the retained result and owner publication; do not repeat the provider effect"}
            due = self._read(schedule_id)
            attempt = due.host_evidence["gateway_attempt"]
        accepted = attempt.get("manager_acceptance")
        exact = (result.get("outcome") == "succeeded" and result.get("context_digest_verified") is True
                 and isinstance(accepted, Mapping) and accepted.get("accepted") is True
                 and accepted.get("owner") == self.actor)
        if not exact:
            return {**handle, "outcome": result.get("outcome", "unknown"), "result": dict(result),
                    "next_action": "reconcile retained evidence before any provider replay"}
        at = self._now()
        compact = {name: result.get(name) for name in (
            "outcome", "delivery_state", "physical_session_id", "observed_turn_id",
            "observed_model", "observed_reasoning", "observed_profile")}
        completed = replace(due, stop_state="completed", completion_state="succeeded",
            in_flight_request=None, delivery_state="returned", last_completed_request=due.in_flight_request,
            last_result=compact, delivered_at=(attempt.get("delivery_admission") or {}).get("observed_at"), completed_at=at,
            completion_evidence={"schema": "otto.role-result.v1", "result_digest": accepted["result_digest"]},
            delivery_evidence={"schema": "otto.role-delivery.v1", "session_id": result["physical_session_id"],
                               "turn_id": result["observed_turn_id"]})
        saved = self.due_port.save_due(schedule_id, completed.to_dict(),
            request_id=due.invocation_identity + ":finalize", expected_version=due.version)
        return {**handle, "due_version": saved["version"], "outcome": "succeeded", "result": dict(result),
                "next_action": "inspect result and accept or correct the task"}

    def continue_manager(self, *, schedule_id: str, execute: bool = True,
                         report_key: str | None = None, task_ref: Mapping[str, Any] | None = None,
                         reports: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        """Prepare a durable callback from the last explicit canonical report."""
        prior = self._read(schedule_id)
        reports = reports if reports is not None else [dict(ref=json_value(report.ref), assignment=json_value(report.assignment),
                        kind=report.kind, value=json_value(report.value))
                   for report in self.assignments.list_observations(
                       ResourceRef.from_dict(prior.assignment_ref), kind="report")]
        request = derive_manager_continuation_request(prior, reports, report_key=report_key)
        if request is None:
            return {"outcome": "idle", "schedule_id": schedule_id, "reason": "no canonical continuation request"}
        key = request["logical_request_key"]
        schedule = manager_continuation_schedule_id(prior.assignment_ref, key)
        if self.due_port.read_due(schedule) is not None:
            return self.recover(schedule_id=schedule, execute=execute)
        instruction = _text(request.get("next_action"), "continuation next_action")
        current = self._current(prior.assignment_ref, prior.generation)
        guide = next(ref for ref in prior.context_refs if ref != prior.target["mandate_ref"])
        due = build_manager_callback_due(prior, schedule_id=schedule, request_key=key,
            assignment_ref=current.ref.to_dict(), guide_ref=guide, mandate_ref=prior.target["mandate_ref"],
            due_at=self._now(), timeout_seconds=prior.timeout_seconds)
        self._verify_native_binding(current, due.target["native_id"], prior.schedule_id)
        due = replace(due, instruction=instruction)
        if task_ref is not None:
            due = replace(due, target={**due.target, "task_ref": dict(task_ref)})
        prepared = prepare_current_assignment_occurrence(due_port=self.due_port,
            assignments=self.assignments, binding=self.binding, due=due,
            assignment_ref=current.ref.to_dict(), assignment_owner=self.manager_actor,
            operation="resume", lifecycle="callback", request_key=key)
        return self.start(schedule_id=schedule) if execute and prepared["outcome"] == "committed" else prepared
