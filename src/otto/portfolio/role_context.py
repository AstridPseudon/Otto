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
from .operating_brief import ROLE_OPERATING_CONTRACTS
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


def _project_set(project: Mapping[str, Any], project_ref: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the owner-selected project set without inferring a portfolio."""
    payload = project.get("payload") if isinstance(project.get("payload"), Mapping) else project
    metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
    metadata = metadata if isinstance(metadata, Mapping) else {}
    selected = None
    for source in (payload, metadata):
        if not isinstance(source, Mapping):
            continue
        for key in ("selected_project_refs", "selected_projects", "project_set", "supervised_project_refs"):
            if key in source:
                selected = source[key]
                break
        if selected is not None:
            break
    if selected is None:
        selected = [project_ref]
    if not isinstance(selected, (list, tuple)) or not selected:
        raise RoleContextError("selected project set must be a non-empty list")
    result = []
    seen = set()
    for item in selected:
        if not isinstance(item, Mapping) or any(not isinstance(item.get(key), str) or not item[key].strip()
                                                for key in ("authority", "kind", "id")):
            raise RoleContextError("selected project set contains an invalid project reference")
        if item["kind"] != "work.project" or item["authority"] != project_ref["authority"]:
            raise RoleContextError("selected project set contains a foreign project")
        identity = tuple(item[key] for key in ("authority", "kind", "id"))
        if identity not in seen:
            result.append({key: item[key] for key in ("authority", "kind", "id", "revision") if key in item})
            seen.add(identity)
    current = tuple(project_ref[key] for key in ("authority", "kind", "id"))
    if current not in seen:
        raise RoleContextError("selected project set omits the current project")
    return result


def effective_context_projection(canonical: Mapping[str, Any], *, tool_entrypoint: str,
                                 identity_commands: tuple[str, ...] = ("effective-context", "whoami")) -> dict[str, Any]:
    """Project durable role context while retaining only canonical pins and bounded state."""
    render = canonical.get("render")
    if not isinstance(render, Mapping):
        raise RoleContextError("canonical role context has no render")
    state = render.get("project_state")
    snapshot = render.get("snapshot")
    brief = render.get("brief")
    if not isinstance(state, Mapping) or not isinstance(snapshot, Mapping) or not isinstance(brief, Mapping):
        raise RoleContextError("canonical role context is incomplete")
    project = state.get("project")
    task = state.get("task")
    if not isinstance(project, Mapping) or not isinstance(project.get("ref"), Mapping):
        raise RoleContextError("canonical role context has no project")
    project_payload = project.get("payload") if isinstance(project.get("payload"), Mapping) else {}
    task_payload = task.get("payload") if isinstance(task, Mapping) and isinstance(task.get("payload"), Mapping) else {}
    continuation = brief.get("continuation") if isinstance(brief.get("continuation"), Mapping) else {}
    next_actor = continuation.get("next_actor", continuation.get("actor"))
    if next_actor is None:
        next_actor = task_payload.get("next_actor", project_payload.get("next_actor"))
    next_action = continuation.get("next_action", continuation.get("action"))
    directions = canonical.get("direction_context", [])
    if not isinstance(directions, list):
        raise RoleContextError("canonical direction context must be a list")
    directive_revisions = []
    for scope in directions:
        if not isinstance(scope, Mapping):
            raise RoleContextError("canonical direction context contains an invalid scope")
        effective = scope.get("effective_ref")
        if isinstance(effective, Mapping):
            directive_revisions.append({key: effective[key] for key in ("authority", "kind", "id", "revision") if key in effective})
    base = canonical.get("base_resource") if isinstance(canonical.get("base_resource"), Mapping) else {}
    resources = []
    if isinstance(base.get("ref"), Mapping):
        resources.append({"ref": dict(base["ref"]), "adopted_revision": base.get("revision"),
                          "content_sha256": base.get("content_sha256")})
    for item in canonical.get("supporting_context", ()):
        if isinstance(item, Mapping) and isinstance(item.get("ref"), Mapping):
            resources.append({"ref": dict(item["ref"]), "content_sha256": item.get("content_sha256"),
                              "source": item.get("source")})
    return {
        "schema": "otto.effective-role-context.v1",
        "assignment_ref": snapshot.get("assignment_ref"),
        "responsibility_ref": snapshot.get("responsibility_ref"),
        "generation": snapshot.get("generation"),
        "directive_context": [dict(item) for item in directions],
        "directive_revisions": directive_revisions,
        "resource_revisions": resources,
        "remit": {"role": canonical.get("role"), "mandate": brief.get("mandate"),
                  "responsibility": ROLE_OPERATING_CONTRACTS.get(canonical.get("role"))},
        "selected_project_set": _project_set(project, project["ref"]),
        "current_outcomes": {
            "project": {"ref": project["ref"], "lifecycle": project.get("lifecycle"),
                        "outcome": project_payload.get("outcome"), "title": project_payload.get("title")},
            "task": None if task is None else {"ref": task.get("ref"), "lifecycle": task.get("lifecycle"),
                                                "outcome": task_payload.get("outcome"), "title": task_payload.get("title")},
        },
        "dependencies": task_payload.get("dependencies", project_payload.get("dependencies", [])),
        "next_actor": next_actor,
        "next_action": next_action,
        "available_commands": {"tool_entrypoint": tool_entrypoint,
                               "identity_reads": list(identity_commands)},
    }


def role_introduction(canonical: Mapping[str, Any], *, operational_supervisor: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    tool_entrypoint = entrypoint or "python -m otto.portfolio.cli help --format text"
    effective_context = effective_context_projection(canonical, tool_entrypoint=tool_entrypoint)
    result = {"schema": "otto.role-introduction.v1", "role": canonical["role"],
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
            "tool_entrypoint": tool_entrypoint,
            "tool_entrypoint_source": configuration["ref"] if entrypoint else "installed Otto portfolio help",
            "effective_context": effective_context,
            "source": "canonical owner records and adopted role resources", "dispatch": False}
    if canonical["role"] == "manager":
        # Composed for every manager at the canonical launch seam, including
        # custom mandates. These are information pins, never host credentials.
        config = configuration["content"] if configuration else {}
        standard_guide = config.get("standard_manager_guide")
        enrolled = isinstance(project.get("payload", {}).get("metadata", {}).get("otto_orchestrator"), Mapping)
        if standard_guide is None and enrolled:
            standard_guide = {"ref": canonical["base_resource"]["ref"], "content_sha256": canonical["base_resource"]["content_sha256"], "standard_contract_sha256": hashlib.sha256(json.dumps({"responsibility": ROLE_OPERATING_CONTRACTS["manager"], "guidance": ROLE_CONTEXT_GUIDANCE["manager"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "source": "current adopted BASE and installed canonical manager contract"}
        if config.get("standard_manager_guide") is not None and (not isinstance(standard_guide, Mapping) or not any(
                item.get("ref") == standard_guide.get("ref")
                and item.get("content_sha256") == standard_guide.get("content_sha256")
                for item in canonical.get("supporting_context", []))):
            raise RoleContextError("standard manager guide must be an exact adopted supporting source")
        supervisor = operational_supervisor
        declared = config.get("operational_supervisor")
        if declared is not None and declared != supervisor:
            raise RoleContextError("selected supervisor differs from current authenticated project supervision")
        if (config.get("manager_context_required") is True or enrolled) and (standard_guide is None or supervisor is None):
            raise RoleContextError("manager launch requires its adopted standard guide and current supervisor")
        if supervisor is not None:
            if not isinstance(supervisor, Mapping) or not isinstance(supervisor.get("project_ref"), Mapping) or any(key not in supervisor for key in
                    ("project_ref", "assignment_ref", "generation", "principal", "conversation_ref")):
                raise RoleContextError("manager supervisor requires a full adopted binding")
            if any(supervisor["project_ref"].get(k) != project["ref"].get(k)
                   for k in ("authority", "kind", "id")):
                raise RoleContextError("manager supervisor belongs to another project")
        result["manager_operating_context"] = {
            "schema": "otto.manager-operating-context.v1",
            "project_ref": project["ref"], "task_ref": None if task is None else task["ref"],
            "principal": snapshot["principal"], "assignment_ref": snapshot["assignment_ref"],
            "generation": snapshot["generation"], "operational_supervisor": supervisor,
            "supervisor_source": None if configuration is None else configuration["ref"],
            "standard_manager_guide": standard_guide,
            "base_resource": canonical["base_resource"]["ref"],
            "project_and_custom_context_refs": result["supporting_refs"],
            "mandate_ref": snapshot["mandate_ref"], "tool_entrypoint": tool_entrypoint,
            "instructions": ROLE_CONTEXT_GUIDANCE["manager"]["help"],
            "precedence": "Current authenticated authority and adopted directions govern; standard manager duties and selected pack policy accompany the custom mandate. Information pins grant no new authority.",
        }
        effective_context["manager_operating_context"] = result["manager_operating_context"]
    return result
