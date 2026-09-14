"""Focused OTT-03 safe responsibility handoff proof over accepted public APIs."""

from __future__ import annotations

from copy import deepcopy


AUTHORITY = "ott03-handoff-authority"
CREDENTIAL = "ott03-handoff-credential"


def _portfolio(tmp_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph, contributions, register_work
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.domains.work.sheet import ProjectSheet
    from herzchen.kernel.store import Store
    from otto.portfolio import HerzchenBindingConfig, HerzchenWorkOperations, OttoPortfolio

    path = tmp_path / "handoff.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    actor = AuthenticatedActor(AUTHORITY, "parent", CREDENTIAL)
    graph = WorkGraph(store, actor=actor)
    assignments = ResponsibilityAssignments(store, actor=actor)
    sheet = ProjectSheet(store, actor=actor)
    operations = HerzchenWorkOperations(
        port=graph.command_port,
        reader=graph.reader,
        binding=HerzchenBindingConfig(AUTHORITY, CREDENTIAL),
        sheet_port=sheet.command_port,
        assignments_port=assignments.command_port,
    )
    return store, graph, assignments, sheet, OttoPortfolio(operations), path, contributions


def _event_snapshot(store):
    return [event.to_dict() for event in store.list_events()]


def _receipt(store, key):
    value = store.get_receipt(key)
    return None if value is None else value.to_dict()


def _assignment_snapshot(assignments, ref):
    value = assignments.get(ref)
    return {
        "ref": value.ref.to_dict(),
        "scope": value.scope.to_dict(),
        "role": value.role,
        "principal": value.principal,
        "generation": value.generation,
        "status": value.status.value,
        "history": [dict(item) for item in value.history],
        "payload": deepcopy(dict(value.payload)),
    }


def test_real_handoff_uses_returned_assignment_and_survives_reopen(tmp_path):
    store, graph, assignments, sheet, api, path, contributions = _portfolio(tmp_path)
    parent = api.create_pending(actor="parent", request_id="parent-project", edit={"title": "Parent obligation"})
    project = api.create_pending(actor="parent", request_id="pending-project", edit={"title": "Pending handoff"})
    assigned = api.assign_roles(
        project["project_ref"],
        {"parent": parent["project_ref"], "manager": "manager-old", "executor": ["executor-a"]},
        actor="parent",
        request_id="assign-roles",
    )
    manager_ref = assigned["manager_assignment_ref"]
    evidence_ref = parent["project_ref"]
    consumption_ref = assigned["roles"]["assign-roles:executor"]["ref"]

    before_project = graph.get(project["project_ref"])
    before_assignment = _assignment_snapshot(assignments, manager_ref)
    before_events = _event_snapshot(store)
    handed = api.handoff(
        project["project_ref"],
        manager_assignment_ref=manager_ref,
        from_manager="manager-old",
        to_manager="manager-new",
        evidence_refs=[evidence_ref],
        consumption_refs=[consumption_ref],
        parent_obligation=parent["project_ref"],
        actor="parent",
        request_id="handoff-1",
    )

    assert handed["outcome"] == "handed-off"
    assert handed["safe_handoff"] is True
    assert handed["executable"] is False
    assert handed["activation"] is handed["dispatch"] is False
    assert handed["budget_reserved"] is handed["task_created"] is handed["session_created"] is False
    assert handed["project_ref"] == project["project_ref"]
    assert handed["assignment"]["ref"]["id"] == before_assignment["ref"]["id"]
    assert handed["assignment"]["principal"] == "manager-new"
    assert handed["assignment"]["generation"] == before_assignment["generation"] + 1
    assert len(handed["assignment"]["history"]) == len(before_assignment["history"]) + 1
    assert handed["handoff"]["evidence_refs"] == [evidence_ref]
    assert handed["handoff"]["consumption_refs"] == [consumption_ref]
    assert handed["handoff"]["parent_obligation"] == parent["project_ref"]
    assert handed["receipt"]["operation"] == "work.assignment.reassign"
    assert handed["receipt"]["result_ref"] == handed["manager_assignment_ref"]
    assert handed["event_ids"] == handed["receipt"]["event_ids"]
    handoff_events = [event for event in _event_snapshot(store) if event["event_id"] in handed["event_ids"]]
    assert len(handoff_events) == 1
    assert handoff_events[0]["event_type"] == "work.assignment.reassigned"
    assert handoff_events[0]["subject"] == handed["manager_assignment_ref"]
    assert len(_event_snapshot(store)) == len(before_events) + 1

    # The project identity and inert project state are unaffected; only the
    # canonical assignment identity changes generation/principal.
    after_project = graph.get(project["project_ref"])
    assert after_project.ref.to_dict() == before_project.ref.to_dict()
    assert after_project.payload["lifecycle"] == "pending"
    assert after_project.payload["manager"] is None
    assert after_project.payload["tasks"] == []
    assert _assignment_snapshot(assignments, manager_ref)["principal"] == "manager-new"

    persisted_events = _event_snapshot(store)
    domains = store.registered_domains()
    store.close()
    reopened = __import__("herzchen.kernel.store", fromlist=["Store"]).Store.open(
        path, authority=AUTHORITY, expected_domains=domains
    )
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments

    fresh_actor = AuthenticatedActor(AUTHORITY, "parent", CREDENTIAL)
    fresh_graph = WorkGraph(reopened, actor=fresh_actor)
    fresh_assignments = ResponsibilityAssignments(reopened, actor=fresh_actor)
    fresh_project = fresh_graph.get(project["project_ref"])
    fresh_assignment = _assignment_snapshot(fresh_assignments, manager_ref)
    assert fresh_project.ref.to_dict() == project["project_ref"]
    assert fresh_project.payload["lifecycle"] == "pending"
    assert fresh_assignment["ref"]["id"] == before_assignment["ref"]["id"]
    assert fresh_assignment["principal"] == "manager-new"
    assert fresh_assignment["generation"] == 2
    assert len(fresh_assignment["history"]) == 2
    assert _receipt(reopened, "handoff-1") == handed["receipt"]
    assert _event_snapshot(reopened) == persisted_events
    reopened.close()


def test_handoff_replay_conflict_and_rejections_have_zero_delta(tmp_path):
    store, _graph, assignments, _sheet, api, _path, _contributions = _portfolio(tmp_path)
    parent = api.create_pending(actor="parent", request_id="parent", edit={"title": "Parent"})
    project = api.create_pending(actor="parent", request_id="project", edit={"title": "Project"})
    assigned = api.assign_roles(project["project_ref"], {"parent": parent["project_ref"], "manager": "old", "executor": "exec"}, actor="parent", request_id="roles")
    ref = assigned["manager_assignment_ref"]
    base = dict(
        project_ref=project["project_ref"], manager_assignment_ref=ref, from_manager="old", to_manager="new",
        evidence_refs=[parent["project_ref"]], consumption_refs=[ref], parent_obligation=parent["project_ref"],
        actor="parent", request_id="handoff",
    )
    first = api.handoff(**base)
    events_after_first = _event_snapshot(store)
    receipt_after_first = _receipt(store, "handoff")
    replay = api.handoff(**base)
    assert replay["outcome"] == "replayed"
    assert replay["assignment"] == first["assignment"]
    assert replay["handoff"] == first["handoff"]
    assert replay["receipt"] == first["receipt"] == receipt_after_first
    assert replay["event_ids"] == first["event_ids"]
    assert _event_snapshot(store) == events_after_first

    for changed in (
        {"to_manager": "other"},
        {"evidence_refs": [{"id": "changed-evidence"}]},
        {"consumption_refs": [{"id": "changed-consumption"}]},
        {"parent_obligation": {"id": "changed-parent"}},
    ):
        conflict = api.handoff(**dict(base, **changed))
        assert conflict["error"]["code"] == "replay_conflict"
        assert _event_snapshot(store) == events_after_first
        assert _receipt(store, "handoff") == receipt_after_first

    for rejected in (
        dict(base, request_id="wrong-from", from_manager="wrong"),
        dict(base, request_id="unknown-target", manager_assignment_ref={"authority": AUTHORITY, "kind": "wrk.assignment", "id": "missing"}),
        dict(base, request_id="wrong-role", manager_assignment_ref=assigned["roles"]["roles:executor"]["ref"]),
    ):
        result = api.handoff(**rejected)
        assert result["outcome"] == "error"
        assert result["event_ids"] == []
        assert _event_snapshot(store) == events_after_first
    assert _assignment_snapshot(assignments, ref)["principal"] == "new"
    store.close()


def test_real_handoff_requires_typed_target_and_retains_finite_consumer_boundary(tmp_path):
    store, _graph, _assignments, _sheet, api, _path, _contributions = _portfolio(tmp_path)
    project = api.create_pending(actor="parent", request_id="project", edit={"title": "Project"})
    parent = api.create_pending(actor="parent", request_id="parent", edit={"title": "Parent"})
    api.assign_roles(project["project_ref"], {"parent": parent["project_ref"], "manager": "old", "executor": "exec"}, actor="parent", request_id="roles")
    missing = api.handoff(
        project["project_ref"], from_manager="old", to_manager="new", evidence_refs=[parent["project_ref"]],
        consumption_refs=[parent["project_ref"]], parent_obligation=parent["project_ref"], actor="parent", request_id="missing-ref",
    )
    assert missing["error"]["code"] == "manager_assignment_ref_required"
    assert missing["event_ids"] == []
    finite = api.operations
    assert sorted(vars(finite)) == ["assignments_port", "authoring_port", "binding", "content_port", "create_open_port", "port", "reader", "sheet_port"]
    for value in vars(finite).values():
        name = type(value).__name__
        assert name not in {"Store", "WorkGraph", "ProjectSheet", "ContentCommandHandler", "ResponsibilityAssignments", "AuthoringSessionService"}
        assert "sqlite" not in name.lower()
    store.close()
