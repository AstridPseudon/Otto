"""Focused S01 checks over the existing disposable owner/provider fixture.

Run: PYTHONPATH=src:. python3 -m unittest discover -s src/otto/portfolio/tests
Provider substitutions exercise admission; the installed live journey is S06.
"""
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest

from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule
from herzchen.kernel.limits import LimitService
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.operating_setup import OperatingSetupError, evaluate_setup, normalize_setup
from otto.portfolio.manager_journey_service import ManagerJourneyService
from tests import test_execution_application as owner_fixture
from tests import test_manager_journey_command as journey_fixture


class OperatingSetupTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def role(self, role):
        f = self.f
        assigned, guide, mandate = f.role_handles(role, role if role != "project_advisor" else "advisor", role + "-session")
        prepared = f.app.prepare_role(role=role, project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=assigned.ref.to_dict(), generation=assigned.generation, mandate_ref=mandate,
            context_refs=(guide, mandate), request_key="setup-" + role, instruction="Advance useful project",
            model="gpt-test", reasoning="high", profile="workspace-write" if role == "manager" else "read-only",
            native_session_id=role + "-session")
        self.assertEqual(prepared["outcome"], "committed", prepared)
        return assigned, prepared["schedule_id"]

    def manual(self):
        _manager, schedule = self.role("manager")
        return {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": {"manager": schedule},
                "advisor_policy": {"mode": "disabled", "reason": "Owner supervises this bounded run"}, "acceptance_tasks": []}

    def test_draft_read_and_activation_are_inert(self):
        f = self.f
        self.assertEqual(f.app.read_operating_setup(project_ref=f.project.ref.to_dict())["state"], "draft")
        self.assertEqual(f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())["outcome"], "blocked")
        self.assertEqual(f.provider.calls, [])

    def test_maintained_service_prepares_and_reads_setup_without_provider(self):
        f = self.f
        setup = self.manual()
        manager = f.app.assignments.get(ResourceRef.from_dict(f.app._read(setup["roles"]["manager"]).assignment_ref))
        state = {"authority": f.actor.authority, "owner": "manager", "manager": "manager",
                 "assignment_ref": manager.ref.to_dict(), "manager_generation": manager.generation,
                 "project_ref": f.project.ref.to_dict(), "task_refs": {"S01": f.task.ref.to_dict()},
                 "requested_model": "gpt-test", "requested_reasoning": "high"}
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, state=state, due_port=f.port,
                                 _execution=lambda **_: f.app)
        service = ManagerJourneyService(server=server, host=None, run_path=f.temporary.name, workspace=f.temporary.name)
        self.assertEqual(service({"command": "operating-setup", "operation": "read"})["state"], "draft")
        prepared = service({"command": "operating-setup", "operation": "prepare", "setup": setup, "request_key": "service-setup"})
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        read = service({"command": "operating-setup", "operation": "read", "setup": None, "request_key": None})
        self.assertEqual(read["outcome"], "read")
        self.assertEqual(read["state"], "ready")
        with self.assertRaisesRegex(ValueError, "bound project"):
            service({"command": "operating-setup", "operation": "read", "project_ref": f.project.ref.to_dict()})
        self.assertEqual(f.provider.calls, [])

    def test_manual_prepare_replay_start_and_active_read(self):
        f = self.f
        setup = self.manual()
        before = f.port.read_due(setup["roles"]["manager"])
        request = dict(project_ref=f.project.ref.to_dict(), setup=setup, request_key="setup-adopt")
        prepared = f.app.prepare_operating_setup(**request)
        duplicate = f.app.prepare_operating_setup(**request)
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        self.assertEqual(duplicate["setup_ref"], prepared["setup_ref"])
        self.assertEqual(f.port.read_due(setup["roles"]["manager"]), before)
        self.assertEqual(f.provider.calls, [])
        decision = f.app.read_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(decision["state"], "ready")
        self.assertFalse(decision["autonomous_ready"])
        self.assertFalse(decision["capabilities"]["operational_help_delivery"])
        started = f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(started["outcome"], "succeeded", started)
        self.assertEqual(f.app.read_operating_setup(project_ref=f.project.ref.to_dict())["state"], "active")
        self.assertEqual(f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), 1)

    def test_invalid_modes_and_advisor_omissions_fail_without_effects(self):
        config = self.manual()
        for change in ({"mode": "implicit"}, {"advisor_policy": {}},
                       {"advisor_policy": {"mode": "disabled"}}, {"roles": {}},
                       {"mode": "autonomous"}, {"advisor_policy": {"mode": "enabled"}}):
            with self.subTest(change=change), self.assertRaises(OperatingSetupError):
                normalize_setup({**config, **change})
        self.assertEqual(self.f.provider.calls, [])

    def test_missing_base_blocks_bootstrap_start_and_resume_without_claim(self):
        f = self.f
        manager, schedule = self.role("manager")
        unadopted = f.app.assignments.assign(f.project.ref, role="manager", principal="manager", manager="manager",
            session="manager-session", logical_request_key="missing-base", actor=f.actor)
        due = f.app._read(schedule)
        f.port.save_due(schedule, replace(due, assignment_ref=unadopted.ref.to_dict(),
            target={**due.target, "assignment_ref": unadopted.ref.to_dict()}, host_evidence={}).to_dict(),
            request_id="unadopted-role", expected_version=due.version)
        before = f.port.read_due(schedule)
        result = f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "partial")
        self.assertIn("BASE", result["error"]["message"])
        after = f.port.read_due(schedule)
        self.assertIsNone((after["host_evidence"] or {}).get("gateway_attempt"))
        self.assertEqual(before["target"], after["target"])
        self.assertEqual(f.provider.calls, [])

    def test_profile_conflict_is_rejected_before_gateway(self):
        f = self.f
        _, schedule = self.role("manager")
        due = f.app._read(schedule)
        changed = replace(due, profile="read-only", target={**due.target, "requested_profile": "read-only"})
        f.port.save_due(schedule, changed.to_dict(), request_id="profile-mismatch", expected_version=due.version)
        result = f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "partial")
        self.assertIn("profile", result["error"]["message"])
        self.assertEqual(f.provider.calls, [])
        self.assertIsNone((f.port.read_due(schedule)["host_evidence"] or {}).get("gateway_attempt"))

    def test_unknown_attempt_is_immutable_and_not_replayed_by_validation(self):
        f = self.f
        setup = self.manual()
        f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="setup-adopt")
        f.provider.unknown = True
        first = f.app.start(schedule_id=setup["roles"]["manager"])
        self.assertEqual(first["outcome"], "unknown", first)
        before = f.port.read_due(setup["roles"]["manager"])
        for _ in range(2):
            f.app.read_operating_setup(project_ref=f.project.ref.to_dict())
            f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(f.port.read_due(setup["roles"]["manager"]), before)
        self.assertEqual(len(f.provider.calls), 1)

    def acceptance(self, manager):
        f = self.f
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope("required-setup-gate", parent_obligation=f.task.ref,
            protocol="focused", criteria=[{"id": "A01", "definition": "Operating setup passes"}],
            designated_approver="manager", policy={"required_for_completion": True}, logical_request_key="scope")
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "setup-review"),
            capacity_units=1, cumulative_allowance_units=1, logical_request_key="pool", actor=f.actor)
        policy = LocalAssessmentPolicy("Setup inspection", True, pool.ref, 1, 1, f.project.ref,
                                       ((f.task.ref, scope.criterion_refs[0]),))
        app = f.owner.execution_application(due_port=f.port, adapter=f.app.runtime.adapter,
                                           clock=f.app.clock, assessment_policy=policy)
        commands = f.owner.manager_assessment(project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            manager_assignment_ref=manager.ref.to_dict(), manager_actor="manager", manager_generation=1,
            assessment_policy=policy)
        return app, commands, scope, assessment, pool

    def test_autonomous_requires_real_help_route_and_uses_existing_acceptance(self):
        f = self.f
        manager, schedule = self.role("manager")
        orchestrator, help_schedule = self.role("orchestrator")
        app, _commands, _scope, _assessment, pool = self.acceptance(manager)
        config = {"schema": "otto.operating-setup.v1", "mode": "autonomous",
                  "roles": {"manager": schedule, "orchestrator": help_schedule},
                  "advisor_policy": {"mode": "disabled", "reason": "Explicit project opt-out"},
                  "acceptance_tasks": [f.task.ref.to_dict()]}
        decision = evaluate_setup(app.runtime, f.project.ref.to_dict(), config)
        self.assertFalse(decision["ready"])
        self.assertIn("delivery port", json.dumps(decision["blockers"]))
        loop = app.runtime.portfolio._issue_loop()
        class Delivery:
            def send(self, intent):
                raise AssertionError("Readiness must not send help")
        # Substitute scoped readers for a fixture project without default
        # orchestrator metadata; actual assignments and conversations are used.
        loop.ports = replace(loop.ports, current_manager=lambda _: manager,
                             current_supervisor=lambda _: orchestrator, delivery=Delivery())
        before = LimitService(f.store).get_pool(pool.ref)
        decision = evaluate_setup(app.runtime, f.project.ref.to_dict(), config)
        self.assertTrue(decision["autonomous_ready"], decision)
        self.assertEqual(decision["acceptance"]["required_scopes"][0]["limit_pool_ref"], pool.ref.to_dict())
        self.assertEqual(LimitService(f.store).get_pool(pool.ref), before)
        self.assertEqual(f.provider.calls, [])
        loop.ports = replace(loop.ports, current_supervisor=lambda _: manager)
        self.assertFalse(evaluate_setup(app.runtime, f.project.ref.to_dict(), config)["ready"])

    def test_required_scope_is_reused_and_conflicting_authority_is_pre_effect(self):
        f = self.f
        manager, _schedule = self.role("manager")
        _app, commands, scope, assessment, _pool = self.acceptance(manager)
        request = {"operation": "declare-scope", "request_key": "ordinary-manager-scope",
                   "expected_task_ref": f.task.ref.to_dict(), "expected_assignment_ref": manager.ref.to_dict(),
                   "expected_generation": 1, "arguments": {"scope_ref": {"authority": f.actor.authority,
                        "kind": "assessment.scope", "id": "would-duplicate-gate"},
                       "criterion_refs": [ref.to_dict() for ref in scope.criterion_refs], "protocol": "focused"}}
        result = commands.execute(request)
        self.assertEqual(result["ref"], scope.ref.to_dict())
        self.assertTrue(result["required_scope_reused"])
        self.assertEqual(commands._assessment.coverage(f.task.ref)["scope_count"], 1)
        assessment.declare_scope("incompatible-owner-gate", parent_obligation=f.task.ref, protocol="focused",
            criteria=scope.criterion_refs, designated_approver="root", policy={"required_for_completion": True},
            logical_request_key="incompatible-gate")
        with self.assertRaises(PermissionError):
            commands.execute({**request, "request_key": "reject-duplicate"})
        self.assertEqual(commands._assessment.coverage(f.task.ref)["scope_count"], 2)
        self.assertEqual(f.provider.calls, [])

    def test_ordinary_review_finishes_adopted_scope_without_owner_ratification(self):
        fixture = journey_fixture.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.application
        task = ResourceRef.from_dict(fixture.fixture.state["task_refs"]["PA01"])
        criterion = ResourceRef.from_dict(fixture.fixture.state["criterion_refs"]["C01"])
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope("owner-required-task-scope", parent_obligation=task,
            protocol="adopted-protocol", criteria=[criterion], designated_approver="manager",
            policy={"required_for_completion": True}, logical_request_key="owner-task-scope")
        result = fixture.commands.review_task(fixture.request(key="reuse-adopted-scope"))
        self.assertEqual(result["completion"]["outcome"], "completed", result)
        self.assertEqual(f.owner.graph.get(task).lifecycle.value, "completed")
        from otto.portfolio.assessment import OttoAssessment
        rows = OttoAssessment(assessment, f.actor).coverage(f.owner.graph.get(task).ref)
        self.assertEqual(rows["scope_count"], 1)
        self.assertEqual(rows["scopes"][0]["ref"], scope.ref.to_dict())
        # Setup uses the current completed head; completion consumed the
        # original accepted scope and must not create or spend another gate.
        state = fixture.fixture.state
        state["task_refs"]["PA01"] = f.owner.graph.get(task).ref.to_dict()
        policy = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=state)
        commands = f.owner.manager_assessment(project_ref=state["project_ref"],
            task_ref=state["task_refs"]["PA01"], manager_assignment_ref=state["assignment_ref"],
            manager_actor=state["manager"], manager_generation=state["manager_generation"], assessment_policy=policy)
        assessment.declare_scope("pending-task-scope", parent_obligation=ResourceRef.from_dict(state["task_refs"]["PA06"]),
            protocol="adopted-protocol", criteria=[ResourceRef.from_dict(state["criterion_refs"]["C09"])],
            designated_approver="manager", policy={"required_for_completion": True}, logical_request_key="pending-scope")
        runtime = f.owner.role_runtime(due_port=f.port, adapter=f.app.runtime.adapter, assessment_policy=policy)
        request = {"operation": "resolve-required-scope", "arguments": {},
            "expected_task_ref": state["task_refs"]["PA01"],
            "expected_assignment_ref": state["assignment_ref"], "expected_generation": state["manager_generation"]}
        pool_before = LimitService(f.store).get_pool(policy.pool_ref)
        counts_before = f.owner.graph.reader.snapshot_counts()
        for _ in range(2):
            self.assertEqual(commands.execute(request)["scope_ref"], scope.ref.to_dict())
        ready = runtime.acceptance_readiness(state["project_ref"],
            {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                "generation": state["manager_generation"]}, list(state["task_refs"].values()))
        self.assertEqual(len(ready["required_scopes"]), 2)
        self.assertFalse(ready["allowance_created"])
        self.assertEqual(LimitService(f.store).get_pool(policy.pool_ref), pool_before)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), counts_before)
        # The historical read never grants mutable assessment authority.
        with self.assertRaisesRegex(PermissionError, "exact current task"):
            commands.required_scope()
        with self.assertRaisesRegex(PermissionError, "exact current task"):
            commands.execute({**request, "operation": "freeze-input", "request_key": "no-rejudge",
                "arguments": {"scope_ref": scope.ref.to_dict(), "candidate_ref": result["candidate_ref"],
                    "criterion_refs": [criterion.to_dict()], "source_refs": [], "evidence_refs": [], "packet": {}}})
        # A retained scope alone, or a later revision carrying a copied
        # completion payload, cannot satisfy the exact transition predicate.
        original_reader = commands._reader
        identity = original_reader.get_identity(ResourceRef.from_dict(state["task_refs"]["PA01"]))
        completion = identity.payload["completion"]
        class ReadView:
            def __init__(self, payload, receipt=None, missing=False):
                self.payload, self.receipt, self.missing = payload, receipt, missing
            def get_identity(self, ref):
                return replace(identity, payload=self.payload)
            def get_receipt(self, key):
                return None if self.missing else self.receipt or original_reader.get_receipt(key)
        receipt = original_reader.get_receipt(completion["logical_request_key"])
        cases = [
            ReadView({**identity.payload, "lifecycle": "pending"}),
            ReadView({**identity.payload, "completion": {**completion, "disposition": "unknown"}}),
            ReadView({**identity.payload, "completion": {**completion, "manager": "foreign"}}),
            ReadView({**identity.payload, "completion": {**completion, "task_ref": state["task_refs"]["PA01"]}}),
            ReadView({**identity.payload, "completion": {**completion, "assessment_gate_check": {
                **completion["assessment_gate_check"], "scope_refs": [], "blockers": [{"code": "UNKNOWN"}]}}}),
            ReadView(identity.payload, missing=True),
            ReadView(identity.payload, receipt=replace(receipt, result_ref=task)),
        ]
        for view in cases:
            with self.subTest(view=view):
                commands._reader = view
                with self.assertRaisesRegex(PermissionError, "completion proof"):
                    commands.execute(request)
        commands._reader = original_reader
        self.assertEqual(commands.execute(request)["scope_ref"], scope.ref.to_dict())
        self.assertEqual(f.provider.calls, [])

    def test_missing_execution_contract_rejects_before_initialization_and_valid_request_recovers(self):
        f = self.f
        manager, valid_schedule = self.role("manager")
        bad = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager", request_id="incomplete-mandate",
            document_id="incomplete-mandate", role="mandate", content={"role": "manager", "scope_ref": f.project.ref.to_dict(),
                "status": "active", "brief": {"role": "manager", "mandate": "Advance useful project"}})
        due = f.app._read(valid_schedule)
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=manager.ref.to_dict(), generation=manager.generation,
            mandate_ref=bad["record"]["payload"]["current_revision"], context_refs=due.context_refs,
            request_key="bad-execution-contract", instruction="Advance useful project", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        invalid_schedule = prepared["schedule_id"]
        for start in (lambda: f.app.start(schedule_id=invalid_schedule),
                      lambda: f.app.recover(schedule_id=invalid_schedule, execute=True)):
            result = start()
            self.assertEqual(result["outcome"], "partial", result)
            self.assertIsNone((f.port.read_due(invalid_schedule)["host_evidence"] or {}).get("gateway_attempt"))
        self.assertEqual(f.provider.calls, [])
        valid = f.app.start(schedule_id=valid_schedule)
        self.assertEqual(valid["outcome"], "succeeded", valid)
        self.assertEqual(len(f.provider.calls), 1)
        self.assertEqual(valid["result"]["physical_session_id"], "manager-session")

    def test_conflicting_required_authority_rejects_before_pool_or_review_writes(self):
        fixture = journey_fixture.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.application
        task = ResourceRef.from_dict(fixture.fixture.state["task_refs"]["PA01"])
        criterion = ResourceRef.from_dict(fixture.fixture.state["criterion_refs"]["C01"])
        AssessmentModule(f.store, actor=f.actor).declare_scope("owner-only-task-scope", parent_obligation=task,
            protocol="adopted-protocol", criteria=[criterion], designated_approver="root",
            policy={"required_for_completion": True}, logical_request_key="owner-only-scope")
        with self.assertRaisesRegex(PermissionError, "designated"):
            fixture.commands.review_task(fixture.request(key="reject-foreign-scope"))
        self.assertIsNone(LimitService(f.store).get_pool(ResourceRef(f.actor.authority, "limit", "local-inspection")))
        self.assertIsNone(fixture.commands._journal("reject-foreign-scope", "intent"))
        self.assertEqual(f.provider.calls, [])


if __name__ == "__main__":
    unittest.main()
