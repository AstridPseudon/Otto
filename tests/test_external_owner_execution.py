"""Real owner-store joins with a synthetic provider; not installed-host proof."""
import copy
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from herzchen.contracts import ResourceRef
from otto.portfolio.external_owner_execution import OwnerExecutionIngress
from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
from otto.portfolio.execution_host import _nested_capability, _starts_work
from otto.portfolio.occurrence_reads import handle
from otto.portfolio.resource_sync import normalize_instruction_contract
from otto.portfolio.tests import test_worker_occurrences as fixtures
from otto.portfolio.identity_context import HostIngress

class ExternalOwnerExecutionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkerOccurrenceTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.yield_parent()
        self.s = self.f.service
        owner = self.f.server.owner
        root = owner.assignments.assign(ResourceRef(self.f.f.store.authority, 'wrk.portfolio', 'external-root'),
            role='orchestrator', principal=owner.owner_actor.actor, logical_request_key='external-root')
        root = owner.assignments.adopt_resources(root.ref, resources=self.f.manager.payload['resource_adoptions'],
            expected_revision=root.revision, expected_generation=1, logical_request_key='external-root-base', actor=owner.owner_actor)
        self.root = root
        self.f.server.state['orchestrator_assignment_ref'] = root.ref.to_dict()
        self.f.config['worker_operation_profiles'] = {}
        (self.f.run/'run.yaml').write_text(json.dumps(self.f.config))
        self.ingress = OwnerExecutionIngress(actor=owner.owner_actor,owner_actor=owner.owner_actor,directory=self.f.root/'root-ipc')
        self.s.external_execution_authorizer = self.ingress.authorize
        self.s.external_execution_policy = {'root_assignment_ref':root.ref.to_dict(),'generation':1,
            'project_ref':self.f.server.state['project_ref'],'task_ref':self.f.server.state['task_refs']['D02'],
            'task':'D02','principal':'external-leaf','route':'normal','model':'gpt-test','reasoning':'high',
            'native_adapter':self.f.f.app.native_adapter_identity(),'max_launches':1,
            'worker_turn_allowance':6,'capacity_units':1,'max_depth':1,'operation_profile':'read_only_inspection'}
    def request(self,operation,**kwargs):
        return {'command':'owner-execution','operation':operation,'request_key':'root-'+operation,**kwargs}
    def call(self,operation,**kwargs):
        r=self.request(operation,**kwargs)
        self.ingress.publish({'schema':self.ingress.schema,'request':r})
        result = self.f.host._dispatch(r, ingress=HostIngress("file-ipc", self.f.host.directory/"external-owned"))
        if result.get("outcome") == "error":
            raise {"PermissionError": PermissionError, "ValueError": ValueError}.get(result["error"], RuntimeError)(result.get("message", str(result)))
        return result
    def launch(self,**kwargs):
        return self.call('launch',focus='Inspect the installed commands and return factual evidence only.',**kwargs)
    def test_launch_exact_parent_historical_reads_consumption_and_leaf_contract(self):
        calls=len(self.f.f.provider.calls)
        answer=self.launch();self.assertEqual(answer['outcome'],'admitted',answer)
        occurrence=answer['occurrence'];due=self.f.f.port.read_due(occurrence['schedule_id'])
        self.assertEqual(due['profile'],'read-only');self.assertEqual(due['target']['launch_request']['external_parent']['assignment_ref'],self.root.ref.to_dict())
        self.assertEqual(len(self.f.f.provider.calls),calls)
        from otto.portfolio.owner_readers import mandate_reader
        m=mandate_reader(self.f.f.app.portfolio.operations,due['target']['project_ref'],due['target']['mandate_ref'])({k:due['target']['mandate_ref'][k]for k in ('authority','kind','id')})
        c=m['payload']['instruction_contract'];normalize_instruction_contract(c)
        self.assertNotIn('delegation',c);self.assertEqual(c['read_scope'],'linked_context');self.assertIn('file_write',c['authority']['forbidden_effects'])
        self.assertEqual(c['objective'], due['target']['launch_request']['input']['focus'])
        self.assertEqual(c['objective'], c['bounded_operation'])
        self.assertNotIn('Adapter/D05', c['objective'])
        for op in ('result','follow'):
            v=self.call(op,occurrence=occurrence);self.assertTrue(v['pure']);self.assertFalse(v['required_capture'])
        counts=self.f.f.store.consumer().snapshot_counts()
        found=self.call('lookup',original_request_key='root-launch');self.assertEqual(found['occurrence'],occurrence)
        self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
        self.f.config['roles']['worker_normal']['model']='changed';(self.f.run/'run.yaml').write_text(json.dumps(self.f.config))
        repeat=self.launch();self.assertEqual(repeat['outcome'],'retained');self.assertEqual(len(self.f.f.provider.calls),calls)
        with self.assertRaises(ValueError):self.call('launch',focus='Changed intent')
        # Actual provider execution is synthetic in this test; capture goes through maintained owner parsing.
        result=self.f.f.app.start(schedule_id=due['schedule_id']);self.assertEqual(result['outcome'],'succeeded',result)
        consumed=self.call('consume',occurrence=occurrence);self.assertTrue(consumed['required_capture'],consumed)
        self.assertEqual(consumed['parent_delivery']['state'],'consumed')
        counts=self.f.f.store.consumer().snapshot_counts()
        for op in ('result','follow'):
            v=self.call(op,occurrence=occurrence);self.assertEqual(v['parent_delivery']['state'],'consumed')
            self.assertEqual(v['consumption_report_ref'],consumed['consumption_report_ref'])
            self.assertTrue(v['pure'])
        self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
        again=self.call('consume',occurrence=occurrence);self.assertEqual(consumed,again)
        self.assertEqual(consumed['external_parent']['result_destination']['assignment_ref'],self.root.ref.to_dict())
    def test_selected_host_composition_fails_before_canonical_admission(self):
        adapter=self.f.f.app.runtime.adapter
        adapter.native_caller_socket=str(self.f.root/'manager.sock')
        adapter.native_process_observer=None
        counts=self.f.f.store.consumer().snapshot_counts();calls=len(self.f.f.provider.calls)
        with self.assertRaisesRegex(RuntimeError,"process observer"):
            self.launch()
        self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
        self.assertEqual(len(self.f.f.provider.calls),calls)
    def test_same_prepared_start_keeps_occurrence_and_denies_attempted_replay(self):
        adapter=self.f.f.app.runtime.adapter;adapter.native_caller_socket=str(self.f.root/'manager.sock')
        def managed(*a,**k):raise AssertionError('read-only worker entered managed native caller registration')
        adapter.native_process_observer=managed
        answer=self.launch();occurrence=answer['occurrence'];before=len(self.f.f.port.list_due({'role':'worker'}))
        result=self.call('start-prepared',occurrence=occurrence)
        self.assertEqual(result['outcome'],'succeeded',result)
        self.assertEqual(result['schedule_id'],occurrence['schedule_id'])
        self.assertEqual(len(self.f.f.port.list_due({'role':'worker'})),before)
        calls=len(self.f.f.provider.calls)
        with self.assertRaises(PermissionError):self.call('start-prepared',occurrence=occurrence,request_key='second-start')
        self.assertEqual(len(self.f.f.provider.calls),calls)
    def test_unauthorized_file_authoring_grant_claims_and_restarted_grants_fail(self):
        r=self.request('launch',focus='Inspect installed docs')
        with self.assertRaises(PermissionError):self.s(r)
        author=OwnerAuthoringIngress(actor=self.f.server.owner.owner_actor,owner_actor=self.f.server.owner.owner_actor,directory=self.f.root/'author')
        with self.assertRaises(PermissionError):author.publish({'schema':author.schema,'request':r})
        for field in ('principal','actor','model','profile','assignment_ref','generation','pool_id','parent','caller_native_session_id'):
            with self.subTest(field=field),self.assertRaises(PermissionError):self.ingress.publish({'schema':self.ingress.schema,'request':{**r,field:'forged'}})
        self.ingress.publish({'schema':self.ingress.schema,'request':r})
        restart=OwnerExecutionIngress(actor=self.f.server.owner.owner_actor,owner_actor=self.f.server.owner.owner_actor,directory=self.ingress.directory)
        with self.assertRaises(PermissionError):restart.authorize(r)
    def test_stale_scope_allowance_occupied_capacity_and_foreign_result_fail_before_effects(self):
        calls=len(self.f.f.provider.calls);counts=self.f.f.store.consumer().snapshot_counts()
        baseline=copy.deepcopy(self.s.external_execution_policy)
        for field,value in [('generation',2),('task_ref',{**baseline['task_ref'],'revision':'rev-999'}),('worker_turn_allowance',1),('model','foreign'),('native_adapter','foreign'),('capacity_units',2),('max_depth',2)]:
            self.s.external_execution_policy={**baseline,field:value}
            with self.subTest(field=field),self.assertRaises(PermissionError):self.launch()
        self.s.external_execution_policy=baseline
        self.f.ingress.live_occurrence=lambda _:True
        with self.assertRaises(PermissionError):self.launch()
        self.f.ingress.live_occurrence=lambda _:False
        self.assertEqual(len(self.f.f.provider.calls),calls);self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
        with self.assertRaises(PermissionError):self.call('result',occurrence=handle(self.f.parent.to_dict()))
        response=self.launch();self.assertEqual(response['outcome'],'admitted',response)
        with self.assertRaises(PermissionError):self.launch(request_key='second-root-launch')
    def test_nested_classification_never_grants_new_execution_or_consumption(self):
        self.assertTrue(_starts_work(self.request('launch',focus='read')))
        self.assertTrue(_starts_work(self.request('start-prepared',occurrence={})))
        self.assertEqual(_nested_capability(self.request('start-prepared',occurrence={})), 'held')
        self.assertEqual(_nested_capability(self.request('launch',focus='read')),'held')
        self.assertEqual(_nested_capability(self.request('consume',occurrence={})),'held')
        self.assertEqual(_nested_capability(self.request('result',occurrence={})),'admitted')

    def test_owner_claude_write_done_removes_landed_lab_after_rejected_capture_acceptance(self):
        """A real owner Due captures its synthetic Claude Write before cleanup."""
        import base64
        from tests import test_execution_application as owner_fixture
        from test_landing import _Runner, _admitted_task, _advance, _project, _service
        from otto.agents.claude_adapter import (ClaudeNativeResultVerifier, ClaudeWorkerAdapter,
                                                ROLE_PROFILES)
        from otto.agents.owner_runtime import OwnerAuthorizedRoleCapture
        from otto.agents.tests.test_claude_binding import local_transport
        from otto.portfolio.occurrence_reads import read_captured_artifact, result_view
        from herzchen.fleet.labs import LabFleet
        from otto.hostctl.product_service import OwnerFleetRegistry

        f = owner_fixture.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        project_root = Path(f.temporary.name) / 'landed-project'
        project_root.mkdir()
        line, _base, _fake_fleet = _project(project_root)

        def checkpoint(worktree, paths, *, message):
            subprocess.run(['git', '-C', str(worktree), 'add', '--', *paths], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(worktree), '-c', 'user.name=LAND test',
                            '-c', 'user.email=land@test.invalid', 'commit', '-m', message], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        fleet = LabFleet(line, project_root / 'real-labs', checkpoint=checkpoint, shared_dirs=())
        lab = fleet.create('one', base='refs/heads/main')
        workspace = str(lab.path.resolve())
        landing, _calls = _service(fleet, _Runner(), task=_admitted_task())
        state = tempfile.TemporaryDirectory(prefix='owner-claude-state-')
        self.addCleanup(state.cleanup)
        transport = local_transport(workspace, str(Path(state.name).resolve()))
        order = []
        landed_commits = []
        original_run = transport.run

        def write_then_done(prompt, **options):
            native = original_run(prompt, **options)
            if not options.get('initializer'):
                order.append('Write')
                landed_commits.append(_advance(landing)['commit'])
                order.append('done')
            return native

        transport.run = write_then_done
        adapter = ClaudeWorkerAdapter(owner='worker', source=workspace, worktree=workspace,
            launcher_pin=transport.pin, state_root=str(Path(state.name).resolve()),
            requested_model='gpt-test', requested_reasoning='high', transport=transport)

        def settle_landed_worker(**kwargs):
            # Runtime calls this after artifact publication and the acceptance
            # decision, even when that decision rejects. The lab must remain
            # readable through this callback.
            assert kwargs['published']
            assert (lab.path / 'answer.txt').read_bytes() == b'Useful artifact\n'
            due = f.port.read_due(kwargs['schedule_id'])
            view = result_view(due)
            assert view['required_capture'] is True
            assert 'manager_acceptance' not in due['host_evidence']['gateway_attempt']
            predicate = object.__new__(OwnerFleetRegistry)
            assert predicate._captured_worker_due(due, task_ref=kwargs['task_ref'],
                assignment_ref=kwargs['assignment_ref'], generation=kwargs['generation'],
                published=kwargs['published']) is True
            captured = read_captured_artifact(due, artifact_ref=view['artifacts'][0]['ref'])
            assert base64.b64decode(captured['content_base64']) == b'Useful artifact\n'
            order.append('capture')
            swept = fleet.sweep_landed('refs/heads/main', lambda name, commit: (
                name == 'one' and landed_commits == [commit]
                and result_view(due)['required_capture'] is True))
            assert any(item.name == 'one' and item.action == 'removed' for item in swept), swept
            return {'cleanup_pending': False}

        f.owner.landed_worker_settler = settle_landed_worker
        app = f.owner.execution_application(due_port=f.port, adapter=adapter,
            clock=lambda: owner_fixture.NOW, native_result_verifier=ClaudeNativeResultVerifier())
        request = f.request()
        worker_effects = ROLE_PROFILES['worker']['effects']
        request['instruction_contract']['authority']['effect_profile'] = 'workspace-write-worker'
        request['instruction_contract']['authority']['permitted_effects'] = sorted(worker_effects)
        request['instruction_contract']['authority']['workspace_roots'] = [str(lab.path.resolve())]
        request['instruction_contract']['read_targets'] = [workspace]

        # Model the owner capture settling while its acceptance CAS rejects.
        # Cleanup must follow the retained artifact capture, not that decision.
        with patch.object(OwnerAuthorizedRoleCapture, 'accept_result',
                return_value={'outcome': 'rejected', 'accepted': False}):
            result = app.assign_and_start(**request)

        self.assertEqual(result['outcome'], 'succeeded', result)
        self.assertEqual(order, ['Write', 'done', 'capture'], result)
        due = f.port.read_due(result['schedule_id'])
        view = result_view(due)
        self.assertTrue(view['required_capture'])
        captured = read_captured_artifact(due, artifact_ref=view['artifacts'][0]['ref'])
        self.assertEqual(base64.b64decode(captured['content_base64']), b'Useful artifact\n')
        self.assertFalse(lab.path.exists())


    def test_owner_claude_write_done_captures_before_landed_lab_removal(self):
        """A real owner Due captures its synthetic Claude Write before cleanup."""
        import base64
        from tests import test_execution_application as owner_fixture
        from test_landing import _Runner, _admitted_task, _advance, _project, _service
        from otto.agents.claude_adapter import (ClaudeNativeResultVerifier, ClaudeWorkerAdapter,
                                                ROLE_PROFILES)
        from otto.agents.tests.test_claude_binding import local_transport
        from otto.portfolio.occurrence_reads import read_captured_artifact, result_view
        from herzchen.fleet.labs import LabFleet
        from otto.hostctl.product_service import OwnerFleetRegistry

        f = owner_fixture.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        project_root = Path(f.temporary.name) / 'landed-project'
        project_root.mkdir()
        line, _base, _fake_fleet = _project(project_root)

        def checkpoint(worktree, paths, *, message):
            subprocess.run(['git', '-C', str(worktree), 'add', '--', *paths], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(worktree), '-c', 'user.name=LAND test',
                            '-c', 'user.email=land@test.invalid', 'commit', '-m', message], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        fleet = LabFleet(line, project_root / 'real-labs', checkpoint=checkpoint, shared_dirs=())
        lab = fleet.create('one', base='refs/heads/main')
        workspace = str(lab.path.resolve())
        landing, _calls = _service(fleet, _Runner(), task=_admitted_task())
        state = tempfile.TemporaryDirectory(prefix='owner-claude-state-')
        self.addCleanup(state.cleanup)
        transport = local_transport(workspace, str(Path(state.name).resolve()))
        order = []
        landed_commits = []
        original_run = transport.run

        def write_then_done(prompt, **options):
            native = original_run(prompt, **options)
            if not options.get('initializer'):
                order.append('Write')
                landed_commits.append(_advance(landing)['commit'])
                order.append('done')
            return native

        transport.run = write_then_done
        adapter = ClaudeWorkerAdapter(owner='worker', source=workspace, worktree=workspace,
            launcher_pin=transport.pin, state_root=str(Path(state.name).resolve()),
            requested_model='gpt-test', requested_reasoning='high', transport=transport)

        def settle_landed_worker(**kwargs):
            # Runtime calls this only after artifact publication and result
            # acceptance. The lab must remain readable through this callback.
            assert kwargs['published']
            assert (lab.path / 'answer.txt').read_bytes() == b'Useful artifact\n'
            due = f.port.read_due(kwargs['schedule_id'])
            view = result_view(due)
            assert view['required_capture'] is True
            assert due['host_evidence']['gateway_attempt']['manager_acceptance']['accepted'] is True
            predicate = object.__new__(OwnerFleetRegistry)
            assert predicate._captured_worker_due(due, task_ref=kwargs['task_ref'],
                assignment_ref=kwargs['assignment_ref'], generation=kwargs['generation'],
                published=kwargs['published']) is True
            captured = read_captured_artifact(due, artifact_ref=view['artifacts'][0]['ref'])
            assert base64.b64decode(captured['content_base64']) == b'Useful artifact\n'
            order.append('capture')
            swept = fleet.sweep_landed('refs/heads/main', lambda name, commit: (
                name == 'one' and landed_commits == [commit]
                and result_view(due)['required_capture'] is True))
            assert any(item.name == 'one' and item.action == 'removed' for item in swept), swept
            return {'cleanup_pending': False}

        f.owner.landed_worker_settler = settle_landed_worker
        app = f.owner.execution_application(due_port=f.port, adapter=adapter,
            clock=lambda: owner_fixture.NOW, native_result_verifier=ClaudeNativeResultVerifier())
        request = f.request()
        worker_effects = ROLE_PROFILES['worker']['effects']
        request['instruction_contract']['authority']['effect_profile'] = 'workspace-write-worker'
        request['instruction_contract']['authority']['permitted_effects'] = sorted(worker_effects)
        request['instruction_contract']['authority']['workspace_roots'] = [str(lab.path.resolve())]
        request['instruction_contract']['read_targets'] = [workspace]

        result = app.assign_and_start(**request)

        self.assertEqual(result['outcome'], 'succeeded', result)
        self.assertEqual(order, ['Write', 'done', 'capture'], result)
        due = f.port.read_due(result['schedule_id'])
        view = result_view(due)
        self.assertEqual(due['completion_state'], 'succeeded')
        self.assertTrue(view['required_capture'])
        captured = read_captured_artifact(due, artifact_ref=view['artifacts'][0]['ref'])
        self.assertEqual(base64.b64decode(captured['content_base64']), b'Useful artifact\n')
        self.assertFalse(lab.path.exists())

    def test_owner_claude_done_without_write_capture_does_not_complete_or_remove_lab(self):
        """Landing alone cannot settle a worker whose Claude Write was not captured."""
        from tests import test_execution_application as owner_fixture
        from test_landing import _Runner, _admitted_task, _advance, _project, _service
        from herzchen.fleet.labs import LabFleet
        from otto.agents.claude_adapter import (ClaudeNativeResultVerifier, ClaudeWorkerAdapter,
                                                ROLE_PROFILES)
        from otto.agents.tests.test_claude_binding import local_transport
        from otto.portfolio.occurrence_reads import result_view

        f = owner_fixture.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        project_root = Path(f.temporary.name) / 'missing-write-project'
        project_root.mkdir()
        line, _base, _fake_fleet = _project(project_root)

        def checkpoint(worktree, paths, *, message):
            subprocess.run(['git', '-C', str(worktree), 'add', '--', *paths], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(worktree), '-c', 'user.name=LAND test',
                            '-c', 'user.email=land@test.invalid', 'commit', '-m', message], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        fleet = LabFleet(line, project_root / 'real-labs', checkpoint=checkpoint, shared_dirs=())
        lab = fleet.create('one', base='refs/heads/main')
        workspace = str(lab.path.resolve())
        landing, _calls = _service(fleet, _Runner(), task=_admitted_task())
        state = tempfile.TemporaryDirectory(prefix='owner-claude-missing-write-')
        self.addCleanup(state.cleanup)
        transport = local_transport(workspace, str(Path(state.name).resolve()))
        original_run = transport.run

        def write_then_done(prompt, **options):
            native = original_run(prompt, **options)
            if not options.get('initializer'):
                _advance(landing)
                # Preserve the real Write event and done call, then model a
                # vanished source file before native stream capture begins.
                (lab.path / 'answer.txt').unlink()
            return native

        transport.run = write_then_done
        adapter = ClaudeWorkerAdapter(owner='worker', source=workspace, worktree=workspace,
            launcher_pin=transport.pin, state_root=str(Path(state.name).resolve()),
            requested_model='gpt-test', requested_reasoning='high', transport=transport)
        cleanup_calls = []
        f.owner.landed_worker_settler = lambda **kwargs: cleanup_calls.append(kwargs)
        app = f.owner.execution_application(due_port=f.port, adapter=adapter,
            clock=lambda: owner_fixture.NOW, native_result_verifier=ClaudeNativeResultVerifier())
        request = f.request()
        request['instruction_contract']['authority']['effect_profile'] = 'workspace-write-worker'
        request['instruction_contract']['authority']['permitted_effects'] = sorted(ROLE_PROFILES['worker']['effects'])
        request['instruction_contract']['authority']['workspace_roots'] = [workspace]
        request['instruction_contract']['read_targets'] = [workspace]

        result = app.assign_and_start(**request)

        self.assertNotEqual(result['outcome'], 'succeeded', result)
        due = f.port.read_due(result['schedule_id'])
        self.assertNotEqual(due['completion_state'], 'succeeded')
        self.assertFalse(result_view(due)['required_capture'])
        self.assertEqual(cleanup_calls, [])
        self.assertTrue(lab.path.is_dir())


if __name__=='__main__':unittest.main()
