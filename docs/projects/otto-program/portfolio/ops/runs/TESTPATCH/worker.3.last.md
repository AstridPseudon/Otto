The round-2 conflict markers are cleared from the files, and `git diff --check` passes. The resolved hydration code stages refreshed `task_refs` before validation and commits state only after validation succeeds. I also restored the cursor continuation check and added the second linked owner task’s lab; the fleet landing test passes.

**Focused check:** 72 passed, 4 skipped, 7 subtests passed, 11 failed. The remaining failures are environment restrictions: `sandbox-exec` is denied during OS-scope preflight, and `ps` is denied in fleet custody checks. The isolated fleet settlement test passed.

**Restored D19 coverage:** the canary uses a real historical task revision; positive hydration checks exact task and criterion refs against independent owner records; the ask test pages the assignment report stream and checks continuation without replay; and the fleet test asserts `two.txt` was not landed. No assertions were weakened, and no additional expectation changes were made beyond the existing D19 changes.

Changed files:

- [serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/src/otto/hostctl/serve.py)
- [test_hostctl_serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_hostctl_serve.py)
- [test_ask_socket_wait.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_ask_socket_wait.py)
- [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_fleet_custody.py)
- [test_execution_continuity.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/src/otto/portfolio/tests/test_execution_continuity.py)
- [test_hostctl_portfolio.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_hostctl_portfolio.py)

The working tree still reports `UU` for three files because this sandbox cannot update `.git` to mark the conflict resolutions. The launcher will need to stage those resolved files before committing.