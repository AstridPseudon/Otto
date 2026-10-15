"""Managed evidence must be fully verified before it supports PASS, acceptance, or completion.

These tests describe behaviour that the assessment module does not implement
yet: a managed DAT payload is verified byte-for-byte through a payload_resolver
before it can back an assess call, an accept call, a no-review acceptance, or a
completion gate.  Most of them are expected to fail on the current code.
"""
import hashlib
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
import unittest

import test_evidence_lifecycle as lifecycle
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.assessment import AssessmentModule, contribution as assessment_contribution
from herzchen.domains.assessment.model import AssessmentAuthorityError, AssessmentStateError
from herzchen.domains.assessment.module import verify_dat_evidence
from herzchen.evidence.commands import EvidenceCommandHandler
from herzchen.evidence.model import load_evidence_pack
from herzchen.kernel.limits import LimitService

RUNNER_BYTES = b"runner output bytes"
OCTET_STREAM = "application/octet-stream"


def _digests(items):
    """Digest strings from evidence_digests items, which are dicts or bare digests."""
    values = set()
    for item in items:
        values.add(item.get("digest") if isinstance(item, Mapping) else item)
    return values


class EvidenceVerificationTests(unittest.TestCase):
    _submit = lifecycle.EvidenceLifecycleTests._submit
    tearDown = lifecycle.EvidenceLifecycleTests.tearDown

    def setUp(self):
        lifecycle.EvidenceLifecycleTests.setUp(self)
        # Same public pack snapshot as src/otto/portfolio/tests/test_bounded_evidence_reads.py.
        root, discover, loader = lifecycle._public_pack_hooks()
        found = discover(project_root=root)[0]
        found.entry.definition.version = "1.1.0"
        found.entry.definition.to_dict = lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2}
        found.entry.resource_handles += tuple(SimpleNamespace(path=path, kind="evidence_preset",
            resolved=root / path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
            for path in ("presets/list.json", "presets/read.json"))
        self.pack = load_evidence_pack(project_root=root, discoverer=lambda **kwargs: (found,), loader=loader)
        self.handler = EvidenceCommandHandler(self.store, Path(self.directory.name) / "managed", pack=self.pack,
            adopted_pins=[item.to_dict() for item in self.pack.resources])
        self.store.register_domain_handler((assessment_contribution(),))
        self.pool = LimitService(self.store).create_pool(
            ResourceRef("owner", "limit", "evidence-pool"), capacity_units=10, cumulative_allowance_units=10,
            logical_request_key="evidence-pool", actor=self.actor)
        # Dedicated admitted candidate, created with a concrete revision so that
        # completion_blockers sees a pinned, current candidate reference.
        candidate_ref = ResourceRef("owner", "work.attempt", "candidate", "rev-1")
        self.store.put_identity(candidate_ref, {"record_type": "work.attempt", "project_ref": self.project,
                                                "task_ref": self.task}, version=0)
        self.candidate = self.store.get_identity(candidate_ref).ref
        self.assertIsNotNone(self.candidate.revision)

    def _module(self, *, resolver=True):
        if resolver:
            return AssessmentModule(self.store, actor=self.actor, payload_resolver=self.handler)
        return AssessmentModule(self.store, actor=self.actor)

    def _runner(self, payload, key):
        return self._submit(payload, key, format=OCTET_STREAM)

    def _declare(self, assessment, scope_id, *, task=None, criterion_id="runner-passed"):
        scope = assessment.declare_scope(scope_id, parent_obligation=task or self.task,
            protocol="evidence-check",
            criteria=[{"id": criterion_id, "definition": "runner check passed"}],
            review_required=False, allow_no_review=True, designated_approver=self.actor.actor,
            policy={"required_for_completion": True}, logical_request_key=scope_id + "-declare")
        packet = assessment.freeze_input(scope.ref, packet={"runner": "ok"}, consumed_refs=[],
            logical_request_key=scope_id + "-input")
        return scope, packet

    def _assess(self, assessment, scope, packet, key, *, evidence=None, candidate=None):
        kwargs = dict(candidate=candidate or self.candidate, criterion=scope.criterion_refs[0],
            input_packet=packet.ref, verdict="PASS", limit_pool=self.pool.ref, logical_request_key=key)
        if evidence is not None:
            kwargs["evidence_refs"] = list(evidence)
        return assessment.assess(scope.ref, **kwargs)

    def _flip_first_byte(self, submitted):
        path = Path(self.directory.name) / "managed" / submitted["manifest"]["storage"]["location"]
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])

    def test_managed_result_verifies(self):
        runner = self._runner(RUNNER_BYTES, "runner-1")
        digest = hashlib.sha256(RUNNER_BYTES).hexdigest()
        verified = verify_dat_evidence(self.store, runner["revision_ref"], actor=self.actor,
                                       payload_resolver=self.handler)
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(verified["digest"], digest)
        self.assertEqual(verified["verification_scope"], "full-payload")

        assessment = self._module()
        scope, packet = self._declare(assessment, "runner-scope")
        result = self._assess(assessment, scope, packet, "runner-1-assess", evidence=[runner["revision_ref"]])
        self.assertIn(digest, _digests(result.payload["evidence_digests"]))
        decision = assessment.accept(result.ref, rationale="runner evidence verified",
                                     evidence_refs=[runner["revision_ref"]], logical_request_key="runner-1-accept")
        self.assertIn(digest, _digests(decision.payload["evidence_digests"]))

    def test_unknown_never_accepted(self):
        runner = self._runner(RUNNER_BYTES, "runner-1")
        # No payload_resolver: managed bytes cannot be fully verified, so they stay unknown.
        assessment = self._module(resolver=False)
        self.assertEqual(verify_dat_evidence(self.store, runner["revision_ref"], actor=self.actor)["state"],
                         "unknown")
        scope, packet = self._declare(assessment, "unknown-scope")
        result = self._assess(assessment, scope, packet, "unknown-assess")
        criterion = scope.criterion_refs[0]

        with self.assertRaises(AssessmentStateError):
            assessment.accept(result.ref, rationale="unverified evidence",
                              evidence_refs=[runner["revision_ref"]], logical_request_key="unknown-accept")
        with self.assertRaises(AssessmentStateError):
            assessment.accept_without_review(scope.ref, candidate=self.candidate, criterion=criterion,
                                             rationale="unverified evidence", evidence_refs=[runner["revision_ref"]],
                                             logical_request_key="unknown-no-review")
        with self.assertRaises(AssessmentAuthorityError):
            assessment.accept_without_review(scope.ref, candidate=self.candidate, criterion=criterion,
                                             rationale="no evidence", evidence_refs=(),
                                             logical_request_key="no-evidence-no-review")
        self.assertEqual(assessment.list_decisions(parent_obligation=self.task), ())
        with self.assertRaises(AssessmentStateError):
            self._assess(assessment, scope, packet, "unknown-assess-evidence", evidence=[runner["revision_ref"]])

    def test_no_review_scope_accepts_verified_result(self):
        runner = self._runner(RUNNER_BYTES, "runner-1")
        digest = hashlib.sha256(RUNNER_BYTES).hexdigest()
        assessment = self._module()
        scope, packet = self._declare(assessment, "check-accepted-scope")

        decision = assessment.accept_without_review(scope.ref, candidate=self.candidate,
            criterion=scope.criterion_refs[0], rationale="check passed",
            evidence_refs=[runner["revision_ref"]], logical_request_key="no-review-accept")
        self.assertEqual(decision.disposition, "accept")
        self.assertIs(decision.payload.get("no_review"), True)
        self.assertIn(digest, _digests(decision.payload["evidence_digests"]))

        result = self._assess(assessment, scope, packet, "check-assess", evidence=[runner["revision_ref"]])
        accepted = assessment.accept(result.ref, rationale="check passed", evidence_refs=[runner["revision_ref"]],
                                     logical_request_key="check-accept")
        self.assertEqual(accepted.disposition, "accept")
        self.assertFalse(accepted.payload["review_evidence"])
        self.assertIn(digest, _digests(accepted.payload["evidence_digests"]))

    def test_astra0_runner_evidence_accepted_and_tamper_refused(self):
        assessment = self._module()
        good = self._runner(RUNNER_BYTES, "runner-1")
        scope_good, _ = self._declare(assessment, "astra0-good-scope", criterion_id="runner-passed")
        decision = assessment.accept_without_review(scope_good.ref, candidate=self.candidate,
            criterion=scope_good.criterion_refs[0], rationale="runner evidence verified",
            evidence_refs=[good["revision_ref"]], logical_request_key="astra0-good-accept")
        self.assertIn(hashlib.sha256(RUNNER_BYTES).hexdigest(), _digests(decision.payload["evidence_digests"]))

        # Separate task and criterion so the accepted part-1 decision cannot satisfy this gate.
        task_b = ResourceRef("owner", "work.task", "task-tamper")
        self.store.put_identity(task_b, {"record_type": "work.task", "project_ref": self.project, "title": "tamper task"},
                                version=0)
        bad = self._runner(b"runner-2 bytes", "runner-2")
        self._flip_first_byte(bad)
        scope_b, packet_b = self._declare(assessment, "astra0-tamper-scope", task=task_b,
                                          criterion_id="runner-passed-tamper")
        with self.assertRaises(AssessmentStateError):
            self._assess(assessment, scope_b, packet_b, "astra0-tamper-assess", evidence=[bad["revision_ref"]])
        with self.assertRaises(AssessmentStateError):
            assessment.accept_without_review(scope_b.ref, candidate=self.candidate,
                criterion=scope_b.criterion_refs[0], rationale="tampered runner evidence",
                evidence_refs=[bad["revision_ref"]], logical_request_key="astra0-tamper-no-review")

        blockers = assessment.completion_blockers(task_b, candidate=self.candidate,
            gate_refs=[], actor=self.actor, evidence_store=self.store, payload_resolver=self.handler)
        self.assertTrue(blockers["required"])
        codes = [item["code"] for item in blockers["blockers"]]
        # The candidate is pinned and current, so the block must come from the evidence gate.
        self.assertNotIn("completion_candidate_stale", codes)
        self.assertTrue({"criterion_uncovered", "pass_not_accepted"} & set(codes), codes)

    def test_result_binds_the_evidence_it_was_verified_against(self):
        runner = self._runner(RUNNER_BYTES, "runner-1")
        assessment = self._module()
        scope, packet = self._declare(assessment, "bind-scope")
        result = self._assess(assessment, scope, packet, "bind-assess", evidence=[runner["revision_ref"]])
        # Tamper with the bytes after the PASS result bound their digest.
        self._flip_first_byte(runner)
        with self.assertRaises(AssessmentStateError):
            assessment.accept(result.ref, rationale="tampered after assess", evidence_refs=[],
                              logical_request_key="bind-accept")
        self.assertEqual(assessment.list_decisions(parent_obligation=self.task), ())

    def test_tamper_after_accept_blocks_completion(self):
        runner = self._runner(RUNNER_BYTES, "runner-1")
        assessment = self._module()
        scope, packet = self._declare(assessment, "gate-scope")
        result = self._assess(assessment, scope, packet, "gate-assess", evidence=[runner["revision_ref"]])
        decision = assessment.accept(result.ref, rationale="runner passed",
                                     evidence_refs=[runner["revision_ref"]], logical_request_key="gate-accept")
        candidate = assessment.get_result(result.ref).candidate_ref

        clean = assessment.completion_blockers(self.task, candidate=candidate, gate_refs=[decision.ref],
            actor=self.actor, evidence_store=self.store, payload_resolver=self.handler)
        self.assertEqual(clean["blockers"], [])
        self.assertEqual(clean["evidence_verification"], "verified")

        self._flip_first_byte(runner)
        blocked = assessment.completion_blockers(self.task, candidate=candidate, gate_refs=[decision.ref],
            actor=self.actor, evidence_store=self.store, payload_resolver=self.handler)
        self.assertIn("completion_evidence_mismatch", [item["code"] for item in blocked["blockers"]])
        self.assertEqual(blocked["evidence_verification"], "mismatch")


if __name__ == "__main__":
    unittest.main()
