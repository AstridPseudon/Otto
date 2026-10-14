"""A verified unattempted supervisor-revision context hold is not readiness."""
import hashlib
from herzchen.contracts import ResourceRef
from herzchen.content.instructions import validate_instruction_content
from otto.portfolio.owner_readers import json_value
HELD_PROJECT='project-2f609a3df3034860aef6e03424b2'
HELD_SCHEDULE='manager-directive-cc0ebf9dfa9d22fd9baad374a9c7'
MESSAGE='selected supervisor differs from current authenticated project supervision'
def identity(ref):return tuple(ref.get(k)for k in ('authority','kind','id'))
def qualify(owner,state,due,prepared,*,view):
 error=prepared.get('error')or{}
 if prepared.get('outcome')!='adoption-required'or prepared.get('provider_called')is not False or error.get('code')!='RoleContextError'or error.get('message')!=MESSAGE:raise PermissionError('fixed view original context refusal: '+str({'view':view,'project_ref':state['project_ref'],'schedule_id':due.get('schedule_id'),'error':error}))
 planned=(due.get('in_flight_request')==due.get('invocation_identity')==due.get('schedule_id'))or(isinstance(due.get('in_flight_request'),str)and due['in_flight_request'].endswith(':launch')and isinstance(due.get('invocation_identity'),str)and due['invocation_identity'].startswith(due['in_flight_request'][:-7]+':'))
 if state['project_ref']['id']!=HELD_PROJECT or due.get('schedule_id')!=HELD_SCHEDULE or due.get('schedule_id')!=state['schedule_id']or due.get('assignment_ref')!=state['assignment_ref']or due.get('generation')!=state['manager_generation']or due.get('recipient')!=state['manager']or due.get('role')!='manager'or due.get('stop_state')!='active'or due.get('completion_state')!='none'or not planned or due.get('delivery_state')!='ready' or due.get('last_completed_request')is not None or due.get('last_result')is not None or due.get('completion_evidence') or (due.get('host_evidence')or{}).get('gateway_attempt')is not None:raise PermissionError('context hold requires exact original unattempted manager occurrence')
 target=due.get('target')or{}
 if identity(target.get('project_ref',{}))!=identity(state['project_ref']):raise PermissionError('context hold project differs')
 current=owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']));root=owner.assignments.get(ResourceRef.from_dict(state['orchestrator_assignment_ref']));project=owner.graph.get(ResourceRef.from_dict(state['project_ref']))
 relation=project.payload.get('metadata',{}).get('otto_orchestrator')or{}
 if current.ref.to_dict()!=state['assignment_ref']or current.generation!=state['manager_generation']or current.principal!=state['manager']or current.role!='manager'or identity(current.scope.to_dict())!=identity(project.ref.to_dict())or root.ref.to_dict()!=state['orchestrator_assignment_ref']or root.principal!=owner.owner_actor.actor or root.generation!=state['root_help_binding']['generation']or root.role!='orchestrator'or relation.get('assignment_ref')!=root.ref.to_dict()or relation.get('generation')!=root.generation:raise PermissionError('context hold current manager/project/root differs')
 configs=[]
 for resource in current.payload.get('resource_adoptions',[]):
  if resource.get('required')is not True:continue
  pin=ResourceRef.from_dict(resource['resource_ref']);read=owner.content.read(pin);body=read.get('content')
  if not isinstance(body,dict)or body.get('schema')!='herzchen.instructions.v1':continue
  if resource.get('content_digest')!=validate_instruction_content(body):raise PermissionError('context hold instruction adoption changed')
  for ref in body.get('supporting_refs',[]):
   read=owner.content.read(ResourceRef.from_dict(ref));content=read.get('content')
   if isinstance(content,dict)and content.get('schema')=='otto.role-configuration.v1':configs.append({'ref':ref,'content':content})
 unique={str(row['ref']):row for row in configs}
 if len(unique)!=1:raise PermissionError('exact original selected role configuration required for context hold')
 config=next(iter(unique.values()));declared=config['content'].get('operational_supervisor')or{}
 if identity(declared.get('assignment_ref',{}))!=identity(root.ref.to_dict())or declared.get('generation')!=root.generation or declared.get('principal')!=root.principal or declared.get('conversation_ref')!=json_value(root.session)or identity(declared.get('project_ref',{}))!=identity(project.ref.to_dict())or declared.get('assignment_ref')==root.ref.to_dict():raise PermissionError('context hold is not a same-root revision-only mismatch')
 key='otto-expanded-existing-five-setup-20261012-v1:phase:direction-synchronize';ref=ResourceRef(root.ref.authority,'wrk.report','report-'+hashlib.sha256((root.ref.id+':'+key).encode()).hexdigest()[:28]);seen=owner.store.consumer().get_identity_bounded(ref,max_record_bytes=65536);report=seen.get('record');value=json_value(report.payload.get('value',{}))if report else{}
 if seen.get('state')!='available'or report is None or report.payload.get('assignment',{}).get('id')!=root.ref.id or report.payload.get('generation')!=root.generation or value.get('schema')!='otto.existing-five-owner-setup-phase.v1'or value.get('phase')!='direction-synchronize'or(value.get('result')or{}).get('new_root')!=root.ref.to_dict()or(value.get('result')or{}).get('provider_called')is not False:raise PermissionError('authenticated original direction transition required')
 return {'schema':'otto.unattempted-context-held-view.v1','view':view,'project_ref':project.ref.to_dict(),'schedule_id':due['schedule_id'],'assignment_ref':current.ref.to_dict(),'generation':current.generation,'current_supervisor_ref':root.ref.to_dict(),'declared_supervisor':declared,'configuration_ref':config['ref'],'direction_phase_ref':report.ref.to_dict(),'current_context_qualified':False,'execution_held':True,'reason':MESSAGE,'provider_called':False,'retry':False,'canonical_effect_recorded':False,'next_action':'Preserve this original occurrence; owner adopts exact current supporting supervisor context through maintained same-assignment recovery. Other qualified views remain available.'}
def held_start(hold):return {'outcome':'held','execution_held':True,'reason':hold['reason'],'schedule_id':hold['schedule_id'],'assignment_ref':hold['assignment_ref'],'generation':hold['generation'],'effects_started':False,'provider_called':False,'retry':False,'next_action':hold['next_action']}


def qualify_settled_idle(owner,state,due,terminal_projection):
 # One existing unfinished Claude project with a finalized manager turn. This
 # is durable capture read qualification; it is never project/task acceptance.
 if state['project_ref']['id']!='project-65e3f08dd7a49f8ceca748ee6857':return None
 terminal=terminal_projection(due)
 if terminal is None:return None
 current=owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']));root=owner.assignments.get(ResourceRef.from_dict(state['orchestrator_assignment_ref']));project=owner.graph.get(ResourceRef.from_dict(state['project_ref']));target=due.get('target')or{}
 relation=project.payload.get('metadata',{}).get('otto_orchestrator')or{}
 from otto.portfolio.operating_setup import authenticated_adoption_ancestor
 digest=(due.get('completion_evidence')or{}).get('result_digest')
 if project.ref.to_dict()!=state['project_ref']or current.ref.to_dict()!=state['assignment_ref']or current.role!='manager'or current.principal!=state['manager']or current.generation!=state['manager_generation']or identity(current.scope.to_dict())!=identity(project.ref.to_dict())or due.get('schedule_id')!=state['schedule_id']or due.get('role')!='manager'or due.get('recipient')!=current.principal or due.get('generation')!=current.generation or target.get('assignment_ref')!=due.get('assignment_ref')or identity(target.get('project_ref',{}))!=identity(project.ref.to_dict())or root.ref.to_dict()!=state['orchestrator_assignment_ref']or relation.get('assignment_ref')!=root.ref.to_dict()or relation.get('generation')!=root.generation or root.principal!=owner.owner_actor.actor or root.role!='orchestrator'or not isinstance(digest,str)or len(digest)!=64 or any(c not in '0123456789abcdef'for c in digest)or not authenticated_adoption_ancestor({'ref':current.ref.to_dict(),'principal':current.principal,'role':current.role,'generation':current.generation,'payload':current.payload},due['assignment_ref'],owner.graph.reader):raise PermissionError('completed idle manager capture/current supervisor differs')
 from otto.portfolio.native5_shared_compose import _supervision_only_project_chain
 chain=_supervision_only_project_chain(owner,root,target['project_ref'],project.ref.to_dict())if target['project_ref']!=project.ref.to_dict()else None
 return {'settled_idle_read_qualified':True,'current_authority_resources_qualified':True,'current_context_qualified':False,'execution_contract_evaluated':False,'historical_occurrence':terminal,'canonical_project_ref':project.ref.to_dict(),'supervision_only_refresh':chain,'project_completion_claimed':False,'task_acceptance_claimed':False,'qualification':'original completed capture; unfinished project and every judgment remain retained; fresh execution still requires current readiness','provider_called':False,'retry':False}
