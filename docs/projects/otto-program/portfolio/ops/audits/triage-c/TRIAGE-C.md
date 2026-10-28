Reviewed all **12 landing audits and 4 strategy audits**, with the final source snapshot pinned to **`canon/main` `97f5f9702c9efbc6ccdc62c1820804590aea9b34`**. No files changed, tests ran, Otto commands executed, services started, or prohibited directories were read.

Three status corrections matter: **OWNERCOMPLETION landed in `b635c93`; FACADEFD in `e56707e`; CTLRACE in `97f5f97`**. I checked their source changes. FACADEFD fixes eager socket binding; it does not establish complete SESSIONFD teardown.

“Confirmed” below means source-verified behavior with an identified practical consequence, not an executed reproduction. Blocker judgments are recommendations for the orchestrator. Historical landed rows are not counted as outstanding duplicate fixes merely because their status still says “not started.”

**1. Summary table**

Stages: **2 Dispatches; 3 Works; 4 Lands; 5 Manages; 6 Dogfood; 7 CUTOVER**.

| audit | finding | verdict | stage | blocks CUTOVER? | row |
|---|---|---|---|---|---|
| COMPLETECITE | Accepted list/labelled hashes are persisted in a form downstream readers reject | CONFIRMED | 2, 5 | Yes | CITECAN |
| FAILCLOSED | 1. Orchestrated creation substitutes owner for absent operator | CONFIRMED | 6, 7 | Yes | OPPRE |
| FAILCLOSED | 2. Create-and-open consumes its key before missing-operator failure | CONFIRMED | 6, 7 | Yes | OPPRE |
| KILLFENCE | 1. Parser’s null fields break ordinary read/recover/resume | CONFIRMED | 2, 5 | Yes | CLIARGS |
| KILLFENCE | 2. General UNKNOWN recovery lacks public digest/reason inputs and readback | BELONGS TO EFFECTS | 5 | Conditional: required if this recovery is in the release journey; otherwise keep UNKNOWN held | EF2, EF5 |
| KILLFENCE | 3. Required real-owner second-project proof is absent | DUPLICATE of ACTIVATEWHILE’s behavioral obligation and PERCH2C’s negative evidence | 2, 5 | Yes unless the quiescent-activation restriction is approved | ACTIVATEWHILE, PERCH2C |
| LABCAPTURE | 1. Earlier occurrence’s capture authorizes later landed-lab cleanup | CONFIRMED | 3, 4 | Yes | LABPIN |
| LABCAPTURE | 2. Marker/HEAD validation precedes deletion lock | PLAUSIBLE impact; race exists, but `remove` preserves a Git ref for unmerged HEAD | 4 | Yes, fold into the same custody fix | LABPIN |
| LABCAPTURE | 3. Claude-shaped capture predicate rejects Codex results | DUPLICATE of CODEXOWNER’s required captured journey and lab cleanup | 3, after | No if Codex worker dispatch remains disabled | CODEXOWNER |
| LABCAPTURE | 4. Failed cleanup has no live retry; response is discarded | CONFIRMED | 4 | No; restart currently supplies retry | LABRETRY |
| LABCAPTURE | 5. Perch examines the wrong lab root after teardown | DUPLICATE | 2, 4 | Yes | PERCH2C |
| LIMITFD | Named shared-LimitService change | NOT A DEFECT; implemented by `9b33101` | 2 | No | — |
| LIMITFD | Remaining eager assessment-facade socket allocation | ALREADY FIXED by `874553c`, landed `e56707e` | 2, 3 | No remaining blocker for this mechanism | FACADEFD |
| LIVENESS | 1. Installed-wrapper exit mapping reverses success/failure handling | BELONGS TO SLIM; confirmed on the legacy composition | 7 | No if BOOTCFG selects and proves the product composition | SL6, BOOTCFG |
| LIVENESS | 2. Native/file clients omit published-state preflight | BELONGS TO SLIM; confirmed | 5, 6 | No additional blocker; transfer must verify actual client outcomes | SL6 |
| LIVENESS | 3. Timeout/protocol error is labelled owner death | BELONGS TO SLIM; confirmed | 5 | No; never infer replay permission from it | SL6 |
| LIVENESS | 4. Restart guidance does not quote homes containing spaces | BELONGS TO SLIM; confirmed | 7 | No if the release procedure uses a verified command | SL6, SL7 |
| LIVENESS | 5. Drain test substitutes authorization and never enters a pending wait | DUPLICATE of TESTPATCH; extend DRAINSETTLE’s release evidence | 5 | Required release coverage blocks; broad reconstruction does not | TESTPATCH, DRAINSETTLE |
| MANUALDISPATCH | Answer continuation records two dispatch events for one launch | CONFIRMED | 5 | No demonstrated duplicate provider effect | ASKDISP |
| MGR | 1. Both route CLI forms send irrelevant null fields and refuse | CONFIRMED | 5 | Yes | CLIARGS |
| MGR | 2. Worker ask routes to orchestrator instead of project manager | CONFIRMED | 5, 6 | Yes | MGRASK |
| MGR | 3. Promised manager MCP tools are absent | CONFIRMED delivery gap | 5 | Scope decision; recommend deferral with a proved CLI journey | MGRMCP |
| MGR | 4. Authenticated effective-context returns identity without composed brief | BELONGS TO SLIM | 5, 6 | No additional blocker if delivered instructions are verified | SL1, SL6 |
| ORPHANWORKER | 1. Rejected contender’s close can signal incumbent worker records | DUPLICATE of OWNERCLAIM’s custody invariant; production trigger remains PLAUSIBLE | 2 | Covered by existing blocker | OWNERCLAIM |
| ORPHANWORKER | 2. Already-dead owner’s staging down skips separately grouped workers | BELONGS TO PROCLIFE; confirmed | 2, 3 | Yes: pull forward the narrow stop-path correction | PL3, PL6 |
| ORPHANWORKER | 3. Startup sweeps constructor-time records without reloading after claim | DUPLICATE of OWNERCLAIM; production interleaving remains PLAUSIBLE | 2 | Covered by existing blocker | OWNERCLAIM |
| ORPHANWORKER | 4. Cleanup/refusal diagnostics omit identified workers and outcomes | BELONGS TO PROCLIFE | 2, 3 | No independent blocker | PL5, PL6 |
| PACKPARITY | 1. Relocated fixture compares a root-dependent hash with the old root’s hash | CONFIRMED test defect | 4 | Yes for trustworthy provenance qualification | PARITYFIX |
| PACKPARITY | 2. Product metadata remains in Herzchen; scan misses ordinary literals | BELONGS TO PACKS for metadata ownership; no runtime failure established | after | No | PK3 scope addition |
| PACKPARITY | 3. Fixture commits live implementation; early failure escapes cleanup | CONFIRMED test defect | 4 | Yes, same qualification fix | PARITYFIX |
| PROJECTPIN | Adding unrelated task changes the setup’s task roster and blocks launches | CONFIRMED | 2, 6 | Yes | ROSTERPIN |
| READYPIN | Exact predecessor/content proof on both named paths | ALREADY FIXED by `1b1159d`, landed `eb9b6cd` | 2 | No | — |
| READYPIN | Missing authentic changed-predecessor regression | NOT A DEFECT in current product; useful coverage strengthening | 2 | No independent blocker | Add to existing readiness coverage |
| INTEGRATE-THROUGHPUT | TP1 baseline uses changing input glob; interrupted pairing is fragile | BELONGS TO THROUGHPUT; baseline defect confirmed, interrupted-run impact unobserved | after | No | TP1; INTEG-THROUGHPUT-1 |
| INTEGRATE-THROUGHPUT | TP3 misrecognizes commands and incompletely selects affected tests | BELONGS TO THROUGHPUT; source defects confirmed, failing fixtures required before fix | 3 | No | TP3; INTEG-THROUGHPUT-2 |
| INTEGRATE-THROUGHPUT | TP3 helper tests do not prove service integration | BELONGS TO THROUGHPUT | 3, 4 | No | TP3 |
| INTEGRATE-THROUGHPUT | TP3 leaves done on the full admitted check | NOT A DEFECT; preserve this boundary | 4 | No | — |
| INTEGRATE-THROUGHPUT | TP6 adds next_action but existing test expects the old exact dictionary | BELONGS TO THROUGHPUT; definite source-established test mismatch | 3 | No | TP6; INTEG-THROUGHPUT-3 |
| INTEGRATE-THROUGHPUT | MCP listing discards refusal guidance | DUPLICATE of TRIAGE-B’s SLIM assignment | 3 | No | SL6; prerequisite to TP6 integration |
| INTEGRATE-THROUGHPUT | TP5 prose test does not establish measurements; ledger omits itself | BELONGS TO THROUGHPUT | after | No | Reopen TP5 |
| INTEGRATE-THROUGHPUT | Cache, warm renderer and measured journey absent | BELONGS TO THROUGHPUT; project goal incomplete, limitations disclosed | after | No | TP2, TP4, TP5 |
| INTEGRATE-ASTRIDFLEET | Caller classification is reversed | BELONGS TO ASTRIDFLEET; confirmed | after | No | INTEG-ASTRIDFLEET-1 |
| INTEGRATE-ASTRIDFLEET | AFUX attributes owner-minted reference to a brief that does not say it | BELONGS TO ASTRIDFLEET; confirmed editorial defect | after | No | INTEG-ASTRIDFLEET-1 |
| INTEGRATE-ASTRIDFLEET | Source checkout/revision and EFFECTS comparison date absent | BELONGS TO ASTRIDFLEET | after | No | INTEG-ASTRIDFLEET-1 |
| INTEGRATE-ASTRIDFLEET | Heading checks alone cannot satisfy current gate | CONFIRMED integration constraint | 4 | No | INTEG-ASTRIDFLEET-1 |
| INTEGRATE-ASTRIDFLEET | Generic project packages collide if imported wholesale | CONFIRMED integration constraint | 4 | No | All integration rows exclude generic `.project/` |
| INTEGRATE-HARNESS3 | H35 contributor map | NOT A DEFECT; accurate documentation | after | No | INTEG-HARNESS3-1 |
| INTEGRATE-HARNESS3 | Project record says H35 needed no gate | BELONGS TO HARNESS3; confirmed record defect | 4 | No | INTEG-HARNESS3-1 |
| INTEGRATE-HARNESS3 | Rounded, self-reported UX timings | NOT A DEFECT as dishonesty; insufficient performance evidence | after | No | Preserve limitation |
| INTEGRATE-HARNESS3 | Third CLI and cleanup absent; H31–H34/H36 blocked | BELONGS TO HARNESS3; project goal incomplete | after | No | H31–H34, H36 |
| PATH-TO-CUTOVER | OWNERCOMPLETION still open | ALREADY FIXED by `ec7c1b9`, landed `b635c93` | 2 | No | Reconcile status |
| PATH-TO-CUTOVER | FACADEFD still open | ALREADY FIXED for eager socket binding by `e56707e`; retain SESSIONFD remainder | 2 | No for fixed mechanism | SESSIONFD |
| PATH-TO-CUTOVER | CTLRACE still open | ALREADY FIXED by `3581821`, landed `97f5f97` | 2 | No | Reconcile status |
| PATH-TO-CUTOVER | Real stages 5/6 absent; wrapper forces fake | CONFIRMED | 5, 6 | Yes | REALSTAGE56 |
| PATH-TO-CUTOVER | Six-follow-up wording, incomplete snapshot/readback obligations | CONFIRMED procedural gap; no actual omission observed | 7 | Yes | XFERMAP |
| PATH-TO-CUTOVER | Old in-flight work, client bindings and deletion boundary insufficiently specified | CONFIRMED procedural gap; live inventory remains unperformed | 7 | Yes | XFERBOUND |
| PATH-TO-CUTOVER | Show silently truncates | NOT A DEFECT as stated: pagination is returned | 7 | Complete readback still blocks | XFERMAP |
| PATH-TO-CUTOVER | Bootstrap SHA, landing proof, file authority, install/restart and relay risks | DUPLICATE of completed wave-2 triage | 4–7 | Existing blocker recommendations remain | BOOTLAND, LANDPROOF, FILEAUTH, BOOTCFG, RELAYSAFE |

Test-quality observations are incorporated into the owning acceptance work below. A source-shape assertion, patched product method, or passing historical log is not substituted for the real-path regression.

**2. Drafted program rows**

All source citations in these rows refer to the final canonical snapshot. Tests are prospective. Use real product methods, person/model stand-ins only, synchronization on state, and external fault injection rather than replacing the product method being proved.

The first ten rows are recommended CUTOVER blockers. Integration rows are in section 6.

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| LABPIN | xhard | 0.75 | LABCAPTURE | **A lab is removed only for its exact captured landing occurrence.**<br>Evidence: `src/otto/hostctl/product_service.py:416`, `src/herzchen/fleet/labs.py:375`, `:399`, `:423`; LABCAPTURE 1–2.<br>• Bind the marker to the owner occurrence, assignment generation and commit. • Check capture, marker, HEAD and retained ref under one exclusive lab lock through removal, including partial-removal recovery. • Reuse existing landing and Due records. | Retain captured turn A and uncaptured landed turn B for the same task: startup must retain B until B’s capture. Coordinate a real writer and sweep so HEAD changes before deletion acquires custody: replacement work must remain available. Both expose the current gap; retain the existing dirty-work and Git-ref protections. | Invariant: Cleanup authority applies to one captured occurrence and one lab incarnation. Plausible mistake: Matching only task identity or validating before acquiring the deletion lock. Surfaces: A later worker loses its lab before its result is captured. | fleet | not started |
| CITECAN | normal | 0.25 | COMPLETECITE | **Every accepted completion input produces the canonical stored evidence-hash form.**<br>Evidence: `src/herzchen/domains/work/assignments.py:732`, `:769`, `src/otto/portfolio/owner_bootstrap.py:1299`, `:1319`, `src/otto/portfolio/manager_journey_command.py:595`; COMPLETECITE 1.<br>• Persist the already verified ref-to-digest mapping in canonical string-key form. • Preserve the original request payload for replay matching. | Complete equivalent real tasks with list, labelled-map and canonical-map inputs, then read historical setup and corrective-task coverage. All succeed with the same exact evidence; changed hashes still refuse. Lists/labels currently fail downstream, including the corrective reader’s list exception. | — | model | not started |
| ROSTERPIN | xhard | 0.5 | PROJECTPIN | **Adding an unrelated task preserves an otherwise unchanged operating setup.**<br>Evidence: `src/otto/portfolio/owner_readers.py:51`, `:68`, `src/herzchen/domains/work/batches.py:699`, `src/otto/portfolio/operating_brief.py:223`; PROJECTPIN 1.<br>• Remove the general task roster from setup-content comparison. • Keep exact retained revisions for the content actually adopted, individual task admission and setup acceptance-task validation. | Activate A, add unrelated D through the real project-sheet path, then start admitted A: it reaches the provider, unlike current code. Changes to A’s instructions, adopted mandate or acceptance policy still refuse. Include an unadmitted D that cannot launch. | Invariant: A roster change cannot weaken the content and authority adopted for an existing task. Plausible mistake: Ignoring task or policy changes along with roster membership. Surfaces: Planning blocks every launch, or changed work inherits old authorization. | dispatch | not started |
| CLIARGS | normal | 0.5 | MGR, KILLFENCE | **Maintained manager commands send and validate operation-specific arguments.**<br>Evidence: `src/otto/hostctl/manager_client.py:69`, `src/otto/portfolio/manager_journey_client.py:506`, `:538`, `src/otto/portfolio/manager_journey_service.py:366`, `:1568`; MGR 1, KILLFENCE 1.<br>• Suppress absent optional fields and distinguish absent values from an actual recovery request. • Preserve required-field and unknown-field refusal. • Share the correction across route and execution-control. | Drive actual parser → launched client → authenticated service for reroute, retry, read, recover and resume. Valid forms reach their intended effects/readback; omitted required values and foreign schedules refuse. Current valid forms fail because irrelevant null fields are forwarded. | — | dispatch | not started |
| OPPRE | normal | 0.5 | FAILCLOSED | **Missing operator authority refuses project creation before any reservation or receipt.**<br>Evidence: `src/otto/portfolio/herzchen_binding.py:456`, `:534`, `src/otto/portfolio/owner_bootstrap.py:479`, `:534`, `src/herzchen/authoring/sessions.py:768`; FAILCLOSED 1–2.<br>• Resolve the operator before orchestration or authoring reservation. • Reuse that resolved actor in creation callbacks. • Cover pending, template, create-and-open and save/import entrances without adding another authority path. | Through real creation entrances with no operator, require no project, authoring reservation or consumed request receipt. Configure the operator and retry the same key: create exactly once. Current orchestration creates under fallback authority; current create-and-open consumes the key and reports a nonexistent saved project. | — | model | not started |
| MGRASK | xhard | 0.75 | CLIARGS, ASK | **A worker question wakes its current project manager and returns to the exact asker.**<br>Evidence: `src/otto/portfolio/issue_loop.py:736`, `:770`, `:790`, `src/otto/portfolio/owner_issue_loop.py:82`; MGR 2.<br>• Route worker-origin questions to the current manager through retained wakes. • Keep explicit orchestrator escalation. • Preserve asking assignment, generation, occurrence and session through answer delivery. | With real owner assignments for two projects, one worker ask creates one wake for its own manager; routine progress creates none. The manager’s answer resumes the exact asking session once; replay, replacement and foreign-project answers cannot resume another session. Current ask targets the orchestrator. | Invariant: Project judgment reaches the current manager while answers retain exact asking-session custody. Plausible mistake: Routing by project or task alone after a manager/session replacement. Surfaces: The wrong manager answers or the wrong worker resumes. | dispatch | not started |
| PARITYFIX | normal | 0.5 | PACKPARITY | **Pack parity evidence survives checkout relocation and unrelated loader edits.**<br>Evidence: `tests/test_evidence_lifecycle.py:108`, `:126`, `:417`, `:428`, `src/herzchen/packs/authoring.py:684`, `:718`; PACKPARITY 1, 3.<br>• Separate portable recorded vectors from root-bound filesystem admission. • Keep immutable fixture bytes independent of live implementation bytes. • Put all materialization and assertions inside temporary-checkout cleanup. • Preserve independently derived expectations. | Run identical fixture content under two roots with correctly rooted independent provenance; both pass. A comment-only loader change preserves parity. A forced setup/assertion failure leaves no source-checkout files or nested repository. These cases fail under the current fixture; tampered pack bytes still refuse. | — | proof | not started |
| REALSTAGE56 | xhard | 1.0 | REALSTAGE4, MGRASK, CLIARGS, REWORKWIRE, DRAINSETTLE, PROOFDOC | **One real campaign proves management and dogfood, with separate stage-5 and stage-6 verdicts.**<br>Evidence: `ops/bootstrap/perch.sh:803`, `:809`, `ops/bootstrap/canary/project.json:5`; PATH-TO-CUTOVER. External wrapper: `otto-program/ops/stage-run.sh:34`.<br>• Add real mode and missing scenarios. • Exercise ask/answer, failed check and bounded rework, changed-admission refusal, two preactivated projects and safe drain/restart. • Land two genuine program tasks and record cold-client reads/save preview. | Calling real stages 5/6 currently fails before a scenario can run. New tests require each claimed verdict to turn red for a missing manager wake, wrong resumed session, unadmitted launch, missing actual landing or fake-mode evidence. Then run the real campaign on one exact candidate; no product-method patches or elapsed-time pass thresholds. | Invariant: Release evidence describes the shipped owner’s real manager/worker effects on the qualified revision. Plausible mistake: Producing verdicts from harness bookkeeping or silently forcing fake mode. Surfaces: CUTOVER proceeds without a working management journey. | proof | not started |
| XFERMAP | normal | 0.75 | CONV, SAVEPATH | **CUTOVER has a complete, revision-consistent preservation manifest and independent readback.**<br>Evidence: `src/otto/portfolio/show.py:32`, `:61`, `src/otto/portfolio/intake.py:1044`, `:1066`; PATH-TO-CUTOVER; program PLAN §14 and CUTOVER’s six-follow-up wording.<br>• Include all seven follow-ups, program, r4 and every other selected upcoming project. • Map old to new identities and compare tasks, dependencies, criteria, instructions, configuration, notes and document bodies. • Freeze source writes or re-export changed exact revisions. • Reject partial pages and stale snapshots. | Disposable real owners containing over 100 tasks, linked documents and differing revisions produce a complete mapped comparison. Omit the final page, alter one body/dependency, or edit the source after export: the transfer verifier refuses. Current CUTOVER procedure has no such completeness/revision gate. Actual live inventory remains a later authorized owner action. | — | proof | not started |
| XFERBOUND | xhard | 0.75 | XFERMAP, BOOTCFG, OWNERCLAIM, DRAINSETTLE, RECEIPTFENCE, REALSTAGE56 | **The switch preserves unresolved custody and deletion cannot outrun verified operation.**<br>Evidence: `src/otto/hostctl/config.py:33`, `:199`, `src/otto/portfolio/orchestrator_client.py:325`; PATH-TO-CUTOVER and existing CUTOVER steps 4–6.<br>• Inventory and disposition old in-flight/unknown work before admitting corresponding new work. • Inventory every home, client locator and authority binding; reissue bindings and verify owner identity/project scope per client. • Keep exports outside the exact deletion set. • Require destination restart, old-owner stop and client readback before deletion becomes eligible; attach the exact set to CUTOVER’s existing user go. | Disposable old/new installations: unresolved corresponding work prevents new admission; one stale client binding, failed destination restart, missing export or live old process keeps deletion ineligible. The valid sequence enables only the enumerated old paths. Current procedure lacks these executable conditions. No destructive live action is part of this task’s test. | Invariant: Transfer neither replays unresolved effects nor deletes the only preserved copy or a still-used runtime. Plausible mistake: Treating saved plans as migrated custody or one working client as proof that all clients switched. Surfaces: Duplicate effects, stale-owner use or irreversible data loss. | proof | not started |
| LABRETRY | normal | 0.5 | LABPIN | **Pending landed-lab cleanup remains visible and retries on the live owner.**<br>Evidence: `src/otto/agents/owner_runtime.py:1140`, `:1145`, `src/otto/portfolio/execution.py:1447`, `src/otto/hostctl/product_service.py:388`; LABCAPTURE 4.<br>• Retain the cleanup result and retry only removal from captured evidence. • Expose pending/error state until removal succeeds. • Delete unused generic sweep paths after checking callers. | Cause the first real filesystem removal to fail, restore access, and let the same owner process its next cleanup opportunity. Status remains pending until the lab disappears; provider, check, acceptance and completion counts never increase. Current code discards the response and waits for restart. | — | fleet | not started |
| ASKDISP | normal | 0.25 | MANUALDISPATCH | **An answered worker continuation records exactly one dispatch.**<br>Evidence: `src/otto/portfolio/execution.py:2046`, `:1263`, `:1346`, `src/herzchen/domains/work/assignments.py:857`; MANUALDISPATCH 1.<br>• Delete the answer path’s explicit dispatch call. • Let the shared start boundary own the event and its replay key. | Extend the real ask/answer journey: one successful continuation adds one provider call and one dispatch event; replay adds neither. Current code adds two events under distinct keys. | — | dispatch | not started |
| MGRMCP | xhard | 1.0 | CLIARGS, FILEAUTH | **Managers receive the promised project-scoped tools through the existing facade.**<br>Evidence: `src/otto/agents/claude_adapter.py:37`, `src/otto/hostctl/serve.py:479`, `src/otto/hostctl/product_service.py:432`; MGR 3.<br>• Extend existing role-bound grants and schemas for whoami, status, show, save, answer, route and report. • Reuse authenticated owner handlers and tool-minted keys. • Do not add a parallel mutation implementation. | A real manager launch discovers and calls the seven tools for its own project. Worker credentials, foreign projects, stale manager generations and replaced sessions refuse. Current manager launch supplies no manager MCP grant. | Invariant: Tool discovery and mutation authority bind to the same current manager assignment and project. Plausible mistake: Reusing a worker token or authorizing only at discovery. Surfaces: Cross-project manager effects or stale-manager mutations. | dispatch | not started |

Existing-row amendments, without duplicate rows:

- **OWNERCLAIM:** guard close-time worker signaling by acquired custody; reload durable worker records after claiming custody. Add rejected-contender-close and post-construction-record cases.
- **CODEXOWNER:** include the real Codex capture/publication shapes through both settlement and startup cleanup.
- **PERCH2C:** retain actual owner-root inspection before teardown and meaningful killed-worker/second-project evidence.
- **SESSIONFD:** rebaseline after FACADEFD. `_start_service` still allocates temporary directories and registry entries (`command_ports.py:499–510`); lazy binding alone does not reclaim them. `close_consumer_operations` closes only the activated bridge transport (`owner_bootstrap.py:812–817`).
- **DRAINSETTLE/TESTPATCH:** prove draining begins during an authenticated pending wait. Replace product-method substitutions in the release scenarios.

**3. Findings belonging to follow-up projects**

**SLIM**

- **SL6 — LIVENESS 1–4:** normalize the retained client/exit contracts, distinguish timeout/protocol failure from confirmed closure, perform useful published-state preflight and shell-quote restart commands. Preserve uncertainty after submission.
- The exit bug is in the **legacy wrapper branch**: `hostctl/cli.py:850–853` explicitly selects it for non-product composition. Prefer retiring that branch with its consumers rather than expanding it. **BOOTCFG must prove the actual product launch’s failure and requested-stop behavior.**
- **SL1/SL6 — MGR 4:** return the composed manager brief through authenticated effective-context. Keep the current identity scope. PACKS PK5 later adds source attribution; it does not own this missing projection.
- **SL6 — TP6 listing refusal:** this is already assigned by TRIAGE-B. Coordinate one correction with THROUGHPUT rather than producing two stdio-server changes.

**EFFECTS**

- **EF2/EF5 — KILLFENCE 2:** authenticated read → exact pinned disposition → replay, preserving historical UNKNOWN and making no provider retry.
- The maintained parser has no digest/reason options; the service read omits the required pins (`manager_journey_client.py:538`, `manager_journey_service.py:1584–1598`).
- Do not wait for the entire ledger redesign if the required FAILEDFENCE release journey needs this public command. Pull forward the narrow interface correction within EFFECTS. Otherwise leave unresolved attempts explicitly held.

**PROCLIFE**

- **PL3/PL6 — ORPHANWORKER 2:** use the birth-fenced recorded-worker cleanup when staging’s owner is already dead, before reporting stopped (`staging.sh:273–294`). Pull this correction forward for the stage-2/3 gate.
- **PL5/PL6 — ORPHANWORKER 4:** expose identified blocking processes and per-group cleanup outcomes.
- Coordinate the native lifecycle work with **OWNERCLAIM**’s rejected-close and record-reload cases. These do not require completing the whole process-scope redesign first.

**PACKS**

- PACKPARITY 2 is a verified **D14 conformance gap**, not evidence of a runtime authorization failure.
- Put product-owned host/usage descriptions in the product-owned data boundary; extend PK3’s scope explicitly where needed. Broaden the boundary check with documented compatibility exceptions.
- **Do not rename existing wire schema IDs merely to remove the word Otto.** `usage/contract.py:20,189` includes compatibility identifiers; source-path metadata at `:159,169,174` is a different category. Preserve wire compatibility while moving ownership.
- PK5 owns provenance attribution after SLIM restores effective-context’s actual brief.

**THROUGHPUT**

- **TP1:** pin source logs/content; make interrupted/retried pairing explicit and reproduce the statistics.
- **TP3:** recognize direct pytest executables and Python `-m pytest`; preserve unsupported commands. Keep both rename identities and conservatively fall back for shared configuration, unsupported imports and nested layouts. Prove service integration.
- **TP6:** correct the changed response expectation through D19; coordinate SL6’s transport correction.
- **TP5:** delete the prose-matching test; reopen comparable workload/commit-bound measurement and the actual cold-worker journey. Keep TP2/TP4 open.

**ASTRIDFLEET**

- Correct caller classification, AFUX attribution and source provenance in the accumulated study.
- Its substantive study goal is delivered. Implementation remains separate and depends on the chosen EFFECTS contract and edition-1 prerequisites.
- No supported deletion of Astrid’s process custody or the active bootstrap lab helper follows from this study.

**HARNESS3**

- Land only H35’s documentation now, after correcting the gate record.
- H31–H34/H36 remain unfinished. Select and pin the real CLI, implement and qualify its host/admission journey, resolve the host-name cleanup scope, and supply authentic benchmark receipts.
- Rounded self-reported timings demonstrate neither measured acceleration nor dishonesty.

**4. Decisions only the orchestrator can make**

1. **Release restrictions.** Recommend Claude workers initially, Codex clients fully reconnected, two projects activated while quiescent, and UNKNOWN effects held. This permits deferring CODEXOWNER and ACTIVATEWHILE without claiming their original acceptance passed.
2. **Manager interface at CUTOVER.** Recommend the authenticated CLI for this release, after CLIARGS and MGRASK pass. Explicitly defer MGRMCP; otherwise the original MGR contract makes it a blocker.
3. **Follow-up integration before edition 1.** Recommend allowing the two small documentation imports and corrected TP1 through the gate; integrate TP3/TP6 only after their listed fixes. Do not merge any whole project package or mark THROUGHPUT/HARNESS3 complete.
4. **Combined review campaigns.** Recommend stages 3–4 together and stages 5–6 together, with separate obligation verdicts on the same candidate. Preserve stage-2 negative evidence and the destination-install/transfer checks.
5. **Transfer scope and deletion authorization.** Recommend XFERMAP/XFERBOUND, an explicit disposition for every unresolved old occurrence, and the exact deletion set attached to the existing CUTOVER go. A second confirmation is unnecessary if that exact action was already authorized; changed scope requires returning to the user.

**5. Sub-agents**

All three were explicitly spawned as **`gpt-6-luna`**, with self-contained read-only briefs; all three slots were used concurrently.

- `/root/landings_custody` — LABCAPTURE, ORPHANWORKER, MANUALDISPATCH, COMPLETECITE; THROUGHPUT integration; lab-race impact check.
- `/root/landings_control` — LIVENESS, KILLFENCE, MGR, FAILCLOSED; PATH-TO-CUTOVER; late FACADEFD reconciliation.
- `/root/landings_pins` — PACKPARITY, PROJECTPIN, READYPIN, LIMITFD; ASTRIDFLEET/HARNESS3 integration; follow-up ownership checks.

I independently checked the consequential paths and corrected overly broad duplicate/fixed classifications from the delegated reports.

**6. Integration plans and landing rows**

Project snapshots checked:

| project | source head | delivery judgment |
|---|---|---|
| THROUGHPUT | `8e2a97c4023d71f255bacc868a2299c1827aebca` | Partial; goal remains open |
| ASTRIDFLEET | `f8d46ee24f069e99c23c6226497e48ec2e6e615f` | Study delivered; corrections required |
| HARNESS3 | `6e4a14b7ff2a1c2da721b557800d8b106af25855` | H35 delivered; substantive project remains open |

“Now” below means after **BOOTLAND’s exact-tested-SHA protection**, and subject to the orchestrator permitting these bounded imports before edition 1. No merge was attempted. Current canonical changes since project base `163925e` have no changed-path intersection with these selected project deliverables; that is a textual observation, not runtime compatibility proof.

Every landing must record source commits → prepared candidate SHA, exclude generic `.project/` control files, pass its concrete check and applicable affected-file sweeps, obtain named D19 decisions for changed expectations, and run staging on the exact candidate. The current fake gate does not prove a real worker journey.

**THROUGHPUT — ordered landings**

1. **TP1, after correction:** land `60600a3`’s reporting capability with pinned inputs and corrected attempt pairing.
2. **TP3, after correction:** land the combined net change of `afff5cf`, `7b0e012`, `b109ce0`, `919407f`, plus the new selector corrections. Keep this one landing.
3. **TP6, after correction:** land `7085a26`, after its D19 expectation decision and the shared SL6 listing-refusal correction.
4. **Never land TP5 `eb82164` as the current standalone code change.** Preserve its report as historical evidence; exclude/delete its prose test. Replacement measurement work stays in TP5 until actual evidence and commits exist.
5. **No current landing for TP2/TP4.** No implementation commits exist to name. Neither task is complete.

**ASTRIDFLEET — ordered landing**

1. Import one corrected accumulated report from **AF1 `450d783` → AF2 `84b33a9` → AFUX `6e8e959` → AF3 `fad4a1d`**, including the relevant final corrections `573c0c9` and `f8d46ee`.
2. Keep the project package in its clone. Do not merge the whole branch. No study task is discarded.
3. Future implementation remains contract → adapter → real-tool UX/custody review; there are no implementation commits to integrate yet.

**HARNESS3 — ordered landing**

1. Land **H35 `f777436`**, merged in the project as **`6e310ed`**, after correcting the gate claim in the handoff at `6e4a14b`.
2. Never import the generic project package as canonical control state.
3. Later, after delivery, gate **H31 → H32 → H33 → H34 → H36** separately. They currently have no implementation commits; no invented integration rows or SHAs are supplied for them.

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| INTEG-THROUGHPUT-1 | normal | 0.5 | BOOTLAND | **Land corrected TP1 reporting from `60600a3` into canon/main.**<br>Evidence: `ops/bootstrap/land.sh:436`, `:464` on canon; `proj/throughput:ops/bootstrap/throughput_report.py:19–41`, `.project/baseline.md:3`; INTEGRATE-THROUGHPUT 5.<br>• First fix and commit pinned-input reproduction and attempt-aware pairing in THROUGHPUT. • Record those correction SHAs before gating. • Import report evidence at a project-specific path, excluding generic control files. | Parser fixtures for an interrupted `1,1,2` sequence, separate attempts and incomplete runs fail on current TP1 and pass after correction. Reproduction uses fixed input contents and yields the recorded aggregates. Gate the prepared candidate and record its exact landed SHA; no speed threshold. | — | proof | not started |
| INTEG-THROUGHPUT-2 | normal | 0.75 | INTEG-THROUGHPUT-1 | **Land corrected TP3 as one combined change from `afff5cf`, `7b0e012`, `b109ce0`, `919407f`.**<br>Evidence: `src/herzchen/fleet/landing.py:118` and `ops/bootstrap/land.sh:436` on canon; `proj/throughput:src/herzchen/fleet/landing.py:388–490`; INTEGRATE-THROUGHPUT 3–4.<br>• Require committed command-recognition and conservative-selection fixes first. • Preserve the admitted full check for done. • Record the source/correction/candidate mapping and land through the gate. | Before correction, fixtures expose make-pytest rewriting, executable-path recognition, old-path rename importers and shared-config omissions. Through real LandingService and runner records, check submits the intended feedback argv while done submits the unchanged admitted argv; removing the integration hook fails coverage. Gate the exact candidate. | — | fleet | not started |
| INTEG-THROUGHPUT-3 | normal | 0.5 | INTEG-THROUGHPUT-2 | **Land corrected TP6 refusal guidance from `7085a26`.**<br>Evidence: `src/herzchen/fleet/tools/stdio_server.py:52` and `ops/bootstrap/land.sh:436` on canon; `proj/throughput:src/herzchen/fleet/tools/facade.py:96`, `tests/test_tools.py:91`; INTEGRATE-THROUGHPUT 1–2.<br>• Require the named D19 decision for the changed test expectation. • Include SL6’s single transport correction so listing preserves recovery information. • Record correction SHAs and land the selected change without project controls. | Current TP6 fails the exact refusal dictionary assertion; current stdio listing loses the refusal. Real stdio requests with revoked tokens return usable protocol refusal/recovery information while authorized discovery works. Preserve all authorization assertions and gate the final candidate. | — | fleet | not started |
| INTEG-ASTRIDFLEET-1 | normal | 0.5 | BOOTLAND | **Land the corrected ASTRIDFLEET study from `450d783`, `84b33a9`, `6e8e959`, `fad4a1d`, `573c0c9`, `f8d46ee`.**<br>Evidence: `ops/bootstrap/run-task.sh:68`, `tests/test_bootstrap_gate.py:88`, `ops/bootstrap/land.sh:279`, `:479` on canon; INTEGRATE-ASTRIDFLEET.<br>• Import the accumulated report to a project-specific documentation path. • Correct caller classification and AFUX attribution. • Record Astrid `f42eaa6db62d989fc869da7219d76493e932869c`, Otto baseline `163925e`, and the dated EFFECTS comparison. • Exclude generic project controls. | An independent citation/entrypoint check rejects the current reversed executable callers and missing source revision; corrected citations resolve to the pinned sources. Run the existing boundary test to supply a real gate check, then applicable sweep/staging on the candidate. Do not add a prose-matching test or claim an executed integration. | — | proof | not started |
| INTEG-HARNESS3-1 | normal | 0.25 | BOOTLAND | **Land H35’s contributor map from `f777436`, project merge `6e310ed`.**<br>Evidence: `src/herzchen/fleet/hosts/__init__.py:11`, `src/otto/hostctl/config.py:103`, `ops/bootstrap/land.sh:279` on canon; source head `6e4a14b`; INTEGRATE-HARNESS3.<br>• Correct the handoff’s no-gate claim before landing. • Import only the documentation delta and provenance, excluding generic project controls. • Keep H31–H34/H36 explicitly incomplete. | The integration evidence check rejects the present gate exemption and any claim of a delivered third host. Confirm the map’s registry/admission targets against source, run existing host-contract/boundary checks, then the ordinary gate and staging on the exact candidate. No native qualification or measured UX improvement is claimed. | — | proof | not started |

**7. PATH-TO-CUTOVER: deferrals, stage changes and uncovered risks**

Recommended moves **after CUTOVER**, requiring recorded restrictions:

| row/work | restriction that makes deferral acceptable |
|---|---|
| ACTIVATEWHILE | Activate both projects while quiescent; still prove concurrent operation of those projects. This changes stage 5’s contract and needs the orchestrator’s decision. |
| COMPLETEPIN | Finish accepted reviews before unrelated plan edits, or re-review at the current revision. Never weaken content checks. |
| STATUSCAP | Capacity evidence reads actual policy and admissions, not the incorrect aggregate ceiling. |
| UNTIME2 | Repair any individual test obstructing required release evidence now; defer the remaining scheduling cleanup. |
| TESTPATCH | Required release scenarios use real product authorization and owner methods now; defer broad historical fixture reconstruction. |
| DEADLAUNCH | Preserve `run_turn` and `run_continuation` for REWORKWIRE; defer unused-path deletion. |
| CODEXOWNER | Disable Codex worker dispatch. Codex and r4 client reconnection remains mandatory before deletion. |
| ROLEIDS | Only if the release manifest proves distinct owner/operator/host/agent identities and new colliding assignments cannot enter the qualified workload. This relaxes TRIAGE-B’s blocker recommendation. |
| SAVEPATH | Only if every transfer invocation uses an absolute file path and XFERMAP verifies the exact content. Otherwise keep it before CUTOVER. |
| LINECHECK, STOPATOM, STATUSOBJ | Preflight release checkouts, use a verified stop procedure and require valid fresh status during transfer. These remain real fixes, not claimed passes. |
| ASSESSCAP, STATINDEX, EVENTPAGE, RET | Fresh Store and bounded initial load; monitor growth. None becomes unnecessary. |
| LABRETRY, ASKDISP | Retained labs can be retried by a rehearsed restart; duplicate dispatch records do not demonstrate duplicate provider work. Keep both fixes scheduled. |
| MGRMCP | Only after approving and proving the authenticated CLI release interface. |
| R1d, SKEL, MANY, REVIEW, UPGRADE, G3, LANES, DELETE, CACHE | Keep their existing post-CUTOVER position. Initial installation/restart remains BOOTCFG’s pre-CUTOVER obligation; caching remains conditional on measurement. |

I would **not** automatically defer OBSOWNER merely because concurrency is small: its owner-thread affinity problem is not resolved by a worker-count ceiling. Keep its controlled regression and coordinate it with PINALL.

For **BOOTLAND**, prioritize exact-tested-SHA publication immediately. Automated recovery machinery can be reduced only if the orchestrator adopts a strict stop-and-reconcile procedure after uncertain push/lock state. A later landing must never publish unresolved prior work implicitly.

Merge or drop **ceremonies**, not evidence:

- Merge **3 Works + 4 Lands** into one real campaign, including failure/conflict/rework.
- Merge **5 Manages + 6 Dogfood** into one campaign with separately reported obligations.
- Drop repeated standalone happy-path runs already proved on the same candidate.
- Retain stage-2 negative checks, actual destination install/restart, and stage-7 transfer verification.
- Shrink later SKEL only where the identical Claude journey is already evidenced; cold Codex and cold-client discovery remain distinct.
- Do not add another broad audit wave before running the missing real journeys.

The uncovered CUTOVER work is represented by **REALSTAGE56, XFERMAP and XFERBOUND** above. They cover the absent real campaign, all seven follow-ups, exact final revisions and bodies, independent complete readback, unresolved old effects, every client locator/binding, preserved exports and deletion eligibility.

The existing tasklist already owns **BOOTCFG, BOOTLAND, LANDPROOF, FILEAUTH, OWNERCLAIM, RELAYSAFE and PROOFDOC**. Keep those rows rather than creating another set from PATH-TO-CUTOVER. The strategy audit’s elapsed-time estimate remains an unverified planning estimate; it is not release evidence.