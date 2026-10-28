# D19 decision: SAVEFIX, tests/test_revisions.py:137 (the orchestrator, 16 Oct 2026)

**Decision: LAND.** No Opus call was made.

- **What changes:** REVS's new test asserts `batch_history` on the project payload. SAVEFIX's row (STAGE1 F8c; ASTRA1) says `batch_history` and `last_batch` leave the project record, and the per-save events carry the mapping instead.
- **Why it's right:** the assertion pins an incidental detail that the row removes on purpose. The test's subject, revisions being immutable snapshots, is unaffected. The replacement assertion reads the mapping from the save's event.
- **Scope:** only this assertion. Any other existing assertion SAVEFIX changes needs its own decision.
