"""The task timeline read: one assignment's events across its streams, paged, with gaps reported."""
import shutil
import tempfile
import unittest
from pathlib import Path

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.contracts.model import EventEnvelope
from herzchen.domains.work.timeline import TASK_STREAM_PREFIXES, task_ids, task_timeline, timelines
from herzchen.kernel import Store

AUTHORITY = "owner"
ACTOR = AuthenticatedActor(AUTHORITY, "perch-test", "perch-test-credential")


class TaskTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perch-timeline-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = Store.create(self.tmp / "owner.sqlite", authority=AUTHORITY)
        self.addCleanup(self.store.close)
        self.counts = {}
        self.admitted = set()

    def append(self, stream, event_type, task_id, n):
        self.counts[stream] = self.counts.get(stream, 0) + 1
        seq = self.counts[stream]
        subject = ResourceRef(AUTHORITY, "work.assignment", task_id, "rev-1")
        if task_id not in self.admitted:
            self.store.put_identity(subject, {"task": task_id})
            self.admitted.add(task_id)
        event = EventEnvelope(
            "%s-%d" % (stream, seq), AUTHORITY, stream, subject,
            "work.assignment.v1", event_type, seq, ACTOR, event_type, None, None,
            "2026-10-16T10:%02d:%02dZ" % (n // 60, n % 60), None, (), (), {"n": n},
        )
        return self.store.append_event(event)

    def test_one_assignment_reads_its_three_streams_in_order(self):
        self.append("assignment:t1", "work.assignment.created", "t1", 0)
        self.append("dispatch:t1", "work.assignment.dispatched", "t1", 1)
        self.append("report:t1", "work.report.appended", "t1", 2)
        self.append("assignment:t1", "work.assignment.reassigned", "t1", 3)
        self.append("assignment:other", "work.assignment.created", "other", 4)
        timeline = task_timeline(self.store, "t1")
        self.assertEqual([e.event_type for e in timeline.events], [
            "work.assignment.created", "work.assignment.dispatched", "work.report.appended", "work.assignment.reassigned",
        ])
        self.assertEqual({e.stream for e in timeline.events}, {"assignment:t1", "dispatch:t1", "report:t1"})
        self.assertTrue(timeline.complete)
        self.assertEqual(timeline.events[1].effects, {"n": 1})

    def test_paging_reaches_the_end_of_a_long_stream(self):
        for n in range(7):
            self.append("assignment:t2", "work.assignment.created" if n == 0 else "work.assignment.reassigned", "t2", n)
        timeline = task_timeline(self.store, "t2", limit=2)
        self.assertEqual(len(timeline.events), 7)
        self.assertEqual([e.sequence for e in timeline.events], list(range(1, 8)))
        self.assertTrue(timeline.complete)

    def test_a_hole_at_the_start_of_a_stream_is_a_gap_not_silence(self):
        self.append("assignment:t3", "work.assignment.created", "t3", 0)
        self.append("assignment:t3", "work.assignment.reassigned", "t3", 1)
        self.store.connection.execute(
            "DELETE FROM events WHERE store_authority = ? AND stream = ? AND sequence = 1", (AUTHORITY, "assignment:t3"))
        timeline = task_timeline(self.store, "t3")
        self.assertFalse(timeline.complete)
        self.assertEqual([(g.stream, g.gap_from, g.gap_to) for g in timeline.gaps], [("assignment:t3", 1, 1)])
        self.assertEqual([e.sequence for e in timeline.events], [2])

    def test_task_ids_come_from_the_assignment_streams(self):
        self.append("assignment:b", "work.assignment.created", "b", 0)
        self.append("dispatch:b", "work.assignment.dispatched", "b", 1)
        self.append("assignment:a", "work.assignment.created", "a", 2)
        self.append("work:p", "work.project.created", "p", 3)
        self.assertEqual(task_ids(self.store), ("a", "b"))
        self.assertEqual([t.task_id for t in timelines(self.store)], ["a", "b"])
        self.assertEqual([t.task_id for t in timelines(self.store, ["b"])], ["b"])

    def test_an_empty_store_has_no_tasks(self):
        self.assertEqual(task_ids(self.store), ())
        self.assertEqual(timelines(self.store), ())
        empty = task_timeline(self.store, "missing")
        self.assertEqual(empty.events, ())
        self.assertTrue(empty.complete)

    def test_blank_task_id_is_refused(self):
        with self.assertRaises(ValueError):
            task_timeline(self.store, " ")

    def test_the_read_writes_nothing(self):
        self.append("assignment:t4", "work.assignment.created", "t4", 0)
        before = self.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        task_timeline(self.store, "t4")
        timelines(self.store)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], before)

    def test_the_prefixes_are_the_three_task_streams(self):
        self.assertEqual(TASK_STREAM_PREFIXES, ("assignment:", "dispatch:", "report:"))


if __name__ == "__main__":
    unittest.main()
