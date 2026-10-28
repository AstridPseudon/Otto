# Brief: READYPIN (xhard, 0.75 focused days)

**Outcome:** A completion for a task revision delivered to the manager is accepted when the completion's predecessor differs only by verified content-equivalent revisions. A content change or a different task remains refused.

**Why it matters:** Stage 2 on c81c9a6 admitted A after the manager turn was prepared, then completed A against rev-2 while the delivered pin was rev-1. The next task's start was refused before reaching its provider.

**Your lab:** The launcher creates the READYPIN lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. The affected owner readers and historical setup proof are Otto wiring and policy.

**Files you own:** `src/otto/portfolio/owner_readers.py`, `src/otto/portfolio/owner_bootstrap.py`, `tests/test_completed_occurrence_readiness.py`, `tests/test_operating_setup_pin_content.py`, and focused tests for the historical setup proof if required.

**Other files:** You may edit any other file directly needed for the outcome, except files listed under Do not touch. Explain each additional file in your report.

**Do not touch:**
- OWNERCOMPLETION's landing changes (`src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_service.py`, and its focused tests);
- PERCH2C's held files;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** Use `herzchen.domains.work.admission.task_content_matches` as PINCONTENT does to prove content-equivalent revisions. Retain the receipt, assignment, manager, native-turn and digest checks in `src/otto/portfolio/owner_readers.py` near lines 170-200; inspect the historical setup guard in `src/otto/portfolio/owner_bootstrap.py` near lines 1249-1258 for the same revision issue.

**Your check.** Add a real-owner regression: prepare a manager occurrence for A rev-1, admit A (rev-2), complete A from accepted evidence, then start B and prove B reaches its provider. Also prove changed instructions and another task remain refused, including through the historical-setup proof where applicable. Run the task's test files and keep unrelated behavior intact. Stage 2 `--fake` is run by the orchestrator after landing; do not start a staging owner in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_completed_occurrence_readiness.py tests/test_operating_setup_pin_content.py tests/test_owner_result_reconciliation.py`

**Regression at the level the friction appears:** A manager start after an admitted task completes reaches its provider even when admission advanced metadata-only revision; changed instructions or a foreign completion still refuse.

**XHARD only:**
- Invariant: Readiness accepts the delivered task's completion across metadata-only revisions, never across a content change.
- Plausible mistake: Comparing task identity alone, so completing changed instructions satisfies an older delivered brief.

**Working rules:** Follow the Codex rules in the template: no commits or pushes; the launcher commits on exit. Do not run `git stash`, check out another commit, run `ottoctl`, or run tests that start a staging owner in the worker sandbox. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. As XHARD lead, delegate execution and keep design, invariant review, and final review yourself.

**When done:** Report the commit, red then green focused checks, invariant coverage, and any remaining limitations. Stop and report if this brief contradicts the code.
