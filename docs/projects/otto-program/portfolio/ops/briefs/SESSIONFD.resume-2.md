# SESSIONFD resume 2

Continue the existing SESSIONFD lab from the current canon base. The landing was terminated by the manager after confirmed new failures; use `ops/runs/SESSIONFD/land.log` and the gate outputs as the failure report.

Fix all confirmed new regressions in `tests/test_execution_application.py` (two advisor failures), `tests/test_hostctl_serve.py` (`fresh_project_view`), and `tests/test_otto_open_release.py` (two failures). Also fix the severe slowdown in `tests/test_root_direction_client.py` (the gate took about 23 minutes per run; comparable recent landings took about 2 seconds). Preserve SESSIONFD's descriptor/thread/temp-dir cleanup invariant and do not weaken tests.

Run focused checks for the affected tests, including `tests/test_root_direction_client.py`. Report the results and leave the lab ready for an outside check-run. The manager will require a passing outside check-run covering these three files plus `tests/test_root_direction_client.py` before requesting another landing.

Do not edit files owned by any concurrently running worker. Follow the existing SESSIONFD brief and all Codex working rules.
