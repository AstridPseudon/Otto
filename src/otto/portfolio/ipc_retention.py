"""Retention for manager-ipc response files.

A ``response-<token>.json`` is answered when the owner has finished the exact
request: the owner unlinks ``request-<token>.json`` right after it writes the
terminal response, so a response with no request beside it is the answered
signal the transport already has. A response is removable only when all of
these hold:

* no ``request-<token>.json`` (the request was consumed and answered);
* no ``pending-<token>.json`` (no retained receipt still names this response);
* no ``socket-intent-<token>.json`` (authenticated socket custody owns it);
* its outcome is terminal (not ``pending``/``unknown``, not ``terminal: false``);
* it is older than the grace period, so pollers that re-read
  ``command-status`` after a settle still find it.

Unanswered requests, pending receipts and anything unparseable are kept.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterator, NamedTuple

ANSWERED_RESPONSE_GRACE_SECONDS = 24 * 3600
MAX_PARSE_BYTES = 16 * 1024 * 1024
_NON_TERMINAL_OUTCOMES = frozenset({"pending", "unknown"})


class Candidate(NamedTuple):
    path: Path
    token: str
    bytes: int
    mtime: float
    status_path: Path | None


def _token_of(name: str, prefix: str) -> str | None:
    if name.startswith(prefix) and name.endswith(".json"):
        return name[len(prefix):-len(".json")]
    return None


def _is_terminal(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("outcome") in _NON_TERMINAL_OUTCOMES:
        return False
    return value.get("terminal") is not False


def _read_terminal(path: Path, size: int) -> bool:
    if size > MAX_PARSE_BYTES:
        return False
    try:
        with path.open("rb") as stream:
            return _is_terminal(json.loads(stream.read()))
    except (OSError, ValueError):
        return False


def scan_candidates(directory: str | Path, *, now: float | None = None,
                    grace: float = ANSWERED_RESPONSE_GRACE_SECONDS) -> Iterator[Candidate]:
    """Yield answered, past-grace responses, oldest first, streaming the directory.

    Only names are held in memory for the live-token check; response bodies
    are read one at a time.
    """
    now = time.time() if now is None else now
    root = Path(directory)
    live: set[str] = set()
    responses: list[tuple[float, str, os.DirEntry]] = []
    with os.scandir(root) as entries:
        for entry in entries:
            name = entry.name
            for prefix in ("request-", "pending-", "socket-intent-"):
                token = _token_of(name, prefix)
                if token is not None:
                    live.add(token)
            if _token_of(name, "response-") is not None and entry.is_file(follow_symlinks=False):
                responses.append((entry.stat(follow_symlinks=False).st_mtime, name, entry))
    responses.sort()
    for mtime, name, entry in responses:
        token = _token_of(name, "response-")
        if token in live or now - mtime < grace:
            continue
        size = entry.stat(follow_symlinks=False).st_size
        path = root / name
        if not _read_terminal(path, size):
            continue
        status = root / ("status-" + name)
        yield Candidate(path, token, size, mtime, status if status.exists() else None)


def prune_answered_responses(directory: str | Path, *, limit: int = 200,
                             now: float | None = None, grace: float = ANSWERED_RESPONSE_GRACE_SECONDS) -> int:
    """Remove up to ``limit`` answered responses (and their status projection)."""
    removed = 0
    for candidate in scan_candidates(directory, now=now, grace=grace):
        if removed >= limit:
            break
        try:
            candidate.path.unlink()
        except OSError:
            continue
        if candidate.status_path is not None:
            candidate.status_path.unlink(missing_ok=True)
        removed += 1
    return removed
