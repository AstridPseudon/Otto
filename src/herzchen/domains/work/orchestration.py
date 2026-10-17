"""Bounded owner-side orchestration placement over the WRK transaction.

This module adds one finite placement boundary.  It deliberately composes the
existing assignment and project-batch engines on the same owner transaction;
it does not expose a Store, SQL, a generic transaction API, a scheduler, or a
second relationship ledger to consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence, Tuple

from herzchen.command_ports import command_facade
from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
    validate_replay,
)

from .assignments import AssignmentStatus, ResponsibilityAssignment, _ResponsibilityAssignmentsEngine
from .batches import BatchResult, _ProjectBatchesEngine
from .model import Lifecycle, WorkNotFoundError, WorkValidationError
from .module import KIND_PREFIX, SCHEMA_REVISION, work_handler


ORCHESTRATION_SCHEMA_REVISION = "work.orchestration.v1"
ORCHESTRATION_DOMAIN_ID = "herzchen.work.orchestration"
DEFAULT_KIND = "wrk.orchestrator-default"
PORTFOLIO_KIND = "wrk.portfolio"
SUPERVISION_KEY = "otto_orchestrator"
PLACEMENT_EVENT = "work.project.supervised-created"
DEFAULT_CREATED_EVENT = "work.orchestrator-default.created"
DEFAULT_CHANGED_EVENT = "work.orchestrator-default.changed"
TRANSFER_EVENT = "work.project.supervision-transferred"
ATTACH_EVENT = "work.project.supervision-attached"
_RETIRED = frozenset({"retired", "stopped", "cancelled", "completed"})


def _safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise WorkValidationError(f"{field} must be a non-blank opaque identifier")
    return value


def _revision(value: Any, field: str) -> str:
    return _opaque(value, field)


def _revision_version(value: Optional[str]) -> int:
    if not isinstance(value, str) or not value.startswith("rev-"):
        return 0
    try:
        return int(value[4:])
    except ValueError:
        return 0


def _current_revision(record: Any) -> str:
    ref = getattr(record, "ref", None)
    revision = getattr(ref, "revision", None)
    return revision if isinstance(revision, str) and revision else "rev-" + str(getattr(record, "version", 0))


def _same_identity(left: Any, right: Any) -> bool:
    return (
        getattr(left, "authority", None), getattr(left, "kind", None), getattr(left, "id", None)
    ) == (
        getattr(right, "authority", None), getattr(right, "kind", None), getattr(right, "id", None)
    )


def _ref(value: Any, *, authority: str, kind: str, field: str, revision: Optional[str] = None) -> ResourceRef:
    if isinstance(value, ResourceRef):
        result = value
    elif isinstance(value, Mapping):
        try:
            result = ResourceRef.from_dict(value)
        except (TypeError, ValueError, KeyError) as exc:
            raise WorkValidationError(f"{field} is malformed") from exc
    else:
        raise WorkValidationError(f"{field} must be a typed reference")
    if result.authority != authority or result.kind != kind or not isinstance(result.id, str) or not result.id.strip():
        raise WorkValidationError(f"{field} has the wrong authority, kind, or id")
    if revision is not None and result.revision != revision:
        raise WorkValidationError(f"{field} revision is stale")
    return result


def _maybe_ref(value: Any, *, authority: str, kind: str, field: str) -> Optional[ResourceRef]:
    if value is None:
        return None
    return _ref(value, authority=authority, kind=kind, field=field)


def _assignment_status(assignment: ResponsibilityAssignment) -> str:
    status = assignment.status
    return str(getattr(status, "value", status)).strip().lower()


def contribution() -> DomainContribution:
    return DomainContribution(
        ORCHESTRATION_DOMAIN_ID,
        "1.0",
        "wrk",
        (DEFAULT_KIND,),
        (),
        ("work.orchestration",),
        (
            "work.create_pending_with_supervisor",
            "work.orchestrator-default.set",
            "work.project.supervision.transfer",
            "work.project.supervision.attach",
        ),
        (PLACEMENT_EVENT, DEFAULT_CREATED_EVENT, DEFAULT_CHANGED_EVENT, TRANSFER_EVENT, ATTACH_EVENT),
        ORCHESTRATION_SCHEMA_REVISION,
        (
            "fnd-03.identities",
            "fnd-03.record_references",
            "fnd-03.transaction",
            "handler-required",
            "mutation-resource:" + DEFAULT_KIND,
            "mutation-resource:work.project",
            "mutation-port:{}|work.create_pending_with_supervisor|work.project|{}".format(ORCHESTRATION_SCHEMA_REVISION, PLACEMENT_EVENT),
            "mutation-port:{}|work.orchestrator-default.set|{}|{}".format(ORCHESTRATION_SCHEMA_REVISION, DEFAULT_KIND, DEFAULT_CREATED_EVENT),
            "mutation-port:{}|work.orchestrator-default.set|{}|{}".format(ORCHESTRATION_SCHEMA_REVISION, DEFAULT_KIND, DEFAULT_CHANGED_EVENT),
            "mutation-port:{}|work.project.supervision.transfer|work.project|{}".format(ORCHESTRATION_SCHEMA_REVISION, TRANSFER_EVENT),
            "mutation-port:{}|work.project.supervision.attach|work.project|{}".format(ORCHESTRATION_SCHEMA_REVISION, ATTACH_EVENT),
        ),
    )


@dataclass(frozen=True)
class PlacementResult:
    project: Any
    receipt: Any
    default_ref: ResourceRef
    assignment: ResponsibilityAssignment
    relation: Mapping[str, Any]
    project_receipt: Any


class _OrchestrationEngine:
    """Finite owner engine; all writes use the existing WRK/FND writer."""

    def __init__(
        self,
        store: Any,
        *,
        actor: Optional[AuthenticatedActor] = None,
        operator_actor: Optional[AuthenticatedActor] = None,
        portfolio_ref: Any,
        main_assignment_ref: Any = None,
        allowed_creator_ids: Sequence[str] = (),
        privileged_actor_ids: Sequence[str] = (),
        expected_main_principal: Optional[str] = None,
    ) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("owner actor must be an AuthenticatedActor")
        if operator_actor is not None and (not isinstance(operator_actor, AuthenticatedActor)
                                           or operator_actor.authority != actor.authority
                                           or not operator_actor.authenticated):
            raise WorkValidationError("operator actor must be authenticated by this owner")
        self._writer = work_handler(store)
        self.reader = self._writer.consumer()
        self.default_actor = actor
        self.operator_actor = operator_actor
        self.portfolio_ref = _ref(portfolio_ref, authority=self._writer.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        self.main_assignment_ref = _maybe_ref(main_assignment_ref, authority=self._writer.authority, kind="wrk.assignment", field="main_assignment_ref")
        creators = tuple(_opaque(value, "allowed_creator_id") for value in allowed_creator_ids)
        privileged = tuple(_opaque(value, "privileged_actor_id") for value in privileged_actor_ids)
        self.allowed_creator_ids = tuple(dict.fromkeys((actor.actor,) + creators))
        self.privileged_actor_ids = tuple(dict.fromkeys((actor.actor,) + privileged))
        self.expected_main_principal = None if expected_main_principal is None else _opaque(expected_main_principal, "expected_main_principal")
        # These are owner-local engines, not consumer ports.  Their nested
        # transaction contexts become savepoints of this engine's transaction.
        self.assignments = _ResponsibilityAssignmentsEngine(store, actor=actor)
        self.batches = _ProjectBatchesEngine(store, actor=actor)

    @property
    def authority(self) -> str:
        return self._writer.authority

    def _actor(self, value: Any, *, privileged: bool = False) -> AuthenticatedActor:
        if not isinstance(value, AuthenticatedActor):
            raise WorkValidationError("actor must be an authenticated owner actor")
        if value.authority != self.authority or not value.authenticated:
            raise WorkValidationError("actor is not authenticated by this owner")
        allowed = self.privileged_actor_ids if privileged else self.allowed_creator_ids
        if value.actor not in allowed:
            raise WorkValidationError("actor is not authorized for this portfolio")
        return value

    def _default_ref(self) -> ResourceRef:
        ident = "default-" + hashlib.sha256(canonical_json(self.portfolio_ref.to_dict()).encode("utf-8")).hexdigest()[:28]
        return ResourceRef(self.authority, DEFAULT_KIND, ident)

    def _project_ref(self, request_key: str) -> ResourceRef:
        ident = "project-" + hashlib.sha256((self.authority + ":" + request_key).encode("utf-8")).hexdigest()[:28]
        return ResourceRef(self.authority, KIND_PREFIX[next(kind for kind in KIND_PREFIX if kind.value == "project")], ident)

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], request_key: str, actor: AuthenticatedActor, *, expected_version: Optional[int] = None, expected_revision: Optional[str] = None) -> CommandEnvelope:
        context = TransactionContext(actor, request_key, "0" * 64, expected_revision=expected_revision, expected_version=expected_version)
        digest = canonical_request_digest(
            logical_request_key=request_key,
            operation=operation,
            schema_revision=ORCHESTRATION_SCHEMA_REVISION,
            target=target,
            actor=actor,
            payload=payload,
            context=context,
        )
        return CommandEnvelope(
            operation,
            ORCHESTRATION_SCHEMA_REVISION,
            target,
            replace(context, request_digest=digest),
            dict(payload),
        )

    def _lookup_replay(self, envelope: CommandEnvelope) -> Any:
        """Use the existing WRK receipt read and kernel replay validator."""
        prior = self._writer.get_receipt(envelope.context.logical_request_key)
        if prior is not None:
            validate_replay(prior, envelope)
        return prior

    def _assignment(self, target: ResourceRef, *, expected_revision: Optional[str], expected_generation: Optional[int], field: str) -> ResponsibilityAssignment:
        assignment = self.assignments.get(target)
        if assignment.ref.authority != self.authority or assignment.ref.kind != "wrk.assignment" or assignment.ref.id != target.id:
            raise WorkValidationError(f"{field} identity is not owned by this portfolio")
        scope = assignment.scope
        if not _same_identity(scope, self.portfolio_ref):
            raise WorkValidationError(f"{field} is outside the exact portfolio scope")
        if assignment.role != "orchestrator":
            raise WorkValidationError(f"{field} is not an orchestrator assignment")
        if _assignment_status(assignment) in _RETIRED:
            raise WorkValidationError(f"{field} is retired")
        current_revision = _current_revision(assignment)
        if expected_revision is not None and expected_revision != current_revision:
            raise WorkValidationError(f"{field} revision is stale")
        if expected_generation is not None and int(expected_generation) != int(assignment.generation):
            raise WorkValidationError(f"{field} generation is stale")
        return assignment

    def _project_assignment(self, target: ResourceRef, *, expected_revision: str, expected_generation: int, field: str) -> ResponsibilityAssignment:
        """Read and fence an existing project-scoped assignment."""
        assignment = self.assignments.get(target)
        if assignment.ref.authority != self.authority or assignment.ref.kind != "wrk.assignment" or assignment.ref.id != target.id:
            raise WorkValidationError(f"{field} identity is not owned by this portfolio")
        if _current_revision(assignment) != expected_revision:
            raise WorkValidationError(f"{field} revision is stale")
        if int(assignment.generation) != int(expected_generation):
            raise WorkValidationError(f"{field} generation is stale")
        if _assignment_status(assignment) in _RETIRED:
            raise WorkValidationError(f"{field} is retired")
        return assignment

    def _validate_caller_assignment(self, actor: AuthenticatedActor, ref: Any, revision: Any, generation: Any) -> None:
        if ref is None:
            if revision is not None or generation is not None:
                raise WorkValidationError("caller assignment pins require a caller assignment")
            return
        caller_ref = _ref(ref, authority=self.authority, kind="wrk.assignment", field="caller_assignment_ref")
        if revision is None or generation is None:
            raise WorkValidationError("caller assignment requires revision and generation pins")
        assignment = self._assignment(caller_ref, expected_revision=_revision(revision, "caller_assignment_revision"), expected_generation=int(generation), field="caller_assignment_ref")
        if assignment.principal != actor.actor:
            raise WorkValidationError("caller assignment principal does not authenticate this actor")

    def _pending_unassigned(self, record: Any, *, field: str) -> None:
        """Permit inert existing queue projects without manufacturing a manager."""
        if (record.payload.get("lifecycle") != Lifecycle.PENDING.value
                or any(record.payload.get(key) is not None for key in ("manager", "worker", "execution", "budget"))):
            raise WorkValidationError(f"{field} missing assignment requires an inert pending project")
        finder = getattr(self._writer, "find_identity_refs", None)
        if not callable(finder):
            raise WorkValidationError(f"{field} owner cannot verify absent project assignment")
        refs = finder(kind="wrk.assignment", payload_matches={
            ("scope", "authority"): record.ref.authority,
            ("scope", "kind"): record.ref.kind,
            ("scope", "id"): record.ref.id,
        })
        if any(_assignment_status(self.assignments.get(ref)) not in _RETIRED for ref in refs):
            raise WorkValidationError(f"{field} current project assignment requires exact pins")

    def _relation(self, *, default_ref: ResourceRef, assignment: ResponsibilityAssignment,
                  project_ref: ResourceRef, request_key: str, default_revision: Optional[str] = None) -> dict[str, Any]:
        observed_default = self._writer.get_identity(default_ref)
        resolved_default_revision = default_revision or _current_revision(observed_default)
        return {
            "schema": "otto.orchestrator.supervision.v2",
            "portfolio_ref": self.portfolio_ref.to_dict(),
            # Keep the project join explicit.  The relation is stored inside
            # the project record, but the pin makes selected-project reads
            # fail closed if a relation is copied or attached elsewhere.
            # New projects are materialized at rev-1; transfers retain the
            # current pinned revision supplied by their caller.
            "project_ref": ResourceRef(
                self.authority, "work.project", project_ref.id,
                project_ref.revision or "rev-1",
            ).to_dict(),
            "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(),
            "assignment_revision": _current_revision(assignment),
            "generation": int(assignment.generation),
            "default_ref": ResourceRef(self.authority, DEFAULT_KIND, default_ref.id, resolved_default_revision).to_dict(),
            "default_revision": resolved_default_revision,
            "request_id": request_key,
        }

    def _pointer_payload(self, assignment: ResponsibilityAssignment, *, validate_main_binding: bool = False) -> dict[str, Any]:
        if validate_main_binding and self.expected_main_principal is not None and assignment.principal != self.expected_main_principal:
            raise WorkValidationError("supplied main assignment is not the trusted owner binding")
        return {
            "record_type": "work.orchestrator-default",
            "schema_revision": ORCHESTRATION_SCHEMA_REVISION,
            "portfolio_ref": self.portfolio_ref.to_dict(),
            "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id).to_dict(),
            "assignment_role": assignment.role,
            "assignment_revision": _current_revision(assignment),
            "generation": int(assignment.generation),
        }

    def _resolve_default(self, *, tx: Any, actor: AuthenticatedActor, supplied_ref: Optional[ResourceRef], supplied_revision: Optional[str], supplied_generation: Optional[int], expected_default_revision: Optional[str]) -> tuple[ResourceRef, ResponsibilityAssignment, str]:
        pointer_ref = self._default_ref()
        identity = self._writer.get_identity(pointer_ref)
        if identity is None:
            target = supplied_ref or self.main_assignment_ref
            if target is None:
                raise WorkValidationError("portfolio has no trusted main assignment seed")
            assignment = self._assignment(target, expected_revision=supplied_revision, expected_generation=supplied_generation, field="assignment_ref")
            if expected_default_revision not in (None, "initial"):
                raise WorkValidationError("default pointer is absent but expected_default_revision is not initial")
            self._writer.mutate(
                self._envelope("work.orchestrator-default.set", pointer_ref, self._pointer_payload(assignment, validate_main_binding=True), "default:" + pointer_ref.id, actor, expected_version=0),
                identity_payload=self._pointer_payload(assignment, validate_main_binding=True),
                event_type=DEFAULT_CREATED_EVENT,
                result_ref=ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, "rev-1"),
                after_refs=(assignment.ref,),
                effects={"portfolio_ref": self.portfolio_ref.to_dict(), "assignment_ref": assignment.ref.to_dict()},
                stream="orchestrator-default:" + pointer_ref.id,
                transaction=tx,
            )
            return pointer_ref, assignment, "rev-1"
        pointer_revision = _current_revision(identity)
        if expected_default_revision is not None and expected_default_revision != pointer_revision:
            raise WorkValidationError("default pointer revision is stale")
        payload = identity.payload
        stored_portfolio = _ref(payload.get("portfolio_ref"), authority=self.authority, kind=PORTFOLIO_KIND, field="stored portfolio_ref")
        stored_assignment = _ref(payload.get("assignment_ref"), authority=self.authority, kind="wrk.assignment", field="stored assignment_ref")
        if not _same_identity(stored_portfolio, self.portfolio_ref):
            raise WorkValidationError("default pointer portfolio scope is foreign")
        if supplied_ref is not None and not _same_identity(supplied_ref, stored_assignment):
            raise WorkValidationError("supplied assignment is not the current default")
        assignment = self._assignment(stored_assignment, expected_revision=supplied_revision, expected_generation=supplied_generation, field="default assignment")
        return pointer_ref, assignment, pointer_revision

    def create_pending_with_supervisor(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        title: Optional[str] = None,
        outcome: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
        sheet: Optional[Mapping[str, Any]] = None,
        assignment_ref: Any = None,
        assignment_revision: Optional[str] = None,
        assignment_generation: Optional[int] = None,
        caller_assignment_ref: Any = None,
        caller_assignment_revision: Optional[str] = None,
        caller_assignment_generation: Optional[int] = None,
        expected_default_revision: Optional[str] = None,
        expected_project_version: int = 0,
    ) -> Mapping[str, Any]:
        actor_value = self._actor(actor)
        operator_value = self.operator_actor
        if operator_value is None:
            raise WorkValidationError("authenticated operator identity is required to create a project")
        request_key = _opaque(request_id, "request_id")
        supplied_portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        if not _same_identity(supplied_portfolio, self.portfolio_ref):
            raise WorkValidationError("portfolio_ref does not match the trusted owner binding")
        if not isinstance(expected_project_version, int) or isinstance(expected_project_version, bool) or expected_project_version != 0:
            raise WorkValidationError("new supervised project requires expected_project_version=0")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise WorkValidationError("metadata must be a mapping")
        if isinstance(metadata, Mapping) and SUPERVISION_KEY in metadata:
            raise WorkValidationError("reserved supervision metadata is owner-controlled")
        if sheet is not None and not isinstance(sheet, Mapping):
            raise WorkValidationError("sheet must be a mapping")
        caller_ref = None if caller_assignment_ref is None else _ref(caller_assignment_ref, authority=self.authority, kind="wrk.assignment", field="caller_assignment_ref")
        target_ref = None if assignment_ref is None else _ref(assignment_ref, authority=self.authority, kind="wrk.assignment", field="assignment_ref")
        payload = {
            "portfolio_ref": supplied_portfolio.to_dict(),
            "title": title,
            "outcome": outcome,
            "metadata": _safe(metadata or {}),
            "sheet": _safe(sheet),
            "assignment_ref": None if target_ref is None else target_ref.to_dict(),
            "assignment_revision": assignment_revision,
            "assignment_generation": assignment_generation,
            "caller_assignment_ref": None if caller_ref is None else caller_ref.to_dict(),
            "caller_assignment_revision": caller_assignment_revision,
            "caller_assignment_generation": caller_assignment_generation,
            "expected_default_revision": expected_default_revision,
            "expected_project_version": expected_project_version,
        }
        project_key = request_key + ":project"
        project_ref = self._project_ref(project_key)
        with self._writer.transaction() as tx:
            # The project identity is created by the composed batch operation
            # before this parent receipt is recorded.  The request payload
            # still pins the caller's expected project version at zero; the
            # envelope must not re-apply that pre-create CAS to the now
            # materialized identity.
            envelope = self._envelope("work.create_pending_with_supervisor", project_ref, payload, request_key, actor_value)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                receipt = self._writer.mutate(envelope, event_type=PLACEMENT_EVENT, result_ref=prior.result_ref, stream="work:" + project_ref.id, transaction=tx)
                project = self.batches.graph.current(prior.result_ref or project_ref)
                relation = dict(project.payload.get("metadata", {}).get(SUPERVISION_KEY, {}))
                return {"outcome": "replayed", "project_ref": project.ref.to_dict(), "project": project.payload, "receipt": receipt.to_dict(), "supervision": relation, "replayed": True, "event_ids": list(receipt.event_ids), "executable": False}

            self._validate_caller_assignment(actor_value, caller_ref, caller_assignment_revision, caller_assignment_generation)
            pointer_ref, assignment, pointer_revision = self._resolve_default(
                tx=tx,
                actor=actor_value,
                supplied_ref=target_ref,
                supplied_revision=None if assignment_revision is None else _revision(assignment_revision, "assignment_revision"),
                supplied_generation=None if assignment_generation is None else int(assignment_generation),
                expected_default_revision=None if expected_default_revision is None else _revision(expected_default_revision, "expected_default_revision"),
            )
            relation = self._relation(default_ref=pointer_ref, assignment=assignment,
                                      project_ref=project_ref, request_key=request_key)
            batch = self.batches.create_pending_project(
                title=title,
                outcome=outcome,
                metadata=metadata,
                sheet=sheet,
                logical_request_key=project_key,
                actor=actor_value,
                creator=operator_value,
                curator=actor_value,
                _owner_supervision=relation,
            )
            receipt = self._writer.mutate(
                envelope,
                identity_payload=batch.project.payload,
                event_type=PLACEMENT_EVENT,
                result_ref=ResourceRef(self.authority, "work.project", batch.project.id, "rev-" + str(batch.project.version + 1)),
                after_refs=(pointer_ref, assignment.ref, batch.project.ref),
                effects={"portfolio_ref": self.portfolio_ref.to_dict(), "default_ref": pointer_ref.to_dict(), "assignment_ref": assignment.ref.to_dict(), "assignment_revision": _current_revision(assignment), "generation": int(assignment.generation), "project_ref": batch.project.ref.to_dict(), "project_receipt": batch.receipt.to_dict()},
                stream="work:" + batch.project.id,
                transaction=tx,
            )
            project = self.batches.graph.current(batch.project.ref)
            return {"outcome": "created", "project_ref": project.ref.to_dict(), "project": project.payload, "receipt": receipt.to_dict(), "project_receipt": batch.receipt.to_dict(), "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, pointer_revision).to_dict(), "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(), "supervision": relation, "replayed": False, "event_ids": list(receipt.event_ids), "executable": False}

    def set_default(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        target_assignment_ref: Any,
        target_assignment_revision: str,
        target_assignment_generation: int,
        expected_default_revision: str,
    ) -> Mapping[str, Any]:
        actor_value = self._actor(actor, privileged=True)
        request_key = _opaque(request_id, "request_id")
        portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        if not _same_identity(portfolio, self.portfolio_ref):
            raise WorkValidationError("portfolio_ref does not match the trusted owner binding")
        target = _ref(target_assignment_ref, authority=self.authority, kind="wrk.assignment", field="target_assignment_ref")
        pointer_ref = self._default_ref()
        payload = {"portfolio_ref": portfolio.to_dict(), "target_assignment_ref": target.to_dict(), "target_assignment_revision": target_assignment_revision, "target_assignment_generation": target_assignment_generation, "expected_default_revision": expected_default_revision}
        with self._writer.transaction() as tx:
            envelope = self._envelope("work.orchestrator-default.set", pointer_ref, payload, request_key, actor_value, expected_version=_revision_version(expected_default_revision), expected_revision=expected_default_revision)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                receipt = self._writer.mutate(envelope, event_type=DEFAULT_CHANGED_EVENT, result_ref=prior.result_ref, stream="orchestrator-default:" + pointer_ref.id, transaction=tx)
                return {"outcome": "replayed", "default_ref": pointer_ref.to_dict(), "receipt": receipt.to_dict(), "replayed": True, "event_ids": list(receipt.event_ids)}
            identity = self._writer.get_identity(pointer_ref)
            if identity is None or _current_revision(identity) != expected_default_revision:
                raise WorkValidationError("default pointer revision is stale or absent")
            assignment = self._assignment(target, expected_revision=_revision(target_assignment_revision, "target_assignment_revision"), expected_generation=int(target_assignment_generation), field="target_assignment_ref")
            new_payload = self._pointer_payload(assignment)
            receipt = self._writer.mutate(envelope, identity_payload=new_payload, event_type=DEFAULT_CHANGED_EVENT, result_ref=ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, "rev-" + str(identity.version + 1)), before_refs=(pointer_ref,), after_refs=(target,), effects={"from": identity.payload, "to": new_payload}, stream="orchestrator-default:" + pointer_ref.id, transaction=tx)
            return {"outcome": "changed", "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, "rev-" + str(identity.version + 1)).to_dict(), "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(), "receipt": receipt.to_dict(), "replayed": False, "event_ids": list(receipt.event_ids)}

    def transfer_supervision(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        project_ref: Any,
        expected_project_revision: str,
        expected_project_version: int,
        current_assignment_ref: Any,
        current_assignment_revision: str,
        current_assignment_generation: int,
        target_assignment_ref: Any,
        target_assignment_revision: str,
        target_assignment_generation: int,
        overlap_acknowledged: bool = False,
    ) -> Mapping[str, Any]:
        actor_value = self._actor(actor, privileged=True)
        if overlap_acknowledged is not True:
            raise WorkValidationError("explicit supervision transfer requires overlap acknowledgement")
        portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        project = _ref(project_ref, authority=self.authority, kind="work.project", field="project_ref")
        current_ref = _ref(current_assignment_ref, authority=self.authority, kind="wrk.assignment", field="current_assignment_ref")
        target_ref = _ref(target_assignment_ref, authority=self.authority, kind="wrk.assignment", field="target_assignment_ref")
        request_key = _opaque(request_id, "request_id")
        if not _same_identity(portfolio, self.portfolio_ref) or expected_project_version < 1:
            raise WorkValidationError("transfer scope or project version is invalid")
        payload = {"portfolio_ref": portfolio.to_dict(), "project_ref": project.to_dict(), "expected_project_revision": expected_project_revision, "expected_project_version": expected_project_version, "current_assignment_ref": current_ref.to_dict(), "current_assignment_revision": current_assignment_revision, "current_assignment_generation": current_assignment_generation, "target_assignment_ref": target_ref.to_dict(), "target_assignment_revision": target_assignment_revision, "target_assignment_generation": target_assignment_generation, "overlap_acknowledged": True}
        with self._writer.transaction() as tx:
            envelope = self._envelope("work.project.supervision.transfer", project, payload, request_key, actor_value, expected_version=expected_project_version, expected_revision=expected_project_revision)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                receipt = self._writer.mutate(envelope, event_type=TRANSFER_EVENT, result_ref=prior.result_ref, stream="work:" + project.id, transaction=tx)
                record = self.batches.graph.current(project)
                return {"outcome": "replayed", "project_ref": record.ref.to_dict(), "project": record.payload, "receipt": receipt.to_dict(), "replayed": True, "event_ids": list(receipt.event_ids)}
            record = self.batches.graph.current(project)
            if _current_revision(record) != expected_project_revision or record.version != expected_project_version:
                raise WorkValidationError("project revision or version is stale")
            current = self._assignment(current_ref, expected_revision=_revision(current_assignment_revision, "current_assignment_revision"), expected_generation=int(current_assignment_generation), field="current_assignment_ref")
            target = self._assignment(target_ref, expected_revision=_revision(target_assignment_revision, "target_assignment_revision"), expected_generation=int(target_assignment_generation), field="target_assignment_ref")
            metadata = dict(record.payload.get("metadata", {}))
            existing = metadata.get(SUPERVISION_KEY)
            if not isinstance(existing, Mapping) or not _same_identity(ResourceRef.from_dict(existing["assignment_ref"]), current.ref):
                raise WorkValidationError("current supervision does not match the transfer fence")
            existing_portfolio = existing.get("portfolio_ref")
            existing_project = existing.get("project_ref")
            stored_portfolio = _ref(existing_portfolio, authority=self.authority,
                                    kind=PORTFOLIO_KIND, field="stored portfolio_ref")
            stored_project = _ref(existing_project, authority=self.authority,
                                  kind="work.project", field="stored project_ref")
            if (not _same_identity(stored_portfolio, self.portfolio_ref)
                    or not _same_identity(stored_project, project)
                    or existing.get("assignment_revision") != _current_revision(current)
                    or existing.get("generation") != current.generation):
                raise WorkValidationError("current supervision scope or assignment fence is stale")
            pointer_ref = self._default_ref()
            pointer = self._writer.get_identity(pointer_ref)
            if pointer is None:
                raise WorkValidationError("default pointer is absent")
            relation = self._relation(default_ref=pointer_ref, assignment=target,
                                      project_ref=project, request_key=existing.get("request_id", request_key))
            updated = dict(record.payload)
            updated["metadata"] = dict(metadata, **{SUPERVISION_KEY: relation})
            receipt = self._writer.mutate(envelope, identity_payload=updated, event_type=TRANSFER_EVENT, result_ref=ResourceRef(self.authority, "work.project", project.id, "rev-" + str(record.version + 1)), before_refs=(record.ref, current.ref), after_refs=(target.ref,), effects={"from_assignment": current.ref.to_dict(), "to_assignment": target.ref.to_dict()}, stream="work:" + project.id, transaction=tx)
            return {"outcome": "transferred", "project_ref": ResourceRef(self.authority, "work.project", project.id, "rev-" + str(record.version + 1)).to_dict(), "project": updated, "supervision": relation, "receipt": receipt.to_dict(), "replayed": False, "event_ids": list(receipt.event_ids)}

    def detach_existing_project(self, *, actor: Any, request_id: str, project_ref: Any,
                                expected_project_version: int) -> Mapping[str, Any]:
        """Remove supervision using the existing supervision-transfer receipt.

        Detachment is a transfer to no supervisor, so it needs no new stored
        kind, operation descriptor or event type. The owner composes document
        unlinks in the same outer transaction.
        """
        actor_value = self._actor(actor, privileged=True)
        project = _ref(project_ref, authority=self.authority, kind="work.project", field="project_ref")
        key = _opaque(request_id, "request_id")
        payload = {"action": "detach", "project_ref": project.to_dict(),
                   "portfolio_ref": self.portfolio_ref.to_dict(),
                   "expected_project_version": expected_project_version}
        with self._writer.transaction() as tx:
            envelope = self._envelope("work.project.supervision.transfer", project, payload, key,
                                      actor_value, expected_version=expected_project_version)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                return {"outcome": "replayed", "project_ref": prior.result_ref.to_dict(),
                        "receipt": prior.to_dict(), "replayed": True, "event_ids": list(prior.event_ids)}
            record = self.batches.graph.current(project)
            relation = record.payload.get("metadata", {}).get(SUPERVISION_KEY) or {}
            if (record.version != expected_project_version
                    or not _same_identity(ResourceRef.from_dict(relation.get("portfolio_ref", {})), self.portfolio_ref)):
                raise WorkValidationError("project supervision or version is stale or foreign")
            if not _same_identity(ResourceRef.from_dict(relation.get("project_ref", {})), project):
                raise WorkValidationError("project supervision belongs to another project")
            assignment = self._assignment(ResourceRef.from_dict(relation["assignment_ref"]),
                expected_revision=None, expected_generation=relation["generation"], field="supervisor")
            if actor_value.actor != self.default_actor.actor and assignment.principal != actor_value.actor:
                raise WorkValidationError("only the project's orchestrator or owner may detach it")
            manager_refs = self.reader.find_identity_refs(kind="wrk.assignment", payload_matches={
                ("scope", "authority"): project.authority, ("scope", "kind"): project.kind,
                ("scope", "id"): project.id, ("role",): "manager", ("status",): "in-flight"})
            if manager_refs:
                raise WorkValidationError("cannot detach while the project's manager is running")
            updated = dict(record.payload)
            updated["metadata"] = {k: v for k, v in record.payload.get("metadata", {}).items()
                                   if k != SUPERVISION_KEY}
            result_ref = ResourceRef(project.authority, project.kind, project.id, "rev-" + str(record.version + 1))
            receipt = self._writer.mutate(envelope, identity_payload=updated, event_type=TRANSFER_EVENT,
                result_ref=result_ref, before_refs=(record.ref,), effects={"action": "detach", "supervision": None},
                stream="work:" + project.id, transaction=tx)
            return {"outcome": "detached", "project_ref": result_ref.to_dict(), "supervision": None,
                    "receipt": receipt.to_dict(), "replayed": False, "event_ids": list(receipt.event_ids)}

    def adopt_resources_with_supervision(
        self, *, actor: Any, request_id: str, assignment_ref: Any,
        expected_generation: int, resources: Sequence[Mapping[str, Any]],
        expected_default_ref: Any, projects: Sequence[Mapping[str, Any]],
        expected_guard_ref: Any = None,
    ) -> Mapping[str, Any]:
        """Atomically refresh one unchanged root and all its exact existing joins.

        This composes the existing assignment-adoption, default and supervision
        transfer operations. It cannot attach, reassign or omit projects, and
        uses the original owner transaction/receipts rather than a new ledger.
        """
        selected = self._actor(actor, privileged=True)
        key = _opaque(request_id, "request_id")
        target = _ref(assignment_ref, authority=self.authority, kind="wrk.assignment", field="assignment_ref")
        if target.revision is None or not isinstance(expected_generation, int) or isinstance(expected_generation, bool):
            raise WorkValidationError("exact assignment revision/generation required")
        if self.main_assignment_ref is None or not _same_identity(target, self.main_assignment_ref):
            raise WorkValidationError("only the bound main root may refresh resources")
        default = _ref(expected_default_ref, authority=self.authority, kind=DEFAULT_KIND, field="expected_default_ref")
        if default.revision is None or not _same_identity(default, self._default_ref()):
            raise WorkValidationError("exact current default pointer required")
        if not isinstance(projects, (list, tuple)) or not projects:
            raise WorkValidationError("complete nonempty supervised project selection required")
        normalized = []
        seen = set()
        for item in projects:
            if not isinstance(item, Mapping) or set(item) != {"project_ref", "project_version", "supervision"}:
                raise WorkValidationError("project refresh requires exact ref/version/relation")
            ref = _ref(item["project_ref"], authority=self.authority, kind="work.project", field="project_ref")
            if ref.revision is None or ref.id in seen:
                raise WorkValidationError("duplicate or unpinned project")
            seen.add(ref.id)
            normalized.append({"project_ref": ref.to_dict(), "project_version": item["project_version"],
                               "supervision": _safe(item["supervision"])})
        payload = {"portfolio_ref": self.portfolio_ref.to_dict(), "assignment_ref": target.to_dict(),
                   "expected_generation": expected_generation, "resources": _safe(resources),
                   "expected_default_ref": default.to_dict(), "projects": normalized,
                   "expected_guard_ref": _safe(expected_guard_ref)}
        first = ResourceRef.from_dict(normalized[0]["project_ref"])
        envelope = self._envelope("work.project.supervision.transfer", first, payload, key, selected,
                                  expected_revision=first.revision, expected_version=normalized[0]["project_version"])
        with self._writer.transaction() as tx:
            prior = self._lookup_replay(envelope)
            if prior is not None:
                event = next(item for item in self._writer.list_events(stream="work:" + first.id)
                             if item.event_id in prior.event_ids)
                result = event.effects["root_resource_refresh"]
                return {**result, "outcome": "replayed", "replayed": True, "receipt": prior.to_dict()}
            root = self._assignment(target, expected_revision=target.revision,
                                    expected_generation=expected_generation, field="assignment_ref")
            if root.principal != selected.actor:
                raise WorkValidationError("resource adoption requires the unchanged root owner")
            pointer = self._writer.get_identity(default)
            if (pointer is None or pointer.ref != default
                    or pointer.payload.get("assignment_revision") != root.revision
                    or pointer.payload.get("generation") != root.generation
                    or not _same_identity(ResourceRef.from_dict(pointer.payload["assignment_ref"]), root.ref)):
                raise WorkValidationError("default root relation is stale")
            joined = self.reader.find_identity_refs(kind="work.project", payload_matches={
                ("metadata", SUPERVISION_KEY, "assignment_ref", "id"): root.id})
            if {ref.id for ref in joined} != seen:
                raise WorkValidationError("selection must include every existing root join")
            records = []
            for item in normalized:
                record = self.batches.graph.current(ResourceRef.from_dict(item["project_ref"]))
                relation = record.payload.get("metadata", {}).get(SUPERVISION_KEY)
                if (record.ref.to_dict() != item["project_ref"] or record.version != item["project_version"]
                        or relation != item["supervision"] or not isinstance(relation, Mapping)
                        or relation.get("assignment_ref") != root.ref.to_dict()
                        or relation.get("assignment_revision") != root.revision
                        or relation.get("generation") != root.generation
                        or not _same_identity(ResourceRef.from_dict(relation["portfolio_ref"]), self.portfolio_ref)
                        or not _same_identity(ResourceRef.from_dict(relation["project_ref"]), record.ref)):
                    raise WorkValidationError("supervised project fence is stale or foreign")
                records.append(record)
            refreshed = self.assignments.adopt_resources(
                target, resources=resources, expected_revision=root.revision,
                expected_generation=root.generation, expected_guard_ref=expected_guard_ref,
                logical_request_key=key + ":assignment", actor=selected)
            changed_default = self.set_default(actor=selected, request_id=key + ":default",
                portfolio_ref=self.portfolio_ref, target_assignment_ref=refreshed.ref,
                target_assignment_revision=refreshed.revision, target_assignment_generation=refreshed.generation,
                expected_default_revision=default.revision)
            default_after = ResourceRef.from_dict(changed_default["default_ref"])
            attachments = []
            for record in records:
                after = ResourceRef(self.authority, "work.project", record.id, "rev-" + str(record.version + 1))
                relation = self._relation(default_ref=default_after, assignment=refreshed,
                    project_ref=after, request_key=record.payload["metadata"][SUPERVISION_KEY]["request_id"],
                    default_revision=default_after.revision)
                attachments.append({"project_ref": after.to_dict(), "supervision": relation})
            result = {"outcome": "resources-adopted", "replayed": False,
                      "assignment_ref": refreshed.ref.to_dict(), "generation": refreshed.generation,
                      "default_ref": default_after.to_dict(), "attachments": attachments,
                      "assignment_receipt": self._writer.get_receipt(key + ":assignment").to_dict(),
                      "default_receipt": changed_default["receipt"], "provider_called": False, "executable": False}
            receipts = []
            for index, (record, attachment) in enumerate(zip(records, attachments)):
                updated = dict(record.payload)
                updated["metadata"] = dict(record.payload["metadata"], **{SUPERVISION_KEY: attachment["supervision"]})
                child = envelope if index == 0 else self._envelope(
                    "work.project.supervision.transfer", record.ref,
                    {"project_ref": record.ref.to_dict(), "supervision": attachment["supervision"]},
                    key + ":project:" + record.id, selected,
                    expected_revision=record.revision, expected_version=record.version)
                receipt = self._writer.mutate(child, identity_payload=updated, event_type=TRANSFER_EVENT,
                    result_ref=ResourceRef.from_dict(attachment["project_ref"]), before_refs=(record.ref, root.ref),
                    after_refs=(refreshed.ref,), effects={"from_assignment": root.ref.to_dict(),
                        "to_assignment": refreshed.ref.to_dict(), "supervision": attachment["supervision"],
                        **({"root_resource_refresh": result} if index == 0 else {})},
                    stream="work:" + record.id, transaction=tx)
                receipts.append(receipt.to_dict())
            return {**result, "receipt": receipts[0], "project_receipts": receipts}

    def attach_existing_projects(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        target_assignment_ref: Any,
        target_assignment_revision: Optional[str],
        target_assignment_generation: int,
        projects: Sequence[Mapping[str, Any]],
        expected_default_revision: Optional[str] = None,
        preview: bool = False,
        request_binding: Optional[str] = None,
    ) -> Mapping[str, Any]:
        """Attach selected existing projects to one portfolio orchestrator.

        This is the existing-project counterpart to
        :meth:`create_pending_with_supervisor`.  It deliberately performs all
        project and assignment checks before the first identity mutation, then
        composes the metadata revisions and retained receipts in the supplied
        WRK transaction.  Project mandates and non-supervision payload fields
        are copied unchanged.
        """

        actor_value = self._actor(actor)
        if request_binding is not None and (not isinstance(request_binding, str)
                or len(request_binding) != 64 or any(c not in "0123456789abcdef" for c in request_binding)):
            raise WorkValidationError("request_binding must be an exact SHA256 input digest")
        request_key = _opaque(request_id, "request_id")
        portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        if not _same_identity(portfolio, self.portfolio_ref):
            raise WorkValidationError("portfolio_ref does not match the trusted owner binding")
        target = _ref(target_assignment_ref, authority=self.authority, kind="wrk.assignment", field="target_assignment_ref")
        if target_assignment_revision is None:
            target_assignment_revision = target.revision
        if target_assignment_revision is None:
            raise WorkValidationError("target_assignment_revision is required")
        target_revision = _revision(target_assignment_revision, "target_assignment_revision")
        if target.revision != target_revision:
            raise WorkValidationError("target_assignment_ref revision is stale")
        if not isinstance(target_assignment_generation, int) or isinstance(target_assignment_generation, bool):
            raise WorkValidationError("target_assignment_generation must be an integer")
        if not isinstance(projects, Sequence) or isinstance(projects, (str, bytes)) or not projects:
            raise WorkValidationError("projects must be a non-empty list")

        # Reconcile an exact retained request before inspecting mutable live
        # project revisions.  A successful first application advances those
        # revisions, but the same request key must still replay safely.
        request_projects = []
        for index, item in enumerate(projects):
            field = f"projects[{index}]"
            if not isinstance(item, Mapping):
                raise WorkValidationError(f"{field} must be an object")
            project = _ref(item.get("project_ref"), authority=self.authority, kind="work.project", field=field + ".project_ref")
            if project.revision is None:
                raise WorkValidationError(f"{field}.project_ref must pin the current project revision")
            expected_version = item.get("project_version", item.get("expected_project_version"))
            if expected_version is None:
                expected_version = _revision_version(project.revision)
            assignment_value = item.get("assignment_ref")
            if assignment_value is None:
                assignment_value = item.get("current_assignment_ref", item.get("manager_assignment_ref"))
            assignment_ref = None if assignment_value is None else _ref(assignment_value, authority=self.authority, kind="wrk.assignment", field=field + ".assignment_ref")
            assignment_revision = item.get("assignment_revision")
            if assignment_revision is None:
                assignment_revision = item.get("current_assignment_revision", item.get("manager_assignment_revision"))
            if assignment_ref is not None and (assignment_ref.revision is None or assignment_revision is None):
                raise WorkValidationError(f"{field} requires an assignment_ref with an assignment revision pin")
            if assignment_revision is not None:
                assignment_revision = _revision(assignment_revision, field + ".assignment_revision")
            if assignment_ref is not None and assignment_ref.revision != assignment_revision:
                raise WorkValidationError(f"{field}.assignment_ref revision is stale")
            assignment_generation = item.get("assignment_generation")
            if assignment_generation is None:
                assignment_generation = item.get("current_assignment_generation", item.get("manager_assignment_generation", item.get("generation")))
            if assignment_ref is None and (assignment_revision is not None or assignment_generation is not None):
                raise WorkValidationError(f"{field} absent assignment cannot include revision/generation pins")
            if assignment_ref is not None and (not isinstance(assignment_generation, int) or isinstance(assignment_generation, bool)):
                raise WorkValidationError(f"{field}.assignment_generation must be an integer")
            mandate_value = item.get("mandate_ref")
            mandate = None if mandate_value is None else _ref(mandate_value, authority=self.authority, kind="dat.content.document", field=field + ".mandate_ref")
            request_projects.append({"project_ref": project.to_dict(), "project_version": expected_version,
                                     "assignment_ref": None if assignment_ref is None else assignment_ref.to_dict(),
                                     "assignment_revision": assignment_revision,
                                     "assignment_generation": assignment_generation,
                                     "mandate_ref": None if mandate is None else mandate.to_dict()})
        request_payload = {
            "portfolio_ref": portfolio.to_dict(),
            "target_assignment_ref": target.to_dict(),
            "target_assignment_revision": target_revision,
            "target_assignment_generation": target_assignment_generation,
            "expected_default_revision": expected_default_revision,
            "projects": request_projects,
        }
        if request_binding is not None:
            request_payload["request_binding"] = request_binding
        replay_envelope = self._envelope(
            "work.project.supervision.attach", _ref(projects[0].get("project_ref"), authority=self.authority, kind="work.project", field="projects[0].project_ref"),
            request_payload, request_key, actor_value,
            expected_version=request_projects[0]["project_version"], expected_revision=request_projects[0]["project_ref"]["revision"],
        )
        prior = self._lookup_replay(replay_envelope)
        if prior is not None:
            event = next((candidate for candidate in self._writer.list_events(stream="work:" + replay_envelope.target.id)
                          if candidate.event_id in prior.event_ids), None)
            effects = event.effects if event is not None and isinstance(event.effects, Mapping) else {}
            return {"outcome": "replayed", "replayed": True, "preview": False,
                    "portfolio_ref": portfolio.to_dict(), "default_ref": effects.get("default_ref"),
                    "assignment_ref": effects.get("assignment_ref"),
                    "attachments": effects.get("attachments", []), "receipt": prior.to_dict(),
                    "writes": 0, "event_ids": list(prior.event_ids), "executable": False}

        target_assignment = self._assignment(
            target, expected_revision=target_revision,
            expected_generation=target_assignment_generation,
            field="target_assignment_ref",
        )

        plans: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for index, item in enumerate(projects):
            field = f"projects[{index}]"
            if not isinstance(item, Mapping):
                raise WorkValidationError(f"{field} must be an object")
            project_value = item.get("project_ref")
            project = _ref(project_value, authority=self.authority, kind="work.project", field=field + ".project_ref")
            if project.revision is None:
                raise WorkValidationError(f"{field}.project_ref must pin the current project revision")
            identity_key = (project.authority, project.kind, project.id)
            if identity_key in seen:
                raise WorkValidationError(f"{field}.project_ref is duplicated")
            seen.add(identity_key)
            record = self.batches.graph.current(project)
            if record.ref != project:
                raise WorkValidationError(f"{field}.project_ref revision is stale")
            expected_version = item.get("project_version", item.get("expected_project_version"))
            if expected_version is not None:
                if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version != record.version:
                    raise WorkValidationError(f"{field}.project_version is stale")

            assignment_value = item.get("assignment_ref")
            if assignment_value is None:
                assignment_value = item.get("current_assignment_ref", item.get("manager_assignment_ref"))
            assignment_revision = item.get("assignment_revision")
            if assignment_revision is None:
                assignment_revision = item.get("current_assignment_revision", item.get("manager_assignment_revision"))
            assignment_generation = item.get("assignment_generation")
            if assignment_generation is None:
                assignment_generation = item.get("current_assignment_generation", item.get("manager_assignment_generation", item.get("generation")))
            assignment = None
            if assignment_value is not None:
                assignment_ref = _ref(assignment_value, authority=self.authority, kind="wrk.assignment", field=field + ".assignment_ref")
                if assignment_ref.revision is None or assignment_revision is None or assignment_generation is None:
                    raise WorkValidationError(f"{field} assignment requires revision and generation pins")
                assignment_revision = _revision(assignment_revision, field + ".assignment_revision")
                if assignment_ref.revision != assignment_revision:
                    raise WorkValidationError(f"{field}.assignment_ref revision is stale")
                if not isinstance(assignment_generation, int) or isinstance(assignment_generation, bool):
                    raise WorkValidationError(f"{field}.assignment_generation must be an integer")
                assignment = self._project_assignment(
                    assignment_ref, expected_revision=assignment_revision,
                    expected_generation=assignment_generation,
                    field=field + ".assignment_ref",
                )
                if not _same_identity(assignment.scope, project):
                    raise WorkValidationError(f"{field}.assignment_ref is outside the project scope")
            else:
                if assignment_revision is not None or assignment_generation is not None:
                    raise WorkValidationError(f"{field} absent assignment cannot include revision/generation pins")
                self._pending_unassigned(record, field=field)

            mandate_value = item.get("mandate_ref")
            mandate = None
            if mandate_value is not None:
                mandate = _ref(mandate_value, authority=self.authority, kind="dat.content.document", field=field + ".mandate_ref")
                if mandate.revision is None:
                    raise WorkValidationError(f"{field}.mandate_ref must pin a revision")
                mandate_identity = self._writer.get_identity(ResourceRef(mandate.authority, mandate.kind, mandate.id))
                if mandate_identity is None or mandate_identity.ref != mandate:
                    raise WorkValidationError(f"{field}.mandate_ref is stale or missing")

            metadata = record.payload.get("metadata", {})
            existing = metadata.get(SUPERVISION_KEY) if isinstance(metadata, Mapping) else None
            if existing is not None:
                if not isinstance(existing, Mapping):
                    raise WorkValidationError(f"{field} has malformed supervision metadata")
                stored_portfolio = _ref(existing.get("portfolio_ref"), authority=self.authority, kind=PORTFOLIO_KIND, field=field + ".stored portfolio_ref")
                if not _same_identity(stored_portfolio, self.portfolio_ref):
                    raise WorkValidationError(f"{field} is supervised by a foreign portfolio")
                raise WorkValidationError(f"{field} is already supervised; use the transfer operation")
            plans.append({"record": record, "project": project, "assignment": assignment, "mandate": mandate})

        pointer_ref = self._default_ref()
        pointer_identity = self._writer.get_identity(pointer_ref)
        if preview:
            if pointer_identity is None:
                if expected_default_revision not in (None, "initial"):
                    raise WorkValidationError("default pointer is absent but expected_default_revision is not initial")
                default_revision = "initial"
                assignment = target_assignment
            else:
                pointer, assignment, default_revision = self._resolve_default(
                    tx=None,
                    actor=actor_value,
                    supplied_ref=target,
                    supplied_revision=target_revision,
                    supplied_generation=target_assignment_generation,
                    expected_default_revision=None if expected_default_revision is None else _revision(expected_default_revision, "expected_default_revision"),
                )
                pointer_ref = pointer
            relations = [
                self._relation(default_ref=pointer_ref, assignment=assignment, project_ref=plan["record"].ref, request_key=request_key, default_revision=default_revision)
                for plan in plans
            ]
            return {
                "outcome": "preview", "preview": True, "replayed": False,
                "portfolio_ref": portfolio.to_dict(),
                "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, default_revision).to_dict(),
                "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(),
                "attachments": [{"project_ref": plan["record"].ref.to_dict(), "supervision": relation} for plan, relation in zip(plans, relations)],
                "writes": 0, "event_ids": [], "executable": False,
            }

        payload = request_payload
        first = plans[0]["record"]
        with self._writer.transaction() as tx:
            for plan in plans:
                if plan["assignment"] is None:
                    self._pending_unassigned(plan["record"], field="selected project")
            envelope = self._envelope(
                "work.project.supervision.attach", first.ref, payload, request_key,
                actor_value, expected_version=first.version, expected_revision=first.revision,
            )
            pointer_ref, assignment, default_revision = self._resolve_default(
                tx=tx,
                actor=actor_value,
                supplied_ref=target,
                supplied_revision=target_revision,
                supplied_generation=target_assignment_generation,
                expected_default_revision=None if expected_default_revision is None else _revision(expected_default_revision, "expected_default_revision"),
            )
            relations = [
                self._relation(default_ref=pointer_ref, assignment=assignment, project_ref=plan["record"].ref, request_key=request_key, default_revision=default_revision)
                for plan in plans
            ]
            attachments = [
                {"project_ref": ResourceRef(self.authority, "work.project", plan["record"].id, "rev-" + str(plan["record"].version + 1)).to_dict(), "supervision": relation}
                for plan, relation in zip(plans, relations)
            ]
            receipts = []
            for index, (plan, relation) in enumerate(zip(plans, relations)):
                record = plan["record"]
                metadata = dict(record.payload.get("metadata", {}))
                updated = dict(record.payload)
                metadata[SUPERVISION_KEY] = relation
                updated["metadata"] = metadata
                child_key = request_key if index == 0 else request_key + ":project:" + record.id
                child_payload = {"project_ref": record.ref.to_dict(), "supervision": relation}
                child_envelope = self._envelope(
                    "work.project.supervision.attach", record.ref, payload if index == 0 else child_payload,
                    child_key, actor_value, expected_version=record.version, expected_revision=record.revision,
                )
                receipt = self._writer.mutate(
                    child_envelope, identity_payload=updated, event_type=ATTACH_EVENT,
                    result_ref=ResourceRef(self.authority, "work.project", record.id, "rev-" + str(record.version + 1)),
                    before_refs=tuple(ref for ref in (record.ref, None if plan["assignment"] is None else plan["assignment"].ref) if ref is not None),
                    after_refs=(assignment.ref,),
                    effects={"project_ref": ResourceRef(self.authority, "work.project", record.id, "rev-" + str(record.version + 1)).to_dict(), "supervision": relation,
                             **({"attachments": attachments, "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, default_revision).to_dict(), "assignment_ref": assignment.ref.to_dict()} if index == 0 else {})},
                    stream="work:" + record.id, transaction=tx,
                )
                receipts.append(receipt)
            first_receipt = receipts[0]
            return {"outcome": "attached", "replayed": False, "preview": False,
                    "portfolio_ref": portfolio.to_dict(), "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, default_revision).to_dict(),
                    "assignment_ref": assignment.ref.to_dict(), "attachments": attachments,
                    "receipt": first_receipt.to_dict(), "project_receipts": [receipt.to_dict() for receipt in receipts],
                    "writes": len(receipts), "event_ids": [event_id for receipt in receipts for event_id in receipt.event_ids], "executable": False}


Orchestration = command_facade(_OrchestrationEngine, ORCHESTRATION_DOMAIN_ID)


__all__ = [
    "DEFAULT_KIND",
    "ORCHESTRATION_DOMAIN_ID",
    "ORCHESTRATION_SCHEMA_REVISION",
    "Orchestration",
    "contribution",
]
