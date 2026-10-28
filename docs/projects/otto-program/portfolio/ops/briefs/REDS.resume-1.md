The landing gate refused commit `b60477daa58a3d490451ecd3dbd3453c30f9ccec` on the task check. Reproduce and repair this failure within the already authorized REDS files and scope:

`tests/test_missing_manager_capture.py::MissingManagerCaptureTests::test_admitted_abort_is_failed_settlement_and_physical_release_not_success`

The test changes the `work-turn` terminal event from `task_complete` to `turn_aborted`. `reconcile_missing_manager_capture` then raises `OwnerRoleRuntimeError: native start differs from retained owner admission second` at `src/otto/agents/manager_capture_reconciliation.py:134`. The check summary was 1 failed, 12 passed, 19 subtests passed. Inspect the complete landing evidence in `ops/runs/REDS/land.log` and `.gate/check.txt`; fix the underlying timing-state comparison without widening a time tolerance or weakening assertions, as the original brief requires. Run the REDS focused check before exiting. Do not alter tests to make this pass.
