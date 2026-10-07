"""Finite same-assignment manager binding and handover seam.

This module delegates assignment identity, history, pins, and generation CAS
to the existing Herzchen command port.  It is not a lease, ledger, scheduler,
native process manager, or replacement authority.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
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
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
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


def _positive_generation(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ManagerContinuityError(f"{field} must be a positive integer")
    return value


def _session(value: Any, field: str) -> Any:
    """Keep native identity opaque while rejecting an empty replacement."""

    value = _json(value)
    if value is None or value == "" or value == {}:
        raise ManagerContinuityError(f"{field} is required")
    return value


def _outcome(value: Any, field: str) -> tuple[bool, dict[str, Any]]:
    """Normalize a custody/readiness callback without inventing success."""

    value = _json(value)
    if value is True:
        return True, {"resolved": True}
    if value is False or value is None:
        return False, {"resolved": False}
    if not isinstance(value, Mapping):
        raise ManagerContinuityError(f"{field} must return an object or boolean")
    result = dict(value)
    status = str(result.get("status", result.get("state", result.get("outcome", "")))).lower()
    resolved = result.get("resolved") is True or status in {
        "resolved", "reconciled", "closed", "stopped", "none", "no_effect",
    }
    if result.get("unknown") is True or status in {"unknown", "pending", "active", "in_flight"}:
        resolved = False
    result["resolved"] = resolved
    return resolved, result


def _call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call one supplied adapter exactly once.

    A callback may reconcile or close an external session.  Retrying after a
    ``TypeError`` could duplicate that effect, so signature compatibility is
    intentionally resolved by the caller rather than by an implicit retry.
    """

    return callback(*args, **kwargs)


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

    def replace_session(
        self,
        project_ref: Mapping[str, Any],
        *,
        principal: str,
        request_key: str,
        assignment_ref: Mapping[str, Any],
        expected_generation: int,
        native_identity: Any = None,
        new_session: Any = None,
        old_session: Any = None,
        prior_session: Any = None,
        actor: Any = None,
        custody: Mapping[str, Any] | bool | None = None,
        reconcile: Callable[..., Any] | None = None,
        close: Callable[..., Any] | None = None,
        context_builder: Callable[..., Any] | None = None,
        readiness: Callable[..., Any] | None = None,
        operational_help: Callable[..., Any] | None = None,
        restart: Callable[..., Any] | None = None,
        reporter: Any = None,
        launcher: Any = None,
        agent: Any = None,
    ) -> dict[str, Any]:
        """Replace manager custody, then deliver a fresh role context.

        This is a composition over existing owner operations.  It never owns
        a session registry, closes a provider, persists a checkpoint, or
        starts a scheduler.  The old session must be reconciled/closed (or an
        equivalent explicit ``custody`` proof supplied) before the canonical
        assignment reassigns.  Context/readiness/restart callbacks are
        supplied by the existing owner/native composition so a failed late
        step leaves the new assignment and its history available for recovery.
        """

        if not isinstance(project_ref, Mapping) or not project_ref.get("id"):
            raise ManagerContinuityError("project_ref is required")
        if not isinstance(principal, str) or not principal.strip():
            raise ManagerContinuityError("principal is required")
        if not isinstance(request_key, str) or not request_key.strip():
            raise ManagerContinuityError("request_key is required")
        expected = _positive_generation(expected_generation, "expected_generation")
        if not isinstance(assignment_ref, Mapping):
            raise ManagerContinuityError("assignment_ref is required")
        replacement_session = _session(
            native_identity if native_identity is not None else new_session,
            "native_identity",
        )

        current_raw = self.assignment_reader(assignment_ref)
        if current_raw is None:
            return {
                "outcome": "unavailable", "status": "unknown",
                "error": {"code": "assignment_unavailable", "message": "current assignment could not be read"},
                "canonical_mutation": False,
            }
        current = _mapping(current_raw, "assignment")
        current_ref = _ref(current)
        requested_ref = _ref(assignment_ref)
        if current_ref is None or requested_ref is None or not _same(current_ref, requested_ref):
            return {
                "outcome": "stale", "status": "conflict",
                "error": {"code": "assignment_ref_stale", "message": "assignment reference is not the current exact assignment"},
                "canonical_mutation": False,
            }
        current_generation = _field(current, "generation")
        if current_generation != expected:
            return {
                "outcome": "stale", "status": "conflict",
                "error": {"code": "stale_generation", "message": "assignment generation is stale",
                           "expected_generation": expected, "current_generation": current_generation},
                "canonical_mutation": False,
            }
        scope = _field(current, "scope")
        if isinstance(scope, Mapping) and any(scope.get(key) != project_ref.get(key) for key in ("authority", "kind", "id") if key in project_ref):
            return {
                "outcome": "stale", "status": "conflict",
                "error": {"code": "assignment_scope_mismatch", "message": "assignment is outside the requested project"},
                "canonical_mutation": False,
            }

        current_session = _field(current, "session")
        expected_old = old_session if old_session is not None else prior_session
        if expected_old is not None and not _same(current_session, expected_old):
            return {
                "outcome": "stale", "status": "conflict",
                "error": {"code": "stale_session", "message": "prior session is not the current assignment session"},
                "canonical_mutation": False,
            }
        custody_result: dict[str, Any] = {"resolved": True, "state": "same_session"}
        if _same(current_session, replacement_session):
            # Same-session retry is safe only for the same current principal;
            # it is not a way for a stale principal to regain custody.
            if _field(current, "principal", _field(current, "manager")) != principal:
                return {
                    "outcome": "stale", "status": "conflict",
                    "error": {"code": "stale_session", "message": "stale session cannot regain manager custody"},
                    "canonical_mutation": False,
                }
            replacement = {"outcome": "replayed", "created": False, "replayed": True,
                           "assignment": current, "generation": current_generation,
                           "preserved": {"pins": _json(_field(current, "pins", ())),
                                         "history": _json(_field(current, "history", ()))}}
        else:
            if custody is None and reconcile is None:
                return {
                    "outcome": "blocked", "status": "held",
                    "error": {"code": "prior_session_custody_unresolved",
                               "message": "reconcile and close the prior session before replacement"},
                    "canonical_mutation": False,
                }
            custody_result: dict[str, Any]
            if reconcile is not None:
                try:
                    resolved, custody_result = _outcome(
                        _call(reconcile, current, current_session), "reconcile",
                    )
                except Exception as exc:
                    return {
                        "outcome": "blocked", "status": "held",
                        "error": {"code": "prior_session_reconciliation_failed", "message": str(exc)},
                        "canonical_mutation": False,
                    }
                if not resolved:
                    return {"outcome": "blocked", "status": "held", "custody": custody_result,
                            "error": {"code": "prior_session_custody_unresolved",
                                       "message": "prior session reconciliation is not resolved"},
                            "canonical_mutation": False}
            else:
                try:
                    resolved, custody_result = _outcome(custody, "custody")
                except ManagerContinuityError as exc:
                    return {"outcome": "blocked", "status": "held",
                            "error": {"code": "prior_session_custody_unresolved", "message": str(exc)},
                            "canonical_mutation": False}
                if not resolved:
                    return {"outcome": "blocked", "status": "held", "custody": custody_result,
                            "error": {"code": "prior_session_custody_unresolved",
                                       "message": "prior session custody is not resolved"},
                            "canonical_mutation": False}
            if close is not None:
                try:
                    closed, close_result = _outcome(_call(close, current, current_session), "close")
                except Exception as exc:
                    return {"outcome": "blocked", "status": "held", "custody": custody_result,
                            "error": {"code": "prior_session_close_failed", "message": str(exc)},
                            "canonical_mutation": False}
                if not closed:
                    return {"outcome": "blocked", "status": "held", "custody": custody_result,
                            "close": close_result,
                            "error": {"code": "prior_session_close_unresolved",
                                       "message": "prior session close is not resolved"},
                            "canonical_mutation": False}
            replacement = self.bind_or_reassign(
                project_ref, principal=principal, request_key=request_key, actor=actor,
                assignment_ref=assignment_ref, expected_generation=expected,
                reporter=reporter, launcher=launcher, agent=agent,
                native_identity=replacement_session,
            )
            if replacement.get("outcome") not in {"reassigned", "replayed"}:
                return {
                    **replacement, "canonical_mutation": False,
                    "recovery": {"request_key": request_key,
                                 "assignment_ref": current_ref,
                                 "generation": current_generation,
                                 "action": "re-read the current assignment and reconcile the retained result before retrying"},
                }

        new_assignment = replacement.get("assignment")
        new_generation = replacement.get("generation")
        result: dict[str, Any] = {
            "outcome": "replaced" if replacement.get("outcome") == "reassigned" else "replayed",
            "status": "ready", "replacement": replacement,
            "assignment": new_assignment, "generation": new_generation,
            "prior_session": _json(current_session), "native_identity": replacement_session,
            "custody": _json(custody_result), "canonical_mutation": replacement.get("outcome") == "reassigned",
            "stale_handles": {"assignment_ref": current_ref, "generation": expected,
                              "rejected": True, "reason": "assignment generation fence"},
            "recovery": {"request_key": request_key, "assignment_ref": _ref(new_assignment),
                         "generation": new_generation,
                         "action": "refresh current assignment and context; do not reuse the prior session"},
        }

        if context_builder is None:
            result.update({"status": "partial", "outcome": "partial",
                           "error": {"code": "current_context_not_delivered",
                                      "message": "replacement requires a current role-context builder"}})
            return result
        try:
            context = _call(context_builder, new_assignment, new_generation, replacement_session)
            context = _mapping(context, "current_context")
            context_ref = context.get("assignment_ref") or context.get("responsibility_ref")
            if context_ref is not None and not _same(_ref(context_ref), _ref(new_assignment)):
                # Refreshing identical immutable BASE for the new generation
                # is a public resource-adoption CAS. Resolve that exact one
                # transition through the canonical reader, never context JSON.
                refreshed = _mapping(self.assignment_reader(_ref(new_assignment)), "current_assignment")
                before_ref = _ref(new_assignment)
                payload = refreshed.get("payload") or {}
                if (not _same(_ref(context_ref), _ref(refreshed))
                        or not isinstance(payload, Mapping)
                        or not _same(payload.get("resource_adoption_base_ref"), before_ref)
                        or _field(refreshed, "generation") != new_generation
                        or not _same(_field(refreshed, "session"), replacement_session)
                        or _field(refreshed, "principal") != principal
                        or any(not _same(_field(refreshed, name), _field(new_assignment, name))
                               for name in ("scope", "role", "pins", "history", "resource_adoptions"))):
                    raise ManagerContinuityError("delivered context assignment is stale")
                new_assignment = refreshed
                result["assignment"] = refreshed
                result["recovery"]["assignment_ref"] = _ref(refreshed)
            if context.get("generation") is not None and context.get("generation") != new_generation:
                raise ManagerContinuityError("delivered context generation is stale")
            result["current_context"] = context
        except Exception as exc:
            result.update({"status": "recoverable", "outcome": "partial",
                           "error": {"code": "current_context_delivery_failed", "message": str(exc)}})
            return result

        for callback, name in ((readiness, "readiness"), (operational_help, "operational_help")):
            if callback is None:
                continue
            try:
                value = _mapping(_call(callback, new_assignment, result["current_context"]), name)
            except Exception as exc:
                result.update({"status": "recoverable", "outcome": "partial",
                               "error": {"code": name + "_failed", "message": str(exc)}})
                return result
            result[name] = value
            if name == "readiness" and value.get("ready") is False:
                result.update({"status": "recoverable", "outcome": "partial",
                               "error": {"code": "replacement_not_ready", "message": "current role readiness is not ready"}})
                return result

        if restart is not None:
            try:
                result["restart"] = _mapping(_call(restart, new_assignment, result["current_context"]), "restart")
            except Exception as exc:
                result.update({"status": "recoverable", "outcome": "partial",
                               "error": {"code": "replacement_restart_failed", "message": str(exc)}})
                return result
        result["status"] = "ready"
        return result

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
