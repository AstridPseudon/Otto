"""Host-aware default model bindings for the seven Megado responsibility slots.

A profile is a *default*, never authority: explicit overrides and adopted
project/role configuration still win (see ``TrustedAdapterSelection``). The
models a host serves are declared once, by the host itself, in
``herzchen.fleet.hosts`` (a ``HostKind``'s ``slots``); this module only projects
them. A new agent CLI is one ``HostKind`` implementation; nothing here lists a
model name. A host kind nobody implements is refused, never given Codex.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Mapping, Optional

from herzchen.fleet.hosts import REGISTRY, SLOTS, UnknownHostKind  # noqa: F401  (UnknownHostKind re-exported)

# The unchanged Codex edition default, used only when nothing at all names a profile or a host
# (pinned by test_host_neutral_defaults). Any host that IS named must be a known one.
_UNSELECTED_HOST_KIND = "codex"


def _project(host: Any) -> dict[str, Any]:
    return {"adapter": host.adapter_id, "host_kinds": (host.kind,),
            "roles": {slot: {"model": b.model, "reasoning": b.reasoning} for slot, b in host.slots.items()}}


PROFILES: Mapping[str, Mapping[str, Any]] = {host.profile_name: _project(host) for host in REGISTRY.hosts()}


def profile_for_host(host_kind: Optional[str]) -> str:
    """Map a host kind (``codex``, ``claude-code``) to its default profile; unknown kinds are refused."""
    return REGISTRY.get(host_kind).profile_name


def resolve_profile_name(explicit: Optional[str] = None, *, host_kind: Optional[str] = None,
                         environ: Optional[Mapping[str, str]] = None) -> str:
    """explicit argument -> OTTO_MODEL_PROFILE -> host kind (must be known) -> the unchanged Codex default."""
    env = os.environ if environ is None else environ
    for candidate in (explicit, env.get("OTTO_MODEL_PROFILE")):
        if candidate:
            if candidate not in PROFILES:
                raise ValueError("unknown model profile %r; known: %s" % (candidate, ", ".join(sorted(PROFILES))))
            return candidate
    kind = host_kind or env.get("OTTO_HOST_KIND")
    return profile_for_host(kind or _UNSELECTED_HOST_KIND)


def profile(name: str) -> dict[str, Any]:
    if name not in PROFILES:
        raise ValueError("unknown model profile %r" % (name,))
    value = copy.deepcopy(dict(PROFILES[name]))
    value["host_kinds"] = list(value["host_kinds"])
    value["name"] = name
    return value


def slot_binding(slot: str, name: Optional[str] = None, **options: Any) -> dict[str, str]:
    if slot not in SLOTS:
        raise ValueError("unknown responsibility slot %r" % (slot,))
    chosen = resolve_profile_name(name, **options)
    binding = dict(PROFILES[chosen]["roles"][slot])
    binding["adapter"] = PROFILES[chosen]["adapter"]
    return binding


def run_template(name: str, *, mode: str = "planning_only") -> dict[str, Any]:
    """The Megado run template with the selected profile's role bindings."""
    chosen = profile(name)
    return {"mode": mode, "model_profile": name,
            "roles": {slot: dict(chosen["roles"][slot]) for slot in SLOTS}}
