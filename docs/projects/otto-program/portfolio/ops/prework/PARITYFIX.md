## Design

1. [tests/test_evidence_lifecycle.py:108](${TRANSFER_ROOT}/source/otto/tests/test_evidence_lifecycle.py:108) → Make `_prepare_recorded_provenance_checkout(destination)` copy only the checked-in pack bytes into the caller’s temporary destination. Create and commit Git there with fixed metadata and the recorded remote. Return the destination, the *location hint* `src/herzchen/packs/authoring.py`, and the revision. Do not copy the live loader or write into the checked-in fixture.
2. [record_astrid_provenance.py:20](${TRANSFER_ROOT}/source/otto/tests/fixtures/managed_source_provenance/record_astrid_provenance.py:20) → Record from temporary checkouts containing those same immutable pack bytes. Use pinned Astrid to retain the revision, manifest digest, and tree digest. Record a canonical inventory preimage with an `@PACK_ROOT@` token; verify its hash against Astrid’s inventory identity at two roots before saving it.
3. [recorded_source.json:1](${TRANSFER_ROOT}/source/otto/tests/fixtures/managed_source_provenance/recorded_source.json:1) → Refresh the revision for the pack-only commit. Keep portable source fields and relative paths; replace the fixed, root-bound inventory identity with that verified preimage template.
4. [tests/test_evidence_lifecycle.py:395](${TRANSFER_ROOT}/source/otto/tests/test_evidence_lifecycle.py:395) → Replace the existing parity test with the test below. Keep setup, loading, tampering, and assertions inside temporary-checkout cleanup. Add a separate regression that fails Git commit during setup and deliberately raises an assertion after setup; after each failure, check that the temporary checkout is gone and the checked-in fixture has neither `.git` nor a generated `authoring.py`.

No production change is indicated: [authoring.py:684](${TRANSFER_ROOT}/source/otto/src/herzchen/packs/authoring.py:684) roots the configured record, and [authoring.py:718](${TRANSFER_ROOT}/source/otto/src/herzchen/packs/authoring.py:718) hashes that rooted inventory. Its Git and resource-byte admission checks should remain intact.

## Failing test to write first

Replace `EvidenceLifecycleTests.test_native_source_provenance_matches_recorded_astrid_fixture_field_by_field` in `tests/test_evidence_lifecycle.py` with:

```python
def test_native_source_provenance_matches_recording_at_two_roots(self):
    from herzchen.packs import authoring

    fixture_dir = Path(__file__).parent / "fixtures" / "managed_source_provenance"
    recording = json.loads(
        (fixture_dir / "recorded_source.json").read_text(encoding="utf-8")
    )
    portable = recording["source"]
    observed = []

    with tempfile.TemporaryDirectory() as temporary:
        for label in ("first", "second"):
            destination = Path(temporary) / label
            repo_root, module_path, revision = (
                _prepare_recorded_provenance_checkout(destination)
            )
            self.assertEqual(repo_root, destination)
            self.assertEqual(revision, portable["revision"])
            self.assertFalse(module_path.exists())  # No live loader bytes in the commit.

            pack_root = repo_root / portable["pack_root"]
            state_record = {
                **portable,
                "pack_root": str(pack_root.resolve()),
            }
            state_path = Path(temporary) / f"{label}-sources.json"
            state_path.write_text(json.dumps({
                "version": 1,
                "active": {portable["pack_id"]: state_record},
                "cached": {},
                "disabled": [],
            }), encoding="utf-8")

            template = recording["inventory_canonical_template"]
            self.assertEqual(template.count("@PACK_ROOT@"), 1)
            preimage = template.replace(
                "@PACK_ROOT@", json.dumps(str(pack_root.resolve()))
            )
            expected = {
                "pack_id": portable["pack_id"],
                "source_kind": portable["source_kind"],
                "source_revision": portable["revision"],
                "source_tree_sha256": portable["tree_sha256"],
                "source_manifest_sha256": portable["manifest_sha256"],
                "source_inventory_identity": hashlib.sha256(
                    preimage.encode("utf-8")
                ).hexdigest(),
                "pack_root": str(pack_root.resolve()),
                "manifest_path": str(
                    (repo_root / recording["manifest_path"]).resolve()
                ),
            }
            with patch.object(authoring, "__file__", str(module_path)):
                managed = read_managed_pack(
                    portable["pack_id"],
                    project_root=repo_root,
                    source_state_path=state_path,
                )
            actual = managed.source.to_dict()
            self.assertEqual(set(actual), set(expected))
            for field, value in expected.items():
                with self.subTest(root=label, field=field):
                    self.assertEqual(actual[field], value)
            observed.append(actual)

            if label == "second":
                policy = pack_root / "policy.json"
                policy.write_bytes(policy.read_bytes() + b" ")
                with patch.object(authoring, "__file__", str(module_path)):
                    with self.assertRaises(PackAuthoringError):
                        read_managed_pack(
                            portable["pack_id"],
                            project_root=repo_root,
                            source_state_path=state_path,
                        )

        self.assertNotEqual(observed[0]["pack_root"], observed[1]["pack_root"])
        self.assertNotEqual(
            observed[0]["source_inventory_identity"],
            observed[1]["source_inventory_identity"],
        )

    fixture_checkout = fixture_dir / "checkout"
    self.assertFalse((fixture_checkout / ".git").exists())
    self.assertFalse(
        (fixture_checkout / "src/herzchen/packs/authoring.py").exists()
    )
```

## Delete and decision

Delete the helper’s deletion/recreation of the checked-in fixture’s `.git`, its copy of live `authoring.py`, and the test’s late manual `finally` cleanup. Delete the fixed `source_inventory_identity` and `fixture_root` fields from the recording.

A plausible mistake is relocating `pack_root` while retaining the old inventory hash. The two roots require different independently expected hashes, so the test catches it. Copying the live loader into the fixture is caught by the absent-file assertion and would also change the pinned revision after a comment-only loader edit.

**D19:** The existing parity test changes its revision and inventory-identity expectations because the commit will contain only immutable fixture bytes and the inventory hash is root-specific. Record a written D19 decision for `tests/test_evidence_lifecycle.py`. No other existing test expectation needs to change.

The row’s line references are current. Its `authoring.py` references point to correct root-bound behavior, not a demonstrated production defect. `PACKPARITY 1, 3` is not present as a named row on `canon/main`, so I could not verify that cross-reference. This was read-only; I did not run tests.