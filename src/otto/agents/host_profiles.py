"""Host-aware default model bindings for the seven Megado responsibility slots.

A profile is a *default*, never authority: explicit overrides and adopted
project/role configuration still win (see ``TrustedAdapterSelection``). The
models a host serves are Otto's policy and live here, in ``PROFILES``; the
product-neutral fleet in ``herzchen.fleet.hosts`` only validates the host kind
and carries the ``ModelPlan`` this module supplies. A new agent CLI is one
``HostKind`` implementation plus one entry here; no other module lists a model
name. A host kind nobody implements is refused, never given Codex.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Mapping, Optional

from herzchen.fleet.hosts import REGISTRY, ModelBinding, ModelPlan, UnknownHostKind  # noqa: F401  (UnknownHostKind re-exported)

SLOTS = ("coordinator", "worker_normal", "worker_xhard", "reviewer_normal", "reviewer_xhard", "oracle", "final_reviewer")

# The unchanged Codex edition default, used only when nothing at all names a profile or a host
# (pinned by test_host_neutral_defaults). Any host that IS named must be a known one.
_UNSELECTED_HOST_KIND = "codex"

# Unchanged edition defaults (src/otto/packs/megado/skill/templates/run.json).
# Claude mirrors the same seven slots with its own model family.
PROFILES: Mapping[str, Mapping[str, Any]] = {
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


def profile_for_host(host_kind: Optional[str]) -> str:
    """Map a host kind (``codex``, ``claude-code``) to its default profile; unknown kinds are refused.

    The fleet registry must implement the kind first (it raises ``UnknownHostKind`` for anything
    it does not, including ``None`` and ``""``); only then is Otto's own table consulted.
    """
    REGISTRY.get(host_kind)
    for name, entry in PROFILES.items():
        if host_kind in entry["host_kinds"]:
            return name
    raise UnknownHostKind(f"no model profile for host kind {host_kind!r}")


def model_plan(name: str) -> ModelPlan:
    """The fleet ``ModelPlan`` for a profile: the worker_normal and worker_xhard bindings."""
    roles = PROFILES[name]["roles"]
    return ModelPlan(ModelBinding(**roles["worker_normal"]), ModelBinding(**roles["worker_xhard"]))


def serving_host(host_kind: Optional[str]) -> Any:
    """The fleet host for a kind, serving this profile's model plan (a copy; the registry is untouched)."""
    return REGISTRY.get(host_kind).serving(model_plan(profile_for_host(host_kind)))


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
