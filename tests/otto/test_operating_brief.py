from copy import deepcopy

import pytest

from otto.portfolio.operating_brief import (
    OperatingBrief,
    OperatingBriefAuthoringAdapter,
    OperatingBriefError,
    brief_diff,
    compose_owner_snapshot,
    json_envelope,
    render_operating_brief,
)


BASE = {
    "schema_revision": "otto.operating-brief.v1",
    "role": "manager",
    "mandate": "Coordinate the owned project toward reviewed delivery.",
    "user_constraints": ["Keep the main project intact", "Use supported owner operations"],
    "priorities": [{"id": "intake", "text": "Refresh canonical ownership", "status": "pending"}],
    "operational_constraints": ["One writer", "Record as-of freshness"],
    "continuation": {"next": "Inspect the current owner inbox"},
    "links": [{"label": "run", "href": ".otto/runs/example"}],
    "revision": "brief-1",
}


class _BatchesSpy:
    def __init__(self):
        self.calls = []

    def lifecycle_handler(self, project, *, authoring, handle, request_id):
        self.calls.append((project, authoring, handle, request_id))
        return {"handler": "owner", "request_id": request_id}


class _LifecycleSpy:
    def __init__(self):
        self.calls = []

    def finish(self, target, *, request_id, handler, **kwargs):
        self.calls.append((target, request_id, handler, kwargs))
        return {"status": "delegated"}


def test_schema_round_trip_and_pretty_json_are_deterministic():
    brief = OperatingBrief.from_mapping(BASE)
    assert brief.to_dict()["schema_revision"] == "otto.operating-brief.v1"
    assert json_envelope(brief.to_dict()) == json_envelope(brief.to_dict())
    assert "\n  \"mandate\"" in json_envelope(brief.to_dict())


def test_user_fields_are_protected_in_diff_while_agent_changes_remain_proposals():
    proposed = deepcopy(BASE)
    proposed["mandate"] = "Forged replacement mandate"
    proposed["priorities"].append({"id": "verify", "text": "Verify the next result", "status": "pending"})
    diff = brief_diff(BASE, proposed)
    assert diff["requires_user_authority"] is True
    assert "mandate" in diff["user_changes"]
    assert "priorities" in diff["agent_changes"]
    assert diff["proposal_only"] is True


def test_absent_brief_uses_role_fallback_and_keeps_entry_refresh_honest():
    rendered = render_operating_brief(
        role="orchestrator",
        role_instructions="Own only the managers attached to this orchestrator.",
        project_state={"id": "project-1", "lifecycle": "pending"},
        snapshot={"as_of": "2026-09-21T18:00:00Z", "active_projects": []},
        edit_recipe={"operation": "work.pending.edit"},
        as_of="2026-09-21T18:00:00Z",
    )
    assert rendered["brief_status"] == "absent_fallback"
    assert rendered["brief"]["role"] == "orchestrator"
    assert rendered["freshness"]["atomic_pre_delivery"] is False
    assert rendered["freshness"]["entry_refresh_required"] is True


def test_snapshot_uses_explicit_manager_refs_and_keeps_closed_history():
    manager = {"authority": "a", "kind": "wrk.assignment", "id": "assignment-1", "revision": "rev-1"}
    snapshot = compose_owner_snapshot(
        projects=[
            {"id": "active", "lifecycle": "pending", "manager_ref": manager},
            {"id": "closed", "lifecycle": "closed", "manager_ref": manager},
            {"id": "unowned", "lifecycle": "pending", "manager_ref": {"id": "other"}},
        ],
        active_manager_refs=[manager],
        recent_completions=[{"id": "completion-1"}],
        returned_results=[{"id": "return-1"}],
        blockers=[{"id": "blocker-1"}],
        as_of="2026-09-21T18:00:00Z",
        coverage_cursor="cursor-1",
    )
    assert [item["id"] for item in snapshot["active_projects"]] == ["active"]
    assert [item["id"] for item in snapshot["closures"]] == ["closed"]
    assert snapshot["coverage_cursor"] == "cursor-1"


def test_invalid_role_and_unknown_fields_are_rejected():
    with pytest.raises(OperatingBriefError, match="role"):
        OperatingBrief.from_mapping({"role": "worker"})
    bad = deepcopy(BASE)
    bad["authority"] = "forged"
    with pytest.raises(OperatingBriefError, match="unknown"):
        OperatingBrief.from_mapping(bad)


def test_requested_role_cannot_rebind_a_declared_brief():
    with pytest.raises(OperatingBriefError, match="does not match"):
        OperatingBrief.from_mapping(BASE, role="orchestrator")
    with pytest.raises(OperatingBriefError, match="does not match"):
        render_operating_brief(
            role="orchestrator",
            role_instructions="",
            project_state={},
            brief=OperatingBrief.from_mapping(BASE),
            as_of="2026-09-21T18:00:00Z",
        )


def test_snapshot_matches_explicit_refs_by_identity_and_copies_inputs():
    manager = {"authority": "a", "kind": "wrk.assignment", "id": "assignment-1", "revision": "rev-1"}
    observed = {**manager, "observed_generation": 3}
    projects = [{"id": "active", "lifecycle": "pending", "assignment_ref": observed}]
    refs = [manager]
    snapshot = compose_owner_snapshot(
        projects=projects,
        active_manager_refs=refs,
        as_of="2026-09-21T18:00:00Z",
    )
    assert [item["id"] for item in snapshot["active_projects"]] == ["active"]
    assert snapshot["active_manager_refs"] == refs
    observed["revision"] = "mutated"
    assert snapshot["active_projects"][0]["assignment_ref"]["revision"] == "rev-1"


def test_snapshot_rejects_non_object_records_and_invalid_lifecycle():
    with pytest.raises(OperatingBriefError, match="recent_completions"):
        compose_owner_snapshot(
            projects=[],
            active_manager_refs=[],
            recent_completions=["not-a-record"],
            as_of="2026-09-21T18:00:00Z",
        )
    with pytest.raises(OperatingBriefError, match="lifecycle"):
        compose_owner_snapshot(
            projects=[{"id": "p", "lifecycle": 3, "manager_ref": {"id": "m"}}],
            active_manager_refs=[{"id": "m"}],
            as_of="2026-09-21T18:00:00Z",
        )


def test_agent_adapter_renders_agent_fields_with_empty_protected_sections():
    adapter = OperatingBriefAuthoringAdapter("manager", _BatchesSpy(), _LifecycleSpy())
    rendered = adapter.agent_draft(
        role_instructions="Continue the owned work.",
        project_state={"id": "project-1"},
        brief={
            "role": "manager",
            "priorities": [{"id": "next", "text": "Review the result", "status": "pending"}],
            "operational_constraints": ["One writer"],
        },
        as_of="2026-09-23T06:30:00Z",
    )
    assert rendered["brief"]["mandate"] == ""
    assert rendered["brief"]["user_constraints"] == []
    assert rendered["brief"]["priorities"][0]["id"] == "next"

    absent = adapter.agent_draft(
        role_instructions="Continue the owned work.",
        project_state={"id": "project-1"},
        as_of="2026-09-23T06:30:00Z",
    )
    assert absent["brief_status"] == "absent_fallback"
    assert absent["brief"]["mandate"] == ""


def test_agent_adapter_rejects_protected_edits_before_owner_delegation():
    batches = _BatchesSpy()
    adapter = OperatingBriefAuthoringAdapter("manager", batches, _LifecycleSpy())
    with pytest.raises(OperatingBriefError, match="protected"):
        adapter.agent_draft(
            role_instructions="",
            project_state={},
            brief={"role": "manager", "mandate": "Forged authority"},
            as_of="2026-09-23T06:30:00Z",
        )
    assert batches.calls == []


def test_agent_adapter_binds_and_finishes_through_the_injected_owner_ports():
    batches = _BatchesSpy()
    lifecycle = _LifecycleSpy()
    adapter = OperatingBriefAuthoringAdapter("manager", batches, lifecycle)
    result = adapter.finish(
        "target",
        project="project",
        authoring="authoring",
        handle="handle",
        request_id="rb02-request-1",
        mode="manual",
        checkout_root="/tmp/checkout",
        registered_files=["document.json"],
    )
    assert result == {"status": "delegated"}
    assert batches.calls == [("project", "authoring", "handle", "rb02-request-1")]
    assert lifecycle.calls == [
        (
            "target",
            "rb02-request-1",
            {"handler": "owner", "request_id": "rb02-request-1"},
            {
                "mode": "manual",
                "checkout_root": "/tmp/checkout",
                "registered_files": ["document.json"],
            },
        )
    ]
