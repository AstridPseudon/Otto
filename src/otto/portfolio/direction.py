"""Owner-issued lifetime direction bindings over existing DAT associations.

WRK's responsibility row is the durable subject; its assignment, principal,
generation and native session are current custody, not direction identity.
The sole owner-wide seam is an authority-qualified locator, not a fake project
or a second owner registry. Exact scope adoption uses the same association and
FND evidence. This module does not compose prompts, authenticate tool callers
or grant execution authority.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any, Mapping

from herzchen.command_ports import command_facade
from herzchen.content.direction_contract import PRIMARY_DIRECTION_KEY, PRIMARY_DIRECTION_NAMESPACE
from herzchen.content import ContentRevision
from herzchen.content.model import ContentDocument, DocumentAssociation, association_identity, revision_identity
from herzchen.content.packets import ContextPacketService, AccessDeniedError
from herzchen.contracts import (
    AuthenticatedActor, CommandEnvelope, DomainContribution, ReferenceBinding,
    ReplayConflictError, ResourceRef, TransactionContext, canonical_json, canonical_request_digest, validate_replay,
)

DOMAIN_ID = "otto.direction-bindings"
ADOPTION_DOMAIN_ID = "otto.direction-adoption"
SCHEMA_REVISION = "otto.direction-binding.v1"
OWNER_SCOPE_KIND = "fnd.owner"


class DirectionBindingError(ValueError):
    """The requested subject, document or lifetime binding is invalid."""


class DirectionResolutionError(DirectionBindingError):
    """An actionable, structural failure; no semantic strategy merge is implied."""

    def __init__(self, code: str, remedy: str | None = None) -> None:
        if remedy is None:
            code, _, remedy = code.partition(": ")
        self.code, self.remedy = code, remedy
        super().__init__(code + ": " + remedy)


def owner_direction_subject(authority: str) -> ResourceRef:
    """One stable owner-wide locator, independent of its current operator."""
    return ResourceRef(authority, OWNER_SCOPE_KIND, authority)


def contribution() -> DomainContribution:
    # Late registration leaves all predecessor descriptor digests unchanged.
    # State is an ordinary DAT association in the same FND writer.
    return DomainContribution(
        DOMAIN_ID, "1", "dat", (), (), (), ("dat.direction.bind",),
        ("dat.direction.bound",), SCHEMA_REVISION,
        ("fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
         "handler-required", "mutation-resource:document-association",
         "mutation-port:" + SCHEMA_REVISION + "|dat.direction.bind|document-association|dat.direction.bound"),
    )


def adoption_contribution() -> DomainContribution:
    # A new finite command port, not a new record/history engine. Retain the
    # D01 descriptor exactly so previously registered owner Stores can reopen.
    return DomainContribution(
        ADOPTION_DOMAIN_ID, "1", "dat", (), (), (), ("dat.direction.adopt",),
        ("dat.direction.adopted",), SCHEMA_REVISION,
        ("fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
         "handler-required", "mutation-resource:document-association",
         "mutation-port:" + SCHEMA_REVISION + "|dat.direction.adopt|document-association|dat.direction.adopted"),
    )


def register_direction_bindings(store: Any) -> Any:
    descriptors = (contribution(), adoption_contribution())
    registered = {item.domain_id: item for item in store.registered_domains()}
    missing = tuple(item for item in descriptors if registered.get(item.domain_id) != item)
    if missing:
        store.register_domain_handler(missing)
    return store.domain_handler(descriptors)


def _ref(value: Any) -> ResourceRef:
    return value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)


def _identity(value: ResourceRef) -> ResourceRef:
    return ResourceRef(value.authority, value.kind, value.id)


class _DirectionBindingsEngine:
    """Finite owner capability; the owner actor is injected at composition.

    Possessing assignment-adoption authority, a role name or a document role
    does not satisfy this capability. No caller-selected operator/grant is
    accepted by an operation. The bootstrap is the trusted issuance boundary.
    """

    def __init__(self, store: Any, *, owner_actor: AuthenticatedActor, assignment_port: Any = None) -> None:
        if not isinstance(owner_actor, AuthenticatedActor) or owner_actor.authority != store.authority:
            raise ValueError("direction capability requires the authenticated local owner")
        self.__writer = store.domain_handler((contribution(), adoption_contribution()))
        self.__owner = owner_actor
        # Optional owner-composed Work port.  Direction remains usable without
        # it; update reports assignment application as pending rather than
        # inventing a second assignment writer.
        self.__assignment_port = assignment_port
        self.reader = self.__writer.consumer()
        from herzchen.content.model import domain_contribution
        from herzchen.content import ContentCommandHandler
        self.__visibility = ContextPacketService(store.domain_handler((domain_contribution(),)))
        self.__content = ContentCommandHandler(store.domain_handler((domain_contribution(),)))

    def _authorize(self, actor: AuthenticatedActor) -> None:
        if actor != self.__owner:
            raise PermissionError("direction operation requires the current issuing owner actor")

    def _scope(self, value: Any) -> Mapping[str, Any]:
        ref = _identity(_ref(value))
        if ref.authority != self.__owner.authority:
            raise DirectionBindingError("direction subject belongs to another owner")
        if ref == owner_direction_subject(ref.authority):
            return {"subject_ref": ref.to_dict(), "scope_ref": ref.to_dict(), "kind": "owner"}
        if ref.kind == "wrk.assignment":
            assignment = self.reader.get_record(ref)
            if assignment is None or assignment.payload.get("record_type") != "work.responsibility-assignment":
                raise DirectionBindingError("assignment is unavailable")
            ref = _identity(_ref(assignment.payload["responsibility_ref"]))
        if ref.kind == "wrk.responsibility":
            responsibility = self.reader.get_record(ref)
            if responsibility is None or responsibility.payload.get("record_type") != "work.responsibility":
                raise DirectionBindingError("durable responsibility is unavailable")
            assignment_ref = _identity(_ref(responsibility.payload["assignment"]))
            assignment = self.reader.get_record(assignment_ref)
            if (assignment is None or assignment.ref.authority != ref.authority
                    or assignment.ref.kind != "wrk.assignment"
                    or assignment.payload.get("record_type") != "work.responsibility-assignment"
                    or _identity(_ref(assignment.payload["responsibility_ref"])) != ref
                    or responsibility.payload.get("role") != assignment.payload.get("role")):
                raise DirectionBindingError("responsibility and current assignment disagree")
            scope = _identity(_ref(assignment.payload["scope"]))
            if scope.authority != ref.authority or scope.kind not in {"work.project", "work.task", "wrk.portfolio"}:
                raise DirectionBindingError("responsibility has no supported canonical scope")
            if scope.kind == "wrk.portfolio":
                if assignment.payload.get("role") != "orchestrator":
                    raise DirectionBindingError("portfolio direction requires an orchestrator responsibility")
                work_scope = {"portfolio_ref": scope.to_dict()}
            else:
                work_scope = self._scope(scope)
            return {**work_scope, "subject_ref": ref.to_dict(), "scope_ref": scope.to_dict(), "kind": "responsibility",
                    "assignment_ref": assignment.ref.to_dict(), "role": assignment.payload["role"],
                    "principal": assignment.payload.get("principal"), "generation": assignment.payload["generation"],
                    "session": assignment.payload.get("session"), "status": assignment.payload["status"]}
        if ref.kind in {"work.project", "work.task"}:
            record = self.reader.get_record(ref)
            if record is not None and record.payload.get("kind") == ref.kind.removeprefix("work."):
                result = {"subject_ref": ref.to_dict(), "scope_ref": ref.to_dict(), "kind": record.payload["kind"]}
                if ref.kind == "work.project":
                    result["project_ref"] = record.ref.to_dict()
                else:
                    project_ref = _identity(_ref(record.payload["project_ref"]))
                    project = self.reader.get_record(project_ref)
                    if project_ref.authority != ref.authority or project_ref.kind != "work.project" or project is None:
                        raise DirectionBindingError("task has no supported canonical project")
                    result.update(task_ref=record.ref.to_dict(), project_ref=project.ref.to_dict())
                return result
        raise DirectionBindingError("use an existing responsibility/project/task or the owner-wide subject; names and sessions are not scopes")

    @staticmethod
    def _association(subject: ResourceRef, document: ResourceRef) -> DocumentAssociation:
        return DocumentAssociation(subject, PRIMARY_DIRECTION_NAMESPACE, PRIMARY_DIRECTION_KEY,
                                   ReferenceBinding(document, "current"), "read")

    @staticmethod
    def _target(subject: ResourceRef) -> ResourceRef:
        return ResourceRef(subject.authority, "document-association",
                           association_identity(subject, PRIMARY_DIRECTION_NAMESPACE, PRIMARY_DIRECTION_KEY))

    def _binding(self, subject: ResourceRef) -> Any:
        record = self.reader.get_record(self._target(subject))
        if record is None:
            return None
        payload = record.payload
        try:
            association = DocumentAssociation.from_dict(payload["association"])
            valid = (payload.get("record_type") == "dat.content.association"
                     and payload.get("direction_contract") == SCHEMA_REVISION and payload.get("active") is True
                     and association.subject == subject and association.namespace == PRIMARY_DIRECTION_NAMESPACE
                     and association.key == PRIMARY_DIRECTION_KEY and association.access_mode == "read"
                     and association.document.mode == "current" and association.document.ref.revision is None
                     and association.document.ref.authority == subject.authority
                     and association.document.ref.kind == "dat.content.document")
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise DirectionBindingError("primary binding is invalid; use explicit owner repair, never unlink/rebind")
        return record

    def read(self, subject: Any, *, actor: AuthenticatedActor) -> Mapping[str, Any]:
        """Owner-only identity read; effective/adopted revision is not inferred."""
        self._authorize(actor)
        scope = self._scope(subject)
        binding = self._binding(_ref(scope["subject_ref"]))
        return dict(scope, binding_ref=None if binding is None else binding.ref.to_dict(),
                    document_ref=None if binding is None else binding.payload["association"]["document"]["ref"],
                    binding_operator=None if binding is None else binding.payload["binding_operator"],
                    scope_adopted_ref=None if binding is None else (binding.payload.get("scope_adoption") or {}).get("ref"),
                    authority="owner scope binding/adoption; no execution grant")

    def bind(self, subject: Any, document_ref: Any, *, actor: AuthenticatedActor,
             logical_request_key: str) -> Mapping[str, Any]:
        """Initial binding only; same identity retries never revise membership."""
        self._authorize(actor)
        document_ref = _ref(document_ref)
        if document_ref.kind != "dat.content.document" or document_ref.revision is not None or document_ref.authority != actor.authority:
            raise DirectionBindingError("initial binding requires an unversioned local DAT document identity")
        with self.__writer.transaction() as transaction:
            scope = self._scope(subject)
            subject_ref = _ref(scope["subject_ref"])
            association = self._association(subject_ref, document_ref)
            target = self._target(subject_ref)
            request = {"subject_ref": subject_ref, "document_ref": document_ref}
            context = TransactionContext(actor, logical_request_key, "0" * 64, expected_version=0)
            envelope = CommandEnvelope("dat.direction.bind", SCHEMA_REVISION, target, context, request)
            envelope = replace(envelope, context=replace(context, request_digest=canonical_request_digest(
                logical_request_key=logical_request_key, operation=envelope.operation,
                schema_revision=SCHEMA_REVISION, target=target, actor=actor, payload=request, context=context)))
            prior = self.__writer.get_receipt(logical_request_key)
            if prior is not None:
                validate_replay(prior, envelope)
            binding = self._binding(subject_ref)
            if binding is not None:
                if binding.payload["association"]["document"]["ref"] != document_ref.to_dict():
                    raise DirectionBindingError("primary direction identity is fixed for this subject's lifetime; append content revisions")
                return self.read(subject_ref, actor=actor)
            if prior is not None:
                raise DirectionBindingError("retained binding receipt has no binding; explicit owner repair is required")
            head = self.reader.get_record(document_ref)
            if head is None or head.payload.get("record_type") != "dat.content.document":
                raise DirectionBindingError("direction document is unavailable")
            document = ContentDocument.from_dict(head.payload["document"])
            if document.import_mode != "owned" or not document.writable or document.role != "direction":
                raise DirectionBindingError("select an owned writable direction document; guides, mandates and imported sources remain distinct")
            allowed_scopes = {subject_ref, _ref(scope["scope_ref"])}
            if scope.get("project_ref") is not None:
                allowed_scopes.add(_identity(_ref(scope["project_ref"])))
            if document.authoring_scope is None or _identity(document.authoring_scope) not in allowed_scopes:
                raise DirectionBindingError("direction document authoring scope does not match the subject")
            payload = {"record_type": "dat.content.association", "association": association,
                       "active": True, "direction_contract": SCHEMA_REVISION,
                       "binding_operator": actor, "initial_request_key": logical_request_key}
            self.__writer.mutate(envelope, identity_payload=payload, event_type="dat.direction.bound",
                                 after_refs=((document_ref,) if scope["kind"] == "owner" else (subject_ref, document_ref)),
                                 effects={"subject_ref": subject_ref, "document_ref": document_ref},
                                 stream="direction:" + target.id, transaction=transaction)
            return self.read(subject_ref, actor=actor)

    def _bound_document(self, subject: Any, actor: AuthenticatedActor) -> tuple[Mapping[str, Any], Any, ContentDocument, ResourceRef]:
        """Read the fixed document identity and its current DAT head."""
        scope = self._scope(subject)
        subject_ref = _ref(scope["subject_ref"])
        binding = self._binding(subject_ref)
        if binding is None:
            raise DirectionResolutionError("unbound_direction", "initially bind an owned direction before editing")
        document_ref = _ref(binding.payload["association"]["document"]["ref"])
        record = self.reader.get_record(_identity(document_ref))
        if record is None or record.payload.get("record_type") != "dat.content.document":
            raise DirectionResolutionError("missing_document", "restore the bound direction document")
        document = ContentDocument.from_dict(record.payload["document"])
        current = _ref(record.payload.get("current_revision"))
        if current.authority != document_ref.authority or current.kind != document_ref.kind or current.id != document_ref.id or not current.revision:
            raise DirectionResolutionError("invalid_head", "repair the bound document's current immutable revision")
        return scope, binding, document, current

    @staticmethod
    def _draft_revision(document: ContentDocument, parent: ResourceRef, content: Mapping[str, Any],
                        logical_request_key: str, revision: str | None) -> str:
        if revision is not None:
            return revision
        material = {"document": document.ref.to_dict(), "parent": parent.to_dict(),
                    "content": content, "logical_request_key": logical_request_key}
        return "rev-" + sha256(canonical_json(material).encode("utf-8")).hexdigest()[:28]

    def save_draft(self, subject: Any, content: Mapping[str, Any], *, actor: AuthenticatedActor,
                   logical_request_key: str, expected_revision: str | None = None,
                   revision: str | None = None) -> Mapping[str, Any]:
        """Append content only; never change scope adoption or assignment pins."""
        self._authorize(actor)
        if not isinstance(content, Mapping):
            raise DirectionBindingError("draft content must be a JSON object")
        scope, binding, document, current = self._bound_document(subject, actor)
        # A completed append is recoverable by the same logical request key;
        # do not attempt a second mutation merely because the caller retried.
        prior = self.reader.get_receipt(logical_request_key)
        if prior is not None and prior.result_ref is not None:
            if prior.result_ref.authority != document.ref.authority or prior.result_ref.kind != document.ref.kind:
                raise ReplayConflictError("logical request key was reused with a changed draft")
            retained = self.reader.get_record(revision_identity(document.ref, prior.result_ref.revision))
            if retained is None or retained.payload.get("content") != dict(content):
                raise ReplayConflictError("logical request key was reused with a changed draft")
            return {"outcome": "drafted", "replayed": True, "subject_ref": scope["subject_ref"],
                    "binding_ref": binding.ref.to_dict(), "document_ref": document.ref.to_dict(),
                    "revision_ref": prior.result_ref.to_dict(), "adopted": False,
                    "scope_adopted_ref": (binding.payload.get("scope_adoption") or {}).get("ref")}
        if expected_revision is not None and expected_revision != current.revision:
            raise DirectionResolutionError("stale_draft", "reread the latest document head before saving")
        revision_name = self._draft_revision(document, current, content, logical_request_key, revision)
        revision_ref = ResourceRef(document.ref.authority, document.ref.kind, document.ref.id, revision_name)

        created = ContentRevision(document.ref, revision_name, dict(content), actor,
                                   parent_revision=current.revision)
        context = TransactionContext(actor, logical_request_key, "0" * 64,
                                     expected_revision=current.revision)
        self.__content.execute(self.__content.build_append_revision(context, document, created))
        return {"outcome": "drafted", "replayed": False, "subject_ref": scope["subject_ref"],
                "binding_ref": binding.ref.to_dict(), "document_ref": document.ref.to_dict(),
                "revision_ref": revision_ref.to_dict(), "adopted": False,
                "scope_adopted_ref": (binding.payload.get("scope_adoption") or {}).get("ref")}

    # Keep the short operation name available to existing authoring callers.
    draft = save_draft

    def history(self, subject: Any, *, actor: AuthenticatedActor) -> Mapping[str, Any]:
        """Derive content/adoption history from DAT revisions and FND events."""
        self._authorize(actor)
        scope, binding, document, current = self._bound_document(subject, actor)
        revisions: list[Mapping[str, Any]] = []
        cursor: ResourceRef | None = current
        while cursor is not None:
            record = self.reader.get_record(revision_identity(document.ref, cursor.revision))
            if record is None or record.payload.get("record_type") != "dat.content.revision":
                raise DirectionResolutionError("missing_history", "restore the immutable direction revision chain")
            payload = record.payload
            revisions.append({"ref": cursor.to_dict(), "parent_ref": None if payload.get("parent_revision") is None else
                              replace(cursor, revision=payload["parent_revision"]).to_dict(),
                              "content": payload.get("content"), "content_sha256": payload.get("content_digest"),
                              "author": payload.get("author"), "initial": payload.get("initial", False)})
            parent = payload.get("parent_revision")
            cursor = None if parent is None else replace(document.ref, revision=parent)
        revisions.reverse()
        events = self.reader.list_events(stream="direction:" + binding.ref.id)
        adoptions = []
        for event in events:
            if event.event_type != "dat.direction.adopted" or "scope_adoption" not in event.effects:
                continue
            adoptions.append({"event_id": event.event_id, "recorded_at": event.recorded_at,
                              "actor": event.actor.to_dict(), "adoption": event.effects["scope_adoption"]})
        adopted = binding.payload.get("scope_adoption") or {}
        return {"outcome": "read", "subject_ref": scope["subject_ref"],
                "binding_ref": binding.ref.to_dict(), "document_ref": document.ref.to_dict(),
                "latest_ref": current.to_dict(), "scope_adopted_ref": adopted.get("ref"),
                "content_revisions": revisions, "revisions": revisions,
                "scope_adoptions": adoptions, "adoptions": adoptions,
                # Occurrence delivery evidence remains owned by Due/assignment
                # records; adoption evidence is retained here, never rewritten.
                "admitted_evidence": [item["adoption"].get("inputs", []) for item in adoptions],
                "occurrence_evidence": [], "read_only": True, "dispatch": False}

    read_history = history

    def update(self, subject: Any, revision_ref: Any = None, *, actor: AuthenticatedActor,
               expected_binding_ref: Any = None, logical_request_key: str,
               content: Mapping[str, Any] | None = None, expected_revision: str | None = None,
               assignment_ref: Any = None, expected_generation: int | None = None,
               assignment_resources: Any = None, assignment_actor: Any = None,
               expected_assignment_guard_ref: Any = None) -> Mapping[str, Any]:
        """Explicitly apply one exact revision, optionally at Work's future boundary.

        Scope adoption is CAS/replay-safe.  Assignment refresh is deliberately
        delegated to Work's existing adoption port; if that port, actor or
        boundary is unavailable, the already committed scope adoption is
        returned as a recoverable partial outcome.
        """
        self._authorize(actor)
        if content is not None and revision_ref is not None:
            raise DirectionBindingError("update accepts content or an exact revision, not both")
        assignment_snapshot = None
        assignment_scope = None
        requested_assignment = None
        if assignment_ref is not None:
            if expected_generation is None:
                raise DirectionResolutionError("invalid_assignment_boundary", "pin the assignment generation for future application")
            requested_assignment = _ref(assignment_ref)
            assignment_snapshot = self.reader.get_record(_identity(requested_assignment))
            assignment_scope = self._scope(requested_assignment)
            # A committed refresh advances this very pin. Recover the two
            # retained boundaries before applying current-state fences, just
            # as Work's adoption port does. Both ports still validate the exact
            # request/actor/digest; receipt presence never authorizes a new
            # adoption or a changed retry against a stale assignment.
            scope_receipt = self.reader.get_receipt(logical_request_key)
            assignment_receipt = self.reader.get_receipt(logical_request_key + ":assignment")
            recovering = (scope_receipt is not None
                          and scope_receipt.operation == "dat.direction.adopt"
                          and assignment_receipt is not None
                          and assignment_receipt.operation == "work.assignment.adopt-resources"
                          and assignment_receipt.target == requested_assignment)
            if (requested_assignment.kind != "wrk.assignment" or requested_assignment.revision is None
                    or assignment_snapshot is None
                    or not recovering and (assignment_snapshot.ref != requested_assignment
                                           or assignment_scope.get("generation") != expected_generation)):
                raise DirectionResolutionError("stale_assignment", "reread the exact current assignment and generation")
            if not recovering and assignment_scope.get("status") not in {"queued", "reassigned"}:
                raise DirectionResolutionError("unsupported_boundary", "assignment refresh requires a queued or reassigned future boundary")
        draft_result = None
        if content is not None:
            draft_result = self.save_draft(subject, content, actor=actor,
                                           logical_request_key=logical_request_key + ":draft",
                                           expected_revision=expected_revision)
            revision_ref = draft_result["revision_ref"]
        if revision_ref is None:
            raise DirectionResolutionError("missing_revision", "save a draft or provide an exact immutable revision")
        scope, binding, _document, _current = self._bound_document(subject, actor)
        if expected_binding_ref is None:
            expected_binding_ref = binding.ref
        adoption = self.adopt(subject, revision_ref, actor=actor,
                              expected_binding_ref=expected_binding_ref,
                              logical_request_key=logical_request_key)
        result: dict[str, Any] = {"outcome": "updated", "draft": draft_result,
                                  "scope_adoption": adoption, "scope_adopted_ref": adoption["ref"],
                                  "assignment_refresh": None, "partial": False,
                                  "admitted_evidence_preserved": True}
        if assignment_ref is None:
            return result
        if not assignment_resources:
            result.update(outcome="partial", partial=True,
                          assignment_refresh={"outcome": "pending", "code": "resources_not_supplied",
                                              "message": "supply the complete adopted BASE resource set to refresh the assignment"})
            return result
        if self.__assignment_port is None or assignment_actor is None:
            result.update(outcome="partial", partial=True,
                          assignment_refresh={"outcome": "pending", "code": "assignment_refresh_unavailable",
                                              "message": "retry through the existing Work adoption port with its authorized assignment actor"})
            return result
        try:
            refreshed = self.__assignment_port.adopt_resources(
                requested_assignment, resources=assignment_resources, expected_revision=requested_assignment.revision,
                expected_generation=expected_generation,
                logical_request_key=logical_request_key + ":assignment",
                actor=assignment_actor, expected_guard_ref=expected_assignment_guard_ref)
            result["assignment_refresh"] = {"outcome": "committed", "assignment_ref": refreshed.ref.to_dict(),
                                             "generation": refreshed.generation,
                                             "resource_adoption_revision": refreshed.payload.get("resource_adoption_revision")}
            return result
        except Exception as exc:
            result.update(outcome="partial", partial=True,
                          assignment_refresh={"outcome": "partial", "code": type(exc).__name__,
                                              "message": str(exc), "retry_key": logical_request_key + ":assignment"},
                          next_action="reconcile the retained scope adoption, then retry the exact assignment refresh")
            return result

    update_direction = update


    def _exact(self, ref: Any, scope: Mapping[str, Any], actor: AuthenticatedActor) -> Mapping[str, Any]:
        ref = _ref(ref)
        if ref.authority != actor.authority or ref.kind != "dat.content.document" or not ref.revision:
            raise DirectionResolutionError("invalid_pin", "select an exact local DAT document revision")
        scopes = tuple(_identity(_ref(scope[key])) for key in
                       ("subject_ref", "scope_ref", "project_ref", "task_ref") if scope.get(key))
        try:
            observed = self.__visibility.resolve_reference(ref, actor=actor, scopes=scopes)
        except AccessDeniedError as exc:
            raise DirectionResolutionError("inaccessible_input", "restore current document read permission: " + ref.id) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DirectionResolutionError("missing_input", "restore the exact immutable input: " + ref.id) from exc
        revision = observed.get("revision")
        document = observed.get("document")
        if (not isinstance(document, Mapping) or document.get("ref") != _identity(ref).to_dict()
                or not isinstance(revision, Mapping) or revision.get("record_type") != "dat.content.revision"
                or revision.get("document") != _identity(ref).to_dict() or revision.get("revision") != ref.revision
                or observed.get("resolved") != ref
                or revision.get("content_digest") != sha256(canonical_json(revision.get("content")).encode()).hexdigest()):
            raise DirectionResolutionError("invalid_input", "repair immutable document identity/content evidence: " + ref.id)
        return {"ref": ref.to_dict(), "content": revision["content"],
                "content_sha256": revision["content_digest"], "document_role": document.get("role")}

    def _inputs(self, ref: Any, scope: Mapping[str, Any], actor: AuthenticatedActor) -> list[Mapping[str, Any]]:
        primary = self._exact(ref, scope, actor)
        head = self.reader.get_record(_identity(_ref(ref)))
        document = ContentDocument.from_dict(head.payload["document"])
        allowed = {_identity(_ref(scope[key])) for key in
                   ("subject_ref", "scope_ref", "project_ref") if scope.get(key)}
        if (document.role != "direction" or document.import_mode != "owned" or not document.writable
                or document.authoring_scope is None or _identity(document.authoring_scope) not in allowed):
            raise DirectionResolutionError("invalid_direction", "restore owned direction metadata for this bound scope")
        content = primary["content"]
        raw = content.get("supporting_refs", []) if isinstance(content, Mapping) else []
        if not isinstance(raw, list) or len(raw) > 32:
            raise DirectionResolutionError("invalid_supporting_refs", "declare at most 32 exact supporting refs in the direction revision")
        result, seen = [primary], {_identity(_ref(ref)): _ref(ref)}
        for value in raw:
            try:
                pin = _ref(value)
            except (KeyError, TypeError, ValueError) as exc:
                raise DirectionResolutionError("invalid_pin", "correct the declared supporting reference") from exc
            identity = _identity(pin)
            if identity in seen:
                if seen[identity] != pin or identity == _identity(_ref(ref)):
                    raise DirectionResolutionError("conflicting_inputs", "remove self-reference or conflicting supporting revisions")
                continue
            seen[identity] = pin
            result.append(self._exact(pin, scope, actor))
        return result

    @staticmethod
    def _evidence(inputs: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [{"ref": item["ref"], "content_sha256": item["content_sha256"]} for item in inputs]

    def adopt(self, subject: Any, revision_ref: Any, *, actor: AuthenticatedActor,
              expected_binding_ref: Any, logical_request_key: str) -> Mapping[str, Any]:
        """Explicit exact scope adoption, CAS/replay over the fixed association.

        Saving content never calls this operation. Assignment refresh still uses
        WRK's existing eligible-state/generation/admission-guard operation.
        """
        self._authorize(actor)
        pin, expected = _ref(revision_ref), _ref(expected_binding_ref)
        with self.__writer.transaction() as transaction:
            scope = self._scope(subject)
            subject_ref = _ref(scope["subject_ref"])
            binding = self._binding(subject_ref)
            if binding is None:
                raise DirectionResolutionError("unbound_direction", "initially bind the owned direction before adoption")
            if _identity(expected) != self._target(subject_ref) or not expected.revision:
                raise DirectionResolutionError("invalid_binding_pin", "read and pin this scope's current binding revision")
            request = {"subject_ref": subject_ref, "revision_ref": pin}
            context = TransactionContext(actor, logical_request_key, "0" * 64, expected_revision=expected.revision)
            envelope = CommandEnvelope("dat.direction.adopt", SCHEMA_REVISION, _identity(expected), context, request)
            envelope = replace(envelope, context=replace(context, request_digest=canonical_request_digest(
                logical_request_key=logical_request_key, operation=envelope.operation,
                schema_revision=SCHEMA_REVISION, target=envelope.target, actor=actor, payload=request, context=context)))
            prior = self.__writer.get_receipt(logical_request_key)
            if prior is not None:
                validate_replay(prior, envelope)
                event = next(item for item in self.reader.list_events(stream="direction:" + expected.id)
                             if item.event_id in prior.event_ids)
                return event.effects["scope_adoption"]
            if expected != binding.ref:
                raise DirectionResolutionError("stale_binding", "reread scope adoption and reconcile before applying the update")
            if _identity(pin).to_dict() != binding.payload["association"]["document"]["ref"]:
                raise DirectionResolutionError("fixed_identity", "append/adopt a revision of the bound primary document")
            inputs = self._inputs(pin, scope, actor)
            adoption = {"ref": pin.to_dict(), "inputs": self._evidence(inputs), "operator": actor.to_dict()}
            payload = dict(binding.payload, scope_adoption=adoption)
            self.__writer.mutate(envelope, identity_payload=payload, event_type="dat.direction.adopted",
                                 effects={"scope_adoption": adoption, "subject_ref": subject_ref},
                                 after_refs=tuple(_ref(item["ref"]) for item in inputs),
                                 stream="direction:" + expected.id, transaction=transaction)
            return adoption

    def resolve(self, subject: Any, *, actor: AuthenticatedActor,
                assignment_ref: Any = None, expected_generation: int | None = None) -> Mapping[str, Any]:
        """Read exact authorized inputs; latest is observation, never selection.

        Assignment mode reuses immutable BASE resource adoption. An older scope
        adoption remains valid for a still-pinned assignment; existing scope
        events prove it. No assignment/native admission fence is relaxed.
        """
        self._authorize(actor)
        with self.__writer.transaction():
            scope = self._scope(subject)
            binding = self._binding(_ref(scope["subject_ref"]))
            if binding is None:
                raise DirectionResolutionError("unbound_direction", "initially bind an owned direction for this scope")
            adoption = binding.payload.get("scope_adoption")
            if not isinstance(adoption, Mapping):
                raise DirectionResolutionError("unadopted_direction", "explicitly adopt an exact revision for this scope")
            pin = _ref(adoption["ref"])
            if _identity(pin).to_dict() != binding.payload["association"]["document"]["ref"]:
                raise DirectionResolutionError("conflicting_binding", "repair scope adoption without replacing primary identity")
            adoptions = [event.effects["scope_adoption"] for event in
                         self.reader.list_events(stream="direction:" + binding.ref.id)
                         if event.event_type == "dat.direction.adopted" and "scope_adoption" in event.effects]
            if not adoptions or adoptions[-1] != adoption:
                raise DirectionResolutionError("conflicting_adoption", "reconcile current scope adoption against its canonical event")
            effective = adoption
            assignment_pin, current_assignment = None, None
            if assignment_ref is not None:
                requested = _ref(assignment_ref)
                if requested.kind != "wrk.assignment" or requested.authority != actor.authority or not requested.revision:
                    raise DirectionResolutionError("invalid_assignment_pin", "use an exact local Work assignment revision and generation")
                assignment_scope = self._scope(requested)
                current_assignment = self.reader.get_record(_identity(requested))
                if (requested.kind != "wrk.assignment" or current_assignment.ref != requested
                        or not isinstance(expected_generation, int) or isinstance(expected_generation, bool)
                        or expected_generation != assignment_scope["generation"]):
                    raise DirectionResolutionError("stale_assignment", "use the current exact assignment revision and generation")
                applicable = {_ref(assignment_scope["subject_ref"]), _ref(assignment_scope["scope_ref"]),
                              owner_direction_subject(actor.authority)}
                applicable.update(_identity(_ref(assignment_scope[key])) for key in ("project_ref", "task_ref")
                                  if assignment_scope.get(key))
                if _ref(scope["subject_ref"]) not in applicable:
                    raise DirectionResolutionError("unauthorized_scope", "resolve only direction applicable to this assignment")
                from .resource_sync import resolve_assignment_attachments
                try:
                    attachments = resolve_assignment_attachments(
                        {"ref": requested.to_dict(), "role": assignment_scope["role"], "payload": current_assignment.payload},
                        self.__content)
                except ValueError as exc:
                    raise DirectionResolutionError("invalid_assignment_resources", "repair exact BASE adoption evidence") from exc
                bases = [item for item in attachments if item["required"]]
                if len(bases) != 1:
                    raise DirectionResolutionError("missing_assignment_base", "adopt exactly one required BASE through Work")
                base = self._exact(bases[0]["resource_ref"], assignment_scope, actor)
                matches = [_ref(value) for value in base["content"]["supporting_refs"]
                           if _identity(_ref(value)) == _identity(pin)]
                if not matches:
                    raise DirectionResolutionError("missing_assignment_direction", "adopt a BASE with the exact authorized direction pin at an eligible Work boundary")
                if any(value != matches[0] for value in matches):
                    raise DirectionResolutionError("conflicting_assignment_direction", "remove competing primary revision pins from BASE")
                assignment_pin = matches[0]
                candidates = [item for item in adoptions if item.get("ref") == assignment_pin.to_dict()]
                if not candidates:
                    raise DirectionResolutionError("unauthorized_revision", "scope owner must authorize this exact revision; assignment adoption alone is insufficient")
                effective = candidates[-1]
            inputs = self._inputs(effective["ref"], scope, actor)
            if assignment_pin is not None:
                consumed = {_identity(_ref(item["ref"])): _ref(item["ref"]) for item in inputs}
                for value in base["content"]["supporting_refs"]:
                    ref = _ref(value)
                    if _identity(ref) in consumed and ref != consumed[_identity(ref)]:
                        raise DirectionResolutionError("conflicting_assignment_inputs", "align overlapping BASE inputs with scope-authorized supporting pins")
            if self._evidence(inputs) != effective.get("inputs"):
                raise DirectionResolutionError("conflicting_adoption", "repair retained scope input/digest evidence")
            # Validate only consumed content. A pending scope update can have
            # new supporting inputs; losing access to those must not invalidate
            # an assignment which still consumes the older authorized inputs.
            head = self.reader.get_record(_identity(pin))
            latest = _ref(head.payload["current_revision"])
            if _identity(latest) != _identity(pin) or not latest.revision:
                raise DirectionResolutionError("invalid_head", "repair document head identity; keep adopted pins unchanged")
            return {**scope, "binding_ref": binding.ref.to_dict(), "document_ref": _identity(pin).to_dict(),
                    "latest_ref": latest.to_dict(), "scope_adopted_ref": pin.to_dict(),
                    "assignment_adopted_ref": None if assignment_pin is None else assignment_pin.to_dict(),
                    "assignment_ref": None if current_assignment is None else current_assignment.ref.to_dict(),
                    "effective_ref": effective["ref"], "inputs": inputs,
                    "pending_scope_adoption": latest != pin,
                    "pending_assignment_application": assignment_pin is not None and assignment_pin != pin,
                    "delivered_ref": None, "delivery_status": "not_inspected",
                    "dispatch": False, "authority": "exact scope adoption; no execution or delivery claim"}


DirectionBindings = command_facade(_DirectionBindingsEngine, DOMAIN_ID)
