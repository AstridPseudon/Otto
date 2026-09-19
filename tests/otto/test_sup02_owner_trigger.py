"""SUP-02 owner-bound trigger seam proofs.

These tests exercise the existing DueRecord/StoreDueRecordPort-shaped path.
The recording host port is only a finite adapter fixture; it does not claim a
Python bridge to a native Codex conversation.
"""

from datetime import datetime, timezone

from otto.attention import (
    DueRecord,
    DurableAttention,
    InMemoryDueRecordPort,
    RecordingAttentionPort,
    RecordingHostTriggerPort,
)


NOW = datetime(2026, 9, 18, 19, 0, tzinfo=timezone.utc)


def _record(schedule_id="sup02", *, identity="invocation-1", target_id="manager-native-1", generation=2):
    return DueRecord(
        schedule_id=schedule_id,
        recipient="project-manager",
        instruction="perform the bounded manager check",
        message="perform the bounded manager check with this owner context",
        profile="normal",
        anchor="2026-09-18T18:00:00Z",
        due_at="2026-09-18T18:30:00Z",
        last_covered_slot=-1,
        invocation_identity=identity,
        target={"host": "codex", "native_id": target_id},
        role="manager",
        purpose="hourly-sense-check",
        lifecycle_owner="owner-01",
        owner="owner-01",
        project_ref="project-01",
        manager_ref="manager-01",
        generation=generation,
    )


def test_owner_configuration_is_serialized_and_delivery_is_idempotent():
    due = InMemoryDueRecordPort()
    attention = RecordingAttentionPort()
    host = RecordingHostTriggerPort()
    scheduler = DurableAttention(
        attention,
        due_port=due,
        host_port=host,
        host_mode="durable-host",
        clock=lambda: NOW,
    )
    record = _record()

    assert scheduler.schedule(record, request_id="schedule-sup02")["outcome"] == "scheduled"
    projected = scheduler.reconcile_host(record.schedule_id, request_id="host-ensure-1", lifecycle_owner="owner-01")
    assert projected["outcome"] == "reconciled"
    assert projected["host_state"] == "active"

    ready = scheduler.check(record.schedule_id, lifecycle_owner="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2)
    assert ready["outcome"] == "attention-ready"
    delivered_request = attention.requests[-1]
    assert delivered_request["message"] == record.message
    assert delivered_request["target"] == dict(record.target)
    assert delivered_request["role"] == "manager"
    assert delivered_request["purpose"] == "hourly-sense-check"
    assert scheduler.check(record.schedule_id, lifecycle_owner="owner-01")["readiness"]["status"] == "in-flight"
    assert len(attention.requests) == 1
    assert scheduler.complete(record.schedule_id, ready["request_id"], lifecycle_owner="owner-01", receipt={"completed": True})["outcome"] == "returned"
    assert scheduler.complete(record.schedule_id, ready["request_id"], lifecycle_owner="owner-01")["outcome"] == "replayed"


def test_reconfigure_requires_new_identity_and_current_owner_cas():
    due = InMemoryDueRecordPort()
    scheduler = DurableAttention(RecordingAttentionPort(), due_port=due, host_mode="durable-host", clock=lambda: NOW)
    original = _record()
    scheduler.schedule(original, request_id="schedule-reconfigure")

    changed_same_identity = _record(target_id="manager-native-2")
    rejected = scheduler.reconfigure(changed_same_identity, request_id="reconfigure-1", expected_version=1, actor="owner-01")
    assert rejected["outcome"] == "rejected"
    assert rejected["error"]["code"] == "configuration_identity_required"

    foreign = scheduler.reconfigure(_record(identity="invocation-2", target_id="manager-native-2"), request_id="reconfigure-foreign", expected_version=1, actor="other-owner")
    assert foreign["error"]["code"] == "foreign_authority"
    stale = scheduler.reconfigure(_record(identity="invocation-2", target_id="manager-native-2"), request_id="reconfigure-stale", expected_version=99, actor="owner-01")
    assert stale["error"]["code"] == "stale_version"

    updated = scheduler.reconfigure(_record(identity="invocation-2", target_id="manager-native-2"), request_id="reconfigure-good", expected_version=1, actor="owner-01")
    assert updated["outcome"] == "reconfigured"
    assert updated["record"]["target"]["native_id"] == "manager-native-2"
    assert updated["record"]["host_state"] == "unknown"


def test_generation_fencing_busy_and_offline_recovery_are_explicit():
    due = InMemoryDueRecordPort()
    attention = RecordingAttentionPort()
    host = RecordingHostTriggerPort()
    scheduler = DurableAttention(attention, due_port=due, host_port=host, host_mode="durable-host", clock=lambda: NOW)
    record = _record(schedule_id="recovery", generation=4)
    scheduler.schedule(record, request_id="schedule-recovery")

    stale = scheduler.check(record.schedule_id, generation=3)
    assert stale["outcome"] == "rejected"
    assert stale["error"]["code"] == "stale_generation"
    foreign = scheduler.check(record.schedule_id, lifecycle_owner="not-owner")
    assert foreign["error"]["code"] == "foreign_authority"

    host.available = False
    unavailable = scheduler.reconcile_host(record.schedule_id, request_id="host-offline", lifecycle_owner="owner-01")
    assert unavailable["outcome"] == "unavailable"
    assert unavailable["host_state"] == "failed"
    host.available = True
    recovered = scheduler.reconcile_host(record.schedule_id, request_id="host-recover", lifecycle_owner="owner-01")
    assert recovered["outcome"] == "reconciled"
    assert recovered["host_state"] == "active"

    ready = scheduler.check(record.schedule_id, generation=4, lifecycle_owner="owner-01")
    busy = scheduler.reconfigure(_record(schedule_id="recovery", identity="invocation-2", target_id="manager-native-2", generation=4), request_id="while-busy", expected_version=ready["record"]["version"], actor="owner-01")
    assert busy["outcome"] == "held"
    assert busy["error"]["code"] == "busy"
