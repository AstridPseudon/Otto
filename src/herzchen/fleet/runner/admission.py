"""Queue admission: the head runs when it fits; later entries backfill only where they never delay the head."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Entry:
    """A queued run: its units and its arrival number."""

    run_id: str
    units: int
    seq: int


@dataclass(frozen=True)
class Holder:
    """A running holder of units; a backfilled holder was started ahead of the head."""

    units: int
    backfill: bool


def pick(queue: Sequence[Entry], holders: Sequence[Holder], capacity: int) -> tuple[Entry, bool] | None:
    """The entry to start next and whether it is a backfill, or None.

    A backfilled entry is admitted only if the head still fits beside it and every other backfilled
    holder, so a backfill never delays the head. Callers clamp units to 1..capacity first.
    """
    if not queue:
        return None
    free = capacity - sum(holder.units for holder in holders)
    head = queue[0]
    if head.units <= free:
        return head, False
    room = capacity - head.units - sum(holder.units for holder in holders if holder.backfill)
    limit = min(room, free)
    for entry in queue[1:]:
        if entry.units <= limit:
            return entry, True
    return None
