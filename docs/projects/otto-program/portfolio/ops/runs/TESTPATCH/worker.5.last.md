Applied the latest D19 restore in `tests/test_fleet_custody.py`. The fixture captures the expected admitted revision before creating the stamp, and the test compares against that independent value. The facade test now sends `check` and `done` requests naming the second real task, asserts both return `bad_args`, and confirms the project line remains at `base`; the successful calls and both artifact-isolation assertions remain.

The lab is based on `canon/main` (`HEAD` `c3ba1ee`, canon `3d91a35`). No rebase conflict was present in the current state, and the task files contain no conflict markers.

- Full focused check completed: **80 passed, 4 skipped, 11 failed**. The failures were sandbox restrictions on manager execution, worker execution, and process inspection.
- `git diff --check` passed.
- Only `tests/test_fleet_custody.py` is modified. There are no staged changes; I left the work for the launcher to commit.