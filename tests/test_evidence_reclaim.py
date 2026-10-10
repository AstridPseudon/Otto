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


if __name__ == "__main__":
    unittest.main()
