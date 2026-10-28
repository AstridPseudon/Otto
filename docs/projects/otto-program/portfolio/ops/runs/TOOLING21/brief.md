# Brief: TOOLING21 (normal, 0.5 focused days)

**Outcome:** Every staging owner started by a test is stopped by that test, including when the test fails or times out; the landing gate also detects and names any `service run` left alive with a home under a temporary root it can see.

**Why it matters:** Orphaned staging owners hold memory and Store files. Cleanup must work without `ps` and must run when tests fail.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING21`, on branch `lab/TOOLING21`, from `canon/main`. Work only here.

**Layer:** Herzchen model. This is test and landing-gate tooling, not Otto product behavior.

**Files you own:**
- `tests/test_staging_startup.py`
- `tests/test_perch_staging.py`
- `tests/test_bootstrap_gate.py`
- `ops/bootstrap/land.sh`

**Other files:** You may edit another file only when the outcome directly requires it. List each in your report with the reason.

**Do not touch:**
- files owned by REDS3 and PERCH2B, the tasks running now;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `tests/test_staging_startup.py` and `tests/test_perch_staging.py` start staging owners in tests; `ops/bootstrap/staging.sh` writes the pidfile. Register cleanup before starting each owner. Read the pidfile and use `os.killpg` to stop the process group and wait for it, without relying on `ps`; remove the temporary root after the owner exits. `ops/bootstrap/land.sh` owns the post-sweep orphan check, and `tests/test_bootstrap_gate.py` contains its scratch-repository gate tests.

**Your check.** Add coverage for cleanup on a forced mid-test failure and timeout for both test files, and for the gate naming a deliberately planted orphan. Do not run `tests/test_staging_startup.py` or `tests/test_perch_staging.py` in your worker sandbox: those tests start owners and the sandbox cannot reliably run `ps` or cleanup on timeout. The landing gate runs both files outside the sandbox. Run the gate tests you change in the worker.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Callers, including production:** If you change a signature, constructor argument or default, find and update every caller, including production startup.

**Existing tests:** Do not weaken existing assertions to make the change pass. If an expectation must change, report each changed assertion as file:line and explain why; it lands only after an Opus D19 decision.

**Regression at the level the friction appears:** Force a failure mid-test and exercise a timeout path; after each, no owner started by the test remains. Plant an orphan for the gate check and confirm it names the owner.

**Invariant:** Every staging owner a test starts is stopped by that test, whatever happens to the test. **Plausible mistake:** Stopping only the wrapper pid, so the Python holder survives, or relying on `ps`.

**Working rules:** Never run `git stash` or check out another commit. Don't run `ottoctl` (including `--help`). Never wait or poll. Run tests in the foreground and give long checks a long timeout. On Codex, leave changes for the launcher to commit; do not work around the read-only `.git`. If a check fails with `sandbox_apply: Operation not permitted`, report it for the landing gate to run outside the sandbox. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work in the lab for the launcher to commit. Report the commit and the checks run, including why the two staging test files were left for the landing gate. Don't push.
