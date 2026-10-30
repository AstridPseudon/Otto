> **HISTORY. This is not a current requirement.** This document is an early assessment of fitting old Otto; superseded. The current documents start at `START-HERE.md`.

# Otto against the process we used: fit, friction, and the shape it should take

> **Superseded in part by `06-otto-end-state.md` (owner, 28 Oct).** No automatic dispatch: managers dispatch, and Otto makes them reliable with a turn-exit check and an escalation ladder. Push alerts become messages on one generic communication channel. The fit map and the cut list below still stand.

**Inputs.** The Otto transfer archive of 28 Oct: source at `a70b3f2`, `PLAN.md`, `AGENT-UX.md`, the Otto and Megado skills, the program's operating records, and seven follow-on project plans. Six Haiku explorers covered it: architecture, support docs, Megado, how the Otto program actually ran, direction, and the CLI/status surface. Their claims about defaults were spot-checked in source. The comparison is against `02-principles-and-runbook.md` and `03-minimal-structure.md`.

**Caveat.** The archive stops at the 19 Oct pause, so anything changed since then isn't seen here.

## Bottom line

1. **Otto's planned end state is right, and it matches what we learned.** `PLAN.md` §1 and `AGENT-UX.md` describe:
   - a plan lives in one place;
   - Otto dispatches ready tasks itself, and the manager is woken **only for judgement**;
   - workers get `task`, `check`, `ask` and `done`, and acceptance is Otto's run, never the worker's;
   - one capacity pool;
   - status is derived, never hand-kept;
   - "a project is a brief plus tasks";
   - an allowance on admission, so the owner isn't the bottleneck;
   - one `otto` command for people.

   That's almost exactly the structure our retrospective arrived at independently.
2. **What's built and installed today is far heavier than that end state.**
   - **Code:** 129K lines of source; the coordination layer (`otto/portfolio`) alone is 58K. Our whole process ran on about 330 lines of shell plus markdown.
   - **Guidance:** the role guides are mostly transport protocol: pins, request keys, compare-and-swap revisions, UNKNOWN receipts, adoption, six-pin refs.
   - **Defaults:** they make the owner and reviews into bottlenecks.
     - Only the project's user can admit a task, and any edit invalidates it.
     - Acceptance needs a review by default.
     - The worker gets 8 turns and no shell.
   - **Where it runs:** it only runs on one local Mac.

   Much of the planned simplification (SLIM, AGENT-UX rows 4–9) is scheduled *after* edition 1. Meanwhile edition 1 keeps building what SLIM will delete.
3. **The Otto program hit the same problems we did.** It used Otto's own process and ended paused, with ~70 of 205 tasks landed. That makes the shared lessons the strongest signal for what Otto must do natively (table below).
4. **To get to the middle:** make a **thin core** excellent and portable, and push everything else behind it or delete it. The core is the queue, isolated labs, check-then-land, liveness with push alerts, derived status, the policy, and spend. Keep the hard-won correctness: effects run at most once, acceptance comes from Otto's run, process custody. But hide it inside the tools instead of teaching it to every agent.

## Two programs, the same lessons

| Lesson | Astrid program (ours) | Otto program |
|---|---|---|
| Managers idle or bottleneck unless dispatch is automatic | 00:34 self-paced idling; 7 finished workers waiting | "An LLM manager does mechanical dispatch: one paid turn per dispatch" (AGENT-UX #4); hand-edited queue rewrites dropped tasks, so `ready.py` was added |
| Long manager context drives cost, so rotate | 263K–281K tokens, three rotations | Replaced at 266K, 198K and 210K; one resumed turn read 1.29M input tokens |
| Status kept in many places goes stale | STATUS.md, queue, snapshots, digests | At least 9 status locations; 184 of 205 rows stale |
| Policy drifts across handoffs and briefs | Opus implementing, pacing, plan contradicting rulings | Claude-era briefs overridden by `manager-codex.md`; run.json versus PLAN model drift; XHARD rubric differs between copies |
| The orchestrator slips into doing the work | Owner corrected it twice | About 25 sections where the orchestrator fixed things in a lab; one edit lost a commit |
| A budget written in prose isn't a budget | Opus drift; no spend ceiling | The watcher's 23 Astra calls bypassed the 5-call cap; the counter was unreliable; the Codex phase was never priced |
| Long or hung runs need state-based bounds | 1,021 hung tests; silent runs | Stage 2 hung for a day after time limits were banned; "never wait" was added after a worker spent $3.29 waiting |
| Per-task gates are slow; batch and bisect | 70-minute full runs to bisect; isolation instead | Per-task gates took 5–50 minutes; integrate-then-bisect landed 18 labs on one suite run |
| Fakes in harnesses hide real failures | Fixture defects (R8-F1/F2/F3) | Both stage-2 Opus FAILs were patched harnesses; POOL passed 93 tests and would have crashed in production |
| Reviews find real issues, but need bounds | 3 rounds found 7 blockers; plans cut 24 → 17 | ASTRA1/STAGE1 found real defects; an 11-stage review tree and 15 Opus calls were planned |
| Infrastructure friction dominates early | Nested sandbox dispatch, sleeping containers, missing trigger | Disk at 0 GB (9 hours lost), a heavy pool starved by other sessions, sandbox-blind checks |

## Fit map: our principles against Otto (built today / planned)

| # | Principle | Otto today | Otto planned | Verdict |
|---|---|---|---|---|
| 1 | Owner attention is scarce | Owner admits every task; pull-only status; no alerts | Allowance on admission (AGENT-UX #8); `otto wait` | **Contradicts today**; planned fix is right, and late |
| 2 | One job per role, enforced | Strong identity and authority model; managers can't be routinely dispatched; workers can't accept their own work | Same | **Covered**, but over-built (enrollment, adoption, scoped supervisor routes) |
| 3 | One current policy, rendered into briefs | run.json + operating brief + direction docs + skills (several sources) | PACKS: versioned policy packs; SLIM SL1: one instruction path | **Partial**; the plan is right |
| 4 | Managers drain back to back; check-ins observe | Manager does dispatch; no scheduler; "hourly oversight is a fallback" | Auto-dispatch (edition 2) | **Missing**; this is the single most valuable feature, and it's scheduled late |
| 5 | Verify against current code at a named commit | Admitted exact revisions; labs from the line; rebase at land | Same | **Covered** |
| 6 | Explore → plan → over-engineering critic → judgement | Megado lifecycle phases 1–2; pragmatic review; "judge every new layer by a current requirement" | Same | **Covered in the method**; the tool doesn't help with the explore and critic steps |
| 7 | Every mechanism names the failure it prevents | §15.1 "every task names what it deletes" | SLIM deletion ledger | **Good rule; not applied to Otto itself.** ASTRA0 Q4 asks for a governance-overhead measure that doesn't exist |
| 8 | Difficulty routing, escalate on failure | Binary normal/XHARD route; manager can reroute | Megado XHARD rubric (sharper than ours); second failure → XHARD/split/Opus (RUNBOOK §5) | **Covered**; adopt Megado's rubric. No automatic escalation; worker `max_turns` 8 is too low for Hard work |
| 9 | Fixed evidence vocabulary; built ≠ verified | Check pass/fail; acceptance separate from worker success; "unavailable is not zero"; lab versus base flake re-runs (TOOLING7/8) | Invariants (§17) | **Mostly covered.** Missing: "pre-existing on base", "release-pending" and "not run (hung)" as first-class outcomes |
| 10 | Debug narrowly; bound long runs | Runner with leases and exit codes; time limits banned (§17) | THROUGHPUT focused checks; integrate-then-bisect (`integ.py`) | **Partial**; needs per-test timeouts plus state-based stall detection, not "no time limits" |
| 11 | Rotate managers with tested handoffs | Six separate mechanisms (replacement, continuity, handoff, fresh_manager, steady_state, sense_check) | SLIM SL2: one `replace()` | **Over-built today**; the plan is right |
| 12 | Bounded end review + bigger-issues list | Assessment with findings and decisions; review-required by default; stage tree | Pragmatic-review table (0 reviews for directly verifiable work) | **Method right, defaults wrong:** the code defaults to review-required, and the program ran 11 stages |
| — | Liveness and alerts (idle, stalled, stale, silent) | Owner heartbeat; `stalled_manager`; `needs_orchestrator` view | — | **Partial.** No idle-with-ready-work or result-backlog detector; **no push of any kind** |
| — | Owner-facing status | `portfolio status`, `events overview/blockers` (pull, CLI) | `otto status/show/wait` | **Partial**; needs a pushed, human-shaped digest |
| — | Spend ceiling in dollars | Careful token accounting; prices only for 2 models; no dollar budget anywhere | — | **Missing**; the accounting is over-built and the enforcement is absent |
| — | Cloud and remote sessions | Unix sockets, peer credentials, launchd, APFS clones, local git; no cloud mode | — | **Missing.** Our program ran entirely in cloud containers, with GitHub bundles and branches as transport |
| — | Non-code tasks (explore, review, package, retro) | Checks are argv-only; free-text checks are refused | — | **Missing**; needs "report" acceptance |

## Over-built: cut or hide

1. **The protocol vocabulary on the agent surface.**
   - Today agents are taught about request keys, pins, compare-and-swap, UNKNOWN receipts, adoption, the six-field occurrence, and a JSON projection script just for reading a help reply.
   - Those guarantees are worth having. They belong inside the tools, not in every agent's head: Haiku managers can't carry them, and they crowd out the judgement guidance that actually mattered to us.
   - **Target:**
     - workers get `task`, `check`, `ask`, `done`;
     - managers get roughly `status`, `next`, `ask`, `answer`, `decide`, `replan` (within allowance), `review`;
     - the tools mint keys and reconcile unknowns; a refusal always carries `next:`.
   - AGENT-UX rows 5 and 6 already say this.
2. **Authority ceremony.**
   - Today: register, then queue, then activate, then adopt, then bind, as separate steps. Enrollment requests are approved by someone else. Direction is drafted, then adopted, then a continuation prepared. The scoped-supervisor route alone needs three operations, a revoke-and-reissue, and six pins.
   - **Replace it with one owner act:** approve a project. That records the scope, policy, allowance (money, routes, size cap) and who supervises it. Everything inside that runs without asking; anything outside it becomes an approval request.
3. **The defaults that create bottlenecks.**
   - Per-task human admission (`work/module.py:501`): replace with the allowance.
   - `scope_mode="review-required"` by default (`local_assessment_policy.py:42`): default to `check-accepted`, and pick reviews by risk using Megado's pragmatic table.
4. **The 58K-line coordination layer.**
   - Do SLIM's merges **before** edition 1, not after:
     - one instruction path;
     - one replace;
     - one status;
     - delete `native5_*`, `lifecycle.py` and the prepared controller.
   - Today edition 1 builds what SLIM deletes (direction report, tension 1).
5. **Usage accounting precision.** Physical-span deduplication, static-rate provenance and partial-window semantics, while no budget exists. Invert it: a simple dollar figure per session or manager, every provider priced, a ceiling enforced in the one launcher. Precise attribution can come later if calibration needs it.
6. **Six project documents.** Northstar, agent_goal, run.json, plan, tasklist, status → **brief plus tasks plus policy** (AGENT-UX #9). That matches our seven-file v0.
7. **Validation ceremony as a default.**
   - The per-landing D19 gate: each changed module's tests run alone twice, plus a staging restart, plus Opus on any assertion change.
   - The 11-stage review tree, and the 15 Opus plus 5 Astra caps.

   Keep "an assertion change needs a counted decision", which is cheap and valuable. Make the rest per-project policy. Prefer integrate-then-bisect batches with base-relative classification, which their own run showed is faster.
8. **Local-only machinery leaking into the design.** The APFS clone, launchd, flock/sysctl heavy leases and macOS write fences can all stay as **one host backend**. They shouldn't shape the core model.

## Missing: what Otto needs for this process

1. **Auto-dispatch in edition 1.** A task runs when it's admitted, its dependencies are accepted and a slot is free. The manager is woken only on a second failure, an `ask`, or a change outside the allowance. This one feature removes our biggest owner frustration (idle managers) and the Otto program's biggest manager cost (paid turns spent on mechanical dispatch).
2. **Push alerts on state**, not on age alone:
   - worker never started;
   - ready work with no worker running;
   - a result waiting for review;
   - a stalled manager;
   - a silent run past its expected end;
   - a second fix on the same mechanism;
   - spend over plan;
   - a pending owner decision.

   Deliver them to the orchestrator session and to the owner (one channel is enough). Otto computes some of these already (`needs_orchestrator`, `stalled_manager`); it just never tells anyone.
3. **A human-shaped status digest**, generated from the event log and pushable on a schedule or on change:
   - running, landed, blocked, next;
   - decisions needed, each with a recommendation;
   - spend;
   - "as of" a time.
4. **Schedules as a core feature:**
   - the first-dispatch check;
   - hourly while active;
   - faster while iterating;
   - automatically off when ownership changes.

   Today Otto's due records need a host automation to fire them, and none exists on the Claude side.
5. **Spend in dollars, enforced at the single launcher, for every provider,** with a per-project ceiling and an "owner-away" ceiling. Both programs had review calls bypass their caps.
6. **First-class test outcomes:**
   - **regression:** passes on the base, fails here; or a new test that fails;
   - **pre-existing:** also fails on the base;
   - **environmental**;
   - **release-pending**;
   - **not run (hung)**.

   Add per-test timeouts with the hung ids recorded, and integrate-then-bisect as the landing mode. Otto has the base-versus-lab flake re-run already; extend it.
7. **A remote mode.** Either a hosted owner service, or a "git-as-store" mode: queue, briefs, results and decisions as files on a branch, with bundles for handoff, which is what we used. **This is the biggest design decision for the owner**; see below.
8. **Task kinds beyond code:** explore, plan, review, package and investigate tasks, with report acceptance (a named output plus a reviewer or manager verdict) instead of an argv check.
9. **Worker capacity that matches Hard work.** 8 turns and no shell is too thin; our Hard tasks ran for hours with full test runs. Make turns and tools part of the route and policy, not hard-coded.
10. **Manager rotation as one operation:** compact state, a cold-start-tested brief, the same queue, triggered by a context threshold or a phase boundary.

## The middle: what Otto should look like

**Core (keep it small, make it excellent, make it portable):**
1. **Project:** brief, policy (roles, tier → model map, review policy, cadence, hard limits), allowance (money, routes, size cap), supervisor.
2. **Task:** outcome, files, dependencies, tier, Done when (an argv check *or* a report), state, `waiting on`, attempts, evidence, landed sha.
3. **Lab and line:** an isolated workspace per running task; check-then-land with a fast-forward merge; integrate-then-bisect batches.
4. **Run:** one agent session, with heartbeat, exit state, resume-with-log, and spend.
5. **Event log:** append-only; the source for status, digests, cost and calibration.
6. **Ask and answer:** a question pauses the task and resumes the same session with the answer.
7. **Schedule and alerts:** check-ins and state triggers, pushed.

**Agent surface:**
- **Worker:** `task`, `check`, `ask`, `done`.
- **Manager:** `status`, `next`, `answer`, `decide`, `replan` (within allowance), `review`.
- **Orchestrator:** portfolio status, approve, set policy, balance capacity across projects, rotate managers.
- **Owner:** digest, approvals, budget, start or stop.

**Kept from Otto's hard work (inside the tools, invisible to agents):**
- external effects run at most once, with reconciliation;
- process custody;
- admitted-revision checks;
- acceptance only from Otto's own run;
- one capacity pool with manager reserve and heavy headroom.

**Method stays in Megado** (pragmatic review, the XHARD rubric, the improvement loop). The tool's job is to **make the pragmatic path the default**. The Otto program had excellent written rules (Megado) and still ran heavy, because the defaults and the ceremony pulled the other way.

## Suggested sequencing for Otto
1. **Before resuming edition 1:**
   - run SLIM's merges and the AGENT-UX rows 4–6 and 8 (auto-dispatch, one command, refusals with `next:`, an allowance on admission);
   - flip the defaults (check-accepted, no per-task admission inside an allowance).

   That reduces what edition 1 has to stabilise.
2. **Add the alerts and digest layer, and the dollar ceiling at the launcher.** Small, and it fixes the most common owner pain in both programs.
3. **Decide the remote question** (below) before CUTOVER. It changes what "the owner service" is.
4. **Defer EFFECTS, PACKS, HARNESS3 and ASTRID-ON-FLEET** until a current requirement names them (Otto's own rule 15.1). Measure governance overhead per accepted task alongside heavy-seconds per task (ASTRA0 Q4).
5. **Dogfood** on a small real project with a low-ceremony policy (planning mode, zero model reviews for directly verifiable tasks, one end review) before running a program the size of Otto's own.

## Decisions for the owner
1. **Where does Otto run?**
   - Local Mac only. Cloud sessions stay outside, as this program did.
   - A git-as-store mode for cloud and remote agents. This is cheap, and proven by this program's bundles and branches.
   - A hosted owner service. Strongest, and a big build.

   Recommendation: **git-as-store as the portable base, with the local service as the fast backend.**
2. **Should edition 1 pause until SLIM's merges and auto-dispatch land?** Recommended: yes.
3. **Default review policy:** check-accepted with risk-picked reviews (recommended), or review-required.
4. **Should the owner approve projects with an allowance rather than admit tasks?** Recommended: yes.
5. **Should spend be enforced in dollars across providers?** Recommended: yes, with a separate owner-away ceiling.
