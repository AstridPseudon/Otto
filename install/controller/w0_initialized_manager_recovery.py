from copy import deepcopy
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService,LimitPool,ReservationRecord
from otto.portfolio.worker_custody import inspect_initialized_worker,release_initialized_worker,retained_capacity_release
from otto.portfolio.operating_setup import read_setup,setup_reference
from otto.portfolio.manager_journey_service import manager_head,advance_manager_head
from w0_finite_role_allowance import digest as accounting_digest
import w0_same_manager_migration as migration
SCHEMA='otto.W0-initialized-manager-render-recovery.v1'
OLD='role-9d3d59aaf0a68ed6ce2f1123104e'
KEY='W0-original-9d-initialized-delivery-recovery-20261013-v1'
FRESH=KEY+':one-same-session-delivery'
def pool_snapshot(pool):
 migration.require(isinstance(pool,LimitPool),'public exact LimitPool snapshot required')
 return {'ref':pool.ref.to_dict(),'capacity_units':pool.capacity_units,'cumulative_allowance_units':pool.cumulative_allowance_units,
  'version':pool.version,'current_revision':pool.current_revision,'held_units':pool.held_units,
  'cumulative_used_units':pool.cumulative_used_units,'available_capacity_units':pool.available_capacity_units,
  'remaining_allowance_units':pool.remaining_allowance_units}

def reservation_snapshot(reservation):
 migration.require(isinstance(reservation,ReservationRecord),'public exact ReservationRecord snapshot required')
 return {'ref':reservation.ref.to_dict(),'pool_ref':reservation.pool_ref.to_dict(),'declared_units':reservation.declared_units,
  'status':reservation.status.value,'actual_units':reservation.actual_units,'charged_units':reservation.charged_units,'version':reservation.version}

def completed(owner):
 rows=owner.assignments.list_observations(ResourceRef(owner.store.authority,'wrk.assignment',migration.MANAGER),kind='report')
 migration.require(len(rows)<=64,'bounded same W0 report inventory required')
 matches=[r for r in rows if isinstance(r.value,dict)and r.value.get('schema')==SCHEMA+'.completed']
 migration.require(len(matches)<=1,'exact W0 host-evidence recovery report is ambiguous')
 if not matches:return None
 report=matches[0]
 migration.require(any(e.operation=='work.report.append'and e.actor==owner.owner_actor
  for e in owner.store.consumer().list_events(subjects=(report.ref,))),'recovery requires authenticated original owner event')
 return {'report_ref':report.ref.to_dict(),**report.value}

def plan(owner,app,state,*,original_result,source_plan_sha256):
 due=app._read(OLD);scope=inspect_initialized_worker(app,schedule_id=OLD)
 migration.require(scope.get('manager_initialized_render_fault')is True and due.generation==2
  and due.assignment_ref['id']==migration.MANAGER and due.project_ref==migration.PROJECT
  and due.allowance_ref==state['new_pool_refs']['manager'],'exact original W0 host-evidence failure required')
 migration.require(due.host_evidence['gateway_attempt']['result']==original_result,'original retained result differs from canonical attempt')
 pool=ResourceRef.from_dict(due.allowance_ref)
 reservation=LimitService(owner.store).get_reservation(ResourceRef(pool.authority,'reservation','W0-finite-turn-'+accounting_digest([OLD,pool.to_dict()])[:28]))
 migration.require(reservation is not None and reservation.pool_ref==pool and reservation.status.value=='uncertain'
  and reservation.actual_units==reservation.charged_units==0,'exact original uncertain W0 bounded reservation required')
 pool_state=LimitService(owner.store).get_pool(pool)
 migration.require(pool_state.held_units==1 and pool_state.remaining_allowance_units>=2,'original initializer and one new delivery must fit retained finite manager allowance')
 setup=read_setup(app.portfolio.operations,due.target['project_ref'])
 head=app.portfolio.operations.content_port.read(setup_reference(due.target['project_ref']))['current_revision']
 migration.require(setup is not None and setup['roles'].get('manager')==OLD,'original manual manager selector differs')
 return {'schema':SCHEMA+'.plan','source_plan_sha256':source_plan_sha256,'scope':scope,'original_result_sha256':migration.digest(original_result),
  'old_due':due.to_dict(),'old_setup':setup,'old_setup_ref':head,'reservation':reservation_snapshot(reservation),
  'pool_before':pool_snapshot(LimitService(owner.store).get_pool(pool)),'fresh_request_key':FRESH,'provider_called':False}

def apply(owner,app,state,*,immutable_plan,fail_before_report=False):
 prior=completed(owner);p=immutable_plan
 if prior:
  migration.require(prior['input_sha256']==migration.digest(p),'original recovery inputs changed')
  return {**prior['result'],'completion_report_ref':prior['report_ref'],'replayed':True}
 current=plan(owner,app,state,original_result=p['old_due']['host_evidence']['gateway_attempt']['result'],source_plan_sha256=p['source_plan_sha256'])
 migration.require(current==p,'original exact W0 recovery inputs changed before transaction')
 old=app._read(OLD)
 with owner.store.transaction():
  disposition=release_initialized_worker(app,schedule_id=OLD,request_key=KEY+':original-disposition',fresh_request_key=FRESH,
   expected_due_sha256=p['scope']['due_sha256'],expected_unknown_result_sha256=p['scope']['unknown_result_sha256'])
  limits=LimitService(owner.store);reservation=limits.get_reservation(ResourceRef(**{k:p['reservation']['ref'][k]for k in('authority','kind','id')}))
  # An actual initializer used the provider. Consume its one original declared
  # call; exact token observation remains original evidence, money may be unknown.
  charged=limits.settle(reservation,1,logical_request_key=KEY+':original-initializer-consumed',actor=owner.owner_actor)
  accounting={'reservation':reservation_snapshot(charged),'original_initializer_provider_occurred':True,
   'usage_capture_preserved':p['scope']['initializer_usage_capture_preserved'],'original_UNKNOWN_preserved':True,'released_as_zero':False}
  prepared=app.prepare_role(role='manager',project_ref=old.target['project_ref'],task_ref=old.target['task_ref'],
   assignment_ref=old.assignment_ref,generation=old.generation,mandate_ref=old.target['mandate_ref'],
   request_key=FRESH,profile=old.profile,native_session_id=p['scope']['native_session_id'],binding_schedule_id=OLD,allowance_ref=old.allowance_ref)
  migration.require(prepared.get('outcome')in('prepared','committed','replayed'),'one bound same manager occurrence must prepare')
  fresh=app._read(prepared['schedule_id']);setup=deepcopy(p['old_setup']);setup['roles']['manager']=fresh.schedule_id
  updated=app.compose_operating_setup(project_ref=old.target['project_ref'],operation='update',setup=setup,
   expected_setup_ref=p['old_setup_ref'],request_key=KEY+':same-manual-selector-CAS')
  migration.require(updated.get('outcome')in('updated','replayed'),'original manual selector CAS must qualify: '+str(updated))
  migration.require(app._read(OLD).host_evidence['gateway_attempt']['result']==p['old_due']['host_evidence']['gateway_attempt']['result'],
   'original failed UNKNOWN result changed')
  value={'original_schedule_id':OLD,'new_schedule_id':fresh.schedule_id,'assignment_ref':fresh.assignment_ref,'generation':fresh.generation,
   'project_ref':fresh.target['project_ref'],'task_ref':fresh.target['task_ref'],'allowance_ref':fresh.allowance_ref,
   'native_session_id':p['scope']['native_session_id'],'initializer_replayed':False,'requested_model':fresh.requested_model,'requested_reasoning':fresh.requested_reasoning,'disposition':disposition,
   'accounting_disposition':accounting,'input_sha256':migration.digest(p),'provider_called':False,
   'original_unknown_preserved':True,'old_Claude_initializer_unchanged':True,'new_provider_starts':0}
  if fail_before_report:raise InterruptedError('synthetic interruption before original recovery completion report')
  report=owner.assignments.append_report(ResourceRef.from_dict(fresh.assignment_ref),
   {'schema':SCHEMA+'.completed','input_sha256':migration.digest(p),'result':value},expected_generation=2,
   logical_request_key=KEY+':completed',actor=owner.owner_actor)
 return {**value,'completion_report_ref':report.ref.to_dict(),'replayed':False}

def refresh_view(service):
 owner,state=service.server.owner,service.server.state;prior=completed(owner)
 if prior is None:return {'outcome':'not-applicable','provider_called':False}
 result=prior['result'];old=result['original_schedule_id'];new=result['new_schedule_id'];head=manager_head(state)
 migration.require(state['assignment_ref']==result['assignment_ref']and state['manager_generation']==result['generation']==2,
  'exact initialized-session current W0 manager projection required')
 if head!=old:return {'outcome':'already-current-or-advanced','head':head,'provider_called':False}
 app=service._execution(principal=state['manager'],model='gpt-6-luna',reasoning='medium',evidence_id='W0-initialized-session-view-qualification')
 original=app._read(old);fresh=app._read(new)
 body=retained_capacity_release(app,original,_initializer_only=True)
 migration.require(fresh.execution_mode=='continue_existing'and fresh.target['native_id']==body['scope']['native_session_id']==result['native_session_id']
  and fresh.allowance_ref==original.allowance_ref==state['new_pool_refs']['manager']and fresh.assignment_ref==original.assignment_ref==state['assignment_ref']
  and fresh.generation==2 and fresh.stop_state=='active'and fresh.completion_state=='none'
  and not(fresh.host_evidence or{}).get('gateway_attempt'),'exact unattempted same-session delivery projection required')
 migration.require(read_setup(app.portfolio.operations,fresh.target['project_ref'])['roles']['manager']==new,
  'canonical manual selector differs from issued same-session delivery')
 before=deepcopy(state.get('manager_continuation'));migration.require(advance_manager_head(state,expected=old,due=fresh,settled_anchor=old),'view head changed')
 state['schedule_id']=new;state['W0_initialized_session_adoption']={'recovery_report_ref':prior['report_ref'],
  'old_schedule_id':old,'new_schedule_id':new,'native_session_id':result['native_session_id'],
  'former_continuation_preserved':before,'original_UNKNOWN_retained':True,'initializer_replayed':False}
 retired=list(state.get('retired_manager_occurrences')or[])
 if old not in retired:retired.append(old)
 state['retired_manager_occurrences']=retired;service.server._save_state()
 return {'outcome':'adopted-existing-initialized-session-delivery','schedule_id':new,'provider_called':False}
