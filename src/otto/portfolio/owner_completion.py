"""Small owner-lane continuations for the existing retained command transport.

These values never cross IPC and are not another work queue. The original
request file and Due remain the restart handles. Only the owner resolves them.
"""
from __future__ import annotations

from contextvars import copy_context
from typing import Any, Callable


class OwnerCompletion:
    def __init__(self) -> None:
        self.done = False
        self.value: Any = None
        self.error: BaseException | None = None
        self._callbacks: list[Callable[[], None]] = []

    def resolve(self, value: Any = None, error: BaseException | None = None) -> None:
        if self.done:
            raise RuntimeError("owner completion was already captured")
        self.done, self.value, self.error = True, value, error
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback()

    def then(self, success: Callable[[Any], Any], failure: Callable[[BaseException], Any] | None = None) -> OwnerCompletion:
        next_value = OwnerCompletion()
        context = copy_context()

        def finish() -> None:
            try:
                if self.error is not None:
                    if failure is None:
                        raise self.error
                    value = failure(self.error)
                else:
                    value = success(self.value)
                if isinstance(value, OwnerCompletion):
                    value.then(next_value.resolve, lambda error: next_value.resolve(error=error))
                else:
                    next_value.resolve(value)
            except BaseException as error:
                next_value.resolve(error=error)

        callback = lambda: context.run(finish)
        if self.done:
            callback()
        else:
            self._callbacks.append(callback)
        return next_value


def after_owner(value: Any, success: Callable[[Any], Any],
                failure: Callable[[BaseException], Any] | None = None) -> Any:
    """Preserve synchronous callers; continue admitted native work on owner."""
    return value.then(success, failure) if isinstance(value, OwnerCompletion) else success(value)


def collect_owner(values: list[Any]) -> Any:
    result: Any = []
    for value in values:
        result = after_owner(result, lambda rows, value=value:
            after_owner(value, lambda item: [*rows, item]))
    return result
