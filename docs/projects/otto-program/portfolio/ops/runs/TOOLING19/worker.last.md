Implemented the landing gate fix. Pytest now continues collection for both the task check and sweep. The check refuses `no tests ran`, `Interrupted:`, or collection-error output without a test outcome.

Added regressions for a pre-existing collection error alongside a passing test, and for all selected files failing collection. The scratch harness now uses pytest for its default check.

**Verification:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py` — **43 passed**. `git diff --check` passed.

Only [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING19/ops/bootstrap/land.sh) and [test_bootstrap_gate.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING19/tests/test_bootstrap_gate.py) changed. No commit or push was made. `ops/brief-template.md` was absent; I followed the working rules in your brief.