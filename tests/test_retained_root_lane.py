"""The original queued request is consumed on its own authenticated lane."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import os
from test_root_direction_client import RootDirectionClientTests
from otto.portfolio import client_lanes as lanes
from otto.portfolio.orchestrator_client import OrchestratorLanePump, submit_exact
from otto.portfolio.retained_root_lane import load_retained_root_lane
from otto.portfolio.root_direction_client import install_owner_root_client

class RetainedRootLaneTests(TestCase):
 def setUp(self):
  self.f=RootDirectionClientTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.controller=self.f.f.path.parent/'controller'
  self.ids=[p.ref.id for p in self.f.projects]
  self.state={**self.f.state,'root_help_binding':{**self.f.state['root_help_binding'],'conversation_ref':self.f.root.session}}
  self.seen=[]
  def handler(request,root):
   self.seen.append(request);return {'outcome':'read','provider_called':False}
  self.handler=handler
  self.original,self.client=install_owner_root_client(service=self.f.service,directory=self.controller/'clients/owner-root',conversation_ref=self.f.root.session,request_key='old-root',project_ids=self.ids,project_handler=handler)
  self.private,self.current=install_owner_root_client(service=self.f.service,directory=self.f.f.path.parent/'private/clients/owner-root',conversation_ref=self.f.root.session,request_key='old-root',project_ids=self.ids,project_handler=handler)
 def load(self,clients):
  return load_retained_root_lane(clients=clients,controller=self.controller,owner=self.f.owner,main_state=self.state,project_ids=self.ids,handler=self.handler)
 def test_same_policy_distinct_lanes_consumes_original_without_republish(self):
  request={'operation':'read-help','project_id':self.ids[0],'request_key':'original-help'}
  token=submit_exact(self.original['lane'],request,namespace=self.original['binding']['request_namespace'],request_key=request['request_key'])
  original_path=Path(self.original['lane'])/('request-'+token+'.json');before=original_path.read_bytes()
  clients={Path(self.private['lane']):self.current}
  with patch('otto.portfolio.client_lanes.submit',side_effect=AssertionError('no republish')):self.load(clients)
  pump=OrchestratorLanePump(owner_inbox=self.f.f.path.parent/'inbox',admissions=self.f.admissions,clients=clients,owner_call=lambda f:f())
  pump.poll();response=lanes.read_private_json(Path(self.original['lane'])/('response-'+token+'.json'))
  self.assertEqual(response['outcome'],'read');self.assertEqual(response['request_id'],token)
  self.assertEqual(original_path.read_bytes(),before);self.assertEqual(len(self.seen),1)
  self.assertFalse((Path(self.private['lane'])/('request-'+token+'.json')).exists())
  pump.poll();self.assertEqual(len(self.seen),1)
 def test_lane_collision_foreign_scope_policy_and_symlink_fail(self):
  with self.assertRaises(PermissionError):self.load({Path(self.original['lane']):self.client})
  path=self.controller/'clients/owner-root/binding.json'
  for field,value in [('principal','foreign'),('policy_ref',{**self.original['binding']['policy_ref'],'revision':'rev-999'}),('project_ids',['foreign'])]:
   value_locator=deepcopy(self.original);value_locator['binding'][field]=value;lanes.atomic_json(path,value_locator)
   with self.assertRaises(PermissionError):self.load({})
  lanes.atomic_json(path,self.original)
  path.unlink();path.symlink_to(self.f.f.path.parent/'foreign')
  with self.assertRaises(PermissionError):self.load({})
 def test_absent_original_is_optional_but_never_created(self):
  absent=self.f.f.path.parent/'absent'
  self.assertIsNone(load_retained_root_lane(clients={},controller=absent,owner=self.f.owner,main_state=self.state,project_ids=self.ids,handler=self.handler))
  self.assertFalse(absent.exists())
