"""ACI-01 host admission proof over disposable canonical EDT/DAT owners.

No installed owner, controller state, provider or operational Store is used.
"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import domain_contribution as edt_contribution
from herzchen.authoring.sessions import AuthoringSessionService, InvalidSessionError
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler, ScopeAuthorizationError
from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef, TransactionContext
from herzchen.kernel.store import Store
from otto.portfolio.document_navigation import ProjectDocumentOperations


class DocumentEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aci-01-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "isolated.sqlite"
        self.domains = (domain_contribution(), edt_contribution())
        self.store = Store.create(self.path, authority="aci-owner")
        self.store.register_domain_handler(self.domains)
        self.actor = AuthenticatedActor("aci-owner", "owner", "fixture-credential")
        self.compose()
        self.addCleanup(lambda: self.store.close())

    def compose(self):
        self.content = ContentCommandHandler(self.store)
        self.authoring = DocumentAuthoringHandler(self.store)

    def restart(self):
        self.store.close()
        self.store = Store.open(self.path, authority="aci-owner", expected_domains=self.domains)
        self.compose()

    def document(self, ident="owned", **options):
        ref = ResourceRef("aci-owner", "dat.content.document", ident)
        doc = ContentDocument(ref, "notes", options.pop("visibility", "shared"), "write", "owner", **options)
        revision = ContentRevision(ref, "rev-1", {"text": "Opening bytes"}, self.actor, initial=True)
        self.content.execute(self.content.build_create_document(
            TransactionContext(self.actor, "create:" + ident, "a" * 64), doc, revision))
        return doc

    def retained(self, doc):
        # Trusted fixture import; no local revision is synthesized for imports.
        self.store.put_identity(doc.ref, {"record_type": "dat.content.document", "document": doc}, version=1)

    def evidence(self, receipt):
        events = self.store.consumer().list_events()
        return next(event for event in events if event.event_id in receipt.event_ids)

    def test_owned_projection_current_capability_and_existing_finish(self):
        doc = self.document()
        opened = self.authoring.open_owned(doc.ref, self.actor, request_id="open")
        self.assertEqual(opened.open_result.status, "opened")
        self.assertTrue(opened.projection.eligible)
        self.assertEqual(opened.projection.scope, ResourceRef("aci-owner", "document", doc.ref.id))
        self.assertEqual(opened.projection.actor, self.actor)
        self.assertEqual(opened.projection.base_revision, "rev-1")
        self.assertEqual(opened.projection.import_mode, "owned")
        self.assertFalse(opened.projection.read_only)
        counts = self.store.consumer().snapshot_counts()
        status = self.authoring.edit_status(opened, self.actor)
        self.assertEqual(status["handle"], opened.handle)
        self.assertEqual(status["abandoned_handle_authority"], "explicit_trusted_owner_recovery_required")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        finished = self.authoring.finish(opened, request_id="finish", draft={"content": {"text": "Saved"}})
        self.assertEqual(finished.finish.status, "finished")
        self.assertEqual(self.content.read(doc.ref)["current_revision"]["revision"], finished.applied.revision.revision)
        self.assertNotEqual(finished.applied.revision.revision, "rev-1")
        self.assertEqual(finished.applied.revision.parent_revision, "rev-1")
        with self.assertRaises(InvalidSessionError):
            self.authoring.edit_status(opened, self.actor)

    def test_imported_pinned_readonly_foreign_and_unsupported_refusals_survive_restart(self):
        doc = self.document()
        cases = []
        for mode in ("imported", "pinned"):
            ref = ResourceRef("aci-owner", "dat.content.document", mode)
            imported = replace(doc, ref=ref, import_mode=mode, writable=False, access_mode="read",
                               source_ref=ResourceRef("foreign", "dat.content.document", "source", "rev-1"))
            self.retained(imported)
            cases.append((ref, mode + "_document"))
        readonly = replace(doc, ref=ResourceRef("aci-owner", "dat.content.document", "readonly"),
                           writable=False, access_mode="read")
        self.retained(readonly)
        cases.extend(((readonly.ref, "read_only_document"),
                      (replace(doc.ref, revision="rev-1"), "pinned_document"),
                      (ResourceRef("foreign", "dat.content.document", "outside"), "foreign_document"),
                      (ResourceRef("aci-owner", "unsupported", "missing"), "unsupported_document")))
        receipts = []
        for index, (ref, reason) in enumerate(cases):
            result = self.authoring.open_owned(ref, self.actor, request_id="refuse:" + str(index))
            self.assertEqual(result.open_result.status, "ineligible")
            self.assertIsNone(result.open_result.handle)
            self.assertEqual(result.projection.reason, reason)
            event = self.evidence(result.refusal_receipt)
            self.assertEqual(event.effects["reason"], reason)
            self.assertEqual(event.effects["target"], ref.to_dict())
            receipts.append(result.refusal_receipt)
        self.assertEqual(self.content.read(doc.ref)["current_revision"]["revision"], "rev-1")
        self.restart()
        for index, (ref, reason) in enumerate(cases):
            result = self.authoring.open_owned(ref, self.actor, request_id="refuse:" + str(index))
            self.assertEqual(result.refusal_receipt, receipts[index])
            self.assertEqual(self.evidence(result.refusal_receipt).effects["reason"], reason)
        self.assertEqual(self.authoring.open_owned(doc.ref, self.actor, request_id="valid").open_result.status, "opened")

    def test_scope_refusal_preserves_an_existing_checkout_and_has_exact_replay(self):
        scope = ResourceRef("aci-owner", "work.project", "project")
        doc = self.document(visibility="private", authoring_scope=scope)
        opened = self.authoring.open_owned(doc.ref, self.actor, request_id="open")
        self.assertEqual(opened.scope, scope)
        before = self.authoring.edit_status(opened, self.actor)["checkout"]
        refused = self.authoring.open_owned(doc.ref, self.actor, request_id="wrong-scope",
                                            parent_scope=ResourceRef("aci-owner", "work.project", "other"))
        self.assertEqual(refused.projection.reason, "scope_ineligible")
        self.assertEqual(self.authoring.edit_status(opened, self.actor)["checkout"], before)
        with self.assertRaises(ReplayConflictError):
            self.authoring.refuse_edit(doc.ref, self.actor, request_id="wrong-scope", reason="other")
        # The same capability remains resumable across service restart.
        self.restart()
        self.assertEqual(self.authoring.edit_status(opened, self.actor)["checkout"], before)

    def test_parent_scope_must_be_unpinned_and_local(self):
        for index, scope in enumerate((ResourceRef("foreign", "work.project", "external"),
                                       ResourceRef("aci-owner", "work.project", "pinned", "rev-1"))):
            doc = self.document(str(index), visibility="private", authoring_scope=scope)
            result = self.authoring.open_owned(doc.ref, self.actor, request_id="scope:" + str(index))
            self.assertEqual(result.projection.reason, "scope_ineligible")
            self.assertIsNone(result.open_result.handle)

    def test_foreign_actor_and_stale_or_forged_capabilities_cannot_resume(self):
        doc = self.document()
        opened = self.authoring.open_owned(doc.ref, self.actor, request_id="open")
        for field in ("token", "fence", "session_id"):
            bad = replace(opened, open_result=replace(opened.open_result, handle=replace(opened.handle, **{field: "forged"})))
            with self.assertRaises(InvalidSessionError):
                self.authoring.edit_status(bad, self.actor)
        other = replace(self.actor, actor="another")
        with self.assertRaises(ScopeAuthorizationError):
            self.authoring.edit_status(opened, other)
        counts = self.store.consumer().snapshot_counts()
        with self.assertRaises(ScopeAuthorizationError):
            self.authoring.open_owned(doc.ref, replace(self.actor, authority="foreign"), request_id="foreign-actor")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        busy = self.authoring.open_owned(doc.ref, other, request_id="busy")
        self.assertEqual(busy.open_result.status, "occupied")
        self.assertIsNone(busy.open_result.handle)

    def test_caller_metadata_cannot_reclassify_a_readonly_document(self):
        readonly = ContentDocument(ResourceRef("aci-owner", "dat.content.document", "readonly"),
                                   "notes", "shared", "read", "owner", writable=False)
        self.retained(readonly)
        doc = replace(readonly, writable=True, access_mode="write")
        with self.assertRaises(ScopeAuthorizationError):
            self.authoring.materialise(doc, self.actor, request_id="spoofed")
        with self.assertRaises(ScopeAuthorizationError):
            self.authoring.materialise(replace(doc.ref, revision="rev-1"), self.actor, request_id="pinned")

    def test_physical_materialization_follows_durable_reservation(self):
        doc = self.document()
        observed = []

        def materializer(checkout, initial_bytes):
            # Inspect only the isolated fixture owner's transaction state;
            # never open a competing writer for even this disposable Store.
            self.assertFalse(self.store.connection.in_transaction)
            read = sessions.read(checkout.target_scope, self.actor, parent_scope=checkout.target_scope)
            observed.append(read.checkout.session_id)
            raise RuntimeError("fixture physical materialization failed")

        sessions = AuthoringSessionService(self.store, materializer=materializer)
        handler = DocumentAuthoringHandler(self.store, authoring=sessions)
        result = handler.open_owned(doc.ref, self.actor, request_id="physical-open")
        self.assertEqual(len(observed), 1)
        self.assertEqual(result.open_result.status, "saved_project_edit_not_opened")
        self.assertIsNone(result.open_result.handle)
        self.assertEqual(self.content.read(doc.ref)["current_revision"]["revision"], "rev-1")
        self.restart()
        self.assertEqual(self.authoring.open_owned(doc.ref, self.actor, request_id="resume-after-failure").open_result.status,
                         "opened")

    def test_host_navigation_keeps_visibility_refusals_durable_and_uses_owner_base(self):
        doc = self.document()
        authoring = self.authoring
        actor = self.actor

        class VisibleReader:
            def list_documents(self, *args, **kwargs):
                return {"outcome": "listed", "documents": [{"document_ref": doc.ref.to_dict()}]}

            def read_document(self, *args, **kwargs):
                # Visibility authorizes a read, but its observed bytes are not
                # an authoritative new base for the subsequent edit session.
                return {"outcome": "read", "content": {"text": "Stale projection"}}

        nav = ProjectDocumentOperations(document_reader=VisibleReader(), authoring=authoring, context_reader=object())
        project = ResourceRef("aci-owner", "work.project", "visible")
        opened = nav.open_edit(project, doc.ref, actor=actor, request_id="host-open")
        self.assertEqual(authoring.authoring.read_snapshot(opened.open_result.checkout.draft_snapshot_ref),
                         b'{"text":"Opening bytes"}')
        status = nav.edit_status(opened, actor=actor)
        self.assertEqual(status["handle"]["base_revision"], "rev-1")
        refused = nav.open_edit(project, replace(doc.ref, revision="rev-1"), actor=actor, request_id="host-pin")
        self.assertEqual(refused["reason"], "pinned_document")
        missing = nav.open_edit(project, ResourceRef("aci-owner", "dat.content.document", "invisible"),
                                actor=actor, request_id="host-invisible")
        self.assertEqual(missing["reason"], "scope_ineligible")
        self.assertNotIn("projection", missing)
        self.assertEqual(self.store.get_receipt("host-invisible").to_dict(), missing["receipt"])


if __name__ == "__main__":
    unittest.main()
