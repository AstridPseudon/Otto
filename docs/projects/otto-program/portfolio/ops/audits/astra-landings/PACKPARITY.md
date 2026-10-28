DEFECTS — PACKPARITY only partially delivers its row; the boundary remains incomplete and the recorded parity test is not portable.

1. **The parity test depends on its recording checkout’s absolute path.**  
   `tests/fixtures/managed_source_provenance/record_astrid_provenance.py:73–83` records the inventory identity before making `pack_root` relative. `src/herzchen/packs/authoring.py:684–718` hashes records containing the absolute root. Yet `tests/test_evidence_lifecycle.py:405–424` substitutes the current checkout’s root and expects the unchanged recorded hash. Moving the checkout therefore changes the actual identity and fails the test despite identical pack bytes. Still present on `canon/main`.
   
   **Fix — normal:** Separate portable recorded hash vectors from filesystem admission checks; retain an independent Astrid-derived expectation rather than calculating it through the implementation under test. Files: recorder, recorded fixture, lifecycle tests. **Failing test:** exercise identical fixture content under two different temporary checkout roots and validate each against its correctly rooted provenance.

2. **Herzchen still names Otto, and the new boundary test permits it.**  
   `src/herzchen/usage/contract.py:20` retains `"otto.usage-cost.contract.v1"`; `:189` retains `"otto.usage.installed-codex-cli.v1"`; `:174` contains `src/otto/...` paths. `tests/test_herzchen_boundary.py:36–59` detects product imports and machine paths, but never product names in ordinary strings. Consequently, `PRODUCT = 'astrid'` passes. This directly misses the row’s requirement to refuse product names throughout non-test Herzchen source. Still present on `canon/main`.
   
   **Fix — normal:** Move remaining product-owned metadata into Otto or make it neutral, preserving existing wire compatibility at the product boundary. Extend the boundary scan. **Failing tests:** separate doctored files containing an Otto literal, an Astrid literal, an Otto source path, and `Documents/Codex`; each must be rejected.

3. **The parity fixture freezes the implementation’s Git identity, causing unrelated edits to fail and leave files behind.**  
   `tests/test_evidence_lifecycle.py:126–135` copies and commits the current `authoring.py`; `:417` compares that commit with a fixed recorded revision. A comment-only loader edit changes the commit and fails before provenance is inspected. Cleanup begins only at `:428`, so that failure leaves the copied module and nested `.git` behind. Still present on `canon/main`.
   
   **Fix — normal:** Delete the live implementation from the frozen fixture commit’s inputs; use immutable fixture content and temporary checkout setup with cleanup covering every assertion. **Failing tests:** a comment-only loader change must preserve parity, and a forced setup/assertion failure must leave the source checkout untouched.

Static test assessment: the new keyword arguments make tests fail against the parent implementation, but the parity test can fail earlier for irrelevant fixture reasons. Its expected provenance is recorded independently; it patches `__file__`, not a product method, and adds no timer waits. No further over-engineering finding is supported.

Verified against `canon/main` at `eb9b6cd`, including independent checks of the Luna reviewers’ findings. No tests or Otto commands were run; no files were changed.