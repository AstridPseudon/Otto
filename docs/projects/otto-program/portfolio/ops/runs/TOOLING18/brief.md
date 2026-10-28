# Brief: TOOLING18 (normal, 0.1 focused days), done by the orchestrator

**Title:** The gate runs only the stages that have passed

**Outcome:** The gate ran `perch.sh all --fake` at every landing, so a stage still being built refused every landing. On 17 Oct, PERCH2's stage 2 canary (a scenario that can't run yet) refused PERCH2 itself. The gate now runs each stage listed in `$OPS_DIR/stages-gated` (default "0 1"); the orchestrator adds a stage once it has passed its run and review.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
