> **HISTORY. This is not a current requirement.** This document is the minimal structure proposed after the retrospective; superseded by the spec (`13-spec.md`). The current documents start at `START-HERE.md`.

# A minimal structure for running orchestrators, managers and workers

**Design rule:** every element below exists because of a specific failure or need observed in this program. The citations are in `evidence/lenses/`. The critic pass (`evidence/drafts/w4-critic.md`) cut an earlier draft from eleven entity types to seven files. Numeric thresholds are marked **default**: they come from observed incidents, but they're not calibrated, so tune them per project.

## 1. Roles

| Role | Owns | Never | Why this boundary |
|---|---|---|---|
| **Owner** | Direction, priority, permissions, policy, release and publication, spend ceiling | Has to chase status or re-state policy | About 20 status questions and about 17 drift corrections cost the owner's attention |
| **Orchestrator** | The program: plans, picks and briefs managers, checks them, decides escalations, balances and merges across managers, keeps the policy current | Implements, reviews diffs, runs tests, lands | The owner restated this boundary twice |
| **Manager** | One project queue: breaks down tasks, dispatches, checks results against Done when, lands, snapshots, reports | Changes scope or policy; asks reviewers to implement; idles while work is startable | Idle pacing, Opus doing implementation, finished-result backlog |
| **Worker** | One task in one worktree | Lands, pushes, widens scope, calls unrun checks passed | Pushes and claims are gated by the manager |
| **Reviewer** (a mode, not a person) | A read-only verdict on an exact revision, with bounded fix rows | Implements | Opus implementation drift |

Several managers can run under one orchestrator. Parallel managers need a **file ownership map**, and a **gate on shared foundations before forking**. The timeline program did this; the planned TST and REL Codex managers were designed to share one dispatcher's 6 worker slots.

## 2. Seven files (v0: a git repo)

| File | Holds | Replaces or fixes |
|---|---|---|
| `POLICY.md` (one per program) | Roles; model tier mapping; review rules; cadence; what the orchestrator, manager and owner each decide; hard limits (no `main`, deploys, secrets); spend ceiling; owner-away rules. **Every brief embeds it verbatim.** | Policy drift across handoffs (principle 3) |
| `PLAN.md` (per project) | Outcome, constraints, mode, base commits, end state, contracts, phases, decisions taken, deferred items, risks | Stale or contradictory plans |
| `QUEUE.md` (per project, **the** source of truth) | One row per task (schema below). Status pages and digests are generated from it, never hand-kept. | Duplicate state between `STATUS.md` and the queue |
| `runs/<task>/` | `brief.md` (current version only; history appended below a line), `final.md` (result template), `tests.txt`, links to logs | Missing or terse results; briefs full of superseded text |
| `DECISIONS.md` | Append-only: `id · when · question · decision · why · decided by (owner/orch/mgr, explicit or delegated) · affects · supersedes` | Rulings that lived only in chat |
| `LOG.md` | One line per check-in: `when · manager · cost · Δ · state · intervention`. The cost log already worked as this. | A separate check-in system (not needed) |
| `HANDOFF.md` + `snapshot/` | Bundles, a `refs.lock` (repo, base, ref, tip), the manifest, and a cold-start brief. Pushed after every landing. | Stale snapshots; painful manager transfers |

**Queue row:**
```
id | outcome (one line) | repo@base · files | after | tier → model | Done when (via real caller)
state | waiting on | attempts | evidence (link) | landed sha | note
```
- **States:** `todo`, `running`, `result-ready`, `fix`, `landed`, `blocked: <named thing>`, `deferred → <where>`.
- `result-ready` exists so a finished-results backlog is visible.
- `waiting on` makes "idle" versus "waiting on a test, worker or owner" visible.

**Worker result (`final.md`):**
```
Status: ready | blocked | LAND | FIX
Changed:
Checks: command → result (full output in tests.txt)
Not run / limits:
```

## 3. Difficulty: a light calculation

The owner asked for a difficulty calculation, and their three tiers worked as a shared language. Keep it as four yes/no questions that guide a judgement, not a formula:

1. Does it touch **more than one repo**, or a shared contract?
2. Does it change **stateful lifecycle** (install, update, stop, rollback, recovery, migration)?
3. Is it **concurrency-, order- or environment-sensitive**?
4. Is the **root cause unknown**, or is there no reproducer?

**Scoring:**
- **0–1 → Normal.**
- **2–3 → Hard.**
- **4, or any data-loss, security or "can't prove stop" risk → Super-hard.**
- **If question 4 is the only yes,** first dispatch a *diagnosis* task at Normal or Hard, then re-tier the fix.

**Escalation:** one failed Hard attempt moves up a tier, with the failure attached. A worker that never started, or failed on its first command, is an infrastructure fault and doesn't escalate.

**Calibration:** record `tier`, `attempts` and the outcome on each row. That's enough to check the rubric after the next program; it was never measured here.

## 4. Loops and triggers

**Manager loop (continuous):**
1. Land or fix finished results.
2. Dispatch every startable row, up to the worker cap.
3. Snapshot after each landing.
4. Wait only when every open row names what it's waiting on.

**Orchestrator loop:**
- **First-dispatch check:** about 10 minutes after a new manager starts, did a worker actually run?
- **Hourly** while any manager is active, asking the ten questions in the runbook §5.
- **~15 minutes** only while the orchestrator is actively iterating with a manager on a live problem.
- The schedule stops when the program's owner or phase changes.

**Triggers.** Each is an event; the defaults are tunable:

| Event | Default action |
|---|---|
| Dispatched worker shows no start or first output (**default:** 5 min) | Mark it failed-to-start; fix the infrastructure; don't escalate the tier |
| Startable rows exist, no worker is running | Nudge the manager: "work back to back" |
| A `result-ready` row is older than ~15 min | Nudge: "land finished results first" |
| Snapshot is older than the last landing | Ask the manager to push it |
| Long run silent past its expected end | Rerun in bounded chunks with per-test timeouts; record hung tests as not run |
| Second fix on the same mechanism | Ask for a simplification proposal, not another patch |
| Review round 3 finished | Stop; any residue goes to the closing review or the owner's list |
| Manager context above ~200K tokens | Rotate at the next phase boundary, using the handoff |
| Spend since the last check is above plan, or the ceiling is reached | Report it; past the ceiling, pause and ask the owner |
| Plan or brief contradicts `DECISIONS.md`, or wrong model or role on a row | Fix the source of truth before the next dispatch |

## 5. Gates

| Gate | Passes when | Decided by |
|---|---|---|
| Plan ready | Outcome, mode, base commits and one review are done; plan, queue and brief agree | Orchestrator; **the owner approves** scope, policy and starting the project |
| Done when | A one-line acceptance through the real caller is approved | Manager (within the plan) |
| Land | Diff in scope; checks cite command, commit and base; not-run items labelled | Manager |
| Project built | Queue empty or deferred; landed SHAs recorded | Manager |
| Project verified | Every required check has real evidence, or is listed as not run | Orchestrator reports it; **the owner accepts any gaps** |
| Release, deploy, pin, publish | — | **Owner only** |

## 6. v0 now → v1 platform

**v0 (keep from this program):**
- the files above;
- the dispatcher request files (`worktree`, `dispatch`, `land`, `sync`, `ci`), because sandboxed managers can't run git or start workers;
- `export.sh` and `import.sh` for handoffs;
- the cost/check-in log.

**Delete or merge:**
- `STATUS.md` (generate it from the queue);
- duplicate briefs (`MANAGER.md`, `MANAGER-CODEX.md` and `BRIEF-claude-manager.md` → one brief plus `POLICY.md`);
- superseded sections in the read-first docs;
- keepalive, recover and watch scripts once the host owns worker lifetime.

**v1 (build only what v0 had to fake):**
1. **A managed worker lifecycle:** dispatch acknowledgement, heartbeat, exit, retry, recovery. Hand-built here, it broke repeatedly: nested workers couldn't run shell commands, workers were falsely marked lost, exit markers vanished, and containers slept.
2. **Live queue and status views** with `as of` timestamps, and owner-facing status generated from them. This answers the owner's most frequent question.
3. **Policy enforcement at dispatch:** model and tier per row, reviewers read-only, role permissions, permitted repos and branches.
4. **Schedules tied to the program's lifecycle:** they start with a manager and stop when ownership changes.
5. **Session rollover** at context or provider limits, using the tested handoff.
6. **Spend per manager against a ceiling.** Per-task cost only if the calibration in §3 needs it.

## 7. Don't build

- A per-event entity model (separate Review, Escalation, Check-in, Evidence and Cost records). Links from queue rows and one log line cover it.
- A numeric difficulty formula before there's data to calibrate it.
- Fixed review ceremonies for every project. Big builds get ≤3 rounds plus an elegance pass; plans and tests get one review plus the real run.
- One-off audit swarms when a required check covers every case on every PR.
- Status documents kept by hand alongside the queue.
- Self-scheduled manager wake-ups as a pacing mechanism.
