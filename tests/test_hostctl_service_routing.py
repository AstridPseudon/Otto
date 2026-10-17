"""In-process checks for bounded manager turns and multi-project status."""
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from otto.hostctl.service import OwnerService, with_lane_advice
from otto.portfolio.execution_host import ExecutionHost


def config(home, limit=3):
    return {"home": str(home), "max_active_manager_turns": limit,
            "owner": {"actor": "owner"},
            "store": {"authority": "test", "domain_descriptor_digest": "digest"},
            "hosts": {}}


class OwnerServiceRoutingTests(unittest.TestCase):
    def test_attach_failure_closes_unretained_host_session(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["hosts"] = {"claude-code": {"root_assignment_ref": {"id": "supervisor"}}}
            service = OwnerService(cfg)
            record = SimpleNamespace(
                payload={"metadata": {"otto_orchestrator": {"assignment_ref": {"id": "supervisor"}}}},
                ref=SimpleNamespace(id="project-1"),
            )
            # Use a real context manager for the short-lived project lookup.
            class LookupSession:
                def __enter__(self):
                    return self
                def __exit__(self, *_args):
                    return False

            class RetainedSession:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return retained_exit(*args)

            retained_exit = Mock(return_value=False)
            retained_session = RetainedSession()

            def make_session(*_args, **kwargs):
                return LookupSession() if "host" not in kwargs else retained_session

            failure = RuntimeError("attach failed")
            with patch("otto.hostctl.service.HostSession", side_effect=make_session), \
                 patch("otto.hostctl.cli._resolve_project", return_value=record), \
                 patch("otto.hostctl.serve.attach", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "attach failed"):
                    service._attach("project-1", host_kind=None)

            retained_exit.assert_called_once()
            self.assertEqual(type(failure), retained_exit.call_args.args[0])
            self.assertEqual({}, service._project_sessions)
            self.assertEqual({}, service.journeys)

    def test_nonrunning_status_explains_closure_and_owner_restart_command(self):
        status = with_lane_advice({
            "outcome": "closed", "state": "closed", "service_home": "/srv/otto",
            "closure": {"reason": "planned upgrade", "expected_return": "10 minutes"},
        }, lane="owner", service_home=Path("/srv/otto"))
        self.assertIn("planned upgrade", status["reason"])
        self.assertEqual(status["restart_command"], "ottoctl --home /srv/otto service run")
        self.assertIn(status["restart_command"], status["next_action"])

    def test_detach_refreshes_activity_and_fences_later_turn_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory))
            drained = threading.Event()
            ipc = Path(directory) / 'p1'
            ipc.mkdir()
            service.journeys['p1'] = SimpleNamespace(
                run_id='run-p1', state={'manager': 'manager-p1'},
                paths={'ipc': ipc, 'socket': Path(directory) / 'p1.sock'},
                execution_host=SimpleNamespace(begin_drain=drained.set))
            args = SimpleNamespace(service_status={'manager_turns': {'active': 0}})
            def detach(namespace):
                self.assertEqual(namespace.service_status['manager_turns']['active'], 1)
                return {'outcome': 'error', 'error': {'code': 'manager_running'}}
            with service._manager_turn('p1'):
                with service.lock:
                    service._run_operation(detach, args, ('project', 'detach'))
            self.assertFalse(drained.is_set())
            with service.lock:
                service._run_operation(lambda ns: {'outcome': 'detached', 'project_ref': {'id': 'p1'}},
                                       args, ('project', 'detach'))
            self.assertTrue(drained.is_set())
            with self.assertRaisesRegex(RuntimeError, 'draining'):
                with service._manager_turn('p1'):
                    self.fail('detached project must not admit another turn')

    def test_mutation_hold_resolves_run_alias_to_the_correct_project(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory))
            service.journeys['canonical-id'] = SimpleNamespace(
                run_id='run-alias', execution_host=SimpleNamespace(_external_waiting=1))
            service._dispatch_context.project_id = 'run-alias'
            result = service.call(lambda: self.fail('must not mutate running project'), hold_during_turn=True)
            self.assertEqual(result['outcome'], 'held')

    def test_turn_admission_is_bounded_and_reports_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory), poll_seconds=0)
            release = threading.Event()
            entered = threading.Event()
            observed = {"active": 0, "maximum": 0}
            lock = threading.Lock()

            def turn(project_id):
                with service._manager_turn(project_id):
                    with lock:
                        observed["active"] += 1
                        observed["maximum"] = max(observed["maximum"], observed["active"])
                        if observed["active"] == 3:
                            entered.set()
                    release.wait(3)
                    with lock:
                        observed["active"] -= 1

            workers = [threading.Thread(target=turn, args=("p%d" % i,)) for i in range(5)]
            for worker in workers:
                worker.start()
            self.assertTrue(entered.wait(2), "three turns should become active")
            deadline = time.monotonic() + 2
            while service._status()["manager_turns"]["queued"] != 2 and time.monotonic() < deadline:
                time.sleep(.01)
            status = service._status()
            self.assertEqual(3, status["manager_turns"]["active"])
            self.assertEqual(2, status["manager_turns"]["queued"])
            self.assertEqual(3, status["manager_turns"]["limit"])
            release.set()
            for worker in workers:
                worker.join(4)
                self.assertFalse(worker.is_alive())
            self.assertEqual(3, observed["maximum"])

    def test_a_queued_turn_gives_up_when_its_project_drains(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory, limit=1), poll_seconds=0)
            release, holding = threading.Event(), threading.Event()
            outcome = {}

            def hold():
                with service._manager_turn("p1"):
                    holding.set()
                    release.wait(3)

            def queued():
                try:
                    with service._manager_turn("p2"):
                        outcome["started"] = True
                except RuntimeError as error:
                    outcome["refused"] = str(error)

            first = threading.Thread(target=hold)
            first.start()
            self.assertTrue(holding.wait(2))
            second = threading.Thread(target=queued)
            second.start()
            deadline = time.monotonic() + 2
            while service._status()["manager_turns"]["queued"] != 1 and time.monotonic() < deadline:
                time.sleep(.01)
            service._draining_projects.add("p2")
            second.join(2)
            self.assertFalse(second.is_alive(), "a queued turn must not block its project's drain")
            self.assertIn("draining", outcome.get("refused", ""))
            self.assertEqual(0, service._status()["manager_turns"]["queued"])
            release.set()
            first.join(2)

    def test_the_turn_limit_accepts_more_than_three_up_to_sixteen(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(16, OwnerService(config(directory, limit=16)).max_active_manager_turns)
            with self.assertRaises(ValueError):
                OwnerService(config(directory, limit=17))

    def test_status_lists_each_attached_project(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory))
            for project_id in ("p1", "p2"):
                ipc = Path(directory) / project_id
                ipc.mkdir()
                service.journeys[project_id] = SimpleNamespace(
                    run_id="run-" + project_id,
                    state={"manager": "manager-" + project_id,
                           "project_ref": {"id": project_id}},
                    paths={"ipc": ipc, "socket": Path(directory) / (project_id + ".sock")})
            service.journey = service.journeys["p1"]
            status = service._status()
            self.assertEqual(["p1", "p2"], [item["project_id"] for item in status["projects"]])
            self.assertEqual(2, len(status["attached_projects"]))
            self.assertEqual("p1", status["attached_project"]["project_id"])

    def test_queued_start_does_not_hold_shared_store_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            entered = threading.Event()
            release = threading.Event()

            @contextmanager
            def admission():
                entered.set()
                release.wait(3)
                yield

            command_lock = threading.RLock()
            host = ExecutionHost(directory=directory, handler=lambda request: {"outcome": "started"})
            host._command_lock = command_lock
            host.turn_admission = admission
            request_path = Path(directory) / ("request-" + "a" * 32 + ".json")
            request_path.write_text('{"command":"start-manager"}')
            worker = threading.Thread(target=lambda: host._serve_files(False))
            worker.start()
            self.assertTrue(entered.wait(2), "manager request should wait in admission")
            acquired = command_lock.acquire(timeout=1)
            self.assertTrue(acquired, "queued manager must not hold the shared Store lock")
            if acquired:
                command_lock.release()
            release.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertTrue((Path(directory) / ("response-" + "a" * 32 + ".json")).exists())


if __name__ == "__main__":
    unittest.main()
