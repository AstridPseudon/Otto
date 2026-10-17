# Goal: PROCLIFE — Otto process custody made structurally true

Replace redundant same-group descendant signalling with owner-held private process-group scopes. Persist launch and cleanup intent before side effects, use TERM then KILL, and report cleanup as settled only with supported evidence. Retain census/ancestry discovery for descendants that escape the private group, such as through `setsid`; signal only the exact birth-bound incarnation discovered through that lineage. An unresolved run keeps its own capacity conflict held; it must not latch unrelated host work. Keep task outcome separate from cleanup state.

Build on canon's CUSTODY (`db1ac48`), KILLFENCE (`e2f807b`), ORPHANWORKER (`ac02366`), and FAILCLOSED (`28408ce`) changes. The detailed task sequence and measured candidate deletions are in `.project/tasklist.md`.

## Invariants

- **G1 — settlement:** a scope settles only when evidence supports that no live process remains inside its declared private process group. A census gap, missing birth identity, unresolved recorded escapee, or interrupted cleanup remains `uncertain`/`unknown` and survives owner restart.
- **G2 — authority:** signal a private group only while its anchor is proven; an escaped descendant may be signalled only by its exact PID and birth identity after census confirms its tracked parent lineage. Parentage alone without a live, birth-matched parent, environment tags, or a bare PID do not grant signal authority. Reused process identities are left untouched.
- An accidental daemonization that was never recorded is an explicit containment limit; the implementation must not claim to have cleaned it up.
- Unknown native worker attempts are not retried. Physical capacity and custody are separate; an unknown holder blocks only its known conflict domain.

## Scope and exclusions

Keep the existing `Custody.launch/release/terminate` compatibility while migrating callers. The 15 Oct minimal design applies: no universal resource ledger, new resident daemon, general Scope/Lease framework, tag sweeper, per-descendant journal, speculative platform backend, or hardware-specific abstraction. Preserve the owner-claim, KILLFENCE, and ORPHANWORKER boundaries already landed.

The former Astrid film journey and its ~4,000-line deletion ambition are not runnable or measurable in this Otto clone. The agreed Otto deletion budget is 99 direct legacy lines, counted only as caller paths are replaced. The orchestrator will add PROCLIFE and that budget to program PLAN.md §14. The Astrid film and Otto staging checks remain external gates.
