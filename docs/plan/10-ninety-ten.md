> **HISTORY. This is not a current requirement.** This document is the 90:10 option analysis; superseded by the spec and plan. The current documents start at `START-HERE.md`.

# The 90:10 path

**How this was made:** I framed three cuts, Astra (xhigh) ranked them against all 13 end-state points, and I checked its answer against the end state. Its full answer is in `evidence/otto-breakdown/astra-ninety-ten.md`. Astra again started no sub-agents.

## The answer
**Harden the thin path once and keep it as the control system.** It meets all 13 end-state points at one-owner scale, for **about 24 engineer-days** by Astra's estimate, or **30–35** by mine. It doesn't carry Otto's 118K-line codebase forward.

**A correction to the comparison:** the 137 days includes 29 days of Windows product work, which has to happen on any path. So the like-for-like comparison is **24–35 days against 108 for the system**, about a quarter of the effort. With the Windows fixes included, that's about **55–65 days against 137**.

| Option | Days (system only) | End-state coverage | Verdict |
|---|---:|---|---|
| **Harden the thin path** (Astra's pick, my Option 2 without the rewrite) | **24–35** | All 13 at one-owner scale; spend enforcement depends on a platform proof | **Recommended** |
| Otto-lite service (my Option 2) | 35–45 | All 13 | A new service adds little early value |
| Full plan | 108 | All 13, plus multi-host guarantees | Benefits arrive late |
| Process first (my Option 1) | 8–12 | Fully meets exits, the supervisor and manager dispatch; partly meets the rest | **The right first tranche, not a destination** |
| Otto-minimum (my Option 3) | 54–70 | No cloud or git; work unspecified | Last |

**What you give up:**
- carrying Otto forward;
- automatic controller failover;
- several writers at once;
- the full process custody work;
- the hardened Mac fleet;
- generic policy packs;
- automatic publication.

At one-owner scale, none of these is part of the end state.

## The scope (8 tasks of 3 days each)
| # | Task | Difficulty |
|---|---|---:|
| 1 | **Prove the platform contract and freeze the mandate.** Every paid entry point is bounded (including wake-ups and scheduled supervision), credentials are protected, the owner is authenticated, and scheduling is independent. **This is a go/no-go gate.** | 7 |
| 2 | One durable writer: operation IDs, an authoritative git append, replayable projections, and unknowns kept as unknown | 7 |
| 3 | One launch boundary for every role: reserve the budget and capacity before invocation, and reconcile afterwards | 8 |
| 4 | Tool wrappers that write receipts; capable workers (diagnose, `ask`, resume with log); status rebuilt from evidence | 6 |
| 5 | Messages and exits: a durable outbox, reply and resolution, generation checks; exit checks run in observation mode first | 7 |
| 6 | An independent monitor plus the cheap supervisor sweep and the metrics | 6 |
| 7 | Delivery acceptance: batches, attributing regressions, exact-candidate qualification, the three states, a review stopping rule | 7 |
| 8 | Qualify recovery (injected faults, restore into a fresh cloud session), a real canary, and a week of observation | 7 |

## Non-negotiable even at one-owner scale (and the cheapest way to keep each)
- **Owner authority can't be forged:** an authenticated platform identity, or decisions signed with a key agents never see. A git author name, or a "sender: owner" field, isn't enough.
- **Budget and capacity are real limits:** one serialised reservation ledger plus an enforceable bound per execution, covering every paid role and every wake-up. Polling the cost after the fact isn't enforcement.
- **Unknown effects aren't blindly repeated:** record the intent before invoking; hold and reconcile when unsure.
- **One active authority:** launch credentials stay out of worker shells, and there is no automatic takeover.
- **Evidence describes the actual candidate:** receipts carry full hashes, and a changed candidate needs new evidence.
- **Dead agents can't hide:** independent monitoring and visible overdue states.

## My judgement on Astra's answer
**I accept the recommendation.** It meets the end state point by point, and it's the strongest 90:10 on offer.

**Where I adjust it:**
1. **24 days is optimistic.** Every task was set to exactly the 3-day cap, and several are dense:
   - Task 2: a durable writer with replay and restart semantics;
   - Task 7: batching, attribution, qualification, the three states and a stopping rule.

   **Plan on 30–35 days.**
2. **A hidden infrastructure decision: where the broker runs.** Astra requires it to run independently of the orchestrator's container, and our cloud containers are ephemeral and get reclaimed. It needs a persistent host: a small always-on VM, a machine you own, or GitHub Actions on a schedule (weak). That isn't in the estimate. **Decide it in Task 1.**
3. **Get the value early.** Astra orders the tasks authority-first. I'd deliver the behavioural pieces in observation mode in week 1 (exits, the supervisor sweep, message wake-up; my Option 1, about 8–10 days), so the problems that hurt us stop sooner. Harden underneath after that. Nothing becomes blocking until Tasks 2–3 are in.
4. **Task 1 can fail on spend.** If a platform wake-up (`send_message`, scheduled tasks) can't be bounded, point 6 stays partial until wake-ups are routed through the broker with a bounded adapter. Every option faces this, including full Otto. Treat it as the first thing to prove.

## What would change the recommendation
- You need **Otto itself to continue** (then budget the port, about 108 days).
- You need several independent authorities, or automatic failover.
- Paid or irreversible effects **regularly** turn ambiguous.
- Cloud wake-up or monitoring misses the targets: a failed start caught within 10 minutes, a question answered within 1 hour, an overdue wait caught within 30 minutes of its deadline.
- The pilot week still shows status-chasing, owner repairs, false alarms or a high supervision cost.

## Decisions for you
1. **Harden the thin path instead of continuing Otto?** This is the strategic call.
2. **Where the broker runs** (an always-on VM, your machine, or something else).
3. **How owner decisions are authenticated:** a platform identity, or a signing key.
4. **Deliver the behavioural tranche in observation mode first** (my ordering), or authority-first (Astra's)?
