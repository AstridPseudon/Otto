# Review brief: STAGE0 (opus), stage 0 "Boots"

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). **Opus:** you check whether it works, judged on the live data and the code. Be diligent: a claim without evidence is not a finding, and a check you didn't run is not a pass.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. The staging Otto under `~/Developer/otto-claude-host/labs/_staging` may be read and queried, but don't start, stop or kill it: landings restart it. Your final message is saved as `ops/reviews/STAGE0.md`.

## Hand the legwork to helpers
Use the Agent tool with `subagent_type: "haiku-worker"`. Split the work into as many parallel helpers as it divides into: one per question, file or claim. Each helper brief is self-contained: the question, the exact paths, the command to run, and what to report (file:line, output tails). You keep the judgment, and you look at the evidence a helper cites before you rely on it. The machine is short of memory and disk (about 3 GB free), so run at most 3 helpers at once, and have them run single test files, never a whole suite.

## Read
- `PLAN.md` §1 (the end state), D14, D17 (the staging Otto), D19, D20 (the perch) and §16 (the stages; the stage 0 row); `RUNBOOK.md` §6.
- `projects/program/tasklist.md`: the rows for STAGE, PERCH, POOL, HOSTKIT and GREEN.
- The perch report `~/Developer/otto-claude-host/otto/ops/perch/0/20261016T044011Z/report.md` and its `raw/` beside it. The run used `--fake`, since `perch.sh` refuses a run without it, although its header says stage 0 needs no worker.
- The code: `ops/bootstrap/staging.sh`, `ops/bootstrap/perch.sh`, `tests/test_staging_startup.py`, `tests/test_perch*.py`, and `src/otto/hostctl/cli.py` (`cmd_service_run` → `OwnerService`) in `~/Developer/otto-claude-host/otto` at canon/main (2cdbb96 or later). Landed since the program began: `git -C ~/Developer/otto-claude-host/otto log --first-parent --format='%h %s' 576d6f2~10..canon/main`.
- STAGE's inventory of what the live owner's composition gives that `OwnerService` doesn't (in `ops/runs/STAGE/worker.json`'s result text). The COMPOSE row places those gaps.

## Questions (PLAN.md §16, stage 0 "Boots")
1. **It starts, or says exactly why not:** does an empty staging instance start through `ottoctl install` + `service run` from canon's own code, and does a refused start name its reason (an exit code, a record)? Evidence: the report, staging.sh, `test_staging_startup.py`, and running that test file once.
2. **Status tells the truth:** while running, after a stop, and after a kill, does the status the staging Otto reports match the processes and the Store? The perch doesn't assert this: say what it would take to assert it.
3. **Nothing is left over after a stop:** processes, sockets, lock files, labs and scratch. Compare the report's census with the code paths that create them.
4. **A restart after a kill recovers:** the perch's stage 0 run doesn't kill. Is it covered elsewhere (the STAGE row's `restart_after_kill_recovers` test)? Is that test meaningful against the real start path, or does it mock it?
5. **The Store's size at rest:** measure it (the staging Store file under `labs/_staging`, read-only) and say whether the perch should record it.
6. **The staging boundary:** is it impossible for staging to touch the live owner's Store, socket or `~/.otto`? Check the paths staging.sh and the started service use against `~/.otto-clients/claude-code/lanes/claude-code/status.json` (it names the live ones).
7. **Perch honesty:** does each PASS line check what its name claims? For example, `timeline-events` passes with "0 events in the Store". Is any assertion vacuous?

For each gap, give a new perch assertion or a fix task (an outcome and a check), sized for a normal Haiku worker if it can be.

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL (unsafe to go on).
2. **Findings**, most severe first. For each:
   - what is wrong;
   - the evidence;
   - why it matters;
   - the fix, as a task or a perch assertion.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list:** anything landed that serves no current requirement, or duplicates another mechanism.
6. **Helpers:** how many you ran and what each did, one line each.

Don't pad. No finding without evidence.
