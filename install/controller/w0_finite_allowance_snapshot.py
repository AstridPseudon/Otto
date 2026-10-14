"""Finite current W0 LimitService/read snapshot; no opener, allocator or provider."""
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.portfolio.owner_readers import json_value
PROJECT='project-68aca4e5bce229bddab0b89a6b52'
MANAGER='assignment-1c95154ca88cd31c0c00fbfec5da'
ORIGINAL='role-2129ac8a3003148081cb18db51fe'
OWNER='otto-operating-setup-owner'

def require(value,message):
 if not value:raise PermissionError(message)
def snapshot(owner,*,due_port,activation_receipt):
 actor=owner.owner_actor
 require(actor.actor==OWNER,'authentic same physical service owner required')
 project=owner.graph.get(ResourceRef(owner.store.authority,'work.project',PROJECT))
 require(activation_receipt.get('project_ref',{}).get('id')==PROJECT
  and activation_receipt.get('steps',{}).get('manager',{}).get('assignment_ref',{}).get('id')==MANAGER,
  'original same-project activation receipt required')
 assignment=owner.assignments.get(ResourceRef(owner.store.authority,'wrk.assignment',MANAGER))
 original=due_port.read_due(ORIGINAL)
 require(original is not None and original['project_ref']==PROJECT and original['assignment_ref']['id']==MANAGER,
  'exact original manager occurrence required')
 # Project-scoped finite identity projection finds ONLY selected W0 schedule
 # IDs. Native bodies/worker text are never enumerated or read for accounting.
 reader=owner.store.consumer()
 refs=reader.find_identity_refs(kind='otto.due-record',payload_matches={('project_ref',):PROJECT})
 require(len(refs)<=64,'W0 Due header inventory exceeds finite bound')
 fields={key:(key,)for key in('schedule_id','project_ref','allowance_ref','generation','assignment_ref','stop_state','completion_state')}
 rows=reader.project_identity_fields_for_refs(list(refs),fields=fields,max_refs=64,max_projection_bytes=65536)
 require(len(rows)==len(refs)and all(row['state']=='available'for row in rows),'current W0 Due headers unavailable')
 dues=[row['fields']for row in rows]
 require(all(row['project_ref']==PROJECT for row in dues),'W0 header projection scope differs')
 pools=set()
 for item in activation_receipt['steps'].get('allowances',[]):
  pin=ResourceRef.from_dict(item['pool_ref'])
  require(pin.authority==actor.authority and pin.kind=='limit'and pin.id.startswith(PROJECT+'-'),
   'original activation allowance scope differs')
  pools.add(pin.id)
 for row in dues:
  if row['allowance_ref']is not None:
   pin=ResourceRef.from_dict(row['allowance_ref'])
   require(pin.authority==actor.authority and pin.kind=='limit'and pin.id.startswith(PROJECT+'-'),
    'W0 retained allowance is foreign; no allocation may proceed')
   pools.add(pin.id)
 require(len(pools)<=16,'W0 allowance inventory exceeds finite bound')
 limits=LimitService(owner.store);observed=[]
 for identity in sorted(pools):
  pool=limits.get_pool(ResourceRef(actor.authority,'limit',identity))
  require(pool is not None,'retained original allowance pool is missing')
  observed.append({key:json_value(getattr(pool,key))for key in('ref','capacity_units','cumulative_allowance_units',
   'version','current_revision','held_units','cumulative_used_units','available_capacity_units','remaining_allowance_units')})
 tasks=project.payload.get('tasks')or[]
 require(len(tasks)<=16,'W0 task inventory exceeds original finite bound')
 return {'schema':'otto.W0-authenticated-finite-allowance-snapshot.v1','project_ref':project.ref.to_dict(),
  'manager_ref':assignment.ref.to_dict(),'manager_generation':assignment.generation,
  'current_manager_owner':assignment.payload.get('manager')or assignment.principal,
  'original_schedule_id':ORIGINAL,'original_allowance_ref':original['allowance_ref'],
  'original_effect_outcome':((original.get('host_evidence')or{}).get('gateway_attempt',{}).get('result')or{}).get('outcome'),
  'original_initializer_usage':'unknown','original_initializer_payment':'unknown',
  'absence_is_not_zero_spend':True,'project_declared_budget':project.payload.get('budget'),
  'pool_snapshots':observed,'due_allowance_headers':dues,'task_refs':tasks,
  'future_authorized_caps':{'manager':6,'normal_worker':5,'xhard_worker':3,'remaining_astra_final_calls':1},
  'prior_source_astra_reviews_used_under_human_cap':2,
  'future_pools_are_new_allocations_not_balance_resets':True,'provider_called':False,'records_modified':False}
