## 1. Design, in implementation order

1. [execution_host.py:2079](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:2079) → Keep `begin_drain()` as the prompt admission fence. Let the owner pump settle the queue; `begin_drain()` must not join or resolve completions from another thread.
2. [execution_host.py:894](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:894) → On each pump, if closing, remove every **nonrunning** job from `_executions` and resolve its completion once with `outcome: held`, `provider_called: false`, `effects_started: false`, `retry: false`, and an instruction to start the same prepared occurrence explicitly after restart. Leave running jobs to their existing finish path.
3. [execution_host.py:911](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:911) → Close the drain race after admission recheck: under `_lock`, check `_closing` before marking a job started. If drain won after `ensure_turn`, use the existing pre-operation release path and return the held result. Make the final `_closing` check and `operation_started` transition atomic under that lock.
4. [execution_host.py:1212](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1212) and [execution_host.py:1602](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1602) → Keep the existing completion callbacks: they publish one socket or file response. The prepared Due remains recoverable; an authenticated socket intent remains retained. Recovery uses a **new explicit start** of that Due, never automatic socket replay.

## 2. Failing test to write first

Add this test to `AdmittedDrainTests` in [test_admitted_transport_drain.py:27](${TRANSFER_ROOT}/source/otto/tests/test_admitted_transport_drain.py:27). Add the imports shown. It uses a real `ExecutionHost`, Unix socket, and one-slot pool; the model effect and durable Due reader are test stand-ins. Its waits have no duration threshold: the current bug hangs.

```python
import json
import socket
from herzchen.contracts import AuthenticatedActor
from otto.portfolio.execution_host import CapacityPolicy
from otto.portfolio.identity_context import HostCallerBinding

def test_drain_answers_queued_socket_and_preserves_prepared_due(self):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        project_ref = ResourceRef("fixture", "work.project", "project", "p1").to_dict()
        task_ref = ResourceRef("fixture", "work.task", "task", "t1").to_dict()
        payload = {"project_ref": project_ref, "dependencies": []}
        payload["metadata_namespaces"] = {
            "work.admission": authoring_stamp("t0", payload, "fixture")}
        task = SimpleNamespace(ref=ResourceRef.from_dict(task_ref), payload=payload)
        project = SimpleNamespace(
            ref=ResourceRef.from_dict(project_ref), payload={"dependencies": []})

        class Reader:
            def get_record(self, ref):
                return {"work.task": task, "work.project": project}.get(ref.kind)

        operations = SimpleNamespace(
            _owner_reader=Reader(), port=SimpleNamespace(list=lambda **kw: []),
            dependency_owner_actor=None)
        apps = {}
        for name in ("first", "second"):
            due = Due(
                schedule_id=name, project_ref="project", role="worker",
                target={**{"project_ref": project_ref, "task_ref": task_ref},
                        "native_id": "native-" + name},
                host_evidence={},
                assignment_ref=ResourceRef(
                    "fixture", "wrk.assignment", name, "r1").to_dict())
            path = root / (name + ".json")
            path.write_text(json.dumps(due.__dict__))
            apps[name] = SimpleNamespace(
                runtime=SimpleNamespace(adapter=SimpleNamespace(
                    owner_transport_only=True, worktree=str(root / name))),
                portfolio=SimpleNamespace(operations=operations),
                binding=SimpleNamespace(authenticated_actor=lambda actor: actor),
                actor="fixture",
                _read=lambda schedule, path=path: Due(
                    **json.loads(path.read_text())),
                _current=lambda ref, generation: SimpleNamespace(
                    ref=ResourceRef.from_dict(ref)))

        binding = HostCallerBinding(
            AuthenticatedActor("fixture", "caller", "credential"),
            ResourceRef("fixture", "wrk.assignment", "caller", "r1"),
            1, "fixture-adapter", "native-caller", "caller-schedule")
        context = {
            "principal": "caller", "generation": 1,
            "assignment_ref": binding.assignment_ref.to_dict(),
            "project_ref": project_ref,
            "native_session": {"id": "native-caller"}}
        first_started = threading.Event()
        queued = threading.Event()
        release = threading.Event()
        calls = {"first": 0, "second": 0}
        socket_path = root / "owner.sock"

        def effect(name):
            calls[name] += 1
            if name == "first":
                first_started.set()
                release.wait()
            return {"outcome": "succeeded"}

        def handler(request):
            name = request["schedule_id"]
            result = host.admit_execution(
                apps[name], apps[name]._read(name),
                lambda name=name: ExecutionHost.adapter_transport(
                    lambda: effect(name)))
            if name == "second":
                queued.set()
            return result

        def make_host():
            return ExecutionHost(
                directory=root / "ipc", socket_path=socket_path,
                handler=handler, bounded_transports=True,
                capacity_policy=CapacityPolicy(
                    turn_units=1, manager_reserve=0,
                    heavy_headroom=1, worker_floor=1),
                caller_binding_reader=lambda ingress: binding,
                caller_context_resolver=lambda caller: context,
                caller_authorizer=lambda caller, request: True)

        def call(token, name):
            request = {
                "command": "owner-execution", "operation": "start-prepared",
                "schedule_id": name, "transport_request_id": token}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(socket_path))
                client.sendall(json.dumps(request).encode() + b"\n")
                client.shutdown(socket.SHUT_WR)
                data = bytearray()
                while part := client.recv(65536):
                    data.extend(part)
            return json.loads(data)

        host = make_host()
        host.start()
        replies = {}
        first = threading.Thread(
            target=lambda: replies.setdefault("first", call("1" * 32, "first")))
        first.start()
        first_started.wait()
        second = threading.Thread(
            target=lambda: replies.setdefault("second", call("2" * 32, "second")))
        second.start()
        queued.wait()
        self.assertFalse(host._owner_request(
            lambda: host._executions["second"]["running"]))

        host.begin_drain()
        closing = threading.Thread(target=host.close)
        closing.start()
        release.set()
        closing.join()
        first.join()
        second.join()
        self.assertEqual(replies["first"]["outcome"], "succeeded")
        held = replies["second"]
        self.assertEqual(held["outcome"], "held")
        self.assertIs(held["provider_called"], False)
        self.assertIs(held["effects_started"], False)
        self.assertEqual(calls, {"first": 1, "second": 0})
        self.assertEqual(apps["second"]._read("second").host_evidence, {})

        host = make_host()
        host.start()
        self.assertEqual(call("2" * 32, "second")["outcome"], "held")
        self.assertEqual(call("3" * 32, "second")["outcome"], "succeeded")
        self.assertEqual(call("3" * 32, "second")["outcome"], "succeeded")
        self.assertEqual(calls, {"first": 1, "second": 1})
        host.close()
```

## 3. Delete

Delete the unconditional drain return and `while not self._closing` queue bypass at [execution_host.py:895](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:895). Remove settled queue entries from `_executions`. Do not delete the prepared Due or add a second scheduler.

## 4. Plausible mistake

Releasing the first slot could start the second worker despite drain, or resolving it could discard its recoverable Due. The test checks the second effect count is zero at close, its held answer has both no-effect flags, and an explicit start after restart runs it exactly once.

## 5. Existing expectations needing D19

[test_bounded_project_host.py:333](${TRANSFER_ROOT}/source/otto/tests/test_bounded_project_host.py:333) and [test_bounded_project_host.py:350](${TRANSFER_ROOT}/source/otto/tests/test_bounded_project_host.py:350) expect no response for a queued second turn after close. **D19 decision:** change these to expect its terminal drain-held response; its unattempted canonical Due and the original UNKNOWN capacity hold remain. The pre-drain `held.done == false` assertion at line 505 stays valid.

## 6. Row corrections on canon/main

Queued jobs have **no reserved turn to release** until [execution_host.py:916](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:916); drain normally releases the in-memory admission, with capacity release only for the final-check race. Line 992 resolves adapter transport, not a queued execution. Socket intents explicitly have no `request-*.json` and are never dispatched on restart ([execution_host.py:1165](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution_host.py:1165)); restart recovery means an explicit start of the same prepared Due. I did not run tests or change files.