"""Completion gate command tests use only an inert owner read port."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from herzchen.contracts import AuthenticatedActor
from otto.portfolio.completion_gate import completion_gate_from_command


def ref(kind, identity, revision="rev-1", authority="gate-owner"):
    return {"authority": authority, "kind": kind, "id": identity, "revision": revision}


class CompletionGateTests(unittest.TestCase):
    def setUp(self):
        self.task = ref("work.task", "pa01", "rev-2")
        self.actor = AuthenticatedActor("principal-namespace", "manager", "test-credential")
        self.read = Mock(return_value={"required": True, "blockers": [{"code": "completion_candidate_required"}]})
        self.complete = Mock()
        self.port = SimpleNamespace(completion_blockers=self.read, complete=self.complete)

    def call(self, request):
        return completion_gate_from_command(self.port, request=request, task_ref=self.task, actor=self.actor)

    def test_initial_read_preserves_blockers_and_records_no_acceptance(self):
        result = self.call({"actor": "untrusted", "task_ref": ref("work.task", "foreign")})
        self.assertEqual(result["eligibility"], "blocked")
        self.assertEqual(result["task_ref"], self.task)
        self.assertTrue(result["read_only"])
        self.assertTrue(result["provisional"])
        self.assertFalse(result["acceptance_recorded"])
        args, kwargs = self.read.call_args
        self.assertEqual(args[0].to_dict(), self.task)
        self.assertEqual(kwargs, {"candidate": None, "gate_refs": (), "actor": self.actor,
                                  "completion_evidence_refs": (), "completion_evidence_hashes": []})
        self.complete.assert_not_called()

    def test_cli_forwards_candidate_decisions_and_aligned_evidence(self):
        spec = importlib.util.spec_from_file_location("gate_client", Path(__file__).resolve().parents[1] / "manager_ctl.py")
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        candidate = ref("wrk.candidate", "candidate")
        gates = [ref("assessment.decision", "c01"), ref("assessment.decision", "c02")]
        evidence = ref("dat.content.document", "review")
        argv = ["manager_ctl.py", "completion-gate", "--task", "PA01", "--candidate-ref", json.dumps(candidate),
                "--evidence-ref", json.dumps(evidence), "--evidence-hash", "a" * 64]
        for gate in gates:
            argv += ["--gate-ref", json.dumps(gate)]
        with patch.object(client, "call", side_effect=self.call), patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            client.main()
        kwargs = self.read.call_args.kwargs
        self.assertEqual(kwargs["candidate"].to_dict(), candidate)
        self.assertEqual([value.to_dict() for value in kwargs["gate_refs"]], gates)
        self.assertEqual([value.to_dict() for value in kwargs["completion_evidence_refs"]], [evidence])
        self.assertEqual(kwargs["completion_evidence_hashes"], ["a" * 64])
        self.complete.assert_not_called()

    def test_unverified_required_evidence_is_unknown_without_blockers(self):
        for state in ("unknown", "stale", "mismatch", None):
            self.read.return_value = {"required": True, "blockers": [], "evidence_verification": state}
            self.assertEqual(self.call({})["eligibility"], "unknown")

    def test_verified_or_not_required_is_clear_but_provisional(self):
        for state in ({"required": True, "blockers": [], "evidence_verification": "verified"},
                      {"required": False, "blockers": []}):
            self.read.return_value = state
            value = self.call({})
            self.assertEqual(value["eligibility"], "clear")
            self.assertFalse(value["acceptance_recorded"])
            self.assertEqual(value["owner_gate_state"], state)

    def test_malformed_or_unavailable_owner_read_is_unknown(self):
        for state in (None, {}, {"blockers": []}, {"required": False, "blockers": None}):
            self.read.return_value = state
            self.assertEqual(self.call({})["eligibility"], "unknown")
        self.read.side_effect = ValueError("stale candidate")
        self.assertEqual(self.call({})["error"]["code"], "completion_gate_read_failed")
        self.complete.assert_not_called()

    def test_invalid_refs_and_hashes_reject_before_owner_read(self):
        evidence = json.dumps(ref("dat.content.document", "review"))
        requests = [
            {"gate_refs": "not-list"}, {"candidate_ref": "{}"}, {"gate_refs": ["not-json"]},
            {"gate_refs": [json.dumps(ref("assessment.decision", "gate", authority="foreign"))]},
            {"candidate_ref": json.dumps(ref("wrk.candidate", "candidate", revision=None))},
            {"evidence_hashes": ["a" * 64]}, {"evidence_refs": [evidence], "evidence_hashes": ["bad"]},
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.call(request)
        self.read.assert_not_called()
        self.complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
