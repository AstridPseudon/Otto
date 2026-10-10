"""Authenticate a live native tool process, not its JSON identity claims.

The owner registers actual Popen objects at an authorized native RESUME. A
Unix socket's kernel peer PID must descend from one still-live registered
process, with unchanged birth identity. This is an ephemeral process capability,
not a caller/history registry. Reopening an owner requires a new genuine native
launch; retained canonical session evidence alone cannot authenticate a peer.
"""
from __future__ import annotations

import ctypes
import hashlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import sys
import threading
from typing import Any


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent: int
    birth: tuple[int, ...]
    uid: int


def process_identity(pid: int) -> ProcessIdentity:
    if type(pid) is not int or pid <= 0:
        raise PermissionError("invalid kernel process identity")
    if sys.platform == "darwin":
        # Public proc_pidinfo/PROC_PIDTBSDINFO from the macOS SDK proc_info.h.
        class BSDInfo(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint32) for name in
                ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid",
                 "ruid", "rgid", "svuid", "svgid", "reserved")]
            _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
            _fields_ += [(name, ctypes.c_uint32) for name in
                ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
            _fields_ += [("nice", ctypes.c_int32), ("seconds", ctypes.c_uint64),
                        ("micros", ctypes.c_uint64)]
        info = BSDInfo()
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                         ctypes.c_void_p, ctypes.c_int]
        size = library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info) or info.pid != pid or info.status == 5 or info.flags & 4:
            raise PermissionError("kernel process is absent or exiting")
        return ProcessIdentity(pid, info.ppid, (info.seconds, info.micros), info.uid)
    if sys.platform.startswith("linux"):
        path = Path("/proc") / str(pid)
        raw = (path / "stat").read_text()
        fields = raw[raw.rindex(")") + 2:].split()
        if fields[0] in {"Z", "X"}:
            raise PermissionError("kernel process is exiting")
        return ProcessIdentity(pid, int(fields[1]), (int(fields[19]),), path.stat().st_uid)
    raise PermissionError("kernel peer process authentication is unsupported on this host")


def socket_peer_pid(connection: socket.socket) -> int:
    if not isinstance(connection, socket.socket) or connection.family != socket.AF_UNIX:
        raise PermissionError("caller authentication requires an accepted Unix socket")
    if sys.platform == "darwin":
        # Bind the connection's audit token to the still-live process version;
        # a recycled peer PID must not be joined to a later native descendant.
        # sys/un.h LOCAL_PEERTOKEN and libproc.h proc_pidpath_audittoken.
        class AuditToken(ctypes.Structure):
            _fields_ = [("values", ctypes.c_uint32 * 8)]
        token = AuditToken.from_buffer_copy(connection.getsockopt(0, 6, 32))
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidpath_audittoken.argtypes = [ctypes.POINTER(AuditToken), ctypes.c_void_p, ctypes.c_uint32]
        path = ctypes.create_string_buffer(4096)
        if library.proc_pidpath_audittoken(ctypes.byref(token), path, len(path)) <= 0:
            raise PermissionError("socket peer audit process version is no longer live")
        audit = ctypes.CDLL("/usr/lib/libbsm.dylib")
        audit.audit_token_to_pid.argtypes = [AuditToken]
        return audit.audit_token_to_pid(token)
    if sys.platform.startswith("linux"):
        import struct
        return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
    raise PermissionError("kernel socket peer identity is unsupported on this host")


class NativeProcessCallerIngress:
    def __init__(self, binding_factory: Any, *, peer_reader=socket_peer_pid,
                 process_reader=process_identity) -> None:
        if not callable(binding_factory):
            raise TypeError("owner binding factory must be callable")
        self.binding_factory = binding_factory
        self.peer_reader, self.process_reader = peer_reader, process_reader
        self._live: dict[int, tuple[Any, ProcessIdentity, Any]] = {}
        self._lock = threading.RLock()

    def observe(self, process: Any, authorization: Any) -> Any:
        """Host-only Popen callback. Returns cleanup for this exact lifetime."""
        if (not isinstance(authorization, dict) or authorization.get("status") != "authorized"
                or not authorization.get("physical_session_id")):
            raise PermissionError("only an owner-authorized native work launch can bind a caller")
        identity = self.process_reader(process.pid)
        if identity.parent != os.getpid() or process.poll() is not None:
            raise PermissionError("native process was not created by this live owner")
        retained = json.loads(json.dumps(authorization, allow_nan=False))
        # Called on the serialized owner via ExecutionHost.owner_callback.
        # Capture the exact occurrence now; a later pending callback pointer
        # must not change the original caller's admission identity.
        from .identity_context import HostCallerBinding
        binding = self.binding_factory(retained)
        if not isinstance(binding, HostCallerBinding):
            raise PermissionError("owner launch factory did not return a canonical caller binding")
        with self._lock:
            if process.pid in self._live:
                raise PermissionError("native process already has a caller binding")
            self._live[process.pid] = (process, identity, binding)

        def release():
            with self._lock:
                current = self._live.get(process.pid)
                if current is not None and current[0] is process:
                    self._live.pop(process.pid)
        return release

    def live_occurrence(self, schedule_id: str) -> bool:
        """Owner custody read; settlement alone does not release native capacity."""
        with self._lock:
            return any(binding.schedule_id == schedule_id and process.poll() is None
                       for process, identity, binding in self._live.values())

    def __call__(self, ingress: Any) -> Any:
        if getattr(ingress, "transport", None) != "unix-socket":
            raise PermissionError("durable file IPC does not authenticate a native caller")
        peer = self.process_reader(self.peer_reader(ingress.handle))
        with self._lock:
            registered = set(self._live)
        chain, current = [], peer
        for _ in range(64):
            if any(item.pid == current.pid for item in chain):
                raise PermissionError("kernel caller ancestry has a cycle")
            chain.append(current)
            # Stop at the first registered native process (its parent is this
            # owner, checked at registration) or at the owner itself. Ancestors
            # above the owner are never consulted: under a terminal they include
            # root-owned processes (login) whose identity cannot be read.
            if current.pid in registered or current.pid == os.getpid() or current.parent <= 1:
                break
            current = self.process_reader(current.parent)
        else:
            raise PermissionError("kernel caller ancestry exceeds bounded inspection")
        with self._lock:
            matches = [value for value in self._live.values()
                       if value[1] in chain and value[0].poll() is None]
            if len(matches) != 1:
                raise PermissionError("socket peer has no unique live owner-created native custody")
            process, root, binding = matches[0]
            # Re-read the entire ancestry, including birth and parent pins.
            if any(self.process_reader(item.pid) != item for item in chain):
                raise PermissionError("caller process ancestry changed during authentication")
            if self.process_reader(root.pid) != root or process.poll() is not None:
                raise PermissionError("native caller custody ended during authentication")
            return binding


def managed_caller_binding(server: Any, authorization: dict[str, Any]) -> Any:
    """Join the captured launch authorization to exact current managed slots."""
    from herzchen.contracts import ResourceRef
    from .identity_context import HostCallerBinding
    state = server.state
    schedules = {state.get("schedule_id"), (state.get("manager_continuation") or {}).get("schedule_id")}
    # Explicit report continuations may be executing before the host locator
    # is refreshed. Their ordinary deterministic identity is a bounded exact
    # lookup; never substitute a locator or scan unrelated Due payloads.
    from .execution_operations import manager_continuation_schedule_id
    schedules.add(manager_continuation_schedule_id(authorization["assignment_ref"],
        authorization["logical_request_key"]))
    # The automatic result callback can be authorized before its host locator
    # is updated, just like an explicit report callback. Its canonical key
    # derives one exact Due; captured authorization must still match below.
    if authorization["logical_request_key"].startswith("worker-result:"):
        from .execution_operations import manager_worker_result_schedule_id
        schedules.add(manager_worker_result_schedule_id(authorization["logical_request_key"]))
    schedules.update(value.get("schedule_id") for value in state.get("workers", {}).values())
    # Child/parent continuations are deterministic owner Due identities. The
    # original authorization supplies the exact key; no history enumeration.
    from .occurrence_reads import worker_schedule
    schedules.add(worker_schedule(authorization["project_ref"],
        authorization["logical_request_key"].removesuffix(":launch")))
    if authorization["logical_request_key"].startswith("parent-result:"):
        schedules.add("parent-consume-" + hashlib.sha256(authorization["logical_request_key"].encode()).hexdigest()[:28])
    matches = []
    for schedule in sorted(value for value in schedules if isinstance(value, str)):
        due = server.due_port.read_due(schedule)
        if not isinstance(due, dict): continue
        attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
        if attempt.get("delivery_authorization") == authorization:
            matches.append(due)
    if len(matches) != 1:
        raise PermissionError("native launch has no unique exact managed occurrence")
    due = matches[0]
    target = due.get("target") or {}
    return HostCallerBinding(server.binding.authenticated_actor(authorization["principal"]),
        ResourceRef.from_dict(authorization["assignment_ref"]), authorization["generation"],
        target.get("native_adapter"), authorization["physical_session_id"], due["schedule_id"])
