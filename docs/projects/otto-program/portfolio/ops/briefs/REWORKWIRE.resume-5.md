# REWORKWIRE resume 5

The landing gate refused your lab with three NEW failures, each reproduced 3/3 alone while BASE passed 0/3:
- `tests/test_fleet_custody.py::test_landed_done_revokes_before_facade_waiter_resumes`
- `tests/test_fleet_custody.py::test_worker_facade_refuses_foreign_assignment_token`
- `tests/test_hostctl_serve.py::WorkerWorkspaceCompositionTests::test_dispatcher_due_requires_exact_owner_generation_principal_and_task_revision`

The full gate log is `${TRANSFER_ROOT}/portfolio/ops/runs/REWORKWIRE/land.log`; paired outputs are under `${TRANSFER_ROOT}/portfolio/ops/runs/REWORKWIRE/.gate/`. Your latest fresh rebase has completed; this resume requests another fresh canon rebase first. Continue in the same lab and worker session. Fix these regressions without weakening assertions, preserve the original task outcome and invariant, and run the exact focused test plus directly affected checks. Leave work for the launcher and report cause and green results.

No other worker owns files at this moment. Do not touch `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab. Follow the original brief's Codex rules word for word: never stash or switch commits, don't run `ottoctl`, and every sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
