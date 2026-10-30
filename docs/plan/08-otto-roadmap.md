> **HISTORY. This is not a current requirement.** This document is a roadmap for finishing old Otto: **a path we did not take**. The current documents start at `START-HERE.md`.

# Otto: the roadmap from today's branches to the end state

**What ran, all on Codex:**
- The Otto repo was restored from the transfer bundle, with hashes verified and nothing started.
- **Nine Luna investigators** looked at canon/main, the 16 lab branches, SLIM, PACKS, EFFECTS and PROCLIFE, THROUGHPUT/HARNESS3/ASTRID-FLEET, the pause queue, the smallest change per target point, and the thin path. Their reports are in `evidence/otto-roadmap/luna/`.
- **Astra (xhigh)** synthesised them and verified claims in the repo. Its answer is in `evidence/otto-roadmap/astra-roadmap.md`.
- **Note:** Astra again started no sub-agents of its own, despite the brief. The fan-out came from the nine investigators I ran.
- I checked Astra's two most surprising claims in code, and both hold:
  - **Canon dispatches automatically today:** `bind_automatic_dispatch` (`otto/hostctl/product_service.py:960`) runs on the owner's capacity tick (`portfolio/execution_host.py:1163`).
  - **A worker's `done` triggers landing:** the landing owner port routes `worker-done` to `LandingService.done` (`herzchen/fleet/tools/facade.py:99`).

  Both contradict the owner's stance, so both must change.

## 1. What to do with in-flight work

| Branch | Verdict | Keep |
|---|---|---|
| `lab/STAGE2CLIENT` | **Finish first** (in Otto; it doesn't gate the pilot) | Install the client, refuse registration if it's absent, detect terminal failures. Its saved check still fails one test. |
| `lab/CLIARGS`, `ROLEIDS`, `OBSOWNER`, `TESTPATCH`, `LABPIN`, `LANDPROOF`, `INTEG-PROCLIFE-PL3` | **Finish and land** as isolated deltas | Valid manager commands, reserved identities, authenticated callers, real-owner tests, task/lab binding, exact-commit proof, reader custody |
| `lab/BOOTCFG`, `BOOTLAND`, `DISTURB`, `REALSTAGE3` | **Rewrite** | Portable install validation, receipt-backed land/publish, restart/refusal scenarios, and a real-worker canary |
| `lab/LANDBATCH`, `PROOFDOC`, `ROOTFILE`, `XFERMAP` | **Drop** | Old gate, runbook freeze and CUTOVER machinery; keep the batch-integration idea |
| `proj/slim` | **Rewrite scope** | Harvest the deletions and status simplification; drop the 25% quota (only about 1.2K lines net removed so far) |
| `proj/packs` | **Shrink** | Pinned role/model policy and provenance → one effective brief |
| `proj/effects`, `proj/proclife` | **Finish bounded slices** | Start claims and unknown-outcome reconciliation; process birth and cleanup |
| `proj/throughput` | **TP3/TP6 only** | Focused feedback and actionable refusals; defer caches |
| `proj/harness3` | **Defer** | — |
| `proj/astridfleet` | **Close as a study** | — |

**I agree with all of these.** The two-tip diff accounting the labs investigator used overstated the branch sizes (BOOTCFG's own delta is 5 files, not 68), and Astra corrected it.

## 2. The path: Astra's phases, with my changes

**Astra's shape:**

| Phase | Contents |
|---|---|
| **0** | Replace the paused programme's instructions: dispositions and the pilot mandate |
| **1** | Build the thin path: T1 git journal, T2 all-role launch gateway, T3 receipts, T4 messages/ask/exec, T5 exits + monitor, T6 supervisor/briefs/replay, T7 batch integration |
| **2** | Pilot: P1 canary, P2 REL-Windows for a week, P3 judge the controls |
| **3** | Port into Otto (O1–O7), starting with *remove automatic selection; `done` becomes submission-only* |
| **4** | Git-backed control store, cloud adapter, transfer, retire the old paths (about 16–23K source deleted, plus 8–12K of ops) |

**Where I'd change it:**
1. **Phase 1 is too heavy for a pilot.**
   - T1 (a git journal with an authenticated single writer and generation fencing) and T2 (an all-role gateway with budget reservation) are both Super-hard, and they put foundation work *before* the pilot. That's what Astra's own first review warned against.
   - The thin path already has a single writer, the dispatcher. So for the pilot:
     - receipts are append-only files the dispatcher writes;
     - every launch (managers, workers, reviewers, supervisor) goes through the dispatcher;
     - the spend ceiling is a reservation line checked before each launch;
     - fencing is "only the dispatcher pushes".
   - The rigorous versions move to Phase 3 and 4, where they become product guarantees.
   - That takes Phase 1 from three Super-hard tasks to roughly **five Hard/Normal tasks**: receipts, messages+ask, exits+monitor, supervisor+briefs, batch integration.
2. **Not every control is judged on a weekly count.** Astra's provocation 9 is right and corrects my `07` ("keep a control only if it catches one real problem a week"). Two classes:
   - **Behaviour nudges** (exit checks, supervisor nudges): judged on catches and false alarms during the pilot.
   - **Safety invariants** (exact-commit proof, effects that run at most once, custody, authority): kept on risk evidence and incident replay.
3. **The pilot needs a Windows runner that actually runs.** P1 must prove Windows access before P2 starts. GitHub Actions jobs stayed queued on the test repo, so solve that first, or use a self-hosted runner. Astra also caught a real discrepancy: the dispatcher pushes CI to a hard-coded owner repo, while the brief describes product-repo Actions.
4. **O1 comes first in Phase 3, and can be done now.** Removing automatic selection and making `done` submission-only is small (about 0.3–0.6K lines) and aligns canon with the owner's stance *before* anything else lands on top.

**Revised sequence:** Phase 0 → Phase 1 (lightweight) → P1 (Windows access first) → P2 → P3, with O1 in parallel. Then O2–O7 → G1–G3.

## 3. The end state, concretely (Astra's description, which I accept with the notes below)

**Components:**
1. Mandate and brief compiler: enforced constraints, checked obligations and judgement guidance, kept separate.
2. Launch gateway: executes the manager's choices, enforces model, spend and capacity, and records the intent before launching.
3. Host and execution adapters: local or cloud.
4. Git journal plus generated projections.
5. Messages, wake-up and liveness, with a scheduler that survives a manager's death.
6. Cheap supervisor.
7. Integration and qualification tools.

**Commands** (proposed; the CLI and agent tools share the same operations):

| Role | Commands |
|---|---|
| Owner | `approve`, `decide`, `policy revise`, `pause`, `status` |
| Orchestrator | `plan`, `run --role explorer/planner/reviewer`, `manager start/replace`, `message`, `status` |
| Supervisor | `sweep`, `show`, `message --kind nudge/escalate` |
| Manager | `task`, `run`, `resume --log`, `answer`, `integrate`, `qualify`, `land`, `exit` |
| Worker | `task`, `exec`/`check`, `ask`, `done` (submission only), `exit` |

**Records:** mandate/policy, task, run and exit, tool receipt, message, decision/review, candidate/delivery. Implemented, verified and accepted-with-gaps stay distinct, and a changed candidate loses its qualification.

**Day in the life:** see Astra §3. A manager dies at 10:00 with a worker's question pending. The monitor catches it, the orchestrator replaces it as generation 2, the replacement reads the generated handoff and answers, the worker resumes, and the owner is never asked "is it running?".

**What happens to today's code** (118K non-test lines): keep about 45%, rewrite about 35%, delete about 20%. These are estimates, not audited.

**My note:** "git is authoritative" (G1) is the biggest bet in the roadmap. Run it *after* the pilot shows the thin path holds up under a week of real work, which the plan already does. If the pilot strains, the fallback is the local service as authority, with git as a mirror for cloud sessions.

## 4. Astra's ten provocative statements (and where I stand)
1. **Manager dispatch is a deliberate tax.** Keep it because the owner values the judgement, and measure what that judgement buys. *Agree; worth measuring in the pilot.*
2. **A hard budget may mean refusing a favourite model.** An adapter without enforceable bounds can't honestly promise capped unattended spend. *Agree.*
3. **Git can be the store, but git authorship isn't authority.** A forged "owner decision" file must grant nothing. *Agree: owner decisions need authentication.*
4. **A dead manager should be replaceable bookkeeping.** If replacing it means rebuilding the truth from prose, the receipts don't own the truth. *Agree; this is the pilot's best test.*
5. **Worker `done` must become less powerful.** Finishing a task isn't permission to choose when to integrate. *Agree, and canon must change (O1).*
6. **"Models loaded" is still weaker than "chat works."** *Agree: the pilot acceptance includes a real chat reply.*
7. **An unknown effect is allowed to stop useful work.** A new request key used to recover throughput is duplicate execution in disguise. *Agree. Hide it from agents, but honour it.*
8. **Cheap managers are a hypothesis, not a moral principle.** *Agree; it corrects my `06`.*
9. **A control can earn its place without catching anything this week.** *Agree; it corrects my `07`.*
10. **Otto should become less visible as it improves.** *Agree. This is the goal stated as a test.*

## 5. Owner decisions this needs
1. **Approve the in-flight verdicts,** especially dropping XFERMAP, LANDBATCH, PROOFDOC, ROOTFILE and HARNESS3, and rescoping SLIM and PACKS.
2. **Make Phase 1 lightweight** (my change), or build Astra's rigorous version?
3. **Remove automatic selection and make `done` submission-only in canon now (O1)?**
4. **Windows runner for the pilot:** fix the Actions hold, or use a self-hosted runner?
5. **Git as authority after the pilot**, with the local service as the fallback if the pilot strains?
