The current HEAD already contains the fix in **`7bce158`**. The regression came from **`4f12ff4`**, which preferred the worker’s saved historical `manager_schedule_id` for synchronization. `7bce158` restores selection through `_current_manager_schedule()`, so stale, foreign, and mismatched-generation records are rejected before synchronization or worker start, while valid current-manager selection is preserved.

Checks passed:

- `tests/test_retained_worker_current_manager_selector.py`: 3 passed, 7 subtests passed.
- `tests/test_manager_service_continuation.py`: 45 passed, 5 subtests passed.
- `git diff --check` passed.

The worktree is clean. I made no additional edits in this resume; the fix is already committed at HEAD.