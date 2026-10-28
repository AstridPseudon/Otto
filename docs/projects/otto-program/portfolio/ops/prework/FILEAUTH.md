## 1. Design, in implementation order

1. [tests/test_bounded_project_host.py:81](${TRANSFER_ROOT}/source/otto/tests/test_bounded_project_host.py:81) → add the failing test below. It prepares B’s worker, probes the real manager write fence with A’s model stand-in, and checks A’s bound ingress before the owner starts B.
2. [src/otto/hostctl/serve.py:441](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:441) → remove the shared IPC directory from `manager_launch().write_roots` and remove `OTTO_MANAGER_IPC` from the launched environment. Keep `OTTO_CALLER_SOCKET`. Update the lane description at lines 9–17.
3. [src/otto/hostctl/manager_client.py:66](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/manager_client.py:66) → send launched `command-status` through the authenticated socket. Reject launched owner-only commands locally. Delete the launched file submission and local status-read branch at lines 76–92.
4. [src/otto/portfolio/execution_host.py:1254](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1254) → handle socket `command-status` after caller binding and authorization, using `read_command_status(..., expected_socket_scope=...)` for the exact principal, assignment, generation and project. Do this before socket intent retention. Include it in the finite read path at line 1372.
5. [src/otto/hostctl/cli.py:1090](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:1090) → recognize a launched caller through `OTTO_CALLER_SOCKET` only. Preserve the private owner file queue: `SharedLaneRelay`, `ExecutionHost.submit`, retained callbacks, and [ProjectServices’ Due-based routing](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/project_services.py:165) still serve owner custody and restart recovery.

## 2. Failing test to write first

Add `BoundedProjectHostTests.test_fenced_A_cannot_submit_B_retained_start` in `tests/test_bounded_project_host.py`. The fixture’s provider wait at lines 61–63 should become an unbounded `release.wait()` so elapsed time cannot fail this test.

```python
@unittest.skipUnless(
    sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists(),
    "real macOS manager fence",
)
def test_fenced_A_cannot_submit_B_retained_start(self):
    import subprocess
    import sys
    from otto.agents.claude_cli import MacWriteScope
    from otto.hostctl.serve import HostOwnerService
    from otto.portfolio.identity_context import HostIngress

    self.host.owner_file_compatibility = True
    a_response = self.send("A", {"command": "start-manager"})
    self.native.started.setdefault(("manager-A", 1), threading.Event()).wait()

    def prepare_b():
        raw = self.f.request()
        raw["project_ref"] = self.states["B"]["project_ref"]
        raw["task_ref"] = self.states["B"]["task_refs"]["T"]
        raw["principal"] = "worker-B"
        raw["request_key"] = "fileauth-B"
        contract = raw["instruction_contract"]
        contract["task_ref"] = raw["task_ref"]
        contract["authority"]["owner_actor"] = "worker-B"
        contract["authority"]["workspace_roots"] = [
            str(self.worker_labs[raw["task_ref"]["id"]][1])
        ]
        prepared = self.apps["B"].assign_worker(**raw)
        self.states["B"]["workers"] = {"T": {
            **prepared, "principal": "worker-B",
            "model": "gpt-test", "reasoning": "high", "automatic": True,
        }}
        return prepared

    prepared = self.host._owner_request(prepare_b)
    self.assertEqual(prepared["outcome"], "committed")
    request = {
        "command": "start-retained-worker", "task": "T",
        "principal": "worker-B", "schedule_id": prepared["schedule_id"],
    }
    self.assertEqual(self.host._owner_request(lambda:
        self.apps["B"].recover(
            schedule_id=prepared["schedule_id"], execute=False
        ))["outcome"], "prepared")

    def a_binding():
        due = self.f.port.read_due(self.states["A"]["schedule_id"])
        authorization = due["host_evidence"]["gateway_attempt"][
            "delivery_authorization"
        ]
        return self.router.managed_caller_binding(authorization)

    binding = self.host._owner_request(a_binding)
    self.host.caller_binding_reader = lambda ingress: binding
    self.host.caller_context_resolver = self.router.caller_context
    denied = self.host._dispatch(
        request, ingress=HostIngress("fixture-authenticated-native", "A")
    )
    self.assertEqual(denied["outcome"], "error", denied)
    self.assertIs(denied["effects_started"], False)

    launch_view = SimpleNamespace(
        paths={"ipc": self.directory, "socket": self.root / "caller.sock"},
        run_id="A",
    )
    launch = HostOwnerService.manager_launch(launch_view)
    state_root = self.root / "manager-native-state"
    state_root.mkdir()
    scope = MacWriteScope(
        str(self.services["A"].workspace), str(state_root),
        allow_subprocesses=True, extra_write_roots=launch["write_roots"],
    )
    self.assertTrue(scope.preflight()["verified"])
    foreign = self.directory / ("request-" + "f" * 32 + ".json")
    script = (
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text(sys.argv[2])"
    )
    probe = subprocess.run(
        scope.wrap([sys.executable, "-c", script,
                    str(foreign), json.dumps(request)]),
        capture_output=True, text=True,
    )
    self.assertNotEqual(probe.returncode, 0, probe.stdout)
    self.assertFalse(foreign.exists())
    self.assertFalse(self.native.has_started("worker-B"))

    self.native.release("manager-A")
    while not a_response.exists():
        time.sleep(.01)
    self.assertEqual(json.loads(a_response.read_text())["outcome"], "succeeded")
    owner_response = self.send("B", request)
    self.native.started.setdefault(("worker-B", 1), threading.Event()).wait()
    self.native.release("worker-B")
    while not owner_response.exists():
        time.sleep(.01)
    self.assertEqual(json.loads(owner_response.read_text())["outcome"], "succeeded")
    replay = self.send("B", request)
    while not replay.exists():
        time.sleep(.01)
    self.assertEqual(json.loads(replay.read_text())["outcome"], "replayed")
    self.assertEqual(self.native.counts["worker-B"], 1)
```

Before the fix, `manager_launch()` grants the shared directory, so the fenced write succeeds and the test fails at the probe assertion. The existing [closed-owner retained-start recovery test](${TRANSFER_ROOT}/source/otto/tests/test_retained_worker_start_recovery.py:22) remains the separate check for rearming an exact, unattempted start after restart.

## 3. Delete

Delete the launched file submission and direct file status read in `manager_client.py:76–92`, together with the manager’s shared-directory write root and `OTTO_MANAGER_IPC` environment entry in `serve.py:443–445`. The owner’s retained request files remain.

## 4. Plausible mistake

Routing a manager’s retained start through the socket would strand legitimate owner starts and callbacks. The test requires A’s authenticated attempt to fail, then requires B’s owner-file start, prepared recovery read and replay to produce exactly one worker effect. Merely moving the writable directory also fails the real fence probe.

## 5. Existing assertion change requiring D19

[tests/test_hostctl_serve.py:719–723](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_serve.py:719): the direct `run_launched` call supplied only `OTTO_MANAGER_IPC` and currently asserts a returned service refusal. It should assert a local `PermissionError` after that route is deleted. **D19 decision:** this expectation changes because launched processes no longer have a file command transport; the owner-grant refusal remains covered through the protected orchestrator relay at lines 724–729. I found no other existing assertion that needs changing.

## 6. Row accuracy on `canon/main`

The cited lines are current. [ProjectServices:165–176](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/project_services.py:165) selects a retained project from an exact Due; that selection is not submitter authentication. The foreign file submission succeeds only when B has a prepared worker tuple matching its current worker slot. The defect is the manager write grant to the shared owner directory combined with [file compatibility dispatch](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1259), which does not authenticate the file writer. This was a read-only design review; I did not run the test.