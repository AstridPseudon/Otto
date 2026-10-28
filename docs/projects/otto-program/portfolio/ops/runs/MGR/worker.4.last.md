Fixed manager occurrence selection in [manager_journey_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MGR/src/otto/portfolio/manager_journey_service.py). It now keeps a live same-assignment continuation, prefers a newer schedule pinned to the current assignment over settled stale history, and rejects stale uncertain history before falling back.

All four refused-landing regressions pass, along with the adopted-head continuation regression: **5 passed**. `git diff --check` passes. No OPERATOR-ADMIT files or test assertions were changed.

The brief’s exact focused command still fails during collection because `test_manager_consumption.py` has a relative import without a package context. The importlib-mode run completed with **118 passed, 19 skipped, 6 failed**. Those six failures are in worker transport/workspace fixture and advisor allowance tests, outside this fix. Some manager service integration tests skip because their owner-service fixture is unavailable. The supplied `ops/runs/MGR/land.log` was not present in the lab; I ran the named regressions directly.

**D19 disclosure retained:** `tests/test_host_neutral_defaults.py:160` changed the assertion from requiring `Documents/Codex` to forbidding it, to remove the hard-coded host path while preserving host-selection coverage.

The fix is uncommitted for the launcher. Head remains `78f2087`; only `manager_journey_service.py` is modified in this resume.