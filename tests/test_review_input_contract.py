"""Policy/readback parity over a real owner; only the Due read is substituted."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import argparse
import unittest

from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.manager_journey_client import add_manager_journey_parsers, command_result_summary
from tests import test_manager_journey_command as journey


class ReviewInputContractTests(unittest.TestCase):
    def setUp(self):
        fixture = journey.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f, self.commands = fixture.application, fixture.commands
        self.state = fixture.fixture.state
        # Two configured criteria catch implementations that expose only one.
        self.state["assessment_policy"]["task_criterion_pairs"] = ["PA01/C01", "PA01/C09"]
        self.worker = self.f.owner.assignments.command_port.assign(self.f.task.ref,
            role="worker", principal="worker", manager="manager", session="worker-session",
            pins=[], logical_request_key="readback-worker", actor=self.f.actor)
        result = {"outcome": "succeeded", "context_digest_verified": True,
                  "task_ref": self.state["task_refs"]["PA01"], "project_ref": self.state["project_ref"],
                  "observed_turn_id": "retained-turn", "physical_session_id": "worker-session"}
        self.observation = self.f.owner.assignments.command_port.append_result(self.worker.ref, result,
            expected_generation=1, logical_request_key="readback-result", actor=self.f.actor)
        self.due = {"assignment_ref": self.worker.ref.to_dict(), "generation": 1,
                    "stop_state": "completed", "completion_state": "succeeded", "in_flight_request": None,
                    "host_evidence": {"gateway_attempt": {"result": result}}}
        self.state["workers"] = {"PA01": {"assignment_ref": self.worker.ref.to_dict(),
            "generation": 1, "principal": "worker", "schedule_id": "retained-worker"}}
        self.commands.due_port = SimpleNamespace(read_due=lambda schedule: deepcopy(self.due))

    def request(self, key="current-review"):
        ref = self.observation.ref.to_dict()
        return {"command": "review-task", "task": "PA01", "request_key": key,
                "candidate_ref": ref, "source_refs": [ref], "finish": False,
                "inspection": {"observed": "Inspected this exact retained result"},
                "judgments": {alias: {"verdict": "REWORK", "rationale": "Observed missing behavior",
                                      "evidence_refs": [ref]} for alias in ("C01", "C09")}}

    def test_real_owner_read_all_criteria_then_one_review_and_exact_replay(self):
        before = self.f.owner.graph.reader.snapshot_counts()
        inputs = self.commands.review_input("PA01")
        self.assertEqual(inputs["candidate_ref"], self.observation.ref.to_dict())
        self.assertEqual(inputs["criterion_aliases"], self.state["criterion_refs"])
        self.assertEqual(inputs["inspection_schema"]["type"], "object")
        self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), before)
        poolref = ResourceRef(self.f.actor.authority, "limit", "local-inspection")
        self.assertIsNone(LimitService(self.f.store).get_pool(poolref))
        request = self.request()
        result = self.commands.review_task(request)
        self.assertEqual(result["outcome"], "rework")
        self.assertEqual(LimitService(self.f.store).get_pool(poolref).cumulative_used_units, 2)
        before = self.f.owner.graph.reader.snapshot_counts()
        self.assertEqual(self.commands.review_task(request), result)
        self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual(self.f.provider.calls, [])

    def test_wrong_alias_and_inspection_shape_fail_before_journal_or_debit(self):
        request = self.request()
        for changes, message in (({"judgments": {"acceptance": request["judgments"]["C01"]}},
                                  "exact aliases: C01, C09"),
                                 ({"inspection": "inspection text"}, "nonempty JSON object"),
                                 ({"inspection": []}, "nonempty JSON object"),
                                 ({"inspection": {}}, "nonempty JSON object")):
            with self.subTest(changes=changes):
                before = self.f.owner.graph.reader.snapshot_counts()
                with self.assertRaisesRegex(ValueError, message):
                    self.commands.review_task({**request, **changes})
                self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), before)
                self.assertIsNone(self.commands._journal(request["request_key"], "intent"))
                self.assertIsNone(LimitService(self.f.store).get_pool(
                    ResourceRef(self.f.actor.authority, "limit", "local-inspection")))
        self.assertEqual(self.f.provider.calls, [])

    def test_foreign_actor_worker_project_and_stale_policy_remain_denied(self):
        before = self.f.owner.graph.reader.snapshot_counts()
        original = self.state["manager"]
        self.state["manager"] = "foreign-manager"
        with self.assertRaises(PermissionError): self.commands.review_input("PA01")
        self.state["manager"] = original
        self.state["workers"]["PA01"]["generation"] = 2
        with self.assertRaises(PermissionError): self.commands.review_input("PA01")
        self.state["workers"]["PA01"]["generation"] = 1
        policy = LocalAssessmentPolicy.from_run_config(self.state["assessment_policy"], state=self.state)
        self.commands.policy = replace(policy, scope_project_ref=replace(policy.scope_project_ref, id="foreign"))
        with self.assertRaises(PermissionError): self.commands.review_input("PA01")
        task, criterion = policy.task_criterion_pairs[0]
        self.commands.policy = replace(policy, task_criterion_pairs=(
            (task, replace(criterion, revision="rev-999")), *policy.task_criterion_pairs[1:]))
        with self.assertRaises(PermissionError): self.commands.review_input("PA01")
        self.commands.policy = policy
        with self.assertRaisesRegex(ValueError, "unknown task alias"): self.commands.review_input("foreign-task")
        request = self.request("foreign-candidate")
        request["candidate_ref"] = {**request["candidate_ref"], "authority": "foreign"}
        request["judgments"]["C01"]["evidence_refs"] = [request["candidate_ref"]]
        with self.assertRaises((PermissionError, ValueError)):
            self.commands.review_task(request)
        self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual(self.f.provider.calls, [])

    def test_pending_read_summary_and_cli_keep_contract_without_assessment(self):
        self.due["completion_state"] = "none"
        inputs = self.commands.review_input("PA01")
        self.assertEqual(inputs["outcome"], "pending")
        for value in (inputs, {"review_input": inputs}):
            summary = command_result_summary(value)
            projected = summary.get("review_input", summary)
            self.assertEqual(projected["criterion_aliases"], inputs["criterion_aliases"])
            self.assertEqual(projected["inspection_schema"]["min_properties"], 1)
        del self.state["workers"]["PA01"]
        self.assertEqual(self.commands.review_input("PA01")["criterion_aliases"], inputs["criterion_aliases"])
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_manager_journey_parsers(subparsers)
        help_text = " ".join(subparsers.choices["review-task"].format_help().split())
        self.assertIn("nonempty JSON object", help_text)
        self.assertIn("not a JSON string", help_text)


if __name__ == "__main__":
    unittest.main()
