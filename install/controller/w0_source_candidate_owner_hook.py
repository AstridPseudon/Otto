"""Finite source publication through the existing protected physical-owner input."""
from types import MethodType
from herzchen.contracts import ResourceRef
import hashlib
import w0_source_candidates as source
import w0_completion_policy as completion
import w0_same_manager_migration as migration
OPERATIONS=frozenset({'W0-source-candidates-preview','W0-source-candidates-publish'})
def install(common):
 target=common.host_clients.router._project({'authority':common.scoped_clients.owner.store.authority,'kind':'work.project','id':migration.PROJECT,'revision':None})
 from w0_completion_owner_hook_v2 import protected_receiver
 receiver=protected_receiver(common);previous=receiver._project_authoring;host=common.host_clients.shared_host
 def handle(self,request):
  if request.get('operation')not in OPERATIONS:return previous(request)
  actor=self.authoring_authorizer(request)
  completion.require(actor==target.server.owner.owner_actor and set(request)=={'command','operation','request_key','project_ref','arguments'}
   and request['command']=='project-authoring','finite authenticated same-owner source publication required')
  pin=ResourceRef.from_dict(request['project_ref']);current=target.server.owner.graph.get(pin)
  completion.require(pin==current.ref and pin.id==migration.PROJECT,'exact current original W0 project required')
  completion.require(not host._closing and not host._executions and not host._capacity_holds,'ordinary shared native quiet boundary required; no shutdown needed')
  args=request['arguments'];completion.require(isinstance(args,dict),'finite source publication arguments required')
  if request['operation']=='W0-source-candidates-preview':
   completion.require(not args and request['request_key']==source.KEY+':preview','source preview takes no overrides')
   return {'outcome':'read','immutable_plan':source.preview(target,actor=actor),'provider_called':False}
  completion.require(set(args)=={'immutable_plan'}and request['request_key']==source.KEY+':publish','publish only original immutable preview inputs')
  return {'outcome':'published',**source.publish(target,actor=actor,immutable_plan=args['immutable_plan']),'provider_called':False}
 receiver._project_authoring=MethodType(handle,receiver)
 owner=target.server.owner;identity='report-'+hashlib.sha256((migration.MANAGER+':'+source.KEY+':published').encode()).hexdigest()[:28]
 record=owner.consumer_operations()._owner_reader.get_record(ResourceRef(owner.store.authority,'wrk.report',identity))
 if record is not None:
  body=record.payload.get('value')or{}
  completion.require(record.payload.get('assignment',{}).get('id')==migration.MANAGER and record.payload.get('generation')==2
   and body.get('schema')==source.SCHEMA+'.published'and body.get('input_sha256')==body.get('result',{}).get('input_sha256')
   and any(event.operation=='work.report.append'and event.actor==owner.owner_actor for event in owner.consumer_operations()._owner_reader.list_events(subjects=(record.ref,))),
   'source publication restore requires exact authentic owner receipt')
  source.bind(target,body['result'])
 else:source.install_review_input(target)
 return {'outcome':'installed-composition','operations':sorted(OPERATIONS),'provider_called':False,'same_W0_only':True}
