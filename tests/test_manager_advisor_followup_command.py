"""Follow-up IPC checks use inert callbacks and in-memory Due only; no Store."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from herzchen.kernel.limits import AllowanceExhaustedError
from otto.attention import DueRecord
from otto.portfolio.advisor_delivery import effect_followup_schedule_id
from otto.portfolio.advisor_execution import AdvisorExecution
from otto.portfolio.advisor_followup_command import advisor_followup_from_command
from tests import test_project_advisor_delivery as fixture_module


class AdvisorFollowupCommandTests(unittest.TestCase):
    def setUp(self):
        self.project = fixture_module.PROJECT
        self.decision = "fixture-decision"
        self.schedule = effect_followup_schedule_id(self.project, self.decision)
        self.record = {"schedule_id": self.schedule, "project_ref": self.project["id"],
                       "role": "project_advisor", "purpose": "advisor-effect-followup",
                       "stop_state": "active", "host_state": "unknown", "target": {}}
        self.read = Mock(return_value=self.record)
        self.dispatch = Mock(return_value={"outcome": "held", "dispatch": {"retry": False}})

    def call(self, request=None):
        return advisor_followup_from_command(
            request=request or {"schedule_id": self.schedule, "decision_id": self.decision},
            project_ref=self.project, read_due=self.read, dispatch=self.dispatch)

    def dispatch_request(self):
        return {"schedule_id": self.schedule, "decision_id": self.decision, "operation": "dispatch"}

    def test_default_status_reads_exact_record_without_prepare_or_dispatch(self):
        before = json.dumps(self.record, sort_keys=True)
        result = self.call()
        self.assertEqual(result["outcome"], "read")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["provider_called"])
        self.read.assert_called_once_with(self.schedule)
        self.dispatch.assert_not_called()
        self.assertEqual(json.dumps(self.record, sort_keys=True), before)

    def test_paused_or_unready_host_never_dispatches_even_when_requested(self):
        for host in ("paused", "pending", "failed"):
            self.record["host_state"] = host
            self.assertEqual(self.call(self.dispatch_request())["outcome"], "held")
        self.record["host_state"] = "unknown"
        for automation in ({"status": "PAUSED"}, {}, "invalid"):
            self.record["target"] = {"automation": automation}
            value = self.call(self.dispatch_request())
            self.assertEqual(value["outcome"], "held")
            self.assertFalse(value["provider_called"])
        self.dispatch.assert_not_called()

    def test_active_operation_forwards_only_existing_ids_to_owner_dispatch(self):
        self.record["host_state"] = "active"
        self.record["target"] = {"automation": {"status": "ACTIVE"}}
        request = {**self.dispatch_request(), "actor": "foreign", "allowance_ref": "new-pool",
                   "native_id": "wrong-target", "request_id": "new-occurrence"}
        result = self.call(request)
        self.dispatch.assert_called_once_with(schedule_id=self.schedule, decision_id=self.decision)
        self.assertEqual(result["outcome"], "held")
        self.assertEqual((result["schedule_id"], result["decision_id"]), (self.schedule, self.decision))
        self.assertFalse(result["retry"])

    def test_invalid_operation_or_id_rejects_before_owner_read(self):
        for changes in ({"operation": "prepare"}, {"operation": "wake"}, {"schedule_id": "new"},
                        {"decision_id": "other"}, {"decision_id": " fixture-decision"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call({**self.dispatch_request(), **changes})
        self.read.assert_not_called()
        self.dispatch.assert_not_called()

    def test_unavailable_or_foreign_read_is_unknown_without_dispatch(self):
        for record in (None, {}, {**self.record, "project_ref": "foreign"},
                       {**self.record, "purpose": "worker"}, {**self.record, "role": "worker"}):
            self.read.return_value = record
            self.assertEqual(self.call(self.dispatch_request())["outcome"], "unknown")
        self.read.side_effect = RuntimeError("owner unavailable")
        self.assertEqual(self.call()["error"]["code"], "followup_read_failed")
        self.dispatch.assert_not_called()

    def test_unknown_dispatch_preserves_no_retry_and_does_not_claim_no_provider(self):
        self.dispatch.side_effect = RuntimeError("requires reconciliation")
        result = self.call(self.dispatch_request())
        self.assertEqual(result["outcome"], "unknown")
        self.assertTrue(result["dispatch_called"])
        self.assertFalse(result["retry"])
        self.assertNotIn("provider_called", result)
        self.dispatch.assert_called_once()

    def test_cli_defaults_to_status_and_only_explicit_operation_dispatches(self):
        spec = importlib.util.spec_from_file_location(
            "followup_client", Path(__file__).resolve().parents[1] / "manager_ctl.py")
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        argv = ["manager_ctl.py", "advisor-followup", "--schedule-id", self.schedule,
                "--decision-id", self.decision]
        with patch.object(client, "call", side_effect=self.call), patch("sys.argv", argv), \
                contextlib.redirect_stdout(io.StringIO()):
            client.main()
        self.dispatch.assert_not_called()
        # Held is deliberately a non-success CLI exit, rather than a successful tick.
        with patch.object(client, "call", side_effect=self.call), \
                patch("sys.argv", argv + ["--operation", "dispatch"]), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            client.main()
        self.assertEqual(caught.exception.code, 1)
        self.dispatch.assert_called_once_with(schedule_id=self.schedule, decision_id=self.decision)
        self.dispatch.return_value = {"outcome": "returned"}
        with patch.object(client, "call", side_effect=self.call), \
                patch("sys.argv", argv + ["--operation", "dispatch"]), \
                contextlib.redirect_stdout(io.StringIO()):
            client.main()

    def test_exhausted_allowance_reaches_existing_admission_and_never_provider(self):
        fixture = fixture_module.AdvisorDeliveryTests()
        fixture.setUp()
        fixture._schedule_second_wake()
        pool_ref = fixture_module.ref("limit", "same-exhausted-pool")
        record = fixture.due_port.read_due("advisor-followup")
        record.update(schedule_id=self.schedule, purpose="advisor-effect-followup", allowance_ref=pool_ref)
        fixture.attention.schedule(DueRecord.from_dict(record), request_id="fixture-existing-schedule")
        allowance = SimpleNamespace(reserve=Mock(side_effect=AllowanceExhaustedError("cumulative allowance is exhausted")))
        provider_start = Mock()
        app = SimpleNamespace(
            actor="owner-principal", binding=SimpleNamespace(authenticated_actor=lambda actor: actor),
            _read=lambda identity: DueRecord.from_dict(fixture.due_port.read_due(identity)),
            _resources=lambda due: due, start=provider_start)
        # The retained pins are fixture data; no resource/pool adoption is performed here.
        integration = AdvisorExecution(execution=app, ports=fixture.loop.ports,
                                       allowance=allowance, allowance_ref=pool_ref)
        def owner_dispatch(*, schedule_id, decision_id):
            result = integration.wake_once(pairing=fixture.pairing, schedule_id=schedule_id,
                advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
                reason="scheduled-effect-followup", request={"decision_id": decision_id})
            return {"outcome": result["outcome"], "dispatch": result}
        self.read.side_effect = fixture.due_port.read_due
        self.dispatch.side_effect = owner_dispatch
        result = self.call(self.dispatch_request())
        self.assertEqual(result["outcome"], "unknown")
        self.assertFalse(result["retry"])
        allowance.reserve.assert_called_once()
        self.assertEqual(allowance.reserve.call_args.args[0].to_dict(), pool_ref)
        provider_start.assert_not_called()
        self.assertEqual(fixture.due_port.read_due(self.schedule)["completion_state"], "unknown")
        # The existing unknown claim prevents another delivery on the same schedule.
        replay = self.call(self.dispatch_request())
        self.assertEqual(replay["outcome"], "reconcile")
        allowance.reserve.assert_called_once()
        provider_start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
