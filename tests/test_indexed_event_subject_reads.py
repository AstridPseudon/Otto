"""Selected event identities must use persisted subject indexes, not history scans."""
import json
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from tests import test_execution_application as owner_fixture


class IndexedEventSubjectReadsTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store = self.f.store

    def test_subject_identity_union_preserves_history_order_and_filters(self):
        events = self.store.list_events()
        subjects = tuple(dict.fromkeys(e.subject for e in events))
        chosen = subjects[:2]
        identities = {(r.authority, r.kind, r.id) for r in chosen}
        expected = tuple(e for e in events if (e.subject.authority, e.subject.kind, e.subject.id) in identities)
        # Historical/current revision pins and duplicate subjects are selectors
        # of the same identity, never duplicate events or a narrower history.
        requested = tuple(ResourceRef(r.authority, r.kind, r.id, 'rev-999') for r in chosen) + chosen
        self.assertEqual(self.store.list_events(subjects=requested), expected)
        one = tuple(e for e in expected if e.subject.id == chosen[0].id and e.subject.kind == chosen[0].kind)
        self.assertEqual(self.store.list_events(subjects=(chosen[0],)), one)
        for event in expected:
            selected = self.store.list_events(stream=event.stream, subjects=requested, subject_kinds=(event.subject.kind,))
            self.assertEqual(selected, tuple(e for e in expected if e.stream == event.stream and e.subject.kind == event.subject.kind))
        self.assertEqual(self.store.list_events(subjects=()), ())
        with self.assertRaises(ValueError):
            self.store.list_events(subjects=(ResourceRef('foreign', chosen[0].kind, chosen[0].id),))

    def test_unrelated_large_history_growth_does_not_increase_selected_work(self):
        events = self.store.list_events()
        wanted, other = events[0], next(e for e in events if e.subject.id != events[0].subject.id)
        connection = self.store._connection
        template = dict(connection.execute('SELECT * FROM events WHERE event_id=?', (other.event_id,)).fetchone())
        columns = tuple(template)
        sql = 'INSERT INTO events (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')'
        position = connection.execute('SELECT max(append_position) FROM events').fetchone()[0]
        steps = []
        for target in (256, 2048):
            start = 0 if target == 256 else 256
            rows = []
            for n in range(start, target):
                row = dict(template, event_id='synthetic-unrelated-' + str(n), stream='synthetic-unrelated', sequence=n + 1,
                    append_position=position + n + 1, effects_json=json.dumps({'body': 'x' * 16384, 'decoy': wanted.subject.to_dict()}))
                rows.append(tuple(row[c] for c in columns))
            connection.executemany(sql, rows)
            expected = tuple(e for e in events if e.subject.kind == wanted.subject.kind and e.subject.id == wanted.subject.id)
            for subjects in ((wanted.subject,), (wanted.subject, wanted.subject)):
                count = []
                connection.set_progress_handler(lambda: count.append(1) or 0, 1)
                try:
                    with patch.object(self.store, '_event_from_row', wraps=self.store._event_from_row) as hydrate:
                        self.assertEqual(self.store.list_events(subjects=subjects), expected)
                        self.assertEqual(hydrate.call_count, len(expected))
                finally:
                    connection.set_progress_handler(None, 0)
                self.assertLess(len(count), 500)
                steps.append(len(count))
        self.assertLessEqual(max(steps[-2:]), max(steps[:2]) + 50)


if __name__ == '__main__':
    unittest.main()
