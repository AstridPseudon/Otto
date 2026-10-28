## CTLRACE design

Implement in this order, using the line numbers on `canon/main`:

1. [tests/test_host_neutral_defaults.py:202](${TRANSFER_ROOT}/source/otto/tests/test_host_neutral_defaults.py:202) → Add the deterministic regression test below first.
2. [manager_ctl.py:85](${TRANSFER_ROOT}/source/otto/manager_ctl.py:85) → Write JSON to a hidden `.request-<token>.tmp` in `IPC` with the existing exclusive, no-follow, `0600` flags. Keep the flush and `fsync`; close it, then `os.replace` it onto `request-<token>.json`. Remove the temp on failure. Leave response waiting unchanged.
3. [tests/test_host_neutral_defaults.py:212](${TRANSFER_ROOT}/source/otto/tests/test_host_neutral_defaults.py:212) → Make the existing responder poll until it sees a request, removing its five-second deadline. Keep its assertions. This makes a missing request fail by hanging, as the program’s test rule requires.
4. [src/otto/hostctl/heavy.py:345](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/heavy.py:345) and [heavy.py:381](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/heavy.py:381) → Replace both direct holder snapshot writes with the existing `lanes.atomic_json`. `_holders()` globs and parses these files at line 196; a partial update is currently silently skipped.
5. [src/otto/portfolio/execution_host.py:2212](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:2212) → Publish immutable exit receipts through a hidden, exclusive temp file, then `os.link` to the final name and remove the temp. Preserve `FileExistsError` on duplicate receipts. Resume and hostctl supervision glob and parse these receipts. Use a link here because `os.replace` would lose the existing no-overwrite rule.

After implementation, run `tests/test_host_neutral_defaults.py` 200 consecutive times, then the relevant heavy-lease and execution-continuity tests. I ran no tests under the read-only instruction.

## Failing test to write first

Add to `ManagerPortConfigTests` in [tests/test_host_neutral_defaults.py](${TRANSFER_ROOT}/source/otto/tests/test_host_neutral_defaults.py:202). It pauses the standard-library `json.dump`, not a product method. On current code, the final request name is already visible and the test fails after allowing the client to finish.

```python
    def test_request_name_appears_only_after_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = Path(directory)
            owner = ipc / "owner.json"
            owner.write_text(json.dumps({"pid": os.getpid()}))
            module = load_manager_ctl({
                "OTTO_MANAGER_IPC": str(ipc),
                "OTTO_MANAGER_SERVICE_SOCKET": str(ipc / "absent.sock"),
                "OTTO_MANAGER_STATUS_OWNER": str(owner),
            })
            entered, release = threading.Event(), threading.Event()
            original_dump = json.dump
            results, failures = [], []

            def paused_dump(value, stream, **kwargs):
                entered.set()
                release.wait()
                return original_dump(value, stream, **kwargs)

            def client_call():
                try:
                    results.append(module.call({"command": "report", "task": "A1"}))
                except BaseException as exc:
                    failures.append(exc)

            with mock.patch.object(module.json, "dump", paused_dump):
                client = threading.Thread(target=client_call)
                client.start()
                try:
                    entered.wait()
                    visible_while_writing = list(ipc.glob("request-*.json"))
                finally:
                    release.set()

                while not (published := list(ipc.glob("request-*.json"))):
                    time.sleep(.001)
                request = published[0]
                while True:
                    try:
                        payload = json.loads(request.read_text())
                        break
                    except json.JSONDecodeError:
                        time.sleep(.001)

                token = request.name[len("request-"):-len(".json")]
                staged_reply = ipc / (".response-" + token + ".tmp")
                staged_reply.write_text('{"outcome":"read"}')
                os.replace(staged_reply, ipc / ("response-" + token + ".json"))
                client.join()

            self.assertEqual(visible_while_writing, [])
            self.assertEqual(payload, {"command": "report", "task": "A1"})
            self.assertEqual(failures, [])
            self.assertEqual(results, [{"outcome": "read"}])
```

## Deletions, risk, and decisions

Delete the direct writes to the final request, holder, and exit-receipt names; delete the existing responder’s five-second deadline. No whole-file deletion is justified: `manager_ctl.py` still has direct test and installed-client references. Add no new transport helper.

A plausible mistake is to give the temp file a `request-*.json` name, or rename it before writing finishes. The paused test sees that name during serialization and fails even if a responder later succeeds.

**D19:** No existing test assertion or expected result needs to change. The responder’s polling deadline changes, but its assertions remain the same.

## Row corrections on `canon/main`

- The affected client is the repository-root [manager_ctl.py:90](${TRANSFER_ROOT}/source/otto/manager_ctl.py:90); its flags combine `O_CREAT | O_EXCL`, rather than “or.” In this fixture, the owner file keeps the `report` wait unbounded.
- [src/otto/hostctl/lanes.py:95](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/lanes.py:95) already publishes requests atomically via a hidden temp and exclusive link. Its response and pending files also use atomic publication.
- [src/herzchen/command_ports.py:464](${TRANSFER_ROOT}/source/otto/src/herzchen/command_ports.py:464) has Unix-socket transport, with no glob-read file lane. The additional glob-read writers found are the heavy holder snapshots and portfolio exit receipts above.