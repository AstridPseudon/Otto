"""The Codex host: ``codex exec --json`` turns, fenced by Codex's own sandbox.

This is the single place the Codex launch argv is built. ``herzchen.adapters.host.CodexCliBinding`` (the
one Codex binding) asks this host for its command; nothing else in the tree knows Codex's flags.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from herzchen.usage.capture import UsageStream

from .contract import HostContractError, HostEvent, HostKind, McpGrant, NativeFlagFence, TurnResult, TurnSpec

SANDBOX_PROFILES = frozenset({"read-only", "workspace-write"})
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def native_caller_permission_overrides(worktree: str, writable_roots: tuple[str, ...], socket_path: str,
                                       profile: str) -> list[str]:
    """Trusted host-selected workspace profile with a managed one-socket grant.

    ``profile`` is the caller's permission profile name; it is written into every key it names.
    The network proxy feature is a BOOLEAN. Merely adding its nested fields
    or enabling direct network does not constrain traffic. No legacy sandbox
    flag may accompany this profile: it would override default_permissions.
    """
    if not isinstance(profile, str) or not _PROFILE_NAME.match(profile):
        raise ValueError("a native caller permission profile name is required")
    if (not isinstance(socket_path, str) or not os.path.isabs(socket_path)
            or ".." in Path(socket_path).parts or "\x00" in socket_path
            or len(os.fsencode(socket_path)) > 103):
        raise ValueError("one absolute bounded Unix socket address required")
    values = [f'default_permissions="{profile}"', 'features.network_proxy=true',
              f'permissions.{profile}.extends=":workspace"',
              f'permissions.{profile}.network.enabled=true',
              f'permissions.{profile}.network.mode="limited"',
              f'permissions.{profile}.network.domains={{}}',
              f'permissions.{profile}.network.unix_sockets={{' + json.dumps(socket_path) + '="allow"}']
    roots = dict.fromkeys((os.path.realpath(worktree), *writable_roots))
    values.append(f'permissions.{profile}.workspace_roots={{' +
                  ','.join(json.dumps(root) + '=true' for root in roots) + '}')
    return values


class CodexStream:
    """Line parser for ``codex exec --json``. Identity comes only from the host's own record headers.

    Last record wins, exactly as the binding has always read its stdout.
    """

    def __init__(self, *, model: Optional[str] = None) -> None:
        self.session_id: Optional[str] = None
        self.turn_id: Optional[str] = None
        self.turn_started = False
        self.turn_completed = False
        self.usage: Optional[Mapping[str, Any]] = None
        self.model = model
        self.usage_stream = UsageStream("codex-host")

    def feed(self, raw: Any) -> tuple:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        self.usage_stream.feed(line)
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            return (HostEvent("other", self.session_id, data={"line": line.rstrip("\n")[:512]}),)
        if not isinstance(event, Mapping):
            return (HostEvent("other", self.session_id, data={"line": line.rstrip("\n")[:512]}),)
        kind = event.get("type")
        if kind == "thread.started":
            self.session_id = event.get("thread_id")
            return (HostEvent("session", self.session_id),)
        if kind == "turn.started":
            self.turn_started = True
            return (HostEvent("turn", self.session_id, event.get("turn_id")),)
        if kind == "turn.completed":
            self.turn_id = event.get("turn_id")
            self.turn_completed = True
            self.usage = event["usage"] if isinstance(event.get("usage"), Mapping) else None
            return (HostEvent("done", self.session_id, self.turn_id, dict(self.usage or {})),)
        return (HostEvent("other", self.session_id, event.get("turn_id"), {"type": kind}),)

    def finish(self, exit_code: Optional[int]) -> TurnResult:
        if exit_code == 0 and self.session_id:
            outcome = "succeeded"
        elif exit_code is None or exit_code <= 0:
            outcome = "unknown"     # a negative code is a signal: interrupted, never a failure
        else:
            outcome = "failed"
        usage = ({"state": "observed", "metrics": dict(self.usage)} if self.usage
                 else {"state": "unavailable", "reason": "turn.completed carried no usage"})
        return TurnResult(self.session_id, self.turn_id, outcome, usage=usage,
                          usage_capture=self.usage_stream.snapshot(), exit_status=exit_code)


class CodexHost(HostKind):
    kind = "codex"
    profiles = SANDBOX_PROFILES
    option_names = frozenset({"receipt_path", "native_caller_socket", "native_caller_profile"})

    def make_fence(self, spec: TurnSpec) -> NativeFlagFence:
        # Codex 0.150.1 exposes --sandbox on exec, not exec resume. Common restrictions precede the
        # subcommand; config/rules and approvals must not silently broaden them. Requested argv is not
        # observed evidence.
        socket = spec.options.get("native_caller_socket")
        profile_name = spec.options.get("native_caller_profile")
        if socket is not None:
            if spec.session is None or spec.profile != "workspace-write":
                raise HostContractError("a socket grant is only for an owner-authorized workspace-write resume")
            if profile_name is None:
                raise HostContractError("a socket grant needs the caller's permission profile name")
            flags = tuple(flag for value in native_caller_permission_overrides(
                spec.workspace, spec.writable_roots, socket, profile_name) for flag in ("-c", value))
        else:
            flags = ("-s", spec.profile)
            if spec.profile == "workspace-write":
                flags += tuple(flag for root in spec.writable_roots for flag in ("--add-dir", root))
        return NativeFlagFence("codex-sandbox", flags,
                               {"profile": spec.profile, "workspace": spec.workspace,
                                "roots": [spec.workspace, *spec.writable_roots],
                                "socket": socket, "native_caller_profile": profile_name})

    def render_mcp(self, grant: McpGrant, spec: TurnSpec) -> tuple:
        flags: list = []
        for server in grant.servers:
            prefix = "mcp_servers.%s." % server.name
            flags += ["-c", prefix + "command=" + json.dumps(server.command)]
            if server.args:
                flags += ["-c", prefix + "args=" + json.dumps(list(server.args))]
            if server.tools:
                flags += ["-c", prefix + "enabled_tools=" + json.dumps(list(server.tools))]
            if grant.token_env:
                flags += ["-c", prefix + "env_vars=" + json.dumps([grant.token_env])]   # forwarded by name
        return tuple(flags)

    def build_argv(self, spec: TurnSpec, fence_flags: tuple, mcp_flags: tuple) -> list:
        argv = [spec.executable, "exec", "-C", spec.workspace, "-m", spec.model,
                "-c", f"model_reasoning_effort={spec.reasoning}",
                "-c", 'approval_policy="never"',
                "--ignore-user-config", "--ignore-rules", "--json", *mcp_flags, *fence_flags]
        if spec.session is not None:
            argv.extend(["resume", spec.session])
        if spec.options.get("receipt_path"):
            argv.extend(["-o", spec.options["receipt_path"]])
        argv.append("-")
        return argv

    def build_stdin(self, spec: TurnSpec) -> bytes:
        return spec.prompt.encode("utf-8")

    def make_parser(self, spec: TurnSpec, **callbacks: Any) -> CodexStream:
        return CodexStream(model=spec.model)


# -- the usage-bearing normalizer (moved unchanged from the retired otto.agents.codex_cli) --------------
def _json_copy(value: Any, field: str = "value") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise HostContractError(f"{field} must contain finite JSON") from exc


def _host_event(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only host-owned JSONL evidence, never arbitrary worker content."""

    allowed = ("type", "event_id", "thread_id", "turn_id", "model", "model_name", "reasoning_effort", "reasoning", "usage", "status")
    result = {key: _json_copy(item[key], f"host_event.{key}") for key in allowed if key in item}
    if isinstance(result.get("usage"), Mapping):
        result["usage"] = _json_copy(result["usage"], "host_event.usage")
    return result


def _worker_text(item: Mapping[str, Any]) -> Optional[str]:
    if item.get("type") != "item.completed":
        return None
    content = item.get("item")
    if not isinstance(content, Mapping) or content.get("type") not in {"agent_message", "message"}:
        return None
    text = content.get("text")
    if isinstance(text, str):
        return text
    return None


def normalize_codex_jsonl(
    lines: Iterable[str],
    *,
    on_thread_started: Optional[Callable[[str], None]] = None,
    on_usage: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    adapter_id: str = "codex-direct",
    turn_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Normalize native JSONL while separating host evidence and worker text."""

    usage_stream = UsageStream(adapter_id, on_usage=on_usage, turn_resolver=turn_resolver)
    host_events: list[dict[str, Any]] = []
    worker_content: list[str] = []
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    observed_model: Optional[str] = None
    observed_reasoning: Optional[str] = None
    usage: Optional[Mapping[str, Any]] = None
    turn_completed = False
    invalid_lines = 0
    for raw in lines:
        completion_observation = usage_stream.feed(raw)
        try:
            item = json.loads(raw)
        except (TypeError, ValueError):
            invalid_lines += 1
            continue
        if not isinstance(item, Mapping):
            invalid_lines += 1
            continue
        event_type = item.get("type")
        if event_type == "thread.started":
            candidate = item.get("thread_id") or item.get("session_id")
            if isinstance(candidate, str) and candidate.strip() and thread_id is None:
                thread_id = candidate
                if on_thread_started is not None:
                    on_thread_started(thread_id)
            if isinstance(item.get("model"), str):
                observed_model = observed_model or item["model"]
            if isinstance(item.get("reasoning_effort"), str):
                observed_reasoning = observed_reasoning or item["reasoning_effort"]
            host_events.append(_host_event(item))
            continue
        if event_type == "turn.completed":
            turn_completed = True
            latest = completion_observation or {}
            turn_id = item.get("turn_id") or (latest.get("identity") or {}).get("turn_id")
            usage = _json_copy(item["usage"], "turn_completed.usage") if isinstance(item.get("usage"), Mapping) else None
            if isinstance(item.get("model"), str):
                observed_model = observed_model or item["model"]
            if isinstance(item.get("reasoning_effort"), str):
                observed_reasoning = observed_reasoning or item["reasoning_effort"]
            host_events.append(_host_event(item))
            continue
        text = _worker_text(item)
        if text is not None:
            worker_content.append(text)
    return {
        "host_evidence": {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "thread_started": thread_id is not None,
            "turn_completed": turn_completed,
            "observed_model": observed_model,
            "observed_reasoning": observed_reasoning,
            "usage": usage,
            "events": host_events,
            "invalid_lines": invalid_lines,
        },
        "usage_capture": usage_stream.snapshot(),
        "worker_content": worker_content,
    }
