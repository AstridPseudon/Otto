## 1. Design, in implementation order

1. [src/otto/hostctl/lanes.py:71](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/lanes.py:71) → Extend `read_private_json` with an optional byte bound. For bounded reads, check the opened file with `fstat` for regular-file type, current ownership and private mode; retain no-follow protection; reject an oversized `st_size` and read at most `bound + 1` bytes before parsing. Keep the unbounded default for existing request and status callers. Declare a shared 1 MiB lane-response bound.
2. [src/otto/portfolio/client_lanes.py:29](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/client_lanes.py:29) → Use that shared reader and bound for client lane records, preserving the current 1 MiB behavior.
3. [src/otto/hostctl/service.py:381](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:381) → Read each manager response through the bounded reader. Only an absent response stays pending. For invalid JSON, a non-object, an unsafe file or an over-bound reply, answer the **original lane token** with a small `unknown`, `retry: false` diagnostic. Include both the original and manager request IDs, the retained manager response path, and `summary_availability.state: "detail-required"`. Do not infer manager effects or alter the manager response file.
4. [src/otto/hostctl/service.py:388](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:388) → Continue forwarding a valid small object’s fields. Check the *serialized lane reply* against the bound before writing; use the same detail-required reference if metadata expansion makes it too large. Contain ordinary read, projection, response-write and publication failures per relay so later relays still poll. Remove a relay from memory only after its host-lane response is written. Never submit the manager command from this path.

The inherited poll covers [ProjectOwnerService.poll at project_service.py:91](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/project_service.py:91); it needs no separate reader.

## 2. Failing test to write first

New `tests/test_hostctl_relay_safe.py`, `test_retained_reply_failures_are_finite_in_the_embedded_poll`. It uses the real `ProjectOwnerService.poll` and `ExecutionHost._status_read` methods, without starting an owner or patching a product method.

```python
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from otto.hostctl import lanes
from otto.hostctl.project_service import ProjectOwnerService
from otto.hostctl.service import status_path
from otto.portfolio.execution_host import ExecutionHost


class RelaySafetyTests(unittest.TestCase):
    def test_retained_reply_failures_are_finite_in_the_embedded_poll(self):
        cases = (
            ("array", b'["not an object"]\n', 0o600),
            ("public file", b'{"outcome":"succeeded"}\n', 0o644),
            ("oversize", b'{"outcome":"succeeded","payload":"'
             + b"x" * 1_048_576 + b'"}\n', 0o600),
        )
        for label, raw, mode in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    home = Path(directory)
                    lane = lanes.private_dir(home / "host-lane")
                    ipc = lanes.private_dir(home / "manager-ipc")
                    host = ExecutionHost(
                        directory=ipc, handler=lambda _request: {},
                        bounded_transports=True)
                    host._owner_thread = threading.get_ident()
                    router = SimpleNamespace(host=host, store=object(), services={})
                    config = {
                        "home": str(home), "max_active_manager_turns": 3,
                        "owner": {"actor": "owner"},
                        "store": {"authority": "test",
                                  "domain_descriptor_digest": "digest"},
                        "hosts": {"supervisor": {"lane": str(lane)}},
                    }
                    service = ProjectOwnerService(config, router=router)

                    outer, inner = "a" * 32, "b" * 32
                    good_outer, good_inner = "c" * 32, "d" * 32
                    for client_id, manager_id in (
                        (outer, inner), (good_outer, good_inner)
                    ):
                        lanes.submit(
                            lane, {"command": "orchestrator", "args": {}},
                            token=client_id)
                        lanes.mark_pending(
                            lane, client_id, "relayed",
                            manager_token=manager_id, ipc=str(ipc),
                            command="manager-continue")
                        lanes.submit(
                            ipc, {"command": "manager-continue"},
                            token=manager_id)

                    original_request = lane / f"request-{outer}.json"
                    manager_request = ipc / f"request-{inner}.json"
                    original_bytes = original_request.read_bytes()
                    manager_bytes = manager_request.read_bytes()
                    response = ipc / f"response-{inner}.json"
                    response.write_bytes(raw)
                    response.chmod(mode)
                    lanes.atomic_json(
                        ipc / f"response-{good_inner}.json",
                        {"outcome": "succeeded", "marker": "intact"})

                    service.poll()

                    bad_lane_response = lane / f"response-{outer}.json"
                    wire = bad_lane_response.read_bytes()
                    self.assertLess(len(wire), 4096)
                    reply = json.loads(wire)
                    self.assertEqual(reply["outcome"], "unknown")
                    self.assertIs(reply["retry"], False)
                    self.assertEqual(reply["request_id"], outer)
                    self.assertEqual(
                        reply["relayed"]["original_request_id"], outer)
                    self.assertEqual(
                        reply["relayed"]["manager_request_id"], inner)
                    self.assertEqual(
                        reply["retained_response"]["path"], str(response))
                    self.assertEqual(
                        reply["summary_availability"]["state"],
                        "detail-required")

                    good = lanes.read_private_json(
                        lane / f"response-{good_outer}.json")
                    self.assertEqual(good["outcome"], "succeeded")
                    self.assertEqual(good["marker"], "intact")
                    self.assertEqual(
                        json.loads(status_path(home).read_text())["state"],
                        "serving")
                    self.assertEqual(response.read_bytes(), raw)
                    self.assertEqual(original_request.read_bytes(), original_bytes)
                    self.assertEqual(manager_request.read_bytes(), manager_bytes)

                    service.poll()
                    self.assertEqual(bad_lane_response.read_bytes(), wire)
                    self.assertEqual(
                        {p.name for p in ipc.glob("request-*.json")},
                        {f"request-{inner}.json",
                         f"request-{good_inner}.json"})
```

## 3. Delete

Delete the raw `json.loads(response.read_text())` path at `service.py:385` and the duplicate private JSON reader implementation at `portfolio/client_lanes.py:74–89`. Keep the original manager response and request files.

## 4. Plausible mistake

Catching the array’s `TypeError` while still accepting a public file or forwarding a large body would leave the poll unsafe. The three cases require finite diagnostics, and the healthy relay in each case proves one bad reply does not block the next. The byte-read ceiling also needs code review: a finite output alone cannot prove the input was read with a bound.

## 5. Existing test expectations

None identified on `canon/main`; no existing assertion needs a D19 decision. The small successful relay checked in `tests/test_hostctl_serve.py:406–428` should keep its payload fields.

## 6. Row corrections

`execution_host.py:2103–2104` is the wait loop; the `idle_poll()` call is at [line 2105](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:2105). The raw reader is solely at `service.py:385`. `project_service.py:102` calls that inherited relay poll when dispatch is open. This was a read-only design review; no tests were run.