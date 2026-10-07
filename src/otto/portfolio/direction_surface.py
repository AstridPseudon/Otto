"""Bounded direction read/authoring projections over canonical D01-D04 ports.

This module is deliberately a facade, not another direction store.  It turns
the owner-issued binding/resolution operations into the read, authoring and
history shapes used by the maintained CLI and manager help surfaces.  Inventory
and caller context are injected by the host so permission scope and unavailable
history remain explicit instead of being guessed from names or sessions.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping, Sequence

from herzchen.contracts import AuthenticatedActor, ResourceRef

from .direction import DirectionBindingError, DirectionResolutionError
from .direction_context import direction_inputs, read_direction_context


SCHEMA = "otto.direction-surface.v1"
MAX_PAGE = 100


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


def _ref(value: Any) -> ResourceRef:
    return value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)


def _identity(value: Any) -> tuple[str, str, str]:
    ref = _ref(value)
    return ref.authority, ref.kind, ref.id


def _same(left: Any, right: Any) -> bool:
    return _identity(left) == _identity(right)


class DirectionSurface:
    """Owner-bound, read-mostly projection for direction operations.

    ``inventory_reader`` returns existing visible subjects (and may include
    completed/retired subjects).  It is never persisted here.  Each item may be
    a ResourceRef, a mapping containing ``subject_ref``/``ref``, or a mapping
    with ``subject_ref`` plus an assignment pin and generation.  The caller's
    host remains responsible for supplying only permitted inventory.
    """

    def __init__(self, directions: Any, *, actor: AuthenticatedActor,
                 context_reader: Callable[..., Any] | None = None,
                 caller_context_reader: Callable[..., Any] | None = None,
                 inventory_reader: Callable[..., Any] | None = None,
                 occurrence_reader: Callable[..., Any] | None = None,
                 allowed_project: Callable[[ResourceRef], bool] | None = None) -> None:
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("direction surface requires an authenticated owner actor")
        self.directions = directions
        self.actor = actor
        self.context_reader = context_reader
        self.caller_context_reader = caller_context_reader
        self.inventory_reader = inventory_reader
        self.occurrence_reader = occurrence_reader
        self.allowed_project = allowed_project

    def _actor(self, actor: Any = None) -> AuthenticatedActor:
        if actor is None:
            return self.actor
        if isinstance(actor, str):
            if actor != self.actor.actor:
                raise PermissionError("direction surface actor is not the current owner")
            return self.actor
        if actor != self.actor:
            raise PermissionError("direction surface actor is not the current owner")
        return actor

    @staticmethod
    def _subject(item: Any) -> tuple[ResourceRef, Mapping[str, Any]]:
        if isinstance(item, ResourceRef):
            return item, {}
        if isinstance(item, Mapping):
            raw = item.get("subject_ref") or item.get("responsibility_ref") or item.get("ref")
            if raw is None:
                raise ValueError("overview subject must include subject_ref or ref")
            return _ref(raw), item
        return _ref(item), {}

    def _project_allowed(self, subject: ResourceRef, row: Mapping[str, Any]) -> bool:
        if self.allowed_project is None:
            return True
        project = row.get("project_ref") or row.get("scope_ref")
        if project is None and subject.kind == "work.project":
            project = subject
        if project is None and subject.kind == "fnd.owner":
            return True
        if project is None:
            # A bounded surface must fail closed when the injected inventory
            # did not supply the project membership needed by the grant.
            return False
        return bool(self.allowed_project(_ref(project)))

    def _pending(self, subject: ResourceRef, error: Exception) -> dict[str, Any]:
        code = getattr(error, "code", None) or "direction_unavailable"
        remedy = getattr(error, "remedy", None) or str(error)
        return {"state": "pending", "subject_ref": subject.to_dict(),
                "error": {"code": code, "message": str(error)},
                "next_action": remedy, "latest_ref": None,
                "scope_adopted_ref": None, "assignment_adopted_ref": None,
                "delivered_ref": None, "delivery_status": "unavailable"}

    def read(self, subject: Any, *, actor: Any = None, assignment_ref: Any = None,
             generation: int | None = None) -> dict[str, Any]:
        """Read identity and effective state without treating latest as adopted."""
        owner = self._actor(actor)
        subject_ref = _ref(subject)
        try:
            identity = dict(self.directions.read(subject_ref, actor=owner))
            if identity.get("document_ref") is None:
                return {"outcome": "read", "schema": SCHEMA, "state": "unbound",
                        **_json(identity), "next_action": "initial-bind an owned direction document",
                        "read_only": True, "dispatch": False}
            resolved = dict(self.directions.resolve(subject_ref, actor=owner,
                                                    assignment_ref=assignment_ref,
                                                    expected_generation=generation)
                            if assignment_ref is not None else
                            self.directions.resolve(subject_ref, actor=owner))
            return {"outcome": "read", "schema": SCHEMA, "state": "effective",
                    **_json(resolved), "read_only": True, "dispatch": False}
        except DirectionResolutionError as exc:
            return {"outcome": "pending", "schema": SCHEMA,
                    **self._pending(subject_ref, exc), "read_only": True,
                    "dispatch": False}
        except DirectionBindingError as exc:
            return {"outcome": "denied", "schema": SCHEMA,
                    "subject_ref": subject_ref.to_dict(),
                    "error": {"code": "direction_read_unavailable", "message": str(exc)},
                    "next_action": "refresh the permitted canonical responsibility or project reference",
                    "read_only": True, "dispatch": False}
        except PermissionError as exc:
            return {"outcome": "denied", "schema": SCHEMA,
                    "subject_ref": subject_ref.to_dict(),
                    "error": {"code": "direction_read_denied", "message": str(exc)},
                    "read_only": True, "dispatch": False}

    def effective_context(self, *, assignment_ref: Any, generation: int,
                          project_ref: Any, task_ref: Any = None,
                          actor: Any = None) -> dict[str, Any]:
        """Return attributed effective scopes plus exact deduplicated inputs."""
        owner = self._actor(actor)
        try:
            if self.context_reader is not None:
                scopes = self.context_reader(assignment_ref=assignment_ref, generation=generation,
                                             project_ref=project_ref, task_ref=task_ref)
            else:
                scopes = read_direction_context(self.directions, actor=owner,
                    assignment_ref=assignment_ref, generation=generation,
                    project_ref=project_ref, task_ref=task_ref)
            scopes = [_json(item) for item in scopes]
            return {"outcome": "read", "schema": SCHEMA, "state": "effective",
                    "assignment_ref": _json(assignment_ref), "generation": generation,
                    "project_ref": _json(project_ref), "task_ref": _json(task_ref),
                    "scopes": scopes, "direction_context": scopes,
                    "inputs": direction_inputs(scopes), "read_only": True,
                    "dispatch": False}
        except (DirectionResolutionError, PermissionError, ValueError) as exc:
            code = getattr(exc, "code", None) or "effective_context_unavailable"
            remedy = getattr(exc, "remedy", None) or str(exc)
            return {"outcome": "pending" if isinstance(exc, DirectionResolutionError) else "denied",
                    "schema": SCHEMA, "state": "pending", "scopes": [], "inputs": [],
                    "error": {"code": code, "message": str(exc)},
                    "next_action": remedy, "read_only": True, "dispatch": False}

    def whoami(self, *, caller_binding: Any = None, actor: Any = None) -> dict[str, Any]:
        """Read trusted caller context; never resolve identity from a name alone."""
        self._actor(actor)
        if self.caller_context_reader is None or caller_binding is None:
            return {"outcome": "unavailable", "schema": SCHEMA, "state": "unbound",
                    "caller_context": None, "read_only": True, "dispatch": False,
                    "error": {"code": "caller_context_unavailable",
                              "message": "a trusted host caller binding is required"},
                    "next_action": "establish a supported host identity binding; do not set an ID manually"}
        try:
            context = _json(self.caller_context_reader(caller_binding))
            return {"outcome": "read", "schema": SCHEMA, "state": "bound",
                    "caller_context": context, "read_only": True, "dispatch": False}
        except PermissionError as exc:
            return {"outcome": "denied", "schema": SCHEMA, "state": "unbound",
                    "caller_context": None, "error": {"code": "caller_context_denied", "message": str(exc)},
                    "next_action": "refresh the trusted host binding", "read_only": True,
                    "dispatch": False}

    def initial_bind(self, subject: Any, document_ref: Any, *, logical_request_key: str,
                     actor: Any = None) -> dict[str, Any]:
        owner = self._actor(actor)
        return {"outcome": "bound", "schema": SCHEMA,
                **_json(self.directions.bind(subject, document_ref, actor=owner,
                                              logical_request_key=logical_request_key)),
                "read_only": False, "dispatch": False}

    def draft(self, subject: Any, content: Mapping[str, Any], *, logical_request_key: str,
              expected_revision: str | None = None, actor: Any = None) -> dict[str, Any]:
        owner = self._actor(actor)
        return {"schema": SCHEMA, **_json(self.directions.save_draft(
            subject, content, actor=owner, logical_request_key=logical_request_key,
            expected_revision=expected_revision)), "read_only": False, "dispatch": False}

    save_draft = draft

    def update(self, subject: Any, revision_ref: Any = None, *, logical_request_key: str,
               content: Mapping[str, Any] | None = None, expected_binding_ref: Any = None,
               expected_revision: str | None = None, assignment_ref: Any = None,
               expected_generation: int | None = None, assignment_resources: Any = None,
               assignment_actor: Any = None, expected_assignment_guard_ref: Any = None,
               actor: Any = None) -> dict[str, Any]:
        owner = self._actor(actor)
        return {"schema": SCHEMA, **_json(self.directions.update(
            subject, revision_ref, actor=owner, expected_binding_ref=expected_binding_ref,
            logical_request_key=logical_request_key, content=content,
            expected_revision=expected_revision, assignment_ref=assignment_ref,
            expected_generation=expected_generation, assignment_resources=assignment_resources,
            assignment_actor=assignment_actor, expected_assignment_guard_ref=expected_assignment_guard_ref)),
                "read_only": False, "dispatch": False}

    update_direction = update

    def history(self, subject: Any, *, actor: Any = None,
                occurrence_reader: Callable[..., Any] | None = None) -> dict[str, Any]:
        owner = self._actor(actor)
        result = {"schema": SCHEMA, **_json(self.directions.history(subject, actor=owner)),
                  "read_only": True, "dispatch": False}
        occurrence_reader = occurrence_reader or self.occurrence_reader
        if occurrence_reader is None:
            result["occurrence_evidence"] = []
            result["history_limitations"] = ["delivered occurrence history is unavailable from the supplied owner reader"]
            return result
        try:
            occurrences = occurrence_reader(subject_ref=_ref(subject), actor=owner)
            result["occurrence_evidence"] = _json(occurrences or [])
            result["history_limitations"] = []
        except PermissionError:
            result["occurrence_evidence"] = None
            result["history_limitations"] = ["delivered occurrence history is unavailable under current permission scope"]
        return result

    read_history = history

    @staticmethod
    def _cursor(cursor: str | None, digest: str) -> int:
        if cursor is None:
            return 0
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
            if value.get("digest") != digest or not isinstance(value.get("offset"), int):
                raise ValueError
            return value["offset"]
        except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError, binascii.Error):
            raise ValueError("overview cursor is stale or malformed")

    @staticmethod
    def _next(offset: int, digest: str) -> str:
        return base64.urlsafe_b64encode(json.dumps({"digest": digest, "offset": offset}, separators=(",", ":")).encode()).decode()

    def overview(self, subjects: Sequence[Any] | None = None, *, actor: Any = None,
                 limit: int = 50, cursor: str | None = None,
                 include_history: bool = True) -> dict[str, Any]:
        """Read a bounded derived overview over supplied canonical inventory.

        Completed/retired rows are included when the existing inventory reader
        supplies them.  The surface does not manufacture a roster or scan
        native sessions.
        """
        self._actor(actor)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE}")
        raw = self.inventory_reader(actor=self.actor) if subjects is None and self.inventory_reader else (subjects or ())
        if isinstance(raw, Mapping):
            raw = raw.get("subjects", raw.get("items", ()))
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            raise ValueError("overview inventory must be a finite sequence")
        rows = []
        for item in raw:
            subject, metadata = self._subject(item)
            if not self._project_allowed(subject, metadata):
                continue
            state = self.read(subject, actor=self.actor,
                              assignment_ref=metadata.get("assignment_ref"),
                              generation=metadata.get("generation"))
            row = {"subject_ref": subject.to_dict(),
                   "kind": subject.kind,
                   "status": metadata.get("status", metadata.get("lifecycle", "active")),
                   "historical": metadata.get("status", metadata.get("lifecycle")) in {"completed", "retired", "closed", "done"},
                   "direction": state}
            if include_history and state.get("outcome") in {"read", "pending"}:
                row["history_available"] = state.get("state") == "effective"
            rows.append(row)
        rows.sort(key=lambda row: json.dumps(row["subject_ref"], sort_keys=True))
        digest = hashlib.sha256(json.dumps(
            [row["subject_ref"] for row in rows], sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        offset = self._cursor(cursor, digest)
        page = rows[offset:offset + limit]
        next_cursor = self._next(offset + limit, digest) if offset + limit < len(rows) else None
        return {"outcome": "listed", "schema": SCHEMA, "items": page, "count": len(page),
                "total": len(rows), "pagination": {"offset": offset, "limit": limit,
                "has_more": next_cursor is not None, "cursor": next_cursor},
                "inventory_basis": "existing owner-provided canonical subjects; no roster created",
                "historical_coverage": "included when supplied by the existing inventory reader",
                "read_only": True, "dispatch": False, "launch": False}


__all__ = ["DirectionSurface", "MAX_PAGE", "SCHEMA"]
