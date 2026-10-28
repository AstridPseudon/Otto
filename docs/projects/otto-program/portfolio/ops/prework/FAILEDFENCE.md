## 1. Design, in implementation order

1. `tests/test_capacity_holds.py:254` → Write the failing test below first. Add a separate real-owner Claude stream test for each ordering: `error_max_turns` before `worker-done`, and a landed `worker-done` before the terminal error. Use a fake model process and the real done command; do not wrap `transport.run` to create the ordering.
2. `src/otto/portfolio/execution_host.py:419,512` → Generalize the existing pinned gone-group disposition to accept an owner-retained `failed` result as well as `unknown`. Require the assigned lifecycle owner, exact Due and result digests, a distinct request key, an authenticated report, and proof that the recorded group is gone. Preserve `gateway_attempt` byte-for-byte, forbid provider retry, and make repeated recovery return the same disposition.
3. `src/otto/portfolio/execution_host.py:395-409` → Verify the new failed-result marker on restore before removing its hold. Keep the old `unknown` marker and schema readable for retained records. Leave `_eligible` at `:850-862` unchanged: custody fences only that project until settlement.
4. `src/otto/portfolio/manager_journey_service.py:1493,1563-1585` → Route the manager’s pinned `execution-control recover` request to the shared disposition. Add `expected_result_sha256` for `failed`; retain `expected_unknown_result_sha256` for the existing route. Return `historical_result_preserved`, `provider_called: false`, and `retry: false`.
5. `src/otto/portfolio/manager_journey_client.py:538-544` → Expose the Due hash, result hash, and reason flags. The service accepts these fields today, but this CLI cannot send them. `src/otto/portfolio/execution.py:1458-1520` and `manager_journey_service.py:1588-1593` → Have recovery status and the read response name the manager’s gone-group recovery and supply its exact pins for a held `failed` result. Keep it a held startup state until disposition.
6. `src/otto/agents/claude_adapter.py:36` → Apply TRIAGE decision 1’s worker `max_turns` value. **The decision and its value are absent from `canon/main`; I asked for the value and cannot specify this edit without inventing it.**

## 2. Failing test to write first

`tests/test_capacity_holds.py`, `CapacityHoldTests.test_manager_settles_gone_failed_worker_before_next_launch`. This first test targets the failing custody seam on the real owner. The additional stream-ordering tests in step 1 are required for the full acceptance criterion.

```python
def test_manager_settles_gone_failed_worker_before_next_launch(self):
    from copy import deepcopy
    from otto.portfolio.execution import _digest

    f = self.fixture.f
    due = f.app._read(self.schedule)
    evidence = deepcopy(due.host_evidence)
    result = evidence["gateway_attempt"]["result"]
    result["outcome"] = "failed"
    result["delivery_state"] = "failed"
    result["error"] = {"code": "claude_native_failure",
                       "message": "error_max_turns"}
    f.port.save_due(
        self.schedule,
        replace(due, host_evidence=evidence).to_dict(),
        request_id="failed-native-result",
        expected_version=due.version,
    )
    due = f.app._read(self.schedule)
    original_attempt = deepcopy(due.host_evidence["gateway_attempt"])
    host = self.host()
    host.restore_execution(f.app, due)
    process = self.group()
    host.record_process_group(self.schedule, process.pid)

    request = dict(
        schedule_id=self.schedule,
        request_key="settle-gone-failed-worker",
        expected_due_sha256=_digest(due.to_dict()),
        expected_result_sha256=_digest(result),
        reason="The native worker ended with error_max_turns.",
    )
    before = f.port.read_due(self.schedule)
    live = host.recover_gone_worker(f.app, **request)
    self.assertEqual(live["outcome"], "refused", live)
    self.assertEqual(live["cause"], "process_group_alive")
    self.assertEqual(f.port.read_due(self.schedule), before)

    self.kill_group(process)
    self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
    scope = host._capacity_holds[self.schedule]
    follow_on = {**scope, "schedule_id": "follow-on-worker",
                 "assignment": ("execution-owner", "next-assignment", 1),
                 "session": "next-session"}
    self.assertFalse(host._eligible(follow_on))
    self.assertTrue(host._eligible({
        **follow_on, "project": "project-b",
        "workspace": str(self.directory / "project-b"),
    }))

    calls = len(f.provider.calls)
    settled = host.recover_gone_worker(f.app, **request)
    self.assertEqual(settled["outcome"], "settled", settled)
    after = f.port.read_due(self.schedule)
    self.assertEqual(after["stop_state"], "stopped")
    self.assertEqual(after["completion_state"], "failed")
    self.assertIsNone(after["in_flight_request"])
    self.assertEqual(after["host_evidence"]["gateway_attempt"],
                     original_attempt)
    self.assertNotIn(self.schedule, host._capacity_holds)
    self.assertTrue(host._eligible(follow_on))
    self.assertEqual(len(f.provider.calls), calls)
    self.assertEqual(
        host.recover_gone_worker(f.app, **request)["outcome"], "replayed")
    self.assertEqual(f.port.read_due(self.schedule), after)
    reports = f.app.assignments.list_observations(
        ResourceRef.from_dict(after["assignment_ref"]), kind="report")
    self.assertEqual(len(reports), 1)

    fresh = f.app.assign_worker(
        **{**f.request(), "request_key": "worker-after-failed-fence"})
    f.app.assignments.dispatch(
        ResourceRef.from_dict(fresh["assignment_ref"]),
        expected_generation=fresh["generation"],
        logical_request_key="dispatch-after-failed-fence", actor=f.actor)
    host.start()
    self.addCleanup(host.close)
    with host._command_lock:
        launched = host._owned(
            lambda: f.app.start(schedule_id=fresh["schedule_id"]))
    finished = threading.Event()
    answer = {}
    launched.then(
        lambda value: (answer.update(value or {}), finished.set()),
        lambda error: (answer.update(error=str(error)), finished.set()),
    )
    finished.wait()  # Only a hang fails.
    self.assertEqual(answer["outcome"], "succeeded", answer)
    self.assertEqual(len(f.provider.calls), calls + 1)
```

## 3. Delete

Delete the `unknown`-only qualification at `execution_host.py:553-556` when replacing it with outcome-specific checks in the shared path. Do not add a second recovery implementation or remove the old retained-record verifier.

## 4. Plausible mistake

Treating `failed` as proof that the worker had no effects could admit another turn for the *same* attempt. The test requires the original attempt and provider-call count to remain unchanged through settlement and replay; only a separately admitted worker may launch. The live-group assertion prevents release based solely on the error result.

## 5. Existing expectations requiring D19

None if the old `unknown` marker, response fields, and behavior remain compatible. Changing `tests/test_capacity_holds.py:330-346` to expect a new marker or a different historical completion state for `unknown` would require a written D19 decision; this design avoids that change.

## 6. Row corrections and limits

The 8-turn value is verified, but “closing answer is turn 9” is an inference, not an observed fact on `canon/main`. `error_max_turns` maps to `failed`; incomplete streams and parser failures can instead map to `unknown`. The narrow capacity-failure recovery already settles one `unknown` result with a failed native cause. Also, the general gone-group recovery exists in the service but lacks CLI flags for its required pins. No files were changed and no tests were run.