"""Final1 correction proof against the installed runtime and public managed pack.

Run with the installed runtime first on ``PYTHONPATH`` and with
``ASTRID_SOURCE_STATE`` pointing at the owner-provided managed source state.
The Store below is deliberately disposable fixture custody; it is not the
canonical operational Store.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from herzchen.content.model import domain_contribution as content_domain_contribution
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from herzchen.evidence.model import load_evidence_pack
from herzchen.kernel import Store


RUN_ROOT = Path(__file__).parents[1]
CONTROLLER_ROOT = Path(
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/"
    "otto-evidence-lifecycle-20261009/controller"
)
RUNTIME_ROOT = CONTROLLER_ROOT / "runtime-source"
SOURCE_STATE = CONTROLLER_ROOT / "evidence/d06-managed-installation/source-state.json"
PACK_ROOT = CONTROLLER_ROOT / (
    "evidence/d06-managed-installation/source-data/evidence/"
    "4abffbb0959e5dc92b2bdc306ca11ae81f77a649"
)
INSTALLED_OTTO_SKILL = RUNTIME_ROOT / "otto/portfolio/skills/SKILL.md"
INSTALLED_EVIDENCE_SKILL = PACK_ROOT / "skill/SKILL.md"

EXPECTED_RESOURCE_PINS = {
    "policies/provenance.json": "21f9760df7280e89144c8246512b0e4f69e86dc25e2b36fd2c9062699e622bf3",
    "presets/list.json": "c576633b5b29952248710d4a19bbb7c7f19beae578b61246799e4c6f24a81c24",
    "presets/read.json": "d849128e269619f85efd0f6ffc74deef7ddf933b150bb61c95e4942434151c8a",
    "presets/reclaim-apply.json": "cd180c3160560a397437356436813a809d41538220e64459a186d592139b0220",
    "presets/reclaim-preview.json": "6ce66fa992bc1d441609cf745f7776c72c1f8ffa5c96c401f9b1312bcfc7cd44",
    "presets/submit.json": "966dc91be748182027fbc912888fd611e2fa51cc5e25e08a11198d2823e31f61",
    "presets/version.json": "0d51235ea3344b47005dd439bd3a00110ef8ca26b9b63329219758a5dbfbc4aa",
    "schemas/evidence.json": "41c67848aebb8f44d8f35563074b50b7a5feb0e689999cd91cb29847c3332fec",
    "skill/SKILL.md": "bbdd205d6d49a25f6cf3abaebae1db49791f897830507c8355d39c2af218bd9a",
    "templates/evidence.json": "6b43aaecd04652edc5fb790e9f57656dffc2eba496e4eef79bace899c9694684",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_bytes(seed: bytes, length: int) -> bytes:
    return (seed * ((length // len(seed)) + 1))[:length]


class FinalCorrectionInstalledJourneyTests(unittest.TestCase):
    def test_one_installed_pack_capture_to_reclaim_journey(self) -> None:
        self.assertTrue(SOURCE_STATE.is_file())
        self.assertEqual(os.environ.get("ASTRID_SOURCE_STATE"), str(SOURCE_STATE))
        self.assertTrue(INSTALLED_OTTO_SKILL.is_file())
        self.assertTrue(INSTALLED_EVIDENCE_SKILL.is_file())

        state = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
        active = state["active"]["evidence"]
        self.assertEqual(active["revision"], "4abffbb0959e5dc92b2bdc306ca11ae81f77a649")
        self.assertEqual(active["tree_sha256"], "328a1827feae8f8a0ed4fc5cf765773ca68defaa87e2d4ef95c47aca41d4e30f")
        self.assertEqual(active["manifest_sha256"], "abfffa505a45c22fb5d7e86146fc10c018cbd6e4cfccb75ba05ef6b24457e459")

        pack = load_evidence_pack(project_root=PACK_ROOT)
        actual_pins = {item.path: item.digest for item in pack.resources}
        self.assertEqual(actual_pins, EXPECTED_RESOURCE_PINS)
        selection = pack.select([item.to_dict() for item in pack.resources])
        for operation in (
            "dat.evidence.capture",
            "dat.content.metadata.list",
            "dat.content.payload.read",
            "dat.evidence.reclaim.preview",
            "dat.evidence.reclaim.apply",
        ):
            pack.validate_operation(operation)

        with tempfile.TemporaryDirectory(prefix="d06-installed-evidence-") as temp:
            root = Path(temp)
            store = Store.create(root / "fixture-owner.sqlite", authority="fixture-owner")
            try:
                store.register_domain_handler((content_domain_contribution(),))
                register_evidence(store)
                actor = AuthenticatedActor("fixture-owner", "d06-worker", "fixture-credential")
                project = ResourceRef("fixture-owner", "work.project", "d06-project")
                other_project = ResourceRef("fixture-owner", "work.project", "d06-other-project")
                task = ResourceRef("fixture-owner", "work.task", "d06-task")
                attempt = ResourceRef("fixture-owner", "work.attempt", "d06-attempt")
                store.put_identity(project, {"record_type": "work.project", "title": "D06 fixture"}, version=0)
                store.put_identity(other_project, {"record_type": "work.project", "title": "D06 shared fixture"}, version=0)
                store.put_identity(
                    task,
                    {"record_type": "work.task", "project_ref": project, "title": "D06 task"},
                    version=0,
                )
                store.put_identity(
                    attempt,
                    {"record_type": "work.attempt", "project_ref": project, "task_ref": task},
                    version=0,
                )

                # This disposed fixture owner has exactly the named task and
                # attempt, both explicitly settled. Caller command metadata
                # cannot supply or replace this authoritative inventory.
                def fixture_dependencies(exact, selected_project):
                    known = selected_project == project
                    for value in (task, attempt):
                        current = store.consumer().get_identity_bounded(value)["record"]
                        known = known and current is not None and current.payload.get("recovery_state") == "settled"
                    return {"complete": bool(known), "holds": () if known else ("dependency-unknown",)}
                store.revise_identity(task, {**store.get_identity(task).payload, "recovery_state": "settled"},
                    revision="settled-1", expected_revision=None, expected_version=0)
                store.revise_identity(attempt, {**store.get_identity(attempt).payload, "recovery_state": "settled"},
                    revision="settled-1", expected_revision=None, expected_version=0)
                handler = EvidenceCommandHandler(store, root / "managed", selection=selection,
                    resolve_dependencies=fixture_dependencies)
                text = _fixture_bytes(b"d06-log-line\n", 1_048_576)
                binary = bytes(range(256)) * 4_096
                held = b"shared-retention-fixture"
                text_result = handler.submit(
                    text,
                    actor=actor,
                    logical_request_key="d06-installed-text",
                    project_ref=project,
                    task_ref=task,
                    attempt_ref=attempt,
                    original_creator="fixture-creator",
                    format="text/plain; charset=utf-8",
                )
                binary_result = handler.submit(
                    binary,
                    actor=actor,
                    logical_request_key="d06-installed-binary",
                    project_ref=project,
                    original_creator="fixture-creator",
                    format="application/octet-stream",
                )
                held_result = handler.submit(
                    held,
                    actor=actor,
                    logical_request_key="d06-installed-held",
                    project_ref=project,
                    original_creator="fixture-creator",
                )

                bounded = handler.read_evidence(
                    binary_result["revision_ref"], actor=actor, offset=123, max_bytes=64
                )
                self.assertEqual(bounded["bytes"], binary[123:187])
                self.assertEqual(bounded["verification"], "range-not-revalidated")
                self.assertLessEqual(bounded["io_work"]["payload_bytes_read"], 64)

                citation = handler.cite_evidence(
                    text_result["revision_ref"],
                    project_ref=project,
                    alias="d06-log.txt",
                    actor=actor,
                    logical_request_key="d06-installed-citation",
                )
                self.assertEqual(citation["citation"], text_result["revision_ref"])
                handler.cite_evidence(
                    binary_result["revision_ref"],
                    project_ref=project,
                    alias="d06-binary.bin",
                    actor=actor,
                    logical_request_key="d06-installed-binary-citation",
                )
                handler.cite_evidence(
                    held_result["revision_ref"],
                    project_ref=project,
                    alias="d06-held.bin",
                    actor=actor,
                    logical_request_key="d06-installed-held-citation",
                )
                handler.cite_evidence(
                    held_result["revision_ref"],
                    project_ref=other_project,
                    alias="d06-held.bin",
                    actor=actor,
                    logical_request_key="d06-installed-shared-citation",
                )

                checkout = root / "checkout"
                checkout_result = handler.checkout_evidence(project, checkout_root=checkout, actor=actor)
                self.assertTrue((checkout / "evidence" / ".checkout.json").is_file())
                self.assertFalse((checkout / "docs").exists())
                self.assertFalse((checkout / "project.json").exists())
                materialized = handler.materialize_evidence(
                    binary_result["revision_ref"],
                    checkout_root=checkout,
                    actor=actor,
                    alias="artifacts/d06.bin",
                )
                self.assertEqual(Path(materialized["path"]).read_bytes(), binary)
                self.assertEqual(Path(materialized["path"]).stat().st_mode & 0o222, 0)

                bundle = root / "bundle"
                bundle_result = handler.bundle_evidence(
                    project,
                    [
                        {"reference": text_result["revision_ref"], "alias": "logs/d06.txt"},
                        {"reference": binary_result["revision_ref"], "alias": "artifacts/d06.bin"},
                    ],
                    bundle,
                    actor=actor,
                )
                bundle_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(bundle_result["outcome"], "bundled")
                self.assertEqual(bundle_manifest["schema"], "dat.evidence.bundle.v1")
                self.assertEqual(len(bundle_manifest["inventory"]["included"]), 2)
                self.assertEqual(
                    {json.dumps(item["reference"], sort_keys=True) for item in bundle_manifest["inventory"]["included"]},
                    {
                        json.dumps(text_result["revision_ref"].to_dict(), sort_keys=True),
                        json.dumps(binary_result["revision_ref"].to_dict(), sort_keys=True),
                    },
                )

                listed = handler.list_evidence(project, actor=actor, limit=100)
                self.assertGreaterEqual(len(listed["documents"]), 3)
                preview = handler.reclaim_preview(
                    project,
                    actor=actor,
                    logical_request_key="d06-installed-reclaim-preview",
                    cutoff="9999-01-01T00:00:00Z",
                )
                applied = handler.reclaim_apply(
                    preview["selection_ref"],
                    actor=actor,
                    logical_request_key="d06-installed-reclaim-apply",
                    project_ref=project,
                )
                self.assertEqual(applied["managed_bytes_removed"], len(text) + len(binary))
                self.assertIn("shared-reference", [item["reason"] for item in applied["held"]])
                self.assertFalse(
                    (root / "managed" / text_result["manifest"]["storage"]["location"]).exists()
                )
                self.assertFalse(
                    (root / "managed" / binary_result["manifest"]["storage"]["location"]).exists()
                )
                self.assertTrue(
                    (root / "managed" / held_result["manifest"]["storage"]["location"]).is_file()
                )
                for result in (text_result, binary_result):
                    after = handler.status(result["revision_ref"], actor=actor)
                    self.assertEqual(after["availability"], "purged")
                    self.assertTrue(after["manifest"]["tombstone"]["decision_history_preserved"])
                self.assertEqual(handler.status(held_result["revision_ref"], actor=actor)["availability"], "admitted")
                disabled = handler.disable_workflow()
                self.assertEqual(disabled, {"outcome": "disabled", "data_preserved": True, "new_workflow_admission": False})

                print(json.dumps({
                    "journey": "final1 corrected capture/read/cite/checkout/materialize/bundle/reclaim",
                    "dependency_authority": "disposable owner named settled task/attempt inventory; not canonical operational proof",
                    "runtime_root": str(RUNTIME_ROOT),
                    "source_state": str(SOURCE_STATE),
                    "pack_root": str(PACK_ROOT),
                    "pack_id": pack.pack_id,
                    "pack_version": pack.version,
                    "pack_manifest_sha256": pack.manifest_digest,
                    "pack_source_revision": pack.source.source_revision,
                    "pack_source_tree_sha256": pack.source.source_tree_sha256,
                    "selection_digest": selection.digest,
                    "installed_otto_skill_sha256": _sha256(INSTALLED_OTTO_SKILL),
                    "installed_evidence_skill_sha256": _sha256(INSTALLED_EVIDENCE_SKILL),
                    "candidate_runtime_commands_sha256": _sha256(RUN_ROOT / "src/herzchen/evidence/commands.py"),
                    "installed_runtime_commands_sha256": _sha256(RUNTIME_ROOT / "herzchen/evidence/commands.py"),
                    "payloads": {"text_bytes": len(text), "binary_bytes": len(binary), "held_bytes": len(held)},
                    "bounded_read": {"offset": bounded["offset"], "bytes": len(bounded["bytes"]), "verification": bounded["verification"]},
                    "checkout": {"lazy": checkout_result["outcome"], "materialized": materialized["path"]},
                    "bundle": {"outcome": bundle_result["outcome"], "included": len(bundle_manifest["inventory"]["included"])},
                    "reclaim": {"managed_bytes_removed": applied["managed_bytes_removed"], "held_reasons": sorted({item["reason"] for item in applied["held"]}), "tombstones": len(applied["tombstones"])},
                    "workflow_disable": disabled,
                }, sort_keys=True))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
