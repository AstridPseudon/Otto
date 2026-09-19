"""Serialized SUP-03 lifecycle transitions over the canonical owner store."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from herzchen.authoring import domain_contribution as authoring_domain_contribution
from herzchen.authoring import register_authoring
from herzchen.content import domain_contribution
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


AUTHORITY = "sup03-owner"


def _store(path: Path, *, create: bool) -> Store:
    if create:
        store = Store.create(path, authority=AUTHORITY)
        register_work(store)
        store.register_domain_handler((domain_contribution(),))
        register_authoring(store)
        return store
    from herzchen.domains.work import contributions
    expected = tuple(sorted(
        (*contributions(), domain_contribution(), authoring_domain_contribution()),
        key=lambda item: item.domain_id,
    ))
    return Store.open(path, authority=AUTHORITY, expected_domains=expected)


def _fixture(tmp_path: Path):
    store = _store(tmp_path / "owner.sqlite", create=True)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
    )
    api = OttoPortfolio(owner.consumer_operations())
    created = api.create_pending(actor="manager", request_id="project", edit={"title": "Lifecycle"})
    project = owner.graph.get(created["project_ref"])
    manager = owner.assignments.assign(
        project.ref, role="manager", principal="manager", logical_request_key="manager", actor=owner.owner_actor
    )
    orchestrator = owner.assignments.assign(
        project.ref, role="orchestrator", principal="orchestrator", logical_request_key="orchestrator", actor=owner.owner_actor
    )
    return store, owner, project, manager, orchestrator


def _transition(operations, project, manager, *, request_id, action, actor="manager", **extra):
    return operations.execute(
        "work.lifecycle.transition",
        {
            "project_ref": project.ref.to_dict(),
            "action": action,
            "expected_project_revision": project.ref.revision,
            "generation": 1,
            "manager_assignment": manager.ref.to_dict(),
            **extra,
        },
        request_id=request_id,
        actor=actor,
    )


def test_serialized_lifecycle_persists_transition_receipt_intent_and_replays(tmp_path):
    store, owner, project, manager, orchestrator = _fixture(tmp_path)
    operations = owner.consumer_operations()
    packet = {role: {key: str(uuid4()) for key in ("effect_id", "readback_id", "ack_id")} for role in ("manager", "portfolio")}

    activated = _transition(operations, project, manager, request_id="activate", action="activate", effect_packet=packet)
    assert activated["outcome"] == "transitioned"
    assert activated["read"]["lifecycle"] == "active"
    assert activated["read"]["reconciliation"]["effect_packet"] == packet
    current = owner.graph.get(project.ref)

    close = _transition(operations, current, manager, request_id="close", action="manager-close-request")
    assert close["outcome"] == "transitioned"
    assert close["read"]["close_request"]["manager_assignment"]["id"] == manager.ref.id
    current = owner.graph.get(project.ref)
    evidence = {
        "project_ref": current.ref.to_dict(),
        "acceptance": {"status": "passed", "ref": "acceptance-proof"},
        "publication": {"status": "verified", "ref": "e6cdd873"},
        "remote": {"status": "verified", "ref": "e6cdd873"},
        "runtime": {"status": "qualified", "ref": "19e8b358"},
    }
    terminal = _transition(
        operations,
        current,
        manager,
        request_id="terminal",
        action="orchestrator-close",
        actor="orchestrator",
        manager_assignment=None,
        orchestrator_assignment=orchestrator.ref.to_dict(),
        evidence=evidence,
    )
    assert terminal["outcome"] == "transitioned"
    assert terminal["read"]["lifecycle"] == "completed"
    replay = operations.execute(
        "work.lifecycle.transition",
        {
            "project_ref": current.ref.to_dict(),
            "action": "orchestrator-close",
            "expected_project_revision": current.ref.revision,
            "generation": 1,
            "orchestrator_assignment": orchestrator.ref.to_dict(),
            "evidence": evidence,
        },
        request_id="terminal",
        actor="orchestrator",
    )
    assert replay["outcome"] == "replayed"
    assert replay["replayed"] is True
    store.close()


def test_stale_and_foreign_lifecycle_requests_do_not_mutate_owner(tmp_path):
    store, owner, project, manager, _orchestrator = _fixture(tmp_path)
    operations = owner.consumer_operations()
    before = dict(store.consumer().snapshot_counts())
    stale = operations.execute(
        "work.lifecycle.transition",
        {
            "project_ref": {**project.ref.to_dict(), "revision": "rev-0"},
            "action": "activate",
            "expected_project_revision": "rev-0",
            "generation": 1,
            "manager_assignment": manager.ref.to_dict(),
        },
        request_id="stale",
        actor="manager",
    )
    assert stale["outcome"] == "error"
    assert "stale project revision" in stale["error"]["message"]
    foreign = _transition(operations, project, manager, request_id="foreign", action="activate", actor="other")
    assert foreign["outcome"] == "error"
    assert "assigned principal" in foreign["error"]["message"]
    assert dict(store.consumer().snapshot_counts()) == before
    store.close()


def test_lifecycle_read_reopens_from_canonical_store(tmp_path):
    store, owner, project, manager, _orchestrator = _fixture(tmp_path)
    operations = owner.consumer_operations()
    _transition(operations, project, manager, request_id="restart-activate", action="activate")
    expected = owner.graph.get(project.ref).ref
    store.close()

    reopened = _store(tmp_path / "owner.sqlite", create=False)
    reopened_owner = PortfolioOwnerBootstrap(
        reopened,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
    )
    read = reopened_owner.consumer_operations().execute(
        "work.lifecycle.read", {"project_ref": expected.to_dict()}, request_id="restart-read", actor="manager"
    )
    assert read["outcome"] == "read"
    assert read["lifecycle"] == "active"
    assert read["transition"]["request_id"] == "restart-activate"
    assert read["reconciliation"]["status"] == "pending"
    reopened.close()
