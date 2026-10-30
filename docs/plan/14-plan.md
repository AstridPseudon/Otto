# The plan, end to end (v3.2)

**This is the single place the whole plan lives.** Everything else is background or detail:

| Question | Where |
|---|---|
| **What we're building** | `13-spec.md` (v3.5): the system, how we build it, acceptance |
| **Start** | `START-HERE.md` (reading order), `GLOSSARY.md`, `DECISIONS.md` |
| **Why** | `README.md` → `01`–`03` (what worked in the Astrid program), `07` (first-principles review), `10`–`12` (the 90:10 path and your minimal design) |
| **History and options considered** | `05`–`09` (the Otto paths we didn't take); `evidence/` (all the investigations) |
| **The checks on this plan** | `evidence/spec/astra-plan-check.md` (§8 below); `16-three-reviews.md` (remove, test, gaps → v3) |
| **The one-page version** | `15-in-short.md` |
| **This file** | The goal, design answers, managers, tasks by tier, schedule, how we know we're done |

## 1. The goal
A small tool that runs an organisation of agents on **one machine** (a Mac or a cloud box), with:
- five ranks: **advisor** (high) → **orchestrator** (mid) → **manager** (low) → **worker** (mid or high, per task) → **sub-agent**;
- **one spawn path,** through **oh-my-pi** (omp) with subscription logins;
- **packs** (Megado first) holding role instructions, skills, sub-agent definitions and model-role seeds;
- **projects** as spec folders, with check-out and check-in, turned into tasks;
- **one local SQLite file** for the tool's state (omp keeps sessions and logins), with Turso sync later.

**The only structure:**
- the hierarchy;
- the orchestrator's reminders and advisor consultations;
- a turn-end check that nudges idle managers.

**Done means** the pilot (§6) passes on a real project with all five ranks.

## 2. Design answers
- **Generic skills:** yes.
  - A shared skills library sits next to each pack's own skills. **Each role's front matter** picks its skills (`pack.toml` holds only the seeds and the schedules).
  - At spawn, the tool writes a per-agent `--config` overlay pointing omp at both folders, and passes `--skills <names>` to filter to that role's list.
  - Sub-agents inherit their worker's skills. We accept that rather than fork omp.
  - Skills are in the open Agent Skills format, so they also work in Claude Code and Codex.
- **Choosing models: the omp way.**
  - Each role is an omp **model role**: `otto-advisor`, `otto-orchestrator`, `otto-manager`, `otto-worker` and `otto-worker-hard`. You pick models in omp's `/model` Roles view or with `omp config set`, and any model omp can reach works.
  - `otto init` seeds arbitrary defaults where a role is unset: Opus 5.5 for the advisor; omp's `@default` for the rest, with `@slow` for hard workers.
  - Spawn passes the **role's model role**, from its front matter; by default that's its rank's (e.g. `@otto-manager`, `@otto-worker`). Any agent or task can name another model instead, e.g. `openai-codex/<id>` (a ChatGPT subscription) or `anthropic/<id>`.
  - Fallbacks are omp's `retry.fallbackChains`.
- **Logins:** one omp profile holds all of them (Claude and ChatGPT side by side, plus several accounts per provider through omp's account routing). A separate profile is optional.
- **What's reusable elsewhere:**
  - the skills library (any Agent Skills tool);
  - the pack format (other protocols);
  - the omp install pattern (shared with Astrid);
  - the SQLite schema and spec-folder sync (a protocol, later).

## 3. Managers
The orchestrator runs the **omp spike** (S0), then writes the **lifecycle and configuration contract** (L0) with the four managers. Then **four projects run in parallel,** each with one manager and its own spec folder (`projects/state`, `runtime`, `pack`, `delivery`).

**More speed comes from workers inside each project, not from more managers.** The busiest point has about eight workers at once; for example, R2 and R3 run as separate workers after R1. Everything integrates continuously into **one new sibling repo** (§11):

| Manager | Owns | Days |
|---|---|---:|
| **M1 State** | The schema, the spec folder, tasks and attempts, spec → tasks, the CLI, status | 12 |
| **M2 Runtime** | `otto run`: the omp RPC lifecycle, spawn and launch configuration, durable message delivery, recovery and stop/resume/replace, recording sub-agents, **the vertical slice** | 12.5 |
| **M3 Pack and behaviour** | The pack format and loader, the skills library, the Megado role guides, skills, sub-agent definitions and templates, the alternative-pack fixture, **schedules and the advisor**, **the idle-manager rule**, **pack-defined roles** | 11 |
| **M4 Delivery and integration** | omp install and logins, OS service units, landing, docs, **the acceptance harness**, **the pilot** and its contingency | 13.5 |
| Orchestrator | X0a, B0, S0, L0, integration, the pilot gate, X0b | 4.5 |

**Ownership boundaries:**
- **M1** owns the migrations. Other managers propose schema changes against the L0 contract, and M1 merges them; it doesn't implement them all.
- **M2** keeps all lifecycle failure handling. **M3** owns only the strike/nudge policy.
- **The `land` skill:** M3 owns its text; M4 owns the script and its tests.
- **M3** owns every `.md` under `packs/` and `skills/`.
- **M4** owns `install/`, the acceptance harness and the pilot.

## 4. Tasks
**Tiers:**
- **Normal:** routine, a known pattern, directly checkable.
- **X-hard:** bounded logic or an adapter, with a real but contained risk.
- **Super-hard:** a specific invariant that's hard to get right under concurrency, recovery or a cross-process protocol. There are three:
  - **C3:** a check-in commits all its paths or none, and a crash never falsely advances a checkout or publishes twice;
  - **R1:** two processes never continue the same session, and recovery keeps identity or reports failure;
  - **R3:** a message survives a crash around admission, and the reply reaches the right asker.

Every task is 3 days or less, except C3 and R1 (3.5 days each; each splits into two subtasks at L0). A task is done when its listed check passes: automated checks in CI, live checks (S0, VS, fresh machines, the pilot) logged with evidence. A workaround named in S0 must be demonstrated before it clears a dependency.

### Orchestrator
| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| **S0** | **omp spike:** pin the latest release (18.14.0 today) with the matching `omp-rpc` client; RPC admission vs `prompt_result` vs `session_settled`; `--resume <exact file>` plus an identity check; one `task` sub-agent with `subagent_*` frames on; `--model @otto-<role>` with custom model roles set to `anthropic/…` and `openai-codex/…` in one profile; custom roles appear in `/model`; a `--config` overlay plus `--skills`; exposing a pack's `agents/`; device-code login on Linux and paste-redirect on the Mac; the installed binary driven by a loopback scripted provider (for the test suite); model-change and spawn-policy behaviour | X-hard | 1.5 | — | A findings note; each item demonstrated live, or a workaround demonstrated |
| **L0** | **Lifecycle and configuration contract:**<br>• bootstrap (`init` creates the advisor and orchestrator, and the owner's mandate);<br>• one active manager per project;<br>• how the CLI asks the supervisor to launch;<br>• the resolved launch config (model role or override, overlay, skills, instructions);<br>• task assign, reject and cancel;<br>• session identity;<br>• which configuration wins (pack precedence);<br>• the interfaces for store transitions, delivery and settle notifications;<br>**And the five contracts from the reviews:**<br>• **acknowledgement:** a message is handled when the recipient's turn ends normally or it replies; commands carry the message id as an operation key;<br>• **work recovery:** one current attempt per task; an interrupted prompt; the worktree kept; stop, cancel and replace kept distinct;<br>• **landing → done:** done only when the checked commit is on the target;<br>• **attach is reserved:** the `host` column, a **current binding id** checked on every identity source, a handover that can't be interleaved, and identity lookup and one holder per seat (the full contract is in `projects/attach/`);<br>• **ranks vs roles:** rank is stored separately from role; which ranks a role may run at; a short wrapper per rank (a worker submits, a helper returns to its worker); instructions recorded as the pack version plus the role-file hash, on both paths; the role's skills live **only in its front matter**;<br>• **the frozen CLI surface:** the operation-key flag, `--json` fields for status, tasks, inbox and schedules, and `project new --from`;<br>• **test seams:** the crash-point list, barriers and the test clock;<br>• **spec changes during work:** the manager continues, amends or cancels each running assignment;<br>**Plus:** when a model change takes effect; only workers delegate natively; the named crash points | X-hard | 2 | S0 | Each manager signs off; interface types, stubs and the crash-point list are committed |

### M1 State (12 days)
| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| C1 | **Schema and store:**<br>• 9 tables and UUIDs;<br>• `project_id` on project rows; global rows for the advisor, the orchestrator and portfolio messages;<br>• task dependencies and model overrides;<br>• each agent's **rank and role** (stored separately), model, host (`otto` or `external`), binding id and config, plus recovery info;<br>• the event log | Normal | 2 | L0 | Migrations run; round-trip tests pass |
| C3 | **Spec folder:**<br>• `open`, `save`, `refresh`, `release`;<br>• a check-in is one transaction and is refused if any path is stale;<br>• tombstones for deletes;<br>• Otto's leaf and filesystem validators, extracted, with the **resulting tree** validated inside the transaction;<br>• the "spec changed" message is written in the save transaction | **Super-hard** | 3.5 | C1 | Tests pass for:<br>• different paths both save, and the same path conflicts;<br>• a repeat save is a no-op;<br>• a multi-file rollback;<br>• a dirty refresh;<br>• tombstones;<br>• a crash between the commit and the checkout update neither advances the base nor publishes twice |
| C4 | **Tasks:**<br>• `todo → running → submitted → done`, plus blocked and cancelled;<br>• dependencies and readiness;<br>• submit, accept and reject;<br>• a model override (a role alias or an exact model);<br>• **one current attempt per task;** a stale submission is refused;<br>• the task records the submitted and checked commits, and a code task is **done only once landed**;<br>• a failed or cancelled agent releases its task | X-hard | 2 | C1 | Tests pass for state, readiness, dependencies, rejection, release, stale submissions and "accepted ≠ landed" |
| C2 | **CLI:**<br>• `init` (the root agents, the default schedules);<br>• `project new` (from the pack template);<br>• `doctor` (login status through omp, never reading tokens; checks that each `otto-*` model role resolves);<br>• `init` seeds the model roles where unset;<br>• schedule list, pause and resume | Normal | 1.5 | C1, P1, P5 | The commands work on a fresh machine, and `project new` works with both the Megado template and the alternative-pack fixture |
| C5 | **Spec → tasks:**<br>• a durable save notification reaches the manager;<br>• each assignment keeps its original spec snapshot;<br>• explicit task edit and cancel commands (the manager interprets; nothing reconciles automatically);<br>• for each running assignment the manager chooses **continue, amend or cancel**, and the worker is told;<br>• a submission is checked against its assignment | X-hard | 2 | C3, C4, R3, P3 | A changed spec reaches the manager; each running assignment gets a recorded decision; a submission racing a cancel is refused |
| C6 | **`otto status`:** counts, agent activity, pending messages, failures, upcoming schedules, sub-agents, each seat's configured model role vs its actual model | Normal | 1 | C4, R3, R4, R6 | All fields are correct, and a read never writes |

### M2 Runtime (12.5 days)
| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| R1 | **Supervisor:**<br>• `otto run` owns one omp RPC process per agent, through `omp-rpc`;<br>• it tracks admission, `prompt_result` and settle;<br>• restart recovery via `--resume <exact file>` plus an identity check, then an **interrupted** prompt carrying the task and its last state; the worktree is kept;<br>• it defines what happens if the supervisor itself dies | **Super-hard** | 3.5 | L0, C1 | Kill-and-restart tests pass: the agents reconcile; a missing session, or a session whose recorded omp profile differs from the one now configured, is marked failed; **a supervisor killed while a child survives:** on restart, the new supervisor adopts or stops that child *before* anything resumes, so no two processes ever hold one session; nothing is silently replaced |
| R2 | **Spawn:**<br>• spawn by **role name** (`otto spawn sense-checker --task <id>`), with the rank check;<br>• the hierarchy check;<br>• instruction composition;<br>• the resolved config: the **role's model role from its front matter** (its rank's by default: `@otto-worker` at worker rank and sub-agent rank, `@otto-manager` for a manager, and so on), then any override; a generated `--config` overlay (skills and agents folders, never `modelRoles`), `--skills`;<role>` or an override, a generated `--config` overlay (skills and agents folders, never `modelRoles`), `--skills`;<br>• a worktree per worker | X-hard | 2 | R1, P1 | Instructions, model and skills are correct per role; an override wins; your omp model choices are never overwritten; a wrong role is refused |
| R3 | **Messages:**<br>• send, inbox, reply;<br>• kept in SQLite until acknowledged (per L0), and delivered at least once **when the recipient has settled** (never pushed into a busy session);<br>• the message id as an operation key, so a replay can't create a second task, worker or reply;<br>• replies correlated to the asker | **Super-hard** | 3 | R1 | Tests pass for:<br>• a crash just before and just after admission;<br>• a repeat delivery changes nothing;<br>• a busy reply waits;<br>• an answer resumes the asker |
| VS | **Vertical slice:** spawn → a non-blocking ask → the answer → the same session continues → settled → restart, including crashes around admission | X-hard | 1.5 | R2, R3 | A scripted run passes with real subscription logins on one machine |
| R5b | **Lifecycle:**<br>• `agent stop/resume/replace`, kept distinct from cancel;<br>• failure handling;<br>• the parent is told and the task released; the original worktree is kept | X-hard | 2 | R1, C4 | Tests pass for each path, including a resumed worker that finds its task reassigned: it is told, it stops, and any submission from it is refused. "Replace" means a fresh session for the same seat, with a handover note; the old session is stopped first |
| R6 | **Sub-agents:** subscribe to omp's sub-agent frames and record them against their worker; native delegation is enabled for workers only (omp spawn policy) | Normal | 0.5 | R2, P4 | Sub-agents appear in status |

### M3 Pack and behaviour (11 days)
| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| P1 | **The pack format:**<br>• `pack.toml` and its loader;<br>• the skills library layout;<br>• **roles with ranks:** each `roles/<name>.md` has front matter (allowed ranks, skills, model role);<br>• skills per role and the model-role seeds;<br>• the organisation-level pack for the advisor and orchestrator;<br>• version behaviour | Normal | 1.5 | L0 | A test pack loads; its roles, seeds and skill lists resolve; an unknown rank is refused |
| P2 | **Role guides:** advisor, orchestrator, manager, worker, plus the specialists sense-checker, over-engineering-checker, reviewer and scout, **translated** from Megado (not copied). The orchestrator records **adopt, defer or reject** for each piece of advice | Normal | 2.5 | P1 | Each is under 400 words, with none of the old commands, slots or allowances |
| P3 | **Skills:** spec-project, plan-tasks, sense-check, over-engineering, best-practices, review, handoff, land (the text), check-in, advise | Normal | 2.5 | P1 | Each is in Agent Skills format; **a fresh agent performs the workflow from them** in a dry run |
| P4 | **Sub-agent definitions generated from role files** for every role allowed at sub-agent rank, exposed through the overlay | Normal | 1 | P1, S0 | A worker spawns one through omp |
| P5 | **Templates:** the project template, plus a tiny alternative-pack fixture | Normal | 0.5 | P1 | The template and the alternative-pack fixture both load and validate through the pack loader (the `project new` end of this is checked in C2) |
| R4 | **Schedules and the advisor:**<br>• the default schedules from the pack;<br>• consultations on request and on schedule, with a snapshot that includes earlier advice and what was decided about it;<br>• the same advisor session continues;<br>• coalescing, pause, busy queueing | X-hard | 2 | VS, C2, P1 | Tests pass: a consultation round-trips with the right snapshot; missed slots coalesce; a paused schedule skips; a busy agent queues |
| R5a | **Idle-manager rule:**<br>• one evaluation per settle;<br>• unfinished work includes tasks ready to start, submissions awaiting acceptance and unreconciled spec changes;<br>• legitimate waiting is allowed;<br>• observation mode, then enforced from the pilot's second half;<br>• a duplicate escalation is suppressed | X-hard | 1 | R3, C4 | Strike, nudge, escalate and reset tests pass |

### M4 Delivery and integration (13.5 days)
| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| D1 | **omp install** for the Mac and Linux, using Astrid's recipe *pattern* with the latest pin, its hashes and Bun ≥1.4.4; **a login guide** (one profile, device code, paste-redirect, the broker optional; choosing models in `/model`) | Normal | 1.5 | S0 | Install smoke tests pass on a fresh Mac and a fresh Linux box |
| D1b | **OS service units** (launchd, systemd) for `otto run`, and `doctor`-green | Normal | 0.5 | D1, C2, R1 | Both fresh machines reach `otto doctor` green and survive a reboot |
| D2 | **Landing:** rebase → check that exact commit → refuse if the target moved → fast-forward only (the sequence from Otto's `landing.py`, without its assessments; **not** `tools/land.sh`); the task is marked done only after landing, and a restart reconciles the recorded commit against Git | X-hard | 3 | L0, C4 | A failed check, a conflict or a moving target leaves the target unchanged; a crash between landing and recording is reconciled correctly |
| D3 | **Acceptance harness** (spec §B7):<br>• a tiny fake omp RPC process;<br>• crash hooks at the L0 crash points;<br>• a loopback scripted provider for the real omp binary;<br>• tests for §B6 1–11, the three invariants and three bridging tests;<br>• one credential-free CI job | X-hard | 3 | L0 (finishes after all mapped tasks) | All of §B6 is green in about 3–5 minutes, with no models used and no leaked processes. Also, **one credential-free journey test** passes, using the installed wheel and the pinned omp binary. It covers init, project import, manager dispatch, a specialist worker and a native helper, a spec amendment mid-work, a crash and replay during delivery, submission and checked landing, both advisor paths, and truthful status at every checkpoint (spec §B7) |
| D4 | **Docs:** README, the pack format, the schema notes, **moving machines** (the state bundle and a restore) | Normal | 0.5 | P1, C1 | A cold reader can set it up and restore it on another machine |
| D5 | **Pilot** (§6) | X-hard | 3 | All pre-pilot tasks | Every scenario's observable outcome is logged |
| D6 | **Contingency:** pilot fixes and a re-run | — | 2 | D5 | The pilot re-runs clean |

### Orchestrator: preserve first, archive last
| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| B0 | **Bootstrap (day 0). DONE 30 Oct:** restart `main` of `AstridPseudon/Otto` fresh (`DECISIONS.md` O2), with old `main` moved to `deprecated`; the package and `otto --version` skeleton; the folder layout and owned paths (`projects/README.md`); the plan package in `docs/plan/`; initial CI (lint, unit placeholder, wheel-install smoke); the landing script (rebase → CI on that commit → fast-forward only). CI grows into the full installed-wheel suite as D3 lands | Normal | 0.5 | O2 decided | The first worker change lands through the script with CI green |
| X0a | **Preserve, before building:** tag the old Otto refs (`a70b3f2`, `bbd9b6d`, `b834793`, every lab and project tip, including packs); a verified bundle and a rehearsed restore; preserve every plan-repo branch | Normal | 0.25 | — (day 0, alongside S0) | The refs are tagged, the bundle restores, and nothing is deleted |
| X0b | **Archive, after the pilot:** move the old plan-repo operating surface (the old root docs, `tools/`, queues) behind a historical index; back up the old Mac installation's live state before it's retired | Normal | 0.25 | D6 | The index exists, the backup is verified, and nothing is deleted |

### Totals
| Tier | Tasks | Days |
|---|---:|---:|
| **Normal** | 15 (C1, C2, C6, R6, P1–P5, D1, D1b, D4, B0, X0a, X0b) | 16.5 |
| **X-hard** | 12 (S0, L0, C4, C5, R2, VS, R5b, R4, R5a, D2, D3, D5) | 25 |
| **Super-hard** | 3 (C3, R1, R3) | 10 |
| **Contingency** | D6 | 2 |
| **Total** | 30 + contingency | **53.5** |

- **Planning range:** about 50–56 engineer-days.
  - v3.1 moves attach (2.5 days) into the follow-up project, which is about 3 days in its own folder.
  - It adds 1 day for pack-defined roles and specialists.
  - v3 had added 8.5 days for the review findings (`16-three-reviews.md` §4).
- **Before v3:** 46 days. v2.1 dropped our model table (−1 day) and added attach (+1.5).
- **v1 was 34,** but it was missing those additions and treated delivery and the spec folder as easier than they are.

## 5. Schedule
| Window (working days) | Running |
|---|---|
| 0–1.5 | S0: the pinned omp and client, real login, session and recovery probes |
| 1.5–3.5 | L0 (the role-file and CLI shapes in its first half-day) · D1 install starts |
| 3.5–5.5 | C1 · P1 · D3 infrastructure (the fake RPC process, the loopback provider, barriers) · D2's Git part against a fake task store |
| 5.5–9 | **R1** · **C3** · C4 · C2 · P2–P5 · D4 · D2 joins the real task records |
| 9–12 | **R2 ‖ R3** (separate workers) · R5b · D1b · R4 and C6 preparation against fixtures · the harness grows |
| 12–14 | R6 · **VS** (live) · C5 · R5a · fresh-agent skill qualification |
| 14–15 | R4 and C6 integration · full installed-wheel qualification, including the journey test |
| 15–18 | **D5 pilot** (idle enforcement switched on halfway through) |
| 18–20 | D6 fixes and a re-run |
| 20–20.5 | X0b archive |

**Critical path:** S0 → L0 → C1 → R1 → (R2 ‖ R3) → VS → R4 → C6 → pilot → contingency → X0b.
- **About 22 working days** with R2 and R3 in parallel. (The previous "23.5" had D6 and the closeout overlapping; done one after another it was 24.)
- **The target is 20.5 days.** It splits R4, C6, D3 and D2 into preparation against fixtures and a short qualification at the end; the effort and the gates stay the same. L0 confirms the splits.
- **The bottleneck is C1 → R1 → R3 → the live VS.** More content or install workers won't shorten it. Managers must also accept finished work promptly. The path is limited by the dependencies and by live testing, not by typing speed.

**The riskiest tasks first.** R1 and R3, then C3, then R2 and the pin and platform compatibility. S0 and VS exist to surface those risks by about day 14, before anything is built on top of them.

**Model guide for the build team** (bootstrap sessions; **advisory**, not binding; the names are illustrative, and the real ids come from S0):

| Who | Model |
|---|---|
| Managers | Low tier (Haiku or Luna) |
| Normal tasks | Low or mid |
| X-hard tasks | Mid (Terra or Sonnet), escalating once on failure |
| Super-hard tasks | High (Sol, Sonnet-high or Opus) |
| Advisor | Opus or Astra |

## 6. How we know we're done
There are four milestones (also in `START-HERE.md`).

**1. Base qualified:**
- B0, X0a, S0, L0 and every C, R and P task, plus D1–D4, pass their "done when" (the pilot, D5, D6 and X0b come after);
- **the acceptance harness** (spec §B6, 1–11) and the **journey test** are green in one credential-free CI run;
- VS and the fresh-machine checks (D1, D1b) are logged.

**2. Pilot passed:**
- **The pilot passes.** **The pilot project is attach** (`projects/attach/`). The tool builds its own next feature on its own repo, while the running tool stays on its installed, pinned version. The observable outcome is logged for each scenario:
  - all five ranks;
  - a sub-agent;
  - a spec change mid-work;
  - two concurrent checkouts;
  - an advisor consultation, both scheduled and on request;
  - a restart during delivery;
  - a tiny second project on the alternative-pack fixture, running alongside;
  - a sense-checker running as a worker task, and an over-engineering checker as a sub-agent;
  - a code task that is done only after it lands;
  - the result is used for real. The candidate build is installed **side by side, in a separate test organisation** (its own `OTTO_HOME` and database), and a Claude Code window is attached there as a manager for a small project, then detached. Production switches only at release;
  - **the owner's real goal, measured:** owner interventions, stalls over 2 hours, and idle-check false alarms, logged for the owner to judge (`DECISIONS.md` O7).

**3. Released:** the owner approves, and the attach-capable version is installed side by side, with a rollback path (`DECISIONS.md` O6).

**4. Closed:** X0b is done, and the next project or pack is chosen.

**What happens after:**
- **Choose the next pack** or project.
- **Turso sync** when a second machine needs it.

## 7. Decisions
**Made (30 Oct):**
- **Models:** any model through omp's model roles; arbitrary seeds; the advisor is seeded with Opus 5.5.
- **Intervals:** the check-in every 60 minutes; the advisor every 180 minutes.
- **The pilot project:** attach (`projects/attach/`), built by the tool on itself.
- **omp:** pin the latest at S0.
- **Attach:** an outside session can take the advisor, orchestrator, manager or worker seat. It's carved out of v1 and built by the tool itself, **as the pilot.**
- **Roles:** fixed ranks in the tool; roles, including specialists, defined in the pack.

**Defaults I've chosen from the reviews (change any):**
- one orchestrator and one advisor per database;
- a model change applies to new agents;
- a spec change mid-work goes to the manager to decide;
- "a repeat does no harm" covers the tool's own state.

**Open:**
- **Seven small owner items** before day 1 (the name, repo, machines, seats, subscriptions, release, how the pilot is judged), each with a recommended answer: see `DECISIONS.md` §2.
- The journey test's checkpoints become the pilot's backbone.

## 8. What we did with Astra's plan check
**Taken:**
- **omp corrections:**
  - `--profile` is an isolated store (v2 used one profile per login; v2.1 simplifies this to one profile holding every login);
  - ChatGPT is `openai-codex`;
  - skills go through a `--config` overlay plus `--skills`, and sub-agents inherit skills;
  - a pack's `agents/` needs exposing;
  - the sub-agent frames need subscribing to;
  - admission vs `prompt_result` vs settled;
  - `--resume <exact file>` with an identity check;
  - use the `omp-rpc` client;
  - reuse the install *pattern*, not the old pin.

  All are in spec v3.1 and S0.
- **Delivery:** at-least-once and acknowledged, with idempotent effects. The "exactly once across a crash" promise is dropped.
- **The manager re-cut, plus the L0 contract.**
- **The vertical slice** is back.
- **C3 is Super-hard.** R5 is split.
- **The data-contract gaps:** dependencies, overrides, resolved config, global rows, the durable save notification, task release.
- **The dependency fixes,** and the stronger checks.
- **The contingency** is labelled as contingency.

**Cuts we agreed with:**
- no second RPC transport;
- no strict skill isolation for sub-agents;
- a tiny alternative-pack fixture, not a second protocol;
- the auth broker is optional;
- no "Turso needs no schema change" promise;
- keep the separate advisor.

**Where we differ:**
- **(At v2) the total was 45.5 days, above Astra's 36–44,** because the additions it asked for are now costed tasks.
- **Astra's audit was read-only:** no live login or recovery was run. S0 does that, and the plan treats any S0 surprise as a reason to re-estimate.

## 9. What we did with the three reviews
See `16-three-reviews.md`. We took all 14 gaps (G1–G14), the testing design and the plan-level cuts. We set two scope defaults: four attachable seats, and one orchestrator per database. That brought the total from 46 to 54.5 days.

## 10. The pilot and follow-up projects (run on the tool itself)
**The pilot is the tool's first self-built project** (attach). After it, the tool builds its own next features. Each one is a **project spec folder** in the format the tool uses, checked in with `otto project new <name> --from <folder>`, managed by a manager, and worked by workers. Each runs **at the same time** as the others, under one orchestrator.

| Project | Folder | Size | Starts after |
|---|---|---:|---|
| **Attach:** connect an existing chat window (Claude Code, Codex, an omp window) to a seat | `projects/attach/` | about 3 days | v1 is qualified (it *is* the pilot, D5) |
| Inbox hooks for outside sessions (e.g. Claude Code) | not yet | small | Attach works |
| A second production pack | not yet | — | A real need |
| Turso and several machines; shared logins | not yet | — | A second machine |

Astra-parallel advised against carving anything else out of v1: atomic saves, recovery, durable messages, checked landing, the advisor and the pilot are the core proofs.

**Why carve out attach first:**
- it's self-contained: v1 already reserves the column, the identity lookup and the one-holder rule;
- it's useful straight away;
- it's a real code project of the right size to prove the tool can extend itself.

## 11. How the build itself runs (bootstrap)
**Until the tool exists, today's sessions run the build.**
- **The organisation:** one orchestrator session, four manager sessions (one per project folder), and bounded worker sessions (Claude Code or Codex). They follow **`POLICY.md`** (which replaces the older runbook rules in `02` where they differ).
- **Briefs:** each one names the task, the repo and base, the files the worker owns, the done check and the evidence required.
- **Fan-out:** prove one worker end to end before fanning out. Managers drain finished results before dispatching more.
- **Integration:** **`main` of `AstridPseudon/Otto`**, restarted fresh. Old Otto stays frozen on `deprecated`.
  - Land the contracts, the package and CLI skeleton and the test infrastructure first; then C1 and P1; then replace the stubs with the real pieces.
  - **M4 runs landing into `main`** with checked fast-forward from day one. Use Otto's `landing.py` sequence, never `tools/land.sh`. The orchestrator owns the release gate.
  - **Every candidate runs the installed-wheel CI** (about 3–5 minutes).
  - Interface changes go through one contract diff, reviewed by its producer and its consumers.
- **Handing over to the tool:**
  1. **After VS,** and once task, landing and recovery checks are green, try the tool on one small, non-critical task.
  2. **The outside organisation stays in charge through the pilot.**
  3. **For the pilot,** start the tool's own organisation and give it `projects/attach/` (§10). After the pilot, the remaining follow-ups go the same way. The running tool stays on its installed, pinned version while it changes its own repo.

---

## Change history (newest first)
**v3.2 (30 Oct)** applies two Astra reviews (`17-parallel-and-journey.md`):
- **four projects run at the same time,** each with its own manager and spec folder under `projects/`, all integrating into one new repo;
- **the schedule is corrected:** about **22 working days** with R2 and R3 in parallel (the old 23.5 had an arithmetic slip), and a **20.5-day target** if four tasks are split into preparation and qualification;
- **a bootstrap plan** for building it with today's sessions until the tool can run itself;
- **one end-to-end journey test** in D3;
- **rank is stored separately from role;**
- **attach reserves a binding id.**

**v3.1 (30 Oct)** has two changes:
- **roles live in the pack,** with fixed ranks in the tool, so Megado ships specialist roles (sense-checker, over-engineering checker, reviewer, scout) with fixed instructions;
- **attach is carved out** into `projects/attach/`, which the tool builds on itself **as the pilot** (§10).

The total is now **about 53 days** (53.5 after B0 was added in the newcomer pass).

**v3 (30 Oct)** applies three Astra reviews (`16-three-reviews.md`):
- **five contracts added to L0:** acknowledgement; work recovery; done only after landing; the attach handover; spec changes during work;
- **attach covers four seats** (advisor, orchestrator, manager, worker);
- **a testing design,** with D3 grown to 3 days;
- **closeout** (now X0a, preserving before the build, and X0b, archiving after);
- **bigger estimates** where Otto code doesn't lift out cleanly;
- **the total is about 54.5 days.**

**v2.1 (30 Oct)** applies your decisions:
- **models the omp way:** any model through omp model roles, with arbitrary seeds (the advisor's is Opus 5.5). The tool keeps no model table, no fallback lists and no profile-per-login convention;
- **default intervals:** a 60-minute check-in, a 180-minute advisor consultation;
- **pin the latest omp;**
- **attach** (AT): an outside session can be the orchestrator or a manager.

**v2 (30 Oct)** folds in Astra's plan check (verdict: *go with S0; revise before full execution*):
- managers re-cut;
- a contract step and an early vertical slice added;
- C3 raised to Super-hard;
- delivery changed to at-least-once;
- omp details corrected;
- dependencies fixed.
