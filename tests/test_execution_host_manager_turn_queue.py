"""No-socket regression for queued manager admission versus the shared lock."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import authoring_stamp
from herzchen.fleet.tools.tokens import TokenBook
from otto.hostctl.product_service import bind_automatic_dispatch
from otto.hostctl.project_service import ProjectOwnerService
from otto.hostctl.service import OwnerService
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.owner_completion import OwnerCompletion
from otto.portfolio.project_services import ProjectServices


class ManagerTurnQueueTests(unittest.TestCase):
    def test_real_owner_start_manager_unwraps_completion_while_worker_is_admitted(self):
        """A bounded real-owner start queues cleanly behind an admitted worker."""
        from otto.hostctl.serve import HostOwnerService
        from tests.test_execution_application import ExecutionApplicationTests

        fixture = ExecutionApplicationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        app = fixture.app
        worker = app.assign_worker(**fixture.request())
        self.assertIn(worker["outcome"], {"committed", "prepared"}, worker)
        worker_due = app._read(worker["schedule_id"])

        manager_assignment, guide, mandate = fixture.role_handles("manager", "manager", "manager-session-2")
        manager = app.prepare_role(role="manager", project_ref=fixture.project.ref.to_dict(),
            task_ref=fixture.task.ref.to_dict(), assignment_ref=manager_assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="deferred-manager-start",
            instruction="Inspect current project", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session-2")
        state = {"manager": "manager", "project_ref": fixture.project.ref.to_dict(),
            "task_refs": {"J01": fixture.task.ref.to_dict()}, "assignment_ref": manager_assignment.ref.to_dict(),
            "manager_generation": 1, "schedule_id": manager["schedule_id"],
            "manager_continuation": {"schedule_id": manager["schedule_id"]},
            "requested_model": "gpt-test", "requested_reasoning": "high"}
        service = HostOwnerService.__new__(HostOwnerService)
        service.state, service.portfolio, service.due_port = state, app.portfolio, fixture.port
        service._execution = lambda **_options: app
        service._save_state = lambda: None

        host = ExecutionHost(directory=Path(fixture.temporary.name) / "manager-ipc",
            handler=lambda _request: {}, bounded_transports=True)
        worker_completion = OwnerCompletion()
        admitted = host._owned(lambda: host.admit_execution(app, worker_due, lambda: worker_completion))
        host._owned(host._start_ready_executions)
        self.assertIn(worker_due.schedule_id, host._executions,
                      {"completion_error": str(admitted.error), "failures": host.failures})
        self.assertTrue(host._executions[worker_due.schedule_id]["running"])

        fixture.provider.work_started = threading.Event()
        fixture.provider.work_release = threading.Event()
        fixture.provider.work_release.set()
        with patch("otto.portfolio.operating_setup.read_setup",
                   return_value={"roles": {"manager": manager["schedule_id"]}}):
            response = host._owned(lambda: service._start_manager({"command": "start-manager",
                "schedule_id": manager["schedule_id"]}))
        self.assertIsInstance(response, OwnerCompletion)

        worker_completion.resolve({"outcome": "succeeded", "provider_called": False})
        host._owned(host._start_ready_executions)
        deadline = time.monotonic() + 10
        while not response.done and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        self.assertTrue(response.done, "manager start did not settle after worker admission released")
        self.assertIsNone(response.error)
        self.assertIsInstance(response.value, dict)
        self.assertIn("outcome", response.value)

    def test_capacity_fence_does_not_block_activation_of_another_project(self):
        host = SimpleNamespace(_threads=[], bounded_transports=True, _executions={},
                               _capacity_holds={"worker-a": {"project": "project-a",
                                   "role": "worker", "schedule_id": "worker-a"}})
        due_port, store = object(), object()
        owner = SimpleNamespace(owner_actor="owner")

        def view(project, assignment):
            state = {"project_ref": {"authority": "fixture", "kind": "project", "id": project},
                     "assignment_ref": {"authority": "fixture", "kind": "assignment", "id": assignment},
                     "manager": project + "-manager", "manager_generation": 1}
            server = SimpleNamespace(state=state, due_port=due_port, store=store, owner=owner)
            return SimpleNamespace(host=host, server=server, workspace=Path("/tmp"),
                                   run_path=Path("/tmp") / project)

        first = view("project-a", "assignment-a")
        router = ProjectServices({"project-a": first}, host=host, due_port=due_port, store=store)
        second = view("project-b", "assignment-b")

        router.add_view("project-b", second)

        self.assertIn("worker-a", host._capacity_holds,
                      "activating an unrelated project must retain the original worker fence")
        self.assertIs(router.services["project-b"], second)

    def test_activation_queue_scopes_the_fence_to_its_project(self):
        with tempfile.TemporaryDirectory(prefix="otto-project-fence-") as temporary:
            service = ProjectOwnerService.__new__(ProjectOwnerService)
            service.shared_host = SimpleNamespace(_executions={}, _capacity_holds={
                "worker-a": {"project": "project-a", "role": "worker"}})
            service.router = SimpleNamespace(services={"project-a": SimpleNamespace(server=
                SimpleNamespace(run_id="run-a", state={"project_ref": {"id": "project-a"}}))})
            lane = Path(temporary)

            def activation(project):
                return {"command": "portfolio-operation", "args": {"command": "project",
                    "sub": "activate", "args": {"project": project}}}

            self.assertFalse(service._defer_request(lane, "owner", "project-b", activation("project-b")))
            self.assertTrue(service._defer_request(lane, "owner", "project-a", activation("project-a")))
            self.assertTrue(service._defer_request(lane, "owner", "run-a", activation("run-a")))
            self.assertTrue((lane / "pending-project-a.json").exists())

    def test_hold_during_turn_operations_remain_held_at_owner_boundary(self):
        host = SimpleNamespace(_external_waiting=1,
                               _status_read=lambda *_args: self.fail("held operation reached the host"))
        service = OwnerService.__new__(OwnerService)
        service.lock = threading.RLock()
        service.journeys = {"project-a": SimpleNamespace(execution_host=host)}
        service._dispatch_context = SimpleNamespace(project_id="project-a")
        calls = []

        result = service.call(lambda: calls.append("ran"), hold_during_turn=True)

        self.assertEqual(result["outcome"], "held")
        self.assertTrue(result["retry"])
        self.assertEqual(calls, [])

    def test_queued_turn_does_not_hold_shared_command_lock(self):
        """A full turn lane must not stop an admitted project's owner pump."""
        with tempfile.TemporaryDirectory(prefix="otto-turn-queue-") as temporary:
            root = Path(temporary)
            ipc = root / "project-b" / "manager-ipc"
            ipc.mkdir(parents=True)
            shared_lock = threading.RLock()
            slots = threading.BoundedSemaphore(1)
            self.assertTrue(slots.acquire(blocking=False), "simulate project A occupying the only turn slot")
            waiting = threading.Event()

            @contextmanager
            def admit_turn():
                waiting.set()
                slots.acquire()
                try:
                    yield
                finally:
                    slots.release()

            host = ExecutionHost(directory=ipc, handler=lambda request: {"outcome": "ok"},
                                 owner_file_compatibility=True)
            host._command_lock = shared_lock
            host.turn_admission = admit_turn
            token = "b" * 32
            (ipc / ("request-" + token + ".json")).write_text(
                json.dumps({"command": "start-manager", "schedule_id": "project-b-manager"}))

            dispatch = threading.Thread(target=host._serve_files, args=(False,), daemon=True)
            dispatch.start()
            self.assertTrue(waiting.wait(2), "project B did not reach turn admission")
            # Project A's owner pump must still be able to run a finite
            # callback while B waits for a turn slot.
            lock_available = shared_lock.acquire(timeout=0.25)
            if lock_available:
                shared_lock.release()

            slots.release()
            dispatch.join(timeout=5)
            self.assertFalse(dispatch.is_alive(), "queued manager did not resume after capacity freed")
            response_path = ipc / ("response-" + token + ".json")
            self.assertTrue(response_path.exists(), "queued manager request did not receive its response")
            response = json.loads(response_path.read_text())
            self.assertEqual(response.get("outcome"), "ok", response)
            self.assertTrue(lock_available,
                            "queued turn held the shared command lock and blocked another project's owner pump")

    def test_two_owner_pumps_racing_manager_request_admit_one_worker(self):
        with tempfile.TemporaryDirectory(prefix="otto-auto-dispatch-") as temporary:
            root = Path(temporary)
            payload = {"kind": "task", "title": "Ready task", "name": "Ready task",
                       "fields": {"instructions": "Implement the admitted task", "check": ["true"]},
                       "dependencies": [], "project_ref": {"authority": "fixture", "kind": "work.project",
                                                       "id": "project"},
                       "metadata_namespaces": {"otto.plan": {"route": "normal"}}}
            payload["metadata_namespaces"]["work.admission"] = authoring_stamp("revision", payload, "owner")
            task = SimpleNamespace(id="T01", title="Ready task",
                ref=ResourceRef("fixture", "work.task", "T01", "revision"),
                payload=payload, lifecycle="pending")
            graph = SimpleNamespace(current=lambda _ref: task,
                                    reader=SimpleNamespace(get_identity=lambda _ref: task))
            owner = SimpleNamespace(graph=graph, owner_actor=object(),
                                    store=SimpleNamespace(consumer=lambda: object()))
            host = ExecutionHost(directory=root / "ipc", handler=lambda _request: {}, bounded_transports=True)
            admissions = []
            original_admit = host.admit_execution

            def admit(app, due, operation):
                admissions.append(due.schedule_id)
                return original_admit(app, due, operation)

            host.admit_execution = admit
            state = {"task_refs": {"T01": task.ref.to_dict()}, "workers": {}}
            app = SimpleNamespace(runtime=SimpleNamespace(adapter=SimpleNamespace(
                owner_transport_only=True, worktree=str(root))),
                portfolio=SimpleNamespace(operations=SimpleNamespace()))
            registry = SimpleNamespace(owner=owner, tokens=TokenBook())

            def bind(dispatcher):
                registry.dispatcher = dispatcher
                registry.tokens = dispatcher.tokens

            registry.bind_dispatcher = bind
            auto_selected = threading.Event()

            def submit(request, *, automatic=False, automatic_revision=None):
                prior = state["workers"].get("T01")
                if prior is not None:
                    return {**prior, "outcome": "retained", "provider_called": False}
                assignment = (next(iter(registry.dispatcher.records)) if automatic else "manager-assignment")
                if automatic:
                    auto_selected.set()
                due = SimpleNamespace(schedule_id="worker-T01", project_ref="project", role="worker",
                    assignment_ref={"authority": "fixture", "kind": "wrk.assignment", "id": assignment},
                    generation=1, host_evidence={}, target={}, profile="workspace-write", host_state="ready")
                state["workers"]["T01"] = {"schedule_id": due.schedule_id,
                    "assignment_ref": due.assignment_ref, "automatic": automatic}
                host.admit_execution(app, due, lambda: {"outcome": "succeeded"})
                return {**state["workers"]["T01"], "outcome": "admitted"}

            view = SimpleNamespace(server=SimpleNamespace(state=state,
                due_port=SimpleNamespace(read_due=lambda _schedule: {"completion_state": "active"})),
                _submit_worker=submit)
            with patch("otto.portfolio.dependencies.PortfolioDependencies",
                       return_value=SimpleNamespace(readiness=lambda _ref, **_kw: {"ready": True})):
                bind_automatic_dispatch(host, registry, {"project": view})
            barrier = threading.Barrier(4)
            results = []

            def pump():
                barrier.wait()
                with host._command_lock:
                    host._owned(host._capacity_tick)

            def manager():
                barrier.wait()
                self.assertTrue(auto_selected.wait(2), "owner pump did not select the admitted task")
                with host._command_lock:
                    results.append(host._owned(lambda: submit({"command": "run-worker", "task": "T01"})))

            threads = [threading.Thread(target=pump) for _ in range(2)] + [threading.Thread(target=manager)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(admissions, ["worker-T01"])
            self.assertEqual(len(host._executions), 1)
            self.assertEqual(results[0]["schedule_id"], "worker-T01")
            self.assertEqual(results[0]["outcome"], "retained")
            self.assertNotIn("routine-dispatch", host.failures)


if __name__ == "__main__":
    unittest.main()
