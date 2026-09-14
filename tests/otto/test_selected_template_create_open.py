"""Focused owner-bridge proof for selected-template create-and-open."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


AUTHORITY = "ott03-selected-open"
CREDENTIAL = "ott03-selected-open-credential"


def _store(tmp_path, name="selected-open.sqlite"):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store

    path = tmp_path / name
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    return store, path


def _api(store, *, materializer=None):
    binding = HerzchenBindingConfig(AUTHORITY, CREDENTIAL)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=binding,
        owner_actor="owner",
        materializer=materializer,
    )
    return owner, OttoPortfolio(owner.consumer_operations()), binding


def _template():
    return {
        "kind": "work_template",
        "id": "ott03.selected.open",
        "revision": "selected-open-v1",
        "parameters": {
            "type": "object",
            "properties": {
                "project_title": {"type": "string", "minLength": 1},
                "task_body": {"type": "string", "minLength": 1},
            },
            "required": ["project_title", "task_body"],
            "additionalProperties": False,
        },
        "seed": {
            "project": {
                "title": {"$param": "project_title"},
                "outcome": "Selected create-and-open outcome",
                "custom": {"selected_open": True},
            },
            "tasks": [{
                "local_id": "selected-task",
                "title": "Selected typed task",
                "body": {"$param": "task_body"},
                "metadata": {"origin": "selected-create-open"},
            }],
        },
    }


def _parameters(title="Selected open project", body="Typed selected content"):
    return {"project_title": title, "task_body": body}


def _events(store):
    return [event.to_dict() for event in store.list_events()]


def _state(store, *keys):
    return {
        "events": _events(store),
        "receipts": {
            key: None if store.get_receipt(key) is None else store.get_receipt(key).to_dict()
            for key in keys
        },
        "counts": dict(store.consumer().snapshot_counts()),
    }


def _planned_ref(request_id):
    from herzchen.contracts import ResourceRef

    project_key = request_id + ":project"
    project_id = "project-" + sha256((AUTHORITY + ":" + project_key).encode()).hexdigest()[:28]
    return ResourceRef(AUTHORITY, "work.project", project_id)


def test_selected_create_and_open_materializes_typed_project_task_and_real_handle(tmp_path):
    store, _path = _store(tmp_path)
    owner, api, _binding = _api(store)
    template = _template()
    parameters = _parameters()

    created = api.create_and_open(
        actor="owner",
        request_id="selected-open",
        template=template,
        template_parameters=parameters,
    )

    assert created["outcome"] == "created"
    assert created["open"]["status"] == "opened"
    assert created["open"]["session_id"]
    assert created["open"]["handle"]["session_id"] == created["open"]["session_id"]
    assert created["open"]["handle"]["scope"] == created["receipt"]["target"]
    assert created["open"]["checkout"]["state"] == "open"
    assert created["open"]["scope"]["id"] == created["project_ref"]["id"]
    assert created["template_ref"] == {
        "authority": "pack",
        "kind": "work_template",
        "id": template["id"],
        "revision": template["revision"],
    }
    assert created["template_revision"] == template["revision"]
    assert created["record"]["payload"]["title"] == parameters["project_title"]
    assert created["record"]["payload"]["outcome"] == "Selected create-and-open outcome"
    assert created["record"]["payload"]["custom"] == {"selected_open": True}
    assert created["record"]["payload"]["lifecycle"] == "pending"
    assert created["record"]["payload"]["readiness"]["dispatch"] is False
    assert created["record"]["payload"]["manager"] is None
    assert created["record"]["payload"]["budget"] is None
    assert created["record"]["payload"]["execution"] is None
    assert created["record"]["payload"]["metadata_namespaces"]["work.template"] == {
        "template_id": template["id"],
        "parameters": parameters,
        "criteria": [],
        "auto_dispatch": False,
    }
    assert len(created["tasks"]) == 1
    task = created["tasks"][0]
    assert task["local_id"] == "selected-task"
    assert task["ref"]["kind"] == "work.task"
    assert task["record"]["payload"]["body"] == parameters["task_body"]
    assert task["record"]["payload"]["metadata"] == {"origin": "selected-create-open"}
    assert created["record"]["payload"]["tasks"] == created["task_refs"]
    assert created["receipt"]["operation"] == "open"
    assert created["project_receipt"]["operation"] == "work.project.create"
    assert created["template_receipt"]["operation"] == "work.project-sheet.apply"
    assert created["template_receipt"]["result_ref"] == created["project_ref"]
    assert len(created["event_ids"]) == 6
    assert len(_events(store)) == 6
    assert owner.consumer_operations().create_open_port.endpoints == ("create_pending_and_open",)
    assert created["executable"] is False
    for field in ("activation", "dispatch", "manager_launch", "budget_reserved", "session_task_created", "execution"):
        assert created[field] is False
    event_types = {event["event_type"] for event in _events(store)}
    assert not any(token in event_type for event_type in event_types for token in ("dispatch", "launch", "budget", "execution"))
    store.close()


def test_selected_create_and_open_exact_replay_and_changed_inputs_are_zero_delta(tmp_path):
    store, _path = _store(tmp_path)
    _owner, api, _binding = _api(store)
    template = _template()
    parameters = _parameters()
    keys = ("replay", "replay:actor", "replay:project", "replay:template", "replay:project-created", "replay:materialized")

    created = api.create_and_open(
        actor="owner", request_id="replay", template=template, template_parameters=parameters
    )
    before = _state(store, *keys)
    replay = api.create_and_open(
        actor="owner",
        request_id="replay",
        template=deepcopy(template),
        template_parameters=deepcopy(parameters),
    )
    assert replay["outcome"] == "replayed"
    assert replay["replayed"] is True
    assert replay["project_ref"] == created["project_ref"]
    assert replay["task_refs"] == created["task_refs"]
    assert replay["open"]["session_id"] == created["open"]["session_id"]
    assert replay["receipt"] == created["receipt"]
    assert replay["project_receipt"] == created["project_receipt"]
    assert replay["template_receipt"] == created["template_receipt"]
    assert _state(store, *keys) == before

    changed_resource = deepcopy(template)
    changed_resource["seed"]["project"]["outcome"] = "Changed selected resource"
    conflict = api.create_and_open(
        actor="owner", request_id="replay", template=changed_resource, template_parameters=parameters
    )
    assert conflict["outcome"] == "error"
    assert conflict["error"]["code"] == "replay_conflict"
    assert conflict["event_ids"] == []
    assert _state(store, *keys) == before

    parameter_conflict = api.create_and_open(
        actor="owner",
        request_id="replay",
        template=template,
        template_parameters=_parameters(title="Changed parameter"),
    )
    assert parameter_conflict["outcome"] == "error"
    assert parameter_conflict["error"]["code"] == "replay_conflict"
    assert parameter_conflict["event_ids"] == []
    assert _state(store, *keys) == before
    store.close()


@pytest.mark.parametrize(
    ("template", "parameters"),
    [
        ({"id": "missing"}, {}),
        (dict(_template(), seed={"tasks": "not-an-array"}), _parameters()),
        (_template(), {}),
        (_template(), {"project_title": 4, "task_body": "content"}),
        (dict(_template(), unexpected=True), _parameters()),
    ],
)
def test_invalid_selected_resource_seed_or_parameters_precedes_project_creation(
    tmp_path, template, parameters
):
    store, _path = _store(tmp_path)
    _owner, api, _binding = _api(store)
    before = _state(store, "invalid", "invalid:project", "invalid:template")

    invalid = api.create_and_open(
        actor="owner",
        request_id="invalid",
        template=template,
        template_parameters=parameters,
    )

    assert invalid["outcome"] == "error"
    assert invalid["error"]["code"] == "invalid_template_resource"
    assert invalid["event_ids"] == []
    assert store.get_identity(_planned_ref("invalid")) is None
    assert _state(store, "invalid", "invalid:project", "invalid:template") == before
    store.close()


def test_selected_create_and_open_occupation_precedes_project_creation(tmp_path):
    store, _path = _store(tmp_path)
    owner, api, binding = _api(store)
    target = _planned_ref("occupied")
    blocker = binding.authenticated_actor("blocker")
    owner.authoring.open(
        target,
        blocker,
        request_id="preexisting-open",
        target_kind="project-sheet",
        base_revision="initial",
        pending=True,
    )
    before = _state(store, "occupied", "occupied:project", "occupied:template")

    occupied = api.create_and_open(
        actor="owner",
        request_id="occupied",
        template=_template(),
        template_parameters=_parameters(),
    )

    assert occupied["outcome"] == "occupied"
    assert occupied["open"]["status"] == "occupied"
    assert occupied["project_ref"] is None
    assert store.get_identity(target) is None
    assert _state(store, "occupied", "occupied:project", "occupied:template") == before
    store.close()


def test_selected_materialization_failure_keeps_one_truthful_project_and_replays(tmp_path):
    calls = []

    def fail_materialization(*, project, **_kwargs):
        calls.append(project.to_dict())
        raise RuntimeError("forced selected owner materialization failure")

    store, _path = _store(tmp_path)
    _owner, api, _binding = _api(store, materializer=fail_materialization)
    keys = ("failure", "failure:project", "failure:template", "failure:materialize-failure")
    failed = api.create_and_open(
        actor="owner",
        request_id="failure",
        template=_template(),
        template_parameters=_parameters(),
    )

    assert failed["outcome"] == "saved_project_edit_not_opened"
    assert failed["open"]["status"] == "saved_project_edit_not_opened"
    assert failed["open"]["recovery_status"] == "saved_project_edit_not_opened"
    assert failed["record"]["payload"]["title"] == "Selected open project"
    assert len(failed["record"]["payload"]["tasks"]) == 1
    assert failed["template_receipt"]["operation"] == "work.project-sheet.apply"
    assert len(calls) == 1
    before = _state(store, *keys)

    replay = api.create_and_open(
        actor="owner",
        request_id="failure",
        template=deepcopy(_template()),
        template_parameters=deepcopy(_parameters()),
    )
    assert replay["outcome"] == "replayed"
    assert replay["open"]["status"] == "saved_project_edit_not_opened"
    assert replay["project_ref"] == failed["project_ref"]
    assert replay["task_refs"] == failed["task_refs"]
    assert len(calls) == 1
    assert _state(store, *keys) == before

    reopened = api.reopen(failed["project_ref"], actor="owner", request_id="failure-reopen")
    assert reopened["outcome"] == "opened"
    assert reopened["project_ref"] == failed["project_ref"]
    store.close()


def test_selected_create_and_open_survives_store_close_and_fresh_replay(tmp_path):
    from herzchen.contracts import ResourceRef
    from herzchen.kernel.store import Store

    store, path = _store(tmp_path)
    _owner, api, binding = _api(store)
    created = api.create_and_open(
        actor="owner",
        request_id="fresh",
        template=_template(),
        template_parameters=_parameters(),
    )
    domains = store.registered_domains()
    events = _events(store)
    store.close()

    reopened_store = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    fresh_owner = PortfolioOwnerBootstrap(
        reopened_store, binding=binding, owner_actor="owner"
    )
    fresh_api = OttoPortfolio(fresh_owner.consumer_operations())
    observed = fresh_api.read_pending(created["project_ref"], actor="owner")
    assert observed["record"]["payload"]["title"] == "Selected open project"
    assert observed["record"]["payload"]["tasks"] == created["task_refs"]
    scope_ref = ResourceRef(AUTHORITY, "authoring-scope", created["project_ref"]["id"])
    scope = fresh_owner.consumer_operations().reader.get_record(scope_ref)
    assert scope.payload["checkout"]["state"] == "open"
    assert scope.payload["project"] == created["project_ref"]

    replay = fresh_api.create_and_open(
        actor="owner",
        request_id="fresh",
        template=deepcopy(_template()),
        template_parameters=deepcopy(_parameters()),
    )
    assert replay["outcome"] == "replayed"
    assert replay["project_ref"] == created["project_ref"]
    assert replay["task_refs"] == created["task_refs"]
    assert replay["open"]["session_id"] == created["open"]["session_id"]
    assert _events(reopened_store) == events
    reopened_store.close()


def test_blank_create_and_open_request_shape_and_lifecycle_remain_unchanged(tmp_path):
    store, _path = _store(tmp_path)
    _owner, api, _binding = _api(store)
    created = api.create_and_open(
        actor="owner", request_id="blank-regression", edit={"title": "Blank regression"}
    )

    assert created["outcome"] == "created"
    assert created["open"]["status"] == "opened"
    assert created["record"]["payload"]["title"] == "Blank regression"
    assert created["record"]["payload"]["tasks"] == []
    assert created["record"]["payload"]["metadata"]["otto_request"]["payload"] == {
        "edit": {"title": "Blank regression"},
        "template": "blank",
        "open": True,
    }
    assert created["template"] is None
    assert created["template_receipt"] is None
    assert len(created["event_ids"]) == 5
    store.close()
