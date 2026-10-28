# KILLFENCE resume 2

The landing gate refused this commit for three NEW failures, each reproduced 3/3 on the candidate and 0/3 on BASE:
- `tests/test_act_activation.py::test_activate_while_other_runs`
- `tests/test_act_activation.py::test_busy_queues_once`
- `tests/test_act_activation.py::test_view_attached_on_activation`

Diagnose and fix these regressions caused by your KILLFENCE change. Preserve the orchestrator's 16:51:21Z recovery decision and the 17:00:24Z released hold. Keep the change within KILLFENCE's killed-worker recovery and project-scoped fence outcome. Do not alter files/concerns owned by LABCAPTURE, ORPHANWORKER, or other tasks. LABCAPTURE is currently exited and held for its own same-session resume; it is not running. Re-run the focused command in the original brief and the failing activation tests. Report the cause, exact checks and results. Do not commit; the launcher commits when you exit.

The current KILLFENCE landing was rebased onto canon and its focused command passed before the expanded sweep. After this resume and commit, recheck the landing queue before requesting the next landing. Do not start a staging Otto in the sandbox; stage-2 `--fake` post-kill acceptance remains an orchestrator run.

**Codex rules:** You can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end: use a long timeout or keep reading its session until it exits; never stop it because a window passed. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
