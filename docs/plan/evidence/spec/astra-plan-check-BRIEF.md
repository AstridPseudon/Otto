# Sense-check the end-to-end plan

You are **Astra**. Read-only. You may start Luna sub-agents (`spawn_agent`, model `gpt-6-luna`) to check claims in parallel, especially the oh-my-pi claims. Verify anything load-bearing yourself.

**Read:**
- `retro/14-plan.md`: the plan under review. It has the goal, design answers, four managers, about 22 tasks with tiers and done-when checks, the schedule and the open decisions.
- `retro/13-spec.md`: spec v3 (Part A the system; Part B how it's built, including B4b skills and model routing; Part C the earlier path).
- `retro/12-minimal-design.md`: the owner's direction.
- `retro/evidence/spec/harness/README.md` plus `retro/evidence/spec/*`: the research.

**Sources to verify against:**
- `oh-my-pi/` (a clone of can1357/oh-my-pi; read `docs/` such as `cli-reference.md`, `rpc.md`, `skills.md`, `settings.md`, `task-agent-discovery.md`, `auth-broker-gateway.md`, `advisor-watchdog.md`, `providers.md`);
- `pi/` (upstream Pi);
- `banodoco/astrid-agent` (Astrid's omp integration: `astrid/omp_agent.py`, `astrid/installer/tools.py`, `astrid/installer/omp/recipe.json`; use `git -C banodoco/astrid-agent show origin/main:<path>`);
- `otto/` (the frozen Otto code and branches).

## The owner's direction (condensed)
- **Five roles,** with tiers: advisor (high intelligence, consulted by the orchestrator) → orchestrator (mid) → manager (low, but farms tasks to mid- or high-level workers) → worker → sub-agent.
- **One central spawn path:** a role, plus generic role instructions, plus job-specific ones.
- **Packs** (Megado first) define the roles, the skills (including generic skills shared across packs) and the configurations. Other packs are possible.
- **Projects are spec folders,** with check-out and check-in to SQLite, turned into tasks.
- **The orchestrator's reminders:** every 1–3 hours, plus the advisor every 3–6 hours.
- **No excessive controls** (no spend control). Basic structure plus trust.
- **Runs on one machine,** a Mac or a cloud box. **One local SQLite file now;** Turso sync of some or all projects later.
- **Subscriptions, through oh-my-pi's login.** Each agent can be told to use a Codex model or a Claude one.
- **Minimal, elegant and tested.** Reuse what exists.

## Questions
1. **Will executing this plan achieve the goal?** Go through each element of the owner's direction and the spec's acceptance (§B6, plus the pilot in plan §6): which tasks deliver it, and what's missing or only implied.
2. **Do the oh-my-pi claims hold?** Check against the clone:
   - `--model provider/model`;
   - `--profile` for choosing an account for a top-level RPC session;
   - `skills.customDirectories` and `--skills`, and whether they can be set per process (config file in the cwd? a CLI flag? an env var?);
   - `session_settled`;
   - resume and `open_session`;
   - `task` sub-agents with a model and account per agent;
   - subscription login on a headless Linux box;
   - the Python RPC client.

   Flag anything that's wrong, and how the plan should change.
3. **The manager split:** are the four workstreams the right cut for maximum parallelism? Check the ownership boundaries, the hidden cross-dependencies (e.g. C5 needs R3, C2 needs P1) and the integration risk. Suggest a better split if there is one.
4. **Tiers and estimates:** are the Normal / X-hard / Super-hard labels right? Super-hard should mean a specific hard invariant. Is the total of about 34 engineer-days and an 18-day critical path credible? Name the riskiest tasks and how to de-risk them early.
5. **Missing tasks or wrong dependencies,** concretely.
6. **Over-engineering:** anything the plan does that the owner's direction doesn't need.

## Output (final message)
1. **The goal-coverage table.**
2. **The omp claim checks:** each claim marked confirmed, wrong or unclear, with the doc path or line.
3. **Manager-split recommendations.**
4. **Tier and estimate corrections,** and the risks.
5. **Missing tasks and dependency fixes.**
6. **Over-engineering to cut.**
7. **A verdict:** go, or the specific changes needed first.

Be concrete and terse.
