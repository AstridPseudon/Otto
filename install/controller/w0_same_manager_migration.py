"""Finite SAME W0 migration, composed by the authenticated physical owner.

No Store opener, service action, source install or provider call. Producers run
inside one canonical transaction. Lost-result recovery consumes the immutable
same-manager completion report before current-head validation.
"""
from copy import deepcopy
import hashlib
from herzchen.contracts import ResourceRef,canonical_json
from herzchen.content.instructions import validate_instruction_content
from herzchen.kernel.limits import LimitService
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.owner_readers import json_value
from otto.hostctl.register import _manager_contract
import assignment_owner_migration as migration
import claude_invalid_initializer_custody as custody

PROJECT='project-68aca4e5bce229bddab0b89a6b52'
MANAGER='assignment-1c95154ca88cd31c0c00fbfec5da'
ROOT='assignment-7b390c8fdd74a67fc489b97692e5'
OWNER='otto-operating-setup-owner'
KEY='W0-same-manager-Codex-Luna-human-handoff-20261013-v1'
SCHEMA='otto.W0-same-manager-Codex-Luna-handoff.v1'
CAPS={'manager':6,'worker-normal':5,'worker-xhard':3,'final-astra':1}

def require(value,message):
 if not value:raise PermissionError(message)
def digest(value):return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def current(owner,kind,identity):return owner.store.consumer().get_record(ResourceRef(owner.store.authority,kind,identity))

def plan(owner,*,root_ref,due_port,activation_receipt,workspace,source_pins,allowance_snapshot,instructions):
 require(owner.owner_actor.actor==OWNER,'authentic existing physical owner required')
 root=owner.assignments.get(ResourceRef.from_dict(root_ref))
 require(root.ref.to_dict()==root_ref and root.ref.id==ROOT and root.role=='orchestrator'
  and root.principal==OWNER and root.session and root.generation==1,'exact unchanged own Root13 responsibility/conversation required')
 project=owner.graph.current(ResourceRef(owner.store.authority,'work.project',PROJECT))
 assignment=owner.assignments.get(ResourceRef(owner.store.authority,'wrk.assignment',MANAGER))
 due=due_port.read_due(custody.ORIGINAL['schedule_id'])
 require(due is not None and due['project_ref']==PROJECT and due['assignment_ref']==assignment.ref.to_dict()
  and due['generation']==assignment.generation==1 and due['stop_state']=='stopped' and due['in_flight_request']is None,
  'exact genuinely retired original initializer/current same manager required')
 require(activation_receipt.get('steps',{}).get('manager',{}).get('assignment_ref',{}).get('id')==MANAGER
  and activation_receipt.get('project_ref',{}).get('id')==PROJECT,'same original activation receipt required')
 require(assignment.role=='manager'and assignment.session is None and assignment.payload.get('manager')=='claude-code-orchestrator',
  'only current sessionless original Claude-owned manager can migrate')
 marker=(due.get('host_evidence')or{}).get(custody.MARKER)or{}
 require(marker.get('disposition_ref'),'authenticated original initializer disposition missing')
 relation=project.payload.get('metadata',{}).get('otto_orchestrator')or{}
 former=owner.assignments.get(ResourceRef.from_dict(relation['assignment_ref']))
 require(former.principal=='claude-code-orchestrator'and former.role=='orchestrator'
  and relation.get('generation')==former.generation and former.scope.kind=='wrk.portfolio',
  'existing original W0 portfolio supervisor required')
 require(allowance_snapshot['manager_ref']==assignment.ref.to_dict()
  and allowance_snapshot['project_ref']==project.ref.to_dict() and allowance_snapshot['records_modified']is False
  and allowance_snapshot['original_initializer_usage']=='unknown'and allowance_snapshot['original_initializer_payment']=='unknown',
  'fresh exact preserved-debit snapshot required')
 require(isinstance(workspace,str)and workspace.startswith('/')and isinstance(instructions,str)and 0<len(instructions.encode())<=32768,
  'explicit finite reviewed workspace and instruction body required')
 require(isinstance(source_pins,dict)and source_pins and len(source_pins)<=32
  and all(isinstance(v,str)and len(v)==64 for v in source_pins.values()),'finite exact approved source pins required')
 require(len(project.payload.get('tasks')or[])==4,'original four W0 task identities required')
 required=[r for r in assignment.payload.get('resource_adoptions',[])if r.get('required')is True]
 require(len(required)==1,'exact original required BASE adoption required')
 return {'schema':SCHEMA+'.plan','request_key':KEY,'project_ref':project.ref.to_dict(),'project_version':project.version,
  'project_payload_sha256':digest(project.payload),'manager_ref':assignment.ref.to_dict(),'generation':1,
  'original_due_sha256':digest(due),'original_due_ref':ResourceRef(owner.store.authority,'otto.due-record',due['schedule_id'],'rev-'+str(due['version'])).to_dict(),
  'disposition_ref':marker['disposition_ref'],'root_ref':root_ref,'root_payload_sha256':digest(root.payload),
  'conversation_ref':json_value(root.session),'former_supervisor_ref':former.ref.to_dict(),'former_supervisor_generation':former.generation,
  'portfolio_ref':json_value(former.scope),'former_supervisor_payload_sha256':digest(former.payload),
  'original_required_resource':required[0],'task_refs':deepcopy(project.payload['tasks']),
  'workspace':workspace,'source_pins':source_pins,'instructions':instructions,'allowance_snapshot':allowance_snapshot,
  'new_authorized_pool_caps':CAPS,'human_review_cap':3,'source_review_calls_used':2,
  'source_document_read_authorization':'human-authorized same W0 takeover through physical owner DAT port; no former principal selected',
  'project_documents':document_inputs(owner,project),'unknown_initializer_usage_and_payment_preserved':True,'provider_called':False}

def document_inputs(owner,project):
 refs=[];selected=[]
 for kind,prefix in (('dat.content.association',()),('document-association',('association',))):
  refs.extend(owner.store.consumer().find_identity_refs(kind=kind,payload_matches={prefix+('subject','id'):project.ref.id,prefix+('namespace',):'project.files'}))
 require(len(refs)<=32,'W0 project document association inventory exceeds finite bound')
 for reference in refs:
  association=owner.store.consumer().get_record(reference)
  payload=json_value(association.payload);link=payload.get('association')or payload
  if link.get('namespace')!='project.files'or payload.get('active')is False:continue
  pin=(link.get('document')or{}).get('ref')
  require(pin and pin['authority']==project.ref.authority and pin['kind']=='dat.content.document',
   'W0 original project.files DAT association is foreign')
  header=owner.store.consumer().get_record(ResourceRef(pin['authority'],pin['kind'],pin['id']))
  meta=json_value(header.payload)['document'];head=json_value(header.payload)['current_revision']
  require(meta['authoring_scope']['id']==PROJECT and meta['maintainer']=='claude-code-orchestrator'
   and meta['visibility']in('private','shared'),'exact original W0 source-maintained document required')
  content=owner.content.read(ResourceRef.from_dict(head))['content']
  require(len(canonical_json(content).encode())<=262144,'selected W0 document body exceeds finite adoption bound')
  selected.append({'path':link['key'],'association_ref':association.ref.to_dict(),'association_sha256':digest(payload),
   'metadata':meta,'current_revision':head,'document_version':header.version,'content_sha256':digest(content)})
 require(1<=len(selected)<=16 and len({r['path']for r in selected})==len(selected),'exact finite named W0 project documents required')
 return sorted(selected,key=lambda row:row['path'])

def share_documents(owner,project,rows):
 from herzchen.content import ContentDocument,ContentRevision
 from herzchen.contracts import TransactionContext
 from herzchen.content.packets import ContextPacketService
 require(document_inputs(owner,project)==rows,'original W0 association/document head or bytes changed')
 result=[]
 for row in rows:
  pin=ResourceRef.from_dict(row['current_revision']);content=owner.content.read(pin)['content']
  document=ContentDocument.from_dict(row['metadata'])
  if document.visibility=='private':
   document=__import__('dataclasses').replace(document,visibility='shared')
   revision=ContentRevision(document.ref,'W0-owner-scope-read-'+digest(rows)[:24],content,owner.owner_actor,parent_revision=pin.revision)
   transaction=TransactionContext(owner.owner_actor,KEY+':scope-read:'+pin.id,
    digest({'old':row,'new_visibility':'shared','content_sha256':digest(content)}),
    expected_version=row['document_version'],expected_revision=pin.revision)
   owner.content.execute(owner.content.build_append_revision(transaction,document,revision))
   head=revision.ref.to_dict()
  else:head=pin.to_dict()
  resolved=ContextPacketService(owner.store).resolve_reference({'ref':head,'mode':'pinned'},actor=owner.owner_actor,scopes=(project.ref,))
  require(json_value(resolved['resolved'])==head and digest(owner.content.read(ResourceRef.from_dict(head))['content'])==row['content_sha256'],
   'normal own-root resolver/content did not verify scoped read adoption')
  result.append({'path':row['path'],'prior_revision':row['current_revision'],'adopted_revision':head,
   'content_sha256':row['content_sha256'],'original_maintainer_and_scope_preserved':True,'associations_unchanged':True})
 return result

def _document(owner,due_port,project,key,name,content,role):
 created=owner.portfolio(due_port=due_port).create_document(project,actor=owner.owner_actor.actor,request_id=key,
  document_id=name,role=role,content=content,visibility='shared',access_mode='read')
 require(created.get('outcome')in('created','replayed','committed')and 'record'in created,'Root-authored canonical document did not commit')
 return created['record']['payload']['current_revision']

def apply(owner,*,due_port,immutable_plan,execution_factory,fail_before_report=False):
 p=immutable_plan
 require(p.get('schema')==SCHEMA+'.plan'and p['request_key']==KEY,'exact immutable W0 migration plan required')
 actor=owner.owner_actor;require(actor.actor==OWNER,'receiving authentic physical owner required')
 # Recovery is receipt first. No refreshed revision or hash replaces the inputs.
 reports=owner.assignments.list_observations(ResourceRef.from_dict(p['manager_ref']),kind='report')
 results=[r for r in reports if isinstance(r.value,dict)and r.value.get('schema')==SCHEMA+'.completed'and r.value.get('plan_sha256')==digest(p)]
 require(len(results)<=1,'ambiguous original migration completion receipt')
 if results:return {**results[0].value['result'],'replayed':True,'completion_report_ref':results[0].ref.to_dict()}
 from otto.attention import DueRecord
 from types import SimpleNamespace
 original=due_port.read_due(custody.ORIGINAL['schedule_id'])
 app=SimpleNamespace(actor=actor.actor,binding=owner.binding,portfolio=owner.portfolio(due_port=due_port),
  _read=lambda key:DueRecord.from_dict(due_port.read_due(key)))
 custody.retained(app,DueRecord.from_dict(original))
 assignment=owner.assignments.get(ResourceRef.from_dict(p['manager_ref']))
 project=owner.graph.current(ResourceRef.from_dict(p['project_ref']))
 root=owner.assignments.get(ResourceRef.from_dict(p['root_ref']))
 former=owner.assignments.get(ResourceRef.from_dict(p['former_supervisor_ref']))
 require(assignment.ref.to_dict()==p['manager_ref']and assignment.generation==p['generation']
  and project.ref.to_dict()==p['project_ref']and digest(project.payload)==p['project_payload_sha256']
  and digest(original)==p['original_due_sha256']and root.ref.to_dict()==p['root_ref']and digest(root.payload)==p['root_payload_sha256']
  and former.ref.to_dict()==p['former_supervisor_ref']and digest(former.payload)==p['former_supervisor_payload_sha256'],
  'original migration project/assignment/Root/initializer/source supervision CAS changed')
 migration.register(owner.store)
 original_limits=LimitService(owner.store)
 for observed in p['allowance_snapshot']['pool_snapshots']:
  pool=original_limits.get_pool(ResourceRef.from_dict(observed['ref']))
  require(pool is not None and all(json_value(getattr(pool,key))==value for key,value in observed.items()),
   'original held/consumed pool snapshot changed; never reinterpret it as free')
 with owner.store.transaction():
  document_adoption=share_documents(owner,project,p['project_documents'])
  authorization={'schema':migration.AUTHORIZATION,'assignment_ref':assignment.ref.to_dict(),'generation':assignment.generation,
   'from_owner':assignment.payload['manager'],'to_owner':actor.actor,'same_project':True,'preserve_effects_and_debits':True,
   'disposition_ref':p['disposition_ref'],'human_override':'same W0 Luna manager; Luna normal; Sol6.1 XHARD; Astra total<=3, two already used',
   'plan_sha256':digest(p)}
  permission=owner.assignments.append_report(assignment.ref,authorization,expected_generation=1,
   logical_request_key=KEY+':human-authorized-owner-input',actor=actor)
  migrated=migration.AssignmentOwnerMigration(owner.store).transfer(assignment.ref,from_owner=assignment.payload['manager'],
   to_owner=actor.actor,expected_generation=1,disposition_ref=p['disposition_ref'],authorization_ref=permission.ref,
   due_ref=p['original_due_ref'],actor=actor,request_key=KEY+':owner-transfer')
  transferred=owner.assignments.get(ResourceRef.from_dict(migrated['assignment_ref']))
  manager=owner.assignments.reassign(transferred.ref,principal=transferred.principal,agent='codex:gpt-6-luna',
   expected_generation=1,logical_request_key=KEY+':same-manager-Codex-generation',actor=actor,
   reason='human-authorized same W0 Codex Luna handoff; original invalid initializer remains UNKNOWN')
  # Same human owner and native conversation, portfolio scoped ONLY to W0.
  supervisor=owner.assignments.assign(ResourceRef.from_dict(p['portfolio_ref']),role='orchestrator',principal=actor.actor,
   session=p['conversation_ref'],manager=actor.actor,logical_request_key=KEY+':W0-portfolio-responsibility',actor=actor)
  scoped=PortfolioOwnerBootstrap(owner.store,binding=owner.binding,owner_actor=actor.actor,
   portfolio_ref=ResourceRef.from_dict(p['portfolio_ref']),main_assignment_ref=supervisor.ref,
   privileged_actor_ids=(actor.actor,),expected_main_principal=actor.actor,project_read_grant=owner.project_read_grant)
  scoped.orchestration_port.transfer_supervision(actor=actor,request_id=KEY+':same-project-supervision',
   portfolio_ref=p['portfolio_ref'],project_ref=p['project_ref'],expected_project_revision=p['project_ref']['revision'],
   expected_project_version=p['project_version'],current_assignment_ref=p['former_supervisor_ref'],
   current_assignment_revision=p['former_supervisor_ref']['revision'],current_assignment_generation=p['former_supervisor_generation'],
   target_assignment_ref=supervisor.ref,target_assignment_revision=supervisor.revision,target_assignment_generation=supervisor.generation,
   overlap_acknowledged=True)
  project=owner.graph.current(ResourceRef(owner.store.authority,'work.project',PROJECT))
  binding={'principal':actor.actor,'assignment_ref':supervisor.ref.to_dict(),'generation':supervisor.generation,
   'conversation_ref':p['conversation_ref'],'project_ref':project.ref.to_dict()}
  limits=LimitService(owner.store);pools={}
  for name,cap in CAPS.items():
   ref=ResourceRef(owner.store.authority,'limit',PROJECT+'-Codex-Luna-'+name+'-20261013')
   require(limits.get_pool(ref)is None,'authorized new pool already exists without migration receipt; preserve it and reconcile')
   pool=limits.create_pool(ref,capacity_units=1,cumulative_allowance_units=cap,
    logical_request_key=KEY+':new-pool:'+name,actor=actor)
   pools[name]=pool.ref.to_dict()
  roles={name:{'adapter':'codex','model':model,'reasoning':effort,'provenance':{'source':'explicit human same-W0 takeover'}}
   for name,model,effort in(('coordinator','gpt-6-luna','medium'),('worker_normal','gpt-6-luna','medium'),
    ('worker_xhard','gpt-6.1-sol','high'),('final_reviewer','gpt-6-astra','high'))}
  configuration={'schema':'otto.role-configuration.v1','model_profile':'codex','roles':roles,
   'role_bindings':{'manager':'coordinator','worker':'worker_normal','orchestrator':'final_reviewer'},
   'worker_routes':{'normal':'worker_normal','xhard':'worker_xhard'},
   'tool_entrypoints':{name:'/Users/hannahomalley/.otto/bin/ottoctl --home /Users/hannahomalley/.otto manager' for name in('manager','worker','orchestrator')},
   'operational_supervisor':binding,'manager_context_required':True,'source':{'original_activation_preserved':True,
    'human_same_project_override':True,'source_pins':p['source_pins'],'old_initializer_disposition_ref':p['disposition_ref']},
   'new_finite_allocations':pools,'prior_usage_payment':'unknown','review_calls_used':2,'remaining_review_calls':1}
  config_ref=_document(owner,due_port,project.ref.to_dict(),KEY+':role-configuration','W0-Codex-Luna-role-configuration',configuration,'configuration')
  guide={'schema':'herzchen.instructions.v1','name':p['original_required_resource']['resource_name'],
   'entrypoint':'manager-brief.md','required':True,'instructions':p['instructions'],
   'bundle_digest':hashlib.sha256(p['instructions'].encode()).hexdigest(),'export_manifest_digest':digest(p['source_pins']),
   'supporting_refs':[config_ref]}
  guide_ref=_document(owner,due_port,project.ref.to_dict(),KEY+':BASE','W0-Codex-Luna-manager-BASE',guide,'supporting')
  adoptions=deepcopy(manager.payload['resource_adoptions'])
  required=[r for r in adoptions if r.get('required')is True]
  require(len(required)==1 and required[0]==p['original_required_resource'],'original required BASE changed during migration')
  adoptions=[{**r,'resource_ref':guide_ref,'content_digest':validate_instruction_content(guide)}if r==required[0]else r for r in adoptions]
  manager=owner.assignments.command_port.adopt_resources(manager.ref,resources=adoptions,expected_revision=manager.revision,
   expected_generation=manager.generation,logical_request_key=KEY+':BASE-adoption',actor=actor)
  task_ref=p['task_refs'][0]
  contract=_manager_contract(task_ref,manager.principal,p['workspace'],'otto-work-model-W0-host-ergonomics')
  mandate={'role':'manager','scope_ref':project.ref.to_dict(),'status':'active','dispatch_enabled':True,'task_ref':task_ref,
   'assignment_ref':manager.ref.to_dict(),'generation':manager.generation,'instruction_contract':contract,
   'brief':{'role':'manager','mandate':'Accept and integrate the frozen existing W0 E1-E4 source batch; verify actual installed use; preserve original task/history/debits and do not replay source workers.'}}
  mandate_ref=_document(owner,due_port,project.ref.to_dict(),KEY+':mandate','W0-Codex-Luna-manager-mandate',mandate,'mandate')
  state={'project_ref':project.ref.to_dict(),'assignment_ref':manager.ref.to_dict(),'manager_generation':manager.generation,
   'manager':manager.principal,'owner':actor.actor,'requested_model':'gpt-6-luna','requested_reasoning':'medium',
   'guide_ref':guide_ref,'mandate_ref':mandate_ref,'role_configuration_ref':config_ref,'root_help_binding':binding,
   'orchestrator_assignment_ref':supervisor.ref.to_dict(),'source_path':p['workspace'],'new_pool_refs':pools,
   'original_schedule_id':original['schedule_id'],'original_unknown_retained':True,
   'project_document_read_adoption':document_adoption,'provider_called':False}
  executable=execution_factory(scoped,state)
  require(executable.actor==actor.actor and executable.assignments is scoped.assignments.command_port
   and executable.manager_actor==manager.principal and executable.due_port is due_port,'same owned Codex execution ports required')
  prepared=executable.prepare_role(role='manager',project_ref=state['project_ref'],task_ref=task_ref,
   assignment_ref=state['assignment_ref'],generation=manager.generation,mandate_ref=mandate_ref,
   request_key=KEY+':first-Codex-role',profile='workspace-write',fresh_manager=True,allowance_ref=pools['manager'])
  require(prepared.get('outcome')in('prepared','committed','replayed'),'same manager Codex role preparation refused')
  state.update(schedule_id=prepared['schedule_id'])
  # Existing manual setup is amended by its canonical producer, exact old CAS.
  from otto.portfolio.operating_setup import read_setup,setup_reference
  setup=deepcopy(read_setup(executable.portfolio.operations,state['project_ref']))
  require(setup is not None and setup['roles']['manager']==original['schedule_id'],'original W0 manual selector changed')
  setup['roles']['manager']=prepared['schedule_id']
  head=executable.portfolio.operations.content_port.read(setup_reference(state['project_ref']))['current_revision']
  bound=executable.compose_operating_setup(project_ref=state['project_ref'],operation='update',setup=setup,
   expected_setup_ref=head,request_key=KEY+':same-setup-CAS')
  require(bound.get('outcome')in('updated','replayed'),'same W0 Codex operating setup did not qualify')
  require(due_port.read_due(original['schedule_id'])==original,'original UNKNOWN/Due changed during handoff')
  require(owner.assignments.get(root.ref).payload==root.payload and owner.assignments.get(former.ref).payload==former.payload,
   'Root13 or unrelated former Claude responsibility changed')
  require(owner.graph.current(project.ref).payload['tasks']==p['task_refs'],'original W0 task identities changed')
  for observed in p['allowance_snapshot']['pool_snapshots']:
   pool=original_limits.get_pool(ResourceRef.from_dict(observed['ref']))
   require(all(json_value(getattr(pool,key))==value for key,value in observed.items()),'migration changed original pools or reservations')
  state.update(operating_setup=json_value(bound),plan_sha256=digest(p),same_assignment_id_preserved=True,
   generation_advanced_once=True,unknown_initializer_usage_and_payment_preserved=True,
   source_review_calls_already_used=2,remaining_astra_final_calls=1,provider_called=False)
  if fail_before_report:raise InterruptedError('fixture interruption before canonical completion; transaction must roll back')
  report=owner.assignments.append_report(manager.ref,{'schema':SCHEMA+'.completed','plan_sha256':digest(p),'result':state},
   expected_generation=manager.generation,logical_request_key=KEY+':completed',actor=actor)
  return {**state,'completion_report_ref':report.ref.to_dict(),'replayed':False}
