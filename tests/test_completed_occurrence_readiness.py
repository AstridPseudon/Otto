"""Readiness follows one authentic settled completion input; effects stay strict."""
import copy,hashlib,json,os,unittest
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio.owner_readers import completed_occurrence_task_reader,OwnerRoleRuntimeError
from herzchen.content.instructions import validate_instruction_content
from tests import test_manager_journey_command as fixture

class CompletedOccurrenceReadinessTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture.ManagerJourneyCommandTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  f=self.f.application;state=self.f.fixture.state;self.state=state
  task=f.owner.graph.reader.get_identity(ResourceRef.from_dict(state['task_refs']['PA01']))
  brief={'context':{'project_state':{'task':{'ref':task.ref.to_dict(),'payload':copy.deepcopy(task.payload),'lifecycle':task.payload['lifecycle']}}}}
  digest=hashlib.sha256(json.dumps(brief,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  result={'outcome':'succeeded','context_digest_verified':True,'physical_session_id':'retained-manager','observed_turn_id':'fixture-turn','assignment_ref':state['assignment_ref'],'generation':1,'task_ref':task.ref.to_dict(),'project_ref':state['project_ref'],'resource_evidence':{'brief':brief,'brief_sha256':digest}}
  self.due=SimpleNamespace(role='manager',completion_state='succeeded',stop_state='completed',in_flight_request=None,assignment_ref=state['assignment_ref'],generation=1,recipient='manager',target={'task_ref':task.ref.to_dict(),'project_ref':state['project_ref']},host_evidence={'gateway_attempt':{'result':result,'delivery_authorization':{'brief_sha256':digest},'delivery_admission':{'native_turn_started':True,'physical_session_id':'retained-manager','observed_turn_id':'fixture-turn'}}})
  reviewed=self.f.commands.review_task(self.f.request(key='complete-before-readiness'))
  self.assertEqual(reviewed['completion']['outcome'],'completed')
  self.assignment=self.f.fixture.manager
 def test_real_committed_completion_allows_readonly_snapshot_and_rejects_drift(self):
  f=self.f.application;before=f.owner.graph.reader.snapshot_counts()
  read=completed_occurrence_task_reader(f.owner.graph.reader,self.due,self.assignment)
  task=self.due.target['task_ref'];self.assertEqual(read({k:task[k] for k in ('authority','kind','id')})['ref'],task)
  runtime=f.owner.role_runtime(due_port=f.port,adapter=f.app.runtime.adapter)
  self.assertEqual(runtime.completed_task_readiness(self.due)({'authority':task['authority'],'kind':task['kind'],'id':task['id']})['ref'],task)
  # The invocation's ordinary task reader still observes the actual rev2 head.
  self.assertNotEqual(runtime._task_reader(self.state['project_ref'],task)({k:task[k] for k in ('authority','kind','id')})['ref'],task)
  for mutate in (lambda d:setattr(d,'generation',2),lambda d:setattr(d,'recipient','foreign'),lambda d:setattr(d,'stop_state','active'),lambda d:d.target['task_ref'].update(revision='rev-999'),lambda d:d.host_evidence['gateway_attempt']['delivery_authorization'].update(brief_sha256='0'*64),lambda d:d.host_evidence['gateway_attempt']['result']['resource_evidence']['brief']['context']['project_state']['task']['payload'].update(title='forged')):
   altered=copy.deepcopy(self.due);mutate(altered)
   with self.assertRaises(OwnerRoleRuntimeError):completed_occurrence_task_reader(f.owner.graph.reader,altered,self.assignment)
  foreign=copy.deepcopy(self.due)
  foreign.target['task_ref']['id']='foreign-task'
  self.assertIsNone(completed_occurrence_task_reader(f.owner.graph.reader,foreign,self.assignment))
  # A caller cannot make changed delivered instructions look authentic by
  # recomputing the brief digest and authorization around the altered snapshot.
  altered=copy.deepcopy(self.due)
  resource=altered.host_evidence['gateway_attempt']['result']['resource_evidence']
  delivered=resource['brief']['context']['project_state']['task']['payload']
  delivered['title']='Changed instructions'
  digest=hashlib.sha256(json.dumps(resource['brief'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  resource['brief_sha256']=digest
  altered.host_evidence['gateway_attempt']['delivery_authorization']['brief_sha256']=digest
  with self.assertRaises(OwnerRoleRuntimeError):completed_occurrence_task_reader(f.owner.graph.reader,altered,self.assignment)
  self.assertEqual(f.owner.graph.reader.snapshot_counts(),before)
  self.assertEqual(f.provider.calls,[])

 def test_role_runtime_reuses_owner_limit_service_without_descriptor_growth(self):
  f=self.f.application
  before=len(os.listdir('/dev/fd'))
  for _ in range(200):
   f.owner.role_runtime(due_port=f.port,adapter=f.app.runtime.adapter)
  after=len(os.listdir('/dev/fd'))
  self.assertLessEqual(after-before,3,f'role_runtime leaked {after-before} file descriptors')

 def test_manager_admission_completion_keeps_next_manager_start_live(self):
  journey=fixture.ManagerJourneyCommandTests();journey.setUp();self.addCleanup(journey.doCleanups)
  f=journey.application;graph=f.owner.graph;state=journey.fixture.state
  task_a=graph.create_task(f.project.ref,title='Admitted manager task A',
   logical_request_key='readiness-create-task-a',actor=f.actor).ref
  state['task_refs']['PA01']=task_a.to_dict();f.task=graph.current(task_a)
  from herzchen.domains.assessment import AssessmentModule
  AssessmentModule(f.store,actor=f.actor).declare_scope('readiness-scope-a',parent_obligation=task_a,
   protocol='readiness-manager-completion',criteria=[ResourceRef.from_dict(state['criterion_refs']['C01'])],designated_approver='manager',
   policy={'required_for_completion':True},logical_request_key='readiness-scope-a')
  assignments=f.owner.assignments.command_port
  worker=f.app.assign_worker(**f.request())
  guide_a=worker['guide_ref'];guide_content=f.owner.content.read(ResourceRef.from_dict(guide_a))['content']
  base_assignment=assignments.get(ResourceRef.from_dict(state['assignment_ref']))
  assignment_a=assignments.adopt_resources(base_assignment.ref,resources=[{'resource_ref':guide_a,
   'resource_name':guide_content['name'],'content_digest':validate_instruction_content(guide_content),'required':True}],
   expected_revision=base_assignment.revision,expected_generation=base_assignment.generation,
   logical_request_key='readiness-manager-adopt-guide',actor=f.actor)
  def mandate_for(task,request_id):
   contract=f.request()['instruction_contract']
   contract['authority']['owner_actor']='manager'
   contract['authority']['effect_profile']='workspace-write-manager'
   contract['allowed_operations'].append('canonical_manager_commands')
   contract['authority']['permitted_effects'].append('canonical_manager_commands')
   contract['task_ref']=task.to_dict()
   return f.app.portfolio.create_document(state['project_ref'],actor='manager',request_id=request_id,
    document_id=request_id,role='mandate',content={'role':'manager','scope_ref':state['project_ref'],
     'status':'active','dispatch_enabled':True,'task_ref':task.to_dict(),
     'assignment_ref':assignment_a.ref.to_dict(),'generation':assignment_a.generation,
     'brief':{'role':'manager','mandate':'Advance remaining work'},'instruction_contract':contract
    })['record']['payload']['current_revision']
  mandate_a=mandate_for(task_a,'readiness-manager-a-mandate')
  prepared_a=f.app.prepare_role(role='manager',project_ref=state['project_ref'],task_ref=task_a.to_dict(),
   assignment_ref=assignment_a.ref.to_dict(),generation=1,mandate_ref=mandate_a,
   context_refs=(guide_a,mandate_a),request_key='readiness-manager-a',instruction='Review task A',
   model='gpt-test',reasoning='high',profile='workspace-write',native_session_id=assignment_a.session)
  first=f.app.start(schedule_id=prepared_a['schedule_id'])
  self.assertEqual(first['outcome'],'succeeded',first)
  self.assertEqual(len(f.provider.calls),1)
  # create_task stamps rev-1 as admitted in this fixture. Advance a metadata
  # only unadmitted rev-2 after preparation, then exercise the real admission
  # writer against that exact reviewed revision.
  unadmitted=graph.revise(task_a,metadata_namespaces={},
   logical_request_key='readiness-unadmit-revision-two',actor=f.actor)
  review_effort=graph.create_effort(f.project.ref,title='Admit manager task A',
   logical_request_key='readiness-admit-review',actor=f.actor)
  admitted=graph.admit(unadmitted.ref,revision=unadmitted.revision,review_ref=review_effort.ref,
   logical_request_key='readiness-admit-a',actor=f.actor)['task_ref']
  self.assertNotEqual(admitted.revision,unadmitted.revision)
  state['task_refs']['PA01']=admitted.to_dict()
  state['assignment_ref']=assignment_a.ref.to_dict()
  state['manager_generation']=assignment_a.generation
  completed=journey.commands.review_task(journey.request(alias='PA01',key='readiness-complete-a'))
  self.assertEqual(completed['completion']['outcome'],'completed',completed)
  state['task_refs']['PA01']=completed['completion']['task_ref']
  due=f.port.read_due(prepared_a['schedule_id'])
  runtime=f.owner.role_runtime(due_port=f.port,adapter=f.app.runtime.adapter)
  historical_reader=runtime.completed_task_readiness(SimpleNamespace(**due))
  self.assertIsNotNone(historical_reader)
  self.assertEqual(historical_reader({k:task_a.to_dict()[k] for k in ('authority','kind','id')})['ref'],task_a.to_dict())
  task_b=ResourceRef.from_dict(state['task_refs']['PA06'])
  AssessmentModule(f.store,actor=f.actor).declare_scope('readiness-scope-b',parent_obligation=task_b,
   protocol='readiness-manager-next',criteria=[ResourceRef.from_dict(state['criterion_refs']['C09'])],
   designated_approver='manager',policy={'required_for_completion':True},logical_request_key='readiness-scope-b')
  from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
  policy=LocalAssessmentPolicy.from_run_config(state['assessment_policy'],state=state)
  f.owner.create_manager_assessment_pool(project_ref=state['project_ref'],task_ref=task_b.to_dict(),
   manager_assignment_ref=assignment_a.ref.to_dict(),manager_actor='manager',manager_generation=1,
   logical_request_key='readiness-next-manager-pool',assessment_policy=policy)
  assignment_b=assignment_a
  mandate_b=mandate_for(task_b,'readiness-manager-b-mandate')
  guide_b=guide_a
  prepared_b=f.app.prepare_role(role='manager',project_ref=state['project_ref'],task_ref=task_b.to_dict(),
   assignment_ref=assignment_b.ref.to_dict(),generation=1,mandate_ref=mandate_b,
   context_refs=(guide_b,mandate_b),request_key='readiness-manager-b',instruction='Review task B',
   model='gpt-test',reasoning='high',profile='workspace-write',native_session_id=assignment_b.session)
  setup={'schema':'otto.operating-setup.v1','mode':'manual','roles':{'manager':prepared_b['schedule_id']},
   'advisor_policy':{'mode':'disabled','reason':'No advisor authorized'},
   'acceptance_tasks':[task_a.to_dict(),task_b.to_dict()]}
  policy_app=f.owner.execution_application(due_port=f.port,adapter=f.app.runtime.adapter,
   clock=f.app.clock,assessment_policy=policy)
  prepared_setup=policy_app.prepare_operating_setup(project_ref=state['project_ref'],setup=setup,
   request_key='readiness-historical-setup')
  self.assertEqual(prepared_setup['outcome'],'prepared',prepared_setup)
  ready=policy_app.read_operating_setup(project_ref=state['project_ref'])
  self.assertTrue(ready['ready'],ready['blockers'])
  second=policy_app.start(schedule_id=prepared_b['schedule_id'])
  self.assertEqual(second['outcome'],'succeeded',second)
  self.assertEqual(len(f.provider.calls),2)
