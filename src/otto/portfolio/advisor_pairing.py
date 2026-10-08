"""Identity-fenced manager/project-advisor pairing over owner assignments.

Assignment creation, conversation delivery, and persistence remain owner or
host operations. This module gives PA01 and PA03 one continuity/staleness seam
without creating a second relationship ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence


class AdvisorPairingError(ValueError):
    """A pairing or recipient is not current and cannot be used."""


def _json(value: Any, field: str) -> Any:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise AdvisorPairingError(f"{field} must contain JSON values") from exc


def _mapping(value: Any, field: str) -> dict[str, Any]:
    value = _json(value, field)
    if not isinstance(value, Mapping):
        raise AdvisorPairingError(f"{field} must be an object")
    return dict(value)


def _field(assignment: Mapping[str, Any], name: str, default: Any = None) -> Any:
    if name in assignment:
        return assignment[name]
    payload = assignment.get("payload")
    return payload.get(name, default) if isinstance(payload, Mapping) else default


def _ref(value: Any, field: str) -> dict[str, Any]:
    result = _mapping(value, field)
    for key in ("authority", "kind", "id", "revision"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise AdvisorPairingError(f"{field}.{key} must be non-blank")
    return {key: result[key] for key in ("authority", "kind", "id", "revision")}


def _conversation(value: Any, field: str) -> dict[str, Any]:
    """Accept an exact owner ref or an unambiguous host conversation binding."""

    result = _mapping(value, field)
    if all(isinstance(result.get(key), str) and result[key].strip()
           for key in ("authority", "kind", "id", "revision")):
        return result
    aliases = ("native_id", "physical_session_id", "conversation_id", "thread_id", "session_id", "id")
    identities = [result[key].strip() for key in aliases
                  if isinstance(result.get(key), str) and result[key].strip()]
    if not identities:
        raise AdvisorPairingError(f"{field} must identify an existing conversation")
    if len(set(identities)) != 1:
        raise AdvisorPairingError(f"{field} conversation aliases conflict")
    if not isinstance(result.get("host"), str) or not result["host"].strip():
        raise AdvisorPairingError(f"{field}.host must be non-blank")
    return result


def _id(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("id") or value.get("principal")
    return value if isinstance(value, str) else ""


def _generation(assignment: Mapping[str, Any], field: str) -> int:
    value = _field(assignment, "generation")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AdvisorPairingError(f"{field} generation must be positive")
    return value


def _active(assignment: Mapping[str, Any]) -> bool:
    status = _field(assignment, "status", _field(assignment, "lifecycle", "active"))
    status = getattr(status, "value", status)
    return str(status).lower() in {"active", "assigned", "queued", "running", "in-flight", "reassigned"}


def _scope(assignment: Mapping[str, Any], field: str) -> dict[str, Any]:
    return _ref(_field(assignment, "scope_ref", _field(assignment, "scope")), field)


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return value["authority"], value["kind"], value["id"]


@dataclass(frozen=True)
class AdvisorPairing:
    project_ref: Mapping[str, Any]
    manager_ref: Mapping[str, Any]
    advisor_ref: Mapping[str, Any]
    # ``generation`` remains the advisor-generation compatibility field from
    # the initial PA01 draft. Manager generation is independent on handover.
    generation: int
    manager_conversation_ref: Mapping[str, Any]
    advisor_conversation_ref: Mapping[str, Any]
    cursor: Mapping[str, Any] | None = None
    manager_generation: int | None = None

    def __post_init__(self) -> None:
        for name, value in (("generation", self.generation), ("manager_generation", self.manager_generation)):
            if name == "manager_generation" and value is None:
                value = self.generation
                object.__setattr__(self, name, value)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise AdvisorPairingError(f"{name} must be positive")
        for name in ("project_ref", "manager_ref", "advisor_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        for name in ("manager_conversation_ref", "advisor_conversation_ref"):
            object.__setattr__(self, name, _conversation(getattr(self, name), name))
        if self.cursor is not None:
            object.__setattr__(self, "cursor", _mapping(self.cursor, "cursor"))

    @property
    def advisor_generation(self) -> int:
        return self.generation

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "otto.project-advisor-pairing.v1",
            "project_ref": dict(self.project_ref),
            "manager_ref": dict(self.manager_ref),
            "advisor_ref": dict(self.advisor_ref),
            "generation": self.generation,
            "manager_generation": self.manager_generation,
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
    if isinstance(assignments, (str, bytes)) or not isinstance(assignments, Sequence):
        raise AdvisorPairingError("assignments must be a list")
    normalized = [_mapping(item, f"assignments[{index}]") for index, item in enumerate(assignments)]
    current = [item for item in normalized if _active(item)]
    scoped = [item for item in current if _identity(_scope(item, "assignment.scope")) == _identity(project)]
    managers = [item for item in scoped if _field(item, "role") == "manager"]
    advisors = [item for item in scoped if _field(item, "role") == "project_advisor"]
    if len(managers) != 1:
        raise AdvisorPairingError("pairing requires exactly one active manager in the project")
    if len(advisors) != 1:
        raise AdvisorPairingError("pairing requires exactly one active project advisor in the project")
    manager, advisor = managers[0], advisors[0]
    manager_ref = _ref(manager.get("ref") or manager.get("assignment_ref"), "manager_ref")
    advisor_ref = _ref(advisor.get("ref") or advisor.get("assignment_ref"), "advisor_ref")
    manager_principal = _id(_field(manager, "principal"))
    # Canonical assignment projections expose the persisted relationship as
    # ``stored_manager`` while retaining ``manager`` as a legacy principal alias.
    linked_manager = advisor.get("stored_manager")
    if linked_manager is None:
        payload = advisor.get("payload")
        linked_manager = payload.get("manager") if isinstance(payload, Mapping) else advisor.get("manager")
    if _id(linked_manager) not in {manager_ref["id"], manager_principal}:
        raise AdvisorPairingError("advisor assignment is not paired to the current manager")
    return AdvisorPairing(
        project, manager_ref, advisor_ref, _generation(advisor, "advisor"),
        manager_conversation_ref, advisor_conversation_ref, cursor,
        manager_generation=_generation(manager, "manager"),
    )


def validate_recipient(
    pairing: AdvisorPairing,
    *,
    role: str,
    assignment_ref: Mapping[str, Any],
    generation: int,
) -> None:
    """Reject wrong-role, stale-generation, and stale-assignment deliveries."""

    if role == "project_advisor":
        expected_ref, expected_generation = pairing.advisor_ref, pairing.generation
    elif role == "manager":
        expected_ref, expected_generation = pairing.manager_ref, pairing.manager_generation
    else:
        raise AdvisorPairingError("recipient role is not part of this pairing")
    if _ref(assignment_ref, "assignment_ref") != dict(expected_ref):
        raise AdvisorPairingError("recipient is not current for this pairing")
    if isinstance(generation, bool) or generation != expected_generation:
        raise AdvisorPairingError("recipient generation is stale")


def conversation_for(
    pairing: AdvisorPairing,
    *,
    role: str,
    assignment_ref: Mapping[str, Any],
    generation: int,
) -> dict[str, Any]:
    """Return the same pinned conversation only after current-recipient checks."""

    validate_recipient(pairing, role=role, assignment_ref=assignment_ref, generation=generation)
    selected = pairing.advisor_conversation_ref if role == "project_advisor" else pairing.manager_conversation_ref
    return dict(selected)


def introductions(pairing: AdvisorPairing) -> dict[str, dict[str, Any]]:
    """Return bounded introductions with references but no new authority."""

    base = {
        "continuity": "resume the pinned conversation; refresh current owner state before acting",
    }
    return {
        "manager": {
            **base,
            "pairing": pairing.to_dict(),
            "recipient": dict(pairing.manager_conversation_ref),
            "message": (
                f"Your project advisor is {pairing.advisor_ref['id']} for project "
                f"{pairing.project_ref['id']}. Ask it about consequential project uncertainty and "
                "continue independent work while waiting; return concrete conflicting evidence."
            ),
        },
        "project_advisor": {
            **base,
            "pairing": pairing.to_dict(),
            "recipient": dict(pairing.advisor_conversation_ref),
            "message": (
                f"You advise manager assignment {pairing.manager_ref['id']} on project "
                f"{pairing.project_ref['id']}. Inspect underlying work, choose the shortest credible "
                "in-mandate direction, and revise earlier advice when evidence requires it."
            ),
        },
    }


__all__ = [
    "AdvisorPairing", "AdvisorPairingError", "conversation_for",
    "establish_pairing", "introductions", "validate_recipient",
]
