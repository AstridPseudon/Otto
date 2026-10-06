"""Host custody for the maintained file command transport and admitted children.

Owner command implementations supply a handler. Request files are retained
until an atomic response exists, so a restarted host can recover the same
logical request through canonical operations. A parent finishing drains its
admitted children while their command/status surface remains available.
"""
from __future__ import annotations

import json
import hashlib
import os
import queue
from pathlib import Path
import socket
import threading
from typing import Any, Callable, Mapping

from .owner_readers import json_value


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(json_value(value), stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_DISPATCH_CONTEXT = threading.local()
_REENTRANT_COMMANDS = frozenset({"task-state", "report", "completion-gate", "complete-task",
                                 "manager-assessment", "manager-assessment-pool",
                                 "run-worker", "worker-status", "start-retained-worker",
                                 "review-task", "finish-task", "finish-project",
                                 "review-input",
                                 "request-help", "request-advice", "read-help", "respond-help", "resolve-help",
                                 "start-retained-help",
                                 "project-lifecycle-read", "commit",
                                 "advisor-decision-state"})


def _nested_capability(request: Mapping[str, Any]) -> str:
    """Classify nested file operations without releasing owner custody."""
    # Setup inspection is finite and inert; prepare/activate stay held during
    # the admitted native wait and cannot acquire another execution effect.
    if (request.get("command") == "operating-setup"
            and request.get("operation", "read") == "read"
            and not set(request) - {"command", "operation"}):
        return "admitted"
    if request.get("command") in _REENTRANT_COMMANDS:
        return "admitted"
    if (request.get("command") == "manager-continue" and request.get("operation") == "dispatch"
            or request.get("command") in {"manager-worker-result", "manager-task-settlement", "manager-help-result"}):
        return "retained"  # Another native manager turn cannot overlap this one.
    return "held"


class ExecutionHost:
    """One owner-process command service, retained to admitted work completion.

    Read-only status uses a separate consumer so a synchronous child cannot
    prevent observation. Mutating commands remain serial. Canonical request
    identities, rather than command-file tokens, fence external effects.
    """

    def __init__(self, *, directory: str | Path, handler: Callable[[Mapping[str, Any]], Any],
                 owner_path: str | Path | None = None,
                 socket_path: str | Path | None = None) -> None:
        self.directory = Path(directory)
        self.handler = handler
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
        self._owns_owner_file = False
        self._threads: list[threading.Thread] = []
        self.failures: dict[str, dict[str, str]] = {}

    def start(self) -> None:
        if self._threads:
            raise RuntimeError("execution host is already started")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.owner_path is not None:
            # Exclusive custody; a live competing owner is never replaced.
            if self.owner_path.exists():
                prior = json.loads(self.owner_path.read_text())
                try:
                    os.kill(int(prior["pid"]), 0)
                except ProcessLookupError:
                    self.owner_path.unlink()
                    if self.socket_path is not None:
                        self.socket_path.unlink(missing_ok=True)
                else:
                    raise RuntimeError("another execution host owns this command directory")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.owner_path, flags, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"pid": os.getpid()}, stream)
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

    def _status_read(self, request: Mapping[str, Any]) -> Any:
        """Read shared owner ports on the same SQLite custodian as commands.

        Native transport waits pump the existing owner callback queue, so a
        status read remains available without concurrent connection use.
        Finite owner operations finish before status takes the command lane.
        """
        completed, result = threading.Event(), {}
        while True:
            with self._lock:
                if self._external_waiting:
                    self._owner_calls.put((lambda: self.handler(request), completed, result))
                    break
            # Do not block across a race into a native wait: on the next
            # iteration that owner can receive this read through its pump.
            if self._command_lock.acquire(blocking=False):
                try:
                    return self.handler(request)
                finally:
                    self._command_lock.release()
            completed.wait(0.01)
        completed.wait()
        if "error" in result:
            raise result["error"]
        return result["value"]

    def _dispatch(self, request: Mapping[str, Any]) -> Any:
        try:
            if request.get("command") == "status":
                return self._status_read(request)
            with self._command_lock:
                if self._closing and request.get("command") not in _REENTRANT_COMMANDS:
                    return {"outcome": "held", "reason": "owner host is draining", "provider_called": False}
                previous = getattr(_DISPATCH_CONTEXT, "value", None)
                _DISPATCH_CONTEXT.value = (self, threading.get_ident(),
                    (request.get("command") == "manager-continue" and request.get("operation") == "dispatch")
                    or request.get("command") in {"start-manager", "start-retained-worker", "start-retained-help", "manager-worker-result", "manager-task-settlement", "manager-help-result"})
                try:
                    return self.handler(request)
                finally:
                    _DISPATCH_CONTEXT.value = previous
        except Exception as exc:
            return {"outcome": "error", "error": type(exc).__name__, "message": str(exc),
                    "next_action": "inspect the exact canonical request before retry"}

    def _serve_socket(self) -> None:
        # Optional compatibility for installed callers. File requests remain
        # the durable transport; both surfaces share one mutation custodian.
        while not self._commands_stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(5)
                try:
                    raw = b""
                    while not raw.endswith(b"\n") and len(raw) <= 256 * 1024:
                        part = connection.recv(65536)
                        if not part:
                            break
                        raw += part
                    result = self._dispatch(json.loads(raw))
                    connection.sendall(json.dumps(json_value(result), sort_keys=True).encode())
                except (OSError, ValueError) as exc:
                    self.failures["socket"] = {"code": type(exc).__name__, "message": str(exc)}

    def _serve_files(self, status: bool, *, allowed: frozenset[str] | None = None) -> None:
        for path in sorted(self.directory.glob("request-*.json")):
            token = path.name[len("request-"):-len(".json")]
            if not token or any(char not in "0123456789abcdef" for char in token):
                continue
            response = self.directory / ("response-" + token + ".json")
            acquired = False
            claimed = False
            try:
                request = json.loads(path.read_text())
                command = request.get("command")
                if (command == "status") != status:
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
                        _atomic_json(pending, {"outcome": "pending", "request_id": token,
                            "request_retained": True, "provider_called": False, "effects_started": False,
                            "retry": False, "response_path": str(response),
                            "reason": "another native manager turn owns the command lane",
                            "next_action": "Observe this exact response path after the current turn settles; do not resend the request or rerun tests while waiting."})
                    continue
                if not status:
                    # A compatible socket dispatch may own a native wait. Do
                    # not claim/block its child's file before its pump sees it.
                    acquired = self._command_lock.acquire(blocking=False)
                    if not acquired:
                        continue
                    if self._closing and _nested_capability(request) == "retained":
                        continue
                with self._lock:
                    if token in self._active_files:
                        continue
                    self._active_files.add(token)
                    claimed = True
                if not response.exists():
                    if capability == "held":
                        result = {"outcome": "held", "reason": "operation is not admitted during the current native transport wait",
                                  "command": command, "provider_called": False, "effects_started": False,
                                  "retry": False, "request_retained": False,
                                  "next_action": "Return this held result to the manager; inspect owner status and wait for the current turn to settle before a new explicit intent. Do not resend or rerun tests while waiting."}
                    else:
                        result = self._dispatch(request)
                    if (command in {"manager-worker-result", "manager-help-result"} and result.get("outcome") == "pending"
                            and result.get("provider_called") is False and result.get("effects_started") is False):
                        pending = self.directory / ("pending-" + token + ".json")
                        if not pending.exists():
                            _atomic_json(pending, {**result, "request_id": token, "request_retained": True,
                                "response_path": str(response),
                                "next_action": "The owner retains this observed worker result until the same manager settles; do not resend it."})
                        continue
                    _atomic_json(response, result)
                (self.directory / ("pending-" + token + ".json")).unlink(missing_ok=True)
                path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
            except Exception as exc:
                self.failures[token] = {"code": type(exc).__name__, "message": str(exc)}
            finally:
                if claimed:
                    with self._lock:
                        self._active_files.discard(token)
                if acquired:
                    self._command_lock.release()

    def _serve(self, status: bool) -> None:
        stop = self._stop if status else self._commands_stop
        while not stop.is_set():
            self._serve_files(status)
            stop.wait(0.05)
        if not status:
            # One bounded final snapshot drains queued finite owner commands.
            # Provider-bearing requests remain durable for owner review/restart.
            self._serve_files(False, allowed=_REENTRANT_COMMANDS)

    @staticmethod
    def owner_callback(callback: Callable[..., Any] | None) -> Callable[..., Any] | None:
        """Marshal an admitted transport callback to its serialized owner."""
        context = getattr(_DISPATCH_CONTEXT, "value", None)
        if callback is None or context is None or not context[2]:
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
        while True:
            try:
                operation, completed, result = self._owner_calls.get_nowait()
            except queue.Empty:
                return
            try:
                result["value"] = operation()
            except BaseException as exc:
                result["error"] = exc
            finally:
                completed.set()

    @staticmethod
    def external_call(operation: Callable[[], Any]) -> Any:
        """Yield only an admitted manager's transport wait, never owner custody.

        The owner thread retains its command lock and executes finite nested
        commands and native admission callbacks itself. The transport thread
        cannot read/mutate the owner through an unwrapped callback. Other long
        dispatches remain queued; result capture/settlement resumes on owner.
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
        if "error" in result:
            raise result["error"]
        return result["value"]

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Retain prepared work/result delivery on the existing owner lane.

        Execution and canonical settlement stay on the command custodian, not
        an arbitrary child thread. Restart consumes the same prepared occurrence
        through its canonical attempt fence rather than resending its provider.
        """
        context = getattr(_DISPATCH_CONTEXT, "value", None)
        if context is None or context[0] is not self or context[1] != threading.get_ident():
            raise RuntimeError("worker submission requires its serialized command owner")
        if self._closing:
            raise RuntimeError("execution host is draining; no new worker may be admitted")
        if request.get("command") not in {"start-retained-worker", "start-retained-help", "manager-worker-result", "manager-task-settlement", "manager-help-result"}:
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
        return {"outcome": "admitted", "schedule_id": request["schedule_id"],
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
        if (hashlib.sha256(raw).hexdigest() != expected_response_sha256
                or held != {"outcome": "held", "provider_called": False, "effects_started": False,
                    "retry": False, "reason": "reconcile the retained manager effect before worker-result continuation"}):
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

    def retain(self, *, name: str, operation: Callable[[], Any]) -> threading.Thread:
        """Admit a child before starting it; close retains its full lifetime."""
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
            if self._closing:
                raise RuntimeError("execution host is draining; no new child may be admitted")
            thread = threading.Thread(target=run, name=name, daemon=False)
            self._children.add(thread)
            thread.start()
            return thread

    def close(self) -> None:
        """Keep commands/status available while retained children settle."""
        with self._lock:
            self._closing = True
        while True:
            with self._lock:
                children = tuple(self._children)
            if not children:
                break
            for thread in children:
                thread.join()
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

    def __enter__(self) -> "ExecutionHost":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

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
