"""Host-aware default model bindings for the seven Megado responsibility slots.

A profile is a *default*, never authority: explicit overrides and adopted
project/role configuration still win (see ``TrustedAdapterSelection``). The
``codex`` profile reproduces the previously hardcoded edition defaults, so a
caller that selects nothing keeps the exact Codex behaviour. A new agent CLI
adds one profile here plus its adapter registration; nothing else needs a
model name.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Mapping, Optional

SLOTS = ("coordinator", "worker_normal", "worker_xhard", "reviewer_normal",
         "reviewer_xhard", "oracle", "final_reviewer")

PROFILES: Mapping[str, Mapping[str, Any]] = {
    # Unchanged edition defaults (policy-staging/megado/skill/templates/run.json).
    "codex": {
        "adapter": "codex",
        "host_kinds": ("codex",),
        "roles": {
            "coordinator": {"model": "gpt-5.6-luna", "reasoning": "medium"},
            "worker_normal": {"model": "gpt-5.6-luna", "reasoning": "high"},
            "worker_xhard": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "reviewer_normal": {"model": "gpt-5.6-luna", "reasoning": "xhigh"},
            "reviewer_xhard": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "oracle": {"model": "gpt-6-astra", "reasoning": "high"},
            "final_reviewer": {"model": "gpt-6-astra", "reasoning": "high"},
        },
    },
    # Claude Code host: economical Haiku, Sonnet for XHARD/independent
    # review, Opus for consequential judgment. Efforts are the values the
    # Claude CLI accepts (low, medium, high, xhigh, max).
    "claude": {
        "adapter": "claude-code",
        "host_kinds": ("claude-code",),
        "roles": {
            "coordinator": {"model": "claude-haiku-5-5", "reasoning": "medium"},
            "worker_normal": {"model": "claude-haiku-5-5", "reasoning": "high"},
            "worker_xhard": {"model": "claude-sonnet-5-5", "reasoning": "high"},
            "reviewer_normal": {"model": "claude-sonnet-5-5", "reasoning": "high"},
            "reviewer_xhard": {"model": "claude-opus-5-5", "reasoning": "high"},
            "oracle": {"model": "claude-opus-5-5", "reasoning": "high"},
            "final_reviewer": {"model": "claude-opus-5-5", "reasoning": "high"},
        },
    },
}

DEFAULT_PROFILE = "codex"


def profile_for_host(host_kind: Optional[str]) -> str:
    """Map a host kind (``codex``, ``claude-code``) to its default profile."""
    for name, profile in PROFILES.items():
        if host_kind in profile["host_kinds"]:
            return name
    return DEFAULT_PROFILE


def resolve_profile_name(explicit: Optional[str] = None, *, host_kind: Optional[str] = None,
                         environ: Optional[Mapping[str, str]] = None) -> str:
    """explicit argument -> OTTO_MODEL_PROFILE -> host kind -> codex (legacy)."""
    env = os.environ if environ is None else environ
    for candidate in (explicit, env.get("OTTO_MODEL_PROFILE")):
        if candidate:
            if candidate not in PROFILES:
                raise ValueError("unknown model profile %r; known: %s" % (candidate, ", ".join(sorted(PROFILES))))
            return candidate
    kind = host_kind or env.get("OTTO_HOST_KIND")
    return profile_for_host(kind) if kind else DEFAULT_PROFILE


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
