"""Focused ACI-04 proof for the host one-shot idle check-in boundary."""

import json
from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import AuthoringLifecycle, FileWriterLeaseAuthority
from herzchen.authoring import domain_contribution as edt_contribution
from herzchen.authoring.sessions import AuthoringSessionService
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.kernel.store import Store
from otto.portfolio.document_navigation import ProjectDocumentOperations


class DocumentIdleCheckinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aci-04-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store.create(self.root / "isolated.sqlite", authority="aci-owner")
        self.store.register_domain_handler((domain_contribution(), edt_contribution()))
        self.actor = AuthenticatedActor("aci-owner", "owner", "fixture-credential")
        self.content = ContentCommandHandler(self.store)
        self.document_ref = ResourceRef("aci-owner", "dat.content.document", "owned")
        self.document = ContentDocument(self.document_ref, "notes", "shared", "write", "owner")
        revision = ContentRevision(
            self.document_ref, "rev-1", {"text": "Opening bytes"}, self.actor, initial=True,
        )
        self.content.execute(self.content.build_create_document(
            TransactionContext(self.actor, "create", "a" * 64), self.document, revision,
        ))
        self.clock_value = 1_000.0

        def materializer(checkout, initial_bytes):
            path = self.root / checkout.session_id
            path.mkdir()
            (path / "document.json").write_bytes(initial_bytes)
            return {"path": str(path), "registered_files": ["document.json"]}

        self.service = AuthoringSessionService(self.store, materializer=materializer)
        self.authoring = DocumentAuthoringHandler(self.store, authoring=self.service)
        leases = FileWriterLeaseAuthority(
            self.root / "locks", authority="aci-owner", secret=b"s" * 32,
            writer_identities=("host",), clock=lambda: self.clock_value,
        )
        self.lifecycle = AuthoringLifecycle(
            self.service, writer_leases=leases, writer_identity="host",
            clock=lambda: self.clock_value,
        )
        self_ref = self.document_ref

        class VisibleReader:
            def list_documents(self, *args, **kwargs):
                return {"outcome": "listed", "documents": [{"document_ref": self_ref.to_dict()}]}

            def read_document(self, *args, **kwargs):
                return {"outcome": "read", "content": {"text": "projection"}}

        self.nav = ProjectDocumentOperations(
            document_reader=VisibleReader(), authoring=self.authoring,
            context_reader=object(), idle_lifecycle=self.lifecycle,
        )
        self.addCleanup(self.store.close)

    def test_timer_attempt_checks_in_through_existing_finish_and_cleanup(self):
        opened = self.nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open",
        )
        self.assertEqual(
            self.nav.autosave_edit(
                opened, {"content": {"text": "Edited"}},
                request_id="autosave", content_edit_at=100.0,
            )["outcome"],
            "autosaved",
        )
        checkout_root = Path(opened.handle.checkout_path)
        (checkout_root / "document.json").write_text(
            json.dumps({"content": {"text": "Edited"}}), encoding="utf-8",
        )

        result = self.nav.idle_close_edit(
            opened, actor=self.actor, request_id="idle",
            inactivity_seconds=900.0, now=1_000.0,
            writer_check=lambda: "quiescent",
        )

        self.assertEqual(result["outcome"], "checked_in", result)
        self.assertTrue(result["durable_checked_in"])
        self.assertFalse(result["cleanup_pending"])
        self.assertTrue(result["dat_revision_advanced"])
        self.assertEqual(result["publication"]["status"], "committed")
        self.assertEqual(result["publication"]["direction_adoption"], "not_performed")
        self.assertEqual(result["publication"]["assignment_adoption"], "not_performed")
        self.assertEqual(result["publication"]["resource_adoption"], "not_performed")
        self.assertEqual(result["publication"]["invocation_context"], "unchanged")
        self.assertEqual(
            result["publication"]["dat_revision_ref"]["revision"],
            self.content.read(self.document_ref)["current_revision"]["revision"],
        )
        self.assertIsNotNone(result["publication"]["receipt"])
        self.assertFalse((checkout_root / "document.json").exists())
        self.assertNotEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")

    def test_timer_attempt_inhibits_when_quiescence_is_uncertain(self):
        opened = self.nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open",
        )
        result = self.nav.idle_close_edit(
            opened, actor=self.actor, request_id="idle",
            inactivity_seconds=0.0, now=1_000.0,
        )

        self.assertEqual(result["outcome"], "writer_active", result)
        self.assertTrue(result["recovery_pending"])
        self.assertFalse(result["dat_revision_advanced"])
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")

    def test_timer_attempt_does_not_infer_a_missing_edit_timestamp(self):
        opened = self.nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open",
        )
        result = self.nav.idle_close_edit(
            opened, actor=self.actor, request_id="idle",
            inactivity_seconds=0.0, now=1_000.0,
            writer_check=lambda: "quiescent",
        )

        self.assertEqual(result["outcome"], "recovery_pending", result)
        self.assertTrue(result["recovery_pending"])
        self.assertFalse(result["dat_revision_advanced"])
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")


if __name__ == "__main__":
    unittest.main()
