"""Focused ACI-02 proof for editor-buffer autosave and edit activity."""

from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import domain_contribution as edt_contribution
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.kernel.store import Store
from otto.portfolio.document_navigation import ProjectDocumentOperations


class DocumentAutosaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aci-02-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / "isolated.sqlite", authority="aci-owner")
        self.store.register_domain_handler((domain_contribution(), edt_contribution()))
        self.actor = AuthenticatedActor("aci-owner", "owner", "fixture-credential")
        self.content = ContentCommandHandler(self.store)
        self.authoring = DocumentAuthoringHandler(self.store)
        self.document_ref = ResourceRef("aci-owner", "dat.content.document", "owned")
        document = ContentDocument(self.document_ref, "notes", "shared", "write", "owner")
        revision = ContentRevision(
            self.document_ref, "rev-1", {"text": "Opening bytes"}, self.actor, initial=True,
        )
        self.content.execute(self.content.build_create_document(
            TransactionContext(self.actor, "create", "a" * 64), document, revision,
        ))
        self.document = document
        self.addCleanup(self.store.close)

    def session_payload(self, opened):
        record = self.authoring.reader.get_identity(opened.handle.scope)
        self.assertIsNotNone(record)
        return record.payload

    def test_changed_editor_buffer_autosaves_without_publication_and_unchanged_save_is_quiet(self):
        opened = self.authoring.open_owned(self.document_ref, self.actor, request_id="open")
        buffer_value = {"content": {"text": "Edited"}}

        saved = self.authoring.autosave(
            opened, buffer_value, request_id="autosave-1", content_edit_at=101.0,
        )
        self.assertEqual(saved.status, "saved")
        self.assertTrue(saved.changed)
        self.assertEqual(saved.last_content_edit, 101.0)
        self.assertTrue(saved.nonpublishing)
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")
        payload = self.session_payload(opened)
        self.assertEqual(payload["draft_digest"], saved.snapshot_digest)
        self.assertEqual(payload["last_content_edit"], 101.0)

        unchanged = self.authoring.autosave(
            opened, buffer_value, request_id="autosave-unchanged", content_edit_at=999.0,
        )
        self.assertEqual(unchanged.status, "unchanged")
        self.assertFalse(unchanged.changed)
        self.assertEqual(unchanged.last_content_edit, 101.0)
        self.assertEqual(self.session_payload(opened)["last_content_edit"], 101.0)

        # Holder reads and status polling are observational only.
        self.authoring.edit_status(opened, self.actor)
        self.authoring.read(self.document_ref, self.actor)
        self.assertEqual(self.session_payload(opened)["last_content_edit"], 101.0)

        changed = self.authoring.autosave(
            opened, {"content": {"text": "Edited again"}},
            request_id="autosave-2", content_edit_at=202.0,
        )
        self.assertEqual(changed.status, "saved")
        self.assertEqual(changed.last_content_edit, 202.0)
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")

    def test_host_autosave_surface_labels_draft_and_explicit_check_in_remains_separate(self):
        class VisibleReader:
            def list_documents(self, *args, **kwargs):
                return {"outcome": "listed", "documents": [{"document_ref": self_ref.to_dict()}]}

            def read_document(self, *args, **kwargs):
                return {"outcome": "read", "content": {"text": "projection"}}

        self_ref = self.document_ref
        nav = ProjectDocumentOperations(
            document_reader=VisibleReader(), authoring=self.authoring,
            context_reader=object(),
        )
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"),
            self.document_ref, actor=self.actor, request_id="open",
        )

        result = nav.autosave_edit(
            opened, {"content": {"text": "Host draft"}},
            request_id="host-autosave", content_edit_at=303.0,
        )
        self.assertEqual(result["outcome"], "autosaved")
        self.assertTrue(result["nonpublishing"])
        self.assertFalse(result["dat_revision_advanced"])
        self.assertEqual(result["publication"]["status"], "not_published")
        self.assertEqual(result["publication"]["direction_adoption"], "not_performed")
        self.assertEqual(result["publication"]["assignment_adoption"], "not_performed")
        self.assertEqual(result["publication"]["resource_adoption"], "not_performed")
        self.assertEqual(result["publication"]["invocation_context"], "unchanged")

        # The content head changes only when the existing explicit finish path
        # is called; autosave itself has no publication effect.
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")
        finished = nav.finish_edit(
            opened, {"content": {"text": "Host draft"}}, request_id="explicit-check-in",
        )
        self.assertEqual(finished["outcome"], "applied")
        self.assertEqual(finished["publication"]["status"], "committed")
        self.assertEqual(finished["publication"]["dat_revision_ref"], finished["revision_ref"])
        self.assertIsNotNone(finished["publication"]["receipt"])
        self.assertEqual(finished["publication"]["direction_adoption"], "not_performed")
        self.assertEqual(finished["publication"]["assignment_adoption"], "not_performed")
        self.assertEqual(finished["publication"]["resource_adoption"], "not_performed")
        self.assertEqual(finished["publication"]["invocation_context"], "unchanged")
        self.assertNotEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")


if __name__ == "__main__":
    unittest.main()
