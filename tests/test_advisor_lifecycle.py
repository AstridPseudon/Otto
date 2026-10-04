"""Existing callback -> attention -> real temporary owner limit; no provider."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel.limits import LimitService
from herzchen.kernel.store import Store
from otto.portfolio.advisor_delivery import effect_followup_schedule_id
from otto.portfolio.advisor_lifecycle import exercise_advisor_lifecycle
from tests import test_project_advisor_delivery as fixtures


class AdvisorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AdvisorDeliveryTests()
        self.fixture.setUp()
        self.fixture._schedule_second_wake()
        self.schedule = effect_followup_schedule_id(fixtures.PROJECT, "existing-decision")
        self.settings = {"id": "existing-paused-automation", "kind": "heartbeat", "name": "Existing",
            "prompt": "Use existing owner callback", "rrule": "existing", "status": "PAUSED",
            "targetThreadId": "manager-session", "notificationPolicy": "failed_runs_only"}
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store.create(Path(self.directory.name) / "owner.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        self.actor = AuthenticatedActor("owner-principal", "owner", "fixture")
        self.limits = LimitService(self.store)
        pool_ref = ResourceRef("owner", "limit", "existing-exhausted")
        pool = self.limits.create_pool(pool_ref, capacity_units=3, cumulative_allowance_units=3,
            logical_request_key="fixture-pool", actor=self.actor)
        held = self.limits.reserve(pool_ref, "fixture-consumed", 3,
            logical_request_key="fixture-reserve", actor=self.actor)
        self.limits.settle(held, 3, logical_request_key="fixture-settle", actor=self.actor)
        value = self.fixture.due_port.read_due("advisor-followup")
        value.update(schedule_id=self.schedule, purpose="advisor-effect-followup", host_state="paused",
                     stop_state="completed", allowance_ref=pool_ref.to_dict(),
                     target={**value["target"], "automation": self.settings})
        self.fixture.due_port.save_due(self.schedule, value, request_id="fixture-existing", expected_version=0)
        self.dispatch = Mock(side_effect=AssertionError("live dispatch must remain suppressed"))

    def call(self, operation="guard-exercise"):
        return exercise_advisor_lifecycle(
            request={"schedule_id": self.schedule, "decision_id": "existing-decision",
                     "automation_id": self.settings["id"], "operation": operation},
            pairing=self.fixture.pairing, advisor_principal="advisor-principal", actor="owner-principal",
            loop=self.fixture.loop, allowance=self.limits, authenticate=lambda _actor: self.actor,
            read_settings=lambda _id: self.settings, live_dispatch=self.dispatch)

    def test_actual_callback_guard_and_real_exhausted_reserve_reject_before_provider(self):
        before = self.fixture.due_port.read_due(self.schedule)
        result = self.call()
        self.assertEqual(result["live_callback"]["outcome"], "held")
        self.dispatch.assert_not_called()
        active = result["inert_callback_scenarios"]["active"]
        self.assertEqual(active["first_callback"]["outcome"], "unknown")
        self.assertIn("cumulative allowance is exhausted", json.dumps(active["first_callback"]))
        self.assertTrue(active["first_callback"]["dispatch"]["runtime_called"])
        self.assertEqual(active["restart_callback"]["outcome"], "reconcile")
        self.assertEqual(result["allowance_before"], result["allowance_after"])
        self.assertEqual(result["allowance_after"]["used"], 3)
        self.assertEqual(result["allowance_after"]["held"], 0)
        self.assertEqual(self.fixture.due_port.read_due(self.schedule), before)
        self.assertFalse(result["provider_called"])
        self.assertFalse(result["automation_activated"])
        self.assertFalse(result["host_connection"]["actual_host_callback_observed"])
        self.assertEqual(result["host_connection"]["evidence_status"], "required_evidence_gap")

    def test_pause_stop_and_completion_use_existing_guards_on_repeat(self):
        result = self.call()
        for name, expected in (("paused", "held"), ("stopped", "stopped"), ("completed", "stopped")):
            row = result["inert_callback_scenarios"][name]
            self.assertEqual(row["first_callback"]["outcome"], expected)
            self.assertEqual(row["restart_callback"]["outcome"], expected)
            self.assertFalse(row["first_callback"].get("dispatch", {}).get("runtime_called", False))
        self.dispatch.assert_not_called()

    def test_missing_host_capability_is_read_before_any_effect_claim_or_reservation(self):
        before = self.fixture.due_port.read_due(self.schedule)
        with patch.object(self.fixture.attention, "prepare_host") as prepare, \
                patch.object(self.fixture.attention, "check") as claim, \
                patch.object(type(self.limits), "reserve", create=True) as reserve:
            result = self.call("host-capability")
        self.assertEqual(result["outcome"], "unsupported")
        self.assertEqual(result["error"]["code"], "host_adapter_unavailable")
        self.assertFalse(result["host_connection"]["actual_host_callback_observed"])
        self.assertEqual(result["host_connection"]["evidence_status"], "required_evidence_gap")
        prepare.assert_not_called()
        claim.assert_not_called()
        reserve.assert_not_called()
        self.dispatch.assert_not_called()
        self.assertEqual(self.fixture.due_port.read_due(self.schedule), before)
        self.assertEqual(result["allowance"]["used"], 3)

    def test_persisted_settings_mismatch_rejects_before_callback(self):
        self.settings = {**self.settings, "targetThreadId": "foreign"}
        with self.assertRaisesRegex(ValueError, "persisted paused"):
            self.call()
        self.dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
