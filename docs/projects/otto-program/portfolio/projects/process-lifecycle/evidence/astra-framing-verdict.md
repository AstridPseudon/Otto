**Verdict: the general problem is real, but the proposed universal contract is too strong.** Build durable cleanup obligations with explicit ownership, release authority, and evidence. Leases and owner-death enforcement are mechanisms available to particular backends, not requirements every resource can satisfy.

The general problem is **responsibility for effects that outlive the execution that created them**: something can remain running, billable, occupied, or sensitive after its task disappears. CPU versus GPU and local versus remote change the enforcement mechanism, not that responsibility.

The evidence checks out—with material corrections:

- **RunPod’s deadline is metadata.** The default is 7,200 seconds; `terminate_at` is calculated and written, with no consumer in Astrid or Runtime. `launch(config, name=...)` receives no maximum-runtime setting. The session’s `finally` cannot protect against SIGKILL. These findings establish missing enforcement in this path, not the absence of every possible external safeguard. [RunPod implementation](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Astrid/astrid/packs/runpod/shared/common.py:1038)

- **There is additional dependency evidence.** The repository contains a [candidate lifecycle wheel](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Astrid/artifacts/h3-candidate-wheels/runpod_lifecycle-0.3.1.dev0-py3-none-any.whl). Its `PodGuard` uses a local `asyncio` watchdog; its `RunPodConfig` has no runtime deadline field. That watchdog does not survive its process. This strengthens the concern, but a candidate wheel does not establish the deployed dependency’s behavior.

- **Teardown cost is indeed call duration, not pod lifetime.** `t0` starts immediately before teardown. Worse, `terminated_at` is written even for an error receipt. Treat that timestamp as an observation unless termination is confirmed; account for allocation-to-release exposure separately from command duration. [Teardown](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Astrid/astrid/packs/runpod/shared/common.py:1382)

- **The ledger shape is correctly described, but “60%” is unsupported.** Reservations are task-keyed, attempts carry fences and deadlines, and execution bindings allow the stated four statuses. However, `attempts.settled` is not proof of physical cleanup: ordinary expiry can mark an attempt settled and release reservations. Retention applies specifically to claimed/stale bindings with a verified actual target. [Schema](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Runtime/runtime_protocol/canonical_schema.py:59), [expiry handling](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Runtime/runtime_protocol/store.py:3100)

- **“GPU boolean, no VRAM” is inaccurate.** Reservations use opaque exclusive resource keys, checked per executor. Runtime also supports minimum `vram_bytes` execution facts. What is missing is quantitative VRAM allocation accounting, not all VRAM representation. [Facts](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Runtime/runtime_protocol/store.py:148), [admission](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Runtime/runtime_protocol/store.py:3433)

- **Inconsistent cleanup responses are real.** Generic host uncertainty blocks admissions; Remotion retains sticky uncertainty; local-worker replacement uses a durable file fence; storage reclaim reports failed removal. Those differences are not inherently wrong: failed cache deletion and an unidentified surviving writer have different consequences. [Host latch](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Astrid/astrid/core/execution/generic_host.py:5287), [worker fence](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Runtime/runtime_protocol/local_worker.py:426), [reclaim](${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/main-20261015/Astrid/astrid/sdk/storage_ownership.py:201)

**1. Right abstraction; smallest version?**

Use a **cleanup obligation**, containing resource identity, owner incarnation, release authority/reference, backend, affected conflict keys, state, and last evidence. Persist acquisition intent before the external side effect; a lost allocation response must remain representable before a resource ID exists.

Start with `acquiring → active → release_requested → settled`, plus unresolved outcomes and reconciliation. Separate task outcome from resource settlement.

Make lease expiry, maximum billable lifetime, and idle retention distinct policies. A renewable lease alone cannot impose a spending ceiling. A shared engine has one lifecycle owner and multiple borrowers; ending a borrower’s lease need not destroy it.

“Never block the whole host” must become “block the smallest **known safe** conflict domain.” Unknown surviving writers may justify a wider block. Retaining a reservation also does not stop ongoing charges.

**2. Runtime ledger, Astrid backends?**

**Yes.** Runtime should own durable obligations, fencing, atomic settlement/reservation transitions, and recovery scheduling. Astrid should supply resource-specific acquisition, inspection, and release adapters.

The ledger records responsibility; it cannot replace live kernel handles or provider authority. Preserve local recovery records until durable handoff works across crashes and Runtime outages. Delete redundant latches individually, not wholesale.

**3. First slice after the render fix?**

**RunPod’s spending safeguard first**, without waiting for ledger generalization. Verify and arm an independently enforced deadline at acquisition, retain unknown allocations, reconcile exact provider identities, and correct lifetime accounting. If provider-side enforcement is unavailable, state the weaker guarantee explicitly.

Acceptance must include owner SIGKILL and lost allocation responses. Then implement PL3/PL4 together narrowly: explicit service ownership plus scoped cleanup obligations.

**4. What must NOT be built?**

No universal resource orchestrator, mandatory heartbeat for every scratch directory, second ledger, generic GPU scheduler, per-descendant journal, or promise that every backend is thin. Do not equate cancellation requests, expired leases, lock release, or operator overrides with confirmed destruction. Do not erase unresolved billing exposure merely to unblock scheduling.

This was a read-only code review; no live cleanup or failure tests were performed.