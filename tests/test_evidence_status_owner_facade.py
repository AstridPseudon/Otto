from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from otto.portfolio import retention_owner_read as retention
from otto.portfolio.retention_owner_read import RetentionOwnerRead
from otto.portfolio.tests import test_retention_owner_read as retention_fixture


class EvidenceStatusOwnerFacadeTests(unittest.TestCase):
    def setUp(self):
        self.f = retention_fixture.RetentionOwnerReadTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def _capability(self):
        root, _subject, _pin, project = self.f.setup_portfolio()
        project = self.f.complete_project_for_preview(project)
        register_evidence(self.f.store)
        from tests.test_evidence_reclaim import _current_pack
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.evidence_payload_root = Path(directory.name) / "managed"
        handler = EvidenceCommandHandler(
            self.f.store, self.evidence_payload_root, pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources])
        submitted = handler.submit(
            b"owner-status-payload", actor=self.f.actor, logical_request_key="status-submit",
            project_ref=project.ref, original_creator="fixture")
        service = SimpleNamespace(server=SimpleNamespace(owner=self.f.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        expected = submitted["revision_ref"].to_dict()
        return root, project, submitted, RetentionOwnerRead(service, evidence_handler=handler), expected

    def _status(self, capability, root, project, reference):
        with patch.object(retention, "USAGE_PROJECT_ID", project.ref.id), \
             patch.object(retention, "_KNOWN_EVIDENCE_STATUS_REFERENCE", reference):
            return capability.call({"request_key": "status-read-v1",
                                    "handle": {"view": "evidence-status", "reference": reference}},
                                   root=root, actor=self.f.actor)

    def test_exact_known_pin_reads_bounded_managed_status_without_payload_or_claims(self):
        root, project, submitted, capability, reference = self._capability()
        result = self._status(capability, root, project, reference)
        self.assertEqual(result["outcome"], "read")
        self.assertTrue(result["complete"])
        self.assertEqual(result["reference"], reference)
        self.assertEqual(result["representation"], "managed")
        self.assertEqual(result["evidence_role"], "evidence")
        self.assertEqual(result["availability"], "admitted")
        self.assertEqual(result["payload_verification"], "not-revalidated")
        self.assertEqual(result["provenance"]["project_ref"]["id"], project.ref.id)
        self.assertEqual(result["byte_length"], len(b"owner-status-payload"))
        self.assertNotIn("document", result)
        self.assertNotIn("manifest", result)
        self.assertEqual(result["eligibility"], "not-evaluated")
        self.assertEqual(result["dependency_evaluation"], "not-performed")
        self.assertFalse(result["provider_called"])
        self.assertEqual(result["writes"], 0)

    def test_missing_payload_remains_no_eligibility_claim_and_no_payload_reads(self):
        root, project, submitted, capability, reference = self._capability()
        handler = capability.evidence_handler
        status = handler.status(reference, actor=self.f.actor)
        payload = self.evidence_payload_root / status["manifest"]["storage"]["location"]
        payload.unlink()  # Only this disposable fixture's admitted payload.
        before = self.f.store.consumer().snapshot_counts()
        result = self._status(capability, root, project, reference)
        self.assertEqual(result["availability"], "missing")
        self.assertEqual(result["eligibility"], "not-evaluated")
        self.assertEqual(result["dependency_evaluation"], "not-performed")
        self.assertTrue(all(result["io_work"][name] == 0 for name in
            ("payload_bytes_read", "payload_bytes_parsed", "payload_bytes_hashed")))
        self.assertEqual(self.f.store.consumer().snapshot_counts(), before)

    def test_non_evidence_role_or_foreign_head_is_not_project_authority(self):
        root, project, submitted, capability, reference = self._capability()
        original = capability.evidence_handler.status(reference, actor=self.f.actor)
        for changed in ({**original, "document": {**original["document"], "role": "SOURCE"}},
                        {**original, "current_head": {**reference, "id": "foreign-head"}}):
            capability.evidence_handler = SimpleNamespace(status=lambda *a, value=changed, **k: value)
            with self.assertRaises(PermissionError):
                self._status(capability, root, project, reference)

    def test_foreign_and_stale_reference_selectors_fail_before_handler_status(self):
        root, project, submitted, capability, reference = self._capability()
        foreign = dict(reference, id="foreign-evidence")
        stale = dict(reference, revision="rev-0")
        with patch.object(retention, "USAGE_PROJECT_ID", project.ref.id), \
             patch.object(retention, "_KNOWN_EVIDENCE_STATUS_REFERENCE", reference):
            with self.assertRaises(PermissionError):
                capability.call({"handle": {"view": "evidence-status", "reference": reference}},
                                root=root, actor=self.f.owner.binding.authenticated_actor("foreign"))
            for bad in (foreign, stale):
                with self.assertRaises(PermissionError):
                    capability.call({"handle": {"view": "evidence-status", "reference": bad}},
                                    root=root, actor=self.f.actor)

    def test_foreign_provenance_and_oversize_status_are_refused(self):
        root, project, submitted, capability, reference = self._capability()
        original_handler = capability.evidence_handler
        original = original_handler.status
        def foreign_status(ref, *, actor, roles=(), scopes=()):
            value = dict(original(ref, actor=actor, roles=roles, scopes=scopes))
            value["manifest"] = dict(value["manifest"], origin=dict(value["manifest"]["origin"],
                project_ref={**project.ref.to_dict(), "id": "foreign-project"}))
            return value
        capability.evidence_handler = SimpleNamespace(status=foreign_status)
        with patch.object(retention, "USAGE_PROJECT_ID", project.ref.id), \
             patch.object(retention, "_KNOWN_EVIDENCE_STATUS_REFERENCE", reference):
            with self.assertRaises(PermissionError):
                capability.call({"handle": {"view": "evidence-status", "reference": reference}},
                                root=root, actor=self.f.actor)
        capability.evidence_handler = SimpleNamespace(status=lambda ref, *, actor, roles=(), scopes=(): {
            "reference": ref.to_dict(), "current_head": ref.to_dict(), "representation": "managed",
            "manifest": {"record_type": "dat.evidence.manifest", "origin": {"project_ref": project.ref.to_dict()},
                         "storage": {"kind": "managed-file"}, "byte_length": 1,
                         "byte_digest": "a" * 64, "oversize": "x" * 70000},
            "availability": "admitted", "payload_verification": "not-revalidated"})
        with patch.object(retention, "USAGE_PROJECT_ID", project.ref.id), \
             patch.object(retention, "_KNOWN_EVIDENCE_STATUS_REFERENCE", reference):
            with self.assertRaises(ValueError):
                capability.call({"handle": {"view": "evidence-status", "reference": reference}},
                                root=root, actor=self.f.actor)

    def test_tool_facade_preserves_owner_error_code_and_message(self):
        from herzchen.fleet.landing import LandingError
        from herzchen.fleet.tools.facade import LandingOwnerPort, ToolFacade
        from herzchen.fleet.tools.rules import DONE, FeedbackLedger, ToolSpec
        from herzchen.fleet.tools.tokens import TokenBook

        class Landing:
            def done(self, _lab_name, _task_id, **_pins):
                raise LandingError("owner assessment policy does not bind this task: local assessment policy task content is stale")

        book = TokenBook()
        token = book.issue("assignment-1", "worker")
        port = LandingOwnerPort(lambda _assignment: {
            "service": Landing(), "lab_name": "task-lab", "task_id": "task-1",
            "assignment_id": "assignment-1"})
        facade = ToolFacade(
            (ToolSpec("done", DONE, "worker-done"),),
            {"worker": ("done",)}, port, book, FeedbackLedger())

        self.assertEqual(facade.call(token, "done"), {
            "ok": False,
            "error": "LandingError",
            "detail": "owner assessment policy does not bind this task: local assessment policy task content is stale",
        })

    def test_tool_facade_keeps_generic_fallback_for_unclassified_owner_errors(self):
        from herzchen.fleet.tools.facade import ToolFacade
        from herzchen.fleet.tools.rules import FeedbackLedger, TASK, ToolSpec
        from herzchen.fleet.tools.tokens import TokenBook

        class Owner:
            def call(self, *_args, **_kwargs):
                raise RuntimeError()

        book = TokenBook()
        token = book.issue("assignment-1", "worker")
        facade = ToolFacade(
            (ToolSpec("task", TASK, "read-task"),),
            {"worker": ("task",)}, Owner(), book, FeedbackLedger())

        self.assertEqual(facade.call(token, "task"), {
            "ok": False, "error": "owner_unavailable", "detail": "RuntimeError"})


if __name__ == "__main__":
    unittest.main()
