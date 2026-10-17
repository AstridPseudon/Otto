"""Otto's selected, versioned model and host defaults.

The pack supplies defaults only. An adopted project role configuration keeps
its own model binding, and the host adapter still qualifies that binding at
execution. The neutral Herzchen fleet carries a plan without choosing one.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from herzchen.fleet.hosts import REGISTRY, ModelBinding, ModelPlan, UnknownHostKind  # noqa: F401

SLOTS = ("coordinator", "worker_normal", "worker_xhard", "reviewer_normal", "reviewer_xhard", "oracle", "final_reviewer")


class ProfileSelectionError(ValueError):
    """A user-selected profile cannot serve this host, with a recovery step."""

    next_action = ("Choose a model profile qualified for this host (or remove the explicit profile override), "
                   "then retry the command.")


def load_profile_pack() -> dict[str, Any]:
    """Read exact managed profile and host resources, retaining their source pin."""
    from herzchen.packs.authoring import read_managed_pack
    from otto.hostctl.owner import _managed_source_state_path

    source_root = Path(__file__).resolve().parents[2]
    pack = read_managed_pack("otto-profiles", project_root=source_root.parent,
                             native_pack_root=source_root / "otto" / "packs",
                             source_state_path=_managed_source_state_path())
    resources = {item.path: item for item in pack.resources}
    try:
        profiles = json.loads(resources["profiles.json"].content)
        hosts = json.loads(resources["hosts.json"].content)
    except (KeyError, UnicodeError, ValueError) as exc:
        raise ValueError("Otto profile pack lacks valid profile/host resources") from exc
    if (not isinstance(profiles, dict) or profiles.get("schema") != "otto.model-profiles.v1"
            or not isinstance(hosts, dict) or hosts.get("schema") != "otto.host-definitions.v1"
            or not isinstance(profiles.get("profiles"), dict) or not isinstance(hosts.get("hosts"), dict)):
        raise ValueError("Otto profile pack has an unsupported schema")
    names = profiles["profiles"]
    if profiles.get("default_profile") not in names:
        raise ValueError("Otto profile pack lacks its default profile")
    for name, value in names.items():
        if (not isinstance(name, str) or not isinstance(value, dict)
                or set(value.get("roles", {})) != set(SLOTS)
                or not isinstance(value.get("host_kinds"), list)
                or any(not isinstance(binding, dict)
                       or any(not isinstance(binding.get(key), str) or not binding[key]
                              for key in ("model", "reasoning"))
                       for binding in value["roles"].values())):
            raise ValueError("Otto profile pack has an invalid seven-slot profile")
    for kind, value in hosts["hosts"].items():
        REGISTRY.get(kind)
        selected = names.get(value.get("model_profile")) if isinstance(value, dict) else None
        if (not isinstance(selected, dict) or selected.get("adapter") != value.get("adapter")
                or kind not in selected["host_kinds"]
                or not isinstance(value.get("adapter_settings"), dict)
                or not isinstance(value.get("launcher_qualification"), dict)):
            raise ValueError("Otto profile pack host/profile qualification is invalid")
        allowed = value["adapter_settings"].get("models")
        if allowed is not None and any(role["model"] not in allowed for role in selected["roles"].values()):
            raise ValueError("Otto profile pack binds a model this host cannot serve")
    pin = {"pack_id": pack.pack_id, "pack_version": pack.version,
           "source_revision": pack.source.source_revision,
           "source_inventory_identity": pack.source.source_inventory_identity,
           "resource_digests": {path: resources[path].source_digest for path in ("profiles.json", "hosts.json")}}
    return {"default_profile": profiles["default_profile"], "profiles": names,
            "hosts": hosts["hosts"], "pin": pin}


def profile_for_host(host_kind: Optional[str]) -> str:
    """Select only a fleet-implemented host kind declared by the profile pack."""
    REGISTRY.get(host_kind)
    host = load_profile_pack()["hosts"].get(host_kind)
    if host is None:
        raise UnknownHostKind(f"no model profile for host kind {host_kind!r}")
    return host["model_profile"]


def host_entry(kind: str, *, model_profile: Optional[str] = None) -> dict[str, Any]:
    """Return one host's qualified pack policy, refusing a foreign profile."""
    REGISTRY.get(kind)
    pack = load_profile_pack()
    host = pack["hosts"].get(kind)
    if host is None:
        raise UnknownHostKind(f"no profile pack host kind {kind!r}")
    chosen = model_profile or host["model_profile"]
    selected = pack["profiles"].get(chosen)
    if selected is None:
        raise ProfileSelectionError("unknown model profile %r" % (chosen,))
    if kind not in selected["host_kinds"] or selected["adapter"] != host["adapter"]:
        raise ProfileSelectionError("model profile %r is not qualified by host %r" % (chosen, kind))
    allowed = host["adapter_settings"].get("models")
    if allowed is not None and any(role["model"] not in allowed for role in selected["roles"].values()):
        raise ProfileSelectionError("model profile %r names a model unsupported by host %r" % (chosen, kind))
    if kind == "claude-code":
        from otto.agents.claude_cli import PARSER_SCHEMA, VERSION
        qualification = host["launcher_qualification"]
        if qualification.get("version") != VERSION or qualification.get("parser_schema") != PARSER_SCHEMA:
            raise ProfileSelectionError("qualified Claude launcher data differs from the installed parser")
    return copy.deepcopy(dict(host))


def model_plan(name: str) -> ModelPlan:
    """The fleet plan for a profile's normal and xhard worker bindings."""
    roles = profile(name)["roles"]
    return ModelPlan(ModelBinding(**roles["worker_normal"]), ModelBinding(**roles["worker_xhard"]))


def serving_host(host_kind: Optional[str]) -> Any:
    return REGISTRY.get(host_kind).serving(model_plan(profile_for_host(host_kind)))


def resolve_profile_name(explicit: Optional[str] = None, *, host_kind: Optional[str] = None,
                         environ: Optional[Mapping[str, str]] = None) -> str:
    """Select an explicit profile, then environment, host, then pack default."""
    env = os.environ if environ is None else environ
    pack = load_profile_pack()
    names = pack["profiles"]
    for candidate in (explicit, env.get("OTTO_MODEL_PROFILE")):
        if candidate:
            if candidate not in names:
                raise ProfileSelectionError("unknown model profile %r; known: %s" % (candidate, ", ".join(sorted(names))))
            if host_kind is not None:
                host_entry(host_kind, model_profile=candidate)
            return candidate
    kind = host_kind or env.get("OTTO_HOST_KIND")
    return profile_for_host(kind) if kind else pack["default_profile"]


def profile(name: str, *, host_kind: Optional[str] = None) -> dict[str, Any]:
    pack = load_profile_pack()
    if name not in pack["profiles"]:
        raise ProfileSelectionError("unknown model profile %r" % (name,))
    if host_kind is not None:
        host_entry(host_kind, model_profile=name)
    value = copy.deepcopy(pack["profiles"][name])
    value["name"] = name
    value["pin"] = copy.deepcopy(pack["pin"])
    return value


def profile_for_run(run: Mapping[str, Any], *, host_kind: str, default_profile: str) -> dict[str, Any]:
    """Resolve a project's explicit profile before the host default, then qualify it."""
    selected = run.get("model_profile") or default_profile
    return profile(selected, host_kind=host_kind)


def profile_resource_pin(full_pin: Mapping[str, Any]) -> dict[str, Any]:
    """Policy resource identity usable inside a Git-tracked run template.

    The full source revision includes the commit containing the template, so
    embedding it in that same template would invalidate itself at commit.
    """
    return {key: copy.deepcopy(full_pin[key]) for key in
            ("pack_id", "pack_version", "resource_digests")}


def profile_pin_matches(declared: Any, full_pin: Mapping[str, Any]) -> bool:
    """Accept an exact adopted pin or the template's exact resource pin."""
    return declared == full_pin or (isinstance(declared, Mapping)
        and set(declared) == {"pack_id", "pack_version", "resource_digests"}
        and dict(declared) == profile_resource_pin(full_pin))


def slot_binding(slot: str, name: Optional[str] = None, **options: Any) -> dict[str, str]:
    if slot not in SLOTS:
        raise ValueError("unknown responsibility slot %r" % (slot,))
    chosen = profile(resolve_profile_name(name, **options))
    return {**chosen["roles"][slot], "adapter": chosen["adapter"]}


def __getattr__(name: str) -> Any:
    # Historical readers still import PROFILES; this is a computed view, not a
    # second live table. New consumers use profile() and its exact pack pin.
    if name == "PROFILES":
        return load_profile_pack()["profiles"]
    raise AttributeError(name)


def run_template(name: str, *, mode: str = "planning_only") -> dict[str, Any]:
    """Resolve a Megado template with a pinned seven-slot profile default."""
    from herzchen.packs.authoring import read_managed_pack
    from otto.hostctl.owner import _managed_source_state_path

    chosen = profile(name)
    source_root = Path(__file__).resolve().parents[2]
    pack = read_managed_pack("megado", project_root=source_root.parent,
                             native_pack_root=source_root / "otto" / "packs",
                             source_state_path=_managed_source_state_path())
    path = "skill/templates/run.json" if name == "codex" else "skill/templates/run.claude.json"
    resource = next((item for item in pack.resources if item.path == path), None)
    if resource is None:
        raise ValueError("Megado has no run template for model profile %r" % (name,))
    template = json.loads(resource.content)
    if (template.get("model_profile") != name or "roles" in template
            or not profile_pin_matches(template.get("profile_pack"), chosen["pin"])):
        raise ValueError("Megado run template conflicts with its selected profile")
    return {**template, "mode": mode, "roles": copy.deepcopy(chosen["roles"]),
            "oracle": copy.deepcopy(chosen["oracle"]),
            "review_stages": copy.deepcopy(chosen["review_stages"]),
            "assurance_selection": chosen["assurance_selection"],
            "scheduled_checks": copy.deepcopy(chosen["scheduled_checks"]),
            "profile_pack": copy.deepcopy(chosen["pin"])}
