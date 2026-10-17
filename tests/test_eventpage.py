import json
import sys
import tempfile
import unittest
from pathlib import Path

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.contracts.model import EventCursor, EventEnvelope
from herzchen.contracts import TransactionContext
from herzchen.content.model import domain_contribution as content_domain_contribution
from herzchen.content.packets import ContextPacketService, domain_contribution as packet_domain_contribution
from herzchen.domains.work.timeline import task_ids
from herzchen.kernel import Store


class EventPageTests(unittest.TestCase):
    @staticmethod
    def _append(store, actor, stream, sequence, event_id, subject, kind, effects):
        identity = ResourceRef(subject.authority, subject.kind, subject.id)
        if store.get_identity(identity) is None:
            store.put_identity(identity, {"id": subject.id})
        store.append_event(EventEnvelope(
            event_id, store.authority, stream, subject, "test.v1", kind,
            sequence, actor, kind, None, None, "2026-10-17T00:00:00Z",
            None, (), (), effects))

    @staticmethod
    def _packet_service(store):
        store.register_domain_handler((content_domain_contribution(), packet_domain_contribution()))
        return ContextPacketService(store)

    def test_scoped_pages_keep_history_without_unrelated_body_hydration(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                edge = ResourceRef("owner", "document-association", "edge", "r1")
                notice = ResourceRef("owner", "dat.context.attention", "notice", "r1")
                task = ResourceRef("owner", "work.assignment", "t", "r1")
                for ref in (edge, notice, task):
                    store.put_identity(ref, {"id": ref.id})

                rows = (
                    ("attention:a", 1, "created", notice,
                     "dat.context.attention.created", {"recipient": "alice", "state": "open"}),
                    ("attention:a", 2, "resolved", notice,
                     "dat.context.attention.resolved", {"recipient": "alice", "state": "resolved"}),
                    ("assignment:t", 1, "task", task,
                     "work.assignment.created", {}),
                    ("content:edge", 1, "link-1", edge,
                     "dat.content.linked", {"association": "edge", "active": True}),
                    ("content:edge", 2, "unlink", edge,
                     "dat.content.unlinked", {"association": "edge", "active": False}),
                    ("content:edge", 3, "link-2", edge,
                     "dat.content.linked", {"association": "edge", "active": True}),
                )
                for stream, sequence, event_id, subject, kind, effects in rows:
                    store.append_event(EventEnvelope(
                        event_id, "owner", stream, subject, "test.v1", kind,
                        sequence, actor, kind, None, None,
                        "2026-10-17T00:00:00Z", None, (), (), effects))

                connection = store.connection
                template = dict(connection.execute(
                    "SELECT * FROM events WHERE event_id = 'link-1'").fetchone())
                columns = tuple(template)
                sql = ("INSERT INTO events (" + ",".join(columns) + ") VALUES (" +
                       ",".join("?" for _ in columns) + ")")
                position = connection.execute(
                    "SELECT MAX(append_position) FROM events").fetchone()[0]

                def decoys():
                    for n in range(30000):
                        is_link = n < 15000
                        row = dict(
                            template, event_id=f"unrelated-{n}",
                            append_position=position + n + 1,
                            stream="noise:link" if is_link else "noise:attention",
                            sequence=n + 1 if is_link else n - 14999,
                            event_type=("dat.content.linked" if is_link
                                        else "dat.context.attention.created"),
                            effects_json=json.dumps({
                                "association": "other", "recipient": "bob",
                                "body": "x" * 256,
                            }),
                        )
                        yield tuple(row[column] for column in columns)

                connection.executemany(sql, decoys())
                hydrations = [0]
                original_profile = sys.getprofile()

                def profile(frame, event, arg):
                    if event == "call" and frame.f_code is Store._event_from_row.__code__:
                        hydrations[0] += 1

                def collect(**scope):
                    cursor, found = None, []
                    while True:
                        page = store.page_events(cursor=cursor, limit=2, **scope)
                        self.assertLessEqual(len(page.events), 2)
                        found.extend(event.event_id for event in page.events)
                        if page.next_cursor is None:
                            return found
                        self.assertNotEqual(page.next_cursor, cursor)
                        cursor = page.next_cursor

                sys.setprofile(profile)
                try:
                    self.assertEqual(collect(
                        event_types=("dat.content.linked", "dat.content.unlinked"),
                        effect_text={"association": ("edge",)}),
                        ["link-1", "unlink", "link-2"])
                    self.assertEqual(collect(
                        event_types=("dat.context.attention.created",
                                     "dat.context.attention.resolved"),
                        effect_text={"recipient": ("alice",)}),
                        ["created", "resolved"])
                    self.assertEqual(
                        [e.event_id for e in store.page_events(
                            stream="content:edge", after_sequence=1,
                            limit=2).events],
                        ["unlink", "link-2"])
                    self.assertEqual(task_ids(store), ("t",))
                finally:
                    sys.setprofile(original_profile)
                self.assertEqual(hydrations[0], 7)
            finally:
                store.close()

    def test_event_page_cursor_binds_scope_and_watermark(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                subject = ResourceRef("owner", "test.subject", "s", "r1")
                self._append(store, actor, "a:stream", 1, "one", subject, "test.changed", {})
                self._append(store, actor, "b:stream", 1, "two", subject, "test.changed", {})
                first = store.page_events(event_types=("test.changed",), limit=1)
                self.assertEqual([event.event_id for event in first.events], ["one"])
                self.assertIsNotNone(first.next_cursor)

                self._append(store, actor, "c:stream", 1, "late", subject, "test.changed", {})
                with self.assertRaises(ValueError):
                    store.page_events(event_types=("test.other",), cursor=first.next_cursor, limit=1)
                second = store.page_events(event_types=("test.changed",), cursor=first.next_cursor, limit=1)
                self.assertEqual([event.event_id for event in second.events], ["two"])
                self.assertIsNone(second.next_cursor)
            finally:
                store.close()

    def test_exact_stream_after_sequence_continues_across_pages(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                subject = ResourceRef("owner", "test.subject", "s", "r1")
                for sequence in range(1, 5):
                    self._append(store, actor, "one:stream", sequence, f"event-{sequence}",
                                 subject, "test.changed", {})
                page = store.page_events(stream="one:stream", after_sequence=1, limit=1)
                found = [event.event_id for event in page.events]
                self.assertEqual(found, ["event-2"])
                while page.next_cursor is not None:
                    page = store.page_events(stream="one:stream", after_sequence=1,
                                             cursor=page.next_cursor, limit=1)
                    found.extend(event.event_id for event in page.events)
                self.assertEqual(found, ["event-2", "event-3", "event-4"])
            finally:
                store.close()

    def test_explicit_empty_selector_values_match_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                subject = ResourceRef("owner", "test.subject", "s", "r1")
                self._append(store, actor, "one:stream", 1, "event", subject, "test.changed", {})
                self.assertEqual(store.page_events(stream="one:stream", subjects=(), limit=5).events, ())
                self.assertEqual(store.page_events(stream="one:stream", event_types=(), limit=5).events, ())
            finally:
                store.close()

    def test_event_stream_prefix_treats_percent_and_underscore_literally(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                subject = ResourceRef("owner", "test.subject", "s", "r1")
                self._append(store, actor, "assignment:100%_done", 1, "literal", subject, "test.changed", {})
                self._append(store, actor, "assignment:100XYdone", 1, "wildcard", subject, "test.changed", {})
                page = store.page_event_streams("assignment:100%_", limit=5)
                self.assertEqual(page.streams, ("assignment:100%_done",))
            finally:
                store.close()

    def test_page_events_matches_exact_pinned_subject_revision(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                pin = ResourceRef("owner", "test.subject", "same", "r1")
                other_revision = ResourceRef("owner", "test.subject", "same", "r2")
                self._append(store, actor, "one", 1, "pinned", pin, "test.changed", {})
                self._append(store, actor, "two", 1, "other-revision", other_revision, "test.changed", {})
                page = store.page_events(subjects=(pin,), limit=10)
                self.assertEqual([event.event_id for event in page.events], ["pinned"])
            finally:
                store.close()

    def test_multi_pin_subject_page_orders_streams_and_excludes_revision_decoy(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                pin_a = ResourceRef("owner", "test.subject", "a", "r1")
                pin_b = ResourceRef("owner", "test.subject", "b", "r3")
                decoy = ResourceRef("owner", "test.subject", "a", "r2")
                self._append(store, actor, "z:stream", 1, "b-later", pin_b, "test.changed", {})
                self._append(store, actor, "a:stream", 1, "a-first", pin_a, "test.changed", {})
                self._append(store, actor, "a:stream", 2, "a-second", pin_a, "test.changed", {})
                self._append(store, actor, "a:stream", 3, "wrong-revision", decoy, "test.changed", {})
                page = store.page_events(subjects=(pin_a, pin_b), limit=10)
                self.assertEqual([event.event_id for event in page.events],
                                 ["a-first", "a-second", "b-later"])
            finally:
                store.close()

    def test_page_event_streams_are_distinct_prefix_scoped_and_watermarked(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                subject = ResourceRef("owner", "test.subject", "s", "r1")
                self._append(store, actor, "assignment:a", 1, "a1", subject, "test.changed", {})
                self._append(store, actor, "assignment:a", 2, "a2", subject, "test.changed", {})
                self._append(store, actor, "assignment:b", 1, "b1", subject, "test.changed", {})
                self._append(store, actor, "dispatch:a", 1, "d1", subject, "test.changed", {})
                first = store.page_event_streams("assignment:", limit=1)
                self.assertEqual(first.streams, ("assignment:a",))
                self.assertIsNotNone(first.next_cursor)
                self._append(store, actor, "assignment:c", 1, "c1", subject, "test.changed", {})
                second = store.page_event_streams("assignment:", cursor=first.next_cursor, limit=1)
                self.assertEqual(second.streams, ("assignment:b",))
                self.assertIsNone(second.next_cursor)
            finally:
                store.close()

    def test_backlinks_preserve_link_history_and_filter_hidden_subjects(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                target = ResourceRef("owner", "dat.content.document", "target")
                visible_subject = ResourceRef("owner", "dat.content.document", "visible")
                hidden_subject = ResourceRef("owner", "dat.content.document", "hidden")
                store.put_identity(target, {"document": {"visibility": "public"}})
                store.put_identity(visible_subject, {"document": {"visibility": "public"}})
                store.put_identity(hidden_subject, {"document": {"visibility": "private", "maintainer": "other"}})

                for association_id, subject_ref in (("edge", visible_subject), ("secret", hidden_subject)):
                    store.put_identity(ResourceRef("owner", "document-association", association_id), {
                        "association": {"document": {"ref": target.to_dict()},
                                        "subject": subject_ref.to_dict(), "namespace": "test", "key": association_id},
                        "active": True,
                    })
                for sequence, event_id, kind, association_id, active in (
                    (1, "link-1", "dat.content.linked", "edge", True),
                    (2, "unlink", "dat.content.unlinked", "edge", False),
                    (3, "link-2", "dat.content.linked", "edge", True),
                    (4, "hidden-link", "dat.content.linked", "secret", True),
                ):
                    self._append(store, actor, "content:links", sequence, event_id,
                                 ResourceRef("owner", "document-association", association_id),
                                 kind, {"association": association_id, "active": active})

                rows = self._packet_service(store).visible_backlinks(target, actor="reader")
                self.assertEqual([row["association"].id for row in rows], ["edge", "edge", "edge"])
            finally:
                store.close()

    def test_attention_history_folds_in_event_order_and_filters_recipient(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                first = ResourceRef("owner", "dat.context.attention", "first", "r1")
                second = ResourceRef("owner", "dat.context.attention", "second", "r1")
                self._append(store, actor, "attention", 1, "alice-created", first,
                             "dat.context.attention.created", {"recipient": "alice", "state": "open"})
                self._append(store, actor, "attention", 2, "bob-created", second,
                             "dat.context.attention.created", {"recipient": "bob", "state": "open"})
                self._append(store, actor, "attention", 3, "alice-resolved", first,
                             "dat.context.attention.resolved", {"recipient": "alice", "state": "resolved"})
                service = self._packet_service(store)
                self.assertEqual(service.list_attention("alice"), ())
                self.assertEqual([row["attention_ref"].id for row in service.list_attention()], ["second"])
            finally:
                store.close()

    def test_responsibility_view_uses_pins_without_cursor_and_full_stream_with_cursor(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store.create(Path(root) / "owner.sqlite", authority="owner")
            try:
                actor = AuthenticatedActor("owner", "reader", "credential")
                source = ResourceRef("owner", "test.source", "input", "r1")
                source_other_revision = ResourceRef("owner", "test.source", "input", "r2")
                unrelated = ResourceRef("owner", "test.source", "unrelated", "r1")
                store.put_identity(source, {"id": source.id, "content_digest": "a" * 64})
                store.put_identity(unrelated, {"id": unrelated.id, "content_digest": "a" * 64})
                service = self._packet_service(store)
                context = TransactionContext(actor, "packet-request", "b" * 64)
                packet = service.create_packet("packet", context, (source,), visibility="public")
                self._append(store, actor, "source-history", 1, "exact-pin", source, "test.changed", {})
                self._append(store, actor, "source-history", 2, "other-pin", source_other_revision, "test.changed", {})
                self._append(store, actor, "source-history", 3, "unrelated", unrelated, "test.changed", {})
                self.assertEqual(service.responsibility_view(packet["packet_ref"], actor="reader")["cursor_delta"],
                                 ("exact-pin",))
                cursor = EventCursor("owner", "source-history", 1)
                self.assertEqual(service.responsibility_view(packet["packet_ref"], actor="reader", cursor=cursor)["cursor_delta"],
                                 ("other-pin", "unrelated"))
            finally:
                store.close()
