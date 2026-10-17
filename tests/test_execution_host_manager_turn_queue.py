"""No-socket regression for queued manager admission versus the shared lock."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import authoring_stamp
from herzchen.fleet.tools.tokens import TokenBook
from otto.hostctl.product_service import bind_automatic_dispatch
from otto.portfolio.execution_host import ExecutionHost


class ManagerTurnQueueTests(unittest.TestCase):
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
