# Brief: PERCHUNTIME (normal, 0.5 focused days)

**Outcome:** Remove every elapsed-time cutoff from the stage-2 harness waits. Each wait must end when its required evidence appears or the staging owner dies. Extend the deadline-absence regression so it covers every `stage2_*` wait in `ops/bootstrap/perch.sh` and the stand-in socket client.

**Why it matters:** `PLAN.md` §17.5 requires the stage-2 journey to follow evidence, without arbitrary 180/90/45/30 second limits.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCHUNTIME`, on branch `lab/PERCHUNTIME`, from `canon/main`. Work only here.

**Layer:** proof. The change removes time limits from the staging proof harness and its regression test; product behavior stays in the product layer.

**Files you own:**
- `ops/bootstrap/perch.sh`
- `ops/bootstrap/perch_fake_claude.py`
- `tests/test_perch.py`

**Other files:** You may edit another file only when the outcome directly requires it; list it and the reason in your report.

**Do not touch:**
- SESSIONFD-owned files: `src/herzchen/command_ports.py`, `src/otto/owner.py`, `src/otto/owner_bootstrap.py`, and `tests/test_owner.py`;
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `ops/bootstrap/perch.sh` already has `stage2_wait_marker` as an evidence-driven polling pattern. Reuse it for the other waits. The current deadline checks are in `stage2_wait_admission_boundary` / `stage2_admit_tasks`; the stand-in timeout is in `ops/bootstrap/perch_fake_claude.py`.

**Your check:** Extend the deadline-absence test in `tests/test_perch.py` to cover every `stage2_*` function and `perch_fake_claude.py`, including a doctored deadline regression. Run the focused unit test file; stage 2 `--fake` is an outside-sandbox check.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Regression at the level the friction appears:** A deadline doctored into any stage-2 wait or the stand-in must be caught by the deadline-absence regression; the stage-2 `--fake` journey must pass.

**Working rules:** Follow the template's Codex rules: don't commit or push; the launcher commits on exit. Run tests to completion with a long timeout. Don't run staging-owner tests inside the worker sandbox. Never wait or use polling loops as a separate job.
