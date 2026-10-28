# POLICYPIN resume 1 — fix new landing regressions

The landing gate refused commit `54ef6ad` on two failures reproduced 3/3 on the candidate and 0/3 on BASE:

- `tests/test_hostctl_serve.py::WorkerWorkspaceCompositionTests::test_fresh_project_view_loads_owner_policy_and_exact_criterion_aliases`
- `tests/test_local_assessment_composition.py::LocalAssessmentCompositionTests::test_invalid_local_flag_aliases_and_unbounded_allowance_reject`

Fix both regressions in your lab while preserving the task outcome and existing assertions. Add or adjust implementation/tests as needed to address the actual causes; do not narrow the landing check or weaken assertions. Your original task brief is `.brief.md`; its outcome, invariant, owned files, and Codex working rules still apply. No other workers are running, so no task files are currently excluded.

Run the two failing tests first, then your task check from `.brief.md` and the two relevant test files. Leave changes uncommitted for the launcher. Report the cause of each failure, the fix, and complete check results. Keep Codex's long test runs in the foreground until they finish. XHARD rule: lead and review the design; delegate execution to Luna (`spawn_agent`, `model: "gpt-6-luna"`) sub-agents where useful, and review every result against the invariant.
