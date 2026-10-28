# Brief: ASSESSCAP (normal, 0.25 focused days)

**Outcome:** Unrelated assessment history cannot exhaust a task’s coverage bound. With more than 10,000 unrelated assessment events, a new task’s real coverage and required-scope lookup succeed; an oversized same-parent history still refuses explicitly.

**Why it matters:** A task’s coverage limit must apply to that task’s own assessment history, so unrelated work cannot block its completion checks.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product; this fixes Otto’s task-specific assessment coverage lookup.

**Files you own:** `tests/test_local_assessment_composition.py`, `src/otto/portfolio/assessment.py`, `src/herzchen/kernel/store.py`.

**Other files:** You may edit any other file directly required by the outcome, except files under Do not touch. Explain each addition in your report.

**Do not touch:**
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, and `tests/test_manager_journey_service.py` (GATESKIP);
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and CODEXOWNER's focused real-owner Codex journey tests;
- `tests/test_fleet_custody.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py` (LANDPROOF);
- `src/otto/portfolio/cli.py`, `tests/test_otto_open_release.py` (SAVEPATH);
- `tests/test_compose.py`, `src/otto/hostctl/cli.py` (STOPATOM);
- files outside this lab, `production/`, any Store, `~/.otto` or `~/.codex`, and Codex project configuration.

**Build on what exists:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/ASSESSCAP.md` first and report any departure. In `src/otto/portfolio/assessment.py:133–135`, select events with `list_events(stream="assessment", assessment_parent=current_parent.ref)` and keep the existing `> 10000` refusal after selection. Complete the existing assessment-parent selector in `src/herzchen/kernel/store.py:2733` so amended scope declarations and created/resolved corrections are included with the existing stream, event type, subject kind, and authority predicates. The owner completion predicate already uses `assessment_parent` in `src/herzchen/domains/assessment/module.py:1115`; required-scope lookup already calls `coverage()` in `src/otto/portfolio/manager_assessment_command.py:80`.

**Your check:** Add the prework regression first to `LocalAssessmentCompositionTests` in `tests/test_local_assessment_composition.py`; it verifies unrelated history does not trigger the bound for coverage or required-scope lookup, while same-parent history over the bound still raises `OttoAssessmentError`. Add focused selector assertions for amended scopes and created/resolved corrections, and confirm `coverage()["corrections"]` still returns the current correction. Run changed test files only; show canon-red and lab-green where feasible. No existing test assertion needs to change (no D19 decision).

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_local_assessment_composition.py`

**Callers, including production:** If changing a signature, constructor argument, or default, find and update every caller, including `install/controller/`.

**Existing tests:** Do not change an existing test’s assertions without a written D19 decision. Never weaken a test to pass in the worker sandbox.

**Regression at the level this friction appears:** Real task coverage and required-scope lookup under more than 10,000 unrelated assessment events, plus explicit refusal when the target parent itself exceeds the bound.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. On Codex, do not commit; the launcher commits when you exit. Give long test commands a long timeout and let them finish. If a check is blocked only by sandbox permissions, report it for the landing gate.

**On Codex:** Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
