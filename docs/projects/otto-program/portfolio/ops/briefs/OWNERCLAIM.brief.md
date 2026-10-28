# Brief: OWNERCLAIM (xhard, 0.5 focused days)

**Outcome:** Nothing launches before the owner holds custody of its home.

**Why it matters:** A refused or held startup must not run retained queued work, and two Stores under one home must not both serve its host directory.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet. The home-scoped custody and runner admission behavior belongs in the shared fleet/product startup boundary; keep Otto-specific wiring in Otto.

**Files you own:** `src/otto/hostctl/product_service.py`, `src/herzchen/fleet/runner/runner.py`, `tests/test_compose.py`; add or adjust focused tests as needed for the two-starter case.

**Other files:** You may edit any other file the outcome directly requires. The orchestrator authorized edge overlaps in this wave; the landing gate rebases each lab. Explain each additional file in your report.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or files outside your lab. Avoid unrelated work in files currently touched by SESSIONFD, FAILEDFENCE, REWORKWIRE, DRAINSETTLE, and PINALL.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/OWNERCLAIM.md` first. Follow its implementation order and invariant; report any departure.

**Your check:** Add the retained-queue refusal regression first and prove it fails on canon, then passes. Cover held then normal restart of the same queued record, and two starters using one home with distinct valid Stores: exactly one serves, and the loser does not alter the first owner's file or socket or reach composition. Preserve startup recovery before host intake.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_compose.py`

**Invariant:** Nothing launches before the owner holds custody of its home. Avoid opening request intake with the claim so retained Due records run before startup recovery. Surfaces: a refused or held startup has already run work (UPGRADE, restarts after CUTOVER).

**Deletion budget:** Delete the early `runner_core.start()` and make `pump()` inert until started. Do not add a second owner-file claim or a second process registry.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report commit, red and green checks, deletions, additional files changed, and any blocker. Stop and report if the brief contradicts canon or the outcome is unclear.
