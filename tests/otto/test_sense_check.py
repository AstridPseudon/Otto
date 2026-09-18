from copy import deepcopy

import pytest

from otto.portfolio.sense_check import SenseCheckError, hourly_sense_check


EXPECTED = {
    "expected_project_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "project-dc5b1e554f240b0997bf065ed250",
        "kind": "work.project",
        "revision": "rev-2",
    },
    "expected_task_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "task-342e12f50d1667f2c413be6586be",
        "kind": "work.task",
        "revision": "rev-1",
    },
    "expected_assignment_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "assignment-9c87869471bbfbdb7bdae3efe2b9",
        "kind": "wrk.assignment",
        "revision": "rev-1",
    },
    "expected_generation": 1,
    "observed_custody": {
        "project_ref": {
            "authority": "ast02-controller-root-v4",
            "id": "project-dc5b1e554f240b0997bf065ed250",
            "kind": "work.project",
            "revision": "rev-2",
        },
        "task_ref": {
            "authority": "ast02-controller-root-v4",
            "id": "task-342e12f50d1667f2c413be6586be",
            "kind": "work.task",
            "revision": "rev-1",
        },
        "assignment_ref": {
            "authority": "ast02-controller-root-v4",
            "id": "assignment-9c87869471bbfbdb7bdae3efe2b9",
            "kind": "wrk.assignment",
            "revision": "rev-1",
        },
        "generation": 1,
    },
    "manager_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "01a0b1f6-e8a5-72a0-919e-e5602e3dbc42",
        "kind": "manager.conversation",
        "revision": "current",
    },
    "worker_observation": {
        "native_id": "01a0b0f1-ae0d-7993-88ad-b17c6fc490b9",
        "requested_model": "gpt-5.6-luna",
        "requested_reasoning": "high",
        "observed_model": "gpt-5.6-luna",
        "observed_reasoning": "xhigh",
        "role": "worker",
        "owner_write": False,
    },
    "orc04_prerequisite": {
        "authority": "ast02-controller-root-v4",
        "kind": "completed_task",
        "id": "task-e0716950bd89bca14264f45a5cec@rev-2",
        "task_id": "task-e0716950bd89bca14264f45a5cec",
        "state": "completed",
    },
    "brief_sha256": "d6d9c010d2856bb256fbc34a0f264d15c55684d2ba80b7da3fe2552d1d4d8cc1",
}


MANDATE = {
    "revision": "orc05-active-20260918",
    "source": "root_transport",
    "trusted": True,
    "state": "active",
    "mode": "coordination",
    "effect_class": "ordinary_execution",
}
ACTION = {
    "id": "action-orc05-sense-check",
    "operation": "verify_orc04_delta_and_reconcile_same_manager",
    "admitted": True,
    "bounded": True,
    "route": "existing_manager_worker_path",
}
PREVIOUS = {
    "manager_phase": "after_orc04",
    "orc04_owner_review": "pending",
    "p1_open": ["BK-C06", "BK-C07"],
    "checked_at": "2026-09-18T10:00:00Z",
}
CURRENT = {
    **PREVIOUS,
    "orc04_owner_review": "evidence_ready",
    "checked_at": "2026-09-18T11:00:00Z",
}


def run(previous_status=PREVIOUS, current_status=CURRENT, **overrides):
    args = deepcopy(EXPECTED)
    args.update(overrides)
    return hourly_sense_check(
        previous_status=previous_status,
        current_status=current_status,
        mandate=MANDATE,
        action=ACTION,
        **args,
    )


def test_meaningful_delta_admits_one_same_manager_action_without_acceptance():
    result = run()
    assert result["outcome"] == "manager_action_admitted"
    assert result["manager_action"]["route"] == "existing_manager_worker_path"
    assert result["manager_action"]["dispatch"] is False
    assert result["manager_action"]["worker_native_id"] == EXPECTED["worker_observation"]["native_id"]
    assert result["notify_manager"] is True
    assert result["project_acceptance"] is False
    assert result["global_project_acceptance"] is False
    assert result["p2_code_oracle_used"] == 0


def test_observation_only_change_is_quiet():
    result = run(previous_status=PREVIOUS, current_status={**PREVIOUS, "checked_at": "2026-09-18T12:00:00Z"})
    assert result["outcome"] == "unchanged_quiet"
    assert result["status_review"]["changed"] is False
    assert result["manager_action"] is None
    assert result["notify_manager"] is False


def test_duplicate_action_is_a_noop_and_stale_custody_is_held():
    first = run()
    second = run(prior_results=[first])
    assert second["outcome"] == "replayed_noop"
    assert second["manager_action"] is None
    assert second["operation_sha256"] == first["operation_sha256"]
    stale = deepcopy(EXPECTED["observed_custody"])
    stale["assignment_ref"]["revision"] = "rev-9"
    with pytest.raises(SenseCheckError, match="assignment_ref"):
        run(observed_custody=stale)


def test_unfinished_orc04_dependency_is_held_for_p2_manager():
    dependency = deepcopy(EXPECTED["orc04_prerequisite"])
    dependency["state"] = "in_progress"
    result = run(orc04_prerequisite=dependency)
    assert result["outcome"] == "held_dependency"
    assert result["manager_action"] is None
    assert result["notify_manager"] is True
    assert result["project_acceptance"] is False


def test_repeated_unfinished_dependency_is_quiet_after_unchanged_and_replay_filtering():
    dependency = deepcopy(EXPECTED["orc04_prerequisite"])
    dependency["state"] = "in_progress"
    unchanged = run(
        previous_status=PREVIOUS,
        current_status={**PREVIOUS, "checked_at": "2026-09-18T12:00:00Z"},
        orc04_prerequisite=dependency,
    )
    assert unchanged["outcome"] == "held_dependency_quiet"
    assert unchanged["notify_manager"] is False
    first = run(orc04_prerequisite=dependency)
    replay = run(orc04_prerequisite=dependency, prior_results=[first])
    assert replay["outcome"] == "held_dependency_replayed_noop"
    assert replay["notify_manager"] is False
    assert replay["operation_sha256"] == first["operation_sha256"]
