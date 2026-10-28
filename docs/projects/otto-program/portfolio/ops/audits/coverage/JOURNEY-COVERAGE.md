**Only stages 0 and 1 currently gate landings.** Stage 2’s assertions are not yet in the landing regression net. Several also lack the observations needed to prove their claims. Stages 3, 5 and 6 are absent; stage 4’s fake run performs a shell merge and can pass while `owner-driven-canary` is skipped. [Gated stages](${TRANSFER_ROOT}/portfolio/ops/stages-gated), [landing hook](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:431), [stage-4 assertions](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1506).

This review pins source to **`canon/main` `ec6bacf44ec0f370317a36353e950f44b918865f`**, read using `git show`. No tests or Otto commands were run. The coverage mappings below are **source-based inferences**, not reproduced failures.

I included the later audit, tooling and integration additions: 110 relevant rows, including RET’s added scope, plus three older carryovers marked †. That is a row count, not a count of independent product defects.

The table uses these existing-check abbreviations:

| Code | Stage and exact existing checks | What they presently establish |
|---|---|---|
| E0 | 0: `staging-ready`, `status-while-up`, `status-after-kill-is-stale`, `restart-after-kill-keeps-store`, `status-after-stop`, `refused-start-names-its-reason` | Empty-owner lifecycle; not queued/live-work recovery |
| E1 | 1: `show-readback-available`, `store-has-typed-tasks`, `edit-is-persisted`, `nothing-runs`, `edit-makes-revision`, `project-history-keeps-old-revision`, `stale-save-refused`, `store-growth-per-save` | Save/read/edit/stale-base behavior |
| E2S | 2: `admit-and-dispatch-ran`, `stage2-canary-valid`, `stage2-review-document` | Setup, declared scopes and retained review |
| E2D | 2: `admitted-ready-dependency-order` | Positive A→B→C progress, using lifecycle snapshots; **not event-order proof** |
| E2A | 2: `operator-presence-approved` | Approved presence records; not denial or impersonation cases |
| E2T | 2: `stage2-store-snapshots` | Matching dispatch records exist; not every replay/count invariant |
| E2K | 2: `worker-kill-recovery`, `stage2-census` | Slot count falls, killed PID disappears, owner survives; **not fence recovery** |
| EC | Shared: `no-leaked-process`, `staging-at-rest-clean` | Recorded process/at-rest cleanup for the exercised path |

Sources: [check definitions](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:45), [stage-2 observations](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:424), [stage-2 assertions](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1333).

**M2a–M6b below are missing assertions**, specified after the inventory. **G1–G5 are complementary guards**, also specified below.

For the “own test” column:

- **U:** isolated unit/domain/contract test.
- **I:** owner, Store, filesystem or process integration test—often called “unit test” in the row, but stronger than an isolated unit test.
- **J:** an explicit staged, client-to-owner or installation journey.
- **S:** static, documentation or bootstrap-script verification.
- **T:** existing-suite repair; unit-only scope is not established.
- **+J:** the row additionally requires an orchestrator stage run. This does **not** mean that journey currently gates landings.

These classify the row’s **acceptance contract**, not whether every promised test was delivered or passed. Tasklist statuses are stale: for example, CAPTUREEDIT remains “not started” although its landing is in the pinned canon history.

The stage-found and bootstrap rows are sourced from [tasklist lines 36 onward](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:36), [tooling rows](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:77), and [stage-2 repairs](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:88).

| Defect row · tasklist line | Existing coverage; missing assertion or other guard | Own test |
|---|---|---|
| AUTODISPATCH · 36 | E2D positive; **M2a** for blocked/unadmitted work and duplicate launches | I |
| AUTODISPATCH2 · 37 | E2D positive; **M2d** for failed-launch recovery | J |
| STAGESETUP · 38 | E2S; **G3** for refusal/path-limit variants | J |
| OPERATOR-ADMIT · 39 | E2A positive; **M2c** for declined presence and foreign authority | I+J |
| REDS2† · 63 | No single journey covers the mixed failures; **G1** | T |
| REDS3 · 64 | No single journey covers the mixed failures; **G1** | T |
| TOOLING18 · 77 | No Otto journey proves gate selection; **G1** | S |
| TOOLING19 · 78 | No journey proves collection-error interpretation; **G1** | S |
| TOOLING20 · 79 | No journey proves D19 file coverage; **G1** | S |
| TOOLING21 · 80 | EC does not exercise failed test teardown; **G1** | S+I |
| TOOLING22 · 81 | No journey proves SUBFAILED/compound-command handling; **G1** | S |
| TOOLING23 · 82 | No journey proves orphan-check ownership boundaries; **G1** | S+I |
| TOOLING24 · 83 | No journey proves affected-test selection; **G1** | S |
| TOOLING25 · 84 | No journey proves brief-command parsing; **G1** | S |
| PERCH1FIX† · 85 | E1 and `store-matches-stage`; **G1** for assertion fault tests | U+J |
| PERCH2† · 86 | E2S/D/A/T/K exist; **M2a–e** supply missing proof | U+J |
| PERCH2B · 87 | E2S checks that setup and scenario actually ran | J |
| ACTCRIT · 88 | E2S checks product-declared scopes; **M3b** for wrong/missing scope | U+J |
| PINCONTENT · 89 | E2D exercises activation→admission; **M2a** for content-change refusal | U+J |
| FDLEAK · 90 | **M2e** resource bound; **M2d** failed launch does not spin | I+J |
| PYSTUB · 91 | E2D catches worker launch failure; **M3a** exercises fenced MCP launch; **G3** denies extra binaries | I+J |
| DISPATCHSEEN · 92 | **M2d** deliberately fails launch and checks status, exit and stderr | I |
| POLICYPIN · 93 | E2D positive landing; **M2a/M3b** reject changed content/policy | U+J |
| LANDASSESS · 94 | E2D positive assessment; **M3b** preserves review-required policy | U+J |
| LANDEVIDENCE · 95 | E2D positive evidence handoff; **M3b** rejects failed/tampered evidence | I+J |
| PACKLOAD · 96 | E2D catches inability to load evidence pack; **G3** proves provenance/tamper behavior | U+J |
| FAKECOMPLETE · 97 | E2D catches broken stand-in completion | U+J |
| FAKECOMPLETE2 · 98 | E2D catches wrong result shape | U+J |
| FAKECOMPLETE3 · 99 | E2D catches wrong resolver call signature | U+J |
| COMPLETEEVIDENCE · 100 | E2D exercises guarded `complete_task`; **M3b** adds tampered/missing blob refusal | I+J |
| STATUSLAUNCH · 101 | E2D reads real project dispatch status; **M2d** adds failure/settlement consistency | I+J |
| WORKERSETTLE · 102 | E2D is insufficient after landing; **M2d/M3a** require the retained turn to settle completed | I+J |
| STAGE2C · 103 | E2K exercises the harness’s kill and slot release | U+J |
| AUTODISPATCHREC · 104 | E2T catches missing dispatch events; **M2a** proves exact count and replay | I+J |
| LABCAPTURE · 105 | **M2d** captured settlement and actual owner-lab census; **M4b** retry/incarnation cases | I+J |
| ORPHANWORKER · 106 | EC partial; **M2d** forces stop with live worker/initializer groups | I+J |
| PROJECTPIN · 107 | **M2a** edits another task after activation and still launches unchanged work | I+J |
| OWNERCOMPLETION · 108 | **M2b** starts a manager while worker admission is outstanding | I |
| READYPIN · 109 | E2D positive progress; **M2a** controls prepare→admit→complete→next-start ordering | I+J |
| FACADEFD · 110 | **M2e**; no current descriptor assertion | I+J |
| CTLRACE · 111 | Natural journey is unreliable; **G2** publication barrier | U |
| PERCH2C · 112 | **M2a–e**, plus **G1** non-vacuity and missing-input tests | U+J |
| COMPLETECITE · 113 | E2D supplies correct citations only; **M3b** supplies wrong refs/hashes/scope | U+J |
| KILLFENCE · 114 | E2K proves capacity release only; **M2d** proves held-state recovery and project isolation | I+J |
| LIMITFD · 115 | **M2e** | I |
| MANUALDISPATCH · 116 | E2T covers automatic path only; **M5a** exercises all maintained manual/continuation paths | I |
| PACKPARITY · 117 | No journey proves provenance equivalence/layering; **G3** | U+S |
| FAILCLOSED · 118 | **M2a/M6a** cover changed admission and missing operator; **G3** covers legacy stamp/exec-allowance forms | U |
| ADMITHELD · 119 | E2A checks final approval only; **M2c** requires one prover call and one retained request | I |
| ADMITFREE · 120 | **M2c** admits B while A holds capacity | I |

The audit and integration rows are sourced from [tasklist lines 129–150](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:129), [151–173](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:151), [174–190](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:174), and [RET](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:205).

| Defect row · tasklist line | Existing coverage; missing assertion or other guard | Own test |
|---|---|---|
| CAPTUREEDIT · 129 | **M3a**: Edit-only, Write→Edit and rebase-altered files | I+J |
| FAILEDFENCE · 130 | **M3c**: provider failure before/after done, manager recovery, next task | I |
| SESSIONFD · 131 | **M2e**: descriptors, threads, directories and retained service registrations | I+J |
| REALSTAGE3 · 132 | **M3a–c**; stage absent | U+J |
| REALSTAGE4 · 133 | **M4a–c**; current shell-merge assertions do not qualify | U+J |
| ACTIVATEWHILE · 134 | **M5c**, when enabled; deferred from first-release scope | I |
| REWORKWIRE · 135 | **M4a/M5a**: real refusal, kept lab, same-session repair | I |
| DRAINSETTLE · 136 | E0 lacks queued work; **M5d** drains a full pool and resolves every waiter | I |
| GATESKIP · 137 | No journey proves tests executed; **G1** | S+I |
| COMPLETEPIN · 138 | **M5b**: accepted review, unrelated save, ordinary finish | I |
| DONESETTLE · 139 | **M4c** plus **G2** controlled queued-call race | I |
| STATUSCAP · 140 | **M2b** compares reported ceilings with actual admission | U |
| PINALL · 141 | **M2d** for initializer/worker custody; **G2** for pin failure and reused-PID cases | I |
| UNTIME2 · 142 | No journey repairs unsound tests; **G1** | U |
| TESTPATCH · 143 | **M3b/M5a/M5c** exercise real paths; **G1** audits substitutions | I |
| OWNERCLAIM · 144 | E0 covers ordinary second-start refusal only; **M2d/M5d**, plus **G2** competing-home race | I |
| RECEIPTFENCE · 145 | **M5d**: failed receipt publication and restart without repeated handler effect | I |
| MCPPATH · 146 | **M3a** launches actual stdio server from a shadowing lab | I |
| ADMITREVIEW · 147 | E2S checks a valid review only; **M2c** rejects nonexistent revision | U |
| FAILCLOSED2 · 148 | **M2c** conflicting activation pins; **G3** actor-decoding matrix | U |
| DEADLAUNCH · 149 | No ordinary journey reaches unused entry points; **G3** static caller/export guard | S |
| CODEXOWNER · 150 | **M3a** parameterized by host; real qualification also belongs to stage 8; deferred | I |
| BOOTLAND · 151 | Product stage 4 cannot prove bootstrap publication; **G1** disposable-Git crash/race tests | I |
| LANDPROOF · 152 | **M4a** refuses completion after acceptance but before line advancement | I |
| FILEAUTH · 153 | **M5c** foreign manager file/socket submission versus legitimate retained start | I |
| ROLEIDS · 154 | **M2c** reserved and duplicate principals through real entrances | I |
| OBSOWNER · 155 | Ordinary successful launch cannot prove thread affinity; **G2** | I |
| RELAYSAFE · 156 | **M5d** malformed/oversized reply while owner continues serving; **G3** input matrix | I |
| SAVEPATH · 157 | **M6a** actual client and owner with different cwd/files | J |
| BOOTCFG · 158 | E0 starts staging, not an unedited managed installation; **M6a** | J |
| PROOFDOC · 159 | No journey proves documentation accuracy; **G5/G1** | S |
| LINECHECK · 160 | **M4a** wrong branch/dirty line refused before provider input, including lab reuse | I |
| STOPATOM · 161 | **M5d** observes stop reason/return; **G2** proves atomic publication | I |
| STATUSOBJ · 162 | **M6a** cold-client unavailable result; **G3** malformed-record matrix | U |
| ASSESSCAP · 163 | Tiny canary cannot reach the foreign-history bound; **G4** | I |
| STATINDEX · 164 | Journey output cannot prove index use; **G4** | I |
| EVENTPAGE · 165 | Tiny canary cannot prove bounded historical hydration; **G4** | I |
| LABPIN · 166 | **M4b** two occurrences and exact cleanup authority; **G2** writer/deletion race | I |
| CITECAN · 167 | **M3b/M5b** completion forms followed by historical/corrective readback | U |
| ROSTERPIN · 168 | **M2a** add unrelated unadmitted D while admitted A remains launchable | I |
| CLIARGS · 169 | **M2d/M5a** actual parser→client→authenticated recovery/route commands | J |
| OPPRE · 170 | **M6a** missing operator leaves no reservation/receipt; same-key retry succeeds once | I |
| MGRASK · 171 | **M5a** exact manager wake, asker session and replay count | I |
| PARITYFIX · 172 | No journey proves independent relocated vectors or fixture cleanup; **G3** | U+I |
| REALSTAGE56 · 173 | **M5a–d/M6a–b**; stages absent | J |
| XFERMAP · 174 | **M6b** safe transfer rehearsal; actual preservation proof remains stage 7 | J |
| XFERBOUND · 175 | **M6b** safe custody/client/deletion-eligibility rehearsal; actual switch remains stage 7 | J |
| LABRETRY · 176 | **M4b** same-owner cleanup retry without repeated work | I |
| ASKDISP · 177 | **M5a** exactly one continuation dispatch/provider call; replay adds none | I |
| MGRMCP · 178 | **M5c** manager tool discovery and scoped calls, when feature ships; deferred | J |
| INTEG-THROUGHPUT-1 · 179 | No journey proves report attempt pairing/reproduction; **G1/G5** | U+S |
| INTEG-THROUGHPUT-2 · 180 | **M3a/M4a** actual feedback argv versus unchanged admitted done argv; **G1** selector fixtures | U+I |
| INTEG-THROUGHPUT-3 · 181 | **M3a** actual stdio discovery with authorized/revoked tokens | J |
| INTEG-ASTRIDFLEET-1 · 182 | Editorial/provenance issue; **G5**, ordinary integration gate retained | S |
| INTEG-HARNESS3-1 · 183 | Documentation/import issue; **G5/G1**; cannot imply third-host qualification | S |
| INTEG-EFFECTS-1 · 184 | **M5d** durable STARTED→crash→UNKNOWN, replay invokes nothing | I |
| INTEG-EFFECTS-2 · 185 | **M5d** exact retained terminal proof resolves once; foreign/stale proof refuses | I |
| INTEG-EFFECTS-3 · 186 | **M5d** runner terminal result binds command, actor and gone custody | I |
| INTEG-EFFECTS-4 · 187 | **M5d** genuine gateway crash/reconstruction/retry; E0 catches only startup breakage | I |
| INTEG-EFFECTS-5 · 188 | **M5d/M6a** real owner-lane held-effect read/refusal/resolution and cold-client guidance | J |
| TESTREAP · 189 | Otto journey cannot prove failing test-harness teardown; **G1** | I |
| TOOLING26 · 190 | No journey proves D19 verdict parsing; **G1** | S |
| RET, including RETOWNER · 205 | Small finite journey cannot prove bounded retention and preserved replay fences; **G4** | Not yet specified |

Three current-source distinctions prevent misleading coverage claims:

- Stage 2 sets `config.tasks=[]`, making `timeline-events` vacuous. Its pool observation uses three dispatch snapshots, while the canary is serial and its stated limits are not applied by `perch.sh`. [Initialization](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:938), [capacity observation](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:448).
- `labs-left-behind` receives the harness’s `labs` directory. Product labs live under `canon.otto-labs/<branch-key>`. A clean harness directory therefore does not prove product cleanup. [Snapshot call](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:744), [product lab root](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:640).
- COMPLETECITE’s product checks now exist. The missing regression proof is the **negative journey**: the fake completion always constructs correct accepted refs/digests. It calls guarded `complete_task`, but bypasses the ordinary manager review/`finish_task` route needed by COMPLETEPIN. [Completion stand-in](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_stage2_owner.py:29), [current citation validation](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/assignments.py:706).

The missing assertions should do and observe the following. Each name is proposed, not present in canon.

| ID · stage · proposed check name | Required journey and observations |
|---|---|
| **M2a · 2 · `dispatch-content-and-order`** | Activate before admission. Prepare a manager occurrence, admit and complete its task, then start its dependent. Compare Store event sequence: prerequisite completion precedes dependent dispatch; every launch has exactly one admitted dispatch; repeated pump/manual requests add none. Edit admitted C’s instructions and observe an owner selection cycle refusing launch. **Re-admit that changed content before** testing a metadata-only revision. Add unadmitted D; unchanged A still launches, D does not. Relevant task/mandate/policy edits still refuse. |
| **M2b · 2 · `capacity-reserve-and-status`** | Apply canary capacity through product configuration. Hold one worker, make a second independent worker ready, and request a manager turn. Observe worker waiting and manager starting, without an OwnerCompletion mapping error. Compare admitted units and published worker/manager/combined ceilings throughout. |
| **M2c · 2 · `admission-authority-and-queue`** | Admit while another worker runs and across the owner-boundary deferral window. Record one request, one presence proof and one stamp. Declined presence, nonexistent review revision, reserved/duplicate principal and conflicting plan pins refuse without writes. Exercise agent attempts through the actual supported ingress paths. |
| **M2d · 2 · `settlement-recovery-and-custody`** | Require A/B’s retained Due results to settle completed with captured artifacts, then inspect the actual owner lab root. Force an early child exit and observe exit/stderr/reason without launch spinning. Kill C: capacity frees while its unknown-effect fence remains. Use the maintained manager CLI to recover once; no provider replay occurs and subsequent work progresses. Force-stop/restart with live worker and initializer descendants; recorded groups disappear and an unrelated sentinel survives. A refused/held owner startup launches no queued work. |
| **M2e · 2 · `owner-resources-bounded`** | Warm the owner, then repeat dispatch preparation, project/manager status, document, assessment and activation reads. Record FD, thread, command-directory and service-registration counts before and after settled requests. Require a small fixed allowance, not growth per request. Keep actor/evidence grants isolated across requests. |
| **M3a · 3 · `worker-capture-and-tools`** | Through REALSTAGE3’s owner/adapter, run Edit-only, Write→Edit and auto-merged-file tasks. Observe actual task/check/done calls, runner argv/commit/evidence, heavy-unit accounting, completed capture and cleanup. Exercise real fenced stdio launch from a lab containing shadow modules; unauthorized/revoked tokens receive usable refusals. Check feedback selection separately from done’s admitted full check. Add Codex as a host variant when CODEXOWNER ships. |
| **M3b · 3 · `completion-evidence-exact`** | Complete through product manager operations with accepted evidence. Try another task’s ref, wrong list/map digest, missing/tampered blob and absent/wrong required scope; no completion advances. Valid canonical, labelled-map and list forms complete equivalent tasks and survive historical/corrective readback. Review-required work still requires review. |
| **M3c · 3 · `provider-failure-recovers`** | End a provider turn with an error before done and after a landed done. Observe failed history and retained fence. Manager recovery requires the group gone, settles once without another provider effect, and releases the next task. A live group remains refused. |
| **M4a · 4 · `landing-exact-commit-and-proof`** | Use product landing for happy and conflicting tasks. Bind check result, accepted candidate and actual line commit. Conflict returns `landing_refused` and keeps the lab. Fail Git advancement after acceptance: ordinary completion refuses until reconciliation advances the exact line once. Wrong/dirty line preparation refuses before provider input, including lab reuse. |
| **M4b · 4 · `captured-lab-custody-and-retry`** | Retain captured occurrence A and uncaptured landed occurrence B of the same task. Restart must preserve B. After exact capture, fail the first removal externally; status stays pending and the same owner retries removal. Provider/check/acceptance/completion counts do not increase. Inspect owner labs before harness teardown. |
| **M4c · 4 · `done-token-revoked`** | Send done and a competing check over the actual facade. Once done’s owner operation settles, queued/new calls with its token refuse and create no runner record. Retain the deterministic race test as G2. |
| **M5a · 5 · `manager-session-and-dispatch`** | Exercise actual manager CLI read/route/retry/recover/resume paths, a failed check, landing conflict and ask/answer. Require same worker session/lab, fresh authorization, bounded rework and no unknown-effect resume. Ask wakes only the current project manager; its answer resumes the exact asker once. Every maintained launch path records one dispatch; replay adds neither dispatch nor provider call. |
| **M5b · 5 · `completion-survives-unrelated-edit`** | Accept a review without finishing, edit unrelated B, then invoke ordinary manager finish for A. It succeeds with canonical evidence readback. Changes to A or its policy refuse with an actionable reason. |
| **M5c · 5 · `project-authority-and-isolation`** | Run two preactivated projects. A’s manager cannot submit B’s retained commands, answer its worker or use stale manager credentials; legitimate owner recovery still works. Add activation-during-work and manager MCP variants **only when their deferred features ship**. |
| **M5d · 5 · `drain-receipt-and-effect-recovery`** | Drain with one running and one queued request: every waiter receives one correct outcome and close completes. Restart without duplicated work. Fail receipt publication after an effect; retry/restart repeats receipt delivery, never the handler. Crash after durable effect start; UNKNOWN remains fenced until exact retained proof resolves it once. Exercise runner custody, stale/foreign proof refusal, malformed relay responses and stop-reason readback. |
| **M6a · 6 · `cold-client-install-and-save`** | Fresh managed installation with no hand edits; verify interpreter/source/home and restart behavior. From a different cwd, save a relative filename and independently compare exact contents. Missing operator leaves no project/reservation/consumed receipt; configure it and retry the same key once. Cold status/effect reads give valid results or specific unavailable/refusal guidance. |
| **M6b · 6 · `transfer-rehearsal-complete-and-fenced`** | Use disposable old/new owners with pagination, documents and changed revisions. Compare complete mapped content; omissions/stale exports refuse. Unresolved effects, stale client binding, failed destination restart, missing export or live old owner keep deletion **ineligible**. This rehearses stage 7; it does not perform or authorize live deletion. |

These placements follow [PLAN §16](${TRANSFER_ROOT}/portfolio/PLAN.md:398). The first-release restrictions—Claude workers, quiescent activation, authenticated manager CLI—must remain explicit; deferred CODEXOWNER, ACTIVATEWHILE and MGRMCP scenarios cannot silently become release requirements or be reported as delivered. [Scope decisions](${TRANSFER_ROOT}/portfolio/PLAN.md:411).

I would add **five rows**, one per stage, extending the existing stage-building work. Estimates are planning judgments.

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| JREG2 | xhard | 1.5 | PERCH2C, SESSIONFD, CLIARGS, OWNERCLAIM, PINALL, ROSTERPIN, ADMITREVIEW | **Stage 2 permanently guards dispatch regressions.** Extend the current canary with dispatch-content-and-order, capacity-reserve-and-status, admission-authority-and-queue, settlement-recovery-and-custody and owner-resources-bounded. Observe Store ordering, exact launch counts, content edits and re-admission, competing workers and manager reserve, approval/denial, failed launch, killed-worker recovery, captured settlement, actual owner labs and resource counts. | Each assertion fails on a corrupted required observation and on its corresponding controlled failing scenario. Missing evidence or an in-scope skip fails. The fake journey passes on the exact candidate with only person/model stand-ins; record every stand-in. Add stage 2 to stages-gated only after its review passes. | Invariant: Every admitted launch and recovery is proved from owner evidence. Plausible mistake: Reusing fixed lists, lifecycle snapshots or harness cleanup as proof. Surfaces: Stage 2 stays green while dispatch, custody or resources regress. | proof | not started |
| JREG3 | xhard | 1.0 | REALSTAGE3, CAPTUREEDIT, FAILEDFENCE, MCPPATH, COMPLETECITE, CITECAN | **Stage 3 guards worker capture, tools and evidence.** Add worker-capture-and-tools, completion-evidence-exact and provider-failure-recovers. Cover Edit and Write combinations, real fenced MCP startup, runner/check records, wrong evidence and scope, completion input forms and failed-provider recovery. Keep the Codex variant conditional on CODEXOWNER. | Fake-provider gate and real-worker qualification use the same owner observations. Every negative case refuses without completion or replay; every positive task settles with exact captured evidence and correct cleanup. Each required assertion has a failing evidence fixture. Real qualification records the actual worker and presence modes. | Invariant: Accepted delivery is exactly the authorized worker output and verified check evidence. Plausible mistake: A stand-in constructs valid evidence while bypassing the manager or adapter being qualified. Surfaces: Real workers land but settle unknown, or invalid evidence completes work. | proof | not started |
| JREG4 | xhard | 1.0 | REALSTAGE4, LANDPROOF, LABPIN, LABRETRY, DONESETTLE, LINECHECK | **Stage 4 guards product landing and cleanup.** Add landing-exact-commit-and-proof, captured-lab-custody-and-retry and done-token-revoked. Exercise real conflict refusal, accepted-but-unlanded recovery, exact captured occurrences, failed removal and token settlement. Remove shell landing and refused-lab deletion as proof. | Runner, acceptance and line records identify the same commit. Unlanded work cannot complete. Conflict keeps the lab. Cleanup retries on the same owner without another work effect. Settled-token calls produce no runner record. Both fake and real worker variants use product landing; in-scope skips fail. | Invariant: Completion and deletion follow the exact accepted, landed and captured occurrence. Plausible mistake: Equating accepted evidence with line advancement or an old capture with current cleanup authority. Surfaces: Missing landed work or lost worker output. | proof | not started |
| JREG5 | xhard | 2.0 | REALSTAGE56, REWORKWIRE, MGRASK, CLIARGS, COMPLETEPIN, DRAINSETTLE, RECEIPTFENCE, FILEAUTH, ASKDISP, RELAYSAFE, INTEG-EFFECTS-5 | **Stage 5 guards management and recovery.** Add manager-session-and-dispatch, completion-survives-unrelated-edit, project-authority-and-isolation and drain-receipt-and-effect-recovery. Drive maintained clients, two preactivated projects, bounded same-session rework, ask/answer, exact dispatch counts, ordinary finish, safe drain and retained-effect recovery. Deferred activation and manager MCP variants remain explicitly disabled until delivered. | Record manager wake, assignment, generation, session, dispatch, provider and receipt counts. Foreign/stale requests refuse. Unrelated edits preserve valid completion. Drain answers every waiter. Crash or receipt-write failure never repeats an effect; exact retained proof resolves once. Fake and real campaigns produce separate stage verdicts on one SHA. | Invariant: Management preserves session authority and effects occur once across recovery. Plausible mistake: Testing direct handlers instead of maintained clients, or treating UNKNOWN as permission to retry. Surfaces: Stranded work, wrong-session answers or duplicate effects. | proof | not started |
| JREG6 | xhard | 1.0 | REALSTAGE56, SAVEPATH, BOOTCFG, OPPRE, XFERMAP, XFERBOUND | **Stage 6 guards cold-client operation and rehearses transfer.** Add cold-client-install-and-save and transfer-rehearsal-complete-and-fenced beside the two genuine program-task landings. Use fresh managed installation, distinct client cwd, independent paginated readback and disposable old/new installations. | Exact source/home survives managed restart; relative save reads the caller’s file; refused creation consumes nothing. Complete mapped readback detects missing pages, altered bodies and stale revisions. Every unresolved-custody, client-binding, export or restart fault keeps deletion ineligible. The actual stage-7 switch and user go remain separate. | Invariant: Release and transfer evidence identifies complete preserved work and the intended owner. Plausible mistake: Treating a successful save or one connected client as complete migration proof. Surfaces: Wrong-file saves, stale-owner use or loss at cutover. | proof | not started |

For every row, retain deterministic assertion tests beside `test_perch.py`, but also prove that the scenario actually reaches the product boundary. Corrupting a JSON observation proves the assertion can reject bad input; it does not prove the collector would notice the product defect.

Some defect classes need guards a journey cannot reasonably replace:

| Guard | Why a journey is insufficient | Required protection |
|---|---|---|
| **G1 — gate and test-harness correctness** | An Otto task journey does not execute every bootstrap decision parser, collection failure, sweep selector, interrupted push or failing-test teardown. | Disposable-repository/script integration tests; misleading D19 headings; all-skipped/no-tests cases; compound commands; affected-file selection; failed/interrupted harness process census. Keep these separate from product stage 4. |
| **G2 — controlled interleavings and process identity** | Repeating a successful journey cannot reliably hit create-before-write, callback-thread, token-settlement or deletion-lock windows, nor safely arrange genuine PID reuse. | Barrier-controlled component/process tests, filesystem-boundary fault injection, exact incarnation fixtures, thread-affinity and before-input assertions. Journey scenarios provide composition coverage, not exhaustive race proof. |
| **G3 — exhaustive contracts, provenance and architecture** | A small canary cannot enumerate malformed actor records, legacy stamps, conflicting aliases, provenance vectors or unused exported launch routes. Successful output cannot prove layering. | Table-driven/property tests, independent immutable provenance vectors under relocated roots, subprocess fence tests, static dependency/caller checks and strict decoder tests. |
| **G4 — scale and retention** | Three tasks cannot expose 10,000-event coverage limits, 30,000-event hydration, query plans or unbounded lifetime retention. Timing a journey cannot prove an index was used. | Synthetic real-Store fixtures; query-plan and hydration-count assertions; replay-fence preservation tests; measured resource/retention soak. No elapsed-time pass thresholds. |
| **G5 — evidence and documentation accuracy** | A runtime success cannot validate a report’s source attribution, fixed input corpus, handoff claims or instructions. | Independent pinned-source/citation review, reproducible report fixtures and documentation-to-command contracts. Avoid prose-matching tests that merely repeat the claim. |

These are consistent with the audits’ distinction between source-established defects, prospective regressions and incomplete project evidence. [TRIAGE-B](${TRANSFER_ROOT}/portfolio/ops/audits/triage-b/TRIAGE-B.md:61), [TRIAGE-C](${TRANSFER_ROOT}/portfolio/ops/audits/triage-c/TRIAGE-C.md:72).

For the nightly sweep, I propose **one pinned canon SHA per campaign**, with explicit expected stages rather than `all` discovering whatever happens to be declared.

| Availability | Nightly work |
|---|---|
| Today | Stages **0 and 1** as qualified regressions; **2** as a separately labelled diagnostic. Report 3–8 as unavailable/unqualified, never as a green full sweep. |
| After REALSTAGE3/4/56 and reviews | Fake-provider **0–6**, then a real-worker **3–6** campaign on the same SHA. The original stage-6 qualification still needs two genuine program tasks; repeatable nightly tasks must be labelled regression replays. |
| After host/render qualification | Add **8**: cold Claude and Codex journeys, bounded concurrency and nested/standalone render accounting. |
| Transfer | Run **7’s disposable rehearsal**, including client/custody/deletion-eligibility checks. Never repeat live switch-over or deletion nightly. |

Unattended real-worker runs need worker mode and presence mode recorded separately. Today `--fake` couples fake workers/completion with fake presence. A nightly test-installation presence stand-in is useful, but cannot satisfy the real-presence qualification. Record at least `worker_mode`, `presence_mode` and `completion_mode`; do not hide them under one “real” label.

Record:

- Canon SHA, harness/canary revision, host/interpreter/profile and configuration digest.
- Expected, executed, skipped and unavailable scenarios; individual assertion verdicts and raw evidence paths.
- Stage start/end and elapsed time; setup, worker, runner, recovery and teardown durations.
- Exact task/assignment/generation/session/occurrence identities; event sequence; provider, dispatch, check, completion and receipt counts.
- Runner/evidence/accepted/landed commit linkage; process groups, owner-lab leftovers, FD/thread/directory counts, Store growth, tokens/cost and memory pressure.
- First failing boundary and diagnostic records, before cleanup.

**Reserve 60 minutes initially for the expanded nightly campaign. That is a provisional scheduling allowance, not a measured runtime.** Report unfinished work explicitly; use a watchdog for hangs without making ordinary slowness a correctness failure. Replace the allowance with observed per-stage distributions after the new stages run.

I independently recomputed the latest **25 successful 17-Oct `land.out` logs**, ending at CAPTUREEDIT:

| Logged interval | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Last swept-test timestamp → staging-complete timestamp | 9 s | **11 s** | 21 s |
| Sweep-start timestamp → last swept-test timestamp | 18 s | **183 s** | 974 s |
| Landing start → final timestamp | 50 s | **221 s** | 1,004 s |

Representative staging-tail intervals:

| Landing | Interval |
|---|---:|
| CAPTUREEDIT | 11 s |
| CTLRACE | 16 s |
| FACADEFD | 19 s |
| OWNERCOMPLETION | 12 s |
| READYPIN | 15 s |
| COMPLETECITE | 21 s |

Evidence: [CAPTUREEDIT](${TRANSFER_ROOT}/portfolio/ops/runs/CAPTUREEDIT/land.out:20), [CTLRACE](${TRANSFER_ROOT}/portfolio/ops/runs/CTLRACE/land.out:10), [FACADEFD](${TRANSFER_ROOT}/portfolio/ops/runs/FACADEFD/land.out:143), [OWNERCOMPLETION](${TRANSFER_ROOT}/portfolio/ops/runs/OWNERCOMPLETION/land.out:127), [READYPIN](${TRANSFER_ROOT}/portfolio/ops/runs/READYPIN/land.out:76), [COMPLETECITE](${TRANSFER_ROOT}/portfolio/ops/runs/COMPLETECITE/land.out:26).

That first interval is a **composite upper bound on the staging portion**, including intervening gate work—not separate stage timings. The gate redirects staging output and logs only its completion milestone. [Instrumentation boundary](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:431).

**There is no measured case for exempting any implemented fake journey from every landing.** Stages 0–1 are inexpensive in these logs. Stages 2–8 have no comparable landing measurement here. Keep newly qualified bounded fake journeys in the landing gate; place real-model campaigns and extended concurrency/retention soaks nightly. Measure each stage before proposing a speed exemption.