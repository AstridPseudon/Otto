# Brief: STAGE (normal, 0.5 focused days)

**Outcome:** a staging Otto exists and can be run safely. It is a fresh, empty Otto instance built from `canon/main`, started through the production entry point (`install/controller/shared_operating_service.py`), with its own Store and socket under `~/Developer/otto-claude-host/labs/_staging`. It is never a clone of the live Store and never the live install. `ops/bootstrap/staging.sh` has four verbs: `up`, `down`, `restart` and `wipe`. `restart` moves the staging tree to the current head of `canon/main`, then restarts. A startup test in the suite composes the production service on a temporary folder, inertly, then stops it. When it's done, the staging Otto starts on an empty Store, a kill and restart recovers, and nothing is left behind after a stop.

**Why it matters:** every later landing is checked on staging (PLAN.md D17, §16). The owner's POOL startup crash on 15 Oct was invisible to every test because no test starts the production service.

**Your lab:** `~/Developer/otto-claude-host/labs/STAGE`, on branch `lab/STAGE`, from `canon/main` at `07354e2`. Work only here.

**Layer:** Otto product (PLAN.md D14, §11). Bootstrap and install code, not Herzchen. The test: this is about running the Otto product, not the fleet, so it lives in Otto's ops and tests.

**Files you own:**
- `ops/bootstrap/staging.sh` (new);
- `tests/test_staging_startup.py` (new).

**Do not touch:**
- `install/controller/shared_operating_service.py`, `src/otto/portfolio/execution_host.py` and any other file POOL or HOSTKIT is editing (POOL is in flight). If production startup refuses an empty Store, or needs a change in those files, stop and report the exact coupling (file, line, error) in your report. Don't edit them.
- other tasks' files;
- `production/`;
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- the running Otto service and `ottoctl`: never pass `ottoctl` `--help`, never write to it;
- anything outside this lab, except the staging folder named above.

**Build on what exists:** `install/controller/shared_operating_service.py` (the production entry point; read how it composes the service and what it takes as arguments); `ops/bootstrap/common.sh` for shell conventions (`die`, paths, `valid_task`); `tests/` for how existing tests build a temporary Otto root.

**Your check.** Make it green and keep everything else green:
- the new startup test (`tests/test_staging_startup.py`): `startup_on_empty_store`, `restart_after_kill_recovers`, `no_leftovers_after_stop`;
- show the red run first (a test that fails before `staging.sh` and the startup path exist), then green;
- every test file that imports a module you changed, each run on its own (the landing gate runs them twice). If you change no module under `src/`, this is only your own new test file;
- heavy commands go through `otto-heavy --weight N --purpose "STAGE" -- <cmd>`.

**Check command:** `PYTHONPATH=src:tests ~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "STAGE check" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_staging_startup.py`

**Callers, including production:** this task adds no constructor argument or signature change. If it finds that startup needs one, stop (see "Do not touch").

**Existing tests:** don't change what an existing test asserts.

**Regression at the level the friction appears:** n/a: feature task.

**Deletion budget:** none. `staging.sh` is new, and it retires in DELETE after CUTOVER, not now.

**Safety rules for the staging Otto:**
- Use only a temporary folder, or `labs/_staging`, for any Store, socket or log. Never a path under `~/.otto`, `~/.codex`, `~/Documents` or iCloud.
- Every process the test or `staging.sh` starts must be stopped by the test's teardown and by `staging.sh down`. A leftover process is a failure.
- If a command would touch the live owner or a live socket, stop and report it instead.

**Working rules:** commit work in progress to `lab/STAGE` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`.

**When done:** commit to `lab/STAGE` and don't push. Report the commit, the check runs (red, then green), what you deleted (none), any coupling you found and didn't fix, and anything you couldn't finish.
