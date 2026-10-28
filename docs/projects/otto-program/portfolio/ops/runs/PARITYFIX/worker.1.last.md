Implemented the D19 Restore. The immutable fixture pack is separate from production; its manifest digest is preserved as `ca177262…cb94`, and its tree digest as `0aa7039e…a9155`. The pack-only revision is `97cfaebc280e24ebffa9fc727bd1af327521fbe0`.

The recorder verified the canonical inventory preimage against pinned Astrid (`f42eaa6db62d989fc869da7219d76493e932869c`) at two roots. The lifecycle test substitutes each checkout root, hashes the recorded preimage, and compares the complete expected provenance record, including `source_inventory_identity`. Relocation, loader comment invariance, failure cleanup, and tamper refusal coverage remain.

Changed files:

- [test_evidence_lifecycle.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/test_evidence_lifecycle.py)
- [record_astrid_provenance.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/fixtures/managed_source_provenance/record_astrid_provenance.py)
- [recorded_source.json](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/fixtures/managed_source_provenance/recorded_source.json)
- [pack.yaml](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/fixtures/managed_source_provenance/immutable_pack/pack.yaml)
- [policy.json](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX/tests/fixtures/managed_source_provenance/immutable_pack/policy.json)

The requested test command completed: **10 passed**. `git diff --check` passed. Changes are left for the launcher to commit.