"""Real owner Store: issued same-root directive save/adopt, with no execution."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from herzchen.contracts import ResourceRef
from herzchen.domains.work.assignments import ResponsibilityAssignments
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.orchestrator_client import OrchestratorAdmissions, ScopedOrchestratorClient
from otto.portfolio.tests.test_portfolio_direction import PortfolioDirectionTests

class RootDirectionClientTests(unittest.TestCase):
 def setUp(self):
  self.f=PortfolioDirectionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  original=ResponsibilityAssignments.assign
  def assign(assignment_port,*args,**kw):
   if kw.get('role')=='orchestrator':kw.setdefault('session',{'host':'codex','native_id':'own-root-chat'})
   return original(assignment_port,*args,**kw)
  with patch.object(ResponsibilityAssignments,'assign',assign):
   self.root,self.subject,self.oldpin,project=self.f.setup_portfolio()
  self.owner=PortfolioOwnerBootstrap(self.f.store,binding=self.f.binding,owner_actor='owner',portfolio_ref=self.root.scope,main_assignment_ref=self.root.ref,expected_main_principal='owner')
  second=self.owner.graph.create_project(title='Other pending',logical_request_key='second')
  self.owner.consumer_operations().execute('work.orchestrator.projects.attach',{'target_assignment_ref':self.root.ref.to_dict(),'target_assignment_revision':self.root.revision,'target_assignment_generation':1,'projects':[{'project_ref':second.ref.to_dict(),'project_version':second.version,'assignment_ref':None,'assignment_revision':None,'assignment_generation':None}]},request_id='second-join',actor='owner')
  self.projects=[self.owner.graph.get(project.ref),self.owner.graph.get(second.ref)]
  self.state={'orchestrator_assignment_ref':self.root.ref.to_dict(),'root_help_binding':{'assignment_ref':self.root.ref.to_dict(),'generation':1}}
  self.server=SimpleNamespace(owner=self.owner,state=self.state,_execution=None,portfolio=None,due_port=None,_save_state=lambda:None)
  self.service=ManagerJourneyService(server=self.server,host=None,run_path=self.f.path.parent,workspace=self.f.path.parent)
  self.admissions=OrchestratorAdmissions(self.owner,main_assignment_ref=self.root.ref.to_dict(),generation=1)
  self.binding=self.admissions.admit_current_root(actor=self.owner.owner_actor,conversation_ref=self.root.session,operations=['whoami','direction-read','direction-draft','direction-update'],request_key='own-policy')
  self.client=ScopedOrchestratorClient(owner=self.owner,binding=self.binding,handlers={op:self.service.root_direction_client for op in self.binding['operations']})
 def read(self):return self.client.call({'operation':'direction-read','request_key':'read'})
 def intent(self):
  d=self.read()['assignment_direction']
  return {'operation':'direction-update','request_key':'expanded-plan','request':{'content':{'schema':'herzchen.instructions.v1','name':'DIRECTION','entrypoint':'ORCHESTRATOR.md','instructions':'Pending plan','bundle_digest':__import__('hashlib').sha256(b'Pending plan').hexdigest(),'export_manifest_digest':'fixture','required':True,'supporting_refs':[]},'expected_direction_ref':d['latest_ref'],'expected_binding_ref':d['binding_ref']}}
 def test_real_save_adopt_effective_and_all_joins_preserved(self):
  before=[deepcopy(p.payload)for p in self.projects];intent=self.intent();intent['request']['content']['instructions']='Expanded plan: pending A-D and pack; task dependencies first; no activation.'
  import hashlib
  intent['request']['content']['bundle_digest']=hashlib.sha256(intent['request']['content']['instructions'].encode()).hexdigest()
  result=self.client.call(intent)
  self.assertEqual(result['outcome'],'synchronized');self.assertFalse(result['provider_called'])
  self.assertEqual(result['effective_context']['assignment_adopted_ref'],result['draft_ref'])
  self.assertEqual(result['project_join_count'],2);self.assertFalse(result['tasks_created']);self.assertFalse(result['allowances_changed']);self.assertFalse(result['project_activation'])
  self.assertEqual(result['assignment_ref']['id'],self.root.ref.id);self.assertEqual(result['generation'],1)
  for previous,p in zip(before,self.projects):
   current=self.owner.graph.get(p.ref);self.assertEqual(current.payload['metadata']['otto_orchestrator']['assignment_ref'],result['assignment_ref'])
   previous['metadata'].pop('otto_orchestrator');now=deepcopy(current.payload);now['metadata'].pop('otto_orchestrator');self.assertEqual(previous,now)
   self.assertEqual(now['lifecycle'],'pending');self.assertFalse(now['tasks'])
  # Old policy cannot silently become authority over a later root revision.
  with self.assertRaises(PermissionError):self.read()
  current=self.owner.assignments.get(result['assignment_ref'])
  refreshed=OrchestratorAdmissions(self.owner,main_assignment_ref=current.ref.to_dict(),generation=1).admit_current_root(actor=self.owner.owner_actor,conversation_ref=current.session,operations=['direction-read'],request_key='qualified-current-policy')
  client=ScopedOrchestratorClient(owner=self.owner,binding=refreshed,handlers={'direction-read':self.service.root_direction_client})
  self.assertEqual(client.call({'operation':'direction-read','request_key':'effective'})['assignment_direction']['effective_ref'],result['draft_ref'])
 def test_stale_pins_foreign_actor_conversation_and_self_grant_fail_before_effect(self):
  counts=self.f.store.consumer().snapshot_counts()
  for change in [{'expected_binding_ref':{'authority':'owner','kind':'document-association','id':'foreign','revision':'rev-1'}},{'expected_direction_ref':{**self.oldpin.to_dict(),'revision':'rev-stale'}}]:
   req=self.intent();req['request'].update(change)
   with self.assertRaises(PermissionError):self.client.call(req)
   self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
  for actor,chat in [(self.f.binding.authenticated_actor('foreign'),self.root.session),(self.owner.owner_actor,{'host':'codex','native_id':'different'})]:
   with self.assertRaises(PermissionError):self.admissions.admit_current_root(actor=actor,conversation_ref=chat,operations=['direction-update'],request_key='self')
  with self.assertRaises(PermissionError):self.client.call({**self.intent(),'project_id':self.projects[0].id})
  forged={**self.binding,'generation':2}
  client=ScopedOrchestratorClient(owner=self.owner,binding=forged,handlers={'direction-update':self.service.root_direction_client})
  with self.assertRaises(PermissionError):client.call(self.intent())
  # Ordinary secondary-root enrollment cannot ask for the owner plan capability.
  req=self.admissions.request(conversation_ref={'host':'codex','native_id':'secondary'},requested_project_ids=[self.projects[0].id],request_key='secondary')
  with self.assertRaises(PermissionError):self.admissions.admit(actor=self.owner.owner_actor,request_ref=req['request_ref'],project_ids=[self.projects[0].id],operations=['direction-update'],request_key='no-escalation')
 def test_real_host_boundary_preserves_native_obligations(self):
  from otto.portfolio.execution_host import ExecutionHost
  host=ExecutionHost(directory=self.f.path.parent/'host',handler=lambda request:None,bounded_transports=True)
  host._capacity_holds['retained-unknown']={'schedule_id':'retained-unknown'}
  self.assertEqual(host.prepare_root_direction_adoption()['outcome'],'held');self.assertFalse(host.draining)
  self.assertIn('retained-unknown',host._capacity_holds)
  host._capacity_holds.clear();host._external_waiting=1
  self.assertEqual(host.prepare_root_direction_adoption()['outcome'],'held');self.assertFalse(host.draining)
  host._external_waiting=0;host._executions['admitted']={'running':True}
  self.assertEqual(host.prepare_root_direction_adoption()['outcome'],'held');self.assertFalse(host.draining)
  host._executions.clear();self.assertEqual(host.prepare_root_direction_adoption()['outcome'],'quiescent');self.assertTrue(host.draining)

 def test_normal_deployment_exact_lane_recovery_without_second_mutation(self):
  from otto.portfolio.root_direction_client import install_owner_root_client
  from otto.portfolio.orchestrator_client import OrchestratorLanePump, submit_exact
  from otto.portfolio import client_lanes as lanes
  directory=self.f.path.parent/'deployed-client'
  locator,client=install_owner_root_client(service=self.service,directory=directory,conversation_ref=self.root.session,request_key='normal-deploy')
  inbox=lanes.private_dir(self.f.path.parent/'inbox')
  pump=OrchestratorLanePump(owner_inbox=inbox,admissions=self.admissions,clients={directory/'lane':client},owner_call=lambda f:f())
  request=self.intent();token=submit_exact(locator['lane'],request,namespace=locator['binding']['request_namespace'],request_key=request['request_key'])
  pump.poll();result=lanes.read_private_json(directory/'lane'/('response-'+token+'.json'))
  self.assertTrue(result['terminal']);self.assertEqual(result['outcome'],'synchronized')
  counts=self.f.store.consumer().snapshot_counts()
  self.assertEqual(submit_exact(locator['lane'],request,namespace=locator['binding']['request_namespace'],request_key=request['request_key']),token)
  pump.poll();self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
  # Normal requalification reissues exact same root, not a new assignment.
  current,_=install_owner_root_client(service=self.service,directory=directory,conversation_ref=self.root.session,request_key='normal-deploy')
  self.assertEqual(current['binding']['assignment_ref'],result['assignment_ref'])
  self.assertEqual(current['binding']['assignment_ref']['id'],self.root.ref.id)
  with self.assertRaises(PermissionError):install_owner_root_client(service=self.service,directory=directory,conversation_ref={'host':'codex','native_id':'foreign'},request_key='foreign')

 def test_current_root_project_access_is_finite_and_uses_existing_handler(self):
  from otto.portfolio.root_direction_client import install_owner_root_client
  from otto.portfolio.orchestrator_client import ROOT_PROJECT_OPERATIONS
  from tempfile import TemporaryDirectory
  seen=[]
  def existing_handler(request,current):
   seen.append((request,current.ref.to_dict(),current.generation))
   return {'existing_handler':True,'operation':request['operation']}
  with TemporaryDirectory() as directory:
   locator,client=install_owner_root_client(service=self.service,directory=directory,
    conversation_ref=self.root.session,request_key='finite-root',
    project_ids=[p.ref.id for p in self.projects],project_handler=existing_handler)
   self.assertEqual(set(locator['binding']['operations']) & ROOT_PROJECT_OPERATIONS,ROOT_PROJECT_OPERATIONS)
   self.assertEqual(locator['binding']['assignment_ref'],self.root.ref.to_dict())
   self.assertEqual(locator['binding']['generation'],1)
   for index,operation in enumerate(sorted(ROOT_PROJECT_OPERATIONS)):
    result=client.call({'operation':operation,'project_id':self.projects[index % len(self.projects)].ref.id,
      'request_key':'call-'+operation,'request':{'sentinel':'preserve-existing-handler-input'}})
    self.assertTrue(result['existing_handler'])
   self.assertEqual([row[0]['operation'] for row in seen],sorted(ROOT_PROJECT_OPERATIONS))
   with self.assertRaises(PermissionError):
    client.call({'operation':'read-help','project_id':'foreign-project','request_key':'foreign-project'})
   foreign=self.owner.graph.create_project(title='Unsupervised project',logical_request_key='unsupervised-root-scope-test')
   with self.assertRaises(PermissionError):
    self.admissions.admit_current_root(actor=self.owner.owner_actor,conversation_ref=self.root.session,
      operations=['read-manager'],project_ids=[foreign.ref.id],request_key='bad-project')

 def test_compact_task_acceptance_projection_preserves_unknown_and_refs(self):
  from otto.portfolio.execution_operations import compact_task_acceptance_projection
  task={'authority':'owner','kind':'work.task','id':'task-a','revision':'rev-2'}
  decision={'authority':'owner','kind':'wrk.decision','id':'decision-a','revision':'rev-1'}
  criterion={'authority':'owner','kind':'wrk.criterion','id':'criterion-a','revision':'rev-1'}
  view={'tasks':[{'ref':task,'authored':{'acceptance':'All checks pass'},
    'observed':{'lifecycle':'pending'}}], 'decision_context':[{'subject':task,'decisions':[
      {'ref':decision,'criterion_ref':criterion,'disposition':'accepted'}]}]}
  rework={'authority':'owner','kind':'wrk.decision','id':'decision-b','revision':'rev-1'}
  view['decision_context'][0]['decisions'].append({'ref':rework,'criterion_ref':criterion,'disposition':'rework'})
  projected=compact_task_acceptance_projection(view,task_refs={'A':task})['tasks']['A']
  self.assertEqual(projected['lifecycle'],'pending')
  self.assertEqual(projected['criteria']['refs'],[criterion])
  self.assertEqual(projected['decision_history']['historical_acceptance_decision_refs'],[decision])
  self.assertEqual([row['disposition'] for row in projected['decision_history']['rows']],['accepted','rework'])
  self.assertEqual(projected['task_acceptance'],{'state':'unknown','value':None,
    'reason':'historical decisions do not derive current task acceptance'})
  unknown=compact_task_acceptance_projection({'tasks':[{'ref':task,'authored':{},'observed':{}}]},
    task_refs={'A':task})['tasks']['A']
  self.assertEqual(unknown['criteria']['state'],'unknown')
  self.assertIsNone(unknown['decision_history']['observed_count'])

 def test_draft_is_not_adoption_and_live_obligation_holds_update(self):
  read=self.read();content=self.intent()['request']['content']
  draft=self.client.call({'operation':'direction-draft','request_key':'draft','request':{'content':content,'expected_revision':read['assignment_direction']['latest_ref']['revision']}})
  self.assertFalse(draft['assignment_resources_refreshed']);self.assertEqual(self.read()['assignment_direction']['effective_ref'],self.oldpin.to_dict())
  host=SimpleNamespace(prepare_root_direction_adoption=lambda:{'outcome':'held','reason':'retained native obligation','retry':False})
  self.service.host=host;counts=self.f.store.consumer().snapshot_counts();result=self.client.call(self.intent())
  self.assertEqual(result['outcome'],'held');self.assertFalse(result['canonical_effect_recorded']);self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)

if __name__=='__main__':unittest.main()
