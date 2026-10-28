## Design

1. [tests/test_fleet_custody.py:211](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:211) → Remove the fixture’s `_OwnerExecutorPort` and `_TaskContextPort` replacements so the new test exercises the product port. Add the regression test below beside the worker facade tests.
2. [src/otto/hostctl/product_service.py:227](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:227) → Make the operation passed to `executor` call `inner.call`, then call `settle(assignment)` when `worker-done` returns a mapping with `landed is True`, then return the result. Settlement must finish before that owner operation signals its waiter. Keep the same landed condition and exception behavior.
3. [src/otto/hostctl/product_service.py:507](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:507) → Retain the existing active-record gate. Both landing calls and the task fallback resolve assignment context on the owner lane; a call queued with a grant captured before revocation will find the record settled and be refused. No new gate is needed.

## Failing test to write first

Add `test_landed_done_revokes_before_facade_waiter_resumes` to [tests/test_fleet_custody.py:299](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:299), after removing the fixture replacements above. It uses the real registry facade, `_OwnerExecutorPort`, and `ExecutionHost` owner pump. The injected landing service supplies only the landed result and records whether `check` ran.

```python
def test_landed_done_revokes_before_facade_waiter_resumes(monkeypatch, tmp_path):
    import threading
    from otto.portfolio.execution_host import ExecutionHost

    calls = []

    class Landing:
        def done(self, lab_name, task_id, **_pins):
            calls.append(("done", lab_name, task_id))
            return {"landed": True}

        def check(self, lab_name, task_id):
            calls.append(("check", lab_name, task_id))
            return {"feedback_only": True}

    landing = Landing()
    registry, _task, record, token, _repo = _fleet_registry_fixture(
        monkeypatch, tmp_path,
        plan={"repo": "repo-a", "branch": "project-line"},
        landing_factory=lambda **_kwargs: landing,
    )
    host = ExecutionHost(
        directory=tmp_path / "owner-pump",
        handler=lambda _request: {},
        owner_file_compatibility=True,
        bounded_transports=True,
    )
    owner_returned = threading.Event()
    release_facade = threading.Event()
    replies = []
    done_thread = None

    def execute(operation):
        def run_owned():
            with host._command_lock:
                return host._owned(operation)

        result = host._owner_request(run_owned)
        if threading.current_thread() is done_thread:
            owner_returned.set()
            release_facade.wait()
        return result

    registry.bind_owner_executor(execute)
    host.start()
    done_thread = threading.Thread(
        target=lambda: replies.append(registry.facade.call(token, "done"))
    )
    try:
        done_thread.start()
        owner_returned.wait()  # Owner finished done; its facade thread is held.
        refused = registry.facade.call(token, "check")
        assert refused == {
            "ok": False, "error": "unauthorized", "detail": "unknown token"
        }
        assert calls == [("done", "task-owned-by-worker", "task-owned-by-worker")]
        assert record.state == "settled"
        assert registry.tokens.live() == frozenset()
    finally:
        release_facade.set()
        done_thread.join()
        host.close()
        registry.close()

    assert replies[0]["submitted"] is True
```

## Delete

Delete the settlement *after* `executor(...)` at [product_service.py:232–233](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:232); its condition moves inside the owner operation. Delete the test fixture’s port replacements at [test_fleet_custody.py:211–213](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:211). The fixture’s `FleetStub` and its patch at lines 195–197 and 209 are also dead: `_pair` imports `LabFleet` locally at product_service.py:640.

## Failure mode and test evidence

A plausible fix leaves settlement after `executor` and adds a token check at facade entry. The test catches it: the `done` thread is held after the owner pump returns but before facade-side settlement, so the same token still resolves and `check` runs. Moving settlement into the owner operation makes `check` return `unauthorized` without reaching landing.

**D19:** No existing test assertion needs to change. The existing done tests make no claim that a landed token remains usable. The row’s implied missing settled-record gate is stale: [product_service.py:507–511](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:507) already rejects settled records. Separately, [claude_cli.py:63–67](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_cli.py:63) has an outdated comment saying check and done are not yet allowlisted; the product facade allowlists them at product_service.py:430–437.

This is an inspection-only design; I did not run tests or change files.