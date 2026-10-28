# Runbook: how the Otto program is run

Revised 15 Oct, evening and late (PLAN.md §16). Who coordinates:
- **Until CUTOVER (the bootstrap):** Claude, the portfolio orchestrator (principal `claude-code-orchestrator`), with a Haiku bootstrap manager (`ops/manager-bootstrap-brief.md`) that launches and lands tasks. Claude checks in hourly with a `/loop` and four Haiku helpers (§7).
- **After CUTOVER:** Otto dispatches, and the project manager handles judgment (`projects/program/manager-brief.md`), unless stage 6 says otherwise (§9).

The plan is in PLAN.md, and the tasks are in `projects/program/tasklist.md`.

## 0. Starting the run (on the user's go), in order

1. **The machine** (§1.3), recorded in STATUS.log.
2. **ASTRA0** if it hasn't run: `ops/launch_review.sh ASTRA0 astra` with its brief (PLAN.md §16). Fold in its findings, after checking each in source.
3. **TOOLING3** (§1.2), landed by the orchestrator.
4. **The manager:** `python3 ops/launch_manager.py` (it refuses while the recorded manager is alive). Its first work is in §1.2: resume HOSTKIT and POOL with their fix messages, and land GREEN.
5. **The loop,** from the orchestrator's session: `/loop 1h Otto program hourly check-in: follow ~/Developer/otto-program/ops/checkin-checklist.md exactly`. A fresh session started in `~/Developer/otto-program` is cheapest; the checklist is self-contained, so any session can run it.

## 1. Before work resumes

1. **The go.** The user gave "deploy the first project end to end" on 15 Oct, then paused the program at 00:57Z. Resuming needs the user's go.
2. **First steps on resume:**
   - **TOOLING3** (the orchestrator):
     - `run-task.sh --route xhard` adds the Agent tool and the `haiku-worker` sub-agent (Haiku 5.5 high), defined once in `ops/bootstrap/common.sh`, copied from `AGENTS` in `ops/experiments/POOLX/launch.sh`;
     - `land.sh` runs the gate in §4 and writes its log to `ops/runs/<TASK>/land.log`, which the check-in reads.
   - **The three finished tasks** (the manager, as its first work):
     - HOSTKIT: resume session `d605f492-d313-41cd-b6fe-77c94c60aee8` with `ops/fixes/HOSTKIT.md` (`run-task.sh HOSTKIT --route xhard --days 0.5 --resume … --message ops/fixes/HOSTKIT.md`);
     - POOL: resume session `a6c885ab-87cb-49ea-aebe-a85078201f67` with `ops/fixes/POOL.md` (the same, `--days 0.75`);
     - GREEN: land it through the gate. It leaves `test_d03_status_reads.py` and `test_hostctl_serve.py` red (the owner design); the gate compares every failure with the same file on canon, so those stay pre-existing, not new, without any exemption;
     - after POOL lands, delete `lab/POOLX` and its lab: the experiment's record is in `ops/experiments/POOLX/`.
3. **The machine:** at least 8 GB of free disk, and memory pressure normal. Record both in STATUS.log.

## 2. Tasks run in parallel, within four limits

1. **Dependencies.** A task starts only when every task in its deps column has landed on `canon/main`.
2. **Sessions.** At most 2 workers at once (swap is nearly full on this Mac). Only the user raises it.
3. **Files.** Two tasks that edit the same module never run at once. Each brief lists its files. The known hot files:
   - `execution_host.py`: POOL, DISPATCH, ACT (and SL12 from another session);
   - `portfolio_apply.py`: RETIRE, A6;
   - `cli.py`/`portfolio.py`: A3.
4. **Priority.**
   - SKEL0's chain first: STAGE, PERCH, HOSTKIT, POOL, CUSTODY, RUNNER, LAB, EVIDENCE, A1, TYPE, A2, ADMIT, TOOLS, DISPATCH, LAND. Until SKEL0 lands, other tasks wait unless no chain task is ready (GREEN is the exception).
   - Within the chain, STAGE and PERCH come as early as a slot allows, because every landing after them is checked on staging.
   - After that, the longest remaining path.

**Other landers.** Other sessions also land on `canon/main` (SL9–SL12, Store leanness, 15 Oct at 12:15Z, touching `execution_host.py` and `herzchen/command_ports.py`). Labs always branch from the current `canon/main`, and the gate rebases. The check-in lists non-program landings against the running tasks' files and the remaining rows (§7).

Owner actions are Claude's own steps, never worker sessions: the stage runs and reviews (§6), and CUTOVER.

## 3. Launching a task

1. **Lab.** `git -C ~/Developer/otto-claude-host/otto worktree add ~/Developer/otto-claude-host/labs/<TASK> -b lab/<TASK> canon/main` (or `ops/bootstrap/otto-lab.sh create TASK`).
2. **Brief.** Use `ops/brief-template.md`. Outcome, files and check are required. XHARD briefs include the invariant and the delegation section.
3. **Session.** `ops/bootstrap/run-task.sh TASK --route <normal|xhard> --days <size>` runs the worker in the lab, detached. **From 16 Oct on Codex** (`ops/worker-host`; the user: Luna instead of Haiku, Sol instead of Sonnet):
   - normal: `gpt-6-luna` high; xhard: `gpt-6-sol` xhigh leading Luna sub-agents (`spawn_agent`);
   - Codex's workspace-write sandbox keeps `.git` read-only, so `run-task.sh` commits the worker's changes when it exits;
   - no dollar budget: usage is tokens in `worker.jsonl` (`workers.py spend`);
   - on Claude (`--host claude`): normal Haiku 5.5 high, xhard a Sonnet 5.5 high lead with the `haiku-worker` sub-agent, $5 or $20 per focused day;
   - the wall-clock limit is 3 hours per focused day;
   - worker isolation: no skills, slash commands or MCP;
   - output goes to `ops/runs/<TASK>/`.
4. **Resume** a stopped or failed worker in its own session, never a fresh one: `run-task.sh TASK --route r --days d --resume SESSION --message FILE`.

## 4. Landing a task: the gate (PLAN.md D19), one task at a time

1. **Rebase** `lab/TASK` onto the current `canon/main`.
2. **Check**, through `otto-heavy`:
   - the task's own check;
   - every test file that imports a module the task changed, each file run on its own, twice. A failure that canon doesn't have counts, even if it's flaky. Every failing file is compared with the same file on canon (run in `labs/_baseline`, cached under `ops/.baseline/<sha>/<file>.txt`);
   - regression tests must also fail on `canon/main`.
3. **Staging** (once STAGE and PERCH have landed): restart the staging Otto on the tested commit (the rebased lab tip, whose tree is the merge's), and run the startup test and the canary scenarios with the fake harness (`perch.sh all --fake`).
4. **Placement** (D14): report the added lines by layer (`git diff --stat` over `src/herzchen` and `src/otto`). If a fleet or model task's new mechanism landed under `src/otto`, send it back with D14. `tests/test_herzchen_boundary.py` must pass.
5. **Existing tests:** if the task changed what an existing test asserts, stop. Write `ops/reviews/D19-<TASK>.brief.md` from the template (the tests' diff and the worker's reason) and run `ops/launch_review.sh D19-<TASK> opus`. It's logged as `opus` in STATUS.log. Land or send back by its answer.
6. **Pass:**
   - `git merge --no-ff lab/TASK -m "Land TASK: <title>"`;
   - push `canon/main` to GitHub `main`;
   - remove the worktree and the branch;
   - log the net lines and what was deleted.
7. **Fail or conflict:** resume the same session with the log.

## 5. When something goes wrong

- **First failure:** resume the session with the log.
- **Second failure:**
  - a normal task goes back with a sharper brief, re-run as XHARD;
  - an XHARD task is split at a natural seam, or goes to an Opus decision (from the reserve).
- **Over budget or time:** stop the session, keep the lab, record it, and decide whether to re-route or split.
- **Disk:**
  - under 8 GB free, nothing new launches;
  - under 4 GB, running workers stop;
  - stopped workers resume with `run-task.sh --resume` once free disk is back over 8 GB.
- **Stop everything and tell the user** when:
  - a go point is needed;
  - the live owner is down: tell the user. The bootstrap doesn't use it until CUTOVER, and other sessions restart it. `ops/launch_owner.py` takes no arguments (there is no preflight) and refuses while an owner's heartbeat is fresh;
  - a stage review finds the system unsafe;
  - a task would touch Codex's projects, vision or Native5.

## 6. Stages and reviews (PLAN.md §16)

- **No per-task reviews.**
- **One launcher for every premium call:** `ops/launch_review.sh ID opus|astra`, with the brief at `ops/reviews/ID.brief.md` written from `ops/review-brief-template.md`. It gives Opus the `haiku-worker` sub-agent and Astra Luna helpers, keeps both read-only, saves the answer to `ops/reviews/ID.md`, logs the call and its tokens in STATUS.log, and refuses a call past the budget. Run it in the background.
- **Stage runs:**
  - when a stage's tasks have all landed, the orchestrator runs `ops/bootstrap/perch.sh <stage>` with real Haiku workers;
  - then `STAGE<n>` (Opus) and, at stages 1, 4 and 8, the paired Astra review, launched together;
  - each finding becomes a fix task or a new perch assertion;
  - the orchestrator verifies the key claims in source (Haiku helpers gather the evidence) and tells the user the result.
- **The Opus budget is 15 calls:**
  - 9 stage reviews;
  - 1 final review (REVIEW);
  - a reserve of 5 for re-reviews of failed stages, D19 decisions, second failures and contested findings.
- **The Astra budget is 5 calls,** all scheduled (PLAN.md §16): ASTRA0 before resuming, ASTRA1 with stage 1, ASTRA2 with stage 4, ASTRA3 before CUTOVER's delete step, and ASTRA4 with stage 8 and the final review.
- `projects/program/run.json` holds both budgets.

## 7. Check-ins and reporting

- **The hourly check-in** (`ops/checkin-checklist.md`) fans out four Haiku helpers in parallel: the manager, the workers, the landings, and health and drift. The orchestrator reads their short reports, checks one claim from each in the evidence, then decides and acts. Its own context stays small, because the helpers do the reading: on 15 Oct one long orchestrator session was two-thirds of the spend.
- **Reaching the manager:** append a `## Orchestrator …` section to `ops/requests.md`. The manager greps those headings at every poll. For an immediate change, stop it between turns and run `ops/resume_manager.py`.
- **Re-apply the portfolio** at milestones only: SKEL0, CUTOVER and the final review.
- **Tell the user:**
  - at each stage's result;
  - before CUTOVER (the go point, with the list of upcoming projects and their verified saves);
  - after MANY and the final review;
  - and immediately on any stop condition.

## 8. The expected schedule

Measured on the first nine tasks: an estimated focused day takes about 30 minutes of agent time, and a landing about 6 minutes.
- **SKEL0:** about 7 hours of continuous running on 2 workers.
- **CUTOVER:** about 13 hours.
- **Edition 1:** about 17 hours.

Add the stage runs and reviews (about 30–60 minutes each), the user's go for CUTOVER, and any stops. `ops/cost-eta-20261015.md` has the low and high cases.

The SKEL0 chain's order with 2 workers: STAGE, A1, PERCH, CUSTODY, TYPE, LAB, A2, RUNNER, EVIDENCE, ADMIT, TOOLS, DISPATCH, LAND, then SKEL0. HOSTKIT, POOL and GREEN have finished and need only their pre-landing fixes.

## 9. After CUTOVER

- **The bootstrap manager's scope ends at CUTOVER:** every wave 0 and wave 1 task landed, and CUTOVER requested.
- **If stage 6 passed,** Otto dispatches the rest (SKEL, MANY, then wave 3) itself, and the project's manager is woken only for judgment. If it didn't, the orchestrator relaunches the bootstrap manager for wave 2, and that is a stage 6 finding.
- Claude stays the portfolio orchestrator, and waits with `otto wait` rather than polling.
- The staging Otto stays as the pre-production instance: upgrades go from staging to live.
