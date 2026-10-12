import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from otto.portfolio import client_lanes as lanes
from otto.portfolio.orchestrator_client import OrchestratorLanePump


class _Admission:
    def request(self, **_):
        return {"state": "requested", "authority_granted": False}


class _Manager:
    def __init__(self, result):
        self.result = result

    def call(self, request):
        self.seen = request
        return self.result


class ManagerStartBoundedEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.inbox = lanes.private_dir(root / "inbox")
        self.lane = lanes.private_dir(root / "client" / "lane")

    def pump(self, result):
        manager = _Manager(result)
        pump = OrchestratorLanePump(owner_inbox=self.inbox, admissions=_Admission(),
                                    clients={self.lane: manager}, owner_call=lambda call: call())
        token = lanes.submit(self.lane, {"operation": "manager-start", "request_key": "manager-domain-v1"})
        self.assertEqual(pump.poll()[0]["outcome"], "succeeded")
        return token, manager

    def test_oversize_manager_start_publishes_bounded_lane_and_exact_retained_pin(self):
        result = {"outcome": "succeeded", "provider_called": False,
                  "assignment_ref": {"authority": "owner", "kind": "wrk.assignment",
                                      "id": "manager-root", "revision": "rev-4"},
                  "generation": 1,
                  "result": {"raw_result": {"worker_transcript": "x" * (1_100_000)}}}
        token, manager = self.pump(result)
        response = self.lane / ("response-" + token + ".json")
        self.assertLess(response.stat().st_size, 1_048_576)
        envelope = lanes.wait(self.lane, token, timeout_seconds=0)
        self.assertEqual(envelope["schema"], lanes.MANAGER_START_RESPONSE_SCHEMA)
        self.assertEqual(envelope["request_id"], token)
        self.assertEqual(envelope["request_key"], "manager-domain-v1")
        self.assertEqual(manager.seen["operation"], "manager-start")
        retained = envelope["retained_response"]
        detail = Path(retained["path"])
        self.assertTrue(detail.is_file())
        raw = detail.read_bytes()
        self.assertGreater(len(raw), 1_048_576)
        self.assertEqual(retained["byte_length"], len(raw))
        self.assertEqual(retained["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(envelope["summary"]["outcome"], "succeeded")
        self.assertEqual(envelope["summary"]["assignment_ref"]["id"], "manager-root")
        # The ordinary lane reader retains its one-MiB caller cap; explicit
        # detail access is required for the exact historical response.
        with self.assertRaises(ValueError):
            lanes.read_private_json(detail)

    def test_changed_domain_transport_or_foreign_retained_ref_is_refused(self):
        result = {"outcome": "succeeded", "result": {"raw": "y" * 1_100_000}}
        token, _ = self.pump(result)
        response = self.lane / ("response-" + token + ".json")
        original = json.loads(response.read_text())
        cases = []
        changed_key = dict(original)
        changed_key["request_key"] = "other-domain"
        cases.append(changed_key)
        foreign_transport = dict(original)
        foreign_transport["authenticated_transport"] = dict(original["authenticated_transport"])
        foreign_transport["authenticated_transport"]["lane"] = str(self.inbox)
        cases.append(foreign_transport)
        foreign_ref = dict(original)
        foreign_ref["retained_response"] = dict(original["retained_response"])
        foreign_ref["retained_response"]["path"] = str(self.inbox / "foreign.detail.json")
        cases.append(foreign_ref)
        for forged in cases:
            lanes.atomic_json(response, forged)
            with self.assertRaises(PermissionError):
                lanes.read_manager_start_response(self.lane, token)

    def test_changed_or_non_oversize_retained_artifact_is_refused(self):
        token, _ = self.pump({"outcome": "succeeded", "result": {"raw": "z" * 1_100_000}})
        response = self.lane / ("response-" + token + ".json")
        envelope = json.loads(response.read_text())
        detail = Path(envelope["retained_response"]["path"])
        original = detail.read_bytes()
        detail.write_bytes(original[:128])
        with self.assertRaises(ValueError):
            lanes.read_manager_start_response(self.lane, token)

    def test_small_manager_start_keeps_original_response_shape(self):
        token, _ = self.pump({"outcome": "succeeded", "result": {"status": "ready"}})
        value = lanes.read_private_json(self.lane / ("response-" + token + ".json"))
        self.assertEqual(value["result"], {"status": "ready"})
        self.assertNotIn("schema", value)
        self.assertFalse((self.lane.parent / "retained").exists())

    def test_summary_overflow_preserves_exact_reply_and_publishes_detail_required(self):
        # Optional metadata overflow must not hide a successful retained effect.
        with patch("otto.portfolio.manager_journey_client.command_result_summary",
                   return_value={"outcome": "succeeded", "optional_metadata": "x" * 1_100_000}):
            token, _ = self.pump({"outcome": "succeeded", "result": {"raw": "z" * 1_100_000}})
        envelope = lanes.wait(self.lane, token, timeout_seconds=0)
        self.assertEqual(envelope["outcome"], "succeeded")
        self.assertEqual(envelope["summary_availability"]["state"], "detail-required")
        self.assertLess((self.lane / ("response-" + token + ".json")).stat().st_size, 65536)
        self.assertTrue(Path(envelope["retained_response"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
