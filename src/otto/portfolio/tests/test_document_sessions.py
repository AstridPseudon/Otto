"""Focused ACI-03 proof for inventory, resume, recovery and discard."""

from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import domain_contribution as edt_contribution
from herzchen.authoring.sessions import InvalidSessionError
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.kernel.store import Store
from otto.portfolio.document_navigation import ProjectDocumentOperations


class DocumentSessionInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aci-03-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "isolated.sqlite"
        self.domains = (domain_contribution(), edt_contribution())
        self.store = Store.create(self.path, authority="aci-owner")
        self.store.register_domain_handler(self.domains)
        self.actor = AuthenticatedActor("aci-owner", "owner", "fixture-credential")
        self.content = ContentCommandHandler(self.store)
        self.authoring = DocumentAuthoringHandler(self.store)
        self.document_ref = ResourceRef("aci-owner", "dat.content.document", "owned")
        self.document = ContentDocument(self.document_ref, "notes", "shared", "write", "owner")
        revision = ContentRevision(
            self.document_ref, "rev-1", {"text": "Opening bytes"}, self.actor, initial=True,
        )
        self.content.execute(self.content.build_create_document(
            TransactionContext(self.actor, "create", "a" * 64), self.document, revision,
        ))
        self.addCleanup(self.store.close)

    def restart(self):
        self.store.close()
        self.store = Store.open(self.path, authority="aci-owner", expected_domains=self.domains)
        self.content = ContentCommandHandler(self.store)
        self.authoring = DocumentAuthoringHandler(self.store)

    def test_inventory_is_canonical_and_conservative_after_lost_handle(self):
        opened = self.authoring.open_owned(self.document_ref, self.actor, request_id="open")

        inventory = self.authoring.session_inventory(self.actor)
        self.assertEqual(inventory["count"], 1)
        entry = inventory["sessions"][0]
        self.assertEqual(entry["holder"]["actor"], "owner")
        self.assertNotIn("credential_ref", entry["holder"])
        self.assertEqual(entry["target_ref"], self.document_ref.to_dict())
        self.assertEqual(entry["base_revision"], "rev-1")
        self.assertIsNone(entry["last_content_edit"])
        self.assertTrue(entry["recovery_pending"])
        self.assertFalse(entry["has_valid_handle"])
        self.assertNotIn("token", entry)
        self.assertNotIn("fence", entry)
        self.assertTrue(inventory["no_takeover"])
        self.assertTrue(inventory["no_timestamp_inference"])

        with_handle = self.authoring.session_inventory(self.actor, handles=(opened.handle,))
        self.assertEqual(with_handle["sessions"][0]["recovery_status"], "active")
        self.assertTrue(with_handle["sessions"][0]["has_valid_handle"])

        saved = self.authoring.autosave(opened, {"content": {"text": "Draft"}}, request_id="autosave", content_edit_at=123.0)
        current = self.authoring.session_inventory(self.actor)["sessions"][0]
        self.assertEqual(current["last_content_edit"], 123.0)
        self.assertEqual(current["draft_digest"], saved.snapshot_digest)

        self.restart()
        after_restart = self.authoring.session_inventory(self.actor)["sessions"][0]
        self.assertEqual(after_restart["recovery_status"], "recovery_pending")
        self.assertEqual(after_restart["last_content_edit"], 123.0)
        resumed = self.authoring.resume(self.document_ref, self.actor, opened.handle)
        self.assertEqual(resumed.open_result.status, "resumed")
        self.assertEqual(resumed.handle.session_id, opened.handle.session_id)

    def test_host_resume_and_explicit_discard_are_nonpublishing(self):
        class VisibleReader:
            def list_documents(self, *args, **kwargs):
                return {"outcome": "listed", "documents": [{"document_ref": self_ref.to_dict()}]}

            def read_document(self, *args, **kwargs):
                return {"outcome": "read", "content": {"text": "projection"}}

        self_ref = self.document_ref
        nav = ProjectDocumentOperations(
            document_reader=VisibleReader(), authoring=self.authoring, context_reader=object(),
        )
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"),
            self.document_ref, actor=self.actor, request_id="open",
        )
        resumed = nav.resume_edit(self.document_ref, actor=self.actor, handle=opened.handle)
        self.assertEqual(resumed.open_result.status, "resumed")
        before = self.content.read(self.document_ref)["current_revision"]["revision"]

        recovered = nav.recover_session(actor=self.actor, session_id=opened.handle.session_id)
        self.assertEqual(recovered["status"], "open")
        discarded = nav.discard_session(
            actor=self.actor, session_id=opened.handle.session_id, request_id="discard",
        )
        self.assertEqual(discarded["outcome"], "discarded")
        self.assertTrue(discarded["nonpublishing"])
        self.assertFalse(discarded["dat_revision_advanced"])
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], before)
        self.assertEqual(self.authoring.session_inventory(self.actor)["sessions"][0]["state"], "released")
        self.assertEqual(self.authoring.session_inventory(self.actor)["sessions"][0]["cleanup_status"], "pending")

    def test_recover_requires_valid_handle_and_never_publishes(self):
        opened = self.authoring.open_owned(self.document_ref, self.actor, request_id="open")
        recovery = self.authoring.recover(opened, self.actor)
        self.assertEqual(recovery["status"], "open")
        self.assertTrue(recovery["nonpublishing"])
        self.assertTrue(recovery["read_only"])
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")

        forged = type(opened.handle)(
            opened.handle.scope, opened.handle.target_scope, opened.handle.target_kind,
            opened.handle.actor, opened.handle.session_id, "forged", opened.handle.fence,
            opened.handle.base_revision, opened.handle.checkout_path,
        )
        with self.assertRaises(InvalidSessionError):
            self.authoring.authoring.recover(forged)


if __name__ == "__main__":
    unittest.main()
