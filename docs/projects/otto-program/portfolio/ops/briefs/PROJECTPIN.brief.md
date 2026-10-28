# Brief: PROJECTPIN (xhard, 0.75 focused days)

**Outcome:** Change operating setup validation so a newer project revision is accepted when the content the setup was built from is unchanged, using trusted owner-reader proof like `_require_task_pin`. Refuse changes to setup-relevant content with a reason naming the changed field and the command that re-activates. Apply the same revision/content check to assignment and mandate pins; say explicitly whether ordinary writes move their revisions.

**Why it matters:** A normal plan edit after activation currently changes the project revision and blocks every later worker start, even though the setup's underlying content did not change. This leaves admitted workers unable to launch until re-activation.

**Your lab:** The launcher creates the PROJECTPIN lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. The defect is in Otto's operating-setup wiring and admission flow.

**Files you own:** `src/otto/portfolio/operating_brief.py`; focused tests for operating-brief setup validation and real owner admission/start behavior.

**Other files:** You may edit any other file directly needed for this outcome, except the files listed under Do not touch. Explain each additional file in your report.

**Do not touch:**
- `ops/bootstrap/land.sh` and `tests/test_perch.py` (TOOLING24 is running); any other files TOOLING24 owns;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `src/otto/portfolio/operating_brief.py` (`_require_exact_ref` around line 563 and `_require_task_pin` nearby); preserve detached trusted owner reads and existing task content proof. Existing real owner/admission coverage includes `tests/test_manager_bootstrap_recovery.py`, `tests/test_manager_service_continuation.py`, and `tests/test_fresh_worker_admission.py`.

**Your check:** Add unit coverage proving (1) activation followed by a task edit that advances the project revision still allows a worker launch for another admitted task, (2) changing setup-defining content is refused with the changed field and re-activation command in the reason, and (3) ordinary assignment/mandate writes either preserve their pinned refs or are handled by the same proof. Include an end-to-end stage-2 `--fake` regression for admit C, edit C, admit A and B, and verify A/B launch. Do not start a staging owner in the worker sandbox; report the stage-2 check for the landing gate/orchestrator to run outside it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_bootstrap_recovery.py tests/test_manager_service_continuation.py tests/test_fresh_worker_admission.py` (adjust to the focused test files actually changed or added).

**Regression at the level the friction appears:** The stage-2 admit C → edit C → admit A/B flow launches A and B; a true change to setup-defining content is refused clearly.

**XHARD invariant:** The operating setup binds the project by the content it was built from, not by revision. Plausible mistake: accepting any newer revision, or comparing the whole payload so every task edit still blocks.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; the launcher commits on exit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. Never run staging-owner tests in the worker sandbox.

**When done:** Report the commit, focused checks, assignment/mandate findings, and the stage-2 regression status. Stop and report if the brief contradicts the code.
