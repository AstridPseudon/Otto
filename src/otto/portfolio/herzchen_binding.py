"""Public Store/WorkGraph binding for the OTT-03 portfolio facade.

This module is intentionally small. The injected objects are the accepted
Herzchen public ``Store`` and ``WorkGraph`` instances; Otto owns neither
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
        "kind": _json_value(getattr(record, "kind", None)),
        "title": _json_value(getattr(record, "title", None)),
        "name": _json_value(getattr(record, "name", None)),
        "lifecycle": _json_value(getattr(record, "lifecycle", None)),
        "readiness": _json_value(getattr(record, "readiness", None)),
        "revision": _json_value(getattr(getattr(record, "ref", None), "revision", None)),
        "version": _json_value(getattr(record, "version", None)),
        "payload": payload,
    }


def _receipt_dict(receipt: Any) -> Optional[dict[str, Any]]:
    if receipt is None:
        return None
    to_dict = getattr(receipt, "to_dict", None)
    return _json_value(to_dict() if callable(to_dict) else receipt)


class StoreWorkOperations:
    """The real OTT-03 operation port over injected public Herzchen objects."""

    def __init__(self, *, store: Any, graph: Any, binding: HerzchenBindingConfig) -> None:
        if store is None or graph is None:
            raise ValueError("store and graph are required for the canonical binding")
        self.store = store
        self.graph = graph
        self.binding = binding

    def _actor(self, actor: str) -> Any:
        return self.binding.authenticated_actor(actor)

    def _events_for(self, receipt: Any) -> list[str]:
        receipt_dict = _receipt_dict(receipt) or {}
        wanted = set(receipt_dict.get("event_ids", []))
        if not wanted:
            return []
        return [event.event_id for event in self.store.list_events() if getattr(event, "event_id", None) in wanted]

    def _result(self, record: Any, *, request_id: str, replayed: bool) -> dict[str, Any]:
        receipt = self.store.get_receipt(request_id)
        return {
            "outcome": "replayed" if replayed else "created",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(record),
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
        if operation != "work.pending.create":
            return {
                "outcome": "unavailable",
                "operation": operation,
                "error": {"code": "canonical_operation_unavailable", "message": "this binding currently exposes pending create and read only"},
            }
        if payload.get("open"):
            return {
                "outcome": "unavailable",
                "operation": operation,
                "error": {"code": "host_open_unavailable", "message": "canonical WorkGraph creation is pending-only; host/session open is outside this binding"},
            }
        edit = payload.get("edit", {})
        actor_value = self._actor(actor)
        before = self.store.get_receipt(request_id)
        try:
            record = self.graph.create_pending_project(
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

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        if operation != "work.pending.read":
            return {
                "outcome": "unavailable",
                "operation": operation,
                "error": {"code": "canonical_operation_unavailable", "message": "this binding currently exposes pending create and read only"},
            }
        from herzchen.contracts import ResourceRef

        record = self.graph.get(ResourceRef.from_dict(payload["project_ref"]))
        return {
            "outcome": "read",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(record),
            "receipt": None,
            "replayed": False,
            "event_ids": [],
            "executable": False,
        }


__all__ = ["HerzchenBindingConfig", "StoreWorkOperations"]
