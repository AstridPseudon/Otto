# The general problem behind PROCLIFE (claim for review, 15 Oct 2026)

## Claim

PROCLIFE as scoped (process scopes) solves one instance of a more general problem. The general problem is this: Astrid acquires things that cost something or have side effects (processes, VRAM-holding engines, remote GPU pods that bill, provider jobs, scratch storage, capacity slots, credentials copied to disk), and it has no single answer to three questions:
1. Who owns this?
2. What releases it when the owner disappears?
3. What happens when release cannot be confirmed?

The right level of abstraction is not a process container. It is an **owned resource with a lease, a dead-man's switch, and a settlement record in the Runtime ledger**:
- **Owner + lease.** Every resource has one owner, an executor incarnation or the host, and a renewable lease. The lease deadline is liveness policy, not a correctness proof.
- **Dead-man's switch.** Release must happen when the owner disappears, enforced by something that outlives the owner. Examples:
  - a lifeline pipe or session for processes;
  - flock for slots;
  - a provider-side TTL or self-termination for pods;
  - a provider-side timeout or cancel for API jobs;
  - TTL garbage collection for scratch.

  Where no such switch exists, a reconciler acts on lease expiry.
- **Settlement in one ledger.** Release yields `settled` (evidence of release) or `unresolved` (named survivors or unknown state). The record lives in the Runtime's existing SQLite ledger, not in file latches or memory.
  - An unresolved resource keeps its reservation (capacity or cost) and blocks only conflicting reuse of that resource, never the whole host.
  - It is resolved by later evidence, provider confirmation, or an explicit operator action.
- **Backends per kind, thin.** POSIX process group, Linux pidfd or cgroup, Windows Job Object, RunPod terminate, provider cancel, rmtree. Each is a small adapter over existing release code. Capacity and placement (VRAM, which GPU, which machine) stay a separate scheduling concern; they share only the reservation rows.

## Evidence (15 Oct, read-only mapping; see PROCLIFE evidence/)

- **About 12 lifecycle mechanisms in 4 failure families.** On "release unconfirmed":
  - **Latch and block the whole host:** the Remotion in-host session, the Codex attempt home, attempt roots, the network broker, and the pack host.
  - **Release anyway, log survivors:** otto-heavy.
  - **Report and move on:** storage reclaim.
  - **Lose the handle:** the launchd frame owner, after a timed-out submit.

  The same outcome means "blocked" in some places and "free" in others.
- **GPU paths each carry their own contract:**
  - RunPod has a per-handle `cleanup_pending` file state, manual teardown, and a pidfd stop that duplicates the custody broker.
  - VibeComfy uses `custody_broker`.
  - Wan2GP uses process groups and an flock that a live orphan keeps forever.

  The Runtime models GPU as a boolean `gpu` reservation, with no VRAM.
- **Money risk, verified:** RunPod `terminate_at` (default now + 2 h) is written to the pod handle but never read or enforced by Astrid. A SIGKILLed session skips `finally`, so nothing tears the pod down. Whether the external `runpod_lifecycle.launch` sets a provider-side auto-stop is unverified; the package is not installed here. The teardown cost sidecar times the teardown call (`t0` at teardown), not pod uptime.
- **The Runtime ledger is about 60% of the general model, for tasks only:**
  - `reservations` (task_id, resource_key, released_at), `attempts.settled`, and `execution_bindings` (prepared|claimed|stale|released) with fences and 30 s leases;
  - `provider_state_unknown` keeps reservations held until an explicit recovery.

  Unresolved is a `waiting_reason` string. The local worker, the custody broker and the process handles keep their own file latches outside the ledger.
- **Today's render failures** (1 s custody cap, host latch, retirement blocked, otto-heavy sweeping the host) are all cases of "release or ownership proven by observation or by markers, not by a dead-man's switch plus ledger".

## What would change in PROCLIFE

- PL2 (process scopes) and PL3 (the host as service owner) become the first two backends.
- PL4 (scoped obligations) becomes "unresolved is a ledger row, keyed by resource".
- Add the RunPod backend: a provider-side TTL as the dead-man's switch, plus a correct cost record.
- Add a reconciler on lease expiry.
- Delete the file latches.

## Questions

1. Is "owned resource + lease + dead-man's switch + ledger settlement" the right abstraction level, or is it over-general? What is the smallest version?
2. Should the ledger generalization live in the Runtime (product-neutral), with backends in Astrid?
3. What should be the first slice after the render fix: the RunPod dead-man's switch (money), or PL3/PL4?
4. What must NOT be built?
