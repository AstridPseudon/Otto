# Minimal structure for a platform

## Design aim

Make the practices that worked part of the workflow: a manager-owned task queue, scoped worker briefs, evidence-backed decisions, and a clear handoff. Make failure visible early: a worker that never starts, results waiting for review, stale snapshots, ambiguous test status, or work assigned to the wrong role.

The proposed thresholds below are **policy choices**, not thresholds observed in the records. The need for them is observed: four workers failed before their first command and were noticed about 35 minutes later [10-26 22:57–23:32]; seven completed runs waited for the manager [10-27 17:58]; snapshots were stale for over an hour [10-28 13:03, 16:02]; and the manager reached 263K–281K context tokens [10-28 01:57, 03:57; `COST-LOG.md`].

## 1. Roles and boundaries

| Role | Owns | Allowed | Must never |
|---|---|---|---|
| **Owner** | Product direction, project priority, external permissions, release or publication choices | Approve plans and policy changes; delegate routine execution decisions; accept named gaps | Be made responsible for routine queue movement or status discovery. Repeated questions about whether work was running show status was not visible enough [10-27 14:56–20:36; `data/user-messages.txt`]. |
| **Orchestrator** | Program-level direction, manager assignment, oversight, cross-project balance, escalations | Approve in-scope rulings when delegated; unblock managers; review cadence and spend; start or hand off manager sessions | Implement product code, review diffs, run tests, or land tasks. The owner stated this boundary at [10-28 02:08], and `ORCHESTRATOR.md` records it. |
| **Manager** | One project queue from plan approval through integration and handoff | Break down tasks, assign tiers, dispatch workers, review evidence, land accepted changes, keep state current | Change owner-approved scope, product policy, or external permissions without an explicit delegation or decision. The manager role shifted over time, but the final UPD brief makes the manager the queue owner and integrator (`MANAGER-CODEX.md`; [10-28 02:08]). |
| **Worker** | One bounded task/run | Read assigned sources, change owned files, run named checks, report evidence and gaps | Land or push changes, broaden scope, rewrite acceptance criteria, or claim unrun checks passed. Workers left changes for manager review and landing (`MANAGER-CODEX.md`; [10-27 02:56–02:57]). |
| **Reviewer** | Independent evaluation of a task, plan, or integration seam | Read the exact revision, return evidence-backed findings and a verdict; propose bounded fix tasks | Implement fixes or silently change acceptance. Opus implementation assignments prompted owner corrections [10-28 01:29–01:40]. |

Enforce these boundaries in task assignment, not only in prose. Model and role must be explicit fields, and a reviewer assignment must not accept an implementation dispatch.

## 2. Entities and minimal fields

Use stable IDs and links between records. Avoid duplicating live task state in several documents: `runs/QUEUE.md` called itself the source of truth, while `STATUS.md` also held task states [both files; `out/w2-tracking.md`].

| Entity | Minimum fields |
|---|---|
| **Program** | `id`, owner, orchestrator, active project IDs, current policy/version, authorized repos/branches/actions, budget, status |
| **Project** | `id`, program ID, manager/session, goal, plan revision, repo/base SHA(s), integration branch, queue, status, approval state |
| **Task** | `id`, project, goal/scope, exclusions, dependencies, owned paths, `difficulty_score` and factors, `model_tier`, actual model/backend, approved `done_when`, test plan, state, next action, evidence links |
| **Run** | `id`, task ID, attempt, role, model, repo/base SHA, worktree, dispatch/start/heartbeat/end times, exit state, changed paths/commit, log/final links, cost |
| **Review** | `id`, target task/revision, purpose, reviewer/model, read-only flag, findings, verdict, round, disposition, linked fix tasks |
| **Decision** | `id`, scope, question, options, decision and rationale, decider, approval basis (explicit/delegated), affected records, supersedes, follow-up |
| **Escalation** | `id`, task/run, blocker and attempts, evidence, proposed options, owner-needed flag, assigned decision-maker, status |
| **Check-in** | `id`, project/session, time, last activity, queue counts, active workers/tests, snapshot time, cost delta, findings/interventions, next action |
| **Handoff** | source/target session, phase, snapshot revision/time, landed SHAs, open tasks/decisions, test gaps, permissions, first next action |
| **Evidence** | `id`, task/run, repo and exact SHA, command or observation, result class, timestamp, artifact path, confidence/limitations |
| **Cost** | timestamp, program/project, session/run/task, model, interval and cumulative cost, context size, retry/review attribution |

Result classes must distinguish `passed`, `failed`, `pre_existing`, `environmental`, and `not_run`. The rebase initially called failures pre-existing based on the updater branch; comparison with `origin/main` found regression candidates [10-28 13:04–15:27]. The final closeout recorded 1,021 tests as hung/not run rather than passed [10-28 20:56].

## 3. v0 records

Keep v0 as a small set of versioned files in a git repo. The task queue is the operational source of truth; project status and digests should be generated from it rather than maintained as competing task tables.

**Task-list table header:**

```text
id | goal | scope/exclusions | repos@base_sha | paths | after
difficulty_score/factors | tier/model | done_when | tests
state | active_run | last_progress_at | evidence | landed_sha | next_action
```

Each task gets one run folder, such as `runs/<task-id>/`, with:

```text
brief.md        # current operative brief and approved Done when
final.md        # status, changes, checks, unrun checks, handoff note
tests.txt       # commands, results, and links to full logs
evidence/       # compact artifacts needed to verify claims
```

Keep prior brief versions or decisions in append-only history, but make the current operative instructions unambiguous. Worker briefs worked best when they named scope, paths, real caller, expected tests, and report format; test fakes missed a real repeated-install failure [COH-C3 review, `/home/user/repo/astrid-install/runs/COH-C3-review/final.md`].

**Check-in record (JSON):**

```json
{
  "at": "2026-10-28T16:02:00Z",
  "project": "REBASE",
  "manager_session": "…",
  "queue": {"ready": 0, "running": 2, "review": 1, "blocked": 0},
  "workers": [{"run": "R8", "state": "running", "last_heartbeat": "…"}],
  "tests": [{"run": "R8-agent", "state": "running", "last_output": "…"}],
  "last_landing": "…",
  "snapshot": {"sha": "…", "at": "…"},
  "cost_delta_usd": 1.65,
  "intervention": "Manager asked to inspect silent test logs",
  "next_action": "Finish bounded test chunks and report hung IDs"
}
```

Also keep `program.yaml`, one `projects/<id>.yaml`, a queue, `decisions.md` or `decisions.jsonl`, `cost.csv`, and a `handoff.md`. The current queue, `brief.md`/`final.md` run folders, handoff manifest, and cost log provide working examples (`runs/QUEUE.md`; `handoff-upd/snapshot/MANIFEST.md`; `COST-LOG.md`).

## 4. Loops and intervention thresholds

**Normal cadence:** the manager dispatches every ready task as capacity permits and handles finished workers before starting long tests. The owner corrected self-scheduled pauses to require back-to-back work [10-28 00:34–00:36]; the manager later accumulated seven finished runs waiting [10-27 17:58]. A check-in observes and steers; it is not the mechanism that advances the queue.

**Orchestrator cadence:** one hourly check while the program is active. Ask: Is the manager alive? Which rows changed state? Are ready tasks waiting while slots are free? Are finished runs awaiting review? Are claimed passes tied to exact commands, commits, and outputs? Is the snapshot current? What is the next milestone, blocker, and cost? The written hourly checklist already asked about status, tests, loops, and cost (`ORCHESTRATOR.md`, “Hourly tick”).

**Use a faster check when an event indicates a stall or risk:**

- **No worker heartbeat within 5 minutes of dispatch:** mark `failed_to_start` and alert the manager. This proposed limit responds to the four failed launches that went unnoticed for about 35 minutes [10-26 22:57–23:32].
- **No state change for 15 minutes:** check liveness and the declared next event. For a long test, record its process/log heartbeat and expected duration; do not confuse an active test with an idle manager. The manager previously polled silent tests and waited through long suites [10-28 07:58–08:58].
- **Completed run waits over 15 minutes:** notify the manager to review or state why it is waiting. The seven-run backlog is the direct basis [10-27 17:58].
- **Same implementation failure twice:** escalate to the manager for diagnosis or reviewer input. After two FIX rounds on the same mechanism, require a simplification proposal; stop after three bounded fix rounds and park remaining findings as separate tasks. Repeated review rounds on C2 led to a cap [10-27 09:59–10:21; `MANAGER.md`].
- **Context exceeds 100K tokens:** warn and schedule a phase-boundary handoff with a compact state file. **Inference/policy choice:** 100K is an early warning chosen well below the observed 263K–281K context levels and associated cost concern [10-28 01:57–03:57; `COST-LOG.md`].
- **Snapshot is over 15 minutes old during active work, or predates a landing:** mark status stale and request an export. **Inference/policy choice:** the observed snapshots lagged by over an hour, including already-landed work [10-28 05:58, 13:03, 16:02].
- **Owner changes scope/cadence or pauses a project:** update effective policy and stop or replace the relevant triggers. Hourly review was explicitly turned off by the owner [10-28 18:09–18:24].

## 5. Difficulty and model routing

Score task difficulty before dispatch. Add one point for each observed risk factor:

1. Crosses multiple repositories or shared interfaces.
2. Changes lifecycle or stateful behavior such as stop, rollback, recovery, install, or update.
3. Depends on concurrency, order, or environment-sensitive behavior.
4. Root cause is uncertain or there is no minimal reproducer.

**Mapping:** `0–1 = Normal`, `2–3 = Hard`, `4 = Super-hard`. Security, data-loss, or destructive lifecycle work is Super-hard regardless of score. This is an **inferred starting rubric**, based on the difference between simple UI work and cross-component stop/recovery work, and on failures whose root cause turned out to be a test fixture or Runtime defect [10-28 14:17–15:00, 15:28–16:04; `out/w2-models-cost.md`].

Store abstract tier separately from actual model. The owner’s requested Codex mapping was Normal → Luna, Hard → Terra, Super-hard → Sol; Astra was reviewer [10-28 10:31–10:33]. If using a different provider, record its model and reasoning level explicitly. In the Claude-manager phase, Hard began at Haiku xhigh with one-failure Sonnet fallback; that was a provider-specific policy, not a change to the tier definition [10-28 02:07–02:08].

A worker that fails before inspecting code is a dispatch/environment failure, not a difficulty escalation: all four initial Codex workers failed on their first command [10-26 23:32–23:38]. On an implementation failure, attach the failed attempt and evidence to the retry; a Hard task may move up a tier under the selected model policy.

## 6. Gates and authority

| Gate | Pass condition | Automatic action or human decision |
|---|---|---|
| **Plan approved** | Goal, scope, repo/base SHAs, dependencies, delivery boundary, risks, and owner decisions are recorded consistently | Owner approves scope and policy. Orchestrator may approve routine execution detail only when delegated. A rebase plan was approved with explicit “merge, don’t replay” and “no repinning” rulings [10-28 09:58–10:21]. |
| **Done when approved** | Measurable acceptance and proving test are attached before implementation | Manager approves within the accepted plan; escalate product behavior, scope, or external commitments. The worker-proposes/manager-approves rule was added after cold-start review found missing criteria [10-26 19:59–20:05]. |
| **Land** | Manager verifies diff scope, focused checks, baseline classification, and evidence; unrun checks are labeled | Manager lands automatically under the approved branch policy. Worker and reviewer cannot land. Manager was responsible for testing and landing in the later brief (`MANAGER-CODEX.md`). |
| **Project done** | No ready/running/review tasks; each task has an outcome, landed SHA or explicit deferment, and evidence; handoff is current | Platform can mark work complete and verification complete separately. Owner decides release/publication and whether to start the next project. `QUEUE-COMPLETE` coexisted with explicitly unrun tests [10-28 20:56], so one “done” flag must not imply full verification. |

## 7. v0 and v1

**v0: git repo plus a few scripts**

Keep:

- One program manifest, project plan, manager brief, authoritative queue, decision log, cost log, and run folders.
- Exact repo/base SHAs, worker briefs and finals, review findings, test outputs, and handoff manifests.
- A narrow dispatcher for dispatch, worktree/sync/land, and status operations where the manager’s sandbox cannot do them. The dispatcher restored execution after nested Codex workers could not run shell commands [10-26 23:32–23:38]; the current request-file interface is documented in `tools/dispatcher.sh`.
- Snapshot/export and landing helpers until the platform provides durable run state. The tested handoff preserved 140 branch tips [10-28 00:11–00:14].

Remove from the active surface:

- Duplicate task-state tables; generate program status from project queues.
- Superseded role/model/cadence instructions from the read-first path. The docs changed faster than the README and other operating files [10-28 `out/w2-codified-process.md`].
- Repeated replacement handoff bundles; keep one current package with a version, `supersedes`, changes, and verification state [10-28 16:36–20:39].
- Separate keepalive, recovery, and watch scripts once the host runtime reliably owns worker lifetime, restart recovery, and scheduled triggers. They were added reactively around container reclaim and missing check-ins [10-27 13:02–16:06; `tools/keepalive.sh`, `tools/recover.sh`, `tools/watch.sh`]. Until then, retain only the script needed by the actual environment.

**v1: platform features**

Build only the capabilities the records show the file-and-script setup had to approximate:

- One state store and live views for program, projects, task queues, runs, reviews, decisions, check-ins, handoffs, evidence, and cost.
- Role and model enforcement at dispatch and landing; scoped repo/branch/path permissions and auditable owner approvals.
- Managed worker lifecycle: dispatch acknowledgment, heartbeat, exit state, retry, recovery, and durable checkpoints.
- Automatic status and stale-snapshot alerts, including a compact owner digest tied to an “as of” revision.
- Evidence-linked gates and explicit `not_run` states; test-run liveness and baseline-aware failure classification.
- Session rollover on context or provider limits, with a validated handoff and preserved queue/run state.
- Cost by task, run, model, retry, and review round. Session totals alone hid task and tier comparisons; `COST-LOG.md` was primarily session-level.

## 8. Do not build

- **A platform-sized orchestration framework before proving the queue and evidence loop.** The TST plan grew to 24 tasks and was cut to 17 after review [10-27 21:08–21:45].
- **A one-time audit swarm when mandatory checks cover the same risk.** The proposed four-worker sweep was removed after over-engineering review [10-28 16:50–17:11].
- **More review rounds without a stop rule.** C2’s repeated rounds generated further findings until bounded [10-27 09:59–10:21].
- **A full-suite rerun to debug a narrow ordering failure.** Two roughly 70-minute runs preceded the instruction to isolate the smallest reproducer [10-28 14:16–14:17].
- **Separate tools and status files that report the same state.** The queue and `STATUS.md` overlapped; the queue worked as the manager’s source of truth (`runs/QUEUE.md`; `out/w2-tracking.md`).
- **Automatic progress claims from “worker finished” or “queue complete.”** The final rebase had 1,021 tests not run (hung) [10-28 20:56]. Mark implementation completion and verification completion separately.