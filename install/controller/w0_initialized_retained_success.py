"""Read-only historical initializer custody proof after exact authorized work.
The original UNKNOWN and charge remain; later terminal continuations must form
one finite, owner-admitted same-session chain rooted at the reserved delivery.
"""
import hashlib,json
from pathlib import Path
from herzchen.contracts import ResourceRef
from otto.portfolio.execution import _digest, _identity
from otto.portfolio.worker_custody import _require
from w0_finite_role_allowance import digest as budget_digest
import w0_same_manager_migration as migration
BOUND=2*1024*1024

def _charged(execution,due,pool):
 ref=ResourceRef(pool.authority,'reservation','W0-finite-turn-'+budget_digest([due.schedule_id,pool.to_dict()])[:28])
 record=execution.portfolio.operations._owner_reader.get_record(ref)
 value=record.payload if record is not None else {}
 _require(record is not None and value.get('pool_ref')==pool.to_dict() and value.get('status')=='consumed'
  and value.get('declared_units')==value.get('actual_units')==value.get('charged_units')==1,
  'each exact initializer/useful delivery reservation must remain consumed')

def _terminal(execution,item,anchor,session,pool):
 attempt=(item.host_evidence or{}).get('gateway_attempt')or{};result=attempt.get('result')or{}
 authorization=attempt.get('delivery_authorization')or{};evidence=result.get('task_bound_evidence')or{}
 request=item.last_completed_request;turn=result.get('observed_turn_id')
 _require(item.stop_state=='completed'and item.completion_state=='succeeded'and item.in_flight_request is None
  and isinstance(request,str)and request and attempt.get('state')=='result'and result.get('outcome')=='succeeded'
  and item.execution_mode=='continue_existing'and item.target.get('native_id')==session
  and item.generation==anchor.generation and item.assignment_ref['id']==anchor.assignment_ref['id']
  and all(getattr(item,k)==getattr(anchor,k)for k in('project_ref','role','recipient','owner','manager_ref','lifecycle_owner','allowance_ref','requested_model','requested_reasoning','profile'))
  and item.target['native_adapter']==anchor.target['native_adapter']
  and all(_identity(item.target[k])==_identity(anchor.target[k])for k in('project_ref','task_ref')),
  'same-session continuation is active, foreign, uncertain or differs from original finite scope')
 expected={'status':'authorized','logical_request_key':request,'physical_session_id':session,'assignment_ref':item.assignment_ref,
  'generation':2,'principal':item.recipient,'lifecycle_owner':execution.actor,'role':'manager',
  'project_ref':item.target['project_ref'],'task_ref':item.target['task_ref']}
 _require(all(authorization.get(k)==v for k,v in expected.items())and result.get('physical_session_id')==session
  and result.get('native_session_id')==session and result.get('logical_request_key')==request
  and result.get('assignment_ref')==item.assignment_ref and result.get('generation')==2
  and result.get('context_digest_verified')is True and isinstance(turn,str)and turn
  and evidence.get('session_id')==session and evidence.get('turn_id')==turn and evidence.get('generation')==2
  and evidence.get('assignment_ref')==item.assignment_ref and evidence.get('owner_delivery_authorization')==authorization
  and evidence.get('delivered_brief_digest')==authorization.get('brief_sha256'),
  'same-session terminal task-bound owner admission/capture differs')
 for name in('user_message','turn_context'):
  record=(evidence.get('host_records')or{}).get(name)or{}
  _require(record.get('session_id')==session and record.get('turn_id')==turn
   and isinstance(record.get('raw_line_sha256'),str)and len(record['raw_line_sha256'])==64,
   'same-session captured native record missing or foreign: '+name+str({k:record.get(k)for k in ('session_id','turn_id','raw_line_sha256')}))
 _require(result.get('observed_model')==anchor.requested_model and result.get('observed_reasoning')==anchor.requested_reasoning
  and result.get('requested_profile')==anchor.profile and result.get('observed_profile')in(None,anchor.profile)
  and ((evidence.get('native_permissions')or{}).get('sandbox_policy')or{}).get('type')==anchor.profile,'same-session observed model/profile differs')
 current=execution._manager_adoption_anchor(item);execution._verify_native_binding(current,session,item.schedule_id)
 _charged(execution,item,pool)
 return turn

def _latest_terminal(execution,session,allowed_turns):
 reader=getattr(execution.runtime.adapter,'trusted_thread_reader',None)
 _require(callable(reader),'trusted exact native metadata reader required')
 thread=(reader(session)or{}).get('thread')or{}
 _require(thread.get('id')==session and isinstance(thread.get('path'),str),'trusted native session metadata differs')
 path=Path(thread['path']);size=path.stat().st_size
 # Never hydrate accumulated session history. A terminal record must be present
 # in this finite suffix; otherwise custody stays held for exact diagnosis.
 with path.open('rb')as stream:
  start=max(0,size-BOUND);stream.seek(start);raw=stream.read(BOUND+1)
 _require(len(raw)<=BOUND and path.stat().st_size==size,'native trace grew during bounded terminal read')
 if start:raw=raw.partition(b'\n')[2]
 try:rows=[json.loads(line)for line in raw.splitlines()if line.strip()]
 except ValueError as error:raise ValueError('bounded native suffix is malformed')from error
 events=[row.get('payload')or{}for row in rows if row.get('type')=='event_msg'and(row.get('payload')or{}).get('type')in('task_started','task_complete','task_aborted')]
 _require(events and events[-1].get('type')=='task_complete'and events[-1].get('turn_id')in allowed_turns
  and events[-1].get('error')is None,'latest native turn is active, foreign or not qualified terminal work')
 # Even a turn context without a task-start event is not silently ignored.
 terminals=[i for i,row in enumerate(rows)if row.get('type')=='event_msg'and(row.get('payload')or{}).get('type')=='task_complete']
 _require(terminals and not any(row.get('type')=='turn_context'for row in rows[terminals[-1]+1:]),
  'newer native context has no qualified terminal occurrence')

def qualifies(execution,due,body):
 scope=body['scope']
 if due.role!='manager'or not scope.get('manager_initialized_render_fault'):return False
 _require(due.project_ref==migration.PROJECT and due.assignment_ref['id']==migration.MANAGER and due.generation==2
  and execution.actor==due.lifecycle_owner==due.owner==due.manager_ref==migration.OWNER,'exact retired W0 initializer ownership required')
 request=body['fresh_request_key'];schedule='role-'+_digest([scope['project_ref'],scope['assignment_ref'],request])[:28]
 fresh_raw=execution.due_port.read_due(schedule)
 if fresh_raw is None:return False
 fresh=execution._read(schedule)
 if not(fresh.host_evidence or{}).get('gateway_attempt'):return False
 _require(fresh.last_completed_request==request and fresh.assignment_ref==scope['assignment_ref']
  and fresh.target['mandate_ref']==due.target['mandate_ref']
  and fresh.target.get('native_binding')=={'schedule_id':due.schedule_id,'due_sha256':_digest(due.to_dict())},
  'original permitted initialized-session delivery binding changed')
 _require(all(fresh.target[k]==due.target[k]for k in('project_ref','task_ref','native_adapter')),'original initialized delivery scope revision changed')
 session=scope['native_session_id'];pool=ResourceRef.from_dict(due.allowance_ref)
 _charged(execution,due,pool)
 allowed={fresh.schedule_id:fresh};turns={_terminal(execution,fresh,due,session,pool)}
 rows=execution.due_port.list_due({'native_adapter':fresh.target['native_adapter'],'native_session_id':session})
 _require(len(rows)<=16,'same-session known occurrence inventory exceeds finite bound')
 pending=[]
 for row in rows:
  if row['schedule_id']in(due.schedule_id,fresh.schedule_id):continue
  _require(row.get('project_ref')==due.project_ref and row.get('generation')==2
   and row.get('recipient')==due.recipient and (row.get('assignment_ref')or{}).get('id')==due.assignment_ref['id'],
   'foreign occurrence shares initialized W0 session')
  if(row.get('host_evidence')or{}).get('gateway_attempt'):pending.append(execution._read(row['schedule_id']))
 # Authenticate each later terminal edge against the already-qualified exact
 # predecessor. Inventory order is irrelevant; branches/unknown anchors refuse.
 while pending:
  joined=False
  for item in list(pending):
   link=item.target.get('native_binding')or{};prior=allowed.get(link.get('schedule_id'))
   if prior is None:continue
   _require(link.get('due_sha256')==_digest(prior.to_dict()),'later continuation predecessor hash changed')
   validate_mandate_edge(execution,prior,item)
   turns.add(_terminal(execution,item,due,session,pool));allowed[item.schedule_id]=item;pending.remove(item);joined=True
  _require(joined,'later attempted continuation lacks exact authorized terminal lineage')
 from w0_initialized_manager_custody import GUARD_SHA,CONTROLLER
 _require(scope.get('renderer_guard_sha256')==GUARD_SHA==hashlib.sha256((CONTROLLER/'operating_service.py').read_bytes()).hexdigest()
  and scope.get('native_terminal_proved')is True and scope.get('task_work_started')is False
  and isinstance(scope.get('native_trace_sha256'),str)and len(scope['native_trace_sha256'])==64,
  'authentic historical initializer/source guard attestation differs')
 _latest_terminal(execution,session,turns)
 return True

from herzchen.contracts import ResourceRef
from otto.portfolio.execution import _digest, _identity
from otto.portfolio.worker_custody import _require
from otto.portfolio.owner_readers import mandate_reader, task_reader

def _mandate(execution,project,ref):
 value=mandate_reader(execution.portfolio.operations,project,ref)(_identity(ref))
 _require(value['document_owner']==execution.actor,'historical mandate owner differs')
 return value['payload']

def _created(execution,item,ref,key):
 reader=execution.portfolio.operations._owner_reader
 target=ResourceRef(ref['authority'],ref['kind'],ref['id'])
 receipt=reader.get_receipt(key)
 _require(receipt is not None and receipt.status.value=='committed'
  and receipt.operation=='dat.content.document.create'and receipt.target==target
  and receipt.result_ref==ResourceRef.from_dict(ref),'historical mandate creation receipt differs')
 _require(any(e.operation=='dat.content.document.create'and e.actor==execution.binding.authenticated_actor(execution.actor)
  for e in reader.list_events(subjects=(target,))), 'historical mandate lacks authenticated owner creation')

def _ancestry(execution,item,prior_ref):
 from otto.portfolio.operating_setup import authenticated_adoption_ancestor
 current=execution.assignments.get(ResourceRef.from_dict(item.assignment_ref))
 projection={'ref':current.ref.to_dict(),'principal':current.principal,'role':current.role,'generation':current.generation,'payload':current.payload}
 _require(current.role=='manager'and current.principal==item.recipient and current.generation==item.generation
  and _identity(current.scope.to_dict())==_identity(item.target['project_ref'])
  and authenticated_adoption_ancestor(projection,item.assignment_ref,execution.portfolio.operations._owner_reader)
  and authenticated_adoption_ancestor(projection,prior_ref,execution.portfolio.operations._owner_reader),
  'historical mandate assignment lacks authenticated same-manager ancestry')

def validate_mandate_edge(execution,prior,item):
 """Authenticate at most one resource-adoption plus one completed-task edge."""
 _require(item.role==prior.role=='manager'and item.generation==prior.generation
  and item.recipient==prior.recipient and item.assignment_ref['id']==prior.assignment_ref['id']
  and _identity(item.target['project_ref'])==_identity(prior.target['project_ref'])
  and _identity(item.target['task_ref'])==_identity(prior.target['task_ref']),
  'historical continuation scope identity changed')
 e=item.host_evidence or {};cursor=prior.target['mandate_ref'];task=prior.target['task_ref']
 adoption=e.get('role_mandate_adoption')or{}
 # Inherited receipts on a later callback are not new edges. Select only an
 # exact receipt whose input is the actual predecessor's immutable mandate.
 if cursor!=item.target['mandate_ref']and adoption.get('before_mandate_ref')==cursor:
  _require(adoption.get('schema')=='otto.role-mandate-adoption.v1'
   and adoption.get('current_assignment_ref')==item.assignment_ref
   and adoption.get('generation')==item.generation and adoption.get('provider_called')is False
   and type(adoption.get('before_due_version'))is int and adoption['before_due_version']<item.version,
   'historical resource-adoption receipt differs')
  before=_mandate(execution,prior.target['project_ref'],cursor);current_ref=adoption['current_mandate_ref']
  after=_mandate(execution,item.target['project_ref'],current_ref)
  _require(adoption.get('before_assignment_ref')==before.get('assignment_ref')
   and after.get('assignment_ref')==item.assignment_ref
   and adoption.get('before_mandate_sha256')==_digest(before)
   and adoption.get('current_mandate_sha256')==_digest(after)
   and before.get('task_ref')==after.get('task_ref')==task
   and before.get('instruction_contract')==after.get('instruction_contract'),
   'historical resource-adoption mandate bodies differ')
  _ancestry(execution,item,before['assignment_ref']);_ancestry(execution,item,prior.assignment_ref)
  key=item.invocation_identity+':mandate-adoption:'+_digest(item.assignment_ref)
  _created(execution,item,current_ref,key);cursor=current_ref
 refresh=e.get('manager_completed_task_refresh')or{}
 if cursor!=item.target['mandate_ref']and refresh.get('before_mandate_ref')==cursor:
  fresh=item.target['task_ref'];new_ref=refresh.get('current_mandate_ref')
  _require(refresh.get('schema')=='otto.manager-completed-task-refresh.v1'
   and refresh.get('before_task_ref')==task and refresh.get('current_task_ref')==fresh
   and refresh.get('assignment_ref')==item.assignment_ref and refresh.get('generation')==item.generation
   and refresh.get('native_id')==item.target.get('native_id')
   and refresh.get('reported_task_ref')==item.target.get('reported_task_ref')
   and refresh.get('provider_called')is False and type(refresh.get('before_due_version'))is int
   and refresh['before_due_version']<item.version,'historical completed-task receipt differs')
  before=_mandate(execution,prior.target['project_ref'],cursor);after=_mandate(execution,item.target['project_ref'],new_ref)
  expected={**before,'task_ref':fresh,'instruction_contract':{**before['instruction_contract'],'task_ref':fresh}}
  _require(before.get('task_ref')==task and before.get('assignment_ref')==item.assignment_ref
   and refresh.get('before_mandate_sha256')==_digest(before)
   and refresh.get('current_mandate_sha256')==_digest(after)and after==expected,
   'historical completed-task mandate body differs')
  observed=task_reader(execution.portfolio.operations,item.target['project_ref'],fresh)(_identity(fresh))
  completion=observed['payload'].get('completion')or{};receipt=execution.portfolio.operations._owner_reader.get_receipt(completion.get('logical_request_key'))
  _require(observed['ref']==fresh and observed['lifecycle']=='completed'
   and completion.get('task_ref')==task and completion.get('generation')==item.generation
   and completion.get('manager')==item.recipient and completion.get('assignment_ref')==item.assignment_ref
   and receipt is not None and receipt.status.value=='committed'and receipt.operation=='work.revise'
   and receipt.target==ResourceRef.from_dict(task)and receipt.result_ref==ResourceRef.from_dict(fresh),
   'historical task revision lacks exact committed completion')
  key=item.invocation_identity+':completed-task:'+fresh['revision']
  _created(execution,item,new_ref,key);cursor=new_ref;task=fresh
 _require(cursor==item.target['mandate_ref']and task==item.target['task_ref'],
  'later mandate lacks exact maintained canonical receipt edge')
 if item.target['project_ref']!=prior.target['project_ref']:
  project=e.get('manager_project_reconciliation')or{}
  _require(project.get('schema')=='otto.manager-project-reconciliation.v1'
   and project.get('before_project_ref')==prior.target['project_ref']
   and project.get('current_project_ref')==item.target['project_ref']
   and project.get('assignment_ref')==item.assignment_ref and project.get('generation')==item.generation
   and project.get('reported_task_ref')==item.target.get('reported_task_ref')
   and project.get('execution_task_ref')in(prior.target['task_ref'],item.target['task_ref'])
   and project.get('provider_called')is False and type(project.get('before_due_version'))is int
   and project['before_due_version']<item.version,'historical project revision lacks exact reconciliation')
