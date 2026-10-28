**Do not integrate PROCLIFE wholesale yet.** It improves custody persistence, but does not fully deliver its goal. I found unresolved authority/recovery gaps, a PL3 conflict with existing acceptance tests, and a timed crash test that can pass prematurely.

Reviewed project `df534f3` against base `eb9b6cd`; canon advanced during review to **`d02e46e`**, including FAILEDFENCE. No tests, owners, staging commands, commits, or file changes were performed. Findings below are static deductions, not reproduced failures.

The measured diff is **31 files, +2077/−204**. The project honestly reports **44/99** credited deletions and pending external validation. The retained 55 lines support escapee custody required by the orchestrator’s ruling; deleting them merely to meet the budget would be wrong. [Accounting]( ${TRANSFER_ROOT}/source/projects/proclife/.project/PROJECT.md:85)

1. **PL1 still cannot guarantee exact birth identity.** `Custody.census()` uses `ps lstart` display text as birth identity. A recorded escapee whose PID is reused within the same displayed second can match `_live()` and receive `os.kill()`. This is an inherited defect left unresolved by a task explicitly promising G2, not a newly introduced regression. PL4 already recognizes the distinction between display time and kernel birth identity. Fix generic custody to use exact identities and retain uncertainty when unavailable. [Census]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/custody.py:61), [identity comparison]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/custody.py:204), [signalling]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/custody.py:262), [PL4 regression]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_heavy_lease.py:208)

2. **PL3 changes capacity semantics against existing tests and PINALL’s direction.** `_group_state()` returns `reused` for a changed-birth process leading the same numeric group; `_reconcile_hold()` now releases capacity for `reused`. Consequently, these unchanged tests would fail their held-capacity expectations:
   - `CapacityHoldTests.test_reused_pid_stays_held`
   - `CapacityHoldTests.test_reused_pid_after_group_death_stays_held`

   PINALL explicitly permits reversing only the **empty-group** case and requires live-group cases to remain held. Restore that distinction; do not reverse both tests to accommodate PL3. Its new `test_replacement_leader_of_same_group_frees_only_physical_hold` also needs correction to the agreed policy. [Implementation]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/portfolio/execution_host.py:868), [new conflicting test]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_worker_custody.py:442), [canon tests]( ${TRANSFER_ROOT}/source/otto/tests/test_capacity_holds.py:154), [PINALL decision]( ${TRANSFER_ROOT}/portfolio/ops/prework/PINALL.md:105)

3. **PL2’s recovery accounting misses unresolved scopes whose accounting record is unavailable.** For a retained nested child, `units` is zero. If its parent record is missing or fails verification, the ancestry walk stops and restoration skips the zero-unit child. Unmatched latches are cleaned separately, but their unresolved dispositions are discarded. New unrelated submissions can then consume the full pool despite surviving work. This is an inherited recovery edge that PL2’s new retention mechanism does not close. Preserve enough claim/parent accounting in existing durable custody records to restore the affected reservation without inventing a host-wide latch. [Record filtering]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/runner/store.py:124), [recovery]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/runner/runner.py:237), [zero-unit nesting]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/runner/runner.py:112)

4. **PL3 leaves production metadata-reader custody non-durable.** `CodexAppServerThreadReader` launches without `latch_path`. Its improved cleanup check rejects a successful lookup when cleanup is uncertain, but then retains no recoverable scope; owner death also bypasses the `finally` cleanup. This production path is explicitly included in PL3. Connect it to durable owner recovery. The same omission in `run_turn()` is a public-contract gap, although I found no active production caller beyond `run_continuation()` in this snapshot. [Reader launch and cleanup]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/agents/codex_host_reader.py:216), [production construction]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/agents/orchestrator_route.py:222), [contract launch]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/hosts/contract.py:345)

5. **PL4 can strand an ordinary same-group descendant.** A command forks a child and exits before a census observes both. The durable record contains the root, but `_observe()` requires a live known anchor before adopting remaining group members. Cleanup consequently sends no signal and retains `group:<pgid>` indefinitely while that child lives. Recovery repeats the same logic. This fails closed, but loses cleanup and capacity; it is broader than the disclosed never-observed `setsid` daemonization limitation. Preserve a sound group anchor through cleanup—do not “fix” this with an unfenced `killpg`. [Adoption]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/hostctl/heavy.py:176), [cleanup]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/hostctl/heavy.py:279), [leader reaping]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/hostctl/heavy.py:635)

6. **PL5’s recovery guidance is incomplete.** After restart proves cleanup complete and removes a latch, the immutable result can still say `custody="uncertain"`. `_recovery_action()` reads that historical field alone and instructs the client to keep a claim held although recovery restored none. Separately, heavy status omits lease identity, unresolved cleanup details, and recovery guidance. Derive current cleanup guidance from retained scope/claim evidence while preserving the unknown task outcome and prohibition on unsafe retries. [Guidance]( ${TRANSFER_ROOT}/source/projects/proclife/src/herzchen/fleet/runner/runner.py:27), [existing cleanup-restoration test]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_runner.py:617), [heavy status]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/hostctl/heavy.py:459)

The test-quality blocker is **`test_holder_crash_at_spawn_cannot_launch_command_without_durable_root`**: it waits for the holder, sleeps **0.3 seconds**, then treats an absent marker as proof the child cannot execute. A delayed child can make a broken implementation pass. Replace the elapsed-time observation with synchronization and proof the child has exited or reached a terminal no-exec state. [Test]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_heavy_lease.py:370)

The mocked runner scopes and patched `resume_cleanup` cases are useful unit tests, not evidence of real owner crash recovery. I found no basis to accuse their authors of dishonesty. The project does disclose the outstanding integration probes. Also repair the documented runner waiter leaks before repeated gate runs; TESTREAP records actual orphaned processes from these fixtures. [Mocked recovery]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_worker_custody.py:363), [TESTREAP]( ${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:189)

Task recommendations:

| Task and merged commit | Recommendation |
|---|---|
| PL1 — `964120e` | **Merge after fixing exact birth identity** in finding 1. Preserve escapee discovery/signalling. |
| PL2 — `eec2b98` | **Merge after fixing recovery accounting** in finding 3; then run the full runner gate. |
| PL3 — `f9d18e3` | **Merge after fixing findings 2 and 4**, coordinating capacity semantics with PINALL and preserving FAILEDFENCE. |
| PL4 — `580c6c4` | **Merge after fixing finding 5 and the timed crash test.** Resolve D14 placement: the new generic custody/launch mechanism is under `src/otto`; the program requires fleet mechanisms in Herzchen. |
| PL4-G1 — `4e195a1` | **Keep with PL4.** Sticky census uncertainty is necessary; do not land PL4 without it. |
| PL5 — `05ec363` | **Merge after fixing finding 6** and completing the cold-agent comparison. |
| PL5-NEXTACTION — `7209c93` | **Keep with PL5.** Exact-key transport retry guidance is appropriate. |
| PL6 — `e6b27eb` and final accounting updates | **Drop as a separate canon source landing.** Retain the handoff as program evidence, corrected with these findings and actual gate receipts. |

D14 is an explicit landing requirement, not an inferred architectural preference. Prefer consolidating the identity/custody primitive rather than maintaining two implementations with different birth guarantees. No universal ledger or resident daemon was introduced. The duplicate `_owns_owner_file = False` is a small deletion worth making; the live compatibility helpers are not justified deletion targets. [D14]( ${TRANSFER_ROOT}/portfolio/RUNBOOK.md:70), [duplicate]( ${TRANSFER_ROOT}/source/projects/proclife/src/otto/portfolio/execution_host.py:1217)

Canon’s landings since `eb9b6cd` are OWNERCOMPLETION (`b635c93`), FACADEFD (`e56707e`), CTLRACE (`97f5f97`), CAPTUREEDIT (`ec6bacf`), and FAILEDFENCE (`d02e46e`). **Only two files are touched by both sides:**

| File | Merge assessment |
|---|---|
| `src/otto/agents/claude_adapter.py` | **Low textual difficulty.** CAPTUREEDIT changes capture/tool handling earlier in the file; PL3 adds launch callbacks in transport calls. Preserve both initializer/work callbacks and checkpoint-based capture. |
| `src/otto/portfolio/execution_host.py` | **Likely clean text merge; substantial semantic review.** OWNERCOMPLETION changes completion callbacks; FAILEDFENCE extends failed/unknown disposition handling; PL3 changes process records, cleanup and physical-capacity release. Preserve exact disposition checks and no-provider-retry behavior. Run the newly expanded canon `test_capacity_holds.py`. |

These are inferred merge assessments from the hunks; no merge was attempted.

For **D19**, the final project diff contains exactly **one replacement of an existing assertion**:

- `tests/test_heavy_lease.py:187`: `assert alive(bystander.pid)` → `assert bystander.poll() is None`. **Recommend LAND for this assertion change:** the directly owned child must still be running; `poll()` also recognizes/reaps termination without relying on an unavailable `ps` probe. It still needs the written landing decision. [Assertion]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_heavy_lease.py:180)

Also explicitly disposition the changed premise of `test_forced_owner_close_terminates_recorded_fake_worker`: PL3 inserts `host.start()` before `close()`. The predicate is unchanged, but the test now checks a claimed owner. That is consistent with owner-claim-before-kill and the added rejected-contender test. [Changed premise]( ${TRANSFER_ROOT}/source/projects/proclife/tests/test_worker_custody.py:167)

The two capacity tests in finding 2 are **not changed assertions in this branch**. They are pending landing conflicts: obtain D19 for the approved empty-group reversal; preserve the live-group hold expectation. PL1’s original `test_group_kill_takes_grandchildren_and_setsid_escapees` remains unchanged.

Integrate through separate program landings in this order:

1. Fixed PL1.
2. Fixed PL2, with TESTREAP’s fixture cleanup available.
3. Fixed PL3, reconciled with PINALL’s policy and current FAILEDFENCE.
4. Fixed PL4 **including PL4-G1** and its D19 decision.
5. Fixed PL5 **including PL5-NEXTACTION**.
6. Attach completed handoff and external-probe evidence to the program.

Each landing rebases onto then-current canon, runs its check and importing test files individually twice, compares failures with canon, and runs the configured staging gate on the tested SHA. At review time, `ops/stages-gated` contains **`0 1`**; the actual script uses that list, despite RUNBOOK’s older `all --fake` wording. [Gate contract]( ${TRANSFER_ROOT}/portfolio/RUNBOOK.md:62), [selector]( ${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:287), [staging selection]( ${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:432)

The **eight focused files** must run in full, outside the restrictive sandbox, one pytest process per file:

```text
tests/test_fleet_custody.py
tests/test_runner.py
tests/test_runner_cli.py
tests/test_worker_custody.py
tests/test_host_contract.py
tests/test_codex_host_reader.py
tests/test_heavy_lease.py
tests/test_runner_cli_retry_key.py
```

Use `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`. Require real AF_UNIX binding, usable process census, and macOS sandbox execution. In particular, do not accept a skipped `test_framework_python_mcp_exec_pin_runs_worker_but_denies_unpinned_executable` as validation. Preserve and run the setsid cleanup and runner orphan-restart tests.

The project records failure **counts**, not the historical failing node IDs or raw logs. Therefore I cannot substantiate that every reported failure was caused solely by sandbox restrictions. The complete files above must be rerun; the interrupted heavy run is not a completed check. [Recorded limitations]( ${TRANSFER_ROOT}/source/projects/proclife/.project/PROJECT.md:136)

Beyond those eight, reproducing the current gate selector yields these **54 additional files**, each individually twice. Recompute after each rebased landing:

```text
tests/test_admitted_transport_drain.py
tests/test_ask_socket_wait.py
tests/test_authenticated_socket_receipts.py
tests/test_bounded_project_host.py
tests/test_capacity_holds.py
tests/test_capacity_pool.py
tests/test_claude_manager_admission.py
tests/test_command_receipt_progress.py
tests/test_completed_worker_selector.py
tests/test_completed_worker_support_pins.py
tests/test_compose.py
tests/test_coordinator_host_contract.py
tests/test_document_editor_host.py
tests/test_embedded_host_heartbeat.py
tests/test_exact_occurrence_summary.py
tests/test_execution_application.py
tests/test_execution_host_manager_turn_queue.py
tests/test_execution_operations.py
tests/test_external_owner_context.py
tests/test_external_owner_execution.py
tests/test_fleet_dispatch.py
tests/test_healthy_worker_lifetime.py
tests/test_herzchen_boundary.py
tests/test_host_bridge_transitions.py
tests/test_host_neutral_defaults.py
tests/test_host_startup_composition.py
tests/test_hostctl_project_service.py
tests/test_hostctl_serve.py
tests/test_hostctl_service_routing.py
tests/test_initial_manager_transport.py
tests/test_invalid_ipc_handle.py
tests/test_ipc_response_retention.py
tests/test_landing.py
tests/test_manager_correction_planning.py
tests/test_manager_journey_service.py
tests/test_manager_reentrant_ipc.py
tests/test_missing_manager_capture.py
tests/test_native_resume_trace.py
tests/test_owner_result_reconciliation.py
tests/test_perch.py
tests/test_planned_owner_maintenance.py
tests/test_project_advisor_delivery.py
tests/test_retained_worker_start_recovery.py
tests/test_role_preinitialization_custody.py
tests/test_root_direction_client.py
tests/test_setup_read_native_wait.py
tests/test_status_owner_custody.py
tests/test_stopped_writer_conflict_custody.py
tests/test_supervisor_direction_client.py
tests/test_tools.py
tests/test_unused_maintenance_supersession.py
tests/test_usage_capture.py
tests/test_worker_readiness.py
tests/test_workspace_write_native_attribution.py
```

Finally, completion requires the documented normal-operation/exact-key probe, owner-SIGKILL recovery with identity-reuse protection, paired installed-owner cold-agent comparison, and external Astrid film journey. Unit-test passes cannot substitute for those still-unperformed acceptance checks. [Probe protocol]( ${TRANSFER_ROOT}/source/projects/proclife/.project/PROJECT.md:122), [cold-agent protocol]( ${TRANSFER_ROOT}/source/projects/proclife/.project/evidence/PL5-ux-gate.md:1)