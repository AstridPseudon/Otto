I removed all remaining merge markers from the six task files. The rebase alternatives are resolved in the working files, and the full test command now collects and runs.

- In hydration, I kept the real historical task ref and verified its content matches the current revision. The canary still refuses the missing T1 scope; the positive case checks exact task and criterion refs from owner records.
- In fleet custody, I kept the linked T2 owner task and its prepared lab, with the restored `two.txt` non-landing assertion.
- In the ask test, I removed the duplicate continuation block and kept the real filtered `EventCursorReader.page` continuation and no-replay checks.

**Checks:** the four restored regression tests passed. The full required check completed with 72 passed, 4 skipped, 7 subtests passed, and 11 failures caused by sandbox restrictions: `sandbox-exec` is denied, and `ps` is denied in process-custody checks. `git diff --check` passed, and marker search returned no matches.

Changed in this resume: [test_ask_socket_wait.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_ask_socket_wait.py), [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_fleet_custody.py), and [test_hostctl_serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TESTPATCH/tests/test_hostctl_serve.py). No assertions were weakened.

The index still reports `UU` for the fleet and hostctl serve tests. I left those resolved file contents unstaged because this sandbox cannot write `.git`; the launcher must mark them resolved and commit.