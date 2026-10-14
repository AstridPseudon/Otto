"""Exact W0 manager READY initializer followed by a render-before-delivery fault.
Reuse the maintained initialized-session disposition/continuity protocol.
This does not mark useful work successful or reinterpret provider usage as zero.
"""
from pathlib import Path
import hashlib,re
from otto.portfolio.execution import OccurrencePreparationError,_digest
from otto.portfolio.worker_custody import _require,_terminal,_events,_native_terminal_trace
import w0_same_manager_migration as migration
OLD='role-9d3d59aaf0a68ed6ce2f1123104e'
ERROR={'code':'authorized_result_unverified','message':'pinned selected pack canonical provenance differs'}
CONTROLLER=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller')
GUARD_SHA='cfe351ce8f87a4c78110a5f4abd3d87f40c2f5f7eada315f06e66d5881213878'
DIAGNOSTICS_SHA='7723855cf7836f86c88be4b5ed9a859e1560b7fda02b9048a6987d16afa9d280'
def classify_retained_loader_diagnostics(stderr):
 # Source-qualified exact original stderr, three missing-frontmatter loader
 # diagnostics only. No runtime/provider/tool error is ignored or rewritten.
 if not isinstance(stderr,str)or len(stderr.encode())>4096 or hashlib.sha256(stderr.encode()).hexdigest()!=DIAGNOSTICS_SHA:return None
 rows=stderr.splitlines();rows=[row for row in rows if row]
 paths=[re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ERROR codex_core::session::session: failed to load skill ([^\n]+/SKILL\.md): missing YAML frontmatter delimited by ---',row)for row in rows]
 expected=['/Users/hannahomalley/Developer/astrid-video/astrid-local/Astrid/astrid/packs/pixel/skill/SKILL.md',
  '/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010/skills/one-otto-eaaa1ce8db77-20261013/otto/support/evidence-resource/SKILL.md']
 if len(paths)!=3 or not all(paths)or [row.group(1)for row in paths]!=[expected[0],expected[1],expected[1]]:return None
 return 'exact_original_W0_three_skill_loader_missing_frontmatter_no_native_work_error'
def inspect(execution,*,due):
 _require(execution.actor==due.lifecycle_owner==due.owner==due.manager_ref==migration.OWNER,
  'only authentic W0 occurrence owner may qualify initializer continuity')
 assignment=(execution._manager_adoption_anchor(due) if (due.host_evidence or{}).get('gateway_attempt') else execution._current(due.assignment_ref,due.generation))
 attempt=(due.host_evidence or{}).get('gateway_attempt')or{};result=attempt.get('result')or{};raw=result.get('raw_result')or{}
 session=result.get('physical_session_id');authorization=attempt.get('delivery_authorization')or{}
 _require(due.schedule_id==OLD and due.role=='manager' and due.generation==2
  and due.assignment_ref['id']==migration.MANAGER and due.project_ref==migration.PROJECT
  and assignment.role=='manager'and assignment.principal==due.recipient
  and assignment.payload.get('manager')==execution.actor and due.stop_state=='active'and due.completion_state=='none'
  and attempt.get('state')=='result'and isinstance(session,str)and session and attempt.get('physical_session_id')==session,
  'not exact existing W0 manager initializer custody')
 for value in(attempt,result):
  _require(value.get('assignment_ref')==due.assignment_ref and value.get('generation')==due.generation
   and value.get('logical_request_key')==due.in_flight_request,'original initialized request binding changed')
 _require(result.get('outcome')=='unknown'and result.get('delivery_state')=='unknown'
  and result.get('context_digest_verified')in(None,False) and result.get('error')==ERROR
  and result.get('operation')=='invoke'and result.get('logical_agent_id')==due.recipient
  and result.get('project_ref')==due.target['project_ref']and result.get('task_ref')==due.target['task_ref']
  and result.get('native_session_id')==session and result.get('requested_model')==due.requested_model
  and result.get('requested_reasoning')==due.requested_reasoning and result.get('requested_profile')==due.profile
  and raw.get('transport_operation')=='resume'and raw.get('worker_content')==[]
  and raw.get('task_bound_evidence')is None and raw.get('work_envelope')=={}
  and raw.get('work_receipt')is None and result.get('observed_turn_id')is None,
  'original UNKNOWN does not prove exact renderer-before-recipient fault')
 expected={'status':'authorized','logical_request_key':due.in_flight_request,'physical_session_id':session,
  'project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],'assignment_ref':due.assignment_ref,
  'generation':due.generation,'role':'manager','principal':due.recipient,'lifecycle_owner':execution.actor}
 _require(authorization==raw.get('owner_delivery_authorization')and all(type(authorization.get(k))is type(v)
  and authorization.get(k)==v for k,v in expected.items()),'exact original initialized owner authorization differs')
 _require(attempt.get('delivery_admission')is None,'recipient admission already occurred')
 # This installed original renderer is deliberately retained unchanged; its
 # call occurs before recipient host creation in the attested adapter source.
 _require(hashlib.sha256((CONTROLLER/'operating_service.py').read_bytes()).hexdigest()==GUARD_SHA,
  'original render guard source fingerprint changed')
 from otto.agents.herzchen_adapter import HerzchenCodexAdapter
 import inspect as source_inspect
 source=source_inspect.getsource(HerzchenCodexAdapter._invoke_owner_authorized)
 _require(source.index('self.render_verified_invocation(')<source.index('recipient.resume(resumed)'),
  'owner adapter no longer qualifies exact render-before-recipient ordering')
 init=raw.get('initialization_envelope')or{};receipt=raw.get('initialization_receipt')or{}
 _terminal(init,receipt,session=session,principal=due.recipient,operation='invoke',status='succeeded',code=0,initializer_diagnostics=True,diagnostic_classifier=classify_retained_loader_diagnostics)
 events=_events(init);turn=(init.get('host_evidence')or{}).get('turn_id')
 _require(len(events)==4 and events[:2]==[{'type':'thread.started','thread_id':session},{'type':'turn.started'}]
  and events[2]=={'type':'item.completed','item':{'id':'item_0','type':'agent_message','text':'READY'}}
  and events[3].get('type')=='turn.completed'and set(events[3])<={'type','usage'},'initializer is not exact terminal READY-only')
 host=init.get('host_evidence')or{}
 _require(host.get('session_id')==session and host.get('session_created')is True and host.get('process_started')is True
  and host.get('invocation_turn_verified')is True and host.get('provenance')=='host_native_jsonl'
  and init.get('observed_model')==due.requested_model and init.get('observed_reasoning')==due.requested_reasoning,
  'original initializer native identity/model qualification differs')
 for other in execution.due_port.list_due({'project_ref':due.project_ref}):
  other_attempt=(other.get('host_evidence')or{}).get('gateway_attempt')or{}
  _require(other.get('schedule_id')==due.schedule_id or other.get('project_ref')!=due.project_ref
   or not(other_attempt.get('state')=='claimed' or other_attempt and other.get('stop_state')=='active'
    and other.get('in_flight_request') and other_attempt.get('state')!='result'),
   'another same-project owner occurrence is physically admitted without terminal evidence')
 trace=_native_terminal_trace(execution,session,turn,None,model=due.requested_model,reasoning=due.requested_reasoning,profile=due.profile)
 return {'schedule_id':due.schedule_id,'due_version':due.version,'due_sha256':_digest(due.to_dict()),'unknown_result_sha256':_digest(result),
  'assignment_ref':due.assignment_ref,'generation':due.generation,'project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],
  'principal':due.recipient,'model':due.requested_model,'reasoning':due.requested_reasoning,'native_session_id':session,'native_turn_id':None,
  'initialization_process_id':init['process_id'],'work_process_id':None,'native_terminal_proved':True,'task_work_started':False,
  'historical_unknown_preserved':True,'provider_retry_allowed':False,'native_trace_sha256':trace,
  'initializer_usage_capture_preserved':init.get('usage_capture'),'initializer_usage_events_preserved':events[3].get('usage'),
  'initializer_stderr_sha256':hashlib.sha256(init['stderr'].encode()).hexdigest(),'initializer_diagnostics_classification':classify_retained_loader_diagnostics(init['stderr']),'renderer_guard_sha256':GUARD_SHA,'manager_initialized_render_fault':True}

def conversation_proof(*,due,original,assignment,due_port,actor,reader):
 """Read-only readiness of one authenticated READY-only initialized delivery.
 No useful-turn admission is synthesized; actual runtime validates full trace.
 """
 from dataclasses import replace
 from herzchen.contracts import ResourceRef
 marker=(original.host_evidence or{}).get('worker_custody_release')or{}
 _require(reader is not None and actor==migration.OWNER and due.role==original.role=='manager'
  and original.schedule_id==OLD and original.project_ref==migration.PROJECT and original.generation==due.generation==2
  and original.assignment_ref==due.assignment_ref==assignment['ref']and assignment['principal']==due.recipient==original.recipient
  and assignment['role']=='manager'and assignment['generation']==2
  and original.lifecycle_owner==due.lifecycle_owner==original.manager_ref==due.manager_ref==actor
  and original.stop_state=='stopped'and original.completion_state=='unknown'and original.in_flight_request is None,
  'READY-only conversation must retain exact same W0 current manager and original stopped UNKNOWN')
 record=reader.get_record(ResourceRef.from_dict(marker['disposition_ref']))
 body=record.payload.get('value')if record else None
 _require(record is not None and record.ref.to_dict()==marker['disposition_ref']and isinstance(body,dict)
  and body.get('schema')=='otto.worker-initializer-custody-disposition.v1'
  and body.get('initializer_provider_occurred')is True and body.get('initializer_replay_allowed')is False
  and body.get('fresh_occurrence_limit')==1 and body.get('recovery_mode')=='same-assignment-initialized-session'
  and body['scope'].get('manager_initialized_render_fault')is True and body['scope'].get('task_work_started')is False,
  'exact authenticated initialized-manager disposition required')
 _require(any(e.operation=='work.report.append'and e.actor.actor==actor and e.actor.authority==due.assignment_ref['authority']
  for e in reader.list_events(subjects=(record.ref,))),'initializer disposition was not written by authentic lifecycle owner')
 scope=body['scope'];old_evidence={k:v for k,v in original.host_evidence.items()if k!='worker_custody_release'}
 before=replace(original,**body['before'],version=scope['due_version'],host_evidence=old_evidence)
 _require(_digest(before.to_dict())==scope['due_sha256']and _digest(old_evidence['gateway_attempt']['result'])==scope['unknown_result_sha256']
  and due.in_flight_request==body['fresh_request_key']==marker['fresh_request_key']
  and due.target.get('native_binding')=={'schedule_id':original.schedule_id,'due_sha256':_digest(original.to_dict())}
  and due.target.get('native_id')==scope['native_session_id']
  and due.allowance_ref==original.allowance_ref and due.target['task_ref']==original.target['task_ref']
  and due.target['mandate_ref']==original.target['mandate_ref']
  and all(getattr(due,k)==getattr(original,k)for k in('requested_model','requested_reasoning','profile')),
  'one continuation differs from exact reserved original initializer/session/task/allowance')
 return scope['native_session_id'],{'source':'authenticated_terminal_READY_initializer_only',
  'schedule_id':original.schedule_id,'disposition_ref':record.ref.to_dict(),'useful_input_previously_delivered':False}
