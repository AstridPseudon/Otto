# Brief: STOPATOM (normal, 0.25 focused days)

**Outcome:** A stop request is published atomically with its complete reason and expected return, so the owner keeps serving until publication completes and then reports the requested explanation while draining and closed.

**Why it matters:** The filesystem control boundary must not expose a partial stop marker that halts the owner before its explanation is available.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product; this is Otto-specific stop control wiring.

**Files you own:** `tests/test_compose.py`, `src/otto/hostctl/cli.py`.

**Other files:** You may edit any other file directly required by the outcome, except files under Do not touch. Explain each addition in your report.

**Do not touch:**
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, and `tests/test_manager_journey_service.py` (GATESKIP);
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and CODEXOWNER's focused real-owner Codex journey tests;
- `tests/test_fleet_custody.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py` (LANDPROOF);
- `src/otto/portfolio/cli.py`, `tests/test_otto_open_release.py` (SAVEPATH);
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or files outside your lab.

**Build on what exists:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/STOPATOM.md` first and report any departure. Reuse `src/otto/hostctl/lanes.py:51` `atomic_json`, which writes a private same-directory temporary file, flushes and fsyncs it, then atomically replaces the destination. At `src/otto/hostctl/cli.py:915–916`, replace create-before-write stop marker publication while preserving whitespace normalization and response shape.

**Your check:** First add the prework regression to `tests/test_compose.py` (`CloseTests.test_stop_is_complete_at_publication_and_reaches_draining_and_closed`), then run the focused test module. The regression pauses publication and verifies the owner continues serving until the complete marker is atomically visible, then reaches draining and closed status with the requested reason and return. Run changed test files only; show canon-red and lab-green where feasible.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_compose.py`

**Callers, including production:** If changing a signature, constructor argument, or default, find and update every caller, including `install/controller/`.

**Existing tests:** Do not change an existing test's assertions without a written D19 decision. Never weaken a test to pass in the worker sandbox.

**Regression at the level the friction appears:** The publication boundary: before replacement the owner still serves; after replacement the draining and closed status contain the full stop explanation.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. On Codex, do not commit; the launcher commits when you exit. Give long test commands a long timeout and let them finish. If a check is blocked only by sandbox permissions, report it for the landing gate.

**On Codex:** Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
