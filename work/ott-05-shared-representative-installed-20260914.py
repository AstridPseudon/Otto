"""Representative OTT-05 shared-store path; run from a disposable venv."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json

import herzchen
from herzchen.domains.work.decisions import CandidateRecord, DecisionRecord
import otto
from otto.engineering import ProcessProfile, ReleaseError, ReleaseOperations, SourceSetEntry


def main() -> None:
    source_set = (
        SourceSetEntry("otto", "otto", "5332885d", "66db6877", "f2fffb0d", "product"),
        SourceSetEntry("herzchen", "herzchen", "b68d8f59", "ee1614fc", "2681daa", "dependency"),
    )
    observations: dict[str, object] = {
        "origins": {"otto": str(Path(otto.__file__).resolve()), "herzchen": str(Path(herzchen.__file__).resolve())},
        "pythonpath": __import__("os").environ.get("PYTHONPATH"),
        "pythonhome": __import__("os").environ.get("PYTHONHOME"),
    }
    with TemporaryDirectory(prefix="ott05-shared-") as directory:
        database = Path(directory) / "shared.sqlite"
        operations = ReleaseOperations.bootstrap(database)
        registration = operations.register_repository(repository_id="delivery", remote_id="origin:delivery", target_id="refs/heads/ott-05", baseline_head="base", target_head="head-1", source_set=source_set, owner="otto-owner", process_profile=ProcessProfile.twelve_hour("manager-1"), logical_request_key="repository-register")
        candidate_observation = operations.select_candidate("delivery", source_set=source_set, owner="otto-owner", logical_request_key="candidate-select")
        assert isinstance(candidate_observation.candidate, CandidateRecord)
        check = operations.record_required_check("delivery", check_id="tests", result="pass", evidence_ref="tests-receipt", owner="otto-owner", authority="check_authority", logical_request_key="check-record", source_set_digest=candidate_observation.source_set_digest)
        decision = operations.record_manager_decision("delivery", disposition="approve", rationale="required check passed", owner="otto-owner", authority="manager_authority", logical_request_key="decision-record", source_set_digest=candidate_observation.source_set_digest)
        assert isinstance(operations.get_decision(operations.get_repository("delivery").payload["decision_ref"]), DecisionRecord)
        before_reopen = operations.get_repository("delivery")
        observations["shared_store"] = {"database": str(database), "registration_receipt": registration.to_dict(), "candidate_receipt": candidate_observation.receipt.to_dict(), "herzchen_candidate_receipt": candidate_observation.candidate.receipt.to_dict(), "check_receipt": check.to_dict(), "decision_receipt": decision.to_dict(), "candidate_ref": candidate_observation.candidate.ref.to_dict(), "candidate_source_set_digest": candidate_observation.source_set_digest, "repository_before_reopen": before_reopen.to_dict(), "repository_event_ids": [event.event_id for event in operations.list_events("delivery")], "counts_before_reopen": dict(operations.snapshot_counts())}
        operations.close()
        operations.reopen()
        after_reopen = operations.get_repository("delivery")
        reopened_candidate = operations.get_candidate(after_reopen.payload["candidate_ref"])
        reopened_decision = operations.get_decision(after_reopen.payload["decision_ref"])
        observations["reopen"] = {"same_typed_repository": after_reopen.to_dict() == before_reopen.to_dict(), "candidate_read": isinstance(reopened_candidate, CandidateRecord), "decision_read": isinstance(reopened_decision, DecisionRecord), "candidate_receipt_read": reopened_candidate.receipt.to_dict(), "decision_receipt_read": reopened_decision.receipt.to_dict(), "receipt_read": operations.get_receipt("decision-record").to_dict(), "version": after_reopen.version, "event_count": len(operations.list_events("delivery"))}
        observations["cases"] = {}
        try:
            operations.record_merge("delivery", target_head_after="bad-head", runner_outcome="completed", owner="otto-owner", logical_request_key="stale-head", expected_head="old-head")
        except ReleaseError as error:
            observations["cases"]["stale_head"] = error.to_dict()
        partial = operations.record_promotion("delivery", steps=("source", "integration"), step_outcomes={"source": "completed", "integration": "pending"}, owner="otto-owner", logical_request_key="partial-promotion", source_set_digest=candidate_observation.source_set_digest)
        unknown = operations.record_merge("delivery", target_head_after="unknown-head", runner_outcome="unknown", owner="otto-owner", logical_request_key="unknown-merge")
        final = operations.get_repository("delivery")
        observations["cases"].update({"partial_promotion": final.payload["promotion"], "unknown_merge_receipt": unknown.to_dict(), "publication": final.payload["publication"], "deployment": final.payload["deployment"]})
        operations.close()
    print(json.dumps(observations, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
