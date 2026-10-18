"""File IPC receipts stay fenced when atomic publication fails."""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.manager_journey_client import read_command_status
from otto.portfolio.owner_completion import OwnerCompletion


class ReceiptFenceTests(unittest.TestCase):
    def test_failed_deferred_response_retries_receipt_without_redispatch_even_after_restart(self):
        for restart in (False, True):
            with self.subTest(restart=restart):
                with tempfile.TemporaryDirectory() as temporary:
                    lane = Path(temporary)
                    token = "a" * 32
                    request = lane / f"request-{token}.json"
                    pending = lane / f"pending-{token}.json"
                    response = lane / f"response-{token}.json"
                    calls = []
                    completion = OwnerCompletion()

                    def handler(command):
                        calls.append(command["command"])
                        return completion

                    host = ExecutionHost(directory=lane, handler=handler)
                    request.write_text(json.dumps({"command": "finish-task"}))
                    host._serve_files(False)
                    self.assertEqual(calls, ["finish-task"])
                    self.assertTrue(pending.is_file())

                    response.mkdir()  # os.replace of an atomic file must fail.
                    completion.resolve({"outcome": "committed", "effect_count": 1})
                    self.assertIn(token, host.failures)
                    self.assertTrue(request.exists())
                    self.assertTrue(pending.exists())
                    response.rmdir()

                    survivor = ExecutionHost(directory=lane, handler=handler) if restart else host
                    survivor._serve_files(False)

                    self.assertEqual(calls, ["finish-task"])
                    self.assertEqual(len(list(lane.glob("response-*.json"))), 1)
                    receipt = json.loads(response.read_text())
                    if restart:
                        self.assertIn(receipt["outcome"], {"committed", "unknown"})
                    else:
                        self.assertEqual(
                            (receipt["outcome"], receipt["effect_count"]),
                            ("committed", 1),
                        )
                    self.assertTrue(read_command_status(lane, token)["terminal"])
                    self.assertFalse(request.exists())
                    self.assertFalse(pending.exists())

                    survivor._serve_files(False)
                    self.assertEqual(calls, ["finish-task"])

    def test_synchronous_claim_precedes_handler_and_failed_receipt_reuses_settlement(self):
        with tempfile.TemporaryDirectory() as temporary:
            lane = Path(temporary)
            token = "b" * 32
            request = lane / f"request-{token}.json"
            pending = lane / f"pending-{token}.json"
            response = lane / f"response-{token}.json"
            request.write_text(json.dumps({"command": "finish-task"}))
            calls = []

            def handler(command):
                calls.append(command["command"])
                claim = json.loads(pending.read_text())
                self.assertTrue(claim["dispatch_claimed"])
                self.assertEqual(claim["request_sha256"], hashlib.sha256(request.read_bytes()).hexdigest())
                response.mkdir()
                return {"outcome": "committed", "effect_count": 1}

            host = ExecutionHost(directory=lane, handler=handler)
            host._serve_files(False)
            self.assertEqual(calls, ["finish-task"])
            self.assertIn(token, host.failures)
            response.rmdir()
            host._serve_files(False)
            self.assertEqual(calls, ["finish-task"])
            self.assertEqual(json.loads(response.read_text())["effect_count"], 1)
            self.assertFalse(request.exists())
            self.assertFalse(pending.exists())

    def test_written_response_wins_when_status_projection_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            lane = Path(temporary)
            token = "c" * 32
            request = lane / f"request-{token}.json"
            pending = lane / f"pending-{token}.json"
            response = lane / f"response-{token}.json"
            status_projection = lane / f"status-response-{token}.json"
            calls = []

            def handler(command):
                calls.append(command["command"])
                status_projection.mkdir()
                return {"outcome": "committed", "effect_count": 1}

            request.write_text(json.dumps({"command": "finish-task"}))
            host = ExecutionHost(directory=lane, handler=handler)
            host._serve_files(False)
            self.assertIn(token, host.failures)
            original = response.read_bytes()
            status_projection.rmdir()
            host._serve_files(False)
            self.assertEqual(calls, ["finish-task"])
            self.assertEqual(response.read_bytes(), original)
            self.assertTrue(read_command_status(lane, token)["terminal"])
            self.assertNotIn(token, host.failures)
            self.assertFalse(request.exists())
            self.assertFalse(pending.exists())

    def test_restart_without_settlement_publishes_unknown_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            lane = Path(temporary)
            token = "d" * 32
            request = lane / f"request-{token}.json"
            response = lane / f"response-{token}.json"
            calls = []

            def handler(command):
                calls.append(command["command"])
                return OwnerCompletion()

            request.write_text(json.dumps({"command": "finish-task"}))
            ExecutionHost(directory=lane, handler=handler)._serve_files(False)
            survivor = ExecutionHost(directory=lane, handler=handler)
            survivor._serve_files(False)
            receipt = json.loads(response.read_text())
            self.assertEqual(calls, ["finish-task"])
            self.assertEqual(receipt["outcome"], "unknown")
            self.assertFalse(receipt["retry"])
            self.assertFalse(request.exists())

    def test_changed_claimed_request_bytes_do_not_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            lane = Path(temporary)
            token = "e" * 32
            request = lane / f"request-{token}.json"
            pending = lane / f"pending-{token}.json"
            calls = []

            def handler(command):
                calls.append(command["command"])
                return OwnerCompletion()

            request.write_text(json.dumps({"command": "finish-task", "target": "original"}))
            ExecutionHost(directory=lane, handler=handler)._serve_files(False)
            claim = json.loads(pending.read_text())
            self.assertTrue(claim["dispatch_claimed"])
            request.write_text(json.dumps({"command": "finish-task", "target": "changed"}))
            survivor = ExecutionHost(directory=lane, handler=handler)
            survivor._serve_files(False)
            self.assertEqual(calls, ["finish-task"])
            self.assertEqual(survivor.failures[token]["code"], "ValueError")
            self.assertTrue(request.exists())
            self.assertTrue(pending.exists())
