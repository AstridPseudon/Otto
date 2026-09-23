"""Pure operating-brief schema, diff and render helpers.

This module is an additive preparation seam.  It validates and renders caller
supplied values, but it does not authenticate a user, read a live owner graph,
or schedule a callback.  ``OperatingBriefAuthoringAdapter`` only composes
these values with already-injected owner ports; authentication, persistence,
CAS and retirement remain in those owner ports.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence, Tuple


SCHEMA_REVISION = "otto.operating-brief.v1"
SNAPSHOT_SCHEMA_REVISION = "otto.operating-snapshot.v1"
_ROLES = frozenset({"orchestrator", "manager"})
_USER_FIELDS = ("mandate", "user_constraints")
_AGENT_FIELDS = ("priorities", "operational_constraints", "continuation", "links")


class OperatingBriefError(ValueError):
    """A brief, diff or supplied snapshot violates the additive contract."""


def _json_copy(value: Any, field: str = "value") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise OperatingBriefError(f"{field} must be JSON-compatible") from exc


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not allow_empty and not value.strip()):
        requirement = "text" if allow_empty else "non-blank text"
        raise OperatingBriefError(f"{field} must be {requirement}")
    return value if allow_empty else value.strip()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatingBriefError(f"{field} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise OperatingBriefError(f"{field} keys must be text")
    return _json_copy(dict(value), field)


def _string_list(value: Any, field: str) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OperatingBriefError(f"{field} must be a list of text")
    return tuple(_text(item, f"{field}[{index}]") for index, item in enumerate(value))


def _mapping_list(value: Any, field: str) -> Tuple[dict[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OperatingBriefError(f"{field} must be a list of objects")
    return tuple(_mapping(item, f"{field}[{index}]") for index, item in enumerate(value))


def _record_list(value: Any, field: str) -> Tuple[dict[str, Any], ...]:
    """Validate a bounded list of caller-supplied record objects."""

    return _mapping_list(value, field)


def _reference_identity(value: Any, field: str) -> tuple[tuple[str, Any], ...]:
    """Return the supplied canonical identity without trusting extra fields."""

    reference = _mapping(value, field)
    _text(reference.get("id"), f"{field}.id")
    return tuple((key, reference[key]) for key in ("authority", "kind", "id", "revision") if key in reference)


def _reference_matches(project_ref: Any, active_ref: Any, field: str) -> bool:
    """Match an observed ref against an explicitly supplied owner ref.

    The active ref is the caller's scope fence. Extra observed metadata is
    permitted, but every identity field present in that fence must match.
    """

    observed = dict(_reference_identity(project_ref, field))
    expected = dict(_reference_identity(active_ref, "active_manager_refs[]"))
    return all(observed.get(key) == value for key, value in expected.items())


def _priority_list(value: Any) -> Tuple[dict[str, Any], ...]:
    items = _mapping_list(value, "priorities")
    normalized = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        item_id = _text(item.get("id", f"priority-{index}"), f"priorities[{index}].id")
        if item_id in seen:
            raise OperatingBriefError("priorities must have unique ids")
        seen.add(item_id)
        text = _text(item.get("text", item.get("title")), f"priorities[{index}].text")
        status = _text(item.get("status", "pending"), f"priorities[{index}].status")
        normalized.append({"id": item_id, "text": text, "status": status, **{key: value for key, value in item.items() if key not in {"id", "text", "title", "status"}}})
    return tuple(normalized)


@dataclass(frozen=True)
class OperatingBrief:
    """The optional user brief plus agent-maintained operational fields."""

    role: str
    mandate: str
    user_constraints: Tuple[str, ...]
    priorities: Tuple[dict[str, Any], ...]
    operational_constraints: Tuple[str, ...]
    continuation: Optional[dict[str, Any]]
    links: Tuple[dict[str, Any], ...]
    revision: str = "initial"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, role: Optional[str] = None) -> "OperatingBrief":
        raw = _mapping(value, "brief")
        unknown = set(raw).difference({"schema_revision", "role", "mandate", "user_constraints", "priorities", "operational_constraints", "continuation", "links", "revision"})
        if unknown:
            raise OperatingBriefError("unknown brief fields: " + ", ".join(sorted(unknown)))
        declared_role = None if raw.get("role") is None else _text(raw.get("role"), "role").lower()
        requested_role = None if role is None else _text(role, "role").lower()
        if declared_role is not None and requested_role is not None and declared_role != requested_role:
            raise OperatingBriefError("brief role does not match the requested role")
        selected_role = requested_role or declared_role
        if selected_role is None:
            raise OperatingBriefError("role must be orchestrator or manager")
        if selected_role not in _ROLES:
            raise OperatingBriefError("role must be orchestrator or manager")
        schema = raw.get("schema_revision", SCHEMA_REVISION)
        if schema != SCHEMA_REVISION:
            raise OperatingBriefError("brief schema_revision is unsupported")
        continuation = raw.get("continuation")
        if continuation is not None:
            continuation = _mapping(continuation, "continuation")
        return cls(
            selected_role,
            _text(raw.get("mandate", ""), "mandate", allow_empty=True),
            _string_list(raw.get("user_constraints", ()), "user_constraints"),
            _priority_list(raw.get("priorities", ())),
            _string_list(raw.get("operational_constraints", ()), "operational_constraints"),
            continuation,
            _mapping_list(raw.get("links", ()), "links"),
            _text(raw.get("revision", "initial"), "revision"),
        )

    @classmethod
    def empty(cls, role: str, *, revision: str = "absent") -> "OperatingBrief":
        return cls.from_mapping({"schema_revision": SCHEMA_REVISION, "role": role, "revision": revision})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_revision": SCHEMA_REVISION,
            "role": self.role,
            "mandate": self.mandate,
            "user_constraints": list(self.user_constraints),
            "priorities": [_json_copy(item) for item in self.priorities],
            "operational_constraints": list(self.operational_constraints),
            "continuation": None if self.continuation is None else _json_copy(self.continuation),
            "links": [_json_copy(item) for item in self.links],
            "revision": self.revision,
        }


def brief_diff(base: OperatingBrief | Mapping[str, Any], proposed: OperatingBrief | Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable field diff without treating proposals as acceptance."""

    left = base if isinstance(base, OperatingBrief) else OperatingBrief.from_mapping(base)
    right = proposed if isinstance(proposed, OperatingBrief) else OperatingBrief.from_mapping(proposed, role=left.role)
    if left.role != right.role:
        raise OperatingBriefError("brief role cannot change")
    before, after = left.to_dict(), right.to_dict()
    changes = {field: {"before": before[field], "after": after[field]} for field in (*_USER_FIELDS, *_AGENT_FIELDS) if before[field] != after[field]}
    user_changes = {field: value for field, value in changes.items() if field in _USER_FIELDS}
    agent_changes = {field: value for field, value in changes.items() if field in _AGENT_FIELDS}
    return {
        "schema_revision": "otto.operating-brief.diff.v1",
        "role": left.role,
        "base_revision": left.revision,
        "proposed_revision": right.revision,
        "changes": changes,
        "user_changes": user_changes,
        "agent_changes": agent_changes,
        "requires_user_authority": bool(user_changes),
        "proposal_only": True,
        "diff_sha256": _digest({"role": left.role, "base_revision": left.revision, "proposed_revision": right.revision, "changes": changes}),
    }


def compose_owner_snapshot(
    *,
    projects: Sequence[Mapping[str, Any]],
    active_manager_refs: Sequence[Mapping[str, Any]],
    recent_completions: Sequence[Mapping[str, Any]] = (),
    returned_results: Sequence[Mapping[str, Any]] = (),
    blockers: Sequence[Mapping[str, Any]] = (),
    as_of: str,
    coverage_cursor: Optional[str] = None,
) -> dict[str, Any]:
    """Compose a bounded snapshot from explicit owner-shaped inputs.

    Ownership is supplied by the caller; this function never infers it from
    names, chat proximity or a global project list. Closed projects leave the
    active view but remain available in ``closures`` for history.
    """

    observed_at = _text(as_of, "as_of")
    active_refs = _record_list(active_manager_refs, "active_manager_refs")
    manager_keys = tuple(active_refs)
    project_records = _record_list(projects, "projects")
    active, closures = [], []
    for index, project in enumerate(project_records):
        owner_refs = [
            ("manager_ref", project.get("manager_ref")),
            ("assignment_ref", project.get("assignment_ref")),
        ]
        owner_refs = [(name, value) for name, value in owner_refs if value is not None]
        if not owner_refs:
            continue
        if not any(_reference_matches(value, active_ref, f"projects[{index}].{name}") for name, value in owner_refs for active_ref in manager_keys):
            continue
        lifecycle = _text(project.get("lifecycle", "pending"), f"projects[{index}].lifecycle").lower()
        if lifecycle in {"closed", "completed", "withdrawn"}:
            closures.append(project)
        else:
            active.append(project)
    completion_records = _record_list(recent_completions, "recent_completions")
    returned_records = _record_list(returned_results, "returned_results")
    blocker_records = _record_list(blockers, "blockers")
    body = {
        "schema_revision": SNAPSHOT_SCHEMA_REVISION,
        "as_of": observed_at,
        "coverage_cursor": None if coverage_cursor is None else _text(coverage_cursor, "coverage_cursor"),
        "active_projects": _json_copy(active),
        "closures": _json_copy(closures),
        "recent_accepted_completions": _json_copy(list(completion_records)),
        "returned_unaccepted_results": _json_copy(list(returned_records)),
        "blockers": _json_copy(list(blocker_records)),
        "active_manager_refs": _json_copy(list(active_refs)),
        "ownership_source": "explicit canonical manager/assignment refs supplied by caller",
    }
    body["snapshot_sha256"] = _digest(body)
    return body


def render_operating_brief(
    *,
    role: str,
    role_instructions: str,
    project_state: Mapping[str, Any],
    brief: Optional[OperatingBrief | Mapping[str, Any]] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    edit_recipe: Optional[Mapping[str, Any]] = None,
    as_of: str,
) -> dict[str, Any]:
    """Render a deterministic inline envelope with honest freshness metadata."""

    role_value = OperatingBrief.empty(role).role
    if brief is None:
        selected = OperatingBrief.empty(role_value)
    elif isinstance(brief, OperatingBrief):
        if brief.role != role_value:
            raise OperatingBriefError("brief role does not match the requested role")
        selected = brief
    else:
        selected = OperatingBrief.from_mapping(brief, role=role_value)
    instructions = _text(role_instructions, "role_instructions", allow_empty=True)
    state = _mapping(project_state, "project_state")
    rendered = {
        "schema_revision": "otto.operating-brief.render.v1",
        "role": selected.role,
        "brief_status": "absent_fallback" if brief is None else "present",
        "brief": selected.to_dict(),
        "role_instructions": instructions,
        "project_state": state,
        "snapshot": None if snapshot is None else _mapping(snapshot, "snapshot"),
        "edit_recipe": None if edit_recipe is None else _mapping(edit_recipe, "edit_recipe"),
        "freshness": {
            "as_of": _text(as_of, "as_of"),
            "source": "caller-supplied owner projection",
            "atomic_pre_delivery": False,
            "entry_refresh_required": True,
        },
    }
    rendered["render_sha256"] = _digest(rendered)
    return _json_copy(rendered)


def json_envelope(value: Mapping[str, Any]) -> str:
    """Materialize one stable pretty JSON envelope for a generic document."""

    _mapping(value, "envelope")
    return json.dumps(_json_copy(dict(value)), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


@dataclass(frozen=True)
class OperatingBriefAuthoringAdapter:
    """Bind an agent-editable brief to the owner's existing semantic handler.

    The adapter deliberately receives the owner ``batches`` and ``lifecycle``
    ports from the caller.  It neither discovers those ports nor creates a
    replacement command path.  ``agent_draft`` is pure and rejects protected
    user fields; ``bind_handler`` and ``finish`` delegate to the supplied
    owner objects, where actor, scope, checkout, CAS and retirement checks
    remain enforced.
    """

    role: str
    batches: Any
    lifecycle: Any

    def __post_init__(self) -> None:
        normalized = OperatingBrief.empty(self.role).role
        object.__setattr__(self, "role", normalized)
        if not callable(getattr(self.batches, "lifecycle_handler", None)):
            raise OperatingBriefError("batches.lifecycle_handler must be callable")
        if not callable(getattr(self.lifecycle, "finish", None)):
            raise OperatingBriefError("lifecycle.finish must be callable")

    def agent_draft(
        self,
        *,
        role_instructions: str,
        project_state: Mapping[str, Any],
        brief: Optional[OperatingBrief | Mapping[str, Any]] = None,
        snapshot: Optional[Mapping[str, Any]] = None,
        edit_recipe: Optional[Mapping[str, Any]] = None,
        as_of: str,
    ) -> dict[str, Any]:
        """Render an agent proposal while keeping protected fields empty.

        A user-provided mandate or constraint must enter through the owner
        authority path.  Raising here prevents an agent-facing draft from
        masquerading as an accepted protected-field edit.
        """

        selected = OperatingBrief.empty(self.role) if brief is None else (
            brief if isinstance(brief, OperatingBrief) else OperatingBrief.from_mapping(brief, role=self.role)
        )
        if selected.role != self.role:
            raise OperatingBriefError("brief role does not match the adapter role")
        if selected.mandate or selected.user_constraints:
            raise OperatingBriefError("agent brief cannot edit protected user fields")
        return render_operating_brief(
            role=self.role,
            role_instructions=role_instructions,
            project_state=project_state,
            brief=None if brief is None else selected,
            snapshot=snapshot,
            edit_recipe=edit_recipe,
            as_of=as_of,
        )

    def bind_handler(self, project: Any, *, authoring: Any, handle: Any, request_id: str) -> Any:
        """Return the owner's existing project-sheet semantic handler."""

        return self.batches.lifecycle_handler(
            project,
            authoring=authoring,
            handle=handle,
            request_id=request_id,
        )

    def finish(
        self,
        target: Any,
        *,
        project: Any,
        authoring: Any,
        handle: Any,
        request_id: str,
        **kwargs: Any,
    ) -> Any:
        """Delegate one finish through the owner's shared lifecycle boundary."""

        handler = self.bind_handler(
            project,
            authoring=authoring,
            handle=handle,
            request_id=request_id,
        )
        return self.lifecycle.finish(
            target,
            request_id=request_id,
            handler=handler,
            **kwargs,
        )


__all__ = [
    "OperatingBrief",
    "OperatingBriefAuthoringAdapter",
    "OperatingBriefError",
    "brief_diff",
    "compose_owner_snapshot",
    "json_envelope",
    "render_operating_brief",
]
