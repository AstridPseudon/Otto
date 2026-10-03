import unittest
from types import SimpleNamespace

from otto.agents.owner_runtime import OwnerAuthorizedRoleCapture, OwnerRoleRuntimeError


ASSIGNMENT = {"authority": "owner", "kind": "wrk.assignment", "id": "a-1", "revision": "rev-2"}
AUTHORIZATION = {"status": "authorized", "physical_session_id": "session-1"}


class FixtureCapture(OwnerAuthorizedRoleCapture):
    def __init__(self):
        self.lifecycle_owner = "owner-principal"
        self.assignment_ref = ASSIGNMENT
        self.generation = 1
        self.record = SimpleNamespace(version=4, requested_model="gpt-test", requested_reasoning="high")
        prior = self.result("unknown")
        self.attempt = {
            "state": "result", "logical_request_key": "request-1",
            "delivery_authorization": AUTHORIZATION, "result": prior,
        }

    @staticmethod
    def result(outcome):
        raw = {
            "initialization_receipt": {"status": "ready"},
            "initialization_envelope": {"stdout": "READY"},
            "owner_delivery_authorization": AUTHORIZATION,
            "work_envelope": {
                "command": ["codex", "resume"], "stdout": "retained bytes",
                "stderr": "", "exit_status": 0, "started_at": "start", "ended_at": "end",
                "physical_session_id": "session-1", "process_id": "42",
                "input_packet_digest": "a" * 64,
            },
        }
        value = {
            "logical_request_key": "request-1", "owner": "worker-1",
            "project_ref": {"id": "project-1"}, "task_ref": {"id": "task-1"},
            "assignment_ref": ASSIGNMENT, "generation": 1, "operation": "invoke",
            "requested_profile": "workspace-write", "requested_model": "gpt-test",
            "requested_reasoning": "high", "logical_agent_id": "worker-1",
            "physical_session_id": "session-1", "native_session_id": "session-1",
            "request_fingerprint": "f" * 64, "raw_result": raw,
            "outcome": outcome, "delivery_state": "unknown" if outcome == "unknown" else "done",
        }
        if outcome == "succeeded":
            value.update({
                "context_digest_verified": True, "observed_model": "gpt-test",
                "observed_reasoning": "high",
                "task_bound_evidence": {
                    "assignment_ref": ASSIGNMENT, "generation": 1,
                    "session_id": "session-1", "owner_delivery_authorization": AUTHORIZATION,
                },
            })
        return value

    def _record(self):
        return self.record

    def _attempt(self, _record):
        return self.attempt

    def _save(self, _record, attempt, _request_id):
        self.attempt = attempt
        return {"version": 5}


class OwnerResultReconciliationTests(unittest.TestCase):
    def test_exact_retained_success_reconciles_without_provider_retry(self):
        capture = FixtureCapture()
        result = capture.reconcile_unknown_result(
            "request-1", capture.result("succeeded"), resolver="owner-principal",
            trace_sha256="b" * 64, parser_revision="host-parser-test-v1",
        )
        self.assertEqual(result["outcome"], "reconciled")
        self.assertEqual(capture.attempt["result"]["outcome"], "succeeded")
        self.assertEqual(
            capture.attempt["reconciliation"]["effect"],
            "retained_evidence_reparsed_no_provider_replay",
        )
        accepted = capture.accept_result("request-1", manager_actor="owner-principal")
        self.assertTrue(accepted["accepted"])
        replayed = capture.reconcile_unknown_result(
            "request-1", capture.result("succeeded"), resolver="owner-principal",
            trace_sha256="b" * 64, parser_revision="host-parser-test-v1",
        )
        self.assertTrue(replayed["replayed"])

    def test_changed_retained_stdout_is_rejected(self):
        capture = FixtureCapture()
        replacement = capture.result("succeeded")
        replacement["raw_result"]["work_envelope"]["stdout"] = "changed"
        with self.assertRaises(OwnerRoleRuntimeError):
            capture.reconcile_unknown_result(
                "request-1", replacement, resolver="owner-principal",
                trace_sha256="b" * 64, parser_revision="host-parser-test-v1",
            )

    def test_foreign_resolver_is_rejected(self):
        capture = FixtureCapture()
        with self.assertRaises(OwnerRoleRuntimeError):
            capture.reconcile_unknown_result(
                "request-1", capture.result("succeeded"), resolver="other",
                trace_sha256="b" * 64, parser_revision="host-parser-test-v1",
            )


if __name__ == "__main__":
    unittest.main()
