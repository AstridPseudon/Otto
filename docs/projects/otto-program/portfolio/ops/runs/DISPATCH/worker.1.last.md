**The launch gate is implemented, but DISPATCH is not complete.** The reusable dispatcher and owner token binding are in the earlier commit, `4d51987`. This continuation is uncommitted in `lab/DISPATCH` for the launcher to commit; I did not push.

[ExecutionApplication.start()](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISPATCH/src/otto/portfolio/execution.py:1203) now reconciles an authorized assignment change before host admission. Direct, hosted, retry, and resume launches share the gated entry, with a final admission and dependency recheck immediately before provider invocation. Worker Due evidence records the admitted revision and a readiness digest. This supersedes the direct `return self._start(...)` path that launched without the gate. The serialized-reader handling is in [execution_operations.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISPATCH/src/otto/portfolio/execution_operations.py:1226). The [capacity fixtures](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISPATCH/tests/test_capacity_pool.py) now carry real admission and assignment context. No existing assertion changed, and no D19 expectation change is needed.

| Selector | Canon red | Lab green |
| --- | --- | --- |
| `unadmitted_never_dispatches_any_path` | Queued-host probe launched `provider` | Passed, including fresh/retry/resume |
| `blocked_dep_waits` | Queued-host probe launched `provider` | Passed, including fresh/retry/resume |
| `gate_dep_waits` | Queued-host probe launched `provider` | Passed, including fresh/retry/resume |
| `manager_not_woken_for_routine` | Dispatcher module absent at collection | Passed |
| `launch_carries_assignment_token` | Dispatcher module absent at collection | Passed, including fresh/retry/resume |
| `worker_done_reaches_its_own_assignment` | Test module could not collect against canon’s absent API | Passed |

The three canon behavioral probes exercised the queued-host route once each; the other canon reds were collection failures, not behavioral proofs. All six lab selectors ran green: **17 passed**. The application and capacity tests passed: **87 passed, 15 subtests passed**. The exact requested command ended **77 passed, 7 failed**; all seven failures are in `test_fleet_custody.py`, where this sandbox denies `ps` with `Operation not permitted`. The landing gate needs to run those outside this sandbox.

Luna sub-agents: `readiness`, `dispatch`, and `owner` produced the earlier committed modules and focused tests; I reviewed their work. `execution_entry` closed the application path; I had it correct the serialized-reader handling and a reconciliation-order bug found by an existing test. `fixtures_red` added fixture context and canon probes; I had it preserve the synthetic project scopes. `composition` audited the production owner path without editing it.

**Owner composition remains unresolved.** [product_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISPATCH/src/otto/hostctl/product_service.py:327) constructs project-worktree workers, but no `LabFleet`, `LandingService`, result store, or assignment-to-lab/task resolver. [serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISPATCH/src/otto/hostctl/serve.py:234) does not supply the `worker_mcp` grant accepted by the adapter. I made no `hostctl` or `install/controller` composition edits because a token-bound `done` or `check` cannot be wired to a real landing assignment from the current objects.

Should this product worker route acquire a per-assignment `LabFleet` and `LandingService` lifecycle? If so, which owner record supplies its `lab_name`, `task_id`, line ref, and sealed result store?