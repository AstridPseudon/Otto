"""Exact historical retain-before-initializer failure and one same-worker delivery."""
from copy import deepcopy
from dataclasses import replace
import unittest
from otto.portfolio.worker_custody import DRAIN_PREINITIALIZATION_ERROR, inspect_drain_preinitialization_worker, release_drain_preinitialization_worker, retained_preinitialization_release
from otto.portfolio.execution_operations import OccurrencePreparationError
from tests import test_execution_application as fixtures

class WorkerDrainPreinitializationTests(unittest.TestCase):
 def setUp(self):
  self.f=f=fixtures.ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups)
  seed=f.app.assign_worker(**f.request());self.seed=seed;due=f.app._read(seed['schedule_id']);self.schedule=due.schedule_id
  result={'assignment_ref':due.assignment_ref,'generation':due.generation,'logical_request_key':due.in_flight_request,
   'outcome':'failed','operation':'invoke','error':deepcopy(DRAIN_PREINITIALIZATION_ERROR),'unknown_reason':DRAIN_PREINITIALIZATION_ERROR['message'],
   'delivery_state':'unknown','replayed':False,'physical_session_id':None,'native_session_id':None,'observed_model':None,'observed_reasoning':None,'timeout':False,
   'logical_agent_id':due.recipient,'owner':due.recipient,'project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],
   'requested_model':due.requested_model,'requested_reasoning':due.requested_reasoning,'requested_profile':due.profile,
   'resource_evidence':{'brief':{'context':{'canonical_snapshot':{'native_session':None,'assignment_ref':due.assignment_ref,'generation':due.generation,'task_ref':due.target['task_ref']}}}}}
  attempt={'state':'result','assignment_ref':due.assignment_ref,'generation':due.generation,'logical_request_key':due.in_flight_request,'result':result}
  f.port.save_due(self.schedule,replace(due,host_evidence={**due.host_evidence,'gateway_attempt':attempt}).to_dict(),request_id='retained-drain',expected_version=due.version)
  self.before=f.port.read_due(self.schedule)
 def release(self):return release_drain_preinitialization_worker(self.f.app,schedule_id=self.schedule,request_key='retire-drain',fresh_request_key='same-worker-delivery')
 def prepare(self,**overrides):
  due=self.f.app._read(self.schedule)
  args=dict(role='worker',project_ref=due.target['project_ref'],task_ref=due.target['task_ref'],assignment_ref=due.assignment_ref,generation=due.generation,mandate_ref=due.target['mandate_ref'],context_refs=due.context_refs,request_key='same-worker-delivery',instruction=due.instruction,model=due.requested_model,reasoning=due.requested_reasoning,profile=due.profile,native_session_id=None,binding_schedule_id=self.schedule,allowance_ref=due.allowance_ref)
  args.update(overrides);return self.f.app.prepare_role(**args)
 def test_exact_retirement_and_same_assignment_delivery_preserve_failure(self):
  scope=inspect_drain_preinitialization_worker(self.f.app,schedule_id=self.schedule);self.assertFalse(scope['initializer_occurred']);self.release()
  due=self.f.app._read(self.schedule);self.assertEqual(due.host_evidence['gateway_attempt'],self.before['host_evidence']['gateway_attempt']);self.assertEqual(due.completion_state,'none')
  self.assertEqual(self.release()['outcome'],'replayed');retained_preinitialization_release(self.f.app,due)
  new=self.prepare();fresh=self.f.app._read(new['schedule_id']);self.assertNotEqual(fresh.schedule_id,self.schedule);self.assertEqual(fresh.assignment_ref,due.assignment_ref);self.assertEqual(fresh.execution_mode,'fresh_bounded_worker');self.assertEqual(fresh.allowance_ref,due.allowance_ref);self.assertEqual(self.f.provider.calls,[])
 def test_changed_model_allowance_or_guard_cannot_gain_recovery(self):
  self.release()
  for change in ({'model':'foreign'},{'allowance_ref':{'authority':'foreign','kind':'work.allowance','id':'foreign','revision':'rev-1'}},{'request_key':'other'}):
   with self.subTest(change=change),self.assertRaises(OccurrencePreparationError):self.prepare(**change)
  due=self.f.app._read(self.schedule);host=deepcopy(due.host_evidence);host['gateway_attempt']['result']['physical_session_id']='initialized'
  self.f.port.save_due(self.schedule,replace(due,host_evidence=host).to_dict(),request_id='tamper',expected_version=due.version)
  with self.assertRaises(OccurrencePreparationError):retained_preinitialization_release(self.f.app,self.f.app._read(self.schedule))
 def test_session_absence_alone_does_not_prove_draining_failure(self):
  for error in ({'code':'adapter_error','message':'another error','operation':'invoke'},{**DRAIN_PREINITIALIZATION_ERROR,'operation':'resume'}):
   due=self.f.app._read(self.schedule);host=deepcopy(due.host_evidence);host['gateway_attempt']['result']['error']=error
   self.f.port.save_due(self.schedule,replace(due,host_evidence=host).to_dict(),request_id='wrong-'+error['operation'],expected_version=due.version)
   with self.assertRaises(OccurrencePreparationError):self.release()
