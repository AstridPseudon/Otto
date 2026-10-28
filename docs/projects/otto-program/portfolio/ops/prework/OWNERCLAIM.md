## OWNERCLAIM design

Line numbers below are from `canon/main`.

1. [product_service.py:1426](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1426) → Acquire a nonblocking lock at a fixed path under the **home**, before `compose()` opens a Store or constructs a runner. Open it with `O_NOFOLLOW`; verify a regular file owned by this account; never unlink the lock file. Map lock contention to `WriterBusyError`, so the competing starter exits through the existing `owner_service_running` path without writing a refusal record. Hold the descriptor through host, runner, Store, and status cleanup; release it in an outer `finally`.

2. [product_service.py:1237](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1237) → Construct the runner and reconcile its records, but delete the immediate `runner_core.start()` at line 1239.

3. [runner.py:70](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/runner/runner.py:70) and [runner.py:218](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/runner/runner.py:218) → Make `pump()` inert until `start()` has enabled admission. This closes the other path: `submit()` calls `pump()` directly at line 122. Keep that immediate pumping behavior once started. A stopped, unstarted runner must leave retained queued records queued.

4. [product_service.py:49](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:49) → In `_start_owner_host`, keep `host.start()` **after** `router.install()` or `install_inert()` at lines 1349–1353. Once `host.start()` has claimed the owner file under the held home lock, start the runner only when `hold_dispatch` is false. A pre-host stop, recovery refusal, host-start refusal, or held start never starts its pump.

5. [execution_host.py:1031](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1031) → Retain its existing stale-locator inspection, eviction, exclusive owner-file creation, and socket bind inside `host.start()`. The product caller now holds the home lock across that entire sequence. Do not move request serving ahead of startup recovery.

Follow-up acceptance tests should cover held then normal restart of the same queued record, and two product starters using one home with distinct valid Stores. For the latter, preserve the first owner file’s contents/inode and socket and assert the loser never reaches composition.

## First failing test

Add to `RefusalTests` in [tests/test_compose.py:245](${TRANSFER_ROOT}/source/otto/tests/test_compose.py:245). It uses durable runner evidence and a real harmless command; it patches no product method and has no timing assertion.

```python
def test_refusal_leaves_retained_runner_queue_unlaunched(self):
    from herzchen.fleet.runner.commit import git_commit_identity
    from herzchen.fleet.runner.store import ResultStore

    self._prepared()
    repo = Path(self.home).parent / "runner-repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "seed").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "seed"], check=True)
    subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.name=owner-claim",
         "-c", "user.email=owner-claim@example.invalid",
         "commit", "-qm", "seed"],
        check=True,
    )
    commit = git_commit_identity(str(repo))
    self.assertIsNotNone(commit)

    marker = repo.parent / "runner-launched"
    argv = [sys.executable, "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"]
    results = ResultStore(Path(self.home) / "runner-results")
    results.put({
        "run_id": "retained-q", "seq": results.next_seq(),
        "binding": results.binding(argv, str(repo), commit),
        "argv": argv, "cwd": str(repo), "commit": commit,
        "task": "custody", "purpose": "retained-q", "units": 1,
        "weight_requested": 1, "max_seconds": 3600,
        "state": "queued", "outcome": None, "exit_code": None,
        "nested_in": None, "backfill": False, "submitted_at": time.time(),
        "started_at": None, "settled_at": None, "seconds": None,
        "unit_seconds": None, "tokens": 0, "custody": None,
        "output_sha256": None, "output_bytes": None,
    })

    host_dir = lanes.private_dir(Path(self.home) / "shared-host")
    lanes.submit(host_dir,
                 {"command": "start-retained-worker",
                  "schedule_id": "killed-run-handle"},
                 token=lanes.new_token())
    events, thread = self._product()
    thread.join()

    self.assertEqual(events.get()["outcome"], "startup-refused")
    self.assertEqual(self.product_result["error"].code, 78)
    self.assertEqual(results.get("retained-q")["state"], "queued")
    self.assertFalse(marker.exists())
```

Today, `Runner.start()` synchronously takes the retained record out of its queue before recovery refuses startup. Cleanup then leaves it terminal or interrupted, so the `queued` assertion fails even if the command thread never reaches the marker.

## Delete, test decisions, and stale row details

- Delete the early `runner_core.start()` call. Do not add a second owner-file claim or tie the home lock to the Store path: [store.py:1133](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/store.py:1133) locks beside each Store, while [config.py:90](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/config.py:90) permits different Store paths for one home.
- **Plausible mistake:** claiming the file and opening host intake during composition. [ProjectServices.reconcile_startup](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/project_services.py:178) requires a closed host; the new test catches early runner admission, and the existing recovery-order tests must continue to establish recovery before host intake.
- **D19:** No existing behavioral expectation needs changing. [tests/test_compose.py:170](${TRANSFER_ROOT}/source/otto/tests/test_compose.py:170) already patches product methods to collect event order, contrary to the stated test rule. Replacing those event-list assertions requires a written D19 decision naming `tests/test_compose.py`; do not silently change them.
- **Row corrections:** a pre-host stop currently reports `stopped-before-serving`, while a `host.start()` exception occurs after the startup-refusal catch and propagates after cleanup; neither is the recorded `startup-refused` path described in the row. The “nothing starts a Due” module comment at [product_service.py:9](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:9) is also misleading while the early runner start can launch retained work.