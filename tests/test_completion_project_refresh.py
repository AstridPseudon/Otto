"""Accepted task finish survives unrelated project edits, but not task or policy edits."""
from dataclasses import replace
import unittest
from herzchen.content import ContentCommandHandler
from herzchen.content.packets import AccessDeniedError, ContextPacketService
from herzchen.content.reads import EvidenceReadGrant
from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentAuthorityError, AssessmentModule, contribution
from herzchen.domains.assessment.module import verify_dat_evidence
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
 def test_private_owner_evidence_is_read_only_for_exact_assessment_and_manager_approves(self):
  fixture=self.f.f;task=ResourceRef.from_dict(self.state['task_refs']['T']);candidate=ResourceRef.from_dict(self.review['candidate_ref'])
  decisions=AssessmentModule(fixture.store).list_decisions(parent_obligation=task)
  self.assertEqual(len(decisions),1)
  decision=decisions[0]
  self.assertEqual(decision.author,'manager')
  accepted=next(event for event in fixture.store.consumer().list_events(stream='assessment') if event.subject==decision.ref)
  self.assertEqual(accepted.actor.actor,'manager')
  manager=fixture.binding.authenticated_actor('manager')
  scopes=(task,self.project.ref)
  with self.assertRaises(PermissionError):
   ContentCommandHandler(fixture.store).metadata(candidate,actor=manager,scopes=scopes)
  with self.assertRaises(AccessDeniedError):
   ContextPacketService(fixture.store).resolve_reference(candidate,actor=manager,scopes=scopes)
  pin=decision.payload['evidence_digests'][0]
  grant=EvidenceReadGrant.from_dict(pin['evidence_read_grant'])
  self.assertEqual(grant.evidence,candidate)
  self.assertEqual(verify_dat_evidence(fixture.store,candidate,actor=manager,scopes=scopes,
   evidence_read_grant=grant)['state'],'verified')
  other=fixture.create_document('ungranted-source',self.project.ref,role='SOURCE')
  other_ref=replace(other.ref,revision='rev-1')
  self.assertEqual(verify_dat_evidence(fixture.store,other_ref,actor=manager,scopes=scopes,
   evidence_read_grant=grant)['state'],'unknown')
  with self.assertRaises(AssessmentAuthorityError):
   AssessmentModule(fixture.store,actor=fixture.actor).accept(decision.result_ref,
    rationale='owner cannot approve',evidence_refs=[candidate],logical_request_key='owner-approval-attempt')
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
 def test_project_edit_after_acceptance_finishes_without_new_review(self):
  current=self.owner.graph.current(self.project.ref)
  edited=self.owner.graph.revise(current.ref,title='Unrelated plan title',logical_request_key='unrelated-plan-edit')
  self.state['project_ref']=edited.ref.to_dict()
  result=self.commands.finish_task(self.finish)
  self.assertEqual(result['outcome'],'completed',result)
  self.assertEqual(result['completion']['project_ref'],self.state['project_ref'])

 def test_task_instruction_edit_requires_fresh_review_without_completion_effect(self):
  task=ResourceRef.from_dict(self.state['task_refs']['T'])
  project=ResourceRef.from_dict(self.state['project_ref'])
  edited=self.owner.sheet.batches.apply_project_sheet(project,
   {'tasks':[{'id':task.id,'instructions':'Changed after accepted review'}]},
   logical_request_key='changed-task-instructions',actor=self.f.f.actor)
  self.state['project_ref']=edited.project.ref.to_dict()
  self.state['task_refs']['T']=edited.mappings[task.id].to_dict()
  counts=self.f.f.store.consumer().snapshot_counts()
  with self.assertRaisesRegex(PermissionError,r'task\.instructions.*review-input --task T.*review-task --task T --request-key <new-key>'):
   self.commands.finish_task(self.finish)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)

 def test_trusted_policy_edit_requires_fresh_review_without_completion_effect(self):
  self.state['assessment_policy']['purpose']='Changed assessment purpose'
  counts=self.f.f.store.consumer().snapshot_counts()
  with self.assertRaisesRegex(PermissionError,r'assessment_policy\.purpose.*review-input --task T.*review-task --task T --request-key <new-key>'):
   self.commands.finish_task(self.finish)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)

 def test_stale_manager_generation_refuses_without_completion_effect(self):
  self.state['manager_generation']=2
  counts=self.f.f.store.consumer().snapshot_counts()
  with self.assertRaises(PermissionError):self.commands.finish_task(self.finish)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)

if __name__=='__main__':unittest.main()
