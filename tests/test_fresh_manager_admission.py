"""Real CLI READY→authorized work admission and retained native reconciliation."""
from pathlib import Path
import sys, unittest, json, hashlib
from dataclasses import replace
from unittest.mock import patch
from otto.agents.herzchen_adapter import HerzchenCodexAdapter,JsonlHostTurnContextReader
from tests.test_manager_bootstrap_recovery import CLI,SESSION
from tests import test_execution_application as application

def digest(body):return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
class FreshManagerTests(unittest.TestCase):
 def fixture(self):
  f=application.ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups)
  root=Path(f.temporary.name).resolve();launcher=root/'fixture-cli'
  launcher.write_text('#!'+sys.executable+'\n'+CLI);launcher.chmod(0o700);context=root/'context.jsonl'
  adapter=HerzchenCodexAdapter(owner='manager',source=str(root),worktree=str(root),launcher=str(launcher),requested_model='gpt-test',requested_reasoning='high',require_host_context=True,native_trace_path=str(root/'native.jsonl'),host_context_path=str(context),turn_context_reader=JsonlHostTurnContextReader(context))
  assignment,guide,_=f.role_handles('manager','manager',None)
  f.app=f.owner.execution_application(due_port=f.port,adapter=adapter,manager_actor='manager')
  contract=f.request()['instruction_contract'];contract['authority']['owner_actor']='manager';contract['authority']['effect_profile']='workspace-write-manager';contract['allowed_operations'].append('canonical_manager_commands');contract['authority']['permitted_effects'].append('canonical_manager_commands')
  mandate=f.app.portfolio.create_document(f.project.ref.to_dict(),actor='manager',request_id='fresh-mandate',document_id='fresh-mandate',role='mandate',content={'role':'manager','scope_ref':f.project.ref.to_dict(),'status':'active','dispatch_enabled':True,'task_ref':f.task.ref.to_dict(),'assignment_ref':assignment.ref.to_dict(),'generation':1,'brief':{'role':'manager','mandate':'Produce actual requested artifact'},'instruction_contract':contract})['record']['payload']['current_revision']
  worker=f.app._read(f.app.assign_worker(**f.request())['schedule_id']);base=assignment.payload['resource_adoption_base_ref']
  due=replace(worker,schedule_id='fresh-manager',recipient='manager',instruction='Produce actual requested artifact café',role='manager',purpose='bootstrap',assignment_ref=base,host_evidence=None,in_flight_request='fresh-manager',invocation_identity='fresh-manager',execution_mode='fresh_manager',context_refs=(guide,mandate),target={**worker.target,'role':'manager','principal':'manager','assignment_ref':base,'mandate_ref':mandate})
  created=f.port.save_due(due.schedule_id,due.to_dict(),request_id='fresh-manager:create',expected_version=0)
  f.port.reconcile_assignment_resources(due.schedule_id,assignment_ref=assignment.ref.to_dict(),request_id='fresh-manager:resources',expected_version=created['version'])
  return f,root
 def test_ready_then_real_work_is_admitted_before_success(self):
  f,root=self.fixture();result=f.app.start(schedule_id='fresh-manager');self.assertEqual(result['outcome'],'succeeded', (result.get('result') or {}).get('error'))
  due=f.port.read_due('fresh-manager');attempt=due['host_evidence']['gateway_attempt'];admission=attempt['delivery_admission']
  self.assertEqual(admission['physical_session_id'],SESSION);self.assertEqual(admission['observed_turn_id'],'work-turn')
  submitted=[json.loads(x) for x in (root/'submitted.jsonl').read_text().splitlines()]
  self.assertEqual([x['resume'] for x in submitted],[False,True]);self.assertNotIn('Produce actual requested artifact café',submitted[0]['prompt']);self.assertIn('Produce actual requested artifact café',submitted[1]['prompt'])
  self.assertEqual(f.app.start(schedule_id='fresh-manager')['outcome'],'replayed');self.assertEqual(len((root/'submitted.jsonl').read_text().splitlines()),2)
 def legacy(self):
  f,root=self.fixture()
  with patch.object(HerzchenCodexAdapter,'set_turn_started_callback',lambda self,callback:None):result=f.app.start(schedule_id='fresh-manager')
  self.assertEqual(result['outcome'],'unknown',result)
  due=f.port.read_due('fresh-manager');prior=due['host_evidence']['gateway_attempt']['result'];self.assertIsNone(due['host_evidence']['gateway_attempt'].get('delivery_admission'))
  f.app.runtime.adapter.trusted_thread_reader=lambda session:{'thread':{'id':session,'path':str(root/'native.jsonl')}}
  return f,root,prior
 def test_retained_completed_native_recovery_preserves_unknown_no_provider(self):
  f,root,prior=self.legacy();before=(root/'submitted.jsonl').read_bytes()
  due_before=f.port.read_due('fresh-manager')
  preview=f.app.runtime.reconcile_fresh_manager_result(schedule_id='fresh-manager',expected_unknown_sha256=digest(prior),validate_only=True)
  self.assertEqual(preview['outcome'],'qualified');self.assertEqual(f.port.read_due('fresh-manager'),due_before)
  result=f.app.runtime.reconcile_fresh_manager_result(schedule_id='fresh-manager',expected_unknown_sha256=digest(prior));self.assertFalse(result['provider_called'])
  self.assertEqual(result['admission_reconciliation']['source_unknown'],prior)
  self.assertEqual(f.app.recover(schedule_id='fresh-manager',execute=False)['outcome'],'succeeded')
  self.assertEqual((root/'submitted.jsonl').read_bytes(),before)
  self.assertTrue(f.app.runtime.reconcile_fresh_manager_result(schedule_id='fresh-manager',expected_unknown_sha256=digest(prior))['replayed'])
 def test_recovery_rejects_changed_trace_and_active_turn_before_effect(self):
  for mode in ('wrong_session','active_turn','alter_context','wrong_profile','not_completed','wrong_digest','stale_assignment'):
   with self.subTest(mode=mode):
    f,root,prior=self.legacy();before=f.port.read_due('fresh-manager');trace=root/'native.jsonl';raw=trace.read_text()
    if mode=='wrong_session':f.app.runtime.adapter.trusted_thread_reader=lambda session:{'thread':{'id':'wrong','path':str(trace)}}
    elif mode=='active_turn':trace.write_text(raw+json.dumps({'type':'event_msg','payload':{'type':'task_started','turn_id':'overlapping'}})+'\n')
    elif mode=='alter_context':trace.write_text(raw.replace('gpt-test','wrong-model'))
    elif mode=='wrong_profile':trace.write_text(raw.replace('workspace-write','read-only'))
    elif mode=='not_completed':trace.write_text('\n'.join(x for x in raw.splitlines() if not ('task_complete' in x and 'work-turn' in x))+'\n')
    elif mode=='stale_assignment':
     from herzchen.contracts import ResourceRef
     f.app.assignments.reassign(ResourceRef.from_dict(prior['assignment_ref']),principal='manager',session=SESSION,reason='changed assignment',expected_generation=1,logical_request_key='change-owner-scope',actor=f.actor)
    with self.assertRaises(Exception):f.app.runtime.reconcile_fresh_manager_result(schedule_id='fresh-manager',expected_unknown_sha256='0'*64 if mode=='wrong_digest' else digest(prior))
    self.assertEqual(f.port.read_due('fresh-manager'),before)

if __name__=='__main__':unittest.main(verbosity=2)
