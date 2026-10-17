"""Canonical owner custody retirement with provider execution forbidden."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

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

    def spawn_fake_worker(self):
        script = Path(__file__).resolve().parents[1] / 'ops' / 'bootstrap' / 'canary' / 'fake_worker.py'
        root = self.f.temporary.name
        return subprocess.Popen([sys.executable, str(script), '--lab', root, '--task', 'hold',
                                 '--project', str(Path(root) / 'unused-project.json'),
                                 '--events', str(Path(root) / 'unused-events.jsonl'), '--hold'],
                                start_new_session=True)

    def test_forced_owner_stop_kills_recorded_fake_worker_but_not_a_reused_pid(self):
        from otto.agents.claude_cli import terminate_recorded_process_group
        from otto.portfolio.execution_host import _process_start_identity

        process = self.spawn_fake_worker()
        self.addCleanup(lambda: (process.poll() is None and os.killpg(process.pid, signal.SIGKILL),
                                 process.wait()))
        record = {'pid': process.pid, 'pgid': process.pid,
                  'birth': _process_start_identity(process.pid)['birth']}
        self.assertTrue(terminate_recorded_process_group(record))
        self.assertLess(process.wait(timeout=2), 0, 'the forced owner stop left its fake worker alive')

        stale = self.spawn_fake_worker()
        self.addCleanup(lambda: (stale.poll() is None and os.killpg(stale.pid, signal.SIGKILL), stale.wait()))
        reused = {'pid': stale.pid, 'pgid': stale.pid,
                  'birth': [value + 1 for value in _process_start_identity(stale.pid)['birth']]}
        self.assertFalse(terminate_recorded_process_group(reused))
        self.assertIsNone(stale.poll(), 'a reused PID must be left alone')


    def test_owner_startup_terminates_a_recorded_worker_group(self):
        from otto.portfolio.execution_host import ExecutionHost, _process_start_identity
        directory = Path(self.f.temporary.name) / 'startup-host'
        directory.mkdir()
        process = self.spawn_fake_worker()
        self.addCleanup(lambda: (process.poll() is None and os.killpg(process.pid, signal.SIGKILL),
                                 process.wait()))
        record = {'pid': process.pid, 'pgid': process.pid,
                  'birth': _process_start_identity(process.pid)['birth']}
        (directory / 'capacity-process-groups.json').write_text(json.dumps({'worker': record}))
        host = ExecutionHost(directory=directory, handler=lambda _request: None, bounded_transports=True)
        host.start()
        self.addCleanup(host.close)
        self.assertLess(process.wait(timeout=2), 0, 'owner startup left its recorded fake worker alive')

    def test_competing_owner_cannot_kill_worker_before_claiming_custody(self):
        from otto.portfolio.execution_host import ExecutionHost, _process_start_identity
        directory = Path(self.f.temporary.name) / 'competing-host'
        owner = ExecutionHost(directory=directory, handler=lambda _request: None, bounded_transports=True)
        owner.start()
        self.addCleanup(owner.close)

        process = self.spawn_fake_worker()
        self.addCleanup(lambda: (process.poll() is None and os.killpg(process.pid, signal.SIGKILL),
                                 process.wait()))
        record = {'pid': process.pid, 'pgid': process.pid,
                  'birth': _process_start_identity(process.pid)['birth']}
        (directory / 'capacity-process-groups.json').write_text(json.dumps({'worker': record}))
        contender = ExecutionHost(directory=directory, handler=lambda _request: None, bounded_transports=True)
        with self.assertRaisesRegex(RuntimeError, 'another execution host owns this command directory'):
            contender.start()
        self.assertIsNone(process.poll(), 'the rejected contender killed a worker owned by the live owner')

    def test_forced_owner_close_terminates_recorded_fake_worker(self):
        from otto.portfolio.execution_host import ExecutionHost, _process_start_identity
        directory = Path(self.f.temporary.name) / 'stop-host'
        process = self.spawn_fake_worker()
        self.addCleanup(lambda: (process.poll() is None and os.killpg(process.pid, signal.SIGKILL),
                                 process.wait()))
        host = ExecutionHost(directory=directory, handler=lambda _request: None, bounded_transports=True)
        host._process_groups['worker'] = {'pid': process.pid, 'pgid': process.pid,
                                          'birth': _process_start_identity(process.pid)['birth']}
        host.start()
        host.close()
        self.assertLess(process.wait(timeout=2), 0, 'forced owner close left its fake worker alive')

    def test_release_restart_exact_one_request_preserves_unknown_and_no_provider(self):
        f = self.f; released = self.release()
        self.assertEqual(released['outcome'], 'released')
        after = f.port.read_due(self.schedule)
        self.assertEqual(after['stop_state'], 'stopped')
        self.assertEqual(after['completion_state'], 'unknown')
        self.assertIsNone(after['in_flight_request'])
        self.assertEqual(after['host_evidence']['gateway_attempt'], self.before['host_evidence']['gateway_attempt'])
        self.assertEqual(f.app.recover(schedule_id=self.schedule)['outcome'], 'stopped')
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
        lab_workspace = root / 'worker-labs' / 'J01'
        lab_workspace.mkdir(parents=True)
        f.app.runtime.adapter.worktree = str(lab_workspace)
        old = {'schedule_id': self.schedule, 'principal': 'worker', 'model': 'gpt-test',
            'reasoning': 'high', 'request_key': 'first-worker', 'assignment_ref': self.before['assignment_ref'],
            'generation': 1, 'submission': {'command': 'run-worker', 'request_key': 'first-worker'}}
        manager, _guide, _mandate = f.role_handles('manager','manager',None)
        state = {'workers': {'J01': old}, 'task_refs': {'J01': f.task.ref.to_dict()},
                 'project_ref': f.project.ref.to_dict(),'assignment_ref':manager.ref.to_dict()}
        admissions = []
        def worker_lab(project_ref, task_ref):
            if project_ref != state['project_ref'] or task_ref != state['task_refs']['J01']:
                raise PermissionError('worker lab requested for a different project or task')
            return {'workspace': str(lab_workspace), 'project_ref': project_ref, 'task_ref': task_ref}
        def submit(request):
            admissions.append(request)
            return {'outcome': 'admitted', 'retained_handle': 'fresh-handle'}
        server = SimpleNamespace(state=state, due_port=f.port, owner=f.owner, portfolio=f.app.portfolio, _execution=lambda **kw: f.app,
                                 _save_state=lambda: None,
                                 worker_lab_provider=worker_lab)
        service = object.__new__(ManagerJourneyService)
        service.server = server; service.host = SimpleNamespace(_closing=False, submit=submit)
        service._execution=server._execution;service.adapter_selection=None
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


class RestartProcessScopeTests(unittest.TestCase):
    def test_rejected_contender_close_cannot_resume_active_owners_latch(self):
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-contender-') as root:
            owner = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            owner.start()
            try:
                latch = str(owner._scope_latch_path('work'))
                Path(latch).write_text(json.dumps({'pgid': 999, 'leader_birth': 'birth',
                    'state': 'running', 'members': {'999': 'birth'}}))
                (Path(root) / 'capacity-process-groups.json').write_text(json.dumps({'work': {
                    'scope_latch': latch, 'scope_disposition': 'running'}}))
                contender = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
                with mock.patch('herzchen.fleet.custody.resume_cleanup') as resume:
                    with self.assertRaisesRegex(RuntimeError, 'another execution host owns'):
                        contender.start()
                    contender.close()
                    resume.assert_not_called()
                    self.assertTrue(Path(latch).exists())
            finally:
                with mock.patch.object(owner, '_terminate_recorded_process_groups'):
                    owner.close()

    def test_claude_transport_passes_prepared_latch_to_custody_before_spawn(self):
        from herzchen.fleet.hosts import McpGrant
        from otto.agents import claude_cli as cli
        transport = object.__new__(cli.ClaudeCliTransport)
        transport.pin = SimpleNamespace(realpath='/fake/claude')
        transport.scope = SimpleNamespace(workspace='/private/tmp', allow_subprocesses=False)
        transport.model, transport.reasoning = 'm', 'high'
        transport.mcp, transport.tools, transport.max_turns = McpGrant(), cli.WORKER_TOOLS, 8
        transport.process_factory = lambda *_a, **_k: None
        transport.preflight = lambda: {}
        transport.environment = lambda: {}
        plan = SimpleNamespace(argv=('/fake/claude',), stdin=b'prompt', env={}, command=lambda: ('/fake/claude',))
        events = []
        def prepare():
            events.append('prepared')
            return '/private/tmp/owner-scope-latch.json'
        def launch(_argv, **kwargs):
            events.append(('launch', kwargs['latch_path']))
            raise OSError('fixture stops before a process')
        with mock.patch.object(cli.CLAUDE, 'launch', return_value=plan), \
                mock.patch.object(cli.CLAUDE, 'parser', return_value=object()), \
                mock.patch.object(cli.Custody, 'launch', side_effect=launch):
            with self.assertRaisesRegex(OSError, 'fixture stops'):
                transport.run('prompt', initializer=True, on_launch=prepare)
        self.assertEqual(events, ['prepared', ('launch', '/private/tmp/owner-scope-latch.json')])

    def test_definite_spawn_failure_without_latch_releases_only_physical_capacity(self):
        from herzchen.fleet.custody import Custody
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-no-spawn-') as root:
            owner = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            owner.start()
            owner._executions['work'] = {'running': True}
            latch = owner._owned(lambda: owner.record_process_launch_intent('work'))
            with self.assertRaises(OSError):
                Custody.launch(['fake'], latch_path=latch,
                               popen=lambda _argv, **_kwargs: (_ for _ in ()).throw(OSError('no spawn')))
            self.assertFalse(Path(latch).exists())
            with mock.patch.object(owner, '_terminate_recorded_process_groups'):
                owner.close()
            restarted = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            restarted._capacity_holds['work'] = {'schedule_id': 'work', 'project': 'project-a',
                'role': 'worker', 'session': 's', 'assignment': ('a', 1), 'workspace': root, 'writer': False}
            restarted.capacity.ensure_turn('work', uncertain=True)
            restarted.start()
            try:
                self.assertEqual(restarted._process_groups['work']['scope_disposition'], 'gone')
                self.assertIn('work', restarted._capacity_holds)
                self.assertNotIn('work', restarted.capacity_holds())
            finally:
                restarted.close()

    def test_crash_between_scope_launch_and_owner_pin_recovers_exact_latch(self):
        from herzchen.fleet.custody import Custody, Disposition, Proc
        from otto.agents.owner_runtime import _pin_process_group
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-crash-') as root:
            owner = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            owner.start()
            owner._executions['work'] = {'running': True}
            adapter = SimpleNamespace()
            owner._owned(lambda: _pin_process_group(adapter, 'work'))
            latch = owner._owned(lambda: adapter.process_pin.prepare_launch())
            def spawned_before_pin(_argv, **_kwargs):
                record = json.loads((Path(root) / 'capacity-process-groups.json').read_text())['work']
                self.assertEqual(record['scope_latch'], latch)
                self.assertTrue(Path(latch).exists(), 'scope intent must precede the process effect')
                return SimpleNamespace(pid=999)
            custody = Custody.launch(['fake'], latch_path=latch, popen=spawned_before_pin,
                census_fn=lambda: {999: Proc(999, os.getpid(), 999, 'native-birth')})
            self.assertEqual(custody.leader_birth, 'native-birth')
            self.assertEqual(json.loads(Path(latch).read_text())['leader_birth'], 'native-birth')
            with mock.patch.object(owner, '_terminate_recorded_process_groups'):
                owner.close()
            restarted = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            hold = {'schedule_id': 'work', 'project': 'project-a', 'role': 'worker', 'session': 's',
                    'assignment': ('a', 1), 'workspace': root, 'writer': False}
            restarted._capacity_holds['work'] = hold
            restarted.capacity.ensure_turn('work', uncertain=True)
            with mock.patch('herzchen.fleet.custody.resume_cleanup',
                            return_value=Disposition('uncertain', 'launch identity unavailable')) as resume:
                restarted.start()
                try:
                    resume.assert_called_once_with(latch)
                    self.assertIn('work', restarted.capacity_holds())
                    self.assertEqual(restarted._process_groups['work']['scope_latch'], latch)
                    def settled(path):
                        Path(path).unlink()
                        return Disposition('gone')
                    with mock.patch('herzchen.fleet.custody.resume_cleanup', side_effect=settled):
                        restarted._terminate_recorded_process_groups()
                    self.assertEqual(restarted.reconcile_dead_holds(), ['work'])
                    self.assertIn('work', restarted._capacity_holds)
                    self.assertNotIn('work', restarted.capacity_holds())
                finally:
                    restarted.close()

    def test_competing_owner_cannot_reconcile_capacity_before_claim(self):
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-owner-') as root:
            owner = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            owner.start()
            try:
                contender = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
                with mock.patch.object(contender, 'reconcile_dead_holds') as reconcile:
                    with self.assertRaisesRegex(RuntimeError, 'another execution host owns'):
                        contender.start()
                    reconcile.assert_not_called()
            finally:
                owner.close()

    def test_recorded_birth_without_recorded_group_cannot_signal_a_reused_group(self):
        from otto.agents.claude_cli import terminate_recorded_process_group
        record = {'pid': 123, 'pgid': 123, 'birth': [7]}
        with mock.patch('otto.agents.claude_cli.os.getpgid', return_value=456), \
                mock.patch('otto.agents.claude_cli.os.killpg') as kill:
            self.assertFalse(terminate_recorded_process_group(record, birth_reader=lambda _pid: [7]))
            kill.assert_not_called()

    def test_changed_leader_with_live_recorded_group_keeps_physical_hold(self):
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-group-') as root:
            host = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            host._process_groups['old'] = {'pid': 123, 'pgid': 123, 'birth': [7]}
            with mock.patch('otto.portfolio.execution_host._process_start_identity',
                            return_value={'birth': [8]}), \
                    mock.patch('otto.portfolio.execution_host.os.killpg', return_value=None), \
                    mock.patch('otto.portfolio.execution_host.os.getpgid', return_value=456):
                self.assertEqual(host._group_state(host._process_groups['old']), 'unproven')
                self.assertFalse(host._reconcile_hold('old'))

    def test_replacement_leader_of_same_group_frees_only_physical_hold(self):
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-group-') as root:
            host = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            host._process_groups['old'] = {'pid': 123, 'pgid': 123, 'birth': [7]}
            with mock.patch('otto.portfolio.execution_host._process_start_identity',
                            return_value={'birth': [8]}), \
                    mock.patch('otto.portfolio.execution_host.os.killpg', return_value=None), \
                    mock.patch('otto.portfolio.execution_host.os.getpgid', return_value=123):
                self.assertEqual(host._group_state(host._process_groups['old']), 'reused')
                self.assertTrue(host._reconcile_hold('old'))
                self.assertIn('old', host._capacity_freed)

    def test_empty_group_does_not_free_scope_with_unsettled_setsid_escapee(self):
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-escapee-') as root:
            host = ExecutionHost(directory=root, handler=lambda _request: None, bounded_transports=True)
            latch = str(host._scope_latch_path('work'))
            host._process_groups['work'] = {'pid': 123, 'pgid': 123, 'birth': [7],
                                            'scope_latch': latch, 'scope_disposition': 'running'}
            Path(latch).write_text(json.dumps({'pgid': 123, 'leader_birth': 'birth',
                                                'state': 'terminating', 'members': {'123': 'birth'}}))
            with mock.patch('otto.portfolio.execution_host._process_start_identity',
                            side_effect=ProcessLookupError), \
                    mock.patch('otto.portfolio.execution_host.os.killpg', side_effect=ProcessLookupError):
                self.assertFalse(host._reconcile_hold('work'))
            self.assertNotIn('work', host._capacity_freed)

    def test_restart_reuses_group_without_killing_it_and_frees_only_physical_capacity(self):
        from otto.portfolio.execution_host import ExecutionHost
        with tempfile.TemporaryDirectory(prefix='worker-restart-') as root:
            directory = Path(root)
            (directory / 'capacity-process-groups.json').write_text(json.dumps({
                'old': {'pid': 123, 'pgid': 123, 'birth': [7]},
                'matching': {'pid': 124, 'pgid': 124, 'birth': [9]}}))
            host = ExecutionHost(directory=directory, handler=lambda _request: None, bounded_transports=True)
            old = {'schedule_id': 'old', 'project': 'project-a', 'role': 'worker', 'session': 'a',
                   'assignment': ('a', 1), 'workspace': str(directory / 'a'), 'writer': False}
            host._capacity_holds['old'] = old
            host.capacity.ensure_turn('old', uncertain=True)
            signals = []
            def signal_group(pgid, sig):
                if pgid == 123 and sig == 0:
                    raise ProcessLookupError
                if sig == signal.SIGKILL:
                    self.assertTrue(host.owner_path.exists(), 'the host must claim before signaling')
                    signals.append(pgid)
            with mock.patch('otto.portfolio.execution_host._process_start_identity',
                               side_effect=lambda pid: {'birth': [8] if pid == 123 else [9] if pid == 124 else [1], 'pid': pid,
                                                        'parent': 1, 'uid': os.getuid()}), \
                    mock.patch('otto.agents.claude_cli.os.getpgid', side_effect=lambda pid: 456 if pid == 123 else pid), \
                    mock.patch('otto.agents.claude_cli.os.killpg', side_effect=signal_group):
                host.start()
                try:
                    self.assertEqual(signals, [124])
                    self.assertIn('old', host._capacity_holds)
                    self.assertNotIn('old', host.capacity_holds())
                    other = {**old, 'schedule_id': 'new', 'project': 'project-b', 'session': 'b',
                             'assignment': ('b', 1), 'workspace': str(directory / 'b')}
                    self.assertTrue(host._eligible(other))
                finally:
                    host.close()


if __name__ == '__main__': unittest.main()
