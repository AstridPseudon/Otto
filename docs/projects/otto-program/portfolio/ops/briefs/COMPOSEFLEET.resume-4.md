# COMPOSEFLEET: fix the refused landing check

The owner-approved design answers in resume-3 are binding: per (repo, branch), branch from `otto.plan.branch`, and check-accepted policy as described there. Do not reopen that design question.

The landing check failed only this selector in `tests/test_hostctl_serve.py`:
`ManagerLoopTests.test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results`
The other 49 tests passed, 4 skipped, 2 subtests passed. Failure: the manager test timed out waiting for `run-worker-2.json` (FileNotFoundError). The complete traceback is in `ops/runs/COMPOSEFLEET/.gate/check.txt`.

Inspect current canon-based lab state and the manager dispatch/resume path. Reproduce the exact selector and fix the defect if this is a real regression; if it is a test race, make the test deterministic without weakening its assertions. Do not touch unrelated code or the already accepted fleet design. Keep all changes within the COMPOSEFLEET row's authorized files in the tasklist. Run the focused selector and the task's full check (as time permits), with long test timeouts; leave changes for the launcher to commit. Report the cause and evidence.

On Codex, do not commit. Long tests must run to completion; use a long timeout. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
