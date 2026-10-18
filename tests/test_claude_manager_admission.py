"""Claude Code as a declared MANAGER through the existing owner admission hooks.

Every provider stream here is SYNTHETIC (no model call). The real owner Store,
Due, operating setup, gateway, owner authorization and capture are exercised;
only the provider process is substituted. The macOS fence test runs the real
sandbox-exec profile with a local probe, never the Claude CLI.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from otto.agents.claude_cli import (ClaudeBindingError, ClaudeCliTransport, LauncherPin, MANAGER_TOOLS,
                                    MacWriteScope, VERSION, WORKER_TOOLS, file_digest)
from otto.agents.claude_adapter import ClaudeNativeResultVerifier, ClaudeWorkerAdapter, ROLE_PROFILES
from otto.portfolio.operating_composition import SCHEMA
import test_execution_application as owner_fixture

MANAGER_PROCESS = r'''
import sys,json,os,subprocess
frame=json.loads(sys.stdin.readline());prompt=frame['message']['content'][0]['text'];session=frame.get('session_id') or 'manager-native-session'
init=prompt.startswith('Initialize this session only.');tools=[] if init else sorted(['Bash','Edit','Glob','Grep','Read','Write']);cwd=os.getcwd()
def emit(e): print(json.dumps(e),flush=True)
emit({'type':'system','subtype':'init','session_id':session,'cwd':cwd,'model':'claude-haiku-5-5','permissionMode':'bypassPermissions','tools':tools,'mcp_servers':[],'plugins':[],'skills':[],'slash_commands':[]})
emit({'type':'user','uuid':'input-init' if init else 'input-work','session_id':session,'message':{'role':'user','content':[{'type':'text','text':prompt}]}})
if not init:
 emit({'type':'assistant','uuid':'assistant-1','session_id':session,'message':{'role':'assistant','model':'claude-haiku-5-5','content':[{'type':'tool_use','id':'bash-1','name':'Bash','input':{'command':'ottoctl status'}}]}})
 out=subprocess.run(['/bin/echo','status read'],capture_output=True,text=True).stdout
 emit({'type':'user','uuid':'tool-result-1','session_id':session,'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'bash-1','is_error':False,'content':out}]}})
emit({'type':'result','subtype':'success','is_error':False,'session_id':session,'uuid':'result-init' if init else 'result-work','result':'READY' if init else 'Manager turn: read status, delegated nothing yet.','usage':{'input_tokens':21,'output_tokens':9}})
'''


class SyntheticScope:
    identity = MacWriteScope.identity

    def __init__(self, root, state, *, subprocesses):
        self.workspace, self.state_root, self.allow_subprocesses = root, state, subprocesses
        self.pin = {'identity': self.identity, 'workspace': root, 'state_root': state,
                    'evidence_kind': 'SYNTHETIC', 'subprocesses': subprocesses}

    def preflight(self):
        return {**self.pin, 'verified': True}

    def wrap(self, command, **options):
        return command


def transport(root, state, *, tools, subprocesses, model='claude-haiku-5-5'):
    executable = str(Path(sys.executable).resolve())
    pin = LauncherPin(executable, executable, file_digest(Path(executable)), VERSION)
    calls, processes = [], []

    def factory(command, **kwargs):
        calls.append(command)
        process = subprocess.Popen([sys.executable, '-c', MANAGER_PROCESS], **kwargs)
        processes.append(process)
        return process

    value = ClaudeCliTransport(pin, SyntheticScope(root, state, subprocesses=subprocesses), model=model,
                               reasoning='medium', timeout_seconds=10, process_factory=factory, tools=tools,
                               max_turns=ROLE_PROFILES['manager']['max_turns'] if 'Bash' in tools else 8)
    value.calls, value.processes = calls, processes
    return value


class ClaudeManagerAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = str(Path(self.f.temporary.name).resolve())
        state = tempfile.TemporaryDirectory(prefix='otto-claude-manager-state-')
        self.addCleanup(state.cleanup)
        self.state = str(Path(state.name).resolve())
        self.worker_t = transport(self.root, self.state, tools=WORKER_TOOLS, subprocesses=False)
        self.manager_t = transport(self.root, self.state, tools=MANAGER_TOOLS, subprocesses=True)
        self.observed = []

        def observer(process, authorization):
            self.observed.append((process.pid, authorization['role'], authorization['physical_session_id']))
            return lambda: self.observed.append('cleanup')

        self.adapter = ClaudeWorkerAdapter(owner='manager', source=self.root, worktree=self.root,
            launcher_pin=self.manager_t.pin, state_root=self.state, requested_model='claude-haiku-5-5',
            requested_reasoning='medium', transport=self.worker_t, roles=('worker', 'manager'),
            manager_transport=self.manager_t, native_caller_socket=self.root + '/caller.sock',
            native_process_observer=observer)
        self.app = self.f.owner.execution_application(due_port=self.f.port, adapter=self.adapter,
            clock=lambda: owner_fixture.NOW, manager_actor='manager',
            native_result_verifier=ClaudeNativeResultVerifier())
        self.f.app = self.app
        self.assignment, self.guide, self.mandate = self.f.role_handles('manager', 'manager', None)

    def role(self, **extra):
        return dict(role='manager', project_ref=self.f.project.ref.to_dict(), task_ref=self.f.task.ref.to_dict(),
                    assignment_ref=self.assignment.ref.to_dict(), generation=1, mandate_ref=self.mandate,
                    context_refs=(self.guide, self.mandate), request_key='haiku-manager-turn',
                    instruction='Read the project status and plan the next task.', model='claude-haiku-5-5',
                    reasoning='medium', profile='workspace-write', **extra)

    def run_on_host(self, schedule_id, configure_host=None):
        import threading
        from otto.portfolio.execution_host import ExecutionHost

        host = ExecutionHost(directory=Path(self.root) / "manager-owner-ipc",
            handler=lambda _request: None, bounded_transports=True,
            capacity_store=self.f.store)
        host.start()
        self.addCleanup(host.close)
        if configure_host is not None:
            configure_host(host)
        completed = threading.Event()
        observed = {}
        launched = host._owner_request(lambda: self.app.start(schedule_id=schedule_id))
        launched.then(lambda value: (observed.update(value), completed.set()),
                      lambda error: (observed.update(raised=repr(error)), completed.set()))
        completed.wait()
        return observed, host

    def test_initializer_pin_is_durable_and_empty_before_work_launch(self):
        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        schedule = prepared['schedule_id']
        original_factory = self.manager_t.process_factory
        owner = []
        observed = []

        def factory(command, **kwargs):
            if self.manager_t.processes:
                initializer = self.manager_t.processes[0]
                host = owner[0]
                record = host._process_groups.get(schedule)
                saved = json.loads((host.directory / "capacity-process-groups.json").read_text())
                try:
                    os.killpg(initializer.pid, 0)
                except ProcessLookupError:
                    empty = True
                else:
                    empty = False
                observed.append((record, saved.get(schedule), empty))
            return original_factory(command, **kwargs)

        self.manager_t.process_factory = factory
        result, host = self.run_on_host(schedule, configure_host=owner.append)
        self.assertEqual(result['outcome'], 'succeeded', result.get('error'))
        self.assertEqual(len(observed), 1)
        memory, durable, empty = observed[0]
        self.assertEqual(memory, durable)
        self.assertEqual(memory['pid'], self.manager_t.processes[0].pid)
        self.assertTrue(empty)
        self.assertEqual(host._process_groups, {})

    def test_manager_role_is_declared_and_default_composition_stays_a_leaf(self):
        self.adapter.validate_owner_host_composition(role='manager', profile='workspace-write')
        self.assertEqual(self.adapter.capabilities()['manager']['state'], 'unverified')
        leaf = ClaudeWorkerAdapter(owner='w', source=self.root, worktree=self.root, launcher_pin=self.worker_t.pin,
            state_root=self.state, requested_model='claude-haiku-5-5', transport=self.worker_t)
        self.assertEqual(leaf.capabilities()['manager']['state'], 'unsupported')
        self.assertNotIn('roles', leaf.pins())
        with self.assertRaises(ClaudeBindingError):
            leaf.validate_owner_host_composition(role='manager', profile='workspace-write')
        with self.assertRaises(ClaudeBindingError):
            ClaudeWorkerAdapter(owner='w', source=self.root, worktree=self.root, launcher_pin=self.worker_t.pin,
                state_root=self.state, requested_model='m', transport=self.worker_t, roles=('coordinator',))
        with self.assertRaises(ClaudeBindingError):
            ClaudeCliTransport(self.worker_t.pin, SyntheticScope(self.root, self.state, subprocesses=False),
                               model='m', reasoning='high', tools=MANAGER_TOOLS)

    def test_existing_manager_still_requires_its_native_session_without_fresh_opt_in(self):
        with self.assertRaisesRegex(Exception, 'existing native session'):
            self.app.prepare_role(**self.role())

    def test_fresh_haiku_manager_preview_is_inert_and_setup_ready(self):
        counts = self.f.store.consumer().snapshot_counts()
        preview = self.app.prepare_role(**self.role(fresh_manager=True), preview=True)
        self.assertEqual(preview['due']['execution_mode'], 'fresh_manager')
        self.assertIsNone(self.f.port.read_due(preview['schedule_id']))
        setup = {'schema': SCHEMA, 'mode': 'manual',
                 'roles': {'manager': {'assignment_ref': self.assignment.ref.to_dict(), 'generation': 1,
                                       'task_ref': self.f.task.ref.to_dict(), 'mandate_ref': self.mandate,
                                       'model': 'claude-haiku-5-5', 'reasoning': 'medium', 'fresh_manager': True}},
                 'advisor_policy': {'mode': 'disabled', 'reason': 'The orchestrator supervises'},
                 'acceptance_tasks': []}
        composed = self.app.compose_operating_setup(project_ref=self.f.project.ref.to_dict(), operation='preview',
                                                    setup=setup, request_key='haiku-setup')
        self.assertEqual(composed['outcome'], 'preview', composed)
        self.assertTrue(composed['readiness']['ready'], composed['readiness']['blockers'])
        self.assertEqual(composed['readiness']['roles']['manager']['conversation_binding_source'],
                         'fresh_manager_first_launch')
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        self.assertEqual(self.manager_t.calls + self.worker_t.calls, [])

    def test_fresh_haiku_manager_is_admitted_with_manager_tools_and_registered_process(self):
        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        result, host = self.run_on_host(prepared['schedule_id'])
        self.assertEqual(result['outcome'], 'succeeded', result)
        self.assertEqual(len(self.manager_t.calls), 2)
        self.assertEqual(self.worker_t.calls, [])
        work = self.manager_t.calls[-1]
        self.assertEqual(work[work.index('--tools') + 1], ','.join(MANAGER_TOOLS))
        self.assertIn('Bash', work[work.index('--allowedTools') + 1:])
        self.assertEqual(self.manager_t.calls[0][self.manager_t.calls[0].index('--tools') + 1], '')
        due = self.f.port.read_due(prepared['schedule_id'])
        admission = due['host_evidence']['gateway_attempt']['delivery_admission']
        self.assertEqual(admission['physical_session_id'], 'manager-native-session')
        self.assertEqual(self.observed[0][1:], ('manager', 'manager-native-session'))
        self.assertEqual(self.observed[-1], 'cleanup')
        self.assertEqual(self.app.start(schedule_id=prepared['schedule_id'])['outcome'], 'replayed')
        self.assertEqual(len(self.manager_t.calls), 2)

    def test_pin_write_failure_stops_initializer_before_input_and_releases_slot(self):
        import threading
        from otto.portfolio.execution_host import ExecutionHost

        host = ExecutionHost(
            directory=Path(self.root) / "pin-failure-ipc",
            handler=lambda _request: None,
            bounded_transports=True,
            capacity_store=self.f.store,
        )
        host.start()
        self.addCleanup(host.close)
        (host.directory / "capacity-process-groups.json").mkdir()

        input_marker = Path(self.root) / "native-input-received"
        processes = []
        model = (
            "import pathlib,sys\n"
            "line=sys.stdin.buffer.readline()\n"
            "if line: pathlib.Path(sys.argv[1]).write_bytes(line)\n"
        )

        def factory(_command, **kwargs):
            process = subprocess.Popen(
                [sys.executable, "-c", model, str(input_marker)], **kwargs
            )
            processes.append(process)
            return process

        self.manager_t.process_factory = factory
        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        launched = host._owner_request(
            lambda: self.app.start(schedule_id=prepared["schedule_id"])
        )
        completed = threading.Event()
        observed = {}

        def capture(value):
            observed.update(value)
            completed.set()

        def failed(error):
            observed["raised"] = repr(error)
            completed.set()

        launched.then(capture, failed)
        completed.wait()

        self.assertEqual(observed.get("outcome"), "failed", observed)
        self.assertEqual(len(processes), 1)
        self.assertFalse(input_marker.exists())
        self.assertIsNotNone(processes[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(processes[0].pid, 0)

        due = self.f.port.read_due(prepared["schedule_id"])
        self.assertEqual((due["stop_state"], due["completion_state"]),
                         ("completed", "failed"))
        self.assertEqual(due["host_evidence"]["gateway_attempt"]["result"]["outcome"],
                         "failed")
        self.assertEqual(host._process_groups, {})
        self.assertEqual(host.capacity_holds(), {})
        self.assertEqual(host.capacity.snapshot()["pool"]["held_units"], 0)

        restarted = ExecutionHost(
            directory=host.directory,
            handler=lambda _request: None,
            bounded_transports=True,
            capacity_store=self.f.store,
        )
        restarted.restore_execution(self.app, self.app._read(prepared["schedule_id"]))
        self.assertEqual(restarted.capacity_holds(), {})
        self.assertEqual(restarted.capacity.snapshot()["pool"]["held_units"], 0)

    def test_work_pin_failure_keeps_initializer_record_and_releases_empty_slot(self):
        from otto.portfolio import execution_host

        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        schedule = prepared['schedule_id']
        original_factory = self.manager_t.process_factory
        work = []
        collision = []
        initializer_record_at_collision = []
        input_marker = Path(self.root) / 'work-input-received'
        model = ('import pathlib,sys\n'
                 'line=sys.stdin.buffer.readline()\n'
                 'if line: pathlib.Path(sys.argv[1]).write_bytes(line)\n')

        def factory(command, **kwargs):
            if self.manager_t.processes:
                # The initializer's pin is already durable. The real writer's
                # exclusive temp-file create now fails for the work pin.
                prior = json.loads(collision[0].with_name('capacity-process-groups.json').read_text())
                initializer_record_at_collision.append(prior[schedule]['pid'])
                collision[0].touch(exist_ok=False)
                process = subprocess.Popen([sys.executable, '-c', model, str(input_marker)], **kwargs)
                work.append(process)
                return process
            return original_factory(command, **kwargs)

        self.manager_t.process_factory = factory

        def configure_host(host):
            path = host.directory / '.capacity-process-groups.json.tmp'
            collision.append(path)
            self.addCleanup(path.unlink, missing_ok=True)

        result, host = self.run_on_host(schedule, configure_host=configure_host)
        saved = json.loads((host.directory / 'capacity-process-groups.json').read_text())
        self.assertEqual(initializer_record_at_collision, [self.manager_t.processes[0].pid])
        self.assertEqual(saved[schedule]['pid'], self.manager_t.processes[0].pid)
        self.assertTrue(collision[0].is_file())
        self.assertEqual(result['outcome'], 'failed', result.get('error'))
        self.assertEqual(host._process_groups, {})
        self.assertEqual(len(work), 1)
        self.assertFalse(input_marker.exists())
        self.assertIsNotNone(work[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(work[0].pid, 0)
        due = self.f.port.read_due(schedule)
        self.assertEqual((due['stop_state'], due['completion_state']), ('completed', 'failed'))
        self.assertEqual(host.capacity_holds(), {})
        collision[0].unlink()
        restarted = execution_host.ExecutionHost(directory=host.directory,
            handler=lambda _request: None, bounded_transports=True,
            capacity_store=self.f.store)
        restarted.restore_execution(self.app, self.app._read(schedule))
        self.assertEqual(restarted.capacity_holds(), {})
        self.assertEqual(restarted._process_groups, {})

    def test_restore_settles_retained_pre_input_registration_failure(self):
        from otto.portfolio.execution_host import ExecutionHost

        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        schedule = prepared['schedule_id']
        # Exercise the missing-owner registration failure without the direct
        # launch host, leaving its exact Due for restore to settle.
        self.app._direct_host_directory = None
        result = self.app.start(schedule_id=schedule, settle=False)
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['error']['code'],
                         'claude_process_registration_failed_before_input')
        self.assertEqual(self.f.port.read_due(schedule)['stop_state'], 'active')
        host = ExecutionHost(directory=Path(self.root) / 'registration-restart-ipc',
            handler=lambda _request: None, bounded_transports=True,
            capacity_store=self.f.store)
        host.restore_execution(self.app, self.app._read(schedule))
        due = self.f.port.read_due(schedule)
        self.assertEqual((due['stop_state'], due['completion_state']), ('completed', 'failed'))
        self.assertEqual(host.capacity_holds(), {})

    def test_retained_registration_failure_keeps_live_recorded_group_held(self):
        import signal
        from otto.portfolio.execution_host import ExecutionHost

        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        schedule = prepared['schedule_id']
        self.app._direct_host_directory = None
        result = self.app.start(schedule_id=schedule, settle=False)
        self.assertEqual(result['error']['code'],
                         'claude_process_registration_failed_before_input')
        due = self.app._read(schedule)
        host = ExecutionHost(directory=Path(self.root) / 'live-init-ipc',
            handler=lambda _request: None, bounded_transports=True,
            capacity_store=self.f.store)
        host._capacity_holds[schedule] = host._execution_scope(self.app, due)
        process = subprocess.Popen(['sleep', '60'], start_new_session=True)
        try:
            host.record_process_group(schedule, process.pid)
            host.restore_execution(self.app, due)
            self.assertEqual(self.f.port.read_due(schedule)['stop_state'], 'active')
            self.assertIn(schedule, host.capacity_holds())
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            host.restore_execution(self.app, self.app._read(schedule))
            settled = self.f.port.read_due(schedule)
            self.assertEqual((settled['stop_state'], settled['completion_state']),
                             ('completed', 'failed'))
            self.assertEqual(host.capacity_holds(), {})
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

    def test_child_exiting_before_stdin_keeps_unknown_with_exit_and_stderr(self):
        def exited_child(command, **kwargs):
            process = subprocess.Popen([sys.executable, '-c',
                "import sys; sys.stderr.write('early child failure\\n'); sys.exit(37)"], **kwargs)
            process.wait(timeout=5)
            return process

        self.worker_t.process_factory = exited_child
        with self.assertRaisesRegex(ClaudeBindingError,
                r'child exited before stdin was accepted \(exit status 37\); stderr tail: early child failure'):
            self.worker_t.run('x' * 50_000)

    def test_owner_launch_refuses_to_pin_exited_child_before_input(self):
        def exited_child(command, **kwargs):
            process = subprocess.Popen([sys.executable, '-c',
                "import sys; sys.stderr.write('early child failure\\n'); sys.exit(37)"], **kwargs)
            process.wait(timeout=5)
            return process

        self.manager_t.process_factory = exited_child
        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        result, host = self.run_on_host(prepared['schedule_id'])
        self.assertEqual(result['outcome'], 'failed', result.get('error'))
        self.assertEqual(result['result']['error']['code'],
                         'claude_process_registration_failed_before_input')
        due = self.f.port.read_due(prepared['schedule_id'])
        attempt = due['host_evidence']['gateway_attempt']
        self.assertEqual(attempt['result']['outcome'], 'failed')
        self.assertEqual((due['stop_state'], due['completion_state']), ('completed', 'failed'))
        self.assertEqual(host.capacity_holds(), {})

    def test_project_dispatch_projection_preserves_unknown_and_launched(self):
        from otto.hostctl.cli import _task_dispatch_status

        observed = {
            'assignments': [{'ref': {'id': 'assignment-1'}}],
            'dispatches': [{'payload': {'assignment': {'id': 'assignment-1'}, 'status': 'dispatched'}}],
            'results': [],
            'reports': [{'payload': {'assignment': {'id': 'assignment-1'}, 'value': {
                'state': 'unknown', 'reason': 'child exit status 37; stderr tail: early child failure'}}}],
        }
        self.assertEqual(_task_dispatch_status(observed), {
            'state': 'unknown', 'reason': 'child exit status 37; stderr tail: early child failure'})
        observed['reports'] = []
        self.assertEqual(_task_dispatch_status(observed), {'state': 'launched', 'reason': None})

    def test_leaf_composition_refuses_the_manager_occurrence_before_any_process(self):
        leaf = ClaudeWorkerAdapter(owner='manager', source=self.root, worktree=self.root,
            launcher_pin=self.worker_t.pin, state_root=self.state, requested_model='claude-haiku-5-5',
            requested_reasoning='medium', transport=self.worker_t)
        app = self.f.owner.execution_application(due_port=self.f.port, adapter=leaf, manager_actor='manager',
            clock=lambda: owner_fixture.NOW, native_result_verifier=ClaudeNativeResultVerifier())
        prepared = app.prepare_role(**self.role(fresh_manager=True))
        result = app.start(schedule_id=prepared['schedule_id'])
        self.assertNotEqual(result['outcome'], 'succeeded')
        self.assertEqual(self.worker_t.calls, [])


@unittest.skipUnless(sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').exists(), 'macOS fence')
class ManagerFenceTests(unittest.TestCase):
    def test_child_processes_run_and_inherit_the_write_fence(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as state:
            scope = MacWriteScope(workspace, state, allow_subprocesses=True)
            proof = scope.preflight()
            self.assertTrue(proof['verified'])
            self.assertTrue(proof['subprocesses'])
            self.assertIn('child process', proof['proof'])
            leaf = MacWriteScope(workspace, state)
            self.assertNotIn('subprocesses', leaf.pin)
            self.assertIn('(deny process-exec)', leaf.policy)
            self.assertNotIn('(deny process-exec)', scope.policy)


if __name__ == '__main__':
    unittest.main()
