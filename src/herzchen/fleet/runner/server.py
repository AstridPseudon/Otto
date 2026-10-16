"""Runner daemon: one JSON object per line over a unix socket, the caller's pid taken from the kernel."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import socketserver
import stat
import struct
import sys
import threading
from typing import Any, Sequence

from ..capacity import CapacityPolicy, CapacityPool
from .runner import Runner
from .store import ResultStore

MAX_REQUEST = 1 << 20


def _peer_pid(sock: socket.socket) -> int | None:
    """The connecting process's pid from the socket's peer credentials; None where the platform gives none."""
    try:
        if sys.platform == "darwin":
            return int(sock.getsockopt(0, 2))  # SOL_LOCAL, LOCAL_PEERPID
        if sys.platform.startswith("linux"):
            raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            return struct.unpack("3i", raw)[0]
    except OSError:
        return None
    return None


def _reply(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(MAX_REQUEST + 1)
        if not line:
            return
        self.wfile.write(_reply(self._answer(line)))

    def _answer(self, line: bytes) -> dict[str, Any]:
        if len(line) > MAX_REQUEST:
            return {"ok": False, "error": "bad_request"}
        try:
            request = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "bad_request"}
        if not isinstance(request, dict):
            return {"ok": False, "error": "bad_request"}
        runner = self.server.runner
        op = request.get("op")
        if op == "submit":
            return runner.submit(request, _peer_pid(self.connection))
        if op == "await":
            timeout = request.get("timeout")
            if not isinstance(request.get("run_id"), str) or (timeout is not None and not _is_number(timeout)):
                return {"ok": False, "error": "bad_request"}
            return runner.await_run(request["run_id"], timeout)
        if op == "status":
            run_id = request.get("run_id")
            if run_id is not None and not isinstance(run_id, str):
                return {"ok": False, "error": "bad_request"}
            return runner.status(run_id)
        if op == "report":
            task = request.get("task")
            if task is not None and not isinstance(task, str):
                return {"ok": False, "error": "bad_request"}
            return runner.report(task)
        return {"ok": False, "error": "unknown_op"}


def _prepare_socket(path: str) -> None:
    """Make the socket's directory private if we create it, and clear a stale socket; refuse a live one."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
        os.chmod(parent, 0o700)
    if not os.path.lexists(path):
        return
    if not stat.S_ISSOCK(os.lstat(path).st_mode):
        raise RuntimeError("socket path is taken by a file that is not a socket")
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1.0)
        probe.connect(path)
    except ConnectionRefusedError:
        os.unlink(path)
        return
    finally:
        probe.close()
    raise RuntimeError("a runner is already serving this socket")


class RunnerServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Serves the runner's submit, await, status and report operations on a unix socket."""

    daemon_threads = True

    def __init__(self, runner: Runner, socket_path: Any) -> None:
        self.runner = runner
        self.socket_path = os.path.abspath(os.fspath(socket_path))
        _prepare_socket(self.socket_path)
        super().__init__(self.socket_path, _Handler)
        os.chmod(self.socket_path, 0o600)

    def server_close(self) -> None:
        super().server_close()
        with contextlib.suppress(OSError):
            os.unlink(self.socket_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="herzchen.fleet.runner")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--capacity", type=int, default=3)
    parser.add_argument("--forbid-root", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    state_dir = os.path.abspath(args.state_dir)
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    pool = CapacityPool(CapacityPolicy(heavy_headroom=args.capacity))
    store = ResultStore(os.path.join(state_dir, "store"), forbidden_roots=args.forbid_root)
    runner = Runner(pool, store, state_dir=state_dir)
    runner.start()
    try:
        server = RunnerServer(runner, args.socket)
    except BaseException:
        runner.stop()
        raise

    def _shutdown(signum: int, frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        runner.stop()
    return 0
