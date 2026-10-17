"""Candidate Claude Code binding for the existing owner/gateway/capture seams.

Roles are declared, never inferred: the default composition is the original
worker leaf (Edit/Glob/Grep/Read/Write). A host may also declare the ``manager`` role, which
admits the manager tool surface (Bash/Edit/Glob/Grep/Read/Write) under the
same OS write fence, with child processes inheriting it. No coordinator or
provider-native child capability is inherited by either role. The host must
separately qualify and adopt exact launcher, scope and resource pins; a
synthetic parser/process test does not enable installed execution.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from herzchen.fleet.hosts import McpGrant
from herzchen.fleet.tools.pins import exec_allow_for, require_sole_server
from .claude_cli import (ClaudeBindingError, ClaudeChildExitError, ClaudeCliTransport, LauncherPin, MANAGER_TOOLS,
                         MacWriteScope, MAX_ARTIFACT, PARSER_SCHEMA, TOOL_SERVER, WORKER_TOOLS, digest,
                         file_digest, text)
from .herzchen_adapter import HerzchenCodexAdapter, _context_digest

IDENTITY = 'otto.adapter.claude-code-2.1.293.leaf.v1'
FINAL_FORMAT = 'claude-code-2.1.293-native-result-v1'
_WORKER_EFFECTS = frozenset({'read_delivered_context', 'read_linked_sources', 'file_write_in_workspace', 'return_result'})
# Declared per-role profiles. The manager profile mirrors the owner's
# workspace-write-manager contract: canonical manager commands are reached
# through the installed client (Bash), never by the provider directly.
ROLE_PROFILES: Mapping[str, Mapping[str, Any]] = {
    'worker': {'tools': WORKER_TOOLS, 'calls': ('task', 'check', 'done'), 'effect_profile': 'workspace-write-worker',
               'effects': _WORKER_EFFECTS, 'artifacts_required': True, 'max_turns': 8},
    'manager': {'tools': MANAGER_TOOLS, 'calls': (), 'effect_profile': 'workspace-write-manager',
                'effects': _WORKER_EFFECTS | {'canonical_manager_commands'}, 'artifacts_required': False,
                'max_turns': 200},
}


def _delivered_role(evidence: Mapping[str, Any]) -> str:
    role = ((evidence.get('owner_delivery_authorization') or {}).get('role')) or 'worker'
    if role not in ROLE_PROFILES:
        raise ClaudeBindingError('Claude result carries an undeclared role')
    return role


def _artifact_path(workspace: str, path: str) -> Path:
    root = Path(workspace)
    value = Path(text(path, 'tool file_path'))
    value = value if value.is_absolute() else root / value
    # Capture only normal, non-symlink files in the exact tool workspace.
    try:
        relative = value.relative_to(root)
    except ValueError as exc:
        raise ClaudeBindingError('artifact path escapes the tool workspace') from exc
    if any(part in {'.git', '.agents', '.codex', '.aws', '.claude', '..'} for part in relative.parts):
        raise ClaudeBindingError('artifact path escapes or addresses protected state')
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ClaudeBindingError('artifact symlink cannot be captured')
    return value


def _git_output(workspace: str, *args: str) -> str:
    try:
        result = subprocess.run(['git', '-C', workspace, *args], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ClaudeBindingError('worker checkpoint provenance is unavailable') from exc
    return result.stdout.strip()


def _worker_checkpoint(workspace: str) -> tuple[str, str] | None:
    """Return (checkpoint commit, parent) for the current land operation."""
    inside = subprocess.run(['git', '-C', workspace, 'rev-parse', '--is-inside-work-tree'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if inside.returncode:
        return None
    entries = _git_output(workspace, 'reflog', '--format=%H%x09%gs', 'HEAD').splitlines()
    if entries and entries[0].partition('\t')[2].startswith('rebase (finish):'):
        # The entry immediately older than rebase start is the HEAD that
        # Landing checkpointed. ORIG_HEAD can be stale across earlier rebases.
        start_index = next((i for i in range(len(entries))
                            if entries[i].partition('\t')[2].startswith('rebase (start):')), None)
        if start_index is None or start_index + 1 >= len(entries):
            raise ClaudeBindingError('worker rebase checkpoint cannot be identified')
        selected = entries[start_index + 1]
        if not selected.partition('\t')[2].startswith('commit: land '):
            raise ClaudeBindingError('worker land checkpoint reflog entry is missing')
        commit = selected.partition('\t')[0]
    else:
        commit = _git_output(workspace, 'rev-parse', 'HEAD')
        if (not entries or entries[0].partition('\t')[0] != commit or
                not entries[0].partition('\t')[2].startswith('commit: land ')):
            raise ClaudeBindingError('worker land checkpoint reflog entry is missing')
    subject = _git_output(workspace, 'show', '-s', '--format=%s', commit)
    if not subject.startswith('land '):
        raise ClaudeBindingError('worker land checkpoint cannot be identified')
    parent = _git_output(workspace, 'rev-parse', commit + '^')
    return commit, parent


def _bounded_blob(workspace: str, spec: str) -> bytes:
    try:
        proc = subprocess.Popen(['git', '-C', workspace, 'cat-file', 'blob', spec],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        body = proc.stdout.read(MAX_ARTIFACT + 1)
        if len(body) > MAX_ARTIFACT:
            proc.kill()
            proc.communicate()
            raise ClaudeBindingError('required delivered artifact exceeds capture bound')
        _, err = proc.communicate()
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, stderr=err)
        return body
    except ClaudeBindingError:
        raise
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ClaudeBindingError('worker checkpoint does not contain the delivered artifact') from exc


def _checkpoint_blob(workspace: str, commit: str, relative: str) -> bytes:
    result = subprocess.run(['git', '-C', workspace, 'ls-tree', '-z', commit, '--', ':(literal)' + relative],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    entry = result.stdout.rstrip(b'\0').split(b'\t')
    fields = entry[0].split() if len(entry) == 2 else []
    if (len(fields) != 3 or fields[0] not in {b'100644', b'100755'} or fields[1] != b'blob'
            or entry[1] != os.fsencode(relative)):
        raise ClaudeBindingError('worker checkpoint artifact is not a regular file')
    return _bounded_blob(workspace, commit + ':' + relative)


def _parent_blob(workspace: str, parent: str, relative: str) -> bytes:
    result = subprocess.run(['git', '-C', workspace, 'ls-tree', '-z', parent, '--', ':(literal)' + relative],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    entry = result.stdout.rstrip(b'\0').split(b'\t')
    fields = entry[0].split() if len(entry) == 2 else []
    if (len(fields) != 3 or fields[0] not in {b'100644', b'100755'} or fields[1] != b'blob'
            or entry[1] != os.fsencode(relative)):
        raise ClaudeBindingError('Edit artifact parent is not a regular file')
    return _bounded_blob(workspace, parent + ':' + relative)


def _live_artifact_exists(workspace: str, path: Path, *, read: bool = False) -> bytes | None:
    """Retain a no-follow live path check, but never source captured bytes from it."""
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
        if not read:
            return None
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            body = stream.read(MAX_ARTIFACT + 1)
            if len(body) > MAX_ARTIFACT:
                raise ClaudeBindingError('required delivered artifact exceeds capture bound')
            return body
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def capture_artifacts(native: Mapping[str, Any], workspace: str) -> list[dict[str, Any]]:
    checkpoint = _worker_checkpoint(workspace)
    states: dict[str, tuple[Path, bytes, str]] = {}
    tools = native['tools']
    results = native['tool_results']
    for ident, tool in tools.items():
        if tool['name'] not in {'Write', 'Edit'} or results[ident].get('is_error', False):
            continue
        inputs = tool.get('input') or {}
        path = _artifact_path(workspace, inputs.get('file_path'))
        relative = str(path.relative_to(workspace))
        if relative not in states:
            if checkpoint is None:
                # Preserve the established non-Git owner fixture, which has no
                # landing checkpoint and supports only direct Write capture.
                if tool['name'] != 'Write':
                    raise ClaudeBindingError('Edit artifact requires a worker checkpoint')
                current = b''
            else:
                current = _parent_blob(workspace, checkpoint[1], relative) if tool['name'] == 'Edit' else b''
            states[relative] = (path, current, ident)
        _, current, _ = states[relative]
        if tool['name'] == 'Write':
            content = inputs.get('content')
            if not isinstance(content, str):
                raise ClaudeBindingError('successful Write has invalid content')
            current = content.encode('utf-8')
        else:
            old, new = inputs.get('old_string'), inputs.get('new_string')
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ClaudeBindingError('successful Edit has invalid replacement input')
            old_bytes, new_bytes = old.encode('utf-8'), new.encode('utf-8')
            replace_all = inputs.get('replace_all') is True
            if old_bytes not in current:
                raise ClaudeBindingError('Edit input does not apply to authorized artifact bytes')
            if not replace_all and current.count(old_bytes) != 1:
                raise ClaudeBindingError('Edit input is ambiguous for authorized artifact bytes')
            current = current.replace(old_bytes, new_bytes) if replace_all else current.replace(old_bytes, new_bytes, 1)
        if len(current) > MAX_ARTIFACT:
            raise ClaudeBindingError('required delivered artifact exceeds capture bound')
        states[relative] = (path, current, ident)

    artifacts = []
    if len(states) > 16:
        raise ClaudeBindingError('delivered artifacts exceed bounded capture')
    for relative, (path, body, ident) in states.items():
        live_body = _live_artifact_exists(workspace, path, read=checkpoint is None)
        if checkpoint is not None and _checkpoint_blob(workspace, checkpoint[0], relative) != body:
            raise ClaudeBindingError('checkpoint artifact differs from successful native Write/Edit inputs')
        elif checkpoint is None:
            # Existing no-Git Write fixture still verifies the live tool result.
            if live_body != body:
                raise ClaudeBindingError('artifact bytes differ from the successful native Write input')
        artifacts.append({'name': relative, 'tool_use_id': ident,
            'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
            'content_base64': base64.b64encode(body).decode('ascii')})
    if not artifacts:
        raise ClaudeBindingError('useful Claude leaf requires a verified delivered Write/Edit artifact')
    return artifacts


def native_context(native: Mapping[str, Any], *, brief: Mapping[str, Any], authorization: Mapping[str, Any],
                   prompt: str, workspace: str, model: str, reasoning: str) -> dict[str, Any]:
    role = _delivered_role({'owner_delivery_authorization': authorization})
    result = native['result']
    body = result['result']
    session, turn = native['session_id'], native['turn_id']
    answer = {'text': body, 'format': FINAL_FORMAT, 'phase': 'final_answer',
              'text_sha256': hashlib.sha256(body.encode()).hexdigest(), 'utf8_bytes': len(body.encode()),
              'host_record': native['refs']['final_answer']}
    # A worker leaf must deliver a verified Write/Edit artifact. A manager's useful
    # effects are owner records made through its commands, so none is captured.
    output = {'final_answer': answer,
              'artifacts': capture_artifacts(native, workspace) if ROLE_PROFILES[role]['artifacts_required'] else []}
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
        minimum = 1 if ROLE_PROFILES[_delivered_role(evidence)]['artifacts_required'] else 0
        if not minimum <= len(artifacts) <= 16:
            raise ClaudeBindingError('bounded captured artifact inventory required')
        captured = []
        for index, artifact in enumerate(artifacts):
            captured_artifact_bytes(artifact)
            ref = {'result_ref': dict(result_ref), 'index': index, 'sha256': artifact['sha256']}
            captured.append({**artifact, 'ref': ref, 'availability': 'retained',
                             'source': 'verified native Write/Edit and owner capture'})
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
                or (ROLE_PROFILES[_delivered_role(evidence)]['artifacts_required'] and not output.get('artifacts'))
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


def _compose_on_process(observer, authorization, pin):
    """Host registration for one native work process, or None when there is none.

    The managed caller-socket observer (``observer``, managers with a socket only)
    runs first and its cleanup is the one returned. Then ``pin``, the separate
    pin-only hook, records the group for every role. A worker has no observer, so
    its cleanup is a no-op. claude_cli requires a callable cleanup from this callback.
    """
    if observer is None and not callable(pin):
        return None

    def on_process(process):
        cleanup = observer(process, dict(authorization)) if observer is not None else (lambda: None)
        if callable(pin):
            pin(process)
        return cleanup
    return on_process


class ClaudeWorkerAdapter:
    owner_transport_only = True
    owner_bound = True
    require_host_context = True
    adapter_identity = IDENTITY
    # Worker invocations are finite leaves (no coordinating workers); the
    # manager role is a separate declared capability, see ``roles``.
    leaf_only = True

    def __init__(self, *, owner: str, source: str, worktree: str, launcher_pin: LauncherPin,
                 state_root: str, requested_model: str, requested_reasoning: str = 'high',
                 transport: ClaudeCliTransport | None = None, authentication: str = 'existing-user',
                 roles: tuple = ('worker',), manager_transport: ClaudeCliTransport | None = None,
                 manager_write_roots: tuple = (), native_caller_socket: str | None = None,
                 native_process_observer: Any = None, manager_timeout_seconds: float = 1800,
                 manager_env: Mapping[str, str] | None = None, worker_mcp: McpGrant | None = None):
        self.owner, self.source = text(owner, 'owner'), text(source, 'source')
        self.worktree = str(Path(worktree).resolve(strict=True))
        self.writable_roots = ()
        self.launcher_pin, self.launcher, self.state_root = launcher_pin, launcher_pin.realpath, state_root
        self.requested_model, self.requested_reasoning = requested_model, requested_reasoning
        roles = tuple(roles)
        if not roles or set(roles) - set(ROLE_PROFILES) or len(set(roles)) != len(roles):
            raise ClaudeBindingError('declared Claude roles must be a subset of ' + ', '.join(sorted(ROLE_PROFILES)))
        self.roles = roles
        if native_caller_socket is not None and ('manager' not in roles or not callable(native_process_observer)):
            raise ClaudeBindingError('a managed caller socket requires the manager role and its process observer')
        self.native_caller_socket, self.native_process_observer = native_caller_socket, native_process_observer
        # Pin-only hook: called once per native work process for every role (see _compose_on_process).
        self.process_pin = None
        if worker_mcp is not None:
            require_sole_server(worker_mcp, TOOL_SERVER)
        self.transport = transport or ClaudeCliTransport(launcher_pin,
            MacWriteScope(self.worktree, state_root, authentication=authentication,
                          exec_allow=() if worker_mcp is None else exec_allow_for(worker_mcp)),
            model=requested_model, reasoning=requested_reasoning, authentication=authentication, mcp=worker_mcp)
        self.manager_transport = None
        if 'manager' in roles:
            self.manager_transport = manager_transport or ClaudeCliTransport(launcher_pin,
                MacWriteScope(self.worktree, state_root, authentication=authentication,
                              allow_subprocesses=True, extra_write_roots=manager_write_roots),
                model=requested_model, reasoning=requested_reasoning, authentication=authentication,
                tools=MANAGER_TOOLS, max_turns=ROLE_PROFILES['manager']['max_turns'],
                timeout_seconds=manager_timeout_seconds,
                extra_env={**dict(manager_env or {}),
                           **({} if native_caller_socket is None else {'OTTO_CALLER_SOCKET': native_caller_socket})})
        self._role = None
        self._authorizer = self._verifier = self._completed_verifier = None
        self._thread_started_callback = self._turn_started_callback = None
        self._used = False

    def _transport_for(self, role: str) -> ClaudeCliTransport:
        if role not in self.roles:
            raise ClaudeBindingError('Claude composition does not declare the ' + str(role) + ' role')
        return self.manager_transport if role == 'manager' else self.transport

    def pins(self) -> Mapping[str, Any]:
        role = self._role or 'worker'
        value = {'launcher': vars(self.launcher_pin), 'parser_schema': PARSER_SCHEMA,
                'parser_sha256': file_digest(Path(__file__).with_name('claude_cli.py')),
                'binding_sha256': file_digest(Path(__file__)), 'scope': self._transport_for(role).scope.pin,
                'model': self.requested_model, 'reasoning': self.requested_reasoning,
                'authentication': self.transport.authentication,
                'permission_mode': ('dontAsk' if role == 'worker' and not getattr(self.transport, 'mcp', McpGrant()).empty
                                    else 'bypassPermissions'),
                'profile': 'workspace-write', 'role': 'worker-leaf' if role == 'worker' else role}
        if self.roles != ('worker',):
            value.update(roles=list(self.roles), tools=list(ROLE_PROFILES[role]['tools']))
        return value

    def capabilities(self) -> Mapping[str, Any]:
        pins = self.pins()
        def cap(state, reason): return {'state': state, 'reason': reason, 'pins': pins}
        return {'useful_leaf': cap('unverified', 'requires authentic installed useful journey and host adoption'),
                'structured_stream': cap('unverified', 'synthetic parser/process checks do not qualify installed schema'),
                'snapshot_follow': cap('supported', 'existing retained owner snapshot reads'),
                'native_streaming': cap('unsupported', 'no partial-token stream advertised'),
                'attach': cap('unsupported', 'no native attach binding'),
                'resume': (cap('unverified', 'declared manager continuation of the exact owner-bound session '
                               '(--resume); synthetic conformance only')
                           if 'manager' in self.roles else
                           cap('unsupported', 'exact initializer-to-work continuation is internal; no later resume qualification')),
                'cancel': cap('degraded', 'transport unwinding reaps its owned process group; owner stop is only a fence'),
                'steering': cap('unsupported', 'stdin sealed for bounded leaf'),
                'native_children': cap('unsupported', 'Agent/Bash/MCP/customizations disabled; child frames rejected'),
                'manager': (cap('unverified', 'declared manager profile: Bash/Edit/Glob/Grep/Read/Write under the '
                                'inherited OS write fence; synthetic conformance only, no installed journey')
                            if 'manager' in self.roles else cap('unsupported', 'worker-leaf only')),
                'coordinator': cap('unsupported', 'no delegated authority or native caller tools')}

    def validate_owner_host_composition(self, *, role: str, profile: str) -> None:
        if role not in self.roles or profile != 'workspace-write':
            raise ClaudeBindingError('Claude composition supports only workspace-write ' + '/'.join(self.roles)
                                     + ' roles; ' + str(role) + ' is not declared')
        self._transport_for(role).preflight()

    def bind_owner_authorization(self, authorizer, *, verifier=None, completed_verifier=None, role=None, profile=None):
        if (role not in self.roles or profile != 'workspace-write'
                or not callable(authorizer) or not callable(verifier)):
            raise ClaudeBindingError('exact owner-authorized ' + '/'.join(self.roles) + ' composition required')
        bound = copy.copy(self)
        bound._authorizer, bound._verifier, bound._completed_verifier = authorizer, verifier, completed_verifier
        bound._role = role
        bound._used = False
        return bound

    def set_thread_started_callback(self, callback):
        prior = self._thread_started_callback; self._thread_started_callback = callback; return prior

    def set_usage_callback(self, callback):
        prior = getattr(self, "_usage_callback", None); self._usage_callback = callback; return prior

    def set_turn_started_callback(self, callback):
        prior = self._turn_started_callback; self._turn_started_callback = callback; return prior

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._owner_turn(request, operation='invoke')

    def resume(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Continue the exact owner-bound manager session (`--resume`), no initializer.

        Only the declared manager role continues a session: the owner's
        continuation (after a worker result, a report or help) authorizes the
        same native session again before the new turn's input is delivered.
        """
        return self._owner_turn(request, operation='resume')

    def _owner_turn(self, request: Mapping[str, Any], *, operation: str) -> Mapping[str, Any]:
        from otto.portfolio.execution_host import ExecutionHost
        from herzchen.adapters.host import _owner_delivery_appendix
        typed, brief_digest, brief = HerzchenCodexAdapter._typed_request(self, operation, request)
        contract = brief['instruction_contract']; authority = contract['authority']
        role = self._role or 'worker'
        profile = ROLE_PROFILES[role]
        transport = self._transport_for(role)
        existing = request.get('physical_session_id')
        if operation == 'resume' and (role != 'manager' or not isinstance(existing, str) or not existing.strip()):
            raise ClaudeBindingError('only the declared manager role continues an exact existing session')
        if (self._used or not callable(self._authorizer) or not callable(self._verifier)
                or not callable(self._thread_started_callback)
                or not callable(self._turn_started_callback)
                or (operation == 'invoke' and existing is not None) or request.get('expected_role') != role
                or typed.requested_profile != 'workspace-write' or contract.get('delegation') is not None
                or authority.get('gateway_claim_required') is not True
                or authority.get('owner_write') is not False or authority.get('dispatch') is not False
                or authority.get('effect_profile') != profile['effect_profile']
                or set(authority.get('workspace_roots', [])) != {self.worktree}
                or set(authority.get('permitted_effects', [])) - set(profile['effects'])
                or request.get('requested_model', self.requested_model) != self.requested_model
                or request.get('requested_reasoning', self.requested_reasoning) != self.requested_reasoning):
            raise ClaudeBindingError('Claude ' + role + ' scope, owner binding or model selection mismatch')
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
        usage_callback = ExecutionHost.owner_callback(getattr(self, "_usage_callback", None))
        usage_options = {} if usage_callback is None else {"on_usage": usage_callback}
        try:
            if operation == 'resume':
                # Owner-bound continuation: no new initializer. Bind the existing
                # session to this occurrence's claim before authorization.
                init = {}
                on_thread(existing)
            else:
                init = ExecutionHost.external_call(lambda: transport.run(
                    'Initialize this session only. Do not use tools or do task work. Return READY.',
                    initializer=True, on_init=on_thread, **usage_options))
                session = init['session_id']
                if init['outcome'] != 'succeeded' or init['result'].get('result', '').strip() != 'READY' or init['tools']:
                    raise ClaudeBindingError('inert native initializer was not exact READY')
            authorization = authorize(session, brief_digest)
            expected = {'status': 'authorized', 'physical_session_id': session,
                'brief_sha256': brief_digest, 'logical_request_key': request['logical_request_key'],
                'project_ref': request.get('expected_project_ref'), 'task_ref': typed.target.to_dict(),
                'assignment_ref': request.get('expected_assignment_ref'), 'generation': request.get('expected_generation'),
                'role': role, 'principal': request.get('expected_principal'),
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
            observer = None
            if role == 'manager' and self.native_caller_socket is not None:
                # Register the owned native process so the managed caller
                # socket can authenticate its descendants (kernel peer PID).
                observer = ExecutionHost.owner_callback(self.native_process_observer)
            on_process = _compose_on_process(observer, authorization, self.process_pin)
            work = ExecutionHost.external_call(lambda: transport.run(prompt, session=session,
                on_input=input_started, on_process=on_process, **usage_options))
            if work['outcome'] == 'failed':
                return {'outcome': 'failed', 'physical_session_id': session, 'observed_turn_id': work['turn_id'],
                        'delivery_state': 'failed', 'native_failure': work['result'], 'usage': work['usage'],
                        'usage_capture': {'schema': 'otto.usage-capture.phases.v1',
                            'initializer': init.get('usage_capture'), 'work': work.get('usage_capture')},
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
                'usage_capture': {'schema': 'otto.usage-capture.phases.v1',
                    'initializer': init.get('usage_capture'), 'work': work.get('usage_capture')},
                'delivery_state': 'done', 'work_receipt': {'observed_profile': 'workspace-write'},
                'work_envelope': {'host_evidence': {'otto_host_turn_context': context}},
                'raw_result': {'worker_content': checked['worker_content'],
                    'work_receipt': {'observed_profile': 'workspace-write'},
                    'work_envelope': {'host_evidence': {'otto_host_turn_context': context}},
                    'native_pins': native_pins},
                'native_pins': native_pins, 'capabilities': self.capabilities()}
        except Exception as exc:
            error = {'code': ('claude_child_exited_before_input' if isinstance(exc, ClaudeChildExitError)
                              else 'claude_qualification_or_capture_held'), 'message': str(exc)}
            result = {'outcome': 'unknown', 'delivery_state': 'unknown', 'physical_session_id': session,
                'useful_input_observed': admitted, 'retry_allowed': False,
                'error': error, 'reason': str(exc),
                'next_actor': 'host through assigned manager; reconcile exact attempt, scope and retained stream'}
            if isinstance(exc, ClaudeChildExitError):
                result['child_exit_status'] = exc.exit_status
                result['stderr_tail'] = exc.stderr_tail
            return result
