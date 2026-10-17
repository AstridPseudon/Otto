"""Owner composition for Herzchen's fleet runner and landing mechanism.

The fleet owns the git/check protocol.  Otto supplies the task admission and the
project view. Assessment inputs bind to the retained dispatch and sealed runner
record. Review-required scopes remain blocked until an owner review exists.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import admitted_revision, task_content_matches
from herzchen.fleet.capacity import CapacityPolicy, CapacityPool
from herzchen.fleet.landing import LandingError, LandingService
from herzchen.fleet.runner.runner import Runner
from herzchen.fleet.runner.store import ResultStore


class RunnerCallAdapter:
    """Expose the small JSON call protocol consumed by ``LandingService``."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            return {"ok": False, "error": "bad_request"}
        op = request.get("op")
        if op == "submit":
            return self._runner.submit(request)
        if op == "await":
            return self._runner.await_run(request.get("run_id"), request.get("timeout"))
        return {"ok": False, "error": "bad_request", "detail": "unsupported runner operation"}


class RunnerLifecycle:
    """One owner runner and its adapter, with an explicit service lifecycle."""

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.client = RunnerCallAdapter(runner)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.runner.start()
            self._started = True

    def close(self) -> None:
        if self._started:
            self.runner.stop()
            self._started = False


def compose_runner(home: Any, result_store: ResultStore,
                   capacity_policy: CapacityPolicy) -> RunnerLifecycle:
    """Compose one direct runner over the owner's shared result store.

    The caller starts this once for the owner and closes it during owner
    shutdown.  No runner socket or second ResultStore is created.
    """
    if not isinstance(result_store, ResultStore):
        raise TypeError("owner ResultStore is required")
    if not isinstance(capacity_policy, CapacityPolicy):
        raise TypeError("owner CapacityPolicy is required")
    runner = Runner(CapacityPool(capacity_policy), result_store,
                    state_dir=Path(home) / "runner-state")
    return RunnerLifecycle(runner)


def make_landing_service(*, fleet: Any, result_store: ResultStore,
                         repo_name: str, repo_path: Any, branch: str, owner: Any,
                         runner: Any, views_provider: Callable[[], Mapping[str, Any]],
                         assignment_lookup: Callable[..., Mapping[str, Any]] | None = None,
                         task_lookup: Callable[[str], Mapping[str, Any]] | None = None,
                         timeout: float = 3600) -> LandingService:
    """Build a repo/branch landing service from owner-issued dependencies.

    ``views_provider`` is read at call time because owner project views are
    attached after the fleet registry is composed.  The resolver never reads
    worker request fields.  ``task_lookup`` may be supplied by the dispatch
    registry to additionally bind a task read to its retained assignment
    record; otherwise the task is re-read from the owner graph.
    """
    if not isinstance(repo_name, str) or not repo_name.strip():
        raise ValueError("repo name is required")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("branch is required")
    if not isinstance(result_store, ResultStore):
        raise TypeError("owner ResultStore is required")
    if not callable(views_provider):
        raise TypeError("owner views provider is required")
    if not callable(getattr(runner, "call", None)):
        raise TypeError("owner runner call adapter is required")

    def current_task(task_id: str) -> Mapping[str, Any]:
        if task_lookup is not None:
            task = task_lookup(task_id)
            if not isinstance(task, Mapping):
                raise LandingError("dispatch-bound task lookup returned no current task")
            return dict(task, id=task_id)
        authority = _owner_authority(owner)
        current = owner.graph.current(ResourceRef(authority, "work.task", task_id))
        return {"id": task_id, "revision": current.ref.revision,
                "current_revision": current.ref.revision,
                "payload": current.payload}

    def assessment_context(record: Mapping[str, Any], task: Mapping[str, Any], **pins: Any) -> Mapping[str, Any]:
        """Resolve and prepare assessment inputs from retained owner records.

        This callback runs only after LandingService has sealed the rebased
        commit's runner result.  It records that exact commit as an owner
        ``wrk.result`` candidate, resolves the dispatch admission and trusted
        manager policy, then freezes one exact input packet before assessment.
        Worker supplied pins are deliberately ignored.
        """
        task_id = str(task.get("id") or record.get("task") or "")
        assignment_id = pins.get("assignment_id")
        if not task_id or not isinstance(assignment_id, str) or not assignment_id or not callable(assignment_lookup):
            raise LandingError("owner assignment lookup is required for assessment inputs")
        binding = assignment_lookup(assignment_id)
        if not isinstance(binding, Mapping) or binding.get("record") is None:
            raise LandingError("dispatch record is unavailable for assessment")
        view = binding.get("view")
        server = getattr(view, "server", None)
        project_owner = getattr(server, "owner", None)
        if project_owner is None:
            raise LandingError("owner project view has no assessment owner")
        assert_policy_current = getattr(server, "assert_assessment_policy_current", None)
        if not callable(assert_policy_current):
            raise LandingError("owner project view cannot verify current assessment policy")
        try:
            assert_policy_current()
        except Exception as exc:
            raise LandingError("owner assessment policy is no longer current: " + str(exc)) from exc
        dispatch = binding["record"]
        if (getattr(dispatch, "assignment", None) != assignment_id
                or getattr(dispatch, "role", None) != "worker"
                or getattr(binding.get("task"), "ref", None) is None
                or binding["task"].ref.id != task_id
                or getattr(dispatch, "admitted_revision", None) != admitted_revision(task.get("payload", {}))):
            raise LandingError("assessment dispatch does not match the admitted task")
        task_ref = _owner_ref(binding.get("task_ref"), "task", "work.task")
        project_ref = _owner_ref(binding.get("project_ref"), "project", "work.project")
        assignment_ref = _owner_ref(binding.get("assignment_ref"), "assignment", "wrk.assignment")
        if assignment_ref.id != assignment_id:
            raise LandingError("dispatch identity differs from the current worker assignment")
        generation = binding.get("generation")
        if type(generation) is not int or generation < 1:
            raise LandingError("dispatch assignment generation is unavailable")
        state = binding.get("project_state")
        if not isinstance(state, Mapping):
            raise LandingError("owner project state is unavailable for assessment")
        config = state.get("assessment_policy")
        if not isinstance(config, Mapping):
            raise LandingError("owner assessment policy is unavailable")
        try:
            # Fresh HostOwnerService state may not materialize criterion aliases.
            # Recover them only from the exact current required assessment scope
            # for this task; task prose and worker input never supply criteria.
            policy_state = dict(state)
            criterion_refs = policy_state.get("criterion_refs")
            if not isinstance(criterion_refs, Mapping) or not criterion_refs:
                from herzchen.domains.assessment import AssessmentModule
                from otto.portfolio.assessment import OttoAssessment
                manager_principal = project_owner.binding.authenticated_actor(state.get("manager"))
                assessed = OttoAssessment(AssessmentModule(project_owner.store, actor=manager_principal,
                    payload_resolver=project_owner.evidence_payload_resolver), manager_principal)
                coverage = assessed.coverage(task_ref)
                current_task_identity = project_owner.graph.reader.get_identity(task_ref)
                if current_task_identity is None or current_task_identity.ref != task_ref:
                    raise LandingError("owner assessment task is stale")
                scopes = [assessed.get_scope(row["ref"]) for row in coverage.get("scopes", ())]
                scopes = [scope for scope in scopes
                          if scope.policy.get("required_for_completion") is True
                          and task_content_matches(project_owner.graph.reader,
                                                   scope.parent_obligation_ref,
                                                   current_task_identity.payload,
                                                   current_ref=task_ref)]
                if len(scopes) != 1 or not scopes[0].criterion_refs:
                    raise LandingError("owner assessment setup has no exact required scope and criterion pins for this task")
                criterion_refs = dict(criterion_refs or {})
                for ref in scopes[0].criterion_refs:
                    criterion_refs.setdefault(ref.id, ref.to_dict())
                policy_state["criterion_refs"] = criterion_refs
            from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
            policy = LocalAssessmentPolicy.from_run_config(config, state=policy_state)
            policy.validate_binding(project_ref, task_ref, project_owner.graph.reader)
            # Admission and other metadata writes can advance the task after
            # activation. Validation above proves its current content still
            # matches the retained policy pin; bind the issued command to the
            # current exact refs so its own revision fences remain effective.
            task_identity = (task_ref.authority, task_ref.kind, task_ref.id)
            pairs = tuple((task_ref if (member.authority, member.kind, member.id) == task_identity
                           else member, criterion)
                          for member, criterion in policy.task_criterion_pairs)
            policy = replace(policy, scope_project_ref=project_ref, task_criterion_pairs=pairs)
            criteria = tuple(criterion for member, criterion in pairs if member == task_ref)
        except Exception as exc:
            raise LandingError("owner assessment policy does not bind this task: " + str(exc)) from exc
        if not criteria:
            raise LandingError("fleet landing requires owner-pinned criteria for this task")
        criterion = criteria[0]
        manager_ref = _owner_ref(state.get("assignment_ref"), "manager assignment", "wrk.assignment")
        manager_actor = state.get("manager")
        manager_generation = state.get("manager_generation")
        if (not isinstance(manager_actor, str) or not manager_actor.strip()
                or type(manager_generation) is not int or manager_generation < 1):
            raise LandingError("owner manager assignment is unavailable for assessment")
        try:
            commands = project_owner.manager_assessment(
                project_ref=project_ref.to_dict(), task_ref=task_ref.to_dict(),
                manager_assignment_ref=manager_ref.to_dict(), manager_actor=manager_actor,
                manager_generation=manager_generation, assessment_policy=policy)
            project_owner.create_manager_assessment_pool(
                project_ref=project_ref.to_dict(), task_ref=task_ref.to_dict(),
                manager_assignment_ref=manager_ref.to_dict(), manager_actor=manager_actor,
                manager_generation=manager_generation,
                logical_request_key="fleet-pool:" + policy.pool_ref.id,
                assessment_policy=policy)
        except Exception as exc:
            raise LandingError("owner assessment command admission failed: " + str(exc)) from exc

        commit = record.get("commit")
        if not isinstance(commit, str) or len(commit) not in {40, 64} or any(c not in "0123456789abcdef" for c in commit):
            raise LandingError("verified lab commit is not a canonical object id")
        admitted = getattr(dispatch, "admitted_revision", None)
        runner = _runner_identity(record)
        repo_line = {"repo_name": repo_name, "line_ref": "refs/heads/" + branch,
                    "lab_name": task_id}
        candidate_key = "fleet-land:" + sha256((assignment_id + ":" + commit + ":" +
            str(runner.get("run_id")) + ":" + str(runner.get("binding"))).encode()).hexdigest()
        candidate_value = {"task_ref": task_ref.to_dict(), "admitted_revision": admitted,
                           "assignment_ref": assignment_ref.to_dict(), "assignment_id": assignment_id,
                           "lab_commit": commit, **repo_line, "runner": runner}
        try:
            candidate_record = project_owner.assignments.append_result(
                assignment_ref, candidate_value, expected_generation=generation,
                logical_request_key=candidate_key, actor=project_owner.owner_actor)
            if candidate_record.value != candidate_value:
                raise LandingError("retained lab candidate differs from the verified commit and runner record")
            candidate = candidate_record.ref
        except Exception as exc:
            raise LandingError("owner could not record the verified lab commit as its candidate: " + str(exc)) from exc

        execution_key = "fleet:" + candidate_key
        expected = {"expected_task_ref": task_ref.to_dict(),
                    "expected_assignment_ref": manager_ref.to_dict(),
                    "expected_generation": manager_generation}
        def execute(operation: str, arguments: Mapping[str, Any], suffix: str) -> Mapping[str, Any]:
            return commands.execute({"operation": operation, "arguments": arguments,
                "request_key": execution_key + ":" + suffix, **expected})

        try:
            # Activation owns the acceptance scope. Landing consumes its required
            # scope and must never add a second policy declaration.
            scope = commands.required_scope(require=True)
            if scope is None:
                raise LandingError("owner assessment setup has no required scope for this task")
            if set(scope.criterion_refs) != set(criteria):
                raise LandingError("assessment scope criteria differ from the owner policy pins")
            if (scope.review_required is not False or scope.allow_no_review is not True
                    or getattr(policy, "scope_mode", None) != "check-accepted"
                    or scope.protocol != "check-accepted"
                    or scope.policy.get("acceptance_mode") != "check-accepted"):
                raise LandingError(
                    "owner assessment scope requires a separate review; fleet check evidence cannot substitute for review"
                )
            scope_ref = scope.ref
            packet = execute("freeze-input", {"scope_ref": scope_ref.to_dict(),
                "candidate_ref": candidate.to_dict(), "criterion_refs": [item.to_dict() for item in criteria],
                "source_refs": [candidate.to_dict()], "evidence_refs": [],
                "packet": {"admitted_revision": admitted, "lab_commit": commit,
                           "runner": runner, "line_ref": "refs/heads/" + branch}}, "input")
            packet_ref = ResourceRef.from_dict(packet["ref"])
        except Exception as exc:
            raise LandingError("owner could not freeze the committed lab assessment input: " + str(exc)) from exc

        assessment = _FleetAssessmentCommands(commands, candidate, criteria, packet_ref,
                                               policy.pool_ref, manager_actor, execution_key)
        return {"candidate": candidate, "criterion": criterion, "parent_obligation": task_ref,
                "actor": project_owner.binding.authenticated_actor(manager_actor),
                "criteria": criteria,
                "scope": scope_ref, "input_packet": packet_ref, "limit_pool": policy.pool_ref,
                "assessment": assessment,
                "assess_kwargs": {"logical_request_key": execution_key + ":assess"}}

    def current_criterion(pinned: Any) -> Any:
        criterion = _owner_ref(pinned, "criterion", "assessment.criterion")
        current = owner.graph.reader.get_identity(ResourceRef(criterion.authority, criterion.kind, criterion.id))
        if current is None or current.ref != criterion:
            raise LandingError("owner assessment criterion is stale")
        return current.ref

    def completion_blockers(parent: Any, *, candidate: Any, gate_refs: Any, actor: Any,
                            **_kwargs: Any) -> Mapping[str, Any]:
        return owner.assignments.completion_blockers(parent, candidate=candidate,
            gate_refs=gate_refs, actor=actor)

    def completion_gate(parent: Any, *, candidate: Any, gate_refs: Any, actor: Any,
                        **_kwargs: Any) -> Mapping[str, Any]:
        state = owner.assignments.completion_blockers(parent, candidate=candidate,
            gate_refs=gate_refs, actor=actor)
        return {"clear": not state.get("blockers"), "blockers": state.get("blockers", ())}

    return LandingService(
        fleet=fleet, runner=runner, task_lookup=current_task,
        line_ref="refs/heads/" + branch,
        assessment=object(),
        assessment_context=assessment_context,
        criterion_lookup=current_criterion,
        completion_blockers=completion_blockers, completion_gate=completion_gate,
        result_lookup=result_store.get, timeout=timeout,
    )


def _owner_ref(value: Any, field: str, kind: str) -> ResourceRef:
    try:
        ref = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    except (TypeError, ValueError, KeyError) as exc:
        raise LandingError("owner " + field + " pin is missing or malformed") from exc
    if ref.kind != kind or not ref.revision:
        raise LandingError("owner " + field + " pin must be an exact " + kind + " revision")
    return ref


def _owner_authority(owner: Any) -> str:
    reader = getattr(getattr(owner, "graph", None), "reader", None)
    authority = getattr(reader, "authority", None)
    if not isinstance(authority, str) or not authority:
        authority = getattr(getattr(owner, "owner_actor", None), "authority", None)
    if not isinstance(authority, str) or not authority:
        raise LandingError("owner graph authority is unavailable")
    return authority


class _FleetAssessmentCommands:
    """Adapt Otto's exact manager command port to LandingService's assessment API."""

    def __init__(self, commands: Any,
                 candidate: ResourceRef, criteria: tuple[ResourceRef, ...], packet: ResourceRef,
                 pool: ResourceRef, manager_actor: str, request_key: str) -> None:
        self.commands = commands
        self.candidate, self.criteria, self.packet, self.pool = candidate, criteria, packet, pool
        self.manager_actor = manager_actor
        self.request_key = request_key

    def assess(self, scope: Any, *, candidate: Any, criterion: Any, input_packet: Any,
               verdict: Any, protocol_result: Any, limit_pool: Any, actor: Any, **_kwargs: Any) -> Any:
        if (candidate != self.candidate or criterion not in self.criteria or input_packet != self.packet
                or limit_pool != self.pool or actor.actor != self.manager_actor):
            raise LandingError("assessment request differs from the owner-frozen fleet pins")
        self.commands._authorize()
        scope_record = self.commands._scope(scope)
        self.commands._policy.require_pair(self.commands._task, criterion)
        self.commands._input(input_packet, scope_record, candidate, criterion)
        self.commands._pool_guard()
        return self.commands._assessment.assess(scope_record.ref, candidate=candidate,
            criterion=criterion, input_packet=input_packet, verdict=verdict,
            protocol_result=dict(protocol_result), limit_pool=limit_pool, actor=actor,
            role="fleet-check", logical_request_key=self.request_key + ":assess:" + criterion.id)

    def accept(self, result: Any, *, candidate: Any, criterion: Any,
               rationale: str, actor: Any) -> Any:
        if (candidate != self.candidate or criterion not in self.criteria
                or actor.actor != self.manager_actor):
            raise LandingError("acceptance request differs from the owner-frozen fleet pins")
        payload = getattr(result, "payload", None)
        if not isinstance(payload, Mapping) or payload.get("role") != "fleet-check":
            raise LandingError("fleet acceptance requires a retained fleet-check result")
        self.commands._authorize()
        scope = self.commands._scope(result.scope_ref)
        self.commands._policy.require_pair(self.commands._task, criterion)
        if (result.scope_ref != scope.ref or result.candidate_ref != candidate
                or result.criterion_ref != criterion or result.verdict.value != "PASS"):
            raise LandingError("assessment result differs from the owner-frozen candidate and criterion")
        self.commands._input(result.input_packet_ref, scope, candidate, criterion)
        return self.commands._assessment.accept(result.ref, candidate=candidate, criterion=criterion,
            rationale=rationale, evidence_refs=(), actor=actor,
            logical_request_key=self.request_key + ":accept:" + criterion.id)


def _runner_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project only sealed runner identity fields into owner assessment records."""
    try:
        return {key: record[key] for key in ("run_id", "commit", "binding", "argv", "cwd", "exit_code")}
    except KeyError as exc:
        raise LandingError("sealed runner identity is incomplete") from exc
