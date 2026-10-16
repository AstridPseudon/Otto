"""Issued external-chat lanes over this one owner; no second Store or wake claim."""
from pathlib import Path
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio import client_lanes as lanes
from otto.portfolio.orchestrator_client import OrchestratorAdmissions,ScopedOrchestratorClient,OrchestratorLanePump
from otto.portfolio.owner_readers import json_value
from otto.portfolio.direction_context import read_direction_context

class ScopedViewClients:
 def __init__(self,*,owner,host,views,controllers,private,main_state,native5_state_map=None,installed_manifest=None):
  self.owner,self.host,self.views,self.controllers=owner,host,views,controllers
  self.private=Path(private);self.main_state=main_state
  self.admissions=OrchestratorAdmissions(owner,main_assignment_ref=main_state['orchestrator_assignment_ref'],generation=main_state['root_help_binding']['generation'])
  clients={}
  original_ids=sorted(views[name].server.state['project_ref']['id']for name in ('onboarding','vision','retention','claude'))
  if native5_state_map is None:
   # Preserve the original four-project issuance path when no Native5 packet
   # exists. After sync, the new lane gets a new immutable key and scope.
   from otto.portfolio.root_direction_client import install_owner_root_client
   from otto.portfolio.supervisor_direction_client import scoped_supervisor_handler
   root_project_handler=scoped_supervisor_handler(services=list(views.values()),fallback=self.handler)
   root_locator,root_client=install_owner_root_client(service=views['onboarding'],project_handler=root_project_handler,**{'directory': str(self.private/'clients'/('owner-root-native5-direction-recovery-'+main_state['orchestrator_assignment_ref']['revision'])), 'conversation_ref': main_state['root_help_binding']['conversation_ref'], 'request_key': 'owner-root-native5-direction-recovery-v1:'+main_state['orchestrator_assignment_ref']['revision'], 'project_ids': original_ids})
   clients[Path(root_locator['lane'])]=root_client
  installed_ids={service.server.state['project_ref']['id'] for service in views.values()}
  services_by_id={service.server.state['project_ref']['id']:service for service in views.values()}
  for path in (self.private/'clients').glob('*/binding.json'):
   locator=lanes.read_private_json(path);binding=locator['binding']
   scope=set(binding['project_ids'])
   if not scope.issubset(installed_ids):raise PermissionError('issued lane includes an uninstalled project view')
   selected={s.server.state['project_ref']['id']:s for s in views.values()}
   from otto.portfolio.supervisor_direction_client import scoped_supervisor_handler
   handler=scoped_supervisor_handler(services=[selected[ident] for ident in binding['project_ids']],fallback=self.handler)
   handlers={op:handler for op in binding['operations']}
   clients[Path(locator['lane'])]=ScopedOrchestratorClient(owner=owner,binding=binding,handlers=handlers)
  from otto.portfolio.retained_root_lane import load_retained_root_lane
  from otto.portfolio.supervisor_direction_client import scoped_supervisor_handler
  original_handler=scoped_supervisor_handler(services=[services_by_id[ident] for ident in original_ids],fallback=self.handler)
  load_retained_root_lane(clients=clients,controller=Path(controllers['onboarding']),owner=owner,main_state=main_state,project_ids=original_ids,handler=original_handler,retain_stale_policy=True)
  if native5_state_map is not None:
   from otto.portfolio.native5_shared_compose import install_exact_nine_root_client
   from otto.portfolio.orchestrator_client import ROOT_DIRECTION_OPERATIONS,ROOT_PROJECT_OPERATIONS
   root=owner.assignments.get(main_state['orchestrator_assignment_ref'])
   exact_ids=set(native5_state_map.get('project_ids',[]))
   required_operations=set(ROOT_PROJECT_OPERATIONS)|set(ROOT_DIRECTION_OPERATIONS)
   current=[client for client in clients.values()
    if getattr(client,'binding',{}).get('assignment_ref')==root.ref.to_dict()
    and getattr(client,'binding',{}).get('generation')==root.generation
    and getattr(client,'binding',{}).get('conversation_ref')==main_state['root_help_binding']['conversation_ref']
    and set(getattr(client,'binding',{}).get('project_ids',[]))==exact_ids]
   if len(current)>1:raise PermissionError('multiple current exact-nine root lanes are ambiguous')
   if current:
    binding=current[0].binding
    if not required_operations.issubset(set(binding.get('operations',[]))) or not binding.get('policy_ref'):
     raise PermissionError('retained exact-nine root lane lacks current finite operation policy')
   else:
    services={ident:services_by_id[ident] for ident in exact_ids if ident in services_by_id}
    if set(services)!=exact_ids:
     raise PermissionError('all nine current root services must exist before issuing the Native5 lane')
    source_commit=(installed_manifest or {}).get('source_commit')
    if not isinstance(source_commit,str) or not source_commit:
     raise PermissionError('current installed source commit is required for the Native5 immutable request key')
    request_key='owner-root-native5:'+source_commit[:12]+':'+str(root.ref.revision)
    staged=SimpleNamespace(pump=SimpleNamespace(clients=clients),handler=self.handler)
    install_exact_nine_root_client(owner,services_by_project=services,scoped_clients=staged,
     state_map=native5_state_map,main_project_id=main_state['project_ref']['id'],
     directory=str(self.private/'clients'),conversation_ref=main_state['root_help_binding']['conversation_ref'],request_key=request_key)
    clients=staged.pump.clients
  self.pump=OrchestratorLanePump(owner_inbox=self.private/'orchestrator-requests',admissions=self.admissions,clients=clients,owner_call=host._owner_request)
 def _service(self,project_id):
  selected=[s for s in self.views.values()if s.server.state['project_ref']['id']==project_id]
  if len(selected)!=1:raise PermissionError('project has no unique installed fixed view')
  return selected[0]
 def _project(self,project_id):return self.owner.graph.current(ResourceRef(self.owner.binding.authority,'work.project',project_id))
 def _owned(self,root):
  rows=[]
  for service in self.views.values():
   project=self._project(service.server.state['project_ref']['id']);relation=project.payload.get('metadata',{}).get('otto_orchestrator',{})
   if relation.get('assignment_ref')==root.ref.to_dict()and relation.get('generation')==root.generation:
    rows.append({'project_ref':project.ref.to_dict(),'title':project.title,'lifecycle':project.lifecycle.value,'supervisor_ref':root.ref.to_dict(),'manager_ref':service.server.state['assignment_ref']})
  return rows
 def handler(self,request,root):
  operation=request['operation'];payload=request.get('request')or{};key=request['request_key']
  common={'principal':root.principal,'assignment_ref':root.ref.to_dict(),'generation':root.generation,'portfolio_ref':root.scope.to_dict(),'canonical_conversation':json_value(root.session),'identity_origin':'owner-issued private client lane','native_identity_claimed':False,'notification_sent':False}
  if operation in {'status','whoami','portfolio'}:
   if payload:raise ValueError('identity/status/portfolio read takes no payload')
   return {**common,'outcome':'read','state':'assigned','supervision_adopted':bool(self._owned(root)),'projects':self._owned(root),'read_only':True}
  service=self._service(request['project_id']);state=service.server.state;project=self._project(request['project_id']);project_ref=project.ref.to_dict()
  if operation=='effective-context':
   if payload:raise ValueError('effective context takes no payload')
   # ScopedOrchestratorClient has revalidated the issued principal, allowed
   # project and exact current canonical supervision before this handler.
   # This server projection uses its owner read capability, never a client
   # impersonation or new authoring grant. Returned identity remains root.
   actor=self.owner.owner_actor
   directions=self.owner.direction_surface()
   resources=json_value(root.payload.get('resource_adoptions',[]))
   if not resources:
    return {**common,'outcome':'read','project_ref':project_ref,'resource_adoptions':[],'direction_context':[],'instruction_adoption':'missing','current_project_direction_binding':directions.read(project_ref,actor=actor),'next_action':'Accountable owner must adopt the scoped orchestrator instruction resources before claiming an effective assignment direction. Existing identity/supervision/read/help scopes remain independent.','read_only':True}
   return {**common,'outcome':'read','project_ref':project_ref,'resource_adoptions':resources,'direction_context':read_direction_context(directions,actor=actor,assignment_ref=root.ref,generation=root.generation,project_ref=project_ref),'instruction_adoption':'read-current','read_only':True}
  if operation=='read-manager':
   if payload:raise ValueError('manager read takes no payload')
   from role_allowance_snapshot import read as read_role_allowances
   from otto.portfolio.execution_operations import compact_operation_status
   schedule=service._current_manager_schedule();raw=service.server.due_port.read_due(schedule)
   continuation=state.get('manager_continuation')or{}
   disposition=continuation.get('operational_disposition')or{}
   if continuation.get('schedule_id')==schedule and continuation.get('outcome')=='partial'and isinstance(raw,dict)and not(raw.get('host_evidence')or{}).get('gateway_attempt')and disposition.get('error'):
    raw={**raw,'pre_effect_runtime_failure':disposition}
   target=(raw or{}).get('target')or{}
   provenance={k:target[k]for k in('project_ref','task_ref','assignment_ref','mandate_ref')if k in target}
   required={'task_refs':[state['task_refs'][a]for a in state.get('task_refs',{})],'task_aliases':list(state.get('task_refs',{}))}
   return {**common,'outcome':'read','project_ref':project_ref,'manager':{'principal':state['manager'],'assignment_ref':state['assignment_ref'],'generation':state['manager_generation'],'schedule_id':schedule,'occurrence':compact_operation_status(raw,required_scope=required,instruction_provenance=provenance)},'allowances':read_role_allowances(service),'task_acceptance':service._task_acceptance_projection(),'workers':{alias:{k:w.get(k)for k in('schedule_id','assignment_ref','generation','principal','request_key')}for alias,w in state.get('workers',{}).items()},'read_only':True}
  portfolio=service.server.portfolio;loop=portfolio._issue_loop()
  if operation=='read-help':
   if set(payload)-{'delivery_id'}:raise PermissionError('help read cannot select actor/project')
   result=loop.recover_delivery(project_ref=project_ref,delivery_id=payload['delivery_id'])if payload.get('delivery_id')else portfolio.read_issues(project_ref=project_ref)
   return {**common,**result,'read_only':True}
  if operation=='respond-help':
   fields={'issue_id','authority_source','response','proposed_solution','next_action'}
   if set(payload)!=fields:raise ValueError('respond-help needs exact issue/authority/response/solution/next_action fields')
   result=portfolio.respond_to_issue(project_ref=project_ref,actor=root.principal,request_id=key,**payload)
   current=service._current_manager_schedule()
   retained=self.host.submit({'command':'manager-help-result','principal':state['manager'],'generation':state['manager_generation'],'schedule_id':current,'report_ref':result['report_ref']})
   return {**common,**result,'continuation':retained}
  if operation=='delivery-ack':
   if set(payload)!={'delivery_id'}:raise ValueError('acknowledgement takes exact delivery_id only')
   issues=portfolio.read_issues(project_ref=project_ref)['issues'];intents=[v for i in issues for v in i.get('deliveries',[])if v.get('delivery_id')==payload['delivery_id']and v.get('state')=='intent']
   if len(intents)!=1:raise PermissionError('acknowledgement needs one retained delivery intent')
   intent=intents[0]
   if intent['recipient_assignment_ref']!=root.ref.to_dict()or intent['recipient_generation']!=root.generation:raise PermissionError('delivery belongs to another recipient')
   value={'schema':'otto.orchestrator-client-receipt.v1','project_ref':project_ref,'delivery_id':payload['delivery_id'],'report_ref':intent['message']['report_ref'],'recipient_assignment_ref':root.ref.to_dict(),'recipient_generation':root.generation,'recipient_conversation':json_value(root.session),'transport':'authenticated-recipient-inspection','notification_sent':False,'disposition':'recipient acknowledged exact retained report; no unattended wake claimed'}
   report=self.owner.assignments.append_report(root.ref,value,expected_generation=root.generation,logical_request_key=key,actor=self.owner.binding.authenticated_actor(root.principal))
   return {**common,'outcome':'acknowledged','report_ref':report.ref.to_dict(),'delivery_id':payload['delivery_id']}
  if operation=='manager-start':
   if set(payload)!={'schedule_id'}:raise ValueError('manager start needs one existing current schedule_id')
   current=service._current_manager_schedule()
   if payload['schedule_id']!=current:raise PermissionError('client may only start the existing current manager occurrence')
   app=service._execution(principal=state['manager'],model=state['requested_model'],reasoning=state['requested_reasoning'],evidence_id='own-client-manager-'+current)
   due=app._read(current)
   if due.assignment_ref!=state['assignment_ref']or due.generation!=state['manager_generation']or due.role!='manager':raise PermissionError('current occurrence manager binding differs')
   from otto.portfolio.owner_completion import after_owner
   return after_owner(app.recover(schedule_id=current,execute=True),lambda result:service._finalize_manager_completion(result,app=app))
  raise PermissionError('operation has no qualified installed handler')
 def poll(self):return self.pump.poll(limit=4)
