# SLIM: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17 20:18 UTC | SL3 scoped friction and usage follow-up | merged ea52539 | +36/-11 | `tests/test_status_friction.py` (3 passed), `tests/test_owner_observability_cli.py` (6 passed) | explicit refs/grants in friction fixtures; malformed owner args return structured usage errors.
2026-10-17 20:16 UTC | SL2 refusal guidance follow-up | merged f0f7bc5 | +57/-20 | `tests/test_manager_replacement_unit.py` (5 passed) | held paths now direct owner reconciliation and prohibit acquisition retry under the same generation/native session; Astra found no defect.
2026-10-17 20:13 UTC | SL0 ledger regression repair | merged b6f48f5 | +237/-21 | `tests/test_slim_ledger.py` (1 passed) | separates immutable base counts from current inventory; dynamically measures candidates; removed stale deleted candidates.
2026-10-17 20:13 UTC | SL3/SL8 owner integration follow-up | merged a4c0a8f | +195/-4 | `tests/test_owner_observability_cli.py` (5 passed), `tests/test_cli_read_routes.py` (3 passed) | installed routes use the owner-issued finite project grant and actor; no owner started.
2026-10-17 20:13 UTC | SL8 retained-history correction | merged ee9a30d | +62/-4 | `tests/test_status_friction.py` (3 passed) | recognizes retained history shape and reports unproven category coverage as unavailable.
2026-10-17 20:12 UTC | SL0 regression repair | Astra's report reproduced: the acceptance failed when current portfolio counts (47,187 lines / 96 modules) were asserted against the base. Generator now reports immutable `163925e` baseline (47,920 / 99) separately from the dynamically measured current inventory; the test checks both without pinning the current count. Candidate sizes and importer counts derive from current rows, retired candidates are absent. Files changed: `.project/ledger.md`, `.project/tasklist.md`, `scripts/slim_ledger.py`, `tests/test_slim_ledger.py`. Focused test failed before the fix and passed after. No deletions.

2026-10-17 19:55 UTC | SL0 | merged 81abf5c | +410/-4 | `tests/test_slim_ledger.py` (1 passed) | files: `.project/PROJECT.md`, `.project/ledger.md`, `.project/tasklist.md`, `scripts/slim_ledger.py`, `tests/test_slim_ledger.py`; measured 47,920 baseline and 11,980 threshold, 99 portfolio modules plus 38 controller modules; no deletions.
2026-10-17 20:05 UTC | SL4 | merged 9fdc4be | +22/-781 | `tests/test_usage_contract.py` (9 passed); `src/otto/portfolio/tests/test_observability_views.py`, `tests/test_portfolio_status.py`, `tests/test_host_startup_composition.py` needs the gate (AF_UNIX bind denied) | retired proof-only Events modules and wrappers; no controller files deleted; ledger regenerated. Files listed in SL4 evidence below.
2026-10-17 20:20 UTC | SL1 | merged cd4d611 | +55/-414 | `tests/test_manager_journey_service.py -k effective_manager_brief` (2 passed); broader journey, advisor delivery, and direction invocation checks need the gate (AF_UNIX bind denied) | adopted exact direction revisions now reach the effective replacement brief; removed 282-line unused advisor adapter; Astra found no concrete defect. Files listed in SL1 evidence below.
2026-10-17 20:30 UTC | SL3 | merged 29c6530 | +210/-76 | `tests/test_cli_read_routes.py` (3 passed); `tests/test_otto_show_status.py`, `tests/test_project_history.py` need the gate (AF_UNIX bind denied) | removed root overview/tasks/task routes; kept `events` compatibility; ledger regenerated. Files listed in SL3 evidence below.
2026-10-17 20:40 UTC | SL8 | merged 24eeda2 | +195/-3 | `tests/test_status_friction.py` (2 passed) | added bounded, authorized `otto status --friction`; unavailable values remain explicit; no deletion; ledger regenerated. Files listed in SL8 evidence below.
2026-10-17 20:50 UTC | SL2 | merged 64869e6 | +167/-6 | `tests/test_manager_replacement_unit.py` (3 passed), `tests/test_manager_continuity.py` (3 passed), `tests/test_manager_handoff.py` (7 passed, 3 subtests); owner-backed execution and replacement checks need the gate (AF_UNIX bind denied) | merged queued-generation fence and acquisition safety; Astra's cross-schedule defect was fixed; live replacement route is blocked pending orchestrator/PROGRAM entrypoint. Files listed in SL2 evidence below.

### SL3 worker evidence

- Routed paginated project/task reads and bounded Events history under `otto show`; retained root `status` as the portfolio status entrypoint and retained `events` as a compatible route to the same authorized history facade. Removed the top-level `overview`, `tasks`, and `task` routes after adding their supported `show` equivalents and migrating generated route hints. The CLI diff measures 53 added and 72 removed lines; no projection module was deleted because status, inbox, and Events reads have different authorization and data scopes.
- Changed files: `.project/PROJECT.md`, `src/otto/portfolio/cli.py`, `src/otto/portfolio/intake.py`, `src/otto/portfolio/show.py`, `tests/test_cli_read_routes.py`, `tests/test_otto_show_status.py`.
- `tests/test_cli_read_routes.py` passed (3 tests), covering project actor/scope/limit/cursor forwarding, task detail pagination, and actor/grant/scope/cursor forwarding through `show history`. The actual owner-backed project cursor regression is in `tests/test_otto_show_status.py` and needs the gate: AF_UNIX bind was denied during fixture setup. `tests/test_project_history.py` and `tests/test_otto_show_status.py` also need the gate for the same fixture setup failure. No test assertions were weakened.

### SL4 worker evidence

- Retired `src/otto/portfolio/events_candidate_proof.py` (148 lines) and `src/otto/portfolio/observability_contract.py` (387 lines), their package exports, and test-only wrappers `src/otto/portfolio/tests/test_d05_events_candidate_proof.py` (95 lines) and `src/otto/portfolio/tests/test_observability_contract.py` (102 lines). Exact source deletion: 535 portfolio lines; proof-test deletion: 197 lines.
- Updated `src/herzchen/usage/contract.py` so its current Events seam identifies only `src/herzchen/kernel/history.py` and maintained `src/otto/portfolio/observability_views.py`. `src/otto/portfolio/tests/test_observability_views.py` now checks that the retired proof symbols are absent from the package API; `tests/test_usage_contract.py` checks the current seam list.
- Regression evidence: before removal, the new view/API check failed because `CandidateProofError` was exported, and the new Usage seam check failed because it listed the historical contract. After removal: `tests/test_usage_contract.py` passed (9 passed, 11 subtests); `src/otto/portfolio/tests/test_observability_views.py` passed 5 tests and 7 subtests, with its real Store/reader socket test needing the gate (sandbox denied AF_UNIX bind).
- Retained route checks needing the gate: `tests/test_portfolio_status.py` (10 failures at owner setup due sandbox denied AF_UNIX bind); `tests/test_host_startup_composition.py` (2 passed; host-start test needs the gate due sandbox denied AF_UNIX bind). No assertions were changed. Controller files were not deleted: the ledger's static zero-import counts did not establish absence of runtime entrypoints.
- Production/source scan across `src`, `install/controller`, `tests`, and `docs` found no remaining live import or entrypoint references to either deleted module. Pinned paths remain only inside immutable historical qualification records (`install/controller/prepared/.../runtime-manifest.json` and `src/herzchen/kernel/tests/d02-evidence/`); those records were preserved. Changed files: `.project/PROJECT.md`, `src/herzchen/usage/contract.py`, `src/otto/portfolio/__init__.py`, `src/otto/portfolio/events_candidate_proof.py` (deleted), `src/otto/portfolio/observability_contract.py` (deleted), `src/otto/portfolio/tests/test_d05_events_candidate_proof.py` (deleted), `src/otto/portfolio/tests/test_observability_contract.py` (deleted), `src/otto/portfolio/tests/test_observability_views.py`, `tests/test_usage_contract.py`.

## SL1 worker evidence

Files changed: `src/otto/portfolio/role_context.py`, `src/otto/portfolio/__init__.py`, `src/otto/portfolio/advisor_context.py` (deleted), `src/otto/portfolio/tests/test_direction_invocation.py`, `tests/test_manager_journey_service.py`, and `tests/test_project_advisor_context.py` (deleted). `advisor_context.py` was 282 portfolio lines, with zero production callers beyond three package exports and one dedicated test file; source, controller, command, and dynamic-reference scans found no retained caller. Those 282 lines and four export lines were removed, along with 127 lines of tests specific to the retired adapter. The canonical direction resolver and DueRecord delivery code remain in place.

The focused manager-brief projection regression failed before implementation on missing `direction_context` and passes after implementation: `tests/test_manager_journey_service.py -k effective_manager_brief` (2 passed). `tests/test_project_advisor_delivery.py` reports 28 passed and one **needs the gate**: `OwnerAdmissionTests.test_adoption_base_claim_reconciles_before_allowance_gateway_and_provider` reaches a Unix socket bind denied by this sandbox. `src/otto/portfolio/tests/test_direction_invocation.py` reports eight **needs the gate** at the same fixture socket bind, including the new replacement regression; none reached its assertion here. Assertions were not weakened.

### SL1 Astra review

Astra reviewed `4dee01c..task/SL1` before merge and found no concrete defects. It confirmed the brief projection uses the canonical adopted revision, the new replacement regression covers newer drafts and foreign responsibility directions, the removed adapter has no retained production caller, DueRecord delivery/wake and canonical resolution are unchanged, and the SL4 removals remain absent. The manager accepted the review without additional changes. 

## SL8 worker evidence

Added `otto status --friction`, generated from the same injected authorized Events reader used by the Events views. The query is scoped to the projects in the selected portfolio, uses a fixed 30-day window, and reads at most 200 rows. If the reader/grant is unavailable, denied, behind, or returns another page, counts are unavailable rather than treated as zero. Explicit evidence supports counts for questions, refusals, `next_action`, reworks, unknown effects, and answer waits; heavy seconds and tokens per accepted task remain unavailable when their retained measurements are absent. No manual friction state or deletion was introduced.

Changed files: `src/otto/portfolio/cli.py`, `src/otto/portfolio/observability_views.py`, `tests/test_status_friction.py`, `.project/PROJECT.md`.

The focused CLI regression was added before implementation and passes: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_status_friction.py` (2 passed). It seeds retained event rows for every friction category and verifies the portfolio project scope, grant forwarding, bounded limit, and unavailable values for denied/missing measurements. No tests were weakened. No gate-only checks were needed for this task.

### SL3/SL8 Astra integration follow-up

- Astra identified that installed `otto` reached `cli.owner_verb` without `observability_views` or `observability_grant`. `owner_verb` now composes those only from the exact `session.owner.project_read_grant` already issued by `HostSession`, preserving its authenticated principal, finite project IDs, policy source, and policy revision. It rejects refs outside that grant and binds the CLI actor to the installed owner actor. The hostctl `--project-ref=JSON` spelling now supplies the same existing finite grant as the split argument form. The maintained `show history` route remains valid and now works through the installed owner path.
- `status --friction` now accepts one or more explicit `--project-ref` values. The owner grants only those refs through the same existing project read grant; the friction reader intersects them with status's project rows and marks coverage partial when the requested scope is absent, inaccessible, behind, or does not cover the full selected portfolio. It does not manufacture an all-portfolio history grant.
- Changed files: `src/otto/portfolio/cli.py`, `src/otto/hostctl/cli.py`, `tests/test_owner_observability_cli.py`, `.project/PROJECT.md`.
- `tests/test_owner_observability_cli.py`: 5 passed through the production `cmd_portfolio` and `owner_verb` entrypoints with fake owner sessions/history reader; checks `--project-ref=JSON` forwarding, actor binding, project grant restriction, `show history`, and `status --friction`. `tests/test_cli_read_routes.py`: 3 passed. The regression avoids starting an Otto owner, as required by the session boundary.

### SL3/SL8 focused test and usage follow-up

- Updated `tests/test_status_friction.py` to pass an explicit `--project-ref` and a matching `ProjectHistoryGrant`; the denied-read case now also has an explicit scoped project and grant. This keeps the finite-scope requirement intact.
- Moved owner observability composition and editor-host setup inside `owner_verb`'s existing `SystemExit` guard and capture parser stderr. Malformed history CLI arguments now return the established structured `usage` error instead of escaping the owner handler. Added a regression without using `--help`.
- Changed files: `.project/PROJECT.md`, `src/otto/portfolio/cli.py`, `tests/test_owner_observability_cli.py`, `tests/test_status_friction.py`.
- `tests/test_status_friction.py`: 3 passed. `tests/test_owner_observability_cli.py`: 6 passed. Ran each file in a separate pytest process; no owner or staging run was started.

## SL5 decision: keep Vision and Native5 until CUTOVER

The orchestrator decided on 17 Oct 2026 to keep Vision and Native5 until CUTOVER/PROGRAM DELETE. DELETE should recheck these exact installed callers after controller retirement and remove the surfaces only when no caller remains outside the retired controller:

- Vision owner composition: `install/controller/shared_operating_service.py:412-413`; exact adopted selection pin comparison: `src/otto/portfolio/owner_vision.py:38`.
- Native5 shared composition and packet loading: `install/controller/shared_operating_service.py:157,365,368,389,589` and `install/controller/scoped_client_service.py:41`.
- Prepared-context Native5 path: `install/controller/prepared_context_hold.py:50`.
- Adjacent retained paths checked during the same scan: root lane loading at `install/controller/scoped_client_service.py:36`, and `OwnerAuthoringIngress` at `install/controller/operating_service.py:210`.

The Vision disablement candidate is not caller-free: `vision_command.py:143` invokes `disable_guidance`, `vision_pack.py:234,279` controls the field/record, tests assert it, and `owner_vision.py:38` compares the entire selection to adopted pins. Leave that contract in place pending a separately scoped pin migration.

## Questions for the orchestrator

1. **SL2 replacement wiring:** `OwnerManagerReplacement` and `ManagerContinuity.replace_session` have zero production callers in this clone; the live manager handoff is a read projection through `manager_journey_service.py`. Wiring a native replacement entrypoint would overlap PROGRAM's in-flight owner/manager work. SL2 closes the live queued-generation admission defect and hardens the existing replacement composition, but cannot claim a live route consolidation or delete a redundant route until the owner entrypoint lands. This task remains blocked as instructed.

## Audit follow-up (17 Oct 2026)

Reviewed `/Users/hannahomalley/Developer/otto-program/ops/audits/20261017b/DEADCODE.md` and `CLISURFACE.md`; the audit snapshot is canon/main `eb9b6cd`. The read-only source checkout is at `2212569`; the SLIM line remains based at `163925e`. Updated `.project/tasklist.md` with scoped deletion and UX tasks, using `git grep` across `src`, `tests`, `ops`, and `install`. In-scope caller findings: `current_packet.py` and `execution_resume.py` have no named callers beyond three `execution_resume` package exports; `advisor_host_command.py` is referenced only by its dedicated test; the `otto-gateway` script is referenced by packaging and its packaging test. SL3 already removed the duplicate root `overview`, `tasks`, and `task` routes. `sync-docs` is owned for implementation removal by PROGRAM A6; SL7 updates docs only. Do not duplicate PROGRAM ownership of the Evidence workflow switch, fleet `done.summary`, Vision/Native5 controller retirement, or manager replacement wiring.

The refreshed tasklist adds SL7A for documentation that does not depend on SL6 and groups the remaining audit work as SL9A-E. It keeps SL2/SL6 blocked on manager-replacement wiring. Vision disablement remains intact because its result is invoked by `vision_command.py` and adopted selections are exact-pinned by `owner_vision.py`; changing it requires a separate pin migration.

## SL2 worker evidence

Changed files: `src/otto/portfolio/manager_replacement.py`, `src/otto/portfolio/execution_operations.py`, `tests/test_manager_replacement_unit.py`, `tests/test_owner_manager_replacement.py`, `tests/test_execution_operations.py`, `.project/PROJECT.md`. No production lines were deleted: the replacement composition has zero production callers, so no redundant live route could be removed safely. `manager_handoff.py` and `manager_continuity.py` were inspected and retained without edits.

Socket-free regressions failed before the changes: queued manager generation was not rechecked at final admission; another schedule/request could reacquire after an unresolved start; simultaneous same-key calls could both pass the absent-intent check. The final admission check now validates the current manager assignment generation before provider launch. A retained intent is scoped to assignment generation/native session, with the exact schedule/project/task pin; a per-call claim and readback prevent two simultaneous callers from acquiring twice. `tests/test_manager_replacement_unit.py`: 3 passed. `tests/test_manager_continuity.py`: 3 passed. `tests/test_manager_handoff.py`: 7 passed, 3 subtests. `tests/test_execution_operations.py`: 25 passed, 3 subtests; one owner-backed case needs the gate because AF_UNIX bind was denied. `tests/test_owner_manager_replacement.py` needs the gate: all 7 cases fail during owner fixture setup at AF_UNIX bind. No assertions were weakened.

### SL2 Astra review

Astra reviewed the original SL2 diff and reproduced the cross-schedule reacquisition defect. The manager sent it to the same worker, which added the schedule-independent identity and concurrent-call regression. Astra rechecked the fix and found no remaining custody defect. It noted that the socket-free concurrency fixture uses permissive `setdefault`; production's retained writer rejects a changed payload under an existing logical key, so that collision also prevents duplicate acquisition. The manager accepts the fix; live route integration remains the question above.

Astra later found that the new structured held replacement responses lacked `next_action` under PLAN §15.2. The follow-up adds owner reconciliation guidance and explicitly prohibits retrying in the same assignment generation/native session. The focused regression asserts the guidance and unchanged acquisition count; 5 passed. Astra reviewed the follow-up before merge and found no custody or retry defect.

## Remaining dependency blocks

- SL6 is blocked because its declared SL2 dependency has no production replacement entrypoint until PROGRAM/orchestrator wiring is decided.
- SL7 is blocked by SL5's unanswered keep/retire decision and SL6.
- SL9 is blocked by the dependent rows above and the measured deletion shortfall: 654 net top-level portfolio lines removed versus 11,980 required. The remaining ledger entries are candidate gross sizes with live callers; further removals need measured parity evidence and an agreed path past PROGRAM-owned files.

### Final whole-project Astra review

Reviewed `git diff 163925e...proj/slim` against the project goal, plan, tasklist, and PROGRAM §§14–15 after merge `ea52539`.

- Astra reproduced the stale friction fixture failure and found that malformed owner history arguments escaped the structured usage handler. Both were fixed in `ea52539`: friction tests now supply explicit project refs and matching finite authenticated grants, and owner argument parsing is inside the `SystemExit` guard with a regression that avoids `--help`. Manager reruns: `tests/test_status_friction.py` (3 passed) and `tests/test_owner_observability_cli.py` (6 passed).
- Astra required final inventory corrections. Ledger regenerated and test rerun: `tests/test_slim_ledger.py` (1 passed); it now records 47,266 current top-level lines / 96 modules, distinct from the immutable 47,920 / 99 baseline. Final top-level portfolio diff: +308/-962, net 654 removed, leaving 11,326 of the 11,980 deletion target.
- Astra found no further correctness, custody, or authority defect. It confirmed the retained-history classification, finite owner grant wiring, adopted-direction projection, replacement generation fence, and refusal reconciliation guidance. Corrected log entries to actual merge SHAs (`a4c0a8f`, `ee9a30d`).
- The project remains partial: SL2 production replacement route, SL5 Vision/Native5 decision, SL6 cold-agent UX pass, SL7 dependent docs, and SL9 deletion closure remain blocked as recorded. Controller retirement and cold-agent acceptance are not achieved. Owner-backed gate tests remain required; no owner or staging process was started.

### SL8 retained-history correction

Astra found the initial friction classifier treated omitted issue data as known-zero and did not recognize retained result observations whose `native_result` mapping has `outcome: unknown`. Fixed the classifier to count the real retained `native_result.outcome` shape and to report a friction count unavailable when non-empty projection rows do not establish that category's coverage. Added regressions that construct issue and result facets with `herzchen.kernel.history.transition`, then pass them through the Events view-row summary shape. Under the previous classifier those assertions would have observed question `known: 0` and unknown-effects `known: 0`; now questions are unavailable because `state()` drops `value/schema/awaiting`, while the unknown retained result counts as one.

Changed files: `src/otto/portfolio/observability_views.py`, `tests/test_status_friction.py`, `.project/PROJECT.md`. Focused check: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_status_friction.py` (3 passed). No assertions were weakened.

### SL2 refusal guidance follow-up

The socket-free regression failed before this edit because held replacement results lacked `next_action`. All structured held paths in `OwnerManagerReplacement.replace` now tell the caller to ask the owner to inspect the original retained intent, reconcile manager/native custody, and submit a new accepted schedule only after resolution. The guidance explicitly forbids another acquisition under the same assignment generation and native session. An unavailable intent readback now returns a held result with this guidance; mismatched retained attribution still raises `PermissionError`. No acquisition or generation fence was relaxed.

Changed files: `src/otto/portfolio/manager_replacement.py`, `tests/test_manager_replacement_unit.py`, `.project/PROJECT.md`. Focused check: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_replacement_unit.py` (5 passed). No gate-only test was required for this follow-up.

### SL9B paused advisor host prototype retirement

- Deleted `src/otto/portfolio/advisor_host_command.py` (115 lines) and its only importing test, `tests/test_manager_advisor_paused_host.py` (190 lines), for 305 gross lines removed. Before deletion, `git grep` across `src`, `tests`, `ops`, and `install` found only the dedicated test import outside runtime manifests; no production or ops caller existed. External imports were not verifiable in this clone.
- `install/README.md` identifies `install/runtime-manifest.json` as a byte-for-byte 15 Oct 2026 snapshot of the live controller, with S0 responsible for reproducible builds. Preserved its pinned digest entry and the prepared antecedent manifest unchanged; neither is a maintained current manifest for selective edits.
- Added `tests/test_advisor_host_retirement.py` with a focused absence assertion. `advisor_delivery` and `DueRecord` were not changed; their maintained behavior tests remain intact.
- Changed files: `.project/PROJECT.md`, `src/otto/portfolio/advisor_host_command.py` (deleted), `tests/test_manager_advisor_paused_host.py` (deleted), `tests/test_advisor_host_retirement.py`.
- Focused validation: `tests/test_advisor_host_retirement.py` (1 passed). `tests/test_project_advisor_delivery.py` ran 28 passed and 1 failed at owner-service AF_UNIX bind (`PermissionError`); this case needs the gate. No assertions were weakened.

- Follow-up: restored the 15 Oct pinned runtime manifest unchanged after verifying its provenance in `install/README.md`; the snapshot remains historical evidence and its candidate path is not a live caller.
