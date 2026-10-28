# Brief: REDS2 (normal, 0.75 focused days)

**Outcome:** Fix the remaining known canon regressions listed below by correcting the production causes. Each listed test passes three times alone and in the gate sweep; no assertion is weakened.

**Why it matters:** These failures are already present on canon and can mask regressions in later landings. Restore the affected behavior so the landing gate can distinguish new failures.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS2`, on branch `lab/REDS2`, from `canon/main` at `5f8a7280faa4046b08e4250f0611d6a6ba887273`. Work only here.

**Layer:** Otto product. New or corrected product code belongs under `src/otto/`.

**Files you own:** The test files listed in the check command, and the directly exercised production modules under `src/otto/` needed to fix those tests. Do not edit test assertions.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** Trace each regression to the production change that introduced it, using `ops/runs/*/land.log` and the canon history; preserve behavior already covered by neighboring tests.

**Your check.** Address both REDS2's original failures and the additional canon failures recorded during ASK's landing:
- Original REDS2 files: `tests/test_events_final_corrections.py`, `tests/test_project_folder_scale.py`, `tests/test_hostctl_serve.py`, `src/otto/portfolio/tests/test_worker_occurrences.py`, `tests/test_supervisor_direction_client.py`, and `tests/test_hostctl_cli.py` (OWNERLANE heartbeat flake).
- ASK landing's canon failures: `tests/test_current_manager_selector.py`, `tests/test_help_completion_regression.py`, `tests/test_manager_correction_planning.py`, `tests/test_manager_journey_command.py`, `tests/test_manager_reentrant_ipc.py`, and `tests/test_manager_service_continuation.py`. The orchestrator described these as 31 failures across five test files; the later ASK gate log has additional BASE-classified selectors, so use the gate's current BASE comparison to identify exact regressions and do not repair failures that are not red on current canon.
- Run regression tests red on canon first, then green after the fix. Run the listed test files with no env prefix; `pyproject.toml` sets pytest's `pythonpath`. The landing gate runs each affected file twice and compares failures with canon.
- Run heavy commands as `otto-heavy --weight N --purpose "REDS2" -- <cmd>`.
- Long test runs must continue to completion; use a long timeout such as `timeout_ms: 1800000` or keep reading the session until it exits.

**Check command:** `otto-heavy --weight 1 --purpose "REDS2" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_events_final_corrections.py tests/test_project_folder_scale.py tests/test_hostctl_serve.py src/otto/portfolio/tests/test_worker_occurrences.py tests/test_supervisor_direction_client.py tests/test_hostctl_cli.py tests/test_current_manager_selector.py tests/test_help_completion_regression.py tests/test_manager_correction_planning.py tests/test_manager_journey_command.py tests/test_manager_reentrant_ipc.py tests/test_manager_service_continuation.py`

**Callers, including production:** If you change a signature, constructor argument or default, find every caller and update it, including production startup where applicable.

**Existing tests:** Don't change what an existing test asserts to make your change pass. If an expectation really must change, keep it in its own commit and report each changed assertion with its reason; it lands only after an Opus decision (D19).

**Regression at the level the friction appears:** Preserve end-to-end manager dispatch/resume, project-folder scale, completion and final-correction behavior, worker occurrence identity, and supervisor completion under load.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Never wait with a monitor, sleep loop, or background job. If a question blocks you, decide it within this brief or end your report with the question.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**When done:** Leave the work for the launcher to commit. Report the commit, red and green checks, fixes made, and anything unfinished. Stop and ask if the brief contradicts the code.
