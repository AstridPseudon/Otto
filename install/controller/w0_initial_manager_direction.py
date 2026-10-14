"""First W0 manager direction, exact native-tool context and one continuation.
Authentic existing issued supervisor only; no provider, new role or pool.
"""
from copy import deepcopy
import hashlib
from herzchen.contracts import ResourceRef,TransactionContext,canonical_json
from herzchen.content import ContentDocument,ContentRevision
from herzchen.content.instructions import validate_instruction_content
from otto.portfolio.owner_readers import json_value
from otto.portfolio.manager_guide import resolve_required_instruction_adoption
import w0_same_manager_migration as migration
SOCKET='/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010/caller.sock'
IPC='/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller/manager-ipc'
NATIVE_ENTRY=f'env OTTO_CALLER_SOCKET={SOCKET} OTTO_MANAGER_IPC={IPC} /Users/hannahomalley/.otto/bin/ottoctl --home /Users/hannahomalley/.otto manager'
def require(value,message):
 if not value:raise PermissionError(message)
def digest(value):return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def append(owner,pin,content,key):
 pin=ResourceRef.from_dict(pin);head=json_value(owner.content.read(ResourceRef(pin.authority,pin.kind,pin.id)))
 require(head['current_revision']==pin.to_dict(),'exact canonical document head changed')
 document=ContentDocument.from_dict(head['document'])
 require(document.maintainer==owner.owner_actor.actor and document.writable and document.import_mode=='owned','authentic owned writable context required')
 revision=ContentRevision(document.ref,'rev-'+digest([key,content])[:28],content,owner.owner_actor,parent_revision=pin.revision)
 tx=TransactionContext(owner.owner_actor,key,digest(content),expected_revision=pin.revision,expected_version=head['version'])
 owner.content.execute(owner.content.build_append_revision(tx,document,revision));return revision.ref.to_dict()
def apply(authoring,request,root,manager,direction,common):
 from otto.portfolio.supervisor_direction_client import current_purpose_content
 service,owner=authoring.service,authoring.owner;state=service.server.state;payload=request.get('request')or{};key=request['request_key']
 fields={'expected_manager_ref','expected_manager_generation','expected_schedule_id','expected_binding_ref','expected_direction_ref','initial_direction_content','expected_configuration_ref'}
 require(set(payload)==fields and len(canonical_json(payload).encode())<=16384,'finite exact first-binding context fields required')
 require(state['project_ref']['id']==migration.PROJECT and manager.ref.id==migration.MANAGER and manager.generation==2
  and manager.payload.get('manager')==root.principal==owner.owner_actor.actor==migration.OWNER
  and direction['state']=='unbound'and direction.get('binding_ref')is None and direction.get('document_ref')is None,
  'first binding requires authentic same W0 supervisor/current manager unbound responsibility')
 require(payload['expected_manager_ref']==manager.ref.to_dict()and payload['expected_manager_generation']==2
  and payload['expected_schedule_id']==service._current_manager_schedule()
  and payload['expected_binding_ref']is None and payload['expected_direction_ref']is None
  and payload['expected_configuration_ref']==state['role_configuration_ref'],'first-binding CAS pins changed')
 app=service._execution(principal=manager.principal,model=state['requested_model'],reasoning=state['requested_reasoning'],evidence_id='first-supervisor-direction')
 prior=app._read(payload['expected_schedule_id']);app._manager_adoption_anchor(prior)
 require(prior.stop_state=='completed'and prior.completion_state=='succeeded'and prior.in_flight_request is None
  and (prior.last_result or{}).get('physical_session_id'),'first binding requires genuine useful settled same-session manager anchor')
 _,_,held=app._manager_anchor(prior,manager,schedule='first-supervisor-direction',purpose='first supervisor direction')
 if held:return{**common,**held,'canonical_effect_recorded':False}
 resources=deepcopy(manager.payload.get('resource_adoptions',[]))
 base,before,_=resolve_required_instruction_adoption(resources,state['guide_ref'],owner.content)
 original_base_ref=deepcopy(base['resource_ref']);original_body=deepcopy(before['content']);old_config=state['role_configuration_ref']
 require(original_body.get('supporting_refs',[]).count(old_config)==1,'canonical BASE must pin exact existing role configuration once')
 configuration=deepcopy(json_value(owner.content.read(ResourceRef.from_dict(old_config)))['content'])
 require(configuration.get('schema')=='otto.role-configuration.v1'and configuration.get('new_finite_allocations')==state['new_pool_refs'],
  'existing canonical role configuration/pools differ')
 instructions=deepcopy(payload['initial_direction_content']);validate_instruction_content(instructions)
 require(not instructions.get('current_purpose'),'initial direction cannot borrow another current purpose')
 # Existing controlling context remains explicitly pinned as history. The caller
 # supplies current work intent; no semantic task acceptance is manufactured.
 inherited=list(original_body.get('supporting_refs',[]))
 require(instructions.get('supporting_refs',[])==inherited,'first direction must preserve exact existing supporting context pins')
 staged=deepcopy(state)
 with owner.store.transaction():
  configuration['tool_entrypoints']={**configuration['tool_entrypoints'],'manager':NATIVE_ENTRY,'worker':NATIVE_ENTRY}
  config_ref=append(owner,old_config,configuration,key+':native-tool-context')
  instructions['supporting_refs']=[config_ref if pin==old_config else pin for pin in inherited]
  direction_ref=migration._document(owner,service.server.due_port,state['project_ref'],key+':owned-direction',
   'W0-first-manager-direction-'+digest([manager.ref.id,key])[:20],instructions,'direction')
  surface=owner.direction_surface();subject=ResourceRef.from_dict(manager.payload['responsibility_ref'])
  bound=surface.initial_bind(subject,{**direction_ref,'revision':None},logical_request_key=key+':initial-bind')
  bound_direction=bound # authentic initial binding identity; scope adoption is not effective yet
  body=current_purpose_content(original_body,direction_ref=direction_ref,instructions=instructions['instructions'],inherited_ref=base['resource_ref'])
  body['supporting_refs']=[config_ref if pin==old_config else pin for pin in inherited]+[direction_ref]
  base_ref=append(owner,base['resource_ref'],body,key+':BASE')
  base.update(resource_ref=base_ref,content_digest=validate_instruction_content(body))
  adopted=surface.update(subject,ResourceRef.from_dict(direction_ref),logical_request_key=key+':adopt',
   expected_binding_ref=bound_direction['binding_ref'],assignment_ref=manager.ref,expected_generation=2,assignment_resources=resources,
   assignment_actor=owner.binding.authenticated_actor(root.principal))
  require(not adopted['partial'],'first direction resource adoption did not complete')
  current=owner.assignments.get(adopted['assignment_refresh']['assignment_ref'])
  value={**common,'schema':'otto.supervisor-directive-application.v1','outcome':'adopted','request_digest':digest(payload),
   'before_manager_ref':manager.ref.to_dict(),'manager_assignment_ref':current.ref.to_dict(),'direction_ref':direction_ref,
   'BASE_ref':base_ref,'adoption_key':key+':adopt:assignment','anchor_schedule_id':prior.schedule_id,'anchor_sha256':app.directive_anchor_digest(prior),
   'continuation_schedule_id':'manager-directive-'+digest([root.ref.to_dict(),key])[:28],
   'W0_first_binding':True,'role_configuration_ref':config_ref,'prior_configuration_ref':old_config,
   'prior_BASE_ref':original_base_ref,'native_tool_entrypoints_corrected':['manager','worker'],
   'native_tool_authority':'kernel authenticated owned native descendant; address is not identity'}
  report=owner.assignments.append_report(root.ref,value,expected_generation=root.generation,logical_request_key=key+':application',
   actor=owner.binding.authenticated_actor(root.principal))
  prepared=app.continue_manager_from_directive(manager_schedule_id=prior.schedule_id,report_ref=report.ref.to_dict(),supervisor_ref=root.ref.to_dict(),execute=False)
  require(prepared.get('outcome')in{'committed','prepared','replayed'},'one same-session continuation did not prepare')
  from otto.portfolio.manager_journey_service import advance_manager_head
  due=app._read(prepared['schedule_id'])
  require(not(due.host_evidence or{}).get('gateway_attempt'),'first direction continuation must be unattempted')
  # Tool-only config adoption retains the exact selected model values and
  # repins only this newly prepared occurrence's canonical selection provenance.
  from dataclasses import replace
  target=deepcopy(due.target);selection=target.get('execution_selection',{})
  from otto.portfolio.role_context import configured_binding
  configured=configured_binding({'ref':config_ref,'content':configuration},'manager')
  for field in('model','reasoning'):
   provenance=selection.get(field,{})
   require(configured[field]==target['requested_'+field]==getattr(due,'requested_'+field),'tool context cannot alter selected manager model')
   if provenance.get('source')=='selected_configuration':
    require(provenance.get('ref')==old_config,'prior selected configuration provenance changed')
    provenance['ref']=config_ref
  app.due_port.save_due(due.schedule_id,replace(due,target=target).to_dict(),request_id=key+':current-tool-selection',expected_version=due.version)
  due=app._read(due.schedule_id)
  app.runtime.prepare_execution_readiness(due=due) # no provider; whole transaction rolls back on mismatch
  require(service._current_manager_schedule()==prior.schedule_id and advance_manager_head(staged,expected=prior.schedule_id,due=due,settled_anchor=prior.schedule_id),'current manager anchor changed')
  authoring._bootstrap_projection(staged,current,due,base_ref);staged['role_configuration_ref']=config_ref
  staged['W0_first_direction_application']={'report_ref':report.ref.to_dict(),'role_configuration_ref':config_ref,'prior_configuration_ref':old_config}
 state.update(staged);service.server._save_state()
 return{**common,**value,'report_ref':report.ref.to_dict(),'continuation':prepared,'delivery':'prepared-not-started','provider_called':False}
def recover_projection(owner,due_port,state):
 """Recover canonical first-bind publication; never rewind a newer head."""
 supervisor=owner.assignments.get(ResourceRef.from_dict(state['orchestrator_assignment_ref']))
 require(supervisor.principal==owner.owner_actor.actor==migration.OWNER,'own W0 supervisor required')
 rows=owner.assignments.list_observations(supervisor.ref,kind='report');require(len(rows)<=64,'bounded W0 supervisor report inventory required')
 matches=[row for row in rows if isinstance(row.value,dict)and row.value.get('W0_first_binding')is True]
 require(len(matches)<=1,'first manager direction application is ambiguous')
 if not matches:return
 report=matches[0];value=report.value
 require(value['project_ref']['id']==migration.PROJECT and value['manager_generation']==2
  and value['manager_assignment_ref']['id']==migration.MANAGER and value['supervisor_assignment_ref']==supervisor.ref.to_dict()
  and any(e.operation=='work.report.append'and e.actor==owner.owner_actor for e in owner.store.consumer().list_events(subjects=(report.ref,))),
  'first direction application lacks authentic own-supervisor event')
 current=owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']))
 from otto.portfolio.operating_setup import authenticated_adoption_ancestor
 projection={'ref':current.ref.to_dict(),'principal':current.principal,'role':current.role,'generation':current.generation,'payload':current.payload}
 require(current.ref.to_dict()==value['manager_assignment_ref']or authenticated_adoption_ancestor(projection,value['manager_assignment_ref'],owner.store.consumer()),'current manager lacks first-binding adoption history')
 head=(state.get('manager_continuation')or{}).get('schedule_id')or state['schedule_id']
 if head==value['anchor_schedule_id']:
  require(state['assignment_ref']==value['before_manager_ref'],'publication recovery requires exact old manager projection')
  due=due_port.read_due(value['continuation_schedule_id'])
  require(due is not None and due['assignment_ref']==value['manager_assignment_ref']and due['generation']==2
   and due['host_evidence'].get('supervisor_directive_ref')==report.ref.to_dict(),'exact committed first-binding continuation required')
  state.update(assignment_ref=value['manager_assignment_ref'],schedule_id=due['schedule_id'],guide_ref=value['BASE_ref'],mandate_ref=due['target']['mandate_ref'],
   manager_continuation={'schedule_id':due['schedule_id'],'native_session_id':due['target']['native_id'],'outcome':'prepared','requested_continuation':{'settled_schedule_id':value['anchor_schedule_id']}})
 require(state['assignment_ref']==current.ref.to_dict(),'first-binding manager publication is stale')
 base,body,_=resolve_required_instruction_adoption(current.payload.get('resource_adoptions',[]),state['guide_ref'],owner.content)
 require(body['content'].get('supporting_refs',[]).count(value['role_configuration_ref'])==1,'current BASE must retain corrected native tool config exactly once')
 state['role_configuration_ref']=value['role_configuration_ref']
 state['W0_first_direction_application']={'report_ref':report.ref.to_dict(),'role_configuration_ref':value['role_configuration_ref'],'prior_configuration_ref':value['prior_configuration_ref']}
