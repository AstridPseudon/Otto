"""Native5 keeps original issued policies but never grants their stale calls."""
import importlib.util,unittest
from pathlib import Path
import test_retained_root_lane as fixtures
HERE=Path(__file__).resolve().parent
import otto.portfolio.retained_root_lane as m
class Native5RetainedPolicyTests(unittest.TestCase):
 def test_sealed_composition_preserves_authentic_old_lane_and_stale_calls_refuse(self):
  f=fixtures.RetainedRootLaneTests();f.setUp();self.addCleanup(f.doCleanups)
  updated=f.f.client.call(f.f.intent())
  state={**f.state,'orchestrator_assignment_ref':updated['assignment_ref'],'root_help_binding':{**f.state['root_help_binding'],'assignment_ref':updated['assignment_ref']}}
  args={'clients':{},'controller':f.controller,'owner':f.f.owner,'main_state':state,'project_ids':f.ids,'handler':f.handler}
  with self.assertRaises(PermissionError):m.load_retained_root_lane(**args)
  result=m.load_retained_root_lane(**args,retain_stale_policy=True)
  self.assertEqual(result,f.original)
  self.assertEqual(len(args['clients']),1)
  client=args['clients'][Path(f.original['lane'])]
  with self.assertRaisesRegex(PermissionError,'stale or foreign'):client.call({'operation':'status','request_key':'stale-root'})
  self.assertEqual(f.seen,[])
 def test_retained_stale_policy_still_refuses_colliding_lane(self):
  f=fixtures.RetainedRootLaneTests();f.setUp();self.addCleanup(f.doCleanups)
  with self.assertRaisesRegex(PermissionError,'collides'):
   m.load_retained_root_lane(clients={Path(f.original['lane']):f.client},controller=f.controller,owner=f.f.owner,main_state=f.state,project_ids=f.ids,handler=f.handler,retain_stale_policy=True)
if __name__=='__main__':unittest.main()
