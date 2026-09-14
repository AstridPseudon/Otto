"""Installed-wheel real Store/packet/event observation for OTT-04."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile


def value(item):
    if item is None or isinstance(item, (str, int, float, bool)):
        return item
    if isinstance(item, dict):
        return {str(key): value(v) for key, v in item.items()}
    if isinstance(item, (tuple, list)):
        return [value(v) for v in item]
    method = getattr(item, "to_dict", None)
    if callable(method):
        return value(method())
    if hasattr(item, "value"):
        return value(item.value)
    return str(item)


def main() -> None:
    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.kernel import EventCursorReader, EventFilter, Store
    from otto.attention import CursorContinuity, DueRecord, DurableAttention, SerializedAttentionPort

    authority = "ott04-real-observation"
    with tempfile.TemporaryDirectory(prefix="ott04-real-") as directory:
        database = Path(directory) / "store.sqlite"
        store = Store.create(database, authority=authority)
        store.register_domain_handler((content_contribution(), __import__("herzchen.content.packets", fromlist=["domain_contribution"]).domain_contribution(),))
        actor = AuthenticatedActor(authority, "manager", "credential-manager")
        content = ContentCommandHandler(store)
        document = ContentDocument(ResourceRef(authority, "document", "subject"), "brief", "public", "read", "manager")
        revision = ContentRevision(document.ref, "rev-1", {"title": "real attention subject"}, actor, initial=True)
        content.execute(content.build_create_document(TransactionContext(actor, "setup", hashlib.sha256(b"setup").hexdigest()), document, revision))
        packets = ContextPacketService(store)

        def create(request):
            request = dict(request)
            context = TransactionContext(actor, request["request_id"], hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest())
            notice = packets.notify_amendment(document.ref, revision.ref, (request["recipient"],), context, reason=request["instruction"])[0]
            receipt = value(notice["receipt"])
            return {"outcome": "created", "attention_ref": value(notice["attention_ref"]), "receipt": receipt, "event_ids": receipt["event_ids"]}

        shared = SerializedAttentionPort(create, lambda recipient: [value(item) for item in packets.list_attention(recipient)])
        now = datetime(2026, 9, 14, 2, tzinfo=timezone.utc)
        scheduler = DurableAttention(shared, clock=lambda: now, host_mode="awaited")
        record = DueRecord("real-one-off", "owner-1", "source-updated", "normal", "2026-09-14T00:00:00Z", -1, "invocation-real", due_at="2026-09-14T01:00:00Z", owner="owner-1")
        scheduler.schedule(record, request_id="schedule-real")
        before = len(store.list_events())
        ready = scheduler.check(record.schedule_id)
        event = next(item for item in store.list_events() if item.event_id == ready["event_ids"][0])
        reader = EventCursorReader(store, clock=lambda: now)
        continuity = CursorContinuity(reader.page, authority=authority, stream=event.stream, event_filter=EventFilter())
        cursor = continuity.read()
        persisted = [value(item) for item in store.list_events()]
        domains = store.registered_domains()
        store.close()
        reopened = Store.open(database, authority=authority, expected_domains=domains)
        reopened_attention = [value(item) for item in ContextPacketService(reopened).list_attention("owner-1")]
        print(json.dumps({
            "mode": "awaited",
            "host_capability": scheduler.capability,
            "before_event_count": before,
            "after_event_count": len(persisted),
            "ready": {"outcome": ready["outcome"], "request_id": ready["request_id"], "event_ids": ready["event_ids"], "readiness": ready["readiness"]},
            "cursor": {"outcome": cursor["outcome"], "events": cursor["events"], "acknowledged": cursor["acknowledged"], "authority": cursor["authority"], "stream": cursor["stream"]},
            "reopened_attention": reopened_attention,
            "consumer_boundary": {"fields": sorted(shared.__dict__), "has_store": hasattr(shared, "store")},
            "persisted_event_count_after_reopen": len(reopened.list_events()),
        }, ensure_ascii=False, sort_keys=True))
        reopened.close()


if __name__ == "__main__":
    main()
