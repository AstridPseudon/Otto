from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import unittest

from herzchen.adapters.host import (
    _communicate_after_native_start,
    _terminate_owned_process,
)


SESSION = "01fixture-healthy-worker"


def _process(source: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-u", "-c", source],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _started_source(after_start: str) -> str:
    events = [
        {"type": "thread.started", "thread_id": SESSION},
        {"type": "turn.started"},
    ]
    return (
        "import json,time\n"
        f"events={events!r}\n"
        "[print(json.dumps(value), flush=True) for value in events]\n"
        + after_start
    )


class HealthyWorkerLifetimeTests(unittest.TestCase):
    def test_native_started_work_continues_beyond_start_timeout(self):
        process = _process(_started_source(
            "time.sleep(0.15)\nprint(json.dumps({'type':'turn.completed'}), flush=True)\n"
        ))
        started = time.monotonic()
        stdout, stderr, exit_status, native_started = _communicate_after_native_start(
            process, "work", expected_session_id=SESSION, start_timeout_seconds=0.03,
        )
        self.assertGreaterEqual(time.monotonic() - started, 0.12)
        self.assertTrue(native_started)
        self.assertEqual(exit_status, 0)
        self.assertIn('"type": "turn.completed"', stdout)
        self.assertEqual(stderr, "")

    def test_wrong_session_does_not_end_finite_start_phase(self):
        process = _process(
            "import json,time\n"
            "print(json.dumps({'type':'thread.started','thread_id':'wrong'}),flush=True)\n"
            "print(json.dumps({'type':'turn.started'}),flush=True)\n"
            "time.sleep(1)\n"
        )
        _, _, exit_status, native_started = _communicate_after_native_start(
            process, "work", expected_session_id=SESSION, start_timeout_seconds=0.03,
        )
        self.assertFalse(native_started)
        self.assertIsNone(exit_status)
        self.assertIsNotNone(process.returncode)

    def test_explicit_owner_cancel_terminates_identified_process(self):
        process = _process(_started_source("time.sleep(10)\n"))
        captured: list[tuple[str, str, int | None, bool]] = []
        worker = threading.Thread(
            target=lambda: captured.append(_communicate_after_native_start(
                process, "work", expected_session_id=SESSION, start_timeout_seconds=1,
            )),
            daemon=True,
        )
        worker.start()
        time.sleep(0.08)
        _terminate_owned_process(process)
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(captured[0][3])
        self.assertNotEqual(captured[0][2], 0)


if __name__ == "__main__":
    unittest.main()
