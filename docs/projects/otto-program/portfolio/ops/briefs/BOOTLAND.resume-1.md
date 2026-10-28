# Resume: BOOTLAND (xhard)

**Decision:** Read `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-BOOTLAND.md.sendback` and apply only its Restore section.

**Restore:** In `tests/test_bootstrap_gate.py`, replace only the two obsolete `land.lock` disappearance assertions with checks that the persistent lock is a regular file and can be independently acquired using nonblocking exclusive `fcntl.lockf`, then released. Preserve the existing publication, cleanup, signal-result and unchanged-main assertions. Replace the two newly added 600-second sleeps with deterministic pipe/FIFO synchronization while retaining readiness signaling and crash/recovery assertions. Present the resulting assertion diff and gate output in your report.

**Scope:** Work only in the BOOTLAND lab. Edit `tests/test_bootstrap_gate.py` only unless a directly required fixture update is necessary; explain any addition. Preserve the existing live-exclusion and subsequent-success assertions. Do not touch other running-task files, `production/`, Stores, `~/.otto`, `~/.codex`, or files outside the lab.

**Check:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`; run to completion and report results plus `git diff --check`. Do not commit or push; the launcher commits on exit. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
