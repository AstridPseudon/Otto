"""Fresh worker live caller context through real gateway/adapter owner ports.

External provider is a fixture; no live authentication claim. This catches the
missing callback composition before a worker terminal result can hide it.
"""
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
from herzchen.contracts import ResourceRef
from herzchen.domains.work import WorkGraph, contributions, admission
from herzchen.domains.work.admission import TaskNotAdmittedError
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.model import Lifecycle, WorkValidationError
from herzchen.domains.work.sheet import ProjectSheet, PolicyAuthorityError
from herzchen.kernel.store import Store
from herzchen.contracts import AuthenticatedActor
from otto.agents.gateway import OwnerDueRecordAttemptCapture
from otto.agents.herzchen_adapter import HerzchenCodexAdapter
from otto.portfolio.identity_context import HostCallerBinding
from tests import test_execution_application as application

class FreshWorkerAdmissionTests(unittest.TestCase):
 def fixture(self):
  f=application.ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups)
  handles=f.app.assign_worker(**f.request());return f,handles['schedule_id']
 def test_live_authorized_worker_context_before_result_and_no_initializer_admission(self):
  f,schedule=self.fixture();original=OwnerDueRecordAttemptCapture.record_delivery_admission;seen=[]
  def capture(owner_capture,key,session,turn,stamp):
   result=original(owner_capture,key,session,turn,stamp)
   due=f.app._read(schedule);attempt=due.host_evidence['gateway_attempt']
   self.assertEqual(attempt['state'],'claimed');self.assertNotIn('result',attempt)
   self.assertEqual(owner_capture.role,'worker');self.assertEqual(turn,'provider-turn-1')
   actor=f.binding.authenticated_actor(due.recipient)
   caller=HostCallerBinding(actor,ResourceRef.from_dict(due.assignment_ref),due.generation,f.app.native_adapter_identity(),session,schedule)
   context=f.app.caller_context(caller);self.assertEqual(context['principal'],'worker')
   with self.assertRaises(PermissionError):f.app.caller_context(replace(caller,native_session_id='foreign-session'))
   seen.append(context)
   return result
  with patch.object(OwnerDueRecordAttemptCapture,'record_delivery_admission',capture):
   result=f.app.start(schedule_id=schedule)
  self.assertEqual(result['outcome'],'succeeded',result)
  self.assertEqual(len(seen),1) # READY initializer has no authorized callback.
  self.assertEqual(len(f.provider.calls),1)
  self.assertEqual(f.app.start(schedule_id=schedule)['outcome'],'replayed')
  self.assertEqual(len(f.provider.calls),1)
 def test_cli_ready_initializer_is_excluded_from_fresh_worker_admission(self):
  import json
  from tests.test_fresh_manager_admission import FreshManagerTests
  fixture=FreshManagerTests();self.addCleanup(fixture.doCleanups)
  f,root=fixture.fixture();worker=f.app.assign_worker(**f.request())
  result=f.app.start(schedule_id=worker['schedule_id'])
  self.assertEqual(result['outcome'],'succeeded',result)
  attempt=f.port.read_due(worker['schedule_id'])['host_evidence']['gateway_attempt']
  self.assertEqual(attempt['delivery_admission']['observed_turn_id'],'work-turn')
  submitted=[json.loads(raw) for raw in (root/'submitted.jsonl').read_text().splitlines()]
  self.assertEqual([v['resume'] for v in submitted],[False,True])
  self.assertNotIn('otto-resource-brief',submitted[0]['prompt'])
  self.assertIn('otto-resource-brief',submitted[1]['prompt'])

 def test_missing_live_admission_does_not_authorize_a_worker_context(self):
  f,schedule=self.fixture();original=OwnerDueRecordAttemptCapture.record_delivery_admission;denied=[]
  def omit(owner_capture,key,session,turn,stamp):
   due=f.app._read(schedule);self.assertNotIn('delivery_admission',due.host_evidence['gateway_attempt'])
   caller=HostCallerBinding(f.binding.authenticated_actor(due.recipient),ResourceRef.from_dict(due.assignment_ref),due.generation,f.app.native_adapter_identity(),session,schedule)
   with self.assertRaisesRegex(PermissionError,'verified admission/readback'):f.app.caller_context(caller)
   denied.append(session)
   return original(owner_capture,key,session,turn,stamp)
  with patch.object(OwnerDueRecordAttemptCapture,'record_delivery_admission',omit):result=f.app.start(schedule_id=schedule)
  self.assertEqual(result['outcome'],'succeeded',result);self.assertEqual(len(denied),1)


class PolicyTaskAdmissionTests(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory(prefix='fresh-worker-admission-')
  self.addCleanup(self.temporary.cleanup)
  self.actor=AuthenticatedActor('admission-test','user','user-credential')
  self.agent=AuthenticatedActor('admission-test','agent','agent-credential')
  self.store=Store.create(Path(self.temporary.name)/'work.sqlite',authority='admission-test')
  self.addCleanup(self.store.close)
  self.store.register_domain_handler(contributions())
  self.graph=WorkGraph(self.store)
  self.assignments=ResponsibilityAssignments(self.store,actor=self.actor).command_port
  self.sheet=ProjectSheet(self.store,actor=self.agent)
  self.project=self.graph.create_project(title='Admission project',logical_request_key='project',actor=self.actor)
  self.task=self.graph.create_task(self.project,title='Original task',logical_request_key='task',actor=self.actor)

 def allow_additions(self,*keys):
  project=self.graph.current(self.project.ref)
  candidate=self.sheet.decisions.create_candidate(
   parent_obligation=project.ref,artifact=project.ref,source=project.ref,spec=project.ref,
   criteria=[project.ref],owner='admission-test',logical_request_key='policy-candidate',actor=self.actor)
  decision=self.sheet.decisions.record_decision(
   project.ref,candidate=candidate.ref,authority='admission-test',rationale='Fixture policy approval',
   disposition='approved',logical_request_key='policy-decision',actor=self.actor)
  return self.sheet.amend_policy(
   project.ref,{'permitted_task_additions':list(keys)},authority='admission-test',
   base_revision=project.revision,decision_ref=decision.ref,
   logical_request_key='set-policy-'+str(len(keys)),actor=self.actor)

 def assign(self,task,key):
  return self.assignments.assign(task.ref,role='worker',principal='worker',
                                 logical_request_key=key,actor=self.actor)

 def test_permitted_local_key_does_not_auto_admit_an_agent_edit(self):
  self.allow_additions('primary')
  self.graph.revise(self.task.ref,add_alias='primary',logical_request_key='add-primary-alias',actor=self.actor)
  task=self.graph.current(self.task.ref)
  assignment=self.assign(task,'assign-edited')
  self.sheet.apply(self.project.ref,{'tasks':[{'id':'primary','title':'Edited by agent'}]},
                   actor=self.agent,logical_request_key='edit-primary')
  with self.assertRaises(TaskNotAdmittedError):
   self.assignments.dispatch(assignment,logical_request_key='dispatch-edited',actor=self.agent)

 def test_permitted_new_sheet_task_is_admitted_at_rev_one_and_dispatches(self):
  self.allow_additions('extra')
  result=self.sheet.apply(self.project.ref,{'tasks':[{'id':'extra','title':'Extra'}]},
                          actor=self.agent,logical_request_key='add-extra')
  task=self.graph.current(result.mappings['extra'])
  self.assertEqual(task.revision,'rev-1')
  self.assertEqual(self.graph.admission_state(task.ref)['admitted_revision'],'rev-1')
  assignment=self.assign(task,'assign-extra')
  self.assignments.dispatch(assignment,logical_request_key='dispatch-extra',actor=self.agent)

 def test_policy_admission_replay_preserves_original_mapping_without_writes(self):
  self.allow_additions('extra')
  sheet={'tasks':[{'id':'extra','title':'Extra'}]}
  original_input=deepcopy(sheet)
  first=self.sheet.apply(self.project.ref,sheet,actor=self.agent,logical_request_key='add-extra-replay')
  first_mapping=dict(first.mappings)
  self.assertEqual(sheet,original_input)
  task_ref=first_mapping['extra']
  current=self.graph.current(task_ref)
  self.graph.revise(current.ref,title='Later user edit',logical_request_key='later-user-edit',actor=self.actor)
  task_after_edit=self.graph.current(task_ref)
  project_id=self.graph.current(self.project.ref).id
  events_before=tuple(event.event_id for event in self.store.list_events(stream='work:'+project_id))
  task_events_before=tuple(event.event_id for event in self.store.list_events(stream='work:'+task_ref.id))
  replay=self.sheet.apply(self.project.ref,sheet,actor=self.agent,logical_request_key='add-extra-replay')
  self.assertEqual(dict(replay.mappings),first_mapping)
  self.assertEqual(self.graph.current(task_ref).revision,task_after_edit.revision)
  self.assertEqual(tuple(event.event_id for event in self.store.list_events(stream='work:'+project_id)),events_before)
  self.assertEqual(tuple(event.event_id for event in self.store.list_events(stream='work:'+task_ref.id)),task_events_before)
  self.assertEqual(sheet,original_input)

 def test_direct_sheet_apply_cannot_install_task_addition_policy(self):
  with self.assertRaises(PolicyAuthorityError):
   self.sheet.apply(self.project.ref,{'metadata_namespace':{'work.policy':{
       'policy':{'permitted_task_additions':['forged']}}}},
       actor=self.agent,logical_request_key='forged-work-policy')

 def test_agent_cannot_forge_project_users_authoring_admission(self):
  unpinned_task=ResourceRef(self.task.ref.authority,self.task.ref.kind,self.task.ref.id)
  assignment=self.assignments.assign(unpinned_task,role='worker',principal='worker',
                                     logical_request_key='assign-forged-authoring',actor=self.actor)
  self.graph.revise(self.task.ref,title='Agent authored edit',
                    logical_request_key='agent-authored-edit',actor=self.agent)
  current=self.graph.current(self.task.ref)
  forged_stamp={
   'revision':'rev-'+str(current.version+1),
   'digest':admission.content_digest(current.payload),
   'basis':admission.BASIS_AUTHORING,
   'admitted_by':{'authority':self.actor.authority,'actor':self.actor.actor},
  }
  if hasattr(admission,'reviewed_content_digest'):
   forged_stamp['reviewed_digest']=admission.reviewed_content_digest(current.payload)
  forged=self.graph.revise(current.ref,metadata_namespaces={admission.NAMESPACE:forged_stamp},
                           logical_request_key='forge-user-authoring-stamp',actor=self.agent)
  self.assertEqual(admission.admitted_revision(forged.payload),forged.revision)
  with self.assertRaises(TaskNotAdmittedError):
   self.assignments.dispatch(assignment,logical_request_key='dispatch-forged-authoring',actor=self.agent)

 def test_unpermitted_new_sheet_task_remains_unadmitted_and_cannot_dispatch(self):
  self.allow_additions('allowed')
  result=self.sheet.apply(self.project.ref,{'tasks':[{'id':'outside','title':'Outside policy'}]},
                          actor=self.agent,logical_request_key='add-outside')
  task=self.graph.current(result.mappings['outside'])
  self.assertIsNone(self.graph.admission_state(task.ref)['admitted_revision'])
  assignment=self.assign(task,'assign-outside')
  with self.assertRaises(TaskNotAdmittedError):
   self.assignments.dispatch(assignment,logical_request_key='dispatch-outside',actor=self.agent)

 def test_unchanged_sibling_stays_admitted_and_dispatchable(self):
  sibling=self.graph.create_task(self.project,title='Sibling',logical_request_key='sibling',actor=self.actor)
  edited_assignment=self.assign(self.task,'assign-edited-sibling')
  sibling_assignment=self.assign(sibling,'assign-unchanged-sibling')
  self.sheet.apply(self.project.ref,{'tasks':[{'id':self.task.id,'title':'Edited'}]},
                   actor=self.agent,logical_request_key='edit-one-task')
  with self.assertRaises(TaskNotAdmittedError):
   self.assignments.dispatch(edited_assignment,logical_request_key='dispatch-edited-sibling',actor=self.agent)
  self.assignments.dispatch(sibling_assignment,logical_request_key='dispatch-unchanged-sibling',actor=self.agent)

 def test_agent_body_edit_of_admitted_task_blocks_only_that_task(self):
  sibling=self.graph.create_task(self.project,title='Body edit sibling',logical_request_key='body-sibling',actor=self.actor)
  edited_assignment=self.assign(self.task,'assign-body-edited')
  sibling_assignment=self.assign(sibling,'assign-body-sibling')
  self.sheet.apply(self.project.ref,{'tasks':[{'id':self.task.id,'body':'Agent edited the task body'}]},
                   actor=self.agent,logical_request_key='edit-task-body')
  self.assertIsNone(self.graph.admission_state(self.task.ref)['admitted_revision'])
  with self.assertRaises(TaskNotAdmittedError):
   self.assignments.dispatch(edited_assignment,logical_request_key='dispatch-body-edited',actor=self.agent)
  self.assignments.dispatch(sibling_assignment,logical_request_key='dispatch-body-sibling',actor=self.agent)

 def test_sheet_cannot_change_completed_task_even_when_key_is_permitted(self):
  self.allow_additions('primary')
  self.graph.revise(self.task.ref,add_alias='primary',logical_request_key='completed-alias',actor=self.actor)
  self.graph.set_lifecycle(self.task.ref,Lifecycle.COMPLETED,logical_request_key='complete-task',actor=self.actor)
  with self.assertRaises(WorkValidationError):
   self.sheet.apply(self.project.ref,{'tasks':[{'id':'primary','title':'Changed completed task'}]},
                    actor=self.agent,logical_request_key='change-completed')

if __name__=='__main__':unittest.main()
