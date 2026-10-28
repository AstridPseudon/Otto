# Brief: PERCH (normal, 0.75 focused days)

**Outcome:** `ops/bootstrap/perch.sh <stage or all> [--fake]` restarts the staging Otto on the commit under test, runs that stage's canary scenarios, and writes one report per run: `ops/perch/<stage>/<UTC time>/report.md`, with the raw data beside it. The report covers: each task's timeline from the Store (admitted, dispatched, lab, turns, checks, done, landed, lab deleted); a process census before and after (leaks and wrong kills); labs and scratch left over; the pool's units over time; Store growth per task and per save; the line's git history; tokens and cost per task; waits and durations, with disk and swap at the same moment. A canary project (a toy repo plus a project file) exercises every path. Assertions are plain checks over the report; a seeded fault must fail each kind of assertion.

**Why it matters:** Every landing from now on is checked on staging (D17, D19, D20). The report is what a stage review reads, so each finding turns into a fix task or a new automatic check. See PLAN.md §16, "The observation perch (PERCH, D20)".

**Your lab:** `~/Developer/otto-claude-host/labs/PERCH`, on branch `lab/PERCH`, from `canon/main` at `f3f792e`. Work only here.

**Layer:** Otto product for `perch.sh`, the canary project and the report renderer. Herzchen model for the task-timeline read: it lives in Herzchen's model on `EventCursorReader` (used today by `src/herzchen/domains/work/decisions.py:695`), so PERCH and `otto status` share one query. `perch.sh` only renders it. `tests/test_herzchen_boundary.py` must stay green. Put the timeline read in `src/herzchen/` and the rendering in Otto's bootstrap scripts.

**Files you own:**
- `ops/bootstrap/perch.sh` (new);
- the canary: a toy repo and a project file, under `ops/bootstrap/canary/` (new);
- the timeline read: a new module under `src/herzchen/domains/work/` on `EventCursorReader`;
- `tests/test_perch.py` (new), and any test file for the timeline read;
- `ops/perch/` is output, never committed.

**Do not touch:**
- other tasks' files (in particular `ops/bootstrap/land.sh`, which the manager owns);
- `production/`;
- any Store, `~/.otto` or `~/.codex`;
- the live owner or its socket;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:**
- `ops/bootstrap/staging.sh` (STAGE, landed): `up`, `down`, `restart`, `wipe`, started through `ottoctl service run` on `labs/_staging/home`. Use it for the restart; don't write a second one.
- `tests/test_staging_startup.py` (STAGE): the startup test. Read it before writing the canary.
- `herzchen/kernel` event cursor and `EventCursorReader` (`src/herzchen/domains/work/decisions.py:30, 695`).
- `ops/bootstrap/report.sh`, which already reads landings from git: reuse its git-history part rather than writing a second one.

**Your check.** Make it green and keep everything else green:
- `tests/test_perch.py`, plus the timeline-read tests you add, through `otto-heavy` as below;
- each assertion kind must fail on a seeded fault: a leaked process, a missing timeline event, a lab left behind, pool units over the limit. Show the red run and the green run;
- run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "PERCH" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`;
- every test file that imports a module you changed, each file on its own (the landing gate runs them twice);
- run the perch itself once, `bash ops/bootstrap/perch.sh 0 --fake`, and say where the report landed and what it contains. A real Haiku-worker run is not needed for stage 0.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Callers, including production:** the timeline read is new, so nothing calls it yet. If you change `EventCursorReader` or the decisions module, find every caller and keep it green.

**Existing tests:** don't change what an existing test asserts. If one must change, keep the change in its own commit and give the reason in your report; it then needs an Opus decision (D19).

**Regression at the level the friction appears:** a seeded fault for each assertion kind, shown to fail.

**Deletion budget:** the timeline read replaces the ad-hoc queries that `report.sh` and the status code would otherwise each write. Name any you remove.

**Working rules:** commit work in progress to `lab/PERCH` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. Don't start, restart or stop the live owner. Only staging may be restarted.

**When done:** commit to `lab/PERCH` and don't push. Report the commit, the check runs (red, then green), the perch report path from the `--fake` run, what you deleted, and anything you couldn't finish. Stop and ask (end your report with the question) if the brief contradicts the code.
