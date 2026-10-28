# Resume: UNTIME2 (xhard)

**Outcome:** Apply the D19 SEND BACK restore for UNTIME2 while preserving the heartbeat state-wait and frozen-projection coverage, and the shared-lock callback regression.

**Decision:** Read `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-UNTIME2.md.sendback`. In `tests/test_embedded_host_heartbeat.py`, add a dedicated status-read thread log to `SerializedHost.__init__`, append the calling thread in its existing `capacity_holds()` fixture method, and after `service.close()` assert the log is nonempty and contains only `host.owner_thread`. Product `_status()` reads this fixture. Leave `service._status` unpatched. Preserve the state waits and frozen-projection assertions. Keep the `tests/test_execution_host_manager_turn_queue.py` regression unchanged.

**Scope:** Work in the UNTIME2 lab. Edit `tests/test_embedded_host_heartbeat.py` only. Do not touch `src/otto/hostctl/project_service.py`, `tests/test_execution_host_manager_turn_queue.py`, FAILEDFENCE-owned service/client paths, or `tests/test_runner.py` (owned by active tasks). Do not touch production/, any Store, ~/.otto, ~/.codex, or anything outside this lab.

**Check:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_embedded_host_heartbeat.py tests/test_execution_host_manager_turn_queue.py`. Run to completion and report results plus `git diff --check`. Do not alter unrelated assertions. Do not commit or push; the launcher commits on exit. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
