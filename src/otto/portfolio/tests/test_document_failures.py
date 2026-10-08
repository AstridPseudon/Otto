"""Focused ACI-05 proof for durable failure, replay and notification state."""

from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import domain_contribution as edt_contribution
from herzchen.authoring import AuthoringLifecycle, FileWriterLeaseAuthority
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.kernel.store import Store
from otto.portfolio.document_navigation import ProjectDocumentOperations


class DocumentFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aci-05-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / "isolated.sqlite", authority="aci-owner")
        self.domains = (domain_contribution(), edt_contribution())
        self.store.register_domain_handler(self.domains)
        self.actor = AuthenticatedActor("aci-owner", "owner", "fixture-credential")
        self.content = ContentCommandHandler(self.store)
        self.authoring = DocumentAuthoringHandler(self.store)
        self.document_ref = ResourceRef("aci-owner", "dat.content.document", "owned")
        self.document = ContentDocument(self.document_ref, "notes", "shared", "write", "owner")
        revision = ContentRevision(self.document_ref, "rev-1", {"text": "Opening bytes"}, self.actor, initial=True)
        self.content.execute(self.content.build_create_document(
            TransactionContext(self.actor, "create", "a" * 64), self.document, revision,
        ))
        self.addCleanup(self.store.close)

    def nav(self, lifecycle=None):
        ref = self.document_ref

        class VisibleReader:
            def list_documents(self, *args, **kwargs):
                return {"outcome": "listed", "documents": [{"document_ref": ref.to_dict()}]}

            def read_document(self, *args, **kwargs):
                return {"outcome": "read", "content": {"text": "projection"}}

        return ProjectDocumentOperations(
            document_reader=VisibleReader(), authoring=self.authoring,
            context_reader=object(), idle_lifecycle=lifecycle,
        )

    def test_invalid_draft_is_retained_and_notification_waits_for_receipt(self):
        nav = self.nav()
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open",
        )

        result = nav.finish_edit(opened, {"unknown": "invalid"}, request_id="finish-invalid")

        self.assertEqual(result["failure_status"], "validation_failed")
        self.assertEqual(result["publication"]["status"], "not_published")
        self.assertEqual(result["publication"]["direction_adoption"], "not_performed")
        self.assertIsNone(result["publication"]["dat_revision_ref"])
        self.assertEqual(result["recovery_actions"], ["correct_draft", "retry"])
        self.assertTrue(result["notification"]["durable"], result)
        self.assertTrue(result["notification"]["retryable"])
        self.assertIsNotNone(result["draft_snapshot_ref"])
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")
        inventory = self.authoring.session_inventory(self.actor, handles=(opened.handle,))
        self.assertEqual(inventory["sessions"][0]["recovery_status"], "validation_failed")
        self.assertEqual(inventory["sessions"][0]["failure_status"], "validation_failed")

    def test_writer_failure_is_durable_and_replay_does_not_publish(self):
        from herzchen.authoring import IdleCloseService

        opened = self.authoring.open_owned(self.document_ref, self.actor, request_id="open")
        service = IdleCloseService(self.authoring.authoring, clock=lambda: 1000.0)

        class OneShotLifecycle:
            def idle_close(self, handle, **kwargs):
                kwargs.pop("writer_identity", None)
                return service.close_if_idle(handle, **kwargs)

        lifecycle = OneShotLifecycle()
        nav = self.nav(lifecycle)
        result = nav.idle_close_edit(
            opened, actor=self.actor, request_id="idle", inactivity_seconds=0.0,
            checkout_root=self.temp.name, now=1000.0, writer_check=lambda: "active",
        )

        self.assertEqual(result["outcome"], "writer_active", result)
        self.assertTrue(result["notification"]["durable"], result)
        self.assertEqual(result["failure_status"], "writer_active")
        self.assertEqual(result["notification"]["actions"], ["wait_for_quiescence", "retry"])
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")
        inventory = self.authoring.session_inventory(self.actor, handles=(opened.handle,))
        self.assertEqual(inventory["sessions"][0]["recovery_status"], "writer_active")

    def test_idle_validation_failure_retains_materialization(self):
        def materializer(checkout, initial_bytes):
            path = Path(self.temp.name) / checkout.session_id
            path.mkdir()
            (path / "document.json").write_bytes(initial_bytes)
            return {"path": str(path), "registered_files": ["document.json"]}

        from herzchen.authoring.sessions import AuthoringSessionService

        service = AuthoringSessionService(self.store, materializer=materializer)
        authoring = DocumentAuthoringHandler(self.store, authoring=service)
        leases = FileWriterLeaseAuthority(
            Path(self.temp.name) / "locks", authority="aci-owner", secret=b"s" * 32,
            writer_identities=("host",), clock=lambda: 1000.0,
        )
        lifecycle = AuthoringLifecycle(
            service, writer_leases=leases, writer_identity="host", clock=lambda: 1000.0,
        )
        nav = ProjectDocumentOperations(
            document_reader=self.nav().document_reader, authoring=authoring,
            context_reader=object(), idle_lifecycle=lifecycle,
        )
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open-idle-invalid",
        )
        nav.autosave_edit(
            opened, {"content": {"text": "Edited"}},
            request_id="autosave-idle-invalid", content_edit_at=0.0,
        )
        checkout_root = Path(opened.handle.checkout_path)
        (checkout_root / "document.json").write_text('{"unknown": "invalid"}', encoding="utf-8")

        result = nav.idle_close_edit(
            opened, actor=self.actor, request_id="idle-invalid",
            inactivity_seconds=0.0, now=1000.0, writer_check=lambda: "quiescent",
        )

        self.assertEqual(result["outcome"], "validation_failed", result)
        self.assertTrue(result["notification"]["durable"], result)
        self.assertTrue((checkout_root / "document.json").exists())
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")

    def test_discard_is_durable_nonpublishing_and_retains_cleanup_state(self):
        nav = self.nav()
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open",
        )
        result = nav.discard_edit(opened, actor=self.actor, request_id="discard")

        self.assertEqual(result["outcome"], "discarded")
        self.assertTrue(result["notification"]["durable"])
        self.assertFalse(result["dat_revision_advanced"])
        self.assertEqual(result["cleanup_status"], "pending")
        self.assertEqual(self.content.read(self.document_ref)["current_revision"]["revision"], "rev-1")
        entry = self.authoring.session_inventory(self.actor)["sessions"][0]
        self.assertEqual(entry["recovery_status"], "discarded")
        self.assertEqual(entry["cleanup_status"], "pending")


if __name__ == "__main__":
    unittest.main()
