The lab was already based directly on `canon/main` at `8edc104a`; `git rebase canon/main` reported it was up to date. I restored support for deliberate class-declared owner errors while keeping generic instance `code`/`message` fields private in [facade.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/src/herzchen/fleet/tools/facade.py:254). No tests or PINALL-owned files were changed.

- The two facade regressions passed: **2 passed**.
- `tests/test_tools.py`: **33 passed, 1 failed**. The remaining sandbox test is blocked because `sandbox-exec` returns “Operation not permitted.” The private `TMPDIR` census found **0 matching folders before and after**.
- `tests/test_fleet_custody.py`: **22 passed, 8 failed**. Census-dependent tests cannot run here because the sandbox denies `ps`; the cleanup-latch test is among them.
- `git diff --check`: passed.

I could not commit: Git cannot create `index.lock` because the worktree metadata is outside the writable lab root. The facade fix remains uncommitted.