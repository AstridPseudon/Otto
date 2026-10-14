"""Same W0 fixed Codex view and ONLY W0 own-principal lane after canonical handoff."""
from copy import deepcopy
import importlib.util,json,os,hashlib
from pathlib import Path
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio.owner_readers import json_value
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.orchestrator_client import OrchestratorAdmissions,ScopedOrchestratorClient,ROOT_PROJECT_OPERATIONS
from otto.portfolio.supervisor_direction_client import scoped_supervisor_handler
from otto.portfolio import client_lanes as lanes
from registered_view_attachment import attach_registered_view,activation_boundary
import w0_same_manager_migration as migration
from w0_finite_role_allowance import bind as bind_allowance

HERE=Path(__file__).resolve().parent
CONTROLLER=HERE if HERE.name=='controller'else Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller')
VIEW='claude-work-model-W0'
RUN='otto-work-model-W0-host-ergonomics'
PRIVATE=Path('/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010')

def require(value,message):
 if not value:raise PermissionError(message)
def result(owner):
 reports=owner.assignments.list_observations(ResourceRef(owner.store.authority,'wrk.assignment',migration.MANAGER),kind='report',logical_request_keys=(migration.KEY+':completed',))
 require(len(reports)<=64,'W0 migration report inventory exceeds finite bound')
 matched=[r for r in reports if isinstance(r.value,dict)and r.value.get('schema')==migration.SCHEMA+'.completed']
 if not matched:
  # A legitimate same-generation BASE adoption advances the assignment ref.
  # Resolve the ONE original migration report identity, not a broad scan.
  identity='report-'+hashlib.sha256((migration.MANAGER+':'+migration.KEY+':completed').encode()).hexdigest()[:28]
  record=owner.store.consumer().get_record(ResourceRef(owner.store.authority,'wrk.report',identity))
  if record is None:return None
  value=record.payload.get('value')or{}
  require(record.payload.get('observation_kind')=='report'and record.payload.get('assignment',{}).get('id')==migration.MANAGER
   and record.payload.get('generation')==2 and value.get('schema')==migration.SCHEMA+'.completed',
   'exact original migration report identity differs')
  manager=owner.assignments.get(ResourceRef(owner.store.authority,'wrk.assignment',migration.MANAGER))
  from otto.portfolio.operating_setup import authenticated_adoption_ancestor
  require(manager.generation==2 and manager.payload.get('manager')==migration.OWNER
   and authenticated_adoption_ancestor({'ref':manager.ref.to_dict(),'principal':manager.principal,'role':manager.role,
    'generation':manager.generation,'payload':manager.payload},record.payload['assignment'],owner.consumer_operations()._owner_reader),
   'migration report lacks authentic same-manager adoption ancestry')
  from types import SimpleNamespace
  matched=[SimpleNamespace(ref=record.ref,value=value)]
 require(len(matched)==1,'W0 migration completion is ambiguous')
 report=matched[0];body=report.value['result']
 require(body.get('same_assignment_id_preserved')is True and body.get('manager_generation')==2
  and body['assignment_ref']['id']==migration.MANAGER and body['project_ref']['id']==migration.PROJECT
  and body.get('unknown_initializer_usage_and_payment_preserved')is True
  and body.get('source_review_calls_already_used')==2 and body.get('remaining_astra_final_calls')==1
  and body['plan_sha256']==report.value['plan_sha256']
  and any(e.operation=='work.report.append'and e.actor==owner.owner_actor
          for e in owner.store.consumer().list_events(subjects=(report.ref,))),
  'canonical same-manager human-authorized handoff report differs')
 return {**body,'completion_report_ref':report.ref.to_dict()}

def server_class():
 spec=importlib.util.spec_from_file_location('otto.hostctl.W0_migrated_shared',CONTROLLER/'w0_shared_host_service.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 class CodexW0Server(module.HostOwnerService):
  def _load_state(self,record,registration):
   prior=super()._load_state(record,registration)
   migrated=result(self.owner);require(migrated is not None,'canonical W0 migration is incomplete')
   same=(self.state_path.exists()and prior.get('plan_sha256')==migrated['plan_sha256']
         and prior.get('manager_generation')==2 and prior.get('assignment_ref',{}).get('id')==migration.MANAGER)
   state={**prior,**({}if same else deepcopy(migrated))}
   if not same:
    state.pop('manager_continuation',None);state.pop('execution_hold',None)
    state['former_manager_projection_preserved_sha256']=migration.digest(prior)
   from w0_initial_manager_direction import recover_projection
   recover_projection(self.owner,self.due_port,state)
   current=self.owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']))
   require(current.ref.to_dict()==state['assignment_ref']and current.generation==2
    and current.payload.get('manager')==migration.OWNER,'current W0 manager binding changed; preserve its own continuation')
   state.update(project_ref=self.owner.graph.get(record.ref).ref.to_dict(),run_id=RUN,
    requested_model='gpt-6-luna',requested_reasoning='medium',requested_profile='workspace-write',
    original_schedule_id=migrated['original_schedule_id'],role_configuration_ref=state.get('role_configuration_ref',migrated['role_configuration_ref']),
    new_pool_refs=migrated['new_pool_refs'])
   state['task_refs']={self.owner.graph.get(ResourceRef.from_dict(pin)).payload.get('alias')or pin['id']:
    self.owner.graph.get(ResourceRef.from_dict(pin)).ref.to_dict()for pin in record.payload['tasks']}
   return state
  def render_run_view(self):
   from otto.hostctl.lanes import private_dir
   project=ResourceRef.from_dict(self.state['project_ref']);view=private_dir(self.paths['run_view'])
   documents={row['path']:row['text']for row in self._documents(project)if row['path']}
   configuration=self.owner.content.read(ResourceRef.from_dict(self.state['role_configuration_ref']))['content']
   source=json.loads(documents.pop('run.json',None)or documents.pop('run.yaml',None)or'{}')
   original_roles=deepcopy(source.get('roles',{}));source['roles']={slot:{'model':value['model'],'reasoning':value['reasoning']}
    for slot,value in configuration['roles'].items()}
   source['otto_generated_view']={'from':'canonical same W0 role migration','role_configuration':self.state['role_configuration_ref'],
    'original_source_roles_preserved_as_history':original_roles,'same_project':True,'native_models_are_human_authorized_overrides':True,
    'new_pool_refs':self.state['new_pool_refs'],'review_calls_already_used':2,'remaining_final_calls':1}
   # This view supplies current model selection; original canonical run bytes,
   # declared budgets, task cards and all old reservations are not overwritten.
   for name,text in list(documents.items())+[('run.json',json.dumps(source,sort_keys=True,indent=2)+'\n')]:
    parts=name.split('/');require(name and not name.startswith('/')and not any(p in('', '.', '..')for p in parts),'canonical W0 run path is unsafe')
    target=view.joinpath(*parts);private_dir(target.parent);target.write_text(text if isinstance(text,str)else json.dumps(text,sort_keys=True));os.chmod(target,0o600)
   return view
 return CodexW0Server

def execution_factory(owner,state,*,run,workspace,host=None,base=None,provider_factory=None):
 from otto.agents.herzchen_adapter import HerzchenCodexAdapter
 from otto.agents.codex_host_reader import CodexAppServerThreadReader
 from otto.portfolio.help_delivery import BoundHelpDelivery
 from otto.portfolio.owner_issue_loop import OwnerIssueReaders
 port=state.pop('_due_port')if '_due_port'in state else None
 require(port is not None,'exact same W0 Due port is required')
 delivery=BoundHelpDelivery(readers=OwnerIssueReaders(owner.consumer_operations(),port),interim_supervision=state['root_help_binding'])
 launcher=base.LAUNCHER if base is not None else 'synthetic-only'
 def factory(*,principal,model,reasoning,**unused):
  allowed={('gpt-6-luna','medium'),('gpt-6.1-sol','high'),('gpt-6-astra','high')}
  require((model,reasoning)in allowed,'W0 model/effort is outside the adopted human allocation')
  options=dict(owner=principal,source=str(run),worktree=str(workspace),launcher=launcher,
   requested_model=model,requested_reasoning=reasoning,require_host_context=True)
  from w0_selected_context_adapter import adapter_type as selected_adapter_type
  adapter_type=selected_adapter_type(base)if base is not None else HerzchenCodexAdapter
  if provider_factory is not None:options.update(binding_factory=provider_factory.binding,turn_context_reader=lambda session,turn:provider_factory.contexts.get((session,turn)))
  else:
   # The exact-session metadata reader is not the task-bound turn capture.
   # Both are host-owned capabilities, as in the established shared factory.
   evidence_root=lanes.private_dir(PRIVATE/'W0-Codex-Luna-native-task-evidence-20261013')
   evidence_key=migration.digest({'principal':principal,'model':model,'reasoning':reasoning,'evidence_id':unused.get('evidence_id')})
   require(not evidence_root.resolve().is_relative_to(Path(workspace).resolve())
    and(host is None or not evidence_root.resolve().is_relative_to(host.directory.resolve())),
    'host-owned task evidence must be outside native writable roots')
   options.update(trusted_thread_reader=CodexAppServerThreadReader(launcher=launcher,timeout_seconds=30),
    host_context_path=str(evidence_root/(evidence_key+'-host.jsonl')))
  if host is not None:options.update(native_caller_socket=str(host.socket_path),native_process_observer=host.caller_binding_reader.observe,
   writable_roots=()) # exact adopted workspace only; socket has its separate bounded override
  adapter=adapter_type(**options)
  app=owner.execution_application(due_port=port,adapter=adapter,manager_actor=state['manager'],issue_delivery=delivery)
  return bind_allowance(app,owner,state)
 return factory,delivery

def refresh_execution_projections(service):
 if service.host.dispatch_held:
  held={'outcome':'deferred-dispatch-held','reason':'service availability does not qualify task execution role context','provider_called':False}
  return dict(held),dict(held)
 from w0_recovered_view_projection import refresh as refresh_recovered_projection
 from w0_initialized_manager_recovery import refresh_view
 return refresh_recovered_projection(service),refresh_view(service)

def attach(common,*,manifest):
 old_owner=common.scoped_clients.owner;migrated=result(old_owner)
 require(migrated is not None,'sealed canonical same-manager W0 migration is required')
 host=common.host_clients.shared_host;clients=common.host_clients;router=clients.router
 require(not host._threads and not host._executions and not host._capacity_holds,'fixed W0 Codex join requires genuinely closed idle composition')
 # The additional W0 grant is for the same physical owner. The original four
 # root policy, responsibility and all unrelated former Claude scopes stay.
 previous=old_owner.project_read_grant
 grant=ProjectReadGrant(old_owner.owner_actor,tuple(sorted(set(previous.project_ids)|{migration.PROJECT})),migration.KEY,manifest['source_commit'])
 supervisor=old_owner.assignments.get(ResourceRef.from_dict(migrated['orchestrator_assignment_ref']))
 owner=PortfolioOwnerBootstrap(old_owner.store,binding=old_owner.binding,owner_actor=old_owner.owner_actor.actor,
  portfolio_ref=supervisor.scope,main_assignment_ref=supervisor.ref,privileged_actor_ids=(old_owner.owner_actor.actor,),
  expected_main_principal=migration.OWNER,project_read_grant=grant)
 old_owner.project_read_grant=grant
 from otto.hostctl.config import load
 config=load(Path('/Users/hannahomalley/.otto'));port=router.due_port
 session=SimpleNamespace(config=config,owner=owner,binding=owner.binding,store=owner.store,due_port=port,
  actor=owner.owner_actor,portfolio=owner.portfolio(due_port=port))
 project=owner.graph.get(ResourceRef(owner.store.authority,'work.project',migration.PROJECT))
 require(project.payload.get('custom',{}).get('otto_host_registration',{}).get('run_id')==RUN,'original W0 registration identity differs')
 server=server_class()(session,project,adapter_factory=lambda **kw:None,shared_host=host,shared_native_ingress=host.caller_binding_reader)
 run=server.render_run_view().resolve();workspace=Path(migrated['source_path']).resolve()
 import operating_service as base
 factory,delivery=execution_factory(owner,{**server.state,'_due_port':port},run=run,workspace=workspace,host=host,base=base)
 server._execution=lambda principal,model,reasoning,evidence_id,**unused:factory(principal=principal,model=model,reasoning=reasoning,evidence_id=evidence_id)
 server.help_delivery=delivery;server.paths['socket']=host.socket_path
 server.portfolio=owner.portfolio(due_port=port,issue_delivery=delivery)
 service=ManagerJourneyService(server=server,host=host,run_path=run,workspace=workspace,orchestrator_principal=migration.OWNER)
 refreshed,initialized_projection=refresh_execution_projections(service)
 expanded,proof=attach_registered_view(router=router,service=service,native_ingress=host.caller_binding_reader,
  view_key=VIEW,expected_project_id=migration.PROJECT,expected_supervisor_ref=supervisor.ref.to_dict(),
  expected_supervisor_principal=migration.OWNER,expected_run_id=RUN)
 clients.router=expanded
 # The lane lives outside P/clients/* so the pre-W0 baseline loader cannot
 # incorrectly treat it as an installed view before this exact join.
 scoped=common.scoped_clients;scoped.views={**dict(scoped.views),VIEW:service}
 directory=lanes.private_dir(PRIVATE/'W0-Codex-Luna-own-owner-client-20261013');lane=lanes.private_dir(directory/'lane')
 admissions=OrchestratorAdmissions(owner,main_assignment_ref=supervisor.ref.to_dict(),generation=supervisor.generation)
 binding=admissions.admit_current_root(actor=owner.owner_actor,conversation_ref=json_value(supervisor.session),
  operations=sorted(ROOT_PROJECT_OPERATIONS|{'whoami','status'}),project_ids=[migration.PROJECT],request_key=migration.KEY+':own-W0-client')
 require(binding['project_ids']==[migration.PROJECT]and not set(binding['operations'])&{'direction-read','direction-draft','direction-update'},
  'W0 client must not grant global or unrelated portfolio direction authority')
 locator={'schema':'otto.orchestrator-client-locator.v1','binding':binding,'lane':str(lane)}
 path=directory/'binding.json';prior=lanes.read_private_json(path)
 require(prior is None or prior==locator,'original immutable W0 owner lane differs')
 if prior is None:lanes.atomic_json(path,locator)
 handler=scoped_supervisor_handler(services=[service],fallback=scoped.handler)
 client=ScopedOrchestratorClient(owner=owner,binding=binding,handlers={op:handler for op in binding['operations']})
 client.current();scoped.pump.clients[lane]=client;server._save_state()
 previous_status=clients._status
 clients._status=lambda state='serving':{**previous_status(state),'execution_changing_boundary':activation_boundary(host)}
 from w0_final_owner_hook import install as install_completion
 from w0_source_candidate_owner_hook import install as install_sources
 completion_join=install_completion(common);source_join=install_sources(common)
 return {**proof,'completion_owner_join':completion_join,'owner_source_candidate_join':source_join,'current_context_qualified':not host.dispatch_held,'qualification':'unqualified-dispatch-held'if host.dispatch_held else'current-execution-context','same_W0_manager_migrated':True,'manager_model':'gpt-6-luna','manager_reasoning':'medium',
  'own_W0_binding_locator':str(path),'recovered_manager_projection':refreshed,'initialized_session_projection':initialized_projection,'main_root_scope_unchanged':True,'original_activation_not_replayed':True,
  'original_UNKNOWN_retained':True,'remaining_Astra_final_calls':1,'source_commit':manifest['source_commit'],'provider_called':False}
