"""Thin Otto operation gateway.

Otto presents responsibility and delegates transport to an injected adapter. It
does not create a queue, persist a session ledger, or settle Runtime work.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
import hashlib
import json
from typing import Any, Mapping, Optional, Protocol

from otto.portfolio.resource_sync import DELIVERY_STATES, ResourceSyncError, validate_resource_evidence

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
    execution_mode: Optional[str] = None
    require_host_attestation: bool = False
    resource_evidence: Any = None

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


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) == 64 and all(
        char in "0123456789abcdef" for char in value.strip().lower()
    )


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
    resource_evidence: Any = None

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

    def claim(self, logical_request_key: str, assignment_ref: Any, generation: int, request_fingerprint: str) -> Mapping[str, Any]: ...

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
        self._claims_by_key: dict[str, dict[str, Any]] = {}
        self._claims_by_assignment: dict[tuple[str, int], str] = {}

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

    def claim(self, logical_request_key: str, assignment_ref: Any, generation: int, request_fingerprint: str) -> Mapping[str, Any]:
        if not _text(logical_request_key) or not _text(request_fingerprint):
            raise ValueError("logical_request_key and request_fingerprint are required")
        assignment_key = (self._assignment_key(assignment_ref), int(generation))
        prior = self._by_key.get(logical_request_key)
        if prior is not None:
            if prior.get("request_fingerprint") != request_fingerprint:
                return {"outcome": "request_reuse_conflict", "message": "logical request key was reused with changed attempt"}
            return {"outcome": "replayed", "replayed": True, "attempt": dict(prior)}
        unresolved = self._by_assignment.get(assignment_key)
        if unresolved is not None and unresolved.get("outcome") == "unknown":
            return {"outcome": "unknown", "message": "an unresolved attempt requires reconciliation"}
        prior_claim = self._claims_by_key.get(logical_request_key)
        if prior_claim is not None:
            if prior_claim["request_fingerprint"] != request_fingerprint:
                return {"outcome": "request_reuse_conflict", "message": "logical request key was reused with changed claim"}
            return {"outcome": "claimed", "claimed": False, "replayed": False}
        competing_key = self._claims_by_assignment.get(assignment_key)
        if competing_key is not None and competing_key != logical_request_key:
            return {"outcome": "unknown", "message": "assignment generation already has a pending claim"}
        claim = {
            "logical_request_key": logical_request_key,
            "assignment_ref": _json_value(assignment_ref),
            "generation": int(generation),
            "request_fingerprint": request_fingerprint,
            "outcome": "claimed",
            "delivery_state": "claimed",
        }
        self._claims_by_key[logical_request_key] = claim
        self._claims_by_assignment[assignment_key] = logical_request_key
        return {"outcome": "claimed", "claimed": True, "replayed": False}

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        value = dict(_json_value(envelope))
        key = value["logical_request_key"]
        prior = self._by_key.get(key)
        if prior is not None:
            if prior != value:
                raise ValueError("logical request key was reused with changed attempt")
            return dict(prior)
        claim = self._claims_by_key.get(key)
        if claim is not None and claim.get("request_fingerprint") != value.get("request_fingerprint"):
            raise ValueError("recorded attempt does not match its owner claim")
        assignment_key = (self._assignment_key(value["assignment_ref"]), int(value["generation"]))
        current = self._current_generation.get(assignment_key[0])
        if current is not None and current != assignment_key[1]:
            raise ValueError("assignment generation is stale")
        self._by_key[key] = value
        self._by_assignment[assignment_key] = value
        self._claims_by_key.pop(key, None)
        if self._claims_by_assignment.get(assignment_key) == key:
            self._claims_by_assignment.pop(assignment_key, None)
        return dict(value)


class HerzchenAttemptCapture:
    """Persist gateway envelopes through the accepted assignment result API.

    This adapts existing ``ResponsibilityAssignments`` result observations and
    owner receipts; it creates no Otto-side store. Results are written after
    transport returns, so this adapter cannot exclude concurrent pre-delivery
    duplicates. A recorded unknown result remains a retry fence.
    """

    def __init__(self, assignments: Any, reader: Any, *, actor: Any) -> None:
        required = ("get", "list_observations", "append_result")
        if assignments is None or any(not callable(getattr(assignments, name, None)) for name in required):
            raise TypeError("assignments must expose the accepted get/list_observations/append_result APIs")
        if reader is None or any(not callable(getattr(reader, name, None)) for name in ("get_receipt", "get_record")):
            raise TypeError("reader must expose the read-only get_receipt/get_record APIs")
        if actor is None:
            raise TypeError("an authenticated Herzchen actor is required")
        self.assignments = assignments
        self.reader = reader
        self.actor = actor

    @staticmethod
    def _same_ref(left: Any, right: Any) -> bool:
        left_value, right_value = _json_value(left), _json_value(right)
        if not isinstance(left_value, Mapping) or not isinstance(right_value, Mapping):
            return False
        return all(left_value.get(key) == right_value.get(key) for key in ("authority", "kind", "id", "revision"))

    @staticmethod
    def _same_identity(left: Any, right: Any) -> bool:
        left_value, right_value = _json_value(left), _json_value(right)
        if not isinstance(left_value, Mapping) or not isinstance(right_value, Mapping):
            return False
        return all(left_value.get(key) == right_value.get(key) for key in ("authority", "kind", "id"))

    @staticmethod
    def _record_value(record: Any) -> Optional[Mapping[str, Any]]:
        payload = _json_value(getattr(record, "payload", None))
        ref = _json_value(getattr(record, "ref", None))
        if not isinstance(ref, Mapping) or ref.get("kind") != "wrk.result":
            return None
        if not isinstance(payload, Mapping) or payload.get("record_type") != "work.observation" or payload.get("observation_kind") != "result":
            return None
        body = payload.get("value") if isinstance(payload, Mapping) else None
        return body if isinstance(body, Mapping) else None

    def _current(self, assignment_ref: Any) -> Any:
        return self.assignments.get(assignment_ref)

    def _read_key(self, logical_request_key: str) -> Optional[Mapping[str, Any]]:
        receipt = self.reader.get_receipt(logical_request_key)
        receipt_value = _json_value(receipt) if receipt is not None else None
        if receipt is None:
            return None
        if not isinstance(receipt_value, Mapping):
            return {"logical_request_key": logical_request_key, "request_fingerprint": "invalid-owner-receipt", "outcome": "unknown"}
        result_ref = receipt_value.get("result_ref")
        if receipt_value.get("operation") != "work.result.append" or receipt_value.get("status") != "committed":
            return {"logical_request_key": logical_request_key, "request_fingerprint": "foreign-owner-receipt", "outcome": "unknown"}
        if not isinstance(result_ref, Mapping) or result_ref.get("kind") != "wrk.result":
            return {"logical_request_key": logical_request_key, "request_fingerprint": "missing-owner-result", "outcome": "unknown"}
        if not self._same_identity(receipt_value.get("target"), result_ref):
            return {"logical_request_key": logical_request_key, "request_fingerprint": "owner-receipt-target-mismatch", "outcome": "unknown"}
        from herzchen.contracts import ResourceRef

        record = self.reader.get_record(ResourceRef.from_dict(result_ref))
        value = self._record_value(record)
        if value is None or value.get("logical_request_key") != logical_request_key:
            return {"logical_request_key": logical_request_key, "request_fingerprint": "mismatched-owner-result", "outcome": "unknown"}
        payload = _json_value(getattr(record, "payload", {}))
        if not isinstance(payload, Mapping):
            return {"logical_request_key": logical_request_key, "request_fingerprint": "invalid-owner-result", "outcome": "unknown"}
        if not self._same_ref(value.get("assignment_ref"), payload.get("assignment")) or value.get("generation") != payload.get("generation"):
            return {"logical_request_key": logical_request_key, "request_fingerprint": "owner-result-custody-mismatch", "outcome": "unknown"}
        return dict(value)

    def read(self, logical_request_key: str) -> Optional[Mapping[str, Any]]:
        if not _text(logical_request_key):
            raise ValueError("logical_request_key is required")
        return self._read_key(logical_request_key)

    def validate_generation(self, assignment_ref: Any, generation: int) -> Optional[str]:
        try:
            current = self._current(assignment_ref)
        except Exception:
            return "current assignment is unavailable"
        current_ref = getattr(current, "ref", None)
        current_generation = getattr(current, "generation", None)
        current_status = getattr(getattr(current, "status", None), "value", getattr(current, "status", None))
        if not self._same_ref(assignment_ref, current_ref):
            return "assignment reference is stale"
        if isinstance(generation, bool) or not isinstance(generation, int) or current_generation != generation:
            return "assignment generation is stale"
        if current_status not in {"queued", "in-flight", "reassigned", "active", "in_progress", "pending"}:
            return "assignment is not live"
        return None

    def read_assignment(self, assignment_ref: Any, generation: int, *,
                        diagnostics: Optional[dict[str, Any]] = None) -> Optional[Mapping[str, Any]]:
        """Read once, optionally describing this call in a caller-owned dictionary.

        Diagnostics do not change the returned attempt or trigger extra reads.
        ``matching_result_count`` counts only values passing the existing exact
        assignment-reference/generation filter, not a task or request-key filter.
        It is None until listing and filtering finish. Known diagnostic fields
        are reset on every call; unexpected exceptions still propagate, leaving
        status ``started`` rather than implying a completed observation.
        """
        if diagnostics is not None:
            diagnostics.update(validation_error=None, list_observations_called=False,
                               matching_result_count=None, status="started")
        failure = self.validate_generation(assignment_ref, generation)
        if diagnostics is not None:
            diagnostics["validation_error"] = failure
        if failure:
            if diagnostics is not None:
                diagnostics["status"] = "validation_failed"
            return None
        try:
            if diagnostics is not None:
                diagnostics["list_observations_called"] = True
            records = self.assignments.list_observations(assignment_ref, kind="result")
        except Exception:
            if diagnostics is not None:
                diagnostics["status"] = "observations_unavailable"
            return {"outcome": "unknown", "unknown_reason": "owner result observations are unavailable"}
        values = []
        for item in records:
            value = _json_value(getattr(item, "value", None))
            if not isinstance(value, Mapping):
                continue
            if value.get("generation") != generation or not self._same_ref(value.get("assignment_ref"), assignment_ref):
                continue
            values.append((int(getattr(item, "version", 0)), dict(value)))
        if diagnostics is not None:
            diagnostics.update(matching_result_count=len(values),
                               status="result_found" if values else "no_matching_result")
        if not values:
            return None
        unknowns = [(version, value) for version, value in values if value.get("outcome") == "unknown"]
        return max(unknowns or values, key=lambda pair: pair[0])[1]

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(envelope, Mapping):
            raise TypeError("attempt envelope must be a mapping")
        value = dict(_json_value(envelope))
        key = value.get("logical_request_key")
        assignment_ref = value.get("assignment_ref")
        generation = value.get("generation")
        if not _text(key) or assignment_ref is None or isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("attempt envelope has incomplete owner custody")
        prior = self._read_key(key)
        if prior is not None:
            if prior != value:
                raise ValueError("logical request key was reused with changed owner result")
            return prior
        failure = self.validate_generation(assignment_ref, generation)
        if failure:
            raise ValueError(failure)
        self.assignments.append_result(
            assignment_ref, value, expected_generation=generation,
            logical_request_key=key, actor=self.actor,
        )
        recorded = self._read_key(key)
        if recorded != value:
            raise ValueError("owner result readback did not match the attempt envelope")
        return recorded

class OwnerDueRecordAttemptCapture:
    """CAS-backed claim/result capture in the existing owner DueRecord.

    The DueRecord remains the sole native-attempt record for runtimes using
    this adapter.  The immutable expected scope is injected by the owner
    runtime; a matching current ``in_flight_request`` is required before a
    claim can be written.  This class does not admit callbacks by itself.
    """

    def __init__(self, due_port: Any, schedule_id: str, *, project_ref: Mapping[str, Any],
                 task_ref: Mapping[str, Any], assignment_ref: Mapping[str, Any],
                 generation: int, role: str, principal: Any,
                 lifecycle_owner: str, expected_target: Optional[Mapping[str, Any]] = None,
                 scope_validator: Optional[Any] = None) -> None:
        if due_port is None or not callable(getattr(due_port, "read_due", None)) or not callable(getattr(due_port, "save_due", None)):
            raise TypeError("due_port must expose read_due/save_due")
        if not _text(schedule_id) or not _text(lifecycle_owner):
            raise ValueError("schedule_id and lifecycle_owner are required")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be positive")
        self.due_port = due_port
        self.schedule_id = schedule_id
        self.project_ref = dict(_json_value(project_ref))
        self.task_ref = dict(_json_value(task_ref))
        self.assignment_ref = dict(_json_value(assignment_ref))
        self.generation = generation
        self.role = role
        self.principal = _json_value(principal)
        self.lifecycle_owner = lifecycle_owner
        self.expected_target = dict(_json_value(expected_target)) if expected_target is not None else {
            "project_ref": self.project_ref, "task_ref": self.task_ref,
            "assignment_ref": self.assignment_ref, "role": role, "principal": self.principal,
        }
        if scope_validator is not None and not callable(scope_validator):
            raise TypeError("scope_validator must be callable")
        self.scope_validator = scope_validator

    @staticmethod
    def _same(left: Any, right: Any) -> bool:
        return json.dumps(_json_value(left), sort_keys=True, separators=(",", ":")) == json.dumps(_json_value(right), sort_keys=True, separators=(",", ":"))

    def _record(self) -> Any:
        from otto.attention import DueRecord

        value = self.due_port.read_due(self.schedule_id)
        return None if value is None else DueRecord.from_dict(value)

    def _scope_error(self, record: Any, assignment_ref: Any, generation: int, request_key: Optional[str] = None) -> Optional[str]:
        target = record.target if isinstance(record.target, Mapping) else {}
        if not self._same(target, self.expected_target):
            return "due record target is outside the bound assignment scope"
        if record.project_ref != self.project_ref.get("id") or record.generation != generation or generation != self.generation:
            return "due record project or generation is stale"
        if record.lifecycle_owner != self.lifecycle_owner or record.manager_ref != self.lifecycle_owner:
            return "due record lifecycle owner is stale"
        if record.stop_state != "active":
            return "owner due record is stopped"
        if record.delivery_state != "ready":
            return "owner due occurrence is not ready for delivery"
        if not self._same(assignment_ref, self.assignment_ref):
            return "assignment reference is outside the bound due record"
        if request_key is not None and record.in_flight_request != request_key:
            return "owner due-record occurrence is not currently admitted"
        return None

    @staticmethod
    def _attempt(record: Any) -> Optional[dict[str, Any]]:
        evidence = record.host_evidence if isinstance(record.host_evidence, Mapping) else {}
        attempt = evidence.get("gateway_attempt")
        return None if not isinstance(attempt, Mapping) else dict(attempt)

    def validate_generation(self, assignment_ref: Any, generation: int) -> Optional[str]:
        if self.scope_validator is not None:
            try:
                failure = self.scope_validator()
            except Exception:
                return "canonical owner scope is unavailable"
            if failure:
                return str(failure)
        try:
            record = self._record()
        except Exception:
            return "owner due record is unavailable"
        if record is None:
            return "owner due record is missing"
        return self._scope_error(record, assignment_ref, generation)

    def read(self, logical_request_key: str) -> Optional[Mapping[str, Any]]:
        record = self._record()
        attempt = None if record is None else self._attempt(record)
        if attempt is None or attempt.get("logical_request_key") != logical_request_key or attempt.get("state") != "result":
            return None
        value = attempt.get("result")
        return dict(value) if isinstance(value, Mapping) else None

    def read_assignment(self, assignment_ref: Any, generation: int) -> Optional[Mapping[str, Any]]:
        record = self._record()
        if record is None or self._scope_error(record, assignment_ref, generation):
            return {"outcome": "unknown", "unknown_reason": "current due-record custody is unavailable"}
        attempt = self._attempt(record)
        if attempt is None or attempt.get("generation") != generation or not self._same(attempt.get("assignment_ref"), assignment_ref):
            return None
        result = attempt.get("result")
        return dict(result) if isinstance(result, Mapping) else {"outcome": "unknown", "unknown_reason": "attempt claim has no result"}

    def _save(self, record: Any, attempt: Mapping[str, Any], request_id: str) -> Mapping[str, Any]:
        value = record.to_dict()
        evidence = dict(record.host_evidence or {})
        evidence["gateway_attempt"] = dict(_json_value(attempt))
        value["host_evidence"] = evidence
        return self.due_port.save_due(self.schedule_id, value, request_id=request_id, expected_version=record.version)

    def claim(self, logical_request_key: str, assignment_ref: Any, generation: int, request_fingerprint: str) -> Mapping[str, Any]:
        if self.scope_validator is not None:
            try:
                failure = self.scope_validator()
            except Exception:
                return {"outcome": "unknown", "message": "canonical owner scope could not be reread before claim"}
            if failure:
                return {"outcome": "stale_scope", "message": str(failure)}
        try:
            record = self._record()
        except Exception:
            return {"outcome": "unknown", "message": "owner due record could not be read"}
        if record is None:
            return {"outcome": "unknown", "message": "owner due record is missing"}
        scope_error = self._scope_error(record, assignment_ref, generation, logical_request_key)
        if scope_error:
            return {"outcome": "foreign_scope", "message": scope_error}
        prior = self._attempt(record)
        if prior is not None:
            if prior.get("logical_request_key") != logical_request_key:
                prior_result = prior.get("result") if isinstance(prior.get("result"), Mapping) else {}
                next_owner_occurrence = (
                    prior.get("state") == "result"
                    and record.last_completed_request == prior.get("logical_request_key")
                    and record.completion_state == "succeeded"
                    and record.in_flight_request == logical_request_key
                    and prior_result.get("outcome") != "unknown"
                    and prior_result.get("delivery_state") != "unknown"
                )
                if not next_owner_occurrence:
                    return {"outcome": "unknown", "message": "due occurrence already has a different unresolved attempt"}
            else:
                if prior.get("request_fingerprint") != request_fingerprint:
                    return {"outcome": "request_reuse_conflict", "message": "same request key has different attempt content"}
                if prior.get("state") == "result" and isinstance(prior.get("result"), Mapping):
                    return {"outcome": "replayed", "attempt": dict(prior["result"])}
                return {"outcome": "unknown", "message": "due occurrence already has an unresolved claim"}
        claim = {
            "state": "claimed", "logical_request_key": logical_request_key,
            "request_fingerprint": request_fingerprint,
            "assignment_ref": _json_value(assignment_ref), "generation": generation,
        }
        try:
            saved = self._save(record, claim, "otto-gateway-claim:" + logical_request_key)
        except Exception as exc:
            if type(exc).__name__ in {"StateConflictError", "VersionConflictError", "InputChangedError", "TargetMismatchError"}:
                return {"outcome": "stale_claim", "message": "owner CAS rejected the delivery claim"}
            raise
        receipt = saved.get("mutation_receipt") if isinstance(saved, Mapping) else None
        if not isinstance(receipt, Mapping) or receipt.get("status") != "committed" or receipt.get("replayed") is not False:
            return {"outcome": "stale_claim", "message": "owner did not prove a fresh committed claim mutation"}
        return {"outcome": "claimed", "claimed": True}

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        value = dict(_json_value(envelope))
        record = self._record()
        if record is None:
            raise ValueError("owner due record is missing")
        if self._scope_error(record, value.get("assignment_ref"), value.get("generation"), value.get("logical_request_key")):
            raise ValueError("attempt result no longer matches the admitted due record")
        current = self._attempt(record)
        if current is None or current.get("state") != "claimed" or current.get("logical_request_key") != value.get("logical_request_key") or current.get("request_fingerprint") != value.get("request_fingerprint"):
            if current is not None and current.get("state") == "result" and current.get("result") == value:
                return value
            raise ValueError("attempt result has no matching CAS-backed claim")
        result = {**current, "state": "result", "result": value}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self._save(record, result, "otto-gateway-result:" + str(value["logical_request_key"]) + ":" + digest)
        return value

    def record_thread_started(
        self, logical_request_key: str, physical_session_id: str, *, process_created: bool = True
    ) -> Mapping[str, Any]:
        """Bind provider identity to a current claim, without authorizing work."""
        if not _text(logical_request_key) or not _text(physical_session_id):
            raise ValueError("logical request key and physical session identity are required")
        if self.scope_validator is not None:
            failure = self.scope_validator()
            if failure:
                raise ValueError(str(failure))
        record = self._record()
        if record is None or self._scope_error(record, self.assignment_ref, self.generation, logical_request_key):
            raise ValueError("thread identity no longer has current owner custody")
        current = self._attempt(record)
        if current is None or current.get("state") != "claimed" or current.get("logical_request_key") != logical_request_key:
            raise ValueError("thread identity has no matching owner claim")
        prior = current.get("physical_session_id")
        if prior is not None:
            if prior != physical_session_id:
                raise ValueError("thread identity changed after owner capture")
            return current
        updated = {**current, "physical_session_id": physical_session_id,
                   "native_session_id": physical_session_id,
                   "launch_state": "identified" if process_created else "identified_existing",
                   "process_created": process_created}
        saved = self._save(record, updated, "otto-gateway-thread-started:" + logical_request_key + ":" + physical_session_id)
        receipt = saved.get("mutation_receipt") if isinstance(saved, Mapping) else None
        if not isinstance(receipt, Mapping) or receipt.get("status") != "committed":
            raise ValueError("owner did not confirm the thread identity capture")
        readback = self._record()
        captured = None if readback is None else self._attempt(readback)
        if (readback is None or self._scope_error(readback, self.assignment_ref, self.generation, logical_request_key)
                or captured is None or captured.get("physical_session_id") != physical_session_id
                or captured.get("logical_request_key") != logical_request_key):
            raise ValueError("thread identity owner readback failed")
        return captured


class DueRecordAttemptCapture:
    """Owner-backed attempt capture over the existing finite DueRecordPort.

    Claims and normalized attempt results are stored inside the current
    DueRecord host evidence and advanced with the record's existing CAS
    version.  This is not a second ledger or persistence path.
    """

    def __init__(
        self,
        due_port: Any,
        schedule_id: str,
        *,
        assignment_ref: Any = None,
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        lifecycle_owner: Optional[str] = None,
    ) -> None:
        if due_port is None or not callable(getattr(due_port, "read_due", None)) or not callable(getattr(due_port, "save_due", None)):
            raise TypeError("due_port must expose the public read_due/save_due methods")
        if not _text(schedule_id):
            raise ValueError("schedule_id is required")
        self.due_port = due_port
        self.schedule_id = schedule_id
        self.assignment_ref = _json_value(assignment_ref)
        self.project_ref = project_ref
        self.manager_ref = manager_ref
        self.lifecycle_owner = lifecycle_owner

    @staticmethod
    def _same(left: Any, right: Any) -> bool:
        return json.dumps(_json_value(left), sort_keys=True, separators=(",", ":")) == json.dumps(_json_value(right), sort_keys=True, separators=(",", ":"))

    def _record(self) -> Any:
        from otto.attention import DueRecord

        value = self.due_port.read_due(self.schedule_id)
        return None if value is None else DueRecord.from_dict(value)

    def _scope_error(self, record: Any, assignment_ref: Any, generation: int) -> Optional[dict[str, Any]]:
        if record.generation != generation:
            return {"outcome": "stale_generation", "message": "due record generation is stale"}
        if self.assignment_ref is not None and not self._same(record.assignment_ref, assignment_ref):
            return {"outcome": "foreign_assignment", "message": "assignment does not match the due record"}
        if self.project_ref is not None and record.project_ref != self.project_ref:
            return {"outcome": "foreign_scope", "message": "project does not match the due record"}
        if self.manager_ref is not None and record.manager_ref != self.manager_ref:
            return {"outcome": "foreign_scope", "message": "manager does not match the due record"}
        if self.lifecycle_owner is not None and record.lifecycle_owner != self.lifecycle_owner:
            return {"outcome": "foreign_authority", "message": "lifecycle owner does not match the due record"}
        return None

    @staticmethod
    def _attempt(record: Any) -> Optional[dict[str, Any]]:
        evidence = record.host_evidence if isinstance(record.host_evidence, Mapping) else {}
        attempt = evidence.get("gateway_attempt")
        return None if not isinstance(attempt, Mapping) else dict(attempt)

    def _save_attempt(self, record: Any, attempt: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        evidence = dict(record.host_evidence or {})
        evidence["gateway_attempt"] = _json_value(attempt)
        value = record.to_dict()
        value["host_evidence"] = evidence
        return self.due_port.save_due(self.schedule_id, value, request_id=request_id, expected_version=record.version)

    def read(self, logical_request_key: str) -> Optional[Mapping[str, Any]]:
        record = self._record()
        attempt = None if record is None else self._attempt(record)
        if attempt is None or attempt.get("logical_request_key") != logical_request_key or attempt.get("state") != "result":
            return None
        result = attempt.get("result")
        return None if not isinstance(result, Mapping) else dict(_json_value(result))

    def read_assignment(self, assignment_ref: Any, generation: int) -> Optional[Mapping[str, Any]]:
        record = self._record()
        attempt = None if record is None else self._attempt(record)
        if attempt is None or attempt.get("generation") != generation or not self._same(attempt.get("assignment_ref"), assignment_ref):
            return None
        result = attempt.get("result")
        return None if not isinstance(result, Mapping) else dict(_json_value(result))

    def validate_generation(self, assignment_ref: Any, generation: int) -> Optional[str]:
        record = self._record()
        if record is None:
            return "due record is missing"
        scope_error = self._scope_error(record, assignment_ref, generation)
        return None if scope_error is None else str(scope_error.get("message"))

    def validate_resources(self, evidence: Any) -> Optional[str]:
        record = self._record()
        adoption = None if record is None else (record.host_evidence or {}).get("resource_adoption")
        if adoption is not None:
            brief_adoption = evidence.get("brief", {}).get("resource_adoption") if isinstance(evidence, Mapping) else None
            if brief_adoption != {"revision": adoption["revision"], "digest": adoption["digest"]}:
                return "brief does not match the reconciled instruction adoption"
        return None

    def claim(self, logical_request_key: str, assignment_ref: Any, generation: int, request_fingerprint: str) -> Mapping[str, Any]:
        record = self._record()
        if record is None:
            return {"outcome": "unknown", "message": "due record is missing"}
        scope_error = self._scope_error(record, assignment_ref, generation)
        if scope_error is not None:
            return scope_error
        current = self._attempt(record)
        if current is not None:
            same_key = current.get("logical_request_key") == logical_request_key
            same_input = current.get("request_fingerprint") == request_fingerprint
            if same_key and not same_input:
                return {"outcome": "request_reuse_conflict", "message": "logical request key was reused with changed attempt"}
            if same_key and current.get("state") == "result":
                return {"outcome": "replayed", "replayed": True, "attempt": current.get("result")}
            if same_key:
                return {"outcome": "claimed", "claimed": False, "replayed": False}
            return {"outcome": "unknown", "message": "assignment generation already has a persisted claim"}
        claim = {
            "state": "claimed",
            "logical_request_key": logical_request_key,
            "assignment_ref": _json_value(assignment_ref),
            "generation": generation,
            "request_fingerprint": request_fingerprint,
            "owner_version": record.version,
        }
        try:
            self._save_attempt(record, claim, request_id="gateway-claim:" + logical_request_key)
        except Exception as exc:
            if type(exc).__name__ in {"VersionConflictError", "StateConflictError", "TargetMismatchError"}:
                return {"outcome": "stale_claim", "message": "owner CAS rejected the claim"}
            raise
        return {"outcome": "claimed", "claimed": True, "replayed": False}

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        value = dict(_json_value(envelope))
        record = self._record()
        if record is None:
            raise ValueError("due record is missing")
        current = self._attempt(record)
        if current is None or current.get("state") != "claimed":
            if current is not None and current.get("state") == "result" and current.get("result") == value:
                return value
            raise ValueError("attempt result has no matching persisted claim")
        if current.get("logical_request_key") != value.get("logical_request_key") or current.get("request_fingerprint") != value.get("request_fingerprint"):
            raise ValueError("attempt result does not match the persisted claim")
        result_attempt = {**current, "state": "result", "result": value}
        self._save_attempt(record, result_attempt, request_id="gateway-result:" + str(value["logical_request_key"]) + ":" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        return value

    def recovery_status(self, logical_request_key: str, *, owner_actor: str) -> Mapping[str, Any]:
        """Read an unresolved native attempt without relaunching it."""

        record = self._record()
        if record is None:
            return {"outcome": "unknown", "status": "undetermined", "message": "due record is missing"}
        if owner_actor != record.lifecycle_owner or owner_actor != record.manager_ref:
            return {"outcome": "rejected", "status": "unsupported", "error": {"code": "foreign_authority", "message": "only the canonical lifecycle manager may reconcile the attempt"}}
        attempt = self._attempt(record)
        if attempt is None or attempt.get("logical_request_key") != logical_request_key:
            return {"outcome": "unknown", "status": "undetermined", "message": "attempt is not present"}
        result = attempt.get("result") if isinstance(attempt.get("result"), Mapping) else attempt
        unresolved = result.get("outcome") == "unknown" or result.get("delivery_state") == "unknown" or attempt.get("launch_state") in {"unknown_before_id", "unknown_after_id"}
        return {
            "outcome": "recovery_required" if unresolved else "not_required",
            "retry_allowed": False if unresolved else None,
            "readback_version": record.version,
            "attempt": attempt,
        }

    def accept_result(self, logical_request_key: str, *, manager_actor: str) -> Mapping[str, Any]:
        """Accept one trusted successful result through the existing owner CAS."""

        record = self._record()
        if record is None:
            return {"outcome": "unknown", "status": "undetermined", "message": "due record is missing"}
        if manager_actor != record.lifecycle_owner or manager_actor != record.manager_ref:
            return {"outcome": "rejected", "status": "unsupported", "error": {"code": "foreign_authority", "message": "only the canonical lifecycle manager may accept the result"}}
        attempt = self._attempt(record)
        if attempt is None or attempt.get("logical_request_key") != logical_request_key:
            return {"outcome": "unknown", "status": "undetermined", "message": "attempt is not present"}
        result = attempt.get("result") if isinstance(attempt.get("result"), Mapping) else {}
        if attempt.get("state") != "result" or result.get("outcome") != "succeeded":
            return {"outcome": "not_accepted", "status": "undetermined", "retry_allowed": False, "attempt": attempt}
        observed_model = result.get("observed_model")
        observed_reasoning = result.get("observed_reasoning")
        if (
            not _text(record.requested_model)
            or not _text(record.requested_reasoning)
            or not _text(observed_model)
            or not _text(observed_reasoning)
            or observed_model != record.requested_model
            or observed_reasoning != record.requested_reasoning
        ):
            return {
                "outcome": "not_accepted",
                "status": "unsupported",
                "retry_allowed": False,
                "error": {
                    "code": "observed_host_attestation_required",
                    "message": "manager acceptance requires trusted observed model/reasoning matching the due record",
                    "requested_model": record.requested_model,
                    "requested_reasoning": record.requested_reasoning,
                    "observed_model": observed_model,
                    "observed_reasoning": observed_reasoning,
                },
                "attempt": attempt,
            }
        prior = attempt.get("manager_acceptance")
        if isinstance(prior, Mapping) and prior.get("owner") == manager_actor and prior.get("accepted") is True:
            return {"outcome": "accepted", "accepted": True, "replayed": True, "readback_version": record.version, "attempt": attempt}
        acceptance = {
            "accepted": True,
            "owner": manager_actor,
            "owner_version": record.version,
            "logical_request_key": logical_request_key,
            "result_digest": hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        }
        updated = {**attempt, "manager_acceptance": acceptance}
        saved = self._save_attempt(record, updated, request_id="gateway-accept:" + logical_request_key + ":" + str(record.version))
        readback = self._attempt(self._record()) or updated
        return {"outcome": "accepted", "accepted": True, "replayed": False, "readback_version": saved.get("version"), "attempt": readback}

    def record_thread_started(
        self, logical_request_key: str, physical_session_id: str, *, process_created: bool = True
    ) -> Mapping[str, Any]:
        """Persist native identity as soon as the owner adapter observes it."""

        if not _text(logical_request_key) or not _text(physical_session_id):
            raise ValueError("logical_request_key and physical_session_id are required")
        record = self._record()
        if record is None:
            raise ValueError("due record is missing")
        current = self._attempt(record)
        if current is None or current.get("logical_request_key") != logical_request_key:
            raise ValueError("thread identity has no matching owner claim")
        prior_identity = current.get("physical_session_id")
        if prior_identity is not None and prior_identity != physical_session_id:
            raise ValueError("thread identity changed after capture")
        if prior_identity == physical_session_id:
            return current
        updated = {
            **current,
            "physical_session_id": physical_session_id,
            "native_session_id": physical_session_id,
            "launch_state": "identified" if process_created else "identified_existing",
            "process_created": process_created,
        }
        self._save_attempt(record, updated, request_id=f"gateway-thread-started:{logical_request_key}:{physical_session_id}")
        return updated


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
        if responsibility.execution_mode is not None and responsibility.execution_mode not in {"continue_existing", "fresh_bounded_worker", "fresh_bounded_role"}:
            return {"code": "unsupported_execution_mode", "message": "execution mode is not supported"}
        if responsibility.require_host_attestation and responsibility.execution_mode not in {"continue_existing", "fresh_bounded_worker", "fresh_bounded_role"}:
            return {"code": "attestation_mode_mismatch", "message": "host attestation requires an explicit execution mode"}
        if responsibility.resource_evidence is not None and responsibility.assignment_ref is None:
            return {"code": "invalid_resource_evidence", "message": "resource evidence requires an assignment reference"}
        if responsibility.resource_evidence is not None and responsibility.assignment_ref is not None:
            try:
                validate_resource_evidence(
                    responsibility.resource_evidence,
                    responsibility_ref=responsibility.assignment_ref,
                    generation=responsibility.generation,
                )
            except ResourceSyncError as exc:
                return {"code": "invalid_resource_evidence", "message": str(exc)}
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
        resource_evidence = _json_value(responsibility.resource_evidence)
        if isinstance(resource_evidence, Mapping):
            resource_evidence = dict(resource_evidence)
            resource_evidence.pop("delivery_state", None)
            resource_evidence.pop("native_identity", None)
        material = {
            "operation": responsibility.operation,
            "owner": responsibility.owner,
            "logical_agent_id": responsibility.logical_agent_id,
            "packet_digest": responsibility.packet_digest,
            "project_ref": _json_value(responsibility.project_ref),
            "task_ref": _json_value(responsibility.task_ref),
            "assignment_ref": _json_value(responsibility.assignment_ref),
            "generation": responsibility.generation,
            "execution_mode": responsibility.execution_mode,
            "requested_profile": responsibility.requested_profile,
            "requested_model": responsibility.requested_model,
            "requested_reasoning": responsibility.requested_reasoning,
            "resource_evidence": resource_evidence,
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
        resource_evidence = _json_value(responsibility.resource_evidence)
        if isinstance(resource_evidence, Mapping):
            resource_evidence = dict(resource_evidence)
            resource_evidence["delivery_state"] = self._resource_delivery_state(delivery_state, outcome)
            if physical is not None:
                resource_evidence["native_identity"] = physical
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
            False,
            resource_evidence,
        )

    @staticmethod
    def _resource_delivery_state(value: Any, outcome: str) -> str:
        observed = str(value).strip().lower() if value is not None else ""
        if observed in DELIVERY_STATES:
            return observed
        if observed in {"done", "success", "succeeded", "complete", "completed"} or outcome == "succeeded":
            return "completed"
        if observed in {"sent", "delivered", "submitted"}:
            return "observed_delivered"
        if observed in {"started", "active"}:
            return "running"
        return "prepared"

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
        envelope_value = envelope.to_dict()
        if isinstance(result, Mapping):
            for field_name in ("task_bound_evidence", "transport_result", "raw_result"):
                if field_name in result:
                    envelope_value[field_name] = _json_value(result[field_name])
        if self.attempt_capture is not None:
            self.attempt_capture.record(envelope_value)
        if isinstance(result, Mapping):
            attached = dict(result)
            attached["attempt"] = envelope_value
            attached["envelope"] = envelope_value
            return attached
        return {"outcome": envelope.outcome, "result": result,
                "attempt": envelope_value, "envelope": envelope_value}

    def _enforce_host_attestation(self, responsibility: Responsibility, result: Any, request: Any = None) -> tuple[Any, Optional[str]]:
        """Fail closed when a fresh success has no trusted host attestation."""

        if not responsibility.require_host_attestation:
            return result, None
        observed_outcome = self._nested_value(result, ("outcome",))
        observed_outcome = getattr(observed_outcome, "value", observed_outcome)
        if str(observed_outcome) != "succeeded":
            return result, None
        worker_content = self._nested_value(result, ("worker_content",))
        if isinstance(worker_content, (str, bytes)):
            worker_content = [worker_content]
        if isinstance(worker_content, (list, tuple)) and any(
            "no operation was performed" in str(item).lower() for item in worker_content
        ):
            message = "host transport succeeded but the worker reported that no operation was performed"
            transport_result = _json_value(result)
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "done",
                "retry_allowed": False,
                "error": {"code": "worker_no_operation", "message": message},
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        task_evidence = self._nested_value(result, ("task_bound_evidence",))
        transport_result = _json_value(result)
        request_value = _json_value(request)
        contract = request_value.get("resource_brief", {}).get("instruction_contract") if isinstance(request_value, Mapping) else None
        if not isinstance(contract, Mapping) and isinstance(responsibility.resource_evidence, Mapping):
            resource_brief = responsibility.resource_evidence.get("brief")
            if isinstance(resource_brief, Mapping):
                contract = resource_brief.get("instruction_contract")
        strict_contract = isinstance(contract, Mapping)
        linked_context_read = strict_contract and contract.get("read_scope") == "linked_context"
        if not isinstance(task_evidence, Mapping):
            message = "successful host result lacks positive task-bound operation evidence"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {"code": "task_bound_evidence_required", "message": message},
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        expected_task = _json_value(responsibility.task_ref)
        observed_task = _json_value(task_evidence.get("task_ref"))
        observed_operation = task_evidence.get("operation")
        observed_session = task_evidence.get("session_id") or task_evidence.get("physical_session_id")
        observed_turn = task_evidence.get("turn_id")
        returned_turn = self._nested_value(result, ("observed_turn_id", "turn_id"))
        observed_context_digest = task_evidence.get("context_digest")
        returned_context_digest = self._nested_value(result, ("observed_context_digest",))
        if (
            observed_task != expected_task
            or observed_operation != responsibility.operation
            or observed_session != self._nested_value(result, ("physical_session_id", "native_session_id"))
            or not _text(observed_turn)
            or (strict_contract and returned_turn != observed_turn)
            or task_evidence.get("provenance") != (
                "host_final_answer/item_completed" if linked_context_read
                else "host_command_execution/item_completed"
            )
            or (strict_contract and not _sha256_hex(observed_context_digest))
            or (strict_contract and returned_context_digest != observed_context_digest)
            or (strict_contract and result.get("context_digest_verified") is not True)
        ):
            message = "task-bound operation evidence does not match the fenced responsibility"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {
                    "code": "task_bound_evidence_mismatch",
                    "message": message,
                    "expected_task_ref": expected_task,
                    "observed_task_ref": observed_task,
                    "expected_operation": responsibility.operation,
                    "observed_operation": observed_operation,
                    "observed_session_id": observed_session,
                    "observed_turn_id": observed_turn,
                    "returned_turn_id": returned_turn,
                    "observed_context_digest": observed_context_digest,
                },
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        if not strict_contract:
            observed_model = self._nested_value(result, ("observed_model", "model", "model_name"))
            observed_reasoning = self._nested_value(result, ("observed_reasoning", "reasoning_effort", "reasoning"))
            if not _text(observed_model) or not _text(observed_reasoning):
                message = "successful host result lacks trusted observed model/reasoning attestation"
                return {
                    "outcome": "undetermined",
                    "status": "unsupported",
                    "delivery_state": "unknown",
                    "error": {"code": "observed_host_attestation_unavailable", "message": message},
                    "observed_model": observed_model,
                    "observed_reasoning": observed_reasoning,
                    "transport_result": transport_result,
                    "raw_result": transport_result,
                }, message
            if observed_model != responsibility.requested_model or observed_reasoning != responsibility.requested_reasoning:
                message = "observed host model/reasoning does not match the requested configuration"
                return {
                    "outcome": "undetermined",
                    "status": "unsupported",
                    "delivery_state": "unknown",
                    "error": {
                        "code": "observed_host_attestation_mismatch",
                        "message": message,
                        "requested_model": responsibility.requested_model,
                        "requested_reasoning": responsibility.requested_reasoning,
                        "observed_model": observed_model,
                        "observed_reasoning": observed_reasoning,
                    },
                    "transport_result": transport_result,
                    "raw_result": transport_result,
                }, message
            return result, None
        evidence_digest = task_evidence.get("evidence_digest")
        if not _sha256_hex(evidence_digest):
            message = "task-bound operation evidence lacks an exact evidence digest"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {"code": "task_bound_evidence_digest_required", "message": message},
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        evidence_without_digest = dict(_json_value(task_evidence))
        evidence_without_digest.pop("evidence_digest", None)
        if evidence_digest.lower() != _sha256_json(evidence_without_digest):
            message = "task-bound operation evidence digest does not match attested bytes"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {"code": "task_bound_evidence_digest_mismatch", "message": message},
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        assignment_ref = task_evidence.get("assignment_ref")
        generation = task_evidence.get("generation")
        if assignment_ref != _json_value(responsibility.assignment_ref) or generation != responsibility.generation:
            message = "task-bound operation evidence does not match the fenced assignment generation"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {
                    "code": "task_bound_assignment_mismatch",
                    "message": message,
                    "expected_assignment_ref": _json_value(responsibility.assignment_ref),
                    "observed_assignment_ref": assignment_ref,
                    "expected_generation": responsibility.generation,
                    "observed_generation": generation,
                },
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        delivered_contract_digest = task_evidence.get("delivered_contract_digest")
        if not isinstance(contract, Mapping) or not _sha256_hex(delivered_contract_digest) or delivered_contract_digest.lower() != _sha256_json(contract):
            message = "task-bound operation evidence lacks the exact delivered instruction contract digest"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {"code": "delivered_contract_digest_mismatch", "message": message},
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        result_ref = task_evidence.get("result_ref")
        result_digest = task_evidence.get("result_digest")
        read_targets = task_evidence.get("read_targets")
        expected_read_targets = contract.get("read_targets") if isinstance(contract, Mapping) else None
        operation_result = task_evidence.get("operation_result")
        if (
            not isinstance(result_ref, (str, Mapping))
            or not result_ref
            or not _sha256_hex(result_digest)
            or not isinstance(read_targets, list)
            or (not linked_context_read and not read_targets)
            or (strict_contract and not linked_context_read and not isinstance(expected_read_targets, list))
            or (strict_contract and not linked_context_read and read_targets != _json_value(expected_read_targets))
            or not isinstance(operation_result, Mapping)
            or operation_result.get("status") != "completed"
            or operation_result.get("result_ref") != result_ref
            or operation_result.get("result_digest") != result_digest
            or "output" not in operation_result
            or result_digest.lower() != _sha256_json(operation_result.get("output"))
        ):
            message = "task-bound operation evidence lacks a completed read result and exact targets"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "retry_allowed": False,
                "error": {"code": "task_result_evidence_required", "message": message},
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        if linked_context_read:
            final = operation_result.get("output", {}).get("final_answer")
            final_ref = task_evidence.get("host_records", {}).get("final_answer")
            if (
                not isinstance(final, Mapping)
                or not isinstance(final.get("text"), str)
                or not final["text"].strip()
                or final.get("host_record") != final_ref
                or not isinstance(final_ref, Mapping)
                or final_ref.get("item_type") != "AgentMessage"
                or final_ref.get("event_type") != "item_completed"
            ):
                message = "linked-context result lacks an exact native final answer"
                return {
                    "outcome": "undetermined", "status": "unsupported",
                    "delivery_state": "unknown", "retry_allowed": False,
                    "error": {"code": "linked_context_final_required", "message": message},
                    "transport_result": transport_result, "raw_result": transport_result,
                }, message
        observed_model = self._nested_value(result, ("observed_model", "model", "model_name"))
        observed_reasoning = self._nested_value(result, ("observed_reasoning", "reasoning_effort", "reasoning"))
        if not _text(observed_model) or not _text(observed_reasoning):
            message = "successful host result lacks trusted observed model/reasoning attestation"
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "error": {"code": "observed_host_attestation_unavailable", "message": message},
                "observed_model": observed_model,
                "observed_reasoning": observed_reasoning,
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        if observed_model != responsibility.requested_model or observed_reasoning != responsibility.requested_reasoning:
            message = "observed host model/reasoning does not match the requested configuration"
            transport_result = _json_value(result)
            return {
                "outcome": "undetermined",
                "status": "unsupported",
                "delivery_state": "unknown",
                "error": {
                    "code": "observed_host_attestation_mismatch",
                    "message": message,
                    "requested_model": responsibility.requested_model,
                    "requested_reasoning": responsibility.requested_reasoning,
                    "observed_model": observed_model,
                    "observed_reasoning": observed_reasoning,
                },
                "transport_result": transport_result,
                "raw_result": transport_result,
            }, message
        return result, None

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
            if prior.get("outcome") == "unknown" or prior.get("delivery_state") == "unknown":
                return error("unknown_attempt_requires_reconciliation",
                             "an unresolved attempt cannot be retried automatically")
            prior["replayed"] = True
            return {"outcome": "replayed", "replayed": True, "adapter_called": False,
                    "attempt": prior, "envelope": prior}
        unresolved = self._capture_read("read_assignment", responsibility.assignment_ref, int(responsibility.generation or 0))
        if unresolved is not None and unresolved.get("outcome") == "unknown":
            return error("unknown_attempt_requires_reconciliation",
                         "an unresolved attempt for this assignment generation cannot be retried")
        resource_validator = getattr(self.attempt_capture, "validate_resources", None)
        if callable(resource_validator):
            resource_error = resource_validator(responsibility.resource_evidence)
            if resource_error:
                return error("stale_resource_adoption", resource_error)
        claimer = getattr(self.attempt_capture, "claim", None) if self.attempt_capture is not None else None
        if callable(claimer):
            claim = claimer(key, responsibility.assignment_ref, int(responsibility.generation or 0), fingerprint)
            outcome = claim.get("outcome") if isinstance(claim, Mapping) else None
            if outcome == "replayed":
                attempt = claim.get("attempt")
                return {"outcome": "replayed", "replayed": True, "adapter_called": False,
                        "attempt": attempt, "envelope": attempt}
            if outcome == "unknown":
                return error("unknown_attempt_requires_reconciliation", str(claim.get("message", "owner claim is unresolved")))
            if outcome == "request_reuse_conflict":
                return error("request_reuse_conflict", str(claim.get("message", "owner claim input changed")))
            if outcome == "stale_generation":
                return error("stale_generation", str(claim.get("message", "owner claim generation is stale")))
            if outcome == "foreign_assignment":
                return error("foreign_assignment", str(claim.get("message", "owner claim assignment does not match")))
            if outcome == "foreign_scope":
                return error("foreign_scope", str(claim.get("message", "owner claim scope does not match")))
            if outcome == "foreign_authority":
                return error("foreign_authority", str(claim.get("message", "owner claim authority does not match")))
            if outcome == "stale_claim":
                return error("stale_claim", str(claim.get("message", "owner CAS rejected the claim")))
            if outcome == "claimed" and claim.get("claimed") is False:
                return error("unknown_attempt_requires_reconciliation", "an owner claim is already pending")
            if outcome != "claimed":
                return error("owner_claim_rejected", "owner did not grant the launch claim")
        return None

    @staticmethod
    def _bind_resource_request(
        responsibility: Responsibility, request: Any
    ) -> tuple[Any, Optional[dict[str, Any]]]:
        """Require the exact owner-composed resource brief at the adapter edge."""

        if responsibility.resource_evidence is None or responsibility.operation not in {"invoke", "resume", "send"}:
            return request, None
        if not isinstance(request, Mapping):
            return request, {"code": "resource_request_unbound", "message": "resource-aware requests must be mappings"}
        request_copy = dict(request)
        evidence = responsibility.resource_evidence
        if not isinstance(evidence, Mapping) or not isinstance(evidence.get("brief"), Mapping) or not _text(evidence.get("brief_sha256")):
            return request, {"code": "invalid_resource_evidence", "message": "resource evidence has no immutable brief binding"}
        supplied_brief = request_copy.get("resource_brief")
        supplied_digest = request_copy.get("resource_brief_sha256")
        if supplied_brief != evidence["brief"] or supplied_digest != evidence["brief_sha256"]:
            return request, {"code": "resource_request_unbound", "message": "adapter request does not carry the exact verified resource brief"}
        for field, expected in {
            "logical_agent_id": responsibility.logical_agent_id,
            "physical_session_id": responsibility.physical_session_id,
            "requested_profile": responsibility.requested_profile,
            "requested_model": responsibility.requested_model,
            "requested_reasoning": responsibility.requested_reasoning,
            "target_ref": responsibility.task_ref,
        }.items():
            if field in request_copy and request_copy[field] is not None and _json_value(request_copy[field]) != _json_value(expected):
                return request, {"code": "resource_request_unbound", "message": f"adapter request {field} conflicts with the fenced responsibility"}
        # Preserve caller ownership: any future enrichment happens on this
        # copy, while the resource-aware adapter remains responsible for
        # requiring the typed fields it needs at its own boundary.
        return request_copy, None

    def operation(self, responsibility: Responsibility, request: Any) -> Any:
        failure = self.preflight(responsibility)
        if failure:
            return {"outcome": "error", "error": failure}
        request, resource_failure = self._bind_resource_request(responsibility, request)
        if resource_failure:
            return {"outcome": "error", "error": resource_failure}
        if responsibility.operation == "resume":
            request_physical_session_id = self._nested_value(
                request, ("physical_session_id", "native_session_id")
            )
            if not _text(request_physical_session_id):
                return error(
                    "physical_session_required",
                    "resume request must carry an explicit physical session identity",
                )
            if request_physical_session_id != responsibility.physical_session_id:
                return error(
                    "physical_session_mismatch",
                    "resume request identity does not match the responsibility physical session",
                    responsibility_physical_session_id=responsibility.physical_session_id,
                    request_physical_session_id=request_physical_session_id,
                )
        owner_bound = self._owner_binding_required(responsibility)
        if owner_bound and responsibility.operation != "inspect":
            prior = self._owner_bound_operation(responsibility, request)
            if prior is not None:
                return prior
        key = responsibility.logical_request_key
        method = getattr(self.adapter, responsibility.operation, None)
        if method is None:
            result = error("unsupported_operation", f"adapter does not support {responsibility.operation}")
            if owner_bound and responsibility.operation != "inspect":
                return self._attach_attempt(responsibility, request, {
                    "outcome": "unsupported",
                    "error": result["error"],
                })
            return result
        restore_thread_callback = None
        callback_installed = False
        setter = getattr(self.adapter, "set_thread_started_callback", None)
        recorder = getattr(self.attempt_capture, "record_thread_started", None) if self.attempt_capture is not None else None
        if owner_bound and responsibility.operation != "inspect" and key and callable(setter) and callable(recorder):
            prior_callback = setter(None)

            def on_thread_started(physical_session_id: str) -> None:
                recorder(
                    key, physical_session_id,
                    process_created=responsibility.operation == "invoke",
                )
                if callable(prior_callback):
                    prior_callback(physical_session_id)

            setter(on_thread_started)
            restore_thread_callback = prior_callback
            callback_installed = True
        try:
            result = method(request)
            result, attestation_error = self._enforce_host_attestation(responsibility, result, request)
        except Exception as exc:
            if owner_bound and responsibility.operation != "inspect":
                return self._attach_attempt(responsibility, request,
                                            error("adapter_error", str(exc), operation=responsibility.operation),
                                            error_message=str(exc))
            return error("adapter_error", str(exc), operation=responsibility.operation)
        finally:
            if callback_installed and callable(setter):
                setter(restore_thread_callback)
        return self._attach_attempt(
            responsibility, request, result, error_message=attestation_error
        ) if owner_bound and responsibility.operation != "inspect" else result

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


def _occurrence_rejection(stage: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    value = error(code, message, stage=stage, adapter_called=False, **details)
    value["automatic_action"] = False
    return value


def _unsupported_occurrence(stage: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    value = _occurrence_rejection(stage, code, message, **details)
    value.update({"outcome": "undetermined", "status": "unsupported"})
    return value


def _read_assignment(reader: Any, assignment_ref: Any) -> Any:
    """Read one exact assignment through a callable or public ``get`` port."""

    if callable(reader):
        return reader(assignment_ref)
    getter = getattr(reader, "get", None)
    if not callable(getter):
        raise TypeError("assignment reader must be callable or expose get")
    target = assignment_ref
    try:
        from herzchen.contracts import ResourceRef

        if isinstance(assignment_ref, Mapping):
            target = ResourceRef.from_dict(dict(assignment_ref))
    except (ImportError, TypeError, ValueError):
        pass
    return getter(target)


def _assignment_value(assignment: Any, *names: str) -> Any:
    if isinstance(assignment, Mapping):
        for name in names:
            if name in assignment:
                return assignment[name]
        return None
    for name in names:
        value = getattr(assignment, name, None)
        if value is not None:
            return value
    return None


def run_due_occurrence(
    due_port: Any,
    attention: Any,
    gateway: OttoGateway,
    responsibility: Responsibility,
    request: Any,
    *,
    schedule_id: str,
    capability_evidence: Mapping[str, Any],
    context_evidence: tuple[Mapping[str, Any], ...] = (),
    allowance_evidence: Optional[Mapping[str, Any]] = None,
    assignment_reader: Any = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one already-due occurrence through existing owner ports.

    This is a finite composition boundary: it reads one owner record,
    validates its requested configuration and exact assignment, then lets the
    injected owner-bound gateway claim and invoke once.  The gateway's
    ``DueRecordAttemptCapture`` persists the claim before the adapter call and
    the normalized result, including an explicit unknown state, afterward.
    There is no scheduling, retry, or native launch in this function.
    """

    if not _text(schedule_id):
        return _occurrence_rejection("read", "schedule_id_required", "schedule_id is required")
    if due_port is None or not callable(getattr(due_port, "read_due", None)):
        return _occurrence_rejection("read", "due_port_required", "a public DueRecordPort is required")
    if not isinstance(gateway, OttoGateway):
        return _occurrence_rejection("invoke", "gateway_required", "an injected OttoGateway is required")
    capture = gateway.attempt_capture
    if not isinstance(capture, DueRecordAttemptCapture) or capture.due_port is not due_port or capture.schedule_id != schedule_id:
        return _occurrence_rejection("claim", "durable_claim_required", "gateway must use the DueRecordAttemptCapture for this schedule")
    raw_record = due_port.read_due(schedule_id)
    if raw_record is None:
        return {"outcome": "unknown", "schedule_id": schedule_id, "stage": "read", "adapter_called": False, "automatic_action": False}
    try:
        from otto.attention import DueRecord

        record = DueRecord.from_dict(raw_record)
    except (TypeError, ValueError) as exc:
        return _occurrence_rejection("read", "invalid_due_record", str(exc))

    if not DueRecordAttemptCapture._same(record.assignment_ref, responsibility.assignment_ref):
        return _occurrence_rejection("assignment", "foreign_assignment", "responsibility assignment does not match the due record")
    if record.project_ref != responsibility.project_ref:
        return _occurrence_rejection("assignment", "foreign_scope", "responsibility project does not match the due record")
    if record.generation != responsibility.generation:
        return _occurrence_rejection("assignment", "stale_generation", "responsibility generation does not match the due record")
    if assignment_reader is None:
        return _occurrence_rejection("assignment", "assignment_reader_required", "exact current assignment resolution requires the public assignment reader")

    configuration = attention.validate_configuration(
        schedule_id,
        capability_evidence=capability_evidence,
        context_evidence=context_evidence,
        allowance_evidence=allowance_evidence,
        expected_version=record.version,
        project_ref=record.project_ref,
        manager_ref=record.manager_ref,
        generation=record.generation,
        lifecycle_owner=responsibility.owner,
    )
    if configuration.get("outcome") != "configuration_supported":
        result = dict(configuration)
        result.update({"stage": "configuration", "adapter_called": False, "automatic_action": False})
        return result

    resolution = attention.resolve_recipient(
        schedule_id,
        recipient=record.recipient,
        role=record.role,
        project_ref=record.project_ref,
        manager_ref=record.manager_ref,
        generation=record.generation,
        lifecycle_owner=responsibility.owner,
        assignment_reader=assignment_reader,
    )
    if resolution.get("outcome") != "resolved":
        result = dict(resolution)
        result.update({"stage": "assignment", "adapter_called": False, "automatic_action": False})
        return result

    if dry_run:
        return {
            "outcome": "bound",
            "status": "ready",
            "schedule_id": schedule_id,
            "stage": "bound",
            "adapter_called": False,
            "automatic_action": False,
            "due_occurrence": {
                "schedule_id": schedule_id,
                "configuration": configuration,
                "resolution": resolution,
                "attempt_state": None,
                "persisted": False,
                "native_activation": False,
            },
        }

    invoked = gateway.invoke(responsibility, request)
    result = dict(_json_value(invoked)) if isinstance(invoked, Mapping) else {"outcome": "unknown", "result": _json_value(invoked)}
    if result.get("outcome") == "succeeded" and responsibility.execution_mode in {"continue_existing", "fresh_bounded_worker", "fresh_bounded_role"} and responsibility.require_host_attestation:
        manager_acceptance = capture.accept_result(responsibility.logical_request_key or "", manager_actor=responsibility.owner)
    else:
        manager_acceptance = {
            "outcome": "not_accepted",
            "status": "undetermined",
            "reason": "manager acceptance requires a trusted attested fresh result",
        }
    persisted = due_port.read_due(schedule_id)
    evidence = persisted.get("host_evidence") if isinstance(persisted, Mapping) else None
    attempt = evidence.get("gateway_attempt") if isinstance(evidence, Mapping) else None
    result["due_occurrence"] = {
        "schedule_id": schedule_id,
        "configuration": configuration,
        "resolution": resolution,
        "attempt_state": attempt.get("state") if isinstance(attempt, Mapping) else None,
        "persisted": isinstance(attempt, Mapping),
        "manager_acceptance": manager_acceptance,
        "automatic_action": False,
    }
    return result


MO02B_SLOT3_REQUEST_KEY = "4624b0c1316b36d5aa2d5798f46b3a5b1254d24dc327ed787df17e624bd98268"


def continue_admitted_occurrence(
    due_port: Any,
    attention: Any,
    gateway: OttoGateway,
    responsibility: Responsibility,
    request: Any,
    *,
    schedule_id: str,
    expected_packet_digest: str,
    expected_allowance_ref: Mapping[str, Any],
    expected_worker_assignment: Mapping[str, Any],
    capability_evidence: Mapping[str, Any],
    context_evidence: tuple[Mapping[str, Any], ...] = (),
    allowance_evidence: Optional[Mapping[str, Any]] = None,
    assignment_reader: Any = None,
    native_capability: Optional[Mapping[str, Any]] = None,
    resource_evidence: Optional[Mapping[str, Any]] = None,
    expected_request_key: str = MO02B_SLOT3_REQUEST_KEY,
) -> dict[str, Any]:
    """Continue one already-admitted occurrence through one guarded dispatch.

    The preflight remains read-only and fail-closed.  Only after the exact
    occurrence, current assignment, configuration, allowance, and capability
    checks pass does it delegate once to ``run_due_occurrence``.  That call
    uses the existing ``DueRecordAttemptCapture`` claim/result/acceptance
    machinery; it is not a new admission or scheduler operation.
    """

    if not _text(schedule_id) or not _text(expected_request_key):
        return _occurrence_rejection("bind", "continuation_identity_required", "schedule_id and expected_request_key are required")
    if not isinstance(gateway, OttoGateway):
        return _occurrence_rejection("bind", "gateway_required", "an injected OttoGateway is required")
    capture = gateway.attempt_capture
    if not isinstance(capture, DueRecordAttemptCapture) or capture.due_port is not due_port or capture.schedule_id != schedule_id:
        return _occurrence_rejection("bind", "durable_claim_required", "continuation requires the existing DueRecordAttemptCapture for this schedule")
    raw_record = due_port.read_due(schedule_id)
    if raw_record is None:
        return {"outcome": "unknown", "status": "undetermined", "stage": "read", "adapter_called": False, "automatic_action": False, "reason": "due_record_missing"}
    try:
        from otto.attention import DueRecord

        record = DueRecord.from_dict(raw_record)
    except (TypeError, ValueError) as exc:
        return _occurrence_rejection("read", "invalid_due_record", str(exc))

    if resource_evidence is not None:
        if responsibility.resource_evidence is not None and not capture._same(responsibility.resource_evidence, resource_evidence):
            return _occurrence_rejection("resource", "resource_evidence_conflict", "continuation resource evidence conflicts with the responsibility")
        responsibility = replace(responsibility, resource_evidence=resource_evidence)
    elif responsibility.resource_evidence is None and isinstance(request, Mapping) and isinstance(request.get("resource_evidence"), Mapping):
        responsibility = replace(responsibility, resource_evidence=request["resource_evidence"])
    if responsibility.resource_evidence is not None:
        try:
            validate_resource_evidence(
                responsibility.resource_evidence,
                responsibility_ref=expected_worker_assignment,
                generation=responsibility.generation,
            )
        except ResourceSyncError as exc:
            return _occurrence_rejection("resource", "invalid_resource_evidence", str(exc))

    if responsibility.logical_request_key != expected_request_key:
        return _occurrence_rejection("bind", "request_reuse_conflict", "continuation request key is not the admitted slot-3 key", expected_request_key=expected_request_key)
    if responsibility.packet_digest != expected_packet_digest:
        return _occurrence_rejection("bind", "packet_conflict", "continuation packet digest does not match the admitted packet")
    if record.generation != responsibility.generation:
        return _occurrence_rejection("bind", "stale_generation", "manager generation is stale")
    if responsibility.requested_profile != record.profile:
        return _occurrence_rejection("configuration", "profile_conflict", "continuation profile does not match the admitted occurrence")
    if record.assignment_ref is None or not capture._same(record.assignment_ref, expected_worker_assignment) or not capture._same(record.assignment_ref, responsibility.assignment_ref):
        return _occurrence_rejection("bind", "foreign_assignment", "worker assignment does not match the admitted occurrence")
    if record.allowance_ref is None or not capture._same(record.allowance_ref, expected_allowance_ref):
        return _occurrence_rejection("bind", "allowance_conflict", "allowance reference does not match the admitted occurrence")
    if record.in_flight_request is not None and record.in_flight_request != expected_request_key:
        return _occurrence_rejection("bind", "competing", "another admitted request is already in flight", competing_request_key=record.in_flight_request)
    evidence = record.host_evidence if isinstance(record.host_evidence, Mapping) else {}
    admitted_packet = evidence.get("packet_digest") or evidence.get("admitted_packet_digest")
    if admitted_packet is not None and admitted_packet != expected_packet_digest:
        return _occurrence_rejection("bind", "packet_conflict", "due record packet evidence does not match the admitted packet")

    if assignment_reader is None:
        return _occurrence_rejection("assignment", "assignment_reader_required", "exact current worker assignment resolution requires the public assignment reader")
    try:
        current_assignment = _read_assignment(assignment_reader, expected_worker_assignment)
    except Exception as exc:
        return _occurrence_rejection("assignment", "assignment_unavailable", str(exc))
    if current_assignment is None:
        return _occurrence_rejection("assignment", "assignment_unavailable", "current worker assignment is unavailable")
    current_assignment_value = _json_value(current_assignment)
    current_generation = current_assignment_value.get("generation") if isinstance(current_assignment_value, Mapping) else None
    current_assignment_ref = current_assignment_value.get("assignment_ref", current_assignment_value.get("ref")) if isinstance(current_assignment_value, Mapping) else None
    if current_generation != responsibility.generation or not capture._same(current_assignment_ref, expected_worker_assignment):
        return _occurrence_rejection("assignment", "stale_generation", "current worker assignment no longer matches the admitted generation")

    dry = run_due_occurrence(
        due_port,
        attention,
        gateway,
        responsibility,
        request,
        schedule_id=schedule_id,
        capability_evidence=capability_evidence,
        context_evidence=context_evidence,
        allowance_evidence=allowance_evidence,
        assignment_reader=assignment_reader,
        dry_run=True,
    )
    if dry.get("outcome") != "bound":
        dry["continuation"] = True
        return dry

    attempt = capture._attempt(record)
    fingerprint = gateway._fingerprint(responsibility, request)
    if attempt is not None:
        if attempt.get("logical_request_key") != expected_request_key:
            return _occurrence_rejection("claim", "competing", "a different request owns the existing occurrence claim", competing_request_key=attempt.get("logical_request_key"))
        if attempt.get("request_fingerprint") != fingerprint:
            return _occurrence_rejection("claim", "request_reuse_conflict", "continuation input changed after admission")
        if attempt.get("state") == "result":
            result = attempt.get("result") if isinstance(attempt.get("result"), Mapping) else {}
            if result.get("outcome") == "unknown" or result.get("delivery_state") == "unknown":
                return {"outcome": "unknown", "status": "undetermined", "stage": "result", "adapter_called": False, "automatic_action": False, "retry_allowed": False, "attempt": attempt}
            return {"outcome": "replayed", "status": "completed", "stage": "result", "replayed": True, "adapter_called": False, "automatic_action": False, "attempt": attempt, "result": result}
        if attempt.get("state") == "claimed":
            return {"outcome": "pending", "status": "pending", "stage": "claim", "adapter_called": False, "automatic_action": False, "retry_allowed": False, "attempt": attempt}

    operation = "resume" if record.execution_mode == "continue_existing" else "invoke"
    capability = native_capability if isinstance(native_capability, Mapping) else {}
    supported = capability.get("available") is True or capability.get("state") in {"available", "supported"}
    operation_support = capability.get(operation)
    if isinstance(operation_support, bool):
        supported = supported and operation_support
    if not supported:
        return {"outcome": "undetermined", "status": "unsupported", "stage": "native_capability", "adapter_called": False, "automatic_action": False, "retry_allowed": False, "error": {"code": "native_capability_unavailable", "message": "native continuation capability is unavailable"}, "bound": dry}
    dispatch_responsibility = responsibility
    if not responsibility.require_host_attestation:
        dispatch_responsibility = replace(responsibility, require_host_attestation=True)
    result = run_due_occurrence(
        due_port,
        attention,
        gateway,
        dispatch_responsibility,
        request,
        schedule_id=schedule_id,
        capability_evidence=capability_evidence,
        context_evidence=context_evidence,
        allowance_evidence=allowance_evidence,
        assignment_reader=assignment_reader,
        dry_run=False,
    )
    if result.get("outcome") == "unknown" or result.get("delivery_state") == "unknown":
        result["retry_allowed"] = False
    result["continuation"] = True
    return result


def run_scheduled_callback(
    callback: Mapping[str, Any],
    *,
    due_port: Any,
    attention: Any,
    gateway: OttoGateway,
    assignment_reader: Any,
) -> dict[str, Any]:
    """Bind one already-authorized host callback to one due occurrence.

    The callback is an input contract, not a scheduler.  It must carry the
    callback identity, current owner version, owner actor, correlation, exact
    assignment/scope pins, requested model, and versioned evidence.  The
    existing occurrence runner remains responsible for configuration,
    assignment resolution, claim-before-invoke, and replay/unknown handling.
    """

    if not isinstance(callback, Mapping):
        return _occurrence_rejection("callback", "callback_object_required", "callback payload must be an object")
    if callback.get("contract") != "otto.scheduled-callback.v1":
        return _occurrence_rejection("callback", "unsupported_callback", "callback contract is not supported")
    if callback.get("enabled") is not True:
        return _occurrence_rejection("callback", "callback_disabled", "callback is disabled")
    execution_mode = callback.get("execution_mode")
    if execution_mode not in {"continue_existing", "fresh_bounded_worker", "fresh_bounded_role"}:
        return _occurrence_rejection("callback", "execution_mode_required", "callback.execution_mode must be explicit")
    required_text_fields = (
        "callback_id", "schedule_id", "owner_actor", "correlation_id", "logical_request_key",
        "logical_agent_id", "packet_digest", "project_ref", "manager_ref", "role", "recipient",
        "model", "reasoning", "profile",
    )
    for field_name in required_text_fields:
        if not _text(callback.get(field_name)):
            return _occurrence_rejection("callback", "callback_field_required", f"callback.{field_name} is required", field=field_name)
    if isinstance(callback.get("owner_version"), bool) or not isinstance(callback.get("owner_version"), int) or callback["owner_version"] < 0:
        return _occurrence_rejection("callback", "owner_version_required", "callback.owner_version must be a non-negative integer")
    if isinstance(callback.get("generation"), bool) or not isinstance(callback.get("generation"), int) or callback["generation"] < 1:
        return _occurrence_rejection("callback", "generation_required", "callback.generation must be a positive integer")
    if not isinstance(callback.get("assignment_ref"), Mapping):
        return _occurrence_rejection("callback", "assignment_ref_required", "callback.assignment_ref is required")
    if not isinstance(callback.get("task_ref"), Mapping):
        return _occurrence_rejection("callback", "task_ref_required", "callback.task_ref is required")
    if "request" not in callback:
        return _occurrence_rejection("callback", "request_required", "callback.request is required")
    capability_evidence = callback.get("capability_evidence")
    context_evidence = callback.get("context_evidence")
    allowance_evidence = callback.get("allowance_evidence")
    resource_evidence = callback.get("resource_evidence")
    if resource_evidence is None and isinstance(callback.get("request"), Mapping):
        nested_resource_evidence = callback["request"].get("resource_evidence")
        if isinstance(nested_resource_evidence, Mapping):
            resource_evidence = nested_resource_evidence
    if not isinstance(capability_evidence, Mapping) or not isinstance(context_evidence, (list, tuple)) or not isinstance(allowance_evidence, Mapping):
        return _occurrence_rejection("callback", "callback_evidence_required", "capability, context, and allowance evidence are required")
    if resource_evidence is not None:
        try:
            validate_resource_evidence(
                resource_evidence,
                responsibility_ref=callback["assignment_ref"],
                generation=callback["generation"],
            )
        except ResourceSyncError as exc:
            return _occurrence_rejection("callback", "invalid_resource_evidence", str(exc))
    raw_record = due_port.read_due(callback["schedule_id"]) if callable(getattr(due_port, "read_due", None)) else None
    if raw_record is None:
        return {"outcome": "unknown", "stage": "callback", "automatic_action": False, "adapter_called": False}
    try:
        from otto.attention import DueRecord

        record = DueRecord.from_dict(raw_record)
    except (TypeError, ValueError) as exc:
        return _occurrence_rejection("callback", "invalid_due_record", str(exc))
    target = record.target if isinstance(record.target, Mapping) else {}
    automation = target.get("automation") if isinstance(target.get("automation"), Mapping) else {}
    expected_callback_id = target.get("automation_id") or target.get("automationId") or automation.get("id") or target.get("native_id") or target.get("id")
    if not _text(expected_callback_id):
        return _occurrence_rejection("callback", "callback_identity_missing", "due record has no persisted callback identity")
    if callback["callback_id"] != expected_callback_id:
        return _occurrence_rejection("callback", "callback_identity_mismatch", "callback identity does not match the due record")
    if callback["owner_version"] != record.version:
        return _occurrence_rejection("callback", "stale_callback", "callback owner version is stale", expected_version=record.version)
    if callback["owner_actor"] != record.lifecycle_owner:
        return _occurrence_rejection("callback", "foreign_authority", "callback owner actor is not the lifecycle owner")
    if callback["project_ref"] != record.project_ref or callback["manager_ref"] != record.manager_ref:
        return _occurrence_rejection("callback", "foreign_scope", "callback scope does not match the due record")
    if callback["assignment_ref"] != record.assignment_ref:
        return _occurrence_rejection("callback", "foreign_assignment", "callback assignment does not match the due record")
    if callback["generation"] != record.generation:
        return _occurrence_rejection("callback", "stale_generation", "callback generation is stale")
    if callback["role"] != record.role or callback["recipient"] != record.recipient:
        return _occurrence_rejection("callback", "role_recipient_mismatch", "callback role or recipient does not match the due record")
    if callback["model"] != record.requested_model or callback["reasoning"] != record.requested_reasoning:
        return _occurrence_rejection("callback", "configuration_mismatch", "callback model or reasoning does not match the due record")
    if execution_mode != record.execution_mode:
        return _occurrence_rejection("callback", "execution_mode_mismatch", "callback execution mode does not match the due record")
    physical_session_id = callback.get("physical_session_id")
    if execution_mode == "continue_existing" and not _text(physical_session_id):
        return _occurrence_rejection("callback", "physical_session_required", "continue-existing callback requires an explicit physical_session_id")
    if execution_mode in {"fresh_bounded_worker", "fresh_bounded_role"} and physical_session_id is not None:
        return _occurrence_rejection("callback", "fresh_physical_session_forbidden", "fresh callback cannot supply a physical session")
    operation = "resume" if execution_mode == "continue_existing" else "invoke"
    if execution_mode == "continue_existing":
        request_physical_session_id = OttoGateway._nested_value(
            callback["request"], ("physical_session_id", "native_session_id")
        )
        if not _text(request_physical_session_id):
            return _occurrence_rejection(
                "callback", "physical_session_required",
                "continue-existing callback request must carry an explicit physical_session_id",
            )
        if request_physical_session_id != physical_session_id:
            return _occurrence_rejection(
                "callback", "physical_session_mismatch",
                "continue-existing callback physical_session_id does not match request identity",
                callback_physical_session_id=physical_session_id,
                request_physical_session_id=request_physical_session_id,
            )
        request_operation = getattr(callback["request"], "operation", None)
        if getattr(request_operation, "value", request_operation) != "resume":
            return _occurrence_rejection("callback", "resume_request_required", "continue-existing callback requires a public resume HostRequest")
    claim_packet_digest = hashlib.sha256(json.dumps({"packet_digest": callback["packet_digest"], "correlation_id": callback["correlation_id"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    responsibility = Responsibility(
        callback["owner_actor"], callback["logical_agent_id"], operation, claim_packet_digest,
        physical_session_id=physical_session_id,
        requested_profile=callback["profile"], requested_model=callback["model"],
        requested_reasoning=callback["reasoning"], logical_request_key=callback["logical_request_key"],
        project_ref=callback["project_ref"], task_ref=callback["task_ref"],
        assignment_ref=callback["assignment_ref"], generation=callback["generation"],
        execution_mode=execution_mode,
        require_host_attestation=True,
        resource_evidence=resource_evidence,
    )
    result = run_due_occurrence(
        due_port, attention, gateway, responsibility, callback["request"],
        schedule_id=callback["schedule_id"], capability_evidence=capability_evidence,
        context_evidence=tuple(context_evidence), allowance_evidence=allowance_evidence,
        assignment_reader=assignment_reader,
    )
    result["callback"] = {
        "contract": callback["contract"], "callback_id": callback["callback_id"],
        "owner_actor": callback["owner_actor"], "owner_version": callback["owner_version"],
        "correlation_id": callback["correlation_id"], "automatic_action": False,
    }
    return result


__all__ = ["OPERATIONS", "AttemptCapturePort", "AttemptEnvelope", "InMemoryAttemptCapture", "HerzchenAttemptCapture", "OwnerDueRecordAttemptCapture", "DueRecordAttemptCapture", "OttoGateway", "Responsibility", "run_due_occurrence", "run_scheduled_callback", "error"]
