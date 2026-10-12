# Reused from claude-host/one-otto hostctl/lanes.py; ONE current owner composition.
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
MANAGER_START_RESPONSE_SCHEMA = "otto.orchestrator-manager-start-response.v1"
_CLIENT_RESPONSE_LIMIT = 1048576


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
    if info.st_size > 1048576:
        raise ValueError("client lane record exceeds 1 MiB; use its bounded retained reference")
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


def read_manager_start_response(lane: Path, token: str) -> Mapping[str, Any]:
    """Read a bounded manager-start envelope and its exact retained artifact pin.

    Large manager replies are retained by the owner action path, outside the
    client lane.  The lane carries only this finite envelope; callers that
    need the body must deliberately follow its authenticated retained pin.
    """
    if not valid_token(token):
        raise ValueError("exact retained manager-start request ID required")
    lane = Path(lane)
    response = lane / ("response-" + token + ".json")
    value = read_private_json(response)
    if value is None:
        raise FileNotFoundError(str(response))
    if value.get("schema") != MANAGER_START_RESPONSE_SCHEMA:
        return value
    if value.get("request_id") != token or value.get("operation") != "manager-start":
        raise PermissionError("manager-start response is bound to a different request")
    request_key = value.get("request_key")
    if not isinstance(request_key, str) or not request_key.strip() or request_key != request_key.strip():
        raise PermissionError("manager-start response has no exact domain key")
    if value.get("response_path") != str(response):
        raise PermissionError("manager-start response path is foreign")
    transport = value.get("authenticated_transport")
    if (not isinstance(transport, Mapping)
            or transport.get("lane") != str(lane)
            or transport.get("request_id") != token
            or transport.get("operation") != "manager-start"
            or transport.get("domain_key") != request_key):
        raise PermissionError("manager-start authenticated transport is foreign")
    retained = value.get("retained_response")
    if not isinstance(retained, Mapping):
        raise ValueError("manager-start response has no retained artifact reference")
    retained_root = lane.parent / "retained"
    metadata = retained_root / ("manager-start-" + token + ".json")
    detail = retained_root / ("manager-start-" + token + ".detail.json")
    if retained.get("metadata_path") != str(metadata) or retained.get("path") != str(detail):
        raise PermissionError("manager-start response retained reference is foreign or changed")
    try:
        root_info = retained_root.lstat()
        meta_info = metadata.lstat()
        if (stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode)
                or root_info.st_uid != os.geteuid() or root_info.st_mode & 0o077
                or stat.S_ISLNK(meta_info.st_mode) or not stat.S_ISREG(meta_info.st_mode)
                or meta_info.st_uid != os.geteuid() or meta_info.st_mode & 0o077):
            raise PermissionError("manager-start retained projection is not private")
        from .retained_projection import read_projection
        projection = read_projection(metadata, expected_binding={
            "request_id": token, "operation": "manager-start", "request_key": request_key})
        artifact = projection.get("artifact")
        if not isinstance(artifact, Mapping) or artifact.get("path") != str(detail):
            raise PermissionError("manager-start artifact projection is foreign")
        if retained.get("sha256") != artifact.get("sha256") or retained.get("byte_length") != artifact.get("byte_length"):
            raise ValueError("manager-start retained artifact identity changed")
        info = detail.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("manager-start retained artifact is not private")
        if info.st_size != artifact.get("byte_length") or info.st_size <= _CLIENT_RESPONSE_LIMIT:
            raise ValueError("manager-start retained response is missing or no longer oversize")
    except FileNotFoundError as exc:
        raise ValueError("manager-start retained response is missing") from exc
    return value


def wait(lane: Path, token: str, *, timeout_seconds: float, poll_seconds: float = 0.05) -> Mapping[str, Any]:
    """The service's response, or a pending receipt naming the retained request."""
    lane = Path(lane)
    response = lane / ("response-" + token + ".json")
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        value = read_private_json(response)
        if value is not None:
            if value.get("schema") == MANAGER_START_RESPONSE_SCHEMA:
                return read_manager_start_response(lane, token)
            return value
        if time.monotonic() >= deadline:
            pending = read_private_json(lane / ("pending-" + token + ".json")) or {}
            return {"outcome": "pending", "request_id": token, "terminal": False, "provider_called": pending.get("provider_called"),
                    "service_state": pending.get("state", "queued"), "response_path": str(response),
                    "next_action": "Follow this exact request with the installed orchestrator_client_ctl.py request-status --request-id "
                                   + token + " using the same binding/connection; do not resend it"}
        time.sleep(poll_seconds)


def requests(lane: Path) -> Iterator[tuple[str, Path]]:
    """Requests that have no response yet, oldest first."""
    lane = Path(lane)
    if not lane.is_dir():
        return
    paths = sorted(lane.glob("request-*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    for path in paths:
        token = path.name[len("request-"):-len(".json")]
        if (lane / ("response-" + token + ".json")).exists():
            continue
        yield token, path


def _respond_oversize_manager_start(lane: Path, token: str, value: Mapping[str, Any], request_key: str) -> None:
    """Retain one exact full reply, publishing only its bounded projection in the lane."""
    from .manager_journey_client import command_result_summary
    from .owner_readers import json_value
    from .retained_projection import atomic_json as retained_json, finite_summary, projection, read_projection

    lane = Path(lane)
    safe = json_value(value)
    retained_root = private_dir(lane.parent / "retained")
    metadata = retained_root / ("manager-start-" + token + ".json")
    detail = retained_root / ("manager-start-" + token + ".detail.json")
    binding = {"request_id": token, "operation": "manager-start", "request_key": request_key}
    if metadata.exists() or detail.exists():
        captured = read_projection(metadata, expected_binding=binding)
        artifact = captured.get("artifact", {})
        if artifact.get("path") != str(detail):
            raise PermissionError("existing manager-start artifact is foreign")
        if artifact.get("byte_length", 0) <= _CLIENT_RESPONSE_LIMIT:
            raise ValueError("existing manager-start artifact is not an oversize response")
        info = detail.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("existing manager-start artifact is not private")
        if info.st_size != artifact.get("byte_length"):
            raise ValueError("existing manager-start artifact length changed")
        summary = captured.get("summary", {})
    else:
        captured_artifact = retained_json(detail, safe)
        summary = {**command_result_summary(safe), **finite_summary(safe)}
        captured = projection(safe, artifact={"path": str(detail), **captured_artifact},
                              binding=binding, summary=summary, oversize="detail")
        retained_json(metadata, captured)
        artifact = captured["artifact"]
        summary = captured["summary"]
    envelope = {"schema": MANAGER_START_RESPONSE_SCHEMA,
        "outcome": safe.get("outcome"), "terminal": True, "request_id": token,
        "operation": "manager-start", "request_key": request_key,
        "response_path": str(lane / ("response-" + token + ".json")),
        "authenticated_transport": {"lane": str(lane), "request_id": token,
            "operation": "manager-start", "domain_key": request_key},
        "retained_response": {"metadata_path": str(metadata), "path": str(detail),
            "sha256": artifact.get("sha256"), "byte_length": artifact.get("byte_length"),
            "serialization": "canonical-json"},
        "summary": summary,
        "summary_availability": captured.get("summary_availability", "finite projection; inspect retained response by exact artifact pin"),
        "provider_called": safe.get("provider_called"), "retry": safe.get("retry"),
        "next_action": "Read the exact retained response artifact; do not resend this terminal request."}
    raw = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_default).encode() + b"\n"
    if len(raw) > _CLIENT_RESPONSE_LIMIT:
        raise ValueError("manager-start bounded response exceeds client lane limit")
    atomic_json(lane / ("response-" + token + ".json"), envelope)


def respond(lane: Path, token: str, value: Mapping[str, Any], *, operation: str | None = None,
            request_key: str | None = None) -> None:
    if operation == "manager-start" and isinstance(request_key, str) and request_key.strip() == request_key and request_key:
        from .owner_readers import json_value
        safe = json_value(value)
        raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_default).encode() + b"\n"
        if len(raw) > _CLIENT_RESPONSE_LIMIT:
            _respond_oversize_manager_start(lane, token, safe, request_key)
        else:
            atomic_json(Path(lane) / ("response-" + token + ".json"), dict(value))
    else:
        atomic_json(Path(lane) / ("response-" + token + ".json"), dict(value))
    (Path(lane) / ("pending-" + token + ".json")).unlink(missing_ok=True)


def mark_pending(lane: Path, token: str, state: str, **fields: Any) -> None:
    atomic_json(Path(lane) / ("pending-" + token + ".json"),
                {"outcome": "pending", "request_id": token, "state": state, **fields})
