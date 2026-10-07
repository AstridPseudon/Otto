"""Role context from the BASE resource's explicit, adopted source pins.

This is a projection over DAT documents, not a context store or a filesystem
loader. A new document revision needs a new BASE adoption before future turns
can consume it. Selected packs may supply role bindings without core model or
delegation defaults.

A selected configuration is an ordinary DAT document pinned in BASE
``supporting_refs``. Its content has ``schema: otto.role-configuration.v1``,
``roles`` (the adopted run's slot-to-model/reasoning bindings), and
``role_bindings`` (execution-role-to-slot selection). Optional
``tool_entrypoints`` maps execution roles to the installed host command;
``role_policies`` supplies selected policy text for each execution role.
Other supporting documents retain their own roles, content and provenance.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .owner_readers import json_value, owner_ref


class RoleContextError(ValueError):
    """A declared role source is missing, stale, or incompatible."""


def supporting_context(base: Mapping[str, Any], reader: Any, *, exact_direction_inputs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    refs = base.get("content", {}).get("supporting_refs", [])
    if not isinstance(refs, list) or len(refs) > 32:
        raise RoleContextError("BASE supporting_refs must be a bounded list")
    result, seen = [], {}
    authorized = {tuple(item["ref"][k] for k in ("authority", "kind", "id")): item
                  for item in (exact_direction_inputs or [])}
    for raw in refs:
        ref = owner_ref(raw, "BASE supporting reference")
        identity = tuple(ref[k] for k in ("authority", "kind", "id"))
        if ref["kind"] != "dat.content.document" or ref["authority"] != base["resource_ref"]["authority"]:
            raise RoleContextError("BASE supporting context requires owner-local DAT documents")
        if identity in seen:
            if seen[identity] != ref:
                raise RoleContextError("BASE supporting context has conflicting revisions")
            continue
        seen[identity] = ref
        if identity in authorized:
            item = authorized[identity]
            if ref != item["ref"]:
                raise RoleContextError("BASE conflicts with scope-authorized direction input: " + ref["id"])
            result.append(dict(item, source="scope-authorized assignment direction", adopted_by=base["resource_ref"]))
            continue
        try:
            observed = json_value(reader.read(ResourceRef.from_dict({k: ref[k] for k in ("authority", "kind", "id")})))
        except Exception as exc:
            raise RoleContextError("required supporting context unavailable: " + ref["id"]) from exc
        revision = observed.get("revision") if isinstance(observed, Mapping) else None
        current = observed.get("current_revision") if isinstance(observed, Mapping) else None
        document = observed.get("document") if isinstance(observed, Mapping) else None
        if (not isinstance(revision, Mapping) or revision.get("revision") != ref["revision"]
                or not isinstance(current, Mapping) or current != ref
                or not isinstance(document, Mapping)
                or not isinstance(document.get("ref"), Mapping)
                or any(document["ref"].get(k) != ref[k] for k in ("authority", "kind", "id"))
                or "content" not in revision):
            raise RoleContextError("required supporting context is missing or stale; adopt current BASE: " + ref["id"])
        content = revision["content"]
        if document.get("role") == "direction":
            raise RoleContextError("direction pin has no applicable scope authorization: " + ref["id"])
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode()).hexdigest()
        result.append({"ref": ref, "document_role": document.get("role"), "content": content,
                       "content_sha256": digest, "source": "adopted_BASE.supporting_refs",
                       "adopted_by": base["resource_ref"]})
    return result


def selected_configuration(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected = [item for item in sources if isinstance(item["content"], Mapping)
                and item["content"].get("schema") == "otto.role-configuration.v1"]
    if len(selected) > 1:
        raise RoleContextError("BASE selects more than one role configuration")
    if not selected:
        return None
    item = selected[0]
    content = item["content"]
    if not isinstance(content.get("roles"), Mapping) or not isinstance(content.get("role_bindings"), Mapping):
        raise RoleContextError("selected configuration requires roles and role_bindings")
    return item


def configured_binding(configuration: Mapping[str, Any] | None, role: str) -> Mapping[str, Any]:
    if configuration is None:
        return {}
    content = configuration["content"]
    slot = content["role_bindings"].get(role)
    value = content["roles"].get(slot) if isinstance(slot, str) else None
    if not isinstance(value, Mapping):
        raise RoleContextError("selected configuration has no binding for " + role)
    for key in ("model", "reasoning"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise RoleContextError("selected " + role + " configuration requires " + key)
    return value


def role_introduction(canonical: Mapping[str, Any]) -> dict[str, Any]:
    from .operating_brief import ROLE_CONTEXT_GUIDANCE, ROLE_OPERATING_CONTRACTS
    render = canonical["render"]
    state, snapshot = render["project_state"], render["snapshot"]
    project = state["project"]
    task = state.get("task")
    brief = render["brief"]
    configuration = selected_configuration(canonical.get("supporting_context", []))
    tools = configuration["content"].get("tool_entrypoints", {}) if configuration else {}
    if not isinstance(tools, Mapping):
        raise RoleContextError("selected configuration tool_entrypoints must be an object")
    entrypoint = tools.get(canonical["role"])
    if entrypoint is not None and (not isinstance(entrypoint, str) or not entrypoint.strip()):
        raise RoleContextError("selected role tool entrypoint must be non-blank text")
    policies = configuration["content"].get("role_policies", {}) if configuration else {}
    if not isinstance(policies, Mapping):
        raise RoleContextError("selected configuration role_policies must be an object")
    policy = policies.get(canonical["role"])
    if policy is not None and (not isinstance(policy, str) or not policy.strip()):
        raise RoleContextError("selected role policy must be non-blank text")
    return {"schema": "otto.role-introduction.v1", "role": canonical["role"],
            "principal": snapshot["principal"], "assignment_ref": snapshot["assignment_ref"],
            "generation": snapshot["generation"], "responsibility": ROLE_OPERATING_CONTRACTS[canonical["role"]],
            "responsibility_ref": snapshot.get("responsibility_ref"),
            "launch_context": {"informational": True, "credential": False,
                "principal": snapshot["principal"], "role": canonical["role"],
                "responsibility_ref": snapshot.get("responsibility_ref"),
                "assignment_ref": snapshot["assignment_ref"], "generation": snapshot["generation"],
                "native_session": snapshot.get("native_session"),
                "direction_refs": [item["effective_ref"] for item in canonical.get("direction_context", [])],
                "identity_read": "effective-context (requires a trusted per-request host binding)"},
            "selected_policy": policy,
            "selected_policy_source": configuration["ref"] if policy else None,
            "operating_guidance": dict(ROLE_CONTEXT_GUIDANCE[canonical["role"]]),
            "goal": {"ref": project["ref"], "title": project["payload"].get("title"),
                     "outcome": project["payload"].get("outcome")},
            "current_task": None if task is None else {"ref": task["ref"],
                "title": task["payload"].get("title"), "outcome": task["payload"].get("outcome"),
                "acceptance": task["payload"].get("acceptance", [])},
            "mandate_ref": snapshot["mandate_ref"], "mandate": brief["mandate"],
            "user_constraints": brief["user_constraints"], "operational_constraints": brief["operational_constraints"],
            "links": brief["links"], "base_resource": canonical["base_resource"]["ref"],
            "supporting_refs": [item["ref"] for item in canonical.get("supporting_context", [])],
            "tool_entrypoint": entrypoint or "python -m otto.portfolio.cli help --format text",
            "tool_entrypoint_source": configuration["ref"] if entrypoint else "installed Otto portfolio help",
            "source": "canonical owner records and adopted role resources", "dispatch": False}
