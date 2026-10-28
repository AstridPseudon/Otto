# Brief: TESTPATCH (normal, 1.0 focused days)

**Outcome:** Replace tests that patch the product path with owner-backed tests that exercise real Store hydration, asker authorization, operating-setup readiness, override composition, and fleet custody. Retain stand-ins only for people or models.

**Why it matters:** Tests that replace product methods can pass while the real owner path is broken. The canary must reject a current criterion that is outside T1's declared scope, and a foreign asker must be refused by the real authorization path.

**Your lab:** The launcher creates `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH` on branch `lab/TESTPATCH` from current `canon/main`. Work only in that lab.

**Layer:** Otto product. New tests and any product changes stay in their existing packages.

**Files you own:** `tests/test_hostctl_serve.py`, `src/otto/hostctl/serve.py`, `tests/test_ask_socket_wait.py`, `src/otto/portfolio/tests/test_execution_continuity.py`, `tests/test_hostctl_portfolio.py`, `tests/test_fleet_custody.py`.

**Other files:** You may edit directly required callers or fixtures outside that list; report each with its reason. Do not edit files under `production/`, any Store, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab. Other wave workers may touch adjacent code; the landing gate rebases each lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/TESTPATCH.md` first and follow its ordered steps, canary, and deletion list. The TRIAGE decision 4 scope is not specified here; do not invent scope beyond the design. If an expectation changes, isolate and report each changed assertion as `file:line`; those changes require written D19 before landing. Do not weaken existing assertions.

**Your check:** First demonstrate the new regressions fail on canon, then run the focused changed tests. Do not run staging-owner tests in the worker sandbox. Use the test files named in the design; a multi-file check is split by the landing gate into separate processes.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_serve.py tests/test_ask_socket_wait.py src/otto/portfolio/tests/test_execution_continuity.py tests/test_hostctl_portfolio.py tests/test_fleet_custody.py`

**Deletion budget:** Remove the invented identity, reader, scope, assessment, authorization, decisions, asking-session, cursor, readiness, `_compose_setup`, `FleetStub`, `FacadeServerStub`, and owner-port replacements listed in the design.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; the launcher commits on exit. Keep long tests running to completion. On Codex, any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report canon red runs, focused green runs, deletions, changed assertions requiring D19, additional files, and blockers.
