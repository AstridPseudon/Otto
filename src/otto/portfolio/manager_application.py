"""Thin ordinary manager entry composed over one trusted owner bootstrap.

The host must create/open and explicitly initialize the canonical Store before
calling :meth:`ManagerApplication.from_owner`.  Composition never registers
domains, opens a Store, resolves credentials, or starts a runtime/provider.
"""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import Any, Mapping, Optional

from herzchen.contracts import ResourceRef
from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.content.packets import (
    ContextPacketService,
    domain_contribution as packet_contribution,
)
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.assessment.module import contribution as assessment_contribution
from herzchen.domains.work import DOMAIN_ID as WORK_DOMAIN_ID
from herzchen.domains.work.assignments import (
    ASSIGNMENT_RESOURCE_DOMAIN_ID,
    DOMAIN_ID as ASSIGNMENT_DOMAIN_ID,
    resource_adoption_contribution,
)
from herzchen.domains.work.lifecycle import LIFECYCLE_DOMAIN_ID
from herzchen.domains.work.sheet import DOMAIN_ID as SHEET_DOMAIN_ID

from .assessment import OttoAssessment
from .document_navigation import ProjectDocumentOperations
from .documents import ProjectDocumentReader
from .intake import OttoPortfolio
from .owner_readers import assignment_reader, mandate_reader, project_reader, task_reader


class ManagerCompositionError(ValueError):
    """A trusted owner cannot supply the complete, already-registered manager surface."""


def _project_scope_allowed(grant: Any, binding: Any, actor: Any, project: Any) -> bool:
    """Check the admitted principal and project before any owner projection."""
    if grant is None:
        return False
    try:
        principal = binding.authenticated_actor(actor) if isinstance(actor, str) else actor
        ref = ResourceRef.from_dict(project) if isinstance(project, Mapping) else project
        return principal == grant.principal and grant.allows(ref)
    except (AttributeError, TypeError, ValueError, KeyError):
        return False


def _scope_denied() -> dict[str, Any]:
    return {"outcome": "denied", "read_only": True,
            "error": {"code": "project_scope_denied", "message": "project read scope is unavailable"}}


class _ScopedDocumentReader:
    """Expose only the documented document reads, after the project grant."""

    __slots__ = ("__delegate", "_grant", "_binding")

    def __init__(self, delegate: ProjectDocumentReader, grant: Any, binding: Any) -> None:
        self.__delegate, self._grant, self._binding = delegate, grant, binding

    def _allowed(self, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> bool:
        project = args[0] if args else kwargs.get("project_ref")
        return _project_scope_allowed(self._grant, self._binding, kwargs.get("actor"), project)

    def list_documents(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.list_documents(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def read_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.read_document(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def read_many(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.read_many(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def list_revisions(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.list_revisions(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()


class _ScopedBacklinkReader:
    """Intersect document privacy with the requested project's Work subjects."""

    __slots__ = ("__delegate", "__reader", "_grant", "_binding")

    def __init__(self, delegate: Any, reader: Any, grant: Any, binding: Any) -> None:
        self.__delegate, self.__reader = delegate, reader
        self._grant, self._binding = grant, binding

    def _within_project(self, subject: Any, project: ResourceRef) -> bool:
        try:
            subject = ResourceRef.from_dict(subject) if isinstance(subject, Mapping) else subject
            if subject.kind == "work.task":
                # Use current owner-backed membership, not a historical link's pin.
                record = self.__reader.get_record(ResourceRef(subject.authority, subject.kind, subject.id))
                parent = record.payload.get("project_ref") if record is not None else None
                subject = ResourceRef.from_dict(parent) if isinstance(parent, Mapping) else parent
            elif subject.kind != "work.project":
                # Document privacy alone cannot establish project membership.
                return False
            return (subject.authority, subject.kind, subject.id) == (project.authority, project.kind, project.id)
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

    def visible_backlinks(self, document: Any, *, actor: Any = None,
                          roles: Any = (), scopes: Any = ()) -> tuple[Any, ...]:
        scopes = tuple(scopes)
        if len(scopes) != 1 or not _project_scope_allowed(self._grant, self._binding, actor, scopes[0]):
            return ()
        project = ResourceRef.from_dict(scopes[0]) if isinstance(scopes[0], Mapping) else scopes[0]
        backlinks = self.__delegate.visible_backlinks(document, actor=actor, roles=roles, scopes=(project,))
        return tuple(item for item in backlinks if self._within_project(item.get("subject"), project))


class _ScopedDocumentOperations:
    """Finite navigation facade; do not publish unscoped Sheet/content ports."""

    __slots__ = ("__delegate", "_grant", "_binding", "document_reader")

    def __init__(self, delegate: ProjectDocumentOperations, reader: _ScopedDocumentReader,
                 grant: Any, binding: Any) -> None:
        self.__delegate, self._grant, self._binding = delegate, grant, binding
        self.document_reader = reader

    def _allowed(self, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> bool:
        project = args[0] if args else kwargs.get("project_ref")
        return _project_scope_allowed(self._grant, self._binding, kwargs.get("actor"), project)

    def search_documents(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.search_documents(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def resolve_relative_link(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.resolve_relative_link(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def diff_revisions(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.diff_revisions(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def visible_backlinks(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.visible_backlinks(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def open_edit(self, *args: Any, **kwargs: Any) -> Any:
        return self.__delegate.open_edit(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def export_bundle(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.__delegate.export_bundle(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def finish_edit(self, *args: Any, **kwargs: Any) -> Any:
        # The existing authoring session owner checks this write operation.
        return self.__delegate.finish_edit(*args, **kwargs)

    def edit_status(self, *args: Any, **kwargs: Any) -> Any:
        # EDT checks the current actor/token/fence before exposing the handle.
        return self.__delegate.edit_status(*args, **kwargs)

    def session_inventory(self, *args: Any, **kwargs: Any) -> Any:
        # Inventory is scoped to the same project grant as document reads.
        return self.__delegate.session_inventory(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def resume_edit(self, *args: Any, **kwargs: Any) -> Any:
        # A supplied handle is still revalidated by EDT; the project grant is
        # an additional host visibility boundary.
        return self.__delegate.resume_edit(*args, **kwargs) if self._allowed(args, kwargs) else _scope_denied()

    def discard_edit(self, *args: Any, **kwargs: Any) -> Any:
        return self.__delegate.discard_edit(*args, **kwargs)

    def release_edit(self, *args: Any, **kwargs: Any) -> Any:
        return self.__delegate.release_edit(*args, **kwargs)

    def recover_edit(self, *args: Any, **kwargs: Any) -> Any:
        return self.__delegate.recover_edit(*args, **kwargs)

    def autosave_edit(self, *args: Any, **kwargs: Any) -> Any:
        # Draft autosave is recoverability; explicit finish_edit remains the
        # only document check-in/publication operation on this facade.
        return self.__delegate.autosave_edit(*args, **kwargs)

    def idle_close_edit(self, *args: Any, **kwargs: Any) -> Any:
        # The host timer/poller invokes one existing one-shot boundary; it does
        # not become a scheduler or acquire a second authoring authority.
        return self.__delegate.idle_close_edit(*args, **kwargs)

    idle_checkin_edit = idle_close_edit


class ManagerApplication:
    """Finite manager CLI composition; it holds no bootstrap or Store handle."""

    __slots__ = (
        "_actor",
        "portfolio",
        "document_operations",
        "assessment",
        "completion_owner",
        "_operating_brief_reader_factory",
        "direction_operations",
    )

    def __init__(
        self,
        *,
        actor: str,
        portfolio: Any,
        document_operations: Any,
        assessment: Any,
        completion_owner: Any,
        operating_brief_reader_factory: Any,
        direction_operations: Any = None,
    ) -> None:
        self._actor = actor
        self.portfolio = portfolio
        self.document_operations = document_operations
        self.assessment = assessment
        self.completion_owner = completion_owner
        self._operating_brief_reader_factory = operating_brief_reader_factory
        self.direction_operations = direction_operations

    @classmethod
    def from_owner(cls, owner: Any, *, due_port: Any = None, issue_delivery: Any = None,
                   idle_lifecycle: Any = None, document_authoring: Any = None) -> "ManagerApplication":
        """Compose read/application facades from the supplied trusted bootstrap.

        Domain registration belongs to the host's explicit initialization
        phase.  This method checks that phase's result before composing any
        readers and never calls a registration or initialization method.
        """
        from .owner_bootstrap import PortfolioOwnerBootstrap

        if not isinstance(owner, PortfolioOwnerBootstrap):
            raise TypeError("owner must be a trusted PortfolioOwnerBootstrap")
        store = owner.store
        binding = owner.binding
        actor = owner.owner_actor
        if (
            not isinstance(getattr(binding, "authority", None), str)
            or not binding.authority
            or not isinstance(getattr(binding, "credential_ref", None), str)
            or not binding.credential_ref
            or getattr(actor, "authority", None) != store.authority
            or actor.authority != binding.authority
            or getattr(actor, "credential_ref", None) != binding.credential_ref
            or not isinstance(getattr(actor, "actor", None), str)
            or not actor.actor.strip()
        ):
            raise ManagerCompositionError("bootstrap actor and binding do not identify the supplied Store authority")

        required = (
            content_contribution(),
            packet_contribution(),
            assessment_contribution(),
            authoring_contribution(),
            resource_adoption_contribution(),
        )
        registered = {item.domain_id for item in store.registered_domains()}
        missing = sorted({item.domain_id for item in required if item.domain_id not in registered})
        # The ordinary project/task readers also require the core Work, Sheet,
        # Assignments and Lifecycle descriptors already established by the
        # same owner.  These IDs are from the paired public owner modules.
        missing.extend(
            domain_id for domain_id in (WORK_DOMAIN_ID, SHEET_DOMAIN_ID, ASSIGNMENT_DOMAIN_ID, LIFECYCLE_DOMAIN_ID)
            if domain_id not in registered and domain_id not in missing
        )
        if missing:
            raise ManagerCompositionError(
                "owner Store is missing explicitly registered domains: " + ", ".join(missing)
            )

        # Obtain one finite operations bundle and reuse it for every Otto view
        # and exact-reference reader in this application.
        operations = owner.consumer_operations()
        grant = getattr(owner, "project_read_grant", None)
        if grant is not None and (
            getattr(grant, "principal", None) != actor
            or getattr(operations, "project_read_grant", None) is not grant
        ):
            raise ManagerCompositionError("project read grant is not bound to the manager principal")
        if due_port is None:
            portfolio = OttoPortfolio(operations)
        else:
            from .owner_issue_loop import compose_owner_issue_loop
            portfolio = OttoPortfolio(operations, issue_loop=compose_owner_issue_loop(
                operations, due_port, delivery=issue_delivery))
        visibility = ContextPacketService(store)
        raw_document_reader = ProjectDocumentReader(
            sheet_reader=owner.sheet,
            content_reader=owner.content,
            visibility_reader=visibility,
        )
        document_reader = _ScopedDocumentReader(raw_document_reader, grant, binding)
        raw_document_operations = ProjectDocumentOperations(
            document_reader=document_reader,
            authoring=document_authoring or DocumentAuthoringHandler(store),
            context_reader=_ScopedBacklinkReader(visibility, operations.reader, grant, binding),
            sheet_reader=owner.sheet,
            idle_lifecycle=idle_lifecycle,
        )
        document_operations = _ScopedDocumentOperations(raw_document_operations, document_reader, grant, binding)
        # Recovery discovery shares these already-composed finite readers;
        # it does not create a second document/session or Due authority.
        portfolio.document_operations = document_operations
        portfolio.due_port = due_port
        assessment_owner = AssessmentModule(store, actor=actor)
        assessment = OttoAssessment(assessment_owner, actor)

        def brief_readers(
            *,
            phase: str,
            request: Mapping[str, Any],
            assignment_ref: Mapping[str, Any],
            project_ref: Optional[Mapping[str, Any]] = None,
            task_ref: Optional[Mapping[str, Any]] = None,
            mandate_ref: Optional[Mapping[str, Any]] = None,
        ) -> Mapping[str, Any]:
            if phase == "assignment":
                requested_project = request.get("project_ref")
                if not _project_scope_allowed(grant, binding, actor, requested_project):
                    raise ManagerCompositionError("project read scope is unavailable")
                try:
                    project_identity = ResourceRef.from_dict(requested_project)
                    assignment_identity = ResourceRef.from_dict(assignment_ref)
                    assignment = owner.assignments.get(ResourceRef(
                        assignment_identity.authority, assignment_identity.kind, assignment_identity.id))
                    scope = assignment.scope
                    if scope.kind == "work.project":
                        scoped_project = scope
                    elif scope.kind == "work.task":
                        task_record = operations._owner_reader.get_record(ResourceRef(
                            scope.authority, scope.kind, scope.id))
                        parent = task_record.payload.get("project_ref") if task_record is not None else None
                        scoped_project = ResourceRef.from_dict(parent) if isinstance(parent, Mapping) else parent
                        requested_task = request.get("task_ref")
                        requested_task = ResourceRef.from_dict(requested_task) if isinstance(requested_task, Mapping) else requested_task
                        if requested_task is None or (requested_task.authority, requested_task.kind, requested_task.id) != (scope.authority, scope.kind, scope.id):
                            raise ManagerCompositionError("assignment task scope is unavailable")
                    else:
                        raise ManagerCompositionError("assignment scope is unavailable")
                    if (scoped_project.authority, scoped_project.kind, scoped_project.id) != (
                        project_identity.authority, project_identity.kind, project_identity.id):
                        raise ManagerCompositionError("assignment project scope is unavailable")
                    if request.get("task_ref") is not None and scope.kind == "work.project":
                        task_ref_value = request["task_ref"]
                        task_ref_value = ResourceRef.from_dict(task_ref_value) if isinstance(task_ref_value, Mapping) else task_ref_value
                        task_record = operations._owner_reader.get_record(ResourceRef(
                            task_ref_value.authority, task_ref_value.kind, task_ref_value.id))
                        parent = task_record.payload.get("project_ref") if task_record is not None else None
                        parent = ResourceRef.from_dict(parent) if isinstance(parent, Mapping) else parent
                        if parent is None or (parent.authority, parent.kind, parent.id) != (
                            project_identity.authority, project_identity.kind, project_identity.id):
                            raise ManagerCompositionError("task project scope is unavailable")
                except (AttributeError, TypeError, ValueError, KeyError) as exc:
                    raise ManagerCompositionError("assignment scope is unavailable") from exc
                return {
                    "assignment_reader": assignment_reader(operations, assignment_ref),
                    "resource_reader": operations.content_port,
                }
            if phase == "context":
                if project_ref is None or mandate_ref is None:
                    raise ManagerCompositionError("brief context requires exact project and mandate pins")
                values: dict[str, Any] = {
                    "project_reader": project_reader(operations, project_ref),
                    "mandate_reader": mandate_reader(operations, project_ref, mandate_ref),
                }
                if task_ref is not None:
                    values["task_reader"] = task_reader(operations, project_ref, task_ref)
                return values
            raise ManagerCompositionError("unsupported operating-brief reader phase")

        direction_operations = None
        registered_direction = {item.domain_id for item in store.registered_domains()}
        if {"otto.direction-bindings", "otto.direction-adoption"}.issubset(registered_direction):
            def direction_occurrences(*, subject_ref: Any, actor: Any) -> list[Mapping[str, Any]]:
                if due_port is None or not callable(getattr(due_port, "list_due", None)):
                    raise PermissionError("delivered occurrence reader is unavailable")
                subject = subject_ref if isinstance(subject_ref, ResourceRef) else ResourceRef.from_dict(subject_ref)
                rows = []
                for due in due_port.list_due():
                    if not isinstance(due, Mapping) or not isinstance(due.get("assignment_ref"), Mapping):
                        continue
                    try:
                        assignment = owner.assignments.command_port.get(
                            ResourceRef.from_dict(due["assignment_ref"]))
                    except Exception:
                        continue
                    responsibility = assignment.payload.get("responsibility_ref")
                    if not isinstance(responsibility, Mapping):
                        continue
                    if (responsibility.get("authority"), responsibility.get("kind"), responsibility.get("id")) != (
                            subject.authority, subject.kind, subject.id):
                        continue
                    target = due.get("target") if isinstance(due.get("target"), Mapping) else {}
                    attempt = ((due.get("host_evidence") or {}).get("gateway_attempt")
                               if isinstance(due.get("host_evidence"), Mapping) else {}) or {}
                    result = attempt.get("result") if isinstance(attempt.get("result"), Mapping) else {}
                    evidence = result.get("task_bound_evidence") if isinstance(result.get("task_bound_evidence"), Mapping) else {}
                    resources = result.get("resource_evidence") if isinstance(result.get("resource_evidence"), Mapping) else {}
                    rows.append({"schedule_id": due.get("schedule_id"),
                                 "assignment_ref": due.get("assignment_ref"),
                                 "generation": due.get("generation"),
                                 "occurrence_ref": {"schedule_id": due.get("schedule_id"),
                                                     "logical_request_key": due.get("in_flight_request") or due.get("last_completed_request")},
                                 "direction_refs": due.get("context_refs", []),
                                 "delivery_status": "delivered" if result.get("context_digest_verified") is True else due.get("completion_state", "unknown"),
                                 "delivered_brief_digest": evidence.get("delivered_brief_digest"),
                                 "delivered_brief": resources.get("brief"),
                                 "rendered_evidence": result.get("task_bound_evidence"),
                                 "retained_ref": due.get("ref") or due.get("schedule_id")})
                return rows

            direction_operations = owner.direction_surface(
                context_reader=operations.direction_context_reader,
                occurrence_reader=direction_occurrences,
                inventory_reader=lambda *, actor: [
                    item.get("project_ref") for item in portfolio.list_projects(actor=actor).get("projects", ())
                    if isinstance(item, Mapping) and isinstance(item.get("project_ref"), Mapping)
                ],
            )

        return cls(
            actor=actor.actor,
            portfolio=portfolio,
            document_operations=document_operations,
            assessment=assessment,
            # Bind the existing gate read to the same authenticated host actor.
            completion_owner=SimpleNamespace(
                completion_blockers=partial(owner.assignments.completion_blockers, actor=actor),
            ),
            operating_brief_reader_factory=brief_readers,
            direction_operations=direction_operations,
        )

    def run(self, argv: Optional[list[str]] = None) -> int:
        """Run the one accepted manager CLI with this host-bound composition."""
        from .cli import main

        return main(
            argv,
            portfolio=self.portfolio,
            document_operations=self.document_operations,
            assessment=self.assessment,
            completion_owner=self.completion_owner,
            operating_brief_reader_factory=self._operating_brief_reader_factory,
            direction_operations=self.direction_operations,
            bound_actor=self._actor,
        )


__all__ = ["ManagerApplication", "ManagerCompositionError"]
