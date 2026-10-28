# STAGE: the entry point gets a seam (resume message, the orchestrator's decision)

You found that `install/controller/shared_operating_service.py` is welded to the live install. You're right, and it's worse than paths: line 5 imports `operating_service` from the live controller folder `C` (line 4), so a staging start would run the live install's code, not `canon/main`'s. Decision: **give the entry point a seam; don't test `operating_service` directly.** The staging Otto exists to catch exactly the startup crash POOL caused in this file. You now lead this task as XHARD. Re-read the "XHARD only: you lead, Haiku executes" section of `~/Developer/otto-program/ops/brief-template.md` and delegate the execution to the `haiku-worker` sub-agent.

**First:** rebase `lab/STAGE` onto the current `canon/main`. Tests now run with no env prefix (`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>` from the lab, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose STAGE -- /opt/homebrew/bin/python3.11 -m pytest …`): TOOLING4 put `pythonpath` in `pyproject.toml`.

**The seam:**
- Each live location becomes an environment override, and its default is today's literal, byte for byte: the controller folder `C` (line 4), which also decides where `operating_service` is imported from; `PRIVATE` (line 19); the sibling controllers `VC` and `PC` (lines 20–21); and the host installation home `~/.otto` (line 581).
- Staging sets them all to folders under `~/Developer/otto-claude-host/labs/_staging`, with `C` pointing at the lab's own `install/controller`. Sibling controllers that don't exist there are skipped, not required.
- The exact-installation check (line 582: `max_active_manager_turns == 3`) stays. Staging writes an installation file that satisfies it.

**Invariant:** with no overrides set, the entry point resolves exactly the same paths and imports the same code as today. The live install is deployed from this file at CUTOVER, so a changed default breaks production. **The plausible mistake:** a default that is computed rather than literal (from `HOME`, the cwd or `__file__`), which matches on this machine today and then drifts.

**Checks:**
- a test that, with the overrides unset, the resolved values equal the old literals (read them from `git show 9739a29:install/controller/shared_operating_service.py`, not from a copy in the test);
- a test that, with the overrides set to a temp folder, nothing under `~/Documents/Codex`, `~/.codex` or `~/.otto` is opened (patch `open` and `Path` reads, or run the composition with `HOME` pointed at the temp folder and assert those three paths were never touched);
- the row's own: `startup_on_empty_store`, `restart_after_kill_recovers`, `no_leftovers_after_stop`, and the ASTRA0 line: the running sha is reported, and the staging Store and socket differ from the live ones.

**Files:** `install/controller/shared_operating_service.py` (only the seam: POOL is also changing line 411 of this file, and STAGE lands after POOL), `ops/bootstrap/staging.sh`, and your tests. Never start anything against the live owner, its Store or `~/.otto`.

Commit to `lab/STAGE`, don't push, and report: the commits, the runs, and anything you couldn't finish.
