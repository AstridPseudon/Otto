# ASK resume: repair the remaining landing failures

Read `ops/runs/ASK/land.log` and repair only the remaining `NEW failure` entries from the refused landing:
- `tests/test_admitted_transport_drain.py::AdmittedDrainTests::test_preparation_crossing_drain_preserves_exact_admitted_transport`
- `tests/test_execution_operations.py::Tests::test_host_final_gate_blocks_fresh_resume_and_retry_on_stale_task_admission`
- `tests/test_execution_operations.py::Tests::test_host_final_gate_rechecks_state_changed_after_queue_selection`

Stay within ASK's already approved scope and existing lab. Preserve the invariant: an answer resumes exactly the asking session; a paused task never dispatches. COMPOSEFLEET is currently active and owns its edits to `src/otto/portfolio/manager_journey_service.py`; avoid that file and unrelated changes. Diagnose the failures against their exact landing traces, repair the underlying regression, and run the three exact test selectors plus relevant focused checks. Do not attempt a landing or change task scope. Report anything unrelated or unresolved.

A long test runs to its end: give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed.
