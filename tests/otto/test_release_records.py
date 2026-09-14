"""OTT-05 public repository/release record conformance."""

from __future__ import annotations

from copy import deepcopy

from otto.engineering import ProcessProfile, ReleaseLedger, RIGHTS, SourceSetEntry


OWNER = "repo-owner"
MANAGER = "manager-1"


def source_set():
    return [
        SourceSetEntry("otto", "otto", "5332885d", "66db6877", "f2ff-wheel", "product"),
        SourceSetEntry("herzchen", "herzchen", "b68d8f59", "ee1614fc", "2681-herzchen", "dependency"),
    ]


def register():
    ledger = ReleaseLedger()
    result = ledger.register_repository(
        repository_id="delivery-repo",
        remote_id="origin:delivery",
        target_id="refs/heads/ott-05",
        baseline_head="baseline-head",
        target_head="target-head-1",
        source_set=source_set(),
        owner=OWNER,
        process_profile=ProcessProfile.twelve_hour(MANAGER),
        logical_key="repo-register",
        actor=OWNER,
    )
    assert result["outcome"] == "recorded"
    return ledger


def expected(ledger):
    record = ledger.get_repository("delivery-repo")
    return {
        "expected_version": record["version"],
        "expected_head": record["target_head"],
        "expected_edit_token": record["edit_token"],
    }


def select(ledger, key="candidate-select"):
    return ledger.select_candidate(
        "delivery-repo",
        candidate_ref="candidate-1",
        decision_ref="decision-1",
        source_set=source_set(),
        owner=OWNER,
        logical_key=key,
        actor=OWNER,
        **expected(ledger),
    )


def test_real_typed_path_records_candidate_check_decision_and_persists(tmp_path):
    ledger = register()
    selected = select(ledger)
    assert selected["repository"]["candidate_ref"] == "candidate-1"
    assert selected["repository"]["source_set_digest"]

    checked = ledger.record_required_check(
        "delivery-repo", check_id="tests", candidate_ref="candidate-1", result="pass",
        evidence_ref="evidence-tests", owner=OWNER, actor="check-runner",
        authority="check-authority", logical_key="check-1", source_set_digest=selected["repository"]["source_set_digest"],
        **expected(ledger),
    )
    assert checked["repository"]["checks"]["tests"]["result"] == "pass"
    decided = ledger.record_manager_decision(
        "delivery-repo", decision_ref="decision-1", candidate_ref="candidate-1", disposition="approve",
        rationale="required check passed", owner=OWNER, actor=MANAGER, authority=MANAGER,
        logical_key="decision-1", source_set_digest=checked["repository"]["source_set_digest"],
        **expected(ledger),
    )
    assert decided["repository"]["manager_decision"]["disposition"] == "approve"

    merged = ledger.record_merge(
        "delivery-repo", owner=OWNER, target_head_after="target-head-2", runner_outcome="completed",
        actor=OWNER, logical_key="merge-1", **expected(ledger),
    )
    record = merged["repository"]
    assert record["merge"]["status"] == "completed"
    assert record["target_head"] == "target-head-2"
    assert record["publication"]["status"] == "not_performed"
    assert record["deployment"]["status"] == "not_performed"

    snapshot_path = tmp_path / "release-records.json"
    ledger.save(snapshot_path)
    reopened = ReleaseLedger.load(snapshot_path)
    assert reopened.get_repository("delivery-repo") == ledger.get_repository("delivery-repo")
    assert len(reopened.list_events()) == len(ledger.list_events())


def test_partial_promotion_is_visible_and_resumable_only_by_same_owner():
    ledger = register()
    select(ledger)
    ledger.record_required_check(
        "delivery-repo", check_id="tests", candidate_ref="candidate-1", result="pass", evidence_ref="evidence",
        owner=OWNER, actor="check-runner", authority="check-authority", logical_key="check-partial", **expected(ledger),
    )
    ledger.record_manager_decision(
        "delivery-repo", decision_ref="decision-1", candidate_ref="candidate-1", disposition="approve", rationale="ok",
        owner=OWNER, actor=MANAGER, authority=MANAGER, logical_key="decision-partial", **expected(ledger),
    )
    ledger.record_merge(
        "delivery-repo", owner=OWNER, target_head_after="target-head-2", runner_outcome="completed", actor=OWNER,
        logical_key="merge-partial", **expected(ledger),
    )
    partial = ledger.record_promotion(
        "delivery-repo", owner=OWNER, steps=["source", "integration"],
        step_outcomes={"source": "completed", "integration": "pending"}, actor=OWNER, logical_key="promotion-partial",
        **expected(ledger),
    )
    assert partial["repository"]["promotion"] == {
        "status": "partial", "owner": OWNER, "completed_steps": ["source"], "pending_steps": ["integration"],
        "unknown_steps": [], "source_set_digest": partial["repository"]["source_set_digest"],
    }
    before = deepcopy(partial["repository"])
    wrong_owner = ledger.record_promotion(
        "delivery-repo", owner="other-owner", steps=["integration"], step_outcomes={"integration": "completed"},
        actor="other-owner", logical_key="promotion-wrong-owner", **expected(ledger),
    )
    assert wrong_owner["error"]["code"] == "authority_mismatch"
    assert ledger.get_repository("delivery-repo") == before
    resumed = ledger.record_promotion(
        "delivery-repo", owner=OWNER, steps=["integration"], step_outcomes={"integration": "completed"}, actor=OWNER,
        logical_key="promotion-resume", **expected(ledger),
    )
    assert resumed["repository"]["promotion"]["status"] == "completed"
    assert resumed["repository"]["promotion"]["pending_steps"] == []
    assert resumed["repository"]["publication"]["status"] == "not_performed"
    assert resumed["repository"]["deployment"]["status"] == "not_performed"


def test_stale_changed_duplicate_and_unknown_cases_have_no_release_delta():
    ledger = register()
    selected = select(ledger)
    base = ledger.get_repository("delivery-repo")
    stale = ledger.record_required_check(
        "delivery-repo", check_id="stale", candidate_ref="candidate-1", result="pass", evidence_ref="evidence",
        owner=OWNER, actor="check-runner", authority="check-authority", logical_key="stale-check",
        expected_version=base["version"], expected_head="old-target-head", expected_edit_token=base["edit_token"],
    )
    assert stale["error"]["code"] == "stale_head"
    assert ledger.get_repository("delivery-repo") == base

    changed = ledger.record_required_check(
        "delivery-repo", check_id="changed", candidate_ref="candidate-1", result="pass", evidence_ref="evidence",
        owner=OWNER, actor="check-runner", authority="check-authority", logical_key="changed-check",
        source_set_digest="different-source-set", **expected(ledger),
    )
    assert changed["error"]["code"] == "changed_source_set"
    assert ledger.get_repository("delivery-repo") == base

    duplicate = ledger.select_candidate(
        "delivery-repo", candidate_ref="candidate-2", decision_ref="decision-2",
        source_set=[source_set()[0], source_set()[0]], owner=OWNER, actor=OWNER, logical_key="duplicate-source",
        **expected(ledger),
    )
    assert duplicate["error"]["code"] == "duplicate_source_set_key"
    assert ledger.get_repository("delivery-repo") == base

    replay = select(ledger)
    assert replay["outcome"] == "replayed"
    conflict = ledger.select_candidate(
        "delivery-repo", candidate_ref="candidate-other", decision_ref="decision-other", source_set=source_set(),
        owner=OWNER, actor=OWNER, logical_key="candidate-select", **expected(ledger),
    )
    assert conflict["error"]["code"] == "replay_conflict"
    assert ledger.get_repository("delivery-repo") == base

    checked = ledger.record_required_check(
        "delivery-repo", check_id="unknown-check", candidate_ref="candidate-1", result="pass", evidence_ref="evidence",
        owner=OWNER, actor="check-runner", authority="check-authority", logical_key="unknown-check", **expected(ledger),
    )
    ledger.record_manager_decision(
        "delivery-repo", decision_ref="decision-1", candidate_ref="candidate-1", disposition="approve", rationale="ok",
        owner=OWNER, actor=MANAGER, authority=MANAGER, logical_key="unknown-decision", **expected(ledger),
    )
    before_unknown = ledger.get_repository("delivery-repo")
    unknown = ledger.record_merge(
        "delivery-repo", owner=OWNER, target_head_after="target-head-unknown", runner_outcome="unknown", actor=OWNER,
        logical_key="merge-unknown", **expected(ledger),
    )
    assert unknown["repository"]["merge"]["status"] == "unknown"
    assert unknown["repository"]["target_head"] == before_unknown["target_head"]
    assert unknown["effects"]["target_head_changed"] is False
    assert unknown["repository"]["publication"]["status"] == "not_performed"
    assert unknown["repository"]["deployment"]["status"] == "not_performed"


def test_rights_and_profiles_are_separate_and_do_not_create_extra_allowance():
    ledger = register()
    record = ledger.get_repository("delivery-repo")
    assert RIGHTS == {
        "repository.register": "repository_owner", "candidate.select": "repository_owner", "check.record": "check_authority",
        "decision.record": "manager_authority", "merge.record": "merge_authority", "promotion.record": "promotion_authority",
        "publication.record": "publication_authority", "deployment.record": "deployment_authority",
    }
    assert record["process_profile"]["cadence"] == "12-hour"
    assert record["process_profile"]["scheduler"] == "none"
    assert record["process_profile"]["queue"] is False
    assert record["process_profile"]["periodic_allowance"] == "none"
    assert record["process_profile"]["automatic_deployment"] is False
    duplicate_profile = ledger.register_repository(
        repository_id="another-repo", remote_id="origin:another", target_id="refs/heads/another",
        baseline_head="base", target_head="head", source_set=source_set(), owner="other-owner",
        process_profile=ProcessProfile.hourly(MANAGER), logical_key="repo-register-2", actor="other-owner",
    )
    assert duplicate_profile["error"]["code"] == "duplicate_periodic_allowance"
