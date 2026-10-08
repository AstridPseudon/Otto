import unittest

from otto.portfolio.manager_handoff import compose_manager_handoff


PROJECT = {"authority": "owner", "kind": "work.project", "id": "project-1", "revision": "rev-2"}
ASSIGNMENT = {"authority": "owner", "kind": "wrk.assignment", "id": "assignment-1", "revision": "rev-3"}


class D06ConnectedHandoffTests(unittest.TestCase):
    def test_handoff_joins_setup_readback_without_embedding_role_instructions(self):
        setup = {
            "outcome": "read",
            "state": "active",
            "ready": True,
            "autonomous_ready": False,
            "execution_observed": True,
            "dispatch": False,
            "setup_ref": {"authority": "owner", "kind": "dat.content.document", "id": "setup", "revision": "rev-1"},
            "roles": {
                "manager": {
                    "schedule_id": "manager-hourly",
                    "principal": "manager-a",
                    "assignment_ref": ASSIGNMENT,
                    "generation": 2,
                    "conversation_ref": {"host": "local", "native_id": "manager-session"},
                    "execution": {"model": "codex", "reasoning": "high"},
                    "introduction": {"role_instructions": "x" * 100000},
                },
            },
            "help": {"operational": {"state": "host_only"}, "advice": {"state": "disabled"}},
            "advisor_policy": {"mode": "disabled", "reason": "host-supervised"},
        }
        result = compose_manager_handoff(
            project_ref=PROJECT,
            assignment={"ref": ASSIGNMENT, "principal": "manager-a", "generation": 2},
            operating_setup=setup,
            as_of="2026-10-08T12:00:00Z",
        )

        projection = result["operating_setup"]
        self.assertEqual(projection["state"], "active")
        self.assertTrue(projection["ready"])
        self.assertEqual(projection["setup_ref"], setup["setup_ref"])
        self.assertEqual(projection["roles"]["manager"]["schedule_id"], "manager-hourly")
        self.assertNotIn("introduction", projection["roles"]["manager"])
        self.assertEqual(result["sources"]["operating_setup"]["ref"], setup["setup_ref"])
        self.assertEqual(result["authority"], {"read_only": True, "dispatch": False,
                                                "owner_write": False, "suggestions_are_authority": False})


if __name__ == "__main__":
    unittest.main()
