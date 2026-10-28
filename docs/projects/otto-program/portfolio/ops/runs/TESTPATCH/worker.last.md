Implemented the hydration, ask authorization, readiness, override, and real facade changes in the lab. **The fleet fixture still uses synthetic owner records**, so the owner-backed fleet conversion is incomplete.

**Checks**

- The new canary failed on unchanged product code with `AssertionError: RuntimeError not raised`, demonstrating that a current T2-only criterion was accepted as `T1/C01`.
- The focused converted tests passed: **8 passed**; a later fleet and canary spot check passed: **3 passed**.
- The full requested command finished with **65 passed, 12 failed, 4 skipped, 7 subtests passed**. Failures included sandbox restrictions (`sandbox-exec` returned “Operation not permitted” and process checks could not launch `ps`).

**D19 assertion changes**

- [test_hostctl_serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_hostctl_serve.py:203): missing-scope hydration now expects refusal; it also checks that refusal preserves task pins.
- [test_ask_socket_wait.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_ask_socket_wait.py:114): replaces the invented cursor value with the real cursor result.
- [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_fleet_custody.py:247): compares task record refs instead of Python object identity.

Removed the hydration mocks, ask authorization/decision/session/cursor patches, readiness patches, `_compose_setup` patch, and fleet/facade/owner-port class patches. The fleet helper now starts real `LabFleet` and `FacadeServer`, but still supplies synthetic owner, task, assignment, and dispatch records; this remains a blocker against the brief’s real-owner fleet requirement.

No files outside the listed ownership set were changed. No staging-owner tests were run, and no commit or push was made.