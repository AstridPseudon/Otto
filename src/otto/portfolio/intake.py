"""Public OTT-03 intake facade.

This module validates the small product contract and delegates all durable
work to a supplied canonical Herzchen operation port.  The port is expected to
be the accepted work-record adapter (or a neutral fixture implementing the
same public call shape):

``execute(operation, payload, request_id=..., actor=...) -> Mapping``
``read(operation, payload, actor=...) -> Mapping``

No Otto-owned store is provided as a fallback.  An absent port is reported as
an explicit unsupported boundary so callers cannot mistake a local no-op for
durable work.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Optional, Protocol, Sequence

from .herzchen_binding import FiniteWorkOperations


ADMISSION_CHOICES = ("admit", "investigate", "merge", "park", "drop")
EDITABLE_FIELDS = frozenset(
    {
        "title",
        "outcome",
        "curator",
        "why_pending",
        "documents",
        "links",
        "revisit",
        "metadata",
        "custom",
    }
)
_PROTECTED_FIELDS = frozenset(
    {
        "id",
        "kind",
        "authority",
        "revision",
        "lifecycle",
        "state",
        "readiness",
        "manager",
        "manager_assignment",
        "executor",
        "parent",
        "tasklist",
        "tasks",
        "allowance",
        "budget",
        "session",
        "accepted_result",
        "dispatch",
        "admitted",
    }
)


class PortfolioError(ValueError):
    """A rejected public request that must have no canonical side effect."""


class WorkOperations(Protocol):
    """The public Herzchen work-operation port consumed by Otto."""

    def execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        ...

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        ...


def _json_copy(value: Any, *, field: str = "value") -> Any:
    """Return JSON data without allowing opaque Python objects into records."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise PortfolioError(f"{field} must be JSON-compatible") from exc


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or "\x00" in value:
        requirement = "a non-blank" if required else "text"
        raise PortfolioError(f"{field} must be {requirement} value")
    return value.strip() if required else value


def _ref(value: Any, field: str = "project_ref") -> dict[str, Any]:
    if isinstance(value, str):
        return {"id": _text(value, field)}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if not isinstance(value, Mapping):
        raise PortfolioError(f"{field} must be a durable reference object")
    result = _json_copy(dict(value), field=field)
    if not isinstance(result.get("id"), str) or not result["id"].strip():
        raise PortfolioError(f"{field}.id must be non-blank")
    return result


def _edit(value: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PortfolioError("edit must be an object")
    result = _json_copy(dict(value), field="edit")
    if not isinstance(result, dict):
        raise PortfolioError("edit must be an object")
    for key in result:
        if not isinstance(key, str) or not key.strip():
            raise PortfolioError("edit field names must be non-blank text")
        if key in _PROTECTED_FIELDS:
            raise PortfolioError(f"protected field cannot be edited: {key}")
    for key in ("title", "outcome", "curator", "why_pending"):
        if key in result and not isinstance(result[key], str):
            raise PortfolioError(f"{key} must be text")
    return result


def _result(value: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "outcome": "error",
            "error": {"code": "malformed_canonical_result", "message": f"{operation} returned a non-object"},
        }
    return _json_copy(dict(value), field=f"{operation} result")


def unavailable_operations() -> "UnavailableWorkOperations":
    """Create an explicit no-binding port for CLI/readiness diagnostics."""

    return UnavailableWorkOperations()


class UnavailableWorkOperations:
    """No-op boundary used when the accepted Herzchen work binding is absent."""

    def execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        return {
            "outcome": "unavailable",
            "operation": operation,
            "error": {
                "code": "canonical_work_port_unavailable",
                "message": "accepted Herzchen work operations are not bound in this environment",
            },
        }

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        return self.execute(operation, payload, request_id="read-only", actor=actor)


class HerzchenWorkOperations(FiniteWorkOperations):
    """Finite accepted Herzchen command/read adapter consumed by Otto."""

    def __init__(
        self,
        *,
        port: Any,
        reader: Any,
        binding: Any,
        sheet_port: Any = None,
        content_port: Any = None,
        assignments_port: Any = None,
        authoring_port: Any = None,
        create_open_port: Any = None,
    ) -> None:
        from .herzchen_binding import HerzchenBindingConfig

        if not isinstance(binding, HerzchenBindingConfig):
            raise TypeError("binding must be HerzchenBindingConfig")
        super().__init__(
            port=port,
            reader=reader,
            binding=binding,
            sheet_port=sheet_port,
            content_port=content_port,
            assignments_port=assignments_port,
            authoring_port=authoring_port,
            create_open_port=create_open_port,
        )


class OttoPortfolio:
    """Manager-facing OTT-03 API over canonical Herzchen work records."""

    def __init__(self, operations: Optional[WorkOperations] = None) -> None:
        self.operations: WorkOperations = operations or unavailable_operations()

    @staticmethod
    def help() -> dict[str, Any]:
        return {
            "surface": "otto.portfolio",
            "purpose": "capture and explicitly admit pending projects through canonical work operations",
            "bootstrap": {
                "owner": "PortfolioOwnerBootstrap(store, binding=HerzchenBindingConfig(authority, credential_ref), owner_actor=actor)",
                "consumer": "OttoPortfolio(owner.consumer_operations())",
                "required_owner_registration": ["register_work(store)", "content.domain_contribution()", "register_authoring(store)"],
                "consumer_boundary": "finite serialized operations and reader only; no Store, DomainHandler, database path, SQL, callback, or generic writer",
                "restart": "close the owner Store and reopen it through the same owner bootstrap before restart/read evidence",
                "typed_task_batch": "use the finite operations.sheet_port.apply(project_ref, {tasks: [...]}, logical_request_key=..., actor=operations.binding.authenticated_actor(actor), base_revision=project_ref['revision']); read its returned project with batch.project.ref.to_dict()",
                "protected_pending_fields": "edit_pending rejects tasks, documents, assignments, and receipts; use their typed finite ports",
                "admission_frame": "admit requires non-blank outcome, recipient, route, and authority text; records a decision without launching, dispatching, reserving budget, or creating a session",
                "public_journey_example": "profiles/otto/ott06-public-journey.py contains the complete direct-task and existing-project checkout/validate/semantic-check-in/cleanup/fresh-reopen journey, plus replay and admission evidence, with every actor and request_id argument",
            },
            "operations": {
                "create_pending": "create a pending project; a qualified owner binding uses atomic default-orchestrator placement",
                "create_with_default_orchestrator": "explicitly require the owner-backed atomic default-orchestrator placement route",
                "create_and_open": "create_pending with open requested, using the blank starter by default or a selected template resource",
                "create_document": "create a typed canonical content document for a pending project",
                "link_document": "link a typed canonical document association to a project",
                "read_pending": "read one durable project reference",
                "list_pending": "list pending work records",
                "edit_pending": "apply a validated sparse edit, preserving unknown fields",
                "reopen": "reopen(project_ref, actor=..., request_id=...); returns the same durable identity and exact-replays the same request without a new event",
                "revisit": "record attention/readiness only",
                "satisfied_prerequisite": "record attention/readiness only for a dependency change",
                "admit": "manager decision: admit, investigate, merge, park, or drop",
                "assign_roles": "bind one parent, one accountable manager, and bounded executor(s)",
                "handoff": "fence a returned manager assignment reference and preserve identity, evidence, consumption, and parent obligation",
                "complete_task": "manager-only guarded task close; verifies current project/task/assignment pins, disposition, evidence hashes and gates before one owner transaction",
                "manager_inbox": "read one derived project/subproject scope with tasks, assignments, attempts, reports, decisions, attention and repeat-safe event cursor; read-only",
            },
            "invariants": [
                "pending creation does not create a manager, tasklist, allowance, session, or accepted result",
                "revisit and prerequisite signals never activate or dispatch work",
                "same request_id is resolved by the canonical receipt/replay contract",
                "host launch/session/AST behavior is outside this surface and unavailable bindings fail explicitly",
            ],
        }

    def _request(self, request_id: str, actor: str) -> tuple[str, str]:
        return _text(request_id, "request_id"), _text(actor, "actor")

    def _execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        try:
            value = self.operations.execute(operation, _json_copy(dict(payload), field="payload"), request_id=request_id, actor=actor)
        except Exception as exc:  # canonical owner reports its own transaction/rejection details
            return {"outcome": "error", "error": {"code": "canonical_rejected", "message": str(exc), "operation": operation}}
        return _result(value, operation=operation)

    def _read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
        actor = _text(actor, "actor")
        try:
            value = self.operations.read(operation, _json_copy(dict(payload), field="payload"), actor=actor)
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "canonical_read_failed", "message": str(exc), "operation": operation}}
        return _result(value, operation=operation)

    def create_pending(
        self,
        *,
        actor: str,
        request_id: str,
        edit: Optional[Mapping[str, Any]] = None,
        template: Any = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
        open_project: bool = False,
        open: Optional[bool] = None,
        orchestrated: bool = False,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        if open is not None:
            if not isinstance(open, bool):
                raise PortfolioError("open must be boolean")
            open_project = open
        if not isinstance(open_project, bool):
            raise PortfolioError("open_project must be boolean")
        if not isinstance(orchestrated, bool):
            raise PortfolioError("orchestrated must be boolean")
        if orchestrated and open_project:
            raise PortfolioError("default-orchestrated creation does not support open_project")
        edit_value = _edit(edit)
        template_value = "blank" if template is None else _json_copy(template, field="template")
        if isinstance(template_value, str):
            _text(template_value, "template")
        elif not isinstance(template_value, Mapping):
            raise PortfolioError("template must be a name or object")
        if template_parameters is not None and not isinstance(template_parameters, Mapping):
            raise PortfolioError("template_parameters must be an object")
        if template_parameters is not None and not isinstance(template_value, Mapping):
            raise PortfolioError("template_parameters require a selected template object")
        payload = {"edit": edit_value, "template": template_value, "open": bool(open_project)}
        if template_parameters is not None:
            payload["template_parameters"] = _json_copy(
                dict(template_parameters), field="template_parameters"
            )
        return self._execute(
            "work.orchestrator.project.create" if orchestrated else "work.pending.create",
            payload,
            request_id=request_id,
            actor=actor,
        )

    def create_with_default_orchestrator(
        self,
        *,
        actor: str,
        request_id: str,
        edit: Optional[Mapping[str, Any]] = None,
        template: Any = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Use the owner-backed one-main/default placement route.

        This explicit route is retained as a named compatibility seam; a
        qualified owner binding also sends ordinary pending creation through
        the same atomic owner operation.
        """

        return self.create_pending(
            actor=actor,
            request_id=request_id,
            edit=edit,
            template=template,
            template_parameters=template_parameters,
            orchestrated=True,
        )

    def create_and_open(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["open_project"] = True
        return self.create_pending(**kwargs)

    def create_document(
        self,
        project_ref: Any,
        *,
        actor: str,
        request_id: str,
        content: Any,
        role: str = "supporting",
        visibility: str = "private",
        access_mode: str = "read",
        document_id: Optional[str] = None,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.document.create",
            {
                "project_ref": _ref(project_ref),
                "content": _json_copy(content, field="content"),
                "role": _text(role, "role"),
                "visibility": _text(visibility, "visibility"),
                "access_mode": _text(access_mode, "access_mode"),
                "document_id": _text(document_id, "document_id") if document_id is not None else None,
            },
            request_id=request_id,
            actor=actor,
        )

    def link_document(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: str,
        request_id: str,
        namespace: str = "project.documents",
        key: str = "document",
        access_mode: str = "read",
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.document.link",
            {
                "project_ref": _ref(project_ref),
                "document_ref": _ref(document_ref, "document_ref"),
                "namespace": _text(namespace, "namespace"),
                "key": _text(key, "key"),
                "access_mode": _text(access_mode, "access_mode"),
            },
            request_id=request_id,
            actor=actor,
        )

    def read_pending(self, project_ref: Any, *, actor: str) -> dict[str, Any]:
        return self._read("work.pending.read", {"project_ref": _ref(project_ref)}, actor=actor)

    def list_pending(self, *, actor: str, parent_ref: Any = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if parent_ref is not None:
            payload["parent_ref"] = _ref(parent_ref, "parent_ref")
        return self._read("work.pending.list", payload, actor=actor)

    def manager_inbox(
        self,
        project_ref: Any,
        *,
        actor: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        safety_scan: bool = True,
    ) -> dict[str, Any]:
        """Read one derived manager scope without acknowledging or dispatching."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise PortfolioError("limit must be between 1 and 1000")
        if cursor is not None and (not isinstance(cursor, str) or not cursor.strip()):
            raise PortfolioError("cursor must be non-blank text when supplied")
        if not isinstance(safety_scan, bool):
            raise PortfolioError("safety_scan must be boolean")
        payload: dict[str, Any] = {"project_ref": _ref(project_ref), "limit": limit, "safety_scan": safety_scan}
        if cursor is not None:
            payload["cursor"] = cursor
        return self._read("work.manager.inbox", payload, actor=actor)

    read_manager_inbox = manager_inbox
    reconcile_inbox = manager_inbox

    def transition_project_lifecycle(
        self,
        project_ref: Any,
        task_ref: Any,
        manager_ref: Any,
        *,
        actor: str,
        request_id: str,
        expected_generation: int,
        expected_project_revision: str,
        expected_task_revision: str,
        intent: str,
        evidence: Mapping[str, Any],
        obligation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one finite owner lifecycle intent; no Otto state is written."""

        request_id, actor = self._request(request_id, actor)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
            raise PortfolioError("expected_generation must be a positive integer")
        if not isinstance(expected_project_revision, str) or not expected_project_revision.strip():
            raise PortfolioError("expected_project_revision is required")
        if not isinstance(expected_task_revision, str) or not expected_task_revision.strip():
            raise PortfolioError("expected_task_revision is required")
        if intent not in {"active", "closing", "blocked", "terminal"}:
            raise PortfolioError("unsupported project lifecycle intent")
        if not isinstance(evidence, Mapping) or not isinstance(obligation, Mapping):
            raise PortfolioError("lifecycle evidence and obligation must be objects")
        return self._execute(
            "work.project.lifecycle.transition",
            {
                "project_ref": _ref(project_ref), "task_ref": _ref(task_ref, "task_ref"),
                "manager_ref": _ref(manager_ref, "manager_ref"),
                "expected_generation": expected_generation,
                "expected_project_revision": expected_project_revision,
                "expected_task_revision": expected_task_revision,
                "intent": intent,
                "evidence": _json_copy(dict(evidence), field="evidence"),
                "obligation": _json_copy(dict(obligation), field="obligation"),
            },
            request_id=request_id, actor=actor,
        )

    def read_project_lifecycle(self, project_ref: Any, task_ref: Any, manager_ref: Any, *, actor: str) -> dict[str, Any]:
        """Read the owner lifecycle projection without a durable side effect."""

        return self._read(
            "work.project.lifecycle.read",
            {"project_ref": _ref(project_ref), "task_ref": _ref(task_ref, "task_ref"), "manager_ref": _ref(manager_ref, "manager_ref")},
            actor=actor,
        )

    def edit_pending(self, project_ref: Any, edit: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.edit",
            {"project_ref": _ref(project_ref), "edit": _edit(edit)},
            request_id=request_id,
            actor=actor,
        )

    def reopen(self, project_ref: Any, *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute("work.pending.open", {"project_ref": _ref(project_ref)}, request_id=request_id, actor=actor)

    def revisit(self, project_ref: Any, revisit: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        if not isinstance(revisit, Mapping) or not revisit:
            raise PortfolioError("revisit must be a non-empty object")
        return self._execute(
            "work.pending.revisit",
            {"project_ref": _ref(project_ref), "revisit": _json_copy(dict(revisit), field="revisit"), "attention_only": True},
            request_id=request_id,
            actor=actor,
        )

    def satisfied_prerequisite(self, project_ref: Any, prerequisite_ref: Any, *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.prerequisite-satisfied",
            {"project_ref": _ref(project_ref), "prerequisite_ref": _ref(prerequisite_ref, "prerequisite_ref"), "attention_only": True},
            request_id=request_id,
            actor=actor,
        )

    @staticmethod
    def _roles(roles: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(roles, Mapping):
            raise PortfolioError("roles must be an object")
        parent = _ref(roles.get("parent"), "roles.parent")
        manager = _text(roles.get("manager"), "roles.manager")
        executor = roles.get("executor")
        if isinstance(executor, str):
            executor_value: Any = [_text(executor, "roles.executor")]
        elif isinstance(executor, Sequence) and not isinstance(executor, (str, bytes)):
            executor_value = [_text(value, "roles.executor") for value in executor]
            if not executor_value:
                raise PortfolioError("roles.executor must not be empty")
        else:
            raise PortfolioError("roles.executor must be text or a bounded list of text")
        if len(executor_value) > 8:
            raise PortfolioError("roles.executor exceeds the bounded executor limit")
        result = {"parent": parent, "manager": manager, "executor": executor_value}
        if "profile" in roles:
            result["profile"] = _text(roles["profile"], "roles.profile")
        return result

    def admit(
        self,
        project_ref: Any,
        *,
        choice: str,
        frame: Mapping[str, Any],
        actor: str,
        request_id: str,
        roles: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        choice = _text(choice, "choice")
        if choice not in ADMISSION_CHOICES:
            raise PortfolioError("choice must be one of: " + ", ".join(ADMISSION_CHOICES))
        if not isinstance(frame, Mapping):
            raise PortfolioError("frame must be an object")
        frame_value = _json_copy(dict(frame), field="frame")
        for key in ("outcome", "recipient", "route", "authority"):
            _text(frame_value.get(key), f"frame.{key}")
        payload: dict[str, Any] = {"project_ref": _ref(project_ref), "choice": choice, "frame": frame_value}
        if roles is not None:
            payload["roles"] = self._roles(roles)
        return self._execute("work.pending.admission", payload, request_id=request_id, actor=actor)

    def assign_roles(self, project_ref: Any, roles: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.responsibility.assign",
            {"project_ref": _ref(project_ref), "roles": self._roles(roles)},
            request_id=request_id,
            actor=actor,
        )

    def complete_task(
        self,
        project_ref: Any,
        task_ref: Any,
        assignment_ref: Any,
        *,
        actor: str,
        request_id: str,
        expected_generation: int,
        expected_project_revision: str,
        expected_task_revision: str,
        disposition: str,
        evidence_refs: Sequence[Any] = (),
        evidence_hashes: Any = (),
        gate_refs: Sequence[Any] = (),
        candidate_ref: Any = None,
        result_ref: Any = None,
        attempt_ref: Any = None,
        source_set_digest: Optional[str] = None,
    ) -> dict[str, Any]:
        """Request a manager-verified close through the existing owner path."""

        request_id, actor = self._request(request_id, actor)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
            raise PortfolioError("expected_generation must be a positive integer")
        if not isinstance(expected_project_revision, str) or not expected_project_revision.strip():
            raise PortfolioError("expected_project_revision is required")
        if not isinstance(expected_task_revision, str) or not expected_task_revision.strip():
            raise PortfolioError("expected_task_revision is required")
        if not isinstance(disposition, str) or not disposition.strip():
            raise PortfolioError("disposition is required")
        if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, (str, bytes)):
            raise PortfolioError("evidence_refs must be a list")
        if not isinstance(gate_refs, Sequence) or isinstance(gate_refs, (str, bytes)):
            raise PortfolioError("gate_refs must be a list")
        if isinstance(evidence_hashes, Mapping):
            # Empty evidence is sent to the owner as a held/unknown result so
            # callers can inspect the missing prerequisite without a mutation.
            hashes = _json_copy(dict(evidence_hashes), field="evidence_hashes")
        elif isinstance(evidence_hashes, Sequence) and not isinstance(evidence_hashes, (str, bytes)):
            # Empty evidence is sent to the owner as a held/unknown result.
            hashes = _json_copy(list(evidence_hashes), field="evidence_hashes")
        else:
            raise PortfolioError("evidence_hashes must be a non-empty mapping or list")
        payload = {
            "project_ref": _ref(project_ref),
            "task_ref": _ref(task_ref, "task_ref"),
            "assignment_ref": _ref(assignment_ref, "assignment_ref"),
            "expected_generation": expected_generation,
            "expected_project_revision": expected_project_revision,
            "expected_task_revision": expected_task_revision,
            "disposition": disposition.strip(),
            "evidence_refs": [_ref(value, "evidence_ref") for value in evidence_refs],
            "evidence_hashes": hashes,
            "gate_refs": [_ref(value, "gate_ref") for value in gate_refs],
        }
        for name, value in (("candidate_ref", candidate_ref), ("result_ref", result_ref), ("attempt_ref", attempt_ref)):
            if value is not None:
                payload[name] = _ref(value, name)
        if source_set_digest is not None:
            payload["source_set_digest"] = _text(source_set_digest, "source_set_digest")
        return self._execute("work.task.complete", payload, request_id=request_id, actor=actor)

    close_task = complete_task

    def handoff(
        self,
        project_ref: Any,
        *,
        from_manager: str,
        to_manager: str,
        evidence_refs: Sequence[Any],
        consumption_refs: Sequence[Any],
        parent_obligation: Any,
        actor: str,
        request_id: str,
        manager_assignment_ref: Any = None,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        from_manager, to_manager = _text(from_manager, "from_manager"), _text(to_manager, "to_manager")
        if from_manager == to_manager:
            raise PortfolioError("handoff must name a replacement manager")
        if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, (str, bytes)) or not evidence_refs:
            raise PortfolioError("evidence_refs must be a non-empty list")
        if not isinstance(consumption_refs, Sequence) or isinstance(consumption_refs, (str, bytes)) or not consumption_refs:
            raise PortfolioError("consumption_refs must be a non-empty list")
        payload = {
            "project_ref": _ref(project_ref),
            "from_manager": from_manager,
            "to_manager": to_manager,
            "evidence_refs": [_ref(value, "evidence_ref") for value in evidence_refs],
            "consumption_refs": [_ref(value, "consumption_ref") for value in consumption_refs],
            "parent_obligation": _ref(parent_obligation, "parent_obligation"),
            "safe_handoff": True,
        }
        if manager_assignment_ref is not None:
            if not isinstance(manager_assignment_ref, Mapping):
                raise PortfolioError("manager_assignment_ref must be the typed reference returned by assign_roles")
            assignment_ref = _ref(manager_assignment_ref, "manager_assignment_ref")
            if assignment_ref.get("kind") != "wrk.assignment" or not isinstance(assignment_ref.get("authority"), str) or not assignment_ref["authority"].strip():
                raise PortfolioError("manager_assignment_ref.kind must be wrk.assignment")
            payload["manager_assignment_ref"] = assignment_ref
        return self._execute("work.responsibility.handoff", payload, request_id=request_id, actor=actor)


__all__ = [
    "ADMISSION_CHOICES",
    "EDITABLE_FIELDS",
    "HerzchenWorkOperations",
    "OttoPortfolio",
    "PortfolioError",
    "UnavailableWorkOperations",
    "unavailable_operations",
]
