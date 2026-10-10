import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from herzchen.evidence.model import EvidencePathCollisionError
from herzchen.content.model import domain_contribution as content_domain_contribution
from herzchen.kernel import Store
from herzchen.packs.authoring import read_managed_pack

from tests.test_evidence_lifecycle import _public_pack_hooks


def _v11_pack_hooks():
    pack_root, _discover, _load = _public_pack_hooks()
    revision = "a" * 40
    manifest_digest = hashlib.sha256((pack_root / "pack.yaml").read_bytes()).hexdigest()
    definition = SimpleNamespace(version="1.1.0", to_dict=lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2})
    paths = {
        "schemas/evidence.json": "evidence_schema", "policies/provenance.json": "evidence_policy",
        "presets/submit.json": "evidence_preset", "presets/version.json": "evidence_preset",
        "presets/list.json": "evidence_preset", "presets/read.json": "evidence_preset",
        "skill/SKILL.md": "skill", "templates/evidence.json": "evidence_template",
    }
    handles = tuple(SimpleNamespace(path=path, kind=kind, resolved=pack_root / path,
                                    sha256=hashlib.sha256((pack_root / path).read_bytes()).hexdigest())
                    for path, kind in paths.items())
    discovered = SimpleNamespace(
        id="evidence", source_kind="managed", source_revision=revision,
        source_tree_sha256="b" * 64, source_manifest_sha256=manifest_digest,
        source_inventory_identity="c" * 64, pack_dir=pack_root,
        entry=SimpleNamespace(manifest=SimpleNamespace(sha256=manifest_digest), definition=definition,
                              resource_handles=handles),
    )
    return pack_root, lambda *, project_root: (discovered,), lambda path, **kwargs: SimpleNamespace(id="evidence", schema_version=2)


class EvidenceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = Store.create(root / "owner.sqlite", authority="owner")
        self.store.register_domain_handler((content_domain_contribution(),))
        register_evidence(self.store)
        self.actor = AuthenticatedActor("owner", "submitter", "credential")
        self.project = ResourceRef("owner", "work.project", "project")
        self.store.put_identity(self.project, {"record_type": "work.project", "title": "fixture"}, version=0)
        pack_root, discover, loader = _v11_pack_hooks()
        pack = read_managed_pack("evidence", project_root=pack_root.parents[3], discoverer=discover, loader=loader)
        from herzchen.evidence.model import load_evidence_pack
        selected = load_evidence_pack(managed_pack=pack)
        self.handler = EvidenceCommandHandler(
            self.store, root / "managed", pack=selected,
            adopted_pins=[item.to_dict() for item in selected.resources],
        )

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def submit(self, value=b"projection-bytes"):
        return self.handler.submit(value, actor=self.actor, logical_request_key="submit-projection",
                                   project_ref=self.project, original_creator="creator")

    def test_lazy_checkout_materialization_collision_and_local_absence(self):
        source = b"binary\x00projection" * 128
        submitted = self.handler.submit(source, actor=self.actor, logical_request_key="projection-capture",
                                         project_ref=self.project, original_creator="creator",
                                         format="application/octet-stream")
        checkout = Path(self.directory.name) / "checkout"
        result = self.handler.checkout_evidence(self.project, checkout_root=checkout, actor=self.actor)
        self.assertFalse((checkout / "project.json").exists())
        self.assertFalse((checkout / "docs").exists())
        self.assertTrue((checkout / "evidence" / ".checkout.json").is_file())
        materialized = self.handler.materialize_evidence(
            submitted["revision_ref"], checkout_root=checkout, actor=self.actor, alias="logs/run.bin"
        )
        self.assertEqual(Path(materialized["path"]).read_bytes(), source)
        self.assertEqual(Path(materialized["path"]).stat().st_mode & 0o222, 0)
        marker = (checkout / "evidence" / ".checkout.json").read_text(encoding="utf-8")
        self.assertIn("logs/run.bin", marker)
        Path(materialized["path"]).unlink()
        self.assertEqual(self.handler.status(submitted["document_ref"], actor=self.actor)["availability"], "admitted")
        self.assertEqual(self.handler.read_evidence(submitted["revision_ref"], actor=self.actor, max_bytes=64)["bytes"], source[:64])

        collision = Path(self.directory.name) / "collision"
        collision.mkdir()
        (collision / "evidence").write_text("user-owned", encoding="utf-8")
        with self.assertRaises(EvidencePathCollisionError):
            self.handler.checkout_evidence(self.project, checkout_root=collision, actor=self.actor)

    def test_annotation_and_aliases_preserve_immutable_pin(self):
        submitted = self.submit()
        first = submitted["revision_ref"]
        cited = self.handler.cite_evidence(first, project_ref=self.project, alias="original.txt",
                                            actor=self.actor, logical_request_key="cite-original")
        annotated = self.handler.annotate(submitted["document_ref"], {"summary": "corrected"},
                                          actor=self.actor, logical_request_key="annotate-original",
                                          base_revision=first.revision)
        self.assertEqual(annotated["manifest"]["byte_digest"], submitted["manifest"]["byte_digest"])
        self.assertEqual(annotated["manifest"]["origin"], submitted["manifest"]["origin"])
        from herzchen.content.model import revision_identity
        original = self.store.get_identity(revision_identity(submitted["document_ref"], first.revision))
        self.assertNotIn("annotations", original.payload["content"])

        moved = self.handler.move_alias(project_ref=self.project, from_alias="original.txt", to_alias="renamed.txt",
                                        actor=self.actor, logical_request_key="move-original")
        self.assertEqual(moved["citation"], first)
        old_ref = ResourceRef("owner", "document-association", cited["association_ref"].id)
        old = self.store.get_identity(old_ref)
        self.assertFalse(old.payload["active"])
        # Read the active association page; its binding must remain the original exact pin.
        page = self.handler.list_evidence(self.project, actor=self.actor)
        active = [item for item in page["documents"] if item["binding_mode"] == "pinned"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["associated_pin"], first)

        unlinked = self.handler.unlink_alias(project_ref=self.project, alias="renamed.txt", actor=self.actor,
                                             logical_request_key="unlink-renamed")
        self.assertTrue(unlinked["canonical_preserved"])
        self.assertEqual(self.handler.status(submitted["document_ref"], actor=self.actor)["availability"], "admitted")

    def test_alias_collision_returns_recoverable_partial_without_retargeting(self):
        submitted = self.submit()
        first = submitted["revision_ref"]
        self.handler.cite_evidence(first, project_ref=self.project, alias="one.txt", actor=self.actor,
                                   logical_request_key="cite-one")
        self.handler.cite_evidence(first, project_ref=self.project, alias="two.txt", actor=self.actor,
                                   logical_request_key="cite-two")
        with self.assertRaises(EvidencePathCollisionError):
            self.handler.move_alias(project_ref=self.project, from_alias="one.txt", to_alias="two.txt",
                                    actor=self.actor, logical_request_key="move-collision")
        partial = self.handler.move_alias(project_ref=self.project, from_alias="one.txt", to_alias="three.txt",
                                          actor=self.actor, logical_request_key="move-partial", interrupt_at="after-link")
        self.assertEqual(partial["outcome"], "partial")
        self.assertEqual(partial["citation"], first)
        self.assertEqual(partial["pending"]["request_key"], "move-partial")
        resumed = self.handler.move_alias(project_ref=self.project, from_alias="one.txt", to_alias="three.txt",
                                          actor=self.actor, logical_request_key="move-partial")
        self.assertEqual(resumed["outcome"], "moved")
        self.assertEqual(self.handler.status(submitted["document_ref"], actor=self.actor)["manifest"]["byte_digest"],
                         hashlib.sha256(b"projection-bytes").hexdigest())


if __name__ == "__main__":
    unittest.main()
