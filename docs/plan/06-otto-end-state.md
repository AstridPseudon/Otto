> **HISTORY. This is not a current requirement.** This document is an earlier end state for old Otto; superseded. The current documents start at `START-HERE.md`.

# Otto's end state: reliable managers, not automatic dispatch

> **Revised by `07-first-principles-review.md`** after Astra's review. The main changes: delivery outcomes, not behaviour, are the goal; a liveness monitor plus wake-on-event (managers still dispatch); tools record their own receipts; a mandate rather than only a budget; judgement guidance kept, not deleted; capable workers; a cheap supervisor sweep that is the hourly check; and a thin-path slice before any Otto restructuring.

**Owner correction (28 Oct), applied here:** no automatic dispatch. Managers stay the ones who dispatch. The problem in `05` was right and its solution wrong. The real job is **instructing agents and making sure they follow the instructions.** The same goes for alerts: one generic way to communicate and escalate, not a separate alert system.

## The idea in one paragraph
Otto is a **reliability harness for agents.** It compiles each agent's instructions, watches every turn end, and checks the turn against the project's state. When an agent stops short, Otto tells the agent. If it happens again, Otto tells the agent's supervisor, who finds out why and fixes the instructions. Everyone talks through one message primitive, and that same primitive carries warnings, questions, escalations, rulings and owner decisions. The orchestrator supervises *behaviour*, not code. The owner approves projects, answers decisions and reads a digest. Everything else is a bug.

## What it looks like in practice
1. **The owner approves a project.** One act sets the brief, the policy (roles, tier → model map, review policy, cadence, hard limits) and a dollar budget.
2. **The orchestrator starts a manager.** Otto compiles the manager's brief from three parts:
   - the **role guide**: short, judgement-focused, and the same for every manager;
   - the **policy**, rendered verbatim;
   - the **project brief and queue**.

   The brief is versioned, and its token count is measured.
3. **The manager dispatches:** `otto run T12 --tier hard`. Otto applies the policy (model, budget, lab) and records the run. The manager keeps the judgement: what to start, what to split, what to accept.
4. **Every manager turn ends with a declared exit,** one of:
   - `working`: waiting on named runs, with expected times;
   - `blocked`: on a named thing, with the escalation already sent;
   - `done`: the project is complete, with evidence;
   - `handoff`: context is full or the phase has ended.
5. **Otto checks the exit against reality.** It works like a stop hook with memory. If the manager says `working` while 3 tasks are startable and 2 slots are free, or ends with no exit at all:
   - **first time:** a message back to the manager, quoting the startable tasks: "dispatch, or say why";
   - **second time:** a message to the orchestrator with the turn's tail and the rule broken;
   - the orchestrator diagnoses the cause (brief bug, confusion, full context, a real blocker) and fixes the instructions or rotates the manager.

   The same pattern covers the other rules:
   - pushing the snapshot after each landing;
   - claims citing evidence;
   - the right model on each tier;
   - not ending while the project is unfinished.
6. **Workers use** `task`, `check`, `ask`, `done`. `ask` is just a message to the manager; the task pauses and the answer resumes the same session.
7. **One message primitive:** from, to, about (a task), kind (info, ask, warn, escalate, ruling, decision) and whether it needs a reply. Escalation is that same message moving up a level, triggered by **repetition or an unanswered reply**, not by elapsed time alone.
8. **The orchestrator's check-in** reads the behaviour ledger (rule breaks, escalations, unanswered messages) and the digest, and then exercises judgement. It's a heartbeat, not the main safety net.
9. **The owner sees:**
   - the digest (landed, running, blocked, next, decisions needed with recommendations, spend);
   - decision messages addressed to them;
   - nothing else.
10. **Store:** a git branch (queue, briefs, messages, ledger, results) works for cloud and local sessions alike. The local service is an accelerator, not a requirement.

## Ten provocative statements about the end state
1. **Otto's product is reliable agent behaviour, not execution.** Labs, landing and custody are plumbing. The thing worth building is the loop of instruct → observe the turn → correct.
2. **An agent turn that ends without a declared, true exit state is the defect Otto exists to catch.** Idle managers, silent stalls and premature "done" are all versions of it.
3. **Instructions are code.** A brief change ships only if a cheap model passes a handful of behavioural scenarios: dispatch back to back, end turns correctly, escalate properly, don't do the worker's job. A rule nobody checks is just prose; enforce it or delete it.
4. **There is exactly one way to communicate.** Warnings, asks, escalations, rulings and owner decisions are all the same message with a different `kind`. Alerts are messages Otto sends. Separate inboxes, help routes and advisor channels are what you get without that one primitive.
5. **Escalate on repetition, not on the clock.** First a nudge to self, then the supervisor, then the owner. "Twice" is the trigger; hourly checks are only a heartbeat.
6. **The owner touches exactly three things:** approve a project with a budget, answer decisions, read the digest. Anything else that reaches the owner is Otto failing.
7. **Managers should be cheap and boring.** The intelligence goes into the plan (a strong model, once), the critic (once) and the orchestrator's judgement on exceptions, not into the loop. If a Haiku manager can't run it, the instructions are wrong.
8. **"Done" is enforced, not hoped for.** Otto knows what done means for each task and project, and won't let a manager stop short of it without a stated, escalated reason.
9. **The orchestrator never touches a lab.** It edits instructions, policy and staffing. If it has to fix code, the system has a hole, and that hole is the real task.
10. **Otto runs anywhere git runs.** The store is a branch; a cloud session and a Mac session are equal citizens. Local-only machinery is an optional backend.

## Ten provocative statements about what to remove
1. **Herzchen as a separate "neutral platform."** Three layers with boundary tests, built for a second product that doesn't exist. Merge the model and the fleet into Otto until a second user appears.
2. **The authority ceremony.** Enrollment requests, adoption, binding, direction drafts, scoped-supervisor routes, six-pin refs. Replace them with one owner approval per project; agents are identified by their session.
3. **Exactly-once transport vocabulary in any brief.** Request keys, pins, compare-and-swap, UNKNOWN receipts. Keep the guarantees and hide them in the tools. If a tool can't hide it, the tool is wrong, not the agent.
4. **Per-task human admission, and review-required as the default.** The budget is the admission; a passing check is the acceptance; reviews are chosen by risk.
5. **Fixed review trees and call caps** (11 stages, 15 Opus, 5 Astra). One dollar budget and a review policy by risk. Count every call in the one launcher, or it isn't counted.
6. **Most documents.** Six project documents, nine status places, STATUS/DIGEST/COST-LOG kept by hand: replace with brief + tasks + policy, with everything else generated from the ledger.
7. **The heavy per-landing gate.** Staging restarts and every importing test run twice on every landing. Use integrate-then-bisect in batches, results classified against the base, and per-test timeouts.
8. **Six manager-rotation mechanisms.** One handoff: snapshot + compiled brief + cold-start check.
9. **Our own hand-built plumbing.** The file-request dispatcher (worktree, dispatch, land, sync and CI requests), keepalive, recover and watch scripts, and hand-written cost rows. A few `otto` verbs and one supervising process replace them.
10. **Hourly orchestrator check-ins as the primary safety net.** Supervision triggered by events from the turn-end check catches the real problems sooner; hourly stays as a heartbeat. The same goes for accounting precision without enforcement: count dollars and enforce them; drop the rest.

## Getting there from here (cheapest first)
1. **Prototype the turn-exit contract now, without Otto.**
   - A Claude Code **Stop hook** plus a ~100-line script that reads the queue and the manager's declared exit.
   - On a false or missing exit, it blocks the stop with a message. On the second time, it calls `send_message` to the orchestrator.
   - This session already showed the mechanism working: the stop hook that told me to push unpushed commits.
2. **Write the message primitive** as files on the store branch (`messages/<to>/<id>.md` with front-matter), plus the escalation ladder: self → supervisor → owner on the second occurrence or a missed reply.
3. **Compile briefs** from `POLICY.md`, a short role guide and the project brief. Write five behavioural scenarios and run them with Haiku before any brief change ships.
4. **Strip Otto's agent-facing guides** down to judgement and verbs; move the protocol into the tools.
5. **Make the git-as-store mode Otto's base.** Then cut, in the order of the removal list.
