"""Thin Otto operation gateway.

Otto presents responsibility and delegates transport to an injected adapter. It
does not create a queue, persist a session ledger, or settle Runtime work.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
from typing import Any, Mapping, Optional, Protocol

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
    requested_profile: str = "default"
    logical_request_key: Optional[str] = None
    project_ref: Any = None
    task_ref: Any = None
    assignment_ref: Any = None
    generation: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _json_value(value: Any) -> Any:
    """Convert public receipt values to finite JSON without owning them."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    value_attr = getattr(value, "value", None)
    if value_attr is not None:
        return _json_value(value_attr)
    return str(value)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class AttemptEnvelope:
    """One owner-bound observation of a native operation.

    This is an evidence value, not a ledger.  Durable hosts may pass an
    ``AttemptCapturePort`` supplied by the owner; Otto only adapts the value
    returned by the existing host adapter.
    """

    logical_request_key: str
    owner: str
    project_ref: Any
    task_ref: Any
    assignment_ref: Any
    generation: int
    operation: str
    requested_profile: str
    requested_model: str
    requested_reasoning: str
    logical_agent_id: str
    physical_session_id: Optional[str]
    observed_model: Optional[str]
    observed_reasoning: Optional[str]
    delivery_state: str
    outcome: str
    unknown_reason: Optional[str] = None
    timeout: Optional[bool] = None
    request_fingerprint: Optional[str] = None
    replayed: bool = False

    @property
    def native_session_id(self) -> Optional[str]:
        return self.physical_session_id

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({
            "native_session_id": self.physical_session_id,
            "project_ref": _json_value(self.project_ref),
            "task_ref": _json_value(self.task_ref),
            "assignment_ref": _json_value(self.assignment_ref),
        })
        return value


class AttemptCapturePort(Protocol):
    """Finite owner supplied attempt read/write boundary."""

    def read(self, logical_request_key: str) -> Optional[Mapping[str, Any]]: ...

    def read_assignment(self, assignment_ref: Any, generation: int) -> Optional[Mapping[str, Any]]: ...

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]: ...


class InMemoryAttemptCapture:
    """Deterministic fixture implementing the finite attempt port.

    The fixture intentionally has no persistence, scheduler, queue, or
    database API.  A real owner can replace it with its existing record port.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, dict[str, Any]] = {}
        self._by_assignment: dict[tuple[str, int], dict[str, Any]] = {}
        self._current_generation: dict[str, int] = {}

    @staticmethod
    def _assignment_key(value: Any) -> str:
        return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))

    def bind_generation(self, assignment_ref: Any, generation: int) -> None:
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be a positive integer")
        self._current_generation[self._assignment_key(assignment_ref)] = generation

    def read(self, logical_request_key: str) -> Optional[Mapping[str, Any]]:
        value = self._by_key.get(logical_request_key)
        return None if value is None else dict(value)

    def read_assignment(self, assignment_ref: Any, generation: int) -> Optional[Mapping[str, Any]]:
        value = self._by_assignment.get((self._assignment_key(assignment_ref), generation))
        return None if value is None else dict(value)

    def validate_generation(self, assignment_ref: Any, generation: int) -> Optional[str]:
        current = self._current_generation.get(self._assignment_key(assignment_ref))
        if current is not None and current != generation:
            return "assignment generation is stale"
        return None

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        value = dict(_json_value(envelope))
        key = value["logical_request_key"]
        prior = self._by_key.get(key)
        if prior is not None:
            if prior != value:
                raise ValueError("logical request key was reused with changed attempt")
            return dict(prior)
        assignment_key = (self._assignment_key(value["assignment_ref"]), int(value["generation"]))
        current = self._current_generation.get(assignment_key[0])
        if current is not None and current != assignment_key[1]:
            raise ValueError("assignment generation is stale")
        self._by_key[key] = value
        self._by_assignment[assignment_key] = value
        return dict(value)


def error(code: str, message: str, **details: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    value.update(details)
    return {"outcome": "error", "error": value}


class OttoGateway:
    """A stateless facade over one already-authorized adapter binding."""

    def __init__(self, adapter: Any = None, *, binding_available: bool = True,
                 authority_available: bool = True,
                 attempt_capture: Optional[AttemptCapturePort] = None,
                 require_owner_binding: bool = False,
                 owner_bound: Optional[bool] = None) -> None:
        self.adapter = adapter
        self.binding_available = binding_available
        self.authority_available = authority_available
        self.attempt_capture = attempt_capture
        self.require_owner_binding = (
            require_owner_binding if owner_bound is None else owner_bound
        )

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
        if self._owner_binding_required(responsibility):
            for field_name, label in (
                ("project_ref", "project reference"),
                ("task_ref", "task reference"),
                ("assignment_ref", "assignment reference"),
                ("logical_request_key", "logical request key"),
            ):
                value = responsibility.__dict__.get(field_name)
                if value is None or (isinstance(value, str) and not _text(value)):
                    return {"code": "missing_" + field_name, "message": label + " is required"}
            if isinstance(responsibility.generation, bool) or not isinstance(responsibility.generation, int) or responsibility.generation < 1:
                return {"code": "missing_generation", "message": "assignment generation must be a positive integer"}
        return None

    def _owner_binding_required(self, responsibility: Responsibility) -> bool:
        """Enable the stricter gate for the supported owner-bound route.

        Legacy neutral adapter callers predate BK-02 and omit all assignment
        fields.  They retain their existing behavior; any explicit owner
        binding metadata, an injected capture port, or an adapter-declared
        owner-bound route opts into the executable gate.
        """

        return bool(
            self.require_owner_binding
            or self.attempt_capture is not None
            or getattr(self.adapter, "owner_bound", False) is True
            or responsibility.logical_request_key is not None
            or any(value is not None for value in (
                responsibility.project_ref,
                responsibility.task_ref,
                responsibility.assignment_ref,
                responsibility.generation,
            ))
        )

    @staticmethod
    def _fingerprint(responsibility: Responsibility, request: Any) -> str:
        material = {
            "operation": responsibility.operation,
            "owner": responsibility.owner,
            "logical_agent_id": responsibility.logical_agent_id,
            "packet_digest": responsibility.packet_digest,
            "project_ref": _json_value(responsibility.project_ref),
            "task_ref": _json_value(responsibility.task_ref),
            "assignment_ref": _json_value(responsibility.assignment_ref),
            "generation": responsibility.generation,
            "requested_profile": responsibility.requested_profile,
            "requested_model": responsibility.requested_model,
            "requested_reasoning": responsibility.requested_reasoning,
            "request": _json_value(request),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _capture_read(self, method: str, *args: Any) -> Optional[Mapping[str, Any]]:
        if self.attempt_capture is None:
            return None
        reader = getattr(self.attempt_capture, method, None)
        if not callable(reader):
            return None
        value = reader(*args)
        if value is None:
            return None
        if isinstance(value, AttemptEnvelope):
            return value.to_dict()
        return dict(_json_value(value))

    def _attempt_from_result(self, responsibility: Responsibility, request: Any,
                            result: Any, *, error_message: Optional[str] = None) -> AttemptEnvelope:
        sources = list(result) if isinstance(result, tuple) else [result]

        def get(names: tuple[str, ...], default: Any = None) -> Any:
            for source in sources:
                value = self._nested_value(source, names)
                if value is not None:
                    return value
            return default

        raw_outcome = get(("outcome",), "unknown")
        outcome = getattr(raw_outcome, "value", raw_outcome)
        outcome = str(outcome)
        if outcome == "error":
            outcome = "failed"
        physical = get(("physical_session_id", "native_session_id"))
        observed_model = get(("observed_model", "model", "model_name"))
        observed_reasoning = get(("observed_reasoning", "reasoning_effort", "reasoning"))
        delivery_state = get(("delivery_state",), "done" if outcome == "succeeded" else "unknown")
        unknown_reason = error_message or get(("reconciliation", "unsupported_error", "unsupported_reason"))
        timeout = get(("timeout",), None)
        if timeout is None and isinstance(unknown_reason, str):
            timeout = "timeout" in unknown_reason.lower()
        return AttemptEnvelope(
            responsibility.logical_request_key or "",
            responsibility.owner,
            responsibility.project_ref,
            responsibility.task_ref,
            responsibility.assignment_ref,
            int(responsibility.generation or 0),
            responsibility.operation,
            responsibility.requested_profile,
            responsibility.requested_model,
            responsibility.requested_reasoning,
            responsibility.logical_agent_id,
            physical if _text(physical) else None,
            observed_model if _text(observed_model) else None,
            observed_reasoning if _text(observed_reasoning) else None,
            str(delivery_state),
            outcome,
            str(unknown_reason) if unknown_reason is not None else None,
            bool(timeout) if timeout is not None else None,
            self._fingerprint(responsibility, request),
        )

    @staticmethod
    def _nested_value(source: Any, names: tuple[str, ...]) -> Any:
        if source is None:
            return None
        if isinstance(source, Mapping):
            for name in names:
                if name in source:
                    return source[name]
            for child in source.values():
                value = OttoGateway._nested_value(child, names)
                if value is not None:
                    return value
            return None
        for name in names:
            value = getattr(source, name, None)
            if value is not None:
                return value
        identity = getattr(source, "identity", None)
        if identity is not None:
            return OttoGateway._nested_value(identity, names)
        return None

    def _attach_attempt(self, responsibility: Responsibility, request: Any, result: Any,
                        *, error_message: Optional[str] = None) -> Any:
        envelope = self._attempt_from_result(responsibility, request, result, error_message=error_message)
        if self.attempt_capture is not None:
            self.attempt_capture.record(envelope.to_dict())
        if isinstance(result, Mapping):
            attached = dict(result)
            attached["attempt"] = envelope.to_dict()
            attached["envelope"] = envelope.to_dict()
            return attached
        return {"outcome": envelope.outcome, "result": result,
                "attempt": envelope.to_dict(), "envelope": envelope.to_dict()}

    def _owner_bound_operation(self, responsibility: Responsibility, request: Any) -> Any:
        key = responsibility.logical_request_key
        fingerprint = self._fingerprint(responsibility, request)
        validator = getattr(self.attempt_capture, "validate_generation", None) if self.attempt_capture is not None else None
        if callable(validator):
            validation = validator(responsibility.assignment_ref, int(responsibility.generation or 0))
            if validation:
                return error("stale_generation", str(validation))
        prior = self._capture_read("read", key) if key else None
        if prior is not None:
            if prior.get("request_fingerprint") != fingerprint:
                return error("request_reuse_conflict", "logical request key was reused with changed attempt")
            prior["replayed"] = True
            return {"outcome": "replayed", "replayed": True, "adapter_called": False,
                    "attempt": prior, "envelope": prior}
        unresolved = self._capture_read("read_assignment", responsibility.assignment_ref, int(responsibility.generation or 0))
        if unresolved is not None and unresolved.get("outcome") == "unknown":
            return error("unknown_attempt_requires_reconciliation",
                         "an unresolved attempt for this assignment generation cannot be retried")
        return None

    def operation(self, responsibility: Responsibility, request: Any) -> Any:
        failure = self.preflight(responsibility)
        if failure:
            return {"outcome": "error", "error": failure}
        owner_bound = self._owner_binding_required(responsibility)
        if owner_bound and responsibility.operation != "inspect":
            prior = self._owner_bound_operation(responsibility, request)
            if prior is not None:
                return prior
        method = getattr(self.adapter, responsibility.operation, None)
        if method is None:
            result = error("unsupported_operation", f"adapter does not support {responsibility.operation}")
            if owner_bound and responsibility.operation != "inspect":
                return self._attach_attempt(responsibility, request, {
                    "outcome": "unsupported",
                    "error": result["error"],
                })
            return result
        try:
            result = method(request)
        except Exception as exc:
            if owner_bound and responsibility.operation != "inspect":
                return self._attach_attempt(responsibility, request,
                                            error("adapter_error", str(exc), operation=responsibility.operation),
                                            error_message=str(exc))
            return error("adapter_error", str(exc), operation=responsibility.operation)
        return self._attach_attempt(responsibility, request, result) if owner_bound and responsibility.operation != "inspect" else result

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


__all__ = ["OPERATIONS", "AttemptCapturePort", "AttemptEnvelope", "InMemoryAttemptCapture", "OttoGateway", "Responsibility", "error"]
