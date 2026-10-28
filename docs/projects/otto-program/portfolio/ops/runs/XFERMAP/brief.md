# Brief: XFERMAP (normal, 0.75 focused days)

**Outcome:** CUTOVER has a complete, revision-consistent preservation manifest and independent readback. It covers the program, seven follow-ups, r4 and every other selected upcoming project, maps identities, and compares tasks, dependencies, criteria, instructions, configuration, notes and document bodies. Reject incomplete pages and stale snapshots.

**Why it matters:** CUTOVER must prove every selected project survived transfer before clients switch. A digest of partial or stale exports is not evidence of preservation.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/XFERMAP`, on branch `lab/XFERMAP`, from `canon/main` at the current base. Work only here.

**Layer:** Otto product. The transfer manifest and verifier are Otto's owner-transfer workflow; keep the owner read ports and bindings read-only.

**Files you own:** `src/otto/portfolio/intake.py`, `src/otto/portfolio/herzchen_binding.py`, `src/otto/portfolio/project_folder.py`, `tests/test_project_folder_scale.py`, and `tests/test_portfolio_shared_documents.py`.

**Other files:** You may create or edit any other file directly required by the outcome, except files under Do not touch. Explain each additional file in your report.

**Do not touch:**
- `ops/bootstrap/perch.sh` and stage-3 scenario/tests (REALSTAGE3);
- `src/otto/hostctl/serve.py`, `tests/test_hostctl_serve.py`, `tests/test_ask_socket_wait.py`, `src/otto/portfolio/tests/test_execution_continuity.py`, `tests/test_hostctl_portfolio.py`, `tests/test_fleet_custody.py` (TESTPATCH);
- `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py`, `tests/test_fleet_custody.py` (LANDPROOF);
- `src/otto/hostctl/product_service.py`, `src/otto/hostctl/fleet_landing.py`, `src/herzchen/fleet/landing.py`, `src/herzchen/fleet/labs.py`, `tests/test_fleet_custody.py`, `tests/test_external_owner_execution.py` (LABPIN);
- `src/otto/hostctl/cli.py`, `src/otto/hostctl/config.py`, `src/otto/hostctl/supervision.py`, `tests/test_hostctl_cli.py`, `tests/test_compose.py`, `tests/test_hostctl_project_service.py` (BOOTCFG);
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects or Native5, and anything outside this lab.

**Build on what exists:** `OttoPortfolio.list_projects` at `src/otto/portfolio/intake.py:849` and `HerzchenBinding.list_projects` at `src/otto/portfolio/herzchen_binding.py:306` provide finite read-only owner pages. `HerzchenBinding._export_project` at `src/otto/portfolio/herzchen_binding.py:881` exports portable records. `project_folder.py:490` validates folder bounds. Reuse these paths and reject incomplete exports; do not treat a digest as proof of completeness.

**Your check:** Cover a >100-task project, linked documents with differing revisions, all selected projects, complete cursor traversal, independent source/target readback, and refusal after omission, body/dependency change, or source revision advance. Regression tests must fail on canon first. Run the affected existing checks and any tests you add; don't sweep the suite.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_project_folder_scale.py tests/test_portfolio_shared_documents.py`

**Regression at the level the friction appears:** A transfer attempt with an omitted final page, changed target content/dependency, or source edit after export is refused; unchanged complete transfer is verified.

**Deletion budget:** Remove silent missing-record/document/link skips that can certify or produce a partial transfer; retain raw folder export, which serves a different purpose.

**Known gap:** The CUTOVER selection list and `PATH-TO-CUTOVER` reference are not present on canon; do not invent the seven follow-up identities. Keep selection explicit and supplied to the capture API.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
