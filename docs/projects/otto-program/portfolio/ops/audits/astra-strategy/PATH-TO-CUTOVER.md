**The shortest sound path is a smaller release gate, followed by a verified transfer and a separately gated deletion.** Do not make every audit recommendation a CUTOVER dependency. Do not skip real-worker proof either: stages 5 and 6 currently have no implemented scenarios.

My planning estimate is **35–60 agent-hours, roughly 12–24 elapsed hours with six workers**, excluding the user’s response time. This is an estimate, not measured remaining work.

I reviewed `canon/main` at **`eb9b6cd`**, used three Luna reviewers and a Sol reviewer for the difficult safety questions, and checked the consequential claims in source. No tests, services, or Otto commands were run.

**1. Reduce the dependency graph to the following gates.**

First reconcile statuses against Git. PROJECTPIN, READYPIN, LABCAPTURE, ORPHANWORKER, KILLFENCE, COMPLETECITE, LIMITFD, MANUALDISPATCH, PACKPARITY and FAILCLOSED have landed. The tasklist still says “not started.” OWNERCOMPLETION, FACADEFD, CTLRACE and PERCH2C remain unlanded at the reviewed SHA. The latest recorded stage-2 diagnosis was **14/18 passing: three harness failures and one descriptor leak**. [Diagnosis and directions](${TRANSFER_ROOT}/portfolio/ops/requests.md:1373)

Keep these existing rows before CUTOVER:

| Row | Why it remains a gate |
|---|---|
| **OWNERCOMPLETION** | Ordinary concurrent starts can mishandle `OwnerCompletion` and return an exception. Finish the already prepared fix. |
| **CTLRACE** | Publishing a partial manager request can strand its caller. Small, already prepared, and affects the working control path. |
| **FACADEFD** | In-process facades eagerly allocate transports; the observed owner grew hundreds of descriptors during one run. |
| **SESSIONFD** | Session teardown leaves owned services alive. Fold overlapping per-call fixes into FACADEFD, but retain the session/thread/temp-directory acceptance checks. |
| **PERCH2C** | Required negative evidence: dependency ordering, changed-content refusal, actual capacity, descriptors and leftovers must be capable of failing. |
| **CAPTUREEDIT** | Ordinary `Edit` work can land and then settle `unknown`; current capture accepts only `Write`. |
| **FAILEDFENCE** | Provider failures can leave an unrecoverable project-wide fence. Raising the turn budget alone does not fix recovery. |
| **REALSTAGE3, REALSTAGE4** | Required real execution and landing evidence. Implement and run them as one campaign. |
| **REWORKWIRE** | Keep the promised repair workflow: retained lab, exact session, fresh authorization and bounded retries. The landed REWORK implementation is not wired into the product. |
| **DRAINSETTLE** | Queued completions can remain unresolved while `close()` joins their waiting threads. A live owner needs a safe stop/restart path. |
| **DONESETTLE** | Fold into landing integrity: revoke/settle within the owner operation before another queued tool call executes. “Feedback only” does not mean the check command performs no work. |
| **PINALL** | A failed durable process pin is swallowed before useful input. That permits work the owner cannot reliably recover or terminate. |
| **OWNERCLAIM** | The runner starts before home custody is claimed. A refused or dispatch-held startup must not already have launched retained work. |
| **RECEIPTFENCE** | A terminal-response write failure can make the scanner invoke the handler again. This is duplicate-effect risk. |
| **MCPPATH** | The token-bearing MCP helper must not import its implementation from the writable worker checkout. |
| **ADMITREVIEW** | Admission must resolve the exact review revision it records, rather than merely finding its identity. |
| **FAILCLOSED2** | Close ambiguous plan selection and permissive actor decoding before accepting live authorization records. |
| **GATESKIP — narrow scope** | Reject entirely skipped check files and identify omitted coverage. Rebuilding every legacy fixture is not itself a release gate. |

The row evidence is collected in the [current follow-up rows](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:108) and [audit triage](${TRANSFER_ROOT}/portfolio/ops/audits/20261017/TRIAGE.md:13). Particularly consequential source checks were the [capture restriction](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_adapter.py:66), [swallowed process-pin failure](${TRANSFER_ROOT}/source/otto/src/otto/agents/owner_runtime.py:46), [runner startup ordering](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1237), and [receipt failure cleanup](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1610).

Move these existing rows after CUTOVER, with the stated restriction:

| Row | Safe deferral and its limit |
|---|---|
| **ACTIVATEWHILE** | Activate projects while the owner is quiescent. The current global restriction fails closed. Remove “activate B while A runs” from pre-cutover acceptance; still demonstrate two already activated projects operating together. |
| **COMPLETEPIN** | Complete accepted reviews before unrelated plan edits; otherwise re-review against the current revision. The existing path refuses completion rather than accepting changed work. This accepts inconvenience, not weaker acceptance. |
| **STATUSCAP** | Cosmetic ceiling mismatch. Capacity proof must read the actual policy/admissions, not this incorrect aggregate field. |
| **UNTIME2** | Test scheduling improvements. Fix individual failures when they obstruct required evidence; do not block release on the whole cleanup. |
| **TESTPATCH** | Broad test reconstruction can follow. Required release scenarios must exercise real owner methods, including authorization refusals. |
| **DEADLAUNCH** | Uncalled entry-point deletion does not make the active owner safer at the boundary. Keep `run_turn` and `run_continuation`, which REWORKWIRE needs. |
| **CODEXOWNER** | Defer **Codex workers**, not Codex clients. Codex/r4 client reconnection remains mandatory. Keep Codex worker dispatch disabled until its owner journey passes, before SKEL/MANY. |

These distinctions follow the [triage’s constrained triggers](${TRANSFER_ROOT}/portfolio/ops/audits/20261017/TRIAGE.md:13). Its “after CUTOVER” column describes when defects surface; it is not automatically permission to defer them.

Keep **R1d, SKEL, MANY, REVIEW, UPGRADE, G3, LANES, DELETE, CACHE and RET** after CUTOVER as already arranged. Respectively they concern Astrid integration, broader host journeys, capacity tuning, final edition review, upgrades, guidance, transport replacement, cleanup, optional caching and long-term retention. Extract only the initial-install restart requirement from UPGRADE’s vicinity. [Existing sequencing](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:151)

The second audit wave mostly contains **proposals without task IDs**, rather than existing rows. Use `audit#finding` until they are assigned. Here is the complete disposition:

| Audit | Before CUTOVER | Defer, fold or drop |
|---|---|---|
| [INSTALLCUTOVER](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/INSTALLCUTOVER.md:3) | **CLIENT-CUTOVER:** explicit locator/binding inventory and per-client readback. **INSTALL-RESTART:** configure and prove restart of the qualified installation. | **SAVE-CWD:** code may wait if every transfer uses an absolute filename. **SHOW-COMPLETE:** code may wait only if verification independently enumerates every task/document and rejects incomplete pages. Their safety obligations cannot wait. |
| [AUTHORITY](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/AUTHORITY.md:3) | **#1:** fix cross-project retained starts through the shared manager-writable file lane. | **#2:** reserve distinct operator/owner/host/agent names in the release manifest; general collision rejection can follow. No admission-presence bypass was demonstrated by name collision alone. |
| [FILELANES](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/FILELANES.md:3) | **#1:** bound and validate relay responses; malformed JSON objects/types can unwind the shared owner. **#2:** fold crash-safe locator publication into OWNERCLAIM. | **#3:** fold terminal socket-receipt growth into RET. **#4:** incomplete stop explanation is diagnostic. **#5:** reused-PID recovery fails closed. **#6:** malformed status handling affects the reader; require valid fresh status during transfer. |
| [GITCUSTODY](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/GITCUSTODY.md:3) | **#1:** pin and merge the tested SHA before further bootstrap landings. **#2:** require durable landed-commit proof for completion of managed Git tasks. | **#3:** stop the landing queue on any push uncertainty and reconcile before continuing; defer automated reconciliation. **#4:** verified manual stale-lock recovery suffices. **#5:** preflight release checkouts; the final landing check already refuses wrong/dirty lines, so earlier product rejection is an efficiency improvement. |
| [CONCURRENCY](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/CONCURRENCY.md:3) | Fold **#1** into the PINALL/adapter work if practical. | Otherwise defer with bounded launch concurrency. Evidence supports registration failure before useful input, not demonstrated wrong-principal binding. Do not advertise reliable high-concurrency launches yet. |
| [STOREGROWTH](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/STOREGROWTH.md:17) | None on a fresh Store. | **A:** scope coverage before approaching 10,000 assessment events. **B:** instruction deduplication; **C:** status indexes; **D:** paged historical reads; **E:** retired projection reclamation—all post-cutover performance/retention work. Measure growth and bound initial load. |
| [CLISURFACE](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/CLISURFACE.md:3) | Validate the exact commands used by the release procedure. | **#1:** full parser/routing alignment; **#2:** obsolete sync guidance; **#3:** unused summary argument; **#4:** aliases; **#5:** inert gateway script; **#6:** flag naming can follow. Never solve #1 by broadly granting owner authority. |
| [UXREFUSALS](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/UXREFUSALS.md:5) | **#4** belongs in REWORKWIRE. Transfer automation must handle **#2/#3/#8** by reading terminal outcomes, retained receipts and state—not exit status or `provider_called:false`. | **#1:** manager recovery CLI can follow; uncertain projects remain held. **#2/#3/#8:** general response/exit cleanup can follow that explicit transfer discipline. **#5/#6/#7/#9/#10:** guidance and response-shape improvements. |
| [DOCDRIFT](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/DOCDRIFT.md:3) | **#5:** correct fake/real evidence claims now. The transfer procedure must supply **#3**’s required operator and **#2**’s admission steps. | **#1:** use verified pool configuration rather than the ignored manager-limit flag. **#2/#3:** general guides can follow. **#4:** duplicate of CLISURFACE #2; one task. |
| [DEADCODE](${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/DEADCODE.md:3) | None. | **#1:** Vision contract migration; **#2:** ORC packet removal; **#3:** advisor binder deletion; **#4:** Evidence toggle removal belong in SLIM/DELETE after consumer checks. |

Two new safety findings deserve emphasis. Managers receive the shared IPC write directory, while compatibility file requests bypass caller binding; retained routing then selects the project from the supplied schedule. That is a real isolation defect. Separately, landing persists acceptance **before** its final Git merge. The completion hazard is an inference conditional on the remaining review requirements being satisfied, but the ordering and missing Git predicate are real. [Shared write grant](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:441), [binding bypass](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1259), [acceptance-before-merge](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:177)

**2. Run the critical path in this order.**

1. **Freeze the release scope and repair the bootstrap SHA gate.** Reconcile actual landed rows; record every deferral and its operating restriction. Hard-stop subsequent landings after unresolved push failures.
2. **Finish the existing prepared fixes and run six independent work streams:**  
   - facade/session resource lifecycle;  
   - capture, process pins and failed-worker recovery;  
   - owner claim, drain and receipt handling;  
   - landing completion proof, settlement and rework;  
   - authority/admission/MCP boundaries;  
   - real-stage harness plus migration/install preparation.  
   Serialize changes within overlapping files and serialize landings. Six workers are a ceiling: the latest direction permits launches only above **25% free memory**. [Direction](${TRANSFER_ROOT}/portfolio/ops/requests.md:1389)
3. **Close stage 2 once on the integrated candidate.** Retain its negative checks. Avoid another broad audit after each isolated repair.
4. **Run combined stages 3–4:** real workers, Edit capture, runner evidence, exact-commit landing, conflict refusal, retained lab and bounded repair.
5. **Run combined stages 5–6:** real manager, failed check/rework, ask/answer to the exact session, changed-admission refusal, two preactivated projects, safe drain/restart, cold-agent reads/save preview, and two genuine program tasks landed through Otto.
6. **Review that final candidate once**, with separate verdicts for the stage obligations. Fix demonstrated failures, then rerun affected scenarios.
7. **Install the exact qualified revision into the final local home.** Prove restart there. Prepare complete exports and diffs in parallel with earlier work.
8. **Quiesce, verify the final source snapshot, obtain the existing required user go, switch clients, stop the old owner, prove new-client operation, then authorize the exact deletion set.**

The missing harness work must be explicit. `perch.sh` rejects real stages above 2; the canary defines only 0, 1, 2 and 4; the manager wrapper always appends `--fake`. REALSTAGE3/4 do not implement 5/6. Add one combined **REALSTAGE56** deliverable and explicit real mode to the manager effect. [Real-stage refusal](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:803), [forced fake mode](${TRANSFER_ROOT}/portfolio/ops/stage-run.sh:34)

My effort allowance is:

| Work | Agent-hours, estimated |
|---|---:|
| Existing essential fixes, integration and landing | 10–16 |
| Additional safety gaps and initial restart | 7–12 |
| Consolidated real-stage harness | 5–9 |
| Live campaigns, review and first repair cycle | 8–14 |
| Transfer verification and cutover | 3–5 |
| **Rounded total** | **35–60** |

Six workers do not divide this by six: shared files, one landing queue, staging runs and review are serial bottlenecks. **12–24 elapsed hours** is a defensible planning range; another substantial real-worker integration failure can exceed it. The runbook’s old 13-hour estimate predates these findings, and its “30 minutes per focused day” measurement covered the first nine tasks—not the subsequent integration chain. [Original calibration](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:123)

**3. Merge evidence campaigns; retain distinct failure checks.**

- **Merge stages 3 and 4.** A real successful landing already exercises the lab, tools, runner and evidence path. Add conflict/repair cases to that campaign.
- **Merge stage 5 into stage 6.** Dogfood can demonstrate management, questions, rework and changed-plan handling while doing the two real program tasks. Those cases must be deliberately exercised.
- **Stop separately repeating stage-3 happy paths after stage 6 proves them on the same candidate.**
- **Keep stage-2 negative checks:** unadmitted content, dependency order, reserve/capacity, killed workers and resource cleanup are not implied by successful dogfood.
- **Keep a fresh-install/restart check and the actual stage-7 transfer verification.** Staging success proves neither the destination configuration nor migrated data completeness.
- **SKEL may shrink later:** the already demonstrated Claude journey need not be repeated wholesale. Cold Codex and cold-client discovery remain distinct evidence.

These are changes to review scheduling, not permission to mark skipped scenarios passed. The current stage contracts distinguish these obligations. [Stage definitions](${TRANSFER_ROOT}/portfolio/PLAN.md:397)

**4. Add these CUTOVER-specific protections; the current row does not specify them sufficiently.**

- **An exact preservation manifest.** CUTOVER says “six follow-ups”; there are **seven**: SLIM, EFFECTS, PACKS, HARNESS3, THROUGHPUT, ASTRIDFLEET and PROCLIFE. Include the program, r4 and every other upcoming project found by the authorized live inventory. Preserve project instructions, configuration, notes and document bodies—not merely task titles. [Seven-project plan](${TRANSFER_ROOT}/portfolio/PLAN.md:326), [stale CUTOVER wording](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:151)
- **A consistent final snapshot.** Listing and saving while r4 or another session continues editing leaves a race before deletion. Freeze source writes at the agreed boundary, or perform a final revision/hash comparison and repeat changed exports.
- **No duplicated in-flight work.** Re-saving plans does not migrate process custody or unknown-effect fences. Inventory unresolved old-owner occurrences; do not newly admit corresponding work until each is settled or explicitly dispositioned. Fixing new canon’s drain does not retrofit the running old owner.
- **Complete, independent readback.** Verify every task, dependency, criterion, document and required configuration using a recorded old-to-new identity mapping. `show project` returns one page with default limit 100; “outcome: read” is insufficient proof. [Implementation](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/show.py:32)
- **Every client locator and binding.** Host `client.json`, `--home`/`OTTO_HOME`, orchestrator connection files and issued bindings are separate. Reissue authority-bound bindings; do not just copy them. Each Claude, Codex and r4 client must prove the new owner identity and project scope, including after the old owner stops. [Independent home selection](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/cli.py:1757), [orchestrator locator](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/orchestrator_client.py:325)
- **A deletion boundary with recovery evidence.** Retain verified upcoming-project exports and the disposition manifest outside every deletion target. Verify the old process groups are gone, its restart mechanism cannot revive it, and destination documents/runtime dependencies do not resolve into old paths.
- **Switch before destructive reclamation.** Keep the old Store inert until the new owner has restarted and all client checks pass. Then delete the reviewed paths. “Free disk up ≥8 GB” is an observation, not a reason to broaden deletion if the measured reclaim differs.

This does **not** require resurrecting the full-Store migration or 7.7 GB rehearsal that D18 explicitly dropped. It requires proving the data the user chose to preserve survives deletion. [D18](${TRANSFER_ROOT}/portfolio/PLAN.md:96)

**5. Cut these from the plan entirely as separate work.**

- Separate stage-3 and stage-4 review ceremonies, and a separate stage-5 campaign when the combined dogfood campaign supplies all its evidence.
- A new task for every audit observation. Fold UXREFUSALS #4 into REWORKWIRE, FILELANES #2 into OWNERCLAIM, socket retention into RET, and duplicate sync-document findings into one documentation task.
- Building long-lived bootstrap push/lock recovery machinery immediately before retiring bootstrap. Keep the strict stop-and-reconcile procedure.
- CLI alias removal and flag renaming as release requirements. They do not protect this transfer.
- CACHE as committed work without measurements showing repeated checks; its own row is already conditional.
- Any further broad audit wave before the missing real-worker campaigns. Today the highest-value unanswered question is whether the actual manager/worker journey works.

This is a release-path recommendation, not permission to delete the old Store. The prohibited live locations were not inspected, so preservation and client-switch evidence still has to be produced before the user’s existing CUTOVER go point.