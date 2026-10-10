"""Shared bounded assessment operations over the supplied FND ports.

There is no assessment table or private writer here.  A parent operation is a
single FND command/receipt.  Child projections are deterministic identities in
that same transaction, and a failure rolls back the parent, children, events,
receipts, operation identity, and reservation together.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from herzchen.command_ports import command_facade

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    ReceiptStatus,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
    validate_replay,
)
from herzchen.kernel import (
    AllowanceExhaustedError,
    LimitService,
    OperationManager,
    OperationRequest,
    OperationState,
    ReservationRecord,
    Store,
    TargetMismatchError,
    VersionConflictError,
)

from .model import (
    AssessmentAuthorityError,
    AssessmentError,
    AssessmentNotFoundError,
    AssessmentResult,
    AssessmentScope,
    AssessmentStateError,
    CandidateSelection,
    Correction,
    Decision,
    Disposition,
    Finding,
    InputPacket,
    Invocation,
    StaleAssessmentError,
    Verdict,
)


DOMAIN_ID = "herzchen.assessment"
DOMAIN_VERSION = "1.0"
DOMAIN_OWNER = "wrk"
SCHEMA_REVISION = "assessment.v1"
SCOPE_KIND = "assessment.scope"
CRITERION_KIND = "assessment.criterion"
INPUT_KIND = "assessment.input"
SELECTION_KIND = "assessment.selection"
RESULT_KIND = "assessment.result"
INVOCATION_KIND = "assessment.invocation"
FINDING_KIND = "assessment.finding"
CORRECTION_KIND = "assessment.correction"
DECISION_KIND = "assessment.decision"
LOOP_FACTS_KIND = "assessment.loop-facts"
ASSESSMENT_STREAM = "assessment"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def verify_dat_evidence(store: Any, evidence: Any, *, actor: AuthenticatedActor,
                        scopes: Sequence[Any] = (), payload_resolver: Any = None) -> Mapping[str, Any]:
    """Resolve one exact DAT revision through the existing visibility/content owners."""
    ref = _ref(evidence, "evidence")
    if ref.kind != "dat.content.document" or ref.revision is None:
        return {"state": "unknown", "reason": "unsupported_or_unpinned_evidence"}
    try:
        from herzchen.content import ContentCommandHandler
        from herzchen.content.packets import ContextPacketService

        scoped = tuple(_ref(value, "evidence scope") for value in scopes if value is not None)
        metadata = ContentCommandHandler(store).metadata(ref, actor=actor, scopes=scoped)
        if metadata.get("representation") == "managed":
            manifest = metadata["manifest"]
            reference = {"schema": "dat.content.consumer-reference.v1", "reference": ref.to_dict(),
                "representation": "managed", "content_digest": metadata["content_digest"],
                "byte_digest": manifest["byte_digest"], "byte_length": manifest["byte_length"],
                "availability": metadata["availability"], "verification": "manifest-verified"}
            result = {"state": "unknown", "reason": "managed_payload_not_fully_verified",
                "manifest_state": "verified", "manifest_digest": metadata["content_digest"],
                "representation": "managed-bytes.v1", "ref": ref.to_dict(), "consumer_reference": reference}
            if payload_resolver is not None:
                observed = payload_resolver.resolve(ref, actor=actor, scopes=scoped,
                    verify_full=True, max_bytes=0)
                result["io_work"] = observed.get("io_work")
                if observed.get("verification") == "full-verified" and observed.get("actual_digest") == manifest["byte_digest"]:
                    result.update(state="verified", reason="managed_payload_full_verification",
                        digest=manifest["byte_digest"], algorithm="sha256", verification_scope="full-payload")
                elif observed.get("availability") == "corrupt":
                    result.update(state="mismatch", reason="managed_payload_mismatch")
            return result
        resolved = ContextPacketService(store).resolve_reference(ref, actor=actor, scopes=scoped)
        if resolved.get("foreign") or resolved.get("resolved") != ref:
            return {"state": "unknown", "reason": "evidence_ref_unresolved"}
        value = ContentCommandHandler(store).read(ref)
        if not value or value.get("identity") != ref:
            return {"state": "unknown", "reason": "evidence_content_unavailable"}
        revision = resolved.get("revision")
        stored_digest = revision.get("content_digest") if isinstance(revision, Mapping) else getattr(revision, "content_digest", None)
        content = value.get("content")
        if isinstance(content, Mapping) and content.get("representation_version") == "managed-bytes.v1":
            # Historical managed receipts without a bounded projection remain
            # readable, but a JSON manifest hash is never proof of payload bytes.
            return {"state": "unknown", "reason": "historical_managed_payload_requires_resolver",
                    "representation": "managed-bytes.v1", "ref": ref.to_dict()}
        if content is None or not isinstance(stored_digest, str):
            return {"state": "unknown", "reason": "evidence_content_unavailable"}
        digest = _digest(content)
        if _digest(resolved.get("content")) != digest:
            return {"state": "mismatch", "reason": "dat_owner_read_mismatch", "digest": digest}
        if stored_digest.lower() != digest:
            return {"state": "mismatch", "reason": "dat_content_digest_mismatch", "digest": digest}
        return {"state": "verified", "digest": digest, "algorithm": "sha256",
                "representation": "herzchen.canonical_json.utf8", "ref": ref.to_dict()}
    except Exception:
        # A missing, denied, external or unsupported owner read is not a proof.
        return {"state": "unknown", "reason": "evidence_read_unavailable"}


def _ref(value: Any, field: str = "reference") -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
        return value.ref
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except Exception as exc:  # pragma: no cover - contract supplies detail
            raise AssessmentError(f"{field} must be a typed ResourceRef") from exc
    if isinstance(value, str) and value.strip():
        raise AssessmentError(f"{field} must be a typed ResourceRef, not an untyped id")
    raise AssessmentError(f"{field} must be a typed ResourceRef")


def _ref_dict(value: Optional[ResourceRef]) -> Optional[dict[str, Any]]:
    return None if value is None else value.to_dict()


def _stable_ref(value: ResourceRef) -> ResourceRef:
    """Return the logical identity reference while retaining full authority/kind/id."""
    return ResourceRef(value.authority, value.kind, value.id)


def _same_identity(left: ResourceRef, right: ResourceRef) -> bool:
    """Compare logical identities, not an incidental current revision pin."""
    return (left.authority, left.kind, left.id) == (right.authority, right.kind, right.id)


def _safe(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


def _logical_ref(value: Any, field: str) -> ResourceRef:
    """Normalize only projection objects; explicit refs retain their pins."""
    ref = _ref(value, field)
    if isinstance(value, (AssessmentResult, Finding)):
        return ResourceRef(ref.authority, ref.kind, ref.id)
    return ref


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise AssessmentError(f"{field} must be a non-blank opaque identifier")
    return value


def contribution() -> DomainContribution:
    return DomainContribution(
        domain_id=DOMAIN_ID,
        version=DOMAIN_VERSION,
        owner=DOMAIN_OWNER,
        resource_types=(
            SCOPE_KIND, CRITERION_KIND, INPUT_KIND, SELECTION_KIND, RESULT_KIND,
            INVOCATION_KIND, FINDING_KIND, CORRECTION_KIND, DECISION_KIND,
            LOOP_FACTS_KIND,
        ),
        document_types=(),
        namespace_types=("assessment", "assessment.guidance", "assessment.protocol"),
        operation_types=(
            "assessment.scope.declare", "assessment.input.freeze", "assessment.candidate.select",
            "assessment.run", "assessment.correction.create", "assessment.finding.close",
            "assessment.accept", "assessment.unknown.disposition", "assessment.loop-facts.record",
            "assessment.result.link-correction", "assessment.finding.link-correction",
            "assessment.correction.resolve",
        ),
        event_types=(
            "assessment.scope.declared", "assessment.input.frozen", "assessment.candidate.selected",
            "assessment.completed", "assessment.correction.created", "assessment.finding.closed",
            "assessment.accepted", "assessment.unknown.disposed", "assessment.loop-facts.recorded",
            "assessment.result.correction-linked", "assessment.finding.correction-linked",
            "assessment.correction.resolved",
        ),
        schema_revision=SCHEMA_REVISION,
        composition_bindings=(
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "fnd-04.limits", "fnd-04.operations", "handler-required",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.scope.declare|" + SCOPE_KIND + "|assessment.scope.declared",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.input.freeze|" + INPUT_KIND + "|assessment.input.frozen",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.candidate.select|" + SELECTION_KIND + "|assessment.candidate.selected",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.run|" + RESULT_KIND + "|assessment.completed",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.correction.create|" + CORRECTION_KIND + "|assessment.correction.created",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.finding.close|" + FINDING_KIND + "|assessment.finding.closed",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.accept|" + DECISION_KIND + "|assessment.accepted",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.unknown.disposition|" + DECISION_KIND + "|assessment.unknown.disposed",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.loop-facts.record|" + LOOP_FACTS_KIND + "|assessment.loop-facts.recorded",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.result.link-correction|" + RESULT_KIND + "|assessment.result.correction-linked",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.finding.link-correction|" + FINDING_KIND + "|assessment.finding.correction-linked",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.correction.resolve|" + CORRECTION_KIND + "|assessment.correction.resolved",
        ),
    )


class _AssessmentModuleEngine:
    """One shared assessment surface for Megado and creative protocols."""

    def __init__(self, store: Store, *, actor: Optional[AuthenticatedActor] = None) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be the supplied FND Store")
        try:
            self.__writer = store.domain_handler((contribution(),))
        except Exception:
            self.__writer = store
        self.reader = self.__writer.consumer()
        self.default_actor = actor
        self._evidence_store = store
        self.limits = LimitService(store)
        self.operations = OperationManager(store)

    def _evidence_scopes(self, parent: ResourceRef) -> tuple[ResourceRef, ...]:
        record = self.__writer.get_identity(parent)
        payload = {} if record is None else record.payload
        raw_project = payload.get("project_ref") or payload.get("parent") if isinstance(payload, Mapping) else None
        project = _ref(raw_project, "evidence project") if raw_project is not None else None
        return (parent,) if project is None else (parent, project)

    def register(self) -> DomainContribution:
        descriptor = contribution()
        self.__writer = self.__writer.register_domain_handler((descriptor,))
        self.reader = self.__writer.consumer()
        return descriptor

    # ---- scope and frozen input -------------------------------------------------

    def declare_scope(
        self,
        scope: Any,
        *,
        parent_obligation: Any,
        protocol: str,
        criteria: Sequence[Any] = (),
        review_required: bool = True,
        allow_no_review: bool = False,
        designated_approver: Optional[str] = None,
        authority: Optional[str] = None,
        policy: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> AssessmentScope:
        scope_ref = self._stable_local(scope, SCOPE_KIND)
        parent_ref = self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation")
        protocol = _opaque(protocol, "protocol")
        if not isinstance(criteria, (tuple, list)):
            raise AssessmentError("criteria must be a sequence of typed references or mappings")
        request_key = self._key(logical_request_key, "scope")
        selected_actor = self._actor(actor)
        criterion_specs = tuple(criteria)
        criterion_refs: list[ResourceRef] = []
        child_specs: list[tuple[ResourceRef, Mapping[str, Any]]] = []
        for index, value in enumerate(criterion_specs):
            if isinstance(value, ResourceRef) or hasattr(value, "ref"):
                criterion_refs.append(self._current_ref(_ref(value, "criterion"), "criterion"))
            elif isinstance(value, Mapping):
                criterion_id = _opaque(value.get("id", f"{request_key}-criterion-{index}"), "criterion id")
                criterion_ref = ResourceRef(self.__writer.authority, CRITERION_KIND, criterion_id, "rev-1")
                criterion_refs.append(criterion_ref)
                child_specs.append((criterion_ref, {"record_type": CRITERION_KIND, "id": criterion_id, "definition": _safe(dict(value)), "schema_revision": SCHEMA_REVISION}))
            else:
                raise AssessmentError("criteria must contain typed ResourceRef values or criterion mappings")
        payload = {
            "record_type": SCOPE_KIND,
            "schema_revision": SCHEMA_REVISION,
            "parent_obligation_ref": parent_ref,
            "protocol": protocol,
            "criterion_refs": tuple(criterion_refs),
            "review_required": bool(review_required),
            "allow_no_review": bool(allow_no_review),
            "designated_approver": designated_approver,
            "authority": authority,
            "policy": dict(policy or {}),
        }
        with self.__writer.transaction() as tx:
            envelope = self._envelope("assessment.scope.declare", scope_ref, payload, request_key, selected_actor, expected_version=0)
            prior = self.__writer.get_receipt(request_key)
            receipt = self.__writer.mutate(envelope, event_type="assessment.scope.declared", result_ref=ResourceRef(scope_ref.authority, scope_ref.kind, scope_ref.id, "rev-1"), before_refs=(parent_ref,), effects={"criterion_refs": tuple(criterion_refs), "protocol": protocol, "logical_parent": True}, stream=ASSESSMENT_STREAM, transaction=tx)
            if prior is None:
                for child_ref, child_payload in child_specs:
                    self.__writer.put_identity(child_ref, child_payload, version=1, transaction=tx)
                    self.__writer.put_reference(child_ref, transaction=tx)
        return self.get_scope(scope_ref)

    create_scope = declare_scope

    def amend_required_scope(self, scope: Any, *, parent_obligation: Any,
                             criteria: Sequence[Any], owner_authorization: Any,
                             logical_request_key: str,
                             actor: Optional[AuthenticatedActor] = None) -> AssessmentScope:
        """Append a changed owner requirement to the same pending-task gate.

        The canonical orchestrator's exact signed report is the capability.
        Old scope/input/result/decision records and all allowance debits remain.
        This uses the existing scope declaration mutation/event, not a new gate.
        """
        expected = _ref(scope, "expected scope")
        parent = self._current_ref(_ref(parent_obligation), "current task")
        selected = self._actor(actor)
        key = self._key(logical_request_key, "scope amendment")
        auth_ref = self._current_ref(_ref(owner_authorization), "owner authorization")
        auth = self.__writer.get_identity(auth_ref)
        if auth_ref.kind != "wrk.report" or auth is None:
            raise AssessmentAuthorityError("scope amendment requires an exact owner report")
        value = auth.payload.get("value", {})
        task = self.__writer.get_identity(parent)
        if parent.kind != "work.task" or task.payload.get("lifecycle") == "completed":
            raise AssessmentAuthorityError("only an uncompleted canonical task may change requirements")
        project = self.__writer.get_identity(_ref(task.payload["project_ref"]))
        root_pin = project.payload.get("metadata", {}).get("otto_orchestrator", {}).get("assignment_ref")
        root = self.__writer.get_identity(_ref(auth.payload.get("assignment")))
        receipt = self.__writer.get_receipt(value.get("logical_request_key", ""))
        events = self.reader.list_events(subjects=(auth_ref,))
        if (root is None or root_pin != root.ref.to_dict()
                or auth.payload.get("assignment") != root.ref.to_dict()
                or root.payload.get("role") != "orchestrator"
                or root.payload.get("principal") != selected.actor
                or auth.payload.get("generation") != root.payload.get("generation")
                or receipt is None or receipt.status.value != "committed"
                or receipt.result_ref != auth_ref
                or not any(e.event_id in receipt.event_ids and e.actor == selected for e in events)):
            raise AssessmentAuthorityError("scope amendment lacks the current authenticated orchestrator")
        refs = tuple(self._current_ref(_ref(x), "criterion") for x in criteria)
        if not refs or len(set(refs)) != len(refs) or any(x.kind != CRITERION_KIND for x in refs):
            raise AssessmentError("exact distinct criterion references required")
        authorized = {"schema": "otto.owner-scope-amendment.v1",
                      "scope_ref": expected.to_dict(), "task_ref": parent.to_dict(),
                      "criterion_refs": [x.to_dict() for x in refs], "request_key": key}
        if any(value.get(k) != v for k, v in authorized.items()) or not value.get("reason"):
            raise AssessmentAuthorityError("owner report does not authorize these exact amended pins")
        current = self.get_scope(_stable_ref(expected))
        amendment = {"previous_scope_ref": expected.to_dict(), "owner_authorization_ref": auth_ref.to_dict(),
                     "request_key": key}
        if current.ref != expected:
            if (self.__writer.get_receipt(key) is not None and current.parent_obligation_ref == parent
                    and current.criterion_refs == refs and current.payload.get("owner_amendment") == amendment):
                return current
            raise StaleAssessmentError("scope amendment expected revision is stale")
        if (not expected.revision or not _same_identity(current.parent_obligation_ref, parent)
                or current.parent_obligation_ref == parent or current.policy.get("required_for_completion") is not True):
            raise AssessmentError("scope amendment requires the same required task at a new canonical revision")
        decisions = self.reader.find_identity_refs(kind=DECISION_KIND,
            payload_matches={("parent_obligation_ref", "id"): parent.id})
        for ref in decisions:
            decision = self.get_decision(ref)
            if decision.result_ref is not None and _same_identity(self.get_result(decision.result_ref).scope_ref, expected):
                raise AssessmentAuthorityError("an accepted or disposed scope cannot be amended")
        payload = dict(current.payload, parent_obligation_ref=parent, criterion_refs=refs,
                       owner_amendment=amendment)
        result_ref = ResourceRef(expected.authority, expected.kind, expected.id, "rev-" + str(current.version + 1))
        with self.__writer.transaction() as tx:
            self.__writer.mutate(self._envelope("assessment.scope.declare", _stable_ref(expected), payload,
                key, selected, expected_version=current.version, expected_revision=expected.revision),
                event_type="assessment.scope.declared", result_ref=result_ref,
                before_refs=(expected, current.parent_obligation_ref, auth_ref),
                effects={"criterion_refs": refs, "protocol": current.protocol, "logical_parent": True,
                         "owner_amendment": amendment, "accepts": False}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_scope(result_ref)


    def freeze_input(
        self,
        scope: Any,
        *,
        packet: Mapping[str, Any],
        consumed_refs: Sequence[Any] = (),
        input_ref: Any = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> InputPacket:
        scope_record = self.get_scope(scope)
        if not isinstance(packet, Mapping):
            raise AssessmentError("packet must be a mapping")
        consumed = tuple(self._current_ref(_ref(value, "consumed input"), "consumed input") for value in consumed_refs)
        request_key = self._key(logical_request_key, "input")
        ref = self._stable_local(input_ref or request_key, INPUT_KIND)
        payload = {"record_type": INPUT_KIND, "schema_revision": SCHEMA_REVISION, "scope_ref": scope_record.ref, "consumed_refs": consumed, "packet": _safe(dict(packet)), "packet_digest": _digest(packet)}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.input.freeze", ref, payload, request_key, self._actor(actor), expected_version=0), event_type="assessment.input.frozen", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), before_refs=(scope_record.ref,), effects={"scope_ref": scope_record.ref, "consumed_refs": consumed}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_input(receipt.result_ref or ref)

    create_input_packet = freeze_input

    # ---- selection and assessment ------------------------------------------------

    def select_candidate(
        self,
        scope: Any,
        *,
        candidate: Any,
        criterion: Any,
        rationale: str,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> CandidateSelection:
        scope_record = self.get_scope(scope)
        candidate_ref = self._current_ref(_ref(candidate, "candidate"), "candidate")
        candidate_identity = self.__writer.get_identity(candidate_ref)
        if candidate_identity is None:  # pragma: no cover - guarded by _current_ref
            raise AssessmentNotFoundError("candidate identity is not admitted")
        self._validate_candidate(candidate_identity.payload)
        criterion_ref = self._current_ref(_ref(criterion, "criterion"), "criterion")
        self._require_criterion(scope_record, criterion_ref)
        request_key = self._key(logical_request_key, "selection")
        ref = self._stable_local(request_key, SELECTION_KIND)
        payload = {"record_type": SELECTION_KIND, "schema_revision": SCHEMA_REVISION, "scope_ref": scope_record.ref, "candidate_ref": candidate_ref, "criterion_ref": criterion_ref, "rationale": _opaque(rationale, "rationale"), "author": self._actor(actor).actor, "accepts": False}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.candidate.select", ref, payload, request_key, self._actor(actor), expected_version=0), event_type="assessment.candidate.selected", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), before_refs=(scope_record.ref, candidate_ref, criterion_ref), effects={"selection_only": True, "accepts": False}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_selection(receipt.result_ref or ref)

    choose_candidate = select_candidate

    def assess(
        self,
        scope: Any,
        *,
        candidate: Any,
        criterion: Any,
        input_packet: Any,
        verdict: Any,
        guidance: Optional[Mapping[str, Any]] = None,
        protocol_result: Optional[Mapping[str, Any]] = None,
        findings: Sequence[Mapping[str, Any]] = (),
        limit_pool: Any,
        declared_units: int = 1,
        actual_units: Optional[int] = None,
        route: str = "normal",
        role: str = "review",
        operation_payload: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> AssessmentResult:
        scope_record = self.get_scope(scope)
        candidate_ref = self._current_ref(_ref(candidate, "candidate"), "candidate")
        candidate_identity = self.__writer.get_identity(candidate_ref)
        if candidate_identity is None:  # pragma: no cover - guarded by _current_ref
            raise AssessmentNotFoundError("candidate identity is not admitted")
        self._validate_candidate(candidate_identity.payload)
        criterion_ref = self._current_ref(_ref(criterion, "criterion"), "criterion")
        self._require_criterion(scope_record, criterion_ref)
        packet = self.get_input(input_packet)
        self._validate_input_packet(packet)
        selected_verdict = verdict if isinstance(verdict, Verdict) else Verdict(str(verdict).upper())
        route = _opaque(route, "route")
        role = _opaque(role, "role")
        request_key = self._key(logical_request_key, "assessment")
        result_ref = ResourceRef(self.__writer.authority, RESULT_KIND, request_key)
        parent_ref = scope_record.parent_obligation_ref
        pool_ref = self._stable_local(limit_pool, "limit") if isinstance(limit_pool, str) else _ref(limit_pool, "limit pool")
        pool_ref = ResourceRef(pool_ref.authority, pool_ref.kind, pool_ref.id)
        reservation_ref = ResourceRef(self.__writer.authority, "reservation", request_key + "-reservation")
        operation_key = request_key + "-invocation"
        invocation_ref = ResourceRef(self.__writer.authority, INVOCATION_KIND, request_key)
        body_for_digest = {"scope": scope_record.ref, "candidate": candidate_ref, "criterion": criterion_ref, "input": packet.ref, "verdict": selected_verdict.value, "guidance": dict(guidance or {}), "protocol_result": dict(protocol_result or {}), "findings": [_safe(item) for item in findings], "pool": pool_ref, "declared_units": declared_units, "actual_units": actual_units, "route": route, "role": role, "operation_payload": dict(operation_payload or {})}
        selected_actor = self._actor(actor)
        parent_payload = {"record_type": RESULT_KIND, "schema_revision": SCHEMA_REVISION, "scope_ref": scope_record.ref, "parent_obligation_ref": parent_ref, "criterion_ref": criterion_ref, "candidate_ref": candidate_ref, "input_packet_ref": packet.ref, "verdict": selected_verdict.value, "guidance": _safe(dict(guidance or {})), "protocol_result": _safe(dict(protocol_result or {})), "route": route, "role": role, "invocation_ref": invocation_ref, "reservation_ref": reservation_ref, "finding_refs": (), "correction_refs": (), "accepted": False}
        with self.__writer.transaction() as tx:
            envelope = self._envelope("assessment.run", result_ref, body_for_digest, request_key, selected_actor, expected_version=0)
            prior = self.__writer.get_receipt(request_key)
            if prior is not None:
                validate_replay(prior, envelope)
                return self.get_result(prior.result_ref or result_ref)
            reservation = self.limits.reserve(pool_ref, reservation_ref, declared_units, logical_request_key=request_key + "-reserve", actor=selected_actor, transaction=tx)
            request = OperationRequest("assessment.invocation", "assessment.invocation.v1", ResourceRef(self.__writer.authority, "assessment-adapter", route), selected_actor, operation_key, _digest({"operation": operation_key, "payload": body_for_digest}), {"assessment_ref": result_ref, "route": route, "role": role, **dict(operation_payload or {})}, invocation_ref, parent_ref)
            operation = self.operations.prepare(request, transaction=tx)
            state = OperationState.UNKNOWN if selected_verdict is Verdict.UNKNOWN else (OperationState.FAILED if selected_verdict is Verdict.REWORK and bool((protocol_result or {}).get("invocation_failed")) else OperationState.COMMITTED)
            if state is OperationState.UNKNOWN:
                operation = self.operations.record_outcome(operation, state, {"verdict": selected_verdict.value, "guidance": dict(guidance or {})}, transition_key=operation_key + "-unknown", transaction=tx)
            else:
                operation = self.operations.record_outcome(operation, state, {"verdict": selected_verdict.value, "protocol_result": dict(protocol_result or {})}, transition_key=operation_key + "-outcome", transaction=tx)
            charged = declared_units if actual_units is None else actual_units
            settled = self.limits.settle(reservation, charged, logical_request_key=request_key + "-settle", actor=selected_actor, transaction=tx)
            reservation_stable = ResourceRef(self.__writer.authority, "reservation", reservation_ref.id)
            invocation_payload = {"record_type": INVOCATION_KIND, "schema_revision": SCHEMA_REVISION, "operation_ref": operation.operation_ref, "reservation_ref": reservation_stable, "route": route, "role": role, "state": operation.state.value, "declared_units": declared_units, "actual_units": charged, "result": _safe(operation.result), "parent_obligation_ref": parent_ref}
            self.__writer.put_identity(invocation_ref, invocation_payload, version=1, transaction=tx)
            self.__writer.put_reference(invocation_ref, transaction=tx)
            if failure_injector is not None:
                failure_injector("after-invocation")
            finding_refs: list[ResourceRef] = []
            for index, spec in enumerate(findings):
                finding_refs.append(self._write_finding(tx, result_ref, parent_ref, index, spec, selected_verdict))
                if failure_injector is not None:
                    failure_injector("after-finding")
            parent_payload["invocation_ref"] = invocation_ref
            parent_payload["finding_refs"] = tuple(finding_refs)
            # Rebuild the envelope after composing children: CommandEnvelope
            # copies its payload, so a pre-child envelope would lose the
            # finding links even though the transaction remained atomic.
            envelope = self._envelope("assessment.run", result_ref, body_for_digest, request_key, selected_actor, expected_version=0)
            receipt = self.__writer.mutate(envelope, identity_payload=parent_payload, event_type="assessment.completed", result_ref=ResourceRef(self.__writer.authority, RESULT_KIND, result_ref.id, "rev-1"), before_refs=(scope_record.ref, parent_ref, candidate_ref, criterion_ref, packet.ref), effects={"logical_parent": True, "invocation_ref": invocation_ref, "reservation_ref": reservation_stable, "finding_refs": tuple(finding_refs), "verdict": selected_verdict.value, "protocol": scope_record.protocol}, stream=ASSESSMENT_STREAM, transaction=tx)
            if failure_injector is not None:
                failure_injector("after-parent")
        return self.get_result(receipt.result_ref or result_ref)

    run = assess
    assess_candidate = assess
    resume = assess

    # ---- corrections, findings, decisions --------------------------------------

    def create_correction(
        self,
        result: Any,
        *,
        instruction: str,
        finding_refs: Sequence[Any] = (),
        owner: Optional[str] = None,
        evidence_refs: Sequence[Any] = (),
        fix_candidate: Any = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> Correction:
        key = self._key(logical_request_key, "correction")
        selected_actor = self._actor(actor)
        selected_owner = None if owner is None else _opaque(owner, "correction owner")
        selected_findings = tuple(_logical_ref(value, "finding") for value in finding_refs)
        evidence = tuple(_ref(value, "correction evidence") for value in evidence_refs)
        candidate_ref = None if fix_candidate is None else _ref(fix_candidate, "fix candidate")
        request_payload = {
            "result": _safe(_logical_ref(result, "result")),
            "instruction": instruction,
            "finding_refs": tuple(_safe(value) for value in selected_findings),
            "owner": selected_owner,
            "evidence_refs": tuple(_safe(value) for value in evidence),
            "fix_candidate_ref": _safe(candidate_ref),
        }
        prior = self.__writer.get_receipt(key)
        if prior is not None:
            replay_target = prior.target
            envelope = self._envelope(
                "assessment.correction.create", replay_target, request_payload, key,
                selected_actor, expected_version=0, expected_revision=replay_target.revision,
            )
            self.__writer.mutate(
                envelope, event_type="assessment.correction.created", result_ref=prior.result_ref,
                stream=ASSESSMENT_STREAM,
            )
            correction_target = prior.result_ref or replay_target
            return self.get_correction(ResourceRef(correction_target.authority, correction_target.kind, correction_target.id))
        accountable = selected_owner is not None or bool(evidence) or candidate_ref is not None
        if accountable and (selected_owner is None or not evidence or candidate_ref is None or not selected_findings):
            raise AssessmentError("accountable corrections require an owner, finding, fix candidate, and evidence")
        correction_ref = ResourceRef(self.__writer.authority, CORRECTION_KIND, key)
        with self.__writer.transaction() as tx:
            current = self.get_result(result)
            if current.verdict is not Verdict.REWORK:
                raise AssessmentStateError("only a REWORK result creates a correction")
            refs = selected_findings or tuple(finding.ref for finding in current.findings if not finding.resolved)
            if accountable and not refs:
                raise AssessmentError("accountable corrections require an originating finding")
            findings: list[Finding] = []
            for finding_ref in refs:
                self._current_ref(finding_ref, "finding")
                finding = self.get_finding(finding_ref)
                if not _same_identity(finding.result_ref, current.ref) or not _same_identity(finding.parent_obligation_ref, current.parent_obligation_ref):
                    raise AssessmentError("correction finding is outside the exact origin result and parent")
                if finding.resolved:
                    raise AssessmentStateError("a resolved finding cannot start a new correction")
                if finding.correction_ref is not None:
                    raise AssessmentStateError("finding already has a correction backlink")
                findings.append(finding)

            owner_text = None if selected_owner is None else selected_owner
            evidence_current: tuple[ResourceRef, ...] = ()
            fix_ref: Optional[ResourceRef] = None
            if accountable:
                evidence_current = tuple(self._current_ref(value, "correction evidence") for value in evidence)
                fix_ref = self._current_ref(candidate_ref, "fix candidate")
                candidate_identity = self.__writer.get_identity(fix_ref)
                if candidate_identity is None:
                    raise AssessmentNotFoundError("fix candidate identity is not admitted")
                self._validate_candidate(candidate_identity.payload)
                if fix_ref == current.candidate_ref:
                    raise AssessmentStateError("fix candidate must be a distinct current candidate revision")
                candidate_parent = candidate_identity.payload.get("parent_obligation_ref")
                if candidate_parent is not None and not _same_identity(self._payload_ref(candidate_parent), current.parent_obligation_ref):
                    raise AssessmentError("fix candidate belongs to another parent obligation")
                if not self._candidate_allows_criterion(candidate_identity.payload, current.criterion_ref):
                    raise AssessmentError("fix candidate does not carry the correction criterion")
                semantic_refs = self._candidate_semantic_refs(candidate_identity.payload)
                if not set(evidence_current).intersection(semantic_refs):
                    raise AssessmentError("correction evidence must be pinned in the fix candidate inputs")

            stable_result_ref = _stable_ref(current.ref)
            payload = {
                "record_type": CORRECTION_KIND, "schema_revision": SCHEMA_REVISION,
                "result_ref": stable_result_ref,
                "parent_obligation_ref": current.parent_obligation_ref,
                "finding_refs": tuple(_stable_ref(item.ref) for item in findings),
                "instruction": _opaque(instruction, "instruction"), "status": "open",
                "owner": owner_text, "scope_ref": current.scope_ref,
                "criterion_ref": current.criterion_ref, "origin_candidate_ref": current.candidate_ref,
                "origin_input_packet_ref": current.input_packet_ref,
                "fix_candidate_ref": fix_ref, "evidence_refs": evidence_current,
                "retest_result_ref": None, "decision_ref": None, "resolved_at": None,
            }
            result_payload = dict(current.payload)
            existing_corrections = tuple(self._payload_ref(item) for item in result_payload.get("correction_refs", ()))
            result_payload["correction_refs"] = existing_corrections + (_stable_ref(correction_ref),)
            link_payload = {"result": _safe(stable_result_ref), "correction": _safe(_stable_ref(correction_ref))}
            receipt = self.__writer.mutate(
                self._envelope("assessment.correction.create", correction_ref, request_payload, key, selected_actor, expected_version=0),
                identity_payload=payload, event_type="assessment.correction.created",
                result_ref=ResourceRef(self.__writer.authority, CORRECTION_KIND, key, "rev-1"),
                before_refs=(current.ref, current.parent_obligation_ref),
                effects={"result_ref": current.ref, "finding_refs": tuple(item.ref for item in findings), "parent_obligation_ref": current.parent_obligation_ref, "request_payload": request_payload},
                stream=ASSESSMENT_STREAM, transaction=tx,
            )
            if failure_injector is not None:
                failure_injector("after-correction-create")
            self.__writer.mutate(
                self._envelope("assessment.result.link-correction", current.ref, link_payload, key + "-result", selected_actor, expected_version=current.version, expected_revision=current.ref.revision),
                identity_payload=result_payload, event_type="assessment.result.correction-linked",
                effects={"correction_ref": _stable_ref(correction_ref), "parent_obligation_ref": current.parent_obligation_ref, "request_payload": link_payload},
                stream=ASSESSMENT_STREAM, transaction=tx,
            )
            if failure_injector is not None:
                failure_injector("after-result-link")
            for index, finding in enumerate(findings):
                target = finding.ref
                finding_payload = dict(finding.payload)
                finding_payload["correction_ref"] = _stable_ref(correction_ref)
                finding_link = {"finding": _safe(_stable_ref(target)), "correction": _safe(_stable_ref(correction_ref))}
                link_key = key + "-finding-" + str(index)
                self.__writer.mutate(
                    self._envelope("assessment.finding.link-correction", target, finding_link, link_key, selected_actor, expected_version=finding.version, expected_revision=target.revision),
                    identity_payload=finding_payload, event_type="assessment.finding.correction-linked",
                    before_refs=(current.ref, target), after_refs=(_stable_ref(correction_ref),),
                    effects={"correction_ref": _stable_ref(correction_ref), "request_payload": finding_link},
                    stream=ASSESSMENT_STREAM, transaction=tx,
                )
                if failure_injector is not None:
                    failure_injector("after-finding-link")
        return self.get_correction(receipt.result_ref or correction_ref)

    def resolve_correction(
        self,
        correction: Any,
        *,
        retest_result: Any,
        decision: Any,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> Correction:
        """Atomically resolve one accountable correction against a precise PASS."""
        key = self._key(logical_request_key, "correction-resolve")
        selected_actor = self._actor(actor)
        correction_ref = _ref(correction, "correction")
        retest_ref = _ref(retest_result, "retest result")
        decision_ref = _ref(decision, "decision")
        if correction_ref.revision is None or retest_ref.revision is None or decision_ref.revision is None:
            raise StaleAssessmentError("resolution requires pinned current correction, retest, and decision refs")
        request_payload = {
            "correction": _safe(correction_ref),
            "retest_result": _safe(retest_ref),
            "decision": _safe(decision_ref),
        }
        prior = self.__writer.get_receipt(key)
        if prior is not None:
            envelope = self._envelope(
                "assessment.correction.resolve", prior.target, request_payload, key,
                selected_actor,
                expected_version=self._replay_version(prior.target.revision, prior.result_ref),
                expected_revision=prior.target.revision,
            )
            self.__writer.mutate(envelope, event_type="assessment.correction.resolved", result_ref=prior.result_ref, stream=ASSESSMENT_STREAM)
            return self.get_correction(ResourceRef(prior.target.authority, prior.target.kind, prior.target.id))

        with self.__writer.transaction() as tx:
            current = self.get_correction(correction_ref)
            if current.status != "open":
                raise AssessmentStateError("only an open correction can be resolved")
            if not current.owner or not current.evidence_refs or current.fix_candidate_ref is None or not current.finding_refs:
                raise AssessmentStateError("historical or incomplete corrections remain explicitly unresolved")
            if current.scope_ref is None or current.criterion_ref is None or current.origin_candidate_ref is None or current.origin_input_packet_ref is None:
                raise AssessmentStateError("correction lacks exact origin lineage")

            # Validate every relevant pin while holding the same owner
            # transaction that commits the resolution.
            self._current_ref(current.ref, "correction")
            self._current_ref(current.scope_ref, "scope")
            self._current_ref(current.criterion_ref, "criterion")
            self._current_ref(current.origin_candidate_ref, "origin candidate")
            self._current_ref(current.origin_input_packet_ref, "origin input packet")
            fix_candidate_ref = self._current_ref(current.fix_candidate_ref, "fix candidate")
            evidence_refs = tuple(self._current_ref(value, "correction evidence") for value in current.evidence_refs)
            origin = self.get_result(current.result_ref)
            if origin.verdict is not Verdict.REWORK:
                raise AssessmentStateError("correction origin is no longer the recorded REWORK result")
            if not _same_identity(origin.parent_obligation_ref, current.parent_obligation_ref):
                raise AssessmentError("correction parent no longer matches its origin")
            if not _same_identity(origin.scope_ref, current.scope_ref) or not _same_identity(origin.criterion_ref, current.criterion_ref):
                raise AssessmentError("correction scope or criterion differs from its origin")
            if origin.candidate_ref != current.origin_candidate_ref or origin.input_packet_ref != current.origin_input_packet_ref:
                raise StaleAssessmentError("correction origin candidate or input lineage changed")
            if not any(_same_identity(value, current.ref) for value in origin.correction_refs):
                raise AssessmentStateError("origin result does not link this correction")
            self._validate_candidate(self.__writer.get_identity(fix_candidate_ref).payload)

            retest = self.get_result(retest_ref)
            if retest.ref == origin.ref:
                raise AssessmentStateError("retest must be a distinct later assessment result")
            if retest.verdict is not Verdict.PASS:
                raise AssessmentStateError("only a PASS retest can resolve a correction")
            if not _same_identity(retest.parent_obligation_ref, current.parent_obligation_ref):
                raise AssessmentError("retest belongs to another parent obligation")
            if not _same_identity(retest.scope_ref, current.scope_ref) or not _same_identity(retest.criterion_ref, current.criterion_ref):
                raise AssessmentError("retest scope or criterion differs from the correction origin")
            if retest.candidate_ref != fix_candidate_ref:
                raise AssessmentError("retest did not consume the correction's exact fix candidate")
            if retest.input_packet_ref == current.origin_input_packet_ref:
                raise AssessmentError("retest must consume a distinct corrected input packet")
            self._current_ref(retest.candidate_ref, "retest candidate")
            self._validate_candidate(self.__writer.get_identity(retest.candidate_ref).payload)
            packet = self.get_input(retest.input_packet_ref)
            self._validate_input_packet(packet)
            if not _same_identity(packet.scope_ref, current.scope_ref):
                raise AssessmentError("retest input packet belongs to another scope")
            if not set(evidence_refs).issubset(set(packet.consumed_refs)):
                raise AssessmentError("retest input packet does not consume every pinned correction evidence ref")
            if any(not finding.resolved for finding in retest.findings):
                raise AssessmentStateError("required retest findings remain unresolved")
            fix_identity = self.__writer.get_identity(fix_candidate_ref)
            if fix_identity is None:
                raise AssessmentNotFoundError("fix candidate identity is not admitted")
            if not set(evidence_refs).intersection(self._candidate_semantic_refs(fix_identity.payload)):
                raise AssessmentError("fix candidate no longer carries correction evidence")
            if not self._candidate_allows_criterion(fix_identity.payload, current.criterion_ref):
                raise AssessmentError("fix candidate does not carry the correction criterion")

            selected_findings: list[Finding] = []
            for finding_ref in current.finding_refs:
                self._current_ref(finding_ref, "origin finding")
                finding = self.get_finding(finding_ref)
                if not _same_identity(finding.result_ref, origin.ref) or not _same_identity(finding.parent_obligation_ref, current.parent_obligation_ref):
                    raise AssessmentError("correction finding no longer matches the exact origin")
                if finding.correction_ref is None or not _same_identity(finding.correction_ref, current.ref):
                    raise AssessmentStateError("origin finding lacks this correction's backlink")
                if not finding.resolved:
                    raise AssessmentStateError("origin findings must be closed before correction resolution")
                if not set(evidence_refs).issubset(set(finding.evidence_refs)):
                    raise AssessmentStateError("origin finding closure does not cite all correction evidence")
                selected_findings.append(finding)

            decision_record = self.get_decision(decision_ref)
            if decision_record.ref.authority != self.__writer.authority or decision_record.ref.kind != DECISION_KIND:
                raise AssessmentAuthorityError("decision is outside the current assessment owner")
            if decision_record.result_ref is None or not _same_identity(decision_record.result_ref, retest.ref):
                raise AssessmentError("decision is not for the exact retest result")
            if decision_record.candidate_ref != retest.candidate_ref or decision_record.criterion_ref != retest.criterion_ref:
                raise AssessmentError("decision candidate or criterion differs from the retest")
            if not _same_identity(decision_record.parent_obligation_ref, current.parent_obligation_ref):
                raise AssessmentError("decision parent differs from the correction")
            if decision_record.disposition != Disposition.ACCEPT.value:
                raise AssessmentStateError("only an exact accept decision can resolve a correction")
            if decision_record.payload.get("unknown_disposition") or decision_record.payload.get("no_review"):
                raise AssessmentStateError("unknown disposition and no-review decisions cannot resolve corrections")
            if not set(evidence_refs).issubset(set(decision_record.evidence_refs)):
                raise AssessmentAuthorityError("accepted decision does not cite all correction evidence")
            scope = self.get_scope(current.scope_ref)
            self._check_approver(scope, decision_record.author, decision_record.authority)
            self._verify_decision_actor(decision_record)

            if failure_injector is not None:
                failure_injector("after-resolution-validation")
            # Recheck the complete semantic pin set immediately before the
            # owner mutation.  The transaction serializes other writers; this
            # second fence also catches an owner-side change surfaced by a
            # reentrant adapter or test injector during validation.
            self._current_ref(current.ref, "correction")
            self._current_ref(current.scope_ref, "scope")
            self._current_ref(current.criterion_ref, "criterion")
            self._current_ref(current.origin_candidate_ref, "origin candidate")
            self._current_ref(current.origin_input_packet_ref, "origin input packet")
            self._current_ref(fix_candidate_ref, "fix candidate")
            self._validate_candidate(self.__writer.get_identity(fix_candidate_ref).payload)
            for evidence_ref in evidence_refs:
                self._current_ref(evidence_ref, "correction evidence")
            self._current_ref(retest.ref, "retest result")
            self._validate_input_packet(self.get_input(retest.input_packet_ref))
            self._current_ref(decision_record.ref, "accepted decision")

            payload = dict(current.payload)
            payload.update({
                "status": "resolved", "retest_result_ref": retest.ref,
                "decision_ref": decision_record.ref, "resolution_evidence_refs": evidence_refs,
                "resolved_by": selected_actor.actor,
            })
            if failure_injector is not None:
                failure_injector("before-resolution-write")
            receipt = self.__writer.mutate(
                self._envelope("assessment.correction.resolve", current.ref, request_payload, key, selected_actor, expected_version=current.version, expected_revision=current.ref.revision),
                identity_payload=payload, event_type="assessment.correction.resolved",
                result_ref=ResourceRef(current.ref.authority, current.ref.kind, current.ref.id, "rev-" + str(current.version + 1)),
                before_refs=(current.ref, origin.ref, retest.ref, decision_record.ref) + tuple(item.ref for item in selected_findings),
                after_refs=(current.ref, retest.ref, decision_record.ref) + evidence_refs,
                effects={"status": "resolved", "retest_result_ref": retest.ref, "decision_ref": decision_record.ref, "evidence_refs": evidence_refs},
                stream=ASSESSMENT_STREAM, transaction=tx,
            )
            if failure_injector is not None:
                failure_injector("after-resolution-write")
        return self.get_correction(receipt.result_ref or current.ref)

    request_correction = create_correction

    def close_finding(
        self,
        finding: Any,
        *,
        evidence_refs: Sequence[Any] = (),
        test_only: bool = False,
        rationale: str = "",
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Finding:
        key = self._key(logical_request_key, "finding-close")
        selected_actor = self._actor(actor)
        request_payload = {
            "finding": _safe(_logical_ref(finding, "finding")),
            "evidence_refs": tuple(_safe(_logical_ref(value, "evidence")) for value in evidence_refs),
            "test_only": bool(test_only),
            "rationale": rationale,
        }
        prior = self.__writer.get_receipt(key)
        if prior is not None:
            replay_target = prior.target
            replay_version = None
            if replay_target.revision is not None and replay_target.revision.startswith("rev-"):
                try:
                    replay_version = int(replay_target.revision.removeprefix("rev-"))
                except ValueError:
                    replay_version = None
            if replay_version is None and prior.result_ref is not None and prior.result_ref.revision and prior.result_ref.revision.startswith("rev-"):
                try:
                    replay_version = max(0, int(prior.result_ref.revision.removeprefix("rev-")) - 1)
                except ValueError:
                    replay_version = None
            envelope = self._envelope(
                "assessment.finding.close", replay_target, request_payload, key, selected_actor,
                expected_version=replay_version, expected_revision=replay_target.revision,
            )
            receipt = self.__writer.mutate(
                envelope, event_type="assessment.finding.closed", result_ref=prior.result_ref,
                stream=ASSESSMENT_STREAM,
            )
            unpinned = ResourceRef(replay_target.authority, replay_target.kind, replay_target.id)
            return self.get_finding(unpinned)
        current = self.get_finding(finding)
        result = self.get_result(current.result_ref)
        if current.subjective and test_only:
            raise AssessmentAuthorityError("test-only evidence cannot clear a subjective finding")
        if result.verdict is Verdict.UNKNOWN and test_only:
            raise AssessmentAuthorityError("test-only evidence cannot clear an UNKNOWN result")
        refs = tuple(self._current_ref(_ref(value, "evidence"), "evidence") for value in evidence_refs)
        payload = dict(current.payload)
        payload.update({"status": "closed", "evidence_refs": refs, "closure_rationale": rationale, "closure_test_only": bool(test_only)})
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.finding.close", current.ref, request_payload, key, selected_actor, expected_version=current.version, expected_revision=current.ref.revision), identity_payload=payload, event_type="assessment.finding.closed", effects={"finding_ref": current.ref, "evidence_refs": refs, "test_only": bool(test_only)}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_finding(receipt.result_ref or current.ref)

    resolve_finding = close_finding

    def accept(
        self,
        result: Any,
        *,
        author: Optional[str] = None,
        authority: Optional[str] = None,
        rationale: str,
        disposition: Any = Disposition.ACCEPT,
        evidence_refs: Sequence[Any] = (),
        return_condition: Optional[str] = None,
        candidate: Any = None,
        criterion: Any = None,
        review_evidence: Sequence[Any] = (),
        test_only: bool = False,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Decision:
        current = self.get_result(result)
        scope = self.get_scope(current.scope_ref)
        if candidate is not None and self._current_ref(_ref(candidate, "candidate"), "candidate") != current.candidate_ref:
            raise StaleAssessmentError("approval candidate is not the exact consumed candidate revision")
        if criterion is not None and self._current_ref(_ref(criterion, "criterion"), "criterion") != current.criterion_ref:
            raise StaleAssessmentError("approval criterion is not the exact consumed criterion revision")
        if current.verdict is not Verdict.PASS:
            raise AssessmentStateError("only PASS can be accepted; REWORK and UNKNOWN remain open")
        if any(not finding.resolved for finding in current.findings):
            raise AssessmentStateError("all objective and subjective findings must be closed before acceptance")
        selected_actor = self._actor(actor)
        if author is not None and author != selected_actor.actor:
            raise AssessmentAuthorityError("decision author must be the authenticated command actor")
        approver = selected_actor.actor
        approval_authority = authority or scope.authority or selected_actor.authority
        self._check_approver(scope, approver, approval_authority)
        review_refs = tuple(self._current_ref(_ref(value, "review evidence"), "review evidence") for value in review_evidence)
        if scope.review_required and current.payload.get("role") != "review" and not review_refs:
            raise AssessmentAuthorityError("required review evidence is missing")
        if test_only and current.findings:
            raise AssessmentAuthorityError("test-only evidence cannot clear subjective or unresolved findings")
        decision_value = disposition if isinstance(disposition, Disposition) else Disposition(str(disposition))
        key = self._key(logical_request_key, "accept")
        decision_ref = ResourceRef(self.__writer.authority, DECISION_KIND, key)
        evidence = tuple(self._current_ref(_ref(value, "evidence"), "evidence") for value in evidence_refs)
        evidence_digests = []
        for evidence_ref in evidence:
            verified = verify_dat_evidence(self._evidence_store, evidence_ref, actor=selected_actor,
                                           scopes=self._evidence_scopes(current.parent_obligation_ref))
            if verified.get("state") == "verified":
                evidence_digests.append(verified)
        payload = {"record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": current.parent_obligation_ref, "result_ref": current.ref, "candidate_ref": current.candidate_ref, "criterion_ref": current.criterion_ref, "author": approver, "authority": approval_authority, "rationale": _opaque(rationale, "rationale"), "disposition": decision_value.value, "evidence_refs": evidence, "evidence_digests": tuple(evidence_digests), "review_evidence": review_refs, "return_condition": return_condition}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.accept", decision_ref, payload, key, selected_actor, expected_version=0), event_type="assessment.accepted", before_refs=(current.ref, current.parent_obligation_ref, current.candidate_ref, current.criterion_ref), effects={"accepted": decision_value in (Disposition.ACCEPT, Disposition.ACCEPT_WITH_RISK), "candidate_ref": current.candidate_ref, "criterion_ref": current.criterion_ref, "authority": approval_authority}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_decision(receipt.result_ref or decision_ref)

    approve = accept

    def accept_without_review(
        self,
        scope: Any,
        *,
        candidate: Any,
        criterion: Any,
        rationale: str,
        evidence_refs: Sequence[Any] = (),
        author: Optional[str] = None,
        authority: Optional[str] = None,
        return_condition: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Decision:
        scope_record = self.get_scope(scope)
        if scope_record.review_required or not scope_record.allow_no_review:
            raise AssessmentAuthorityError("policy requires a review; no-review evidence is not admissible")
        candidate_ref = self._current_ref(_ref(candidate, "candidate"), "candidate")
        criterion_ref = self._current_ref(_ref(criterion, "criterion"), "criterion")
        self._require_criterion(scope_record, criterion_ref)
        selected_actor = self._actor(actor)
        if author is not None and author != selected_actor.actor:
            raise AssessmentAuthorityError("decision author must be the authenticated command actor")
        approver = selected_actor.actor
        approval_authority = authority or scope_record.authority or selected_actor.authority
        self._check_approver(scope_record, approver, approval_authority)
        key = self._key(logical_request_key, "no-review-accept")
        decision_ref = ResourceRef(self.__writer.authority, DECISION_KIND, key)
        evidence = tuple(self._current_ref(_ref(value, "evidence"), "evidence") for value in evidence_refs)
        payload = {"record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": scope_record.parent_obligation_ref, "result_ref": None, "candidate_ref": candidate_ref, "criterion_ref": criterion_ref, "author": approver, "authority": approval_authority, "rationale": _opaque(rationale, "rationale"), "disposition": Disposition.ACCEPT.value, "evidence_refs": evidence, "review_evidence": (), "return_condition": return_condition, "no_review": True}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.accept", decision_ref, payload, key, selected_actor, expected_version=0), event_type="assessment.accepted", before_refs=(scope_record.parent_obligation_ref, candidate_ref, criterion_ref), effects={"accepted": True, "no_review": True, "candidate_ref": candidate_ref, "criterion_ref": criterion_ref}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_decision(receipt.result_ref or decision_ref)

    def dispose_unknown(
        self,
        result: Any,
        *,
        disposition: Any,
        authority: str,
        rationale: str,
        return_condition: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Decision:
        current = self.get_result(result)
        if current.verdict is not Verdict.UNKNOWN:
            raise AssessmentStateError("only UNKNOWN results need an explicit disposition")
        scope = self.get_scope(current.scope_ref)
        selected_actor = self._actor(actor)
        self._check_approver(scope, selected_actor.actor, authority)
        value = disposition if isinstance(disposition, Disposition) else Disposition(str(disposition))
        key = self._key(logical_request_key, "unknown-disposition")
        decision_ref = ResourceRef(self.__writer.authority, DECISION_KIND, key)
        payload = {"record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": current.parent_obligation_ref, "result_ref": current.ref, "candidate_ref": current.candidate_ref, "criterion_ref": current.criterion_ref, "author": selected_actor.actor, "authority": authority, "rationale": _opaque(rationale, "rationale"), "disposition": value.value, "evidence_refs": (), "review_evidence": (), "return_condition": return_condition, "unknown_disposition": True}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.unknown.disposition", decision_ref, payload, key, selected_actor, expected_version=0), event_type="assessment.unknown.disposed", before_refs=(current.ref, current.parent_obligation_ref, current.candidate_ref, current.criterion_ref), effects={"unknown": True, "disposition": value.value, "authority": authority}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_decision(receipt.result_ref or decision_ref)

    resolve_unknown = dispose_unknown

    def record_loop_facts(
        self,
        parent_obligation: Any,
        *,
        attempt_count: int,
        unresolved_findings: int,
        exhausted_allowance: bool,
        required_approver: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> ResourceRef:
        if min(attempt_count, unresolved_findings) < 0:
            raise AssessmentError("loop facts counts must be non-negative")
        parent = self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation")
        key = self._key(logical_request_key, "loop-facts")
        target = ResourceRef(self.__writer.authority, LOOP_FACTS_KIND, key)
        payload = {"record_type": LOOP_FACTS_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": parent, "attempt_count": attempt_count, "unresolved_findings": unresolved_findings, "exhausted_allowance": bool(exhausted_allowance), "required_approver": required_approver, "inference": None}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.loop-facts.record", target, payload, key, self._actor(actor), expected_version=0), event_type="assessment.loop-facts.recorded", before_refs=(parent,), effects={"facts_only": True, "inference": None}, stream=ASSESSMENT_STREAM, transaction=tx)
        return receipt.result_ref or target

    def completion_blockers(
        self,
        parent_obligation: Any,
        *,
        candidate: Any = None,
        gate_refs: Sequence[Any] = (),
        actor: Optional[AuthenticatedActor] = None,
        evidence_store: Any = None,
        completion_evidence_refs: Sequence[Any] = (),
        completion_evidence_hashes: Any = (),
    ) -> Mapping[str, Any]:
        """Explain the finite required-scope predicate used by work completion.

        Only scopes explicitly marked ``required_for_completion`` are gates.
        The completion owner calls this inside its write transaction; ordinary
        readers may call it for a provisional explanation that is rechecked
        before a write. No assessment record or counter is changed here.
        """
        parent = _ref(parent_obligation, "parent obligation")
        if parent.authority != self.__writer.authority:
            raise AssessmentAuthorityError("parent obligation is outside the assessment owner")
        current_parent = self._current_ref(parent, "parent obligation")
        events = tuple(self.reader.list_events(stream=ASSESSMENT_STREAM, assessment_parent=current_parent))
        if len(events) > 10000:
            raise AssessmentStateError("assessment history exceeds the complete gate scan bound")
        scope_ids: dict[tuple[str, str], ResourceRef] = {}
        result_ids: dict[tuple[str, str], ResourceRef] = {}
        selection_ids: dict[tuple[str, str], ResourceRef] = {}
        for event in events:
            if event.store_authority != self.__writer.authority:
                continue
            subject = event.subject
            key = (subject.authority, subject.id)
            if event.event_type == "assessment.scope.declared" and subject.kind == SCOPE_KIND:
                scope_ids[key] = _stable_ref(subject)
            elif event.event_type == "assessment.completed" and subject.kind == RESULT_KIND:
                result_ids[key] = _stable_ref(subject)
            elif event.event_type == "assessment.candidate.selected" and subject.kind == SELECTION_KIND:
                selection_ids[key] = _stable_ref(subject)
        scopes = [self.get_scope(ref) for ref in scope_ids.values()]
        required = [scope for scope in scopes if _same_identity(scope.parent_obligation_ref, current_parent)
                    and scope.policy.get("required_for_completion") is True]
        blockers: list[dict[str, Any]] = []
        def block(code: str, message: str, scope: Optional[AssessmentScope] = None,
                  criterion: Optional[ResourceRef] = None) -> None:
            blockers.append({"code": code, "message": message,
                             "scope_ref": _ref_dict(scope.ref) if scope else None,
                             "criterion_ref": _ref_dict(criterion)})

        if not required:
            return {"required": False, "blockers": [], "accepted_decision_refs": [],
                    "scope_refs": [], "candidate_ref": None}
        if candidate is None:
            block("completion_candidate_required", "required assessment needs an exact candidate")
            return {"required": True, "blockers": blockers, "accepted_decision_refs": [],
                    "scope_refs": [_ref_dict(scope.ref) for scope in required], "candidate_ref": None}
        candidate_ref = _ref(candidate, "candidate")
        try:
            current_candidate = self._current_ref(candidate_ref, "candidate")
            if candidate_ref.revision is None or candidate_ref != current_candidate:
                raise StaleAssessmentError("candidate must be pinned to its current revision")
            candidate_identity = self.__writer.get_identity(current_candidate)
            if candidate_identity is None:
                raise AssessmentNotFoundError("candidate is not admitted")
            self._validate_candidate(candidate_identity.payload)
        except AssessmentError as exc:
            block("completion_candidate_stale", str(exc))
            return {"required": True, "blockers": blockers, "accepted_decision_refs": [],
                    "scope_refs": [_ref_dict(scope.ref) for scope in required],
                    "candidate_ref": _ref_dict(candidate_ref)}
        supplied_gates = tuple(_ref(value, "gate") for value in gate_refs)
        results = [self.get_result(ref) for ref in result_ids.values()]
        selections = [self.get_selection(ref) for ref in selection_ids.values()]
        decisions = self.list_decisions(parent_obligation=_stable_ref(current_parent))
        accepted: list[ResourceRef] = []
        evidence_states: list[str] = []
        for scope in required:
            if not scope.criterion_refs:
                block("required_scope_empty", "required scope has no declared criteria", scope)
                continue
            for criterion in scope.criterion_refs:
                try:
                    self._current_ref(criterion, "criterion")
                except AssessmentError as exc:
                    block("completion_criterion_stale", str(exc), scope, criterion)
                    continue
                selected = [row for row in selections if _same_identity(row.scope_ref, scope.ref)
                            and _same_identity(row.criterion_ref, criterion)]
                if selected and selected[-1].candidate_ref != current_candidate:
                    block("selected_candidate_mismatch", "current candidate differs from the selected candidate", scope, criterion)
                    continue
                matching = [result for result in results
                            if _same_identity(result.scope_ref, scope.ref)
                            and _same_identity(result.criterion_ref, criterion)]
                if any(not finding.resolved for result in matching for finding in result.findings):
                    block("unresolved_finding", "required criterion has an unresolved finding", scope, criterion)
                    continue
                current_results = [result for result in matching if result.candidate_ref == current_candidate]
                if not current_results:
                    block("criterion_uncovered", "required criterion has no result for the current candidate", scope, criterion)
                    continue
                result = current_results[-1]
                if result.verdict is not Verdict.PASS:
                    block("criterion_not_pass", "latest current-candidate result is not PASS", scope, criterion)
                    continue
                try:
                    packet = self.get_input(result.input_packet_ref)
                    if not _same_identity(packet.scope_ref, scope.ref):
                        raise AssessmentError("input packet belongs to another scope")
                    self._validate_input_packet(packet)
                except AssessmentError as exc:
                    block("completion_input_stale", str(exc), scope, criterion)
                    continue
                matching_decisions = [decision for decision in decisions
                                      if decision.result_ref is not None
                                      and decision.result_ref == result.ref
                                      and decision.candidate_ref == current_candidate
                                      and _same_identity(decision.criterion_ref, criterion)
                                      and decision.disposition in {Disposition.ACCEPT.value,
                                                                    Disposition.ACCEPT_WITH_RISK.value}]
                if not matching_decisions:
                    block("pass_not_accepted", "PASS result lacks an accepted owner decision", scope, criterion)
                    continue
                decision = matching_decisions[-1]
                try:
                    self._verify_decision_actor(decision)
                    self._check_approver(scope, decision.author, decision.authority)
                    for evidence in decision.evidence_refs:
                        self._current_ref(evidence, "decision evidence")
                    review_evidence = tuple(_ref(value, "review evidence") for value in
                                            decision.payload.get("review_evidence", ()))
                    if scope.review_required and result.payload.get("role") != "review":
                        if not review_evidence:
                            raise AssessmentAuthorityError("required review evidence is missing")
                        for evidence in review_evidence:
                            self._current_ref(evidence, "review evidence")
                    if decision.ref not in supplied_gates:
                        raise AssessmentStateError("accepted decision revision is missing from completion gates")
                except AssessmentError as exc:
                    block("completion_decision_invalid", str(exc), scope, criterion)
                    evidence_states.append("stale" if "stale" in str(exc).lower() else "unknown")
                    continue
                pinned_digests = decision.payload.get("evidence_digests", ())
                for evidence in decision.evidence_refs:
                    pin = next((row for row in pinned_digests
                                if isinstance(row, Mapping) and row.get("ref") == evidence.to_dict()), None)
                    if pin is None or actor is None or evidence_store is None:
                        evidence_states.append("unknown")
                        continue
                    verified = verify_dat_evidence(evidence_store, evidence, actor=actor,
                                                   scopes=self._evidence_scopes(current_parent))
                    state = str(verified.get("state", "unknown"))
                    if state == "verified" and verified.get("digest") != pin.get("digest"):
                        state = "mismatch"
                    claims = tuple(_ref(value, "completion evidence") for value in completion_evidence_refs)
                    if evidence in claims:
                        index = claims.index(evidence)
                        claimed = (completion_evidence_hashes[index]
                                   if isinstance(completion_evidence_hashes, (list, tuple))
                                   and index < len(completion_evidence_hashes) else None)
                        if claimed is not None and state == "verified" and str(claimed).lower() != verified.get("digest"):
                            state = "mismatch"
                    evidence_states.append(state)
                    if state == "mismatch":
                        block("completion_evidence_mismatch", "verified DAT evidence digest does not match", scope, criterion)
                accepted.append(decision.ref)
            cap = scope.policy.get("max_rounds")
            consumed = scope.policy.get("rounds_consumed")
            if cap is not None or consumed is not None:
                if (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1
                        or isinstance(consumed, bool) or not isinstance(consumed, int) or consumed < 0):
                    block("review_allowance_invalid", "adopted review allowance is malformed", scope)
                elif consumed >= cap and any(row["scope_ref"] == _ref_dict(scope.ref) for row in blockers):
                    block("review_allowance_exhausted", "no new review invocation is available", scope)
        return {"required": True, "blockers": blockers,
                "accepted_decision_refs": [_ref_dict(ref) for ref in accepted],
                "scope_refs": [_ref_dict(scope.ref) for scope in required],
                "candidate_ref": _ref_dict(current_candidate),
                "evidence_verification": "mismatch" if "mismatch" in evidence_states else
                                         "stale" if "stale" in evidence_states else
                                         "verified" if evidence_states and all(state == "verified" for state in evidence_states)
                                         else "unknown"}

    # ---- typed reads -------------------------------------------------------------

    def get_scope(self, target: Any) -> AssessmentScope:
        identity = self._identity(target, SCOPE_KIND)
        payload = identity.payload
        return AssessmentScope(identity.ref, self._payload_ref(payload["parent_obligation_ref"]), payload["protocol"], tuple(self._payload_ref(value) for value in payload.get("criterion_refs", ())), bool(payload.get("review_required", True)), bool(payload.get("allow_no_review", False)), payload.get("designated_approver"), payload.get("authority"), dict(payload.get("policy", {})), identity.version, payload)

    def get_input(self, target: Any) -> InputPacket:
        identity = self._identity(target, INPUT_KIND)
        payload = identity.payload
        return InputPacket(identity.ref, self._payload_ref(payload["scope_ref"]), tuple(self._payload_ref(value) for value in payload.get("consumed_refs", ())), payload.get("packet", {}), identity.version, payload)

    def get_selection(self, target: Any) -> CandidateSelection:
        identity = self._identity(target, SELECTION_KIND)
        payload = identity.payload
        return CandidateSelection(identity.ref, self._payload_ref(payload["scope_ref"]), self._payload_ref(payload["candidate_ref"]), self._payload_ref(payload["criterion_ref"]), payload["rationale"], payload["author"], identity.version, payload)

    def get_invocation(self, target: Any) -> Invocation:
        identity = self._identity(target, INVOCATION_KIND)
        payload = identity.payload
        return Invocation(identity.ref, self._payload_ref(payload["operation_ref"]), self._payload_ref(payload["reservation_ref"]), payload["route"], payload["role"], payload["state"], int(payload["declared_units"]), int(payload["actual_units"]), payload.get("result", {}), identity.version, payload)

    def get_finding(self, target: Any) -> Finding:
        identity = self._identity(target, FINDING_KIND)
        payload = identity.payload
        return Finding(identity.ref, self._payload_ref(payload["result_ref"]), self._payload_ref(payload["parent_obligation_ref"]), payload["summary"], payload.get("severity", "normal"), bool(payload.get("subjective", False)), payload.get("status", "open"), self._payload_ref(payload.get("correction_ref")) if payload.get("correction_ref") else None, tuple(self._payload_ref(value) for value in payload.get("evidence_refs", ())), identity.version, payload)

    def get_result(self, target: Any) -> AssessmentResult:
        identity = self._identity(target, RESULT_KIND)
        payload = identity.payload
        invocation = self.get_invocation(payload["invocation_ref"])
        findings = tuple(self.get_finding(value) for value in payload.get("finding_refs", ()))
        return AssessmentResult(identity.ref, self._payload_ref(payload["scope_ref"]), self._payload_ref(payload["parent_obligation_ref"]), self._payload_ref(payload["criterion_ref"]), self._payload_ref(payload["candidate_ref"]), self._payload_ref(payload["input_packet_ref"]), Verdict(payload["verdict"]), payload.get("guidance", {}), payload.get("protocol_result", {}), invocation, findings, tuple(self._payload_ref(value) for value in payload.get("correction_refs", ())), identity.version, payload)

    def get_correction(self, target: Any) -> Correction:
        identity = self._identity(target, CORRECTION_KIND)
        payload = identity.payload
        optional_ref = lambda name: self._payload_ref(payload[name]) if payload.get(name) is not None else None
        return Correction(
            identity.ref, self._payload_ref(payload["result_ref"]), self._payload_ref(payload["parent_obligation_ref"]),
            tuple(self._payload_ref(value) for value in payload.get("finding_refs", ())), payload["instruction"],
            payload.get("status", "open"), identity.version, payload,
            owner=payload.get("owner"), scope_ref=optional_ref("scope_ref"),
            criterion_ref=optional_ref("criterion_ref"), origin_candidate_ref=optional_ref("origin_candidate_ref"),
            origin_input_packet_ref=optional_ref("origin_input_packet_ref"), fix_candidate_ref=optional_ref("fix_candidate_ref"),
            evidence_refs=tuple(self._payload_ref(value) for value in payload.get("evidence_refs", ())),
            retest_result_ref=optional_ref("retest_result_ref"), decision_ref=optional_ref("decision_ref"),
        )

    def get_decision(self, target: Any) -> Decision:
        identity = self._identity(target, DECISION_KIND)
        payload = identity.payload
        result_value = payload.get("result_ref")
        return Decision(identity.ref, self._payload_ref(payload["parent_obligation_ref"]), self._payload_ref(result_value) if result_value else None, self._payload_ref(payload["candidate_ref"]), self._payload_ref(payload["criterion_ref"]), payload["author"], payload["authority"], payload["rationale"], payload["disposition"], tuple(self._payload_ref(value) for value in payload.get("evidence_refs", ())), payload.get("return_condition"), identity.version, payload)

    def list_decisions(self, *, parent_obligation: Any = None) -> Tuple[Decision, ...]:
        parent_id = None if parent_obligation is None else self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation").id
        rows = self.__writer.connection.execute("SELECT * FROM identities WHERE authority = ? AND kind = ? ORDER BY id", (self.__writer.authority, DECISION_KIND)).fetchall()
        decisions = tuple(self.get_decision(ResourceRef(row["authority"], row["kind"], row["id"])) for row in rows)
        if parent_id is not None:
            decisions = tuple(item for item in decisions if item.parent_obligation_ref.id == parent_id)
        return decisions

    # ---- internal FND helpers ----------------------------------------------------

    def _write_finding(self, tx: Any, result_ref: ResourceRef, parent_ref: ResourceRef, index: int, spec: Mapping[str, Any], verdict: Verdict) -> ResourceRef:
        if not isinstance(spec, Mapping):
            raise AssessmentError("finding specifications must be mappings")
        summary = _opaque(spec.get("summary", f"finding-{index}"), "finding summary")
        finding_id = result_ref.id + "-finding-" + str(index)
        # Findings are stable child identities.  Their current revision is
        # read through the unpinned identity ref so closing a finding does not
        # make the parent result's child link stale.
        finding_ref = ResourceRef(self.__writer.authority, FINDING_KIND, finding_id)
        payload = {"record_type": FINDING_KIND, "schema_revision": SCHEMA_REVISION, "result_ref": result_ref, "parent_obligation_ref": parent_ref, "summary": summary, "severity": _opaque(spec.get("severity", "normal"), "finding severity"), "subjective": bool(spec.get("subjective", False)), "status": "open", "correction_ref": None, "evidence_refs": (), "verdict": verdict.value}
        self.__writer.put_identity(finding_ref, payload, version=1, transaction=tx)
        self.__writer.put_reference(finding_ref, transaction=tx)
        return finding_ref

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], key: str, actor: AuthenticatedActor, *, expected_version: Optional[int] = None, expected_revision: Optional[str] = None, digest_payload: Optional[Mapping[str, Any]] = None) -> CommandEnvelope:
        envelope_payload = dict(payload)
        context = TransactionContext(
            actor,
            key,
            "0" * 64,
            expected_revision=expected_revision,
            expected_version=expected_version,
        )
        digest = canonical_request_digest(
            logical_request_key=key, operation=operation, schema_revision=SCHEMA_REVISION,
            target=target, actor=actor, payload=envelope_payload, context=context,
        )
        return CommandEnvelope(operation, SCHEMA_REVISION, target, TransactionContext(actor, key, digest, expected_revision=expected_revision, expected_version=expected_version), envelope_payload)

    def _actor(self, actor: Optional[AuthenticatedActor]) -> AuthenticatedActor:
        value = actor or self.default_actor or AuthenticatedActor("herzchen.assessment", "assessment-module", "herzchen.assessment")
        if not isinstance(value, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        return value

    @staticmethod
    def _replay_version(target_revision: Optional[str], result_ref: Optional[ResourceRef]) -> Optional[int]:
        revision = target_revision
        if revision is None and result_ref is not None:
            revision = result_ref.revision
            if revision is not None and revision.startswith("rev-"):
                try:
                    return max(0, int(revision.removeprefix("rev-")) - 1)
                except ValueError:
                    return None
        if revision is None or not revision.startswith("rev-"):
            return None
        try:
            return int(revision.removeprefix("rev-"))
        except ValueError:
            return None

    def _key(self, value: Optional[str], prefix: str) -> str:
        return _opaque(value or prefix + "-" + uuid.uuid4().hex, "logical_request_key")

    def _stable_local(self, value: Any, kind: str) -> ResourceRef:
        if isinstance(value, ResourceRef):
            if value.authority != self.__writer.authority or value.kind != kind or value.revision is not None:
                raise AssessmentError(f"{kind} target must be an unpinned local ResourceRef")
            return value
        if isinstance(value, str):
            return ResourceRef(self.__writer.authority, kind, _opaque(value, kind + " id"))
        raise AssessmentError(f"{kind} target must be an unpinned local ResourceRef")

    def _identity(self, target: Any, kind: str) -> Any:
        ref = _ref(target, kind)
        identity = self.__writer.get_identity(ref)
        if identity is None or identity.ref.kind != kind:
            raise AssessmentNotFoundError(f"{kind} not found: {target!r}")
        if ref.revision is not None and identity.ref.revision != ref.revision:
            raise StaleAssessmentError(f"{kind} reference is stale")
        return identity

    def _current_ref(self, ref: ResourceRef, field: str) -> ResourceRef:
        identity = self.__writer.get_identity(ref)
        if identity is None:
            raise AssessmentNotFoundError(f"{field} identity is not admitted")
        if ref.revision is not None and identity.ref.revision != ref.revision:
            raise StaleAssessmentError(f"{field} reference is stale")
        return identity.ref

    def _payload_ref(self, value: Any) -> ResourceRef:
        return value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)

    def _require_criterion(self, scope: AssessmentScope, criterion: ResourceRef) -> None:
        if scope.criterion_refs and criterion not in scope.criterion_refs:
            raise AssessmentError("criterion is not declared in the assessment scope")

    def _validate_input_packet(self, packet: InputPacket) -> None:
        for ref in packet.consumed_refs:
            self._current_ref(ref, "consumed input")

    def _validate_candidate(self, payload: Mapping[str, Any]) -> None:
        """Validate only inputs that the candidate declares as consumed.

        Annotation refs are intentionally not inspected here.  A protocol can
        add an annotation without invalidating a historical result; artifact,
        source, specification, and explicitly consumed input refs are the
        applicability boundary.
        """
        sources = [payload]
        pin = payload.get("pin")
        if isinstance(pin, Mapping):
            sources.append(pin)
        for source in sources:
            for field in ("artifact_ref", "source_ref", "spec_ref"):
                if field in source and source[field] is not None:
                    self._current_ref(_ref(source[field], field), field)
            for value in source.get("criteria_refs", ()):
                self._current_ref(_ref(value, "candidate criterion"), "candidate criterion")
            for field in ("consumed_refs", "input_refs", "consumed_inputs"):
                for value in source.get(field, ()):
                    self._current_ref(_ref(value, field), field)

    def _candidate_semantic_refs(self, payload: Mapping[str, Any]) -> set[ResourceRef]:
        refs: set[ResourceRef] = set()
        sources = [payload]
        pin = payload.get("pin")
        if isinstance(pin, Mapping):
            sources.append(pin)
        for source in sources:
            for field in ("artifact_ref", "source_ref", "spec_ref", "consumed_refs", "input_refs", "consumed_inputs"):
                if field.endswith("_ref"):
                    value = source.get(field)
                    values = () if value is None else (value,)
                else:
                    values = source.get(field, ())
                for value in values:
                    refs.add(_ref(value, "candidate semantic input"))
        return refs

    def _candidate_allows_criterion(self, payload: Mapping[str, Any], criterion: ResourceRef) -> bool:
        sources = [payload]
        pin = payload.get("pin")
        if isinstance(pin, Mapping):
            sources.append(pin)
        declared: list[ResourceRef] = []
        for source in sources:
            for value in source.get("criteria_refs", ()):
                declared.append(_ref(value, "candidate criterion"))
        return not declared or any(value == criterion for value in declared)

    def _verify_decision_actor(self, decision: Decision) -> None:
        receipt = self.__writer.get_receipt(decision.ref.id)
        if receipt is None:
            raise AssessmentAuthorityError("accepted decision has no owner command receipt")
        if (receipt.status != ReceiptStatus.COMMITTED or receipt.operation != "assessment.accept"
                or not _same_identity(receipt.target, decision.ref) or receipt.result_ref != decision.ref):
            raise AssessmentAuthorityError("accepted decision does not match its committed owner receipt")
        events = tuple(
            event for event in self.__writer.list_events(stream=ASSESSMENT_STREAM, subjects=(decision.ref,))
            if event.event_id in set(receipt.event_ids)
            and event.operation == "assessment.accept"
            and _same_identity(event.subject, decision.ref)
        )
        if len(events) != 1:
            raise AssessmentAuthorityError("accepted decision has no unique acceptance event")
        event = events[0]
        if event.store_authority != self.__writer.authority or decision.result_ref not in event.before_refs:
            raise AssessmentAuthorityError("acceptance event owner or exact result provenance differs")
        if event.actor.actor != decision.author:
            raise AssessmentAuthorityError("decision author does not match the authenticated owner event actor")

    def _check_approver(self, scope: AssessmentScope, approver: str, authority: str) -> None:
        if scope.designated_approver is not None and approver != scope.designated_approver:
            raise AssessmentAuthorityError("actor is not the designated approver")
        if scope.authority is not None and authority != scope.authority:
            raise AssessmentAuthorityError("approval authority is not the designated authority")


class _CompletionReadView(_AssessmentModuleEngine):
    """Use the assessment owner's typed reads over a finite consumer reader.

    The work owner supplies its transaction-bound consumer; this view has no
    writer, operation manager, or allowance service and is never published as
    a command facade.
    """

    def __init__(self, reader: Any) -> None:
        for name in ("get_identity", "get_receipt", "list_events"):
            if not callable(getattr(reader, name, None)):
                raise TypeError("assessment completion needs a finite owner reader")
        self._AssessmentModuleEngine__writer = reader
        self.reader = reader

    def list_decisions(self, *, parent_obligation: Any = None) -> Tuple[Decision, ...]:
        parent = None if parent_obligation is None else _ref(parent_obligation, "parent obligation")
        refs: dict[tuple[str, str], ResourceRef] = {}
        for event in self.reader.list_events(stream=ASSESSMENT_STREAM, assessment_parent=parent):
            if event.event_type in {"assessment.accepted", "assessment.unknown.disposed"} and event.subject.kind == DECISION_KIND:
                refs[(event.subject.authority, event.subject.id)] = _stable_ref(event.subject)
        decisions = tuple(self.get_decision(ref) for ref in refs.values())
        return decisions if parent is None else tuple(
            decision for decision in decisions if _same_identity(decision.parent_obligation_ref, parent)
        )


def required_completion_blockers(
    reader: Any, parent_obligation: Any, *, candidate: Any = None,
    gate_refs: Sequence[Any] = (), actor: Optional[AuthenticatedActor] = None,
    evidence_store: Any = None, completion_evidence_refs: Sequence[Any] = (),
    completion_evidence_hashes: Any = (),
) -> Mapping[str, Any]:
    """Read the one assessment completion predicate through a transaction-bound reader."""
    return _CompletionReadView(reader).completion_blockers(
        parent_obligation, candidate=candidate, gate_refs=gate_refs, actor=actor,
        evidence_store=evidence_store, completion_evidence_refs=completion_evidence_refs,
        completion_evidence_hashes=completion_evidence_hashes,
    )


AssessmentModule = command_facade(_AssessmentModuleEngine, DOMAIN_ID)
AssessmentStore = AssessmentModule
Assessment = AssessmentModule


__all__ = [
    "ASSESSMENT_STREAM", "Assessment", "AssessmentModule", "AssessmentStore", "CRITERION_KIND",
    "DOMAIN_ID", "DOMAIN_OWNER", "DOMAIN_VERSION", "SCHEMA_REVISION", "contribution",
]
