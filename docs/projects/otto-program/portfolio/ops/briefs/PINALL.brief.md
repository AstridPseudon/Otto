# Brief: PINALL (xhard, 0.75 focused days)

**Outcome:** Every native process is recorded before it gets input, and its slot frees exactly when its group is empty.

**Why it matters:** Missing process pins can leave workers orphaned after a crash, or leave capacity charged forever in long-running owners.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet. The row's runtime custody and process-group behavior belongs in Herzchen; keep Otto-specific wiring in Otto.

**Files you own:** Follow `${TRANSFER_ROOT}/portfolio/ops/prework/PINALL.md` for its implementation files and tests. The task row's identified surfaces are `src/otto/agents/claude_cli.py`, `src/otto/agents/claude_adapter.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/execution.py`, `tests/test_claude_manager_admission.py`, `tests/test_capacity_pool.py`, and `tests/test_capacity_holds.py`.

**Other files:** You may also edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report. The orchestrator has authorized edge overlaps among this wave; the landing gate rebases each lab.

**Do not touch:**
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab;
- the files owned by another task beyond the direct overlap needed for this row.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/PINALL.md` before editing. Follow its implementation order and exact failure and recovery invariant; report any departure.

**Your check:** Add the real-owner pin-failure regression first and prove it fails on canon, then passes. Cover initializer pinning and force-stop cleanup, empty-PGID slot release, and live-member retention. Update the obsolete expectations listed in the design; the orchestrator's D19 decision is recorded there. Do not weaken unrelated assertions.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_claude_manager_admission.py tests/test_capacity_pool.py tests/test_capacity_holds.py`

**XHARD:** Preserve the invariant that every native process is recorded before input and its slot frees exactly when its group is provably empty. Avoid freeing a slot after pin failure while a child may still run, or releasing it on a PID mismatch while a process-group member remains. Surfaces: orphaned workers after a crash and slots charged forever.

**Deletion budget:** Remove the initializer exclusion, swallowed pin failures, and leader-PID reuse branch identified in the design; do not add a second process registry.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report commit, red and green checks, deletions, additional files changed, and any blocker. Stop and report if the brief contradicts canon or the outcome is unclear.
