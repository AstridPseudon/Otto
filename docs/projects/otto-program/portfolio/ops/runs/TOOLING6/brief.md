# TOOLING6

Title: Heavy jobs backfill free slots without delaying the head; the gate runs the check and never reports a stopped run as landed
**Layer:** Otto hostctl (the bootstrap heavy pool, heavy.py); POOL's capacity pool replaces it later
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_heavy_lease.py tests/test_bootstrap_gate.py`
