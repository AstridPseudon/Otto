"""Supported owner-side prerequisite revision refresh proof."""

from __future__ import annotations

from pathlib import Path

from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap

from test_bk04_manager_inbox import _store


AUTHORITY = "bk04-owner"


def _fixture(tmp_path: Path):
    store = _store(tmp_path)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
    )
    api = OttoPortfolio(owner.consumer_operations())
    project = api.create_pending(actor="manager", request_id="project", edit={"title": "Refresh"})
    applied = owner.sheet.apply(
        project["project_ref"],
        {"tasks": [{"id": "prerequisite", "title": "Prerequisite"}, {"id": "dependent", "title": "Dependent", "dependencies": ["prerequisite"]}]},
        logical_request_key="tasks",
        actor=owner.owner_actor,
    )
    prerequisite = owner.graph.get(applied.mappings["prerequisite"])
    dependent = owner.graph.get(applied.mappings["dependent"])
    owner.graph.revise(prerequisite.ref, title="Completed prerequisite revision", logical_request_key="revise-prerequisite", actor=owner.owner_actor)
    return store, owner, api, owner.graph.get(project["project_ref"]), owner.graph.get(prerequisite.ref), owner.graph.get(dependent.ref)


def test_supported_refresh_clears_stale_history_and_replays_without_dispatch(tmp_path):
    store, owner, api, project, prerequisite, dependent = _fixture(tmp_path)
    operation = owner.consumer_operations()
    payload = {"task_ref": dependent.ref.to_dict(), "dependency_ref": prerequisite.ref.to_dict()}

    before = api.manager_inbox(project.ref, actor="manager")
    stale = next(item for item in before["tasks"] if item["ref"]["id"] == dependent.ref.id)
    assert stale["stale"] is True
    event_count = store.consumer().snapshot_counts()["events"]

    refreshed = operation.execute("work.task.dependency-refresh", payload, request_id="refresh:dependent", actor="manager")
    assert refreshed["outcome"] == "refreshed"
    assert refreshed["replayed"] is False
    assert refreshed["acknowledged_revision"] == prerequisite.ref.revision

    after = api.manager_inbox(refreshed["project_ref"], actor="manager")
    current = next(item for item in after["tasks"] if item["ref"]["id"] == dependent.ref.id)
    assert current["stale"] is False
    assert current["dependencies"][0]["expected_revision"] == prerequisite.ref.revision
    assert store.consumer().snapshot_counts()["events"] == event_count + 1

    replayed = operation.execute("work.task.dependency-refresh", payload, request_id="refresh:dependent", actor="manager")
    assert replayed["outcome"] == "replayed"
    assert replayed["replayed"] is True
    assert replayed["event_ids"] == refreshed["event_ids"]
    assert store.consumer().snapshot_counts()["events"] == event_count + 1
    store.close()


def test_refresh_marker_becomes_stale_when_prerequisite_advances_again(tmp_path):
    store, owner, api, project, prerequisite, dependent = _fixture(tmp_path)
    operation = owner.consumer_operations()
    operation.execute(
        "work.task.dependency-refresh",
        {"task_ref": dependent.ref.to_dict(), "dependency_ref": prerequisite.ref.to_dict()},
        request_id="refresh:dependent",
        actor="manager",
    )
    advanced = owner.graph.revise(prerequisite.ref, title="Prerequisite advanced again", logical_request_key="advance-again", actor=owner.owner_actor)
    result = api.manager_inbox(owner.graph.get(project.ref).ref, actor="manager")
    current = next(item for item in result["tasks"] if item["ref"]["id"] == dependent.ref.id)
    assert current["stale"] is True
    assert current["eligibility"] == "recompute-needed"
    assert current["dependencies"][0]["expected_revision"] == prerequisite.ref.revision
    store.close()
