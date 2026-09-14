"""Representative installed OTT-05 public-path observation."""
from __future__ import annotations

import json
import os
import sys

import herzchen
import otto
from otto.engineering import ProcessProfile, ReleaseLedger, SourceSetEntry


def main() -> None:
    assert os.environ.get("PYTHONPATH") is None
    assert os.environ.get("PYTHONHOME") is None
    ledger = ReleaseLedger()
    entries = [
        SourceSetEntry("otto", "otto", "5332885d", "66db6877", "f2fffb0d", "product"),
        SourceSetEntry("herzchen", "herzchen", "b68d8f59", "ee1614fc", "2681daa", "dependency"),
    ]
    registered = ledger.register_repository(
        repository_id="installed-delivery", remote_id="origin:delivery", target_id="refs/heads/ott-05",
        baseline_head="baseline-head", target_head="target-head-1", source_set=entries, owner="owner-1",
        process_profile=ProcessProfile.twelve_hour("manager-1"), logical_key="installed-register", actor="owner-1",
    )
    selected = ledger.select_candidate(
        "installed-delivery", candidate_ref="candidate-1", decision_ref="decision-1", source_set=entries,
        owner="owner-1", logical_key="installed-select", actor="owner-1", **{
            "expected_version": registered["repository"]["version"],
            "expected_head": registered["repository"]["target_head"],
            "expected_edit_token": registered["repository"]["edit_token"],
        },
    )
    stale = ledger.record_required_check(
        "installed-delivery", check_id="stale-check", candidate_ref="candidate-1", result="pass", evidence_ref="evidence",
        owner="owner-1", actor="check-runner", authority="check-authority", logical_key="installed-stale-check",
        expected_version=selected["repository"]["version"], expected_head="stale-head", expected_edit_token=selected["repository"]["edit_token"],
    )
    checked = ledger.record_required_check(
        "installed-delivery", check_id="tests", candidate_ref="candidate-1", result="pass", evidence_ref="evidence-tests",
        owner="owner-1", actor="check-runner", authority="check-authority", logical_key="installed-check",
        **{
            "expected_version": selected["repository"]["version"],
            "expected_head": selected["repository"]["target_head"],
            "expected_edit_token": selected["repository"]["edit_token"],
        },
    )
    decided = ledger.record_manager_decision(
        "installed-delivery", decision_ref="decision-1", candidate_ref="candidate-1", disposition="approve", rationale="check recorded",
        owner="owner-1", actor="manager-1", authority="manager-1", logical_key="installed-decision",
        **{
            "expected_version": checked["repository"]["version"],
            "expected_head": checked["repository"]["target_head"],
            "expected_edit_token": checked["repository"]["edit_token"],
        },
    )
    unknown_merge = ledger.record_merge(
        "installed-delivery", owner="owner-1", target_head_after="target-head-2", runner_outcome="unknown", actor="owner-1",
        logical_key="installed-merge-unknown", **{
            "expected_version": decided["repository"]["version"],
            "expected_head": decided["repository"]["target_head"],
            "expected_edit_token": decided["repository"]["edit_token"],
        },
    )
    promotion = ledger.record_promotion(
        "installed-delivery", owner="owner-1", steps=["source"], step_outcomes={"source": "completed"}, actor="owner-1",
        logical_key="installed-promotion", **{
            "expected_version": unknown_merge["repository"]["version"],
            "expected_head": unknown_merge["repository"]["target_head"],
            "expected_edit_token": unknown_merge["repository"]["edit_token"],
        },
    )
    record = ledger.get_repository("installed-delivery")
    assert stale["error"]["code"] == "stale_head"
    assert unknown_merge["repository"]["merge"]["status"] == "unknown"
    assert promotion["error"]["code"] == "merge_required"
    assert record["publication"]["status"] == "not_performed"
    assert record["deployment"]["status"] == "not_performed"
    print(json.dumps({
        "python": sys.executable,
        "origins": {"otto": otto.__file__, "otto.engineering": __import__("otto.engineering", fromlist=["__file__"]).__file__, "herzchen": herzchen.__file__},
        "candidate": {"outcome": selected["outcome"], "source_set_digest": selected["repository"]["source_set_digest"]},
        "check": {"stale": stale["error"]["code"], "recorded": checked["repository"]["checks"]["tests"]["result"]},
        "decision": decided["repository"]["manager_decision"]["disposition"],
        "merge": {"status": unknown_merge["repository"]["merge"]["status"], "target_head_changed": unknown_merge["effects"]["target_head_changed"]},
        "promotion": {"status": promotion["error"]["code"]},
        "publication": record["publication"]["status"],
        "deployment": record["deployment"]["status"],
        "event_count": len(ledger.list_events()),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
