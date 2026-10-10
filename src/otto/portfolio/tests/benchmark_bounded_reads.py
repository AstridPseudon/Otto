"""Offline D02 measurements; no provider or operational owner effects.

PYTHONPATH=src:tests python3 -m otto.portfolio.tests.benchmark_bounded_reads --output PATH
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time

from .test_bounded_evidence_reads import BoundedEvidenceTests
from otto.portfolio.execution_host import _atomic_json
from otto.portfolio.manager_journey_client import read_command_status, read_command_detail
from otto.portfolio.retained_projection import (
    capture_preparation_checkpoint, finite_summary, read_projection, read_checkpoint_detail,
)

FIXTURE = Path("/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-agent-adapter-conformance-20261009/controller/evidence/d05-coordinator-preparation-stages.json")
DIGEST = "596f8373d84ab87db0fe2130dfe8e0ee3e2590f29b7f503d6ee3671e9cf3d760"
LENGTH = 37657216
BINDING = {
    "principal": "otto-evidence-d02-worker-1", "generation": 1,
    "assignment_ref": {"authority": "otto-project-operating-setup-20261005-owner-v1", "kind": "wrk.assignment",
        "id": "assignment-a3d4afe9d48e9fbcfe5a538a17db", "revision": "rev-2"},
    "project_ref": {"authority": "otto-project-operating-setup-20261005-owner-v1", "kind": "work.project",
        "id": "project-1a0a32aa681b82db0da5c844cc07", "revision": "rev-12"},
    "task_ref": {"authority": "otto-project-operating-setup-20261005-owner-v1", "kind": "work.task",
        "id": "task-28816510091475c240e2ee75fba9", "revision": "rev-1"},
    "parent": {"principal": "otto-evidence-manager-1", "generation": 1,
        "assignment_ref": {"authority": "otto-project-operating-setup-20261005-owner-v1", "kind": "wrk.assignment",
            "id": "assignment-7f8cdfbe280731995ade2adc8dff", "revision": "rev-4"}},
    "native_session": "01a1233d-7d48-7c23-a3af-f2a6c778ab4c",
}


def legacy_read(path):
    started = time.perf_counter()
    raw = path.read_bytes()
    read_at = time.perf_counter()
    value = json.loads(raw)
    parsed_at = time.perf_counter()
    digest = hashlib.sha256(raw).hexdigest()
    hashed_at = time.perf_counter()
    return value, {"byte_length": len(raw), "sha256": digest,
        "payload_bytes_read": len(raw), "payload_bytes_parsed": len(raw), "payload_bytes_hashed": len(raw),
        "read_seconds": read_at-started, "parse_seconds": parsed_at-read_at,
        "hash_seconds": hashed_at-parsed_at, "processing_seconds": hashed_at-started}


def run():
    original, identity = legacy_read(FIXTURE)
    assert identity["byte_length"] == LENGTH and identity["sha256"] == DIGEST
    summary = finite_summary(original)
    report = {"schema": "otto.evidence.D02.offline-benchmark.v1", "binding": BINDING,
        "baseline_head": "076883718494c418cb9d62cdedbf37f65e6a7d9d",
        "source_fixture": {"path": str(FIXTURE), "byte_length": LENGTH, "sha256": DIGEST},
        "clock": "same-process perf_counter; warmed offline filesystem; median of 5 reads",
        "provider_called": False, "replay_called": False, "checkpoint": [], "managed_payloads": [],
        "limitations": ["Source-only disposable-fixture proof; installation/adoption is D06 responsibility.",
            "Times cover these warmed local operations, not provider latency, native time, total workflow time or money.",
            "Admission is linear and accounted separately; historical JSON without projections requires explicit detail capture.",
            "Metadata byte measures are logical application bytes; no claim about filesystem cache, SQLite pages or physical disk traffic.",
            "Same-length corruption is not detected by a status/range; explicit full verification detects it."]}
    with tempfile.TemporaryDirectory(prefix="evidence-d02-benchmark-") as directory:
        root = Path(directory)
        small = root / "small-source.json"
        small.write_bytes(json.dumps({**original, "before_state": summary.get("before_state", {}),
            "stages": summary.get("stages", {}), "workers_before": summary.get("workers_before", []),
            "offline_padding": "x" * 1_000_000}, sort_keys=True).encode())
        # Real fixture remains exact; the smaller variant preserves all finite
        # identity/phase/outcome observations and is labelled synthetic.
        for label, source in (("synthetic-1MB-variant", small), ("exact-offline-fixture", FIXTURE)):
            before = [legacy_read(source)[1] for _ in range(5)]
            checkpoint = root / (label + ".json")
            pin = before[0]
            captured = capture_preparation_checkpoint(checkpoint, source,
                expected_sha256=pin["sha256"], expected_length=pin["byte_length"], binding=BINDING)
            after = [read_projection(checkpoint, expected_binding=BINDING) for _ in range(5)]
            assert after[0]["artifact"]["sha256"] == pin["sha256"]
            assert after[0]["binding"] == BINDING
            assert after[0]["summary"] == finite_summary(legacy_read(source)[0])
            assert after[0]["summary"] == summary
            detail = read_checkpoint_detail(checkpoint, expected_binding=BINDING, offset=113, max_bytes=4096)
            with source.open("rb") as stream:
                stream.seek(113); expected = stream.read(4096)
            assert detail["bytes"] == expected
            report["checkpoint"].append({"label": label, "source_pin": {k: pin[k] for k in ("sha256", "byte_length")},
                "identity_phase_outcome_summary_sha256": hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest(),
                "before": {**pin, "processing_seconds_median": statistics.median(x["processing_seconds"] for x in before)},
                "after": {**after[0]["io_work"], "processing_seconds_median": statistics.median(x["io_work"]["processing_seconds"] for x in after)},
                "admission": captured["admission_work"], "details": {"payload_bytes_read": detail["io_work"]["payload_bytes_read"],
                    "offset": detail["offset"], "next_offset": detail["next_offset"], "verification": detail["verification"]}})
        fixture = BoundedEvidenceTests()
        fixture.setUp()
        try:
            for size in (1_000_000, LENGTH):
                data = (bytes(range(256)) * (size // 256 + 1))[:size]
                captured = fixture._submit(data, "benchmark-%d" % size, format="application/octet-stream")
                statuses = [fixture.handler.status(captured["revision_ref"], actor=fixture.actor) for _ in range(5)]
                detail = fixture.handler.read_evidence(captured["revision_ref"], actor=fixture.actor, offset=31, max_bytes=4096)
                assert detail["bytes"] == data[31:4127]
                verification = fixture.handler.resolve(captured["revision_ref"], actor=fixture.actor, max_bytes=0, verify_full=True)
                assert verification["actual_digest"] == hashlib.sha256(data).hexdigest()
                fixture.link("benchmark-%d" % size, captured["revision_ref"])
                page = fixture.handler.list_evidence(fixture.project, actor=fixture.actor, limit=1)
                report["managed_payloads"].append({"byte_length": size, "sha256": hashlib.sha256(data).hexdigest(),
                    "reference": captured["revision_ref"].to_dict(), "status": statuses[0]["io_work"],
                    "status_processing_seconds_median": statistics.median(x["io_work"]["processing_seconds"] for x in statuses),
                    "page": page["io_work"], "detail": detail["io_work"], "full_verification": verification["io_work"]})
        finally:
            fixture.tearDown()
        token = "f" * 32
        response = root / ("response-" + token + ".json")
        _atomic_json(response, {"outcome": "unknown", "generation": 1, "parent": BINDING["parent"],
            "assignment_ref": BINDING["assignment_ref"], "raw_result": original})
        status = read_command_status(root, token)
        detail = read_command_detail(root, token, max_bytes=4096)
        assert status["outcome"] == "unknown" and len(detail["bytes"]) == 4096
        report["transport"] = {"outcome": status["outcome"], "response_utf8_bytes": status["response_utf8_bytes"],
            "response_sha256": status["response_sha256"], "io_work": status["io_work"], "details": detail["io_work"]}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run()
    Path(args.output).write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": args.output, "checkpoint": [{"label": x["label"],
        "before_bytes": x["before"]["payload_bytes_read"], "after_bytes": x["after"]["metadata_bytes_read"],
        "before_seconds": x["before"]["processing_seconds_median"], "after_seconds": x["after"]["processing_seconds_median"]}
        for x in report["checkpoint"]]}, sort_keys=True))
