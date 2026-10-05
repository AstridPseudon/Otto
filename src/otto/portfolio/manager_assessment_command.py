"""Finite manager commands over the existing assessment owner; no execution route."""
from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .owner_readers import json_value


OPERATIONS = ("declare-scope", "freeze-input", "select-candidate", "assess", "accept", "coverage")


def manager_assessment_from_command(owner: Any, *, request: Mapping[str, Any],
                                    state: Mapping[str, Any], policy: Any) -> Mapping[str, Any]:
    """The service supplies current state; the CLI supplies no actor capability."""
    alias = request.get("task")
    if alias not in state["task_refs"]:
        raise ValueError("unknown task alias")
    return owner.manager_assessment(
        project_ref=state["project_ref"], task_ref=state["task_refs"][alias],
        manager_assignment_ref=state["assignment_ref"], manager_actor=state["manager"],
        manager_generation=state["manager_generation"], assessment_policy=policy,
    ).execute(request)


def manager_assessment_pool_from_command(owner: Any, *, request: Mapping[str, Any],
                                         state: Mapping[str, Any], policy: Any) -> Mapping[str, Any]:
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

    def __init__(self, *, assessment: Any, reader: Any, actor: Any, task: ResourceRef,
                 assignment: ResourceRef, generation: int, authorize: Any, policy: Any, pool_guard: Any) -> None:
        self._assessment, self._reader, self._actor = assessment, reader, actor
        self._task, self._assignment, self._generation = task, assignment, generation
        self._authorize = authorize
        self._policy, self._pool_guard = policy, pool_guard

    def _ref(self, value: Any, field: str, *, kind: str | None = None,
             stable: bool = False) -> ResourceRef:
        if not isinstance(value, Mapping):
            raise ValueError(field + " must be resource-ref JSON")
        ref = ResourceRef.from_dict(value)
        if (ref.authority != self._task.authority or (kind and ref.kind != kind)
                or (ref.revision is not None if stable else not ref.revision)):
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
        fields = {
            "declare-scope": {"scope_ref", "criterion_refs", "protocol"},
            "freeze-input": {"scope_ref", "candidate_ref", "criterion_refs", "source_refs", "evidence_refs", "packet"},
            "select-candidate": {"scope_ref", "candidate_ref", "criterion_ref", "rationale"},
            "assess": {"scope_ref", "candidate_ref", "criterion_ref", "input_ref", "verdict", "limit_pool_ref", "protocol_result", "findings"},
            "accept": {"result_ref", "candidate_ref", "criterion_ref", "evidence_refs", "rationale"},
            "coverage": set(),
        }[op]
        if set(args) - fields:
            raise ValueError("unsupported assessment arguments: " + ", ".join(sorted(set(args) - fields)))
        if op == "coverage":
            return {"outcome": "read", "coverage": self._assessment.coverage(self._task)}
        key = request.get("request_key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("logical request key is required")
        ref = lambda field, kind=None: self._ref(args.get(field), field, kind=kind)
        common = {"logical_request_key": key}
        if op == "declare-scope":
            record = self._assessment.declare_scope(
                self._ref(args.get("scope_ref"), "scope_ref", kind="assessment.scope", stable=True),
                parent_obligation=self._task, criteria=self._criteria(args.get("criterion_refs")),
                protocol=args.get("protocol"), designated_approver=self._actor.actor,
                authority=self._actor.authority, review_required=True, allow_no_review=False,
                policy={"required_for_completion": True}, **common)
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

    def _scope(self, ref: ResourceRef) -> Any:
        scope = self._assessment.get_scope(ref)
        for criterion in scope.criterion_refs:
            self._policy.require_pair(self._task, criterion)
        if scope.parent_obligation_ref != self._task:
            raise PermissionError("assessment scope is not bound to the exact current task")
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
