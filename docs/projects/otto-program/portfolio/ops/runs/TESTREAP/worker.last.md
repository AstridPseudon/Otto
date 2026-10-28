Updated [tests/test_runner.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTREAP/tests/test_runner.py) with teardown cleanup for recorded gated-helper PIDs, parent-exit checks in the waiter loops, and two regressions covering assertion failure and parent disappearance. No other test files needed changes; the other helper waits I found are bounded and have cleanup paths.

The two regressions passed: **2 passed**. Both requested full-file runs completed separately, and both reported **13 passed, 4 failed**. The failures were the existing sleeper cleanup, orphan custody status, and nested-run admission checks. `git diff --check` passed.

No commit was created; the lab is at `ec6bacf44ec0f370317a36353e950f44b918865f` with changes left for the launcher.