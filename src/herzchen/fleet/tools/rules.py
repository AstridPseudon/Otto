"""Tool rules: what a tool spec may declare, the feedback ledger for worker checks, and the owner-only acceptance gate."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "TASK",
    "CHECK",
    "DONE",
    "KINDS",
    "ToolRuleError",
    "ToolSpec",
    "FeedbackLedger",
    "AcceptanceError",
    "Acceptance",
]

TASK = "task"
CHECK = "check"
DONE = "done"
KINDS = (TASK, CHECK, DONE)

_TOOL_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_ARG_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
_RESERVED_ARGS = frozenset({"assignment", "token", "role", "feedback", "accepted", "acceptance"})
_REF_KEYS = frozenset({"run_id", "receipt", "ref"})


class ToolRuleError(Exception):
    """A tool spec or role rule is malformed."""


@dataclass(frozen=True)
class ToolSpec:
    """One tool a worker may see. Names, operations and argument names are supplied by the caller."""

    name: str
    kind: str
    operation: str
    args: tuple = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _TOOL_NAME.fullmatch(self.name):
            raise ToolRuleError("tool name must match ^[a-z][a-z0-9_-]{0,31}$")
        if self.kind not in KINDS:
            raise ToolRuleError("tool kind must be one of task, check, done")
        if not isinstance(self.operation, str) or not self.operation:
            raise ToolRuleError("tool operation must be a non-empty string")
        if not isinstance(self.args, tuple):
            raise ToolRuleError("tool args must be a tuple")
        seen: set[str] = set()
        for arg in self.args:
            if not isinstance(arg, str) or not _ARG_NAME.fullmatch(arg):
                raise ToolRuleError("tool arg names must match ^[a-z][a-z0-9_]{0,31}$")
            if arg in _RESERVED_ARGS:
                raise ToolRuleError("tool arg name is reserved")
            if arg in seen:
                raise ToolRuleError("tool arg names must be distinct")
            seen.add(arg)


def _plain(value: Mapping) -> dict:
    """A deep, JSON-only copy. Raises TypeError or ValueError for anything that is not JSON data."""

    if not isinstance(value, Mapping):
        raise TypeError("result must be a mapping")
    return json.loads(json.dumps(value))


def _collect_refs(node: object, under_ref_key: bool, out: set) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _collect_refs(value, under_ref_key or key in _REF_KEYS, out)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, under_ref_key, out)
    elif isinstance(node, str) and under_ref_key:
        out.add(node)


class FeedbackLedger:
    """Owner-side record of check results. Thread-safe. Every run reference it sees is feedback, never acceptance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, list[dict]] = {}
        self._refs: set[str] = set()

    def record(self, assignment: str, tool: str, result: Mapping) -> dict:
        """Append a feedback entry for a check result and remember its reference strings."""

        copy = _plain(result)
        refs: set[str] = set()
        _collect_refs(copy, False, refs)
        entry = {
            "assignment": assignment,
            "tool": tool,
            "kind": "feedback",
            "result": copy,
            "counts_as_acceptance": False,
        }
        with self._lock:
            self._entries.setdefault(assignment, []).append(entry)
            self._refs.update(refs)
        return json.loads(json.dumps(entry))

    def entries(self, assignment: str) -> list:
        """Copies of the feedback entries recorded for the assignment, oldest first."""

        with self._lock:
            return json.loads(json.dumps(self._entries.get(assignment, [])))

    def is_feedback_ref(self, ref: object) -> bool:
        """True when the reference string was produced by a check result."""

        if not isinstance(ref, str):
            return False
        with self._lock:
            return ref in self._refs


class AcceptanceError(Exception):
    """A run may not be recorded as acceptance."""


class Acceptance:
    """The owner-side acceptance gate. Not reachable through the worker facade."""

    def __init__(self, ledger: FeedbackLedger) -> None:
        self._ledger = ledger
        self._lock = threading.Lock()
        self._accepted: set[tuple[str, str]] = set()

    def record(self, assignment: str, commit: str, run: Mapping) -> None:
        """Accept an assignment at a commit, only from a passing check that ran on exactly that commit."""

        if not isinstance(run, Mapping):
            raise AcceptanceError("run must be a mapping")
        run_id = run.get("run_id")
        run_commit = run.get("commit")
        if not isinstance(run_id, str) or not run_id or not isinstance(run_commit, str) or not run_commit:
            raise AcceptanceError("run must carry a run_id and a commit")
        if run_commit != commit:
            raise AcceptanceError("run was not made on the commit being accepted")
        if run.get("ok") is not True:
            raise AcceptanceError("run did not pass")
        if self._ledger.is_feedback_ref(run_id):
            raise AcceptanceError("worker feedback cannot count as acceptance")
        with self._lock:
            self._accepted.add((assignment, commit))

    def accepted(self, assignment: str, commit: str) -> bool:
        """True when the owner recorded acceptance of the assignment at the commit."""

        with self._lock:
            return (assignment, commit) in self._accepted
