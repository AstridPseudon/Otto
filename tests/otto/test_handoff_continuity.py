"""Focused sequential safe-handoff continuity proof over public APIs."""

from __future__ import annotations

from copy import deepcopy


AUTHORITY = "ott03-sequential-handoff"
CREDENTIAL = "ott03-sequential-credential"


def _portfolio(tmp_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph, contributions, register_work
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.domains.work.sheet import ProjectSheet
    from herzchen.kernel.store import Store
    from otto.portfolio import HerzchenBindingConfig, HerzchenWorkOperations, OttoPortfolio

    path = tmp_path / "sequential-handoff.sqlite"
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
    return store, graph, assignments, OttoPortfolio(operations), path


def _events(store):
    return [event.to_dict() for event in store.list_events()]


def _receipt(store, request_id):
    receipt = store.get_receipt(request_id)
    return None if receipt is None else receipt.to_dict()


def _assignment(assignments, ref):
    value = assignments.get(ref)
    return {
        "ref": value.ref.to_dict(),
        "scope": value.scope.to_dict(),
        "role": value.role,
        "principal": value.principal,
        "stored_manager": value.payload.get("manager"),
        "generation": value.generation,
        "status": value.status.value,
        "history": [dict(item) for item in value.history],
        "payload": deepcopy(dict(value.payload)),
    }


def test_two_sequential_handoffs_replay_conflict_and_reopen(tmp_path):
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.kernel.store import Store

    store, graph, assignments, api, path = _portfolio(tmp_path)
    parent = api.create_pending(actor="parent", request_id="parent", edit={"title": "Parent obligation"})
    project = api.create_pending(actor="parent", request_id="project", edit={"title": "Pending sequential handoff"})
    assigned = api.assign_roles(
        project["project_ref"],
        {"parent": parent["project_ref"], "manager": "manager-old", "executor": ["executor-a"]},
        actor="parent",
        request_id="roles",
    )
    manager_ref_1 = assigned["manager_assignment_ref"]
    evidence_refs = [parent["project_ref"]]
    consumption_refs = [assigned["roles"]["roles:executor"]["ref"]]
    first_request = dict(
        project_ref=project["project_ref"], manager_assignment_ref=manager_ref_1,
        from_manager="manager-old", to_manager="manager-new", evidence_refs=evidence_refs,
        consumption_refs=consumption_refs, parent_obligation=parent["project_ref"],
        actor="parent", request_id="handoff-sequential-1",
    )
    before_project = graph.get(project["project_ref"])
    before = _assignment(assignments, manager_ref_1)
    first = api.handoff(**first_request)
    manager_ref_2 = first["manager_assignment_ref"]
    second_request = dict(
        project_ref=project["project_ref"], manager_assignment_ref=manager_ref_2,
        from_manager="manager-new", to_manager="manager-third", evidence_refs=evidence_refs,
        consumption_refs=consumption_refs, parent_obligation=parent["project_ref"],
        actor="parent", request_id="handoff-sequential-2",
    )
    second = api.handoff(**second_request)
    manager_ref_3 = second["manager_assignment_ref"]
    assert first["outcome"] == "handed-off"
    assert second["outcome"] == "handed-off"
    assert [manager_ref_1["revision"], manager_ref_2["revision"], manager_ref_3["revision"]] == ["rev-1", "rev-2", "rev-3"]
    assert first["assignment"]["ref"]["id"] == second["assignment"]["ref"]["id"] == before["ref"]["id"]
    assert [before["generation"], first["assignment"]["generation"], second["assignment"]["generation"]] == [1, 2, 3]
    assert [before["principal"], first["assignment"]["principal"], second["assignment"]["principal"]] == ["manager-old", "manager-new", "manager-third"]
    assert len(second["assignment"]["history"]) == 3
    assert second["assignment"]["stored_manager"] == "manager-old"
    assert second["handoff"]["evidence_refs"] == evidence_refs
    assert second["handoff"]["consumption_refs"] == consumption_refs
    assert second["handoff"]["parent_obligation"] == parent["project_ref"]
    assert first["receipt"]["operation"] == second["receipt"]["operation"] == "work.assignment.reassign"
    assert first["receipt"]["result_ref"] == manager_ref_2
    assert second["receipt"]["result_ref"] == manager_ref_3
    assert first["event_ids"] == first["receipt"]["event_ids"]
    assert second["event_ids"] == second["receipt"]["event_ids"]
    assert all(event["event_type"] == "work.assignment.reassigned" for event in _events(store) if event["event_id"] in first["event_ids"] + second["event_ids"])
    handoff_events = [
        event for event in _events(store)
        if event["event_id"] in first["event_ids"] + second["event_ids"]
    ]
    assert [event["subject"] for event in handoff_events] == [manager_ref_2, manager_ref_3]
    assert graph.get(project["project_ref"]).ref.to_dict() == before_project.ref.to_dict()
    assert graph.get(project["project_ref"]).payload["lifecycle"] == "pending"
    assert graph.get(project["project_ref"]).payload["tasks"] == []

    events_after_second = _events(store)
    second_receipt = _receipt(store, second_request["request_id"])
    second_retry = api.handoff(**second_request)
    assert second_retry["outcome"] == "replayed"
    assert second_retry["receipt"] == second["receipt"] == second_receipt
    assert second_retry["assignment"] == second["assignment"]
    assert second_retry["event_ids"] == second["event_ids"]
    assert _events(store) == events_after_second
    first_retry = api.handoff(**first_request)
    assert first_retry["outcome"] == "replayed"
    assert first_retry["receipt"] == first["receipt"]
    assert first_retry["assignment"]["generation"] == 2
    assert _events(store) == events_after_second
    assert _assignment(assignments, manager_ref_3)["principal"] == "manager-third"
    assert _assignment(assignments, manager_ref_3)["generation"] == 3

    conflict = api.handoff(**dict(second_request, to_manager="manager-other"))
    assert conflict["outcome"] == "error"
    assert conflict["error"]["code"] == "replay_conflict"
    assert conflict["event_ids"] == []
    assert _events(store) == events_after_second
    stale = api.handoff(**dict(first_request, request_id="stale-old-target"))
    assert stale["outcome"] == "error"
    assert stale["error"]["code"] == "stale_manager_assignment"
    assert stale["event_ids"] == []
    assert _events(store) == events_after_second

    domains = store.registered_domains()
    persisted_events = _events(store)
    store.close()
    reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    actor = AuthenticatedActor(AUTHORITY, "parent", CREDENTIAL)
    fresh_graph = WorkGraph(reopened, actor=actor)
    fresh_assignments = ResponsibilityAssignments(reopened, actor=actor)
    fresh_project = fresh_graph.get(project["project_ref"])
    fresh = _assignment(fresh_assignments, manager_ref_3)
    assert fresh_project.ref.to_dict() == project["project_ref"]
    assert fresh_project.payload["lifecycle"] == "pending"
    assert fresh["ref"] == manager_ref_3
    assert fresh["principal"] == "manager-third"
    assert fresh["generation"] == 3
    assert len(fresh["history"]) == 3
    assert _receipt(reopened, first_request["request_id"]) == first["receipt"]
    assert _receipt(reopened, second_request["request_id"]) == second["receipt"]
    assert _events(reopened) == persisted_events
    reopened.close()
