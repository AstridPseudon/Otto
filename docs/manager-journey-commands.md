# Otto manager-journey operator path

This run uses the root-owned manager service and its maintained command client.
The service owns canonical task, assignment, assessment, Due, and project records;
this document is a concise entrypoint, not a second state store.

## Read the current contract

Read the actual owner goal, criteria, active configuration, current manager guide
and accessible skill links in your delivered context. Their paths and task/model
routes belong to this pinned project; examples from another project do not grant
authority or budget. `status` supplies the current aliases, refs and handles.

Use the installed `ottoctl` beside the current controller's operator guide. It
pins its stdlib client interpreter separately from the owner service. Use its
absolute path from your delivered context, or from the controller directory:

```sh
CLIENT="$PWD/ottoctl"
"$CLIENT" --help
"$CLIENT" status
```

Do not open `owner.sqlite`, edit `canonical-state.json`, or hot-edit the pinned
controller. The maintained route for a scoped local checkpoint is:

```sh
"$CLIENT" commit --path docs/manager-journey-commands.md \
  --message "Document the maintained manager-journey command path"
```

Use only paths actually owned by your implementation role. The manager generally
delegates implementation and owns substantive judgment and bookkeeping.

## Ordinary progress and continuation

`report` records observed evidence and the next bounded action. A report that
requests continuation yields an exact report-key command; preparation and
dispatch are separate. Once that report-key continuation is delivered, perform
its substantive objective rather than redispatching its consumed trigger. Never
replace an unknown effect with a fresh key to guess at delivery.

Delegate with `run-worker --help`, the current task alias, configured route,
principal, exact logical request key and bounded focus. Use `worker-status` and
`command-status` for the returned retained handles. A worker result is evidence
for manager judgment, not automatic acceptance or task completion.

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
"$CLIENT" review-input --task J01
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

When an owner authorizes correction of a completed obligation, use a separate
corrective task and explicit local bookkeeping allocation. Preserve original
tasks, decisions and consumed units. Project sheet metadata can designate pinned
owner-authored SOURCE documents with schema `otto.completed-task-correction.v1`.
Each document pins the original completed task refs, completion hashes and gate
refs, names their exact criterion coverage, and designates a corrective task and
its authored outcome hash. This link does not accept or reopen either task.

Ordinary project close recognizes that linkage only after the corrective task
completes with genuine settled `wrk.result` candidate evidence and accepted
coverage of every designated original criterion. Closeout records the correction
source, preserved task refs, corrective task, candidate and gates in its acceptance
evidence. Missing work, altered history, wrong owner/scope, incomplete coverage,
instruction-only candidates and unsettled effects remain blocking.

`completion-gate` is a read-only provisional predicate. It must be supplied the
exact current candidate, accepted gate refs, and evidence refs when those exist;
`clear` does not itself record acceptance. Use the existing manager assessment
operations for substantive PASS/REWORK/UNKNOWN judgment and local bookkeeping,
then use `complete-task` only with the returned current refs and accepted gates.

Project close is a separate guarded operation after actual task completion. Use
`finish-project --help` for the complete JSON shape and response semantics. A
local delivery example is:

```sh
"$CLIENT" finish-project --request-key local-project-close-v1 --dispositions '{"acceptance":{"status":"passed","rationale":"All actual tasks retain accepted candidates and committed completion"},"publication":{"status":"qualified","rationale":"Local artifact delivery; publication is not required"},"remote":{"status":"qualified","rationale":"Local delivery; remote push is not required"},"runtime":{"status":"qualified","rationale":"Owner retains bounded callbacks and reconciles project-owned schedules"}}'
```

Choose each disposition from actual facts. Allowed statuses are `passed`,
`verified` and `qualified`; each needs a substantive rationale. This example
does not waive gates or establish acceptance, publication, remote delivery or
runtime settlement. The owner service binds the orchestrator and schedule
observer and supplies current lifecycle pins; operators need not assemble
low-level transitions or inspect controller source.

A `pending` reply retains its exact transport handle. Use `command-status
--request-id HANDLE` to recover that reply; keep the logical request key and do
not create another finish effect. If a finish waits on your own manager turn,
return so owner settlement can proceed. A terminal transport response can still
be held or unknown. Actual project completion requires the retained response's
`project_completion_recorded=true`, `settlement_pending=false`, and completed
`readback` with `reconciliation.status=reconciled`.

`project-lifecycle-read` reads current canonical state without mutation.
Completed command output or pending metadata alone does not prove project close.

For a cold journey, a fresh operator must use these same documents and commands to
submit work, receive a retained handle, issue nested status/report/assessment or
finish commands, reconcile any interruption without duplicate effects, complete a
task, advance, and verify the project terminal state. Supervisor-written per-step
instructions are not journey evidence.

## Historical host repairs

Earlier controller adoption and retry proposals are historical bootstrap evidence
in the run's execution observations. They are not operator instructions. Use the
current installed client and retained handles; never edit, adopt or restart a
live controller, reconstruct old requests, or replay an uncertain provider effect.
