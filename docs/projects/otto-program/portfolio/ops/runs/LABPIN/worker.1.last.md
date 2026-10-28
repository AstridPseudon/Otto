Implemented the entire D19 Restore in [tests/test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LABPIN/tests/test_fleet_custody.py). The five waits and joins are unconditional; the timeout branch, deadline assertion, and redundant liveness assertions are removed. The required custody and recovery assertions remain. No other file changed.

The full check completed: **26 passed, 8 failed**. All eight failures involve sandbox restrictions on `sandbox-exec`, `ps`, or process census; they remain for the landing gate outside the worker sandbox. `git diff --check` passed.

One Luna sub-agent made the edit and ran the check. I reviewed the diff and made no corrections. The change is uncommitted for the launcher.