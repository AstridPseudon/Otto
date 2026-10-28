## 1. Design, in implementation order

1. `src/herzchen/kernel/store.py:2680` → Add `page_events` alongside `list_events`. Require a scope: exact stream, event types, or subjects. Support top-level text predicates in `effects` (for `association` and `recipient`), exact revision-pinned subjects, and `after_sequence` for an initial exact-stream read. Use a scope-bound cursor containing `(stream, sequence)` and an `append_position` watermark. Select at most `limit + 1` **metadata rows**, then hydrate only the returned page. Preserve `list_events` ordering: `(store_authority, stream, sequence)`. Share predicate validation with `list_events` rather than maintaining two interpretations of a selector.
2. `src/herzchen/kernel/store.py:2663` → Add `page_event_streams(prefix, cursor, limit)`, selecting distinct stream names from event metadata with a keyset cursor and the same watermark rule. No event bodies are needed.
3. `src/herzchen/kernel/store.py:2849` and `:2962`; `src/herzchen/content/packets.py:88` → Forward `page_events` through the existing handler/reader capabilities and declare it on `FNDPacketWriter`. Keep the existing exact-stream `EventCursorReader` for timeline gap detection.
4. `src/herzchen/content/packets.py:457` → For backlinks, obtain candidate association IDs using the existing current-identity lookup for the requested document, then page **both** `dat.content.linked` and `dat.content.unlinked` events whose `effects.association` is a candidate. Keep the current per-event association, target, subject, and visibility checks, and append in event order. Do not collapse events to one current association row: the present reader can emit multiple rows for one active association.
5. `src/herzchen/content/packets.py:636` → Page created and resolved attention events; apply the recipient predicate before hydration when supplied. Fold pages into the existing `latest` dict in order, preserving last-event state and first-insertion output order.
6. `src/herzchen/content/packets.py:650` → For no cursor, page events for the **exact pinned** input refs and collect IDs. With an `EventCursor`, page its entire stream after its sequence, regardless of input refs. Preserve both branches’ current order and membership.
7. `src/herzchen/domains/work/timeline.py:80` → Drain `page_event_streams("assignment:")` and return the same sorted IDs. Add caller tests for visibility, link/unlink and resolution history, exact pinned refs, cursor deltas, and task discovery. Leave existing assertions intact.

The page selector should use the existing `events` table and indexes. It needs no new event table, projection, or schema revision.

## 2. Failing test to write first

Add `tests/test_eventpage.py` with this test. It uses a Python profile hook to count hydration calls; it does not patch a product method or use a timing threshold.

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.contracts.model import EventEnvelope
from herzchen.domains.work.timeline import task_ids
from herzchen.kernel import Store


class EventPageTests(unittest.TestCase):
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
```

## 3. Delete

Delete the four unscoped `list_events()` reads at `packets.py:462`, `:638`, `:655`, and `timeline.py:82`, including their broad Python-side event filtering.

## 4. Plausible mistake

Selecting only current association or attention identities would lose unlink and resolution events; selecting backlink events by subject instead of `effects.association` would also change what the current reader means by an association event. The test retains link–unlink–link and create–resolve sequences, puts 30,000 same-type decoys behind the selectors, checks cursor completion, and requires only seven relevant bodies to be hydrated.

## 5. D19 expectation changes

None proposed. Existing assertions in `tests/test_perch_timeline.py:39–99` and `tests/test_execution_application.py:681` should still hold. If implementation changes an existing assertion, that test file needs a written D19 decision.

## 6. Row corrections on `canon/main`

`list_events` already has subject and subject-kind predicates (`store.py:2680–2726`), and exact-stream reads already have cursor paging (`recovery.py:914–978`). `task_timeline` itself uses that paging (`timeline.py:55–77`); its implicit task discovery at `:82` is the ledger-wide hydration. The existing cursor reader’s default visibility filter is `("public",)` (`recovery.py:775–777`), so using it unchanged for packet deltas would silently omit events. Also, `packets.py:51–54` declares attention creation but no resolution writer, although `list_attention` reads resolved events.

I inspected `canon/main` only. I made no changes and ran no tests.