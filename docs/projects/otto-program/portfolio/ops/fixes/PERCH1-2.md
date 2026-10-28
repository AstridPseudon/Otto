# PERCH1: the landing gate refused it (manager, 11:04Z)

Your commit 46149ac is refused by the landing gate. `perch.sh all --fake` fails on staging, on one assertion:

    FAIL tasks-are-typed-records          task A is not a typed ref (authority, type, id)

The other stage 1 assertions pass on staging (`portfolio-admitted-before-saves`, `nothing-runs`, `edit-makes-revision`, `stale-save-refused`, `store-growth-per-save`). The log is `ops/runs/PERCH1/.gate/staging.log`, and the stage 1 report is at `ops/perch/1/20261016T110322Z/report.md` under `~/Developer/otto-claude-host/otto/`.

Your own check passes, so your fixture doesn't match what staging actually stores. Find out which one is wrong:
- Read what the save writes for task A on staging (the report's raw data for the create, not your fixture), and what a typed ref looks like in `src/herzchen/domains/work/` (the `(authority, type, id)` shape).
- If the save writes an untyped ref, the save is wrong. Fix it in the save path (the product, within the files you may already change) and say so.
- If the assertion reads the wrong field, fix the assertion and say which field and why.
- Either way, make your seeded fault for this assertion turn it red on its own, and keep the other four assertions as they are.

Re-run the check command, then run the staging gate yourself the way land.sh does, `ops/bootstrap/perch.sh 1 --fake`, from the lab (not the live machine). Report whether it passes on staging.

Commit to `lab/PERCH1`. Report the commit, the cause, and the red-then-green runs.
