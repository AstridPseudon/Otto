# Brief: SAVEPATH (normal, 0.25 focused days)

**Outcome:** `otto save` reads the relative file from the thin client caller's current directory before forwarding it to the owner.

**Why it matters:** A caller saving from directory A must not accidentally submit a same-named but different file from the owner's directory B.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product; the thin client owns caller-side path resolution.

**Files you own:** `src/otto/portfolio/cli.py`, `tests/test_otto_open_release.py`.

**Other files:** Edit only files directly required by this outcome; report each addition and why.

**Do not touch:**
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `src/otto/agents/gateway.py`, `src/otto/agents/orchestrator_route.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/lifecycle.py`, `src/otto/engineering/release_records.py` and their direct tests/exports (DEADLAUNCH);
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py` and focused real-owner Codex journey tests (CODEXOWNER);
- `tests/test_fleet_custody.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py` (LANDPROOF);
- `src/otto/hostctl/lanes.py`, `src/otto/portfolio/client_lanes.py`, `src/otto/hostctl/service.py`, `tests/test_owner_lane.py` (RELAYSAFE);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Build on what exists:** Follow `ops/prework/SAVEPATH.md`. Resolve `parsed.file` using `Path(...).absolute()` in `client_main`, rebuilding save argv from parsed fields so options before the filename work. Preserve `_absolute_directories` behavior for other commands and mirror the owner-side save normalization in `src/otto/hostctl/portfolio.py:115-118`.

**Your check:** Add the real-owner caller-A/owner-B regression in `tests/test_otto_open_release.py` as specified by the prework. Demonstrate its failure before the change and pass after; run the changed file.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_open_release.py`

**Regression at the level the friction appears:** The client runs from caller directory A while the owner runs from B; both contain valid, different `project.json` files. Ensure options preceding the positional filename are covered.

**Existing tests:** Do not change existing assertions. Prework notes that successful save returns refs and stale conflicts return a diff; document persistence is a separate gap, so report this mismatch with the task row rather than silently broadening scope.

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long test runs running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests to pass in the worker sandbox.

**When done:** Report canon red and lab green runs, changed files, and any acceptance mismatch or blocker.
