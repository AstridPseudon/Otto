Preserved PERCH2C commit `793498e` on `canon/main` at `b62b3ea`; rebase reported up to date.

- Added `.perch-*.pid` to the canary [`.gitignore`](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C/ops/bootstrap/canary/toy/.gitignore). `make_canon` copies it before the first commit.
- Added two Git behavior tests in [test_perch.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C/tests/test_perch.py): canon’s `git status --porcelain` stays empty with the manager marker present, and neither the worker lab commit nor its landed commit contains the worker marker.

The two focused tests passed. The owner-free perch selection passed: **58 passed, 6 deselected, 63 subtests**. `git diff --check` passed. I did not start an owner, run stage 2, commit, or land PERCH2C. The landing hold remains in force for the Orchestrator’s rerun.