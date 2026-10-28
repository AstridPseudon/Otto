# Review brief: STAGE1 (opus), stage 1 "Holds plans"

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). **Opus:** you check whether it works, judged on the live data and the code. Be diligent: a claim without evidence is not a finding, and a check you didn't run is not a pass.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. The staging Otto under `~/Developer/otto-claude-host/labs/_staging` may be read and queried, but don't start, stop or kill it: landings restart it. Your final message is saved as `ops/reviews/STAGE1.md`.

## Hand the legwork to helpers
Use the Agent tool with `subagent_type: "haiku-worker"`. Split the work into as many parallel helpers as it divides into: one per question, file or claim. Each helper brief is self-contained: the question, the exact paths, the command to run, and what to report (file:line, output tails). You keep the judgment, and you look at the evidence a helper cites before you rely on it. Two workers and the manager share the machine, so run at most 4 helpers at once, and have them run single test files, never a whole suite.

## Read
- `PLAN.md` §1 (the end state), D14, D17, D19, D20 and §16 (the stage 1 row: "save the canary from a file; show; edit; save again; a save from a stale base" → "tasks are typed records; nothing runs; edits make revisions; the stale save is refused; Store growth per save"); `RUNBOOK.md` §4 and §6.
- `projects/program/tasklist.md`: the rows for A1, TYPE, A2, PERCH0FIX, PERCH1, and A3/A3FIX (A3's `show` landed outside stage 1).
- The perch report `~/Developer/otto-claude-host/otto/ops/perch/1/20261016T113140Z/report.md` and its raw data beside it (run by the orchestrator at canon `c126587`). Also the gate's runs in `ops/perch/1/` and `ops/perch/0/`.
- The stage 0 review `ops/reviews/STAGE0.md` and what PERCH0FIX did with its findings.
- The code landed since stage 0's run (`2cdbb96`): `git -C ~/Developer/otto-claude-host/otto log --first-parent --format='%h %s' 2cdbb96..canon/main`, and the diffs of TYPE (`4f27fd4`), A2 (`4b3d9d7`), PERCH0FIX (`1ab1401`), PERCH1 (`89f2005`). The landing logs are `ops/runs/<TASK>/land.log` in the program folder, and the workers' results `ops/runs/<TASK>/worker*.json`.

## Questions
1. **Tasks are typed records:** does a saved task become one typed record with its criteria, route, size and deps, readable back exactly as saved? Compare a save's input with what the staging Store holds. Is there a second copy of a task anywhere (a table, a file, a generated view)?
2. **Nothing runs:** after a save, can anything dispatch, open a lab or start a worker? Check the code paths, not just the perch's flags.
3. **Edits make revisions:** an edit moves the project to a later revision and the old revision stays readable. Is a revision an exact, immutable snapshot? Can two saves interleave and lose one (the stale-base check against a concurrent writer: A3's report names a race between the stale pre-check and `finish`)?
4. **The stale save is refused** with the base it lost to and a diff. Is the refusal a record an agent can act on?
5. **Store growth per save:** the numbers, and what grows that needn't.
6. **The socket route** (PERCH1 added `work.project.save` to the owner socket's allowlist, `src/otto/hostctl/service.py` around 352-370): what else does that allowlist now admit, and is each entry needed? Who can call it?
7. **Perch honesty:** does each stage 1 PASS check what its name claims? The perch saved one canary task ("4 events and 1 tasks in the Store"): is one task enough for "tasks are typed records" and "edits make revisions"? PERCH1's first landing failed `tasks-are-typed-records` and the assertion (not the code) was changed from `type` to `kind`: is the fixed assertion still meaningful?
8. **The perch harness:** `perch.sh` refuses every stage but 0 without `--fake` (`ops/bootstrap/perch.sh:385-387`), though stage 1 runs no worker; the orchestrator ran it with `--fake`. Is the flag inert for stage 1, as it should be?
9. **The landing gate since stage 0:** the gate passes failures already red on BASE as pre-existing, so reds accumulated on canon (row REDS). Which tests are red on canon now, and does any touch stage 1's code? Did any landing since stage 0 weaken an assertion without a D19 decision? Did the D19 SEND BACK fixes (PERCH0FIX `d4f4890`, UNTIME `2d91fba`) match what the reviews asked for?

For each gap, give a new perch assertion or a fix task (an outcome and a check), sized for a normal Haiku worker if it can be.

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL (unsafe to go on).
2. **Findings**, most severe first. For each: what is wrong; the evidence; why it matters; the fix, as a task or a perch assertion.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list:** anything landed that serves no current requirement, or duplicates another mechanism.
6. **Helpers:** how many you ran and what each did, one line each.

Don't pad. No finding without evidence. Don't read `ops/reviews/ASTRA1.md` (the paired review stays independent).
