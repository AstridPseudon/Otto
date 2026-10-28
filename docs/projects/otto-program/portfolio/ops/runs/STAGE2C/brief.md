# Brief: STAGE2C (normal, 0.25 focused days)

**Outcome:** Stage 2's kill-recovery reaches C while C's fake worker is still held, kills it through perch, confirms its slot is freed and the census is clean, and continues to pass for A and B. The harness recognizes `unknown` dispatch state, while `unknown` for A or B still fails with its reason because those tasks must land.

**Why it matters:** The stage must test the owner's recovery from a kill the harness makes, not the owner's own worker timeout. If C times out first, the kill probe never runs and the journey gives false confidence about kill recovery.

**Your lab:** `lab/STAGE2C`, on branch `lab/STAGE2C`, from `canon/main` at the current canon head. Work only here.

**Layer:** Otto product. New code goes in `ops/bootstrap/`. Keep `tests/test_herzchen_boundary.py` green.

**Files you own:**
- `ops/bootstrap/perch_report.py`
- `ops/bootstrap/perch.sh`
- `tests/test_perch.py`

**Other files:** You may edit other files the outcome directly requires, except those under Do not touch. List each in your report with the reason.

**Do not touch:**
- The files of tasks running now: none known at launch; recheck before editing.
- `production/` (the Astrid film's folder; it means nothing for code).
- Any Store, `~/.otto` or `~/.codex`.
- Codex's projects, vision and Native5.
- Anything outside this lab.

**Build on what exists:** `stage2_wait_worker` and `stage2_kill_worker` in `ops/bootstrap/perch.sh` (around lines 350-450 and 650-665); `stage2_status_task` and `stage2_dispatch_no_failure` in `ops/bootstrap/perch_report.py` (around lines 332-350); `Stage2OwnerBootstrapTests` and stage-2 report tests in `tests/test_perch.py` (around lines 800-890 and 676-691).

**Your check:** Add unit coverage that an `unknown` A/B dispatch fails and preserves its reason, and that C's `unknown` state is recognized for the kill-recovery path. Make the fake journey arrange the kill while C is held, before A/B waits can consume C's timeout. First demonstrate new regression tests fail on canon, then pass on the change. The stage-2 `--fake` journey starts a staging owner and is not runnable in the worker sandbox; the landing gate runs it outside.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Regression at the level the friction appears:** Run stage 2 `--fake`: A and B land and complete in order; C is killed by perch while held, its slot is freed, and the census finds nothing leaked or wrongly killed.

**Working rules:** Follow `ops/brief-template.md`, including its Codex rules and long-test guidance. On Codex, do not commit; the launcher commits when you exit. Never run `ottoctl`, and never pass it `--help`. Never wait or poll. Do not run staging or owner-starting tests in the worker sandbox. Never weaken tests to pass in the sandbox. Report red and green runs, commit status, changed assertions, deletions/replacements, and anything unfinished.
