# D19 decision: CONV, tests/test_otto_save.py:279 (the orchestrator, 16 Oct 2026)

**Decision: LAND.** No Opus call was made.

- **What changes:** the existing refusal test drops its case asserting that `otto save` refuses nonempty `documents` (ASTRA1 F2, `save.py:33`).
- **Why it's right:** CONV's row (narrowed 16 Oct 18:17Z) is exactly that a save carries a task's brief documents, so the old refusal is the behaviour the row removes. The new regression asserts the replacement: a save with documents round-trips through `show`. The worker showed it red on canon (1 failed, 20 passed) and green in the lab (21 passed).
- **Scope:** only this case. The test's other refusal cases are unchanged.
