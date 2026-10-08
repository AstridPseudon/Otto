# J04 cold installed journey receipt

This is the worker evidence for J04/C07-C08. It records the bounded cold-path
checks performed by the normal worker; acceptance and owner-state completion
remain with the canonical manager.

## Exact run inputs

- Run artifacts: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/{agent_goal.md,tasklist.md,run.yaml,plan.md,manager-guide.md}`
- Candidate source: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/work/integration-owner/src`
- Pinned Python: `/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python`
- Maintained client: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/controller/manager_ctl.py`

The maintained client `--help` receipt exposed the required `manager-continue`,
`completion-gate`, `complete-task`, `project-lifecycle-read`, and
`project-lifecycle-transition` operations. Its read-only `status` receipt was
authoritative and identified the current project and J04 task refs. The current
manager occurrence was still `delivery_state=ready`, `completion_state=none`,
`host_state=unknown`, with an in-flight request and no terminal native session.

## Disposable cold-path receipts

Run with the pinned interpreter:

```sh
PYTHONPATH=src \
  /Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python \
  -m unittest tests.test_manager_reentrant_ipc tests.test_manager_no_overlap_disposition \
  tests.test_manager_preprovider_disposition tests.test_execution_operations
```

Result: `Ran 66 tests ... OK`.

The retained file-IPC fixture provides the relevant receipts:

- nested task-state and report commands returned `committed` before the native
  manager transport returned;
- the child retained the owner path while the parent was in its transport wait;
- a status read remained available while the host drained;
- a second queued dispatch was retained across restart and returned `replayed`;
- provider call count did not increase on restart, proving no duplicate native
  effect;
- the canonical gateway attempt reached terminal `state=result` only once.

The candidate execution host now also admits the read-only
`project-lifecycle-read` command during that wait/drain window. The regression
transcript returned `read` for that command while the native manager was still
held, while lifecycle transition remains non-reentrant and therefore cannot
mutate owner state from the nested path.

The existing reentrant allowlist also covers `completion-gate`, `complete-task`,
`manager-assessment`, and `manager-assessment-pool`; these are exercised by the
focused assessment/IPC suite rather than by the disposable child transcript.

## Owner boundary

The maintained-client `project-lifecycle-read --task J04` request did not return
within the bounded 30-second observation window. It was not retried, and no
controller, owner record, advisor, publication, or deployment state was edited.
The canonical manager must inspect that exact pending read request and perform
any permitted reconciliation, task completion, lifecycle transition, and
terminal project readback. This worker does not claim C07/C08 terminal project
completion from the disposable fixture alone.
