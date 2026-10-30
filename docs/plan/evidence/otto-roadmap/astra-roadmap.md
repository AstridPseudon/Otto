**Recommendation:** salvage the useful fixes, replace the edition-1/CUTOVER critical path, prove the REL Windows project on the thin path, then port the proven controls into Otto.

I read all nine reports and checked the decisive source paths, branch diffs and saved results at `a70b3f2`. No files changed; no tests, services or installations ran.

**1. In-flight work**

“Finish and land” means repair and qualify the task’s delta against current canon—not merge its old branch wholesale. The lab report’s large diff figures often include divergent canon history: BOOTCFG’s own delta is **5 files, +97/−11**, not 68 files. [Branch inventory](BRANCH-LOG.md:1)

| Branch · tip | Verdict | Reason and retained scope |
|---|---|---|
| `lab/BOOTCFG` · `b1227aa` | **Rewrite** | Keep reproducible installation and composition validation. Move launchd generation into an optional local-host adapter; cloud startup must work without it. |
| `lab/BOOTLAND` · `0c5a4c3` | **Rewrite** | Keep checked-SHA binding and remote publication reconciliation. Replace the bootstrap shell gate with the common receipt-backed land/publish operations. |
| `lab/CLIARGS` · `88b7a42` | **Finish and land** | Absent arguments must stay absent; retry authorization must hold. Diagnose the combined regression before landing. |
| `lab/DISTURB` · `72ffd63` | **Rewrite** | Retain restart, refusal, overlap and failed-start scenarios as portable acceptance tests. Do not preserve the entire stage-2 harness. |
| `lab/INTEG-PROCLIFE-PL3` · `4ea1ad0` | **Finish and land** | Durable reader custody and recovery are useful. Qualify every constructor/startup route, including the externally owned bridge. |
| `lab/LABPIN` · `416ab80` | **Finish and land** | Preserve task/lab/assignment binding. Repair capture and rework integration failures; the invariant remains necessary. |
| `lab/LANDBATCH` · `0a409e7` | **Drop** | Its complicated shell gate was superseded by integration runs and has recorded blocking findings. Keep **batch integration**, implemented through the simpler candidate workflow. |
| `lab/LANDPROOF` · `03efa57` | **Finish and land** | Keep assignment-bound proof, exact candidate checks and capture-before-cleanup. Repair the recorded custody/rework regressions. |
| `lab/OBSOWNER` · `50d46a3` | **Finish and land** | Authenticated caller observations and owned-child cleanup protect real boundaries. Isolate its combined failures. |
| `lab/PROOFDOC` · `673d3b8` | **Drop** | A test freezing the old RUNBOOK would preserve the wrong operating model. Replace it with incident-tested instructions. |
| `lab/REALSTAGE3` · `f296dd4` | **Rewrite** | Extract the real-worker journey and evidence assertions into the new operational canary. Historical stage numbering is expendable. |
| `lab/ROLEIDS` · `6454654` | **Finish and land** | Reject reserved-principal reuse before assignment writes. Fix integration rather than redesigning the invariant. |
| `lab/ROOTFILE` · `a4144ac` | **Drop** | Remove the stray `D19.md` during cleanup; do not preserve a special root-file gate. Enforce the task’s ordinary file scope. |
| `lab/STAGE2CLIENT` · `874e920` | **Finish and land first** | Fresh install advertises a missing executable. Retain installation, registration refusal and terminal-failure detection; diagnose its failing outside check. |
| `lab/TESTPATCH` · `7370386` | **Finish and land** | Real owner/socket/facade tests expose failures that mocks concealed. Repair integration without weakening assertions. |
| `lab/XFERMAP` · `ef7577b` | **Drop from this roadmap** | This is old-Store → new-Store CUTOVER machinery, **not git storage**. Reuse manifest/readback ideas in the later exporter. |
| `proj/slim` · `2df7571` | **Rewrite scope** | Harvest audited deletions, status simplification and generation fencing. Finish the replacement journey; abandon the arbitrary 25% quota. |
| `proj/packs` · `403182e` | **Rewrite scope** | Keep pinned role/model policy and context provenance. Reduce to one effective brief; defer domain kits and pack-product expansion. |
| `proj/effects` · `17da237` | **Finish and land bounded slices** | Native-turn and runner start claims/reconciliation are useful. Qualify unknown-outcome recovery; do not claim coverage of every external effect. |
| `proj/proclife` · `abe13f1` | **Finish and land remaining deltas** | Preserve exact process birth, durable cleanup and capacity holds. Reconcile with already-landed PL1/PL2 and lab PL3; it supplies evidence, not the liveness monitor. |
| `proj/throughput` · `8e2a97c` | **Finish TP3/TP6; drop remaining scope** | Focused feedback and actionable refusals help workers. Keep full qualification; defer caching and warm rendering until a measured bottleneck exists. |
| `proj/harness3` · `6e4a14b` | **Drop/defer** | No third CLI or authentic protocol evidence exists. Archive the onboarding documentation; a third provider is not required for the target. |
| `proj/astridfleet` · `f8d46ee` | **Close as a study** | Preserve its identity/receipt analysis. Do not turn the film-agent integration proposal into a prerequisite. |

The saved STAGE2CLIENT check actually failed—`harness-pool-within-limit` failed unexpectedly alongside the seeded conflict assertion. Other culprit reports remain open despite earlier LAND reviews. [Check output](otto/portfolio/ops/runs/STAGE2CLIENT/check.out), [authoritative resume queue](otto/portfolio/ops/requests.md:1818)

Project records also qualify “done”: SLIM’s live replacement route is blocked; EFFECTS’ cold reconciliation journey is unverified; PACKS still needs socket/staging qualification; THROUGHPUT reports **no production before/after measurements**. [SLIM](otto/projects/slim/.project/tasklist.md:14), [EFFECTS](otto/projects/effects/.project/PROJECT.md:24), [PACKS](otto/projects/packs/.project/PROJECT.md:66), [THROUGHPUT](otto/projects/throughput/.project/after.md:21)

**2. Q1 — the path**

Two necessary changes were understated by the investigators:

- **Canon actively dispatches automatically.** Product composition installs a candidate selector; the capacity tick invokes it. Delete that selection path while preserving execution of explicitly requested runs. [`product_service.py:960`](otto/otto/src/otto/hostctl/product_service.py:960), [`:1163`](otto/otto/src/otto/hostctl/product_service.py:1163), [`execution_host.py:1163`](otto/otto/src/otto/portfolio/execution_host.py:1163)
- **Worker `done` can trigger landing today.** Its wrapper reports “submitted,” but `LandingOwnerPort` invokes `LandingService.done`. Change it to submit evidence and wake the manager; managers choose integration batches. [`facade.py:99`](otto/otto/src/herzchen/fleet/tools/facade.py:99), [`landing.py:96`](otto/otto/src/herzchen/fleet/landing.py:96)

Target numbers below refer to the user’s 1–13. Deletion amounts are estimates of source removed, not quotas; dropped unlanded branches remove **zero** from canon.

*Phase 0 — replace the paused programme’s instructions*

| ID | Task | Why | Depends on | Tier | Done when |
|---|---|---|---|---|---|
| R0 | Freeze refs, evidence, unresolved effects and actual review spending; replace the resume queue with these dispositions. | 5, 12 | — | Normal | Every branch has a disposition; budgets retain prior usage; no paused operation silently resumes. |
| R1 | Define the pilot mandate and policy: outcome, real acceptance, scope/effects, delegated decisions, tiers, total/owner-away budget, reserved decisions. Use one planner → critic → orchestrator judgement pass. | 1, 10, 11 | R0 | Hard | One approved version governs tasks and briefs; changes explicitly identify affected work. |

*Phase 1 — the minimum thin path, for one cloud host and one programme*

| ID | Task | Why | Depends on | Tier | Done when |
|---|---|---|---|---|---|
| T1 | Add a small git journal: immutable records, one authenticated writer, expected-head updates, generation fencing and remote checkpoints. | 5, 13 | R1 | Super-hard | Two writers cannot both claim authority; a fresh session reconstructs state; disconnected execution cannot create unfenced effects. |
| T2 | Put **every role launch** through one gateway: explicit requester, model policy, capacity, budget reservation and durable launch intent. | 1, 6 | T1 | Super-hard | Concurrent starts cannot overspend; supervisor/reviewer launches count; an unbounded paid adapter is refused under a hard cap. |
| T3 | Make launch/check/land/publish tools append receipts; generate queue status, digest and handoff from them. | 5, 12 | T1, T2 | Hard | Each result names base, execution and candidate; missing outcomes remain unknown; no manager rewrites execution status. |
| T4 | Add one message interface with durable delivery/wake state, replies, resolution and assignment-generation routing. Expose worker `ask`, diagnostic execution and resume-with-log. | 2, 7, 9 | T2, T3 | Hard | A question wakes its manager; a reply reaches the right worker; duplicate delivery does not duplicate work. |
| T5 | Add declared exits plus an independent host monitor; observe first. Detect absent starts, dead sessions, expired promises and missing exits. | 3, 4 | T3, T4 | Hard | Each seeded incident produces one attributable nudge; repetition reaches the supervisor; unknown sessions are not treated as dead. |
| T6 | Add the cheap supervisor sweep, compact briefs, incident replay and outcome metrics. | 8, 11, 12 | T4, T5 | Hard | Supervisor nudges managers directly; only exceptions reach the orchestrator; replay distinguishes capability, state, execution and judgement failures. |
| T7 | Adapt the existing integration approach: batch candidate → diagnose/bisect regressions → qualify exact candidate → explicit land/publication. | 5, 10 | T3, T4 | Super-hard | Changed refs invalidate qualification; missing/skipped required evidence refuses delivery; lost publication replies reconcile safely. |

The thin path already has manager-requested execution and exit markers, but needs these additions. Its current dispatcher also pushes CI branches to a hard-coded owner repository while the manager guide describes product-repository Actions—**preflight must resolve that discrepancy**. [`dispatcher.sh:54`](astrid-plan-repo/tools/dispatcher.sh:54), [`MANAGER-CODEX.md:79`](astrid-plan-repo/MANAGER-CODEX.md:79)

*Phase 2 — prove the pilot before restructuring Otto*

| ID | Task | Why | Depends on | Tier | Done when |
|---|---|---|---|---|---|
| P1 | Run one real canary; prove cloud wake, shell/check, ask/reply, capped spending, cold restore and access to the Windows acceptance environment. | 4, 6, 9, 13 | T1–T7 | Hard | Each path actually runs through delivered tools; credentials, runner access and budget enforcement are demonstrated. |
| P2 | Run **REL-Windows** end to end; collect a week’s operational evidence. | 1–13 | P1 | Hard | Exact candidate satisfies the user path; stalls/questions recover; delivery, costs and gaps have receipts. |
| P3 | Judge the controls and freeze the proven interface. | 11, 12 | P2 | Normal | Each discretionary control has measured benefit/cost or is removed; unresolved false alarms prevent blocking enforcement. |

**Pilot scope:** FIX-W1…W6, COH-C14 and the corresponding exact-candidate release checks. Refresh the actual bases first; the Windows findings document is explicitly an **unimplemented spec**. Its order is W4/COH-C14 → W1 → W2 → W3 → W5 → W6. [`FIX-windows-install-findings.md:3`](astrid-plan-repo/plans/FIX-windows-install-findings.md:3), [`:56`](astrid-plan-repo/plans/FIX-windows-install-findings.md:56)

**Pilot acceptance:** on real Windows PowerShell 5.1, fresh install, stale-configuration update and repair use the delivered binaries; discovery succeeds; a real chat prompt receives a response; breaking the model command makes verification fail. Include W6’s recovery evidence. Model discovery alone does not prove “chat works.” Publication remains an explicit reserved decision. [`:81`](astrid-plan-repo/plans/FIX-windows-install-findings.md:81)

Measure natural stalls separately from injected recovery drills. Stop the project’s schedules when it closes; do not manufacture activity to fill the measurement week.

*Phase 3 — repair and port into Otto*

| ID | Task | Why | Depends on | Tier | Done when |
|---|---|---|---|---|---|
| O1 | Remove automatic task selection; make worker `done` submission-only. **DELETE ≈0.3–0.6K.** | 2, 10 | P3 | Hard | Ready work never launches without manager intent; worker submission never advances a project branch. |
| O2 | Finish STAGE2CLIENT, CLIARGS, ROLEIDS, OBSOWNER and TESTPATCH as isolated deltas, then integrate together. | 5, 9, 10 | P3 | Hard | Delivered client works; authenticated routes work; reported regressions are resolved against the exact candidate. |
| O3 | Reconcile LABPIN, LANDPROOF, PL3, remaining PROCLIFE and EFFECTS changes under one custody/effect contract. | 4–6 | O2 | Super-hard | Crash-before/after-launch, lost replies, stale generations and capture-before-cleanup preserve identity and never blindly repeat effects. |
| O4 | Port the mandate and all-role launch gateway; remove duplicated role-specific admission plumbing where superseded. | 1, 6 | O1, O3 | Super-hard | Manager task authorization works within mandate; stale policy/revision, reserved effects and exceeded budgets refuse before launch. |
| O5 | Port receipts, messaging, exit checks, monitor, supervisor and projections. **DELETE ≈2–4K** duplicate delivery/polling/projection code. | 2–8, 12 | O3, O4 | Hard | Same incident replays and cold-session recovery pass through Otto; no parallel authoritative status or message channel remains. |
| O6 | Land the reduced PACKS/SLIM instruction work and TP3/TP6; expose capable workers and task-sized turns. **DELETE ≈0.1–0.3K** duplicated compulsory guidance. | 9, 11 | O2, O4, O5 | Hard | Cold workers diagnose, ask, recover and submit using the documented surface; briefs identify their governing policy. |
| O7 | Port manager-owned batch integration and user-path qualification; incorporate rewritten BOOTLAND, REALSTAGE3 and DISTURB scenarios. | 5, 10 | O1–O3, T7 | Super-hard | Batch regressions are attributed; exact integrated candidate passes the installed journey; neither fake staging nor baseline parity substitutes for qualification. |

STAGE2CLIENT’s recovery is the first Otto repair, but **does not gate the thin-path pilot**. The saved baseline itself contains failures; “no new failures” is an integration criterion, not proof that the target user journey works. [`summary-base.json`](otto/portfolio/ops/integ/summary-base.json), [`integ.py:4`](otto/portfolio/ops/integ.py:4)

*Phase 4 — make cloud/git operation the shipped product and remove the old paths*

| ID | Task | Why | Depends on | Tier | Done when |
|---|---|---|---|---|---|
| G1 | Implement Otto’s git-backed control store and cloud host adapter; make any local database a rebuildable projection. | 13 | O4–O7 | Super-hard | Fresh cloud sessions recover assignments, receipts, messages and budget holds without an old machine’s Store or PID namespace. |
| G2 | Drain and export retained projects/effects, verify readback, then transfer writer authority once. Rewrite BOOTCFG around portable startup. | 5, 6, 13 | G1 | Super-hard | Every active identity and unresolved hold is accounted for; old and new writers cannot both act; rollback is defined. |
| G3 | Qualify the shipped Otto journey, then retire superseded paths. **DELETE ≈16–23K core source**, including SLIM’s audited subset; **≈8–12K additional ops/controller code** subject to caller audit. | 10–13 | G2 | Hard | Fresh cloud run delivers verified work, survives interruption and reproduces its digest; removed routes have no required callers; historical evidence remains readable. |

**Stop:**

- Automatic-dispatch work and the old “manager only handles exceptions” programme.
- Edition-1 completion and Store-to-Store CUTOVER as prerequisites for everything else.
- D19’s direct reviewer launcher and fixed stage-review ceremonies; preserve their decisions and spending history.
- Per-task full qualification repeated before batch integration.
- HARNESS3, domain-pack expansion, speculative caches/warm renderers and film-agent integration.
- Hand-maintained status copies, arbitrary deletion quotas and the blanket prohibition on deadlines.
- Deleting rare safety invariants merely because they caught nothing during one week.

**3. Q2 — the concrete end state**

Otto is a small control layer around manager decisions, execution adapters and durable evidence. **Git is the authoritative programme store; a persistent local Otto service is optional.** This requires real storage work: today the Store is SQLite and the documented host contract assumes one machine-owned service. [`store.py:1`](otto/otto/src/herzchen/kernel/store.py:1), [`host-onboarding.md:3`](otto/otto/docs/host-onboarding.md:3)

| Component | Responsibility |
|---|---|
| **Mandate and brief compiler** | Resolve owner policy, project mandate and task scope into a compact brief with provenance. Separate enforced constraints, checked obligations and judgement guidance. |
| **Launch gateway** | Authenticate the requester; recheck mandate/task/generation; select the policy-approved model; reserve money and capacity; record intent before calling an adapter. It executes manager choices. |
| **Host and execution adapters** | Start/resume/inspect/stop local processes or cloud sessions; own workspaces, diagnostic commands and exact execution identity. Local birth identity and cloud session identity are different adapter evidence. |
| **Git journal and projections** | One writer commits authoritative records using expected-head checks. Generate status, queues, handoffs and metrics. Retain artifact hashes and retrievable evidence; never commit credentials. |
| **Messages, wake and liveness** | Record messages, track delivery separately from resolution, coalesce wakes, inspect session health and declared deadlines. Its scheduler survives manager-session death. |
| **Supervisor** | Cheap hourly judgement over every active manager. Nudge directly; escalate recurring failures and decisions needing the orchestrator. |
| **Integration and qualification tools** | Build manager-selected batches, preserve exact source tuples, check the real user path, advance branches and publish only with the required authority. |

A hard dollar ceiling needs **enforceable bounded usage**, not merely post-run estimates. Reserve a conservative maximum before launch; retain uncertain charges until reconciled. Total and owner-away limits include supervisors and reviewers. Today’s accounting explicitly returns unavailable when pricing facts are missing. [`accounting.py:154`](otto/otto/src/herzchen/usage/accounting.py:154)

The following commands are the **proposed interface**, not claims about today’s CLI. CLI and agent tools call the same operations; tools mint request keys.

| Role | Commands/tools and authority |
|---|---|
| **Owner** | `otto approve`, `decide`, `policy revise`, `pause`, `status`. Approve mandates; decide reserved effects and gaps; inspect or steer whenever desired. |
| **Orchestrator** | `otto plan`, `run --role explorer/planner/reviewer`, `manager start/replace`, `message`, `status`. Judge plans and exceptions, allocate across projects, fix instructions. No lab edits or integration. |
| **Supervisor** | `otto sweep`, `show`, `message --kind nudge/escalate`. Read evidence and nudge; cannot dispatch project workers or land code. |
| **Manager** | `otto task`, `run`, `resume --log`, `answer`, `integrate`, `qualify`, `land`, `exit`. Author tasks within mandate, choose every dispatch, judge results and own integration. |
| **Worker** | `task`, `exec` or capable `check`, `ask`, `done`, `exit`. Diagnose and implement in assigned scope; submit evidence. No independent provider launch, publication or landing. |

Reviewing is a read-only run mode, not another permanent hierarchy. A plan or code review names one uncertainty and exact inputs. Recurrence without new evidence goes to the supervisor for simplification, deferral or escalation; a round limit never waives a genuine blocker.

The durable records are small and explicit:

| Record | Key fields |
|---|---|
| **Mandate/policy** | ID, revision, authenticated owner, outcome, acceptance scenarios, repos/branches, allowed effects, delegated/reserved decisions, tier mapping, total/away limits, effective scope, supersedes. |
| **Task** | ID/revision, mandate revision, outcome, dependencies, file/repo scope, acceptance, tier, assigned manager/worker generation. Execution state is derived. |
| **Run and exit** | Run/request ID, role/model, task revision, base tuple, host/session identity, generation, reservation, start acknowledgement, logs; exit kind, waiting-on IDs, expected times, next responsible party. |
| **Tool receipt** | Operation/key, authenticated actor, input digest, intent/start/result times, base/candidate, execution identity, environment, outcome—including unknown—artifact hashes, cost evidence, target ref. |
| **Message** | ID/thread/reply-to, sender, recipient assignment/generation, task, kind, needs-reply, declared deadline, delivery/wake acknowledgement, resolution and decision reference. |
| **Decision/review** | Question or uncertainty, exact inputs/candidate, verdict/reason, actor/authority, new evidence, recurrence, affected work, superseded decision. |
| **Candidate/delivery** | Exact repo→SHA tuple, required scenarios, result/receipt references, gaps, implementation state, verification state, owner acceptance, publication receipt. |

**Implemented**, **verified** and **accepted-with-gaps** remain distinct. Accepting a gap does not turn its missing test into a pass. A changed candidate loses the previous candidate’s qualification.

Every view says **“as of”** and names unknowns. False alarms and avoidable owner interventions require adjudication; the ledger can count labels, but cannot automatically know those judgements.

A day in the life, using illustrative budgets:

1. **09:00:** The owner approves REL-Windows: $200 total, $50 while away, three worker slots; publication, repins and verification gaps remain reserved. The orchestrator appoints the manager.
2. **09:10:** The manager chooses W4 and COH-C14. The gateway commits launch intents and reservations; tools record actual starts. Their completion wakes the manager, which chooses W1.
3. **10:00:** W1 asks whether a valid external command override should survive repair. The message is durable, but the manager’s session has died. Delivery remains pending.
4. **10:02:** The monitor detects the dead session and attempts the first nudge. Failed recovery reaches the supervisor; the orchestrator replaces the manager with generation 2. Existing worker identities and reservations survive; generation 1 cannot act.
5. **10:10:** The replacement reads the generated handoff, answers from the mandate, and resumes the exact asking worker. The reply is delivered and the question resolved. No owner status-chasing occurs.
6. **Afternoon:** The manager integrates a batch. One regression produces a worker resume with its log. The corrected frozen tuple passes Windows installation, update, repair, actual chat and the broken-command negative control.
7. **Delivery:** Otto marks that tuple verified. The owner approves publication; the publication tool confirms the remote result and records it. The digest shows evidence, spend, one recovered manager stall and zero unresolved gaps.

For **today’s core source**, my planning estimate is:

| Disposition | Rough share | What |
|---|---:|---|
| **Keep** | **45%** | Useful contracts, identity/provenance checks, work/dependency logic, host parsers, labs, runner, custody, exact-commit checks and usage capture. |
| **Rewrite/consolidate** | **35%** | Store coupling, owner composition, admission, messaging, attention, brief assembly, status and delivery orchestration. |
| **Delete** | **20%** | Automatic selection, duplicate control paths, obsolete controllers/adapters and superseded projections/ceremonies. |

Denominator: **118,314 non-test Python lines under `src`**, counted at `a70b3f2`; the quoted 129,158 includes embedded tests. These are design estimates, not audited deletion promises. SLIM presently demonstrates only about **1.2K net top-level portfolio lines removed against current canon**.

**4. Ten provocative statements**

1. **Manager dispatch is a deliberate tax.** Keep it because the owner values the judgement; measure what that judgement buys.
2. **A hard budget may require refusing a favourite model.** An adapter without enforceable bounds cannot honestly promise capped unattended spending.
3. **Git can be the store, but git authorship is not authority.** A forged “owner decision” file must grant nothing.
4. **A dead manager should be replaceable bookkeeping.** If replacing it requires reconstructing truth from prose, receipts still do not own the truth.
5. **Worker `done` must become less powerful.** Finishing a task is not permission to choose the integration moment.
6. **“Models loaded” is still weaker than “chat works.”** Acceptance must cross the last boundary the user actually experiences.
7. **An unknown effect is allowed to stop useful work.** Inventing a new request key to recover throughput is duplicate execution disguised as recovery.
8. **Cheap managers are a hypothesis, not a moral principle.** Escalate the model when measured judgement failures cost more than the saving.
9. **A control can earn its place without catching anything this week.** Rare-loss protection needs incident replay and risk evidence, not a weekly popularity contest.
10. **Otto should make itself less visible as it improves.** The owner should see decisions and verified outcomes, not a growing vocabulary of operational ceremonies.

**5. Investigator findings**

- **canon:** Relied on existing execution/evidence primitives; overruled its incomplete dispatch assessment—canon actively auto-dispatches—and qualified the apparently submission-only `done`.
- **labs:** Relied on task changes and culprit records; overruled blanket rewrites, XFERMAP’s git relevance, ROOTFILE’s gate value and misleading two-tip diff accounting.
- **slim:** Relied on blocked replacement and measured deletions; overruled finishing the original 25% scope as a roadmap objective.
- **packs:** Relied on exact pins and effective-context provenance; agree to shrink it; provenance alone does not create one governing policy.
- **effects-proclife:** Relied on the distinction between effect identity and process custody; neither provides general liveness or universal external-effect coverage.
- **throughput-harness-fleet:** Relied on honest blocked/unmeasured findings; retain TP3/TP6, close the study, defer the third host.
- **pause:** Relied on the newer failure artifact and resume queue; baseline-relative green is insufficient for product qualification.
- **target:** Relied on native turn-end and admission seams; overruled the “small extensions” framing where live auto-dispatch, spend enforcement and git storage require structural changes.
- **thinpath:** Relied on the manager-requested execution loop; qualify its portability and acceptance claims; importing Otto’s runner/landing stack is not a pilot prerequisite.
- **Additional boundary audit:** Confirmed bounded-provider admission and backend `ask`; a usable worker `ask` surface and all-role dollar enforcement remain unfinished.
- **Additional thin/git audit:** Confirmed script limitations, the unimplemented Windows spec and Store coupling; retain Store authority during transition, but the requested final state makes git authoritative.