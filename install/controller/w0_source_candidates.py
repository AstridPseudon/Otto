"""Finite factual W0 owner source publication; no worker/native result claims.
Current original task heads and accepted patch/runtime hashes are retained.
The same Luna manager supplies all judgments through the ordinary commands.
"""
from copy import deepcopy
from pathlib import Path
from types import MethodType
import hashlib,json
from herzchen.contracts import ResourceRef
import w0_same_manager_migration as migration
import w0_completion_policy as completion
C=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller')
D=C/'prepared/W0-codex-luna-handoff-20261013'
FEATURES=C/'prepared/W0-codex-migration-next-20261013/feature-source-pins.json'
KEY='W0-existing-E1-E4-owner-source-candidates-20261013-v1'
SCHEMA='otto.W0-owner-source-candidates.v1'
FILES={'E1':('otto/hostctl/cli.py','otto/hostctl/service.py'),'E2':('otto/hostctl/cli.py',),
 'E3':('otto/hostctl/portfolio.py','otto/hostctl/portfolio_apply.py','otto/portfolio/shared_documents.py'),
 'E4':('otto/hostctl/skills.py',)}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path,limit=131072):
 path=Path(path);completion.require(path.is_file()and not path.is_symlink()and path.stat().st_size<=limit,'exact bounded source evidence file required')
 with path.open('rb')as stream:raw=stream.read(limit+1)
 completion.require(len(raw)<=limit,'source evidence grew beyond its bound')
 return raw.decode()

def preview(service,*,actor):
 owner,project,manager,_=completion.current(service,actor)
 completion.require(service.commands.policy is not None and service.server.state.get('W0_completion_policy_report_ref'),
  'original four local assessment scopes must be adopted before source candidate publication')
 pins=json.loads(read(FEATURES))['files'];manifest=json.loads(read(C/'runtime-manifest.json',262144))
 tasks=[];sources={}
 for alias,names in FILES.items():
  task=owner.graph.get(ResourceRef.from_dict(service.server.state['task_refs'][alias]))
  completion.require(task.lifecycle.value=='pending'and completion.same(task.payload['project_ref'],project.ref.to_dict()),'exact original pending W0 task required')
  selected={}
  for name in names:
   completion.require(manifest['files'][name]==pins[name]['after']==sha(C/'runtime-source'/name),'accepted actual runtime source pin differs')
   selected[name]=pins[name]['after']
  patch=D/(alias+'-codex-preparation.patch');receipt=D/(alias+'-source-preparation-receipt.json')
  patch_body=read(patch);receipt_body=read(receipt)
  # Entire existing patch and source receipt, not instruction prose or a fake
  # completed worker envelope, form the immutable delivered artifact snapshot.
  sources[alias]={'patch_path':str(patch),'patch_sha256':sha(patch),'receipt_path':str(receipt),'receipt_sha256':sha(receipt),'runtime_source_sha256':selected}
  tasks.append({'alias':alias,'task_ref':task.ref.to_dict(),'task_sha256':migration.digest(task.payload),'acceptance':task.payload['acceptance']})
 source_receipt=D/'combined-source-integration-receipt.json';joined=json.loads(read(source_receipt))
 completion.require(joined['validation']['result'].startswith('passed: 74 tests')and joined['human_review_cap']['source_advisory_reviews_completed']==2
  and joined['human_review_cap']['remaining_calls_across_future_canonical_final_or_rework_review']==1,'original tested source/review provenance differs')
 skill=C/'evidence/W0-E4-actual-installed-skill-closure-20261013.json';read(skill)
 return {'schema':SCHEMA+'.plan','project_ref':project.ref.to_dict(),'manager_ref':manager.ref.to_dict(),'generation':2,
  'tasks':tasks,'sources':sources,'joined_source_receipt':{'path':str(source_receipt),'sha256':sha(source_receipt)},
  'actual_skill_receipt':{'path':str(skill),'sha256':sha(skill)},'runtime_manifest_sha256':sha(C/'runtime-manifest.json'),
  'completion_policy_input_sha256':service.server.state['W0_completion_policy_input_sha256'],
  'source_reviews_used':2,'final_calls_remaining':1,'provider_called':False,'source_work_replayed':False,'judgments_recorded':0}

def publish(service,*,actor,immutable_plan):
 owner=service.server.owner;p=immutable_plan
 completion.require(actor==owner.owner_actor and p.get('schema')==SCHEMA+'.plan','authentic exact W0 source publication inputs required')
 record_id='report-'+hashlib.sha256((migration.MANAGER+':'+KEY+':published').encode()).hexdigest()[:28]
 old=owner.consumer_operations()._owner_reader.get_record(ResourceRef(owner.store.authority,'wrk.report',record_id))
 if old is not None:
  body=old.payload.get('value')or{}
  completion.require(body.get('schema')==SCHEMA+'.published'and body.get('input_sha256')==migration.digest(p),'original candidate publication input changed')
  bind(service,body['result']);return {**body['result'],'replayed':True}
 completion.require(preview(service,actor=actor)==p,'current original source/task/policy inputs changed before publication')
 candidates={}
 with owner.store.transaction():
  for task in p['tasks']:
   alias=task['alias'];source=p['sources'][alias]
   value={'schema':SCHEMA+'.candidate','origin':'existing owner source preparation','project_ref':p['project_ref'],
    'task_ref':task['task_ref'],'original_task_sha256':task['task_sha256'],'acceptance':task['acceptance'],
    'patch':{'path':source['patch_path'],'sha256':source['patch_sha256'],'content':read(source['patch_path'])},
    'source_receipt':{'path':source['receipt_path'],'sha256':source['receipt_sha256'],'content':json.loads(read(source['receipt_path']))},
    'actual_runtime_source_sha256':source['runtime_source_sha256'],'joined_source_receipt':p['joined_source_receipt'],
    'actual_skill_receipt':p['actual_skill_receipt']if alias=='E4'else None,
    'runtime_manifest_sha256':p['runtime_manifest_sha256'],'worker_invocation':None,'native_result_claim':False,
    'source_tests_consumed':74,'source_reviews_consumed':2,'reviewer_observed_settings':'unavailable',
    'final_review_calls_remaining':1,'canonical_acceptance':'unjudged','installed_use':'judge each original criterion against actual available use evidence; source installation alone is not task acceptance'}
   completion.require(len(json.dumps(value).encode())<=131072,'complete source candidate exceeds finite assessment bound')
   report=owner.assignments.append_report(ResourceRef.from_dict(p['manager_ref']),value,expected_generation=2,
    logical_request_key=KEY+':candidate:'+alias,actor=actor)
   candidates[alias]={'task_ref':task['task_ref'],'candidate_ref':report.ref.to_dict(),'body_sha256':migration.digest(value)}
  result={'input_sha256':migration.digest(p),'project_ref':p['project_ref'],'manager_ref':p['manager_ref'],'generation':2,
   'candidates':candidates,'source_tests_replayed':False,'worker_invocations':0,'provider_called':False,'judgments_recorded':0}
  report=owner.assignments.append_report(ResourceRef.from_dict(p['manager_ref']),{'schema':SCHEMA+'.published',
   'input_sha256':migration.digest(p),'result':result},expected_generation=2,logical_request_key=KEY+':published',actor=actor)
 result['publication_report_ref']=report.ref.to_dict();bind(service,result);return {**result,'replayed':False}

def bind(service,projection):
 service.server.state['W0_owner_source_candidates']=deepcopy(projection['candidates'])
 service.server.state['W0_owner_source_candidates_input_sha256']=projection['input_sha256']
 service.server._save_state();install_review_input(service)

def install_review_input(service):
 commands=service.commands
 if getattr(commands,'_W0_owner_candidate_hook',False):return
 original=commands.review_input
 def review_input(self,alias):
  source=(self.state.get('W0_owner_source_candidates')or{}).get(alias)
  if source is None or (self.state.get('workers')or{}).get(alias):return original(alias)
  self._authorize();task_ref=self.state['task_refs'][alias]
  task=self.owner.graph.reader.get_identity(ResourceRef.from_dict(task_ref))
  if task is None or task.payload.get('lifecycle')=='completed':return original(alias)
  completion.require(source['task_ref']==task_ref,'owner source candidate task head changed; preserve previous review before refreshing')
  pin=ResourceRef.from_dict(source['candidate_ref']);record=self.owner.consumer_operations()._owner_reader.get_record(pin)
  body=record.payload.get('value')if record else None
  completion.require(record is not None and record.ref==pin and record.payload.get('assignment',{}).get('id')==migration.MANAGER
   and record.payload.get('generation')==2 and isinstance(body,dict)and body.get('schema')==SCHEMA+'.candidate'
   and body.get('task_ref')==task_ref and migration.digest(body)==source['body_sha256']
   and any(event.operation=='work.report.append'and event.actor==self.owner.owner_actor
    for event in self.owner.consumer_operations()._owner_reader.list_events(subjects=(record.ref,))),
   'authentic original task-bound owner source candidate missing or changed')
  policy=self._review_policy(alias)
  return {'outcome':'read','task_ref':task_ref,'candidate_ref':pin.to_dict(),'source_refs':[pin.to_dict()],
   'evidence_refs':[pin.to_dict()],'candidate_content':body,'candidate_body_sha256':source['body_sha256'],
   'assessment_policy_selection':self._review_policy_pin(alias,policy),'criterion_aliases':self._review_criteria(task_ref,policy),
   'inspection_schema':self._inspection_schema(),'judgment_schema':self._judgment_schema(),'provider_called':False,
   'worker_invocation':None,'canonical_acceptance':'unjudged','next_action':'Inspect this exact existing source artifact and original criterion; use ordinary review-task and finish-task. Do not replay workers or the consumed 74-test batch.'}
 commands.review_input=MethodType(review_input,commands);commands._W0_owner_candidate_hook=True
