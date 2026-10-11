"""A lost owner capture joins the original admitted turn without native replay."""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_fresh_manager_admission as fixture


class MissingManagerCaptureTests(unittest.TestCase):
    def claimed(self):
        helper = fixture.FreshManagerTests()
        f, root = helper.fixture()
        self.addCleanup(helper.doCleanups)
        outcome = f.app.start(schedule_id='fresh-manager', settle=False)
        self.assertEqual(outcome['outcome'], 'succeeded')
        due = f.port.read_due('fresh-manager')
        attempt = due['host_evidence']['gateway_attempt']
        claim = {k: copy.deepcopy(v) for k, v in attempt.items()
                 if k not in {'result', 'manager_acceptance'}}
        claim['state'] = 'claimed'
        value = {**due, 'stop_state': 'active', 'completion_state': 'none',
                 'delivery_state': 'ready',
                 'in_flight_request': 'fresh-manager', 'last_completed_request': None,
                 'completion_evidence': None, 'completed_at': None,
                 'host_evidence': {**due['host_evidence'], 'gateway_attempt': claim}}
        f.port.save_due('fresh-manager', value, expected_version=due['version'],
                        request_id='fixture-owner-lost-capture')
        f.app.runtime.adapter.trusted_thread_reader = lambda session: {
            'thread': {'id': session, 'path': str(root / 'native.jsonl')}}
        return f, root, claim

    def test_completed_admitted_turn_captured_and_settled_once_without_provider(self):
        f, root, claim = self.claimed()
        before = (root / 'submitted.jsonl').read_bytes()
        due_before = f.port.read_due('fresh-manager')
        preview = f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=fixture.digest(claim), validate_only=True)
        self.assertEqual(preview['outcome'], 'qualified')
        self.assertEqual(f.port.read_due('fresh-manager'), due_before)
        recovered = f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=fixture.digest(claim))
        self.assertFalse(recovered['provider_called'])
        self.assertEqual(recovered['reconciliation']['source_claim'], claim)
        self.assertIsNone(recovered['reconciliation']['original_transport_exit_status'])
        self.assertEqual(f.app.recover(schedule_id='fresh-manager', execute=False)['outcome'], 'succeeded')
        self.assertTrue(f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=fixture.digest(claim))['replayed'])
        self.assertEqual((root / 'submitted.jsonl').read_bytes(), before)

    def test_admitted_abort_is_failed_settlement_and_physical_release_not_success(self):
        from otto.agents.manager_capture_reconciliation import retained_aborted_manager_capture
        from otto.portfolio.execution_host import ExecutionHost
        f, root, claim = self.claimed()
        trace = root / 'native.jsonl'
        rows = [json.loads(v) for v in trace.read_text().splitlines()]
        for row in rows:
            payload = row.get('payload', {})
            if payload.get('type') == 'task_complete' and payload.get('turn_id') == 'work-turn':
                payload.update(type='turn_aborted', reason='interrupted')
        trace.write_text(''.join(json.dumps(v) + '\n' for v in rows))
        before = (root / 'submitted.jsonl').read_bytes()
        key = fixture.digest(claim)
        result = f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=key)
        self.assertEqual(result['reconciliation']['native_terminal_state'], 'aborted')
        recovered = f.app.recover(schedule_id='fresh-manager', execute=False)
        self.assertEqual(recovered['outcome'], 'failed')
        self.assertFalse(recovered['retry'])
        self.assertFalse(recovered['result']['context_digest_verified'])
        self.assertFalse(recovered['command_effects_reconciled'])
        due = f.app._read('fresh-manager')
        self.assertEqual((due.stop_state, due.completion_state, due.in_flight_request),
                         ('completed', 'failed', None))
        self.assertTrue(retained_aborted_manager_capture(due, f.app.actor))
        host = ExecutionHost(directory=root/'ipc', handler=lambda request: None)
        host.restore_execution(f.app, due)
        self.assertNotIn('fresh-manager', host._capacity_holds)
        # A distinct response-driven same-native callback can be prepared;
        # the original aborted occurrence itself is never resumed.
        from otto.portfolio.execution_operations import build_manager_callback_due
        callback = build_manager_callback_due(due, schedule_id='abort-response-callback',
            request_key='abort-response-callback', assignment_ref=due.assignment_ref,
            guide_ref=next(ref for ref in due.context_refs if ref != due.target['mandate_ref']),
            mandate_ref=due.target['mandate_ref'], due_at=due.due_at,
            timeout_seconds=due.timeout_seconds, native_adapter=f.app.native_adapter_identity())
        f.port.save_due(callback.schedule_id, callback.to_dict(), expected_version=0,
                        request_id='fixture-abort-response-callback')
        f.app._verify_native_binding(f.app._current(due.assignment_ref, due.generation),
                                    callback.target['native_id'], callback.schedule_id)
        f.app.runtime.prepare_execution_readiness(due=callback)
        self.assertEqual(callback.target['native_id'], due.last_result['physical_session_id'])
        self.assertNotEqual(callback.schedule_id, due.schedule_id)
        self.assertEqual(f.app.recover(schedule_id='fresh-manager', execute=True)['outcome'], 'replayed')
        changed = due.to_dict()
        changed['host_evidence']['gateway_attempt']['result']['error']['message'] = 'changed'
        self.assertFalse(retained_aborted_manager_capture(changed, f.app.actor))
        self.assertFalse(retained_aborted_manager_capture(due, 'foreign'))
        self.assertEqual((root / 'submitted.jsonl').read_bytes(), before)

    def test_missing_foreign_changed_and_active_evidence_stays_held(self):
        for mode in ('claim_digest', 'missing_terminal', 'active_turn', 'wrong_model',
                     'changed_prompt', 'wrong_session', 'missing_admission', 'changed_assignment', 'abort_overlap'):
            with self.subTest(mode=mode):
                f, root, claim = self.claimed()
                trace = root / 'native.jsonl'; raw = trace.read_text()
                key = fixture.digest(claim)
                if mode == 'claim_digest': key = '0' * 64
                elif mode == 'missing_terminal':
                    trace.write_text('\n'.join(v for v in raw.splitlines()
                        if not ('task_complete' in v and 'work-turn' in v)) + '\n')
                elif mode == 'active_turn':
                    trace.write_text(raw + json.dumps({'type': 'event_msg', 'payload': {
                        'type': 'task_started', 'turn_id': 'foreign-active'}}) + '\n')
                elif mode == 'abort_overlap':
                    altered = raw.replace('task_complete', 'turn_aborted')
                    trace.write_text(altered + json.dumps({'type': 'event_msg', 'payload': {
                        'type': 'task_started', 'turn_id': 'foreign-active'}}) + '\n')
                elif mode == 'wrong_model': trace.write_text(raw.replace('gpt-test', 'wrong-model'))
                elif mode == 'changed_prompt': trace.write_text(raw.replace('Produce actual requested artifact', 'different request'))
                elif mode == 'wrong_session':
                    f.app.runtime.adapter.trusted_thread_reader = lambda session: {
                        'thread': {'id': 'foreign', 'path': str(trace)}}
                elif mode == 'missing_admission':
                    due = f.port.read_due('fresh-manager')
                    altered = copy.deepcopy(due); altered['host_evidence']['gateway_attempt'].pop('delivery_admission')
                    claim = altered['host_evidence']['gateway_attempt']; key = fixture.digest(claim)
                    f.port.save_due('fresh-manager', altered, expected_version=due['version'],
                                    request_id='fixture-missing-admission')
                elif mode == 'changed_assignment':
                    from herzchen.contracts import ResourceRef
                    f.app.assignments.reassign(ResourceRef.from_dict(claim['assignment_ref']),
                        principal='foreign', session=fixture.SESSION, reason='changed custody',
                        expected_generation=1, logical_request_key='fixture-custody-change', actor=f.actor)
                before = f.port.read_due('fresh-manager')
                submitted = (root / 'submitted.jsonl').read_bytes()
                with self.assertRaises(Exception):
                    f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
                        expected_claim_sha256=key)
                self.assertEqual(f.port.read_due('fresh-manager'), before)
                self.assertEqual((root / 'submitted.jsonl').read_bytes(), submitted)

    def test_capture_interruption_after_proof_recovers_same_claim_without_replay(self):
        from otto.agents.owner_runtime import OwnerAuthorizedRoleCapture
        f, root, claim = self.claimed()
        submitted = (root / 'submitted.jsonl').read_bytes()
        key = fixture.digest(claim)
        with patch.object(OwnerAuthorizedRoleCapture, 'record', side_effect=RuntimeError('owner interrupted')):
            with self.assertRaises(RuntimeError):
                f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
                    expected_claim_sha256=key)
        due = f.port.read_due('fresh-manager')
        self.assertEqual(due['host_evidence']['gateway_attempt']['state'], 'claimed')
        self.assertNotIn('result', due['host_evidence']['gateway_attempt'])
        recovered = f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=key)
        self.assertEqual(recovered['outcome'], 'reconciled')
        self.assertEqual(f.app.recover(schedule_id='fresh-manager', execute=False)['outcome'], 'succeeded')
        self.assertEqual((root / 'submitted.jsonl').read_bytes(), submitted)


if __name__ == '__main__': unittest.main()
