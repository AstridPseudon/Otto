Implemented portable provenance parity in [test_evidence_lifecycle.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/test_evidence_lifecycle.py), [record_astrid_provenance.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/fixtures/managed_source_provenance/record_astrid_provenance.py), and [recorded_source.json](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/fixtures/managed_source_provenance/recorded_source.json).

The regression failed before the change on the root-bound inventory identity comparison. It now checks two independently rooted checkouts, confirms a comment-only loader edit preserves provenance, exercises cleanup after setup and assertion failures, and retains tamper refusal. The recorder and checkout setup use temporary directories.

I also removed the two stale, checked-in checkout payload files because the new cleanup contract requires no fixture checkout to remain:

- `tests/fixtures/managed_source_provenance/checkout/src/herzchen/packs/evidence_resource_pack/pack.yaml`
- `tests/fixtures/managed_source_provenance/checkout/src/herzchen/packs/evidence_resource_pack/policy.json`

The specified check passes: **10 passed, 14 subtests passed**. `git diff --check` passes. No production admission code changed; nothing was committed or pushed.