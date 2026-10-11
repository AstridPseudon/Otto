import tempfile
import unittest
from pathlib import Path
from herzchen.contracts import ResourceRef
from otto.portfolio.orchestrator_client import OrchestratorAdmissions, ScopedOrchestratorClient, submit_exact
from otto.portfolio import client_lanes
from tests.test_scoped_root_supervision import ScopedRootSupervisionTests

class OrchestratorClientTests(unittest.TestCase):
 def setUp(self):
  self.f=ScopedRootSupervisionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.a=OrchestratorAdmissions(self.f.owner,main_assignment_ref=self.f.default_root.ref.to_dict(),generation=1)
  self.request=self.a.request(conversation_ref={'host':'codex','native_id':'astrid-chat'},requested_project_ids=[self.f.project.ref.id],request_key='enroll')
 def admit(self,**kw):
  return self.a.admit(actor=self.f.owner.owner_actor,request_ref=self.request['request_ref'],project_ids=[self.f.project.ref.id],operations=['whoami','status','portfolio','read-manager'],request_key='admit',**kw)
 def test_pending_request_grants_nothing_and_self_elevation_rejected(self):
  self.assertFalse(self.request['authority_granted'])
  with self.assertRaises(PermissionError):
   self.a.admit(actor=self.f.binding.authenticated_actor('requester'),request_ref=self.request['request_ref'],project_ids=[self.f.project.ref.id],operations=['whoami'],request_key='self')
  with self.assertRaises(TypeError):
   self.a.request(conversation_ref={'host':'codex','native_id':'astrid-chat'},requested_project_ids=[],request_key='x',human_approved=True)
 def test_own_identity_scope_transfer_revoke_and_repeat_enrollment(self):
  binding=self.admit();root=self.f.owner.assignments.get(ResourceRef.from_dict(binding['assignment_ref']))
  client=ScopedOrchestratorClient(owner=self.f.owner,binding=binding,handlers={k:(lambda r,a:{'principal':a.principal})for k in binding['operations']})
  self.assertEqual(client.call({'operation':'whoami','request_key':'r'})['principal'],binding['principal'])
  with self.assertRaises(PermissionError):client.call({'operation':'whoami','request_key':'r','principal':'owner'})
  with self.assertRaises(PermissionError):client.call({'operation':'read-manager','project_id':'foreign','request_key':'r'})
  with self.assertRaises(PermissionError):client.call({'operation':'read-manager','project_id':self.f.project.ref.id,'request_key':'r'})
  p=self.f.owner.graph.get(self.f.project.ref);relation=p.payload['metadata']['otto_orchestrator'];before=self.f._default_identity(relation);self.f._transfer(p,relation,target=root)
  self.assertEqual(before,self.f._default_identity(relation))
  self.assertEqual(client.call({'operation':'read-manager','project_id':p.ref.id,'request_key':'r'})['principal'],binding['principal'])
  second=self.a.request(conversation_ref={'host':'codex','native_id':'astrid-chat'},requested_project_ids=[p.ref.id],request_key='accidental-new-key')
  reused=self.a.admit(actor=self.f.owner.owner_actor,request_ref=second['request_ref'],project_ids=[p.ref.id],operations=binding['operations'],request_key='second')
  self.assertEqual(reused['assignment_ref'],binding['assignment_ref']);self.assertEqual(reused['policy_ref'],binding['policy_ref'])
  self.a.revoke(actor=self.f.owner.owner_actor,binding=binding,request_key='revoke')
  self.assertEqual(client.call({'operation':'status','request_key':'s'})['state'],'revoked')
  with self.assertRaises(PermissionError):client.call({'operation':'whoami','request_key':'r'})
 def test_denied_request_cannot_be_admitted(self):
  disposition=self.a.deny(actor=self.f.owner.owner_actor,request_ref=self.request['request_ref'],reason='Scope not approved',request_key='deny')
  self.assertEqual(disposition['state'],'denied');self.assertFalse(disposition['authority_granted'])
  with self.assertRaisesRegex(PermissionError,'canonically denied'):self.admit()
 def test_retained_per_client_key_rejects_changed_input(self):
  with tempfile.TemporaryDirectory()as d:
   lane=client_lanes.private_dir(Path(d)/'lane');request={'operation':'whoami','request_key':'k'}
   token=submit_exact(lane,request,namespace='own',request_key='k')
   self.assertEqual(submit_exact(lane,request,namespace='own',request_key='k'),token)
   with self.assertRaises(PermissionError):submit_exact(lane,{**request,'operation':'portfolio'},namespace='own',request_key='k')
   other=submit_exact(lane,request,namespace='other',request_key='k');self.assertNotEqual(other,token)
   pending=client_lanes.wait(lane,token,timeout_seconds=0);self.assertIsNone(pending['provider_called'])
if __name__=='__main__':unittest.main()
