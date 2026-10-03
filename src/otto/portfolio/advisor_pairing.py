"""Identity-fenced manager/project-advisor pairing over owner assignments.

Assignment creation, conversation delivery, and persistence remain owner
operations. This module gives PA01 and PA03 one continuity/staleness seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class AdvisorPairingError(ValueError):
    """A pairing or recipient is not current and cannot be used."""


def _ref(value: Any, field: str) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise AdvisorPairingError(f"{field} must be a reference")
    result = dict(value)
    for key in ("authority", "kind", "id", "revision"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise AdvisorPairingError(f"{field}.{key} must be non-blank")
    return result


def _id(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("id") or value.get("principal")
    return value if isinstance(value, str) else ""


def _active(assignment: Mapping[str, Any]) -> bool:
    status = assignment.get("status", assignment.get("lifecycle", "active"))
    status = getattr(status, "value", status)
    return str(status).lower() in {"active", "assigned", "queued", "running", "in-flight", "reassigned"}


@dataclass(frozen=True)
class AdvisorPairing:
    project_ref: Mapping[str, Any]
    manager_ref: Mapping[str, Any]
    advisor_ref: Mapping[str, Any]
    generation: int
    manager_conversation_ref: Mapping[str, Any]
    advisor_conversation_ref: Mapping[str, Any]
    cursor: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 1:
            raise AdvisorPairingError("generation must be positive")
        for name in ("project_ref", "manager_ref", "advisor_ref", "manager_conversation_ref", "advisor_conversation_ref"):
            _ref(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "otto.project-advisor-pairing.v1",
            "project_ref": dict(self.project_ref),
            "manager_ref": dict(self.manager_ref),
            "advisor_ref": dict(self.advisor_ref),
            "generation": self.generation,
            "manager_conversation_ref": dict(self.manager_conversation_ref),
            "advisor_conversation_ref": dict(self.advisor_conversation_ref),
            "cursor": None if self.cursor is None else dict(self.cursor),
        }


def establish_pairing(
    project_ref: Mapping[str, Any],
    assignments: Sequence[Mapping[str, Any]],
    *,
    manager_conversation_ref: Mapping[str, Any],
    advisor_conversation_ref: Mapping[str, Any],
    cursor: Mapping[str, Any] | None = None,
) -> AdvisorPairing:
    """Select exactly one current advisor for exactly one current manager."""
    project = _ref(project_ref, "project_ref")
    current = [item for item in assignments if isinstance(item, Mapping) and _active(item)]
    managers = [item for item in current if item.get("role") == "manager"]
    advisors = [item for item in current if item.get("role") == "project_advisor"]
    if len(managers) != 1:
        raise AdvisorPairingError("pairing requires exactly one active manager")
    if len(advisors) != 1:
        raise AdvisorPairingError("pairing requires exactly one active project advisor")
    manager, advisor = managers[0], advisors[0]
    manager_ref = _ref(manager.get("ref", manager.get("assignment_ref")), "manager_ref")
    advisor_ref = _ref(advisor.get("ref", advisor.get("assignment_ref")), "advisor_ref")
    if _ref(advisor.get("scope", project), "advisor.scope").get("id") != project["id"]:
        raise AdvisorPairingError("advisor assignment belongs to another project")
    if _id(advisor.get("manager")) not in {manager_ref["id"], _id(manager.get("principal"))}:
        raise AdvisorPairingError("advisor assignment is not paired to the current manager")
    generation = advisor.get("generation")
    if generation != manager.get("generation") or isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise AdvisorPairingError("manager and advisor generations differ")
    return AdvisorPairing(
        project, manager_ref, advisor_ref, generation,
        _ref(manager_conversation_ref, "manager_conversation_ref"),
        _ref(advisor_conversation_ref, "advisor_conversation_ref"),
        None if cursor is None else dict(cursor),
    )


def validate_recipient(pairing: AdvisorPairing, *, role: str, assignment_ref: Mapping[str, Any], generation: int) -> None:
    """Reject wrong-role, stale-generation, and stale-assignment deliveries."""
    expected = pairing.advisor_ref if role == "project_advisor" else pairing.manager_ref if role == "manager" else None
    if expected is None or _ref(assignment_ref, "assignment_ref") != dict(expected):
        raise AdvisorPairingError("recipient is not current for this pairing")
    if generation != pairing.generation:
        raise AdvisorPairingError("recipient generation is stale")


def introductions(pairing: AdvisorPairing) -> dict[str, dict[str, Any]]:
    """Return bounded introductions without granting authority."""
    base = {
        "pairing": pairing.to_dict(),
        "continuity": "resume the pinned conversation; refresh current owner state before acting",
    }
    return {
        "manager": {
            **base,
            "recipient": dict(pairing.manager_conversation_ref),
            "message": "Your project advisor is paired to this project for questions and follow-up.",
        },
        "project_advisor": {
            **base,
            "recipient": dict(pairing.advisor_conversation_ref),
            "message": "Advise this manager only within the pinned project mandate and reject stale pairing state.",
        },
    }


__all__ = ["AdvisorPairing", "AdvisorPairingError", "establish_pairing", "introductions", "validate_recipient"]
