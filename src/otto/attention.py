"""Durable attention and event continuity over finite public ports.

Otto does not own a database, an inbox, a scheduler, or an agent launcher.
The two ports in this module are deliberately small:

* ``DueRecordPort`` is a trusted host capability for persisting one serialized
  due record.  A durable host may implement it with Herzchen's public command
  surface; Otto never receives a Store, connection, descriptor, or writer.
* ``SharedAttentionPort`` is the public Herzchen attention/packet command and
  read surface, represented here as finite JSON-shaped calls.

The same state machine serves the host-compatible awaited mode and the
explicit durable-host mode.  Awaited mode may use an in-process record for the
duration of a host call, but its result says that it is not durable-host
support.  Durable-host mode refuses to claim durability without a supplied
trusted persistence port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence


JSONValue = Any


class AttentionError(RuntimeError):
    """Base error for the bounded attention surface."""


class InputChangedError(AttentionError):
    """A replay key was reused with a different immutable request."""


class StateConflictError(AttentionError):
    """A trusted host rejected a stale state update."""


class CursorContinuityError(AttentionError):
    """A cursor result cannot be safely continued."""


class HostUnavailableError(AttentionError):
    """Durable-host capability is not available."""


class AmendmentInterruptedError(AttentionError):
    """The trusted owner stopped after one durably committed amendment stage."""


def _json_copy(value: Any, field_name: str = "value") -> JSONValue:
    """Return a canonical JSON-shaped copy and reject descriptors/callables."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must contain only finite JSON values") from exc


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be non-blank text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-blank text")
    return value


@dataclass(frozen=True)
class DueRecord:
    """The small durable record needed to resume one responsibility.

    ``anchor`` and ``due_at`` are UTC ISO strings so a close/reopen does not
    depend on a process-local datetime object.  ``last_covered_slot`` is a
    logical slot, not elapsed wall-clock state.  Missed interval slots are
    coalesced into one attention request.
    """

    schedule_id: str
    recipient: str
    instruction: str
    profile: str
    anchor: str
    last_covered_slot: int
    invocation_identity: str
    stop_state: str = "active"
    interval_seconds: Optional[int] = None
    due_at: Optional[str] = None
    in_flight_request: Optional[str] = None
    delivery_state: str = "none"
    owner: Optional[str] = None
    missing_handoff: Optional[str] = None
    return_condition: str = "host returns a receipt for the same invocation"
    outstanding_decisions: tuple[Mapping[str, JSONValue], ...] = ()
    last_completed_request: Optional[str] = None
    last_result: Optional[Mapping[str, JSONValue]] = None
    version: int = 0
    # BK-06 foundation metadata is additive and remains in the same owner
    # record.  It makes the wake/check boundary observable without inventing
    # a scheduler ledger or a second persistence path.
    project_ref: Optional[str] = None
    manager_ref: Optional[str] = None
    generation: int = 1
    due_reasons: tuple[str, ...] = ()
    delivered_at: Optional[str] = None
    delivery_evidence: Optional[Mapping[str, JSONValue]] = None
    completed_at: Optional[str] = None
    completion_evidence: Optional[Mapping[str, JSONValue]] = None
    completion_state: str = "none"
    # SUP-02 owner-bound host configuration.  These fields remain part of the
    # existing due record so a host can reconcile a trigger without a second
    # registry or scheduler.  ``target`` is descriptive routing metadata; it
    # does not imply that Otto can reach the named host itself.
    target: Optional[Mapping[str, JSONValue]] = None
    role: Optional[str] = None
    purpose: Optional[str] = None
    message: Optional[str] = None
    lifecycle_owner: Optional[str] = None
    host_state: str = "unknown"
    host_evidence: Optional[Mapping[str, JSONValue]] = None

    def __post_init__(self) -> None:
        _required_text(self.schedule_id, "schedule_id")
        _required_text(self.recipient, "recipient")
        _required_text(self.instruction, "instruction")
        _required_text(self.profile, "profile")
        _required_text(self.anchor, "anchor")
        _required_text(self.invocation_identity, "invocation_identity")
        _parse_iso(self.anchor)
        if self.due_at is not None:
            _parse_iso(self.due_at)
        if isinstance(self.last_covered_slot, bool) or not isinstance(self.last_covered_slot, int):
            raise ValueError("last_covered_slot must be an integer")
        if self.interval_seconds is not None and (isinstance(self.interval_seconds, bool) or not isinstance(self.interval_seconds, int) or self.interval_seconds <= 0):
            raise ValueError("interval_seconds must be a positive integer")
        if self.interval_seconds is None and self.due_at is None:
            raise ValueError("one-off records require due_at when interval_seconds is absent")
        for field_name, value in (("project_ref", self.project_ref), ("manager_ref", self.manager_ref)):
            if value is not None:
                _required_text(value, field_name)
        for field_name, value in (("role", self.role), ("purpose", self.purpose), ("message", self.message), ("lifecycle_owner", self.lifecycle_owner)):
            if value is not None:
                _required_text(value, field_name)
        if self.target is not None:
            if not isinstance(self.target, Mapping):
                raise TypeError("target must be a JSON object")
            target = _json_copy(self.target, "target")
            if not isinstance(target, Mapping):
                raise TypeError("target must be a JSON object")
            if not _required_text(target.get("host") or target.get("host_id"), "target.host"):
                raise ValueError("target.host must be non-blank text")
            identity = next((target.get(key) for key in ("native_id", "conversation_id", "agent_id", "thread_id", "id") if target.get(key)), None)
            if not _required_text(identity, "target.native_id"):
                raise ValueError("target.native_id must be non-blank text")
            object.__setattr__(self, "target", target)
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be a positive integer")
        if any(not isinstance(reason, str) or not reason.strip() for reason in self.due_reasons):
            raise ValueError("due_reasons must contain non-blank text")
        if self.delivered_at is not None:
            _parse_iso(self.delivered_at)
        if self.completed_at is not None:
            _parse_iso(self.completed_at)
        if self.stop_state not in {"active", "stopped", "completed"}:
            raise ValueError("stop_state must be active, stopped, or completed")
        if self.delivery_state not in {"none", "ready", "returned", "unknown", "crashed"}:
            raise ValueError("unsupported delivery_state")
        if self.completion_state not in {"none", "succeeded", "failed", "unknown"}:
            raise ValueError("unsupported completion_state")
        if self.host_state not in {"unknown", "pending", "active", "paused", "failed"}:
            raise ValueError("unsupported host_state")
        object.__setattr__(self, "outstanding_decisions", tuple(_json_copy(item, "outstanding_decisions") for item in self.outstanding_decisions))
        if self.last_result is not None:
            object.__setattr__(self, "last_result", _json_copy(self.last_result, "last_result"))
        if self.delivery_evidence is not None:
            object.__setattr__(self, "delivery_evidence", _json_copy(self.delivery_evidence, "delivery_evidence"))
        if self.completion_evidence is not None:
            object.__setattr__(self, "completion_evidence", _json_copy(self.completion_evidence, "completion_evidence"))
        if self.host_evidence is not None:
            object.__setattr__(self, "host_evidence", _json_copy(self.host_evidence, "host_evidence"))

    @property
    def immutable_input(self) -> dict[str, JSONValue]:
        return {
            "schedule_id": self.schedule_id,
            "recipient": self.recipient,
            "instruction": self.instruction,
            "profile": self.profile,
            "anchor": self.anchor,
            "interval_seconds": self.interval_seconds,
            "due_at": self.due_at,
            "invocation_identity": self.invocation_identity,
            "owner": self.owner,
            "project_ref": self.project_ref,
            "manager_ref": self.manager_ref,
            "generation": self.generation,
            "target": None if self.target is None else dict(self.target),
            "role": self.role,
            "purpose": self.purpose,
            "message": self.message,
            "lifecycle_owner": self.lifecycle_owner,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            **self.immutable_input,
            "last_covered_slot": self.last_covered_slot,
            "stop_state": self.stop_state,
            "in_flight_request": self.in_flight_request,
            "delivery_state": self.delivery_state,
            "missing_handoff": self.missing_handoff,
            "return_condition": self.return_condition,
            "outstanding_decisions": [dict(item) for item in self.outstanding_decisions],
            "last_completed_request": self.last_completed_request,
            "last_result": None if self.last_result is None else dict(self.last_result),
            "version": self.version,
            "due_reasons": list(self.due_reasons),
            "delivered_at": self.delivered_at,
            "delivery_evidence": None if self.delivery_evidence is None else dict(self.delivery_evidence),
            "completed_at": self.completed_at,
            "completion_evidence": None if self.completion_evidence is None else dict(self.completion_evidence),
            "completion_state": self.completion_state,
            "host_state": self.host_state,
            "host_evidence": None if self.host_evidence is None else dict(self.host_evidence),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DueRecord":
        if not isinstance(value, Mapping):
            raise TypeError("due record must be a JSON object")
        return cls(
            schedule_id=value["schedule_id"], recipient=value["recipient"], instruction=value["instruction"],
            profile=value["profile"], anchor=value["anchor"], last_covered_slot=int(value.get("last_covered_slot", -1)),
            invocation_identity=value["invocation_identity"], stop_state=value.get("stop_state", "active"),
            interval_seconds=value.get("interval_seconds"), due_at=value.get("due_at"),
            in_flight_request=value.get("in_flight_request"), delivery_state=value.get("delivery_state", "none"),
            owner=value.get("owner"), missing_handoff=value.get("missing_handoff"),
            return_condition=value.get("return_condition", "host returns a receipt for the same invocation"),
            outstanding_decisions=tuple(value.get("outstanding_decisions", ())),
            last_completed_request=value.get("last_completed_request"), last_result=value.get("last_result"),
            version=int(value.get("version", 0)),
            project_ref=value.get("project_ref"), manager_ref=value.get("manager_ref"),
            generation=int(value.get("generation", 1)), due_reasons=tuple(value.get("due_reasons", ())),
            delivered_at=value.get("delivered_at"), delivery_evidence=value.get("delivery_evidence"),
            completed_at=value.get("completed_at"), completion_evidence=value.get("completion_evidence"),
            completion_state=value.get("completion_state", "none"),
            target=value.get("target"), role=value.get("role"), purpose=value.get("purpose"),
            message=value.get("message"), lifecycle_owner=value.get("lifecycle_owner"),
            host_state=value.get("host_state", "unknown"), host_evidence=value.get("host_evidence"),
        )


class DueRecordPort(Protocol):
    """Finite trusted-host persistence boundary; no Store-shaped methods."""

    def read_due(self, schedule_id: str) -> Optional[Mapping[str, JSONValue]]: ...

    def save_due(self, schedule_id: str, record: Mapping[str, JSONValue], *, request_id: str, expected_version: int) -> Mapping[str, JSONValue]: ...


class SharedAttentionPort(Protocol):
    """Finite shared attention commands and reads."""

    def create_attention(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]: ...

    def list_attention(self, recipient: Optional[str] = None) -> Sequence[Mapping[str, JSONValue]]: ...


class HostTriggerPort(Protocol):
    """Finite owner-side trigger seam; implementations remain outside Otto."""

    def ensure_trigger(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]: ...

    def read_trigger(self, schedule_id: str) -> Optional[Mapping[str, JSONValue]]: ...

    def pause_trigger(self, schedule_id: str, *, request_id: str) -> Mapping[str, JSONValue]: ...


class AmendmentPort(Protocol):
    """Finite manager-authorized amendment command."""

    def apply_amendment(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]: ...


class InMemoryDueRecordPort:
    """Fixture/awaited port with the same finite contract as a trusted host.

    It is intentionally not advertised as durable-host support.  Tests use it
    to prove state-machine behavior without giving Otto a database writer.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict[str, JSONValue]] = {}
        self._requests: dict[str, tuple[str, dict[str, JSONValue]]] = {}

    def read_due(self, schedule_id: str) -> Optional[Mapping[str, JSONValue]]:
        value = self._records.get(schedule_id)
        return None if value is None else _json_copy(value, "record")

    def save_due(self, schedule_id: str, record: Mapping[str, JSONValue], *, request_id: str, expected_version: int) -> Mapping[str, JSONValue]:
        value = dict(_json_copy(record, "record"))
        if schedule_id != value.get("schedule_id"):
            raise InputChangedError("schedule_id does not match the durable record")
        prior_request = self._requests.get(request_id)
        if prior_request is not None:
            prior_schedule, prior_value = prior_request
            if prior_schedule != schedule_id or prior_value != value:
                raise InputChangedError("request id was reused with changed durable input")
            return _json_copy(prior_value, "record")
        current = self._records.get(schedule_id)
        current_version = 0 if current is None else int(current.get("version", 0))
        if current_version != expected_version:
            raise StateConflictError(f"expected durable version {expected_version}, observed {current_version}")
        value["version"] = current_version + 1
        self._records[schedule_id] = value
        self._requests[request_id] = (schedule_id, dict(value))
        return _json_copy(value, "record")


def due_record_contribution() -> Any:
    """Return the public Herzchen domain declaration for the owner adapter.

    The import is intentionally lazy: the Otto state machine remains usable
    with the fixture port when no Herzchen wheel is installed.  A durable host
    composes this declaration with ``Store.register_domain_handler`` and keeps
    the resulting handler on the owner side of the finite DueRecordPort.
    """

    from herzchen.contracts import DomainContribution

    schema = "otto.due-record.v1"
    operation = "otto.due-record.save"
    kind = "otto.due-record"
    event = "otto.due-record.changed"
    return DomainContribution(
        "otto.attention", "1.0", "otto", (kind,), (), ("otto.attention",),
        (operation,), (event,), schema,
        (
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "handler-required",
            f"mutation-port:{schema}|{operation}|{kind}|{event}",
        ),
    )


def _wire_json(value: Any) -> JSONValue:
    """Convert accepted Herzchen value objects to finite JSON data."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _wire_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire_json(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _wire_json(to_dict())
    if hasattr(value, "value"):
        return _wire_json(value.value)
    raise TypeError("owner service returned a non-serialized value")


def _receipt_json(receipt: Any, *, result_payload: Mapping[str, JSONValue], result_version: int, replayed: bool) -> dict[str, JSONValue]:
    result_ref = getattr(receipt, "result_ref", None)
    status = getattr(getattr(receipt, "status", None), "value", getattr(receipt, "status", None))
    return {
        "logical_request_key": receipt.logical_request_key,
        "request_digest": receipt.request_digest,
        "status": status,
        "event_ids": list(receipt.event_ids),
        "result_ref": None if result_ref is None else _wire_json(result_ref),
        "result_payload": _wire_json(result_payload),
        "result_version": result_version,
        "replayed": replayed,
    }


class _DueRecordOwnerEngine:
    """Trusted owner implementation used behind Herzchen's command port."""

    def __init__(self, writer: Any, actor: Any) -> None:
        from herzchen.contracts import AuthenticatedActor

        if not hasattr(writer, "mutate") or not hasattr(writer, "get_identity"):
            raise TypeError("writer must be an issued Herzchen domain handler")
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("actor must be an FND AuthenticatedActor")
        self._writer = writer
        self._actor = actor

    @staticmethod
    def _ref(authority: str, schedule_id: str, revision: Optional[str] = None) -> Any:
        from herzchen.contracts import ResourceRef

        return ResourceRef(authority, "otto.due-record", schedule_id, revision)

    def read_due(self, schedule_id: str) -> Optional[Mapping[str, JSONValue]]:
        _required_text(schedule_id, "schedule_id")
        identity = self._writer.get_identity(self._ref(self._writer.authority, schedule_id))
        if identity is None:
            return None
        value = _json_copy(identity.payload, "due record")
        value["version"] = int(identity.version)
        return value

    def save_due(
        self,
        schedule_id: str,
        record: Mapping[str, JSONValue],
        *,
        request_id: str,
        expected_version: int,
    ) -> Mapping[str, JSONValue]:
        from herzchen.contracts import CommandEnvelope, TransactionContext

        _required_text(schedule_id, "schedule_id")
        _required_text(request_id, "request_id")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        value = dict(_json_copy(record, "record"))
        if value.get("schedule_id") != schedule_id:
            raise InputChangedError("schedule_id does not match the durable record")
        current_ref = self._ref(self._writer.authority, schedule_id)
        current = self._writer.get_identity(current_ref)
        prior = self._writer.get_receipt(request_id)
        if prior is None:
            observed = 0 if current is None else int(current.version)
            if observed != expected_version:
                raise StateConflictError(f"expected durable version {expected_version}, observed {observed}")
        if prior is not None:
            # Store replay identity includes the original unpinned target and
            # request payload.  Reconstruct those exact values before asking
            # the public mutation API to replay; otherwise a later revision
            # would be mistaken for changed input.
            target = prior.target
            result_revision = None if prior.result_ref is None else prior.result_ref.revision
            try:
                next_version = int(str(result_revision).removeprefix("rev-"))
            except (TypeError, ValueError):
                next_version = 1 if current is None else int(current.version)
            # Preserve the caller's supplied precondition in the replay
            # envelope.  Store's public replay validator hashes the complete
            # TransactionContext, so a retry with a different expected
            # version must fail before mutation rather than inheriting A's
            # historical precondition silently.
            replay_expected_version = expected_version
            replay_expected_revision = target.revision
        else:
            target = current_ref if current is None else current.ref
            next_version = (0 if current is None else int(current.version)) + 1
            replay_expected_version = expected_version
            replay_expected_revision = None if current is None else current.ref.revision
        value["version"] = next_version
        digest = _digest({"request_id": request_id, "expected_version": expected_version, "record": value})
        context = TransactionContext(
            self._actor, request_id, digest,
            expected_revision=replay_expected_revision,
            expected_version=replay_expected_version,
        )
        envelope = CommandEnvelope(
            "otto.due-record.save", "otto.due-record.v1", target, context, value,
        )
        try:
            receipt = self._writer.mutate(
                envelope,
                event_type="otto.due-record.changed",
                result_ref=self._ref(self._writer.authority, schedule_id, f"rev-{next_version}"),
                before_refs=() if current is None else (current.ref,),
                after_refs=(self._ref(self._writer.authority, schedule_id, f"rev-{next_version}"),),
                effects={"schedule_id": schedule_id, "version": next_version, "record": value},
                stream="otto.due-record:" + schedule_id,
            )
        except Exception as exc:
            name = type(exc).__name__
            if name == "ReplayConflictError":
                raise InputChangedError("request id was reused with changed durable input") from exc
            if name in {"VersionConflictError", "TargetMismatchError"}:
                raise StateConflictError(str(exc)) from exc
            raise
        # A replay is a historical result, not a read of the current
        # projection.  The live projection remains available through
        # read_due, while this response retains the original result ref,
        # version, payload, and event/receipt linkage.
        result = dict(_json_copy(value, "due record"))
        result["mutation_receipt"] = _receipt_json(
            prior if prior is not None else receipt,
            result_payload=value,
            result_version=next_version,
            replayed=prior is not None,
        )
        return result


_DUE_OWNER_SERVICE_TYPE: Any = None


def _due_owner_service_type() -> Any:
    global _DUE_OWNER_SERVICE_TYPE
    if _DUE_OWNER_SERVICE_TYPE is None:
        from herzchen.command_ports import command_facade

        _DUE_OWNER_SERVICE_TYPE = command_facade(_DueRecordOwnerEngine, "otto.attention.due-record")
    return _DUE_OWNER_SERVICE_TYPE


class StoreDueRecordPort:
    """Finite serialized consumer client for an owner-side due-record service.

    The client stores only Herzchen's authenticated serialized command
    transport.  The Store/DomainHandler remains behind the owner service and
    is never reachable through this object or through DurableAttention.
    """

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        from herzchen.command_ports import SerializedCommandClient

        if not isinstance(client, SerializedCommandClient):
            raise TypeError("client must be an issued Herzchen SerializedCommandClient")
        if tuple(client.endpoints) != ("read_due", "save_due"):
            raise TypeError("due-record client endpoints must be exactly read_due and save_due")
        self._client = client

    @property
    def transport(self) -> Any:
        """Return the finite transport descriptor for owner shutdown/audit."""

        return self._client.transport

    def __dir__(self) -> list[str]:
        return ["read_due", "save_due", "transport"]

    def read_due(self, schedule_id: str) -> Optional[Mapping[str, JSONValue]]:
        value = self._client.call("read_due", schedule_id)
        return None if value is None else dict(_json_copy(value, "due record"))

    def save_due(
        self,
        schedule_id: str,
        record: Mapping[str, JSONValue],
        *,
        request_id: str,
        expected_version: int,
    ) -> Mapping[str, JSONValue]:
        value = self._client.call(
            "save_due", schedule_id, _json_copy(record, "record"),
            request_id=request_id, expected_version=expected_version,
        )
        return dict(_json_copy(value, "due record"))


def issue_store_due_record_port(writer: Any, actor: Any) -> StoreDueRecordPort:
    """Issue the finite client while retaining Herzchen custody in the host."""

    service = _due_owner_service_type()(writer, actor)
    return StoreDueRecordPort(service.command_port)


class SerializedAttentionPort:
    """Adapt trusted public Herzchen methods without exposing their owner."""

    def __init__(self, create: Callable[[Mapping[str, JSONValue]], Mapping[str, JSONValue]], read: Callable[[Optional[str]], Sequence[Mapping[str, JSONValue]]]) -> None:
        self._create = create
        self._read = read

    def create_attention(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        return dict(_json_copy(self._create(_json_copy(request, "attention request")), "attention response"))

    def list_attention(self, recipient: Optional[str] = None) -> Sequence[Mapping[str, JSONValue]]:
        return tuple(dict(_json_copy(item, "attention item")) for item in self._read(recipient))


class _AmendmentOwnerEngine:
    """Trusted owner composition over accepted Herzchen public facades."""

    _STAGES = ("decision", "plan", "assignment", "attention")

    def __init__(
        self,
        store: Any,
        actor: Any,
        project: Any,
        assignment: Any,
        subject: Any,
        amended_revision: Any,
        interrupt_after_stage: Optional[str] = None,
    ) -> None:
        from herzchen.content.packets import ContextPacketService
        from herzchen.domains.work.assignments import ResponsibilityAssignments
        from herzchen.domains.work.sheet import ProjectSheet

        if interrupt_after_stage is not None and interrupt_after_stage not in self._STAGES:
            raise ValueError("interrupt_after_stage must name decision, plan, assignment, or attention")
        self._actor = actor
        self._project = project
        self._assignment = assignment
        self._subject = subject
        self._amended_revision = amended_revision
        self._receipts = store.consumer()
        self._interrupt_after_stage = interrupt_after_stage
        self._sheet = ProjectSheet(store, actor=actor)
        self._assignments = ResponsibilityAssignments(store, actor=actor)
        self._packets = ContextPacketService(store)
        current = self._assignments.get(assignment)
        self._task = current.scope

    def _views(self) -> dict[str, JSONValue]:
        fresh_project = self._sheet.graph.get(self._project)
        fresh_assignment = self._assignments.get(self._assignment)
        fresh_sheet = self._sheet.export(fresh_project, task_refs=[self._task])
        usage_budget = fresh_project.payload.get("metadata", {}).get("ott04_usage_budget", {})
        return _wire_json({
            "plan": {"task": fresh_sheet.tasks[0]["authored"].get("body")},
            "next_dispatch": fresh_project.payload.get("last_batch", {}).get("manager_action"),
            "attention": self._packets.list_attention(fresh_assignment.principal),
            "assignment": {
                "route_binding": fresh_assignment.payload.get("route_binding"),
                "principal": fresh_assignment.principal,
                "agent": fresh_assignment.agent,
                "session": fresh_assignment.session,
            },
            "current_owner": fresh_assignment.principal,
            "usage": {
                "budget": fresh_project.payload.get("budget"),
                "spent": usage_budget.get("spent"),
                "limit": usage_budget.get("limit"),
            },
            "running_input_pins": [pin.to_dict() for pin in fresh_assignment.pins],
        })

    def read_views(self) -> Mapping[str, JSONValue]:
        return self._views()

    def _stage_from_receipt(self, receipt: Any, *, replayed: bool) -> dict[str, JSONValue]:
        return {
            "status": "replayed" if replayed else "committed",
            "replayed": replayed,
            "receipt": _wire_json(receipt),
        }

    def _interrupt_if_selected(self, stage: str, *, committed: bool) -> None:
        if committed and self._interrupt_after_stage == stage:
            raise AmendmentInterruptedError(f"trusted owner interrupted after committed {stage} stage")

    def _decision_stage(self, request: Mapping[str, JSONValue], request_id: str) -> dict[str, JSONValue]:
        """Bind the complete logical amendment before any partial stage write."""

        from herzchen.contracts import TransactionContext

        key = request_id + ":decision"
        prior = self._receipts.get_receipt(key)
        decision = self._packets.register_decision(
            {
                "decision_id": request["decision_id"],
                "subject": self._amended_revision,
                "author": self._actor.actor,
                "authority": self._amended_revision,
                "question": "implement the manager-selected amendment",
                "rationale": "bind the complete amendment before staged propagation",
                "return_condition": "all public amendment stages are committed or replayed",
                "amendment_request": request,
            },
            TransactionContext(self._actor, key, _digest(request)),
        )
        stage = self._stage_from_receipt(decision["receipt"], replayed=prior is not None)
        self._interrupt_if_selected("decision", committed=prior is None)
        return stage

    def _existing_stage(self, key: str) -> Optional[dict[str, JSONValue]]:
        receipt = self._receipts.get_receipt(key)
        return None if receipt is None else self._stage_from_receipt(receipt, replayed=True)

    def apply_amendment(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        request = _json_copy(request, "amendment request")
        if request.get("manager_decision") != "implement":
            raise AttentionError("a manager decision of implement is required")
        amendment = request.get("amendment")
        if not isinstance(amendment, Mapping):
            raise TypeError("amendment must be a JSON object")
        instruction = _required_text(amendment.get("instruction"), "amendment.instruction")
        next_dispatch = _required_text(amendment.get("next_dispatch"), "amendment.next_dispatch")
        route = _required_text(amendment.get("route"), "amendment.route")
        request_id = _required_text(request.get("request_id"), "request_id")
        try:
            # The shared decision manifest is the authoritative full-request
            # binding.  A changed same-key retry is rejected here before any
            # plan, route, or attention mutation can run.
            stages: dict[str, JSONValue] = {
                "decision": self._decision_stage(request, request_id),
            }

            plan_key = request_id + ":plan"
            plan_stage = self._existing_stage(plan_key)
            if plan_stage is None:
                plan = self._sheet.apply(
                    self._project,
                    {"tasks": [{"id": self._task.id, "body": {"instructions": instruction}}]},
                    logical_request_key=plan_key, next_action=next_dispatch, actor=self._actor,
                )
                plan_stage = self._stage_from_receipt(plan.receipt, replayed=False)
                self._interrupt_if_selected("plan", committed=True)
            stages["plan"] = plan_stage

            route_key = request_id + ":route"
            assignment_stage = self._existing_stage(route_key)
            if assignment_stage is None:
                route_result = self._sheet.pin_assignment_route(
                    self._assignment,
                    {"name": route, "reason": "manager-selected amendment"},
                    logical_request_key=route_key, actor=self._actor,
                )
                assignment_stage = self._stage_from_receipt(route_result.receipt, replayed=False)
                self._interrupt_if_selected("assignment", committed=True)
            stages["assignment"] = assignment_stage

            from herzchen.contracts import TransactionContext

            owner = self._assignments.get(self._assignment).principal
            attention_key = request_id + ":attention:" + owner
            attention_stage = self._existing_stage(attention_key)
            if attention_stage is None:
                notices = self._packets.notify_amendment(
                    self._subject,
                    self._amended_revision,
                    (owner,),
                    TransactionContext(self._actor, request_id + ":attention", _digest(request)),
                    reason="manager-selected amendment: " + instruction,
                )
                attention_stage = {
                    "status": "committed",
                    "replayed": False,
                    "receipts": [_wire_json(notice["receipt"]) for notice in notices],
                }
                self._interrupt_if_selected("attention", committed=True)
            else:
                attention_stage = {
                    "status": "replayed",
                    "replayed": True,
                    "receipts": [attention_stage["receipt"]],
                }
            stages["attention"] = attention_stage
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                raise InputChangedError("amendment request key was reused with changed logical input") from exc
            raise

        receipts = {
            "decision": stages["decision"]["receipt"],
            "plan": stages["plan"]["receipt"],
            "assignment": stages["assignment"]["receipt"],
            "attention": stages["attention"]["receipts"],
        }
        stage_values = tuple(stages.values())
        replayed = all(bool(stage.get("replayed")) for stage in stage_values)
        recovered = any(bool(stage.get("replayed")) for stage in stage_values) and not replayed
        event_ids = [
            event_id
            for value in receipts.values()
            for receipt in (value if isinstance(value, list) else [value])
            for event_id in receipt.get("event_ids", ())
        ]
        return _wire_json({
            "status": "already-applied" if replayed else "completed",
            "completed": True,
            "replayed": replayed,
            "recovered": recovered,
            "event_ids": event_ids,
            "stages": stages,
            "receipts": receipts,
            "incomplete": False,
            "automatic_action": False,
            "dispatch": False,
        })


_AMENDMENT_OWNER_SERVICE_TYPE: Any = None


def _amendment_owner_service_type() -> Any:
    global _AMENDMENT_OWNER_SERVICE_TYPE
    if _AMENDMENT_OWNER_SERVICE_TYPE is None:
        from herzchen.command_ports import command_facade

        _AMENDMENT_OWNER_SERVICE_TYPE = command_facade(_AmendmentOwnerEngine, "otto.attention.amendment")
    return _AMENDMENT_OWNER_SERVICE_TYPE


class SerializedAmendmentPort:
    """Finite serialized client for the shipped owner amendment service."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        from herzchen.command_ports import SerializedCommandClient

        if not isinstance(client, SerializedCommandClient):
            raise TypeError("client must be an issued Herzchen SerializedCommandClient")
        if tuple(client.endpoints) != ("apply_amendment", "read_views"):
            raise TypeError("amendment client endpoints must be exactly apply_amendment and read_views")
        self._client = client

    @property
    def transport(self) -> Any:
        return self._client.transport

    def __dir__(self) -> list[str]:
        return ["apply_amendment", "read_views", "transport"]

    def apply_amendment(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        return dict(_json_copy(self._client.call("apply_amendment", _json_copy(request, "amendment request")), "amendment response"))

    def read_views(self) -> Mapping[str, JSONValue]:
        return dict(_json_copy(self._client.call("read_views"), "amendment views"))


def issue_store_amendment_port(
    store: Any,
    actor: Any,
    project: Any,
    assignment: Any,
    subject: Any,
    amended_revision: Any,
    *,
    interrupt_after_stage: Optional[str] = None,
) -> SerializedAmendmentPort:
    """Issue a finite client; all Herzchen service objects stay owner-side."""

    service = _amendment_owner_service_type()(
        store, actor, project, assignment, subject, amended_revision, interrupt_after_stage,
    )
    return SerializedAmendmentPort(service.command_port)


class RecordingAttentionPort:
    """Fixture port used for behavior tests; it records finite mutations only."""

    def __init__(self) -> None:
        self.requests: list[dict[str, JSONValue]] = []

    def create_attention(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        value = dict(_json_copy(request, "attention request"))
        for prior in self.requests:
            if prior["request_id"] == value["request_id"]:
                if prior != value:
                    raise InputChangedError("attention request was reused with changed input")
                return {"outcome": "replayed", "request_id": value["request_id"], "event_ids": list(prior.get("event_ids", ())), "receipt": prior.get("receipt")}
        event_id = f"attention-event-{len(self.requests) + 1}"
        value["event_ids"] = [event_id]
        value["receipt"] = {"logical_request_key": value["request_id"], "event_ids": [event_id]}
        self.requests.append(value)
        return {"outcome": "created", "request_id": value["request_id"], "event_ids": [event_id], "receipt": value["receipt"]}

    def list_attention(self, recipient: Optional[str] = None) -> Sequence[Mapping[str, JSONValue]]:
        return tuple(item for item in self.requests if recipient is None or item.get("recipient") == recipient)


class RecordingHostTriggerPort:
    """Deterministic fixture for the finite owner-side host seam.

    This fixture records idempotent ensure/pause calls and exposes readback so
    tests can distinguish desired configuration from observed host state.  It
    is deliberately not a scheduler and does not launch a native conversation.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, JSONValue]] = []
        self._records: dict[str, dict[str, JSONValue]] = {}
        self._replies: dict[str, dict[str, JSONValue]] = {}
        self.available = True

    def ensure_trigger(self, request: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        value = dict(_json_copy(request, "host trigger request"))
        schedule_id = _required_text(value.get("schedule_id"), "schedule_id")
        request_id = _required_text(value.get("request_id"), "request_id")
        prior = self._replies.get(request_id)
        if prior is not None:
            if prior.get("request") != value:
                raise InputChangedError("host trigger request was reused with changed input")
            return _json_copy(prior["response"], "host trigger response")
        if not self.available:
            raise HostUnavailableError("host trigger port is unavailable")
        current = self._records.get(schedule_id)
        same_configuration = current is not None and current.get("configuration") == value.get("configuration")
        response = {
            "outcome": "replayed" if same_configuration else "ensured",
            "schedule_id": schedule_id,
            "request_id": request_id,
            "state": "active",
            "target": value.get("configuration", {}).get("target"),
            "configuration": value.get("configuration"),
        }
        self._records[schedule_id] = {"configuration": value.get("configuration"), "state": "active", "response": response}
        self._replies[request_id] = {"request": value, "response": response}
        self.requests.append(value)
        return _json_copy(response, "host trigger response")

    def read_trigger(self, schedule_id: str) -> Optional[Mapping[str, JSONValue]]:
        value = self._records.get(schedule_id)
        return None if value is None else _json_copy(value.get("response"), "host trigger readback")

    def pause_trigger(self, schedule_id: str, *, request_id: str) -> Mapping[str, JSONValue]:
        request_id = _required_text(request_id, "request_id")
        if not self.available:
            raise HostUnavailableError("host trigger port is unavailable")
        current = self._records.get(schedule_id)
        if current is None:
            return {"outcome": "unknown", "schedule_id": schedule_id, "state": "unknown", "request_id": request_id}
        configuration = _json_copy(current.get("configuration"), "configuration")
        if isinstance(configuration, Mapping):
            configuration = dict(configuration)
            target = configuration.get("target")
            if isinstance(target, Mapping) and isinstance(target.get("automation"), Mapping):
                target = dict(target)
                automation = dict(target["automation"])
                automation["status"] = "PAUSED"
                target["automation"] = automation
                configuration["target"] = target
            if isinstance(configuration.get("automation"), Mapping):
                automation = dict(configuration["automation"])
                automation["status"] = "PAUSED"
                configuration["automation"] = automation
        response = {
            "outcome": "paused", "schedule_id": schedule_id, "state": "paused",
            "request_id": request_id, "configuration": configuration,
            "target": configuration.get("target") if isinstance(configuration, Mapping) else None,
        }
        current["state"] = "paused"
        current["configuration"] = configuration
        current["response"] = response
        self._replies[request_id] = {"request": {"schedule_id": schedule_id, "request_id": request_id, "action": "pause"}, "response": response}
        return _json_copy(response, "host trigger response")


class ImprovementPropagation:
    """Keep review notification, manager choice, and implementation distinct."""

    def __init__(self, amendment: AmendmentPort, read_views: Optional[Callable[[], Mapping[str, JSONValue]]] = None) -> None:
        self.amendment = amendment
        if read_views is None:
            read_views = getattr(amendment, "read_views", None)
        if not callable(read_views):
            raise TypeError("a finite amendment client must provide read_views")
        self.read_views = read_views

    def handle_review(self, review_id: str, *, recipient: str, return_condition: str) -> dict[str, JSONValue]:
        return {
            "outcome": "review-handled",
            "review_id": _required_text(review_id, "review_id"),
            "recipient": _required_text(recipient, "recipient"),
            "return_condition": _required_text(return_condition, "return_condition"),
            "implemented_improvement": False,
            "dispatch": False,
            "automatic_action": False,
        }

    def apply(self, review_id: str, *, decision_id: str, amendment: Mapping[str, JSONValue], request_id: str) -> dict[str, JSONValue]:
        if not _required_text(decision_id, "decision_id"):
            raise ValueError("decision_id is required")
        before = _json_copy(self.read_views(), "before_views")
        if not isinstance(before, Mapping):
            raise TypeError("read_views must return a JSON object")
        request = {
            "review_id": _required_text(review_id, "review_id"),
            "decision_id": decision_id,
            "request_id": _required_text(request_id, "request_id"),
            "amendment": _json_copy(amendment, "amendment"),
            "manager_decision": "implement",
        }
        response = dict(_json_copy(self.amendment.apply_amendment(request), "amendment response"))
        after = _json_copy(self.read_views(), "after_views")
        required_changes = {
            "plan_changed": before.get("plan") != after.get("plan"),
            "next_dispatch_changed": before.get("next_dispatch") != after.get("next_dispatch"),
            "attention_view_changed": before.get("attention") != after.get("attention"),
            "assignment_view_changed": before.get("assignment") != after.get("assignment"),
        }
        stages = response.get("stages", {})
        stage_satisfaction = {
            "plan": isinstance(stages, Mapping) and isinstance(stages.get("plan"), Mapping) and stages["plan"].get("status") in {"committed", "replayed"},
            "next_dispatch": isinstance(stages, Mapping) and isinstance(stages.get("plan"), Mapping) and stages["plan"].get("status") in {"committed", "replayed"},
            "attention": isinstance(stages, Mapping) and isinstance(stages.get("attention"), Mapping) and stages["attention"].get("status") in {"committed", "replayed"},
            "assignment": isinstance(stages, Mapping) and isinstance(stages.get("assignment"), Mapping) and stages["assignment"].get("status") in {"committed", "replayed"},
        }
        requirements_satisfied = {
            "plan": required_changes["plan_changed"] or stage_satisfaction["plan"],
            "next_dispatch": required_changes["next_dispatch_changed"] or stage_satisfaction["next_dispatch"],
            "attention": required_changes["attention_view_changed"] or stage_satisfaction["attention"],
            "assignment": required_changes["assignment_view_changed"] or stage_satisfaction["assignment"],
        }
        preserved = {
            key: before.get(key) == after.get(key)
            for key in ("current_owner", "usage", "running_input_pins")
        }
        incomplete = bool(response.get("incomplete", False)) or not all(requirements_satisfied.values()) or not all(preserved.values())
        replayed = bool(response.get("replayed", False))
        recovered = bool(response.get("recovered", False))
        outcome = "incomplete-propagation"
        if not incomplete:
            outcome = "improvement-already-applied" if replayed else ("improvement-recovered" if recovered else "improvement-implemented")
        return {
            "outcome": outcome,
            "review_id": review_id,
            "decision_id": decision_id,
            "implemented_improvement": not incomplete,
            "required_changes": required_changes,
            "stage_satisfaction": stage_satisfaction,
            "requirements_satisfied": requirements_satisfied,
            "preserved": preserved,
            "before": before,
            "action": request,
            "response": response,
            "fresh_after": after,
            "replayed": replayed,
            "recovered": recovered,
            "dispatch": False,
            "automatic_action": False,
        }


def _same_immutable(left: DueRecord, right: DueRecord) -> bool:
    return left.immutable_input == right.immutable_input


class DurableAttention:
    """One-shot/interval readiness gate with durable-host reconciliation."""

    def __init__(self, attention: SharedAttentionPort, *, due_port: Optional[DueRecordPort] = None, clock: Optional[Callable[[], datetime]] = None, host_mode: str = "awaited", host_available: bool = True, host_port: Optional[HostTriggerPort] = None) -> None:
        if host_mode not in {"awaited", "durable-host"}:
            raise ValueError("host_mode must be awaited or durable-host")
        self.attention = attention
        self.due_port = due_port
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.host_mode = host_mode
        self.host_available = host_available
        self.host_port = host_port
        self._awaited_records: dict[str, DueRecord] = {}

    @property
    def capability(self) -> dict[str, JSONValue]:
        durable = self.host_mode == "durable-host" and self.due_port is not None and self.host_available
        return {"mode": self.host_mode, "available": bool(self.host_available and (self.host_mode == "awaited" or self.due_port is not None)), "durable": durable, "owner": "trusted-host" if durable else "current-host-call", "automatic_action": False}

    def _read(self, schedule_id: str) -> Optional[DueRecord]:
        if self.due_port is not None:
            value = self.due_port.read_due(schedule_id)
            return None if value is None else DueRecord.from_dict(value)
        return self._awaited_records.get(schedule_id)

    def _write(self, record: DueRecord, *, request_id: str, expected_version: int) -> DueRecord:
        if self.due_port is not None:
            value = self.due_port.save_due(record.schedule_id, record.to_dict(), request_id=request_id, expected_version=expected_version)
            return DueRecord.from_dict(value)
        if self.host_mode == "durable-host":
            raise HostUnavailableError("durable-host mode requires a trusted DueRecordPort")
        value = DueRecord.from_dict({**record.to_dict(), "version": expected_version + 1})
        self._awaited_records[record.schedule_id] = value
        return value

    def schedule(self, record: DueRecord, *, request_id: Optional[str] = None) -> dict[str, JSONValue]:
        if not self.host_available:
            return {"outcome": "unavailable", "error": {"code": "host_unavailable", "message": "the responsible host is unavailable"}, "capability": self.capability, "automatic_action": False}
        if self.host_mode == "durable-host" and self.due_port is None:
            return {"outcome": "unavailable", "error": {"code": "durable_host_unavailable", "message": "no trusted durable DueRecordPort was supplied"}, "capability": self.capability, "automatic_action": False}
        prior = self._read(record.schedule_id)
        key = request_id or "schedule:" + record.schedule_id
        if prior is not None:
            if not _same_immutable(prior, record):
                raise InputChangedError("same schedule_id was reused with changed immutable input")
            return {"outcome": "replayed", "record": prior.to_dict(), "replayed": True, "expected_delta": "none", "mutation": {"before": prior.to_dict(), "action": record.to_dict(), "fresh_after": prior.to_dict()}, "automatic_action": False, "capability": self.capability}
        stored = self._write(record, request_id=key, expected_version=0)
        return {"outcome": "scheduled", "record": stored.to_dict(), "replayed": False, "expected_delta": {"record_version": 1}, "mutation": {"before": None, "action": record.to_dict(), "fresh_after": stored.to_dict()}, "automatic_action": False, "capability": self.capability}

    def reconfigure(
        self,
        desired: DueRecord,
        *,
        request_id: str,
        expected_version: int,
        actor: Optional[str] = None,
    ) -> dict[str, JSONValue]:
        """CAS-replace immutable host configuration under the current owner.

        A changed target/role/message requires a new invocation identity and a
        current version.  This keeps same-key replay and generation fencing
        meaningful while avoiding a second trigger registry.
        """

        _required_text(request_id, "request_id")
        current = self._read(desired.schedule_id)
        if current is None:
            return {"outcome": "unknown", "schedule_id": desired.schedule_id, "automatic_action": False}
        if actor is not None and actor != current.lifecycle_owner:
            return {"outcome": "rejected", "schedule_id": desired.schedule_id, "error": {"code": "foreign_authority", "message": "actor is not the lifecycle owner"}, "automatic_action": False}
        if expected_version != current.version:
            return {"outcome": "rejected", "schedule_id": desired.schedule_id, "error": {"code": "stale_version", "message": "configuration CAS is stale"}, "automatic_action": False}
        if current.in_flight_request is not None:
            return {"outcome": "held", "schedule_id": desired.schedule_id, "request_id": current.in_flight_request, "error": {"code": "busy", "message": "an invocation is in flight"}, "automatic_action": False}
        if _same_immutable(current, desired):
            return {"outcome": "replayed", "schedule_id": desired.schedule_id, "record": current.to_dict(), "replayed": True, "expected_delta": "none", "automatic_action": False}
        if current.invocation_identity == desired.invocation_identity:
            return {"outcome": "rejected", "schedule_id": desired.schedule_id, "error": {"code": "configuration_identity_required", "message": "changed configuration requires a new invocation identity"}, "automatic_action": False}
        next_record = DueRecord.from_dict({
            **desired.to_dict(),
            "version": current.version,
            "last_covered_slot": current.last_covered_slot,
            "in_flight_request": None,
            "delivery_state": "none",
            "last_completed_request": current.last_completed_request,
            "last_result": current.last_result,
            "due_reasons": list(current.due_reasons),
            "delivered_at": None,
            "delivery_evidence": None,
            "completed_at": None,
            "completion_evidence": None,
            "completion_state": "none",
            "host_state": "unknown",
            "host_evidence": None,
        })
        try:
            stored = self._write(next_record, request_id="reconfigure:" + request_id, expected_version=current.version)
        except StateConflictError:
            return {"outcome": "rejected", "schedule_id": desired.schedule_id, "error": {"code": "stale_version", "message": "configuration CAS was rejected by the owner"}, "automatic_action": False}
        return {
            "outcome": "reconfigured", "schedule_id": desired.schedule_id, "record": stored.to_dict(),
            "replayed": False, "expected_delta": {"invocation_identity": stored.invocation_identity, "host_state": "unknown"},
            "mutation": {"before": current.to_dict(), "action": desired.to_dict(), "fresh_after": stored.to_dict()},
            "automatic_action": False,
        }

    @staticmethod
    def _host_configuration(record: DueRecord, desired_state: str = "active") -> dict[str, JSONValue]:
        configuration = {
            "target": None if record.target is None else dict(record.target),
            "role": record.role,
            "purpose": record.purpose,
            "message": record.message or record.instruction,
            "schedule": {"anchor": record.anchor, "interval_seconds": record.interval_seconds, "due_at": record.due_at},
            "lifecycle_owner": record.lifecycle_owner,
            "invocation_identity": record.invocation_identity,
        }
        if desired_state not in {"active", "paused"}:
            raise ValueError("desired_state must be active or paused")
        target = configuration.get("target")
        if isinstance(target, Mapping) and isinstance(target.get("automation"), Mapping):
            target = dict(target)
            automation = dict(target["automation"])
            automation["status"] = "ACTIVE" if desired_state == "active" else "PAUSED"
            target["automation"] = automation
            configuration["target"] = target
        automation = configuration.get("automation")
        if isinstance(automation, Mapping):
            automation = dict(automation)
            automation["status"] = "ACTIVE" if desired_state == "active" else "PAUSED"
            configuration["automation"] = automation
        return configuration

    def prepare_host(
        self,
        schedule_id: str,
        *,
        request_id: str,
        expected_version: Optional[int] = None,
        actor: Optional[str] = None,
        lifecycle_owner: Optional[str] = None,
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        generation: Optional[int] = None,
        desired_state: str = "active",
    ) -> dict[str, JSONValue]:
        """Validate current ownership and durably prepare one host effect.

        This is the owner half of the bridge.  It performs no host call.  A
        host caller must use the returned effect and then submit readback to
        :meth:`acknowledge_host`.
        """

        from .host_bridge import HostBridgeError, make_host_effect

        _required_text(request_id, "request_id")
        if desired_state not in {"active", "paused"}:
            raise ValueError("desired_state must be active or paused")
        owner = actor if actor is not None else lifecycle_owner
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "schedule_id": schedule_id, "automatic_action": False}
        if owner is None or owner != record.lifecycle_owner:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "foreign_authority", "message": "authenticated actor is not the lifecycle owner"}, "automatic_action": False}
        scope_error = self._scope_error(record, project_ref=project_ref, manager_ref=manager_ref, generation=generation, lifecycle_owner=owner)
        if scope_error is not None:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": scope_error, "automatic_action": False}
        if expected_version is not None and expected_version != record.version:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "stale_version", "message": "host preparation version is stale"}, "automatic_action": False}
        if record.target is None:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "missing_target", "message": "host effects require an owner-bound native target"}, "automatic_action": False}

        # Same logical request adopts an already persisted pending effect.  It
        # never produces a second host registration.
        prior_evidence = record.host_evidence
        if isinstance(prior_evidence, Mapping) and prior_evidence.get("effect") is not None:
            try:
                prior_effect = make_host_effect(
                    schedule_id=record.schedule_id, request_id=str(prior_evidence["effect"]["request_id"]),
                    lifecycle_owner=record.lifecycle_owner or owner, project_ref=record.project_ref,
                    manager_ref=record.manager_ref, generation=record.generation,
                    owner_version=int(prior_evidence["effect"]["owner_version"]),
                    desired_state=str(prior_evidence["effect"]["desired_state"]),
                    configuration=prior_evidence["effect"]["configuration"],
                )
            except (KeyError, TypeError, ValueError, HostBridgeError):
                prior_effect = None
            if prior_effect is not None and prior_effect.request_id == request_id:
                if prior_effect.desired_state != desired_state or prior_effect.configuration != self._host_configuration(record, desired_state):
                    return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "input_changed", "message": "host request id was reused with changed input"}, "automatic_action": False}
                return {"outcome": "replayed", "schedule_id": schedule_id, "effect": prior_effect.to_dict(), "record": record.to_dict(), "replayed": True, "automatic_action": False}

        try:
            effect = make_host_effect(
                schedule_id=record.schedule_id, request_id=request_id,
                lifecycle_owner=record.lifecycle_owner or owner, project_ref=record.project_ref,
                manager_ref=record.manager_ref, generation=record.generation,
                owner_version=record.version, desired_state=desired_state,
                configuration=self._host_configuration(record, desired_state),
            )
        except HostBridgeError as exc:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "invalid_host_effect", "message": str(exc)}, "automatic_action": False}
        pending = DueRecord.from_dict({
            **record.to_dict(), "host_state": "pending",
            "host_evidence": {"outcome": "pending_host", "effect": effect.to_dict(), "owner_version": record.version},
        })
        try:
            stored = self._write(pending, request_id="host-prepare:" + request_id, expected_version=record.version)
        except StateConflictError:
            fresh = self._read(schedule_id)
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "stale_version", "message": "host preparation lost the owner race"}, "record": None if fresh is None else fresh.to_dict(), "automatic_action": False}
        return {"outcome": "pending_host", "schedule_id": schedule_id, "effect": effect.to_dict(), "record": stored.to_dict(), "replayed": False, "automatic_action": False}

    def acknowledge_host(
        self,
        schedule_id: str,
        *,
        request_id: str,
        observed: Optional[Mapping[str, JSONValue]],
        expected_version: Optional[int] = None,
        actor: Optional[str] = None,
        lifecycle_owner: Optional[str] = None,
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> dict[str, JSONValue]:
        """Persist exact host readback through the guarded owner path."""

        from .host_bridge import HostEffect, readback_matches

        _required_text(request_id, "request_id")
        owner = actor if actor is not None else lifecycle_owner
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "schedule_id": schedule_id, "automatic_action": False}
        if owner is None or owner != record.lifecycle_owner:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "foreign_authority", "message": "authenticated actor is not the lifecycle owner"}, "automatic_action": False}
        scope_error = self._scope_error(record, project_ref=project_ref, manager_ref=manager_ref, generation=generation, lifecycle_owner=owner)
        if scope_error is not None:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": scope_error, "automatic_action": False}
        if expected_version is not None and expected_version != record.version:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "stale_version", "message": "host acknowledgement version is stale"}, "record": record.to_dict(), "automatic_action": False}
        evidence = record.host_evidence if isinstance(record.host_evidence, Mapping) else {}
        effect_value = evidence.get("effect")
        if not isinstance(effect_value, Mapping):
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "no_pending_host_effect", "message": "no prepared host effect exists"}, "automatic_action": False}
        try:
            effect = HostEffect.from_dict(effect_value)
        except Exception as exc:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "invalid_host_effect", "message": str(exc)}, "automatic_action": False}
        if effect.request_id != request_id:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "request_mismatch", "message": "acknowledgement is for a different host effect"}, "automatic_action": False}
        if observed is None:
            observation = {"schedule_id": schedule_id, "state": "pending", "outcome": "response_lost", "response_lost": True}
            next_state = "pending"
            exact = False
        else:
            observation = dict(_json_copy(observed, "observed host readback"))
            exact, comparison = readback_matches(effect, observation)
            observation["readback_exact"] = exact
            observation["comparison"] = comparison
            next_state = effect.desired_state if exact else ("failed" if observation.get("outcome") in {"host_failure", "failed"} else "pending")
        updated = DueRecord.from_dict({**record.to_dict(), "host_state": next_state, "host_evidence": {"effect": effect.to_dict(), "observation": observation, "readback_exact": exact}})
        try:
            # A response-loss retry can settle the same logical effect with a
            # new observation.  Bind the persistence key to that observation
            # so the finite port accepts a changed, guarded acknowledgement.
            stored = self._write(updated, request_id="host-ack:" + request_id + ":" + _digest(observation), expected_version=record.version)
        except StateConflictError:
            fresh = self._read(schedule_id)
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": {"code": "stale_version", "message": "host acknowledgement lost the owner race"}, "record": None if fresh is None else fresh.to_dict(), "automatic_action": False}
        return {"outcome": "reconciled" if exact else next_state, "schedule_id": schedule_id, "host_state": next_state, "readback_exact": exact, "record": stored.to_dict(), "observation": observation, "automatic_action": False}

    def reconcile_host(
        self,
        schedule_id: str,
        *,
        request_id: str,
        desired_state: str = "active",
        lifecycle_owner: Optional[str] = None,
        actor: Optional[str] = None,
        expected_version: Optional[int] = None,
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> dict[str, JSONValue]:
        """Project one existing due record to an owner-side host adapter.

        The adapter is optional and finite.  If absent, the result is an
        explicit unsupported capability rather than a claimed native launch.
        Any returned host state is persisted beside the due record, separate
        from delivery and later completion evidence.
        """

        _required_text(request_id, "request_id")
        if desired_state not in {"active", "paused"}:
            raise ValueError("desired_state must be active or paused")
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "schedule_id": schedule_id, "automatic_action": False}
        owner = actor if actor is not None else lifecycle_owner
        prepared = self.prepare_host(schedule_id, request_id=request_id, expected_version=record.version if expected_version is None else expected_version, actor=owner, project_ref=project_ref, manager_ref=manager_ref, generation=generation, desired_state=desired_state)
        if prepared.get("outcome") == "rejected":
            return prepared
        if prepared.get("outcome") == "replayed" and record.host_state == desired_state:
            return {"outcome": "reconciled", "schedule_id": schedule_id, "host_state": desired_state, "record": record.to_dict(), "replayed": True, "automatic_action": False}
        if self.host_port is None:
            return {"outcome": "unsupported", "schedule_id": schedule_id, "error": {"code": "host_adapter_unavailable", "message": "no owner-side HostTriggerPort was supplied"}, "record": prepared.get("record", record.to_dict()), "automatic_action": False}
        effect_record = prepared.get("record") or self._read(schedule_id)
        effect_value = (prepared.get("effect") or (effect_record or {}).get("host_evidence", {}).get("effect"))
        host_request_id = request_id
        try:
            configuration = self._host_configuration(record, desired_state)
            if desired_state == "active":
                response = dict(_json_copy(self.host_port.ensure_trigger({
                    "request_id": request_id,
                    "schedule_id": record.schedule_id,
                    "desired_state": desired_state,
                    "configuration": configuration,
                }), "host response"))
            else:
                response = dict(_json_copy(self.host_port.pause_trigger(record.schedule_id, request_id=request_id), "host response"))
        except HostUnavailableError as exc:
            response = {"outcome": "unavailable", "state": "failed", "error": {"code": "host_unavailable", "message": str(exc)}}
        except Exception as exc:
            response = {"outcome": "failed", "state": "failed", "error": {"code": "host_adapter_error", "message": str(exc)}}
        readback = self.host_port.read_trigger(schedule_id)
        if readback is None:
            if response.get("outcome") in {"unavailable", "failed"}:
                readback = {"schedule_id": schedule_id, "state": "failed", "outcome": "host_failure", "response_lost": False, "host_response": response}
            else:
                readback = {"schedule_id": schedule_id, "state": "pending", "outcome": "response_lost", "response_lost": True, "host_response": response}
        else:
            readback = {**dict(readback), "host_response": response}
        if isinstance(effect_value, Mapping):
            ack = self.acknowledge_host(schedule_id, request_id=host_request_id, observed=readback, expected_version=int((effect_record or {}).get("version", record.version + 1)), actor=owner, project_ref=project_ref, manager_ref=manager_ref, generation=generation)
            if ack.get("outcome") in {"reconciled", "active", "paused", "pending", "failed"}:
                ack["host_response"] = response
                if response.get("outcome") in {"unavailable", "failed"}:
                    ack["outcome"] = response.get("outcome")
                return ack
        state = readback.get("state")
        return {"outcome": "pending", "schedule_id": schedule_id, "host_response": response, "host_state": state or "pending", "record": effect_record, "automatic_action": False}

    def _slot(self, record: DueRecord, now: datetime) -> Optional[int]:
        current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        if record.interval_seconds is None:
            return 0 if current >= _parse_iso(record.due_at or record.anchor) else None
        elapsed = (current.astimezone(timezone.utc) - _parse_iso(record.anchor)).total_seconds()
        return int(elapsed // record.interval_seconds)

    @staticmethod
    def _scope_error(
        record: DueRecord,
        *,
        project_ref: Optional[str],
        manager_ref: Optional[str],
        generation: Optional[int],
        lifecycle_owner: Optional[str] = None,
    ) -> Optional[dict[str, JSONValue]]:
        if project_ref is not None and project_ref != record.project_ref:
            return {"code": "scope_mismatch", "message": "project scope does not match the due record"}
        if manager_ref is not None and manager_ref != record.manager_ref:
            return {"code": "scope_mismatch", "message": "manager scope does not match the due record"}
        if generation is not None:
            if isinstance(generation, bool) or not isinstance(generation, int):
                return {"code": "stale_generation", "message": "generation must be an integer"}
            if generation != record.generation:
                return {"code": "stale_generation", "message": "generation is fenced"}
        if lifecycle_owner is not None and lifecycle_owner != record.lifecycle_owner:
            return {"code": "foreign_authority", "message": "lifecycle owner does not match the due record"}
        return None

    @staticmethod
    def _reasons(
        record: DueRecord,
        *,
        due_reason: Optional[str],
        due_reasons: Optional[Iterable[str]],
    ) -> tuple[str, ...]:
        values = list(due_reasons or ())
        if due_reason is not None:
            values.append(due_reason)
        if not values:
            if record.interval_seconds == 60 * 60:
                values.append("hourly")
            elif record.interval_seconds == 3 * 60 * 60:
                values.append("three-hour-review")
            else:
                values.append("scheduled")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("due reasons must contain non-blank text")
        return tuple(dict.fromkeys(values))

    def check(
        self,
        schedule_id: str,
        *,
        now: Optional[datetime] = None,
        due_reason: Optional[str] = None,
        due_reasons: Optional[Iterable[str]] = None,
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        generation: Optional[int] = None,
        lifecycle_owner: Optional[str] = None,
    ) -> dict[str, JSONValue]:
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule", "message": schedule_id}, "automatic_action": False}
        scope_error = self._scope_error(record, project_ref=project_ref, manager_ref=manager_ref, generation=generation, lifecycle_owner=lifecycle_owner)
        if scope_error is not None:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": scope_error, "relaunch": False, "automatic_action": False}
        if not self.host_available or (self.host_mode == "durable-host" and self.due_port is None):
            return {"outcome": "unavailable", "schedule_id": schedule_id, "capability": self.capability, "responsible_owner": record.owner, "automatic_action": False}
        requested_reasons = self._reasons(record, due_reason=due_reason, due_reasons=due_reasons)
        if record.stop_state != "active":
            return self._readiness(record, "stopped", due=False)
        if record.in_flight_request is not None:
            if any(reason not in record.due_reasons for reason in requested_reasons):
                merged = tuple(dict.fromkeys((*record.due_reasons, *requested_reasons)))
                try:
                    record = self._write(
                        DueRecord.from_dict({**record.to_dict(), "due_reasons": list(merged)}),
                        request_id="coalesce:" + record.in_flight_request + ":" + ":".join(merged),
                        expected_version=record.version,
                    )
                except StateConflictError:
                    record = self._read(schedule_id) or record
            return self._readiness(record, "in-flight", due=True, request_id=record.in_flight_request, delivery_state=record.delivery_state, replayed=True)
        observed_now = now or self.clock()
        slot = self._slot(record, observed_now)
        if slot is None or slot <= record.last_covered_slot:
            return self._readiness(record, "waiting", due=False)
        request_id = hashlib.sha256(f"{record.schedule_id}:{record.invocation_identity}:{slot}".encode("utf-8")).hexdigest()
        next_record = DueRecord.from_dict({**record.to_dict(), "last_covered_slot": slot, "in_flight_request": request_id, "delivery_state": "ready", "due_reasons": list(requested_reasons), "delivered_at": None, "delivery_evidence": None, "completed_at": None, "completion_evidence": None, "completion_state": "none"})
        try:
            stored = self._write(next_record, request_id=f"check:{request_id}", expected_version=record.version)
        except StateConflictError:
            current = self._read(schedule_id)
            if current is not None and current.in_flight_request is not None:
                return self._readiness(current, "in-flight", due=True, request_id=current.in_flight_request, delivery_state=current.delivery_state, replayed=True)
            raise
        request = {
            "request_id": request_id, "schedule_id": schedule_id, "recipient": stored.recipient,
            "instruction": stored.instruction, "profile": stored.profile, "anchor": stored.anchor,
            "message": stored.message or stored.instruction,
            "slot": slot, "missed_slots": max(0, slot - record.last_covered_slot - 1),
            "invocation_identity": stored.invocation_identity, "owner": stored.owner,
            "missing_handoff": stored.missing_handoff, "return_condition": stored.return_condition,
            "due_reasons": list(stored.due_reasons), "project_ref": stored.project_ref,
            "manager_ref": stored.manager_ref, "generation": stored.generation,
            "target": None if stored.target is None else dict(stored.target), "role": stored.role,
            "purpose": stored.purpose, "lifecycle_owner": stored.lifecycle_owner,
            "readiness": {"status": "attention", "dispatch": False, "executable": False},
        }
        try:
            response = dict(_json_copy(self.attention.create_attention(request), "attention response"))
        except Exception as exc:
            return {"outcome": "attention-error", "schedule_id": schedule_id, "request_id": request_id, "error": {"code": "attention_port_error", "message": str(exc)}, "reconcile": True, "relaunch": False, "automatic_action": False}
        # The owner has now accepted a delivery response.  Persist its time
        # and evidence separately from the later completion callback.
        delivered = DueRecord.from_dict({**stored.to_dict(), "delivered_at": _iso(observed_now), "delivery_evidence": response})
        try:
            stored = self._write(delivered, request_id="deliver:" + request_id, expected_version=stored.version)
        except StateConflictError:
            current = self._read(schedule_id)
            if current is not None:
                stored = current
        result = self._readiness(stored, "attention", due=True, request_id=request_id, delivery_state="ready")
        result.update({"notification": response, "event_ids": list(response.get("event_ids", ())), "missed_slots": request["missed_slots"], "replayed": response.get("outcome") == "replayed", "mutation": {"before": record.to_dict(), "action": request, "fresh_after": stored.to_dict()}, "expected_delta": {"last_covered_slot": slot, "in_flight_request": request_id}})
        return result

    @staticmethod
    def _readiness(record: DueRecord, state: str, *, due: bool, request_id: Optional[str] = None, delivery_state: Optional[str] = None, replayed: bool = False) -> dict[str, JSONValue]:
        return {
            "outcome": "attention-ready" if due else state, "schedule_id": record.schedule_id,
            "request_id": request_id or record.in_flight_request, "record": record.to_dict(),
            "readiness": {"status": state if state == "in-flight" else ("attention" if due else state), "dispatch": False, "executable": False},
            "responsible_owner": record.owner or record.recipient, "missing_handoff": record.missing_handoff,
            "return_condition": record.return_condition, "delivery_state": delivery_state or record.delivery_state,
            "due_reasons": list(record.due_reasons), "project_ref": record.project_ref,
            "manager_ref": record.manager_ref, "generation": record.generation,
            "target": None if record.target is None else dict(record.target), "role": record.role,
            "purpose": record.purpose, "message": record.message, "lifecycle_owner": record.lifecycle_owner,
            "host_state": record.host_state, "host_evidence": record.host_evidence,
            "delivered_at": record.delivered_at, "delivery_evidence": record.delivery_evidence,
            "completed_at": record.completed_at, "completion_evidence": record.completion_evidence,
            "completion_state": record.completion_state,
            "replayed": replayed, "automatic_action": False,
        }

    def complete(
        self,
        schedule_id: str,
        request_id: str,
        *,
        receipt: Optional[Mapping[str, JSONValue]] = None,
        outcome: str = "returned",
        completed_at: Optional[datetime] = None,
        completion_evidence: Optional[Mapping[str, JSONValue]] = None,
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        generation: Optional[int] = None,
        lifecycle_owner: Optional[str] = None,
    ) -> dict[str, JSONValue]:
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule", "message": schedule_id}, "automatic_action": False}
        scope_error = self._scope_error(record, project_ref=project_ref, manager_ref=manager_ref, generation=generation, lifecycle_owner=lifecycle_owner)
        if scope_error is not None:
            return {"outcome": "rejected", "request_id": request_id, "error": scope_error, "relaunch": False, "automatic_action": False}
        if record.last_completed_request == request_id and record.last_result is not None:
            return {**dict(record.last_result), "outcome": "replayed", "replayed": True, "expected_delta": "none", "automatic_action": False}
        if record.in_flight_request != request_id:
            return {"outcome": "reconcile", "error": {"code": "request_not_in_flight", "message": "only the recorded invocation may complete"}, "relaunch": False, "automatic_action": False}
        completion_time = _iso(completed_at or self.clock())
        evidence = completion_evidence if completion_evidence is not None else receipt
        if outcome in {"unknown", "crashed"}:
            state = DueRecord.from_dict({**record.to_dict(), "delivery_state": outcome, "completed_at": completion_time, "completion_evidence": evidence, "completion_state": "unknown"})
            stored = self._write(state, request_id=f"reconcile:{request_id}:{outcome}", expected_version=record.version)
            return {"outcome": "reconcile", "request_id": request_id, "record": stored.to_dict(), "relaunch": False, "same_request": True, "return_condition": stored.return_condition, "mutation": {"before": record.to_dict(), "action": {"request_id": request_id, "outcome": outcome}, "fresh_after": stored.to_dict()}, "automatic_action": False}
        if outcome in {"failed", "failure", "error"}:
            result = {"outcome": "completion-failed", "request_id": request_id, "receipt": None if receipt is None else dict(_json_copy(receipt, "receipt")), "relaunch": False, "same_request": True, "reconcile": True, "automatic_action": False}
            state = DueRecord.from_dict({**record.to_dict(), "completed_at": completion_time, "completion_evidence": evidence, "completion_state": "failed", "last_result": result})
            stored = self._write(state, request_id=f"complete-failed:{request_id}", expected_version=record.version)
            result["record"] = stored.to_dict()
            result["mutation"] = {"before": record.to_dict(), "action": {"request_id": request_id, "receipt": result["receipt"], "outcome": outcome}, "fresh_after": stored.to_dict()}
            return result
        result = {"outcome": "returned", "request_id": request_id, "receipt": None if receipt is None else dict(_json_copy(receipt, "receipt")), "relaunch": False, "same_request": True, "automatic_action": False}
        state = DueRecord.from_dict({**record.to_dict(), "in_flight_request": None, "delivery_state": "returned", "last_completed_request": request_id, "last_result": result, "completed_at": completion_time, "completion_evidence": evidence, "completion_state": "succeeded", "stop_state": "completed" if record.interval_seconds is None else "active"})
        stored = self._write(state, request_id=f"complete:{request_id}", expected_version=record.version)
        result["record"] = stored.to_dict()
        result["expected_delta"] = {"in_flight_request": None, "last_completed_request": request_id}
        result["mutation"] = {"before": record.to_dict(), "action": {"request_id": request_id, "receipt": result["receipt"], "outcome": outcome}, "fresh_after": stored.to_dict()}
        return result

    def mark_missed(
        self,
        schedule_id: str,
        *,
        now: Optional[datetime] = None,
        reason: str = "offline",
        project_ref: Optional[str] = None,
        manager_ref: Optional[str] = None,
        generation: Optional[int] = None,
        lifecycle_owner: Optional[str] = None,
    ) -> dict[str, JSONValue]:
        """Record one bounded missed period while preserving a future cursor."""
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule", "message": schedule_id}, "automatic_action": False}
        scope_error = self._scope_error(record, project_ref=project_ref, manager_ref=manager_ref, generation=generation, lifecycle_owner=lifecycle_owner)
        if scope_error is not None:
            return {"outcome": "rejected", "schedule_id": schedule_id, "error": scope_error, "relaunch": False, "automatic_action": False}
        slot = self._slot(record, now or self.clock())
        if slot is None or slot <= record.last_covered_slot:
            return self._readiness(record, "waiting", due=False)
        missed = max(0, slot - record.last_covered_slot - 1)
        state = DueRecord.from_dict({
            **record.to_dict(),
            "last_covered_slot": slot,
            "in_flight_request": None,
            "delivery_state": "unknown",
            "due_reasons": list(self._reasons(record, due_reason=reason, due_reasons=None)),
            "completed_at": _iso(now or self.clock()),
            "completion_state": "unknown",
            "completion_evidence": {"reason": reason, "missed_slots": missed},
        })
        request_id = "missed:" + schedule_id + ":" + str(slot)
        stored = self._write(state, request_id=request_id, expected_version=record.version)
        result = self._readiness(stored, "missed", due=False, delivery_state="unknown")
        result.update({"outcome": "missed", "missed_slots": missed, "reason": reason, "relaunch": False,
                       "mutation": {"before": record.to_dict(), "action": {"reason": reason, "slot": slot}, "fresh_after": stored.to_dict()},
                       "expected_delta": {"last_covered_slot": slot}, "automatic_action": False})
        return result

    def resume(self, schedule_id: str) -> dict[str, JSONValue]:
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule", "message": schedule_id}, "relaunch": False}
        if record.in_flight_request is None:
            return {"outcome": "waiting", "record": record.to_dict(), "relaunch": False, "automatic_action": False}
        return {"outcome": "resume-same-request", "request_id": record.in_flight_request, "record": record.to_dict(), "relaunch": False, "responsible_owner": record.owner or record.recipient, "return_condition": record.return_condition, "automatic_action": False}

    def stop(self, schedule_id: str, *, request_id: str) -> dict[str, JSONValue]:
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule", "message": schedule_id}}
        if record.stop_state == "stopped":
            return {"outcome": "replayed", "record": record.to_dict(), "automatic_action": False}
        stored = self._write(DueRecord.from_dict({**record.to_dict(), "stop_state": "stopped"}), request_id=f"stop:{request_id}", expected_version=record.version)
        return {"outcome": "stopped", "record": stored.to_dict(), "mutation": {"before": record.to_dict(), "action": {"request_id": request_id, "stop": True}, "fresh_after": stored.to_dict()}, "automatic_action": False}

    def record_decision(self, schedule_id: str, *, decision_id: str, decision: str, request_id: str) -> dict[str, JSONValue]:
        if decision not in {"wait", "act"}:
            raise ValueError("decision must be wait or act")
        record = self._read(schedule_id)
        if record is None:
            return {"outcome": "unknown", "error": {"code": "unknown_schedule", "message": schedule_id}}
        entry = {"decision_id": _required_text(decision_id, "decision_id"), "decision": decision, "recorded": True}
        decisions = tuple(item for item in record.outstanding_decisions if item.get("decision_id") != decision_id) + (entry,)
        stored = self._write(DueRecord.from_dict({**record.to_dict(), "outstanding_decisions": decisions}), request_id=f"decision:{request_id}", expected_version=record.version)
        return {"outcome": "decision-recorded", "record": stored.to_dict(), "mutation": {"before": record.to_dict(), "action": entry, "fresh_after": stored.to_dict()}, "automatic_action": False, "dispatch": False, "manager_created": False, "task_created": False, "budget_reserved": False}


class CursorContinuity:
    """A read-only continuity guard around the public EventCursorReader port."""

    def __init__(self, page: Callable[..., Any], *, authority: str, stream: str, event_filter: Any = None) -> None:
        self.page = page
        self.authority = _required_text(authority, "authority")
        self.stream = _required_text(stream, "stream")
        self.event_filter = event_filter
        self.cursor: Optional[str] = None
        self._seen_event_ids: set[str] = set()
        self._last_sequence = 0

    def read(self, *, cursor: Optional[str] = None, limit: int = 100) -> dict[str, JSONValue]:
        supplied = self.cursor if cursor is None else cursor
        try:
            page = self.page(self.stream, cursor=supplied, event_filter=self.event_filter, limit=limit)
        except Exception as exc:
            name = type(exc).__name__
            code = {"CursorMalformedError": "malformed", "CursorScopeError": "mismatch", "CursorExpiredError": "expired"}.get(name, "cursor-error")
            return {"outcome": "cursor-error", "error": {"code": code, "message": str(exc)}, "recoverable": True, "acknowledged": False, "cursor": supplied, "authority": self.authority, "stream": self.stream}
        events = tuple(getattr(page, "events", ()))
        values = []
        duplicate = False
        out_of_order = False
        for event in events:
            event_id = getattr(event, "event_id", None)
            sequence = getattr(event, "sequence", None)
            if event_id in self._seen_event_ids:
                duplicate = True
            if isinstance(sequence, int) and sequence <= self._last_sequence:
                out_of_order = True
            if event_id is not None:
                self._seen_event_ids.add(event_id)
            if isinstance(sequence, int):
                self._last_sequence = max(self._last_sequence, sequence)
            to_dict = getattr(event, "to_dict", None)
            values.append(_json_copy(to_dict() if callable(to_dict) else event, "event"))
        status = getattr(page, "status", "ok")
        self.cursor = getattr(page, "next_cursor", None) or getattr(page, "cursor", supplied)
        if status == "gap":
            outcome = "gap"
        elif duplicate:
            outcome = "duplicate-read"
        elif out_of_order:
            outcome = "out-of-order"
        else:
            outcome = "ok"
        return {"outcome": outcome, "events": values, "cursor": getattr(page, "cursor", None), "next_cursor": getattr(page, "next_cursor", None), "authority": self.authority, "stream": self.stream, "filter": _json_copy(getattr(self.event_filter, "to_dict", lambda: self.event_filter)(), "filter") if self.event_filter is not None else None, "acknowledged": False, "recoverable": outcome in {"gap", "out-of-order", "duplicate-read"}, "gap_from": getattr(page, "gap_from", None), "gap_to": getattr(page, "gap_to", None)}

    def acknowledge(self, cursor: Optional[str] = None) -> dict[str, JSONValue]:
        """Record only caller intent; reading itself never acknowledges."""
        return {"outcome": "acknowledged", "cursor": cursor or self.cursor, "acknowledged": True, "authority": self.authority, "stream": self.stream}


EventCursorReaderAdapter = CursorContinuity
AttentionScheduler = DurableAttention
DurableAttentionService = DurableAttention


__all__ = [
    "AmendmentInterruptedError", "AmendmentPort", "AttentionError", "AttentionScheduler", "CursorContinuity", "CursorContinuityError", "DueRecord", "DueRecordPort",
    "DurableAttention", "DurableAttentionService", "EventCursorReaderAdapter", "HostTriggerPort", "HostUnavailableError", "InMemoryDueRecordPort",
    "ImprovementPropagation", "InputChangedError", "RecordingAttentionPort", "RecordingHostTriggerPort", "SerializedAmendmentPort", "SerializedAttentionPort", "SharedAttentionPort", "StateConflictError",
    "StoreDueRecordPort", "due_record_contribution", "issue_store_amendment_port", "issue_store_due_record_port",
]
