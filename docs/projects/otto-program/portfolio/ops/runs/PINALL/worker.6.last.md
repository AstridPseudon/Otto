The integration regression came from `ExecutionHost.start()` launching `sysctl` to read macOS boot identity. That process tripped the tests’ provider-launch guard before a provider started. [execution_host.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PINALL/src/otto/portfolio/execution_host.py) now reads the boot value in-process and compares it with legacy stored values. The process-start custody check remains in place. The D19 wait and `signal.pause()` restore was already present.

- **Before the fix:** 8 failed, 10 passed in `test_manager_preprovider_disposition.py`. **After:** 18 passed, 42 subtests passed.
- **Original brief check:** 83 passed, 10 subtests passed, 1 failed. The remaining failure is `test_child_processes_run_and_inherit_the_write_fence`: this sandbox rejects its subprocess preflight with `sandbox_apply: Operation not permitted`. It needs the outside check-run.
- `git diff --check`: passed. Only `execution_host.py` changed; `canon/main` was already an ancestor of the lab’s HEAD.

Sub-agent `integration_diag` diagnosed the failure, made the edit, and ran both suites. I caught a macOS timeval field-width error during review; the agent corrected it before the final runs.

The change is **uncommitted** for the launcher. Codex’s sandbox keeps `.git` read-only, so the remaining work is the outside check and launcher commit.