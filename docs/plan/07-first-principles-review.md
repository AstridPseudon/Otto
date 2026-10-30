> **HISTORY. This is not a current requirement.** This document is a first-principles review; its accepted findings are already in the spec. The current documents start at `START-HERE.md`.

# First-principles review (Astra) and my verdicts

**What ran:** Astra (gpt-6-astra, high) reviewed the whole effort from first principles: our retro, `05`/`06`, Otto's code and plans, and the raw transcripts. It returned 16 ranked findings with line-level evidence. The raw output is in `evidence/drafts/astra-first-principles-findings.md`.

**Caveat:**
- Astra says it used "seven Luna investigations", but its event log shows **no sub-agent calls**. It ran 33 shell commands itself.
- I spot-checked four load-bearing citations: `mgr4-digest:1100–1119`, `d19_watch.py:43–86`, `requests.md:1807–1813` and `main-full:8939–8944`. All four are accurate.
- The findings hold up, but they rest on one investigator, not a fan-out.

**Astra's reading of the goal**, which I adopt: *trustworthy progress with little owner intervention, within agreed scope, cost and quality.* Getting agents to follow instructions serves that goal; it isn't the goal itself. `06` had drifted into treating agent behaviour as the product.

## Verdicts

| # | Finding (short) | Verdict | My reasoning |
|---|---|---|---|
| 1 | `06` centres on behaviour and under-specifies delivery. Define acceptance through the real user path; keep separate states for implemented, verified, and accepted-with-gaps | **Accept** | Correct, and a regression on our own retro, which said "built ≠ verified". A perfectly obedient manager closed a queue with 707 tests unrun. |
| 2 | Turn-end checks can't detect a dead or hung process. Repetition needs a second event that may never come. Wake managers on completions; detect missing starts and overdue waits independently | **Accept, reshaped** | This is a real hole: a dead process never ends its turn. Waking a manager on events **isn't automatic dispatch**; the manager still chooses. Deadlines come from the agent's own declaration: an exit says "waiting on R7, expected by 14:30", and Otto nudges when that time passes. That's not a global timer. |
| 3 | Tools record their own receipts; managers shouldn't reconstruct the truth afterwards | **Accept** | `06` still had managers pushing snapshots, which is the stale-state failure we saw three times. Launch, check, land and publish each write their own record; views show "as of" a time and list unknowns. |
| 4 | Keep base and execution identity attached to evidence | **Accept** | Already a core principle (the base decides). Removal #3 in `06` must not throw away provenance with the vocabulary. |
| 5 | A limit enforced by one optional launcher isn't a limit | **Accept** | The watcher bypassed the review caps. Spend, model policy and launch accounting must sit at the one boundary every launch goes through: managers, workers, reviewers and supervisors alike. |
| 6 | A dollar budget can't replace delegated authority | **Accept** | I conflated the two. Replace per-task admission with a **mandate**: allowed outcomes, repos and effects, spend, and **reserved decisions** (publish, deploy, scope change, accepting verification gaps). Keep the revision check at dispatch. |
| 7 | Workers need diagnose-and-recover capability, not just editing (no shell, 8 turns) | **Accept** | This is exactly the trust-agents principle. Workers need a bounded shell or a capable `check`, a turn allowance sized to the task, and `ask`. |
| 8 | Not every failure is an instruction defect; reject "if Haiku can't run it, the instructions are wrong" | **Accept** | My statement was too absolute: the stage-2 hang was a missing binary, not a brief. Diagnose by layer: contradictory guidance, missing capability, stale state, execution failure, or a judgement error. A cheap manager stays the default assumption, not a law. |
| 9 | One message interface, but delivery, wake-up, resolution and authority need distinct meanings | **Accept** | Writing a file isn't delivery; I learned that when the hourly check went off. A message carries id, recipient, task, needs-reply and resolved state, and wakes its recipient. Owner decisions are authenticated. None of this belongs in a brief. |
| 10 | Risk-based review still needs a stopping rule that doesn't depend on money | **Accept** | My removal #5 dropped the round cap. Restore it in a better form: each review resolves one named uncertainty; the same issue recurring without new evidence goes to the supervisor to simplify, defer or stop; genuine blockers survive the cap. |
| 11 | Batch integration should remove repeated work, not qualification | **Accept** | Batch-then-bisect, then qualify the integrated user path on the exact candidate. The manager runs integration; the orchestrator doesn't. |
| 12 | Trial verification methods with measured catches, false alarms and cost; don't run hourly AI sweeps *and* orchestrator sweeps | **Accept, with a merge** | **The AI supervisor sweep *is* the hourly check:** a cheap model (Haiku or Luna) sweeps every manager, nudges directly, and passes only exceptions to the orchestrator. The Otto program already ran four Haiku helpers per check-in. The ledger counts nudges, catches and false alarms automatically, so measuring costs nothing extra. |
| 13 | Small compulsory core, the rest as guidance; the difficulty rubric contradicts itself | **Accept** | `03` called its rubric "judgement, not formula" and then gave it scores. Fix: the owner's tiers stay, a task is classed by its **hard invariant** (Megado's rubric is better than mine), and outcomes are recorded for calibration. Compulsory: outcome and scope, current inputs, who's responsible next, evidence and gaps. |
| 14 | "Enforce it or delete it" discards judgement guidance | **Accept** | Three classes: **hard constraints** (enforced), **observable obligations** (checked), **judgement guidance** (assessed by outcomes and sampling). Run the turn-end check in **observation mode first**, then make it blocking. |
| 15 | Prove one operational slice before making git storage or layer consolidation the foundation | **Accept the sequencing, push back on the base** | Agreed: no big migration first. But run the slice on the **thinnest path**: our file and git v0, plus a stop hook, plus the message files. That path already ran a 3-day program in cloud sessions. Don't run it through Otto's 129K-line stack. Then port the proven mechanisms into Otto. **The owner decides this.** |
| 16 | Removing compulsory owner work must not remove voluntary steering | **Accept** | My "the owner touches exactly three things" was wrong as a ceiling. Correct version: the owner *never needs* more than approve, decide and read, and can always drill down, steer, pause or change policy. A policy change applies explicitly to affected work. |

**Nothing rejected outright.** My pushback is in #2 (deadlines come from the agent's declaration, not global timers), #12 (merge the supervisor into the check-in) and #15 (the slice runs on the thin path).

**What Astra didn't cover:** the owner-away spend ceiling, and how the plan → critic → judgement pattern gets supported by the tool. Both stay as they are in `02`/`03`.

## Revised end state (supersedes `06` where they differ)

**Goal:** trustworthy progress with little owner intervention, within agreed scope, cost and quality.

1. **Mandate.** The owner sets outcome, acceptance (the real user path), scope (repos, effects), budget, and reserved decisions. Within it, managers authorize their own tasks. A policy change is an explicit event applied to affected work.
2. **Managers dispatch** (owner's stance, kept). Otto **wakes** the responsible manager when something it owns changes: a run completed, a question asked, a reply arrived, a declared deadline passed. Waking is not choosing.
3. **Turn exits are declared and checked:** `working` (on named runs, by expected times), `blocked` (with the escalation sent), `done` (with evidence), `handoff`.
   - **First** a mismatch with reality nudges the agent itself; **the second time** it goes to its supervisor.
   - The check starts in **observation mode** and becomes blocking once its false-alarm rate is known.
4. **A liveness monitor** catches what no turn end can: a run that never started, a dead session, a declared deadline passed with no new event.
5. **Tools record their own receipts** (launch, check, land, publish), with base and execution identity. Status, digests and handoffs come from those receipts: "as of" a time, unknowns explicit. No hand-kept snapshots.
6. **One boundary for every launch** (managers, workers, reviewers, supervisors) enforces model policy, spend and capacity, and accounts for it.
7. **One message interface:** id, sender, recipient, task, kind, needs-reply, resolved state, and a wake-up. Owner decisions are authenticated. Escalation runs on repetition, or on an unanswered reply past its declared deadline.
8. **The supervisor sweep:** a cheap model checks every manager hourly and nudges directly. Only exceptions reach the orchestrator, which handles judgement, priorities across projects, and fixing instructions. It never runs integration and never edits a lab.
9. **Capable workers:** a bounded shell or a capable `check`, `ask`, turns sized to the task, and resume-with-log after a failure.
10. **Verification:**
    - acceptance through the real user path, with separate states for implemented, verified and accepted-with-gaps;
    - claims sampled for spot checks;
    - batch integration, then qualification;
    - every review tied to a named uncertainty, with a recurrence stop.
11. **Instructions:** a small compulsory core (outcome and scope, inputs, who's responsible next, evidence and gaps), plus judgement guidance delivered when relevant. Briefs are tested by **replaying real incidents**, and a small live canary runs after setup changes. Failures are fixed at the right layer, not always by adding another rule.
12. **Measure what matters** from the ledger:
    - verified completion time;
    - avoidable owner interventions;
    - unattended stalls;
    - false alarms;
    - rework;
    - supervision cost.

    A control stays only if it earns its place.

**How to get there:**
1. Pick one real project.
2. Run it on the thin path (files on git, a stop hook in observation mode, message files, the supervisor sweep).
3. Measure for a week.
4. Port what earned its keep into Otto, deleting what Otto has that the slice didn't need.

## Astra's questions, with my proposed answers (yours to confirm)
1. **Which project shows success?** The REL program (FIX-W1..W6, GATE, COH): real, multi-repo, and with a user-visible outcome, which is a Windows install where chat works.
2. **What can managers decide alone?**
   - Yes: task creation and splitting within the mandate, model tier, integration onto project branches, and fixture-only fixes under the no-assertion-change rule.
   - No: publish, deploy, repin, scope change, and accepting a verification gap.
3. **Which environment first?** Cloud sessions with git as the store (what we have). It has persistence (git), wake-up (`send_message` plus scheduled tasks) and interruption detection (session status).
4. **The longest acceptable unattended delay?**
   - Failed start: 10 minutes.
   - Unanswered question: 1 hour.
   - Silent stall: the declared deadline plus 30 minutes.
5. **What keeps a control?** It catches at least one real problem a week on the slice, with false alarms under roughly a third of its nudges. Otherwise it goes.
