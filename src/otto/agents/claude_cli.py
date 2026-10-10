"""Pinned local Claude structured-stream transport; no retries or owner writes.

The sole candidate profile exposes Read/Write, disables customizations, and
requires an OS file-write fence. CLI permission flags alone never qualify it.
Native initialization is inert; an owner must authorize the exact session
before the separate useful turn. Installed qualification is a host obligation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

PARSER_SCHEMA = "otto.claude-code-2.1.293.stream-json.v1"
VERSION = "2.1.293 (Claude Code)"
MAX_LINE = 256 * 1024
MAX_STREAM = 2 * 1024 * 1024
MAX_ARTIFACT = 65536


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ClaudeBindingError(ValueError):
    pass


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ClaudeBindingError(field + " must be nonblank text")
    return value


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _preflight_interpreter() -> Mapping[str, str]:
    """Pin the host interpreter that runs without spawning a framework wrapper.

    Apple's framework bin/python entry point posix_spawns Python.app. The
    scope permits one executable and denies fork/other exec, so use the direct
    executable from that same framework rather than broadening the fence.
    """
    executable = Path(sys.executable).resolve(strict=True)
    if (executable.parent.name == 'bin'
            and executable.parent.parent.parent.name == 'Versions'
            and executable.parent.parent.parent.parent.name in {'Python.framework', 'Python3.framework'}):
        executable = (executable.parent.parent / 'Resources/Python.app/Contents/MacOS/Python').resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ClaudeBindingError('host preflight interpreter is not executable')
    return {'realpath': str(executable), 'sha256': file_digest(executable)}


@dataclass(frozen=True)
class LauncherPin:
    locator: str
    realpath: str
    sha256: str
    version: str

    @classmethod
    def inspect(cls, launcher: str) -> "LauncherPin":
        path = Path(launcher)
        if not path.is_absolute():
            raise ClaudeBindingError("absolute trusted launcher required; no PATH fallback")
        real = path.resolve(strict=True)
        before = file_digest(real)
        result = subprocess.run([str(real), "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
        if result.returncode or result.stdout.strip() != VERSION or file_digest(real) != before:
            raise ClaudeBindingError("launcher version unsupported or changed during inspection")
        return cls(str(path), str(real), before, result.stdout.strip())

    def verify(self) -> None:
        if (str(Path(self.locator).resolve(strict=True)) != self.realpath
                or file_digest(Path(self.realpath)) != self.sha256 or self.version != VERSION):
            raise ClaudeBindingError("pinned Claude launcher drift/removal; host reconciliation required")


class MacWriteScope:
    """Finite OS fence for Read/Write leafs, with private native state custody.

    The host provisions authentication in state_root. No user credentials are
    copied and no live provider configuration is modified by this adapter.
    """
    identity = "otto.claude-macos-file-write-scope.v1"

    def __init__(self, workspace: str, state_root: str, *, authentication: str = 'isolated'):
        self.workspace = str(Path(workspace).resolve(strict=True))
        self.state_root = str(Path(state_root).resolve(strict=True))
        if (not Path(self.workspace).is_dir() or not Path(self.state_root).is_dir()
                or self.workspace == self.state_root
                or Path(self.workspace) in Path(self.state_root).parents
                or Path(self.state_root) in Path(self.workspace).parents):
            raise ClaudeBindingError("separate existing workspace and host-owned state roots required")
        if authentication not in {'existing-user', 'isolated'}:
            raise ClaudeBindingError('unsupported authentication profile')
        self.authentication = authentication
        self.auth_helper = None
        if authentication == 'existing-user':
            shared = (Path.home() / '.claude').resolve()
            for root in (Path(self.workspace), Path(self.state_root)):
                if root == shared or root in shared.parents or shared in root.parents:
                    raise ClaudeBindingError('shared Claude configuration must remain read-only')
            cache = subprocess.check_output(['/usr/bin/getconf', 'DARWIN_USER_CACHE_DIR'],
                                            text=True, timeout=5).strip()
            lock = Path(cache) / 'mds' / 'mds.lock'
            if not lock.is_file() or lock.is_symlink():
                raise ClaudeBindingError('native security lock unavailable; no broad write fallback')
            helper = Path('/usr/bin/security')
            self.auth_helper = {'executable': str(helper), 'sha256': file_digest(helper),
                                'lock': str(lock.resolve(strict=True))}
        quote = json.dumps
        self.policy = ('(version 1)(allow default)(deny file-write*)(deny process-fork)(deny process-exec)'
            + ''.join('(allow file-write* (subpath ' + quote(root) + '))'
                      for root in (self.workspace, self.state_root))
            + '(allow file-write* (literal "/dev/null"))'
            + ''.join('(deny file-write* (subpath ' + quote(str(Path(self.workspace) / name)) + '))'
                      for name in ('.git', '.agents', '.codex', '.aws', '.claude')))
        if self.auth_helper:
            self.policy += ('(allow process-fork)(allow process-exec (literal "/usr/bin/security"))'
                            '(allow file-write-data (literal ' + quote(self.auth_helper['lock']) + '))')
        self.pin = {"authentication": authentication, "auth_helper": self.auth_helper,
                    "identity": self.identity, "workspace": self.workspace,
                    "state_root": self.state_root, "policy_sha256": hashlib.sha256(self.policy.encode()).hexdigest(),
                    "sandbox_runner": '/usr/bin/sandbox-exec',
                    "sandbox_runner_sha256": file_digest(Path('/usr/bin/sandbox-exec'))}
        self.preflight_interpreter = dict(_preflight_interpreter())

    def preflight(self) -> Mapping[str, Any]:
        if sys.platform != "darwin":
            raise ClaudeBindingError("candidate scope requires macOS sandbox-exec; no permissive fallback")
        if self.auth_helper and file_digest(Path(self.auth_helper['executable'])) != self.auth_helper['sha256']:
            raise ClaudeBindingError('native authentication helper changed')
        # Managed hooks/plugins can precede the stream. This profile does not
        # qualify a managed-policy extension or an alternate sandbox runner.
        policy_root = Path('/Library/Application Support/ClaudeCode')
        if any((policy_root / name).exists() for name in ('managed-settings.json', 'managed-mcp.json')):
            raise ClaudeBindingError("managed Claude policy needs separate host qualification")
        interpreter = Path(self.preflight_interpreter['realpath'])
        if (str(interpreter.resolve(strict=True)) != str(interpreter)
                or file_digest(interpreter) != self.preflight_interpreter['sha256']):
            raise ClaudeBindingError('pinned host preflight interpreter changed')
        # Prove actual fence installation, permitted writes and denied escapes.
        probe = ('import os,sys,tempfile; '
                 'a=tempfile.NamedTemporaryFile(dir=sys.argv[1]); a.write(b"scope"); a.flush(); '
                 'b=tempfile.NamedTemporaryFile(dir=sys.argv[2]); b.write(b"scope"); b.flush(); '
                 '\ntry:\n f=tempfile.NamedTemporaryFile(dir="/private/tmp")\n f.close()\n sys.exit(9)'
                 '\nexcept PermissionError: pass')
        result = subprocess.run(self.wrap([str(interpreter), '-c', probe, self.workspace, self.state_root]),
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ClaudeBindingError("OS scope preflight failed: " + result.stderr[:512])
        return {**self.pin, "preflight_interpreter": dict(self.preflight_interpreter),
                "verified": True, "proof": "permitted writes and denied outside-root create"}

    def wrap(self, command: list[str], *, initializer: bool = False) -> list[str]:
        # Initializer hooks cannot write task files even before native init.
        # No subprocess/tool shell can escape the selected leaf surface.
        policy = self.policy + '(allow process-exec (literal ' + json.dumps(command[0]) + '))'
        if initializer:
            policy += '(deny file-write* (subpath ' + json.dumps(self.workspace) + '))'
        return ['/usr/bin/sandbox-exec', '-p', policy, *command]


class ClaudeStream:
    """Strict selected native schema. Worker text supplies no authority facts."""

    def __init__(self, *, prompt: str, cwd: str, model: str, tools: tuple[str, ...],
                 session: str | None = None, on_init: Callable[..., Any] | None = None,
                 on_input: Callable[..., Any] | None = None,
                 on_usage: Callable[..., Any] | None = None, phase: str = "work"):
        self.prompt, self.cwd, self.model, self.tools = prompt, cwd, model, tools
        self.session, self.on_init, self.on_input = session, on_init, on_input
        from .usage_capture import UsageStream
        self.usage_stream = UsageStream("claude-code", phase=phase, session_id=session,
            requested_model=model, on_usage=on_usage)
        self.init = self.input = self.result = None
        self.refs: dict[str, Any] = {}
        self.tool_uses: dict[str, Any] = {}
        self.tool_results: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.bytes = 0

    def feed(self, raw: bytes) -> None:
        self.bytes += len(raw)
        if len(raw) > MAX_LINE or self.bytes > MAX_STREAM:
            raise ClaudeBindingError("native stream exceeds selected bounds")
        try:
            def unique_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError('duplicate JSON key')
                    value[key] = item
                return value
            event = json.loads(raw, object_pairs_hook=unique_object,
                parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
        except (UnicodeError, ValueError) as exc:
            raise ClaudeBindingError("invalid native JSONL") from exc
        if not isinstance(event, dict):
            raise ClaudeBindingError("native stream item must be an object")
        kind = event.get('type')
        if self.result is not None:
            raise ClaudeBindingError("observation after terminal or duplicate result")
        if kind == 'system' and event.get('subtype') == 'init':
            if self.init is not None:
                raise ClaudeBindingError("duplicate native initialization")
            session = text(event.get('session_id'), 'native session')
            if (self.session is not None and session != self.session or event.get('cwd') != self.cwd
                    or event.get('model') != self.model or event.get('permissionMode') != 'bypassPermissions'
                    or not isinstance(event.get('tools'), list) or sorted(event['tools']) != sorted(self.tools)
                    or event.get('mcp_servers') != [] or event.get('plugins', []) != []
                    or event.get('skills', []) != [] or event.get('slash_commands', []) != []):
                raise ClaudeBindingError("native identity/model/scope/tool ingress mismatch")
            self.session, self.init = session, event
            if self.on_init:
                self.on_init(session)
        elif kind == 'user':
            if self.init is None or event.get('session_id') != self.session or event.get('parent_tool_use_id') is not None:
                raise ClaudeBindingError("foreign or uninitialized native user input")
            message = event.get('message') or {}
            content = message.get('content')
            if message.get('role') != 'user' or not isinstance(content, list):
                raise ClaudeBindingError("unsupported native user schema")
            if content and all(isinstance(b, dict) and b.get('type') == 'text' for b in content):
                if self.input is not None or ''.join(b.get('text', '') for b in content) != self.prompt:
                    raise ClaudeBindingError("native admitted input differs or is duplicated")
                text(event.get('uuid'), 'native input uuid')
                self.input = event
                if self.on_input:
                    self.on_input(event['uuid'])
            else:
                if self.input is None:
                    raise ClaudeBindingError("tool result before admitted input")
                for block in content:
                    if not isinstance(block, dict) or block.get('type') != 'tool_result':
                        raise ClaudeBindingError("unsupported native tool result")
                    ident = block.get('tool_use_id')
                    if ident not in self.tool_uses or ident in self.tool_results or type(block.get('is_error', False)) is not bool:
                        raise ClaudeBindingError("unknown or duplicate native tool result")
                    self.tool_results[ident] = block
        elif kind == 'assistant':
            if (self.input is None or event.get('session_id') != self.session
                    or event.get('parent_tool_use_id') is not None):
                raise ClaudeBindingError("assistant work before input or native child outside coverage")
            message = event.get('message') or {}
            if message.get('model') != self.model or message.get('role') != 'assistant' or not isinstance(message.get('content'), list):
                raise ClaudeBindingError("native assistant model/schema mismatch")
            for block in message['content']:
                if not isinstance(block, dict):
                    raise ClaudeBindingError("invalid assistant content")
                if block.get('type') == 'tool_use':
                    ident = text(block.get('id'), 'tool use id')
                    if ident in self.tool_uses or block.get('name') not in self.tools or not isinstance(block.get('input'), dict):
                        raise ClaudeBindingError("unqualified or duplicate native tool ingress")
                    self.tool_uses[ident] = block
        elif kind == 'result':
            if (self.input is None or event.get('session_id') != self.session
                    or type(event.get('is_error')) is not bool):
                raise ClaudeBindingError("native result lacks exact input/session/error fact")
            text(event.get('uuid'), 'native result uuid')
            if event.get('subtype') not in {'success', 'error_during_execution', 'error_max_turns', 'error_max_budget_usd', 'error_max_structured_output_retries'}:
                raise ClaudeBindingError("unsupported native result subtype")
            if event['subtype'] != 'success' and not event['is_error']:
                raise ClaudeBindingError("native error cannot map to success")
            if not event['is_error']:
                text(event.get('result'), 'native final result')
                if event.get('permission_denials') not in (None, []):
                    raise ClaudeBindingError('required tool ingress was denied; useful result remains held')
                if set(self.tool_uses) != set(self.tool_results):
                    raise ClaudeBindingError("incomplete native tool results")
            self.result = event
        else:
            # Do not accept telemetry, partial streams, hook records or child
            # notifications as a replacement for the selected schema.
            raise ClaudeBindingError("unqualified native event: " + str(kind))
        ref = {"session_id": self.session, "turn_id": (self.input or {}).get('uuid'),
               "event_type": kind, "item_type": 'ClaudeResult' if kind == 'result' else kind,
               "item_id": event.get('uuid'), "raw_line_sha256": hashlib.sha256(raw).hexdigest()}
        self.usage_stream.feed(raw)
        self.events.append(ref)
        if kind == 'user':
            for block in event['message']['content']:
                if block.get('type') == 'tool_result':
                    self.refs.setdefault('tool_results', {})[block['tool_use_id']] = {
                        **ref, 'item_type': 'ClaudeToolResult', 'item_id': block['tool_use_id']}
        if kind == 'result':
            self.refs['final_answer'] = ref

    def finish(self, exit_code: int) -> Mapping[str, Any]:
        if self.result is None:
            raise ClaudeBindingError("initializer-only, killed process or incomplete native stream")
        if not self.result['is_error'] and exit_code != 0:
            raise ClaudeBindingError("native success conflicts with process failure")
        return {'session_id': self.session, 'turn_id': self.input['uuid'],
                'outcome': 'failed' if self.result['is_error'] else 'succeeded',
                'result': self.result, 'refs': self.refs, 'tools': self.tool_uses,
                'tool_results': self.tool_results, 'events': self.events}

    def usage(self) -> Mapping[str, Any]:
        value = (self.result or {}).get('usage')
        names = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
        if not isinstance(value, dict) or not any(name in value for name in names):
            return {'state': 'unavailable', 'reason': 'native terminal did not expose qualified token fields'}
        fields = {name: value[name] for name in names if name in value}
        if any(type(n) is not int or n < 0 for n in fields.values()):
            return {'state': 'invalid', 'reason': 'native token field is not a nonnegative integer'}
        return {'state': 'observed', 'metrics': fields, 'scope': 'native result invocation',
                'source': self.refs['final_answer'], 'model': self.model,
                'limits': 'native reported fields only; no price, sum, descendant or billing claim'}


class ClaudeCliTransport:
    """Sealed stdin and bounded pipe custody for exactly one native turn."""

    def __init__(self, pin: LauncherPin, scope: MacWriteScope, *, model: str, reasoning: str,
                 timeout_seconds: float = 120, process_factory: Callable[..., Any] = subprocess.Popen,
                 authentication: str = 'existing-user'):
        if authentication not in {'existing-user', 'isolated'}:
            raise ClaudeBindingError('unsupported authentication profile')
        self.authentication = authentication
        self.pin, self.scope = pin, scope
        self.model, self.reasoning = text(model, 'model'), text(reasoning, 'reasoning')
        if reasoning not in {'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ClaudeBindingError("unsupported Claude effort; no fallback")
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 1800:
            raise ClaudeBindingError("bounded finite owner timeout required")
        self.timeout_seconds, self.process_factory = timeout_seconds, process_factory

    def preflight(self) -> Mapping[str, Any]:
        self.pin.verify()
        return self.scope.preflight()

    def environment(self) -> dict[str, str]:
        """Let native Claude own credentials; never extract or copy tokens.

        Existing-user deliberately leaves CLAUDE_CONFIG_DIR unset (even setting
        it to ~/.claude can select another keychain namespace). Safe mode keeps
        customizations disabled. The OS write fence remains independent.
        """
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('CLAUDE_', 'ANTHROPIC_'))}
        env.update(CLAUDE_CODE_SAFE_MODE='1',
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                   TMPDIR=self.scope.state_root)
        if self.authentication == 'isolated':
            env['CLAUDE_CONFIG_DIR'] = self.scope.state_root
        return env

    def run(self, prompt: str, *, session: str | None = None,
            initializer: bool = False, on_init: Any = None, on_input: Any = None, on_usage: Any = None) -> Mapping[str, Any]:
        proof = self.preflight()  # Before process creation, including initialization.
        tools = () if initializer else ('Read', 'Write')
        command = [self.pin.realpath, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
                   '--verbose', '--replay-user-messages', '--safe-mode', '--setting-sources', '',
                   '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--disable-slash-commands',
                   '--dangerously-skip-permissions', '--tools', ','.join(tools), '--model', self.model,
                   '--effort', self.reasoning, '--max-turns', '1' if initializer else '8']
        if not initializer:
            command.extend(['--allowedTools', 'Read(' + self.scope.workspace + '/**)', 'Write(' + self.scope.workspace + '/**)'])
        if session is not None:
            command.extend(['--resume', text(session, 'exact native session')])
        frame = {'type': 'user', 'session_id': session or '', 'message': {'role': 'user',
                 'content': [{'type': 'text', 'text': text(prompt, 'admitted input')}]}}
        data = (json.dumps(frame, ensure_ascii=False) + '\n').encode()
        if len(data) > MAX_LINE:
            raise ClaudeBindingError("admitted input exceeds profile bound")
        env = self.environment()
        parser = ClaudeStream(prompt=prompt, cwd=self.scope.workspace, model=self.model,
                              tools=tools, session=session, on_init=on_init, on_input=on_input,
                              on_usage=on_usage, phase="initializer" if initializer else "work")
        process = self.process_factory(self.scope.wrap(command, initializer=initializer), cwd=self.scope.workspace,
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        selector = selectors.DefaultSelector()
        stdout = bytearray(); stderr = bytearray(); offset = 0
        deadline = time.monotonic() + self.timeout_seconds
        try:
            for stream, role, event in ((process.stdin, 'stdin', selectors.EVENT_WRITE),
                    (process.stdout, 'stdout', selectors.EVENT_READ), (process.stderr, 'stderr', selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False); selector.register(stream, event, role)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise ClaudeBindingError("owned process timeout; native terminal unproved; no replay")
                for key, _ in selector.select(min(.1, max(0, deadline - time.monotonic()))):
                    if key.data == 'stdin':
                        offset += os.write(key.fd, data[offset:offset + 65536])
                        if offset == len(data):
                            selector.unregister(key.fileobj); key.fileobj.close()
                        continue
                    part = os.read(key.fd, 65536)
                    if not part:
                        selector.unregister(key.fileobj); key.fileobj.close(); continue
                    if key.data == 'stderr':
                        if len(stderr) + len(part) > MAX_LINE:
                            raise ClaudeBindingError("native stderr exceeds profile bound")
                        stderr.extend(part); continue
                    stdout.extend(part)
                    while b'\n' in stdout:
                        raw, _, rest = stdout.partition(b'\n'); stdout = bytearray(rest)
                        parser.feed(raw)
                    if len(stdout) > MAX_LINE:
                        raise ClaudeBindingError("native line exceeds profile bound")
            if stdout:
                raise ClaudeBindingError("incomplete JSONL framing")
            code = process.wait(timeout=max(.01, deadline - time.monotonic()))
            result = dict(parser.finish(code))
            return {**result, 'usage': parser.usage(), 'usage_capture': parser.usage_stream.snapshot(), 'scope': proof, 'command': command,
                    'exit_status': code, 'stderr': stderr.decode('utf-8', errors='replace')[:4096],
                    'launcher': vars(self.pin), 'parser_schema': PARSER_SCHEMA}
        finally:
            selector.close()
            if process.poll() is None:
                # Only this owned process group; no provider-session deletion.
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed: stream.close()
