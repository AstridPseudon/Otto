# The Otto program: one plan (14 Oct 2026; revised 15 Oct after the first nine tasks)

**Status (15 Oct, evening):** the bootstrap ran from 15 Oct, 01:20 CEST (the user's go: "deploy the first project end to end") and has been **paused** by the user since 00:57Z. Landed on `canon/main`: S0B, STATUSREAD, BOUNDARY and HOLD, after S0 and OWNERSAFE, plus the orchestrator's TOOLING and TOOLING2. Finished in labs but not landed: HOSTKIT, POOL and GREEN. The 15 Oct evening revision (below and §16) changes the route, not the end state. Registered in Otto as the portfolio `otto-program` (namespace `otto-program`); this folder is its source until CUTOVER. History before 15 Oct: `~/Developer/otto-many-agents` (to commit 7a16577).

**Owner:** Claude. The user: "you're taking over all of this."

**Revisions on 14 Oct:**
1. **Plans live only in Otto's project schema.** The user rejected git cards as a second source of truth.
2. **Tasks are typed records** with criteria.
3. **Agent UX** (AGENT-UX.md), the lab lifecycle and the merge step were added, after the user asked "what's stopping this from being elegant for agents?" and "won't this accumulate tons of worktrees?"
4. **Astra's over-engineering check** (`production/review/optimization/otto-plan/astra-plan-overengineering-20261014.md`, 10 of its citations re-checked in source) was adopted:
   - admission and dispatch move into edition 1;
   - one runner package, with caching deferred until it's measured;
   - the standby hand-over becomes a drained restart;
   - the third harness, the generic host registry and W3 are cut or deferred. On the user's later request to generalize agents, a lean host contract came back as HOSTKIT, with a fake third CLI only in tests;
   - waves are scheduling labels, not gates.
5. **Six Haiku checks of every code claim** (14 Oct, late). They corrected:
   - H0's route;
   - the critical path;
   - the sizes of RUN, PRUNE, LOOP and CHANGE;
   - eight gaps between the decisions and the tasks.
   The reports are summarised in §10.

**Revisions on 15 Oct, evening** (after the first nine tasks; §16 has the reasons and the measurements):
1. **A staging Otto checks every landing** (D17). It's a fresh, empty instance started through the production entry point, run on the commit being landed and stopped after its checks. It replaces REH's rehearsal on a Store clone, and SKEL0's late, one-off instance.
2. **The old Store is deleted, not migrated** (D18). The user: "we can not only archive, but we can delete, so long as we still have the data on the upcoming projects all saved". RETAIN, H0, REH and SUPERVISE are dropped; INSTALL and IMPORT become one task, CUTOVER.
3. **The landing gate is mechanical, and judgment is triggered** (D19): a startup test, every test file that imports a changed module run alone and twice, and an Opus decision whenever a task changes what an existing test expects.
4. **Validation is live** (D20, §16): the observation perch, and nine stages, each run on the staging Otto with a canary project and examined by a fresh Opus reviewer with Haiku helpers. The Opus budget is 15 calls across the program. The user: "let's say if you have like 15 Opus reviews you can budget throughout it".
5. **XHARD tasks run as a Sol lead delegating execution to Luna sub-agents** (D10; a Sonnet lead with Haiku sub-agents until 16 Oct), after the POOL rerun (§16).

**Revisions on 15 Oct, late** (the user asked whether this is specced cleanly enough to run with an hourly loop, and for five more premium reviews from Astra):
1. **Five Astra reviews** (GPT via Codex, a second model family) at the five points where a different kind of reviewer adds most (§16), each with Luna helpers. Opus still owns "does it work"; Astra judges the shape. The Opus budget stays 15.
2. **One launcher for every premium call** (`ops/launch_review.sh`): stage reviews, the final review, Astra reviews and D19 decisions all use one brief template, give the reviewer helpers (Haiku for Opus, Luna for Astra), save the answer to `ops/reviews/`, and count against the budgets in STATUS.log.
3. **The hourly check-in fans out four Haiku helpers** (manager, workers, landings, health), and the orchestrator judges their evidence (RUNBOOK §7).
4. **Other sessions land on `canon/main` too:** SL9–SL12, Store leanness, on 15 Oct at 12:15Z, touching `execution_host.py`. Labs branch from the current `canon/main`, the gate rebases, and each check-in lists non-program landings against the running tasks' files.
5. **The bootstrap manager's scope ends at CUTOVER** (RUNBOOK §9). Its old goal still named "three final Opus reviews".

**Basis:**
- the fact reports `production/review/optimization/otto-plan/h-a…h-f.md` and `otto-plug/h1…h8.md`;
- the designs `o-2-execution.md` and `o-3-takeover.md` (o-1 is withdrawn);
- AGENT-UX.md;
- Astra's review;
- the 12 Oct decision 4, "project documents are Otto-only", and W1 A6.

**What it replaces:** the 11 Otto-improvement projects (otto-work-model W0–W6; otto-many-agents R1, D1, H1, I1). Their open work is carried below, or dropped or deferred with a reason (§7).

## 1. The end state

- **One Otto service for every host.** Claude owns its source and installs; Codex is a host and contributor.
- **A plan lives in one place: Otto's project schema.**
  - Tasks are typed records with criteria; briefs are document revisions.
  - Files outside Otto are only short-lived checkouts or generated views.
  - Code lives in git.
- **Each project has a line:** one branch per repo it touches.
  - Each running task works in its own lab, an instant copy-on-write clone of the line.
  - A passed task lands on the line, one at a time, after its check passes on exactly the merged commit. Its lab is then deleted.
  - Labs exist only for tasks in flight, so their number follows concurrency, not plan size.
- **Otto starts ready tasks itself:** admitted, dependencies accepted and a slot free.
- **Underneath is a neutral platform** (D14):
  - Herzchen's model of the work, plus a Herzchen "fleet" that runs many agents efficiently (D15).
  - Adding another agent harness is one host implementation (HOSTKIT).
  - Another product could deploy agents on the same fleet.
- **Each project has its own manager:** a separate Claude or Codex session with its own identity (`whoami`), base instructions shared by every manager plus the project's own, and manager tools. It is resumed only for judgment: questions, repeated failures, changes outside the allowance.
- **Workers have four tools:** `task`, `check` (feedback now, through the runner), `ask` and `done`.
  - A failed check resumes the same session with the log.
  - Acceptance is Otto's own run, never the worker's.
- **One capacity pool** has turn slots and heavy slots, with headroom so checks can always run. Heavy work goes through one runner.
- **People use one `otto` command:** `open`, `save`, `show`, `admit`, `status`, `wait`, `run`, `heavy`, `upgrade`. `ottoctl` is an admin surface only.

**The metrics:**
- heavy seconds per accepted task;
- sustainable concurrent turns on this Mac, measured, with memory pressure never critical;
- zero activations refused because another project is busy.

## 2. Decisions

| # | Decision | Basis |
|---|---|---|
| D1 | **Claude owns Otto's source and installs.** Codex runs its own projects as a host and sends Otto changes as patches. It never writes the controller, manifest or Store. | user; o-3 §3-4 |
| D2 | **Plans live only in Otto's project schema.**<br>• Tasks are first-class records (WorkRecord, model.py:34).<br>• Route, size and the project's lines live in a declared `otto.plan` metadata namespace, validated in the common payload check (work/module.py:745 `_validate_payload`, which `create` and `revise` both run) as well as the sheet validator. Today route and repo sit in `custom.megado` (register.py:88-109); CONV moves them.<br>• Checks are criteria in the assessment's scope (assessment/module.py:290-300), one representation.<br>• Edit with `otto open` and `otto save`: a stale base is refused, never merged. Views are never read back.<br>• The run-folder mirror, task-table parsing and the r4 generator are deleted.<br>• Older code refuses unknown top-level task fields (batches.py:840), so namespaced metadata keeps rollback a rename. | user; decision 4; W1 A6 |
| D3 | **One capacity pool: Herzchen's `limits`** (kernel/limits.py). These are capacity reservations (reserve, settle, release, uncertain) kept in the Store; the allowance pools already use them (reviewed_activation.py:282, owner_bootstrap.py:971).<br>• Turn units and heavy units: weights become units, headroom is kept for checks, and managers keep a reserve.<br>• Otto's owner takes turn units at turn start without blocking. The runner takes heavy units per command through the owner: a few per minute, and the owner is already the single writer.<br>• `_eligible`'s hard-coded counts and heavy.py's flock pool retire. heavy.py stays only for the bootstrap.<br>• `OTTO_HEAVY_*` is stripped from agent environments. | sweeps (herzchen, execution, Astrid); o-2 §4 |
| D4 | **Acceptance is one path.**<br>• Otto commits the lab and rebases it onto the line.<br>• It runs the task's admitted criterion check on that exact commit, through the runner.<br>• It validates the runner's result explicitly. `accept_without_review` doesn't verify evidence digests (assessment/module.py:964-997), unlike `accept` (:951).<br>• It accepts through the existing assessment, then moves the line forward.<br>• Scopes for check-accepted tasks are declared with no-review allowed. `declare_scope` requires review by default, and `accept_without_review` refuses otherwise.<br>• Gates with a check use the same path. Write and stdout capture are retired. | o-2; Astra #1 |
| D5 | **One transport: a Unix socket to the owner.**<br>• Managers and clients are identified by their process: the peer PID must descend from a process Otto launched (native_caller_ingress.py).<br>• Workers reach the MCP facade with a per-assignment token, because their sandbox blocks exec and TCP has no peer PID.<br>• The file lanes polled at 20 Hz (hostctl/lanes.py, service.py:157-166) retire once both hosts use the socket (LANES). | o-2 §4; sweeps |
| D6 | **Bootstrap, staging, then native.**<br>• Until CUTOVER, each task is built by a separate `claude -p` session in a lab: Haiku for normal tasks, a Sonnet lead with Haiku sub-agents for XHARD. The bootstrap manager coordinates (`ops/manager-bootstrap-brief.md`). At most 2 at once; 3 after a measured hour with memory pressure normal.<br>• Checks run through `otto-heavy`.<br>• Every landing also runs on the staging Otto (D17). The program's own work moves onto Otto at stage 6 (§16) and runs natively after CUTOVER. | o-2 §2, h-f; 15 Oct revision |
| D7 | **Upgrades are a drained restart.**<br>• Drain, swap the tree by rename, restart under the existing supervisor (execution_host.py:1362); clients retry within a bound.<br>• The outage is measured before anything is promised.<br>• No standby successor. | Astra #4 |
| D8 | **Codex's Otto projects** (revised 15 Oct, evening). Codex is idle (the user, 15 Oct).<br>• At CUTOVER, every project in the old Store that isn't done is listed. The upcoming ones are saved into the new Otto and verified by diff: vision and the union port too, if the list shows them upcoming. The rest goes with the old Store (D18).<br>• W0's stale hold goes with the old owner, so H0 is dropped. Luna's E1–E4 are still imported: E1 into UPGRADE's drain status, E2 into A2's preview, E4 into G3; E3 is superseded by A6. | o-3 §5; user, 15 Oct |
| D9 | **One program, one Otto project.** Until CUTOVER, this folder is the authoring source, re-applied at milestones, and the four pending otto-many-agents projects in Otto are inert. At CUTOVER, the plan is saved into the new Otto, and this folder and r4's freeze as archives. | user |
| D10 | **Models and reviews** (the user, 15 Oct; revised 15 Oct, evening; **Codex from 16 Oct**).<br>• **From 16 Oct 2026 (the user): Codex models, Luna instead of Haiku and Sol instead of Sonnet,** for the manager and the workers (`ops/manager-codex.md`, `run-task.sh --host codex`; CODEXHOST). Running Claude workers finished on Claude. The lines below give the Claude routing they replace.<br>• Normal tasks: Haiku 5.5 high.<br>• XHARD tasks: a Sonnet 5.5 high lead that delegates almost all execution (reading, edits, test runs) to Haiku 5.5 high sub-agents, and keeps the design, the review of each result and the commit.<br>• The bootstrap manager: Haiku 5.5 high.<br>• **The Opus budget is 15 calls** across the program (§16): nine stage reviews, one final review of edition 1, and five held for re-reviews and triggered decisions. Opus is the oracle.<br>• **Five Astra reviews** (`gpt-6-astra` through Codex, with Luna helpers) at the five points in §16, where a second model family adds most; the Opus budget is unchanged (the user, 15 Oct, late).<br>• Every premium call goes through `ops/launch_review.sh`, and every premium reviewer hands the legwork to helpers (Haiku for Opus, Luna for Astra).<br>• No per-task reviews: acceptance is each task's check plus the landing gate (D19). | user, 15 Oct |
| D11 | **Nothing runs without the user's go.** | user |
| D12 | **Labs and lines.**<br>• Only Otto creates and deletes labs: copy-on-write clones of a prepared template (code + installed dependencies) at the line's head.<br>• A lab lives from dispatch until landing or withdrawal.<br>• A task parked for rework or an answer is committed to `lab/<task>` and its folder freed; resuming recreates it in seconds.<br>• Startup and hourly sweeps commit and remove any lab without a live task. Uncommitted work is never discarded.<br>• `otto status` shows the lab count. | user, 14 Oct |
| D13 | **Waves are scheduling labels, not gates.**<br>• Regression tests must fail before the change; feature tests need only pass.<br>• Refusals that a task touches gain `next_action` (the existing field). There is no universal retrofit. | Astra #9, #10 |
| D14 | **Three layers, one repo, one process.** The test for where code goes: would another product that deploys agents need it?<br>• **Herzchen model** (exists; it calls itself "neutral" throughout): the Store, events, documents and authoring sessions, the work graph (tasks, deps, admission, readiness, waits), assessment, evidence and capacity.<br>• **Herzchen fleet** (new package `herzchen/fleet`, assembled from what this plan builds): how many agents run efficiently on one machine. That means hosts (one contract; Claude and Codex as implementations), sessions (start, resume, park, replace, tokens), workspaces (labs), the runner (heavy commands, process custody, results as evidence), the worker tools facade (`task`, `check`, `ask`, `done`), the dispatcher (ready → capacity → launch, by role), wakes and landing.<br>• **Otto product:** projects and portfolios, the manager, worker and orchestrator role definitions, admission and allowance UX, reviews, Megado's guidance, the `otto` command, install and upgrade.<br>• **Imports point down only:** the fleet imports the model; Otto imports both; nothing imports Otto. Today two Herzchen modules import Otto (work/usage.py:157-159, adapters/host.py:29-30), and BOUNDARY fixes that.<br>• **This is a module boundary, not a service or framework.** Code moves only when a task touches it anyway, but a task that adds a fleet or model mechanism puts it in Herzchen even when it builds on Otto code.<br>• **Placement is checked, not only imports** (15 Oct, evening; POOL put the pool in `otto/portfolio/execution_host.py`, and HOSTKIT carried Otto's names into `herzchen/fleet`). Every fleet or model task names its destination package in its row and brief. The landing gate reports the added lines by layer, and a fleet or model mechanism that lands under `src/otto` goes back. `herzchen/` carries no Otto vocabulary: product names, role tool sets, `OTTO_*` names and Megado defaults are passed in by Otto, and `tests/test_herzchen_boundary.py` checks the names as well as the imports. | user, 14 Oct; sweeps |
| D15 | **Efficiency rules for the fleet** (what "tons of agents, maximally efficient" means here):<br>1. An idle agent costs nothing: one process per turn, continuity by resume.<br>2. Nothing polls: wakes are events.<br>3. Capacity is units in one pool (D3).<br>4. Heavy work goes through the runner, deduplicated only once measured.<br>5. Labs are copy-on-write.<br>6. Each role's instructions keep a byte-stable shared base first and the project-specific part after it, so hosts' prompt caches can reuse the base.<br>7. A session whose context grows too long is replaced by a fresh one that reads the handoff.<br>8. Cheap models by default; the manager re-routes a task to xhard after repeated failure.<br>9. The metric is heavy seconds and tokens per accepted task, from the runner report and usage capture. | user, 14 Oct |
| D16 | **One program project, not several.**<br>• The areas depend on each other densely (LAND↔TYPE, DISPATCH↔ADMIT/POOL/LAB, MGR↔ASK/DISPATCH, ADMIT↔A2). Otto enforces task deps only inside one project (register.py:92); across projects there are only gate edges, which no launch path checks today.<br>• It is one repo and one line (`canon/main`); only R1d touches Astrid.<br>• During the bootstrap, Claude coordinates the sessions directly, so separate managers would buy no parallelism.<br>• Each task carries a **stream** field instead: takeover, model, fleet, dispatch, plans, proof, after. Onboarding templates materialize tasks but not efforts (sheet.py:558-600).<br>• The integration proof Megado asks for is the proof stream (SKEL, MANY, REVIEW).<br>• Other plans stay separate projects: r4 (the timeline work, ten projects with managers by the user's 15 Oct direction) and Codex's projects. | Megado; register.py:92; r4 precedent |
| D17 | **A staging Otto checks every landing** (16 Oct, STAGE0 F8: it is up only while the gate or a stage run checks it; the machine can't spare it idle).<br>• It's a fresh, empty instance under `~/Developer/otto-claude-host/labs/_staging`, with its own Store and socket. It starts through the product entry point (`ottoctl install` on its own home, then `ottoctl service run`), the same one the new live Otto uses at CUTOVER. (15 Oct 19:34Z: the onboarding wrapper `shared_operating_service.py` composes one onboarding project and can't host an empty Store; it retires at CUTOVER.) It's never a clone of the live Store and never the live install.<br>• Every landing starts it on the commit being landed (`OTTO_STAGING_REF`), before the merge, then runs the canary scenarios that work at the current stage (§16), and the gate refuses a report that names another commit (STAGE0 F1).<br>• It stays after CUTOVER as the pre-production instance: upgrades go from staging to live.<br>• It can be wiped and rebuilt at any time. | 15 Oct: POOL's startup crash was invisible to every test |
| D18 | **The old Store is deleted, not migrated.** The user, 15 Oct: "we can delete, so long as we still have the data on the upcoming projects all saved".<br>• CUTOVER lists every project in the old Store that isn't done and saves each upcoming one into the new Otto. It verifies each save by diff, and shows the user the list before anything is deleted.<br>• Then the old owner stops, and the old Store (8.3 GB), its controller and its run folders in iCloud are deleted. The new Otto lives on local disk that iCloud doesn't sync.<br>• Dropped with it:<br>– RETAIN, the compaction;<br>– REH, a rehearsal on a 7.7 GB clone that this disk can't hold;<br>– H0, a stale hold in the old Store;<br>– SUPERVISE: the old owner only has to last until CUTOVER, and `ops/launch_owner.py` restarts it by hand. | user, 15 Oct |
| D19 | **The landing gate is mechanical; judgment is triggered.** A task lands only when:<br>1. its check passes on the rebased commit;<br>2. every test file that imports a module it changed passes, each file run alone, twice; a flaky new failure counts as a failure;<br>3. the staging Otto restarts on the merged commit and passes the startup test and the current stage's canary scenarios, once STAGE and PERCH have landed.<br>• If the task changed what an existing test asserts, the manager can't accept it alone. An Opus decision, from the budget, accepts or rejects the change.<br>• Each landing logs its net lines and what it deleted. | the POOL rerun, 15 Oct (§16) |
| D20 | **Validation is live.** The user, 15 Oct: "look at it in a low-stakes environment live … look at all the data that's collected and figure out a check to do at each stage".<br>• The observation perch: one report per staging run, of everything Otto did (§16).<br>• A canary project exercises every path.<br>• Nine stages, each examined once by a fresh Opus reviewer with Haiku helpers.<br>• Each finding becomes either a fix task or a new automatic check. So judgment is spent once per stage, and checked automatically at every later landing. | user, 15 Oct |

## 3. The work

The tasks live in `projects/program/tasklist.md`, one row per task with route, size, deps, outcome, check, XHARD justification and stream. In Otto they become task records at activation. The waves, order, file ownership and reviews below are unchanged.

### Wave 0: take ownership (no restart)

### Wave 1: edition 1, the first usable release (built in labs; nothing touches the live Otto)
**Capacity and runner**

**Labs, landing and the worker loop**

**Admission and dispatch** (W2, moved before SKEL)

**One copy of every plan** (W1)

**Order** (dependency levels, computed from the deps; S0 comes first):
1. OWNERSAFE, HOLD, ACT, A1, BOUNDARY;
2. POOL, CUSTODY, EVIDENCE, TYPE, A3, HOSTKIT;
3. RUNNER, LAB, A2;
4. R1d, LAND, TOOLS, ADMIT, A4, RETIRE, CONV;
5. ASK, REWORK, DISPATCH, CHANGE, A6;
6. MGR.

STAGE and PERCH run as early as a slot allows. Every landing after them restarts the staging Otto (D17). They are SKEL0 deps, so they are in its chain.

**File ownership:**
- POOL follows HOLD (both edit `_eligible`).
- DISPATCH owns the dispatch paths; LAND owns the landing; TOOLS owns the worker launcher, ASK the pause and wait, and REWORK the resume path.

**Reviews:** none per task. Fifteen Opus calls in all, spent at the stages of §16 (D10, D20).
- A6 runs last in portfolio_apply.py.

### Wave 2: switch to the new Otto and prove it

### Wave 3: after edition 1 (native on Otto)

## 4. Size and time

**Measured on the first nine tasks** (15 Oct; `ops/cost-eta-20261015.md`):
- An estimated focused day takes about 30 minutes of agent time: about 2 estimated days per active hour per worker. Landing a task takes about 6 minutes.
- A normal task costs about $1 per estimated day; an XHARD task about $2.56, or about 15–30% less with Haiku sub-agents.
- So edition 1 is about 17 hours of continuous running on 2 workers, not 14–17 working days. Elapsed time is set by go points, stops and orchestration, not by the coding.

**The 15 Oct evening revision:**
- removed: RETAIN 2.0, REH 0.5, INSTALL 0.5, IMPORT 0.5, SUPERVISE 0.5 and H0 0.25 focused days;
- added: CUTOVER 0.75, PERCH 0.75 and STAGE 0.5;
- net: 2.25 focused days fewer;
- the Opus budget rises from 3 to 15 calls (about $60–75);
- the whole program is likely about $250 all in.

The sizing below is the 14 Oct one, kept for the record.

| Part | Focused days |
|---|---|
| Wave 0 | 1.85 |
| Wave 1 (edition 1) | 27.75 |
| Wave 2 | 3.25 |
| Wave 3 | 3.25 (+ 0.75 CACHE if needed; RET unsized) |
| Integration contingency (Astra) | ≈ 2.5 |
| **Total** | **≈ 38** (≈ 38.6 with CACHE) |

**Elapsed time:**
- **Edition 1** (waves 0–2) is 32.6 focused days, with a critical path of ≈ 11.5 days: S0 → BOUNDARY → HOSTKIT → LAB → TOOLS → ASK → MGR → REH → INSTALL → IMPORT → SKEL → MANY → REVIEW.
  - With 2 workers the load (≈ 16.3 days) binds.
  - With 3, once measured safe (D6), the critical path binds.
  - That puts edition 1 at ≈ 14–17 working days, with an early walking skeleton (SKEL0) on a Store clone about a week in.
- **Everything,** with wave 3 and the contingency: ≈ 18–21 working days.
- REWORK was split out of LOOP so the worker tools don't wait for LAND.
- The usable end state arrives with edition 1: there is no edition 2 dependency.

**How the size moved (focused days of work, excluding contingency):**
- **36.1:** the earlier draft plus AGENT-UX.
- **25.6 (−10.5):** after Astra's simplifications:
  - shared admission and dispatch: 2.25;
  - H1 and W3: 3.0;
  - the drained restart: 1.75;
  - one runner package, with the cache deferred: 1.75;
  - refusals, templates, the A tasks, S0 and G4 into SKEL: 2.75.
- **27.85 (+2.25):** after the six Haiku checks: RUN, PRUNE, LOOP and REWORK, CHANGE, UPGRADE.
- **29.35 (+1.5):** MGR, a manager per project.
- **≈ 33.6 (+4.25):** after the ten-agent codebase sweep and the layering:
  - HOSTKIT replaces HOSTFIX: +1.25;
  - BOUNDARY: +0.5;
  - process custody in RUN: +0.25;
  - R1d's lease pass-through: +0.25;
  - LAND's evidence gap: +0.25;
  - LOOP's wait and launcher qualification: +0.25;
  - A1's direction fence: +0.25;
  - A3 is smaller because status and sessions exist: −0.25;
  - LANES and DELETE in wave 3: +1.5.
- **≈ 33.85 (+0.25):** RETIRE generalizes PRUNE to retire any record with a reason and successors.
- The sweep also replaced several planned builds with reuse: sessions, status, the capacity ledger, the issue loop, manager continuity and caller identity. Without that, A3, MGR, RUN and LOOP would each have grown.

## 5. How the work is run

The operating instructions are RUNBOOK.md: scheduling, launching, landing, failures, reviews and check-ins. The per-task brief is `ops/brief-template.md`. The summary:

- **The canonical repo** is `~/Developer/otto-claude-host/otto`. S0 creates `canon/installed`; the trunk is `canon/main`. During bootstrap, every Otto task lands there.
- **Bootstrap (waves 0–2):**
  - Each task is one `claude -p` session in a lab (lab.sh's Otto variant), with `--model` set by route and `--max-budget-usd` per task. The supervisor enforces timeouts.
  - At most 2 run at once. The brief is the task's row in §3, plus its linked documents.
  - A task lands through the gate in D19: its check on the rebased commit, every changed module's test files run alone and twice, and the staging Otto restarted on the merged commit.
  - XHARD tasks run as a Sonnet lead with Haiku sub-agents (D10).
  - Claude launches the stage reviews of §16 (fresh Opus sessions with Haiku helpers) and the final review. There are no per-task reviews.
- **After CUTOVER:** native. Otto dispatches ready tasks into labs, workers use the four tools, Otto lands passing work, and managers are woken for judgment.
- **Supervision:** Claude, through `otto wait`, not polling. Every timing records the machine's state. Check-ins run in fresh, short orchestrator sessions: on 15 Oct, one long Opus session was two-thirds of the spend.

## 6. Risks, ranked

1. **Two owners at once.** *Mitigation:* T0 before S0; a digest check at every go/no-go.
2. **Losing an upcoming project's data at CUTOVER.** The old Store is deleted (D18). *Mitigation:* every project that isn't done is listed; each upcoming one is saved and verified by diff; the user sees the list before anything is deleted; deletion is the last step.
3. **Checks that pass integration defects.** On 15 Oct, task checks passed a startup crash, a flaky regression and rewritten tests (§16). *Mitigation:* the gate in D19, and the staging stages in §16.
4. **S0 can't match the installed tree byte for byte.** *Mitigation:* S0 stops and lists the differing files; nothing installs until they match.
5. **Stale holds or orphaned labs recur.** *Mitigation:* HOLD, the LAB sweeps, and the perch's leftover census at every landing. The old owner's holds go with it at CUTOVER.
6. **Bootstrap sessions leak processes or cost too much.** *Mitigation:* labs, otto-heavy's cleanup, a budget per session, at most 2 at once.
7. **Someone edits a view or an archive and expects the edit to stick.** *Mitigation:* views and archives say where the copy lives; `show` reports edited views; a second registration is refused.
8. **The disk.** 228 GB with 5–13 GB free, swap nearly full, and other sessions' renders. *Mitigation:* nothing launches under 8 GB free, and workers stop under 4 GB; staging is small; CUTOVER frees 8–10 GB.
9. **Production startup may refuse an empty Store**: Native5's startup "refuses any other set" of projects. *Mitigation:* STAGE finds out first, and the coupling becomes a fix task.

## 7. Carried, dropped and deferred

| From | Where it went |
|---|---|
| W1 | A1–A4, TYPE, RETIRE and A6; A5 → SKEL |
| W2 | ADMIT (M2/M3), DISPATCH (M4), CHANGE (M5). M1 is decided: tasks are stamped with their admitted revision. |
| W4 | CONV, CUTOVER (was IMPORT), G3; G4 → SKEL |
| W5 | L2/L3 → ACT; L1 → CHANGE; L4 (self-service bring-up) → ACT + DISPATCH; L5 → ASK; L6/L7 → SKEL; L8 (moved to D1 T2 on 14 Oct) → POOL |
| W6 | UPGRADE (drained restart, rehearsed; U4) |
| R1 | RUNNER (T1, T3, T5), POOL, R1d (T4); T2 → CACHE (conditional) |
| D1 | LAB (T1), POOL (T2), LAND (T3/T4); T3's host-lane check → TOOLS' `check` |
| I1 | SKEL, MANY, REVIEW |
| H1 | HOSTKIT (the contract; no registry engine) |
| W0 | D8 (H0 dropped on 15 Oct): E1 → UPGRADE, E2 → A2, E3 superseded by A6, E4 → G3 |

**Dropped:**
- on 15 Oct, evening (D18): RETAIN, REH, H0 and SUPERVISE; INSTALL and IMPORT became CUTOVER;
- the git-card variant (o-1), the standby successor and hand-over protocol;
- H1's data-driven registry engine and a real third harness. HOSTKIT is a small contract proven with a fake CLI;
- priority tickets;
- a universal refusal retrofit;
- the lease's capacity share and a second allowance ledger;
- Write and stdout result capture.

**Deferred to the project that needs it:**
- W3, published milestones and read grants (r4's port);
- CACHE, until it's measured.

## 8. The user's go points

1. ~~H0~~: dropped (D18).
2. Start the bootstrap: given on 15 Oct ("deploy the first project end to end"), and **paused** by the user at 00:57Z. Resuming needs the user's go.
3. CUTOVER: the switch to the new Otto and the deletion of the old Store, after the user has seen the list of upcoming projects and their verified saves.

T0 is now a courtesy notice, not a go point (the user, 15 Oct: disregard Codex).

## 10. What the Haiku checks found (14 Oct, late; re-checked by Claude where marked ✓)

Six read-only Haiku agents checked every code claim against `~/Developer/otto-claude-host/otto/src` (branch w0/host-ergonomics), plus the plan's own consistency.

- **Confirmed:**
  - WorkRecord; unknown task fields refused (batches.py:840);
  - `accept` verifies evidence digests but `accept_without_review` doesn't (assessment/module.py:909-997);
  - gate completion accepts any note (portfolio_apply.py:466-494);
  - Claude results are captured `Write` calls, up to 16 × 64 KiB, with Edit not captured, and Codex results are stdout;
  - no production code commits, rebases or merges worker work;
  - workers share one worktree; Claude workers can't fork or exec; Codex workers are `-s read-only`;
  - only managers resume ✓; the execution queue only starts what owner commands enqueue, and no launch path checks deps;
  - unknown hosts fall back to Codex; nothing reads run.json `limits`;
  - the `otto-heavy` launcher's usage line omits `--weight`.
- **Corrected in this plan:**
  - H0's route only captures turns that already finished ✓ (owner_runtime.py:1054);
  - RUN 1.25 → 2.0: the daemon, persistence and restart; the env passthrough bypasses accounting (heavy.py:260);
  - PRUNE 0.25 → 0.75: no gate or document withdrawal exists;
  - TYPE validates in `_validate_payload` (work/module.py:745), because `create` and `revise` bypass the sheet;
  - A2 must pass its base revision (intake.py:1113);
  - LOOP needs launcher changes ✓ (worker tools `Read,Write` at claude_cli.py:33; MCP switched off at :445) and a Codex probe;
  - answers to questions don't reach the asking worker (issue_loop.py:710-782);
  - CHANGE: the allowance bounds launches only;
  - the critical path is ≈ 9.25 days, not 10;
  - the gaps closed: E1, L4, U4 and the `OTTO_HEAVY_*` stripping each have a task; `otto status`/`otto wait` sit in A3/LOOP; generate.py is deleted at IMPORT; `canon/main` is created in S0; the Opus reviews are listed; S0 no longer replays E3.
- **Still open, by design:** whether Codex MCP tool calls work under its sandbox. That is LOOP's first probe, and Codex workers get workspace-write in LAB either way.

## 11. Where each piece lives (D14) and what it builds on

| Layer | Tasks | Builds on (exists today) | Retires |
|---|---|---|---|
| Herzchen model | RETIRE (`retire` with reason and successors), TYPE, ADMIT (stamps and the dispatch rule), DISPATCH (`ready()`), ASK (`record_wait`, event long-poll), EVIDENCE, the `limits` ledger that POOL uses, PERCH's task-timeline read, RET, BOUNDARY | work module, sheet, batches, assignments.dispatch, decisions waits, kernel `limits`, `EventCursorReader`, assessment `accept`/`completion_blockers`, evidence, templates, authoring sessions | the two Herzchen → Otto imports |
| Herzchen fleet | HOSTKIT (`fleet/hosts`), POOL (the admission policy: turn and heavy units, reserve, headroom; `fleet/capacity.py`), CUSTODY (`fleet/custody.py`), RUNNER (`fleet/runner/`), LAB (`fleet/labs.py`), TOOLS (facade, tokens; `fleet/tools/`), REWORK, DISPATCH (launch by role; `fleet/dispatch.py`), LAND (commit, rebase, check; `fleet/landing.py`) | adapter_conformance, claude_cli/adapter, the Codex bindings, native_caller_ingress, execution_host's queue, `commit_local_checkpoint`, writer_lease, lab.sh's steps, Astrid process_group's rules | the second Codex binding, heavy.py's flock pool, lab.sh, `_eligible`'s hard-coded caps |
| Otto product | STAGE and PERCH (bootstrap tooling: staging moves into UPGRADE, the report into `otto status`), MGR (role definitions and composition), A1–A4, RETIRE (the verb), CONV, A6, ACT, CHANGE (allowance UX), HOLD, CUTOVER, SKEL, MANY, UPGRADE, G3, LANES, DELETE | operating_brief and role_context, manager continuity and replacement, identity_context, project_services, issue_loop and help_delivery, the advisor wake, portfolio_status, herzchen_binding, reviewed_activation | the sync mirror, the hard-coded Codex brief, `sense_check`, the successor pair, operator.py, the file lanes, the six-file package |

**Adding another agent harness** (for example a third CLI agent) means writing one HOSTKIT implementation: launch, resume, tools, fence, parse, models. Labs, capacity, the runner, tools, dispatch, landing, managers and acceptance all come for free.

**Another product** (for example Astrid running its own film-edit agents) would use the Herzchen model and fleet directly, and define its own roles and policies the way Otto does. That is out of scope here; the import rule keeps it possible.

## 13. Frictions met while setting the program up (15 Oct), and where each lands

| Friction | Evidence | Lands in |
|---|---|---|
| A client's `--help` or malformed forwarded command stops the shared owner | Closed 14 Oct 21:53:53Z after `portfolio onboarding create --help`; installed service.py:305 catches only `Exception` | OWNERSAFE (fixed in source, 12f3a1e) |
| A client waits forever on a closed owner; nobody is told the service is down | My call hung for minutes; Codex learned by message | LIVENESS |
| Restarting after a clean stop needs a one-shot launch intent in the operator's tree; `launchctl kickstart` silently exits 0 | launchd job runs 2, exit 0, state not running | UPGRADE (`otto service restart`) |
| Safe CLI usage could only be learned by reading source | `--help` on forwarded commands was unsafe | OWNERSAFE (help answered client-side), A3 |
| Two routes create a project, with different results | file-mode apply: tasks only at activation; onboarding template: task records outside a portfolio root | A2 (one creation route) |
| A portfolio root needs five files and a run.json per project, plus a generator | bundle.py REQUIRED_FILES | G3, CUTOVER (the file-mode root retires) |
| A `|` inside a task cell breaks parsing | 14 Oct "no pipe characters inside cells" | A4 (no table parsing) |
| The installed source lives in an iCloud folder where listings hang | ~/Documents/Codex | S0 (canonical repo, builds from it) |
| Two Claude sessions coordinate edits to plan folders by message | the 15 Oct r4 hand-off | A3 (Otto checkouts: one writer per project) |
| The owner now runs unsupervised and won't return after a crash, logout or reboot | the 15 Oct manual restart (pid 92281) | dropped with the old owner at CUTOVER (D18); until then, `ops/launch_owner.py` |
| A crash that exits 0 is treated as a normal stop | the 14 Oct exit status 0; launchd restarts only unsuccessful exits | LIVENESS |
| The walking skeleton came last in edition 1 | SKEL depended on every task | STAGE, PERCH and the stages of §16 (SKEL0 is stage 4, on the staging Otto) |
| `portfolio status` (a read) fails as a whole when one project's supervision record differs from the caller | "only the portfolio orchestrator or owner may change project dependencies" (dependencies.py:62-75) | STATUSREAD (early) |
| A supervised restart is refused while any hold exists, and the stale hold can only be released by a running owner | supervision.py:146-150; the 15 Oct restart had to start the owner outside its supervisor | UPGRADE, HOLD |
| Deleting answered lane files while the owner runs closes it (a vanished file mid-listing) | the 15 Oct 23:23:39Z outage, client_lanes.py:204 | LANEFIX |
| Answered requests and IPC are never pruned: 4.1 GB in the live onboarding run, 6.6 GB across old runs | the 15 Oct cleanup (`ops/cleanup-20261015.txt`) | LANEFIX, RET |
| The Store is 8.3 GB of events (5.6 GB) and identities (2.5 GB), with no free pages; the gapless-log admission check forbids deleting rows | the 15 Oct analysis; store.py:1198-1201 | deleted at CUTOVER (D18); RET designs retention for the new Store from the perch's growth figures |
| The live Store (7.7 GB) and the install live in iCloud Drive | the owner's open files: `~/Documents/Codex/…/controller/owner.sqlite` | CUTOVER (the new Otto lives on local disk) |
| Outside Otto: a `bfs … -name ottoctl*` search process left running for 8+ hours | pid 94313 | not Otto's scope (a Claude Code tool leak), noted |
| The manager read `requests.md` once, so three orchestrator notes never reached it; a SendMessage to a headless `claude -p` is held, then dropped | 15 Oct, before 00:15Z | the brief's loop step 0 (fixed); MGR (managers get a real inbox) |
| Free disk fell to 5.3 GB mid-run: other sessions' renders, swap, and two tar pipelines writing the same archive | the 00:26Z stop | the disk rule (RUNBOOK §5); CUTOVER frees 8–10 GB |
| A baseline of the whole suite can't be trusted: tests pass alone and fail together | 136 versus 172 failing ids on the same commit | D19 (each file alone) |
| No test starts the production service, so POOL's startup crash passed its check | `install/controller/shared_operating_service.py:411` | STAGE (startup test), D17 |
| A worker can rewrite existing tests' expectations to make its change pass | POOLX's edits to test_bounded_project_host and test_hostctl_project_service | D19 (an Opus decision) |
| Estimates in focused days overstate agent time about 16× | the first nine tasks | §4 (measured) |
| The orchestrator's long Opus context was two-thirds of the spend | `ops/cost-eta-20261015.md` | RUNBOOK §7 (fresh check-in sessions) |
| Workers couldn't run shell loops, so GREEN made one call per file (179 turns) | GREEN's transcript | TOOLING (`Bash(bash:*)`), landed e13c927 |

## 14. Follow-up projects (drafted 15 Oct; each waits for `PROGRAM#edition-1`)

The user's direction: "they should also include an aggressive cleanup … streamline how we interact with stuff from an actual agent UX perspective". So every project carries a deletion budget and a ledger, and a UX task measured with a cold agent.

| Project | What it does | Deletion budget | Days |
|---|---|---|---|
| SLIM | One way to do each thing in `otto/portfolio` and the controller: one instruction mechanism, one manager-replacement path, one status, dead and one-off code retired, Vision and Native5 decided, an agent UX pass | ≥ 25% of `src/otto/portfolio`, every W0- or incident-specific controller script, everything without a caller | 7.0 |
| EFFECTS | One effect ledger in Herzchen: at most once per identity, unknown held, one reconciliation | the per-case capture and recovery modules | 4.75 |
| PACKS | Roles, profiles, templates, Megado, host data and domain kits as versioned packs | instruction and profile constants in code; duplicate skill copies | 2.5 |
| HARNESS3 | A real third agent through HOSTKIT | host-specific code outside fleet/hosts | 2.0 |
| THROUGHPUT | Focused checks in seconds, the safe cache, a warm renderer for frames | the cold-start paths superseded | 3.25 |
| ASTRIDFLEET | A study: Astrid's agents on the fleet; Astrid Runtime's ledger versus EFFECTS | lab.sh and Astrid-side duplicates, named | 2.5 |
| PROCLIFE | Scope-based process lifecycle: one private group per launch, setsid escapees still caught (17 Oct ruling), per-PID paths retired | 99 measured direct legacy lines in fleet custody | 2.5 |

## 15. Rules every project follows (stated once; the project files point here)

1. **Cleanup:** every task names what it deletes, or says "none". Each project's deletion budget (§14) is the ambition. The deletion ledger is generated from git (each `Land` merge's shortstat, logged in its `land.log`), never kept by hand.
2. **Agent UX:** fewer verbs, tools and steps for the agents a task touches; every refusal it touches carries `next_action`; tools mint request keys; briefs get shorter. Each project's UX task measures this with a cold agent.
3. **Acceptance is the task's check** on its landed commit, through the landing gate (D19), including the staging run. Regression tests must fail first. A change to what an existing test asserts needs an Opus decision. Stage reviews (§16) examine stages, not tasks.
4. **Approval is for agents' changes.** The user's own edits are approved by being made; agent-written changes need `otto admit` or fit the allowance.
5. **Records are generated, not kept:** the landing record, workers and spend come from `ops/report.sh`, and deletions from the `Land` merges in git. The portfolio is re-applied at milestones only.

## 16. Validation: the staging Otto, the observation perch and the stages (15 Oct, evening)

### What the first nine tasks showed
- **Writing code is cheap; knowing it works is the hard part.** An estimated focused day takes about 30 minutes of agent time, and tasks cost $1–5 (`ops/cost-eta-20261015.md`). The defects sat in the integration, and each task's own check passed them:
  - HOLD landed with its new functions unwired.
  - POOL removed `manager_turn_limit` from the execution host, but `install/controller/shared_operating_service.py:411` still passes it, so the owner would fail at startup. No test starts the production service.
  - POOL also made `test_five_projects_share_slots_and_A_settles_while_B_waits` fail 4 runs in 5. Its check didn't include that file.
  - The delegated POOL rerun counted managers against worker turns, and rewrote two existing tests' expectations so they passed.
  - The first two would have surfaced at SKEL0 or REH, a dozen or more landings later; the third only in a review.
- **The POOL rerun** (`ops/experiments/POOLX/comparison.md`), the same brief from the same commit:

  | | Sonnet alone (POOL) | Sonnet lead, Haiku sub-agents (POOLX) |
  |---|---|---|
  | active time | 35.5 min (22.4 min to its disk stop) | 24.7 min |
  | cost | $3.07 ($2.43 to its disk stop) | $2.11 (Sonnet $1.28, Haiku $0.82) |
  | tool calls | 122, all Sonnet | 222, of which Haiku 180 |
  | defects | startup crash; one flaky regression | managers take worker turns; two tests rewritten |

  Delegation cut cost by about 15–30% and saved no time. Quality was different rather than worse: the rerun broke nothing and found the production call; the original's design was better.
- **Orchestration is the cost and the latency.** One long Opus orchestrator session was two-thirds of the spend. The manager's inbox failed silently for hours, and owner actions waited for hourly check-ins.
- **The disk binds.** It has 5–13 GB free and swap is nearly full, so REH's 7.7 GB Store clone wouldn't fit.

### The staging Otto (STAGE, D17)
- A fresh, empty Otto from `canon/main`, started through the product entry point (`ottoctl service run`), with its own Store and socket under `labs/_staging`.
- Every landing restarts it on the merged commit and runs the startup test and the current stage's canary scenarios.
- It stays after CUTOVER as the pre-production instance.

### The observation perch (PERCH, D20)
`ops/bootstrap/perch.sh <stage>` restarts staging, runs that stage's canary scenarios, and writes `ops/perch/<stage>/<UTC time>/report.md` with the raw data beside it:
- each task's timeline from the Store: admitted, dispatched, lab, turns, checks, done, landed, lab deleted;
- a process census before and after, to catch leaks and wrong kills;
- labs and scratch left over;
- the pool's units over time;
- Store growth per task and per save;
- the line's git history;
- tokens and cost per task;
- waits and durations, with disk and swap at the same moment.

**The canary project** is a toy repo with a project file. Its tasks:
- pass first time;
- fail a check and get fixed;
- conflict at landing;
- ask a question;
- chain by deps;
- run a heavy check;
- get killed mid-turn;
- and a second project runs alongside.

Scenarios are tagged by stage; one whose features haven't landed is skipped and says so. A skip inside the stage's own scope fails that stage: a stage passes only on scenarios that ran. A stage review opens only after the previous stage passed. A fake harness runs them at every landing at no cost; real Haiku workers run them at stage reviews. Assertions are plain checks over the report (for example: nothing left over; the pool never over its units), and every stage review adds more.

### The stages
| Stage | Opens when these have landed | Live run on staging | What the reviewer checks in the data |
|---|---|---|---|
| 0 Boots | STAGE, PERCH (with POOL, HOSTKIT, GREEN) | start an empty instance; status; stop; kill; restart | it starts, or says exactly why not; status tells the truth; nothing is left over after a stop; a restart after a kill recovers; the Store's size at rest |
| 1 Holds plans | A1, TYPE, A2 | save the canary from a file; show; edit; save again; a save from a stale base | tasks are typed records; nothing runs; edits make revisions; the stale save is refused; Store growth per save |
| 2 Dispatches | ADMIT, DISPATCH, CUSTODY, COMPOSEFLEET, PERCH2, AUTODISPATCH, AUTODISPATCH2, STAGESETUP, OPERATOR-ADMIT, PERCH2B, ACTCRIT, PINCONTENT, LABCAPTURE, ORPHANWORKER, PERCH2C, COMPLETECITE, KILLFENCE, LIMITFD, MANUALDISPATCH, PROJECTPIN, READYPIN, FACADEFD, SESSIONFD, SCRIPTMGR, PERCHUNTIME, HOLDSTATUS (the stage passes only with no product method patched by the harness: fake-run stand-ins for presence, worker turns and completion only) (17 Oct, evening: the first full pass on canon 5b4a770 FAILED its Opus review: the harness patched `LabFleet.remove`, hiding that real workers settle unknown on landing; a worker outlived a forced stop; five checks couldn't fail; ops/reviews/STAGE2.md) (17 Oct: nothing called the dispatcher, and no path let the operator admit; the real run needs a person at the Mac for the presence check) (16 Oct: the owner composes no dispatcher before COMPOSEFLEET, and stage 2 had no canary) | admit the canary, with the fake harness | only admitted, ready tasks start, in dependency order; the pool and the manager reserve hold; an unadmitted revision is refused; a killed worker frees its slot, and nothing leaks or is wrongly killed |
| 3 Works | LAB, RUNNER, TOOLS, EVIDENCE, CAPTUREEDIT, FAILEDFENCE, SESSIONFD, REALSTAGE3 (17 Oct audit triage, ops/audits/20261017/TRIAGE.md) | real Haiku workers on three canary tasks | one lab per task (time to create, size); checks go through the runner within heavy units; `task`, `check` and `done` work (`ask` is stage 5's, with ASK); evidence verifies |
| 4 Lands | LAND (SKEL0 is this stage's run) | the canary's happy path and a landing conflict (detected and refused, the worker resumed with it; repair is REWORK's, stage 5) | one landing per task, each checked on the exact merged commit; labs deleted; nothing left over; Store growth per task |
| 5 Manages | MGR, ASK, REWORK, CHANGE, ACT, LANEFIX, LIVENESS | a failed check, a question, an edit after admission, a second project | a failure resumes the same session; the manager wakes only for judgment; the answer reaches whoever asked; agent-changed tasks wait; the second project activates while the first runs; a closed owner is reported, not waited on |
| 6 Dogfood | A3, A4, RETIRE, A6, CONV | the program saved into staging; two real program tasks dispatched by it and landed (the orchestrator names two not-yet-started tasks when the stage opens and tells the manager not to launch them) | it runs our own work; time, cost and failures compared with the bootstrap; `otto open`, `show` and `status` work for a cold agent; r4's save previews exactly its changes |
| 7 Switch-over | CUTOVER | list, save, verify, switch, delete | every upcoming project present by diff; clients on the new owner; nothing references the old paths; disk freed |
| 8 Many | SKEL, MANY, R1d, INTEG-PROCLIFE-PL1, INTEG-PROCLIFE-PL2, INTEG-PROCLIFE-PL3, INTEG-PROCLIFE-PL4, INTEG-PROCLIFE-PL5 | cold Claude and cold Codex journeys; workers ramped up; an Astrid render through the pool | sustainable concurrency with memory pressure never critical; heavy seconds per accepted task; renders don't deadlock |

**17 Oct, evening (TRIAGE-C decisions):** stages 3 and 4 share one review, and stages 5 and 6 share one, each with separate verdicts per stage on the same candidate. CUTOVER's first release runs Claude workers, reconnects Codex clients, activates projects while quiescent and holds UNKNOWN effects, so CODEXOWNER and ACTIVATEWHILE no longer gate CUTOVER (they stay queued); the manager interface at CUTOVER is the authenticated CLI (CLIARGS, MGRASK), MGRMCP after. CUTOVER still needs the user's explicit go on the exact deletion set (XFERMAP, XFERBOUND).

### A stage review
1. The orchestrator runs `perch.sh <stage>` with real Haiku workers.
2. A fresh Opus session examines the stage: `ops/launch_review.sh STAGE<n> opus`, which runs `claude -p --model claude-opus-5-5 --effort high` with the `haiku-worker` sub-agent, as in the POOL rerun, and the brief from `ops/review-brief-template.md`.
   - It reads the report, the raw data and the code landed since the last stage.
   - Haiku helpers query the Store, rerun scenarios and gather evidence; Opus judges.
   - It never edits code.
3. It writes `ops/reviews/stage-<n>.md`: what works, what doesn't, and for each finding either a fix task or a new perch assertion.
4. The orchestrator checks the key claims in source before acting on them, adds the assertions, and tells the user the stage's result.

A failed stage is fixed and re-reviewed, from the reserve, before the next stage's review.

### The Opus budget: 15 calls (the user, 15 Oct; tracked in run.json)
| Use | Calls |
|---|---|
| stage reviews 0–8 | 9 |
| the final review of edition 1 (REVIEW) | 1 |
| reserve: re-reviews of failed stages, D19 decisions, second failures, contested findings | 5 |

At about $4–5 a call, that's $60–75. With RETAIN, REH, H0 and SUPERVISE dropped, INSTALL and IMPORT merged into CUTOVER, and STAGE and PERCH added, edition 1 is 2.25 focused days smaller. The whole program is likely about $250 all in (it was about $200), with defects found at the stage that causes them.

### Astra reviews: 5 calls (the user, 15 Oct, late)
Astra (`gpt-6-astra`, high, through `codex exec`) is a second model family. The user finds it more holistic and less exact at checking. So:
- Opus keeps "does it work", judged on the data.
- Astra gets the questions where breadth and taste matter, and where a miss is caught elsewhere: what is missing that nobody thought to test, what is built twice, what to delete, what an agent would trip over.
- Each Astra review runs alongside its stage's Opus review, not after it. Neither sees the other's answer.
- Findings both reviewers raise are taken as found. A finding only one raises is checked in source by the orchestrator (with Haiku helpers) before it becomes a fix task. A contested finding goes to an Opus reserve call.
- All five are scheduled; there is no Astra reserve.

| ID | When | Alongside | Astra's job |
|---|---|---|---|
| ASTRA0 | now, before work resumes | — | Can this be run as written? |
| ASTRA1 | stage 1 (Holds plans) | STAGE1 | The model's shape, before 25 tasks build on it |
| ASTRA2 | stage 4 (Lands; SKEL0) | STAGE4 | Layering and over-engineering in the walking skeleton |
| ASTRA3 | CUTOVER, before the delete step | the orchestrator's save diff | What else depends on the old Store |
| ASTRA4 | stage 8 and the final review | STAGE8, FINAL | A cold Codex journey, and the end state |

**ASTRA0: can this be run as written?** The plan, RUNBOOK, tasklist, manager brief, brief template, check-in checklist and launchers.
1. Play the Haiku manager for its first six launches and three landings, using only these documents. List every point where you'd have to guess, where two documents disagree, or where a named path, command or session doesn't exist. Luna helpers check each one.
2. For the next ten tasks in RUNBOOK §8 order: could the task's check pass while the outcome is wrong (POOL's pattern: a function left unwired, a production caller not exercised)? Give the one check line that would catch it.
3. Which rows still invite fleet code into `src/otto` (D14)?
4. Which process costs more than it protects? Name what to cut.

**ASTRA1: the model's shape** (with STAGE1; A1, TYPE and A2 landed).
1. Is there exactly one source of truth for a plan, a task and its status? Name every place one fact is stored twice: Store tables, files, generated views, caches.
2. Is this the smallest schema that carries the end state in §1? Which field or table has no reader?
3. Will the six follow-up projects, Astrid's work and a superseded project fit without special cases?
4. In the perch's Store-growth numbers, what grows that needn't?

**ASTRA2: layering and over-engineering** (with STAGE4; the walking skeleton runs).
1. Could a second product, such as an Astrid fleet, use `herzchen/fleet` unchanged? List every Otto word, path or default inside Herzchen.
2. Where are there two mechanisms for one purpose (pools, status reads, retention, locks, labs)?
3. What landed that the skeleton doesn't need?
4. Count the commands and files an agent touches from taking a task to its landing. What would the elegant version be?

**ASTRA3: what else depends on the old Store** (before CUTOVER's delete step). The deletion can't be undone, and Claude prepared the list, so a different family checks it. The exact diff of the saves is the orchestrator's job, and stage 7's.
1. Given the list of upcoming projects, the saves and their verification, what else could depend on the old Store or its run folders? For example: Codex threads and skills that embed its paths; launchd jobs; installed editions under `~/.codex/owner-services`; Astrid's clients; other sessions' work, such as r4 and the SL retention; notes and receipts. Luna helpers search for the old paths in named places only, with time limits: no listings of `~/Documents/Codex` or iCloud.
2. What would the user regret losing that isn't a project: history, decisions, evidence?
3. Is the rollback real right up to the delete?

**ASTRA4: a cold Codex journey, and the end state** (with STAGE8 and FINAL). It runs with `--write`, on staging only.
1. As a cold Codex agent with only the installed Otto skill: open the program, find a ready canary task, take it, run its check, ask a question and finish. Report each friction as it happens. Luna helpers run further journeys in parallel.
2. Does the system match §1's end state? What is still two mechanisms, and what should be deleted?
3. What would a third agent host need to add? Is that one implementation, as HOSTKIT promised?
4. Which of the six follow-up projects should change in the light of this?

## 17. How Otto is tested (the orchestrator's design, 17 Oct 2026, evening)

Today's ~70 defects came from a few classes, and unit tests passed for nearly all of them: an ordinary write blocking later work (exact-revision pins: PINCONTENT, POLICYPIN, PROJECTPIN, READYPIN); side effects in the wrong order (LABCAPTURE, ORPHANWORKER); things never released (KILLFENCE, FAILEDFENCE, FDLEAK, FACADEFD, SESSIONFD, TESTREAP); a launch path skipping a step (MANUALDISPATCH); deferred results misused (OWNERCOMPLETION); races in file lanes (CTLRACE). They surfaced only in a full journey, and some were hidden by a harness that patched the product. So:

1. **A few journeys through the real product.** The perch canary runs through the real owner, Store, dispatch, labs, git and gate. Only the two true boundaries are faked: the model (a scripted Claude or Codex turn) and the person (the presence prover). A fake never patches a product method.
2. **Invariants over the recorded evidence, checked after every step**, not scripted expected outputs: (a) every launch has exactly one dispatch, and the exact content it ran was admitted; (b) every turn settles exactly once, and every hold or fence is released or names its next action; (c) ordinary writes (metadata, edits, admissions, lifecycle) never block later work; (d) no process, socket, lab or temp root outlives the run, and descriptors stay flat per operation; (e) completion cites the accepted evidence; (f) Store history is gapless. Each invariant guards a class; a new scenario gets all of them.
3. **Ordinary disturbances as scenario steps**: edit after admit, admit after prepare, kill a worker, restart the owner mid-turn, a refused landing, two projects at once, concurrent landings. This is where the classes above show up.
4. **Unit tests** for pure logic and to pin a specific fix fast (fail first). A cross-component defect is covered when an invariant plus a disturbance would catch its regression, not by its unit test alone; no bespoke journey assertion per bug.
5. **Honesty, enforced mechanically**: no product patch outside an allow-list of boundary stand-ins; no time limits (only a hang fails, judged at the run level); every check has a test where doctored evidence makes it fail.
6. **Where it runs**: each landing runs the touched modules' tests (THROUGHPUT's selector) plus the passed stages' journeys with fakes (`ops/stages-gated`); each night, every built journey runs on canon, including real-model ones from stage 3; a `check-run` effect lets a worker run its socket and sandbox tests outside the sandbox before landing, so "needs the gate" stops being a blind spot.

Rows that add journey checks implement this shape: invariants live as functions over the evidence in `ops/bootstrap/perch_report.py`, disturbances as steps in `perch.sh`. Astra's coverage map (ops/audits/coverage/JOURNEY-COVERAGE.md) is evidence for which disturbances and invariants are missing; the orchestrator decides the rows.
