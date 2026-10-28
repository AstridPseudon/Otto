## SESSIONFD implementation design

All line numbers below are from `canon/main`. This is a read-only design; I did not run tests.

1. `src/herzchen/command_ports.py:583–655` → Give each generated `CommandFacade` an idempotent owner-side `close()`. Retain the exact transport handles created for its main client, reader, and nested clients; close children before the main transport through `close_consumer_facade`. Clean up handles created before a constructor failure. Do not find services by scanning the process-wide registry: that could close another principal’s service.
2. `src/otto/portfolio/owner_bootstrap.py:601–626,676–756` → Track and close every facade the bootstrap owns, including orchestration, the create/open bridge, and the lazy direction and late-usage facades at `:838–889`. Keep the orchestration and late-usage *facade objects*, not only their ports, so their nested transports can close. Make `PortfolioOwnerBootstrap.close()` idempotent and close its facades in reverse construction order. It must not close the Store.
3. `src/otto/hostctl/owner.py:175–180,203–245` → Initialize `self.owner` before entry. Call its single `close()` from both failed-entry cleanup and `__exit__`, before closing an owned Store. Close the bootstrap even when `_SERVICE_STORE` supplied a shared Store; leave that Store under the resident owner’s custody.
4. `src/otto/portfolio/owner_bootstrap.py:681,1012–1077` and `src/otto/portfolio/manager_assessment_command.py:64–73,163` → Reuse the bootstrap’s existing owner-scoped limit facade. Keep manager assessment bound to the **current manager actor, task, assignment, and generation**. Make its assessment facade request-owned and close it after execution, including error paths; update its production callers at `manager_assessment_command.py:19–30`, `manager_journey_command.py:665`, `hostctl/fleet_landing.py:216`, and `owner_bootstrap.py:1088,1367`. Do not cache a manager assessment across requests or principals.
5. `src/otto/hostctl/cli.py:532–535,570–591`, `src/otto/portfolio/manager_journey_service.py:646–669`, `src/otto/hostctl/serve.py:411–434`, and `src/otto/portfolio/reviewed_activation.py:297–313,403–419` → Replace the repeated owner-scoped `AssessmentModule`, `ContextPacketService`, and `LimitService` constructions with facades owned by the current bootstrap or resident view. Pass the actor for each read as today. Apply the same replacement to `src/otto/portfolio/status.py:185`, `src/otto/hostctl/register.py:476,559`, and `owner_bootstrap.py:1151`. Retain the two sessions in `cmd_project_status` at `cli.py:522–524`: the second adds the project grant.
6. Add 200-call resource censuses for manager status, document reads, manager assessment execution, and reviewed-activation pool access, using the real resident owner. Check descriptors, threads, and `herzchen-command-*` directories after each series. Verify the stage 2 `--fake` run’s owner descriptor count separately.

## Failing test to write first

Add this test to `tests/test_hostctl_cli.py`, in `HostctlCliTest`. It uses its existing real resident owner fixture and patches no product method.

```python
def test_resident_project_status_retires_services_and_preserves_principals(self):
    import copy
    from otto.hostctl.owner import HostSession

    self._ready()
    fd_dir = next(
        (path for path in ("/dev/fd", "/proc/self/fd") if os.path.isdir(path)),
        None,
    )
    if fd_dir is None:
        self.skipTest("no process descriptor census is available")

    def census():
        return {
            "descriptors": len(os.listdir(fd_dir)),
            "threads": len(threading.enumerate()),
            "command_dirs": len(list(
                Path(tempfile.gettempdir()).glob("herzchen-command-*")
            )),
        }

    code, result = self._ottoctl("project", "status", "--project", "demo-run")
    self.assertEqual(code, 0, result)
    before = census()
    for _ in range(200):
        code, result = self._ottoctl(
            "project", "status", "--project", "demo-run"
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(result["outcome"], "read")
    after = census()
    for name in before:
        self.assertLessEqual(
            after[name], before[name] + 3,
            f"{name} grew from {before[name]} to {after[name]}",
        )

    def check_principals():
        config = host_config.load(Path(self.home))
        alternate = copy.deepcopy(config)
        alternate["owner"]["actor"] = "second-owner"
        with HostSession(config, project_ids=("demo-run",)) as first:
            first_transport = first.owner.graph.command_port.transport
        self.assertFalse(os.path.exists(first_transport.socket_path))
        with HostSession(alternate, project_ids=("different-project",)) as second:
            self.assertEqual(second.owner.owner_actor.actor, "second-owner")
            self.assertEqual(
                second.owner.project_read_grant.project_ids,
                ("different-project",),
            )
            self.assertNotEqual(
                second.owner.graph.command_port.transport.session_id,
                first_transport.session_id,
            )

    self.owner_service.call(check_principals)
```

## Delete

Delete the duplicate per-call facade constructions identified in step 5 and their now-unused imports. Keep the two-session status flow and the process-exit cleanup fallback.

A tempting shortcut is to cache one bootstrap for all `HostSession`s. The resource census could pass with that change, but the test’s second half would fail: the second session must have its own actor, project grant, and command transport, and the first session’s socket must already be gone.

**Existing assertion changes:** none are needed. Preserve current command results; any change to an existing test assertion requires the program’s written D19 decision.

**Stale or incomplete row details:** `owner_bootstrap.py:781` activates the bridge thread when `consumer_operations()` is called, not in the bootstrap constructor. `cmd_project_status` also creates three fresh facade families at `cli.py:532–583`, beyond its two session bootstraps. Reviewed activation’s `_pool` runs during activation, rather than an ordinary read. Finally, the current stage 2 `perch.sh:460–465` “census” records process PIDs; `perch_report.py:386–415` does not measure descriptors. Its claimed descriptor item needs a separate check.