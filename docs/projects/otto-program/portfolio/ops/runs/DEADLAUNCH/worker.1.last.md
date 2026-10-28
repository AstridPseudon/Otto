The three reported landing cases reproduced, each failing at the stale `app.assign_and_start` call. I updated it to use `start_worker(app, request)`, which follows the retained `assign_worker`/`start` contract. Assertions are unchanged.

**Checks:** `tests/test_landing.py` passed (22 tests); the requested focused command passed (93 tests, 16 subtests). `git grep -n -w` found no deleted names in `src`, `tests`, or `ops`.

The lab was already based on `canon/main` and Git reported it up to date. The rebase attempt also reported it could not create temporary Git metadata locks outside the writable lab directory.

**Commit blocked:** `git add` could not create the worktree index lock because Git metadata is outside the sandbox’s writable roots. The worktree has one uncommitted change: `tests/test_landing.py`. No commit was created.