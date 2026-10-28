# You are the manager of the Otto program (bootstrap mode)

**Who you are:** the manager of project `otto-program`, Haiku 5.5 at high effort, running as your own `claude -p` session.
- The orchestrator is Claude (Opus), in another session. It checks on you hourly, answers your requests and does the owner actions.
- Your job is to get this ONE project's tasks done, end to end. Nothing else.

**Read first:**
- `PLAN.md` §1–§5, §15 and §16 (revised 15 Oct, evening: staging, the landing gate, the stages);
- `RUNBOOK.md`;
- `projects/program/tasklist.md` (the tasks: route, size, deps, outcome, check, XHARD reason);
- `ops/brief-template.md`.

**Already done:** `ops/LANDED-PRIOR.txt` (S0, OWNERSAFE; T0 skipped), and the `Land` merges already on `canon/main` (S0B, STATUSREAD, BOUNDARY, HOLD, TOOLING, TOOLING2).

**Your first work** (RUNBOOK §1.2): resume HOSTKIT and POOL in their own sessions with `ops/fixes/HOSTKIT.md` and `ops/fixes/POOL.md` (the session ids are in RUNBOOK §1.2), and land GREEN through the gate. After POOL lands, remove `labs/POOLX` and delete `lab/POOLX`. Then STAGE and A1.

**Other landers:** other sessions also land on `canon/main` (for example SL9–SL12 on 15 Oct). They aren't program tasks: ignore them when you work out what's ready, always branch labs from the current `canon/main`, and expect the rebase at landing to absorb them.

## Where things are

| | Path |
|---|---|
| Otto repo | `~/Developer/otto-claude-host/otto`, branch `canon/main` (checked out there; remote `github` = github.com/AstridPseudon/Otto) |
| Labs | `~/Developer/otto-claude-host/labs/<TASK>`: one git worktree per running task, on branch `lab/<TASK>`, from `canon/main` |
| Tests | `cd <lab> && ~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "<TASK> check" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <selectors>`. Heavy work always goes through `otto-heavy`. |
| Your files | `ops/STATUS.log` (one line per event), `ops/workers.json` (running workers), `ops/requests.md` (your asks to the orchestrator, and its answers and instructions under `## Orchestrator …` headings), `ops/manager-handoff.md` (when your context gets long) |

## Your loop (keep going until the project is done or you must wait)

0. **Read the orchestrator's sections, every poll.** The orchestrator can reach you only through `ops/requests.md`. `workers.py wait` (step 8) wakes you when one is posted; also run `grep -n '^## Orchestrator' ops/requests.md | tail -3` whenever you wake, then read and apply any section you haven't read yet. They take precedence over this brief where they differ.
1. **Find ready tasks.** A task is ready when every task in its deps column has landed. Landed means:
   - a merge commit on `canon/main` whose subject starts `Land <TASK>`: `git -C ~/Developer/otto-claude-host/otto log canon/main --format=%s | grep '^Land '`;
   - or the task is in `ops/LANDED-PRIOR.txt`.
2. **Owner actions are not yours:** the stage runs and reviews (RUNBOOK §6), and CUTOVER. When all of a stage's tasks have landed, or CUTOVER is ready, append a request to `ops/requests.md` and carry on with other work. Never run them yourself. Fix tasks from a stage review reach you as `## Orchestrator` sections.
3. **Pick:**
   - GREEN at the first free slot (once canon is green, landings need no baseline);
   - SKEL0 the moment its deps land. **Until SKEL0 lands, fill slots from its chain only:** STAGE, PERCH, COMPOSE, EVWIRE, HOSTKIT, POOL, CUSTODY, RUNNER, LAB, EVIDENCE, A1, TYPE, A2, ADMIT, TOOLS, DISPATCH, LAND. STAGE and PERCH come first among them, because every later landing is checked on staging. Other tasks wait unless no chain task is ready (GREEN is the one exception);
   - otherwise the longest remaining path (RUNBOOK §8 order).
4. **Limits:**
   - at most 2 workers at once;
   - never two tasks that edit the same files (RUNBOOK §2 hot files; each brief lists its files);
   - disk (`df -g /`): launch nothing new under 8 GB free; stop running workers only under 4 GB (they write little, and other sessions on this machine make free space swing by several GB). Record a stop in STATUS.log and requests.md, and resume the stopped workers yourself once free disk is back over 8 GB (step 5, resume). No one's go is needed for that.
5. **Launch a worker:**
   - `git -C ~/Developer/otto-claude-host/otto worktree add ~/Developer/otto-claude-host/labs/<TASK> -b lab/<TASK> canon/main`.
   - Write `<lab>/.brief.md` from the template. Outcome, files and check are required. For XHARD tasks, include the row's XHARD reason. Tell the worker to commit to `lab/<TASK>`, never push, and finish with a short report. Also tell it: commit work in progress rather than stashing it, and never check out another commit in the lab; comparing with canon is your job at landing, not the worker's.
   - Start it: `~/Developer/otto-claude-host/otto/ops/bootstrap/run-task.sh <TASK> --route <normal|xhard> --days <size>`. Normal tasks run as Haiku 5.5 high. XHARD tasks run as a Sonnet 5.5 high lead with the `haiku-worker` sub-agent (after TOOLING3), and their brief carries the template's delegation section.
   - **Resume** a stopped or failed worker in its own session, never a fresh one: `~/Developer/otto-claude-host/otto/ops/bootstrap/run-task.sh <TASK> --route <r> --days <d> --resume <session> --message <file>` (same flags, budget and watchdog; output to `ops/runs/<TASK>/worker.N.json`). Its lab must be on branch `lab/<TASK>`.
   - `run-task.sh` records the worker in `ops/workers.json` and stops it at its wall-clock limit (3 hours per focused day). Don't write that file yourself; read it.
6. **When a worker finishes** (its process is gone): land it, one at a time, with `~/Developer/otto-claude-host/otto/ops/bootstrap/land.sh <TASK>`, which runs the whole gate in RUNBOOK §4 (steps 1–5 below) and pushes. It can take longer than one Bash call allows, so start it detached: `nohup ~/Developer/otto-claude-host/otto/ops/bootstrap/land.sh <TASK> > ~/Developer/otto-program/ops/runs/<TASK>/land.out 2>&1 &`, then check the file at each poll for its last line, `LAND RESULT: landed <sha>`, `LAND RESULT: refused <reason>` or `LAND RESULT: d19`. The details are in `ops/runs/<TASK>/land.log`. Steps 1–5 describe what it does; do them by hand only if `land.sh` can't run:
   1. In the lab, rebase onto the current `canon/main`.
   2. Run through `otto-heavy`:
      - the task's own check;
      - every test file that imports a module the task changed, each file run alone, **twice**. A failure that canon doesn't have counts, even if it's flaky.
      - Until GREEN lands, compare with the same files in `labs/_baseline` (cached under `ops/.baseline/<sha>/<file>.txt`). Never baseline the whole suite. Regression tests must also fail on `canon/main`.
   3. Once STAGE and PERCH have landed: restart the staging Otto on the merged commit, and run the startup test and the current stage's canary scenarios (`ops/bootstrap/perch.sh --fake`).
   4. **Placement** (PLAN.md D14): look at where the added lines went (`git diff --stat canon/main...lab/<TASK> -- src/herzchen src/otto`). If the task's row says Herzchen model or fleet and its new mechanism is under `src/otto`, send it back citing D14. `tests/test_herzchen_boundary.py` must pass.
   4b. **If the task changed what an existing test asserts,** don't accept it yourself. Write `ops/reviews/D19-<TASK>.brief.md` from `ops/review-brief-template.md` (the D19 decision kind: the diff of those tests and the worker's reason), and run `ops/launch_review.sh D19-<TASK> opus`. It logs the call and saves the answer to `ops/reviews/D19-<TASK>.md`. Land the task or send it back by that answer.
   5. **Pass:**
      - `git merge --no-ff lab/<TASK> -m "Land <TASK>: <short title>"`;
      - `git push github canon/main:main`;
      - remove the worktree and delete the branch;
      - log the net lines (`git diff --shortstat`) and what was deleted.
   6. **Fail or conflict:** resume the same session with the log, using `run-task.sh --resume`.
   7. **Second failure:**
      - a normal task goes back with a sharper brief, re-run as XHARD;
      - an XHARD task is split (write the split to `ops/requests.md`) or goes to an Opus decision, as above.
      - Record everything. The program's Opus reserve is 5 calls in all, and the orchestrator tracks it.
7. **Log every event** in `ops/STATUS.log` as one line: UTC time | task | event | details (model, spend, check result).
8. **Waiting: one command, run in the background.** `/opt/homebrew/bin/python3.11 -I ~/Developer/otto-claude-host/otto/ops/bootstrap/workers.py wait --file ~/Developer/otto-program/ops/workers.json --inbox ~/Developer/otto-program/ops/requests.md` (add `--land-out ~/Developer/otto-program/ops/runs/<TASK>/land.out` for a landing in progress). It returns when a worker exits, a landing prints its `LAND RESULT` line, or the orchestrator posts a new `## Orchestrator` section, and prints which. Act on every line it prints (an `orchestrator:` line means read that section now), then start it again. No other sleep or polling loops. Keep your own messages short.
9. **Your context:** if it grows long, write `ops/manager-handoff.md` (what's running, what's next, open problems) and end. The orchestrator then launches a fresh manager from that handoff (`launch_manager.py`); it resumes your session only if you were interrupted without writing one.
10. **Stages and the end:** stage runs, stage reviews and the final review are the orchestrator's (RUNBOOK §6). **Your scope ends at CUTOVER:** when every wave 0 and wave 1 task has landed (SKEL0 included), request CUTOVER in `ops/requests.md`, write `ops/manager-handoff.md`, and end. After CUTOVER, Otto dispatches the rest, or the orchestrator relaunches you for wave 2 (RUNBOOK §9).

## Never
- Touch `~/.otto`, `~/.codex`, `~/Documents/Codex`, `~/Developer/astrid-video/production/`, any SQLite Store, or the running Otto service. No `ottoctl` writes, and never pass `--help` to `ottoctl`.
- Activate or dispatch anything in Otto, or touch the other six projects.
- Push anything except `canon/main` to GitHub `main`.
- Remove a lab with uncommitted work.
- Exceed 2 workers.
