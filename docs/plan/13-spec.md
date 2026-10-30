# Spec: a minimal tool for running agent organisations (v3.5)

The research is in `evidence/spec/`: Luna reports on the spec-folder sync, reuse, the pack material and the branches; Astra's v1 sense-check; and Claude research on oh-my-pi, upstream Pi and Astrid's OMP integration. Part A is *what the system is*; Part B is *how we build it*; Part C is *what we reuse*. **New here? Read `START-HERE.md` and `GLOSSARY.md` first.** The change history is at the end.

---

# Part A: the system

## A1. Vision
One small tool runs an organisation of agents on **one machine**:
- an **advisor**, the highest intelligence, gives advice when the orchestrator asks;
- an **orchestrator** (mid-level) deploys **managers** and checks on them on a schedule;
- each **manager** (a lower, cheaper model) owns **one project**, and farms tasks out to **workers** at a mid or high level depending on difficulty;
- each **worker** deploys **sub-agents** for narrower pieces.

**Every agent is started the same way:** a role, plus the generic instructions for that role, plus the specific instructions for its job. The generic instructions and the skills come from the project's **pack** (Megado first). The specific ones come from the **project spec folder**, a task, or the owner's mandate.

**Structure, not controls:**
- the hierarchy;
- the orchestrator's reminders (by default a check-in every 60 minutes and an advisor consultation every 180 minutes; both can be changed);
- a turn-end check that nudges idle managers.

**Everything else is trust and skills.**

## A2. Ranks, roles and models
**Two layers.** The tool knows only the **ranks**; the **pack** defines the **roles**.

- **Ranks** are fixed and built into the tool. There are five: advisor, orchestrator, manager, worker and sub-agent. A rank decides who can start whom, who reports to whom, and how the agent is run (a supervised session, or an omp sub-agent inside its worker).
- **Roles** are flexible and defined by the pack. A role is a named job at a rank, with:
  - **fixed instructions** (`roles/<name>.md`);
  - the **skills** it gets;
  - its **model role** (by default, its rank's).

  Megado ships the four core roles (advisor, orchestrator, manager, worker) plus **specialists:**

  | Specialist | What it does | Generic skill |
  |---|---|---|
  | `sense-checker` | Checks whether a spec or plan reaches its goal | `sense-check` |
  | `over-engineering-checker` | Looks for what to cut | `over-engineering` |
  | `reviewer` | Reviews a change | `review` |
  | `scout` | Researches a question | — |

  Another pack can add its own roles.
- **A specialist runs at whichever rank suits the job.**
  - At **worker** rank, a manager starts one as its own task: `otto spawn sense-checker --task <id>`. It gets a supervised session, a submission and a manager's acceptance.
  - At **sub-agent** rank, a worker calls it through omp's `task` tool. The tool generates the omp agent definition from the same role file.
- **One instruction file per role,** versioned with the pack. Each agent records its pack version and a hash of its role file **on both paths** (supervised and native helper), so you can always see exactly which fixed instructions it ran with.
- **A short wrapper per rank** sits around the shared role instructions. A worker submits to its manager; a helper returns its result to its worker. The agent's **rank is stored separately from its role,** and it's inferred from how it was started: a manager's `otto spawn` gives a worker, a worker's native `task` call gives a helper. It's then checked against the ranks the role allows.
- **The role's skills and model role live in its front matter only.** `pack.toml` holds only the seeds and the default schedules.
- **The generic "how to do this well" lives in the shared skills library,** so any role in any pack can reuse it.

| Rank | omp model role (seeded default) | Started by | Owns | Talks to |
|---|---|---|---|---|
| **Advisor** | `otto-advisor` (Opus 5.5) | `otto init` (one, long-lived) | Advice; no work | The orchestrator, on request or schedule |
| **Orchestrator** | `otto-orchestrator` (`@default`) | `otto init` | The portfolio: which projects run, managers, check-ins | Owner, advisor, managers |
| **Manager** | `otto-manager` (`@default`) | Orchestrator | One project: spec → tasks, dispatch, acceptance | Orchestrator, its workers |
| **Worker** (any worker-rank role) | `otto-worker` (`@default`) or `otto-worker-hard` (`@slow`), per task, or the role's own model role | Manager | One task: implement, check, review or sense-check; submit | Its manager, its sub-agents |
| **Sub-agent** (any sub-agent-rank role) | The role's model role | Worker | A narrower piece of a task | Its worker |

- **Models are chosen the omp way.** Each role is an omp **model role**, so you pick models exactly as in omp:
  - its `/model` Roles view, `omp config set modelRoles.otto-manager <model>`, or a model preset;
  - **any model omp can reach** works (Claude, ChatGPT/Codex, others);
  - fallbacks are omp's own `retry.fallbackChains`.
- **Defaults are arbitrary seeds.** `otto init` writes them only where a role is unset: Opus 5.5 for the advisor; the others point at omp's own default model (`@default`), with `@slow` for hard workers. Change any of them at any time; the tool never overwrites your choice.
- **When a change takes effect:** for new agents. A resumed session keeps its model unless switched explicitly at a settled point. Status shows both the configured role and the actual model.
- **Per agent or per task,** any model can be named instead (e.g. `otto spawn … --model openai-codex/<id>`, or a task's model field). The manager picks `otto-worker` or `otto-worker-hard` from the task's difficulty, or names a model.

## A3. Concepts
| Concept | What it is |
|---|---|
| **Pack** | A versioned folder of role instructions, skills, sub-agent definitions, project templates and defaults (schedules, skills per role, model-role seeds). **One pack per project.** Megado is the first; other packs are other protocols on the same tool. |
| **Project** | A **spec folder** of documents, kept in the database as revisions and edited by **check-out and check-in**; plus settings (repo, branch, check command, pack). One active manager per project. |
| **Task** | Planned by the manager from the spec. **Code tasks** land; **non-code tasks** (a review, a sense-check, research) are done when the manager accepts their submission. Each assignment keeps the spec snapshot it was given. Its states run `todo → running → submitted → done`, plus `blocked` and `cancelled`. **Workers submit; managers accept;** a code task is **done only once its checked commit has landed.** One current attempt at a time. |
| **Agent** | One seat in the tree: role, parent, project or task, model, session reference, state, and **host** (`otto` if `otto run` runs it, `external` if an outside session holds it) |
| **Message** | The one way to communicate and escalate, up or down the tree or to the advisor. It has an id, a reply link, a kind, needs-reply and a delivery state. |
| **Schedule** | A recurring reminder or advisor consultation for an agent |
| **Event** | An append-only record of every change: the history and the status source |

## A4. Key behaviours
- **Spawn:** check the hierarchy, compose the instructions (role file + skills index + role-specific inputs), start the session, record it.
- **Spec folder:**
  - check-out writes the files and records their base revisions;
  - check-in commits the changed files in one transaction, or refuses them all if any changed underneath;
  - different files edited in parallel both succeed;
  - refresh and release are available.
- **Spec → tasks:** the manager's skill. A spec change messages the manager, who updates the tasks with explicit edit and cancel commands. For **each running assignment** the manager chooses **continue, amend or cancel**, and the worker is told. A submission is checked against its assignment, so one that races a cancel is refused.
- **Messages:** kept in SQLite until acknowledged, and delivered **at least once**, only when the recipient's session has settled (never pushed into a busy one).
  - **Acknowledged** means the recipient's turn ended normally after receiving it, or it replied.
  - The message id goes in the text and travels as an **operation key** (`<message-id>/<step>` when one message causes several changes) on the commands it triggers, so a replay can't create a second task, worker or reply.
  - The guarantee covers **the tool's own state,** not arbitrary shell or external effects.
  - An answer resumes the asker.
- **Advisor:** the orchestrator can ask at any time (a message with needs-reply). On schedule (every 180 minutes by default), the advisor gets a snapshot (mandate, status, spec index, **earlier advice and what was decided about it**) and returns advice. The orchestrator records **adopt, defer or reject** for each point, and checks what it adopted. The advisor keeps its own session, so its context carries over.
- **Turn-end check:**
  - on each manager settle, **unfinished work** with nothing in progress earns a strike. Unfinished work means tasks ready to start, submissions awaiting acceptance, or spec changes not yet reconciled;
  - strike 1 nudges the manager, strike 2 tells the orchestrator;
  - a dispatch or a marked blocker resets the count.
  - It runs in observation mode at first, and is enforced from the pilot's second half.
- **Failure and recovery:**
  - a dead or failed session is marked with its reason, and its parent is told;
  - on restart, the tool reconciles its records with reality and never silently replaces a session;
  - a resumed agent gets a short **"you were interrupted"** prompt with its task and last known state, and its worktree is kept;
  - **stop, cancel and replace are distinct;**
  - a stale attempt's submission is refused.
- **Landing:** rebase → check that exact commit → refuse if the target moved → fast-forward only. The task records the submitted and checked commits and becomes done only after landing. A restart reconciles the record against Git.
- **Attach (bring your own session):** **carved out of v1** into `projects/attach/`, which the tool builds on itself **as the pilot.** v1 reserves:
  - the `host` column;
  - a **current binding id**, checked on every identity source;
  - the identity lookup (`--as`, then `OTTO_AGENT`, then `.otto/agent`);
  - the one-holder-per-seat rule, with a handover that can't be interleaved.

  So attach should slot in without schema changes; if not, the follow-up adds a small migration. The design is below. Usually `otto run` starts every agent, but any outside session (Claude Code, Codex, an omp window) can take a seat:
  - **The seats you can attach:** `otto attach advisor`, `orchestrator`, `manager --project <name>` or `worker --task <id>`, run from inside that session. Sub-agents stay inside omp, under their worker;
  - attaching records the seat as `external`, stops any `otto run` process holding it (one holder per seat, always), and writes the identity to `.otto/agent` in that working directory. Taking a seat from another outside session needs `--force`, and stale bindings are refused;
  - it returns a **handover packet**: the role guide, skills, mandate, current work and inbox instructions;
  - from then on that session uses the ordinary CLI (`otto spawn`, `otto send`, `otto inbox`, `otto task …`) as that agent. Everything it starts below it is normal and runs under `otto run`;
  - its messages and reminders wait in its inbox, because the tool can't push into a session it doesn't run. Its role guide says to check `otto inbox` each turn. (A Claude Code hook that shows pending messages automatically is deferred.)
  - the idle-manager check skips external seats, since the tool can't see their turns;
  - `otto detach` hands the seat back, and `otto run` starts a fresh session for it with a handover note.

  Nothing else changes: no new tables, no second message path, no second spawn path.
- **Status:** one digest generated from the database:
  - projects and tasks by state;
  - agents, and how long since each was last active;
  - each seat's configured model role and its actual model;
  - pending messages, failures and upcoming schedules.

## A5. Out of scope (deliberately)
- spend limits;
- a launch gateway;
- authenticated decisions;
- effect ledgers;
- process custody;
- automatic dispatch;
- an automatic spec→task parser;
- pack stacking;
- cloud sync in v1;
- Herzchen;
- Otto's owner service.

---

# Part B: how we build it

## B1. Shape
- **One machine** (a Mac or a Linux cloud box) runs everything.
- **One Python package** provides the `otto` CLI and **`otto run`**, a supervisor kept alive by launchd or systemd. It owns every agent's harness process, delivers messages, fires schedules and runs the turn-end check.
- **State:** one local SQLite file holds **the tool's state**. omp's own directory holds sessions and logins, and the repos, worktrees and spec checkouts live on disk. Moving machines means stopping `otto run` and copying all of that; the docs (D4) cover it with a restore exercise.

## B2. Harness: oh-my-pi (omp), pinned
**The pin:** the latest release at S0 (18.14.0 today, which needs Bun ≥1.4.4), with the matching `omp-rpc` client. We bump it deliberately, not automatically; omp ships several releases a week.

**Why omp over upstream Pi:**
1. It has **subscription login built in:** Claude Pro/Max, ChatGPT/Codex, and others.
2. It has a **reliable "all done" signal:** `session_settled`. That's stricter than Pi's `agent_settled`, because it also accounts for background jobs.
3. It has **built-in sub-agents** (`task` agents, defined in markdown, with a model per sub-agent and nesting).
4. It has a **Python RPC client.**
5. **Astrid already pins and installs it** (`@oh-my-pi/pi-coding-agent@18.12.6`, with checksum-verified binaries for Mac, Linux and Windows).

**How the tool uses omp:**
- **The advisor, orchestrator, managers and workers** each run as an `omp --mode rpc` process owned by `otto run`. Instructions go in with `--append-system-prompt`, and the session id and file are recorded.
- **Prompt semantics:** the command response means the prompt was **admitted**; `prompt_result` reports how the turn ended (yield, error or abort); **done** means `session_settled`, which also covers queued input and background work. Settled does not mean successful, so the tool reads both.
- **Resuming** means `--resume <exact session file>`, then checking the returned session identity. If it isn't the same session, the agent is marked failed; it is never silently replaced. (`open_session` picks a conversation from a directory and can create a new one, so it isn't used for recovery.) Delivering a message means sending a `prompt` once the session has settled.
- **Client:** omp's Python RPC client (`sdk/python/omp-rpc`, alpha, Python ≥3.11), pinned together with the omp version. We don't write a second transport.
- **The harness boundary:** all oh-my-pi-specific code sits in one module (`src/otto/runtime/harness/omp.py`), behind a narrow interface: start, prompt, events, resume, stop, login status. Nothing else imports omp. A different harness later is an adapter, not a rewrite. The interface is fixed in the L0 contract (`projects/contract.md` §2b).
- **Sub-agents are omp's own `task` agents,** defined in the pack's `agents/*.md` (role, model, tools, the result shape). `packs/*/agents` isn't discovered automatically, so the generated config overlay exposes it. Only workers delegate this way, enforced through omp's spawn policy; the four upper roles are separate RPC sessions. A sub-agent's result returns to its worker; the durable-message promise covers seats, not helpers. Sub-agents **inherit the worker's skills and logins** (accepted, not fought). The tool records them from omp's `subagent_*` events, which must be subscribed to; it doesn't spawn them itself.
- **Worker isolation:** each worker gets a git worktree of the project branch.

## B3. Authentication (subscriptions)
- **The tool holds no credentials.** You log in **once per machine** with omp's own flow. **One omp profile holds all your logins:** Claude and ChatGPT side by side, and several accounts of one provider through omp's own account routing. A separate `--profile` is optional, only for a fully separate store:
  - ChatGPT/Codex: `omp login openai-codex-device` (a **device code**, which suits a cloud box). Credentials are stored as the `openai-codex` provider;
  - Anthropic uses **paste-the-redirect**;
  - optional: `omp auth-broker login <provider> --via=user@host` can log a remote box in from your Mac.
- **omp keeps the credentials** in its own SQLite store, refreshes them safely across processes, and supports **several accounts**. Which model, and so which provider, each role uses is set through its model role (A2).
- **`otto doctor`** checks login status by asking omp which providers are signed in, as Astrid already does. It never reads the token store.
- **Risk:** Anthropic can restrict subscription use from third-party clients. omp's `retry.fallbackChains` can fall back to another provider.

## B4. Data model (one SQLite file)
| Table | Key fields |
|---|---|
| `projects` | id, name, pack, pack_version, repo, branch, check_cmd, status, manager_id |
| `documents` / `revisions` / `checkouts` | The spec folder: path → head revision; revisions with parent and sha256; checkouts with a base map and state |
| `tasks` | id, project_id, title, brief, done_when, model (a role such as `@otto-worker-hard`, or an exact model), spec_snapshot, state, assignee_id, result |
| `agents` | id, rank, role, role_hash, pack_version, model, host (`otto` or `external`), binding_id, parent_id, project_id, task_id, session_id, session_file, cwd, state, strikes, last_event_at |
| `messages` | id, in_reply_to, from, to, task_id, kind, body, needs_reply, delivery, resolved_at |
| `schedules` | id, agent_id, kind (`checkin` or `consult`), every_minutes, prompt, next_due, paused |
| `events` | id, at, actor, kind, subject, project_id, data |

**Sync-ready for later, at no cost now:**
- every id is a UUID;
- every project-scoped row carries `project_id`;
- events are append-only.

- **Global rows** (the advisor, the orchestrator, portfolio-level messages and schedules) have no `project_id`; everything else does.

This makes a later Turso sync of **one project, several, or everything** mostly a replication choice. It may still need small schema changes; we don't promise otherwise.

**Also stored** (the data contract from the plan check): task dependencies; a per-task model override; each agent's config overlay (and profile, if not the default); and enough to recover a session. A spec save writes its "spec changed" message **in the same transaction.** An agent that fails or is cancelled **releases its running task** back to `todo`.

## B4b. Skills and model routing
- **Generic skills and pack skills.**
  - A **shared skills library** (`skills/`, at the tool level) holds generic skills any pack can use: best-practices, over-engineering, sense-check, review, handoff, land.
  - A **pack's own `skills/`** holds protocol-specific ones (Megado's spec-project, plan-tasks, check-in, advise).
  - Each role's front matter lists which skills it gets, by name, from either place.
  - **At spawn,** the tool writes a per-agent **`--config <file>` overlay** whose `skills.customDirectories` points at the shared library and the pack, and passes **`--skills <names>`** to filter down to that role's list. (Custom directories add places to look; `--skills` picks from what's found.) Sub-agents inherit their worker's skills.
  - Skills use the open **Agent Skills** format (`<name>/SKILL.md` with a name and a description), so the same files also work in Claude Code, Codex and other tools.
- **Which model and provider each agent uses:** omp decides, through its model roles (A2).
  - **At spawn,** the tool passes the **role's model role** (from its front matter; by default its rank's, e.g. `@otto-worker`), or the task's or caller's override (a role alias or an exact `provider/id`). It never puts `modelRoles` in the config overlay, because an overlay would beat your own choices.
  - **The tool holds no model table:** no tiers-to-models map and no fallback lists. The pack only lists the seeds `otto init` writes when a role is unset.
  - **Exact ids** come from omp's catalogue (`omp models`). A ChatGPT subscription is the **`openai-codex`** provider, not `openai`.
  - **Sub-agents** use the same mechanism: an agent definition's `model: "@otto-worker"` (or any model), and omp's account routing within the profile.

## B5. The Megado pack (v1)
```
packs/megado/
  pack.toml        # model-role seeds, default schedules (skills per role live in each role's front matter)
  roles/           advisor.md orchestrator.md manager.md worker.md
                   sense-checker.md over-engineering-checker.md reviewer.md scout.md
                   (each with front matter: rank(s), skills, model role; omp agent definitions are generated from these)
  skills/          Megado-only skills: spec-project, plan-tasks, check-in, advise
  templates/project/   the spec-folder layout
skills/            (tool level, shared by every pack) sense-check, over-engineering,
                   best-practices, review, handoff, land
```

**A complete role file, as an example** (`packs/megado/roles/sense-checker.md`):
```markdown
---
name: sense-checker
ranks: [worker, sub-agent]        # where it may run
skills: [sense-check, best-practices]
model: "@otto-worker-hard"        # an omp model role; it defaults to its rank's
---
You check whether a spec, plan or change will actually reach its stated goal.
Read the goal first, then the material. Report, most important first: what will
not reach the goal and why; ambiguities that a builder would have to guess; what
is missing; what is over-built. Be concrete (file, line), and say what you would
change. Do not rewrite the material yourself.
```
The tool wraps this with a short per-rank wrapper: as a worker it submits its report to its manager; as a sub-agent it returns the report to its worker.
- **Sources:** Megado's method (lifecycle, pragmatic review, the XHARD rubric), the Astrid briefs (orchestrator, manager), and the retro's runbook and minimal structure.
- **Size:** about 3,000 words. Skills use the Agent Skills format (`SKILL.md` with a name and a description), which omp loads on demand.

## B6. Acceptance
**Observable behaviours, each with a test:**
1. Readiness respects dependencies and terminal states.
2. Landing checks the rebased commit, and a failure or a moving target leaves the target unchanged. A code task is done only once landed.
3. Check-out and check-in handle concurrency: conflicts, idempotency, tombstones, crash recovery.
4. A message reaches its recipient at least once, even across a crash around admission; a repeat changes nothing; and an answer resumes the asker.
5. Schedules coalesce missed slots, respect pauses, and queue while the agent is busy.
6. Spawn enforces the hierarchy, composes the instructions, and records the session.
7. The turn-end check strikes, nudges, escalates and resets.
8. Restart reconciliation works: identity is kept or failure reported, the interrupted work continues, and stale attempts are refused.
9. Status reads never write.
10. `otto doctor` reports login readiness without reading tokens, and that each `otto-*` model role resolves.
11. Pack roles: a specialist role runs at worker rank (`otto spawn sense-checker`) and at sub-agent rank (through omp) from one role file, and its recorded instructions hash matches that file.

*Attach and detach is acceptance for the follow-up project `projects/attach/`, not for v1.*

*§B6 is milestone 1 (base qualified). The pilot's acceptance is in `projects/attach/PROJECT.md`, plus the scenarios below.*

**The pilot** is the tool building `projects/attach/` on itself, with all five ranks:
- a sub-agent through omp's `task`;
- a mid-work spec change;
- two concurrent checkouts;
- an advisor consultation, both scheduled and on request;
- a restart during delivery;
- an alternative pack;
- a sense-checker as a worker task, and an over-engineering checker as a sub-agent;
- a code task that is done only after it lands;
- the owner's goal, measured: interventions, long stalls and idle-check false alarms (`DECISIONS.md` O7).

## B7. Testing
**Real storage, Git and processes; faked model replies.** The full design and the test list are in `16-three-reviews.md` §2.

| Layer | What's real | What's faked |
|---|---|---|
| **Unit** | The rules | — |
| **Acceptance** | The app, SQLite, Git, the supervisor and the installed CLI | omp, as a tiny **fake RPC process** behind the real `omp-rpc` client; the clock |
| **omp compatibility** | **The installed omp binary**, credential-free | The model, as a **loopback scripted provider** |
| **Live** | Subscriptions and real models | — |

- **Live tests run only at the trial, the vertical slice and the pilot.**
- **One end-to-end journey test** (owned by D3, about 600 lines; it lives in the compatibility layer because it uses the real omp binary):
  - **What runs:** the installed wheel and the real `otto run` drive the real omp binary against a **scripted loopback model**. The scripted model replies with tool calls (`bash: otto spawn …`, `write`, `task`), so the agents drive the tool exactly as real ones would. Nothing writes to the database behind their backs.
  - **The journey:** install → init → `project new` → the manager plans and dispatches → a specialist worker, plus a native helper → a spec amendment mid-work → **one `SIGKILL`** after the amendment is committed but before the message is acknowledged → replay → submit → checked landing → both advisor paths → status.
  - **How it checks:** every step asserts on `--json` output and Git, waiting on settle events, never on sleeps. Schedules use a test clock.
  - **The live variant:** the same checkpoints, real models, and assertions on outcomes rather than wording. It becomes the pilot's backbone.
  - **Not built:** a scenario language, an agent simulator, record and replay, or LLM judges.
- **Crashes:** a production no-op hook at each named crash point (L0) lets a test kill the process and restart it.
- **CI:** one serial run, about 3–5 minutes, with no models and no credentials. A skip, a hang or a leaked process fails it.
- **Not tested:** spend or authority suites, every provider-and-model combination, prompt wording, or LLM judges for correctness.

---

# Part C: the path from current code

**What we reuse:**

| From | What |
|---|---|
| **Otto (frozen, tagged)** | The Megado method (translated into the new roles, not copied); the leaf and filesystem validators; the landing sequence from `landing.py`; its tests as behaviour cases |
| **Astrid** | The omp install recipe (pinned version, checksums, Bun), the login-status check, the ideas from its launcher and stdio host |
| **omp** | Login, the credential store, RPC, sub-agents, skills, model roles |
| **Our retro** | The role instructions and the skills |

**Everything else is new and small.** The tasks, managers, estimates and schedule live in **`14-plan.md`** only. What to lift, simplify or leave behind in Otto is in `16-three-reviews.md` §1.

**Later (not v1):**
- **Turso sync of one project, several or all:** the schema is built for it, though small changes may still be needed.
- **omp's auth gateway** if several machines need to share credentials.
- **A second pack.**

## Decisions
- **Models:** any model, chosen through omp's model roles. The seeds are arbitrary; the advisor's is Opus 5.5. A change applies to new agents; a running seat switches only explicitly.
- **One orchestrator and one advisor per database;** a separate organisation uses another file.
- **Attach:** the advisor, orchestrator, manager and worker seats. It's built by the tool on itself, as the pilot.
- **Roles:** fixed ranks in the tool; roles, including specialists, in the pack.
- **Intervals:** the check-in every 60 minutes; the advisor every 180 minutes.
- **omp:** pin the latest release at S0.
- **Pilot project:** attach (`projects/attach/`), built by the tool on its own repo.

---

## Change history (newest first)
**v3.5 (30 Oct)** applies the parallel-build and journey-test reviews (`17-parallel-and-journey.md`):
- **rank is stored separately from role;**
- **a short wrapper per rank;**
- **the role's skills live only in its front matter;**
- **attach reserves a binding id;**
- **a single end-to-end journey test** (B7).

**v3.4 (30 Oct)** makes two changes:
- **roles are defined by the pack,** on top of five fixed ranks, so specialists such as a sense-checker or an over-engineering checker are just roles with fixed instructions (A2);
- **attach is carved out of v1** into `projects/attach/`, which the tool builds on itself **as the pilot.**

**v3.3 (30 Oct)** applies the three Astra reviews (`16-three-reviews.md`):
- **five contracts:** acknowledgement; work recovery; done only after landing; the attach handover; spec changes during work;
- **attach** covers four seats;
- when a model change takes effect;
- the advisor's follow-through;
- a broader idle check;
- **testing (B7);**
- **Part C** is reduced to the reuse table, with a pointer to the plan.

**v3.2 (30 Oct)** applies the owner's decisions:
- **models are chosen the omp way:** any model, through omp model roles, with arbitrary defaults (the advisor defaults to Opus 5.5);
- **one omp profile** holds all your logins;
- **default intervals:** a 60-minute check-in and a 180-minute advisor consultation;
- **pin the latest omp;**
- **attach:** an outside session can take a seat (A4).

**v3.1 (30 Oct)** applies Astra's plan check (`evidence/spec/astra-plan-check.md`): omp profiles, model ids, config overlays, prompt semantics, resume, and at-least-once delivery. See `14-plan.md` §8.

**v3 (30 Oct)** adds the owner's latest direction:
- **an advisor role;**
- **runs on one machine** (a Mac or a cloud box);
- **one local SQLite file now,** with Turso sync of some or all projects later;
- **subscriptions,** using **oh-my-pi**'s login.
