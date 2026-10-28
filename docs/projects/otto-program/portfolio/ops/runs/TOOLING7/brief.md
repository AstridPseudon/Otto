# TOOLING7

Title: The heavy queue starts jobs in arrival order (locked tickets), and the gate re-runs a new failure beside BASE before refusing
**Layer:** Otto hostctl (the bootstrap heavy pool, heavy.py) and the bootstrap gate (land.sh); POOL's capacity pool and LAND replace them later
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_heavy_lease.py tests/test_bootstrap_gate.py`
