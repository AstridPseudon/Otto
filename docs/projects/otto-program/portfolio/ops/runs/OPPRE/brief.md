# Brief: OPPRE (normal, 0.5)

**Outcome:** Missing operator authority refuses project creation before any reservation or receipt.

**Why it matters:** A project creation request must be attributable to an authenticated operator before creating project state or consuming its replay key.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPPRE`, on branch `lab/OPPRE`, from `canon/main`. Work only here.

**Layer:** Otto product. New code belongs in `src/otto/portfolio/` or the Otto wiring in `src/herzchen/domains/work/orchestration.py` as the design requires.

**Files you own:**
- `src/herzchen/domains/work/orchestration.py`
- `src/otto/portfolio/herzchen_binding.py`
- `src/otto/portfolio/owner_bootstrap.py`
- `tests/test_missing_operator_creation.py` (new)
- Any directly required creation-entrance tests among `tests/test_operator_admission.py` and related tests; report each additional path.

**Other files:** You may edit another file only when the outcome directly requires it; list each in your report and why.

**Do not touch:**
- Files owned by running LABPIN and the active FAILEDFENCE landing; do not edit files belonging to any other task.
- `production/`, Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Resolve operator identity before orchestration or authoring reservation, reuse that actor in creation callbacks, and retain existing authoring receipt/recovery behavior. The reviewed design is `${TRANSFER_ROOT}/portfolio/ops/prework/OPPRE.brief.md`; its paths and cited lines were checked against canon/main. In particular, remove the `actor` fallback for `operator_actor` in `orchestration.py`, guard create-and-open before writes, and keep existing-project save/attach available without an operator.

**Your check:** Write the missing-operator refusal/retry regression first. Cover ordinary pending, template pending, orchestrated pending, create-and-open, new-project save, and import through their real entrances. Missing authority must leave no project, authoring reservation, or request receipt; retrying the same key after configuring the operator must create once. Include the direct orchestration port so the fallback cannot hide behind a facade guard. Do not change existing assertions without a written D19 decision.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_missing_operator_creation.py tests/test_operator_admission.py`

**Regression at the level the friction appears:** Refusal before reservation/receipt followed by successful same-key retry.

**Deletion budget:** Delete the implicit `operator_actor or actor` fallback; do not add another authority source or compensating receipt path.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Run tests in the foreground and to completion. Never weaken tests for sandbox failures. Do not run tests that start a staging owner in the worker sandbox. On Codex, leave changes uncommitted for the launcher. A long test runs to completion; use a long timeout. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
