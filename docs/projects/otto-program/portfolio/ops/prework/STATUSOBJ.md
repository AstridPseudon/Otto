## 1. Design, in build order

1. [tests/test_embedded_host_heartbeat.py:159](${TRANSFER_ROOT}/source/otto/tests/test_embedded_host_heartbeat.py:159) → write the regression test below first. It uses private status files and a live PID; it starts no owner.
2. [src/otto/hostctl/service.py:119](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:119) → after the existing file read and missing-file handling, validate the fields that status interpretation uses. Require `schema == STATUS_SCHEMA`, a known `state`, a mapping `holder` with a positive integer PID, a valid ISO heartbeat string, and a finite positive numeric `heartbeat_seconds`. Exclude booleans as numbers. Validate `holder.owner_actor` when present because lane advice uses it. Allow `in_flight` to be absent on closed records; when present, require a mapping with list-valued `lane_requests` and `relays`. Validate `manager_turn_active` when present.
3. [src/otto/hostctl/service.py:128](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:128) → probe the validated PID and calculate freshness from parsed heartbeat values. Keep the existing live, stale, draining, and closed classifications for valid records. Return `{ "outcome": "unavailable", "reason": "invalid status schema: <field> ...", "provider_called": False }` for invalid fields, without copying damaged fields into that result. Handle an out-of-range PID at the probe as invalid schema.
4. [src/otto/hostctl/service.py:144](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:144) → compute `busy` once from validated `in_flight` lists and `manager_turn_active`. Keep `busy=False` for stale and closed results. The existing CLI callers at [cli.py:893](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:893) and [cli.py:937](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:937) can then use the sanitized unavailable result without another parser.
5. [tests/test_hostctl_ownersafe.py:24](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_ownersafe.py:24) → complete that synthetic *closed* fixture with the published schema, PID, and heartbeat fields. Preserve its closure-guidance assertions.

## 2. Failing test to write first

File: `tests/test_embedded_host_heartbeat.py`; name: `test_read_status_rejects_damaged_schema_and_accepts_live_status`. Add this method to `EmbeddedHeartbeatTests`:

```python
def test_read_status_rejects_damaged_schema_and_accepts_live_status(self):
    from datetime import datetime, timezone
    import os
    from otto.hostctl.service import STATUS_SCHEMA

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "status.json"
        live = {
            "schema": STATUS_SCHEMA,
            "state": "serving",
            "holder": {"pid": os.getpid(), "owner_actor": "owner"},
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "heartbeat_seconds": 1.0,
            "manager_turn_active": False,
            "in_flight": {
                "lane_requests": [{"token": "a" * 32}],
                "relays": [],
                "manager_lane_queued": {},
            },
        }
        cases = (
            ("string holder", {"holder": "owner"}, "holder"),
            ("invalid PID", {"holder": {"pid": "unknown"}}, "holder.pid"),
            ("invalid actor", {"holder": {"pid": os.getpid(),
                                         "owner_actor": 7}}, "holder.owner_actor"),
            ("invalid in_flight", {"in_flight": "busy"}, "in_flight"),
            ("invalid requests", {"in_flight": {
                "lane_requests": "busy", "relays": []}}, "in_flight.lane_requests"),
            ("invalid interval", {"heartbeat_seconds": "often"}, "heartbeat_seconds"),
            ("invalid heartbeat type", {"heartbeat_at": []}, "heartbeat_at"),
            ("wrong schema", {"schema": "other"}, "schema"),
        )
        for label, changes, field in cases:
            with self.subTest(label=label):
                lanes.atomic_json(path, {**live, **changes})
                result = read_status(path)
                self.assertEqual(result["outcome"], "unavailable", result)
                self.assertIn("invalid status schema:", result["reason"])
                self.assertIn(field, result["reason"])
                self.assertIs(result["provider_called"], False)
                self.assertNotIn("holder", result)

        lanes.atomic_json(path, live)
        result = read_status(path)
        self.assertEqual(result["outcome"], "running", result)
        self.assertIs(result["holder_alive"], True)
        self.assertIs(result["busy"], True)
```

## 3. Delete

Replace the unchecked `holder` fallback at [service.py:128](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:128), the invalid-heartbeat-to-stale fallback and `float(... or 1)` at [service.py:137](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:137), and the repeated unchecked `in_flight` lookups at [service.py:144](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:144). No file or separate status interpreter needs deleting.

## 4. Plausible mistake

Catching `AttributeError`, `TypeError`, and `ValueError` around the whole interpreter would stop some tracebacks but could classify damaged records as stale, or leave malformed `holder` data for CLI advice to read. The test requires a field-specific unavailable reason, omits the damaged holder from the result, and checks that a valid busy owner still reports running.

## 5. Existing expectations and D19

**D19 decision:** preserve existing assertions. The incomplete closed fixture at [tests/test_hostctl_ownersafe.py:24](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_ownersafe.py:24) currently lacks schema, PID, and heartbeat fields. Complete that fixture so its assertions continue to test closure guidance. No existing assertion needs changing. The valid running, draining, closed, and dead-PID expectations remain valid.

## 6. Row corrections

The cited failure lines are accurate. On `canon/main`, there are **no existing tests with the four malformed fixtures**; the row’s “current fixtures raise” describes what those fixtures would do when added. The JSON reader already rejects a non-object top-level value. `FILELANES 6` and `STATUSOBJ` are not present in `canon/main`, so that cross-reference cannot be verified there. No files were changed and no tests were run.