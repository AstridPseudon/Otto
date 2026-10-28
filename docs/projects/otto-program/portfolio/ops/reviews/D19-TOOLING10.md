# D19-TOOLING10: orchestrator decision (no Opus call)

1. **Verdict: LAND.**
2. **What changed:** TOOLING9's own `test_staging_runs_the_tested_commits_scripts` asserted that the gate calls `staging.sh restart` and then `perch.sh all`, with `OTTO_COMMIT` set. It becomes `test_staging_runs_the_tested_commit`, where the perch report names the tested sha and is kept in the main checkout, plus `test_staging_on_another_commit_is_refused`.
3. **Why the expectation itself changes:** the STAGE0 review (F1, verified by the orchestrator in `ops/runs/EVWIRE/.gate/staging.log`, "sha 2cdbb96" against the tested 2a8c21c) showed the old expectation enshrined the bug: `OTTO_COMMIT` is read by nothing. The separate restart is redundant, since perch restarts staging itself (the review's delete list).
4. **Why the orchestrator decides it:** these are the orchestrator's own tooling and test from an hour earlier. Logged in `ops/STATUS.log`.
