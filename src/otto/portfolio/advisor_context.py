"""Compact project-advisor context and judgment records.

The owner and host remain responsible for reading messages, files, and
persisting decisions.  This module supplies the small, explicit boundary that
lets an advisor start from the real project outcome, inspect the referenced
sources, and return one executable disposition without creating an evidence
store or a second issue ledger.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

from .advisor_pairing import AdvisorPairing


class AdvisorContextError(ValueError):
    """An advisor context or direction is incomplete or out of bounds."""


_DISPOSITIONS = frozenset({"continue", "watch", "correct", "escalate"})
_PROVENANCE = frozenset({"owner", "acceptance", "defect", "tool", "self_imposed", "stale", "unknown"})
_OWNER_ONLY = frozenset({"owner_only", "cross_project", "authority_gap", "uncertain_effect"})
_MAX_ITEMS = 32
_MAX_TEXT = 4000


def _copy(value: Any, field: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError, RecursionError) as exc:
        raise AdvisorContextError(f"{field} must contain JSON values") from exc


def _text(value: Any, field: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise AdvisorContextError(f"{field} must be non-blank text")
    value = value.strip()
    if len(value) > max_length:
        raise AdvisorContextError(f"{field} is too long")
    return value


def _ref(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdvisorContextError(f"{field} must be a reference object")
    result = _copy(dict(value), field)
    for key in ("authority", "kind", "id"):
        _text(result.get(key), f"{field}.{key}", max_length=256)
    if result.get("revision") is not None:
        _text(result["revision"], f"{field}.revision", max_length=256)
    return result


def _items(values: Any, field: str, *, refs: bool = False) -> list[Any]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise AdvisorContextError(f"{field} must be a list")
    if len(values) > _MAX_ITEMS:
        raise AdvisorContextError(f"{field} exceeds the bounded item limit")
    return [_ref(value, f"{field}[{index}]") if refs else _copy(value, f"{field}[{index}]")
            for index, value in enumerate(values)]


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _context_pairing(pairing: AdvisorPairing) -> dict[str, Any]:
    if not isinstance(pairing, AdvisorPairing):
        raise AdvisorContextError("pairing must be an AdvisorPairing")
    return {
        "project_ref": dict(pairing.project_ref),
        "manager_ref": dict(pairing.manager_ref),
        "advisor_ref": dict(pairing.advisor_ref),
        "manager_generation": pairing.manager_generation,
        "advisor_generation": pairing.advisor_generation,
        "manager_conversation_ref": dict(pairing.manager_conversation_ref),
        "advisor_conversation_ref": dict(pairing.advisor_conversation_ref),
    }


def build_advisor_context(
    pairing: AdvisorPairing,
    *,
    goal: Any,
    acceptance_criteria: Sequence[str],
    mandate: Any,
    document_refs: Sequence[Mapping[str, Any]] = (),
    last_inspected: Optional[Mapping[str, Any]] = None,
    open_decisions: Sequence[Mapping[str, Any]] = (),
    question: Optional[str] = None,
    wake_reason: str = "scheduled_check",
    plan_ref: Optional[Mapping[str, Any]] = None,
    status_ref: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Render the bounded pointers an advisor needs for one inspection.

    The returned refs are read instructions, not cached evidence.  A caller
    should read the actual conversation/files through its existing owner/host
    ports and may use ``last_inspected`` to avoid rereading unchanged history.
    """

    identity = _context_pairing(pairing)
    if isinstance(goal, str):
        goal_value: Any = _text(goal, "goal")
    elif isinstance(goal, Mapping) and goal:
        goal_value = _copy(dict(goal), "goal")
    else:
        raise AdvisorContextError("goal must be non-empty text or an object")
    if isinstance(mandate, str):
        mandate_value: Any = _text(mandate, "mandate")
    elif isinstance(mandate, Mapping) and mandate:
        mandate_value = _copy(dict(mandate), "mandate")
    else:
        raise AdvisorContextError("mandate must be non-empty text or an object")
    criteria = [_text(item, f"acceptance_criteria[{index}]")
                for index, item in enumerate(_items(acceptance_criteria, "acceptance_criteria"))]
    documents = _items(document_refs, "document_refs", refs=True)
    decisions = _items(open_decisions, "open_decisions")
    if last_inspected is not None and not isinstance(last_inspected, Mapping):
        raise AdvisorContextError("last_inspected must be an object")
    inspected = {"position": None} if last_inspected is None else _copy(dict(last_inspected), "last_inspected")
    reason = _text(wake_reason, "wake_reason", max_length=128)
    trigger = {"wake_reason": reason}
    if question is not None:
        trigger["question"] = _text(question, "question")
    refs: dict[str, Any] = {
        "documents": documents,
        "manager_conversation": dict(pairing.manager_conversation_ref),
        "advisor_conversation": dict(pairing.advisor_conversation_ref),
    }
    if plan_ref is not None:
        refs["plan"] = _ref(plan_ref, "plan_ref")
    if status_ref is not None:
        refs["status"] = _ref(status_ref, "status_ref")
    body: dict[str, Any] = {
        "schema": "otto.project-advisor-context.v1",
        "pairing": identity,
        "goal": goal_value,
        "acceptance_criteria": criteria,
        "mandate": mandate_value,
        "references": refs,
        "last_inspected": dict(inspected),
        "open_decisions": decisions,
        "trigger": trigger,
        "inspection": {
            "read_actual_messages": True,
            "read_relevant_files": True,
            "read_owner_state": True,
            "missing_delta_fallback": "bounded_direct_read",
        },
        "authority": {
            "can": ["continue", "watch", "correct_within_mandate"],
            "must_escalate": ["owner_only", "cross_project", "authority_gap", "uncertain_effect"],
        },
    }
    body["context_sha256"] = _digest(body)
    return body


def _observation(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise AdvisorContextError("observation must be a non-empty object")
    result = _copy(dict(value), "observation")
    if result.get("evidence") is None:
        raise AdvisorContextError("observation.evidence is required")
    evidence = result["evidence"]
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence) or not evidence:
        raise AdvisorContextError("observation.evidence must be a non-empty list")
    if len(evidence) > _MAX_ITEMS:
        raise AdvisorContextError("observation.evidence exceeds the bounded item limit")
    result["evidence"] = [_copy(item, f"observation.evidence[{index}]") for index, item in enumerate(evidence)]
    return result


def _provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdvisorContextError("requirement_provenance must be an object")
    result = _copy(dict(value), "requirement_provenance")
    source = _text(result.get("source"), "requirement_provenance.source", max_length=128).lower()
    if source not in _PROVENANCE:
        raise AdvisorContextError("requirement_provenance.source is unsupported")
    result["source"] = source
    result["requirement"] = _text(result.get("requirement"), "requirement_provenance.requirement")
    result["harm_if_removed"] = _text(result.get("harm_if_removed"), "requirement_provenance.harm_if_removed")
    return result


def _required_text(result: Mapping[str, Any], field: str) -> str:
    return _text(result.get(field), field)


def choose_advisor_direction(
    *,
    context: Mapping[str, Any],
    observation: Mapping[str, Any],
    disposition: str,
    previous_advice: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Validate one evidence-backed advisor disposition.

    ``disposition`` is the advisor's judgment; this function makes its proof,
    authority, and next action explicit.  In particular, a healthy check is a
    quiet ``continue`` record, while a correction cannot be represented as a
    vague request for the manager to choose among subtle alternatives.
    """

    if not isinstance(context, Mapping) or context.get("schema") != "otto.project-advisor-context.v1":
        raise AdvisorContextError("context is not an advisor context")
    selected = _text(disposition, "disposition", max_length=64).lower()
    if selected not in _DISPOSITIONS:
        raise AdvisorContextError("disposition must be continue, watch, correct, or escalate")
    observed = _observation(observation)
    authority = _text(observed.get("authority", "in_mandate"), "observation.authority", max_length=128).lower()
    if authority in _OWNER_ONLY and selected != "escalate":
        raise AdvisorContextError("owner-only or uncertain work must be escalated")
    if selected == "escalate" and authority not in _OWNER_ONLY:
        raise AdvisorContextError("escalation requires an owner-only, cross-project, authority, or uncertainty reason")

    result: dict[str, Any] = {
        "schema": "otto.project-advisor-direction.v1",
        "context_sha256": context.get("context_sha256"),
        "disposition": selected,
        "evidence": observed["evidence"],
        "observed": _copy({key: value for key, value in observed.items() if key != "evidence"}, "observed"),
        "authority": authority,
        "notify_manager": selected in {"watch", "correct", "escalate"},
    }
    if selected == "continue":
        result.update({
            "message": None,
            "selected_action": None,
            "revisit_condition": _text(observed.get("revisit_condition", "materially changed evidence"), "revisit_condition"),
        })
    elif selected == "watch":
        result.update({
            "message": _required_text(observed, "message"),
            "selected_action": _required_text(observed, "selected_action"),
            "revisit_condition": _required_text(observed, "revisit_condition"),
        })
    elif selected == "correct":
        if authority in _OWNER_ONLY:
            raise AdvisorContextError("corrections cannot cross the advisor's authority boundary")
        provenance = _provenance(observed.get("requirement_provenance"))
        result["requirement_provenance"] = provenance
        result.update({
            "implication": _required_text(observed, "implication"),
            "shortest_path": _required_text(observed, "shortest_path"),
            "selected_action": _required_text(observed, "selected_action"),
            "responsible": _required_text(observed, "responsible"),
            "required_proof": _required_text(observed, "required_proof"),
            "preserved_constraints": _items(observed.get("preserved_constraints", ()), "preserved_constraints"),
            "dropped_or_reused": _items(observed.get("dropped_or_reused", ()), "dropped_or_reused"),
            "revisit_condition": _required_text(observed, "revisit_condition"),
        })
        if provenance["source"] in {"self_imposed", "stale", "tool"} and not result["dropped_or_reused"]:
            raise AdvisorContextError("an invented or stale requirement must be removed or reused explicitly")
    else:
        result.update({
            "requested_decision": _required_text(observed, "requested_decision"),
            "held_dependents": _items(observed.get("held_dependents", ()), "held_dependents"),
            "revisit_condition": _required_text(observed, "revisit_condition"),
        })

    if previous_advice is not None:
        prior = _copy(dict(previous_advice), "previous_advice")
        result["previous_advice"] = prior
        if prior.get("was_wrong") is True or prior.get("status") in {"contradicted", "superseded"}:
            result["revises_previous_advice"] = True
            result["revision_reason"] = _required_text(observed, "revision_reason")
        else:
            result["revises_previous_advice"] = False
    else:
        result["revises_previous_advice"] = False
    result["direction_sha256"] = _digest(result)
    return result


__all__ = ["AdvisorContextError", "build_advisor_context", "choose_advisor_direction"]
