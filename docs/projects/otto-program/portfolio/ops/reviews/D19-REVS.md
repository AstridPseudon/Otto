# D19 decision: REVS's 28 test lines (recorded by the manager, 16 Oct 2026-10-16T14:34:57Z)

**Decision (the orchestrator, 14:34Z): LAND.** No Opus call was made.

- **What changed:** 28 test and fixture lines, `graph.get(` → `graph.current(`. No expected value and no assertion was changed.
- **Why it's right:** before REVS, `get` ignored the revision, so it returned the head. Each test read the head before REVS, and `current` keeps exactly that. The rename preserves what each test read.
- **Maybe-vacuous tests:** `test_existing_project_orchestration.py` 101–166 and `test_project_queue.py` 114, 209 are no weaker than before the change.
- **Rule:** existing assertions are not weakened, and a test that reads the head still does.

**Re-checked by the orchestrator at 2026-10-16T15:57Z, lab at 3edf645 (the resumed run renamed more lines):** across the existing test files the gate listed, 98 lines were removed and 98 added. They are identical once `.current(` is normalised to `.get(`, so every change is the head-read rename and nothing else. The decision above covers all of them. LAND.
