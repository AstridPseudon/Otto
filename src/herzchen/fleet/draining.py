"""Drain queued fleet admissions without starting their effects."""
from __future__ import annotations

from typing import Any, Callable, Generic, MutableMapping, TypeVar


Key = TypeVar("Key")
Entry = TypeVar("Entry")


class QueuedAdmissionDrain(Generic[Key, Entry]):
    """Share a lock with the admission fence and final start transition.

    The caller owns the queue and the closing flag. It supplies the running
    predicate and settlement callback so this mechanism has no opinion about
    effect receipts, durable requests, or capacity policy.
    """

    def __init__(self, entries: MutableMapping[Key, Entry], *, lock: Any,
                 closing: Callable[[], bool]) -> None:
        self._entries = entries
        self._lock = lock
        self._closing = closing

    def settle_unstarted(self, *, running: Callable[[Entry], bool],
                        settle: Callable[[Key, Entry], None]) -> bool:
        """Detach each waiting entry once, then settle it outside the lock.

        Return true whenever drain has begun, including after all waiting
        entries have already been detached. Running entries stay in the queue.
        """
        with self._lock:
            if not self._closing():
                return False
            waiting = [(key, self._entries.pop(key)) for key, entry in
                       tuple(self._entries.items()) if not running(entry)]
        for key, entry in waiting:
            settle(key, entry)
        return True

    def mark_started_if_open(self, mark_started: Callable[[], None]) -> bool:
        """Atomically fence the last transition before an effect can start."""
        with self._lock:
            if self._closing():
                return False
            mark_started()
            return True
