"""Exercise the installed orchestrator client grammar against private temp lanes."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otto.portfolio import client_lanes
from otto.portfolio.orchestrator_client import main


class OrchestratorClientCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner_lane = client_lanes.private_dir(self.root / "owner-inbox")
        self.client_lane = client_lanes.private_dir(self.root / "astrid-client")
        self.connection = self.root / "connection.json"
        self.binding = self.root / "binding.json"
        client_lanes.atomic_json(self.connection, {
            "schema": "otto.orchestrator-connection.v1",
            "owner_inbox": str(self.owner_lane),
            "service": "temporary-test-owner",
        })
        client_lanes.atomic_json(self.binding, {
            "lane": str(self.client_lane),
            "binding": {
                "request_namespace": "assignment-astrid-root",
                "assignment_ref": {"authority": "owner", "kind": "wrk.assignment",
                                   "id": "astrid-root", "revision": "rev-1"},
            },
        })
        self.waited = []

    def invoke(self, *args, waiter=None):
        output = io.StringIO()
        argv = ["--connection", str(self.connection), *args]
        with contextlib.redirect_stdout(output):
            if waiter is None:
                code = main(argv)
            else:
                with patch.object(client_lanes, "wait", side_effect=waiter):
                    code = main(argv)
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def test_cold_discover_and_status_are_read_only_without_binding(self):
        discover = self.invoke("discover")
        self.assertEqual(discover["state"], "unregistered")
        status = self.invoke("status")
        self.assertEqual(status["state"], "unregistered")
        self.assertFalse(status["authority_granted"])
        self.assertEqual(list(client_lanes.requests(self.owner_lane)), [])

    def test_enrollment_request_grants_no_authority_and_can_be_recovered_prebinding(self):
        seen = []

        def pending(lane, token, *, timeout_seconds):
            seen.append((Path(lane), token))
            return {"outcome": "pending", "request_id": token, "provider_called": False}

        request = self.invoke(
            "request-enrollment", "--request-key", "astrid-enroll-1",
            "--conversation-ref", '{"host":"codex","native_id":"astrid-chat"}',
            "--project-id", "project-port", waiter=pending)
        self.assertEqual(request["outcome"], "pending")
        self.assertEqual(seen[0][0], self.owner_lane)
        request_record = client_lanes.read_private_json(
            self.owner_lane / ("request-" + seen[0][1] + ".json"))
        self.assertEqual(request_record["operation"], "request-enrollment")
        self.assertEqual(request_record["requested_project_ids"], ["project-port"])
        self.assertNotIn("authority", request_record)
        self.assertNotIn("binding", request_record)
        request_paths = sorted(self.owner_lane.glob("request-*.json"))

        recovered_calls = []

        def recover(lane, token, *, timeout_seconds):
            recovered_calls.append((Path(lane), token))
            return {"outcome": "completed", "request_id": token, "state": "requested",
                    "authority_granted": False}

        recovered = self.invoke("request-status", "--request-id", seen[0][1], waiter=recover)
        self.assertEqual(recovered["state"], "requested")
        self.assertEqual(recovered_calls, [(self.owner_lane, seen[0][1])])
        self.assertEqual(sorted(self.owner_lane.glob("request-*.json")), request_paths)

    def test_mutations_require_explicit_stable_request_key(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--connection", str(self.connection), "--binding", str(self.binding),
                  "project-authoring", "--project-id", "project-port", "--request", "{}"])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(list(client_lanes.requests(self.client_lane)), [])

    def test_unkeyed_reads_get_fresh_handles_and_status_reuses_exact_old_handle(self):
        observed = []

        def pending(lane, token, *, timeout_seconds):
            observed.append((Path(lane), token, timeout_seconds))
            return {"outcome": "pending", "request_id": token}

        first = self.invoke("--binding", str(self.binding), "whoami", waiter=pending)
        second = self.invoke("--binding", str(self.binding), "whoami", waiter=pending)
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertEqual(observed[0][0], self.client_lane)
        self.assertEqual(observed[1][0], self.client_lane)
        self.assertTrue((self.client_lane / ("request-" + first["request_id"] + ".json")).exists())
        self.assertTrue((self.client_lane / ("request-" + second["request_id"] + ".json")).exists())

        recovered_calls = []

        def recover(lane, token, *, timeout_seconds):
            recovered_calls.append((Path(lane), token))
            return {"outcome": "completed", "request_id": token, "principal": "astrid"}

        recovered = self.invoke("--binding", str(self.binding), "request-status",
                                "--request-id", first["request_id"], waiter=recover)
        self.assertEqual(recovered["principal"], "astrid")
        self.assertEqual(recovered_calls, [(self.client_lane, first["request_id"])])
        self.assertEqual(len(list(client_lanes.requests(self.client_lane))), 2)


if __name__ == "__main__":
    unittest.main()
