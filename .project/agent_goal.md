# Goal: PROCLIFE: process lifecycle made structurally true

Replace per-descendant custody (live observation under fixed sub-second budgets, and a host-wide latch) with owner-bound scopes. Prove it on the real film under normal load, then delete what it replaces.

**Why (15 Oct evidence, `evidence/proposal-20261015.md` §1):**
- On Astrid main (22b59e34), the film journey failed only at the render. Every symptom came from lifecycle proof machinery:
  - the 20 s start budget;
  - the 1 s reconciliation cap and the latch it trips;
  - "retirement blocked";
  - 223-context launch validation taking 6.5 min, plus a `scripts` name collision;
  - otto-heavy sweeping the host.
- The live line, which has no `custody_broker.py`, renders the same film every day.
- Codex's own full-film runs on recent tips (films 11–13) also ended unresolved.

**Threat model (Astra's wording, `evidence/astra-verdict.md`):**
- **G1:** a scope is settled only after its backend confirms that no live processes remain within its declared containment boundary. POSIX covers group members and explicitly registered services while cleanup ownership survives. Accidental daemonization, environment sanitization and owner crashes are stated limitations that report `unresolved`.
- **G2:** Astrid lifecycle code signals only an anchored private group or a registered incarnation-bound handle. Missing authority produces unresolved cleanup. This does not defend against malicious same-user processes; SECURITY.md already says pack code has the user's full power.

**API:** `spawn(owner, spec, lifetime="task"|"service") -> Scope`, `lease(service, task)`, `release(lease)`, `stop(scope, grace) -> Report`, `status(scope) -> Report`. Reports separate the execution result from cleanup state (`running` / `settled` / `unresolved`) and include backend coverage.

**Deletion budget (about −4k lines):**
- the ordinary-command per-descendant path in `custody_broker.py`: `ProcessCustody.start_observer`, `observe_census`, `_register_census_candidate`, `_candidate_reconciliation_deadline`;
- reconciliation in `process_group._observe_tree`;
- the host-wide `generic_host._latch_cleanup_uncertainty` admission block;
- the cross-process recognition in `host_bootstrap.py`: `_pin_native_host_command`, `_framework_reexec_of_launch`, and `_darwin_host_command_observation` as lifecycle authority;
- startup-wide render validation: `_prepare_render_validation`'s worker enumeration and `_settle_registries`' cross-context loop.

Runtime custody and shared control-peer code are deleted only once their callers are proven gone.

**Do not build:**
- universal tag sweepers (tags are discovery hints, never signal authority);
- another resident daemon (the pack host is the owner);
- per-descendant journals;
- generic container-runtime orchestration;
- speculative Windows plumbing (Job Objects come only before claiming Windows);
- caching before measurement;
- hardware-specific lifecycle abstractions.

No Codex gating (user, 15 Oct): this is Claude's job. Rules: `portfolio/PLAN.md` §15.

**Rescoped 15 Oct (evidence/resource-lifecycle-framing.md, evidence/astra-framing-verdict.md).**
- **The general problem:** responsibility for effects that outlive the execution that created them: running, billable, occupying, or sensitive. CPU/GPU and local/remote change only the enforcement mechanism.
- **The abstraction is a durable cleanup obligation:** resource identity, owner incarnation, release authority/reference, backend, affected conflict keys, state, and last evidence.
  - Acquisition intent is recorded before the external side effect, so a lost allocation response stays representable.
  - States: `acquiring → active → release_requested → settled`, plus `unresolved` and reconciliation.
  - Task outcome is separate from resource settlement.
- **Lease expiry, maximum billable lifetime and idle retention are distinct policies.** Leases and owner-death enforcement are backend mechanisms, not universal requirements.
- **Block the smallest known-safe conflict domain.** An unknown surviving writer may justify a wider block. A held reservation does not stop charges.
- **The Runtime owns durable obligations, fencing, atomic settlement/reservation transitions and recovery scheduling.** Astrid supplies acquire, inspect and release adapters. Local recovery records stay until durable handoff works across crashes and Runtime outages. Redundant latches are deleted one at a time.
- **Do not build:** a universal resource orchestrator, mandatory heartbeats for scratch, a second ledger, a generic GPU scheduler, per-descendant journals, or a promise that every backend is thin. Never equate cancel requests, expired leases, lock release or operator overrides with confirmed destruction. Never erase unresolved billing exposure to unblock scheduling.

**Policy axes (evidence/astra-cpu-gpu-verdict.md supersedes cpu-gpu-differences.md).** CPU vs GPU is the wrong axis. Policy hangs off four independent properties of a resource:
- **Lifetime:** disposable or reused service.
- **Ownership:** owned (stop it) or borrowed/attached (protocol cancel, with acknowledgement and quiescence).
- **Billing:** a paid provider allocation, including CPU pods; stopped RunPod storage still bills, so stop and terminate are distinct.
- **Release evidence:** what the backend can authoritatively say. Provider confirmation suffices for pods. No VRAM-clearance proofs.

**Defer:** VRAM packing (start with explicit device sets and coarse serialization), and universal GPU health checks (use backend readiness plus fault-triggered quarantine).

**On Apple Silicon,** budget CPU and GPU memory as one unified pool.

**Minimal plan adopted (15 Oct, evidence/opus-complexity-review.md).**
- Fix the four observed failures mostly by deletion, in about 4 days.
- The obligations ledger, policy objects, Scope/Lease API, host control endpoint, Linux/cgroup/Job Object backends, VRAM accounting and non-reaping retrofits are deferred until a real need appears.
- Astra's principles above still bound every step.
- Accepted limitation: on normal completion the leader is reaped before the group kill. That leaves a seconds-long pgid-reuse window, as on the live line.
