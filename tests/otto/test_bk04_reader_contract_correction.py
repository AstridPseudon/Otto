"""Redacted ORC-02 typed observation contract proof for BK-04."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from otto.portfolio.inbox import derive_manager_inbox


FIXTURE = Path(__file__).with_name("fixtures") / "bk04_orc02_redacted.json"


def _read_fixture():
    fixture = json.loads(FIXTURE.read_text())
    project = fixture["project"]
    for observation in fixture["observations"]:
        project["observed"]["results" if observation["kind"] == "result" else "reports"].append(
            {
                "ref": observation["ref"],
                "assignment": observation["assignment"],
                "generation": observation["generation"],
                "payload": observation["value"],
            }
        )
    return {"project": project, "tasks": fixture["tasks"]}


def test_typed_result_attachment_correction_and_bookkeeping_join_once():
    result = derive_manager_inbox(_read_fixture(), limit=100)

    assert len(result["attempts"]) == 2
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    unknown = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-unknown")
    assert retained["native_id"] == "native-redacted-orc02"
    assert retained["assessed"] is True
    assert retained["assessment_disposition"] == "held"
    assert [entry["source_ref"]["id"] for entry in retained["verification"]["history"]] == [
        "report-redacted-verification-original",
        "report-redacted-verification-corrected",
    ]
    assert retained["verification"]["history"][0]["result_evidence_sha256"] == "1" * 64
    assert retained["verification"]["history"][1]["result_evidence_sha256"] == "2" * 64
    assert unknown["assessed"] is False
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["joined"] is True
    assert len(result["bookkeeping"]) == 1
    assert result["bookkeeping"][0]["status"] == "pending"
    assert [item["reason"] for item in result["attention"]].count("held_assessment_requires_recovery") == 1
    assert [item["reason"] for item in result["attention"]].count("unknown_attempt_blocks_retry") == 1
    assert result["dispatch"] is False and result["launch"] is False
    assert result["acknowledged"] is False and result["read_side_effects"] is False


def test_n01_n04_legacy_unpinned_result_context_joins_pinned_attachment_but_wrong_task_does_not():
    view = _read_fixture()
    worker_result = next(item for item in view["project"]["observed"]["results"] if item["ref"]["id"] == "result-redacted-orc02")
    worker_result["payload"]["project_ref"] = "project-redacted-orc02"
    worker_result["payload"]["task_ref"] = "task-redacted-orc02"
    joined = derive_manager_inbox(view, limit=100)
    attachment = next(item for item in joined["attachments"] if item["source_ref"]["id"] == "report-redacted-attachment")
    assert attachment["joined"] is True
    assert attachment["task_ref"]["revision"] == "rev-1"

    foreign = deepcopy(view)
    next(item for item in foreign["project"]["observed"]["reports"] if item["ref"]["id"] == "report-redacted-attachment")["payload"]["task_ref"] = "foreign-task@rev-1"
    rejected = derive_manager_inbox(foreign, limit=100)
    attachment = next(item for item in rejected["attachments"] if item["source_ref"]["id"] == "report-redacted-attachment")
    attempt = next(item for item in rejected["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert attachment["joined"] is False
    assert "native_id_source_ref" not in attempt
    assert attempt.get("native_identity_observed") is not True
    assert any(item["reason"] == "native_attachment_without_exact_result" and item["source_ref"]["id"] == "report-redacted-attachment" for item in rejected["attention"])


def test_bare_assessed_flag_and_wrong_generation_do_not_discharge_result():
    view = _read_fixture()
    correction = next(
        item["payload"]
        for item in view["project"]["observed"]["reports"]
        if item["payload"].get("schema", "").endswith("manager_verification_correction.v1")
    )
    correction["assignment_generation"] = 99
    correction["assessed"] = True
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    # The valid original remains current; the wrong-generation correction is
    # retained as a visible mismatch and cannot replace it.
    assert retained["assessed"] is True
    assert any(item["reason"] == "verification_target_mismatch" for item in result["attention"])


def _verification_reports(view):
    return [item["payload"] for item in view["project"]["observed"]["reports"] if "manager_verification" in item["payload"].get("schema", "")]


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_refs", [None]),
        ("evidence_refs", [""]),
        ("evidence_refs", [{}]),
        ("evidence_hashes", {"sha256": "bad"}),
        ("evidence_hashes", {"tests": ""}),
        ("worker_result_evidence_sha256", "not-a-sha256"),
    ],
)
def test_n02_malformed_evidence_is_visible_and_cannot_replace_predecessor(field, value):
    view = _read_fixture()
    correction = _verification_reports(view)[1]
    correction[field] = value
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessed"] is True
    assert retained["assessment_ref"]["id"] == "report-redacted-verification-original"
    rejected = next(item for item in retained["verification"]["history"] if item["source_ref"]["id"] == "report-redacted-verification-corrected")
    assert rejected["evidence_valid"] is False
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])


@pytest.mark.parametrize(
    "result_ref",
    [
        {"authority": "ast02-controller-root-v4", "kind": "wrk.result", "id": "result-redacted-orc02"},
        {"authority": "ast02-controller-root-v4", "kind": "wrk.result", "id": "result-redacted-orc02", "revision": "rev-99"},
        {"authority": "foreign", "kind": "wrk.result", "id": "result-redacted-orc02", "revision": "rev-1"},
    ],
)
def test_n03_missing_or_foreign_result_ref_remains_unmatched(result_ref):
    view = _read_fixture()
    _verification_reports(view)[1]["result_ref"] = result_ref
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessed"] is True
    assert retained["assessment_ref"]["id"] == "report-redacted-verification-original"
    assert any(item["source_ref"]["id"] == "report-redacted-verification-corrected" for item in result["diagnostics"])


def test_n04_wrong_task_scope_does_not_join_worker_result():
    view = _read_fixture()
    _verification_reports(view)[1]["task_ref"] = "other-task@rev-1"
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessed"] is True
    assert retained["assessment_ref"]["id"] == "report-redacted-verification-original"
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])


def test_n05_branch_and_reverse_order_have_deterministic_conflict_history():
    view = _read_fixture()
    reports = view["project"]["observed"]["reports"]
    correction = next(item for item in reports if item["payload"].get("schema", "").endswith("manager_verification_correction.v1"))
    branch = deepcopy(correction)
    branch["ref"] = {**branch["ref"], "id": "report-redacted-verification-branch"}
    branch["payload"] = deepcopy(branch["payload"])
    reports.append(branch)
    reports.reverse()
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessed"] is False
    assert len(retained["verification"]["history"]) == 3
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])


def test_n05_missing_predecessor_and_cycle_are_retained_without_guessing():
    missing = _read_fixture()
    reports = _verification_reports(missing)
    reports[1]["correction_of_report_ref"] = {"authority": "ast02-controller-root-v4", "kind": "wrk.report", "id": "missing-predecessor", "revision": "rev-1"}
    result = derive_manager_inbox(missing, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert len(retained["verification"]["history"]) == 2
    assert retained["verification"]["chain_conflict"] is True
    assert retained["verification"]["current_ref"]["id"] == "report-redacted-verification-original"
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])

    cycle = _read_fixture()
    cycle_reports = _verification_reports(cycle)
    cycle_reports[0]["correction_of_report_ref"] = "report-redacted-verification-corrected@rev-1"
    cycle_reports[1]["correction_of_report_ref"] = "report-redacted-verification-original@rev-1"
    cycled = derive_manager_inbox(cycle, limit=100)
    retained = next(item for item in cycled["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert len(retained["verification"]["history"]) == 2
    assert retained["verification"]["current_ref"] is None
    assert retained["assessed"] is False
    assert any(item["reason"] == "verification_conflict" for item in cycled["attention"])


def test_n06_nested_manager_completion_keeps_manager_and_worker_fields_separate():
    view = _read_fixture()
    reports = view["project"]["observed"]["reports"]
    reports[:] = [item for item in reports if "manager_verification" not in item["payload"].get("schema", "")]
    reports.append({
        "ref": {"authority": "ast02-controller-root-v4", "kind": "wrk.report", "id": "report-manager-completion", "revision": "rev-1"},
        "assignment": {"authority": "ast02-controller-root-v4", "kind": "wrk.assignment", "id": "manager-redacted-orc02", "revision": "rev-1"},
        "generation": 7,
        "payload": {"kind": "manager-completion", "completion": {
            "manager": "manager-actor", "assignment_ref": {"authority": "ast02-controller-root-v4", "kind": "wrk.assignment", "id": "manager-redacted-orc02", "revision": "rev-1"}, "generation": 7,
            "project_ref": "project-redacted-orc02@rev-1", "task_ref": "task-redacted-orc02@rev-1", "result_ref": "result-redacted-orc02@rev-1", "disposition": "held",
            "evidence_refs": [{"authority": "ast02-controller-root-v4", "kind": "work.task", "id": "task-redacted-orc02", "revision": "rev-1"}], "evidence_hashes": {"tests": "A" * 64},
        }},
    })
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessed"] is True
    assert retained["verification"]["manager_assignment_ref"]["id"] == "manager-redacted-orc02"
    assert retained["verification"]["manager_generation"] == 7
    assert retained["verification"]["history"][0]["result_ref"]["id"] == "result-redacted-orc02"


def test_n07_pending_review_completion_is_bookkeeping_only():
    view = _read_fixture()
    pending = next(item for item in view["project"]["observed"]["reports"] if "hourly" in item["payload"].get("schema", ""))
    pending["payload"]["completion"] = {"result_ref": "result-redacted-orc02@rev-1", "disposition": "accepted"}
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessment_disposition"] == "held"
    assert result["bookkeeping"][0]["status"] == "pending"


def test_n08_claimed_manager_and_hash_remain_structural_unknown():
    view = _read_fixture()
    correction = _verification_reports(view)[1]
    correction["assessed"] = True
    correction["manager"] = "claimed-manager"
    correction["worker_result_evidence_sha256"] = "3" * 64
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["verification"]["manager_authority"] == "unknown"
    assert retained["verification"]["evidence_verification"] == "unknown"


def test_n08_accepted_unknown_authority_or_evidence_keeps_stable_attention():
    view = _read_fixture()
    correction = _verification_reports(view)[1]
    correction["disposition"] = "accepted-for-task"
    correction["manager"] = "claimed-manager"
    correction["worker_result_evidence_sha256"] = "3" * 64
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["source_ref"]["id"] == "result-redacted-orc02")
    assert retained["assessment_disposition"] == "accepted-for-task"
    assert retained["verification"]["manager_authority"] == "unknown"
    assert retained["verification"]["evidence_verification"] == "unknown"
    assert any(item["reason"] == "accepted_assessment_requires_provenance" for item in result["attention"])


def test_n09_repeat_read_is_stable_and_does_not_duplicate_obligations():
    view = _read_fixture()
    first = derive_manager_inbox(view, limit=100)
    second = derive_manager_inbox(deepcopy(view), limit=100)
    assert first["source_refs"] == second["source_refs"]
    assert first["attention"] == second["attention"]
    assert first["dispatch"] is False and first["launch"] is False and first["read_side_effects"] is False


def _owner_completion_view(tmp_path, *, manager_scope="task"):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store
    from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap

    store = Store.create(tmp_path / "bk04-owner.sqlite", authority="bk04-owner")
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    owner = PortfolioOwnerBootstrap(store, binding=HerzchenBindingConfig("bk04-owner", "credential"), owner_actor="manager")
    api = OttoPortfolio(owner.consumer_operations())
    project = api.create_pending(actor="manager", request_id="project", edit={"title": "Owner completion"})
    applied = owner.sheet.apply(project["project_ref"], {"tasks": [{"id": "task", "title": "Owner task"}]}, logical_request_key="tasks", actor=owner.owner_actor)
    task = owner.graph.get(next(iter(applied.mappings.values())))
    project_record = owner.graph.get(project["project_ref"])
    worker = owner.assignments.assign(task.ref, role="execution", principal="worker", logical_request_key="worker", actor=owner.owner_actor)
    manager_target = task.ref if manager_scope == "task" else project_record.ref
    manager = owner.assignments.assign(manager_target, role="manager", principal="manager", logical_request_key=f"manager-{manager_scope}", actor=owner.owner_actor)
    worker_result = owner.assignments.append_result(worker.ref, {"attempt": {"outcome": "succeeded", "worker_native_id": "native-owner"}}, expected_generation=worker.generation, logical_request_key="result", actor=owner.owner_actor)
    completion = api.complete_task(
        request_id="owner-completion",
        actor="manager",
        project_ref=project_record.ref.to_dict(),
        task_ref=task.ref.to_dict(),
        assignment_ref=manager.ref.to_dict(),
        expected_generation=manager.generation,
        expected_project_revision=project_record.ref.revision,
        expected_task_revision=task.ref.revision,
        disposition="accepted-for-task",
        evidence_refs=[task.ref.to_dict()],
        evidence_hashes={"tests": "a" * 64},
        gate_refs=[project_record.ref.to_dict()],
        result_ref=worker_result.ref.to_dict(),
    )
    assert completion["outcome"] == "completed"
    exported = owner.sheet.export(project_record.ref)
    return store, exported.to_dict() if hasattr(exported, "to_dict") else exported, manager


def test_n06_n08_owner_completion_preserves_worker_linkage_and_public_manager_provenance(tmp_path):
    store, view, manager = _owner_completion_view(tmp_path)
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["observation_kind"] == "result")
    verification = retained["verification"]
    assert verification["manager_assignment_ref"]["id"] == manager.ref.id
    assert verification["manager_generation"] == manager.generation
    assert verification["manager_authority"] == "verified"
    assert verification["history"][0]["result_ref"]["id"] == retained["result_ref"]["id"]
    assert verification["history"][0]["worker_assignment_ref"]["id"] == retained["assignment_ref"]["id"]
    assert verification["history"][0]["evidence_refs"][0]["revision"] == "rev-1"
    assert retained["task_ref"]["id"].startswith("task-")
    assert any(item["reason"] == "accepted_assessment_requires_provenance" for item in result["attention"])
    assert result["dispatch"] is False and result["launch"] is False and result["acknowledged"] is False
    store.close()


def test_n06_project_scoped_owner_completion_verifies_manager_binding(tmp_path):
    store, view, manager = _owner_completion_view(tmp_path, manager_scope="project")
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["observation_kind"] == "result")
    verification = retained["verification"]
    assert verification["manager_assignment_ref"]["id"] == manager.ref.id
    assert verification["manager_authority"] == "verified"
    assert "manager_scope_mismatch" not in verification["history"][0]["manager_binding_diagnostics"]
    store.close()


def test_n06_foreign_project_manager_binding_is_rejected(tmp_path):
    store, view, manager = _owner_completion_view(tmp_path, manager_scope="project")
    project_assignment = view["project"]["observed"]["assignments"][0]
    project_assignment["payload"]["scope"] = {
        "authority": "bk04-owner",
        "kind": "work.project",
        "id": "foreign-project",
        "revision": "rev-1",
    }
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["observation_kind"] == "result")
    verification = retained["verification"]
    assert verification["manager_assignment_ref"]["id"] == manager.ref.id
    assert verification["manager_authority"] == "mismatch"
    assert "manager_scope_mismatch" in verification["history"][0]["manager_binding_diagnostics"]
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])
    store.close()


def test_n06_foreign_task_manager_binding_is_rejected(tmp_path):
    store, view, manager = _owner_completion_view(tmp_path, manager_scope="task")
    assignment = next(
        item for task in view["tasks"] for item in task["observed"]["assignments"]
        if item["ref"]["id"] == manager.ref.id
    )
    assignment["payload"]["scope"] = {
        "authority": "bk04-owner",
        "kind": "work.task",
        "id": "foreign-task",
        "revision": "rev-1",
    }
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["observation_kind"] == "result")
    verification = retained["verification"]
    assert verification["manager_assignment_ref"]["id"] == manager.ref.id
    assert verification["manager_authority"] == "mismatch"
    assert "manager_scope_mismatch" in verification["history"][0]["manager_binding_diagnostics"]
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])
    store.close()


def test_n04_manager_principal_conflict_is_mismatch_and_retains_attention(tmp_path):
    store, view, _manager = _owner_completion_view(tmp_path)
    report = view["tasks"][0]["observed"]["reports"][0]
    report["payload"]["value"]["completion"]["manager"] = "foreign-manager"
    result = derive_manager_inbox(view, limit=100)
    retained = next(item for item in result["attempts"] if item["observation_kind"] == "result")
    assert retained["verification"]["manager_authority"] == "mismatch"
    assert any(item["reason"] == "verification_conflict" for item in result["attention"])
    assert any("manager_principal_mismatch" in item["diagnostic_reasons"] for item in retained["verification"]["history"])
    store.close()
