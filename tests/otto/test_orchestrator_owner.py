from __future__ import annotations

from hashlib import sha256

from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


AUTHORITY = "otto-mo02-owner"
PORTFOLIO = {"authority": AUTHORITY, "kind": "wrk.portfolio", "id": "portfolio-main"}
MAIN_REQUEST = "seed-main"


def _main_ref():
    from herzchen.contracts import ResourceRef

    return ResourceRef(AUTHORITY, "wrk.assignment", "assignment-" + sha256((AUTHORITY + ":" + MAIN_REQUEST).encode()).hexdigest()[:28])


def _registered_store(tmp_path, name="orchestrator.sqlite"):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store

    path = tmp_path / name
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    from herzchen.contracts import AuthenticatedActor, ResourceRef
    from herzchen.domains.work.assignments import ResponsibilityAssignments

    ResponsibilityAssignments(store, actor=AuthenticatedActor(AUTHORITY, "manager", "credential")).assign(
        ResourceRef.from_dict(PORTFOLIO),
        role="orchestrator",
        principal="qualified-main",
        manager="qualified-main",
        logical_request_key=MAIN_REQUEST,
        actor=AuthenticatedActor(AUTHORITY, "manager", "credential"),
    )
    return store, path


def _api(store):
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
        portfolio_ref=PORTFOLIO,
        main_assignment_ref=_main_ref(),
        expected_main_principal="qualified-main",
    )
    return OttoPortfolio(owner.consumer_operations())


def _owner_api(store):
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
        portfolio_ref=PORTFOLIO,
        main_assignment_ref=_main_ref(),
        allowed_creator_ids=("another-manager",),
        expected_main_principal="qualified-main",
    )
    operations = owner.consumer_operations()
    return OttoPortfolio(operations), operations


def test_default_orchestrated_creation_replays_and_survives_owner_reopen(tmp_path):
    from herzchen.kernel.store import Store

    store, path = _registered_store(tmp_path)
    api = _api(store)
    created = api.create_with_default_orchestrator(
        actor="manager",
        request_id="mo02-project-1",
        edit={"title": "MO-02 project", "outcome": "bounded"},
    )
    assert created["outcome"] == "created"
    relation = created["record"]["payload"]["metadata"]["otto_orchestrator"]
    assert relation["schema"] == "otto.orchestrator.supervision.v2"
    assert relation["generation"] == 1
    assert created["supervision"]["assignment_ref"] == created["default_assignment_ref"]
    assert created["assignment"]["role"] == "orchestrator"

    replay = api.create_with_default_orchestrator(
        actor="manager",
        request_id="mo02-project-1",
        edit={"title": "MO-02 project", "outcome": "bounded"},
    )
    assert replay["outcome"] == "replayed"
    assert replay["project_ref"] == created["project_ref"]
    assert replay["default_assignment_ref"] == created["default_assignment_ref"]

    domains = store.registered_domains()
    store.close()
    reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    fresh = _api(reopened)
    observed = fresh.read_pending(created["project_ref"], actor="manager")
    assert observed["record"]["payload"]["metadata"]["otto_orchestrator"] == relation
    assert reopened.get_receipt(MAIN_REQUEST) is not None
    reopened.close()


def test_second_creator_reuses_the_same_main_assignment(tmp_path):
    store, _path = _registered_store(tmp_path)
    api, operations = _owner_api(store)

    first = api.create_with_default_orchestrator(
        actor="manager",
        request_id="multi-actor-1",
        edit={"title": "First"},
    )
    second = api.create_with_default_orchestrator(
        actor="another-manager",
        request_id="multi-actor-2",
        edit={"title": "Second"},
    )

    assert first["outcome"] == "created"
    assert second["outcome"] == "created"
    assert second["default_assignment_ref"] == first["default_assignment_ref"]
    assert operations.reader.get_receipt(MAIN_REQUEST) is not None
    store.close()


def test_replay_preserves_original_relation_after_main_assignment_rebind(tmp_path):
    from herzchen.contracts import ResourceRef

    store, _path = _registered_store(tmp_path)
    api, operations = _owner_api(store)
    created = api.create_with_default_orchestrator(
        actor="manager",
        request_id="rebind-replay-1",
        edit={"title": "Rebind replay"},
    )
    original_relation = created["record"]["payload"]["metadata"]["otto_orchestrator"]
    assignment_ref = ResourceRef.from_dict(created["default_assignment_ref"])
    operations.assignments_port.reassign(
        assignment_ref,
        principal="replacement-principal",
        expected_generation=1,
        logical_request_key="rebind-replay-1:reassign",
        actor=operations.binding.authenticated_actor("manager"),
    )

    replay = api.create_with_default_orchestrator(
        actor="manager",
        request_id="rebind-replay-1",
        edit={"title": "Rebind replay"},
    )
    assert replay["outcome"] == "replayed"
    assert replay["record"]["payload"]["metadata"]["otto_orchestrator"] == original_relation
    assert replay["supervision"]["assignment_ref"] == original_relation["assignment_ref"]
    store.close()


def test_owner_fence_reresolves_current_assignment_after_rebind(tmp_path):
    from herzchen.contracts import ResourceRef

    store, _path = _registered_store(tmp_path)
    api, operations = _owner_api(store)
    established = api.create_with_default_orchestrator(
        actor="manager",
        request_id="fence-seed",
        edit={"title": "Fence seed"},
    )
    assignment_ref = ResourceRef.from_dict(established["default_assignment_ref"])
    operations.assignments_port.reassign(
        ResourceRef.from_dict(established["default_assignment_ref"]),
        principal="raced-principal",
        expected_generation=1,
        logical_request_key="fence-race:reassign",
        actor=operations.binding.authenticated_actor("manager"),
    )
    raced = api.create_with_default_orchestrator(
        actor="manager",
        request_id="fence-race",
        edit={"title": "Must not create"},
    )

    assert raced["outcome"] == "created"
    assert raced["supervision"]["generation"] == 2
    assert store.get_receipt("fence-race") is not None
    store.close()


def test_ordinary_create_open_and_replay_authorization_use_owner_contract(tmp_path):
    store, _path = _registered_store(tmp_path)
    api = _api(store)
    created = api.create_pending(actor="manager", request_id="ordinary", edit={"title": "Ordinary"})
    assert created["outcome"] == "created"
    assert created["record"]["payload"]["metadata"]["otto_orchestrator"]["schema"] == "otto.orchestrator.supervision.v2"
    opened = api.create_and_open(actor="manager", request_id="ordinary-open", edit={"title": "Open"})
    assert opened["outcome"] == "created"
    assert opened["open"]["status"] == "opened"
    changed = api.create_pending(actor="manager", request_id="ordinary", edit={"title": "Changed"})
    assert changed["outcome"] == "error"
    assert changed["error"]["code"] == "replay_conflict"
    unauthorized = api.create_pending(actor="outsider", request_id="unauthorized", edit={"title": "No"})
    assert unauthorized["outcome"] == "error"
    assert store.get_receipt("unauthorized") is None
    store.close()


def test_bound_owner_template_creation_keeps_atomic_supervision_and_typed_batch(tmp_path):
    store, _path = _registered_store(tmp_path)
    api = _api(store)
    template = {
        "id": "mo02.template",
        "revision": "rev-1",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "seed": {"project": {"title": "Template project"}, "tasks": [{"local_id": "task", "title": "Template task"}]},
    }
    created = api.create_pending(actor="manager", request_id="bound-template", template=template)
    assert created["outcome"] == "created"
    assert created["record"]["payload"]["metadata"]["otto_orchestrator"]["schema"] == "otto.orchestrator.supervision.v2"
    assert created["task_created"] is True
    assert created["tasks"][0]["local_id"] == "task"
    store.close()


def test_old_core_descriptor_reopen_then_owner_bootstrap_registers_orchestration(tmp_path):
    from herzchen.kernel import Store

    store, path = _registered_store(tmp_path, name="old-core.sqlite")
    old_domains = store.registered_domains()
    assert "herzchen.work.orchestration" not in {item.domain_id for item in old_domains}
    store.close()

    reopened = Store.open(path, authority=AUTHORITY, expected_domains=old_domains)
    try:
        created = _api(reopened).create_pending(
            actor="manager",
            request_id="old-core-owner-create",
            edit={"title": "Reopened old core"},
        )
        assert created["outcome"] == "created"
        assert "herzchen.work.orchestration" in {item.domain_id for item in reopened.registered_domains()}
    finally:
        reopened.close()
