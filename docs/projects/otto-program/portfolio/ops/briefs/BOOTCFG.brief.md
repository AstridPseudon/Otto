# Brief: BOOTCFG (xhard, 0.5 focused days)

**Outcome:** A fresh installation selects and configures the supported managed product launch, with exact interpreter, source, home, working directory and logs. Generate a valid launch definition without hand edits or the retired wrapper; recovery keeps the same installation and an explicit stop remains stopped.

**Why it matters:** CUTOVER cannot rely on a fresh installation to restart the qualified product edition after an unsuccessful owner exit.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/BOOTCFG`, on branch `lab/BOOTCFG`, from current `canon/main`. Work only here.

**Layer:** Otto product. New behavior belongs in `src/otto/hostctl/` and the existing install path.

**Files you own:** `src/otto/hostctl/cli.py`, `src/otto/hostctl/config.py`, `src/otto/hostctl/supervision.py`, `tests/test_hostctl_cli.py`, `tests/test_compose.py`, `tests/test_hostctl_project_service.py`.

**Other files:** You may edit another file only when the outcome directly requires it, except files under Do not touch; explain each added path in the report. Do not modify `install/controller/` without stopping to ask the manager: that changes the approved row scope.

**Do not touch:** The files owned by active tasks: `ops/bootstrap/perch.sh`, `ops/bootstrap/canary/project.json`, stage-3 tests; `tests/test_hostctl_serve.py`, `src/otto/hostctl/serve.py`, `tests/test_ask_socket_wait.py`, `src/otto/portfolio/tests/test_execution_continuity.py`, `tests/test_hostctl_portfolio.py`, `tests/test_fleet_custody.py`; `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py`; `src/otto/hostctl/product_service.py`, `src/otto/portfolio/execution_host.py`, `tests/test_receipt_fence.py` and its narrowly authorized related paths. Also do not touch `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `new_installation` in `src/otto/hostctl/config.py`; `cmd_install` in `src/otto/hostctl/cli.py`; `PRODUCT_COMPOSITION`, `product_argv`, and `launchd_definition` in `src/otto/hostctl/supervision.py`. Keep the selected composition tied to the installed source and home.

**Your check:** Add regression coverage proving the fresh install currently lacks a usable managed launch, then cover generated launch configuration and unsuccessful-exit recovery versus explicit stop. Run focused changed tests to completion; don't run the whole suite.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_cli.py tests/test_compose.py tests/test_hostctl_project_service.py`

**Regression at the level the friction appears:** Fresh install → generated managed launch → unsuccessful exit and recovery, plus explicit stop stays stopped.

**Invariant:** Managed recovery starts the same qualified product edition against the same installation. **Plausible mistake:** Generating a valid launch definition that resolves another source tree or the retired wrapper.

**Deletion budget:** Remove reliance on hand-edited launch configuration or the old wrapper for a fresh installation; identify the retired mechanism in your report.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**On Codex:** You can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end: give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** Report the canon red run, focused green run, changed assertions, deletion, and any blocker. Do not push.
