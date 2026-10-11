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

    def test_aborted_manual_selector_allows_distinct_same_native_callback_start(self):
        f, root, claim = self.claimed()
        # Retain the original setup selector before the authoritative abort.
        setup = {'schema':'otto.operating-setup.v1', 'mode':'manual',
            'roles':{'manager':'fresh-manager'}, 'advisor_policy':{'mode':'disabled','reason':'No advisor'},
            'acceptance_tasks':[]}
        self.assertEqual(f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(),
            setup=setup, request_key='abort-manual-setup')['outcome'], 'prepared')
        trace = root/'native.jsonl'
        rows = [json.loads(v) for v in trace.read_text().splitlines()]
        for row in rows:
            value=row.get('payload',{})
            if value.get('type')=='task_complete' and value.get('turn_id')=='work-turn':
                value.update(type='turn_aborted',reason='interrupted')
        trace.write_text(''.join(json.dumps(v)+'\n' for v in rows))
        f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=fixture.digest(claim))
        self.assertEqual(f.app.recover(schedule_id='fresh-manager',execute=False)['outcome'],'failed')
        due=f.app._read('fresh-manager')
        from otto.portfolio.execution_operations import build_manager_callback_due
        callback=build_manager_callback_due(due,schedule_id='new-authorized-response',
            request_key='new-authorized-response',assignment_ref=due.assignment_ref,
            guide_ref=next(r for r in due.context_refs if r!=due.target['mandate_ref']),
            mandate_ref=due.target['mandate_ref'],due_at=due.due_at,
            timeout_seconds=due.timeout_seconds,native_adapter=f.app.native_adapter_identity())
        from otto.portfolio.execution_operations import prepare_current_assignment_occurrence
        prepared = prepare_current_assignment_occurrence(due_port=f.port, assignments=f.app.assignments,
            binding=f.app.binding,due=callback,assignment_ref=due.assignment_ref,
            assignment_owner=f.app.manager_actor,operation='resume',lifecycle='callback',request_key='response-callback')
        self.assertEqual(prepared['outcome'],'committed')
        before=f.port.read_due('fresh-manager')
        # The trusted fixture reader must expose the maintained finite deadline
        # for a new real resume; the recovery-only reader above is read-only.
        f.app.runtime.adapter.trusted_thread_reader = lambda session, timeout_seconds=None: {
            'thread': {'id': session, 'path': str(root/'native.jsonl')}}
        f.app.runtime.adapter.trusted_thread_reader.read_with_deadline = lambda session, deadline: {
            'thread': {'id': session, 'path': str(root/'native.jsonl')}}
        submitted=len((root/'submitted.jsonl').read_text().splitlines())
        result=f.app.start(schedule_id=callback.schedule_id)
        self.assertEqual(result['outcome'],'succeeded',result.get('result',{}).get('error'))
        self.assertEqual(f.port.read_due('fresh-manager'),before)
        self.assertEqual(len((root/'submitted.jsonl').read_text().splitlines()),submitted+1)
        self.assertEqual(f.app.read_operating_setup(project_ref=f.project.ref.to_dict())['setup']['roles']['manager'], callback.schedule_id)
        self.assertEqual(f.app.start(schedule_id=callback.schedule_id)['outcome'],'replayed')
        self.assertEqual(len((root/'submitted.jsonl').read_text().splitlines()),submitted+1)

    def test_abort_old_prepared_help_new_supervisor_reply_same_service_resume(self):
        from types import SimpleNamespace
        from pathlib import Path
        from otto.portfolio.help_delivery import BoundHelpDelivery
        from otto.portfolio.owner_issue_loop import OwnerIssueReaders
        from otto.portfolio.manager_journey_service import install_manager_journey_service
        from otto.portfolio.execution_host import ExecutionHost
        f, root, claim = self.claimed()
        setup={'schema':'otto.operating-setup.v1','mode':'manual','roles':{'manager':'fresh-manager'},
            'advisor_policy':{'mode':'disabled','reason':'No advisor'},'acceptance_tasks':[]}
        self.assertEqual(f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(),
            setup=setup,request_key='joined-manual-setup')['outcome'],'prepared')
        trace=root/'native.jsonl'
        trace.write_text(trace.read_text().replace('task_complete','turn_aborted'))
        f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=fixture.digest(claim))
        self.assertEqual(f.app.recover(schedule_id='fresh-manager',execute=False)['outcome'],'failed')
        original=f.port.read_due('fresh-manager'); due=f.app._read('fresh-manager')
        supervisor,_,_=f.role_handles('orchestrator','root','root-session')
        binding={'project_ref':f.project.ref.to_dict(),'assignment_ref':supervisor.ref.to_dict(),
            'generation':1,'principal':'root','conversation_ref':{'host':'codex','native_id':'root-session'}}
        readers=OwnerIssueReaders(f.owner.consumer_operations(),f.port)
        delivery=BoundHelpDelivery(readers=readers,interim_supervision=binding)
        portfolio=f.owner.manager_application(due_port=f.port,issue_delivery=delivery).portfolio
        f.app.portfolio=f.app.runtime.portfolio=portfolio
        state={'authority':f.actor.authority,'owner':'manager','manager':'manager',
            'assignment_ref':due.assignment_ref,'manager_generation':1,'project_ref':f.project.ref.to_dict(),
            'task_refs':{'T1':f.task.ref.to_dict()},'schedule_id':due.schedule_id,
            'requested_model':'gpt-test','requested_reasoning':'high'}
        state_path = root / "joined-state.json"
        def save_state():
            from otto.portfolio.execution_host import _atomic_json
            _atomic_json(state_path, server.state)
        server=SimpleNamespace(owner=f.owner,portfolio=portfolio,state=state,due_port=f.port,
            _execution=lambda **_:f.app,_save_state=save_state,handle=lambda r:{'outcome':'unsupported'})
        save_state()
        host=ExecutionHost(directory=root/'joined-ipc',handler=server.handle);server.execution_host=host;host._closing=True
        service=install_manager_journey_service(server,run_path=str(root),workspace=str(root),
            orchestrator_principal='root',help_reply_authorizer=lambda _:f.binding.authenticated_actor('root'))
        def request(key):
            return service({'command':'request-help','request_key':key,'issue_key':key,
                'problem':'Retained manager aborted','impact':'Correction needs current response',
                'evidence':[{'schedule_id':'fresh-manager'}],'requested_decision':'Confirm adopted scope',
                'return_condition':'Current supervisor response retained'})
        def reply(issue,key):
            return service({'command':'respond-help','issue_id':issue['issue_id'],'request_key':key,
                'authority_source':'Exact owner binding','response':'Continue current adopted scope',
                'proposed_solution':'Same manager corrective work','next_action':'Retain original failures; one current correction'})
        first=reply(request('old-issue'),'old-reply')
        old=f.app.continue_manager_from_help(manager_schedule_id=due.schedule_id,
            report_ref=first['report_ref'],execute=False)
        state['manager_continuation']={'schedule_id':old['schedule_id'],'outcome':'partial'}
        new=reply(request('new-issue'),'new-reply')
        reader=lambda session:{'thread':{'id':session,'path':str(trace)}}
        reader.read_with_deadline=lambda session,deadline:reader(session)
        f.app.runtime.adapter.trusted_thread_reader=reader
        count=len((root/'submitted.jsonl').read_text().splitlines())
        result=service({'command':'manager-help-result','principal':'manager','generation':1,
            'schedule_id':old['schedule_id'],'report_ref':new['report_ref']})
        self.assertEqual(result['outcome'],'succeeded',result.get('result',{}).get('error'))
        self.assertEqual(f.port.read_due('fresh-manager'),original)
        self.assertEqual(f.app._read(old['schedule_id']).stop_state,'stopped')
        self.assertEqual(len((root/'submitted.jsonl').read_text().splitlines()),count+1)
        current=f.app._read(state['manager_continuation']['schedule_id'])
        self.assertEqual(current.last_result['physical_session_id'],due.last_result['physical_session_id'])
        self.assertIn(new['report_ref']['id'],current.message)
        self.assertEqual(current.host_evidence['help_continuation']['report_ref'],new['report_ref'])
        # Reopen from durable state and redeliver the exact original request.
        # Canonical Due/outcome is retained; this does not submit another turn.
        server.state = json.loads(state_path.read_text())
        reopened = install_manager_journey_service(server, run_path=str(root), workspace=str(root),
            orchestrator_principal='root', help_reply_authorizer=lambda _:f.binding.authenticated_actor('root'))
        count = len((root/'submitted.jsonl').read_text().splitlines())
        replay = reopened({'command':'manager-help-result','principal':'manager','generation':1,
            'schedule_id':old['schedule_id'],'report_ref':new['report_ref']})
        self.assertEqual(replay['outcome'], 'replayed')
        self.assertEqual(len((root/'submitted.jsonl').read_text().splitlines()), count)
        self.assertEqual(f.port.read_due('fresh-manager'), original)

    def test_shared_anchor_classification_keeps_abort_help_only_and_unknown_held(self):
        from dataclasses import replace
        from herzchen.contracts import ResourceRef
        f, root, claim = self.claimed()
        trace = root/'native.jsonl'
        trace.write_text(trace.read_text().replace('task_complete', 'turn_aborted'))
        f.app.runtime.reconcile_missing_manager_capture(schedule_id='fresh-manager',
            expected_claim_sha256=fixture.digest(claim))
        self.assertEqual(f.app.recover(schedule_id='fresh-manager', execute=False)['outcome'], 'failed')
        aborted = f.app._read('fresh-manager')
        current = f.app.assignments.get(ResourceRef.from_dict(aborted.assignment_ref))
        before = f.port.read_due('fresh-manager')
        for purpose, accept_abort in (('help continuation', True),
                                     ('worker-result continuation', False),
                                     ('task-settlement continuation', False)):
            with self.subTest(purpose=purpose):
                anchor, superseded, blocked = f.app._manager_anchor(aborted, current,
                    schedule='new-callback', purpose=purpose, accept_aborted=accept_abort)
                self.assertIsNone(superseded)
                self.assertEqual(anchor, aborted)
                self.assertEqual(blocked is None, accept_abort)
                if blocked is not None:
                    self.assertEqual(blocked['outcome'], 'held')
                    self.assertEqual(blocked['schedule_id'], aborted.schedule_id)
                    self.assertFalse(blocked['provider_called'])
                unknown = replace(aborted, completion_state='unknown')
                _, _, blocked = f.app._manager_anchor(unknown, current,
                    schedule='new-callback', purpose=purpose, accept_aborted=accept_abort)
                self.assertEqual(blocked['outcome'], 'held')
        self.assertEqual(f.port.read_due('fresh-manager'), before)

    def test_delayed_completion_cannot_overwrite_newer_durable_head(self):
        from types import SimpleNamespace
        from otto.portfolio.manager_journey_service import advance_manager_head, complete_manager_head
        from otto.portfolio.owner_completion import OwnerCompletion, after_owner
        from otto.portfolio.execution_host import _atomic_json
        f, root, _ = self.claimed()
        path = root/'head-state.json'
        state = {'schedule_id':'old', 'manager_continuation':{'schedule_id':'old','outcome':'prepared'}}
        pending = OwnerCompletion()
        callback = after_owner(pending, lambda result: complete_manager_head(state, schedule_id='old', result=result))
        newer = SimpleNamespace(schedule_id='new', target={'native_id':fixture.SESSION})
        self.assertTrue(advance_manager_head(state, expected='old', due=newer, settled_anchor='old'))
        _atomic_json(path, state)
        state.clear(); state.update(json.loads(path.read_text()))
        before = copy.deepcopy(state)
        pending.resolve({'outcome':'succeeded', 'schedule_id':'old', 'provider_called':True})
        self.assertFalse(callback.value)
        self.assertEqual(state, before)
        self.assertFalse(advance_manager_head(state, expected='old', due=newer, settled_anchor='old'))
        self.assertTrue(complete_manager_head(state, schedule_id='new', result={'outcome':'succeeded'}))
        _atomic_json(path, state)
        self.assertEqual(json.loads(path.read_text())['manager_continuation']['outcome'], 'succeeded')

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
