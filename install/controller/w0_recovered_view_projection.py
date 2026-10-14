"""W0-only composition adoption of one already-issued recovered manager head.
No canonical write, role/provider creation, budget mutation or UNKNOWN bypass.
"""
from copy import deepcopy
from herzchen.contracts import ResourceRef
from otto.portfolio.manager_journey_service import manager_head,advance_manager_head
from otto.portfolio.operating_setup import read_setup
from otto.portfolio.worker_custody import retained_preinitialization_release,permits_preinitialization_role
from w0_host_evidence_recovery import completed
import w0_same_manager_migration as migration

OLD='role-84cd74ba0bd9fea6770f164288a4'

def refresh(service):
 owner,state=service.server.owner,service.server.state
 record=completed(owner)
 if record is None:return {'outcome':'not-applicable','provider_called':False}
 result=record['result'];old_id=result['original_schedule_id'];fresh_id=result['new_schedule_id']
 migration.require(state['project_ref']['id']==migration.PROJECT and all(state['assignment_ref'].get(key)==result['assignment_ref'].get(key)for key in('authority','kind','id'))
  and state['manager_generation']==result['generation']==2,'same W0 exact current manager projection required')
 head=manager_head(state)
 if head!=old_id:
  # Preserve a legitimately advanced callback/turn. This historical report
  # never rewinds a newer same-manager head or resets its native session.
  return {'outcome':'already-current-or-advanced','head':head,'recovery_report_ref':record['report_ref'],'provider_called':False}
 app=service._execution(principal=state['manager'],model=state['requested_model'],reasoning=state['requested_reasoning'],evidence_id='W0-recovered-head-source-qualification')
 old=app._read(old_id);fresh=app._read(fresh_id)
 body=retained_preinitialization_release(app,old);scope=body['scope']
 migration.require(scope.get('host_evidence_guard_before_typed_request')is True and old_id==OLD
  and body['fresh_occurrence_limit']==1 and result['disposition']['disposition_ref']==old.host_evidence['role_preinitialization_custody_release']['disposition_ref'],
  'exact original qualified host-evidence disposition required')
 current=owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']))
 permission=permits_preinitialization_role(app,schedule_id=old_id,assignment=current,
  project_ref=fresh.target['project_ref'],task_ref=fresh.target['task_ref'],request_key=body['fresh_request_key'])
 migration.require(fresh.target.get('preinitialization_recovery')==permission
  and fresh.assignment_ref==state['assignment_ref']and fresh.generation==2 and fresh.recipient==state['manager']
  and fresh.allowance_ref==state['new_pool_refs']['manager']and fresh.allowance_ref==old.allowance_ref
  and(fresh.requested_model,fresh.requested_reasoning,fresh.profile)==('gpt-6-luna','medium','workspace-write')
  and fresh.stop_state=='active'and fresh.completion_state=='none'
  and not(fresh.host_evidence or{}).get('gateway_attempt')and fresh.last_result is None,
  'one existing exact same-manager unattempted recovery occurrence required')
 setup=read_setup(app.portfolio.operations,state['project_ref'])
 migration.require(setup is not None and setup['mode']=='manual'and setup['roles'].get('manager')==fresh_id,
  'canonical adopted manual selector must name exact recovered occurrence')
 # All permission/result/budget guards above are canonical reads. Only the
 # existing normal owner-view pointer/save operation follows qualification.
 before=deepcopy(state.get('manager_continuation'))
 migration.require(advance_manager_head(state,expected=old_id,due=fresh,settled_anchor=old_id),'view head changed before exact adoption')
 state['schedule_id']=fresh_id
 retired=list(state.get('retired_manager_occurrences')or[])
 if old_id not in retired:retired.append(old_id)
 state['retired_manager_occurrences']=retired
 state['W0_recovered_head_adoption']={'recovery_report_ref':record['report_ref'],'old_schedule_id':old_id,'new_schedule_id':fresh_id,
  'former_continuation_preserved':before,'canonical_effects_replayed':False,'provider_called':False}
 service.server._save_state()
 return {'outcome':'adopted-existing-recovered-head','schedule_id':fresh_id,'recovery_report_ref':record['report_ref'],'provider_called':False}
