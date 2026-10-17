"""Owner/Due/gateway/capture, runner, facade, and Git rework journey.

The Claude process and landing assessment policy are test fixtures.
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from herzchen.fleet.landing import LandingError
from herzchen.fleet.labs import LabFleet
from herzchen.fleet.capacity import CapacityPolicy
from herzchen.fleet.hosts.contract import McpGrant, McpServer
from herzchen.fleet.runner.store import ResultStore
from herzchen.fleet.tools import CHECK, FeedbackLedger, TokenBook, ToolFacade, ToolSpec
from herzchen.fleet.tools.facade import LandingOwnerPort
from herzchen.fleet.tools.server import FacadeServer
from otto.agents.claude_adapter import ClaudeNativeResultVerifier, ClaudeWorkerAdapter
from otto.agents.claude_cli import ClaudeCliTransport, LauncherPin, VERSION, WORKER_TOOLS, TOOL_SPECS, file_digest
from otto.hostctl.product_service import OwnerFleetRegistry, _OwnerExecutorPort
from otto.hostctl.fleet_landing import compose_runner
from otto.portfolio.manager_journey_service import ManagerJourneyService

import test_execution_application as owner_fixture
import test_landing as landing_fixture
from test_claude_manager_admission import SyntheticScope


NATIVE = r"""
import json,os,socket,sys
from pathlib import Path
frame=json.loads(sys.stdin.readline()); prompt=frame['message']['content'][0]['text']
session=frame.get('session_id') or 'native-worker-session'; init=prompt.startswith('Initialize this session only.')
cwd=os.getcwd(); phase='init' if init else ('second' if Path(os.environ['OTTO_TRACE_PATH']).exists() else 'first')
tools=[] if init else ['Edit','Glob','Grep','Read','Write','mcp__otto__task','mcp__otto__check','mcp__otto__done']
def emit(event): print(json.dumps(event),flush=True)
emit({'type':'system','subtype':'init','session_id':session,'cwd':cwd,'model':'claude-haiku-5-5',
 'permissionMode':'bypassPermissions' if init else 'dontAsk','tools':tools,
 'mcp_servers':[] if init else ['otto'],'plugins':[],'skills':[],'slash_commands':[]})
emit({'type':'user','uuid':'input-'+phase,'session_id':session,
 'message':{'role':'user','content':[{'type':'text','text':prompt}]}})
if not init:
 path=str(Path(cwd)/'shared.txt')
 content=('worker change\n' if phase=='first' else
          Path(path).read_text() if os.environ.get('OTTO_LEAVE_MARKERS')=='1' else
          'line change\nworker change\n')
 Path(path).write_text(content)
 emit({'type':'assistant','uuid':'write-'+phase,'session_id':session,
  'message':{'role':'assistant','model':'claude-haiku-5-5','content':[
   {'type':'tool_use','id':'write-'+phase,'name':'Write','input':{'file_path':path,'content':content}}]}})
 emit({'type':'user','uuid':'write-result-'+phase,'session_id':session,
  'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'write-'+phase,
   'is_error':False,'content':'written'}]}})
 emit({'type':'assistant','uuid':'done-'+phase,'session_id':session,
  'message':{'role':'assistant','model':'claude-haiku-5-5','content':[
   {'type':'tool_use','id':'done-'+phase,'name':'mcp__otto__done','input':{}}]}})
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
  sock.connect(os.environ['OTTO_FACADE_SOCKET'])
  sock.sendall((json.dumps({'op':'call','token':os.environ['OTTO_WORKER_TOKEN'],
   'tool':'done','args':{}})+'\n').encode())
  reply=json.loads(sock.makefile().readline())
 with open(os.environ['OTTO_TRACE_PATH'],'a') as trace:
  trace.write(json.dumps({'phase':phase,'cwd':cwd,'session_id':session,'admitted_prompt':prompt,
   'done_reply':reply})+'\n')
 emit({'type':'user','uuid':'done-result-'+phase,'session_id':session,
  'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'done-'+phase,
   'is_error':not reply['ok'],'content':json.dumps(reply)}]}})
 if os.environ.get('OTTO_UNKNOWN_FIRST')=='1' and phase=='first': sys.exit(0)
emit({'type':'result','subtype':'success','is_error':False,'session_id':session,
 'uuid':'result-'+phase,'result':'READY' if init else 'Worker turn complete.',
 'usage':{'input_tokens':21,'output_tokens':9}})
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
        capture_output=True, text=True).stdout.strip()


class ReworkOwner:
    def __init__(self, root: Path, fixture: owner_fixture.ExecutionApplicationTests):
        self.f, self.root = fixture, root
        self.line = root / 'line'; self.line.mkdir()
        git(self.line, 'init', '-b', 'main')
        git(self.line, 'config', 'user.name', 'REWORKWIRE test')
        git(self.line, 'config', 'user.email', 'rework@test.invalid')
        (self.line / 'shared.txt').write_text('base\n')
        git(self.line, 'add', 'shared.txt'); git(self.line, 'commit', '-m', 'base')
        def checkpoint(worktree, paths, *, message):
            path = Path(worktree)
            git(path, 'add', '--', *paths)
            git(path, '-c', 'user.name=REWORKWIRE test', '-c', 'user.email=rework@test.invalid',
                'commit', '-m', message)
        self.fleet = LabFleet(self.line, root / 'labs', checkpoint=checkpoint)
        self.lab = self.fleet.create(self.f.task.id, base='refs/heads/main')
        git(self.lab.path, 'config', 'user.name', 'REWORKWIRE test')
        git(self.lab.path, 'config', 'user.email', 'rework@test.invalid')
        (self.line / 'shared.txt').write_text('line change\n')
        git(self.line, 'add', 'shared.txt'); git(self.line, 'commit', '-m', 'advance line')
        self.line_head_before = git(self.line, 'rev-parse', 'HEAD')
        self.check_failure = root / 'check-fails'
        check_script = root / 'check.py'
        check_script.write_text('import pathlib,sys\nsys.exit(1 if pathlib.Path(sys.argv[1]).exists() else 0)\n')
        self.result_store = ResultStore(root / 'runner-results')
        self.runner_lifecycle = compose_runner(root / 'runner-home', self.result_store, CapacityPolicy())
        self.runner_lifecycle.start()
        class RunnerView:
            def call(_, request):
                return self.runner_lifecycle.client.call(request)
            def lookup(_, run_id):
                return self.result_store.get(run_id)
        self.runner = RunnerView()
        task = landing_fixture._admitted_task(argv=(sys.executable, str(check_script), str(self.check_failure)))
        self.landing, _ = landing_fixture._service(self.fleet, self.runner, task=task)
        self.trace_path = root / 'native-trace.jsonl'
        self.ipc = tempfile.TemporaryDirectory(prefix='rw-', dir='/private/tmp')
        self.socket_path = str(Path(self.ipc.name) / 'f.sock')
        state = root / 'state'; state.mkdir()
        executable = str(Path(sys.executable).resolve())
        pin = LauncherPin(executable, executable, file_digest(Path(executable)), VERSION)
        self.commands = []
        def factory(command, **kwargs):
            self.commands.append(list(command))
            return subprocess.Popen([sys.executable, '-c', NATIVE, *command], **kwargs)
        self.transport = ClaudeCliTransport(pin, SyntheticScope(str(self.lab.path), str(state), subprocesses=False),
            model='claude-haiku-5-5', reasoning='medium', timeout_seconds=15,
            process_factory=factory, tools=WORKER_TOOLS,
            extra_env={'OTTO_FACADE_SOCKET': self.socket_path, 'OTTO_TRACE_PATH': str(self.trace_path)})
        self.adapter = ClaudeWorkerAdapter(owner='worker', source=str(self.lab.path),
            worktree=str(self.lab.path), launcher_pin=pin, state_root=str(state),
            requested_model='claude-haiku-5-5', requested_reasoning='medium', transport=self.transport)
        self.app = self.f.owner.execution_application(due_port=self.f.port, adapter=self.adapter,
            clock=lambda: owner_fixture.NOW, manager_actor='manager',
            native_result_verifier=ClaudeNativeResultVerifier())
        request = self.f.request()
        request.update(model='claude-haiku-5-5', reasoning='medium')
        request['instruction_contract']['authority']['workspace_roots'] = [str(self.lab.path)]
        self.prepared = self.app.assign_worker(**request)
        self.schedule = self.prepared['schedule_id']
        due = self.f.port.read_due(self.schedule)
        assignment = due['assignment_ref']
        book = TokenBook(); token = book.issue(assignment['id'], 'worker')
        self.transport.mcp = McpGrant(servers=(McpServer(name='otto', command=executable,
            tools=('task', 'check', 'done')),), token_env='OTTO_WORKER_TOKEN', token=token,
            token_env_prefix='OTTO_WORKER_')
        registry = object.__new__(OwnerFleetRegistry)
        registry.due_port = self.f.port
        registry._lock = threading.RLock()
        registry._active_due = {assignment['id']: self.schedule}
        context = {'service': self.landing, 'lab_name': self.f.task.id,
            'task_id': self.f.task.id, 'assignment_id': assignment['id'],
            'assignment_ref': assignment, 'generation': due['generation'],
            'task_ref': due['target']['task_ref'], 'workspace': str(self.lab.path),
            'candidate': 'candidate@1', 'criterion': landing_fixture._criterion(),
            'parent_obligation': 'obligation@1', 'actor': 'owner'}
        registry.assignment_context = lambda _assignment: context
        self.registry = registry
        owned = _OwnerExecutorPort(LandingOwnerPort(registry.assignment_context),
            lambda: lambda callback: callback(), lambda _assignment: None,
            registry.retain_landing_refusal)
        self.facade = ToolFacade(TOOL_SPECS, {'worker': ('task', 'check', 'done')},
            owned, book, FeedbackLedger())
        self.server = FacadeServer(self.facade, self.socket_path)
        self.server.start()

    def run(self, *, unknown_first=False, second_conflict=False,
            second_unresolved=False, fail_refusal_write=False):
        self.transport.extra_env['OTTO_UNKNOWN_FIRST'] = '1' if unknown_first else '0'
        self.transport.extra_env['OTTO_LEAVE_MARKERS'] = '1' if second_unresolved else '0'
        save_due = type(self.f.port).save_due
        if fail_refusal_write:
            def reject_refusal(port, *args, **kwargs):
                if str(kwargs.get('request_id', '')).startswith('worker-landing-refusal:'):
                    raise RuntimeError('test CAS failure')
                return save_due(port, *args, **kwargs)
        boundary = (patch.object(type(self.f.port), 'save_due', reject_refusal)
                    if fail_refusal_write else nullcontext())
        with boundary:
            first_result = self.app.start(schedule_id=self.schedule)
        first_due = self.f.port.read_due(self.schedule)
        after_first = {'line_head': git(self.line, 'rev-parse', 'HEAD'),
                       'lab_exists': self.lab.path.exists()}
        next_id = None
        if (first_result['outcome'] == 'succeeded'
                and (first_due['host_evidence'] or {}).get('landing_refusal')):
            prepared = self.app.rework_worker(schedule_id=self.schedule, execute=False)
            next_id = prepared['schedule_id']
            self.registry._active_due[first_due['assignment_ref']['id']] = next_id
            self.landing.prepare_rework(self.f.task.id)
            if second_conflict:
                self.check_failure.touch()
            self.app.start(schedule_id=next_id)
        turns = [json.loads(line) for line in self.trace_path.read_text().splitlines()]
        work_commands = [command for command in self.commands if '--resume' in command or
                         '--tools' in command and command[command.index('--tools') + 1] != '']
        for index, turn in enumerate(turns):
            turn['argv'] = work_commands[index]
            due = self.f.port.read_due(self.schedule if index == 0 else next_id)
            turn['authorization'] = due['host_evidence']['gateway_attempt']['delivery_authorization']
            if turn['done_reply']['ok']:
                turn['landed_commit'] = turn['done_reply']['result']['commit']
        if turns[0]['done_reply']['ok'] is False:
            turns[0]['rebase_message'] = turns[0]['done_reply']['detail']
        captured_second = bool(next_id and (self.f.port.read_due(next_id)['host_evidence'] or {}).get('captured_artifacts'))
        if captured_second and turns[-1]['done_reply']['ok']:
            self.fleet.sweep_landed('refs/heads/main', lambda name, _commit: name == self.f.task.id)
        return {'work_turns': turns, 'after_first': after_first,
            'line_head_before': self.line_head_before, 'lab_path': str(self.lab.path),
            'captured_second_write': captured_second, 'lab_exists_after_capture': self.lab.path.exists(),
            'final_line_head': git(self.line, 'rev-parse', 'HEAD'),
            'first_result': first_result, 'second_schedule_id': next_id}

    def close(self):
        self.server.stop()
        self.runner_lifecycle.close()
        self.ipc.cleanup()


@pytest.fixture
def rework_owner(tmp_path):
    fixture = owner_fixture.ExecutionApplicationTests(); fixture.setUp()
    owner = ReworkOwner(tmp_path, fixture)
    try:
        yield owner
    finally:
        owner.close(); fixture.doCleanups()


def test_landing_refusal_has_stable_code_and_unknown_default():
    refusal = LandingError('rebase conflict; lab returned to worker')
    assert refusal.code == 'landing_refused'
    assert refusal.message == str(refusal)
    assert refusal.settled is None


def test_worker_check_reports_refusal_without_retaining_landing():
    class CheckOnly:
        def check(self, _lab, _task):
            raise LandingError('admitted check unavailable')
    book = TokenBook(); token = book.issue('assignment-check', 'worker')
    retained = []
    owned = _OwnerExecutorPort(LandingOwnerPort(lambda _assignment: {
        'service': CheckOnly(), 'lab_name': 'lab', 'task_id': 'task'}),
        lambda: lambda callback: callback(), lambda _assignment: None,
        lambda *_args: retained.append(True))
    facade = ToolFacade((ToolSpec('check', CHECK, 'worker-check'),),
        {'worker': ('check',)}, owned, book, FeedbackLedger())
    assert facade.call(token, 'check') == {
        'ok': False, 'error': 'landing_refused', 'detail': 'admitted check unavailable'}
    assert retained == []


def test_conflicting_done_reworks_exact_worker(rework_owner):
    trace = rework_owner.run()
    first, second = trace['work_turns']
    assert first['done_reply'] == {'ok': False, 'error': 'landing_refused',
                                   'detail': first['rebase_message']}
    assert 'rebase conflict' in first['rebase_message']
    assert trace['after_first']['line_head'] == trace['line_head_before']
    assert trace['after_first']['lab_exists'] is True
    assert len(trace['work_turns']) == 2
    assert second['session_id'] == first['session_id']
    assert second['cwd'] == first['cwd'] == trace['lab_path']
    assert second['argv'][-2:] == ['--resume', first['session_id']]
    assert first['rebase_message'] in second['admitted_prompt']
    assert second['authorization'] != first['authorization']
    assert second['done_reply']['ok'] is True
    assert second['done_reply']['result']['landed'] is True
    assert trace['captured_second_write'] is True
    assert trace['lab_exists_after_capture'] is False
    assert trace['final_line_head'] == second['landed_commit']


def test_unknown_native_after_refusal_never_resumes(rework_owner):
    trace = rework_owner.run(unknown_first=True)
    assert len(trace['work_turns']) == 1
    assert trace['first_result']['outcome'] == 'unknown'
    assert rework_owner.f.port.read_due(rework_owner.schedule)['host_evidence']['landing_refusal']['settled'] is True
    with pytest.raises(ValueError, match='captured, settled refusal'):
        rework_owner.app.rework_worker(schedule_id=rework_owner.schedule)
    assert trace['after_first']['lab_exists'] is True
    assert trace['final_line_head'] == trace['line_head_before']


def test_second_refusal_exhausts_rework_bound(rework_owner):
    trace = rework_owner.run(second_conflict=True)
    assert len(trace['work_turns']) == 2
    assert trace['work_turns'][1]['done_reply']['ok'] is False
    assert trace['work_turns'][1]['session_id'] == trace['work_turns'][0]['session_id']
    with pytest.raises(ValueError, match='captured, settled refusal'):
        rework_owner.app.rework_worker(schedule_id=trace['second_schedule_id'])
    assert trace['lab_exists_after_capture'] is True
    assert trace['final_line_head'] == trace['line_head_before']


def test_failed_refusal_cas_leaves_rework_unknown(rework_owner):
    trace = rework_owner.run(fail_refusal_write=True)
    assert len(trace['work_turns']) == 1
    assert trace['work_turns'][0]['done_reply']['error'] == 'landing_refused'
    assert 'landing_refusal' not in rework_owner.f.port.read_due(rework_owner.schedule)['host_evidence']
    with pytest.raises(ValueError, match='captured, settled refusal'):
        rework_owner.app.rework_worker(schedule_id=rework_owner.schedule)


def test_unresolved_conflict_markers_do_not_land(rework_owner):
    trace = rework_owner.run(second_unresolved=True)
    assert len(trace['work_turns']) == 2
    assert trace['work_turns'][1]['done_reply']['error'] == 'landing_refused'
    assert 'conflict markers' in trace['work_turns'][1]['done_reply']['detail']
    assert trace['final_line_head'] == trace['line_head_before']


def test_owner_routes_manager_result_only_after_rework_due():
    service = ManagerJourneyService.__new__(ManagerJourneyService)
    service.commands = SimpleNamespace(_authorize=lambda: None)
    worker = {'schedule_id': 'first-due', 'principal': 'worker', 'model': 'm', 'reasoning': 'high'}
    state = {'workers': {'task': worker}, 'worker_history': {}}
    first = {'target': {'launch_request': {}}, 'host_evidence': {'landing_refusal': {
        'schema': 'otto.worker-landing-refusal.v1', 'settled': True, 'outcome': 'conflict'}}}
    second = {'target': {'launch_request': {}, 'worker_rework': {'schema': 'otto.worker-rework.v1'}},
              'host_evidence': {}}
    dues = {'first-due': first, 'second-due': second}
    events = []
    service.server = SimpleNamespace(state=state,
        due_port=SimpleNamespace(read_due=lambda schedule: dues[schedule]),
        worker_context_provider=lambda _due: {'landing': SimpleNamespace(
            prepare_rework=lambda _lab: events.append('prepared-conflict')), 'lab_name': 'lab'},
        _save_state=lambda: events.append('saved-current-worker'))
    service.host = SimpleNamespace(_closing=False,
        submit=lambda request: (events.append(('manager-result', request['schedule_id']))
                                or {'outcome': 'prepared'}))
    service._current_manager_schedule = lambda: 'manager-due'
    service._settle_shared_completion = lambda result, **_kwargs: {**result, 'completion_intents': []}
    first_app = SimpleNamespace(
        synchronize_manual_manager_occurrence=lambda **_kwargs: None,
        start=lambda **_kwargs: {'outcome': 'succeeded'},
        rework_worker=lambda **_kwargs: {'schedule_id': 'second-due'})
    second_app = SimpleNamespace(start=lambda **_kwargs: (events.append('started-rework')
                                                          or {'outcome': 'succeeded'}))
    service._execution = lambda **options: (first_app if options['evidence_id'] == 'first-due' else second_app)
    result = service({'command': 'start-retained-worker', 'task': 'task',
                      'principal': 'worker', 'schedule_id': 'first-due'})
    assert result['outcome'] == 'succeeded'
    assert state['workers']['task']['schedule_id'] == 'second-due'
    assert events == ['prepared-conflict', 'saved-current-worker', 'started-rework',
                      ('manager-result', 'second-due')]
