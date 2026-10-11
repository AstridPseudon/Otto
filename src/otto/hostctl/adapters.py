"""Host-owned adapter registry: which agent CLIs this host may launch, and how.

Settings name adapters, models and efforts; they never select executables or
verifiers at request time. Composition pins the launcher realpath, digest and
version before any role can be admitted. Adding a CLI = one entry here plus
its adapter module and conformance tests (see docs/host-onboarding.md).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional


class AdapterUnavailable(RuntimeError):
    pass


def claude_settings(config: Mapping[str, Any]) -> Mapping[str, Any]:
    settings = (config.get("adapters", {}).get("claude-code")
                or ((config.get("hosts") or {}).get("claude-code") or {}).get("adapters", {}).get("claude-code"))
    if not isinstance(settings, Mapping):
        raise AdapterUnavailable("this host declares no claude-code adapter")
    return settings


def launcher_check(config: Mapping[str, Any]) -> dict[str, Any]:
    """Inspect the pinned Claude launcher (runs `claude --version` only)."""
    from otto.agents.claude_cli import ClaudeBindingError, LauncherPin
    settings = claude_settings(config)
    try:
        pin = LauncherPin.inspect(settings["launcher"], qualified=settings.get("qualified_versions"))
        return {"ok": True, "pin": dict(vars(pin)), "provider_called": False}
    except (ClaudeBindingError, OSError) as exc:
        return {"ok": False, "error": str(exc), "provider_called": False,
                "next_action": "qualify the observed exact version for the parser schema (ottoctl host qualify-launcher) "
                               "or install the pinned version"}


def native_state_root(config: Mapping[str, Any]) -> Path:
    root = Path(config["home"]) / "state" / "claude-native"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def compose_claude(config: Mapping[str, Any], *, worktree: str, model: str, reasoning: str,
                   roles: tuple = ("worker", "manager"), owner: str = "otto-host",
                   native_caller_socket: Optional[str] = None, native_process_observer: Any = None,
                   manager_write_roots: tuple = (), manager_env: Optional[Mapping[str, str]] = None) -> Any:
    """Compose the declared Claude Code adapter with real pins (no launch)."""
    from otto.agents.claude_adapter import ClaudeWorkerAdapter
    from otto.agents.claude_cli import LauncherPin
    settings = claude_settings(config)
    declared = tuple(settings.get("roles", ("worker",)))
    if set(roles) - set(declared):
        raise AdapterUnavailable("host declares claude-code roles " + ", ".join(declared))
    if model not in settings.get("models", ()) or reasoning not in settings.get("efforts", ()):
        raise AdapterUnavailable("model/effort not qualified for claude-code on this host: " + model + "/" + reasoning)
    pin = LauncherPin.inspect(settings["launcher"], qualified=settings.get("qualified_versions"))
    return ClaudeWorkerAdapter(owner=owner, source=worktree, worktree=worktree, launcher_pin=pin,
        state_root=str(native_state_root(config)), requested_model=model, requested_reasoning=reasoning,
        roles=roles, authentication=settings.get("authentication", "existing-user"),
        native_caller_socket=native_caller_socket, native_process_observer=native_process_observer,
        manager_write_roots=tuple(manager_write_roots), manager_env=manager_env)


def adapter_selection(config: Mapping[str, Any], *, worktree: Optional[str] = None) -> Any:
    """The finite TrustedAdapterSelection this host offers to run-worker."""
    from otto.agents.claude_adapter import IDENTITY
    from otto.agents.claude_cli import PARSER_SCHEMA
    from otto.agents.trusted_selection import TrustedAdapter, TrustedAdapterSelection
    settings = claude_settings(config)

    def compose(*, model: str, reasoning: str, **options: Any) -> Any:
        raise AdapterUnavailable("launch composition requires the running owner service (`ottoctl service run`)")

    return TrustedAdapterSelection({"claude-code": TrustedAdapter(
        IDENTITY, compose, frozenset(settings.get("models", ())), frozenset(settings.get("profiles", ())),
        {"launcher": settings.get("launcher"), "qualified_versions": list(settings.get("qualified_versions") or ()),
         "parser_schema": PARSER_SCHEMA, "roles": list(settings.get("roles", ()))},
        frozenset(settings.get("efforts", ())))})


class UnavailableAdapter:
    """Stands in for a declared adapter that cannot be composed right now.

    Pure reads (operating-setup read, readiness) still run; every admission
    path reports the composition failure as a blocker instead of a crash.
    """
    owner_bound = True
    require_host_context = True

    def __init__(self, identity: str, reason: str) -> None:
        self.adapter_identity, self.reason = identity, reason

    def validate_owner_host_composition(self, *, role: str, profile: str) -> None:
        raise AdapterUnavailable(self.reason)

    def bind_owner_authorization(self, *args: Any, **kwargs: Any) -> Any:
        raise AdapterUnavailable(self.reason)
