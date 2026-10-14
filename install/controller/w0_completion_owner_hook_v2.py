"""Prepared W0-only provider-free completion authoring composition hook.

Install only through a later pinned maintained composition. Existing protected
OwnerAuthoringIngress grants/authentication remain the sole input authority.
This does not expose final dispatch or weaken native admission classification.
"""
from types import MethodType,SimpleNamespace
from herzchen.contracts import ResourceRef
import w0_same_manager_migration as migration
import w0_completion_policy as completion

OPERATIONS=frozenset({'W0-completion-preview','W0-completion-adopt'})
def protected_receiver(common):
 from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
 router=common.host_clients.router;ingress=common.owner_authoring
 if not isinstance(ingress,OwnerAuthoringIngress):raise PermissionError('existing authentic owner authoring ingress required')
 receiver=router._project(common.state['project_ref'])
 if receiver is not router.services.get('onboarding'):raise PermissionError('protected owner route must select canonical onboarding receiver')
 authorization=receiver.authoring_authorizer
 if(getattr(authorization,'__self__',None)is not ingress or getattr(authorization,'__func__',None)is not OwnerAuthoringIngress.authorize
  or ingress.actor!=receiver.server.owner.owner_actor or receiver.host is not common.host_clients.shared_host
  or receiver.server.store is not router.store or receiver.server.due_port is not router.due_port):
  raise PermissionError('canonical receiver must retain exact protected physical-owner ingress/Store/host/Due')
 return receiver

def install(common):
 router=common.host_clients.router
 target=router._project({'authority':common.scoped_clients.owner.store.authority,
  'kind':'work.project','id':migration.PROJECT,'revision':None})
 physical=common.host_clients.shared_host
 receiver=protected_receiver(common);original=receiver._project_authoring
 def handle(self,request):
  if request.get('operation')not in OPERATIONS:return original(request)
  actor=self.authoring_authorizer(request)
  if actor!=target.server.owner.owner_actor:raise PermissionError('same physical owner input required')
  if set(request)!={'command','operation','request_key','project_ref','arguments'}:
   raise ValueError('finite exact W0 completion authoring fields required')
  if request['command']!='project-authoring' or not isinstance(request['request_key'],str)or not request['request_key'].strip():
   raise ValueError('canonical completion authoring correlation required')
  pin=ResourceRef.from_dict(request['project_ref'])
  current=target.server.owner.graph.get(pin)
  if pin!=current.ref or pin.id!=migration.PROJECT:raise PermissionError('exact current original W0 project required')
  # Existing nested-capability classification holds these newly defined
  # operations during another native turn. Require the same idle boundary here
  # as well; no new provider execution or service-process shutdown is required.
  if physical._executions or physical._capacity_holds:raise PermissionError('existing shared native custody must settle before completion authoring')
  arguments=request['arguments']
  if not isinstance(arguments,dict):raise ValueError('exact completion arguments required')
  if request['operation']=='W0-completion-preview':
   if arguments:raise ValueError('completion preview takes no override')
   return {'outcome':'read','immutable_plan':completion.plan(target,actor=actor),'provider_called':False}
  if set(arguments)!={'immutable_plan'}:raise ValueError('completion adoption requires original preview inputs only')
  return {'outcome':'adopted',**completion.adopt(target,actor=actor,immutable_plan=arguments['immutable_plan']),'provider_called':False}
 receiver._project_authoring=MethodType(handle,receiver)
 # Restore the ordinary command policy from the same canonical completion
 # receipt after restart; state marker presence is not a bound Python policy.
 rows=target.server.owner.assignments.list_observations(ResourceRef(target.server.owner.store.authority,'wrk.assignment',migration.MANAGER),kind='report',logical_request_keys=(completion.KEY+':completed',))
 if len(rows)>64:raise PermissionError('bounded same W0 completion report inventory required')
 selected=[row for row in rows if isinstance(row.value,dict)and row.value.get('schema')==completion.SCHEMA+'.completed']
 if not selected and target.server.state.get('W0_completion_policy_report_ref'):
  pin=ResourceRef.from_dict(target.server.state['W0_completion_policy_report_ref'])
  record=target.server.owner.consumer_operations()._owner_reader.get_record(pin)
  if record is None or record.ref!=pin or record.payload.get('assignment',{}).get('id')!=migration.MANAGER or record.payload.get('generation')!=2:
   raise PermissionError('retained original W0 local policy receipt missing or foreign')
  body=record.payload.get('value')or{}
  if body.get('schema')!=completion.SCHEMA+'.completed':raise PermissionError('retained completion policy schema differs')
  from otto.portfolio.operating_setup import authenticated_adoption_ancestor
  manager=target.server.owner.assignments.get(ResourceRef.from_dict(target.server.state['assignment_ref']))
  if not authenticated_adoption_ancestor({'ref':manager.ref.to_dict(),'principal':manager.principal,'role':manager.role,
    'generation':manager.generation,'payload':manager.payload},record.payload['assignment'],target.server.owner.consumer_operations()._owner_reader):
   raise PermissionError('completion policy requires same-generation adoption ancestry')
  selected=[SimpleNamespace(ref=record.ref,value=body)]
 if len(selected)>1:raise PermissionError('same W0 completion policy receipt is ambiguous')
 if selected:
  row=selected[0];projection={**row.value['result'],'completion_report_ref':row.ref.to_dict()}
  if row.value.get('input_sha256')!=projection.get('input_sha256')or not any(event.operation=='work.report.append'and event.actor==target.server.owner.owner_actor
    for event in target.server.owner.store.consumer().list_events(subjects=(row.ref,))):
   raise PermissionError('completion policy requires authentic original owner receipt')
  completion.bind(target,projection)
  from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
  target.commands.policy=LocalAssessmentPolicy.from_run_config(target.server.state['assessment_policy'],state=target.server.state)

 return {'outcome':'installed-composition','provider_called':False,'operations':sorted(OPERATIONS),
  'same_W0_only':True,'existing_owner_authoring_authentication_preserved':True,'final_dispatch_available':False}
