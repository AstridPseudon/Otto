"""Focused D04 fixtures for retained host effects and Due coalescing."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import unittest

from otto.attention import (DueRecord, DurableAttention, InMemoryDueRecordPort,
                            RecordingAttentionPort, reminder_continuity_view)
from otto.host_bridge import DeterministicHostExecutor


NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def record(*, host_state="unknown", last_covered_slot=-1, interval_seconds=60):
    return DueRecord(
        schedule_id="reminder", recipient="manager", instruction="Inspect progress",
        profile="read-only", anchor=(NOW - timedelta(seconds=120)).isoformat(),
        last_covered_slot=last_covered_slot, interval_seconds=interval_seconds,
        due_at=None, invocation_identity="reminder-v1", project_ref="project",
        manager_ref="manager", lifecycle_owner="manager", host_state=host_state,
        target={"host": "local", "native_id": "manager-session", "automation": {
            "id": "automation-1", "name": "Reminder", "kind": "heartbeat",
            "prompt": "Inspect progress", "rrule": "FREQ=MINUTELY",
            "status": "ACTIVE", "targetThreadId": "manager-thread"}},
        role="manager", purpose="reminder", message="Inspect progress",
    )


class ReminderContinuityTests(unittest.TestCase):
    def setUp(self):
        self.due = InMemoryDueRecordPort()
        self.attention = DurableAttention(RecordingAttentionPort(), due_port=self.due,
                                           clock=lambda: NOW, host_mode="durable-host")
        self.attention.schedule(record(), request_id="create-reminder")
        self.settings = {
            "id": "automation-1", "name": "Reminder", "kind": "heartbeat",
            "prompt": "Inspect progress", "rrule": "FREQ=MINUTELY",
            "status": "ACTIVE", "targetThreadId": "manager-thread",
        }
        self.updates = []

    def executor(self, *, read, updates=None):
        updates = self.updates if updates is None else updates

        def update(request):
            updates.append(dict(request))
            self.settings.update(request)
            return {"id": request["id"]}

        def acknowledge(effect, observation):
            current = self.attention._read(effect.schedule_id)
            return self.attention.acknowledge_host(
                effect.schedule_id, request_id=effect.request_id,
                expected_version=current.version, actor="manager", observed=observation,
            )

        return DeterministicHostExecutor(update, read, acknowledge)

    def test_status_keeps_absent_wake_unknown_and_separates_due_fields(self):
        status = self.attention.reminder_status("reminder")
        self.assertEqual(status["last_observed_host_wake"]["state"], "unknown")
        self.assertIsNone(status["last_observed_host_wake"]["at"])
        self.assertEqual(status["last_admitted_due_occurrence"]["state"], "unknown")
        self.assertIn("desired_configuration", status)
        self.assertIn("delivery", status)

    def test_initial_covered_slot_without_request_or_completion_stays_unknown(self):
        status = reminder_continuity_view(record(host_state="active", last_covered_slot=0))
        self.assertEqual(status["last_admitted_due_occurrence"], {
            "state": "unknown", "slot": None, "at": None, "request_id": None,
        })

    def test_startup_holds_unknown_host_without_automation_id_before_due(self):
        current = self.attention._read("reminder")
        self.due.save_due(
            "reminder",
            replace(current, target={"host": "local", "native_id": "manager-session"}).to_dict(),
            request_id="remove-automation-id",
            expected_version=current.version,
        )

        result = self.attention.startup_reconcile(["reminder"], evaluate_due=True, now=NOW)

        self.assertEqual(result["outcome"], "held")
        self.assertEqual(result["admission"], "held")
        self.assertEqual(result["rows"][0]["due"]["outcome"], "held")
        self.assertIsNone(result["rows"][0]["status"]["delivery"]["request_id"])
        self.assertEqual(self.attention._read("reminder").last_covered_slot, -1)

    def test_startup_reconciles_lost_update_response_without_mutation_replay(self):
        lost = {"value": True}

        def read(_effect, _response):
            if lost["value"]:
                raise RuntimeError("lost readback")
            return {**self.settings, "state": self.settings["status"].lower(),
                    "observed_at": NOW.isoformat()}

        first = self.executor(read=read)
        prepared = self.attention.prepare_host("reminder", request_id="pause-reminder",
            actor="manager", expected_version=self.attention._read("reminder").version,
            desired_state="paused")
        first_receipt = first.execute(prepared["effect"])
        self.assertEqual(first_receipt["outcome"], "response_lost")
        self.assertEqual(len(self.updates), 1)

        # The new host process only performs retained readback.  It cannot
        # call automation_update because reconcile_retained_bridge requires
        # the executor's recovery operation.
        lost["value"] = False
        self.settings["status"] = "PAUSED"
        recovered = self.attention.startup_reconcile(["reminder"], executor=first)
        self.assertEqual(recovered["outcome"], "reconciled", recovered)
        self.assertEqual(len(self.updates), 1)
        status = self.attention.reminder_status("reminder")
        self.assertEqual(status["last_observed_host_wake"]["state"], "observed")
        self.assertEqual(status["last_observed_host_wake"]["at"], NOW.isoformat())

    def test_missed_slots_coalesce_and_paused_schedule_is_held(self):
        self.due.save_due("reminder", {**self.due.read_due("reminder"),
            "host_state": "active"}, request_id="activate-host", expected_version=1)
        ready = self.attention.startup_reconcile(["reminder"], evaluate_due=True, now=NOW)
        self.assertEqual(ready["outcome"], "reconciled")
        self.assertEqual(ready["rows"][0]["due"]["missed_slots"], 2)
        admitted = self.attention.reminder_status("reminder")
        self.assertEqual(admitted["last_admitted_due_occurrence"]["state"], "admitted")

        paused = DueRecord.from_dict({**self.due.read_due("reminder"), "host_state": "paused"})
        self.due.save_due("reminder", paused.to_dict(), request_id="pause-owner",
                          expected_version=paused.version)
        held = self.attention.startup_reconcile(["reminder"], evaluate_due=True, now=NOW)
        self.assertEqual(held["outcome"], "held")
        self.assertEqual(held["rows"][0]["due"]["reason"], "paused_or_unknown_host")

    def test_mismatched_readback_remains_held_without_recreating_schedule(self):
        current = self.attention._read("reminder")
        prepared = self.attention.prepare_host("reminder", request_id="active-reminder",
            actor="manager", expected_version=current.version, desired_state="active")
        executor = self.executor(read=lambda _effect, _response: {
            **self.settings, "state": "active", "prompt": "different"})
        result = self.attention.startup_reconcile(["reminder"], executor=executor,
                                                  evaluate_due=True, now=NOW)
        self.assertEqual(result["outcome"], "held")
        self.assertEqual(result["rows"][0]["bridge"]["reason"],
                         "missing_or_mismatched_readback")
        self.assertEqual(self.updates, [])


if __name__ == "__main__":
    unittest.main()
