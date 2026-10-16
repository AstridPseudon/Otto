"""File lanes between ``ottoctl`` clients and the one running owner service.

A lane is a private directory (0700, this account, no symlink). A client
drops ``request-<token>.json`` (created exclusively, 0600) and waits for the
service's ``response-<token>.json``; while the service works it may publish
``pending-<token>.json``. Tokens are 32 lowercase hexadecimal characters.

Which lane a request arrives on is what binds its principal: the service
creates one lane per admitted host (in that host's own client home) and one
owner lane (in the service home, for operator actions such as admitting a
host). A request can never name its own principal. All lanes live in one OS
account, so this binds intent and prevents confusion between hosts; it is
not a defence against a hostile process of the same account (no lane in
this account can be).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterator, Mapping, Optional
import uuid

REQUEST_SCHEMA = "otto.host-lane-request.v1"
STATUS_FILE = "status.json"
# Same window as portfolio/ipc_retention.ANSWERED_RESPONSE_GRACE_SECONDS.
ANSWERED_PAIR_GRACE_SECONDS = 24 * 3600


def new_token() -> str:
    return uuid.uuid4().hex


def valid_token(token: Any) -> bool:
    return isinstance(token, str) and len(token) == 32 and all(c in "0123456789abcdef" for c in token)


def private_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise PermissionError(str(path) + " must be a directory owned by this account (no symlink)")
    if info.st_mode & 0o077:
        os.chmod(path, 0o700)
    return path


def atomic_json(path: Path, value: Any) -> Path:
    path = Path(path)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex[:8] + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, default=_default) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return path


def _default(item: Any) -> Any:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if isinstance(item, (set, frozenset, tuple)):
        return list(item)
    return str(item)


def read_private_json(path: Path) -> Optional[dict]:
    """A regular 0600-class file of this account, or None. Never follows a symlink."""
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError(str(path) + " is not a private regular file of this account")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd) as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(str(path) + " is not a JSON object")
    return value


def submit(lane: Path, request: Mapping[str, Any], *, token: Optional[str] = None) -> str:
    """Drop one request into a lane; never overwrites an existing request."""
    lane = Path(lane)
    if not lane.is_dir():
        raise FileNotFoundError("no lane at " + str(lane) + "; the host must be admitted by the owner service first")
    token = token or new_token()
    if not valid_token(token):
        raise ValueError("lane token must be 32 lowercase hexadecimal characters")
    path = lane / ("request-" + token + ".json")
    # Write aside, then link into place: the service never sees a partial
    # request, and an existing request is never replaced.
    temporary = lane / (".request-" + token + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(dict(request), stream, separators=(",", ":"), sort_keys=True, default=_default)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return token


def wait(lane: Path, token: str, *, timeout_seconds: float, poll_seconds: float = 0.05) -> Mapping[str, Any]:
    """The service's response, or a pending receipt naming the retained request."""
    lane = Path(lane)
    response = lane / ("response-" + token + ".json")
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        value = read_private_json(response)
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            pending = read_private_json(lane / ("pending-" + token + ".json")) or {}
            return {"outcome": "pending", "request_id": token, "terminal": False, "effects": "unknown",
                    "service_state": pending.get("state", "queued"), "response_path": str(response),
                    "next_action": "the request is retained; read it later with `ottoctl request-status --request-id "
                                   + token + "` and check `ottoctl service status`; do not resend it"}
        time.sleep(poll_seconds)


def requests(lane: Path) -> Iterator[tuple[str, Path]]:
    """Requests that have no response yet, oldest first.

    An answered pair past the retention window is removed as the listing passes
    it. A request that vanishes between the glob and its stat was answered or
    removed by someone else: it is skipped, never an error.
    """
    lane = Path(lane)
    if not lane.is_dir():
        return
    dated = []
    for path in lane.glob("request-*.json"):
        try:
            dated.append((path.stat().st_mtime_ns, path.name, path))
        except FileNotFoundError:
            continue
    dated.sort()
    for _, _, path in dated:
        token = path.name[len("request-"):-len(".json")]
        if (lane / ("response-" + token + ".json")).exists():
            _retire_answered(lane, token)
            continue
        yield token, path


def _retire_answered(lane: Path, token: str) -> None:
    """Remove an answered pair once its response is past the window; a pending receipt keeps it.

    The request goes first: a request left alone would look unanswered and run again.
    """
    response = lane / ("response-" + token + ".json")
    try:
        answered_at = response.stat().st_mtime
    except FileNotFoundError:
        return
    if time.time() - answered_at < ANSWERED_PAIR_GRACE_SECONDS or (lane / ("pending-" + token + ".json")).exists():
        return
    (lane / ("request-" + token + ".json")).unlink(missing_ok=True)
    response.unlink(missing_ok=True)


def respond(lane: Path, token: str, value: Mapping[str, Any]) -> None:
    atomic_json(Path(lane) / ("response-" + token + ".json"), dict(value))
    (Path(lane) / ("pending-" + token + ".json")).unlink(missing_ok=True)


def mark_pending(lane: Path, token: str, state: str, **fields: Any) -> None:
    atomic_json(Path(lane) / ("pending-" + token + ".json"),
                {"outcome": "pending", "request_id": token, "state": state, **fields})
