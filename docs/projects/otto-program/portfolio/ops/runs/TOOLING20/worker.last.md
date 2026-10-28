Implemented D19 path coverage in [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING20/ops/bootstrap/land.sh): a LAND decision must name every changed test file using its exact path. Missing paths are reported, and longer similar paths do not count.

Added regressions confirming that an omitted path is refused and naming both paths passes. No existing test assertions changed. The SEND BACK and LAND fixtures now include the changed test path.

The requested focused check passed: **45 passed**. `git diff --check` passed. Only the two owned files were changed. No other files changed; nothing is unfinished.