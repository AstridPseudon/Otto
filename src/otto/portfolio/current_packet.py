"""Pure current-action packet selection for the ORC-03 intake boundary.

The packet is a derived view over caller-supplied mandate, history, owner refs,
and plan provenance.  It does not persist a queue, dispatch a worker, or grant
execution authority.  Canonical owner state and the existing scheduler remain
outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence, Tuple


class CurrentPacketError(ValueError):
    """A current-packet input violates the narrow ORC-03 contract."""


_TRUSTED_SOURCES = frozenset({"user", "root_transport", "owner"})
_ACTIVE_STATES = frozenset({"active", "execute"})


def _copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise CurrentPacketError("packet inputs must be JSON-compatible") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CurrentPacketError(f"{field} must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CurrentPacketError(f"{field} must be a reference object")
    result = _copy(dict(value))
    if not result.get("id"):
        raise CurrentPacketError(f"{field}.id is required")
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SteeringDirective:
    """One immutable mandate observation, including supersession provenance."""

    revision: str
    sequence: int
    state: str
    mode: str
    effect_class: str
    text: str
    source: str
    trusted: bool
    supersedes: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SteeringDirective":
        if not isinstance(value, Mapping):
            raise CurrentPacketError("steering directives must be objects")
        revision = _text(value.get("revision"), "steering.revision")
        sequence = value.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise CurrentPacketError("steering.sequence must be a non-negative integer")
        state = _text(value.get("state"), "steering.state").lower()
        mode = _text(value.get("mode"), "steering.mode").lower()
        effect_class = _text(value.get("effect_class"), "steering.effect_class").lower()
        text = _text(value.get("text"), "steering.text")
        source = _text(value.get("source"), "steering.source").lower()
        trusted = value.get("trusted")
        if not isinstance(trusted, bool):
            raise CurrentPacketError("steering.trusted must be boolean")
        supersedes_value = value.get("supersedes", ())
        if isinstance(supersedes_value, str):
            supersedes = (supersedes_value,)
        elif isinstance(supersedes_value, Sequence):
            supersedes = tuple(_text(item, "steering.supersedes") for item in supersedes_value)
        else:
            raise CurrentPacketError("steering.supersedes must be text or a list")
        return cls(revision, sequence, state, mode, effect_class, text, source, trusted, supersedes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_trusted(self) -> bool:
        return self.trusted and self.source in _TRUSTED_SOURCES

    @property
    def is_current_candidate(self) -> bool:
        return self.is_trusted and self.state in _ACTIVE_STATES and self.mode == "execution"


@dataclass(frozen=True)
class PlannerProvenance:
    """Observed planner identity and immutable plan artifact reference."""

    native_id: str
    host: str
    requested_model: str
    observed_model: str
    requested_reasoning: str
    observed_reasoning: str
    plan_path: str
    plan_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PlannerProvenance":
        if not isinstance(value, Mapping):
            raise CurrentPacketError("planner provenance must be an object")
        fields = ("native_id", "host", "requested_model", "observed_model", "requested_reasoning", "observed_reasoning", "plan_path", "plan_sha256")
        values = {field: _text(value.get(field), f"planner.{field}") for field in fields}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _history(directives: Sequence[Mapping[str, Any]]) -> Tuple[SteeringDirective, ...]:
    values = tuple(SteeringDirective.from_mapping(item) for item in directives)
    if not values:
        raise CurrentPacketError("at least one steering observation is required")
    revisions = [item.revision for item in values]
    if len(set(revisions)) != len(revisions):
        raise CurrentPacketError("steering revisions must be unique")
    return tuple(sorted(values, key=lambda item: item.sequence))


def select_current_action_packet(
    *,
    request: Mapping[str, Any],
    context: Mapping[str, Any],
    source: Mapping[str, Any],
    constraints: Sequence[str],
    acceptance: Sequence[str],
    uncertainties: Sequence[str],
    steering_history: Sequence[Mapping[str, Any]],
    owner_ref: Mapping[str, Any],
    task_ref: Mapping[str, Any],
    assignment_ref: Mapping[str, Any],
    generation: int,
    planner: Mapping[str, Any],
    worker_observation: Mapping[str, Any],
    next_action: Mapping[str, Any],
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    """Select one trusted active mandate and render a non-dispatching packet."""

    if not isinstance(request, Mapping) or not request:
        raise CurrentPacketError("request must be a non-empty object")
    if not isinstance(context, Mapping) or not context:
        raise CurrentPacketError("context must be a non-empty object")
    if not isinstance(source, Mapping) or not source:
        raise CurrentPacketError("source must be a non-empty object")
    if not isinstance(next_action, Mapping) or not next_action:
        raise CurrentPacketError("next_action must be a non-empty object")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise CurrentPacketError("generation must be a positive integer")
    for name, values in (("constraints", constraints), ("acceptance", acceptance), ("uncertainties", uncertainties)):
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise CurrentPacketError(f"{name} must be a sequence")
        for item in values:
            _text(item, name)
    history = _history(steering_history)
    candidates = tuple(item for item in history if item.is_current_candidate)
    if not candidates:
        raise CurrentPacketError("no trusted active execution steering directive")
    selected = max(candidates, key=lambda item: item.sequence)
    previous = tuple(item for item in history if item.sequence < selected.sequence)
    if previous and not set(item.revision for item in previous).intersection(selected.supersedes):
        raise CurrentPacketError("active steering must name the historical revision it supersedes")
    if not selected.supersedes and previous:
        raise CurrentPacketError("active steering must include supersession provenance")
    planner_value = PlannerProvenance.from_mapping(planner)
    owner = _ref(owner_ref, "owner_ref")
    task = _ref(task_ref, "task_ref")
    assignment = _ref(assignment_ref, "assignment_ref")
    worker = _copy(dict(worker_observation))
    for field in ("native_id", "actual_model", "actual_reasoning"):
        _text(worker.get(field), f"worker_observation.{field}")
    worker["role"] = "worker"
    worker["dispatch"] = False
    worker["launch"] = False
    budget_value = _copy(dict(budgets))
    body = {
        "schema": "otto.orchestrator.orc03.current_action_packet.v1",
        "source": _copy(dict(source)),
        "request": _copy(dict(request)),
        "context": _copy(dict(context)),
        "constraints": list(constraints),
        "acceptance": list(acceptance),
        "uncertainties": list(uncertainties),
        "selected_mandate": selected.to_dict(),
        "supersession_source": {"selected_revision": selected.revision, "superseded_revisions": list(selected.supersedes)},
        "steering_history": [item.to_dict() for item in history],
        "owner_ref": owner,
        "task_ref": task,
        "assignment_ref": assignment,
        "generation": generation,
        "role": "planner",
        "mode": "planning",
        "effect_class": "discovery",
        "worker_observation": worker,
        "budgets": budget_value,
        "next_action": _copy(dict(next_action)),
        "planner_handoff": {
            "planner": planner_value.to_dict(),
            "auto_dispatch": False,
            "worker_dispatch": False,
            "execution_authority": False,
            "report_only": True,
        },
    }
    body["packet_sha256"] = _digest(body)
    body["idempotency_key"] = "orc03-current-action-" + body["packet_sha256"]
    return body


def render_planner_handoff(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact Astra leaf handoff without granting execution."""

    if not isinstance(packet, Mapping) or packet.get("schema") != "otto.orchestrator.orc03.current_action_packet.v1":
        raise CurrentPacketError("packet schema is not an ORC-03 current action packet")
    planner_handoff = packet.get("planner_handoff")
    if not isinstance(planner_handoff, Mapping) or planner_handoff.get("auto_dispatch") is not False:
        raise CurrentPacketError("planner handoff must be report-only")
    return {
        "schema": "otto.orchestrator.orc03.astra_planning_handoff.v1",
        "input_packet_sha256": _text(packet.get("packet_sha256"), "packet_sha256"),
        "planner": _copy(dict(planner_handoff["planner"])),
        "selected_mandate": _copy(dict(packet["selected_mandate"])),
        "source": _copy(dict(packet["source"])),
        "constraints": _copy(packet["constraints"]),
        "acceptance": _copy(packet["acceptance"]),
        "uncertainties": _copy(packet["uncertainties"]),
        "owner_ref": _copy(dict(packet["owner_ref"])),
        "task_ref": _copy(dict(packet["task_ref"])),
        "assignment_ref": _copy(dict(packet["assignment_ref"])),
        "generation": packet["generation"],
        "role": "planner",
        "mode": "planning",
        "effect_class": "discovery",
        "auto_dispatch": False,
        "execution_authority": False,
        "next_action": _copy(dict(packet["next_action"])),
    }


__all__ = ["CurrentPacketError", "PlannerProvenance", "SteeringDirective", "render_planner_handoff", "select_current_action_packet"]
