"""Runner client: one request line out, one reply line back, over the runner's unix socket."""
from __future__ import annotations

import json
import os
import socket
from typing import Any, Mapping


class RunnerUnavailable(RuntimeError):
    """The runner cannot be reached, or did not answer."""


class RunnerClient:
    def __init__(self, socket_path: Any, timeout: float | None = None) -> None:
        self.socket_path = os.fspath(socket_path)
        self.timeout = timeout

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(request)
        if body.get("op") == "submit":
            parent = os.environ.get("RUNNER_PARENT_RUN_ID")
            token = os.environ.get("RUNNER_PARENT_TOKEN")
            if parent and token:
                body.setdefault("parent_run_id", parent)
                body.setdefault("parent_token", token)
        payload = (json.dumps(body, sort_keys=True) + "\n").encode("utf-8")
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except OSError as exc:
            raise RunnerUnavailable("cannot open a socket: %s" % exc) from exc
        with sock:
            try:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(payload)
                buffer = b""
                while b"\n" not in buffer:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
            except OSError as exc:
                raise RunnerUnavailable("runner at %s is unreachable: %s" % (self.socket_path, exc)) from exc
        line = buffer.split(b"\n", 1)[0]
        if not line:
            raise RunnerUnavailable("runner at %s closed without a reply" % self.socket_path)
        try:
            reply = json.loads(line.decode("utf-8"))
        except ValueError as exc:
            raise RunnerUnavailable("runner at %s sent a malformed reply" % self.socket_path) from exc
        if not isinstance(reply, dict):
            raise RunnerUnavailable("runner at %s sent a malformed reply" % self.socket_path)
        return reply
