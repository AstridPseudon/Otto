# SKEL0 resume 3: fix stage 4 fake-run assertions

The latest landing at 2026-10-17T13:21:27Z was refused by the task's check. The gate ran the focused command and got 92 passed, 2 failed, 68 subtests passed. Failures:
- `tests/test_perch.py::FakeRunTests::test_stage4_fake_run_lands_happy_path_refuses_conflict_and_deletes_labs`: `timeline-events` and the owner-driven happy path assertions fail; the report says no owner-driven timeline events were recorded.
- `tests/test_perch.py::FakeRunTests::test_stage4_seeded_missing_conflict_turns_its_assertion_red`: expected only `landing-conflict-refused` red, but `timeline-events`, `owner-driven-canary`, and `landing-conflict-lab-deleted` were also red.

Inspect the current lab after canon rebase. Trace why the fake owner-driven canary isn't creating the timeline/events and why conflict cleanup doesn't meet the assertion. Preserve canon's stage 2 changes and SKEL0 stage 4 assertions; do not weaken checks. Leave the lab clean and resolved for the launcher to commit; do not commit or write Git metadata yourself. Report the concrete cause and changed files.

Do not run tests that start a staging owner in the worker sandbox, including `tests/test_staging_startup.py`, `tests/test_perch_staging.py`, or staging cases in `tests/test_perch.py`; those time out there and the landing gate runs them. A non-staging focused check is fine if useful. Do not claim the owner-driven stage 4 journey or real Claude journey is proven; these remain orchestrator-run stage work.

Keep the existing SKEL0 task outcome and file scope in `ops/runs/SKEL0/brief.md`. Do not edit files owned by another running task. The launcher commits your work on exit.
