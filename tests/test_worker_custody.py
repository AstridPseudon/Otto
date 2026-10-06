"""Canonical owner custody retirement with provider execution forbidden."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.execution import _digest
from otto.portfolio.execution_operations import OccurrencePreparationError
from otto.portfolio.worker_custody import CAPACITY, permits_fresh_worker
from tests import test_execution_application as fixtures


def jsonl(items):
    return ''.join(json.dumps(item) + '\n' for item in items)


class WorkerCustodyTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ExecutionApplicationTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        admitted = f.app.assign_worker(**f.request())
        self.schedule = admitted['schedule_id']
        due = f.app._resources(f.app._read(self.schedule))
        session, initial_turn, work_turn = 'capacity-session', 'ready-turn', 'capacity-turn'
        auth = {'status': 'authorized', 'logical_request_key': due.in_flight_request,
            'physical_session_id': session, 'project_ref': due.target['project_ref'],
            'task_ref': due.target['task_ref'], 'assignment_ref': due.assignment_ref,
            'generation': due.generation, 'role': 'worker', 'principal': due.recipient,
            'lifecycle_owner': f.app.actor}
        def envelope(operation, success, process, turn, events):
            receipt = {'identity': {'logical_agent_id': due.recipient, 'physical_session_id': session},
                'operation': operation, 'outcome': 'succeeded' if success else 'failed',
                'process_id': process, 'result_ref': None,
                'unsupported_reason': None if success else 'codex_execution_failed'}
            candidate = {'status': 'unsupported', 'task_bound': False, 'retry_allowed': False,
                         'native_records': []}
            return receipt, {'fnd_receipt': receipt, 'physical_session_id': session,
                'logical_agent_id': due.recipient, 'owner': due.recipient,
                'transport_operation': operation, 'status': receipt['outcome'],
                'exit_status': 0 if success else 1, 'runner': 'codex-cli', 'stderr': '',
                'stdout': jsonl(events), 'result_ref': None, 'timeout': None, 'cancel': None,
                'process_id': process, 'started_at': '2026-10-06T12:00:00Z' if success else '2026-10-06T12:00:02Z',
                'ended_at': '2026-10-06T12:00:01Z' if success else '2026-10-06T12:00:03Z',
                'host_evidence': {'session_id': session, 'process_started': True,
                    'session_created': success, 'invocation_turn_verified': True,
                    'provenance': 'host_native_jsonl', 'turn_id': turn, 'native_candidate': candidate}}
        common = [{'type': 'thread.started', 'thread_id': session}, {'type': 'turn.started'}]
        ir, ie = envelope('invoke', True, '100', initial_turn, common + [
            {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'agent_message', 'text': 'READY'}},
            {'type': 'turn.completed', 'usage': {}}])
        wr, we = envelope('resume', False, '101', work_turn, common + [
            {'type': 'error', 'message': CAPACITY}, {'type': 'turn.failed', 'error': {'message': CAPACITY}}])
        result = {'assignment_ref': due.assignment_ref, 'generation': due.generation,
            'logical_request_key': due.in_flight_request, 'outcome': 'unknown', 'delivery_state': 'unknown',
            'requested_model': due.requested_model, 'requested_reasoning': due.requested_reasoning,
            'requested_profile': due.profile, 'native_session_id': session,
            'context_digest_verified': False, 'error': {'code': 'authorized_result_unverified'},
            'logical_agent_id': due.recipient, 'project_ref': due.target['project_ref'],
            'task_ref': due.target['task_ref'], 'operation': 'invoke', 'physical_session_id': session,
            'observed_turn_id': work_turn, 'raw_result': {'transport_operation': 'resume',
                'worker_content': [], 'task_bound_evidence': None, 'owner_delivery_authorization': auth,
                'initialization_receipt': ir, 'initialization_envelope': ie,
                'work_receipt': wr, 'work_envelope': we, 'native_candidate': we['host_evidence']['native_candidate']}}
        attempt = {'state': 'result', 'physical_session_id': session, 'assignment_ref': due.assignment_ref,
            'generation': due.generation, 'logical_request_key': due.in_flight_request,
            'delivery_authorization': auth, 'result': result}
        f.port.save_due(self.schedule, replace(due, host_evidence={**(due.host_evidence or {}), 'gateway_attempt': attempt}).to_dict(),
            request_id='fixture-capacity', expected_version=due.version)
        self.trace = Path(f.temporary.name) / 'trace.jsonl'
        self.trace.write_text(jsonl([
            {'type': 'session_meta', 'payload': {'id': session}},
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': initial_turn}},
            {'type': 'event_msg', 'payload': {'type': 'item_completed', 'turn_id': initial_turn,
                'thread_id': session, 'item': {'type': 'AgentMessage', 'content': [{'type': 'Text', 'text': 'READY'}]}}},
            {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': initial_turn, 'last_agent_message': 'READY'}},
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': work_turn}},
            {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': work_turn,
                'last_agent_message': None, 'error': {'message': CAPACITY, 'codex_error_info': 'server_overloaded'}}}]))
        f.app.runtime.adapter.trusted_thread_reader = lambda selected: {'thread': {'id': selected, 'path': str(self.trace)}}
        self.before = f.port.read_due(self.schedule)

    def release(self, **changes):
        scope = self.f.app.inspect_capacity_failed_worker(schedule_id=self.schedule)
        request = {'schedule_id': self.schedule, 'request_key': 'release-capacity-v1',
            'fresh_request_key': 'new-worker-v1', 'expected_due_sha256': scope['due_sha256'],
            'expected_unknown_result_sha256': scope['unknown_result_sha256']}
        request.update(changes)
        return self.f.app.release_capacity_failed_worker(**request)

    def mutate_attempt(self, mutate):
        f = self.f; due = f.app._read(self.schedule)
        host = deepcopy(due.host_evidence); mutate(host['gateway_attempt'])
        f.port.save_due(self.schedule, replace(due, host_evidence=host).to_dict(),
            request_id='fixture-mutated', expected_version=due.version)

    def test_release_restart_exact_one_request_preserves_unknown_and_no_provider(self):
        f = self.f; released = self.release()
        self.assertEqual(released['outcome'], 'released')
        after = f.port.read_due(self.schedule)
        self.assertEqual(after['stop_state'], 'stopped')
        self.assertEqual(after['completion_state'], 'unknown')
        self.assertIsNone(after['in_flight_request'])
        self.assertEqual(after['host_evidence']['gateway_attempt'], self.before['host_evidence']['gateway_attempt'])
        self.assertEqual(f.app.recover(schedule_id=self.schedule)['outcome'], 'unknown')
        self.assertEqual(f.provider.calls, [])
        observations = f.app.assignments.list_observations(ResourceRef.from_dict(after['assignment_ref']), kind='report')
        self.assertEqual(len(observations), 1)
        request = {'request_key': 'new-worker-v1', 'route': 'normal', 'principal': 'worker'}
        self.assertTrue(permits_fresh_worker(f.app, f.app._read(self.schedule), request=request, model='gpt-test', reasoning='high'))
        for field, value in [('request_key', 'other'), ('route', 'xhard'), ('principal', 'foreign')]:
            self.assertFalse(permits_fresh_worker(f.app, f.app._read(self.schedule),
                request={**request, field: value}, model='gpt-test', reasoning='high'))
        self.assertFalse(permits_fresh_worker(f.app, f.app._read(self.schedule), request=request, model='gpt-other', reasoning='high'))
        f.compose(); f.app.runtime.adapter.trusted_thread_reader = lambda selected: {'thread': {'id': selected, 'path': str(self.trace)}}
        replay = f.app.release_capacity_failed_worker(schedule_id=self.schedule, request_key='release-capacity-v1',
            fresh_request_key='new-worker-v1', expected_due_sha256=_digest(self.before),
            expected_unknown_result_sha256=_digest(self.before['host_evidence']['gateway_attempt']['result']))
        self.assertEqual(replay['outcome'], 'replayed')
        self.assertEqual(f.port.read_due(self.schedule), after)
        self.assertEqual(f.provider.calls, [])

    def test_ordinary_service_admits_one_reserved_fresh_worker_and_keeps_history(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        f = self.f
        self.release()
        root = Path(f.temporary.name).resolve()
        (root / 'run.yaml').write_text(json.dumps({'roles': {
            'worker_normal': {'model': 'gpt-test', 'reasoning': 'high'},
            'worker_xhard': {'model': 'gpt-test', 'reasoning': 'high'}}}))
        old = {'schedule_id': self.schedule, 'principal': 'worker', 'model': 'gpt-test',
            'reasoning': 'high', 'request_key': 'first-worker', 'assignment_ref': self.before['assignment_ref'],
            'generation': 1, 'submission': {'command': 'run-worker', 'request_key': 'first-worker'}}
        state = {'workers': {'J01': old}, 'task_refs': {'J01': f.task.ref.to_dict()},
                 'project_ref': f.project.ref.to_dict()}
        admissions = []
        def submit(request):
            admissions.append(request)
            return {'outcome': 'admitted', 'retained_handle': 'fresh-handle'}
        server = SimpleNamespace(state=state, due_port=f.port, _execution=lambda **kw: f.app,
                                 _save_state=lambda: None)
        service = object.__new__(ManagerJourneyService)
        service.server = server; service.host = SimpleNamespace(_closing=False, submit=submit)
        service.run_path = service.workspace = root
        service.commands = SimpleNamespace(_authorize=lambda: f.actor, _key=lambda request: request['request_key'])
        request = {'command': 'run-worker', 'task': 'J01', 'route': 'normal', 'principal': 'worker',
                   'request_key': 'new-worker-v1', 'focus': 'Repair this exact bounded task'}
        fresh = service._submit_worker(request)
        self.assertEqual(fresh['outcome'], 'admitted', fresh)
        self.assertNotEqual(fresh['schedule_id'], self.schedule)
        self.assertEqual(state['worker_history']['J01'], [old])
        self.assertEqual(len(admissions), 1)
        self.assertEqual(f.port.read_due(self.schedule)['host_evidence']['gateway_attempt'],
                         self.before['host_evidence']['gateway_attempt'])
        third = service._submit_worker({**request, 'request_key': 'third-worker'})
        self.assertEqual(third['outcome'], 'held')
        self.assertEqual(len(admissions), 1)
        self.assertEqual(f.provider.calls, [])

    def test_stale_pins_no_report_or_stop(self):
        with self.assertRaises(OccurrencePreparationError): self.release(expected_due_sha256='0' * 64)
        self.assertEqual(self.f.port.read_due(self.schedule), self.before)
        self.assertEqual(self.f.app.assignments.list_observations(ResourceRef.from_dict(self.before['assignment_ref']), kind='report'), ())

    def test_changed_authorization_rejected(self):
        self.mutate_attempt(lambda a: a['delivery_authorization'].update(generation=2))
        with self.assertRaises(OccurrencePreparationError): self.release()

    def test_error_substring_or_work_content_cannot_release(self):
        self.mutate_attempt(lambda a: a['result']['raw_result']['work_envelope'].update(stdout=jsonl([
            {'type': 'error', 'message': CAPACITY}])) )
        with self.assertRaises(OccurrencePreparationError): self.release()

    def test_native_active_turn_rejected(self):
        with self.trace.open('a') as trace:
            trace.write(jsonl([{'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'foreign-turn'}}]))
        with self.assertRaises(OccurrencePreparationError): self.release()

    def test_native_tool_effect_rejected_even_with_terminal_capacity(self):
        with self.trace.open('a') as trace:
            trace.write(jsonl([{'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec'}}]))
        with self.assertRaises(OccurrencePreparationError): self.release()

    def test_receipt_only_cannot_authorize_release_without_native_reader(self):
        self.f.app.runtime.adapter.trusted_thread_reader = None
        with self.assertRaises(OccurrencePreparationError): self.release()

    def test_released_native_session_change_blocks_new_admission(self):
        self.release()
        with self.trace.open('a') as trace: trace.write(jsonl([{'type': 'world_state', 'payload': {}}]))
        self.assertFalse(permits_fresh_worker(self.f.app, self.f.app._read(self.schedule),
            request={'request_key': 'new-worker-v1', 'route': 'normal', 'principal': 'worker'}, model='gpt-test', reasoning='high'))


if __name__ == '__main__': unittest.main()
