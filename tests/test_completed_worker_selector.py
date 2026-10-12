"""Real owner/adapter/native-fixture capture across a manager selector change."""
from copy import deepcopy
from unittest.mock import patch
import unittest
from otto.attention import DueRecord
from otto.agents.owner_runtime import OwnerAuthorizedRoleCapture
from otto.portfolio.execution_operations import prepare_current_assignment_occurrence, build_manager_callback_due
from tests import test_execution_application as application

class CompletedWorkerSelectorTests(unittest.TestCase):
 def fixture(self):
  f=application.ExecutionApplicationTests(); f.setUp(); self.addCleanup(f.doCleanups)
  manager,guide,mandate=f.role_handles('manager','manager',None)
  at=f.app.clock().isoformat()
  target={'host':'local','native_id':'manager-session','role':'manager','principal':'manager',
   'project_ref':f.project.ref.to_dict(),'task_ref':f.task.ref.to_dict(),
   'assignment_ref':manager.ref.to_dict(),'mandate_ref':mandate,
   'requested_model':'gpt-test','requested_reasoning':'high','requested_profile':'workspace-write'}
  initial=DueRecord(schedule_id='manager-A',recipient='manager',instruction='Inspect project',
   profile='workspace-write',anchor=at,due_at=at,last_covered_slot=0,invocation_identity='manager-A',
   in_flight_request='manager-A',delivery_state='ready',owner='manager',project_ref=f.project.id,
   manager_ref='manager',assignment_ref=manager.ref.to_dict(),generation=1,target=target,role='manager',
   lifecycle_owner='manager',execution_mode='continue_existing',requested_model='gpt-test',requested_reasoning='high',
   context_refs=(guide,mandate),result_owner='manager',timeout_seconds=1200)
  prepare_current_assignment_occurrence(due_port=f.port,assignments=f.app.assignments,binding=f.binding,
   due=initial,assignment_ref=manager.ref.to_dict(),assignment_owner='manager',operation='resume',
   lifecycle='resume',request_key='manager-A')
  self.assertEqual(f.app.start(schedule_id='manager-A')['outcome'],'succeeded')
  callback=build_manager_callback_due(f.app._read('manager-A'),schedule_id='manager-B',request_key='manager-B',
   assignment_ref=manager.ref.to_dict(),guide_ref=guide,mandate_ref=mandate,due_at=at,timeout_seconds=1200)
  prepare_current_assignment_occurrence(due_port=f.port,assignments=f.app.assignments,binding=f.binding,due=callback,
   assignment_ref=manager.ref.to_dict(),assignment_owner='manager',operation='resume',lifecycle='callback',request_key='manager-B')
  setup={'schema':'otto.operating-setup.v1','mode':'manual','roles':{'manager':'manager-A'},
   'advisor_policy':{'mode':'disabled','reason':'Fixture owner'},'acceptance_tasks':[]}
  self.assertEqual(f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(),setup=setup,
   request_key='setup')['outcome'],'prepared')
  request=deepcopy(f.request()); request['instruction_contract']['authority']['owner_actor']='capture-worker'
  worker=f.app.assign_worker(**{**request,'request_key':'capture-worker','principal':'capture-worker'})
  return f,worker
 def run_capture(self,*,legacy=False,mutation=None):
  f,worker=self.fixture(); original=application.ProviderBinding.execute; before=f.port.read_due(worker['schedule_id'])
  admission=[]
  def transport(binding,request):
   result=original(binding,request)
   if binding.options.get('delivered_brief') and request.identity.logical_agent_id=='capture-worker':
    due=f.port.read_due(worker['schedule_id']); admission.append(deepcopy(due['host_evidence']['gateway_attempt']['delivery_admission']))
    self.assertTrue(admission[-1]['native_turn_started']); self.assertEqual(due['assignment_ref'],before['assignment_ref'])
    if mutation: mutation(f,worker)
    else:
     sync=f.app.synchronize_manual_manager_occurrence(schedule_id='manager-B')
     self.assertEqual(sync['outcome'],'updated',sync)
   return result
  completed=OwnerAuthorizedRoleCapture.verify_completed_delivery
  def old(capture,*args):
   return capture.verify_delivery(*args) if capture.role=='worker' else completed(capture,*args)
  with patch.object(application.ProviderBinding,'execute',transport), patch.object(OwnerAuthorizedRoleCapture,'verify_completed_delivery',old if legacy else completed):
   result=f.app.start(schedule_id=worker['schedule_id'])
  return f,worker,result,admission
 def test_old_capture_reproduces_unknown_and_fixed_capture_settles_once(self):
  f,worker,result,seen=self.run_capture(legacy=True)
  self.assertEqual(result['outcome'],'unknown',result.get('error'))
  self.assertIn('adopted operating setup changed before delivery',str(result))
  f,worker,result,seen=self.run_capture()
  self.assertEqual(result['outcome'],'succeeded',result.get('error'))
  self.assertEqual(len(seen),1)
  calls=len(f.provider.calls)
  self.assertEqual(f.app.start(schedule_id=worker['schedule_id'])['outcome'],'replayed')
  self.assertEqual(len(f.provider.calls),calls)
 def test_unchanged_setup_review_override_is_not_capture_authority(self):
  def override(f,worker):
   from herzchen.domains.assessment import AssessmentModule
   from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
   from otto.portfolio.manager_journey_command import ManagerJourneyCommands
   from otto.portfolio.operating_setup import read_setup
   criterion=AssessmentModule(f.store,actor=f.actor).declare_scope('capture-review',parent_obligation=f.task.ref,
    protocol='fixture',criteria=[{'id':'C'}],designated_approver='manager',
    policy={'required_for_completion':True},logical_request_key='capture-review')
   manager=f.port.read_due('manager-A')['assignment_ref']
   state={'authority':f.actor.authority,'project_ref':f.project.ref.to_dict(),'assignment_ref':manager,
    'manager':'manager','manager_generation':1,'task_refs':{'T':f.task.ref.to_dict()},
    'criterion_refs':{'C':criterion.criterion_refs[0].to_dict()}}
   base={'kind':'owner_local_bookkeeping','purpose':'Fixture bookkeeping','local_only':True,
    'capacity_units':1,'cumulative_allowance_units':1,'pool_id':'main-review','task_criterion_pairs':['T/C']}
   state['assessment_policy']=deepcopy(base)
   supplemental={**base,'pool_id':'separate-review-only'}
   policy=LocalAssessmentPolicy.from_run_config(supplemental,state=state)
   f.owner.create_manager_assessment_pool(project_ref=state['project_ref'],task_ref=state['task_refs']['T'],
    manager_assignment_ref=manager,manager_actor='manager',manager_generation=1,
    logical_request_key='review-override',assessment_policy=policy)
   state['task_assessment_supplements']={'T':{'policy':supplemental,'binding':{
    'project_ref':state['project_ref'],'task_ref':state['task_refs']['T'],'assignment_ref':manager,
    'principal':'manager','generation':1,'pool_ref':policy.pool_ref.to_dict(),
    'criterion_refs':[state['criterion_refs']['C']],'allocation_key':'review-override'}}}
   before=read_setup(f.app.portfolio.operations,state['project_ref'])
   commands=ManagerJourneyCommands(owner=f.owner,portfolio=f.app.portfolio,state=state)
   self.assertEqual(commands._review_policy('T').pool_ref.id,'separate-review-only')
   self.assertEqual(read_setup(f.app.portfolio.operations,state['project_ref']),before)
   self.assertEqual(state['assessment_policy'],base)
  f,worker,result,seen=self.run_capture(mutation=override)
  self.assertEqual(result['outcome'],'succeeded',result.get('error'))
 def test_other_setup_change_remains_unknown(self):
  from otto.portfolio.operating_setup import read_setup,setup_reference
  def mutate(f,worker):
   setup=read_setup(f.app.portfolio.operations,f.project.ref.to_dict()); setup['advisor_policy']['reason']='changed'
   ref=f.app.portfolio.operations.content_port.read(setup_reference(f.project.ref.to_dict()))['current_revision']
   changed=f.app.compose_operating_setup(project_ref=f.project.ref.to_dict(),operation='update',setup=setup,
    request_key='other-setup',expected_setup_ref=ref)
   self.assertEqual(changed['outcome'],'updated',changed)
  f,worker,result,seen=self.run_capture(mutation=mutate)
  self.assertEqual(result['outcome'],'unknown',result.get('error'))
  self.assertIn('changed beyond its manager selector',str(result))
 def test_reassigned_worker_is_not_captured(self):
  from herzchen.contracts import ResourceRef
  def mutate(f,worker):
   f.app.assignments.reassign(ResourceRef.from_dict(worker['assignment_ref']),principal='foreign',session=None,
    reason='fixture changed worker',expected_generation=1,logical_request_key='foreign-worker',actor=f.actor)
  f,worker,result,seen=self.run_capture(mutation=mutate)
  self.assertEqual(result['outcome'],'unknown',result.get('error'))

 def test_missing_original_native_admission_remains_unknown(self):
  from otto.agents.gateway import OwnerDueRecordAttemptCapture
  original=OwnerDueRecordAttemptCapture.record_delivery_admission
  def omit(capture,*args):
   return {} if capture.role=='worker' else original(capture,*args)
  with patch.object(OwnerDueRecordAttemptCapture,'record_delivery_admission',omit):
   f,worker,result,seen=self.run_capture()
  self.assertEqual(result['outcome'],'unknown',result.get('error'))
 def test_foreign_manager_selector_and_changed_generation_refuse_without_effect(self):
  for field,value in [('recipient','foreign'),('generation',2),('lifecycle_owner','foreign')]:
   with self.subTest(field=field):
    f,worker=self.fixture()
    from otto.portfolio.operating_setup import read_setup
    setup=read_setup(f.app.portfolio.operations,f.project.ref.to_dict()); new=deepcopy(setup)
    new['roles']['manager']='manager-B'; bad=deepcopy(f.port.read_due('manager-B'));bad[field]=value
    read=f.app.runtime.due_port.read_due
    before=f.store.consumer().snapshot_counts()
    from types import SimpleNamespace
    with patch.object(f.app.runtime,'due_port',SimpleNamespace(read_due=lambda key:bad if key=='manager-B' else read(key))):
     with self.assertRaises(Exception): f.app.runtime._verify_completed_worker_selector(setup,new,f.project.ref.to_dict())
    self.assertEqual(before,f.store.consumer().snapshot_counts())
