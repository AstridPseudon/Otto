**Behavior:** A landed `worker-done` now revokes its token inside the owner-pump operation, before that operation returns to the facade waiter. The existing active-record gate refuses later calls.

**Runs:**

- Before the implementation change, the new regression failed: `check` reached landing while the `done` facade thread was held.
- After the change, the new regression and two existing worker-facade tests passed: **3 passed**.
- The specified full-file command finished with **22 passed, 8 failed**. The failures involve host restrictions: sandbox execution was denied, process census was unavailable, and launching `ps` returned `EPERM`.

**Files changed:** [product_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DONESETTLE/src/otto/hostctl/product_service.py) and [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DONESETTLE/tests/test_fleet_custody.py). The test fixture now uses the real product port, and the new regression covers the owner-pump race.

`git diff --check` passed. No other blockers.