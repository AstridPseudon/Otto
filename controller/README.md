# Maintained owner-service handoff

The runnable controller remains the existing outside-Git service at:

`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-advisor-20260930/work/canonical-bootstrap/controller`

The canonical maintained source is the adjacent `manager-worktree`. Before
adopting runtime changes, stop the service through its explicit stop file, wait
for the process to exit, update `controller/runtime-source` from the committed
source, refresh `controller/execution-runtime-source-manifest.json`, remove the
stop file, and restart the same entrypoint. Never hot-edit runtime source while
the owner holds the Store.

Use the compatible interpreter and service entrypoint from the documented host:

```sh
cd /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-advisor-20260930/work/canonical-bootstrap/controller
/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python \
  serve_manager_owner.py --stop-file /Users/hannahomalley/Documents/Codex/2026-10-04/otto-owner-service-stop
```

Wait for `outcome=ready`, then invoke the maintained client from `controller`:

```sh
/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python \
  ../manager-worktree/manager_ctl.py status
```

`status` is the compact current read. `completion-gate --task PA02` is a
read-only provisional predicate and records no acceptance. Use `report` for a
manager progress/next-action record, `run-worker` for a fresh bounded task, and
`resume-worker` only after inspecting the exact reconciled existing occurrence.
Use `commit --message ... --path ...` for an owner-authorized local checkpoint.
The source command surface also includes the existing advisor and completion
operations; their identity, allowance and unknown-effect fences remain
canonical. Do not replay PA01 or PA06, reset advisor allowance, or invoke a
new advisor/reviewer from this handoff.

The service performs no automatic manager, worker, advisor, timer, or review
launch on startup. Keep the stop file absent while the service is intentionally
running. The paused product automation proposal and its exact readback/
acknowledgement sequence are recorded in the successor run's `work/` receipts;
creating that paused app automation is a separate root-host lifecycle operation.

The maintained owner-admission tick for an existing advisor effect follow-up is
also available through `manager_ctl.py advisor-followup`. It defaults to a
read-only status read:

```sh
/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python \
  ../manager-worktree/manager_ctl.py advisor-followup \
  --schedule-id advisor-followup-27a599f6cadb57bb25884b7d9627 \
  --decision-id decision-pa06-delivery-boundary-v1 \
  --operation status
```

An explicitly authorized active tick may use `--operation dispatch`; it passes
only those existing IDs into Otto's pairing, Due, allowance, and provider
admission path. It does not wake the advisor thread directly, create a new
occurrence, or reset the exhausted PA06 allowance. A paused, pending, or failed
canonical trigger is held, and an ambiguous dispatch remains unknown with no
retry. The native advisor thread is a valid identity for the paused binding,
but an active automation must notify the owner/controller path first so Otto
admission runs before any native advisor turn.

For a cold operator, read the successor run's `status.md`, `tasklist.md`, and
`execution-observations.md`, then use the exact source head and runtime manifest
readback before any mutation. The current canonical commit is obtained with
`git -C ../manager-worktree rev-parse HEAD`; do not infer it from a narrative
note or from a stale historical controller patch.
