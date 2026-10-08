"""Instruction adoption may precede owner stop; every retained effect stays fixed."""
from pathlib import Path
import importlib.util,hashlib,json,unittest
from datetime import datetime,timezone
from otto.attention import DurableAttention,StateConflictError
from herzchen.contracts import ResourceRef,TransactionContext
from herzchen.content.model import ContentDocument,ContentRevision
from herzchen.content.instructions import validate_instruction_content
from otto.portfolio.owner_readers import json_value
from tests import test_execution_application as fixture

class StaleManagerStopTests(unittest.TestCase):
 def setUp(self):
  f=fixture.ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
  self.manager,guide,mandate=f.role_handles('manager','manager','manager-session')
  self.guide=guide
  d=f.app.prepare_role(role='manager',project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),assignment_ref=self.manager.ref.to_dict(),generation=1,mandate_ref=mandate,context_refs=(guide,mandate),request_key='manager-unknown',instruction='Advance work',model='gpt-test',reasoning='high',profile='workspace-write',native_session_id='manager-session')
  self.schedule=d['schedule_id'];f.provider.unknown=True;self.assertEqual(f.app.start(schedule_id=self.schedule)['outcome'],'unknown')
  self.before=f.port.read_due(self.schedule)
  g=ResourceRef.from_dict(guide);stable=ResourceRef(g.authority,g.kind,g.id);head=f.owner.content.read(stable);content=dict(f.owner.content.read(g)['content']);content['instructions']+=' New bounded setup.';content['bundle_digest']=hashlib.sha256(content['instructions'].encode()).hexdigest()
  doc=ContentDocument.from_dict(json_value(head['document']));revision=ContentRevision(stable,'rev-2',content,f.actor,parent_revision=g.revision)
  ctx=TransactionContext(f.actor,'updated-base',hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest(),expected_revision=g.revision,expected_version=head['version'])
  f.owner.content.execute(f.owner.content.build_append_revision(ctx,doc,revision))
  resources=[{**r,'resource_ref':revision.ref.to_dict(),'content_digest':validate_instruction_content(content)} for r in self.manager.payload['resource_adoptions']]
  self.adopted=f.owner.assignments.command_port.adopt_resources(self.manager.ref,resources=resources,expected_revision=self.manager.revision,expected_generation=1,logical_request_key='adopt-updated-base',actor=f.actor)
 def stop(self):
  b=self.before
  return DurableAttention(None,due_port=self.f.port).stop(self.schedule,request_id='exact-owner-stop',expected_version=b['version'],project_ref=b['project_ref'],manager_ref=b['manager_ref'],generation=b['generation'],lifecycle_owner=b['lifecycle_owner'])
 def test_public_stop_after_adoption_preserves_unknown_inflight_and_old_refs(self):
  self.assertNotEqual(self.adopted.ref.to_dict(),self.before['assignment_ref'])
  calls=self.f.provider.calls[:];self.assertEqual(self.stop()['outcome'],'stopped')
  self.assertEqual(self.f.port.read_due(self.schedule),{**self.before,'stop_state':'stopped','version':self.before['version']+1})
  self.assertEqual(self.stop()['outcome'],'rejected')  # stale precondition stays fenced
  current=self.f.port.read_due(self.schedule)
  self.assertEqual(DurableAttention(None,due_port=self.f.port).stop(self.schedule,request_id='exact-owner-stop',expected_version=current['version'])['outcome'],'replayed')
  self.assertEqual(self.f.provider.calls,calls)
 def test_modified_old_effect_or_binding_cannot_use_stop_exception(self):
  for field,value in [('completion_state','succeeded'),('in_flight_request',None),('instruction','changed'),('lifecycle_owner','foreign')]:
   with self.subTest(field=field):
    with self.assertRaises(StateConflictError):self.f.port.save_due(self.schedule,{**self.before,'stop_state':'stopped',field:value},request_id='invalid-'+field,expected_version=self.before['version'])
    self.assertEqual(self.f.port.read_due(self.schedule),self.before)
 def test_reassignment_generation_drift_still_rejects_before_stop(self):
  self.f.owner.assignments.command_port.reassign(self.adopted.ref,principal='other',expected_generation=1,logical_request_key='other-manager')
  with self.assertRaises(StateConflictError):self.stop()
  self.assertEqual(self.f.port.read_due(self.schedule),self.before)
if __name__=='__main__':unittest.main()
