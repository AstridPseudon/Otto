"""One original W0 source-derived initializer disposition; no native attestation or retry."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from herzchen.contracts import ResourceRef, canonical_json

SCHEMA='otto.claude-invalid-initializer-custody-disposition.v1'
MARKER='claude_invalid_initializer_custody_release'
HERE=Path(__file__).resolve().parent
ORIGIN=HERE/'prepared/W0-codex-migration-20261013/antecedent-source' if HERE.name=='controller' else HERE/'antecedent-source'
SOURCE_PINS={
 'claude_cli.py':'3f18bbab0a2f26871996c610e76afa3ac8e3fe20a4c3cd50e376c8752b37eb4c',
 'claude_adapter.py':'f1995e6556da2e3b5080e9e0368d1e5ce45373af670dcf704a5983e3d22005aa',
 'gateway.py':'2a51039c3f2ed257a198cca6013c51d6509fa6f33ae553ef3f0dc065a63c2eb7',
 'runtime-manifest.json':'27827e024af455106064812ebc6b50b3ca0e5c47adfb228742b3610510341aa6',
 'physical-ready.json':'9d9085a665cc83ac5b65612f81991d5207ed93b20742c2fd65b6b9484e602455'}
ORIGINAL={'schedule_id':'role-2129ac8a3003148081cb18db51fe',
 'project_id':'project-68aca4e5bce229bddab0b89a6b52',
 'assignment_id':'assignment-1c95154ca88cd31c0c00fbfec5da',
 'fingerprint':'862732617abf36c67ee9ebb7f610a842b22716df82b93ab2a5f9667053585558',
 'generation':1,'model':'claude-haiku-5-5','reasoning':'medium',
 'principal':'otto-work-model-W0-host-ergonomics-manager',
 'lifecycle_owner':'otto-operating-setup-owner'}
ERROR={'code':'claude_qualification_or_capture_held','message':'native identity/model/scope/tool ingress mismatch'}

def require(condition,message):
 if not condition:raise PermissionError(message)

def digest(value):return sha256(canonical_json(value).encode()).hexdigest()

def source_origin(*, controller=None):
 for name,expected in SOURCE_PINS.items():
  p=ORIGIN/name
  require(not p.is_symlink() and p.is_file() and p.stat().st_size<=524288 and sha256(p.read_bytes()).hexdigest()==expected,
          'exact accepted antecedent source/physical receipt changed')
 manifest=json.loads((HERE/'antecedent-source/runtime-manifest.json').read_text())
 physical=json.loads((HERE/'antecedent-source/physical-ready.json').read_text())
 require(physical['runtime_files_all_match']is True and physical['entrypoints_all_match']is True
   and physical['W0_original_schedule']==ORIGINAL['schedule_id'],'original physical source custody proof differs')
 for name in ('claude_cli.py','claude_adapter.py','gateway.py'):
  require(manifest['files']['otto/agents/'+name]==SOURCE_PINS[name],'source manifest component differs')
 if controller is not None:
  root=Path(controller)
  require(sha256((root/'runtime-manifest.json').read_bytes()).hexdigest()==SOURCE_PINS['runtime-manifest.json'],
          'original physical source must remain installed at first disposition')
  for name in ('claude_cli.py','claude_adapter.py','gateway.py'):
   require(sha256((root/'runtime-source/otto/agents'/name).read_bytes()).hexdigest()==SOURCE_PINS[name],
           'first disposition source differs from actual original admitted code')
 return {'kind':'source-derived; native initializer trace was not retained','source_pins':dict(SOURCE_PINS),
   'useful_input_delivered':False,'initializer_process_spawned':True,
   'transport_unwound_owned_process':True,'workspace_initializer_fence':'OS deny workspace writes',
   'native_identity':'unverified','initializer_usage':'unknown','payment':'unknown','native_session_creation':'unknown'}

def inspect(execution,*,schedule_id,controller=None,_due=None,_assignment_proof=None):
 due=_due or execution._read(schedule_id);policy=ORIGINAL
 require(execution.actor==due.lifecycle_owner==due.owner==due.manager_ref==policy['lifecycle_owner'],
         'exact authenticated original lifecycle owner required')
 require(schedule_id==due.schedule_id==policy['schedule_id'] and due.project_ref==policy['project_id']
   and due.assignment_ref['id']==policy['assignment_id'] and due.generation==policy['generation']
   and due.recipient==policy['principal'] and due.role=='manager' and due.execution_mode=='fresh_manager'
   and due.profile=='workspace-write' and due.stop_state=='active' and due.completion_state=='none'
   and due.requested_model==policy['model'] and due.requested_reasoning==policy['reasoning']
   and due.in_flight_request and not due.accepted_checkins and due.last_result is None
   and due.delivery_evidence is None and due.completion_evidence is None,'exact original pre-useful-input manager differs')
 reader=execution.portfolio.operations._owner_reader
 if _assignment_proof is None:
  assigned=reader.get_record(ResourceRef.from_dict(due.assignment_ref))
  require(assigned is not None,'original manager record missing')
  assignment_proof={'ref':assigned.ref.to_dict(),**{k:assigned.payload.get(k)for k in('role','principal','generation','session','scope')}}
 else:
  require(_due is not None,'historical assignment proof is not a public caller input')
  assignment_proof=dict(_assignment_proof)
 require(assignment_proof.get('ref')==due.assignment_ref
   and assignment_proof.get('role')=='manager' and assignment_proof.get('principal')==due.recipient
   and assignment_proof.get('generation')==due.generation and assignment_proof.get('session')is None
   and assignment_proof.get('scope',{}).get('id')==due.project_ref,
   'exact original authenticated manager assignment differs')
 if _due is None:execution._current(due.assignment_ref,due.generation)
 attempt=(due.host_evidence or{}).get('gateway_attempt')or{};result=attempt.get('result')or{}
 require(attempt.get('state')=='result' and result.get('outcome')=='unknown'
   and result.get('delivery_state')=='unknown' and result.get('error')==ERROR
   and result.get('unknown_reason')==ERROR['message'] and result.get('operation')=='invoke'
   and result.get('timeout')is False and result.get('replayed')is False
   and all(result.get(k)is None for k in('physical_session_id','native_session_id','observed_model','observed_reasoning'))
   and all(attempt.get(k)is None for k in('physical_session_id','delivery_authorization','delivery_admission','manager_acceptance'))
   and not result.get('useful_input_observed') and not result.get('raw_result'),
   'exact original invalid initializer result required; no arbitrary UNKNOWN release')
 for body in(attempt,result):
  require(body.get('request_fingerprint')==policy['fingerprint'] and body.get('assignment_ref')==due.assignment_ref
    and body.get('generation')==due.generation and body.get('logical_request_key')==due.in_flight_request,
    'original attempt fingerprint/identity differs')
 require(result.get('logical_agent_id')==result.get('owner')==due.recipient
   and result.get('project_ref')==due.target['project_ref'] and result.get('task_ref')==due.target['task_ref']
   and result.get('requested_model')==due.requested_model and result.get('requested_reasoning')==due.requested_reasoning
   and result.get('requested_profile')==due.profile and due.target.get('native_adapter')=='otto.adapter.claude-code-2.1.293.leaf.v1'
   and not any(due.target.get(k)for k in('native_id','native_session_id','physical_session_id','native_binding')),
   'original model/project/task/adapter identity differs')
 proof=source_origin(controller=controller)
 return {'schedule_id':schedule_id,'due_version':due.version,'due_sha256':digest(due.to_dict()),
   'result_sha256':digest(result),'assignment_ref':due.assignment_ref,'generation':due.generation,
   'project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],'principal':due.recipient,
   'request_fingerprint':policy['fingerprint'],'allowance_ref':due.allowance_ref,'source_proof':proof,
   'assignment_snapshot':assignment_proof}

def retained(execution,due):
 marker=(due.host_evidence or{}).get(MARKER)or{}
 require(marker.get('schema')==SCHEMA and due.stop_state=='stopped' and due.in_flight_request is None,
         'exact stopped initializer custody disposition required')
 reader=execution.portfolio.operations._owner_reader
 report=reader.get_record(ResourceRef.from_dict(marker['disposition_ref']))
 require(report is not None and report.ref.to_dict()==marker['disposition_ref']
   and report.payload.get('assignment')==due.assignment_ref and report.payload.get('generation')==due.generation
   and report.payload.get('record_type')=='work.observation' and report.payload.get('observation_kind')=='report',
   'canonical original assignment disposition required')
 body=report.payload['value'];scope=body.get('scope')or{}
 require(body.get('schema')==SCHEMA and body.get('provider_retry_allowed')is False
   and body.get('unknown_result_preserved')is True and body.get('initializer_usage')=='unknown'
   and body.get('payment')=='unknown' and body.get('native_session_creation')=='unknown',
   'initializer uncertainty was rewritten or replay authorized')
 before=replace(due,**body['before'],version=scope['due_version'],
   host_evidence={k:v for k,v in due.host_evidence.items()if k!=MARKER})
 require(inspect(execution,schedule_id=due.schedule_id,_due=before,_assignment_proof=scope['assignment_snapshot'])==scope,
         'retained original initializer proof changed')
 require(any(e.operation=='work.report.append' and e.actor==execution.binding.authenticated_actor(execution.actor)
   for e in reader.list_events(subjects=(report.ref,))),'disposition requires authentic lifecycle-owner append')
 return body

def release(execution,*,schedule_id,request_key,expected_fingerprint,controller,host):
 require(expected_fingerprint==ORIGINAL['fingerprint'] and request_key and request_key.strip()==request_key,
         'exact original fingerprint and stable disposition key required')
 require(not host._executions and not host._external_waiting and not host._children,
         'all actual admitted native/transport work must settle before closed initializer disposition')
 due=execution._read(schedule_id)
 if (due.host_evidence or{}).get(MARKER):
  body=retained(execution,due);require(body['request_key']==request_key,'disposition replay key differs')
  host.restore_execution(execution,due)
  return {'outcome':'replayed','provider_called':False,'disposition':due.host_evidence[MARKER]}
 scope=inspect(execution,schedule_id=schedule_id,controller=controller)
 body={'schema':SCHEMA,'request_key':request_key,'scope':scope,'provider_retry_allowed':False,
   'unknown_result_preserved':True,'initializer_usage':'unknown','payment':'unknown','native_session_creation':'unknown',
   'before':{k:due.to_dict()[k]for k in('stop_state','completion_state','in_flight_request')}}
 current=execution._current(due.assignment_ref,due.generation)
 report=execution.assignments.append_report(current.ref,body,expected_generation=due.generation,
   logical_request_key=request_key,actor=execution.binding.authenticated_actor(execution.actor))
 require(digest(execution._read(schedule_id).to_dict())==scope['due_sha256'],'original occurrence changed before custody retirement')
 marker={'schema':SCHEMA,'disposition_ref':report.ref.to_dict(),'provider_retry_allowed':False}
 saved=replace(due,stop_state='stopped',in_flight_request=None,
   host_evidence={**due.host_evidence,MARKER:marker})
 execution.due_port.save_due(schedule_id,saved.to_dict(),request_id=request_key+':stop',expected_version=due.version)
 host.restore_execution(execution,execution._read(schedule_id))
 return {'outcome':'released','provider_called':False,'scope':scope,'disposition':marker}
