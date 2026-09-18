"""Pure ORC-04 continuation at the persistent-manager boundary.

ORC-03 produces a report-only current-action packet.  This module is the
small boundary immediately after that packet: it validates the packet and
the existing ORC-04 custody, then emits one deterministic execution/resume
receipt.  It deliberately has no persistence, queue, scheduler, worker
launch, or owner-write capability.  The P2 manager decides whether to attach
or accept the receipt.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping, Sequence


class ExecutionResumeError(ValueError):
    """A selected packet cannot be continued under the supplied custody."""


_PACKET_SCHEMA = "otto.orchestrator.orc03.current_action_packet.v1"
_RESULT_SCHEMA = "otto.orchestrator.orc04.selected_packet_execution_resume.v1"
_TRUSTED_SOURCES = frozenset({"user", "root_transport", "owner"})


def _copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ExecutionResumeError("values must be JSON-compatible") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ExecutionResumeError(f"{field} must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionResumeError(f"{field} must be a reference object")
    result = _copy(dict(value))
    _text(result.get("id"), f"{field}.id")
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _packet_body(packet: Mapping[str, Any]) -> dict[str, Any]:
    body = _copy(dict(packet))
    body.pop("packet_sha256", None)
    body.pop("idempotency_key", None)
    return body


def packet_digest(packet: Mapping[str, Any]) -> str:
    """Return the canonical ORC-03 digest used by its packet idempotency key."""

    return _digest(_packet_body(packet))


def _same_ref(actual: Mapping[str, Any], expected: Mapping[str, Any], field: str) -> None:
    actual_ref = _ref(actual, field)
    expected_ref = _ref(expected, f"expected_{field}")
    # A manager may add observational fields, but the pinned identity and
    # revision must match exactly when both are present.
    for key in ("authority", "kind", "id", "revision"):
        if key in expected_ref and actual_ref.get(key) != expected_ref[key]:
            raise ExecutionResumeError(f"{field} does not match the pinned custody")


def _require_sequence(value: Any, field: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ExecutionResumeError(f"{field} must be a sequence")
    return list(value)


def _validate_packet(
    packet: Mapping[str, Any],
    expected_packet_sha256: str,
    packet_artifact_sha256: str,
) -> tuple[dict[str, Any], str, str]:
    if not isinstance(packet, Mapping) or packet.get("schema") != _PACKET_SCHEMA:
        raise ExecutionResumeError("selected packet schema is not a supported ORC-03 packet")
    expected_artifact = _text(expected_packet_sha256, "expected_packet_sha256")
    observed_artifact = _text(packet_artifact_sha256, "packet_artifact_sha256")
    if observed_artifact != expected_artifact:
        raise ExecutionResumeError("selected packet is stale: artifact digest does not match the pinned packet")
    observed = _text(packet.get("packet_sha256"), "packet.packet_sha256")
    computed = packet_digest(packet)
    if observed != computed:
        raise ExecutionResumeError("selected packet digest is internally inconsistent")
    selected = packet.get("selected_mandate")
    if not isinstance(selected, Mapping):
        raise ExecutionResumeError("selected packet has no current mandate")
    if selected.get("source") not in _TRUSTED_SOURCES or selected.get("trusted") is not True:
        raise ExecutionResumeError("selected packet mandate is not trusted")
    if selected.get("state") not in {"active", "execute"} or selected.get("mode") != "execution":
        raise ExecutionResumeError("selected packet mandate is not active execution")
    planner_handoff = packet.get("planner_handoff")
    if not isinstance(planner_handoff, Mapping) or planner_handoff.get("report_only") is not True:
        raise ExecutionResumeError("selected packet planner handoff must remain report-only")
    if planner_handoff.get("auto_dispatch") is not False or planner_handoff.get("worker_dispatch") is not False:
        raise ExecutionResumeError("planner handoff cannot auto-dispatch")
    return _copy(dict(packet)), computed, observed_artifact


def execute_selected_packet(
    *,
    packet: Mapping[str, Any],
    expected_packet_sha256: str,
    packet_artifact_sha256: str,
    expected_project_ref: Mapping[str, Any],
    expected_task_ref: Mapping[str, Any],
    expected_assignment_ref: Mapping[str, Any],
    expected_generation: int,
    observed_custody: Mapping[str, Any],
    manager_ref: Mapping[str, Any],
    worker_observation: Mapping[str, Any],
    prerequisite_refs: Sequence[Mapping[str, Any]],
    brief_sha256: str,
    plan_sha256: str,
    p1_handoff_sha256: str,
    operation: str = "execute_or_resume",
    prior_attempts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Admit exactly one bounded continuation without launching anything.

    A repeated idempotency key is returned as a replay record.  It carries
    the same stable operation digest and never becomes a second launch.  Any
    stale or incompatible input raises a typed error before a result is
    emitted, leaving the existing manager records untouched.
    """

    packet_value, selected_digest, selected_artifact = _validate_packet(packet, expected_packet_sha256, packet_artifact_sha256)
    if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
        raise ExecutionResumeError("expected_generation must be a positive integer")
    packet_generation = packet_value.get("generation")
    if packet_generation != 2:
        raise ExecutionResumeError("selected packet generation is stale or unsupported")
    _same_ref(packet_value.get("owner_ref"), packet_value.get("context", {}).get("project_ref", {}), "owner_ref")
    # ORC-04 is a continuation of the ORC-03 packet.  Its custody is pinned
    # separately; this prevents an ORC-03 task reference from being silently
    # reused as the ORC-04 task.
    project_ref = _ref(expected_project_ref, "expected_project_ref")
    task_ref = _ref(expected_task_ref, "expected_task_ref")
    assignment_ref = _ref(expected_assignment_ref, "expected_assignment_ref")
    manager = _ref(manager_ref, "manager_ref")
    if "revision" not in project_ref or "revision" not in task_ref or "revision" not in assignment_ref:
        raise ExecutionResumeError("ORC-04 custody refs must include pinned revisions")
    if not isinstance(observed_custody, Mapping):
        raise ExecutionResumeError("observed_custody must be an object")
    _same_ref(observed_custody.get("project_ref"), project_ref, "project_ref")
    _same_ref(observed_custody.get("task_ref"), task_ref, "task_ref")
    _same_ref(observed_custody.get("assignment_ref"), assignment_ref, "assignment_ref")
    observed_generation = observed_custody.get("generation")
    if observed_generation != expected_generation:
        raise ExecutionResumeError("observed custody generation does not match the pinned assignment")
    if not isinstance(worker_observation, Mapping):
        raise ExecutionResumeError("worker_observation must be an object")
    worker = _copy(dict(worker_observation))
    for field in ("native_id", "requested_model", "requested_reasoning", "observed_model", "observed_reasoning"):
        _text(worker.get(field), f"worker_observation.{field}")
    if worker.get("role") != "worker":
        raise ExecutionResumeError("reused context must remain a worker")
    if worker.get("owner_write") is not False or worker.get("dispatch") is not False:
        raise ExecutionResumeError("worker observation grants no owner write or dispatch authority")
    brief = _text(brief_sha256, "brief_sha256")
    plan = _text(plan_sha256, "plan_sha256")
    p1_handoff = _text(p1_handoff_sha256, "p1_handoff_sha256")
    operation_name = _text(operation, "operation")
    prereqs = [_ref(item, "prerequisite_ref") for item in _require_sequence(prerequisite_refs, "prerequisite_refs")]
    if not prereqs:
        raise ExecutionResumeError("at least one prerequisite reference is required")
    if not isinstance(prior_attempts, Sequence) or isinstance(prior_attempts, (str, bytes)):
        raise ExecutionResumeError("prior_attempts must be a sequence")
    target = {
        "project_ref": project_ref,
        "task_ref": task_ref,
        "assignment_ref": assignment_ref,
        "generation": expected_generation,
        "manager_ref": manager,
        "operation": operation_name,
    }
    stable = {
        "schema": _RESULT_SCHEMA,
        "selected_packet_sha256": selected_artifact,
        "selected_packet_digest": selected_digest,
        "target": target,
        "brief_sha256": brief,
        "plan_sha256": plan,
        "p1_handoff_sha256": p1_handoff,
        "prerequisite_refs": prereqs,
        "worker": worker,
    }
    operation_sha = _digest(stable)
    idempotency_key = "orc04-selected-packet-" + operation_sha
    prior_keys = set()
    for item in prior_attempts:
        if isinstance(item, Mapping) and isinstance(item.get("idempotency_key"), str):
            prior_keys.add(item["idempotency_key"])
    replayed = idempotency_key in prior_keys
    result = {
        **stable,
        "idempotency_key": idempotency_key,
        "operation_sha256": operation_sha,
        "outcome": "replayed_noop" if replayed else "admitted_bounded_resume",
        "replayed": replayed,
        "dispatch": False,
        "launch": False,
        "owner_acceptance": False,
        "schedule_mutation": False,
        "live_controller_mutation": False,
        "p1_owner_writes_parked": True,
        "p1_open_obligations": ["BK-C06", "BK-C07"],
        "unmet_criteria": [
            {
                "criterion": "P2 manager owner attachment and acceptance",
                "status": "pending",
                "responsible_owner": manager,
                "next_resume_event": "P2 manager verifies this receipt and performs guarded disposition",
            },
        ],
    }
    result["result_sha256"] = _digest(result)
    return result


__all__ = ["ExecutionResumeError", "execute_selected_packet", "packet_digest"]
