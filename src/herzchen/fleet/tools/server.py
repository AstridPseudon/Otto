"""A unix-socket server that serves a ToolFacade, one JSON request per connection, plus the client helper that speaks to it."""

from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import threading

from .facade import ToolFacade

__all__ = ["FacadeServer", "request"]

MAX_LINE = 1024 * 1024
_SOCKET_PATH_LIMIT = 100
_CONNECTION_TIMEOUT = 10.0
_SOCKET_MODE = 0o600

_INTERNAL_REPLY = (
    json.dumps({"ok": False, "error": "owner_unavailable", "detail": "internal"}, sort_keys=True) + "\n"
).encode("utf-8")


def _refusal(code: str, detail: str) -> dict:
    return {"ok": False, "error": code, "detail": detail}


def _route(facade: ToolFacade, raw: bytes) -> dict:
    """Answer one request line. Caller mistakes return refusals; the token is never echoed."""

    if len(raw) > MAX_LINE:
        return _refusal("bad_request", "request exceeds 1 MiB")
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return _refusal("bad_request", "request is not JSON")
    if not isinstance(message, dict):
        return _refusal("bad_request", "request must be a JSON object")
    op = message.get("op")
    token = message.get("token")
    if op == "list":
        listed = facade.listing(token)
        if isinstance(listed, dict):
            return listed
        return {"ok": True, "tools": listed}
    if op == "call":
        return facade.call(token, message.get("tool"), message.get("args"))
    return _refusal("bad_request", "unknown op")


def _answer(facade: ToolFacade, raw: bytes) -> bytes:
    """The encoded reply line for one request. Any internal failure becomes the generic owner refusal."""

    try:
        reply = _route(facade, raw)
        return (json.dumps(reply, sort_keys=True) + "\n").encode("utf-8")
    except Exception:
        return _INTERNAL_REPLY


class _Handler(socketserver.StreamRequestHandler):
    timeout = _CONNECTION_TIMEOUT

    def handle(self) -> None:
        try:
            raw = self.rfile.readline(MAX_LINE + 1)
            self.wfile.write(_answer(self.server.facade, raw))
            self.wfile.flush()
        except Exception:
            return


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, facade: ToolFacade) -> None:
        self.facade = facade
        super().__init__(path, _Handler)


def _socket_is_live(path: str) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1.0)
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _clear_stale_socket(path: str) -> None:
    """Refuse a path that holds anything but a dead socket file; unlink a dead socket file."""

    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(status.st_mode):
        raise FileExistsError("socket path exists and is not a socket")
    if _socket_is_live(path):
        raise FileExistsError("socket path is in use by a live server")
    os.unlink(path)


class FacadeServer:
    """Serves a ToolFacade on a unix stream socket in a daemon thread. Usable as a context manager."""

    def __init__(self, facade: ToolFacade, socket_path: str) -> None:
        self._facade = facade
        self._path = os.fspath(socket_path)
        self._server: _UnixServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("server already started")
        if len(os.fsencode(self._path)) > _SOCKET_PATH_LIMIT:
            raise ValueError("socket path is longer than 100 bytes")
        _clear_stale_socket(self._path)
        previous = os.umask(0o177)
        try:
            server = _UnixServer(self._path, self._facade)
        finally:
            os.umask(previous)
        os.chmod(self._path, _SOCKET_MODE)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="facade-server",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        if thread is not None:
            server.shutdown()
        server.server_close()
        try:
            if stat.S_ISSOCK(os.lstat(self._path).st_mode):
                os.unlink(self._path)
        except FileNotFoundError:
            pass

    def __enter__(self) -> FacadeServer:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def request(socket_path: str, payload: dict, timeout: float = 30.0) -> dict:
    """Send one request line to a FacadeServer and return its one reply line. Transport failures are refusals."""

    line = (json.dumps(payload) + "\n").encode("utf-8")
    unavailable = {"ok": False, "error": "owner_unavailable", "detail": "socket"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(line)
            buffer = bytearray()
            while b"\n" not in buffer and len(buffer) <= MAX_LINE:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
    except OSError:
        return unavailable
    reply_line = bytes(buffer).split(b"\n", 1)[0]
    try:
        reply = json.loads(reply_line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return unavailable
    if not isinstance(reply, dict):
        return unavailable
    return reply
