"""Fresh OTT-04 product observations for the continuation handoff."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile


def safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return safe(to_dict())
    return str(value)


def due_observation(root: Path):
    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService, domain_contribution as packet_contribution
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.kernel import Store
    from otto.attention import (
        DueRecord, DurableAttention, InputChangedError, SerializedAttentionPort,
        StateConflictError, StoreDueRecordPort, due_record_contribution,
    )

    authority = "ott04-observation-due"
    path = root / "due.sqlite"
    store = Store.create(path, authority=authority)
    due_domain = due_record_contribution()
    handler = store.register_domain_handler((content_contribution(), packet_contribution(), due_domain))
    actor = AuthenticatedActor(authority, "manager", "credential-manager")
    content = ContentCommandHandler(store)
    subject = ContentDocument(ResourceRef(authority, "document", "subject"), "brief", "public", "read", "manager")
    revision = ContentRevision(subject.ref, "rev-1", {"title": "durable observation subject"}, actor, initial=True)
    content.execute(content.build_create_document(TransactionContext(actor, "setup", hashlib.sha256(b"setup").hexdigest()), subject, revision))
    packets = ContextPacketService(store)

    def create_attention(request):
        tx = TransactionContext(actor, request["request_id"], hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest())
        notice = packets.notify_amendment(subject.ref, revision.ref, (request["recipient"],), tx, reason=request["instruction"])[0]
        receipt = safe(notice["receipt"])
        return {"outcome": "created", "event_ids": receipt.get("event_ids", []), "receipt": receipt}

    shared = SerializedAttentionPort(create_attention, lambda recipient: [safe(item) for item in packets.list_attention(recipient)])
    port = StoreDueRecordPort(handler, actor)
    clock = lambda: datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
    scheduler = DurableAttention(shared, due_port=port, clock=clock, host_mode="durable-host")
    record = DueRecord(
        schedule_id="observed-due", recipient="owner-1", instruction="inspect durable state", profile="normal",
        anchor="2026-09-14T00:00:00Z", interval_seconds=3 * 60 * 60, last_covered_slot=0,
        invocation_identity="invocation-observed", owner="owner-1",
        return_condition="owner-1 returns the same recorded request receipt",
    )
    before = {"event_count": len(store.list_events()), "record": port.read_due(record.schedule_id)}
    scheduled = scheduler.schedule(record, request_id="schedule-observed")
    schedule_receipt = safe(store.get_receipt("schedule-observed"))
    after_schedule = {"event_count": len(store.list_events()), "record": port.read_due(record.schedule_id)}
    replay = port.save_due(record.schedule_id, record.to_dict(), request_id="schedule-observed", expected_version=0)
    replay_event_count = len(store.list_events())
    changed_error = None
    changed = record.to_dict()
    changed["instruction"] = "changed input"
    try:
        port.save_due(record.schedule_id, changed, request_id="schedule-observed", expected_version=0)
    except InputChangedError as exc:
        changed_error = {"type": type(exc).__name__, "message": str(exc)}
    changed_event_count = len(store.list_events())
    cas_error = None
    try:
        port.save_due(record.schedule_id, record.to_dict(), request_id="stale-cas", expected_version=0)
    except StateConflictError as exc:
        cas_error = {"type": type(exc).__name__, "message": str(exc)}
    cas_event_count = len(store.list_events())
    decision = scheduler.record_decision(record.schedule_id, decision_id="manager-wait", decision="wait", request_id="decision-observed")
    ready = scheduler.check(record.schedule_id)
    receipt_ids = [safe(store.get_receipt(key)) for key in ("schedule-observed", "decision:decision-observed", "check:" + ready["request_id"])]
    before_restart = port.read_due(record.schedule_id)
    events_before_restart = [safe(event) for event in store.list_events()]
    domains = store.registered_domains()
    store.close()
    reopened = Store.open(path, authority=authority, expected_domains=domains)
    reopened_port = StoreDueRecordPort(reopened.domain_handler((due_domain,)), actor)
    resumed = DurableAttention(shared, due_port=reopened_port, clock=clock, host_mode="durable-host").resume(record.schedule_id)
    reopened_record = reopened_port.read_due(record.schedule_id)
    resumed_scheduler = DurableAttention(shared, due_port=reopened_port, clock=clock, host_mode="durable-host")
    returned = resumed_scheduler.complete(record.schedule_id, ready["request_id"], receipt=ready["notification"]["receipt"])
    final_record = reopened_port.read_due(record.schedule_id)
    reopened.close()
    return {
        "mode": "durable-host",
        "capability": scheduled["capability"],
        "before": before,
        "action": {"schedule": scheduled, "decision": decision, "ready": ready},
        "fresh_after_schedule": after_schedule,
        "replay": {"record": replay, "event_count": replay_event_count, "delta": replay_event_count - after_schedule["event_count"]},
        "changed_input_rejection": {"error": changed_error, "event_count": changed_event_count, "delta": changed_event_count - replay_event_count},
        "cas_rejection": {"error": cas_error, "event_count": cas_event_count, "delta": cas_event_count - changed_event_count},
        "restart": {"before": before_restart, "events_before": events_before_restart, "resumed": resumed, "fresh_after_reopen": reopened_record},
        "completion": {"returned": returned, "fresh_after_completion": final_record},
        "receipt_event_linkage": receipt_ids,
        "attention_event_ids": ready["notification"]["event_ids"],
        "missed_slots": ready["missed_slots"],
        "automatic_action": False,
    }


def amendment_observation(root: Path):
    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService, domain_contribution as packet_contribution
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.domains.work.sheet import ProjectSheet
    from herzchen.kernel import Store
    from otto.attention import ImprovementPropagation, SerializedAmendmentPort

    authority = "ott04-observation-amendment"
    store = Store.create(root / "amendment.sqlite", authority=authority)
    actor = AuthenticatedActor(authority, "manager", "credential-manager")
    store.register_domain_handler((content_contribution(), packet_contribution()))
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(title="continuity plan", metadata={"ott04_usage_budget": {"spent": 3, "limit": 10}}, logical_request_key="project")
    task = graph.create_task(project, title="inspect source", logical_request_key="task")
    assignments = ResponsibilityAssignments(store, actor=actor)
    assignment = assignments.assign(task, role="execution", principal="owner-1", agent="agent-1", session="session-1", pins=(task.ref,), logical_request_key="assignment")
    sheet = ProjectSheet(store, actor=actor)
    content = ContentCommandHandler(store)
    subject = ContentDocument(ResourceRef(authority, "document", "subject"), "brief", "public", "read", "owner-1")
    revision = ContentRevision(subject.ref, "rev-1", {"title": "amendment subject"}, actor, initial=True)
    content.execute(content.build_create_document(TransactionContext(actor, "setup", hashlib.sha256(b"setup").hexdigest()), subject, revision))
    packets = ContextPacketService(store)

    def views():
        fresh_project = graph.get(project.ref)
        fresh_assignment = assignments.get(assignment.ref)
        fresh_sheet = sheet.export(fresh_project, task_refs=[task.ref])
        usage = fresh_project.payload.get("metadata", {}).get("ott04_usage_budget", {})
        return safe({
            "plan": {"task": fresh_sheet.tasks[0]["authored"].get("body")},
            "next_dispatch": fresh_project.payload.get("last_batch", {}).get("manager_action"),
            "attention": packets.list_attention("owner-1"),
            "assignment": {"route_binding": fresh_assignment.payload.get("route_binding"), "principal": fresh_assignment.principal, "agent": fresh_assignment.agent, "session": fresh_assignment.session},
            "current_owner": fresh_assignment.principal,
            "usage": {"budget": fresh_project.payload.get("budget"), "spent": usage.get("spent"), "limit": usage.get("limit")},
            "running_input_pins": [pin.to_dict() for pin in fresh_assignment.pins],
        })

    def apply_real(request):
        amendment = request["amendment"]
        plan = sheet.apply(project, {"tasks": [{"id": task.id, "body": {"instructions": amendment["instruction"]}}]}, logical_request_key=request["request_id"] + ":plan", next_action=amendment["next_dispatch"], actor=actor)
        route = sheet.pin_assignment_route(assignment, {"name": amendment["route"], "reason": "manager-selected amendment"}, logical_request_key=request["request_id"] + ":route", actor=actor)
        context = TransactionContext(actor, request["request_id"] + ":attention", hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest())
        notices = packets.notify_amendment(subject.ref, revision.ref, ("owner-1",), context, reason="manager-selected amendment")
        return {"event_ids": list(safe(plan.receipt).get("event_ids", ())) + list(safe(route.receipt).get("event_ids", ())) + [event_id for notice in notices for event_id in safe(notice["receipt"]).get("event_ids", ())], "receipts": {"plan": safe(plan.receipt), "assignment": safe(route.receipt), "attention": [safe(notice["receipt"]) for notice in notices]}, "incomplete": False, "automatic_action": False, "dispatch": False}

    propagation = ImprovementPropagation(SerializedAmendmentPort(apply_real), views)
    handled = propagation.handle_review("review-1", recipient="owner-1", return_condition="manager selects an amendment")
    before_events = len(store.list_events())
    result = propagation.apply("review-1", decision_id="manager-decision-1", amendment={"instruction": "inspect amended source", "next_dispatch": "owner-review", "route": "owner-review-route"}, request_id="amendment-1")
    event_types = [event.event_type for event in store.list_events()]
    store.close()
    return {"handled_review": handled, "before_event_count": before_events, "result": result, "event_types": event_types, "dispatch_event_present": "work.assignment.dispatched" in event_types, "automatic_action": False}


with tempfile.TemporaryDirectory(prefix="ott04-observation-") as directory:
    root = Path(directory)
    import herzchen
    import otto
    import otto.attention
    print(json.dumps({
        "origins": {"otto": otto.__file__, "otto_attention": otto.attention.__file__, "herzchen": herzchen.__file__},
        "due": due_observation(root),
        "amendment": amendment_observation(root),
    }, sort_keys=True, indent=2))
