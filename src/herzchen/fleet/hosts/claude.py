"""The Claude Code host: stream-json turns inside an OS write fence.

The sole candidate profile exposes Read/Write, disables customizations, and requires an OS file-write
fence (``sandbox-exec``). CLI permission flags alone never qualify it: ``--dangerously-skip-permissions``
is only ever passed inside that fence. Moved here unchanged from ``otto.agents.claude_cli`` (the strict
stream parser, the tool surfaces, the fence policy and the launch flags); the owner-side pinning,
preflight and process custody stay in Otto.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .contract import (HostContractError, HostEvent, HostKind, McpGrant, TurnResult, TurnSpec)

MAX_LINE = 256 * 1024
MAX_STREAM = 2 * 1024 * 1024
# The Claude CLI's own built-in tool names. The caller picks the subset a turn may use (``allowed_tools``);
# Agent/Task and web tools are not in this list, so no provider-native child is ever admitted. MCP is
# opt-in per turn and only through a caller-supplied McpGrant.
BUILTIN_TOOLS = ('Bash', 'Edit', 'Glob', 'Grep', 'Read', 'Write')
# The file tools a worker gets on every host (no Bash: a worker runs no commands of its own).
WORKER_BUILTIN_TOOLS = ('Edit', 'Glob', 'Grep', 'Read', 'Write')
# Tools whose --allowedTools rule is pinned to the workspace. The OS fence confines writes only (reads are
# allowed by default), so a leaf's every tool that reads or lists files carries the path scope itself. A
# profile that runs commands (Bash) keeps its recorded Glob/Grep rules.
LEAF_SCOPED_TOOLS = frozenset({'Read', 'Write', 'Edit', 'Glob', 'Grep'})
COMMAND_SCOPED_TOOLS = frozenset({'Read', 'Write', 'Edit'})
# Live probe (ops/runs/TOOLS, CLI 2.1.301): under --dangerously-skip-permissions the --allowedTools path
# scopes are inert and Read/Grep/Glob read any file the user can; under dontAsk a call outside the scope is
# refused. --safe-mode also drops every MCP server, so a worker that is granted its one server runs without
# it (settings, slash commands and every other MCP config stay off through --setting-sources,
# --disable-slash-commands and --strict-mcp-config).
CONFINED_PERMISSION_MODE = 'dontAsk'


def confined_leaf(spec: Any, tools: Sequence[str]) -> bool:
    """A command-free worker turn that has been granted its MCP server."""
    return not spec.initializer and 'Bash' not in tools and not spec.mcp.empty
EFFORTS = frozenset({'low', 'medium', 'high', 'xhigh', 'max'})
PROTECTED_NAMES = ('.git', '.agents', '.codex', '.aws', '.claude')
STRICT_EMPTY_MCP = ('--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}')


class ClaudeBindingError(HostContractError):
    pass


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ClaudeBindingError(field + " must be nonblank text")
    return value


def validate_tools(tools: Any, allowed: Any, allow_subprocesses: bool) -> tuple:
    tools, allowed = tuple(tools), tuple(allowed)
    if set(allowed) - set(BUILTIN_TOOLS):
        raise ClaudeBindingError("allowed tools must be a subset of the Claude CLI built-in tools")
    if not tools or set(tools) - set(allowed) or len(set(tools)) != len(tools):
        raise ClaudeBindingError("tool surface must be a subset of the allowed tools")
    if 'Bash' in tools and not allow_subprocesses:
        raise ClaudeBindingError("Bash requires a scope that admits fenced child processes")
    return tools


def validate_max_turns(max_turns: Any) -> int:
    if type(max_turns) is not int or not 1 <= max_turns <= 500:
        raise ClaudeBindingError("bounded native turn limit required")
    return max_turns


def validate_effort(reasoning: Any) -> str:
    if reasoning not in EFFORTS:
        raise ClaudeBindingError("unsupported Claude effort; no fallback")
    return reasoning


def mcp_tool_names(grant: McpGrant) -> tuple:
    """The native names of the granted tools (``mcp__<server>__<tool>``)."""
    return tuple("mcp__%s__%s" % (server.name, tool) for server in grant.servers for tool in server.tools)


# -- the OS write fence ------------------------------------------------------------------------------
def sandbox_policy(workspace: str, state_root: str, *, allow_subprocesses: bool = False,
                   extra_write_roots: Sequence[str] = (), auth_lock: Optional[str] = None,
                   exec_allow: Sequence[str] = ()) -> str:
    """A Read/Write leaf may write its workspace and host state root, never its protected directories.

    A manager profile runs commands: its children inherit this same write fence, so only process
    creation is relaxed, never file writes. ``exec_allow`` lets a leaf fork and exec exactly the listed
    absolute binaries (its one MCP server) and nothing else; it has no effect when subprocesses are allowed.
    """
    quote = json.dumps
    exec_allow = tuple(exec_allow)
    for path in exec_allow:
        if not isinstance(path, str) or not os.path.isabs(path) or "\x00" in path:
            raise ClaudeBindingError("exec_allow entries must be absolute paths")
    leaf_exec = bool(exec_allow) and not allow_subprocesses
    if leaf_exec:
        spawn = '(deny process-exec)(allow process-fork)'
    else:
        spawn = '' if allow_subprocesses else '(deny process-fork)(deny process-exec)'
    policy = ('(version 1)(allow default)(deny file-write*)' + spawn
              + ''.join('(allow file-write* (subpath ' + quote(root) + '))'
                        for root in (workspace, state_root, *extra_write_roots))
              + '(allow file-write* (literal "/dev/null"))'
              + ''.join('(deny file-write* (subpath ' + quote(str(Path(workspace) / name)) + '))'
                        for name in PROTECTED_NAMES))
    if leaf_exec:
        policy += ''.join('(allow process-exec (literal ' + quote(path) + '))' for path in exec_allow)
    if auth_lock:
        policy += (('' if allow_subprocesses else
                    '(allow process-fork)(allow process-exec (literal "/usr/bin/security"))')
                   + '(allow file-write-data (literal ' + quote(auth_lock) + '))')
    return policy


def sandbox_wrap(policy: str, workspace: str, command: Sequence[str], *, initializer: bool = False) -> list:
    # Initializer hooks cannot write task files even before native init.
    # No subprocess/tool shell can escape the selected leaf surface.
    policy = policy + '(allow process-exec (literal ' + json.dumps(command[0]) + '))'
    if initializer:
        policy += '(deny file-write* (subpath ' + json.dumps(workspace) + '))'
    return ['/usr/bin/sandbox-exec', '-p', policy, *command]


class SandboxFence:
    """The contract's view of the OS fence: pure policy, no probing (the owner proves it in preflight)."""

    kind = "sandbox-exec"
    flags: tuple = ()

    def __init__(self, workspace: str, state_root: str, *, allow_subprocesses: bool = False,
                 extra_write_roots: Sequence[str] = (), auth_lock: Optional[str] = None,
                 exec_allow: Sequence[str] = ()) -> None:
        if type(allow_subprocesses) is not bool:
            raise ClaudeBindingError('allow_subprocesses must be explicit')
        self.workspace = workspace
        self.policy = sandbox_policy(workspace, state_root, allow_subprocesses=allow_subprocesses,
                                     extra_write_roots=tuple(extra_write_roots), auth_lock=auth_lock,
                                     exec_allow=tuple(exec_allow))
        self.pin = {"kind": self.kind, "workspace": workspace, "state_root": state_root,
                    "subprocesses": allow_subprocesses, "extra_write_roots": list(extra_write_roots),
                    "policy_sha256": hashlib.sha256(self.policy.encode()).hexdigest()}
        if exec_allow:
            # Pins without an exec allowance stay byte-identical; only a granted server adds the key.
            self.pin["exec_allow"] = list(exec_allow)

    def wrap(self, argv: Sequence[str], *, initializer: bool = False) -> list:
        return sandbox_wrap(self.policy, self.workspace, argv, initializer=initializer)


# -- the strict native stream ------------------------------------------------------------------------
class ClaudeStream:
    """Strict selected native schema. Worker text supplies no authority facts."""

    def __init__(self, *, prompt: str, cwd: str, model: str, tools: tuple[str, ...],
                 session: str | None = None, on_init: Callable[..., Any] | None = None,
                 on_input: Callable[..., Any] | None = None,
                 on_usage: Callable[..., Any] | None = None, phase: str = "work",
                 mcp_servers: tuple = (), mcp_tools: tuple = (), permission_mode: str = 'bypassPermissions'):
        self.prompt, self.cwd, self.model, self.tools = prompt, cwd, model, tools
        self.permission_mode = permission_mode
        self.session, self.on_init, self.on_input = session, on_init, on_input
        self.mcp_servers, self.mcp_tools = tuple(mcp_servers), tuple(mcp_tools)
        from herzchen.usage.capture import UsageStream
        self.usage_stream = UsageStream("claude-code", phase=phase, session_id=session,
            requested_model=model, on_usage=on_usage)
        self.init = self.input = self.result = None
        self.refs: dict[str, Any] = {}
        self.tool_uses: dict[str, Any] = {}
        self.tool_results: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.bytes = 0

    def _servers_match(self, reported: Any) -> bool:
        if not isinstance(reported, list):
            return False
        names = [item.get('name') if isinstance(item, dict) else item for item in reported]
        return sorted(names, key=str) == sorted(self.mcp_servers)

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
                    or event.get('model') != self.model or event.get('permissionMode') != self.permission_mode
                    or not isinstance(event.get('tools'), list)
                    or sorted(event['tools']) != sorted((*self.tools, *self.mcp_tools))
                    or not self._servers_match(event.get('mcp_servers')) or event.get('plugins', []) != []
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
                    if (ident in self.tool_uses or block.get('name') not in (*self.tools, *self.mcp_tools)
                            or not isinstance(block.get('input'), dict)):
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


class ClaudeHostStream:
    """The contract's ``HostStream`` over the strict native parser."""

    def __init__(self, stream: ClaudeStream) -> None:
        self.stream = stream

    def feed(self, raw: bytes) -> tuple:
        before = len(self.stream.events)
        self.stream.feed(raw)
        out = []
        for ref in self.stream.events[before:]:
            kind = {"system": "session", "result": "done"}.get(ref["event_type"], "other")
            if ref["event_type"] == "user" and self.stream.input is not None \
                    and ref["item_id"] == self.stream.input.get("uuid"):
                kind = "turn"
            out.append(HostEvent(kind, ref["session_id"], ref["turn_id"], ref))
        return tuple(out)

    def finish(self, exit_code: int) -> TurnResult:
        native = self.stream.finish(exit_code)
        return TurnResult(native["session_id"], native["turn_id"], native["outcome"], usage=self.stream.usage(),
                          usage_capture=self.stream.usage_stream.snapshot(), native=native, exit_status=exit_code)


class ClaudeHost(HostKind):
    kind = "claude-code"
    profiles = frozenset({"workspace-write"})
    option_names = frozenset({"tools", "allowed_tools", "max_turns", "state_root", "allow_subprocesses",
                              "extra_write_roots", "auth_lock", "exec_allow"})

    @staticmethod
    def tools_for(spec: TurnSpec) -> tuple:
        """An initializer is inert: no tools, no MCP. Otherwise the caller must name both surfaces."""
        if spec.initializer:
            return ()
        if "tools" not in spec.options or "allowed_tools" not in spec.options:
            raise HostContractError("claude-code needs the caller to pass tools and allowed_tools")
        return validate_tools(spec.options["tools"], spec.options["allowed_tools"],
                              bool(spec.options.get("allow_subprocesses", False)))

    def make_fence(self, spec: TurnSpec) -> SandboxFence:
        if "state_root" not in spec.options:
            raise HostContractError("claude-code needs the host-owned state_root to build its write fence")
        return SandboxFence(spec.workspace, spec.options["state_root"],
                            allow_subprocesses=spec.options.get("allow_subprocesses", False),
                            extra_write_roots=tuple(spec.options.get("extra_write_roots", ())),
                            auth_lock=spec.options.get("auth_lock"),
                            exec_allow=tuple(spec.options.get("exec_allow", ())))

    def render_mcp(self, grant: McpGrant, spec: TurnSpec) -> tuple:
        if grant.empty or spec.initializer:
            return STRICT_EMPTY_MCP
        servers = {}
        for server in grant.servers:
            if not server.tools:
                raise HostContractError("claude-code requires an explicit tool allowlist for MCP server %r" % server.name)
            entry: dict = {"command": server.command, "args": list(server.args)}
            if grant.token_env:
                entry["env"] = {grant.token_env: "${%s}" % grant.token_env}    # expanded from the environment
            servers[server.name] = entry
        return ('--strict-mcp-config', '--mcp-config',
                json.dumps({"mcpServers": servers}, separators=(",", ":"), sort_keys=True))

    def build_argv(self, spec: TurnSpec, fence_flags: tuple, mcp_flags: tuple) -> list:
        reasoning = validate_effort(spec.reasoning)
        tools = self.tools_for(spec)
        max_turns = validate_max_turns(spec.options.get("max_turns", 8))
        confined = confined_leaf(spec, tools)
        command = [spec.executable, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
                   '--verbose', '--replay-user-messages', *(() if confined else ('--safe-mode',)),
                   '--setting-sources', '', *mcp_flags, '--disable-slash-commands',
                   *(('--permission-mode', CONFINED_PERMISSION_MODE) if confined
                     else ('--dangerously-skip-permissions',)), '--tools', ','.join(tools),
                   '--model', spec.model, '--effort', reasoning,
                   '--max-turns', '1' if spec.initializer else str(max_turns)]
        if not spec.initializer:
            scoped = COMMAND_SCOPED_TOOLS if 'Bash' in tools else LEAF_SCOPED_TOOLS
            # A rule's "/path" is project-relative; only "//path" names an absolute directory (probed).
            root = ('/' if confined else '') + spec.workspace
            command.extend(['--allowedTools', *(name + '(' + root + '/**)'
                                                if name in scoped else name for name in tools),
                            *mcp_tool_names(spec.mcp)])
        if spec.session is not None:
            command.extend(['--resume', text(spec.session, 'exact native session')])
        return command

    def build_stdin(self, spec: TurnSpec) -> bytes:
        frame = {'type': 'user', 'session_id': spec.session or '', 'message': {'role': 'user',
                 'content': [{'type': 'text', 'text': text(spec.prompt, 'admitted input')}]}}
        data = (json.dumps(frame, ensure_ascii=False) + '\n').encode()
        if len(data) > MAX_LINE:
            raise ClaudeBindingError("admitted input exceeds profile bound")
        return data

    def make_parser(self, spec: TurnSpec, **callbacks: Any) -> ClaudeHostStream:
        grant = (McpGrant() if spec.initializer else spec.mcp)
        return ClaudeHostStream(ClaudeStream(
            prompt=spec.prompt, cwd=spec.workspace, model=spec.model, tools=self.tools_for(spec),
            session=spec.session, on_init=callbacks.get("on_init"), on_input=callbacks.get("on_input"),
            on_usage=callbacks.get("on_usage"), phase="initializer" if spec.initializer else "work",
            mcp_servers=tuple(s.name for s in grant.servers), mcp_tools=mcp_tool_names(grant),
            permission_mode=(CONFINED_PERMISSION_MODE if confined_leaf(spec, self.tools_for(spec))
                             else 'bypassPermissions')))
