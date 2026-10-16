"""Host custody for the maintained file command transport and admitted children.

Owner command implementations supply a handler. Request files are retained
until an atomic response exists, so a restarted host can recover the same
logical request through canonical operations. A parent finishing drains its
admitted children while their command/status surface remains available.
"""
from __future__ import annotations

import json
from contextvars import ContextVar, copy_context
import hashlib
import os
import queue
from pathlib import Path
import socket
import threading
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .owner_readers import json_value
from .recovery_timing import ReceiptTiming, attach_receipt_timing, stable_correlation_id
from .owner_completion import OwnerCompletion, after_owner
from .ipc_retention import prune_answered_responses
from herzchen.fleet.capacity import CapacityPolicy, CapacityPool


def _atomic_json(path: Path, value: Any) -> None:
    from .retained_projection import atomic_json, finite_summary, projection
    from .manager_journey_client import command_result_summary
    safe = json_value(value)
    capture = atomic_json(path, safe)
    if path.name.startswith("response-") and path.suffix == ".json":
        token = path.stem.removeprefix("response-")
        summary = {**command_result_summary(safe), **finite_summary(safe)}
        status = projection(safe, artifact={"path": str(path), **capture},
            binding={"request_id": token}, summary=summary, oversize="detail")
        timing = safe.get("receipt_timing") if isinstance(safe, Mapping) else None
        if isinstance(timing, Mapping):
            status["receipt_timing"] = timing
        if len(json.dumps(status).encode()) > 65536:
            raise ValueError("transport status exceeds its finite metadata bound")
        atomic_json(path.with_name("status-" + path.name), status)


def _timed_receipt(value: Any, timing: ReceiptTiming) -> Any:
    """Add bounded phase metadata to an existing command receipt."""

    timing.observe("terminal")
    if isinstance(value, Mapping):
        return attach_receipt_timing(value, timing.as_dict(), correlation_id=timing.correlation_id)
    return attach_receipt_timing({"outcome": "unavailable", "result": value}, timing.as_dict(),
                                 correlation_id=timing.correlation_id)


def _host_boot_identity() -> str | None:
    """Return a host boot pin when the platform exposes one.

    The owner locator is deliberately local and small.  A process-start pin
    is the primary custody fence; the boot pin closes the remaining ambiguity
    when a platform can expose it without another service or registry.
    """
    try:
        if sys.platform.startswith("linux"):
            value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        elif sys.platform == "darwin":
            value = subprocess.check_output(
                ["/usr/sbin/sysctl", "-n", "kern.boottime"],
                text=True, stderr=subprocess.DEVNULL, timeout=1,
            ).strip()
        else:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def _process_start_identity(pid: int) -> dict[str, Any]:
    """Capture the kernel identity needed to distinguish a reused PID."""
    from .native_caller_ingress import process_identity

    identity = process_identity(pid)
    return {"pid": identity.pid, "parent": identity.parent,
            "birth": list(identity.birth), "uid": identity.uid}


def _same_process_start_identity(value: Any, expected: Mapping[str, Any]) -> bool:
    return (isinstance(value, Mapping)
            and value.get("pid") == expected.get("pid")
            and value.get("parent") == expected.get("parent")
            and list(value.get("birth", ())) == list(expected.get("birth", ()))
            and value.get("uid") == expected.get("uid"))


_DISPATCH_CONTEXT = threading.local()
_INERT_STATUS_CONTEXT = threading.local()
_COMMAND_TRANSPORT = ContextVar("otto_command_transport", default=None)
_ACTIVE_EXECUTION = ContextVar("otto_active_execution", default=None)
_MANAGER_TURN_COMMANDS = frozenset({"start-manager", "manager-continue", "manager-worker-result",
                                   "manager-help-result", "manager-task-settlement"})
_REENTRANT_COMMANDS = frozenset({"task-state", "report", "completion-gate", "complete-task",
                                 "effective-context", "whoami", "lookup-occurrence", "follow-occurrence", "read-result", "read-artifact", "consume-result",
                                 "manager-assessment", "manager-assessment-pool",
                                 "run-worker", "worker-status", "worker-readiness", "start-retained-worker",
                                 "review-task", "finish-task", "finish-project",
                                 "review-input", "task-list-author",
                                 "request-help", "request-advice", "read-help", "respond-help", "resolve-help",
                                 "start-retained-help",
                                 "project-lifecycle-read", "commit",
                                 "advisor-decision-state", "execution-control", "answer-session-result"})


def _starts_work(request: Mapping[str, Any]) -> bool:
    # Some nested commands can settle evidence AND admit a new effect. Keep
    # their original file handle while draining; read-only worker-status and
    # finite child bookkeeping continue through the same custodian.
    return (request.get("command") == "owner-execution" and request.get("operation") in {"launch", "start-prepared"}
            or request.get("command") in {"start-manager", "run-worker",
                "start-retained-worker", "start-retained-help", "manager-worker-result",
                "manager-task-settlement", "manager-help-result", "answer-session-result",
                "request-help", "request-advice", "start-retained-child", "parent-child-result"}
            or request.get("command") == "manager-continue" and request.get("operation") == "dispatch"
            or request.get("command") == "operating-setup" and request.get("operation") == "activate"
            or request.get("command") == "execution-control" and request.get("operation") == "resume")


def _nested_capability(request: Mapping[str, Any]) -> str:
    """Classify nested file operations without releasing owner custody."""
    if request.get("command") == "owner-execution":
        return ("admitted" if request.get("operation") in {"lookup", "follow", "result", "artifact"}
                and not set(request) - {"command", "operation", "request_key", "original_request_key", "occurrence", "artifact_ref", "offset", "max_bytes"}
                else "held")
    if request.get("command") == "owner-context":
        # External owner reads use the same serialized pump and exact
        # independently issued input grant. Classification is not authority;
        # the handler still verifies the grant/current host-bound root.
        # Direction mutations must never fall through a blanket command allow.
        if request.get("operation") == "events-read":
            return ("admitted" if set(request) == {"command", "operation", "request_key", "handle"}
                    and isinstance(request.get("handle"), Mapping) else "held")
        if request.get("operation") == "retention-read":
            return ("admitted" if set(request) == {"command", "operation", "request_key", "handle"}
                    and isinstance(request.get("handle"), Mapping) else "held")
        return ("admitted" if request.get("operation") in {
            "whoami", "effective-context", "direction-read", "direction-history"}
            and set(request) == {"command", "operation", "request_key"}
            else "held")
    if (request.get("command") == "project-queue"
            and request.get("operation", "read") in {"read", "seed", "after"}
            and not set(request) - {"command", "operation", "request_key", "order", "rule",
                                   "consumer", "expected_revision", "predecessor_ref", "project_ref"}):
        return "admitted"  # Exact owner grant is still checked by the handler.
    if (request.get("command") == "vision"
            and request.get("operation") in {"help", "create", "read", "query", "context", "history", "reorganize", "attach", "snapshot"}
            and not set(request) - {"command", "operation", "request_key", "arguments"}
            and isinstance(request.get("arguments", {}), Mapping)):
        return "admitted"  # Native read authorization or exact owner grant is checked in the service.
    # Setup inspection/preview are finite and inert; apply/update/prepare/activate stay held during
    # the admitted native wait and cannot acquire another execution effect.
    if (request.get("command") == "project-authoring"
            and request.get("operation", "read") in {"create", "open", "check-in", "read", "import-folder", "export-folder", "release", "current-scope"}
            and not set(request) - {"command", "operation", "request_key", "edit", "template", "template_parameters", "project_ref", "project_json", "session_id", "files", "document_changes"}):
        return "admitted"  # Finite authenticated owner authoring, including siblings.
    if (request.get("command") == "operating-setup"
            and request.get("operation", "read") in {"read", "preview"}
            and not set(request) - {"command", "operation", "setup", "request_key", "expected_setup_ref"}
            and (request.get("operation") == "preview" or request.get("setup") is None
                 and request.get("request_key") is None and request.get("expected_setup_ref") is None)):
        return "admitted"
    if request.get("command") in {"start-retained-child", "parent-child-result"}:
        return "retained"
    if request.get("command") == "execution-control" and request.get("operation") == "resume":
        return "retained"
    if request.get("command") in _REENTRANT_COMMANDS:
        return "admitted"
    if (request.get("command") == "manager-continue" and request.get("operation") == "dispatch"
            or request.get("command") in {"manager-worker-result", "manager-task-settlement", "manager-help-result"}):
        return "retained"  # Another native manager turn cannot overlap this one.
    return "held"


class ExecutionAdmissionHeld(RuntimeError):
    """Dispatch is held for an explicitly inert owner service."""


class ExecutionHost:
    """One owner-process command service, retained to admitted work completion.

    Read-only status uses a separate consumer so a synchronous child cannot
    prevent observation. Mutating commands remain serial. Canonical request
    identities, rather than command-file tokens, fence external effects.
    """

    def __init__(self, *, directory: str | Path, handler: Callable[[Mapping[str, Any]], Any],
                 owner_path: str | Path | None = None,
                 socket_path: str | Path | None = None,
                 caller_binding_reader: Any = None, caller_context_resolver: Any = None,
                 caller_authorizer: Any = None, owner_file_compatibility: bool = False,
                 bounded_transports: bool = False, capacity_policy: CapacityPolicy | None = None,
                 capacity_store: Any = None) -> None:
        self.directory = Path(directory)
        self._last_response_prune = float('-inf')
        self.handler = handler
        if (caller_binding_reader is None) != (caller_context_resolver is None):
            raise ValueError("trusted ingress reader and canonical caller resolver must be supplied together")
        if caller_authorizer is not None and caller_binding_reader is None:
            raise ValueError("caller authorization requires a trusted ingress binding")
        if any(value is not None and not callable(value) for value in
               (caller_binding_reader, caller_context_resolver, caller_authorizer)):
            raise TypeError("caller ingress capabilities must be host-injected callables")
        self.caller_binding_reader = caller_binding_reader
        self.caller_context_resolver = caller_context_resolver
        self.caller_authorizer = caller_authorizer
        if type(owner_file_compatibility) is not bool:
            raise TypeError("owner_file_compatibility must be explicit")
        self.owner_file_compatibility = owner_file_compatibility
        self.owner_path = self.directory / "owner.json" if owner_path is None else Path(owner_path)
        self.socket_path = None if socket_path is None else Path(socket_path)
        self._socket: socket.socket | None = None
        self._stop = threading.Event()
        self._commands_stop = threading.Event()
        self._children: set[threading.Thread] = set()
        self._lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._owner_calls = queue.Queue()
        self._external_waiting = 0
        self._active_files: set[str] = set()
        self._closing = False
        self._dispatch_held = False
        self._startup_report: dict[str, Any] | None = None
        self.startup_report_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
        self._owns_owner_file = False
        self._threads: list[threading.Thread] = []
        self.failures: dict[str, dict[str, str]] = {}
        if type(bounded_transports) is not bool:
            raise TypeError("bounded_transports must be an explicit owner choice")
        if capacity_policy is not None and not isinstance(capacity_policy, CapacityPolicy):
            raise TypeError("capacity_policy must be a CapacityPolicy")
        # The one pool for turns and heavy work. Pass the owner Store to keep its
        # reservations there; without one the host keeps them in memory.
        self.capacity = CapacityPool(capacity_policy or CapacityPolicy(), store=capacity_store,
            process_birth=lambda pid: list(_process_start_identity(pid)["birth"]))
        self.bounded_transports = bounded_transports
        self._owner_thread: int | None = None
        # These are continuations of retained requests, not durable new work.
        self._executions: dict[str, dict[str, Any]] = {}
        # _capacity_holds is the custody fence: it lists every hold until an
        # exact disposition releases it. _capacity_freed names the holds whose
        # process group is provably gone; they keep the fence, not a slot.
        self._capacity_holds: dict[str, dict[str, Any]] = {}
        self._capacity_freed: set[str] = set()
        self._process_groups = self._load_process_groups()
        self._reconcile_checked = 0.0
        self._last_project: str | None = None
        self._project_order: list[str] = []

    @property
    def dispatch_held(self) -> bool:
        return self._dispatch_held

    def hold_admission(self, startup_report: Mapping[str, Any] | None = None) -> None:
        """Fence all new execution before the host starts serving requests."""
        if self._threads:
            raise RuntimeError("dispatch hold must be installed before host start")
        self._dispatch_held = True
        self._startup_report = None if startup_report is None else dict(startup_report)

    @staticmethod
    def current_bounded() -> Any:
        context = getattr(_DISPATCH_CONTEXT, "value", None)
        if context is not None and context[0].bounded_transports:
            if context[1] != threading.get_ident():
                raise RuntimeError("canonical execution must enter through its owner")
            return context[0]
        return None

    def _owned(self, operation: Callable[[], Any]) -> Any:
        previous = getattr(_DISPATCH_CONTEXT, "value", None)
        _DISPATCH_CONTEXT.value = (self, threading.get_ident(), True)
        try:
            return operation()
        finally:
            _DISPATCH_CONTEXT.value = previous

    @staticmethod
    def worker_facade_for_occurrence(
        *, app: Any, due: Any, token: object, token_book: Any,
        tools: Any, roles: Mapping[str, Any], assignment_context: Callable[[str], Mapping[str, Any]],
        fallback: Any = None, ledger: Any = None,
    ) -> Any:
        """Build a worker facade bound to one current owner assignment.

        The live TokenBook grant must name this Due's assignment ID and the
        worker role. Landing check/done context is resolved again at call time
        through the supplied owner resolver; worker arguments cannot choose
        the lab, task, or landing pins.
        """
        from herzchen.fleet.tools import (
            AllowlistedPort, FeedbackLedger, ToolFacade, TokenBook,
        )
        from herzchen.fleet.tools.facade import LandingOwnerPort

        if not isinstance(token_book, TokenBook):
            raise TypeError("a live owner TokenBook is required")
        if getattr(due, "role", None) != "worker":
            raise PermissionError("landing facade requires a worker occurrence")
        grant = token_book.resolve(token)
        assignment_ref = getattr(due, "assignment_ref", None)
        generation = getattr(due, "generation", None)
        if (grant.role != "worker" or not isinstance(assignment_ref, Mapping)
                or grant.assignment != assignment_ref.get("id")):
            raise PermissionError("worker token does not name this occurrence assignment")
        app._current(assignment_ref, generation)

        def resolve_context(assignment: str) -> Mapping[str, Any]:
            if assignment != grant.assignment:
                raise PermissionError("worker token cannot resolve another assignment")
            app._current(assignment_ref, generation)
            return assignment_context(assignment)

        owner = LandingOwnerPort(resolve_context, fallback=fallback)
        allowed = tuple(spec.operation for spec in tools)
        return ToolFacade(
            tools, roles, AllowlistedPort(owner, allowed), token_book,
            FeedbackLedger() if ledger is None else ledger,
        )

    def _owner_request(self, operation: Callable[[], Any]) -> Any:
        completed, result = threading.Event(), {}
        with self._lock:
            if self._commands_stop.is_set() or not self._threads:
                raise RuntimeError("owner command lane is closed")
            self._owner_calls.put((operation, completed, result))
        completed.wait()
        if "error" in result:
            raise result["error"]
        return result["value"]

    @staticmethod
    def _execution_scope(app: Any, due: Any) -> dict[str, Any]:
        from otto.attention import native_target_identity
        adapter = app.runtime.adapter
        return {"schedule_id": due.schedule_id, "project": due.project_ref,
            "role": due.role, "session": ((due.host_evidence or {}).get("gateway_attempt") or {}).get("physical_session_id") or native_target_identity(due.target),
            "assignment": (due.assignment_ref["authority"], due.assignment_ref["id"], due.generation),
            "workspace": str(Path(adapter.worktree).resolve()),
            "writer": due.role == "worker" and due.profile == "workspace-write"}

    def restore_execution(self, app: Any, due: Any) -> None:
        """Reconcile one known handle, never enumerate historical attempts."""
        attempt = (due.host_evidence or {}).get("gateway_attempt")
        # UNKNOWN/stop/cancel alone do not prove native exit. The existing
        # exact owner custody disposition can release a terminal failed turn.
        released = due.stop_state == "completed" and due.completion_state == "succeeded"
        if not released:
            from otto.agents.manager_capture_reconciliation import retained_aborted_manager_capture
            released = retained_aborted_manager_capture(due, app.actor)
        if not released and (due.host_evidence or {}).get("role_preinitialization_custody_release"):
            from .worker_custody import retained_preinitialization_release
            try:
                retained_preinitialization_release(app, due)
                released = True
            except (ValueError, KeyError, TypeError, OSError):
                pass  # A missing or changed exact guard proof retains custody.
        if not released and (due.host_evidence or {}).get("worker_custody_release"):
            from .worker_custody import retained_capacity_release, INITIALIZER_SCHEMA
            marker = due.host_evidence["worker_custody_release"]
            try:
                retained_capacity_release(app, due,
                    _initializer_only=marker.get("schema") == INITIALIZER_SCHEMA)
                released = True
            except (ValueError, KeyError, TypeError, OSError):
                pass  # Missing/stale terminal proof keeps the conservative hold.
        if not released and (due.host_evidence or {}).get("claude_invalid_initializer_custody_release"):
            from claude_invalid_initializer_custody import retained as retained_invalid_initializer
            try:
                retained_invalid_initializer(app, due)
                released = True
            except (ValueError, KeyError, TypeError, OSError, PermissionError):
                pass  # An unqualified historical initializer keeps exact custody.
        if not released and (due.host_evidence or {}).get("manager_prompt_bound_custody_release"):
            from prompt_bound_manager_custody import retained as retained_prompt_refusal
            try:
                retained_prompt_refusal(app, due)
                released = True
            except (ValueError, KeyError, TypeError, OSError, PermissionError):
                pass  # Exact source/authorization/prior-settlement mismatch holds.
        if not released and due.stop_state == "stopped":
            from .worker_custody import retained_stopped_writer_conflict_release
            try:
                retained_stopped_writer_conflict_release(app, due)
                released = True
            except (ValueError, KeyError, TypeError, OSError):
                pass  # Any changed/ambiguous terminal proof keeps custody.
        if attempt and not released:
            self._capacity_holds[due.schedule_id] = self._execution_scope(app, due)
            if self._reconcile_hold(due.schedule_id):
                self.capacity.release_turn(due.schedule_id)
            else:
                self.capacity.ensure_turn(due.schedule_id, uncertain=True)
        else:
            if self._capacity_holds.pop(due.schedule_id, None) is not None:
                self.capacity.settle_turn(due.schedule_id)  # a disposition ends custody of used capacity
            self._forget_process_group(due.schedule_id)

    _PROCESS_GROUPS = "capacity-process-groups.json"

    def _load_process_groups(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads((self.directory / self._PROCESS_GROUPS).read_text())
        except (OSError, ValueError):
            return {}  # No readable record is no proof: the hold keeps its slot.
        if not isinstance(value, dict):
            return {}
        return {key: row for key, row in value.items() if isinstance(row, dict)}

    def _save_process_groups(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _atomic_json(self.directory / self._PROCESS_GROUPS, self._process_groups)

    def _forget_process_group(self, schedule_id: str) -> None:
        self._capacity_freed.discard(schedule_id)
        if self._process_groups.pop(schedule_id, None) is not None:
            self._save_process_groups()

    def record_process_group(self, schedule_id: str, pid: int) -> None:
        """Pin a live native process group (pgid plus start time) to its occurrence.

        The pin lets a later restart prove the group gone. It never releases
        custody: only the existing exact dispositions do that.
        """
        if schedule_id not in self._capacity_holds and not (self._executions.get(schedule_id) or {}).get("running"):
            raise RuntimeError("process group has no running or held occurrence")
        try:
            birth = list(_process_start_identity(pid)["birth"])
            pgid = os.getpgid(pid)
        except OSError as error:
            raise PermissionError("process is not live; nothing to pin") from error
        self._process_groups[schedule_id] = {"pid": pid, "pgid": pgid, "birth": birth}
        if schedule_id in self._capacity_freed:
            self._capacity_freed.discard(schedule_id)
            self.capacity.ensure_turn(schedule_id, uncertain=True)  # the group is live again: it costs its slot
        self._save_process_groups()

    @staticmethod
    def _group_state(record: Mapping[str, Any]) -> str:
        """gone | alive | reused | unproven. Only gone may free capacity.

        Gone needs both an empty process group and an absent pid. A pid that is
        live with another start time is reused, a pgid that still has members is
        alive, and anything unreadable is unproven; each of those stays held.
        """
        pid, pgid, birth = record.get("pid"), record.get("pgid"), record.get("birth")
        if (type(pid) is not int or type(pgid) is not int or pid <= 0 or pgid <= 0
                or not isinstance(birth, list) or not birth or any(type(v) is not int for v in birth)):
            return "unproven"
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            return "alive"
        except OSError:
            return "unproven"
        else:
            return "alive"
        try:
            live = _process_start_identity(pid)
        except (FileNotFoundError, ProcessLookupError):
            return "gone"
        except PermissionError:
            # The native reader also reports an exiting process this way.
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return "gone"
            except PermissionError:
                return "alive"
            return "alive"
        except (OSError, ValueError, IndexError):
            return "unproven"
        return "alive" if list(live["birth"]) == birth else "reused"

    def _reconcile_hold(self, schedule_id: str) -> bool:
        record = self._process_groups.get(schedule_id)
        if record is None or self._group_state(record) != "gone":
            return False
        self._capacity_freed.add(schedule_id)
        return True

    def reconcile_dead_holds(self) -> list[str]:
        """Stop charging capacity for holds whose process group is provably gone.

        Process exit does not prove absence of a provider effect, so the hold
        stays in the custody fence (_capacity_holds) and keeps blocking
        activation and supervised restart.
        """
        freed = [key for key in list(self._capacity_holds)
                 if key not in self._capacity_freed and self._reconcile_hold(key)]
        for key in freed:
            self.capacity.release_turn(key)
        # A reservation that no running turn or live hold stands behind is a leak
        # from an earlier life of this host; dead heavy owners likewise.
        self.capacity.sweep_turns(set(self.capacity_holds()) | {
            key for key, value in self._executions.items() if value["running"]})
        self.capacity.prune_dead_heavy()
        return freed

    def capacity_holds(self) -> dict[str, dict[str, Any]]:
        """The holds that still cost a slot: the fence minus provably dead groups."""
        return {key: scope for key, scope in self._capacity_holds.items()
                if key not in self._capacity_freed}

    def admit_execution(self, app: Any, due: Any, operation: Callable[[], Any]) -> OwnerCompletion:
        if self._dispatch_held:
            raise ExecutionAdmissionHeld("dispatch is held during inert startup")
        if not self.bounded_transports or self.current_bounded() is not self:
            raise RuntimeError("bounded execution requires its serialized owner")
        if not getattr(app.runtime.adapter, "owner_transport_only", False):
            raise TypeError("adapter has no isolated owner-callback transport contract")
        # Admission is the single launch boundary. Re-read the owner task here:
        # the prepared DueRecord can outlive a task pause and must not authorize
        # a provider call from its earlier readiness snapshot.
        if getattr(due, "host_state", None) in {"paused", "waiting"}:
            raise ExecutionAdmissionHeld("paused task cannot be admitted")
        from .owner_readers import task_reader
        task_ref = due.target.get("task_ref")
        project_ref = due.target.get("project_ref")
        if isinstance(task_ref, Mapping) and isinstance(project_ref, Mapping):
            observed = task_reader(app.portfolio.operations, project_ref, task_ref)(
                {key: task_ref[key] for key in ("authority", "kind", "id")})
            lifecycle = observed.get("lifecycle")
            lifecycle = getattr(lifecycle, "value", lifecycle)
            task_payload = observed.get("payload") if isinstance(observed, Mapping) else None
            readiness = task_payload.get("readiness") if isinstance(task_payload, Mapping) else None
            readiness_state = (readiness.get("state", readiness.get("status"))
                               if isinstance(readiness, Mapping) else readiness)
            if lifecycle in {"paused", "waiting"} or readiness_state in {"paused", "waiting"}:
                raise ExecutionAdmissionHeld("paused task cannot be admitted")
        current = self._executions.get(due.schedule_id)
        if current is not None:
            return current["completion"]
        if self._closing:
            raise RuntimeError("owner host is draining")
        value = OwnerCompletion()
        if due.project_ref not in self._project_order:
            self._project_order.append(due.project_ref)
        self._executions[due.schedule_id] = {"scope": self._execution_scope(app, due),
            "app": app, "operation": operation, "context": copy_context(),
            "completion": value, "running": False}
        return value

    def _eligible(self, scope: Mapping[str, Any]) -> bool:
        # Capacity follows processes: a hold whose group is provably gone no
        # longer counts, though it stays in the custody fence.
        active_by_id = {**self.capacity_holds(),
            **{key: value["scope"] for key, value in self._executions.items() if value["running"]}}
        active = list(active_by_id.values())
        managers = sum(row["role"] == "manager" for row in active)
        if not self.capacity.policy.admits_turn(scope["role"], len(active) - managers, managers):
            return False
        for row in active:
            if (row["assignment"] == scope["assignment"]
                    or scope["session"] and row["session"] == scope["session"]):
                return False
            if row["writer"] and scope["writer"]:
                first, second = Path(row["workspace"]), Path(scope["workspace"])
                if first.is_relative_to(second) or second.is_relative_to(first):
                    return False
        return True

    def bind_native_session(self, schedule_id: str, session: str) -> None:
        """Fence even a provider returning a reused identity before delivery."""
        if self._dispatch_held:
            raise ExecutionAdmissionHeld("dispatch is held during inert startup")
        job = self._executions.get(schedule_id)
        if job is None or not job["running"]:
            raise RuntimeError("native identity has no admitted owner occurrence")
        others = {**self._capacity_holds,
            **{key: value["scope"] for key, value in self._executions.items() if value["running"]}}
        if any(key != schedule_id and scope["session"] == session for key, scope in others.items()):
            raise PermissionError("native session already belongs to another live or uncertain occurrence")
        job["scope"]["session"] = session

    def _start_ready_executions(self) -> None:
        if self._dispatch_held or self._closing:
            return
        while not self._closing:
            ready = [value for value in self._executions.values()
                     if not value["running"] and self._eligible(value["scope"])]
            if not ready:
                return
            # Insertion order is the retained request order. Rotate project
            # when another is eligible; worker result turns beat new workers.
            start = (self._project_order.index(self._last_project) + 1
                     if self._last_project in self._project_order else 0)
            order = self._project_order[start:] + self._project_order[:start]
            ready.sort(key=lambda value: (order.index(value["scope"]["project"]),
                                          value["scope"]["role"] == "worker"))
            job = ready[0]
            try:
                due = job["app"]._read(job["scope"]["schedule_id"])
                if self._execution_scope(job["app"], due) != job["scope"]:
                    raise PermissionError("queued execution binding changed before admission")
                from .execution_operations import recheck_execution_admission
                admission_binding = recheck_execution_admission(job["app"], due)
                self.capacity.ensure_turn(job["scope"]["schedule_id"])
            except Exception as error:
                self._executions.pop(job["scope"]["schedule_id"])
                job["completion"].resolve(error=error)
                continue
            job["running"] = True
            job["admission_binding"] = admission_binding
            self._forget_process_group(job["scope"]["schedule_id"])  # a new attempt owns its own group
            self._last_project = job["scope"]["project"]
            schedule = job["scope"]["schedule_id"]

            def finish(value: Any = None, error: BaseException | None = None, *, job=job, schedule=schedule) -> None:
                if job.get("operation_started"):
                    try:
                        # Capture/settlement has already run through this owner.
                        self.restore_execution(job["app"], job["app"]._read(schedule))
                    except Exception as observed:
                        self._capacity_holds[schedule] = job["scope"]
                        error = error or observed
                else:
                    # Admission refusal has happened before an owner operation
                    # or provider call. It releases only this provisional slot.
                    self._capacity_holds.pop(schedule, None)
                    self._forget_process_group(schedule)
                try:
                    if not job.get("operation_started"):
                        self.capacity.release_turn(schedule)
                    elif schedule in self.capacity_holds():
                        self.capacity.ensure_turn(schedule, uncertain=True)  # custody keeps the units
                    elif schedule not in self._capacity_holds:
                        self.capacity.settle_turn(schedule)
                    # else: held in the fence with its group gone; the units are already back
                except Exception as observed:
                    self.failures["capacity:" + schedule] = {"code": type(observed).__name__, "message": str(observed)}
                self._executions.pop(schedule, None)
                job["completion"].resolve(value, error)

            try:
                def admitted_operation():
                    due = job["app"]._read(schedule)
                    if self._execution_scope(job["app"], due) != job["scope"]:
                        raise PermissionError("execution binding changed at the final launch check")
                    from .execution_operations import recheck_execution_admission
                    if recheck_execution_admission(job["app"], due) != job["admission_binding"]:
                        raise PermissionError("worker admission or dependency state changed before launch")
                    job["operation_started"] = True
                    token = _ACTIVE_EXECUTION.set((self, job))
                    try:
                        return job["operation"]()
                    finally:
                        _ACTIVE_EXECUTION.reset(token)
                result = job["context"].run(admitted_operation)
                after_owner(result, finish, lambda error, finish=finish: finish(error=error))
            except BaseException as error:
                finish(error=error)

    @staticmethod
    def adapter_transport(operation: Callable[[], Any]) -> Any:
        """Run only the isolated adapter; enqueue capture on the same owner."""
        host = ExecutionHost.current_bounded()
        if host is None:
            return operation()
        if host._dispatch_held:
            raise ExecutionAdmissionHeld("dispatch is held during inert startup")
        result = OwnerCompletion()
        with host._lock:
            host._external_waiting += 1

        def run() -> None:
            value, error = None, None
            try:
                value = operation()
            except BaseException as caught:
                error = caught
            def capture() -> None:
                try:
                    result.resolve(value, error)
                finally:
                    with host._lock:
                        host._external_waiting -= 1
            host._owner_calls.put((capture, threading.Event(), {}))
        try:
            host.retain(name="otto-native-transport", operation=run,
                        _admitted_execution=_ACTIVE_EXECUTION.get())
        except BaseException:
            with host._lock:
                host._external_waiting -= 1
            raise
        return result

    _RECONCILE_INTERVAL = 30.0

    def _capacity_tick(self) -> None:
        """Owner-loop upkeep: free what has provably died."""
        now = time.monotonic()
        if now - self._reconcile_checked >= self._RECONCILE_INTERVAL:
            self._reconcile_checked = now
            self.reconcile_dead_holds()  # the next pump sees the freed slots

    def start(self) -> None:
        if self._threads:
            raise RuntimeError("execution host is already started")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Holds were restored before the host serves; settle which are already dead.
        self.reconcile_dead_holds()
        if self.owner_path is not None:
            # Exclusive custody; a live competing owner is never replaced.
            # PID alone is only a locator.  Re-read its process-start and boot
            # identity so a stale/PID-reused file cannot claim this host.
            if self.owner_path.exists():
                try:
                    prior = json.loads(self.owner_path.read_text())
                except (OSError, ValueError, TypeError) as exc:
                    raise RuntimeError("owner custody locator is unreadable; inspect it before replacement") from exc
                if not isinstance(prior, Mapping) or not isinstance(prior.get("pid"), int):
                    raise RuntimeError("owner custody locator is incomplete")
                recorded_identity = prior.get("process_start_identity")
                boot = _host_boot_identity()
                boot_matches = (boot is None or prior.get("boot_identity") in {None, boot})
                try:
                    live_identity = _process_start_identity(int(prior["pid"]))
                except (FileNotFoundError, ProcessLookupError):
                    live_identity = None
                except PermissionError:
                    # The native reader also uses PermissionError for an
                    # exiting process (for example a macOS process whose
                    # kernel record disappeared between reads).  Confirm
                    # liveness with the ordinary signal-0 probe before
                    # deciding whether custody is still held.  A live but
                    # unverifiable process remains fail-closed.
                    try:
                        os.kill(int(prior["pid"]), 0)
                    except ProcessLookupError:
                        live_identity = None
                    except PermissionError as exc:
                        raise RuntimeError("another execution host owns this command directory") from exc
                    else:
                        raise RuntimeError("another execution host owns this command directory")
                if live_identity is not None and (
                        _same_process_start_identity(recorded_identity, live_identity)
                        and boot_matches):
                    raise RuntimeError("another execution host owns this command directory")
                if live_identity is not None and recorded_identity is None:
                    raise RuntimeError("owner custody locator has no process-start identity")
                # The locator is stale (dead process, PID reuse, or a prior
                # boot).  Removing this metadata is safe; it does not stop or
                # mutate the unrelated live process.
                self.owner_path.unlink()
                if self.socket_path is not None:
                    self.socket_path.unlink(missing_ok=True)
            process_identity = _process_start_identity(os.getpid())
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.owner_path, flags, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"schema": "otto.owner-host-custody.v2", "pid": os.getpid(),
                           "process_start_identity": process_identity,
                           "boot_identity": _host_boot_identity()}, stream,
                          sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            self._owns_owner_file = True
        # A partial atomic response from a crashed host is never a terminal
        # response. Only our own response-temp naming convention is removed.
        for temporary in self.directory.glob(".response-*.json.tmp"):
            temporary.unlink()
        if self.socket_path is not None:
            try:
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(str(self.socket_path))
                os.chmod(self.socket_path, 0o600)
                server.listen(4)
                server.settimeout(0.1)
                self._socket = server
            except Exception:
                server.close()
                self.owner_path.unlink(missing_ok=True)
                self._owns_owner_file = False
                raise
        for status in (False, True):
            thread = threading.Thread(target=self._serve, args=(status,),
                                      name="otto-status" if status else "otto-commands", daemon=False)
            self._threads.append(thread)
            thread.start()
        if self._socket is not None:
            thread = threading.Thread(target=self._serve_socket, name="otto-compatible-command-port", daemon=False)
            self._threads.append(thread)
            thread.start()

    def _status_read(self, request: Mapping[str, Any], operation: Any = None) -> Any:
        """Read shared owner ports on the same SQLite custodian as commands.

        Native transport waits pump the existing owner callback queue, so a
        status read remains available without concurrent connection use.
        Finite owner operations finish before status takes the command lane.
        """
        completed, result = threading.Event(), {}
        operation = operation or (lambda: self.handler(request))
        if self.bounded_transports:
            return operation() if threading.get_ident() == self._owner_thread else self._owner_request(operation)
        current = getattr(_DISPATCH_CONTEXT, "value", None)
        if current is not None and current[0] is self and current[1] == threading.get_ident():
            # A finite nested command is already on its serialized owner pump.
            # Queuing it back to that same waiting pump would deadlock. Foreign
            # readers still use the owner queue and cannot borrow this context.
            with self._command_lock:
                return operation()
        while True:
            with self._lock:
                if self._external_waiting:
                    self._owner_calls.put((operation, completed, result))
                    break
            # Do not block across a race into a native wait: on the next
            # iteration that owner can receive this read through its pump.
            if self._command_lock.acquire(blocking=False):
                try:
                    return operation()
                finally:
                    self._command_lock.release()
            completed.wait(0.01)
        completed.wait()
        if "error" in result:
            raise result["error"]
        return result["value"]

    def command_handle(self) -> Any:
        return _COMMAND_TRANSPORT.get()

    def _retain_socket_admission(self, request, binding, context):
        """Capture an authenticated finite intent without enqueueing a replay.

        The request file namespace belongs to owner file commands. Socket
        receipts deliberately have no request-*.json and are never dispatched
        on restart. A pending receipt after interruption remains UNKNOWN.
        """
        outer = self.command_handle()
        if not outer or outer["transport"] != "unix-socket":
            return None
        from herzchen.contracts import canonical_json
        token = outer["request_id"]
        metadata = {"schema": "otto.authenticated-socket-intent.v1", "request_id": token,
            "command": request.get("command"), "operation": request.get("operation"),
            "input_sha256": hashlib.sha256(canonical_json(request).encode()).hexdigest(),
            "caller": {"principal": binding.actor.actor,
                "assignment_ref": binding.assignment_ref.to_dict(), "generation": binding.generation,
                "adapter": binding.adapter, "native_session_id": binding.native_session_id,
                "schedule_id": binding.schedule_id},
            "project_identity": {k: context["project_ref"][k] for k in ("authority", "kind", "id")}}
        path = self.directory / ("socket-intent-" + token + ".json")
        response = self.directory / ("response-" + token + ".json")
        pending = self.directory / ("pending-" + token + ".json")
        with self._lock:
            if path.exists():
                with path.open("rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536 or json.loads(raw) != metadata:
                    raise PermissionError("socket handle belongs to different input or caller")
                outer["retained"] = True
                outer["recovered"] = True
                from .manager_journey_client import read_command_status
                retained = read_command_status(self.directory, token)
                return retained or {"outcome": "unknown", "terminal": False, "retry": False,
                    "request_id": token, "next_action": "Original authenticated intent is retained; reconcile its effect. Do not resend."}
            if response.exists() or pending.exists() or (self.directory / ("request-" + token + ".json")).exists():
                raise PermissionError("socket handle collides with an existing retained command")
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            _atomic_json(path, metadata)
            _atomic_json(pending, {"outcome": "pending", "terminal": False,
                "request_id": token, "request_retained": True, "response_path": str(response),
                "transport": "unix-socket", "authenticated_intent": metadata,
                "retry": False, "next_action": "Read command-status for this exact handle; pending does not prove absence of effects and never authorizes replay."})
            outer["retained"] = True
        return None

    def _retain_socket_terminal(self, result, outer):
        if outer is not None and isinstance(result, Mapping):
            result = {**result, "outer_command": dict(outer)}
            if (outer["transport"] == "unix-socket" and outer["retained"]
                    and not outer.get("recovered")):
                # Publish before sendall, including a disconnected client's
                # late completion. The owner receipt survives broken pipes.
                response = self.directory / ("response-" + outer["request_id"] + ".json")
                with self._lock:
                    if response.exists():
                        raise RuntimeError("authenticated socket terminal receipt already exists")
                    _atomic_json(response, result)
        return result

    def _call_bound(self, request: Mapping[str, Any], ingress: Any) -> Any:
        request = dict(request)
        request_id = request.pop("transport_request_id", None)
        transport = getattr(ingress, "transport", None)
        if request_id is not None and (transport != "unix-socket" or not isinstance(request_id, str)
                or len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id)):
            raise ValueError("native command transport handle must be 32 hexadecimal characters")
        if transport == "file-ipc":
            name = getattr(ingress.handle, "name", "")
            request_id = name[len("request-"):-len(".json")] if name.startswith("request-") and name.endswith(".json") else None
        outer = None if request_id is None else {"transport": transport, "request_id": request_id,
                    "retained": transport == "file-ipc"}
        token = _COMMAND_TRANSPORT.set(outer)
        try:
            try:
                result = self._call_bound_command(request, ingress)
            except Exception as exc:
                if not (outer and outer["transport"] == "unix-socket" and outer["retained"]):
                    raise
                result = {"outcome": "unknown", "error": type(exc).__name__, "message": str(exc),
                    "retry": False, "next_action": "Inspect the exact retained command; this exception does not establish absence of effects."}
            return after_owner(result, lambda result: self._retain_socket_terminal(result, outer),
                lambda exc: self._retain_socket_terminal({"outcome": "unknown", "retry": False,
                    "error": type(exc).__name__, "message": str(exc),
                    "next_action": "Reconcile this exact retained command; completion failure does not prove absence of effects."}, outer))
        finally:
            _COMMAND_TRANSPORT.reset(token)

    def _call_bound_command(self, request: Mapping[str, Any], ingress: Any) -> Any:
        from .identity_context import HostCallerBinding, check_caller_claims
        identity_read = request.get("command") in {"whoami", "effective-context"}
        claims = {"caller_principal", "caller_assignment_ref", "caller_generation", "caller_native_session_id",
                  "logical_agent_id", "caller_context", "host_caller_binding"}
        compatibility_file = (self.owner_file_compatibility
            and getattr(ingress, "transport", None) == "file-ipc")
        if self.caller_binding_reader is None or compatibility_file:
            if identity_read or request.get("command") == "task-list-author" or claims.intersection(request):
                return {"outcome": "held", "reason": "trusted per-request caller binding is unavailable",
                        "next_action": "use an owner-supported identity-bearing host ingress",
                        "provider_called": False, "effects_started": False}
            # Compatibility lane remains explicitly owner custody. It makes
            # no claim to authenticate the original file/socket submitter.
            return self.handler(request)
        try:
            binding = self.caller_binding_reader(ingress)
            if not isinstance(binding, HostCallerBinding):
                raise PermissionError("host ingress has no trusted caller binding")
            context = self.caller_context_resolver(binding)
            clean = check_caller_claims(context, request)
            if identity_read:
                if set(clean) != {"command"}:
                    raise PermissionError("effective-context reads only the bound caller; administrative targets need a separate authorized command")
                recovered = self._retain_socket_admission(clean, binding, context)
                if recovered is not None:
                    return recovered
                return {"outcome": "read", "caller_context": context, "provider_called": False, "effects_started": False}
            authorizer = self.caller_authorizer or getattr(self.handler, "authorize_caller", None)
            if not callable(authorizer):
                raise PermissionError("command has no caller-aware owner authorization")
            if authorizer(context, clean) is False:
                raise PermissionError("owner command authorization rejected this caller")
            if not getattr(_INERT_STATUS_CONTEXT, "value", False):
                recovered = self._retain_socket_admission(clean, binding, context)
                if recovered is not None:
                    return recovered
        except Exception as exc:
            return {"outcome": "error", "error": type(exc).__name__, "message": str(exc),
                    "provider_called": False, "effects_started": False,
                    "next_action": "refresh the trusted caller binding and current owner authorization"}
        bound = getattr(self.handler, "dispatch_bound", None)
        result = bound(context, clean) if callable(bound) else self.handler(clean)
        return after_owner(result, lambda result: dict(result, caller_context=context,
                    target_context={key: clean[key] for key in ("principal", "assignment_ref", "project_ref", "task_ref") if key in clean}))

    def _authorize_inert_request(self, request: Mapping[str, Any], ingress: Any) -> None:
        """Check caller authority without retaining or dispatching the request."""
        from .identity_context import HostCallerBinding, check_caller_claims
        if self.caller_binding_reader is None or (self.owner_file_compatibility
                and getattr(ingress, "transport", None) == "file-ipc"):
            raise PermissionError("inert dispatch requires an authenticated host ingress")
        binding = self.caller_binding_reader(ingress)
        if not isinstance(binding, HostCallerBinding):
            raise PermissionError("host ingress has no trusted caller binding")
        context = self.caller_context_resolver(binding)
        clean = check_caller_claims(context, request)
        authorizer = self.caller_authorizer or getattr(self.handler, "authorize_caller", None)
        if not callable(authorizer) or authorizer(context, clean) is False:
            raise PermissionError("owner command authorization rejected this caller")

    def _dispatch(self, request: Mapping[str, Any], *, ingress: Any = None,
                  _turn_admitted: bool = False) -> Any:
        try:
            command = request.get("command")
            # Event-cursor waiting is read-only. Authenticate it on the socket
            # thread and leave the serialized Store lane available for answers.
            if (self.bounded_transports and threading.get_ident() != self._owner_thread
                    and command != "wait-for-answer"):
                return self._owner_request(lambda: self._dispatch(request, ingress=ingress))
            if self._dispatch_held:
                command = request.get("command")
                if command != "status":
                    try:
                        self._authorize_inert_request(request, ingress)
                    except Exception as exc:
                        return {"outcome": "error", "error": type(exc).__name__, "message": str(exc),
                                "provider_called": False, "effects_started": False}
                    return {"outcome": "held", "reason": "dispatch is held during inert startup",
                            "dispatch": "held", "provider_called": False,
                            "effects_started": False, "retry": False}
                def inert_read():
                    previous_inert = getattr(_INERT_STATUS_CONTEXT, "value", False)
                    _INERT_STATUS_CONTEXT.value = True
                    try:
                        result = self._call_bound(request, ingress)
                    finally:
                        _INERT_STATUS_CONTEXT.value = previous_inert
                    def include_startup(value):
                        if isinstance(value, Mapping) and isinstance(value.get("caller_context"), Mapping):
                            caller = value["caller_context"]
                            report = None
                            if callable(self.startup_report_reader):
                                report = dict(self.startup_report_reader(caller))
                            elif isinstance(self._startup_report, Mapping):
                                report = {key: self._startup_report[key] for key in
                                    ("source_commit", "manifest_sha256", "pid", "dispatch",
                                     "admission_report", "phase_timings", "provider_called", "composition_source_next_append")
                                    if key in self._startup_report}
                            return {**value, "startup": report,
                                    "dispatch": "held", "provider_called": False}
                        return value
                    return after_owner(result, include_startup)
                return self._status_read(request, inert_read)
            # Admission happens before taking the shared Store command lock.
            # A queued manager must not block another project's owner pump.
            turn_admission = getattr(self, "turn_admission", None)
            if (not self.bounded_transports and not _turn_admitted and callable(turn_admission)
                    and request.get("command") in _MANAGER_TURN_COMMANDS):
                with turn_admission():
                    return self._dispatch(request, ingress=ingress, _turn_admitted=True)
            if self._closing and _starts_work(request):
                return {"outcome": "held", "reason": "owner host is draining",
                        "provider_called": False, "effects_started": False, "retry": False}
            if command == "wait-for-answer":
                return self._call_bound(request, ingress)
            # The manager-only planning write uses the same custodian pump,
            # with socket peer authorization before its finite public effect.
            if request.get("command") in {"status", "whoami", "effective-context", "task-list-author", "lookup-occurrence", "follow-occurrence", "read-result", "read-artifact", "consume-result", "run-worker", "project-documents"}:
                def finite():
                    previous = getattr(_DISPATCH_CONTEXT, "value", None)
                    _DISPATCH_CONTEXT.value = (self, threading.get_ident(), False)
                    try:
                        return self._call_bound(request, ingress)
                    finally:
                        _DISPATCH_CONTEXT.value = previous
                return self._status_read(request, finite)
            with self._command_lock:
                if self._closing and _starts_work(request):
                    return {"outcome": "held", "reason": "owner host is draining",
                            "provider_called": False, "effects_started": False, "retry": False}
                if self._closing and request.get("command") not in _REENTRANT_COMMANDS:
                    return {"outcome": "held", "reason": "owner host is draining", "provider_called": False}
                previous = getattr(_DISPATCH_CONTEXT, "value", None)
                _DISPATCH_CONTEXT.value = (self, threading.get_ident(),
                    (request.get("command") == "manager-continue" and request.get("operation") == "dispatch")
                    or (request.get("command") == "execution-control" and request.get("operation") == "resume")
                    or request.get("command") in {"start-manager", "start-retained-worker", "start-retained-help", "manager-worker-result", "manager-task-settlement", "manager-help-result", "start-retained-child", "parent-child-result"})
                try:
                    return self._call_bound(request, ingress)
                finally:
                    _DISPATCH_CONTEXT.value = previous
        except Exception as exc:
            return {"outcome": "error", "error": type(exc).__name__, "message": str(exc),
                    "next_action": "inspect the exact canonical request before retry"}

    def _serve_socket(self) -> None:
        # Optional compatibility for installed callers. File requests remain
        # the durable transport; both surfaces share one mutation custodian.
        connections = {}
        while not self._commands_stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            with self._lock:
                connection_id = id(connection)
                # Real accept calls return a fresh socket object. A repeated
                # object can come from a test or injected listener; never
                # assign the same active stream to multiple readers.
                if connection_id in connections:
                    continue
                def serve_admitted(connection=connection, connection_id=connection_id):
                    try:
                        self._serve_socket_connection(connection)
                    finally:
                        with self._lock:
                            connections.pop(connection_id, None)
                thread = threading.Thread(target=serve_admitted,
                    name="otto-caller-socket-request", daemon=False)
                self._children.add(thread)
                connections[connection_id] = thread
                thread.start()
        # Receipt publication happens in the connection worker before it tries
        # to send the response. Keep the listener alive through that settlement
        # for every connection admitted before shutdown.
        with self._lock:
            admitted = tuple(connections.values())
        for thread in admitted:
            thread.join()

    def _serve_socket_connection(self, connection: socket.socket) -> None:
        try:
            with connection:
                connection.settimeout(5)
                raw = b""
                while not raw.endswith(b"\n") and len(raw) <= 256 * 1024:
                    part = connection.recv(65536)
                    if not part:
                        break
                    raw += part
                from .identity_context import HostIngress
                result = self._dispatch(json.loads(raw), ingress=HostIngress("unix-socket", connection))
                if isinstance(result, OwnerCompletion):
                    # A native wait settles outside the owner pump, while the
                    # owner remains free to process its corresponding answer.
                    ready = threading.Event()
                    observed = {}
                    self._owner_request(lambda: result.then(
                        lambda value: (observed.update(value=value), ready.set()),
                        lambda error: (observed.update(error=str(error)), ready.set())))
                    ready.wait()
                    result = observed.get("value", {"outcome": "error", "message": observed.get("error")})
                connection.sendall(json.dumps(json_value(result), sort_keys=True).encode())
        except (OSError, ValueError) as exc:
            self.failures["socket"] = {"code": type(exc).__name__, "message": str(exc)}
        finally:
            with self._lock:
                self._children.discard(threading.current_thread())

    def _request_paths(self) -> list[Path]:
        # Streams the directory and keeps only request names; answered responses
        # are pruned on a timer below, so this scan stays bounded in practice.
        with os.scandir(self.directory) as entries:
            return [self.directory / entry.name for entry in entries
                    if entry.name.startswith("request-") and entry.name.endswith(".json")]

    def _prune_answered_responses(self) -> None:
        # Answered responses (request consumed, terminal, past grace) leave the
        # lane in bounded batches so the directory never grows without limit.
        now = time.monotonic()
        if now - self._last_response_prune < 60:
            return
        self._last_response_prune = now
        try:
            prune_answered_responses(self.directory, limit=200)
        except OSError as exc:
            self.failures["response-retention"] = {"code": type(exc).__name__, "message": str(exc)}

    def _serve_files(self, status: bool, *, allowed: frozenset[str] | None = None) -> None:
        if not status:
            self._prune_answered_responses()
        paths = self._request_paths()
        # Hash order is unrelated to admission age and can starve a project.
        def age(path):
            try:
                return path.stat().st_mtime_ns, path.name
            except FileNotFoundError:
                return float("inf"), path.name
        paths.sort(key=age)
        for path in paths:
            token = path.name[len("request-"):-len(".json")]
            if not token or any(char not in "0123456789abcdef" for char in token):
                if not status:
                    # Keep rejected bytes as diagnostic evidence. Never dispatch
                    # an invalid handle or let two serving threads race a reply.
                    with self._lock:
                        rejection = self.directory / ("response-" + token + ".json")
                        if not rejection.exists():
                            _atomic_json(rejection, {"outcome": "rejected", "error": {"code": "invalid_request_id",
                                "message": "transport handle must be nonempty lowercase hexadecimal"},
                                "request_id": token, "request_path": str(path),
                                "request_retained": True, "request_dispatched": False,
                                "provider_called": False, "effects_started": False, "retry": False,
                                "next_action": "Inspect the rejected request; use a valid fresh handle only for an explicitly corrected intent."})
                continue
            response = self.directory / ("response-" + token + ".json")
            acquired = False
            claimed = False
            deferred = False
            try:
                request = json.loads(path.read_text())
                command = request.get("command")
                if self._dispatch_held and command != "status":
                    continue
                if (command == "status") != status:
                    continue
                if command == "answer-session-result":
                    pending_path = self.directory / ("pending-" + token + ".json")
                    if pending_path.exists():
                        try:
                            retained_state = json.loads(pending_path.read_text())
                            retry_after = retained_state.get("retry_after")
                        except (OSError, ValueError, TypeError):
                            retry_after = None
                        if isinstance(retry_after, (int, float)) and retry_after > time.time():
                            continue
                # The pump also sees its own outer request. It already owns
                # that token; never describe it as a queued second dispatch.
                with self._lock:
                    if token in self._active_files:
                        continue
                capability = _nested_capability(request) if allowed is not None else "admitted"
                if capability == "retained":
                    pending = self.directory / ("pending-" + token + ".json")
                    if not pending.exists():
                        timing = ReceiptTiming(stable_correlation_id(request, fallback=token))
                        timing.observe("queued").absent("processing", reason="owner_lane_retained")
                        timing.absent("native", reason="native_phase_not_started")
                        timing.absent("terminal", reason="terminal_response_not_yet_observed")
                        _atomic_json(pending, {"outcome": "pending", "request_id": token,
                            "request_retained": True, "provider_called": False, "effects_started": False,
                            "retry": False, "response_path": str(response),
                            "reason": "another native manager turn owns the command lane",
                            "correlation_id": timing.correlation_id,
                            "receipt_timing": timing.as_dict(),
                            "next_action": "Observe this exact response path after the current turn settles; do not resend the request or rerun tests while waiting."})
                    continue
                if not status:
                    # A compatible socket dispatch may own a native wait. Do
                    # not claim/block its child's file before its pump sees it.
                    # Turn admission can wait for a global slot; let it do so
                    # before taking the shared Store lock so active projects
                    # can keep pumping finite owner callbacks.
                    queued_turn = (callable(getattr(self, "turn_admission", None))
                                   and command in _MANAGER_TURN_COMMANDS)
                    if not queued_turn:
                        acquired = self._command_lock.acquire(blocking=False)
                        if not acquired:
                            continue
                    if self._closing and _starts_work(request):
                        continue
                with self._lock:
                    if token in self._active_files:
                        continue
                    self._active_files.add(token)
                    claimed = True
                if not response.exists():
                    timing = ReceiptTiming(stable_correlation_id(request, fallback=token))
                    timing.observe("queued").observe("processing")
                    timing.absent("native", reason="command_transport_has_no_native_phase")
                    if capability == "held":
                        result = {"outcome": "held", "reason": "operation is not admitted during the current native transport wait",
                                  "command": command, "provider_called": False, "effects_started": False,
                                  "retry": False, "request_retained": False,
                                  "next_action": "Return this held result to the manager; inspect owner status and wait for the current turn to settle before a new explicit intent. Do not resend or rerun tests while waiting."}
                    else:
                        if command in _REENTRANT_COMMANDS and not _starts_work(request):
                            # This is transport progress, not an assertion that
                            # effects are absent. Publish before synchronous
                            # finite work so a child need not wait on itself.
                            pending = self.directory / ("pending-" + token + ".json")
                            _atomic_json(pending, {"outcome": "pending", "terminal": False,
                                "request_id": token, "request_retained": True,
                                "request_state": "processing", "response_path": str(response),
                                "retry": False,
                                "correlation_id": timing.correlation_id,
                                "receipt_timing": {**timing.as_dict(), "phases": {
                                    **timing.as_dict()["phases"],
                                    "terminal": {"state": "absent", "observed_at": None,
                                                  "reason": "terminal_response_not_yet_observed",
                                                  "clock": "unavailable"},
                                }, "gaps": [*timing.as_dict()["gaps"], {
                                    "kind": "absent", "phase": "terminal",
                                    "reason": "terminal_response_not_yet_observed"}]},
                                "next_action": "The owner is processing this exact request. Observe its terminal response with command-status; do not resend or infer owner death."})
                        from .identity_context import HostIngress
                        result = self._dispatch(request, ingress=HostIngress("file-ipc", path))
                    if isinstance(result, OwnerCompletion):
                        deferred = True
                        _atomic_json(self.directory / ("pending-" + token + ".json"), {
                            "outcome": "pending", "request_id": token, "request_retained": True,
                            "response_path": str(response), "retry": False,
                            "reason": "retained execution is queued or awaiting its original transport",
                            "next_action": "Observe this exact retained handle; do not resend."})

                        def complete(value: Any = None, error: BaseException | None = None,
                                     *, token=token, response=response, path=path, timing=timing) -> None:
                            try:
                                if error is not None:
                                    value = {"outcome": "error", "error": type(error).__name__,
                                        "message": str(error), "retry": False,
                                        "next_action": "reconcile the original occurrence before replay"}
                                _atomic_json(response, _timed_receipt(value, timing))
                                (self.directory / ("pending-" + token + ".json")).unlink(missing_ok=True)
                                path.unlink(missing_ok=True)
                            except Exception as exc:
                                self.failures[token] = {"code": type(exc).__name__, "message": str(exc)}
                            finally:
                                with self._lock:
                                    self._active_files.discard(token)
                        result.then(complete, lambda error, complete=complete: complete(error=error))
                        continue
                    if (command in {"manager-worker-result", "manager-help-result", "start-retained-child", "parent-child-result", "answer-session-result"} and result.get("outcome") == "pending"
                            and result.get("provider_called") is False and result.get("effects_started") is False):
                        pending = self.directory / ("pending-" + token + ".json")
                        if command == "answer-session-result" or not pending.exists():
                            retained = _timed_receipt(result, timing)
                            value = {**retained, "request_id": token, "request_retained": True,
                                "response_path": str(response),
                                "next_action": ("The owner retains this exact answer continuation and rechecks its asking Due until settlement; do not resend it."
                                    if command == "answer-session-result" else
                                    "The owner retains this observed worker result until the same manager settles; do not resend it.")}
                            if command == "answer-session-result":
                                value["retry_after"] = time.time() + 0.5
                            _atomic_json(pending, value)
                        continue
                    _atomic_json(response, _timed_receipt(result, timing))
                (self.directory / ("pending-" + token + ".json")).unlink(missing_ok=True)
                path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
            except Exception as exc:
                self.failures[token] = {"code": type(exc).__name__, "message": str(exc)}
            finally:
                if claimed and not deferred:
                    with self._lock:
                        self._active_files.discard(token)
                if acquired:
                    self._command_lock.release()

    def _serve(self, status: bool) -> None:
        if self.bounded_transports and not status:
            self._owner_thread = threading.get_ident()
        stop = self._stop if status else self._commands_stop
        while not stop.is_set():
            if self.bounded_transports and not status:
                with self._command_lock:
                    self._owned(self._pump_owner_calls)
                    if not self._dispatch_held:
                        self._serve_files(False)
                    self._owned(self._pump_owner_calls)
                    self._owned(self._start_ready_executions)
                    self._owned(self._capacity_tick)
            else:
                self._serve_files(status)
            stop.wait(0.05)
        if not status:
            if self.bounded_transports:
                # Admission to this queue is closed before its final drain.
                # Authenticated reads already admitted must still resolve.
                while not self._owner_calls.empty():
                    self._owned(self._pump_owner_calls)
            # An inert owner preserves all queued business requests for a later
            # explicit operator decision; shutdown never turns into a replay.
            if not self._dispatch_held:
                self._serve_files(False, allowed=_REENTRANT_COMMANDS)

    @staticmethod
    def owner_callback(callback: Callable[..., Any] | None) -> Callable[..., Any] | None:
        """Marshal an admitted transport callback to its serialized owner."""
        context = getattr(_DISPATCH_CONTEXT, "value", None)
        if callback is None or context is None or not (context[2] or context[0].bounded_transports):
            return callback
        host, owner_thread, _ = context

        def owned(*args: Any, **kwargs: Any) -> Any:
            if threading.get_ident() == owner_thread:
                return callback(*args, **kwargs)
            completed, result = threading.Event(), {}
            with host._lock:
                if not host._external_waiting:
                    raise RuntimeError("owner callback arrived outside its admitted transport wait")
                host._owner_calls.put((lambda: callback(*args, **kwargs), completed, result))
            completed.wait()
            if "error" in result:
                raise result["error"]
            return result["value"]
        return owned

    def _pump_owner_calls(self) -> None:
        for _ in range(32):
            try:
                operation, completed, result = self._owner_calls.get_nowait()
            except queue.Empty:
                return
            try:
                if self.bounded_transports:
                    result["value"] = self._owned(operation)
                else:
                    with self._command_lock:
                        result["value"] = operation()
            except BaseException as exc:
                result["error"] = exc
            finally:
                completed.set()

    @staticmethod
    def external_call(operation: Callable[[], Any]) -> Any:
        """Yield only an admitted manager's transport wait, never owner custody.

        The owner thread executes finite nested commands and native admission
        callbacks itself. A multi-project service may release the shared lock
        during the wait and reacquire it for those callbacks. The transport
        thread cannot mutate the owner through an unwrapped callback; result
        capture and settlement resume on the owner.
        """
        context = getattr(_DISPATCH_CONTEXT, "value", None)
        if context is None or not context[2]:
            return operation()
        host, owner_thread, _ = context
        if threading.get_ident() != owner_thread:
            raise RuntimeError("transport wait must be entered by its command owner")
        completed, result = threading.Event(), {}

        def run() -> None:
            try:
                result["value"] = operation()
            except BaseException as exc:
                result["error"] = exc
            finally:
                completed.set()

        with host._lock:
            host._external_waiting += 1
        # A one-owner service can admit multiple project manager turns while
        # retaining a single Store write lock. Release only for the external
        # provider wait; owner callbacks and retained commands reacquire it.
        lock_state = None
        if getattr(host, "release_command_lock_during_wait", False):
            release_save = getattr(host._command_lock, "_release_save", None)
            if callable(release_save):
                lock_state = release_save()
        transport = threading.Thread(target=run, name="otto-manager-transport", daemon=False)
        try:
            transport.start()
            while not completed.is_set():
                host._pump_owner_calls()
                host._serve_files(False, allowed=_REENTRANT_COMMANDS)
                completed.wait(0.01)
            host._pump_owner_calls()
        finally:
            with host._lock:
                host._external_waiting -= 1
                while not host._external_waiting:
                    try:
                        _, waiting, value = host._owner_calls.get_nowait()
                    except queue.Empty:
                        break
                    value["error"] = RuntimeError("transport completed before owner callback admission")
                    waiting.set()
            if transport.ident is not None:
                transport.join()
            if lock_state is not None:
                host._command_lock._acquire_restore(lock_state)
        if "error" in result:
            raise result["error"]
        return result["value"]

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Retain prepared work/result delivery on the existing owner lane.

        Execution and canonical settlement stay on the command custodian, not
        an arbitrary child thread. Restart consumes the same prepared occurrence
        through its canonical attempt fence rather than resending its provider.
        """
        if self._dispatch_held and request.get("command") not in {"status", "whoami", "effective-context"}:
            return {"outcome": "held", "reason": "dispatch is held during inert startup",
                    "dispatch": "held", "provider_called": False, "effects_started": False,
                    "retry": False}
        context = getattr(_DISPATCH_CONTEXT, "value", None)
        if context is None or context[0] is not self or context[1] != threading.get_ident():
            raise RuntimeError("worker submission requires its serialized command owner")
        if self._closing and not (self.bounded_transports and request.get("command") in {
                "manager-worker-result", "manager-task-settlement", "manager-help-result", "parent-child-result",
                "answer-session-result"}):
            raise RuntimeError("execution host is draining; no new worker may be admitted")
        command = request.get("command")
        if command == "answer-session-result":
            base_fields = {"command", "asking_schedule_id", "report_ref", "issue_id",
                           "assignment_ref", "generation", "native_session_id"}
            if set(request) != base_fields:
                raise ValueError("answer continuation must be bound to its exact asking occurrence")
            schedule_id = request["asking_schedule_id"]
            if not isinstance(schedule_id, str) or not schedule_id.strip():
                raise ValueError("answer continuation needs its asking schedule id")
        elif command in {"start-retained-worker", "start-retained-help", "manager-worker-result",
                         "manager-task-settlement", "manager-help-result", "start-retained-child",
                         "parent-child-result"}:
            schedule_id = request.get("schedule_id")
            if not isinstance(schedule_id, str) or not schedule_id.strip():
                raise ValueError("retained work needs its schedule id")
        else:
            raise ValueError("only prepared work or an observed result/completion continuation may be retained")
        encoded = json.dumps(json_value(request), sort_keys=True, separators=(",", ":"))
        token = hashlib.sha256(encoded.encode()).hexdigest()
        path = self.directory / ("request-" + token + ".json")
        response = self.directory / ("response-" + token + ".json")
        if not response.exists():
            if path.exists():
                if json.loads(path.read_text()) != dict(request):
                    raise ValueError("retained worker input changed")
            else:
                _atomic_json(path, dict(request))
        return {"outcome": "admitted", "schedule_id": schedule_id,
                "retained_handle": token, "response_path": str(response),
                "provider_called": False, "retry_provider": False,
                "next_command": "worker-status" if request["command"] == "start-retained-worker" else "command-status"}

    def rearm_pre_effect_worker_notification(self, request: Mapping[str, Any], *,
                                            expected_response_sha256: str) -> Mapping[str, Any]:
        """Closed-owner recovery of the same held worker observation handle.

        Never retries worker execution. The canonical handler still validates
        the settled worker/manager and fences its deterministic callback. The
        historical HELD bytes and an explicit transport reconciliation remain.
        """
        if (not isinstance(expected_response_sha256, str) or len(expected_response_sha256) != 64
                or any(char not in "0123456789abcdef" for char in expected_response_sha256)):
            raise ValueError("exact held response digest required")
        if self._threads or self._children or self._active_files:
            raise RuntimeError("close the owner before retained notification recovery")
        if self.owner_path.exists():
            try:
                os.kill(int(json.loads(self.owner_path.read_text())["pid"]), 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError("another live owner holds this notification")
        if (set(request) != {"command", "task", "principal", "schedule_id"}
                or request.get("command") != "manager-worker-result"):
            raise ValueError("only the exact retained worker-result observation may be recovered")
        encoded = json.dumps(json_value(request), sort_keys=True, separators=(",", ":"))
        token = hashlib.sha256(encoded.encode()).hexdigest()
        response = self.directory / ("response-" + token + ".json")
        path = self.directory / ("request-" + token + ".json")
        history = self.directory / ("reconciled-response-" + token + "-" + expected_response_sha256 + ".json")
        receipt_path = self.directory / ("reconciliation-" + token + ".json")
        receipt = {"schema": "otto.pre-effect-worker-notification-reconciliation.v1",
            "retained_handle": token, "request": dict(request),
            "source_response_sha256": expected_response_sha256,
            "source_response_path": str(history), "provider_called": False,
            "effect": "same_worker_observation_rearmed_after_owner_reconciliation"}
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != receipt:
                raise ValueError("retained notification reconciliation changed")
            if hashlib.sha256(history.read_bytes()).hexdigest() != expected_response_sha256:
                raise ValueError("historical held response changed")
            if response.exists() and hashlib.sha256(response.read_bytes()).hexdigest() == expected_response_sha256:
                if not path.exists(): _atomic_json(path, dict(request))
                response.unlink()
            elif not response.exists() and not path.exists():
                _atomic_json(path, dict(request))
            return {**receipt, "replayed": True}
        raw = response.read_bytes()
        held = json.loads(raw)
        # Current owner replies wrap the same effect result with read-only
        # correlation/timing metadata. Keep all original bytes in history;
        # unwrap only the exact current transport identity before qualification.
        transport_fields = {"correlation_id", "outer_command", "receipt_timing"}
        if isinstance(held, Mapping) and transport_fields.intersection(held):
            timing = held.get("receipt_timing")
            if (not transport_fields.issubset(held) or held.get("correlation_id") != token
                    or held.get("outer_command") != {"request_id": token, "retained": True, "transport": "file-ipc"}
                    or not isinstance(timing, Mapping) or timing.get("schema") != "otto.recovery-timing.v1"
                    or timing.get("correlation_id") != token):
                raise ValueError("notification transport metadata differs from the exact retained handle")
            held = {key: value for key, value in held.items() if key not in transport_fields}
        pre_effect = (held == {"outcome": "held", "provider_called": False, "effects_started": False,
                    "retry": False, "reason": "reconcile the retained manager effect before worker-result continuation"}
            or held == {"outcome": "error", "error": "OccurrencePreparationError",
                "message": "native session has no current owner assignment binding",
                "next_action": "inspect the exact canonical request before retry"})
        if hashlib.sha256(raw).hexdigest() != expected_response_sha256 or not pre_effect:
            raise ValueError("notification is not the exact proven pre-effect held result")
        if history.exists():
            if history.read_bytes() != raw:
                raise ValueError("historical response differs")
        else:
            fd = os.open(history, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if path.exists():
            if json.loads(path.read_text()) != dict(request):
                raise ValueError("retained notification request changed")
        else:
            _atomic_json(path, dict(request))
        _atomic_json(receipt_path, receipt)
        response.unlink()
        return {**receipt, "replayed": False}

    def rearm_pre_effect_worker_start(self, request: Mapping[str, Any], *,
                                     application: Any, expected_response_sha256: str) -> Mapping[str, Any]:
        """Closed owner resumes the same unattempted worker after selector reconciliation.

        A failed control command is not itself no-effect proof. Both the exact
        validation failure and the current canonical occurrence must agree.
        The original response and its status stay immutable in history; neither
        a native attempt nor an allowance is reset by this transport recovery.
        """
        from herzchen.contracts import ResourceRef
        if (not isinstance(expected_response_sha256, str) or len(expected_response_sha256) != 64
                or any(c not in "0123456789abcdef" for c in expected_response_sha256)):
            raise ValueError("exact historical response digest required")
        if self._threads or self._children or self._active_files:
            raise RuntimeError("close the owner before retained start recovery")
        if self.owner_path.exists():
            try:
                os.kill(int(json.loads(self.owner_path.read_text())["pid"]), 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError("another live owner holds this start")
        if (set(request) != {"command", "task", "principal", "schedule_id"}
                or request.get("command") != "start-retained-worker"):
            raise ValueError("exact retained worker start required")
        due = application._read(request["schedule_id"])
        if (due.role != "worker" or due.recipient != request["principal"]
                or due.lifecycle_owner != application.actor or due.manager_ref != application.actor
                or due.stop_state != "active" or due.completion_state != "none"
                or (due.host_evidence or {}).get("gateway_attempt") or due.last_result is not None):
            raise PermissionError("only the same owner-bound unattempted worker may recover")
        current = application.assignments.get(ResourceRef.from_dict(due.assignment_ref))
        if current.ref.to_dict() != due.assignment_ref or current.generation != due.generation:
            raise PermissionError("worker assignment changed before recovery")
        ready = application.recover(schedule_id=due.schedule_id, execute=False)
        if ready.get("outcome") != "prepared":
            raise ValueError("retained worker requires canonical preparation reconciliation")
        token = hashlib.sha256(json.dumps(json_value(request), sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        response = self.directory / ("response-" + token + ".json")
        history = self.directory / ("reconciled-start-response-" + token + "-" + expected_response_sha256 + ".json")
        receipt_path = self.directory / ("start-reconciliation-" + token + ".json")
        receipt = {"schema": "otto.pre-effect-worker-start-reconciliation.v1",
            "retained_handle": token, "request": dict(request),
            "assignment_ref": due.assignment_ref, "generation": due.generation,
            "source_response_sha256": expected_response_sha256,
            "source_response_path": str(history), "provider_called": False,
            "effect": "same_unattempted_worker_start_rearmed_after_canonical_reconciliation"}
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != receipt or hashlib.sha256(history.read_bytes()).hexdigest() != expected_response_sha256:
                raise ValueError("retained start reconciliation differs")
            path = self.directory / ("request-" + token + ".json")
            if response.exists() and hashlib.sha256(response.read_bytes()).hexdigest() == expected_response_sha256:
                _atomic_json(path, dict(request)); response.unlink()
            elif not response.exists() and not path.exists():
                _atomic_json(path, dict(request))
            return {**receipt, "replayed": True}
        raw = response.read_bytes()
        failure = json.loads(raw)
        if (hashlib.sha256(raw).hexdigest() != expected_response_sha256
                or failure.get("correlation_id") != token
                or failure.get("outcome") != "error"
                or failure.get("error") != "OccurrencePreparationError"
                or failure.get("message") != "manual selector predecessor effects require reconciliation"):
            raise ValueError("exact pre-start selector rejection required")
        if history.exists() and history.read_bytes() != raw:
            raise ValueError("historical start response differs")
        if not history.exists():
            fd = os.open(history, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        status = self.directory / ("status-response-" + token + ".json")
        if status.exists():
            status_history = self.directory / ("reconciled-start-status-" + token + ".json")
            if status_history.exists() and status_history.read_bytes() != status.read_bytes():
                raise ValueError("historical start status differs")
            if not status_history.exists():
                fd = os.open(status_history, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(status.read_bytes()); stream.flush(); os.fsync(stream.fileno())
        _atomic_json(receipt_path, receipt)
        _atomic_json(self.directory / ("request-" + token + ".json"), dict(request))
        response.unlink()
        return {**receipt, "replayed": False}

    def retain(self, *, name: str, operation: Callable[[], Any],
               _admitted_execution: Any = None) -> threading.Thread:
        """Admit a child before starting it; close retains its full lifetime."""
        if self._dispatch_held:
            raise ExecutionAdmissionHeld("dispatch is held during inert startup")
        def run() -> None:
            try:
                operation()
            except Exception as exc:
                self.failures[name] = {"code": type(exc).__name__, "message": str(exc)}
            finally:
                with self._lock:
                    self._children.discard(threading.current_thread())
        with self._lock:
            if not self._threads:
                raise RuntimeError("execution host must be started before admitting a child")
            admitted = False
            if _admitted_execution is not None:
                # This is a continuation of a job admitted before drain, not
                # another capacity admission. Caller context and exact object
                # custody must both match; native input cannot mint this tuple.
                owner, job = _admitted_execution
                admitted = (owner is self and self.current_bounded() is self
                    and _ACTIVE_EXECUTION.get() is _admitted_execution
                    and self._executions.get(job["scope"]["schedule_id"]) is job
                    and job["running"] is True)
                if not admitted:
                    raise PermissionError("transport has no exact admitted execution custody")
            if self._closing and not admitted:
                raise RuntimeError("execution host is draining; no new child may be admitted")
            thread = threading.Thread(target=run, name=name, daemon=False)
            self._children.add(thread)
            thread.start()
            return thread

    def close(self) -> None:
        """Keep commands/status available while retained children settle."""
        self.begin_drain()
        while True:
            with self._lock:
                children = tuple(self._children)
            if not children:
                break
            for thread in children:
                thread.join()
        with self._lock:
            self._commands_stop.set()
        # A synchronous command may already own a worker; joining the command
        # thread retains it without a healthy-work duration cap.
        if self._threads:
            self._threads[0].join()
        if self._socket is not None:
            self._threads[-1].join()
        self._stop.set()
        for thread in self._threads[1:]:
            thread.join()
        if self._socket is not None:
            self._socket.close()
            self.socket_path.unlink(missing_ok=True)
        if self._owns_owner_file and self.owner_path.exists():
            value = json.loads(self.owner_path.read_text())
            if value.get("pid") == os.getpid():
                self.owner_path.unlink()
                self._owns_owner_file = False

    def prepare_root_direction_adoption(self) -> Mapping[str, Any]:
        """Existing owner-lane boundary for a root-only direction/BASE change.

        Preserve every retained native job/UNKNOWN fence. The quiescent update
        closes future admission so runtime joins can be normally requalified.
        """
        with self._lock:
            if self._executions or self._capacity_holds or self._external_waiting:
                return {'outcome': 'held', 'reason': 'retained native obligations must settle before root direction adoption',
                        'retry': False, 'runtime_requalification_required': True}
            self._closing = True
        return {'outcome': 'quiescent', 'provider_called': False}

    def begin_drain(self) -> Mapping[str, Any]:
        """Stop admission without joining the command that requests the drain.

        The owning service calls close after its loop observes draining. This
        leaves admitted work and status on their original serialized lane.
        """
        with self._lock:
            self._closing = True
        return {"outcome": "draining", "provider_called": False, "retry": False}

    @property
    def draining(self) -> bool:
        return self._closing

    def wait_until_stopped(self, stop_requested: Callable[[], bool], *, poll_seconds: float = 0.2, idle_poll: Callable[[], Any] | None = None) -> None:
        """Existing service-loop seam for an explicit marker or command drain.

        The owner then closes this host and its Store in its normal finally
        block. No marker is removed, no occurrence is reactivated, and no new
        service is launched here.
        """
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise ValueError("poll_seconds must be finite positive seconds")
        while not self.draining and not stop_requested():
            if idle_poll is not None:
                idle_poll()  # finite IPC publication only; canonical work stays on the owner lane
            self._commands_stop.wait(poll_seconds)
        self.begin_drain()

    @staticmethod
    def supervise(*, argv: list[str], receipt_path: str | Path,
                  source_identity: Mapping[str, Any], reconcile: Callable[[Any], Mapping[str, Any]],
                  disposition: Callable[[], str], request_stop: Callable[[Any], None],
                  max_restarts: int = 2, restart_delay: float = 0.25,
                  max_restart_delay: float = 5.0,
                  process_factory: Callable[..., Any] = subprocess.Popen,
                  resume: bool = False) -> Mapping[str, Any]:
        """Bounded recovery of this owner service process, never its provider.

        Trusted host composition supplies current source/runtime identity,
        exact-effect reconciliation and graceful stop transport. Reconciliation
        must explicitly return ready before EVERY spawn. Pending/unknown effects
        hold; process exits do not prove absence of a provider effect. Stop and
        pause are checked before admission, during service life and backoff.
        Each exit is an immutable receipt; reusing its path cannot reset limits.
        """
        if not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise ValueError("argv must contain an explicit installed command")
        if isinstance(max_restarts, bool) or not isinstance(max_restarts, int) or max_restarts < 0:
            raise ValueError("max_restarts must be a nonnegative integer")
        for delay in (restart_delay, max_restart_delay):
            if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay <= 0:
                raise ValueError("restart delays must be finite positive seconds")
        if max_restart_delay < restart_delay:
            raise ValueError("max_restart_delay must bound restart_delay")
        if type(resume) is not bool:
            raise ValueError("resume must be boolean")
        identity = json_value(source_identity)
        if not isinstance(identity, dict) or not identity:
            raise ValueError("source/runtime identity is required")
        path = Path(receipt_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        from otto.hostctl.supervision import require_unsuperseded_preparation, claim_supervision_launch
        require_unsuperseded_preparation(path)
        policy = {"argv": argv, "source_identity": identity,
                  "max_restarts": max_restarts, "restart_delay": restart_delay,
                  "max_restart_delay": max_restart_delay}
        policy_sha256 = hashlib.sha256(json.dumps(
            policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest()
        if path.exists():
            if not resume:
                # Preserve the original no-implicit-retry fence.  A caller
                # must opt into the explicit retained supervision operation.
                raise FileExistsError(str(path))
            try:
                retained_policy = json.loads(path.read_text())
            except (OSError, ValueError, TypeError) as exc:
                raise RuntimeError("supervision policy receipt is unreadable") from exc
            if (not isinstance(retained_policy, Mapping)
                    or retained_policy.get("schema") not in {
                        "otto.owner-host-supervision.v1", "otto.owner-host-supervision.v2"}
                    or (retained_policy.get("schema") == "otto.owner-host-supervision.v2"
                        and retained_policy.get("policy_sha256") != policy_sha256)
                    or any(retained_policy.get(key) != value for key, value in policy.items())):
                raise ValueError("retained supervision policy differs; restart allowance is not transferable")
        else:
            # Reserve this supervision identity before any launch; even an
            # unknown launch/wait cannot be retried with fresh counters.
            with path.open("x") as stream:
                json.dump({"schema": "otto.owner-host-supervision.v2", **policy,
                           "policy_sha256": policy_sha256}, stream, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
        exits = []
        if resume:
            for candidate in sorted(path.parent.glob(path.name + ".exit-*.json")):
                try:
                    receipt = json.loads(candidate.read_text())
                except (OSError, ValueError, TypeError) as exc:
                    raise RuntimeError("supervision exit receipt is unreadable") from exc
                if (not isinstance(receipt, Mapping)
                        or receipt.get("schema") not in {
                            "otto.owner-host-exit.v1", "otto.owner-host-exit.v2"}
                        or (receipt.get("schema") == "otto.owner-host-exit.v2"
                            and receipt.get("policy_sha256") != policy_sha256)
                        or (receipt.get("schema") == "otto.owner-host-exit.v1"
                            and receipt.get("source_identity") != identity)):
                    raise ValueError("retained supervision exit does not match its policy")
                exits.append(dict(receipt))
            exits.sort(key=lambda item: item.get("index", -1))
            if any(item.get("index") != index for index, item in enumerate(exits)):
                raise ValueError("retained supervision exits are not contiguous")
            if exits and exits[-1].get("exit_status") is None:
                return {"outcome": "unknown", "exit_receipts": exits,
                        "supervision_path": str(path), "supervision_policy_sha256": policy_sha256,
                        "provider_replayed": False, "resumed": True,
                        "restart_allowance": {"max_restarts": max_restarts,
                            "consumed": max(0, len(exits) - 1), "remaining": max(0, max_restarts - len(exits) + 1)},
                        "retry": False}
            if exits and exits[-1].get("exit_status") == 0:
                return {"outcome": "closed", "exit_receipts": exits,
                        "supervision_path": str(path), "supervision_policy_sha256": policy_sha256,
                        "provider_replayed": False, "resumed": True,
                        "restart_allowance": {"max_restarts": max_restarts,
                            "consumed": max(0, len(exits) - 1), "remaining": max(0, max_restarts - len(exits) + 1)}}
            if len(exits) > max_restarts:
                return {"outcome": "restart_exhausted", "exit_receipts": exits,
                        "supervision_path": str(path), "supervision_policy_sha256": policy_sha256,
                        "provider_replayed": False, "resumed": True, "retry": False,
                        "restart_allowance": {"max_restarts": max_restarts,
                            "consumed": max_restarts, "remaining": 0}}
        delay = min(restart_delay * (2 ** max(0, len(exits) - 1)), max_restart_delay)

        def save_exit(receipt: Mapping[str, Any]) -> None:
            target = path.with_name(path.name + f".exit-{receipt['index']}.json")
            # Immutable observation, not a replaceable status locator.
            with target.open("x") as stream:
                json.dump(receipt, stream, sort_keys=True)
                stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
            exits.append(receipt)

        def state() -> str:
            value = disposition()
            if value not in {"active", "stopped", "paused"}:
                raise ValueError("host disposition must be active, stopped or paused")
            return value

        def outcome(value: str, **fields: Any) -> Mapping[str, Any]:
            return {"outcome": value, "exit_receipts": exits, "supervision_path": str(path),
                    "supervision_policy_sha256": policy_sha256, "provider_replayed": False,
                    "resumed": resume,
                    "restart_allowance": {"max_restarts": max_restarts,
                        "consumed": min(max_restarts, max(0, len(exits) - 1)),
                        "remaining": max(0, max_restarts - max(0, len(exits) - 1))}, **fields}

        start_index = len(exits)
        for index in range(start_index, max_restarts + 1):
            current = state()
            if current != "active":
                return outcome(current)
            refusal_path = path.with_name(path.name + f".reconcile-refusal-{index}.json")
            if refusal_path.exists():
                # A prelaunch failure cannot become an unbounded launchd retry
                # with no child exits charged. Retain its original policy/index.
                import stat
                try:
                    fd = os.open(refusal_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as stream:
                        info = os.fstat(stream.fileno()); raw = stream.read(32769)
                    refusal = json.loads(raw)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or stat.S_IMODE(info.st_mode) != 0o600 or len(raw) > 32768
                            or not isinstance(refusal, Mapping)
                            or refusal.get("schema") != "otto.owner-reconciliation-refusal.v1"
                            or refusal.get("policy_sha256") != policy_sha256
                            or refusal.get("index") != index
                            or refusal.get("source_identity") != identity):
                        raise ValueError("retained reconciliation refusal differs")
                except (OSError, ValueError, TypeError) as error:
                    return outcome("unknown", retry=False, reason="unverified retained reconciliation refusal",
                                   error={"code": type(error).__name__})
                return outcome("held", retry=False, reconciliation=refusal)
            try:
                decision = json_value(reconcile(exits[-1] if exits else None))
            except Exception as error:
                refusal = {"schema": "otto.owner-reconciliation-refusal.v1",
                    "policy_sha256": policy_sha256, "index": index, "source_identity": identity,
                    "ready": False, "provider_replayed": False,
                    "error": {"code": type(error).__name__, "message": str(error)[:4096]}}
                raw = (json.dumps(refusal, sort_keys=True) + "\n").encode()
                fd = os.open(refusal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                return outcome("held", retry=False, reconciliation=refusal)
            if not isinstance(decision, Mapping) or decision.get("ready") is not True:
                return outcome("held", reconciliation=decision)
            current = state()
            if current != "active":
                return outcome(current)
            if not claim_supervision_launch(path,index=index,policy_sha256=policy_sha256):
                return outcome('unknown',retry=False,reason='retained launch claim lacks a terminal exit; reconcile original custody')
            started_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            try:
                process = process_factory(argv, stdin=subprocess.DEVNULL)
                stopped = False
                while True:
                    current = state()
                    if current != "active" and not stopped:
                        request_stop(process)  # Supported drain, never kill.
                        stopped = True
                    try:
                        code = process.wait(timeout=0.05)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except Exception as exc:
                receipt = {"schema": "otto.owner-host-exit.v2", "policy_sha256": policy_sha256,
                    "index": index,
                    "started_at": started_at, "ended_at": datetime.now(timezone.utc).isoformat(),
                    "duration_seconds": time.monotonic() - started, "exit_status": None,
                    "source_identity": identity, "reconciliation": decision,
                    "error": {"code": type(exc).__name__, "message": str(exc)}}
                save_exit(receipt)
                return outcome("unknown", retry=False)
            receipt = {"schema": "otto.owner-host-exit.v2", "policy_sha256": policy_sha256,
                "index": index,
                "pid": process.pid, "started_at": started_at,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": time.monotonic() - started, "exit_status": code,
                "source_identity": identity, "reconciliation": decision}
            save_exit(receipt)
            current = state()
            if current != "active":
                return outcome(current)
            if code == 0:
                return outcome("closed")
            if index == max_restarts:
                return outcome("restart_exhausted", retry=False)
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                current = state()
                if current != "active":
                    return outcome(current)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, max_restart_delay)
        raise AssertionError("bounded host loop did not return")

    def __enter__(self) -> "ExecutionHost":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @staticmethod
    def supervise_owner_service(*, argv: list[str], cwd: str | Path,
                                stdin_fifo: str | Path, log_path: str | Path,
                                receipt_path: str | Path, source_identity: Mapping[str, Any],
                                reconcile: Callable[[Any], Mapping[str, Any]],
                                disposition: Callable[[], str], request_stop: Callable[[Any], None],
                                max_restarts: int = 2, restart_delay: float = 0.25,
                                max_restart_delay: float = 5.0,
                                on_spawn: Callable[[Any], None] | None = None,
                                resume: bool = False) -> Mapping[str, Any]:
        """Compose bounded supervision with an independently owned stdin FIFO.

        Trusted host composition supplies paths and effect reconciliation. The
        FIFO remains live across tool/terminal lifetimes; it is neither caller
        IPC nor another durable queue. This adds no admission or restart policy
        beyond supervise, and never removes an explicit stop/pause marker.
        """
        import stat
        fifo, log = Path(stdin_fifo), Path(log_path)
        metadata = fifo.lstat()
        if (not stat.S_ISFIFO(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise PermissionError("owner stdin requires an independently owned mode0600 FIFO")

        def spawn(command: list[str], **_ignored: Any) -> Any:
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(fifo, flags)
            output = None
            try:
                held = os.fstat(fd)
                if (held.st_dev, held.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise PermissionError("owner stdin FIFO changed before spawn")
                output = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
                info = os.fstat(output)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                    raise PermissionError("owner log requires a mode0600 owned regular file")
                process = subprocess.Popen(command, cwd=cwd, stdin=fd, stdout=output,
                    stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
                if on_spawn is not None:
                    try:
                        on_spawn(process)  # Trusted host receipt, never caller routing.
                    except BaseException:
                        request_stop(process)
                        process.wait()  # Drain the launched owner; never orphan/retry it.
                        raise
                return process
            finally:
                os.close(fd)
                if output is not None: os.close(output)

        return ExecutionHost.supervise(argv=argv, receipt_path=receipt_path,
            source_identity=source_identity, reconcile=reconcile, disposition=disposition,
            request_stop=request_stop, max_restarts=max_restarts, restart_delay=restart_delay,
            max_restart_delay=max_restart_delay, process_factory=spawn, resume=resume)

    @staticmethod
    def reconcile_trigger(*, attention: Any, executor: Any, schedule_id: str,
                          request_id: str, actor: str, desired_state: str = "active",
                          expected_version: int | None = None, project_ref: str | None = None,
                          manager_ref: str | None = None, generation: int | None = None,
                          owner_transition: str | None = None,
                          completion: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Use the existing owner host-effect and automation executor seam.

        An effect already persisted under this request is reconciled by host
        readback after restart. It is never automatically mutated a second time.
        Provisioning an actual automation and its configuration belongs to the
        host; this method neither invents a timer nor equates an awaited check
        with unattended execution.
        """
        from otto.host_bridge import HostEffect
        if owner_transition not in {None, "stop", "complete"}:
            raise ValueError("owner_transition must be stop or complete")
        if expected_version is not None and (isinstance(expected_version, bool)
                or not isinstance(expected_version, int) or expected_version < 1):
            raise ValueError("expected_version must be a positive integer")
        if generation is not None and (isinstance(generation, bool)
                or not isinstance(generation, int) or generation < 1):
            raise ValueError("generation must be a positive integer")
        record = attention._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule"}, "automatic_action": False}
        scope = {"project_ref": project_ref if project_ref is not None else record.project_ref,
                 "manager_ref": manager_ref if manager_ref is not None else record.manager_ref,
                 "generation": generation if generation is not None else record.generation,
                 "lifecycle_owner": actor}
        owner_result = None
        expected = record.version if expected_version is None else expected_version
        if owner_transition == "stop":
            owner_result = attention.stop(schedule_id, request_id=request_id,
                expected_version=expected, **scope)
        elif owner_transition == "complete":
            values = dict(completion or {})
            if set(values) - {"receipt", "outcome", "completion_evidence", "completed_at"}:
                raise ValueError("completion must contain only receipt/outcome/evidence/time")
            owner_result = attention.complete(schedule_id, request_id, expected_version=expected,
                                               **scope, **values)
        if owner_result is not None:
            fresh = attention._read(schedule_id)
            # Unknown/failed completion never becomes an external lifecycle
            # success. Recurring successful completion keeps its cadence.
            if (owner_result.get("outcome") not in {"stopped", "returned", "replayed"}
                    or fresh.stop_state not in {"stopped", "completed"}):
                return {**owner_result, "external_host_suspended": False,
                        "host_operation_called": False, "owner_transition": owner_result}
            record = fresh
            request_id = "host-" + owner_transition + ":" + request_id
            desired_state = "paused"
            expected = record.version
        if desired_state == "active" and record.stop_state != "active":
            return {"outcome": "rejected", "error": {"code": "schedule_stopped" if record.stop_state == "stopped" else "schedule_terminal"},
                    "external_host_suspended": False, "automatic_action": False}
        prepared = attention.prepare_host(schedule_id, request_id=request_id,
            expected_version=expected, desired_state=desired_state, actor=actor,
            project_ref=scope["project_ref"], manager_ref=scope["manager_ref"], generation=scope["generation"])
        if prepared.get("effect") is None:
            return {**prepared, "owner_transition": owner_result, "external_host_suspended": False}
        effect = HostEffect.from_dict(prepared["effect"])
        result = executor.recover(effect) if prepared.get("replayed") else executor.execute(effect)
        acknowledgement = result.get("acknowledgement") or {}
        outcome = result.get("outcome")
        if outcome == "reconciled" and acknowledgement.get("outcome") != "reconciled":
            outcome = "pending_owner"
        return {"schedule_id": schedule_id, "prepared": prepared, "host": result,
                "owner_transition": owner_result, "outcome": outcome,
                "external_host_suspended": (desired_state == "paused" and outcome == "reconciled"
                    and acknowledgement.get("readback_exact") is True),
                "observed_scheduled_callback": False, "automatic_action": outcome == "reconciled"}
