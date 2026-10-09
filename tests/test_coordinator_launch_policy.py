"""Finite owner allocation checks with synthetic provider; no installed proof."""
import copy,json,unittest
from tests.test_external_owner_execution import ExternalOwnerExecutionTests
class CoordinatorLaunchPolicyTests(ExternalOwnerExecutionTests):
 def config_coordinator(self):
  self.f.config['worker_operation_profiles']={'D02':'coordinating_implementation'}
  (self.f.run/'run.yaml').write_text(json.dumps(self.f.config))
  self.f.server.state['worker_role_configuration_ref']=self.f.roles.document('role_configuration',{'schema':'otto.role-configuration.v1','roles':self.f.config['roles'],'role_bindings':{'worker':'worker_normal'},'tool_entrypoints':{'worker':'/usr/bin/python3 /installed/manager_ctl.py'}})
  policy={'task':'D02','principal':'installed-coordinator','route':'normal','model':'gpt-test','reasoning':'high','native_adapter':self.f.f.app.native_adapter_identity(),'capacity_units':1,'max_depth':1,'cumulative_allowance_units':6,'root_assignment_ref':self.root.ref.to_dict(),'root_generation':1,'project_ref':self.f.server.state['project_ref'],'task_ref':self.f.server.state['task_refs']['D02'],'role_configuration_ref':self.f.server.state['worker_role_configuration_ref']}
  report=self.f.server.owner.assignments.command_port.append_report(self.root.ref,{'schema':'otto.owner-coordinator-launch-policy.v1','policy':policy},expected_generation=1,logical_request_key='test-coordinator-allocation',actor=self.f.server.owner.owner_actor)
  self.f.server.state['coordinator_launch_policy']={**policy,'allocation_report_ref':report.ref.to_dict()}
  self.request={'command':'run-worker','task':'D02','route':'normal','principal':policy['principal'],'request_key':'finite-installed-coordinator','focus':'Coordinate one bounded child; yield and consume it.'}
 def test_explicit_policy_binds_new_coordinator_and_remaining_three_turns(self):
  self.config_coordinator();calls=len(self.f.f.provider.calls);result=self.f.host._dispatch(self.request,ingress=__import__('otto.portfolio.identity_context',fromlist=['HostIngress']).HostIngress('file-ipc',self.f.host.directory/'owner-preparation'))
  self.assertEqual(result['outcome'],'admitted',result)
  self.assertEqual(len(self.f.f.provider.calls),calls)
  self.assertEqual(self.s.delegation_policy['coordinators'][0]['assignment_ref'],result['assignment_ref'])
  self.assertEqual(self.s.delegation_policy,self.f.server.state['delegation_policy'])
  from otto.attention import DueRecord
  from otto.portfolio.role_context import role_introduction
  due=self.f.f.port.read_due(result['occurrence']['schedule_id'])
  prepared=self.f.f.app.runtime.prepare_execution_readiness(due=DueRecord.from_dict(due))
  self.assertEqual(role_introduction(prepared['canonical_evidence'])['tool_entrypoint'],'/usr/bin/python3 /installed/manager_ctl.py')
 def test_stale_policy_and_missing_three_turns_reject_before_assignment(self):
  self.config_coordinator();base=copy.deepcopy(self.f.server.state['coordinator_launch_policy']);counts=self.f.f.store.consumer().snapshot_counts();calls=len(self.f.f.provider.calls)
  for field,value in [('task_ref',{**base['task_ref'],'revision':'rev-99'}),('root_generation',2),('role_configuration_ref',{**base['role_configuration_ref'],'revision':'rev-99'}),('model','other'),('max_depth',2),('cumulative_allowance_units',2)]:
   self.f.server.state['coordinator_launch_policy']={**base,field:value}
   with self.subTest(field=field),self.assertRaises(PermissionError):self.s._submit_worker(self.request)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts);self.assertEqual(len(self.f.f.provider.calls),calls)
 def adopt_configuration(self,configref):
  from herzchen.contracts import ResourceRef
  from herzchen.content.instructions import validate_instruction_content
  manager=self.f.server.owner.assignments.get(self.f.server.state['assignment_ref'])
  item=manager.payload['resource_adoptions'][0]
  body=copy.deepcopy(self.f.server.owner.content.command_port.read(ResourceRef.from_dict(item['resource_ref']))['content'])
  body['supporting_refs']=[configref]
  guide=self.f.roles.document('role_instructions',body)
  adopted=self.f.server.owner.assignments.adopt_resources(manager.ref,resources=[{**item,'resource_ref':guide,'content_digest':validate_instruction_content(body)}],expected_revision=manager.revision,expected_generation=manager.generation,logical_request_key='configuration-selection',actor=self.f.server.owner.owner_actor)
  self.f.server.state['assignment_ref']=adopted.ref.to_dict()
 def test_same_adopted_configuration_is_selected_once(self):
  self.config_coordinator();self.adopt_configuration(self.f.server.state['worker_role_configuration_ref'])
  self.assert_launch_selected_configuration()
 def assert_launch_selected_configuration(self):
  result=self.f.host._dispatch(self.request,ingress=__import__('otto.portfolio.identity_context',fromlist=['HostIngress']).HostIngress('file-ipc',self.f.host.directory/'owner-preparation'))
  self.assertEqual(result['outcome'],'admitted',result)
  from otto.attention import DueRecord
  from otto.portfolio.role_context import selected_configuration
  due=self.f.f.port.read_due(result['occurrence']['schedule_id'])
  ready=self.f.f.app.runtime.prepare_execution_readiness(due=DueRecord.from_dict(due))
  self.assertEqual(selected_configuration(ready['canonical_evidence']['supporting_context'])['ref'],self.f.server.state['worker_role_configuration_ref'])
 def test_conflicting_adopted_configuration_rejects_before_assignment(self):
  self.config_coordinator()
  other=self.f.roles.document('role_configuration',{'schema':'otto.role-configuration.v1','roles':self.f.config['roles'],'role_bindings':{'worker':'worker_normal'}})
  self.adopt_configuration(other)
  counts=self.f.f.store.consumer().snapshot_counts();calls=len(self.f.f.provider.calls)
  from otto.portfolio.role_context import RoleContextError
  with self.assertRaisesRegex(RoleContextError,'more than one role configuration'):self.s._submit_worker(self.request)
  self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts);self.assertEqual(len(self.f.f.provider.calls),calls)
if __name__=='__main__':unittest.main()
