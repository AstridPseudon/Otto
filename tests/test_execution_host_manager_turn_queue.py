"""No-socket regression for queued manager admission versus the shared lock."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
