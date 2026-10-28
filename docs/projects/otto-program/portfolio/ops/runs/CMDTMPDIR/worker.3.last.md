The lab is already based on `canon/main` at `3d91a35`; `git rebase canon/main` reported it was up to date.

The reported admission retry failure did not reproduce: `tests/test_native_resume_trace.py` passed (**4 passed, 5 subtests passed**), and the delayed-message test passed **20/20** repeated runs. The culprit note points to the command facade, but I found no connection to this test’s local trace-reader path, so I made no speculative product change.

`tests/test_fleet_custody.py` completed with **22 passed, 8 failed**. The cleanup-latch test and other census-dependent failures occur because this sandbox denies `ps`; sandbox tests also fail with “Operation not permitted.” `git diff --check` passed, and the worktree is clean. No new changes are available for the launcher to commit.