from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

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


class _ObservedStartStream:
    """Signal after the consumer has processed the native turn-start line."""

    def __init__(self, stream):
        self.stream = stream
        self.observed = threading.Event()
        self.saw_start = False

    def readline(self):
        # The next read begins only after the prior event was processed.
        if self.saw_start:
            self.observed.set()
        line = self.stream.readline()
        if line:
            self.saw_start |= json.loads(line).get("type") == "turn.started"
        return line

    def close(self):
        self.stream.close()


class HealthyWorkerLifetimeTests(unittest.TestCase):
    def test_native_started_work_continues_beyond_start_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "finish"
            process = _process(_started_source(
                "from pathlib import Path\n"
                f"release=Path({str(release)!r})\n"
                "while not release.exists(): time.sleep(0.005)\n"
                "print(json.dumps({'type':'turn.completed'}), flush=True)\n"
            ))
            observed = _ObservedStartStream(process.stdout)
            process.stdout = observed
            clock = [0.0]
            captured = []
            worker = threading.Thread(target=lambda: captured.append(
                _communicate_after_native_start(
                    process, "work", expected_session_id=SESSION,
                    start_timeout_seconds=0.03, monotonic_clock=lambda: clock[0],
                )
            ), daemon=True)
            worker.start()
            try:
                self.assertTrue(observed.observed.wait(5), "native start was not consumed")
                clock[0] = 1000.0
                worker.join(timeout=0.08)
                self.assertTrue(worker.is_alive(), "healthy work ended at the startup deadline")
                self.assertIsNone(process.poll())
                release.touch()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            finally:
                if process.poll() is None:
                    _terminate_owned_process(process)
                worker.join(timeout=5)
            stdout, stderr, exit_status, native_started = captured[0]
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
        observed = _ObservedStartStream(process.stdout)
        process.stdout = observed
        captured: list[tuple[str, str, int | None, bool]] = []
        worker = threading.Thread(
            target=lambda: captured.append(_communicate_after_native_start(
                process, "work", expected_session_id=SESSION, start_timeout_seconds=5,
            )),
            daemon=True,
        )
        worker.start()
        try:
            self.assertTrue(observed.observed.wait(5), "native start was not consumed")
        finally:
            _terminate_owned_process(process)
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(captured[0][3])
        self.assertNotEqual(captured[0][2], 0)


if __name__ == "__main__":
    unittest.main()
