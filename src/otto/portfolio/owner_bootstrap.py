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


def _read_current_result_task(scope_reader: Any, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                              *, allow_task_content_revision: bool = False) -> Any:
    """Reuse owner membership semantics, optionally accepting metadata-only task revisions."""
    from types import SimpleNamespace
    from .owner_readers import project_reader, task_reader
    operations = SimpleNamespace(reader=scope_reader)
    identity = lambda ref: {key: ref[key] for key in ("authority", "kind", "id")}
    try:
        project = project_reader(operations, project_ref)(identity(project_ref))
        task = task_reader(operations, project_ref, task_ref)(identity(task_ref))
    except (ValueError, KeyError, TypeError) as exc:
        raise PermissionError("result capability project/task scope changed") from exc
    task_ref_matches = task["ref"] == dict(task_ref)
    if allow_task_content_revision and not task_ref_matches:
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.admission import task_content_matches
        try:
            pinned = ResourceRef.from_dict(task_ref)
            current = ResourceRef.from_dict(task["ref"])
            task_ref_matches = task_content_matches(scope_reader, pinned, task["payload"], current_ref=current)
        except (TypeError, ValueError, KeyError):
            task_ref_matches = False
    if project["ref"] != dict(project_ref) or not task_ref_matches or task["project_ref"] != dict(project_ref):
        raise PermissionError("result capability project/task revision changed")
    return task


class _BoundResultAccess:
    """Owner-issued result access for one admitted assignment generation/key."""

    def __init__(self, *, assignments: Any, reader: Any, scope_reader: Any, actor: Any,
                 project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                 assignment_ref: Mapping[str, Any], generation: int, logical_request_key: str,
                 allow_project_manager: bool = False) -> None:
        from herzchen.contracts import ResourceRef

        self.__assignments, self.__reader, self.__actor = assignments, reader, actor
        self.__scope_reader = scope_reader
        self.__project = ResourceRef.from_dict(project_ref)
        self.__task = ResourceRef.from_dict(task_ref)
        self.__assignment = ResourceRef.from_dict(assignment_ref)
        if type(allow_project_manager) is not bool:
            raise TypeError("manager result capability must be explicit")
        self.__allow_project_manager = allow_project_manager
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
            not task_scope and isinstance(scope, Mapping) and getattr(current, "role", None) in ({"worker", "executor", "manager"} if self.__allow_project_manager else {"worker", "executor"})
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


from .project_folder import ProjectFolderOwner


class _CreateAndOpenOwnerEngine(ProjectFolderOwner):
    """Owner-only composition over the accepted ProjectSheet and EDT services."""

    def __init__(self, store: Any, *, sheet: Any, authoring: Any, materializer: Any = None,
                 operator_actor: Any = None,
                 folder_transport_request_bytes: int = 16 * 1024) -> None:
        from .project_folder import MAX_OPERATION_BYTES, MEASURED_LIVE_REQUEST_BYTES
        if type(folder_transport_request_bytes) is not int or not MEASURED_LIVE_REQUEST_BYTES <= folder_transport_request_bytes <= MAX_OPERATION_BYTES:
            raise ValueError("qualified folder transport bound required")
        self.folder_transport_request_bytes = folder_transport_request_bytes
        self.reader = store.consumer()
        self.authority = store.authority
        self.sheet = sheet
        self.operator_actor = operator_actor
        self.authoring = authoring
        self.materializer = materializer
        from herzchen.content import ContentCommandHandler
        from herzchen.content.packets import ContextPacketService
        from herzchen.content import domain_contribution as content_contribution
        self.content = ContentCommandHandler(store)
        # Folder visibility only needs the already admitted DAT domain.
        # Its sealed handler cannot mutate the unrelated attention domain.
        self.folder_visibility = ContextPacketService(store.domain_handler((content_contribution(),)))

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

    def _project_draft(self, project: Any, request_id: str, actor: Any = None) -> dict[str, Any]:
        """Generate semantic bytes and CAS pins from the same owner read."""
        view = _json_value(self.sheet.export(project))
        authored = view["project"]["authored"]
        # Operational metadata and observations never enter project.json.
        fields = ("title", "outcome", "scope", "approach", "acceptance", "protocol", "custom")
        draft = {key: authored[key] for key in fields if key in authored}
        tasks = []
        bases = {}
        for task in view["tasks"]:
            ref = task["ref"]
            bases[ref["id"]] = ref["revision"]
            value = {key: val for key, val in task["authored"].items()
                     if key in view["definitions"]["task_editable"] and key not in {"metadata", "fields", "lifecycle"}}
            value["id"] = ref["id"]
            tasks.append(value)
        draft["tasks"] = tasks
        files, documents = self._folder_tree(project, actor) if actor is not None else ({}, {})
        return {"document_files": files, "document_bases": documents,
                "ref": view["project"]["ref"], "base_task_revisions": bases,
                "project_json": draft, "open_request_key": request_id}

    @staticmethod
    def _draft_bytes(draft: Mapping[str, Any]) -> bytes:
        return json.dumps(dict(draft), ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")

    def open_project_sheet(self, *, project_ref: Any, actor: Any, request_id: str) -> Mapping[str, Any]:
        """Open a semantic project.json projection; generated pins stay in EDT."""
        from herzchen.contracts import AuthenticatedActor, ResourceRef
        from herzchen.kernel import VersionConflictError
        if not isinstance(actor, AuthenticatedActor) or actor.authority != self.authority:
            raise PermissionError("project authoring requires an owner-bound actor")
        ref = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        if ref.authority != self.authority or ref.kind != "work.project" or ref.revision is None:
            raise ValueError("project checkout requires an exact owner project revision")
        scope = ResourceRef(self.authority, "authoring-scope", ref.id)
        previous = self.reader.get_identity(scope)
        prior = self.reader.get_receipt(request_id)
        if prior is not None:
            state = None if previous is None else previous.payload.get("project")
            if (not isinstance(state, Mapping) or state.get("open_request_key") != request_id
                    or state.get("ref") != ref.to_dict()):
                from herzchen.contracts import ReplayConflictError
                raise ReplayConflictError("checkout key differs from the retained project session")
        else:
            state = self._project_draft(ref, request_id, actor=actor)
            if state["ref"] != ref.to_dict():
                raise VersionConflictError("project checkout base is stale")

        def materialize(checkout: Any, initial_bytes: bytes) -> Mapping[str, Any]:
            result = {} if self.materializer is None else _call_owner_materializer(
                self.materializer, checkout=checkout, initial_bytes=initial_bytes, project=ref)
            result = dict(result) if isinstance(result, Mapping) else {"path": result}
            result["project"] = state
            return self._folder_materialize(result, state.get("document_files", {}))

        opened = self.authoring.open(ref, actor, request_id=request_id, target_kind="project-sheet",
            base_revision=ref.revision, initial_content=self._draft_bytes(state["project_json"]),
            project=state, materialize=materialize, pending=True, purpose="otto", activity="editing")
        return {"outcome": opened.status, "project_ref": ref.to_dict(),
                "session_id": None if opened.handle is None else opened.handle.session_id,
                "target_kind": "project-sheet", "base_revision": ref.revision,
                "project_json": state["project_json"], "document_files": state.get("document_files", {}),
                "error": opened.error,
                "execution": False, "dispatch": False}

    def finish_project_sheet(self, *, project_ref: Any, session_id: str, project_json: Mapping[str, Any],
                             actor: Any, request_id: str) -> Mapping[str, Any]:
        """Apply one WRK sheet and retire its EDT session in the common transaction."""
        from herzchen.contracts import AuthoringCheckout, ResourceRef
        from herzchen.authoring.sessions import SessionHandle
        from herzchen.kernel import VersionConflictError
        ref = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        if ref.authority != self.authority or ref.kind != "work.project" or ref.revision is None:
            raise ValueError("project check-in requires its exact checkout project revision")
        record = self.reader.get_identity(ResourceRef(self.authority, "authoring-scope", ref.id))
        state = None if record is None else record.payload.get("project")
        if not isinstance(state, Mapping) or state.get("ref") != ref.to_dict() or "base_task_revisions" not in state:
            raise PermissionError("project check-in has no matching owner-issued checkout")
        checkout = AuthoringCheckout.from_dict(record.payload["checkout"])
        if checkout.actor != actor or checkout.session_id != session_id:
            raise PermissionError("project check-in actor or session differs from checkout")
        handle = SessionHandle(ResourceRef(self.authority, "authoring-scope", ref.id), checkout.target_scope, checkout.target_kind, actor,
            session_id, checkout.token, checkout.fence, checkout.base_revision, record.payload.get("checkout_path"))
        data = self._draft_bytes(self._json_mapping(project_json, "project_json"))

        if self.reader.get_receipt(request_id) is None:
            current = _json_value(self.sheet.export(ref))
            bases = {task["ref"]["id"]: task["ref"]["revision"] for task in current["tasks"]}
            if current["project"]["ref"] != state["ref"] or bases != state["base_task_revisions"]:
                return {"outcome": "conflict", "error": {"code": "stale_base", "message": "project or task checkout bases are stale"},
                        "session_id": session_id, "execution": False, "dispatch": False}

        def apply(snapshot: Any, _checkout: Any, **_: Any) -> None:
            self.authoring.authorize_mutation(handle, checkout.target_scope, token=handle.token, fence=handle.fence,
                expected_base_revision=handle.base_revision)
            current = _json_value(self.sheet.export(ref))
            bases = {task["ref"]["id"]: task["ref"]["revision"] for task in current["tasks"]}
            if bases != state["base_task_revisions"]:
                raise VersionConflictError("project task bases are stale")
            self.sheet.apply(ref, json.loads(snapshot.data.decode("utf-8")), actor=actor,
                base_revision=ref.revision, logical_request_key=request_id + ":sheet")

        finished = self.authoring.finish(handle, request_id=request_id, mode="manual", capture=data,
            apply=apply, pending=False, expected_base_revision=handle.base_revision,
            snapshot_digest=sha256(data).hexdigest())
        sheet_receipt = self.reader.get_receipt(request_id + ":sheet")
        snapshot_ref = (finished.final_snapshot.ref if finished.final_snapshot is not None
                        else None if finished.checkout is None else finished.checkout.final_snapshot_ref)
        return {"outcome": finished.status, "project_ref": _json_value(sheet_receipt.result_ref if sheet_receipt is not None else self.reader.get_identity(ref).ref),
                "session_id": session_id, "receipt": _json_value(finished.receipt),
                "sheet_receipt": _json_value(sheet_receipt), "error": finished.error,
                "snapshot_ref": _json_value(snapshot_ref), "snapshot_sha256": sha256(data).hexdigest(),
                "recovery_pending": finished.recovery_pending, "execution": False, "dispatch": False}

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
        previous_scope = self.reader.get_identity(ResourceRef(self.authority, "authoring-scope", target.id))
        if self.reader.get_receipt(request_id) is not None and previous_scope is not None:
            previous_state = previous_scope.payload.get("project")
            if isinstance(previous_state, Mapping) and previous_state.get("open_request_key", request_id) != request_id:
                from herzchen.contracts import ReplayConflictError
                raise ReplayConflictError("create key belongs to a retired authoring session")

        def create_project(*_args: Any, **_kwargs: Any) -> ResourceRef:
            created = self.sheet.create_pending(
                title=title,
                outcome=outcome,
                creator=self.operator_actor or actor,
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
            from herzchen.authoring.sessions import SessionHandle
            state = self._project_draft(project, request_id)
            initial_bytes = self._draft_bytes(state["project_json"])
            handle = SessionHandle(ResourceRef(self.authority, "authoring-scope", target.id),
                checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id,
                checkout.token, checkout.fence, checkout.base_revision)
            self.authoring.autosave(handle, request_id=request_id + ":initial-sheet", snapshot=initial_bytes)
            if self.materializer is None:
                return {"project": state}
            observed = _call_owner_materializer(
                self.materializer,
                checkout=checkout,
                initial_bytes=initial_bytes,
                project=project,
            )
            if isinstance(observed, Mapping):
                result = dict(observed)
                result["project"] = state
                return result
            return {"path": observed, "project": state}

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
            "project_json": None if scope_record is None or not isinstance(scope_record.payload.get("project"), Mapping)
                else scope_record.payload["project"].get("project_json"),
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
        "operator_actor",
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
        "queue_binding",
        "reviewed_policy",
        "evidence_payload_resolver",
        "on_project_finished",
        "_direction_bindings_lock",
        "_direction_bindings_instance",
        "_late_usage_lock",
        "_late_usage_cache",
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
        operator_actor: Optional[str] = None,
        materializer: Any = None,
        portfolio_ref: Any = None,
        main_assignment_ref: Any = None,
        allowed_creator_ids: tuple[str, ...] = (),
        privileged_actor_ids: tuple[str, ...] = (),
        expected_main_principal: Optional[str] = None,
        project_read_grant: Optional[ProjectReadGrant] = None,
        folder_transport_request_bytes: int = 16 * 1024,
        queue_ref: Any = None,
        reviewed_policy: Mapping[str, Any] | None = None,
        evidence_payload_resolver: Any = None,
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
        operator = binding.authenticated_actor(operator_actor or owner_actor)
        if authenticated.authority != store.authority:
            raise ValueError("binding authority does not belong to the supplied store")
        if project_read_grant is not None and (
            not isinstance(project_read_grant, ProjectReadGrant)
            or project_read_grant.principal != authenticated
        ):
            raise ValueError("project read grant must bind the authenticated owner principal")

        self.store = store
        # These owner capabilities own command transports.  Keep one for the
        # lifetime of this bootstrap instead of binding a fresh listening
        # socket each time a manager asks for its direction surface.
        import threading
        self._direction_bindings_lock = threading.RLock()
        self._direction_bindings_instance = None
        # Native body providers can carry authority.  This owner session is
        # bound to one provider, retained alongside its assignment port.
        self._late_usage_lock = threading.RLock()
        self._late_usage_cache = None
        # Called after a project's lifecycle becomes completed or withdrawn (see project_finished).
        self.on_project_finished = None
        self.reviewed_policy = reviewed_policy
        # The owner's evidence handler: verifies managed DAT payloads before accept or completion.
        self.evidence_payload_resolver = evidence_payload_resolver
        self.binding = binding
        self.owner_actor = authenticated
        self.operator_actor = operator
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
                operator_actor=operator,
                portfolio_ref=portfolio_ref,
                main_assignment_ref=main_assignment_ref,
                allowed_creator_ids=allowed_creator_ids,
                privileged_actor_ids=privileged_actor_ids,
                expected_main_principal=expected_main_principal,
            )
            orchestration_port = orchestration.command_port
        self.orchestration_port = orchestration_port
        self.orchestration_portfolio = portfolio_ref
        self.queue_binding = None
        if portfolio_ref is not None:
            from .project_queue import queue_locator
            from herzchen.contracts import ResourceRef
            portfolio = ResourceRef.from_dict(_json_value(portfolio_ref))
            root = ResourceRef.from_dict(_json_value(main_assignment_ref))
            locator = queue_locator(portfolio) if queue_ref is None else ResourceRef.from_dict(_json_value(queue_ref))
            if locator.authority != binding.authority or locator.kind != "dat.content.document" or locator.revision is not None:
                raise ValueError("queue locator must be a current owned DAT document")
            self.queue_binding = {"owner": authenticated, "portfolio": portfolio, "root": root, "locator": locator}
        bridge_type = _create_bridge_type()
        self.create_and_open_bridge = bridge_type(
            store,
            sheet=self.sheet,
            authoring=self.authoring,
            materializer=materializer,
            operator_actor=operator,
            folder_transport_request_bytes=folder_transport_request_bytes,
        )

    def project_finished(self, project_ref: Any) -> Any:
        """Tell the installed hook (clean-close) that a project may have just finished.

        Never raises: a failing hook is logged and must not block or undo the
        lifecycle transition that already committed. The hook decides whether
        the project really is completed or withdrawn, and is idempotent.
        """
        hook = self.on_project_finished
        if hook is None:
            return None
        try:
            return hook(project_ref)
        except Exception:
            import logging
            logging.getLogger("otto.clean_close").warning("project-finished hook failed for %r", project_ref,
                                                          exc_info=True)
            return None

    def consumer_operations(self) -> FiniteWorkOperations:
        """Return only finite serialized/read clients and typed binding data."""

        from herzchen.command_ports import connect_consumer_facade

        transport = self.create_and_open_bridge.consumer_transport()
        create_open_port = connect_consumer_facade(transport.to_dict())
        return FiniteWorkOperations(
            port=self.graph.command_port,
            reader=self.graph.reader,
            binding=self.binding,
            dependency_owner_actor=self.owner_actor,
            operator_actor=self.operator_actor,
            task_revision_reader=self.graph.get,
            sheet_port=self.sheet.command_port,
            content_port=self.content.command_port,
            assignments_port=self.assignments.command_port,
            lifecycle_port=self.lifecycle.command_port,
            authoring_port=self.authoring.command_port,
            create_open_port=create_open_port,
            orchestration_port=self.orchestration_port,
            orchestration_portfolio=self.orchestration_portfolio,
            project_read_grant=self.project_read_grant,
            direction_context_reader=self._direction_context_reader(),
            queue_binding=self.queue_binding,
            on_lifecycle=self.project_finished,
        )

    def _direction_context_reader(self) -> Any:
        # Read capability only: neither registering domains nor exposing bind
        # or adopt to workers. The explicit owner setup remains the issuer.
        def read(*, assignment_ref: Any, generation: Any, project_ref: Any, task_ref: Any = None) -> Any:
            from .direction import DOMAIN_ID, ADOPTION_DOMAIN_ID
            from .direction_context import read_direction_context
            registered = {item.domain_id for item in self.store.registered_domains()}
            if DOMAIN_ID not in registered:
                return []
            from herzchen.contracts import ResourceRef
            project = ResourceRef.from_dict(project_ref)
            if self.project_read_grant is None or not self.project_read_grant.allows(project):
                raise PermissionError("direction context is outside the current project read grant")
            if ADOPTION_DOMAIN_ID not in registered:
                raise ValueError("direction adoption reader unavailable; complete owner direction setup")
            directions = self._get_direction_bindings()
            return read_direction_context(directions, actor=self.owner_actor,
                assignment_ref=assignment_ref, generation=generation, project_ref=project_ref, task_ref=task_ref)
        return read

    def late_usage_operation(self, *, project_ref: Any, authorizing_assignment_ref: Any,
                             authorizing_generation: int, native_bodies: Any) -> Any:
        """Explicit trusted-owner issuance; never included in worker result access.

        The grant is reread at each append. Issuance grants only this project's
        late observation operation, under the current manager generation.
        """
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.assignments import ResponsibilityAssignments
        project = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        if not isinstance(project, ResourceRef) or project.kind != "work.project":
            raise ValueError("one admitted project required")
        actor = self.owner_actor
        with self._late_usage_lock:
            cached = self._late_usage_cache
            if cached is None:
                assignments = ResponsibilityAssignments(
                    self.store, actor=actor, native_bodies=native_bodies
                ).command_port
                self._late_usage_cache = (native_bodies, assignments)
            elif cached[0] is not native_bodies:
                raise ValueError("owner session is already bound to a different native bodies provider")
            else:
                assignments = cached[1]
        owner = self

        class BoundLateUsage:
            def append(self, target: Any, source_ref: Any, source: Any, *, adapter_id: str,
                       phase: str, session_id: str, turn_id: str, logical_request_key: str,
                       supersedes_ref: Any = None) -> Any:
                grant = owner.project_read_grant
                if grant is None or grant.principal != actor or not grant.allows(project):
                    raise PermissionError("late usage requires the current project grant")
                current = assignments.get(authorizing_assignment_ref)
                scope = _json_value(current.scope)
                if any(scope.get(k) != project.to_dict()[k] for k in ("authority", "kind", "id")):
                    raise PermissionError("late usage authorizer is outside the issued project")
                return assignments.append_late_usage(target, source_ref, source, adapter_id=adapter_id,
                    phase=phase, session_id=session_id, turn_id=turn_id,
                    authorizing_assignment_ref=authorizing_assignment_ref,
                    authorizing_generation=authorizing_generation, logical_request_key=logical_request_key,
                    actor=actor, supersedes_ref=supersedes_ref)

        return BoundLateUsage()

    def direction_bindings(self) -> Any:
        """Issue the narrow owner direction capability, without role adoption.

        This explicit composition registers binding and exact scope adoption. Ordinary
        manager/worker facades receive no broader direction authority.
        """
        from .direction import DirectionBindings, register_direction_bindings
        register_direction_bindings(self.store)
        return self._get_direction_bindings()

    def _get_direction_bindings(self) -> Any:
        """Return this session's direction capability, creating it once."""
        from .direction import DirectionBindings
        with self._direction_bindings_lock:
            if self._direction_bindings_instance is None:
                self._direction_bindings_instance = DirectionBindings(
                    self.store, owner_actor=self.owner_actor,
                    assignment_port=self.assignments.command_port,
                )
            return self._direction_bindings_instance

    def direction_surface(self, *, context_reader: Any = None,
                          caller_context_reader: Any = None,
                          inventory_reader: Any = None,
                          occurrence_reader: Any = None,
                          allowed_project: Any = None) -> Any:
        """Issue the bounded D05 direction read/authoring projection.

        The projection reuses the owner-issued D01-D04 capability.  Inventory
        and trusted caller bindings remain host-supplied; this method does not
        create a roster, context store, or native/session history.
        """
        from .direction_surface import DirectionSurface
        return DirectionSurface(self.direction_bindings(), actor=self.owner_actor,
                                context_reader=context_reader,
                                caller_context_reader=caller_context_reader,
                                inventory_reader=inventory_reader,
                                occurrence_reader=occurrence_reader,
                                allowed_project=allowed_project)

    def portfolio(self, *, due_port: Any, issue_delivery: Any = None) -> Any:
        """Issue the ordinary portfolio API with owner-backed check-in/issue ports."""
        from .intake import OttoPortfolio
        from .owner_issue_loop import compose_owner_issue_loop

        operations = self.consumer_operations()
        return OttoPortfolio(operations, issue_loop=compose_owner_issue_loop(
            operations, due_port, delivery=issue_delivery,
        ), due_port=due_port)

    def synchronize_portfolio_direction(
        self, *, assignment_ref: Any, generation: int, direction_ref: Any,
        expected_binding_ref: Any, resources: Any, expected_default_ref: Any,
        projects: Any, logical_request_key: str, expected_guard_ref: Any = None,
    ) -> Mapping[str, Any]:
        """Adopt one root direction/BASE and all current joins atomically.

        Only the trusted owner exposes this finite boundary. DAT scope adoption
        and WRK's existing resource/default/supervision receipts share the owner
        transaction. A lost response recovers those exact immutable receipts;
        a failed fence rolls back the whole application.
        """
        from herzchen.contracts import ResourceRef
        from herzchen.content.instructions import validate_instruction_content
        from .owner_readers import json_value
        if self.orchestration_port is None:
            raise PermissionError("bound portfolio orchestration port required")
        ref = ResourceRef.from_dict(assignment_ref) if isinstance(assignment_ref, Mapping) else assignment_ref
        pin = ResourceRef.from_dict(direction_ref) if isinstance(direction_ref, Mapping) else direction_ref
        root = self.assignments.get(ref)
        if (root.principal != self.owner_actor.actor or root.role != "orchestrator"
                or root.scope.kind != "wrk.portfolio" or root.scope != (ResourceRef.from_dict(self.orchestration_portfolio) if isinstance(self.orchestration_portfolio, Mapping) else self.orchestration_portfolio)
                or root.ref.id != ref.id or root.generation != generation):
            raise PermissionError("exact owned portfolio root required")
        subject = ResourceRef.from_dict(root.payload["responsibility_ref"])
        directions = self.direction_bindings()
        receipt = self.store.consumer().get_receipt(logical_request_key + ":resources")
        if receipt is None:
            if root.ref != ref:
                raise PermissionError("root revision changed")
            old = list(root.payload.get("resource_adoptions", ()))
            if not isinstance(resources, (list, tuple)) or len(resources) != len(old):
                raise ValueError("complete existing root resource set required")
            names = {item["resource_name"]: item for item in old}
            if set(names) != {item.get("resource_name") for item in resources}:
                raise ValueError("resource names cannot change")
            changed = []
            for item in resources:
                prior = names[item["resource_name"]]
                if item == prior:
                    continue
                before = self.content.read(ResourceRef.from_dict(prior["resource_ref"]))["content"]
                after = self.content.read(ResourceRef.from_dict(item["resource_ref"]))["content"]
                old_ref = ResourceRef.from_dict(prior["resource_ref"])
                new_ref = ResourceRef.from_dict(item["resource_ref"])
                if (old_ref.id != new_ref.id or old_ref.authority != new_ref.authority
                        or old_ref.kind != new_ref.kind or not prior["required"] or not item["required"]
                        or before.get("schema") != "herzchen.instructions.v1"
                        or item["content_digest"] != validate_instruction_content(after)):
                    raise ValueError("only the existing required BASE revision may change")
                expected = dict(before)
                support = []
                count = 0
                for value in before.get("supporting_refs", ()):
                    candidate = ResourceRef.from_dict(value)
                    if (candidate.authority, candidate.kind, candidate.id) == (pin.authority, pin.kind, pin.id):
                        support.append(pin.to_dict());count += 1
                    else:support.append(value)
                expected["supporting_refs"] = support
                if count != 1 or after != expected:
                    raise ValueError("BASE must preserve shared guidance and all unrelated supporting pins")
                changed.append(item)
            if len(changed) != 1:
                raise ValueError("exactly one existing BASE direction pin must change")
        with self.store.transaction():
            scope = directions.update(subject, pin, actor=self.owner_actor,
                expected_binding_ref=expected_binding_ref, logical_request_key=logical_request_key + ":scope")
            work = self.orchestration_port.adopt_resources_with_supervision(
                actor=self.owner_actor, request_id=logical_request_key + ":resources",
                assignment_ref=ref, expected_generation=generation, resources=resources,
                expected_default_ref=expected_default_ref, projects=projects,
                expected_guard_ref=expected_guard_ref)
            actual = self.assignments.get(work["assignment_ref"])
            if actual.ref.to_dict() != work["assignment_ref"]:
                raise PermissionError("retained synchronization is superseded; inspect current root")
            effective = directions.resolve(subject, actor=self.owner_actor,
                assignment_ref=actual.ref, expected_generation=generation)
            if effective["effective_ref"] != pin.to_dict() or effective["assignment_adopted_ref"] != pin.to_dict():
                raise PermissionError("full assignment-effective direction verification failed")
        return {"outcome": "synchronized", "replayed": work["replayed"],
                "scope_adopted": True, "assignment_resources_refreshed": True,
                "provider_called": False, "native_delivery_claimed": False,
                "assignment_ref": work["assignment_ref"], "generation": generation,
                "direction_ref": pin.to_dict(), "effective_context": json_value(effective),
                "stages": {"scope": json_value(scope), "resources_and_joins": json_value(work)}}

    def manager_application(self, *, due_port: Any = None, issue_delivery: Any = None) -> Any:
        """Compose the ordinary finite manager entry over this trusted owner."""
        from .manager_application import ManagerApplication

        return ManagerApplication.from_owner(self, due_port=due_port, issue_delivery=issue_delivery)

    def manager_assessment(self, *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                           manager_assignment_ref: Mapping[str, Any], manager_actor: str,
                           manager_generation: int, assessment_policy: Any) -> Any:
        """Issue finite assessment commands for the current assigned manager/task."""
        from herzchen.contracts import ResourceRef
        from herzchen.domains.assessment import AssessmentModule
        from herzchen.content.reads import EvidenceReadGrant
        from .assessment import OttoAssessment
        from .manager_assessment_command import ManagerAssessmentCommands
        from .local_assessment_policy import LocalAssessmentPolicy
        from herzchen.kernel import LimitService
        if not isinstance(assessment_policy, LocalAssessmentPolicy):
            raise TypeError("trusted local assessment policy is required")
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
            _read_current_result_task(self.graph.reader, project.to_dict(), task.to_dict(), allow_task_content_revision=True)
            assessment_policy.validate_binding(project, task, self.graph.reader)
            current = self.assignments.command_port.get(assignment)
            if (current.ref != assignment or current.generation != manager_generation
                    or current.role != "manager" or current.principal != actor.actor
                    or (current.scope.authority, current.scope.kind, current.scope.id)
                    != (project.authority, project.kind, project.id)
                    or current.status.value == "cancelled"):
                raise PermissionError("manager assessment assignment is stale or out of scope")

        def pool_guard() -> None:
            pool = LimitService(self.store).get_pool(assessment_policy.pool_ref)
            if (pool is None or pool.capacity_units != assessment_policy.capacity_units
                    or pool.cumulative_allowance_units != assessment_policy.cumulative_allowance_units):
                raise PermissionError("local assessment pool is missing or differs from the bound policy")

        def issue_evidence_read_grant(evidence: ResourceRef, parent: ResourceRef) -> EvidenceReadGrant:
            # Recheck the owner's current project grant and manager assignment
            # for each exact evidence read. This grants no assessment write.
            authorize()
            if parent != task or evidence.authority != task.authority or evidence.revision is None:
                raise PermissionError("assessment evidence is outside the owner-issued grant")
            return EvidenceReadGrant(self.owner_actor, actor, project, task, evidence)

        authorize()
        return ManagerAssessmentCommands(
            assessment=OttoAssessment(AssessmentModule(self.store, actor=actor,
                payload_resolver=self.evidence_payload_resolver,
                evidence_read_grant_issuer=issue_evidence_read_grant), actor),
            reader=self.graph.reader, actor=actor, task=task, assignment=assignment,
            generation=manager_generation, authorize=authorize, policy=assessment_policy, pool_guard=pool_guard)

    def create_manager_assessment_pool(self, *, project_ref: Mapping[str, Any],
                                       task_ref: Mapping[str, Any],
                                       manager_assignment_ref: Mapping[str, Any],
                                       manager_actor: str, manager_generation: int,
                                       logical_request_key: str, assessment_policy: Any) -> Mapping[str, Any]:
        """Create only the pool authorized by trusted local controller policy."""
        from herzchen.kernel import LimitService, VersionConflictError
        if not isinstance(logical_request_key, str) or not logical_request_key.strip():
            raise ValueError("logical request key is required")
        self.manager_assessment(project_ref=project_ref, task_ref=task_ref,
            manager_assignment_ref=manager_assignment_ref, manager_actor=manager_actor,
            manager_generation=manager_generation, assessment_policy=assessment_policy)
        actor = self.binding.authenticated_actor(manager_actor)
        limits = LimitService(self.store)
        try:
            pool = limits.create_pool(
                assessment_policy.pool_ref, capacity_units=assessment_policy.capacity_units,
                cumulative_allowance_units=assessment_policy.cumulative_allowance_units,
                logical_request_key=logical_request_key, actor=actor)
            replayed = pool.receipt is not None and pool.receipt.replayed
        except VersionConflictError:
            # A controller-created pool can have a different setup key. Only
            # recover the specific version-conflict shape by reading the exact
            # policy-bound identity; all other failures remain unchanged.
            pool = limits.get_pool(assessment_policy.pool_ref)
            if pool is None:
                raise
            if (pool.capacity_units != assessment_policy.capacity_units
                    or pool.cumulative_allowance_units != assessment_policy.cumulative_allowance_units):
                raise PermissionError("local assessment pool exists but differs from the bound policy")
            # The current identity is the exact trusted pool, so reuse is safe
            # even though the setup logical key differs from this operation.
            replayed = True
        return {"outcome": "replayed" if replayed else "committed",
                "schema": "otto.manager-assessment-pool.v1", "pool": pool.ref.to_dict(),
                "capacity_units": pool.capacity_units, "cumulative_allowance_units": pool.cumulative_allowance_units,
                "held_units": pool.held_units, "cumulative_used_units": pool.cumulative_used_units,
                "remaining_allowance_units": pool.remaining_allowance_units,
                "purpose": assessment_policy.purpose, "local_only": True, "provider_called": False}

    def execution_application(self, *, due_port: Any, adapter: Any, clock: Any = None,
                              manager_actor: str | None = None, assessment_policy: Any = None,
                              issue_delivery: Any = None, native_result_verifier: Any = None, native_bodies: Any = None,
                              reviewed_policy: Mapping[str, Any] | None = None) -> Any:
        """Issue maintained execution commands over the existing finite ports."""
        from .execution import ExecutionApplication
        runtime = self.role_runtime(due_port=due_port, adapter=adapter,
                                    assessment_policy=assessment_policy, issue_delivery=issue_delivery, native_result_verifier=native_result_verifier, native_bodies=native_bodies)
        kwargs = {} if clock is None else {"clock": clock}
        activation = self.reviewed_plan_activation(owner_policy=reviewed_policy)
        app = ExecutionApplication(portfolio=runtime.portfolio,
            assignments=self.assignments.command_port, due_port=due_port,
            binding=self.binding, actor=self.owner_actor.actor, runtime=runtime,
            manager_actor=manager_actor, reviewed_activation=activation, **kwargs)
        activation.setup_application = app
        return app

    def reviewed_plan_activation(self, *, setup_application: Any = None,
                                 owner_policy: Mapping[str, Any] | None = None) -> Any:
        """Return the owner-bound reviewed-plan activation composition."""
        from .reviewed_activation import ReviewedPlanActivation
        selected = self.reviewed_policy if owner_policy is None else owner_policy
        return ReviewedPlanActivation(self, setup_application=setup_application,
                                      owner_policy=selected)

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
                     issue_delivery: Any = None, assessment_policy: Any = None, native_result_verifier: Any = None, native_bodies: Any = None) -> Any:
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
                           assignment_ref: Mapping[str, Any], generation: int, logical_request_key: str,
                           allow_project_manager: bool = False) -> Any:
            from herzchen.contracts import ResourceRef

            project, task = ResourceRef.from_dict(project_ref), ResourceRef.from_dict(task_ref)
            if grant is None or grant.principal != owner_actor or not grant.allows(project):
                raise PermissionError("result capability requires the admitted project/task scope")
            _read_current_result_task(scope_reader, project_ref, task_ref)
            access = _BoundResultAccess(assignments=assignments, reader=result_reader, scope_reader=scope_reader,
                actor=owner_actor, project_ref=project_ref, task_ref=task_ref, assignment_ref=assignment_ref,
                generation=generation, logical_request_key=logical_request_key,
                allow_project_manager=allow_project_manager)
            capture = HerzchenAttemptCapture(access, access, actor=owner_actor, native_bodies=native_bodies)
            error = capture.validate_generation(assignment_ref, generation)
            if error:
                raise PermissionError(error)
            return capture

        def acceptance_readiness(project_ref: Mapping[str, Any], manager: Mapping[str, Any],
                                 tasks: Any) -> Mapping[str, Any]:
            if assessment_policy is None:
                raise PermissionError("operating setup requires the owner-bound assessment policy and existing allowance")
            from herzchen.contracts import ResourceRef
            if not isinstance(tasks, (list, tuple)) or not tasks or len(tasks) > 64:
                raise PermissionError("setup acceptance tasks must be a bounded nonempty reference list")
            policy_tasks = {task.id for task, _ in assessment_policy.task_criterion_pairs}
            configured_refs = [ResourceRef.from_dict(value) for value in tasks]
            configured_ids = [ref.id for ref in configured_refs]
            project = ResourceRef.from_dict(project_ref)
            if (any(ref.kind != "work.task" or ref.authority != project.authority or not ref.revision
                    for ref in configured_refs)
                    or len(configured_ids) != len(set(configured_ids))
                    or not policy_tasks.issubset(set(configured_ids))):
                raise PermissionError("setup must retain every task in the owner assessment policy exactly once")
            scopes, completed_readbacks = [], []
            assignment = ResourceRef.from_dict(manager["assignment_ref"])
            if type(manager.get("generation")) is not int or manager["generation"] < 1:
                raise PermissionError("setup manager generation is invalid")
            actor = self.binding.authenticated_actor(manager["principal"])
            current_manager = self.assignments.command_port.get(assignment)
            if (current_manager.ref != assignment or current_manager.generation != manager["generation"]
                    or current_manager.role != "manager" or current_manager.principal != actor.actor
                    or (current_manager.scope.authority, current_manager.scope.kind, current_manager.scope.id)
                    != (project.authority, project.kind, project.id)):
                raise PermissionError("setup manager assignment is stale or outside the project")

            def verify_completed_history(configured_task: Mapping[str, Any], current: Any) -> None:
                """Verify canonical accepted completion without consulting the new-review policy."""
                completion = current.payload.get("completion")
                try:
                    completion_project = ResourceRef.from_dict(completion.get("project_ref"))
                except (TypeError, ValueError, KeyError, AttributeError):
                    completion_project = None
                if (current.payload.get("lifecycle") != "completed" or not isinstance(completion, Mapping)
                        or completion_project is None
                        or (completion_project.authority, completion_project.kind, completion_project.id)
                        != (project.authority, project.kind, project.id)
                        or completion_project.revision != completion.get("project_revision")
                        or not isinstance(completion.get("project_revision"), str)
                        or not completion.get("project_revision")
                        or completion.get("manager") != manager["principal"]
                        or completion.get("disposition") not in {
                            "accept", "accepted", "accepted-for-task", "approved", "complete", "completed", "verified"}):
                    raise PermissionError("historical setup task lacks canonical accepted completion proof")
                predecessor = ResourceRef.from_dict(completion.get("task_ref"))
                configured_ref = ResourceRef.from_dict(configured_task)
                if predecessor != configured_ref and configured_ref != current.ref:
                    raise PermissionError("historical setup task lacks exact committed completion predecessor")
                key = completion.get("logical_request_key")
                receipt = self.graph.reader.get_receipt(key) if isinstance(key, str) and key else None
                if (receipt is None or receipt.status.value != "committed"
                        or receipt.operation != "work.revise" or receipt.target != predecessor
                        or receipt.result_ref != current.ref):
                    raise PermissionError("historical setup task lacks exact committed completion predecessor")
                assignment_ref = ResourceRef.from_dict(completion.get("assignment_ref"))
                if (assignment_ref.kind != "wrk.assignment" or assignment_ref.authority != project.authority
                        or type(completion.get("generation")) is not int or completion["generation"] < 1):
                    raise PermissionError("historical setup completion has invalid manager assignment pins")
                completed_assignment = self.assignments.command_port.get(assignment_ref)
                if (completed_assignment.role != "manager" or completed_assignment.principal != manager["principal"]
                        or (completed_assignment.scope.authority, completed_assignment.scope.kind, completed_assignment.scope.id)
                        != (project.authority, project.kind, project.id)):
                    raise PermissionError("historical setup completion belongs to another manager or project")
                candidate = ResourceRef.from_dict(completion.get("candidate_ref"))
                gates = [ResourceRef.from_dict(value) for value in completion.get("gate_refs", ())]
                evidence = [ResourceRef.from_dict(value) for value in completion.get("evidence_refs", ())]
                hashes = completion.get("evidence_hashes")
                if (candidate.authority != project.authority or not candidate.revision
                        or not gates or len(gates) > 64 or not evidence or len(evidence) > 64
                        or not isinstance(hashes, Mapping) or not hashes):
                    raise PermissionError("historical setup completion evidence pins are incomplete")
                candidate_identity = self.graph.reader.get_identity(candidate)
                if candidate_identity is None or candidate_identity.ref != candidate:
                    raise PermissionError("historical setup completion evidence is stale")
                # The ordinary completion producer stores exact hashes for all
                # review evidence. The generic assessment verifier only
                # verifies DAT documents, so its aggregate may honestly be
                # unknown when a WRK result/report is also evidence. Verify the
                # immutable producer hashes directly instead of treating that
                # DAT-only coverage flag as canonical task acceptance.
                from .manager_journey_command import _digest
                if (not isinstance(hashes, Mapping) or not hashes
                        or len(evidence) > 64 or not evidence
                        or any(not ref.revision for ref in evidence)
                        or len({(ref.authority, ref.kind, ref.id, ref.revision) for ref in evidence}) != len(evidence)):
                    raise PermissionError("historical setup completion evidence hashes are invalid")
                expected_hash_keys = {f"{ref.kind}:{ref.id}:{ref.revision}" for ref in evidence}
                if set(hashes) != expected_hash_keys:
                    raise PermissionError("historical setup completion evidence hashes do not cover exact evidence pins")
                for evidence_ref in evidence:
                    claimed_digest = hashes.get(f"{evidence_ref.kind}:{evidence_ref.id}:{evidence_ref.revision}")
                    if (not isinstance(claimed_digest, str) or len(claimed_digest) != 64
                            or any(character not in "0123456789abcdef" for character in claimed_digest)):
                        raise PermissionError("historical setup completion evidence digest is malformed")
                    if evidence_ref.kind == "dat.content.document":
                        retained = self.content.read(evidence_ref)
                        from herzchen.content.model import revision_identity
                        storage_ref = revision_identity(
                            ResourceRef(evidence_ref.authority, evidence_ref.kind, evidence_ref.id),
                            evidence_ref.revision)
                        actual_digest = (_digest(retained["content"])
                            if retained.get("identity") == evidence_ref
                            and retained.get("storage_identity") == storage_ref
                            and "content" in retained else None)
                    elif evidence_ref.kind in {"wrk.result", "wrk.report"}:
                        retained = self.graph.reader.get_identity(evidence_ref)
                        value = None if retained is None or retained.ref != evidence_ref else retained.payload.get("value")
                        actual_digest = _digest(value) if isinstance(value, Mapping) else None
                    else:
                        retained = self.graph.reader.get_identity(evidence_ref)
                        stored_digest = (retained.payload.get("content_digest")
                            if retained is not None and retained.ref == evidence_ref else None)
                        actual_digest = (stored_digest if isinstance(stored_digest, str)
                            and len(stored_digest) == 64
                            and all(character in "0123456789abcdef" for character in stored_digest) else None)
                    if actual_digest != claimed_digest:
                        raise PermissionError("historical setup completion evidence hash does not match retained content")
                gate = completion.get("assessment_gate_check")
                if (not isinstance(gate, Mapping) or gate.get("required") is not True
                        or gate.get("blockers") != []
                        or gate.get("candidate_ref") != candidate.to_dict()
                        or gate.get("accepted_decision_refs") != [ref.to_dict() for ref in gates]):
                    raise PermissionError("historical setup completion does not retain its accepted gate proof")
                state = self.assignments.completion_blockers(current.ref, candidate=candidate, gate_refs=gates,
                    actor=actor, completion_evidence_refs=evidence, completion_evidence_hashes=hashes)
                if (state.get("required") is not True or state.get("blockers")
                        or state.get("evidence_verification") not in {"verified", "unknown"}
                        or state.get("candidate_ref") != candidate.to_dict()
                        or not state.get("accepted_decision_refs")
                        or state.get("accepted_decision_refs") != [ref.to_dict() for ref in gates]):
                    raise PermissionError("historical setup completion failed canonical gate/evidence verification")

            for configured_task in tasks:
                ref = ResourceRef.from_dict(configured_task)
                current = self.graph.reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
                if current is None:
                    raise PermissionError("setup acceptance task is missing")
                if current.ref.to_dict() != configured_task:
                    # Immutable setup selects the completion input revision.
                    # Only that exact committed transition can supply a current
                    # read; assessment/result mutation capabilities stay strict.
                    verify_completed_history(configured_task, current)
                    completed_readbacks.append({"configured_task_ref": configured_task,
                        "current_task_ref": current.ref.to_dict(),
                        "completion_request_key": current.payload["completion"]["logical_request_key"]})
                if ref.id not in policy_tasks:
                    if current.ref.to_dict() == configured_task:
                        verify_completed_history(configured_task, current)
                    continue
                task = current.ref.to_dict()
                commands = self.manager_assessment(project_ref=project_ref, task_ref=task,
                    manager_assignment_ref=manager["assignment_ref"], manager_actor=manager["principal"],
                    manager_generation=manager["generation"], assessment_policy=assessment_policy)
                scopes.append(commands.execute({"operation": "resolve-required-scope", "arguments": {},
                    "expected_task_ref": task, "expected_assignment_ref": manager["assignment_ref"],
                    "expected_generation": manager["generation"]}))
            return {"required_scopes": scopes, "completed_task_readbacks": completed_readbacks, "allowance_created": False}

        from herzchen.kernel import LimitService
        limits = LimitService(self.store)

        def allowance_readiness(value: Mapping[str, Any]) -> None:
            from herzchen.contracts import ResourceRef
            ref = ResourceRef.from_dict(value)
            if ref.authority != owner_actor.authority or ref.kind != "limit" or ref.revision is not None:
                raise PermissionError("advisor allowance must select an existing owner pool")
            pool = limits.get_pool(ref)
            if pool is None or pool.remaining_allowance_units < 1:
                raise PermissionError("advisor allowance is missing or exhausted")

        def completed_task_readiness(due: Any) -> Any:
            from .owner_readers import completed_occurrence_task_reader
            from herzchen.contracts import ResourceRef
            if due.stop_state != "completed" or due.completion_state != "succeeded":
                return None
            assignment = assignments.get(ResourceRef.from_dict(due.assignment_ref))
            return completed_occurrence_task_reader(result_reader, due, assignment)

        return CanonicalRoleRuntime(
            operations=operations, portfolio=portfolio, due_port=due_port,
            adapter=adapter, actor=self.owner_actor.actor, runtime_probe=runtime_probe,
            result_capture_factory=result_capture,
            acceptance_readiness=acceptance_readiness,
            allowance_readiness=allowance_readiness,
            completed_task_readiness=completed_task_readiness, native_result_verifier=native_result_verifier, native_bodies=native_bodies,
        )


__all__ = ["CreateAndOpenCommandPort", "PortfolioOwnerBootstrap"]
