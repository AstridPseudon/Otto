"""The sole neutral FND-03 SQLite owner and common record writer."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import inspect
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import threading
import time
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple, Union

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    ContractError,
    DomainContribution,
    DomainRegistry,
    EventEnvelope,
    ReceiptStatus,
    ReplayConflictError,
    ResourceRef,
    canonical_json,
    canonical_request_digest,
    validate_expected_state,
    validate_replay,
)

from herzchen.command_ports import command_facade
from .schema import (COMPOSITION, DDL, SCHEMA_FINGERPRINT, SCHEMA_REVISION, IDENTITY_LOOKUP_INDEXES,
                     LEGACY_SCHEMA_REVISION, SUPPORTED_SCHEMAS, verify_physical_schema)
from .history import (HISTORY_SCHEMA, MAX_SUMMARY_BYTES, MAX_INLINE_FACETS,
                      transition, project_relations)


FND02_CONTRACT_REVISION = "fnd-02.v1.1"
FND02_CONTRACT_DIGEST = "28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264"


class StoreError(RuntimeError):
    """Base error for store admission, ownership, and transaction failures."""


class StoreAdmissionError(StoreError):
    """The database is not an admitted FND-03 composition."""


class AdmissionStopped(StoreAdmissionError):
    """Cooperative cancellation of admission, before a writer is returned."""


# Change whenever the admitted invariants in _verify change.
ADMISSION_CHECK_REVISION = "fnd.clean-close-check.2"
_CLEAN_CLOSE_SCHEMA = "fnd.clean-close-admission.v1"


class MigrationRequiredError(StoreAdmissionError):
    """Legacy stores require explicit closed-owner migration before writes."""


class StoreExistsError(StoreAdmissionError):
    """Create was requested for an already initialized database."""


class SchemaMismatchError(StoreAdmissionError):
    """Schema revision or fingerprint does not match the declared baseline."""


class CompositionMismatchError(StoreAdmissionError):
    """The database has missing or unknown user tables."""


class WriterBusyError(StoreError):
    """Another process or store instance owns the durable writer lock."""


class ClosedStoreError(StoreError):
    """An operation was attempted after close or failed admission."""


class TargetMismatchError(StoreError):
    """The requested target/reference is not the current stored identity."""


class VersionConflictError(StoreError):
    """The expected revision or version does not match current state."""


class DescriptorDigestMismatchError(StoreAdmissionError):
    """Persisted optional-domain descriptors do not match their digest."""


class DescriptorExpectationMismatchError(StoreAdmissionError):
    """Caller-supplied descriptor composition is not exactly admitted."""


class MutationAdmissionError(StoreError):
    """A command/resource/event combination has no admitted owner handler."""


DOMAIN_KIND = "domain"
DOMAIN_DESCRIPTOR_DIGEST_KEY = "domain_descriptor_digest"
EMPTY_DOMAIN_DESCRIPTOR_DIGEST = hashlib.sha256(b"[]").hexdigest()
_OWNER_CONSTRUCTION_TOKEN = object()
_HANDLER_CONSTRUCTION_TOKEN = object()
_COMMAND_PORT_CONSTRUCTION_TOKEN = object()
_OPERATION_OWNER_CONSTRUCTION_TOKEN = object()
_RUNTIME_OWNER_CONSTRUCTION_TOKEN = object()
_RUNTIME_DOMAIN_OWNER_CONSTRUCTION_TOKEN = object()


class RuntimeOperationReader:
    """Nominal finite read surface supplied by a foreign Runtime owner.

    Runtime composition may keep its own storage and transaction implementation,
    but the operation kernel receives this explicitly typed reader only.  The
    class intentionally has no fallback attribute forwarding; a Runtime
    adapter implements the listed read methods and nothing writer-shaped is
    admitted through this boundary.
    """

    __slots__ = ()
    _fnd_runtime_reader_marker = _RUNTIME_OWNER_CONSTRUCTION_TOKEN


class RuntimeOperationOwner:
    """Nominal foreign owner bridge for one already-open Runtime owner.

    A Runtime adapter subclasses this type and supplies the OperationOwner
    protocol methods.  Nominal admission prevents an arbitrary consumer object
    with Store-shaped attributes from being treated as an owner capability.
    """

    __slots__ = ()
    _fnd_runtime_owner_marker = _RUNTIME_OWNER_CONSTRUCTION_TOKEN


class RuntimeDomainOwner:
    """Nominal foreign owner bridge for one registered domain contribution.

    This is deliberately distinct from ``RuntimeOperationOwner``: domain
    services receive a scoped capability for their exact registered domain,
    while the kernel operation capability remains a separate seam.
    """

    __slots__ = ()
    _fnd_runtime_domain_owner_marker = _RUNTIME_DOMAIN_OWNER_CONSTRUCTION_TOKEN


class DomainCommandPort:
    """Finite command adapter issued by trusted Store composition.

    The port deliberately has no Store-shaped API.  It exposes only the exact
    command endpoints declared by one adapter engine, validates every call
    against that endpoint's Python signature, and keeps the trusted engine in
    a slot that is outside the supported consumer surface.  Ordinary callers
    therefore receive the same domain methods as the command object, never a
    connection, transaction factory, generic mutation operation, or direct
    identity/reference writer.
    """

    __slots__ = ("__engine", "__endpoints", "__reader", "__domain_id")

    _FORBIDDEN = frozenset({
        "connection", "transaction", "mutate", "put_identity",
        "revise_identity", "put_reference", "append_event",
        "register_domain", "register_domain_handler", "domain_handler",
    })

    def __init__(
        self,
        engine: Any,
        domain_id: str,
        endpoints: Sequence[str],
        reader: Optional["ConsumerStore"],
        *,
        _construction_token: object = None,
    ) -> None:
        if _construction_token is not _COMMAND_PORT_CONSTRUCTION_TOKEN:
            raise StoreAdmissionError("domain command ports are issued only by trusted Store composition")
        if not isinstance(domain_id, str) or not domain_id.strip():
            raise TypeError("domain_id must be a non-blank string")
        exact = tuple(dict.fromkeys(endpoints))
        if not exact or any(not isinstance(name, str) or not name for name in exact):
            raise TypeError("command endpoints must be non-empty names")
        if self._FORBIDDEN.intersection(exact) or any(name.startswith("_") for name in exact):
            raise StoreAdmissionError("a narrow command port cannot expose a broad writer endpoint")
        if reader is not None and not isinstance(reader, (ConsumerStore, RuntimeOperationReader)):
            raise TypeError("command reader must be a finite ConsumerStore or RuntimeOperationReader")
        self.__engine = engine
        self.__endpoints = frozenset(exact)
        self.__reader = reader
        self.__domain_id = domain_id

    @property
    def domain_id(self) -> str:
        return self.__domain_id

    @property
    def endpoints(self) -> Tuple[str, ...]:
        return tuple(sorted(name for name in self.__endpoints if not name.startswith("_")))

    @property
    def reader(self) -> Optional["ConsumerStore"]:
        return self.__reader

    def __dir__(self) -> list[str]:
        return sorted({"domain_id", "endpoints", "reader"} | set(self.endpoints))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in self.__endpoints or name in self._FORBIDDEN:
            raise AttributeError(name)
        value = getattr(self.__engine, name)
        if not callable(value):
            return value

        signature = inspect.signature(value)

        def exact_endpoint(*args: Any, **kwargs: Any) -> Any:
            signature.bind(*args, **kwargs)
            return value(*args, **kwargs)

        exact_endpoint.__name__ = name
        exact_endpoint.__qualname__ = "{}.{}".format(type(self).__name__, name)
        exact_endpoint.__doc__ = getattr(value, "__doc__", None)
        return exact_endpoint


class OperationOwnerCapability:
    """Trusted owner-side operation capability over the common Store.

    This is intentionally smaller than :class:`DomainHandler`: it contains
    only the operation manager's transaction, admission, durable-read and
    event-lineage seams.  It is issued by an admitted Store and is consumed
    by trusted kernel composition; serialized consumers receive the operation
    command client, never this object or its backing writer.
    """

    __slots__ = ("__owner",)

    def __init__(self, owner: Union["Store", RuntimeOperationOwner], *, _construction_token: object = None) -> None:
        admitted_foreign = (
            isinstance(owner, RuntimeOperationOwner)
            and getattr(type(owner), "_fnd_runtime_owner_marker", None) is _RUNTIME_OWNER_CONSTRUCTION_TOKEN
            and isinstance(getattr(owner, "reader", None), RuntimeOperationReader)
        )
        if _construction_token is not _OPERATION_OWNER_CONSTRUCTION_TOKEN or not (isinstance(owner, Store) or admitted_foreign):
            raise StoreAdmissionError("operation owner capabilities require an admitted Store or nominal RuntimeOperationOwner")
        if admitted_foreign:
            _validate_runtime_owner(owner)
        self.__owner = owner

    @classmethod
    def issue_runtime(cls, owner: RuntimeOperationOwner) -> "OperationOwnerCapability":
        """Issue one capability for an already-open foreign Runtime owner.

        This is the trusted composition boundary used by AST.  It never opens
        a Store; the supplied owner remains responsible for its transaction,
        descriptor admission, and durable reads/writes.
        """
        return cls(owner, _construction_token=_OPERATION_OWNER_CONSTRUCTION_TOKEN)

    @property
    def authority(self) -> str:
        return self.__owner.authority

    @property
    def reader(self) -> Union["ConsumerStore", RuntimeOperationReader]:
        return self.__owner.consumer() if isinstance(self.__owner, Store) else self.__owner.reader

    @property
    def domain_descriptor_digest(self) -> str:
        return self.__owner.domain_descriptor_digest

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        return self.__owner.registered_domains()

    def transaction(self) -> Any:
        """Return the owner's re-entrant transaction/savepoint context."""
        return self.__owner.transaction()

    def mutate(
        self,
        envelope: CommandEnvelope,
        *,
        event_type: str,
        result_ref: Optional[ResourceRef] = None,
        before_refs: Sequence[ResourceRef] = (),
        after_refs: Sequence[ResourceRef] = (),
        effects: Optional[Mapping[str, Any]] = None,
        stream: Optional[str] = None,
        event_schema_revision: str = "fnd-03.event.v1",
        occurred_at: Optional[str] = None,
        no_op: bool = False,
        transaction: Optional[Transaction] = None,
    ) -> CommandReceipt:
        return self.__owner.mutate(
            envelope,
            event_type=event_type,
            result_ref=result_ref,
            before_refs=before_refs,
            after_refs=after_refs,
            effects=effects,
            stream=stream,
            event_schema_revision=event_schema_revision,
            occurred_at=occurred_at,
            no_op=no_op,
            transaction=transaction,
        )

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.__owner.get_identity(ref)

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        return self.__owner.get_receipt(logical_request_key)

    def list_events(self, *, stream: Optional[str] = None) -> Tuple[EventEnvelope, ...]:
        return self.__owner.list_events(stream=stream)

    def lookup_replay(self, envelope: CommandEnvelope) -> Optional[CommandReceipt]:
        """Return the exact prior receipt or raise on changed request input."""
        prior = self.__owner.get_receipt(envelope.context.logical_request_key)
        if prior is not None:
            validate_replay(prior, envelope)
        return prior

    def event_lineage(self, receipt: CommandReceipt) -> Tuple[EventEnvelope, ...]:
        """Return receipt-linked events in the store's durable order."""
        wanted = set(receipt.event_ids)
        if not wanted:
            return ()
        if isinstance(self.__owner, Store):
            # Store mutation receipts name their event subject with the exact
            # result ref (or target for older receipts). Apply this existing
            # typed predicate before decoding unrelated historical payloads.
            subject = receipt.result_ref or receipt.target
            if not isinstance(subject, ResourceRef) or subject.authority != self.authority:
                raise ValueError("receipt lineage requires a local typed subject")
            events = self.__owner.list_events(subjects=(subject,))
        else:
            # The nominal Runtime bridge already owns the finite lineage
            # contract; do not substitute an unbounded inventory read.
            events = self.__owner.event_lineage(receipt)
        return tuple(event for event in events if event.event_id in wanted)

    def issue_command_port(
        self,
        engine: Any,
        domain_id: str,
        endpoints: Sequence[str],
        *,
        reader: Optional[Union["ConsumerStore", RuntimeOperationReader]] = None,
    ) -> DomainCommandPort:
        if domain_id != "herzchen.kernel.operations":
            raise StoreAdmissionError("operation owner capability cannot issue another domain port")
        if isinstance(self.__owner, Store):
            return self.__owner.issue_command_port(engine, domain_id, endpoints, reader=reader or self.reader)
        return DomainCommandPort(
            engine,
            domain_id,
            endpoints,
            reader or self.reader,
            _construction_token=_COMMAND_PORT_CONSTRUCTION_TOKEN,
        )


class DomainOwnerCapability:
    """Trusted capability scoped to one exact registered domain descriptor."""

    __slots__ = ("__owner", "__domain", "__reader")

    def __init__(self, owner: RuntimeDomainOwner, domain: DomainContribution, *, _construction_token: object = None) -> None:
        admitted = (
            isinstance(owner, RuntimeDomainOwner)
            and getattr(type(owner), "_fnd_runtime_domain_owner_marker", None) is _RUNTIME_DOMAIN_OWNER_CONSTRUCTION_TOKEN
        )
        if _construction_token is not _RUNTIME_DOMAIN_OWNER_CONSTRUCTION_TOKEN or not admitted:
            raise StoreAdmissionError("domain owner capabilities require a nominal RuntimeDomainOwner")
        if not isinstance(domain, DomainContribution):
            raise StoreAdmissionError("domain owner capability requires a DomainContribution")
        _validate_runtime_domain_owner(owner, domain.domain_id)
        self.__owner = owner
        self.__domain = domain
        self.__reader = owner.consumer()

    @classmethod
    def issue_runtime(cls, owner: RuntimeDomainOwner, domain_id: str) -> "DomainOwnerCapability":
        """Issue one finite capability for a previously admitted domain."""
        if not (
            isinstance(owner, RuntimeDomainOwner)
            and getattr(type(owner), "_fnd_runtime_domain_owner_marker", None) is _RUNTIME_DOMAIN_OWNER_CONSTRUCTION_TOKEN
        ):
            raise StoreAdmissionError("domain owner capabilities require a nominal RuntimeDomainOwner")
        descriptors = tuple(owner.registered_domains())
        selected = next((item for item in descriptors if item.domain_id == domain_id), None)
        if selected is None:
            raise StoreAdmissionError("domain is not an exactly registered Runtime domain: {!r}".format(domain_id))
        return cls(owner, selected, _construction_token=_RUNTIME_DOMAIN_OWNER_CONSTRUCTION_TOKEN)

    @property
    def authority(self) -> str:
        return self.__owner.authority

    @property
    def reader(self) -> RuntimeOperationReader:
        return self.__reader

    @property
    def domain_descriptor_digest(self) -> str:
        return self.__owner.domain_descriptor_digest

    @property
    def domain_id(self) -> str:
        return self.__domain.domain_id

    def consumer(self) -> RuntimeOperationReader:
        return self.reader

    def transaction(self) -> Any:
        return self.__owner.transaction()

    def mutate(self, envelope: CommandEnvelope, **kwargs: Any) -> CommandReceipt:
        return self.__owner.mutate(envelope, **kwargs)

    def put_identity(self, *args: Any, **kwargs: Any) -> Any:
        return self.__owner.put_identity(*args, **kwargs)

    def put_reference(self, ref: ResourceRef, *, transaction: Any = None) -> ResourceRef:
        """Retain one owner-authorized reference in the same transaction."""
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("reference authority does not belong to this Runtime owner")
        return self.__owner.put_reference(ref, transaction=transaction)

    def get_identity(self, ref: ResourceRef) -> Any:
        return self.__owner.get_identity(ref)

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        return self.__owner.get_receipt(logical_request_key)

    def list_events(self, *, stream: Optional[str] = None) -> Sequence[EventEnvelope]:
        return self.__owner.list_events(stream=stream)

    def register_domain(self, contribution: DomainContribution, **kwargs: Any) -> DomainContribution:
        if contribution != self.__domain:
            raise StoreAdmissionError("domain owner capability cannot register a different descriptor")
        return self.__owner.register_domain(contribution, **kwargs)

    def registered_domains(self) -> Sequence[DomainContribution]:
        return self.__owner.registered_domains()

    def issue_command_port(
        self,
        engine: Any,
        domain_id: str,
        endpoints: Sequence[str],
        *,
        reader: Optional[RuntimeOperationReader] = None,
    ) -> DomainCommandPort:
        if domain_id != self.__domain.domain_id:
            raise StoreAdmissionError("domain owner capability cannot issue an unregistered or different domain port")
        return DomainCommandPort(
            engine,
            domain_id,
            endpoints,
            reader or self.reader,
            _construction_token=_COMMAND_PORT_CONSTRUCTION_TOKEN,
        )

def _authority_root(value: str) -> str:
    """Return the stable authority namespace used by admission bindings."""
    return re.split(r"[.:-]", value, maxsplit=1)[0]


# These are the finite mutation ports owned by the neutral kernel itself.  An
# optional domain must instead declare its operation/event/resource surface in
# its persisted DomainContribution.  The operation manager intentionally
# accepts a caller's typed external operation name, but only for the kernel's
# ``operation`` identity and its two fixed lifecycle events.
_CORE_MUTATION_PORTS = (
    (None, ("operation",), ("operation.prepared",), None),
    ("operation.outcome", ("operation",), ("operation.outcome",), None),
    ("limit.create", ("limit",), ("limit.created",), "fnd-04.limit.v1"),
    ("limit.reserve", ("reservation",), ("reservation.held",), "fnd-04.limit.v1"),
    ("limit.uncertain", ("reservation",), ("reservation.uncertain",), "fnd-04.limit.v1"),
    ("limit.consumed", ("reservation",), ("reservation.consumed",), "fnd-04.limit.v1"),
    ("limit.released", ("reservation",), ("reservation.released",), "fnd-04.limit.v1"),
    ("recovery.state", ("runtime-epoch",), ("recovery.state.changed",), "fnd-05.recovery.v1"),
    ("recovery.retain_unknown", ("operation",), ("recovery.operation.unknown",), "fnd-05.recovery.v1"),
    ("attention.interval", ("attention-interval",), ("attention.interval.changed",), "fnd-05.interval.v1"),
)


@dataclass(frozen=True)
class IdentityRecord:
    """A neutral durable identity and its current mutable state."""

    ref: ResourceRef
    version: int
    payload: Mapping[str, Any]
    edit_token: Optional[str]
    created_at: str
    updated_at: str

    @property
    def revision(self) -> Optional[str]:
        return self.ref.revision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    # Contract validation, including JSON safety, is intentionally performed
    # before a write transaction is admitted by the public methods.
    return canonical_json(value)


def _ref_key(ref: ResourceRef) -> str:
    return ref.to_json()


def _descriptor_digest(descriptors: Sequence[DomainContribution]) -> str:
    ordered = sorted(descriptors, key=lambda descriptor: descriptor.domain_id)
    return hashlib.sha256(canonical_json([descriptor.to_dict() for descriptor in ordered]).encode("utf-8")).hexdigest()


def _validate_runtime_owner(owner: RuntimeOperationOwner) -> None:
    """Validate the finite descriptor contract before issuing a foreign owner."""
    authority = getattr(owner, "authority", None)
    if not isinstance(authority, str) or not authority.strip():
        raise StoreAdmissionError("RuntimeOperationOwner authority must be non-blank")
    try:
        descriptors = tuple(owner.registered_domains())
        reader = owner.reader
        owner_digest = owner.domain_descriptor_digest
        reader_digest = reader.domain_descriptor_digest
    except AttributeError as exc:
        raise StoreAdmissionError("RuntimeOperationOwner is missing its finite descriptor/read contract") from exc
    required_owner_methods = (
        "registered_domains", "transaction", "mutate", "get_identity", "get_receipt",
        "list_events", "lookup_replay", "event_lineage",
    )
    required_reader_methods = ("registered_domains", "get_identity", "get_receipt", "list_events")
    if any(not callable(getattr(owner, name, None)) for name in required_owner_methods):
        raise StoreAdmissionError("RuntimeOperationOwner does not implement the complete typed writer contract")
    if any(not callable(getattr(reader, name, None)) for name in required_reader_methods):
        raise StoreAdmissionError("RuntimeOperationReader does not implement the finite read contract")
    forbidden_reader_members = (
        "connection", "transaction", "mutate", "put_identity", "revise_identity",
        "put_reference", "append_event", "register_domain", "execute", "cursor",
    )
    if any(hasattr(reader, name) for name in forbidden_reader_members):
        raise StoreAdmissionError("RuntimeOperationReader exposes a broad writer member")
    if any(not isinstance(item, DomainContribution) for item in descriptors):
        raise StoreAdmissionError("RuntimeOperationOwner descriptors must be DomainContribution values")
    registry = DomainRegistry()
    for descriptor in descriptors:
        registry.register(descriptor)
    canonical = tuple(sorted(descriptors, key=lambda descriptor: descriptor.domain_id))
    if descriptors != canonical:
        raise DescriptorExpectationMismatchError("RuntimeOperationOwner descriptors must be in canonical domain-id order")
    expected = _descriptor_digest(canonical)
    if owner_digest != expected or reader_digest != expected:
        raise DescriptorExpectationMismatchError("RuntimeOperationOwner descriptor digest does not match its admitted set")


def _validate_runtime_domain_owner(owner: RuntimeDomainOwner, domain_id: str) -> None:
    """Validate the exact domain-owner bridge before issuing a scoped port."""
    authority = getattr(owner, "authority", None)
    if not isinstance(authority, str) or not authority.strip():
        raise StoreAdmissionError("RuntimeDomainOwner authority must be non-blank")
    required_owner_methods = (
        "transaction", "mutate", "put_identity", "put_reference", "get_identity", "get_receipt",
        "register_domain", "registered_domains", "consumer", "list_events",
    )
    if any(not callable(getattr(owner, name, None)) for name in required_owner_methods):
        raise StoreAdmissionError("RuntimeDomainOwner does not implement the required domain writer contract")
    descriptors = tuple(owner.registered_domains())
    if any(not isinstance(item, DomainContribution) for item in descriptors):
        raise StoreAdmissionError("RuntimeDomainOwner descriptors must be DomainContribution values")
    registry = DomainRegistry()
    for descriptor in descriptors:
        registry.register(descriptor)
    canonical = tuple(sorted(descriptors, key=lambda descriptor: descriptor.domain_id))
    if descriptors != canonical:
        raise DescriptorExpectationMismatchError("RuntimeDomainOwner descriptors must be canonical")
    expected = _descriptor_digest(canonical)
    if getattr(owner, "domain_descriptor_digest", None) != expected:
        raise DescriptorExpectationMismatchError("RuntimeDomainOwner descriptor digest does not match its admitted set")
    selected = next((item for item in descriptors if item.domain_id == domain_id), None)
    if selected is None:
        raise StoreAdmissionError("RuntimeDomainOwner has no exact descriptor for {!r}".format(domain_id))
    reader = owner.consumer()
    if not isinstance(reader, RuntimeOperationReader):
        raise StoreAdmissionError("RuntimeDomainOwner consumer must be a finite RuntimeOperationReader")
    required_reader_methods = ("registered_domains", "get_identity", "get_receipt", "list_events")
    if any(not callable(getattr(reader, name, None)) for name in required_reader_methods):
        raise StoreAdmissionError("RuntimeDomainOwner consumer lacks the finite read contract")
    if any(hasattr(reader, name) for name in (
        "connection", "transaction", "mutate", "put_identity", "revise_identity",
        "put_reference", "append_event", "register_domain", "execute", "cursor",
    )):
        raise StoreAdmissionError("RuntimeDomainOwner consumer exposes a broad writer member")
    if getattr(reader, "domain_descriptor_digest", None) != expected:
        raise DescriptorExpectationMismatchError("RuntimeDomainOwner consumer digest does not match its admitted set")


def _descriptor_expectation(
    expected_domains: Sequence[DomainContribution],
    expected_domain_digest: Optional[str] = None,
) -> Tuple[Tuple[DomainContribution, ...], str]:
    expected = tuple(expected_domains)
    if any(not isinstance(descriptor, DomainContribution) for descriptor in expected):
        raise DescriptorExpectationMismatchError("expected_domains must contain DomainContribution values")
    registry = DomainRegistry()
    for descriptor in expected:
        registry.register(descriptor)
    canonical = tuple(sorted(expected, key=lambda descriptor: descriptor.domain_id))
    if expected != canonical:
        raise DescriptorExpectationMismatchError("expected_domains must be in canonical domain-id order")
    computed_digest = _descriptor_digest(canonical)
    if expected_domain_digest is not None and expected_domain_digest != computed_digest:
        raise DescriptorExpectationMismatchError("expected_domain_digest does not match expected_domains")
    return canonical, computed_digest


def _ref_json(ref: Optional[ResourceRef]) -> Optional[str]:
    return None if ref is None else ref.to_json()


_NUMERIC_REVISION = re.compile(r"^rev-([0-9]+)$")


class Transaction:
    """A supplied common writer port with nested savepoint support."""

    def __init__(self, store: "Store") -> None:
        self.store = store
        self.connection = store._connection
        self._active = False
        self._savepoint_number = 0
        self._domain_working: Dict[str, DomainContribution] = {}
        self._domain_digest = store._domain_descriptor_digest
        self._history: Dict[str, list] = {}
        self._after_commit = []
        self._history_projection_scheduled = False

    def _require_active(self) -> None:
        self.store._require_open()
        if not self._active:
            raise StoreError("transaction is not active")

    def _begin(self) -> None:
        self.store._require_open()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise WriterBusyError("SQLite writer admission is busy") from exc
            raise
        self._active = True
        self._domain_working = dict(self.store._domain_descriptors)
        self._domain_digest = self.store._domain_descriptor_digest

    def _commit(self) -> None:
        self._require_active()
        try:
            self.store._flush_history(self)
            self.connection.execute("COMMIT")
            self.store._domain_descriptors = dict(self._domain_working)
            self.store._domain_descriptor_digest = self._domain_digest
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._active = False
        # Cleanup is post-commit only. Failure retains recoverable residue and
        # cannot turn accepted domain work into a rollback/error claim.
        for callback in self._after_commit:
            try:
                callback()
            except OSError:
                pass

    def _rollback(self) -> None:
        if self._active:
            try:
                self.connection.execute("ROLLBACK")
            finally:
                self._active = False

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        self._require_active()
        return self.connection.execute(sql, parameters)

    def executemany(self, sql: str, parameters: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        self._require_active()
        return self.connection.executemany(sql, parameters)

    @contextmanager
    def savepoint(self) -> Iterator["Transaction"]:
        self._require_active()
        self._savepoint_number += 1
        name = "fnd_sp_{}".format(self._savepoint_number)
        domain_snapshot = dict(self._domain_working)
        digest_snapshot = self._domain_digest
        history_snapshot = {key: len(facets) for key, facets in self._history.items()}
        callback_count = len(self._after_commit)
        projection_scheduled = self._history_projection_scheduled
        self.connection.execute("SAVEPOINT " + name)
        try:
            yield self
        except BaseException:
            self.connection.execute("ROLLBACK TO SAVEPOINT " + name)
            self.connection.execute("RELEASE SAVEPOINT " + name)
            self._domain_working = domain_snapshot
            self._domain_digest = digest_snapshot
            self._history = {key: self._history[key][:size] for key, size in history_snapshot.items()}
            del self._after_commit[callback_count:]
            self._history_projection_scheduled = projection_scheduled
            raise
        else:
            self.connection.execute("RELEASE SAVEPOINT " + name)


class Store:
    """The sealed owner capability for one admitted FND-03 writer.

    Host composition code acquires this capability only through ``create`` or
    ``open``.  It supplies the object to trusted domain handlers.  Ordinary
    consumers receive :meth:`consumer`, whose concrete type contains read
    operations and deliberately has no writable connection or mutation API.
    """

    def __init__(self, connection: sqlite3.Connection, lock_fd: Optional[int], path: str, authority: str, domain_descriptors: Optional[Mapping[str, DomainContribution]] = None, *, _owner_token: object = None) -> None:
        if _owner_token is not _OWNER_CONSTRUCTION_TOKEN:
            raise StoreAdmissionError("Store owner capabilities are acquired through Store.create or Store.open")
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._lock_fd = lock_fd
        self.path = path
        self.authority = authority
        self._closed = False
        # ``check_same_thread=False`` permits service/adapter contenders to
        # share this Store, but sqlite3 cursors still must not be used by
        # multiple threads at once.  Transaction admission and Store-owned
        # reads therefore use the same re-entrant boundary.
        self._transaction_lock = threading.RLock()
        self._local = threading.local()
        self._domain_descriptors: Dict[str, DomainContribution] = dict(domain_descriptors or {})
        self._domain_descriptor_digest = _descriptor_digest(self._domain_descriptors.values())
        self._issued_handlers: set[DomainHandler] = set()
        self._history_publisher = None
        self._history_projection = None
        self._history_projection_limit = 100
        self._read_only = False
        self._admission_mode = "full"
        self._admission_data_version = None
        self.admission_report = {"mode": "full", "path": "create", "fallback_reason": None}

    @classmethod
    def create(cls, path: Union[os.PathLike, str], *, authority: str = "neutral-store") -> "Store":
        path_text = os.fspath(path)
        lock_fd = cls._acquire_lock(path_text)
        connection: Optional[sqlite3.Connection] = None
        try:
            cls._consume_clean_close(path_text)
            connection = cls._connect(path_text)
            if cls._user_tables(connection):
                raise StoreExistsError("database already contains a user composition")
            # executescript commits any already-open transaction before
            # running.  Start the transaction inside the script so DDL and
            # metadata below remain one admission unit.
            connection.executescript("BEGIN IMMEDIATE;\n" + DDL)
            metadata = {
                "schema_revision": SCHEMA_REVISION,
                "schema_fingerprint": SCHEMA_FINGERPRINT,
                "composition": canonical_json(COMPOSITION),
                "store_authority": authority,
                "source_next_append": "1",
                "history_generation": "1",
                "history_checkpoint": "0",
                "legacy_append_boundary": "0",
                "fnd02_contract_revision": FND02_CONTRACT_REVISION,
                "fnd02_contract_digest": FND02_CONTRACT_DIGEST,
                DOMAIN_DESCRIPTOR_DIGEST_KEY: EMPTY_DOMAIN_DESCRIPTOR_DIGEST,
            }
            connection.executemany("INSERT INTO store_metadata(key, value) VALUES (?, ?)", metadata.items())
            connection.execute("COMMIT")
            return cls(connection, lock_fd, path_text, authority, {}, _owner_token=_OWNER_CONSTRUCTION_TOKEN)
        except BaseException:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                connection.close()
            cls._release_lock(lock_fd)
            raise

    @classmethod
    def open(cls, path, *, authority="neutral-store", expected_domains=(), expected_domain_digest=None,
             admission="full", should_stop=None):
        return cls._open(path, authority=authority, expected_domains=expected_domains,
                         expected_domain_digest=expected_domain_digest, admission=admission,
                         should_stop=should_stop)

    @classmethod
    def _open(
        cls,
        path: Union[os.PathLike, str],
        *,
        authority: str = "neutral-store",
        expected_domains: Sequence[DomainContribution] = (),
        expected_domain_digest: Optional[str] = None,
        _migration_id: Optional[str] = None,
        admission: str = "full",
        should_stop=None,
    ) -> "Store":
        if admission not in {"full", "clean-close"}:
            raise ValueError("admission must be full or clean-close")
        if should_stop is not None and not callable(should_stop):
            raise TypeError("should_stop must be callable")
        path_text = os.fspath(path)
        if path_text == ":memory:":
            raise StoreAdmissionError("ordinary open requires a durable database path")
        if not os.path.exists(path_text):
            raise StoreAdmissionError("database does not exist; use create for first admission")
        lock_fd = cls._acquire_lock(path_text)
        connection: Optional[sqlite3.Connection] = None
        report = {"mode": admission, "path": "full", "fallback_reason": None,
                  "structural_s": 0.0, "fk_check_s": 0.0, "count_s": 0.0}
        started = time.monotonic()
        interrupted = False
        last_poll = float("-inf")
        def poll_stop(force=False):
            nonlocal interrupted, last_poll
            now = time.monotonic()
            if should_stop is not None and (force or now - last_poll >= 0.25):
                last_poll = now
                if should_stop():
                    interrupted = True
                    raise AdmissionStopped("Store admission stopped before writable admission")
        def progress():
            try:
                poll_stop()
                return 0
            except AdmissionStopped:
                return 1
        try:
            poll_stop(True)
            candidate, reason, stamp = (cls._clean_close_candidate(path_text, authority)
                                        if admission == "clean-close" else (None, None, None))
            if admission == "full":
                cls._consume_clean_close(path_text)
            report["fallback_reason"] = reason
            connection = cls._connect(path_text)
            if should_stop is not None:
                connection.set_progress_handler(progress, 1000)
            if admission == "clean-close":
                # Reserve SQLite's writer lock before trusting the pre-connect
                # file stamp. No raw database fd is opened/closed while SQLite
                # owns its POSIX locks (closing one would drop those locks).
                connection.execute("BEGIN IMMEDIATE")
                if candidate is not None and cls._file_stamp(path_text) != stamp:
                    candidate, report["fallback_reason"] = None, "file-changed-before-admission"
                if candidate is not None and _migration_id is not None:
                    candidate, report["fallback_reason"] = None, "migration-request"
                if candidate is not None:
                    meta = dict(connection.execute("SELECT key,value FROM store_metadata"))
                    if meta.get("migration_progress"):
                        try:
                            installed_migration = cls._installed_migration(meta, path_text)
                        except (KeyError, TypeError, ValueError):
                            installed_migration = False  # Full verification owns malformed metadata refusal.
                        if not installed_migration:
                            candidate, report["fallback_reason"] = None, "migration-progress"
                    if candidate is not None and meta.get("source_next_append") != candidate["source_next_append"]:
                        candidate, report["fallback_reason"] = None, "append-marker-mismatch"
            poll_stop(True)
            domains = cls._verify(connection, authority, expected_domains, expected_domain_digest,
                                  _skip_foreign_key_check=candidate is not None,
                                  _admission_timings=report)
            if candidate is not None and cls._file_stamp(path_text) != stamp:
                # Raw external writes do not respect SQLite locks. Changed
                # metadata is a fallback, never evidence of a clean file.
                report["fallback_reason"] = "file-changed-during-admission"
                domains = cls._verify(connection, authority, expected_domains, expected_domain_digest,
                                      _admission_timings=report)
                candidate = None
            metadata = dict(connection.execute("SELECT key,value FROM store_metadata"))
            progress = metadata.get("migration_progress")
            installed = cls._installed_migration(metadata, path_text)
            if progress and not installed and _migration_id != metadata.get("migration_id"):
                raise MigrationRequiredError("migration candidate is not an installed writable owner")
            if _migration_id is not None and _migration_id != metadata.get("migration_id"):
                raise StoreAdmissionError("migration candidate identity mismatch")
            poll_stop(True)
            # Invalidate durably BEFORE returning any writable capability.
            cls._consume_clean_close(path_text)
            baseline = connection.execute("PRAGMA data_version").fetchone()[0]
            if admission == "clean-close":
                connection.execute("COMMIT")
            connection.set_progress_handler(None, 0)
            owner = cls(connection, lock_fd, path_text, authority, domains, _owner_token=_OWNER_CONSTRUCTION_TOKEN)
            owner._admission_mode, owner._admission_data_version = admission, baseline
            report["path"] = "clean-close" if candidate is not None else "full"
            report["source_next_append"] = owner.source_next_append
            report["total_s"] = time.monotonic() - started
            owner.admission_report = report
            return owner
        except BaseException as error:
            try:
                if connection is not None:
                    connection.set_progress_handler(None, 0)
                    connection.close()
            finally:
                cls._release_lock(lock_fd)
            if interrupted and isinstance(error, sqlite3.Error):
                raise AdmissionStopped("Store admission stopped during verification") from error
            raise

    @staticmethod
    def _installed_migration(metadata, path):
        """The ordinary writable-admission terminal migration predicate.

        Completed migration metadata remains durable provenance. Its presence
        alone does not mean migration is in progress. Both admission modes use
        this identical receipt check; nonterminal candidates still require full
        verification and their explicitly authorized migration identity.
        """
        switch_receipt = json.loads(metadata.get("migration_switch_receipt", "null"))
        progress = metadata.get("migration_progress")
        phase = json.loads(progress)["phase"] if progress else None
        valid_receipt = (isinstance(switch_receipt, Mapping) and
            switch_receipt.get("schema") == "fnd.events-migration.v1" and
            switch_receipt.get("migration_id") == metadata.get("migration_id") and
            switch_receipt.get("successor_revision") == SCHEMA_REVISION and
            switch_receipt.get("successor_fingerprint") == SCHEMA_FINGERPRINT)
        return valid_receipt and (phase == "installed" or
            (phase == "verified" and os.path.abspath(path) == switch_receipt.get("source")))

    @staticmethod
    def _fsync_parent(path):
        fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @classmethod
    def _consume_clean_close(cls, path):
        if path == ":memory:":
            return
        try:
            os.unlink(path + ".fnd-clean-close")
        except FileNotFoundError:
            return
        cls._fsync_parent(path)

    @staticmethod
    def _file_stamp(path):
        info = os.stat(path)
        return {"realpath": os.path.realpath(path), "st_dev": info.st_dev, "st_ino": info.st_ino,
                "st_size": info.st_size, "st_mtime_ns": info.st_mtime_ns, "st_ctime_ns": info.st_ctime_ns}

    @classmethod
    def _closed_file_identity(cls, path):
        # Called only before SQLite connects or after it has closed completely.
        if os.path.islink(path):
            raise StoreAdmissionError("clean-close path is a symlink")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            page1 = os.read(fd, 65536)
            after = os.fstat(fd)
            if (any(getattr(before, field) != getattr(after, field) for field in
                    ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
                    or not stat.S_ISREG(before.st_mode)):
                raise StoreAdmissionError("database changed during closed-file inspection")
        finally:
            os.close(fd)
        stamp = cls._file_stamp(path)
        if (stamp["st_dev"], stamp["st_ino"], stamp["st_size"], stamp["st_mtime_ns"], stamp["st_ctime_ns"]) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise StoreAdmissionError("database changed after closed-file inspection")
        if len(page1) < 100 or page1[:16] != b"SQLite format 3\x00":
            raise StoreAdmissionError("invalid SQLite header")
        page_size = int.from_bytes(page1[16:18], "big")
        page_size = 65536 if page_size == 1 else page_size
        if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
            raise StoreAdmissionError("invalid SQLite page size")
        if page1[18:20] != b"\x01\x01":
            raise StoreAdmissionError("clean-close requires rollback journal format")
        if int.from_bytes(page1[28:32], "big") * page_size != stamp["st_size"]:
            raise StoreAdmissionError("SQLite header page count differs from file size")
        if any(os.path.lexists(path + suffix) for suffix in ("-journal", "-wal", "-shm")):
            raise StoreAdmissionError("SQLite journal sidecar present")
        return {**stamp, "page1_sha256": hashlib.sha256(page1[:page_size]).hexdigest()}

    @classmethod
    def _clean_close_candidate(cls, path, authority):
        try:
            fd = os.open(path + ".fnd-clean-close", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None, "record-missing", None
        except OSError:
            return None, "record-unavailable", None
        try:
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno()); raw = stream.read(16385)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or len(raw) > 16384):
                return None, "record-shape", None
            record = json.loads(raw)
            required = {"schema", "admission_check_revision", "schema_fingerprint", "authority", "source_next_append",
                        "realpath", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "page1_sha256"}
            if not isinstance(record, dict) or set(record) != required:
                return None, "record-shape", None
            if record["schema"] != _CLEAN_CLOSE_SCHEMA or record["admission_check_revision"] != ADMISSION_CHECK_REVISION:
                return None, "check-revision", None
            if record["schema_fingerprint"] != SCHEMA_FINGERPRINT or record["authority"] != authority:
                return None, "authority-or-schema", None
            identity = cls._closed_file_identity(path)
            if any(record[key] != value for key, value in identity.items()):
                return None, "file-identity", None
            return record, None, {key: value for key, value in identity.items() if key != "page1_sha256"}
        except (OSError, ValueError, TypeError, StoreAdmissionError):
            return None, "record-or-file-invalid", None

    def _write_clean_close(self, source_next_append, expected_stamp):
        identity = self._closed_file_identity(self.path)
        if any(identity[key] != value for key, value in expected_stamp.items()):
            raise StoreAdmissionError("file changed between SQLite close and seal")
        record = {"schema": _CLEAN_CLOSE_SCHEMA, "admission_check_revision": ADMISSION_CHECK_REVISION,
                  "schema_fingerprint": SCHEMA_FINGERPRINT, "authority": self.authority,
                  "source_next_append": source_next_append, **identity}
        path = self.path + ".fnd-clean-close"
        temporary = path + ".tmp-" + secrets.token_hex(8)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write((canonical_json(record) + "\n").encode()); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
            try:
                self._fsync_parent(self.path)
            except BaseException:
                try: os.unlink(path)
                except OSError: pass
                raise
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass

    @classmethod
    def open_readonly(cls, path, *, authority="neutral-store", expected_domains=(), expected_domain_digest=None):
        """Admit either supported composition without a writable capability.

        Legacy reads remain current-head reads; this does not invent old-ref
        state or implement the project history reader. The physical owner lock
        is retained for the lifetime of this explicit inspection handle.
        """
        from pathlib import Path
        path_text = os.fspath(path)
        if not os.path.isfile(path_text) or os.path.islink(path_text):
            raise StoreAdmissionError("read-only admission requires a regular durable file")
        lock_fd, connection = cls._acquire_lock(path_text), None
        try:
            connection = sqlite3.connect(Path(path_text).absolute().as_uri() + "?mode=ro", uri=True,
                                         isolation_level=None, check_same_thread=False)
            connection.execute("PRAGMA foreign_keys=ON")
            metadata = dict(connection.execute("SELECT key,value FROM store_metadata"))
            revision = metadata.get("schema_revision")
            domains = cls._verify(connection,authority,expected_domains,expected_domain_digest,
                                  schema_revision=revision)
            owner = cls(connection,lock_fd,path_text,authority,domains,_owner_token=_OWNER_CONSTRUCTION_TOKEN)
            owner._read_only = True
            return ReadOnlyStore(owner)
        except BaseException:
            if connection is not None:
                connection.close()
            cls._release_lock(lock_fd)
            raise

    def defer_after_commit(self, callback):
        """Trusted Evidence cleanup; retain sidecars on outer rollback."""
        self._require_open()
        tx = getattr(self._local, "transaction", None)
        if tx is not None and tx._active:
            tx._after_commit.append(callback)
        else:
            callback()

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=0.0, isolation_level=None, check_same_thread=False)
        connection.execute("PRAGMA foreign_keys = ON")
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        if enabled != 1:
            connection.close()
            raise StoreAdmissionError("SQLite foreign-key enforcement could not be enabled")
        return connection

    @staticmethod
    def _acquire_lock(path: str) -> Optional[int]:
        if path == ":memory:":
            return None
        lock_path = path + ".fnd-owner.lock"
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(lock_fd)
                raise WriterBusyError("another store owns the durable writer lock") from exc
            return lock_fd
        except FileNotFoundError as exc:
            raise StoreAdmissionError("database parent directory does not exist") from exc

    @staticmethod
    def _release_lock(lock_fd: Optional[int]) -> None:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    @staticmethod
    def _user_tables(connection: sqlite3.Connection) -> Tuple[str, ...]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return tuple(row[0] for row in rows)

    @classmethod
    def _verify(
        cls,
        connection: sqlite3.Connection,
        authority: str,
        expected_domains: Sequence[DomainContribution] = (),
        expected_domain_digest: Optional[str] = None,
        *, schema_revision: str = SCHEMA_REVISION,
        _skip_foreign_key_check: bool = False, _admission_timings=None,
    ) -> Dict[str, DomainContribution]:
        structural_started = time.monotonic()
        actual = cls._user_tables(connection)
        if schema_revision not in SUPPORTED_SCHEMAS:
            raise SchemaMismatchError("unsupported FND composition revision")
        composition, fingerprint, _ddl = SUPPORTED_SCHEMAS[schema_revision]
        rows = dict(connection.execute("SELECT key, value FROM store_metadata").fetchall()) if "store_metadata" in actual else {}
        if rows.get("schema_revision") == LEGACY_SCHEMA_REVISION and schema_revision == SCHEMA_REVISION:
            raise MigrationRequiredError("legacy FND requires explicit closed-owner migration before writable open")
        if actual != tuple(sorted(composition)):
            raise CompositionMismatchError("declared tables do not exactly match FND composition: {}".format(actual))
        if rows.get("schema_revision") != schema_revision or rows.get("schema_fingerprint") != fingerprint:
            raise SchemaMismatchError("schema revision or fingerprint is not an admitted FND composition")
        if rows.get("composition") != canonical_json(composition):
            raise CompositionMismatchError("stored composition declaration does not match")
        if not verify_physical_schema(connection, schema_revision):
            raise SchemaMismatchError("physical FND tables, constraints or indexes do not match")
        if _admission_timings is not None:
            _admission_timings["structural_s"] += time.monotonic() - structural_started
        fk_started = time.monotonic()
        if not _skip_foreign_key_check and connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StoreAdmissionError("FND foreign-key relations are invalid")
        if _admission_timings is not None:
            _admission_timings["fk_check_s"] += time.monotonic() - fk_started
        if schema_revision == SCHEMA_REVISION:
            try:
                next_append = int(rows["source_next_append"])
                generation = int(rows["history_generation"])
                checkpoint = int(rows["history_checkpoint"])
                legacy = int(rows["legacy_append_boundary"])
                progress = json.loads(rows.get("migration_progress", "null"))
                if progress is not None:
                    if not isinstance(progress, dict) or progress.get("phase") not in {
                        "copy", "order", "normalize", "backfill", "verify", "verified", "installed"}:
                        raise ValueError("unsupported migration progress")
                    if not rows.get("migration_id"):
                        raise ValueError("migration continuation lacks identity")
                if checkpoint < 0 or legacy < 0:
                    raise ValueError("negative source/projection boundary")
                if not progress or progress["phase"] in {"verified", "installed"}:
                    count_started = time.monotonic()
                    count, maximum = connection.execute("SELECT count(*),coalesce(max(append_position),0) FROM events").fetchone()
                    if _admission_timings is not None:
                        _admission_timings["count_s"] += time.monotonic() - count_started
                    if count != maximum or next_append != maximum + 1 or not (0 <= checkpoint <= maximum and 0 <= legacy <= maximum):
                        raise ValueError("source append boundary mismatch")
                if generation < 1 or next_append < 1:
                    raise ValueError("invalid source/projection generation")
            except (KeyError, TypeError, ValueError) as exc:
                raise SchemaMismatchError("successor ordering/projection metadata is invalid") from exc
        if rows.get("store_authority") != authority:
            raise SchemaMismatchError("store authority does not match admission")
        if rows.get("fnd02_contract_revision") != FND02_CONTRACT_REVISION or rows.get("fnd02_contract_digest") != FND02_CONTRACT_DIGEST:
            raise SchemaMismatchError("accepted FND-02 contract baseline is not present")
        descriptors: Dict[str, DomainContribution] = {}
        descriptor_rows = connection.execute(
            "SELECT authority, kind, id, payload_json FROM identities WHERE kind = ? ORDER BY authority, id",
            (DOMAIN_KIND,),
        ).fetchall()
        registry = DomainRegistry()
        for descriptor_row in descriptor_rows:
            if descriptor_row[0] != authority:
                raise StoreAdmissionError("domain descriptor authority does not match store authority")
            try:
                descriptor = DomainContribution.from_dict(json.loads(descriptor_row[3]))
                if descriptor.domain_id != descriptor_row[2]:
                    raise ContractError("domain descriptor identity does not match its record id")
                registry.register(descriptor)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise StoreAdmissionError("stored domain descriptor is invalid") from exc
            descriptors[descriptor.domain_id] = descriptor
        expected_digest = _descriptor_digest(descriptors.values())
        if rows.get(DOMAIN_DESCRIPTOR_DIGEST_KEY) != expected_digest:
            raise DescriptorDigestMismatchError("stored domain descriptor set does not match metadata digest")
        expected, caller_digest = _descriptor_expectation(expected_domains, expected_domain_digest)
        persisted = tuple(descriptors[key] for key in sorted(descriptors))
        if persisted != expected or caller_digest != expected_digest:
            raise DescriptorExpectationMismatchError("caller descriptor composition does not match admitted store")
        return descriptors

    def _require_open(self) -> None:
        if self._closed:
            raise ClosedStoreError("store is closed")

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the raw connection held by this explicit owner capability."""
        self._require_open()
        return self._connection

    def consumer(self) -> "ConsumerStore":
        """Return the supported read-only surface for ordinary consumers."""
        self._require_open()
        return ConsumerStore(self)

    def foreign_keys_enabled(self) -> bool:
        with self._transaction_lock:
            self._require_open()
            return self._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    @contextmanager
    def read_transaction(self):
        """Trusted domain reads share the SQLite connection's owner mutex."""
        with self._transaction_lock:
            self._require_open()
            yield

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        self._require_open()
        if self._read_only:
            raise StoreAdmissionError("read-only admission cannot mutate the owner")
        active = getattr(self._local, "transaction", None)
        if active is not None and active._active:
            # A nested transaction is a savepoint, so a caller may handle a
            # failed unit without losing the coherent outer transaction.
            with active.savepoint() as nested:
                yield nested
            return
        with self._transaction_lock:
            transaction = Transaction(self)
            transaction._begin()
            self._local.transaction = transaction
            try:
                yield transaction
            except BaseException:
                transaction._rollback()
                raise
            else:
                transaction._commit()
            finally:
                self._local.transaction = None

    def _transaction(self) -> Any:
        """Compatibility spelling for the supplied transaction port."""
        return self.transaction()

    @property
    def source_next_append(self):
        """Read-only owner telemetry; no history hydration or canonical write."""
        row = self._connection.execute("SELECT value FROM store_metadata WHERE key='source_next_append'").fetchone()
        if row is None:
            return None  # Legacy schema has no append-boundary field.
        try:
            value = int(row[0])
        except (ValueError, TypeError) as error:
            raise StoreAdmissionError("invalid source append telemetry") from error
        if value < 1:
            raise StoreAdmissionError("invalid source append telemetry")
        return value

    def close(self, *, seal=False) -> None:
        if type(seal) is not bool:
            raise TypeError("seal must be boolean")
        if self._closed:
            return
        with self._transaction_lock:
            if self._closed:
                return
            active = getattr(self._local, "transaction", None)
            eligible, source_next_append, close_stamp = False, None, None
            reason = "not-requested"
            if seal:
                try:
                    if self._admission_mode != "clean-close" or self._read_only or self.path == ":memory:":
                        raise StoreAdmissionError("not a clean-close admitted writer")
                    if self._connection.in_transaction or active is not None and active._active:
                        raise StoreAdmissionError("transaction active at close")
                    # Prevent a foreign writer between the data_version check
                    # and SQLite close. The post-close stamp is compared with
                    # this locked stamp, so the lock-release/sidecar-write gap
                    # cannot bless a newly committed foreign change.
                    self._connection.execute("BEGIN IMMEDIATE")
                    if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                        raise StoreAdmissionError("foreign-key enforcement disabled")
                    if self._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                        raise StoreAdmissionError("journal mode is not delete")
                    if self._connection.execute("PRAGMA data_version").fetchone()[0] != self._admission_data_version:
                        raise StoreAdmissionError("foreign connection committed during session")
                    source_next_append = self._connection.execute("SELECT value FROM store_metadata WHERE key='source_next_append'").fetchone()[0]
                    close_stamp = self._file_stamp(self.path)
                    eligible, reason = True, None
                except (sqlite3.Error, StoreAdmissionError) as error:
                    reason = str(error)
            if active is not None and active._active:
                active._rollback()
            try:
                self._connection.close()
                if eligible:
                    try:
                        self._write_clean_close(source_next_append, close_stamp)
                        self.admission_report["seal"] = "written"
                        self.admission_report["sealed_source_next_append"] = int(source_next_append)
                        print("clean-close-record: written", file=sys.stderr, flush=True)
                    except (OSError, ValueError, sqlite3.Error, StoreAdmissionError) as error:
                        reason = type(error).__name__ + ": " + str(error)
                        self._consume_clean_close(self.path)
            finally:
                self._release_lock(self._lock_fd)
                self._lock_fd = None
                self._closed = True
                if seal and self.admission_report.get("seal") != "written":
                    self.admission_report["seal"] = "not-written"
                    self.admission_report["seal_reason"] = reason or "connection close failed"
                    print("clean-close-record: not-written: " + self.admission_report["seal_reason"], file=sys.stderr, flush=True)

    def __enter__(self) -> "Store":
        self._require_open()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def _active_or_transaction(self, transaction: Optional[Transaction]) -> Tuple[Transaction, bool]:
        self._require_open()
        if transaction is not None:
            if transaction.store is not self or not transaction._active:
                raise StoreError("supplied transaction is not active for this store")
            return transaction, False
        active = getattr(self._local, "transaction", None)
        if active is not None and active._active:
            return active, False
        return None, True  # type: ignore[return-value]

    def put_identity(
        self,
        ref: ResourceRef,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        version: int = 0,
        edit_token: Optional[str] = None,
        transaction: Optional[Transaction] = None,
        history_event_id: Optional[str] = None,
    ) -> IdentityRecord:
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("identity authority does not belong to this store")
        if not isinstance(version, int) or version < 0:
            raise ValueError("version must be a non-negative integer")
        if not isinstance(payload or {}, Mapping):
            raise TypeError("payload must be a mapping")
        payload_json = _json(dict(payload or {}))
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._put_identity(owned, ref, payload_json, version, edit_token, history_event_id)
        return self._put_identity(tx, ref, payload_json, version, edit_token, history_event_id)

    def _put_identity(self, tx: Transaction, ref: ResourceRef, payload_json: str, version: int, edit_token: Optional[str], history_event_id: Optional[str] = None) -> IdentityRecord:
        now = _now()
        existing = tx.execute(
            "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
            (ref.authority, ref.kind, ref.id),
        ).fetchone()
        if existing is not None:
            current = self._identity_from_row(existing)
            if current.ref.revision != ref.revision or current.version != version or _json(current.payload) != payload_json:
                raise StoreError("identity already exists with a different state")
            return current
        tx.execute(
            "INSERT INTO identities(authority, kind, id, current_revision, version, edit_token, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ref.authority, ref.kind, ref.id, ref.revision, version, edit_token, payload_json, now, now),
        )
        if history_event_id is not None:
            self._capture_child(tx, history_event_id, None, None, ref, json.loads(payload_json))
        return IdentityRecord(ref, version, json.loads(payload_json), edit_token, now, now)

    def _identity_from_row(self, row: sqlite3.Row) -> IdentityRecord:
        return IdentityRecord(
            ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]),
            row["version"],
            json.loads(row["payload_json"]),
            row["edit_token"],
            row["created_at"],
            row["updated_at"],
        )

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            return None if row is None else self._identity_from_row(row)

    def prepare_identity_lookup_indexes(self, *, timeout_seconds: float = 300.0) -> Mapping[str, Any]:
        """Explicit trusted-owner maintenance at a closed host boundary.

        Build only declared current-reference accelerators in one rollbackable
        SQLite transaction. No canonical payload, event, revision or allowance
        changes. Ordinary open and consumer readers never invoke maintenance.
        """
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 3600):
            raise ValueError("index build requires a finite positive deadline <= 3600 seconds")
        if getattr(self._local, "transaction", None) is not None:
            raise StoreAdmissionError("index maintenance requires its own closed-owner transaction")
        started = time.monotonic()
        with self._transaction_lock:
            self._require_open()
            if not verify_physical_schema(self._connection, SCHEMA_REVISION):
                raise SchemaMismatchError("index maintenance requires exact admitted physical schema")
            present = {row[0] for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            missing = [name for name in IDENTITY_LOOKUP_INDEXES if name not in present]
            self._connection.set_progress_handler(lambda: int(time.monotonic() - started > timeout_seconds), 1000)
            try:
                with self.transaction() as tx:
                    for name in missing:
                        if time.monotonic() - started > timeout_seconds:
                            raise sqlite3.OperationalError("interrupted: identity lookup index deadline")
                        tx.execute(IDENTITY_LOOKUP_INDEXES[name])
            finally:
                self._connection.set_progress_handler(None, 0)
            if not verify_physical_schema(self._connection, SCHEMA_REVISION):
                raise SchemaMismatchError("completed index definitions differ from exact declarations")
        return {"outcome": "prepared", "created_indexes": missing,
                "indexes": list(IDENTITY_LOOKUP_INDEXES), "elapsed_seconds": time.monotonic() - started,
                "canonical_rows_changed": False}

    def find_identity_refs(self, *, kind: str, payload_matches: Mapping[Tuple[str, ...], str]) -> Tuple[ResourceRef, ...]:
        """Current owner references matching exact string fields, before hydration.

        This narrows the existing identity reader; it creates no scope or
        authority. Paths are structural names, values and paths are SQL
        parameters, and historical event payloads are never materialized.
        """
        if not isinstance(kind, str) or not kind.strip() or not isinstance(payload_matches, Mapping) or not payload_matches:
            raise ValueError("identity kind and exact payload predicates required")
        # These literal paths exactly match the declared expression indexes.
        # Bound JSON-path parameters cannot use SQLite expression indexes.
        indexed_paths = {('project_ref',): '$.project_ref',
            ('target', 'native_adapter'): '$.target.native_adapter',
            ('host_evidence', 'gateway_attempt', 'delivery_authorization', 'physical_session_id'):
                '$.host_evidence.gateway_attempt.delivery_authorization.physical_session_id'}
        indexed = kind == 'otto.due-record' and all(isinstance(path, tuple) and path in indexed_paths for path in payload_matches)
        if indexed:
            with self._transaction_lock:
                self._require_open()
                present = {row[0] for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'")}
                indexed = {'identities_due_native_lookup', 'identities_due_project_lookup'}.issubset(present)
        clauses, args = ["authority = ?", "kind = 'otto.due-record'" if indexed else "kind = ?"], [self.authority]
        if not indexed:
            args.append(kind)
        structural, structural_args, candidates, candidate_args = [], [], [], []
        for path, value in payload_matches.items():
            if (not isinstance(path, tuple) or not path or len(path) > 8
                    or not all(isinstance(part, str) and part and part.replace('_', '').isalnum() for part in path)
                    or not isinstance(value, str)):
                raise ValueError("identity payload predicates require structural paths and string values")
            json_path = '$.' + '.'.join(path)
            if indexed:
                literal = indexed_paths[path]
                clauses.extend(["json_type(payload_json, '" + literal + "') = 'text'",
                                "json_extract(payload_json, '" + literal + "') = ?"])
                args.append(value)
                continue
            structural.extend(["json_type(payload_json, ?) = 'text'", "json_extract(payload_json, ?) = ?"])
            structural_args.extend([json_path, json_path, value])
            candidates.append("instr(payload_json, ?) > 0")
            candidate_args.append(canonical_json(value))
        # Store writes canonical JSON. Every matching string therefore has
        # this exact encoded token. CASE short-circuits structural JSON parsing
        # for non-candidates; the original type/path/equality checks still decide
        # authority. False-positive tokens (including nested history) never match
        # by themselves. No identity/context cache or schema change is involved.
        if not indexed:
            clauses.append("CASE WHEN " + " AND ".join(candidates) + " THEN (" +
                           " AND ".join(structural) + ") ELSE 0 END")
            args.extend(candidate_args + structural_args)
        with self._transaction_lock:
            self._require_open()
            index_clause = ""
            if indexed:
                index_clause = " INDEXED BY " + ("identities_due_native_lookup"
                    if ('target', 'native_adapter') in payload_matches else "identities_due_project_lookup"
                    if ('project_ref',) in payload_matches else "identities_due_native_lookup")
            rows = self._connection.execute(
                "SELECT authority, kind, id, current_revision FROM identities" + index_clause + " WHERE " +
                " AND ".join(clauses) + " ORDER BY id", args).fetchall()
            return tuple(ResourceRef(row[0], row[1], row[2], row[3]) for row in rows)

    @staticmethod
    def _structural_path(path: Any) -> str:
        if (not isinstance(path, tuple) or not path or len(path) > 8
                or not all(isinstance(part, str) and part and part.replace('_', '').isalnum() for part in path)):
            raise ValueError("identity payload paths must be structural names")
        return '$.' + '.'.join(path)

    def project_identity_fields(self, *, kind: str, match_path: Tuple[str, ...], match_values: Sequence[str],
                                fields: Mapping[str, Tuple[str, ...]],
                                payload_matches: Optional[Mapping[Tuple[str, ...], str]] = None,
                                payload_in: Optional[Mapping[Tuple[str, ...], Sequence[str]]] = None,
                                ) -> Tuple[Mapping[str, Any], ...]:
        """Named current fields of the identities whose ``match_path`` is one of ``match_values``.

        A bounded projection for multi-project summaries: one read of the
        current identities of one kind, never event history, returning only
        the named fields plus ``ref`` and ``updated_at``. Paths are structural
        names; every path and value is an SQL parameter.
        """
        values = tuple(match_values)
        if (not isinstance(kind, str) or not kind.strip() or not isinstance(fields, Mapping) or not fields
                or len(fields) > 32 or len(values) > 1000 or not all(isinstance(value, str) for value in values)):
            raise ValueError("identity kind, string match values and named fields required")
        if not values:
            return ()
        match = self._structural_path(match_path)
        columns, args = [], []
        for name, path in fields.items():
            if not isinstance(name, str) or not name.replace('_', '').isalnum():
                raise ValueError("projected field names must be identifiers")
            columns.append("?, json_extract(payload_json, ?)")
            args.extend([name, self._structural_path(path)])
        clauses = ["authority = ?", "kind = ?", "json_extract(payload_json, ?) IN (" + ",".join("?" for _ in values) + ")"]
        args.extend([self.authority, kind, match, *values])
        for path, value in (payload_matches or {}).items():
            if not isinstance(value, str):
                raise ValueError("identity payload predicates require string values")
            clauses.append("json_extract(payload_json, ?) = ?")
            args.extend([self._structural_path(path), value])
        for path, choices in (payload_in or {}).items():
            choices = tuple(choices)
            if not choices or not all(isinstance(choice, str) for choice in choices):
                raise ValueError("identity payload choices require string values")
            clauses.append("json_extract(payload_json, ?) IN (" + ",".join("?" for _ in choices) + ")")
            args.extend([self._structural_path(path), *choices])
        with self._transaction_lock:
            self._require_open()
            rows = self._connection.execute(
                "SELECT authority, kind, id, current_revision, updated_at, json_object(" + ", ".join(columns) +
                ") FROM identities WHERE " + " AND ".join(clauses) + " ORDER BY id", args).fetchall()
        return tuple({**json.loads(row[5]), "ref": ResourceRef(row[0], row[1], row[2], row[3]).to_dict(),
                      "updated_at": row[4]} for row in rows)

    def project_identity_fields_for_refs(self, refs: Sequence[ResourceRef], *,
                                         fields: Mapping[str, Tuple[str, ...]],
                                         max_projection_bytes: int = 32768,
                                         max_refs: int = 100) -> Tuple[Mapping[str, Any], ...]:
        """Project named fields from an exact, finite set of identity keys.

        Unlike ``project_identity_fields``, this method chooses identities by
        their primary keys before evaluating any JSON path. It is intended for
        bounded joins from already trusted canonical refs, so unrelated large
        legacy payloads cannot poison the read. A requested revision is an
        exact pin: stale pins return a ``stale`` state without projecting the
        newer payload. Only named fields are returned; full payloads are never
        hydrated into Python.
        """
        values = tuple(refs)
        if (not isinstance(refs, (list, tuple)) or type(max_refs) is not int
                or not 1 <= max_refs <= 100 or len(values) > max_refs
                or type(max_projection_bytes) is not int
                or not 1 <= max_projection_bytes <= 262144
                or not isinstance(fields, Mapping) or not fields or len(fields) > 32):
            raise ValueError("bounded exact refs and named fields required")
        if not all(isinstance(ref, ResourceRef) for ref in values):
            raise ValueError("identity projections require ResourceRef keys")
        if any(ref.authority != self.authority for ref in values):
            raise ValueError("identity projection ref authority does not belong to this store")
        if len({(ref.authority, ref.kind, ref.id) for ref in values}) != len(values):
            raise ValueError("identity projection refs must be unique")
        normalized_fields = []
        for name, path in fields.items():
            if (not isinstance(name, str) or not name.replace("_", "").isalnum()
                    or not isinstance(path, tuple)):
                raise ValueError("projected field names and paths must be structural")
            normalized_fields.append((name, self._structural_path(path)))
        if not values:
            return ()
        requested = ", ".join("(?, ?, ?, ?, ?)" for _ in values)
        projected_fields = ", ".join("?, json_extract(s.payload_json, ?)" for _name, _path in normalized_fields)
        present_fields = ", ".join("?, json_type(s.payload_json, ?) IS NOT NULL" for _name, _path in normalized_fields)
        value_size_terms = " + ".join(
            "coalesce(length(CAST(json_extract(s.payload_json, ?) AS BLOB)), 0)"
            for _name, _path in normalized_fields)
        projection_expr = ("json_object('fields', json_object(" + projected_fields
                           + "), 'present', json_object(" + present_fields + "))")
        args: list[Any] = []
        for ordinal, ref in enumerate(values):
            args.extend((ordinal, ref.authority, ref.kind, ref.id, ref.revision))
        # Check selected value sizes before constructing the JSON envelope. The
        # exact final envelope is still measured below to include JSON overhead.
        args.extend(path for _name, path in normalized_fields)
        args.append(max_projection_bytes)
        args.extend(arg for name, path in normalized_fields for arg in (name, path))
        args.extend(arg for name, path in normalized_fields for arg in (name, path))
        args.append(max_projection_bytes)
        with self._transaction_lock:
            self._require_open()
            rows = self._connection.execute(
                "WITH requested(ord, authority, kind, id, requested_revision) AS MATERIALIZED (VALUES " + requested + "), "
                "selected AS MATERIALIZED (SELECT r.ord, r.requested_revision, i.current_revision, i.updated_at, "
                "i.payload_json FROM requested r LEFT JOIN identities i "
                "ON i.authority=r.authority AND i.kind=r.kind AND i.id=r.id), "
                "projected AS MATERIALIZED (SELECT s.ord, s.requested_revision, s.current_revision, s.updated_at, "
                "s.payload_json, CASE WHEN " + value_size_terms + " <= ? THEN " + projection_expr
                + " END AS projection FROM selected s) "
                "SELECT ord, requested_revision, current_revision, updated_at, "
                "CASE WHEN current_revision IS NULL THEN 1 ELSE 0 END, "
                "length(CAST(projection AS BLOB)), "
                "CASE WHEN length(CAST(projection AS BLOB)) <= ? THEN projection END "
                "FROM projected ORDER BY ord",
                args,
            ).fetchall()
        projected = []
        total_bytes = 0
        for row in rows:
            ordinal, requested_revision, current_revision, updated_at, missing, projected_bytes, raw_projection = row
            ref = values[ordinal]
            current_ref = (None if missing else
                           ResourceRef(ref.authority, ref.kind, ref.id, current_revision).to_dict())
            if missing:
                projected.append({"state": "missing", "requested_ref": ref.to_dict(),
                                  "ref": None, "fields": {}, "projected_bytes": 0})
                continue
            if requested_revision is not None and requested_revision != current_revision:
                projected.append({"state": "stale", "requested_ref": ref.to_dict(),
                                  "ref": current_ref, "fields": {}, "projected_bytes": 0})
                continue
            if raw_projection is None:
                projected.append({"state": "oversize", "requested_ref": ref.to_dict(),
                                  "ref": current_ref, "fields": {}, "present": {},
                                  "projected_bytes": projected_bytes})
                continue
            try:
                envelope = json.loads(raw_projection)
            except (TypeError, ValueError):
                projected.append({"state": "invalid-projection", "requested_ref": ref.to_dict(),
                                  "ref": current_ref, "fields": {}, "present": {},
                                  "projected_bytes": projected_bytes})
                continue
            total_bytes += projected_bytes
            if total_bytes > max_projection_bytes:
                projected.append({"state": "oversize", "requested_ref": ref.to_dict(),
                                  "ref": current_ref, "fields": {}, "present": {},
                                  "projected_bytes": projected_bytes})
                continue
            projected.append({"state": "available", "requested_ref": ref.to_dict(),
                              "ref": current_ref, "updated_at": updated_at,
                              "fields": {name: envelope["fields"].get(name)
                                         for name, present in envelope["present"].items() if present},
                              "present": envelope["present"], "projected_bytes": projected_bytes})
        return tuple(projected)

    def get_record(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.get_identity(ref)

    def get_identity_ref(self, ref: ResourceRef) -> Optional[ResourceRef]:
        """Exact existence/current-pin read without selecting payload bytes."""
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT current_revision FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id)).fetchone()
            return None if row is None else ResourceRef(ref.authority, ref.kind, ref.id, row[0])

    def read_identity_page(self, *, kind: str, after: str = "", limit: int = 50,
                           max_record_bytes: int = 65536,
                           payload_matches: Optional[Mapping[Tuple[str, ...], str]] = None) -> Mapping[str, Any]:
        """Seek a finite PK window before decoding or applying domain filters.

        Empty domain pages still advance. Oversized legacy records are held,
        never hydrated by this metadata reader. No new tables or descriptors.
        """
        if (not isinstance(kind, str) or not kind or not isinstance(after, str)
                or len(after) > 512 or type(limit) is not int or not 1 <= limit <= 100
                or type(max_record_bytes) is not int or not 1 <= max_record_bytes <= 65536):
            raise ValueError("invalid bounded identity page")
        if payload_matches is not None:
            if not isinstance(payload_matches, Mapping) or len(payload_matches) > 16:
                raise ValueError("invalid identity page predicates")
            for path, value in payload_matches.items():
                if (not isinstance(path, tuple) or not path or len(path) > 8
                        or not all(isinstance(part, str) and part and part.replace('_', '').isalnum() for part in path)
                        or not isinstance(value, str)):
                    raise ValueError("identity page predicates require structural paths and string values")
        with self._transaction_lock:
            self._require_open()
            rows = self._connection.execute(
                "SELECT authority, kind, id, current_revision, version, edit_token, created_at, updated_at, "
                "CASE WHEN length(CAST(payload_json AS BLOB)) <= ? THEN payload_json END AS payload_json "
                "FROM identities WHERE authority = ? AND kind = ? AND id > ? ORDER BY id LIMIT ?",
                (max_record_bytes, self.authority, kind, after, limit)).fetchall()
            records = tuple(self._identity_from_row(row) for row in rows if row["payload_json"] is not None)
            # Domain predicates run only AFTER the finite PK/byte window.
            # SQL JSON predicates would parse arbitrarily large rejected
            # historical bodies before LIMIT; never hide that work here.
            def matches(record):
                for path, value in (payload_matches or {}).items():
                    found = record.payload
                    for part in path:
                        found = found.get(part) if isinstance(found, Mapping) else None
                    if not isinstance(found, str) or found != value:
                        return False
                return True
            records = tuple(record for record in records if matches(record))
            return {"records": records, "examined": len(rows),
                    "held": sum(row["payload_json"] is None for row in rows),
                    "next_cursor": rows[-1]["id"] if len(rows) == limit else None,
                    "bytes_parsed": sum(len(row["payload_json"].encode()) for row in rows if row["payload_json"] is not None)}

    def get_identity_bounded(self, ref: ResourceRef, *, max_record_bytes: int = 65536) -> Mapping[str, Any]:
        """Exact bounded metadata read; missing and oversize are explicit."""
        if type(max_record_bytes) is not int or not 1 <= max_record_bytes <= 65536:
            raise ValueError("invalid metadata byte bound")
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT authority, kind, id, current_revision, version, edit_token, created_at, updated_at, "
                "CASE WHEN length(CAST(payload_json AS BLOB)) <= ? THEN payload_json END AS payload_json "
                "FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (max_record_bytes, ref.authority, ref.kind, ref.id)).fetchone()
            return {"record": self._identity_from_row(row) if row is not None and row["payload_json"] is not None else None,
                    "state": "missing" if row is None else "detail-required" if row["payload_json"] is None else "available",
                    "bytes_parsed": len(row["payload_json"].encode()) if row is not None and row["payload_json"] is not None else 0}

    def revise_identity(
        self,
        ref: ResourceRef,
        payload: Mapping[str, Any],
        *,
        revision: str,
        expected_revision: Optional[str],
        expected_version: int,
        expected_edit_token: Optional[str] = None,
        transaction: Optional[Transaction] = None,
        history_event_id: Optional[str] = None,
    ) -> IdentityRecord:
        """CAS-revise one admitted identity through the common writer.

        ``ref`` must be the current reference, and ``expected_revision`` must
        repeat its pin (or both must be ``None`` for an unpinned identity).
        Numeric ``rev-N`` revisions advance exactly by one.  A legacy opaque
        current revision is accepted only for one bounded transition to
        ``rev-(expected_version + 1)``; subsequent revisions are numeric.
        The method emits no receipt or event and uses a caller transaction when
        supplied, so a parent operation can own the single logical boundary.
        """
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("identity authority does not belong to this store")
        if ref.revision != expected_revision:
            raise TargetMismatchError("expected_revision must match the supplied current reference")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        payload_json = _json(dict(payload))
        # ResourceRef performs the contract's revision validation.  Revisions
        # are required for a revision operation even though identity creation
        # permits an unpinned ref.
        if revision is None:
            raise ValueError("revision must be pinned for an identity revision")
        new_ref = ResourceRef(self.authority, ref.kind, ref.id, revision)
        if expected_edit_token is not None and (
            not isinstance(expected_edit_token, str) or not expected_edit_token
        ):
            raise ValueError("expected_edit_token must be a non-blank string when supplied")

        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._revise_identity(owned, ref, new_ref, payload_json, expected_revision, expected_version, expected_edit_token, history_event_id)
        return self._revise_identity(tx, ref, new_ref, payload_json, expected_revision, expected_version, expected_edit_token, history_event_id)

    def _revise_identity(
        self,
        tx: Transaction,
        ref: ResourceRef,
        new_ref: ResourceRef,
        payload_json: str,
        expected_revision: Optional[str],
        expected_version: int,
        expected_edit_token: Optional[str],
        history_event_id: Optional[str] = None,
    ) -> IdentityRecord:
        with tx.savepoint():
            row = tx.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            if row is None:
                raise TargetMismatchError("identity does not exist")
            current = self._identity_from_row(row)
            if current.ref.revision != ref.revision or current.ref.revision != expected_revision:
                raise TargetMismatchError("supplied reference is not the current identity reference")
            if current.version != expected_version:
                raise VersionConflictError("expected version does not match current version")
            if expected_edit_token is not None and current.edit_token != expected_edit_token:
                raise VersionConflictError("expected edit token does not match")

            current_numeric = None if current.revision is None else _NUMERIC_REVISION.fullmatch(current.revision)
            if current_numeric is not None:
                expected_new_revision = "rev-{}".format(int(current_numeric.group(1)) + 1)
            else:
                expected_new_revision = "rev-{}".format(expected_version + 1)
            if new_ref.revision != expected_new_revision:
                raise VersionConflictError(
                    "revision must advance exactly to {}".format(expected_new_revision)
                )

            now = _now()
            where = (
                "WHERE authority = ? AND kind = ? AND id = ? "
                "AND (current_revision = ? OR (current_revision IS NULL AND ? IS NULL)) "
                "AND version = ?"
            )
            parameters = [
                new_ref.revision,
                expected_version + 1,
                payload_json,
                now,
                ref.authority,
                ref.kind,
                ref.id,
                expected_revision,
                expected_revision,
                expected_version,
            ]
            if expected_edit_token is not None:
                where += " AND edit_token = ?"
                parameters.append(expected_edit_token)
            updated = tx.execute(
                "UPDATE identities SET current_revision = ?, version = ?, payload_json = ?, updated_at = ? " + where,
                parameters,
            )
            if updated.rowcount != 1:
                raise StoreError("identity revision affected {} rows, expected exactly one".format(updated.rowcount))
            self.put_reference(new_ref, transaction=tx)
            revised = tx.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            if revised is None:
                raise StoreError("revised identity disappeared before readback")
            if history_event_id is not None:
                self._capture_child(tx, history_event_id, current.ref, current.payload, new_ref, json.loads(payload_json))
            return self._identity_from_row(revised)

    @property
    def domain_descriptor_digest(self) -> str:
        self._require_open()
        return self._domain_descriptor_digest

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        """Return the admitted typed optional-domain descriptors in stable order."""
        self._require_open()
        return tuple(self._domain_descriptors[key] for key in sorted(self._domain_descriptors))

    def issue_operation_owner(self) -> OperationOwnerCapability:
        """Issue the narrow trusted capability used by operation composition."""
        self._require_open()
        return OperationOwnerCapability(self, _construction_token=_OPERATION_OWNER_CONSTRUCTION_TOKEN)

    def register_domain(
        self,
        contribution: DomainContribution,
        *,
        transaction: Optional[Transaction] = None,
    ) -> DomainContribution:
        """Register one typed descriptor using the common writer transaction."""
        if not isinstance(contribution, DomainContribution):
            raise TypeError("contribution must be a DomainContribution")
        tx, own = self._active_or_transaction(transaction)
        if own:
            # Serialize the read/preflight with transaction admission.  This
            # keeps the candidate from going stale if two callers register
            # different descriptors concurrently, while the digest work stays
            # outside BEGIN IMMEDIATE.
            with self._transaction_lock:
                candidate, candidate_digest = self._validated_domain_candidate(contribution, self._domain_descriptors)
                with self.transaction() as owned:
                    return self._register_domain(owned, contribution, candidate, candidate_digest)
        candidate, candidate_digest = self._validated_domain_candidate(contribution, tx._domain_working)
        return self._register_domain(tx, contribution, candidate, candidate_digest)

    def register_domain_handler(self, contributions: Sequence[DomainContribution]) -> "DomainHandler":
        """Atomically register exact descriptors and issue their sealed handler."""
        descriptors = tuple(contributions)
        if not descriptors or any(not isinstance(item, DomainContribution) for item in descriptors):
            raise TypeError("contributions must be a non-empty sequence of DomainContribution values")
        with self.transaction() as tx:
            for contribution in descriptors:
                self.register_domain(contribution, transaction=tx)
        return self.domain_handler(descriptors)

    def domain_handler(self, contributions: Sequence[DomainContribution]) -> "DomainHandler":
        """Issue a handler only for an exact, already-persisted descriptor set."""
        descriptors = tuple(contributions)
        if not descriptors or any(not isinstance(item, DomainContribution) for item in descriptors):
            raise TypeError("contributions must be a non-empty sequence of DomainContribution values")
        for contribution in descriptors:
            if self._domain_descriptors.get(contribution.domain_id) != contribution:
                raise MutationAdmissionError(
                    "handler descriptor is not the exact registered definition: {}".format(contribution.domain_id)
                )
        handler = DomainHandler(self, descriptors, _construction_token=_HANDLER_CONSTRUCTION_TOKEN)
        self._issued_handlers.add(handler)
        return handler

    def issue_command_port(
        self,
        engine: Any,
        domain_id: str,
        endpoints: Sequence[str],
        *,
        reader: Optional["ConsumerStore"] = None,
    ) -> DomainCommandPort:
        """Issue one authenticated finite port during trusted composition."""
        self._require_open()
        selected_reader = self.consumer() if reader is None else reader
        return DomainCommandPort(
            engine, domain_id, endpoints, selected_reader,
            _construction_token=_COMMAND_PORT_CONSTRUCTION_TOKEN,
        )

    def _validated_domain_candidate(
        self,
        contribution: DomainContribution,
        existing: Mapping[str, DomainContribution],
    ) -> Tuple[Dict[str, DomainContribution], str]:
        registry = DomainRegistry()
        for descriptor in existing.values():
            registry.register(descriptor)
        registry.register(contribution)
        candidate = dict(existing)
        candidate[contribution.domain_id] = contribution
        return candidate, _descriptor_digest(candidate.values())

    def _register_domain(
        self,
        tx: Transaction,
        contribution: DomainContribution,
        candidate: Mapping[str, DomainContribution],
        candidate_digest: str,
    ) -> DomainContribution:
        with tx.savepoint():
            ref = ResourceRef(self.authority, DOMAIN_KIND, contribution.domain_id, contribution.version)
            existing = tx.execute(
                "SELECT 1 FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            if existing is not None:
                raise ContractError("duplicate domain identity: {}".format(contribution.domain_id))
            now = _now()
            tx.execute(
                "INSERT INTO identities(authority, kind, id, current_revision, version, edit_token, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref.authority, ref.kind, ref.id, ref.revision, 1, None, _json(contribution.to_dict()), now, now),
            )
            self._store_reference(tx, ref)
            tx.execute(
                "UPDATE store_metadata SET value = ? WHERE key = ?",
                (candidate_digest, DOMAIN_DESCRIPTOR_DIGEST_KEY),
            )
            tx._domain_working = candidate
            tx._domain_digest = candidate_digest
            return contribution

    def put_reference(self, ref: ResourceRef, *, transaction: Optional[Transaction] = None) -> ResourceRef:
        """Durably retain a validated reference to an admitted identity."""
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("reference authority does not belong to this store")
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                self._store_reference(owned, ref)
        else:
            self._store_reference(tx, ref)
        return ref

    def _store_reference(self, tx: Transaction, ref: ResourceRef) -> None:
        tx.execute(
            "INSERT OR IGNORE INTO record_references(reference_key, authority, kind, id, revision, reference_json) VALUES (?, ?, ?, ?, ?, ?)",
            (_ref_key(ref), ref.authority, ref.kind, ref.id, ref.revision, ref.to_json()),
        )

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]:
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT reference_json FROM record_references WHERE reference_key = ?", (_ref_key(ref),)
            ).fetchone()
            return None if row is None else ResourceRef.from_dict(json.loads(row[0]))

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT * FROM command_receipts WHERE logical_request_key = ?", (logical_request_key,)
            ).fetchone()
            return None if row is None else self._receipt_from_row(row)

    def _receipt_from_row(self, row: sqlite3.Row) -> CommandReceipt:
        target = ResourceRef(row["target_authority"], row["target_kind"], row["target_id"], row["target_revision"])
        result = None if row["result_ref_json"] is None else ResourceRef.from_dict(json.loads(row["result_ref_json"]))
        return CommandReceipt(
            row["logical_request_key"], row["request_digest"], row["operation"], target,
            ReceiptStatus(row["status"]), row["transaction_id"], tuple(json.loads(row["event_ids_json"])),
            result, row["error_code"], bool(row["replayed"]), row["observed_revision"], row["unknown_reason"],
        )

    def _insert_receipt(self, tx: Transaction, receipt: CommandReceipt) -> None:
        target = receipt.target
        tx.execute(
            "INSERT INTO command_receipts(logical_request_key, request_digest, operation, target_authority, target_kind, target_id, target_revision, status, transaction_id, event_ids_json, result_ref_json, error_code, replayed, observed_revision, unknown_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt.logical_request_key, receipt.request_digest, receipt.operation,
                target.authority, target.kind, target.id, target.revision, receipt.status.value,
                receipt.transaction_id, _json(receipt.event_ids), _ref_json(receipt.result_ref),
                receipt.error_code, int(receipt.replayed), receipt.observed_revision, receipt.unknown_reason,
            ),
        )

    def _next_sequence(self, tx: Transaction, stream: str) -> int:
        row = tx.execute(
            "SELECT next_sequence FROM event_sequences WHERE store_authority = ? AND stream = ?",
            (self.authority, stream),
        ).fetchone()
        if row is None:
            tx.execute("INSERT INTO event_sequences(store_authority, stream, next_sequence) VALUES (?, ?, ?)", (self.authority, stream, 2))
            return 1
        sequence = row[0]
        tx.execute("UPDATE event_sequences SET next_sequence = ? WHERE store_authority = ? AND stream = ?", (sequence + 1, self.authority, stream))
        return sequence

    def mutate(
        self,
        envelope: CommandEnvelope,
        *,
        event_type: str,
        result_ref: Optional[ResourceRef] = None,
        before_refs: Sequence[ResourceRef] = (),
        after_refs: Sequence[ResourceRef] = (),
        effects: Optional[Mapping[str, Any]] = None,
        stream: Optional[str] = None,
        event_schema_revision: str = "fnd-03.event.v1",
        occurred_at: Optional[str] = None,
        no_op: bool = False,
        transaction: Optional[Transaction] = None,
        _handler: Optional["DomainHandler"] = None,
        _identity_payload: Optional[Mapping[str, Any]] = None,
    ) -> CommandReceipt:
        if not isinstance(envelope, CommandEnvelope):
            raise TypeError("envelope must be a CommandEnvelope")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-blank string")
        if not isinstance(effects or {}, Mapping):
            raise TypeError("effects must be a mapping")
        if _identity_payload is not None and not isinstance(_identity_payload, Mapping):
            raise TypeError("identity payload must be a mapping")
        request_digest = canonical_request_digest(
            logical_request_key=envelope.context.logical_request_key,
            operation=envelope.operation,
            schema_revision=envelope.schema_revision,
            target=envelope.target,
            actor=envelope.context.actor,
            payload=envelope.payload,
            context=envelope.context,
        )
        envelope = replace(
            envelope,
            context=replace(envelope.context, request_digest=request_digest),
        )
        # Validate all contract-shaped values before taking the writer path.
        effects_json = _json(dict(effects or {}))
        before_refs = tuple(before_refs)
        after_refs = tuple(after_refs)
        if any(not isinstance(ref, ResourceRef) for ref in before_refs + after_refs):
            raise TypeError("before_refs and after_refs must contain ResourceRef values")
        # Resolve the trusted owner before transaction admission.  A rejected
        # combination therefore cannot allocate an identity, sequence,
        # reference, event, or receipt.
        self._admit_mutation(envelope, event_type, _handler)
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._mutate(owned, envelope, event_type, result_ref, before_refs, after_refs, effects_json, stream, event_schema_revision, occurred_at, no_op, _identity_payload)
        return self._mutate(tx, envelope, event_type, result_ref, before_refs, after_refs, effects_json, stream, event_schema_revision, occurred_at, no_op, _identity_payload)

    @staticmethod
    def _actor_bound_to_owner(envelope: CommandEnvelope, owner: str, bindings: Iterable[str] = ()) -> bool:
        actor = envelope.context.actor
        exact_authorities = {
            binding.split(":", 1)[1]
            for binding in bindings
            if binding.startswith("actor-authority:")
        }
        exact_actors = {
            binding.split(":", 1)[1]
            for binding in bindings
            if binding.startswith("actor-id:")
        }
        if exact_authorities or exact_actors:
            # Explicit descriptor bindings are exact authority constraints,
            # not namespace/root hints.  When both forms are declared both
            # constraints apply; an actor id can never stand in for a
            # declared authority (or vice versa).
            return (
                (not exact_authorities or actor.authority in exact_authorities)
                and (not exact_actors or actor.actor in exact_actors)
            )
        owner_root = _authority_root(owner)
        return (
            actor.authority == owner
            or actor.actor == owner
            or _authority_root(actor.authority) == owner_root
            or _authority_root(actor.actor) == owner_root
        )

    def _admit_mutation(self, envelope: CommandEnvelope, event_type: str, handler: Optional["DomainHandler"] = None) -> str:
        """Resolve one command to its persisted domain owner or neutral port."""
        matches = []
        for descriptor in self._domain_descriptors.values():
            if envelope.operation not in descriptor.operation_types or event_type not in descriptor.event_types:
                continue
            resources = set(descriptor.resource_types)
            bindings = set(descriptor.composition_bindings)
            resource_allowed = envelope.target.kind in resources
            resource_allowed = resource_allowed or "mutation-resource:{}".format(envelope.target.kind) in bindings
            if "mutation-resource:registered:*" in bindings:
                resource_allowed = resource_allowed or any(
                    envelope.target.kind in candidate.resource_types
                    for candidate in self._domain_descriptors.values()
                )
            if not resource_allowed:
                continue
            if envelope.schema_revision != descriptor.schema_revision:
                continue
            declared_ports = {
                binding.split(":", 1)[1]
                for binding in bindings
                if binding.startswith("mutation-port:")
            }
            if declared_ports and "|".join((
                envelope.schema_revision,
                envelope.operation,
                envelope.target.kind,
                event_type,
            )) not in declared_ports:
                wildcard_resource_port = "|".join((
                    envelope.schema_revision,
                    envelope.operation,
                    "*",
                    event_type,
                ))
                if wildcard_resource_port not in declared_ports:
                    continue
            matches.append(descriptor)
        if len(matches) == 1:
            admitted = matches[0]
            if "handler-required" in admitted.composition_bindings:
                if (
                    handler is None
                    or handler not in self._issued_handlers
                    or handler._owner is not self
                    or admitted.domain_id not in handler.domain_ids
                ):
                    raise MutationAdmissionError(
                        "mutation requires the sealed handler for admitted owner {!r}".format(admitted.owner)
                    )
                return admitted.owner
            if not self._actor_bound_to_owner(envelope, admitted.owner, admitted.composition_bindings):
                raise MutationAdmissionError(
                    "authenticated actor {!r} is not bound to admitted owner {!r}".format(
                        envelope.context.actor.actor, admitted.owner
                    )
                )
            return admitted.owner
        if len(matches) > 1:
            raise MutationAdmissionError("mutation combination resolves to more than one domain owner")

        for operation, resources, events, schema in _CORE_MUTATION_PORTS:
            operation_allowed = envelope.operation == operation
            if operation is None:
                operation_allowed = envelope.target.kind == "operation" and envelope.operation != "operation.outcome"
            if operation_allowed and envelope.target.kind in resources and event_type in events and (schema is None or envelope.schema_revision == schema):
                return "fnd"
        raise MutationAdmissionError(
            "unregistered mutation combination: operation={!r}, resource={!r}, event={!r}, schema={!r}".format(
                envelope.operation, envelope.target.kind, event_type, envelope.schema_revision
            )
        )


    def _mutate(
        self, tx: Transaction, envelope: CommandEnvelope, event_type: str,
        result_ref: Optional[ResourceRef], before_refs: Tuple[ResourceRef, ...], after_refs: Tuple[ResourceRef, ...],
        effects_json: str, stream: Optional[str], event_schema_revision: str,
        occurred_at: Optional[str], no_op: bool, identity_payload: Optional[Mapping[str, Any]],
    ) -> CommandReceipt:
        with tx.savepoint():
            existing = tx.execute(
                "SELECT * FROM command_receipts WHERE logical_request_key = ?",
                (envelope.context.logical_request_key,),
            ).fetchone()
            if existing is not None:
                prior = self._receipt_from_row(existing)
                validate_replay(prior, envelope)
                return prior

            target = envelope.target
            if target.authority != self.authority:
                raise TargetMismatchError("command target authority does not belong to this store")
            row = tx.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (target.authority, target.kind, target.id),
            ).fetchone()
            if row is None:
                if envelope.context.expected_version not in (None, 0) or envelope.context.expected_revision is not None or target.revision is not None:
                    raise TargetMismatchError("target identity is not admitted")
                current_revision, current_version, current_token, current_payload = None, 0, None, {}
            else:
                current_revision, current_version, current_token, current_payload = row["current_revision"], row["version"], row["edit_token"], json.loads(row["payload_json"])
                if target.revision is not None and target.revision != current_revision:
                    raise TargetMismatchError("target reference revision does not match current identity")
            try:
                validate_expected_state(
                    envelope.context,
                    current_revision=current_revision,
                    current_version=current_version,
                    supplied_edit_token=current_token,
                )
            except ValueError as exc:
                raise VersionConflictError(str(exc)) from exc

            if no_op:
                receipt = CommandReceipt(
                    envelope.context.logical_request_key, envelope.context.request_digest,
                    envelope.operation, target, ReceiptStatus.NOOP,
                    observed_revision=current_revision,
                )
                if row is None:
                    self._put_identity(tx, target, _json({}), 0, None)
                self._store_reference(tx, target)
                self._insert_receipt(tx, receipt)
                return receipt

            next_version = current_version + 1
            persisted_payload = envelope.payload if identity_payload is None else identity_payload
            if result_ref is None:
                revision = "rev-{}".format(next_version)
                result_ref = ResourceRef(target.authority, target.kind, target.id, revision)
            if (result_ref.authority, result_ref.kind, result_ref.id) != (target.authority, target.kind, target.id) or result_ref.revision is None:
                raise TargetMismatchError("result reference must pin the exact target identity")
            if row is None:
                created_at = _now()
                tx.execute(
                    "INSERT INTO identities(authority, kind, id, current_revision, version, edit_token, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (target.authority, target.kind, target.id, result_ref.revision, next_version, None, _json(persisted_payload), created_at, created_at),
                )
            else:
                tx.execute(
                    "UPDATE identities SET current_revision = ?, version = ?, payload_json = ?, updated_at = ? WHERE authority = ? AND kind = ? AND id = ?",
                    (result_ref.revision, next_version, _json(persisted_payload), _now(), target.authority, target.kind, target.id),
                )

            stream_name = stream or "{}:{}".format(target.kind, target.id)
            sequence = self._next_sequence(tx, stream_name)
            transaction_id = secrets.token_hex(16)
            event_id = "event-{}".format(secrets.token_hex(16))
            before = before_refs or (() if current_revision is None else (ResourceRef(target.authority, target.kind, target.id, current_revision),))
            after = after_refs or (result_ref,)
            for ref in before + after:
                self._store_reference(tx, ref)
            recorded_at = _now()
            effects = json.loads(effects_json)
            if "history_summary" in effects:
                raise StoreError("history_summary is reserved for the authoritative writer")
            facet_type = "creation_or_revision"
            if row is not None and current_payload.get("lifecycle") != persisted_payload.get("lifecycle"):
                facet_type = "lifecycle_transition"
            elif event_type in {"work.assignment.reassigned", "work.assignment.resources-adopted"}:
                facet_type = "replacement_or_adoption"
            elif event_type == "work.result.appended" and result_ref.kind == "wrk.result":
                facet_type = "retained_attempt_or_result"
            primary = self._history_transition(tx, None if row is None else ResourceRef(target.authority, target.kind, target.id, current_revision),
                                               None if row is None else current_payload, result_ref, persisted_payload, facet_type)
            effects["history_summary"] = {"schema": HISTORY_SCHEMA, "primary": primary, "facets": []}
            tx._history[event_id] = []
            event = EventEnvelope(
                event_id, self.authority, stream_name, result_ref, event_schema_revision,
                event_type, sequence, envelope.context.actor, envelope.operation,
                envelope.context.correlation_id, envelope.context.causation_id,
                recorded_at, occurred_at, before, after, effects,
            )
            tx.execute(
                "INSERT INTO events(append_position, event_id, store_authority, stream, subject_authority, subject_kind, subject_id, subject_revision, schema_revision, event_type, sequence, actor_authority, actor_id, credential_ref, correlation_id, causation_id, operation, recorded_at, occurred_at, before_refs_json, after_refs_json, effects_json, transaction_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._next_append(tx), event.event_id, event.store_authority, event.stream, result_ref.authority, result_ref.kind,
                    result_ref.id, result_ref.revision, event.schema_revision, event.event_type, event.sequence,
                    event.actor.authority, event.actor.actor, event.actor.credential_ref, event.correlation_id,
                    event.causation_id, event.operation, event.recorded_at, event.occurred_at,
                    _json([ref.to_dict() for ref in event.before_refs]), _json([ref.to_dict() for ref in event.after_refs]),
                    _json(event.effects), transaction_id,
                ),
            )
            receipt = CommandReceipt(
                envelope.context.logical_request_key, envelope.context.request_digest,
                envelope.operation, target, ReceiptStatus.COMMITTED, transaction_id,
                (event.event_id,), result_ref, observed_revision=result_ref.revision,
            )
            self._store_reference(tx, target)
            self._insert_receipt(tx, receipt)
            self._schedule_history_projection(tx)
            return receipt

    def _next_append(self, tx: Transaction) -> int:
        row = tx.execute("SELECT value FROM store_metadata WHERE key = 'source_next_append'").fetchone()
        if row is None:
            raise StoreAdmissionError("source append allocator is missing")
        position = int(row[0])
        tx.execute("UPDATE store_metadata SET value = ? WHERE key = 'source_next_append'", (str(position + 1),))
        return position

    def configure_history_publisher(self, publisher) -> None:
        """Trusted host composition only; never an exposed client endpoint."""
        self._require_open()
        if publisher is not None and not callable(publisher):
            raise TypeError("history publisher must be callable")
        self._history_publisher = publisher

    def configure_history_projection(self, projection=None, *, manifest_reader=None,
                                     batch_size: int = 100):
        """Attach the bounded D03 projector at the owner composition boundary."""
        from .project_history import ProjectHistoryProjection

        if projection is None:
            projection = ProjectHistoryProjection(self, manifest_reader=manifest_reader,
                                                   default_batch=batch_size)
        if not isinstance(projection, ProjectHistoryProjection) or projection.store is not self:
            raise StoreError("history projection must be owned by this Store")
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        self._history_projection = projection
        self._history_projection_limit = batch_size
        return projection

    def project_history_projection(self):
        """Return the configured projector, or construct an inert owner projector."""
        if self._history_projection is None:
            from .project_history import ProjectHistoryProjection
            self._history_projection = ProjectHistoryProjection(self)
        return self._history_projection

    def project_history_reader(self, *, grant=None, grant_reader=None, evidence_reader=None):
        from .project_history import ProjectHistoryReader
        return ProjectHistoryReader(self, grant=grant, grant_reader=grant_reader,
                                    evidence_reader=evidence_reader)

    def maintain_project_history(self, *, limit=None):
        return self.project_history_projection().maintain(limit=limit)

    def rebuild_project_history(self, *, batch_size=None):
        return self.project_history_projection().rebuild(batch_size=batch_size)

    def _schedule_history_projection(self, tx: Transaction) -> None:
        projection = self._history_projection
        if projection is None or getattr(tx, "_history_projection_scheduled", False):
            return
        tx._history_projection_scheduled = True
        tx._after_commit.append(lambda: projection.maintain(limit=self._history_projection_limit))

    def _history_transition(self, tx, before_ref, before_payload, after_ref, after_payload,
                            facet_type="creation_or_revision"):
        summary = transition(before_ref, before_payload, after_ref, after_payload, facet_type=facet_type)
        projects, resolutions = {}, []
        # Task-scoped assignment membership is resolved from the exact task
        # revision. A stale pin never borrows a changed current head.
        for side, payload in (("before", before_payload), ("after", after_payload)):
            if not payload:
                continue
            scope = payload.get("scope")
            # Observation membership comes from its exact canonical assignment
            # at capture. Result JSON cannot select a project; later readers
            # never resolve a historical observation through current heads.
            assignment = payload.get("assignment")
            if isinstance(assignment, ResourceRef):
                assignment = assignment.to_dict()
            if scope is None and isinstance(assignment, Mapping) and assignment.get("kind") == "wrk.assignment":
                identity = tx.execute("SELECT current_revision,payload_json FROM identities WHERE authority=? AND kind=? AND id=?",
                    (assignment["authority"], assignment["kind"], assignment["id"])).fetchone()
                if identity and assignment.get("revision") == identity[0]:
                    assigned = json.loads(identity[1])
                    scope = assigned.get("scope")
                    for field in ("principal", "role"):
                        if field in assigned:
                            summary[side]["fields"][field] = assigned[field]
                            summary[side]["unknown"] = [k for k in summary[side]["unknown"] if k != field]
                    resolutions.append({"side": side, "assignment_ref": dict(assignment),
                        "coverage": "validated-exact-assignment-at-capture"})
                else:
                    resolutions.append({"side": side, "assignment_ref": dict(assignment),
                        "coverage": "unknown-exact-assignment-source-gap"})
            if isinstance(scope, ResourceRef):
                scope = scope.to_dict()
            if isinstance(scope, Mapping) and scope.get("kind") == "work.project":
                projects[(scope["authority"], scope["id"])] = scope
                continue
            if not (isinstance(scope, Mapping) and scope.get("kind") == "work.task"):
                continue
            identity = tx.execute("SELECT current_revision,payload_json FROM identities WHERE authority=? AND kind=? AND id=?",
                (scope["authority"], scope["kind"], scope["id"])).fetchone()
            task, provenance = None, "unknown-source-gap"
            if identity and (scope.get("revision") is None or scope.get("revision") == identity[0]):
                task, provenance = json.loads(identity[1]), "validated-exact-state-at-capture"
            elif scope.get("revision") is not None:
                historical = tx.execute("SELECT json_extract(effects_json,'$.history_summary.primary.after') FROM events "
                    "WHERE subject_authority=? AND subject_kind=? AND subject_id=? AND subject_revision=? "
                    "ORDER BY append_position DESC LIMIT 1",
                    (scope["authority"],scope["kind"],scope["id"],scope["revision"])).fetchone()
                if historical and historical[0]:
                    captured = json.loads(historical[0])
                    if captured.get("ref") == dict(scope):
                        task, provenance = captured["fields"], "retained-exact-revision-summary"
            resolutions.append({"side":side,"scope_ref":dict(scope),"coverage":provenance})
            if task:
                for field in ("project_ref", "parent"):
                    project = task.get(field)
                    if isinstance(project, Mapping) and project.get("kind") == "work.project":
                        projects[(project["authority"], project["id"])] = project
        summary["resolved_projects"] = [projects[k] for k in sorted(projects)]
        for side, payload in (("before", before_payload), ("after", after_payload)):
            fields = summary[side]["fields"]
            if payload and "native_result" in fields:
                claimed = payload.get("value", {}).get("project_ref")
                if isinstance(claimed, ResourceRef):
                    claimed = claimed.to_dict()
                if not isinstance(claimed, Mapping) or (claimed.get("authority"), claimed.get("id")) not in projects:
                    fields.pop("native_result")
                    summary[side]["unknown"] = sorted(set(summary[side]["unknown"]) | {"native_result"})
        summary["project_resolution"] = resolutions
        if len(_json({"schema": HISTORY_SCHEMA, "primary": summary, "facets": []}).encode()) > MAX_SUMMARY_BYTES:
            raise StoreError("individual typed history exceeds the inline bound")
        return summary

    def _capture_child(self, tx, event_id, before_ref, before_payload, after_ref, after_payload):
        if event_id not in tx._history:
            raise StoreError("child history requires a source event created in this transaction")
        summary = self._history_transition(tx, before_ref, before_payload,
            after_ref, after_payload, facet_type="project_sheet_batch_child" if after_ref.kind == "work.task" else "related_identity_change")
        parent = tx.execute("SELECT subject_authority,subject_kind,subject_id,subject_revision,event_type FROM events WHERE event_id=?",
                            (event_id,)).fetchone()
        if parent[4] == "work.project-sheet.applied" and parent[1] == "work.project":
            # Document revisions/associations have no intrinsic project field.
            # Their exact parent sheet establishes this source relation without
            # copying the sheet or inventing a child event.
            project = ResourceRef(*parent[:4]).to_dict()
            projects = {(p["authority"],p["id"]):p for p in summary["resolved_projects"]}
            projects[(project["authority"],project["id"])] = project
            summary["resolved_projects"] = [projects[k] for k in sorted(projects)]
            summary["parent_source_ref"] = project
        if len(_json(summary).encode()) > MAX_SUMMARY_BYTES:
            raise StoreError("individual child history exceeds the bounded summary contract")
        tx._history[event_id].append(summary)

    def _flush_history(self, tx):
        # Publication can append Evidence events to this transaction. Iterate
        # until those new source events are sealed as well, without recursion.
        sealed = set()
        while set(tx._history) - sealed:
            event_id = next(k for k in tx._history if k not in sealed)
            facets = tx._history[event_id]
            row = tx.execute("SELECT effects_json, after_refs_json FROM events WHERE event_id=?", (event_id,)).fetchone()
            effects = json.loads(row[0])
            history = effects["history_summary"]
            history["facets"] = facets
            if len(facets) > MAX_INLINE_FACETS or len(_json(history).encode()) > MAX_SUMMARY_BYTES:
                projects = project_relations(history["primary"])
                if self._history_publisher is None or len(projects) != 1:
                    raise StoreError("large history requires the admitted Evidence publisher and one exact project")
                manifest = self._history_publisher(event_id, tuple(facets), ResourceRef.from_dict(projects[0]))
                pinned = ResourceRef.from_dict(manifest["ref"])
                self._store_reference(tx, pinned)
                history["manifest"], history["facets"] = manifest, []
                refs = json.loads(row[1]) + [pinned.to_dict()]
                tx.execute("UPDATE events SET after_refs_json=? WHERE event_id=?", (_json(refs), event_id))
            if len(_json(history).encode()) > MAX_SUMMARY_BYTES:
                raise StoreError("history summary and manifest locator exceed the inline bound")
            tx.execute("UPDATE events SET effects_json=? WHERE event_id=?", (_json(effects), event_id))
            sealed.add(event_id)

    def append_event(
        self,
        event: EventEnvelope,
        *,
        transaction_id: Optional[str] = None,
        transaction: Optional[Transaction] = None,
    ) -> EventEnvelope:
        """Append one already-formed event, idempotently by event identity."""
        if not isinstance(event, EventEnvelope):
            raise TypeError("event must be an EventEnvelope")
        if event.store_authority != self.authority:
            raise TargetMismatchError("event authority does not belong to this store")
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._append_event(owned, event, transaction_id)
        return self._append_event(tx, event, transaction_id)

    def _append_event(self, tx: Transaction, event: EventEnvelope, transaction_id: Optional[str]) -> EventEnvelope:
        with tx.savepoint():
            existing = tx.execute("SELECT * FROM events WHERE event_id = ?", (event.event_id,)).fetchone()
            if existing is not None:
                prior = self._event_from_row(existing)
                if prior != event:
                    raise StoreError("event identity was reused with different content")
                return prior
            if "history_summary" in event.effects:
                raise StoreError("imported events cannot claim writer-validated historical state")
            identity = tx.execute(
                "SELECT 1 FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (event.subject.authority, event.subject.kind, event.subject.id),
            ).fetchone()
            if identity is None:
                raise TargetMismatchError("event subject identity is not admitted")
            expected = tx.execute(
                "SELECT next_sequence FROM event_sequences WHERE store_authority = ? AND stream = ?",
                (self.authority, event.stream),
            ).fetchone()
            if expected is not None and event.sequence != expected[0]:
                raise StoreError("event sequence is not the next durable sequence")
            if expected is None and event.sequence != 1:
                raise StoreError("first event sequence must be one")
            for ref in event.before_refs + event.after_refs:
                self._store_reference(tx, ref)
            if expected is None:
                tx.execute("INSERT INTO event_sequences(store_authority, stream, next_sequence) VALUES (?, ?, ?)", (self.authority, event.stream, 2))
            else:
                tx.execute("UPDATE event_sequences SET next_sequence = ? WHERE store_authority = ? AND stream = ?", (event.sequence + 1, self.authority, event.stream))
            tx.execute(
                "INSERT INTO events(append_position, event_id, store_authority, stream, subject_authority, subject_kind, subject_id, subject_revision, schema_revision, event_type, sequence, actor_authority, actor_id, credential_ref, correlation_id, causation_id, operation, recorded_at, occurred_at, before_refs_json, after_refs_json, effects_json, transaction_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._next_append(tx), event.event_id, event.store_authority, event.stream, event.subject.authority, event.subject.kind,
                    event.subject.id, event.subject.revision, event.schema_revision, event.event_type, event.sequence,
                    event.actor.authority, event.actor.actor, event.actor.credential_ref, event.correlation_id,
                    event.causation_id, event.operation, event.recorded_at, event.occurred_at,
                    _json([ref.to_dict() for ref in event.before_refs]), _json([ref.to_dict() for ref in event.after_refs]),
                    _json(event.effects), transaction_id or "external-" + event.event_id,
                ),
            )
            self._schedule_history_projection(tx)
            return event

    def list_event_subjects(self, *, stream: str) -> Tuple[ResourceRef, ...]:
        """Read exact stream subjects without fetching retained event bodies.

        Order and historical revisions match list_events(stream=...). This
        selects append metadata only; callers must still validate current
        identity payloads and their authorized relationships.
        """
        if not isinstance(stream, str) or not stream.strip():
            raise ValueError("event subject selection requires an exact stream")
        with self._transaction_lock:
            self._require_open()
            rows = self._connection.execute(
                "SELECT subject_authority, subject_kind, subject_id, subject_revision "
                "FROM events WHERE store_authority = ? AND stream = ? ORDER BY sequence",
                (self.authority, stream)).fetchall()
            return tuple(ResourceRef(*row) for row in rows)

    def list_events(self, *, stream: Optional[str] = None,
                    subjects: Optional[Sequence[ResourceRef]] = None,
                    subject_kinds: Optional[Sequence[str]] = None,
                    assessment_parent: Optional[ResourceRef] = None) -> Tuple[EventEnvelope, ...]:
        """Read existing events, with optional owner predicates before hydration.

        Assessment history follows its persisted declaration/parent links,
        including historical scope events when a current record is missing.
        Subject kinds retain cross-stream attribution while excluding unrelated
        payloads. These predicates narrow an existing reader; they issue no read grant.
        """
        clauses, args = [], []
        if stream is not None:
            clauses.extend(["e.store_authority = ?", "e.stream = ?"])
            args.extend([self.authority, stream])
        if subjects is not None:
            subjects = tuple(subjects)
            if not all(isinstance(ref, ResourceRef) and ref.authority == self.authority for ref in subjects):
                raise ValueError("event subjects must be local typed references")
            if not subjects:
                return ()
            if len(subjects) == 1:
                # The persisted subject columns already have an identity index.
                # A correlated JSON predicate instead scans all event rows.
                clauses.extend(["e.subject_authority = ?", "e.subject_kind = ?", "e.subject_id = ?"])
                args.extend([subjects[0].authority, subjects[0].kind, subjects[0].id])
            else:
                # Keep wanted identities outermost so each performs an indexed
                # lookup. IN deduplicates repeated subjects; the final ordering
                # and revision-independent identity semantics remain unchanged.
                clauses.append("e.rowid IN (SELECT matched.rowid FROM json_each(?) wanted "
                    "CROSS JOIN events matched WHERE "
                    "matched.subject_authority = json_extract(wanted.value, '$.authority') AND "
                    "matched.subject_kind = json_extract(wanted.value, '$.kind') AND "
                    "matched.subject_id = json_extract(wanted.value, '$.id'))")
                args.append(_json([ref.to_dict() for ref in subjects]))
        if subject_kinds is not None:
            if isinstance(subject_kinds, (str, bytes)):
                raise ValueError("event subject kinds must be a sequence of nonempty kind names")
            subject_kinds = tuple(subject_kinds)
            if not all(isinstance(kind, str) and kind.strip() for kind in subject_kinds):
                raise ValueError("event subject kinds must be nonempty kind names")
            if not subject_kinds:
                return ()
            clauses.extend(["e.store_authority = ?",
                "e.subject_kind IN (SELECT value FROM json_each(?))"])
            args.extend([self.authority, _json(subject_kinds)])
        if assessment_parent is not None:
            if (not isinstance(assessment_parent, ResourceRef)
                    or assessment_parent.authority != self.authority or stream != "assessment"):
                raise ValueError("assessment history requires a local parent and assessment stream")
            # Match the assessment protocol's parent slot, never arbitrary
            # evidence/candidate refs that happen to mention the selected task.
            parent_slot = ("CASE WHEN e.event_type = 'assessment.scope.declared' "
                "AND e.subject_kind = 'assessment.scope' THEN '$[0]' "
                "WHEN e.event_type = 'assessment.completed' AND e.subject_kind = 'assessment.result' THEN '$[1]' "
                "WHEN e.event_type = 'assessment.unknown.disposed' AND e.subject_kind = 'assessment.decision' THEN '$[1]' "
                "WHEN e.event_type = 'assessment.accepted' AND e.subject_kind = 'assessment.decision' "
                "THEN CASE WHEN json_extract(e.effects_json, '$.no_review') = 1 THEN '$[0]' ELSE '$[1]' END END")
            parent_link = "json_extract(e.before_refs_json, " + parent_slot + ")"
            clauses.append("((json_extract(" + parent_link + ", '$.authority') = ? AND "
                "json_extract(" + parent_link + ", '$.kind') = ? AND json_extract(" + parent_link + ", '$.id') = ?) "
                "OR (e.event_type = 'assessment.candidate.selected' AND e.subject_kind = 'assessment.selection' "
                "AND EXISTS (SELECT 1 FROM events scope WHERE scope.store_authority = ? "
                "AND scope.stream = 'assessment' AND scope.event_type = 'assessment.scope.declared' "
                "AND scope.subject_kind = 'assessment.scope' "
                "AND json_extract(scope.before_refs_json, '$[0].authority') = ? "
                "AND json_extract(scope.before_refs_json, '$[0].kind') = ? "
                "AND json_extract(scope.before_refs_json, '$[0].id') = ? "
                "AND json_extract(e.before_refs_json, '$[0].authority') = scope.subject_authority "
                "AND json_extract(e.before_refs_json, '$[0].kind') = scope.subject_kind "
                "AND json_extract(e.before_refs_json, '$[0].id') = scope.subject_id)))")
            args.extend([assessment_parent.authority, assessment_parent.kind, assessment_parent.id,
                         self.authority, assessment_parent.authority, assessment_parent.kind, assessment_parent.id])
        with self._transaction_lock:
            self._require_open()
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = self._connection.execute("SELECT e.* FROM events e" + where
                + " ORDER BY e.store_authority, e.stream, e.sequence", args).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def _event_from_row(self, row: sqlite3.Row) -> EventEnvelope:
        subject = ResourceRef(row["subject_authority"], row["subject_kind"], row["subject_id"], row["subject_revision"])
        actor = AuthenticatedActor(row["actor_authority"], row["actor_id"], row["credential_ref"])
        return EventEnvelope(
            row["event_id"], row["store_authority"], row["stream"], subject, row["schema_revision"], row["event_type"], row["sequence"], actor,
            row["operation"], row["correlation_id"], row["causation_id"], row["recorded_at"], row["occurred_at"],
            tuple(ResourceRef.from_dict(ref) for ref in json.loads(row["before_refs_json"])),
            tuple(ResourceRef.from_dict(ref) for ref in json.loads(row["after_refs_json"])), json.loads(row["effects_json"]),
        )


def coerce_operation_owner(value: Any) -> OperationOwnerCapability:
    """Convert only an admitted Store, Runtime owner, or issued capability.

    The compatibility conversion is centralized at the trusted bootstrap
    boundary. Operation engines retain the resulting capability, never the
    supplied Store/handler or an arbitrary duck-typed writer.
    """
    if isinstance(value, OperationOwnerCapability):
        return value
    if isinstance(value, Store):
        return value.issue_operation_owner()
    if isinstance(value, RuntimeOperationOwner):
        return OperationOwnerCapability.issue_runtime(value)
    raise StoreAdmissionError("operation commands require an admitted Store or RuntimeOperationOwner")


def issue_operation_owner(owner: Any) -> OperationOwnerCapability:
    """Issue one operation capability at trusted Runtime composition.

    ``owner`` may be the already-open Runtime owner implementing the nominal
    ``RuntimeOperationOwner`` bridge.  This function never opens a Store or
    creates a second connection; it is deliberately separate from the
    serialized consumer facade.
    """
    return coerce_operation_owner(owner)


class DomainHandler:
    """Sealed trusted-domain writer; the command actor remains provenance."""

    __slots__ = ("_owner", "_descriptors")

    def __init__(self, owner: Store, descriptors: Sequence[DomainContribution], *, _construction_token: object = None) -> None:
        if _construction_token is not _HANDLER_CONSTRUCTION_TOKEN or not isinstance(owner, Store):
            raise StoreAdmissionError("domain handlers are issued only by an admitted Store")
        self._owner = owner
        self._descriptors = tuple(descriptors)

    @property
    def authority(self) -> str:
        return self._owner.authority

    @property
    def domain_ids(self) -> Tuple[str, ...]:
        return tuple(item.domain_id for item in self._descriptors)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._owner.connection

    def read_transaction(self):
        return self._owner.read_transaction()

    def transaction(self) -> Any:
        return self._owner.transaction()

    def mutate(self, envelope: CommandEnvelope, *, identity_payload: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> CommandReceipt:
        return self._owner.mutate(envelope, _handler=self, _identity_payload=identity_payload, **kwargs)

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self._owner.get_identity(ref)

    def find_identity_refs(self, *, kind: str, payload_matches: Mapping[Tuple[str, ...], str]) -> Tuple[ResourceRef, ...]:
        return self._owner.find_identity_refs(kind=kind, payload_matches=payload_matches)

    def get_record(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self._owner.get_record(ref)

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]:
        return self._owner.get_reference(ref)

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        return self._owner.get_receipt(logical_request_key)

    def list_event_subjects(self, *, stream: str) -> Tuple[ResourceRef, ...]:
        return self._owner.list_event_subjects(stream=stream)

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        return self._owner.registered_domains()

    def list_events(self, *, stream: Optional[str] = None,
                    subjects: Optional[Sequence[ResourceRef]] = None,
                    subject_kinds: Optional[Sequence[str]] = None,
                    assessment_parent: Optional[ResourceRef] = None) -> Tuple[EventEnvelope, ...]:
        kwargs = {"stream": stream}
        if subjects is not None:
            kwargs["subjects"] = subjects
        if subject_kinds is not None:
            kwargs["subject_kinds"] = subject_kinds
        if assessment_parent is not None:
            kwargs["assessment_parent"] = assessment_parent
        return self._owner.list_events(**kwargs)

    def put_identity(self, *args: Any, **kwargs: Any) -> IdentityRecord:
        return self._owner.put_identity(*args, **kwargs)

    def revise_identity(self, *args: Any, **kwargs: Any) -> IdentityRecord:
        return self._owner.revise_identity(*args, **kwargs)

    def put_reference(self, *args: Any, **kwargs: Any) -> ResourceRef:
        return self._owner.put_reference(*args, **kwargs)

    def defer_after_commit(self, callback):
        self._owner.defer_after_commit(callback)

    def consumer(self) -> "ConsumerStore":
        return self._owner.consumer()

    def issue_command_port(
        self,
        engine: Any,
        domain_id: str,
        endpoints: Sequence[str],
        *,
        reader: Optional["ConsumerStore"] = None,
    ) -> DomainCommandPort:
        if self not in self._owner._issued_handlers:
            raise StoreAdmissionError("domain handler is not an issued owner capability")
        return self._owner.issue_command_port(engine, domain_id, endpoints, reader=reader)


class ConsumerStore:
    """Concrete read-only Store view safe to give to an ordinary consumer.

    The wrapper intentionally does not proxy unknown attributes.  In
    particular it has no ``connection``, ``transaction``, ``put_identity``,
    ``revise_identity``, ``append_event``, ``mutate``, or domain-registration
    surface.
    """

    __slots__ = ("__owner",)

    def __init__(self, owner: Store) -> None:
        if not isinstance(owner, Store):
            raise TypeError("ConsumerStore requires the sealed Store owner capability")
        self.__owner = owner

    @property
    def authority(self) -> str:
        return self.__owner.authority

    @property
    def domain_descriptor_digest(self) -> str:
        return self.__owner.domain_descriptor_digest

    def foreign_keys_enabled(self) -> bool:
        return self.__owner.foreign_keys_enabled()

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.__owner.get_identity(ref)

    def get_identity_bounded(self, ref: ResourceRef, *, max_record_bytes: int = 65536) -> Mapping[str, Any]:
        return self.__owner.get_identity_bounded(ref, max_record_bytes=max_record_bytes)

    def get_identity_ref(self, ref: ResourceRef) -> Optional[ResourceRef]:
        return self.__owner.get_identity_ref(ref)

    def read_identity_page(self, *, kind: str, after: str = "", limit: int = 50,
                           max_record_bytes: int = 65536,
                           payload_matches: Optional[Mapping[Tuple[str, ...], str]] = None) -> Mapping[str, Any]:
        return self.__owner.read_identity_page(kind=kind, after=after, limit=limit,
            max_record_bytes=max_record_bytes, payload_matches=payload_matches)

    def find_identity_refs(self, *, kind: str, payload_matches: Mapping[Tuple[str, ...], str]) -> Tuple[ResourceRef, ...]:
        return self.__owner.find_identity_refs(kind=kind, payload_matches=payload_matches)

    def project_identity_fields(self, **options: Any) -> Tuple[Mapping[str, Any], ...]:
        return self.__owner.project_identity_fields(**options)

    def project_identity_fields_for_refs(self, refs: Sequence[ResourceRef], **options: Any) -> Tuple[Mapping[str, Any], ...]:
        return self.__owner.project_identity_fields_for_refs(refs, **options)

    def get_record(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.__owner.get_record(ref)

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        return self.__owner.registered_domains()

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]:
        return self.__owner.get_reference(ref)

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        return self.__owner.get_receipt(logical_request_key)

    def list_event_subjects(self, *, stream: str) -> Tuple[ResourceRef, ...]:
        return self.__owner.list_event_subjects(stream=stream)

    def list_events(self, *, stream: Optional[str] = None,
                    subjects: Optional[Sequence[ResourceRef]] = None,
                    subject_kinds: Optional[Sequence[str]] = None,
                    assessment_parent: Optional[ResourceRef] = None) -> Tuple[EventEnvelope, ...]:
        kwargs = {"stream": stream}
        if subjects is not None:
            kwargs["subjects"] = subjects
        if subject_kinds is not None:
            kwargs["subject_kinds"] = subject_kinds
        if assessment_parent is not None:
            kwargs["assessment_parent"] = assessment_parent
        return self.__owner.list_events(**kwargs)

    def project_history_reader(self, *, grant=None, grant_reader=None, evidence_reader=None):
        """Return the bounded D03 reader without exposing the owner SQL port."""
        return self.__owner.project_history_reader(grant=grant, grant_reader=grant_reader,
                                                   evidence_reader=evidence_reader)

    def project_history_status(self) -> Mapping[str, Any]:
        return self.__owner.project_history_projection().status()

    def _project_history_owner(self):
        """Private composition bridge used by the typed reader constructor."""
        return self.__owner

    def snapshot_counts(self) -> Mapping[str, int]:
        """Return fresh durable counts without exposing a SQL execution port."""
        owner = self.__owner
        with owner._transaction_lock:
            owner._require_open()
            tables = ("identities", "record_references", "events", "command_receipts", "event_sequences")
            return {
                table: int(owner._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
                for table in tables
            }


class ReadOnlyStore(ConsumerStore):
    """A closable inspection handle; no writer, SQL or command composition."""
    __slots__ = ("__close_owner",)

    def __init__(self, owner):
        super().__init__(owner)
        self.__close_owner = owner

    def close(self):
        self.__close_owner.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


SQLiteStore = Store
RealmStore = Store


__all__ = [
    "Store", "SQLiteStore", "RealmStore", "ConsumerStore", "DomainHandler", "DomainCommandPort",
    "RuntimeOperationOwner", "RuntimeOperationReader", "RuntimeDomainOwner", "DomainOwnerCapability",
    "OperationOwnerCapability",
    "coerce_operation_owner", "issue_operation_owner",
    "Transaction", "IdentityRecord", "command_facade",
    "StoreError", "StoreAdmissionError", "StoreExistsError", "SchemaMismatchError", "MigrationRequiredError", "ReadOnlyStore",
    "CompositionMismatchError", "WriterBusyError", "ClosedStoreError",
    "TargetMismatchError", "VersionConflictError", "DescriptorDigestMismatchError",
    "DescriptorExpectationMismatchError", "MutationAdmissionError",
    "FND02_CONTRACT_REVISION", "FND02_CONTRACT_DIGEST", "DOMAIN_KIND",
    "DOMAIN_DESCRIPTOR_DIGEST_KEY", "EMPTY_DOMAIN_DESCRIPTOR_DIGEST",
]
