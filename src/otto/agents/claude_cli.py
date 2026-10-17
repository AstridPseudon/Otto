"""Pinned local Claude structured-stream transport; no retries or owner writes.

The sole candidate profile exposes Read/Write, disables customizations, and
requires an OS file-write fence. CLI permission flags alone never qualify it.
Native initialization is inert; an owner must authorize the exact session
before the separate useful turn. Installed qualification is a host obligation.

The launch flags, the fence policy, the tool surfaces and the strict stream
parser belong to the Claude host in ``herzchen.fleet.hosts.claude``; this module
keeps the owner-side custody: the pinned launcher, the proven fence and the
bounded process loop.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

from herzchen.fleet.hosts import McpGrant, TurnSpec, get_host
from herzchen.fleet.hosts.contract import HostContractError
from herzchen.fleet.custody import Custody
from herzchen.fleet.tools import CHECK, DONE, TASK, ToolSpec
from herzchen.fleet.tools.pins import exec_allow_for_commands
# Re-exported: the owner-side adapters import these names from this module.
from herzchen.fleet.hosts.claude import (MAX_LINE, MAX_STREAM, WORKER_BUILTIN_TOOLS, ClaudeBindingError,
                                         ClaudeStream, sandbox_policy, sandbox_wrap, text, validate_effort,
                                         validate_max_turns, validate_tools)

VERSION = "2.1.293 (Claude Code)"
MAX_ARTIFACT = 65536
CLAUDE = get_host("claude-code")


class ClaudeChildExitError(ClaudeBindingError):
    """An owned CLI exited while its sealed input pipe was still being written."""

    def __init__(self, exit_status: int, stderr_tail: str):
        self.exit_status = exit_status
        self.stderr_tail = stderr_tail
        reason = f"child exited before stdin was accepted (exit status {exit_status})"
        if stderr_tail:
            reason += "; stderr tail: " + stderr_tail
        super().__init__(reason)

# Otto's side of the Claude surface: the parser schema and tool surfaces are Otto's policy, supplied
# to the product-neutral fleet host rather than defined by it. Tool surfaces per role profile. A worker
# leaf reads and writes files only; a manager also runs commands (tests, git, the owner's installed
# client) and edits files. Agent/Task and web tools stay disabled for both, so no provider-native child
# can escape owner custody. MCP is opt-in per turn and only through an owner-supplied McpGrant.
PARSER_SCHEMA = "otto.claude-code-2.1.293.stream-json.v1"
WORKER_TOOLS = WORKER_BUILTIN_TOOLS
MANAGER_TOOLS = ('Bash', 'Edit', 'Glob', 'Grep', 'Read', 'Write')
# The one MCP server a worker sees, and the owner calls behind it. Which role may call which tool is
# ``ROLE_PROFILES[role]['calls']`` in claude_adapter. ``task`` reads the caller's own context over an
# operation already on the owner's allowlist; ``check`` is feedback only (a worker's check never
# counts as acceptance) and ``done`` only submits. Their operations are not on the allowlist yet, so
# the allowlisted port refuses them until the owner puts them there.
TOOL_SERVER = 'otto'
TOOL_ENV_PREFIX = 'OTTO_TOOL_'
TOOL_SPECS = (
    ToolSpec('task', TASK, 'effective-context', description="Read this assignment's task and context."),
    ToolSpec('check', CHECK, 'worker-check',
             description='Run the checks on your work. The result is feedback only; it is never acceptance.'),
    ToolSpec('done', DONE, 'worker-done', args=('summary',),
             description='Submit your work as finished. The owner decides acceptance.'),
)
OWNER_OPERATIONS = ('effective-context',)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def terminate_recorded_process_group(record: Mapping[str, Any], *,
                                    birth_reader: Callable[[int], Any] | None = None) -> bool:
    """Kill a recorded worker group only while its recorded leader birth still matches.

    A PID or PGID can be reused after a worker exits. The durable record is
    therefore authority to signal only when the current leader has the same
    kernel birth identity. False means the group was not safely signalled.
    """
    pid, pgid, birth = record.get('pid'), record.get('pgid'), record.get('birth')
    if (type(pid) is not int or type(pgid) is not int or pid <= 0 or pgid <= 0
            or not isinstance(birth, list) or not birth or any(type(value) is not int for value in birth)):
        return False
    if birth_reader is None:
        from otto.portfolio.execution_host import _process_start_identity
        birth_reader = lambda selected: _process_start_identity(selected)['birth']
    try:
        current_birth = list(birth_reader(pid))
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False
    if current_birth != birth:
        return False
    try:
        if os.getpgid(pid) != pgid:
            return False
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


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


_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+ \(Claude Code\)$")


def qualified_versions(values: Any = None) -> tuple[str, ...]:
    """The exact launcher versions a host has qualified for PARSER_SCHEMA.

    The parser schema stays pinned (VERSION by default). A host that has
    re-run the parser/transport fixtures against a newer CLI may add its
    exact ``--version`` string through its adapter configuration; nothing is
    accepted by prefix, range or PATH discovery, and there is no fallback.
    """
    values = (VERSION,) if values is None else tuple(values)
    if (not values or len(values) > 8 or VERSION not in values
            or any(not isinstance(v, str) or not _VERSION_PATTERN.match(v) for v in values)
            or len(set(values)) != len(values)):
        raise ClaudeBindingError("qualified Claude versions must be exact '<x.y.z> (Claude Code)' strings including "
                                 + VERSION)
    return values


@dataclass(frozen=True)
class LauncherPin:
    locator: str
    realpath: str
    sha256: str
    version: str
    qualified: tuple = (VERSION,)

    @classmethod
    def inspect(cls, launcher: str, *, qualified: Any = None) -> "LauncherPin":
        accepted = qualified_versions(qualified)
        path = Path(launcher)
        if not path.is_absolute():
            raise ClaudeBindingError("absolute trusted launcher required; no PATH fallback")
        real = path.resolve(strict=True)
        before = file_digest(real)
        result = subprocess.run([str(real), "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
        if result.returncode or result.stdout.strip() not in accepted or file_digest(real) != before:
            raise ClaudeBindingError("launcher version unsupported or changed during inspection: observed "
                                     + repr(result.stdout.strip()[:64]) + "; qualified " + ", ".join(accepted))
        return cls(str(path), str(real), before, result.stdout.strip(), accepted)

    def verify(self) -> None:
        if (str(Path(self.locator).resolve(strict=True)) != self.realpath
                or file_digest(Path(self.realpath)) != self.sha256
                or self.version not in qualified_versions(self.qualified)):
            raise ClaudeBindingError("pinned Claude launcher drift/removal; host reconciliation required")


class MacWriteScope:
    """Finite OS fence for Read/Write leafs, with private native state custody.

    The host provisions authentication in state_root. No user credentials are
    copied and no live provider configuration is modified by this adapter.
    """
    identity = "otto.claude-macos-file-write-scope.v1"
    kind = "sandbox-exec"
    flags: tuple = ()

    def __init__(self, workspace: str, state_root: str, *, authentication: str = 'isolated',
                 allow_subprocesses: bool = False, extra_write_roots: Any = (), exec_allow: tuple = ()):
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
        if type(allow_subprocesses) is not bool:
            raise ClaudeBindingError('allow_subprocesses must be explicit')
        self.allow_subprocesses = allow_subprocesses
        extra = []
        for root in tuple(extra_write_roots):
            resolved = Path(root).resolve(strict=True)
            if not resolved.is_dir() or any(part in {'.git', '.agents', '.codex', '.aws', '.claude'} for part in resolved.parts):
                raise ClaudeBindingError('extra write roots must be existing unprotected directories')
            extra.append(str(resolved))
        self.extra_write_roots = tuple(dict.fromkeys(extra))
        execs = []
        for command in tuple(exec_allow):
            if not Path(command).is_absolute():
                raise ClaudeBindingError('exec allowances must be existing absolute file paths')
            resolved = os.path.realpath(command)
            if not os.path.isfile(resolved):
                raise ClaudeBindingError('exec allowances must be existing absolute file paths')
            execs.append(resolved)
        self.exec_allow = tuple(dict.fromkeys(exec_allow_for_commands(execs)))
        # The policy text belongs to the host contract: one fence, one place.
        self.policy = sandbox_policy(self.workspace, self.state_root, allow_subprocesses=allow_subprocesses,
                                     extra_write_roots=self.extra_write_roots,
                                     auth_lock=self.auth_helper['lock'] if self.auth_helper else None,
                                     exec_allow=self.exec_allow)
        self.pin = {"authentication": authentication, "auth_helper": self.auth_helper,
                    "identity": self.identity, "workspace": self.workspace,
                    "state_root": self.state_root, "policy_sha256": hashlib.sha256(self.policy.encode()).hexdigest(),
                    "sandbox_runner": '/usr/bin/sandbox-exec',
                    "sandbox_runner_sha256": file_digest(Path('/usr/bin/sandbox-exec'))}
        if allow_subprocesses or self.extra_write_roots:
            # Leaf pins stay byte-identical; only an extended profile adds keys.
            self.pin.update(subprocesses=allow_subprocesses, extra_write_roots=list(self.extra_write_roots))
        if self.exec_allow:
            # Only a scope that grants its MCP server's binary adds the key; leaf pins stay identical.
            self.pin['exec_allow'] = list(self.exec_allow)
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
        if self.allow_subprocesses:
            # A child process must start, and must inherit the write fence.
            probe += ('\nimport subprocess'
                      '\nif subprocess.run(["/usr/bin/true"]).returncode: sys.exit(10)'
                      '\nescape="/private/tmp/otto-scope-probe-%d" % os.getpid()'
                      '\nif subprocess.run(["/usr/bin/touch", escape], stderr=subprocess.DEVNULL).returncode == 0:'
                      '\n os.unlink(escape); sys.exit(11)')
        result = subprocess.run(self.wrap([str(interpreter), '-c', probe, self.workspace, self.state_root]),
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ClaudeBindingError("OS scope preflight failed: " + result.stderr[:512])
        return {**self.pin, "preflight_interpreter": dict(self.preflight_interpreter),
                "verified": True, "proof": "permitted writes and denied outside-root create"
                + ("; child process started and inherited the write fence" if self.allow_subprocesses else "")}

    def wrap(self, command: list[str], *, initializer: bool = False) -> list[str]:
        return sandbox_wrap(self.policy, self.workspace, command, initializer=initializer)


class ClaudeCliTransport:
    """Sealed stdin and bounded pipe custody for exactly one native turn."""

    def __init__(self, pin: LauncherPin, scope: MacWriteScope, *, model: str, reasoning: str,
                 timeout_seconds: float = 120, process_factory: Callable[..., Any] = subprocess.Popen,
                 authentication: str = 'existing-user', tools: tuple = WORKER_TOOLS,
                 max_turns: int = 8, extra_env: Mapping[str, str] | None = None,
                 mcp: McpGrant | None = None):
        if authentication not in {'existing-user', 'isolated'}:
            raise ClaudeBindingError('unsupported authentication profile')
        self.authentication = authentication
        self.pin, self.scope = pin, scope
        self.model, self.reasoning = text(model, 'model'), text(reasoning, 'reasoning')
        validate_effort(reasoning)
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 1800:
            raise ClaudeBindingError("bounded finite owner timeout required")
        self.timeout_seconds, self.process_factory = timeout_seconds, process_factory
        self.tools = validate_tools(tools, MANAGER_TOOLS, getattr(scope, 'allow_subprocesses', False))
        self.max_turns = validate_max_turns(max_turns)
        extra_env = dict(extra_env or {})
        if any(not isinstance(k, str) or not k.startswith('OTTO_') or not isinstance(v, str) or '\x00' in v
               for k, v in extra_env.items()):
            raise ClaudeBindingError("extra environment is limited to OTTO_* text values")
        self.extra_env = extra_env
        self.mcp = McpGrant() if mcp is None else mcp

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
        env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                   TMPDIR=self.scope.state_root, **getattr(self, 'extra_env', {}))
        if self.mcp.empty:
            # Safe mode also drops every MCP server, so a granted worker runs without it (see the host's
            # confined leaf launch); everything else stays disabled through its flags.
            env['CLAUDE_CODE_SAFE_MODE'] = '1'
        # An agent never inherits heavy-lease markers: the runner knows a nested call by its lease, not by these.
        env = {key: value for key, value in env.items() if not key.startswith('OTTO_HEAVY_')}
        if self.authentication == 'isolated':
            env['CLAUDE_CONFIG_DIR'] = self.scope.state_root
        return env

    def run(self, prompt: str, *, session: str | None = None,
            initializer: bool = False, on_init: Any = None, on_input: Any = None, on_usage: Any = None,
            on_process: Any = None, on_launch: Any = None) -> Mapping[str, Any]:
        proof = self.preflight()  # Before process creation, including initialization.
        try:
            # The host contract owns every launch flag; the proven scope is the fence it wraps them in.
            spec = TurnSpec(executable=self.pin.realpath, workspace=self.scope.workspace, prompt=prompt,
                            model=self.model, reasoning=self.reasoning, profile='workspace-write', session=session,
                            initializer=initializer, mcp=self.mcp,
                            options={'tools': self.tools, 'allowed_tools': MANAGER_TOOLS, 'max_turns': self.max_turns,
                                     'allow_subprocesses': getattr(self.scope, 'allow_subprocesses', False)})
            plan = CLAUDE.launch(spec, fence=self.scope)
            parser = CLAUDE.parser(spec, on_init=on_init, on_input=on_input, on_usage=on_usage)
        except ClaudeBindingError:
            raise
        except HostContractError as exc:
            raise ClaudeBindingError(str(exc)) from exc
        command, data = list(plan.argv), plan.stdin
        env = {**self.environment(), **plan.env}
        latch_path = on_launch() if callable(on_launch) else None
        custody = Custody.launch(list(plan.command()), latch_path=latch_path,
            popen=self.process_factory, cwd=self.scope.workspace,
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = custody.process
        cleanup = None
        disposition = None
        if on_process is not None and not initializer:
            # Host registration of the owned native process (for example the
            # managed caller socket's peer ancestry). Failure stops the turn.
            try:
                cleanup = on_process(process)
                if not callable(cleanup):
                    raise ClaudeBindingError("native process registration must return its cleanup")
            except BaseException:
                custody.terminate()
                process.wait(timeout=5)
                raise
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
                        try:
                            offset += os.write(key.fd, data[offset:offset + 65536])
                        except BrokenPipeError as exc:
                            # The child may have exited before accepting its
                            # sealed request. Keep that launch uncertain, while
                            # preserving the evidence needed for reconciliation.
                            while process.poll() is None:
                                if time.monotonic() >= deadline:
                                    raise ClaudeBindingError(
                                        "owned process timeout; native terminal unproved; no replay") from exc
                                try:
                                    part = os.read(process.stderr.fileno(), 65536)
                                except BlockingIOError:
                                    time.sleep(.01)
                                    continue
                                if not part:
                                    time.sleep(.01)
                                    continue
                                stderr.extend(part)
                                if len(stderr) > MAX_LINE:
                                    del stderr[:-MAX_LINE]
                            code = process.wait(timeout=max(.01, deadline - time.monotonic()))
                            while True:
                                try:
                                    part = os.read(process.stderr.fileno(), 65536)
                                except BlockingIOError:
                                    break
                                if not part:
                                    break
                                stderr.extend(part)
                                if len(stderr) > MAX_LINE:
                                    del stderr[:-MAX_LINE]
                            tail = stderr.decode('utf-8', errors='replace')[-1024:]
                            raise ClaudeChildExitError(code, tail) from exc
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
            turn = parser.finish(code)
            disposition = custody.release()     # sweeps stragglers the CLI left in its tree
            settle_scope = getattr(on_launch, "settle_scope", None)
            if disposition.gone and callable(settle_scope):
                settle_scope(disposition)
            if not disposition.gone:
                raise ClaudeBindingError("owned process cleanup unresolved: " + disposition.reason)
            result = {**dict(turn.native), 'usage': turn.usage, 'usage_capture': turn.usage_capture, 'scope': proof,
                    'command': command, 'exit_status': code, 'stderr': stderr.decode('utf-8', errors='replace')[:4096],
                    'launcher': vars(self.pin), 'parser_schema': PARSER_SCHEMA}
            return result
        finally:
            selector.close()
            if cleanup is not None:
                cleanup()
            if disposition is None:
                # Only this owned process tree; no provider-session deletion.
                if process.poll() is None:
                    cleanup_disposition = custody.terminate()
                    process.wait(timeout=5)
                else:
                    cleanup_disposition = custody.release()
                settle_scope = getattr(on_launch, "settle_scope", None)
                if cleanup_disposition.gone and callable(settle_scope):
                    try:
                        settle_scope(cleanup_disposition)
                    except Exception:
                        pass  # The original unknown turn propagates; restart retains its owner row.
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed: stream.close()
