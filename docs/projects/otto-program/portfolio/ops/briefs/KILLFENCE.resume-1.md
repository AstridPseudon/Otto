# KILLFENCE resume 1

Implement the orchestrator's 2026-10-17T16:51:21Z decision exactly:

The manager's `execution-control recover` also settles a general unknown worker attempt when the owner itself has observed the worker's process group gone (its recorded group no longer alive, birth-checked; process exit alone is the precondition, not the settlement). The manager's request carries the expected due digest and unknown-result digest (the same pinning as the capacity release) and a short reason.

1. Write one disposition report on the assignment (`append_report`), stop the occurrence (`stop_state` stopped, `completion_state` stays unknown, `in_flight_request` cleared), and clear the fence through `restore_execution`. No provider retry: any further work is a new dispatch through `WorkAssignments.dispatch`. A replayed request writes nothing new.
2. A live recorded group, stale pins, or a missing reason are refused, naming the cause.
3. Keep the capacity release as it is for its own case; don't widen it.
4. Tests on the real owner: SIGKILL a held fake worker → manager recover settles it, the fence clears, and a new dispatch in the same project launches; recover while the group is alive is refused; a replay writes no second report. Keep the project-scoping already implemented.

The row's original ownership boundaries still apply. Keep changes to killed-worker recovery and project-scoped fence release. Do not edit `perch.sh`, `perch_report.py`, `claude_cli.py`, worker process census, or files/changes owned by LABCAPTURE, ORPHANWORKER, or COMPLETECITE. Do not start a staging Otto in the sandbox; report that stage 2 `--fake` post-kill acceptance requires the orchestrator run. Run the focused check from the brief and report the full result. You do not commit; the launcher commits on exit. Any sub-agent must be started with `spawn_agent` and `model: "gpt-6-luna"`.
