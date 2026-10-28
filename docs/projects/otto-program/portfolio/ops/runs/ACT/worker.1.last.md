Implemented ACT in `labs/ACT` and left the changes for the launcher to commit. Activation now retains one queued lane request while shared execution custody is active. Once custody clears, it attaches the new project view to the existing host and router; the running project’s view is preserved. The retired mechanism is the closed-custody attachment refusal in [project_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ACT/src/otto/hostctl/project_service.py).

The exact caller paths identified before editing were [service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ACT/src/otto/hostctl/service.py), [product_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ACT/src/otto/hostctl/product_service.py), and [project_services.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ACT/src/otto/portfolio/project_services.py). Only those four source files and [test_act_activation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ACT/tests/test_act_activation.py) changed.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py`

- On `canon/main`, the focused regression run was red: **3 failed**.
- Final named run with `tests/test_act_activation.py tests/test_hostctl_service_routing.py`: **10 passed**. The embedded heartbeat file also passed: **3 passed**. `git diff --check` passed.
- Product integration remains unverified locally: existing socket-based tests hit sandbox `AF_UNIX socket.bind` `EPERM`. `tests/test_hostctl_project_service.py` reached **3 passed, 2 failed** for that reason; the compose and staging runs were interrupted after the same failure appeared. The landing gate needs to run them outside this sandbox.

Luna sub-agent `/root/act_impl` implemented the source changes and regressions. I reviewed its diff and directed corrections for replay, blocked activation, live host configuration, cleanup, and test coverage. An early discarded integration test invoked a fixture’s `_ottoctl`; I removed it. The final checks do not invoke `ottoctl`.

**Commit:** none here, as required by the Codex sandbox. Base HEAD is `2a1267df9663a19d8d62e47f9f7019e104da91d7`; no push was made.