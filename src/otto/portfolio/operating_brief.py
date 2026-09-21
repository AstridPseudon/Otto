"""Pure operating-brief schema, diff and render helpers.

This module is an additive preparation seam.  It validates and renders caller
supplied values, but it does not authenticate a user, write a document,
associate a record, read a live owner graph, or schedule a callback.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


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
    return _json_copy(dict(value), field)


def _string_list(value: Any, field: str) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OperatingBriefError(f"{field} must be a list of text")
    return tuple(_text(item, f"{field}[{index}]") for index, item in enumerate(value))


def _mapping_list(value: Any, field: str) -> Tuple[dict[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OperatingBriefError(f"{field} must be a list of objects")
    return tuple(_mapping(item, f"{field}[{index}]") for index, item in enumerate(value))


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
        selected_role = _text(role or raw.get("role"), "role").lower()
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
    if isinstance(projects, (str, bytes)) or not isinstance(projects, Sequence):
        raise OperatingBriefError("projects must be a list")
    if isinstance(active_manager_refs, (str, bytes)) or not isinstance(active_manager_refs, Sequence):
        raise OperatingBriefError("active_manager_refs must be a list")
    manager_keys = {json.dumps(_mapping(item, "active_manager_refs[]"), sort_keys=True, separators=(",", ":")) for item in active_manager_refs}
    active, closures = [], []
    for index, raw in enumerate(projects):
        project = _mapping(raw, f"projects[{index}]")
        owner_ref = project.get("manager_ref") or project.get("assignment_ref")
        if owner_ref is None or json.dumps(_mapping(owner_ref, f"projects[{index}].manager_ref"), sort_keys=True, separators=(",", ":")) not in manager_keys:
            continue
        lifecycle = str(project.get("lifecycle", "pending")).lower()
        if lifecycle in {"closed", "completed", "withdrawn"}:
            closures.append(project)
        else:
            active.append(project)
    body = {
        "schema_revision": SNAPSHOT_SCHEMA_REVISION,
        "as_of": observed_at,
        "coverage_cursor": None if coverage_cursor is None else _text(coverage_cursor, "coverage_cursor"),
        "active_projects": _json_copy(active),
        "closures": _json_copy(closures),
        "recent_accepted_completions": _json_copy(list(recent_completions)),
        "returned_unaccepted_results": _json_copy(list(returned_results)),
        "blockers": _json_copy(list(blockers)),
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

    selected = OperatingBrief.empty(role) if brief is None else (brief if isinstance(brief, OperatingBrief) else OperatingBrief.from_mapping(brief, role=role))
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


__all__ = ["OperatingBrief", "OperatingBriefError", "brief_diff", "compose_owner_snapshot", "json_envelope", "render_operating_brief"]
