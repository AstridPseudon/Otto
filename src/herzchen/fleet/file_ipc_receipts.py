"""Durable file IPC claims and terminal receipt publication for fleet owners.

The caller owns command admission, dispatch, receipt formatting and its atomic
JSON writer. This fence owns the transport state that decides whether dispatch
may happen again after a write failure or owner restart.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, MutableMapping


@dataclass(frozen=True)
class FileReceiptInspection:
    state: str  # terminal, claimed, or unclaimed
    pending: Mapping[str, Any] | None


class FileReceiptFence:
    def __init__(self, *, lock: threading.RLock, active: set[str],
                 failures: MutableMapping[str, dict[str, str]],
                 write_json: Callable[[Path, Any], None],
                 legacy_claim_reasons: frozenset[str] = frozenset()) -> None:
        self._lock = lock
        self._active = active
        self._failures = failures
        self._write_json = write_json
        self._legacy_claim_reasons = legacy_claim_reasons
        self._settled: dict[str, dict[str, Any]] = {}

    @staticmethod
    def read_request(path: Path) -> tuple[Mapping[str, Any], str]:
        raw = path.read_bytes()
        request = json.loads(raw)
        if not isinstance(request, Mapping):
            raise ValueError("file IPC request must be an object")
        return request, hashlib.sha256(raw).hexdigest()

    def reserve(self, token: str) -> bool:
        with self._lock:
            if token in self._active:
                return False
            self._active.add(token)
            return True

    def release(self, token: str) -> None:
        with self._lock:
            self._active.discard(token)

    @staticmethod
    def terminal_response(response: Path) -> bool:
        if not response.is_file():
            return False
        value = json.loads(response.read_bytes())
        if not isinstance(value, Mapping) or not isinstance(value.get("outcome"), str):
            raise ValueError("terminal response is not a valid receipt")
        return True

    def inspect(self, token: str, request_digest: str, pending: Path,
                response: Path) -> FileReceiptInspection:
        if self.terminal_response(response):
            return FileReceiptInspection("terminal", None)
        state = json.loads(pending.read_bytes()) if pending.exists() else None
        if state is None:
            return FileReceiptInspection("unclaimed", None)
        if (not isinstance(state, Mapping) or state.get("request_id") != token
                or state.get("response_path") != str(response)):
            raise ValueError("pending receipt differs from the exact request handle")
        recorded_digest = state.get("request_sha256")
        if recorded_digest is not None and recorded_digest != request_digest:
            raise ValueError("pending request bytes changed")
        if "dispatch_claimed" in state and type(state["dispatch_claimed"]) is not bool:
            raise ValueError("pending dispatch claim is not boolean")
        # Older owners may have used a processing marker or a caller-supplied
        # deferred reason before the explicit claim field existed.
        legacy_reason = state.get("reason")
        claimed = (state.get("dispatch_claimed") is True
                   or "dispatch_claimed" not in state
                   and (state.get("request_state") == "processing"
                        or isinstance(legacy_reason, str)
                        and legacy_reason in self._legacy_claim_reasons))
        return FileReceiptInspection("claimed" if claimed else "unclaimed", state)

    def write_pending(self, token: str, request_digest: str, pending: Path,
                      response: Path, *, claimed: bool,
                      details: Mapping[str, Any]) -> None:
        marker = {"retry": False, **details, "outcome": "pending", "request_id": token,
                  "request_retained": True, "response_path": str(response),
                  "request_sha256": request_digest, "dispatch_claimed": claimed}
        self._write_json(pending, marker)

    def settled_receipt(self, token: str, request_digest: str) -> Any | None:
        with self._lock:
            settled = self._settled.get(token)
        if settled is None:
            return None
        if settled["request_sha256"] != request_digest:
            raise ValueError("settled receipt belongs to different request bytes")
        return settled["receipt"]

    @staticmethod
    def unknown_after_claim(token: str) -> dict[str, Any]:
        return {"outcome": "unknown", "request_id": token,
                "request_dispatched": True, "retry": False,
                "reason": "claimed dispatch has no durable terminal response after owner restart",
                "next_action": "Reconcile the original effect before any new explicit intent; do not resend this request."}

    def finish_terminal(self, token: str, request: Path, pending: Path) -> None:
        pending.unlink(missing_ok=True)
        request.unlink(missing_ok=True)
        with self._lock:
            self._settled.pop(token, None)
            self._failures.pop(token, None)

    def publish(self, token: str, request_digest: str, receipt: Any,
                request: Path, pending: Path, response: Path) -> None:
        # Store the timed settlement before active-token release. A scan can
        # then retry these exact receipt bytes without entering the handler.
        with self._lock:
            self._settled[token] = {"request_sha256": request_digest, "receipt": receipt}
        try:
            if not self.terminal_response(response):
                self._write_json(response, receipt)
            self.finish_terminal(token, request, pending)
        except Exception as exc:
            with self._lock:
                self._failures[token] = {"code": type(exc).__name__, "message": str(exc)}
        finally:
            self.release(token)
