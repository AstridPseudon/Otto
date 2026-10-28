**Verdict: approve the simplification, reject the proposal as written.** Use owner-bound scopes, keep the pack host as the resident owner, and explicitly narrow the POSIX cleanup guarantee. Do not land the separate host-owner daemon first. The live line demonstrates operational viability, not proof of G1/G2. This was a read-only review; I did not run renders.

1. **Tags are discovery hints only.** Machines and Failure are correct; Overengineering’s tag-sweep recommendation is unsafe. UID, tag, and start time do not close the check-to-`kill(pid)` race on macOS. “Started after scope creation” does not even identify one incarnation. `--user-data-dir` is likewise diagnostic.

   Signal an owned, anchored process group or an explicitly registered incarnation-bound handle. Keep native handles for known detached services; do not retain continuous custody of every observed descendant. Apple’s audit-token lookup validates PID version, unlike numeric PID signalling. [Apple source](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_proc.c)

2. **Tasks is right about abstraction.** Use one scope per task attempt and one scope per leased service. ffmpeg, Python and Codex executions fit task scopes; VibeComfy and the frame worker fit service scopes. Preserve Codex’s nested controls and VibeComfy’s listener protocol behind their adapters. Remote ownership remains remote; an SSH process is not its workload.

3. **The pack host should own its engines and tasks.** Give it a singleton lock and private control endpoint for orderly drain/stop/replacement. A CLI requests shutdown; it need not retain the host’s original `Popen`.

   Reject `928a85cd` as the first migration: its 821-line owner adds another lifecycle and recovery loop without independently retaining every task scope. A lifeline handles cooperative shutdown, not host SIGKILL or deadlock. On POSIX, host death can leave children: record affected scopes as unresolved and prevent conflicting resource reuse. Do not declare them cleaned or reconstruct signal authority from markers.

   Main already implements a directly spawned, host-owned Remotion worker with sequential leases in `remotion_host_session.py:HostRemotionSession._start`; the proposal’s launchctl description is stale for that path.

4. **Build POSIX first; strengthen deployments selectively.** Use one session/group backend on macOS, Linux and inside supplied containers. Keep existing exact RunPod process handling. Add cgroup v2 when a tested deployment provides delegation; systemd availability is not equivalent to cgroup capability. A cgroup does not automatically die with its owner: crash cleanup needs an independent supervisor. [Kernel documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

   Build Windows Job Objects before claiming Windows support, with assignment before execution, breakaway disabled and controlled handle inheritance. Kill-on-close requires the **last** job handle to close. [Microsoft documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

   Use an external container boundary only when Astrid actually owns its lifecycle.

The replacement threat model should say:

- **G1:** “A scope is settled only after its backend confirms no live processes remain within its declared containment boundary.” POSIX covers group members and explicitly registered services while cleanup ownership survives. Accidental daemonization, environment sanitization and owner crashes are limitations, not merely adversarial exceptions. Stronger backends cover their enforced membership; owner-death cleanup is a separately reported capability.
- **G2:** “Astrid lifecycle code signals only an anchored private group or a registered incarnation-bound handle; missing authority produces unresolved cleanup.” This excludes malicious same-user interference and does not promise that arbitrary pack code cannot signal other processes.

An empty census is evidence about that boundary, never complete descendant history. Current main itself records complete descendant history as `UNPROVED`.

The smallest API is five operations:

```python
spawn(owner, spec, lifetime="task" | "service") -> Scope
lease(service, task) -> Lease
release(lease)                 # service idle policy may stop it
stop(scope, grace) -> Report   # idempotent; reap after cleanup
status(scope) -> Report        # non-reaping observation
```

Reports separate execution result from cleanup state: `running`, `settled`, or `unresolved`, plus backend coverage. Deadlines produce unresolved results, never fabricated absence.

The POSIX implementation must retain its session leader until cleanup finishes. Existing callers use `Popen.poll()` and `communicate()`, which can reap it; consequently this **cannot** be a transparent substitution behind today’s API. Replace those call sites with non-reaping status and output collection.

Delete and migrate in this order:

1. **Remove startup-wide render validation:** `host_bootstrap.py:_prepare_render_validation`’s worker enumeration and `remotion_runtime.py:_settle_registries`’s cross-context loop. Validate the actual render context at use time. Acceptance: cold-start and complete the film under normal load.
2. **Implement task scopes and replace reaping call sites.** Then remove ordinary-command use of `custody_broker.py:ProcessCustody.start_observer`, `observe_census`, `_register_census_candidate`, `_candidate_reconciliation_deadline`, and `process_group.py:_observe_tree` reconciliation. Acceptance: full film, cancellation halfway through, leader-before-helper exit, then another full film.
3. **Make the host the explicit service owner.** Reuse Remotion leases; adapt VibeComfy without removing its control protocol. Remove `host_bootstrap.py:_pin_native_host_command`, `_framework_reexec_of_launch`, and `_darwin_host_command_observation` as lifecycle authority. Scrub inherited job tags at the persistent-service boundary. Acceptance: two sequential films, orderly host replacement, then another film.
4. **Replace global poisoning with scoped cleanup obligations:** remove `generic_host.py:_latch_cleanup_uncertainty`’s host-wide admission block. Retain affected resource reservations until resolved. Acceptance: delayed observation, host crash, honest unresolved reporting and recovery, then a full film.

Every step also repeats image → sprite/edit → publish → full-film review on the normally busy Mac, checking playback and residual processes. Linux gets equivalent backend acceptance before release.

**Do not build:** universal tag sweepers, another resident daemon, per-descendant journals, generic container-runtime orchestration, speculative Windows plumbing, new caching before measurement, or hardware-specific lifecycle abstractions. Do not delete Runtime custody or shared control-peer code without proving its callers are gone.