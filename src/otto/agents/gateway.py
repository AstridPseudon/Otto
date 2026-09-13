"""Thin Otto operation gateway.

Otto presents responsibility and delegates transport to an injected adapter. It
does not create a queue, persist a session ledger, or settle Runtime work.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Optional

OPERATIONS = ("invoke", "resume", "send", "inspect", "cancel", "wait")


@dataclass(frozen=True)
class Responsibility:
    owner: str
    logical_agent_id: str
    operation: str
    packet_digest: str
    route: str = "normal"
    physical_session_id: Optional[str] = None
    requested_model: str = "gpt-5.6-luna"
    requested_reasoning: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def error(code: str, message: str, **details: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    value.update(details)
    return {"outcome": "error", "error": value}


class OttoGateway:
    """A stateless facade over one already-authorized adapter binding."""

    def __init__(self, adapter: Any = None, *, binding_available: bool = True,
                 authority_available: bool = True) -> None:
        self.adapter = adapter
        self.binding_available = binding_available
        self.authority_available = authority_available

    def read(self) -> dict[str, Any]:
        return {
            "mode": "read",
            "binding": "available" if self.binding_available else "unavailable",
            "authority": "available" if self.authority_available else "unavailable",
            "transport_owner": "injected_adapter",
            "settlement_owner": "Runtime",
            "queue": "none",
        }

    def status(self) -> dict[str, Any]:
        result = self.read()
        result.update({"mode": "status", "status": "ready" if self.binding_available and self.authority_available else "blocked"})
        return result

    def inspect(self, responsibility: Responsibility) -> dict[str, Any]:
        if not responsibility.logical_agent_id:
            return error("missing_logical_agent", "logical agent identity is required")
        if not self.binding_available or self.adapter is None:
            return {"mode": "inspect", "responsibility": responsibility.to_dict(), "observed": False,
                    "state": "unknown", "error": {"code": "binding_unavailable", "message": "host adapter binding is unavailable"}}
        method = getattr(self.adapter, "inspect", None)
        if method is None:
            return error("unsupported_operation", "inspect is not supported by the adapter")
        return method(responsibility)

    def preflight(self, responsibility: Responsibility) -> Optional[dict[str, Any]]:
        if responsibility.operation not in OPERATIONS:
            return {"code": "unsupported_operation", "message": responsibility.operation}
        if not self.authority_available:
            return {"code": "authority_unavailable", "message": "explicit invocation authority is unavailable"}
        if not self.binding_available or self.adapter is None:
            return {"code": "binding_unavailable", "message": "host adapter binding is unavailable"}
        if not responsibility.owner:
            return {"code": "missing_owner", "message": "owning responsibility is required"}
        if not responsibility.logical_agent_id:
            return {"code": "missing_logical_agent", "message": "logical agent identity is required"}
        if responsibility.operation in {"invoke", "resume", "send"} and not responsibility.packet_digest:
            return {"code": "missing_packet_digest", "message": "input packet digest is required"}
        if responsibility.operation in {"resume", "send", "cancel"} and not responsibility.physical_session_id:
            return {"code": "missing_physical_session", "message": "existing physical session identity is required"}
        return None

    def operation(self, responsibility: Responsibility, request: Any) -> Any:
        failure = self.preflight(responsibility)
        if failure:
            return {"outcome": "error", "error": failure}
        method = getattr(self.adapter, responsibility.operation, None)
        if method is None:
            return error("unsupported_operation", f"adapter does not support {responsibility.operation}")
        try:
            return method(request)
        except Exception as exc:
            return error("adapter_error", str(exc), operation=responsibility.operation)

    def invoke(self, responsibility: Responsibility, request: Any) -> Any:
        return self.operation(responsibility, request)

    def resume(self, responsibility: Responsibility, request: Any) -> Any:
        return self.operation(responsibility, request)

    def send(self, responsibility: Responsibility, request: Any) -> Any:
        return self.operation(responsibility, request)

    def cancel(self, responsibility: Responsibility, request: Any) -> Any:
        return self.operation(responsibility, request)

    def wait(self, responsibility: Responsibility, request: Any) -> Any:
        return self.operation(responsibility, request)


__all__ = ["OPERATIONS", "OttoGateway", "Responsibility", "error"]
