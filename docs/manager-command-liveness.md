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
