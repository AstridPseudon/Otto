# PERCH0FIX: finish the proof runs (manager, 09:52Z)

Your code and tests are committed (`f54888e`, `28f1358`, `ca7469f`, `457d7af`), and the light tests pass. What's left is the proof the row asks for, and it never ran: 16 of your Bash calls were refused by the worker's command allowlist, not by the gate. Your work is good; only the command shapes were wrong. Use the forms below exactly.

## Command forms that the allowlist accepts

The allowlist matches a command's prefix. These are the only shapes it accepts:

- `git -C <lab> <git args>`, one git command per call. Not `cd <lab> && git …`.
- `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "PERCH0FIX" -- <cmd>`. Use the tilde path exactly. The absolute `${ORIGINAL_HOME}/…` path was refused.
- `/opt/homebrew/bin/python3.11 -m pytest …`, and `/opt/homebrew/bin/python3.11 …` in general.
- `bash <script>`, with the script as a file. Not `env VAR=… bash …`, not `VAR=… cmd`.

Not allowed: `cd … &&` chains, `env`, `mktemp`, `tar`, `mkdir` with chains, anything under `/tmp`, `$TMPDIR`, `sed`/`awk` pipelines that call `git show`.

## Where your scratch goes

Keep everything inside the lab, under `ops/perch/_scratch/`. Do not commit it.

- **Staging root:** `ops/perch/_scratch/staging`.
- **Staging ref:** `refs/heads/lab/PERCH0FIX` (your lab's commit, not `canon/main`).
- **Perch output:** `ops/perch/_scratch/out`.

Because `bash <script>` is the only way to set environment, write this file once and then run it:

`ops/perch/_scratch/run-perch.sh`:

```
#!/bin/bash
# The lab's own staging run: the scratch root and ref, never the shared labs/_staging.
export OTTO_STAGING_ROOT="$PWD/ops/perch/_scratch/staging"
export OTTO_STAGING_REF=refs/heads/lab/PERCH0FIX
export PERCH_OUT="$PWD/ops/perch/_scratch/out"
exec bash ops/bootstrap/perch.sh "$@"
```

Run it from the lab root as `bash ops/perch/_scratch/run-perch.sh 0 --fake`. For a seeded fault, copy it to `ops/perch/_scratch/run-fault.sh` and add `export PERCH_FAULT=<kind>` above the `exec` line. Then run `bash ops/perch/_scratch/run-fault.sh 0 --fake`.

For the canon regression run, make a detached worktree of `canon/main` inside the lab, in two separate calls:

1. `git -C <lab> worktree add --detach ops/perch/_scratch/canon canon/main`
2. Run the light tests from there with the tilde-path python. Then `git -C <lab> worktree remove ops/perch/_scratch/canon --force` when done.

## What to run, in order

1. The light tests on the lab (`tests/test_perch.py` non-staging classes, `tests/test_perch_timeline.py`), through `otto-heavy`.
2. `tests/test_perch_staging.py` through `otto-heavy`, once. These start a real staging Otto under your scratch root.
3. `bash ops/perch/_scratch/run-perch.sh 0 --fake`. It must pass with every new assertion.
4. Each `PERCH_FAULT` kind, one run each, under its own script. Report which assertions turn red. Do not change any expectation to make a run pass.
5. The same staging test file on the canon worktree (step 1 above), so the regression is shown red there.

## Rules

- **Don't change expectations further.** The two expectation changes you already committed (`28f1358`, the `staging` fault turning three assertions red) stay as they are. Report the red set for every fault as it actually runs. A D19 Opus review will look at them, and it decides them, not you.
- **Never wait.** No Monitor, no sleep loops, no background job you wait on. Foreground runs only.
- **Commit only files you own.** Never `.brief.md`, never `ops/perch/_scratch/`.
- **Report:** the commit, every run's result (red and green), the seeded-fault red sets, and anything blocked, with the exact refused command if one is.
