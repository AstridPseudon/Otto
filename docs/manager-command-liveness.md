# Ordinary manager command liveness

The owner command lane remains serialized while an admitted manager waits on its
native child. The owner pumps supported finite commands, including the maintained
local `commit`, on that same thread. Git checkpoint effects and Store callbacks
must not move to an unlocked worker thread.

The live failure was an omitted capability: the nested allowlist admitted report,
assessment and finish operations but omitted the documented commit operation.
The native manager waited for its commit response while its outer dispatch held
the command lane. The original commit ran only after that manager exited. Earlier
tests exercised several nested commands but did not exercise the supported local
checkpoint through the same outer dispatch. The regression now runs a real child
process against file IPC and the maintained Git checkpoint, proving the response
arrives before child exit and owner mutations stay serialized.

Unsupported nested operations return a finite `held` response with no effects,
no automatic retry, and directions to return the result to the manager. A second
manager provider dispatch stays retained rather than overlapping the current
turn. Its `pending-<request_id>.json` receipt identifies the exact future response
path. The installed client can return this pending handle and read it through
`command-status --request-id <handle>` without sending a second request. Pending
does not mean failure or missing effects. Preserve the request and terminal
response; inspect that exact handle after settlement. Do not invent another key,
repeat the send, poll by rerunning tests, or claim adoption has happened while
waiting. Report the concrete blocker and next host action, then let the current
turn settle.

Owner installation must guard the entire host lifetime, including ready output,
bootstrap invocation, result serialization and handler installation. The observed
idle owner was already in Python finalization with two non-daemon service threads
alive; the root entrypoint placed those bootstrap operations before its cleanup
guard. The particular exception that triggered finalization was not captured.
An output failure is one possible trigger, not an established diagnosis. Use the
existing host context manager or a `try/finally` surrounding start and all later
operations. Keep admitted healthy work through settlement, then close command and
status threads and Store. The regression verifies an early bootstrap exception
leaves no idle host threads or owner file.

Focused checks from the source checkout:

```sh
PYTHONPATH=src "$PYTHON" -m unittest tests.test_manager_reentrant_ipc tests.test_manager_journey_service tests.test_manager_journey_command tests.test_execution_application -q
```

These fixtures support J05/C09 judgment. They do not mark that task accepted or
prove the installed cold journey; retain native and installed receipts separately.

Adding an owner-authorized task can advance the current project revision while a
successful manager anchor retains its older project snapshot. A bound manager
callback refreshes that same project's reference through an identity-fenced
canonical read and public Due CAS before the gateway claim. Its receipt preserves
the before/current project references and original Due version. The execution
task, reported task, mandate, native session, assignment, generation and invocation
identity remain unchanged. Foreign project scope is rejected. Attempted callbacks
keep their original pins and are reconciled through retained evidence.

If dispatch returned `partial` before the gateway, inspect the exact callback's
gateway evidence. After the correction is installed and no gateway attempt is
confirmed, use the same report key and occurrence for public continuation
dispatch. Do not invent a new report, callback or model invocation to bypass the
failure. The regression reproduces the stale-project error and then resumes that
same occurrence through real canonical briefing, gateway and fake provider
settlement; provider replay remains fenced.

Terminal `command-status` now returns a bounded typed summary plus the exact
response path, SHA256 and byte count. Full transport bytes stay in the artifact;
large responses must never be embedded recursively in another native command
output. Installed clients use `read_command_response` for terminal reads and
`read_command_status(..., pending_only=True)` while waiting. A response that
arrives between those reads is consumed by the next terminal read, preserving a
worker's retained handle rather than confusing it with the outer submission.
The IPC pump skips its own active token before classifying a second provider
request as pending. Observe the original handle; pending receipts belong only
to distinct queued requests.

A manager explicitly authorized for canonical manager commands may advance its
project and task revisions during work. Admission still checks the full owner
snapshot. Terminal verification checks the same native admission and claim,
unchanged assignment and mandate, current identity and membership, and the exact
admitted brief/contract/context evidence. Task acceptance remains a separate
substantive operation. Ordinary workers retain the full post-work scope fence.
The old failure discarded the explicit post-work authorization error and selected
an unrelated oversized CLI-candidate diagnostic recursively. New records preserve
the adapter error; historical UNKNOWNs require public retained-evidence
reconciliation, never provider replay or altered transport bytes.

Owner run policy may declare `worker_operation_profiles` with task aliases mapped
to `implementation` (default) or `cold_manager_operation`. Caller focus cannot
grant this capability. Cold operation instructions authorize the assigned
installed journey through canonical manager commands and require actual receipts;
they do not ask for source implementation. The parent manager judges the cold
operator task. Contract roots come from the actual selected adapter's worktree and
writable roots, and invalid task profiles fail before assignment or initialization.
After a READY-only contract failure, preserve that occurrence, append an owner
disposition, reassign the same observed idle session through public assignment
operations, adopt the corrected guide/mandate and prepare a distinct first-work
RESUME. A new key alone does not authorize replay of UNKNOWN work.


A project manager remains accountable after completing the task that anchors its
execution. The next ordinary report-key continuation refreshes that same task's
revision only when canonical completion evidence exists. It creates a distinct
mandate document by copying the retained content and changing only the mandate
and instruction-contract task revision pins. The old occurrence and mandate
remain readable. Permissions, manager assignment/generation, native session,
report intent and task identity do not change. The prospective Due CAS records
both task/mandate refs and content digests; duplicate dispatch consumes the same
receipt and never calls the provider again. An attempted occurrence is immutable.

Canonical briefing accepts a completed execution task only for a project-scoped
active manager with an exact current manager mandate and canonical manager
command authority. Workers/advisors still require active task state. A changed
uncompleted task, changed contract, adopted-mandate resource, stale assignment,
foreign scope or unknown effect requires the corresponding explicit owner
operation; no report text grants those changes.

Previously the final task completion made the preserved task/mandate revisions
stale, then the generic active-task rule also rejected the legitimate remaining
manager/project-close turn. Verification stopped at task completion and invoked
project close from an external test caller without traversing that continuation.
The installed-service regression now traverses retained native worker result,
substantive review and real completion, a new same-session manager continuation,
repeat dispatch and ordinary terminal project close. This is fixture coverage;
authentic cold journey evidence still requires the actual installed operator.

Retained manager settlement compares the instruction contract in the admitted
brief with the canonical mandate using the same maintained normalization used
at admission. An authored trailing newline does not imply changed authority.
The full admitted brief digest, unchanged mandate/assignment, native admission,
contract evidence and parsed result fences still apply. A successful native
result may remain `partial` at owner settlement; inspect and recover that exact
occurrence with execute=False instead of replaying its provider work.

Ordinary manager lifecycle reads first authorize the exact current manager
assignment and constrain project/task/manager refs to the service binding. The
service then uses its finite owner's project read grant. This supports an owner
issuer distinct from the native manager without giving the manager a raw reader
or allowing caller-selected project scope.

A manager cannot await its own current turn's settlement. Record a continuation
report and return; the owner finalizes the turn and consumes the report. An
unsettled self-continuation returns that explicit next action. A delivered
continuation identifies the report already consumed by this invocation and asks
the manager to carry out its substantive next action, avoiding redispatch of the
same report. A native-success inner result is not proof of owner settlement and
must not trigger automatic continuation while the occurrence is still active.

The primary instruction of a bound manager continuation advances the adopted
contract objective. The triggering report's next action remains attributed
planning advice in `current_intent.reported_next_action`; it is not copied into
the primary work instruction. Otherwise a report saying "dispatch this report,
then deliver" can turn a delivered work invocation into another dispatch-only
turn. Do not put temporary startup-only work into the enduring mandate's
continuation direction. A phase change uses public document/adoption and role
preparation with a corrected brief, the same native manager and a distinct
intent; attempted occurrences and their reports remain immutable.

Successful worker settlement retains one deterministic result notification on
the same owner command lane. It resumes the same manager to inspect the actual
result and continue ready work, without inventing a manager progress report or
accepting the task. If the manager is still active, the notification remains
pending without preparing another occurrence or overlapping a native turn.
Restart/duplicate delivery consumes the exact callback through its attempt
fence. A completed task suppresses redundant result review; an unknown manager
effect returns an actionable hold. Draining never admits a new native turn.

Previously a manager could return while its worker was pending, and successful
worker settlement only wrote the worker response. The startup continuation
check had already run and found no explicit report; nothing woke the manager
afterward. The connected regression now waits for the retained result wake,
then traverses review, completion, continuation and terminal project close.
Another lane regression covers worker-first settlement, pending result
delivery until manager settlement, and duplicate notification without replay.
These are fixture qualifications; authentic cold acceptance still needs the
installed operator's artifacts, judgments and terminal records.
