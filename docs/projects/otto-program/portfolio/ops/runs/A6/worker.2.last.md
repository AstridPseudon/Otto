The five stale sync-dependent callers and expectations are updated in the lab. The duplicate-registration check remains, activation replay is still verified, and detach tests use canonical DAT associations.

The brief check passed: **25 passed**. The full affected-file run completed with **27 passed, 4 skipped, 5 failed**. Those five failures stop at the local `sandbox-exec` preflight with “Operation not permitted”; the named serve test does not reach its updated document assertion. `git diff --check` is clean.

The lab is clean at **`fbc939d`**; I made no additional commit during this resume.