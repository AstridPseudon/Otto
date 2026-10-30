**Use five managers initially, retain B as the manager for F, and appoint G only after the Otto port qualifies. A owns Otto’s integration queue; C owns product qualification.** Separate managers are useful for D and E, provided they receive exclusive file scopes and staged integration gates.

My baseline is **137 human engineer-days**, with a **71-working-day critical path** under the staffing assumptions below. Plan for **15–17 calendar weeks**, excluding an unresolved Windows-access delay.

This was read-only. I used two Luna audits and independently checked the decisive source paths, branch overlaps, existing tests and saved results. No tests, services, edits or git writes ran.

**Evidence that changes the plan**

- O1 must include `product_service.py` and `execution_host.py`: composition installs automatic selection, and the capacity tick invokes it. Worker `done` reaches a method that advances the branch. These are verified behavior changes, not just instruction changes. [Automatic dispatch](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/otto/hostctl/product_service.py:960), [capacity tick](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/otto/portfolio/execution_host.py:1163), [landing implementation](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/fleet/landing.py:105).
- The test investigator’s “Otto integration artifacts not found” conclusion does not hold in this workspace. The integration runner and baseline summary are present. The saved STAGE2CLIENT check reports **121 passed, one failed, one skipped, in 739.19 seconds**. Full-suite elapsed time remains unestablished. [Integration runner](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/integ.py:1), [saved check](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/runs/STAGE2CLIENT/check.out:21).
- The FIX document says its mains equal the served commits. The available checkout does not: Agent main is `670baed9`, Runtime main is `15eb2b6c`, and both differ from the named served revisions. The stale-command carry-over still exists, including on updater handoff `5d844436`. **Refresh bases before treating the spec’s anchors as current.** [Spec’s base claim](/home/user/repo/astrid-install/plans/FIX-windows-install-findings.md:3), [current carry-over](/home/user/banodoco/astrid-agent/astrid/installer/backend.py:200).
- The dispatcher currently pushes CI branches to the separate owner repository, while the revised CI plan requires product-repository Actions. B and C must resolve this interface before P1. [Dispatcher target](/home/user/repo/astrid-install/tools/dispatcher.sh:54), [CI requirements](/home/user/repo/astrid-install/plans/TEST-cross-platform-testing.md:148).

**Workstreams and managers**

“Owns” includes corresponding focused tests. Shared files are governed by the ownership table below.

| Manager / workstream | Goal and ownership | Must not touch independently | Start and handoff | Days |
|---|---|---|---|---:|
| **A — canon and Otto integration** | Phase 0; O1; O2. Owns dispositions, mandate freeze, Otto integration tooling, dispatch/composition changes, client/CLI/authentication repairs. | Product behavior; D’s custody semantics; B/F’s control protocol; G’s storage design. | Starts now. Delivers O2 base to D; accepts D’s integrated custody contract; builds the final Otto candidate for F’s qualification. | **14** |
| **B — thin-path controls** | Astrid plan repo: `tools/`, receipt/message/replay fixtures, `MANAGER-CODEX.md`, `CODEX.md`, relevant `ORCHESTRATOR.md` instructions. Owns P1 and P3. | Product installer/chat files; Otto production code during Phase 1. | Receipt work starts now; launch-policy wiring follows Phase 0. Hands an operating control path to C and a judged interface to F. | **18** |
| **C — Windows product and pilot** | `banodoco/astrid-agent`, App integration UI, Runtime verification seams, Pinokio candidate identity, product workflows; FIX-W1–W6 and COH-C14. | Plan-repo dispatcher/control implementation; Otto; unrelated updater expansion. | Runner/base audit now; W4 and W1 core early. Remaining product work supplies the controlled pilot. Hands exact-tuple evidence and operational observations to B. | **29** |
| **D — custody and effects** | O3: LABPIN, LANDPROOF, PL3, remaining PROCLIFE, native/runner EFFECTS. Owns custody, effect ledgers and their recovery tests. | Automatic selection, brief policy, new messaging authority, publication policy. | Contract spike now; integrated implementation after A’s O2 base. Hands one reconciled custody/effect contract to A, then F. | **18** |
| **E — instructions and worker surface** | O6: reduced PACKS, audited SLIM slices, TP3/TP6, effective briefs and cold-worker acceptance. | Launch authorization, effect settlement, authoritative status/message storage. | Brief work and isolated preparation now. Live worker composition waits for F’s O4/O5 ports. Hands worker-surface evidence to A/F. | **12** |
| **F — Otto control port; same manager as B** | O4/O5/O7: mandate/gateway, reservations, receipts/messages, liveness/supervision, batch tools and real-worker qualification. | D’s effect identity rules; E’s policy content; G’s storage authority. | Starts after P3 and accepted O3. Hands a qualified Otto candidate and frozen storage-facing contracts to G. | **22** |
| **G — git authority, transfer and retirement** | G1–G3: kernel store/operations, host and runner storage adapters, exporter, portable startup, audited retirement. | Reopening pilot policy; unrelated refactors; deletion without caller evidence. | Staff after F qualifies and the post-pilot git decision holds. Hands final cloud/recovery evidence and retired-route inventory to A. | **24** |
| | | | **Total** | **137** |

The source ownership follows the branch-derived file sets and overlap matrix, with O1’s composition files added from direct inspection. [Otto ownership evidence](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/astra-breakdown/luna/r-otto-files.md:3), [pilot ownership evidence](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/astra-breakdown/luna/r-pilot-files.md:1).

**Parallel schedule**

These are working-day offsets from kickoff, assuming one executor supplies one engineer-day per working day. The schedule needs **six executor slots at peak**, usually fewer; B and F each need three concurrent slots briefly. Managers are lead responsibilities, not five additional full-time engineers charged on top.

| Window | Managers running together | Exit milestone |
|---|---|---|
| **0–2** | A: dispositions/mandate. B: receipt primitive. C: runner and base audit in parallel. D: custody contract spike. E: brief contract. | Phase 0 fixed; runner evidence or explicit access blocker; shared contracts drafted. |
| **2–11** | A: O1 then O2. B: launch, messages, monitor, supervisor, replay and batch controls. C: W4 and W1 core. E: isolated SLIM/TP preparation. | O2 accepted; thin path ready for canary. |
| **11–12** | B+C: P1 canary. D: O3 implementation begins on O2. A maintains merge ownership. | **P1 passes; counted pilot starts.** |
| **12–22** | C: W1 updater, W2, W3 and W5. D: custody/effects branches and fault replay. A: O3 integration. B: control operation and evidence collection. | O3 accepted by day 22; product work continues. |
| **22–29** | C: W6, final required checks, Windows acceptance and evidence closeout. B: P3 judgement. | **P3 by day 29.** |
| **29–41** | B becomes F: mandate and reservation work in parallel, then gateway; receipts, messaging, liveness and batch tools. A owns shared-file integration. | O4/O5 ready; O7 batch tools prepared. |
| **41–50** | E: live worker composition and cold-worker journey. A: integrated candidate. F: qualification of that exact candidate. | **Otto port qualified by day 50.** |
| **50–58** | G: git design spike, writer fencing, then projections and cloud adapter in parallel. A available for integration arbitration. | Git/cloud foundation passes failure tests. |
| **58–71** | G: export/readback, transfer, cloud journey, core and ops retirement, final qualification. | **G1–G3 complete.** |

The **71-day critical path** is:

`Phase 0 (2) → thin-path critical chain/P1 (10) → remaining pilot work/P3 (17) → Otto port/convergence (21) → git/transfer/retirement (21)`.

O2/O3 run beside the pilot and finish before they are needed. Windows access becomes critical if it misses P1. E’s final worker integration becomes critical after O5.

**The pilot has a seven-calendar-day minimum observation period, not a seven-engineer-day implementation budget.** This decomposition puts about three working weeks of real product work through the controls. P3 requires both the observation period and release acceptance. If the project finishes sooner in practice, stop its schedules; do not manufacture activity to fill the week. That distinction is explicit in the earlier roadmap. [Pilot gates and observation rule](/home/user/repo/astrid-install/retro/evidence/otto-roadmap/astra-roadmap.md:69).

**Shared-file ownership and integration**

A is the **dedicated Otto integration owner**, but not a separate full-time qualification manager. C owns product acceptance, B owns pilot-control judgement, and F owns Otto acceptance. Each stream manager integrates its own branch; A integrates across Otto streams.

A owns the merge decision and grants **one editing lease per shared file at a time**. This does not require A to author every change.

| Hot spot | Editing and integration order |
|---|---|
| Otto `hostctl/{service,serve,cli,register,config}.py` | **A/O2 → F/control composition → E/live brief wiring → G/cloud startup.** Isolated helpers can be developed concurrently; shared composition edits receive sequential leases. |
| Otto `hostctl/product_service.py`, `portfolio/execution_host.py` | **A/O1 → D/custody and effects → F/gateway and receipts → G/cloud adapter.** Preserve explicitly requested execution while removing selection. |
| Herzchen `fleet/landing.py`, `fleet/tools/{facade,rules}.py`, Otto `hostctl/fleet_landing.py` | **A/submission boundary → D/proof binding → F/receipts and batch integration → E/worker surface → final qualification.** E prepares TP changes early but does not independently merge these files. |
| Otto `agents/{claude_cli,claude_adapter,gateway,owner_runtime,orchestrator_route}.py` | **A/client/auth repairs → D/process/effect wiring → F/launch boundary → E/brief/tool wiring.** G receives them only after port qualification. |
| Herzchen `kernel/{store,operations}.py`, `fleet/runner/{runner,store,server}.py` | **D/effects first; F uses the accepted contract; G replaces storage underneath it.** D’s native and runner slices use separate files; shared runner composition is serialized. |
| Plan repo `tools/dispatcher.sh`, `land.sh`, operating instructions | **B is sole owner.** C supplies CI repository/ref/result requirements. B integrates that contract; C does not patch the dispatcher separately. |
| Agent `installer/backend.py`, `core.py`, `app_update.py`, recovery/platform tests | **C is sole integration owner:** W1 → W3 policy → W5 installer changes → W6. Chat/App and capability work use separate files. |
| Agent capability census/matrix and CI workflows | C commissions runner workflow first; W4 installs matrix/census checks; W5 supplies reconciliation; COH-C14 closes required-check wiring. |

This order is supported by the actual overlapping branch deltas, especially PROCLIFE/EFFECTS/PACKS in adapters and runtime composition, and LABPIN/LANDPROOF/THROUGHPUT in landing. [Overlap matrix](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/astra-breakdown/luna/r-otto-files.md:29).

Every handoff contains the base SHA, bounded delta, owned-file list, focused results, retained unknowns and interface changes. A builds ordered batches, compares failures with the recorded base, and bisects new failures. The existing integration runner already implements that basic approach, but contains machine-specific paths that need adapting. [Existing batching/bisection](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/integ.py:4).

Textual conflicts return to the originating executor under A’s lease. Semantic conflicts go to the relevant contract owner: D for custody/effects, F for launch/control authority, E for brief policy. Unresolved slices leave the batch. **A changed candidate invalidates qualification; baseline parity never substitutes for the required user journey.**

**Executor tasks**

All estimates below include implementation and focused verification. Each task goes to one executor; its subtasks are sequential steps, not additional effort estimates. All tasks are at most three engineer-days. Existing tests are starting points; the “done when” conditions are requirements, not claims of current passing proof.

Path abbreviations:

- `O` = `otto/otto/src`; `OT` = `otto/otto/tests`; `OPS` = `otto/portfolio/ops`.
- `P` = `astrid-plan-repo`.
- `AG`, `AP`, `RT`, `PI` = the Agent, App, Runtime and Pinokio product repositories.
- New helpers/fixtures are identified as new areas rather than asserted existing filenames.

Task rows use the requested order:  
`ID | task | days | difficulty | hard invariant if ≥7 | depends on | done when | files or areas`

**A — 14 days; manager difficulty 8/10.** A must preserve explicit manager authority and candidate identity while several streams change the same composition and landing files.

Existing dispatch/tool/landing tests need changed acceptance cases, not merely reruns. O2 additionally needs an installed-client journey; its saved failing check is not that proof. [Test inventory](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/astra-breakdown/luna/r-tests.md:5).

```text
A1 | Freeze dispositions, bases and pilot mandate | 2 | 6 | — | none | Every branch has a disposition; prior spend/unknown effects are retained; one mandate governs the pilot | P mandate/disposition records; OPS requests/evidence
A1.1 | Inventory refs, unresolved effects and historical spending | 4 | Inventory reconciles against branch and operation records.
A1.2 | Replace paused-program dispositions and identify reserved decisions | 5 | No dropped branch or paused operation is implicitly scheduled.
A1.3 | Fix acceptance, budget, model policy and runner fallback in one mandate | 6 | Every pilot task and paid role maps to the same revision.

A2 | Remove automatic selection and make done submission-only | 2 | 6 | — | A1 | Ready work does not launch without intent; worker done cannot move a project ref; explicit launches still work | O hostctl/product_service.py, portfolio/execution_host.py, fleet/dispatch.py, landing.py, tools, claude_cli.py
A2.1 | Remove selector binding and capacity-pump selection | 5 | Capacity/reconciliation ticks launch nothing without a manager request.
A2.2 | Separate worker submission from manager integration/landing | 6 | Calling worker done records evidence and leaves target refs unchanged.
A2.3 | Update dispatch, tool and landing acceptance cases | 5 | Both negative authority tests and explicit-run positive tests pass.

A3 | Repair and land STAGE2CLIENT delta | 3 | 6 | — | A2 | Fresh installed client works, missing-client registration refuses, and the saved regression is resolved | O hostctl/{cli,service,config,register}.py; OT bundle/CLI/perch tests
A3.1 | Reproduce the saved failure on an identified base | 4 | Failure classification distinguishes the seeded fault from the extra pool failure.
A3.2 | Repair installation, registration refusal and terminal-failure handling | 6 | Each behavior passes its focused case without weakening assertions.
A3.3 | Exercise the delivered client from a clean installation | 6 | Recorded commands use the installed executable and exact candidate.

A4 | Land CLIARGS and ROLEIDS as bounded deltas | 2 | 6 | — | A3 | Absent arguments remain absent; retry authorization holds; reserved principals refuse before writes | O hostctl/cli.py, service.py; portfolio manager-journey routes
A4.1 | Isolate and apply CLI argument handling | 4 | Omitted/explicit argument and retry cases pass.
A4.2 | Apply reserved-identity checks | 6 | Rejected identities leave assignments and admission records unchanged.
A4.3 | Check the combined installed command surface | 5 | Installed commands retain the intended parser and authorization behavior.

A5 | Integrate OBSOWNER and TESTPATCH | 2 | 7 | Caller identity cannot be promoted to owner authority by transport or mocks | A4 | Real owner/socket tests pass for authenticated callers and reject impersonation | O agents/claude_{cli,adapter}.py, portfolio/native_caller_ingress.py, hostctl/serve.py; OT auth tests
A5.1 | Preserve caller identity through adapter and ingress paths | 7 | Foreign or missing identity is rejected before the privileged operation.
A5.2 | Restore real-owner tests and repair their exposed regressions | 6 | Tests exercise actual owner/socket composition rather than permissive substitutes.
A5.3 | Freeze the O2 integration base | 5 | Exact-candidate client/authentication results accompany the handoff to D.

A6 | Integrate the O3 batch | 1 | 6 | — | D7 | One accepted base contains custody/proof/effect slices and their cross-path results | O shared custody/runtime/landing files; OPS integration records
A6.1 | Integrate D's ordered slices and inspect shared-file resolutions | 6 | Every conflict resolution agrees with D's identity/state contract.
A6.2 | Attribute regressions and issue the accepted base | 6 | New failures are resolved or the offending slice is excluded.

A7 | Build and freeze the final Otto port candidate | 2 | 6 | — | E5, F8 | O1–O7 are integrated; regressions attributed; immutable candidate handed to F9 | O shared files; OPS integration/candidate records
A7.1 | Integrate the control and worker-surface branches in the agreed order | 6 | No lease overlap or unresolved semantic conflict remains.
A7.2 | Run batch regression attribution and freeze candidate/artifact identities | 6 | F9 receives exact hashes; subsequent code changes invalidate this candidate.
```

**B — 18 days; manager difficulty 7/10.** The hard coordination problem is making receipts, wake-up and recovery agree while preserving one dispatcher as the pilot writer.

The existing scripts provide request/result markers, process heartbeats and recovery entry points. They do not already establish the proposed receipt, durable-message or declared-exit semantics. [Thin-path seams and gaps](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/astra-breakdown/luna/r-pilot-files.md:1).

```text
B1 | Route all paid pilot roles through the dispatcher | 2 | 6 | — | A1 | Worker, manager, reviewer and supervisor starts check policy, capacity and a recorded reservation first | P tools/dispatcher.sh, role launch helper/config
B1.1 | Add explicit requester, role, task and policy revision to launch requests | 4 | Missing or stale required fields refuse before invocation.
B1.2 | Serialize reservation checks and retain uncertain charges | 6 | Two queued starts cannot consume the same remaining allowance.
B1.3 | Route every paid role through the same entry point | 6 | Launch census finds no remaining direct paid-role bypass; unbounded adapters are excluded from a hard-cap pilot.

B2 | Add append-only tool receipts | 2 | 5 | — | none | Launch/check/land/publish attempts retain input, identity, candidate and outcome, including unknown | P tools/dispatcher.sh, land.sh, new receipt helper/fixtures
B2.1 | Define a compact receipt schema and append operation | 4 | Round-trip fixtures retain all required fields and reject malformed records.
B2.2 | Instrument tool intent and result boundaries | 5 | An interrupted operation retains intent and does not fabricate success.
B2.3 | Generate a basic status projection | 4 | Rebuilding from receipts gives the same state and names unknown outcomes.

B3 | Add message files, ask/reply and wake-up | 2 | 7 | Replacement or duplicate delivery cannot answer the wrong assignment generation | B1, B2 | A durable question wakes the manager; reply reaches the correct worker once logically | P tools/dispatcher.sh, watch.sh, new message helper/fixtures
B3.1 | Define IDs, threads, recipients, generations and resolution state | 5 | Invalid or mismatched routing records refuse.
B3.2 | Implement delivery, wake acknowledgement and reply/resume | 7 | Manager replacement and repeated delivery preserve one logical question/reply.
B3.3 | Expose worker ask and resume-with-log | 5 | A cold worker resumes the asking task with its retained diagnostic log.

B4 | Add declared exits and independent liveness observation | 3 | 6 | — | B3 | Missing starts/exits and expired waits produce attributable observations; unknown is not dead | P tools/run-worker.sh, keepalive.sh, recover.sh, new exit hook/monitor
B4.1 | Record exit kind, waits, expected times and next responsible party | 4 | Each supported exit produces a validated declaration.
B4.2 | Compare declarations with independently observed sessions | 6 | Seeded dead, absent, late and unobservable sessions classify distinctly.
B4.3 | Deduplicate nudges and escalate repeated mismatches | 6 | One incident produces one initial nudge and the specified repeat escalation.

B5 | Add supervisor sweep and compact briefs | 2 | 5 | — | B3 | Sweep nudges managers directly, escalates exceptions and cannot dispatch project work | P new sweep/brief helpers; operating instructions
B5.1 | Build evidence-based sweep inputs and brief projections | 4 | A fresh session can identify work, waits, unknowns and governing mandate.
B5.2 | Implement nudge/escalation decisions and authority limits | 5 | Seeded cases route correctly; supervisor cannot launch workers or land.
B5.3 | Remove conflicting operating instructions | 4 | Current instructions name one control path and distinguish superseded guidance.

B6 | Build the incident-replay harness | 2 | 6 | — | B4, B5 | Repeatable incidents test lost replies, dead managers, missed exits and cold restore | P new replay driver/fixtures and run evidence
B6.1 | Capture deterministic incident fixtures and expected transitions | 5 | Each fixture fails when its intended control is disabled.
B6.2 | Replay restart, duplicate-delivery and liveness cases | 6 | Results preserve IDs, unknowns and the expected responsible party.
B6.3 | Separate natural events, drills, false alarms and owner interventions | 4 | Report totals trace back to individually classified evidence.

B7 | Add manager-selected batch integration and exact-candidate gates | 3 | 7 | Only the checked candidate may advance; an unknown publication cannot be blindly repeated | B2, B3 | Changed/skipped/missing evidence refuses delivery; lost publication reply reconciles by identity | P tools/land.sh, dispatcher.sh, new candidate/gate fixtures
B7.1 | Build ordered batch candidates and retain constituent SHAs | 5 | A seeded regression is attributable to its introduced slice.
B7.2 | Bind required evidence to candidate and artifact hashes | 7 | Changed refs or incomplete checks invalidate admission.
B7.3 | Align product-repo CI routing and reconcile publication results | 7 | Recorded remote state settles a lost reply without creating a fresh publication.

B8 | Run the real control canary and open P2 | 1 | 6 | — | B6, B7, C1 | Real launch/check/ask/reply/wake/cold-restore and Windows access work through delivered tools | P canary/evidence; C's Windows result
B8.1 | Exercise one real task through all pilot control boundaries | 6 | Receipts show actual execution, bounded spend and successful recovery.
B8.2 | Record the controlled-pilot start | 4 | Timestamp and control revision distinguish all later evidence from baseline work.

B9 | Judge controls and freeze the port interface | 1 | 5 | — | C14; at least seven calendar days after B8 | Nudges have benefit/false-alarm decisions; safety controls have replay/risk evidence; port contract is frozen | P pilot decision and interface records
B9.1 | Judge natural events separately from drills | 5 | Every keep/change/remove decision cites its evidence and cost.
B9.2 | Freeze retained interfaces and decide the git-stage condition | 5 | Unresolved false alarms do not become blocking enforcement; G's decision is explicit.
```

**C — 29 days; manager difficulty 8/10.** C coordinates an updater transaction and a frozen cross-repository candidate while native Windows proof is externally constrained.

W1 explicitly includes the updater path; W3 changes update verification policy; W6 changes recovery behavior. COH-C14 cannot finish before W5 supplies its reconciliation test. [FIX rows and order](/home/user/repo/astrid-install/plans/FIX-windows-install-findings.md:54).

The final journey requires PowerShell 5.1 and delivered binaries. Discovery runs with bridge authorization and without provider credentials; the roadmap additionally requires a real chat response. The real-response leg needs an explicitly provisioned, bounded test account where required. [Installed verification](/home/user/repo/astrid-install/plans/FIX-windows-install-findings.md:71), [real-chat acceptance](/home/user/repo/astrid-install/retro/evidence/otto-roadmap/astra-roadmap.md:79).

```text
C1 | Commission usable Windows execution first | 2 | 6 | — | none | A product-repo job actually runs on pinned Windows with PS 5.1, sibling access and retained artifacts | AG workflows/scripts; cross-repo CI configuration
C1.1 | Prove runner admission, shell version and private sibling checkout | 5 | Completed job logs identify image, PowerShell and resolved repository SHAs.
C1.2 | Exercise a minimal installed-product smoke | 6 | Job reaches the installed binary and emits a machine-readable result.
C1.3 | Resolve queued-hosted fallback and record the selected route | 5 | Selected runner executes; the hosted-only plan is reconciled explicitly with 08's fallback.

C2 | Reconcile actual bases and updater prerequisite | 2 | 6 | — | none | Explicit Agent/Runtime/App/Pinokio and updater bases are accepted; stale spec assumptions are corrected | Product refs; AG updater handoff; P FIX/TST base records
C2.1 | Compare served revisions, current mains and updater handoff | 4 | SHA/delta inventory identifies retained fixes and regressions.
C2.2 | Establish the integrated updater base for W1/W3/W6 | 6 | Recovery/configuration focused checks describe the actual base behavior.
C2.3 | Freeze development inputs and remaining updater blockers | 5 | No task silently substitutes main for the agreed updater line.

C3 | Implement W4 and initial COH-C14 checks | 2 | 5 | — | C2 | music.duck, census, approval wording and local-orchestrator exemption are corrected | AG capability config/census, music pack, stale-row filter, matrix/ledger tests
C3.1 | Correct the matrix and regenerate the census with reviewed differences | 4 | Matrix/census tests pass and every lock change is explained.
C3.2 | Fix the approval message and stale-row exemption | 4 | Tests reject version-directory advice and retain warnings for genuinely stale rows.
C3.3 | Wire matrix/census checks into CI | 5 | A deliberately failing matrix/census case makes the candidate check fail.

C4 | Implement W1 version-owned defaults and carry-over core | 2 | 6 | — | C2 | Bare/missing/pruned values are replaced; valid typed external overrides survive | AG installer/backend.py, services.py, platform/service tests
C4.1 | Classify version-owned paths and permitted external overrides | 5 | Executable/directory cases include type, existence and versions-root boundaries.
C4.2 | Regenerate defaults and explain discarded settings | 6 | Selected-version command/cwd/interpreter/shim values reach the declaration.
C4.3 | Exercise install and repair matrices | 5 | Bare, missing, pruned and valid-override cases pass.

C5 | Complete W1 on the updater path | 2 | 6 | — | C4, B8 | Update and interrupted-update recovery use the same setting policy | AG installer/backend.py, core.py/app_update.py seams, recovery tests
C5.1 | Apply the setting policy to the integrated updater routes | 6 | Update cannot retain the stale declaration through an alternate path.
C5.2 | Exercise update/recovery and external-override cases | 6 | Selected-version defaults and valid user overrides survive each tested transition.
C5.3 | Integrate the complete W1 delta | 5 | W1 evidence names the updater base and all install/update/repair cases.

C6 | Implement W2 discovery failure classification | 2 | 6 | — | C3, C4, B8 | Existing helpers distinguish missing command/cwd, exit and timeout on native Windows | AG chat/discoveryProbe.ts, acpProcessHost.ts and tests
C6.1 | Extend existing helper results without a universal launcher | 5 | Each failure class has a specific, path-free user-facing reason.
C6.2 | Test native exe/cmd invocation and quoting | 6 | Windows logs show both formats invoked through the delivered helper.
C6.3 | Integrate after W1 and check discovery behavior | 5 | Classification survives the actual service configuration.

C7 | Implement W3 shared verification observations | 2 | 6 | — | C5, C6 | One observation set reports Runtime identity, services, authorized discovery and required capabilities | AG installer verification/chat bridge; RT verification interface/tests
C7.1 | Define the observation result and failure reasons | 5 | Fixtures represent healthy, failed and unavailable observations distinctly.
C7.2 | Gather observations through actual service/bridge interfaces | 6 | Broken discovery is visible even with a healthy pack host.
C7.3 | Exercise identity and readiness mismatches | 6 | Wrong Runtime identity and missing required capabilities fail their observations.

C8 | Implement W3 install/update verification policy | 3 | 8 | Update rolls back for a new regression, without treating pre-existing failure or hosted App state as a local rollback cause | C7 | Install fails any required failure; update applies the before/after policy and retains evidence | AG installer/backend.py, core.py/app_update.py, recovery/verify tests
C8.1 | Define the before/after policy table | 6 | Every healthy/failing/unavailable transition has an explicit outcome.
C8.2 | Bind observations to the update transaction | 8 | Fault tests cannot compare observations from different versions or operations.
C8.3 | Exercise regression, pre-existing failure and hosted-App cases | 8 | Only the specified local regression triggers rollback; App build checks stay in CI/canary.

C9 | Complete W3 truthful chat and App behavior | 2 | 5 | — | C7 | Chat and /agents expose failure truthfully; App shows the reason and backs off polling | AG chat bridge/models/local-agents; AP integrations/astrid UI and tests
C9.1 | Propagate degraded discovery state through chat and /agents | 5 | Failed discovery never produces a ready agent.
C9.2 | Add App reason display and bounded polling backoff | 5 | UI test observes reduced retries and recovery when health returns.
C9.3 | Check the Agent/App contract together | 5 | The App renders the actual emitted reason, including unknown/unavailable state.

C10 | Implement W5 dependency completeness and installer summary | 3 | 6 | — | C8, C9 | Required tools are bundled/hashed and originate from the install; optional-tool reporting is accurate | AG requirements/runtime.lock, pyproject.toml, generation action, installer/tools.py/backend.py, tests
C10.1 | Lock/bundle edge-tts and yt-dlp and reconcile declarations | 6 | One test checks all existing pack tool declarations against shipped dependencies.
C10.2 | Preserve user-supplied codex and optional OCR semantics | 5 | Missing-tool summary matches preflight and does not claim optional tools are bundled.
C10.3 | Add installed-origin checks and installer-scoped uv copy mode | 6 | Removing runner PATH assistance exposes missing shipped tools; cross-volume leg succeeds.

C11 | Implement W6 bounded rollback recovery | 3 | 8 | Recovery cannot destroy the retained backup or later user changes, including after a crash during failed rollback | C2, C8, C10 | Retry is bounded, needs-repair persists, backup survives and explicit rerun repairs forward | AG installer/core.py, backend.py, app_update.py; recovery/backup tests
C11.1 | Specify retry and needs-repair transitions | 6 | Broken-target and repeated-start cases have bounded outcomes.
C11.2 | Persist failure state while protecting backup and user edits | 8 | Fault injection at each state boundary preserves recovery assets and post-backup changes.
C11.3 | Implement and test explicit forward repair | 8 | Rerunning the installer repairs from needs-repair without an automatic retry loop.

C12 | Finish COH-C14 and candidate admission checks | 1 | 6 | — | C3, C10 | Matrix, census and dependency checks are required; absent/skipped/cancelled evidence refuses | AG .github/workflows/ci.yml and required-check/gate configuration
C12.1 | Add dependency reconciliation to the required set | 4 | A seeded dependency omission makes the required check fail.
C12.2 | Exercise unconditional aggregate-gate decisions | 6 | Failed, missing, skipped and cancelled dependencies all refuse admission.

C13 | Qualify the exact installed-product candidate | 2 | 7 | The tested repo/artifact tuple must be the tuple admitted for delivery | C11, C12 | Required native Windows journey, real chat, negative control and three-OS smoke pass on recorded inputs | Product journey workflows/scripts; frozen tuple and result artifacts
C13.1 | Freeze repo SHAs, manifest/artifact hashes and check set | 5 | Qualification performs no sibling-main fallback.
C13.2 | Run PS 5.1 fresh install, stale-setting update and reinstall | 7 | Delivered binaries pass identity, capabilities, authenticated discovery and W6 recovery checks.
C13.3 | Run real chat and broken-command negative control; close platform evidence | 7 | Real response succeeds; broken command makes verify fail; required smoke and App build identity evidence are complete.

C14 | Close pilot evidence and hand off to P3 | 1 | 5 | — | C13; observation period complete | Release and operational evidence distinguish baseline, natural incidents, drills, costs and gaps | P pilot evidence; product candidate result links
C14.1 | Reconcile run/receipt/message/cost records | 4 | Every counted event belongs to the controlled pilot revision and period.
C14.2 | Record outcome, interventions and unresolved gaps; stop schedules | 5 | B can judge controls without reconstructing events from conversation.
```

**D — 18 days; manager difficulty 8/10.** Effect identity and process custody must remain distinct but consistent through uncertain outcomes.

The effects branch already claims before adapter invocation and retains unknown outcomes. PROCLIFE identifies processes by `(pid, birth)` and treats missing census evidence as uncertainty. These are the contracts to preserve. [Native effect claim](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/projects/effects/src/otto/agents/effect_ledger.py:36), [custody rules](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/projects/proclife/src/herzchen/fleet/custody.py:1).

```text
D1 | Spike the common custody/effect contract | 2 | 7 | One logical effect retains its identity while process custody and transport outcome vary independently | none | State table names authoritative IDs, transition owners, covered effects and unresolved gaps | O kernel/operations, custody, native/runner ledgers; contract fixtures
D1.1 | Map branch identities and already-landed PL1/PL2 behavior | 5 | Matrix identifies overlaps and prevents reintroducing obsolete deltas.
D1.2 | Define claim, unknown, reconciliation and cleanup transitions | 7 | Crash/lost-reply traces never require inventing a replacement effect key.
D1.3 | Freeze file leases and the bounded effect scope | 5 | Native turns and runner jobs have explicit owners; unsupported external effects remain named gaps.

D2 | Integrate LABPIN and LANDPROOF | 3 | 7 | Assignment, lab and checked SHA remain bound until evidence capture completes | D1, A5 | Wrong assignment/SHA refuses; changed candidates lose proof; cleanup cannot precede capture | O work/assignments.py, fleet/labs.py, landing.py, hostctl/fleet_landing.py
D2.1 | Apply task/lab/assignment binding | 6 | Foreign and stale bindings leave the target line unchanged.
D2.2 | Apply exact-candidate proof and capture ordering | 7 | Mutated candidate and premature cleanup tests refuse safely.
D2.3 | Repair rework/capture regressions on the O2 base | 7 | Rework preserves the same assignment and retained evidence.

D3 | Complete PL3 reader custody across startup routes | 2 | 7 | Every reader/startup route retains the same execution identity, including the external-owner bridge | D1, A5 | Constructor and recovery route matrix passes | O hosts/contract.py, codex_host_reader.py, orchestrator_route.py, owner/bootstrap adapters
D3.1 | Enumerate constructors and externally owned startup routes | 4 | Route census has a test entry for every supported constructor.
D3.2 | Bind and restore reader custody | 7 | Restart and external-owner cases recover the correct retained execution.
D3.3 | Check stale and foreign identity refusal | 7 | Mismatched custody cannot be attached to the new session.

D4 | Reconcile remaining PROCLIFE cleanup and capacity holds | 3 | 8 | Cleanup never signals a reused identity or frees capacity while owned-process disappearance is uncertain | D3 | Birth-gap, escaped-descendant and crash-at-spawn/cleanup cases preserve custody and holds | O fleet/custody.py, kernel/process_identity.py, agents/owner_runtime.py, runner/runner.py, execution_host.py
D4.1 | Harvest remaining deltas against accepted PL1/PL2/PL3 | 5 | Delta inventory excludes already-landed or superseded behavior.
D4.2 | Preserve exact birth identity and durable cleanup state | 8 | PID reuse, empty census and interrupted cleanup cannot authorize unsafe signals.
D4.3 | Bind capacity release to proven disappearance | 7 | Unknown cleanup remains held; proven cleanup releases exactly its hold.

D5 | Integrate native-turn effect claims and reconciliation | 3 | 8 | An uncertain native invocation cannot be repeated under a new request identity | D4 | Claim precedes invocation; lost reply remains held; exact retained proof settles without provider retry | O agents/effect_ledger.py, gateway.py, native_terminal_proof.py, owner_runtime.py; kernel/operations.py
D5.1 | Bind native launch/resume to a durable effect claim | 8 | Crash before/after invocation preserves one logical effect.
D5.2 | Validate retained terminal proof and resolver authority | 8 | Foreign, changed or incomplete proof cannot settle the hold.
D5.3 | Exercise cold reconciliation without provider retry | 7 | Provider-call counter remains unchanged during successful reconciliation.

D6 | Integrate runner effect claims and reconciliation | 3 | 8 | Runner restart or lost acknowledgement cannot duplicate the claimed process effect | D4 | Runner claim, restart and reconciliation preserve identity across client/server boundaries | O fleet/runner/{effect_ledger,runner,server,store}.py; execution_operations.py
D6.1 | Bind runner requests and authenticated actor to ledger identity | 7 | Changed payload or foreign actor cannot reuse the claim.
D6.2 | Record start before spawn and retain uncertain results | 8 | Spawn-boundary crash tests produce one effect and a durable unknown when needed.
D6.3 | Reconcile retained runner proof | 8 | Restart settles the original effect or keeps it held; it never silently resubmits.

D7 | Run cross-path fault and cold-recovery acceptance | 2 | 8 | Effect identity, custody, proof and capacity must agree after every tested interruption | D2, D5, D6 | Crash-before/after, lost reply, stale generation and capture-before-cleanup cases pass together | OT custody, retained-start, reconciliation, receipt-lineage tests; new cross-path fixtures
D7.1 | Combine native and runner interruption scenarios | 6 | Each scenario records the exact interruption boundary and expected retained state.
D7.2 | Assert identity, no-repeat and hold-release properties | 8 | Call counts, effect IDs and capacity evidence agree after cold recovery.
D7.3 | Package the accepted O3 contract for A | 5 | Results identify the exact base and bounded effect coverage.
```

**E — 12 days; manager difficulty 7/10.** Briefs, worker tools and status simplification must converge on the same governing policy without creating another control path.

The existing manager-guide, readiness and resume tests are component evidence. A cold-worker diagnosis → ask → recovery → submission journey remains the acceptance bar. [O6 proof gap](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/astra-breakdown/luna/r-tests.md:10).

```text
E1 | Define the reduced effective-brief contract | 2 | 5 | — | none | One brief identifies pinned policy, role/model constraints, provenance and task-sized obligations | O herzchen/packs, otto/packs, portfolio/operating_brief.py, role_context.py
E1.1 | Inventory conflicting or duplicated guidance | 3 | Each retained rule has one intended source.
E1.2 | Define brief fields and provenance references | 5 | Cold-reader fixture can identify governing policy and task scope.
E1.3 | Prepare reduced PACKS templates | 4 | No domain-kit expansion or independent policy authority is introduced.

E2 | Prepare bounded SLIM simplification and caller audit | 3 | 6 | — | E1 | Pure view/guidance simplifications are checked; later deletions have a caller inventory | O portfolio status/context/show/intake areas; SLIM caller inventory
E2.1 | Separate pure projections from authority-bearing paths | 6 | Each proposed deletion/replacement names its actual callers and source of truth.
E2.2 | Prepare isolated simplifications against contract fixtures | 5 | Output retains unknowns, generation and as-of information.
E2.3 | Hand live-route changes to F/E4 and retirement inventory to G | 5 | No second authoritative status path lands prematurely.

E3 | Prepare TP3/TP6 focused feedback and refusals | 2 | 6 | — | E1, A2 | Feedback narrows appropriately and refusals give an actionable next step | O fleet/landing.py, tools/facade.py; isolated helpers/tests under A lease
E3.1 | Harvest focused-check selection changes | 6 | Unknown pytest options and committed test changes retain safe selection behavior.
E3.2 | Harvest actionable refusal messages | 4 | Refusals name the blocked operation and valid next action.
E3.3 | Check feedback/qualification separation | 6 | A successful focused check cannot mark the candidate qualified.

E4 | Integrate effective briefs and capable worker tools | 3 | 7 | Brief, CLI and tool surfaces cannot grant authority beyond the same current mandate | E2, E3, F7 | Worker can diagnose, ask, resume and submit through the accepted control boundary | O agents adapters/gateway, hostctl skills/service, portfolio role context; facade under A lease
E4.1 | Bind effective brief to the accepted policy revision | 7 | Stale or conflicting policy cannot silently supply broader permissions.
E4.2 | Wire diagnostic execution, ask and resume-with-log | 6 | Each documented operation reaches F's existing authorized route.
E4.3 | Integrate TP feedback and submission-only completion | 6 | Tools retain A2's no-landing property and F's qualification distinction.

E5 | Run the cold-worker journey and remove proven duplicate guidance | 2 | 6 | — | E4 | New worker diagnoses, asks, recovers and submits using only its delivered brief/tools | OT guide/readiness/resume tests; real-worker scenario; pack guidance
E5.1 | Run the complete cold-worker scenario | 6 | Evidence shows actual diagnostic execution, answer delivery and resumed submission.
E5.2 | Verify policy provenance and task-sized turn behavior | 5 | Worker identifies governing constraints without hidden conversational context.
E5.3 | Remove only guidance proved redundant by the journey | 4 | The reduced brief still passes the same scenario.
```

**F — 22 days; manager difficulty 8/10.** This is the rigorous authority boundary: authorization, spend, effect claims and manager replacement must compose before any launch.

Existing mandate, capacity and accounting tests do not prove all-role enforcement. Current accounting explicitly returns “unavailable” when required pricing facts are missing; that must not become zero-cost admission. [Accounting behavior](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/usage/accounting.py:154).

```text
F1 | Port mandate and task authorization | 3 | 7 | Delegation cannot expand scope or use a stale policy/task revision | B9, A6 | Every role's requests are checked against authenticated, current mandate and reserved decisions | O work/admission.py, assignments.py, hostctl service routes; mandate tests
F1.1 | Map pilot mandate fields to Otto authority records | 5 | Every enforced field has one authenticated source.
F1.2 | Implement revision, scope and reserved-effect checks | 7 | Stale/foreign/out-of-scope requests refuse before assignments or effects.
F1.3 | Exercise CLI and tool authorization parity | 7 | Equivalent requests receive equivalent decisions through both surfaces.

F2 | Implement durable spend and capacity reservation | 3 | 8 | Concurrent or uncertain starts cannot spend or release the same allowance twice | B9, A6 | Total/away/model/capacity limits refuse before launch and uncertain charges remain reserved | O usage/{accounting,contract}.py, kernel/limits.py, fleet/capacity.py; reservation seam
F2.1 | Define conservative adapter bounds and unknown-price behavior | 6 | Unbounded/unpriced adapters refuse a hard-cap request.
F2.2 | Implement atomic reserve, settle and retained-unknown transitions | 8 | Competing last-slot/last-budget starts admit at most the affordable set.
F2.3 | Test crash/retry and all paid role classes | 8 | Restart preserves reservations; reviewer/supervisor/manager costs are included.

F3 | Enforce the all-role launch gateway | 3 | 8 | No supported route may invoke an adapter before authorization, reservation and effect claim | F1, F2 | Route census and fault tests prove enforcement for every role | O agents/gateway.py, adapters, hostctl/service.py/serve.py; dispatch/admission wiring
F3.1 | Enumerate supported launch/resume entry points | 5 | Every route maps to one gateway operation.
F3.2 | Compose authorization, reservation and D's claim boundary | 8 | Each injected refusal leaves adapter invocation count at zero.
F3.3 | Remove superseded admission bypasses | 7 | Direct/legacy route probes cannot evade the accepted boundary.

F4 | Port receipts and candidate projections | 2 | 6 | — | F3 | Otto tools retain input/execution/candidate/outcome identity and rebuild truthful views | O evidence, adapters/receipt.py, file_ipc_receipts.py, landing receipt seams
F4.1 | Map thin receipts to Otto operation/evidence records | 5 | Round-trip fixtures preserve unknown outcomes and lineage.
F4.2 | Instrument accepted tool boundaries | 6 | Interrupted operations retain intent and exact candidate references.
F4.3 | Rebuild status/handoff views from receipts | 5 | Cold projection agrees with recorded execution without prose status edits.

F5 | Port durable messaging, wake and replacement routing | 2 | 7 | A stale manager generation cannot consume or resolve the replacement's message work | F4 | Ask/reply and replacement recover from durable state without duplicate logical delivery | O portfolio/{inbox,help_delivery,issue_loop}.py, attention.py, routing seams
F5.1 | Map message identity, generation and resolution to Otto records | 5 | Invalid recipient/assignment combinations refuse.
F5.2 | Implement durable wake/reply/resume transitions | 7 | Death between delivery and acknowledgement preserves one logical conversation.
F5.3 | Exercise generation replacement and cold recovery | 7 | Old manager actions refuse; replacement resumes the correct pending question.

F6 | Port exits and independent liveness monitoring | 2 | 6 | — | F4 | Declared exits and host evidence distinguish dead, late and unknown sessions | O hostctl/supervision.py/serve.py seams, due scheduling, exit records
F6.1 | Wire declared exits and named waits | 5 | Each supported role persists a validated exit or wait.
F6.2 | Port monitor classifications and deduplication | 6 | Seeded absence, death, lateness and unknown evidence produce the intended observations.
F6.3 | Prove monitor continuity across manager death | 6 | Independent scheduling continues and does not infer death from missing visibility alone.

F7 | Port supervisor and consolidate authoritative projections | 2 | 6 | — | F5, F6 | One message/status path supports supervision and cold-session handoff | O supervision, portfolio/status.py, observability_views.py, completion_gate.py
F7.1 | Port evidence sweep and exception routing | 5 | Supervisor nudges the responsible manager and lacks project dispatch/landing authority.
F7.2 | Replace duplicate polling/delivery/projection routes | 6 | Caller audit shows one authoritative path with compatible remaining callers.
F7.3 | Replay the pilot's manager-death incident through Otto | 6 | Replacement reconstructs work, answers and resumes from durable evidence.

F8 | Port manager-owned batch integration and publication reconciliation | 3 | 7 | Qualification and publication stay bound to the exact selected candidate and authorized operation | F4, B7 | Regressions are attributable; changed evidence refuses; unknown publication reconciles | O landing/facade, hostctl/fleet_landing.py/product_service.py; rewritten BOOTLAND scenarios
F8.1 | Port ordered batch construction and attribution | 5 | Seeded failure identifies the introducing slice.
F8.2 | Bind qualification to source/artifact tuple and required scenarios | 7 | Changed, skipped or missing evidence cannot authorize delivery.
F8.3 | Port explicit landing/publication and lost-reply recovery | 7 | Remote-result reconciliation settles the original operation without blind repeat.

F9 | Qualify the exact integrated Otto candidate | 2 | 7 | Installed real-worker evidence must describe A7's candidate, including interruption/refusal behavior | A7, F7 | Real installed journey, rewritten DISTURB/REALSTAGE3 cases and incident replay pass | OT installed journeys; portable acceptance driver; exact-candidate evidence
F9.1 | Install A7's frozen candidate and verify its identity | 5 | Delivered client/service/artifact identities match the candidate record.
F9.2 | Run real-worker work, ask/recovery, batch qualification and explicit landing | 7 | Successful user path has complete linked receipts.
F9.3 | Run restart/refusal and negative qualification scenarios | 7 | Seeded failures refuse; fake staging or baseline parity cannot satisfy the gate.
```

The existing `perch` harness has useful restart/refusal and staged lifecycle scenarios, but expressly supports fake workers. Preserve its useful assertions without treating fake staging as the final real-worker journey. [Harness contract](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/ops/bootstrap/perch.sh:1).

**G — 24 days; manager difficulty 8/10, conditional on its design spike.** The hard invariant is exclusive authority across disconnection, restart and transfer. Git history alone cannot establish it.

G starts with a bounded spike because an unresolved fencing design would make the implementation a 9–10. The final state must reconstruct assignments, receipts, messages and budget holds without the old Store or PID namespace. [G1–G3 acceptance](/home/user/repo/astrid-install/retro/evidence/otto-roadmap/astra-roadmap.md:97).

```text
G1 | Spike git authority, fencing and failure semantics | 2 | 8 | At most one writer epoch may authorize effects; Git authorship alone grants no authority | F9; post-pilot git decision | Competing/disconnected writer traces have an implementable fail-closed design | O kernel/store.py/operations.py; authority/store contract fixtures
G1.1 | Map authoritative records and rebuildable projections | 5 | Every F/D record has one authoritative representation.
G1.2 | Specify authenticated expected-head updates and effect-boundary fencing | 8 | Competing writers, stale epochs and lost acknowledgements have safe outcomes.
G1.3 | Demonstrate the failure model before implementation | 8 | Adversarial prototype admits one writer and blocks disconnected/stale effect starts; otherwise rescope G.

G2 | Implement the authoritative git writer and fences | 3 | 8 | A stale or losing writer cannot authorize effects even if it retains a local checkout | G1 | CAS, authentication, epoch and disconnect tests pass at the actual write/effect boundary | O kernel store/operations; new git-store backend; adapter fencing seams
G2.1 | Implement immutable record append and expected-head commit | 7 | Conflicting writes cannot both become accepted authority.
G2.2 | Bind authenticated writer epoch to effect authorization | 8 | Stale writer and forged owner-record attempts refuse.
G2.3 | Exercise crash, partition and lost-ack recovery | 8 | Recovery reads accepted history; it cannot create duplicate authority.

G3 | Implement record replay and rebuildable local projections | 3 | 7 | Rebuild cannot lose unresolved effects, messages, assignments or budget holds | G2 | Empty local database rebuilds the same authoritative state and digest | O kernel/store.py, operations.py; receipt/message/reservation projections
G3.1 | Implement deterministic replay and schema validation | 6 | Record order/version fixtures rebuild consistently or refuse explicitly.
G3.2 | Preserve unknown states and retained holds | 7 | Fresh rebuild cannot free an unresolved reservation or convert unknown into success.
G3.3 | Compare reconstructed state and digest | 7 | Source and rebuilt identities, totals and unresolved sets match.

G4 | Implement cloud host and fresh-session recovery adapter | 3 | 7 | A new cloud session must not confuse local process identity with authority to repeat an effect | G2 | Fresh host recovers work without old machine Store/PID assumptions | O adapters/host.py, fleet/hosts contracts/adapters, runner store/server, execution_host.py
G4.1 | Separate portable execution identity from local process evidence | 6 | Contract fixtures make unavailable local evidence explicit.
G4.2 | Restore assignments, messages, receipts and holds on a fresh host | 7 | Recovery uses authoritative records and preserves existing effect IDs.
G4.3 | Exercise host loss and stale-session behavior | 7 | Old session cannot act; new session reconciles or remains held.

G5 | Export retained state and prove readback | 3 | 7 | Transfer inventory accounts for every active identity and unresolved obligation exactly once | G3, G4 | Dry-run export/readback matches identities, balances, unknowns and history references | New exporter/readback tools; OPS retained-project/effect inventory
G5.1 | Inventory retained projects, runs, messages, effects and holds | 5 | No live entity is omitted from the manifest.
G5.2 | Export and independently read back records | 7 | Counts, identity sets, balances and digests reconcile.
G5.3 | Exercise malformed/missing/duplicated record refusal | 6 | Export acceptance fails before authority transfer on any discrepancy.

G6 | Transfer authority once and validate portable startup | 3 | 8 | Old and new writers must never both act; rollback cannot resurrect a revoked epoch | G5 | Rehearsed transfer, interrupted transfer and permitted rollback obey one authority boundary | Store/host composition; new transfer tooling; rewritten BOOTCFG startup
G6.1 | Define drain, freeze, transfer and rollback checkpoints | 7 | Each checkpoint names the sole permitted writer and retained unknowns.
G6.2 | Exercise transfer failures at each checkpoint | 8 | Old/new concurrent attempts never both authorize an effect.
G6.3 | Perform the authorized transfer and verify portable restart | 8 | Fresh startup proves the active epoch and no required launchd/local-Store dependency.

G7 | Qualify the shipped cloud journey before retirement | 3 | 7 | Fresh-session evidence must prove the transferred authority and exact delivered candidate | G6 | Real work survives interruption, resumes safely and reproduces its digest | Cloud installed journey; transfer/recovery/receipt evidence
G7.1 | Start from a fresh cloud environment | 6 | No old local database or PID namespace is available to the test.
G7.2 | Execute, interrupt, recover and deliver verified work | 7 | Effect IDs and holds remain consistent; no duplicate invocation occurs.
G7.3 | Rebuild projections and reproduce the final digest | 7 | Rebuilt result matches authoritative history and delivered candidate.

G8 | Retire audited superseded core routes | 2 | 6 | — | G7, E2 | Obsolete core routes are removed; required callers and historical readers still work | O audited controllers/adapters/projections; caller map
G8.1 | Confirm callers and replacement coverage for each deletion slice | 5 | Every removed route has no required caller or a checked replacement.
G8.2 | Delete bounded slices and run affected compatibility checks | 6 | No retired path remains required by startup, recovery or historical evidence reads.
G8.3 | Update the final candidate identity | 4 | Earlier qualification is not reused for the changed candidate.

G9 | Retire old ops paths and qualify the final candidate | 2 | 6 | — | G8 | Old launch/control paths are inactive; evidence remains readable; final cloud journey passes | OPS old controllers/runbooks; portable startup; final acceptance evidence
G9.1 | Remove audited obsolete ops entry points and update instructions | 5 | Entry-point/caller audit finds one supported operational path.
G9.2 | Check historical evidence compatibility | 5 | Retained projects and receipts remain inspectable.
G9.3 | Re-run the shipped journey on the final post-deletion candidate | 6 | Final evidence names the exact delivered hashes and passes recovery/digest checks.
```

**Totals and schedule interpretation**

| Scope | Engineer-days |
|---|---:|
| A | 14 |
| B | 18 |
| C | 29 |
| D | 18 |
| E | 12 |
| F — same manager as B | 22 |
| G — conditional later stage | 24 |
| **Through qualified Otto port** | **113** |
| **Entire roadmap** | **137** |

The dependency model gives **50 working days through the Otto port**, then **21 more through G**, despite G containing 24 engineer-days because projections and cloud-adapter work overlap.

Thus:

- **Critical-path effort:** 71 engineer-days on the longest dependency chain.
- **Modeled elapsed time:** 71 working days, about 14.2 five-day weeks.
- **Practical calendar commitment:** **15–17 weeks**, with runner-access delay added separately.
- **Staffing:** six executor slots at peak, five initial manager responsibilities; B continues as F, and G starts later. Idle stream capacity is reassigned rather than held for the entire roadmap.

Use **137 as the baseline and roughly 150 as the initial effort envelope**. Unknown updater-base defects or a failed git-authority spike require a revised estimate rather than hiding work inside a three-day task.

Saved focused Agent and Runtime checks took **19.46 seconds** and **13.45 seconds** respectively; those are useful feedback examples, not measurements of W1–W6 acceptance. The Windows driver’s timeout ceilings likewise are not observed durations. Qualification time belongs at batch milestones, not repeated in full for every small task. [Agent result](/home/user/repo/astrid-install/runs/UPD-EL-X3-F2-review/tests.txt:1), [Runtime result](/home/user/repo/astrid-install/runs/UPD-EL-X3-F2-review/runtime.txt:1).

**Where I disagree with the tentative takes**

1. **Five managers can start, but five unrestricted implementation streams cannot.** B can build receipts and E can prepare briefs immediately; D can resolve its contract. D’s integrated work waits for O2, and E’s live worker wiring waits for O4/O5. Starting those shared-file edits immediately would buy branch divergence.

2. **Keep A, D and E as separate managers, with A owning integration.** Combining all three under one manager concentrates both technical judgement and the merge queue. Their exclusive work is substantial enough to manage independently. The single-owner leases handle their overlap.

3. **Explicitly pull bounded O2/O3 repair ahead of P3.** My earlier dependency table placed O2 after P3. These repairs do not require the pilot’s final interface. Keeping that old edge adds about **18 working days** to this schedule. O4/O5 and live O6 still wait for the appropriate pilot/control gates.

4. **B and F should be the same manager.** The principal handoff is from observed pilot behavior to a production contract. Continuity matters more than creating another management boundary. Executors can change.

5. **No separate full-time qualification manager is needed.** Named accountability is needed: C for product acceptance, B for control judgement, F for Otto acceptance, A for the candidate and integration queue. Qualification must use the candidate A already built; merging afterward would invalidate it.

6. **The pilot week is not the duration of all remaining product engineering.** Keep the minimum observation period and real release acceptance as separate gates. Early W4/W1 work is baseline evidence.

7. **G should have no implementation staffing before the pilot result and qualified port.** Its estimate remains in the roadmap, but its first assignment is a fencing spike. A local authoritative service with git as a mirror is a possible revised decision; it is not completion of the proposed G1.

8. **The model mapping is a useful default, not the acceptance mechanism.** Use the proposed bands for bounded assignments, then escalate based on the named invariant and failures. None of these tasks should be handed over at difficulty 9–10; G1 and D1 resolve uncertainty first.

**Highest-risk tasks and the first de-risking step**

| Tasks | Specific risk | De-risk first |
|---|---|---|
| **A5, F1, F3, E4** | Caller, policy or tool composition accidentally grants broader authority. | Build a route/authority matrix and negative tests for foreign principal, stale revision and reserved action before wiring composition. |
| **B3, F5** | Replacement manager or duplicate wake resolves the wrong question. | Replay death between write, delivery and acknowledgement with two manager generations; assert message identity and one logical resolution. |
| **B7, D2, C13, F8, F9** | Evidence for one assignment/candidate authorizes another, or lost publication is repeated. | Mutate one SHA/hash/assignment at a time; drop the publication reply; require refusal or reconciliation against the original operation. |
| **D1, D3, D4** | Process recovery loses custody, signals reused identity or releases an uncertain hold. | Resolve the identity/state table, then inject PID reuse, birth gaps, empty census and crashes at spawn/cleanup boundaries. |
| **D5, D6, D7** | Unknown launch becomes duplicate execution during recovery. | Count actual adapter/spawn calls across crashes before and after invocation and lost replies; require one effect ID and proof-based settlement. |
| **F2** | Concurrent starts overspend, or an unknown charge is refunded too early. | Race two starts for the last budget/capacity reservation; crash after reserving and after invoking; rebuild without releasing uncertainty. |
| **C8** | Verification rolls back for old damage or compares different operation/version observations. | Write the complete before/after policy table and test it against a fault-injected updater before adding the live verification calls. |
| **C11** | Failed rollback destroys recovery assets or user changes. | Construct the broken rollback target and post-backup edits first; crash at every durable transition and verify both survive. |
| **G1, G2** | Git CAS prevents conflicting commits but fails to prevent two writers authorizing effects. | Demonstrate fencing at the effect boundary with disconnected and stale writers. A commit-history demonstration alone fails the spike. |
| **G3, G4, G7** | Fresh cloud recovery drops unknowns or recreates work because local process evidence is unavailable. | Recover from an empty environment containing only authoritative git history; compare IDs, balances, messages, holds and invocation counts. |
| **G5, G6** | Transfer loses obligations or rollback revives the old writer. | Complete independent export/readback first, then rehearse every transfer interruption with competing old/new writer attempts. |

Windows access remains the first operational risk to retire. **G’s effect-boundary fencing is the largest architectural uncertainty; D’s reconciliation and C’s updater recovery are the largest implementation correctness risks.**