# Review brief: STAGE2 (opus), stage 2 "Dispatches"

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). **Opus:** you check whether it works, judged on the live data and the code. Be diligent: a claim without evidence is not a finding, and a check you didn't run is not a pass.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. Don't start a staging Otto: the run below is the evidence (its scratch Store is gone; its raw files are kept).

## Hand the legwork to helpers
Use the Agent tool with `subagent_type: "haiku-worker"`. Split the work into as many parallel helpers as it divides into: one per question, file or claim. Each helper brief is self-contained: the question, the exact paths, the command to run, and what to report. Check any claim a helper makes in the source before you rely on it.

## Read
- `PLAN.md` §1 (the end state), D14, D17, D19, D20 and §16 (the stage 2 row: "admit the canary, with the fake harness" → "only admitted, ready tasks start, in dependency order; the pool and the manager reserve hold; an unadmitted revision is refused; a killed worker frees its slot, and nothing leaks or is wrongly killed"; and its gate note: the stage passes only with no product method patched by the harness, fake-run stand-ins for presence, worker turns and completion only).
- The perch report `${TRANSFER_ROOT}/portfolio/ops/perch-reports/2/20261017T162710Z/report.md` and its `raw/` beside it. The orchestrator ran `ops/bootstrap/perch.sh 2 --fake` on canon `5b4a770` (all 16 checks PASS), from a throwaway worktree with its own staging root.
- `ops/reviews/ORACLE-ADMIT.md` (who may admit) and `ops/reviews/STAGE1.md`.
- The rows in `projects/program/tasklist.md` for the work stage 2 needed, most found by running it: ADMIT, DISPATCH, CUSTODY, COMPOSEFLEET, PERCH2, AUTODISPATCH, AUTODISPATCH2, STAGESETUP, OPERATOR-ADMIT, PERCH2B, ACTCRIT, PINCONTENT, FDLEAK, ADMITHELD, ADMITFREE, PYSTUB, DISPATCHSEEN, POLICYPIN, LANDASSESS, LANDEVIDENCE, PACKLOAD, FAKECOMPLETE (and 2, 3), COMPLETEEVIDENCE, STATUSLAUNCH, WORKERSETTLE, STAGE2C, AUTODISPATCHREC; and the gate rows TOOLING19 to TOOLING23.
- The code: `git -C ~/Developer/otto-claude-host/otto log --first-parent --format='%h %s' 85dbb13..canon/main` (stage 1's re-run was at 85dbb13), and the diffs of the rows above. Each landing's log is `ops/runs/<TASK>/land.out`; D19 decisions are `ops/reviews/D19-<TASK>.md`.

## Questions
1. **Only admitted, ready tasks start, in dependency order:** follow one launch from the pump to the worker (`src/otto/portfolio/execution_host.py`, `src/otto/hostctl/product_service.py`, `src/herzchen/fleet/dispatch.py`, `WorkAssignments.dispatch` since AUTODISPATCHREC). Is the work domain's admission gate the one that decides, on every launch path? Can any path still start an unadmitted or not-ready task?
2. **Who admits** (OPERATOR-ADMIT, ADMITHELD, ADMITFREE): only the operator, through the owner's `admit` command, after the owner's own presence check, with one presence check per admission. Can an agent admit, or make the owner admit, its own work? Does the `--fake` presence stub (`ops/bootstrap/perch_fake_presence.py`) stay out of every non-fake path?
3. **Pins and bindings by content** (PINCONTENT, POLICYPIN, LANDASSESS, WORKERSETTLE): metadata-only revisions keep a binding; a content change breaks it. Is the content comparison the same everywhere, and can a crafted metadata write make different content match? Is there a remaining exact-revision check that will bite the next metadata write?
4. **Acceptance and completion** (LANDASSESS, LANDEVIDENCE, COMPLETEEVIDENCE): the run's single policy decides acceptance; completion cites the exact managed evidence of the check that passed, verified on every completion path. Can a task be completed without verified evidence?
5. **The pool and the manager reserve**, and **a killed worker frees its slot**: check the run's raw capacity samples and the kill record; is the slot released by the owner's own recovery, not by a timeout or the harness?
6. **Nothing leaks:** descriptors (FDLEAK: the owner's facade reuse), staging owners (TOOLING21-23), labs. Does the run's census prove it, and would a long-running owner under dispatch traffic stay flat?
7. **Harness honesty** (PLAN.md §16's gate note): `ops/bootstrap/perch_stage2_owner.py` installs `install_fake_completion` (patches `_OwnerExecutorPort.call`) and `defer_fake_lab_cleanup` (patches `LabFleet.remove`); the fake Claude and its compiled launcher stand in for workers. Is each a stand-in only for what a person or a real model would do, or does one patch the product's own behaviour (the lab cleanup deferral in particular)? Does each stage-2 PASS check what its name claims?
8. **The Herzchen/Otto boundary** (PACKLOAD): Herzchen now loads its own packs without importing Astrid. Is the provenance record identical to Astrid's, and is anything left in Herzchen that imports a product above it?
9. **The fence** (PYSTUB): does the worker fence still admit exactly the pinned binaries plus their own re-exec targets, by literal path?

For each gap, give a new perch assertion or a fix task (an outcome and a check), sized for a normal worker if it can be.

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL (unsafe to go on).
2. **Findings**, most severe first. For each: what is wrong; the evidence; why it matters; the fix, as a task or a perch assertion.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list:** anything landed that serves no current requirement, or duplicates another mechanism.
6. **Helpers:** how many you ran and what each did, one line each.

Don't pad. No finding without evidence.
