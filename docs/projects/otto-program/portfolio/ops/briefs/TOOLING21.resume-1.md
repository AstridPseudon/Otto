# TOOLING21 resume 1

The landing gate refused commit `1fc4c7462ccd76c96c3d8ced57434b5ab8895826` for two reproducible NEW failures in `tests/test_perch_staging.py`:

- `StatusTests.test_cleanup_after_forced_mid_test_failure`
- `StatusTests.test_cleanup_after_timeout`

Both failures show the staging subprocess exiting before the cleanup scenario because its generated caller socket path exceeds macOS's 100-byte Unix socket limit. The failing path is under `/private/var/folders/.../T/perch-staging-.../_staging/home/run/c-000000000000.sock`. The gate reproduced each failure three times; BASE passed each three times. Read `${TRANSFER_ROOT}/portfolio/ops/runs/TOOLING21/.gate/pair-1-*.txt`, `pair-2-*.txt`, and `land.log`.

Fix the test setup or implementation so both forced-failure and timeout scenarios reach their intended cleanup assertions with a socket path within the limit. Preserve the task invariant: every staging owner started by a test is stopped even when the test fails or times out. Do not weaken the assertions. You may edit the task's owned files from `.brief.md`; do not touch files owned by REDS3 or PERCH2B, or anything outside this lab. Do not run `tests/test_staging_startup.py` or `tests/test_perch_staging.py` in the worker sandbox; the landing gate runs them outside the sandbox. Run the existing task check command from `.brief.md`.

Working rules: Never run `git stash` or check out another commit. Don't run `ottoctl` (including `--help`). Never wait or poll. Run tests in the foreground and give long checks a long timeout. On Codex, leave changes for the launcher to commit; do not work around the read-only `.git`. If a check fails with `sandbox_apply: Operation not permitted`, report it for the landing gate to run outside the sandbox. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

When done, leave work in the lab for the launcher to commit. Report the commit and checks run, including why the two staging test files were left for the landing gate. Don't push.
