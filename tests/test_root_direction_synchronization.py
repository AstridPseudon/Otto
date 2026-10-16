"""Same root direction/resource adoption preserves every exact portfolio join."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest
from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef, ReplayConflictError
from herzchen.domains.work.model import WorkValidationError
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.direction_context import read_direction_context
from otto.portfolio.tests import test_portfolio_direction as fixtures

class RootDirectionSynchronizationTests(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.PortfolioDirectionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.root,self.subject,self.oldpin,project=self.f.setup_portfolio()
  self.owner=PortfolioOwnerBootstrap(self.f.store,binding=self.f.binding,owner_actor='owner',portfolio_ref=self.root.scope,main_assignment_ref=self.root.ref,expected_main_principal='owner')
  second=self.owner.graph.create_project(title='Another pending',logical_request_key='second')
  self.owner.consumer_operations().execute('work.orchestrator.projects.attach',{'target_assignment_ref':self.root.ref.to_dict(),'target_assignment_revision':self.root.revision,'target_assignment_generation':1,'projects':[{'project_ref':second.ref.to_dict(),'project_version':second.version,'assignment_ref':None,'assignment_revision':None,'assignment_generation':None}]},request_id='second-enroll',actor='owner')
  self.projects=[self.owner.graph.current(project.ref),self.owner.graph.current(second.ref)]
  self.resources=deepcopy(self.root.payload['resource_adoptions'])
  draft=self.owner.direction_surface().draft(self.subject,{'text':'Full canonical queue mission'},logical_request_key='mission-draft',expected_revision='rev-1')
  self.pin=draft['revision_ref']
  base=ResourceRef.from_dict(self.resources[0]['resource_ref']);read=self.owner.content.read(base);body=deepcopy(read['content']);body['supporting_refs']=[self.pin]
  document=ContentDocument(replace(base,revision=None),'role_instructions','private','append','owner',self.subject)
  revision=ContentRevision(document.ref,'rev-3',body,self.owner.owner_actor,parent_revision=base.revision)
  self.owner.content.execute(self.owner.content.build_append_revision(self.f.context('base-next',expected_revision=base.revision),document,revision))
  self.resources[0].update(resource_ref=revision.ref.to_dict(),content_digest=validate_instruction_content(body))
  self.request={'assignment_ref':self.root.ref.to_dict(),'generation':1,'direction_ref':self.pin,'expected_binding_ref':draft['binding_ref'],'resources':self.resources,'expected_default_ref':self.projects[0].payload['metadata']['otto_orchestrator']['default_ref'],'projects':[{'project_ref':v.ref.to_dict(),'project_version':v.version,'supervision':deepcopy(v.payload['metadata']['otto_orchestrator'])}for v in self.projects],'logical_request_key':'mission-sync'}
 def call(self,**kwargs):return self.owner.synchronize_portfolio_direction(**{**self.request,**kwargs})
 def assert_unchanged(self,counts):
  self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
  self.assertEqual(self.owner.assignments.get(self.root.ref).ref,self.root.ref)
  self.assertEqual(self.owner.direction_surface().read(self.subject)['effective_ref'],self.oldpin.to_dict())
  for v in self.projects:self.assertEqual(self.owner.graph.get(v.ref),v)
 def test_exact_rev2_to3_all_joins_effective_and_lost_response_recovery(self):
  self.assertEqual(self.root.revision,'rev-2')
  result=self.call();self.assertTrue(result['assignment_resources_refreshed']);self.assertEqual(result['assignment_ref']['revision'],'rev-3');self.assertEqual(result['generation'],1)
  root=self.owner.assignments.get(result['assignment_ref'])
  for original in self.projects:
   current=self.owner.graph.current(original.ref);relation=current.payload['metadata']['otto_orchestrator']
   self.assertEqual(relation['assignment_ref'],root.ref.to_dict());self.assertEqual(relation['project_ref'],current.ref.to_dict())
   a=deepcopy(original.payload);b=deepcopy(current.payload);a['metadata'].pop('otto_orchestrator');b['metadata'].pop('otto_orchestrator');self.assertEqual(a,b)
   context=read_direction_context(self.owner.direction_bindings(),actor=self.owner.owner_actor,assignment_ref=root.ref.to_dict(),generation=1,project_ref=current.ref.to_dict());self.assertEqual(context[-1]['effective_ref'],self.pin)
  with self.assertRaises(PermissionError):read_direction_context(self.owner.direction_bindings(),actor=self.owner.owner_actor,assignment_ref=root.ref.to_dict(),generation=1,project_ref=self.f.project.ref.to_dict())
  counts=self.f.store.consumer().snapshot_counts();recovered=self.call();self.assertTrue(recovered['replayed']);self.assertEqual(recovered['assignment_ref'],result['assignment_ref']);self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
  changed=deepcopy(self.resources);changed[0]['content_digest']='changed'
  with self.assertRaises(ReplayConflictError):self.call(resources=changed)
  self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
 def test_omitted_or_changed_join_and_stale_generation_fail_without_scope_adoption(self):
  counts=self.f.store.consumer().snapshot_counts()
  for override in ({'projects':self.request['projects'][:1]},{'generation':2},{'projects':[dict(self.request['projects'][0],project_version=999),self.request['projects'][1]]}):
   with self.subTest(override=override),self.assertRaises((PermissionError,WorkValidationError)):self.call(**override)
   self.assert_unchanged(counts)
 def test_failure_after_root_adoption_rolls_back_all_then_same_input_succeeds(self):
  from herzchen.domains.work.orchestration import _OrchestrationEngine
  counts=self.f.store.consumer().snapshot_counts()
  with patch.object(_OrchestrationEngine,'set_default',side_effect=RuntimeError('simulated owner failure')):
   with self.assertRaisesRegex(RuntimeError,'simulated'):self.call()
  self.assert_unchanged(counts)
  self.assertEqual(self.call()['outcome'],'synchronized')
 def test_protected_external_owner_route_returns_full_context_and_replays(self):
  import json
  from pathlib import Path
  from types import SimpleNamespace
  from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
  from otto.portfolio.manager_journey_service import ManagerJourneyService
  ingress=OwnerAuthoringIngress(actor=self.owner.owner_actor,owner_actor=self.owner.owner_actor,directory=self.f.path.parent/'root-ipc')
  state={'orchestrator_assignment_ref':self.root.ref.to_dict(),'root_help_binding':{'assignment_ref':self.root.ref.to_dict(),'generation':1}}
  server=SimpleNamespace(owner=self.owner,state=state,_execution=None,portfolio=None,due_port=None,_save_state=lambda:None)
  service=ManagerJourneyService(server=server,host=None,run_path=self.f.path.parent,workspace=self.f.path.parent,authoring_authorizer=ingress.authorize)
  handle={k:self.request[k]for k in ('assignment_ref','generation','resources','expected_default_ref','projects')}
  request={'command':'owner-context','operation':'direction-synchronize','request_key':'protected-mission','document_ref':self.pin,'expected_binding_ref':self.request['expected_binding_ref'],'handle':handle}
  with self.assertRaises(PermissionError):service(request)
  grant=ingress.publish({'schema':ingress.schema,'request':request});actual=service(json.loads(Path(grant['request_path']).read_text()))
  self.assertTrue(actual['assignment_resources_refreshed']);self.assertEqual(state['orchestrator_assignment_ref'],actual['assignment_ref']);self.assertFalse(actual['native_process_identity_claimed']);self.assertTrue(actual['runtime_requalification_required']);self.assertEqual(state['root_help_binding']['assignment_ref'],actual['assignment_ref'])
  counts=self.f.store.consumer().snapshot_counts();replayed=service(request);self.assertTrue(replayed['replayed']);self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
  read={'command':'owner-context','operation':'effective-context','request_key':'after-sync'};ingress.publish({'schema':ingress.schema,'request':read});view=service(read);self.assertEqual(view['assignment_direction']['effective_ref'],self.pin)
 def test_cannot_change_shared_role_guidance_or_foreign_root(self):
  changed=deepcopy(self.resources);changed[0]['resource_name']='not-the-base'
  counts=self.f.store.consumer().snapshot_counts()
  with self.assertRaises(ValueError):self.call(resources=changed)
  self.assert_unchanged(counts)
  foreign=self.owner.assignments.assign(ResourceRef(self.root.ref.authority,'wrk.portfolio','foreign'),role='orchestrator',principal='owner',logical_request_key='foreign')
  with self.assertRaises(PermissionError):self.call(assignment_ref=foreign.ref.to_dict())

if __name__=='__main__':unittest.main()
