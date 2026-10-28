Updated [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING25/ops/bootstrap/land.sh) to use only the command inside the first pair of backticks and refuse angle bracket placeholders with a brief line number and “fill it in” message before the gate starts.

Added focused landing cases in [test_bootstrap_gate.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING25/tests/test_bootstrap_gate.py). No other files changed.

The requested check completed: **53 passed**. `git diff --check` also passed.