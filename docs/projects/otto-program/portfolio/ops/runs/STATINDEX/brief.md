# Brief: STATINDEX (normal, 0.5)

**Outcome:** Project status uses project-scoped indexed selectors while preserving all selected-project rows and physical-schema admission rules.

**Why it matters:** Status reads should find child records through declared project-key indexes instead of scanning unrelated payloads.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STATINDEX`, on branch `lab/STATINDEX`, from `canon/main`. Work only here.

**Layer:** Otto product. New product wiring belongs in `src/otto/`; reusable selectors and schema declarations belong in Herzchen.

**Files you own:**
- `src/herzchen/kernel/schema.py`
- `src/herzchen/kernel/store.py`
- `src/otto/hostctl/product_service.py`
- `src/otto/portfolio/status.py`
- `tests/test_portfolio_status.py`
- `tests/test_indexed_identity_lookup.py` only if required by the declared index set; do not change existing expectations without D19.

**Other files:** You may edit another file only when the outcome directly requires it; list each additional path and why.

**Do not touch:**
- `src/otto/portfolio/manager_journey_service.py` and `tests/test_manager_journey_service.py` (active FAILEDFENCE landing); files owned by running OPPRE; any files owned by another task.
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Reuse `Store.prepare_identity_lookup_indexes()`, `Store.verify_physical_schema()`, existing due-record project index, and the single shared status reader. The reviewed design is `${TRANSFER_ROOT}/portfolio/ops/prework/STATINDEX.md`; its paths and cited lines were checked against canon/main.

**Your check:** First add the regression that captures the four real status queries and their `EXPLAIN QUERY PLAN` output with 10,000 foreign records. Establish the failing plan before changing code. Declare three optional expression indexes for task, assignment, and report project keys; route only the four known selectors through fixed literal kind/JSON expressions and `INDEXED BY` when the optional indexes exist, retaining the generic fallback otherwise. Prepare indexes after admitted Store.open while startup holds the exclusive owner lock. Compare results with the pre-index reference and retain all selected-project rows. Do not change existing assertions without a written D19 decision.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_portfolio_status.py tests/test_indexed_identity_lookup.py`

**Regression at the level the friction appears:** Query-plan assertions must prove project-key searches, with result parity against the generic reader.

**Deletion budget:** Replace the bound-path selector for the four indexed cases; retain it as the generic fallback. Add no second status reader.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Run tests in the foreground and to completion. Never weaken tests for sandbox failures. Do not run tests that start a staging owner in the worker sandbox. On Codex, leave changes uncommitted for the launcher. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
