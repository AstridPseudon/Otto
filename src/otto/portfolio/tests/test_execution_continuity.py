"""D04 bounded proof. Run PYTHONPATH=src:. python3 -m unittest
otto.portfolio.tests.test_execution_continuity. Only disposable owners/providers
and local child processes are used; installed servicing remains a host proof.
"""
from tests.execution_helpers import start_worker
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from otto.attention import DurableAttention
from otto.portfolio.execution_host import ExecutionHost, _nested_capability
from otto.portfolio.manager_journey_client import add_manager_journey_parsers, read_command_response
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.owner_readers import json_value
from tests import test_execution_application as fixture
from tests import test_stale_manager_stop as adoption_fixture


class OccurrenceContinuityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def stop(self, schedule):
        f = self.f
        due = f.port.read_due(schedule)
        return DurableAttention(None, due_port=f.port).stop(schedule, request_id='stop-' + schedule,
            expected_version=due['version'], project_ref=due['project_ref'], manager_ref=due['manager_ref'],
            generation=due['generation'], lifecycle_owner=due['lifecycle_owner'])

    def test_stopped_prepared_occurrence_never_resources_refreshes_or_executes(self):
        f = self.f
        prepared = f.app.assign_worker(**f.request())
        schedule = prepared['schedule_id']
        self.assertEqual(self.stop(schedule)['outcome'], 'stopped')
        before = f.port.read_due(schedule)
        with patch.object(f.app, '_resources', side_effect=AssertionError('stopped resources refresh')):
            self.assertEqual(f.app.start(schedule_id=schedule)['outcome'], 'stopped')
            self.assertEqual(f.app.recover(schedule_id=schedule, execute=True)['outcome'], 'stopped')
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(f.provider.calls, [])

    def test_null_result_restart_recovers_exact_attempt_without_replay_then_stop(self):
        f = self.f
        f.provider.unknown = True
        launched = start_worker(f.app, f.request())
        schedule = launched['schedule_id']
        due = f.port.read_due(schedule)
        due['host_evidence']['gateway_attempt']['result'] = None
        f.port.save_due(schedule, due, request_id='interrupted-result', expected_version=due['version'])
        before = f.port.read_due(schedule)
        f.store.close()
        f.store = fixture.Store.open(f.path, authority='execution-owner',
            expected_domains=tuple(sorted(f.domains, key=lambda d: d.domain_id)))
        f.compose()
        for operation in (lambda: f.app.recover(schedule_id=schedule, execute=True),
                          lambda: f.app.start(schedule_id=schedule)):
            self.assertEqual(operation()['outcome'], 'pending')
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(len(f.provider.calls), 1)
        self.assertEqual(self.stop(schedule)['outcome'], 'stopped')
        stopped = f.port.read_due(schedule)
        result = f.app.recover(schedule_id=schedule, execute=True)
        self.assertEqual(result['outcome'], 'stopped')
        self.assertTrue(result['reconciliation_required'])
        self.assertEqual(result['in_flight_request'], before['in_flight_request'])
        self.assertEqual(f.port.read_due(schedule), stopped)
        self.assertEqual(len(f.provider.calls), 1)

    def test_paused_prepared_occurrence_waits_for_exact_host_reconciliation(self):
        f = self.f
        schedule = f.app.assign_worker(**f.request())['schedule_id']
        due = f.port.read_due(schedule)
        due['host_state'] = 'paused'
        f.port.save_due(schedule, due, request_id='paused-trigger', expected_version=due['version'])
        before = f.port.read_due(schedule)
        self.assertEqual(f.app.start(schedule_id=schedule)['outcome'], 'paused')
        self.assertEqual(f.app.recover(schedule_id=schedule, execute=True)['outcome'], 'paused')
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(f.provider.calls, [])

    def test_resource_adoption_then_stop_read_preserves_old_effect_and_history(self):
        # Existing real DAT/adoption fixture covers the accepted same-generation
        # stop exception. D04 adds recovery, without rewriting those old pins.
        adopted = adoption_fixture.StaleManagerStopTests()
        adopted.setUp()
        self.addCleanup(adopted.doCleanups)
        self.assertEqual(adopted.stop()['outcome'], 'stopped')
        f = adopted.f
        before = f.port.read_due(adopted.schedule)
        calls = list(f.provider.calls)
        history = json_value(f.owner.assignments.command_port.get(adopted.adopted.ref))
        self.assertEqual(f.app.start(schedule_id=adopted.schedule)['outcome'], 'stopped')
        self.assertEqual(f.app.recover(schedule_id=adopted.schedule, execute=True)['outcome'], 'stopped')
        self.assertEqual(f.port.read_due(adopted.schedule), before)
        self.assertEqual(json_value(f.owner.assignments.command_port.get(adopted.adopted.ref)), history)
        self.assertEqual(f.provider.calls, calls)

    def service(self):
        f = self.f
        assignment, guide, mandate = f.role_handles('manager', 'manager', 'manager-session')
        prepared = f.app.prepare_role(role='manager', project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key='prepared-manager',
            instruction='Inspect work', model='gpt-test', reasoning='high', profile='workspace-write',
            native_session_id='manager-session')
        state = {'authority': f.actor.authority, 'owner': 'manager', 'manager': 'manager',
            'assignment_ref': assignment.ref.to_dict(), 'manager_generation': 1,
            'project_ref': f.project.ref.to_dict(), 'task_refs': {'D04': f.task.ref.to_dict()},
            'schedule_id': prepared['schedule_id'], 'workers': {}}
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, due_port=f.port,
            state=state, _execution=lambda **_: f.app)
        host = ExecutionHost(directory=Path(f.temporary.name) / 'control', handler=lambda r: {})
        service = ManagerJourneyService(server=server, host=host, run_path=f.temporary.name,
            workspace=f.temporary.name)
        host.handler = service
        return host, service, prepared['schedule_id']

    def test_actual_parser_service_stop_recover_and_drain_use_current_handles(self):
        host, service, schedule = self.service()
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest='command'))
        host.start()
        self.addCleanup(host.close)
        handles = []
        def command(*args):
            request = vars(parser.parse_args(['execution-control', *args]))
            handle = format(len(handles) + 1, 'x')
            handles.append(handle)
            (host.directory / ('request-' + handle + '.json')).write_text(json.dumps(request))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                response = read_command_response(host.directory, handle)
                if response is not None:
                    return response
                time.sleep(.01)
            self.fail('retained control request did not return: ' + handle)
        version = command('--schedule-id', schedule)['occurrence']['version']
        self.assertEqual(command('--operation', 'stop', '--schedule-id', schedule,
            '--request-key', 'ordinary-stop', '--expected-version', str(version))['outcome'], 'stopped')
        self.assertEqual(command('--operation', 'resume', '--schedule-id', schedule)['outcome'], 'stopped')
        self.assertEqual(command('--operation', 'recover', '--schedule-id', schedule)['outcome'], 'stopped')
        self.assertEqual(command('--operation', 'drain')['outcome'], 'draining')
        self.assertTrue(host.draining)
        self.assertEqual(self.f.provider.calls, [])
        self.assertEqual(command('--schedule-id', 'foreign-schedule')['error'], 'PermissionError')
        with self.assertRaises(ValueError):
            service({'command': 'execution-control', 'operation': 'read', 'schedule_id': schedule, 'actor': 'foreign'})
        self.assertEqual(_nested_capability({'command': 'execution-control', 'operation': 'resume'}), 'retained')

    def test_service_resume_reconciles_and_uses_shared_manager_readiness(self):
        host, service, schedule = self.service()
        request = {'command': 'execution-control', 'operation': 'resume', 'schedule_id': schedule}
        with patch.object(self.f.app, 'read_operating_setup', return_value={'ready': False}):
            self.assertEqual(service(request)['outcome'], 'blocked')
        self.assertEqual(self.f.provider.calls, [])
        with patch.object(self.f.app, 'read_operating_setup', return_value={'ready': True}):
            self.assertEqual(service(request)['outcome'], 'succeeded')
        before = self.f.port.read_due(schedule)
        self.assertEqual(service(request)['outcome'], 'replayed')
        self.assertEqual(self.f.port.read_due(schedule), before)
        self.assertEqual(len(self.f.provider.calls), 1)


class HostContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='portable-d04-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_drain_retains_effect_requests_and_serves_finite_bookkeeping_then_restart(self):
        calls = []
        host = ExecutionHost(directory=self.root, handler=lambda r: calls.append(r) or {'outcome': 'done'})
        host.start()
        released, admitted = threading.Event(), threading.Event()
        def child():
            admitted.set()
            released.wait(5)
        host.retain(name='admitted', operation=child)
        self.assertTrue(admitted.wait(1))
        host.begin_drain()
        closer = threading.Thread(target=host.close)
        closer.start()
        for index, request in enumerate(({'command': 'start-retained-worker', 'schedule_id': 'exact'},
                {'command': 'run-worker'}, {'command': 'start-retained-help'},
                {'command': 'operating-setup', 'operation': 'activate'},
                {'command': 'execution-control', 'operation': 'resume'},
                {'command': 'manager-help-result'}, {'command': 'report'})):
            (self.root / f'request-{index:x}.json').write_text(json.dumps(request))
        try:
            deadline = time.monotonic() + 2
            while not (self.root / 'response-6.json').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.root / 'response-6.json').exists())
            self.assertEqual(calls, [{'command': 'report'}])
            self.assertTrue(closer.is_alive())
            self.assertEqual(host._dispatch({'command': 'run-worker'})['outcome'], 'held')
            with self.assertRaisesRegex(RuntimeError, 'draining'):
                host.retain(name='late', operation=lambda: None)
        finally:
            released.set(); closer.join(3)
        self.assertFalse(closer.is_alive())
        for index in range(6):
            self.assertTrue((self.root / f'request-{index:x}.json').exists())
            self.assertFalse((self.root / f'response-{index:x}.json').exists())
        self.assertFalse((self.root / 'owner.json').exists())
        restarted = ExecutionHost(directory=self.root, handler=lambda r: calls.append(r) or {'outcome': 'done'})
        restarted.start()
        try:
            deadline = time.monotonic() + 2
            while not (self.root / 'response-5.json').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.root / 'response-5.json').exists())
        finally:
            restarted.close()
        self.assertEqual(len(calls), 7)

    def test_resume_wait_keeps_serialized_child_bookkeeping_available(self):
        called = []
        host = None
        def handler(request):
            called.append(request['command'])
            if request['command'] == 'execution-control':
                def provider():
                    (self.root / 'request-b.json').write_text(json.dumps({'command': 'report'}))
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        if read_command_response(self.root, 'b') is not None:
                            return {'outcome': 'succeeded'}
                        time.sleep(.01)
                    raise RuntimeError('resume did not pump child bookkeeping')
                return ExecutionHost.external_call(provider)
            return {'outcome': 'reported'}
        host = ExecutionHost(directory=self.root, handler=handler)
        host.start()
        try:
            (self.root / 'request-a.json').write_text(json.dumps(
                {'command': 'execution-control', 'operation': 'resume'}))
            deadline = time.monotonic() + 3
            result = None
            while time.monotonic() < deadline:
                result = read_command_response(self.root, 'a')
                if result is not None: break
                time.sleep(.01)
            self.assertIsNotNone(result)
            self.assertEqual(result['outcome'], 'succeeded', result)
            self.assertEqual(called, ['execution-control', 'report'])
        finally:
            host.close()

    def supervise(self, **options):
        defaults = dict(argv=[sys.executable, '-c', 'raise SystemExit(3)'],
            receipt_path=self.root / 'supervision.json', source_identity={'source': 'fixture', 'runtime': 'fixture'},
            reconcile=lambda receipt: {'ready': True, 'retained_effect': 'none'},
            disposition=lambda: 'active', request_stop=lambda process: None,
            restart_delay=.02, max_restart_delay=.04)
        return ExecutionHost.supervise(**{**defaults, **options})

    def test_real_host_exits_are_captured_and_restart_limit_is_not_reset(self):
        observed = []
        result = self.supervise(reconcile=lambda receipt: observed.append(receipt) or {'ready': True})
        self.assertEqual(result['outcome'], 'restart_exhausted')
        self.assertEqual([r['exit_status'] for r in result['exit_receipts']], [3, 3, 3])
        self.assertEqual(len(observed), 3)
        self.assertIsNone(observed[0])
        self.assertEqual(observed[1]['index'], 0)
        for receipt in result['exit_receipts']:
            retained = self.root / f"supervision.json.exit-{receipt['index']}.json"
            self.assertEqual(json.loads(retained.read_text()), receipt)
            self.assertGreaterEqual(receipt['duration_seconds'], 0)
        with self.assertRaises(FileExistsError):
            self.supervise()

    def test_unknown_reconciliation_holds_before_restart(self):
        count = 0
        def reconcile(receipt):
            nonlocal count
            count += 1
            return {'ready': count == 1, 'retained_handle': 'exact-handle', 'state': 'unknown'}
        result = self.supervise(reconcile=reconcile)
        self.assertEqual(result['outcome'], 'held')
        self.assertEqual(len(result['exit_receipts']), 1)
        self.assertEqual(result['reconciliation']['retained_handle'], 'exact-handle')

    def test_stop_and_pause_suppress_initial_admission(self):
        for state in ('stopped', 'paused'):
            factory = Mock(side_effect=AssertionError('must not spawn'))
            reconcile = Mock(side_effect=AssertionError('must not reconcile stopped host'))
            result = self.supervise(receipt_path=self.root / (state + '.json'),
                disposition=lambda: state, reconcile=reconcile, process_factory=factory)
            self.assertEqual(result['outcome'], state)
            factory.assert_not_called(); reconcile.assert_not_called()

    def test_pause_during_backoff_suppresses_restart(self):
        started = threading.Event()
        current = ['active']
        def factory(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            started.set()
            return process
        def pause():
            started.wait(1); time.sleep(.06); current[0] = 'paused'
        pauser = threading.Thread(target=pause)
        pauser.start()
        result = self.supervise(process_factory=factory, disposition=lambda: current[0],
            restart_delay=.2, max_restart_delay=.2)
        pauser.join(1)
        self.assertEqual(result['outcome'], 'paused')
        self.assertEqual(len(result['exit_receipts']), 1)

    def test_stop_during_service_uses_graceful_marker_and_captures_exit(self):
        marker = self.root / 'stop'
        running = threading.Event()
        state = ['active']
        def factory(*args, **kwargs):
            result = subprocess.Popen(*args, **kwargs)
            running.set()
            return result
        def stop():
            running.wait(1); state[0] = 'stopped'
        stopper = threading.Thread(target=stop)
        stopper.start()
        code = 'import time,pathlib; p=pathlib.Path(' + repr(str(marker)) + ');\nwhile not p.exists(): time.sleep(.01)'
        result = self.supervise(argv=[sys.executable, '-c', code], disposition=lambda: state[0],
            process_factory=factory, request_stop=lambda process: marker.write_text('drain'))
        stopper.join(1)
        self.assertEqual(result['outcome'], 'stopped')
        self.assertEqual(result['exit_receipts'][0]['exit_status'], 0)
        self.assertTrue(marker.exists())

    def test_success_exit_is_closed_and_unknown_launch_is_never_retried(self):
        result = self.supervise(argv=[sys.executable, '-c', 'pass'])
        self.assertEqual(result['outcome'], 'closed')
        factory = Mock(side_effect=OSError('launch uncertain'))
        result = self.supervise(receipt_path=self.root / 'unknown.json', process_factory=factory)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertIsNone(result['exit_receipts'][0]['exit_status'])
        self.assertEqual(factory.call_count, 1)

    def test_service_wait_observes_command_drain_and_retains_explicit_marker(self):
        host = ExecutionHost(directory=self.root / 'ipc', handler=lambda request: {})
        waiter = threading.Thread(target=host.wait_until_stopped, args=(lambda: False,),
            kwargs={'poll_seconds': .01})
        waiter.start()
        host.begin_drain()
        waiter.join(1)
        self.assertFalse(waiter.is_alive())
        marker = self.root / 'explicit-stop'
        marker.write_text('stop')
        fresh = ExecutionHost(directory=self.root / 'fresh', handler=lambda request: {})
        fresh.wait_until_stopped(marker.exists)
        self.assertTrue(fresh.draining)
        self.assertEqual(marker.read_text(), 'stop')

    def test_stop_requested_by_reconciliation_prevents_spawn(self):
        current = ['active']
        def reconcile(receipt):
            current[0] = 'stopped'
            return {'ready': True}
        factory = Mock(side_effect=AssertionError('must not spawn after stop'))
        result = self.supervise(disposition=lambda: current[0], reconcile=reconcile, process_factory=factory)
        self.assertEqual(result['outcome'], 'stopped')
        factory.assert_not_called()

    def test_invalid_limits_are_inert(self):
        for options in ({'max_restarts': True}, {'max_restarts': -1}, {'restart_delay': 0},
                        {'restart_delay': float('nan')}, {'max_restart_delay': .001}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.supervise(**options)
        self.assertFalse((self.root / 'supervision.json').exists())


if __name__ == '__main__':
    unittest.main()


class InstalledOwnerCompositionTests(unittest.TestCase):
    def test_supervised_real_child_receives_private_fifo_and_retains_exit(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fifo = root / 'root.stdin'; os.mkfifo(fifo, 0o600)
            fd = os.open(fifo, os.O_RDWR)
            try:
                os.write(fd, b'authenticated-root-input\n')
                calls = []
                result = ExecutionHost.supervise_owner_service(
                    argv=[sys.executable, '-u', '-c', 'import sys; print(sys.stdin.readline().strip())'],
                    cwd=root, stdin_fifo=fifo, log_path=root / 'owner.log', receipt_path=root / 'supervision.json',
                    source_identity={'installed': 'exact-digest'}, reconcile=lambda prior: calls.append(prior) or {'ready': True},
                    disposition=lambda: 'active', request_stop=lambda _: self.fail('no stop requested'), max_restarts=1)
                self.assertEqual(result['outcome'], 'closed')
                self.assertEqual((root / 'owner.log').read_text().strip(), 'authenticated-root-input')
                self.assertEqual(len(calls), 1)
                self.assertEqual(result['exit_receipts'][0]['exit_status'], 0)
                self.assertFalse(result['provider_replayed'])
            finally: os.close(fd)

    def test_private_fifo_composition_rejects_symlink_before_admission(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fifo = root / 'root.stdin'; os.mkfifo(fifo, 0o600)
            link = root / 'caller.stdin'; link.symlink_to(fifo)
            with self.assertRaises(PermissionError):
                ExecutionHost.supervise_owner_service(argv=[sys.executable], cwd=root, stdin_fifo=link,
                    log_path=root / 'owner.log', receipt_path=root / 'supervision.json', source_identity={'installed':'digest'},
                    reconcile=lambda _: self.fail('symlink must fail before reconciliation'), disposition=lambda:'active', request_stop=lambda _:None)
            self.assertFalse((root / 'supervision.json').exists())
