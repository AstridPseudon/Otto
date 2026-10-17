"""Neutral durable operation identity and adapter-context mechanics.

This module deliberately does not invoke an adapter.  It records the request
and each explicit outcome through the FND-03 ``Store`` transaction port.  The
operation identity, physical invocation reference, and authoritative external
owner are separate values so an adapter cannot accidentally collapse them into
one product-specific authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from typing import Any, ContextManager, Mapping, Optional, Protocol, Sequence, runtime_checkable

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    ReceiptStatus,
    ResourceRef,
    TransactionContext,
    canonical_request_digest,
    canonical_json,
    validate_replay,
)

from herzchen.command_ports import command_facade
from .store import StoreError, TargetMismatchError, Transaction, VersionConflictError, coerce_operation_owner


OPERATION_SCHEMA_REVISION = "fnd-04.operation.v1"
OPERATION_KIND = "operation"
OPERATION_STREAM = "operations"
_UNSET = object()


class OperationError(StoreError):
    """Base error for neutral operation admission and state transitions."""


class OperationState(str, Enum):
    PREPARED = "prepared"
    STARTED = "started"
    COMMITTED = "committed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNCERTAIN = "uncertain"


class UnknownOutcomeError(OperationError):
    """An unknown operation requires an explicit resolution."""


@runtime_checkable
class OperationOwner(Protocol):
    """Typed trusted-owner seam required by the operation manager.

    Implementations are issued by FND Store composition.  The protocol is
    deliberately limited to transaction/savepoint admission, durable reads,
    exact descriptor lookup, and the common mutation writer; it is not a
    consumer-facing Store substitute.
    """

    authority: str
    reader: Any
    domain_descriptor_digest: str

    def registered_domains(self) -> Sequence[Any]: ...
    def ensure_durable_start_boundary(self) -> None: ...
    def transaction(self) -> ContextManager[Transaction]: ...
    def mutate(self, envelope: CommandEnvelope, *, event_type: str, result_ref: Optional[ResourceRef] = None,
               before_refs: Sequence[ResourceRef] = (), after_refs: Sequence[ResourceRef] = (),
               effects: Optional[Mapping[str, Any]] = None, stream: Optional[str] = None,
               event_schema_revision: str = "fnd-03.event.v1", occurred_at: Optional[str] = None,
               no_op: bool = False, transaction: Optional[Transaction] = None) -> CommandReceipt: ...
    def get_identity(self, ref: ResourceRef) -> Any: ...
    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]: ...
    def list_events(self, *, stream: Optional[str] = None) -> Sequence[Any]: ...
    def lookup_replay(self, envelope: CommandEnvelope) -> Optional[CommandReceipt]: ...
    def event_lineage(self, receipt: CommandReceipt) -> Sequence[Any]: ...


@dataclass(frozen=True)
class OperationRequest:
    """Validated request and neutral adapter context.

    ``logical_request_key`` and ``request_digest`` identify the durable
    command.  The three references are intentionally independent: the
    operation identity is created by this module, while the adapter context,
    physical invocation, and external owner are supplied by a caller.
    """

    operation: str
    schema_revision: str
    adapter_ref: ResourceRef
    actor: AuthenticatedActor
    logical_request_key: str
    request_digest: str
    payload: Mapping[str, Any]
    physical_invocation_ref: Optional[ResourceRef] = None
    external_owner_ref: Optional[ResourceRef] = None
    expected_revision: Optional[str] = None
    expected_version: Optional[int] = None
    edit_token: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise OperationError("operation must be a non-blank string")
        if not isinstance(self.schema_revision, str) or not self.schema_revision.strip():
            raise OperationError("schema_revision must be a non-blank string")
        if not isinstance(self.adapter_ref, ResourceRef):
            raise OperationError("adapter_ref must be a ResourceRef")
        if not isinstance(self.actor, AuthenticatedActor):
            raise OperationError("actor must be an AuthenticatedActor")
        if not isinstance(self.payload, Mapping):
            raise OperationError("payload must be a mapping")
        if self.physical_invocation_ref is not None and not isinstance(self.physical_invocation_ref, ResourceRef):
            raise OperationError("physical_invocation_ref must be a ResourceRef")
        if self.external_owner_ref is not None and not isinstance(self.external_owner_ref, ResourceRef):
            raise OperationError("external_owner_ref must be a ResourceRef")
        # Constructing the neutral FND context performs the canonical key and
        # digest validation before a writer transaction is admitted.
        TransactionContext(
            self.actor,
            self.logical_request_key,
            self.request_digest,
            expected_revision=self.expected_revision,
            expected_version=self.expected_version,
            edit_token=self.edit_token,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
        )
        canonical_json(dict(self.payload))

    def semantic_payload(self) -> dict[str, Any]:
        """Return request arguments whose meaning is fixed by this request."""
        return {
            "adapter_ref": self.adapter_ref.to_dict(),
            "payload": dict(self.payload),
            "physical_invocation_ref": _ref_dict(self.physical_invocation_ref),
            "external_owner_ref": _ref_dict(self.external_owner_ref),
        }

    def _context(
        self,
        *,
        expected_revision: Any = _UNSET,
        expected_version: Any = _UNSET,
        edit_token: Any = _UNSET,
        correlation_id: Any = _UNSET,
        causation_id: Any = _UNSET,
    ) -> TransactionContext:
        return TransactionContext(
            self.actor,
            self.logical_request_key,
            self.request_digest,
            expected_revision=self.expected_revision if expected_revision is _UNSET else expected_revision,
            expected_version=self.expected_version if expected_version is _UNSET else expected_version,
            edit_token=self.edit_token if edit_token is _UNSET else edit_token,
            correlation_id=self.correlation_id if correlation_id is _UNSET else correlation_id,
            causation_id=self.causation_id if causation_id is _UNSET else causation_id,
        )

    def canonical_digest(
        self,
        target: ResourceRef,
        *,
        expected_revision: Any = _UNSET,
        expected_version: Any = _UNSET,
        edit_token: Any = _UNSET,
        correlation_id: Any = _UNSET,
        causation_id: Any = _UNSET,
    ) -> str:
        context = self._context(
            expected_revision=expected_revision,
            expected_version=expected_version,
            edit_token=edit_token,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return canonical_request_digest(
            logical_request_key=context.logical_request_key,
            operation=self.operation,
            schema_revision=self.schema_revision,
            target=target,
            actor=context.actor,
            payload=self.semantic_payload(),
            context=context,
        )

    def canonicalized(self, target: ResourceRef, **context_fields: Any) -> "OperationRequest":
        """Return the request with its digest bound to admitted semantics."""
        context = self._context(**context_fields)
        return replace(
            self,
            request_digest=self.canonical_digest(target, **context_fields),
            expected_revision=context.expected_revision,
            expected_version=context.expected_version,
            edit_token=context.edit_token,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )

    def envelope(
        self,
        target: ResourceRef,
        *,
        expected_revision: Any = _UNSET,
        expected_version: Any = _UNSET,
        edit_token: Any = _UNSET,
        correlation_id: Any = _UNSET,
        causation_id: Any = _UNSET,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> CommandEnvelope:
        envelope_payload = dict(self.payload if payload is None else payload)
        context = self._context(
            expected_revision=expected_revision,
            expected_version=expected_version,
            edit_token=edit_token,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return CommandEnvelope(
            self.operation,
            self.schema_revision,
            target,
            TransactionContext(
                context.actor,
                self.logical_request_key,
                canonical_request_digest(
                    logical_request_key=context.logical_request_key,
                    operation=self.operation,
                    schema_revision=self.schema_revision,
                    target=target,
                    actor=context.actor,
                    payload=envelope_payload,
                    context=context,
                ),
                expected_revision=context.expected_revision,
                expected_version=context.expected_version,
                edit_token=context.edit_token,
                correlation_id=context.correlation_id,
                causation_id=context.causation_id,
            ),
            envelope_payload,
        )


# The brief uses both “operation context” and “request”.  Keep one canonical
# type while offering the neutral context spelling to adapters.
OperationContext = OperationRequest


@dataclass(frozen=True)
class OperationRecord:
    operation_ref: ResourceRef
    request: OperationRequest
    state: OperationState
    result: Mapping[str, Any]
    receipt: Optional[CommandReceipt]
    version: int

    @property
    def logical_receipt(self) -> Optional[CommandReceipt]:
        return self.receipt

    @property
    def effect_ref(self) -> ResourceRef:
        """Stable effect identity, distinct from the operation and invocation."""
        return ResourceRef(self.operation_ref.authority, "effect", self.operation_ref.id)

    @property
    def physical_invocation_ref(self) -> Optional[ResourceRef]:
        return self.request.physical_invocation_ref

    @property
    def external_owner_ref(self) -> Optional[ResourceRef]:
        return self.request.external_owner_ref


def request_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical digest helper for callers constructing requests."""
    return hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _ref_dict(ref: Optional[ResourceRef]) -> Optional[dict[str, Any]]:
    return None if ref is None else ref.to_dict()


def _ref(value: Optional[Mapping[str, Any]]) -> Optional[ResourceRef]:
    return None if value is None else ResourceRef.from_dict(value)


class _OperationManagerEngine:
    """Record operation requests and explicit outcomes; never invoke them."""

    def __init__(self, owner: OperationOwner) -> None:
        # Existing trusted constructors pass Store for compatibility. Convert
        # it once at the bootstrap boundary; the operation engine retains only
        # the typed capability and never a concrete writer/handler graph.
        self.__owner: OperationOwner = coerce_operation_owner(owner)
        self.reader = self.__owner.reader

    def _target(self, logical_request_key: str) -> ResourceRef:
        return ResourceRef(self.__owner.authority, OPERATION_KIND, logical_request_key)

    def _payload(self, request: OperationRequest, state: OperationState, result: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "record_type": OPERATION_KIND,
            "operation": request.operation,
            "schema_revision": request.schema_revision,
            "adapter_ref": request.adapter_ref.to_dict(),
            "request_actor": request.actor.to_dict(),
            "logical_request_key": request.logical_request_key,
            "request_digest": request.request_digest,
            "request_payload": dict(request.payload),
            "physical_invocation_ref": _ref_dict(request.physical_invocation_ref),
            "external_owner_ref": _ref_dict(request.external_owner_ref),
            "expected_revision": request.expected_revision,
            "expected_version": request.expected_version,
            "edit_token": request.edit_token,
            "correlation_id": request.correlation_id,
            "causation_id": request.causation_id,
            "state": state.value,
            "result": dict(result),
        }

    def _record_from_event(self, receipt: CommandReceipt, event_effects: Mapping[str, Any], request: OperationRequest, operation_ref: ResourceRef, version: int) -> OperationRecord:
        state = OperationState(event_effects["state"])
        result = dict(event_effects.get("result", {}))
        recorded_request = OperationRequest(
            request.operation,
            request.schema_revision,
            ResourceRef.from_dict(event_effects.get("adapter_ref", request.adapter_ref.to_dict())),
            AuthenticatedActor.from_dict(event_effects.get("request_actor", request.actor.to_dict())),
            request.logical_request_key,
            event_effects.get("request_digest", request.request_digest),
            event_effects.get("request_payload", request.payload),
            _ref(event_effects.get("physical_invocation_ref")),
            _ref(event_effects.get("external_owner_ref")),
            event_effects.get("expected_revision", request.expected_revision),
            event_effects.get("expected_version", request.expected_version),
            event_effects.get("edit_token", request.edit_token),
            event_effects.get("correlation_id", request.correlation_id),
            event_effects.get("causation_id", request.causation_id),
        )
        return OperationRecord(operation_ref, recorded_request, state, result, receipt, version)

    def _event_for_receipt(self, receipt: CommandReceipt) -> Mapping[str, Any]:
        if not receipt.event_ids:
            return {"state": OperationState.PREPARED.value, "result": {}, "version": 1}
        for event in self.__owner.event_lineage(receipt):
            if event.stream == OPERATION_STREAM:
                return event.effects
        raise OperationError("receipt event is not visible in the admitted store")

    def _request_from_identity(self, payload: Mapping[str, Any], actor: Optional[AuthenticatedActor] = None) -> OperationRequest:
        request_actor = actor
        if request_actor is None and payload.get("request_actor") is not None:
            request_actor = AuthenticatedActor.from_dict(payload["request_actor"])
        if request_actor is None:
            raise OperationError("operation actor is absent from identity and event lineage")
        return OperationRequest(
            payload["operation"],
            payload["schema_revision"],
            ResourceRef.from_dict(payload["adapter_ref"]),
            request_actor,
            payload["logical_request_key"],
            payload["request_digest"],
            payload.get("request_payload", {}),
            _ref(payload.get("physical_invocation_ref")),
            _ref(payload.get("external_owner_ref")),
            payload.get("expected_revision"),
            payload.get("expected_version"),
            payload.get("edit_token"),
            payload.get("correlation_id"),
            payload.get("causation_id"),
        )

    def prepare(self, request: OperationRequest, *, transaction: Optional[Transaction] = None) -> OperationRecord:
        if not isinstance(request, OperationRequest):
            raise TypeError("request must be an OperationRequest")
        target = self._target(request.logical_request_key)
        # Keep the caller's request context as the logical operation identity.
        # The create-state check is an admitted Store concern and must not
        # overwrite that context before it is hashed or persisted.
        request = request.canonicalized(target)
        payload = self._payload(request, OperationState.PREPARED, {})
        envelope = request.envelope(
            target,
            expected_revision=None,
            expected_version=0,
            edit_token=None,
            payload=payload,
        )
        effects = {
            "state": OperationState.PREPARED.value,
            "effect_ref": ResourceRef(self.__owner.authority, "effect", request.logical_request_key).to_dict(),
            "result": {},
            "adapter_ref": request.adapter_ref.to_dict(),
            "request_actor": request.actor.to_dict(),
            "physical_invocation_ref": _ref_dict(request.physical_invocation_ref),
            "external_owner_ref": _ref_dict(request.external_owner_ref),
            "request_payload": dict(request.payload),
            "request_digest": request.request_digest,
            "expected_revision": request.expected_revision,
            "expected_version": request.expected_version,
            "edit_token": request.edit_token,
            "correlation_id": request.correlation_id,
            "causation_id": request.causation_id,
            "version": 1,
        }
        receipt = self.__owner.mutate(
            envelope,
            event_type="operation.prepared",
            result_ref=ResourceRef(self.__owner.authority, OPERATION_KIND, request.logical_request_key, "rev-1"),
            effects=effects,
            stream=OPERATION_STREAM,
            transaction=transaction,
        )
        event_effects = self._event_for_receipt(receipt)
        identity = self.__owner.get_identity(target)
        version = int(event_effects.get("version", identity.version if identity else 1))
        operation_ref = receipt.result_ref or (identity.ref if identity else target)
        return self._record_from_event(receipt, event_effects, request, operation_ref, version)

    def claim_start(self, record: OperationRecord, *, transition_key: Optional[str] = None, transaction: Optional[Transaction] = None) -> OperationRecord:
        """Commit the one start claim before the caller invokes its effect.

        The returned STARTED record is the caller's permission to invoke once.
        A later caller, including one replaying the same key, receives a hold
        instead of another permission.  A reconstructed STARTED identity reads
        as UNKNOWN because its external outcome cannot be inferred.
        """
        if not isinstance(record, OperationRecord):
            raise TypeError("record must be an OperationRecord")
        if transaction is not None:
            raise OperationError("start claim must commit before external invocation")
        self.__owner.ensure_durable_start_boundary()
        target = record.operation_ref
        if target.revision is None:
            raise OperationError("operation record must carry its current revision")
        if record.state is not OperationState.PREPARED:
            raise UnknownOutcomeError("effect is already started or held")
        start_key = transition_key or record.request.logical_request_key + ":start"
        if self.__owner.get_receipt(start_key) is not None:
            raise UnknownOutcomeError("effect start claim already exists")
        identity = self.__owner.get_identity(target)
        if identity is None or identity.ref != target or identity.version != record.version or identity.payload.get("state") != OperationState.PREPARED.value:
            raise UnknownOutcomeError("effect is already started or held")
        if self._request_from_identity(identity.payload) != record.request:
            raise OperationError("start claim does not match the prepared effect")
        if identity.payload.get("effect_ref", record.effect_ref.to_dict()) != record.effect_ref.to_dict():
            raise OperationError("prepared effect identity does not match its operation")
        start_request = OperationRequest(
            "operation.start", record.request.schema_revision, record.request.adapter_ref,
            record.request.actor, start_key, request_digest({"effect_ref": record.effect_ref.to_dict()}),
            {"effect_ref": record.effect_ref.to_dict()},
            record.request.physical_invocation_ref, record.request.external_owner_ref,
            record.request.expected_revision, record.request.expected_version,
            record.request.edit_token, record.request.correlation_id, record.request.causation_id,
        )
        payload = self._payload(record.request, OperationState.STARTED, {})
        payload["effect_ref"] = record.effect_ref.to_dict()
        envelope = start_request.envelope(
            target, expected_revision=target.revision, expected_version=record.version,
            edit_token=None, payload=payload,
        )
        effects = dict(payload)
        effects["version"] = record.version + 1
        try:
            receipt = self.__owner.mutate(
                envelope, event_type="operation.started",
                result_ref=ResourceRef(target.authority, target.kind, target.id, "rev-{}".format(record.version + 1)),
                effects=effects, stream=OPERATION_STREAM,
            )
        except (TargetMismatchError, VersionConflictError) as exc:
            raise UnknownOutcomeError("effect is already started or held") from exc
        if receipt.replayed:
            raise UnknownOutcomeError("effect start claim already exists")
        if receipt.logical_request_key != start_key or receipt.result_ref is None:
            raise OperationError("start claim has no durable result")
        event_effects = self._event_for_receipt(receipt)
        return self._record_from_event(receipt, event_effects, record.request, receipt.result_ref, int(event_effects["version"]))

    def _transition(
        self,
        record: OperationRecord,
        state: OperationState,
        result: Mapping[str, Any],
        *,
        transition_key: Optional[str],
        transition_digest: Optional[str],
        physical_invocation_ref: Optional[ResourceRef],
        external_owner_ref: Optional[ResourceRef],
        allow_unknown_resolution: bool,
        transition_actor: AuthenticatedActor,
        transaction: Optional[Transaction],
        resolution_evidence: Optional[Mapping[str, str]] = None,
    ) -> OperationRecord:
        if not isinstance(result, Mapping):
            raise OperationError("result must be a mapping")
        next_request_key = transition_key or (record.request.logical_request_key + ":outcome")
        # The optional legacy digest is deliberately not trusted.  The
        # envelope derives the transition digest from its full semantics.
        next_request = OperationRequest(
            "operation.outcome",
            record.request.schema_revision,
            record.request.adapter_ref,
            transition_actor,
            next_request_key,
            request_digest({"operation": record.request.logical_request_key, "state": state.value, "result": dict(result)}),
            {
                "original_request_payload": dict(record.request.payload),
                "state": state.value,
                "result": dict(result),
            },
            physical_invocation_ref if physical_invocation_ref is not None else record.request.physical_invocation_ref,
            external_owner_ref if external_owner_ref is not None else record.request.external_owner_ref,
            record.request.expected_revision,
            record.request.expected_version,
            record.request.edit_token,
            record.request.correlation_id,
            record.request.causation_id,
        )
        target = record.operation_ref
        if target.revision is None:
            raise OperationError("operation record must carry its current revision")
        identity_request = OperationRequest(
            record.request.operation,
            record.request.schema_revision,
            record.request.adapter_ref,
            record.request.actor,
            record.request.logical_request_key,
            record.request.request_digest,
            record.request.payload,
            next_request.physical_invocation_ref,
            next_request.external_owner_ref,
            record.request.expected_revision,
            record.request.expected_version,
            record.request.edit_token,
            record.request.correlation_id,
            record.request.causation_id,
        )
        payload = self._payload(identity_request, state, result)
        if resolution_evidence is not None:
            payload["resolution_evidence"] = dict(resolution_evidence)
        envelope = next_request.envelope(
            target,
            expected_revision=target.revision,
            expected_version=record.version,
            edit_token=None,
            payload=payload,
        )
        prior = self.__owner.lookup_replay(envelope)
        if prior is not None:
            event_effects = self._event_for_receipt(prior)
            return self._record_from_event(prior, event_effects, record.request, prior.result_ref or target, int(event_effects.get("version", record.version + 1)))
        if record.state in (OperationState.UNKNOWN, OperationState.UNCERTAIN) and not allow_unknown_resolution:
            raise UnknownOutcomeError("unknown operation outcome requires explicit resolution")
        if record.state not in (OperationState.PREPARED, OperationState.STARTED, OperationState.UNKNOWN, OperationState.UNCERTAIN):
            raise OperationError("operation already has a terminal outcome")
        effects = {
            "state": state.value,
            "result": dict(result),
            "adapter_ref": next_request.adapter_ref.to_dict(),
            "request_actor": record.request.actor.to_dict(),
            "physical_invocation_ref": _ref_dict(next_request.physical_invocation_ref),
            "external_owner_ref": _ref_dict(next_request.external_owner_ref),
            "request_payload": dict(record.request.payload),
            "request_digest": record.request.request_digest,
            "expected_revision": record.request.expected_revision,
            "expected_version": record.request.expected_version,
            "edit_token": record.request.edit_token,
            "correlation_id": record.request.correlation_id,
            "causation_id": record.request.causation_id,
            "version": record.version + 1,
        }
        if resolution_evidence is not None:
            effects["resolution_evidence"] = dict(resolution_evidence)
        try:
            receipt = self.__owner.mutate(
                envelope,
                event_type="operation.outcome",
                result_ref=ResourceRef(target.authority, target.kind, target.id, "rev-{}".format(record.version + 1)),
                effects=effects,
                stream=OPERATION_STREAM,
                transaction=transaction,
            )
        except (TargetMismatchError, VersionConflictError) as exc:
            if not allow_unknown_resolution:
                raise
            raise UnknownOutcomeError("held effect was already reconciled or changed") from exc
        event_effects = self._event_for_receipt(receipt)
        new_ref = receipt.result_ref or target
        return self._record_from_event(receipt, event_effects, identity_request, new_ref, int(event_effects.get("version", record.version + 1)))

    def record_outcome(self, record: OperationRecord, state: OperationState, result: Optional[Mapping[str, Any]] = None, *, transition_key: Optional[str] = None, transition_digest: Optional[str] = None, physical_invocation_ref: Optional[ResourceRef] = None, external_owner_ref: Optional[ResourceRef] = None, transaction: Optional[Transaction] = None) -> OperationRecord:
        if not isinstance(state, OperationState):
            state = OperationState(state)
        if state not in (OperationState.COMMITTED, OperationState.FAILED, OperationState.UNKNOWN, OperationState.UNCERTAIN):
            raise OperationError("record_outcome requires a terminal or uncertain state")
        return self._transition(record, state, result or {}, transition_key=transition_key, transition_digest=transition_digest, physical_invocation_ref=physical_invocation_ref, external_owner_ref=external_owner_ref, allow_unknown_resolution=False, transition_actor=record.request.actor, transaction=transaction)

    def resolve_unknown(self, record: OperationRecord, state: OperationState, result: Optional[Mapping[str, Any]] = None, *, resolver: Optional[AuthenticatedActor] = None, evidence_key: Optional[str] = None, transition_key: Optional[str] = None, transition_digest: Optional[str] = None, physical_invocation_ref: Optional[ResourceRef] = None, external_owner_ref: Optional[ResourceRef] = None, transaction: Optional[Transaction] = None) -> OperationRecord:
        """Settle a held effect from one exact, retained terminal proof.

        A proof is a committed owner receipt with one linked effect.terminal
        event. Its effect identity, terminal state, and result must equal this
        resolution claim. A missing or changed proof leaves the hold intact.
        """
        if not isinstance(record, OperationRecord) or record.state not in (OperationState.UNKNOWN, OperationState.UNCERTAIN):
            raise UnknownOutcomeError("only a held effect can be reconciled")
        if state not in (OperationState.COMMITTED, OperationState.FAILED):
            raise OperationError("unknown resolution must be committed or failed")
        if not isinstance(resolver, AuthenticatedActor):
            raise OperationError("unknown resolution requires an authenticated resolver")
        if (physical_invocation_ref is not None and physical_invocation_ref != record.request.physical_invocation_ref
                or external_owner_ref is not None and external_owner_ref != record.request.external_owner_ref):
            raise UnknownOutcomeError("resolution cannot change held effect custody")
        if not isinstance(evidence_key, str) or not evidence_key.strip():
            raise UnknownOutcomeError("held effect requires a retained terminal proof")
        if not isinstance(result, Mapping) and result is not None:
            raise OperationError("result must be a mapping")
        claimed_result = dict(result or {})
        receipt = self.__owner.get_receipt(evidence_key)
        if (receipt is None or receipt.status is not ReceiptStatus.COMMITTED
                or receipt.target.authority != self.__owner.authority
                or receipt.result_ref is None or receipt.result_ref.authority != self.__owner.authority
                or len(receipt.event_ids) != 1):
            raise UnknownOutcomeError("held effect has no exact local terminal proof")
        events = self.__owner.event_lineage(receipt)
        if len(events) != 1 or events[0].event_id != receipt.event_ids[0]:
            raise UnknownOutcomeError("held effect terminal proof is incomplete")
        event = events[0]
        if (event.store_authority != self.__owner.authority
                or event.subject != receipt.result_ref
                or event.event_type != "effect.terminal"
                or event.effects.get("effect_ref") != record.effect_ref.to_dict()
                or event.effects.get("state") != state.value
                or event.effects.get("result") != claimed_result):
            raise UnknownOutcomeError("terminal proof does not match the held effect and claim")
        evidence = {"evidence_key": evidence_key, "event_id": event.event_id, "request_digest": receipt.request_digest}
        return self._transition(record, state, claimed_result, transaction=transaction, transition_key=transition_key, transition_digest=transition_digest, physical_invocation_ref=physical_invocation_ref, external_owner_ref=external_owner_ref, allow_unknown_resolution=True, transition_actor=resolver, resolution_evidence=evidence)

    def get(self, logical_request_key: str) -> Optional[OperationRecord]:
        target = self._target(logical_request_key)
        identity = self.__owner.get_identity(target)
        if identity is None or identity.payload.get("record_type") != OPERATION_KIND:
            return None
        lineage_actor = next(
            (
                event.actor
                for event in self.__owner.list_events(stream=OPERATION_STREAM)
                if event.subject.authority == identity.ref.authority
                and event.subject.kind == identity.ref.kind
                and event.subject.id == identity.ref.id
                and event.event_type == "operation.prepared"
            ),
            None,
        )
        request = self._request_from_identity(identity.payload, actor=lineage_actor)
        receipt = self.__owner.get_receipt(request.logical_request_key)
        state = OperationState(identity.payload["state"])
        if state is OperationState.STARTED:
            state = OperationState.UNKNOWN
        return OperationRecord(identity.ref, request, state, dict(identity.payload.get("result", {})), receipt, identity.version)


OperationManager = command_facade(_OperationManagerEngine, "herzchen.kernel.operations")
OperationAdapter = OperationManager


__all__ = [
    "OPERATION_KIND", "OPERATION_SCHEMA_REVISION", "OperationError", "UnknownOutcomeError",
    "OperationOwner", "OperationState", "OperationRequest", "OperationContext", "OperationRecord",
    "OperationManager", "OperationAdapter", "request_digest",
]
