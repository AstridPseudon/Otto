"""Accepted task finish survives only a genuine same-root join refresh."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest
from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule, contribution
from herzchen.kernel.limits import LimitService
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from tests.test_root_direction_synchronization import RootDirectionSynchronizationTests

class CompletionProjectRefreshTests(unittest.TestCase):
 def setUp(self):
  self.f=RootDirectionSynchronizationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  root=self.f; fixture=root.f;self.project=root.projects[0]
  fixture.store.register_domain_handler((contribution(),))
  self.owner=PortfolioOwnerBootstrap(fixture.store,binding=fixture.binding,owner_actor='owner',project_read_grant=ProjectReadGrant(fixture.actor,(self.project.id,),'test','v1'))
  task=self.owner.graph.create_task(self.project.ref,title='Accepted task',logical_request_key='accepted-task')
  manager=self.owner.assignments.assign(self.project.ref,role='manager',principal='manager',manager='manager',logical_request_key='manager')
  scope=AssessmentModule(fixture.store,actor=fixture.actor).declare_scope('completion-scope',parent_obligation=task.ref,protocol='test',criteria=[{'id':'C'}],logical_request_key='completion-scope')
  self.state={'authority':fixture.store.authority,'project_ref':self.project.ref.to_dict(),'assignment_ref':manager.ref.to_dict(),'manager':'manager','manager_generation':1,'task_refs':{'T':task.ref.to_dict()},'criterion_refs':{'C':scope.criterion_refs[0].to_dict()},'assessment_policy':{'kind':'owner_local_bookkeeping','purpose':'test','local_only':True,'pool_id':'completion-pool','capacity_units':1,'cumulative_allowance_units':1,'task_criterion_pairs':['T/C']}}
  self.commands=ManagerJourneyCommands(owner=self.owner,portfolio=OttoPortfolio(self.owner.consumer_operations()),state=self.state)
  doc=fixture.create_document('delivered-source',self.project.ref,role='SOURCE');candidate=replace(doc.ref,revision='rev-1').to_dict()
  self.review={'command':'review-task','task':'T','request_key':'accepted','candidate_ref':candidate,'source_refs':[candidate],'inspection':{'observed':'Exact source verified'},'judgments':{'C':{'verdict':'PASS','rationale':'Exact evidence verified','evidence_refs':[candidate]}},'finish':False}
  self.assertEqual(self.commands.review_task(self.review)['outcome'],'accepted')
  self.finish={'command':'finish-task','task':'T','request_key':'finish','review_key':'accepted'}
 def refresh(self):
  self.f.call();self.state['project_ref']=self.owner.graph.current(self.project.ref).ref.to_dict()
 def test_exact_refresh_finish_and_replay_preserve_review_and_debit(self):
  before=self.commands._journal('accepted','intent');review=self.commands._journal('accepted','review')
  self.refresh();pool=LimitService(self.f.f.store).get_pool(ResourceRef(self.state['authority'],'limit','completion-pool'))
  result=self.commands.finish_task(self.finish);self.assertEqual(result['outcome'],'completed',result)
  self.assertEqual(result['completion']['project_ref'],self.state['project_ref'])
  self.state['task_refs']['T']=result['task_ref'];counts=self.f.f.store.consumer().snapshot_counts()
  self.assertEqual(self.commands.finish_task(self.finish)['outcome'],'replayed')
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
  self.assertEqual(self.commands._journal('accepted','intent'),before);self.assertEqual(self.commands._journal('accepted','review'),review)
  self.assertEqual(LimitService(self.f.f.store).get_pool(pool.ref),pool)
 def second_refresh(self):
  f=self.f;root=f.owner.assignments.get(f.root.ref);direction=f.owner.direction_surface().read(f.subject)
  draft=f.owner.direction_surface().draft(f.subject,{'text':'Observer policy changed'},logical_request_key='mission-draft-next',expected_revision=direction['latest_ref']['revision'])
  resources=deepcopy(root.payload['resource_adoptions']);base=ResourceRef.from_dict(resources[0]['resource_ref']);read=f.owner.content.read(base);body=deepcopy(read['content']);body['supporting_refs']=[draft['revision_ref']]
  document=ContentDocument(replace(base,revision=None),'role_instructions','private','append','owner',f.subject)
  revision=ContentRevision(document.ref,'rev-4',body,f.owner.owner_actor,parent_revision=base.revision)
  f.owner.content.execute(f.owner.content.build_append_revision(f.f.context('base-next-again',expected_revision=base.revision),document,revision))
  resources[0].update(resource_ref=revision.ref.to_dict(),content_digest=validate_instruction_content(body))
  projects=[f.owner.graph.current(v.ref)for v in f.projects]
  f.owner.synchronize_portfolio_direction(assignment_ref=root.ref.to_dict(),generation=1,direction_ref=draft['revision_ref'],expected_binding_ref=draft['binding_ref'],resources=resources,expected_default_ref=projects[0].payload['metadata']['otto_orchestrator']['default_ref'],projects=[{'project_ref':v.ref.to_dict(),'project_version':v.version,'supervision':deepcopy(v.payload['metadata']['otto_orchestrator'])}for v in projects],logical_request_key='mission-sync-again')
  self.state['project_ref']=self.owner.graph.current(self.project.ref).ref.to_dict()
 def pending_pin(self):
  self.refresh()
  with patch.object(self.commands,'_native_settlement',return_value={'outcome':'pending'}):
   self.assertEqual(self.commands.finish_task(self.finish)['outcome'],'pending')
  return self.commands._journal('finish','finish-project-pin')
 def test_pending_pin_refresh_appends_proof_then_exact_completion_and_replay(self):
  original=self.pending_pin();review=self.commands._journal('accepted','review');manifest=self.commands._journal('accepted','intent')
  pool=LimitService(self.f.f.store).get_pool(ResourceRef(self.state['authority'],'limit','completion-pool'))
  self.second_refresh();result=self.commands.finish_task(self.finish);self.assertEqual(result['outcome'],'completed')
  self.assertEqual(result['completion']['project_ref'],self.state['project_ref'])
  self.assertEqual(self.commands._journal('finish','finish-project-pin'),original)
  refreshed=self.commands._journal('finish','finish-project-pin-refresh:'+self.state['project_ref']['revision'])
  self.assertEqual(refreshed['event_ids'][:len(original['event_ids'])],original['event_ids'])
  self.state['task_refs']['T']=result['task_ref'];counts=self.f.f.store.consumer().snapshot_counts()
  self.assertEqual(self.commands.finish_task(self.finish)['outcome'],'replayed');self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
  self.assertEqual(self.commands._journal('accepted','intent'),manifest);self.assertEqual(self.commands._journal('accepted','review'),review)
  self.assertEqual(LimitService(self.f.f.store).get_pool(pool.ref),pool)
  current=self.owner.graph.current(self.project.ref);self.owner.graph.revise(current.ref,title='Later unrelated bookkeeping',logical_request_key='later-bookkeeping');self.state['project_ref']=self.owner.graph.current(current.ref).ref.to_dict();counts=self.f.f.store.consumer().snapshot_counts()
  self.assertEqual(self.commands.finish_task(self.finish)['outcome'],'replayed');self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
 def test_pending_pin_unrelated_edit_or_changed_review_proof_rejects_without_effect(self):
  original=self.pending_pin();self.second_refresh();current=self.owner.graph.current(self.project.ref)
  self.owner.graph.revise(current.ref,title='Changed outcome scope',logical_request_key='unrelated-after-pin');self.state['project_ref']=self.owner.graph.current(current.ref).ref.to_dict()
  counts=self.f.f.store.consumer().snapshot_counts()
  with self.assertRaises(PermissionError):self.commands.finish_task(self.finish)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts);self.assertEqual(self.commands._journal('finish','finish-project-pin'),original)
 def test_pending_pin_missing_foreign_adoption_or_changed_criteria_rejects(self):
  original=self.pending_pin();self.second_refresh();reader=self.owner.graph.reader;lookup=type(reader).__getattr__;events=reader.list_events
  counts=self.f.f.store.consumer().snapshot_counts()
  for variant in ('missing','foreign','criteria'):
   def changed(*,stream=None):
    rows=events(stream=stream)
    if stream=='assignment:'+self.f.root.id and variant=='missing':return ()
    if stream=='work:'+self.project.id and variant=='foreign':return tuple(replace(e,actor=self.f.f.binding.authenticated_actor('foreign'))if e.event_type=='work.project.supervision-transferred'else e for e in rows)
    return rows
   journal=self.commands._journal
   def changed_journal(key,stage,value=None,**kwargs):
    item=journal(key,stage,value,**kwargs)
    return {**item,'gate_refs':[]}if variant=='criteria'and key=='accepted'and stage=='review'and item else item
   with self.subTest(variant=variant),patch.object(type(reader),'__getattr__',lambda obj,name:changed if obj is reader and name=='list_events'else lookup(obj,name)),patch.object(self.commands,'_journal',side_effect=changed_journal):
    with self.assertRaises(PermissionError):self.commands.finish_task(self.finish)
   self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
   self.assertEqual(self.commands._journal('finish','finish-project-pin'),original)
 def test_unrelated_revision_in_chain_and_stale_generation_reject(self):
  self.refresh();current=self.owner.graph.current(self.project.ref);self.owner.graph.revise(current.ref,title='Changed outcome scope',logical_request_key='unrelated')
  self.state['project_ref']=self.owner.graph.current(current.ref).ref.to_dict();counts=self.f.f.store.consumer().snapshot_counts()
  with self.assertRaises(PermissionError):self.commands.finish_task(self.finish)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
  self.state['manager_generation']=2
  with self.assertRaises(PermissionError):self.commands.finish_task(self.finish)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
 def test_missing_foreign_and_ambiguous_adoption_proof_reject_without_effect(self):
  self.refresh();reader=self.owner.graph.reader;original=reader.list_events
  events=original(stream='work:'+self.project.id);transfer=next(e for e in events if e.event_type=='work.project.supervision-transferred')
  counts=self.f.f.store.consumer().snapshot_counts()
  lookup=type(reader).__getattr__
  for variant in ('missing','foreign','duplicate'):
   def changed(*,stream=None):
    rows=original(stream=stream)
    if stream=='assignment:'+self.f.root.id:return () if variant=='missing' else rows
    if stream=='work:'+self.project.id:
     if variant=='duplicate':return tuple(rows)+(transfer,)
     if variant=='foreign':return tuple(replace(e,actor=self.f.f.binding.authenticated_actor('foreign'))if e==transfer else e for e in rows)
    return rows
   with self.subTest(variant=variant),patch.object(type(reader),'__getattr__',lambda obj,name: changed if obj is reader and name=='list_events' else lookup(obj,name)):
    with self.assertRaises(PermissionError):self.commands.finish_task(self.finish)
   self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)

if __name__=='__main__':unittest.main()
