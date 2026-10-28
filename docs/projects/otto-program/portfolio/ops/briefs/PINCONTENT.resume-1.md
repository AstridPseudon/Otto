# PINCONTENT landing regression resume

The landing gate refused commit `c65ec5cf71c79b6e5bce5a2e6b4ac9b20023821a` for one NEW failure, reproduced 3/3 alone while BASE passed 0/3:

`tests/test_fresh_worker_admission.py::PolicyTaskAdmissionTests::test_permitted_new_sheet_task_is_admitted_at_rev_one_and_dispatches`

Gate evidence: `${TRANSFER_ROOT}/portfolio/ops/runs/PINCONTENT/land.log` and `.gate/pair-1-*.txt` in that run directory. Fix the regression in the PINCONTENT lab, add or adjust only task-relevant coverage as needed, and run the failing test plus focused checks. Do not weaken the expected behavior or touch PERCH2B's files. Preserve the invariant: metadata-only revisions retain task pins; content changes invalidate them. Keep all edits in the lab and let the launcher commit on exit.

Run long checks to completion (use a long timeout; do not stop at a window). Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
