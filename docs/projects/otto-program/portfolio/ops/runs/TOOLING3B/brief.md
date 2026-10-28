# Brief: TOOLING3B

Title: Gate scratch and baseline cache stay out of the synced documents

**Layer:** Otto bootstrap tooling (retired by DELETE).

Check command: `PYTHONPATH=src:tests ~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "TOOLING3B check" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
