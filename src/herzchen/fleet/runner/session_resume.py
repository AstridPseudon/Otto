"""Exact, product-neutral fence for resuming an asking execution session."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class AskingSessionMismatch(ValueError):
    """The proposed resume binding is incomplete, invalid, or no longer current."""


def _validated_binding(value: Any, label: str) -> tuple[tuple[str, str, str, str], int, str, str]:
    if not isinstance(value, Mapping):
        raise AskingSessionMismatch(f"{label} asking binding must be a mapping")
    assignment = value.get("assignment_ref")
    if not isinstance(assignment, Mapping):
        raise AskingSessionMismatch(f"{label} assignment_ref must be a mapping")
    assignment_fields = ("authority", "kind", "id", "revision")
    if any(not isinstance(assignment.get(key), str) or not assignment[key].strip() for key in assignment_fields):
        raise AskingSessionMismatch(f"{label} assignment_ref must include authority, kind, id, and revision")
    generation = value.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise AskingSessionMismatch(f"{label} generation must be a positive integer")
    native_session_id = value.get("native_session_id")
    if not isinstance(native_session_id, str) or not native_session_id.strip():
        raise AskingSessionMismatch(f"{label} native_session_id must be non-blank")
    schedule_id = value.get("schedule_id")
    if not isinstance(schedule_id, str) or not schedule_id.strip():
        raise AskingSessionMismatch(f"{label} schedule_id must be non-blank")
    return tuple(assignment[key] for key in assignment_fields), generation, native_session_id, schedule_id


def require_asking_session(asking: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    """Require an exact assignment revision, generation, session, and schedule match.

    A task reference alone cannot satisfy this fence. Both mappings must carry
    all four binding dimensions, with an explicitly pinned assignment revision.
    """
    expected = _validated_binding(asking, "asking")
    proposed = _validated_binding(candidate, "candidate")
    if proposed != expected:
        raise AskingSessionMismatch("resume candidate does not match the exact asking assignment session and generation")
