# Otto: facts gathered by six read-only explorers (28 Oct)

These are summaries. Verify anything load-bearing in `otto/`. The archive stops at the 19 Oct pause.

## What exists in code (`otto/source/otto/src`)
- **Size:** 129K lines of source plus 50K of tests. `otto/portfolio` (coordination, authority, managers) is 58K lines. The fleet (execution) is 5.6K. The domains (work, assessment) are 10K.
- **Work record** (`herzchen/domains/work/model.py:34`): kinds project, effort, task, criterion, scenario, gate. Lifecycle: pending, active, paused, withdrawn, completed. Task payload: `fields.check.argv` (an argv check is required; free text is refused), `acceptance`, `gate_checks`, and `otto.plan` metadata (route normal|xhard, size, repo, branch).
- **Admission** (`work/module.py:491-505`): "Only the project's user admits, only on an approving review that names an exact retained revision". Any edit to an authored field invalidates it. Dispatch re-checks the admitted revision.
- **Assessment:** `local_assessment_policy.py:42` defaults `scope_mode="review-required"`. `check-accepted` exists as an option.
- **Execution:**
  - labs (git clone plus an APFS clone of shared directories);
  - a dispatcher with a pre-launch recheck;
  - a capacity pool (6 turn units, manager reserve 2, heavy headroom 3);
  - a runner with sealed results;
  - process custody;
  - `done` = checkpoint, rebase, recheck, gate checks, accept, then an ff-only merge under a lock.

  A failed check returns the lab to the worker. Resume with the log is owner-driven; there's no automatic retry.
- **Roles:**
  - the manager gets Bash/Edit/Read etc. and `max_turns` 200;
  - the worker gets Edit/Glob/Grep/Read/Write, **no Bash**, `max_turns` **8** (`otto/agents/claude_adapter.py:36-37`);
  - worker MCP tools are `task`, `check`, `done`; `ask` is a CLI that needs a socket, and workers have no way to call it;
  - worker refusals carry no `next_action`.
- **Model routing:** binary normal/XHARD from `otto.plan.route` to run-config roles. Profiles in `otto/agents/host_profiles.py`.
- **Status and attention:** `portfolio status` computes `needs_orchestrator` (help requests, ready-not-active, readiness overridden, stalled manager by heartbeat). There's no idle-worker or result-backlog detector and **no push or alerting of any kind**. Due records (scheduled checks) only fire if a host automation wakes them, and no Claude-side implementation exists.
- **Usage:** detailed token accounting by project/task/role/model, with static prices for only 2 models. **No dollar budget or enforcement anywhere**; the allowance units are turns.
- **Platform:** local single machine (Unix sockets, peer credentials, launchd, APFS, flock). **No cloud or remote mode.** Hard-coded macOS paths remain in `manager_ctl.py`.
- **Commands:** `ottoctl` (operator/admin, large), `otto` (portfolio client), `manager_ctl.py`. The single `otto` verb set (open, save, show, admit, status, wait, run…) from the PLAN is **not built**.

## Guidance (skills)
- **The Otto skill's role guides** (`otto/skills/otto/references/{orchestrator,manager,worker}.md`) are dominated by transport and authority protocol: exact pins, request keys, compare-and-swap revisions, UNKNOWN receipts, adoption, the six-field occurrence, draft-versus-adopt. The judgement guidance (pace, quality, escalation taste) is thin. "Hourly oversight is a fallback; act on ready handoffs."
- **Setup:** about 15 commands before the first dispatch for a Megado project. The steps (enrollment request, owner approval, adoption, binding, activation) are separate.
- **Megado** (`otto/skills/megado/`): the lifecycle has phases 0–7. Six project documents: northstar, agent_goal, run.json, plan, tasklist, status. Its rules are pragmatic:
  - zero reviews for reversible, directly verifiable work;
  - "judge every new layer by a current requirement";
  - an improvement loop of 0–3 changes;
  - an XHARD rubric ("a specific correctness invariant… size, importance, a security label or one failure alone is insufficient").

  One exception: a final Astra review is the default for new substantial delivery.

## The Otto program (built Otto with this process, 14–19 Oct)
- About 70 of 205 tasks landed; it was paused by the user. Stage 2 never passed review, and edition 1 and CUTOVER were never reached.
- **Same problems as the Astrid program:**
  - managers rotated at 198K–266K context;
  - one resumed manager turn read 1.29M input tokens;
  - an LLM manager spent paid turns on mechanical dispatch;
  - 9 places carried status, and 184 of 205 rows were stale;
  - the orchestrator edited labs about 25 times, losing one commit;
  - 23 Astra calls from a watcher bypassed the 5-call cap;
  - harness shortcuts caused both stage-2 FAILs;
  - time limits were banned, and then a real hang went unseen for hours;
  - the disk hit 0 GB (9 hours lost);
  - per-task gates took 5–50 minutes, while integrate-then-bisect landed 18 labs in one run.
- **What helped:** integrate-then-bisect (`ops/integ.py`); `ready.py` deriving what's startable; four Haiku helpers at the hourly check-in; a base-versus-lab flake rule (refuse only if the lab fails at least 2 of 3 and the base never fails).

## Direction (`otto/portfolio/PLAN.md` §1, `AGENT-UX.md`, `portfolio/projects/*`)
- **End state:**
  - plans only in Otto's schema;
  - Otto starts ready tasks itself, and the manager is woken only for judgement (**owner has now rejected auto-dispatch; see GOAL**);
  - four worker tools, with acceptance by Otto's own run;
  - one capacity pool;
  - one `otto` command for people;
  - an allowance on admission;
  - a project is a brief plus tasks;
  - status is derived.
- **Follow-on projects, all waiting on edition 1:**
  - SLIM: cut at least 25% of `portfolio`, with one instruction path, one replace and one status;
  - EFFECTS: an at-most-once effect ledger;
  - PACKS: versioned policy packs;
  - HARNESS3: a third agent CLI;
  - THROUGHPUT: focused checks and caches;
  - ASTRID-ON-FLEET: a study;
  - PROCLIFE: process scopes.
- **Tensions:**
  - edition 1 builds what SLIM deletes;
  - the scoped-supervisor route is built on mechanisms SLIM retires;
  - who owns durable effects is unresolved;
  - Herzchen's "neutrality" is asserted but not true yet.
