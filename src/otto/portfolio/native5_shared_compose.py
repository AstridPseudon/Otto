"""Finite post-sync Native5 state projection and root-client qualification.

This source-ready module is intended for the pinned installed
``otto.portfolio`` package used by the existing shared owner composition. It
never opens a Store, creates a project, starts a manager, or changes
worker/native state. Call it only after the maintained direction-sync phase
has returned and the same owner can read its fresh root joins.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

# The five fixed project IDs are the transferred Native5 set; startup refuses any other set.
FIVE_IDS = frozenset({
    "project-4086b37edbac246a01274cc80fd3",
    "project-628826ccc18b1111d407a501cfc8",
    "project-8ca73fedf3c62a20eb7951b338cd",
    "project-49be5a14a003f60ab0ed1ca31890",
    "project-1b335cebc6d69a6c9ac919252119",
})


def _identity(ref: Mapping[str, Any]) -> tuple[str, str, str]:
    if not isinstance(ref, Mapping) or not all(isinstance(ref.get(k), str) for k in ("authority", "kind", "id")):
        raise PermissionError("canonical resource identity required")
    return ref["authority"], ref["kind"], ref["id"]


def _root(owner: Any) -> Any:
    root = owner.assignments.get(owner.queue_binding["root"])
    if (root.role != "orchestrator" or root.principal != owner.owner_actor.actor
            or root.generation < 1):
        raise PermissionError("current authenticated owner root required")
    return root


def _current_joins(owner: Any, root: Any) -> dict[str, Any]:
    from herzchen.contracts import ResourceRef
    rows = owner.store.consumer().find_identity_refs(kind="work.project", payload_matches={
        ("metadata", "otto_orchestrator", "assignment_ref", "authority"): root.ref.authority,
        ("metadata", "otto_orchestrator", "assignment_ref", "kind"): root.ref.kind,
        ("metadata", "otto_orchestrator", "assignment_ref", "id"): root.ref.id,
    })
    if len(rows) > 16:
        raise PermissionError("current root join query exceeds the existing finite project cap")
    projects: dict[str, Any] = {}
    for raw in rows:
        project = owner.graph.current(raw if isinstance(raw, ResourceRef) else ResourceRef.from_dict(raw))
        relation = (project.payload.get("metadata") or {}).get("otto_orchestrator") or {}
        if (relation.get("assignment_ref") != root.ref.to_dict()
                or relation.get("generation") != root.generation
                or relation.get("assignment_revision") != root.ref.revision
                or _identity(relation.get("portfolio_ref", {})) != _identity(root.scope.to_dict())):
            raise PermissionError("root join is stale or belongs to another generation")
        if project.ref.id in projects:
            raise PermissionError("duplicate current root project join")
        projects[project.ref.id] = project
    if len(projects) != 9:
        raise PermissionError("the synchronized root must have exactly nine current project joins")
    return projects


def _supervision_only_project_chain(owner: Any, root: Any, old_ref: Mapping[str, Any],
                                    new_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Prove a project revision change is only the existing root join refresh.

    This mirrors the maintained completion-project bridge: one unambiguous
    authenticated project-supervision transfer per revision, paired with the
    exact same-root resource adoption. It does not authorize task or policy
    changes.
    """
    from herzchen.contracts import ResourceRef
    old = ResourceRef.from_dict(old_ref)
    target = ResourceRef.from_dict(new_ref)
    if ((old.authority, old.kind, old.id) != (target.authority, target.kind, target.id)
            or old.kind != "work.project" or not old.revision or not target.revision):
        raise PermissionError("supplement project refresh changed project identity")
    if old == target:
        return {"from": old.to_dict(), "to": target.to_dict(), "event_ids": [],
                "root_adoption_event_ids": []}
    events = owner.graph.reader.list_events(stream="work:" + old.id)
    by_subject: dict[Any, list[Any]] = {}
    for event in events:
        by_subject.setdefault(event.subject, []).append(event)
    cursor, chain = target, []
    while cursor != old:
        matches = by_subject.get(cursor, ())
        if len(matches) != 1 or len(chain) >= 32:
            raise PermissionError("supplement refresh ancestry is missing or ambiguous")
        event = matches[0]
        effects = event.effects
        before, after = effects.get("from_assignment"), effects.get("to_assignment")
        relation = effects.get("supervision", {})
        allowed = {"from_assignment", "to_assignment", "supervision", "root_resource_refresh"}
        history = effects.get("history_summary")
        if history is not None:
            from herzchen.kernel.history import HISTORY_SCHEMA
            if not isinstance(history, Mapping) or history.get("schema") != HISTORY_SCHEMA:
                raise PermissionError("supplement refresh history summary is invalid")
            allowed.add("history_summary")
        if (event.event_type != "work.project.supervision-transferred"
                or event.operation != "work.project.supervision.transfer"
                or not isinstance(before, Mapping) or not isinstance(after, Mapping)
                or any(before.get(k) != after.get(k) for k in ("authority", "kind", "id"))
                or before == after or relation.get("assignment_ref") != after
                or relation.get("project_ref") != cursor.to_dict()
                or relation.get("generation") != root.generation
                or relation.get("portfolio_ref") != root.scope.to_dict()
                or not event.actor.authenticated or event.actor.actor != root.principal
                or set(effects) - allowed):
            raise PermissionError("supplement project changed beyond authenticated root supervision refresh")
        root_events = owner.graph.reader.list_events(stream="assignment:" + after["id"])
        adopted = [row for row in root_events if row.subject == ResourceRef.from_dict(after)
                   and row.event_type == "work.assignment.resources-adopted"]
        payload = adopted[0].effects.get("result_payload", {}) if len(adopted) == 1 else {}
        if (len(adopted) != 1 or adopted[0].actor != event.actor
                or payload.get("resource_adoption_base_ref") != before
                or payload.get("role") != "orchestrator"
                or payload.get("principal") != root.principal
                or payload.get("generation") != root.generation
                or payload.get("scope") != root.scope.to_dict()):
            raise PermissionError("supplement project refresh lacks exact same-root adoption proof")
        bases = [ref for ref in event.before_refs
                 if (ref.authority, ref.kind, ref.id) == (old.authority, old.kind, old.id)]
        if len(bases) != 1 or bases[0] == cursor or any(item[0] == bases[0] for item in chain):
            raise PermissionError("supplement project refresh predecessor is invalid")
        chain.append((cursor, event.event_id, adopted[0].event_id))
        cursor = bases[0]
    return {"from": old.to_dict(), "to": target.to_dict(),
            "event_ids": [item[1] for item in reversed(chain)],
            "root_adoption_event_ids": [item[2] for item in reversed(chain)]}


def _refresh_pending_supplements(owner: Any, root: Any, state: dict[str, Any],
                                 current_project: Any) -> None:
    """Refresh only pending task bindings after an authenticated root sync.

    Completed-task supplements are immutable history and remain byte-for-byte
    unchanged. For pending tasks only the project revision in the binding is
    projected forward; policy, task, criterion, pool, allocation receipt,
    manager lineage, and allowance are all revalidated and retained.
    """
    supplements = state.get("task_assessment_supplements", {})
    if supplements is None:
        return
    if not isinstance(supplements, Mapping) or len(supplements) > 64:
        raise PermissionError("task supplement map is malformed or exceeds its bound")
    if not supplements:
        return
    from herzchen.contracts import ResourceRef
    from .local_assessment_policy import LocalAssessmentPolicy
    from .operating_setup import authenticated_adoption_ancestor
    task_refs = state.get("task_refs")
    if not isinstance(task_refs, Mapping):
        raise PermissionError("current configured task pins are unavailable for supplement refresh")
    refreshed = deepcopy(dict(supplements))
    provenance = deepcopy(state.get("task_assessment_supplement_refresh_provenance", {}))
    if not isinstance(provenance, Mapping) or len(provenance) > 64:
        raise PermissionError("supplement refresh provenance is malformed")
    provenance = deepcopy(dict(provenance))
    for alias, supplemental in supplements.items():
        if alias not in task_refs or not isinstance(supplemental, Mapping) or set(supplemental) != {"policy", "binding"}:
            raise PermissionError("supplement must bind one configured task with exact policy and binding")
        task_ref = ResourceRef.from_dict(task_refs[alias])
        task = owner.graph.reader.get_identity(task_ref)
        if task is None or task.ref != task_ref:
            raise PermissionError("supplement task pin is missing or stale")
        lifecycle = getattr(task, "lifecycle", None) or task.payload.get("lifecycle")
        lifecycle = getattr(lifecycle, "value", lifecycle)
        if lifecycle == "completed":
            # Historic accepted/rework policy pins must not be migrated.
            continue
        if lifecycle != "pending":
            raise PermissionError("only a genuinely pending task supplement can be refreshed")
        binding = supplemental["binding"]
        if not isinstance(binding, Mapping) or set(binding) != {
                "project_ref", "task_ref", "criterion_refs", "assignment_ref", "generation",
                "principal", "pool_ref", "allocation_key"}:
            raise PermissionError("pending supplement binding has an unexpected shape")
        old_project = ResourceRef.from_dict(binding["project_ref"])
        if (old_project.to_dict() != state.get("project_ref")
                or binding.get("task_ref") != task_ref.to_dict()
                or _identity(old_project.to_dict()) != _identity(current_project.ref.to_dict())):
            raise PermissionError("pending supplement is not bound to the prior same task/project")
        assignment_ref = ResourceRef.from_dict(state["assignment_ref"])
        assignment = owner.assignments.command_port.get(assignment_ref)
        prior_assignment = binding.get("assignment_ref")
        if (assignment.ref.to_dict() != state["assignment_ref"] or assignment.role != "manager"
                or assignment.principal != state.get("manager")
                or assignment.generation != state.get("manager_generation")
                or _identity(assignment.scope.to_dict()) != _identity(current_project.ref.to_dict())
                or binding.get("principal") != assignment.principal
                or binding.get("generation") != assignment.generation
                or not isinstance(prior_assignment, Mapping)
                or not authenticated_adoption_ancestor({"ref": assignment.ref.to_dict(),
                    "principal": assignment.principal, "role": assignment.role,
                    "generation": assignment.generation, "payload": assignment.payload},
                    prior_assignment, owner.graph.reader)):
            raise PermissionError("pending supplement manager lineage changed")
        current_state = {**state, "project_ref": current_project.ref.to_dict()}
        policy = LocalAssessmentPolicy.from_run_config(supplemental["policy"], state=current_state)
        base = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=current_state)
        if policy.scope_project_ref != current_project.ref:
            raise PermissionError("pending supplement policy project pin is stale")
        selected_pairs = tuple(pair for pair in base.task_criterion_pairs if pair[0] == task_ref)
        if (not selected_pairs or set(policy.task_criterion_pairs) != set(selected_pairs)
                or any(pair[0] != task_ref for pair in policy.task_criterion_pairs)
                or binding.get("criterion_refs") != [criterion.to_dict() for _, criterion in policy.task_criterion_pairs]
                or binding.get("pool_ref") != policy.pool_ref.to_dict()
                or not isinstance(binding.get("allocation_key"), str)):
            raise PermissionError("pending supplement task, criteria, or pool binding changed")
        receipt = owner.graph.reader.get_receipt(binding["allocation_key"])
        if (receipt is None or getattr(receipt.status, "value", receipt.status) != "committed"
                or (receipt.target.authority, receipt.target.kind, receipt.target.id)
                   != (policy.pool_ref.authority, policy.pool_ref.kind, policy.pool_ref.id)):
            raise PermissionError("pending supplement allocation receipt is missing or foreign")
        pool_row = owner.graph.reader.get_identity_bounded(policy.pool_ref, max_record_bytes=8192)["record"]
        if (pool_row is None or pool_row.ref != policy.pool_ref
                or pool_row.payload.get("capacity_units") != policy.capacity_units
                or pool_row.payload.get("cumulative_allowance_units") != policy.cumulative_allowance_units):
            raise PermissionError("pending supplement pool capacity or allowance changed")
        policy.validate_binding(current_project.ref, task_ref, owner.graph.reader)
        if old_project == current_project.ref:
            prior_proof = provenance.get(alias)
            if prior_proof is not None and prior_proof.get("to_binding") != dict(binding):
                raise PermissionError("retained pending supplement refresh proof changed")
            continue
        chain = _supervision_only_project_chain(owner, root, old_project.to_dict(), current_project.ref.to_dict())
        updated = deepcopy(dict(supplemental))
        updated_binding = deepcopy(dict(binding))
        updated_binding["project_ref"] = current_project.ref.to_dict()
        updated["binding"] = updated_binding
        refreshed[alias] = updated
        prior_proof = provenance.get(alias)
        proof = {"schema": "otto.pending-task-supplement-project-refresh.v1",
                 "task_ref": task_ref.to_dict(), "from_binding": deepcopy(dict(binding)),
                 "to_binding": deepcopy(updated_binding), "supervision_chain": chain,
                 "policy_unchanged": True, "pool_unchanged": True, "allocation_reused": True}
        if prior_proof is not None and prior_proof != proof:
            raise PermissionError("retained pending supplement refresh proof changed")
        provenance[alias] = proof
    state["task_assessment_supplements"] = refreshed
    if provenance:
        state["task_assessment_supplement_refresh_provenance"] = provenance


def _fresh_state(owner: Any, root: Any, project: Any, state: Mapping[str, Any], *, old_view: bool) -> dict[str, Any]:
    from herzchen.contracts import ResourceRef
    out = deepcopy(dict(state))
    if _identity(out.get("project_ref", {})) != _identity(project.ref.to_dict()):
        raise PermissionError("state project identity differs from its authenticated current join")
    assignment_ref = out.get("assignment_ref")
    if not isinstance(assignment_ref, dict):
        raise PermissionError("current fixed manager assignment pin is required")
    assignment = owner.assignments.get(ResourceRef.from_dict(assignment_ref))
    if (assignment.ref.to_dict() != assignment_ref or assignment.role != "manager"
            or assignment.principal != out.get("manager")
            or assignment.generation != out.get("manager_generation")
            or _identity(assignment.scope.to_dict()) != _identity(project.ref.to_dict())):
        raise PermissionError("fixed manager identity, role, project, or generation changed")
    previous_root = out.get("orchestrator_assignment_ref")
    if previous_root is None or _identity(previous_root) != _identity(root.ref.to_dict()):
        raise PermissionError("fixed view is not bound to this root identity")
    previous_help = out.get("root_help_binding") or {}
    if (previous_help.get("principal") != root.principal
            or _identity(previous_help.get("assignment_ref", {})) != _identity(root.ref.to_dict())
            or previous_help.get("generation") != root.generation
            or previous_help.get("conversation_ref") != root.session):
        raise PermissionError("fixed help projection is not authenticated to the current root")
    if old_view:
        _refresh_pending_supplements(owner, root, out, project)
    # Project revision and root revision may advance during the ordinary
    # direction synchronization. These are projections of the same identity;
    # manager/worker/Due pins are intentionally left untouched.
    out["project_ref"] = project.ref.to_dict()
    out["orchestrator_assignment_ref"] = root.ref.to_dict()
    out["orchestrator_generation"] = root.generation
    out["root_help_binding"] = {**previous_help, "assignment_ref": root.ref.to_dict(),
        "generation": root.generation, "project_ref": project.ref.to_dict()}
    out["current_root_projection_refreshed"] = True
    out["projection_only"] = True
    out["provider_called"] = False
    out["manager_started"] = False
    return out


def build_nine_state_map(owner: Any, *, root_views: Mapping[str, Any],
                         existing_controllers: Mapping[str, str],
                         new_manager_states: Mapping[str, Mapping[str, Any]],
                         controllers: Mapping[str, str], workspace_rows: Mapping[str, Mapping[str, Any]],
                         expected_synchronized_root_ref: Mapping[str, Any],
                         persist: bool = False) -> dict[str, Any]:
    """Validate nine canonical states and refresh the four old projections.

    ``root_views`` is the four existing root-owned views by stable view name;
    an independent Astrid view must be passed separately and is never folded
    into this map. This operation is post-sync: it requires the exact nine
    canonical joins after the root revision advanced.
    """
    if set(new_manager_states) != set(FIVE_IDS) or set(controllers) != set(FIVE_IDS) or set(workspace_rows) != set(FIVE_IDS):
        raise PermissionError("exact five Native5 states, controllers, and workspace rows are required")
    if len(root_views) != 4 or "astrid" in root_views or set(existing_controllers) != set(root_views):
        raise PermissionError("exactly four existing root views are required; Astrid remains a separate view")
    root = _root(owner)
    if root.ref.to_dict() != dict(expected_synchronized_root_ref):
        raise PermissionError("root synchronization receipt does not match the current full root revision")
    projects = _current_joins(owner, root)
    old_ids = {service.server.state.get("project_ref", {}).get("id") for service in root_views.values()}
    if None in old_ids or len(old_ids) != 4 or old_ids & set(FIVE_IDS):
        raise PermissionError("four existing root-owned fixed view identities required")
    if set(projects) != old_ids | set(FIVE_IDS):
        raise PermissionError("current root join set differs from the existing four plus exact Native5")

    # The manager support pins are borrowed from the existing qualified root
    # view. Verify their exact immutable reads and keep their names explicit in
    # each new packet; do not treat the opaque source-support list as proof.
    if "onboarding" not in root_views:
        raise PermissionError("existing onboarding root view is required as the support-pin source")
    onboarding = root_views["onboarding"].server.state
    support_names = ("selected_pack_ref", "native_evidence_selection_ref", "bounded_host_policy_ref")
    support_refs = [onboarding.get(key) for key in support_names]
    if any(not isinstance(ref, dict) for ref in support_refs) or len({_identity(ref) for ref in support_refs}) != 3:
        raise PermissionError("existing root support pins are missing or ambiguous")
    from herzchen.contracts import ResourceRef
    for ref in support_refs:
        ref_obj = ResourceRef.from_dict(ref)
        immutable = owner.content.read(ref_obj)
        if immutable.get("identity") != ref_obj:
            raise PermissionError("selected support content read returned a different immutable identity")

    states_by_project: dict[str, dict[str, Any]] = {}
    controllers_by_project: dict[str, str] = {}
    refresh: dict[str, dict[str, Any]] = {}
    for name, service in root_views.items():
        previous = service.server.state
        ident = previous["project_ref"]["id"]
        updated = _fresh_state(owner, root, projects[ident], previous, old_view=True)
        states_by_project[ident] = updated
        controller = str(existing_controllers.get(name, ""))
        if not controller or not __import__("pathlib").Path(controller).is_absolute():
            raise PermissionError("existing root fixed view controller pin is unavailable")
        controllers_by_project[ident] = controller
        refresh[name] = updated
    historical_due_reads: dict[str, Any] = {}
    for name, service in root_views.items():
        if not callable(getattr(service, "_current_manager_schedule", None)):
            historical_due_reads[name] = {"outcome": "unavailable", "reason": "fixed service exposes no maintained current schedule reader",
                "read_only": True, "current_executable_context_claimed": False, "manager_starts": 0}
            continue
        schedule = service._current_manager_schedule()
        if not isinstance(schedule, str) or not schedule:
            historical_due_reads[name] = {"outcome": "unavailable", "reason": "no retained current schedule pin",
                "read_only": True, "current_executable_context_claimed": False, "manager_starts": 0}
            continue
        due = service.server.due_port.read_due(schedule)
        state = refresh[name]
        if (not isinstance(due, dict) or due.get("assignment_ref") != state.get("assignment_ref")
                or due.get("generation") != state.get("manager_generation")
                or _identity((due.get("target") or {}).get("project_ref", {})) != _identity(state["project_ref"])):
            raise PermissionError("retained existing Due belongs to a stale or foreign manager context")
        terminal = due.get("completion_state") in {"succeeded", "failed", "cancelled", "timed_out"} or due.get("last_result") is not None
        historical_due_reads[name] = {"schedule_id": schedule, "completion_state": due.get("completion_state"),
            "terminal_evidence_present": bool(terminal), "read_only": True,
            "current_executable_context_claimed": False, "manager_starts": 0}
    packets: dict[str, dict[str, Any]] = {}
    for ident, raw in new_manager_states.items():
        state = _fresh_state(owner, root, projects[ident], raw, old_view=False)
        workspace = workspace_rows[ident]
        controller = controllers[ident]
        if (not isinstance(controller, str) or not controller
                or str(workspace.get("controller_state_directory", "")) != controller
                or state.get("runtime_controller") != controller
                or state.get("source_path") != workspace.get("workspace")
                or state.get("run_id") != workspace.get("run_id")):
            raise PermissionError("Native5 run/workspace/controller pins are not the exact prepared inputs")
        support = ("selected_pack_ref", "native_evidence_selection_ref", "bounded_host_policy_ref")
        if any(not isinstance(state.get(key), dict) for key in support):
            raise PermissionError("Native5 packet is missing a concrete source/evidence/host-policy pin")
        if [state[key] for key in support_names] != state.get("source_support_refs") or [state[key] for key in support_names] != support_refs:
            raise PermissionError("named Native5 support pins differ from the adopted source list")
        if not isinstance(state.get("requested_model"), str) or not isinstance(state.get("requested_reasoning"), str):
            raise PermissionError("Native5 model and reasoning pins are required")
        import re
        if (not re.fullmatch(r"[0-9a-f]{40,64}", str(state.get("source_commit", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(state.get("workspace_spec_sha256", "")))
                or not re.fullmatch(r"[0-9a-f]{40,64}", str(state.get("worktree_head", "")))
                or not re.fullmatch(r"[0-9a-f]{40,64}", str(state.get("integration_owner_head", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(state.get("tool_entrypoint_sha256", "")))):
            raise PermissionError("Native5 source, workspace, worktree, integration, or entrypoint digest pin is invalid")
        packet = {key: state.get(key) for key in (
            "project_ref", "assignment_ref", "manager_generation", "manager", "guide_ref", "mandate_ref",
            "manager_direction_ref", *support, "source_support_refs", "run_id", "run_directory",
            "registered_run_directory", "bundle_sha256", "worktree_root", "worktree_head",
            "integration_owner_worktree", "integration_owner_head", "tool_entrypoint",
            "tool_entrypoint_sha256", "source_path", "workspace", "runtime_controller", "requested_model",
            "requested_reasoning", "schedule_id", "logical_request_key", "task_refs", "criterion_refs",
            "assessment_policy", "root_help_binding", "orchestrator_assignment_ref", "source_commit",
            "workspace_spec_sha256")}
        packet.update({"root_assignment_ref": root.ref.to_dict(), "root_generation": root.generation,
            "root_conversation_ref": root.session, "current_project_join_ref": projects[ident].ref.to_dict(),
            "canonical_state_projection": deepcopy(state),
            "state": "prepared-not-started", "provider_called": False, "dispatch": False,
            "manager_starts": 0, "activation": False})
        packets[ident] = packet
        states_by_project[ident] = state
        controllers_by_project[ident] = controller
    if set(states_by_project) != set(projects) or len(controllers_by_project) != 9:
        raise PermissionError("the final canonical state/controller map is not exactly nine")
    source_commits = {state.get("source_commit") for state in new_manager_states.values()}
    if len(source_commits) != 1 or not isinstance(next(iter(source_commits)), str):
        raise PermissionError("Native5 states must share one exact setup source commit")
    source_commit = next(iter(source_commits))
    if len(source_commit) not in {40, 64} or any(char not in "0123456789abcdef" for char in source_commit):
        raise PermissionError("Native5 setup source commit is malformed")
    # No mutation occurs before all nine states and pins pass validation.
    if persist:
        for name, service in root_views.items():
            service.server.state.clear()
            service.server.state.update(refresh[name])
        for name, service in root_views.items():
            service.server._save_state()
    return {"schema": "otto.native-five-nine-state-map.v1", "root_assignment_ref": root.ref.to_dict(),
        "root_generation": root.generation, "root_conversation_ref": root.session,
        "source_commit": source_commit,
        "project_ids": sorted(projects), "current_join_refs": {k: v.ref.to_dict() for k, v in projects.items()},
        "states_by_project": states_by_project, "controllers_by_project": controllers_by_project,
        "refreshed_existing_root_views": refresh, "prepared_native_five_packets": packets,
        "historical_existing_due_reads": historical_due_reads,
        "independent_secondary_views_touched": False, "manager_resource_mutations": 0,
        "worker_mutations": 0, "native_starts": 0, "provider_called": False, "dispatch": False}


def load_prepared_native_five_packets(packet_document: Mapping[str, Any], *, owner: Any,
                                      installed_source_commit: str,
                                      installed_pack_hashes: Mapping[str, str]) -> dict[str, Any]:
    """Read a retained setup packet into the existing shared compose map.

    The caller supplies the already-open authenticated owner and installed
    manifest pins. This is a bounded projection only; it does not read or
    rewrite resources beyond exact current assignment/project/content refs.
    """
    if isinstance(packet_document, Mapping) and isinstance(packet_document.get("native_five_state_map"), Mapping):
        packet_document = packet_document["native_five_state_map"]
    root = _root(owner)
    if (not isinstance(packet_document, Mapping)
            or packet_document.get("schema") != "otto.native-five-nine-state-map.v1"
            or packet_document.get("root_assignment_ref") != root.ref.to_dict()
            or packet_document.get("root_generation") != root.generation
            or len(packet_document.get("prepared_native_five_packets", {})) != 5):
        raise PermissionError("retained packet must match the full current synchronized root revision")
    if not isinstance(installed_source_commit, str) or not installed_source_commit:
        raise PermissionError("exact installed source commit required")
    projects = _current_joins(owner, root)
    ids = set(packet_document["prepared_native_five_packets"])
    if ids != set(FIVE_IDS) or not ids.issubset(projects):
        raise PermissionError("retained packets do not cover the exact current Native5 joins")
    states: dict[str, dict[str, Any]] = {}
    controllers: dict[str, str] = {}
    for ident, packet in packet_document["prepared_native_five_packets"].items():
        state = packet.get("canonical_state_projection")
        if (not isinstance(state, dict) or packet.get("source_commit") != installed_source_commit
                or state.get("source_commit") != installed_source_commit
                or packet.get("root_assignment_ref") != root.ref.to_dict()
                or packet.get("root_generation") != root.generation
                or packet.get("current_project_join_ref") != projects[ident].ref.to_dict()
                or state.get("project_ref") != projects[ident].ref.to_dict()
                or packet.get("state") != "prepared-not-started"):
            raise PermissionError("Native5 packet is stale, foreign, or not an exact installed source")
        if packet.get("selected_pack_ref") != state.get("selected_pack_ref"):
            raise PermissionError("Native5 pack pin differs between packet and canonical state")
        from herzchen.contracts import ResourceRef
        pack_ref = ResourceRef.from_dict(packet["selected_pack_ref"])
        pack = owner.content.read(pack_ref)
        if pack.get("identity") != pack_ref:
            raise PermissionError("selected pack immutable read differs")
        if pack.get("content", {}).get("file_sha256") != dict(installed_pack_hashes):
            raise PermissionError("selected pack bytes differ from the exact installed manifest pins")
        selection_ref = packet.get("native_evidence_selection_ref")
        policy_ref = packet.get("bounded_host_policy_ref")
        if (not isinstance(selection_ref, dict) or not isinstance(policy_ref, dict)
                or packet.get("source_support_refs") != [packet.get("selected_pack_ref"), selection_ref, policy_ref]):
            raise PermissionError("Native5 packet lacks exact named evidence/policy source pins")
        for ref in (selection_ref, policy_ref):
            ref_obj = ResourceRef.from_dict(ref)
            if owner.content.read(ref_obj).get("identity") != ref_obj:
                raise PermissionError("native evidence or host-policy immutable read differs")
        selection_content = owner.content.read(ResourceRef.from_dict(selection_ref)).get("content", {})
        expected_context_commit = installed_source_commit
        if selection_content.get("runtime_source_commit") != expected_context_commit:
            raise PermissionError("native evidence selection was qualified for a different installed source")
        policy_content = owner.content.read(ResourceRef.from_dict(policy_ref)).get("content", {})
        if (policy_content.get("manager_max"), policy_content.get("productive_worker_max"),
                policy_content.get("total_native_max")) != (3, 2, 3):
            raise PermissionError("Native5 bounded host policy differs from the currently qualified shared cap")
        assignment = owner.assignments.get(state["assignment_ref"])
        if (assignment.ref.to_dict() != state["assignment_ref"]
                or assignment.role != "manager" or assignment.principal != state.get("manager")
                or assignment.generation != state.get("manager_generation")):
            raise PermissionError("Native5 manager assignment changed since packet creation")
        guide_ref = ResourceRef.from_dict(state["guide_ref"])
        guide_read = owner.content.read(guide_ref)
        guide_content = guide_read.get("content")
        from herzchen.content.instructions import validate_instruction_content
        guide_adoptions = [row for row in assignment.payload.get("resource_adoptions", [])
            if row.get("required") is True and row.get("resource_ref") == guide_ref.to_dict()
            and row.get("content_digest") == validate_instruction_content(guide_content)]
        if len(guide_adoptions) != 1:
            raise PermissionError("Native5 required manager BASE is not an exact adopted content pin")
        mandate_ref = ResourceRef.from_dict(state["mandate_ref"])
        mandate_read = owner.content.read(mandate_ref)
        mandate_content = mandate_read.get("content") or {}
        if (mandate_read.get("identity") != mandate_ref
                or mandate_content.get("assignment_ref") != assignment.ref.to_dict()
                or mandate_content.get("generation") != assignment.generation
                or _identity(mandate_content.get("scope_ref", {})) != _identity(projects[ident].ref.to_dict())):
            raise PermissionError("Native5 mandate is not bound to its current manager/project")
        direction_ref = state.get("manager_direction_ref")
        direction_obj = ResourceRef.from_dict(direction_ref)
        if owner.content.read(direction_obj).get("identity") != direction_obj:
            raise PermissionError("Native5 manager direction pin is unavailable")
        direction = owner.direction_surface().read(ResourceRef.from_dict(assignment.payload["responsibility_ref"]),
            assignment_ref=assignment.ref, generation=assignment.generation)
        if direction.get("effective_ref") != direction_obj.to_dict():
            raise PermissionError("Native5 manager direction is not the current assigned context")
        from pathlib import Path
        controller = state.get("runtime_controller")
        if not isinstance(controller, str) or not Path(controller).is_absolute():
            raise PermissionError("Native5 controller-state path is not explicit and absolute")
        if (not state.get("workspace") or not state.get("source_path") or not state.get("run_id")
                or not state.get("requested_model") or not state.get("requested_reasoning")
                or not state.get("schedule_id")):
            raise PermissionError("Native5 execution provenance is incomplete")
        states[ident] = deepcopy(state)
        controllers[ident] = controller
    return {"states": states, "controllers": controllers,
        "project_ids": sorted(ids), "root_assignment_ref": root.ref.to_dict(),
        "root_generation": root.generation, "source_commit": installed_source_commit,
        "provider_called": False, "manager_starts": 0, "dispatch": False}


def merge_packets_for_shared_compose(existing_states: Mapping[str, Mapping[str, Any]],
                                    controllers: Mapping[str, Any], *, packet_document: Mapping[str, Any],
                                    owner: Any, installed_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the generic ``states``/``controllers`` maps used by shared compose.

    Invoke immediately after the authenticated owner is opened and before the
    existing ``for key, state in states.items()`` service-construction loop.
    The unrelated Astrid view remains in its existing map and is separately
    supervised; no policy or project operation is granted for it here.
    """
    root = _root(owner)
    existing = {key: deepcopy(dict(value)) for key, value in existing_states.items()}
    paths = dict(controllers)
    if set(existing) - {"astrid"} != {"onboarding", "vision", "retention", "claude"}:
        raise PermissionError("shared compose needs the exact existing four Otto views")
    if set(paths) != set(existing):
        raise PermissionError("controller map must exactly match the existing service-state map")
    root_ids: set[str] = set()
    for name in ("onboarding", "vision", "retention", "claude"):
        state = existing[name]
        project_ref = state.get("project_ref")
        project = owner.graph.current(__import__("herzchen.contracts", fromlist=["ResourceRef"]).ResourceRef.from_dict(project_ref))
        relation = (project.payload.get("metadata") or {}).get("otto_orchestrator") or {}
        if (project.ref.to_dict() != project_ref or relation.get("assignment_ref") != root.ref.to_dict()
                or relation.get("generation") != root.generation
                or state.get("orchestrator_assignment_ref") != root.ref.to_dict()
                or state.get("root_help_binding", {}).get("assignment_ref") != root.ref.to_dict()
                or state.get("root_help_binding", {}).get("generation") != root.generation
                or state.get("root_help_binding", {}).get("project_ref") != project.ref.to_dict()):
            raise PermissionError("existing Otto state projection is not refreshed from the current canonical root join")
        root_ids.add(project.ref.id)
    if len(root_ids) != 4:
        raise PermissionError("existing Otto view identities must be unique")
    if "astrid" in existing:
        state = existing["astrid"]
        project = owner.graph.current(__import__("herzchen.contracts", fromlist=["ResourceRef"]).ResourceRef.from_dict(state["project_ref"]))
        relation = (project.payload.get("metadata") or {}).get("otto_orchestrator") or {}
        if (project.ref.to_dict() != state["project_ref"] or relation.get("assignment_ref") == root.ref.to_dict()
                or state.get("root_help_binding", {}).get("assignment_ref") != relation.get("assignment_ref")
                or state.get("root_help_binding", {}).get("generation") != relation.get("generation")):
            raise PermissionError("independent Astrid supervision must remain separately current")
    loaded = load_prepared_native_five_packets(packet_document, owner=owner,
        installed_source_commit=installed_manifest.get("source_commit"),
        installed_pack_hashes=installed_manifest.get("pack_hashes", {}))
    if root_ids & set(loaded["states"]):
        raise PermissionError("Native5 packet project duplicates an existing view")
    states_by_id = {state["project_ref"]["id"]: state for name, state in existing.items() if name != "astrid"}
    states_by_id.update(loaded["states"])
    if set(states_by_id) != set(_current_joins(owner, root)):
        raise PermissionError("shared compose's Otto state map is not exactly the synchronized nine-project root")
    for ident, path in loaded["controllers"].items():
        states_name = next((name for name, state in existing.items()
                            if name != "astrid" and state["project_ref"]["id"] == ident), None)
        if states_name is not None:
            raise PermissionError("Native5 state identity collides with an existing fixed view")
        existing[ident] = loaded["states"][ident]
        paths[ident] = path
    if set(paths) != set(existing):
        raise PermissionError("merged controller and state maps diverged")
    return {"states": existing, "controllers": paths,
        "root_project_ids": sorted(states_by_id), "project_ids": sorted(states_by_id),
        "root_assignment_ref": root.ref.to_dict(),
        "root_generation": root.generation, "astrid_preserved_separately": "astrid" in existing,
        "native_manager_starts": 0, "authority_issued": False, "provider_called": False}


def install_exact_nine_root_client(owner: Any, *, services_by_project: Mapping[str, Any],
                                   scoped_clients: Any, state_map: Mapping[str, Any],
                                   main_project_id: str,
                                   directory: str, conversation_ref: Mapping[str, Any],
                                   request_key: str) -> dict[str, Any]:
    """Issue a fresh exact-nine root lane after the state map proves current joins.

    Uses the maintained installer and scoped supervisor-direction wrapper. The
    per-revision subdirectory keeps any previous four-project client binding
    immutable. Call with only the nine root-owned services; preserve Astrid's
    independent service and registry entry outside this policy.
    """
    from pathlib import Path
    from otto.portfolio.root_direction_client import install_owner_root_client
    from otto.portfolio.supervisor_direction_client import scoped_supervisor_handler
    root = _root(owner)
    projects = _current_joins(owner, root)
    if (state_map.get("root_assignment_ref") != root.ref.to_dict()
            or state_map.get("root_generation") != root.generation
            or set(services_by_project) != set(projects)
            or set(state_map.get("project_ids", [])) != set(projects)):
        raise PermissionError("fresh exact-nine state map and service set required before issuance")
    if (not isinstance(request_key, str) or not request_key
            or not isinstance(conversation_ref, Mapping)
            or conversation_ref != root.session or main_project_id not in projects):
        raise PermissionError("existing owner-issued conversation and fresh immutable policy key required")
    for ident, service in services_by_project.items():
        state = service.server.state
        if state.get("project_ref") != projects[ident].ref.to_dict() or state.get("orchestrator_assignment_ref") != root.ref.to_dict():
            raise PermissionError("all nine composed services must consume the refreshed current state map")
        from herzchen.contracts import ResourceRef
        assignment = owner.assignments.get(ResourceRef.from_dict(state["assignment_ref"]))
        if (assignment.ref.to_dict() != state["assignment_ref"] or assignment.role != "manager"
                or assignment.principal != state.get("manager")
                or assignment.generation != state.get("manager_generation")
                or _identity(assignment.scope.to_dict()) != _identity(projects[ident].ref.to_dict())):
            raise PermissionError("current nine-service manager assignment changed before client issuance")
    main = services_by_project.get(main_project_id)
    if main is None:
        raise PermissionError("exact existing onboarding main project service required")
    handler = scoped_supervisor_handler(services=list(services_by_project.values()),
                                        fallback=scoped_clients.handler)
    rev_directory = Path(directory) / ("root-" + root.ref.revision)
    locator, client = install_owner_root_client(service=main, directory=rev_directory,
        conversation_ref=conversation_ref, request_key=request_key,
        project_ids=sorted(projects), project_handler=handler)
    if locator.get("binding", {}).get("project_ids") != sorted(projects):
        raise PermissionError("maintained installer did not issue the exact-nine scope")
    clients = scoped_clients.pump.clients
    lane = Path(locator["lane"])
    if lane in clients:
        raise PermissionError("fresh root lane path already exists; do not overwrite immutable policy")
    clients[lane] = client
    return {"outcome": "exact-nine-root-client-issued", "locator": locator,
        "project_ids": sorted(projects), "assignment_ref": root.ref.to_dict(),
        "generation": root.generation, "conversation_ref": root.session,
        "operations": locator["binding"]["operations"], "previous_lanes_preserved": True,
        "astrid_scope_excluded": True, "provider_called": False, "manager_starts": 0}

