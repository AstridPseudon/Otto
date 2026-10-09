"""Host contract authority checks before provider initialization."""
import copy,unittest
from types import SimpleNamespace
from herzchen.adapters.host import workspace_delivery_contract
class CoordinatorHostContractTests(unittest.TestCase):
 def setUp(self):
  self.contract={'allowed_operations':['read_project_context','edit_candidate_workspace','run_focused_tests','return_progress','canonical_child_commands'],'delegation':{'max_depth':1,'result_consumption':'yield'},'authority':{'source':'canonical_owner','effect_profile':'workspace-write-worker','workspace_roots':['/workspace','/controller'],'permitted_effects':['read_delivered_context','read_linked_sources','file_write_in_workspace','return_result','canonical_child_commands']}}
 def test_only_exact_existing_coordinator_extension_is_supported(self):
  self.contract['authority'].update(owner_write=False,dispatch=False,gateway_claim_required=True)
  self.assertTrue(workspace_delivery_contract(self.contract,'workspace-write','worker',('/workspace','/controller')))
  for field,value in [('delegation',{'max_depth':2,'result_consumption':'yield'}),('delegation',{'max_depth':1,'result_consumption':'poll'}),('allowed_operations',self.contract['allowed_operations']+['canonical_manager_commands'])]:
   c=copy.deepcopy(self.contract);c[field]=value;self.assertFalse(workspace_delivery_contract(c,'workspace-write','worker',('/workspace','/controller')))
  for role,profile,roots in [('manager','workspace-write',('/workspace','/controller')),('worker','read-only',('/workspace','/controller')),('worker','workspace-write',('/workspace','/foreign'))]:self.assertFalse(workspace_delivery_contract(self.contract,profile,role,roots))
  c=copy.deepcopy(self.contract);c['authority']['permitted_effects'].remove('canonical_child_commands');self.assertFalse(workspace_delivery_contract(c,'workspace-write','worker',('/workspace','/controller')))
  for field in ('owner_write','dispatch'):
   c=copy.deepcopy(self.contract);c['authority'][field]=True;self.assertFalse(workspace_delivery_contract(c,'workspace-write','worker',('/workspace','/controller')))
 def test_invalid_coordinator_is_refused_before_initializer_construction(self):
  from otto.agents.herzchen_adapter import HerzchenCodexAdapter,HerzchenAdapterError
  adapter=object.__new__(HerzchenCodexAdapter);adapter.require_host_context=True;adapter.turn_context_reader=lambda *a:None
  adapter._owner_delivery_verifier=lambda *a:None;adapter.worktree='/workspace';adapter.writable_roots=('/controller',)
  bad=copy.deepcopy(self.contract);bad['delegation']['max_depth']=2
  adapter._typed_request=lambda *a:(SimpleNamespace(requested_profile='workspace-write'),'digest',{'instruction_contract':bad})
  calls=[];adapter._new_host=lambda *a,**kw:calls.append(kw)
  with self.assertRaisesRegex(HerzchenAdapterError,'before initialization'):adapter._invoke_owner_authorized({'expected_role':'worker'})
  self.assertEqual(calls,[])
if __name__=='__main__':unittest.main()
