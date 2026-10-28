# ACT: verify the socket integration after TOOLING12

The implementation is complete in this lab. TOOLING12 has landed and enables the Unix socket tests that were blocked by sandbox `EPERM` on your prior run.

Run the named check files below, including `tests/test_hostctl_project_service.py` and `tests/test_existing_project_orchestration.py`, then report the result and any remaining environment failures. Keep the current implementation; do not broaden scope.

If you delegate, every sub-agent must be started with `spawn_agent` and `model: "gpt-6-luna"`.

`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_hostctl_service_routing.py tests/test_embedded_host_heartbeat.py tests/test_hostctl_project_service.py tests/test_existing_project_orchestration.py`
