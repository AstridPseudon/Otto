> **HISTORY. This is not a current requirement.** This document is a breakdown of finishing old Otto (137 days): **a path we did not take**. The current documents start at `START-HERE.md`.

# Otto roadmap: managers, tasks and difficulty

**How this was made:**
- Three Luna investigators mapped which Otto files each roadmap item touches, the pilot's files and overlaps, and which existing tests could prove each item done (`evidence/otto-breakdown/luna/`).
- Astra (xhigh) then broke the roadmap into managers and tasks. Its brief included my tentative takes, as hypotheses to challenge.
- The full task tables are in `evidence/otto-breakdown/astra-breakdown.md`: every task is 3 engineer-days or less, with subtasks, and every level is scored 1–10.
- **Astra again started no sub-agents** (0 sub-agent calls in its log), although it says it used "two Luna audits". The three investigators above were run separately.
- **One of its findings is wrong:** it says the product repos' `main` differs from the served commits. It read stale local `main` branches in my workspace. `origin/main` (`aadd0ff7`) is identical to the served `3204bb00`, so the fix spec's base statement stands. Ignore that finding.

## Managers and parallelism

| Manager | Owns | Starts | Days | Difficulty |
|---|---|---|---:|---:|
| **A, Otto canon and integration owner** | Phase 0; remove auto-dispatch and make `done` submission-only; land STAGE2CLIENT, CLIARGS, ROLEIDS, OBSOWNER and TESTPATCH; **the Otto merge queue and the edit leases on shared files** | Now | 14 | 8 |
| **B, thin-path controls** | Plan-repo `tools/` and briefs: launch routing, receipts, messages plus `ask`, exits plus monitor, supervisor sweep, incident replay, batch integration; the canary; judging the controls | Now | 18 | 7 |
| **C, Windows product and pilot** | Windows runner first; W4 and COH-C14, W1, W2, W3, W5, W6; exact-candidate qualification; the pilot evidence | Now | 29 | 8 |
| **D, custody and run-once effects** | Contract spike now; LABPIN, LANDPROOF, PL3, PROCLIFE and EFFECTS slices; cross-path fault tests | Spike now; implementation after A's lab landings | 18 | 8 |
| **E, instructions and worker surface** | Reduced brief contract, a SLIM audit, focused feedback and refusals; then capable worker tools and a cold-worker journey | Prep now; live wiring after F | 12 | 7 |
| **F, the control port** (**the same manager as B**) | Mandate, spend and capacity reservation, all-role launch gateway, receipts, messaging, monitor, supervisor, batch integration and publication, qualifying the Otto candidate | After the pilot is judged and A integrates D's work | 22 | 8 |
| **G, git authority** (conditional) | A fencing spike first; then the git writer, rebuildable projections, cloud adapter, export and transfer, retiring old paths | Only after the Otto port qualifies *and* you confirm git | 24 | 8 |
| | | **Total** | **137** | |

**Schedule** (working days, one engineer-day per executor-day):

| Days | What's happening |
|---|---|
| 0–2 | Phase 0, runner audit, contract spikes |
| 2–11 | A lands the lab fixes; B builds the controls; C does W4 and W1 |
| 11–12 | **Canary; the counted pilot starts** |
| 12–29 | C does the rest of the Windows fixes under the controls; D's custody and effects work is integrated by A; **controls judged by day 29** |
| 29–50 | F ports the controls into Otto; E wires the worker surface; A builds the candidate; **Otto port qualified by day 50** |
| 50–71 | G (if confirmed) |

**Critical path:** 71 working days, about **15–17 calendar weeks**, at a peak of six executors.

## Where Astra disagreed with my takes, and my call

| My take | Astra | My call |
|---|---|---|
| One Otto manager with parallel workers, rather than three on the same files | Keep A, D and E as separate managers; **A owns integration and grants one edit lease per shared file** | **Accept.** The lease model handles the six hot files (`service.py`, `serve.py`, `landing.py`, `facade.py`, `claude_cli.py`, `claude_adapter.py`), and D's custody work is big enough to need its own judgement. |
| Five managers can start at once | Five *managers* can start, but not five unrestricted *implementation* streams: D and E prepare first and implement after their gates | **Accept.** |
| Should B and F be the same manager? | Yes: continuity from the pilot to the production contract | **Accept.** |
| The lab fixes and custody work came after the pilot (my earlier roadmap) | **Pull them ahead of the pilot judgement;** they don't need the pilot's interface. That saves about 18 working days | **Accept.** It's the biggest schedule win. |
| A dedicated integration or qualification manager? | No full-time one; named accountability instead (C for the product, B for the controls, F for Otto, A for the candidate) | **Accept.** |
| G | No staffing until after the pilot result and the qualified port; spike the fencing first | **Accept.** It matches my "git after the pilot". |

## Where I'd push back on Astra
1. **B is still too heavy for a pilot (18 days).**
   - B1 (serialised budget reservations across concurrent starts, difficulty 7 at the subtask) and B7.3 (reconciling publication after a lost reply, 7) are the production-grade rigour that F builds anyway.
   - In the pilot, publication is your reserved decision, and one dispatcher serialises launches by construction.
   - **Cut B1.2 and B7.3 to simple versions:** a reservation line checked under the dispatcher's lock, and no automated publication. That brings B down to about **14 days**, and the canary moves from day 11 to about day 9.
2. **C1 (Windows access) is the real start gate for the pilot.** If hosted runners stay queued, the self-hosted fallback must be decided on day 1, not discovered on day 11. Make it an owner decision now.
3. **Stopping before G is a credible end point.** Everything through the qualified Otto port is about **113 days, with a 50-day critical path (about 10–11 weeks)**. G adds about 24 days and 21 more on the critical path, for git as the authority. Decide after the pilot whether cloud-first is worth it.
4. **These are human days.** With agents doing the executor work, as on the updater, the calendar compresses a lot. The critical path is then set by the pilot's 7-day observation minimum, the Windows runner, and review gates, rather than typing speed.

## Difficulty profile (from the task tables)
- **Mostly 5–7.** The genuine 8s are:
  - **D:** process custody, native and runner effect reconciliation, cross-path faults;
  - **F:** spend reservation and the all-role gateway;
  - **C:** W3's update-verification policy and W6's rollback recovery;
  - **G:** fencing, transfer and recovery.
- **No task is handed over at 9–10.** D1 and G1 are spikes that resolve the uncertainty first, which is exactly how the scale should work.
- **Every 7+ task names its hard invariant,** for example "an uncertain native invocation can't be repeated under a new request identity" (D5), or "old and new writers must never both act" (G6).

## Decisions this needs from you
1. **The manager plan:** A–E start now, with B continuing as F, and G conditional.
2. **The Windows runner fallback** (self-hosted?), decided now.
3. **Trim B to pilot weight** (my push-back), or keep Astra's version?
4. **Whether G is in scope at all,** decided after the pilot.
