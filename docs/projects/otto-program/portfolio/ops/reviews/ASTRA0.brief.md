# Review brief: ASTRA0 (astra), can this be run as written?

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). You are a second model family. Opus reviews whether things work; you judge whether this is the right shape: what is missing that nobody thought to test, what is built twice, what should be deleted, and what an agent using it would trip over. Breadth and imagination matter here; every finding still needs evidence.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. Never start any script under `ops/` or `ops/bootstrap/`: read them. Your final message is saved as `ops/reviews/ASTRA0.md`.

## The situation
- The program is **paused**, and nothing runs. On the user's go it starts by RUNBOOK §0: TOOLING3, then a Haiku 5.5 manager (`ops/launch_manager.py`, brief `ops/manager-bootstrap-brief.md`) that launches up to 2 workers and lands their work through the gate; Claude (Opus) is the orchestrator, checking in hourly by `ops/checkin-checklist.md`.
- Workers: normal tasks run as Haiku 5.5; XHARD tasks as a Sonnet 5.5 lead delegating to Haiku sub-agents. All are headless `claude -p` sessions in git worktrees under `~/Developer/otto-claude-host/labs/`.
- `canon/main` of `~/Developer/otto-claude-host/otto` is at 9739a29. HOSTKIT, POOL and GREEN finished in labs but haven't landed; `ops/fixes/` has the resume messages for the first two.
- **TOOLING3 is not done yet.** `run-task.sh` doesn't yet give XHARD leads the `haiku-worker` sub-agent, and `land.sh` doesn't yet run the gate. Judge whether RUNBOOK §1.2 specifies them precisely enough, not whether they exist.
- The stage scripts (`staging.sh`, `perch.sh`) are tasks STAGE and PERCH, not yet built.

## Hand the legwork to helpers
Use `spawn_agent` with `model: "gpt-6-luna"`. Split the work into as many parallel helpers as it divides into: one per document pair to cross-check, one per script to read against the docs that describe it, one per batch of named paths, commands and session ids to verify they exist. Each helper brief is self-contained: the question, the exact paths, the read-only command to run, and what to report (file:line, output tails). You keep the judgment: a helper's "this is fine" is a lead, so look at the evidence it cites before you rely on it.

## Read
- `PLAN.md`: the header and its revisions, §1 (the end state), D10, D14, D17–D20, §11 (layers), §15, §16 (validation, the Opus and Astra budgets).
- `RUNBOOK.md`; `projects/program/tasklist.md`; `projects/program/run.json`.
- `ops/manager-bootstrap-brief.md`, `ops/brief-template.md`, `ops/checkin-checklist.md`, `ops/review-brief-template.md`, `ops/fixes/POOL.md`, `ops/fixes/HOSTKIT.md`.
- The launchers: `ops/launch_manager.py`, `ops/resume_manager.py`, `ops/launch_review.sh`, `ops/launch_owner.py`.
- The bootstrap scripts in the Otto repo: `~/Developer/otto-claude-host/otto/ops/bootstrap/` (`common.sh`, `run-task.sh`, `land.sh`, `otto-lab.sh`, `report.sh`, `workers.py`).
- `ops/STATUS.log` and `ops/requests.md` for history; `ops/experiments/POOLX/comparison.md` for the one measured comparison.

## Questions
1. **Play the Haiku manager** for its first six launches and three landings, using only these documents. List every point where you'd have to guess, where two documents disagree, or where a named path, command, flag or session doesn't exist. Have Luna helpers verify each path, command and id. Remember the manager is Haiku: an instruction a careful senior engineer would read correctly but a literal, fast model could misread counts.
2. **Play the orchestrator's hourly check-in** once against the checklist. Can each of its four helpers actually find what it's asked for in the files named (log formats, field names, where `land.log` comes from)?
3. **For the next ten tasks in RUNBOOK §8's order:** could the task's check pass while the outcome is wrong? POOL's pattern: a function left unwired, a production caller not exercised, a test's expectation quietly changed. For each, give the one check line that would catch it.
4. **Placement (D14):** which tasklist rows still invite fleet or model code into `src/otto`?
5. **What costs more than it protects?** Name any process, file, record or gate to cut, and what it would save.
6. **Anything else** that would stop this running for 17 hours unattended between hourly check-ins: silent failures, things that wait forever, budgets or limits that can't be enforced as written.

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL (unsafe to go on).
2. **Findings**, most severe first. For each: what is wrong; the evidence (file:line); why it matters; the fix, as a concrete edit to a named document or script.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list.**
6. **Helpers:** how many you ran and what each did, one line each.

Don't pad. No finding without evidence.
