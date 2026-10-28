The lab was already based directly on `canon/main` at `8edc104`; `git rebase canon/main` reported it up to date. Git also reported it could not create rebase locks in the linked worktree metadata.

The reproduced regression failure came from the fixture omitting `_active_due`, which `OwnerFleetRegistry.__init__` initializes and the merged implementation now reads. I added that state to the fixture; no product methods or assertions were changed.

- Focused regression: **passed** (`1 passed`).
- Required `tests/test_tools.py` check: **29 passed, 1 failed**. The remaining failure is the macOS sandbox test, which reports `sandbox_apply: Operation not permitted`.
- Changed file: [tests/test_tools.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MCPPATH/tests/test_tools.py:672).
- **Commit blocked:** Git could not create `.git/worktrees/MCPPATH/index.lock` because the linked metadata is outside the writable lab. The one-line fixture change remains uncommitted for the launcher.