Fixed deferred completion handling at the manager start boundary. `HostOwnerService._start_manager` now uses `after_owner` before reading the result or updating launch state. I also routed the execution host’s socket and file IPC completion callbacks through `after_owner`, and standardized the related answer-session handling.

The real-owner regression admits a worker, starts a prepared manager while that worker is running, and verifies the manager response settles as a mapping after the worker releases capacity.

**Focused check:** `27 passed, 19 skipped` with the requested pytest command. `git diff --check` passed.

The caller audit found `execution.py:1226` as the sole production caller of `admit_execution`. I also inspected worker and external-owner starts, manager continuation, startup recovery, answer-session recovery, and `orchestrator_client`; their mapping work is behind `after_owner` or an explicit completion check. The grep audit found no remaining direct mapping-style use of an `OwnerCompletion`.

Additional file: [serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OWNERCOMPLETION/src/otto/hostctl/serve.py), because it implements the failing `start-manager` boundary.

No commit was created, per the lab instructions; current HEAD is `d5a9b35`, and the launcher will commit on exit.