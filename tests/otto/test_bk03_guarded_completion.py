"""Focused BK-03 manager guarded completion proof."""

from __future__ import annotations

from copy import deepcopy

import pytest

from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


AUTHORITY = "bk03-owner"


def _store(tmp_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store

    path = tmp_path / "bk03.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    return store


def _fixture(tmp_path):
    store = _store(tmp_path)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
    )
    api = OttoPortfolio(owner.consumer_operations())
    project = api.create_pending(actor="manager", request_id="project", edit={"title": "Managed project"})
    applied = owner.sheet.apply(
        project["project_ref"],
        {"tasks": [{"id": "task", "title": "Managed task"}]},
        logical_request_key="task-sheet",
        actor=owner.owner_actor,
    )
    task = next(iter(applied.mappings.values()))
    current_project = owner.graph.get(project["project_ref"])
    current_task = owner.graph.get(task)
    assignment = owner.assignments.assign(
        current_project.ref,
        role="manager",
        principal="manager",
        logical_request_key="manager-assignment",
        actor=owner.owner_actor,
    )
    return store, owner, api, current_project, current_task, assignment


def _close_kwargs(project, task, assignment):
    return dict(
        project_ref=project.ref.to_dict(),
        task_ref=task.ref.to_dict(),
        assignment_ref=assignment.ref.to_dict(),
        expected_generation=assignment.generation,
        expected_project_revision=project.ref.revision,
        expected_task_revision=task.ref.revision,
        disposition="accepted-for-task",
        evidence_refs=[task.ref.to_dict()],
        evidence_hashes={"tests": "a" * 64},
        gate_refs=[project.ref.to_dict()],
    )


def test_missing_gate_or_evidence_hash_is_held_without_mutation(tmp_path):
    store, owner, api, project, task, assignment = _fixture(tmp_path)
    before = len(store.list_events())
    values = _close_kwargs(project, task, assignment)
    values.pop("gate_refs")
    held = api.complete_task(request_id="missing-gate", actor="manager", **values)
    assert held["outcome"] == "held"
    assert held["status"] == "unknown"
    assert len(store.list_events()) == before
    assert owner.graph.get(task.ref).lifecycle.value == "pending"
    store.close()


def test_worker_assignment_cannot_close_and_valid_manager_close_replays(tmp_path):
    store, owner, api, project, task, manager_assignment = _fixture(tmp_path)
    worker = owner.assignments.assign(
        task.ref,
        role="execution",
        principal="worker",
        logical_request_key="worker-assignment",
        actor=owner.owner_actor,
    )
    values = _close_kwargs(project, task, worker)
    rejected = api.complete_task(request_id="worker-close", actor="worker", **values)
    assert rejected["outcome"] == "held"
    assert owner.graph.get(task.ref).lifecycle.value == "pending"

    values = _close_kwargs(project, task, manager_assignment)
    first = api.complete_task(request_id="manager-close", actor="manager", **values)
    assert first["outcome"] == "completed"
    assert owner.graph.get(task.ref).lifecycle.value == "completed"
    event_count = len(store.list_events())
    replay = api.complete_task(request_id="manager-close", actor="manager", **deepcopy(values))
    assert replay["outcome"] == "replayed"
    assert replay["receipt"] == first["receipt"]
    assert len(store.list_events()) == event_count
    changed = dict(values, disposition="correction-needed")
    conflict = api.complete_task(request_id="manager-close", actor="manager", **changed)
    assert conflict["outcome"] == "error"
    assert conflict["error"]["code"] == "replay_conflict"
    store.close()


def test_stale_task_revision_is_rejected_before_owner_mutation(tmp_path):
    store, owner, api, project, task, assignment = _fixture(tmp_path)
    values = _close_kwargs(project, task, assignment)
    values["expected_task_revision"] = "rev-99"
    result = api.complete_task(request_id="stale-close", actor="manager", **values)
    assert result["outcome"] == "error"
    assert result["error"]["code"] == "stale_completion"
    assert owner.graph.get(task.ref).lifecycle.value == "pending"
    store.close()


def test_project_sheet_cannot_bypass_manager_guard_with_completed_lifecycle(tmp_path):
    from herzchen.domains.work.model import WorkValidationError

    store, owner, _api, project, task, _assignment = _fixture(tmp_path)
    with pytest.raises(WorkValidationError, match="complete_managed_task"):
        owner.sheet.apply(
            project.ref,
            {"tasks": [{"id": task.id, "lifecycle": "completed"}]},
            logical_request_key="sheet-bypass",
            actor=owner.owner_actor,
        )
    assert owner.graph.get(task.ref).lifecycle.value == "pending"
    store.close()
