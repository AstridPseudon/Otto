Updated the setup policy fixture to include `pool_id: "demo-review-pool"` and kept it local to the registration/show test. The shared run fixture no longer injects an invalid assessment policy into compose tests. The existing flow still preserves the bundle policy in `project status`.

**Checks**

- `tests/test_compose.py`: 19 passed.
- `tests/test_hostctl_serve.py`: 11 passed, 4 skipped, 3 failed at OS sandbox preflight (`sandbox_apply: Operation not permitted`); no pool-identity refusal.
- `tests/test_hostctl_cli.py`: 13 passed, 2 subtests passed, 3 failed: two sandbox preflights and a history-import replay assertion.
- `tests/test_hostctl_bundle.py`: 19 passed.
- `tests/test_staging_startup.py`: 3 passed, 6 failed; startup subprocesses timed out after 300 seconds following the `tree at ...` message.
- Combined brief check: 35 passed, 2 subtests passed, 9 failed from those same CLI and staging issues.
- `git diff --check`: passed.

Only `tests/test_hostctl_cli.py` is modified in this resume, within the brief’s owned files. No files outside the owned list were changed. Current lab HEAD is `46707c8620e7315da74672c9e38a8fc3e913c960`; changes remain uncommitted for the launcher.