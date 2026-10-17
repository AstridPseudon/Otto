import unittest
from types import SimpleNamespace
from pathlib import Path
import tempfile
import hashlib
import json

from herzchen.contracts import AuthenticatedActor
from herzchen.kernel import Store
from herzchen.kernel.operations import OperationState, UnknownOutcomeError
from otto.agents.effect_ledger import NativeEffectLedger
from otto.agents.gateway import Responsibility

from otto.agents.owner_runtime import CanonicalRoleRuntime, OwnerAuthorizedRoleCapture, OwnerRoleRuntimeError


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
    def test_fresh_manager_replay_finishes_held_effect_after_capture_crash(self):
        source = {"logical_request_key": "turn-1", "operation": "invoke", "outcome": "unknown",
                  "assignment_ref": ASSIGNMENT, "generation": 1}
        digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        result = {"logical_request_key": "turn-1", "operation": "invoke", "outcome": "succeeded",
                  "delivery_state": "done", "assignment_ref": ASSIGNMENT, "generation": 1,
                  "project_ref": {"id": "project-1"}, "task_ref": {"id": "task-1"},
                  "physical_session_id": "session-1", "observed_turn_id": "turn-native",
                  "task_bound_evidence": {"verified": True}}
        proof = {"schema": "otto.owner-native-admission-reconciliation.v1",
                 "resolver": "owner-principal", "effect": "retained_completed_native_turn_no_provider_replay",
                 "source_unknown": source, "source_unknown_sha256": digest(source),
                 "native_turn_started": True, "trace_sha256": "b" * 64,
                 "physical_session_id": "session-1", "observed_turn_id": "turn-native",
                 "task_bound_evidence_sha256": digest(result["task_bound_evidence"])}
        reconciliation = {"schema": "otto.owner-result-reconciliation.v1", "resolver": "owner-principal",
                          "effect": "retained_evidence_reparsed_no_provider_replay",
                          "source_unknown_sha256": digest(source), "trace_sha256": "b" * 64}
        due = {"role": "manager", "execution_mode": "fresh_manager", "generation": 1,
               "target": {"mandate_ref": {"id": "mandate-1"}, "principal": "manager"},
               "host_evidence": {"gateway_attempt": {"state": "result", "logical_request_key": "turn-1",
                   "result": result, "delivery_admission_reconciliation": proof,
                   "reconciliation": reconciliation}}}
        checks, settlements = [], []
        capture = SimpleNamespace(completed_scope_validator=lambda: None, settled_publication=False,
            validate_completed_manager_result=lambda value: checks.append(value))
        current_assignment = {"ref": ASSIGNMENT, "assignment_ref": ASSIGNMENT,
            "role": "manager", "principal": "manager", "generation": 1,
            "assignment_pin_content_matches": True}
        ledger = SimpleNamespace(get=lambda key: SimpleNamespace(state=OperationState.UNKNOWN),
            settle_verified=lambda key, value: settlements.append((key, value)))
        runtime = object.__new__(CanonicalRoleRuntime)
        runtime.actor = "owner-principal"
        runtime.due_port = SimpleNamespace(read_due=lambda schedule: due)
        runtime.effect_ledger = ledger
        runtime._binding = lambda **kwargs: (current_assignment, None, capture)
        current_assignment.update(ref={**ASSIGNMENT, "revision": "rev-3"},
            assignment_ref={**ASSIGNMENT, "revision": "rev-3"}, generation=2,
            assignment_pin_content_matches=False)
        with self.assertRaisesRegex(OwnerRoleRuntimeError, "assignment"):
            runtime.reconcile_fresh_manager_result(schedule_id="schedule-1",
                expected_unknown_sha256=digest(source))
        self.assertEqual(settlements, [])
        current_assignment.update(ref=ASSIGNMENT, assignment_ref=ASSIGNMENT,
            generation=1, assignment_pin_content_matches=True)
        replay = runtime.reconcile_fresh_manager_result(schedule_id="schedule-1",
            expected_unknown_sha256=digest(source))
        self.assertTrue(replay["replayed"])
        self.assertEqual(checks, [result])
        self.assertEqual(settlements, [("turn-1", result)])

    def test_native_start_claim_survives_reconstruction_and_unknown_stays_held(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "effect.sqlite"
            store = Store.create(path, authority="owner")
            actor = AuthenticatedActor("owner", "owner-principal", "credential")
            ledger = NativeEffectLedger(store, actor)
            responsibility = Responsibility(owner="owner-principal", logical_agent_id="worker-1",
                operation="resume", packet_digest="a" * 64, physical_session_id="session-1",
                logical_request_key="turn-1", project_ref={"authority": "owner", "kind": "wrk.project", "id": "p-1"},
                task_ref={"authority": "owner", "kind": "wrk.task", "id": "t-1"},
                assignment_ref=ASSIGNMENT, generation=1)
            started = ledger.begin(responsibility, "f" * 64)
            self.assertEqual(started.state, OperationState.STARTED)
            store.close()
            store = Store.open(path, authority="owner")
            try:
                recovered = NativeEffectLedger(store, actor)
                self.assertEqual(recovered.get("turn-1").state, OperationState.UNKNOWN)
                with self.assertRaises(UnknownOutcomeError):
                    recovered.begin(responsibility, "f" * 64)
                self.assertEqual(recovered.get("turn-1").state, OperationState.UNKNOWN)
            finally:
                store.close()

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

class SettledPublicationFenceTests(unittest.TestCase):
    def fixture(self):
        import hashlib,json
        r=FixtureCapture.result('succeeded')
        r.update(observed_model='gpt-test',observed_reasoning='high',context_digest_verified=True)
        accepted={'accepted':True,'owner':'owner-principal','logical_request_key':'request-1','result_digest':hashlib.sha256(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        return SimpleNamespace(stop_state='completed',completion_state='succeeded',in_flight_request=None,assignment_ref=ASSIGNMENT,generation=1,requested_model='gpt-test',requested_reasoning='high',host_evidence={'gateway_attempt':{'state':'result','logical_request_key':'request-1','result':r,'manager_acceptance':accepted}})
    def test_completed_exact_accepted_result_is_publication_only(self):
        from otto.agents.owner_runtime import CanonicalRoleRuntime
        due=self.fixture(); self.assertTrue(CanonicalRoleRuntime._settled_publication_matches(due,'request-1','owner-principal'))
        capture=FixtureCapture();capture.project_ref={'id':'project-1'};capture.expected_target={};capture._same=lambda a,b:a==b;capture._scope_error=lambda *_:'not actively admitted';capture.settled_publication=True
        due.target={};due.project_ref='project-1';due.lifecycle_owner=due.manager_ref='owner-principal'
        self.assertIsNone(capture._publication_scope_error(due,ASSIGNMENT,1,'request-1'))
        self.assertEqual(capture._scope_error(due,ASSIGNMENT,1,'request-1'),'not actively admitted')
        due.generation=2;self.assertIsNotNone(capture._publication_scope_error(due,ASSIGNMENT,1,'request-1'))
    def test_unknown_foreign_changed_and_unsettled_results_reject(self):
        from otto.agents.owner_runtime import CanonicalRoleRuntime
        for field,value in [('stop_state','active'),('completion_state','unknown'),('in_flight_request','other'),('generation',2),('assignment_ref',dict(ASSIGNMENT,revision='rev-3')),('requested_model','foreign')]:
            with self.subTest(field=field):
                due=self.fixture();setattr(due,field,value);self.assertFalse(CanonicalRoleRuntime._settled_publication_matches(due,'request-1','owner-principal'))
        for section,field,value in [('result','outcome','unknown'),('result','context_digest_verified',False),('result','physical_session_id','changed'),('manager_acceptance','owner','foreign'),('manager_acceptance','accepted',False),('manager_acceptance','result_digest','foreign')]:
            with self.subTest(section=section,field=field):
                due=self.fixture();due.host_evidence['gateway_attempt'][section][field]=value;self.assertFalse(CanonicalRoleRuntime._settled_publication_matches(due,'request-1','owner-principal'))

class ManagerResultCapabilityTests(unittest.TestCase):
    def fixture(self,role='manager',**overrides):
        from herzchen.contracts import ResourceRef
        from unittest.mock import Mock
        self.project=ResourceRef('owner','work.project','p','rev-1');self.task=ResourceRef('owner','work.task','t','rev-1');self.assignment=ResourceRef.from_dict(ASSIGNMENT);self.actor=SimpleNamespace(authority='owner')
        self.current=SimpleNamespace(ref=self.assignment,scope=self.project,generation=1,role=role)
        self.assignments=Mock();self.assignments.get.return_value=self.current
        return dict(assignments=self.assignments,reader=Mock(),scope_reader=Mock(),actor=self.actor,project_ref=self.project.to_dict(),task_ref=self.task.to_dict(),assignment_ref=ASSIGNMENT,generation=1,logical_request_key='request-1',**overrides)
    def test_project_manager_requires_explicit_owner_capability(self):
        from unittest.mock import patch
        from otto.portfolio.owner_bootstrap import _BoundResultAccess
        args=self.fixture()
        with patch('otto.portfolio.owner_bootstrap._read_current_result_task') as membership:
            with self.assertRaises(PermissionError):_BoundResultAccess(**args)
            access=_BoundResultAccess(**args,allow_project_manager=True)
            value=dict(project_ref=self.project.to_dict(),task_ref=self.task.to_dict(),assignment_ref=ASSIGNMENT,generation=1,logical_request_key='request-1')
            access.append_result(ASSIGNMENT,value,expected_generation=1,logical_request_key='request-1',actor=self.actor)
            self.assignments.append_result.assert_called_once()
            with self.assertRaises(PermissionError):access.append_result(ASSIGNMENT,dict(value,task_ref=dict(self.task.to_dict(),id='sibling')),expected_generation=1,logical_request_key='request-1',actor=self.actor)
            with self.assertRaises(PermissionError):access.append_result(ASSIGNMENT,value,expected_generation=1,logical_request_key='foreign',actor=self.actor)
            membership.assert_called()
    def test_advisor_foreign_revision_generation_and_membership_stay_rejected(self):
        from unittest.mock import patch
        from herzchen.contracts import ResourceRef
        from otto.portfolio.owner_bootstrap import _BoundResultAccess
        for field,value in [('role','project_advisor'),('scope',ResourceRef('owner','work.project','foreign','rev-1')),('generation',2),('ref',ResourceRef('owner','wrk.assignment','a-1','rev-3'))]:
            with self.subTest(field=field),patch('otto.portfolio.owner_bootstrap._read_current_result_task'):
                args=self.fixture();setattr(self.current,field,value)
                with self.assertRaises(PermissionError):_BoundResultAccess(**args,allow_project_manager=True)
        with patch('otto.portfolio.owner_bootstrap._read_current_result_task',side_effect=PermissionError('changed membership')):
            with self.assertRaises(PermissionError):_BoundResultAccess(**self.fixture(),allow_project_manager=True)
