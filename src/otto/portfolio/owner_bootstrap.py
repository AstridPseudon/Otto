"""Trusted owner composition for the finite OTT-03 create-and-open bridge.

Only :class:`PortfolioOwnerBootstrap` retains Herzchen owner facades.  The
object returned by ``consumer_operations`` contains serialized finite clients,
one read-only reader, and the explicit authentication binding.
"""

from __future__ import annotations

from hashlib import sha256
from inspect import Parameter, signature
import json
from typing import Any, Mapping, Optional, Protocol

from .herzchen_binding import FiniteWorkOperations, HerzchenBindingConfig, ProjectReadGrant, _json_value


def _read_current_result_task(scope_reader: Any, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any]) -> Any:
    """Reuse owner membership semantics while pinning both current revisions."""
    from types import SimpleNamespace
    from .owner_readers import project_reader, task_reader
    operations = SimpleNamespace(reader=scope_reader)
    identity = lambda ref: {key: ref[key] for key in ("authority", "kind", "id")}
    try:
        project = project_reader(operations, project_ref)(identity(project_ref))
        task = task_reader(operations, project_ref, task_ref)(identity(task_ref))
    except (ValueError, KeyError, TypeError) as exc:
        raise PermissionError("result capability project/task scope changed") from exc
    if project["ref"] != dict(project_ref) or task["ref"] != dict(task_ref) or task["project_ref"] != dict(project_ref):
        raise PermissionError("result capability project/task revision changed")
    return task


class _BoundResultAccess:
    """Owner-issued result access for one admitted assignment generation/key."""

    def __init__(self, *, assignments: Any, reader: Any, scope_reader: Any, actor: Any,
                 project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                 assignment_ref: Mapping[str, Any], generation: int, logical_request_key: str) -> None:
        from herzchen.contracts import ResourceRef

        self.__assignments, self.__reader, self.__actor = assignments, reader, actor
        self.__scope_reader = scope_reader
        self.__project = ResourceRef.from_dict(project_ref)
        self.__task = ResourceRef.from_dict(task_ref)
        self.__assignment = ResourceRef.from_dict(assignment_ref)
        self.__generation, self.__key = generation, logical_request_key
        if (self.__project.kind != "work.project" or self.__task.kind != "work.task"
                or self.__assignment.kind != "wrk.assignment"
                or any(ref.authority != actor.authority for ref in (self.__project, self.__task, self.__assignment))
                or not isinstance(generation, int) or isinstance(generation, bool) or generation < 1
                or not isinstance(logical_request_key, str) or not logical_request_key.strip()):
            raise ValueError("invalid result capability binding")
        self.get(assignment_ref)

    def get(self, target: Any) -> Any:
        if _json_value(target) != self.__assignment.to_dict():
            raise PermissionError("result capability assignment mismatch")
        _read_current_result_task(self.__scope_reader, self.__project.to_dict(), self.__task.to_dict())
        current = self.__assignments.get(self.__assignment)
        scope = _json_value(current.scope)
        task_scope = scope == self.__task.to_dict()
        project_worker_scope = (
            not task_scope and isinstance(scope, Mapping) and getattr(current, "role", None) in {"worker", "executor"}
            and all(scope.get(key) == self.__project.to_dict()[key] for key in ("authority", "kind", "id"))
        )
        # A project executor is still issued only this exact task and request;
        # publication below never accepts sibling-task or other-key evidence.
        if (_json_value(current.ref) != self.__assignment.to_dict()
                or current.generation != self.__generation
                or not (task_scope or project_worker_scope)):
            raise PermissionError("result capability assignment is stale or out of scope")
        return current

    def list_observations(self, target: Any, *, kind: str) -> Any:
        self.get(target)
        if kind != "result":
            raise PermissionError("result capability observation kind mismatch")
        return tuple(value for value in self.__assignments.list_observations(self.__assignment, kind=kind)
                     if value.generation == self.__generation)

    def append_result(self, target: Any, value: Any, *, expected_generation: int,
                      logical_request_key: str, actor: Any) -> Any:
        self.get(target)
        expected = {"project_ref": self.__project.to_dict(), "task_ref": self.__task.to_dict(),
                    "assignment_ref": self.__assignment.to_dict(), "generation": self.__generation,
                    "logical_request_key": self.__key}
        if (expected_generation != self.__generation or logical_request_key != self.__key or actor != self.__actor
                or not isinstance(value, Mapping) or any(value.get(key) != val for key, val in expected.items())):
            raise PermissionError("result publication differs from owner capability")
        return self.__assignments.append_result(self.__assignment, value, expected_generation=expected_generation,
            logical_request_key=logical_request_key, actor=self.__actor)

    def get_receipt(self, logical_request_key: str) -> Any:
        from herzchen.contracts import ResourceRef

        if logical_request_key != self.__key:
            raise PermissionError("result capability request mismatch")
        self.get(self.__assignment)
        receipt = self.__reader.get_receipt(self.__key)
        if receipt is None:
            return None
        value = _json_value(receipt)
        try:
            result = ResourceRef.from_dict(value["result_ref"])
            target = ResourceRef.from_dict(value["target"])
            if (value.get("logical_request_key") != self.__key or value.get("operation") != "work.result.append"
                    or value.get("status") != "committed" or result.kind != "wrk.result"
                    or result.authority != self.__actor.authority or result.revision is None
                    or (target.authority, target.kind, target.id) != (result.authority, result.kind, result.id)):
                raise ValueError("invalid bound result receipt")
            self.__record(result)
        except (TypeError, ValueError, KeyError) as error:
            raise PermissionError("result receipt differs from owner capability") from error
        return receipt

    def __record(self, ref: Any) -> Any:
        record = self.__reader.get_record(ref)
        payload = _json_value(getattr(record, "payload", None))
        if (_json_value(getattr(record, "ref", None)) != ref.to_dict() or not isinstance(payload, Mapping)
                or payload.get("record_type") != "work.observation" or payload.get("observation_kind") != "result"
                or payload.get("assignment") != self.__assignment.to_dict() or payload.get("generation") != self.__generation):
            raise PermissionError("result record differs from owner capability")
        value = payload.get("value")
        expected = {"project_ref": self.__project.to_dict(), "task_ref": self.__task.to_dict(),
                    "assignment_ref": self.__assignment.to_dict(), "generation": self.__generation,
                    "logical_request_key": self.__key}
        if not isinstance(value, Mapping) or any(value.get(key) != val for key, val in expected.items()):
            raise PermissionError("result value differs from owner capability")
        return record

    def get_record(self, ref: Any) -> Any:
        receipt = self.get_receipt(self.__key)
        if receipt is None or _json_value(ref) != _json_value(receipt)["result_ref"]:
            raise PermissionError("result capability reference mismatch")
        return self.__record(ref)


class CreateAndOpenCommandPort(Protocol):
    """Finite serialized consumer operation implemented by the owner bridge."""

    def create_pending_and_open(
        self,
        *,
        actor: Any,
        request_id: str,
        title: Optional[str],
        outcome: str,
        metadata: Mapping[str, Any],
        template_resource: Optional[Mapping[str, Any]] = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        ...


def _call_owner_materializer(materializer: Any, **values: Any) -> Any:
    """Invoke one bootstrap-owned hook without accepting it over transport."""

    parameters = signature(materializer).parameters.values()
    accepts_kwargs = any(item.kind == Parameter.VAR_KEYWORD for item in parameters)
    if accepts_kwargs:
        return materializer(**values)
    accepted = {item.name for item in parameters}
    return materializer(**{key: value for key, value in values.items() if key in accepted})


class _CreateAndOpenOwnerEngine:
    """Owner-only composition over the accepted ProjectSheet and EDT services."""

    def __init__(self, store: Any, *, sheet: Any, authoring: Any, materializer: Any = None) -> None:
        self.reader = store.consumer()
        self.authority = store.authority
        self.sheet = sheet
        self.authoring = authoring
        self.materializer = materializer

    def _planned_project_ref(self, project_request_key: str) -> Any:
        from herzchen.contracts import ResourceRef

        # ProjectSheet.create_pending has a stable public logical-key identity
        # contract.  The post-create identity check below fails closed if that
        # accepted contract ever changes.
        project_id = "project-" + sha256(
            (self.authority + ":" + project_request_key).encode("utf-8")
        ).hexdigest()[:28]
        return ResourceRef(self.authority, "work.project", project_id)

    @staticmethod
    def _same_identity(left: Any, right: Any) -> bool:
        return (
            getattr(left, "authority", None),
            getattr(left, "kind", None),
            getattr(left, "id", None),
        ) == (
            getattr(right, "authority", None),
            getattr(right, "kind", None),
            getattr(right, "id", None),
        )

    @staticmethod
    def _json_mapping(value: Any, field: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError(field + " must be a JSON object")
        try:
            result = json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError) as exc:
            raise ValueError(field + " must contain only JSON values") from exc
        if not isinstance(result, dict):
            raise TypeError(field + " must be a JSON object")
        return result

    @classmethod
    def _selected_template(
        cls,
        resource: Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]],
    ) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        """Construct and render one declared resource before authoring writes."""

        from herzchen.contracts import ResourceRef
        from herzchen.packs.templates import WorkTemplate, render_template, validate_template

        value = cls._json_mapping(resource, "template_resource")
        invocation = cls._json_mapping(
            {} if parameters is None else parameters, "template_parameters"
        )
        allowed = {"kind", "id", "revision", "version", "parameters", "seed", "source_ref"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ValueError("template_resource has unsupported fields: " + ", ".join(unexpected))
        if value.get("kind", "work_template") != "work_template":
            raise ValueError("template_resource.kind must be work_template")
        template_id = value.get("id")
        revision = value.get("revision", value.get("version"))
        if "revision" in value and "version" in value and value["revision"] != value["version"]:
            raise ValueError("template_resource revision and version must agree")
        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError("template_resource.id must be non-blank text")
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("template_resource.revision or version must be non-blank text")
        schema = value.get("parameters")
        seed = value.get("seed")
        if not isinstance(schema, Mapping):
            raise ValueError("template_resource.parameters must be an object")
        if not isinstance(seed, Mapping):
            raise ValueError("template_resource.seed must be an object")
        source_ref = value.get("source_ref")
        if source_ref is not None:
            if not isinstance(source_ref, Mapping):
                raise ValueError("template_resource.source_ref must be a resource object")
            source_ref = ResourceRef.from_dict(source_ref)
        template = validate_template(
            WorkTemplate(template_id, revision, dict(schema), dict(seed), source_ref=source_ref)
        )
        render_template(template, invocation)
        return template, value, invocation

    @staticmethod
    def _handle_value(handle: Any) -> Optional[dict[str, Any]]:
        if handle is None:
            return None
        return {
            "scope": _json_value(handle.scope),
            "target_scope": _json_value(handle.target_scope),
            "target_kind": handle.target_kind,
            "actor": _json_value(handle.actor),
            "session_id": handle.session_id,
            "token": handle.token,
            "fence": handle.fence,
            "base_revision": handle.base_revision,
            "checkout_path": handle.checkout_path,
        }

    def create_pending_and_open(
        self,
        *,
        actor: Any,
        request_id: str,
        title: Optional[str],
        outcome: str,
        metadata: Mapping[str, Any],
        template_resource: Optional[Mapping[str, Any]] = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Run the one admitted ProjectSheet creation callback inside EDT."""

        from herzchen.contracts import AuthenticatedActor, ResourceRef

        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        if actor.authority != self.authority:
            raise ValueError("actor authority does not belong to this owner")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be non-blank")
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be text or None")
        if not isinstance(outcome, str):
            raise TypeError("outcome must be text")
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        selected = None
        selected_resource = None
        selected_parameters: dict[str, Any] = {}
        if template_resource is not None:
            selected, selected_resource, selected_parameters = self._selected_template(
                template_resource, template_parameters
            )
        elif template_parameters not in (None, {}):
            raise ValueError("template_parameters require a selected template_resource")

        project_key = request_id + ":project"
        target = self._planned_project_ref(project_key)

        def create_project(*_args: Any, **_kwargs: Any) -> ResourceRef:
            created = self.sheet.create_pending(
                title=title,
                outcome=outcome,
                creator=actor,
                curator=actor,
                metadata=dict(metadata),
                logical_request_key=project_key,
                actor=actor,
            )
            project_ref = created.project.ref
            if not self._same_identity(project_ref, target):
                raise RuntimeError("ProjectSheet returned a project identity outside the reserved authoring scope")
            if selected is not None:
                applied = self.sheet.command_port.instantiate_new_template(
                    selected,
                    selected_parameters,
                    project=project_ref,
                    logical_request_key=request_id + ":template",
                    actor=actor,
                )
                project_ref = applied.project.ref
            return project_ref

        def materialize(checkout: Any, initial_bytes: bytes, *, project: Any) -> Mapping[str, Any]:
            if not isinstance(project, ResourceRef) or not self._same_identity(project, target):
                raise RuntimeError("ProjectSheet returned a project identity outside the reserved authoring scope")
            if self.materializer is None:
                return {"project": project}
            observed = _call_owner_materializer(
                self.materializer,
                checkout=checkout,
                initial_bytes=initial_bytes,
                project=project,
            )
            if isinstance(observed, Mapping):
                result = dict(observed)
                result["project"] = project
                return result
            return {"path": observed, "project": project}

        logical_request = {
            "title": title,
            "outcome": outcome,
            "metadata": dict(metadata),
        }
        if selected is not None:
            logical_request.update({
                "template_resource": selected_resource,
                "template_parameters": selected_parameters,
            })
        planned_project = ResourceRef(target.authority, target.kind, target.id, "rev-1")
        opened = self.authoring.create_and_open(
            target,
            actor,
            request_id=request_id,
            create_project=create_project,
            target_kind="project-sheet",
            base_revision="initial",
            initial_content=b"",
            pending=True,
            purpose="otto",
            activity="editing",
            materialize=materialize,
            project={
                "ref": planned_project,
                "otto_create_and_open_request": logical_request,
            },
        )

        project_record = self.reader.get_identity(target)
        project_ref = None if project_record is None else project_record.ref
        scope_ref = ResourceRef(self.authority, "authoring-scope", target.id)
        scope_record = self.reader.get_identity(scope_ref)
        status = opened.status
        if (
            status == "replayed"
            and scope_record is not None
            and scope_record.payload.get("status") == "saved_edit_not_opened"
        ):
            status = "saved_project_edit_not_opened"
        handle = opened.handle
        template_receipt = self.reader.get_receipt(request_id + ":template")
        task_refs = []
        if project_record is not None:
            task_refs = list(project_record.payload.get("tasks", ()))
        return {
            "status": status,
            "scope": opened.scope,
            "project_ref": project_ref or opened.project_ref,
            "session_id": None if handle is None else handle.session_id,
            "handle": self._handle_value(handle),
            "checkout": opened.checkout,
            "target_kind": None if handle is None else handle.target_kind,
            "base_revision": None if handle is None else handle.base_revision,
            "template": None if selected is None else selected,
            "template_receipt": template_receipt,
            "task_refs": task_refs,
            "error": opened.error,
            "recovery_pending": False,
            "recovery_status": (
                "saved_project_edit_not_opened"
                if status == "saved_project_edit_not_opened"
                else "not_requested"
            ),
        }


def _create_bridge_type() -> type[Any]:
    from herzchen.command_ports import command_facade

    return command_facade(_CreateAndOpenOwnerEngine, "otto.portfolio.create-and-open")


class PortfolioOwnerBootstrap:
    """Trusted owner graph; never pass this object to an Otto consumer."""

    __slots__ = (
        "store",
        "binding",
        "owner_actor",
        "graph",
        "sheet",
        "content",
        "assignments",
        "lifecycle",
        "authoring",
        "create_and_open_bridge",
        "orchestration_port",
        "orchestration_portfolio",
        "project_read_grant",
    )

    def issue_attention_assignment_guard(self, scope: Mapping[str, Any], *, attention_authority: str) -> Any:
        """Issue one original-owner transaction guard, retaining Store custody."""
        from .attention_binding import ExternalAssignmentGuard, _GUARD_TOKEN
        return ExternalAssignmentGuard(self, scope, attention_authority, _token=_GUARD_TOKEN)

    def __init__(
        self,
        store: Any,
        *,
        binding: HerzchenBindingConfig,
        owner_actor: str,
        materializer: Any = None,
        portfolio_ref: Any = None,
        main_assignment_ref: Any = None,
        allowed_creator_ids: tuple[str, ...] = (),
        privileged_actor_ids: tuple[str, ...] = (),
        expected_main_principal: Optional[str] = None,
        project_read_grant: Optional[ProjectReadGrant] = None,
    ) -> None:
        from herzchen.authoring import AuthoringSessionService
        from herzchen.content import ContentCommandHandler
        from herzchen.domains.work import WorkGraph, register_orchestration
        from herzchen.domains.work.assignments import ResponsibilityAssignments
        from herzchen.domains.work.lifecycle import ProjectLifecycle
        from herzchen.domains.work.sheet import ProjectSheet
        from herzchen.kernel.store import Store

        if not isinstance(store, Store):
            raise TypeError("store must be the trusted Herzchen Store owner")
        if not isinstance(binding, HerzchenBindingConfig):
            raise TypeError("binding must be HerzchenBindingConfig")
        authenticated = binding.authenticated_actor(owner_actor)
        if authenticated.authority != store.authority:
            raise ValueError("binding authority does not belong to the supplied store")
        if project_read_grant is not None and (
            not isinstance(project_read_grant, ProjectReadGrant)
            or project_read_grant.principal != authenticated
        ):
            raise ValueError("project read grant must bind the authenticated owner principal")

        self.store = store
        self.binding = binding
        self.owner_actor = authenticated
        self.project_read_grant = project_read_grant
        self.graph = WorkGraph(store, actor=authenticated)
        # Assignment instruction adoption is an optional late-registered
        # port.  Opening WorkGraph first preserves compatibility with owner
        # databases persisted under the old assignment descriptor digest.
        from herzchen.domains import work as work_domain
        register_resources = getattr(work_domain, "register_assignment_resources", None)
        if register_resources is not None:
            register_resources(store)
        self.sheet = ProjectSheet(store, actor=authenticated)
        self.content = ContentCommandHandler(store)
        self.assignments = ResponsibilityAssignments(store, actor=authenticated)
        self.lifecycle = ProjectLifecycle(store, actor=authenticated, delegation_issuer=authenticated)
        self.authoring = AuthoringSessionService(store)
        orchestration_port = None
        if portfolio_ref is not None or main_assignment_ref is not None:
            if portfolio_ref is None or main_assignment_ref is None:
                raise ValueError("portfolio_ref and main_assignment_ref must be supplied together")
            from herzchen.domains.work.orchestration import Orchestration

            register_orchestration(store)
            orchestration = Orchestration(
                store,
                actor=authenticated,
                portfolio_ref=portfolio_ref,
                main_assignment_ref=main_assignment_ref,
                allowed_creator_ids=allowed_creator_ids,
                privileged_actor_ids=privileged_actor_ids,
                expected_main_principal=expected_main_principal,
            )
            orchestration_port = orchestration.command_port
        self.orchestration_port = orchestration_port
        self.orchestration_portfolio = portfolio_ref
        bridge_type = _create_bridge_type()
        self.create_and_open_bridge = bridge_type(
            store,
            sheet=self.sheet,
            authoring=self.authoring,
            materializer=materializer,
        )

    def consumer_operations(self) -> FiniteWorkOperations:
        """Return only finite serialized/read clients and typed binding data."""

        from herzchen.command_ports import connect_consumer_facade

        transport = self.create_and_open_bridge.consumer_transport()
        create_open_port = connect_consumer_facade(transport.to_dict())
        return FiniteWorkOperations(
            port=self.graph.command_port,
            reader=self.graph.reader,
            binding=self.binding,
            sheet_port=self.sheet.command_port,
            content_port=self.content.command_port,
            assignments_port=self.assignments.command_port,
            lifecycle_port=self.lifecycle.command_port,
            authoring_port=self.authoring.command_port,
            create_open_port=create_open_port,
            orchestration_port=self.orchestration_port,
            orchestration_portfolio=self.orchestration_portfolio,
            project_read_grant=self.project_read_grant,
        )

    def portfolio(self, *, due_port: Any, issue_delivery: Any = None) -> Any:
        """Issue the ordinary portfolio API with owner-backed check-in/issue ports."""
        from .intake import OttoPortfolio
        from .owner_issue_loop import compose_owner_issue_loop

        operations = self.consumer_operations()
        return OttoPortfolio(operations, issue_loop=compose_owner_issue_loop(
            operations, due_port, delivery=issue_delivery,
        ))

    def manager_application(self) -> Any:
        """Compose the ordinary finite manager entry over this trusted owner."""
        from .manager_application import ManagerApplication

        return ManagerApplication.from_owner(self)

    def manager_assessment(self, *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                           manager_assignment_ref: Mapping[str, Any], manager_actor: str,
                           manager_generation: int) -> Any:
        """Issue finite assessment commands for the current assigned manager/task."""
        from herzchen.contracts import ResourceRef
        from herzchen.domains.assessment import AssessmentModule
        from .assessment import OttoAssessment
        from .manager_assessment_command import ManagerAssessmentCommands
        project, task, assignment = (ResourceRef.from_dict(value) for value in
                                    (project_ref, task_ref, manager_assignment_ref))
        actor = self.binding.authenticated_actor(manager_actor)
        if (project.kind != "work.project" or task.kind != "work.task"
                or assignment.kind != "wrk.assignment"
                or any(ref.authority != self.owner_actor.authority or not ref.revision
                       for ref in (project, task, assignment))
                or type(manager_generation) is not int or manager_generation < 1):
            raise ValueError("manager assessment requires exact owner scope and generation")

        def authorize() -> None:
            grant = self.project_read_grant
            if grant is None or grant.principal != self.owner_actor or not grant.allows(project):
                raise PermissionError("manager assessment project is outside the owner grant")
            _read_current_result_task(self.graph.reader, project.to_dict(), task.to_dict())
            current = self.assignments.command_port.get(assignment)
            if (current.ref != assignment or current.generation != manager_generation
                    or current.role != "manager" or current.principal != actor.actor
                    or (current.scope.authority, current.scope.kind, current.scope.id)
                    != (project.authority, project.kind, project.id)
                    or current.status.value in {"cancelled", "reassigned"}):
                raise PermissionError("manager assessment assignment is stale or out of scope")

        authorize()
        return ManagerAssessmentCommands(
            assessment=OttoAssessment(AssessmentModule(self.store, actor=actor), actor),
            reader=self.graph.reader, actor=actor, task=task, assignment=assignment,
            generation=manager_generation, authorize=authorize)

    def execution_application(self, *, due_port: Any, adapter: Any, clock: Any = None,
                              manager_actor: str | None = None) -> Any:
        """Issue maintained execution commands over the existing finite ports."""
        from .execution import ExecutionApplication
        runtime = self.role_runtime(due_port=due_port, adapter=adapter)
        kwargs = {} if clock is None else {"clock": clock}
        return ExecutionApplication(portfolio=runtime.portfolio,
            assignments=self.assignments.command_port, due_port=due_port,
            binding=self.binding, actor=self.owner_actor.actor, runtime=runtime,
            manager_actor=manager_actor, **kwargs)

    def shared_attention_port(self, *, due_port: Any) -> Any:
        """Issue durable scheduled notifications through the existing DAT owner."""
        from herzchen.content.packets import ContextPacketService
        from herzchen.contracts import ResourceRef, TransactionContext
        from otto.attention import SerializedAttentionPort
        import hashlib
        import json
        packets = ContextPacketService(self.store).command_port
        actor, grant = self.owner_actor, self.project_read_grant

        def create(request: Mapping[str, Any]) -> Mapping[str, Any]:
            due = due_port.read_due(request.get("schedule_id"))
            project = ResourceRef(actor.authority, "work.project", request.get("project_ref"))
            if (grant is None or not grant.allows(project) or not isinstance(due, Mapping)
                    or due.get("lifecycle_owner") != actor.actor
                    or due.get("in_flight_request") != request.get("request_id")
                    or any(due.get(field) != request.get(field) for field in
                           ("recipient", "generation", "project_ref", "manager_ref", "target", "role"))):
                raise PermissionError("attention request does not match the current granted owner occurrence")
            digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":")).encode()).hexdigest()
            return packets.create_attention(request, TransactionContext(actor, request["request_id"], digest))
        from .owner_readers import json_value
        return SerializedAttentionPort(create, lambda recipient: json_value(packets.list_attention(recipient)))

    def role_runtime(self, *, due_port: Any, adapter: Any, runtime_probe: Any = None,
                     issue_delivery: Any = None) -> Any:
        """Compose a role runtime from finite clients without exposing Store.

        The caller supplies the already-issued finite DueRecord port and host
        adapter.  The returned consumer runtime retains only the operation
        reader, command facades, and due port needed for its bounded routes.
        """
        from ..agents.owner_runtime import CanonicalRoleRuntime
        from ..agents.gateway import HerzchenAttemptCapture
        portfolio = self.portfolio(due_port=due_port, issue_delivery=issue_delivery)
        operations = portfolio.operations
        assignments, result_reader = self.assignments.command_port, self.graph.reader
        owner_actor, grant, scope_reader = self.owner_actor, self.project_read_grant, operations.reader

        def result_capture(*, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                           assignment_ref: Mapping[str, Any], generation: int, logical_request_key: str) -> Any:
            from herzchen.contracts import ResourceRef

            project, task = ResourceRef.from_dict(project_ref), ResourceRef.from_dict(task_ref)
            if grant is None or grant.principal != owner_actor or not grant.allows(project):
                raise PermissionError("result capability requires the admitted project/task scope")
            _read_current_result_task(scope_reader, project_ref, task_ref)
            access = _BoundResultAccess(assignments=assignments, reader=result_reader, scope_reader=scope_reader,
                actor=owner_actor, project_ref=project_ref, task_ref=task_ref, assignment_ref=assignment_ref,
                generation=generation, logical_request_key=logical_request_key)
            capture = HerzchenAttemptCapture(access, access, actor=owner_actor)
            error = capture.validate_generation(assignment_ref, generation)
            if error:
                raise PermissionError(error)
            return capture

        return CanonicalRoleRuntime(
            operations=operations, portfolio=portfolio, due_port=due_port,
            adapter=adapter, actor=self.owner_actor.actor, runtime_probe=runtime_probe,
            result_capture_factory=result_capture,
        )


__all__ = ["CreateAndOpenCommandPort", "PortfolioOwnerBootstrap"]
