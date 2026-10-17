"""Explicit host-local attention custody, guarded by the original owner Store.

Only trusted owner composition receives these objects. Consumers retain the
existing finite DueRecord port; no Store or guard crosses its transport.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import sys
from typing import Any, Mapping

from otto.agents.source_verification import DEFAULT_TIMEOUTS, T01_EXTENDED_TIMEOUTS, t01_timeout_scope

_GUARD_TOKEN = object()

def _scope_timeout(scope):
    return type(scope.get('timeout_seconds')) is int and (scope['timeout_seconds'] == 1920
        or (scope['timeout_seconds'] == 4620 and t01_timeout_scope(scope)))

def _binding_timeout(binding):
    scope = binding.get('scope', {})
    return (_scope_timeout(scope) and ((binding.get('limits') == DEFAULT_TIMEOUTS and scope['timeout_seconds'] == 1920)
        or (binding.get('limits') == T01_EXTENDED_TIMEOUTS and scope['timeout_seconds'] == 4620 and t01_timeout_scope(scope))))

def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def _need(condition, reason):
    if not condition:
        raise ValueError(reason)

class ExternalAssignmentGuard:
    """Sealed finite scope from PortfolioOwnerBootstrap, never a caller callback."""
    def __init__(self, owner, scope, attention_authority, *, _token=None):
        from .owner_bootstrap import PortfolioOwnerBootstrap
        from .owner_readers import owner_ref
        _need(_token is _GUARD_TOKEN and type(owner) is PortfolioOwnerBootstrap, 'original owner issuer required')
        self._owner = owner
        self._operations = owner.consumer_operations()
        self._scope = json.loads(json.dumps(scope))
        self._attention_authority = attention_authority
        self._terminalization = self._scope.get('terminalization')
        self._terminal_hold = False
        _need(isinstance(attention_authority, str) and attention_authority and attention_authority != owner.store.authority, 'separate attention authority required')
        for key, kind in [('project_ref','work.project'),('task_ref','work.task'),('assignment_ref','wrk.assignment'),('mandate_ref','dat.content.document')]:
            ref = owner_ref(self._scope[key], key)
            _need(ref == self._scope[key] and ref['authority'] == owner.store.authority and ref['kind'] == kind, 'foreign or malformed '+key)
        for key in ['schedule_id','logical_request_key','principal','host','brief_sha256','mandate_payload_sha256','requested_model','requested_reasoning','profile']:
            _need(isinstance(self._scope.get(key), str) and bool(self._scope[key]), 'missing scope '+key)
        _need(type(self._scope.get('generation')) is int and self._scope['generation'] > 0, 'invalid generation')
        _need(_scope_timeout(self._scope), 'total deadline outside exact task admission')
        for key in ['brief_sha256','mandate_payload_sha256']:
            _need(len(self._scope[key]) == 64 and all(c in '0123456789abcdef' for c in self._scope[key]), 'invalid '+key)
        if self._terminalization is not None:
            proof = self._terminalization
            _need(isinstance(proof, Mapping) and set(proof) == {'schema','completed_task_ref','completion_sha256','result_ref','result_sha256','source_set_digest','prior_due_sha256','gateway_attempt_sha256'}
                  and proof.get('schema') == 'otto.manager-completed-occurrence.v1', 'invalid terminalization proof')
            _need(t01_timeout_scope(self._scope) and self._scope['timeout_seconds'] == 4620, 'terminalization outside exact T01 admission')
            for key in ('completion_sha256','result_sha256','source_set_digest','prior_due_sha256','gateway_attempt_sha256'):
                _need(isinstance(proof[key], str) and len(proof[key]) == 64 and all(c in '0123456789abcdef' for c in proof[key]), 'invalid terminalization '+key)
            for key, kind in [('completed_task_ref','work.task'),('result_ref','wrk.result')]:
                ref = owner_ref(proof[key], key)
                _need(ref == proof[key] and ref['authority'] == owner.store.authority and ref['kind'] == kind, 'foreign terminalization '+key)
        with owner.store.transaction():
            self._validate_owner()

    def validate_issuer(self, authority, actor):
        _need(authority == self._attention_authority and actor == self._owner.owner_actor, 'attention issuer authority/actor mismatch')

    def _validate_owner(self):
        from .owner_readers import assignment_reader, mandate_reader, project_reader, task_reader
        from .operating_brief import _state
        scope = self._scope
        operations = self._operations
        identity = lambda ref: {k:ref[k] for k in ('authority','kind','id')}
        for name, reader in [('project',project_reader(operations, scope['project_ref'])), ('task',task_reader(operations,scope['project_ref'],scope['task_ref'])), ('assignment',assignment_reader(operations,scope['assignment_ref'])), ('mandate',mandate_reader(operations,scope['project_ref'],scope['mandate_ref']))]:
            value = reader(identity(scope[name+'_ref']))
            if name == 'task' and self._terminalization is not None:
                self._validate_completed_task(value)
            else:
                _need(value['ref'] == scope[name+'_ref'], name+' revision changed')
                _state(value, name)
            if name == 'assignment':
                payload = value.get('payload', value)
                _need(value['role'] in ('worker','executor') and value['principal'] == scope['principal'] and value['generation'] == scope['generation'], 'assignment identity changed')
                parent = value.get('scope',value.get('scope_ref'))
                _need(parent is not None and any(all(parent.get(k)==scope[key][k] for k in ('authority','kind','id')) for key in ('project_ref','task_ref')), 'assignment outside bound task/project')
                expected = scope.get('resource_adoption')
                _need(isinstance(expected, Mapping) and payload.get('resource_adoptions') and payload.get('resource_adoption_digest') and payload.get('resource_adoption_revision'), 'instruction adoption required')
                _need(expected.get('assignment_ref') == scope['assignment_ref'] and expected.get('generation') == scope['generation'] and expected.get('digest') == payload['resource_adoption_digest'] and expected.get('revision') == payload['resource_adoption_revision'], 'instruction adoption changed before owner CAS')
            if name == 'mandate':
                content = value['payload']
                _need(_digest(content) == scope['mandate_payload_sha256'] and value['document_owner'] == self._owner.owner_actor.actor, 'mandate content/owner changed')
                _need(content.get('dispatch_enabled') is True and content.get('task_ref') == scope['task_ref'] and content.get('assignment_ref') == scope['assignment_ref'] and content.get('generation') == scope['generation'], 'execution mandate scope mismatch')
                if scope['timeout_seconds'] == 4620:
                    _need(content.get('instruction_contract', {}).get('source_inspection', {}).get('timeouts') == T01_EXTENDED_TIMEOUTS, 'extended deadline differs from owner mandate')

    def _validate_completed_task(self, task):
        """Read the manager completion and original worker result in the owner transaction."""
        from herzchen.contracts import ResourceRef
        from .owner_readers import json_value
        scope, proof = self._scope, self._terminalization
        identity = lambda ref: {k:ref[k] for k in ('authority','kind','id')}
        _need(task['ref'] == proof['completed_task_ref'] and identity(task['ref']) == identity(scope['task_ref'])
              and task['ref']['revision'] != scope['task_ref']['revision'] and task.get('lifecycle') == 'completed'
              and task.get('project_ref') == scope['project_ref'], 'completed task identity/revision is not linked')
        completion = task.get('payload', {}).get('completion')
        _need(isinstance(completion, Mapping) and _digest(completion) == proof['completion_sha256'], 'manager completion changed')
        _need(completion.get('task_ref') == scope['task_ref'] and completion.get('task_revision') == scope['task_ref']['revision']
              and completion.get('project_ref') == scope['project_ref'] and completion.get('manager') == self._owner.owner_actor.actor
              and completion.get('disposition') == 'accepted-for-task' and completion.get('result_ref') == proof['result_ref']
              and proof['result_ref'] in completion.get('evidence_refs', []), 'manager completion does not accept the exact result/task')
        reader = self._owner.graph.reader
        receipt = json_value(reader.get_receipt(completion.get('logical_request_key')))
        _need(isinstance(receipt, Mapping) and receipt.get('status') == 'committed' and receipt.get('operation') == 'work.revise'
              and receipt.get('logical_request_key') == completion.get('logical_request_key')
              and receipt.get('target') == scope['task_ref'] and receipt.get('result_ref') == proof['completed_task_ref'], 'manager revision receipt is not exact')
        result = reader.get_record(ResourceRef.from_dict(proof['result_ref']))
        payload = json_value(getattr(result, 'payload', None))
        _need(json_value(getattr(result, 'ref', None)) == proof['result_ref'] and isinstance(payload, Mapping)
              and payload.get('record_type') == 'work.observation' and payload.get('observation_kind') == 'result'
              and payload.get('assignment') == scope['assignment_ref'] and payload.get('generation') == scope['generation'], 'owner result record changed')
        value = payload.get('value')
        expected = {k:scope[k] for k in ('project_ref','task_ref','assignment_ref','generation','logical_request_key')}
        _need(isinstance(value, Mapping) and all(value.get(k) == v for k,v in expected.items())
              and value.get('outcome') == 'succeeded' and value.get('delivery_state') == 'done'
              and _digest(value) == proof['result_sha256'], 'owner result value differs from occurrence')
        hashes = completion.get('evidence_hashes', {})
        result_key = ':'.join((proof['result_ref']['kind'], proof['result_ref']['id'], proof['result_ref']['revision'] or ''))
        resources = value.get('resource_evidence', {})
        evidence = value.get('task_bound_evidence', {})
        source = evidence.get('operation_result', {}).get('output', {}).get('source_verification', {})
        _need(hashes.get(result_key) == proof['result_sha256']
              and completion.get('source_set_digest') == source.get('manifest_sha256') == proof['source_set_digest']
              and resources.get('brief_sha256') == scope['brief_sha256'] and _digest(resources.get('brief')) == scope['brief_sha256']
              and resources['brief']['instruction_contract']['source_inspection']['manifest_sha256'] == proof['source_set_digest'], 'accepted source/brief evidence changed')
        self._manager_completion = json_value(completion)

    def _terminal_record(self, value, *, request_id):
        scope, proof = self._scope, self._terminalization
        key = scope['logical_request_key']
        _need(request_id == 'complete:'+key and value.schedule_id == scope['schedule_id']
              and value.interval_seconds is None and value.in_flight_request is None
              and value.last_completed_request == key and value.delivery_state == 'returned'
              and value.completion_state == 'succeeded' and value.stop_state == 'completed'
              and isinstance(value.completed_at, str) and bool(value.completed_at), 'terminal-only completion transition required')
        evidence = value.completion_evidence or {}
        completion = self._manager_completion
        expected = {'kind':'manager-completed-t01-c01','schedule_id':scope['schedule_id'],
            'worker_result_ref':proof['result_ref'],'worker_result_canonical_sha256':proof['result_sha256'],
            'manager_task_ref':proof['completed_task_ref'],'manager_assignment_ref':completion['assignment_ref'],
            'manager_generation':completion['generation'],'manager_disposition':'accepted-for-task'}
        _need(all(evidence.get(k) == v for k,v in expected.items()), 'completion evidence differs from current manager acceptance')
        result = value.last_result
        _need(isinstance(result, Mapping) and set(result) == {'outcome','request_id','receipt','relaunch','same_request','automatic_action'}
              and result['outcome'] == 'returned' and result['request_id'] == key and result['relaunch'] is False
              and result['same_request'] is True and result['automatic_action'] is False, 'terminal result may not dispatch/reset')
        attempt = (value.host_evidence or {}).get('gateway_attempt')
        _need(isinstance(attempt, Mapping) and _digest(attempt) == proof['gateway_attempt_sha256']
              and attempt.get('state') == 'result' and attempt.get('logical_request_key') == key
              and attempt.get('assignment_ref') == scope['assignment_ref'] and attempt.get('generation') == scope['generation']
              and _digest(attempt.get('result')) == proof['result_sha256'], 'terminal gateway/result bytes changed')
        result_value = attempt['result']
        _need(attempt.get('request_fingerprint') == result_value.get('request_fingerprint')
              and attempt.get('physical_session_id') == result_value.get('physical_session_id')
              and attempt.get('native_session_id') == result_value.get('native_session_id')
              and attempt.get('delivery_authorization') == result_value.get('raw_result', {}).get('owner_delivery_authorization'), 'gateway custody differs from accepted owner result')

    def validate_transition(self, prior, current):
        """A split binding owns one occurrence: custody cannot be erased/reset."""
        from otto.attention import DueRecord
        if self._terminalization is not None:
            _need(self._terminal_hold and isinstance(prior, Mapping), 'terminalization requires existing occurrence under owner transaction')
            _need(_digest(prior) == self._terminalization['prior_due_sha256'], 'original Due bytes/version changed')
            before = DueRecord.from_dict(prior)
            _need(before.in_flight_request == self._scope['logical_request_key'] and before.stop_state == 'active'
                  and before.delivery_state == 'ready' and before.completion_state == 'none'
                  and before.last_completed_request is None and before.last_result is None and before.completed_at is None
                  and before.completion_evidence is None, 'occurrence is not the original returned worker attempt')
            allowed = {'in_flight_request','delivery_state','last_completed_request','last_result','completed_at','completion_evidence','completion_state','stop_state'}
            _need({k:v for k,v in prior.items() if k not in allowed} == {k:v for k,v in current.items() if k not in allowed}, 'terminalization altered retained occurrence evidence')
        if prior is None:
            _need((current.get('host_evidence') or {}).get('gateway_attempt') is None, 'new occurrence must be unclaimed')
            return
        _need(DueRecord.from_dict(prior).immutable_input == DueRecord.from_dict(current).immutable_input, 'immutable occurrence input changed')
        before = (prior.get('host_evidence') or {}).get('gateway_attempt')
        after = (current.get('host_evidence') or {}).get('gateway_attempt')
        if before is not None:
            _need(isinstance(after, Mapping), 'durable attempt cannot be removed')
            for key in ('logical_request_key','assignment_ref','generation','request_fingerprint','physical_session_id','delivery_authorization'):
                if key in before:
                    _need(after.get(key) == before[key], 'durable attempt custody changed: '+key)
            if before.get('state') == 'result':
                _need(after == before, 'durable result cannot be replaced')
            else:
                _need(after.get('state') in ('claimed','result'), 'claim cannot be reset')

    @contextmanager
    def hold(self, schedule_id, record, *, request_id):
        from otto.attention import DueRecord
        value = DueRecord.from_dict(record)
        scope = self._scope
        _need(isinstance(request_id,str) and request_id.strip(), 'request identity missing')
        _need(schedule_id == value.schedule_id == scope['schedule_id'] and (self._terminalization is not None or value.in_flight_request == scope['logical_request_key']), 'occurrence scope mismatch')
        expected_target = {k:scope[k] for k in ('project_ref','task_ref','assignment_ref','mandate_ref','principal','host')}
        expected_target['role'] = 'worker'
        _need(value.execution_mode == 'fresh_bounded_worker' and value.role == 'worker' and value.target == expected_target, 'target scope mismatch')
        _need(value.assignment_ref == scope['assignment_ref'] and value.project_ref == scope['project_ref']['id'] and value.generation == scope['generation'] and value.recipient == scope['principal'], 'DueRecord assignment mismatch')
        _need(value.lifecycle_owner == self._owner.owner_actor.actor and value.manager_ref == self._owner.owner_actor.actor and value.result_owner == self._owner.owner_actor.actor, 'DueRecord owner mismatch')
        for key in ('requested_model','requested_reasoning','profile','timeout_seconds'):
            _need(getattr(value,key) == scope[key], 'DueRecord '+key+' mismatch')
        _need(scope['mandate_ref'] in value.context_refs and scope['task_ref'] in value.context_refs, 'context refs missing')
        evidence = value.host_evidence or {}
        _need(evidence.get('resource_adoption') == scope['resource_adoption'], 'missing or changed adoption evidence')
        attempt = evidence.get('gateway_attempt')
        if attempt is not None:
            _need(attempt.get('logical_request_key') == scope['logical_request_key'] and attempt.get('generation') == scope['generation'], 'attempt scope mismatch')
            authorization = attempt.get('delivery_authorization')
            if authorization is not None:
                _need(authorization.get('brief_sha256') == scope['brief_sha256'], 'delivery brief changed')
        with self._owner.store.transaction():
            self._validate_owner()
            if self._terminalization is not None:
                self._terminal_record(value, request_id=request_id)
                self._terminal_hold = True
            try:
                yield
            finally:
                self._terminal_hold = False

_REQUIRED_MODULES = ('otto.portfolio.operator','otto.attention','otto.portfolio.attention_binding','otto.portfolio.owner_bootstrap','otto.agents.owner_runtime','otto.agents.source_verification','herzchen.kernel.store')

def _path(path, *, exists):
    path = Path(path)
    _need(path.is_absolute(), 'absolute attention path required')
    for part in path.parents:
        _need(not part.is_symlink(), 'symlink in attention path')
    _need(not path.is_symlink(), 'symlink attention file')
    parent = path.parent.stat()
    _need(parent.st_uid == os.geteuid() and not parent.st_mode & 0o077, 'attention parent must be private and owner owned')
    if exists:
        info = path.stat()
        _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077 and info.st_nlink == 1, 'attention file custody mismatch')
    else:
        _need(not path.exists(), 'attention path must be absent before creation')
    return path

def _validate_binding(operator, binding, expected_sha256, *, exists):
    from .operator import ProjectOperator, checked_file
    _need(type(operator) is ProjectOperator and operator.store is not None, 'live original ProjectOperator required')
    _need(_digest(binding) == expected_sha256 and binding.get('schema') == 'otto.host-attention-binding.v1', 'host attention binding digest/schema mismatch')
    config = operator.config
    _need(binding.get('host_id') == config['host_id'] == socket.gethostname(), 'host mismatch')
    principal = {'uid':os.geteuid(),'gid':os.getegid(),'account':pwd.getpwuid(os.geteuid()).pw_name}
    _need(os.getuid()==os.geteuid() and os.getgid()==os.getegid() and binding.get('principal') == config['principal'] == principal, 'principal mismatch')
    _need(binding.get('credential_ref') == config['credential_ref'] and binding.get('owner_config_sha256') == operator.config_sha256, 'owner credential/config mismatch')
    raw_config=checked_file(Path(binding['owner_config_path']))
    _need(hashlib.sha256(raw_config).hexdigest() == operator.config_sha256 and json.loads(raw_config) == config, 'original config bytes changed')
    _need(binding.get('issuer') == 'PortfolioOwnerBootstrap.issue_attention_assignment_guard' and binding.get('forbidden') == ['T02+','GPU'] and _binding_timeout(binding), 'bounded issuer/limits required')
    _need(binding.get('owner_store') == config['store'], 'original Store pin mismatch')
    original = Path(config['store']['path']);info=original.stat()
    _need([info.st_dev,info.st_ino] == config['store']['device_inode'] and operator.store.domain_descriptor_digest == config['store']['domain_descriptor_digest'], 'original Store custody changed')
    _need(binding.get('allowed_domains') == ['otto.attention'] and binding.get('no_retry') is True, 'attention scope must be single-domain/no-retry')
    _need(binding['scope']['project_ref'] == config['project_ref'] and binding['scope']['host'] == binding['host_id'], 'scope host/project mismatch')
    _need(binding.get('python') == str(Path(sys.executable).absolute()) and binding.get('python_sha256') == hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(), 'interpreter mismatch')
    hashes=binding.get('module_sha256',{})
    required = _REQUIRED_MODULES + (('otto.agents.herzchen_adapter','otto.portfolio.resource_sync','herzchen.adapters.host')
        if binding.get('limits') == T01_EXTENDED_TIMEOUTS else ())
    _need(set(hashes) == set(required), 'exact installed modules required')
    for name in required:
        raw=Path(importlib.import_module(name).__file__).read_bytes()
        _need(hashlib.sha256(raw).hexdigest() == hashes[name], 'installed module changed: '+name)
    path=_path(binding['attention_path'],exists=exists)
    _need(path.resolve()!=original.resolve() and (not exists or not os.path.samefile(path,original)), 'attention aliases original Store')
    _need(exists or binding['scope'].get('terminalization') is None, 'terminalization cannot create an attention store')
    guard=operator.owner.issue_attention_assignment_guard(binding['scope'],attention_authority=binding['attention_authority'])
    return path,guard

def create_host_attention_store(operator, binding, *, expected_sha256):
    """Explicit bootstrap only. Returns identity pins; never creates a DueRecord."""
    from herzchen.kernel.store import Store
    from otto.attention import due_record_contribution
    path,_=_validate_binding(operator,binding,expected_sha256,exists=False)
    store=Store.create(path,authority=binding['attention_authority'])
    try:
        os.chmod(path,0o600)
        store.register_domain_handler([due_record_contribution()])
        info=path.stat()
        result={'binding_sha256':expected_sha256,'path':str(path),'authority':store.authority,'device_inode':[info.st_dev,info.st_ino],'domain_descriptor_digest':store.domain_descriptor_digest}
    finally:
        store.close()
    return result

@contextmanager
def open_host_attention_port(operator, binding, custody, *, expected_sha256):
    """Fresh-open the separately admitted Store and yield only its finite port."""
    from herzchen.kernel.store import Store
    from otto.attention import due_record_contribution,issue_store_due_record_port
    from herzchen.command_ports import close_consumer_facade
    path,guard=_validate_binding(operator,binding,expected_sha256,exists=True)
    info=path.stat()
    _need(custody.get('binding_sha256')==expected_sha256 and custody.get('path')==str(path) and custody.get('authority')==binding['attention_authority'] and custody.get('device_inode')==[info.st_dev,info.st_ino], 'attention custody mismatch')
    store=Store.open(path,authority=binding['attention_authority'],expected_domains=[due_record_contribution()],expected_domain_digest=custody['domain_descriptor_digest'])
    port=None
    try:
        port=issue_store_due_record_port(store.domain_handler([due_record_contribution()]),operator.owner.owner_actor,external_assignment_guard=guard)
        yield port
    finally:
        if port is not None:close_consumer_facade(port.transport)
        store.close()
