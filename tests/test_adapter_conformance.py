"""D01 common adapter contract and deliberately insufficient fixtures."""
from __future__ import annotations

import unittest

from otto.agents.adapter_conformance import (
    AdapterConformanceFailure,
    bounded_result_view,
    capability_inventory,
    cli_contract,
    delivery_identity,
    d01_baseline_artifact,
    exact_lookup,
    normalize_pins,
    parent_binding,
    run_conformance,
    scope_identity,
    subtract_compatible_overlap,
    validate_caller_claims,
    validate_d01_baseline_artifact,
    validate_native_proof,
    validate_parent_binding,
    digest,
)


AUTH = "owner"


def ref(kind: str, ident: str, revision: str = "rev-1"):
    return {"authority": AUTH, "kind": kind, "id": ident, "revision": revision}


def pins(seed: str):
    return {
        name: {"ref": ref("dat.content.document", f"{name}-{seed}"), "sha256": digest([name, seed])}
        for name in ("recovery", "source", "runtime", "client", "resource")
    }


class ConformingFixture:
    def __init__(self):
        self.records = []
        self.effect_count = 0

    def launch(self, request):
        if request.get("caller_principal") == "forged-caller":
            return {"outcome": "denied", "reason": "caller binding mismatch"}
        scope = request["scope"]
        key = request["request_key"]
        existing = next((item for item in self.records if item["request_key"] == key), None)
        if existing is not None:
            if existing["request_fingerprint"] != digest({"scope": scope, "input": request["input"]}):
                return {"outcome": "conflict"}
            return {"replayed": True, "occurrence": existing["occurrence"],
                    "outer_command": "command-1", "start": "start-1", "callback": "callback-1"}
        occurrence = {"schedule_id": "schedule-1", "scope": scope}
        record = {
            "request_key": key, "scope": scope,
            "request_fingerprint": digest({"scope": scope, "input": request["input"]}),
            "occurrence": occurrence,
        }
        self.records = [record]
        self.effect_count += 1
        return {
            "occurrence": occurrence,
            "outer_command": "command-1", "start": "start-1", "callback": "callback-1",
            "native_proof": {
                "adapter": "fixture", "session_id": "session-1", "useful": True,
                "scope_digest": digest(scope), "input_digest": digest(request["input"]),
            },
        }

    def lookup(self, scope, request_key, request_input=None):
        return exact_lookup(self.records, scope=scope, request_key=request_key, request_input=request_input)

    def result(self, occurrence):
        return {"schema": "otto.agent-adapter-contract.v1.result-view.v1", "pure": True,
                "occurrence": occurrence, "outcome": "held"}


class InsufficientFixture:
    def launch(self, request):
        return {"occurrence": {"schedule_id": "same"}, "outer_command": "same", "start": "same", "callback": "same"}


class AdapterConformanceTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope_identity(
            project_ref=ref("work.project", "project"), task_ref=ref("work.task", "task"),
            assignment_ref=ref("wrk.assignment", "assignment"), generation=2,
            parent={"assignment_ref": ref("wrk.assignment", "parent"), "generation": 1,
                    "occurrence_ref": ref("wrk.occurrence", "parent-occurrence"),
                    "result_destination": ref("wrk.result", "parent-result")},
        )
        self.request = {"scope": self.scope, "request_key": "stable-key", "input": {"focus": "bounded"},
                        "caller_context": {"principal": "worker", "generation": 2,
                                            "assignment_ref": self.scope["assignment_ref"],
                                            "native_identity": {"session_id": "session-1"}},
                        "caller_principal": "worker"}

    def test_pin_overlap_subtracts_exact_bytes_and_reports_conflict(self):
        prior = pins("old")
        candidate = dict(prior)
        candidate["source"] = {"ref": ref("dat.content.document", "source-new"), "sha256": digest("new")}
        value = subtract_compatible_overlap(candidate, prior)
        self.assertEqual(set(value["overlap"]), {"recovery", "runtime", "client", "resource"})
        self.assertIn("source", value["conflicts"])
        candidate["source"] = {"ref": prior["source"]["ref"], "sha256": digest("changed")}
        self.assertIn("source", subtract_compatible_overlap(candidate, prior)["conflicts"])

    def test_exact_lookup_rejects_changed_input_and_preserves_pure_outcome(self):
        record = {"request_key": "stable-key", "scope": self.scope,
                  "request_fingerprint": digest({"scope": self.scope, "input": {"focus": "bounded"}}),
                  "occurrence": {"schedule_id": "schedule-1"}}
        found = exact_lookup([record], scope=self.scope, request_key="stable-key", request_input={"focus": "bounded"})
        changed = exact_lookup([record], scope=self.scope, request_key="stable-key", request_input={"focus": "other"})
        self.assertEqual(found["outcome"], "found")
        self.assertEqual(changed["outcome"], "conflict")
        self.assertTrue(changed["pure"])

    def test_parent_delivery_and_native_proof_are_exact(self):
        parent = self.scope["parent"]
        validate_parent_binding({"parent": parent}, parent)
        with self.assertRaises(AdapterConformanceFailure):
            validate_parent_binding({"parent": {**parent, "generation": 3}}, parent)
        proof = {"adapter": "fixture", "session_id": "session-1", "useful": True,
                 "scope_digest": digest(self.scope), "input_digest": digest(self.request["input"])}
        self.assertEqual(validate_native_proof(proof, scope=self.scope, request_input=self.request["input"])["session_id"], "session-1")
        with self.assertRaises(AdapterConformanceFailure):
            validate_native_proof({**proof, "useful": False}, scope=self.scope, request_input=self.request["input"])
        self.assertTrue(delivery_identity(ref("wrk.result", "result"), "rev-2").startswith("delivery-"))

    def test_forged_caller_claims_are_rejected(self):
        context = self.request["caller_context"]
        self.assertEqual(validate_caller_claims(context, {"focus": "bounded"})["focus"], "bounded")
        with self.assertRaises(AdapterConformanceFailure):
            validate_caller_claims(context, {"caller_principal": "forged"})

    def test_suite_passes_fixture_and_detects_insufficient_fixture(self):
        good = run_conformance(ConformingFixture(), request=self.request)
        self.assertEqual(good.outcome, "passed", good.to_dict())
        bad = run_conformance(InsufficientFixture(), request=self.request)
        self.assertEqual(bad.outcome, "failed")
        self.assertTrue(any(item["code"] in {"identity_collision", "missing_native_proof", "insufficient_adapter"}
                            for item in bad.failures))

    def test_result_view_is_bounded_and_inventory_fails_closed(self):
        view = bounded_result_view({"conclusion": "x" * 20, "refs": {"result": ref("wrk.result", "r")}}, max_conclusion=8)
        self.assertEqual(len(view["conclusion"]), 8)
        inventory = capability_inventory()
        self.assertEqual(inventory["adapters"]["claude-code"]["capabilities"]["native_identity"], "unverified")
        self.assertIn("manager-only native caller authorization", " ".join(inventory["current_limits"]))
        self.assertTrue(cli_contract()["operations"]["occurrence-lookup"]["required_addition"])

    def test_d01_baseline_is_source_backed_and_pins_compatible_overlap(self):
        artifact = validate_d01_baseline_artifact(d01_baseline_artifact())
        self.assertEqual(artifact["source_identity"]["commit"], "417f1a88ef21a82ce4e326a33ac22f00b7f619d6")
        pins_by_category = artifact["accepted_pins"]
        self.assertEqual(pins_by_category["recovery"]["status"], "unavailable")
        for category in ("source", "runtime", "client", "resource"):
            self.assertEqual(artifact["compatible_overlap"][category]["status"], "compatible")
            self.assertEqual(artifact["compatible_overlap"][category]["ref"], pins_by_category[category]["ref"])
            self.assertEqual(artifact["compatible_overlap"][category]["sha256"], pins_by_category[category]["sha256"])
        self.assertTrue(artifact["qualification"]["source_backed"])
        self.assertEqual(artifact["qualification"]["authentic_qualification"]["claude-code"], "not-established")
        self.assertEqual(artifact["qualification"]["synthetic_negative_suite"]["evidence_kind"], "synthetic-negative-fixtures")


if __name__ == "__main__":
    unittest.main()
