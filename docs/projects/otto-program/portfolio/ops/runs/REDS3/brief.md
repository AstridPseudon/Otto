# Brief: REDS3 (normal, 0.75 focused days)

**Outcome:** Make the canon regressions remaining after REDS2 and MGR land green because the code or test fake reflects the intended behavior. Start by rerunning each listed test file against the current canon and drop any selectors already green. For each remaining failure, trace the landing that introduced it, then fix the affected fake or code. Keep the existing assertion's meaning; do not weaken it. The stale `review-task` expectation in `test_manager_correction_planning.py` must match canon's native-caller routing; any assertion change requires a D19 decision.

**Why it matters:** The task removes regressions left by earlier landings without hiding broken behavior behind weaker assertions.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3`, on branch `lab/REDS3`, from `canon/main` at `a9d73607dc875c69972f6a710de38814c547f761`. Work only here.

**Layer:** Otto product. New code goes under `src/otto/`.

**Files you own:**
- `tests/test_current_manager_selector.py`
- `tests/test_help_completion_regression.py`
- `tests/test_manager_correction_planning.py`
- `tests/test_manager_journey_command.py`
- `tests/test_manager_service_continuation.py`
- `tests/test_hostctl_cli.py`
- `tests/test_hostctl_serve.py`
- `src/otto/portfolio/tests/test_manager_consumption.py`

**Other files:** You may edit another file only when the outcome directly requires it. Explain each such file in your report. Do not touch the task's `test_project_folder_scale.py` limit contradiction: report it for the orchestrator to decide.

**Do not touch:**
- files owned by any task running now;
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** Follow the code paths exercised by the named test files. The current-canon landing and the REDS2 changes are the baseline. For each remaining red, use `git log` on the exercised files to find the landing that introduced it, then fix the fake or the code that landing broke. Do not add a `due_port` to a fake if that would hide a missing dependency.

**Your check:** Rerun the listed files individually on the lab, twice each. The `test_manager_consumption.py` file must collect and run. First establish which selectors remain red on current canon. Do not run the full suite. Do not weaken an assertion; if an existing expectation must change, stop that change pending D19 approval. Report the `test_project_folder_scale.py` contradiction without changing it.

**Check command:** `rc=0; for f in tests/test_current_manager_selector.py tests/test_help_completion_regression.py tests/test_manager_correction_planning.py tests/test_manager_journey_command.py tests/test_manager_service_continuation.py tests/test_hostctl_cli.py tests/test_hostctl_serve.py src/otto/portfolio/tests/test_manager_consumption.py; do /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider "$f" || rc=1; done; exit $rc`

**Regression at the level the friction appears:** Each named failing selector must pass in its single-file journey, twice; the manager consumption tests collect and run.

**XHARD only:** Not applicable.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl` (including `--help`), or wait with a monitor, sleep loop or background job. Run checks in the foreground and let them finish. On Codex, leave changes for the launcher to commit; do not work around the read-only `.git`. Give long checks a long timeout. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave changes for the launcher to commit. Report the commit, each file's before/after baseline, checks run twice, source landing traced for each fix, any additional files changed, and the untouched `test_project_folder_scale.py` contradiction.
