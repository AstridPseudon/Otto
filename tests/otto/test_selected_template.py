"""Real ProjectSheet template-instantiation proof for OTT-03."""

from __future__ import annotations

from copy import deepcopy


AUTHORITY = "ott03-selected-template"
CREDENTIAL = "ott03-selected-template-credential"


def _owner_api(tmp_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph, register_work
    from herzchen.kernel.store import Store
    from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap

    path = tmp_path / "selected-template.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    binding = HerzchenBindingConfig(AUTHORITY, CREDENTIAL)
    owner = PortfolioOwnerBootstrap(store, binding=binding, owner_actor="owner")
    graph = WorkGraph(store, actor=AuthenticatedActor(AUTHORITY, "owner", CREDENTIAL))
    return store, owner, graph, OttoPortfolio(owner.consumer_operations()), path, binding


def _template():
    return {
        "id": "ott03.selected.template",
        "revision": "template-rev-7",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "seed": {
            "project": {
                "title": "Selected template project",
                "outcome": "Template-defined outcome",
                "custom": {"selected": True},
            },
            "tasks": [{
                "local_id": "template-task",
                "title": "Template-defined task",
                "body": "Typed task content",
                "metadata": {"origin": "selected-template"},
            }],
        },
    }


def _events(store):
    return [event.to_dict() for event in store.list_events()]


def _receipt(store, request_id):
    receipt = store.get_receipt(request_id)
    return None if receipt is None else receipt.to_dict()


def test_selected_template_instantiates_typed_pending_project_and_replays(tmp_path):
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph
    from herzchen.kernel.store import Store
    from otto.portfolio import PortfolioOwnerBootstrap

    store, owner, graph, api, path, binding = _owner_api(tmp_path)
    template = _template()
    before_events = _events(store)
    created = api.create_pending(actor="owner", request_id="selected-1", template=template)
    assert created["outcome"] == "created"
    assert created["template_ref"] == {"authority": "pack", "kind": "work_template", "id": template["id"], "revision": template["revision"]}
    assert created["template_revision"] == template["revision"]
    assert created["record"]["project_ref"] == created["project_ref"]
    assert created["record"]["payload"]["title"] == "Selected template project"
    assert created["record"]["payload"]["outcome"] == "Template-defined outcome"
    assert created["record"]["payload"]["custom"] == {"selected": True}
    assert created["record"]["payload"]["lifecycle"] == "pending"
    assert created["record"]["payload"]["tasks"] == [created["task_refs"][0]]
    assert len(created["tasks"]) == 1
    task = created["tasks"][0]
    assert task["local_id"] == "template-task"
    assert task["ref"]["kind"] == "work.task"
    assert task["record"]["payload"]["title"] == "Template-defined task"
    assert task["record"]["payload"]["body"] == "Typed task content"
    assert task["record"]["payload"]["metadata"] == {"origin": "selected-template"}
    assert created["receipt"]["operation"] == "work.project-sheet.apply"
    assert created["receipt"]["result_ref"] == created["project_ref"]
    assert created["event_ids"] == created["receipt"]["event_ids"] + created["project_receipt"]["event_ids"]
    assert len(_events(store)) == len(before_events) + 2
    assert created["executable"] is False
    assert created["activation"] is created["dispatch"] is False
    assert created["task_created"] is True
    assert created["budget_reserved"] is created["session_created"] is False

    edited = api.edit_pending(
        created["project_ref"],
        {"title": "Edited selected template project", "outcome": "Edited template outcome"},
        actor="owner",
        request_id="selected-edit",
    )
    assert edited["outcome"] == "edited"
    fresh = graph.get(created["project_ref"])
    assert fresh.payload["title"] == "Edited selected template project"
    assert fresh.payload["outcome"] == "Edited template outcome"
    assert fresh.payload["tasks"] == created["record"]["payload"]["tasks"]

    reopened = api.reopen(created["project_ref"], actor="owner", request_id="selected-reopen")
    assert reopened["outcome"] == "opened"
    assert reopened["project_ref"] == created["project_ref"]

    events_after_create = _events(store)
    receipt_after_create = _receipt(store, "selected-1")
    replay = api.create_pending(actor="owner", request_id="selected-1", template=deepcopy(template))
    assert replay["outcome"] == "replayed"
    assert replay["project_ref"]["authority"] == created["project_ref"]["authority"]
    assert replay["project_ref"]["kind"] == created["project_ref"]["kind"]
    assert replay["project_ref"]["id"] == created["project_ref"]["id"]
    assert replay["task_refs"] == created["task_refs"]
    assert replay["receipt"] == created["receipt"] == receipt_after_create
    assert replay["project_receipt"] == created["project_receipt"]
    assert _events(store) == events_after_create

    changed = deepcopy(template)
    changed["parameters"] = {"type": "object", "properties": {"changed": {"type": "string"}}, "additionalProperties": False}
    conflict = api.create_pending(actor="owner", request_id="selected-1", template=changed)
    assert conflict["outcome"] == "error"
    assert conflict["error"]["code"] == "replay_conflict"
    assert conflict["event_ids"] == []
    assert _events(store) == events_after_create
    assert _receipt(store, "selected-1") == receipt_after_create

    invalid_before = _events(store)
    invalid = api.create_pending(actor="owner", request_id="selected-invalid", template={"id": "missing"})
    assert invalid["outcome"] == "error"
    assert invalid["error"]["code"] == "invalid_template_resource"
    assert invalid["event_ids"] == []
    assert _events(store) == invalid_before

    selected_open = api.create_and_open(actor="owner", request_id="selected-open", template=template)
    assert selected_open["outcome"] == "occupied"
    assert selected_open["open"]["status"] == "actor_occupied"
    assert selected_open.get("project_ref") is None
    assert selected_open["event_ids"] == []
    assert _events(store) == invalid_before
    domains = store.registered_domains()
    store.close()

    reopened_store = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    fresh_owner = PortfolioOwnerBootstrap(reopened_store, binding=binding, owner_actor="owner")
    fresh_graph = WorkGraph(reopened_store, actor=AuthenticatedActor(AUTHORITY, "owner", CREDENTIAL))
    observed = fresh_graph.get(created["project_ref"])
    assert observed.ref.authority == created["project_ref"]["authority"]
    assert observed.ref.kind == created["project_ref"]["kind"]
    assert observed.ref.id == created["project_ref"]["id"]
    assert observed.payload["title"] == "Edited selected template project"
    assert observed.payload["outcome"] == "Edited template outcome"
    assert observed.payload["tasks"] == created["task_refs"]
    assert len(fresh_owner.consumer_operations().reader.list_events()) == len(invalid_before)
    reopened_store.close()
