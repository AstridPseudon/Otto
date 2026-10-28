## 1. Design, in implementation order

1. `src/otto/portfolio/execution_host.py:1515` → Read each request once as bytes, parse it, and retain its digest. Use the digest to bind any pending claim to those exact request bytes.
2. `src/otto/portfolio/execution_host.py:1533-1571` → Classify the pending marker **before** deciding to dispatch. A valid terminal response wins, even if its status projection failed: finish cleanup without calling the handler. A claimed request with no response must never reach `_dispatch`. If this host holds its settled receipt, retry publication from that value. After restart, use an existing durable terminal response if present; otherwise publish a terminal `unknown` receipt with `retry: false`. A queued, unclaimed marker remains eligible for its existing admission path.
3. `src/otto/portfolio/execution_host.py:1566-1608` → Atomically write a pending claim containing the token, request digest, response path, and explicit `dispatch_claimed: true` **before** calling the handler. Preserve that claim when the handler returns `OwnerCompletion`. A crash after the claim but before a known settlement resolves conservatively to `unknown`. Keep queued markers explicitly unclaimed; preserve the deliberate rechecks for unsettled results at `:1627-1640`.
4. `src/otto/portfolio/execution_host.py:234-241,1610-1653` → Keep the fully formed, timed settled receipt in a per-token in-memory failure record before releasing `_active_files`. Make deferred and synchronous terminal results use one receipt publication and cleanup path. On a write failure, retain request and claim; on the next scan, retry only publication. Store the receipt and release the active token under the same lock so a scan cannot pass between those steps. Treat “response written, status projection failed” as a durable response, not as permission to overwrite or redispatch it.
5. `src/otto/portfolio/manager_journey_client.py:78-161` → Keep response-first readback and pending validation. No new client command is needed.

## 2. Failing test to write first

New file: `tests/test_receipt_fence.py`. The directory at the response path causes a real atomic rename failure; the test patches no product method.

```python
import json
import tempfile
import unittest
from pathlib import Path

from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.manager_journey_client import read_command_status
from otto.portfolio.owner_completion import OwnerCompletion


class ReceiptFenceTests(unittest.TestCase):
    def test_failed_deferred_response_retries_receipt_without_redispatch_even_after_restart(self):
        for restart in (False, True):
            with self.subTest(restart=restart):
                with tempfile.TemporaryDirectory() as temporary:
                    lane = Path(temporary)
                    token = "a" * 32
                    request = lane / f"request-{token}.json"
                    pending = lane / f"pending-{token}.json"
                    response = lane / f"response-{token}.json"
                    calls = []
                    completion = OwnerCompletion()

                    def handler(command):
                        calls.append(command["command"])
                        return completion

                    host = ExecutionHost(directory=lane, handler=handler)
                    request.write_text(json.dumps({"command": "finish-task"}))
                    host._serve_files(False)
                    self.assertEqual(calls, ["finish-task"])
                    self.assertTrue(pending.is_file())

                    response.mkdir()  # Atomic file replacement must fail.
                    completion.resolve({"outcome": "committed", "effect_count": 1})
                    self.assertIn(token, host.failures)
                    self.assertTrue(request.exists())
                    self.assertTrue(pending.exists())
                    response.rmdir()

                    survivor = (
                        ExecutionHost(directory=lane, handler=handler)
                        if restart else host
                    )
                    survivor._serve_files(False)

                    self.assertEqual(calls, ["finish-task"])
                    self.assertEqual(len(list(lane.glob("response-*.json"))), 1)
                    receipt = json.loads(response.read_text())
                    if restart:
                        self.assertIn(receipt["outcome"], {"committed", "unknown"})
                    else:
                        self.assertEqual(
                            (receipt["outcome"], receipt["effect_count"]),
                            ("committed", 1),
                        )
                    self.assertTrue(read_command_status(lane, token)["terminal"])
                    self.assertFalse(request.exists())
                    self.assertFalse(pending.exists())

                    survivor._serve_files(False)
                    self.assertEqual(calls, ["finish-task"])
```

## 3. What to delete

Delete the reentrant-only pre-dispatch pending-write branch at `src/otto/portfolio/execution_host.py:1581-1599` when the common claim replaces it. Consolidate the duplicate deferred and synchronous response-write/cleanup sequences at `:1617-1619` and `:1641-1643`. Remove the response-absent fallthrough that redispatches an already claimed request.

## 4. Plausible mistake

Clearing `_active_files` and retrying the **command** is the mistake. Both test cases reopen the same request after the write failure and assert one handler call. The current code calls it twice; reconstruction of `ExecutionHost` also checks the durable restart fence.

## 5. Existing expectation needing D19

`tests/test_manager_reentrant_ipc.py:143` expects no pending file while a manager dispatch is running. A claim written before handler entry makes that file present. A D19 decision should authorize changing this assertion to verify a claimed, processing marker. The queued request’s restart replay assertion at `:216` should remain: that request was not dispatched before restart.

## 6. Row corrections on `canon/main`

A pending marker does **not** always mean a settled receipt is owed. `execution_host.py:1537-1551` marks work queued without dispatch, and `:1627-1640` retains unsettled results for recheck. Also, the deferred marker at `:1602-1608` is written *after* `_dispatch` returns; it cannot fence a crash inside the handler. Finally, that marker contains no settled value, so a restart with no durable response cannot reconstruct the original result generically. Its safe answer is `unknown`, without calling the handler again.

This is a read-only design; I did not run tests or modify files.