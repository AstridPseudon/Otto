# TOOLING10

Title: Staging runs the commit being landed, and its perch reports outlive the lab (STAGE0 F1, F6)
**Layer:** Otto bootstrap tooling (ops/bootstrap/land.sh)
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
