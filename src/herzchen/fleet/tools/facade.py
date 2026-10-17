"""The tool facade: what a worker may call, with its assignment taken from its token and never from its arguments."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Protocol

from .rules import CHECK, DONE, TASK, FeedbackLedger, ToolRuleError, ToolSpec
from .tokens import TokenBook, TokenError

__all__ = ["AllowlistedPort", "LandingOwnerPort", "OwnerPort", "SettlingOwnerPort", "ToolFacade"]

_STRIPPED_KEYS = frozenset({"accepted", "acceptance", "counts_as_acceptance"})
_MAX_DEPTH = 32


class OwnerPort(Protocol):
    """The owner's side of a tool call. The facade never sees the owner's internals."""

    def call(self, operation: str, assignment: str, args: Mapping, *, feedback: bool) -> Mapping:
        ...


class AllowlistedPort:
    """An owner port that forwards only the operations the owner has already put on its allowlist."""

    def __init__(self, inner: OwnerPort, allowed: Sequence[str]) -> None:
        self._inner = inner
        self._allowed = frozenset(allowed)

    def call(self, operation: str, assignment: str, args: Mapping, *, feedback: bool) -> Mapping:
        if operation not in self._allowed:
            raise PermissionError("operation is not on the owner allowlist")
        return self._inner.call(operation, assignment, args, feedback=feedback)


class SettlingOwnerPort:
    """Run a facade operation on the owner lane and settle landed work before it returns."""

    def __init__(self, inner: OwnerPort, executor: Callable[[], Any],
                 settle: Callable[[str], None],
                 retain_refusal: Callable[[str, Any], None] | None = None,
                 *, done_operation: str = "worker-done") -> None:
        self.inner, self.executor, self.settle = inner, executor, settle
        self.retain_refusal = retain_refusal
        self.done_operation = done_operation

    def call(self, operation: str, assignment: str, args: Mapping, *, feedback: bool) -> Mapping:
        executor = self.executor()
        if not callable(executor):
            raise PermissionError("owner command executor is unavailable")

        def owned_call() -> Mapping:
            try:
                result = self.inner.call(operation, assignment, args, feedback=feedback)
            except Exception as exc:
                from herzchen.fleet.landing import LandingError
                if (operation == self.done_operation and isinstance(exc, LandingError)
                        and self.retain_refusal is not None):
                    try:
                        self.retain_refusal(assignment, exc)
                    except Exception:
                        # A failed owner CAS leaves continuation unknown. Keep
                        # the original refusal visible to the worker.
                        pass
                raise
            if (operation == self.done_operation and isinstance(result, Mapping)
                    and result.get("landed") is True):
                self.settle(assignment)
            return result

        return executor(owned_call)


class LandingOwnerPort:
    """Bind worker check/done operations to owner-resolved landing state.

    The resolver receives only the assignment from the live TokenBook grant and must return
    ``service``, ``lab_name``, and ``task_id``.  Optional assessment pins (``candidate``,
    ``criterion``, ``parent_obligation``, ``actor``, ``gate_refs``) also come from that owner
    context. Worker arguments are never used to choose the lab, task, check, or acceptance pins.
    """

    _PINS = ("assignment_id", "candidate", "criterion", "parent_obligation", "actor", "gate_refs")

    def __init__(
        self,
        assignment_context: Callable[[str], Mapping[str, Any]],
        *,
        fallback: OwnerPort | None = None,
    ) -> None:
        if not callable(assignment_context):
            raise TypeError("assignment_context must be callable")
        self._assignment_context = assignment_context
        self._fallback = fallback

    def call(self, operation: str, assignment: str, args: Mapping, *, feedback: bool) -> Mapping:
        if operation not in {"worker-check", "worker-done"}:
            if self._fallback is None:
                raise PermissionError("operation is not a landing operation")
            return self._fallback.call(operation, assignment, args, feedback=feedback)
        if operation == "worker-check":
            if feedback is not True:
                raise PermissionError("worker check must be feedback only")
            method_name = "check"
        elif operation == "worker-done":
            if feedback is not False:
                raise PermissionError("worker done cannot be feedback")
            method_name = "done"

        context = self._assignment_context(assignment)
        if not isinstance(context, Mapping):
            raise TypeError("assignment context must be a mapping")
        service = context.get("service")
        lab_name = context.get("lab_name")
        task_id = context.get("task_id")
        assignment_id = context.get("assignment_id", assignment)
        method = getattr(service, method_name, None)
        if not callable(method):
            raise TypeError("landing service does not implement %s" % method_name)
        if (not isinstance(lab_name, str) or not lab_name or not isinstance(task_id, str) or not task_id
                or assignment_id != assignment):
            raise TypeError("assignment context must name its lab and admitted task")

        # Do not pass worker-supplied values into landing, even when a tool schema allows them.
        if method_name == "check":
            return method(lab_name, task_id)
        pins = {name: context[name] for name in self._PINS if name in context}
        return method(lab_name, task_id, **pins)


def _refusal(code: str, detail: str) -> dict:
    return {"ok": False, "error": code, "detail": detail}


def _json_safe(value: object, depth: int = 0) -> bool:
    if depth > _MAX_DEPTH:
        return False
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_safe(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_safe(item, depth + 1) for key, item in value.items())
    return False


def _clean(node: object) -> object:
    """A copy with acceptance-claiming keys removed at every depth."""

    if isinstance(node, dict):
        return {key: _clean(value) for key, value in node.items() if key not in _STRIPPED_KEYS}
    if isinstance(node, list):
        return [_clean(item) for item in node]
    return node


class ToolFacade:
    """Lists and calls the tools a token's role may use. Caller mistakes return refusals; nothing raises."""

    def __init__(
        self,
        tools: Sequence[ToolSpec],
        roles: Mapping[str, Sequence[str]],
        owner: OwnerPort,
        book: TokenBook,
        ledger: FeedbackLedger,
        audit: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        by_name: dict[str, ToolSpec] = {}
        for spec in tools:
            if not isinstance(spec, ToolSpec):
                raise ToolRuleError("tools must be ToolSpec instances")
            if spec.name in by_name:
                raise ToolRuleError("tool names must be distinct")
            by_name[spec.name] = spec
        role_tools: dict[str, tuple[ToolSpec, ...]] = {}
        for role, names in roles.items():
            if not isinstance(role, str) or not role:
                raise ToolRuleError("role names must be non-empty strings")
            specs = []
            for name in names:
                if not isinstance(name, str) or name not in by_name:
                    raise ToolRuleError("a role lists a tool that does not exist")
                specs.append(by_name[name])
            role_tools[role] = tuple(specs)
        self._role_tools = role_tools
        self._owner = owner
        self._book = book
        self._ledger = ledger
        self._audit = audit

    def listing(self, token: object) -> list[dict] | dict:
        """The tools the token's role may call, in the role's order. A bad token returns a refusal."""

        try:
            grant = self._book.resolve(token)
        except TokenError:
            return _refusal("unauthorized", "unknown token")
        return [
            {"name": spec.name, "kind": spec.kind, "description": spec.description, "args": list(spec.args)}
            for spec in self._role_tools.get(grant.role, ())
        ]

    def call(self, token: object, tool: object, args: object = None) -> dict:
        """Run one tool for the token's assignment and shape the reply by the tool's kind."""

        try:
            grant = self._book.resolve(token)
        except TokenError:
            return _refusal("unauthorized", "unknown token")

        spec = self._allowed(grant.role, tool)
        if spec is None:
            return _refusal("forbidden", "tool is not available to this worker")

        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            return _refusal("bad_args", "arguments must be a mapping")
        for key, value in args.items():
            if not isinstance(key, str) or key not in spec.args:
                return _refusal("bad_args", "argument is not declared for this tool")
            if not _json_safe(value):
                return _refusal("bad_args", "argument value must be JSON data")
        payload = json.loads(json.dumps(dict(args)))

        assignment = grant.assignment
        audit_base = {"assignment_id": assignment, "tool": spec.name, "kind": spec.kind,
                      "operation": spec.operation}
        try:
            reply = self._owner.call(spec.operation, assignment, payload, feedback=(spec.kind == CHECK))
            if not isinstance(reply, Mapping):
                raise TypeError("owner reply must be a mapping")
            result = _clean(json.loads(json.dumps(reply)))
            if spec.kind == TASK:
                response = {"ok": True, "tool": spec.name, "kind": TASK, "result": result}
            elif spec.kind == CHECK:
                self._ledger.record(assignment, spec.name, reply)
                response = {
                    "ok": True,
                    "tool": spec.name,
                    "kind": CHECK,
                    "feedback": True,
                    "accepted": False,
                    "result": result,
                }
            else:
                response = {
                    "ok": True,
                    "tool": spec.name,
                    "kind": DONE,
                    "submitted": True,
                    "accepted": False,
                    "result": result,
                }
        except Exception as exc:
            # Only class-declared owner error codes are classified. Generic
            # exceptions can acquire arbitrary instance code/message fields that
            # may contain credentials or private state.
            from herzchen.fleet.landing import LandingError
            code = getattr(type(exc), "code", None)
            message = getattr(type(exc), "message", None)
            if isinstance(exc, LandingError):
                message = exc.message
            if isinstance(code, str) and code and isinstance(message, str) and message:
                response = {"ok": False, "error": code, "detail": message}
            else:
                response = _refusal("owner_unavailable", type(exc).__name__)
        if self._audit is not None:
            self._audit({**audit_base, "result": response})
        return response

    def _allowed(self, role: str, tool: object) -> ToolSpec | None:
        if not isinstance(tool, str):
            return None
        for spec in self._role_tools.get(role, ()):
            if spec.name == tool:
                return spec
        return None
