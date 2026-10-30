> **HISTORY. This is not a current requirement.** This document is principles and a runbook from that programme. **For the current build, `POLICY.md` replaces its operating rules** (model limits, spend ceilings, dispatcher files). The current documents start at `START-HERE.md`.

# Principles and runbook: running orchestrator → manager → worker programs

Distilled from the Astrid program (26–28 Oct 2026). It covers the orchestrator transcript, four manager transcripts, about 130 task run folders, 157 plan-repo commits, and process docs from three other programs. 16 analysis lenses produced the evidence; their reports are in `evidence/lenses/`, and timestamps below point into them. **Confidence:** "high" means the rule was tested repeatedly here; "medium" means a few times; "proposed" means it follows from an observed failure but was never run.

## The 12 core principles

1. **The owner's attention is the scarce resource. Spend it only on direction, not on status or drift.** About 20 owner messages asked "is it running / what's open / where are we", and about 17 corrected drift: role, model, pacing, stale plans. Only a minority were real product calls only the owner could make: the shortcut, the release paths, the testing decisions. Anything that makes status visible and stops policy drifting saves owner attention. *(High)*

2. **One job per role, enforced at assignment, not only written down.**
   - The **owner** sets direction, permissions and policy.
   - The **orchestrator** plans, equips, checks and decides escalations. It does no product work.
   - The **manager** owns one queue: it dispatches, checks, lands and reports.
   - **Workers** do one bounded task.
   - **Reviewers** read and judge; they never implement.

   The owner had to restate the orchestrator/manager boundary on 27 and 28 Oct, and correct Opus doing implementation (28 Oct 01:29–01:40). *(High)*

3. **The current policy lives in one place, and every brief and handoff renders it.** Policy covers model tiers, cadence, the review rules, permissions and the test baseline. Each manager handoff re-stated rules, and some arrived stale: the 20-minute self-wake pacing, Opus doing design, a rebase plan still saying "replay/repin" after the ruling said merge/no-repin. A ruling isn't real until the canonical plan and queue say it. *(High)*

4. **Managers drain the queue back to back. Check-ins observe; they don't drive.** Idle time came from a brief that told the manager to stop and self-schedule (28 Oct 00:34). Throughput was also lost when seven finished workers waited for one manager (27 Oct 17:58). The rule: process finished results first, then dispatch every startable task, and stop only when everything open is waiting on something named. *(High)*

5. **Verify against the code as it is now, at a named commit, before planning or judging.** The first installer audit used a snapshot 127 commits behind `main`, and its PATH and skills conclusions were wrong (26 Oct 01:12). Managers found wrong checkouts and missing adapters only after dispatch. *(High)*

6. **Planning pattern: cheap explorers → one strong planner → an over-engineering critic → orchestrator judgement → queue.** TST went from 22 Luna explorations to an Opus plan of 24 tasks, then an Astra over-engineering review, then judgement calls, ending at 17 tasks. The release-safety plan got an Astra blocker review, then an Opus elegance rewrite, then a robustness check and an over-engineering check. A single review that asks both "what's missing?" and "what can go?" is the default. Add a second only for a distinct risk. *(Medium-high)*

7. **Every added mechanism must name the failure it prevents.** Plans grew before they shrank: the 24 → 17 TST cut, the audit swarm that was dropped, about 850 lines removed by the UPD elegance pass. A mechanism that names no failure is cut. *(High)*

8. **Route by difficulty, keep reviewers expensive and rare, and escalate on failure, not up front.** Defaults the owner set:

   | Tier | Codex | Claude |
   |---|---|---|
   | Normal | Luna | Haiku |
   | Hard | Terra | Haiku at xhigh, then Sonnet after one failure |
   | Super-hard | Sol | Sonnet |
   | Review | Astra | Opus, only at the end |

   When the root cause is unknown, run a diagnosis task first. A fixture defect looked like a Super-hard product bug (R8-F1), and a "test isolation" flake hid a real fd leak (R7-F2). A worker that fails before touching code is an infrastructure failure, not a reason to escalate. *(Medium. The mapping is the owner's policy; its cost-effectiveness wasn't measured.)*

9. **Evidence vocabulary is fixed, and "done" is two states: built and verified.**
   - The base you're merging into decides what is pre-existing.
   - A new test that fails is a regression.
   - "Written, not run" is never a pass.
   - Pushed ≠ queued ≠ ran ≠ passed.
   - A hung test is "not run", with its id recorded.

   The wrong baseline hid regressions (28 Oct 13:04), and CI that "worked" was only ever queued. *(High)*

10. **Debug narrowly, then run the full suite once.** Two 70-minute full runs were spent bisecting order-dependent failures before isolation found the leak (28 Oct 14:17). The one-hour agent run hung silently until it was given per-test timeouts and bounded chunks. *(High)*

11. **Rotate managers at phase boundaries, with a handoff tested by a cold start.** Context reached 263K–281K tokens while spend jumped. The export/import that verified all 140 branch tips made a Codex → Claude transfer painless (28 Oct 00:11–00:23). Snapshots must be pushed after every landing; they were stale three times. *(High)*

12. **End with a bounded review, a bigger-issues list for the owner, and a retrospective.**
   - Big builds get at most 3 review rounds plus an elegance pass, run by workers. UPD's rounds found 7 blocking issues; the elegance pass landed 12 cleanups.
   - Plans and test infrastructure get one review, then the real qualification run.
   - Structural "gremlins" go on the owner's list, not into silent fixes.

   *(Medium)*

## Runbook by stage

### 1. Intake: questions to ask of a new project

- **The outcome:** what problem, for whom, and what end state? What would "done" look like to a user?
- **Constraints and non-goals:** for this owner, "don't over-engineer", consent, cross-platform, and no pushes to `main`.
- **Mode:** investigate, plan, implement, or package-only? The owner used all four and expected the boundary held. "Plan but don't queue TST"; "investigate the logs, don't fix".
- **What exists:** the current code at a named commit; existing tests and harnesses; conventions; prior plans or paused work this overlaps.
- **Feasibility of the tooling:** do the workers start? Is the runner available? Credentials? Can CI actually run? **Dispatch one worker end to end before fanning out.** Four workers failed silently for 35 minutes on 26 Oct, and Actions stayed queued for hours on 28 Oct.
- **Who decides what while the owner is away**, and the spend ceiling.

### 2. Explore
- Fan out cheap workers (Luna or Haiku), each with **one narrow question, required sources, and a report shape**: findings, evidence (file:line), confidence, unknowns. 3–22 explorers worked well.
- Label every claim reproduced or read-only.

### 3. Plan
A plan contains:
- the end state as a user journey;
- the shared contracts;
- phases and dependencies;
- tasks with tier and a one-line **Done when** (or "worker proposes; manager approves" when it's unclear);
- decisions taken, with alternatives;
- what's deferred and where it goes;
- risks;
- the authoritative queue path.

Then run the **one review** from principle 6, and record each finding as accepted, partial, rejected or deferred, with a reason. The orchestrator makes the calls; the reviewer advises.

**Ready to queue** means the plan, the queue and the brief agree: same task count, same review rules, no superseded instructions.

### 4. Deploy a manager
The brief holds:
- the phase goal;
- the source-of-truth files and read order;
- the current policy block (principle 3);
- what it may decide and what it escalates;
- the evidence rules;
- the report format;
- "work back to back";
- "push a snapshot after every landing";
- "verbose output goes to files, not into your context".

Keep it under ~30K tokens. Leave out history; link it instead.

**Worker brief:** task, repo@base and files; goal and exclusions; Done when (through the **real caller**); tests to run; report fields.

**Worker result:** status; what changed; checks (command → result, full output in a file); what wasn't run.

### 5. Supervise

**Cadence:**
- **Right after the first dispatch:** confirm a worker actually started.
- **Then hourly** while a manager is active.
- **Every ~15 minutes** only during intense iteration on a live problem. The owner's proof-run program used this; this program never needed it.
- **Stop or re-point the schedule** when ownership changes, for example the owner taking over the next phase (28 Oct 18:24).

Hourly checks earned their keep: the 00:36, 10:19, 14:17 and 16:58 interventions each caught a real problem. The one bad stretch (27 Oct 13:00–16:00) was the check itself not existing.

**The check-in questions** (from `ORCHESTRATOR.md`, sharpened):
1. Is the manager alive, and within its rate and context limits?
2. What landed since the last check? Is the snapshot newer than the last landing?
3. Is startable work idle, or are finished results waiting?
4. What's running long (tests, workers)? Is it making progress (last log line, expected end)?
5. Do claimed passes cite command, commit and base?
6. Is anything looping: a second fix on the same mechanism, or a third review round?
7. Has anything drifted: scope, model policy, plan versus rulings?
8. Cost since the last check: is it on plan?
9. Is there an owner decision pending?
10. What's the next expected event?

**Intervene when:**
- a dispatched worker shows no sign of starting;
- the manager is idle while work is startable, or finished results are waiting;
- the snapshot is older than the last landing;
- a long run is silent past its expected time;
- there's a second fix on the same mechanism (ask for a simplification proposal, not another patch);
- a third review round is coming without a stop rule;
- a manager's context is over ~200K tokens (rotate at the next phase boundary);
- a plan contradicts a ruling;
- policy drift: the wrong model on a task, or a reviewer implementing.

Every correction that should outlive the moment also goes into the brief.

### 6. Decide
- **The orchestrator decides** in-scope, reversible questions, quickly and with a reason: "build the route, it's in scope", "pin stays put", "the base decides", "stop patching piecemeal, one result contract".
- **Recurring heuristics:**
  - take the smallest change that closes the class of problem;
  - test the real caller;
  - don't build substitutes for work another project or upstream owns;
  - put each change in the phase that owns it (repins at release);
  - accept test-only fixes only when no assertion changes.
- **The owner decides:**
  - product behaviour visible to users;
  - release, pins and deploys;
  - external publication;
  - spend beyond plan;
  - starting or pausing projects;
  - structural "bigger issues".
- **Write every ruling** into the decision log and the affected plan or queue row before the next dispatch. Mark proposals, rulings and owner approvals distinctly. One speed-up change on 27 Oct was applied with no recorded owner approval.

### 7. Verify

Each test failure gets one class:

| Class | Meaning |
|---|---|
| regression | passes on the base, fails here; or a new test that fails |
| pre-existing | also fails on the base |
| environmental | caused by the machine or setup; listed once |
| release-pending | caused only by pins that move at release |
| not run | never ran, or hung; id recorded |

- Order-dependent failures are fixed by isolation, never by bisecting full runs.
- Long suites get per-test timeouts and bounded chunks.
- Fixture-only fixes are accepted only if no assertion changes and the fixture models a real install.
- Report "built" and "verified" separately.

### 8. Report and deliver
- **Status in one shape:**
  - phase;
  - landed / running / blocked / next;
  - evidence and baseline;
  - not-run items;
  - decisions made;
  - decisions needed (each with a recommendation and the consequence of waiting);
  - cost;
  - "as of" a time.
- **Packages:** a version, what they supersede, what changed and what didn't, their verification state, and the recipient's next action. Send a delta when the recipient already has the last one.
- **Overnight digest:** check that the snapshot is current and that test statuses are final, or marked provisional. The 08:59 digest needed a correction a minute later.

### 9. Close
Run the bounded review from principle 12, then:
- **Bigger-issues list:** each item with evidence, a recommendation, and who decides.
- **Done marker:** what's built, what's verified, what's not run, what's pre-existing, and what's open for the owner.
- **Archive** the managers and **disable** their schedules.
- **Retrospective:** use the method in `04-retro-method.md`.
