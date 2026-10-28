# COMPOSEFLEET: repair new landing regressions

The landing gate refused the current commit for eight failures it classified as NEW (full details and reproduction evidence are in `ops/runs/COMPOSEFLEET/land.log`):

- `tests/test_bounded_project_host.py::BoundedProjectHostTests::test_drain_finishes_capture_and_fences_conflicting_source_writers`
- `tests/test_bounded_project_host.py::BoundedProjectHostTests::test_five_projects_share_slots_and_A_settles_while_B_waits`
- `tests/test_bounded_project_host.py::BoundedProjectHostTests::test_pending_child_survives_restart_and_returns_to_exact_parent_with_B_live`
- `tests/test_current_manager_selector.py::NativeManagerWorkerSubmissionTests::test_actual_native_context_retains_exact_manager_and_one_child_start`
- `tests/test_final_recovery_composition.py::ComposedReminderTests::test_native_recovery_diagnosis_remains_available_under_separate_reminder_hold`
- `tests/test_hostctl_project_service.py::SharedHostAdmissionTests::test_three_managers_share_total_three_with_queued_worker`
- `tests/test_manager_journey_command.py::ManagerJourneyCommandTests::test_same_key_review_replay_rejects_changed_scope_mode`
- `tests/test_worker_custody.py::WorkerCustodyTests::test_ordinary_service_admits_one_reserved_fresh_worker_and_keeps_history`

Reproduce these exact selectors and inspect the paired commit/BASE outputs in `ops/runs/COMPOSEFLEET/.gate/`. Diagnose the regressions and fix them within COMPOSEFLEET's authorized files in the tasklist; do not edit another task's files or broaden the fleet design already approved. If a failure cannot be fixed within that scope, report the cause and exact required files without editing them. Run the eight selectors and the task's full check with long test timeouts; leave changes for the launcher to commit. Report causes and evidence.

On Codex, do not commit. Long tests must run to completion; use a long timeout. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
