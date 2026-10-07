"""Public finite Herzchen command/read binding for the OTT-03 facade.

The trusted bootstrap constructs the accepted Herzchen graph and injects only
its finite command port and read-only consumer reader. Otto owns neither
storage nor a second command/event implementation.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Optional

from .resource_sync import ResourceSyncError, normalize_role_attachments, resolve_role_attachments, role_resource_pins


# Keep the consumer facade's public instance shape stable while lifecycle
# authority remains injected exclusively by the trusted owner bootstrap.
_LIFECYCLE_PORTS: dict[int, Any] = {}
_ORCHESTRATION_PORTS: dict[int, Any] = {}
_ORCHESTRATION_PORTFOLIOS: dict[int, Any] = {}


def _lifecycle_for(operations: Any) -> Any:
    return _LIFECYCLE_PORTS.get(id(operations))


def _orchestration_for(operations: Any) -> Any:
    return _ORCHESTRATION_PORTS.get(id(operations))


def _orchestration_portfolio_for(operations: Any) -> Any:
    return _ORCHESTRATION_PORTFOLIOS.get(id(operations))


@dataclass(frozen=True)
class HerzchenBindingConfig:
    """Explicit authority and credential used to authenticate an Otto actor."""

    authority: str
    credential_ref: str

    def authenticated_actor(self, actor: str) -> Any:
        from herzchen.contracts import AuthenticatedActor

        return AuthenticatedActor(self.authority, actor, self.credential_ref)


@dataclass(frozen=True)
class ProjectReadGrant:
    """Finite project identities admitted by a trusted host for one actor."""

    principal: Any
    project_ids: tuple[str, ...]
    policy_source: str
    policy_revision: str

    def __post_init__(self) -> None:
        from herzchen.contracts import AuthenticatedActor

        if not isinstance(self.principal, AuthenticatedActor):
            raise TypeError("project grant principal must be authenticated")
        if (not isinstance(self.project_ids, tuple) or not all(
            isinstance(value, str) and value.strip() and "/" not in value
            for value in self.project_ids
        ) or len(set(self.project_ids)) != len(self.project_ids)):
            raise ValueError("project grant must contain distinct finite project IDs")
        if not all(isinstance(value, str) and value.strip() for value in (self.policy_source, self.policy_revision)):
            raise ValueError("project grant requires an authoritative policy source and revision")

    def allows(self, ref: Any) -> bool:
        return (
            getattr(ref, "authority", None) == self.principal.authority
            and getattr(ref, "kind", None) == "work.project"
            and getattr(ref, "id", None) in self.project_ids
        )


class _ScopedProjectReader:
    """Expose granted projects and their owner-backed tasks to finite readers."""

    __slots__ = ("__reader", "__grant", "authority")

    def __init__(self, reader: Any, grant: Optional[ProjectReadGrant], authority: str) -> None:
        self.__reader = reader
        self.__grant = grant
        self.authority = authority

    def get_record(self, ref: Any) -> Any:
        if self.__grant is None:
            return None
        if self.__grant.allows(ref):
            return self.__reader.get_record(ref)
        if getattr(ref, "kind", None) != "work.task" or getattr(ref, "authority", None) != self.authority:
            return None
        record = self.__reader.get_record(ref)
        parent = getattr(record, "payload", {}).get("project_ref") if record is not None else None
        if isinstance(parent, Mapping):
            from herzchen.contracts import ResourceRef

            try:
                parent = ResourceRef.from_dict(parent)
            except (TypeError, ValueError, KeyError):
                return None
        return record if self.__grant.allows(parent) else None

    def get_identity(self, ref: Any) -> Any:
        if self.__grant is None:
            return None
        if self.__grant.allows(ref):
            return self.__reader.get_identity(ref)
        if getattr(ref, "kind", None) != "work.task" or getattr(ref, "authority", None) != self.authority:
            return None
        identity = self.__reader.get_identity(ref)
        parent = getattr(identity, "payload", {}).get("project_ref") if identity is not None else None
        if isinstance(parent, Mapping):
            from herzchen.contracts import ResourceRef

            try:
                parent = ResourceRef.from_dict(parent)
            except (TypeError, ValueError, KeyError):
                return None
        return identity if self.__grant.allows(parent) else None

    def list_events(self, *, stream: Optional[str] = None) -> tuple[Any, ...]:
        if self.__grant is None:
            return ()
        return tuple(event for event in self.__reader.list_events(stream=stream)
                     if self.__grant.allows(getattr(event, "subject", None)))


def _json_value(value: Any) -> Any:
    """Serialize public Herzchen model values without reaching through them."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        import json

        return json.loads(to_json())
    if hasattr(value, "value"):
        return _json_value(value.value)
    return str(value)


def _record_dict(record: Any) -> dict[str, Any]:
    payload = _json_value(getattr(record, "payload", {}))
    return {
        "project_ref": _json_value(getattr(record, "ref", None)),
        "kind": _json_value(getattr(record, "kind", None) or payload.get("kind")),
        "title": _json_value(getattr(record, "title", None) or payload.get("title")),
        "name": _json_value(getattr(record, "name", None) or payload.get("name")),
        "lifecycle": _json_value(getattr(record, "lifecycle", None) or payload.get("lifecycle")),
        "readiness": _json_value(getattr(record, "readiness", None) or payload.get("readiness")),
        "revision": _json_value(getattr(getattr(record, "ref", None), "revision", None)),
        "version": _json_value(getattr(record, "version", None)),
        "payload": payload,
    }


def _receipt_dict(receipt: Any) -> Optional[dict[str, Any]]:
    if receipt is None:
        return None
    to_dict = getattr(receipt, "to_dict", None)
    return _json_value(to_dict() if callable(to_dict) else receipt)


class FiniteWorkOperations:
    """The real OTT-03 operation port over a finite command/read pair."""

    def __init__(
        self,
        *,
        port: Any,
        reader: Any,
        binding: HerzchenBindingConfig,
        sheet_port: Any = None,
        content_port: Any = None,
        assignments_port: Any = None,
        lifecycle_port: Any = None,
        authoring_port: Any = None,
        create_open_port: Any = None,
        orchestration_port: Any = None,
        orchestration_portfolio: Any = None,
        project_read_grant: Optional[ProjectReadGrant] = None,
        content_command_guard: Any = None,
    ) -> None:
        if port is None or reader is None:
            raise ValueError("port and reader are required for the canonical binding")
        self.port = port
        if project_read_grant is not None and (
            not isinstance(project_read_grant, ProjectReadGrant)
            or project_read_grant.principal.authority != binding.authority
            or project_read_grant.principal.credential_ref != binding.credential_ref
        ):
            raise ValueError("project read grant does not match the owner binding")
        self._owner_reader = reader
        self.reader = _ScopedProjectReader(reader, project_read_grant, binding.authority)
        self.project_read_grant = project_read_grant
        self.binding = binding
        self.sheet_port = sheet_port
        self.content_port = content_port
        self.content_command_guard = content_command_guard
        self.assignments_port = assignments_port
        if lifecycle_port is not None:
            _LIFECYCLE_PORTS[id(self)] = lifecycle_port
        self.authoring_port = authoring_port
        self.create_open_port = create_open_port
        if orchestration_port is not None:
            _ORCHESTRATION_PORTS[id(self)] = orchestration_port
            _ORCHESTRATION_PORTFOLIOS[id(self)] = orchestration_portfolio

    def _actor(self, actor: str) -> Any:
        return self.binding.authenticated_actor(actor)

    def _read_grant(self, actor: str) -> Optional[ProjectReadGrant]:
        grant = self.project_read_grant
        return grant if grant is not None and grant.principal == self._actor(actor) else None

    @staticmethod
    def _project_read_denied() -> dict[str, Any]:
        return {"outcome": "denied", "read_only": True, "projects": [],
                "error": {"code": "project_scope_denied", "message": "project read scope is unavailable"}}

    def list_projects(self, *, actor: str, parent_ref: Any = None,
                      cursor: Optional[str] = None, limit: Optional[int] = None) -> Mapping[str, Any]:
        """List only the host-granted finite project identities, including completed."""
        from herzchen.contracts import ResourceRef

        grant = self._read_grant(actor)
        if grant is None:
            return self._project_read_denied()
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000):
            return self._project_read_denied()
        parent = None
        if parent_ref is not None:
            try:
                parent = ResourceRef.from_dict(parent_ref) if isinstance(parent_ref, Mapping) else parent_ref
            except (TypeError, ValueError, KeyError):
                return self._project_read_denied()
            if not grant.allows(parent):
                return self._project_read_denied()
        after = ""
        if cursor is not None:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
                if (value.get("actor") != grant.principal.actor
                        or value.get("authority") != grant.principal.authority
                        or value.get("policy_source") != grant.policy_source
                        or value.get("policy_revision") != grant.policy_revision
                        or value.get("parent") != _json_value(parent)):
                    return self._project_read_denied()
                after = value["after"]
                if after not in grant.project_ids:
                    return self._project_read_denied()
            except (AttributeError, TypeError, ValueError, KeyError, UnicodeError, binascii.Error):
                return self._project_read_denied()
        selected: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for project_id in sorted(grant.project_ids):
            if project_id <= after:
                continue
            record = self._owner_reader.get_record(ResourceRef(grant.principal.authority, "work.project", project_id))
            if record is None:
                issues.append({"code": "project_record_missing", "project_ref": {"authority": grant.principal.authority, "kind": "work.project", "id": project_id}})
                continue
            ref = getattr(record, "ref", None)
            if not grant.allows(ref):
                issues.append({"code": "project_record_identity_mismatch", "project_ref": {"authority": grant.principal.authority, "kind": "work.project", "id": project_id}})
                continue
            payload = getattr(record, "payload", None)
            if not isinstance(payload, Mapping):
                issues.append({"code": "project_record_payload_malformed", "project_ref": _json_value(ref)})
                continue
            actual_parent = payload.get("parent")
            if parent is not None:
                parent_value = _json_value(parent)
                if not isinstance(actual_parent, Mapping) or any(actual_parent.get(key) != parent_value[key] for key in ("authority", "kind", "id")):
                    continue
            selected.append({"project_ref": _json_value(ref), "title": payload.get("title") or payload.get("name"),
                             "lifecycle": payload.get("lifecycle", "unknown"), "parent_ref": _json_value(actual_parent),
                             "readiness": _json_value(payload.get("readiness", {}))})
        page = selected if limit is None else selected[:limit]
        next_cursor = None
        if limit is not None and len(selected) > limit:
            next_cursor = base64.urlsafe_b64encode(json.dumps({"actor": grant.principal.actor,
                "authority": grant.principal.authority, "policy_source": grant.policy_source,
                "policy_revision": grant.policy_revision, "parent": _json_value(parent),
                "after": page[-1]["project_ref"]["id"]}, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
        return {"outcome": "listed" if not issues else "partial", "schema": "otto.portfolio-projects.v1",
                "scope": {"authority": grant.principal.authority, "actor": grant.principal.actor, "parent_ref": _json_value(parent)},
                "projects": page, "count": len(page), "next_cursor": next_cursor,
                "read_only": True, "writes": 0, "issues": issues, "actor_acl": "host_grant"}

    def _events_for(self, receipt: Any) -> list[str]:
        receipt_dict = _receipt_dict(receipt) or {}
        wanted = set(receipt_dict.get("event_ids", []))
        if not wanted:
            return []
        return [event.event_id for event in self._owner_reader.list_events() if getattr(event, "event_id", None) in wanted]

    def _result(self, record: Any, *, request_id: str, replayed: bool) -> dict[str, Any]:
        receipt = self._owner_reader.get_receipt(request_id)
        observed = self._owner_reader.get_record(record.ref)
        return {
            "outcome": "replayed" if replayed else "created",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(observed),
            "receipt": _receipt_dict(receipt),
            "replayed": replayed,
            "event_ids": self._events_for(receipt),
            "executable": False,
            "open": {"status": "not_requested"},
        }

    def _metadata(self, payload: Mapping[str, Any], request_id: str, template: Any) -> dict[str, Any]:
        edit = payload.get("edit", {})
        metadata = dict(edit.get("metadata", {})) if isinstance(edit.get("metadata", {}), Mapping) else {}
        for key, value in edit.items():
            if key not in {"title", "outcome", "metadata"}:
                metadata.setdefault(key, value)
        metadata.setdefault("template", template)
        metadata["otto_request"] = {"logical_request_key": request_id, "payload": dict(payload)}
        return metadata

    def execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if operation == "work.project.export":
            return self._export_project(payload, request_id=request_id)
        if operation == "work.project.import":
            return self._import_project(payload, request_id=request_id, actor=actor)
        if operation == "work.task.dependency-refresh":
            return self._refresh_task_dependency(payload, request_id=request_id, actor=actor)
        if operation == "work.lifecycle.transition":
            return self._lifecycle_transition(payload, request_id=request_id, actor=actor)
        if operation == "work.lifecycle.read":
            return self._lifecycle_read(payload, request_id=request_id)
        if operation == "work.project.lifecycle.transition":
            return self._transition_project_lifecycle(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.fence":
            return self._fence_assignment(payload, request_id=request_id)
        if operation == "work.responsibility.dispatch":
            return self._dispatch_assignment(payload, request_id=request_id, actor=actor)
        if operation == "work.orchestrator.project.create":
            return self._create_orchestrated_project(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.create" and payload.get("open"):
            return self._create_and_open(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.create" and _orchestration_for(self) is not None:
            if isinstance(payload.get("template"), Mapping):
                return self._create_orchestrated_template(payload, request_id=request_id, actor=actor)
            return self._create_orchestrated_project(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.create" and isinstance(payload.get("template"), Mapping):
            return self._create_from_template(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.open":
            return self._open_existing(payload, request_id=request_id, actor=actor)
        if operation in {"work.project.folder-import", "work.project.folder-export", "work.project.folder-check-in", "work.project.folder-release"}:
            return self._project_folder(operation, payload, request_id=request_id, actor=actor)
        if operation in {"work.project.checkout", "work.project.check-in"}:
            return self._project_authoring(operation, payload, request_id=request_id, actor=actor)
        if operation == "work.pending.edit":
            return self._revise(payload, request_id=request_id, actor=actor)
        if operation in {"work.pending.revisit", "work.pending.prerequisite-satisfied"}:
            return self._attention(operation, payload, request_id=request_id, actor=actor)
        if operation == "work.pending.admission":
            return self._admit(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.assign":
            return self._assign_roles(payload, request_id=request_id, actor=actor)
        if operation == "work.project-advisor.pair":
            return self._project_advisor_pair(payload, request_id=request_id, actor=actor)
        if operation in {"work.task.complete", "work.project-sheet.complete"}:
            return self._complete_task(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.handoff":
            return self._handoff(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.document.create":
            return self._create_document(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.document.link":
            return self._link_document(payload, request_id=request_id, actor=actor)
        if operation != "work.pending.create":
            return self._unsupported(operation, request_id=request_id)
        if payload.get("open"):
            return self._unsupported(operation, request_id=request_id, code="canonical_open_endpoint_unavailable", message="the finite accepted work port has no canonical open/session endpoint")
        edit = payload.get("edit", {})
        actor_value = self._actor(actor)
        before = self._owner_reader.get_receipt(request_id)
        try:
            record = self.port.create_pending_project(
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                logical_request_key=request_id,
                actor=actor_value,
                creator=actor_value,
                curator=actor_value,
                metadata=self._metadata(payload, request_id, payload.get("template", "blank")),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {
                    "outcome": "error",
                    "error": {"code": "replay_conflict", "message": str(exc), "operation": operation},
                    "replayed": False,
                    "event_ids": [],
                }
            raise
        return self._result(record, request_id=request_id, replayed=before is not None)

    def _create_orchestrated_project(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Use the one owner-local WRK operation for placement and creation."""

        orchestration = _orchestration_for(self)
        portfolio_ref = _orchestration_portfolio_for(self)
        if orchestration is None or portfolio_ref is None:
            return self._unsupported(
                "work.orchestrator.project.create",
                request_id=request_id,
                code="canonical_orchestration_port_unavailable",
                message="qualified owner orchestration binding was not injected",
            )
        edit = payload.get("edit", {})
        if not isinstance(edit, Mapping):
            return {"outcome": "error", "error": {"code": "invalid_edit", "message": "edit must be an object", "operation": "work.orchestrator.project.create"}, "replayed": False, "event_ids": []}
        actor_value = self._actor(actor)
        before = self._receipt(request_id)
        try:
            result = orchestration.create_pending_with_supervisor(
                actor=actor_value,
                request_id=request_id,
                portfolio_ref=portfolio_ref,
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                metadata=self._metadata(payload, request_id, payload.get("template", "blank")),
                expected_project_version=0,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.orchestrator.project.create"}, "replayed": False, "event_ids": []}
            raise
        if not isinstance(result, Mapping):
            return {"outcome": "error", "error": {"code": "malformed_orchestration_result", "message": "owner orchestration returned a non-object", "operation": "work.orchestrator.project.create"}, "replayed": False, "event_ids": []}
        project_ref = result.get("project_ref")
        project_target = None if project_ref is None else self._record_ref(project_ref)
        observed = None if project_target is None else self._owner_reader.get_record(project_target)
        supervision = result.get("supervision") if isinstance(result.get("supervision"), Mapping) else {}
        assignment_ref = result.get("assignment_ref") or supervision.get("assignment_ref")
        assignment = None
        if assignment_ref is not None and self.assignments_port is not None:
            assignment = self.assignments_port.get(self._record_ref(assignment_ref))
        event_ids = list(result.get("event_ids", ()))
        for key in (request_id, request_id + ":project"):
            for event_id in self._events_for(self._receipt(key)):
                if event_id not in event_ids:
                    event_ids.append(event_id)
        return {
            "outcome": result.get("outcome", "replayed" if before is not None else "created"),
            "project_ref": _json_value(project_ref),
            "record": None if observed is None else _record_dict(observed),
            "receipt": result.get("receipt") or _receipt_dict(self._receipt(request_id)),
            "project_receipt": result.get("project_receipt") or _receipt_dict(self._receipt(request_id + ":project")),
            "assignment": None if assignment is None else self._assignment_dict(assignment),
            "current_assignment": None if assignment is None else self._assignment_dict(assignment),
            "default_assignment_ref": _json_value(assignment_ref),
            "default_ref": _json_value(result.get("default_ref") or supervision.get("default_ref")),
            "supervision": _json_value(result.get("supervision")),
            "replayed": bool(result.get("replayed", before is not None)),
            "event_ids": event_ids,
            "executable": False,
        }

    def _create_orchestrated_template(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Create atomically, then apply the existing template batch after commit."""
        if self.sheet_port is None:
            return self._unsupported("work.pending.create", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet command port was not injected")
        try:
            template = self._typed_template(payload["template"], payload.get("template_parameters"))
        except Exception as exc:
            return self._template_error(exc)
        created = self._create_orchestrated_project(payload, request_id=request_id, actor=actor)
        if created.get("outcome") == "error":
            return created
        project_ref = created.get("project_ref")
        template_key = request_id + ":template"
        try:
            materialized = self.sheet_port.instantiate_new_template(
                template,
                payload.get("template_parameters"),
                project=self._record_ref(project_ref),
                logical_request_key=template_key,
                actor=self._actor(actor),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.create"}, "replayed": False, "event_ids": []}
            return self._template_error(exc)
        record = self._owner_reader.get_record(self._record_ref(project_ref))
        mappings = getattr(materialized, "mappings", {})
        task_records = []
        if isinstance(mappings, Mapping):
            for local_id, task_ref in mappings.items():
                task_record = self._owner_reader.get_record(task_ref)
                task_records.append({
                    "local_id": str(local_id),
                    "ref": _json_value(task_ref),
                    "record": None if task_record is None else _record_dict(task_record),
                })
        result = dict(created)
        result.update({
            "record": None if record is None else _record_dict(record),
            "template": _json_value(template),
            "template_receipt": _receipt_dict(self._receipt(template_key)),
            "template_ref": _json_value(getattr(template, "ref", None)),
            "template_revision": getattr(template, "revision", None),
            "tasks": task_records,
            "task_refs": [_json_value(item["ref"]) for item in task_records],
            "task_created": bool(task_records),
        })
        event_ids = list(result.get("event_ids", ()))
        for event_id in self._events_for(self._receipt(template_key)):
            if event_id not in event_ids:
                event_ids.append(event_id)
        result["event_ids"] = event_ids
        return result

    @staticmethod
    def _key(request_id: str, suffix: str) -> str:
        return request_id + ":" + suffix

    def _record_ref(self, value: Any) -> Any:
        from herzchen.contracts import ResourceRef

        return ResourceRef.from_dict(value) if isinstance(value, Mapping) else value

    @staticmethod
    def _same_identity(left: Any, right: Any) -> bool:
        if isinstance(left, Mapping):
            left = (left.get("authority"), left.get("kind"), left.get("id"))
        else:
            left = (getattr(left, "authority", None), getattr(left, "kind", None), getattr(left, "id", None))
        if isinstance(right, Mapping):
            right = (right.get("authority"), right.get("kind"), right.get("id"))
        else:
            right = (getattr(right, "authority", None), getattr(right, "kind", None), getattr(right, "id", None))
        return (
            left[0], left[1], left[2]
        ) == (
            right[0], right[1], right[2]
        )

    def _receipt(self, request_id: str) -> Any:
        return self._owner_reader.get_receipt(request_id)

    def _receipt_result(self, request_id: str, *, outcome: str, **values: Any) -> dict[str, Any]:
        receipt = self._receipt(request_id)
        result = {
            "outcome": outcome,
            "receipt": _receipt_dict(receipt),
            "replayed": bool(receipt and getattr(receipt, "replayed", False)),
            "event_ids": self._events_for(receipt),
        }
        result.update(values)
        return result

    def _refresh_task_dependency(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """A supported owner operation that acknowledges a current prerequisite.

        ProjectSheet intentionally stores dependency links by identity, so a
        normal ``link_dependency`` replay cannot remove the historical
        revision observed by the read-only manager projection.  This command
        uses the accepted ProjectSheet batch and records the current
        prerequisite revision in task metadata.  The inbox reader treats that
        typed marker as an owner acknowledgement only while the observed
        prerequisite still has the acknowledged revision.
        """

        if self.sheet_port is None:
            return self._unsupported(
                "work.task.dependency-refresh",
                request_id=request_id,
                code="canonical_project_sheet_port_unavailable",
                message="accepted ProjectSheet command port was not injected",
            )
        try:
            from herzchen.contracts import ResourceRef

            task_ref = ResourceRef.from_dict(payload["task_ref"])
            dependency_ref = ResourceRef.from_dict(payload["dependency_ref"])
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "outcome": "error",
                "error": {"code": "invalid_dependency_refresh", "message": str(exc), "operation": "work.task.dependency-refresh"},
                "replayed": False,
                "event_ids": [],
            }
        before = self._receipt(request_id)
        task = self._owner_reader.get_record(ResourceRef(task_ref.authority, task_ref.kind, task_ref.id))
        dependency = self._owner_reader.get_record(ResourceRef(dependency_ref.authority, dependency_ref.kind, dependency_ref.id))
        task_payload = getattr(task, "payload", {}) if task is not None else {}
        dependency_payload = getattr(dependency, "payload", {}) if dependency is not None else {}
        if task is None or not isinstance(task_payload, Mapping) or task_payload.get("kind") != "task":
            return {"outcome": "error", "error": {"code": "task_not_found", "message": "task_ref is not a readable work.task"}, "replayed": False, "event_ids": []}
        if dependency is None or not isinstance(dependency_payload, Mapping) or dependency_payload.get("kind") != "task":
            return {"outcome": "error", "error": {"code": "dependency_not_found", "message": "dependency_ref is not a readable work.task"}, "replayed": False, "event_ids": []}
        project_value = task_payload.get("project_ref")
        dependency_project_value = dependency_payload.get("project_ref")
        try:
            project_ref = ResourceRef.from_dict(project_value) if isinstance(project_value, Mapping) else None
            dependency_project_ref = ResourceRef.from_dict(dependency_project_value) if isinstance(dependency_project_value, Mapping) else None
        except (TypeError, ValueError):
            project_ref = dependency_project_ref = None
        if project_ref is None or dependency_project_ref is None or not self._same_identity(project_ref, dependency_project_ref):
            return {"outcome": "error", "error": {"code": "dependency_scope_mismatch", "message": "task and prerequisite must share a project"}, "replayed": False, "event_ids": []}
        if not any(self._same_identity(ref, dependency.ref) for ref in task_payload.get("dependencies", ())):
            return {"outcome": "error", "error": {"code": "dependency_not_linked", "message": "task does not currently link dependency_ref"}, "replayed": False, "event_ids": []}
        project = self._owner_reader.get_record(ResourceRef(project_ref.authority, project_ref.kind, project_ref.id))
        if project is None:
            return {"outcome": "error", "error": {"code": "project_not_found", "message": "task project is not readable"}, "replayed": False, "event_ids": []}
        if before is not None:
            result = self._receipt_result(
                request_id,
                outcome="replayed",
                project_ref=_json_value(getattr(before, "result_ref", None) or project.ref),
                task_ref=_json_value(getattr(task, "ref", task_ref)),
                dependency_ref=_json_value(getattr(dependency, "ref", dependency_ref)),
                acknowledged_revision=_json_value(dependency.ref.revision),
            )
            result["replayed"] = True
            return result

        metadata = dict(task_payload.get("metadata", {})) if isinstance(task_payload.get("metadata", {}), Mapping) else {}
        marker = metadata.get("otto_dependency_refresh", [])
        marker = list(marker) if isinstance(marker, (list, tuple)) else []
        marker = [item for item in marker if isinstance(item, Mapping) and not self._same_identity(item.get("ref"), dependency.ref)]
        marker.append({"ref": _json_value(dependency.ref), "revision": _json_value(dependency.ref.revision), "source": "otto.owner.dependency-refresh.v1"})
        metadata["otto_dependency_refresh"] = marker
        dependencies = [_json_value(ref) for ref in task_payload.get("dependencies", ())]
        try:
            batch = self.sheet_port.apply(
                project.ref,
                {"tasks": [{"id": task_ref.id, "dependencies": dependencies, "metadata": metadata}]},
                logical_request_key=request_id,
                actor=self._actor(actor),
                base_revision=project.ref.revision,
            )
        except Exception as exc:
            return {"outcome": "error", "error": {"code": type(exc).__name__, "message": str(exc), "operation": "work.task.dependency-refresh"}, "replayed": False, "event_ids": []}
        receipt = getattr(batch, "receipt", None)
        replayed = bool(getattr(receipt, "replayed", False))
        observed_task = self._owner_reader.get_record(ResourceRef(task_ref.authority, task_ref.kind, task_ref.id))
        return self._receipt_result(
            request_id,
            outcome="replayed" if replayed else "refreshed",
            project_ref=_json_value(getattr(batch.project, "ref", project.ref)),
            task_ref=_json_value(getattr(observed_task, "ref", task.ref)),
            dependency_ref=_json_value(getattr(dependency, "ref", dependency_ref)),
            acknowledged_revision=_json_value(dependency.ref.revision),
        )

    def _lifecycle_transition(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        lifecycle_port = _lifecycle_for(self)
        if lifecycle_port is None:
            return self._unsupported("work.lifecycle.transition", request_id=request_id, code="canonical_lifecycle_port_unavailable", message="canonical owner lifecycle port was not injected")
        try:
            from herzchen.contracts import ResourceRef
            project_ref = ResourceRef.from_dict(payload["project_ref"])
            result = lifecycle_port.transition(
                project_ref,
                action=payload["action"],
                logical_request_key=request_id,
                expected_project_revision=payload["expected_project_revision"],
                generation=payload["generation"],
                expected_project_version=payload.get("expected_project_version"),
                manager_assignment=payload.get("manager_assignment"),
                task=payload.get("task_ref"),
                orchestrator_assignment=payload.get("orchestrator_assignment"),
                orchestrator_principal=payload.get("orchestrator_principal"),
                task_refs=payload.get("task_refs", ()),
                attribution_digest=payload.get("attribution_digest"),
                owner_attribution=payload.get("owner_attribution"),
                evidence=payload.get("evidence"),
                schedule_observation=payload.get("schedule_observation"),
                effect_packet=payload.get("effect_packet"),
                settlement=payload.get("settlement"),
                actor=self._actor(actor),
            )
            return _json_value(result)
        except Exception as exc:
            return {"outcome":"error","error":{"code":type(exc).__name__,"message":str(exc),"operation":"work.lifecycle.transition"},"replayed":False,"event_ids":[]}

    def _lifecycle_read(self, payload: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        lifecycle_port = _lifecycle_for(self)
        if lifecycle_port is None:
            return self._unsupported("work.lifecycle.read", request_id=request_id, code="canonical_lifecycle_port_unavailable", message="canonical owner lifecycle port was not injected")
        try:
            from herzchen.contracts import ResourceRef
            project_ref = ResourceRef.from_dict(payload["project_ref"])
            result = lifecycle_port.read_current(project_ref)
            return _json_value(result)
        except Exception as exc:
            return {"outcome":"error","error":{"code":type(exc).__name__,"message":str(exc),"operation":"work.lifecycle.read"},"replayed":False,"event_ids":[]}

    def _transition_project_lifecycle(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Compatibility adapter for the established portfolio lifecycle call."""
        intent = payload.get("intent")
        action = {
            "active": "activate",
            "closing": "manager-close-request",
            "blocked": "manager-close-request",
            "terminal": "orchestrator-close",
        }.get(intent)
        if action is None:
            return {"outcome": "error", "error": {"code": "unsupported_lifecycle_intent", "message": "unsupported project lifecycle intent", "operation": "work.project.lifecycle.transition"}, "replayed": False, "event_ids": []}
        obligation = payload.get("obligation") if isinstance(payload.get("obligation"), Mapping) else {}
        translated = {
            "project_ref": payload.get("project_ref"),
            "action": action,
            "expected_project_revision": payload.get("expected_project_revision"),
            "generation": payload.get("expected_generation"),
            "manager_assignment": payload.get("manager_ref") if action != "orchestrator-close" else None,
            "task_ref": payload.get("task_ref"),
            "orchestrator_assignment": payload.get("orchestrator_ref", obligation.get("orchestrator_assignment")),
            "evidence": payload.get("evidence"),
            "effect_packet": obligation.get("effect_packet"),
        }
        result = self._lifecycle_transition(translated, request_id=request_id, actor=actor)
        if isinstance(result, Mapping) and result.get("outcome") in {"transitioned", "replayed"}:
            observed = result.get("read") if isinstance(result.get("read"), Mapping) else {}
            result = dict(result)
            result.setdefault("state", observed.get("lifecycle"))
            transition = observed.get("transition")
            if isinstance(transition, Mapping):
                transition = dict(transition)
                transition.setdefault("intent", {"activate": "active", "resume": "active", "manager-close-request": "closing", "orchestrator-close": "terminal"}.get(transition.get("action"), intent))
                result.setdefault("transition", transition)
        return result

    def _export_project(self, payload: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        """Export a typed pending project through the read-only Herzchen reader.

        The snapshot is deliberately a portable representation of public
        records.  It contains no Store, writer, SQLite path, or callback.  A
        consumer can pass it to another owner bootstrap's ``work.project.import``
        endpoint for passive adoption and later comparison.
        """

        from herzchen.contracts import ResourceRef

        try:
            project_ref = ResourceRef.from_dict(payload["project_ref"])
        except (KeyError, TypeError, ValueError) as exc:
            return {"outcome": "error", "error": {"code": "invalid_project_ref", "message": str(exc)}, "event_ids": []}
        record = self._owner_reader.get_record(project_ref)
        if record is None:
            return {"outcome": "error", "error": {"code": "project_not_found", "message": "project is not admitted"}, "event_ids": []}
        source = _record_dict(record)
        raw_payload = dict(source.get("payload", {}))
        tasks = []
        for raw_ref in raw_payload.get("tasks", ()):
            try:
                task = self._owner_reader.get_record(self._record_ref(raw_ref))
            except Exception:
                task = None
            if task is not None:
                tasks.append(_record_dict(task))
        documents = []
        requested_documents = payload.get("document_refs", raw_payload.get("documents", ()))
        if not isinstance(requested_documents, (list, tuple)):
            return {"outcome": "error", "error": {"code": "invalid_document_refs", "message": "document_refs must be an array", "operation": "work.project.export"}, "event_ids": []}
        for raw_ref in requested_documents:
            try:
                document = self._owner_reader.get_record(self._record_ref(raw_ref))
            except Exception:
                document = None
            if document is not None:
                document_value = _record_dict(document)
                current_revision = document_value.get("payload", {}).get("current_revision")
                if current_revision is not None:
                    try:
                        current_ref = self._record_ref(current_revision)
                        # DAT's public read resolves the revision's storage
                        # identity (the neutral reader intentionally does not
                        # expose revision rows as a second mutable identity).
                        revision_read = self.content_port.read(current_ref) if self.content_port is not None else {}
                        revision_payload = dict(revision_read) if isinstance(revision_read, Mapping) else None
                        if isinstance(revision_payload, Mapping) and isinstance(revision_payload.get("content"), (Mapping, list, tuple, str, int, float, bool, type(None))):
                            revision_payload["content_digest"] = sha256(
                                json.dumps(_json_value(revision_payload.get("content")), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                            ).hexdigest()
                            document_value["current_revision_record"] = {
                                "payload": _json_value(revision_payload),
                                "project_ref": _json_value(current_ref),
                                "revision": revision_payload.get("revision"),
                            }
                    except Exception as exc:
                        document_value["_revision_read_error"] = type(exc).__name__ + ": " + str(exc)
                documents.append(document_value)
        links = []
        requested_links = payload.get("association_refs", ())
        if not isinstance(requested_links, (list, tuple)):
            return {"outcome": "error", "error": {"code": "invalid_association_refs", "message": "association_refs must be an array", "operation": "work.project.export"}, "event_ids": []}
        for raw_ref in requested_links:
            try:
                association = self._owner_reader.get_record(self._record_ref(raw_ref))
            except Exception:
                association = None
            if association is not None:
                links.append(_record_dict(association))
        snapshot = {
            "schema": "otto.project-transfer.v1",
            "source_ref": _json_value(record.ref),
            "project": source,
            "tasks": tasks,
            "documents": documents,
            "document_links": links,
            "transfer_limits": {
                "assignments": "provenance-only; source assignment identity and generation are not cloned",
                "sessions": "not cloned",
                "dispatch": "not cloned",
                "execution": "not cloned",
                "manager_launch": "not cloned",
                "budget_reserved": "not cloned",
            },
            "dispatch": False,
            "execution": False,
            "manager_launch": False,
            "budget_reserved": False,
        }
        digest = sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        snapshot["snapshot_digest"] = digest
        return {"outcome": "exported", "snapshot": snapshot, "snapshot_digest": digest, "request_id": request_id, "event_ids": []}

    def _replay_import(self, *, before: Any, computed_digest: str, request_id: str) -> Optional[Mapping[str, Any]]:
        """Return the original import result without re-running its writes.

        Import has several child commands (adoption, document creation, and
        document linking).  Re-entering those commands on an exact retry is
        wrong once the destination project has since been admitted or edited:
        the parent receipt is still the same logical command, while the live
        project revision is newer.  The first import stores a compact result
        manifest in the destination project's public metadata.  An exact
        retry validates the original snapshot digest and reads that manifest,
        preserving the original receipt/event set and producing no new delta.
        """

        from herzchen.contracts import ResourceRef

        target = getattr(before, "target", None) or getattr(before, "result_ref", None)
        if target is None:
            return {
                "outcome": "error",
                "error": {"code": "replay_state_unavailable", "message": "import receipt has no target project", "operation": "work.project.import"},
                "replayed": False,
                "event_ids": [],
            }
        target_ref = ResourceRef(
            getattr(target, "authority", self.binding.authority),
            getattr(target, "kind", "work.project"),
            getattr(target, "id"),
        )
        record = self._owner_reader.get_record(target_ref)
        if record is None:
            return {
                "outcome": "error",
                "error": {"code": "replay_state_unavailable", "message": "import target project is no longer readable", "operation": "work.project.import"},
                "replayed": False,
                "event_ids": [],
            }
        payload = getattr(record, "payload", {})
        metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
        transfer = metadata.get("otto_transfer", {}) if isinstance(metadata, Mapping) else {}
        if not isinstance(transfer, Mapping) or transfer.get("snapshot_digest") != computed_digest:
            return {
                "outcome": "error",
                "error": {"code": "replay_conflict", "message": "logical request key was reused with a changed request digest", "operation": "work.project.import"},
                "replayed": False,
                "event_ids": [],
            }
        saved = metadata.get("otto_transfer_result") if isinstance(metadata, Mapping) else None
        if not isinstance(saved, Mapping):
            # Parent input is already frozen in the creation receipt/metadata;
            # resume its same child receipts rather than creating a new project.
            return None
        result = dict(saved)
        result["outcome"] = "replayed"
        result["replayed"] = True
        result["project_ref"] = _json_value(getattr(record, "ref", target_ref))
        result["record"] = _record_dict(record)
        result["receipt"] = _receipt_dict(before)
        event_ids = list(result.get("event_ids", ()))
        result_receipt = self._receipt(request_id + ":result")
        for event_id in self._events_for(result_receipt):
            if event_id not in event_ids:
                event_ids.append(event_id)
        result["event_ids"] = event_ids
        return result

    def _import_project(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        try:
            result = self._import_project_steps(payload, request_id=request_id, actor=actor)
        except Exception as exc:
            if self._receipt(request_id) is None or type(exc).__name__ == "ReplayConflictError":
                raise
            result = {"outcome": "error", "error": {"code": type(exc).__name__, "message": str(exc)}}
        parent = self._receipt(request_id)
        if (parent is None or result.get("outcome") != "error"
                or result.get("error", {}).get("code") in {"replay_conflict", "invalid_transfer_snapshot", "transfer_digest_mismatch"}):
            return result
        snapshot = payload.get("snapshot", {})
        keys = [request_id + ":adoption", request_id + ":result"]
        keys += [request_id + ":document:" + str(index) for index in range(len(snapshot.get("documents", ())))]
        keys += [request_id + ":document-link:" + str(index) for index in range(len(snapshot.get("document_links", ())))]
        receipts = [self._receipt(key) for key in keys]
        return {**result, "outcome": "partial", "atomic": False, "project_ref": _json_value(parent.result_ref),
                "committed": [_receipt_dict(receipt) for receipt in receipts if receipt is not None],
                "pending_request_keys": [key for key, receipt in zip(keys, receipts) if receipt is None],
                "recovery": "Inspect retained receipts and resume the exact snapshot and request key.",
                "execution": False, "dispatch": False}

    def _import_project_steps(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Passively import a project snapshot through ProjectSheet adoption.

        Import creates one new pending project in the destination authority,
        records the source identity and exact snapshot digest, and adopts the
        source's task/observation payload through the accepted ProjectSheet
        command port.  It never clones a source identity, assignment, session,
        dispatch, or budget authority and therefore cannot create a second
        writer graph.
        """

        if self.sheet_port is None:
            return self._unsupported("work.project.import", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet command port was not injected")
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, Mapping) or snapshot.get("schema") != "otto.project-transfer.v1":
            return {"outcome": "error", "error": {"code": "invalid_transfer_snapshot", "message": "snapshot must be an otto.project-transfer.v1 object", "operation": "work.project.import"}, "event_ids": []}
        source = snapshot.get("project")
        if not isinstance(source, Mapping):
            return {"outcome": "error", "error": {"code": "invalid_transfer_snapshot", "message": "snapshot.project must be an object", "operation": "work.project.import"}, "event_ids": []}
        canonical = dict(snapshot)
        supplied_digest = canonical.pop("snapshot_digest", None)
        computed_digest = sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if supplied_digest != computed_digest:
            return {"outcome": "error", "error": {"code": "transfer_digest_mismatch", "message": "snapshot digest does not match its public records", "operation": "work.project.import"}, "event_ids": []}
        from .project_folder import validate_transfer
        try:
            validate_transfer(snapshot)
        except (ValueError, TypeError, KeyError) as exc:
            return {"outcome": "rejected", "error": {"code": "invalid_transfer_provenance", "message": str(exc)}, "event_ids": []}
        before = self._receipt(request_id)
        if before is not None:
            replay = self._replay_import(before=before, computed_digest=computed_digest, request_id=request_id)
            if replay is not None:
                return replay
        edit_payload = source.get("payload") if isinstance(source.get("payload"), Mapping) else source
        title = edit_payload.get("title") or edit_payload.get("name") or "Imported pending project"
        outcome = edit_payload.get("outcome", "")
        metadata = dict(edit_payload.get("metadata", {})) if isinstance(edit_payload.get("metadata"), Mapping) else {}
        metadata["otto_transfer"] = {"source_ref": _json_value(snapshot.get("source_ref")), "snapshot_digest": computed_digest, "mode": "passive-adoption"}
        actor_value = self._actor(actor)
        try:
            created = self.port.create_pending_project(
                title=title,
                outcome=outcome,
                logical_request_key=request_id,
                actor=actor_value,
                creator=actor_value,
                curator=actor_value,
                metadata=metadata,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project.import"}, "replayed": False, "event_ids": []}
            raise
        target_ref = self._receipt(request_id).result_ref
        raw_tasks = list(snapshot.get("tasks", ()))
        task_ids = {}
        for item in raw_tasks:
            value = item.get("payload") if isinstance(item, Mapping) and isinstance(item.get("payload"), Mapping) else item
            if isinstance(value, Mapping) and value.get("id"):
                task_ids[str(value["id"])] = str(value["id"])
        adopted_tasks = []
        for item in raw_tasks:
            value = item.get("payload") if isinstance(item, Mapping) and isinstance(item.get("payload"), Mapping) else item
            if not isinstance(value, Mapping):
                continue
            task = dict(value)
            dependencies = []
            for dependency in task.get("dependencies", ()):
                dep_id = dependency.get("id") if isinstance(dependency, Mapping) else dependency
                if dep_id is not None and str(dep_id) in task_ids:
                    dependencies.append(task_ids[str(dep_id)])
            task["dependencies"] = dependencies
            adopted_tasks.append(task)
        adopted_source = dict(edit_payload)
        adopted_source["tasks"] = adopted_tasks
        # The Otto transfer schema calls these values ``external_accounting_refs``
        # because they are source-owned accounting identities.  The public
        # ProjectSheet adoption contract names the corresponding read-only
        # census ``external_budget_refs``.  Map the source metadata into that
        # contract before adoption so the destination's census is backed by
        # the same typed references; retaining the values only in ordinary
        # project metadata would make the imported accounting appear empty.
        source_metadata = edit_payload.get("metadata") if isinstance(edit_payload.get("metadata"), Mapping) else {}
        accounting_refs = source_metadata.get("external_accounting_refs", source_metadata.get("external_budget_refs", source_metadata.get("budget_refs", ())))
        if isinstance(accounting_refs, (list, tuple)):
            adopted_source["external_budget_refs"] = _json_value(list(accounting_refs))
        # DAT content remains an independent source-owned identity.  Preserve
        # its full public record and association under adoption metadata rather
        # than manufacturing a destination content revision; C38 explicitly
        # permits deferred seeds to retain unknown fields without cloning live
        # grants, sessions, or accepted results.
        adopted_source["documents"] = list(snapshot.get("documents", ()))
        adopted_source["document_links"] = list(snapshot.get("document_links", ()))
        try:
            adopted = self.sheet_port.adopt_existing_effort(
                adopted_source,
                project=target_ref,
                logical_request_key=request_id + ":adoption",
                actor=actor_value,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project.import"}, "replayed": False, "event_ids": []}
            raise
        # A deferred seed keeps unknown source fields in the adoption record,
        # but an existing document must remain usable by the receiving owner.
        # Recreate each immutable public revision as a new target-owned
        # document through DAT's command port, then recreate its named links.
        # This deliberately maps identities instead of cloning the source
        # document/assignment/session/allowance rows.
        restored_documents: list[dict[str, Any]] = []
        document_map: dict[tuple[str, str, str], Any] = {}
        for index, item in enumerate(snapshot.get("documents", ())):
            if not isinstance(item, Mapping):
                continue
            record_payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            document_value = record_payload.get("document") if isinstance(record_payload.get("document"), Mapping) else {}
            source_ref_value = document_value.get("ref") if isinstance(document_value.get("ref"), Mapping) else item.get("project_ref")
            if not isinstance(source_ref_value, Mapping):
                continue
            source_ref = self._record_ref(source_ref_value)
            source_key = (source_ref.authority, source_ref.kind, source_ref.id)
            revision_record = item.get("current_revision_record") if isinstance(item.get("current_revision_record"), Mapping) else {}
            revision_payload = revision_record.get("payload") if isinstance(revision_record.get("payload"), Mapping) else {}
            content = revision_payload.get("content", {})
            restore_request = request_id + ":document:" + str(index)
            restored = self._create_document(
                {
                    "project_ref": _json_value(target_ref),
                    "document_id": "restored-" + sha256((computed_digest + ":" + ":".join(source_key)).encode("utf-8")).hexdigest()[:28],
                    "role": document_value.get("role", "supporting"),
                    "visibility": document_value.get("visibility", "private"),
                    "access_mode": document_value.get("access_mode", "read"),
                    "content": content,
                },
                request_id=restore_request,
                actor=actor,
            )
            if restored.get("outcome") not in {"created", "replayed"}:
                return {
                    "outcome": "error",
                    "error": {"code": "document_restore_failed", "message": "target-owned document restoration failed", "operation": "work.project.import", "source_ref": _json_value(source_ref), "detail": restored},
                    "replayed": False,
                    "event_ids": [],
                }
            target_document_ref = restored.get("document_ref")
            document_map[source_key] = target_document_ref
            source_content_digest = revision_payload.get("content_digest")
            target_content_digest = None
            content_equal = False
            try:
                target_content_read = self.content_port.read(self._record_ref(target_document_ref)) if self.content_port is not None else {}
                target_revision_read = target_content_read.get("revision") if isinstance(target_content_read, Mapping) else None
                target_content = target_revision_read.get("content") if isinstance(target_revision_read, Mapping) else None
                target_content_digest = sha256(
                    json.dumps(_json_value(target_content), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                content_equal = source_content_digest == target_content_digest
            except Exception:
                content_equal = False
            target_record = restored.get("record") if isinstance(restored.get("record"), Mapping) else {}
            target_payload = target_record.get("payload") if isinstance(target_record.get("payload"), Mapping) else {}
            restored_documents.append({
                "source_ref": _json_value(source_ref),
                "target_ref": target_document_ref,
                "source_revision": revision_payload.get("revision"),
                "target_revision": target_payload.get("current_revision"),
                "content_digest": source_content_digest,
                "target_content_digest": target_content_digest,
                "content_equal": content_equal,
                "receipt": restored.get("receipt"),
                "event_ids": restored.get("event_ids", []),
            })
        restored_links: list[dict[str, Any]] = []
        for index, item in enumerate(snapshot.get("document_links", ())):
            if not isinstance(item, Mapping):
                continue
            link_payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            association = link_payload.get("association") if isinstance(link_payload.get("association"), Mapping) else {}
            source_document = association.get("document") if isinstance(association.get("document"), Mapping) else {}
            source_document_ref = source_document.get("ref") if isinstance(source_document.get("ref"), Mapping) else None
            if not isinstance(source_document_ref, Mapping):
                continue
            source_key = (str(source_document_ref.get("authority")), str(source_document_ref.get("kind")), str(source_document_ref.get("id")))
            target_document_ref = document_map.get(source_key)
            if target_document_ref is None:
                continue
            restored_link = self._link_document(
                {
                    "project_ref": _json_value(target_ref),
                    "document_ref": target_document_ref,
                    "namespace": association.get("namespace", "project.documents"),
                    "key": association.get("key", "document"),
                    "access_mode": association.get("access_mode", "read"),
                },
                request_id=request_id + ":document-link:" + str(index),
                actor=actor,
            )
            if restored_link.get("outcome") not in {"linked", "replayed"}:
                return {
                    "outcome": "error",
                    "error": {"code": "document_link_restore_failed", "message": "target-owned document link restoration failed", "operation": "work.project.import", "detail": restored_link},
                    "replayed": False,
                    "event_ids": [],
                }
            restored_links.append({
                "source": _json_value(source_document_ref),
                "target": target_document_ref,
                "namespace": association.get("namespace"),
                "key": association.get("key"),
                "association_ref": restored_link.get("association_ref"),
                "receipt": restored_link.get("receipt"),
                "event_ids": restored_link.get("event_ids", []),
            })
        receipt = self._receipt(request_id)
        adoption_receipt = self._receipt(request_id + ":adoption")
        observed = self._owner_reader.get_record(target_ref)
        tasks = list(observed.payload.get("tasks", ())) if observed is not None else []
        event_ids = self._events_for(receipt) + [item for item in self._events_for(adoption_receipt) if item not in self._events_for(receipt)]
        for item in restored_documents + restored_links:
            for event_id in item.get("event_ids", ()):
                if event_id not in event_ids:
                    event_ids.append(event_id)
        content_provenance = {
            "documents": len(snapshot.get("documents", ())),
            "document_links": len(snapshot.get("document_links", ())),
            "destination_content_identity_created": bool(restored_documents),
            "restored_documents": restored_documents,
            "restored_document_links": restored_links,
            "source_records_retained_in_adoption_metadata": True,
        }
        # Persist the result manifest through the public ProjectSheet port so
        # exact retries can return the original child receipts/event IDs even
        # after a later admission or edit has advanced the live project.
        saved_result = {
            "project_ref": _json_value(target_ref),
            "source_ref": _json_value(snapshot.get("source_ref")),
            "snapshot_digest": computed_digest,
            "adoption": _json_value(adopted),
            "receipt": _receipt_dict(receipt),
            "adoption_receipt": _receipt_dict(adoption_receipt),
            "task_refs": _json_value(tasks),
            "content_provenance": content_provenance,
            "dispatch": False,
            "execution": False,
            "manager_launch": False,
            "budget_reserved": False,
            "event_ids": event_ids,
        }
        try:
            self.sheet_port.apply(
                target_ref,
                {"metadata": {"otto_transfer_result": saved_result}},
                logical_request_key=request_id + ":result",
                actor=actor_value,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project.import"}, "replayed": False, "event_ids": []}
            raise
        observed = self._owner_reader.get_record(target_ref)
        return {
            "outcome": "imported",
            "project_ref": _json_value(getattr(observed, "ref", target_ref)),
            "source_ref": _json_value(snapshot.get("source_ref")),
            "snapshot_digest": computed_digest,
            "record": None if observed is None else _record_dict(observed),
            "adoption": _json_value(adopted),
            "receipt": _receipt_dict(receipt),
            "adoption_receipt": _receipt_dict(adoption_receipt),
            "task_refs": _json_value(tasks),
            "content_provenance": content_provenance,
            "dispatch": False,
            "execution": False,
            "manager_launch": False,
            "budget_reserved": False,
            "replayed": False,
            "event_ids": event_ids + [event_id for event_id in self._events_for(self._receipt(request_id + ":result")) if event_id not in event_ids],
        }

    def _fence_assignment(self, payload: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        """Validate the current generation before a manager handoff.

        Herzchen's assignment owner performs the generation check.  The finite
        endpoint returns the typed current assignment and never exposes the
        Store or a dispatch callback to the consumer.
        """

        if self.assignments_port is None:
            return self._unsupported("work.responsibility.fence", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        try:
            assignment_ref = self._record_ref(payload["manager_assignment_ref"])
            generation = int(payload["expected_generation"])
            assignment = self.assignments_port.fence(assignment_ref, generation)
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "stale_assignment_fence", "message": str(exc), "operation": "work.responsibility.fence"}, "replayed": False, "event_ids": [], "dispatch": False}
        return {"outcome": "fenced", "manager_assignment_ref": _json_value(getattr(assignment, "ref", assignment_ref)), "assignment": self._assignment_dict(assignment), "expected_generation": generation, "dispatch": False, "execution": False, "request_id": request_id, "event_ids": []}

    def _dispatch_assignment(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Attempt a typed dispatch through the public assignment command port.

        The generation fence is evaluated by Herzchen after a consumer reopens
        the owner store.  This endpoint deliberately returns no dispatch or
        execution side effect when an old owner presents a stale generation.
        """

        if self.assignments_port is None:
            return self._unsupported("work.responsibility.dispatch", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        try:
            assignment_ref = self._record_ref(payload["manager_assignment_ref"])
            generation = int(payload["expected_generation"])
            input_refs = tuple(self._record_ref(item) for item in payload.get("input_refs", ()))
            dispatch = self.assignments_port.dispatch(
                assignment_ref,
                input_refs=input_refs,
                action=payload.get("action"),
                expected_generation=generation,
                logical_request_key=request_id,
                actor=self._actor(actor),
            )
        except Exception as exc:
            error_name = type(exc).__name__
            code = "stale_assignment_dispatch" if error_name in {"StaleAssignmentError", "WorkNotFoundError"} else "assignment_dispatch_rejected"
            return {"outcome": "error", "error": {"code": code, "message": str(exc), "operation": "work.responsibility.dispatch"}, "replayed": False, "event_ids": [], "dispatch": False, "execution": False}
        receipt = self._receipt(request_id)
        return {"outcome": "dispatched", "dispatch": _json_value(dispatch), "receipt": _receipt_dict(receipt), "replayed": False, "event_ids": self._events_for(receipt), "execution": False}

    def _create_and_open(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if _orchestration_for(self) is not None:
            atomic_payload = dict(payload)
            atomic_payload["open"] = False
            if isinstance(payload.get("template"), Mapping):
                created = self._create_orchestrated_template(atomic_payload, request_id=request_id, actor=actor)
            else:
                created = self._create_orchestrated_project(atomic_payload, request_id=request_id, actor=actor)
            if created.get("outcome") == "error":
                created = dict(created)
                created["open"] = {"status": "not_requested", "recovery_pending": False, "recovery_status": "not_requested"}
                return created
            opened = self._open_existing(
                {"project_ref": created["project_ref"]},
                request_id=request_id + ":open",
                actor=actor,
            )
            result = dict(created)
            result["open"] = opened.get("opened", {"status": opened.get("outcome", "unknown")})
            result["outcome"] = created.get("outcome", "created")
            result["replayed"] = bool(created.get("replayed")) and bool(opened.get("replayed"))
            event_ids = list(created.get("event_ids", ()))
            for event_id in opened.get("event_ids", ()):
                if event_id not in event_ids:
                    event_ids.append(event_id)
            result["event_ids"] = event_ids
            return result
        if self.create_open_port is None:
            result = self._unsupported(
                "work.pending.create",
                request_id=request_id,
                code="canonical_create_and_open_finite_endpoint_unavailable",
                message=(
                    "the trusted owner create-and-open bridge was not injected; "
                    "sequential consumer create then open is forbidden"
                ),
            )
            result.update({
                "open": {"status": "unsupported", "recovery_pending": False, "recovery_status": "not_requested"},
                "executable": False,
            })
            return result

        edit = payload.get("edit", {})
        before = self._owner_reader.get_receipt(request_id)
        selected_resource = payload.get("template") if isinstance(payload.get("template"), Mapping) else None
        selected_parameters = payload.get("template_parameters", {})
        try:
            opened = self.create_open_port.create_pending_and_open(
                actor=self._actor(actor),
                request_id=request_id,
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                metadata=self._metadata(payload, request_id, payload.get("template", "blank")),
                template_resource=selected_resource,
                template_parameters=selected_parameters,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {
                    "outcome": "error",
                    "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.create"},
                    "replayed": False,
                    "event_ids": [],
                }
            if selected_resource is not None and type(exc).__name__ in {
                "TemplateError", "TemplateValidationError", "TemplateParameterError",
                "TemplateReferenceError", "SheetError", "ValueError", "TypeError",
            }:
                result = dict(self._template_error(exc))
                result["open"] = {
                    "status": "not_requested",
                    "recovery_pending": False,
                    "recovery_status": "not_requested",
                }
                return result
            raise

        status = opened.get("status", "unknown")
        project_ref = opened.get("project_ref")
        if status in {"occupied", "actor_occupied"}:
            return {
                "outcome": "occupied",
                "project_ref": None,
                "receipt": None,
                "project_receipt": None,
                "replayed": False,
                "event_ids": [],
                "executable": False,
                "open": _json_value(opened),
            }

        receipt_keys = (
            request_id + ":actor",
            request_id,
            request_id + ":project",
            request_id + ":project-created",
            request_id + ":template",
            request_id + ":materialized",
            request_id + ":materialize-failure",
            request_id + ":materialize-failure:actor",
        )
        event_ids = {
            event_id
            for key in receipt_keys
            for event_id in ((_receipt_dict(self._owner_reader.get_receipt(key)) or {}).get("event_ids", []))
        }
        record = None
        if project_ref is not None:
            record = self._owner_reader.get_record(self._record_ref(project_ref))
        template = opened.get("template")
        task_refs = opened.get("task_refs", [])
        task_records = []
        if isinstance(task_refs, (list, tuple)):
            seed_tasks = []
            if isinstance(selected_resource, Mapping):
                seed = selected_resource.get("seed", {})
                if isinstance(seed, Mapping):
                    raw_tasks = seed.get("tasks", seed.get("task_bundle", ()))
                    if isinstance(raw_tasks, (list, tuple)):
                        seed_tasks = list(raw_tasks)
            for index, task_ref in enumerate(task_refs):
                task_record = self._owner_reader.get_record(self._record_ref(task_ref))
                raw = seed_tasks[index] if index < len(seed_tasks) and isinstance(seed_tasks[index], Mapping) else {}
                task_records.append({
                    "local_id": str(raw.get("local_id", raw.get("id", raw.get("key", "task-" + str(index))))),
                    "ref": _json_value(task_ref),
                    "record": None if task_record is None else _record_dict(task_record),
                })
        return {
            "outcome": "replayed" if before is not None else ("created" if status == "opened" else status),
            "project_ref": _json_value(project_ref),
            "record": None if record is None else _record_dict(record),
            "receipt": _receipt_dict(self._owner_reader.get_receipt(request_id)),
            "project_receipt": _receipt_dict(self._owner_reader.get_receipt(request_id + ":project")),
            "template_receipt": _receipt_dict(opened.get("template_receipt")),
            "template": _json_value(template),
            "template_ref": None if template is None else _json_value(getattr(template, "ref", None)),
            "template_revision": None if template is None else getattr(template, "revision", None),
            "tasks": task_records,
            "task_refs": [_json_value(item["ref"]) for item in task_records],
            "replayed": before is not None,
            "event_ids": [
                event.event_id
                for event in self._owner_reader.list_events()
                if getattr(event, "event_id", None) in event_ids
            ],
            "executable": False,
            "activation": False,
            "dispatch": False,
            "manager_launch": False,
            "budget_reserved": False,
            "session_task_created": False,
            "execution": False,
            "open": _json_value(opened),
        }

    @staticmethod
    def _typed_template(value: Mapping[str, Any], parameters: Optional[Mapping[str, Any]] = None) -> Any:
        """Construct and validate the declared WorkTemplate before any write."""

        from herzchen.packs.templates import WorkTemplate, render_template, validate_template

        if not isinstance(value, Mapping):
            raise ValueError("template must be a JSON resource object")
        template_id = value.get("id")
        revision = value.get("revision", value.get("version"))
        if "revision" in value and "version" in value and value["revision"] != value["version"]:
            raise ValueError("template revision and version must agree")
        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError("template.id must be non-blank text")
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("template.revision or template.version must be non-blank text")
        parameter_schema = value.get("parameters")
        seed = value.get("seed")
        if not isinstance(parameter_schema, Mapping):
            raise ValueError("template.parameters must be an object")
        if not isinstance(seed, Mapping):
            raise ValueError("template.seed must be an object")
        template = validate_template(WorkTemplate(template_id, revision, dict(parameter_schema), dict(seed)))
        # Render once before the canonical project create so malformed seed
        # markers or missing declared defaults cannot leave a project behind.
        render_template(template, parameters)
        return template

    @staticmethod
    def _template_error(exc: Exception) -> Mapping[str, Any]:
        return {
            "outcome": "error",
            "error": {"code": "invalid_template_resource", "message": str(exc), "operation": "work.project-sheet.instantiate-template"},
            "replayed": False,
            "event_ids": [],
            "executable": False,
        }

    def _create_from_template(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.sheet_port is None:
            return self._unsupported("work.pending.create", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet template command port was not injected")
        try:
            template = self._typed_template(payload["template"], payload.get("template_parameters"))
        except Exception as exc:
            return self._template_error(exc)
        prior = self._receipt(request_id)
        edit = payload.get("edit", {})
        try:
            project = self.port.create_pending_project(
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                logical_request_key=request_id + "-project",
                actor=self._actor(actor),
                creator=self._actor(actor),
                curator=self._actor(actor),
                metadata=self._metadata(payload, request_id, payload["template"]),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.create"}, "replayed": False, "event_ids": [], "executable": False}
            raise
        project_ref = getattr(project, "ref", None)
        try:
            batch = self.sheet_port.instantiate_new_template(
                template,
                payload.get("template_parameters"),
                project=project_ref,
                logical_request_key=request_id,
                actor=self._actor(actor),
            )
        except Exception as exc:
            if type(exc).__name__ in {"ReplayConflictError", "TemplateError", "TemplateValidationError", "UnknownTemplateError", "SheetError"}:
                if type(exc).__name__ == "ReplayConflictError":
                    return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project-sheet.instantiate-template"}, "replayed": False, "event_ids": [], "executable": False}
                return self._template_error(exc)
            raise
        batch_project = getattr(batch, "project", None)
        if project_ref is None:
            project_ref = getattr(batch_project, "ref", None)
        if project_ref is None and isinstance(batch, Mapping):
            project_ref = batch.get("project_ref")
        fresh = None if project_ref is None else self._owner_reader.get_record(project_ref)
        returned_project_ref = getattr(fresh, "ref", project_ref)
        mappings = getattr(batch, "mappings", {})
        if not isinstance(mappings, Mapping) and isinstance(batch, Mapping):
            mappings = batch.get("mappings", {})
        task_records = []
        if isinstance(mappings, Mapping):
            for local_id, task_ref in mappings.items():
                record = self._owner_reader.get_record(task_ref)
                task_records.append({
                    "local_id": str(local_id),
                    "ref": _json_value(task_ref),
                    "record": None if record is None else _record_dict(record),
                })
        receipt = getattr(batch, "receipt", None)
        if receipt is None and isinstance(batch, Mapping):
            receipt = batch.get("receipt")
        receipt = receipt or self._receipt(request_id)
        project_receipt = self._owner_reader.get_receipt(request_id + "-project")
        event_ids = self._events_for(receipt) + [event_id for event_id in self._events_for(project_receipt) if event_id not in self._events_for(receipt)]
        return {
            "outcome": "replayed" if prior is not None else "created",
            "project_ref": _json_value(returned_project_ref),
            "record": None if fresh is None else _record_dict(fresh),
            "template": _json_value(template),
            "template_ref": _json_value(template.ref),
            "template_revision": template.revision,
            "tasks": task_records,
            "task_refs": [_json_value(item["ref"]) for item in task_records],
            "receipt": _receipt_dict(receipt),
            "project_receipt": _receipt_dict(project_receipt),
            "replayed": prior is not None,
            "event_ids": event_ids,
            "executable": False,
            "activation": False,
            "dispatch": False,
            "budget_reserved": False,
            "task_created": bool(task_records),
            "session_created": False,
        }

    @staticmethod
    def _open_dict(result: Any) -> dict[str, Any]:
        handle = getattr(result, "handle", None)
        return {
            "status": getattr(result, "status", "unknown"),
            "scope": _json_value(getattr(result, "scope", None)),
            "project_ref": _json_value(getattr(result, "project_ref", None)),
            "session_id": getattr(handle, "session_id", None),
            "target_kind": getattr(handle, "target_kind", None),
            "base_revision": getattr(handle, "base_revision", None),
            "error": getattr(result, "error", None),
            "recovery_pending": bool(getattr(result, "recovery_pending", False)),
            "recovery_status": "pending" if getattr(result, "recovery_pending", False) else "not_requested",
        }

    def _open_existing(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.create_open_port is not None:
            opened = self._project_authoring("work.project.checkout", payload, request_id=request_id, actor=actor)
            return {**opened, "opened": {**opened, "status": opened["outcome"]},
                    "replayed": opened["outcome"] == "replayed"}
        if self.authoring_port is None:
            return self._unsupported("work.pending.open", request_id=request_id, code="canonical_authoring_port_unavailable", message="accepted AuthoringSessionService command port was not injected")
        actor_value = self._actor(actor)
        ref = self._record_ref(payload["project_ref"])
        before = self._receipt(request_id)
        try:
            result = self.authoring_port.open(ref, actor_value, request_id=request_id, target_kind="project", base_revision=getattr(ref, "revision", None), purpose="otto", activity="editing", pending=True)
        except Exception as exc:
            if type(exc).__name__ in {"OccupiedError", "ActorOccupiedError"}:
                return self._receipt_result(request_id, outcome="occupied", project_ref=_json_value(ref), opened={"status": "occupied", "error": str(exc)})
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "authoring.open"}, "replayed": False, "event_ids": []}
            raise
        return self._receipt_result(request_id, outcome="replayed" if before is not None else getattr(result, "status", "opened"), project_ref=_json_value(ref), opened=self._open_dict(result), replayed=before is not None)

    def _project_folder(self, operation, payload, *, request_id, actor):
        if self.create_open_port is None:
            return self._unsupported(operation, request_id=request_id, code="project_authoring_unavailable")
        arguments = {**dict(payload), "actor": self._actor(actor), "request_id": request_id}
        methods = {"work.project.folder-import": "import_project_folder",
                   "work.project.folder-export": "export_project_folder",
                   "work.project.folder-check-in": "finish_project_folder",
                   "work.project.folder-release": "release_project_folder"}
        try:
            return _json_value(getattr(self.create_open_port, methods[operation])(**arguments))
        except Exception as exc:
            code = type(exc).__name__
            parent = self._receipt(request_id + ":project") if operation == "work.project.folder-import" else None
            if parent is not None and code not in {"ReplayConflictError", "VersionConflictError"}:
                return {"outcome": "partial", "atomic": False, "project_ref": _json_value(parent.result_ref),
                    "committed": [_receipt_dict(parent)], "pending": list(payload.get("files", {})),
                    "error": {"code": code, "message": str(exc)},
                    "recovery": "Inspect retained receipts and resume the exact input and request key.",
                    "execution": False, "dispatch": False}
            return {"outcome": "conflict" if code in {"ReplayConflictError", "VersionConflictError"} else "rejected",
                    "error": {"code": code, "message": str(exc)}, "execution": False, "dispatch": False}

    def _project_authoring(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.create_open_port is None:
            return self._unsupported(operation, request_id=request_id, code="project_authoring_unavailable")
        arguments = {"project_ref": payload["project_ref"], "actor": self._actor(actor), "request_id": request_id}
        try:
            if operation == "work.project.checkout":
                return _json_value(self.create_open_port.open_project_sheet(**arguments))
            return _json_value(self.create_open_port.finish_project_sheet(**arguments,
                session_id=payload["session_id"], project_json=payload["project_json"]))
        except Exception as exc:
            if type(exc).__name__ in {"ReplayConflictError", "VersionConflictError"}:
                return {"outcome": "conflict", "error": {"code": "replay_conflict" if type(exc).__name__ == "ReplayConflictError" else "stale_base", "message": str(exc)},
                        "execution": False, "dispatch": False}
            raise

    def _attention(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        observation = {"kind": "revisit" if operation.endswith("revisit") else "prerequisite-satisfied", "payload": dict(payload), "dispatch": False}
        prior = self._receipt(request_id)
        try:
            result_ref = self.port.set_readiness(self._record_ref(payload["project_ref"]), observation, logical_request_key=request_id, actor=self._actor(actor))
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": operation}, "replayed": False, "event_ids": []}
            raise
        return self._receipt_result(request_id, outcome="attention-created", project_ref=_json_value(self._record_ref(payload["project_ref"])), attention_ref=_json_value(result_ref), readiness={"dispatch": False}, executable=False, replayed=prior is not None)

    def _admit(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.sheet_port is None:
            return self._unsupported("work.pending.admission", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet command port was not injected")
        frame = dict(payload["frame"])
        sheet = {
            "outcome": frame["outcome"],
            "manager_action": payload["choice"],
            "resources": {key: frame[key] for key in ("recipient", "route", "authority")},
        }
        prior = self._receipt(request_id)
        try:
            result = self.sheet_port.apply(self._record_ref(payload["project_ref"]), sheet, logical_request_key=request_id, actor=self._actor(actor), next_action=payload["choice"])
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.admission"}, "replayed": False, "event_ids": []}
            raise
        return self._receipt_result(request_id, outcome="admitted", project_ref=_json_value(getattr(getattr(result, "project", None), "ref", None)), admission={"choice": payload["choice"], "frame": frame}, executable=False, replayed=prior is not None)

    def _assign_roles(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.assignments_port is None:
            return self._unsupported("work.responsibility.assign", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        actor_value = self._actor(actor)
        ref = self._record_ref(payload["project_ref"])
        roles = payload["roles"]
        resources = roles.get("resources") or {}
        if resources.get("orchestrator") and not roles.get("orchestrator"):
            return {"outcome": "error", "error": {"code": "orphan_resource_attachment", "message": "orchestrator resources require an explicit orchestrator principal", "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": [], "executable": False}
        if resources.get("project_advisor") and not roles.get("project_advisor"):
            return {"outcome": "error", "error": {"code": "orphan_resource_attachment", "message": "project_advisor resources require an explicit project_advisor principal", "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": [], "executable": False}
        for slot, items in resources.items():
            for item in items:
                if item.get("responsibility_ref") != _json_value(ref):
                    return {"outcome": "error", "error": {"code": "invalid_resource_attachment", "message": "resource attachment scope does not match the assignment project", "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": [], "executable": False}
        try:
            role_resources = resolve_role_attachments(roles.get("resources"), self.content_port or self._owner_reader) if roles.get("resources") else {}
        except ResourceSyncError as exc:
            return {"outcome": "error", "error": {"code": "invalid_resource_attachment", "message": str(exc), "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": [], "executable": False}
        assignments: dict[str, Any] = {}
        parent_receipt = None
        executor_values = roles["executor"] if isinstance(roles["executor"], list) else [roles["executor"]]
        role_inputs = [("parent", [self._record_ref(roles["parent"])])]
        if roles.get("orchestrator") is not None:
            role_inputs.append(("orchestrator", [roles["orchestrator"]]))
        if roles.get("project_advisor") is not None:
            role_inputs.append(("project_advisor", [roles["project_advisor"]]))
        role_inputs.extend((("manager", [roles["manager"]]), ("executor", executor_values)))
        event_ids: list[str] = []
        for role, principals in role_inputs:
            for index, principal in enumerate(principals):
                key = self._key(request_id, role + (":" + str(index) if len(principals) > 1 else ""))
                prior = self._receipt(key)
                try:
                    pins = role_resource_pins(role_resources, role)
                    kwargs = {"role": role, "principal": principal, "manager": roles["manager"], "logical_request_key": key, "actor": actor_value}
                    if pins:
                        kwargs["pins"] = pins
                    assignment = self.assignments_port.assign(ref, **kwargs)
                except Exception as exc:
                    if type(exc).__name__ == "ReplayConflictError":
                        return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": []}
                    raise
                receipt = self._receipt(key)
                assignment_ref_value = _json_value(getattr(assignment, "ref", None))
                resource_slot = {
                    "orchestrator": "orchestrator",
                    "manager": "manager",
                    "project_advisor": "project_advisor",
                    "executor": "worker",
                }.get(role)
                effective_resources = [
                    dict(item, responsibility_ref=assignment_ref_value)
                    for item in role_resources.get(resource_slot, [])
                ] if resource_slot else []
                assignments[key] = {"ref": assignment_ref_value, "assignment_ref": assignment_ref_value, "role": role, "principal": _json_value(principal), "generation": getattr(assignment, "generation", None), "resources": effective_resources, "pins": _json_value(getattr(assignment, "pins", ())), "receipt": _receipt_dict(receipt), "replayed": prior is not None}
                event_ids.extend(self._events_for(receipt))
                if role == "parent":
                    parent_receipt = receipt
        manager_assignment_ref = next(
            (item["ref"] for item in assignments.values() if item["role"] == "manager"),
            None,
        )
        return {"outcome": "assigned", "project_ref": _json_value(ref), "roles": assignments, "manager_assignment_ref": manager_assignment_ref, "parent_receipt": _receipt_dict(parent_receipt), "event_ids": event_ids, "replayed": all(item["replayed"] for item in assignments.values()) if assignments else False, "executable": False}

    @staticmethod
    def _active_assignment(assignment: Any) -> bool:
        status = getattr(assignment, "status", None)
        status = getattr(status, "value", status)
        return str(status).lower() in {
            "active", "assigned", "queued", "running", "in-flight", "reassigned",
        }

    @staticmethod
    def _same_ref_identity(left: Any, right: Any) -> bool:
        left, right = _json_value(left), _json_value(right)
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and all(left.get(key) == right.get(key) for key in ("authority", "kind", "id"))
        )

    def _project_assignment_values(self, project_ref: Any) -> tuple[Any, list[Any]]:
        """Read current project assignments through the public Sheet projection."""

        view = self.sheet_port.export(project_ref)
        value = _json_value(view.to_dict() if hasattr(view, "to_dict") else view)
        project = value.get("project") if isinstance(value, Mapping) else None
        current_ref = project.get("ref") if isinstance(project, Mapping) else None
        if not isinstance(current_ref, Mapping):
            raise ValueError("project Sheet projection has no current project ref")
        observed = project.get("observed") if isinstance(project, Mapping) else None
        rows = observed.get("assignments") if isinstance(observed, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("project Sheet projection has no assignment list")
        result = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            ref = row.get("ref") if isinstance(row, Mapping) else None
            if not isinstance(ref, Mapping):
                continue
            identity = tuple(str(ref.get(key, "")) for key in ("authority", "kind", "id"))
            if not all(identity) or identity in seen:
                continue
            seen.add(identity)
            assignment = self.assignments_port.get(self._record_ref(ref))
            if self._same_ref_identity(getattr(assignment, "scope", None), project_ref):
                result.append(assignment)
        return self._record_ref(current_ref), result

    def _project_advisor_pair(
        self, payload: Mapping[str, Any], *, request_id: str, actor: str,
    ) -> Mapping[str, Any]:
        """Read or create the one advisor assignment for a current manager.

        The Project Sheet remains the roster read and ResponsibilityAssignments
        remains the sole writer.  This operation creates no conversation,
        schedule, allowance, delivery, or pilot-specific state.
        """

        operation = "work.project-advisor.pair"
        if self.sheet_port is None or self.assignments_port is None:
            return self._unsupported(
                operation, request_id=request_id,
                code="canonical_project_advisor_ports_unavailable",
                message="accepted ProjectSheet and ResponsibilityAssignments ports are required",
            )
        try:
            project_ref = self._record_ref(payload["project_ref"])
            manager_ref = self._record_ref(payload["manager_assignment_ref"])
        except (KeyError, TypeError, ValueError) as exc:
            return {"outcome": "error", "error": {"code": "invalid_pairing_ref", "message": str(exc), "operation": operation}, "event_ids": []}
        expected_generation = payload.get("manager_generation")
        if (isinstance(expected_generation, bool) or not isinstance(expected_generation, int)
                or expected_generation < 1):
            return {"outcome": "error", "error": {"code": "invalid_manager_generation", "message": "manager_generation must be a positive integer", "operation": operation}, "event_ids": []}
        principal = payload.get("advisor_principal")
        if principal is not None and (not isinstance(principal, str) or not principal.strip()):
            return {"outcome": "error", "error": {"code": "invalid_advisor_principal", "message": "advisor_principal must be non-blank text", "operation": operation}, "event_ids": []}
        pins = payload.get("pins", ())
        if not isinstance(pins, (list, tuple)):
            return {"outcome": "error", "error": {"code": "invalid_advisor_pins", "message": "pins must be an array", "operation": operation}, "event_ids": []}
        if pins and principal is None:
            return {"outcome": "error", "error": {"code": "invalid_advisor_pins", "message": "pins require advisor_principal", "operation": operation}, "event_ids": []}
        try:
            pin_refs = tuple(self._record_ref(value) for value in pins)
            current_project_ref, assignments = self._project_assignment_values(project_ref)
            if _json_value(current_project_ref) != _json_value(project_ref):
                raise ValueError("project reference is stale")
            active = [value for value in assignments if self._active_assignment(value)]
            managers = [value for value in active if getattr(value, "role", None) == "manager"]
            advisors = [value for value in active if getattr(value, "role", None) == "project_advisor"]
            if len(managers) != 1:
                raise ValueError("project must have exactly one active manager assignment")
            manager = managers[0]
            if (_json_value(getattr(manager, "ref", None)) != _json_value(manager_ref)
                    or getattr(manager, "generation", None) != expected_generation):
                raise ValueError("manager assignment or generation is stale")
            manager_principal = getattr(manager, "principal", None)
            pair_key = (
                "otto-project-advisor-pair:" + current_project_ref.id + ":"
                + manager.ref.id + ":g" + str(expected_generation)
            )
            prior_receipt = self._receipt(pair_key)
            created = False
            if len(advisors) > 1:
                raise ValueError("project has more than one active project advisor assignment")
            if not advisors:
                if principal is None:
                    return {
                        "outcome": "missing", "schema": "otto.project-advisor-owner-pair.v1",
                        "project_ref": _json_value(project_ref),
                        "manager": self._assignment_dict(manager), "advisor": None,
                        "read_only": True, "dispatch": False, "execution": False,
                        "event_ids": [], "replayed": False,
                    }
                advisor = self.assignments_port.assign(
                    current_project_ref, role="project_advisor", principal=principal.strip(),
                    manager=manager_principal, pins=pin_refs,
                    logical_request_key=pair_key,
                    actor=self._actor(actor),
                )
                created = prior_receipt is None
            else:
                advisor = advisors[0]
                if principal is not None and getattr(advisor, "principal", None) != principal.strip():
                    raise ValueError("current project advisor principal differs from the request")
                if principal is not None and tuple(getattr(advisor, "pins", ())) != pin_refs:
                    raise ValueError("current project advisor pins differ from the request")
            advisor_payload = _json_value(getattr(advisor, "payload", {}))
            linked_manager = advisor_payload.get("manager") if isinstance(advisor_payload, Mapping) else None
            if isinstance(linked_manager, Mapping):
                linked_manager = linked_manager.get("id") or linked_manager.get("principal")
            else:
                linked_manager = getattr(linked_manager, "id", linked_manager)
            if linked_manager not in {manager_principal, getattr(manager_ref, "id", None)}:
                raise ValueError("project advisor is not linked to the current manager")
            receipt = self._receipt(pair_key)
            replayed = prior_receipt is not None or (receipt is not None and not created)
            return {
                "outcome": "created" if created else "read",
                "schema": "otto.project-advisor-owner-pair.v1",
                "project_ref": _json_value(current_project_ref),
                "manager": self._assignment_dict(manager),
                "advisor": self._assignment_dict(advisor),
                "pairing_request_key": pair_key,
                "receipt": _receipt_dict(receipt),
                "event_ids": self._events_for(receipt),
                "replayed": replayed, "dispatch": False, "execution": False,
            }
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "project_advisor_pairing_rejected", "message": str(exc), "operation": operation}, "event_ids": []}

    def _complete_task(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Forward direct and sheet completion through one owner guard."""

        if self.sheet_port is None and self.assignments_port is None:
            return self._unsupported(
                "work.task.complete", request_id=request_id,
                code="canonical_completion_port_unavailable",
                message="accepted ProjectSheet/ResponsibilityAssignments completion port was not injected",
            )
        required = ("project_ref", "task_ref", "assignment_ref", "expected_generation", "expected_project_revision", "expected_task_revision", "disposition", "evidence_refs", "evidence_hashes", "gate_refs")
        missing = [field for field in required if field not in payload]
        if missing:
            return {"outcome": "held", "status": "unknown", "error": {"code": "completion_prerequisite_missing", "message": "completion requires " + ", ".join(missing), "operation": "work.task.complete"}, "replayed": False, "event_ids": [], "executable": False}
        try:
            project_ref = self._record_ref(payload["project_ref"])
            task_ref = self._record_ref(payload["task_ref"])
            assignment_ref = self._record_ref(payload["assignment_ref"])
            evidence_refs = [self._record_ref(value) for value in payload["evidence_refs"]]
            gate_refs = [self._record_ref(value) for value in payload["gate_refs"]]
            kwargs = {
                "project": project_ref,
                "assignment": assignment_ref,
                "expected_generation": payload["expected_generation"],
                "expected_project_revision": payload["expected_project_revision"],
                "expected_task_revision": payload["expected_task_revision"],
                "disposition": payload["disposition"],
                "evidence_refs": evidence_refs,
                "evidence_hashes": payload["evidence_hashes"],
                "gate_refs": gate_refs,
                "candidate_ref": self._record_ref(payload["candidate_ref"]) if payload.get("candidate_ref") is not None else None,
                "result_ref": self._record_ref(payload["result_ref"]) if payload.get("result_ref") is not None else None,
                "attempt_ref": self._record_ref(payload["attempt_ref"]) if payload.get("attempt_ref") is not None else None,
                "source_set_digest": payload.get("source_set_digest"),
                "logical_request_key": request_id,
                "actor": self._actor(actor),
            }
            # The ProjectSheet endpoint is the canonical governed-task surface;
            # its implementation delegates to the same owner assignment guard.
            port = self.sheet_port if self.sheet_port is not None else self.assignments_port
            result = port.complete_managed_task(task_ref, **kwargs) if self.sheet_port is not None else port.complete(task_ref, **kwargs)
        except Exception as exc:
            name = type(exc).__name__
            if name in {"ReplayConflictError", "StaleAssignmentError", "WorkNotFoundError", "VersionConflictError"}:
                code = "replay_conflict" if name == "ReplayConflictError" else "stale_completion" if name in {"StaleAssignmentError", "VersionConflictError"} else "completion_target_not_found"
                return {"outcome": "error", "error": {"code": code, "message": str(exc), "operation": "work.task.complete"}, "replayed": False, "event_ids": [], "executable": False}
            if name in {"WorkValidationError", "SheetError", "TypeError", "ValueError"}:
                return {"outcome": "held", "status": "unknown", "error": {"code": "completion_not_eligible", "message": str(exc), "operation": "work.task.complete"}, "replayed": False, "event_ids": [], "executable": False}
            raise
        value = _json_value(result)
        if not isinstance(value, Mapping):
            return {"outcome": "error", "error": {"code": "malformed_completion_result", "message": "owner completion returned a non-object", "operation": "work.task.complete"}, "replayed": False, "event_ids": []}
        return dict(value)

    @staticmethod
    def _assignment_dict(assignment: Any) -> dict[str, Any]:
        """Return only the declared assignment value, including durable history."""

        payload = _json_value(getattr(assignment, "payload", {}))
        return {
            "ref": _json_value(getattr(assignment, "ref", None)),
            "assignment_ref": _json_value(getattr(assignment, "assignment_ref", getattr(assignment, "ref", None))),
            "scope": _json_value(getattr(assignment, "scope", None)),
            "role": getattr(assignment, "role", None),
            "principal": _json_value(getattr(assignment, "principal", None)),
            # The accepted reassignment operation changes the typed principal;
            # retain the raw payload as well because its manager attribution is
            # historical metadata owned by Herzchen.
            "manager": _json_value(getattr(assignment, "principal", payload.get("manager") if isinstance(payload, Mapping) else None)),
            "stored_manager": payload.get("manager") if isinstance(payload, Mapping) else None,
            "generation": getattr(assignment, "generation", None),
            "status": _json_value(getattr(assignment, "status", None)),
            "pins": _json_value(getattr(assignment, "pins", payload.get("pins", ()) if isinstance(payload, Mapping) else ())),
            "history": _json_value(getattr(assignment, "history", ())),
            "payload": payload,
        }

    @staticmethod
    def _handoff_context_token(context: Mapping[str, Any]) -> str:
        """Encode typed context in the accepted assignment history reason field."""

        encoded = base64.urlsafe_b64encode(
            json.dumps(dict(context), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return "otto-handoff-context-" + encoded

    @staticmethod
    def _handoff_context_from_assignment(assignment: Any, *, request_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        history = getattr(assignment, "history", ())
        if not history:
            return None
        prefix = "otto-handoff-context-"
        fallback = None
        for item in reversed(history):
            reason = item.get("reason") if isinstance(item, Mapping) else None
            if not isinstance(reason, str) or not reason.startswith(prefix):
                continue
            value = reason[len(prefix):]
            try:
                padded = value + "=" * (-len(value) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if not isinstance(decoded, Mapping):
                continue
            decoded_context = dict(decoded)
            fallback = fallback or decoded_context
            if request_id is None or decoded_context.get("request_id") == request_id:
                return decoded_context
        # Contexts written by the accepted pre-v2 implementation have no
        # request_id.  They are still replayable when they are the only
        # durable handoff context on the assignment.
        return fallback

    def _handoff(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.assignments_port is None:
            return self._unsupported("work.responsibility.handoff", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        assignment_value = payload.get("manager_assignment_ref")
        if not isinstance(assignment_value, Mapping):
            return {
                "outcome": "error",
                "error": {"code": "manager_assignment_ref_required", "message": "real handoff requires the typed manager assignment reference returned by assign_roles", "operation": "work.responsibility.handoff"},
                "replayed": False,
                "event_ids": [],
                "executable": False,
            }
        from herzchen.contracts import ResourceRef

        project_ref = self._record_ref(payload["project_ref"])
        try:
            assignment_ref = ResourceRef.from_dict(assignment_value)
        except (TypeError, ValueError) as exc:
            return {"outcome": "error", "error": {"code": "malformed_manager_assignment_ref", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        if assignment_ref.kind != "wrk.assignment":
            return {"outcome": "error", "error": {"code": "invalid_manager_assignment_ref", "message": "manager_assignment_ref must name a wrk.assignment", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        if assignment_ref.authority != self.binding.authority:
            return {"outcome": "error", "error": {"code": "foreign_manager_assignment_ref", "message": "manager assignment belongs to another authority", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}

        # The bounded lookup is the accepted public assignment API.  There is
        # no manager-name inference, scope scan, private SQL, or side mirror.
        try:
            current = self.assignments_port.get(assignment_ref)
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "unknown_manager_assignment_target", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        if getattr(current, "role", None) != "manager" or not self._same_identity(getattr(current, "scope", None), project_ref):
            return {"outcome": "error", "error": {"code": "invalid_manager_assignment_target", "message": "assignment is not the current manager assignment for this project", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        from_manager = payload["from_manager"]
        current_principal = getattr(current, "principal", None)
        current_status = getattr(current, "status", None)
        current_status = getattr(current_status, "value", current_status)
        if current_status not in {"queued", "reassigned"}:
            return {"outcome": "error", "error": {"code": "invalid_manager_assignment_status", "message": "manager assignment is not available for handoff", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        prior = self._receipt(request_id)
        stored_context = self._handoff_context_from_assignment(current, request_id=request_id) if prior is not None else None
        if prior is None and current_principal != from_manager:
            return {"outcome": "error", "error": {"code": "stale_manager_assignment", "message": "from_manager does not match the current assignment principal/manager", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}

        context = {
            "kind": "otto.safe-responsibility-handoff",
            "project_ref": _json_value(project_ref),
            "manager_assignment_ref": _json_value(assignment_ref),
            "from_manager": from_manager,
            "to_manager": payload["to_manager"],
            "evidence_refs": _json_value(payload["evidence_refs"]),
            "consumption_refs": _json_value(payload["consumption_refs"]),
            "parent_obligation": _json_value(payload["parent_obligation"]),
            "from_generation": getattr(current, "generation", None),
            "request_id": request_id,
        }
        if prior is not None:
            if not isinstance(stored_context, Mapping):
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": "prior handoff receipt has no durable typed context", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            for key in ("kind", "project_ref", "manager_assignment_ref", "from_manager", "to_manager", "evidence_refs", "consumption_refs", "parent_obligation"):
                if stored_context.get(key) != context.get(key):
                    return {"outcome": "error", "error": {"code": "replay_conflict", "message": "same handoff request key was reused with changed input", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            latest_context = self._handoff_context_from_assignment(current)
            # A retry of the latest handoff must still observe its current
            # replacement.  An older exact request may be retried after a
            # later valid handoff: its durable context is in assignment
            # history, and replaying Herzchen's original receipt must not
            # revert the newer principal.
            if current_principal != stored_context.get("to_manager") and stored_context == latest_context:
                return {"outcome": "error", "error": {"code": "stale_manager_assignment", "message": "durable handoff target no longer matches the original replacement", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            context = dict(stored_context)
        try:
            replacement = self.assignments_port.reassign(
                assignment_ref,
                principal=context["to_manager"],
                reason=self._handoff_context_token(context),
                expected_generation=context["from_generation"],
                logical_request_key=request_id,
                actor=self._actor(actor),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            if type(exc).__name__ in {"StaleAssignmentError", "WorkNotFoundError"}:
                return {"outcome": "error", "error": {"code": "stale_or_unknown_manager_assignment", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            raise
        receipt = self._receipt(request_id)
        observed_context = self._handoff_context_from_assignment(replacement) or context
        return {
            "outcome": "replayed" if prior is not None else "handed-off",
            "safe_handoff": True,
            "project_ref": _json_value(project_ref),
            "manager_assignment_ref": _json_value(getattr(replacement, "ref", assignment_ref)),
            "assignment": self._assignment_dict(replacement),
            "handoff": observed_context,
            "receipt": _receipt_dict(receipt),
            "replayed": prior is not None,
            "event_ids": self._events_for(receipt),
            "executable": False,
            "activation": False,
            "dispatch": False,
            "budget_reserved": False,
            "task_created": False,
            "session_created": False,
        }

    def _content_context(self, operation: str, target: Any, request_id: str, actor: Any, payload: Mapping[str, Any], schema_revision: str) -> Any:
        from herzchen.contracts import TransactionContext, canonical_request_digest

        context = TransactionContext(actor, request_id, "0" * 64)
        digest = canonical_request_digest(logical_request_key=request_id, operation=operation, schema_revision=schema_revision, target=target, actor=actor, payload=payload, context=context)
        return TransactionContext(actor, request_id, digest)

    def _create_document(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.content_port is None:
            return self._unsupported("work.pending.document.create", request_id=request_id, code="canonical_content_port_unavailable", message="accepted ContentCommandHandler command port was not injected")
        from herzchen.content import CONTENT_SCHEMA_REVISION, ContentDocument, ContentRevision
        from herzchen.contracts import ResourceRef, canonical_json

        actor_value = self._actor(actor)
        project_ref = self._record_ref(payload["project_ref"])
        doc_id = payload.get("document_id") or "document-" + sha256(request_id.encode()).hexdigest()[:28]
        document_ref = ResourceRef(self.binding.authority, "dat.content.document", doc_id)
        source_ref = self._record_ref(payload["source_ref"]) if payload.get("source_ref") is not None else None
        import_mode = payload.get("import_mode", "owned")
        writable = bool(payload.get("writable", True))
        document = ContentDocument(
            document_ref,
            payload.get("role", "supporting"),
            payload.get("visibility", "private"),
            payload.get("access_mode", "read"),
            actor,
            authoring_scope=project_ref,
            source_ref=source_ref,
            import_mode=import_mode,
            writable=writable,
        )
        revision = ContentRevision(document_ref, "rev-1", payload.get("content", {}), actor_value, initial=True)
        command_payload = {"document": document, "revision": revision}
        context = self._content_context("dat.content.document.create", document_ref, request_id, actor_value, command_payload, CONTENT_SCHEMA_REVISION)
        envelope = self.content_port.build_create_document(context, document, revision)
        public_args = None
        if self.content_command_guard is not None:
            raw = payload.get("content", "").encode("utf-8")
            public_args = {"project_ref":_json_value(project_ref), "actor":actor, "request_id":request_id,
                           "document_id":doc_id, "role":document.role, "visibility":document.visibility,
                           "access_mode":document.access_mode, "content_raw_sha256":sha256(raw).hexdigest(),
                           "content_utf8_bytes":len(raw), "content_canonical_string_sha256":sha256(canonical_json(payload["content"]).encode()).hexdigest()}
        receipt_before = self._receipt(request_id)
        guard = self.content_command_guard
        if guard is not None:
            guard.before_content(envelope, public_args)
            if receipt_before is not None:
                guard._halted = True
                raise ValueError("suffix_receipt_already_present")
        try:
            receipt_result = self.content_port.execute(envelope)
        except BaseException as exc:
            if guard is not None:
                guard.after_content(envelope, self._receipt(request_id), failed=True)
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.document.create"}, "replayed": False, "event_ids": []}
            raise
        receipt = self._receipt(request_id) if guard is not None else (self._receipt(request_id) or receipt_result)
        if guard is not None:
            guard.after_content(envelope, receipt)
        result = {"outcome": "replayed" if receipt_before is not None else "created", "document_ref": _json_value(document_ref), "project_ref": _json_value(project_ref), "record": _record_dict(self._owner_reader.get_record(document_ref)), "receipt": _receipt_dict(receipt), "replayed": receipt_before is not None, "event_ids": self._events_for(receipt)}
        if guard is not None:
            guard.content_formatted()
        return result

    def _link_document(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.content_port is None:
            return self._unsupported("work.pending.document.link", request_id=request_id, code="canonical_content_port_unavailable", message="accepted ContentCommandHandler command port was not injected")
        from herzchen.content import CONTENT_SCHEMA_REVISION, DocumentAssociation
        from herzchen.contracts import ReferenceBinding, ResourceRef

        actor_value = self._actor(actor)
        project_ref = self._record_ref(payload["project_ref"])
        document_ref = self._record_ref(payload["document_ref"])
        association = DocumentAssociation(project_ref, payload.get("namespace", "project.documents"), payload.get("key", "document"), ReferenceBinding(document_ref, "current"), payload.get("access_mode", "read"))
        target = ResourceRef(self.binding.authority, "document-association", association.identity)
        command_payload = {"association": association}
        context = self._content_context("dat.content.link", target, request_id, actor_value, command_payload, CONTENT_SCHEMA_REVISION)
        envelope = self.content_port.build_link(context, association)
        public_args = None
        if self.content_command_guard is not None:
            public_args = {"project_ref":_json_value(project_ref), "document_ref":_json_value(document_ref),
                           "actor":actor, "request_id":request_id, "namespace":association.namespace,
                           "key":association.key, "access_mode":association.access_mode}
        receipt_before = self._receipt(request_id)
        guard = self.content_command_guard
        if guard is not None:
            guard.before_content(envelope, public_args)
            if receipt_before is not None:
                guard._halted = True
                raise ValueError("suffix_receipt_already_present")
        try:
            receipt_result = self.content_port.execute(envelope)
        except BaseException as exc:
            if guard is not None:
                guard.after_content(envelope, self._receipt(request_id), failed=True)
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.document.link"}, "replayed": False, "event_ids": []}
            raise
        receipt = self._receipt(request_id) if guard is not None else (self._receipt(request_id) or receipt_result)
        if guard is not None:
            guard.after_content(envelope, receipt)
        result = {"outcome": "replayed" if receipt_before is not None else "linked", "project_ref": _json_value(project_ref), "document_ref": _json_value(document_ref), "association_ref": _json_value(target), "record": _record_dict(self._owner_reader.get_record(target)), "receipt": _receipt_dict(receipt), "replayed": receipt_before is not None, "event_ids": self._events_for(receipt)}
        if guard is not None:
            guard.content_formatted()
        return result

    def _unsupported(self, operation: str, *, request_id: Optional[str] = None, code: str = "canonical_operation_unavailable", message: str = "no accepted finite Herzchen endpoint is available for this Otto operation") -> dict[str, Any]:
        receipt = self._owner_reader.get_receipt(request_id) if request_id else None
        return {
            "outcome": "unavailable",
            "operation": operation,
            "error": {"code": code, "message": message},
            "receipt": _receipt_dict(receipt),
            "replayed": False,
            "event_ids": self._events_for(receipt),
        }

    def _pending_projects(self, parent_ref: Any = None) -> list[Any]:
        """Read pending projects through the sealed consumer reader.

        The consumer reader exposes event history and record lookup, but no
        generic query or SQL surface.  Reconstructing the finite project index
        from public work subjects keeps listing read-only and preserves the
        owner/consumer boundary.
        """

        from herzchen.contracts import ResourceRef

        latest: dict[tuple[str, str, str], ResourceRef] = {}
        for event in self._owner_reader.list_events():
            subject = getattr(event, "subject", None)
            if subject is None or getattr(subject, "kind", None) != "work.project":
                continue
            key = (subject.authority, subject.kind, subject.id)
            latest[key] = ResourceRef(subject.authority, subject.kind, subject.id)

        parent_identity = None
        if parent_ref is not None:
            parent = self._record_ref(parent_ref)
            parent_identity = (parent.authority, parent.kind, parent.id)

        records = []
        for ref in latest.values():
            record = self._owner_reader.get_record(ref)
            if record is None:
                continue
            payload = getattr(record, "payload", {}) or {}
            if payload.get("lifecycle") != "pending":
                continue
            if parent_identity is not None:
                value = payload.get("parent")
                if value is None:
                    continue
                parent_value = self._record_ref(value)
                if (parent_value.authority, parent_value.kind, parent_value.id) != parent_identity:
                    continue
            records.append(record)
        return sorted(records, key=lambda record: (getattr(record, "id", ""), getattr(record, "version", 0)))

    def _revise(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        from herzchen.contracts import ResourceRef

        edit = payload["edit"]
        fields = {key: value for key, value in edit.items() if key not in {"title", "outcome"}}
        actor_value = self._actor(actor)
        changes: dict[str, Any] = {
            "logical_request_key": request_id,
            "actor": actor_value,
            "fields": fields,
        }
        if "title" in edit:
            changes["title"] = edit["title"]
        if "outcome" in edit:
            changes["outcome"] = edit["outcome"]
        before = self._owner_reader.get_receipt(request_id)
        project_ref = ResourceRef.from_dict(payload["project_ref"])
        if project_ref.revision is None:
            return {"outcome": "conflict", "error": {"code": "stale_base", "message": "pending edit requires the current project revision"},
                    "replayed": False, "event_ids": []}
        try:
            record = self.port.revise(project_ref, base_revision=project_ref.revision, **changes)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.edit"}, "replayed": False, "event_ids": []}
            if type(exc).__name__ == "VersionConflictError":
                return {"outcome": "conflict", "error": {"code": "stale_base", "message": str(exc)}, "replayed": False, "event_ids": []}
            raise
        receipt = self._owner_reader.get_receipt(request_id)
        observed = self._owner_reader.get_record(record.ref)
        return {
            "outcome": "replayed" if before is not None else "edited",
            "project_ref": _json_value(record.ref),
            "record": _record_dict(observed),
            "receipt": _receipt_dict(receipt),
            "replayed": before is not None,
            "event_ids": self._events_for(receipt),
            "executable": False,
        }

    def _import_readback(self, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        """Read one staged import's definitions and receipt proofs within its grant.

        The project holds the source manifest. Caller refs and request keys are
        claims, never authority to enumerate criteria or arbitrary receipts.
        """
        from herzchen.contracts import ResourceRef

        denied = {"outcome": "denied", "read_only": True, "writes": 0,
                  "error": {"code": "import_readback_unavailable", "message": "import readback is unavailable"}}
        grant = self._read_grant(actor)
        if grant is None:
            return denied
        try:
            def ref(value: Any, kind: str) -> Any:
                value = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
                if value.authority != grant.principal.authority or value.kind != kind:
                    raise ValueError("foreign reference")
                return value

            def identity(value: Any) -> tuple[str, str, str]:
                return value.authority, value.kind, value.id

            def current(value: Any) -> Any:
                record = self._owner_reader.get_record(ResourceRef(value.authority, value.kind, value.id))
                if record is None or identity(record.ref) != identity(value):
                    raise ValueError("missing record")
                if value.revision is not None and record.ref.revision != value.revision:
                    raise ValueError("stale record")
                return record

            project = ref(payload["project_ref"], "work.project")
            if not grant.allows(project):
                return denied
            record = current(project)
            metadata = record.payload.get("metadata", {})
            request_id = payload["request_id"]
            if not isinstance(request_id, str) or not request_id.strip():
                return denied
            if metadata.get("otto_request", {}).get("logical_request_key") != request_id + ":project":
                return denied
            source = metadata["worker_source_projection"]
            if source["mapping_sha256"] != metadata["worker_source_mapping_sha256"]:
                return denied
            criteria, documents = source["criteria"], source["documents"]
            if not isinstance(criteria, (tuple, list)) or not 1 <= len(criteria) <= 100:
                return denied
            if not isinstance(documents, (tuple, list)) or not 1 <= len(documents) <= 500:
                return denied
            criterion_claims, document_claims = payload["criterion_refs"], payload["document_refs"]
            if (not isinstance(criterion_claims, Mapping) or not isinstance(document_claims, Mapping)
                    or set(criterion_claims) != {row["source_alias"] for row in criteria}
                    or set(document_claims) != {row["source_alias"] for row in documents}):
                return denied
            scope = ref(payload["scope_ref"], "assessment.scope")
            if scope.revision is None or scope.id != "worker-" + sha256(request_id.encode()).hexdigest()[:28]:
                return denied
            scope_record = current(scope)
            scope_payload = scope_record.payload
            if (identity(ref(scope_payload["parent_obligation_ref"], "work.project")) != identity(project)
                    or scope_payload.get("protocol") != "worker-source-freeze"
                    or scope_payload.get("policy", {}).get("source_mapping_sha256") != source["mapping_sha256"]):
                return denied
            members = scope_payload["criterion_refs"]
            if len(members) != len(criteria):
                return denied
            definitions = {}
            for row, member in zip(criteria, members):
                member = ref(member, "assessment.criterion")
                claimed = ref(criterion_claims[row["source_alias"]], "assessment.criterion")
                if member.revision is None or claimed != member:
                    return denied
                criterion = current(member)
                definition = _json_value(criterion.payload.get("definition", {}))
                if any(definition.get(field) != row[field] for field in (
                        "source_alias", "expected_behavior", "proof", "applicability")):
                    return denied
                definitions[row["source_alias"]] = definition

            receipts = [(request_id + ":project", "work.create", project),
                        (request_id + ":work", "work.project-sheet.apply", project),
                        (request_id + ":assessment", "assessment.scope.declare", scope)]
            for row in documents:
                alias = row["source_alias"]
                claim = document_claims[alias]
                document = ref(claim["document_ref"], "dat.content.document")
                expected_id = "worker-" + sha256((request_id + ":" + alias).encode()).hexdigest()[:28]
                if document.id != expected_id:
                    return denied
                document_record = current(document)
                authored = _json_value(document_record.payload["document"])
                if identity(ref(authored["authoring_scope"], "work.project")) != identity(project):
                    return denied
                association = ref(claim["association_ref"], "document-association")
                link_record = current(association)
                link = _json_value(link_record.payload["association"])
                alias_key = sha256(alias.encode()).hexdigest()[:28]
                if (link_record.payload.get("active") is not True
                        or identity(ref(link["subject"], "work.project")) != identity(project)
                        or link.get("namespace") != "worker.source" or link.get("key") != "alias-" + alias_key
                        or identity(ref(link["document"]["ref"], "dat.content.document")) != identity(document)):
                    return denied
                receipts.extend(((request_id + ":doc:" + alias_key, "dat.content.document.create", document),
                                 (request_id + ":link:" + alias_key, "dat.content.link", association)))
            for key, operation, target in receipts:
                receipt = self._owner_reader.get_receipt(key)
                if (receipt is None or receipt.logical_request_key != key or receipt.operation != operation
                        or _json_value(receipt.status) != "committed" or identity(receipt.target) != identity(target)):
                    return denied
            return {"outcome": "read", "read_only": True, "writes": 0,
                    "criterion_definitions": definitions, "verified_receipt_count": len(receipts)}
        except (AttributeError, KeyError, TypeError, ValueError):
            # Never return partial definitions, receipt existence or foreign metadata.
            return denied

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        from herzchen.contracts import ResourceRef

        if operation == "work.import.readback":
            return self._import_readback(payload, actor=actor)
        if operation == "work.project.list":
            return self.list_projects(actor=actor, parent_ref=payload.get("parent_ref"),
                                      cursor=payload.get("cursor"), limit=payload.get("limit"))
        project_reads = {"work.project.read", "work.pending.read", "work.pending.list",
                         "work.project.lifecycle.read", "work.manager.inbox"}
        grant = self._read_grant(actor) if operation in project_reads else None
        if operation in project_reads and grant is None:
            return self._project_read_denied()
        if operation in {"work.project.read", "work.pending.read", "work.project.lifecycle.read", "work.manager.inbox"}:
            try:
                raw = payload["project_ref"]
                project_ref = ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
            except (KeyError, TypeError, ValueError):
                return self._project_read_denied()
            if not grant.allows(project_ref):
                return self._project_read_denied()
        if operation == "work.project.read":
            record = self._owner_reader.get_record(project_ref)
            if record is None:
                return self._project_read_denied()
            return {"outcome": "read", "project_ref": _json_value(record.ref), "record": _record_dict(record),
                    "read_only": True, "writes": 0}
        if operation == "work.project.lifecycle.read":
            return self._read_project_lifecycle(payload)
        if operation == "work.manager.inbox":
            return self._manager_inbox(payload, actor=actor)
        if operation == "work.pending.list":
            parent = payload.get("parent_ref")
            if parent is not None:
                try:
                    parent_ref = ResourceRef.from_dict(parent) if isinstance(parent, Mapping) else parent
                except (TypeError, ValueError):
                    return self._project_read_denied()
                if not grant.allows(parent_ref):
                    return self._project_read_denied()
            records = [record for record in self._pending_projects(parent) if grant.allows(getattr(record, "ref", None))]
            return {
                "outcome": "listed",
                "records": [_record_dict(record) for record in records],
                "project_refs": [_json_value(getattr(record, "ref", None)) for record in records],
                "count": len(records),
                "receipt": None,
                "replayed": False,
                "event_ids": [],
                "executable": False,
            }
        if operation != "work.pending.read":
            return {
                "outcome": "unavailable",
                "operation": operation,
                "error": {"code": "canonical_operation_unavailable", "message": "this binding exposes only the finite pending list and read operations"},
            }
        record = self._owner_reader.get_record(project_ref)
        if record is None:
            return self._project_read_denied()
        return {
            "outcome": "read",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(record),
            "receipt": None,
            "replayed": False,
            "event_ids": [],
            "executable": False,
        }

    def _read_project_lifecycle(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        result = self._lifecycle_read({"project_ref": payload.get("project_ref")}, request_id="read-only")
        if result.get("outcome") != "read":
            return result
        manager_ref = payload.get("manager_ref")
        transition = result.get("transition")
        if isinstance(transition, Mapping):
            transition = dict(transition)
            transition.setdefault("intent", {"activate": "active", "resume": "active", "manager-close-request": "closing", "orchestrator-close": "terminal"}.get(transition.get("action"), result.get("lifecycle")))
        return {
            "outcome": "read",
            "project_ref": result.get("project_ref"),
            "task_ref": payload.get("task_ref"),
            "manager_ref": manager_ref,
            "generation": manager_ref.get("generation", 1) if isinstance(manager_ref, Mapping) else 1,
            "state": "completed" if result.get("lifecycle") == "completed" else result.get("lifecycle"),
            "transition": transition,
            "reconciliation": result.get("reconciliation"),
            "close_request": result.get("close_request"),
        }

    def manager_inbox(
        self,
        project_ref: Any,
        *,
        actor: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        safety_scan: bool = True,
    ) -> Mapping[str, Any]:
        """Convenience read on the finite binding for manager integrations."""
        from herzchen.contracts import ResourceRef

        ref = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        return self.read(
            "work.manager.inbox",
            {"project_ref": _json_value(ref), "cursor": cursor, "limit": limit, "safety_scan": safety_scan},
            actor=actor,
        )

    def manager_inventory(self, *, actor: str, native_observer: Any = None) -> Mapping[str, Any]:
        """Read a project-scoped manager inventory through existing ports."""

        from .manager_inventory import ManagerInventoryReader

        def pending_reader(selected_actor: str) -> Mapping[str, Any]:
            return self.read("work.pending.list", {}, actor=selected_actor)

        def project_reader(project_ref: Any) -> Any:
            if self.sheet_port is None:
                raise RuntimeError("accepted ProjectSheet reader is unavailable")
            return self.sheet_port.export(self._record_ref(project_ref))

        def assignment_reader(assignment_ref: Any) -> Any:
            if self.assignments_port is None or not callable(getattr(self.assignments_port, "get", None)):
                raise RuntimeError("accepted ResponsibilityAssignments reader is unavailable")
            return self.assignments_port.get(self._record_ref(assignment_ref))

        return ManagerInventoryReader(
            pending_reader=pending_reader,
            project_reader=project_reader,
            assignment_reader=assignment_reader,
        ).read(actor=actor, native_observer=native_observer)

    def _manager_inbox(self, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        """Build the bounded read-only manager projection from public ports."""
        if self.sheet_port is None:
            return self._unsupported(
                "work.manager.inbox",
                request_id="read-only",
                code="canonical_project_sheet_port_unavailable",
                message="accepted ProjectSheet read port was not injected",
            )
        try:
            from herzchen.contracts import ResourceRef
            from .inbox import derive_manager_inbox

            project_ref = ResourceRef.from_dict(payload["project_ref"])
            view = self.sheet_port.export(project_ref)
            view_value = _json_value(view.to_dict() if hasattr(view, "to_dict") else view)
            task_records: dict[tuple[str, str, str], Mapping[str, Any]] = {}
            completion_verifications: dict[tuple[str, str, str], Mapping[str, Any]] = {}

            def typed_ref(value: Any) -> Any:
                if isinstance(value, ResourceRef):
                    return value
                if isinstance(value, Mapping):
                    try:
                        return ResourceRef.from_dict(value)
                    except (TypeError, ValueError, KeyError):
                        return None
                return None

            def same_identity(left: Any, right: Any) -> bool:
                return (
                    getattr(left, "authority", None), getattr(left, "kind", None), getattr(left, "id", None)
                ) == (
                    getattr(right, "authority", None), getattr(right, "kind", None), getattr(right, "id", None)
                )

            if isinstance(view_value, Mapping):
                for task in view_value.get("tasks", ()):
                    if not isinstance(task, Mapping):
                        continue
                    task_ref = typed_ref(task.get("ref"))
                    if (task_ref is None or task_ref.authority != project_ref.authority
                            or task_ref.kind != "work.task"):
                        continue
                    # Resolve the canonical current task only through the
                    # actor-scoped project/task reader. This enforces D31's
                    # selected-project/current-parent rule before any DAT read.
                    record = self.reader.get_record(task_ref)
                    if record is None or record.ref.kind != "work.task":
                        continue
                    owner_parent = typed_ref(record.payload.get("project_ref") or record.payload.get("parent"))
                    if owner_parent is None or not same_identity(owner_parent, project_ref):
                        continue
                    key = (record.ref.authority, record.ref.kind, record.ref.id)
                    task_records[key] = {
                        "ref": _json_value(record.ref),
                        "lifecycle": _json_value(record.payload.get("lifecycle")),
                        "revision": _json_value(record.ref.revision),
                    }

                    completion = record.payload.get("completion")
                    completion_task_ref = typed_ref(completion.get("task_ref")) if isinstance(completion, Mapping) else None
                    completion_project_ref = typed_ref(completion.get("project_ref")) if isinstance(completion, Mapping) else None
                    candidate_ref = typed_ref(completion.get("candidate_ref")) if isinstance(completion, Mapping) else None
                    result_ref = typed_ref(completion.get("result_ref")) if isinstance(completion, Mapping) else None
                    gate_values = completion.get("gate_refs") if isinstance(completion, Mapping) else None
                    evidence_values = completion.get("evidence_refs") if isinstance(completion, Mapping) else None
                    evidence_hashes = completion.get("evidence_hashes") if isinstance(completion, Mapping) else None
                    gates = tuple(typed_ref(value) for value in gate_values) if isinstance(gate_values, (list, tuple)) else ()
                    evidence = tuple(typed_ref(value) for value in evidence_values) if isinstance(evidence_values, (list, tuple)) else ()
                    completion_revision = completion.get("task_revision") if isinstance(completion, Mapping) else None
                    completion_generation = completion.get("generation") if isinstance(completion, Mapping) else None
                    completion_assignment = typed_ref(completion.get("assignment_ref")) if isinstance(completion, Mapping) else None
                    if (
                        record.payload.get("lifecycle") == "completed"
                        and isinstance(completion, Mapping)
                        and completion_task_ref is not None
                        and same_identity(completion_task_ref, record.ref)
                        and completion_task_ref.revision == completion_revision
                        and completion_project_ref is not None
                        and same_identity(completion_project_ref, project_ref)
                        and candidate_ref is not None
                        and result_ref is not None
                        and result_ref.kind == "wrk.result"
                        and completion_assignment is not None
                        and completion_assignment.kind == "wrk.assignment"
                        and isinstance(completion_generation, int)
                        and not isinstance(completion_generation, bool)
                        and completion_generation > 0
                        and gates and all(value is not None for value in gates)
                        and evidence and all(value is not None for value in evidence)
                        and bool(evidence_hashes)
                        and callable(getattr(self.assignments_port, "completion_blockers", None))
                    ):
                        try:
                            owner_state = self.assignments_port.completion_blockers(
                                record.ref,
                                candidate=candidate_ref,
                                gate_refs=gates,
                                actor=self._actor(actor),
                                completion_evidence_refs=evidence,
                                completion_evidence_hashes=evidence_hashes,
                            )
                        except Exception:
                            owner_state = {}
                        accepted_decisions = tuple(
                            typed_ref(value) for value in owner_state.get("accepted_decision_refs", ())
                        ) if isinstance(owner_state, Mapping) else ()
                        exact_gates = all(
                            accepted is not None and any(accepted == gate for gate in gates)
                            for accepted in accepted_decisions
                        )
                        is_current = bool(
                            isinstance(owner_state, Mapping)
                            and owner_state.get("required") is True
                            and not owner_state.get("blockers")
                            and owner_state.get("evidence_verification") == "verified"
                            and owner_state.get("candidate_ref") == _json_value(candidate_ref)
                            and accepted_decisions
                            and exact_gates
                        )
                        completion_verifications[key] = {
                            "task_ref": _json_value(record.ref),
                            "completion": _json_value(completion),
                            "result_ref": _json_value(result_ref),
                            "candidate_ref": _json_value(candidate_ref),
                            "gate_refs": [_json_value(value) for value in gates],
                            "accepted_decision_refs": [
                                _json_value(value) for value in accepted_decisions if value is not None
                            ],
                            "evidence_refs": [_json_value(value) for value in evidence],
                            "evidence_verification": owner_state.get("evidence_verification", "unknown") if isinstance(owner_state, Mapping) else "unknown",
                            "verified": is_current,
                        }
                view_value["tasks"] = [
                    task for task in view_value.get("tasks", ())
                    if isinstance(task, Mapping)
                    and (task_ref := typed_ref(task.get("ref"))) is not None
                    and (task_ref.authority, task_ref.kind, task_ref.id) in task_records
                ]
            events = view_value.get("project", {}).get("observed", {}).get("events")
            if not isinstance(events, (list, tuple)):
                raise ValueError("ProjectSheet scoped event history is unavailable")
            return derive_manager_inbox(
                view_value,
                events=events,
                cursor=payload.get("cursor"),
                dependency_records=task_records,
                completion_verifications=completion_verifications,
                limit=payload.get("limit", 100),
                safety_scan=payload.get("safety_scan", True),
            )
        except Exception as exc:
            return {
                "outcome": "error",
                "error": {
                    "code": "manager_inbox_read_failed",
                    "message": str(exc),
                    "operation": "work.manager.inbox",
                },
                "dispatch": False,
                "launch": False,
                "acknowledged": False,
            }


__all__ = ["FiniteWorkOperations", "HerzchenBindingConfig"]
