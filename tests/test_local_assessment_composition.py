"""Owning-run composition and public DAT acceptance, without native execution."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.content import ContentDocument, ContentRevision
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.work import WorkGraph
from herzchen.kernel.limits import LimitService
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy, compose_manager_assessment_state
from otto.portfolio.manager_assessment_command import manager_assessment_from_command, manager_assessment_pool_from_command
from otto.portfolio.completion_gate import completion_gate_from_command
from otto.portfolio.execution_operations import complete_task_from_command
from tests import test_execution_application as execution


class LocalAssessmentCompositionTests(unittest.TestCase):
    def setUp(self):
        self.f = execution.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        second = WorkGraph(f.store, actor=f.actor).create_task(f.project.ref, title="PA06", logical_request_key="second-task")
        self.manager = f.owner.assignments.command_port.assign(f.project.ref, role="manager", principal="manager",
            manager="manager", session="retained-manager", pins=[], logical_request_key="manager-assignment", actor=f.actor)
        scope = AssessmentModule(f.store, actor=f.actor).declare_scope("original-criteria", parent_obligation=f.project.ref,
            protocol="original-criteria", criteria=[{"id": "C01"}, {"id": "C09"}], logical_request_key="original-criteria")
        self.state = {"authority": f.actor.authority, "project_ref": f.project.ref.to_dict(),
            "task_refs": {"PA01": f.task.ref.to_dict(), "PA06": second.ref.to_dict()},
            "criterion_refs": {key: ref.to_dict() for key, ref in zip(("C01", "C09"), scope.criterion_refs)},
            "manager": "manager", "manager_generation": 1, "assignment_ref": self.manager.ref.to_dict()}
        self.config = {"kind": "owner_local_bookkeeping", "purpose": "local retained inspection", "local_only": True,
            "pool_id": "local-inspection", "capacity_units": 1, "cumulative_allowance_units": 2,
            "task_criterion_pairs": ["PA01/C01", "PA06/C09"]}
        self.config_path = Path(f.temporary.name) / "run.yaml"
        self.config_path.write_text(json.dumps({"assessment_accounting": self.config}))
        self.state = compose_manager_assessment_state(self.state, config_path=self.config_path)

    def request(self, task, operation=None, arguments=None, key="pool-create"):
        value = {"command": "manager-assessment" if operation else "manager-assessment-pool", "task": task,
            "request_key": key, "expected_task_ref": self.state["task_refs"][task],
            "expected_assignment_ref": self.state["assignment_ref"], "expected_generation": 1}
        if operation:
            value.update(operation=operation, arguments=arguments)
        return value

    def call(self, task, operation, arguments, key):
        return manager_assessment_from_command(self.f.owner, state=self.state,
            request=self.request(task, operation, arguments, key))

    def test_declarative_owning_config_normalizes_and_remains_serializable(self):
        policy = LocalAssessmentPolicy.from_run_config(self.config, state=self.state)
        self.assertEqual(policy.pool_ref.to_dict(), {"authority": self.f.actor.authority, "kind": "limit", "id": "local-inspection", "revision": None})
        self.assertEqual(policy.scope_project_ref.to_dict(), self.state["project_ref"])
        self.assertEqual(len(policy.task_criterion_pairs), 2)
        self.assertEqual(json.loads(json.dumps(self.state))["assessment_policy"], self.config)
        record = manager_assessment_pool_from_command(self.f.owner, request=self.request("PA01"), state=self.state)
        self.assertEqual(record["cumulative_allowance_units"], 2)
        self.assertEqual(self.f.provider.calls, [])

    def test_invalid_local_flag_aliases_and_unbounded_allowance_reject(self):
        for changes in ({"local_only": False}, {"local_only": None}, {"cumulative_allowance_units": 3},
                        {"capacity_units": True}, {"task_criterion_pairs": ["PA01/missing"]},
                        {"task_criterion_pairs": ["PA01/C01", "PA01/C01"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                LocalAssessmentPolicy.from_run_config({**self.config, **changes}, state=self.state)
        policy = LocalAssessmentPolicy.from_run_config(self.config, state=self.state)
        stale = replace(policy, scope_project_ref=replace(policy.scope_project_ref, revision="rev-999"))
        with self.assertRaises(PermissionError):
            stale.validate_binding(policy.scope_project_ref, policy.task_criterion_pairs[0][0], self.f.owner.graph.reader)

    def test_scope_mode_is_owner_configured_and_review_required_by_default(self):
        criterion = self.state["criterion_refs"]["C01"]
        review_ref = self.call("PA01", "declare-scope", {"scope_ref": {"authority": self.f.actor.authority,
            "kind": "assessment.scope", "id": "review-mode"}, "criterion_refs": [criterion],
            "protocol": "inspection"}, "review-mode")
        review_scope = AssessmentModule(self.f.store, actor=self.f.actor).get_scope(ResourceRef.from_dict(review_ref["ref"]))
        self.assertTrue(review_scope.review_required)
        self.assertFalse(review_scope.allow_no_review)
        self.assertNotIn("acceptance_mode", review_scope.policy)

        check_config = {**self.config, "scope_mode": "check-accepted"}
        self.config_path.write_text(json.dumps({"assessment_accounting": check_config}))
        self.state = compose_manager_assessment_state(self.state, config_path=self.config_path)
        check_ref = self.call("PA06", "declare-scope", {"scope_ref": {"authority": self.f.actor.authority,
            "kind": "assessment.scope", "id": "check-mode"}, "criterion_refs": [self.state["criterion_refs"]["C09"]],
            "protocol": "inspection"}, "check-mode")
        check_scope = AssessmentModule(self.f.store, actor=self.f.actor).get_scope(ResourceRef.from_dict(check_ref["ref"]))
        self.assertFalse(check_scope.review_required)
        self.assertTrue(check_scope.allow_no_review)
        self.assertEqual(check_scope.policy["acceptance_mode"], "check-accepted")
        self.assertEqual(check_scope.protocol, "check-accepted")

        self.config_path.write_text(json.dumps({"assessment_accounting": self.config}))
        self.state = compose_manager_assessment_state(self.state, config_path=self.config_path)
        with self.assertRaises(PermissionError):
            self.call("PA06", "resolve-required-scope", {}, "mode-drift")

        with self.assertRaises(ValueError):
            LocalAssessmentPolicy.from_run_config({**check_config, "scope_mode": "free-pass"}, state=self.state)
        with self.assertRaises(ValueError):
            self.call("PA06", "declare-scope", {"scope_ref": {"authority": self.f.actor.authority,
                "kind": "assessment.scope", "id": "transport-mode"}, "criterion_refs": [self.state["criterion_refs"]["C09"]],
                "protocol": "inspection", "scope_mode": "review-required"}, "transport-mode")

    def test_check_accepted_rejects_generic_manager_assess_and_accept(self):
        check_config = {**self.config, "scope_mode": "check-accepted"}
        self.config_path.write_text(json.dumps({"assessment_accounting": check_config}))
        self.state = compose_manager_assessment_state(self.state, config_path=self.config_path)
        for operation in ("assess", "accept"):
            with self.subTest(operation=operation), self.assertRaisesRegex(PermissionError, "verified fleet adapter"):
                self.call("PA01", operation, {}, "generic-" + operation)

    def test_transport_cannot_create_arbitrary_budget_or_use_other_pool(self):
        with self.assertRaises(ValueError):
            manager_assessment_pool_from_command(self.f.owner, state=self.state,
                request={**self.request("PA01"), "capacity_units": 99})
        # This is isolated public limit accounting, not actual advisor calls.
        limits = LimitService(self.f.store)
        model_pool = limits.create_pool(ResourceRef(self.f.actor.authority, "limit", "model-pool"),
            capacity_units=1, cumulative_allowance_units=3, logical_request_key="model-pool", actor=self.f.actor)
        for i in range(3):
            reservation = limits.reserve(model_pool.ref, "prior-" + str(i), 1,
                logical_request_key="reserve-" + str(i), actor=self.f.actor)
            limits.settle(reservation, 1, logical_request_key="settle-" + str(i), actor=self.f.actor)
        before = limits.get_pool(model_pool.ref)
        manager_assessment_pool_from_command(self.f.owner, state=self.state, request=self.request("PA01"))
        port = self.f.owner.manager_assessment(project_ref=self.state["project_ref"], task_ref=self.state["task_refs"]["PA01"],
            manager_assignment_ref=self.state["assignment_ref"], manager_actor="manager", manager_generation=1,
            assessment_policy=LocalAssessmentPolicy.from_run_config(self.config, state=self.state))
        self.assertNotEqual(port._policy.pool_ref, model_pool.ref)
        after = limits.get_pool(model_pool.ref)
        self.assertEqual((before.cumulative_used_units, before.held_units), (3, 0))
        self.assertEqual((after.cumulative_used_units, after.held_units), (3, 0))

    def test_current_source_role_dat_documents_accept_and_complete_both_tasks(self):
        manager_assessment_pool_from_command(self.f.owner, state=self.state, request=self.request("PA01"))
        for alias, criterion_alias in (("PA01", "C01"), ("PA06", "C09")):
            with self.subTest(task=alias):
                self.complete_dat_task(alias, criterion_alias)
        self.assertEqual(self.f.provider.calls, [])

    def complete_dat_task(self, alias, criterion_alias):
        f = self.f
        document = ContentDocument(ResourceRef(f.actor.authority, "dat.content.document", "source-" + alias),
            role="SOURCE", visibility="shared", access_mode="read", maintainer="manager", authoring_scope=f.project.ref)
        revision = ContentRevision(document.ref, "rev-1", {"inspection": alias, "source_digest": "a" * 64}, f.actor, initial=True)
        envelope = f.owner.content.build_create_document(TransactionContext(f.actor, "source-" + alias, "b" * 64), document, revision)
        f.owner.content.execute(envelope)
        candidate = revision.ref.to_dict()
        criterion = self.state["criterion_refs"][criterion_alias]
        scope = self.call(alias, "declare-scope", {"scope_ref": {"authority": f.actor.authority, "kind": "assessment.scope", "id": "gate-" + alias},
            "criterion_refs": [criterion], "protocol": "retained-source-inspection"}, "scope-" + alias)["ref"]
        packet = self.call(alias, "freeze-input", {"scope_ref": scope, "candidate_ref": candidate, "criterion_refs": [criterion],
            "source_refs": [candidate], "evidence_refs": [candidate], "packet": {"inspected": True}}, "input-" + alias)["ref"]
        self.call(alias, "select-candidate", {"scope_ref": scope, "candidate_ref": candidate, "criterion_ref": criterion,
            "rationale": "exact current admitted source"}, "select-" + alias)
        result = self.call(alias, "assess", {"scope_ref": scope, "candidate_ref": candidate, "criterion_ref": criterion,
            "input_ref": packet, "verdict": "PASS", "limit_pool_ref": {"authority": f.actor.authority, "kind": "limit", "id": "local-inspection"},
            "protocol_result": {"inspected": True}}, "assess-" + alias)["ref"]
        # Other caller pools are rejected before reservation or result writes.
        with self.assertRaises(PermissionError):
            self.call(alias, "assess", {"scope_ref": scope, "candidate_ref": candidate, "criterion_ref": criterion,
                "input_ref": packet, "verdict": "PASS", "limit_pool_ref": {"authority": f.actor.authority, "kind": "limit", "id": "model-pool"},
                "protocol_result": {"inspected": True}}, "wrong-pool-" + alias)
        decision = self.call(alias, "accept", {"result_ref": result, "candidate_ref": candidate, "criterion_ref": criterion,
            "evidence_refs": [candidate], "rationale": "local inspection accepted"}, "accept-" + alias)["ref"]
        gate_request = {"candidate_ref": json.dumps(candidate), "gate_refs": [json.dumps(decision)],
            "evidence_refs": [json.dumps(candidate)], "evidence_hashes": [revision.content_digest]}
        gate = completion_gate_from_command(f.owner.assignments.command_port, request=gate_request,
            task_ref=self.state["task_refs"][alias], actor=f.actor)
        self.assertEqual(gate["eligibility"], "clear", gate)
        self.assertEqual(gate["owner_gate_state"]["evidence_verification"], "verified")
        completed = complete_task_from_command(f.app.portfolio,
            request={**gate_request, "evidence_hashes": ["content=" + revision.content_digest],
                     "request_key": "complete-" + alias, "disposition": "accepted"},
            project_ref=self.state["project_ref"], task_ref=self.state["task_refs"][alias],
            manager_assignment_ref=self.state["assignment_ref"], manager_actor="manager", manager_generation=1)
        self.assertEqual(completed["outcome"], "completed", completed)
