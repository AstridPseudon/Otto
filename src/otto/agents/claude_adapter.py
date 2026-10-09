"""Candidate Claude leaf binding for the existing owner/gateway/capture seams.

No manager, coordinator or provider-native child capability is inherited.
The host must separately qualify and adopt exact launcher, scope and resource
pins; a synthetic parser/process test does not enable installed execution.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from .claude_cli import (ClaudeBindingError, ClaudeCliTransport, LauncherPin,
                         MacWriteScope, MAX_ARTIFACT, PARSER_SCHEMA, digest, file_digest, text)
from .herzchen_adapter import HerzchenCodexAdapter, _context_digest

IDENTITY = 'otto.adapter.claude-code-2.1.293.leaf.v1'
FINAL_FORMAT = 'claude-code-2.1.293-native-result-v1'


def _artifact_path(workspace: str, path: str) -> Path:
    root = Path(workspace)
    value = Path(text(path, 'tool file_path'))
    value = value if value.is_absolute() else root / value
    # Capture only normal, non-symlink files in the exact tool workspace.
    relative = value.relative_to(root)
    if any(part in {'.git', '.agents', '.codex', '.aws', '.claude', '..'} for part in relative.parts):
        raise ClaudeBindingError('artifact path escapes or addresses protected state')
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ClaudeBindingError('artifact symlink cannot be captured')
    return value


def capture_artifacts(native: Mapping[str, Any], workspace: str) -> list[dict[str, Any]]:
    artifacts = []
    seen = set()
    for ident, tool in reversed(list(native['tools'].items())):
        if tool['name'] != 'Write' or native['tool_results'][ident].get('is_error', False):
            continue
        path = _artifact_path(workspace, tool['input'].get('file_path'))
        if str(path) in seen:
            continue
        seen.add(str(path))
        if len(artifacts) >= 16:
            raise ClaudeBindingError('delivered artifacts exceed bounded capture')
        # The selected OS fence and leaf tool surface prevent native writers
        # outside scope. Capture uses a no-follow descriptor and bounded bytes.
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(workspace, directory_flags)
        fd = None
        try:
            for part in path.relative_to(workspace).parts[:-1]:
                child = os.open(part, directory_flags, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            import stat
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ClaudeBindingError('artifact is not a regular file')
            with os.fdopen(fd, 'rb') as stream:
                fd = None
                body = stream.read(MAX_ARTIFACT + 1)
        finally:
            if fd is not None: os.close(fd)
            os.close(directory)
        if len(body) > MAX_ARTIFACT:
            raise ClaudeBindingError('required delivered artifact exceeds capture bound')
        written = tool['input'].get('content')
        if not isinstance(written, str) or body != written.encode('utf-8'):
            raise ClaudeBindingError('artifact bytes differ from the last successful native Write input')
        artifacts.append({'name': str(path.relative_to(workspace)), 'tool_use_id': ident,
            'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
            'content_base64': base64.b64encode(body).decode('ascii')})
    if not artifacts:
        raise ClaudeBindingError('useful Claude leaf requires a verified delivered Write artifact')
    return artifacts


def native_context(native: Mapping[str, Any], *, brief: Mapping[str, Any], authorization: Mapping[str, Any],
                   prompt: str, workspace: str, model: str, reasoning: str) -> dict[str, Any]:
    result = native['result']
    body = result['result']
    session, turn = native['session_id'], native['turn_id']
    answer = {'text': body, 'format': FINAL_FORMAT, 'phase': 'final_answer',
              'text_sha256': hashlib.sha256(body.encode()).hexdigest(), 'utf8_bytes': len(body.encode()),
              'host_record': native['refs']['final_answer']}
    output = {'final_answer': answer, 'artifacts': capture_artifacts(native, workspace)}
    result_digest = digest(output)
    result_ref = 'claude-native-result:' + result['uuid']
    contract = brief['instruction_contract']
    # Common operation evidence is mapped by the host; native references keep
    # the actual Claude types. No Codex event or transcript is fabricated.
    evidence = {'session_id': session, 'turn_id': turn, 'task_ref': authorization['task_ref'],
        'assignment_ref': authorization['assignment_ref'], 'generation': authorization['generation'],
        'operation': 'invoke', 'provenance': 'host_command_execution/item_completed',
        'provider_schema': PARSER_SCHEMA, 'owner_delivery_authorization': dict(authorization),
        'delivered_brief_digest': digest(brief), 'delivered_contract_digest': digest(contract),
        'native_input_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'effective_scope': native['scope'], 'launcher_pin': native['launcher'],
        'model_provenance': 'native system.init and assistant.message.model',
        'reasoning_provenance': 'pinned host --effort configuration; native effort unreported',
        'read_targets': contract.get('read_targets', [workspace]),
        'result_ref': result_ref, 'result_digest': result_digest,
        'host_records': {'commands': list(native['refs'].get('tool_results', {}).values()),
                         'final_answer': answer['host_record']},
        'usage': native['usage'],
        'operation_result': {'status': 'completed', 'result_ref': result_ref,
                             'result_digest': result_digest, 'output': output}}
    context = {'session_id': session, 'turn_id': turn, 'provenance': 'host_owned_turn_context',
        'model': model, 'reasoning': reasoning, 'effective_profile': 'workspace-write',
        'worker_content': [body], 'task_bound_evidence': evidence}
    cd = _context_digest(session_id=session, turn_id=turn, provenance=context['provenance'], model=model,
        reasoning=reasoning, worker_content=[body], task_bound_evidence=evidence, effective_profile='workspace-write')
    evidence['context_digest'] = context['context_digest'] = cd
    evidence['evidence_digest'] = digest(evidence)
    return context


class ClaudeNativeResultVerifier:
    identity = 'otto.claude-native-result-verifier.v1'
    native_work_operation = 'invoke'

    def capture_summary(self, evidence: Mapping[str, Any], *, result_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        artifacts = evidence['operation_result']['output']['artifacts']
        if not 1 <= len(artifacts) <= 16:
            raise ClaudeBindingError('bounded captured artifact inventory required')
        captured = []
        for index, artifact in enumerate(artifacts):
            captured_artifact_bytes(artifact)
            ref = {'result_ref': dict(result_ref), 'index': index, 'sha256': artifact['sha256']}
            captured.append({**artifact, 'ref': ref, 'availability': 'retained',
                             'source': 'verified native Write and owner capture'})
        return {'artifacts': captured, 'usage': copy.deepcopy(evidence.get('usage', {
            'state': 'unavailable', 'reason': 'native usage not observed'}))}

    def supports_final_answer(self, answer: Mapping[str, Any]) -> bool:
        return (isinstance(answer, Mapping) and answer.get('format') == FINAL_FORMAT
            and answer.get('phase') == 'final_answer'
            and (answer.get('host_record') or {}).get('event_type') == 'result'
            and (answer.get('host_record') or {}).get('item_type') == 'ClaudeResult')

    def observe_context(self, context: Any, *, expected_session_id: str, expected_turn_id: str,
                        expected_profile: str, expected_read_targets: Any = None,
                        expected_read_scope: Any = None) -> Mapping[str, Any]:
        if not isinstance(context, dict):
            raise ClaudeBindingError('host-owned Claude context required')
        value = copy.deepcopy(context); evidence = value.get('task_bound_evidence') or {}
        output = (evidence.get('operation_result') or {}).get('output') or {}
        answer = output.get('final_answer') or {}
        record = answer.get('host_record') or {}
        scope = evidence.get('effective_scope') or {}
        if (value.get('session_id') != expected_session_id or value.get('turn_id') != expected_turn_id
                or value.get('provenance') != 'host_owned_turn_context'
                or value.get('effective_profile') != expected_profile or expected_profile != 'workspace-write'
                or expected_read_scope is not None
                or evidence.get('session_id') != expected_session_id or evidence.get('turn_id') != expected_turn_id
                or evidence.get('provider_schema') != PARSER_SCHEMA or evidence.get('operation') != 'invoke'
                or scope.get('identity') != MacWriteScope.identity or scope.get('verified') is not True
                or not self.supports_final_answer(answer) or record.get('session_id') != expected_session_id
                or record.get('turn_id') != expected_turn_id or value.get('worker_content') != [answer.get('text')]
                or evidence.get('result_digest') != digest(output)
                or evidence.get('operation_result', {}).get('result_digest') != digest(output)
                or evidence.get('operation_result', {}).get('result_ref') != evidence.get('result_ref')
                or evidence.get('operation_result', {}).get('status') != 'completed'
                or not output.get('artifacts')
                or (expected_read_targets is not None and evidence.get('read_targets') != expected_read_targets)):
            raise ClaudeBindingError('Claude native result/input/scope binding is invalid')
        body = text(answer.get('text'), 'conclusion').encode()
        if (answer.get('text_sha256') != hashlib.sha256(body).hexdigest() or answer.get('utf8_bytes') != len(body)
                or evidence.get('evidence_digest') != digest({k: v for k, v in evidence.items() if k != 'evidence_digest'})):
            raise ClaudeBindingError('Claude native result/evidence bytes mismatch')
        cd = _context_digest(session_id=expected_session_id, turn_id=expected_turn_id,
            provenance=value['provenance'], model=value['model'], reasoning=value['reasoning'],
            worker_content=value['worker_content'], task_bound_evidence=evidence,
            effective_profile=expected_profile)
        if value.get('context_digest') != cd or evidence.get('context_digest') != cd:
            raise ClaudeBindingError('Claude host context digest mismatch')
        for artifact in output['artifacts']:
            captured_artifact_bytes(artifact)
        return {**value, 'context_digest_verified': True, 'observed_profile': expected_profile}


def captured_artifact_bytes(artifact: Mapping[str, Any]) -> bytes:
    try:
        encoded = artifact['content_base64']
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_ARTIFACT + 2) // 3):
            raise ClaudeBindingError('captured artifact exceeds byte bound')
        body = base64.b64decode(encoded, validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise ClaudeBindingError('captured artifact bytes invalid') from exc
    if (len(body) > MAX_ARTIFACT or artifact.get('bytes') != len(body)
            or artifact.get('sha256') != hashlib.sha256(body).hexdigest()):
        raise ClaudeBindingError('captured artifact digest/size mismatch')
    return body


class ClaudeWorkerAdapter:
    owner_bound = True
    require_host_context = True
    adapter_identity = IDENTITY

    def __init__(self, *, owner: str, source: str, worktree: str, launcher_pin: LauncherPin,
                 state_root: str, requested_model: str, requested_reasoning: str = 'high',
                 transport: ClaudeCliTransport | None = None, authentication: str = 'existing-user'):
        self.owner, self.source = text(owner, 'owner'), text(source, 'source')
        self.worktree = str(Path(worktree).resolve(strict=True))
        self.writable_roots = ()
        self.launcher_pin, self.launcher, self.state_root = launcher_pin, launcher_pin.realpath, state_root
        self.requested_model, self.requested_reasoning = requested_model, requested_reasoning
        self.transport = transport or ClaudeCliTransport(launcher_pin, MacWriteScope(self.worktree, state_root, authentication=authentication),
            model=requested_model, reasoning=requested_reasoning, authentication=authentication)
        self._authorizer = self._verifier = self._completed_verifier = None
        self._thread_started_callback = self._turn_started_callback = None
        self._used = False

    def pins(self) -> Mapping[str, Any]:
        return {'launcher': vars(self.launcher_pin), 'parser_schema': PARSER_SCHEMA,
                'parser_sha256': file_digest(Path(__file__).with_name('claude_cli.py')),
                'binding_sha256': file_digest(Path(__file__)), 'scope': self.transport.scope.pin,
                'model': self.requested_model, 'reasoning': self.requested_reasoning,
                'authentication': self.transport.authentication, 'permission_mode': 'bypassPermissions',
                'profile': 'workspace-write', 'role': 'worker-leaf'}

    def capabilities(self) -> Mapping[str, Any]:
        pins = self.pins()
        def cap(state, reason): return {'state': state, 'reason': reason, 'pins': pins}
        return {'useful_leaf': cap('unverified', 'requires authentic installed useful journey and host adoption'),
                'structured_stream': cap('unverified', 'synthetic parser/process checks do not qualify installed schema'),
                'snapshot_follow': cap('supported', 'existing retained owner snapshot reads'),
                'native_streaming': cap('unsupported', 'no partial-token stream advertised'),
                'attach': cap('unsupported', 'no native attach binding'),
                'resume': cap('unsupported', 'exact initializer-to-work continuation is internal; no later resume qualification'),
                'cancel': cap('degraded', 'transport unwinding reaps its owned process group; owner stop is only a fence'),
                'steering': cap('unsupported', 'stdin sealed for bounded leaf'),
                'native_children': cap('unsupported', 'Agent/Bash/MCP/customizations disabled; child frames rejected'),
                'manager': cap('unsupported', 'worker-leaf only'),
                'coordinator': cap('unsupported', 'no delegated authority or native caller tools')}

    def validate_owner_host_composition(self, *, role: str, profile: str) -> None:
        if role != 'worker' or profile != 'workspace-write':
            raise ClaudeBindingError('Claude candidate supports only workspace-write worker leaves')
        self.transport.preflight()

    def bind_owner_authorization(self, authorizer, *, verifier=None, completed_verifier=None, role=None, profile=None):
        if role != 'worker' or profile != 'workspace-write' or not callable(authorizer) or not callable(verifier):
            raise ClaudeBindingError('exact owner-authorized leaf composition required')
        bound = copy.copy(self)
        bound._authorizer, bound._verifier, bound._completed_verifier = authorizer, verifier, completed_verifier
        bound._used = False
        return bound

    def set_thread_started_callback(self, callback):
        prior = self._thread_started_callback; self._thread_started_callback = callback; return prior

    def set_turn_started_callback(self, callback):
        prior = self._turn_started_callback; self._turn_started_callback = callback; return prior

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        from otto.portfolio.execution_host import ExecutionHost
        from herzchen.adapters.host import _owner_delivery_appendix
        typed, brief_digest, brief = HerzchenCodexAdapter._typed_request(self, 'invoke', request)
        contract = brief['instruction_contract']; authority = contract['authority']
        if (self._used or not callable(self._authorizer) or not callable(self._verifier)
                or not callable(self._thread_started_callback) or not callable(self._turn_started_callback)
                or request.get('physical_session_id') is not None or request.get('expected_role') != 'worker'
                or typed.requested_profile != 'workspace-write' or contract.get('delegation') is not None
                or authority.get('gateway_claim_required') is not True
                or authority.get('owner_write') is not False or authority.get('dispatch') is not False
                or authority.get('effect_profile') != 'workspace-write-worker'
                or set(authority.get('workspace_roots', [])) != {self.worktree}
                or set(authority.get('permitted_effects', [])) - {'read_delivered_context', 'read_linked_sources', 'file_write_in_workspace', 'return_result'}
                or request.get('requested_model', self.requested_model) != self.requested_model
                or request.get('requested_reasoning', self.requested_reasoning) != self.requested_reasoning):
            raise ClaudeBindingError('Claude leaf scope, owner binding or model selection mismatch')
        self._used = True  # No unknown effect can be retried on this binding.
        session = None; admitted = False
        thread_capture = ExecutionHost.owner_callback(self._thread_started_callback)
        def on_thread(observed_session):
            nonlocal session
            session = observed_session
            thread_capture(observed_session)
        on_turn = ExecutionHost.owner_callback(self._turn_started_callback)
        authorize = ExecutionHost.owner_callback(self._authorizer)
        verify = ExecutionHost.owner_callback(self._verifier)
        try:
            init = ExecutionHost.external_call(lambda: self.transport.run(
                'Initialize this session only. Do not use tools or do task work. Return READY.',
                initializer=True, on_init=on_thread))
            session = init['session_id']
            if init['outcome'] != 'succeeded' or init['result'].get('result', '').strip() != 'READY' or init['tools']:
                raise ClaudeBindingError('inert native initializer was not exact READY')
            authorization = authorize(session, brief_digest)
            expected = {'status': 'authorized', 'physical_session_id': session,
                'brief_sha256': brief_digest, 'logical_request_key': request['logical_request_key'],
                'project_ref': request.get('expected_project_ref'), 'task_ref': typed.target.to_dict(),
                'assignment_ref': request.get('expected_assignment_ref'), 'generation': request.get('expected_generation'),
                'role': 'worker', 'principal': request.get('expected_principal'),
                'lifecycle_owner': request.get('expected_lifecycle_owner')}
            if (not isinstance(authorization, Mapping) or any(v is None or authorization.get(k) != v for k,v in expected.items())
                    or type(authorization.get('owner_version')) is not int
                    or verify(session, brief_digest, dict(authorization)) != authorization):
                raise ClaudeBindingError('owner authorization readback differs before useful input')
            prompt = HerzchenCodexAdapter.render_verified_invocation(brief, brief_digest, request)
            prompt += _owner_delivery_appendix(authorization, 'workspace-write')
            def input_started(turn):
                nonlocal admitted
                if admitted: raise ClaudeBindingError('duplicate useful native admission')
                on_turn(turn, datetime.now(timezone.utc).isoformat())
                admitted = True
            work = ExecutionHost.external_call(lambda: self.transport.run(prompt, session=session, on_input=input_started))
            if work['outcome'] == 'failed':
                return {'outcome': 'failed', 'physical_session_id': session, 'observed_turn_id': work['turn_id'],
                        'delivery_state': 'failed', 'native_failure': work['result'], 'usage': work['usage'],
                        'worker_content': [], 'raw_result': {'native_failure': work['result'],
                            'usage': work['usage'], 'native_pins': self.pins(), 'events': work['events']},
                        'error': {'code': 'claude_native_failure', 'message': 'native Claude error result retained'}}
            context = native_context(work, brief=brief, authorization=authorization, prompt=prompt,
                workspace=self.worktree, model=self.requested_model, reasoning=self.requested_reasoning)
            checked = ClaudeNativeResultVerifier().observe_context(context, expected_session_id=session,
                expected_turn_id=work['turn_id'], expected_profile='workspace-write', expected_read_targets=contract.get('read_targets'))
            completed_verify = ExecutionHost.owner_callback(self._completed_verifier or self._verifier)
            if completed_verify(session, brief_digest, dict(authorization)) != authorization:
                raise ClaudeBindingError('owner authorization changed after native work; reconciliation required')
            native_pins = {**self.pins(), 'resource_brief_sha256': brief_digest,
                'resource_adoption': copy.deepcopy(brief.get('resource_adoption')),
                'resource_resolution': copy.deepcopy(brief.get('resource_resolution')),
                'model_selection': copy.deepcopy(brief.get('context', {}).get('operating_setup', {}).get('current_execution'))}
            return {'outcome': 'succeeded', 'physical_session_id': session, 'observed_turn_id': work['turn_id'],
                'observed_model': checked['model'], 'observed_reasoning': checked['reasoning'],
                'observed_profile': 'workspace-write', 'observed_context_provenance': 'host_owned_turn_context',
                'observed_context_digest': checked['context_digest'], 'context_digest_verified': True,
                'task_bound_evidence': checked['task_bound_evidence'], 'worker_content': checked['worker_content'],
                'delivery_state': 'done', 'work_receipt': {'observed_profile': 'workspace-write'},
                'work_envelope': {'host_evidence': {'otto_host_turn_context': context}},
                'raw_result': {'worker_content': checked['worker_content'],
                    'work_receipt': {'observed_profile': 'workspace-write'},
                    'work_envelope': {'host_evidence': {'otto_host_turn_context': context}},
                    'native_pins': native_pins},
                'native_pins': native_pins, 'capabilities': self.capabilities()}
        except Exception as exc:
            return {'outcome': 'unknown', 'delivery_state': 'unknown', 'physical_session_id': session,
                'useful_input_observed': admitted, 'retry_allowed': False,
                'error': {'code': 'claude_qualification_or_capture_held', 'message': str(exc)},
                'next_actor': 'host through assigned manager; reconcile exact attempt, scope and retained stream'}
