# Otto manager-journey operator path

This run uses the root-owned manager service and its maintained command client.
The service owns canonical task, assignment, assessment, Due, and project records;
this document is a concise entrypoint, not a second state store.

## Read the current contract

Before acting, read these exact run artifacts:

- `agent_goal.md` — objective, authority, and non-goals
- `tasklist.md` — C01–C08 and the evidence required for each criterion
- `run.yaml` — active model routes, local assessment allowance, and review limits
- `plan.md` — integration order and cold-journey validation
- `manager-guide.md` — current manager instructions
- `work/integration-owner/policy-staging/megado/skill/SKILL.md` — accessible Megado protocol

The working checkout is:

`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/work/integration-owner`

The maintained client is:

`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/controller/manager_ctl.py`

Use it with the run's pinned interpreter:

```sh
PYTHON=/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python
CLIENT=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/controller/manager_ctl.py
"$PYTHON" "$CLIENT" --help
"$PYTHON" "$CLIENT" status
```

Do not open `owner.sqlite`, edit `canonical-state.json`, or hot-edit the pinned
controller. The supported owner route for a local checkpoint is `commit`:

```sh
"$PYTHON" "$CLIENT" commit --path docs/manager-journey-commands.md \
  --message "Document the maintained manager-journey command path"
```

## Ordinary progress and continuation

Record evidence and the next bounded action with `report`. When a report requests
continuation, consume the returned exact command with `manager-continue --operation
prepare`; preparation is not provider replay. Dispatch is separate, and an
unknown current manager effect remains held until its owner disposition is
recorded. Never retry a new request key merely because a prior provider result is
unknown.

Delegate through the current task route:

```sh
"$PYTHON" "$CLIENT" run-worker --task J01 --route xhard \
  --principal journey-integration-1 --request-key journey-j01-worker-v1 \
  --focus "bounded connected J01/J02 implementation and evidence"
```

The J01/J02 integration owner is the single Sol route. J03 and the cold operator
use the normal route. A worker result is evidence for manager judgment, not an
automatic acceptance or task completion.

The owner service retains settled worker-result delivery to the same manager.
After the last accepted finish intent actually commits and that manager turn
settles, it also retains one same-manager closeout inspection. Neither delivery
creates a progress report or accepts the project. A repeated observation resolves
the same occurrence; an unknown manager effect blocks another dispatch. Return
from a turn whose finish is pending on its own settlement. Inspect its retained
handle rather than redispatching it, polling indefinitely, or repeating tests.

## Judgment, completion, and project close

Discover the canonical result of an existing worker before choosing review refs:

```sh
"$PYTHON" "$CLIENT" review-input --task J01
```

This read returns the exact `wrk.result` candidate, source/evidence references,
worker result digest and native identity. `worker-status` also returns this view
after success. Read the actual artifact, task outcome and criterion before
`review-task`; transport success is unjudged evidence. Verify promised paths as
well as contents. A useful alternate filename does not fulfill a task that
explicitly promises another path.

Use each resource-ref JSON object as returned: `--candidate-ref OBJECT` and one
`--source-ref OBJECT` flag per source. Do not pass an array to a single source
flag. Supply a judgment for every configured criterion with `verdict`,
`rationale` and `evidence_refs`, and include the actual candidate in those
evidence refs. The assessment owner's rationale field is an identifier and
does not admit slash, backslash or NUL; put paths and substantive observations
in `--inspection`. Instruction GUIDE/MANDATE documents describe requirements
and authority; they cannot substitute for delivered artifact candidates.

An older schema-valid acceptance can still have wrong candidate provenance.
The service preserves such decisions, completions and consumed allowance, but
holds project acceptance with the affected task refs. Inspect the retained
records and obtain an authorized correction; do not relabel the candidate,
reset the pool, or blindly submit another review.

`completion-gate` is a read-only provisional predicate. It must be supplied the
exact current candidate, accepted gate refs, and evidence refs when those exist;
`clear` does not itself record acceptance. Use the existing manager assessment
operations for substantive PASS/REWORK/UNKNOWN judgment and local bookkeeping,
then use `complete-task` only with the returned current refs and accepted gates.

The project close is a separate maintained operation. First read the current
lifecycle and revisions:

```sh
"$PYTHON" "$CLIENT" project-lifecycle-read --task J01
```

Perform a lifecycle transition only with the exact expected generation, project
revision, task revision, evidence, and obligation returned by the owner read.
After task completion, read the project lifecycle again and retain the terminal
readback. Completed commands, six finished steps, or a pending metadata record do
not prove project close.

For a cold journey, a fresh operator must use these same documents and commands to
submit work, receive a retained handle, issue nested status/report/assessment or
finish commands, reconcile any interruption without duplicate effects, complete a
task, advance, and verify the project terminal state. Supervisor-written per-step
instructions are not journey evidence.

## Observed host boundary

The fresh J04 run reproduced a real command-lane dependency cycle. The outer
`run-worker --task J04 --request-key journey-j04-cold-v1` was admitted as
`worker-765555adea732a77f135cbe17e01` and reached physical session
`01a10c5b-2f05-7612-bee5-5e76e2a695db`. Its retained host receipt contains the
initial READY turn. The worker then submitted the nested
`project-lifecycle-read --task J04` request, which remains queued behind the
outer request; the manager's same-lane progress report is queued as well. This
is terminal evidence of the synchronous command dependency, not evidence of a
completed journey.

The host-only adoption request is bounded to the pinned controller's
`manager_server_baseline.py:779`: schedule `app.start(...)` through the already
available `ExecutionHost.retain` (or an equivalent owner-approved retained
operation), return the durable handle to the caller, and keep the existing
occurrence/reconciliation semantics. Add a host-level regression proving that
an admitted worker can issue a nested `status`/lifecycle read while the worker
operation is active, then retry the same J04 request only after the host
reports the prior occurrence reconciled. The worker must not edit or restart
the controller.
