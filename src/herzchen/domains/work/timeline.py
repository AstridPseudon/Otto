"""Task timeline: one bounded read of an assignment's events in the Store.

A task's Store events sit on three streams that share its assignment id:
``assignment:<id>`` (created, reassigned, resources adopted), ``dispatch:<id>``
(dispatched) and ``report:<id>`` (reports appended). The read pages each stream
through EventCursorReader, the reader decisions.py uses to reconcile attention,
so PERCH and ``otto status`` ask the Store the same question the same way.

The events are a projection: nothing is written, and a stream whose sequence has
a hole is reported as a gap rather than papered over. Events from different
streams are ordered by recorded_at, then stream and sequence, because the
envelope does not carry the Store's global append position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, Tuple

from herzchen.kernel import EventCursorReader, Store

TASK_STREAM_PREFIXES = ("assignment:", "dispatch:", "report:")
TASK_STREAM_PREFIX = "assignment:"
PAGE_LIMIT = 200


@dataclass(frozen=True)
class TimelineEvent:
    stream: str
    sequence: int
    event_type: str
    operation: str
    recorded_at: str
    effects: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelineGap:
    stream: str
    gap_from: int
    gap_to: int


@dataclass(frozen=True)
class TaskTimeline:
    task_id: str
    events: Tuple[TimelineEvent, ...]
    gaps: Tuple[TimelineGap, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.gaps


def task_timeline(store: Store, task_id: str, *, limit: int = PAGE_LIMIT) -> TaskTimeline:
    """Every event of one assignment across its task streams, paged to the end."""
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-blank string")
    reader = EventCursorReader(store)
    events = []
    gaps = []
    for prefix in TASK_STREAM_PREFIXES:
        stream = prefix + task_id
        cursor = None
        while True:
            page = reader.page(stream, cursor=cursor, limit=limit)
            if page.status == "gap":
                gaps.append(TimelineGap(stream, page.gap_from, page.gap_to))
            events.extend(
                TimelineEvent(e.stream, e.sequence, e.event_type, e.operation, e.recorded_at, dict(e.effects or {}))
                for e in page.events
            )
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
    events.sort(key=lambda e: (e.recorded_at, e.stream, e.sequence))
    return TaskTimeline(task_id, tuple(events), tuple(gaps))


def task_ids(store: Store) -> Tuple[str, ...]:
    """The assignment ids the Store holds, from its assignment streams, in id order."""
    ids = {e.stream[len(TASK_STREAM_PREFIX):] for e in store.list_events() if e.stream.startswith(TASK_STREAM_PREFIX)}
    return tuple(sorted(ids))


def timelines(store: Store, tasks: Sequence[str] = ()) -> Tuple[TaskTimeline, ...]:
    """The timeline of each named task, or of every task the Store holds when none are named."""
    return tuple(task_timeline(store, task) for task in (tuple(tasks) or task_ids(store)))
