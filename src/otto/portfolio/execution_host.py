"""Host custody for the maintained file command transport and admitted children.

Owner command implementations supply a handler. Request files are retained
until an atomic response exists, so a restarted host can recover the same
logical request through canonical operations. A parent finishing drains its
admitted children while their command/status surface remains available.
"""
from __future__ import annotations

import json
import os
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
        self._command_lock = threading.Lock()
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

    def _dispatch(self, request: Mapping[str, Any]) -> Any:
        try:
            if request.get("command") == "status":
                return self.handler(request)
            with self._command_lock:
                return self.handler(request)
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

    def _serve(self, status: bool) -> None:
        stop = self._stop if status else self._commands_stop
        while not stop.is_set():
            for path in sorted(self.directory.glob("request-*.json")):
                token = path.name[len("request-"):-len(".json")]
                if not token or any(char not in "0123456789abcdef" for char in token):
                    continue
                response = self.directory / ("response-" + token + ".json")
                try:
                    request = json.loads(path.read_text())
                    if (request.get("command") == "status") != status:
                        continue
                    if not response.exists():
                        result = self._dispatch(request)
                        _atomic_json(response, result)
                    path.unlink(missing_ok=True)
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    self.failures[token] = {"code": type(exc).__name__, "message": str(exc)}
            stop.wait(0.05)

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
                          request_id: str, actor: str, desired_state: str = "active") -> dict[str, Any]:
        """Use the existing owner host-effect and automation executor seam.

        An effect already persisted under this request is reconciled by host
        readback after restart. It is never automatically mutated a second time.
        Provisioning an actual automation and its configuration belongs to the
        host; this method neither invents a timer nor equates an awaited check
        with unattended execution.
        """
        from otto.host_bridge import HostEffect
        prepared = attention.prepare_host(schedule_id, request_id=request_id,
                                          desired_state=desired_state, actor=actor)
        if prepared.get("effect") is None:
            return prepared
        effect = HostEffect.from_dict(prepared["effect"])
        result = executor.recover(effect) if prepared.get("replayed") else executor.execute(effect)
        acknowledgement = result.get("acknowledgement") or {}
        outcome = result.get("outcome")
        if outcome == "reconciled" and acknowledgement.get("outcome") != "reconciled":
            outcome = "pending_owner"
        return {"schedule_id": schedule_id, "prepared": prepared, "host": result,
                "outcome": outcome, "automatic_action": outcome == "reconciled"}
