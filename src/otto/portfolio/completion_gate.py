"""Read the existing owner completion predicate through a finite injected port."""
from __future__ import annotations

import json
from typing import Any, Mapping

from herzchen.contracts import AuthenticatedActor, ResourceRef


def completion_gate_from_command(
    completion_owner: Any, *, request: Mapping[str, Any],
    task_ref: Mapping[str, Any], actor: AuthenticatedActor,
) -> Mapping[str, Any]:
    """Explain current blockers without completing or reconciling any work.

    The owner supplies the task and authenticated actor. Evidence is optional
    for an initial read; hashes, when supplied, align with evidence refs.
    Completion rechecks this predicate inside its existing transaction.
    """
    task = ResourceRef.from_dict(task_ref)
    if task.kind != "work.task" or not task.revision:
        raise ValueError("owner must supply an exact task revision")
    if not isinstance(actor, AuthenticatedActor):
        raise TypeError("owner must supply an authenticated actor")

    def reference(value: Any) -> ResourceRef:
        try:
            ref = ResourceRef.from_dict(json.loads(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("exact owner resource-ref JSON is required") from exc
        if ref.authority != task.authority or not ref.revision:
            raise ValueError("completion gate refs must pin an owner revision")
        return ref

    def references(field: str) -> tuple[ResourceRef, ...]:
        values = request.get(field, [])
        if not isinstance(values, list):
            raise ValueError(field + " must be a list")
        return tuple(reference(value) for value in values)

    candidate = reference(request["candidate_ref"]) if request.get("candidate_ref") is not None else None
    gates = references("gate_refs")
    evidence = references("evidence_refs")
    hashes = request.get("evidence_hashes", [])
    if (not isinstance(hashes, list) or (hashes and len(hashes) != len(evidence))
            or any(not isinstance(value, str) or len(value) != 64
                   or any(char not in "0123456789abcdefABCDEF" for char in value) for value in hashes)):
        raise ValueError("evidence hashes must be SHA256 values aligned with evidence refs")
    value = {
        "outcome": "read", "schema": "otto.completion-gate.v1",
        "task_ref": task.to_dict(), "read_only": True, "provisional": True,
        "acceptance_recorded": False,
    }
    try:
        state = completion_owner.completion_blockers(
            task, candidate=candidate, gate_refs=gates, actor=actor,
            completion_evidence_refs=evidence, completion_evidence_hashes=hashes,
        )
    except Exception as exc:
        return {**value, "eligibility": "unknown",
                "error": {"code": "completion_gate_read_failed", "message": str(exc)}}
    if (not isinstance(state, Mapping) or type(state.get("required")) is not bool
            or not isinstance(state.get("blockers"), list)):
        return {**value, "eligibility": "unknown",
                "error": {"code": "malformed_completion_gate", "message": "owner returned no complete blocker object"}}
    eligibility = "blocked" if state["blockers"] else "clear"
    if not state["blockers"] and state["required"] and state.get("evidence_verification") != "verified":
        eligibility = "unknown"
    return {**value, "eligibility": eligibility, "owner_gate_state": dict(state)}
