"""Owner independent admission and launch mechanics for fleet assignments.

The integrating product supplies role selection, readiness, assignment context and the
actual host launch. This module orders those decisions and records what was admitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .hosts.contract import McpGrant, TurnSpec
from .tools.pins import require_sole_server
from .tools.tokens import TokenBook
from ..domains.work.admission import admitted_revision


class DispatchError(RuntimeError):
    """An assignment could not safely be dispatched."""


@dataclass
class DispatchRecord:
    assignment: str
    task: Any
    role: str
    admitted_revision: str | None
    state: str = "admitted"
    token: str | None = field(default=None, repr=False)
    result: Any = None
    blockers: tuple = ()


class FleetDispatcher:
    """Run readiness, role and capacity gates before handing a turn to an injected launcher.

    ``ready`` receives the task and keyword context and returns either ``True`` or a mapping
    with a true ``ready`` key. ``active_counts`` returns ``(workers, managers)``. ``make_spec``
    receives ``(task, role, token, context)`` and must return a host ``TurnSpec``. The launcher
    receives ``(spec, context)``. No manager wake or scheduling callback is part of dispatch.
    """

    def __init__(self, capacity: Any, tokens: TokenBook, *, ready: Callable[..., Any],
                 role_for: Callable[[Any], str], policy_for: Callable[[str], Any],
                 active_counts: Callable[[], tuple[int, int]],
                 make_spec: Callable[..., TurnSpec], launch: Callable[..., Any],
                 mcp_server_name: str, mcp_tools: tuple[str, ...],
                 assignment_id: Callable[[Any], str] | None = None,
                 read_current: Callable[..., Any]):
        for name, value in (("ready", ready), ("role_for", role_for), ("policy_for", policy_for),
                            ("active_counts", active_counts), ("make_spec", make_spec), ("launch", launch),
                            ("read_current", read_current)):
            if not callable(value):
                raise TypeError(name + " must be callable")
        if not isinstance(tokens, TokenBook):
            raise TypeError("tokens must be a TokenBook")
        if not isinstance(mcp_server_name, str) or not mcp_server_name:
            raise TypeError("mcp_server_name must be a nonempty string")
        if not isinstance(mcp_tools, tuple) or any(not isinstance(t, str) or not t for t in mcp_tools):
            raise TypeError("mcp_tools must be a tuple of tool names")
        self.capacity, self.tokens = capacity, tokens
        self.ready, self.role_for, self.policy_for = ready, role_for, policy_for
        self.active_counts, self.make_spec, self.launch = active_counts, make_spec, launch
        self.mcp_server_name, self.mcp_tools = mcp_server_name, mcp_tools
        self.assignment_id = assignment_id or self._default_assignment
        self.read_current = read_current
        self.records: dict[str, DispatchRecord] = {}

    def dispatch(self, task: Any, *, context: Mapping[str, Any] | None = None,
                 assignment: str | None = None, retry: bool = False,
                 resume: bool = False) -> DispatchRecord:
        """Dispatch one fresh, retry or resumed launch through the same final readiness check."""
        context = dict(context or {})
        assignment = assignment or self.assignment_id(task)
        if not isinstance(assignment, str) or not assignment:
            raise DispatchError("assignment id is required")
        previous = self.records.get(assignment)
        if previous is not None and previous.state in {"admitted", "launched", "unknown"}:
            raise DispatchError("assignment already has an active dispatch")
        context.update(assignment=assignment, retry=bool(retry), resume=bool(resume))
        self._require_ready(task, context)
        role = self.role_for(task)
        if not isinstance(role, str) or not role:
            raise DispatchError("role policy did not select a role")
        if role == "manager":
            raise DispatchError("routine dispatch cannot launch or wake a manager")
        workers, managers = self.active_counts()
        policy = self.policy_for(role)
        if not policy.admits_turn(role, workers, managers):
            raise DispatchError("capacity is full for role %s" % role)
        admitted = self._admitted_revision(task)
        if admitted is None:
            raise DispatchError("task has no valid admitted revision")

        token = self.tokens.issue(assignment, role)
        record = DispatchRecord(assignment, task, role, admitted, token=token)
        self.records[assignment] = record
        reserved = False
        launch_started = False
        try:
            current = self.read_current(task, **context)
            if current is None:
                raise DispatchError("assignment no longer exists")
            spec = self.make_spec(current, role, token, context)
            self._validate_spec(spec, token)
            self.capacity.ensure_turn(assignment)
            reserved = True
            # Final check is adjacent to launch on every path, including resume and retry.
            current = self.read_current(task, **context)
            if current is None:
                raise DispatchError("assignment no longer exists")
            if self._admitted_revision(current) != record.admitted_revision:
                raise DispatchError("assignment admission changed before launch")
            self._require_ready(current, context)
            launch_started = True
            record.result = self.launch(spec, context)
            record.state = "launched"
            return record
        except Exception as exc:
            if launch_started:
                # A raised launcher may have spawned a process. Keep both its authority and slot
                # until the owner explicitly settles this unknown dispatch.
                record.state = "unknown"
            else:
                self.tokens.revoke(assignment)
                if reserved:
                    self.capacity.release_turn(assignment)
                record.state = "refused"
            if isinstance(exc, DispatchError):
                raise
            raise DispatchError(str(exc)) from exc

    def dispatch_ready(self, tasks: Any, *, context: Mapping[str, Any] | None = None) -> DispatchRecord | None:
        """Dispatch the first currently ready, worker-capacity-admissible candidate.

        Candidate scanning is a convenience for routine work. Each candidate is read afresh and
        checked before role/capacity selection; the selected candidate still goes through
        ``dispatch`` and its immediate prelaunch readiness check. Blocked candidates are skipped
        without issuing a token or waking a manager.
        """
        base_context = dict(context or {})
        for task in tasks:
            assignment = self.assignment_id(task)
            candidate_context = dict(base_context, assignment=assignment, retry=False, resume=False)
            current = self.read_current(task, **candidate_context)
            if current is None:
                continue
            try:
                self._require_ready(current, candidate_context)
            except DispatchError:
                continue
            role = self.role_for(current)
            if not isinstance(role, str) or not role or role == "manager":
                continue
            workers, managers = self.active_counts()
            if not self.policy_for(role).admits_turn(role, workers, managers):
                continue
            try:
                return self.dispatch(current, context=base_context, assignment=assignment)
            except DispatchError as exc:
                # A concurrent readiness or capacity change makes this candidate wait. Spec,
                # token, or uncertain launch failures remain visible to the owner.
                record = self.records.get(assignment)
                if record is not None and record.state == "unknown":
                    raise
                if str(exc).startswith(("assignment is not ready:", "capacity is full for role")):
                    continue
                raise
        return None

    def finish(self, assignment: str, *, settled: bool = True) -> None:
        """Release the turn reservation and token after the owner has settled the assignment."""
        record = self.records.get(assignment)
        if record is None:
            return
        self.tokens.revoke(assignment)
        if settled:
            self.capacity.settle_turn(assignment)
        else:
            self.capacity.release_turn(assignment)
        record.state = "settled" if settled else "released"
        record.token = None

    def _require_ready(self, task: Any, context: Mapping[str, Any]) -> None:
        result = self.ready(task, **dict(context))
        ready = result is True or (isinstance(result, Mapping) and result.get("ready") is True)
        if not ready:
            blockers = result.get("blockers", ()) if isinstance(result, Mapping) else ()
            raise DispatchError("assignment is not ready: %s" % (", ".join(map(str, blockers)) or "readiness refused"))

    def _validate_spec(self, spec: Any, token: str) -> None:
        if not isinstance(spec, TurnSpec):
            raise DispatchError("make_spec must return a TurnSpec")
        if spec.initializer:
            raise DispatchError("routine worker dispatch cannot use an inert initializer")
        grant = spec.mcp
        try:
            require_sole_server(grant, self.mcp_server_name)
        except (TypeError, ValueError) as exc:
            raise DispatchError("dispatch requires exactly the %s MCP server" % self.mcp_server_name.capitalize()) from exc
        server = grant.servers[0]
        if server.name != self.mcp_server_name or tuple(server.tools) != self.mcp_tools:
            raise DispatchError("dispatch MCP grant must expose only the configured tools")
        if grant.token != token or not grant.token_env or not grant.token_env_prefix:
            raise DispatchError("the issued token must be delivered through the MCP environment")

    @staticmethod
    def _admitted_revision(task: Any) -> str | None:
        payload = task.get("payload") if isinstance(task, Mapping) else getattr(task, "payload", None)
        value = admitted_revision(payload) if isinstance(payload, Mapping) else None
        return value if isinstance(value, str) else None

    @staticmethod
    def _default_assignment(task: Any) -> str:
        if isinstance(task, Mapping):
            value = task.get("assignment") or task.get("id")
        else:
            value = getattr(task, "assignment", None) or getattr(task, "id", None)
        if not isinstance(value, str) or not value:
            raise DispatchError("task does not identify an existing assignment")
        return value
