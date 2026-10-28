# Brief: REDS (normal, 0.75 focused days)

**Outcome:** Clear the canon-red regressions named in the REDS task row, including the shared manager journey import failure, the hostctl xhard manager-loop path, and the listed data, status, folder, capture, and flaky-client failures. Keep the existing assertions intact.

A4 adds tests to `tests/test_hostctl_serve.py`; keep those tests passing. Its changes may land while you work, so rebase your lab at landing as usual.

**Why it matters:** The growing canon-red list has blocked otherwise-ready task landings. Restoring these behaviors lets the landing gate distinguish new regressions from known failures.

**Your lab:** `labs/REDS`, on branch `lab/REDS`, from `canon/main` at `c365152108383d687091a6c36fd01f470464504c`. Work only here.

**Layer:** Otto product. The manager journey, hostctl, portfolio, and capture reconciliation behavior is Otto's orchestration and policy wiring.

**Files you own:**
- `src/otto/agents/manager_capture_reconciliation.py`
- `src/otto/hostctl/cli.py`
- `src/otto/hostctl/config.py`
- `src/otto/hostctl/manager_client.py`
- `src/otto/hostctl/serve.py`
- `src/otto/hostctl/service.py`
- `src/otto/hostctl/product_service.py`
- `src/otto/hostctl/project_service.py`
- `src/otto/portfolio/document_navigation.py`
- `src/otto/portfolio/fixtures/project_folder.py`
- `src/otto/portfolio/herzchen_binding.py`
- `src/otto/portfolio/intake.py`
- `src/otto/portfolio/manager_guide.py`
- `src/otto/portfolio/manager_journey_command.py`
- `src/otto/portfolio/manager_journey_service.py`
- `src/otto/portfolio/observability_views.py`
- `src/otto/portfolio/owner_bootstrap.py`
- `src/otto/portfolio/owner_issue_loop.py`
- `src/otto/portfolio/project_folder.py`
- `src/otto/portfolio/supervisor_direction_client.py`
- `tests/test_completion_project_refresh.py`
- `tests/test_d03_status_reads.py`
- `tests/test_events_final_corrections.py`
- `tests/test_hostctl_cli.py`
- `tests/test_hostctl_serve.py`
- `tests/test_manager_reentrant_ipc.py`
- `tests/test_missing_manager_capture.py`
- `tests/test_project_folder_scale.py`
- `tests/test_supervisor_direction_client.py`

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** Inspect the existing implementations in the listed files and preserve their APIs and invariants. For the manager journey import red, make the runtime module available through the supported Otto package rather than relying on an `install/controller`-only import. For native manager-capture timing, make the code compare the state it means, not by adding a wider time tolerance.

**Your check.** Make the task's reds pass without weakening assertions. First reproduce each listed failure on the lab and canon where practical, then run this focused suite:

`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_reentrant_ipc.py tests/test_events_final_corrections.py tests/test_completion_project_refresh.py tests/test_project_folder_scale.py tests/test_d03_status_reads.py tests/test_missing_manager_capture.py tests/test_hostctl_serve.py tests/test_hostctl_cli.py tests/test_supervisor_direction_client.py`

Run tests with no env prefix. The landing gate also runs imported test files and checks against canon. Do not change the assertions to make these failures pass; if an expectation must change, put it in a separate commit and report each changed assertion for D19.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_reentrant_ipc.py tests/test_events_final_corrections.py tests/test_completion_project_refresh.py tests/test_project_folder_scale.py tests/test_d03_status_reads.py tests/test_missing_manager_capture.py tests/test_hostctl_serve.py tests/test_hostctl_cli.py tests/test_supervisor_direction_client.py`

**Callers, including production:** If you change a signature, constructor argument, or default, find and update every caller, including `install/controller/`.

**Existing tests:** Don't change what a test asserts to make your change pass. Any needed expectation change goes in its own commit and must be reported for D19.

**Regression at the level the friction appears:** Exercise the host manager dispatch/resume path and the state-reconciliation paths that produced the listed reds.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Never wait or start a background job you then wait on. If a question blocks you, end your report with it.

**On Codex:** You can't commit because the sandbox keeps `.git` read-only. Leave the work in the lab; `run-task.sh` commits it when you exit. A `sandbox_apply: Operation not permitted` test needs a sandbox of its own, which can't nest inside yours: report it for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report the commit, each failure's red and green evidence, what changed, and anything unfinished. Stop and ask if the brief contradicts the code.
