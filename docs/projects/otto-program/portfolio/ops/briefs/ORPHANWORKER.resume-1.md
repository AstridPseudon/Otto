# ORPHANWORKER resume 1 (same worker session)

**Outcome:** Complete the row's custody-safe worker cleanup and forced-down behavior. Follow the three corrections below exactly; retain birth-time checks and do not kill a live owner's workers before this owner has custody.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ORPHANWORKER`, branch `lab/ORPHANWORKER`, rebased onto current `canon/main` first. Work only here.

**Files you own:** `src/otto/agents/claude_cli.py`, `src/otto/portfolio/execution_host.py` (direct caller needed for the custody ordering), `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, and focused process-custody/staging tests. Keep the `perch_report.py` changes to ORPHANWORKER's cross-root census and start/down assertions; PERCH2C is editing the stage-2 assertion section in that file concurrently.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab. LABCAPTURE, KILLFENCE, COMPLETECITE and FAILCLOSED have landed; preserve their canon behavior while rebasing.

**Required corrections (Orchestrator 2026-10-17T16:50:44Z):**
1. The current start-time kill runs in `ExecutionHost.__init__` via `_terminate_recorded_process_groups()` immediately after `_load_process_groups()`, before `start()` claims custody. Move it into `start()` after the owner file is written and `_owns_owner_file = True`. Add a unit test where a live owner holds custody and a recorded worker group exists; constructing and starting a second `ExecutionHost` must raise `another execution host owns this command directory`, while the worker remains alive.
2. Graceful `close()` currently SIGKILLs running workers immediately after `begin_drain()`. Remove that first call and keep the final termination only after children have settled.
3. Forced `staging.sh down` does not call `close()`, so it must kill recorded groups itself. After forced stop, run the birth-checked `terminate_recorded_process_group` helper through the staging Python and print each group killed. Add a unit or script test proving force-down with a held fake worker leaves no worker alive.

Retain the row requirements: a stale PID whose birth time differs is left alone; the cross-root census detects live `perch-fake-claude` workers. Do not change KILLFENCE's capacity accounting or recovery behavior. Run focused checks and report the exact test files changed. Do not run staging-owner tests in the worker sandbox; the landing gate runs them.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_worker_custody.py tests/test_perch.py`

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave the work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
