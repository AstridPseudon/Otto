# How the build team operates (until the tool runs itself)

This is the **current** operating policy. It replaces the older rules in `02`–`03` wherever they differ: there are no model restrictions, no spend ceilings and no dispatcher files.

## Who does what
| Seat | Filled by | Does | Decides |
|---|---|---|---|
| **Owner** | The person who commissioned this | Answers the open items in `DECISIONS.md`; approves releases | Scope, defaults, cost, release |
| **Orchestrator** | One long-lived Claude Code or Codex session | Runs S0, L0, X0a and X0b; hands each manager its folder; checks in **every 60 minutes**; consults an advisor session **every 180 minutes** and on request; owns the release *gate* (the owner owns the release *decision*) | The order of work, integration priorities, disputes between managers |
| **Advisor** | A separate session on the strongest available model | Reads a snapshot (the mandate, the status of each project, earlier advice and what was done with it) and returns advice. The orchestrator records **adopt, defer or reject** for each point | Nothing; it advises |
| **Manager ×4** | One session per project folder (`projects/state`, `runtime`, `pack`, `delivery`) | Plans from `TASKS.md`, dispatches workers, reviews and accepts their results promptly, keeps `STATUS.md` current | Which worker does what, and acceptance within the project |
| **Worker** | Short sessions, one task each, using a mid or strong model to match the task's tier | Implements in its own Git worktree, runs the checks, submits with evidence | How to do the task |

## The rules
1. **Managers dispatch;** no one else dispatches into a project. Prove one worker end to end before running several.
2. **Every brief names:** the task id, the repo and base commit, the files the worker owns, the done check (from `TASKS.md`), and the evidence expected.
3. **Drain before dispatching more.** Review finished work before starting new work. An idle manager with ready work is nudged by the orchestrator once, then escalated to the owner.
4. **Landing:** every change goes rebase → run CI on that exact commit → fast-forward `main` only, refusing if `main` has moved. B0 sets up the script and initial CI on day 0, M4 runs it from then on, and CI grows into the full suite as D3 lands. Use the sequence from old Otto's `landing.py`, never `tools/land.sh`.
5. **CI** is the installed-wheel suite (unit, acceptance, omp compatibility), about 3–5 minutes. A skip, a hang or a leaked process is a failure. Live tests (S0, VS, the pilot) are logged separately, with evidence.
6. **Interfaces** come from `projects/contract.md` (L0). To change one, send one contract diff, reviewed by its producer and its consumers; M1 owns migrations.
7. **Status lives in the repo:** each `projects/<name>/STATUS.md` (managers) and `projects/LOG.md` (the orchestrator: decisions, escalations, advice and what was done with it). Once the tool runs, `otto status` replaces these.
8. **Escalation:** worker → manager → orchestrator → owner. Escalate early with a concrete question and a recommended answer.
9. **Never:** delete history or branches, push to old Otto's branches, put credentials in Git, or work around a permission denial.

## When the tool takes over
1. **After VS** (the live vertical slice), with task, landing and recovery checks green: try one small, non-critical task on the tool.
2. **When the base qualifies** (`START-HERE.md` milestone 1): start the tool's own organisation and import the pilot with `otto project new attach --from docs/plan/projects/attach`. That's the pilot. The outside team stays in charge until the pilot passes.
3. **After the owner approves the release:** the tool runs the remaining follow-ups itself.
