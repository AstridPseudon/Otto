# Resume: PINALL (xhard)

The landing gate refused PINALL with NEW failures in these tests. Read `${TRANSFER_ROOT}/portfolio/ops/runs/PINALL/land.log` for the full diagnostics:

- `tests/test_external_owner_execution.py::ExternalOwnerExecutionTests::test_owner_claude_write_done_captures_before_landed_lab_removal`
- `tests/test_external_owner_execution.py::ExternalOwnerExecutionTests::test_owner_claude_write_done_removes_landed_lab_after_rejected_capture_acceptance`
- `tests/test_hostctl_serve.py::EscalationTests::test_manager_escalates_the_orchestrator_answers_and_the_manager_applies_it`
- `tests/test_hostctl_serve.py::ManagerLoopTests::test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results`
- `tests/test_hostctl_serve.py::ServeTests::test_activation_launches_the_manager_which_authenticates_and_reads_its_documents`
- `tests/test_landing.py::test_real_owner_claude_edit_capture_settles_and_removes_lab[auto_merge_write]`
- `tests/test_landing.py::test_real_owner_claude_edit_capture_settles_and_removes_lab[edit]`
- `tests/test_landing.py::test_real_owner_claude_edit_capture_settles_and_removes_lab[write_edit]`
- all listed NEW failures in `tests/test_missing_manager_capture.py` (see land.log)

After the requested lab rebase, diagnose how PINALL's changes caused these failures and fix the regression in PINALL-owned product code. Do not edit unrelated tests or files owned by other work. Preserve the PINALL invariant: every native process is recorded before input, and its slot frees exactly when its process group is provably empty. Run the original Check command in the brief to completion, then `git diff --check`. Report the cause, exact checks, changed files, and any blocker. Leave changes uncommitted for the launcher. Never stash, switch commits, or run ottoctl. No sub-agent is needed.
