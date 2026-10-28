## XFERMAP design

1. [intake.py:849](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/intake.py:849) and [herzchen_binding.py:306](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:306) → Add a read-only manifest capture path that follows `list_projects.next_cursor` to exhaustion. Take the selected project set from an explicit, approved selection containing the program, seven follow-ups, r4, and every other selected upcoming project. Record that selection separately from the captured pages; refuse partial outcomes, issues, repeated cursors, missing members, and duplicate identities. Do not derive the transfer from `show_project` or a single `list_work` page.

2. [herzchen_binding.py:881](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:881) → Make each project export exhaustive against its owner records: every project task ref, every active project or task document association, every referenced document, and every required exact revision/body must resolve. Record full source identities and revisions, including task revisions that can advance without a project revision. Refuse an incomplete export instead of skipping a record.

3. [project_folder.py:490](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/project_folder.py:490) → Validate the manifest’s declared counts and identity sets against the exported records. Keep the per-operation bounds, but refuse a project that cannot be transferred completely within them; a partial selection must never count as preservation. Treat the digest as integrity of supplied bytes, not proof of completeness.

4. [herzchen_binding.py:1118](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:1118), [herzchen_binding.py:1174](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:1174), and [herzchen_binding.py:1237](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:1237) → Produce explicit, one-to-one source→target maps for projects, tasks, documents, revisions, and associations. Preserve each link’s mapped subject and current or pinned binding. Refuse unresolved dependencies or links; never silently drop them.

5. [intake.py:1374](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/intake.py:1374) → Add `transfer_manifest.py` with `capture_manifest`, `manifest_digest`, and `verify_manifest`. The verifier re-reads both owners independently of import receipts and stored transfer metadata. Compare mapped tasks, dependencies, criteria, instructions, configuration, notes, document bodies, link subjects, and bindings. Return `verified` only with exact set equality and no read errors. Re-read the source revision vector at verification; any advancement requires a new export. CUTOVER must consume a fresh verified result while source writes are held.

## Failing test to write first

New file: `tests/test_transfer_manifest.py`; name: `test_complete_revision_fenced_transfer_readback`. The proposed API and refusal codes are the contract this test drives.

```python
from copy import deepcopy
from pathlib import Path
import unittest

from herzchen.contracts import ResourceRef
from herzchen.kernel.store import Store
from otto.portfolio.fixtures.project_folder import ProjectFolderProof
from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.transfer_manifest import (
    capture_manifest, manifest_digest, verify_manifest,
)


class TransferManifestTests(ProjectFolderProof):
    def test_complete_revision_fenced_transfer_readback(self):
        created = self.import_files(
            key="program",
            files={"docs/a.md": "first body", "docs/b.md": "second body"},
        )
        opened = self.open(created["project_ref"], key="program-open")
        edited = self.checkin(
            opened,
            [{"operation": "edit", "path": "docs/a.md",
              "content": "second revision body"}],
            key="program-edit",
        )
        project = self.owner.graph.current(ResourceRef.from_dict(edited["project_ref"]))
        tasks = [
            {"id": f"T{i:03}", "title": f"Task {i}", "instructions": f"Do {i}",
             "acceptance": f"Accept {i}",
             "dependencies": [f"T{i-1:03}"] if i else []}
            for i in range(121)
        ]
        applied = self.owner.sheet.apply(
            project.ref, {"tasks": tasks}, base_revision=project.ref.revision,
            logical_request_key="program-tasks",
        )
        required = {"program": applied.project.ref.to_dict()}
        required.update({
            f"followup-{i}": self.create(key=f"followup-{i}")
            for i in range(1, 8)
        })
        required["r4"] = self.create(key="r4")
        required["other-upcoming"] = self.create(key="other-upcoming")

        source = PortfolioOwnerBootstrap(
            self.store, binding=self.owner.binding, owner_actor="owner",
            operator_actor="fixture-operator",
            project_read_grant=ProjectReadGrant(
                self.owner.owner_actor, tuple(ref["id"] for ref in required.values()),
                "transfer-fixture", "1",
            ),
        )
        manifest = capture_manifest(source, required, actor="owner", page_limit=3)
        self.assertEqual(len(manifest["pages"]), 4)
        self.assertEqual(len(manifest["projects"]), 10)
        self.assertEqual(len(manifest["projects"]["program"]["snapshot"]["tasks"]), 121)
        self.assertEqual(len(manifest["projects"]["program"]["snapshot"]["documents"]), 2)

        target_store = Store.create(self.root / "target.sqlite", authority="target-fixture")
        target_store.register_domain_handler(self.domains)
        self.addCleanup(target_store.close)
        binding = HerzchenBindingConfig("target-fixture", "fixture-credential")
        target = PortfolioOwnerBootstrap(
            target_store, binding=binding, owner_actor="owner",
            operator_actor="fixture-operator",
        )
        destination = OttoPortfolio(target.consumer_operations())
        imports = {
            alias: destination.import_project(
                entry["snapshot"], actor="owner", request_id=f"transfer:{alias}"
            )
            for alias, entry in manifest["projects"].items()
        }
        self.assertTrue(all(row["outcome"] == "imported" for row in imports.values()))
        self.assertTrue(any(
            row["source_revision"] != row["target_revision"]
            for row in imports["program"]["content_provenance"]["restored_documents"]
        ))
        target_read = PortfolioOwnerBootstrap(
            target_store, binding=binding, owner_actor="owner",
            operator_actor="fixture-operator",
            project_read_grant=ProjectReadGrant(
                binding.authenticated_actor("owner"),
                tuple(row["project_ref"]["id"] for row in imports.values()),
                "transfer-fixture", "1",
            ),
        )
        def check(candidate):
            return verify_manifest(
                candidate, source, target_read, imports,
                required=required, actor="owner",
            )

        good = check(manifest)
        self.assertEqual(good["outcome"], "verified", good)
        self.assertEqual(good["comparison"]["task_count"], 121)

        missing = deepcopy(manifest)
        last_alias = missing["pages"][-1]["aliases"][0]
        missing["pages"].pop()
        missing["projects"].pop(last_alias)
        missing["manifest_digest"] = manifest_digest(missing)
        refused = check(missing)
        self.assertEqual(refused["outcome"], "refused", refused)
        self.assertIn("incomplete_selection", {e["code"] for e in refused["errors"]})

        target.graph.revise(
            ResourceRef.from_dict(imports["program"]["task_refs"][1]),
            dependencies=[], logical_request_key="alter-target-dependency",
        )
        checkout = destination.checkout_project(
            imports["program"]["project_ref"], actor="owner",
            request_id="alter-target-body-open",
        )
        changed = destination.check_in_project(
            imports["program"]["project_ref"], actor="owner",
            request_id="alter-target-body", session_id=checkout["session_id"],
            project_json=checkout["project_json"],
            document_changes=[{"operation": "edit", "path": "docs/a.md",
                               "content": "altered target body"}],
        )
        self.assertEqual(changed["outcome"], "finished", changed)
        errors = {e["code"] for e in check(manifest)["errors"]}
        self.assertTrue({"dependency_mismatch", "document_body_mismatch"} <= errors)

        source_task = manifest["projects"]["program"]["snapshot"]["tasks"][0]["project_ref"]
        self.owner.graph.revise(
            ResourceRef.from_dict(source_task), title="Edited after export",
            logical_request_key="alter-source-task",
        )
        self.assertIn(
            "stale_source_revision",
            {e["code"] for e in check(manifest)["errors"]},
        )


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        TransferManifestTests("test_complete_revision_fenced_transfer_readback")
    ])
```

## Delete

Delete the exporter’s silent missing-record skips at [herzchen_binding.py:903](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:903), [herzchen_binding.py:915](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:915), and [herzchen_binding.py:947](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:947), and the importer’s silent unresolved document/link skips at [herzchen_binding.py:1176](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:1176) and [herzchen_binding.py:1238](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:1238). Keep raw folder export: it serves a different purpose.

## Likely mistake

A worker could hash the snapshots returned by export and compare import receipts. That would certify an omitted final page or a snapshot made before a task changed. The test removes the final page **and recomputes its digest**, then advances a source task independently of the project and changes target content and a dependency. Fresh owner reads must catch each case.

## Existing expectations and D19

No existing test assertion needs to change for this design. The small transfer/recovery proof at [project_folder.py:287](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/fixtures/project_folder.py:287) should still pass. If implementation changes any existing assertion, write the D19 decision before landing it. That proof currently patches `_link_document` at line 308 to simulate interruption; this conflicts with the stated test rule and should be replaced with a real failing command boundary when that proof is touched.

## Stale or unverified row references

`PATH-TO-CUTOVER`, program PLAN §14, XFERMAP, and CUTOVER’s six-follow-up list are absent from `canon/main`; the seven exact follow-up identities cannot be established from this checkout. The approved selection must supply them. On canon, [show.py:32](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/show.py:32) reads one page, while [intake.py:1044](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/intake.py:1044) hashes only selected task rows for a cursor; neither is a preservation gate. The current transfer exports only selected documents’ current revisions, and its link restoration changes bindings to `current`, so pinned historical bodies and bindings need explicit handling. No live inventory was read.