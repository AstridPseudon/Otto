## 1. Design, in implementation order

1. `src/otto/agents/claude_cli.py:377-387,461-473` → Invoke `on_process` for initializers as well as work processes, before the selector can write stdin. If registration raises, terminate the owned tree, reap it, close its pipes, and retain the cleanup disposition. Raise a distinct pre-input registration failure **only when custody proves the group gone**; otherwise retain an unknown outcome and its capacity hold.

2. `src/otto/agents/owner_runtime.py:31-67` → Remove both exception-swallowing wrappers. Require the bounded owner context and let a missing occurrence, failed birth lookup, or pin write abort registration. Keep the owner-thread callback marshalling.

3. `src/otto/agents/claude_adapter.py:234-250,423-425,452-454` → Give the initializer a **pin-only** process callback; it must not enter the manager caller-socket observer. Preserve the current observer-then-pin order for work, but run observer cleanup if pinning raises. Start work only after the initializer’s recorded group is proven empty.

4. `src/otto/portfolio/execution_host.py:696-729` → Save a candidate pin map durably before changing `_process_groups`. Reject replacement while the previous group has any member or is unproven. This preserves the initializer record if the work pin fails. A failed save must never leave an in-memory pin that a restart cannot read.

5. `src/otto/agents/claude_adapter.py:488-498`, `src/otto/portfolio/execution.py:1423-1459`, `src/otto/portfolio/execution_host.py:356-417` → Retain an exact failed-before-useful-input result when registration failed and cleanup proved the new group gone. Terminally settle that Due as failed, then release its capacity and custody fence, including on restart. Share one predicate over the retained result and admission evidence; do not generalize ordinary failed or unknown results. If an older, empty initializer pin cannot be deleted because storage is still broken, that stale metadata must not prevent this verified terminal settlement.

6. `src/otto/portfolio/execution_host.py:731-768` → After validating the record, return `gone` immediately when `killpg(pgid, 0)` reports `ProcessLookupError`. Keep `alive` for an existing group, including a surviving member, and `unproven` for unreadable evidence. Remove the subsequent leader-PID lookup and `reused` branch.

Add focused owner tests for initializer pinning and recorded-group force-stop cleanup, plus the empty-PGID and live-member capacity cases. Keep custody-fence release separate from ordinary group-death reconciliation.

## 2. Failing test to write first

Add this method to `ClaudeManagerAdmissionTests` in `tests/test_claude_manager_admission.py`. The injected collision is a filesystem write failure; the substitute child stands in for the model. The test has no timing assertion.

```python
    def test_pin_write_failure_stops_initializer_before_input_and_releases_slot(self):
        import threading
        from otto.portfolio.execution_host import ExecutionHost

        host = ExecutionHost(
            directory=Path(self.root) / "pin-failure-ipc",
            handler=lambda _request: None,
            bounded_transports=True,
            capacity_store=self.f.store,
        )
        host.start()
        self.addCleanup(host.close)
        (host.directory / "capacity-process-groups.json").mkdir()

        input_marker = Path(self.root) / "native-input-received"
        processes = []
        model = (
            "import pathlib,sys\n"
            "line=sys.stdin.buffer.readline()\n"
            "if line: pathlib.Path(sys.argv[1]).write_bytes(line)\n"
        )

        def factory(_command, **kwargs):
            process = subprocess.Popen(
                [sys.executable, "-c", model, str(input_marker)], **kwargs
            )
            processes.append(process)
            return process

        self.manager_t.process_factory = factory
        prepared = self.app.prepare_role(**self.role(fresh_manager=True))
        launched = host._owner_request(
            lambda: self.app.start(schedule_id=prepared["schedule_id"])
        )
        completed = threading.Event()
        observed = {}

        def capture(value):
            observed.update(value)
            completed.set()

        def failed(error):
            observed["raised"] = repr(error)
            completed.set()

        launched.then(capture, failed)
        completed.wait()

        self.assertEqual(observed.get("outcome"), "failed", observed)
        self.assertEqual(len(processes), 1)
        self.assertFalse(input_marker.exists())
        self.assertIsNotNone(processes[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(processes[0].pid, 0)

        due = self.f.port.read_due(prepared["schedule_id"])
        self.assertEqual((due["stop_state"], due["completion_state"]),
                         ("completed", "failed"))
        self.assertEqual(due["host_evidence"]["gateway_attempt"]["result"]["outcome"],
                         "failed")
        self.assertEqual(host._process_groups, {})
        self.assertEqual(host.capacity_holds(), {})
        self.assertEqual(host.capacity.snapshot()["pool"]["held_units"], 0)

        restarted = ExecutionHost(
            directory=host.directory,
            handler=lambda _request: None,
            bounded_transports=True,
            capacity_store=self.f.store,
        )
        restarted.restore_execution(self.app, self.app._read(prepared["schedule_id"]))
        self.assertEqual(restarted.capacity_holds(), {})
        self.assertEqual(restarted.capacity.snapshot()["pool"]["held_units"], 0)
```

## 3. Delete

Delete the initializer exclusion at `claude_cli.py:377`, the silent catches and `safe` wrapper at `owner_runtime.py:53-67`, and the leader-PID decision path at `execution_host.py:753-768`. Do not add another process registry. Remove the product-method patch in `tests/test_capacity_pool.py:454-459` when updating that test; it violates the stated harness rule.

## 4. Plausible mistake

A worker could free capacity as soon as pin writing fails, while the child remains alive or has received stdin. The first test catches that through the input marker, process-group probe, terminal Due, and restart slot check. The existing live-member test at `tests/test_capacity_holds.py:129-141` catches the other mistake: releasing on a leader-PID mismatch while the recorded group still has a member.

## 5. Existing expectations requiring a D19 decision

**D19 decision:** pinning is a launch gate; silent pin failures are no longer acceptable.

- `tests/test_capacity_pool.py:409-425`, `test_pin_failure_never_breaks_the_launch`: reverse its no-raise expectations for an exited process, unknown occurrence, and absent owner context.
- `tests/test_capacity_pool.py:475-493`, `test_pin_from_a_foreign_thread_outside_a_transport_wait_is_silent`: expect registration failure, with no input.
- `tests/test_capacity_holds.py:121-127`, `test_reused_pid_after_group_death_stays_held`: expect the empty PGID to free the slot. Keep `:110-119` and `:129-141` held because their groups are live.

## 6. Stale row or surrounding claims

The row’s test at `:121` simulates reuse by pairing the current PID with an empty unrelated PGID; it does not cause actual PID reuse. “Exactly when” means at the next reconciliation or restore: the current periodic reconciliation is at `execution_host.py:1006-1014`. The module comment in `test_capacity_holds.py:4` and the fail-open explanation in `owner_runtime.py:46-49` become stale. `herzchen/fleet/custody.py:166-178` already treats a reused leader with an empty old group as gone; the host should use the same rule.

No files were changed, and no tests were run.