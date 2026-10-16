"""Bounded host-owned exact-session metadata lookup for selected Codex CLI.

Construction is inert. Calls use only initialize and thread/read(includeTurns=false).
No session search, transcript read, provider invocation, or raw observation logging.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any

from herzchen.fleet.custody import Custody

# Independently qualified initialize/thread-read stdio implementations. A new
# version/path alone does not admit a binary; its exact digest must be qualified.
SUPPORTED_CLI_SHA256 = frozenset({
    "788a818fbb9596869c7a487554507cb8bdca17584b8671112b23f9e225ba35c8",  # 0.158.0
    "50ac633af64851511f9bbc71032cdae7f1ba20b3234c189687d61ba846c354c5",  # desktop 0.159.2
    "16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704",  # pinned daemon 0.159.2
    "12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de",  # pinned daemon 0.161.0
})
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_MESSAGES = 64


class HostThreadReadError(ValueError):
    """A sanitized fail-closed metadata lookup failure; never includes a trace path."""


def _fail(code: str) -> None:
    raise HostThreadReadError(code) from None


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail("duplicate_json_key")
        value[key] = item
    return value


def _invalid_constant(value):
    _fail("app_server_decode_error")


def _checked_path(value: str, root: Path) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("native_path_missing_or_malformed")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        _fail("native_path_not_absolute_or_normal")
    try:
        path.relative_to(root)
    except ValueError:
        _fail("native_path_outside_root")
    # Inspect metadata only, including every root/path ancestor; never open trace.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            _fail("symlink_in_native_path")
        if current != path and not stat.S_ISDIR(info.st_mode):
            _fail("native_ancestor_not_directory")
    if not stat.S_ISREG(path.lstat().st_mode):
        _fail("native_path_not_regular")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError:
        _fail("resolved_native_path_outside_root")
    return str(resolved)


class _StdioRPC:
    def __init__(self, process: Any, deadline: float) -> None:
        self.process, self.deadline = process, deadline
        self.buffer = b""
        self.total = self.messages = 0
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)

    def _ready(self, stream: Any, event: int) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            _fail("app_server_timeout")
        with selectors.DefaultSelector() as selector:
            selector.register(stream, event)
            if not selector.select(remaining):
                _fail("app_server_timeout")

    def send(self, value: dict[str, Any]) -> None:
        raw = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        while raw:
            self._ready(self.process.stdin, selectors.EVENT_WRITE)
            try:
                count = os.write(self.process.stdin.fileno(), raw)
            except BlockingIOError:
                continue
            if count <= 0:
                _fail("app_server_stdin_closed")
            raw = raw[count:]

    def response(self, request_id: int) -> dict[str, Any]:
        while True:
            if time.monotonic() >= self.deadline:
                _fail("app_server_timeout")
            if b"\n" not in self.buffer:
                self._ready(self.process.stdout, selectors.EVENT_READ)
                try:
                    chunk = os.read(self.process.stdout.fileno(), min(65536, MAX_OUTPUT_BYTES + 1 - self.total))
                except BlockingIOError:
                    continue
                if not chunk:
                    _fail("app_server_stdout_closed")
                self.total += len(chunk)
                if self.total > MAX_OUTPUT_BYTES:
                    _fail("app_server_output_limit")
                self.buffer += chunk
                continue
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.messages += 1
            if self.messages > MAX_MESSAGES:
                _fail("app_server_message_limit")
            try:
                item = json.loads(line.decode("utf-8"), object_pairs_hook=_object, parse_constant=_invalid_constant)
            except (UnicodeError, json.JSONDecodeError, RecursionError):
                _fail("app_server_decode_error")
            if not isinstance(item, dict) or item.get("jsonrpc", "2.0") != "2.0":
                _fail("app_server_malformed_message")
            if "id" not in item:
                if not isinstance(item.get("method"), str) or "error" in item or "result" in item:
                    _fail("app_server_malformed_notification")
                continue  # No notification payload is interpreted or retained.
            if type(item["id"]) is not int or item["id"] != request_id:
                _fail("app_server_response_id_mismatch")
            if "error" in item:
                _fail("app_server_rpc_error")
            if "method" in item or not isinstance(item.get("result"), dict):
                _fail("app_server_malformed_result")
            return item["result"]


def _reap_app_server(process: Any) -> None:
    """Bound teardown separately from the already exhausted RPC deadline."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=1.0)


class CodexAppServerThreadReader:
    """Trusted composition callback. The sole call input is the issued session ID.

    The selected CLI digest binds a separately qualified stdio protocol;
    another binary requires a separately qualified adapter update. Root/cwd are
    trusted composition settings, never parameters from a task request.
    """
    def __init__(self, *, launcher: str, sessions_root: str | None = None,
                 timeout_seconds: float = 15.0) -> None:
        if not isinstance(launcher, str) or not Path(launcher).is_absolute():
            _fail("launcher_must_be_absolute")
        root = Path(sessions_root) if sessions_root is not None else Path.home() / ".codex" / "sessions"
        if not root.is_absolute() or ".." in root.parts:
            _fail("sessions_root_must_be_absolute")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
            _fail("invalid_finite_timeout")
        self.launcher, self.sessions_root, self.timeout_seconds = launcher, root, timeout_seconds

    def read_with_deadline(self, issued_session: str, deadline: float) -> dict[str, Any]:
        if isinstance(deadline, bool) or not isinstance(deadline, (float, int)) or not math.isfinite(deadline) or deadline <= time.monotonic():
            _fail("app_server_timeout")
        return self(issued_session, _deadline=deadline)

    def __call__(self, issued_session: str, *, _deadline: float | None = None) -> dict[str, Any]:
        if not isinstance(issued_session, str) or not issued_session or len(issued_session) > 256 or any(c.isspace() or ord(c) < 32 for c in issued_session):
            _fail("issued_session_missing_or_malformed")
        process = None
        custody = None
        deadline = time.monotonic() + self.timeout_seconds
        if _deadline is not None: deadline = min(deadline, _deadline)
        try:
            # Bounded binary hashing; no credential or session file is opened.
            digest = hashlib.sha256()
            if not stat.S_ISREG(os.stat(self.launcher).st_mode):
                _fail("launcher_not_regular")
            with open(self.launcher, "rb") as binary:
                for _ in range(512):
                    if time.monotonic() >= deadline: _fail("app_server_timeout")
                    chunk = binary.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                else:
                    _fail("launcher_size_limit")
            if digest.hexdigest() not in SUPPORTED_CLI_SHA256:
                _fail("unsupported_cli_identity")
            custody = Custody.launch([self.launcher, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd="/private/tmp", close_fds=True, bufsize=0)
            process = custody.process
            rpc = _StdioRPC(process, deadline)
            rpc.send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "otto-exact-session-reader", "version": "0.1"},
                "capabilities": {"experimentalApi": True}}})
            rpc.response(1)
            rpc.send({"method": "initialized"})
            rpc.send({"id": 2, "method": "thread/read", "params": {
                "threadId": issued_session, "includeTurns": False}})
            result = rpc.response(2)
            thread = result.get("thread")
            if not isinstance(thread, dict) or thread.get("id") != issued_session:
                _fail("thread_missing_or_session_mismatch")
            if "turns" in thread and thread["turns"] != []:
                _fail("unexpected_turns_in_metadata_response")
            path = _checked_path(thread.get("path"), self.sessions_root)
            return {"thread": {"id": issued_session, "path": path}}
        except HostThreadReadError:
            raise
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            raise HostThreadReadError("host_metadata_lookup_failed") from None
        finally:
            if process is not None:
                # One process group per call; teardown never leaves a reusable
                # app-server session or unbounded wait behind.
                lookup_failed = sys.exc_info()[0] is not None
                try:
                    _reap_app_server(process)
                except (OSError, subprocess.SubprocessError):
                    # Preserve an earlier strict RPC/identity failure. A valid
                    # lookup still fails closed if its process cannot be reaped.
                    if not lookup_failed:
                        raise HostThreadReadError("app_server_cleanup_failed") from None
                finally:
                    if custody is not None:
                        # Sweep leftovers after the reap; the disposition never changes the propagating error.
                        try:
                            custody.release()
                        except Exception:
                            pass
                    process.stdin.close()
                    process.stdout.close()
