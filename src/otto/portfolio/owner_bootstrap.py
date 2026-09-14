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

from .herzchen_binding import FiniteWorkOperations, HerzchenBindingConfig, _json_value


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
        "authoring",
        "create_and_open_bridge",
    )

    def __init__(
        self,
        store: Any,
        *,
        binding: HerzchenBindingConfig,
        owner_actor: str,
        materializer: Any = None,
    ) -> None:
        from herzchen.authoring import AuthoringSessionService
        from herzchen.content import ContentCommandHandler
        from herzchen.domains.work import WorkGraph
        from herzchen.domains.work.assignments import ResponsibilityAssignments
        from herzchen.domains.work.sheet import ProjectSheet
        from herzchen.kernel.store import Store

        if not isinstance(store, Store):
            raise TypeError("store must be the trusted Herzchen Store owner")
        if not isinstance(binding, HerzchenBindingConfig):
            raise TypeError("binding must be HerzchenBindingConfig")
        authenticated = binding.authenticated_actor(owner_actor)
        if authenticated.authority != store.authority:
            raise ValueError("binding authority does not belong to the supplied store")

        self.store = store
        self.binding = binding
        self.owner_actor = authenticated
        self.graph = WorkGraph(store, actor=authenticated)
        self.sheet = ProjectSheet(store, actor=authenticated)
        self.content = ContentCommandHandler(store)
        self.assignments = ResponsibilityAssignments(store, actor=authenticated)
        self.authoring = AuthoringSessionService(store)
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
            authoring_port=self.authoring.command_port,
            create_open_port=create_open_port,
        )


__all__ = ["CreateAndOpenCommandPort", "PortfolioOwnerBootstrap"]
