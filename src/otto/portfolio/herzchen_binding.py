"""Public finite Herzchen command/read binding for the OTT-03 facade.

The trusted bootstrap constructs the accepted Herzchen graph and injects only
its finite command port and read-only consumer reader. Otto owns neither
storage nor a second command/event implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class HerzchenBindingConfig:
    """Explicit authority and credential used to authenticate an Otto actor."""

    authority: str
    credential_ref: str

    def authenticated_actor(self, actor: str) -> Any:
        from herzchen.contracts import AuthenticatedActor

        return AuthenticatedActor(self.authority, actor, self.credential_ref)


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
        authoring_port: Any = None,
        create_open_port: Any = None,
    ) -> None:
        if port is None or reader is None:
            raise ValueError("port and reader are required for the canonical binding")
        self.port = port
        self.reader = reader
        self.binding = binding
        self.sheet_port = sheet_port
        self.content_port = content_port
        self.assignments_port = assignments_port
        self.authoring_port = authoring_port
        self.create_open_port = create_open_port

    def _actor(self, actor: str) -> Any:
        return self.binding.authenticated_actor(actor)

    def _events_for(self, receipt: Any) -> list[str]:
        receipt_dict = _receipt_dict(receipt) or {}
        wanted = set(receipt_dict.get("event_ids", []))
        if not wanted:
            return []
        return [event.event_id for event in self.reader.list_events() if getattr(event, "event_id", None) in wanted]

    def _result(self, record: Any, *, request_id: str, replayed: bool) -> dict[str, Any]:
        receipt = self.reader.get_receipt(request_id)
        observed = self.reader.get_record(record.ref)
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
        if operation == "work.pending.create" and payload.get("open"):
            return self._create_and_open(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.open":
            return self._open_existing(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.edit":
            return self._revise(payload, request_id=request_id, actor=actor)
        if operation in {"work.pending.revisit", "work.pending.prerequisite-satisfied"}:
            return self._attention(operation, payload, request_id=request_id, actor=actor)
        if operation == "work.pending.admission":
            return self._admit(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.assign":
            return self._assign_roles(payload, request_id=request_id, actor=actor)
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
        before = self.reader.get_receipt(request_id)
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

    @staticmethod
    def _key(request_id: str, suffix: str) -> str:
        return request_id + ":" + suffix

    def _record_ref(self, value: Any) -> Any:
        from herzchen.contracts import ResourceRef

        return ResourceRef.from_dict(value) if isinstance(value, Mapping) else value

    def _receipt(self, request_id: str) -> Any:
        return self.reader.get_receipt(request_id)

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

    def _create_and_open(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
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
        before = self.reader.get_receipt(request_id)
        try:
            opened = self.create_open_port.create_pending_and_open(
                actor=self._actor(actor),
                request_id=request_id,
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                metadata=self._metadata(payload, request_id, payload.get("template", "blank")),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {
                    "outcome": "error",
                    "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.create"},
                    "replayed": False,
                    "event_ids": [],
                }
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
            request_id + ":materialized",
            request_id + ":materialize-failure",
            request_id + ":materialize-failure:actor",
        )
        event_ids = {
            event_id
            for key in receipt_keys
            for event_id in ((_receipt_dict(self.reader.get_receipt(key)) or {}).get("event_ids", []))
        }
        record = None
        if project_ref is not None:
            record = self.reader.get_record(self._record_ref(project_ref))
        return {
            "outcome": "replayed" if before is not None else ("created" if status == "opened" else status),
            "project_ref": _json_value(project_ref),
            "record": None if record is None else _record_dict(record),
            "receipt": _receipt_dict(self.reader.get_receipt(request_id)),
            "project_receipt": _receipt_dict(self.reader.get_receipt(request_id + ":project")),
            "replayed": before is not None,
            "event_ids": [
                event.event_id
                for event in self.reader.list_events()
                if getattr(event, "event_id", None) in event_ids
            ],
            "executable": False,
            "open": _json_value(opened),
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
        assignments: dict[str, Any] = {}
        parent_receipt = None
        executor_values = roles["executor"] if isinstance(roles["executor"], list) else [roles["executor"]]
        role_inputs = [("parent", [self._record_ref(roles["parent"])])]
        role_inputs.extend((("manager", [roles["manager"]]), ("executor", executor_values)))
        event_ids: list[str] = []
        for role, principals in role_inputs:
            for index, principal in enumerate(principals):
                key = self._key(request_id, role + (":" + str(index) if len(principals) > 1 else ""))
                prior = self._receipt(key)
                try:
                    assignment = self.assignments_port.assign(ref, role=role, principal=principal, manager=roles["manager"], logical_request_key=key, actor=actor_value)
                except Exception as exc:
                    if type(exc).__name__ == "ReplayConflictError":
                        return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": []}
                    raise
                receipt = self._receipt(key)
                assignments[key] = {"ref": _json_value(getattr(assignment, "ref", None)), "role": role, "principal": _json_value(principal), "receipt": _receipt_dict(receipt), "replayed": prior is not None}
                event_ids.extend(self._events_for(receipt))
                if role == "parent":
                    parent_receipt = receipt
        return {"outcome": "assigned", "project_ref": _json_value(ref), "roles": assignments, "parent_receipt": _receipt_dict(parent_receipt), "event_ids": event_ids, "replayed": all(item["replayed"] for item in assignments.values()) if assignments else False, "executable": False}

    def _content_context(self, operation: str, target: Any, request_id: str, actor: Any, payload: Mapping[str, Any], schema_revision: str) -> Any:
        from herzchen.contracts import TransactionContext, canonical_request_digest

        context = TransactionContext(actor, request_id, "0" * 64)
        digest = canonical_request_digest(logical_request_key=request_id, operation=operation, schema_revision=schema_revision, target=target, actor=actor, payload=payload, context=context)
        return TransactionContext(actor, request_id, digest)

    def _create_document(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.content_port is None:
            return self._unsupported("work.pending.document.create", request_id=request_id, code="canonical_content_port_unavailable", message="accepted ContentCommandHandler command port was not injected")
        from herzchen.content import CONTENT_SCHEMA_REVISION, ContentDocument, ContentRevision
        from herzchen.contracts import ResourceRef

        actor_value = self._actor(actor)
        project_ref = self._record_ref(payload["project_ref"])
        doc_id = payload.get("document_id") or "document-" + sha256(request_id.encode()).hexdigest()[:28]
        document_ref = ResourceRef(self.binding.authority, "dat.content.document", doc_id)
        document = ContentDocument(document_ref, payload.get("role", "supporting"), payload.get("visibility", "private"), payload.get("access_mode", "read"), actor, authoring_scope=project_ref)
        revision = ContentRevision(document_ref, "rev-1", payload.get("content", {}), actor_value, initial=True)
        command_payload = {"document": document, "revision": revision}
        context = self._content_context("dat.content.document.create", document_ref, request_id, actor_value, command_payload, CONTENT_SCHEMA_REVISION)
        envelope = self.content_port.build_create_document(context, document, revision)
        receipt_before = self._receipt(request_id)
        try:
            receipt_result = self.content_port.execute(envelope)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.document.create"}, "replayed": False, "event_ids": []}
            raise
        receipt = self._receipt(request_id) or receipt_result
        return {"outcome": "replayed" if receipt_before is not None else "created", "document_ref": _json_value(document_ref), "project_ref": _json_value(project_ref), "record": _record_dict(self.reader.get_record(document_ref)), "receipt": _receipt_dict(receipt), "replayed": receipt_before is not None, "event_ids": self._events_for(receipt)}

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
        receipt_before = self._receipt(request_id)
        try:
            receipt_result = self.content_port.execute(envelope)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.document.link"}, "replayed": False, "event_ids": []}
            raise
        receipt = self._receipt(request_id) or receipt_result
        return {"outcome": "replayed" if receipt_before is not None else "linked", "project_ref": _json_value(project_ref), "document_ref": _json_value(document_ref), "association_ref": _json_value(target), "record": _record_dict(self.reader.get_record(target)), "receipt": _receipt_dict(receipt), "replayed": receipt_before is not None, "event_ids": self._events_for(receipt)}

    def _unsupported(self, operation: str, *, request_id: Optional[str] = None, code: str = "canonical_operation_unavailable", message: str = "no accepted finite Herzchen endpoint is available for this Otto operation") -> dict[str, Any]:
        receipt = self.reader.get_receipt(request_id) if request_id else None
        return {
            "outcome": "unavailable",
            "operation": operation,
            "error": {"code": code, "message": message},
            "receipt": _receipt_dict(receipt),
            "replayed": False,
            "event_ids": self._events_for(receipt),
        }

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
        before = self.reader.get_receipt(request_id)
        try:
            record = self.port.revise(ResourceRef.from_dict(payload["project_ref"]), **changes)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.edit"}, "replayed": False, "event_ids": []}
            raise
        receipt = self.reader.get_receipt(request_id)
        observed = self.reader.get_record(record.ref)
        return {
            "outcome": "replayed" if before is not None else "edited",
            "project_ref": _json_value(record.ref),
            "record": _record_dict(observed),
            "receipt": _receipt_dict(receipt),
            "replayed": before is not None,
            "event_ids": self._events_for(receipt),
            "executable": False,
        }

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        if operation != "work.pending.read":
            return {
                "outcome": "unavailable",
                "operation": operation,
                "error": {"code": "canonical_operation_unavailable", "message": "this binding currently exposes pending create and read only"},
            }
        from herzchen.contracts import ResourceRef

        record = self.reader.get_record(ResourceRef.from_dict(payload["project_ref"]))
        return {
            "outcome": "read",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(record),
            "receipt": None,
            "replayed": False,
            "event_ids": [],
            "executable": False,
        }


__all__ = ["FiniteWorkOperations", "HerzchenBindingConfig"]
