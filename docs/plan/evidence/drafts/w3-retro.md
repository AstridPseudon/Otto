# What happened and what worked

## The program in one page

The program began as a review of a Windows installer complaint. It expanded into plans for cross-platform installation and release safety, then the owner paused those projects to prioritize the updater (UPD). UPD was completed on its branch, then merged onto the latest `main` across four repositories. The owner also requested a separate plan for cross-platform testing (TST) and a read-only analysis of Windows tester logs. Those became plans and a handover package; they were not implemented in this run.

**Cost caveat:** The cost log records manager-session totals, including sub-agents, but not a complete program invoice. Its session endpoints and the morning digest do not reconcile exactly. The recorded UPD and rebase manager sessions amount to roughly **$76**, excluding earlier Codex work and unmetered orchestration. The initial planning and Oct 26 Codex phase have no reliable total in the supplied records. [COST-LOG.md; `DIGEST-2026-10-28.md`; 10-28 08:59]

| Phase | What happened, agents and models | Rough cost and result |
|---|---|---|
| **Oct 26, morning: explore and plan** | The orchestrator examined the installer complaint, used Haiku probes and Astra/Opus reviews, and revised the plan after discovering its source snapshot was 127 commits behind `main`. The owner approved a simple default path, visible consent and zip delivery. [10-26 00:54–02:05; `out/w1-chunk-1.md`] | Cost not recorded. A usable plan and manager handoff were produced; no product implementation is shown in this phase. |
| **Oct 26 evening–Oct 27 early: launch release/installer work** | A Codex manager began stage-0 release-safety and installer tasks. All four first worker commands failed before doing work; an external dispatcher restored execution. Some tasks landed, but container restarts interrupted workers. [10-26 22:57–23:38; 10-27 00:01; `out/w1-chunk-3.md`] | Cost not reliably recorded. Several local tasks landed; hosted CI and real platform checks remained unverified. |
| **Oct 27: pause and pivot to UPD** | The owner paused the release/installer program and started UPD off `main`. A Codex manager ran the queue, with Luna/Terra/Sol tiers and Astra reviews. Container sleep and manager bottlenecks led to keepalive, recovery and “finished workers first” rules. TST was planned but explicitly left unqueued. [10-27 02:24–02:55; 17:58–17:59; 21:07–21:50] | Codex usage limit forced a handoff after a snapshot reported 54 completed rows. Cost for this earlier Codex work is not isolated in the final log. [10-27 23:58–10-28 00:00] |
| **Oct 28, 00:06–09:59: finish UPD** | Work transferred to a Claude Haiku manager, with Sonnet used for harder work and Opus eventually limited to final review and elegance work. Three review rounds and an elegance pass ran; final tests found regressions, which were fixed before the UPD queue closed. [10-28 00:06–02:08; 02:57–06:58; 09:53–09:59] | Recorded manager sessions total about **$62** through UPD queue close: $16.05, $19.62 and $26.24. The digest’s earlier “about $59” was an interim total. [COST-LOG.md; `DIGEST-2026-10-28.md`] |
| **Oct 28, 09:58–20:56: rebase and closeout** | A fresh manager merged UPD once per repo onto `origin/main`, kept existing pins, fixed confirmed regressions, and classified failures. GitHub Actions remained queued, and bounded agent-test runs still left 1,021 tests unrun. [10-28 09:58–10:21; 13:04–16:13; `REBASE-COMPLETE.md`] | Rebase manager cost: **$13.84**. Four-repo integration branches and a final handover zip were delivered; the manager was archived. The rebase was explicitly **not fully verified**. [COST-LOG.md; 10-28 20:38–20:56] |

**End state:** UPD and its rebase work were packaged for the owner. The rebase completion record names the repo tips and fixes, but says 1,021 agent tests “did not run (hung)” and marks Windows, macOS, CI and live GitHub checks “written, not run.” Release/installer projects remained paused, TST remained unqueued, and Windows tester findings were analyzed and specified but not fixed. [10-28 17:11; 20:38–20:56; `REBASE-COMPLETE.md`; `STATUS.md`]

## Scorecard

“Went well/badly” describes the observed result. “Rule” is the process rule suggested by that event. Root-cause explanations are marked **inference**.

| When | What happened | Went well / badly | Why | Rule it suggests |
|---|---|---|---|---|
| Oct 26, 00:57–01:14 | Installer analysis used a source snapshot 127 commits behind `main`; checking current code reversed PATH and skills conclusions. | **Badly:** rework before the plan was final. | **Inference:** no freshness gate. | Record repo and commit before analysis; reject stale evidence. |
| Oct 26, 01:23–01:26 | Owner corrected Opus’s assignment; the requested Opus-led Mac/Linux investigation did not use Haiku helpers. | **Mixed:** platform findings arrived, but delegation missed its mark. | Role and output were underspecified. | Name each reviewer’s role, sources, delegation and deliverable. |
| Oct 26, 19:59–20:06 | Cold-start review found missing “Done when” criteria and plan inconsistencies; docs were corrected. | **Well:** a fresh manager could execute more reliably. | Review tested whether the plan was runnable, not just readable. | Require approved acceptance criteria and a proving test before implementation. |
| Oct 26, 21:42–22:24 | Astra found release-safety blockers; owner separately asked for robustness and over-engineering reviews. | **Well:** the plan gained a hotfix path and safety floor, while some machinery was cut. | Independent reviewers checked different failure modes. | Separate safety review from simplicity review. |
| Oct 26, 22:57–23:38 | Four first-wave workers failed their first command; an external dispatcher restored execution. | **Badly, then well:** ~35 minutes passed before failure detection; workaround enabled progress. | **Inference:** dispatch had no start handshake. | Alert if a worker has not started within minutes; classify dispatch failures separately from task failures. |
| Oct 26, 23:58–Oct 27, 00:01 | Container restart killed workers; recovery resumed work from durable state. | **Mixed:** interruption, but partial work survived. | Worker and session lifetimes were fragile. | Persist task state and recover workers from the last checkpoint. |
| Oct 27, 01:06 | Deep check blocked INS-C1 despite manager marking it ready. | **Well:** review caught a real issue before landing. | Reviewer checked actual callers and behavior. | “Ready” needs evidence against acceptance, not just worker status. |
| Oct 27, 02:24–02:30 | Owner paused release/installer work, switched to UPD, and requested durable save. | **Well:** scope changed without losing the paused work. | Snapshot and explicit hold preserved state. | Make pause/resume and current scope explicit in the queue. |
| Oct 27, 04:59–05:35 | C1a was marked lost despite completed output; wrapper changes fixed exit reporting. | **Badly:** false loss states caused extra investigation. | **Inference:** state was inferred from process presence instead of durable exit/result. | One runtime should own heartbeat, exit code and recovery state. |
| Oct 27, 06:22 | Native Pinokio Stop/Quit veto was ruled outside UPD scope. | **Well:** avoided pretending Astrid could control upstream behavior. | Clear ownership boundary. | Defer dependencies owned by another project or upstream. |
| Oct 27, 08:44–10:21 | C2 went through repeated Astra fix rounds; review rounds were capped. | **Mixed:** findings improved work, but looping delayed closure. | No firm stop rule at first. | Set review-round limits and route residuals to a final review. |
| Oct 27, 12:01–12:12 | Orchestrator applied speed-up changes after asking about them, with no recorded owner reply. | **Ambiguous:** work sped up, but approval state is unclear. | Proposal and authorization were not distinguished. | Label proposals, approvals and autonomous decisions separately. |
| Oct 27, 13:02–16:06 | Hourly loop failed; owner saw a two-hour gap, and later no workers were running. | **Badly:** owner had to check liveness and restart work. | **Inference:** scheduled oversight was mistaken for continuous execution. | Show session, worker and trigger health separately; alert on missed checks. |
| Oct 27, 17:58 | Seven finished worker runs waited for the manager while one worker was busy. | **Badly:** review/landing, not worker supply, gated throughput. | Manager did not drain completed results first. | Process finished workers before dispatching more. |
| Oct 27, 21:23–21:45 | TST plan shrank from 24 tasks to 17 after Astra review and owner judgment. | **Mixed:** good cuts, but initial plan was oversized. | **Inference:** no minimum-scope pass before review. | Review the smallest plan that meets the stated confidence goal before queueing. |
| Oct 28, 00:34–00:36 | Manager stopped after one task and scheduled its own wake-up; owner required back-to-back dispatch. | **Badly, then well:** idle time ended after a direct correction. | Brief encoded pacing instead of continuous queue draining. | Dispatch ready work until all open tasks are explicitly waiting. |
| Oct 28, 00:37–01:40 | Opus was used for ordinary work/design; owner narrowed it to final review and elegance. | **Badly:** repeated role corrections and extra review of unchecked work. | Model policy drifted between handoffs. | Enforce role and model at dispatch; reviewers do not implement. |
| Oct 28, 01:57–03:57 | Manager context reached 263K then 281K tokens; cost rose sharply. | **Badly:** substantial spend accumulated in long sessions. | **Inference:** too much raw context and repeated output reading. | Keep briefs bounded; put logs in files; rotate at phase boundaries. |
| Oct 28, 05:58 | Snapshot omitted cleanup rows and already-landed work. | **Badly:** oversight relied on stale state. | Snapshot cadence depended on manager memory. | Checkpoint after every landing; display snapshot age. |
| Oct 28, 08:59–09:00 | Morning digest initially misstated ten Runtime regressions; correction followed a minute later. | **Mixed:** useful summary, but inaccurate test status. | Summary was sent before baseline classification was final. | Timestamp evidence and verify test classifications before digest delivery. |
| Oct 28, 09:58–10:21 | Rebase rulings said merge/no repin, but plan still said replay/repin; owner caught it. | **Badly, then well:** contradiction was fixed before execution. | Decision was not propagated to the canonical plan. | Update the source of truth as part of making a ruling. |
| Oct 28, 13:04–14:17 | Failure baseline changed to `origin/main`; 87 IDs were rechecked; full-suite bisects took ~70 minutes each before targeted isolation. | **Mixed:** corrected triage found regressions, but broad runs wasted time. | Old branch was the wrong baseline; tests were too broad for isolation diagnosis. | Compare to the exact target base; reproduce order failures with the smallest set first. |
| Oct 28, 15:27–16:13 | New Pinokio tests were first called pre-existing; CI jobs stayed queued; owner received a zip while tests were still running. | **Badly:** classification and CI status needed clarification; package was interim. | New tests were absent on base; push success was confused with CI execution. | Treat absent-on-base tests explicitly; separate pushed, queued and passed states. |
| Oct 28, 16:58–20:56 | Hung agent tests were bounded and recorded as not run; rebase closed with 1,021 tests unrun. | **Well for reporting; bad for coverage:** uncertainty was visible, verification incomplete. | Time limits allowed closeout but could not finish the suite. | Separate work completion from verification completion. |
| Oct 28, 16:36–20:39 | Multiple handover zips superseded earlier packages; owner clarified they needed a delta for an existing manager. | **Mixed:** durable packages, but version churn and recipient mismatch. | **Inference:** package version and recipient context were not explicit. | Each handoff should state what it replaces, what changed and what action is needed. |

## What worked: top 10 by impact

1. **Task queues made a large program executable.** UPD’s queue became the manager’s work spine, with dependencies, task state, acceptance and evidence links; it closed before rebase planning began. [10-28 09:53–09:59; `runs/QUEUE.md`; `out/w2-codified-process.md`]

2. **Approved “Done when” criteria made completion checkable.** A cold-start review found missing pass criteria; the process then required the worker to propose a criterion and test, and the manager to approve it before code. [10-26 19:59–20:06; `MANAGER.md`]

3. **Independent review found real integration issues and cut excess.** Deep review blocked INS-C1 despite a “ready” label; Astra cut TST from 24 tasks to 17; three end reviews found fixes before rebase. [10-27 01:06; 21:23–21:45; 10-28 02:57–06:58]

4. **The dispatcher turned an unusable worker path into productive work.** After four workers failed immediately in the nested sandbox, the external dispatcher let managers request dispatch and landing through files. [10-26 23:32–23:38; `tools/dispatcher.sh`]

5. **The owner’s scope changes were usually captured durably.** Paused work was saved before the UPD pivot; TST remained explicitly unqueued; rebase used a fresh manager and a separate queue. [10-27 02:24–02:30; 21:50; 10-28 09:58–09:59]

6. **Back-to-back dispatch and parallelism improved throughput.** After the owner’s 00:35 correction, the UPD sprint landed eight named tasks in roughly half an hour. [10-28 00:32–01:01; `data/plan-repo-gitlog.txt`]

7. **Exact baselines and honest labels improved test evidence.** `origin/main` comparison identified real regressions; release-pending, environmental and test-fixture issues were separated. Hung tests were labeled not run. [`REBASE-COMPLETE.md`; 10-28 13:04–15:29, 16:58–20:56]

8. **Narrowing work avoided out-of-scope fixes.** The orchestrator deferred Pinokio’s native stop behavior, kept pins stable during rebase and put schema digest changes in the release phase. [10-27 06:22; 10-28 03:10, 09:58–10:45]

9. **Fresh managers helped mark phase boundaries.** The UPD review and rebase phases each began with a new manager and explicit handoff; the cost log records session endpoints and context concerns. [10-28 02:52, 04:54, 09:59; `COST-LOG.md`]

10. **Durable snapshots and replacement notes preserved handoffs.** Bundles and run records supported Codex-to-Claude transfer; later zips stated which package they replaced. [10-28 00:06–00:23; 17:11; 20:38]

## What went badly: top 10 by cost to the owner

1. **The owner had to repeatedly ask whether work was alive.** They asked whether the loop was working, whether work was “cooking,” and whether everything was running; at one point the answer was “Nothing is running.” [10-27 14:56–16:06; 18:49; 19:46; 20:36; 10-28 00:34–00:35] **Root cause (inference):** no reliable live status combining worker health, task progress and next action.

2. **The owner had to repeatedly restate role boundaries.** They said the orchestrator should guide and the manager should do the work, then corrected Opus’s normal implementation assignments. [10-27 02:52; 10-28 01:29–01:40, 02:08] **Root cause (inference):** the active brief did not enforce roles or keep current policy clear across handoffs.

3. **A stale source snapshot led to incorrect initial analysis.** The first audit made wrong claims about PATH and skill syncing, then had to be corrected against `main`. [10-26 00:57–01:14] **Root cause (inference):** evidence was not pinned to a current commit before analysis.

4. **A broken dispatch path consumed a kickoff window.** Four workers failed before reading code; the failure surfaced about 35 minutes after launch and required new dispatcher tooling. [10-26 22:57–23:38] **Root cause (inference):** no dispatch acknowledgment or early failure alert.

5. **Session sleep and a missing hourly trigger interrupted work.** The owner expected hourly checks; the trigger was absent and the process slept, leading to restarts and visible progress gaps. [10-27 13:02–16:06] **Root cause (inference):** worker, session and schedule lifecycles were separate and unreliable.

6. **Manager bottlenecks wasted worker capacity.** Seven completed runs waited for manager attention; other times the manager stopped after one task to self-schedule a wake-up. [10-27 17:58; 10-28 00:34–00:36] **Root cause (inference):** queue progression was not enforced as a continuous drain cycle.

7. **Large context drove material model spend.** Manager context reached 263K–281K; the log called repeated context reads the main cost driver. Recorded manager spend through UPD was about $62, plus $13.84 for rebase. [10-28 01:57–03:57; `COST-LOG.md`] **Root cause (inference):** briefs, logs and session state were not kept compact enough.

8. **A wrong failure baseline triggered reclassification and rework.** Comparing failures to the UPD branch hid regressions; `origin/main` later showed failures needing fixes. [10-28 13:04–15:29] **Root cause (inference):** the baseline did not match the actual question, “did the rebase introduce this?”

9. **Broad test runs spent time without isolating the cause.** The manager used ~70-minute full-suite runs for order-dependent failures before the orchestrator directed smaller reproductions. [10-28 14:16–14:17] **Root cause (inference):** the plan lacked a diagnostic sequence and runtime limit for test isolation.

10. **Handoffs and plans needed repeated reconciliation.** The rebase plan contradicted approved rulings; multiple zips were superseded, and the owner had to clarify that they wanted a delta and the current assistant only updating the package. [10-28 10:19–10:21; 16:13–17:11; 16:55–16:57] **Root cause (inference):** decisions, plans, queues and package versions were not generated from one current state.

## Owner operating model

Observed from corrections, approvals and repeated requests:

1. **The manager owns execution.** The orchestrator guides, unblocks and checks; it should not take over implementation or routine review. [10-27 02:52; 10-28 02:08]
2. **Keep the queue moving.** Dispatch ready tasks back to back; do not stop for self-scheduled wake-ups while work is available. [10-28 00:34–00:36]
3. **Make progress visible without prompting.** Report what landed, what is active, what is blocked, what is next, and evidence of progress. [10-27 14:56–15:27; 10-28 01:41]
4. **Use model tiers deliberately.** Route routine, hard and very hard work by tier; keep Opus for final reviews and taste work after the owner clarified its role. [10-27 20:54–20:55; 10-28 01:29–01:40]
5. **Prefer a simple end state over exhaustive machinery.** The owner repeatedly asked for proportionate, elegant plans and review for over-engineering. [10-26 00:54; 10-27 21:09–21:45; 10-28 16:47]
6. **Get independent review where it can change a decision.** They requested Astra robustness and simplicity reviews, but expected judgment rather than mechanically accepting every cut. [10-26 22:18–22:24; 10-27 21:41]
7. **Prove claims against current code and actual user paths.** They asked for checks against `main`, coherent test strategy, and evidence that CI actually ran. [10-26 19:26; 10-28 10:19, 15:50–15:58]
8. **Compare failures to the correct base.** The owner wanted new failures only; rebase classification ultimately used `origin/main`. [10-28 01:52, 13:04]
9. **Keep plans and execution separate when asked.** TST was to be planned but not queued; later Windows work was diagnosis and specification, not implementation. [10-27 21:07–21:50; 10-28 16:24, 16:55]
10. **Make risk and missing proof explicit.** The owner accepted hard-to-reach gaps when named, and the closeout recorded unrun tests rather than calling them passed. [10-28 10:48–10:51; 20:56]
11. **Keep delivery and publication under the stated boundary.** Early work was to be zipped, not pushed to product repos; public CI use was separately authorized later. [10-26 01:52, 22:38; 10-28 10:59]
12. **When the owner is away, decide within scope and report later.** “No more questions” authorized routine judgment, with larger issues held for review. [10-28 02:08; `ORCHESTRATOR.md`]
13. **Adapt when priorities change.** The owner paused release/install work for UPD, kept TST inactive, and later turned off hourly review. [10-27 02:24; 21:50; 10-28 18:09]

## Surprises

- **More workers did not always mean more throughput.** Seven finished runs waited for the manager; after that, draining results and back-to-back dispatch mattered more than adding worker slots. [10-27 17:58; 10-28 00:34–01:01]
- **A shorter brief was not sufficient if its acceptance test missed the real caller.** COH-C3 had focused tests, but its mock bypassed a repeated-install guard; the review found the reachable failure. UPD-F1d also passed many tests while review found user-facing issues. [COH-C3 review; `out/w2-worker-briefs.md`]
- **A test failure was not automatically a product defect.** R8-F1 was a realistic-fixture issue: the product correctly refused an unproven stop. R8-F2 was a missing package in a test venv. But R7-F2 did expose a real file-handle leak. [R8-F1/F2 cause files; `REBASE-COMPLETE.md`]
- **The right review found both missing safeguards and excess safeguards.** Astra’s release-safety review added a needed coherence check; its TST review cut duplicate infrastructure. Simplicity and safety were not opposing goals in every case. [10-26 21:42–22:24; 10-27 21:23–21:45]
- **A completed phase was not a verified phase.** Rebase closeout was a concrete deliverable, yet 1,021 tests remained unrun and hosted/native checks were unverified. [10-28 20:38–20:56; `REBASE-COMPLETE.md`]
- **The stable part of the system was the ownership and evidence model, not the tools.** The run shifted from Codex to Claude after a quota limit, changed model tiers, and used custom dispatch/recovery scripts, while task IDs, queues, evidence and manager ownership remained useful. [10-27 23:58–10-28 00:23; `out/w2-codified-process.md`]