from __future__ import annotations

import pytest

from otto.portfolio.orchestrator_placement import (
    ExplicitPeerRequired,
    ForeignAuthorityError,
    OverlapAcknowledgementRequired,
    RecursiveOrchestrationError,
    StalePlacementError,
    build_orchestrator_view,
    guard_peer_request,
    place_new_project,
    preview_peer_request,
)


def assignment(ref, *, status="active", purpose="Main orchestration", scope="portfolio", authority="owner-a", **extra):
    return {
        "ref": {"authority": authority, "id": ref, "revision": "rev-1"},
        "role": "orchestrator",
        "principal": "task-" + ref,
        "generation": 1,
        "status": status,
        "purpose": purpose,
        "intended_scope": scope,
        **extra,
    }


def view(*, peer=False):
    assignments = [assignment("main")]
    if peer:
        assignments.append(assignment("peer", purpose="Research track", scope="research"))
    return build_orchestrator_view(
        authority="owner-a",
        revision="rev-4",
        assignments=assignments,
        default_assignment_ref={"authority": "owner-a", "id": "main"},
        supervision=[
            {
                "authority": "owner-a",
                "project_ref": {"authority": "owner-a", "id": "project-1", "revision": "rev-2"},
                "orchestrator_assignment_ref": {"authority": "owner-a", "id": "main"},
            }
        ],
    )


def test_normal_project_start_reuses_one_default_without_peer_warning():
    decision = place_new_project(view(), "project-2")

    assert decision.action == "reuse-default"
    assert decision.accountable_orchestrator_assignment_ref == "main"
    assert decision.warning is None


def test_explicit_peer_preview_exposes_purpose_scope_and_overlap():
    preview = preview_peer_request(
        view(peer=True),
        purpose="Research track",
        intended_scope="research",
        intended_project_refs=("project-1",),
    )

    assert preview.purpose == "Research track"
    assert preview.intended_scope == "research"
    assert preview.overlap_project_refs == ("project-1",)
    assert "Keep the current supervisor" in preview.overlap_warning
    assert preview.default_assignment_ref == "main"
    assert preview.recursive_hierarchy is False


def test_peer_request_requires_existing_orchestrator_and_overlap_acknowledgement():
    with pytest.raises(OverlapAcknowledgementRequired):
        guard_peer_request(
            view(peer=True),
            requested_by_assignment_ref="main",
            purpose="Research track",
            intended_scope="research",
            intended_project_refs=("project-1",),
            expected_revision="rev-4",
        )

    request = guard_peer_request(
        view(peer=True),
        requested_by_assignment_ref="main",
        purpose="Research track",
        intended_scope="research",
        intended_project_refs=("project-1",),
        expected_revision="rev-4",
        overlap_acknowledged=True,
    )
    assert request.action == "peer-request-accepted"
    assert request.default_assignment_ref == "main"
    assert request.accountable_supervisor_by_project == (("project-1", "main"),)


def test_peer_placement_cannot_bypass_explicit_peer_path():
    with pytest.raises(ExplicitPeerRequired):
        place_new_project(view(peer=True), "project-2", requested_assignment_ref="peer")

    assert place_new_project(view(peer=True), "project-2", requested_assignment_ref="peer", explicit_peer=True).action == "place-on-explicit-peer"


def test_stale_foreign_retired_and_recursive_inputs_fail_closed():
    with pytest.raises(StalePlacementError):
        guard_peer_request(
            view(peer=True),
            requested_by_assignment_ref="main",
            purpose="Research track",
            intended_scope="research",
            expected_revision="rev-3",
        )

    with pytest.raises(ForeignAuthorityError):
        build_orchestrator_view(
            authority="owner-a",
            revision="rev-4",
            assignments=[assignment("foreign", authority="owner-b")],
            default_assignment_ref=None,
        )

    with pytest.raises(ForeignAuthorityError):
        guard_peer_request(
            view(peer=True),
            requested_by_assignment_ref={"authority": "owner-b", "id": "main"},
            purpose="Research track",
            intended_scope="research",
            expected_revision="rev-4",
        )

    with pytest.raises(ForeignAuthorityError):
        place_new_project(view(peer=True), {"authority": "owner-b", "id": "project-2"})

    with pytest.raises(StalePlacementError):
        build_orchestrator_view(
            authority="owner-a",
            revision="rev-4",
            assignments=[assignment("main", status="retired")],
            default_assignment_ref="main",
        )

    with pytest.raises(RecursiveOrchestrationError):
        build_orchestrator_view(
            authority="owner-a",
            revision="rev-4",
            assignments=[assignment("main", parent_assignment_ref="another")],
            default_assignment_ref="main",
        )
