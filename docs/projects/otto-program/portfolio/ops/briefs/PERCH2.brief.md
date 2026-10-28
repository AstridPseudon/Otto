# Brief: PERCH2 (normal, 0.75 focused days)

**Outcome:** Stage 2 runs on staging. Add a stage-2 entry in `ops/bootstrap/canary/project.json` with a three-task canary admitted, B depending on A, and one revision left unadmitted. Add an `admit-and-dispatch` staging scenario using the fake harness: the owner dispatches only admitted, ready tasks in dependency order; an unadmitted revision is refused; the pool and manager reserve hold; and killing a worker mid-task frees its slot without killing anything else. Add Store-snapshot and census assertions with one seeded fault per assertion, following stage 1. If COMPOSEFLEET has not landed, the scenario must say it was skipped; stage 2 passes only when it actually ran.

**Why it matters:** Stage 2 proves admission, dependency ordering, bounded dispatch, reserve protection and worker recovery on staging before later skeleton work depends on those guarantees.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2`, on branch `lab/PERCH2`, from `canon/main` at `812d06a86937873b15b6f1d5225873a5531930eb`. Work only here.

**Layer:** Otto product, bootstrap tooling. Keep changes in `ops/bootstrap/`; `land.sh` is outside scope.

**Files you own:**
- `ops/bootstrap/perch.sh`
- `ops/bootstrap/perch_report.py`
- `ops/bootstrap/canary/project.json`
- `ops/bootstrap/canary/fake_worker.py`
- `tests/test_perch.py`
- `tests/test_perch_staging.py`
- `tests/test_perch_timeline.py`

**Do not touch:**
- other tasks' files, especially `land.sh`;
- `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists:** Extend the stage runner and report CLI in `ops/bootstrap/perch.sh` and `ops/bootstrap/perch_report.py`, the stage-1 canary in `ops/bootstrap/canary/project.json`, and its fake worker and Store-backed assertion patterns. The task row in `projects/program/tasklist.md` is the acceptance contract.

**Your check.** Add focused tests for the stage-2 canary, admitted-only dependency-ordered dispatch, refusal of an unadmitted revision, pool and manager reserve bounds, worker-kill recovery, Store snapshots, census, and seeded faults. Each new assertion must turn red under its own seeded fault. Preserve stage 0 and stage 1 behavior. The landing gate runs changed-module sweeps and the real staging perch.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_staging.py tests/test_perch_timeline.py`

**Regression at the level the friction appears:** A stage-2 run must fail if dispatch includes an unadmitted or dependency-blocked task, exceeds pool/reserve limits, or fails to release a worker slot after a kill; each seeded Store/census fault must fail its matching assertion.

**Deletion budget:** Replace or extend the incomplete stage-1-only perch scenario and assertion path; name any obsolete helper or assertion removed in the report.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl` (including `--help`). Never wait or use background jobs you then wait on; run tests in the foreground. Do not touch `land.sh`.
- **On Codex (Luna):** You can't commit; leave work in the lab and the launcher commits it. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own; list it in your report for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave changes for the launcher to commit and report the commit, focused check results, seeded-fault red/green evidence, what was replaced, and anything incomplete.
