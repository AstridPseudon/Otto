# Hourly check-in (the orchestrator's /loop)

**Status: RUNNING since 15 Oct 17:50Z** (cron 7135edd9 in the orchestrator's session, hourly at :17 local). Start it again, if it's lost, by RUNBOOK §0, step 5:
`/loop 1h Otto program hourly check-in: follow ~/Developer/otto-program/ops/checkin-checklist.md exactly`

Only the first project, `otto-program`. Each tick: fan out, judge, push forward, report. Helpers gather the evidence and the orchestrator makes the decisions. Keep the orchestrator's own reading small: the helpers read the logs.

**Since when:** the last line in `ops/STATUS.log` whose event is `checkin` (none yet: use the last `| program |` line).

## 1. Fan out four Haiku helpers, in parallel, in one message
Use the Agent tool with `model: "haiku"`. Each helper is read-only, gets the "since" time and the paths below, and reports in at most 15 lines, citing evidence (file:line, log lines, command output). Ask for facts, not verdicts.

1. **The manager.** Read `ops/manager-session.json` and the stream-json in `ops/manager.log` since the last tick.
   - **Since 16 Oct 15:01Z the manager is Luna on Codex** (`ops/manager-codex.md`): `pid` in the session file is `ops/manager_loop.py`, whose child is the current `codex exec` turn. In `ops/manager.log`, Codex events (`thread.started`, `item.completed` with `command_execution` or `agent_message`, `turn.completed` with usage) and the loop's own `{"type":"loop"}` lines replace Claude's stream-json. Effects it asked for are `ops/effects/*.done` with `*.out`. Its context is the last `turn.completed` usage's `input_tokens`.
   - Is the process alive (`ps -p <pid>`), and what did it do: launches, landings, requests, errors, loops?
   - Did it follow `ops/manager-bootstrap-brief.md`? Check: it waits only with `workers.py wait` and reads each `orchestrator:` line it returns; at most 2 workers; the model matches the route; no two tasks on the same files; it uses `run-task.sh --resume` for failures; owner actions are requested, not done.
   - Its spend (the `result` lines' `total_cost_usd`), and its context size if visible.
2. **The workers.** Only what the files show (workers write one result JSON when they finish, nothing while running):
   - **running** (entries in `ops/workers.json`): alive (`ps -p`), elapsed against the deadline, and progress as commits on `lab/<TASK>` since the last tick (`git -C <lab> log --since=<time> --oneline`). No commit for over an hour is worth a look;
   - **finished** since the last tick (`ops/runs/<TASK>/worker*.json`): `total_cost_usd` against the budget, `num_turns`, `is_error`, and for xhard the Haiku and Sonnet costs in `modelUsage` and the sub-agent count in `subagent_stats`; the `result` text's own list of what it couldn't do.
3. **The landings.** For each `Land <TASK>` merge on `canon/main` since the last tick (`git -C ~/Developer/otto-claude-host/otto log --first-parent --since=<time> --format='%h %s' canon/main`), read `ops/runs/<TASK>/land.log`:
   - every test file that imports a changed module ran alone, twice;
   - staging was restarted and the canary ran (once STAGE and PERCH have landed);
   - the placement report, and whether new fleet or model code landed under `src/otto`;
   - any change to an existing test's assertions, and its D19 decision in `ops/reviews/`;
   - pushed to GitHub `main`; the worktree and branch removed; net lines.
4. **Health and drift.**
   - free disk (`df -g /`), memory pressure (`memory_pressure | tail -1`), swap (`sysctl vm.swapusage`);
   - the live owner is serving: in `~/.otto-clients/claude-code/lanes/claude-code/status.json`, `heartbeat_at` within 2 minutes and `holder.pid` alive. If not, tell the user (the bootstrap doesn't need it until CUTOVER, and other sessions restart it);
   - leftover processes: `claude -p` or `pytest` processes with no entry in `ops/workers.json`;
   - labs under `~/Developer/otto-claude-host/labs` with no running worker and no pending landing;
   - **non-program landings** on `canon/main` since the last tick (subjects not starting `Land <program task>`, e.g. SL*): the files they touched, against the running tasks' files and RUNBOOK §2's hot files;
   - open asks in `ops/requests.md` that wait on the orchestrator;
   - premium calls so far: `| opus |` lines (budget 15) and `| astra |` lines (budget 5) in `ops/STATUS.log`.

## 2. Judge
- Read the four reports. For each, check one claim yourself in the evidence it cites, plus anything that would change what you do.
- **Push forward** where something is blocked or wasteful. Append a `## Orchestrator <UTC>` section to `ops/requests.md` (the manager greps for those headings at every poll), then confirm it was read by grepping `ops/manager.log` on the next tick. SendMessage does NOT reach the headless manager.
  - For an immediate change, stop it between turns (`kill -TERM <pid>`; workers are detached and survive) and run `python3 ops/resume_manager.py`.
  - If the manager has ended and its goal isn't met: if it wrote a fresh `ops/manager-handoff.md` (its context was long), launch a fresh manager with `python3 ops/launch_manager.py`; if it was interrupted without one, resume the same session with `python3 ops/resume_manager.py`.
- **Owner actions are yours:**
  - stage runs and reviews (RUNBOOK §6): run `perch.sh`, then launch `STAGE<n>` and any paired Astra review with `ops/launch_review.sh` in the background;
  - splits and contested findings: decide as captain, and write the answer to `ops/requests.md`;
  - CUTOVER only after the user's explicit go, given after they have seen the list of upcoming projects and their verified saves.
- **Stop everything and tell the user** on RUNBOOK §5's stop conditions.

## 3. Record and report
- One line in `ops/STATUS.log`: `<UTC> | orchestrator | checkin | landed N, running [..], spend $X, actions taken`.
- Report to the user in at most 6 lines: progress, anything off, what you did about it.

## 4. When the goal is met
The loop's goal is edition 1: the final review done and `PROGRAM#edition-1` reached. The bootstrap manager's own goal ends earlier, at CUTOVER (RUNBOOK §9). After CUTOVER, helper 1 reads the project's state from Otto (`otto status`) instead of the bootstrap manager's log.
- Total the tokens by model: the manager's and every worker's result JSON or stream-json usage (input, output, cache read, cache creation) and cost, plus every premium call (`ops/reviews/.raw/`). Use each run's `modelUsage`, because sub-agent transcripts undercount output tokens. A resumed session's `worker.N.json` holds the session's running total, so take the last file per session id and never add a session's files together (checked on COMPOSE and PERCH0FIX, 16 Oct). Astra's usage, and its Luna helpers', are in the `review-done` lines. Codex workers and the Luna manager have no dollar cost line. A **resumed** Codex worker's `turn.completed` is the thread's running total, so take each task's LAST `worker*.jsonl` (`workers.py spend` after TOOLING16); the manager's wakes are fresh sessions, so sum its `turn.completed` lines in `ops/manager.log`; their sub-agents' usage is NOT in worker.jsonl: it is in `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` files whose first lines carry `"parent_thread_id":"<the worker's session>"` (read those files only, by grep for the id). Count their model too: LAND's Sol lead started two Sol sub-agents against its brief (16 Oct).
- Report the totals by model and by task.
- Cancel the loop.

**Archived logs (19 Oct pause):** `ops/manager.log` up to the pause is `ops/manager.log.gz` (its turn.completed totals are in `ops/manager-usage-total.json`: 758 turns, 237.4M input, 211.5M cached, 3.0M output); landed tasks' `ops/runs/<TASK>/*.jsonl` are gzipped (`*.jsonl.gz`). Read them with `zcat` for step 4.
