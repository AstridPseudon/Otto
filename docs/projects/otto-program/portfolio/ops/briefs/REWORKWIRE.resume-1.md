# Resume: REWORKWIRE

The landing gate refused your commit for three reproduced NEW failures (each reproduced 3/3 alone and passed 0/3 on BASE):
- `tests/test_fleet_custody.py::test_landed_done_revokes_before_facade_waiter_resumes`
- `tests/test_fleet_custody.py::test_worker_facade_refuses_foreign_assignment_token`
- `tests/test_hostctl_serve.py::WorkerWorkspaceCompositionTests::test_dispatcher_due_requires_exact_owner_generation_principal_and_task_revision`

Fix these regressions in your lab after the requested rebase. Preserve the existing task outcome and assertions. Run the exact focused tests above, plus any directly affected coverage needed. Do not broaden the check to unrelated tests or change an unrelated assertion. Report the cause of each failure and the green results. Leave changes uncommitted for the launcher.

No other worker currently owns files. Do not touch production/, any Store, ~/.otto, ~/.codex, Codex project configuration, or anything outside this lab.

Follow the original brief's Codex working rules word for word: never stash, switch commits, or run ottoctl; keep long test commands running to completion; every sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
