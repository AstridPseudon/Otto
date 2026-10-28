# D19 request: PINALL

The landing gate found changed existing expectations in `tests/test_capacity_holds.py`, `tests/test_capacity_pool.py`, and `tests/test_claude_manager_admission.py`. Please decide LAND or SEND BACK.

PINALL changes process-group custody so every native process, including a Claude initializer, is pinned before it receives input. A failed pin terminates the child before input; a later failed write preserves an earlier pin. Empty recorded groups are treated as gone even if the leader PID is reused, while any live group member keeps capacity held. The worker reports the real-owner regression red on canon (`unknown` instead of `failed`) and passing after the fix. Its focused suite passed 78 tests with 1 sandbox-blocked fence test deselected and 10 subtests passing; the fence test was blocked by `sandbox-exec: sandbox_apply: Operation not permitted` in the worker sandbox. `git diff --check` passed.
