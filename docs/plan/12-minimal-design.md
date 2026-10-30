> **HISTORY. This is not a current requirement.** This document is the owner's first minimal design (30 Oct). The spec evolved from it: the advisor, five ranks, oh-my-pi rather than Pi, SQLite rather than Git as the authority, no budget machinery. **Where they differ, the spec wins**. The current documents start at `START-HERE.md`.

# The minimal design (owner's direction, 30 Oct)

**The direction:**
- Four roles: orchestrator, manager, worker and sub-agent.
- **One central way to spawn any of them** (via Pi): a role plus instructions, where the instructions are **generic ones for that role plus specific ones** (the project for a manager, the task for a worker).
- **Projects are a spec folder,** which agents can extend, turned into a task list. One manager per project.
- **Packs** (Megado first) define the roles' instructions, the **skills** for the basic processes (speccing a project, sense-checking it, checking for over-engineering, best practices) and the role configurations. Other packs can be made later.
- The **orchestrator has scheduled reminders:** an hourly check-in, plus a second opinion every 3–6 hours.
- **No extravagant controls** (no spend control). **Trust plus basic structure.**
- A simple **SQLite database** that can move between machines or **sync to Turso.**
- **A tool now, built to become a protocol.** Skip the Herzchen library layer.

## What it is
A small tool (call it Otto) with five parts.

### 1. Packs (folders in git)
```
packs/megado/
  pack.yaml            # role defaults: model/host, which skills, reminder schedule
  roles/orchestrator.md  roles/manager.md  roles/worker.md  roles/subagent.md   # generic instructions
  skills/spec-project.md  skills/sense-check.md  skills/over-engineering.md
  skills/best-practices.md  skills/review.md  skills/handoff.md ...
  templates/project/   # the spec-folder layout a new project starts from
```
A different pack means a different protocol: other roles, skills, spec templates and schedules on the same infrastructure.

### 2. Projects (a spec folder plus task rows)
```
projects/<name>/
  brief.md   plan.md   decisions.md   notes/...   # agents extend this freely
```
The manager (using the pack's spec skill) turns the spec into task rows. The spec stays the source of truth; the task list is the work.

### 3. One database (SQLite, optionally synced to Turso)
| Table | Fields |
|---|---|
| `projects` | id, pack, spec_path, status, manager_id |
| `tasks` | id, project_id, title, brief, done_when, difficulty, state, assignee_id, result |
| `agents` | id, role, pack, parent_id, project_id, task_id, model, session_ref, status, started, last_seen |
| `messages` | id, from, to, task_id, kind (info/ask/escalate/answer/nudge), body, needs_reply, resolved |
| `schedules` | id, agent_id, every, prompt, next_at |
| `events` | an append-only log of everything above, for status and history |

That's six tables. One file. Copy it to move machines; sync it to Turso for backup or a second viewer.

### 4. One CLI, the same for people and agents
| Command | Does |
|---|---|
| `otto spawn <role> --project P [--task T]` | Composes the pack's role instructions, the project spec or task brief, and the role's skills. Launches the agent through **Pi**. Records the agent. Each role can only spawn the next level down. |
| `otto task add/update/list` | The manager writes tasks; workers update their state and results |
| `otto msg send/inbox/reply` | The one way to communicate and escalate: up to the parent, down to children |
| `otto status` | A digest generated from the database |
| `otto schedule add` | Reminders: hourly check-ins, the 3-hourly or 6-hourly second opinion |
| `otto run` | A small loop: fires schedules, delivers messages (by resuming the recipient's session), runs the turn-end check |

### 5. The only enforcement (basic structure)
- **Hierarchy:** orchestrator → manager → worker → sub-agent. A manager owns exactly one project.
- **The turn-end check** (your earlier rule): a manager ends its turn while its project has open tasks and nothing running.
  - The **first time,** a message back to the manager: "N tasks open, nothing running; dispatch or say why".
  - The **second time,** a message to the orchestrator.

  In Pi this is a small extension hook. (A Claude Code Stop hook does the same thing.)
- **Reminders fire on schedule.** That's the orchestrator's safety net.

There's nothing else: no spend gate, no launch gateway, no receipt system, no fencing, no authority layer.

## Why Pi fits the single spawn path
- **Several modes:** Pi runs interactively, as JSON, as an **RPC process (JSON over stdin/stdout)** or as an **SDK** (`createAgentSession`). One spawn function can start, resume and message agents.
- **Several providers through one harness:** API keys, or **OAuth sign-in for subscription providers** (`/login`). Claude and GPT models go through one path, so we don't need separate Claude Code and Codex adapters.
- **Sessions** are saved, so an agent can be resumed to deliver a message or a nudge.
- **Extensions** give the turn-end hook, and Pi has skills support.

**To verify before relying on it:**
- the package scope moved (`@mariozechner/pi-coding-agent` → `@earendil-works/...`), so check which is current;
- which subscription providers the current version supports;
- the RPC protocol details for the version we pin.

## Turso
- Two ways to sync:
  - **Embedded replicas** (libSQL): local reads, writes forwarded to the cloud primary. Production-ready.
  - **Turso Sync:** local reads and writes with explicit push and pull. Recommended for offline-first.
- **For one machine running the tool,** plain SQLite plus a periodic push is enough. Turso becomes useful once a second machine or a phone dashboard reads the same state.

## Reusing what exists
| From | Becomes |
|---|---|
| Megado skill (lifecycle, pragmatic review, XHARD rubric, improvement loop) | The Megado pack's method and skills |
| Otto's `otto-roles`/`otto-profiles` packs (about 280 lines) | `roles/*.md` and the `pack.yaml` defaults |
| `MANAGER-CODEX.md`, `ORCHESTRATOR.md` (hourly checklist), `retro/02` runbook | The role instructions: back-to-back dispatch, the evidence rules, the check-in questions |
| Our over-engineering and first-principles review briefs, the Astra review prompts | `skills/over-engineering.md`, `skills/sense-check.md` |
| Worker brief and result templates (`retro/03`), queue and Done-when format | The task fields and the worker role |
| `land.sh` order (rebase → check the merged commit → fast-forward) | A worker or manager skill plus a script |
| `export.sh`/`import.sh` | Mostly unnecessary: the DB plus the git repos are the state |
| Otto service, Herzchen, dispatcher file protocol, keepalive/recover/watch | **Retired** |

## What this drops from earlier plans (deliberately)
| Dropped | What covers it instead |
|---|---|
| Spend ceiling and launch gateway | The orchestrator's check-in sees cost |
| Receipts system | The events table plus git history |
| Separate liveness monitor | The turn-end check plus the hourly reminder. A dead manager is found within an hour. |
| Authenticated decisions | One owner, one machine |
| Supervisor sweep as its own role | The orchestrator's hourly check-in *is* the sweep; the 3–6-hourly second opinion is the "consult another thing" |
| Mandate record | The project brief |

These are conscious trades for simplicity, and each can be added later if a real incident calls for it.

## Effort
| Piece | Engineer-days |
|---|---:|
| DB schema plus CLI (projects, tasks, messages, status) | 2–3 |
| `spawn` through Pi with instruction composition, plus resume to deliver messages | 3–4 |
| Schedules plus the `otto run` loop | 1–2 |
| Turn-end check (Pi extension) | 1–2 |
| The Megado pack: roles plus skills, mostly assembled from existing material | 3–4 |
| Turso sync (optional) | 0.5–1 |
| Pilot on a real project (e.g. the Windows fixes) and fixes from it | 3–5 |
| **Total** | **about 14–21** |

With agents building it, that's probably about a week of calendar time. **To become a protocol later:** publish the pack format and the six-table schema, and anyone can implement the CLI.

## Open questions for you
1. **Where it runs:** your Mac, an always-on box, or both (with Turso keeping them in sync)?
2. **The orchestrator's host:** a Pi session like the others, or stay in Claude Code?
3. **The second opinion:** which model or agent the 3–6-hourly "consult another thing" calls (Astra through Pi's OpenAI provider?).
4. **Subscriptions or API keys** for Pi's providers. This affects cost and rate limits.
