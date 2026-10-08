import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from otto.portfolio.manager_handoff import compose_manager_handoff
from otto.portfolio.manager_journey_service import ManagerJourneyService


PROJECT = {"authority": "owner", "kind": "work.project", "id": "project-1", "revision": "rev-2"}
ASSIGNMENT = {"authority": "owner", "kind": "wrk.assignment", "id": "assignment-1", "revision": "rev-3"}
TASK = {"authority": "owner", "kind": "work.task", "id": "task-1", "revision": "rev-1"}


class ManagerHandoffTests(unittest.TestCase):
    def test_projection_is_bounded_and_keeps_evidence_as_refs(self):
        current = {
            "schedule_id": "due-1", "version": 4, "delivery_state": "ready", "completion_state": "none",
            "assignment_ref": ASSIGNMENT, "generation": 2,
            "target": {"project_ref": PROJECT, "task_ref": TASK, "mandate_ref": {"authority": "owner", "kind": "dat.content.document", "id": "mandate-1"}},
            "gateway_attempt": {"result": {"native": "retained"}},
        }
        decisions = [{"ref": {"authority": "owner", "kind": "assessment.decision", "id": str(index)},
                      "value": {"disposition": "accepted", "evidence": "large" * 1000}}
                     for index in range(200)]
        result = compose_manager_handoff(
            project_ref=PROJECT, project={"ref": PROJECT, "payload": {"large": "x" * 100000}},
            assignment={"ref": ASSIGNMENT, "role": "manager", "principal": "manager", "generation": 2},
            current_occurrence=current,
            effective_context={"state": "known", "generation": 2, "instruction_sha256": "abc"},
            status={"canonical_lifecycle": "pending", "blockers": [{"code": "held"}],
                    "agent_suggestion": "continue", "historical_uncertain_effects": [{"schedule_id": "old"}]},
            tasks=[{"ref": TASK, "authored": {"title": "Work", "lifecycle": "pending"}}],
            decisions=decisions,
            reports=[{"ref": {"authority": "owner", "kind": "wrk.report", "id": "report-1"},
                      "value": {"summary": "suggested next step"}}],
            as_of="2026-10-07T00:00:00Z",
        )
        self.assertEqual(result["current_occurrence"]["state"], "unknown")
        self.assertEqual(len(result["decisions"]), 128)
        self.assertEqual(result["attributed_notes"][0]["authority"], "attributed_suggestion")
        self.assertNotIn("large", result["decisions"][0])
        self.assertEqual(len(result["envelope_sha256"]), 64)

    def test_unknown_and_terminal_states_are_distinct(self):
        result = compose_manager_handoff(
            project_ref=PROJECT,
            assignment=ASSIGNMENT,
            current_occurrence={"schedule_id": "due-current", "completion_state": "completed"},
            historical_occurrences=[{"schedule_id": "due-old", "delivery_state": "unknown"}],
            status={"canonical_lifecycle": "completed"},
            as_of="2026-10-07T00:00:00Z",
        )
        self.assertEqual(result["current_occurrence"]["state"], "terminal")
        self.assertEqual(result["historical_occurrences"][0]["state"], "unknown")
        self.assertFalse(result["authority"]["dispatch"])

        accepted = compose_manager_handoff(
            project_ref=PROJECT, current_occurrence={"schedule_id": "due-accepted", "completion_state": "accepted"},
            status={}, as_of="2026-10-07T00:00:00Z",
        )
        self.assertEqual(accepted["current_occurrence"]["state"], "accepted")

    def test_preclipped_instruction_preview_retains_full_source_digest_and_flag(self):
        for text, upstream, expected in (("x" * 2048, True, True), ("complete", False, False),
                                         ("x" * 2049, False, True)):
            with self.subTest(upstream=upstream, length=len(text)):
                result = compose_manager_handoff(project_ref=PROJECT,
                    effective_context={"state": "known", "role_instructions": text,
                        "role_instructions_truncated": upstream, "instruction_sha256": "full-retained-guide-digest",
                        "source_refs": {"guide": {"authority": "owner", "kind": "dat.content.document", "id": "guide", "revision": "rev-1"}}},
                    as_of="2026-10-07T00:00:00Z")
                context = result["effective_context"]["value"]
                self.assertEqual(context["role_instructions_truncated"], expected)
                self.assertEqual(context["instruction_sha256"], "full-retained-guide-digest")
                self.assertEqual(len(context["role_instructions"]), min(len(text), 2048))
                self.assertEqual(context["source_refs"]["guide"]["revision"], "rev-1")

    def test_due_and_project_sheet_wire_shapes_preserve_execution_and_decisions(self):
        decision = {"authority": "owner", "kind": "decision", "id": "decision-1", "revision": "rev-1"}
        evidence = {"authority": "owner", "kind": "wrk.result", "id": "result-1", "revision": "rev-1"}
        current = {"schedule_id": "manager", "role": "manager", "completion_state": "succeeded",
                   "stop_state": "completed", "delivery_state": "returned", "in_flight_request": None,
                   "provider_called": False,  # This read did not invoke a provider.
                   "host_evidence": {"gateway_attempt": {"result": {"outcome": "succeeded", "observed_turn_id": "turn-1"}}},
                   "last_result": {"outcome": "succeeded", "physical_session_id": "session-1", "observed_turn_id": "turn-1"}}
        task = {"ref": TASK, "title": "Completed work", "lifecycle": {"state": "known", "value": "completed"},
                "readiness": {"state": "known", "value": {"status": "completed"}, "stale": False},
                "accepted_current_evidence": {"state": "known", "value": True,
                    "evidence": {"decision_refs": [decision], "result_ref": evidence, "disposition": "accepted"}}}
        result = compose_manager_handoff(project_ref=PROJECT, current_occurrence=current, tasks=[task],
            decisions=[{"subject": TASK, "decisions": [{"ref": decision, "disposition": "accept",
                "candidate_ref": evidence, "assessment_result_ref": evidence}], "waiting": [], "read_only": True}],
            as_of="2026-10-07T00:00:00Z")
        occurrence = result["current_occurrence"]
        self.assertTrue(occurrence["provider_called"])
        self.assertEqual(occurrence["provider_called_scope"], "retained_occurrence_attempt")
        self.assertEqual(occurrence["observed_turn_id"], "turn-1")
        self.assertIsNone(occurrence["result_ref"])
        self.assertEqual(occurrence["result_ref_reason"], "manager_occurrence_has_no_analytical_result_ref")
        self.assertEqual(result["decisions"][0]["ref"], decision)
        self.assertEqual(result["decisions"][0]["task_ref"], TASK)
        self.assertEqual(result["decisions"][0]["status"], "accepted")
        projected = result["tasks"][0]
        self.assertEqual(projected["title"], "Completed work")
        self.assertEqual(projected["state"], "terminal")
        self.assertEqual(projected["readiness"]["status"], "completed")
        self.assertTrue(projected["accepted_current_evidence"]["value"])
        self.assertEqual(projected["accepted_current_evidence"]["evidence"]["decision_refs"], [decision])

    def test_completed_lifecycle_does_not_imply_verified_acceptance_or_execution(self):
        result = compose_manager_handoff(project_ref=PROJECT,
            current_occurrence={"role": "worker", "completion_state": "none", "in_flight_request": "prepared"},
            tasks=[{"ref": TASK, "lifecycle": {"state": "known", "value": "completed"},
                "accepted_current_evidence": {"state": "unknown", "value": None,
                    "reason": "accepted_decision_evidence_not_independently_verified"}}],
            decisions=[{"subject": TASK, "decisions": []}], as_of="2026-10-07T00:00:00Z")
        self.assertFalse(result["current_occurrence"]["provider_called"])
        self.assertEqual(result["decisions"], [])
        self.assertEqual(result["tasks"][0]["accepted_current_evidence"]["state"], "unknown")
        self.assertIsNone(result["tasks"][0]["accepted_current_evidence"]["value"])

    def test_operational_view_exposes_schedule_progress_advice_and_feedback_routes(self):
        advisory_ref = {"authority": "owner", "kind": "wrk.report", "id": "advice-1", "revision": "rev-1"}
        result = compose_manager_handoff(
            project_ref=PROJECT,
            assignment={"ref": ASSIGNMENT, "role": "manager", "principal": "manager", "generation": 2},
            current_occurrence={"schedule_id": "manager-due", "interval_seconds": 3600,
                                "due_at": "2026-10-08T01:00:00Z", "last_completed_at": "2026-10-08T00:00:00Z"},
            effective_context={"state": "known", "assignment_ref": ASSIGNMENT,
                               "selected_project_set": [PROJECT], "next_actor": "manager",
                               "next_action": "inspect", "available_commands": {"status": "read"},
                               "role_instructions": "Read the current state before acting.",
                               "instruction_sha256": "guide-digest"},
            reports=[{"ref": advisory_ref, "value": {"summary": "Worker produced useful progress.",
                                                        "recorded_at": "2026-10-08T00:30:00Z"}}],
            advisory_findings=[{"ref": advisory_ref, "finding": "Continue the bounded repair.",
                                "disposition": "continue", "evidence_refs": [advisory_ref]}],
            as_of="2026-10-08T01:00:00Z",
        )
        self.assertEqual(result["schedule"]["interval_seconds"], 3600)
        self.assertEqual(result["last_useful_progress"]["summary"], "Worker produced useful progress.")
        self.assertEqual(result["advisory"]["disposition"], "continue")
        self.assertEqual(result["advisory"]["findings"][0]["evidence_refs"], [advisory_ref])
        self.assertEqual(result["feedback_routing"]["routes"][0]["recipient"], "manager")
        self.assertEqual(result["point_of_use"]["commands"], {"status": "read"})
        self.assertEqual(result["responsibilities"]["selected_project_set"], [PROJECT])

    def test_service_uses_rich_inbox_task_rows_instead_of_lifecycle_summary(self):
        # These are the two distinct wire rows returned by derive_manager_inbox.
        summary = {"ref": TASK, "lifecycle": "completed", "readiness": {"status": "completed"}}
        row = {"ref": TASK, "title": "Canonical completed task",
               "lifecycle": {"state": "known", "value": "completed"},
               "accepted_current_evidence": {"state": "known", "value": True,
                                             "evidence": {"decision_refs": [ASSIGNMENT]}}}
        portfolio = Mock()
        portfolio.operations._assignment_dict.return_value = {"ref": ASSIGNMENT, "principal": "manager"}
        portfolio.manager_inventory.return_value = {"projects": []}
        portfolio.manager_inbox.return_value = {"tasks": [summary], "task_rows": [row]}
        service = object.__new__(ManagerJourneyService)
        service.server = SimpleNamespace(state={"project_ref": PROJECT, "assignment_ref": ASSIGNMENT, "owner": "owner"},
                                         owner=Mock(), portfolio=portfolio)
        service._effective_context = lambda operation: {}
        service._budget = lambda: {}
        service._as_of = lambda: "2026-10-07T00:00:00Z"
        result = service._handoff(view={}, status={}, operation={}, occurrences=[], help_issues=[])
        self.assertEqual(result["tasks"][0]["title"], "Canonical completed task")
        self.assertTrue(result["tasks"][0]["accepted_current_evidence"]["value"])
        self.assertEqual(result["tasks"][0]["state"], "terminal")


if __name__ == "__main__":
    unittest.main()
