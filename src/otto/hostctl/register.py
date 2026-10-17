"""Register a Megado file-mode run bundle as a PENDING Otto project.

Every step is an existing owner operation with a stable logical request key,
so re-running the same registration replays it and a changed bundle under the
same key is a conflict. Nothing here prepares a Due for a role, activates the
project, launches an agent or calls a provider.

Steps (each idempotent):
 1. project + documents   OttoPortfolio.import_folder (raw bytes digests in custom)
 2. tasks                 ProjectSheet.apply from tasklist.md tables
 3. role configuration    otto.role-configuration.v1 document from run.json
 4. manager role          BASE guide (manager-brief.md) + assignment + adopted
                          BASE + manager mandate (workspace-write-manager)
 5. allowances            LimitService pools: oracle decisions + review stages
 6. orchestrator checks   DurableAttention Due records, host_state paused
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional

from herzchen.contracts import ResourceRef, canonical_json

from .bundle import parse_files, read_bundle

REGISTRATION_SCHEMA = "otto.host-registration.v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _objective(markdown: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith("## objective"):
            for candidate in lines[index + 1:]:
                if candidate.strip():
                    return candidate.strip()
    return _first_heading(markdown)


def _interval(check: Mapping[str, Any]) -> Optional[int]:
    """Explicit interval_seconds wins; else the check id/cadence names 6 h or hourly."""
    if isinstance(check.get("interval_seconds"), int) and check["interval_seconds"] > 0:
        return check["interval_seconds"]
    ident = (check.get("id") or "").lower()
    cadence = (check.get("cadence") or "").lower()
    if "6h" in ident or re.search(r"every 6 ?h|6-hour|6 hours", cadence):
        return 21600
    if "1h" in ident or cadence.startswith("hourly") or "every hour" in cadence:
        return 3600
    return None


def plan(bundle_source: Any, *, profile: Mapping[str, Any], manager_principal: str,
         worktree: str, tool_entrypoint: str) -> dict[str, Any]:
    """Pure: compute what registration and activation write.

    ``bundle_source`` is a source bundle (registration: the submitted run
    files are the authority) or an already parsed bundle (activation: Otto's
    own stored copies of the run's files are the authority). A generated run
    view is rejected by the bundle parser before its task table is parsed.
    """
    if isinstance(bundle_source, (str, Path)):
        bundle = read_bundle(bundle_source)
    else:
        # Rebuild every parsed field from the bundle's text. In particular,
        # callers cannot smuggle task rows parsed from a generated view beside
        # an unrelated source file mapping. Keep the supplied run record:
        # portfolio apply adds canonical card_dependencies to it in memory.
        bundle = {**bundle_source, **parse_files(dict(bundle_source["files"]),
                                                  raw_sha256=dict(bundle_source.get("raw_sha256") or {})),
                  "run": bundle_source["run"]}
    run = bundle["run"]
    run_id = run.get("run_id") or Path(bundle.get("root") or "run").name
    heading = _first_heading(bundle["files"]["agent_goal.md"]).split(":", 1)[-1].strip()
    title = heading if heading.startswith(run_id) else (run_id + ": " + heading if heading else run_id)
    task_ids = [task["id"] for task in bundle["tasks"]]
    tasks = []
    card_dependencies = run.get("card_dependencies") or {}
    for task in bundle["tasks"]:
        internal = [dep for dep in task["deps"] if dep in task_ids]
        declared_dependencies = card_dependencies.get(task["id"])
        if declared_dependencies is None:
            # The Megado parser intentionally extracts local task ids only;
            # retain explicit milestone/external tokens from the source too.
            dependency_text = re.sub(r"\([^)]*\)", " ", task.get("deps_text") or "")
            declared_dependencies = [token.strip().strip("*`") for token in
                re.split(r",|;|\band\b", dependency_text, flags=re.I)
                if "#" in token or token.strip().startswith("user:")]
        custom = {"megado": {"phase": task["phase"], "route": task["route"], "route_text": task["route_text"],
                             "repo": task["repo"], "who": task["who"], "deps_text": task["deps_text"],
                             "external_deps": [dep for dep in task["deps"] if dep not in task_ids],
                             "card_dependencies": list(declared_dependencies or ()),
                             "source": "tasklist.md"}}
        custom["otto.plan"] = {"repo": task.get("repo"), "branch": task.get("branch")}
        # The alias keeps the Megado id (M1, P1–P7, ...) as the durable task handle.
        value = {"id": task["id"], "alias": task["id"], "title": task["title"] or task["id"], "outcome": task["outcome"],
                 "acceptance": task["proof"] or "", "dependencies": internal, "custom": custom}
        tasks.append(value)
    roles = run.get("roles") or {}
    slot_bindings = {}
    profile_names = set()
    for slot, default in profile["roles"].items():
        configured = roles.get(slot) or {}
        model = configured.get("model", default["model"])
        # File-mode runs can intentionally mix adapter families. Preserve the
        # declared model family in drafts; an adapter is runtime authority and
        # is only inferred for the two built-in model namespaces.
        inferred = ("codex" if str(model).startswith(("gpt-", "o1", "o3", "o4")) else
                    "claude-code" if str(model).startswith("claude-") else profile["adapter"])
        adapter = configured.get("adapter") or inferred
        if adapter == "codex":
            profile_names.add("codex")
        elif adapter == "claude-code":
            profile_names.add("claude")
        else:
            profile_names.add(str(adapter))
        slot_bindings[slot] = {"adapter": adapter,
                               "model": model,
                               "reasoning": configured.get("reasoning", default["reasoning"]),
                               "provenance": {"model": "run file roles." + slot if "model" in configured
                                              else "host profile " + profile["name"],
                                              "reasoning": "run file roles." + slot if "reasoning" in configured
                                              else "host profile " + profile["name"]}}
    configuration = {"schema": "otto.role-configuration.v1",
                     "model_profile": next(iter(profile_names)) if len(profile_names) == 1 else "mixed",
                     "roles": slot_bindings,
                     "role_bindings": {"manager": "coordinator", "orchestrator": "oracle"},
                     "worker_routes": {"normal": "worker_normal", "xhard": "worker_xhard"},
                     "tool_entrypoints": {"manager": tool_entrypoint, "orchestrator": tool_entrypoint,
                                          "worker": tool_entrypoint},
                     "source": {"run_file": bundle["run_file"], "raw_sha256": bundle["raw_sha256"][bundle["run_file"]]}}
    allowances = []
    oracle = (run.get("oracle") or {}).get("max_calls")
    if isinstance(oracle, int) and oracle > 0:
        allowances.append({"id": "oracle", "purpose": "oracle decision requests (scheduled checks excluded)",
                           "units": oracle})
    for stage in run.get("review_stages") or ():
        units = int(stage.get("max_calls", 0)) + int(stage.get("repeat_allowance", 0))
        if units > 0:
            allowances.append({"id": _slug(stage["id"]), "purpose": stage["id"] + " review: " + stage.get("scope", ""),
                               "units": units, "reviewer": stage.get("reviewer"), "trigger": stage.get("trigger")})
    checks = []
    for check in run.get("scheduled_checks") or ():
        interval = _interval(check)
        if interval is None:
            continue
        checks.append({"id": check["id"], "interval_seconds": interval, "who": check.get("who"),
                       "cadence": check.get("cadence"), "purpose": check.get("purpose")})
    manager_brief = bundle["files"].get("manager-brief.md") or bundle["files"]["agent_goal.md"]
    custom = {"otto_host_registration": {
        "schema": REGISTRATION_SCHEMA, "run_id": run_id, "mode": run.get("mode"),
        "activation_trigger": run.get("activation_trigger"), "control_root": run.get("control_root"),
        "assessment_scope": run.get("assessment_accounting"),
        "source_bundle": bundle.get("root"), "raw_sha256": bundle["raw_sha256"],
        "activation": "pending: no role occurrence is prepared, no schedule is active, nothing is dispatched"}}
    brief = "\n".join(line for line in [
        "Megado run " + run_id + " (" + str(run.get("mode") or "draft") + ").",
        "Objective: " + _objective(bundle["files"]["agent_goal.md"]),
        ("Activation trigger: " + run["activation_trigger"]) if run.get("activation_trigger") else "",
        "Documents: " + ", ".join(sorted(bundle["files"])) + ".",
    ] if line)
    return {"run_id": run_id, "title": title, "outcome": _objective(bundle["files"]["agent_goal.md"]), "brief": brief,
            "files": bundle["files"], "raw_sha256": bundle["raw_sha256"], "custom": custom,
            "tasks": tasks, "configuration": configuration, "allowances": allowances, "checks": checks,
            "manager": {"principal": manager_principal, "slot": "coordinator",
                        "binding": slot_bindings["coordinator"], "brief": manager_brief,
                        "worktree": worktree, "first_task": tasks[0]["id"] if tasks else None},
            "phases": bundle["phases"]}


def _document(session: Any, project: Mapping[str, Any], key: str, document_id: str, content: Any, role: str) -> dict:
    created = session.portfolio.create_document(project, actor=session.host_principal(), request_id=key,
                                                document_id=document_id, role=role, content=content)
    if created.get("outcome") not in {"created", "replayed", "committed"} or "record" not in created:
        raise RuntimeError("document " + document_id + " was not committed: " + json.dumps(created, default=str)[:400])
    return created["record"]["payload"]["current_revision"]


def _manager_contract(task_ref: Mapping[str, Any], principal: str, worktree: str, run_id: str) -> dict:
    return {"task_ref": dict(task_ref), "objective": "Manage " + run_id + " to its agent_goal outcome",
            "bounded_operation": ("Coordinate the run per the adopted manager brief: dispatch ready tasks to the "
                                  "configured normal/xhard workers through the owner's run-worker route, read results, "
                                  "judge through the configured assessment path, and escalate decisions to the oracle."),
            "allowed_operations": ["read_project_context", "edit_candidate_workspace", "run_focused_tests",
                                   "return_progress", "canonical_manager_commands"],
            "acceptance_criteria": ["Every completed task has an accepted candidate and committed completion",
                                    "Decisions beyond the mandate were escalated to the oracle"],
            "authority": {"source": "canonical_owner", "owner_actor": principal, "gateway_claim_required": True,
                          "owner_write": False, "dispatch": False, "effect_profile": "workspace-write-manager",
                          "workspace_roots": [worktree],
                          "permitted_effects": ["read_delivered_context", "read_linked_sources",
                                                "file_write_in_workspace", "return_result", "canonical_manager_commands"],
                          "forbidden_effects": ["owner_write", "publication", "package_adoption", "remote_push",
                                                "release", "deployment"]}}


def register(session: Any, registration: Mapping[str, Any], *, key: Optional[str] = None) -> dict[str, Any]:
    """Register the run as an inert DRAFT on the canonical onboarding route.

    Only the draft exists afterwards: title, brief, the run's documents and
    the registration facts. Tasks, roles, pools and schedules are created at
    activation (``materialize``), from Otto's stored documents.
    """
    run_id = registration["run_id"]
    key = key or "register:" + run_id + ":v1"
    receipt: dict[str, Any] = {"schema": REGISTRATION_SCHEMA, "run_id": run_id, "request_key": key,
                               "provider_called": False, "dispatch": False, "steps": {}}
    principal = session.host_principal()
    existing = _registered_project(session, run_id)
    source_bundle = registration["custom"]["otto_host_registration"].get("source_bundle")
    same_folder = _registered_bundle(session, source_bundle) if source_bundle else None
    if same_folder is not None and (existing is None or same_folder.ref.id != existing.ref.id):
        raise ValueError("run folder is already registered: " + str(source_bundle))
    if existing is not None:
        existing_registration = (existing.payload.get("custom") or {}).get("otto_host_registration") or {}
        if existing_registration.get("source_bundle") == registration["custom"]["otto_host_registration"].get("source_bundle"):
            raise ValueError("run folder is already registered: " + run_id)
        raise ValueError("run id is already registered from another folder: " + run_id)
    else:
        created = None
    # 1. The canonical onboarding route: one inert title-and-brief draft whose
    #    supporting files are the run's documents (DAT, linked in project.files).
    if created is None:
        created = session.portfolio.create_draft(actor=principal, request_id=key, title=registration["title"],
            brief=registration["brief"], supporting_files=registration["files"])
    if created.get("outcome") not in {"created", "replayed"}:
        raise RuntimeError("onboarding create did not complete: " + json.dumps(created, default=str)[:600])
    project = ResourceRef.from_dict(created["project_ref"])
    receipt["steps"]["draft"] = {"outcome": created["outcome"], "project_ref": project.to_dict(),
                                 "workspace": (created.get("workspace") or {}).get("locator")}
    # 2. Registration facts on the draft (custom), through its own workspace.
    current = session.owner.graph.current(ResourceRef(project.authority, project.kind, project.id))
    current_custom = current.payload.get("custom") or {}
    wanted_custom = {**current_custom, **registration["custom"]}
    if current_custom != wanted_custom:
        # Use the draft's own open workspace (create_draft leaves it open).
        custom_key = hashlib.sha256(canonical_json(registration["custom"]).encode("utf-8")).hexdigest()[:16]
        _check_in(session, created["project_ref"], principal,
                  key + ":registration:" + custom_key + ":" + str(current.version),
                  lambda draft: draft.update(custom={**(draft.get("custom") or {}), **registration["custom"]}),
                  opened=(created.get("workspace") or {}).get("projection"))
    receipt["steps"]["registration"] = {"custom": "otto_host_registration", "lifecycle": "pending",
                                        "tasks": 0, "roles": 0, "pools": 0, "schedules": 0}
    # 3. Queue it in the host's own portfolio: the existing supervision
    #    relation (work.orchestrator.projects.attach). The host's orchestrator
    #    becomes the project's accountable supervisor (help is routed there).
    current = session.owner.graph.current(ResourceRef(project.authority, project.kind, project.id))
    relation = (current.payload.get("metadata") or {}).get("otto_orchestrator")
    if not relation:
        root = session.root_assignment()
        attached = session.portfolio.operations.execute("work.orchestrator.projects.attach", {
            "target_assignment_ref": root.ref.to_dict(), "target_assignment_revision": root.ref.revision,
            "target_assignment_generation": root.generation,
            "projects": [{"project_ref": current.ref.to_dict(), "project_version": current.version,
                          "assignment_ref": None, "assignment_revision": None, "assignment_generation": None}]},
            request_id=key + ":enroll", actor=principal)
        if attached.get("outcome") not in {"attached", "replayed"}:
            raise RuntimeError("portfolio enrollment did not complete: " + json.dumps(attached, default=str)[:400])
        relation = (session.owner.graph.current(ResourceRef(project.authority, project.kind, project.id))
                    .payload.get("metadata") or {}).get("otto_orchestrator")
    receipt["steps"]["enrollment"] = {"portfolio_ref": (relation or {}).get("portfolio_ref"),
                                      "supervisor_assignment_ref": (relation or {}).get("assignment_ref"),
                                      "queued": True}
    receipt["project_ref"] = session.owner.graph.current(ResourceRef(project.authority, project.kind, project.id)).ref.to_dict()
    receipt["lifecycle"] = "pending"
    return receipt


def import_history(session: Any, registration: Mapping[str, Any], *, note: str,
                   key: Optional[str] = None) -> dict[str, Any]:
    """Keep a CLOSED run as history: its whole run directory as documents.

    The run is registered on the same onboarding route (in the host's
    portfolio), marked mode=history, and then withdrawn. That is Otto's
    lifecycle for a project that ends without Otto completing it. It never
    ran in Otto, so it gets no tasks, roles, pools or schedules, and its
    documents are a read-only record.
    """
    run_id = registration["run_id"]
    key = key or "history:" + run_id + ":v1"
    existing = _registered_project(session, run_id)
    existing_facts = ((existing.payload.get("custom") or {}).get("otto_host_registration") or {}) if existing else {}
    if existing_facts.get("mode") == "history":
        current = session.owner.graph.current(ResourceRef(existing.ref.authority, existing.ref.kind, existing.ref.id))
        if current.lifecycle.value != "withdrawn":
            raise PermissionError("registered history is no longer withdrawn")
        # The stable history key represents one immutable import. A replay must
        # not try to revise a terminal project (or replace its original note).
        return {"schema": "otto.host-history-import.v1", "outcome": "replayed",
                "run_id": run_id, "request_key": key, "project_ref": current.ref.to_dict(),
                "lifecycle": current.lifecycle.value, "provider_called": False, "dispatch": False,
                "steps": {"registration": {"mode": "history", "outcome": "replayed",
                    "project_ref": current.ref.to_dict()}}}
    custom = dict(registration["custom"])
    facts = dict(custom["otto_host_registration"])
    facts.update(mode="history", activation_trigger=None,
                 history={"closed": True, "lifecycle": "withdrawn", "read_only": True, "note": note,
                          "meaning": "closed outside Otto; imported as the record of the run, never executed here"})
    custom["otto_host_registration"] = facts
    receipt = register(session, {**registration, "custom": custom,
                                 "title": "History: " + registration["title"]}, key=key)
    ref = ResourceRef.from_dict(receipt["project_ref"])
    current = session.owner.graph.current(ResourceRef(ref.authority, ref.kind, ref.id))
    if current.lifecycle.value != "withdrawn":
        session.owner.sheet.withdraw(current.ref, logical_request_key=key + ":withdraw",
                                     base_revision=current.ref.revision)
    current = session.owner.graph.current(ResourceRef(ref.authority, ref.kind, ref.id))
    session.owner.project_finished(current.ref)
    receipt.update(outcome="imported_history", lifecycle=current.lifecycle.value,
                   project_ref=current.ref.to_dict(), schema="otto.host-history-import.v1")
    receipt["steps"]["registration"] = {"custom": "otto_host_registration", "mode": "history",
                                        "tasks": 0, "roles": 0, "pools": 0, "schedules": 0}
    return receipt


def _check_in(session: Any, project_ref: Any, principal: str, key: str, edit: Any,
              opened: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
    if not opened or opened.get("outcome") not in {"opened", "replayed"}:
        opened = session.portfolio.checkout_project(project_ref, actor=principal, request_id=key + ":workspace")
    if opened.get("outcome") not in {"opened", "replayed"}:
        # The draft's onboarding workspace may still be open: reopen it (Otto's route).
        opened = session.portfolio.reopen_draft(actor=principal, project_ref=project_ref, request_id=key + ":reopen")
        opened = opened.get("open") or opened.get("workspace", {}).get("projection") or opened
    if opened.get("outcome") not in {"opened", "replayed"}:
        raise RuntimeError("workspace checkout failed: " + json.dumps(opened, default=str)[:400])
    draft = dict(opened["project_json"])
    edit(draft)
    done = session.portfolio.check_in_project(opened["project_ref"], session_id=opened["session_id"],
        project_json=draft, actor=principal, request_id=key + ":check-in")
    if done.get("outcome") not in {"finished", "replayed"}:
        raise RuntimeError("check-in did not complete: " + json.dumps(done, default=str)[:400])
    return done


def materialize(session: Any, record: Any, registration: Mapping[str, Any], *, key: Optional[str] = None) -> dict:
    """Activation step 1: create tasks, roles, pools and checks from Otto's documents.

    Nothing starts: the manager occurrence is prepared separately by the
    operating setup and launched only by an explicit start-manager.
    """
    from herzchen.content.instructions import validate_instruction_content
    from herzchen.kernel import LimitService
    from otto.attention import DueRecord, DurableAttention
    from otto.portfolio.resource_sync import normalize_instruction_contract
    run_id = registration["run_id"]
    key = key or "activate:" + run_id + ":v1"
    principal = session.host_principal()
    project = ResourceRef(record.ref.authority, record.ref.kind, record.ref.id)
    receipt: dict[str, Any] = {"schema": REGISTRATION_SCHEMA + ".activation", "run_id": run_id, "request_key": key,
                               "provider_called": False, "dispatch": False, "steps": {}}
    current = session.owner.graph.current(project)
    if not current.payload.get("tasks"):
        _check_in(session, current.ref.to_dict(), principal, key + ":tasks",
                  lambda draft: draft.update(outcome=registration["outcome"], tasks=list(registration["tasks"])))
        receipt["steps"]["tasks"] = {"outcome": "applied", "count": len(registration["tasks"])}
    else:
        receipt["steps"]["tasks"] = {"outcome": "replayed", "count": len(current.payload["tasks"])}
    project_record = session.owner.graph.current(project)
    project_ref = project_record.ref.to_dict()
    task_refs = _task_refs(session, project_record)
    receipt["steps"]["tasks"]["task_refs"] = task_refs
    # The task list is the registered source of acceptance criteria. Persist
    # those criteria as required assessment scopes on the exact owner tasks;
    # stable scope ids and logical request keys make activation replay safe.
    from herzchen.domains.assessment import AssessmentModule
    assessment = AssessmentModule(session.store, actor=session.owner.owner_actor)
    configured = ((registration.get("custom") or {}).get("otto_host_registration") or {}).get("assessment_scope") or {}
    aliases_by_task: dict[str, list[str]] = {}
    for pair in configured.get("task_criterion_pairs", ()) if isinstance(configured, Mapping) else ():
        if isinstance(pair, str) and pair.count("/") == 1:
            task_alias, criterion_alias = pair.split("/")
        elif isinstance(pair, Mapping) and set(pair) == {"task", "criterion"}:
            task_alias, criterion_alias = pair["task"], pair["criterion"]
        else:
            raise ValueError("assessment_accounting contains an invalid task/criterion pair")
        if not all(isinstance(value, str) and value.strip() for value in (task_alias, criterion_alias)):
            raise ValueError("assessment_accounting contains an empty task/criterion alias")
        aliases_by_task.setdefault(task_alias, []).append(criterion_alias)
    required_scopes = []
    for alias, raw_task_ref in task_refs.items():
        task_ref = ResourceRef.from_dict(raw_task_ref)
        task = session.owner.graph.current(task_ref)
        criterion_text = task.payload.get("acceptance")
        if not isinstance(criterion_text, str) or not criterion_text.strip():
            raise ValueError("registered task " + alias + " has no explicit proof criterion")
        criterion_aliases = aliases_by_task.get(alias) or [alias + "-criterion"]
        criterion_specs = [{"id": criterion_alias, "source_alias": criterion_alias,
                            "definition": criterion_text.strip()}
                           for criterion_alias in criterion_aliases]
        scope_id = "host-activation-" + hashlib.sha256((project.id + ":" + alias).encode()).hexdigest()[:24]
        scope = assessment.declare_scope(
            ResourceRef(project.authority, "assessment.scope", scope_id),
            parent_obligation=task.ref, protocol="otto-registered-run", criteria=criterion_specs,
            review_required=True, designated_approver=registration["manager"]["principal"],
            authority=project.authority, policy={"required_for_completion": True},
            logical_request_key=key + ":assessment-scope:" + alias, actor=session.owner.owner_actor)
        required_scopes.append({"task_ref": task.ref.to_dict(), "scope_ref": scope.ref.to_dict(),
                                "criterion_refs": [ref.to_dict() for ref in scope.criterion_refs]})
    receipt["steps"]["assessment_scopes"] = required_scopes
    # 3. Role configuration (the canonical slot -> adapter/model/effort record).
    configuration_ref = _document(session, project_ref, key + ":role-configuration", "role-configuration-" + project.id,
                                  registration["configuration"], "configuration")
    receipt["steps"]["role_configuration"] = configuration_ref
    # 4. Manager: BASE guide, assignment, adopted BASE, mandate. No Due.
    manager = registration["manager"]
    instructions = manager["brief"]
    name = "manager-base-" + project.id
    guide = {"schema": "herzchen.instructions.v1", "name": name, "entrypoint": "manager-brief.md",
             "bundle_digest": hashlib.sha256(instructions.encode()).hexdigest(),
             "export_manifest_digest": _digest(registration["raw_sha256"]), "required": True,
             "supporting_refs": [configuration_ref], "instructions": instructions}
    guide_ref = _document(session, project_ref, key + ":manager-guide", name, guide, "supporting")
    assignments = session.owner.assignments.command_port
    first_task = task_refs[manager["first_task"]]
    orchestrator = assignments.assign(ResourceRef.from_dict(project_ref), role="orchestrator", principal=principal,
        logical_request_key=key + ":orchestrator-assign", actor=session.actor)
    receipt["steps"]["orchestrator"] = {"principal": principal, "assignment_ref": orchestrator.ref.to_dict(),
                                        "generation": orchestrator.generation}
    base = assignments.assign(ResourceRef.from_dict(project_ref), role="manager", principal=manager["principal"],
        manager=principal, session=None, pins=[ResourceRef.from_dict(guide_ref)],
        logical_request_key=key + ":manager-assign", actor=session.actor)
    resources = [{"resource_ref": guide_ref, "resource_name": name,
                  "content_digest": validate_instruction_content(guide), "required": True}]
    assignment = base if base.payload.get("resource_adoptions") == resources else assignments.adopt_resources(
        base.ref, resources=resources, expected_revision=base.revision, expected_generation=base.generation,
        logical_request_key=key + ":manager-adopt", actor=session.binding.authenticated_actor(principal))
    contract = _manager_contract(first_task, manager["principal"], manager["worktree"], run_id)
    normalize_instruction_contract(contract)
    mandate_ref = _document(session, project_ref, key + ":manager-mandate", "manager-mandate-" + project.id, {
        "role": "manager", "scope_ref": project_ref, "status": "active", "dispatch_enabled": True,
        "task_ref": first_task, "assignment_ref": assignment.ref.to_dict(), "generation": assignment.generation,
        "brief": {"role": "manager", "mandate": "Manage " + run_id + " per manager-brief.md once the activation "
                  "trigger holds; the project stays pending until the orchestrator activates it."},
        "instruction_contract": contract}, "mandate")
    receipt["steps"]["manager"] = {"principal": manager["principal"], "assignment_ref": assignment.ref.to_dict(),
        "generation": assignment.generation, "status": getattr(assignment.status, "value", assignment.status),
        "guide_ref": guide_ref, "mandate_ref": mandate_ref, "task_ref": first_task,
        "binding": manager["binding"], "fresh_manager": True, "due": None}
    # 5. Finite allowances (kernel limit pools; nothing reserved or spent).
    limits = LimitService(session.store)
    pools = []
    for allowance in registration["allowances"]:
        pool_ref = ResourceRef(project.authority, "limit", project.id + "-" + allowance["id"])
        pool = limits.get_pool(pool_ref) or limits.create_pool(pool_ref, capacity_units=1,
            cumulative_allowance_units=allowance["units"], logical_request_key=key + ":pool:" + allowance["id"],
            actor=session.actor)
        pools.append({**allowance, "pool_ref": pool.ref.to_dict(), "capacity_units": pool.capacity_units,
                      "cumulative_allowance_units": pool.cumulative_allowance_units,
                      "remaining_allowance_units": pool.remaining_allowance_units})
    receipt["steps"]["allowances"] = pools
    # 6. Orchestrator checks: Due records owned by this host, paused (inactive).
    attention = DurableAttention(None, due_port=session.due_port, host_mode="durable-host")
    anchor = _now()
    schedules = []
    root = orchestrator
    for check in registration["checks"]:
        schedule_id = "check-" + project.id + "-" + _slug(check["id"])
        existing = session.due_port.read_due(schedule_id)
        if existing is None:
            record = DueRecord(schedule_id=schedule_id, recipient=principal,
                instruction="Orchestrator check " + check["id"] + " for " + run_id + ": " + (check.get("purpose") or ""),
                profile="read-only", anchor=anchor, last_covered_slot=0,
                invocation_identity=key + ":check:" + check["id"], interval_seconds=check["interval_seconds"],
                owner=session.actor.actor, project_ref=project.id, manager_ref=session.actor.actor,
                assignment_ref=root.ref.to_dict(), generation=root.generation, role="orchestrator",
                purpose="orchestrator-check", lifecycle_owner=session.actor.actor, host_state="paused",
                # No target yet: the orchestrator's conversation and the host
                # scheduler (Claude Code /loop or CronCreate) are bound at
                # activation by reconfiguring this record; nothing is invented.
                message=json.dumps({"check_id": check["id"], "cadence": check.get("cadence"),
                                    "scheduler": "bound at activation", "project_ref": project_ref},
                                   sort_keys=True))
            stored = attention.schedule(record, request_id=key + ":check:" + check["id"])["record"]
        else:
            stored = existing
        schedules.append({"id": check["id"], "schedule_id": schedule_id,
                          "interval_seconds": stored["interval_seconds"], "host_state": stored["host_state"],
                          "stop_state": stored["stop_state"], "version": stored["version"]})
    receipt["steps"]["orchestrator_checks"] = schedules
    receipt["project_ref"] = session.owner.graph.current(ResourceRef(project.authority, project.kind, project.id)).ref.to_dict()
    receipt["lifecycle"] = session.owner.graph.current(ResourceRef(project.authority, project.kind, project.id)).lifecycle.value
    return receipt


def _registered_project(session: Any, run_id: str) -> Any:
    from .cli import _project_records
    for record in _project_records(session):
        custom = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
        if custom.get("run_id") == run_id:
            return record
    return None


def _registered_bundle(session: Any, source_bundle: str) -> Any:
    """Find a registered source directory even if its run id was later edited."""
    from .cli import _project_records
    source = Path(source_bundle).resolve()
    for record in _project_records(session):
        facts = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
        registered = facts.get("source_bundle")
        if registered and Path(registered).resolve() == source:
            return record
    return None


def _task_refs(session: Any, project_record: Any) -> dict[str, Any]:
    refs = {}
    for raw in project_record.payload.get("tasks", ()):
        task_ref = ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
        task = session.owner.graph.current(ResourceRef(task_ref.authority, task_ref.kind, task_ref.id))
        alias = task.payload.get("alias") or task.payload.get("id") or task.ref.id
        refs[alias] = task.ref.to_dict()
    return refs


def stored_bundle(session: Any, record: Any) -> dict:
    """Otto's stored copies of the run's files, parsed as a bundle (activation input)."""
    from herzchen.content import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService
    from otto.portfolio.documents import ProjectDocumentReader
    from .bundle import parse_files
    reader = ProjectDocumentReader(sheet_reader=session.owner.sheet, content_reader=session.owner.content,
        visibility_reader=ContextPacketService(session.store.domain_handler((content_contribution(),))))
    actor = session.binding.authenticated_actor(session.host["principal"]) if session.host else session.owner.owner_actor
    documents = reader.list_documents(record.ref.to_dict(), actor=actor)["documents"]
    files = {}
    for row in documents:
        path = next((m.get("key") for m in row.get("memberships") or () if m.get("namespace") == "project.files"), None)
        if path is not None:
            files[path] = session.owner.content.read(ResourceRef.from_dict(row["current_revision_ref"]))["content"]
    return parse_files(files)
