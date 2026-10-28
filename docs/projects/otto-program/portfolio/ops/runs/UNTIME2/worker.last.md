Implemented in the lab, based on `97f5f97` (with OWNERCOMPLETION already in its history). Only the three owned test files changed.

- Admission now waits for a queued `status` response to prove the owner polled past the held admission. The regression test fails when deferral is bypassed: it reported `AssertionError: True is not false`.
- The queue test waits for a callback to complete under the shared lock while the manager remains queued, then retains the response checks.
- The heartbeat test waits for the published timestamp to advance by at least five seconds while the owner is blocked. Deadline waits and the `_status` wrapper were removed; the owner-thread operation assertion remains.

**D19 review:** In [test_execution_host_manager_turn_queue.py:171](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/UNTIME2/tests/test_execution_host_manager_turn_queue.py:171), the one-time lock probe was replaced by the completed-callback-while-queued expectation. In [test_embedded_host_heartbeat.py:98](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/UNTIME2/tests/test_embedded_host_heartbeat.py:98), the `_status` wrapper’s direct every-call assertion was removed. Landing remains held for D19’s decisions.

**Runs:** Lab check: **28 passed, 1 skipped**. The bypassed-deferral regression check produced the expected failure. Canon tests were not run; work stayed in the lab. `git diff --check` passed.

**Blocker:** D19 review remains outstanding.