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


`report --continue-project` returns the explicit handoff command
`manager-continue --report-key <original-key> --operation prepare`. The ordinary
service consumes the durable owner report through that command, including
reports submitted after a manager turn. See
[final-review-closures-README.md](final-review-closures-README.md) for identity,
unknown-result, restart and provider-free lifecycle details. Prepare consumes
one current-task request into the existing manager's callback; dispatch is
held while the current manager effect is unknown. The lifecycle command reads
the adopted PAUSED automation and exercises existing production rejection
guards with explicitly inert Due/resource projections and the existing 3/3 pool.

Host capability inspection separates the optional direct owner HostTriggerPort,
the supported external prepare/execute-or-recover/readback/ack bridge, and actual
scheduled firing. Missing direct port does not disable the external bridge.
`ExecutionHost.reconcile_trigger` is the existing bridge-aware lifecycle caller;
its scoped stop/terminal-completion transitions reconcile external PAUSED state.
Low-level Due stop/complete remain owner state only. Exact readback and owner ack
prove reconciliation, not firing. A worker-local tool approval error does not
apply to a root context whose authorized automation view succeeds. See
`final-review-closures-README.md` for the retained PAUSED evidence gap.

`manager-continue --operation dispose-no-overlap` appends one owner report scoped
to an already-prepared explicit report-key continuation. It validates the expected
current and continuation Due versions/IDs, project, manager principal, generation,
native session and last completed anchor turn. The old record must remain terminal
unknown with no in-flight request, explicit false process/session creation evidence,
no observed new turn and a retained `preprovider_unknown` result. False creation
flags alone never authorize an uncertain existing-session effect. The disposition
neither rewrites that unknown nor launches a provider. Repeated identical requests
replay the same owner report. `manager-continue --operation dispatch` revalidates
the entire scope and old Due fingerprint before admitting that same report key;
changed Due versions, another report key or a new callback attempt keep dispatch
held. The global unknown guard remains in place for all other intents.
