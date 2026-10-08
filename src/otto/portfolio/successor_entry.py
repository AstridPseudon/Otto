"""Owner-admitted one-use successor after a proven pre-dispatch rejection.

No occurrence is reset or created. Historical binding/custody bytes remain
provenance; a separately pinned admission names the current installed code.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping
from .attention_binding import _digest, _need, _validate_binding
from .operator import checked_file

_SCHEMA = 'otto.same-occurrence-successor-admission.v1'
_FAILURE = 'result capability requires the admitted project/task scope'
_FILES = ('binding','custody','creation_intent','creation_receipt','packet','intent','uncertain','reconciliation','reconciliation_report','observation','runner')

def _pinned(pin):
    _need(isinstance(pin,Mapping) and set(pin)=={'path','sha256'}, 'exact predecessor file pin required')
    path=Path(pin['path']);raw=checked_file(path)
    _need(hashlib.sha256(raw).hexdigest()==pin['sha256'], 'predecessor bytes changed: '+path.name)
    return raw

def _proof(admission, expected_sha256):
    _need(admission.get('schema')==_SCHEMA and _digest(admission)==expected_sha256, 'successor admission digest/schema mismatch')
    _need(admission.get('entry_module_sha256')==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'successor installed entry changed')
    pins=admission.get('predecessor',{});_need(set(pins)==set(_FILES), 'complete predecessor evidence required')
    raw={k:_pinned(v) for k,v in pins.items()}
    data={k:json.loads(v) for k,v in raw.items() if k not in ('runner','reconciliation_report')}
    old=data['binding'];custody=data['custody'];packet=data['packet'];intent=data['intent'];uncertain=data['uncertain'];reconciliation=data['reconciliation'];observation=data['observation']
    _need(custody['binding_sha256']==_digest(old)==packet['binding_sha256'], 'predecessor binding chain mismatch')
    _need(custody['path']==old['attention_path'] and custody['authority']==old['attention_authority'], 'original attention identity mismatch')
    create=data['creation_intent'];receipt=data['creation_receipt']
    _need(create.get('create_only') is True and create.get('binding_sha256')==_digest(old) and create.get('attention_path')==custody['path'], 'creation intent mismatch')
    for key in ('binding','custody','packet'):
        _need(receipt.get('artifacts',{}).get(Path(pins[key]['path']).name)==pins[key]['sha256'], 'creation receipt chain mismatch: '+key)
    _need(receipt.get('provider_invoked') is False and receipt.get('claim') is None and receipt.get('native_id') is None, 'creation receipt has effects')
    _need(reconciliation.get('schema')=='otto.o12.o16-pre-dispatch-reconciliation.v1' and reconciliation.get('classification')=='known_pre_dispatch_no_provider_effect' and reconciliation.get('provider_invoked') is False and reconciliation.get('intent_preserved') is True and reconciliation.get('uncertain_preserved') is True and reconciliation.get('relaunch') is False, 'predecessor is not proven effect-free')
    for key in ('binding','custody','packet','intent','uncertain','observation','reconciliation_report','runner'):
        _need(reconciliation.get('artifacts_sha256',{}).get(Path(pins[key]['path']).name)==pins[key]['sha256'], 'reconciliation chain mismatch: '+key)
    _need(reconciliation.get('report_sha256')==pins['reconciliation_report']['sha256'], 'reconciliation report mismatch')
    _need(hashlib.sha256(checked_file(Path(packet['launcher']).resolve(strict=True))).hexdigest()==packet['launcher_sha256'], 'launcher changed')
    expected_absent={'o16-invoke-result.json','o16-due-after.json','host-context.jsonl'}
    _need(set(reconciliation.get('result_files_absent',[]))==expected_absent, 'predecessor absence evidence incomplete')
    for name in expected_absent:
        path=Path(pins['intent']['path']).parent/name
        _need(not path.exists() and not path.is_symlink(), 'predecessor provider/result evidence now exists')
        _need(observation.get('files',{}).get(name,{}).get('exists') is False, 'predecessor absence observation missing')
    context=Path(packet['host_context_path'])
    _need(not context.exists() and not context.is_symlink(), 'prior provider host context exists')
    inv=packet.get('invocation',{});scope=old['scope'];key=scope['logical_request_key']
    calculated=_digest({**packet,'invocation':{k:v for k,v in inv.items() if k!='packet_digest'}})
    _need(packet.get('schema')=='otto.o16.t01.single-invocation.v1' and inv.get('packet_digest')==calculated, 'predecessor packet changed')
    _need(inv.get('role')=='worker' and inv.get('mode')=='direct' and inv.get('operation')=='invoke' and inv.get('lifecycle')=='launch' and not inv.get('request') and 'physical_session_id' not in inv, 'successor only supports the original fresh worker invoke')
    _need(inv.get('schedule_id')==scope['schedule_id'] and inv.get('logical_request_key')==key and inv.get('expected_generation')==scope['generation'], 'occurrence changed')
    for ref in ('project_ref','task_ref','assignment_ref','mandate_ref'):_need(inv.get(ref)==scope[ref], 'invocation scope changed')
    _need(intent=={'packet_sha256':pins['packet']['sha256'],'packet_digest':calculated,'schedule_id':scope['schedule_id'],'due_version':1}, 'consumed intent does not match exact occurrence')
    _need(uncertain.get('intent')==intent and uncertain.get('exception_type')=='PermissionError' and uncertain.get('message')==_FAILURE and uncertain.get('relaunch') is False, 'uncertain predecessor is not the proved rejection')
    due_sha=admission.get('due_sha256');r_due=reconciliation.get('due',{});o_due=observation.get('due',{})
    _need(due_sha==r_due.get('canonical_sha256')==o_due.get('sha256')==packet.get('due_sha256')==receipt.get('due_record_sha256'), 'DueRecord digest chain mismatch')
    _need(r_due.get('version')==o_due.get('version')==packet.get('due_version')==receipt.get('due_version')==1 and r_due.get('state')==o_due.get('delivery_state')=='ready' and r_due.get('gateway_attempt') is None and r_due.get('native_id') is None and o_due.get('gateway_attempt') is None and o_due.get('last_result') is None and o_due.get('in_flight_request')==key, 'predecessor occurrence already has an effect')
    current=admission.get('current_binding',{})
    allowed={'python','python_sha256','module_sha256'}
    _need({k:v for k,v in current.items() if k not in allowed}=={k:v for k,v in old.items() if k not in allowed}, 're-admission changed original scope/custody')
    _need(admission.get('no_retry') is True and admission.get('same_occurrence') is True, 'single successor authority required')
    target=Path(pins['intent']['path']).with_name(Path(pins['intent']['path']).stem+'-successor.json')
    _need(admission.get('successor_intent_path')==str(target), 'successor intent must have deterministic predecessor location')
    return data,target

@contextmanager
def _open(operator, admission, expected_sha256):
    from herzchen.kernel.store import Store
    from herzchen.command_ports import close_consumer_facade
    from otto.attention import due_record_contribution,issue_store_due_record_port
    data,target=_proof(admission,expected_sha256)
    current=admission['current_binding'];custody=data['custody']
    path,guard=_validate_binding(operator,current,_digest(current),exists=True)
    info=path.stat()
    _need([info.st_dev,info.st_ino]==custody['device_inode'], 'original attention file replaced')
    # Original custody retains its original binding digest; no fabricated
    # successor creation receipt is substituted for it.
    store=Store.open(path,authority=custody['authority'],expected_domains=[due_record_contribution()],expected_domain_digest=custody['domain_descriptor_digest'])
    port=None
    try:
        port=issue_store_due_record_port(store.domain_handler([due_record_contribution()]),operator.owner.owner_actor,external_assignment_guard=guard)
        yield port,data,target
    finally:
        if port is not None:close_consumer_facade(port.transport)
        store.close()

def _due(port, admission):
    from otto.attention import DueRecord,native_target_identity
    scope=admission['current_binding']['scope'];value=port.read_due(scope['schedule_id'])
    _need(value is not None and _digest(value)==admission['due_sha256'], 'current DueRecord changed')
    record=DueRecord.from_dict(value);evidence=record.host_evidence or {}
    _need(record.version==1 and record.delivery_state=='ready' and record.in_flight_request==scope['logical_request_key'] and record.stop_state=='active' and evidence.get('gateway_attempt') is None and native_target_identity(record.target) is None and record.last_result is None and record.delivered_at is None and record.delivery_evidence is None and record.completed_at is None and record.completion_evidence is None and record.last_completed_request is None, 'current occurrence has effect or unknown custody')
    return value

def _preflight(operator, port, admission, data, adapter):
    from .owner_readers import project_reader,task_reader,assignment_reader,mandate_reader
    from ..agents.orchestrator_route import prepare_canonical_assignment_role_brief,_canonical_operation_evidence
    scope=admission['current_binding']['scope'];inv=data['packet']['invocation']
    _due(port,admission)
    runtime=operator.owner.role_runtime(due_port=port,adapter=adapter)
    result=runtime.result_capture_factory(**{k:scope[k] for k in ('project_ref','task_ref','assignment_ref','generation','logical_request_key')})
    _need(result.read(scope['logical_request_key']) is None, 'an owner result already exists')
    ops=runtime.operations
    prepared=prepare_canonical_assignment_role_brief(role='worker',project_ref=scope['project_ref'],task_ref=scope['task_ref'],assignment_ref=scope['assignment_ref'],mandate_ref=scope['mandate_ref'],expected_generation=scope['generation'],project_reader=project_reader(ops,scope['project_ref']),task_reader=task_reader(ops,scope['project_ref'],scope['task_ref']),assignment_reader=assignment_reader(ops,scope['assignment_ref']),mandate_reader=mandate_reader(ops,scope['project_ref'],scope['mandate_ref']),resource_reader=ops.content_port,lifecycle=inv['lifecycle'],as_of=inv['as_of'],required_resource_names=inv.get('required_resource_names',()))
    published=operator._document_read(admission['current_binding']['published_brief_ref'],'operating_brief')
    _need(published['content']==prepared['canonical_evidence'], 'published canonical brief is stale or changed')
    operation=_canonical_operation_evidence(prepared,owner=scope['principal'],task_ref=scope['task_ref'])
    _need(operation['brief_sha256']==scope['brief_sha256'], 'canonical operation brief changed')
    explicit=operation['brief'].get('instruction_contract',{}).get('source_inspection',{})
    _need(explicit.get('manifest_sha256')==data['packet']['source_manifest_sha256'], 'source admission changed')
    _due(port,admission)
    return runtime,{'outcome':'preflight_passed','admission_sha256':_digest(admission),'predecessor_binding_sha256':data['custody']['binding_sha256'],'current_binding_sha256':_digest(admission['current_binding']),'schedule_id':scope['schedule_id'],'logical_request_key':scope['logical_request_key'],'due_version':1,'due_sha256':admission['due_sha256'],'operation_brief_sha256':operation['brief_sha256'],'provider_invoked':False}

def preflight_successor(operator, admission, *, expected_sha256):
    """Non-dispatch receiving check, including real scoped result capability."""
    with _open(operator,admission,expected_sha256) as (port,data,target):
        _need(not target.exists() and not target.is_symlink(), 'successor intent already consumed')
        _,proof=_preflight(operator,port,admission,data,None)
        return proof

def _exclusive(path, value):
    # Deterministic exclusive file is the existing one-use mechanism. Retain
    # even a partially written file on any error: uncertainty is spent.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)

def invoke_successor_once(operator, admission, *, expected_sha256, adapter):
    """One explicitly admitted same-occurrence successor; never an auto-retry."""
    from ..agents.herzchen_adapter import HerzchenCodexAdapter
    _need(isinstance(adapter,HerzchenCodexAdapter), 'existing owner Codex adapter required')
    with _open(operator,admission,expected_sha256) as (port,data,target):
        _need(not target.exists() and not target.is_symlink(), 'successor intent already consumed')
        packet=data['packet'];scope=admission['current_binding']['scope']
        expected={'owner':'worker','source':packet['source_run'],'worktree':packet['worktree'],'launcher':packet['launcher'],'host_context_path':packet['host_context_path'],'requested_model':scope['requested_model'],'requested_reasoning':scope['requested_reasoning'],'require_host_context':True}
        _need(all(getattr(adapter,k,None)==v for k,v in expected.items()) and callable(adapter.source_verifier_factory), 'adapter differs from original admitted route')
        runtime,proof=_preflight(operator,port,admission,data,adapter)
        # Hash-check predecessor bytes again immediately before consuming the
        # successor. Scope/adoption is guarded again by the ordinary claim CAS.
        _proof(admission,expected_sha256);_due(port,admission)
        intent={**proof,'schema':'otto.same-occurrence-successor-intent.v1','predecessor_intent_sha256':admission['predecessor']['intent']['sha256'],'predecessor_uncertain_sha256':admission['predecessor']['uncertain']['sha256'],'reconciliation_sha256':admission['predecessor']['reconciliation']['sha256'],'invocation':data['packet']['invocation'],'no_retry':True}
        _exclusive(target,intent)
        try:
            result=runtime.invoke_role(**data['packet']['invocation'])
        except BaseException as exc:
            _exclusive(target.with_suffix('.uncertain.json'),{'admission_sha256':expected_sha256,'exception_type':type(exc).__name__,'message':str(exc),'relaunch':False})
            raise
        _exclusive(target.with_suffix('.result.json'),result)
        return result
