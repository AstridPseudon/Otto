"""OTT-05 focused tests for the real Herzchen shared-store composition."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

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


def test_serialized_consumer_has_no_owner_object_graph() -> None:
    """The consumer retains only Herzchen's finite command/read transports."""
    from herzchen.command_ports import SerializedCommandClient, SerializedReaderClient

    forbidden_names = {"store", "domainhandler", "domain_handler", "transaction", "connection", "writer", "release_handler", "database", "sqlite"}
    forbidden_types = {"Store", "DomainHandler", "Transaction", "ConsumerStore", "DomainCommandPort"}

    def walk(value: Any, depth: int = 0, seen: set[int] | None = None) -> list[str]:
        if seen is None:
            seen = set()
        if value is None or isinstance(value, (str, bytes, int, float, bool, type)) or depth > 4 or id(value) in seen:
            return []
        seen.add(id(value))
        kind = type(value)
        found: list[str] = []
        if kind.__name__ in forbidden_types:
            found.append("type:" + kind.__name__)
        for name in getattr(kind, "__slots__", ()):
            if not isinstance(name, str):
                continue
            lowered = name.lstrip("_").lower()
            if lowered in forbidden_names or any(token in lowered for token in forbidden_names if token in {"release_handler", "database", "sqlite"}):
                found.append("name:" + name)
            try:
                found.extend(walk(getattr(value, name), depth + 1, seen))
            except AttributeError:
                pass
        if hasattr(value, "__dict__"):
            for name, item in vars(value).items():
                lowered = name.lstrip("_").lower()
                if lowered in forbidden_names or any(token in lowered for token in forbidden_names if token in {"release_handler", "database", "sqlite"}):
                    found.append("name:" + name)
                found.extend(walk(item, depth + 1, seen))
        return found

    with TemporaryDirectory() as directory:
        operations = ReleaseOperations.bootstrap(Path(directory) / "shared.sqlite")
        instance_names = set(vars(operations))
        assert instance_names == {"_client", "_reader", "_authority"}
        assert isinstance(operations._client, SerializedCommandClient)
        assert isinstance(operations._reader, SerializedReaderClient)
        expected_endpoints = {"close_store", "reopen_store", "register_repository", "get_repository", "select_candidate", "record_required_check", "record_manager_decision", "record_merge", "record_promotion", "record_publication", "record_deployment", "get_candidate", "get_decision", "get_receipt", "list_events", "snapshot_counts", "registered_domains"}
        assert set(operations._client.endpoints) == expected_endpoints
        assert not walk(operations)
        socket_path = operations._client.transport.socket_path
        assert socket_path.endswith("owner.sock")
        assert not any(socket_path.endswith(suffix) for suffix in (".sqlite", ".sqlite3", ".db"))
        operations.close()
