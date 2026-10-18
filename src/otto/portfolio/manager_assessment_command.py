"""Finite manager commands over the existing assessment owner; no execution route."""
from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .owner_readers import json_value


OPERATIONS = ("declare-scope", "resolve-required-scope", "freeze-input", "select-candidate", "assess", "accept", "close-finding", "coverage")


def _bound_policy(policy: Any, state: Mapping[str, Any]) -> Any:
    from .local_assessment_policy import LocalAssessmentPolicy
    value = state["assessment_policy"] if policy is None else policy
    return LocalAssessmentPolicy.from_run_config(value, state=state) if isinstance(value, Mapping) else value


def manager_assessment_from_command(owner: Any, *, request: Mapping[str, Any],
                                    state: Mapping[str, Any], policy: Any = None) -> Mapping[str, Any]:
    """The service supplies current state; the CLI supplies no actor capability."""
    alias = request.get("task")
    if alias not in state["task_refs"]:
        raise ValueError("unknown task alias")
    policy = _bound_policy(policy, state)
    with owner.manager_assessment(
        project_ref=state["project_ref"], task_ref=state["task_refs"][alias],
        manager_assignment_ref=state["assignment_ref"], manager_actor=state["manager"],
        manager_generation=state["manager_generation"], assessment_policy=policy,
    ) as commands:
        return commands.execute(request)


def manager_assessment_pool_from_command(owner: Any, *, request: Mapping[str, Any],
                                         state: Mapping[str, Any], policy: Any = None) -> Mapping[str, Any]:
    """Create/read the finite local assessment pool through the owner.

    The controller supplies the bound run policy; callers supply only current
    manager/task pins and a replay key, never pool identities or quantities.
    """
    fields = {"command", "task", "expected_task_ref", "expected_assignment_ref", "expected_generation", "request_key"}
    if set(request) - fields:
        raise ValueError("assessment pool request cannot supply policy or budget fields")
    alias = request.get("task")
    if alias not in state["task_refs"]:
        raise ValueError("unknown task alias")
    policy = _bound_policy(policy, state)
    expected_task = request.get("expected_task_ref")
    expected_assignment = request.get("expected_assignment_ref")
    if expected_task != state["task_refs"][alias] or expected_assignment != state["assignment_ref"]:
        raise PermissionError("assessment pool task/manager assignment pins changed")
    if (type(request.get("expected_generation")) is not int
            or request["expected_generation"] != state["manager_generation"]):
        raise PermissionError("assessment pool manager generation changed")
    key = request.get("request_key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("logical request key is required")
    return owner.create_manager_assessment_pool(
        project_ref=state["project_ref"], task_ref=state["task_refs"][alias],
        manager_assignment_ref=state["assignment_ref"], manager_actor=state["manager"],
        manager_generation=state["manager_generation"], assessment_policy=policy, logical_request_key=key,
    )


class ManagerAssessmentCommands:
    """Owner-issued, exact task/assignment capability, revalidated on every call."""

    def __init__(self, *, assessment: Any, assessment_facade: Any, reader: Any, actor: Any, task: ResourceRef,
                 assignment: ResourceRef, generation: int, authorize: Any, policy: Any, pool_guard: Any) -> None:
        self._assessment, self._reader, self._actor = assessment, reader, actor
        self._assessment_facade = assessment_facade
        self._task, self._assignment, self._generation = task, assignment, generation
        self._authorize = authorize
        self._policy, self._pool_guard = policy, pool_guard

    def close(self) -> None:
        if self._assessment_facade is not None:
            facade, self._assessment_facade = self._assessment_facade, None
            facade.close()

    def __enter__(self) -> "ManagerAssessmentCommands":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def required_scope(self, *, require: bool = True, completed_read: bool = False) -> Any:
        """Resolve the one required scope without creating a competing gate."""
        self._authorize()
        current_task = self._reader.get_identity(ResourceRef(self._task.authority, self._task.kind, self._task.id))
        if current_task is None:
            raise PermissionError("assessment task is no longer current")
        rows = self._assessment.coverage(current_task.ref)["scopes"]
        scopes = [self._assessment.get_scope(ResourceRef.from_dict(row["ref"])) for row in rows]
        required = [scope for scope in scopes if scope.policy.get("required_for_completion") is True]
        if not required and not require:
            return None
        if len(required) != 1:
            raise PermissionError("task must have exactly one required assessment scope; resolve owner scope configuration")
        scope = required[0]
        if completed_read and current_task.payload.get("lifecycle") == "completed":
            self._completed_scope(scope)
        else:
            scope = self._scope(scope.ref)
        check_accepted = self._policy.scope_mode == "check-accepted"
        acceptance_mode_valid = (scope.policy.get("acceptance_mode") == "check-accepted"
                                 if check_accepted else "acceptance_mode" not in scope.policy)
        if (scope.review_required == check_accepted
                or scope.allow_no_review != check_accepted
                or not acceptance_mode_valid
                or (check_accepted and scope.protocol != "check-accepted")):
            raise PermissionError("required assessment scope mode differs from the configured owner policy")
        expected = {criterion for task, criterion in self._policy.task_criterion_pairs if task == self._task}
        if set(scope.criterion_refs) != expected:
            raise PermissionError("required scope does not cover the exact configured task criteria")
        return scope

    def _completed_scope(self, scope: Any) -> None:
        """Read the scope consumed by the exact canonical completion transition.

        Completion revises a task while its accepted assessment scope remains
        pinned to the input revision. This is historical readiness evidence,
        never authority to assess or accept another revision.
        """
        identity = self._reader.get_identity(self._task)
        completion = {} if identity is None else identity.payload.get("completion", {})
        gate = completion.get("assessment_gate_check", {}) if isinstance(completion, Mapping) else {}
        key = completion.get("logical_request_key") if isinstance(completion, Mapping) else None
        receipt = self._reader.get_receipt(key) if isinstance(key, str) and key else None
        if (identity is None or not self._task_content_matches(self._task, identity.payload)
                or not self._task_content_matches(scope.parent_obligation_ref, identity.payload)
                or identity.payload.get("lifecycle") != "completed"
                or not isinstance(completion, Mapping) or not isinstance(gate, Mapping)
                or not self._same_task_content_ref(completion.get("task_ref"), scope.parent_obligation_ref)
                or completion.get("manager") != self._actor.actor
                or completion.get("disposition") not in {
                    "accept", "accepted", "accepted-for-task", "approved", "complete", "completed", "verified"}
                or receipt is None or receipt.status.value != "committed"
                or receipt.operation != "work.revise"
                or receipt.target != ResourceRef.from_dict(completion.get("task_ref"))
                or receipt.result_ref != identity.ref
                or gate.get("required") is not True or gate.get("blockers") != []
                or gate.get("scope_refs") != [scope.ref.to_dict()]
                or not gate.get("accepted_decision_refs")
                or gate.get("accepted_decision_refs") != completion.get("gate_refs")
                or gate.get("candidate_ref") != completion.get("candidate_ref")):
            raise PermissionError("required scope lacks the exact committed task completion proof")
        for criterion in scope.criterion_refs:
            self._policy.require_pair(self._task, criterion)
        if scope.designated_approver != self._actor.actor or scope.authority not in {None, self._actor.authority}:
            raise PermissionError("required assessment scope is not designated to this manager authority")

    def _ref(self, value: Any, field: str, *, kind: str | None = None,
             stable: bool = False) -> ResourceRef:
        if not isinstance(value, Mapping):
            raise ValueError(field + " must be resource-ref JSON")
        ref = ResourceRef.from_dict(value)
        unpinned_finding = kind == "assessment.finding" and ref.revision is None and not stable
        if (ref.authority != self._task.authority or (kind and ref.kind != kind)
                or (ref.revision is not None if stable else (not ref.revision and not unpinned_finding))):
            raise ValueError(field + (" must be an unpinned owner target" if stable else " must pin an owner revision"))
        if not stable:
            self._current(ref, field)
        return ref

    def _current(self, ref: ResourceRef, field: str) -> None:
        current = self._reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if current is None or current.ref != ref:
            raise ValueError(field + " is missing or stale")

    def _refs(self, values: Any, field: str, *, kind: str | None = None) -> tuple[ResourceRef, ...]:
        if not isinstance(values, list) or not values or len(values) > 64:
            raise ValueError(field + " requires 1..64 exact references")
        return tuple(self._ref(value, field, kind=kind) for value in values)

    def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._authorize()
        if (request.get("expected_task_ref") != self._task.to_dict()
                or request.get("expected_assignment_ref") != self._assignment.to_dict()
                or type(request.get("expected_generation")) is not int
                or request["expected_generation"] != self._generation):
            raise PermissionError("assessment command task/manager assignment pins changed")
        op, args = request.get("operation"), request.get("arguments")
        if op not in OPERATIONS or not isinstance(args, Mapping):
            raise ValueError("unknown assessment operation or missing arguments object")
        if self._policy.scope_mode == "check-accepted" and op in {"assess", "accept"}:
            raise PermissionError("check-accepted assessments require the verified fleet adapter")
        fields = {
            "declare-scope": {"scope_ref", "criterion_refs", "protocol"},
            "resolve-required-scope": set(),
            "freeze-input": {"scope_ref", "candidate_ref", "criterion_refs", "source_refs", "evidence_refs", "packet"},
            "select-candidate": {"scope_ref", "candidate_ref", "criterion_ref", "rationale"},
            "assess": {"scope_ref", "candidate_ref", "criterion_ref", "input_ref", "verdict", "limit_pool_ref", "protocol_result", "findings"},
            "accept": {"result_ref", "candidate_ref", "criterion_ref", "evidence_refs", "rationale"},
            "close-finding": {"finding_ref", "evidence_refs", "test_only", "rationale"},
            "coverage": set(),
        }[op]
        if set(args) - fields:
            raise ValueError("unsupported assessment arguments: " + ", ".join(sorted(set(args) - fields)))
        if op == "coverage":
            return {"outcome": "read", "coverage": self._assessment.coverage(self._task)}
        if op == "resolve-required-scope":
            scope = self.required_scope(completed_read=True)
            self._pool_guard()
            return {"outcome": "read", "scope_ref": scope.ref.to_dict(),
                    "criterion_refs": [ref.to_dict() for ref in scope.criterion_refs],
                    "designated_approver": scope.designated_approver,
                    "limit_pool_ref": self._policy.pool_ref.to_dict()}
        key = request.get("request_key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("logical request key is required")
        ref = lambda field, kind=None: self._ref(args.get(field), field, kind=kind)
        common = {"logical_request_key": key}
        if op == "declare-scope":
            criteria = self._criteria(args.get("criterion_refs"))
            check_accepted = self._policy.scope_mode == "check-accepted"
            protocol = "check-accepted" if check_accepted else args.get("protocol")
            existing = self.required_scope(require=False)
            if existing is not None:
                if set(existing.criterion_refs) != set(criteria) or existing.protocol != protocol:
                    raise PermissionError("declaration conflicts with the existing required scope")
                return {"outcome": "replayed", "ref": existing.ref.to_dict(),
                        "required_scope_reused": True}
            scope_policy = {"required_for_completion": True}
            if check_accepted:
                scope_policy["acceptance_mode"] = "check-accepted"
            record = self._assessment.declare_scope(
                self._ref(args.get("scope_ref"), "scope_ref", kind="assessment.scope", stable=True),
                parent_obligation=self._task, criteria=criteria,
                protocol=protocol, designated_approver=self._actor.actor,
                authority=self._actor.authority, review_required=not check_accepted,
                allow_no_review=check_accepted, policy=scope_policy, **common)
        elif op == "close-finding":
            finding = self._assessment.get_finding(ref("finding_ref", "assessment.finding"))
            result = self._assessment.get_result(finding.result_ref)
            scope = self._scope(result.scope_ref)
            candidate, criterion = result.candidate_ref, result.criterion_ref
            self._policy.require_pair(self._task, criterion)
            self._input(result.input_packet_ref, scope, candidate, criterion)
            evidence = self._refs(args.get("evidence_refs"), "evidence_refs")
            closed = self._assessment.close_finding(
                finding.ref, evidence_refs=evidence, test_only=bool(args.get("test_only", False)),
                rationale=args.get("rationale"), **common)
            record = closed
        elif op == "accept":
            result = self._assessment.get_result(ref("result_ref", "assessment.result"))
            scope = self._scope(result.scope_ref)
            candidate, criterion = ref("candidate_ref"), ref("criterion_ref", "assessment.criterion")
            self._policy.require_pair(self._task, criterion)
            self._input(result.input_packet_ref, scope, candidate, criterion)
            evidence = self._refs(args.get("evidence_refs"), "evidence_refs")
            packet = self._assessment.get_input(result.input_packet_ref)
            if not set(evidence).issubset(set(packet.consumed_refs)):
                raise ValueError("acceptance evidence was not in the frozen input")
            record = self._assessment.accept(result.ref, candidate=candidate, criterion=criterion,
                rationale=args.get("rationale"), evidence_refs=evidence, **common)
        else:
            scope = self._scope(ref("scope_ref", "assessment.scope"))
            candidate = ref("candidate_ref")
            if op == "freeze-input":
                criteria = self._criteria(args.get("criterion_refs"))
                if not set(criteria).issubset(set(scope.criterion_refs)):
                    raise ValueError("input criteria are outside the scope")
                sources = self._refs(args.get("source_refs"), "source_refs")
                evidence = self._refs(args.get("evidence_refs"), "evidence_refs")
                packet = args.get("packet")
                if not isinstance(packet, Mapping):
                    raise ValueError("packet must be an object containing the manager's inspection notes")
                consumed = tuple(dict.fromkeys((candidate, *criteria, *sources, *evidence)))
                record = self._assessment.freeze_input(scope.ref,
                    packet={"inspection": dict(packet), "candidate_ref": candidate.to_dict(),
                            "criterion_refs": [r.to_dict() for r in criteria],
                            "source_refs": [r.to_dict() for r in sources],
                            "evidence_refs": [r.to_dict() for r in evidence]},
                    consumed_refs=consumed, **common)
            else:
                criterion = ref("criterion_ref", "assessment.criterion")
                self._policy.require_pair(self._task, criterion)
                if op == "select-candidate":
                    record = self._assessment.select_candidate(scope.ref, candidate=candidate,
                        criterion=criterion, rationale=args.get("rationale"), **common)
                else:
                    packet_ref = ref("input_ref", "assessment.input")
                    self._input(packet_ref, scope, candidate, criterion)
                    pool = self._ref(args.get("limit_pool_ref"), "limit_pool_ref", kind="limit", stable=True)
                    if pool != self._policy.pool_ref:
                        raise PermissionError("assessment requires the exact controller-authorized local pool")
                    self._pool_guard()
                    protocol_result = args.get("protocol_result")
                    if not isinstance(protocol_result, Mapping) or not protocol_result:
                        raise ValueError("protocol_result must record the manager's actual inspection")
                    record = self._assessment.assess(scope.ref, candidate=candidate, criterion=criterion,
                        input_packet=packet_ref, verdict=args.get("verdict"), limit_pool=pool,
                        protocol_result=dict(protocol_result), findings=args.get("findings", ()), **common)
        return {"outcome": "committed", "schema": "otto.manager-assessment.v1",
                "operation": op, "ref": record.ref.to_dict(), "record": json_value(record.payload),
                "provider_called": False, "task_completion_recorded": False}

    def _criteria(self, values: Any) -> tuple[ResourceRef, ...]:
        criteria = self._refs(values, "criterion_refs", kind="assessment.criterion")
        for criterion in criteria:
            self._policy.require_pair(self._task, criterion)
        return criteria

    def _task_content_matches(self, pinned: ResourceRef | None = None, payload: Any = None) -> bool:
        """Bind the activated task by authored content across metadata revisions."""
        from herzchen.domains.work.admission import task_content_matches

        pinned = self._task if pinned is None else pinned
        identity = self._reader.get_identity(ResourceRef(pinned.authority, pinned.kind, pinned.id))
        if identity is None:
            return False
        return task_content_matches(self._reader, pinned, identity.payload if payload is None else payload,
                                    current_ref=identity.ref)

    def _same_task_content_ref(self, value: Any, pinned: ResourceRef) -> bool:
        if not isinstance(value, Mapping):
            return False
        try:
            ref = ResourceRef.from_dict(value)
        except (TypeError, ValueError, KeyError):
            return False
        return ref == pinned or self._task_content_matches(ref)

    def _scope(self, ref: ResourceRef) -> Any:
        current_task = self._reader.get_identity(ResourceRef(self._task.authority, self._task.kind, self._task.id))
        if current_task is None or current_task.payload.get("lifecycle") == "completed":
            raise PermissionError("assessment authority requires the exact current task")
        scope = self._assessment.get_scope(ref)
        for criterion in scope.criterion_refs:
            self._policy.require_pair(self._task, criterion)
        if not self._task_content_matches(scope.parent_obligation_ref):
            raise PermissionError("assessment scope is not bound to the current task content")
        if scope.designated_approver != self._actor.actor or scope.authority not in {None, self._actor.authority}:
            raise PermissionError("required assessment scope is not designated to this manager authority")
        return scope

    def _input(self, ref: ResourceRef, scope: Any, candidate: ResourceRef, criterion: ResourceRef) -> None:
        packet = self._assessment.get_input(ref)
        if (packet.scope_ref != scope.ref or packet.packet.get("candidate_ref") != candidate.to_dict()
                or criterion.to_dict() not in packet.packet.get("criterion_refs", ())
                or candidate not in packet.consumed_refs or criterion not in packet.consumed_refs):
            raise ValueError("frozen input does not consume this exact scope/candidate/criterion")
        for consumed in packet.consumed_refs:
            self._current(consumed, "consumed input")
        # Recheck the same semantic pins used by the assessment owner at run
        # time. A source can change after PASS while the candidate itself stays
        # current; acceptance must not certify that stale consumed source.
        identity = self._reader.get_identity(candidate)
        payloads = [identity.payload]
        if isinstance(identity.payload.get("pin"), Mapping):
            payloads.append(identity.payload["pin"])
        for payload in payloads:
            for field in ("artifact_ref", "source_ref", "spec_ref"):
                if payload.get(field) is not None:
                    self._ref(payload[field], "candidate " + field)
            for field in ("criteria_refs", "consumed_refs", "input_refs", "consumed_inputs"):
                for value in payload.get(field, ()):
                    self._ref(value, "candidate " + field)
