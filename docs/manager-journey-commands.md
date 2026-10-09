# Otto manager-journey operator path

This run uses the root-owned manager service and its maintained command client.
The service owns canonical task, assignment, assessment, Due, and project records;
this document is a concise entrypoint, not a second state store.

For the setup/help distinction and recovery matrix, use the maintained
[operating setup and help guide](operating-setup-and-help.md). This document
keeps the longer worker, assessment and closeout journey.

## Adding a new agent CLI adapter

An adapter is a bounded owner-backed provider binding, not a parser-only
integration or a generic promise that any CLI is supported. Keep the existing
composition (`PortfolioOwnerBootstrap` → `ExecutionApplication` → `OttoGateway`
→ injected adapter), assignment/Due custody, native caller binding and
Recovery reconciliation. Pin the real launcher path, version/hash, parser
shape and adopted resources. Provider-supplied IDs, flags, model names and
capability claims never grant authority.

The minimum useful qualification has four layers: authentic or synthetic
parser fixtures; owner-fault fixtures with effect counters; local process/pipe
or socket custody; and one bounded installed journey for each qualified
adapter. Prove, in order:

1. owner admission, native identity, admitted input and effective scope before
   useful provider work;
2. one useful tool or artifact and a bounded native result/error mapping;
3. canonical capture/settlement, retained result identity and authorized
   bounded artifact access;
4. parent consumption, stop/recovery behavior and the capability status of
   attach, resume, cancel, steering, streaming and native children separately.

Each capability is `supported`, `unsupported`, `degraded` or `unverified`,
with evidence, reason and pins. A process handle, initializer-only response,
parser fixture or all-unsupported provider descriptor is not useful adapter
qualification. A native terminal or exit code is not task success until the
required capture and canonical result publication are verified.

Claude is mechanically qualified in this candidate only: native fixtures,
host-scope checks, existing-login metadata and parser/transport evidence may
qualify mechanics. Paid Claude initialization, inference, resume and useful
provider artifact delivery remain unverified and must not be claimed. Native
usage is `available`, `invalid` or `unavailable` as actually observed; missing
usage is not zero cost, and no totals, prices or descendant sums may be
inferred. External orchestrators use a separately installed protected `owner-execution`
capability for finite launch, lookup, follow, result, artifact and consumption.
The host pins root/project/task, worker route and allowance; request JSON cannot
select identity, privilege or budget. The exact root input grant and canonical
parent/result association are retained. Installation requires explicit host
policy and actual authenticated use; native process identity is not claimed.
Never borrow a
manager identity or backfill external-session observations as Otto
admission.

## Launch, inspect, stop and recover agents

Use the exact installed prefix emitted by the current role introduction. The
current candidate inspection used this host-installed command; it is a pinned
inspection fact, not a repository wrapper or a claim that a package has been
adopted:

```sh
PYTHON="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"
CONTROL="/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-agent-adapter-conformance-20261009/controller/manager_ctl.py"

"$PYTHON" "$CONTROL" --help
"$PYTHON" "$CONTROL" run-worker --help
"$PYTHON" "$CONTROL" lookup-occurrence --help
"$PYTHON" "$CONTROL" follow-occurrence --help
"$PYTHON" "$CONTROL" read-result --help
"$PYTHON" "$CONTROL" read-artifact --help
"$PYTHON" "$CONTROL" consume-result --help
"$PYTHON" "$CONTROL" execution-control --help
```

The ordinary bounded journey is:

```sh
# Manager/coordinating-worker only, after current scope/readiness and
# authenticated delegation are established.
"$PYTHON" "$CONTROL" run-worker \
  --task TASK \
  --route normal \
  --principal CHILD_PRINCIPAL \
  --request-key STABLE_REQUEST_KEY \
  --focus "bounded implementation focus"

# If the first reply is lost, read the exact request; do not submit a new key.
"$PYTHON" "$CONTROL" command-status --request-id TRANSPORT_HANDLE
"$PYTHON" "$CONTROL" lookup-occurrence \
  --scope '{"project_ref":PROJECT_REF,"task_ref":TASK_REF,"parent":PARENT_BINDING}' \
  --request-key STABLE_REQUEST_KEY \
  --request-input ORIGINAL_EXACT_INPUT

# Use the returned occurrence object, not a schedule guessed from a name.
"$PYTHON" "$CONTROL" follow-occurrence \
  --occurrence OCCURRENCE_JSON --timeout-seconds 2
"$PYTHON" "$CONTROL" read-result --occurrence OCCURRENCE_JSON
"$PYTHON" "$CONTROL" read-artifact \
  --occurrence OCCURRENCE_JSON \
  --artifact-ref ARTIFACT_REF_JSON --offset 0 --max-bytes 65536
"$PYTHON" "$CONTROL" consume-result --occurrence OCCURRENCE_JSON
```

The durable occurrence handle contains the schedule, assignment, generation,
project, task and parent binding. It is distinct from the outer command
request ID, provider/start handle and callback/transport handle. Exact lookup
uses the original scope, stable request key and original input fingerprint;
changed input, changed parent or an ambiguous/missing match is an actionable
conflict, never a fresh launch. `follow-occurrence`, `read-result` and
`read-artifact` are bounded reads. They observe the same occurrence and do not
cancel, resume, reconcile or accept it. `consume-result` is the authenticated
parent-consumption receipt; a pending notification alone is not consumption.
Artifact refs must come from retained owner records and are read with a bound,
not an arbitrary response-supplied path.

Results keep separate facts for useful admission/native identity, native
terminality, required capture, occurrence settlement, parent delivery and
task assessment. A result may be readable before callback delivery finishes.
`succeeded` without verified canonical capture is held; `unknown` is not a
successful terminal result. Repeated reads have no duplicate callback,
completion or debit effect. Preserve the exact result/disposition revision and
artifact digest for manager judgment.

If the manager/coordinating worker's active turn prevents retained delivery
from proceeding, return/yield with the occurrence and transport handles plus a
next action; never wait indefinitely inside the same turn or run overlapping
parent turns. Use the existing owner report route when authorized:

```sh
"$PYTHON" "$CONTROL" report \
  --task TASK --request-key REPORT_KEY \
  --summary "retained child handle and bounded next action" \
  --next-action "consume the same occurrence after continuation" \
  --continue-project
```

Local capacity one requires an actually eligible released-capacity or
authorized reentrant path. Waiting does not create a hidden slot. A leaf gets
one bounded assignment, executes it and returns evidence; it does not
recursively redelegate an unchanged brief, accept its own task or consume a
manager allowance.

Resolve defaults at admission as explicit authorized override → applicable
project/role configuration → user default. Show the selected adapter/CLI,
model, reasoning, profile, source/resource refs and provenance in the retained
selection. Defaults affect future admissions only; there is no silent provider
or model fallback. The current inspected worker was bound to assignment
`assignment-4b9823050f1a429d60c0ffbabee7`, generation `1`, principal
`otto-adapter-d05-worker-1`, model `gpt-5.6-luna`, reasoning `high`, and native
adapter `otto.adapter.installed-codex-cli.v1`. The observed `whoami` and
`effective-context` reads were read-only, provider-free and had
`effects_started=false`.

For recovery, read the exact retained command or occurrence before acting:

```sh
"$PYTHON" "$CONTROL" command-status --request-id TRANSPORT_HANDLE
"$PYTHON" "$CONTROL" execution-control --operation read --schedule-id SCHEDULE_ID
"$PYTHON" "$CONTROL" execution-control --operation recover --schedule-id SCHEDULE_ID
"$PYTHON" "$CONTROL" execution-control --operation stop \
  --schedule-id SCHEDULE_ID --request-key STOP_KEY \
  --expected-version VERSION
```

`command-status` is a pure retained transport read. `recover` may capture or
settle, so it is not a pure read. Stop fences the exact owned occurrence and
reports requested versus observed cleanup; it does not by itself prove native
process termination. Reconnect observes the same occurrence and never restarts
a stopped one. After host restart or installation, reconcile retained attempt,
capture and delivery before admitting new work. A missing help destination,
external-root launch or unavailable native control remains a truthful host
limitation with its next actor; it is not a successful delivery or permission
to replay provider work.

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

### Authenticated external orchestrator commands

The protected host client exposes `launch`, `lookup`, `follow`, `result`, `artifact`
and `consume`. Read the current root `effective-context`, installed Otto skill and
host-issued finite execution policy first. A launch takes one stable request key
and factual focus; the owner selects principal/model/profile/scope/resources.
Retain the separate returned occurrence, start and outer transport handles.
`lookup` takes the original key. `follow`, `result` and `consume` take the exact
returned occurrence. Artifact reads take a returned known artifact ref and a
bounded range. Consumption is an idempotent root assignment report identifying
the original external parent and captured result. Follow and result are pure;
launch and consumption require a separately protected execution grant.
Neither public file IPC nor direction/authoring grants authorize these effects.

For this installed host, use the host-issued `adapter_external_execution_ctl.py`
companion next to the owner-context client. Its `--send` transports the exact
protected envelope once; retain its response path and inspect that same path
after a timeout. Do not recreate an occurrence or borrow manager/native credentials.
