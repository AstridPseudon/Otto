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

    def test_completed_manager_scope_keeps_assignment_and_admission_fences(self):
        capture = FixtureCapture()
        capture.completed_scope_validator = lambda: "canonical assignment changed after instruction preparation"
        with self.assertRaisesRegex(OwnerRoleRuntimeError, "canonical assignment changed"):
            capture.verify_completed_delivery("request-1", "session-1", "a" * 64, AUTHORIZATION)
        capture.completed_scope_validator = lambda: None
        capture._scope_error = lambda *args: None
        capture.attempt["physical_session_id"] = "session-1"
        capture.attempt["delivery_authorization"] = {**AUTHORIZATION, "brief_sha256": "a" * 64}
        capture.attempt["delivery_admission"] = {"native_turn_started": True, "physical_session_id": "different-session"}
        with self.assertRaisesRegex(OwnerRoleRuntimeError, "exact admitted native claim"):
            capture.verify_completed_delivery("request-1", "session-1", "a" * 64, capture.attempt["delivery_authorization"])
        capture.attempt["delivery_admission"]["physical_session_id"] = "session-1"
        self.assertEqual(capture.verify_completed_delivery("request-1", "session-1", "a" * 64,
            capture.attempt["delivery_authorization"]), capture.attempt["delivery_authorization"])
        capture.attempt["delivery_authorization"] = {**capture.attempt["delivery_authorization"], "brief_sha256": "b" * 64}
        with self.assertRaisesRegex(OwnerRoleRuntimeError, "exact admitted native claim"):
            capture.verify_completed_delivery("request-1", "session-1", "a" * 64, capture.attempt["delivery_authorization"])

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

class ExplicitManagerPublicationTests(unittest.TestCase):
    def request(self):
        return dict(role='manager',project_ref={'id':'p'},task_ref={'id':'t'},assignment_ref=ASSIGNMENT,mandate_ref={'id':'m'},schedule_id='d',logical_request_key='request-1',expected_generation=1,lifecycle='active',as_of='2026-10-10T00:00:00Z')
    def test_invalid_publication_role_or_flag_rejects_before_binding(self):
        from unittest.mock import Mock
        from otto.agents.owner_runtime import CanonicalRoleRuntime
        runtime=SimpleNamespace(_binding=Mock(side_effect=AssertionError('unauthorized binding effect')))
        for role,flag in [('project_advisor',True),('manager',1),('worker','yes')]:
            with self.subTest(role=role,flag=flag),self.assertRaises(OwnerRoleRuntimeError):
                CanonicalRoleRuntime.accept_role_result(runtime,**{**self.request(),'role':role,'publish_result':flag})
        runtime._binding.assert_not_called()
    def test_explicit_publication_does_not_bypass_current_scope_authority(self):
        from unittest.mock import Mock
        from otto.agents.owner_runtime import CanonicalRoleRuntime
        runtime=SimpleNamespace(_binding=Mock(side_effect=PermissionError('foreign/current generation rejected')))
        with self.assertRaises(PermissionError):CanonicalRoleRuntime.accept_role_result(runtime,**self.request(),publish_result=True)
        runtime._binding.assert_called_once()
    def test_unknown_or_changed_retained_result_cannot_publish(self):
        from unittest.mock import Mock
        capture=FixtureCapture();capture._scope_error=lambda *_:None
        owner=SimpleNamespace(record=Mock())
        for result in [capture.result('unknown'),capture.result('succeeded')]:
            with self.assertRaises(OwnerRoleRuntimeError):capture.publish_analytical_result(result,owner)
        owner.record.assert_not_called()
