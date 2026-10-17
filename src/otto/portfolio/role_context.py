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
from pathlib import Path
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .owner_readers import json_value, owner_ref


def _role_pack_locations(module_path: str | Path = __file__) -> tuple[Path, Path]:
    source_root = Path(module_path).resolve().parents[2]
    project_root = source_root.parent
    return project_root, source_root / "otto" / "packs"


def _role_pack(configuration: Mapping[str, Any] | None, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the native versioned role pack and enforce an adopted exact pin."""
    from herzchen.packs.authoring import read_managed_pack

    project_root, pack_root = _role_pack_locations()
    config_content = configuration.get("content") if isinstance(configuration, Mapping) else None
    if configuration is not None and not isinstance(config_content, Mapping):
        raise RoleContextError("adopted role configuration is invalid")
    selected = config_content.get("role_pack") if isinstance(config_content, Mapping) else None
    if selected is not None and not isinstance(selected, Mapping):
        raise RoleContextError("selected role pack pin must be an object")
    pack_id = selected.get("pack_id", "otto-roles") if isinstance(selected, Mapping) else "otto-roles"
    try:
        from otto.hostctl.owner import _managed_source_state_path
        pack = read_managed_pack(pack_id, project_root=project_root, native_pack_root=pack_root,
                                 source_state_path=_managed_source_state_path())
    except Exception as exc:
        raise RoleContextError("selected role pack is unavailable or changed") from exc
    path = selected.get("resource_path", "roles.json") if isinstance(selected, Mapping) else "roles.json"
    resource = next((item for item in pack.resources if item.path == path and item.kind == "role_guidance"), None)
    if resource is None:
        raise RoleContextError("selected role pack resource is missing")
    actual_pin = {"pack_id": pack.pack_id, "pack_version": pack.version,
                  "source_revision": pack.source.source_revision,
                  "source_inventory_identity": pack.source.source_inventory_identity,
                  "resource_path": resource.path, "resource_digest": resource.source_digest}
    if isinstance(selected, Mapping) and dict(selected) != actual_pin:
        raise RoleContextError("selected role pack pin is stale or inconsistent")
    try:
        content = json.loads(resource.content.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RoleContextError("selected role pack resource is invalid") from exc
    if not isinstance(content, Mapping) or content.get("schema") != "otto.role-pack.v1":
        raise RoleContextError("selected role pack has an unsupported schema")
    adapter_guidance = content.get("adapter_role_guidance")
    if not isinstance(adapter_guidance, str) or not adapter_guidance.strip():
        raise RoleContextError("selected role pack has no adapter role guidance")
    role_value = content.get("roles", {}).get(role) if isinstance(content.get("roles"), Mapping) else None
    guidance = role_value.get("guidance") if isinstance(role_value, Mapping) else None
    if (not isinstance(role_value, Mapping) or not isinstance(role_value.get("responsibility"), str)
            or not role_value["responsibility"].strip() or not isinstance(guidance, Mapping) or not guidance
            or any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
                   for key, value in guidance.items())
            or not isinstance(role_value.get("tools", []), list)
            or any(not isinstance(item, str) or not item.strip() for item in role_value.get("tools", []))):
        raise RoleContextError("selected role pack has no valid role " + role)
    if (not isinstance(role_value.get("tool_entrypoint"), str) or not role_value["tool_entrypoint"].strip()
            or not isinstance(role_value.get("manager_actions", []), list)
            or any(not isinstance(item, str) or not item.strip() for item in role_value.get("manager_actions", []))):
        raise RoleContextError("selected role pack has invalid tools for " + role)
    base_manager = content.get("base_manager_brief")
    if (not isinstance(base_manager, Mapping)
            or base_manager.get("schema") != "otto.base-manager-brief.v1"
            or not isinstance(base_manager.get("mandate"), str) or not base_manager["mandate"].strip()
            or not isinstance(base_manager.get("constraints"), list) or not base_manager["constraints"]
            or any(not isinstance(item, str) or not item.strip() for item in base_manager["constraints"])):
        raise RoleContextError("selected role pack has an invalid base manager brief")
    return {**dict(role_value), "pin": actual_pin, "base_manager_brief": dict(base_manager),
            "adapter_role_guidance": adapter_guidance}, {"pack": pack, "resource": resource}


def _compose_role(role_data: Mapping[str, Any], configuration: Mapping[str, Any] | None,
                  role: str) -> dict[str, Any]:
    """Apply only an already adopted configuration's explicit role overrides."""
    result = dict(role_data)
    if configuration is None:
        return result
    content = configuration.get("content")
    if not isinstance(content, Mapping):
        raise RoleContextError("adopted role configuration is invalid")
    policies = content.get("role_policies", {})
    tools = content.get("tool_entrypoints", {})
    if not isinstance(policies, Mapping) or not isinstance(tools, Mapping):
        raise RoleContextError("adopted role overrides must be objects")
    policy = policies.get(role)
    tool = tools.get(role)
    if policy is not None:
        if not isinstance(policy, str) or not policy.strip():
            raise RoleContextError("adopted role policy must be non-blank text")
        result["selected_policy"] = policy
        result["selected_policy_source"] = configuration.get("ref")
    if tool is not None:
        if not isinstance(tool, str) or not tool.strip():
            raise RoleContextError("adopted role tool entrypoint must be non-blank text")
        result["tool_entrypoint"] = tool
        result["tool_source"] = configuration.get("ref")
    return result


def _effective_role_data(canonical: Mapping[str, Any],
                         configuration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if configuration is None:
        configuration = selected_configuration(canonical.get("supporting_context", []))
    role_data, _ = _role_pack(configuration, canonical.get("role"))
    role_data = _compose_role(role_data, configuration, canonical.get("role"))
    if role_data.get("include_adapter_guidance"):
        from .operating_brief import _host_role_guidance
        role_data["responsibility"] += _host_role_guidance(base_text=role_data["adapter_role_guidance"])
    return role_data


class RoleContextError(ValueError):
    """A declared role source is missing, stale, or incompatible."""


def supporting_context(base: Mapping[str, Any], reader: Any, *, exact_direction_inputs: list[dict[str, Any]] | None = None,
                       completed_support_refs: tuple[Mapping[str, Any], ...] = ()) -> list[dict[str, Any]]:
    refs = base.get("content", {}).get("supporting_refs", [])
    if not isinstance(refs, list) or len(refs) > 32:
        raise RoleContextError("BASE supporting_refs must be a bounded list")
    result, seen = [], {}
    retained = [owner_ref(ref, "completed supporting reference") for ref in completed_support_refs]
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
            # Only completed-result reconstruction may resolve its exact
            # immutable delivered support pins. New delivery still reads HEAD.
            completed = ref in retained
            lookup = {k: ref[k] for k in ("authority", "kind", "id")}
            observed = json_value(reader.read(ResourceRef.from_dict(lookup)))
            if completed:
                exact = json_value(reader.read(ResourceRef.from_dict(ref)))
                if (not isinstance(exact, Mapping) or exact.get("identity") != ref
                        or exact.get("revision") != ref["revision"] or "content" not in exact):
                    raise RoleContextError("completed supporting revision unavailable: " + ref["id"])
                # Immutable DAT reads expose revision/content separately; current
                # metadata still supplies the live document identity/role.
                observed = dict(observed, revision={"revision": exact["revision"], "content": exact["content"]})
        except Exception as exc:
            raise RoleContextError("required supporting context unavailable: " + ref["id"]) from exc
        revision = observed.get("revision") if isinstance(observed, Mapping) else None
        current = observed.get("current_revision") if isinstance(observed, Mapping) else None
        document = observed.get("document") if isinstance(observed, Mapping) else None
        if (not isinstance(revision, Mapping) or revision.get("revision") != ref["revision"]
                or (not completed and (not isinstance(current, Mapping) or current != ref))
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
                                 identity_commands: tuple[str, ...] = ("effective-context", "whoami"),
                                 role_data: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    if role_data is None:
        role_data = _effective_role_data(canonical)
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
    available_commands = {"tool_entrypoint": tool_entrypoint,
                          "identity_reads": list(identity_commands)}
    result = {
        "schema": "otto.effective-role-context.v1",
        "assignment_ref": snapshot.get("assignment_ref"),
        "responsibility_ref": snapshot.get("responsibility_ref"),
        "generation": snapshot.get("generation"),
        "directive_context": [dict(item) for item in directions],
        "directive_revisions": directive_revisions,
        "resource_revisions": resources,
        "remit": {"role": canonical.get("role"), "mandate": brief.get("mandate"),
                  "responsibility": role_data["responsibility"]},
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
        "available_commands": available_commands,
    }
    if canonical.get("role") == "manager":
        result["manager_actions"] = list(role_data["manager_actions"])
        manager_notes = {
            "priorities": brief.get("priorities", []),
            "operational_constraints": brief.get("operational_constraints", []),
            "continuation": brief.get("continuation"),
            "links": brief.get("links", []),
        }
        result["effective_manager_brief"] = {
            "schema": "otto.effective-manager-brief.v1",
            "project_ref": project["ref"],
            "assignment_ref": snapshot.get("assignment_ref"),
            "generation": snapshot.get("generation"),
            "base_manager_brief": {
                **role_data["base_manager_brief"],
                "content_sha256": hashlib.sha256(json.dumps(role_data["base_manager_brief"], sort_keys=True,
                    separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
                "source": "versioned Otto role pack",
            },
            "project_brief": {
                "mandate": brief.get("mandate"),
                "user_constraints": brief.get("user_constraints", []),
                "source_ref": snapshot.get("mandate_ref"),
            },
            "manager_notes": manager_notes,
            "precedence": "Current authority and adopted directions; project brief; manager notes; base manager guidance.",
        }
    return result


def same_supervisor_authority_binding(declared: Any, current: Any) -> bool:
    """Compare informational pins against an already authenticated supervisor.

    Project/task changes and resource adoption advance ResourceRef revisions.
    Those revisions remain provenance; current authorization still comes from
    the owner delivery reader's exact current assignment, scope and session.
    This comparison grants no authority and never authenticates stale bindings.
    """
    keys = {"project_ref", "assignment_ref", "generation", "principal", "conversation_ref"}
    if not isinstance(declared, Mapping) or not isinstance(current, Mapping):
        return False
    if set(declared) != keys or set(current) != keys:
        return False
    for name, kind in (("project_ref", "work.project"), ("assignment_ref", "wrk.assignment")):
        try:
            before, after = ResourceRef.from_dict(declared[name]), ResourceRef.from_dict(current[name])
        except (TypeError, ValueError, KeyError):
            return False
        if (before.kind != kind or after.kind != kind or not before.revision or not after.revision
                or (before.authority, before.kind, before.id) != (after.authority, after.kind, after.id)):
            return False
    generation = declared["generation"]
    if type(generation) is not int or generation < 1 or type(current["generation"]) is not int:
        return False
    if not isinstance(declared["principal"], str) or not declared["principal"].strip():
        return False
    conversation = declared["conversation_ref"]
    if (not isinstance(conversation, Mapping) or not isinstance(conversation.get("host"), str)
            or not conversation["host"].strip() or not isinstance(conversation.get("native_id"), str)
            or not conversation["native_id"].strip()):
        return False
    return all(declared[name] == current[name] for name in ("generation", "principal", "conversation_ref"))


def role_introduction(canonical: Mapping[str, Any], *, operational_supervisor: Mapping[str, Any] | None = None) -> dict[str, Any]:
    render = canonical["render"]
    state, snapshot = render["project_state"], render["snapshot"]
    project = state["project"]
    task = state.get("task")
    brief = render["brief"]
    configuration = selected_configuration(canonical.get("supporting_context", []))
    selected_role = _effective_role_data(canonical, configuration)
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
    tool_entrypoint = entrypoint or selected_role["tool_entrypoint"]
    responsibility = selected_role["responsibility"]
    effective_context = effective_context_projection(canonical, tool_entrypoint=tool_entrypoint,
                                                     role_data=selected_role)
    role_guidance = selected_role["guidance"]
    result = {"schema": "otto.role-introduction.v1", "role": canonical["role"],
            "principal": snapshot["principal"], "assignment_ref": snapshot["assignment_ref"],
            "generation": snapshot["generation"], "responsibility": responsibility,
            "responsibility_ref": snapshot.get("responsibility_ref"),
            "launch_context": {"informational": True, "credential": False,
                "principal": snapshot["principal"], "role": canonical["role"],
                "responsibility_ref": snapshot.get("responsibility_ref"),
                "assignment_ref": snapshot["assignment_ref"], "generation": snapshot["generation"],
                "native_session": snapshot.get("native_session"),
                "direction_refs": [item["effective_ref"] for item in canonical.get("direction_context", [])],
                "identity_read": "effective-context (requires a trusted per-request host binding)"},
            "selected_policy": policy,
            "selected_policy_source": selected_role.get("selected_policy_source"),
            "operating_guidance": dict(role_guidance),
            "role_pack": selected_role["pin"],
            "available_tools": list(selected_role.get("tools", [])),
            "goal": {"ref": project["ref"], "title": project["payload"].get("title"),
                     "outcome": project["payload"].get("outcome")},
            "current_task": None if task is None else {"ref": task["ref"],
                "title": task["payload"].get("title"), "lifecycle": task["payload"].get("lifecycle"),
                "outcome": task["payload"].get("outcome"),
                "acceptance": task["payload"].get("acceptance", []),
                "execution_anchor": True,
                "actionability": ("not-actionable" if task["payload"].get("lifecycle") == "completed"
                                  else "requires-current-task-read" if canonical["role"] == "manager"
                                  else "current-lifecycle" if task["payload"].get("lifecycle") in {"pending", "active"}
                                  else "unknown"),
                "actionability_source": ("current_task.lifecycle" if task["payload"].get("lifecycle") is not None
                                         else "current_task.lifecycle unavailable")},
            "mandate_ref": snapshot["mandate_ref"], "mandate": brief["mandate"],
            "user_constraints": brief["user_constraints"], "operational_constraints": brief["operational_constraints"],
            "links": brief["links"], "base_resource": canonical["base_resource"]["ref"],
            "supporting_refs": [item["ref"] for item in canonical.get("supporting_context", [])],
            "tool_entrypoint": tool_entrypoint,
            "tool_entrypoint_source": (configuration["ref"] if entrypoint else selected_role["pin"]),
            "effective_context": effective_context,
            "source": "canonical owner records and adopted role resources", "dispatch": False,
            "dispatch_scope": "This informational context projection dispatches nothing; command authority is checked separately."}
    if canonical["role"] == "manager":
        # Composed for every manager at the canonical launch seam, including
        # custom mandates. These are information pins, never host credentials.
        config = configuration["content"] if configuration else {}
        standard_guide = config.get("standard_manager_guide")
        enrolled = isinstance(project.get("payload", {}).get("metadata", {}).get("otto_orchestrator"), Mapping)
        if standard_guide is None and enrolled:
            standard_guide = {"ref": canonical["base_resource"]["ref"], "content_sha256": canonical["base_resource"]["content_sha256"], "standard_contract_sha256": hashlib.sha256(json.dumps({"responsibility": responsibility, "guidance": role_guidance}, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "source": "current adopted BASE and installed canonical manager contract"}
        if config.get("standard_manager_guide") is not None and (not isinstance(standard_guide, Mapping) or not any(
                item.get("ref") == standard_guide.get("ref")
                and item.get("content_sha256") == standard_guide.get("content_sha256")
                for item in canonical.get("supporting_context", []))):
            raise RoleContextError("standard manager guide must be an exact adopted supporting source")
        supervisor = operational_supervisor
        declared = config.get("operational_supervisor")
        if declared is not None and not same_supervisor_authority_binding(declared, supervisor):
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
            "declared_supervisor": declared,
            "supervisor_binding_comparison": "authority-identity-generation-principal-conversation",
            "standard_manager_guide": standard_guide,
            "base_resource": canonical["base_resource"]["ref"],
            "project_and_custom_context_refs": result["supporting_refs"],
            "mandate_ref": snapshot["mandate_ref"], "tool_entrypoint": tool_entrypoint,
            "instructions": role_guidance["help"],
            "effective_manager_brief": effective_context.get("effective_manager_brief"),
            "precedence": "Current authenticated authority and adopted directions govern; standard manager duties and selected pack policy accompany the custom mandate. Information pins grant no new authority.",
        }
        effective_context["manager_operating_context"] = result["manager_operating_context"]
    return result
