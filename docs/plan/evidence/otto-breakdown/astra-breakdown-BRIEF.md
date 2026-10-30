# Break the Otto roadmap into parallel managers and executor-sized tasks

You are **Astra**. Read-only: no edits, no git writes, no services. You may start Luna sub-agents (`spawn_agent`, model `gpt-6-luna`) for anything still open. Verify the load-bearing facts yourself.

## The work
The roadmap is in `retro/08-otto-roadmap.md`, which holds the orchestrator's judgement, and `retro/evidence/otto-roadmap/astra-roadmap.md`, your own earlier answer. It has:
- **Phase 0:** dispositions and mandate.
- **Phase 1:** a lightweight thin path in the Astrid plan repo: tool receipts, message files plus wake-up, a turn-exit hook plus liveness monitor, a supervisor sweep, an incident-replay harness, batch integration.
- **Pilot:** a Windows runner, then REL-Windows (FIX-W1..W6, COH-C14 in `astrid-plan-repo/plans/FIX-windows-install-findings.md`) for a week, then judging the controls.
- **O1–O7:** port into Otto. O1 removes automatic selection and makes `done` submission-only, and can start now.
- **G1–G3:** a git-backed store, transfer, and retiring old paths.

The human engineer-day estimate for all of it is about 90–150. Every **day** below means a human engineer-day.

**Evidence for planning:**
- `luna/r-otto-files.md`: which Otto files each item touches, and the overlap matrix.
- `luna/r-pilot-files.md`: thin-path and FIX-W files, overlaps, the updater dependency, and the Windows runner.
- `luna/r-tests.md`: the existing proof per area, missing tests, and suite runtimes.
- `roadmap-luna/r-*.md`: earlier investigators. Repos: `otto/otto` (with branches), `astrid-plan-repo`, `banodoco/*`.

## Two questions
**Q1. Managers.** How should the work split into **workstreams, each run by one manager**, so that as much as possible runs **at the same time**?
- For each workstream: its goal, what it owns (repos, directories, files), what it must not touch, when it can start (now, or after which milestone), how it hands off, and its rough total in days.
- **Show the parallel schedule:** which managers run together in each window, and the critical path.
- **Handle the shared hot spots explicitly:** file ownership, integration order, who integrates, and how conflicts get resolved.
- Say whether a dedicated integration or qualification manager is needed, or whether each manager integrates its own work.

**Q2. Tasks.** Within each workstream, the units handed to a single executor:
- **Tasks of about 3 days each** (human engineer-days; never more than 3). Split anything bigger.
- **Each task breaks into subtasks** (typically 2–6), each a concrete step with its own check.
- **Score difficulty from 1 to 10 at every level:** each workstream as a whole (manager-level complexity: coordination, hot spots, ambiguity), each task, and each subtask.
  - **1–3:** routine, a known pattern, directly checkable;
  - **4–6:** bounded logic, adapters, harnesses, a real but contained risk;
  - **7–8:** transactions, recovery, concurrency, authority or a cross-repo protocol, where a specific correctness invariant is hard to get right;
  - **9–10:** too risky or uncertain to hand over as is; split it, or run a design spike first.

  **Name the invariant that makes something hard.** Size, importance or a scary label alone don't count (Megado's XHARD rubric).
- **Task format:** `ID | task | days (≤3) | difficulty | the hard invariant (if 7 or above) | depends on | done when (the real check) | files or areas`, followed by its subtasks as `ID.n | subtask | difficulty | check`.

## The orchestrator's tentative takes (challenge them; don't just adopt them)
1. **Five managers can start at once.** Owner decisions are assumed to follow the recommendations in `08`:
   - **A, Otto canon alignment:** O1 plus the O2 lab landings.
   - **B, thin-path control layer:** Phase 1, in the Astrid plan repo.
   - **C, pilot product work:** FIX-W rows and the Windows runner. It can start on W4 and the W1 core now, under the current process.
   - **D, Otto custody and effects:** O3.
   - **E, Otto instruction and worker surface:** O6.

   Later managers:
   - **F:** port the controls (O4, O5, O7) after the pilot;
   - **G:** the git store (G1–G3) after F.
2. **A, D and E all touch Otto** (hot spots: dispatch, landing, the tools facade, the adapters). One option is a single Otto manager running A, then D and E in parallel under a file ownership map. Another is three managers plus one integration owner. I lean towards **one Otto integration owner (manager A) and parallel workers**, rather than three managers editing the same files.
3. **The pilot's controls must exist before C's pilot week counts.** C's early work runs under the current process and is the "before" baseline.
4. **Integration:** each manager integrates its own workstream onto its own branch. The Otto integration owner batches across A, D and E, then bisects any failures.
5. **Difficulty mapping to models:**
   - 1–3 → Luna or Haiku;
   - 4–6 → Terra or Haiku-xhigh, then Sonnet;
   - 7–8 → Sol or Sonnet;
   - 9–10 → split or spike first.

   The likely 7–8s: O3 custody and effects reconciliation, O4 the launch gateway with spend reservation, G1 the git store with single-writer fencing, and W3/W6 in the product.
6. **The biggest schedule risk** is Windows runner access (GitHub Actions jobs stayed queued), so it goes first in C.
7. **I may be wrong about:** whether B and F should be the same manager (whoever builds the thin-path controls ports them), and whether G should exist at all before the pilot's result.

## Output (your final message)
1. **Workstreams and managers:** a table, plus the parallel schedule by window, the critical path, and the hot-spot plan.
2. **Per workstream:** its overall difficulty score with a one-line reason, then its tasks (≤3 days each) with scored subtasks, in the Q2 format.
3. **Totals:** days per workstream, the critical-path length in days, and the expected calendar time with your manager plan.
4. **Where you disagree with the orchestrator's takes,** and why.
5. **The riskiest tasks** (difficulty 7 or above): what would de-risk each one first.

Be concrete. Cite evidence for the file ownership and the test claims.
