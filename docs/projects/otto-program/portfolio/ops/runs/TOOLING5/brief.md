# TOOLING5

Title: The manager waits on one command that also wakes it for the orchestrator; workers can't self-schedule
**Layer:** bootstrap tooling (ops/bootstrap), not Otto or Herzchen
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
