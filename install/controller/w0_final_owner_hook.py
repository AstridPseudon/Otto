"""Prepared final-only protected owner transport; installed by composition only.

Uses the existing owner grant, same W0 adviser preparation receipt, finite
AdvisorExecution pool and shared host admission. No scheduler or provider
trial, caller-controlled model, alternate Store, or manager replacement.
"""
from types import MethodType
from herzchen.contracts import ResourceRef
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.owner_completion import after_owner
import w0_same_manager_migration as migration
import w0_completion_owner_hook_v2 as policy_hook
import w0_final_review as final

OPERATIONS=frozenset({'W0-final-prepare','W0-final-start','W0-final-read'})
def application(service,principal):
 owner=service.server.owner
 wrapped=service._execution(principal=principal,model='gpt-6-astra',reasoning='high',evidence_id=final.KEY+':same-owner-final')
 return owner.execution_application(due_port=service.server.due_port,adapter=wrapped.runtime.adapter,
  manager_actor=owner.owner_actor.actor,issue_delivery=service.server.help_delivery,
  native_result_verifier=wrapped.runtime.native_result_verifier)

def prepared(service):
 owner=service.server.owner
 rows=owner.assignments.list_observations(ResourceRef(owner.store.authority,'wrk.assignment',migration.MANAGER),kind='report',logical_request_keys=(final.KEY+':prepared',))
 final.require(len(rows)<=64,'bounded same W0 report inventory required')
 selected=[r for r in rows if isinstance(r.value,dict)and r.value.get('schema')==final.SCHEMA+'.prepared']
 final.require(len(selected)==1,'one original final preparation report required')
 row=selected[0]
 final.require(any(event.operation=='work.report.append'and event.actor==owner.owner_actor
  for event in owner.store.consumer().list_events(subjects=(row.ref,))), 'final preparation must be authentic same-owner source')
 value=row.value['result'];due=service.server.due_port.read_due(value['schedule_id'])
 final.require(due is not None and due['assignment_ref']==value['assignment_ref']and due['generation']==value['generation']
  and due['project_ref']==migration.PROJECT and due['allowance_ref']==value['pool_ref']
  and(due['requested_model'],due['requested_reasoning'],due['profile'])==('gpt-6-astra','high','read-only'),
  'exact prepared one-final occurrence/pool/model differs')
 return row,value,due

def install(common):
 policy=policy_hook.install(common)
 router=common.host_clients.router;host=common.host_clients.shared_host
 target=router._project({'authority':common.scoped_clients.owner.store.authority,'kind':'work.project','id':migration.PROJECT,'revision':None})
 receiver=policy_hook.protected_receiver(common);previous=receiver._project_authoring
 def handle(self,request):
  if request.get('operation')not in OPERATIONS:return previous(request)
  actor=self.authoring_authorizer(request)
  final.require(actor==target.server.owner.owner_actor,'same physical owner input required')
  final.require(set(request)=={'command','operation','request_key','project_ref','arguments'}
   and request['command']=='project-authoring','finite exact W0 final owner fields required')
  pin=ResourceRef.from_dict(request['project_ref']);current=target.server.owner.graph.get(pin)
  final.require(pin==current.ref and pin.id==migration.PROJECT,'exact current original W0 project required')
  operation=request['operation'];arguments=request['arguments']
  final.require(isinstance(arguments,dict),'finite original final arguments required')
  if operation=='W0-final-read':
   final.require(not arguments and request['request_key']==final.KEY+':read','finite same final read required')
   row,value,due=prepared(target)
   return {'outcome':'read','prepared_report_ref':row.ref.to_dict(),'prepared':value,
    'due':{key:due.get(key)for key in('schedule_id','version','assignment_ref','generation','stop_state','completion_state','delivery_state','allowance_ref','last_completed_request')},
    'provider_called':False}
  final.require(not host._closing and not host._executions and not host._capacity_holds,
   'ordinary shared native quiet boundary required; never shut down or bypass admitted work')
  if operation=='W0-final-prepare':
   final.require(set(arguments)=={'candidate_refs'}and request['request_key']==final.KEY+':prepare','original finite final preparation input required')
   value=final.prepare(target,actor=actor,candidate_refs=arguments['candidate_refs'],execution_factory=lambda principal:application(target,principal))
   row,_,_=prepared(target)
   return {'outcome':'prepared',**value,'prepared_report_ref':row.ref.to_dict(),'provider_called':False}
  final.require(set(arguments)=={'prepared_report_ref'}and request['request_key']==final.KEY+':start','one original final start required')
  row,value,due=prepared(target)
  final.require(row.ref.to_dict()==arguments['prepared_report_ref'],'final start must consume exact issued preparation receipt')
  final.require(ExecutionHost.current_bounded()is host,'final starts only in the actual serialized shared owner')
  integration=final.compose(target,value);app=integration.execution
  raw=integration._deliver({'schedule_id':value['schedule_id'],'request_id':due['in_flight_request']or due['last_completed_request']})
  def completed(result):
   def settled(projection):
    return {'outcome':projection.get('outcome'),'schedule_id':value['schedule_id'],'prepared_report_ref':row.ref.to_dict(),
     'runtime_result':result,'settlement':projection,'source_reviews_already_used':2,'remaining_final_cap':1,'same_Luna_manager_acceptance_required':True}
   return after_owner(app.recover(schedule_id=value['schedule_id'],execute=False),settled)
  return after_owner(raw,completed)
 receiver._project_authoring=MethodType(handle,receiver)
 # Existing immutable prepared final Due is reconciled when this composition
 # is reconstructed, so incomplete captures retain capacity through restart.
 rows=target.server.owner.assignments.list_observations(ResourceRef(target.server.owner.store.authority,'wrk.assignment',migration.MANAGER),kind='report',logical_request_keys=(final.KEY+':prepared',))
 if any(isinstance(r.value,dict)and r.value.get('schema')==final.SCHEMA+'.prepared'for r in rows):
  _,value,_=prepared(target);app=final.compose(target,value).execution
  host.restore_execution(app,app._read(value['schedule_id']))
 return {**policy,'final_operations':sorted(OPERATIONS),'provider_called':False,'one_existing_final_pool_only':True}
