Implemented the D19 Restore section in the TESTPATCH lab.

- `tests/test_ask_socket_wait.py`: the drain cursor now continues through `EventCursorReader.page` on the assignment report stream. The test checks the next report appears once and is not replayed.
- `tests/test_fleet_custody.py`: the real owner-backed facade test prepares a second admitted T2 lab with `two.txt` and verifies it is not landed.
- `tests/test_hostctl_serve.py`: the canary uses a real historical task revision whose content matches the current task. The positive hydration test starts from a prior revision and checks refreshed task and criterion refs against independent owner records.
- `src/otto/hostctl/serve.py`: staged `task_refs` now enter `policy_state` before validation; state is still committed only after validation.

**Checks:** The four restored regressions passed (**4 passed**). The brief’s full check completed: **67 passed, 11 failed, 4 skipped, 7 subtests passed**. The failures are sandbox restrictions on `sandbox-exec` and `ps`; they need the landing gate’s separate sandbox. I also removed the scope guard temporarily to verify canary sensitivity: the canary failed with `RuntimeError not raised`; I restored the guard. Final `git diff --check` passed.

Changed files: `src/otto/hostctl/serve.py`, `tests/test_ask_socket_wait.py`, `tests/test_fleet_custody.py`, and `tests/test_hostctl_serve.py`. No assertion expectations were weakened or changed. No other labs were touched; changes are left for the launcher to commit.