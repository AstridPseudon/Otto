Implemented SAVEFIX on `lab/SAVEFIX`. First saves now validate and commit the project, tasks, event and receipt in one transaction. Saved criteria appear in `otto show`; stale and busy refusals include recovery guidance; retained-task cycle checks and `otto.plan` key removal are covered. Batch mappings now live in event effects, and the project payload no longer stores `batch_history` or `last_batch`.

The updated regression tests were **red on a `canon/main` snapshot**: 7 failed, 13 passed, 9 subtests. On the lab, the requested check passed: **27 passed, 10 subtests**. `test_revisions.py` passed (12), and `test_herzchen_boundary.py` passed (4). `git diff --check` is clean.

Per D19, I changed only the existing assertion at [test_revisions.py:137](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/SAVEFIX/tests/test_revisions.py:137) to verify the mapping in the applied event.

The changes are left uncommitted in the lab for the launcher. I did not run a broader test sweep.