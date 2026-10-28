# Brief: PERCH1FIX (normal, 0.75 focused days)

**Outcome:** Stage 1's perch proves what it claims: the canary has three tasks with an A→B dependency, each with `otto.plan` route, size, lines and criteria; the edit changes A's title and B's size and adds C→B; `show` read-back through the owner lane must be available; assertions use Store snapshots, including typed task records, no execution, stage counts, old revision, project history and growth per save; each seeded fault corrupts the Store snapshot and turns its matching assertion red. `perch.sh 1` runs without `--fake` and passes.

**Why it matters:** Stage 1 is the last prerequisite for its staging rerun and review. The perch must verify persisted state and owner-lane read-back so the validation evidence reflects the Store, not a save response.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH1FIX`, on branch `lab/PERCH1FIX`, from `canon/main` at `2e445ae7a4c54f101b402b55a386db5299049bc3`. Work only here.

**Layer:** Otto product, bootstrap tooling. Keep changes in `ops/bootstrap/`; `land.sh` is outside scope.

**Files you own:**
- `ops/bootstrap/perch.sh`
- `ops/bootstrap/perch_report.py`
- `ops/bootstrap/canary/` (stage 1 project and its task fixtures)
- `tests/test_perch.py`
- `tests/test_perch_stage1.py`
- `tests/test_perch_staging.py`
- `tests/test_perch_timeline.py`

**Do not touch:**
- other tasks' files, especially `land.sh`;
- `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists:** preserve the existing stage runner and report CLI in `ops/bootstrap/perch.sh` and `ops/bootstrap/perch_report.py`; use the owner-lane save/read paths and the stage-1 canary project. The task row in `projects/program/tasklist.md` is the acceptance contract.

**Your check.** Add or update focused tests for the three-task canary, edit/read-back path, Store-backed assertions and seeded faults. Each new assertion must turn red under its own seeded fault. Keep existing stage 0 behavior and boundary checks green; do not weaken assertions. Run the task-owned tests below. The landing gate runs changed-module sweeps and the real staging perch.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_stage1.py tests/test_perch_staging.py tests/test_perch_timeline.py`

**Regression at the level the friction appears:** a successful save whose owner-lane `show` read-back is unavailable must fail stage 1; corrupted Store state must fail the corresponding assertion even when a save reply claims success.

**Deletion budget:** replace the current incomplete stage-1 canary/assertion behavior with Store-backed checks; name any obsolete assertion or helper removed in the report.

**Working rules:** never run `git stash`, check out another commit, or run `ottoctl` (including `--help`). Never wait or use background jobs you then wait on; run tests in the foreground. Do not touch `land.sh`.
- **On Codex (Luna):** you can't commit; leave work in the lab and the launcher commits it. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own; list it in your report for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** leave changes for the launcher to commit and report the commit, focused check results, seeded-fault red/green evidence, what was replaced, and anything incomplete.
