"""Owner independent admission and launch mechanics for fleet assignments.

The integrating product supplies role selection, readiness, assignment context and the
actual host launch. This module orders those decisions and records what was admitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
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
    automatic_retry_blocked: bool = False


class FleetDispatcher:
    """Run readiness, role and capacity gates before handing a turn to an injected launcher.

    ``ready`` receives the task and keyword context and returns either ``True`` or a mapping
    with a true ``ready`` key. ``active_counts`` returns ``(workers, managers)``. ``make_spec``
    receives ``(task, role, token, context)`` and must return a host ``TurnSpec``. The launcher
    receives ``(spec, context)``. When ``make_spec`` is ``None``, the owner launcher receives
    ``(current_task, context)`` and must prepare a retained occurrence; that occurrence owns
    the host turn reservation and final execution admission. No manager wake is part of dispatch.
    """

    def __init__(self, capacity: Any, tokens: TokenBook, *, ready: Callable[..., Any],
                 role_for: Callable[[Any], str], policy_for: Callable[[str], Any],
                 active_counts: Callable[[], tuple[int, int]],
                 make_spec: Callable[..., TurnSpec] | None, launch: Callable[..., Any],
                 mcp_server_name: str, mcp_tools: tuple[str, ...],
                 assignment_id: Callable[[Any], str] | None = None,
                 read_current: Callable[..., Any]):
        for name, value in (("ready", ready), ("role_for", role_for), ("policy_for", policy_for),
                            ("active_counts", active_counts), ("launch", launch),
                            ("read_current", read_current)):
            if not callable(value):
                raise TypeError(name + " must be callable")
        if not isinstance(tokens, TokenBook):
            raise TypeError("tokens must be a TokenBook")
        if make_spec is not None and not callable(make_spec):
            raise TypeError("make_spec must be callable or None")
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
        self._lock = threading.RLock()

    def dispatch(self, task: Any, *, context: Mapping[str, Any] | None = None,
                 assignment: str | None = None, retry: bool = False,
                 resume: bool = False) -> DispatchRecord:
        """Dispatch one fresh, retry or resumed launch through the same final readiness check."""
        with self._lock:
            return self._dispatch_locked(task, context=context, assignment=assignment,
                                         retry=retry, resume=resume)

    def _dispatch_locked(self, task: Any, *, context: Mapping[str, Any] | None,
                         assignment: str | None, retry: bool, resume: bool) -> DispatchRecord:
        context = dict(context or {})
        assignment = assignment or self.assignment_id(task)
        if not isinstance(assignment, str) or not assignment:
            raise DispatchError("assignment id is required")
        previous = self.records.get(assignment)
        if previous is not None and previous.state != "refused":
            raise DispatchError("assignment already has an active dispatch or settled generation")
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
        transient_refusal = False
        try:
            current = self.read_current(task, **context)
            if current is None:
                raise DispatchError("assignment no longer exists")
            if self.make_spec is not None:
                spec = self.make_spec(current, role, token, context)
                self._validate_spec(spec, token)
                try:
                    self.capacity.ensure_turn(assignment)
                except Exception:
                    transient_refusal = True
                    raise
                reserved = True
            # Final check is adjacent to launch on every path, including resume and retry.
            current = self.read_current(task, **context)
            if current is None:
                raise DispatchError("assignment no longer exists")
            if self._admitted_revision(current) != record.admitted_revision:
                raise DispatchError("assignment admission changed before launch")
            try:
                self._require_ready(current, context)
            except DispatchError:
                transient_refusal = True
                raise
            record.task = current
            launch_started = True
            # Owner-composed launchers prepare a canonical occurrence. Its retained start
            # takes the real host slot and calls admit_execution; reserving this selector's
            # assignment as a second turn would charge capacity twice.
            record.result = (self.launch(spec, context) if self.make_spec is not None
                             else self.launch(current, context))
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
                # Only readiness and host-turn capacity rejection at their actual gates
                # are transient. A similarly worded setup/launcher error is still fenced.
                record.automatic_retry_blocked = not transient_refusal
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
        with self._lock:
            return self._dispatch_ready_locked(tasks, context=context)

    def _dispatch_ready_locked(self, tasks: Any, *, context: Mapping[str, Any] | None) -> DispatchRecord | None:
        base_context = dict(context or {})
        for task in tasks:
            assignment = self.assignment_id(task)
            previous = self.records.get(assignment)
            if previous is not None and previous.state != "refused":
                continue
            candidate_context = dict(base_context, assignment=assignment, retry=False, resume=False)
            current = self.read_current(task, **candidate_context)
            if current is None:
                continue
            # A prelaunch refusal is safe to reconsider only after admission changes.
            # Automatic pumps run frequently, so retrying an unchanged generation here
            # would repeatedly rebuild its spec and consume launch-side resources. Direct
            # dispatch() still permits an owner-requested retry or resume of a refusal.
            if (previous is not None and previous.state == "refused"
                    and previous.automatic_retry_blocked
                    and previous.admitted_revision == self._admitted_revision(current)):
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
                # Readiness/capacity can also change in the pre-record gates. If the
                # dispatch attempt did not replace the prior record, keep scanning.
                # Once a new record exists, its stage classification decides whether
                # the automatic pump may retry it.
                if record is None or record is previous:
                    if str(exc).startswith(("assignment is not ready:",
                                            "capacity is full for role")):
                        continue
                    raise
                if record.state == "refused" and not record.automatic_retry_blocked:
                    continue
                raise
        return None

    def finish(self, assignment: str, *, settled: bool = True) -> None:
        """Release the turn reservation and token after the owner has settled the assignment."""
        with self._lock:
            record = self.records.get(assignment)
            if record is None:
                return
            self.tokens.revoke(assignment)
            if self.make_spec is not None:
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
