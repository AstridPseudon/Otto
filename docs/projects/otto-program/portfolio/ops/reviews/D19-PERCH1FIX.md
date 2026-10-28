# D19 decision: PERCH1FIX, tests/test_perch_stage1.py (the orchestrator, 16 Oct 2026)

**Decision: LAND.** No Opus call was made. The perch is the orchestrator's instrument, and this row rewrites it.

- **What changes:** the test removes its checks on the save's *reply* (the `task_refs` keys of `created`), and the fixtures of the one-task canary (event counts of 1/3/4, `store_events: 4`, a `read-back` of `{"outcome": "read"}`). It adds 106 lines for the three-task canary.
- **Why it's right:** PERCH1FIX's row (STAGE1 F2, F8a, F10; ASTRA1 F7) says the assertions read the Store snapshot, not the save's reply. It also says `tasks-are-typed-records` becomes Store-backed, the read-back goes through `show` on the owner lane, and each seeded fault corrupts the Store snapshot. The removed lines are exactly the reply-based checks and the old canary's numbers. The worker showed each new assertion failing under its own seeded fault (20 subtests).
- **Scope:** `tests/test_perch_stage1.py` only.
