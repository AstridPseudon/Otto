# Principles and runbook

**Evidence convention:** “Observed” means the transcripts, plans, manager records, or repo files directly record it. “Inference” means the rule is a process interpretation of those records. Confidence reflects how often a practice was exercised here: **high** means repeated evidence across phases; **medium** means a few examples or one substantial phase; **low** means it was proposed or tested only once. This retrospective supports practical rules, not controlled comparisons.

## Core principles

1. **Keep roles and authority explicit.**  
   **Rule:** The owner sets product direction and permissions; the orchestrator plans, guides, and unblocks; the manager owns the queue, worker dispatch, review, integration, and status. Record allowed actions for each role in the current handoff.  
   **Applies:** Throughout the program and especially at manager startup or replacement.  
   **Why:** The owner repeatedly restated that the manager should execute and the orchestrator should “guide” it; Opus was assigned implementation before the owner narrowed its role to final review and taste work. [10-27 02:52; 10-28 01:29–01:40, 02:08; `ORCHESTRATOR.md`] **Inference:** Written boundaries help prevent role drift, but need to be present in the actual brief.  
   **Confidence:** High.  
   **Counter-indication:** In a small one-off task with no manager or worker layer, a separate orchestration role may add overhead.

2. **Start with the owner’s outcome and constraints; verify the code before scoping work.**  
   **Rule:** Capture the user problem, intended end state, constraints, non-goals, and owner decisions first. Then inspect the relevant code and tools at named, current revisions before estimating or assigning tasks.  
   **Applies:** Intake, exploration, and any plan that depends on existing behavior or external tools.  
   **Why:** The installer kickoff began from a user complaint and constraints, but the first audit used a source snapshot 127 commits behind `main`; checking current source reversed conclusions about PATH and skill syncing. Later, a remote manager lacked Codex setup even though local Codex worked. [10-26 00:54–01:14; 10-28 10:31–10:44; `out/w2-setup-explore.md`, `out/w2-tooling-friction.md`] **Inference:** Separate “what does current code do?” from “what should the product do?”  
   **Confidence:** High.  
   **Counter-indication:** Skip broad exploration when the request is a narrow, well-specified change and the relevant code path is already verified.

3. **Make a plan executable before activating its queue.**  
   **Rule:** The plan names the end state, phase boundaries, dependencies, authoritative queue, current code base, and deferred work. Each task has an approved “Done when” and the evidence that would prove it. Reconcile documents before dispatch.  
   **Applies:** Before manager kickoff and whenever a ruling changes scope, sequence, baseline, or acceptance.  
   **Why:** Cold-start reviews found missing pass criteria; the process then required manager approval of proposed criteria. During rebase, the plan still said “replay” and “repin” after those rulings changed, until the owner challenged coherence. [10-26 19:59–20:06; 10-28 09:58–10:21; `out/w2-verification.md`, `out/w2-decisions.md`]  
   **Confidence:** High.  
   **Counter-indication:** Do not force a complete task inventory before a discovery phase whose purpose is to reduce major uncertainty; keep that phase explicitly exploratory.

4. **Use second opinions to test both robustness and simplicity.**  
   **Rule:** Ask reviewers distinct questions: what real failure or missing safety check remains, and what can be removed without weakening the required safety floor? Treat findings as recommendations; decide which become tasks and record why. Bound review rounds and define when review ends.  
   **Applies:** Before executing a complex plan, at major integration seams, and during final review.  
   **Why:** Astra cut a proposed TST plan from 24 tasks to 17 after judgment-based revisions; a separate release-safety review found missing proof in a plan considered minimal. Three UPD review rounds produced fixes, while a planned deep check was skipped because recent reviews covered the same ground. [10-27 21:07–21:45; 10-26 21:37–22:24; 10-28 02:57–06:58, 05:51; `out/w2-reviews.md`] **Inference:** robustness and simplicity reviews catch different failure classes.  
   **Confidence:** Medium.  
   **Counter-indication:** Skip another review when it would repeat the same question against unchanged evidence; run final qualification instead.

5. **Break work into bounded tasks that exercise real paths; assign models from risk, not labels alone.**  
   **Rule:** Give each worker one task with scope, exclusions, owned paths, dependencies, real caller, tests, and required report. Match the model tier to complexity and consequence; when root cause is unknown, dispatch diagnosis before assigning an expensive implementation tier.  
   **Applies:** Queue construction and every dispatch or retry.  
   **Why:** Focused briefs helped, but fake/component tests missed composed behavior in COH-C3 and UPD-A2. Some apparent task difficulty was actually a broken worker launch; other apparent isolation failures exposed a real Runtime leak. [10-26 23:32–23:38; 10-28 14:16–15:00; `out/w2-worker-briefs.md`, `out/w2-models-cost.md`] **Inference:** root-cause uncertainty and verification cost should affect tiering alongside code complexity.  
   **Confidence:** Medium.  
   **Counter-indication:** Do not split tightly coupled changes so far that no worker owns proving the integrated behavior.

6. **Treat the manager brief as the current operating contract, and keep it lean.**  
   **Rule:** State the source-of-truth queue, phase goal, role boundaries, model policy, allowed actions, dispatch cadence, evidence rules, escalation triggers, and report format. Keep only current instructions in the operative brief; put history in a linked decision log.  
   **Applies:** At kickoff, after a standing process change, and on manager replacement.  
   **Why:** A specific “back-to-back” correction changed manager behavior quickly, but outdated or conflicting instructions also caused idling and model-role drift. Context reached 263K–281K tokens, with cost concerns and fresh sessions at phase boundaries. [10-28 00:34–00:39, 01:29–01:40, 01:57–03:57; `out/w2-manager-side.md`, `out/w2-antipatterns.md`]  
   **Confidence:** High.  
   **Counter-indication:** Preserve detailed constraints when a task is unusually risky; “lean” means relevant, not underspecified.

7. **Supervise the system’s state, not just the manager’s messages.**  
   **Rule:** Check session activity alongside queue state, worker and test liveness, recent landings, snapshot age, blockers, and next action. Dispatch available independent work immediately; process completed workers before launching more.  
   **Applies:** During active execution and long-running tests.  
   **Why:** Seven completed runs waited behind the manager; one initial wave’s workers had all failed their first command before the failure was noticed. Hourly checks also found sleeping containers and stale snapshots. [10-26 22:57–23:38; 10-27 17:58–17:59; 10-28 05:58, 13:03, 16:02; `out/w2-throughput.md`]  
   **Confidence:** High.  
   **Counter-indication:** Do not interrupt an expected long test merely because there is no code landing; inspect its process and log heartbeat first.

8. **Define verification against the question being asked, and make gaps visible.**  
   **Rule:** Name the exact base commit and runner. Classify each result as passed, regression, pre-existing, environmental, release-pending, or not run. A new test absent on the base is not “pre-existing” merely because it cannot run there. “Written, not run” is never a pass.  
   **Applies:** Every test claim, regression triage, platform qualification, and closeout.  
   **Why:** Comparing failures with the updater branch initially hid rebase regressions; checking `origin/main` corrected the baseline. New Pinokio tests needed separate treatment. Queued Actions jobs were not execution evidence, and closeout recorded 1,021 tests as hung/not run. [10-28 13:04–15:29, 16:00–16:13, 16:58, 20:56; `out/w2-verification.md`]  
   **Confidence:** High.  
   **Counter-indication:** If the task is not about regressions against a base, choose the relevant oracle instead, such as a product contract or external acceptance test.

9. **Report verified state and next action in a predictable format.**  
   **Rule:** Status and handoff reports state phase, what landed, active/blocked work, evidence and baseline, not-run checks, decisions made, owner decisions needed, cost when available, and next action. Mark the report “as of” a time and distinguish work completion from verification completion.  
   **Applies:** Check-ins, overnight digests, package delivery, and manager handoffs.  
   **Why:** The owner repeatedly asked whether work was progressing. The morning digest needed a correction to its test classification; successive zips also needed clear “replaces” notes and delta instructions. [10-27 15:12–20:36; 10-28 08:59–09:00, 16:13–20:39; `out/w2-communication.md`, `out/w2-tracking.md`]  
   **Confidence:** High.  
   **Counter-indication:** Routine check-ins can be shorter when no state changed, provided the live status record is current.

10. **Close with two reviews: what remains unsafe or unclear, and what was learned about the process.**  
    **Rule:** Before closing, review the integrated result for behavior, coherence, and unnecessary machinery; move unresolved structural or product questions to a bigger-issues list with recommendation and owner. Then record the retrospective findings, including process failures and evidence gaps.  
    **Applies:** Phase completion, handoff, or stopping a program.  
    **Why:** The elegance pass landed 12 cleanup tasks and parked a user-facing change; the final rebase pack recorded larger issues and 1,021 tests not run. [10-28 05:51–06:58, 20:38–20:56; `out/w2-reviews.md`, `out/w2-communication.md`] **Inference:** a declared closeout is safer when open product decisions and verification gaps survive the handoff.  
    **Confidence:** Medium.  
    **Counter-indication:** Avoid a separate elegance ceremony after a recent equivalent integration review; include that question in the existing review.

## Detailed practices by lifecycle stage

### 1. Intake and kickoff

- **Ask for the problem, user, intended outcome, constraints, non-goals, and owner decisions before task ideas.**  
  **Applies:** New project or newly expanded scope.  
  **Why:** The Windows complaint elicited concerns about unsigned scripts, startup, PATH, symlinks, and global skills; the constraints of consent and cross-platform support shaped the plan. [10-26 00:54–01:07; `out/w2-setup-explore.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** For a clear maintenance task, capture the request and move directly to code preflight.

- **Probe unknowns with narrow questions and required evidence.**  
  Ask one investigator to map the UI path, another the agent/runtime flow, another install/update/repair behavior. Require sources, findings, confidence, and unknowns. **Observed:** these probes produced distinct evidence; however, the requested Opus platform lead did not use Haiku subagents as directed. [10-26 01:07–01:26; `data/subagents.txt`]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not fan out when the same investigator can answer a bounded question quickly or the relevant files are few.

- **Preflight code and execution tools before committing to the proposed topology.** Record repo/branch/SHA, available runtime, authentication availability, worker launch path, test commands, external runner status, and permission boundaries. Test one dispatch through result collection. **Observed:** the first four Codex workers failed before reading code; remote Codex availability and GitHub Actions also differed from assumptions. [10-26 22:57–23:38; 10-28 10:31–10:44, 15:50–16:13]  
  **Confidence:** Medium.  
  **Counter-indication:** Reuse a recently verified setup when the same environment and permissions are still current.

- **Discover project conventions from current code, tests, and contracts.** Find the real caller path and existing test harness before proposing parallel helpers or new infrastructure. **Observed:** a realistic fake installer bypassed the repeated-install guard; F1e was narrowed to the actual TypeScript caller rather than a hand-built HTTP helper. [10-28 00:57, 10:57; `out/w2-worker-briefs.md`, `out/w2-decisions.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** If existing tests deliberately isolate a component, retain them and add a caller-level test only where the task’s risk requires it.

### 2. Planning

- **Create one approved plan and one authoritative execution queue per active project.** Keep the wider program roadmap separate; make paused, planned, approved, queued, and active states explicit. **Observed:** the UPD queue was the manager’s source of truth; TST was explicitly kept unqueued. Duplicate status narratives and stale plan references caused confusion. [10-27 21:07–21:50; `runs/QUEUE.md`, `runs/TEST-QUEUE.md`; `out/w2-tracking.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** A separate status view is useful when it is derived from the queue or clearly owns only program-level status.

- **Make task completion testable before implementation.** If “Done when” is missing, let the worker propose one and a proving command; manager approves before implementation. Include exclusions for unavailable platforms or upstream dependencies. **Observed:** this was added after cold-start review found missing pass criteria. [10-26 19:59–20:06; `out/w2-verification.md`]  
  **Confidence:** High.  
  **Counter-indication:** Exploratory tasks may have learning outcomes rather than product acceptance; define the report required instead.

- **Run a feasibility and simplicity pass before queueing.** Every proposed task should connect to a named user outcome, failure mode, release requirement, or necessary evidence. Cut duplicate matrices, audits, and infrastructure when they add no distinct check. **Observed:** Astra’s reviews reduced a 24-task TST draft to a 17-task plan and removed an audit sweep while retaining mandatory checks. [10-27 21:23–21:45; 10-28 16:48–17:11]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not cut a required safety or release proof simply because it adds work; the release-safety review found missing proof in a plan otherwise judged close to minimal. [10-26 21:37–21:43]

- **Keep phase and delivery boundaries explicit.** Specify what is paused, who owns external approvals, which branch/repos may be touched, and what artifact constitutes delivery. **Observed:** UPD was separated from paused installer work; the owner later directed “update the zip,” not execute the next project. [10-27 02:24, 19:15; 10-28 16:55]  
  **Confidence:** High.  
  **Counter-indication:** A single-repo, continuously integrated task may not need a separate delivery package.

### 3. Second opinions and simplification

- **Ask a reviewer to inspect exact current inputs and answer a focused question.** Good review prompts specify source revisions, intended user paths, contracts, accepted criteria, read-only/edit authority, output format, and finding threshold. **Observed:** stale-source review produced incorrect claims; focused later reviews found reachable defects and concrete cuts. [10-26 01:12–01:26; 10-28 02:52–06:58; `out/w2-reviews.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Skip independent review for trivial, low-risk changes with strong local tests and straightforward ownership.

- **Separate “find missing safeguards” from “remove unnecessary machinery.”** Ask each reviewer to name which failure a mechanism prevents and what evidence proves it. The orchestrator decides disposition and records accepted, rejected, partial, or deferred findings. **Observed:** robustness review found missing release-proof checks; over-engineering review removed redundant audit and matrix work. [10-26 21:37–22:24; 10-28 16:47–17:11]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not force two formal reviews when one reviewer can clearly answer both questions and the plan is small.

- **Set review caps and a stop condition before review begins.** One substantive review plus qualification may suit a test plan; a multi-repo integration may justify several fix-and-rereview rounds. **Observed:** UPD used three final rounds, while TST’s revised proposal reduced its review ceremony; a nearby deep check was skipped as duplicative. [10-28 02:57–06:58, 05:51; `out/w2-reviews.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Reopen a review if new evidence materially changes risk or uncovers a different failure mode.

- **Reserve expensive taste/review models for their authorized purpose.** Do not route implementation to a reviewer; turn findings into bounded worker tasks. **Observed:** Opus implementation assignments prompted repeated owner correction; the later elegance pass routed 12 tasks to workers. [10-28 01:29–01:40, 05:58–06:58]  
  **Confidence:** Medium.  
  **Counter-indication:** Use a reviewer model for a tightly scoped implementation only if the owner explicitly authorizes it and the task’s role is changed in the brief.

### 4. Task breakdown and difficulty/model assignment

- **One task should name one outcome, ownership boundary, dependency set, caller path, acceptance test, and report fields.** Include repository/base SHA, files, exclusions, and whether commits/pushes are allowed. **Observed:** scoped briefs aided manager review, but wrong checkout, missing adapter, and unrealistic fixtures were discovered after dispatch. [mgr1 00:45–01:01; mgr3 05:03–05:22; `out/w2-manager-side.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Split only when the pieces can be independently verified and integrated without obscuring the end-to-end owner.

- **Use dependencies and file ownership to parallelize independent work; keep the manager draining completed results.** **Observed:** back-to-back dispatch accelerated UPD; seven completed workers waiting showed manager capacity can be the bottleneck. Parallel work also created duplicate edits in a shared worktree. [10-28 00:34–00:36; 10-27 17:58–17:59; `out/w2-throughput.md`]  
  **Confidence:** High.  
  **Counter-indication:** Keep serial order where tasks share contracts, depend on unresolved design, or edit the same risky path.

- **Separate dispatch failures from implementation failures.** If a worker cannot execute its first command or inspect files, classify it as environment/dispatch failure, repair the path, and retry without escalating model tier. **Observed:** four first-wave failures came from nested sandbox limitations, later addressed by an external dispatcher. [10-26 23:32–23:38; `out/w2-tooling-friction.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Escalate model tier when the worker has started validly and evidence shows the task itself exceeds capability.

- **Treat model tiers as local policy, not universal difficulty labels.** Record both abstract tier and actual model/backend, reasoning setting, and fallback. For unknown causes, start with diagnosis; for costly or safety-critical changes, route up based on consequence as well as complexity. **Observed:** tier mappings changed between Codex and Claude; a purported product bug proved fixture-related while an isolation issue concealed a real leak. [10-27 20:54–20:55; 10-28 02:07–02:08, 14:17–16:04; `out/w2-models-cost.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not impose a multi-tier scoring rubric until you have enough task history to calibrate it.

### 5. Deploying a manager

- **Give the manager the approved plan, queue, and exact read order.** The brief should name source-of-truth files, current phase, startup action, queue authority, escalation route, and task-final format. **Observed:** successful manager handoff used a tested snapshot and cold-start brief; cold-start checks also exposed missing criteria. [10-28 00:06–00:23; 10-26 19:59–20:10]  
  **Confidence:** Medium.  
  **Counter-indication:** A new brief can be short if the manager already has the current plan and receives a delta handoff.

- **Include what the manager may decide and what needs owner authorization.** Define in-scope reversible rulings, product/scope decisions, external actions, and pause conditions. **Observed:** overnight autonomy worked for a bounded Runtime compatibility ruling, while bigger issues were held for the owner. [10-28 02:08–03:10; `out/w2-autonomy.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not pause for decisions the owner has explicitly delegated within the approved scope.

- **Leave out transcripts, full logs, and superseded rules from the active brief.** Link to durable evidence and summarize the current operative state. **Observed:** large context coincided with cost concerns; output hygiene and fresh sessions were introduced, though the records do not isolate savings caused by those changes. [10-28 01:57–03:57; `out/w2-antipatterns.md`]  
  **Confidence:** Low.  
  **Counter-indication:** Include the relevant excerpt when a decision depends on exact wording or a reviewer needs the original evidence.

### 6. Supervision

- **Default to an hourly orchestrator check during active work, with immediate escalation handling.** Each check asks: Is the manager alive and within limits? What changed since the last check? Are startable tasks idle? Are completed workers waiting? Are snapshots current? What tests are running, on which base, with what last output/ETA? Are there loops, scope drift, unsupported pass claims, model/cost drift, or an owner decision? What is the next expected event? **Observed:** this checklist is in `ORCHESTRATOR.md`; targeted messages restarted idle work and redirected inefficient test loops. [10-28 00:36, 05:58, 14:17, 16:58; `ORCHESTRATOR.md`]  
  **Confidence:** High.  
  **Counter-indication:** Stop or change the cadence when the owner changes operating mode or asks to turn reviews off; the owner did so at 18:09. [10-28 18:09–18:24]

- **Use a faster cadence during intense iteration only if it closes a demonstrated gap.** A prior proof-run playbook specifies 15-minute light checks during active iteration plus hourly full review. **This program did not show recurring 15-minute orchestrator check-ins:** the attempted manager self-wake was every 20 minutes while working/60 while waiting, caused idling, and was replaced by back-to-back dispatch plus hourly oversight. [`data/other-branches-process-docs.txt:748–756`; 10-28 00:35–00:36; `out/w2-supervision.md`]  
  **Confidence:** Low for 15-minute checks; high for hourly checks in this program.  
  **Counter-indication:** Do not add 15-minute checks when they merely duplicate an effective liveness monitor or pull the orchestrator into routine execution.

- **Use explicit intervention triggers, and label thresholds by evidence strength.** Observed triggers: manager idle with startable rows; result backlog; snapshot stale for two hours; long test silent beyond expected duration; contradictions between plan and rulings. A 2–5 minute first-heartbeat target is a proposed safeguard from the throughput analysis, not a tested threshold. [10-27 17:58–17:59; 10-28 00:36, 10:19, 13:03, 16:02; `out/w2-throughput.md`]  
  **Confidence:** Medium for observed triggers; low for the proposed heartbeat threshold.  
  **Counter-indication:** Do not intervene on lack of landings while a test or dependency is demonstrably progressing within its expected window.

- **Replace managers at phase, provider, or context boundaries with a verified handoff.** Save WIP, refs/base SHAs, queue state, landed work, evidence, blockers, not-run checks, permissions, cost/context, and next action; test a cold start and stop/archive the predecessor. **Observed:** a tested 140-ref export/import enabled a provider handoff; fresh phase managers reduced continuity burden, though snapshots still lagged. [10-28 00:11–00:23, 02:52, 09:59; `out/w2-supervision.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Keep the existing manager if it has fresh context, no provider limits, and can finish a small remaining phase more cheaply than a handoff.

- **Keep context hygiene proportional.** Store verbose output in files; keep queue rows, summaries, and decisions compact; snapshot after landings; rotate at phase boundaries when context or cost materially grows. **Observed:** 263K and 281K contexts coincided with cost concern; stale snapshots also concealed landings. [10-28 01:57–03:57, 05:58, 16:02]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not rotate mid-task if the manager holds important unsaved reasoning or a handoff would cost more than finishing.

### 7. Verification

- **For regressions, compare against the exact target base and preserve the comparison record.** Record base SHA, candidate SHA, command, environment, selected test IDs, and results on both. **Observed:** `origin/main` corrected the earlier rule that failures on the updater branch were pre-existing; new tests absent from the base required a separate classification. [10-28 13:04–15:29]  
  **Confidence:** High.  
  **Counter-indication:** A baseline comparison alone cannot establish correctness; it answers only whether the candidate introduced a difference.

- **Test the composed user/caller path named in “Done when.”** Prefer the project’s real harness and realistic fixtures. For a fixture-only fix, preserve assertions and demonstrate that the fixture models actual install state. **Observed:** COH-C3’s fake installer bypassed a guard; R8 fixture changes were accepted only with test-only boundaries and unchanged assertions. [10-28 16:04, 20:21; `out/w2-worker-briefs.md`, `out/w2-verification.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Component tests remain useful for isolating behavior; pair them with composed-path proof when the task changes a user workflow.

- **For order-dependent failures, find the smallest reproducer before a full suite.** Check the pair/file that triggers the failure, repair isolation or product behavior, then run one full suite. Bound runs with per-test and per-chunk timeouts; report remaining IDs as not run. **Observed:** roughly 70-minute full-suite runs preceded targeted isolation checks; the later bounded run explicitly reported 1,021 unrun tests. [10-28 14:16–14:17, 16:58, 20:56]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not infer an isolation defect solely because a test passes alone; investigate product state and test fixtures too.

- **Separate work status from verification status.** A phase may be implementation-complete but not fully verified. Identify queued, skipped, cancelled, environmental, written-not-run, and hung checks distinctly. **Observed:** CI push succeeded while Actions stayed queued; final rebase was closed with a substantial hung-test gap. [10-28 15:58–16:13, 20:56]  
  **Confidence:** High.  
  **Counter-indication:** If all required checks have real passing evidence, a simpler complete state is adequate.

### 8. Delivery and owner communication

- **Report the state in one compact update.** Include phase, completion by effort or rows with caveats, current activity, blockers, what passed/failed/not run, next action, and decisions needed. **Observed:** repeated owner status questions eased when replies named concrete work and the next phase, but status was often owner-prompted. [10-27 18:49–20:36; 10-28 01:41, 09:53, 15:48]  
  **Confidence:** High.  
  **Counter-indication:** Avoid routine digests when the owner requested manual updates only or no meaningful state changed.

- **For a replacement package, state version, superseded package, changed/unchanged contents, verification state, and recipient’s next action.** If recipient already has prior material, send a delta. **Observed:** several zips superseded one another; the owner clarified the manager already had earlier packs and needed an update to merge. [10-28 16:13–20:39, especially 16:55–16:57]  
  **Confidence:** Medium.  
  **Counter-indication:** For the first handoff, provide the full read-first package rather than assuming prior context.

- **Separate autonomous rulings from owner decisions.** For each open owner decision, state the question, recommendation, reason, consequence of deferring, and whether work can continue meanwhile. **Observed:** the overnight digest listed recommendations and owner issues; autonomy was explicit only within current scope. [10-28 02:08, 08:59; `out/w2-autonomy.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not ask for confirmation on routine choices already delegated or settled by written policy.

### 9. Closing

- **Before declaring delivery, verify the package itself and its source state.** Link the final commits/bundles, manifest, release note, tests, and exact limitations; label superseded artifacts. **Observed:** handoff packages were rebuilt several times and the 16:13 integration zip preceded completion of R8. [10-28 16:13–20:39; `out/w2-communication.md`]  
  **Confidence:** Medium.  
  **Counter-indication:** Skip package revalidation when no package is being transferred and the delivery is the integrated repository itself.

- **Close the queue only with explicit deferred issues and verification gaps.** Distinguish completed work from required future proof; give each bigger issue a recommendation and owner. **Observed:** the final pack named bigger issues and hung tests rather than claiming full verification. [10-28 20:38–20:56]  
  **Confidence:** Medium.  
  **Counter-indication:** Do not create a large “bigger issues” list for speculative findings; include evidence, relevance, and a clear reason to defer.

- **End with a retrospective tied to observed events.** Record which controls prevented errors, which failed, what was changed in response, and which conclusions remain uncertain. **Observed:** this run’s process changed repeatedly in response to dispatch failures, idle queues, context growth, stale evidence, and verification problems. [10-26 23:32–23:38; 10-27 17:58–17:59; 10-28 01:57–03:57, 13:04–16:58] **Inference:** this makes later process design evidence-led instead of treating every proposed control as proven.  
  **Confidence:** Medium.  
  **Counter-indication:** Keep the retrospective proportional; a small task with no meaningful process learning needs only a short closeout note.

## Source conflicts and limits

- **15-minute check-ins:** A prior proof-run playbook recommends light 15-minute checks during active iteration, but this program did not demonstrate recurring 15-minute orchestrator checks. Its manager’s 20/60-minute self-wake caused idle gaps and was replaced by back-to-back dispatch with hourly oversight. Treat 15-minute checks as an optional, unproven response to a real stall pattern, not a default. [`data/other-branches-process-docs.txt:748–756`; 10-28 00:35–00:36; `out/w2-supervision.md`]
- **Failure counts:** One transcript classification reports 82 + 10 + 5 against 87 IDs, which does not reconcile. Use the supported lesson—compare with the exact base and preserve per-test evidence—not the arithmetic partition. [10-28 13:04–14:17; `out/w2-antipatterns.md`]
- **Review intensity:** Three UPD end reviews produced fixes, but that does not establish three rounds as the right default. Reviews varied by project and stage; one TST plan favored a single substantive review plus qualification. Select the cap by risk, with a stop condition. [10-28 02:57–06:58; `out/w2-reviews.md`]
- **Confidence limits:** Most practices were tested within one owner-led program over three days. The runbooks from other programs support recurring patterns such as durable state and role separation, but they do not prove a universal cadence or model-tier mapping. [10-26–10-28 ledgers; `data/other-branches-process-docs.txt`]