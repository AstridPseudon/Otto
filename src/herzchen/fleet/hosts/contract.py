"""The one host contract.

A host is an agent CLI (a harness). Adding one is a single ``HostKind`` implementation that says:

* how to launch a turn and resume a session   -> ``build_argv`` / ``build_stdin``
* how to pass the MCP tools and a token       -> ``render_mcp`` (flags); the token rides the environment
* how to fence writes to a workspace          -> ``make_fence``
* how to parse its output into events/usage   -> ``make_parser``
* which models serve normal and xhard         -> ``models`` (a ``ModelPlan`` the caller supplies)

Everything else (``launch`` validation, token delivery, the registry, ``run_turn``) is shared, so labs,
capacity, tools and landing never learn which harness they are driving. Unknown host kinds are refused.
"""
from __future__ import annotations

import abc
import copy
from dataclasses import dataclass, field, replace
import os
import re
import subprocess
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

from ..custody import Custody

OUTCOMES = frozenset({"succeeded", "failed", "unknown"})
EVENT_KINDS = frozenset({"session", "turn", "done", "other"})

_KIND = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")      # no "_": Claude joins server and tool with "__"
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")              # matched with fullmatch: no trailing newline slips in


class HostContractError(ValueError):
    """A host, a request to it, or a grant for it breaks the contract."""


class UnknownHostKind(HostContractError):
    """No host implements this kind. Never answered with another host."""


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise HostContractError(field_name + " must be nonblank text")
    return value


@dataclass(frozen=True)
class ModelBinding:
    model: str
    reasoning: str

    def __post_init__(self) -> None:
        _text(self.model, "model")
        _text(self.reasoning, "reasoning")


@dataclass(frozen=True)
class ModelPlan:
    """The caller's model choice: the binding that serves normal work and the one that serves xhard work."""

    normal: ModelBinding
    xhard: ModelBinding

    def __post_init__(self) -> None:
        if not isinstance(self.normal, ModelBinding) or not isinstance(self.xhard, ModelBinding):
            raise HostContractError("a model plan binds normal and xhard to ModelBinding values")


@dataclass(frozen=True)
class McpServer:
    """One MCP server the owner grants a turn. ``tools`` is the explicit allowlist."""

    name: str
    command: str
    args: tuple = ()
    tools: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.match(self.name):
            raise HostContractError("MCP server name must be letters, digits and '-'")
        if not isinstance(self.command, str) or not os.path.isabs(self.command) or "\x00" in self.command:
            raise HostContractError("MCP server command must be an absolute path")
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "tools", tuple(self.tools))
        if any(not isinstance(a, str) or "\x00" in a for a in self.args):
            raise HostContractError("MCP server args must be text")
        if any(not isinstance(t, str) or not _NAME.match(t) for t in self.tools) or len(set(self.tools)) != len(self.tools):
            raise HostContractError("MCP tool names must be distinct letters, digits and '-'")


@dataclass(frozen=True)
class McpGrant:
    """MCP servers plus the token they authenticate with. The token is environment-only."""

    servers: tuple = ()
    token_env: Optional[str] = None
    token: Optional[str] = field(default=None, repr=False)
    token_env_prefix: Optional[str] = None      # supplied by the caller; ignored when token_env is None

    def __post_init__(self) -> None:
        object.__setattr__(self, "servers", tuple(self.servers))
        if any(not isinstance(s, McpServer) for s in self.servers):
            raise HostContractError("servers must be McpServer values")
        if len({s.name for s in self.servers}) != len(self.servers):
            raise HostContractError("duplicate MCP server name")
        if (self.token_env is None) != (self.token is None):
            raise HostContractError("a token needs its environment variable name, and the reverse")
        if self.token_env is not None:
            bad_prefix = (not isinstance(self.token_env_prefix, str)
                          or not _ENV_NAME.fullmatch(self.token_env_prefix))
            if (bad_prefix or not isinstance(self.token_env, str) or not _ENV_NAME.fullmatch(self.token_env)
                    or not self.token_env.startswith(self.token_env_prefix)
                    or len(self.token_env) <= len(self.token_env_prefix)):
                raise HostContractError("token environment variable must be an uppercase name under the caller-supplied prefix")
            _text(self.token, "token")

    @property
    def empty(self) -> bool:
        return not self.servers


@dataclass(frozen=True)
class TurnSpec:
    """Everything the owner decides for one turn. Host-specific knobs go in ``options`` (validated)."""

    executable: str
    workspace: str
    prompt: str
    model: str
    reasoning: str
    profile: str = "read-only"
    session: Optional[str] = None            # None launches a fresh session; a value resumes exactly it
    initializer: bool = False                # an inert first turn that may not touch the workspace
    writable_roots: tuple = ()
    mcp: McpGrant = field(default_factory=McpGrant)
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("executable", "workspace", "model", "reasoning", "profile"):
            _text(getattr(self, name), name)
        if not isinstance(self.prompt, str) or "\x00" in self.prompt:
            raise HostContractError("prompt must be text")
        if self.session is not None:
            _text(self.session, "session")
        object.__setattr__(self, "writable_roots", tuple(self.writable_roots))
        object.__setattr__(self, "options", dict(self.options))
        if not isinstance(self.mcp, McpGrant):
            raise HostContractError("mcp must be an McpGrant")


@dataclass(frozen=True)
class HostEvent:
    """One normalized observation. ``other`` carries everything the contract does not name."""

    kind: str
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise HostContractError("unknown host event kind %r" % (self.kind,))


@dataclass(frozen=True)
class TurnResult:
    session_id: Optional[str]
    turn_id: Optional[str]
    outcome: str
    events: tuple = ()
    usage: Mapping[str, Any] = field(default_factory=lambda: {"state": "unavailable"})
    usage_capture: Optional[Mapping[str, Any]] = None
    native: Optional[Mapping[str, Any]] = None       # the host's own strict result, when it has one
    exit_status: Optional[int] = None
    error: Optional[str] = None
    plan: Optional["LaunchPlan"] = None

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise HostContractError("unknown turn outcome %r" % (self.outcome,))


class WriteFence(Protocol):
    """How a host keeps a turn's writes inside its workspace.

    Some CLIs enforce the fence themselves (``flags`` land in argv); others rely on an OS wrapper
    (``wrap``). ``pin`` is the retained description of the fence.
    """

    kind: str
    flags: tuple
    pin: Mapping[str, Any]

    def wrap(self, argv: Sequence[str], *, initializer: bool = False) -> list: ...


@dataclass(frozen=True)
class NativeFlagFence:
    """A fence the CLI enforces through its own flags; nothing wraps the command."""

    kind: str
    flags: tuple
    pin: Mapping[str, Any]

    def wrap(self, argv: Sequence[str], *, initializer: bool = False) -> list:
        return list(argv)


class HostStream(Protocol):
    """Incremental parser for one turn's output (one line per ``feed``)."""

    def feed(self, raw: Any) -> Sequence[HostEvent]: ...

    def finish(self, exit_code: Optional[int]) -> TurnResult: ...


@dataclass(frozen=True)
class LaunchPlan:
    argv: tuple                  # the host CLI command, before any OS wrapper
    stdin: bytes
    env: Mapping[str, str]       # additions to the child environment: the MCP token, nothing else
    cwd: str
    fence: Any
    session: Optional[str]
    initializer: bool = False

    def command(self) -> tuple:
        """The exact argv to execute: the CLI command inside its write fence."""
        return tuple(self.fence.wrap(list(self.argv), initializer=self.initializer))


class HostKind(abc.ABC):
    """Implement this once to add an agent harness."""

    kind: str
    profiles: frozenset            # permission profiles this CLI can honestly translate
    option_names: frozenset = frozenset()
    models: Optional[ModelPlan] = None     # supplied by the caller through ``serving``

    # -- what a harness supplies ------------------------------------------------
    @abc.abstractmethod
    def make_fence(self, spec: TurnSpec) -> WriteFence: ...

    @abc.abstractmethod
    def render_mcp(self, grant: McpGrant, spec: TurnSpec) -> tuple:
        """The CLI flags that hand ``grant``'s servers to the harness. Never the token value."""

    @abc.abstractmethod
    def build_argv(self, spec: TurnSpec, fence_flags: tuple, mcp_flags: tuple) -> list: ...

    @abc.abstractmethod
    def build_stdin(self, spec: TurnSpec) -> bytes: ...

    @abc.abstractmethod
    def make_parser(self, spec: TurnSpec, **callbacks: Any) -> HostStream: ...

    # -- what the contract does for every harness ---------------------------------
    def serving(self, plan: ModelPlan) -> "HostKind":
        """A copy of this host that answers normal and xhard with the caller's ``plan``."""
        if not isinstance(plan, ModelPlan):
            raise HostContractError("serving needs a ModelPlan")
        bound = copy.copy(self)
        bound.models = plan
        return bound

    def _plan(self) -> ModelPlan:
        if self.models is None:
            raise HostContractError("no model plan supplied for host %s" % self.kind)
        return self.models

    @property
    def normal(self) -> ModelBinding:
        return self._plan().normal

    @property
    def xhard(self) -> ModelBinding:
        return self._plan().xhard

    def check(self, spec: TurnSpec) -> None:
        if spec.profile not in self.profiles:
            raise HostContractError("%s has no translation for profile %r; supported: %s"
                                    % (self.kind, spec.profile, ", ".join(sorted(self.profiles))))
        unknown = set(spec.options) - set(self.option_names)
        if unknown:
            raise HostContractError("%s does not take option(s): %s" % (self.kind, ", ".join(sorted(unknown))))

    def fence(self, spec: TurnSpec) -> WriteFence:
        self.check(spec)
        return self.make_fence(spec)

    def parser(self, spec: TurnSpec, **callbacks: Any) -> HostStream:
        self.check(spec)
        return self.make_parser(spec, **callbacks)

    def launch(self, spec: TurnSpec, fence: Optional[WriteFence] = None) -> LaunchPlan:
        """Plan one turn. ``fence`` lets an owner supply the already-proven fence it holds."""
        self.check(spec)
        fence = self.make_fence(spec) if fence is None else fence
        mcp_flags = tuple(self.render_mcp(spec.mcp, spec))
        env = {spec.mcp.token_env: spec.mcp.token} if spec.mcp.token_env else {}
        argv = tuple(self.build_argv(spec, tuple(getattr(fence, "flags", ())), mcp_flags))
        if spec.mcp.token and any(spec.mcp.token in part for part in argv):
            raise HostContractError("the MCP token must travel in the environment, never in argv")
        return LaunchPlan(argv, self.build_stdin(spec), env, spec.workspace, fence, spec.session, spec.initializer)


def run_turn(host: HostKind, spec: TurnSpec, *, fence: Optional[WriteFence] = None,
             process_factory: Any = subprocess.Popen, timeout: float = 120.0) -> TurnResult:
    """The whole loop for any harness: launch, feed the stream to the parser, finish.

    A parser error or a timeout never reads as success: the outcome is ``unknown`` and the turn is
    never replayed here.
    """
    plan = host.launch(spec, fence)
    parser = host.make_parser(spec)
    events: list = []
    custody = Custody.launch(list(plan.command()), popen=process_factory, cwd=plan.cwd,
                             env={**os.environ, **plan.env},
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process = custody.process
    try:
        stdout, stderr = process.communicate(plan.stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        custody.terminate()
        if process.poll() is None:
            process.kill()      # our unreaped leader: a direct kill is safe even when the census is blind
        process.communicate()
        return TurnResult(None, None, "unknown", error="host process timed out", plan=plan)
    custody.release()
    code = process.returncode
    try:
        for line in stdout.splitlines():
            events.extend(parser.feed(line))
        result = parser.finish(code)
    except HostContractError as exc:
        return TurnResult(None, None, "unknown", events=tuple(events), exit_status=code, error=str(exc), plan=plan)
    return replace(result, events=tuple(events), exit_status=code, plan=plan,
                   error=result.error or (stderr.decode("utf-8", "replace")[:512] if code else None))


class HostRegistry:
    """Host kinds by name. An unknown kind is refused, never mapped to a default."""

    def __init__(self, *hosts: HostKind) -> None:
        self._hosts: dict = {}
        for host in hosts:
            self.register(host)

    @staticmethod
    def validate(host: Any) -> None:
        if not isinstance(host, HostKind):
            raise HostContractError("a host must implement HostKind")
        if not isinstance(getattr(host, "kind", None), str) or not _KIND.match(host.kind):
            raise HostContractError("host kind must be lowercase letters, digits and '-'")
        profiles = getattr(host, "profiles", None)
        if not isinstance(profiles, frozenset) or not profiles or any(not isinstance(p, str) for p in profiles):
            raise HostContractError(host.kind + " must declare the permission profiles it supports")
        models = getattr(host, "models", None)
        if models is not None and not isinstance(models, ModelPlan):
            raise HostContractError(host.kind + " models must be a ModelPlan or None")

    def register(self, host: HostKind) -> HostKind:
        self.validate(host)
        if host.kind in self._hosts:
            raise HostContractError("host kind %r already has an implementation" % host.kind)
        self._hosts[host.kind] = host
        return host

    def get(self, kind: Any) -> HostKind:
        if isinstance(kind, str) and kind in self._hosts:
            return self._hosts[kind]
        raise UnknownHostKind("unknown host kind %r; known: %s" % (kind, ", ".join(self._hosts) or "none"))

    def kinds(self) -> tuple:
        return tuple(self._hosts)

    def hosts(self) -> tuple:
        return tuple(self._hosts.values())
