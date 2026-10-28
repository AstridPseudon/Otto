# STAGE: staging starts through the product entry point (the orchestrator's decision on your blocker)

You were right: the onboarding entry point (`install/controller/shared_operating_service.py`) is the old install's wrapper for one onboarding project (`canonical-state.json`, pinned files, the 3/2/3 policy), so it can't compose on an empty Store, whatever its paths. It can't host the new live Otto at CUTOVER either. **Decision:** staging, and the new live Otto at CUTOVER, start through the product's own entry point: `ottoctl install` on a fresh `OTTO_HOME`, then `ottoctl service run` (`cmd_service_run` → `OwnerService`, `src/otto/hostctl/cli.py:743`). The onboarding wrapper retires with the old owner at CUTOVER. You still lead as XHARD and delegate the execution to `haiku-worker`.

**First:** rebase `lab/STAGE` onto the current `canon/main`, then **drop the seam commit 55d5d1d** (`git revert` or rebase it out): STAGE no longer changes `shared_operating_service.py`. Keep `staging.sh` (7144db6) and repoint it.

**Build:**
- `ops/bootstrap/staging.sh up|down|restart|wipe`: `OTTO_HOME=~/Developer/otto-claude-host/labs/_staging/home`, `ottoctl install` there if not installed, then `ottoctl service run`, detached, with its pid recorded. Run canon's own code, not any installed `ottoctl`: `/opt/homebrew/bin/python3.11 -c 'import sys; from otto.hostctl.cli import main; sys.exit(main())' …` with a `canon/main` checkout's `src` first on `PYTHONPATH` (there is no `__main__` module), and report the sha it ran; `down` uses `ottoctl service stop` and waits for the process to go. It never reads or writes `~/.otto`, `~/.codex` or `~/Documents/Codex`. Never pass `--help` to `ottoctl`.
- A startup test in the suite: compose `OwnerService` on a temp home (install, start, confirm it serves, stop), inert: no provider calls, no Due started.

**Checks (the row's):** `startup_on_empty_store`, `restart_after_kill_recovers`, `no_leftovers_after_stop`; and the ASTRA0 line: the running sha is reported, and the staging Store and socket paths differ from the live ones (`~/.otto-clients/claude-code/lanes/claude-code/status.json` names the live ones). Tests run as `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>` with no env prefix.

**Also, in your report, an inventory (don't build any of it):** what `shared_operating_service.compose` (line 345 on) gives the live owner that `OwnerService` doesn't: for example `CurrentProjectServices`, the schedule and closeout observers, host admission, Codex's caller address (`native_caller_address.py`), the manager-turn limit. One line each: what it does, `file:line`, and "the product needs it" or "onboarding-only", with the evidence. The orchestrator places the gaps.

**Files:** `ops/bootstrap/staging.sh`, your tests, and at most a small fix in `src/otto/hostctl/` if `OwnerService` itself refuses an empty home (say which line and why). Never start anything against the live owner, its Store or `~/.otto`.

Commit to `lab/STAGE`, don't push, and report: the commits, the runs, the inventory, and anything you couldn't finish.
