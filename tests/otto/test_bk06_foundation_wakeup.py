"""Deterministic BK-06 foundation qualification fixtures."""

from datetime import datetime, timedelta, timezone

from otto.attention import DurableAttention, InMemoryDueRecordPort, RecordingAttentionPort


BASE = datetime(2026, 9, 18, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value=BASE):
        self.value = value

    def __call__(self):
        return self.value


def record(**changes):
    value = {
        "schedule_id": "project-manager-hourly",
        "recipient": "manager-native",
        "instruction": "inspect the project",
        "profile": "astra-high",
        "anchor": BASE.isoformat().replace("+00:00", "Z"),
        "interval_seconds": 3600,
        "last_covered_slot": 0,
        "invocation_identity": "logical-request-1",
        "project_ref": "project-1",
        "manager_ref": "manager-1",
        "generation": 1,
        "owner": "owner-1",
    }
    value.update(changes)
    from otto.attention import DueRecord
    return DueRecord(**value)


def setup(**changes):
    clock = Clock()
    attention = RecordingAttentionPort()
    due = InMemoryDueRecordPort()
    controller = DurableAttention(attention, due_port=due, clock=clock, host_mode="durable-host")
    item = record(**changes)
    assert controller.schedule(item, request_id="schedule-1")["outcome"] == "scheduled"
    return controller, attention, due, clock, item


def test_duplicate_wake_coalesces_logical_key_and_due_reasons():
    controller, attention, due, clock, item = setup()
    clock.value = BASE + timedelta(hours=1)
    first = controller.check(item.schedule_id, due_reason="hourly", project_ref="project-1", manager_ref="manager-1", generation=1)
    second = controller.check(item.schedule_id, due_reason="three-hour-review", project_ref="project-1", manager_ref="manager-1", generation=1)

    assert first["outcome"] == "attention-ready"
    assert second["outcome"] == "attention-ready"
    assert second["request_id"] == first["request_id"]
    assert second["replayed"] is True
    assert second["record"]["due_reasons"] == ["hourly", "three-hour-review"]
    assert len(attention.requests) == 1
    assert due.read_due(item.schedule_id)["in_flight_request"] == first["request_id"]


def test_offline_period_is_one_bounded_missed_cursor_and_next_slot_is_live():
    controller, attention, due, clock, item = setup()
    clock.value = BASE + timedelta(hours=4, minutes=1)
    missed = controller.mark_missed(item.schedule_id, reason="offline", project_ref="project-1", manager_ref="manager-1", generation=1)
    assert missed["outcome"] == "missed"
    assert missed["missed_slots"] == 3
    assert missed["record"]["last_covered_slot"] == 4
    assert missed["record"]["in_flight_request"] is None
    assert not attention.requests
    clock.value = BASE + timedelta(hours=5)
    ready = controller.check(item.schedule_id, due_reason="hourly", project_ref="project-1", manager_ref="manager-1", generation=1)
    assert ready["outcome"] == "attention-ready"
    assert ready["missed_slots"] == 0
    assert len(attention.requests) == 1


def test_delivery_completion_are_distinct_and_completion_failure_remains_reconcilable():
    controller, attention, due, clock, item = setup()
    clock.value = BASE + timedelta(hours=1)
    ready = controller.check(item.schedule_id, due_reason="hourly")
    assert ready["delivered_at"] is not None
    assert ready["delivery_evidence"]["event_ids"] == ["attention-event-1"]
    assert ready["completed_at"] is None
    request_id = ready["request_id"]
    rejected = controller.complete(item.schedule_id, request_id, project_ref="other-project", generation=1)
    assert rejected["outcome"] == "rejected"
    assert rejected["error"]["code"] == "scope_mismatch"
    failed = controller.complete(item.schedule_id, request_id, outcome="failed", completion_evidence={"error": "host lost"}, project_ref="project-1", manager_ref="manager-1", generation=1)
    assert failed["outcome"] == "completion-failed"
    assert failed["record"]["completion_state"] == "failed"
    assert failed["record"]["delivered_at"] is not None
    assert failed["record"]["completed_at"] is not None
    assert failed["record"]["in_flight_request"] == request_id
    returned = controller.complete(item.schedule_id, request_id, receipt={"native": "receipt-1"}, project_ref="project-1", manager_ref="manager-1", generation=1)
    assert returned["outcome"] == "returned"
    assert returned["record"]["completion_state"] == "succeeded"
    assert returned["record"]["in_flight_request"] is None


def test_restart_preserves_generation_and_stale_completion_is_fenced():
    controller, attention, due, clock, item = setup()
    clock.value = BASE + timedelta(hours=1)
    ready = controller.check(item.schedule_id, due_reason="hourly")
    reopened = DurableAttention(attention, due_port=due, clock=clock, host_mode="durable-host")
    resumed = reopened.resume(item.schedule_id)
    assert resumed["request_id"] == ready["request_id"]
    stale = reopened.complete(item.schedule_id, ready["request_id"], generation=2)
    assert stale["outcome"] == "rejected"
    assert stale["error"]["code"] == "stale_generation"
    assert due.read_due(item.schedule_id)["in_flight_request"] == ready["request_id"]


def test_quiet_unchanged_projection_has_no_notification_or_launch():
    controller, attention, due, clock, item = setup()
    quiet = controller.check(item.schedule_id, due_reason="hourly")
    assert quiet["outcome"] == "waiting"
    assert quiet["readiness"] == {"status": "waiting", "dispatch": False, "executable": False}
    assert quiet["automatic_action"] is False
    assert not attention.requests
