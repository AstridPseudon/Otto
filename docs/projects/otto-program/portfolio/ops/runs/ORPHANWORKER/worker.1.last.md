Moved startup cleanup from `ExecutionHost` construction to `start()`, after it claims the owner file. A competing owner now fails custody acquisition without killing the live owner’s worker. Removed the early cleanup from `close()`; its remaining cleanup runs after children settle. Forced `staging.sh down` now runs the birth-checked helper and reports groups it kills.

The branch was already based on current `canon/main`; rebasing was a no-op. Changes are in [claude_cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ORPHANWORKER/src/otto/agents/claude_cli.py), [execution_host.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ORPHANWORKER/src/otto/portfolio/execution_host.py), [staging.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ORPHANWORKER/ops/bootstrap/staging.sh), and these test files:

- [test_worker_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ORPHANWORKER/tests/test_worker_custody.py)
- [test_perch.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ORPHANWORKER/tests/test_perch.py)

The focused permitted run passed: **65 passed**. I excluded staging-owner tests as instructed, the census test blocked by the sandbox’s `ps` restriction, and two existing stage-2 unit tests that fail because `perch_stage2_owner` lacks `defer_fake_lab_cleanup`. `bash -n` and `git diff --check` passed. No commit was made.