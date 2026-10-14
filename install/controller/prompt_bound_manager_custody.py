"""Exact original complete-prompt pre-spawn refusal; retain same native lineage."""
from dataclasses import replace
import hashlib,json
from pathlib import Path
from herzchen.contracts import ResourceRef,canonical_json

HERE=Path(__file__).resolve().parent
ORIGIN=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller/prepared/W0-codex-migration-20261013/antecedent-source')
SCHEMA='otto.manager-prompt-bound-custody-disposition.v1'
MARKER='manager_prompt_bound_custody_release'
PROOF_SHA='1a1cce975a8d5a24ede96d5a3c3de7440d48cf01ada4a022f0f494d9fa2dfb1f'
HOST_SHA='5b64eed50c0004bfb2061bc8b98c2966d0505334b2217129ce7247b4ed4edf69'
ORIGINAL={'schedule_id':'manager-directive-9765b8478ad0f1cb773de3247e25',
 'assignment_id':'assignment-75f5d309013dbde5281773606431','generation':1,
 'project_id':'project-b813b18d65ad1cdb6e694c80fd5e','principal':'otto-astrid-port-manager-1',
 'fingerprint':'7ef20e868704d51b2e90fa79f23bc75f080bbcf41835278497ceaaa64420961d',
 'session':'01a12866-8bf8-7c70-a35e-e8b8257d51c2','lifecycle_owner':'otto-operating-setup-owner',
 'stderr':'prompt_size_limit_exceeded: characters=1008512, utf8_bytes=1009680, limit=1000000; no process started',
 'input_packet_digest':'1ad7af263fd35651ccaa00db9577d72bcbc1c9165a928b9cc8797105087d6c82'}

REPEATED={**ORIGINAL,'schedule_id':'manager-directive-43c88c1bbb8d48b76dc70da76325',
 'fingerprint':'d4312777729809456d8498a800532e2b44a89b3fbf92d1b92713671775bb6f9d',
 'stderr':'prompt_size_limit_exceeded: characters=1008901, utf8_bytes=1010001, limit=1000000; no process started',
 'brief_sha256':'8ba521730720f19b1343088860c261c36a9b65376c97cf3205cea9992f1f5eaa',
 'transport_sha256':'e7d1fdf770f423153fa6ccdce257e583222b5e491a653780c64542bd98f62e91'}
REPEATED_ORIGIN=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller/prepared/shared-prompt-refusal-d470-20261013/prompt-refusal-d470-transport.json')
def exact_policy(due):
 if due.schedule_id==ORIGINAL['schedule_id']:return ORIGINAL
 if due.schedule_id==REPEATED['schedule_id']:return REPEATED
 raise PermissionError('only the two exact source-qualified prompt refusals are authorized')

def require(value,message):
 if not value:raise PermissionError(message)
def digest(value):return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def source_origin(controller=None,policy=None):
 policy=policy or ORIGINAL
 for name,pin in(('codex_host.py',HOST_SHA),('prompt-refusal-transport.json',PROOF_SHA)):
  path=REPEATED_ORIGIN if name=='prompt-refusal-transport.json'and policy is REPEATED else ORIGIN/name
  if name=='prompt-refusal-transport.json'and policy is REPEATED:pin=REPEATED['transport_sha256']
  require(not path.is_symlink() and path.stat().st_size<=524288 and hashlib.sha256(path.read_bytes()).hexdigest()==pin,
    'exact accepted prompt guard/transport extraction changed')
 if controller is not None:
  require(hashlib.sha256((Path(controller)/'runtime-source/herzchen/adapters/host.py').read_bytes()).hexdigest()==HOST_SHA,
    'original prompt-size guard code differs')
 return {'source_guard_sha256':HOST_SHA,'original_transport_extraction_sha256':policy.get('transport_sha256',PROOF_SHA),
   'process_started':False,'useful_input_delivered':False,'original_unknown_retained':True,
   'previous_native_session_preserved':ORIGINAL['session']}

def settled_anchor(execution,due):
 pin=due.target.get('native_binding')or{}
 require(set(pin)=={'schedule_id','due_sha256'} and pin['schedule_id']!=due.schedule_id,
   'original prompt refusal requires its independently settled native anchor')
 anchor=execution._read(pin['schedule_id'])
 require(digest(anchor.to_dict())==pin['due_sha256'] and anchor.role==due.role=='manager'
   and anchor.recipient==due.recipient and anchor.generation==due.generation
   and all(anchor.assignment_ref[k]==due.assignment_ref[k]for k in('authority','kind','id'))
   and anchor.target['project_ref']['id']==due.target['project_ref']['id']
   and anchor.target['task_ref']['id']==due.target['task_ref']['id']
   and anchor.stop_state=='completed' and anchor.completion_state=='succeeded' and anchor.in_flight_request is None,
   'original prior native settlement differs')
 prior=((anchor.host_evidence or{}).get('gateway_attempt')or{}).get('result')or{}
 require(prior.get('outcome')=='succeeded' and prior.get('context_digest_verified')is True
   and prior.get('physical_session_id')==ORIGINAL['session'] and prior.get('observed_turn_id')
   and (anchor.last_result or{}).get('physical_session_id')==ORIGINAL['session'],
   'UNKNOWN refusal is not proof of a prior useful native turn')
 return anchor

def inspect(execution,*,schedule_id,controller=None,_due=None,_assignment_proof=None):
 due=_due or execution._read(schedule_id);policy=exact_policy(due)
 require(execution.actor==due.owner==due.lifecycle_owner==due.manager_ref==policy['lifecycle_owner'],
   'exact lifecycle-owner prompt disposition required')
 require(due.schedule_id==schedule_id==policy['schedule_id'] and due.project_ref==policy['project_id']
   and due.assignment_ref['id']==policy['assignment_id'] and due.generation==policy['generation']
   and due.recipient==policy['principal'] and due.role=='manager' and due.execution_mode=='continue_existing'
   and due.stop_state=='active' and due.completion_state=='none' and due.in_flight_request,
   'exact original retained manager prompt scope differs')
 reader=execution.portfolio.operations._owner_reader
 if _assignment_proof is None:
  record=reader.get_record(ResourceRef.from_dict(due.assignment_ref));require(record is not None,'original manager assignment missing')
  assignment_proof={'ref':record.ref.to_dict(),**{k:record.payload.get(k)for k in('role','principal','generation','scope')}}
 else:assignment_proof=dict(_assignment_proof)
 require(assignment_proof['ref']==due.assignment_ref and assignment_proof['role']=='manager'
   and assignment_proof['principal']==due.recipient and assignment_proof['generation']==due.generation
   and assignment_proof['scope']['id']==due.project_ref,'original prompt manager identity differs')
 if _due is None:execution._current(due.assignment_ref,due.generation)
 attempt=(due.host_evidence or{}).get('gateway_attempt')or{};result=attempt.get('result')or{};raw=result.get('raw_result')or{}
 work=raw.get('work_envelope')or{};authorization=raw.get('owner_delivery_authorization')or{}
 require(attempt.get('state')=='result' and result.get('outcome')=='unknown' and result.get('delivery_state')=='unknown'
   and (result.get('error')or{}).get('code')=='authorized_result_unverified'
   and result.get('context_digest_verified')is False and result.get('observed_turn_id')is None
   and result.get('physical_session_id')==result.get('native_session_id')==policy['session']
   and raw.get('transport_operation')=='resume' and work.get('status')=='failed'
   and work.get('process_id')is None and work.get('exit_status')is None and work.get('stdout')==''
   and work.get('delivery_state')=='not_started' and work.get('unsupported_error')=='prompt_size_limit_exceeded'
   and work.get('stderr')==policy['stderr'] and work.get('reconciliation')==policy['stderr']
   and work.get('input_packet_digest')==policy['input_packet_digest'],
   'exact source-backed complete-prompt refusal before process creation required')
 for body in(attempt,result):
  require(body.get('assignment_ref')==due.assignment_ref and body.get('generation')==due.generation
    and body.get('logical_request_key')==due.in_flight_request and body.get('request_fingerprint')==policy['fingerprint'],
    'original prompt attempt fingerprint/assignment differs')
 require(attempt.get('delivery_authorization')==authorization
   and authorization.get('owner_version')==5 and authorization.get('brief_sha256')==policy.get('brief_sha256','0c4a06e3fbf62ae0bb75ab1da9870c33b1a7a888cf42de8c407f13646ca8d26c')
   and authorization.get('status')=='authorized' and authorization.get('assignment_ref')==due.assignment_ref
   and authorization.get('generation')==due.generation and authorization.get('logical_request_key')==due.in_flight_request
   and authorization.get('principal')==due.recipient and authorization.get('role')=='manager'
   and authorization.get('lifecycle_owner')==execution.actor and authorization.get('physical_session_id')==policy['session']
   and authorization.get('project_ref')==due.target['project_ref'] and authorization.get('task_ref')==due.target['task_ref'],
   'exact existing-session owner authorization missing or foreign')
 if policy is REPEATED:require(raw.get('initialization_envelope')is None,'cached initialized-session path must remain honest; no new initializer claim')
 anchor=settled_anchor(execution,due)
 return {'schedule_id':schedule_id,'due_version':due.version,'due_sha256':digest(due.to_dict()),
   'result_sha256':digest(result),'assignment_ref':due.assignment_ref,'generation':due.generation,
   'assignment_snapshot':assignment_proof,'project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],
   'principal':due.recipient,'request_fingerprint':policy['fingerprint'],'prior_native_session':policy['session'],
   'settled_anchor_schedule_id':anchor.schedule_id,'settled_anchor_sha256':digest(anchor.to_dict()),
   'allowance_ref':due.allowance_ref,'source_proof':source_origin(controller,policy)}

def retained(execution,due):
 marker=(due.host_evidence or{}).get(MARKER)or{}
 require(marker.get('schema')==SCHEMA and due.stop_state=='stopped' and due.in_flight_request is None,
   'exact prompt refusal disposition required')
 reader=execution.portfolio.operations._owner_reader;report=reader.get_record(ResourceRef.from_dict(marker['disposition_ref']))
 require(report is not None and report.ref.to_dict()==marker['disposition_ref']
   and report.payload.get('assignment')==due.assignment_ref and report.payload.get('generation')==due.generation,
   'canonical prompt disposition assignment differs')
 body=report.payload['value'];scope=body.get('scope')or{}
 require(body.get('schema')==SCHEMA and body.get('provider_retry_allowed')is False
   and body.get('original_unknown_retained')is True,'prompt refusal cannot authorize replay or overwrite UNKNOWN')
 require(any(e.operation=='work.report.append' and e.actor==execution.binding.authenticated_actor(execution.actor)
   for e in reader.list_events(subjects=(report.ref,))),'prompt disposition lacks authenticated lifecycle owner event')
 before=replace(due,**body['before'],version=scope['due_version'],host_evidence={k:v for k,v in due.host_evidence.items()if k!=MARKER})
 require(inspect(execution,schedule_id=due.schedule_id,_due=before,_assignment_proof=scope['assignment_snapshot'])==scope,
   'original prompt refusal/settled lineage changed')
 return body

def release(execution,*,schedule_id,request_key,expected_fingerprint,controller,host):
 require(expected_fingerprint==exact_policy(execution._read(schedule_id))['fingerprint'] and request_key and request_key.strip()==request_key,
   'exact original prompt fingerprint/disposition key required')
 require(not host._executions and not host._children and not host._external_waiting,
   'actual native/transport work must settle before closed prompt disposition')
 due=execution._read(schedule_id)
 if (due.host_evidence or{}).get(MARKER):
  body=retained(execution,due);require(body['request_key']==request_key,'prompt disposition replay key differs')
  host.restore_execution(execution,due);return {'outcome':'replayed','provider_called':False,'disposition':due.host_evidence[MARKER]}
 scope=inspect(execution,schedule_id=schedule_id,controller=controller)
 body={'schema':SCHEMA,'request_key':request_key,'scope':scope,'provider_retry_allowed':False,
   'original_unknown_retained':True,'same_native_session_required':True,
   'before':{k:due.to_dict()[k]for k in('stop_state','completion_state','in_flight_request')}}
 current=execution._current(due.assignment_ref,due.generation)
 report=execution.assignments.append_report(current.ref,body,expected_generation=due.generation,
   logical_request_key=request_key,actor=execution.binding.authenticated_actor(execution.actor))
 require(digest(execution._read(schedule_id).to_dict())==scope['due_sha256'],'prompt occurrence changed before disposition')
 marker={'schema':SCHEMA,'disposition_ref':report.ref.to_dict(),'provider_retry_allowed':False}
 retired=replace(due,stop_state='stopped',in_flight_request=None,host_evidence={**due.host_evidence,MARKER:marker})
 execution.due_port.save_due(schedule_id,retired.to_dict(),request_id=request_key+':stop',expected_version=due.version)
 host.restore_execution(execution,execution._read(schedule_id))
 return {'outcome':'released','provider_called':False,'disposition':marker,'scope':scope}
