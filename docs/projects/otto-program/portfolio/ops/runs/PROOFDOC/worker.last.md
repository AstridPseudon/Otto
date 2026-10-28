Updated [RUNBOOK.md](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROOFDOC/RUNBOOK.md) to document the `stages-gated` default and selection, and to distinguish fake `stage-run` diagnostics from the required real-model review and real-worker evidence.

Added a contract test in [test_bootstrap_gate.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROOFDOC/tests/test_bootstrap_gate.py:535) that checks the runbook against `land.sh` and `perch.sh`.

**Verification:** the requested test command passed: **55 passed**. `git diff --check` passed.

The referenced `ops/brief-template.md` was absent from this checkout; I followed the working rules in the provided brief. No commit was made.