# Brief: TOOLING3 (normal, orchestrator tooling)

Title: The landing gate in land.sh; xhard workers get the haiku-worker sub-agent

**Outcome:** land.sh runs RUNBOOK §4's gate (sweep twice against a canon baseline, staging hook, placement, D19, remote check, push) and ends with a LAND RESULT line; run-task.sh gives xhard leads the haiku-worker sub-agent.

**Layer:** Otto bootstrap tooling (retired by DELETE).

Check command: `PYTHONPATH=src:tests ~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "TOOLING3 check" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
