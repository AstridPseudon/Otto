import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from otto.portfolio.worker_custody import retained_stopped_writer_conflict_release
from otto.portfolio.execution_host import ExecutionHost

class StoppedWriterConflictTests(unittest.TestCase):
    def setUp(self):
        ref={'authority':'test','kind':'wrk.assignment','id':'manager','revision':'rev-1'}
        project={'authority':'test','kind':'work.project','id':'project','revision':'rev-1'}
        task={'authority':'test','kind':'work.task','id':'task','revision':'rev-1'}
        session='test-session';principal='manager';actor='owner'
        auth={'assignment_ref':ref,'generation':1,'physical_session_id':session,'project_ref':project,'task_ref':task,'role':'manager','principal':principal,'lifecycle_owner':actor,'status':'authorized','logical_request_key':'original'}
        receipt={'operation':'resume','outcome':'failed','process_id':'123','identity':{'logical_agent_id':principal,'physical_session_id':session},'result_ref':None}
        host={'session_id':session,'process_started':True,'session_created':False,'native_turn_started':False,'invocation_turn_verified':False,'turn_id':None,'provenance':'host_native_jsonl','otto_host_turn_context':None,'native_candidate':{'capture_utf8_bytes':0,'capture_sha256':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','native_records':[],'turn_id':None,'task_bound':False,'retry_allowed':False,'status':'unsupported'}}
        message='thread-store conflict: thread '+session+' already has an active writer'
        diagnostic='2026-10-11T06:05:31.952106Z ERROR codex_core::session::session: failed to initialize thread persistence: '+message+'\n2026-10-11T06:05:31.952633Z ERROR codex_core::session: Failed to create session: '+message+'\nError: thread/resume: thread/resume failed: thread '+session+' already has an active writer (code -32600)\n'
        work={'fnd_receipt':receipt,'runner':'codex-cli','status':'failed','exit_status':1,'transport_operation':'resume','physical_session_id':session,'logical_agent_id':principal,'owner':principal,'process_id':'123','timeout':None,'cancel':None,'result_ref':None,'stdout':'','stderr':diagnostic,'started_at':'2026-10-11T06:05:08Z','ended_at':'2026-10-11T06:05:32Z','host_evidence':host}
        result={'physical_session_id':session,'native_session_id':session,'outcome':'unknown','delivery_state':'unknown','context_digest_verified':False,'observed_turn_id':None,'error':{'code':'authorized_result_unverified'},'logical_request_key':'original','assignment_ref':ref,'generation':1,'project_ref':project,'task_ref':task,'logical_agent_id':principal,'owner':principal,'raw_result':{'work_envelope':work,'work_receipt':receipt,'owner_delivery_authorization':auth,'transport_operation':'resume','worker_content':[],'task_bound_evidence':None,'initialization_envelope':None,'initialization_receipt':None}}
        attempt={'state':'result','physical_session_id':session,'result':result,'delivery_authorization':auth,'logical_request_key':'original','assignment_ref':ref,'generation':1}
        self.due=SimpleNamespace(schedule_id='old',stop_state='stopped',in_flight_request=None,completion_state='none',role='manager',lifecycle_owner=actor,owner=actor,manager_ref=actor,assignment_ref=ref,generation=1,recipient=principal,target={'native_id':session,'project_ref':project,'task_ref':task},host_evidence={'gateway_attempt':attempt})
        current=SimpleNamespace(role='manager',principal=principal,generation=1,ref=SimpleNamespace(to_dict=lambda:ref),payload={})
        self.app=SimpleNamespace(actor=actor,manager_actor=principal,assignments=SimpleNamespace(get=lambda ref:current),_current=lambda ref,gen:current,runtime=SimpleNamespace(adapter=SimpleNamespace(worktree='/tmp/project')),portfolio=SimpleNamespace(operations=SimpleNamespace(_owner_reader=None)))

    def test_release_preserves_unknown_and_external_writer_uncertainty(self):
        before=copy.deepcopy(vars(self.due));out=retained_stopped_writer_conflict_release(self.app,self.due)
        self.assertFalse(out['external_writer_release_verified']);self.assertFalse(out['provider_retry_allowed'])
        self.assertEqual(vars(self.due),before)
        host=ExecutionHost(directory='/tmp/not-opened',handler=lambda x:x,owner_path='/tmp/not-opened-owner',bounded_transports=True)
        with patch.object(host,'_execution_scope',return_value={'role':'manager'}):host.restore_execution(self.app,self.due)
        self.assertNotIn('old',host._capacity_holds)

    def test_exact_terminal_inflight_token_is_preserved_not_replayed(self):
        self.due.in_flight_request = 'original'
        before = copy.deepcopy(vars(self.due))
        out = retained_stopped_writer_conflict_release(self.app, self.due)
        self.assertFalse(out['provider_retry_allowed'])
        self.assertEqual(vars(self.due), before)

    def test_ambiguous_foreign_or_started_turn_never_releases(self):
        cases=[lambda d:setattr(d,'stop_state','active'),lambda d:setattr(d,'in_flight_request','unknown'),lambda d:setattr(d,'lifecycle_owner','foreign'),lambda d:setattr(d,'generation',2),lambda d:d.target.update(native_id='foreign'),lambda d:d.host_evidence['gateway_attempt']['result'].update(observed_turn_id='turn'),lambda d:d.host_evidence['gateway_attempt']['result']['raw_result']['work_envelope'].update(stdout='{"type":"turn.started"}'),lambda d:d.host_evidence['gateway_attempt']['result']['raw_result']['work_envelope'].update(exit_status=None),lambda d:d.host_evidence['gateway_attempt']['result']['raw_result']['work_envelope'].update(stderr='generic failure'),lambda d:d.host_evidence['gateway_attempt']['result']['raw_result']['work_envelope']['host_evidence'].update(session_created=True),lambda d:d.host_evidence['gateway_attempt']['result']['raw_result']['owner_delivery_authorization'].update(principal='foreign')]
        for change in cases:
            with self.subTest(change=change):
                d=copy.deepcopy(self.due);change(d)
                with self.assertRaises((ValueError,KeyError,TypeError)):retained_stopped_writer_conflict_release(self.app,d)
                host=ExecutionHost(directory='/tmp/not-opened',handler=lambda x:x,owner_path='/tmp/not-opened-owner',bounded_transports=True)
                with patch.object(host,'_execution_scope',return_value={'role':'manager'}):host.restore_execution(self.app,d)
                self.assertIn('old',host._capacity_holds)
