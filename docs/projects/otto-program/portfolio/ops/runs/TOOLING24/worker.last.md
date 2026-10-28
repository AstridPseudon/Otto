Updated [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING24/ops/bootstrap/land.sh) to scan changed files under `ops/` and select tests that name them by filename or Python module name. Selected files keep the gate’s isolated, twice-per-file execution.

Added a doctored landing regression in [test_bootstrap_gate.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING24/tests/test_bootstrap_gate.py): it changes `ops/bootstrap/perch_stage2_owner.py`, selects the baseline `tests/test_perch.py`, and verifies that file is the sole pytest target on both runs.

**Check:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py` — 51 passed. `git diff --check` passed.

**Files changed:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`. No other files changed; `tests/test_perch.py` remains unchanged. No commit created, per instructions; current HEAD is `ac02366`.