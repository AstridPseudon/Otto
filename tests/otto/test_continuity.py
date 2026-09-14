"""OTT-04 representative product proof.

This file starts with the real installed Herzchen attention path.  Additional
state-machine coverage is added only after this path is green.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest


AUTHORITY = "ott04-real-attention"


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    if hasattr(value, "value"):
        return _json_value(value.value)
    return str(value)


def test_real_installed_shared_attention_survives_reopen(tmp_path):
    """Use only finite serialized callbacks at the Otto consumer boundary."""

    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService, domain_contribution as packet_contribution
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.kernel import EventCursorReader, EventFilter, Store
    from otto.attention import DueRecord, DurableAttention, SerializedAttentionPort

    path = tmp_path / "attention.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    store.register_domain_handler((content_contribution(), packet_contribution()))
    actor = AuthenticatedActor(AUTHORITY, "manager", "credential-manager")
    content = ContentCommandHandler(store)
    subject = ContentDocument(ResourceRef(AUTHORITY, "document", "subject"), "brief", "public", "read", "manager")
    revision = ContentRevision(subject.ref, "rev-1", {"title": "attention subject"}, actor, initial=True)
    context = TransactionContext(actor, "setup", hashlib.sha256(b"setup").hexdigest())
    content.execute(content.build_create_document(context, subject, revision))
    packets = ContextPacketService(store)

    def create_attention(request):
        request = dict(request)
        request_context = TransactionContext(
            actor,
            request["request_id"],
            hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
        )
        notices = packets.notify_amendment(
            subject.ref,
            revision.ref,
            (request["recipient"],),
            request_context,
            reason=request["instruction"],
        )
        notice = notices[0]
        return {
            "outcome": "created",
            "attention_ref": _json_value(notice["attention_ref"]),
            "receipt": _json_value(notice["receipt"]),
            "event_ids": list(_json_value(notice["receipt"]).get("event_ids", [])),
        }

    def read_attention(recipient):
        return [_json_value(item) for item in packets.list_attention(recipient)]

    # This is the consumer-facing object: finite JSON request/response methods,
    # with no Store, DB descriptor, generic writer, or callback engine exposed.
    shared = SerializedAttentionPort(create_attention, read_attention)
    now = __import__("datetime").datetime(2026, 9, 14, 2, tzinfo=__import__("datetime").timezone.utc)
    scheduler = DurableAttention(shared, host_mode="awaited", clock=lambda: now)
    record = DueRecord(
        schedule_id="one-off-real",
        recipient="owner-1",
        instruction="source-updated",
        profile="normal",
        anchor="2026-09-14T00:00:00Z",
        due_at="2026-09-14T01:00:00Z",
        last_covered_slot=-1,
        invocation_identity="invocation-real-1",
        owner="owner-1",
        return_condition="owner returns the same invocation receipt",
    )
    scheduled = scheduler.schedule(record, request_id="schedule-real")
    before_events = len(store.list_events())
    ready = scheduler.check(record.schedule_id)
    after_events = len(store.list_events())

    assert scheduled["outcome"] == "scheduled"
    assert ready["outcome"] == "attention-ready"
    assert ready["readiness"] == {"status": "attention", "dispatch": False, "executable": False}
    assert ready["notification"]["receipt"]["event_ids"]
    assert after_events == before_events + 1
    assert ready["event_ids"] == ready["notification"]["receipt"]["event_ids"]
    assert shared.__dict__.keys() == {"_create", "_read"}
    assert not hasattr(shared, "store")
    assert len(shared.list_attention("owner-1")) == 1

    event = next(item for item in store.list_events() if item.event_id == ready["event_ids"][0])
    cursor_reader = EventCursorReader(store, clock=lambda: now)
    event_filter = EventFilter()
    from otto.attention import CursorContinuity

    continuity = CursorContinuity(
        cursor_reader.page,
        authority=AUTHORITY,
        stream=event.stream,
        event_filter=event_filter,
    )
    cursor_result = continuity.read()
    assert cursor_result["outcome"] == "ok", cursor_result
    assert cursor_result["events"], cursor_result
    assert cursor_result["events"][0]["event_id"] == event.event_id, cursor_result
    assert cursor_result["acknowledged"] is False
    assert continuity.acknowledge()["acknowledged"] is True

    persisted_events = [_json_value(event) for event in store.list_events()]
    domains = store.registered_domains()
    store.close()
    reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    reopened_packets = ContextPacketService(reopened)
    reopened_attention = [_json_value(item) for item in reopened_packets.list_attention("owner-1")]
    assert len(reopened_attention) == 1
    assert reopened_attention[0]["state"] == "open"
    assert [_json_value(event) for event in reopened.list_events()] == persisted_events
    reopened.close()


class _Clock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _due_record(schedule_id: str, *, interval_seconds=None, due_at=None) -> "DueRecord":
    from otto.attention import DueRecord

    return DueRecord(
        schedule_id=schedule_id,
        recipient="owner-1",
        instruction="inspect readiness",
        profile="normal",
        anchor="2026-01-01T00:00:00Z",
        due_at=due_at or (None if interval_seconds is not None else "2026-01-01T01:00:00Z"),
        interval_seconds=interval_seconds,
        last_covered_slot=0 if interval_seconds is not None else -1,
        invocation_identity="logical-agent-1",
        owner="owner-1",
        missing_handoff=None,
        return_condition="same owner returns the same request receipt",
    )


def test_durable_intervals_coalesce_restart_and_complete_once():
    from otto.attention import DurableAttention, InMemoryDueRecordPort, RecordingAttentionPort

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = _Clock(base)
    due_port = InMemoryDueRecordPort()
    attention = RecordingAttentionPort()
    first = DurableAttention(attention, due_port=due_port, clock=clock, host_mode="durable-host")
    record = _due_record("three-hours", interval_seconds=3 * 60 * 60)

    assert first.schedule(record, request_id="schedule-three-hours")["outcome"] == "scheduled"
    clock.value = base + timedelta(hours=9)
    ready = first.check(record.schedule_id)
    assert ready["outcome"] == "attention-ready"
    assert ready["missed_slots"] == 2
    request_id = ready["request_id"]
    assert first.check(record.schedule_id)["request_id"] == request_id
    assert len(attention.requests) == 1

    unknown = first.complete(record.schedule_id, request_id, outcome="unknown")
    assert unknown["outcome"] == "reconcile"
    assert unknown["relaunch"] is False
    assert first.resume(record.schedule_id)["request_id"] == request_id
    returned = first.complete(record.schedule_id, request_id, receipt={"event_ids": ["receipt-1"]})
    assert returned["outcome"] == "returned"
    assert first.complete(record.schedule_id, request_id)["outcome"] == "replayed"
    assert len(attention.requests) == 1

    # A new process/object sees the same durable anchor and outstanding state.
    clock.value = base + timedelta(hours=12)
    reopened = DurableAttention(attention, due_port=due_port, clock=clock, host_mode="durable-host")
    next_ready = reopened.check(record.schedule_id)
    assert next_ready["outcome"] == "attention-ready"
    assert next_ready["missed_slots"] == 0
    assert next_ready["request_id"] != request_id
    assert len(attention.requests) == 2

    # Another interval uses the identical state machine, with no wall-clock sleep.
    alternate = _due_record("ninety-minutes", interval_seconds=90 * 60)
    assert reopened.schedule(alternate, request_id="schedule-ninety")["outcome"] == "scheduled"
    clock.value = base + timedelta(hours=4, minutes=31)
    alternate_ready = reopened.check(alternate.schedule_id)
    assert alternate_ready["outcome"] == "attention-ready"
    assert alternate_ready["missed_slots"] == 2


def test_one_off_replay_input_rejection_stop_and_unavailable_host():
    from otto.attention import DurableAttention, InMemoryDueRecordPort, InputChangedError, RecordingAttentionPort

    due_port = InMemoryDueRecordPort()
    attention = RecordingAttentionPort()
    clock = _Clock(datetime(2026, 1, 1, 2, tzinfo=timezone.utc))
    scheduler = DurableAttention(attention, due_port=due_port, clock=clock, host_mode="durable-host")
    record = _due_record("one-off")
    assert scheduler.schedule(record, request_id="schedule-one")["outcome"] == "scheduled"
    assert scheduler.schedule(record, request_id="schedule-one")["outcome"] == "replayed"
    with pytest.raises(InputChangedError):
        scheduler.schedule(_due_record("one-off", due_at="2026-01-01T03:00:00Z"), request_id="schedule-other")
    ready = scheduler.check("one-off")
    assert ready["outcome"] == "attention-ready"
    assert scheduler.stop("one-off", request_id="stop-one")["outcome"] == "stopped"
    assert scheduler.check("one-off")["outcome"] == "stopped"

    unavailable = DurableAttention(attention, host_mode="durable-host", host_available=False)
    assert unavailable.schedule(_due_record("unavailable"))["outcome"] == "unavailable"
    missing_port = DurableAttention(attention, host_mode="durable-host")
    assert missing_port.schedule(_due_record("missing-port"))["outcome"] == "unavailable"


def test_no_auto_action_decision_and_truthful_unknown_launch():
    from otto.attention import DurableAttention, InMemoryDueRecordPort, RecordingAttentionPort

    clock = _Clock(datetime(2026, 1, 1, 2, tzinfo=timezone.utc))
    scheduler = DurableAttention(
        RecordingAttentionPort(),
        due_port=InMemoryDueRecordPort(),
        clock=clock,
        host_mode="durable-host",
    )
    record = _due_record("decision")
    scheduler.schedule(record, request_id="schedule-decision")
    ready = scheduler.check(record.schedule_id)
    assert ready["readiness"]["dispatch"] is False
    assert ready["readiness"]["executable"] is False
    decision = scheduler.record_decision(record.schedule_id, decision_id="manager-decision-1", decision="wait", request_id="decision-request")
    assert decision["outcome"] == "decision-recorded"
    assert decision["manager_created"] is False
    assert decision["task_created"] is False
    assert decision["budget_reserved"] is False
    assert scheduler.complete(record.schedule_id, ready["request_id"], outcome="crashed")["relaunch"] is False
    resumed = scheduler.resume(record.schedule_id)
    assert resumed["outcome"] == "resume-same-request"
    assert resumed["relaunch"] is False


def test_review_handling_is_distinct_and_amendment_propagation_preserves_pins():
    from otto.attention import ImprovementPropagation

    views = {
        "plan": "plan-v1",
        "next_dispatch": "dispatch-v1",
        "attention": "attention-v1",
        "assignment": "owner-1",
        "current_owner": "owner-1",
        "usage": {"spent": 3},
        "running_input_pins": ["input-rev-1"],
    }

    class Amendment:
        def apply_amendment(self, request):
            assert request["manager_decision"] == "implement"
            views.update({
                "plan": "plan-v2",
                "next_dispatch": "dispatch-v2",
                "attention": "attention-v2",
                "assignment": "owner-1-amended-view",
            })
            return {"event_ids": ["amendment-event-1"], "receipt": {"request_id": request["request_id"]}}

    propagation = ImprovementPropagation(Amendment(), lambda: dict(views))
    handled = propagation.handle_review("review-1", recipient="owner-1", return_condition="source changes")
    assert handled["implemented_improvement"] is False
    implemented = propagation.apply("review-1", decision_id="manager-decision-1", amendment={"title": "tighten plan"}, request_id="amend-1")
    assert implemented["outcome"] == "improvement-implemented"
    assert implemented["implemented_improvement"] is True
    assert all(implemented["required_changes"].values())
    assert all(implemented["preserved"].values())
    assert implemented["response"]["event_ids"] == ["amendment-event-1"]

    class Incomplete:
        def apply_amendment(self, request):
            return {"event_ids": [], "incomplete": True}

    incomplete = ImprovementPropagation(Incomplete(), lambda: dict(views)).apply(
        "review-1", decision_id="manager-decision-2", amendment={"title": "not propagated"}, request_id="amend-2"
    )
    assert incomplete["outcome"] == "incomplete-propagation"
    assert incomplete["implemented_improvement"] is False


def test_cursor_duplicate_gap_expiry_and_scope_are_recoverable():
    from types import SimpleNamespace

    from otto.attention import CursorContinuity

    pages = [
        SimpleNamespace(events=(SimpleNamespace(event_id="e1", sequence=1, to_dict=lambda: {"event_id": "e1", "sequence": 1}),), cursor="c1", next_cursor=None, status="ok", gap_from=None, gap_to=None),
        SimpleNamespace(events=(SimpleNamespace(event_id="e1", sequence=1, to_dict=lambda: {"event_id": "e1", "sequence": 1}),), cursor="c1", next_cursor=None, status="ok", gap_from=None, gap_to=None),
        SimpleNamespace(events=(), cursor="c2", next_cursor=None, status="gap", gap_from=2, gap_to=3),
    ]

    def page(*_args, **_kwargs):
        return pages.pop(0)

    continuity = CursorContinuity(page, authority="authority-1", stream="stream-1", event_filter={"event_types": []})
    assert continuity.read()["outcome"] == "ok"
    assert continuity.read(cursor="c1")["outcome"] == "duplicate-read"
    assert continuity.read(cursor="c1")["outcome"] == "gap"

    class CursorExpiredError(RuntimeError):
        pass

    def expired(*_args, **_kwargs):
        raise CursorExpiredError("cursor has expired")

    expired_reader = CursorContinuity(expired, authority="authority-1", stream="stream-1")
    result = expired_reader.read(cursor="expired")
    assert result["outcome"] == "cursor-error"
    assert result["error"]["code"] == "expired"
    assert result["recoverable"] is True
