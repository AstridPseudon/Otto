from copy import deepcopy

import pytest

from otto.portfolio.steady_state import SteadyStateError, build_manager_action_packet, fence_replacement


BINDING = {
    "binding_id": "qualified-p1-binding",
    "generation": 4,
    "status": "qualified",
    "origin": "p1-installed-target",
    "source_tree": "qualified-tree",
}
ATTEMPT = {
    "binding_id": "replacement-candidate",
    "generation": 5,
    "status": "failed",
    "origin": "isolated-replacement",
}
HISTORY = [
    {"event": "qualified", "binding_id": "qualified-p1-binding", "generation": 4},
    {"event": "replacement_started", "binding_id": "replacement-candidate", "generation": 5},
]


def test_failed_replacement_is_fenced_and_prior_history_binding_is_preserved():
    result = fence_replacement(
        current_binding=BINDING,
        replacement_attempt=ATTEMPT,
        history=HISTORY,
        requested_generation=4,
        action_key="orc06-replacement-rollback",
    )
    assert result["outcome"] == "rollback_preserved"
    assert result["rollback_performed"] is True
    assert result["selected_binding"] == BINDING
    assert result["history_preserved"] == HISTORY
    assert result["canonical_mutation"] is False


def test_stale_generation_and_late_writer_are_held():
    stale = fence_replacement(
        current_binding=BINDING,
        replacement_attempt=ATTEMPT,
        history=HISTORY,
        requested_generation=3,
        action_key="orc06-replacement-rollback",
    )
    assert stale["outcome"] == "held_stale_generation"
    late_attempt = {**ATTEMPT, "generation": 4}
    late = fence_replacement(
        current_binding=BINDING,
        replacement_attempt=late_attempt,
        history=HISTORY,
        requested_generation=4,
        action_key="orc06-replacement-rollback",
    )
    assert late["outcome"] == "held_late_writer"


def test_same_failed_replacement_decision_replays_without_second_mutation():
    first = fence_replacement(
        current_binding=BINDING,
        replacement_attempt=ATTEMPT,
        history=HISTORY,
        requested_generation=4,
        action_key="orc06-replacement-rollback",
    )
    replay = fence_replacement(
        current_binding=BINDING,
        replacement_attempt=ATTEMPT,
        history=HISTORY,
        requested_generation=4,
        action_key="orc06-replacement-rollback",
        prior_results=[first],
    )
    assert replay["outcome"] == "replayed_noop"
    assert replay["operation_sha256"] == first["operation_sha256"]
    assert replay["canonical_mutation"] is False


def test_manager_packet_pins_owner_api_generation_rollback_retirement_and_status_separation():
    packet = build_manager_action_packet(
        owner_api="supported.owner.assignment_action.v1",
        project_ref={"authority": "ast02-controller-root-v4", "id": "project-dc5b1e554f240b0997bf065ed250", "kind": "work.project", "revision": "rev-2"},
        task_ref={"authority": "ast02-controller-root-v4", "id": "task-6be835ba60ec6a07c86f4021a628", "kind": "work.task", "revision": "rev-1"},
        assignment_ref={"authority": "ast02-controller-root-v4", "id": "assignment-ffdb48a62a6b8f92785a3c1b261d", "kind": "wrk.assignment", "revision": "rev-1"},
        generation=1,
        manager_ref={"authority": "ast02-controller-root-v4", "id": "01a0b1f6-e8a5-72a0-919e-e5602e3dbc42", "kind": "manager.conversation", "revision": "current"},
        action_key="orc06-qualified-binding-owner-use",
        qualified_binding={"binding_id": "qualified-p1-binding", "status": "qualified_installed", "origin": "p1-installed-target", "tree": "qualified-tree"},
        expected_evidence=[{"kind": "owner_receipt", "required": True}, {"kind": "fresh_public_read", "required": True}],
        rollback_disposition={"on_failure": "hold_late_writer_and_restore_prior_binding", "preserve_history": True},
        retirement_disposition={"on_success": "retire_only_project_provisional_enrollment", "preserve_shared_heartbeat": True},
        source_lineage={"orc04_commit": "8041ca9e6bffaff0eb8229de28c3f953184c6ee8", "orc05_commit": "695d085b8d34acbed7e3d836e3218ad75c889493"},
    )
    assert packet["execute_now"] is False
    assert packet["owner_acceptance"] is False
    assert packet["generation_fence"]["late_writer"] == "hold"
    assert packet["status_separation"] == {
        "built": True,
        "tested": True,
        "installed": True,
        "selected": True,
        "active": False,
        "used": False,
        "heartbeat": False,
        "schedule": False,
        "project_acceptance": False,
    }


def test_unqualified_binding_cannot_create_owner_packet():
    with pytest.raises(SteadyStateError, match="qualified installed"):
        build_manager_action_packet(
            owner_api="supported.owner.assignment_action.v1",
            project_ref={"id": "project"}, task_ref={"id": "task"}, assignment_ref={"id": "assignment"},
            generation=1, manager_ref={"id": "manager"}, action_key="action",
            qualified_binding={"binding_id": "candidate", "status": "built", "origin": "source"},
            expected_evidence=[{"kind": "receipt"}], rollback_disposition={"on_failure": "hold"},
            retirement_disposition={"on_success": "retire"}, source_lineage={"commit": "candidate"},
        )
