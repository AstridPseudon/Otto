"""Root-only closed, receipt-first exact W0 preinitializer recovery.
No Store opener/provider; the maintained closed operator supplies authentic ports.
"""
from copy import deepcopy
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.portfolio.owner_readers import json_value
from otto.portfolio.worker_custody import inspect_preinitialization_role,release_preinitialization_role,retained_preinitialization_release
from otto.portfolio.operating_setup import read_setup,setup_reference
from w0_host_evidence_reservation import release as release_reservation
import w0_same_manager_migration as migration
from w0_finite_role_allowance import digest as accounting_digest

SCHEMA='otto.W0-first-Codex-host-evidence-recovery.v1'
OLD='role-84cd74ba0bd9fea6770f164288a4'
KEY='W0-original-84cd-host-evidence-recovery-20261013-v1'
FRESH=KEY+':one-bound-manager-role'

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
 due=app._read(OLD);scope=inspect_preinitialization_role(app,schedule_id=OLD)
 migration.require(scope.get('host_evidence_guard_before_typed_request')is True and due.generation==2
  and due.assignment_ref['id']==migration.MANAGER and due.project_ref==migration.PROJECT
  and due.allowance_ref==state['new_pool_refs']['manager'],'exact original W0 host-evidence failure required')
 migration.require(due.host_evidence['gateway_attempt']['result']==original_result,'original retained result differs from canonical attempt')
 pool=ResourceRef.from_dict(due.allowance_ref)
 reservation=LimitService(owner.store).get_reservation(ResourceRef(pool.authority,'reservation','W0-finite-turn-'+accounting_digest([OLD,pool.to_dict()])[:28]))
 migration.require(reservation is not None and reservation.pool_ref==pool and reservation.status.value=='uncertain'
  and reservation.actual_units==reservation.charged_units==0,'exact original uncertain W0 bounded reservation required')
 setup=read_setup(app.portfolio.operations,due.target['project_ref'])
 head=app.portfolio.operations.content_port.read(setup_reference(due.target['project_ref']))['current_revision']
 migration.require(setup is not None and setup['roles'].get('manager')==OLD,'original manual manager selector differs')
 return {'schema':SCHEMA+'.plan','source_plan_sha256':source_plan_sha256,'scope':scope,'original_result_sha256':migration.digest(original_result),
  'old_due':due.to_dict(),'old_setup':setup,'old_setup_ref':head,'reservation':json_value(reservation),
  'pool_before':json_value(LimitService(owner.store).get_pool(pool)),'fresh_request_key':FRESH,'provider_called':False}

def apply(owner,app,state,*,immutable_plan,fail_before_report=False):
 prior=completed(owner);p=immutable_plan
 if prior:
  migration.require(prior['input_sha256']==migration.digest(p),'original recovery inputs changed')
  return {**prior['result'],'completion_report_ref':prior['report_ref'],'replayed':True}
 current=plan(owner,app,state,original_result=p['old_due']['host_evidence']['gateway_attempt']['result'],source_plan_sha256=p['source_plan_sha256'])
 migration.require(current==p,'original exact W0 recovery inputs changed before transaction')
 old=app._read(OLD)
 with owner.store.transaction():
  disposition=release_preinitialization_role(app,schedule_id=OLD,request_key=KEY+':original-disposition',fresh_request_key=FRESH)
  accounting=release_reservation(app,owner=owner,state=state,disposition=disposition)
  prepared=app.prepare_role(role='manager',project_ref=old.target['project_ref'],task_ref=old.target['task_ref'],
   assignment_ref=old.assignment_ref,generation=old.generation,mandate_ref=old.target['mandate_ref'],
   request_key=FRESH,profile=old.profile,binding_schedule_id=OLD,allowance_ref=old.allowance_ref)
  migration.require(prepared.get('outcome')in('prepared','committed','replayed'),'one bound same manager occurrence must prepare')
  fresh=app._read(prepared['schedule_id']);setup=deepcopy(p['old_setup']);setup['roles']['manager']=fresh.schedule_id
  updated=app.compose_operating_setup(project_ref=old.target['project_ref'],operation='update',setup=setup,
   expected_setup_ref=p['old_setup_ref'],request_key=KEY+':same-manual-selector-CAS')
  migration.require(updated.get('outcome')in('updated','replayed'),'original manual selector CAS must qualify')
  migration.require(app._read(OLD).host_evidence['gateway_attempt']['result']==p['old_due']['host_evidence']['gateway_attempt']['result'],
   'original failed UNKNOWN result changed')
  value={'original_schedule_id':OLD,'new_schedule_id':fresh.schedule_id,'assignment_ref':fresh.assignment_ref,'generation':fresh.generation,
   'project_ref':fresh.target['project_ref'],'task_ref':fresh.target['task_ref'],'allowance_ref':fresh.allowance_ref,
   'requested_model':fresh.requested_model,'requested_reasoning':fresh.requested_reasoning,'disposition':disposition,
   'accounting_disposition':accounting,'input_sha256':migration.digest(p),'provider_called':False,
   'original_unknown_preserved':True,'old_Claude_initializer_unchanged':True,'new_provider_starts':0}
  if fail_before_report:raise InterruptedError('synthetic interruption before original recovery completion report')
  report=owner.assignments.append_report(ResourceRef.from_dict(fresh.assignment_ref),
   {'schema':SCHEMA+'.completed','input_sha256':migration.digest(p),'result':value},expected_generation=2,
   logical_request_key=KEY+':completed',actor=owner.owner_actor)
 return {**value,'completion_report_ref':report.ref.to_dict(),'replayed':False}
