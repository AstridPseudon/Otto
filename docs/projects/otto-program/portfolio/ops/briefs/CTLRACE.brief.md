# Brief: CTLRACE (normal, 0.25 focused days)

**Outcome:** A manager-control request is never visible as an empty or partial JSON file. Write each file-lane request to a temporary name in the same directory, then atomically replace it with the final `request-*.json` name. Inspect other file-lane writers, but do not change files owned by running tasks.

**Why it matters:** The responder can discover a request between file creation and the write, fail to parse it, and leave the client waiting forever. This happened during OWNERCOMPLETION's landing and reproduces on canon.

**Your lab:** The launcher creates the CTLRACE lab from current `canon/main`; work only in that lab.

**Layer:** Otto product, installed manager controller IPC.

**Files you own:** `install/controller/manager_ctl.py` and focused coverage in `tests/test_host_neutral_defaults.py`.

**Other files:** You may edit another file only when the outcome directly requires it and no active task owns it. Inspect file-lane writers under `src/otto/hostctl` and `src/herzchen/command_ports.py`; explain any additional change in your report.

**Do not touch:**
- `src/herzchen/command_ports.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/assessment/module.py`, `src/otto/hostctl/service.py`, or their focused tests (FACADEFD);
- `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, `ops/bootstrap/perch_stage2_evidence.py`, `ops/bootstrap/canary/project.json`, or `tests/test_perch.py` (PERCH2C);
- `src/otto/agents/claude_adapter.py` or its focused tests (CAPTUREEDIT);
- `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_service.py`, or OWNERCOMPLETION's focused tests;
- `production/`, any Store, `~/.otto`, `~/.codex`, or anything outside this lab.

**Build on what exists:** `call` in `install/controller/manager_ctl.py` creates and writes the request file; keep the final request naming and response protocol unchanged while making publication atomic.

**Your check:** Add a regression that observes the request directory during publication and proves no empty or partial final request is visible. Run the request test 200 times without a hang. Do not run staging-owner tests in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_host_neutral_defaults.py`

**Regression at the level the friction appears:** A real file-lane client and responder never expose a malformed request under concurrent observation, including repeated runs.

**Working rules:** Never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with a question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**When done:** Report the commit, focused check results, the 200-run result, and any other file-lane writers inspected or changed.
