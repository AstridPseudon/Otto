"""Exact source-proved W0 preinitializer accounting disposition.

No pool creation/reset. Preserve the original reservation's uncertain history,
failed UNKNOWN result and old Claude initializer; release only a canonical
reservation proved to have reached the guard before any host construction.
"""
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.portfolio.worker_custody import retained_preinitialization_release
from w0_finite_role_allowance import digest
import w0_same_manager_migration as migration

def release(application,*,owner,state,disposition):
 due=application._read(disposition['scope']['schedule_id'])
 body=retained_preinitialization_release(application,due);scope=body['scope']
 migration.require(scope.get('host_evidence_guard_before_typed_request')is True
  and scope.get('initializer_occurred')is False and scope.get('native_effect_occurred')is False
  and due.role=='manager'and due.project_ref==migration.PROJECT and due.generation==2
  and due.assignment_ref['id']==migration.MANAGER and due.allowance_ref==state['new_pool_refs']['manager'],
  'only exact same W0 first-line host-evidence guard permits accounting disposition')
 pool=ResourceRef.from_dict(due.allowance_ref)
 ref=ResourceRef(pool.authority,'reservation','W0-finite-turn-'+digest([due.schedule_id,pool.to_dict()])[:28])
 migration.require(application.actor==owner.owner_actor.actor and application.assignments is owner.assignments.command_port,'same authentic owner accounting ports required')
 limits=LimitService(owner.store)
 original=limits.get_reservation(ref)
 migration.require(original is not None and original.pool_ref==pool and original.declared_units==1
  and original.status.value in('uncertain','held','released')and original.actual_units==original.charged_units==0,
  'original exact bounded manager reservation/source-zero-effect evidence differs')
 key='W0-host-evidence-preinitializer-reservation:'+digest([scope['due_sha256'],scope['result_sha256'],disposition['disposition_ref'],ref.to_dict()])
 if original.status.value!='released':
  original=limits.release(original,actual_units=0,logical_request_key=key,actor=application.binding.authenticated_actor(application.actor))
 return {'reservation_ref':original.ref.to_dict(),'status':original.status.value,'actual_units':original.actual_units,
  'original_uncertain_history_preserved':True,'disposition_ref':disposition['disposition_ref'],'provider_called':False}
