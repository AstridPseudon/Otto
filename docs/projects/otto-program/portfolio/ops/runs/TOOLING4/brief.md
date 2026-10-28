# Brief: TOOLING4

Title: Workers run tests without an env prefix (pytest pythonpath)

**Layer:** Otto bootstrap tooling.

Check command: `env -u PYTHONPATH /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_herzchen_boundary.py tests/test_capacity_holds.py tests/test_bootstrap_gate.py`
