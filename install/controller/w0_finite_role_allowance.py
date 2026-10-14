"""W0-only binding of declared new turn pools to existing kernel accounting.

Uses the same reserve/read/settle/uncertain/release operations as maintained
AdvisorExecution. It never resets capacity or treats old UNKNOWN cost as zero.
"""
from collections.abc import Mapping
import hashlib
from herzchen.contracts import ResourceRef,canonical_json
from herzchen.kernel.limits import LimitService
from otto.portfolio.owner_completion import after_owner
import w0_same_manager_migration as migration

def require(value,message):
 if not value:raise PermissionError(message)
def digest(value):return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def bind(application,owner,state):
 require(application.actor==owner.owner_actor.actor==migration.OWNER
  and state['project_ref']['id']==migration.PROJECT and state['manager_generation']==2,
  'finite role accounting requires authentic current W0 receiving owner/generation')
 limits=LimitService(owner.store);runtime=application.runtime;invoke=runtime.invoke_role
 def selected(due):
  require(due.target['project_ref']['id']==migration.PROJECT and due.lifecycle_owner==migration.OWNER
   and due.role in('manager','worker')and due.allowance_ref in state['new_pool_refs'].values(),
   'current W0 Due lacks its exact adopted finite pool')
  if due.role=='manager':expected='manager';model,reasoning='gpt-6-luna','medium'
  elif due.requested_model=='gpt-6-luna'and due.requested_reasoning=='medium':expected='worker-normal';model,reasoning='gpt-6-luna','medium'
  elif due.requested_model=='gpt-6.1-sol'and due.requested_reasoning=='high':expected='worker-xhard';model,reasoning='gpt-6.1-sol','high'
  else:raise PermissionError('W0 worker model/effort has no human-authorized route')
  require(due.allowance_ref==state['new_pool_refs'][expected]and (due.requested_model,due.requested_reasoning)==(model,reasoning),
   'W0 role/model/finite allowance differs')
  return ResourceRef.from_dict(due.allowance_ref)
 def settle(reservation,schedule,key):
  reservation=limits.get_reservation(ResourceRef(reservation.ref.authority,reservation.ref.kind,reservation.ref.id))
  require(reservation is not None,'original W0 role reservation missing')
  due=application._read(schedule);attempt=(due.host_evidence or{}).get('gateway_attempt')
  result=attempt.get('result')if isinstance(attempt,Mapping)else None;status=reservation.status.value
  if isinstance(result,Mapping)and result.get('outcome')=='succeeded':
   if status!='consumed':limits.settle(reservation,1,logical_request_key=key+':settle',actor=owner.owner_actor)
  elif attempt is not None:
   if status!='uncertain':limits.mark_uncertain(reservation,logical_request_key=key+':uncertain',actor=owner.owner_actor)
  elif status!='released':limits.release(reservation,logical_request_key=key+':release',actor=owner.owner_actor)
 def bounded_invoke(*,role,mode,**kwargs):
  schedule=kwargs['schedule_id'];due=application._read(schedule);pool=selected(due)
  require(due.role==role and due.assignment_ref==kwargs['assignment_ref']and due.generation==kwargs['expected_generation'],
   'finite role invocation differs from canonical current Due')
  key='W0-finite-role:'+digest([schedule,due.assignment_ref,due.generation,pool.to_dict()])
  reservation=limits.reserve(pool,'W0-finite-turn-'+digest([schedule,pool.to_dict()])[:28],1,
   logical_request_key=key+':reserve',actor=owner.owner_actor)
  try:result=invoke(role=role,mode=mode,**kwargs)
  except BaseException:
   settle(reservation,schedule,key);raise
  def completed(value):
   settle(reservation,schedule,key);return value
  def failed(error):
   settle(reservation,schedule,key);raise error
  return after_owner(result,completed,failed)
 runtime.invoke_role=bounded_invoke
 return application
