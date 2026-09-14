"""Public finite Herzchen command/read binding for the OTT-03 facade.

The trusted bootstrap constructs the accepted Herzchen graph and injects only
its finite command port and read-only consumer reader. Otto owns neither
storage nor a second command/event implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    def __init__(self, *, port: Any, reader: Any, binding: HerzchenBindingConfig) -> None:
        if port is None or reader is None:
            raise ValueError("port and reader are required for the canonical binding")
        self.port = port
        self.reader = reader
        self.binding = binding

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
        if operation == "work.pending.edit":
            return self._revise(payload, request_id=request_id, actor=actor)
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
