"""Prepared finite W0 acceptance supplement using existing public producers.

No opener, dispatch, provider or source install. A future maintained owner
ingress must authenticate the physical owner before calling adopt(). Existing
manager review-task/finish-task consume the ordinary policy; source advisory
reviews are never imported as assessment decisions or pool debit records.
"""
from copy import deepcopy
from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule,contribution as assessment_contribution
from herzchen.kernel.limits import LimitService
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.owner_readers import json_value
import w0_same_manager_migration as migration
from w0_codex_view_join import result as migration_result

KEY='W0-original-four-local-completion-policy-20261013-v1'
SCHEMA='otto.W0-original-four-local-completion-policy.v1'
def require(value,message):
 if not value:raise PermissionError(message)
def same(a,b):return all(a.get(k)==b.get(k)for k in('authority','kind','id'))

def current(service,actor):
 owner,state=service.server.owner,service.server.state
 require(any(d==assessment_contribution()for d in owner.store.registered_domains()),'existing admitted assessment contribution required; this supplement registers no domain')
 require(actor==owner.owner_actor and actor.actor==migration.OWNER,'completion policy requires authentic receiving physical owner input')
 migrated=migration_result(owner)
 require(migrated is not None and state['manager_generation']==2
  and state['project_ref']['id']==migration.PROJECT and state['assignment_ref']['id']==migration.MANAGER,
  'same original migrated W0 manager/context required')
 manager=owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']))
 project=owner.graph.get(ResourceRef.from_dict(state['project_ref']))
 require(manager.ref.to_dict()==state['assignment_ref']and manager.generation==2
  and manager.payload.get('manager')==actor.actor,'current same W0 receiving ownership differs')
 require(len(service.host._executions)<=64 and len(service.host._capacity_holds)<=64,'finite current native ledger required')
 for schedule in set(service.host._executions)|set(service.host._capacity_holds):
  due=service.server.due_port.read_due(schedule)
  require(due is not None,'native ledger occurrence missing')
  require(due['project_ref']!=project.id,'W0 must settle its admitted native custody before completion-policy adoption')
 # Original migration's first schedule is a retained historical refusal. The
 # current exact head must instead prove an actually completed owned task turn.
 schedule=service._current_manager_schedule();first=service.server.due_port.read_due(schedule)
 result=((first or{}).get('host_evidence')or{}).get('gateway_attempt',{}).get('result')or{}
 require(first is not None and first['assignment_ref']==manager.ref.to_dict()and first['generation']==2
  and first['stop_state']=='completed'and first['completion_state']=='succeeded'and first['in_flight_request']is None
  and result.get('outcome')=='succeeded'and result.get('context_digest_verified')is True
  and result.get('physical_session_id')==first['target'].get('native_id')
  and result.get('observed_model')=='gpt-6-luna'and result.get('observed_reasoning')=='medium',
  'current exact same-manager task-bound terminal turn must settle before completion adoption')
 app=service._execution(principal=state['manager'],model='gpt-6-luna',reasoning='medium',evidence_id='W0-completion-anchor-read')
 app._verify_native_binding(manager,result['physical_session_id'],schedule)
 from w0_finite_role_allowance import digest as finite_digest
 pool=ResourceRef.from_dict(migrated['new_pool_refs']['manager'])
 require(first['allowance_ref']==pool.to_dict(),'same adopted manager finite pool required')
 reservation=LimitService(owner.store).get_reservation(ResourceRef(pool.authority,'reservation','W0-finite-turn-'+finite_digest([schedule,pool.to_dict()])[:28]))
 require(reservation is not None and reservation.status.value=='consumed'and reservation.pool_ref==pool
  and reservation.declared_units==reservation.actual_units==reservation.charged_units==1,
  'current completed manager turn must preserve its genuinely consumed exact reservation')
 return owner,project,manager,migrated

def plan(service,*,actor):
 owner,project,manager,migrated=current(service,actor)
 memberships=project.payload.get('tasks')or[]
 require(len(memberships)==4,'exact original four W0 task memberships required')
 rows=[]
 for member in memberships:
  pin=ResourceRef.from_dict(member)
  require(pin.authority==project.ref.authority and pin.kind=='work.task','W0 task membership is foreign')
  task=owner.graph.get(ResourceRef(pin.authority,pin.kind,pin.id))
  require(same(task.payload.get('project_ref')or{},project.ref.to_dict())and task.lifecycle.value=='pending',
   'ordinary initial W0 task assessment requires same pending authored task')
  acceptance=task.payload.get('acceptance')
  require(isinstance(acceptance,str)and acceptance.strip(),'original authored acceptance is missing; never invent it')
  aliases=[alias for alias,ref in service.server.state['task_refs'].items()if same(ref,task.ref.to_dict())]
  require(len(aliases)==1,'original service task alias must identify exactly one canonical task')
  rows.append({'task_ref':task.ref.to_dict(),'task_sha256':migration.digest(task.payload),
   'alias':aliases[0],'acceptance':acceptance})
 require(len({r['alias']for r in rows})==4,'original task aliases are ambiguous')
 pool=LimitService(owner.store).get_pool(ResourceRef.from_dict(migrated['new_pool_refs']['final-astra']))
 require(pool is not None and pool.capacity_units==1 and pool.cumulative_allowance_units==1,
  'exact human-authorized one remaining Astra final pool required')
 return {'schema':SCHEMA+'.plan','project_ref':project.ref.to_dict(),'project_sha256':migration.digest(project.payload),
  'manager_ref':manager.ref.to_dict(),'manager_generation':2,'migration_plan_sha256':migrated['plan_sha256'],
  'tasks':rows,'source_review_calls_used':2,'remaining_Astra_final_calls':1,
  'final_pool_snapshot':{k:json_value(getattr(pool,k))for k in('ref','version','current_revision','held_units','cumulative_used_units','remaining_allowance_units')},
  'ordinary_local_judgments':4,'local_judgments_are_not_provider_or_review_calls':True,'provider_called':False}

def adopt(service,*,actor,immutable_plan):
 owner=service.server.owner;p=immutable_plan
 require(actor==owner.owner_actor and p.get('schema')==SCHEMA+'.plan','authenticated exact completion inputs required')
 reports=owner.assignments.list_observations(ResourceRef(owner.store.authority,'wrk.assignment',migration.MANAGER),kind='report')
 matches=[r for r in reports if isinstance(r.value,dict)and r.value.get('schema')==SCHEMA+'.completed'and r.value.get('input_sha256')==migration.digest(p)]
 require(len(matches)<=1,'completion-policy report is ambiguous')
 if matches:
  value={**matches[0].value['result'],'completion_report_ref':matches[0].ref.to_dict(),'replayed':True}
  bind(service,value);return value
 require(plan(service,actor=actor)==p,'current task/project/manager/remaining-final snapshot changed')
 state=service.server.state;configured={'kind':'owner_local_bookkeeping',
  'purpose':'One ordinary provider-free judgment per original W0 authored task; source reviews remain separate',
  'local_only':True,'pool_id':migration.PROJECT+'-original-four-local-judgment-20261013',
  'capacity_units':1,'cumulative_allowance_units':4,'task_criterion_pairs':[]}
 with owner.store.transaction():
  criteria={};scopes={};tasks={}
  for row in p['tasks']:
   alias=row['alias'];name=migration.PROJECT+':'+alias+':original-authored-acceptance'
   scope=AssessmentModule(owner.store,actor=actor,payload_resolver=owner.evidence_payload_resolver).declare_scope(migration.PROJECT+':'+alias+':ordinary-local-completion',
    parent_obligation=ResourceRef.from_dict(row['task_ref']),protocol='ordinary-authored-task-acceptance',
    criteria=[{'id':name,'definition':row['acceptance'],'task_ref':row['task_ref'],'provenance':'canonical original W0 authored task acceptance'}],
    designated_approver=state['manager'],policy={'required_for_completion':True,'local_only':True},
    logical_request_key=KEY+':criterion:'+alias)
   require(len(scope.criterion_refs)==1,'ordinary W0 criterion cardinality changed')
   criterion=scope.criterion_refs[0];tasks[alias]=row['task_ref'];criteria[criterion.id]=criterion.to_dict();scopes[alias]=scope.ref.to_dict()
   configured['task_criterion_pairs'].append({'task':alias,'criterion':criterion.id})
  projection={'authority':owner.store.authority,'project_ref':p['project_ref'],'task_refs':tasks,'criterion_refs':criteria,
   'scope_refs':scopes,'assessment_policy':configured,'provider_called':False,'provider_allowances_changed':False,
   'source_review_calls_used':2,'remaining_Astra_final_calls':1,'final_pool_ref':p['final_pool_snapshot']['ref'],
   'canonical_judgments_recorded':0,'input_sha256':migration.digest(p)}
  policy=LocalAssessmentPolicy.from_run_config(configured,state=projection)
  allocation=owner.create_manager_assessment_pool(project_ref=p['project_ref'],task_ref=next(iter(tasks.values())),
   manager_assignment_ref=p['manager_ref'],manager_actor=state['manager'],manager_generation=2,
   logical_request_key=KEY+':ordinary-local-pool',assessment_policy=policy)
  projection['local_pool_allocation']=json_value(allocation)
  report=owner.assignments.append_report(ResourceRef.from_dict(p['manager_ref']),
   {'schema':SCHEMA+'.completed','input_sha256':migration.digest(p),'result':projection},expected_generation=2,
   logical_request_key=KEY+':completed',actor=actor)
 value={**projection,'completion_report_ref':report.ref.to_dict(),'replayed':False};bind(service,value);return value

def bind(service,projection):
 owner,state=service.server.owner,service.server.state
 require(projection['project_ref']['id']==migration.PROJECT and state['manager_generation']==2,
  'completion policy belongs only to the same migrated W0 view')
 if state.get('W0_completion_policy_input_sha256')==projection['input_sha256']:
  service.commands.policy=LocalAssessmentPolicy.from_run_config(state['assessment_policy'],state=state)
  return {'outcome':'replayed','provider_called':False,'current_manager_projection_preserved':True}
 state.update({k:deepcopy(projection[k])for k in('authority','task_refs','criterion_refs','scope_refs','assessment_policy')})
 state['W0_completion_policy_input_sha256']=projection['input_sha256']
 state['W0_completion_policy_report_ref']=projection['completion_report_ref']
 # Existing commands and runtime paths both consume this same trusted policy.
 service.commands.policy=LocalAssessmentPolicy.from_run_config(state['assessment_policy'],state=state)
 service.server._save_state()
 return {'outcome':'adopted','provider_called':False,'remaining_Astra_final_calls':1}
