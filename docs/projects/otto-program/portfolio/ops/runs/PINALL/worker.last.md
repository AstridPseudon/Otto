PINALL is implemented in the lab and left uncommitted for the launcher. The base commit is `b635c93`.

The new real-owner regression was **red on canon** (`unknown` instead of `failed`) and passes after the fix. The final green check, excluding the environment-blocked macOS fence test, reports **78 passed, 1 deselected, 10 subtests passed**. `git diff --check` passes.

The fix removes the initializer pin exclusion, swallowed pin failures, and leader-PID reuse branch. It records initializers before input, preserves an existing pin when a later write fails, and keeps capacity held while a recorded group is live. The additional implementation file is [custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PINALL/src/herzchen/fleet/custody.py), where owned-group stop and empty-group proof belong in Herzchen.

**Check blocker:** The exact requested command has one failure: macOS rejects the existing `sandbox-exec` fence preflight with `sandbox_apply: Operation not permitted`. The additional fleet custody suite also encounters this sandbox’s denied `ps` access.