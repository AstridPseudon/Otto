"""Focused D05 replacement proofs over disposable assignment projections."""

import unittest

from otto.portfolio.manager_continuity import ManagerContinuity


PROJECT = {"authority": "owner", "kind": "work.project", "id": "project-1", "revision": "rev-3"}
ASSIGNMENT = {"authority": "owner", "kind": "wrk.assignment", "id": "assignment-1", "revision": "rev-1"}


class AssignmentPort:
    def __init__(self):
        self.current = {
            "ref": ASSIGNMENT,
            "scope": PROJECT,
            "role": "manager",
            "principal": "old-manager",
            "session": "old-session",
            "generation": 1,
            "status": "queued",
            "pins": [{"id": "adopted-guide", "revision": "rev-2"}],
            "history": [{"generation": 1, "principal": "old-manager", "session": "old-session"}],
        }
        self.calls = []

    def read(self, _ref):
        return self.current

    def reassign(self, ref, **kwargs):
        self.calls.append((ref, kwargs))
        self.current = {
            **self.current,
            "ref": {**ASSIGNMENT, "revision": "rev-2"},
            "principal": kwargs["principal"],
            "session": kwargs["session"],
            "generation": 2,
            "status": "reassigned",
            "history": [*self.current["history"], {"generation": 2,
                "principal": kwargs["principal"], "session": kwargs["session"]}],
        }
        return self.current


class ManagerContinuityTests(unittest.TestCase):
    def setUp(self):
        self.port = AssignmentPort()
        self.continuity = ManagerContinuity(
            assignment_reader=self.port.read, assignments_port=self.port,
        )

    def test_replacement_reconciles_old_custody_delivers_current_context_and_restarts(self):
        events = []

        def reconcile(assignment, session):
            events.append(("reconcile", assignment["generation"], session))
            return {"resolved": True, "provider_called": False}

        def close(assignment, session):
            events.append(("close", assignment["generation"], session))
            return {"state": "closed"}

        def context(assignment, generation, session):
            events.append(("context", generation, session))
            return {"assignment_ref": assignment["ref"], "generation": generation,
                    "role_defaults": {"model": "gpt-test", "reasoning": "xhigh"},
                    "conversation": session}

        result = self.continuity.replace_session(
            PROJECT, principal="new-manager", request_key="replace-1",
            assignment_ref=ASSIGNMENT, expected_generation=1,
            native_identity="new-session", reconcile=reconcile, close=close,
            context_builder=context, readiness=lambda *_: {"ready": True},
            restart=lambda *_: {"outcome": "restarted", "provider_called": False},
        )

        self.assertEqual(result["outcome"], "replaced", result)
        self.assertEqual(result["generation"], 2)
        self.assertEqual(result["current_context"]["conversation"], "new-session")
        self.assertEqual(result["restart"]["outcome"], "restarted")
        self.assertEqual([item[0] for item in events], ["reconcile", "close", "context"])
        self.assertEqual(self.port.current["session"], "new-session")
        self.assertEqual(self.port.current["history"][0]["session"], "old-session")

    def test_stale_generation_and_unresolved_custody_do_not_reassign(self):
        held = self.continuity.replace_session(
            PROJECT, principal="new-manager", request_key="replace-held",
            assignment_ref=ASSIGNMENT, expected_generation=1,
            native_identity="new-session", custody={"state": "unknown"},
            context_builder=lambda *_: {"generation": 2},
        )
        self.assertEqual(held["outcome"], "blocked")
        self.assertEqual(self.port.calls, [])

        stale = self.continuity.replace_session(
            PROJECT, principal="new-manager", request_key="replace-stale",
            assignment_ref=ASSIGNMENT, expected_generation=2,
            native_identity="new-session", custody={"resolved": True},
            context_builder=lambda *_: {"generation": 2},
        )
        self.assertEqual(stale["outcome"], "stale")
        self.assertEqual(self.port.calls, [])

    def test_context_failure_keeps_replacement_recoverable_and_old_session_fenced(self):
        result = self.continuity.replace_session(
            PROJECT, principal="new-manager", request_key="replace-context-fail",
            assignment_ref=ASSIGNMENT, expected_generation=1,
            native_identity="new-session", custody={"resolved": True},
            context_builder=lambda *_: (_ for _ in ()).throw(RuntimeError("brief race")),
        )
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["status"], "recoverable")
        self.assertEqual(result["generation"], 2)
        self.assertEqual(result["recovery"]["generation"], 2)

        stale = self.continuity.replace_session(
            PROJECT, principal="old-manager", request_key="old-session-retry",
            assignment_ref=ASSIGNMENT, expected_generation=1,
            native_identity="old-session", custody={"resolved": True},
            context_builder=lambda *_: {"generation": 2},
        )
        self.assertEqual(stale["outcome"], "stale")
        self.assertIn(stale["error"]["code"], {"assignment_ref_stale", "stale_generation"})


if __name__ == "__main__":
    unittest.main()
