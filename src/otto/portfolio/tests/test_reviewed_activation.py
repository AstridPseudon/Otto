"""Focused D04 checks for reviewed-plan activation."""

import unittest
from unittest.mock import patch

from herzchen.command_ports import SerializedCommandClient
from herzchen.contracts import ResourceRef
from herzchen.domains.work.module import WorkGraph
from herzchen.kernel import LimitService
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.reviewed_activation import ReviewedPlanActivation
from tests import test_execution_application as owner_fixture


class ReviewedActivationTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.portfolio = OttoPortfolio(self.f.owner.consumer_operations())

    def _documents(self):
        plan = self.portfolio.create_document(self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-plan", role="plan", content={
                "schema": "otto.plan.v1", "deliverables": [
                    {"id": "one", "title": "First", "acceptance": ["first"]},
                    {"id": "two", "title": "Second", "acceptance": ["second"]},
                    {"id": "three", "title": "Third", "acceptance": ["third"]},
                    {"id": "four", "title": "Fourth", "acceptance": ["fourth"]},
                    {"id": "five", "title": "Fifth", "acceptance": ["fifth"]},
                ]})
        plan_ref = dict(plan["document_ref"])
        # DAT document references are pinned by the current immutable document
        # head before they become activation inputs.
        plan_ref["revision"] = "rev-1"
        review = self.portfolio.create_document(self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-review", role="review", content={
                "plan_ref": plan_ref, "disposition": "approved"})
        review_ref = dict(review["document_ref"])
        review_ref["revision"] = "rev-1"
        return plan_ref, review_ref

    def test_readiness_holds_then_materializes_five_pairs_once(self):
        plan_ref, review_ref = self._documents()
        policy = {"pool_id": "d04-pool", "capacity_units": 1,
                  "cumulative_allowance_units": 5}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        held = activation.read(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy)
        self.assertTrue(held["ready"], held)
        result = activation.activate(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy, request_key="d04-activate", manager="manager")
        self.assertEqual(result["outcome"], "activated", result)
        self.assertEqual(len(result["task_refs"]), 5)
        self.assertEqual(len(result["criterion_refs"]), 5)
        self.assertFalse(result["dispatch"])
        self.assertFalse(result["terminal_acceptance"])
        again = activation.activate(project_ref=result["project_ref"], plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy, request_key="d04-retry", manager="manager")
        self.assertEqual(again["outcome"], "replayed", again)
        self.assertEqual(again["task_refs"], result["task_refs"])
        self.assertEqual(len(self.f.owner.graph.list(project=result["project_ref"], kind="task")), 6)
        self.assertEqual(len(self.f.provider.calls), 0)

    def test_conflicting_review_and_policy_plan_aliases_hold_before_activation(self):
        plan_a, clean_review = self._documents()
        other = self.portfolio.create_document(
            self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-other-plan", role="plan",
            content={"schema": "otto.plan.v1",
                     "deliverables": [{"id": "other", "title": "Other"}]})
        plan_b = dict(other["document_ref"])
        plan_b["revision"] = "rev-1"

        conflicting = self.portfolio.create_document(
            self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-conflicting-review", role="review",
            content={"plan_ref": plan_a, "reviewed_plan_ref": plan_b,
                     "disposition": "approved"})
        conflicting_review = dict(conflicting["document_ref"])
        conflicting_review["revision"] = "rev-1"

        specs = {"task_specs": [{"id": "one", "title": "First"}]}
        cases = (
            ("review", conflicting_review, specs,
             {"plan_ref": plan_a, "reviewed_plan_ref": plan_b}),
            ("owner_policy", clean_review,
             {**specs, "plan_ref": plan_a, "required_plan_ref": plan_b},
             {"plan_ref": plan_a, "required_plan_ref": plan_b}),
        )
        for source, review_ref, policy, values in cases:
            with self.subTest(source=source):
                activation = self.f.owner.reviewed_plan_activation(
                    owner_policy=policy)
                arguments = dict(project_ref=self.f.project.ref.to_dict(),
                                 plan_ref=plan_a, review_ref=review_ref,
                                 owner_policy=policy)
                readiness = activation.read(**arguments)
                self.assertFalse(readiness["ready"], readiness)
                self.assertEqual(readiness["state"], "held")
                conflicts = [
                    item for item in readiness["blockers"]
                    if item.get("code") == "ambiguous_plan_pin"
                    and item.get("source") == source
                ]
                self.assertEqual(len(conflicts), 1, readiness)
                self.assertEqual(conflicts[0]["values"], values)
                result = activation.activate(
                    **arguments, request_key="d04-conflict-" + source)
                self.assertEqual(result["outcome"], "held", result)
                self.assertFalse(result["effects_started"])
                self.assertEqual(
                    len(self.f.owner.graph.list(
                        project=self.f.project.ref, kind="task")), 1)
                self.assertEqual(len(self.f.provider.calls), 0)

        consistent = self.portfolio.create_document(
            self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-consistent-review", role="review",
            content={"plan_ref": plan_a,
                     "reviewed_plan_ref": {"ref": plan_a},
                     "disposition": "approved"})
        consistent_review = dict(consistent["document_ref"])
        consistent_review["revision"] = "rev-1"
        policy = {**specs, "plan_ref": plan_a, "required_plan_ref": plan_a}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        self.assertTrue(activation.read(
            project_ref=self.f.project.ref.to_dict(), plan_ref=plan_a,
            review_ref=consistent_review, owner_policy=policy)["ready"])

    def test_malformed_plan_alias_does_not_fall_through_to_valid_alias(self):
        plan_ref, _review_ref = self._documents()
        malformed_review = self.portfolio.create_document(
            self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-malformed-review", role="review",
            content={"plan_ref": None, "reviewed_plan_ref": plan_ref,
                     "disposition": "approved"})
        review_ref = dict(malformed_review["document_ref"])
        review_ref["revision"] = "rev-1"
        policy = {"task_specs": [{"id": "one", "title": "First"}]}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        readiness = activation.read(
            project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy)
        self.assertFalse(readiness["ready"], readiness)
        self.assertIn({"code": "invalid_plan_pin", "source": "review",
                       "values": {"plan_ref": None}}, readiness["blockers"])

    def test_conflicting_review_digest_aliases_hold_readiness(self):
        plan_ref, _review_ref = self._documents()
        review = self.portfolio.create_document(
            self.f.project.ref.to_dict(), actor="manager",
            request_id="d04-conflicting-digest", role="review",
            content={"plan_ref": plan_ref, "plan_digest": "first",
                     "reviewed_plan_digest": "second",
                     "disposition": "approved"})
        review_ref = dict(review["document_ref"])
        review_ref["revision"] = "rev-1"
        policy = {"task_specs": [{"id": "one", "title": "First"}]}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        readiness = activation.read(
            project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy)
        self.assertFalse(readiness["ready"], readiness)
        self.assertIn({"code": "ambiguous_plan_digest", "source": "review",
                       "values": {"plan_digest": "first",
                                  "reviewed_plan_digest": "second"}},
                      readiness["blockers"])

    def test_nonterminal_predecessor_holds_without_work_effects(self):
        plan_ref, review_ref = self._documents()
        predecessor = self.f.owner.graph.create_project(title="Predecessor", logical_request_key="d04-predecessor")
        policy = {"name": "current-policy", "task_specs": [{"id": "one", "title": "First"}]}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        readiness = activation.read(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy, predecessor_ref=predecessor.ref.to_dict())
        self.assertFalse(readiness["ready"])
        result = activation.activate(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy, predecessor_ref=predecessor.ref.to_dict(),
            request_key="d04-held")
        self.assertEqual(result["outcome"], "held")
        self.assertFalse(result["effects_started"])
        self.assertEqual(len(self.f.owner.graph.list(project=self.f.project.ref, kind="task")), 1)

    def test_caller_cannot_replace_adopted_policy_or_manager_binding(self):
        plan_ref, review_ref = self._documents()
        policy = {"pool_id": "d04-binding-pool", "capacity_units": 1,
                  "cumulative_allowance_units": 5}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        binding = activation.read(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy)["owner_policy"]["binding"]
        self.assertEqual(binding["owner"], {"authority": self.f.store.authority, "actor": "manager"})
        self.assertEqual(binding["policy_source"], "test-host")
        self.assertEqual(binding["policy_revision"], "v1")
        with self.assertRaisesRegex(ValueError, "current adopted policy binding"):
            activation.read(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
                review_ref=review_ref, owner_policy={**policy, "pool_id": "foreign-pool"})
        with self.assertRaisesRegex(ValueError, "owner-bound adopted policy"):
            ReviewedPlanActivation(self.f.owner).read(project_ref=self.f.project.ref.to_dict(),
                plan_ref=plan_ref, review_ref=review_ref, owner_policy=policy)
        with self.assertRaisesRegex(ValueError, "manager is outside"):
            activation.activate(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
                review_ref=review_ref, owner_policy=policy, request_key="d04-foreign-manager",
                manager="foreign-manager")
        self.assertEqual(len(self.f.owner.graph.list(project=self.f.project.ref, kind="task")), 1)

    def test_same_request_recovers_each_committed_activation_stage_without_duplicates(self):
        stages = ("task", "criterion", "pool", "marker", "activation")
        for stage in stages:
            with self.subTest(stage=stage):
                fixture = owner_fixture.ExecutionApplicationTests()
                fixture.setUp()
                try:
                    plan_ref, review_ref = ReviewedActivationTests._documents_for(fixture)
                    policy = {"pool_id": "d04-recovery-pool", "capacity_units": 1,
                              "cumulative_allowance_units": 5}
                    activation = fixture.owner.reviewed_plan_activation(owner_policy=policy)
                    request_key = "d04-recovery-" + stage
                    self._interrupt_once(fixture, activation, stage)
                    try:
                        with self.assertRaisesRegex(RuntimeError, "lost reply"):
                            activation.activate(project_ref=fixture.project.ref.to_dict(), plan_ref=plan_ref,
                                review_ref=review_ref, owner_policy=policy, request_key=request_key,
                                manager="manager")
                    finally:
                        activation._test_interrupt_patcher.stop()
                    result = activation.activate(project_ref=fixture.project.ref.to_dict(), plan_ref=plan_ref,
                        review_ref=review_ref, owner_policy=policy, request_key=request_key,
                        manager="manager")
                    self.assertIn(result["outcome"], {"activated", "replayed"}, result)
                    self.assertEqual(len(fixture.owner.graph.list(project=result["project_ref"], kind="task")), 6)
                    pool = LimitService(fixture.store).get_pool(
                        ResourceRef(fixture.owner.owner_actor.authority, "limit", policy["pool_id"]))
                    self.assertIsNotNone(pool)
                    self.assertEqual(pool.cumulative_allowance_units, 5)
                    self.assertFalse(result["dispatch"])
                    self.assertFalse(result["terminal_acceptance"])
                finally:
                    fixture.doCleanups()

    @staticmethod
    def _documents_for(fixture):
        portfolio = OttoPortfolio(fixture.owner.consumer_operations())
        plan = portfolio.create_document(fixture.project.ref.to_dict(), actor="manager",
            request_id="d04-recovery-plan", role="plan", content={
                "schema": "otto.plan.v1", "deliverables": [
                    {"id": "one", "title": "First", "acceptance": ["first"]},
                    {"id": "two", "title": "Second", "acceptance": ["second"]},
                    {"id": "three", "title": "Third", "acceptance": ["third"]},
                    {"id": "four", "title": "Fourth", "acceptance": ["fourth"]},
                    {"id": "five", "title": "Fifth", "acceptance": ["fifth"]},
                ]})
        plan_ref = dict(plan["document_ref"])
        plan_ref["revision"] = "rev-1"
        review = portfolio.create_document(fixture.project.ref.to_dict(), actor="manager",
            request_id="d04-recovery-review", role="review", content={
                "plan_ref": plan_ref, "disposition": "approved"})
        review_ref = dict(review["document_ref"])
        review_ref["revision"] = "rev-1"
        return plan_ref, review_ref

    @staticmethod
    def _interrupt_once(fixture, activation, stage):
        """Make one committed stage look like a lost reply, then restore it."""
        state = {"raised": False}

        def after(original):
            def wrapped(*args, **kwargs):
                result = original(*args, **kwargs)
                if not state["raised"]:
                    state["raised"] = True
                    raise RuntimeError("lost reply")
                return result
            return wrapped

        if stage == "task":
            original = WorkGraph.create_task
            def wrapped(graph, *args, **kwargs):
                return after(original)(graph, *args, **kwargs)
            patcher = patch.object(WorkGraph, "create_task", autospec=True, side_effect=wrapped)
        elif stage == "criterion":
            target = __import__("herzchen.domains.assessment", fromlist=["AssessmentModule"]).AssessmentModule
            original = target.declare_scope
            def wrapped(owner, *args, **kwargs):
                return after(original)(owner, *args, **kwargs)
            patcher = patch.object(target, "declare_scope", autospec=True, side_effect=wrapped)
        elif stage == "pool":
            patcher = patch.object(activation, "_pool", side_effect=after(activation._pool))
        elif stage == "marker":
            original = WorkGraph.revise
            def wrapped(graph, *args, **kwargs):
                return after(original)(graph, *args, **kwargs)
            patcher = patch.object(WorkGraph, "revise", autospec=True, side_effect=wrapped)
        else:
            original = SerializedCommandClient.call
            def wrapped(client, operation, *args, **kwargs):
                result = original(client, operation, *args, **kwargs)
                if operation == "activate_project":
                    return after(lambda: result)()
                return result
            patcher = patch.object(SerializedCommandClient, "call", autospec=True, side_effect=wrapped)
        patcher.start()
        activation._test_interrupt_patcher = patcher


if __name__ == "__main__":
    unittest.main()
