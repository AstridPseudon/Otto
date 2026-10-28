## Design

1. [tests/test_compose.py:323](${TRANSFER_ROOT}/source/otto/tests/test_compose.py:323) → Add the regression test below to `CloseTests` first. It pauses the filesystem replacement, verifies that the product owner still serves a request, then checks the published draining and closed statuses. Its waits are hang guards, not timing assertions.
2. [src/otto/hostctl/cli.py:906](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:906) → Import `lanes` locally. At lines 915–916, replace `path.write_text(...)` and `os.chmod(...)` with `lanes.atomic_json(path, {"requested_at": ..., **closure})`. Keep the current whitespace normalization and response shape. [lanes.py:51](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/lanes.py:51) already writes a 0600 temporary file in the destination directory, flushes and fsyncs it, then calls `os.replace`.

### Failing test to write first

File: `tests/test_compose.py`, class `CloseTests`  
Name: `test_stop_is_complete_at_publication_and_reaches_draining_and_closed`

```python
def test_stop_is_complete_at_publication_and_reaches_draining_and_closed(self):
    from otto.hostctl.cli import cmd_service_stop

    self._prepared()
    events, owner_thread = self._product()
    self._ready_doc(events)

    marker = stop_marker(Path(self.home))
    status_file = status_path(Path(self.home))
    closure = {"reason": "planned upgrade", "expected_return": "10 minutes"}
    self.assertFalse(marker.exists())

    entered = threading.Event()
    release = threading.Event()
    temporary = []
    published = []
    result = {}
    real_replace = os.replace

    def replace(source, destination):
        destination = Path(destination)
        if destination == marker:
            temporary.append(Path(source))
            entered.set()
            if not release.wait(60):
                raise AssertionError("stop publication was never released")
        real_replace(source, destination)
        if destination == status_file:
            value = read_status(status_file)
            if value["outcome"] in {"draining", "closed"}:
                published.append(value)

    def request_stop():
        try:
            result["value"] = cmd_service_stop(SimpleNamespace(
                home=self.home,
                reason="  planned upgrade  ",
                expected_return="  10 minutes  "))
        except BaseException as error:
            result["error"] = error

    with mock.patch.object(os, "replace", replace):
        writer = threading.Thread(target=request_stop, daemon=True)
        writer.start()
        try:
            self.assertTrue(entered.wait(60), "stop never reached atomic replacement")
            self.assertEqual(temporary[0].parent, marker.parent)
            self.assertEqual(temporary[0].stat().st_mode & 0o777, 0o600)
            prepared = json.loads(temporary[0].read_text())
            self.assertTrue(prepared["requested_at"])
            self.assertEqual({key: prepared[key] for key in closure}, closure)

            self.assertFalse(marker.exists())
            self.assertTrue(owner_thread.is_alive())
            self.assertEqual(read_status(status_file)["outcome"], "running")
            code, reply = self._ottoctl(
                "help", "read", "--project", "demo-run")
            self.assertEqual(code, 0, reply)
            self.assertEqual(reply["relayed"]["command"], "read-help")
        finally:
            release.set()
            writer.join(timeout=60)

        self.assertFalse(writer.is_alive())
        self.assertNotIn("error", result, result)
        owner_thread.join(timeout=60)

    self.assertFalse(owner_thread.is_alive())
    self.assertEqual(result["value"]["closure"], closure)
    self.assertEqual(
        {key: json.loads(marker.read_text())[key] for key in closure},
        closure)
    self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
    self.assertEqual(list(marker.parent.glob(".service-stop.*.tmp")), [])

    for phase in ("draining", "closed"):
        matches = [value for value in published if value["outcome"] == phase]
        self.assertTrue(matches, published)
        self.assertEqual(matches[-1]["closure"], closure)
    self.assertEqual(read_status(status_file)["closure"], closure)
    self.assertEqual(self.product_result["value"]["closure"], closure)
```

The test intercepts `os.replace`, a filesystem boundary; it does not patch a product method.

## Delete

Delete the direct final-path write and subsequent chmod at `cli.py:915–916`. Add no stop-specific publication helper.

## Mistake the test catches

A tempting implementation creates the final marker as a placeholder, then prepares and replaces it. While replacement is paused, the owner would see that marker and start stopping; the test requires the marker to be absent and a routed `help read` request to succeed. It also catches an incomplete or nonprivate temporary file and either closure field missing from draining or closed status.

## Existing expectations and D19

No existing assertion needs to change, so no D19 assertion-change decision is needed. The exact run-directory expectation at `tests/test_compose.py:486` remains valid: successful atomic publication leaves the same final marker and no temporary file.

## Row qualification

The cited stop and draining lines are current on `canon/main`. The acceptance describes a **fresh** stop while the product owner is serving. A repeated stop after draining has begun cannot satisfy “keeps serving”; the cached draining explanation may already have been chosen. The legacy `OwnerService.run` also has a closed status but no draining status. Atomic replacement addresses the stated create-before-write race; it does not resolve a separate race with startup’s stale-marker removal at `product_service.py:1216–1220`.