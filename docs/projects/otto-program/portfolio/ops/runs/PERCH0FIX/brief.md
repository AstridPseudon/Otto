# Brief: PERCH0FIX (normal, 1.0 focused day)

**Outcome:** the stage 0 perch checks what stage 0 claims. Status, kill and restart after a kill, a refused start, the Store's contents, and staging at rest are each checked by a real assertion, and each seeded fault turns one red. The full row is `PERCH0FIX` in `~/Developer/otto-program/projects/program/tasklist.md` (line 54). Read that row first. Its acceptance evidence is the contract.

**Why it matters:** the STAGE0 review (`~/Developer/otto-program/ops/reviews/STAGE0.md`, findings F2, F3, F4, F5 and F7) found that stage 0 passed without checking the things it claimed. It must land before the stage 1 review.

**Your lab:** `~/Developer/otto-claude-host/labs/PERCH0FIX`, on branch `lab/PERCH0FIX`, from `canon/main` at `1b91364`. Work only here.

**Layer:** Otto product (PLAN.md D14, §11). This is ops tooling, not Herzchen. Nothing goes in `src/herzchen`. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `ops/bootstrap/staging.sh`, `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, and anything else under `ops/bootstrap/` that the row names (`canary/`, `CENSUS_MARKERS` in the common file);
- `tests/test_perch.py` and `tests/test_perch_timeline.py`, plus any new `tests/test_perch*.py`.

**Do not touch:**
- `~/Developer/otto-program/` (read-only for you: the review and the tasklist are there);
- `labs/_staging`, the live owner, `~/.otto`, `~/.codex`, `~/Documents/Codex`;
- any other task's lab or files;
- `ops/` in the otto-program repo, except to read it.

**Staging is shared. Do not run it on the shared root.** `labs/_staging` is used by the landing gate and by the orchestrator's stage runs. For every staging run you make, set both:
- `OTTO_STAGING_ROOT` to a scratch directory you create under your own temp space (never `labs/_staging`);
- `OTTO_STAGING_REF=refs/heads/lab/PERCH0FIX`, so the run tests your lab's commit, not `canon/main`.

If a run would touch the live owner, `labs/_staging`, or anything outside your scratch root, stop that run and report it. Do not run `perch.sh 0` against the shared root, and do not run `staging.sh restart` against it.

**Build on what exists:** `ops/bootstrap/staging.sh` (the staging wrapper, which already takes `OTTO_STAGING_ROOT`), `ops/bootstrap/perch.sh` (already takes `OTTO_STAGING_REF` and `PERCH_OUT`), `ops/bootstrap/perch_report.py`, `ops/bootstrap/canary/` (`project.json`, `fake_worker.py`, `toy/`), and the existing `tests/test_perch.py` and `tests/test_perch_timeline.py`.

**Your check.** Make it green and keep everything else green:
- `cd ~/Developer/otto-claude-host/labs/PERCH0FIX && /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_timeline.py` (no env prefix; `pyproject.toml` sets pytest's `pythonpath`);
- the row's new assertions (`status_after_kill_is_stale`, `restart_after_kill_keeps_store`, `refused_start_names_its_reason`, `store_matches_stage`, `staging_at_rest_clean`) each have a test;
- for the seeded-fault check, run `perch.sh 0 --fake` with the scratch root and ref above. Each `PERCH_FAULT` kind must turn one assertion red. Show the red and green runs;
- regression tests must fail on `canon/main` first: show that run too;
- run only the test files you changed or added. The landing gate sweeps the rest, twice (D19).
- run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "PERCH0FIX check" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_timeline.py`

**Callers:** if you change a signature or default in `staging.sh`, `perch.sh` or `perch_report.py`, find every caller and update it, including the landing gate (`ops/bootstrap/land.sh`), which calls `perch.sh all --fake` and `staging.sh restart`. Keep those calls working.

**Existing tests:** do not change what an existing test asserts to make your change pass. If an expectation really must change, keep it in its own commit and give the reason in your report. It then needs an Opus decision (D19).

**Regression at the level the friction appears:** n/a: feature task (the perch itself is the check).

**Deletion budget:** the row says to delete `ottoctl` and `otto.hostctl` from `CENSUS_MARKERS`. Name it in your report.

**Working rules:** commit work in progress to `lab/PERCH0FIX` as you go. Never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on. Run tests in the foreground. If a question blocks you, decide it within this brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**When done:** commit to `lab/PERCH0FIX` and don't push. Report the commit, the check runs (red, then green), the seeded-fault results, what you deleted, and anything you couldn't finish.
