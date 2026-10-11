import tempfile
import unittest
from pathlib import Path
from otto.portfolio import client_lanes as lanes
from otto.portfolio.orchestrator_client import OrchestratorLanePump


class Admissions:
 def __init__(self): self.calls=[]
 def request(self, **kw):
  self.calls.append(kw)
  return {'state':'requested','authority_granted':False}

class Client:
 def __init__(self): self.calls=[]
 def call(self, request):
  self.calls.append(request)
  return {'outcome':'read','principal':'issued-root'}

class LanePumpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name);self.inbox=lanes.private_dir(root/'inbox');self.lane=lanes.private_dir(root/'issued')
  self.a=Admissions();self.client=Client();self.marshalled=0
  def owner_call(f):self.marshalled+=1;return f()
  self.pump=OrchestratorLanePump(owner_inbox=self.inbox,admissions=self.a,clients={self.lane:self.client},owner_call=owner_call)
 def test_unregistered_inbox_requests_never_admit_or_select_authority(self):
  token=lanes.submit(self.inbox,{'operation':'request-enrollment','conversation_ref':{'host':'codex','native_id':'chat'},'requested_project_ids':['port'],'request_key':'ask'})
  self.pump.poll();result=lanes.read_private_json(self.inbox/('response-'+token+'.json'))
  self.assertEqual(result['state'],'requested');self.assertFalse(result['authority_granted']);self.assertEqual(self.marshalled,1)
  bad=lanes.submit(self.inbox,{'operation':'admit','principal':'owner'})
  self.pump.poll();result=lanes.read_private_json(self.inbox/('response-'+bad+'.json'))
  self.assertEqual(result['error'],'PermissionError');self.assertEqual(len(self.a.calls),1)
 def test_interrupted_processing_never_replays_or_starves_later_requests(self):
  old=lanes.submit(self.lane,{'operation':'respond-help','request_key':'old'});lanes.mark_pending(self.lane,old,'processing')
  token=lanes.submit(self.lane,{'operation':'whoami','request_key':'fresh'})
  self.pump.poll(limit=1);self.pump.poll(limit=1)
  self.assertEqual(self.client.calls,[{'operation':'whoami','request_key':'fresh'}]);self.assertEqual(self.marshalled,1)
  self.assertFalse((self.lane/('response-'+old+'.json')).exists())
  self.assertEqual(lanes.read_private_json(self.lane/('response-'+token+'.json'))['principal'],'issued-root')
 def test_actual_issued_policy_denies_nested_foreign_scope_and_authority(self):
  from tests import test_scoped_root_supervision as fixture
  from otto.portfolio.orchestrator_client import OrchestratorAdmissions, ScopedOrchestratorClient
  f=fixture.ScopedRootSupervisionTests();f.setUp();self.addCleanup(f.doCleanups)
  admissions=OrchestratorAdmissions(f.owner,main_assignment_ref=f.default_root.ref.to_dict(),generation=1)
  pending=admissions.request(conversation_ref={'host':'codex','native_id':'own-chat'},requested_project_ids=[f.project.id],request_key='enroll')
  binding=admissions.admit(actor=f.owner.owner_actor,request_ref=pending['request_ref'],project_ids=[f.project.id],operations=['read-manager'],request_key='admit')
  calls=[];client=ScopedOrchestratorClient(owner=f.owner,binding=binding,handlers={'read-manager':lambda r,a:calls.append(r)})
  envelope={'operation':'read-manager','project_id':f.project.id,'request_key':'read'}
  for payload in [{'project_ref':{'authority':'owner','kind':'work.project','id':'foreign'}},{'principal':'owner-root'},{'project_id':'foreign'}]:
   with self.assertRaises(PermissionError):client.call({**envelope,'request':payload})
  self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
