import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from otto.hostctl import lanes
from otto.hostctl.cli import _await
from otto.hostctl.project_service import ProjectOwnerService
from otto.hostctl.service import owner_lane, read_status, status_path


class SerializedHost:
    """Disposable owner queue: every canonical operation has one thread."""

    bounded_transports = True
    manager_turn_limit = 3

    def __init__(self, home):
        self.directory = Path(home) / 'shared-ipc'
        self.directory.mkdir()
        self._executions = {}
        self._capacity_holds = {}
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self.owner_thread = None
        self.operation_threads = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        while self.owner_thread is None:
            time.sleep(.001)

    def _serve(self):
        self.owner_thread = threading.get_ident()
        while not self._stop.is_set():
            try:
                operation, done, result = self._queue.get(timeout=.01)
            except queue.Empty:
                continue
            self.operation_threads.append(threading.get_ident())
            try:
                result['value'] = operation()
            except BaseException as exc:  # pass through to the caller
                result['error'] = exc
            finally:
                done.set()

    def _status_read(self, request, operation):
        if threading.get_ident() == self.owner_thread:
            self.operation_threads.append(threading.get_ident())
            return operation()
        done, result = threading.Event(), {}
        self._queue.put((operation, done, result))
        if not done.wait(10):
            raise TimeoutError(request)
        if 'error' in result:
            raise result['error']
        return result['value']

    def enqueue(self, operation):
        done, result = threading.Event(), {}
        self._queue.put((operation, done, result))
        return done, result

    def close(self):
        self._stop.set()
        self._thread.join(2)


def config_for(home):
    return {
        'home': str(home),
        'owner': {'actor': 'owner'},
        'store': {'authority': 'embedded-test', 'domain_descriptor_digest': 'digest'},
        'hosts': {},
        'max_active_manager_turns': 3,
    }


class EmbeddedHeartbeatTests(unittest.TestCase):
    def make_service(self):
        directory = tempfile.TemporaryDirectory()
        home = Path(directory.name)
        host = SerializedHost(home)
        router = SimpleNamespace(host=host, store=object(), services={})
        service = ProjectOwnerService(config_for(home), router=router)
        self.addCleanup(host.close)
        self.addCleanup(directory.cleanup)
        return service, host

    def test_pulse_keeps_status_running_while_owner_is_blocked(self):
        service, host = self.make_service()
        original_status = service._status

        def owner_only_status(*args, **kwargs):
            self.assertEqual(threading.get_ident(), host.owner_thread)
            return original_status(*args, **kwargs)

        service._status = owner_only_status
        service.start_heartbeat()
        path = status_path(service.home)
        first = json.loads(path.read_text())

        entered, release = threading.Event(), threading.Event()

        def blocked():
            entered.set()
            self.assertTrue(release.wait(12))

        done, result = host.enqueue(blocked)
        self.assertTrue(entered.wait(2))
        # The production read_status gate is 3*1+2 seconds.  Hold the
        # serialized owner beyond five seconds so the regression is real.
        time.sleep(5.2)
        current = json.loads(path.read_text())
        self.assertNotEqual(first['heartbeat_at'], current['heartbeat_at'])
        self.assertEqual(first['projection_at'], current['projection_at'])
        self.assertEqual(first['generation'], current['generation'])
        self.assertEqual(first['holder'], current['holder'])
        self.assertEqual(read_status(path)['outcome'], 'running')

        received = {}

        def request():
            received['value'] = _await(owner_lane(service.home), {'command': 'status'}, 5)

        waiter = threading.Thread(target=request)
        waiter.start()
        lane = owner_lane(service.home)
        deadline = time.time() + 2
        while time.time() < deadline and len(list(lanes.requests(lane))) != 1:
            time.sleep(.005)
        self.assertEqual(len(list(lanes.requests(lane))), 1)

        release.set()
        poll_done, poll_result = host.enqueue(service.poll)
        self.assertTrue(done.wait(2))
        self.assertTrue(poll_done.wait(2))
        if 'error' in result:
            raise result['error']
        waiter.join(2)
        self.assertFalse(waiter.is_alive())
        if 'error' in poll_result:
            raise poll_result['error']
        self.assertEqual(received['value']['outcome'], 'serving')
        self.assertEqual(len(list(lanes.requests(lane))), 0)
        self.assertEqual(set(host.operation_threads), {host.owner_thread})
        service.close()

    def test_close_joins_pulse_and_dead_holder_is_stale(self):
        service, host = self.make_service()
        service.start_heartbeat()
        service.close()
        closed = json.loads(status_path(service.home).read_text())
        self.assertEqual(closed['state'], 'closed')
        self.assertFalse(service._heartbeat_thread.is_alive())
        time.sleep(.1)
        service._publish(state='serving')
        self.assertEqual(json.loads(status_path(service.home).read_text())['state'], 'closed')
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            service.start_heartbeat()

        result = _await(owner_lane(service.home), {'command': 'status'}, .1)
        self.assertEqual(result['outcome'], 'unavailable')
        self.assertEqual(len(list(lanes.requests(owner_lane(service.home)))), 0)

        dead = dict(closed)
        dead['state'] = 'serving'
        dead['holder'] = {**dead['holder'], 'pid': 2147483647}
        lanes.atomic_json(status_path(service.home), dead)
        self.assertEqual(read_status(status_path(service.home))['outcome'], 'stale')
        result = _await(owner_lane(service.home), {'command': 'status'}, .1)
        self.assertEqual(result['outcome'], 'unavailable')
        self.assertEqual(len(list(lanes.requests(owner_lane(service.home)))), 0)

    def test_two_phase_shutdown_keeps_admitted_capture_live_until_host_and_store_release(self):
        service, host = self.make_service()
        service.start_heartbeat()
        initial = json.loads(status_path(service.home).read_text())
        projection_at = initial["projection_at"]
        service._remember_and_publish({**initial, "manager_turn_active": True,
            "manager_turns": {"active": 1, "active_projects": ["fixture-project"]},
            "native_capacity": {"active_or_uncertain": 1, "holds": ["unknown-worker-hold"]},
            "in_flight": {"lane_requests": [{"token": "retained"}], "relays": []},
            "store_open_count": 1}, service._heartbeat_paths)
        entered, release = threading.Event(), threading.Event()
        captured = {}

        def admitted_capture():
            entered.set()
            self.assertTrue(release.wait(3))
            captured.update({"whoami": "current-owner", "report": "retained-read", "finish": "pending"})
            return captured

        capture_done, capture_result = host.enqueue(admitted_capture)
        self.assertTrue(entered.wait(2))
        service.begin_draining()
        draining = json.loads(status_path(service.home).read_text())
        self.assertEqual(draining["state"], "draining")
        self.assertEqual(draining["shutdown_phase"], "draining")
        status = read_status(status_path(service.home))
        self.assertEqual(status["outcome"], "draining")
        self.assertTrue(status["busy"])

        # Simulate an owner projection racing with the draining publication;
        # it must keep the immutable basis and phase while heartbeat continues.
        service._remember_and_publish({**draining, "projection_at": "late-owner-projection"},
                                      service._heartbeat_paths)
        reread = json.loads(status_path(service.home).read_text())
        self.assertEqual(reread["projection_at"], projection_at)
        self.assertEqual(reread["state"], "draining")
        self.assertEqual(reread["shutdown_phase"], "draining")

        release.set()
        self.assertTrue(capture_done.wait(2))
        if "error" in capture_result:
            raise capture_result["error"]
        self.assertEqual(capture_result["value"], {"whoami": "current-owner", "report": "retained-read", "finish": "pending"})
        host.close()  # Synthetic serialized host release, after the admitted capture settled.
        store_released = threading.Event()  # Synthetic Store release; no Store is opened by this fixture.
        store_released.set()
        self.assertTrue(store_released.is_set())

        def forbidden_dead_queue_read(*args, **kwargs):
            raise AssertionError("finalization must not read the released owner queue")

        service.shared_host._status_read = forbidden_dead_queue_read
        service.finalize_closed()
        closed = json.loads(status_path(service.home).read_text())
        self.assertEqual(closed["state"], "closed")
        self.assertEqual(closed["shutdown_phase"], "closed")
        self.assertEqual(closed["closure_provenance"], "host-and-store-released")
        self.assertEqual(closed["projection_at"], projection_at)
        self.assertTrue(closed["closed_at"])
        self.assertEqual(closed["store_open_count"], 0)
        self.assertIs(closed["store_closed"], True)
        self.assertEqual(closed["post_projection_liveness"], "unobserved_after_host_and_store_release")
        self.assertEqual(closed["last_projection"]["native_capacity"]["holds"], ["unknown-worker-hold"])
        self.assertEqual(closed["last_projection"]["manager_turns"]["active"], 1)
        self.assertEqual(closed["last_projection"]["in_flight"]["lane_requests"][0]["token"], "retained")
        self.assertNotIn("native_capacity", closed)
        self.assertNotIn("manager_turn_active", closed)
        self.assertNotIn("in_flight", closed)
        self.assertFalse(service._heartbeat_thread.is_alive())


if __name__ == '__main__':
    unittest.main()
