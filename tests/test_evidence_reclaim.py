import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from herzchen.evidence.model import EvidencePackError, PublicationInterrupted, load_evidence_pack
from herzchen.content.model import domain_contribution as content_domain_contribution
from herzchen.kernel import Store
from herzchen.packs.authoring import read_managed_pack


def _current_pack():
    root = Path(__file__).parents[1] / "src" / "herzchen" / "packs" / "evidence_resource_pack"
    paths = {
        "schemas/evidence.json": "evidence_schema",
        "policies/provenance.json": "evidence_policy",
        "presets/submit.json": "evidence_preset",
        "presets/version.json": "evidence_preset",
        "presets/list.json": "evidence_preset",
        "presets/read.json": "evidence_preset",
        "presets/reclaim-preview.json": "evidence_preset",
        "presets/reclaim-apply.json": "evidence_preset",
        "skill/SKILL.md": "skill",
        "templates/evidence.json": "evidence_template",
    }
    manifest_digest = hashlib.sha256((root / "pack.yaml").read_bytes()).hexdigest()
    handles = tuple(
        SimpleNamespace(path=path, kind=kind, resolved=root / path,
                        sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
        for path, kind in paths.items()
    )
    discovered = SimpleNamespace(
        id="evidence", source_kind="managed", source_revision="a" * 40,
        source_tree_sha256="b" * 64, source_manifest_sha256=manifest_digest,
        source_inventory_identity="c" * 64, pack_dir=root,
        entry=SimpleNamespace(
            manifest=SimpleNamespace(sha256=manifest_digest),
            definition=SimpleNamespace(
                version="1.1.0",
                to_dict=lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2},
            ),
            resource_handles=handles,
        ),
    )
    managed = read_managed_pack(
        "evidence", project_root=root.parents[3],
        discoverer=lambda *, project_root: (discovered,),
        loader=lambda path, **kwargs: SimpleNamespace(id="evidence", schema_version=2),
    )
    return load_evidence_pack(managed_pack=managed)


class EvidenceReclaimTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = Store.create(root / "owner.sqlite", authority="owner")
        self.store.register_domain_handler((content_domain_contribution(),))
        register_evidence(self.store)
        self.actor = AuthenticatedActor("owner", "retention", "credential")
        self.project = ResourceRef("owner", "work.project", "project")
        self.other_project = ResourceRef("owner", "work.project", "other-project")
        self.store.put_identity(self.project, {"record_type": "work.project", "title": "fixture"}, version=0)
        self.store.put_identity(self.other_project, {"record_type": "work.project", "title": "other"}, version=0)
        self.handler = EvidenceCommandHandler(
            self.store, root / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources],
            resolve_dependencies=lambda exact, project: {"complete": True, "holds": ()},
        )

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def submit(self, value=b"reclaimable evidence", key="submit"):
        return self.handler.submit(value, actor=self.actor, logical_request_key=key,
                                   project_ref=self.project, original_creator="creator")

    def test_preview_apply_removes_managed_file_and_retains_tombstone(self):
        submitted = self.submit(b"managed bytes", "managed")
        status = self.handler.status(submitted["revision_ref"], actor=self.actor)
        path = Path(self.directory.name) / "managed" / status["manifest"]["storage"]["location"]
        self.assertTrue(path.is_file())

        preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-managed", cutoff="9999-01-01T00:00:00Z"
        )
        self.assertEqual(preview["eligible_unique_managed_bytes"], len(b"managed bytes"))
        applied = self.handler.reclaim_apply(
            preview["selection_ref"], actor=self.actor, logical_request_key="apply-managed", project_ref=self.project
        )
        self.assertEqual(applied["managed_bytes_removed"], len(b"managed bytes"))
        self.assertFalse(path.exists())
        after = self.handler.status(submitted["revision_ref"], actor=self.actor)
        self.assertEqual(after["availability"], "purged")
        self.assertTrue(after["manifest"]["tombstone"]["decision_history_preserved"])
        self.assertEqual(self.handler.reclaim_apply(
            preview["selection_ref"], actor=self.actor, logical_request_key="apply-managed", project_ref=self.project
        )["outcome"], "replayed")

    def test_preview_includes_eligible_historical_versions(self):
        first = self.submit(b"historical-one", "historical-one")
        self.handler.version(
            first["document_ref"], b"historical-two", actor=self.actor, logical_request_key="historical-two",
            project_ref=self.project, original_creator="creator",
        )
        preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-history", cutoff="9999-01-01T00:00:00Z"
        )
        self.assertEqual({item["reference"].revision for item in preview["items"]}, {"rev-1", "rev-2"})

    def test_stale_shared_and_dependency_holds_never_remove_files(self):
        submitted = self.submit(b"shared", "shared")
        self.handler.cite_evidence(
            submitted["revision_ref"], project_ref=self.other_project, alias="shared.txt",
            actor=self.actor, logical_request_key="cite-shared",
        )
        preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-shared", cutoff="9999-01-01T00:00:00Z"
        )
        held = self.handler.reclaim_apply(
            preview["selection_ref"], actor=self.actor, logical_request_key="apply-shared", project_ref=self.project
        )
        self.assertIn("shared-reference", [item["reason"] for item in held["held"]])
        self.assertTrue(self.handler.status(submitted["revision_ref"], actor=self.actor)["availability"] == "admitted")

        inflight = self.submit(b"in-flight", "in-flight")
        inflight_preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-inflight", cutoff="9999-01-01T00:00:00Z",
            dependency_state={inflight["revision_ref"].id: "in-flight"},
        )
        inflight_apply = self.handler.reclaim_apply(
            inflight_preview["selection_ref"], actor=self.actor, logical_request_key="apply-inflight",
            project_ref=self.project, dependency_state={inflight["revision_ref"].id: "in-flight"},
        )
        reasons = [item["reason"] for item in inflight_apply["held"]]
        self.assertIn("in-flight-recovery", reasons)

        unknown = self.submit(b"unknown", "unknown")
        unknown_preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-unknown", cutoff="9999-01-01T00:00:00Z",
            dependency_state={unknown["revision_ref"].id: "unknown"},
        )
        unknown_apply = self.handler.reclaim_apply(
            unknown_preview["selection_ref"], actor=self.actor, logical_request_key="apply-unknown",
            project_ref=self.project, dependency_state={unknown["revision_ref"].id: "unknown"},
        )
        self.assertIn("dependency-unknown", [item["reason"] for item in unknown_apply["held"]])

    def test_changed_apply_input_is_rejected_before_a_second_file_effect(self):
        submitted = self.submit(b"replay fence", "replay-fence")
        preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-fence", cutoff="9999-01-01T00:00:00Z"
        )
        self.handler.reclaim_apply(
            preview["selection_ref"], actor=self.actor, logical_request_key="apply-fence",
            project_ref=self.project, dependency_state={submitted["revision_ref"].id: "unknown"},
        )
        with self.assertRaises(ReplayConflictError):
            self.handler.reclaim_apply(
                preview["selection_ref"], actor=self.actor, logical_request_key="apply-fence",
                project_ref=self.project,
            )
        status = self.handler.status(submitted["revision_ref"], actor=self.actor)
        path = Path(self.directory.name) / "managed" / status["manifest"]["storage"]["location"]
        self.assertTrue(path.is_file())

    def test_interrupted_delete_reconciles_absence_and_disable_preserves_data(self):
        submitted = self.submit(b"interruptible", "interruptible")
        preview = self.handler.reclaim_preview(
            self.project, actor=self.actor, logical_request_key="preview-interrupt", cutoff="9999-01-01T00:00:00Z"
        )
        with self.assertRaises(PublicationInterrupted):
            self.handler.reclaim_apply(
                preview["selection_ref"], actor=self.actor, logical_request_key="apply-interrupt",
                project_ref=self.project, interrupt_at="after-delete",
            )
        reconciled = self.handler.reclaim_apply(
            preview["selection_ref"], actor=self.actor, logical_request_key="apply-interrupt", project_ref=self.project
        )
        self.assertEqual(reconciled["managed_bytes_removed"], 0)
        self.assertEqual(reconciled["tombstones"][0]["reason"], "reconciled-missing")
        self.assertEqual(self.handler.status(submitted["revision_ref"], actor=self.actor)["availability"], "purged")

        self.handler.disable_workflow()
        self.assertEqual(self.handler.status(submitted["revision_ref"], actor=self.actor)["availability"], "purged")
        with self.assertRaises(EvidencePackError):
            self.submit(b"must-not-admit", "disabled")


    def preview(self, key="p", **kwargs):
        return self.handler.reclaim_preview(self.project, actor=self.actor,
            logical_request_key=key, cutoff="9999-01-01T00:00:00Z", **kwargs)

    def test_optional_dependency_omission_cannot_clear_retained_hold(self):
        item = self.submit(b"recovery input", "recovery")
        preview = self.preview(dependency_state={item["revision_ref"].id: "in-flight"})
        applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(applied["managed_bytes_removed"], 0)
        self.assertIn("in-flight-recovery", [x["reason"] for x in applied["held"]])
        self.assertEqual(self.handler.status(item["revision_ref"], actor=self.actor)["availability"], "admitted")

    def test_missing_authoritative_dependency_resolver_fails_closed(self):
        self.submit()
        handler = EvidenceCommandHandler(self.store, Path(self.directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources])
        preview = handler.reclaim_preview(self.project, actor=self.actor, logical_request_key="p", cutoff="9999Z")
        self.assertEqual(preview["items"][0]["hold"], "dependency-unknown")
        applied = handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a",
            dependency_state={preview["items"][0]["reference"].id: "resolved"})
        self.assertEqual(applied["managed_bytes_removed"], 0)

    def test_read_sharing_does_not_grant_purge_authority_or_preview_disclosure(self):
        from herzchen.evidence.model import EvidenceAccessDeniedError
        item = self.submit()
        handler = EvidenceCommandHandler(self.store, Path(self.directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources], authorize=lambda *args: True,
            resolve_dependencies=lambda *args: {"complete": True, "holds": ()})
        reader = AuthenticatedActor("foreign-owner", "reader", "reader-credential")
        self.assertEqual(handler.status(item["revision_ref"], actor=reader)["availability"], "admitted")
        preview = self.preview()
        with self.assertRaises(EvidenceAccessDeniedError):
            handler.reclaim_apply(preview["selection_ref"], actor=reader, logical_request_key="foreign-apply")
        foreign_preview = handler.reclaim_preview(self.project, actor=reader, logical_request_key="foreign-preview", cutoff="9999Z")
        self.assertEqual(foreign_preview["items"], [])
        self.assertIsNone(self.store.get_receipt("foreign-apply"))
        self.assertEqual(handler.status(item["revision_ref"], actor=self.actor)["availability"], "admitted")

    def test_explicit_lifecycle_authorization_is_distinct_from_read_authorization(self):
        self.submit()
        actor = AuthenticatedActor("owner", "delegated-lifecycle", "trusted-credential")
        handler = EvidenceCommandHandler(self.store, Path(self.directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources], authorize=lambda *args: True,
            authorize_lifecycle=lambda document, caller, project, operation: caller == actor,
            resolve_dependencies=lambda *args: {"complete": True, "holds": ()})
        preview = handler.reclaim_preview(self.project, actor=actor, logical_request_key="delegated-p", cutoff="9999Z")
        applied = handler.reclaim_apply(preview["selection_ref"], actor=actor, logical_request_key="delegated-a")
        self.assertGreater(applied["managed_bytes_removed"], 0)

    def test_new_reference_after_preview_is_held_at_intent_boundary(self):
        item = self.submit(b"race protection")
        preview = self.preview()
        self.handler.cite_evidence(item["revision_ref"], project_ref=self.other_project, alias="raced",
            actor=self.actor, logical_request_key="raced-link")
        applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(applied["managed_bytes_removed"], 0)
        self.assertEqual(applied["held"][0]["reason"], "shared-reference")

    def test_pending_intent_blocks_all_content_link_ingress_and_payload_consumers(self):
        from herzchen.content.commands import ContentCommandHandler
        from herzchen.content.model import DocumentAssociation
        from herzchen.contracts import ReferenceBinding
        from herzchen.content.reads import document_metadata, reclaim_intent_ref
        item = self.submit(b"pending input")
        preview = self.preview()
        with self.assertRaises(PublicationInterrupted):
            self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a", interrupt_at="before-delete")
        self.assertIsNotNone(self.store.get_identity(reclaim_intent_ref(item["revision_ref"])))
        self.assertEqual(document_metadata(self.store.consumer(), item["revision_ref"], actor=self.actor)["availability"], "pending-reclaim")
        self.assertEqual(self.handler.read_evidence(item["revision_ref"], actor=self.actor)["bytes"], b"")
        content = ContentCommandHandler(self.store)
        for mode in ("pinned", "current"):
            ref = item["revision_ref"] if mode == "pinned" else item["document_ref"]
            association = DocumentAssociation(self.other_project, "evidence", "new-" + mode, ReferenceBinding(ref, mode))
            from herzchen.contracts import TransactionContext
            target = ResourceRef("owner", "document-association", association.identity)
            # The handler's public builder computes the ordinary envelope;
            # admission still passes through the common content domain.
            context = TransactionContext(self.actor, "link-" + mode, "0" * 64, expected_version=0)
            envelope = content.build_link(context, association)
            with self.assertRaises(PermissionError):
                content.execute(envelope)
            self.assertIsNone(self.store.get_receipt("link-" + mode))
        applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(applied["managed_bytes_removed"], len(b"pending input"))

    def test_changed_pending_inputs_cannot_take_over_original_intent(self):
        item = self.submit()
        preview = self.preview()
        with self.assertRaises(PublicationInterrupted):
            self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a", interrupt_at="before-delete")
        with self.assertRaises(ReplayConflictError):
            self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a",
                dependency_state={item["revision_ref"].id: "unknown"})
        self.assertIsNone(self.store.get_receipt("a"))
        self.assertGreater(self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")["managed_bytes_removed"], 0)

    def test_preview_work_is_bounded_before_selection_and_apply_does_not_discover(self):
        from unittest.mock import patch
        for i in range(12):
            self.submit(("payload-" + str(i)).encode(), "submit-" + str(i))
        from herzchen.evidence.commands import _EvidenceCommandHandlerEngine
        original = _EvidenceCommandHandlerEngine.status
        seen = []
        def counted(engine, ref, **kwargs):
            seen.append(ref)
            return original(engine, ref, **kwargs)
        with patch.object(_EvidenceCommandHandlerEngine, "status", counted):
            preview = self.preview(limit=1)
            for i in range(10):
                if preview["items"]:
                    break
                preview = self.preview("first-" + str(i), limit=1, cursor=preview["next_cursor"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(preview["items"]), 1)
        self.assertEqual(preview["io_work"]["identities_examined"], 1)
        self.assertIsNotNone(preview["next_cursor"])
        with patch.object(_EvidenceCommandHandlerEngine, "_reclaim_candidates", side_effect=AssertionError("global discovery")):
            applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertGreater(applied["managed_bytes_removed"], 0)
        self.assertEqual(applied["io_work"]["global_discovery_pages"], 0)
        refs = set()
        cursor = ""
        for i in range(40):
            page = self.preview("page-" + str(i), limit=1, cursor=cursor)
            self.assertLessEqual(page["io_work"]["identities_examined"], 1)
            refs.update(x["reference"] for x in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual(len(refs), 12)


    def test_concurrent_link_waits_for_intent_and_cannot_race_delete(self):
        import threading
        from unittest.mock import patch
        from herzchen.evidence.commands import _EvidenceCommandHandlerEngine
        item = self.submit(b"serialized deletion")
        preview = self.preview()
        entered, finished = threading.Event(), threading.Event()
        outcomes, threads = [], []
        original = _EvidenceCommandHandlerEngine._persist_lifecycle
        def link():
            entered.set()
            try:
                self.handler.cite_evidence(item["revision_ref"], project_ref=self.other_project,
                    alias="concurrent", actor=self.actor, logical_request_key="concurrent-link")
                outcomes.append("admitted")
            except PermissionError:
                outcomes.append("denied")
            finally:
                finished.set()
        def boundary(engine, **kwargs):
            if kwargs["record"].get("record_type") == "dat.evidence.reclaim.intent":
                thread = threading.Thread(target=link)
                threads.append(thread)
                thread.start()
                self.assertTrue(entered.wait(2))
                self.assertFalse(finished.wait(.05))
            return original(engine, **kwargs)
        with patch.object(_EvidenceCommandHandlerEngine, "_persist_lifecycle", boundary):
            applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, ["denied"])
        self.assertEqual(applied["managed_bytes_removed"], len(b"serialized deletion"))
        self.assertIsNone(self.store.get_receipt("concurrent-link"))

    def test_intent_admission_failure_precedes_any_file_effect(self):
        from unittest.mock import patch
        item = self.submit(b"must remain")
        preview = self.preview()
        original = Store.mutate
        def rejected(store, envelope, **kwargs):
            if envelope.payload.get("record_type") == "dat.evidence.reclaim.intent":
                raise RuntimeError("fixture owner rejected deletion admission")
            return original(store, envelope, **kwargs)
        with patch.object(Store, "mutate", rejected):
            with self.assertRaisesRegex(RuntimeError, "rejected deletion admission"):
                self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(self.handler.read_evidence(item["revision_ref"], actor=self.actor)["bytes"], b"must remain")
        self.assertIsNone(self.store.get_receipt("a"))

    def test_final_receipt_failure_leaves_durable_fence_and_same_key_reconciles(self):
        from unittest.mock import patch
        from herzchen.content.reads import reclaim_intent_ref
        item = self.submit(b"durable removal")
        preview = self.preview()
        original = Store.mutate
        def rejected(store, envelope, **kwargs):
            if envelope.payload.get("record_type") == "dat.evidence.reclaim.apply":
                raise RuntimeError("fixture final commit rejected")
            return original(store, envelope, **kwargs)
        with patch.object(Store, "mutate", rejected):
            with self.assertRaisesRegex(RuntimeError, "final commit rejected"):
                self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertIsNotNone(self.store.get_identity(reclaim_intent_ref(item["revision_ref"])))
        self.assertEqual(self.handler.status(item["revision_ref"], actor=self.actor)["availability"], "pending-reclaim")
        self.assertIsNone(self.store.get_receipt("a"))
        recovered = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(recovered["managed_bytes_removed"], 0)
        self.assertEqual(recovered["tombstones"][0]["reason"], "reconciled-missing")
        self.assertEqual(self.handler.status(item["revision_ref"], actor=self.actor)["availability"], "purged")

    def test_missing_file_without_original_intent_is_not_attributed_to_reclaim(self):
        item = self.submit()
        preview = self.preview()
        status = self.handler.status(item["revision_ref"], actor=self.actor)
        (Path(self.directory.name) / "managed" / status["manifest"]["storage"]["location"]).unlink()
        applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(applied["tombstones"], [])
        self.assertEqual(applied["held"][0]["reason"], "unavailable")
        self.assertEqual(self.handler.status(item["revision_ref"], actor=self.actor)["availability"], "missing")

    def test_reference_saturation_is_unknown_and_never_exhausts_history(self):
        item = self.submit()
        for i in range(100):
            self.handler.cite_evidence(item["revision_ref"], project_ref=self.project, alias="same-" + str(i),
                actor=self.actor, logical_request_key="link-" + str(i))
        preview = self.preview()
        self.assertEqual(preview["items"][0]["hold"], "dependency-unknown")
        applied = self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a")
        self.assertEqual(applied["managed_bytes_removed"], 0)

    def test_filtered_owner_page_is_bounded_and_rejects_ambiguous_predicates(self):
        for i in range(4):
            self.submit(b"page", "s" + str(i))
        page = self.store.consumer().read_identity_page(kind="dat.content.revision", limit=1,
            payload_matches={("record_type",): "dat.content.metadata", ("representation",): "managed"})
        self.assertEqual(page["examined"], 1)
        self.assertEqual(len(page["records"]), 0)
        self.assertIsNotNone(page["next_cursor"])
        page = self.store.consumer().read_identity_page(kind="dat.content.revision", limit=1, after=page["next_cursor"],
            payload_matches={("record_type",): "dat.content.metadata", ("representation",): "managed"})
        self.assertEqual(page["examined"], 1)
        self.assertEqual(page["records"][0].payload["record_type"], "dat.content.metadata")
        for predicate in ({("bad.path",): "x"}, {("record_type",): 1}):
            with self.assertRaises(ValueError):
                self.store.consumer().read_identity_page(kind="dat.content.revision", payload_matches=predicate)
        with self.assertRaises(Exception):
            self.preview(cursor="1")


    def test_pending_intent_also_guards_context_packet_admission(self):
        from herzchen.content.commands import ContentCommandHandler
        from herzchen.content.model import ContentDocument, ContentRevision
        from herzchen.contracts import TransactionContext
        item = self.submit(b"packet input")
        preview = self.preview()
        with self.assertRaises(PublicationInterrupted):
            self.handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="a", interrupt_at="before-delete")
        ref = ResourceRef("owner", "dat.context.packet", "pending-packet")
        document = ContentDocument(ref, "context-packet", "private", "read", self.actor.actor)
        revision = ContentRevision(ref, "packet-1", {"inputs": [{"resolved_ref": item["revision_ref"], "consumed": True}]}, self.actor, initial=True)
        content = ContentCommandHandler(self.store)
        context = TransactionContext(self.actor, "packet-admit", "0" * 64, expected_version=0)
        with self.assertRaises(PermissionError):
            content.execute(content.build_create_document(context, document, revision))
        self.assertIsNone(self.store.get_receipt("packet-admit"))


    def test_rejected_large_history_is_not_json_parsed_before_page_limit(self):
        import json
        queries = []
        self.store.put_identity(ResourceRef("owner", "dat.content.revision", "000-large-legacy"),
            {"record_type": "dat.content.revision", "content": "x" * 1_000_000}, version=0)
        self.submit()
        self.store.connection.set_trace_callback(queries.append)
        try:
            page = self.preview(limit=1)
        finally:
            self.store.connection.set_trace_callback(None)
        self.assertEqual(page["items"], [])
        self.assertEqual(page["io_work"]["identities_examined"], 1)
        self.assertEqual(page["io_work"]["discovery_metadata_bytes_parsed"], 0)
        self.assertEqual(page["io_work"]["oversize_held"], 1)
        self.assertIsNotNone(page["next_cursor"])
        self.assertFalse(any("json_extract" in q or "json_type" in q for q in queries))

    def test_dependency_change_after_preview_is_revalidated_and_unknown_fails_closed(self):
        item = self.submit()
        state = {"complete": True, "holds": ()}
        handler = EvidenceCommandHandler(self.store, Path(self.directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources],
            resolve_dependencies=lambda *args: state)
        preview = handler.reclaim_preview(self.project, actor=self.actor, logical_request_key="current-p", cutoff="9999Z")
        state.update(complete=False, holds=())
        applied = handler.reclaim_apply(preview["selection_ref"], actor=self.actor, logical_request_key="current-a")
        self.assertEqual(applied["managed_bytes_removed"], 0)
        self.assertEqual(applied["held"][0]["reason"], "dependency-unknown")
        self.assertEqual(handler.status(item["revision_ref"], actor=self.actor)["availability"], "admitted")


if __name__ == "__main__":
    unittest.main()
