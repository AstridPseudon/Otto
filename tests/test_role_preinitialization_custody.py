"""Exact maintained guard retirement; tiny disposable canonical Store, no provider."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from herzchen.contracts import ResourceRef
from otto.portfolio.execution_operations import OccurrencePreparationError
from otto.portfolio.worker_custody import (PREINITIALIZATION_ERROR,inspect_preinitialization_role,
    release_preinitialization_role,retained_preinitialization_release,permits_preinitialization_role)
from tests import test_execution_application as fixtures

class PreinitializationCustodyTests(unittest.TestCase):
 def setUp(self):
  self.f=f=fixtures.ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups)
  manager,guide,mandate=f.role_handles('manager','manager',None);self.manager=manager;self.guide=guide;self.mandate=mandate
  seed=f.app.assign_worker(**f.request());due=f.app._read(seed['schedule_id']);self.schedule='fixture-original-manager'
  target={**due.target,'assignment_ref':manager.ref.to_dict(),'mandate_ref':mandate,'role':'manager','principal':'manager'}
  due=replace(due,schedule_id=self.schedule,version=0,host_evidence=None,assignment_ref=manager.ref.to_dict(),recipient='manager',role='manager',execution_mode='fresh_manager',target=target)
  base=manager.payload['resource_adoption_base_ref'];due=replace(due,assignment_ref=base,target={**due.target,'assignment_ref':base})
  f.port.save_due(self.schedule,due.to_dict(),request_id='fixture-original-manager',expected_version=0)
  f.port.reconcile_assignment_resources(self.schedule,assignment_ref=manager.ref.to_dict(),expected_version=f.port.read_due(self.schedule)['version'],request_id='fixture-original-manager:resources')
  due=f.app._read(self.schedule)
  result={'assignment_ref':due.assignment_ref,'generation':1,'logical_request_key':due.in_flight_request,
   'outcome':'failed','operation':'invoke','error':deepcopy(PREINITIALIZATION_ERROR),'unknown_reason':PREINITIALIZATION_ERROR['message'],
   'delivery_state':'unknown','replayed':False,'physical_session_id':None,'native_session_id':None,'observed_model':None,'observed_reasoning':None,'timeout':False,
   'logical_agent_id':'manager','owner':'manager','project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],
   'requested_model':due.requested_model,'requested_reasoning':due.requested_reasoning,'requested_profile':due.profile,
   'resource_evidence':{'brief':{'context':{'canonical_snapshot':{'native_session':None,'assignment_ref':due.assignment_ref,'generation':1,'task_ref':due.target['task_ref']}}}}}
  attempt={'state':'result','assignment_ref':due.assignment_ref,'generation':1,'logical_request_key':due.in_flight_request,'result':result}
  f.port.save_due(self.schedule,replace(due,host_evidence={**due.host_evidence,'gateway_attempt':attempt}).to_dict(),request_id='fixture-preinit',expected_version=due.version)
  self.before=f.port.read_due(self.schedule)
 def release(self):
  return release_preinitialization_role(self.f.app,schedule_id=self.schedule,request_key='retire-exact',fresh_request_key='separate-delivery')
 def change(self,fn):
  f=self.f;due=f.app._read(self.schedule);host=deepcopy(due.host_evidence);fn(host['gateway_attempt']);f.port.save_due(self.schedule,replace(due,host_evidence=host).to_dict(),request_id='mutated',expected_version=due.version)
 def test_retire_preserves_original_failure_and_exact_one_delivery(self):
  f=self.f;scope=inspect_preinitialization_role(f.app,schedule_id=self.schedule);self.assertFalse(scope['initializer_occurred']);self.release()
  after=f.port.read_due(self.schedule);self.assertEqual(after['host_evidence']['gateway_attempt'],self.before['host_evidence']['gateway_attempt']);self.assertEqual(after['completion_state'],'none');self.assertEqual(after['stop_state'],'stopped');self.assertIsNone(after['in_flight_request'])
  self.assertEqual(self.release()['outcome'],'replayed');retained_preinitialization_release(f.app,f.app._read(self.schedule))
  proof=permits_preinitialization_role(f.app,schedule_id=self.schedule,assignment=self.manager,project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),request_key='separate-delivery');self.assertEqual(proof['original_result_sha256'],scope['result_sha256'])
  prepared=f.app.prepare_role(role='manager',project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),assignment_ref=self.manager.ref.to_dict(),generation=1,mandate_ref=self.mandate,context_refs=(self.guide,self.mandate),request_key='separate-delivery',instruction='Useful same-task delivery',model='gpt-test',reasoning='high',profile='workspace-write',native_session_id=None,binding_schedule_id=self.schedule)
  self.assertNotEqual(prepared['schedule_id'],self.schedule);self.assertEqual(f.app._read(prepared['schedule_id']).execution_mode,'fresh_manager');self.assertEqual(f.provider.calls,[])
 def test_other_failure_or_initializer_or_unknown_cannot_release(self):
  for name,fn in [('error',lambda a:a['result']['error'].update(message='other failure')),('native',lambda a:a['result'].update(native_session_id='started')),('raw',lambda a:a['result'].update(raw_result={'initializer':True})),('unknown',lambda a:a['result'].update(outcome='unknown')),('timeout',lambda a:a['result'].update(timeout=True)),('authorized',lambda a:a.update(delivery_authorization={'status':'authorized'}))]:
   with self.subTest(name=name):
    original=deepcopy(self.before['host_evidence']);due=self.f.app._read(self.schedule);host=deepcopy(original);fn(host['gateway_attempt']);self.f.port.save_due(self.schedule,replace(due,host_evidence=host).to_dict(),request_id='negative-'+name,expected_version=due.version)
    with self.assertRaises(OccurrencePreparationError):self.release()
  self.assertEqual(self.f.provider.calls,[])
 def test_changed_binding_and_missing_or_modified_proof_rejected(self):
  self.release();f=self.f;due=f.app._read(self.schedule)
  with self.assertRaises(OccurrencePreparationError):permits_preinitialization_role(f.app,schedule_id=self.schedule,assignment=self.manager,project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),request_key='foreign-key')
  with self.assertRaises(OccurrencePreparationError):permits_preinitialization_role(f.app,schedule_id=self.schedule,assignment=self.manager,project_ref={**f.project.ref.to_dict(),'id':'foreign'},task_ref=f.task.ref.to_dict(),request_key='separate-delivery')
  self.change(lambda a:a['result'].update(requested_model='other'))
  with self.assertRaises(OccurrencePreparationError):retained_preinitialization_release(f.app,f.app._read(self.schedule))
 def test_uninitialized_manager_without_disposition_is_still_denied(self):
  f=self.f
  with self.assertRaises(OccurrencePreparationError):f.app.prepare_role(role='manager',project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),assignment_ref=self.manager.ref.to_dict(),generation=1,mandate_ref=self.mandate,context_refs=(self.guide,self.mandate),request_key='without-proof',instruction='Work',model='gpt-test',reasoning='high',profile='workspace-write',native_session_id=None)
  self.assertEqual(f.provider.calls,[])
 def test_restart_hold_released_only_with_unchanged_canonical_disposition(self):
  from otto.portfolio.execution_host import ExecutionHost
  f=self.f;host=ExecutionHost(directory=f.temporary.name+'/restart-ipc',handler=lambda x:None,bounded_transports=True)
  host.restore_execution(f.app,f.app._read(self.schedule));self.assertIn(self.schedule,host._capacity_holds)
  self.release();host.restore_execution(f.app,f.app._read(self.schedule));self.assertNotIn(self.schedule,host._capacity_holds)
  self.change(lambda a:a['result'].update(observed_model='unexpected-start'))
  host.restore_execution(f.app,f.app._read(self.schedule));self.assertIn(self.schedule,host._capacity_holds)
  self.assertEqual(f.provider.calls,[])
 def test_exact_historical_disposition_survives_same_generation_resource_adoption(self):
  self.release();f=self.f;old=self.manager
  current=f.app.assignments.adopt_resources(old.ref,resources=old.payload['resource_adoptions'],expected_revision=old.revision,expected_generation=1,logical_request_key='next-supported-BASE',actor=f.actor)
  self.assertNotEqual(current.ref,old.ref)
  body=retained_preinitialization_release(f.app,f.app._read(self.schedule));self.assertEqual(body['scope']['assignment_ref'],old.ref.to_dict())
  permits_preinitialization_role(f.app,schedule_id=self.schedule,assignment=current,project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),request_key='separate-delivery')
  with patch('otto.portfolio.operating_setup.authenticated_adoption_ancestor',return_value=False):
   with self.assertRaises(OccurrencePreparationError):retained_preinitialization_release(f.app,f.app._read(self.schedule))
  with self.assertRaises(OccurrencePreparationError):permits_preinitialization_role(f.app,schedule_id=self.schedule,assignment=replace(current,generation=2),project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),request_key='separate-delivery')
  self.assertEqual(f.provider.calls,[])

if __name__=='__main__':unittest.main()
