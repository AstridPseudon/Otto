"""Focused BK-04 derived inbox and restart/reconciliation proof."""

from __future__ import annotations

from copy import deepcopy

from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


AUTHORITY = "bk04-owner"


def _store(tmp_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store

    store = Store.create(tmp_path / "bk04.sqlite", authority=AUTHORITY)
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
    project = api.create_pending(actor="manager", request_id="project", edit={"title": "Inbox project"})
    applied = owner.sheet.apply(
        project["project_ref"],
        {"tasks": [{"id": "task", "title": "Inbox task"}]},
        logical_request_key="task-sheet",
        actor=owner.owner_actor,
    )
    task = next(iter(applied.mappings.values()))
    task_record = owner.graph.get(task)
    assignment = owner.assignments.assign(
        task_record.ref,
        role="manager",
        principal="manager",
        logical_request_key="manager-assignment",
        actor=owner.owner_actor,
    )
    return store, owner, api, owner.graph.get(project["project_ref"]), task_record, assignment


def test_unknown_terminal_is_visible_and_read_does_not_acknowledge(tmp_path):
    store, owner, api, project, task, assignment = _fixture(tmp_path)
    owner.assignments.append_result(
        assignment.ref,
        {"attempt": {"outcome": "unknown", "native_session_id": "native-unknown", "reconciliation": "lost response"}},
        expected_generation=assignment.generation,
        logical_request_key="unknown-result",
        actor=owner.owner_actor,
    )
    before = dict(store.consumer().snapshot_counts())
    first = api.manager_inbox(project.ref, actor="manager")
    after = dict(store.consumer().snapshot_counts())

    assert first["schema"] == "otto.manager-inbox.v1"
    assert any(item["status"] == "lost_response" for item in first["attempts"])
    assert any(item["reason"] == "unknown_attempt_blocks_retry" for item in first["attention"])
    assert first["dispatch"] is False and first["launch"] is False
    assert first["acknowledged"] is False and first["read_side_effects"] is False
    assert before == after
    store.close()


def test_cursor_replay_is_repeat_safe_and_terminal_states_remain_distinct(tmp_path):
    store, owner, api, project, task, assignment = _fixture(tmp_path)
    owner.assignments.append_result(
        assignment.ref,
        {"attempt": {"outcome": "succeeded", "native_session_id": "native-success"}},
        expected_generation=assignment.generation,
        logical_request_key="success-result",
        actor=owner.owner_actor,
    )
    first = api.manager_inbox(project.ref, actor="manager", limit=100)
    second = api.manager_inbox(project.ref, actor="manager", cursor=first["reconciliation"]["cursor"], limit=100)

    assert any(item["status"] == "success" and item["terminal"] for item in first["attempts"])
    assert any(item["reason"] == "manager_assessment_required" for item in first["attention"])
    assert second["reconciliation"]["event_ids"] == []
    assert second["reconciliation"]["status"] == "advanced"
    store.close()


def test_prerequisite_revision_marks_only_dependent_task_stale(tmp_path):
    store = _store(tmp_path)
    owner = PortfolioOwnerBootstrap(store, binding=HerzchenBindingConfig(AUTHORITY, "credential"), owner_actor="manager")
    api = OttoPortfolio(owner.consumer_operations())
    project = api.create_pending(actor="manager", request_id="project", edit={"title": "Prerequisites"})
    sheet = owner.sheet.apply(
        project["project_ref"],
        {"tasks": [{"id": "prerequisite", "title": "Prerequisite"}, {"id": "dependent", "title": "Dependent", "dependencies": ["prerequisite"]}]},
        logical_request_key="tasks",
        actor=owner.owner_actor,
    )
    prerequisite = owner.graph.get(sheet.mappings["prerequisite"])
    owner.graph.revise(prerequisite.ref, title="Revised prerequisite", logical_request_key="revise-prerequisite", actor=owner.owner_actor)
    result = api.manager_inbox(project["project_ref"], actor="manager")
    dependent = next(item for item in result["tasks"] if item["ref"]["id"] == sheet.mappings["dependent"].id)

    assert dependent["stale"] is True
    assert dependent["eligibility"] == "recompute-needed"
    assert dependent["dispatch"] is False and dependent["launch"] is False
    store.close()


def test_vanished_native_handle_keeps_result_obligation(tmp_path):
    store, owner, api, project, task, assignment = _fixture(tmp_path)
    owner.assignments.append_result(
        assignment.ref,
        {"attempt": {"outcome": "failed", "native_handle_missing": True, "reconciliation": "handle vanished"}, "result": {"value": "retained"}},
        expected_generation=assignment.generation,
        logical_request_key="vanished-result",
        actor=owner.owner_actor,
    )
    result = api.manager_inbox(project.ref, actor="manager")
    observation = next(item for item in result["attempts"] if item["source_ref"]["id"].startswith("result-"))

    assert observation["status"] == "failure"
    assert observation["native_handle_state"] == "vanished"
    assert observation["result_retained"] is True
    assert any(item["source_ref"] == observation["source_ref"] for item in result["attention"])
    store.close()


def test_project_manager_scope_revision_advance_keeps_existing_manager(tmp_path):
    """A project manager follows identity while retaining its pinned scope."""
    store = _store(tmp_path)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(AUTHORITY, "credential"),
        owner_actor="manager",
    )
    api = OttoPortfolio(owner.consumer_operations())
    project = api.create_pending(actor="manager", request_id="project", edit={"title": "Revision advance"})
    initial_project = owner.graph.get(project["project_ref"])
    assignment = owner.assignments.assign(
        initial_project.ref,
        role="manager",
        principal="manager",
        logical_request_key="manager-assignment",
        actor=owner.owner_actor,
    )
    applied = owner.sheet.apply(
        initial_project.ref,
        {"tasks": [{"id": "task", "title": "Current task"}]},
        logical_request_key="task-sheet",
        actor=owner.owner_actor,
    )
    current_project = owner.graph.get(applied.project.ref)

    before = dict(store.consumer().snapshot_counts())
    result = api.manager_inbox(current_project.ref, actor="manager")
    after = dict(store.consumer().snapshot_counts())

    assert result["manager"]["count"] == 1
    assert result["manager"]["assignments"][0]["source_ref"] == assignment.ref.to_dict()
    assert result["manager"]["assignments"][0]["scope_ref"]["revision"] == initial_project.ref.revision
    assert result["manager"]["assignments"][0]["scope_ref"]["id"] == current_project.ref.id
    assert current_project.ref.revision != initial_project.ref.revision
    assert result["read_side_effects"] is False
    assert before == after
    store.close()


def test_competing_project_managers_remain_distinct_and_visible(tmp_path):
    store, owner, api, project, _task, first = _fixture(tmp_path)
    second = owner.assignments.assign(
        project.ref,
        role="manager",
        principal="second-manager",
        logical_request_key="second-manager",
        actor=owner.owner_actor,
    )
    result = api.manager_inbox(project.ref, actor="manager")
    assignment_ids = {item["source_ref"]["id"] for item in result["manager"]["assignments"]}
    assert result["manager"]["count"] == 2
    assert {first.ref.id, second.ref.id} <= assignment_ids
    store.close()
