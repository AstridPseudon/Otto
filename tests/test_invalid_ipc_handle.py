"""Invalid transport handles receive retained rejections without dispatch."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from otto.portfolio.execution_host import ExecutionHost


class InvalidHandleTests(unittest.TestCase):
    def test_invalid_handles_are_terminal_rejected_and_preserved_through_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            handler = lambda request: calls.append(request) or {"outcome": "ok"}
            invalid = {"bad-label": b'{"command":"status"}\n', "ABCDEF": b'not JSON', "": b'{}'}
            for token, raw in invalid.items():
                (root / ("request-" + token + ".json")).write_bytes(raw)
            host = ExecutionHost(directory=root, handler=handler)
            host.start()
            try:
                deadline = time.monotonic() + 3
                while not all((root / ("response-" + token + ".json")).exists() for token in invalid) and time.monotonic() < deadline:
                    time.sleep(.01)
                retained = {}
                for token, raw in invalid.items():
                    response = root / ("response-" + token + ".json")
                    value = json.loads(response.read_text())
                    self.assertEqual(value["outcome"], "rejected")
                    self.assertEqual(value["error"]["code"], "invalid_request_id")
                    self.assertFalse(value["request_dispatched"])
                    self.assertFalse(value["effects_started"])
                    self.assertFalse(value["provider_called"])
                    self.assertEqual((root / ("request-" + token + ".json")).read_bytes(), raw)
                    retained[token] = response.read_bytes()
                self.assertEqual(calls, [])
            finally:
                host.close()
            host = ExecutionHost(directory=root, handler=handler)
            host.start()
            try:
                (root / "request-a1b2.json").write_text('{"command":"status"}')
                deadline = time.monotonic() + 3
                while not (root / "response-a1b2.json").exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(json.loads((root / "response-a1b2.json").read_text())["outcome"], "ok")
                self.assertEqual(calls, [{"command": "status"}])
                for token, raw in retained.items():
                    self.assertEqual((root / ("response-" + token + ".json")).read_bytes(), raw)
            finally:
                host.close()


if __name__ == "__main__": unittest.main()
