"""Interim run host adapter; all execution/review joins use the maintained installer.
No provider calls occur with --preflight. Root alone owns this process and Store.
"""
from pathlib import Path
import argparse, hashlib, json, os, sys, threading, time
HERE=Path(__file__).resolve().parent
if HERE.name=='prepared': HERE=HERE.parent
from native_caller_address import native_caller_socket_path
RUN=HERE.parent; WORK=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/work/integration-owner')
sys.path.insert(0,str(HERE/'runtime-source'))
# Trusted host dependency/source selection; not caller-provided configuration.
ASTRID_DEPENDENCY_ROOT=Path('/Users/hannahomalley/Developer/astrid-video/astrid-local/Astrid')
EVIDENCE_SOURCE_STATE=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-evidence-lifecycle-20261009/controller/evidence/d06-managed-installation/source-state.json')
sys.path.insert(1,str(ASTRID_DEPENDENCY_ROOT))
os.environ['ASTRID_SOURCE_STATE']=str(EVIDENCE_SOURCE_STATE)
NATIVE_EVIDENCE_ROOT=Path('/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010/native-evidence')
os.environ['HERZCHEN_IN_PROCESS_COMMAND_FALLBACK']='1'
AUTH='otto-project-operating-setup-20261005-owner-v1'
OWNER='otto-operating-setup-owner'; MANAGER='otto-onboarding-manager-1'
CREDENTIAL='local-otto-operating-setup-owner-credential-v1'
LAUNCHER='/Users/hannahomalley/.codex/packages/app-server-daemon/releases/0.161.0-aarch64-apple-darwin/bin/codex'
LAUNCHER_SHA='12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de'

def digest(raw): return hashlib.sha256(raw).hexdigest()
def write(path,value): path.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+'\n')
def domains():
 from herzchen.authoring import domain_contribution as authoring
 from herzchen.content import domain_contribution as content
 from herzchen.evidence.commands import domain_contribution as evidence
 from herzchen.content.packets import domain_contribution as packets
 from herzchen.domains.assessment import contribution as assessment
 from herzchen.domains.work import contributions
 from otto.attention import due_record_contribution
 from otto.portfolio.direction import contribution as direction, adoption_contribution as direction_adoption
 return tuple(sorted((*contributions(include_assignment_resources=True,include_orchestration=True),content(),packets(),authoring(),assessment(),due_record_contribution(),direction(),direction_adoption(),evidence()),key=lambda item:item.domain_id))

def verify_install():
 manifest=json.loads((HERE/'runtime-manifest.json').read_text())
 for name,want in manifest['files'].items():
  if digest((HERE/'runtime-source'/name).read_bytes())!=want:raise RuntimeError('installed runtime differs: '+name)
 for name,want in manifest['entrypoints'].items():
  if digest((HERE/name).read_bytes())!=want:raise RuntimeError('installed entrypoint differs: '+name)
 if digest(Path(LAUNCHER).read_bytes())!=LAUNCHER_SHA:raise RuntimeError('pinned native launcher differs')
 return manifest

def composition(state, *, admission="full", should_stop=None):
 from herzchen.kernel.store import Store
 from otto.attention import due_record_contribution,issue_store_due_record_port
 from otto.portfolio.herzchen_binding import HerzchenBindingConfig,ProjectReadGrant
 from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
 store=Store.open(state['store_path'],authority=AUTH,expected_domains=domains(),admission=admission,should_stop=should_stop)
 try:
  binding=HerzchenBindingConfig(AUTH,CREDENTIAL); actor=binding.authenticated_actor(OWNER)
  owner=PortfolioOwnerBootstrap(store,binding=binding,owner_actor=OWNER,project_read_grant=ProjectReadGrant(actor,(state['project_ref']['id'],),str(HERE/'canonical-state.json'),'operating-activation-v1'))
  store.configure_history_projection(batch_size=100)
  native_bodies=native_body_capability(state,owner,store)
  port=issue_store_due_record_port(store.domain_handler((due_record_contribution(),)),actor,native_bodies=native_bodies)
  return store,binding,owner,port
 except BaseException:store.close();raise

def native_body_capability(state,owner,store):
 actor=owner.binding.authenticated_actor(OWNER)
 from herzchen.contracts import ResourceRef
 from herzchen.evidence.model import load_evidence_pack
 from herzchen.evidence.commands import EvidenceCommandHandler
 from otto.agents.retained_native import RetainedNativeBodies
 selected=owner.content.read(ResourceRef.from_dict(state['native_evidence_selection_ref']))['content']
 # This fixed host capability is issued only from the current adopted BASE.
 # A caller cannot choose a source, payload root, identity or replacement pin.
 assignment=owner.assignments.get(state['assignment_ref'])
 if assignment.ref.to_dict()!=state['assignment_ref'] or assignment.generation!=state['manager_generation']:raise RuntimeError('current native Evidence assignment binding differs')
 guide=owner.content.read(ResourceRef.from_dict(state['guide_ref']))['content']
 from herzchen.content.instructions import validate_instruction_content
 if not any(x['resource_ref']==state['guide_ref'] and x['content_digest']==validate_instruction_content(guide) and x['required'] is True for x in assignment.payload['resource_adoptions']):raise RuntimeError('native Evidence BASE is not currently adopted')
 if state['native_evidence_selection_ref'] not in guide['supporting_refs']:raise RuntimeError('native Evidence selection is not an adopted supporting resource')
 pack=load_evidence_pack(project_root=WORK)
 if selected.get('schema')!='otto.owner.native-evidence-composition.v1' or selected.get('source')!=pack.source.to_dict() or selected.get('payload_root')!=str(NATIVE_EVIDENCE_ROOT) or selected.get('runtime_source_commit')!=verify_install().get('adopted_context_source_commit',verify_install()['source_commit']):raise RuntimeError('current native Evidence source selection differs')
 import stat
 for private in (NATIVE_EVIDENCE_ROOT.parent.parent,NATIVE_EVIDENCE_ROOT.parent,NATIVE_EVIDENCE_ROOT):
  mode=private.lstat()
  if not stat.S_ISDIR(mode.st_mode) or mode.st_uid!=os.getuid() or stat.S_IMODE(mode.st_mode)!=0o700:raise PermissionError('native Evidence root is not owner-protected')
 if NATIVE_EVIDENCE_ROOT.resolve().is_relative_to(WORK.resolve()) or NATIVE_EVIDENCE_ROOT.resolve().is_relative_to(HERE.resolve()):raise PermissionError('native Evidence body root overlaps native writable scope')
 handler=EvidenceCommandHandler(store,NATIVE_EVIDENCE_ROOT,pack=pack,adopted_pins=selected['pins'])
 # The owner's manager assessment verifies managed DAT evidence through this same handler.
 owner.evidence_payload_resolver=handler
 return RetainedNativeBodies(handler,actor)

def read_preflight(state,owner,port):
 from herzchen.contracts import ResourceRef
 from herzchen.content.instructions import validate_instruction_content
 from otto.portfolio.local_assessment_policy import compose_manager_assessment_state,LocalAssessmentPolicy
 from otto.agents.orchestrator_route import prepare_canonical_assignment_role_brief
 from otto.portfolio.operating_setup import validate_execution_contract
 from otto.portfolio.owner_readers import project_reader,task_reader,assignment_reader,mandate_reader
 cfg=json.loads((RUN/'run.yaml').read_text())
 state.update(compose_manager_assessment_state(state,config_path=RUN/'run.yaml'))
 assignment=owner.assignments.command_port.get(ResourceRef.from_dict(state['assignment_ref']))
 if assignment.ref.to_dict()!=state['assignment_ref'] or assignment.generation!=state['manager_generation'] or assignment.principal!=MANAGER:raise RuntimeError('current manager assignment differs')
 # Bootstrap locator resources are historical. The active Due is the exact
 # occurrence pin; resolve its refreshed task/mandate and adopted BASE through
 # the same maintained canonical readers used immediately before delivery.
 due=port.read_due(state['schedule_id'])
 if (not due or due['requested_model']!=cfg['roles']['coordinator']['model']
     or due['requested_reasoning']!=cfg['roles']['coordinator']['reasoning']
     or due['profile']!=state['requested_profile'] or due['assignment_ref']!=state['assignment_ref']
     or due['generation']!=state['manager_generation'] or due['role']!='manager'
     or due['recipient']!=MANAGER or due['manager_ref']!=OWNER or due['lifecycle_owner']!=OWNER
     or any(due['target']['project_ref'].get(k)!=state['project_ref'].get(k) for k in ('authority','kind','id'))):
  raise RuntimeError('prepared manager current model/context binding differs')
 target=due['target']
 for field,expected in (('requested_model',due['requested_model']),('requested_reasoning',due['requested_reasoning']),('requested_profile',due['profile'])):
  if target.get(field)!=expected:raise RuntimeError('prepared manager target '+field+' differs')
 operations=owner.portfolio(due_port=port).operations
 from otto.attention import DueRecord
 app=owner.execution_application(due_port=port,adapter=pinned_pack_adapter()(owner=state['manager'],source=str(RUN),worktree=str(WORK),launcher=LAUNCHER,requested_model=due['requested_model'],requested_reasoning=due['requested_reasoning'],require_host_context=True),manager_actor=state['manager'],native_bodies=native_body_capability(state,owner,owner.store))
 prepared=app.runtime.prepare_execution_readiness(due=DueRecord.from_dict(due))
 validate_execution_contract(prepared,due['profile'],execution_manager=True)
 guide_ref=prepared['canonical_evidence']['base_resource']['ref']
 guide=owner.content.read(ResourceRef.from_dict(guide_ref))['content']
 expected=validate_instruction_content(guide)
 if not any(r['resource_ref']==guide_ref and r['content_digest']==expected and r['required'] is True for r in assignment.payload.get('resource_adoptions',[])):raise RuntimeError('exact required BASE guide adoption missing')
 policy=LocalAssessmentPolicy.from_run_config(cfg['assessment_accounting'],state=state)
 # Withdrawn planning records remain history, without an acceptance budget.
 # Pending/completed obligations, exact current refs and project association
 # still require complete configured task-criterion coverage.
 active=[]
 for ref in state['task_refs'].values():
  task=owner.graph.reader.get_identity(ResourceRef(ref['authority'],ref['kind'],ref['id']))
  if task is None or task.ref.to_dict()!=ref or any(task.payload.get('project_ref',{}).get(k)!=state['project_ref'].get(k)for k in ('authority','kind','id')):raise RuntimeError('current task identity/project binding differs')
  if task.payload.get('lifecycle')!='withdrawn':active.append(ref)
 configured=[task.to_dict()for task,_ in policy.task_criterion_pairs]
 if len(configured)!=len(active)or {json.dumps(x,sort_keys=True)for x in configured}!={json.dumps(x,sort_keys=True)for x in active}:raise RuntimeError('exact current active task-criterion bindings required')
 for alias,ref in state['source_document_refs'].items():
  content=owner.content.read(ResourceRef.from_dict(ref))['content']
  path=RUN/alias
  if isinstance(content,str):expected_source_digest=digest(content.encode('utf-8'))
  elif isinstance(content,dict):
   if alias=='predecessor/usage-terminal.json' and content.get('kind')=='accepted-predecessor-terminal':
    # Preserve exact canonical JSON bytes pinned by this structured terminal resource.
    expected_source_digest=digest((json.dumps(content['bounded_terminal'],indent=2,sort_keys=True)+'\n').encode('utf-8'))
   else:expected_source_digest=content.get('sha256',content.get('source_sha256'))
  else:raise RuntimeError('unsupported adopted authoritative resource content: '+alias)
  if not isinstance(expected_source_digest,str) or digest(path.read_bytes())!=expected_source_digest:raise RuntimeError('adopted authoritative resource differs: '+alias)
 orchestrator=owner.assignments.command_port.get(ResourceRef.from_dict(state['orchestrator_assignment_ref']))
 if orchestrator.principal!=OWNER or orchestrator.role!='orchestrator':raise RuntimeError('accountable interim orchestrator missing')
 pack=owner.content.read(ResourceRef.from_dict(state['selected_pack_ref']))['content']
 pack_install=verify_selected_pack_materialization(state,pack)
 return {'outcome':'qualified','provider_called':False,'actual_installed_entrypoint':str(HERE/'operating_service.py'),'domains':[d.domain_id for d in domains()], 'project_ref':state['project_ref'],'manager_assignment_ref':assignment.ref.to_dict(),'schedule_id':due['schedule_id'],'current_guide_ref':guide_ref,'current_mandate_ref':target['mandate_ref'],'current_task_ref':target['task_ref'],'completed_task_readiness':prepared['canonical_evidence'].get('completed_task_readback'),'requested_model':due['requested_model'],'requested_reasoning':due['requested_reasoning'],'observed_native_identity':None,'required_task_criterion_pairs':len(policy.task_criterion_pairs),'duplicate_bootstrap_task_scopes':False,'help_transport':'interim public reports/receipts inspected by root; not automatic recipient delivery','advisor_policy':state['advisor_policy'],'selected_pack_materialization':pack_install}

def verify_selected_pack_materialization(state,pack):
 """Verify immutable adopted sources separately from the editable candidate."""
 manifest=json.loads((HERE/'runtime-manifest.json').read_text())
 install=manifest.get('selected_pack_materialization')
 if not isinstance(install,dict):raise RuntimeError('pinned selected pack materialization missing')
 if (install.get('selected_pack_ref')!=state['selected_pack_ref']
     or install.get('source_commit')!=pack.get('source_commit',state['source_baseline'])
     or not isinstance(install.get('relative_root'),str) or not install['relative_root'].startswith('selected-pack-source') or Path(install['relative_root']).name!=install['relative_root']
     or pack.get('file_sha256')!=manifest['pack_hashes']):
  raise RuntimeError('pinned selected pack canonical provenance differs')
 root=HERE/install['relative_root']
 expected=set(manifest['pack_hashes'])
 actual={str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()}
 if actual!=expected:raise RuntimeError('pinned selected pack file membership differs')
 for name,want in manifest['pack_hashes'].items():
  path=root/name
  if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise RuntimeError('pinned selected pack path escapes: '+name)
  if digest(path.read_bytes())!=want:raise RuntimeError('pinned selected pack resource differs: '+name)
 skill='policy-staging/megado/skill/SKILL.md'
 if digest(pack['skill_text'].encode())!=manifest['pack_hashes'][skill]:raise RuntimeError('canonical selected pack skill text differs')
 return {'selected_pack_ref':state['selected_pack_ref'],'source_commit':install['source_commit'],
  'root':str(root),'file_count':len(expected),'candidate_root':str(WORK),
  'candidate_package_adopted':install.get('candidate_package_adopted',False),'runtime_source_commit':manifest['source_commit']}

def pinned_pack_adapter():
 from otto.agents.herzchen_adapter import HerzchenCodexAdapter
 class PinnedPackAdapter(HerzchenCodexAdapter):
  adapter_identity="otto.usage.installed-codex-cli.v1"
  @staticmethod
  def render_verified_invocation(brief,digest_value,request,*,model_projection=None):
   # Preserve canonical evidence and its digest byte-for-byte. This physical
   # locator projection corrects the closed host's original mutable locator.
   # It neither revises BASE/Due nor adopts candidate package contents.
   manifest=json.loads((HERE/'runtime-manifest.json').read_text())
   state=json.loads((HERE/'canonical-state.json').read_text())
   pack_root=HERE/manifest['selected_pack_materialization']['relative_root']
   pack={'file_sha256':manifest['pack_hashes'],'source_commit':manifest['selected_pack_materialization']['source_commit'],
    'skill_text':(pack_root/'policy-staging/megado/skill/SKILL.md').read_text()}
   evidence=verify_selected_pack_materialization(state,pack)
   projection={'schema':'otto.closed-host.selected-pack-location.v1',**evidence,
    'path_mapping':{str(WORK/name):str(pack_root/name) for name in manifest['pack_hashes']},
    'instruction':'For adopted Megado pack/skill context, use the verified immutable paths in this mapping, including all linked pack references. The WORK policy-staging paths in the preserved canonical brief are historical physical locators to an editable candidate; they do not establish package adoption. Candidate contents remain project implementation and review inputs. Keep the canonical brief, assignment, Due, task acceptance and invocation authority unchanged. Read the immutable SKILL.md and follow its relative references from the immutable pack root.'}
   rendered=HerzchenCodexAdapter.render_verified_invocation(brief,digest_value,request,model_projection=model_projection)
   encoded=json.dumps(projection,sort_keys=True,separators=(',',':'))
   return ('Closed host physical resource location correction; applies to all manager and worker pack reads.\n'
    + '<otto-selected-pack-location>\n'+encoded+'\n</otto-selected-pack-location>\n'+rendered)
 return PinnedPackAdapter

class Server:
 def __init__(self,owner,port,state,binding,store):
  from otto.portfolio.execution_host import ExecutionHost
  self.owner,self.due_port,self.state,self.binding,self.store=owner,port,state,binding,store
  self.native_bodies=native_body_capability(state,owner,store)
  from otto.portfolio.help_delivery import BoundHelpDelivery
  from otto.portfolio.owner_issue_loop import OwnerIssueReaders
  from s06_root_reply import RootStdinReply
  from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
  from otto.portfolio.external_owner_execution import OwnerExecutionIngress
  self.owner_execution=OwnerExecutionIngress(actor=binding.authenticated_actor(OWNER),owner_actor=owner.owner_actor,directory=HERE/'manager-ipc')
  self.owner_authoring=OwnerAuthoringIngress(actor=binding.authenticated_actor(OWNER),owner_actor=owner.owner_actor,directory=HERE/'manager-ipc')
  from otto.portfolio.document_editor_host import DocumentEditorHost
  import stat
  editor_private=Path('/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010/document-editor')
  for path in (editor_private.parent.parent,editor_private.parent,editor_private):
   mode=path.lstat()
   if not stat.S_ISDIR(mode.st_mode) or mode.st_uid!=os.getuid() or stat.S_IMODE(mode.st_mode)!=0o700:raise PermissionError('editor private directory is not owner-protected')
  secret_path=editor_private/'writer-secret'
  mode=secret_path.lstat()
  if not stat.S_ISREG(mode.st_mode) or mode.st_uid!=os.getuid() or stat.S_IMODE(mode.st_mode)!=0o600:raise PermissionError('editor writer secret is not owner-protected')
  secret=secret_path.read_bytes()
  if len(secret)!=32:raise PermissionError('editor writer secret size differs')
  if editor_private.resolve().is_relative_to(WORK.resolve()) or editor_private.resolve().is_relative_to(RUN.resolve()):raise PermissionError('editor private state overlaps native writable roots')
  self.document_editor=DocumentEditorHost(owner=owner,directory=editor_private,secret=secret)

  class OwnerInput(RootStdinReply):
   def publish(reply,envelope):
    if isinstance(envelope,dict) and envelope.get('schema')==self.owner_execution.schema:return self.owner_execution.publish(envelope)
    if isinstance(envelope,dict) and envelope.get('schema')==self.owner_authoring.schema:return self.owner_authoring.publish(envelope)
    return super().publish(envelope)
  self.help_delivery=BoundHelpDelivery(readers=OwnerIssueReaders(owner.consumer_operations(),port),interim_supervision=state['root_help_binding'])
  self.portfolio=owner.portfolio(due_port=port,issue_delivery=self.help_delivery);self.manager_turn_settled=threading.Event()
  self.root_reply=OwnerInput(binding=state['root_help_binding'],authenticated_actor=binding.authenticated_actor(OWNER),delivery=self.help_delivery,portfolio=self.portfolio,directory=HERE/'manager-ipc')
  from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress,managed_caller_binding
  self.native_callers=NativeProcessCallerIngress(lambda authorization:managed_caller_binding(self,authorization))
  self.execution_host=ExecutionHost(directory=HERE/'manager-ipc',handler=self.handle,owner_path=HERE/'manager-status-owner.json',socket_path=native_caller_socket_path(),caller_binding_reader=self.native_callers,caller_context_resolver=self._caller_context,caller_authorizer=self._authorize_caller,owner_file_compatibility=True)
 def _caller_context(self,caller):
  due=self.due_port.read_due(caller.schedule_id)
  return self._execution(principal=caller.actor.actor,model=due['requested_model'],reasoning=due['requested_reasoning'],evidence_id='caller-context-read').caller_context(caller)
 def _authorize_caller(self,context,request):
  from otto.portfolio.manager_journey_service import ManagerJourneyService
  if not isinstance(self.execution_host.handler,ManagerJourneyService):raise PermissionError('current manager command authorization is not installed')
  return self.execution_host.handler.authorize_caller(context,request)
 def _save_state(self):write(HERE/'canonical-state.json',self.state)
 def _execution(self,*,principal,model,reasoning,evidence_id):
  from otto.agents.codex_host_reader import CodexAppServerThreadReader
  from otto.agents.herzchen_adapter import HerzchenCodexAdapter
  adapter=pinned_pack_adapter()(owner=principal,source=str(RUN),worktree=str(WORK),launcher=LAUNCHER,requested_model=model,requested_reasoning=reasoning,trusted_thread_reader=CodexAppServerThreadReader(launcher=LAUNCHER,timeout_seconds=30),host_context_path=str(HERE/'evidence'/(evidence_id+'-host.jsonl')),require_host_context=True,writable_roots=(str(HERE),),native_process_observer=self.native_callers.observe,native_caller_socket=str(native_caller_socket_path()))
  return self.owner.execution_application(due_port=self.due_port,adapter=adapter,manager_actor=MANAGER,issue_delivery=self.help_delivery,native_bodies=self.native_bodies)
 def handle(self,request):
  from herzchen.contracts import ResourceRef
  from otto.portfolio.execution_operations import commit_local_checkpoint
  command=request.get('command');state=self.state
  if command=='status':
   due=self.due_port.read_due((state.get('manager_continuation') or {}).get('schedule_id') or state['schedule_id'])
   return {'outcome':'ok','project_ref':state['project_ref'],'task_refs':state['task_refs'],'criteria':state['criterion_refs'],'workers':state.get('workers',{}),'manager':MANAGER,'manager_assignment_ref':state['assignment_ref'],'occurrence':{k:due.get(k) for k in ('schedule_id','version','delivery_state','host_state','completion_state','stop_state','in_flight_request')},'advisor_policy':state['advisor_policy'],'interim_supervision':state['interim_supervision'],'source_baseline':state['source_baseline']}
  if command=='report':
   alias=request['task']
   if alias not in state['task_refs']:raise ValueError('unknown current task')
   from datetime import datetime,timezone
   value={'schema':'otto.manager-progress.v1','project_ref':state['project_ref'],'task_alias':alias,'task_ref':state['task_refs'][alias],'summary':request['summary'],'next_action':request['next_action'],'continue_requested':request.get('continue_project') is True,'logical_request_key':request['request_key'],'recorded_at':datetime.now(timezone.utc).isoformat()}
   result=self.owner.assignments.command_port.append_report(ResourceRef.from_dict(state['assignment_ref']),value,expected_generation=state['manager_generation'],logical_request_key=request['request_key'],actor=self.binding.authenticated_actor(MANAGER))
   from otto.portfolio.owner_readers import json_value
   return {'outcome':'committed','report':json_value(result),'continuation_requested':value['continue_requested'],'provider_called':False,'host_action_transport':'root actively inspects this exact report/receipt; no automatic help delivery yet'}
  if command=='commit':return commit_local_checkpoint(WORK,request['paths'],message=request['message'])
  if command=='start-manager':
   if set(request)!={'command','schedule_id'} or request['schedule_id']!=state['schedule_id']:raise ValueError('root initial manager schedule differs')
   app=self._execution(principal=MANAGER,model=state['requested_model'],reasoning=state['requested_reasoning'],evidence_id='manager-initial')
   self.manager_turn_settled.clear()
   try:
    result=app.start(schedule_id=state['schedule_id']);write(HERE/'evidence/manager-launch-result.json',result)
    due=self.due_port.read_due(state['schedule_id']);attempt=((due.get('host_evidence') or {}).get('gateway_attempt') or {});observed=attempt.get('result') or {};session=observed.get('physical_session_id') or attempt.get('physical_session_id')
    state['manager_launch']={'outcome':result.get('outcome'),'physical_session_id':session,'observed_model':observed.get('observed_model'),'observed_reasoning':observed.get('observed_reasoning'),'observed_turn_id':observed.get('observed_turn_id'),'completion_state':due.get('completion_state')}
    if due.get('completion_state')=='succeeded' and isinstance(session,str):state['manager_continuation']={'schedule_id':due['schedule_id'],'native_session_id':session,'outcome':'succeeded','requested_continuation':{'settled_schedule_id':due['schedule_id']}}
    self._save_state();return result
   finally:self.manager_turn_settled.set()
  raise ValueError('operation is not installed in this interim host; read client --help and return exact operational-help report without replay')

def enqueue_initial_manager(state):
 """Root startup uses ordinary durable file ingress, never internal submit.

 The stable transport handle is preserved across restart. The existing app.start
 occurrence fence owns provider replay; this function cannot choose another Due.
 """
 request={'command':'start-manager','schedule_id':state['schedule_id']}
 token=digest(json.dumps(request,sort_keys=True,separators=(',',':')).encode())
 path=HERE/'manager-ipc'/('request-'+token+'.json')
 response=path.with_name('response-'+token+'.json')
 receipt={'outcome':'admitted','request_id':token,'retained_handle':token,
  'schedule_id':state['schedule_id'],'request_path':str(path),'response_path':str(response),
  'provider_called':False,'retry_provider':False,'transport':'ordinary-file-ipc'}
 retained=HERE/'evidence/manager-start-retained.json'
 if retained.exists() and json.loads(retained.read_text())!=receipt:
  raise RuntimeError('initial retained ingress receipt differs; inspect without replacing')
 if not retained.exists():write(retained,receipt)
 if path.exists() and json.loads(path.read_text())!=request:
  raise RuntimeError('initial request identity changed; inspect without replay')
 if not response.exists() and not path.exists():
  temporary=path.with_name('.'+path.name+'.publish')
  fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  try:
   with os.fdopen(fd,'w') as stream:
    json.dump(request,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
   os.replace(temporary,path)
  finally:temporary.unlink(missing_ok=True)
 return receipt

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preflight',action='store_true');p.add_argument('--start-manager',action='store_true');p.add_argument('--root-reply-stdin',action='store_true');args=p.parse_args()
 verify_install();state=json.loads((HERE/'canonical-state.json').read_text())
 store,binding,owner,port=composition(state)
 server=None
 try:
  qualified=read_preflight(state,owner,port)
  server=Server(owner,port,state,binding,store)
  qualified['help_delivery']=server.help_delivery.describe(state['project_ref'])
  qualified['root_reply_ingress']='exact root-owned stdin grant over existing serialized file IPC; manual run-local host adapter'
  qualified['document_editor_host']={'shared_edt_lifecycle':server.document_editor.lifecycle.service is server.document_editor.sessions,'default_idle_seconds':900,'buffer_transport':'authenticated owner document-authoring commands','poller':'existing wait loop publishes finite owner-lane idle attempt','restart':'explicit holder resume and buffer recapture; no automatic recovery publication'}
  if args.preflight:print(json.dumps(qualified,indent=2));return
  if (HERE/'manager-service-stop').exists():raise RuntimeError('explicit stop marker retained; root must inspect before restart')
  from otto.portfolio.manager_journey_service import install_manager_journey_service
  def observe_schedules(project_id):
   records=port.list_due();owned=[r['schedule_id'] for r in records if (r.get('project_ref',{}).get('id') if isinstance(r.get('project_ref'),dict) else r.get('project_ref'))==project_id and r.get('owner')==OWNER and r.get('interval_seconds') is not None and r.get('stop_state')!='completed']
   unknown=any((r.get('project_ref',{}).get('id') if isinstance(r.get('project_ref'),dict) else r.get('project_ref'))==project_id and r.get('interval_seconds') is not None and r.get('owner')!=OWNER for r in records)
   return {'mode':'owned-schedule' if owned else 'no-owned-schedule','pm_owned_schedule_ids':owned,'unknown_ownership':unknown,'coverage':{'authority':AUTH,'project_id':project_id,'source':'complete public Due list','record_count':len(records)},'shared_records':[{'schedule_id':r['schedule_id'],'status':'preserved'} for r in records if r['schedule_id'] not in owned]}
  install_manager_journey_service(server,run_path=RUN,workspace=WORK,policy=state['assessment_policy'],orchestrator_principal=OWNER,observe_schedules=observe_schedules,help_reply_authorizer=server.root_reply.authorize,authoring_authorizer=server.owner_authoring.authorize, external_execution_authorizer=server.owner_execution.authorize, external_execution_policy=state.get('external_execution_policy'),delegation_policy=state.get('delegation_policy'))
  server.execution_host.start();print(json.dumps({'outcome':'ready','provider_called':False,'pid':os.getpid(),'qualified':qualified}),flush=True)
  if args.root_reply_stdin:
   threading.Thread(target=server.root_reply.serve_stdin,args=(sys.stdin,lambda value:print(json.dumps(value),flush=True)),daemon=True,name='root-reply-stdin').start()
  if args.start_manager:
   retained=enqueue_initial_manager(state);print(json.dumps({'manager_start':retained}),flush=True)
  server.execution_host.wait_until_stopped(lambda: (HERE/'manager-service-stop').exists(), idle_poll=lambda: server.document_editor.poll_idle(server.owner_authoring))
 finally:
  if server is not None:server.execution_host.close()
  store.close();print(json.dumps({'outcome':'closed'}),flush=True)
if __name__=='__main__':main()
