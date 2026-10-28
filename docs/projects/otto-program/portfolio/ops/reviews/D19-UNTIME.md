1. **Verdicts**
- **Q1 (external owner `mkdir`): LAND.** It does what `start()` does and doesn't touch what the test checks.
- **Q2 (external owner timeouts): LAND.** Each changed number is a guard against a hang. No expectation got weaker.
- **Q3 (reentrant IPC guards): SEND BACK.** The gate recorded two failure kinds for these tests that a longer guard can't fix. Both need a wait on the right state, inside the test file.
- **Q4 (other assertion changes): None.**

The commit lands as a whole, so UNTIME goes back. The worker should keep the external-owner change as it is and fix the two reentrant waits below.

2. **Findings**, most severe first

**F1. `test_close_retains_child_responses_and_defers_second_dispatch_to_restart` races at line 212. Widening doesn't help.**
- **Evidence:** `ops/runs/POOL/.gate/fail-test_manager_reentrant_ipc.py-run2.txt` and `pair-2-lab1.txt` both fail at `tests/test_manager_reentrant_ipc.py:212` (`assertFalse((self.directory / "pending-ffffff.json").exists())`) with `AssertionError: True is not false` (`1 failed in 12.37s`).
- **Cause:** the test wakes when the replay response exists (`:209`, `wait_file(queued)`) and checks straight away that the pending file is gone. The host writes the response first and removes the pending file afterwards: `src/otto/portfolio/execution_host.py:1161` `_atomic_json(response, ...)`, then `:1162` `pending-<token>.json .unlink()` (the same order at `:1180-1181`). Under load, the test can run between those two lines.
- **State to wait on:** `pending-ffffff.json` is absent. Poll for that with a hang guard, then keep the assertion at `:212` and the one at `:213`.

**F2. `test_explicit_manager_commands_may_advance_bound_task_after_exact_admission` reads a receipt that is still being written. Widening doesn't help.**
- **Evidence:** `ops/runs/POOL/.gate/pair-3-base1.txt` shows `:255` `self.wait_file(self.child_receipt)` → `:85` `json.loads(path.read_text())` → `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` with `s = ''` (`1 failed in 14.05s`). It failed on base, so it isn't caused by the lab change.
- **Cause:** the child script writes `Path(sys.argv[3]).write_text(json.dumps(results))` (`:52`), which isn't atomic. `wait_file` (`:81-85`) returns as soon as the file exists, so it can read it empty.
- **Same risk elsewhere:** the child-ready file is written the same way (`:45`) and waited on at `:161`. The close test reads `child_receipt` at `:174` the same way.
- **State to wait on:** the child's file is complete. Have the child write it to a temporary name and `os.replace` it into place at `:45` and `:52`. Product files already arrive this way (`retained_projection.py:132` uses `os.replace`).

**F3. The other failures recorded for these two tests were guard expiries, which the widening does fix.**
- **Evidence:** `fail-test_manager_reentrant_ipc.py-run1.txt` shows `wait_file` running out (`:84`, then `AssertionError: False is not true`):
  - for the close test at `:197` on `response-abc123.json`;
  - for the explicit-commands test at `:255` on `child-responses.json`.
- That run took 64.38 s against the old 8 s guard. The gate was queued behind other jobs ("memory pressure is critical") at the time.
- On base, the subprocess timeout (12 s, `:66`) was also shorter than the child's own two 10 s deadlines. The new 60 s covers both 30 s waits.
- So the widening is right as far as it goes, but it covers only half the observed failure kinds.

**F4. The worker's 5 of 5 passes don't show the reentrant tests are deterministic.** The worker says they "could not reproduce their flaky-list failures" and had "no red run on their original waits." F1 and F2 are narrow timing windows that five passes can't rule out. The gate saw them in 1 of 3 isolated runs each.

**F5. Follow-up (outside this decision): the missing-capture test fails on a 1-second time tolerance in product code.**
- `fail-test_missing_manager_capture.py-run2.txt` (`60.06s`) fails at `tests/test_missing_manager_capture.py:116`, then `src/otto/agents/manager_capture_reconciliation.py:130-131`. The check is `abs(starts[0]["started_at"] - observed.timestamp()) <= 1`, and it raises `OwnerRoleRuntimeError: native start differs from retained owner admission`.
- The worker found no timed wait in the test body. They were right: the time limit is in `src/`.
- It needs a row that decides whether the tolerance stays (a product question). It isn't a test-file fix.

3. **Sound**
- **The `mkdir` matches `start()`:** `execution_host.py:631` runs `self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)`, and the test's line 103 is the same call. `start()` is never called in this test, and nothing else creates the inbox before the first publish:
  - `__init__` doesn't create it;
  - `setUp` (`:15-20`) and `prepare_events` (`:25-27`) don't publish;
  - `OwnerAuthoringIngress.publish` creates it only when it publishes (`owner_authoring_ingress.py:55`).
- **The race the worker described is real:**
  - `_request_paths` calls `os.scandir(self.directory)` (`execution_host.py:1021`) with no handler for a missing directory.
  - `external_call`'s pump loop (`:1298-1302`) has no `except`, so the scan error escapes it.
  - The gate output fits this: the external test fails on the very first request, `during-whoami`, at about 4 s, on lab and on base (`fail-test_external_owner_context.py-run1/2.txt`, `pair-1-base1/2`, `pair-1-lab2/3`: `:117 in submit`). The pump never answers anything.
- **The `mkdir` doesn't change what the test checks.** None of its assertions (`:106`, `:120`, `:127`, `:133-142`) look at whether the inbox exists, its mode, or its absence. It checks reads admitted, writes held, forged requests rejected and Store counts unchanged.
- **The external timeouts are guards only:**
  - `begun.wait`: an event.
  - The response polls: the response file existing.
  - `finished.wait`: an event set in submit's `finally`.
  - `thread.join`: thread exit.
  - None of them asserts that something happens within a time limit.
- **No assertion changed in either file.** `git diff 4b3d9d7 17a2851 -- tests/` changes only numbers, plus the `mkdir` line and two comment lines. The rebased tip `193555a` has identical content for both files.
- **The reentrant waits already watch state:** files, `_closing`, thread exit. No bare sleeps. The child client (`manager_ctl.py:85-111`) has no time limit of its own for these commands.
- **The unlisted test was already red on canon.** `test_terminal_status_is_bounded_and_preserves_full_response` fails on canon `1ab1401` (`~/Developer/otto-claude-host/otto`, clean) with `KeyError: 'summary'` at `:278` (`1 failed in 0.64s`). It also failed in both POOL gate runs. The likely cause: the test writes a ~1.5 MB response with plain `write_text` (`:273`) and no `status-response-` sidecar, so `read_command_status` returns no summary (`manager_journey_client.py:105-110`). It has nothing to do with time.

4. **Not checked**
- I didn't run any test repeatedly, so failure rates come only from the POOL gate's retained output (one landing, 03:05–04:00Z). Outputs from earlier POOL attempts were overwritten.
- I didn't confirm through `_call_bound` that the scan error comes back as `outcome: error`. The first-request failures in the gate output fit that path.

5. **Helpers:** 3 Haiku workers.
- **`start()` and the inbox:** confirmed the `mkdir` at `:631`, the scan with no handler, `publish`'s `mkdir`, and that no assertion changed.
- **The reentrant waits and canon:** mapped every timed wait, found the canon checkout and ran the unlisted test there (red, `KeyError`). It called the partial-read risk "theoretical"; the gate output shows it happened (F2).
- **The gate failure output:** found the retained tracebacks for all four listed tests, the gate's reproduction rules (`land.sh:205-220`), and the missing-capture tolerance (F5). I read the reentrant and external tracebacks myself as well.