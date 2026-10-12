"""Real retained policies and fake process only; no operational Store/provider."""
import importlib.util,json,sys,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
import otto.hostctl.supervision as original
import otto.portfolio.execution_host as hosts
s=original
supervise=hosts.ExecutionHost.supervise
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
class SupersessionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.parent=self.root/'parent.json';self.first=self.root/'first.json';self.next=self.root/'next.json';self.identity={'source_commit':'parent'}
  class Process:
   pid=10
   def wait(self,timeout):return 0
  with patch.dict(sys.modules,{'otto.hostctl.supervision':s}):
   supervise(argv=['fake-owner'],receipt_path=self.parent,source_identity=self.identity,reconcile=lambda _: {'ready':True},disposition=lambda:'active',request_stop=lambda _:None,process_factory=lambda *a,**k:Process(),max_restarts=2)
  exits={x.name:sha(x)for x in self.root.glob('parent.json.exit-*.json')}
  self.custody={'ordinary_exit_status':0,'store_closed':True,'owner_alive':False,'supervisor_alive':False,'native_active_or_uncertain':0,'holds':[],'in_flight':[],'owner_pid':10,'supervisor_pid':20}
  self.origin=s.prepare_planned_maintenance(old_path=self.parent,expected_policy_sha256=sha(self.parent),expected_exits=exits,new_path=self.first,source_identity={'source_commit':'first'},request_key='first',custody=self.custody)
  self.launch=self.root/'owner-launch.json';self.launch.write_text(json.dumps({'supervision_path':str(self.parent),'source_commit':'parent','pid':10,'monitor_pid':20}))
  self.proof=self.root/'root-proof.json';self.proof.write_text(json.dumps({'schema':'otto.root-never-launched-preparation-custody.v1','original_482_policy_path':str(self.first),'original_482_policy_sha256':sha(self.first),'original_e921_owner_pid':10,'original_e921_supervisor_pid':20,'original_e921_processes_dead':True,'launchd_label_absent':True,'matching_live_owner_or_supervisor_processes':[],'unused_482_exit_files':[],'root_exclusive_custody':True,'current_config_still_selects_original_482_intent':True,'root_operator_attestation':'fixture exclusive no launch','store_closed':True,'native_active_or_uncertain':0,'holds':[]}))
  self.evidence={'owner_launch_path':str(self.launch),'owner_launch_sha256':sha(self.launch),'exclusive_closed_operator':True,'root_custody_path':str(self.proof),'root_custody_sha256':sha(self.proof)}
 def apply(self,identity=None):return s.supersede_unlaunched_preparation(old_path=self.first,expected_policy_sha256=sha(self.first),new_path=self.next,source_identity=identity or {'source_commit':'corrected'},request_key='corrected',custody=self.custody,unused_evidence=self.evidence)
 def test_exact_replay_preserves_every_original_and_budget_old_seed_denied(self):
  before=self.parent.read_bytes(),self.first.read_bytes(),Path(str(self.parent)+'.maintenance.json').read_bytes()
  result=self.apply();self.assertEqual(result['automatic_restart_budget'],self.origin['automatic_restart_budget']);self.assertEqual(self.apply(),result)
  self.assertEqual(before,(self.parent.read_bytes(),self.first.read_bytes(),Path(str(self.parent)+'.maintenance.json').read_bytes()))
  intent={'supervision_path':str(self.next),'argv':['fake-owner'],'metadata':{'source_commit':'corrected'}}
  self.assertEqual(s.maintenance_restart_limit(intent),2)
  with self.assertRaises(PermissionError):s.maintenance_restart_limit({'supervision_path':str(self.first),'argv':['fake-owner'],'metadata':{'source_commit':'first'}})
  with patch.dict(sys.modules,{'otto.hostctl.supervision':s}),self.assertRaises(PermissionError):supervise(argv=['fake-owner'],receipt_path=self.first,source_identity={'source_commit':'first'},max_restarts=2,resume=True,reconcile=lambda _: {'ready':True},disposition=lambda:'active',request_stop=lambda _:None,process_factory=lambda *a,**k:self.fail('old policy launched'))
 def test_marker_before_seed_loss_exact_replay_and_changed_input_refuse(self):
  original_create=s._private_create
  def fail(path,value):
   if path==self.next:raise OSError('lost seed publication')
   return original_create(path,value)
  with patch.object(s,'_private_create',side_effect=fail),self.assertRaises(OSError):self.apply()
  self.assertTrue(Path(str(self.first)+'.supersession.json').exists());self.assertFalse(self.next.exists())
  with self.assertRaises(PermissionError):self.apply({'source_commit':'foreign'})
  self.apply();self.assertTrue(self.next.exists())
 def test_started_unknown_or_wrong_custody_refuses(self):
  self.assertTrue(s.claim_supervision_launch(self.first,index=0,policy_sha256=json.loads(self.first.read_text())['policy_sha256']))
  with self.assertRaises(PermissionError):self.apply()
  self.assertFalse(self.next.exists())
 def test_live_or_changed_no_launch_proof_refuses_before_marker(self):
  self.custody['owner_alive']=True
  with self.assertRaises(PermissionError):self.apply()
  self.custody['owner_alive']=False
  proof=json.loads(self.proof.read_text());proof['launchd_label_absent']=False;self.proof.write_text(json.dumps(proof));self.evidence['root_custody_sha256']=sha(self.proof)
  with self.assertRaises(PermissionError):self.apply()
  self.assertFalse(Path(str(self.first)+'.supersession.json').exists())
 def test_unknown_exit_prevents_supersession(self):
  Path(str(self.first)+'.exit-0.json').write_text(json.dumps({'exit_status':None}))
  with self.assertRaises(PermissionError):self.apply()
  self.assertFalse(self.next.exists())
 def test_successor_launch_once_lost_launch_exit_does_not_spawn_again(self):
  self.apply();calls=[]
  class Process:
   pid=10
   def wait(self,timeout):return 0
  kwargs=dict(argv=['fake-owner'],receipt_path=self.next,source_identity={'source_commit':'corrected'},max_restarts=2,resume=True,reconcile=lambda _: {'ready':True},disposition=lambda:'active',request_stop=lambda _:None,process_factory=lambda *a,**k:(calls.append(1)or Process()))
  with patch.dict(sys.modules,{'otto.hostctl.supervision':s}):
   result=supervise(**kwargs);self.assertEqual(result['outcome'],'closed');self.assertEqual(supervise(**kwargs)['outcome'],'closed')
  self.assertEqual(len(calls),1);self.assertEqual(result['restart_allowance']['remaining'],2)
  # The same durable claim without an exit cannot become a second process.
  (self.root/(self.next.name+'.exit-0.json')).unlink()
  with patch.dict(sys.modules,{'otto.hostctl.supervision':s}):self.assertEqual(supervise(**kwargs)['outcome'],'unknown')
  self.assertEqual(len(calls),1)
if __name__=='__main__':unittest.main()
