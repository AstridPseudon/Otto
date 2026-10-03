"""Finite same-assignment manager binding and handover seam.

This module delegates assignment identity, history, pins, and generation CAS
to the existing Herzchen command port.  It is not a lease, ledger, scheduler,
native process manager, or replacement authority.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional


class ManagerContinuityError(ValueError):
    """A continuity request is malformed or cannot be safely fenced."""


def _json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json(to_dict())
    return str(value)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    value = _json(value)
    if not isinstance(value, Mapping):
        raise ManagerContinuityError(f"{field} must be an object")
    return dict(value)


def _ref(value: Any) -> Optional[dict[str, Any]]:
    value = _json(value)
    if not isinstance(value, Mapping):
        return None
    selected = value.get("assignment_ref") or value.get("ref") or value
    selected = _json(selected)
    if not isinstance(selected, Mapping) or not all(selected.get(key) for key in ("authority", "kind", "id")):
        return None
    return dict(selected)


def _same(left: Any, right: Any) -> bool:
    return json.dumps(_json(left), sort_keys=True, separators=(",", ":")) == json.dumps(_json(right), sort_keys=True, separators=(",", ":"))


def _field(assignment: Mapping[str, Any], name: str, default: Any = None) -> Any:
    if name in assignment:
        return assignment[name]
    payload = assignment.get("payload")
    if isinstance(payload, Mapping):
        return payload.get(name, default)
    return default


class ManagerContinuity:
    """A finite owner-only wrapper around existing assignment ports."""

    def __init__(self, *, assignment_reader: Callable[[Any], Any], assignments_port: Any) -> None:
        if not callable(assignment_reader):
            raise ManagerContinuityError("assignment_reader is required")
        if assignments_port is None:
            raise ManagerContinuityError("assignments_port is required")
        self.assignment_reader = assignment_reader
        self.assignments_port = assignments_port

    def bind_or_reassign(
        self,
        project_ref: Mapping[str, Any],
        *,
        principal: Any,
        request_key: str,
        actor: Any = None,
        assignment_ref: Optional[Mapping[str, Any]] = None,
        expected_generation: Optional[int] = None,
        reporter: Any = None,
        launcher: Any = None,
        agent: Any = None,
        native_identity: Any = None,
    ) -> dict[str, Any]:
        """Create once when absent, otherwise reassign the same assignment with CAS."""

        if not isinstance(project_ref, Mapping) or not project_ref.get("id"):
            raise ManagerContinuityError("project_ref is required")
        if not isinstance(principal, str) or not principal.strip():
            raise ManagerContinuityError("principal is required")
        if not isinstance(request_key, str) or not request_key.strip():
            raise ManagerContinuityError("request_key is required")
        if assignment_ref is None:
            assign = getattr(self.assignments_port, "assign", None) or getattr(self.assignments_port, "create", None)
            if not callable(assign):
                return {"outcome": "unsupported", "status": "unsupported", "error": {"code": "assignment_create_unsupported", "message": "canonical assignment create is unavailable"}}
            try:
                created = assign(
                    project_ref,
                    role="manager",
                    principal=principal,
                    manager=principal,
                    reporter=reporter,
                    launcher=launcher,
                    agent=agent,
                    session=native_identity,
                    logical_request_key=request_key,
                    actor=actor,
                )
            except Exception as exc:
                return {"outcome": "error", "status": "unknown", "error": {"code": "assignment_create_unknown", "message": str(exc)}}
            created_value = _mapping(created, "assignment")
            return {"outcome": "bound", "created": True, "replayed": False, "assignment": created_value, "generation": _field(created_value, "generation")}

        current_raw = self.assignment_reader(assignment_ref)
        if current_raw is None:
            return {"outcome": "unavailable", "status": "unknown", "error": {"code": "assignment_unavailable", "message": "current assignment could not be read"}}
        current = _mapping(current_raw, "assignment")
        current_ref = _ref(current)
        requested_ref = _ref(assignment_ref)
        if current_ref is None or requested_ref is None or not _same(current_ref, requested_ref):
            return {"outcome": "stale", "status": "conflict", "error": {"code": "assignment_ref_stale", "message": "assignment reference is not the current exact assignment"}}
        current_generation = _field(current, "generation")
        if expected_generation != current_generation:
            return {"outcome": "stale", "status": "conflict", "error": {"code": "stale_generation", "message": "assignment generation is stale", "expected_generation": expected_generation, "current_generation": current_generation}}
        old_principal = _field(current, "principal", _field(current, "manager"))
        old_session = _field(current, "session")
        if old_principal == principal and (native_identity is None or _same(old_session, native_identity)):
            return {"outcome": "replayed", "created": False, "replayed": True, "assignment": current, "generation": current_generation, "preserved": {"pins": _json(_field(current, "pins", ())), "history": _json(_field(current, "history", ()))}}
        reassign = getattr(self.assignments_port, "reassign", None)
        if not callable(reassign):
            return {"outcome": "unsupported", "status": "unsupported", "error": {"code": "assignment_reassign_unsupported", "message": "canonical assignment reassign is unavailable"}}
        try:
            replacement = reassign(
                requested_ref,
                principal=principal,
                reporter=_field(current, "reporter") if reporter is None else reporter,
                launcher=_field(current, "launcher") if launcher is None else launcher,
                agent=_field(current, "agent") if agent is None else agent,
                session=_field(current, "session") if native_identity is None else native_identity,
                reason="otto-manager-continuity-handover",
                expected_generation=expected_generation,
                logical_request_key=request_key,
                actor=actor,
            )
        except Exception as exc:
            return {"outcome": "stale", "status": "conflict", "error": {"code": "assignment_reassign_rejected", "message": str(exc)}}
        replacement_value = _mapping(replacement, "assignment")
        return {
            "outcome": "reassigned",
            "created": False,
            "replayed": False,
            "assignment": replacement_value,
            "generation": _field(replacement_value, "generation"),
            "preserved": {"pins": _json(_field(current, "pins", ())), "history": _json(_field(current, "history", ())), "prior_principal": old_principal, "prior_generation": current_generation},
        }

    @staticmethod
    def unsupported_resume(*, native_port: Any = None) -> dict[str, Any]:
        if native_port is None or not callable(getattr(native_port, "resume", None)):
            return {"outcome": "undetermined", "status": "unsupported", "adapter_called": False, "error": {"code": "resume_unsupported", "message": "supported exact-session resume is unavailable"}}
        return {"outcome": "undetermined", "status": "unsupported", "adapter_called": False, "error": {"code": "resume_not_activated", "message": "continuity seam does not activate native resume"}}

    @staticmethod
    def unsupported_close(*, native_port: Any = None) -> dict[str, Any]:
        if native_port is None or not callable(getattr(native_port, "close", None)):
            return {"outcome": "undetermined", "status": "unsupported", "adapter_called": False, "error": {"code": "close_unsupported", "message": "supported exact-identity close is unavailable"}}
        return {"outcome": "undetermined", "status": "unsupported", "adapter_called": False, "error": {"code": "close_not_activated", "message": "continuity seam does not activate native close"}}


__all__ = ["ManagerContinuity", "ManagerContinuityError"]
