Task: OPERATOR-ADMIT.

The landing gate refused the current commit for six NEW failures, each reproduced 3/3 alone on the candidate and 0/3 on BASE. Fix the regressions introduced by OPERATOR-ADMIT; do not change the intended stage-1 save behavior or weaken tests. Full gate log: `${TRANSFER_ROOT}/portfolio/ops/runs/OPERATOR-ADMIT/land.out`; paired candidate/BASE outputs are in `${TRANSFER_ROOT}/portfolio/ops/runs/OPERATOR-ADMIT/.gate/pair-1-*` through `pair-6-*`.

Failures:
- `tests/test_perch_stage1.py::OwnerSocketSaveTests::test_cold_client_save_reaches_the_owner_socket`
- `tests/test_perch_stage1.py::OwnerSocketSaveTests::test_save_sent_through_the_owner_socket_is_accepted`
- `tests/test_perch_stage1.py::OwnerSocketSaveTests::test_show_readback_through_owner_lane_returns_the_saved_tasks`
- `tests/test_perch_stage1.py::OwnerSocketSaveTests::test_stale_save_sent_through_the_owner_socket_is_refused`
- `tests/test_perch_stage1.py::OwnerSocketSaveTests::test_store_snapshot_reads_saved_task_records_and_kept_project_revision`
- `tests/test_perch_stage1.py::OwnerSocketSaveTests::test_the_save_names_each_task_with_a_typed_ref_as_the_store_holds_it`

Reproduce these tests in the rebased lab, inspect the paired gate output to identify the shared cause, and fix it while preserving OPERATOR-ADMIT's invariant and its D19-approved changes. Run the task's exact check from the main brief: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py tests/test_admit.py tests/test_operator_admission.py`. Also run `tests/test_perch_stage1.py` because the gate identified these regressions. Do not alter other tasks' files; list any necessary extra file and reason in your report. Leave changes uncommitted for the launcher.

Do not touch files owned by the concurrent A6 landing. Its changed paths are `src/otto/hostctl/sync.py`, `src/otto/hostctl/portfolio.py`, `src/otto/portfolio/shared_documents.py`, `tests/test_hostctl_sync.py`, `tests/test_hostctl_portfolio_apply.py`, `tests/test_portfolio_shared_documents.py`, `tests/test_hostctl_portfolio.py`, and `tests/test_owner_vision_installation.py`. Also preserve the main brief's other Do not touch rules and its Codex working rules. Give long test runs enough time to finish.
