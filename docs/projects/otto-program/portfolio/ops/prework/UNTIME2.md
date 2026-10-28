## Design on `canon/main`

1. **Write the admission regression first.** Add the test below beside [tests/test_operator_admission.py:294](${TRANSFER_ROOT}/source/otto/tests/test_operator_admission.py:294). It puts an `admit` request ahead of a `status` probe on the real owner lane. The probe’s response proves the owner polled past the admission request while the hold was open. The owner sorts lane requests before applying deferral at [src/otto/hostctl/service.py:277](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:277).
2. **Convert the shared admission helper.** At `tests/test_operator_admission.py:269–292`, use the same probe in place of the 150 ms sleep. Keep its request, presence, and audit assertions and both callers’ outcome assertions. Wait for the final response without a test deadline.
3. **Wait for a completed owner callback.** At [tests/test_execution_host_manager_turn_queue.py:80](${TRANSFER_ROOT}/source/otto/tests/test_execution_host_manager_turn_queue.py:80), start a finite callback on another thread under `shared_lock` after `waiting` is set. Wait for its completion **before** releasing `slots`; assert the manager is still queued, then retain the response assertions. Remove the one-shot lock probe at lines 113–116. Use state waits and joins without deadlines in this test. The relevant product ordering is at `src/otto/portfolio/execution_host.py:1555–1563`.
4. **Observe a published heartbeat.** At [tests/test_embedded_host_heartbeat.py:98](${TRANSFER_ROOT}/source/otto/tests/test_embedded_host_heartbeat.py:98), poll the status file until a published `heartbeat_at` is at least five seconds after the first value, while the owner remains blocked. Then retain the heartbeat, projection, generation, holder, and `read_status(...)=running` assertions. The pulse writes that file at `src/otto/hostctl/project_service.py:402–413`. Convert the other deadline-based waits in this test and its `SerializedHost` fixture to state waits; the client `_await` can use `float("inf")`. A stopped pulse or held lock then hangs, which the outer harness treats as failure.
5. **No product change is indicated.** Rebase the first test file after OWNERCOMPLETION’s additions.

## Failing test to write first

`tests/test_operator_admission.py`, `OperatorAdmissionTests.test_admission_stays_queued_after_owner_poll_while_dispatching`:

```python
def test_admission_stays_queued_after_owner_poll_while_dispatching(self):
    from otto.hostctl.service import owner_lane

    host = SimpleNamespace(
        _external_waiting=1, begin_drain=lambda: None, close=lambda: None)
    self.owner_service.journeys["dispatching-project"] = SimpleNamespace(
        execution_host=host, run_id="dispatching-project",
        state={"manager": "test"},
        paths={"ipc": Path(self.home) / "ipc",
               "socket": Path(self.home) / "socket"})
    try:
        lane = owner_lane(Path(self.home))
        request = {"command": "admit", "args": {
            "task_ref": self.task_ref.to_dict(),
            "revision": self.task_ref.revision,
            "review_ref": self.review_ref.to_dict(),
            "request_key": "polled-held-admission"}}
        before = self.owner_service.served
        token = lanes.submit(lane, request, token="0" * 32)
        probe_token = lanes.submit(
            lane, {"command": "status"}, token="f" * 32)

        probe = lanes.wait(lane, probe_token, timeout_seconds=float("inf"))
        self.assertEqual(probe["outcome"], "serving")
        self.assertGreater(self.owner_service.served, before)
        self.assertTrue((lane / ("request-" + token + ".json")).exists())
        self.assertFalse((lane / ("response-" + token + ".json")).exists())
        self.assertEqual(self.prover.calls, 0)
        self.assertEqual(self._audit(), [])

        host._external_waiting = 0
        reply = lanes.wait(lane, token, timeout_seconds=float("inf"))
        self.assertEqual(reply["outcome"], "admitted", reply)
    finally:
        host._external_waiting = 0
        self.owner_service.journeys.pop("dispatching-project", None)
```

This test is green on correct `canon/main` behavior; its **failing** case is bypassed deferral. This is a test hardening task, so there is no honest red phase against unchanged product code.

## Deletions and D19 decisions

Delete the lock probe and its `lock_available` variable, the 5.2 s sleep and timing comment, and the admission helper’s 150 ms sleep. Do not add a polling hook to product code.

The heartbeat test also patches `service._status` at lines 100–106, contrary to the stated no-product-method-patching rule. Remove that wrapper; the frozen projection assertions and owner-thread operation assertion at line 154 remain. **D19 decision needed:** this removes the wrapper’s direct assertion about *every* `_status` call. **D19 decision needed:** the queue test replaces “the lock was acquired once” with the stronger expectation “a finite owner callback completed while the manager remained queued.” Other business expectations stay the same.

The plausible mistake is to replace each sleep with a shorter timeout or a one-off check. A slow owner could still make broken admission deferral pass. The status probe prevents that: it cannot receive its response until the owner has polled the earlier admission request.

## Row corrections and verification

On `canon/main`, `ops/flaky.txt` does not exist, so the row’s claim about its contents cannot be checked there. The admission helper serves **two** test methods (`:294` and `:304`), making this three wait sites across four test invocations. The cited line ranges otherwise match `canon/main`. No files were changed and no tests were run under the read-only instruction; loaded-machine 5/5 and mutation checks remain worker acceptance work.