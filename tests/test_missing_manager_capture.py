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

    def test_missing_foreign_changed_and_active_evidence_stays_held(self):
        for mode in ('claim_digest', 'missing_terminal', 'active_turn', 'wrong_model',
                     'changed_prompt', 'wrong_session', 'missing_admission', 'changed_assignment'):
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
