import unittest

from otto.portfolio import (
    AdvisorContextError,
    ROLE_OPERATING_CONTRACTS,
    build_advisor_context,
    choose_advisor_direction,
    establish_pairing,
)


def ref(kind, ident, revision="rev-1", authority="owner"):
    return {"authority": authority, "kind": kind, "id": ident, "revision": revision}


PROJECT = ref("work.project", "project-1")
MANAGER = ref("wrk.assignment", "manager-a", "rev-4")
ADVISOR = ref("wrk.assignment", "advisor-a", "rev-7")


def assignment(role, assignment_ref, principal, generation, *, manager=None):
    return {
        "ref": assignment_ref,
        "scope": PROJECT,
        "role": role,
        "principal": principal,
        "stored_manager": manager,
        "generation": generation,
        "status": "active",
    }


class AdvisorContextTests(unittest.TestCase):
    def setUp(self):
        self.pairing = establish_pairing(
            PROJECT,
            [
                assignment("manager", MANAGER, "manager-principal", 3, manager="manager-principal"),
                assignment("project_advisor", ADVISOR, "advisor-principal", 5, manager="manager-principal"),
            ],
            manager_conversation_ref={"host": "codex", "physical_session_id": "manager-session"},
            advisor_conversation_ref={"host": "codex", "physical_session_id": "advisor-session"},
        )
        self.context = build_advisor_context(
            self.pairing,
            goal="Ship the smallest useful delivery",
            acceptance_criteria=["C03", "C04"],
            mandate={"scope": "project-1", "authority": "in-mandate"},
            document_refs=[ref("dat.content.document", "plan")],
            last_inspected={"message_id": "m-4", "observed_at": "2026-10-03T15:00:00Z"},
            open_decisions=[{"id": "decision-1", "question": "which path?"}],
            question="Is this check still necessary?",
        )

    def test_context_is_compact_but_points_to_actual_sources(self):
        self.assertEqual(self.context["schema"], "otto.project-advisor-context.v1")
        self.assertEqual(self.context["pairing"]["advisor_generation"], 5)
        self.assertEqual(self.context["references"]["documents"][0]["id"], "plan")
        self.assertEqual(self.context["last_inspected"]["message_id"], "m-4")
        self.assertTrue(self.context["inspection"]["read_actual_messages"])
        self.assertEqual(self.context["inspection"]["missing_delta_fallback"], "bounded_direct_read")

    def test_operating_contract_preserves_low_noise_supervision_boundary(self):
        contract = ROLE_OPERATING_CONTRACTS["project_advisor"]
        for requirement in (
            "stay quiet when progress is healthy or unchanged",
            "evidence-backed",
            "requirement provenance",
            "Escalate only owner-only, cross-project, authority-gap, or uncertain effects",
        ):
            self.assertIn(requirement, contract)

    def test_healthy_check_is_quiet(self):
        result = choose_advisor_direction(
            context=self.context,
            observation={"evidence": [{"message_id": "m-5"}], "summary": "accepted work is progressing"},
            disposition="continue",
        )
        self.assertFalse(result["notify_manager"])
        self.assertIsNone(result["message"])
        self.assertIsNone(result["selected_action"])

    def test_correction_makes_provenance_and_shortest_path_executable(self):
        result = choose_advisor_direction(
            context=self.context,
            observation={
                "evidence": [{"report_ref": ref("wrk.report", "report-1")}],
                "implication": "The extra packet gate blocks the accepted route but proves no product invariant.",
                "shortest_path": "Reuse the existing result and run the focused transition test.",
                "selected_action": "Remove the extra gate and run the transition test.",
                "responsible": "manager-a",
                "required_proof": "Focused transition test and resulting artifact",
                "preserved_constraints": ["Keep owner acceptance and unknown-effect protection"],
                "dropped_or_reused": ["Drop the agent-added packet gate"],
                "revisit_condition": "Return if the transition test exposes a real invariant failure",
                "requirement_provenance": {
                    "source": "self_imposed",
                    "requirement": "extra packet gate",
                    "harm_if_removed": "none shown beyond the already-covered transition test",
                },
            },
            disposition="correct",
        )
        self.assertEqual(result["requirement_provenance"]["source"], "self_imposed")
        self.assertEqual(result["responsible"], "manager-a")
        self.assertTrue(result["dropped_or_reused"])

    def test_owner_only_uncertainty_cannot_be_disguised_as_correction(self):
        with self.assertRaisesRegex(AdvisorContextError, "must be escalated"):
            choose_advisor_direction(
                context=self.context,
                observation={"evidence": [{"reason": "owner decision missing"}], "authority": "owner_only"},
                disposition="correct",
            )

    def test_mistaken_advice_requires_a_revision_reason(self):
        with self.assertRaisesRegex(AdvisorContextError, "revision_reason"):
            choose_advisor_direction(
                context=self.context,
                observation={"evidence": [{"message_id": "m-6"}], "summary": "new evidence"},
                disposition="continue",
                previous_advice={"status": "contradicted", "selected_action": "old action"},
            )


if __name__ == "__main__":
    unittest.main()
