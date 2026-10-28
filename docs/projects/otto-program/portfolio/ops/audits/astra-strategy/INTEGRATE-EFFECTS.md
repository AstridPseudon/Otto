**Do not integrate EFFECTS as-is. EF3 contains a deterministic owner-startup failure.** The project also only partially delivers its stated goal.

Reviewed EFFECTS `17da237` against base `163925e` and canon **`e56707e`**, including FACADEFD, which landed during this review. Three Luna reviewers handled parallel inspection; I checked their findings against source. No tests, owners, staging, or Otto commands were run.

1. **Goal and blocking finding**

   **EF3: owner construction raises `AttributeError`.** `PortfolioOwnerBootstrap` has no base class and declares `__slots__` without `_native_effect_ledger`. Commit `d77e520` nevertheless assigns that attribute during construction. Any normal owner startup reaching this assignment fails. This is established statically, not by executing startup. See [slots](${TRANSFER_ROOT}/source/projects/effects/src/otto/portfolio/owner_bootstrap.py:598) and [assignment](${TRANSFER_ROOT}/source/projects/effects/src/otto/portfolio/owner_bootstrap.py:683).

   **Fix:** declare `_native_effect_ledger` in `__slots__`, preserving its initialization once per owner and reuse by role runtimes. The recorded AF_UNIX setup failures prevented the affected integration tests from reaching this defect. The project’s final “no additional concrete defect” assessment is therefore insufficient.

   The [goal](${TRANSFER_ROOT}/source/projects/effects/.project/agent_goal.md:3) remains partial:

   - Native turns and runner jobs acquire kernel start claims; unknown reconciliation checks exact retained evidence.
   - The per-case custody modules are **not gone**. Git identifies `manager_capture_reconciliation.py → native_terminal_proof.py` as a **93% similar rename**, reducing 448 lines to 433. `worker_custody.py` is unchanged; `owner_runtime.py` grows by 83 net lines.
   - `execution_resume.py` genuinely loses 269 lines; I found no remaining source/test reference to it or `execute_selected_packet`.
   - The diff does not establish coverage of every external effect or paid API call, or a measured cold-agent reconciliation journey.

   These limitations are substantially acknowledged in the [project’s final record](${TRANSFER_ROOT}/source/projects/effects/.project/PROJECT.md:24).

2. **Task decisions**

   “Merge now” below means eligible for a separate program landing **after its gate passes**, not permission to bypass validation.

   | Task | Assessment | Recommendation |
   |---|---|---|
   | **EF1** | The start claim commits before invocation, rejects another grant, and reconstructs STARTED as UNKNOWN. Retained-operation compatibility is preserved. No concrete new defect verified. [Implementation](${TRANSFER_ROOT}/source/projects/effects/src/herzchen/kernel/operations.py:431) | **Merge now**, including the retained-replay fix. Its blocked tests must run. |
   | **EF2** | Resolution checks retained custody, local receipt/event lineage, exact effect/state/result, and concurrent state changes. Canonical JSON comparison addresses bool/int ambiguity. No concrete new defect verified. [Implementation](${TRANSFER_ROOT}/source/projects/effects/src/herzchen/kernel/operations.py:615) | **Merge now**, including custody/proof fixes. |
   | **EF3** | Startup blocker above; crash/retry acceptance is also inadequately demonstrated. Shared settlement is useful, but the promised consolidation remains incomplete. | **Merge after fixing the slot and adding an actual gateway crash/reconstruction/retry regression.** Preserve fresh-manager generation fencing and prior-effect identity fixes. |
   | **EF4** | Claims precede launch; kernel terminal results precede sealed runner results; restart mirrors only matching result/output evidence. Authenticated actor composition fixes are necessary. [Ordering](${TRANSFER_ROOT}/source/projects/effects/src/herzchen/fleet/runner/runner.py:345), [mirroring](${TRANSFER_ROOT}/source/projects/effects/src/herzchen/fleet/runner/runner.py:512) | **Merge now**, including `3d1634f`. Gate must resolve the recorded custody failure without weakening its assertion. |
   | **EF5** | Exact references, shell quoting, authenticated resolver and minted keys are useful. The deletion is justified. Current “cold-agent” tests use injected fake managers and do not prove the owner-lane journey. | **Merge after an acceptance fix:** exercise real owner-lane read/refusal/resolution with retained proof, and record the cold-agent check. Include `8f65505`. |

   No whole task warrants dropping. Do not count the renamed proof module as removed complexity. A later consolidation should remove duplicated lifecycle decisions while preserving native-proof and assignment/custody validation; the generic ledger expressly relies on those checks. [Proof contract](${TRANSFER_ROOT}/source/projects/effects/src/otto/agents/effect_ledger.py:73)

   EF4 also intentionally disables the standalone daemon without an injected owner ledger. Its module entry point cannot supply one, so standalone invocation now exits 2. Preserve this deliberate behavior in the landing description. [Source](${TRANSFER_ROOT}/source/projects/effects/src/herzchen/fleet/runner/server.py:132)

3. **Test honesty, timing and changed assertions**

   - **Misleading EF3 crash fixture:** it disables the ledger, completes a successful provider turn, rewrites the capture, then manually creates an UNKNOWN effect. Its comment says “crash after durable start,” but that is not the sequence exercised. Keep it as a reconciliation fixture; add a separate real gateway-boundary regression. [Fixture](${TRANSFER_ROOT}/source/projects/effects/tests/test_missing_manager_capture.py:15)
   - **Weak retry assertion:** the worker-custody test releases custody and asserts no provider calls, but never attempts a retry. It proves the ledger stays UNKNOWN, not that a subsequent launch is refused. [Test](${TRANSFER_ROOT}/source/projects/effects/tests/test_worker_custody.py:27)
   - **Synthetic runner proof:** the reconciliation test retains the exit code in test memory and writes `effect.terminal` directly. That verifies kernel resolution and mirroring, not recovery of proof after actual owner loss. [Test](${TRANSFER_ROOT}/source/projects/effects/tests/test_runner.py:558)
   - Production runner completion persists its terminal result before sealing. A later seal crash is recoverable. Before that persistence, output and custody information alone do not establish an exit result; remaining held is correct. I found no production runner proof writer equivalent to the native proof writer.
   - The new runner crash test uses a **30-second sleeping child**, polling, and explicit cleanup. It is a process-lifetime fixture, not a performance threshold or a delay used as proof of success. [Test](${TRANSFER_ROOT}/source/projects/effects/tests/test_runner.py:482)
   - **No baseline assertion was removed or changed in the final `163925e..proj/effects` test diff.** Removed test lines are imports. However, the project explicitly records correcting its **new EF5 read-exit assertion to 0**, then not rerunning it. Flag that correction and rerun both JSON/text cases. [Record](${TRANSFER_ROOT}/source/projects/effects/.project/PROJECT.md:12), [assertions](${TRANSFER_ROOT}/source/projects/effects/tests/test_hostctl_cli.py:65)

   The final diff does not trigger the gate’s removed-assertion detector. That does not excuse misleading fixtures or unmet fail-first acceptance.

4. **Canon conflicts**

   Since `163925e`, canon contains:

   ```
   1b1159d READYPIN
   eb9b6cd Land READYPIN
   ec7c1b9 OWNERCOMPLETION
   b635c93 Land OWNERCOMPLETION
   874553c FACADEFD
   e56707e Land FACADEFD
   ```

   Exactly **two files are touched by both sides**:

   | File | Overlap and merge difficulty |
   |---|---|
   | `src/otto/portfolio/execution_host.py` | **Low.** EFFECTS changes the proof-module import near line 363. OWNERCOMPLETION changes completion callbacks near baseline lines 1452 and 1625. Separate hunks; preserve both. |
   | `src/otto/portfolio/owner_bootstrap.py` | **Small manual conflict.** EFFECTS and FACADEFD both insert initialization immediately after `_limit_service`. Keep native ledger, assessment operations and consumer transport initialization. Declare all three corresponding slots. READYPIN’s historical completion/content checks are elsewhere and must remain. |

   This is source comparison, not a performed merge. FACADEFD also changes `command_ports.py`, which EFFECTS does not edit but its operation facades use; include the lifecycle/descriptor regressions explicitly.

5. **Integration and gate**

   Land separately, rebasing each onto then-current canon:

   1. **EF1** — `5f3da51` task changes, including retained replay compatibility.
   2. **EF2** — `3e1f9b2`.
   3. **EF4** — `1634644` plus authenticated-actor fix `3d1634f`.
   4. **EF3** — `b1f877c`, the missing-slot fix, and genuine crash/retry coverage.
   5. **EF5** — `ee489f4` plus `8f65505`; include EF3’s held-effect UX/raced-identity changes from `5141e5d` here so their suggested `otto effects` command exists when exposed.

   Port the task changes into landing labs; do not import the EFFECTS project package as canon’s project metadata.

   The immediate deferred checks are these **whole files**, each in its own process, twice:

   | Task | Required files |
   |---|---|
   | EF1–EF2 | `tests/test_operation_receipt_lineage.py` |
   | EF3 | `tests/test_owner_result_reconciliation.py`, `tests/test_missing_manager_capture.py`, `tests/test_completed_manager_capture.py`, `tests/test_worker_custody.py` |
   | EF4 | `tests/test_runner.py` |
   | EF5 | `tests/test_hostctl_cli.py`, `tests/test_effect_owner_verb.py`, `tests/test_effect_command_shell.py` |

   The project reports nine EF1/EF2 tests blocked in setup; substantial EF3 setup failures; and six runner gate cases, including custody observed as `uncertain` where `gone` was expected. Those are **unverified**, not passes. Keep the explicit `gone` assertion in [the orphan-tree regression](${TRANSFER_ROOT}/source/projects/effects/tests/test_runner.py:841).

   I independently reproduced the gate’s import-selection calculation without executing tests: the complete EFFECTS delta selects **117 files**, unchanged by FACADEFD’s added tests. For split landings, recompute each task’s selection. Every filename below is under `tests/`:

   ```text
   test_admit.py
   test_admitted_transport_drain.py
   test_advisor_lifecycle.py
   test_ask_integration.py
   test_ask_runner_session.py
   test_ask_socket_wait.py
   test_authenticated_socket_receipts.py
   test_bounded_project_host.py
   test_capacity_holds.py
   test_capacity_pool.py
   test_clean_close.py
   test_command_receipt_progress.py
   test_compact_authenticated_reads.py
   test_completed_manager_capture.py
   test_completed_worker_selector.py
   test_completed_worker_support_pins.py
   test_completion_project_refresh.py
   test_compose.py
   test_document_editor_host.py
   test_effect_command_shell.py
   test_effect_owner_verb.py
   test_embedded_host_heartbeat.py
   test_evidence_single_copy.py
   test_evidence_status_owner_facade.py
   test_evidence_wiring.py
   test_exact_occurrence_summary.py
   test_execution_application.py
   test_execution_host_manager_turn_queue.py
   test_execution_operations.py
   test_existing_project_orchestration.py
   test_external_owner_context.py
   test_external_owner_execution.py
   test_final_recovery_composition.py
   test_fleet_custody.py
   test_fleet_dispatch.py
   test_fresh_worker_admission.py
   test_herzchen_boundary.py
   test_host_bridge_transitions.py
   test_host_neutral_defaults.py
   test_host_startup_composition.py
   test_hostctl_cli.py
   test_hostctl_portfolio.py
   test_hostctl_project_service.py
   test_hostctl_serve.py
   test_hostctl_service_routing.py
   test_identity_ref_prefilter.py
   test_indexed_identity_lookup.py
   test_indexed_sheet_relationship_reads.py
   test_initial_manager_transport.py
   test_invalid_ipc_handle.py
   test_ipc_response_retention.py
   test_labs.py
   test_landing.py
   test_lane_listing_robustness.py
   test_local_assessment_composition.py
   test_manager_advisor_paused_host.py
   test_manager_assessment_ipc.py
   test_manager_completion_command.py
   test_manager_consumption_adoption.py
   test_manager_correction_planning.py
   test_manager_journey_service.py
   test_manager_mandate_reconciliation.py
   test_manager_no_overlap_disposition.py
   test_manager_preprovider_disposition.py
   test_manager_reentrant_ipc.py
   test_manager_service_continuation.py
   test_manager_start_bounded_envelope.py
   test_missing_manager_capture.py
   test_native5_retained_root_policy.py
   test_operation_receipt_lineage.py
   test_operator_admission.py
   test_orchestrator_client.py
   test_orchestrator_client_cli.py
   test_orchestrator_lane_pump.py
   test_otto_open_release.py
   test_otto_save.py
   test_otto_show_status.py
   test_owner_lane.py
   test_owner_port_binding_lifetime.py
   test_owner_result_reconciliation.py
   test_owner_vision_installation.py
   test_pending_inert_tasks.py
   test_perch.py
   test_planned_owner_maintenance.py
   test_portfolio_dependencies.py
   test_portfolio_detach.py
   test_portfolio_shared_documents.py
   test_portfolio_status.py
   test_project_advisor_context.py
   test_project_advisor_delivery.py
   test_project_advisor_pairing.py
   test_project_folder_scale.py
   test_retained_root_lane.py
   test_retained_worker_start_recovery.py
   test_revisions.py
   test_role_preinitialization_custody.py
   test_root_direction_client.py
   test_root_direction_synchronization.py
   test_runner.py
   test_runner_cli.py
   test_scoped_root_supervision.py
   test_setup_read_native_wait.py
   test_sheet_relation_prefilter.py
   test_status_owner_custody.py
   test_stopped_writer_conflict_custody.py
   test_supervisor_direction_client.py
   test_task_assessment_supplement.py
   test_task_metadata.py
   test_transcript_once.py
   test_unused_maintenance_supersession.py
   test_usage_capture.py
   test_usage_late.py
   test_usage_retained_native.py
   test_worker_custody.py
   test_worker_drain_preinitialization.py
   test_worker_initializer_continuity.py
   test_worker_readiness.py
   ```

   Add four explicit checks outside that automatic selection:

   - `tests/test_fresh_manager_admission.py` — real fixture underlying the changed capture tests.
   - `src/otto/portfolio/tests/test_operating_setup.py` — imports changed operating-setup code but lies outside the gate’s scanned directory.
   - `tests/test_command_ports_lifecycle.py`
   - `tests/test_facadefd_regression.py` — the latter two cover the newly landed facade/lifetime seam.

   Run startup and the configured staging canaries on the tested landing SHA. `otto-program/ops/stages-gated` currently contains **`0 1`**.

   Finally, explicitly establish fail-first evidence for regressions added inside existing files: the current gate automatically checks only entirely new test files and merely warns when they pass on BASE. Its flaky-failure handling also differs from the stricter runbook wording. Record any such disposition rather than treating a green script exit as complete acceptance. [Gate selection](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:287), [fail-first handling](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:421), [runbook](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:62)