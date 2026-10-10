"""D02 integration checks using only disposable FND/payload fixtures.

Run with PYTHONPATH=src:tests (the predecessor capture fixture is retained in
tests/test_evidence_lifecycle.py).
"""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from test_evidence_lifecycle import EvidenceLifecycleTests
from herzchen.contracts import AuthenticatedActor, ReferenceBinding, ResourceRef
from herzchen.content.model import ContentDocument, ContentRevision, DocumentAssociation, revision_identity
from herzchen.content.commands import ContentCommandHandler
from herzchen.evidence.model import EvidenceAccessDeniedError, EvidenceError
from herzchen.domains.assessment.module import verify_dat_evidence
from otto.portfolio.documents import ProjectDocumentReader
from otto.portfolio.execution_host import _atomic_json
from otto.portfolio.manager_journey_client import read_command_status
from otto.portfolio.retained_projection import read_projection, write_preparation_checkpoint


class BoundedEvidenceTests(unittest.TestCase):
    _submit = EvidenceLifecycleTests._submit
    tearDown = EvidenceLifecycleTests.tearDown

    def setUp(self):
        EvidenceLifecycleTests.setUp(self)
        # Extend the retained D01 fixture's public discovery snapshot with the
        # two declared candidate read presets; this is source proof, no adoption.
        from test_evidence_lifecycle import _public_pack_hooks
        from types import SimpleNamespace
        from herzchen.evidence.model import load_evidence_pack
        from herzchen.evidence.commands import EvidenceCommandHandler
        root, discover, loader = _public_pack_hooks()
        found = discover(project_root=root)[0]
        found.entry.definition.version = "1.1.0"
        found.entry.definition.to_dict = lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2}
        found.entry.resource_handles += tuple(SimpleNamespace(path=path, kind="evidence_preset",
            resolved=root / path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
            for path in ("presets/list.json", "presets/read.json"))
        self.pack = load_evidence_pack(project_root=root, discoverer=lambda **kwargs: (found,), loader=loader)
        self.handler = EvidenceCommandHandler(self.store, Path(self.directory.name) / "managed", pack=self.pack,
            adopted_pins=[item.to_dict() for item in self.pack.resources])

    def link(self, key, ref, project=None):
        project = project or self.project
        association = DocumentAssociation(project, "fixture", key,
            ReferenceBinding(ref, "pinned" if ref.revision else "current"))
        self.store.put_identity(ResourceRef("owner", "document-association", association.identity),
            {"association": association, "active": True}, version=0)

    def test_metadata_page_bounds_before_filters_and_keeps_pins(self):
        first = self._submit(b"first", "page-first")
        second = self.handler.version(first["revision_ref"], b"second", actor=self.actor,
            logical_request_key="page-second", project_ref=self.project, original_creator="creator")
        self.link("old", first["revision_ref"])
        self.link("head", first["document_ref"])
        foreign = ResourceRef("foreign", "dat.content.document", "secret", "rev-1")
        self.link("foreign", foreign)
        for i in range(200):
            other = ResourceRef("owner", "work.project", "unrelated")
            self.link("unrelated-%d" % i, first["document_ref"], other)
        trace = []
        self.store.connection.set_trace_callback(trace.append)
        pages, cursor = [], ""
        while True:
            page = self.handler.list_evidence(self.project, actor=self.actor, limit=7, cursor=cursor,
                representation="managed", format="text/plain; charset=utf-8")
            self.assertLessEqual(page["io_work"]["associations_examined"], 7)
            pages.extend(page["documents"])
            if page["next_cursor"] is None:
                break
            self.assertNotEqual(cursor, page["next_cursor"])
            cursor = page["next_cursor"]
        self.store.connection.set_trace_callback(None)
        self.assertEqual(len(pages), 2)
        self.assertEqual({item["current_head"] for item in pages}, {second["revision_ref"]})
        self.assertEqual({item["associated_pin"] for item in pages}, {first["revision_ref"], None})
        self.assertTrue(any("ORDER BY id LIMIT 7" in sql for sql in trace))
        self.assertFalse(any("json_extract" in sql or "events" in sql for sql in trace))

    def test_authorized_reuse_and_non_disclosing_denial(self):
        result = self._submit(b"private evidence", "reuse")
        other = ResourceRef("owner", "work.project", "reuse-project")
        self.store.put_identity(other, {"record_type": "work.project"}, version=0)
        self.link("reuse", result["revision_ref"], other)
        page = self.handler.list_evidence(other, actor=self.actor)
        self.assertEqual(page["documents"][0]["associated_pin"], result["revision_ref"])
        stranger = AuthenticatedActor("owner", "stranger", "credential-other")
        self.assertEqual(self.handler.list_evidence(other, actor=stranger)["documents"], [])
        messages = []
        for ref in (result["revision_ref"], ResourceRef("owner", "dat.content.document", "missing", "rev-1"),
                    ResourceRef("foreign", "dat.content.document", "secret", "rev-1")):
            with self.assertRaises(EvidenceAccessDeniedError) as caught:
                self.handler.status(ref, actor=stranger)
            messages.append(str(caught.exception))
        self.assertEqual(messages, ["document unavailable"] * 3)
        foreign_actor = AuthenticatedActor("foreign", self.actor.actor, "credential-other")
        with self.assertRaises(EvidenceAccessDeniedError):
            self.handler.status(result["revision_ref"], actor=foreign_actor)
        # Revocation uses the current head even for the earlier immutable pin.
        head = self.store.get_identity(result["document_ref"])
        changed = dict(head.payload)
        changed["document"] = dict(changed["document"], maintainer="different-owner")
        self.store.revise_identity(head.ref, changed, revision="rev-2",
            expected_revision=head.ref.revision, expected_version=head.version)
        with self.assertRaises(EvidenceAccessDeniedError):
            self.handler.resolve(result["revision_ref"], actor=self.actor)

    def test_ranges_work_integrity_and_actual_availability(self):
        data = bytes(range(256)) * 8192
        result = self._submit(data, "ranges", format="application/octet-stream")
        path = Path(self.directory.name) / "managed" / result["manifest"]["storage"]["location"]
        with patch.object(Path, "open", side_effect=AssertionError("status opened bytes")):
            status = self.handler.status(result["revision_ref"], actor=self.actor)
        self.assertEqual(status["availability"], "admitted")
        self.assertEqual(status["io_work"]["payload_bytes_hashed"], 0)
        detail = self.handler.resolve(result["revision_ref"], actor=self.actor, offset=3, max_bytes=65536)
        self.assertEqual(detail["bytes"], data[3:65539])
        self.assertEqual(detail["next_offset"], 65539)
        self.assertEqual(detail["io_work"]["payload_bytes_read"], 65536)
        self.assertEqual(detail["io_work"]["payload_bytes_hashed"], 0)
        for max_bytes in (65537, -1, True):
            with self.assertRaises(EvidenceError):
                self.handler.resolve(result["revision_ref"], actor=self.actor, max_bytes=max_bytes)
        reference = self.handler.consumer_reference(result["revision_ref"], actor=self.actor)
        self.assertEqual(reference["byte_digest"], hashlib.sha256(data).hexdigest())
        self.assertNotIn("manifest", reference)
        self.assertNotIn("content", reference)
        unknown = verify_dat_evidence(self.store, result["revision_ref"], actor=self.actor)
        self.assertEqual(unknown["state"], "unknown")
        self.assertEqual(unknown["manifest_state"], "verified")
        verified = verify_dat_evidence(self.store, result["revision_ref"], actor=self.actor, payload_resolver=self.handler)
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(verified["verification_scope"], "full-payload")
        self.assertEqual(verified["io_work"]["payload_bytes_hashed"], len(data))
        path.write_bytes(b"X" + data[1:])
        # Same-length corruption is unknown until explicit linear verification.
        self.assertEqual(self.handler.status(result["revision_ref"], actor=self.actor)["availability"], "admitted")
        bad = self.handler.resolve(result["revision_ref"], actor=self.actor, max_bytes=0, verify_full=True)
        self.assertEqual(bad["availability"], "corrupt")
        self.assertEqual(bad["io_work"]["payload_bytes_hashed"], len(data))
        path.unlink()
        self.assertEqual(self.handler.status(result["revision_ref"], actor=self.actor)["availability"], "missing")

    def test_shared_document_reader_uses_bounded_surface(self):
        result = self._submit(b"generic", "generic")
        self.link("generic", result["revision_ref"])
        content = ContentCommandHandler(self.store)
        class NoHydration:
            def export(self, *args, **kwargs):
                raise AssertionError("metadata listing exported entire project")
            def resolve_reference(self, *args, **kwargs):
                raise AssertionError("metadata listing hydrated body resolver")
        reader = ProjectDocumentReader(sheet_reader=NoHydration(), content_reader=content,
            visibility_reader=NoHydration())
        page = reader.list_metadata(self.project, actor=self.actor.actor, exact_role="evidence")
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["io_work"]["payload_bytes_read"], 0)

    def test_large_old_inline_resolves_to_honest_detail_requirement(self):
        ref = ResourceRef("owner", "dat.content.document", "old-large-inline")
        document = ContentDocument(ref, "evidence", "private", "write", self.actor.actor)
        revision = ContentRevision(ref, "rev-1", {"text": "x" * 1_000_000}, self.actor, initial=True)
        self.store.put_identity(ref, {"document": document, "current_revision": revision.ref}, version=0)
        self.store.put_identity(revision_identity(ref, "rev-1"),
            {"record_type": "dat.content.revision", "document": ref, "revision": "rev-1",
             "content": revision.content, "author": self.actor}, version=0)
        result = self.handler.resolve(revision.ref, actor=self.actor)
        self.assertEqual(result["representation"], "unknown")
        self.assertEqual(result["availability"], "detail-required")
        self.assertEqual(result["io_work"]["payload_bytes_parsed"], 0)
        detail = self.handler.read_legacy_inline(revision.ref, actor=self.actor)
        self.assertEqual(detail["content"], revision.content)
        self.assertTrue(detail["io_work"]["linear_historical_read"])

    def test_new_inline_metadata_does_not_hydrate_large_revision(self):
        from herzchen.content import domain_contribution
        from herzchen.contracts import TransactionContext
        from herzchen.content.reads import metadata_identity
        self.store.register_domain_handler((domain_contribution(),))
        content = ContentCommandHandler(self.store)
        ref = ResourceRef("owner", "dat.content.document", "large-inline")
        document = ContentDocument(ref, "working", "private", "write", self.actor.actor)
        revision = ContentRevision(ref, "rev-1", {"text": "x" * 4_000_000}, self.actor, initial=True)
        context = TransactionContext(self.actor, "inline-create", "e" * 64, expected_version=0)
        content.execute(content.build_create_document(context, document, revision))
        source = revision_identity(ref, "rev-1")
        seen = []
        original = self.store.get_identity_bounded
        def guarded(reference, **kwargs):
            seen.append(reference)
            if reference == source:
                raise AssertionError("metadata read opened inline body")
            return original(reference, **kwargs)
        with patch.object(self.store, "get_identity_bounded", guarded):
            item = content.metadata(revision.ref, actor=self.actor)
        self.assertEqual(item["representation"], "inline")
        self.assertGreater(item["byte_length"], 4_000_000)
        self.assertIn(metadata_identity(revision.ref), seen)
        self.assertEqual(item["io_work"]["payload_bytes_parsed"], 0)


class CompactProjectionTests(unittest.TestCase):
    def test_large_legacy_transport_remains_readable_without_automatic_hydration(self):
        from otto.portfolio.manager_journey_client import read_command_detail
        with tempfile.TemporaryDirectory() as directory:
            token = "e" * 32
            path = Path(directory) / ("response-" + token + ".json")
            raw = json.dumps({"outcome": "succeeded", "stdout": "legacy" * 20_000}).encode()
            path.write_bytes(raw)
            original_open = Path.open
            def guard(candidate, *args, **kwargs):
                if candidate == path:
                    raise AssertionError("status opened legacy body")
                return original_open(candidate, *args, **kwargs)
            with patch.object(Path, "open", guard):
                status = read_command_status(directory, token)
            self.assertEqual(status["verification"], "legacy-detail-required")
            self.assertEqual(status["io_work"]["payload_bytes_read"], 0)
            self.assertIsNone(status["response_sha256"])
            detail = read_command_detail(directory, token, offset=19, max_bytes=4096)
            self.assertEqual(detail["bytes"], raw[19:4115])
            self.assertEqual(detail["next_offset"], 4115)
            self.assertEqual(path.read_bytes(), raw)

    def test_response_status_never_reopens_payload_and_keeps_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            token = "a" * 32
            path = Path(directory) / ("response-" + token + ".json")
            result = {"outcome": "unknown", "candidate_ref": {"authority": "owner", "kind": "wrk.result", "id": "original", "revision": "rev-1"},
                "result_digest": "b" * 64, "generation": 3, "parent": {"principal": "parent", "generation": 2},
                "raw_result": {"huge": "data" * 1_000_000}}
            _atomic_json(path, result)
            original_open = Path.open
            def guarded_open(candidate, *args, **kwargs):
                if candidate == path:
                    raise AssertionError("routine status opened historical body")
                return original_open(candidate, *args, **kwargs)
            with patch.object(Path, "open", guarded_open):
                status = read_command_status(directory, token)
            self.assertEqual(status["outcome"], "unknown")
            self.assertEqual(status["summary"]["candidate_ref"], result["candidate_ref"])
            self.assertEqual(status["summary"]["parent"], result["parent"])
            self.assertEqual(status["response_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(status["io_work"]["payload_bytes_read"], 0)
            self.assertLess(status["io_work"]["metadata_bytes_read"], 65536)
            with self.assertRaises(PermissionError):
                read_projection(path.with_name("status-" + path.name), expected_binding={"request_id": "foreign"})

    def test_preparation_checkpoint_refs_and_binding_reject_foreign(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            binding = {"principal": "worker", "generation": 3, "assignment_ref": {"authority": "owner", "kind": "wrk.assignment", "id": "worker", "revision": "rev-2"},
                       "parent": {"principal": "parent", "generation": 2}}
            original = {"source_commit": "c" * 40, "before_state": {"project_ref": {"authority": "owner", "kind": "work.project", "id": "project", "revision": "rev-12"}, "huge": "data" * 100_000},
                        "stages": {"capture": {"outcome": "unknown", "result_digest": "d" * 64, "generation": 3}}}
            write_preparation_checkpoint(path, original, binding=binding)
            value = read_projection(path, expected_binding=binding)
            self.assertEqual(value["summary"]["stages"]["capture"]["outcome"], "unknown")
            detail = Path(value["artifact"]["path"]).read_bytes()
            self.assertEqual(json.loads(detail), original)
            self.assertEqual(hashlib.sha256(detail).hexdigest(), value["artifact"]["sha256"])
            self.assertEqual(value["io_work"]["payload_bytes_read"], 0)
            with self.assertRaises(PermissionError):
                read_projection(path, expected_binding={**binding, "generation": 4})
            with self.assertRaises(FileExistsError):
                write_preparation_checkpoint(path, original, binding=binding)


if __name__ == "__main__":
    unittest.main()
