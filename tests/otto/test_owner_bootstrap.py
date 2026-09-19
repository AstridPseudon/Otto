from __future__ import annotations

from hashlib import sha256

import pytest

from otto.portfolio import (
    HerzchenBindingConfig,
    OttoPortfolio,
    PortfolioOwnerBootstrap,
)


AUTHORITY = "ott03-xhard-owner"
CREDENTIAL = "ott03-xhard-credential"


def _registered_store(tmp_path, name="owner.sqlite"):
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


def _bootstrap(store, *, materializer=None):
    binding = HerzchenBindingConfig(AUTHORITY, CREDENTIAL)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=binding,
        owner_actor="manager",
        materializer=materializer,
    )
    return owner, OttoPortfolio(owner.consumer_operations())


def _receipt(store, key):
    value = store.get_receipt(key)
    return None if value is None else value.to_dict()


def _state(store, *keys):
    return {
        "event_ids": [event.event_id for event in store.list_events()],
        "receipts": {key: _receipt(store, key) for key in keys},
    }


def _planned_ref(request_id):
    from herzchen.contracts import ResourceRef

    project_key = request_id + ":project"
    project_id = "project-" + sha256((AUTHORITY + ":" + project_key).encode()).hexdigest()[:28]
    return ResourceRef(AUTHORITY, "work.project", project_id)


def test_owner_bridge_create_and_open_is_durable_across_fresh_bootstrap(tmp_path):
    from herzchen.contracts import ResourceRef
    from herzchen.kernel.store import Store

    store, path = _registered_store(tmp_path)
    _owner, api = _bootstrap(store)
    before = _state(store, "owner-open-1", "owner-open-1:project")

    created = api.create_and_open(
        actor="manager",
        request_id="owner-open-1",
        edit={
            "title": "Owner bridge",
            "outcome": "durable create and open",
            "why_pending": "await explicit admission",
            "custom": {"preserved": True},
        },
    )
    assert created["outcome"] == "created"
    assert created["open"]["status"] == "opened"
    assert created["open"]["session_id"]
    assert created["project_ref"]["kind"] == "work.project"
    assert created["record"]["payload"]["lifecycle"] == "pending"
    assert created["record"]["payload"]["readiness"]["dispatch"] is False
    assert created["record"]["payload"]["manager"] is None
    assert created["record"]["payload"]["tasks"] == []
    assert created["record"]["payload"]["metadata"]["custom"] == {"preserved": True}
    assert created["receipt"]["operation"] == "open"
    assert created["project_receipt"]["operation"] == "work.project.create"
    assert len(created["event_ids"]) == 5

    project_ref = ResourceRef.from_dict(created["project_ref"])
    scope_ref = ResourceRef(AUTHORITY, "authoring-scope", project_ref.id)
    project_record = store.get_identity(project_ref)
    scope_record = store.get_identity(scope_ref)
    assert project_record is not None
    assert scope_record is not None
    assert scope_record.payload["checkout"]["state"] == "open"
    assert scope_record.payload["project"] == created["project_ref"]
    after = _state(store, "owner-open-1", "owner-open-1:project")
    assert before["event_ids"] == []
    assert len(after["event_ids"]) == 5

    domains = store.registered_domains()
    store.close()
    reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    _fresh_owner, fresh_api = _bootstrap(reopened)
    observed = fresh_api.read_pending(created["project_ref"], actor="manager")
    assert observed["record"]["payload"] == created["record"]["payload"]

    replay = fresh_api.create_and_open(
        actor="manager",
        request_id="owner-open-1",
        edit={
            "title": "Owner bridge",
            "outcome": "durable create and open",
            "why_pending": "await explicit admission",
            "custom": {"preserved": True},
        },
    )
    fresh_after = _state(reopened, "owner-open-1", "owner-open-1:project")
    assert replay["outcome"] == "replayed"
    assert replay["replayed"] is True
    assert replay["project_ref"] == created["project_ref"]
    assert replay["open"]["session_id"] == created["open"]["session_id"]
    assert replay["receipt"] == created["receipt"]
    assert replay["project_receipt"] == created["project_receipt"]
    assert replay["event_ids"] == created["event_ids"]
    assert fresh_after == after
    reopened.close()


def test_owner_bridge_changed_same_key_is_typed_conflict_with_zero_delta(tmp_path):
    store, _path = _registered_store(tmp_path)
    _owner, api = _bootstrap(store)
    api.create_and_open(actor="manager", request_id="owner-conflict", edit={"title": "Original"})
    before = _state(store, "owner-conflict", "owner-conflict:project")

    changed = api.create_and_open(actor="manager", request_id="owner-conflict", edit={"title": "Changed"})
    after = _state(store, "owner-conflict", "owner-conflict:project")

    assert changed["outcome"] == "error"
    assert changed["error"]["code"] == "replay_conflict"
    assert changed["event_ids"] == []
    assert after == before
    store.close()


def test_owner_admission_occupation_happens_before_project_creation(tmp_path):
    store, _path = _registered_store(tmp_path)
    owner, api = _bootstrap(store)
    blocker = HerzchenBindingConfig(AUTHORITY, CREDENTIAL).authenticated_actor("blocker")
    target = _planned_ref("owner-occupied")
    owner.authoring.open(
        target,
        blocker,
        request_id="preexisting-open",
        target_kind="project-sheet",
        base_revision="initial",
        pending=True,
    )
    before = _state(store, "owner-occupied", "owner-occupied:project")

    occupied = api.create_and_open(
        actor="manager",
        request_id="owner-occupied",
        edit={"title": "Must not be created"},
    )
    after = _state(store, "owner-occupied", "owner-occupied:project")

    assert occupied["outcome"] == "occupied"
    assert occupied["open"]["status"] == "occupied"
    assert occupied["project_ref"] is None
    assert store.get_identity(target) is None
    assert store.get_receipt("owner-occupied") is None
    assert store.get_receipt("owner-occupied:project") is None
    assert after == before
    store.close()


def test_owner_materialization_failure_saves_one_project_and_reopens_without_second_create(tmp_path):
    from herzchen.contracts import ResourceRef

    calls = []

    def fail_materialization(*, project, **_kwargs):
        calls.append(project.to_dict())
        raise RuntimeError("forced owner materialization failure")

    store, _path = _registered_store(tmp_path)
    _owner, api = _bootstrap(store, materializer=fail_materialization)
    failed = api.create_and_open(
        actor="manager",
        request_id="owner-materialize",
        edit={"title": "Saved recovery project"},
    )
    assert failed["outcome"] == "saved_project_edit_not_opened"
    assert failed["open"]["status"] == "saved_project_edit_not_opened"
    assert failed["open"]["recovery_pending"] is False
    assert failed["open"]["recovery_status"] == "saved_project_edit_not_opened"
    assert failed["project_ref"] is not None
    assert len(calls) == 1

    project_ref = ResourceRef.from_dict(failed["project_ref"])
    project_record = store.get_identity(project_ref)
    project_receipt = store.get_receipt("owner-materialize:project")
    scope_record = store.get_identity(ResourceRef(AUTHORITY, "authoring-scope", project_ref.id))
    assert project_record is not None
    assert project_record.payload["lifecycle"] == "pending"
    assert scope_record is not None
    assert scope_record.payload["status"] == "saved_edit_not_opened"
    assert scope_record.payload["checkout"]["state"] == "released"
    assert scope_record.payload["project"]["ref"] == failed["project_ref"]
    before_replay = _state(store, "owner-materialize", "owner-materialize:project")

    replay = api.create_and_open(
        actor="manager",
        request_id="owner-materialize",
        edit={"title": "Saved recovery project"},
    )
    after_replay = _state(store, "owner-materialize", "owner-materialize:project")
    assert replay["outcome"] == "replayed"
    assert replay["open"]["status"] == "saved_project_edit_not_opened"
    assert replay["project_ref"] == failed["project_ref"]
    assert replay["receipt"] == failed["receipt"]
    assert replay["project_receipt"] == failed["project_receipt"]
    assert len(calls) == 1
    assert after_replay == before_replay

    reopened = api.reopen(
        failed["project_ref"],
        actor="manager",
        request_id="owner-materialize-reopen",
    )
    assert reopened["outcome"] == "opened"
    assert reopened["project_ref"] == failed["project_ref"]
    assert reopened["opened"]["status"] == "opened"
    assert store.get_identity(project_ref) == project_record
    assert store.get_receipt("owner-materialize:project") == project_receipt
    store.close()


def test_consumer_graph_retains_only_finite_serialized_ports_reader_and_binding(tmp_path):
    from herzchen.command_ports import SerializedCommandClient, SerializedReaderClient

    store, _path = _registered_store(tmp_path)
    owner, _api = _bootstrap(store)
    consumer = owner.consumer_operations()
    assert sorted(vars(consumer)) == [
        "assignments_port",
        "authoring_port",
        "binding",
        "content_port",
        "create_open_port",
        "port",
        "reader",
        "sheet_port",
    ]
    assert isinstance(consumer.binding, HerzchenBindingConfig)
    assert isinstance(consumer.reader, SerializedReaderClient)
    for name in ("port", "sheet_port", "content_port", "assignments_port", "authoring_port", "create_open_port"):
        assert isinstance(getattr(consumer, name), SerializedCommandClient)
    assert consumer.create_open_port.endpoints == ("create_pending_and_open",)
    assert "create_and_open" not in consumer.authoring_port.endpoints
    forbidden = {
        "Store",
        "WorkGraph",
        "ProjectSheet",
        "ContentCommandHandler",
        "ResponsibilityAssignments",
        "AuthoringSessionService",
    }
    assert not forbidden.intersection({type(value).__name__ for value in vars(consumer).values()})
    for value in vars(consumer).values():
        assert not callable(value)
        assert not isinstance(value, str) or not value.endswith((".sqlite", ".sqlite3", ".db"))
    assert consumer.create_open_port.transport.socket_path.endswith("owner.sock")
    store.close()


def test_owner_bootstrap_rejects_wrong_authority_before_issuing_consumer(tmp_path):
    store, _path = _registered_store(tmp_path)
    with pytest.raises(ValueError, match="binding authority"):
        PortfolioOwnerBootstrap(
            store,
            binding=HerzchenBindingConfig("foreign-authority", CREDENTIAL),
            owner_actor="manager",
        )
    assert list(store.list_events()) == []
    store.close()


def test_consumer_lifecycle_transition_and_read_use_the_owner_port_after_reopen(tmp_path):
    from herzchen.kernel.store import Store

    store, path = _registered_store(tmp_path, "lifecycle-owner.sqlite")
    owner, api = _bootstrap(store)
    created = api.create_pending(actor="manager", request_id="lifecycle-project", edit={"title": "Lifecycle owner"})
    applied = owner.sheet.apply(
        created["project_ref"], {"tasks": [{"id": "required", "title": "Required"}]},
        logical_request_key="lifecycle-task", actor=owner.owner_actor,
    )
    project = owner.graph.get(applied.project.ref)
    task = owner.graph.get(next(iter(applied.mappings.values())))
    manager = owner.assignments.assign(task.ref, role="manager", principal="manager", logical_request_key="lifecycle-manager", actor=owner.owner_actor)

    transitioned = api.transition_project_lifecycle(
        project.ref, task.ref, manager.ref,
        actor="manager", request_id="lifecycle-active", expected_generation=manager.generation,
        expected_project_revision=project.ref.revision, expected_task_revision=task.ref.revision,
        intent="active", evidence={"acceptance": {"status": "passed", "ref": "proof"}},
        obligation={"required_task": task.ref.to_dict()},
    )
    assert transitioned["outcome"] == "transitioned"
    assert transitioned["state"] == "active"
    assert transitioned["receipt"]["logical_request_key"] == "lifecycle-active"
    read = api.read_project_lifecycle(transitioned["project_ref"], task.ref, manager.ref, actor="manager")
    assert read["outcome"] == "read"
    assert read["transition"]["intent"] == "active"

    domains = store.registered_domains()
    store.close()
    reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    try:
        _fresh_owner, fresh_api = _bootstrap(reopened)
        observed = fresh_api.read_project_lifecycle(transitioned["project_ref"], task.ref, manager.ref, actor="manager")
        assert observed["transition"] == read["transition"]
        assert observed["project_ref"] == read["project_ref"]
    finally:
        reopened.close()
