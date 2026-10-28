# Brief: UNTIME (normal, 0.5 focused days)

**Outcome:** the tests listed in `~/Developer/otto-program/ops/flaky.txt` wait on the state they mean, not on fixed time. Each listed test passes 5 of 5 runs while the machine is loaded. No assertion is removed. The full row is `UNTIME` in `~/Developer/otto-program/projects/program/tasklist.md` (line 50). Read that row first.

**Why it matters:** the gate's paired re-runs refuse on timed tests that fail under load. "Tests wait on state, not time" is the user's rule: only a hang should fail a test.

**Your lab:** `~/Developer/otto-claude-host/labs/UNTIME`, on branch `lab/UNTIME`, from `canon/main` at `4b3d9d7`. Work only here.

**Layer:** Otto product (tests only, PLAN.md D14). Nothing in `src/` changes. `tests/test_herzchen_boundary.py` must stay green.

**The tests in scope (the complete list, from `ops/flaky.txt`):**
1. `tests/test_external_owner_context.py::ExternalOwnerContextTests::test_native_wait_admits_only_exact_owner_reads_without_releasing_custody`
2. `tests/test_manager_reentrant_ipc.py::ManagerReentrantIPCTests::test_close_retains_child_responses_and_defers_second_dispatch_to_restart`
3. `tests/test_manager_reentrant_ipc.py::ManagerReentrantIPCTests::test_explicit_manager_commands_may_advance_bound_task_after_exact_admission`
4. `tests/test_missing_manager_capture.py::MissingManagerCaptureTests::test_aborted_manual_selector_allows_distinct_same_native_callback_start`

**Files you own:** exactly the three test files above: `tests/test_external_owner_context.py`, `tests/test_manager_reentrant_ipc.py`, `tests/test_missing_manager_capture.py`. Change nothing else. Do not add a new test file.

**Do not touch:**
- any `src/` file: if a test's wait needs a product change to observe its state, stop and report it, don't change the product;
- other tests, even ones in the same file that aren't on the list;
- `ops/flaky.txt` (the manager maintains it);
- `~/.otto`, `~/.codex`, `~/Documents/Codex`, `production/`, and any Store;
- the live owner. Do not run `ottoctl`, and never pass it `--help`.

**What to do in each test:** replace each fixed `sleep`, fixed timeout, or fixed-time wait (for example `timeout_seconds=`, `Event.wait(2)`, `time.sleep`) with a wait on the state the test means: an event, a file, a status, or a condition polled with a deadline. Keep a deadline only as a guard against a hang, and make it generous (tens of seconds). Keep every assertion.

**Your check.** Make it green and keep everything else green:
- run each listed test file alone through `otto-heavy`, twice, with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`;
- each listed test must pass on the lab and must still assert what it asserted before (show the diff of assertions: none removed);
- run the three files again under load, at the same time as another run, to show the wait holds;
- regression: the same files on `canon/main` must pass too, as a sanity check that you didn't change the expectation;
- run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "UNTIME check" -- <cmd>`.

**Command forms.** Your Bash allowlist matches command prefixes only. Use `git -C <lab> …` (one git command per call), not `cd <lab> && …`. Use the tilde path `~/Developer/otto-claude-host/bin/otto-heavy` exactly. Don't use `env VAR=…`, `mktemp`, `/tmp` or `tar`. Keep scratch inside the lab and never commit it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_external_owner_context.py tests/test_manager_reentrant_ipc.py tests/test_missing_manager_capture.py`

**Existing tests:** this task changes how the listed tests wait, not what they assert. If a listed test's assertion itself must change to pass, stop and report instead: that needs an Opus decision (D19).

**Regression at the level the friction appears:** n/a: test-only task.

**Deletion budget:** name the fixed sleeps and timeouts you remove.

**Working rules:** commit work in progress to `lab/UNTIME` as you go. Never run `git stash`, and never check out another commit in the lab. Commit only the three test files, never `.brief.md`. **Never wait:** no Monitor, no sleep loops and no background job you wait on. Run tests in the foreground. If a question blocks you, decide it within this brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**When done:** commit to `lab/UNTIME` and don't push. Report the commit, the check runs (red where the wait was timed, then green), what you removed, and anything you couldn't finish.
