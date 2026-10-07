import unittest

from otto.portfolio.manager_handoff import compose_manager_handoff


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


if __name__ == "__main__":
    unittest.main()
