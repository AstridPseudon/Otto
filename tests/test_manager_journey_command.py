"""Ordinary explicit judgment uses real assessment/completion/lifecycle APIs."""
import unittest
import argparse

from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.content import ContentDocument, ContentRevision
from herzchen.kernel.limits import LimitService
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from tests import test_local_assessment_composition as local


class ManagerJourneyCommandTests(unittest.TestCase):
    def setUp(self):
        self.fixture = local.LocalAssessmentCompositionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.application = self.fixture.f
        self.commands = ManagerJourneyCommands(owner=self.application.owner, portfolio=self.application.app.portfolio,
                                               state=self.fixture.state)

    def source(self, alias):
        document = ContentDocument(ResourceRef(self.application.actor.authority, "dat.content.document", "source-" + alias),
            role="SOURCE", visibility="shared", access_mode="read", maintainer="manager", authoring_scope=self.application.project.ref)
        revision = ContentRevision(document.ref, "rev-1", {"verified": alias}, self.application.actor, initial=True)
        envelope = self.application.owner.content.build_create_document(
            TransactionContext(self.application.actor, "source-" + alias, "a" * 64), document, revision)
        self.application.owner.content.execute(envelope)
        return revision.ref.to_dict()

    def request(self, alias="PA01", candidate=None, verdict="PASS", key="ordinary-review"):
        criterion = "C01" if alias == "PA01" else "C09"
        candidate = candidate or self.source(alias)
        return {"command": "review-task", "task": alias, "request_key": key,
                "candidate_ref": candidate, "source_refs": [candidate],
                "inspection": {"observed": "Inspected the exact retained source and its focused verification"},
                "judgments": {criterion: {"verdict": verdict,
                    "rationale": "The retained evidence satisfies the declared criterion" if verdict == "PASS" else "The retained check is incomplete",
                    "evidence_refs": [candidate]}}}

    def test_one_operation_accepts_source_and_completes_replay_without_provider(self):
        request = self.request()
        first = self.commands.review_task(request)
        self.assertEqual(first["outcome"], "accepted")
        self.assertEqual(first["completion"]["outcome"], "completed", first)
        self.assertEqual(self.commands.review_task(request)["completion"]["outcome"], "replayed")
        self.assertEqual(self.application.provider.calls, [])
        pool = LimitService(self.application.store).get_pool(ResourceRef(self.application.actor.authority, "limit", "local-inspection"))
        self.assertEqual(pool.cumulative_used_units, 1)
        with self.assertRaises(ValueError):
            self.commands.review_task({**request, "inspection": {"different": True}})

    def test_review_reuses_precreated_bound_pool_from_a_different_setup_key(self):
        policy = self.fixture.state["assessment_policy"]
        LimitService(self.application.store).create_pool(
            ResourceRef(self.application.actor.authority, "limit", "local-inspection"),
            capacity_units=policy["capacity_units"],
            cumulative_allowance_units=policy["cumulative_allowance_units"],
            logical_request_key="controller-local-pool-setup", actor=self.application.actor)
        result = self.commands.review_task(self.request(key="precreated-pool-review"))
        self.assertEqual(result["outcome"], "accepted", result)
        self.assertEqual(result["completion"]["outcome"], "completed", result)
        pool = LimitService(self.application.store).get_pool(
            ResourceRef(self.application.actor.authority, "limit", "local-inspection"))
        self.assertEqual(pool.cumulative_used_units, 1)

    def test_existing_bound_pool_with_different_limits_is_rejected(self):
        policy = self.fixture.state["assessment_policy"]
        LimitService(self.application.store).create_pool(
            ResourceRef(self.application.actor.authority, "limit", "local-inspection"),
            capacity_units=policy["capacity_units"],
            cumulative_allowance_units=policy["cumulative_allowance_units"] + 1,
            logical_request_key="controller-wrong-pool-setup", actor=self.application.actor)
        with self.assertRaises(PermissionError):
            self.commands.review_task(self.request(key="wrong-pool-review"))

    def test_rework_never_accepts_and_repaired_evidence_uses_same_required_scope(self):
        request = self.request(verdict="REWORK")
        rejected = self.commands.review_task(request)
        self.assertEqual(rejected["outcome"], "rework")
        self.assertEqual(rejected["gate_refs"], [])
        current = self.application.owner.graph.reader.get_identity(self.application.task.ref)
        self.assertEqual(current.payload["lifecycle"], "pending")
        repaired = self.request(candidate=request["candidate_ref"], key="repaired-review")
        result = self.commands.review_task(repaired)
        self.assertEqual(result["completion"]["outcome"], "completed", result)

    def test_unknown_missing_criteria_foreign_actor_and_stale_source_do_not_autoaccept(self):
        request = self.request(verdict="UNKNOWN")
        self.assertEqual(self.commands.review_task(request)["outcome"], "unknown")
        with self.assertRaises(ValueError):
            self.commands.review_task({**request, "request_key": "missing-criteria", "judgments": {}})
        stale = {**request["candidate_ref"], "revision": "rev-999"}
        with self.assertRaises(ValueError):
            self.commands.review_task(self.request(candidate=stale, key="stale-source"))
        self.fixture.state["manager"] = "foreign-manager"
        with self.assertRaises(PermissionError):
            self.commands.review_task(request)

    def test_project_finish_holds_unfinished_tasks_then_records_terminal_and_pending_settlement(self):
        request = {"command": "finish-project", "request_key": "project-finish",
            "dispositions": {name: {"status": "qualified", "rationale": "Isolated local journey; no publication or remote effects required"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}
        observer = lambda project: {"mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
            "coverage": {"project_id": project, "fixture": "all fixture Due records inspected"}, "shared_records": []}
        call = lambda: self.commands.finish_project(request, orchestrator_principal="orchestrator", observe_schedules=observer)
        self.assertEqual(call()["outcome"], "held")
        for alias in ("PA01", "PA06"):
            result = self.commands.review_task(self.request(alias=alias, key="review-" + alias))
            self.assertEqual(result["completion"]["outcome"], "completed", result)
        observer = lambda project: {"unknown_ownership": True}
        pending = call()
        self.assertEqual(pending["outcome"], "pending", pending)
        self.assertTrue(pending["project_completion_recorded"])
        self.assertTrue(pending["settlement_pending"])
        observer = lambda project: {"mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
            "coverage": {"project_id": project}, "shared_records": []}
        terminal = call()
        self.assertEqual(terminal["outcome"], "completed", terminal)
        self.assertEqual(terminal["readback"]["lifecycle"], "completed")
        self.assertFalse(terminal["settlement_pending"])
        self.assertEqual(call()["outcome"], "completed")

    def test_client_definitions_request_judgment_without_owner_pins_or_pool_fields(self):
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest="command", required=True))
        request = vars(parser.parse_args(["review-task", "--task", "J01", "--request-key", "review",
            "--candidate-ref", '{"id":"candidate"}', "--source-ref", '{"id":"source"}',
            "--judgments", '{"C01":{"verdict":"PASS"}}', "--inspection", '{"observed":"check"}',
            "--review-only"]))
        self.assertFalse(request["finish"])
        self.assertEqual(request["source_refs"], [{"id": "source"}])
        self.assertFalse(any(name in request for name in ("actor", "pool", "expected_task_ref")))

    def test_current_reassigned_manager_can_review_and_close_with_distinct_orchestrator_epoch(self):
        assignment = self.application.owner.assignments.command_port.reassign(self.fixture.manager.ref,
            principal="manager", reason="same-manager native recovery", expected_generation=1,
            logical_request_key="current-manager", actor=self.application.actor)
        self.fixture.state.update(assignment_ref=assignment.ref.to_dict(), manager_generation=assignment.generation)
        for alias in ("PA01", "PA06"):
            result = self.commands.review_task(self.request(alias=alias, key="reassigned-" + alias))
            self.assertEqual(result["completion"]["outcome"], "completed", result)
        result = self.commands.finish_project({"request_key": "reassigned-project",
            "dispositions": {name: {"status": "qualified", "rationale": "Local fixture only; no external obligations"}
                             for name in ("acceptance", "publication", "remote", "runtime")}},
            orchestrator_principal="orchestrator", observe_schedules=lambda project: {
                "mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
                "coverage": {"project": project}, "shared_records": []})
        self.assertEqual(result["outcome"], "completed", result)
        project = self.application.owner.graph.reader.get_identity(ResourceRef(self.application.project.ref.authority, "work.project", self.application.project.ref.id))
        attribution = project.payload["lifecycle_control"]["owner_attribution"]
        self.assertEqual(attribution["manager"]["generation"], 2)
        self.assertEqual(attribution["orchestrator"]["generation"], 1)

    def test_native_completion_intent_waits_for_exact_settlement_without_provider_retry(self):
        prepared = self.application.app.assign_worker(**self.application.request())
        self.application.app.start(schedule_id=prepared["schedule_id"], settle=False)
        candidate = self.application.app.assignments.list_observations(
            ResourceRef.from_dict(prepared["assignment_ref"]), kind="result")[0].ref.to_dict()
        request = self.request(candidate=candidate)
        self.commands.due_port = self.application.port
        reviewed = self.commands.review_task(request)
        self.assertEqual(reviewed["completion"]["outcome"], "pending", reviewed)
        self.assertEqual(self.application.owner.graph.get(self.application.task.ref).lifecycle.value, "pending")
        calls = len(self.application.provider.calls)
        self.commands.settle_execution = lambda due: self.application.app.recover(schedule_id=due["schedule_id"], execute=False)
        completed = self.commands.review_task(request)
        self.assertEqual(completed["completion"]["outcome"], "completed", completed)
        self.assertEqual(len(self.application.provider.calls), calls)
        self.assertEqual(self.application.port.read_due(prepared["schedule_id"])["completion_state"], "succeeded")


if __name__ == "__main__":
    unittest.main()
