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
from .owner_readers import json_value, owner_ref, project_reader, task_reader
from .operating_brief import OperatingBrief
from .resource_sync import normalize_instruction_contract

_UNSPECIFIED_SESSION = object()


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

    def prepare_operating_setup(self, *, project_ref: Mapping[str, Any],
                                setup: Mapping[str, Any], request_key: str) -> dict[str, Any]:
        """Validate and adopt setup using one existing project document.

        This prepares roles already issued by supported owner operations and
        performs no provider work. To change a setup, publish a new revision
        through ordinary document authoring; replay never replaces identities.
        """
        from .operating_setup import evaluate_setup, normalize_setup, setup_reference
        project = owner_ref(project_ref, "project_ref")
        _text(request_key, "request_key")
        config = normalize_setup(setup)
        decision = evaluate_setup(self.runtime, project, config)
        if not decision["ready"]:
            return {"outcome": "blocked", "readiness": decision, "provider_called": False}
        document = self.portfolio.create_document(project, actor=self.actor,
            request_id=request_key, document_id=setup_reference(project).id,
            role="operating_setup", content=config)
        return {"outcome": "prepared", "setup_ref": self._document_revision(document, "operating setup"),
                "readiness": decision, "provider_called": False}

    def read_operating_setup(self, *, project_ref: Mapping[str, Any]) -> dict[str, Any]:
        """Read draft/ready/active separately from administrative lifecycle."""
        from .operating_setup import evaluate_setup, read_setup
        project = owner_ref(project_ref, "project_ref")
        current = project_reader(self.portfolio.operations, project)(_identity(project))
        if current["ref"] != project:
            raise OccurrencePreparationError("operating setup project revision is stale")
        setup = read_setup(self.portfolio.operations, project)
        if setup is None:
            return {"outcome": "read", "schema": "otto.operating-readiness.v1", "state": "draft", "ready": False,
                    "autonomous_ready": False, "execution_observed": False, "dispatch": False,
                    "canonical_lifecycle": current["lifecycle"],
                    "next_action": "prepare_operating_setup with explicit mode, roles and advisor policy"}
        return {"outcome": "read", **evaluate_setup(self.runtime, project, setup), "canonical_lifecycle": current["lifecycle"]}

    def activate_operating_setup(self, *, project_ref: Mapping[str, Any]) -> dict[str, Any]:
        """Start the configured manager through the shared runtime admission guard."""
        from .operating_setup import read_setup
        decision = self.read_operating_setup(project_ref=project_ref)
        if not decision["ready"]:
            return {"outcome": "blocked", "readiness": decision, "provider_called": False}
        setup = read_setup(self.portfolio.operations, project_ref)
        return self.start(schedule_id=setup["roles"]["manager"])

    def _current(self, ref: Mapping[str, Any], generation: int) -> Any:
        current = self.assignments.get(ResourceRef.from_dict(ref))
        if current.ref.to_dict() != dict(ref) or current.generation != generation:
            raise OccurrencePreparationError("assignment reference or generation is stale")
        if not {self.actor, self.manager_actor}.intersection({current.payload.get("manager"), current.principal}):
            raise OccurrencePreparationError("execution actor does not own the assignment")
        return current

    def _document_revision(self, result: Mapping[str, Any], field: str) -> Mapping[str, Any]:
        """Resolve a document revision from either response envelope or owner readback."""
        record = result.get("record")
        payload = record.get("payload") if isinstance(record, Mapping) else None
        revision = payload.get("current_revision") if isinstance(payload, Mapping) else None
        if isinstance(revision, Mapping) and revision.get("revision"):
            return dict(revision)
        document_ref = result.get("document_ref")
        if isinstance(document_ref, Mapping):
            stable = ResourceRef.from_dict(document_ref)
            current = self.portfolio.operations.reader.get_record(stable)
            current_payload = (current.get("payload") if isinstance(current, Mapping)
                               else getattr(current, "payload", None))
            revision = (current_payload.get("current_revision")
                        if isinstance(current_payload, Mapping) else None)
            if isinstance(revision, ResourceRef):
                return json_value(revision)
            if isinstance(revision, Mapping) and revision.get("revision"):
                return dict(revision)
            content_port = getattr(self.portfolio.operations, "content_port", None)
            if content_port is not None:
                observed = content_port.read(stable)
                observed_payload = (observed.get("payload") if isinstance(observed, Mapping)
                                    else None)
                revision = (observed.get("current_revision")
                            if isinstance(observed, Mapping) else None)
                if revision is None and isinstance(observed_payload, Mapping):
                    revision = observed_payload.get("current_revision")
                if isinstance(revision, ResourceRef):
                    return json_value(revision)
                if isinstance(revision, Mapping) and revision.get("revision"):
                    return dict(revision)
            if stable.revision:
                return stable.to_dict()
        raise OccurrencePreparationError(field + " create response has no current document revision")

    def assign_worker(self, *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                      principal: str, request_key: str, instructions: str,
                      instruction_contract: Mapping[str, Any], brief: Mapping[str, Any],
                      model: str, reasoning: str, profile: str = "workspace-write",
                      timeout_seconds: int = 1200,
                      supporting_refs: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
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
        # Validate explicit owner pins before the first assignment/document effect.
        # The ordinary manager service supplies its adopted sources; caller prose
        # cannot select another policy or an installed command.
        from .role_context import selected_configuration, supporting_context
        sources = supporting_context({"resource_ref": project,
            "content": {"supporting_refs": [] if supporting_refs is None else supporting_refs}},
            self.portfolio.operations.content_port)
        pins = [source["ref"] for source in sources]
        configuration = selected_configuration(sources)
        selection = {field: {"source": "explicit_override", "selected_configuration_ref":
            None if configuration is None else configuration["ref"]} for field in ("model", "reasoning")}
        schedule = "worker-" + _digest([project, request_key])[:28]
        semantic = _digest([project, task, principal, instructions, instruction_contract,
                            brief, model, reasoning, profile, timeout_seconds] + ([pins] if pins else []))
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
                       "supporting_refs": pins, "instructions": instructions}
            guide = self.portfolio.create_document(project, actor=self.actor,
                request_id=request_key + ":guide", document_id=name, content=content)
            guide_ref = self._document_revision(guide, "worker guide")
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
            mandate_ref = self._document_revision(mandate, "worker mandate")
            handles["mandate_ref"] = mandate_ref
            stage = "due"
            at = self._now()
            target = {"host": "local", "project_ref": project, "task_ref": task,
                      "assignment_ref": assignment.ref.to_dict(), "mandate_ref": mandate_ref,
                      "role": "worker", "principal": principal, "requested_model": model,
                      "requested_reasoning": reasoning, "requested_profile": profile,
                      "execution_selection": selection}
            due = DueRecord(schedule_id=schedule, recipient=principal, instruction=instructions,
                profile=profile, anchor=at, due_at=at, last_covered_slot=0,
                invocation_identity=request_key + ":" + semantic,
                in_flight_request=request_key + ":launch", delivery_state="ready",
                owner=self.actor, project_ref=project["id"], manager_ref=self.actor,
                assignment_ref=assignment.ref.to_dict(), generation=assignment.generation,
                target=target, role="worker", purpose="delegated-worker", lifecycle_owner=self.actor,
                execution_mode="fresh_bounded_worker", requested_model=model,
                requested_reasoning=reasoning, context_refs=(guide_ref, mandate_ref, *pins),
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
                     context_refs: tuple[Mapping[str, Any], ...] | None = None, request_key: str,
                     instruction: str | None = None, model: str | None = None,
                     reasoning: str | None = None, profile: str, native_session_id: Any = _UNSPECIFIED_SESSION,
                     binding_schedule_id: str | None = None,
                     allowance_ref: Mapping[str, Any] | None = None,
                     timeout_seconds: int = 1200) -> dict[str, Any]:
        """Prepare an already-assigned role from exact public owner handles.

        Native identity for a continuation is checked against the assignment's
        host binding or a prior owner-authorized occurrence, never roster text.
        Omitted instructions/context/bindings come from the adopted BASE and
        its selected role configuration; explicit overrides keep provenance.
        """
        if role not in {"worker", "manager", "orchestrator", "project_advisor"}:
            raise OccurrencePreparationError("unsupported execution role")
        assignment = self._current(assignment_ref, generation)
        actual_role = "worker" if assignment.role == "executor" else assignment.role
        if actual_role != role:
            raise OccurrencePreparationError("execution role differs from current assignment")
        from .resource_sync import resolve_assignment_attachments
        from .role_context import configured_binding, selected_configuration, supporting_context
        attachments = resolve_assignment_attachments(self.portfolio.operations._assignment_dict(assignment),
            self.portfolio.operations.content_port, role=role)
        if len(attachments) != 1 or attachments[0].get("required") is not True:
            raise OccurrencePreparationError("role requires exactly one required adopted BASE resource")
        base = attachments[0]
        sources = supporting_context(base, self.portfolio.operations.content_port)
        configuration = selected_configuration(sources)
        configured = configured_binding(configuration, role)
        selection = {}
        values = {"model": model, "reasoning": reasoning}
        for field in values:
            if values[field] is None:
                values[field] = configured.get(field)
                selection[field] = {"source": "selected_configuration", "ref": None if configuration is None else configuration["ref"]}
            else:
                selection[field] = {"source": "explicit_override", "selected_configuration_ref": None if configuration is None else configuration["ref"]}
            _text(values[field], field + "; select an adopted role configuration or supply an explicit override")
        model, reasoning = values["model"], values["reasoning"]
        selection["instruction"] = {"source": "adopted_BASE" if instruction is None else "explicit_override",
                                     "ref": base["resource_ref"]}
        if instruction is None:
            instruction = base["content"]["instructions"]
        selection["context_refs"] = {"source": "adopted_role_sources" if context_refs is None else "explicit_override"}
        if context_refs is None:
            context_refs = tuple([base["resource_ref"], mandate_ref, *[item["ref"] for item in sources]])
        if native_session_id is _UNSPECIFIED_SESSION:
            from otto.attention import native_target_identity
            stored = assignment.session
            native_session_id = stored if isinstance(stored, str) else native_target_identity(stored) if isinstance(stored, Mapping) else None
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
                  "requested_reasoning": reasoning, "requested_profile": profile,
                  "execution_selection": selection}
        if native_session_id is not None:
            target["native_id"] = native_session_id
            if binding_schedule_id is not None:
                proof = self.due_port.read_due(binding_schedule_id)
                target["native_binding"] = {"schedule_id": binding_schedule_id,
                                            "due_sha256": _digest(proof)}
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
        current = self._current(due.assignment_ref, due.generation)
        return self._manager_task_reference(self._manager_project_reference(due, current), current)

    def _manager_project_reference(self, due: DueRecord, assignment: Any) -> DueRecord:
        """Refresh only the project snapshot of an unattempted bound callback.

        Project edits do not rebind the manager's execution task or mandate.
        Once gateway custody exists, every invocation pin remains immutable.
        """
        target = due.target
        if (due.role != "manager" or due.execution_mode != "continue_existing"
                or not isinstance(target, Mapping) or "reported_task_ref" not in target):
            return due
        if due.stop_state != "active" or (due.host_evidence or {}).get("gateway_attempt") is not None:
            return due
        pinned = owner_ref(target["project_ref"], "callback project_ref")
        if (pinned["kind"] != "work.project" or due.project_ref != pinned["id"]
                or _identity(assignment.scope.to_dict()) != _identity(pinned)
                or assignment.role != "manager"):
            raise OccurrencePreparationError("callback project differs from its current manager scope")
        observed = project_reader(self.portfolio.operations, pinned)(_identity(pinned))
        fresh = owner_ref(observed["ref"], "current callback project_ref")
        if _identity(fresh) != _identity(pinned):
            raise OccurrencePreparationError("current callback project identity changed")
        if fresh == pinned:
            return due
        receipt = {"schema": "otto.manager-project-reconciliation.v1",
                   "before_project_ref": pinned, "current_project_ref": fresh,
                   "before_due_version": due.version, "assignment_ref": due.assignment_ref,
                   "generation": due.generation, "execution_task_ref": target["task_ref"],
                   "reported_task_ref": target["reported_task_ref"], "provider_called": False}
        saved = self.due_port.save_due(due.schedule_id, replace(due,
            target={**target, "project_ref": fresh},
            host_evidence={**(due.host_evidence or {}), "manager_project_reconciliation": receipt}).to_dict(),
            request_id=due.invocation_identity + ":project:" + fresh["revision"],
            expected_version=due.version)
        return DueRecord.from_dict(saved)

    def _manager_task_reference(self, due: DueRecord, assignment: Any) -> DueRecord:
        """Derive the next manager mandate after its same task actually completes.

        Only a prospective callback can refresh its snapshot. The historical
        occurrence and mandate remain intact; no permission or task identity is
        inferred from the task mentioned in a progress report.
        """
        target = due.target
        if (due.role != "manager" or due.execution_mode != "continue_existing"
                or not isinstance(target, Mapping) or "reported_task_ref" not in target
                or due.stop_state != "active"
                or (due.host_evidence or {}).get("gateway_attempt") is not None):
            return due
        pinned = owner_ref(target["task_ref"], "callback task_ref")
        if assignment.role != "manager" or _identity(assignment.scope.to_dict()) != _identity(target["project_ref"]):
            raise OccurrencePreparationError("callback task differs from its current manager scope")
        observed = task_reader(self.portfolio.operations, target["project_ref"], pinned)(_identity(pinned))
        fresh = owner_ref(observed["ref"], "current callback task_ref")
        if _identity(fresh) != _identity(pinned):
            raise OccurrencePreparationError("current callback task identity changed")
        if fresh == pinned:
            return due
        if observed["lifecycle"] != "completed" or not isinstance(observed["payload"].get("completion"), Mapping):
            raise OccurrencePreparationError("changed manager task requires committed completion before continuation refresh")
        from .owner_readers import mandate_reader
        before_ref = target["mandate_ref"]
        before = mandate_reader(self.portfolio.operations, target["project_ref"], before_ref)(_identity(before_ref))["payload"]
        expected = {"role": "manager", "status": "active", "dispatch_enabled": True,
                    "task_ref": pinned, "assignment_ref": due.assignment_ref, "generation": due.generation}
        if any(type(before.get(k)) is not type(v) or before.get(k) != v for k, v in expected.items()):
            raise OccurrencePreparationError("completed manager task mandate differs from its retained binding")
        contract = normalize_instruction_contract(before.get("instruction_contract"))
        authority = contract.get("authority", {})
        if (contract.get("task_ref") != pinned or authority.get("source") != "canonical_owner"
                or authority.get("owner_actor") != assignment.principal
                or authority.get("effect_profile") != "workspace-write-manager"
                or "canonical_manager_commands" not in contract.get("allowed_operations", ())):
            raise OccurrencePreparationError("task refresh requires the retained canonical manager contract")
        if any(item.get("resource_ref") == before_ref for item in assignment.payload.get("resource_adoptions", ())):
            raise OccurrencePreparationError("adopted mandate task refresh requires explicit resource adoption")
        # Copy all original content, changing only the two task revision pins.
        # A distinct immutable document keeps every old authorization readable.
        content = {**before, "task_ref": fresh,
                   "instruction_contract": {**before["instruction_contract"], "task_ref": fresh}}
        key = due.invocation_identity + ":completed-task:" + fresh["revision"]
        created = self.portfolio.create_document(target["project_ref"], actor=self.actor,
            request_id=key, document_id="manager-continuation-mandate-" + _digest(key)[:24],
            role="mandate", content=content)
        mandate = self._document_revision(created, "continued manager mandate")
        receipt = {"schema": "otto.manager-completed-task-refresh.v1",
                   "before_task_ref": pinned, "current_task_ref": fresh,
                   "before_mandate_ref": before_ref, "current_mandate_ref": mandate,
                   "before_mandate_sha256": _digest(before), "current_mandate_sha256": _digest(content),
                   "assignment_ref": due.assignment_ref, "generation": due.generation,
                   "native_id": target["native_id"], "before_due_version": due.version,
                   "reported_task_ref": target["reported_task_ref"], "provider_called": False}
        saved = self.due_port.save_due(due.schedule_id, replace(due,
            target={**target, "task_ref": fresh, "mandate_ref": mandate},
            context_refs=tuple(mandate if ref == before_ref else ref for ref in due.context_refs),
            host_evidence={**(due.host_evidence or {}), "manager_completed_task_refresh": receipt}).to_dict(),
            request_id=key + ":due", expected_version=due.version)
        return DueRecord.from_dict(saved)

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

    def inspect_mandate(self, *, schedule_id: str) -> dict[str, Any]:
        """Read the prepared occurrence's exact mandate scope without effects."""
        from .owner_readers import mandate_reader
        due = self._read(schedule_id)
        target = due.target
        assignment = self.assignments.get(ResourceRef.from_dict(due.assignment_ref))
        read = mandate_reader(self.portfolio.operations, target["project_ref"], target["mandate_ref"])
        mandate = read(_identity(target["mandate_ref"]))
        content = mandate["payload"]
        expected = {"role": due.role, "status": "active", "dispatch_enabled": True,
                    "task_ref": target["task_ref"], "assignment_ref": assignment.ref.to_dict(),
                    "generation": due.generation}
        mismatches = {key: {"actual": content.get(key), "expected": value}
                      for key, value in expected.items()
                      if type(content.get(key)) is not type(value) or content.get(key) != value}
        contract = content.get("instruction_contract") or {}
        authority = contract.get("authority") or {}
        return {"outcome": "read", "read_only": True, "provider_called": False,
                "schedule_id": schedule_id, "due_version": due.version,
                "mandate_ref": target["mandate_ref"], "current_assignment_ref": assignment.ref.to_dict(),
                "mandate_scope": {key: content.get(key) for key in expected},
                "expected_scope": expected, "scope_mismatches": mismatches,
                "instruction_contract_scope": {"task_ref": contract.get("task_ref"),
                    "source": authority.get("source"), "owner_actor": authority.get("owner_actor"),
                    "effect_profile": authority.get("effect_profile")},
                "mandate_content_sha256": _digest(content),
                "attempt_present": (due.host_evidence or {}).get("gateway_attempt") is not None}

    def manager_task_reconciliation(self, due: DueRecord) -> Mapping[str, Any] | None:
        """Validate the exact one-version derivative of an unattempted callback."""
        evidence = due.host_evidence or {}
        receipt = evidence.get("manager_task_reconciliation")
        if receipt is None:
            return None
        if not isinstance(receipt, Mapping):
            raise OccurrencePreparationError("manager task reconciliation receipt is invalid")
        before = receipt.get("before")
        if (not isinstance(before, Mapping) or type(before.get("version")) is not int
                or not isinstance(before.get("target"), Mapping)
                or not isinstance(receipt.get("execution_task_ref"), Mapping)
                or receipt.get("schema") != "otto.manager-task-reconciliation.v1"):
            raise OccurrencePreparationError("manager task reconciliation receipt is invalid")
        expected = {**before, "version": before["version"] + 1,
                    "target": {**before["target"], "task_ref": receipt["execution_task_ref"]},
                    "host_evidence": {**(before.get("host_evidence") or {}),
                                      "manager_task_reconciliation": receipt}}
        if due.to_dict() != expected or _digest(before) != receipt.get("before_sha256"):
            raise OccurrencePreparationError("manager callback changed after task reconciliation")
        return receipt

    def reconcile_manager_task(self, *, schedule_id: str, anchor_schedule_id: str,
                               expected_version: int, report_task_ref: Mapping[str, Any],
                               execution_task_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any],
                               scope: Mapping[str, Any], disposition_ref: Mapping[str, Any] | None,
                               request_key: str) -> dict[str, Any]:
        """CAS only a legacy report-task pin to the settled manager's mandate task.

        Report intent stays in the instruction. Neither the mandate nor the old
        unknown occurrence is rewritten; retained disposition scope is durable.
        """
        _text(request_key, "request_key")
        due, anchor = self._read(schedule_id), self._read(anchor_schedule_id)
        receipt = self.manager_task_reconciliation(due)
        original = due if receipt is None else DueRecord.from_dict(receipt["before"])
        if (type(expected_version) is not int or original.version != expected_version
                or original.target.get("task_ref") != dict(report_task_ref)
                or anchor.target.get("task_ref") != dict(execution_task_ref)
                or original.target.get("mandate_ref") != dict(mandate_ref)
                or anchor.target.get("mandate_ref") != dict(mandate_ref)
                or due.role != "manager" or anchor.role != "manager"
                or anchor.completion_state != "succeeded"
                or due.assignment_ref["id"] != anchor.assignment_ref["id"]
                or due.generation != anchor.generation
                or due.target.get("native_id") != anchor.target.get("native_id")
                or due.stop_state != "active" or due.completion_state != "none"
                or due.in_flight_request != scope["report_key"]
                or (due.host_evidence or {}).get("gateway_attempt") is not None):
            raise OccurrencePreparationError("manager task reconciliation pins are stale or foreign")
        assignment = self._current(due.assignment_ref, due.generation)
        self._verify_native_binding(assignment, due.target["native_id"], anchor_schedule_id)
        if _digest(self._read(scope["current_schedule_id"]).to_dict()) != scope["current_due_sha256"]:
            raise OccurrencePreparationError("current manager evidence changed before reconciliation")
        inspected = self.inspect_mandate(schedule_id=schedule_id)
        mandate_scope = inspected["mandate_scope"]
        wanted = {**inspected["expected_scope"], "task_ref": dict(execution_task_ref)}
        contract = inspected["instruction_contract_scope"]
        if (mandate_scope != wanted or contract != {"task_ref": dict(execution_task_ref),
                "source": "canonical_owner", "owner_actor": assignment.principal,
                "effect_profile": "workspace-write-manager"}):
            raise OccurrencePreparationError("anchor manager mandate does not authorize exact reconciliation scope")
        binding = {"schema": "otto.manager-task-reconciliation.v1", "request_key": request_key,
                   "anchor_schedule_id": anchor_schedule_id, "scope": dict(scope),
                   "disposition_ref": disposition_ref, "execution_task_ref": dict(execution_task_ref),
                   "before": original.to_dict(), "before_sha256": _digest(original.to_dict())}
        if receipt is not None:
            if receipt != binding:
                raise OccurrencePreparationError("manager task reconciliation input changed")
            return {"outcome": "replayed", "schedule_id": schedule_id,
                    "due_version": due.version, "provider_called": False}
        if report_task_ref == execution_task_ref:
            raise OccurrencePreparationError("manager task reconciliation requires a task mismatch")
        saved = self.due_port.save_due(schedule_id, replace(due,
            target={**due.target, "task_ref": dict(execution_task_ref)},
            host_evidence={**(due.host_evidence or {}), "manager_task_reconciliation": binding}).to_dict(),
            request_id="execution-manager-task:" + request_key, expected_version=expected_version)
        return {"outcome": "committed", "schedule_id": schedule_id,
                "due_version": saved["version"], "provider_called": False}

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

    def inspect_capacity_failed_worker(self, *, schedule_id: str) -> dict[str, Any]:
        """Root owner readback of an exact native terminal capacity failure."""
        from .worker_custody import inspect_capacity_failed_worker
        return inspect_capacity_failed_worker(self, schedule_id=schedule_id)

    def release_capacity_failed_worker(self, **request: Any) -> dict[str, Any]:
        """Release only qualified old custody; preserve its UNKNOWN result."""
        from .worker_custody import release_capacity_failed_worker
        return release_capacity_failed_worker(self, **request)

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

    def _retained_completed_task_refresh(self, value: Mapping[str, Any], anchor: DueRecord) -> bool:
        receipt = (value.get("host_evidence") or {}).get("manager_completed_task_refresh")
        return (isinstance(receipt, Mapping)
                and receipt.get("schema") == "otto.manager-completed-task-refresh.v1"
                and receipt.get("before_task_ref") == anchor.target["task_ref"]
                and receipt.get("before_mandate_ref") == anchor.target["mandate_ref"]
                and receipt.get("current_task_ref") == value["target"].get("task_ref")
                and receipt.get("current_mandate_ref") == value["target"].get("mandate_ref")
                and receipt.get("assignment_ref") == value["assignment_ref"]
                and receipt.get("generation") == value["generation"]
                and receipt.get("native_id") == value["target"].get("native_id")
                and receipt.get("reported_task_ref") == value["target"].get("reported_task_ref"))

    def continue_manager_from_worker(self, *, manager_schedule_id: str,
                                    worker_schedule_id: str, execute: bool = False) -> dict[str, Any]:
        """Prepare one same-manager inspection turn from a settled worker result.

        This owner observation is neither a manager progress report nor task
        acceptance. Both original occurrences and the provider result remain
        immutable. The deterministic callback is the restart/replay fence.
        """
        prior, worker = self._read(manager_schedule_id), self._read(worker_schedule_id)
        result = ((worker.host_evidence or {}).get("gateway_attempt") or {}).get("result") or {}
        if (prior.role != "manager" or worker.role != "worker"
                or _identity(prior.target["project_ref"]) != _identity(worker.target["project_ref"])
                or worker.stop_state != "completed" or worker.completion_state != "succeeded"
                or worker.in_flight_request is not None or result.get("outcome") != "succeeded"
                or result.get("context_digest_verified") is not True
                or result.get("assignment_ref") != worker.assignment_ref
                or result.get("generation") != worker.generation
                or result.get("task_ref") != worker.target["task_ref"]):
            raise OccurrencePreparationError("worker result continuation requires a verified settled same-project worker")
        current = self._current(prior.assignment_ref, prior.generation)
        worker_assignment = self.assignments.get(ResourceRef.from_dict(worker.assignment_ref))
        if (current.principal != self.manager_actor or worker_assignment.payload.get("manager") != current.principal
                or worker_assignment.principal != worker.recipient
                or worker_assignment.role not in {"worker", "executor"}
                or worker_assignment.generation != worker.generation):
            raise OccurrencePreparationError("worker result belongs to another manager or assignment generation")
        observed_task = task_reader(self.portfolio.operations, prior.target["project_ref"],
            worker.target["task_ref"])(_identity(worker.target["task_ref"]))
        if observed_task.get("lifecycle") == "completed":
            return {"outcome": "idle", "provider_called": False,
                    "reason": "worker task is already completed by the manager", "retry": False}
        evidence = {"schema": "otto.worker-result-continuation.v1", "worker_schedule_id": worker.schedule_id,
                    "worker_assignment_ref": worker.assignment_ref, "worker_generation": worker.generation,
                    "worker_task_ref": worker.target["task_ref"], "worker_result_sha256": _digest(result),
                    "observed_turn_id": result.get("observed_turn_id"),
                    "physical_session_id": result.get("physical_session_id"),
                    "acceptance": "unjudged worker result; task/project gates remain required"}
        key = "worker-result:" + _digest([current.ref.id, current.generation, evidence])
        schedule = "manager-worker-callback-" + _digest(key)[:28]
        if (prior.completion_state == "unknown"
                or (((prior.host_evidence or {}).get("gateway_attempt") or {}).get("result") or {}).get("outcome") == "unknown"
                or prior.stop_state == "completed" and prior.completion_state != "succeeded"):
            return {"outcome": "held", "provider_called": False, "effects_started": False,
                    "reason": "reconcile the retained manager effect before worker-result continuation", "retry": False}
        existing = self.due_port.read_due(schedule)
        if existing is None:
            retained = [item for item in self.due_port.list_due({"project_ref": prior.project_ref,
                "manager_ref": self.actor, "role": "manager", "recipient": current.principal})
                if (item.get("host_evidence") or {}).get("worker_result_continuation") == evidence
                and (item.get("assignment_ref") or {}).get("id") == current.ref.id
                and item.get("generation") == current.generation
                and (item.get("target") or {}).get("native_id") == prior.target.get("native_id")]
            if len(retained) > 1:
                raise OccurrencePreparationError("worker result has multiple retained manager deliveries")
            if retained:
                existing, schedule = retained[0], retained[0]["schedule_id"]
        if (existing is None and prior.stop_state == "active" and prior.completion_state == "none"
                and prior.purpose == "Canonical manager callback continuation"
                and prior.delivery_state == "ready" and prior.in_flight_request is not None
                and (prior.host_evidence or {}).get("gateway_attempt") is None):
            # Startup/report preparation may already have committed the next
            # intent. Deliver the result through it rather than waiting for an
            # unstarted turn or stranding that existing occurrence.
            self._verify_native_binding(current, prior.target["native_id"], manager_schedule_id)
            prior = self._resources(prior)
            self.due_port.save_due(prior.schedule_id, replace(prior,
                instruction=prior.instruction + "\nInspect the observed settled worker result and continue ready work; worker success is not acceptance.",
                message=(prior.message or "") + "\nObserved owner worker-result context:\n" +
                    json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                host_evidence={**(prior.host_evidence or {}), "worker_result_continuation": evidence}).to_dict(),
                request_id=key + ":deliver-worker-result", expected_version=prior.version)
            return self.recover(schedule_id=prior.schedule_id, execute=execute)
        if ((prior.stop_state != "completed" or prior.completion_state != "succeeded"
                or prior.in_flight_request is not None) and prior.schedule_id != schedule):
            return {"outcome": "pending", "provider_called": False, "effects_started": False,
                    "reason": "manager must settle before worker-result continuation", "retry": False}
        if existing is not None:
            if (existing.get("host_evidence") or {}).get("worker_result_continuation") != evidence:
                raise OccurrencePreparationError("retained worker-result continuation evidence differs")
            return self.recover(schedule_id=schedule, execute=execute)
        guide = next(ref for ref in prior.context_refs if ref != prior.target["mandate_ref"])
        due = build_manager_callback_due(prior, schedule_id=schedule, request_key=key,
            assignment_ref=current.ref.to_dict(), guide_ref=guide, mandate_ref=prior.target["mandate_ref"],
            due_at=self._now(), timeout_seconds=prior.timeout_seconds)
        self._verify_native_binding(current, due.target["native_id"], manager_schedule_id)
        due = replace(due, instruction=("Inspect the actual settled worker result on schedule " + worker.schedule_id +
            ". Read its retained result and changed artifacts, substantively judge or correct that work through the "
            "ordinary manager commands, then continue ready work toward the adopted project objective. "
            "Worker transport success is not task acceptance or project completion. Preserve the existing worker "
            "and uncertain effects; this invocation does not authorize worker replay."),
            message="Observed owner worker-result context:\n" + json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            target={**due.target, "reported_task_ref": worker.target["task_ref"]},
            host_evidence={"worker_result_continuation": evidence})
        prepared = prepare_current_assignment_occurrence(due_port=self.due_port,
            assignments=self.assignments, binding=self.binding, due=due,
            assignment_ref=current.ref.to_dict(), assignment_owner=self.manager_actor,
            operation="resume", lifecycle="callback", request_key=key)
        if prepared["outcome"] == "committed":
            reconciled = self._resources(self._read(schedule))
            prepared = {**prepared, "due_version": reconciled.version}
        return self.start(schedule_id=schedule) if execute and prepared["outcome"] == "committed" else prepared

    def continue_manager_from_help(self, *, manager_schedule_id: str,
                                   report_ref: Mapping[str, Any], execute: bool = False) -> dict[str, Any]:
        """Consume one response/applied outcome through retained manager continuation.

        The report identity is the callback fence. It does not authorize its
        proposed solution, replay an unknown turn, or change role ownership.
        """
        prior = self._read(manager_schedule_id)
        current = self._current(prior.assignment_ref, prior.generation)
        if (prior.role != "manager" or current.role != "manager" or current.principal != self.manager_actor
                or _identity(current.scope.to_dict()) != _identity(prior.target["project_ref"])):
            raise OccurrencePreparationError("help continuation requires the current project manager")
        loop = self.portfolio._issue_loop()
        if loop is None:
            raise OccurrencePreparationError("owner help ports are unavailable")
        reports = loop._issue_reports(prior.target["project_ref"])
        report = next((r for r in reports if r.get("ref") == dict(report_ref)), None)
        value = report.get("value") if report else None
        if not isinstance(value, Mapping) or value.get("schema") not in {"otto.issue.response.v1", "otto.issue.outcome.v1"}:
            raise OccurrencePreparationError("help continuation requires an exact retained response or applied outcome")
        issue = next((i for i in loop.derive_issues(reports) if i["issue_id"] == value.get("issue_id")), None)
        if issue is None or value.get("manager_generation") != current.generation:
            raise OccurrencePreparationError("help response belongs to another manager generation")
        if value["schema"] == "otto.issue.response.v1":
            recipient = loop._recipient(prior.target["project_ref"], issue["purpose"])
            if (value.get("awaiting") != "manager" or value.get("current_owner_ref") != current.ref.to_dict()
                    or recipient is None or value.get("responding_assignment_ref") != json_value(recipient.ref)
                    or value.get("responding_generation") != recipient.generation
                    or report.get("assignment") != json_value(recipient.ref)):
                raise OccurrencePreparationError("help response recipient is stale")
        elif (value.get("disposition") != "resolved" or not value.get("evidence")
                or value.get("manager_assignment_ref") != current.ref.to_dict()
                or report.get("assignment") != current.ref.to_dict()):
            raise OccurrencePreparationError("help outcome is not applied by this manager")
        project = project_reader(self.portfolio.operations, prior.target["project_ref"])(_identity(prior.target["project_ref"]))
        if project["lifecycle"] == "completed":
            return {"outcome": "idle", "provider_called": False, "retry": False}
        evidence = {"schema": "otto.help-continuation.v1", "report_ref": dict(report_ref),
                    "issue_id": issue["issue_id"], "purpose": issue["purpose"],
                    "report_sha256": _digest(value), "manager_assignment_ref": current.ref.to_dict(),
                    "manager_generation": current.generation}
        key = "help-result:" + _digest([current.ref.id, current.generation, report_ref])
        schedule = "manager-help-callback-" + _digest(key)[:28]
        if (prior.completion_state == "unknown" or
                (((prior.host_evidence or {}).get("gateway_attempt") or {}).get("result") or {}).get("outcome") == "unknown"
                or prior.stop_state == "completed" and prior.completion_state != "succeeded"):
            return {"outcome": "held", "provider_called": False, "effects_started": False,
                    "reason": "reconcile the retained manager effect before help continuation", "retry": False}
        existing = self.due_port.read_due(schedule)
        if existing is not None:
            if ((existing.get("host_evidence") or {}).get("help_continuation") != evidence
                    or existing["target"].get("native_id") != prior.target.get("native_id")):
                raise OccurrencePreparationError("retained help continuation binding differs")
            if prior.schedule_id != schedule and prior.stop_state != "completed":
                return {"outcome": "pending", "provider_called": False, "effects_started": False, "retry": False}
            return self.recover(schedule_id=schedule, execute=execute)
        if prior.stop_state != "completed" or prior.completion_state != "succeeded" or prior.in_flight_request is not None:
            return {"outcome": "pending", "provider_called": False, "effects_started": False,
                    "reason": "manager must settle before help continuation", "retry": False}
        guide = next(ref for ref in prior.context_refs if ref != prior.target["mandate_ref"])
        due = build_manager_callback_due(prior, schedule_id=schedule, request_key=key,
            assignment_ref=current.ref.to_dict(), guide_ref=guide, mandate_ref=prior.target["mandate_ref"],
            due_at=self._now(), timeout_seconds=prior.timeout_seconds)
        self._verify_native_binding(current, due.target["native_id"], manager_schedule_id)
        due = replace(due, instruction=("Read the retained help/advice report and its current issue disposition. "
            "Apply only actions authorized by your adopted mandate, record concrete application evidence through resolve-help, "
            "and continue independent ready work through ordinary delegation and review. Advice is a suggestion; "
            "receipt or response alone does not resolve a blockage. This invocation consumes the report; "
            "do not redispatch it or wait for your own turn to settle. Preserve unknown effects and budgets."),
            message="Observed help continuation context:\n" + json.dumps(evidence, sort_keys=True),
            host_evidence={"help_continuation": evidence})
        prepared = prepare_current_assignment_occurrence(due_port=self.due_port,
            assignments=self.assignments, binding=self.binding, due=due,
            assignment_ref=current.ref.to_dict(), assignment_owner=self.manager_actor,
            operation="resume", lifecycle="callback", request_key=key)
        if prepared["outcome"] == "committed":
            reconciled = self._resources(self._read(schedule))
            prepared = {**prepared, "due_version": reconciled.version}
        return self.start(schedule_id=schedule) if execute and prepared["outcome"] == "committed" else prepared

    def continue_manager_after_tasks(self, *, manager_schedule_id: str,
                                     execute: bool = False) -> dict[str, Any]:
        """Deliver newly observed committed finishes and advance ordinary work.

        This is an inspection/advancement opportunity, not project acceptance.
        The completed-task set identifies one deterministic occurrence across
        settlement, restart and repeated observation. Unfinished tasks do not
        prevent their manager from receiving a committed intermediate finish.
        """
        prior = self._read(manager_schedule_id)
        current = self._current(prior.assignment_ref, prior.generation)
        if (prior.role != "manager" or current.role != "manager"
                or current.principal != self.manager_actor
                or _identity(current.scope.to_dict()) != _identity(prior.target["project_ref"])):
            raise OccurrencePreparationError("task settlement continuation requires the current project manager")
        operations = self.portfolio.operations
        project = project_reader(operations, prior.target["project_ref"])(_identity(prior.target["project_ref"]))
        if project["lifecycle"] == "completed":
            return {"outcome": "idle", "provider_called": False, "reason": "project is already completed", "retry": False}
        sheet = operations.sheet_port.export(ResourceRef.from_dict(_identity(project["ref"])))
        completed = []
        for item in sheet.tasks:
            ref = json_value(item["ref"])
            task = task_reader(operations, project["ref"], ref)(_identity(ref))
            completion = task["payload"].get("completion")
            if task["lifecycle"] != "completed" or not isinstance(completion, Mapping):
                continue
            completed.append({"task_ref": task["ref"], "completion_sha256": _digest(completion)})
        if not completed:
            return {"outcome": "idle", "provider_called": False, "reason": "no completed project tasks", "retry": False}
        evidence = {"schema": "otto.manager-task-settlement-continuation.v1",
                    "project_identity": _identity(project["ref"]),
                    "completed_tasks": sorted(completed, key=lambda item: item["task_ref"]["id"]),
                    "acceptance": "recorded task completion; authentic evidence and project closeout remain manager responsibilities"}
        key = "task-settlement:" + _digest([current.ref.id, current.generation, evidence])
        schedule = "manager-finish-callback-" + _digest(key)[:28]
        if (prior.completion_state == "unknown" or
                (((prior.host_evidence or {}).get("gateway_attempt") or {}).get("result") or {}).get("outcome") == "unknown"
                or prior.stop_state == "completed" and prior.completion_state != "succeeded"):
            return {"outcome": "held", "provider_called": False, "effects_started": False,
                    "reason": "reconcile the retained manager effect before task-settlement continuation", "retry": False}
        existing = self.due_port.read_due(schedule)
        if existing is not None:
            # The completed-task set is deliberately stable across resource
            # adoption. A successful notification from the same role epoch
            # has already delivered that set; do not replay it under new
            # resources or fail a later successfully settled manager turn.
            if (existing.get("assignment_ref") != current.ref.to_dict()
                    and _identity(existing.get("assignment_ref") or {}) == _identity(current.ref.to_dict())
                    and existing.get("generation") == current.generation
                    and existing.get("role") == "manager" and existing.get("recipient") == current.principal
                    and existing["target"].get("native_id") == prior.target.get("native_id")
                    and (existing.get("host_evidence") or {}).get("task_settlement_continuation") == evidence
                    and existing.get("stop_state") == "completed"
                    and existing.get("completion_state") == "succeeded"
                    and existing.get("in_flight_request") is None):
                return {"outcome": "already_observed", "provider_called": False,
                        "schedule_id": schedule, "retry": False,
                        "reason": "same task completions were delivered before resource adoption"}
            if ((existing.get("host_evidence") or {}).get("task_settlement_continuation") != evidence
                    or existing.get("assignment_ref") != current.ref.to_dict()
                    or existing.get("generation") != current.generation
                    or existing["target"].get("native_id") != prior.target.get("native_id")):
                raise OccurrencePreparationError("retained task-settlement continuation binding differs")
            return self.recover(schedule_id=schedule, execute=execute)
        if prior.stop_state != "completed" or prior.completion_state != "succeeded" or prior.in_flight_request is not None:
            return {"outcome": "pending", "provider_called": False, "effects_started": False,
                    "reason": "manager must settle before task-settlement continuation", "retry": False}
        guide = next(ref for ref in prior.context_refs if ref != prior.target["mandate_ref"])
        due = build_manager_callback_due(prior, schedule_id=schedule, request_key=key,
            assignment_ref=current.ref.to_dict(), guide_ref=guide, mandate_ref=prior.target["mandate_ref"],
            due_at=self._now(), timeout_seconds=prior.timeout_seconds)
        self._verify_native_binding(current, due.target["native_id"], manager_schedule_id)
        due = replace(due,
            instruction=("Inspect the committed project task completions and their authentic candidate/evidence bindings, "
                "then advance ready unfinished tasks through ordinary delegation and review, or carry out guarded project closeout when eligible. "
                "Recorded task completion does not establish authentic artifact acceptance or project completion. "
                "This invocation already delivers the observed finishes; do not redispatch it or await your own settlement. "
                "Preserve prior decisions, completed tasks, budgets and uncertain effects; do not replay workers."),
            message="Observed owner task-settlement context:\n" + json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            target={**due.target, "reported_task_ref": prior.target["task_ref"]},
            host_evidence={"task_settlement_continuation": evidence})
        prepared = prepare_current_assignment_occurrence(due_port=self.due_port,
            assignments=self.assignments, binding=self.binding, due=due,
            assignment_ref=current.ref.to_dict(), assignment_owner=self.manager_actor,
            operation="resume", lifecycle="callback", request_key=key)
        if prepared["outcome"] == "committed":
            reconciled = self._resources(self._read(schedule))
            prepared = {**prepared, "due_version": reconciled.version}
        return self.start(schedule_id=schedule) if execute and prepared["outcome"] == "committed" else prepared

    def continue_manager(self, *, schedule_id: str, execute: bool = True,
                         report_key: str | None = None, task_ref: Mapping[str, Any] | None = None,
                         reports: list[Mapping[str, Any]] | None = None,
                         preserve_execution_binding: bool = False) -> dict[str, Any]:
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
        existing = self.due_port.read_due(schedule)
        if existing is not None:
            if preserve_execution_binding and (
                    (existing["target"].get("task_ref") != prior.target["task_ref"]
                     and not self._retained_completed_task_refresh(existing, prior))
                    or existing["target"].get("reported_task_ref") != task_ref):
                return {"outcome": "held", "schedule_id": schedule, "provider_called": False,
                        "reason": "retained legacy continuation requires explicit task-binding reconciliation"}
            return self.recover(schedule_id=schedule, execute=execute)
        instruction = _text(request.get("next_action"), "continuation next_action")
        current = self._current(prior.assignment_ref, prior.generation)
        guide = next(ref for ref in prior.context_refs if ref != prior.target["mandate_ref"])
        due = build_manager_callback_due(prior, schedule_id=schedule, request_key=key,
            assignment_ref=current.ref.to_dict(), guide_ref=guide, mandate_ref=prior.target["mandate_ref"],
            due_at=self._now(), timeout_seconds=prior.timeout_seconds)
        self._verify_native_binding(current, due.target["native_id"], prior.schedule_id)
        context = request.get("report_context")
        if preserve_execution_binding:
            # A report can describe the transport operation that brought us
            # here. Keep that prose attributed rather than promoting it into
            # another execution instruction after the report is consumed.
            reported_next_action = instruction
            from .owner_readers import mandate_reader
            mandate = mandate_reader(self.portfolio.operations, prior.target["project_ref"],
                prior.target["mandate_ref"])(_identity(prior.target["mandate_ref"]))
            contract = normalize_instruction_contract(mandate["payload"]["instruction_contract"])
            instruction = ("Advance the adopted manager objective: " + contract["objective"] + ". "
                "Perform the remaining substantive project work within the adopted contract. "
                "The triggering report has already been consumed to deliver this work invocation. "
                "Use the attributed reported next action as planning advice within that objective; "
                "a request to dispatch this same report describes this invocation's transport, not new work.")
            context = {**(context or {}), "execution_task_ref": prior.target["task_ref"],
                "current_continuation": {"schedule_id": schedule, "consumed_report_key": key,
                    "report_consumed_by_this_invocation": True,
                    "operator_direction": "This invocation already consumes the referenced report. Carry out its substantive next action; do not redispatch that report or wait for your own turn to settle. The owner finalizes settlement after this native turn returns."},
                "reported_task_ref": None if task_ref is None else dict(task_ref),
                "current_intent": {"source": "adopted_manager_contract", "report_ref": request["report_ref"],
                                   "recorded_at": request["requested_at"], "next_action": instruction,
                                   "suggestion_source": "explicit_manager_report",
                                   "reported_next_action": reported_next_action},
                "requirement_provenance": {
                    "owner_constraints": "adopted mandate and executable permission contract remain binding",
                    "observed_facts": "canonical report and retained owner/native readbacks",
                    "agent_suggestions": "historical priorities and next-step prose are advice, not owner prohibitions",
                    "uncertain_effects": "unknown-send fences remain binding; current intent does not authorize replay"}}
            if len(json.dumps(context, ensure_ascii=False).encode()) > 16384:
                raise OccurrencePreparationError("manager continuation evidence exceeds its bounded context size")
        due = replace(due, instruction=instruction,
            message=due.message if context is None else "Current canonical manager report context:\n" +
                json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        if task_ref is not None:
            due = replace(due, target={**due.target,
                "reported_task_ref" if preserve_execution_binding else "task_ref": dict(task_ref)})
        prepared = prepare_current_assignment_occurrence(due_port=self.due_port,
            assignments=self.assignments, binding=self.binding, due=due,
            assignment_ref=current.ref.to_dict(), assignment_owner=self.manager_actor,
            operation="resume", lifecycle="callback", request_key=key)
        if prepared["outcome"] == "committed" and preserve_execution_binding:
            reconciled = self._resources(self._read(schedule))
            prepared = {**prepared, "due_version": reconciled.version}
        return self.start(schedule_id=schedule) if execute and prepared["outcome"] == "committed" else prepared
