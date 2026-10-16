"""Store-backed regressions for generic asking waits and event long-polling."""
import tempfile
import threading
import unittest
from pathlib import Path

from herzchen.contracts import AuthenticatedActor, EventEnvelope, ResourceRef
from herzchen.domains.work.decisions import WorkDecisions
from herzchen.domains.work.module import contributions
from herzchen.kernel import CursorScopeError, EventCursorReader, EventFilter, Store


class AskKernelWaitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store.create(Path(self.temporary.name) / "events.sqlite", authority="ask-kernel-test")
        self.store.register_domain_handler(contributions())
        self.addCleanup(self.store.close)
        self.addCleanup(self.temporary.cleanup)

    def identity(self, kind, identifier):
        ref = ResourceRef(self.store.authority, kind, identifier, "rev-1")
        self.store.put_identity(ref, {"record_type": kind, "fixture": True})
        return ref

    def test_wait_record_round_trips_exact_assignment_session_generation_and_never_dispatches(self):
        task = self.identity("test.task", "asking-task")
        awaited = self.identity("test.obligation", "human-answer")
        assignment = self.identity("test.assignment", "asking-assignment")
        decisions = WorkDecisions(self.store)

        waiting = decisions.record_wait(
            task,
            missing_obligation="human answer",
            owner="person-17",
            awaited_ref=awaited,
            asking_assignment_ref=assignment,
            asking_session_id="native-session-42",
            asking_generation=7,
            logical_request_key="ask-binding-roundtrip",
        )
        reopened = decisions.get_wait(waiting.ref)

        self.assertEqual(reopened.asking_assignment_ref, assignment)
        self.assertEqual(reopened.asking_session_id, "native-session-42")
        self.assertEqual(reopened.asking_generation, 7)
        self.assertFalse(reopened.dispatch)
        self.assertIs(reopened.payload["dispatch"], False)
        self.assertIsNone(reopened.payload["allowance"])
        self.assertIsNone(reopened.payload["reservation_ref"])
        self.assertIs(reopened.payload["launch"], False)
        self.assertEqual([event.event_type for event in self.store.list_events(stream="attention:" + task.id)], ["work.wait.recorded"])

    def test_wait_returns_filtered_answer_event_and_preserves_cursor_scope(self):
        subject = self.identity("test.task", "asking-task")
        stream = "attention:" + subject.id
        actor = AuthenticatedActor("ask-kernel-test", "human", "credential")
        reader = EventCursorReader(self.store)
        answer_filter = EventFilter(event_types=("ask.answer.recorded",))
        initial = reader.page(stream, event_filter=answer_filter).cursor

        def append(sequence, event_type):
            self.store.append_event(EventEnvelope(
                event_id="event-{}".format(sequence), store_authority=self.store.authority,
                stream=stream, subject=subject, schema_revision="test.v1", event_type=event_type,
                sequence=sequence, actor=actor, operation="ask.answer.record", correlation_id=None,
                causation_id=None, recorded_at="2026-10-16T00:00:00Z", effects={"visibility": "public"},
            ))

        append(1, "unrelated.activity")
        append(2, "ask.answer.recorded")
        result = reader.wait(stream, cursor=initial, event_filter=answer_filter, timeout_seconds=0)

        self.assertEqual([event.event_type for event in result.events], ["ask.answer.recorded"])
        self.assertEqual(result.events[0].sequence, 2)
        self.assertEqual(result.status, "ok")
        timed_out = reader.wait(stream, cursor=result.cursor, event_filter=answer_filter, timeout_seconds=0)
        self.assertEqual(timed_out.status, "timeout")
        self.assertEqual(timed_out.events, ())
        with self.assertRaises(CursorScopeError):
            reader.wait(stream, cursor=initial, event_filter=EventFilter(event_types=("other.answer",)), timeout_seconds=0)

    def test_cursor_wait_and_store_write_share_serialized_sqlite_access(self):
        subject = self.identity("test.task", "concurrent-asking-task")
        stream = "attention:" + subject.id
        actor = AuthenticatedActor("ask-kernel-test", "human", "credential")
        reader = EventCursorReader(self.store)
        event_filter = EventFilter(event_types=("ask.answer.recorded",))
        cursor = reader.page(stream, event_filter=event_filter).cursor
        entered_wait = threading.Event()
        result = []
        errors = []

        def wait_for_answer():
            entered_wait.set()
            try:
                result.append(reader.wait(stream, cursor=cursor, event_filter=event_filter,
                                          timeout_seconds=1, poll_interval_seconds=0.005))
            except BaseException as exc:
                errors.append(exc)

        waiter = threading.Thread(target=wait_for_answer)
        waiter.start()
        self.assertTrue(entered_wait.wait(1))
        self.store.append_event(EventEnvelope(
            event_id="concurrent-answer", store_authority=self.store.authority,
            stream=stream, subject=subject, schema_revision="test.v1", event_type="ask.answer.recorded",
            sequence=1, actor=actor, operation="ask.answer.record", correlation_id=None,
            causation_id=None, recorded_at="2026-10-16T00:00:00Z", effects={"visibility": "public"},
        ))
        waiter.join(2)
        self.assertFalse(waiter.is_alive(), "event cursor wait did not return after the concurrent write")
        self.assertEqual(errors, [])
        self.assertEqual([event.event_id for event in result[0].events], ["concurrent-answer"])


if __name__ == "__main__":
    unittest.main()
