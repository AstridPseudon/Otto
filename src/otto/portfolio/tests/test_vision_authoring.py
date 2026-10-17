"""D02 source integrity proof on isolated DAT/EDT fixtures.

Managed loader/adoption inputs below are explicit test doubles, not installed
Vision pins or owner acceptance. Existing writer/custody mechanisms are real.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from herzchen.authoring import AuthoringLifecycle, FileWriterLeaseAuthority, domain_contribution as edt_domain
from herzchen.authoring.sessions import AuthoringSessionService
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler, SchemaValidationError, ScopeAuthorizationError
from herzchen.content.packets import ContextPacketService, AccessDeniedError, UnresolvedReferenceError, domain_contribution as packet_domain
from herzchen.content.vision import (ManagedVisionDefinitions, VisionValidator, VisionValidationError,
                                    DEFINITION_CONTRACT, diagnose_collection, RESOURCE_PATH)
from herzchen.content.vision_authoring import VisionAuthoring
from herzchen.contracts import AuthenticatedActor, ResourceRef, ReferenceBinding, TransactionContext, ReplayConflictError, canonical_json
from herzchen.packs.authoring import ManagedSourceIdentity, ManagedResource, ManagedPack, ExecutionPin
from herzchen.kernel.store import Store
from otto.portfolio.fixtures.vision import PAGES, frame_nodes


class VisionAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="vision-d02-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store.create(self.root / "fixture.sqlite", authority="vision-test")
        self.store.register_domain_handler((domain_contribution(), edt_domain(), packet_domain()))
        self.addCleanup(self.store.close)
        self.actor = AuthenticatedActor("vision-test", "owner", "fixture-only")
        self.content = ContentCommandHandler(self.store)
        self.packets = ContextPacketService(self.store)
        source_schema = Path(__file__).parents[3] / "herzchen/packs/vision_resource_pack/schemas/vision-node.json"
        schema = source_schema.read_bytes()
        self.pack_root = self.root / "managed-fixture"
        self.pack_root.mkdir()
        manifest = self.pack_root / "pack.yaml"
        manifest.write_text("fixture-only\n")
        schema_path = self.pack_root / RESOURCE_PATH
        schema_path.parent.mkdir()
        schema_path.write_bytes(schema)
        digest = hashlib.sha256(schema).hexdigest()
        source = ManagedSourceIdentity("vision", "managed", "a" * 40, "b" * 64,
            hashlib.sha256(manifest.read_bytes()).hexdigest(), "c" * 64, str(self.pack_root), str(manifest))
        resource = ManagedResource(RESOURCE_PATH, "vision_schema", schema, digest,
                                  ResourceRef("managed-source", "managed_pack", "vision", "a" * 40))
        self.pack = ManagedPack("vision", "1.0.0", source, {}, (resource,), (), ())
        self.pin = ExecutionPin("vision/" + RESOURCE_PATH, "vision_schema", "a" * 40, digest)
        self.definition = {"pack_id": "vision", "source_revision": "a" * 40,
            "resource_path": RESOURCE_PATH, "resource_sha256": digest, "host_contract": "vision-inline.v1"}
        self.definitions = ManagedVisionDefinitions((self.pack,), (self.pin,))
        self.validator = VisionValidator(self.definitions, target_reader=self.visible)
        self.authoring = DocumentAuthoringHandler(self.store, vision_validator=self.validator)
        self.creator = VisionAuthoring(self.authoring, self.actor)
        self.refs = {name: self.creator.creation_ref("frame:" + name) for name, *_ in PAGES}
        self.nodes = frame_nodes(self.definition, self.refs)

    def visible(self, binding, actor=None):
        try:
            return self.packets.resolve_reference(binding, actor=actor or self.actor)
        except (AccessDeniedError, UnresolvedReferenceError):
            return None

    def head(self, ref):
        current = ResourceRef.from_dict(self.content.read(ref)["current_revision"])
        return current, self.content.read(current)["content"]

    def create(self, name="frame"):
        result = self.creator.create(self.nodes[name], request_id="frame:" + name)
        self.assertIsNotNone(result.revision_ref, result)
        self.assertEqual(result.document_ref, self.refs[name])
        return result

    def test_connected_fixture_and_normal_roundtrip_preserve_every_field(self):
        results = {name: self.create(name) for name, *_ in PAGES}
        self.assertEqual(len(results), 14)
        counts = {kind: sum(node["kind"] == kind for node in self.nodes.values()) for kind in ("product", "area", "repository", "concept", "subsystem")}
        self.assertEqual(counts, {"product": 1, "area": 2, "repository": 7, "concept": 2, "subsystem": 2})
        for name in results:
            ref, content = self.head(self.refs[name])
            self.assertEqual(content, self.nodes[name])
            self.assertGreater(len(content["body_markdown"]), 90)
            self.assertEqual(content["definition"], self.definition)
        offline = deepcopy(self.nodes["offline"])
        offline["title"] = "Recoverable disconnected work"
        offline["body_markdown"] += "\n\nA recovery copy bridges the transition to a journal."
        offline["sources"] = [{"ref": results["model"].revision_ref.to_dict(), "use": "rationale", "note": "Exact prior model intent"}]
        from herzchen.domains.work import WorkModule, register_work
        register_work(self.store)
        work = WorkModule(self.store, actor=self.actor)
        project = work.create_project(title="Fixture scope", logical_request_key="fixture-project")
        task = work.create_task(project.ref, title="Recovery copy", logical_request_key="fixture-task")
        offline["work_refs"] = [task.ref.to_dict()]
        opened = self.authoring.open_owned(self.refs["offline"], self.actor, request_id="edit-offline")
        saved = self.authoring.autosave(opened, {"content": offline}, request_id="save-offline")
        self.assertTrue(saved.saved)
        result = self.authoring.finish(opened, draft={"content": offline}, request_id="finish-offline")
        self.assertIsNotNone(result.applied, result)
        self.assertEqual(self.head(self.refs["offline"])[1], offline)
        self.assertEqual(self.content.read(results["offline"].revision_ref)["content"], self.nodes["offline"])
        projection = {canonical_json(ref): self.head(ref)[1] for ref in self.refs.values()}
        self.assertEqual(diagnose_collection(projection), ())

    def test_creation_and_finish_replay_bind_exact_input(self):
        first = self.create("offline")
        second = self.create("offline")
        self.assertEqual(first.document_ref, second.document_ref)
        self.assertEqual(first.revision_ref, second.revision_ref)
        changed = deepcopy(self.nodes["offline"])
        changed["body_markdown"] += "changed request"
        with self.assertRaises(ReplayConflictError):
            self.creator.create(changed, request_id="frame:offline")
        opened = self.authoring.open_owned(first.document_ref, self.actor, request_id="edit")
        result = self.authoring.finish(opened, draft={"content": changed}, request_id="finish")
        self.assertIsNotNone(result.applied)
        replay = self.authoring.finish(opened, draft={"content": changed}, request_id="finish")
        self.assertEqual(replay.finish.status, "replayed")
        changed["relationships"].pop()
        with self.assertRaises(ReplayConflictError):
            self.authoring.finish(opened, draft={"content": changed}, request_id="finish")
        self.assertEqual(self.head(first.document_ref)[1], result.applied.revision.content)

    def test_structure_definition_digest_size_rejections_keep_drafts_and_head(self):
        first = self.create("offline")
        cases = {}
        bad = deepcopy(self.nodes["offline"]); bad["unrecognized"] = True; cases["unknown"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["definition"]["resource_sha256"] = "0" * 64; cases["digest"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["definition"]["source_revision"] = "b" * 40; cases["definition"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["body_markdown"] = "é" * 20000; cases["oversize"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["relationships"][0]["target"]["ref"]["revision"] = "pinned"; cases["binding"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["relationships"] += [bad["relationships"][0]]; cases["duplicate"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["as_of"] = "2026-02-30"; cases["date"] = bad
        bad = deepcopy(self.nodes["offline"]); bad["navigation_parent"] = ReferenceBinding(first.document_ref, "current").to_dict(); cases["self-parent"] = bad
        cases["malformed"] = b'{"content":'
        for name, bad in cases.items():
            with self.subTest(name=name):
                opened = self.authoring.open_owned(first.document_ref, self.actor, request_id="open-" + name)
                draft = bad if isinstance(bad, bytes) else {"content": bad}
                saved = self.authoring.autosave(opened, draft, request_id="save-" + name)
                self.assertTrue(saved.saved)
                result = self.authoring.finish(opened, draft=draft, request_id="reject-" + name)
                self.assertIsNone(result.applied)
                self.assertEqual(self.head(first.document_ref)[0], first.revision_ref)
                recovered = self.authoring.recover(opened, self.actor)
                self.assertTrue(recovered["read_only"])
                self.assertIsNotNone(result.finish.final_snapshot)
                raw = self.authoring.authoring.read_snapshot(result.finish.final_snapshot.ref)
                expected = draft if isinstance(draft, bytes) else canonical_json(draft).encode()
                self.assertEqual(raw, expected)

    def test_stale_cas_is_atomic_and_recoverable(self):
        created = self.create("offline")
        opened = self.authoring.open_owned(created.document_ref, self.actor, request_id="stale-open")
        competing = deepcopy(self.nodes["offline"])
        competing["body_markdown"] += "\nCompeting paragraph"
        self.content.execute(self.content.build_append_revision(
            TransactionContext(self.actor, "fixture-competing-edit", "d" * 64, expected_revision=created.revision_ref.revision),
            self.authoring.read(created.document_ref)["document"],
            ContentRevision(created.document_ref, "competing", competing, self.actor, parent_revision=created.revision_ref.revision)))
        proposal = deepcopy(self.nodes["offline"])
        proposal["body_markdown"] += "\nLocal proposal"
        proposal["relationships"].pop()
        result = self.authoring.finish(opened, draft={"content": proposal}, request_id="stale-finish")
        self.assertIsNone(result.applied)
        self.assertEqual(result.finish.failure_status, "conflict")
        self.assertEqual(self.head(created.document_ref)[1], competing)
        self.assertIsNotNone(result.finish.final_snapshot)

    def test_canonical_role_metadata_and_definition_cannot_escape_validation(self):
        created = self.create("offline")
        opened = self.authoring.open_owned(created.document_ref, self.actor, request_id="open")
        doc = self.authoring.read(created.document_ref)["document"]
        bad = {"document": replace(doc, role="notes"), "content": {"text": "escape"}}
        result = self.authoring.finish(opened, draft=bad, request_id="finish")
        self.assertIsNone(result.applied)
        self.assertEqual(self.head(created.document_ref)[0], created.revision_ref)
        unselected = DocumentAuthoringHandler(self.store)
        with self.assertRaisesRegex(SchemaValidationError, "definition_unavailable"):
            unselected.validate({"content": self.nodes["offline"]}, target=created.document_ref)
        notes = replace(doc, ref=ResourceRef("vision-test", "dat.content.document", "notes"), role="notes")
        with self.assertRaisesRegex(SchemaValidationError, "canonical role"):
            self.authoring.validate({"document": notes, "content": self.nodes["offline"]}, target=notes.ref)

    def test_selected_definition_is_exact_and_data_only(self):
        with self.assertRaisesRegex(VisionValidationError, "not selected"):
            ManagedVisionDefinitions((self.pack,), ()).resolve(self.definition)
        bad = {**self.definition, "resource_sha256": "0" * 64}
        with self.assertRaisesRegex(VisionValidationError, "digest mismatch"):
            self.definitions.resolve(bad)
        wrong_resource = replace(self.pack.resources[0], source_ref=ResourceRef("managed-source", "managed_pack", "vision", "b" * 40))
        with self.assertRaisesRegex(VisionValidationError, "provenance"):
            ManagedVisionDefinitions((replace(self.pack, resources=(wrong_resource,)),), (self.pin,)).resolve(self.definition)
        unsafe = {**DEFINITION_CONTRACT, "hook": "os.system('never run')"}
        raw = canonical_json(unsafe).encode()
        digest = hashlib.sha256(raw).hexdigest()
        resource = replace(self.pack.resources[0], content=raw, source_digest=digest)
        pin = replace(self.pin, digest=digest)
        with self.assertRaisesRegex(VisionValidationError, "semantics"):
            ManagedVisionDefinitions((replace(self.pack, resources=(resource,)),), (pin,)).resolve({**self.definition, "resource_sha256": digest})
        # An upgrade cannot reinterpret an old exact descriptor.
        newer = replace(self.pack, source=replace(self.pack.source, source_revision="b" * 40))
        with self.assertRaisesRegex(VisionValidationError, "exact managed source unavailable"):
            ManagedVisionDefinitions((newer,), (self.pin,)).resolve(self.definition)
        ManagedVisionDefinitions((self.pack, newer), (self.pin,)).resolve(self.definition)

    def test_known_wrong_kind_rejects_but_unavailable_links_remain_diagnostic(self):
        concept = self.create("operation-identity")
        bad = deepcopy(self.nodes["offline"])
        bad["applies_to"] = [ReferenceBinding(concept.document_ref, "current").to_dict()]
        with self.assertRaisesRegex(SchemaValidationError, "wrong required kind"):
            self.authoring.validate({"document": ContentDocument(self.refs["offline"], "vision", "private", "write", "owner"), "content": bad})
        stranger = AuthenticatedActor("vision-test", "stranger", "fixture-other")
        hidden_validator = VisionValidator(self.definitions, target_reader=lambda b: self.visible(b, stranger))
        # The same inaccessible citation reveals no target kind/title/existence.
        hidden_validator.validate(bad, self.refs["offline"])
        normalized = self.validator.validate(self.nodes["offline"], self.refs["offline"])
        findings = diagnose_collection({canonical_json(self.refs["offline"]): normalized})
        self.assertTrue(any(f["code"] == "unresolved_or_outside_collection" for f in findings))
        self.assertFalse(any("title" in f for f in findings))
        left, right = deepcopy(self.nodes["creation"]), deepcopy(self.nodes["collaboration"])
        left["navigation_parent"] = ReferenceBinding(self.refs["collaboration"], "current").to_dict()
        right["navigation_parent"] = ReferenceBinding(self.refs["creation"], "current").to_dict()
        self.validator.validate(left, self.refs["creation"])
        self.validator.validate(right, self.refs["collaboration"])
        findings = diagnose_collection({canonical_json(self.refs["creation"]): left, canonical_json(self.refs["collaboration"]): right})
        self.assertEqual(sum(f["code"] == "navigation_cycle" for f in findings), 2)

    def test_partial_root_inclusion_reuses_created_id(self):
        self.nodes["frame"]["members"] = []
        root, node = self.create("frame"), self.create("offline")
        opened = self.authoring.open_owned(root.document_ref, self.actor, request_id="root-open")
        competing = deepcopy(self.nodes["frame"])
        competing["body_markdown"] += "\nAnother root edit"
        self.content.execute(self.content.build_append_revision(
            TransactionContext(self.actor, "root-competitor", "e" * 64, expected_revision=root.revision_ref.revision),
            self.authoring.read(root.document_ref)["document"],
            ContentRevision(root.document_ref, "root-competing", competing, self.actor, parent_revision=root.revision_ref.revision)))
        failed = self.creator.include(node.document_ref, opened, request_id="include-stale")
        self.assertEqual(failed.root_finish.finish.failure_status, "conflict")
        self.assertEqual(failed.document_ref, node.document_ref)
        self.assertTrue(failed.inclusion_pending)
        self.assertIsNone(failed.root_finish.applied)
        self.assertEqual(self.head(root.document_ref)[1]["members"], [])
        retained = self.create("offline")
        self.assertEqual(retained.document_ref, node.document_ref)
        opened = self.authoring.open_owned(root.document_ref, self.actor, request_id="root-reconcile")
        included = self.creator.include(retained.document_ref, opened, request_id="include-current")
        self.assertIsNotNone(included.root_finish.applied)
        self.assertFalse(included.inclusion_pending)
        self.assertEqual(self.head(root.document_ref)[1]["members"], [ReferenceBinding(node.document_ref, "current").to_dict()])
        self.assertIn("Another root edit", self.head(root.document_ref)[1]["body_markdown"])
        self.assertEqual(self.head(node.document_ref)[0], node.revision_ref)

    def test_imported_and_pinned_sources_cannot_open(self):
        for mode in ("imported", "pinned"):
            ref = ResourceRef("vision-test", "dat.content.document", mode)
            source = ResourceRef("source-owner", "dat.content.document", "source", "r1" if mode == "pinned" else None)
            doc = ContentDocument(ref, "vision", "shared", "read", "owner", source_ref=source, import_mode=mode, writable=False)
            with self.assertRaisesRegex(ValueError, "cannot create a local content revision"):
                self.content.build_create_document(TransactionContext(self.actor, "import-" + mode, "f" * 64),
                    doc, ContentRevision(ref, "r1", self.nodes["offline"], self.actor, initial=True))
            with self.assertRaisesRegex(ScopeAuthorizationError, "read-only"):
                self.authoring.materialise(doc, self.actor, request_id="open-" + mode)
        owned = self.create("offline")
        pinned = self.authoring.open_owned(owned.revision_ref, self.actor, request_id="open-exact")
        self.assertIsNone(pinned.open_result.handle)

    def test_optional_defaults_and_reference_constraints(self):
        minimal = {key: self.nodes["offline"][key] for key in ("schema", "definition", "kind", "title", "summary", "as_of", "body_markdown")}
        normalized = self.validator.validate(minimal, self.refs["offline"])
        self.assertEqual(normalized["maturity"], "sketch")
        for name in ("applies_to", "relationships", "sources", "work_refs"):
            self.assertEqual(normalized[name], [])
        for name in ("members", "repository", "horizon", "navigation_parent"):
            self.assertIsNone(normalized[name])
        bad_cases = []
        bad = deepcopy(normalized); bad["navigation_parent"] = ReferenceBinding(ResourceRef("foreign", "dat.content.document", "outside"), "current").to_dict(); bad_cases.append(bad)
        bad = deepcopy(normalized); bad["relationships"] = [{"id": "old", "relation": "supersedes", "target": ReferenceBinding(self.refs["frame"], "current").to_dict()}]; bad_cases.append(bad)
        bad = deepcopy(normalized); bad["members"] = []; bad_cases.append(bad)
        bad = deepcopy(normalized); bad["applies_to"] = [ReferenceBinding(self.refs["desktop"], "current").to_dict()] * 2; bad_cases.append(bad)
        bad = deepcopy(normalized); bad["sources"] = [{"ref": self.refs["frame"].to_dict(), "use": "observation"}]; bad_cases.append(bad)
        bad = deepcopy(normalized); bad["repository"] = {"key": "invalid-for-concept"}; bad_cases.append(bad)
        bad = deepcopy(normalized); bad["work_refs"] = [ResourceRef("vision-test", "work.task", "unavailable").to_dict()]; bad_cases.append(bad)
        for index, bad in enumerate(bad_cases):
            with self.subTest(index=index), self.assertRaises(VisionValidationError):
                self.validator.validate(bad, self.refs["offline"])
        product = deepcopy(self.nodes["frame"])
        product["members"] = [ReferenceBinding(ResourceRef("vision-test", "dat.content.document", "member-" + str(i)), "current").to_dict() for i in range(129)]
        with self.assertRaisesRegex(VisionValidationError, "128"):
            self.validator.validate(product, self.refs["frame"])

    def test_self_supersedes_requires_an_existing_exact_revision(self):
        created = self.create("offline")
        changed = deepcopy(self.nodes["offline"])
        changed["relationships"].append({"id": "prior", "relation": "supersedes",
            "target": ReferenceBinding(created.revision_ref, "pinned").to_dict()})
        opened = self.authoring.open_owned(created.document_ref, self.actor, request_id="supersede-open")
        result = self.authoring.finish(opened, draft={"content": changed}, request_id="supersede-finish")
        self.assertIsNotNone(result.applied, result)
        self.assertNotEqual(result.applied.revision.ref, created.revision_ref)
        changed["relationships"][-1]["target"]["ref"]["revision"] = "not-admitted"
        with self.assertRaisesRegex(SchemaValidationError, "older revision"):
            self.authoring.validate({"content": changed}, target=created.document_ref)

    def test_document_json_initial_buffer_and_reverting_content_keep_history(self):
        created = self.create("offline")
        envelopes = []
        def capture(checkout, initial_bytes):
            envelopes.append(json.loads(initial_bytes))
        opened = self.authoring.materialise(created.document_ref, self.actor,
            request_id="unchanged-open", materialize=capture)
        self.assertEqual(envelopes[0]["content"], self.nodes["offline"])
        result = self.authoring.finish(opened, draft=envelopes[0], request_id="unchanged-finish")
        self.assertIsNotNone(result.applied, result)
        self.assertNotEqual(result.applied.revision.ref, created.revision_ref)
        original = deepcopy(self.nodes["offline"])
        changed = deepcopy(original); changed["title"] = "Alternative title"
        for index, node in enumerate((changed, original)):
            opened = self.authoring.open_owned(created.document_ref, self.actor, request_id="history-open-" + str(index))
            result = self.authoring.finish(opened, draft={"content": node}, request_id="history-finish-" + str(index))
            self.assertIsNotNone(result.applied, result)
        self.assertEqual(self.head(created.document_ref)[1], original)
        self.assertEqual(self.content.read(created.revision_ref)["content"], original)

    def test_direct_create_apply_replay_has_original_receipt_identity(self):
        ref = self.refs["offline"]
        doc = ContentDocument(ref, "vision", "private", "write", "owner")
        opened = self.authoring.materialise(doc, self.actor, request_id="apply-open")
        draft = {"document": doc, "content": self.nodes["offline"]}
        first = self.authoring.apply(opened, draft, request_id="apply-create")
        replay = self.authoring.apply(opened, draft, request_id="apply-create")
        self.assertEqual(first.receipt, replay.receipt)
        changed = deepcopy(draft); changed["content"]["title"] = "Changed"
        with self.assertRaises(ReplayConflictError):
            self.authoring.apply(opened, changed, request_id="apply-create")
        self.assertEqual(self.head(ref)[0], first.revision.ref)

    def test_actual_standalone_editor_host_manual_idle_and_refusal(self):
        from herzchen.domains.work import contributions
        from herzchen.domains.assessment.module import contribution as assessment_domain
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        from otto.portfolio.herzchen_binding import HerzchenBindingConfig
        from otto.portfolio.document_editor_host import DocumentEditorHost
        self.store.register_domain_handler((*contributions(include_assignment_resources=True), assessment_domain()))
        owner = PortfolioOwnerBootstrap(self.store, binding=HerzchenBindingConfig("vision-test", "fixture-only"), owner_actor="owner")
        host = DocumentEditorHost(owner=owner, directory=self.root / "editor", secret=b"x" * 32,
            vision_validator=self.validator, clock=lambda: 1000.0)
        created = self.create("offline")
        def call(operation, key, **arguments):
            return host.dispatch({"command": "document-authoring", "operation": operation,
                "request_key": key, **arguments}, actor=self.actor)
        help_result = call("help", "help")
        self.assertIn("project_ref", help_result["optional_fields"]["open"])
        for mode in ("finish", "idle-close"):
            opened = call("open", "editor-open-" + mode, document_ref=created.document_ref.to_dict(), inactivity_seconds=0)
            self.assertEqual(opened["outcome"], "opened")
            session = {"document_ref": created.document_ref.to_dict(), "handle": opened["handle"]}
            path = self.root / "editor/checkouts" / opened["handle"]["session_id"] / "document.json"
            envelope = json.loads(path.read_text())
            self.assertEqual(envelope["content"], self.head(created.document_ref)[1])
            envelope["content"]["body_markdown"] += "\nEdited through the actual shared host " + mode
            saved = call("save", "editor-save-" + mode, editor_buffer=envelope, **session)
            self.assertTrue(saved["buffer_captured"])
            result = call(mode, "editor-publish-" + mode, **session)
            self.assertIn(result["outcome"], ("finished", "checked_in"), result)
            self.assertEqual(self.head(created.document_ref)[1], envelope["content"])
        opened = call("open", "invalid-editor-open", document_ref=created.document_ref.to_dict())
        session = {"document_ref": created.document_ref.to_dict(), "handle": opened["handle"]}
        bad = deepcopy(self.head(created.document_ref)[1]); bad["unknown"] = True
        before = self.head(created.document_ref)[0]
        call("save", "invalid-editor-save", editor_buffer={"content": bad}, **session)
        rejected = call("finish", "invalid-editor-finish", **session)
        self.assertFalse(rejected["dat_revision_advanced"])
        self.assertEqual(self.head(created.document_ref)[0], before)
        with self.assertRaises(PermissionError):
            host.dispatch({"command": "document-authoring", "operation": "help", "request_key": "foreign"},
                actor=AuthenticatedActor("vision-test", "outsider", "other"))
        with self.assertRaises(PermissionError):
            call("open", "missing", document_ref=ResourceRef("vision-test", "dat.content.document", "missing").to_dict())
        with self.assertRaises(ValueError):
            call("open", "actor-field", document_ref=created.document_ref.to_dict(), actor="owner")

    def test_shared_lifecycle_checkin_and_idle_validate_vision(self):
        created = self.create("offline")
        def materialize(checkout, initial_bytes):
            root = self.root / checkout.session_id
            root.mkdir()
            (root / "document.json").write_bytes(initial_bytes)
            return {"path": str(root), "registered_files": ["document.json"]}
        sessions = AuthoringSessionService(self.store, materializer=materialize)
        authoring = DocumentAuthoringHandler(self.store, authoring=sessions, vision_validator=self.validator)
        leases = FileWriterLeaseAuthority(self.root / "leases", authority="vision-test", secret=b"x" * 32, writer_identities=("host",))
        lifecycle = AuthoringLifecycle(sessions, writer_leases=leases, writer_identity="host")
        for mode in ("manual", "idle"):
            opened = authoring.open_owned(created.document_ref, self.actor, request_id="open-" + mode)
            bad = deepcopy(self.nodes["offline"]); bad["unknown"] = "reject"
            draft = {"content": bad}
            authoring.autosave(opened, draft, request_id="save-" + mode, content_edit_at=0)
            (Path(opened.handle.checkout_path) / "document.json").write_text(canonical_json(draft))
            result = lifecycle.finish(opened.handle, request_id="checkin-" + mode, mode=mode,
                checkout_root=opened.handle.checkout_path, registered_files=("document.json",),
                handler=authoring.lifecycle_handler(opened, request_id="checkin-" + mode), writer_check=lambda: "quiescent")
            self.assertNotIn(result.status, ("finished", "applied"), result)
            self.assertEqual(self.head(created.document_ref)[0], created.revision_ref)
            recovered = authoring.recover(opened, self.actor)
            self.assertTrue(recovered["read_only"])
            self.assertTrue((Path(opened.handle.checkout_path) / "document.json").exists())
            authoring.discard(opened, self.actor, request_id="discard-" + mode)


if __name__ == "__main__":
    unittest.main()
