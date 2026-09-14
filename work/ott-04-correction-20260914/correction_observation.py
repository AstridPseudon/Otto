"""Raw OTT-04 correction observations using the shipped finite clients."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile


def safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    convert = getattr(value, "to_dict", None)
    if callable(convert):
        return safe(convert())
    if hasattr(value, "value"):
        return safe(value.value)
    return str(value)


def due_proof(root):
    from herzchen.command_ports import close_consumer_facade
    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService, domain_contribution as packet_contribution
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.kernel import Store
    from otto.attention import (
        DueRecord, DurableAttention, InputChangedError, SerializedAttentionPort,
        StateConflictError, due_record_contribution, issue_store_due_record_port,
    )

    authority = "ott04-correction-due"
    store = Store.create(root / "due.sqlite", authority=authority)
    due_domain = due_record_contribution()
    handler = store.register_domain_handler((content_contribution(), packet_contribution(), due_domain))
    actor = AuthenticatedActor(authority, "manager", "credential")
    content = ContentCommandHandler(store)
    subject = ContentDocument(ResourceRef(authority, "document", "subject"), "brief", "public", "read", "manager")
    revision = ContentRevision(subject.ref, "rev-1", {"title": "correction"}, actor, initial=True)
    content.execute(content.build_create_document(TransactionContext(actor, "setup", hashlib.sha256(b"setup").hexdigest()), subject, revision))
    packets = ContextPacketService(store)

    def create_attention(request):
        tx = TransactionContext(actor, request["request_id"], hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest())
        notice = packets.notify_amendment(subject.ref, revision.ref, (request["recipient"],), tx, reason=request["instruction"])[0]
        receipt = safe(notice["receipt"])
        return {"event_ids": receipt["event_ids"], "receipt": receipt, "outcome": "created"}

    port = issue_store_due_record_port(handler, actor)
    boundary = {
        "port_dir": dir(port),
        "has_writer": hasattr(port, "_writer"),
        "has_store": hasattr(port, "store"),
        "transport_endpoints": list(port.transport.endpoints),
        "transport_has_connection": hasattr(port.transport, "connection"),
        "transport_path_is_db": str(port.transport.socket_path).endswith((".sqlite", ".sqlite3", ".db")),
    }
    shared = SerializedAttentionPort(create_attention, lambda recipient: [safe(item) for item in packets.list_attention(recipient)])
    scheduler = DurableAttention(shared, due_port=port, host_mode="durable-host", clock=lambda: datetime(2026, 9, 14, 9, tzinfo=timezone.utc))
    record = DueRecord(
        schedule_id="correction-due", recipient="owner-1", instruction="inspect", profile="normal",
        anchor="2026-09-14T00:00:00Z", interval_seconds=3 * 60 * 60, last_covered_slot=0,
        invocation_identity="invocation-correction", owner="owner-1",
        return_condition="same owner returns the same request receipt",
    )
    before_count = len(store.list_events())
    scheduled = scheduler.schedule(record, request_id="request-A")
    receipt_a = safe(store.get_receipt("request-A"))
    later = record.to_dict()
    later["outstanding_decisions"] = [{"decision": "wait", "decision_id": "later", "recorded": True}]
    updated = port.save_due(record.schedule_id, later, request_id="request-B", expected_version=1)
    live_before_replay = port.read_due(record.schedule_id)
    before_replay_count = len(store.list_events())
    historical = port.save_due(record.schedule_id, record.to_dict(), request_id="request-A", expected_version=0)
    after_replay_count = len(store.list_events())
    precondition_error = None
    before_precondition_count = len(store.list_events())
    try:
        port.save_due(record.schedule_id, record.to_dict(), request_id="request-A", expected_version=99)
    except InputChangedError as exc:
        precondition_error = {"type": type(exc).__name__, "message": str(exc)}
    precondition_count = len(store.list_events())
    live_after_precondition = port.read_due(record.schedule_id)
    changed_error = None
    changed = record.to_dict(); changed["instruction"] = "changed"
    try:
        port.save_due(record.schedule_id, changed, request_id="request-A", expected_version=0)
    except InputChangedError as exc:
        changed_error = {"type": type(exc).__name__, "message": str(exc)}
    changed_count = len(store.list_events())
    cas_error = None
    try:
        port.save_due(record.schedule_id, record.to_dict(), request_id="request-C", expected_version=1)
    except StateConflictError as exc:
        cas_error = {"type": type(exc).__name__, "message": str(exc)}
    cas_count = len(store.list_events())
    scheduler.record_decision(record.schedule_id, decision_id="manager-wait", decision="wait", request_id="decision")
    ready = scheduler.check(record.schedule_id)
    before_restart = port.read_due(record.schedule_id)
    domains = store.registered_domains()
    store.close()
    reopened = Store.open(root / "due.sqlite", authority=authority, expected_domains=domains)
    reopened_port = issue_store_due_record_port(reopened.domain_handler((due_domain,)), actor)
    resumed = DurableAttention(shared, due_port=reopened_port, host_mode="durable-host").resume(record.schedule_id)
    reopened_record = reopened_port.read_due(record.schedule_id)
    close_consumer_facade(port.transport)
    close_consumer_facade(reopened_port.transport)
    reopened.close()
    return {
        "boundary": boundary,
        "capability": scheduled["capability"],
        "before": {"event_count": before_count, "record": None},
        "action_A": {"scheduled": scheduled, "receipt": receipt_a},
        "action_B": {"updated": updated, "live_before_replay": live_before_replay},
        "historical_replay_A": {"result": historical, "event_delta": after_replay_count - before_replay_count, "fresh_live_read": live_before_replay},
        "changed_expected_version_rejection": {"error": precondition_error, "event_delta": precondition_count - before_precondition_count, "live_version": live_after_precondition["version"]},
        "changed_input_rejection": {"error": changed_error, "event_delta": changed_count - precondition_count},
        "cas_rejection": {"error": cas_error, "event_delta": cas_count - changed_count},
        "ready_and_restart": {"ready": ready, "before_restart": before_restart, "resumed": resumed, "reopened_record": reopened_record},
    }


def amendment_proof(root):
    from herzchen.command_ports import close_consumer_facade
    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import domain_contribution as packet_contribution
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.kernel import Store
    from otto.attention import ImprovementPropagation, issue_store_amendment_port

    authority = "ott04-correction-amendment"
    store = Store.create(root / "amendment.sqlite", authority=authority)
    actor = AuthenticatedActor(authority, "manager", "credential")
    store.register_domain_handler((content_contribution(), packet_contribution()))
    graph = WorkGraph(store, actor=actor); graph.register()
    project = graph.create_project(title="plan", metadata={"ott04_usage_budget": {"spent": 3, "limit": 10}}, logical_request_key="project")
    task = graph.create_task(project, title="task", logical_request_key="task")
    assignments = ResponsibilityAssignments(store, actor=actor)
    assignment = assignments.assign(task, role="execution", principal="owner-1", agent="agent-1", session="session-1", pins=(task.ref,), logical_request_key="assignment")
    content = ContentCommandHandler(store)
    subject = ContentDocument(ResourceRef(authority, "document", "subject"), "brief", "public", "read", "owner-1")
    revision = ContentRevision(subject.ref, "rev-1", {"title": "amendment"}, actor, initial=True)
    content.execute(content.build_create_document(TransactionContext(actor, "setup", hashlib.sha256(b"setup").hexdigest()), subject, revision))
    amendment = issue_store_amendment_port(store, actor, project, assignment, subject.ref, revision.ref)
    propagation = ImprovementPropagation(amendment)
    handled = propagation.handle_review("review", recipient="owner-1", return_condition="manager selects an amendment")
    result = propagation.apply("review", decision_id="manager-decision", amendment={"instruction": "updated", "next_dispatch": "owner-review", "route": "owner-route"}, request_id="amendment")
    event_types = [event.event_type for event in store.list_events()]
    boundary = {"client_dir": dir(amendment), "has_callback": hasattr(amendment, "_apply"), "has_store": hasattr(amendment, "store"), "transport_endpoints": list(amendment.transport.endpoints)}
    close_consumer_facade(amendment.transport); store.close()
    return {"boundary": boundary, "handled_review": handled, "result": result, "event_types": event_types, "dispatch_event_present": "work.assignment.dispatched" in event_types}


with tempfile.TemporaryDirectory(prefix="ott04-correction-") as directory:
    import herzchen
    import otto
    import otto.attention
    root = Path(directory)
    print(json.dumps({"origins": {"otto": otto.__file__, "otto_attention": otto.attention.__file__, "herzchen": herzchen.__file__}, "due": due_proof(root), "amendment": amendment_proof(root)}, sort_keys=True, indent=2))
