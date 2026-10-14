"""One remaining W0 Astra advice call, through existing AdvisorExecution.

Preparation is owner-bound/read-only-profile and provider-free. Native review
is separate from the manager's four ordinary canonical acceptance judgments.
No future transport handler is installed by this prepared source file.
"""
from copy import deepcopy
import hashlib
from herzchen.contracts import ResourceRef
from herzchen.content.instructions import validate_instruction_content
from herzchen.kernel.limits import LimitService
from otto.portfolio.advisor_execution import AdvisorExecution
from otto.portfolio.owner_completion import after_owner
from otto.portfolio.owner_readers import json_value
from otto.hostctl.register import _manager_contract
import w0_same_manager_migration as migration
import w0_completion_policy as completion

KEY='W0-one-remaining-Astra-final-20261013-v1'
SCHEMA='otto.W0-one-remaining-Astra-final.v1'
def require(value,message):
 if not value:raise PermissionError(message)

def prepare(service,*,actor,candidate_refs,execution_factory):
 owner,project,manager,migrated=completion.current(service,actor)
 require(service.server.state.get('W0_completion_policy_input_sha256'),
  'ordinary original acceptance policy must be adopted before final review preparation')
 require(isinstance(candidate_refs,list)and 1<=len(candidate_refs)<=16,'finite actual substantive candidate refs required')
 selected=[]
 for value in candidate_refs:
  pin=ResourceRef.from_dict(value)
  require(pin.authority==project.ref.authority and pin.revision and pin.kind in('wrk.report','wrk.result'),
   'final inputs must pin substantive original W0 manager work observations')
  row=owner.store.consumer().get_record(pin)
  require(row is not None and row.ref==pin and row.payload.get('assignment',{}).get('id')==manager.id
   and row.payload.get('generation')==2,'final candidate is foreign/stale or from original unknown initializer')
  body=row.payload.get('value')
  require(isinstance(body,dict)and body.get('schema')not in(migration.SCHEMA+'.completed',completion.SCHEMA+'.completed')
   and body,'setup/guide receipts cannot substitute for substantive final-review work')
  require(len(__import__('json').dumps(body,sort_keys=True).encode())<=131072,'final candidate requires existing bounded source snapshot before review')
  selected.append({'ref':pin.to_dict(),'body_sha256':migration.digest(body),'content':deepcopy(body)})
 require(len(__import__('json').dumps(selected,sort_keys=True).encode())<=262144,'finite complete selected final candidate snapshot exceeds bound')
 inputs={'project_ref':project.ref.to_dict(),'manager_ref':manager.ref.to_dict(),'generation':2,'candidates':selected,
  'completion_policy_input_sha256':service.server.state['W0_completion_policy_input_sha256'],
  'pool_ref':migrated['new_pool_refs']['final-astra'],'prior_source_reviews':2,'remaining_call_cap':1}
 reports=owner.assignments.list_observations(manager.ref,kind='report')
 matched=[r for r in reports if isinstance(r.value,dict)and r.value.get('schema')==SCHEMA+'.prepared']
 require(len(matched)<=1,'one final-review preparation must be unambiguous')
 if matched:
  require(matched[0].value['input_sha256']==migration.digest(inputs),'original final-review key/input changed; preserve prior effect')
  return {**matched[0].value['result'],'replayed':True}
 limits=LimitService(owner.store);pool=limits.get_pool(ResourceRef.from_dict(inputs['pool_ref']))
 require(pool is not None and pool.capacity_units==pool.cumulative_allowance_units==1
  and pool.held_units==pool.cumulative_used_units==0 and pool.remaining_allowance_units==1,
  'only the genuinely unused one remaining final pool can prepare initial review')
 state=service.server.state;task=next(iter(state['task_refs'].values()))
 with owner.store.transaction():
  advisor=owner.assignments.assign(project.ref,role='project_advisor',principal='otto-W0-one-final-Astra-20261013',
   manager=actor.actor,agent='codex:gpt-6-astra',logical_request_key=KEY+':advisor',actor=actor)
  prompt=('Perform the one remaining human-authorized W0 final source/use review, read-only. '
   'Inspect original E1-E4 acceptance criteria, the current accepted source/runtime/skill closure and the delivered substantive candidate evidence. '
   'Two source advisory reviews already occurred; this is at most the third and final call. '
   'Return one bounded report with separate PASS/REWORK/UNKNOWN findings for the four original tasks and exact evidence. '
   'No source edits, delegated children, provider retries, new tasks, role/manager replacement or acceptance writes. '
   'The same Luna manager remains the canonical approver; this advice is not automatic task acceptance. '
   'Preserve old initializer UNKNOWN usage/payment and every original pool/receipt.\n'
   +'Pinned candidate metadata: '+__import__('json').dumps([{k:v for k,v in row.items()if k!='content'}for row in selected],sort_keys=True))
  configuration={'schema':'otto.role-configuration.v1','model_profile':'codex',
   'roles':{'final_reviewer':{'adapter':'codex','model':'gpt-6-astra','reasoning':'high'}},
   'role_bindings':{'project_advisor':'final_reviewer'},'operational_supervisor':migrated['root_help_binding'],
   'manager_context_required':True,'tool_entrypoints':{'project_advisor':__import__('w0_initial_manager_direction').NATIVE_ENTRY},
   'source':{'human_override':True,'same_W0_only':True,'source_reviews_already_used':2,'remaining_final_calls':1}}
  config_ref=migration._document(owner,service.server.due_port,project.ref.to_dict(),KEY+':configuration','W0-one-Astra-final-config',configuration,'configuration')
  snapshot_ref=migration._document(owner,service.server.due_port,project.ref.to_dict(),KEY+':candidate-snapshot','W0-one-Astra-final-candidate-snapshot',
   {'schema':'otto.W0-final-candidate-source-snapshot.v1','source_refs':[r['ref']for r in selected],
    'sources':selected,'original_heads_and_hashes_retained':True,'input_sha256':migration.digest(inputs)},'source')
  guide={'schema':'herzchen.instructions.v1','name':'W0-one-remaining-Astra-final-BASE','entrypoint':'review.md','required':True,
   'instructions':prompt,'bundle_digest':hashlib.sha256(prompt.encode()).hexdigest(),
   'export_manifest_digest':migration.digest(inputs),'supporting_refs':[config_ref,snapshot_ref]}
  guide_ref=migration._document(owner,service.server.due_port,project.ref.to_dict(),KEY+':BASE','W0-one-Astra-final-BASE',guide,'supporting')
  advisor=owner.assignments.command_port.adopt_resources(advisor.ref,
   resources=[{'resource_ref':guide_ref,'resource_name':guide['name'],'content_digest':validate_instruction_content(guide),'required':True}],
   expected_revision=advisor.revision,expected_generation=advisor.generation,logical_request_key=KEY+':BASE-adopt',actor=actor)
  contract=_manager_contract(task,advisor.principal,str(service.workspace),'W0-final-review')
  contract.update(objective='Read-only final review of original W0 E1-E4 evidence',bounded_operation=prompt,
   read_scope='linked_context',allowed_operations=['read_project_context','return_advice'])
  contract['authority'].pop('effect_profile');contract['authority'].pop('workspace_roots')
  contract['authority']['permitted_effects']=['read_delivered_context','read_linked_sources','return_advice']
  contract['authority']['forbidden_effects'].append('file_write')
  mandate={'role':'project_advisor','scope_ref':project.ref.to_dict(),'task_ref':task,'status':'active','dispatch_enabled':True,
   'assignment_ref':advisor.ref.to_dict(),'generation':advisor.generation,'instruction_contract':contract,
   'brief':{'role':'project_advisor','mandate':'One remaining bounded read-only final review; Luna manager retains approval'}}
  mandate_ref=migration._document(owner,service.server.due_port,project.ref.to_dict(),KEY+':mandate','W0-one-Astra-final-mandate',mandate,'mandate')
  app=execution_factory(advisor.principal)
  require(app.actor==actor.actor and app.assignments is owner.assignments.command_port and app.due_port is service.server.due_port,
   'one final reviewer requires the same owned ordinary execution ports')
  prepared=app.prepare_role(role='project_advisor',project_ref=project.ref.to_dict(),task_ref=task,
   assignment_ref=advisor.ref.to_dict(),generation=advisor.generation,mandate_ref=mandate_ref,
   request_key=KEY+':role',instruction=prompt,model='gpt-6-astra',reasoning='high',profile='read-only',
   allowance_ref=pool.ref.to_dict())
  require(prepared.get('outcome')in('prepared','committed','replayed'),'one final readonly role did not prepare')
  value={'schedule_id':prepared['schedule_id'],'assignment_ref':advisor.ref.to_dict(),'generation':advisor.generation,
   'pool_ref':pool.ref.to_dict(),'profile':'read-only','model':'gpt-6-astra','reasoning':'high',
   'candidate_refs':candidate_refs,'input_sha256':migration.digest(inputs),'provider_called':False,'source_review_calls_used':2,
   'remaining_final_call_cap':1,'same_manager_approval_required':True}
  owner.assignments.append_report(manager.ref,{'schema':SCHEMA+'.prepared','input_sha256':migration.digest(inputs),'result':value},
   expected_generation=2,logical_request_key=KEY+':prepared',actor=actor)
  return value

class FinalAdvisorExecution(AdvisorExecution):
 """Same reserve/settle semantics, respecting typed owner completion."""
 def _deliver(self,delivery):
  app=self.execution;schedule,key=delivery['schedule_id'],delivery['request_id'];due=app._read(schedule)
  require(due.project_ref==migration.PROJECT and due.role=='project_advisor'
   and(due.requested_model,due.requested_reasoning,due.profile)==('gpt-6-astra','high','read-only')
   and key in{due.in_flight_request,due.last_completed_request},'exact current one-final advisor occurrence required')
  due=app._resources(due)
  require(due.allowance_ref==self.allowance_ref.to_dict(),'one final occurrence pool differs')
  actor=app.binding.authenticated_actor(app.actor)
  reservation=self.allowance.reserve(self.allowance_ref,'advisor-turn-'+__import__('otto.portfolio.advisor_execution',fromlist=['_digest'])._digest([schedule,key])[:28],1,
   logical_request_key=key+':reserve',actor=actor)
  try:value=app.start(schedule_id=schedule,settle=False)
  except BaseException:self._settle(reservation,schedule,key,actor);raise
  def completed(value):self._settle(reservation,schedule,key,actor);return value
  def failed(error):self._settle(reservation,schedule,key,actor);raise error
  return after_owner(value,completed,failed)

def compose(service,prepared):
 """Explicit final pool accounting; no manager/worker wrapper bypass.

 The final role has its own ordinary readonly runtime. AdvisorExecution owns
 its reservation, including UNKNOWN/held settlement; manager/worker pools
 remain enforced on their original factory and no model route is generalized.
 """
 owner=service.server.owner
 wrapped=service._execution(principal=owner.assignments.get(ResourceRef.from_dict(prepared['assignment_ref'])).principal,
  model='gpt-6-astra',reasoning='high',evidence_id=KEY+':same-owner-final')
 app=owner.execution_application(due_port=service.server.due_port,adapter=wrapped.runtime.adapter,
  manager_actor=owner.owner_actor.actor,issue_delivery=service.server.help_delivery,
  native_result_verifier=wrapped.runtime.native_result_verifier)
 return FinalAdvisorExecution(execution=app,allowance=LimitService(owner.store),allowance_ref=prepared['pool_ref'])
