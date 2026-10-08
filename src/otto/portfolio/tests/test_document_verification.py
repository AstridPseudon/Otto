"""ACI-07 owner and host-integration verification fixtures.

These tests stay on isolated Store/EDT/DAT fixtures.  They prove the
recoverability, conflict, replay, cleanup, and publication-boundary
properties that can be exercised without claiming that the installed CLI
currently composes the full edit/autosave/finish lifecycle.
"""

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


class DocumentVerificationTests(unittest.TestCase):
    """Controlled ACI-07 crash, race, replay, cleanup, and boundary checks."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aci-07-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store_path = self.root / "isolated.sqlite"
        self.domains = (domain_contribution(), edt_contribution())
        self.store = Store.create(self.store_path, authority="aci-owner")
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

    def nav(self, authoring=None, lifecycle=None):
        ref = self.document_ref

        class VisibleReader:
            def list_documents(self, *args, **kwargs):
                return {"outcome": "listed", "documents": [{"document_ref": ref.to_dict()}]}

            def read_document(self, *args, **kwargs):
                return {"outcome": "read", "content": {"text": "projection"}}

        return ProjectDocumentOperations(
            document_reader=VisibleReader(), authoring=authoring or self.authoring,
            context_reader=object(), idle_lifecycle=lifecycle,
        )

    def reopen_owner(self):
        self.store.close()
        self.store = Store.open(self.store_path, authority="aci-owner", expected_domains=self.domains)
        self.content = ContentCommandHandler(self.store)
        self.authoring = DocumentAuthoringHandler(self.store)
        self.addCleanup(self.store.close)

    def append_external_revision(self):
        revision = ContentRevision(
            self.document_ref, "rev-external", {"text": "External edit"},
            self.actor, parent_revision="rev-1",
        )
        context = TransactionContext(
            self.actor, "external-append", "b" * 64, expected_revision="rev-1",
        )
        return self.content.execute(
            self.content.build_append_revision(context, self.document, revision),
        )

    def test_crash_restart_keeps_one_session_and_requires_explicit_resume(self):
        nav = self.nav()
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open-crash",
        )
        nav.autosave_edit(
            opened, {"content": {"text": "Recovered draft"}},
            request_id="autosave-crash", content_edit_at=12.0,
        )
        session_id = opened.handle.session_id

        self.reopen_owner()
        inventory = self.authoring.session_inventory(self.actor)
        self.assertEqual(inventory["count"], 1)
        entry = inventory["sessions"][0]
        self.assertEqual(entry["session_id"], session_id)
        self.assertEqual(entry["recovery_status"], "recovery_pending")
        self.assertTrue(entry["has_valid_handle"] is False)

        resumed = self.nav().resume_edit(self.document_ref, actor=self.actor, handle=opened.handle)
        self.assertEqual(resumed.open_result.status, "resumed")
        self.assertEqual(resumed.handle.session_id, session_id)

        competing = self.authoring.open_owned(self.document_ref, self.actor, request_id="competing-open")
        self.assertEqual(competing.open_result.status, "occupied")

    def test_simultaneous_canonical_edit_conflicts_without_overwrite(self):
        opened = self.nav().open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open-conflict",
        )
        self.nav().autosave_edit(
            opened, {"content": {"text": "Retained local draft"}},
            request_id="autosave-conflict", content_edit_at=20.0,
        )
        self.append_external_revision()

        result = self.nav().finish_edit(
            opened, {"content": {"text": "Retained local draft"}},
            request_id="finish-conflict",
        )

        self.assertEqual(result["outcome"], "conflict", result)
        self.assertEqual(result["failure_status"], "conflict")
        self.assertEqual(result["publication"]["status"], "not_published")
        self.assertTrue(result["notification"]["durable"])
        self.assertEqual(
            self.content.read(self.document_ref)["current_revision"]["revision"],
            "rev-external",
        )
        inventory = self.authoring.session_inventory(self.actor, handles=(opened.handle,))
        self.assertEqual(inventory["sessions"][0]["failure_status"], "conflict")

    def test_replayed_finish_receipt_is_idempotent_and_remains_committed(self):
        nav = self.nav()
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open-replay",
        )
        draft = {"content": {"text": "Exactly once"}}
        first = nav.finish_edit(opened, draft, request_id="finish-replay")
        head = first["revision_ref"]
        second = nav.finish_edit(opened, draft, request_id="finish-replay")

        self.assertEqual(first["outcome"], "applied")
        self.assertIn(second["outcome"], {"replayed", "already_finished"}, second)
        self.assertEqual(second["finish_status"], "replayed")
        self.assertEqual(second["publication"]["status"], "committed")
        self.assertEqual(second["revision_ref"], head)
        self.assertEqual(second["receipt"], first["receipt"])
        self.assertEqual(
            ResourceRef.from_dict(self.content.read(self.document_ref)["current_revision"]),
            ResourceRef.from_dict(head),
        )

    def test_exact_cleanup_fails_closed_on_an_unregistered_file(self):
        def materializer(checkout, initial_bytes):
            path = self.root / checkout.session_id
            path.mkdir()
            (path / "document.json").write_bytes(initial_bytes)
            (path / "unregistered.txt").write_text("keep me", encoding="utf-8")
            return {"path": str(path), "registered_files": ["document.json"]}

        service = AuthoringSessionService(self.store, materializer=materializer)
        authoring = DocumentAuthoringHandler(self.store, authoring=service)
        leases = FileWriterLeaseAuthority(
            self.root / "locks", authority="aci-owner", secret=b"s" * 32,
            writer_identities=("host",), clock=lambda: 1_000.0,
        )
        lifecycle = AuthoringLifecycle(
            service, writer_leases=leases, writer_identity="host", clock=lambda: 1_000.0,
        )
        nav = self.nav(authoring=authoring, lifecycle=lifecycle)
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open-cleanup",
        )
        nav.autosave_edit(
            opened, {"content": {"text": "Cleanup draft"}},
            request_id="autosave-cleanup", content_edit_at=0.0,
        )
        checkout_root = Path(opened.handle.checkout_path)
        (checkout_root / "document.json").write_text(
            '{"content": {"text": "Cleanup draft"}}', encoding="utf-8",
        )
        result = nav.idle_close_edit(
            opened, actor=self.actor, request_id="idle-cleanup",
            inactivity_seconds=0.0, now=1_000.0,
            writer_check=lambda: "quiescent",
        )

        self.assertEqual(result["outcome"], "recovery_pending", result)
        self.assertFalse(result["durable_checked_in"])
        self.assertFalse(result["cleanup_pending"])
        self.assertTrue((checkout_root / "document.json").exists())
        self.assertTrue((checkout_root / "unregistered.txt").exists())
        self.assertEqual(
            self.content.read(self.document_ref)["current_revision"]["revision"],
            "rev-1",
        )

    def test_check_in_publication_does_not_adopt_direction_or_invocation_context(self):
        nav = self.nav()
        opened = nav.open_edit(
            ResourceRef("aci-owner", "work.project", "visible"), self.document_ref,
            actor=self.actor, request_id="open-boundary",
        )
        result = nav.finish_edit(
            opened, {"content": {"text": "Published only"}},
            request_id="finish-boundary",
        )

        publication = result["publication"]
        self.assertEqual(publication["status"], "committed")
        self.assertEqual(publication["direction_adoption"], "not_performed")
        self.assertEqual(publication["assignment_adoption"], "not_performed")
        self.assertEqual(publication["resource_adoption"], "not_performed")
        self.assertEqual(publication["invocation_context"], "unchanged")
        self.assertEqual(self.content.read(self.document_ref)["document"]["role"], "notes")


if __name__ == "__main__":
    unittest.main()
