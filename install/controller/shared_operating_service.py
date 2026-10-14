"""Three fixed canonical views; one existing owner and serialized Store lane."""
from pathlib import Path
import argparse,hashlib,json,os,sys,threading,time,contextvars
C=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller')
sys.path.insert(0,str(C));import operating_service as base
# Exact source-authenticated optional descriptor, registered by the accepted
# owner transfer producer. This startup composition admits no discovered or
# caller-selected descriptor and preserves the stable work definitions.
from assignment_owner_migration import contribution as W0_owner_migration_contribution
if not getattr(base.domains,'_W0_owner_migration_composition',False):
 _W0_base_domains=base.domains
 def _W0_exact_domains():
  selected=tuple(_W0_base_domains());optional=W0_owner_migration_contribution()
  prior=[d for d in selected if d.domain_id==optional.domain_id]
  if prior and prior!=[optional]:raise PermissionError('exact owner migration descriptor differs')
  return tuple(sorted(selected if prior else (*selected,optional),key=lambda d:d.domain_id))
 _W0_exact_domains._W0_owner_migration_composition=True
 base.domains=_W0_exact_domains
PRIVATE=Path('/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010')
VC=C.parent.parent/'otto-vision-20261011/controller'
PC=C.parent.parent/'otto-astrid-union-port-20261011/controller'
def read(p):return json.loads(p.read_text())
def dump(p,v):base.write(p,v)
def identity(r):return tuple(r[k]for k in('authority','kind','id'))

def scoped_startup_report(block,states,capacity_holds,caller):
 """Scope in-memory status after caller authority was authenticated by router."""
 def project_identity(value):
  if hasattr(value,'to_dict'):value=value.to_dict()
  if isinstance(value,dict):return tuple(value.get(k)for k in('authority','kind','id'))
  return None
 caller_identity=project_identity(caller.get('project_ref'))
 key=next((name for name,state in states.items()if caller_identity is not None and project_identity(state.get('project_ref'))==caller_identity),None)
 if key is None:raise PermissionError('authenticated caller has no startup-status view')
 # ExecutionHost scopes contain project IDs, not ResourceRefs. The authority
 # and kind were checked above against the actual authorized view.
 project_id=caller_identity[2]
 return {**block,
  'current_context_qualified':{key:block['current_context_qualified'].get(key)},
  'context_qualifications':{key:block['context_qualifications'].get(key,{})},
  'held_capacity_effects':sorted(schedule for schedule,scope in capacity_holds.items()if scope.get('project')==project_id)}


def owner_scoped_startup_report(block,router,owner_actor,capacity_holds):
 """Read only views covered by this installation-owner's issued grants."""
 allowed={}
 for view_key,view in router.services.items():
  grant=view.server.owner.project_read_grant
  project=ResourceRef.from_dict(view.server.state['project_ref'])
  if (grant is not None and grant.principal==view.server.owner.owner_actor
      and grant.principal.actor==owner_actor and grant.allows(project)):
   allowed[view_key]=project
 project_ids={project.id for project in allowed.values()}
 return {'current_context_qualified':{key:block['current_context_qualified'].get(key)for key in allowed},
  'context_qualifications':{key:block['context_qualifications'].get(key,{})for key in allowed},
  'held_capacity_effects':sorted(schedule for schedule,scope in capacity_holds.items()if scope.get('project')in project_ids),
  'qualification_scope':{'owner_actor':owner_actor,'project_ids':sorted(project_ids),'source':'existing installation-owner project grants'}}


def bind_startup_readers(common,block,store):
 """Resolve the currently installed expanded router on every status read."""
 def fresh_block():return {**block,'source_next_append':store.source_next_append}
 def manager_report(caller):
  current=common.host_clients.router
  states={key:service.server.state for key,service in current.services.items()}
  return scoped_startup_report(fresh_block(),states,current.host._capacity_holds,caller)
 def owner_report():
  current=common.host_clients.router
  return {**owner_scoped_startup_report(fresh_block(),current,common.host_clients.config['owner']['actor'],current.host._capacity_holds),
   'source_next_append':store.source_next_append}
 common.host_clients.shared_host.startup_report_reader=manager_report
 common.host_clients.startup_report_reader=owner_report

# BEGIN qualified project closeout observer
"""Finite owner-only current project Due observation; no recovery or mutation."""
from datetime import datetime,timezone
from herzchen.contracts import ResourceRef
FIELDS={name:(name,)for name in('schedule_id','project_ref','owner','interval_seconds','stop_state')}
def observe_project_schedules(owner,project_id):
 if not isinstance(project_id,str)or not project_id:raise PermissionError('exact project identity required')
 actor=owner.owner_actor.actor;reader=owner.store.consumer()
 refs=reader.find_identity_refs(kind='otto.due-record',payload_matches={('project_ref',):project_id})
 coverage={'authority':owner.store.authority,'project_id':project_id,'source':'complete project-scoped public Due list','record_count':len(refs),'observed_at':datetime.now(timezone.utc).isoformat(),'complete':False}
 unavailable={'mode':'unknown','pm_owned_schedule_ids':None,'unknown_ownership':True,'coverage':coverage,'shared_records':[],'records_modified':False,'provider_called':False}
 if len(refs)>100:return{**unavailable,'reason':'project Due metadata exceeds finite 100-record bound'}
 rows=reader.project_identity_fields_for_refs(list(refs),fields=FIELDS,max_refs=100,max_projection_bytes=32768)
 if len(rows)!=len(refs)or any(r['state']!='available'for r in rows):return{**unavailable,'reason':'project Due metadata missing, stale or over bound'}
 owned=[];shared=[];unknown=False
 for ref,row in zip(refs,rows):
  f=row['fields'];present=row.get('present')or{}
  if f.get('schedule_id')!=ref.id or f.get('project_ref')!=project_id or not all(present.get(k)for k in FIELDS)or not isinstance(f.get('owner'),str)or f.get('stop_state')not in{'active','stopped','completed'}or(f['interval_seconds']is not None and(type(f['interval_seconds'])is not int or f['interval_seconds']<=0)):
   unknown=True;continue
  # Keep the maintained PM recurring-schedule ownership contract. Finite
  # native turns are preserved; this observation never settles/captures them.
  recurring=f['interval_seconds']is not None
  if recurring and f['owner']!=actor:unknown=True
  if recurring and f['owner']==actor and f['stop_state']!='completed':owned.append(ref.id)
  else:shared.append({'schedule_id':ref.id,'status':'preserved'})
 coverage['complete']=not unknown
 return{'mode':'unknown'if unknown else('owned-schedule'if owned else'no-owned-schedule'),'pm_owned_schedule_ids':owned,'unknown_ownership':unknown,'coverage':coverage,'shared_records':shared,'records_modified':False,'provider_called':False}
def compose_closeout_observer(owner,expected_project_id):
 def observe(project_id):
  if project_id!=expected_project_id:raise PermissionError('closeout observer project differs from fixed view')
  return observe_project_schedules(owner,project_id)
 return observe

# END qualified project closeout observer
# BEGIN qualified terminal fixed view
"""Read qualification for canonical completed fixed views; no live admission."""
def qualify_terminal_project_view(owner,state,due,terminal_projection):
 from herzchen.contracts import ResourceRef
 from otto.portfolio.operating_setup import authenticated_adoption_ancestor
 project=owner.graph.get(state['project_ref'])
 if project.ref.to_dict()!=state['project_ref']:raise PermissionError('fixed current project differs')
 if project.payload.get('lifecycle')!='completed':return None
 terminal=terminal_projection(due)
 if terminal is None:return None
 current=owner.assignments.get(state['assignment_ref'])
 target=due.get('target')or{};same=lambda a,b:isinstance(a,dict)and isinstance(b,dict)and all(a.get(k)==b.get(k)for k in('authority','kind','id'))
 digest=(due.get('completion_evidence')or{}).get('result_digest')
 if (current.ref.to_dict()!=state['assignment_ref']or current.principal!=state['manager']or current.role!='manager'
  or current.generation!=state['manager_generation']or current.status.value=='cancelled'
  or not same(current.scope.to_dict(),state['project_ref'])or due.get('role')!='manager'
  or due.get('schedule_id')!=state['schedule_id']or due.get('recipient')!=current.principal
  or due.get('generation')!=current.generation or not same(target.get('project_ref'),state['project_ref'])
  or target.get('assignment_ref')!=due.get('assignment_ref')
  or not isinstance(digest,str)or len(digest)!=64 or any(x not in '0123456789abcdef'for x in digest)
  or not isinstance(due.get('assignment_ref'),dict)
  or not authenticated_adoption_ancestor({'ref':current.ref.to_dict(),'principal':current.principal,'role':current.role,
    'generation':current.generation,'payload':current.payload},due['assignment_ref'],owner.graph.reader)):
  raise PermissionError('historical completed fixed manager binding/capture differs')
 control=project.payload.get('lifecycle_control')or{};close=control.get('close_request')or{}
 transition=control.get('transition')or{};reconciliation=control.get('reconciliation')or{}
 observation=reconciliation.get('observation')or{};coverage=observation.get('coverage')or{}
 evidence=control.get('terminal_evidence')or{}
 if (not same(close.get('project_ref'),state['project_ref'])or not same(close.get('manager_assignment'),state['assignment_ref'])
  or close.get('generation')!=current.generation or not isinstance(close.get('report_ref'),dict)
  or transition.get('action')!='pm-reconcile-no-owned-schedule' or not same(transition.get('project_ref'),state['project_ref'])
  or reconciliation.get('status')!='reconciled'or reconciliation.get('mode')!='no-owned-schedule'
  or observation.get('mode')!='no-owned-schedule'or observation.get('unknown_ownership')is not False
  or observation.get('pm_owned_schedule_ids')!=[]or coverage.get('project_id')!=project.ref.id or coverage.get('complete')is not True
  or not isinstance(observation.get('shared_records'),list)or len(observation['shared_records'])>100
  or any(not isinstance(item,dict)or item.get('status')!='preserved'for item in observation['shared_records'])
  or any(not isinstance(evidence.get(name),dict)or evidence[name].get('status')not in{'passed','verified','qualified'}for name in('acceptance','publication','remote','runtime'))):
  raise PermissionError('terminal fixed project lacks complete canonical close/reconciliation proof')
 reader=owner.graph.reader
 key=close.get('request_id');report_receipt=reader.get_receipt(key+':report')if isinstance(key,str)else None
 key=transition.get('request_id');receipt=reader.get_receipt(key)if isinstance(key,str)else None
 if (report_receipt is None or report_receipt.status.value!='committed' or report_receipt.operation!='work.report.append'
  or report_receipt.result_ref is None or not same(report_receipt.result_ref.to_dict(),close['report_ref'])
  or reader.get_identity_ref(ResourceRef.from_dict(close['report_ref']))!=report_receipt.result_ref
  or receipt is None or receipt.status.value!='committed'or receipt.operation!='work.lifecycle.transition'
  or receipt.target!=ResourceRef.from_dict(transition['project_ref'])or receipt.result_ref is None):
  raise PermissionError('terminal fixed project close receipts differ')
 chain=None
 if receipt.result_ref!=project.ref:
  from otto.portfolio.native5_shared_compose import _supervision_only_project_chain
  current_root=owner.assignments.get(state['orchestrator_assignment_ref'])
  relation=project.payload.get('metadata',{}).get('otto_orchestrator',{})
  if (current_root.ref.to_dict()!=state['orchestrator_assignment_ref']
   or current_root.role!='orchestrator'or relation.get('assignment_ref')!=current_root.ref.to_dict()
   or relation.get('generation')!=current_root.generation):raise PermissionError('terminal fixed project current supervisor differs')
  chain=_supervision_only_project_chain(owner,current_root,receipt.result_ref.to_dict(),project.ref.to_dict())
 return {'terminal_read_qualified':True,'terminal_close_project_ref':receipt.result_ref.to_dict(),'supervision_only_refresh':chain,'current_authority_resources_qualified':True,'current_context_qualified':False,
  'execution_contract_evaluated':False,'historical_occurrence':terminal,'canonical_project_ref':project.ref.to_dict(),
  'qualification':'completed project and finalized original capture; never new executable context','provider_called':False}

# END qualified terminal fixed view
# BEGIN qualified retained per-view resource context
def selected_view_context(manifest,key,state):
 contexts=manifest.get('view_resource_contexts',{})
 if not isinstance(contexts,dict)or not set(contexts)<={'vision','astrid','retention','claude'}:raise PermissionError('finite retained view context scope differs')
 context=contexts.get(key)
 if context is None:
  return {'pack_hashes':manifest['pack_hashes'],'source_commit':manifest.get('adopted_context_source_commit',manifest['source_commit']),
   'pack_relative_root':manifest['selected_pack_materialization']['relative_root'],'pack_source_commit':manifest['selected_pack_materialization']['source_commit']}
 if set(context)!={'project_identity','selected_pack_ref','native_evidence_selection_ref','pack_hashes','source_commit','pack_relative_root','pack_source_commit'}:raise PermissionError('retained view context fields differ')
 if {k:state['project_ref'][k]for k in ('authority','kind','id')}!=context['project_identity']or state['selected_pack_ref']!=context['selected_pack_ref']or state['native_evidence_selection_ref']!=context['native_evidence_selection_ref']:raise PermissionError('retained view resource pins differ')
 root=Path(context['pack_relative_root'])
 if root.is_absolute()or '..'in root.parts or len(root.parts)!=1:raise PermissionError('retained pack location escaped')
 if not isinstance(context['pack_hashes'],dict)or not 1<=len(context['pack_hashes'])<=256:raise PermissionError('retained pack hashes unbounded')
 return context

def verify_selected_context_files(controller,context):
 root=Path(context['pack_relative_root'])
 if root.is_absolute()or len(root.parts)!=1 or '..'in root.parts or (controller/root).is_symlink():raise PermissionError('selected physical pack escaped')
 pins=context['pack_hashes']
 if not isinstance(pins,dict)or not 1<=len(pins)<=256:raise PermissionError('selected physical pack count is unbounded')
 total=0
 for name,pin in pins.items():
  relative=Path(name)
  if relative.is_absolute()or '..'in relative.parts:raise PermissionError('selected physical file escaped')
  path=controller/root/relative
  if path.is_symlink()or not path.is_file()or not path.resolve().is_relative_to((controller/root).resolve()):raise PermissionError('selected physical file custody differs')
  size=path.stat().st_size;total+=size
  if size>4*1024*1024 or total>16*1024*1024:raise PermissionError('selected physical file verification bound exceeded')
  if hashlib.sha256(path.read_bytes()).hexdigest()!=pin:raise PermissionError('selected physical file hash differs')
# END qualified retained per-view resource context
# BEGIN qualified Onboarding adopted idle read
"""Exact completed Onboarding resource-adoption idle read; never admission."""
from herzchen.contracts import ResourceRef
from otto.attention import DueRecord
ADOPTION_KEY='owner-onboarding-delivery-482e601fef96-maintenance-v1:onboarding:adopt:assignment'
PROJECT_ID='project-de46d9be34be4cd8805397a2e542'
def qualify_adopted_idle_view(owner,state,due,terminal_projection,app):
 if state['project_ref']['id']!=PROJECT_ID or due['assignment_ref']==state['assignment_ref']:return None
 if (due.get('role')!='manager'or due.get('recipient')!=state['manager']or due.get('generation')!=state['manager_generation']
  or due.get('stop_state')!='completed'or due.get('completion_state')!='succeeded'or due.get('in_flight_request')is not None):return None
 terminal=terminal_projection(due)
 if terminal is None:raise PermissionError('completed adopted manager lacks original capture proof')
 current=app._manager_adoption_anchor(DueRecord.from_dict(due))
 if current.ref.to_dict()!=state['assignment_ref']or current.generation!=state['manager_generation']or current.principal!=state['manager']:raise PermissionError('current manager adoption anchor differs')
 receipt=owner.store.consumer().get_receipt(ADOPTION_KEY)
 if (receipt is None or receipt.operation!='work.assignment.adopt-resources'or receipt.target.to_dict()!=due['assignment_ref']or receipt.result_ref!=current.ref):raise PermissionError('exact resource-only assignment adoption receipt required')
 project=owner.graph.get(ResourceRef.from_dict(state['project_ref']));root=owner.assignments.get(ResourceRef.from_dict(state['root_help_binding']['assignment_ref']))
 relation=project.payload.get('metadata',{}).get('otto_orchestrator',{})
 if (project.ref.to_dict()!=state['project_ref']or root.ref.to_dict()!=state['root_help_binding']['assignment_ref']or root.generation!=state['root_help_binding']['generation']or root.principal!=owner.owner_actor.actor
  or root.role!='orchestrator'or relation.get('assignment_ref')!=root.ref.to_dict()or relation.get('generation')!=root.generation):raise PermissionError('current protected own-root supervision differs')
 return {'resource_adopted_idle_read_qualified':True,'current_authority_resources_qualified':True,
  'current_context_qualified':False,'execution_contract_evaluated':False,'historical_occurrence':terminal,
  'canonical_assignment_ref':current.ref.to_dict(),'adoption_receipt_key':ADOPTION_KEY,
  'qualification':'original completed capture plus exact canonical resource adoption; new execution requires a future qualified purpose',
  'provider_called':False,'retry':False}

# END qualified Onboarding adopted idle read
def validate_fixed_supervisor(owner,state,root):
 view_root=owner.assignments.get(state['orchestrator_assignment_ref']);supervisor=state['root_help_binding'];project=owner.graph.get(state['project_ref']);relation=project.payload.get('metadata',{}).get('otto_orchestrator',{})
 if (view_root.ref.to_dict()!=state['orchestrator_assignment_ref']or view_root.role!='orchestrator'or getattr(view_root.status,'value',view_root.status)=='cancelled'or identity(view_root.scope.to_dict())!=identity(root.scope.to_dict())or view_root.principal!=supervisor['principal']or view_root.generation!=supervisor['generation']or view_root.ref.to_dict()!=supervisor['assignment_ref']or view_root.session!=supervisor['conversation_ref']or relation.get('assignment_ref')!=view_root.ref.to_dict()or relation.get('generation')!=view_root.generation or identity(supervisor['project_ref'])!=identity(state['project_ref'])):raise PermissionError('fixed view current canonical supervisor differs')
 return view_root

def completed_terminal_projection(due):
 # Only a durable, already finalized successful occurrence is read without
 # authorizing its historical assignment under a newer BASE. No settlement,
 # admission or provider effect occurs; every unresolved occurrence stays on
 # the maintained recovery path and conservative capacity fence.
 evidence=due.get('completion_evidence')or{}
 if due.get('stop_state')!='completed' or due.get('completion_state')!='succeeded' or due.get('in_flight_request')is not None or evidence.get('schema')!='otto.role-result.v1' or not isinstance(evidence.get('result_digest'),str) or not evidence['result_digest']:
  return None
 return {'outcome':'historical-completed','schedule_id':due['schedule_id'],'assignment_ref':due['assignment_ref'],'generation':due['generation'],'due_version':due['version'],'completion_evidence':evidence,'provider_called':False,'retry':False}

def unresolved_terminal_projection(due):
 # Retained UNKNOWN is not recovery permission. Startup may restore its exact
 # conservative fence under a later same-project resource adoption, without
 # accepting, rebinding, retrying or finalizing the historical occurrence.
 attempt=(due.get('host_evidence')or{}).get('gateway_attempt')
 if not isinstance(attempt,dict):return None
 result=attempt.get('result')
 if not isinstance(result,dict) or result.get('outcome')!='unknown' or due.get('completion_state')not in {'none','unknown'}:return None
 return {'outcome':'historical-UNKNOWN-held','schedule_id':due['schedule_id'],'assignment_ref':due['assignment_ref'],'generation':due['generation'],'due_version':due['version'],'original_result_digest':result.get('result_digest'),'conservative_hold_preserved':True,'provider_called':False,'retry':False}

def held_view_qualification(service,*,state,source_commit):
 """Availability is not an execution-role authority qualification."""
 return {'project_ref':state['project_ref'],'assignment_ref':state['assignment_ref'],
  'schedule_id':service._current_manager_schedule(),'source_commit':source_commit,
  'current_context_qualified':False,'qualification':'unqualified-dispatch-held',
  'reason':'task execution-role readiness is deferred while service dispatch is held; no task authority changed',
  'provider_called':False}

_startup_store_observation={}
def observe_startup_store(store,phase):
 global _startup_store_observation
 observation={'phase':phase,'admission_completed':True,'admission_report':dict(getattr(store,'admission_report',{})), 'store_closed':False}
 try:observation['source_next_append']=store.source_next_append
 except Exception as error:observation['source_next_append']=None;observation['telemetry_error']=type(error).__name__
 _startup_store_observation=observation
 return observation

def close_startup_store(store,*,seal=False,phase='owner-close'):
 observation=observe_startup_store(store,phase)
 try:store.close(seal=seal)
 except BaseException:
  observation.update(store_closed=False,seal_requested=seal,close_outcome='unverified')
  print(json.dumps({'schema':'otto.owner-startup-store-observation.v1',**observation}),flush=True)
  raise
 observation.update(store_closed=True,seal_requested=seal,close_outcome='closed',
  sealed=getattr(store,'admission_report',{}).get('seal')=='written',
  sealed_source_next_append=getattr(store,'admission_report',{}).get('sealed_source_next_append'))
 print(json.dumps({'schema':'otto.owner-startup-store-observation.v1',**observation}),flush=True)

class StartupStopped(RuntimeError):
 """Explicit owner stop at a transaction-free composition boundary."""

_startup_phase_started=None
_startup_phase_records=[]
_closed_owner_qualification=contextvars.ContextVar("closed_owner_qualification",default=False)

def startup_checkpoint(phase):
 global _startup_phase_started
 if (C/'manager-service-stop').exists() and not _closed_owner_qualification.get():raise StartupStopped('explicit stop before '+phase)
 now=time.monotonic();elapsed=None if _startup_phase_started is None else now-_startup_phase_started
 _startup_phase_started=now
 record={'schema':'otto.owner-startup-phase.v1','phase':phase,'pid':os.getpid(),'monotonic':now,'elapsed_since_previous_phase_seconds':elapsed,'provider_called':False}
 _startup_phase_records.append(record)
 print(json.dumps(record),file=sys.stderr,flush=True)

def write_startup_refusal(error):
 # This does not claim canonical composition had no effects. It records only
 # refusal before host.start/native admission, for the retained supervisor exit.
 manifest=base.verify_install()
 target=C/('owner-startup-refusal-'+str(os.getpid())+'.json')
 value={'schema':'otto.owner-startup-refusal.v1','pid':os.getpid(),
  'source_commit':manifest['source_commit'],'manifest_sha256':hashlib.sha256((C/'runtime-manifest.json').read_bytes()).hexdigest(),
  'native_admission_started':False,'canonical_effects':'preserved-not-inferred',
  'error':{'code':type(error).__name__,'message':str(error)[:4096]},
  'startup_store_observation':{**_startup_store_observation,'phase_timings':list(_startup_phase_records)}}
 raw=(json.dumps(value,sort_keys=True)+'\n').encode()
 fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())

from otto.portfolio.project_services import ProjectServices
class CurrentProjectServices(ProjectServices):
 def install(self):
  if self.host.dispatch_held:return self.install_inert(checkpoint=startup_checkpoint)
  return super().install()
 def reconcile_startup(self):
  if self.host._threads:raise RuntimeError('startup requires closed owner custody')
  schedules=set()
  for service in self.services.values():schedules.update(service._known_schedule_ids(service.server.state))
  files=list(self.host.directory.glob('request-*.json'))
  if len(files)>128:raise ValueError('retained command set exceeds finite bound')
  for path in files:
   request=read(path)
   if request.get('command')in self._retained:schedules.add(request['schedule_id'])
  if len(schedules)>128:raise ValueError('known occurrence set exceeds finite bound')
  rows=[]
  for schedule in sorted(schedules):
   startup_checkpoint('occurrence-reconciliation')
   service,due=self._due(schedule,hydrate_native=False) # exact original assignment/project ownership
   if due['stop_state']!='completed'or due['completion_state']!='succeeded':
    service,due=self._due(schedule)
   app=service._execution(principal=due['recipient'],model=due['requested_model'],reasoning=due['requested_reasoning'],evidence_id='startup-'+schedule,selection=(due['target'].get('launch_request')or{}).get('selection'))
   try:
    from retired_original_view_hold import qualify as qualify_retired
    retired=qualify_retired(app,due)
    terminal=retired or completed_terminal_projection(due) or unresolved_terminal_projection(due)
    result=terminal if terminal is not None else app.recover(schedule_id=schedule,execute=False)
   finally:
    # Existing successful terminal custody needs typed status/identity, not
    # full native Evidence bodies. Every unresolved proof stays fully read.
    thin=due['stop_state']=='completed'and due['completion_state']=='succeeded'
    self.host.restore_execution(app,app._read(schedule,hydrate_native=not thin))
   rows.append({'schedule_id':schedule,'outcome':result['outcome'],'historical_terminal_projection':terminal is not None and retired is None,'execution_held':retired is not None})
  return {'outcome':'reconciled','occurrences':rows,'capacity_holds':list(self.host._capacity_holds),'provider_called':False}

def compose(*, hold_dispatch=False):
 global _startup_store_observation,_startup_phase_records,_startup_phase_started
 _startup_store_observation={'admission_completed':False,'store_closed':None};_startup_phase_records=[];_startup_phase_started=None
 startup_checkpoint('composition')
 from herzchen.contracts import ResourceRef
 from otto.attention import issue_store_due_record_port,due_record_contribution
 from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
 from otto.portfolio.herzchen_binding import ProjectReadGrant
 from otto.portfolio.execution_host import ExecutionHost
 from otto.portfolio.manager_journey_service import ManagerJourneyService
 from otto.portfolio.project_services import ProjectServices
 from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress
 from otto.portfolio.owner_completion import after_owner
 controllers={'onboarding':C,'vision':VC,'astrid':PC}
 for key,path in {'retention':C.parent.parent/'otto-retention-cleanup-20261011/controller','claude':C.parent.parent/'otto-claude-code-validation-20261011/controller'}.items():
  if(path/'canonical-state.json').exists():controllers[key]=path
 states={k:read(p/'canonical-state.json')for k,p in controllers.items()}
 fixed_view_states=states.copy();fixed_view_controllers=controllers.copy()
 manifest=base.verify_install()
 startup_checkpoint('store-open')
 from otto.portfolio.native5_compose_packet import load_packet
 native5_packet=load_packet(C,manifest=manifest,main_state=states['onboarding'])
 if native5_packet is not None:
  from otto.portfolio.native5_shared_compose import FIVE_IDS
  for ident in FIVE_IDS:
   states[ident]=native5_packet['state_map']['states_by_project'][ident]
   controllers[ident]=native5_packet['state_map']['controllers_by_project'][ident]
 s=states['onboarding'];store,b,initial,oldport=base.composition(s,admission='clean-close',should_stop=lambda:(C/'manager-service-stop').exists() and not _closed_owner_qualification.get())
 host=None
 observe_startup_store(store,'admission-complete')
 try:
  startup_checkpoint('owner-construction')
  root=initial.assignments.get(s['orchestrator_assignment_ref'])
  if native5_packet is None:
   if root.ref.to_dict()!=s['orchestrator_assignment_ref']:raise PermissionError('current ROOT pin differs')
  else:
   packet_root=native5_packet['state_map'].get('root_assignment_ref')
   if (identity(root.ref.to_dict())!=identity(s['orchestrator_assignment_ref'])
       or root.ref.to_dict()!=packet_root
       or root.generation!=native5_packet['state_map'].get('root_generation')):
    raise PermissionError('Native5 packet must match the exact current post-sync root revision and generation')
  owner=PortfolioOwnerBootstrap(store,binding=b,owner_actor=s['owner'],portfolio_ref=root.scope,main_assignment_ref=root.ref,expected_main_principal=s['owner'],project_read_grant=ProjectReadGrant(b.authenticated_actor(s['owner']),tuple(v['project_ref']['id']for v in states.values()),str(PRIVATE/'shared-host-start-grants.json'),'shared-host-current-v1'))
  native5_state_map=None
  if native5_packet is not None:
   from otto.portfolio.native5_shared_compose import merge_packets_for_shared_compose
   merged=merge_packets_for_shared_compose(fixed_view_states,fixed_view_controllers,
    packet_document=native5_packet['result'],owner=owner,installed_manifest=manifest)
   states=merged['states'];controllers=merged['controllers'];native5_state_map=merged;s=states['onboarding']
  bodies=base.native_body_capability(s,owner,store)
  port=issue_store_due_record_port(store.domain_handler((due_record_contribution(),)),owner.owner_actor,native_bodies=bodies)
  common=base.Server(owner,port,s,b,store)
  # Startup-only public managed discovery. Restore Evidence's original source
  # state before any role/native evidence composition or heartbeat thread.
  selection_ref=states['vision'].get('vision_resource_selection_ref')
  if not selection_ref:raise PermissionError('canonical Vision selection must be adopted before startup')
  expected=owner.content.read(ResourceRef.from_dict(selection_ref))['content']
  from herzchen.packs.authoring import read_managed_pack
  before_source_state=os.environ.get('ASTRID_SOURCE_STATE')
  try:
   os.environ['ASTRID_SOURCE_STATE']=str(C/'evidence/vision-managed-installation/source-state.json')
   vision_managed=read_managed_pack('vision',project_root=base.ASTRID_DEPENDENCY_ROOT)
  finally:
   if before_source_state is None:os.environ.pop('ASTRID_SOURCE_STATE',None)
   else:os.environ['ASTRID_SOURCE_STATE']=before_source_state
  from otto.portfolio.owner_vision import OwnerVision
  common.vision=OwnerVision(owner=owner,editor=common.document_editor,managed_pack=vision_managed,expected_selection=expected)
  host=ExecutionHost(directory=C/'manager-ipc',handler=lambda request:None,owner_path=C/'manager-status-owner.json',socket_path=base.native_caller_socket_path(),owner_file_compatibility=True,bounded_transports=True,manager_turn_limit=3)
  if hold_dispatch:host.hold_admission()
  views={};servers={};qualified={}
  for key,state in states.items():
   startup_checkpoint('view-'+key)
   controller=controllers[key];run=Path(state.get('registered_run_directory')or state.get('run_directory')or controller.parent);work=Path(state['source_path']);manager=state['manager']
   validate_fixed_supervisor(owner,state,root)
   policy=owner.content.read(ResourceRef.from_dict(state['bounded_host_policy_ref']))['content']
   if (policy.get('manager_max'),policy.get('productive_worker_max'),policy.get('total_native_max'))!=(3,2,3):raise PermissionError('current adopted shared capacity differs')
   assignment=owner.assignments.get(state['assignment_ref'])
   if assignment.ref.to_dict()!=state['assignment_ref']or assignment.principal!=manager or assignment.generation!=state['manager_generation']or identity(assignment.scope.to_dict())!=identity(state['project_ref']):raise PermissionError('fixed view manager binding differs')
   view_context=selected_view_context(manifest,key,state)
   verify_selected_context_files(C,view_context)
   pack=owner.content.read(ResourceRef.from_dict(state['selected_pack_ref']))['content']
   if pack['file_sha256']!=view_context['pack_hashes']:raise PermissionError('view selected pack bytes differ')
   selection=owner.content.read(ResourceRef.from_dict(state['native_evidence_selection_ref']))['content']
   if selection['runtime_source_commit']!=view_context['source_commit']or selection['payload_root']!=str(base.NATIVE_EVIDENCE_ROOT):raise PermissionError('view body selection differs')
   # Same owner-issued source and pins, independently checked in each current adopted BASE.
   guide=owner.content.read(ResourceRef.from_dict(state['guide_ref']))['content']
   from herzchen.content.instructions import validate_instruction_content
   if state['native_evidence_selection_ref']not in guide['supporting_refs']or not any(x['resource_ref']==state['guide_ref']and x['content_digest']==validate_instruction_content(guide)and x['required']for x in assignment.payload['resource_adoptions']):raise PermissionError('view current BASE selection is not adopted')
   server=object.__new__(base.Server);server.__dict__.update(common.__dict__);server.state=state;server.execution_host=host;server.manager_turn_settled=threading.Event();server.native_bodies=bodies
   server._save_state=lambda state=state,controller=controller:dump(controller/'canonical-state.json',state)
   from otto.portfolio.help_delivery import BoundHelpDelivery
   from otto.portfolio.owner_issue_loop import OwnerIssueReaders
   from s06_root_reply import RootStdinReply
   server.help_delivery=BoundHelpDelivery(readers=OwnerIssueReaders(owner.consumer_operations(),port),interim_supervision=state['root_help_binding'])
   server.portfolio=owner.portfolio(due_port=port,issue_delivery=server.help_delivery)
   server.root_reply=RootStdinReply(binding=state['root_help_binding'],authenticated_actor=b.authenticated_actor(state['root_help_binding']['principal']),delivery=server.help_delivery,portfolio=server.portfolio,directory=C/'manager-ipc')
   def execution(*,principal,model,reasoning,evidence_id,server=server,run=run,work=work,controller=controller,manager=manager,view_context=view_context,native5_view=(state['project_ref']['id'] in (native5_packet['state_map']['prepared_native_five_packets'] if native5_packet is not None else {}))):
    from otto.agents.herzchen_adapter import HerzchenCodexAdapter
    from otto.agents.codex_host_reader import CodexAppServerThreadReader
    class Adapter(HerzchenCodexAdapter):
     adapter_identity='otto.usage.installed-codex-cli.v1'
     @staticmethod
     def render_verified_invocation(brief,digest_value,request,*,model_projection=None):
      # Fixed physical selection; canonical brief and context digest are preserved.
      base.verify_install();packroot=C/view_context['pack_relative_root']
      mapping={str(work/n):str(packroot/n)for n in view_context['pack_hashes']}
      return '<otto-selected-pack-location>\n'+json.dumps({'path_mapping':mapping,'source_commit':view_context['pack_source_commit'],'instruction':'Read adopted skills/resources from these immutable installed paths; candidate package contents are implementation only.'},sort_keys=True)+'\n</otto-selected-pack-location>\n'+HerzchenCodexAdapter.render_verified_invocation(brief,digest_value,request,model_projection=model_projection)
    # Native5 context write access must match its prepared owner factory:
    # the project workspace plus the shared manager IPC, never the controller
    # tree that contains canonical state, policy, and owner receipts. Preserve
    # the already-qualified writable roots for the original four views.
    adapter_roots=((str(work),str(C/"manager-ipc")) if native5_view else ((str(controller),str(C/"manager-ipc")) if controller!=C else (str(controller),)))
    adapter=Adapter(owner=principal,source=str(run),worktree=str(work),launcher=base.LAUNCHER,requested_model=model,requested_reasoning=reasoning,trusted_thread_reader=CodexAppServerThreadReader(launcher=base.LAUNCHER,timeout_seconds=30),host_context_path=str(controller/'evidence'/(evidence_id+'-host.jsonl')),require_host_context=True,writable_roots=adapter_roots,native_process_observer=server.native_callers.observe,native_caller_socket=str(base.native_caller_socket_path()))
    return owner.execution_application(due_port=port,adapter=adapter,manager_actor=manager,issue_delivery=server.help_delivery,native_bodies=server.native_bodies)
   server._execution=execution
   def handle(request,server=server,state=state,controller=controller,work=work):
    command=request.get('command')
    if command=='start-manager':
     if request!={'command':'start-manager','schedule_id':state['schedule_id']}:raise PermissionError('exact owner-issued initial occurrence required')
     app=server._execution(principal=state['manager'],model=state['requested_model'],reasoning=state['requested_reasoning'],evidence_id='manager-current')
     def captured(result):
      due=port.read_due(state['schedule_id']);attempt=(due.get('host_evidence')or{}).get('gateway_attempt')or{};actual=attempt.get('result')or{};session=actual.get('physical_session_id')or attempt.get('physical_session_id');state['manager_launch']={'outcome':result.get('outcome'),'physical_session_id':session,'observed_model':actual.get('observed_model'),'observed_reasoning':actual.get('observed_reasoning'),'completion_state':due['completion_state']}
      if due['completion_state']=='succeeded'and isinstance(session,str):state['manager_continuation']={'schedule_id':due['schedule_id'],'native_session_id':session,'outcome':'succeeded','requested_continuation':{'settled_schedule_id':due['schedule_id']}}
      server._save_state();dump(controller/'evidence/manager-current-launch-result.json',result);server.manager_turn_settled.set();return result
     server.manager_turn_settled.clear();return after_owner(app.start(schedule_id=state['schedule_id']),captured)
    if command=='report':
     alias=request['task']
     if alias not in state['task_refs']:raise ValueError('unknown current view task')
     from datetime import datetime,timezone
     from otto.portfolio.owner_readers import json_value
     value={'schema':'otto.manager-progress.v1','project_ref':state['project_ref'],'task_alias':alias,'task_ref':state['task_refs'][alias],'summary':request['summary'],'next_action':request['next_action'],'continue_requested':request.get('continue_project')is True,'logical_request_key':request['request_key'],'recorded_at':datetime.now(timezone.utc).isoformat()}
     result=owner.assignments.command_port.append_report(ResourceRef.from_dict(state['assignment_ref']),value,expected_generation=state['manager_generation'],logical_request_key=request['request_key'],actor=b.authenticated_actor(state['manager']))
     return{'outcome':'committed','report':json_value(result),'continuation_requested':value['continue_requested'],'provider_called':False}
    if command=='commit':
     from otto.portfolio.execution_operations import commit_local_checkpoint
     return commit_local_checkpoint(work,request['paths'],message=request['message'])
    raise ValueError('unsupported view fallback command')
   server.handle=handle
   service=ManagerJourneyService(server=server,host=host,run_path=run,workspace=work,policy=state['assessment_policy'],orchestrator_principal=state['root_help_binding']['principal'],observe_schedules=compose_closeout_observer(owner,state['project_ref']['id']),help_reply_authorizer=server.root_reply.authorize,authoring_authorizer=common.owner_authoring.authorize,external_execution_authorizer=common.owner_execution.authorize,external_execution_policy=state.get('external_execution_policy'),delegation_policy=state.get('delegation_policy'))
   server._execution=service._execution;views[key]=service;servers[key]=server
   if key=='onboarding':
    from otto.portfolio.retention_owner_read import RetentionOwnerRead
    storage_receipt=None
    for receipt_path in(C/'evidence/retention-closed-owner-storage-diagnostics.json',C/'evidence/retention-closed-storage-partial-cancelled.json'):
     if not receipt_path.exists():continue
     if receipt_path.is_symlink():raise PermissionError('retained storage observation must be a regular owned file')
     with receipt_path.open('rb')as receipt_stream:receipt_bytes=receipt_stream.read(65537)
     if len(receipt_bytes)>65536:continue
     receipt_value=json.loads(receipt_bytes)
     if isinstance(receipt_value,dict)and receipt_value.get('schema')in{'otto.closed-storage-diagnostic-receipt.v1','otto.owner-storage-diagnostic-partial.v1'}:
      storage_receipt=receipt_value;break
    if server.native_bodies.actor!=owner.owner_actor:raise PermissionError('retention preview backend owner differs')
    service.retention_owner_read=RetentionOwnerRead(service,storage_receipt=storage_receipt,evidence_handler=server.native_bodies.evidence)
   if hold_dispatch:
    qualified[key]=held_view_qualification(service,state=state,source_commit=manifest['source_commit'])
    continue
   from otto.attention import DueRecord
   app=service._execution(principal=manager,model=state['requested_model'],reasoning=state['requested_reasoning'],evidence_id='fixed-view-preflight')
   from retired_original_view_hold import qualify as qualify_retired, fence as fence_retired
   due=port.read_due(state['schedule_id'],hydrate_native=False)
   if due['stop_state']!='completed'or due['completion_state']!='succeeded':
    due=port.read_due(state['schedule_id'])
   context_hold=qualify_retired(app,due)
   if context_hold is not None:fence_retired(service,context_hold)
   if not hold_dispatch and due['stop_state']=='active'and(due.get('host_evidence')or{}).get('gateway_attempt')is None:
    prepared=app.recover(schedule_id=state['schedule_id'],execute=False)
    due=port.read_due(state['schedule_id'])
    if prepared['outcome']!='prepared':
     from prepared_context_hold import qualify,held_start
     context_hold=qualify(owner,state,due,prepared,view=key)
     # Fence only this exact original schedule; maintain all normal guards
     # for any separately authorized future current-context occurrence.
     original_execution=service._execution
     def held_execution(*args,_execution=original_execution,_hold=context_hold,**kwargs):
      application=_execution(*args,**kwargs);original_start=application.start
      def start(*args,**kwargs):
       schedule=kwargs.get('schedule_id')or(args[0]if args else None)
       return held_start(_hold)if schedule==_hold['schedule_id']else original_start(*args,**kwargs)
      application.start=start;return application
     service._execution=held_execution;server._execution=held_execution
     server.state['execution_hold']=context_hold

   if due['target'].get('native_adapter')!=app.native_adapter_identity():raise PermissionError('fixed view prepared adapter differs from selected runtime before admission')
   terminal_view=qualify_terminal_project_view(owner,state,due,completed_terminal_projection)
   if terminal_view is None:terminal_view=qualify_adopted_idle_view(owner,state,due,completed_terminal_projection,app)
   if terminal_view is None:
    from prepared_context_hold import qualify_settled_idle
    terminal_view=qualify_settled_idle(owner,state,due,completed_terminal_projection)
   if context_hold is not None:
    qualified[key]={'project_ref':state['project_ref'],'assignment_ref':state['assignment_ref'],'schedule_id':state['schedule_id'],'source_commit':manifest['source_commit'],**context_hold}
   elif terminal_view is not None:
    qualified[key]={'project_ref':state['project_ref'],'assignment_ref':state['assignment_ref'],'schedule_id':state['schedule_id'],'source_commit':manifest['source_commit'],**terminal_view}
   else:
    readiness=app.runtime.prepare_execution_readiness(due=DueRecord.from_dict(due))
    from otto.portfolio.operating_setup import validate_execution_contract
    validate_execution_contract(readiness,due['profile'],execution_manager=True)
    from herzchen.adapters.host import workspace_delivery_contract
    roots=tuple(dict.fromkeys((os.path.realpath(app.runtime.adapter.worktree),*app.runtime.adapter.writable_roots)))
    if not workspace_delivery_contract(readiness['canonical_evidence']['mandate_instruction_contract']['instruction_contract'],due['profile'],due['role'],roots):raise PermissionError('fixed view declared workspace differs before initialization')
    qualified[key]={'project_ref':state['project_ref'],'assignment_ref':state['assignment_ref'],'schedule_id':state['schedule_id'],'current_context_qualified':True,'source_commit':manifest['source_commit'],'provider_called':False}
  from fixed_root_replies import FixedRootReplies
  replies=FixedRootReplies({key:server.root_reply for key,server in servers.items()})
  old_input=common.root_reply;old_publish=old_input.publish
  class OwnerInput:
   def publish(self,envelope):
    if isinstance(envelope,dict)and envelope.get('schema')in {common.owner_execution.schema,common.owner_authoring.schema}:return old_publish(envelope)
    return replies.publish(envelope)
   def serve_stdin(self,stream,emit):
    # Reuse the bounded stdin loop while dispatching to the fixed full binding.
    old_input.publish=self.publish
    return old_input.serve_stdin(stream,emit)
  common.root_reply=OwnerInput()
  grants=read(PRIVATE/'shared-host-start-grants.json')
  def owner_route(request):
   command=request.get('command')
   if command=='start-manager':
    handle=host.command_handle();token=handle.get('request_id')if isinstance(handle,dict)else None
    grant=grants.get(token)
    if not grant or request!=grant['request']or grant['view']not in views:raise PermissionError('original protected owner start grant required')
    state=states[grant['view']];current=owner.assignments.get(state['assignment_ref']);due=port.read_due(request['schedule_id'])
    if current.ref.to_dict()!=state['assignment_ref']or current.generation!=state['manager_generation']or due['assignment_ref']!=state['assignment_ref']or due['generation']!=state['manager_generation']or identity(due['target']['project_ref'])!=identity(state['project_ref']):raise PermissionError('owner-issued start bindings changed')
    return grant['view']
   if command=='respond-help':return replies.authorize_route(request)
   if command in{'owner-context','document-authoring','project-authoring','project-queue','vision'}:common.owner_authoring.authorize(request);return'onboarding'
   if command=='owner-execution':common.owner_execution.authorize(request);return'onboarding'
   raise PermissionError('unbound command is not an authenticated owner operation')
  router=CurrentProjectServices(views,owner_route=owner_route);native=NativeProcessCallerIngress(router.managed_caller_binding)
  for server in servers.values():server.native_callers=native
  host.caller_binding_reader=native
  startup_checkpoint('router-install')
  if hold_dispatch:
   reconciliation=router.install_inert(checkpoint=startup_checkpoint)
  else:
   reconciliation=router.install()
  startup_checkpoint('client-issuance')
  from otto.hostctl.config import load as load_host_installation
  from otto.hostctl.project_service import ProjectOwnerService
  installation=load_host_installation(Path('/Users/hannahomalley/.otto'))
  if installation.get('owner_composition',{}).get('kind')!='shared-project-services' or installation.get('max_active_manager_turns')!=3:raise PermissionError('exact shared host installation required')
  common.host_clients=ProjectOwnerService(installation,router=router)
  from scoped_client_service import ScopedViewClients
  if native5_state_map is not None and not hold_dispatch:
   from otto.portfolio.native5_shared_compose import FIVE_IDS
   for ident in FIVE_IDS:
    proof=qualified.get(ident)
    if proof is None or proof.get('current_context_qualified') is not True or proof.get('provider_called') is not False:
     raise PermissionError('all five Native5 current contexts must pass read/execution qualification before exact-nine issuance')
  common.scoped_clients=ScopedViewClients(owner=owner,host=host,views=views,controllers=controllers,private=PRIVATE,main_state=states['onboarding'],native5_state_map=native5_state_map,installed_manifest=manifest)
  from w0_current_view_join import attach as attach_W0
  qualified['claude-work-model-W0']=attach_W0(common,manifest=manifest)
  startup_checkpoint('composition-complete')
  observe_startup_store(store,'composition-complete')
  if hold_dispatch:
   startup_block={'source_commit':manifest['source_commit'],'manifest_sha256':hashlib.sha256((C/'runtime-manifest.json').read_bytes()).hexdigest(), 'pid':os.getpid(),'dispatch':'held','composition_source_next_append':store.source_next_append,'admission_report':dict(getattr(store,'admission_report',{})), 'phase_timings':list(_startup_phase_records), 'current_context_qualified':{k:v.get('current_context_qualified') for k,v in qualified.items() if isinstance(v,dict)}, 'context_qualifications':{k:{field:v.get(field) for field in ('current_context_qualified','refusal_reason','reason','qualification','provider_called') if field in v} for k,v in qualified.items() if isinstance(v,dict)}, 'held_capacity_effects':sorted(host._capacity_holds), 'business_reconciliation':'held','provider_called':False}
   bind_startup_readers(common,startup_block,store)
   host.hold_admission(startup_block)
  return store,host,common,qualified,reconciliation
 except BaseException:
  try:
   if host is not None:host.close()
  finally:close_startup_store(store,phase='composition-failed-close')
  raise

def compose_closed_task_qualification(*, authorization_receipt):
 """Run existing nonexecuting composition under Root's ordinary closed custody.

 No service/host thread is started. The explicit stop marker remains present.
 Existing recover(execute=False) semantics retain any canonical preparation;
 callers must measure effects, not infer zero from lack of provider dispatch.
 """
 path=Path(authorization_receipt)
 if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
  raise PermissionError('bounded existing human task authorization required')
 authorization=read(path)
 current=hashlib.sha256((C/'runtime-manifest.json').read_bytes()).hexdigest()
 if (authorization.get('schema')!='otto.human-authorized-task-resume-delivery.v1'
  or authorization.get('baseline_manifest')!=current
  or authorization.get('business_task_execution_authorized_after_qualification')is not True
  or authorization.get('UNKNOWN_replay_or_bypass_authorized')is not False
  or authorization.get('budget_resets_authorized')is not False):
  raise PermissionError('current task qualification authorization differs')
 # Reuse the already-qualified ordinary physical closure implementation.
 import importlib.util
 engine=C/'prepared/reliability-journey-20261013/startup-near-instant-20261014/terminal-migration-115047/deploy_runtime_v2.py'
 spec=importlib.util.spec_from_file_location('closed_task_qualification_guard',engine)
 module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 custody=module.defaults().physical_closed_custody()
 if custody.get('exit_returncode')!=0:raise PermissionError('ordinary current owner closure required')
 token=_closed_owner_qualification.set(True)
 try:return compose(hold_dispatch=False)
 finally:_closed_owner_qualification.reset(token)

def main():
 p=argparse.ArgumentParser();p.add_argument('--preflight',action='store_true');p.add_argument('--root-reply-stdin',action='store_true');p.add_argument('--hold-dispatch',action='store_true');args=p.parse_args()
 try:store,host,common,qualified,reconciled=compose(hold_dispatch=args.hold_dispatch)
 except StartupStopped:
  print(json.dumps({'outcome':'stopped-before-serving','provider_called':False}),flush=True);return
 except Exception as error:
  from herzchen.kernel.store import AdmissionStopped
  if isinstance(error,AdmissionStopped):
   print(json.dumps({'outcome':'stopped-before-serving','provider_called':False}),flush=True);return
  write_startup_refusal(error)
  print(json.dumps({'outcome':'startup-refused','error':type(error).__name__,'provider_called':False}),flush=True)
  raise SystemExit(78)
 served=False;normal_return=False
 try:
  if args.preflight:print(json.dumps({'outcome':'qualified-fixed-views','views':qualified,'startup':reconciled,'provider_called':False},default=str));return
  if(C/'manager-service-stop').exists():
   print(json.dumps({'outcome':'stopped-before-serving','provider_called':False}),flush=True);return
  host.start();served=True;common.host_clients.start_heartbeat()
  print(json.dumps({'outcome':'ready','pid':os.getpid(),'views':qualified,'startup':reconciled,'dispatch':'held' if args.hold_dispatch else 'open','provider_called':False},default=str),flush=True)
  if args.root_reply_stdin and not args.hold_dispatch:threading.Thread(target=common.root_reply.serve_stdin,args=(sys.stdin,lambda v:print(json.dumps(v),flush=True)),daemon=True).start()
  def idle():
   if not args.hold_dispatch:
    common.document_editor.poll_idle(common.owner_authoring)
    common.scoped_clients.poll()
   common.host_clients.poll()
  host.wait_until_stopped(lambda:(C/'manager-service-stop').exists()or common.host_clients.stop_requested(),idle_poll=idle)
  normal_return=True
 finally:
  if hasattr(common,'host_clients'):common.host_clients.begin_draining()
  orderly=False
  try:
   host.close()
   orderly=served and normal_return
  finally:
   close_startup_store(store,seal=orderly and getattr(store,'admission_report',{}).get('mode')=='clean-close')
  if hasattr(common,'host_clients'):common.host_clients.finalize_closed()
  print(json.dumps({'outcome':'closed'}),flush=True)
if __name__=='__main__':main()
