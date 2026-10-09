"""Exact initialized-session recovery; synthetic native fixture, no installed proof."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from tests import test_worker_custody as custody_fixtures
jsonl=custody_fixtures.jsonl
from otto.portfolio.worker_custody import inspect_initialized_worker,release_initialized_worker,permits_fresh_worker
from otto.portfolio.execution_operations import OccurrencePreparationError
from otto.portfolio.execution import _digest
from herzchen.contracts import ResourceRef
class InitializedWorkerContinuityTests(unittest.TestCase):
 def setUp(self):
  self.base=custody_fixtures.WorkerCustodyTests();self.base.setUp();self.addCleanup(self.base.doCleanups);self.f=self.base.f;self.schedule=self.base.schedule
  due=self.f.app._read(self.schedule);host=deepcopy(due.host_evidence);r=host['gateway_attempt']['result'];raw=r['raw_result'];wr=raw['work_receipt'];we=raw['work_envelope']
  wr.update(outcome='unknown',process_id=None,unsupported_reason='recipient_context_unavailable')
  we.update(fnd_receipt=wr,status='unknown',process_id=None,exit_status=None,stdout=None,stderr=None,command=None,host_evidence=None,delivery_state='not_started',unsupported_error='recipient_context_unavailable',reconciliation='trusted recipient authorization is not exact')
  raw['initialization_envelope'].update(observed_model=due.requested_model,observed_reasoning=due.requested_reasoning)
  r['observed_turn_id']=None;r['task_bound_evidence']=None;raw['native_candidate']=None
  self.f.port.save_due(self.schedule,replace(due,host_evidence=host).to_dict(),request_id='fixture-unstarted-resume',expected_version=due.version)
  records=[json.loads(x)for x in self.base.trace.read_text().splitlines()];self.base.trace.write_text(jsonl(records[:4]));self.before=self.f.port.read_due(self.schedule)
 def release(self,**changes):
  scope=inspect_initialized_worker(self.f.app,schedule_id=self.schedule)
  request=dict(schedule_id=self.schedule,request_key='release-exact-initializer',fresh_request_key='same-session-delivery',expected_due_sha256=scope['due_sha256'],expected_unknown_result_sha256=scope['unknown_result_sha256']);request.update(changes)
  return release_initialized_worker(self.f.app,**request)
 def test_exact_owner_disposition_prepares_same_session_without_initializer_or_unknown_rewrite(self):
  self.release();f=self.f;due=f.app._read(self.schedule);assignment=f.app.assignments.get(ResourceRef.from_dict(due.assignment_ref))
  self.assertEqual(due.host_evidence['gateway_attempt'],self.before['host_evidence']['gateway_attempt']);self.assertEqual(due.completion_state,'unknown')
  self.assertFalse(permits_fresh_worker(f.app,due,request={'request_key':'same-session-delivery','route':'normal','principal':due.recipient},model=due.requested_model,reasoning=due.requested_reasoning))
  prepared=f.app.prepare_role(role='worker',project_ref=due.target['project_ref'],task_ref=due.target['task_ref'],assignment_ref=due.assignment_ref,generation=due.generation,mandate_ref=due.target['mandate_ref'],request_key='same-session-delivery',instruction='Perform the original bounded work once',model=due.requested_model,reasoning=due.requested_reasoning,profile=due.profile,native_session_id='capacity-session',binding_schedule_id=self.schedule)
  self.assertEqual(prepared['outcome'],'committed',prepared);new=f.app._read(prepared['schedule_id']);self.assertEqual(new.assignment_ref,due.assignment_ref);self.assertEqual(new.target['native_id'],'capacity-session');self.assertEqual(new.execution_mode,'continue_existing')
  f.app._verify_native_binding(assignment,'capacity-session',new.schedule_id);self.assertEqual(f.provider.calls,[])
  for key,session in [('foreign-key','capacity-session'),('same-session-delivery','foreign-session')]:
   with self.assertRaises(OccurrencePreparationError):f.app._verify_native_binding(assignment,session,self.schedule,request_key=key)
 def test_started_resume_and_foreign_authorization_cannot_release(self):
  for mutate in (lambda a:a['result']['raw_result']['work_envelope'].update(process_id='200'),lambda a:a['delivery_authorization'].update(generation=2)):
   due=self.f.app._read(self.schedule);host=deepcopy(due.host_evidence);mutate(host['gateway_attempt']);self.f.port.save_due(self.schedule,replace(due,host_evidence=host).to_dict(),request_id='bad-'+str(due.version),expected_version=due.version)
   with self.assertRaises(OccurrencePreparationError):self.release()
   self.f.port.save_due(self.schedule,{**self.before,'version':self.f.app._read(self.schedule).version},request_id='reset-'+str(due.version),expected_version=self.f.app._read(self.schedule).version)
 def test_stale_pin_and_native_task_or_effect_evidence_reject(self):
  with self.assertRaises(OccurrencePreparationError):self.release(expected_due_sha256='0'*64)
  with self.base.trace.open('a')as trace:trace.write(jsonl([{'type':'event_msg','payload':{'type':'task_started','turn_id':'task-turn'}}]))
  with self.assertRaises(OccurrencePreparationError):self.release()
  self.assertEqual(self.f.port.read_due(self.schedule),self.before);self.assertEqual(self.f.provider.calls,[])
if __name__=='__main__':unittest.main()
