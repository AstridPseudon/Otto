"""Caller timeout advice preserves uncertainty and the exact socket handle."""
import json
import socket
import threading
import unittest

from otto.portfolio.caller_client import _timeout_for, call_connection


class CallerClientRetainedRecoveryTests(unittest.TestCase):
    def test_timeout_keeps_exact_outer_handle_and_does_not_resend_or_claim_absence(self):
        caller, owner = socket.socketpair()
        self.addCleanup(caller.close)
        self.addCleanup(owner.close)
        caller.settimeout(0.02)
        owner.settimeout(1)
        request = {"command": "resolve-help", "request_key": "canonical-help-17",
                   "issue_id": "issue-17", "transport_request_id": "caller-forgery"}

        result = call_connection(caller, request)
        line = owner.recv(65536)
        sent = json.loads(line)

        self.assertEqual(sent["request_key"], "canonical-help-17")
        self.assertNotEqual(sent["transport_request_id"], "caller-forgery")
        handle = sent["transport_request_id"]
        self.assertEqual(len(handle), 32)
        self.assertEqual(result["outcome"], "unknown")
        self.assertFalse(result["retry"])
        self.assertEqual(result["outer_command"], {
            "transport": "unix-socket", "request_id": handle,
            "retained": None, "retention": "unconfirmed"})
        self.assertIn("command-status --request-id " + handle, result["next_action"])
        self.assertIn("exact scope and canonical logical request key", result["next_action"])
        self.assertNotIn("provider_called", result)
        self.assertNotIn("effects_started", result)
        owner.settimeout(0.02)
        with self.assertRaises(socket.timeout):
            owner.recv(1)

    def test_disconnected_owner_returns_unknown_and_launch_only_lookup_advice(self):
        caller, owner = socket.socketpair()
        self.addCleanup(caller.close)
        caller.settimeout(1)
        received = threading.Event()

        def close_after_one_request():
            try:
                owner.recv(65536)
                received.set()
            finally:
                owner.close()

        thread = threading.Thread(target=close_after_one_request)
        thread.start()
        result = call_connection(caller, {
            "command": "run-worker", "schedule_id": "schedule-1",
            "request_key": "launch-1", "request_input": {"task": "D01"}})
        thread.join(1)
        self.assertTrue(received.is_set())
        self.assertEqual(result["outcome"], "unknown")
        self.assertFalse(result["retry"])
        self.assertIn("command-status --request-id " + result["outer_command"]["request_id"],
                      result["next_action"])
        self.assertIn("lookup-occurrence only for this exact launch/run-worker", result["next_action"])
        self.assertNotIn("absent", result["next_action"].lower())
        self.assertNotIn("provider_called", result)
        self.assertNotIn("effects_started", result)

    def test_default_waits_are_bounded_by_operation_and_explicit_timeout_wins(self):
        self.assertEqual(_timeout_for({"command": "whoami"}, None), 15)
        self.assertEqual(_timeout_for({"command": "effective-context"}, None), 15)
        for command in ("report", "request-help", "respond-help", "resolve-help", "read-help"):
            with self.subTest(command=command):
                self.assertEqual(_timeout_for({"command": command}, None), 60)
        self.assertEqual(_timeout_for({"command": "resolve-help"}, 2.5), 2.5)


if __name__ == "__main__":
    unittest.main()
