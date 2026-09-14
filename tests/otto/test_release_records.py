"""OTT-05 focused tests for the real Herzchen shared-store composition."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from otto.engineering import ProcessProfile, ReleaseError, ReleaseOperations, SourceSetEntry


OWNER = "otto-owner"
SOURCE_SET = (
    SourceSetEntry("otto", "otto", "5332885d", "66db6877", "f2fffb0d", "product"),
    SourceSetEntry("herzchen", "herzchen", "b68d8f59", "ee1614fc", "2681daa", "dependency"),
)


def _open(tmp: Path) -> ReleaseOperations:
    operations = ReleaseOperations.bootstrap(tmp / "shared.sqlite")
    operations.register_repository(repository_id="delivery", remote_id="origin:delivery", target_id="refs/heads/ott-05", baseline_head="base", target_head="head-1", source_set=SOURCE_SET, owner=OWNER, process_profile=ProcessProfile.twelve_hour("manager-1"), logical_request_key="repository-register")
    return operations


def _prepared(tmp: Path) -> tuple[ReleaseOperations, str]:
    operations = _open(tmp)
    candidate = operations.select_candidate("delivery", source_set=SOURCE_SET, owner=OWNER, logical_request_key="candidate-select")
    operations.record_required_check("delivery", check_id="tests", result="pass", evidence_ref="tests-receipt", owner=OWNER, authority="check_authority", logical_request_key="check-record", source_set_digest=candidate.source_set_digest)
    operations.record_manager_decision("delivery", disposition="approve", rationale="required check passed", owner=OWNER, authority="manager_authority", logical_request_key="decision-record", source_set_digest=candidate.source_set_digest)
    return operations, candidate.source_set_digest


def test_shared_store_candidate_check_decision_close_reopen() -> None:
    with TemporaryDirectory() as directory:
        operations, digest = _prepared(Path(directory))
        before = operations.get_repository("delivery")
        assert before.payload["candidate_ref"]["kind"] == "wrk.candidate"
        assert before.payload["decision_ref"]["kind"] == "wrk.decision"
        assert before.payload["checks"]["tests"]["result"] == "pass"
        assert digest == before.payload["source_set_digest"]
        assert "herzchen.work.decisions" in operations.registered_domains
        operations.close()
        operations.reopen()
        after = operations.get_repository("delivery")
        assert after.to_dict() == before.to_dict()
        assert len(operations.list_events("delivery")) == 4
        operations.close()


def test_stale_changed_duplicate_unknown_and_partial_have_zero_unintended_delta() -> None:
    with TemporaryDirectory() as directory:
        operations, digest = _prepared(Path(directory))
        before = operations.get_repository("delivery")
        try:
            operations.record_merge("delivery", target_head_after="bad", runner_outcome="completed", owner=OWNER, logical_request_key="stale", expected_head="old-head")
        except ReleaseError as error:
            assert error.code == "stale_head"
        assert operations.get_repository("delivery").version == before.version
        try:
            operations.select_candidate("delivery", source_set=(SOURCE_SET[0],), owner=OWNER, logical_request_key="changed-candidate")
        except ReleaseError as error:
            assert error.code == "changed_source_set"
        assert operations.get_repository("delivery").version == before.version
        try:
            operations.select_candidate("delivery", source_set=(SOURCE_SET[0], SOURCE_SET[0]), owner=OWNER, logical_request_key="duplicate-source")
        except ReleaseError as error:
            assert error.code == "duplicate_source_set_key"
        assert operations.get_repository("delivery").version == before.version
        try:
            operations.record_required_check("delivery", check_id="tests", result="fail", evidence_ref="changed", owner=OWNER, authority="check_authority", logical_request_key="check-record", source_set_digest=digest)
        except ReleaseError as error:
            assert error.code == "replay_conflict"
        assert operations.get_repository("delivery").payload["checks"]["tests"]["result"] == "pass"
        partial = operations.record_promotion("delivery", steps=("source", "integration"), step_outcomes={"source": "completed", "integration": "pending"}, owner=OWNER, logical_request_key="promotion-partial", source_set_digest=digest)
        assert partial.status.value == "committed"
        assert operations.get_repository("delivery").payload["promotion"]["status"] == "partial"
        try:
            operations.record_promotion("delivery", steps=("integration",), step_outcomes={"integration": "completed"}, owner="other-owner", logical_request_key="promotion-wrong-owner", source_set_digest=digest)
        except ReleaseError as error:
            assert error.code == "authority_mismatch"
        resumed = operations.record_promotion("delivery", steps=("integration",), step_outcomes={"integration": "completed"}, owner=OWNER, logical_request_key="promotion-resume", source_set_digest=digest)
        assert resumed.status.value == "committed"
        operations.record_merge("delivery", target_head_after="head-unknown", runner_outcome="unknown", owner=OWNER, logical_request_key="merge-unknown")
        final = operations.get_repository("delivery")
        assert final.payload["merge"]["status"] == "unknown"
        assert final.payload["target_head"] == before.payload["target_head"]
        assert final.payload["publication"]["status"] == "not_performed"
        assert final.payload["deployment"]["status"] == "not_performed"
        operations.close()


def test_separate_rights_profile_and_no_duplicate_repository() -> None:
    with TemporaryDirectory() as directory:
        operations = _open(Path(directory))
        record = operations.get_repository("delivery")
        assert record.payload["rights"]["merge.record"] == "merge_authority"
        assert record.payload["rights"]["publication.record"] == "publication_authority"
        assert record.payload["process_profile"]["cadence"] == "12-hour"
        assert record.payload["process_profile"]["scheduler"] == "none"
        assert record.payload["process_profile"]["periodic_allowance"] == "none"
        assert record.payload["process_profile"]["automatic_deployment"] is False
        try:
            operations.register_repository(repository_id="delivery", remote_id="other", target_id="other", baseline_head="b", target_head="h", source_set=SOURCE_SET, owner=OWNER, process_profile=ProcessProfile.hourly("manager-1"), logical_request_key="repository-register-duplicate")
        except ReleaseError as error:
            assert error.code == "duplicate_repository"
        operations.close()
