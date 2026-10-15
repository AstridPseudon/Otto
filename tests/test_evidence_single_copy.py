"""A recorded turn holds its task_bound_evidence exactly once."""

import json
import unittest

from otto.agents.evidence_refs import (
    EvidenceReferenceError, compact_raw_result, evidence_digest, expand_evidence_references)
from otto.agents.gateway import OttoGateway

MARK = "SINGLE-COPY-MARK"


def _evidence(size=2000):
    return {"session_id": "s1", "turn_id": "t1", "owner_delivery_authorization": {"principal": "p"},
            "delivered_brief_digest": "a" * 64, "read_targets": [], "text": MARK * size}


def _context(evidence):
    return {"session_id": "s1", "turn_id": "t1", "provenance": "host_owned_turn_context",
            "model": "m", "reasoning": "high", "worker_content": ["done"],
            "task_bound_evidence": evidence, "context_digest": "c" * 64}


def _adapter_result(evidence):
    """Shape of a resumed herzchen turn: the adapter result carries its own raw_result copy."""
    envelope = {"exit_status": 0, "stdout": "{}", "host_evidence": {
        "session_id": "s1", "turn_id": "t1", "otto_host_turn_context": _context(evidence)}}
    return {"outcome": "succeeded", "physical_session_id": "s1", "observed_turn_id": "t1",
            "context_digest_verified": True, "task_bound_evidence": evidence, "worker_content": ["done"],
            "raw_result": {"work_receipt": {"outcome": "succeeded"}, "work_envelope": envelope,
                           "task_bound_evidence": evidence, "worker_content": ["done"]}}


class _Stub:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return dict(self.value)


class _Capture:
    def __init__(self):
        self.recorded = []

    def record(self, envelope):
        self.recorded.append(json.loads(json.dumps(envelope)))


def _record_through_gateway(result):
    gateway = OttoGateway.__new__(OttoGateway)
    capture = _Capture()
    gateway.attempt_capture = capture
    gateway._attempt_from_result = lambda *args, **kwargs: _Stub({"outcome": "succeeded", "logical_request_key": "k"})
    gateway._attach_attempt(None, None, result)
    return capture.recorded[0]


class SingleEvidenceCopyTests(unittest.TestCase):
    def test_recorded_turn_holds_task_bound_evidence_exactly_once(self):
        evidence = _evidence()
        recorded = _record_through_gateway(_adapter_result(evidence))
        serialized = json.dumps(recorded, ensure_ascii=False)
        self.assertEqual(serialized.count(evidence["text"]), 1,
                         "task_bound_evidence must be stored once in the recorded turn")
        self.assertEqual(recorded["task_bound_evidence"], evidence)
        self.assertEqual(recorded["raw_result"]["task_bound_evidence"],
                         {"same_as": "result.task_bound_evidence", "sha256": evidence_digest(evidence)})

    def test_reader_expands_reference_back_to_the_exact_context(self):
        evidence = _evidence(10)
        recorded = _record_through_gateway(_adapter_result(evidence))
        expanded = expand_evidence_references(recorded["raw_result"], recorded["task_bound_evidence"])
        context = expanded["work_envelope"]["host_evidence"]["otto_host_turn_context"]
        self.assertEqual(context, _context(evidence))
        self.assertEqual(context["context_digest"], "c" * 64)

    def test_reference_with_mismatched_evidence_fails_closed(self):
        evidence = _evidence(10)
        recorded = _record_through_gateway(_adapter_result(evidence))
        tampered = dict(recorded["task_bound_evidence"], turn_id="other")
        with self.assertRaises(EvidenceReferenceError):
            expand_evidence_references(recorded["raw_result"], tampered)

    def test_records_without_references_read_unchanged(self):
        evidence = _evidence(10)
        raw = {"work_envelope": {"host_evidence": {"otto_host_turn_context": _context(evidence)}}}
        self.assertEqual(expand_evidence_references(raw, evidence), raw)

    def test_compaction_does_not_touch_unrelated_evidence_and_is_idempotent(self):
        evidence = _evidence(10)
        other = dict(evidence, turn_id="initializer")
        raw = {"initialization_envelope": {"host_evidence": {"otto_host_turn_context": _context(other)}},
               "task_bound_evidence": evidence}
        once = compact_raw_result(raw, evidence)
        self.assertEqual(once["initialization_envelope"], raw["initialization_envelope"])
        self.assertEqual(compact_raw_result(once, evidence), once)
        self.assertEqual(expand_evidence_references(once, evidence), raw)


if __name__ == "__main__":
    unittest.main()
