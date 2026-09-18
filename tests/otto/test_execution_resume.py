from copy import deepcopy
import json
from pathlib import Path

import pytest

from otto.portfolio.execution_resume import ExecutionResumeError, execute_selected_packet


PACKET_PATH = Path(__file__).parent / "fixtures" / "orc03_current_action_packet.json"
PACKET = json.loads(PACKET_PATH.read_text())

EXPECTED = {
    "expected_packet_sha256": "e7afbb28ebb4ff3a201f1a4df8a99e206e540e80c4217975b6d23dbecd8eaddc",
    "packet_artifact_sha256": "e7afbb28ebb4ff3a201f1a4df8a99e206e540e80c4217975b6d23dbecd8eaddc",
    "expected_project_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "project-dc5b1e554f240b0997bf065ed250",
        "kind": "work.project",
        "revision": "rev-2",
    },
    "expected_task_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "task-e0716950bd89bca14264f45a5cec",
        "kind": "work.task",
        "revision": "rev-1",
    },
    "expected_assignment_ref": {
        "authority": "ast02-controller-root-v4",
        "id": "assignment-415b555ad23dc56229a1909db585",
        "kind": "wrk.assignment",
        "revision": "rev-1",
    },
    "expected_generation": 2,
    "observed_custody": {
        "project_ref": {
            "authority": "ast02-controller-root-v4",
            "id": "project-dc5b1e554f240b0997bf065ed250",
            "kind": "work.project",
            "revision": "rev-2",
        },
        "task_ref": {
            "authority": "ast02-controller-root-v4",
            "id": "task-e0716950bd89bca14264f45a5cec",
            "kind": "work.task",
            "revision": "rev-1",
        },
        "assignment_ref": {
            "authority": "ast02-controller-root-v4",
            "id": "assignment-415b555ad23dc56229a1909db585",
            "kind": "wrk.assignment",
            "revision": "rev-1",
        },
        "generation": 2,
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
        "dispatch": False,
    },
    "prerequisite_refs": [
        {"kind": "artifact", "id": "a98fdf34e40702310be5b14a60695f4d209ace7d568547f0a934824405ddfa26"},
        {"kind": "artifact", "id": "6fa56432ccb845f898f047d67711c46632e56c8dba1131fda804b384b76250b7"},
    ],
    "brief_sha256": "81dbeea5c5d2ef63956786ae2621be3b578fcae71217edee663d943b066aaafd",
    "plan_sha256": "952e899f654798c41a0cdc2a250d4b242094d1ee717b16c3360716cde73b3b7d",
    "p1_handoff_sha256": "4e917ca0d07306b815c649a4521d011f9d91d069ed0057abc5d078b545b357",
}


def run(packet=PACKET, **overrides):
    args = deepcopy(EXPECTED)
    args.update(overrides)
    return execute_selected_packet(packet=packet, **args)


def test_valid_packet_admits_one_bounded_resume_and_preserves_requested_observed_route():
    result = run()
    assert result["outcome"] == "admitted_bounded_resume"
    assert result["dispatch"] is False
    assert result["launch"] is False
    assert result["owner_acceptance"] is False
    assert result["worker"]["requested_reasoning"] == "high"
    assert result["worker"]["observed_reasoning"] == "xhigh"
    assert result["target"]["task_ref"]["id"] == "task-e0716950bd89bca14264f45a5cec"
    assert result["p1_open_obligations"] == ["BK-C06", "BK-C07"]


def test_stale_digest_and_incompatible_mandate_are_held_at_boundary():
    with pytest.raises(ExecutionResumeError, match="stale"):
        run(expected_packet_sha256="0" * 64)
    stale = deepcopy(PACKET)
    stale["selected_mandate"]["state"] = "paused"
    stale["packet_sha256"] = __import__("otto.portfolio.execution_resume", fromlist=["packet_digest"]).packet_digest(stale)
    with pytest.raises(ExecutionResumeError, match="not active"):
        run(packet=stale)


def test_wrong_task_or_assignment_revision_cannot_resume_old_custody():
    with pytest.raises(ExecutionResumeError, match="task_ref"):
        run(observed_custody={**EXPECTED["observed_custody"], "task_ref": {**EXPECTED["expected_task_ref"], "revision": "rev-9"}})
    # The expected ORC-04 assignment is pinned in the target record, so a
    # changed revision is rejected before any result can be emitted.
    with pytest.raises(ExecutionResumeError, match="assignment_ref"):
        run(observed_custody={**EXPECTED["observed_custody"], "assignment_ref": {**EXPECTED["expected_assignment_ref"], "revision": "rev-9"}})


def test_same_idempotency_key_is_a_replayed_noop():
    first = run()
    second = run(prior_attempts=[first])
    assert second["outcome"] == "replayed_noop"
    assert second["replayed"] is True
    assert second["idempotency_key"] == first["idempotency_key"]
    assert second["operation_sha256"] == first["operation_sha256"]
