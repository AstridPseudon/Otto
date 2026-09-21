from copy import deepcopy

import pytest

from otto.portfolio.operating_brief import (
    OperatingBrief,
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
