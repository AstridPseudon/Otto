## 1. Design, in implementation order

1. `src/otto/portfolio/manager_journey_client.py:506–512` → Give `route`’s task, principal, route, focus, and schedule ID arguments `default=argparse.SUPPRESS`. Reroute then sends exactly its four required values; retry sends only its schedule ID. Keep the service’s exact field sets at `manager_journey_service.py:361–377`, which reject missing and extra fields.

2. `src/otto/portfolio/manager_journey_client.py:538–543` → Suppress absent execution-control schedule ID, request key, and expected version. Add the service’s existing general-recovery inputs—`--expected-due-sha256`, `--expected-unknown-result-sha256`, and `--reason`—with suppressed defaults. Keep `operation=read` as the default.

3. `src/otto/portfolio/manager_journey_service.py:1568–1592` → Treat recovery evidence or a request key as a general-recovery request **only for `recover`**. An ordinary `recover --schedule-id` follows the existing reconciliation path; a partial general-recovery request still fails its required-field check. Other operations still reject mutation fields. Keep the unknown-field check at `:1499–1501` and the owner-known/project checks at `:1545–1558`.

4. `src/otto/portfolio/manager_journey_service.py:371–376` and `:725–761` → Before `route retry` delegates to resume, apply the same native-caller resume authorization. `route retry` must not bypass the bounded host’s retained-start fence. `src/otto/portfolio/execution_host.py:179–185` → classify that retry alias as retained, as direct execution-control resume already is. Reuse `_execution_control`; add no second recovery runner.

The shared parser already feeds both launched `run_launched` (`manager_client.py:69–90`) and the orchestrator client (`hostctl/cli.py:997–1003`), so neither forwarding function needs a separate null filter.

## 2. Failing test to write first

Add to `ManagerJourneyServiceTests` in `tests/test_manager_journey_service.py`. It uses the fixture’s model provider, the real parser/client/socket/host/service path, and a host-issued manager binding; it patches no product method.

```python
def test_cliargs_launched_manager_sends_exact_operation_fields(self):
    from otto.hostctl.manager_client import run_launched
    from otto.portfolio.identity_context import HostCallerBinding

    self.install_candidate()
    self.host.close()
    service = self.host.handler
    f, state = self.fixture, self.server.state
    binding = HostCallerBinding(
        actor=f.binding.authenticated_actor(state["manager"]),
        assignment_ref=ResourceRef.from_dict(state["assignment_ref"]),
        generation=state["manager_generation"],
        adapter=f.app.native_adapter_identity(),
        native_session_id="manager-session",
        schedule_id=self.anchor,
    )
    socket_path = self.directory / "caller.sock"
    self.host = ExecutionHost(
        directory=self.directory,
        handler=service,
        owner_path=self.directory / "manager-status-owner.json",
        socket_path=socket_path,
        caller_binding_reader=lambda ingress: binding
            if ingress.transport == "unix-socket" else None,
        caller_context_resolver=f.app.caller_context,
    )
    service.host = self.host
    self.host.start()
    env = {"OTTO_CALLER_SOCKET": str(socket_path)}

    def command(*argv):
        return run_launched(list(argv), env)

    read = command("execution-control", "--operation", "read",
                   "--schedule-id", self.anchor)
    self.assertEqual(read["outcome"], "read", read)
    self.assertEqual(read["occurrence"]["schedule_id"], self.anchor)
    self.assertEqual(read["caller_context"]["principal"], state["manager"])

    calls = len(f.provider.calls)
    for argv in (
        ("execution-control", "--operation", "recover",
         "--schedule-id", self.anchor),
        ("execution-control", "--operation", "resume",
         "--schedule-id", self.anchor),
        ("route", "--operation", "retry", "--schedule-id", self.anchor),
    ):
        with self.subTest(argv=argv):
            result = command(*argv)
            self.assertIn(result["outcome"], {"succeeded", "replayed"}, result)
    self.assertEqual(len(f.provider.calls), calls)

    f.provider.work_release.set()
    routed = command("route", "--operation", "reroute", "--task", "J01",
                     "--principal", "worker", "--route", "xhard",
                     "--focus", "Inspect the bounded J01 seam")
    self.assertEqual(routed["outcome"], "admitted", routed)
    worker = command("execution-control", "--operation", "read",
                     "--schedule-id", routed["schedule_id"])
    self.assertEqual(worker["occurrence"]["schedule_id"],
                     routed["schedule_id"])

    missing = command("route", "--operation", "reroute", "--task", "J01")
    self.assertEqual(missing["error"], "ValueError", missing)
    partial = command("execution-control", "--operation", "recover",
                      "--schedule-id", self.anchor, "--request-key", "partial")
    self.assertEqual(partial["error"], "ValueError", partial)
    foreign = command("execution-control", "--operation", "read",
                      "--schedule-id", "foreign-schedule")
    self.assertEqual(foreign["error"], "PermissionError", foreign)
    with self.assertRaises(SystemExit):
        command("execution-control", "--schedule-id", self.anchor,
                "--foreign-field", "x")
```

The worker should also add a focused bounded-host assertion that `route retry` and direct resume receive the same permission refusal; the test above uses the unbounded fixture to exercise their reconciliation readback.

## 3. What to delete

Delete the implicit `None` entries from these two parser command shapes by suppressing their defaults. Do not add a parallel client-side validator or recovery path. No existing product function needs deletion.

## 4. Plausible mistake

Filtering `None` only in `run_launched` fixes the launched manager while leaving the orchestrator’s shared parser path broken. Fixing only the service would still forward irrelevant fields. The test catches the launched failure; the existing parser-to-service continuity test exercises the other parser use. It also catches treating an omitted request key as general recovery and accidentally dropping an explicitly supplied, incomplete recovery request.

## 5. Existing expectations and D19

**No existing assertion needs to change.** In particular, `src/otto/portfolio/tests/test_execution_continuity.py:127–157` already expects parsed read, stop, recover, resume, drain, and foreign-schedule refusal; those expectations are consistent with this design. If implementation changes or removes an existing assertion, the worker must write its D19 decision.

## 6. Stale or incorrect row detail

On `canon/main`, direct native `execution-control resume` is deliberately refused by bounded transports (`manager_journey_service.py:754–761`), while `route retry` currently delegates to resume without that same check (`:371–376`). Thus “valid resume reaches its effect” cannot apply to a currently running bounded native manager; its authorized retained owner path must perform the start. The parser also does not yet expose the three general worker-recovery evidence fields that the service accepts.

This is a read-only design review; I did not run tests or change files.