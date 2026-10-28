1. **Verdict: LAND.** The deleted test only covered `CodexCliAdapter`, which the live service never ran and HOSTKIT deleted. The live binding never had that coverage, so removing the test loses none. The live path does have a separate gap that existed before HOSTKIT (finding 1), and it needs its own task.

2. **Findings**, most severe first

   **F1 (gap on the live path, existed before HOSTKIT, not a reason to send back). The live Codex binding doesn't do what the deleted test expected, and nothing tests it end to end.**
   - **Evidence:**
     - In `CodexCliBinding.execute` (`src/herzchen/adapters/host.py:829-889`), the try only catches `TimeoutExpired` and `OSError`.
     - A `RuntimeError` after the provider has emitted usage escapes. `HerzchenHostAdapter.execute` (`host.py:1879-1881`) then maps it to `HostOutcome.FAILED`, with empty metadata.
     - An `OSError` from the prompt transport (`host.py:158-161`) returns `FAILED` (`codex_launcher_os_error`) at `host.py:884-889`, also with no `usage_capture`.
     - `usage_stream.snapshot()` is only reached on the normal return (`host.py:1002`).
     - So on the live path an interrupted turn reports `failed`, not `unknown`. The usage reaches the owner only through the callback, which fires on the reader thread before `wait`. The turn's metadata doesn't carry it.
     - Only these lines are untouched by HOSTKIT. The rest of `host.py` is in its diff, so this is behaviour from before HOSTKIT.
   - **What is tested on the live path:**
     - Usage is emitted once before the interrupting `wait`, at stream level: `tests/test_usage_capture.py:197` `test_host_stream_callback_precedes_terminal_wait_and_authority_callback_stays_separate`. It drives `_communicate_after_native_start` and asserts one observation. It doesn't check the outcome.
     - A telemetry callback raising `OSError` is harmless, at stream level: `tests/test_usage_capture.py:182` `test_line_and_count_bounds_and_optional_callback_failure`, which includes `codex-host`. The guard is `optional_emit` (`src/herzchen/usage/capture.py:26-34`), and the binding passes its callback straight into `UsageStream` (`host.py:824-828`), so the guard covers the live path too.
     - No test drives `CodexCliBinding.execute` through either case.
   - **Why it matters:** copying the deleted test onto the live binding would fail today, on the outcome and on `metadata['usage_capture']`. That means changing code in `host.py`, which is outside HOSTKIT's "move without changing behaviour" row. Whether an interruption after start should be `unknown` (the owner keeps custody) rather than `failed` is a decision to make on its own.
   - **Fix:**
     - Outcome: a new task, with a decision on whether `unknown` is the required outcome.
     - Check: a binding-level test with `herzchen.adapters.host.subprocess.Popen` patched to a fake process that emits usage, then raises from `wait` or the transport. It asserts outcome `unknown`, one owner observation, and `usage_capture` present. A second case has the usage callback raise `OSError` and asserts `succeeded` with the usage kept.

   **F2 (low). The `codex-direct` usage descriptor still claims a live seam that no longer exists.**
   - **Evidence:**
     - `src/herzchen/usage/contract.py:132-139` keeps `codex-direct` with `live="supported"` and invoke/resume `supported`. HOSTKIT repointed its `source_paths` to `src/herzchen/fleet/hosts/codex.py`.
     - The only runtime producer of `UsageStream("codex-direct")` was `CodexCliAdapter` (canon `src/otto/agents/codex_cli.py:295`). On `lab/HOSTKIT`, `codex-direct` appears in `src` only as the default of `normalize_codex_jsonl` (`fleet/hosts/codex.py:191`) and in the descriptor itself.
     - `tests/test_usage_contract.py:25` pins `live: supported`.
   - **Why it matters:** the usage contract now claims a live path that nothing runs.
   - **Fix:**
     - Outcome: a follow-up marks `codex-direct` as offline-only or retires it. Changing `test_usage_contract.py:25` would be its own D19 decision.
     - Check: no descriptor claims `live="supported"` unless some `src` constructs a `UsageStream` with its id.

3. **Sound**
   - **Q2:** the class was deleted, not just its use in this test.
     - On canon, `CodexCliAdapter` was referenced only by its own module, the `otto.agents` export and this test.
     - The live path constructs `CodexCliBinding` (canon `src/otto/agents/herzchen_adapter.py:501`).
     - On the lab, `codex_cli.py` is gone, along with its exports.
     - `tests/test_host_contract.py:722` `test_one_codex_binding` pins one Codex binding, the module's absence and the removed exports.
   - The `test_usage_capture.py` diff is exactly two hunks: the import moves to `herzchen.fleet.hosts.codex.normalize_codex_jsonl` (the normalizer's comment says it moved unchanged), and the one test is deleted. No other assertion changed.
   - **Q3:** the other test changes.
     - `src/otto/portfolio/tests/test_native_caller_ingress.py` is a fixture change only: it passes the new `native_caller_profile` / `"otto-native-caller"` argument. Every assertion is kept. The `assertRaises(ValueError)` on line 180 still fails for the same reason, the missing observer, because the profile is now supplied.
     - `tests/test_herzchen_boundary.py` is additive only, with no removed lines.
     - `tests/test_host_contract.py` is new.
     - No other test files changed.
   - **Tests on `af1b49d`**, clean worktree, `python3.11 -m pytest -q -p no:cacheprovider`:
     - `test_usage_capture`: 16 passed.
     - `test_host_contract`: 34 passed.
     - `test_herzchen_boundary`: 4 passed.
     - `NativeCallerIngressTests` under unittest: 9 OK.
     - The one failure in that module is the imported `CallerContextTests.test_worker_context_uses_retained_native_readback_without_an_admission_field` ("completed role result differs…"). It matches the worker's report that it fails on canon too.

4. **Not checked**
   - I didn't confirm that failure on canon myself, because of the no-checkout rule. It needs `labs/_baseline` or the gate.
   - I didn't run the RUNBOOK §4 gate (each file twice).
   - I didn't trace `owner_runtime` → `gateway.operation` end to end for the interruption case.
   - I didn't check whether `attempt_capture.record` (`gateway.py:1296`) can overwrite the observation the callback already recorded when `usage_capture` is `None`.
   - The worker's report cites commits `8e9da10`/`bd17b70`/`4cb32af` on `033cd03`. The branch now has `9e7c16a`/`2fec586`/`af1b49d` on `ed78f58`, so it has been rebased again since that report. I reviewed the branch as it stands now.

5. **Delete list:** the `codex-direct` live claim in `src/herzchen/usage/contract.py:132-139` (F2). The code it described is gone.

I made no changes to the repos. The helpers wrote scratch output only to `/tmp`.