"""Paused host binding uses in-memory owner ports, never a Store or host write."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from otto.attention import DueRecord
from otto.portfolio.advisor_delivery import effect_followup_schedule_id
from otto.portfolio.advisor_host_command import (
    bind_paused_advisor_automation, read_persisted_automation_settings,
)
from tests import test_project_advisor_delivery as fixture_module


class PausedAdvisorHostTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.AdvisorDeliveryTests()
        self.fixture.setUp()
        self.fixture._schedule_second_wake()
        self.attention = self.fixture.attention
        self.schedule = effect_followup_schedule_id(self.fixture.pairing.project_ref, "decision-fixture")
        value = self.fixture.due_port.read_due("advisor-followup")
        value.update(schedule_id=self.schedule, purpose="advisor-effect-followup",
                     stop_state="completed", last_covered_slot=3,
                     last_completed_request="historical-request", last_result={"outcome": "returned"},
                     completion_state="succeeded",
                     allowance_ref=fixture_module.ref("limit", "same-exhausted-pool"))
        self.attention.schedule(DueRecord.from_dict(value), request_id="existing-fixture-schedule")
        self.initial = self.attention._read(self.schedule)
        self.settings = {"id": "existing-paused-automation", "kind": "heartbeat", "name": "Effect follow-up",
                         "prompt": "Notify owner only", "status": "PAUSED", "rrule": "FREQ=HOURLY;INTERVAL=1",
                         "targetThreadId": "manager-session", "notificationPolicy": "failed_runs_only"}
        self.reader = Mock(side_effect=lambda _identity: dict(self.settings))
        self.request = {"schedule_id": self.schedule, "decision_id": "decision-fixture",
                        "automation_id": self.settings["id"], "expected_version": self.initial.version,
                        "request_key": "fixture-host-adoption"}

    def call(self, **kwargs):
        return bind_paused_advisor_automation(
            request=kwargs.get("request", self.request), pairing=self.fixture.pairing,
            actor=kwargs.get("actor", "owner-principal"), attention=self.attention,
            read_settings=self.reader)

    def test_bind_prepare_exact_readback_ack_preserves_identity_cadence_and_pool(self):
        result = self.call()
        self.assertEqual(result["outcome"], "reconciled")
        self.assertEqual(result["prepared"]["effect"]["desired_state"], "paused")
        self.assertTrue(result["acknowledgement"]["readback_exact"])
        current = self.attention._read(self.schedule)
        self.assertEqual(current.version, self.initial.version + 3)
        self.assertEqual(current.host_state, "paused")
        self.assertEqual(current.target["automation"], self.settings)
        self.assertEqual({key: value for key, value in current.target.items() if key != "automation"}, self.initial.target)
        for name in ("schedule_id", "anchor", "due_at", "interval_seconds", "last_covered_slot",
                     "last_completed_request", "last_result", "stop_state", "allowance_ref",
                     "assignment_ref", "generation", "context_refs", "requested_model"):
            self.assertEqual(getattr(current, name), getattr(self.initial, name), name)
        self.assertIsNone(current.in_flight_request)
        self.assertEqual(self.fixture.attention_port.requests, [])
        self.assertEqual(self.fixture.runtime_calls, [])
        self.assertFalse(result["provider_called"])
        self.assertFalse(result["automation_updated"])
        self.assertEqual(self.reader.call_count, 2)

    def test_exact_replay_reads_existing_effect_without_second_reconfigure(self):
        first = self.call()
        fresh = self.attention._read(self.schedule)
        with patch.object(self.attention, "reconfigure", wraps=self.attention.reconfigure) as reconfigure:
            second = self.call(request={**self.request, "expected_version": fresh.version})
        reconfigure.assert_not_called()
        self.assertEqual(second["outcome"], "reconciled")
        self.assertTrue(second["prepared"]["replayed"])
        self.assertEqual(second["prepared"]["effect"], first["prepared"]["effect"])
        self.assertEqual(self.attention._read(self.schedule).version, fresh.version)

    def test_stale_foreign_or_wrong_schedule_rejects_before_host_read_and_writes(self):
        with patch.object(self.attention, "reconfigure") as write:
            self.assertEqual(self.call(actor="foreign")["outcome"], "rejected")
            self.assertEqual(self.call(request={**self.request, "expected_version": 99})["error"]["code"], "stale_version")
            with self.assertRaises(ValueError):
                self.call(request={**self.request, "schedule_id": "new-occurrence"})
            with self.assertRaises(ValueError):
                self.call(request={**self.request, "expected_version": True})
        write.assert_not_called()
        self.reader.assert_not_called()

    def test_active_or_direct_advisor_target_never_reconfigures(self):
        for changes in ({"status": "ACTIVE"}, {"targetThreadId": "advisor-session"},
                        {"id": "other-automation"}, {"kind": "cron"}):
            self.reader.side_effect = lambda _identity, changes=changes: {**self.settings, **changes}
            with patch.object(self.attention, "reconfigure") as write:
                result = self.call()
            self.assertEqual(result["outcome"], "rejected")
            write.assert_not_called()
        self.assertEqual(self.attention._read(self.schedule).version, self.initial.version)

    def test_unknown_occurrence_is_held_without_changing_fence(self):
        from dataclasses import replace
        unknown = replace(self.initial, completion_state="unknown", in_flight_request="original-unknown")
        with patch.object(self.attention, "_read", return_value=unknown), \
                patch.object(self.attention, "reconfigure") as write:
            self.assertEqual(self.call()["outcome"], "held")
        write.assert_not_called()
        self.reader.assert_not_called()

    def test_changed_or_lost_readback_stays_pending(self):
        self.reader.side_effect = [self.settings, {**self.settings, "prompt": "changed"}]
        result = self.call()
        self.assertEqual(result["outcome"], "pending")
        self.assertFalse(result["acknowledgement"]["readback_exact"])
        fresh = self.attention._read(self.schedule)
        self.reader.side_effect = [self.settings, FileNotFoundError("response lost")]
        result = self.call(request={**self.request, "expected_version": fresh.version})
        self.assertEqual(result["outcome"], "pending")
        self.assertTrue(result["acknowledgement"]["observation"]["response_lost"])

    def test_cli_supplies_only_explicit_paused_binding_and_exact_ids(self):
        spec = importlib.util.spec_from_file_location("paused_host_client", Path(__file__).resolve().parents[1] / "manager_ctl.py")
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        argv = ["manager_ctl.py", "advisor-followup-bind-paused", "--schedule-id", self.schedule,
                "--decision-id", self.request["decision_id"], "--automation-id", self.settings["id"],
                "--expected-version", str(self.initial.version), "--request-key", self.request["request_key"]]
        with patch.object(client, "call", side_effect=lambda request: self.call(request=request)), \
                patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            client.main()
        self.assertEqual(self.attention._read(self.schedule).host_state, "paused")

    def test_persisted_reader_normalizes_exact_fields_without_writing(self):
        try:
            import tomllib
        except ImportError:
            from pip._vendor import tomli as tomllib
        raw = ('id = "existing-id"\nkind = "heartbeat"\nname = "Follow-up"\nprompt = "Owner tick"\n'
               'status = "PAUSED"\nrrule = "FREQ=HOURLY"\ntarget_thread_id = "manager-session"\n'
               'notification_policy = "failed_runs_only"\n').encode()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            folder = directory / "existing-id"
            folder.mkdir()
            path = folder / "automation.toml"
            path.write_bytes(raw)
            value = read_persisted_automation_settings(directory, "existing-id", parse_toml=tomllib.loads)
            self.assertEqual(value["targetThreadId"], "manager-session")
            self.assertEqual(value["notificationPolicy"], "failed_runs_only")
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(len(value["persisted_sha256"]), 64)
            with self.assertRaises(ValueError):
                read_persisted_automation_settings(directory, "../existing-id", parse_toml=tomllib.loads)


if __name__ == "__main__":
    unittest.main()
