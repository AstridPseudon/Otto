"""Adopt and acknowledge an existing paused automation through owner ports."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from otto.attention import native_target_identity
from .advisor_delivery import effect_followup_schedule_id


def read_persisted_automation_settings(
    directory: Path, automation_id: str, *, parse_toml: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Read app-owned settings by exact ID; never write or provision a timer."""
    if not isinstance(automation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", automation_id):
        raise ValueError("automation_id must be one exact local automation ID")
    path = directory / automation_id / "automation.toml"
    raw = path.read_bytes()
    value = parse_toml(raw.decode("utf-8"))
    result = {key: value.get(key) for key in ("id", "kind", "name", "prompt", "status", "rrule")}
    result["targetThreadId"] = value.get("target_thread_id")
    if value.get("notification_policy") is not None:
        result["notificationPolicy"] = value["notification_policy"]
    return {**result, "persisted_source": str(path), "persisted_sha256": sha256(raw).hexdigest()}


def bind_paused_advisor_automation(
    *, request: Mapping[str, Any], pairing: Any, actor: str, attention: Any,
    read_settings: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """CAS-bind settings, prepare a paused effect, reread, and owner-acknowledge.

    No host mutation, attention claim, execution, or allowance operation is
    supplied to this command. Unknown/in-flight occurrences cannot be rebound.
    """
    schedule, decision = request.get("schedule_id"), request.get("decision_id")
    identity, key = request.get("automation_id"), request.get("request_key")
    version = request.get("expected_version")
    for name, value in (("schedule_id", schedule), ("decision_id", decision),
                        ("automation_id", identity), ("request_key", key)):
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or "\x00" in value):
            raise ValueError(name + " must be exact non-blank text")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("expected_version must be a positive integer")
    if schedule != effect_followup_schedule_id(pairing.project_ref, decision):
        raise ValueError("schedule_id does not identify the current project's decision follow-up")
    base = {"schema": "otto.advisor-paused-host-binding.v1", "schedule_id": schedule,
            "decision_id": decision, "automation_id": identity, "request_key": key,
            "provider_called": False, "automation_updated": False, "retry": False}
    current = attention._read(schedule)
    if current is None:
        return {**base, "outcome": "unknown", "error": {"code": "unknown_schedule"}}
    if (actor != current.lifecycle_owner or current.project_ref != pairing.project_ref["id"]
            or current.role != "project_advisor" or current.purpose != "advisor-effect-followup"
            or current.generation != pairing.advisor_generation
            or not isinstance(current.assignment_ref, Mapping)
            or current.assignment_ref["id"] != pairing.advisor_ref["id"]
            or native_target_identity(current.target) != native_target_identity(pairing.advisor_conversation_ref)):
        return {**base, "outcome": "rejected", "error": {"code": "foreign_or_stale_binding"}}
    if current.version != version:
        return {**base, "outcome": "rejected", "error": {"code": "stale_version"}, "version": current.version}
    if current.in_flight_request is not None or current.completion_state == "unknown":
        return {**base, "outcome": "held", "error": {"code": "occurrence_requires_reconciliation"}}
    try:
        observed = dict(read_settings(identity))
    except Exception as exc:
        return {**base, "outcome": "unknown", "error": {"code": "automation_readback_unavailable", "message": str(exc)}}
    fields = ("id", "kind", "name", "prompt", "status", "rrule", "targetThreadId")
    for field in fields:
        if not isinstance(observed.get(field), str) or not observed[field].strip():
            raise ValueError("persisted automation settings are incomplete: " + field)
    if (observed["id"] != identity or observed["kind"] != "heartbeat"
            or observed["status"] != "PAUSED"
            or observed["targetThreadId"] != native_target_identity(pairing.manager_conversation_ref)):
        return {**base, "outcome": "rejected", "error": {"code": "automation_not_paused_owner_target"}}
    settings = {field: observed[field] for field in fields}
    if "notificationPolicy" in observed:
        settings["notificationPolicy"] = observed["notificationPolicy"]
    target = dict(current.target)
    previous = target.get("automation")
    if previous is not None and previous != settings:
        return {**base, "outcome": "rejected", "error": {"code": "automation_binding_conflict"}}
    configuration = {"outcome": "replayed", "record": current.to_dict()}
    if previous is None:
        target["automation"] = settings
        digest = sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        desired = replace(current, target=target,
                          invocation_identity=current.invocation_identity + ":host-paused:" + digest)
        configuration = attention.reconfigure(desired, request_id=key + ":bind",
                                              expected_version=version, actor=actor)
        if configuration.get("outcome") not in {"reconfigured", "replayed"}:
            return {**base, "outcome": configuration.get("outcome"), "configuration": configuration}
        current = attention._read(schedule)
    scope = {"actor": actor, "project_ref": current.project_ref,
             "manager_ref": current.manager_ref, "generation": current.generation}
    prepared = attention.prepare_host(schedule, request_id=key + ":paused",
        expected_version=current.version, desired_state="paused", **scope)
    if prepared.get("effect") is None:
        return {**base, "outcome": prepared.get("outcome"), "configuration": configuration, "prepared": prepared}
    # Exact persisted settings are read again after the owner effect exists.
    # Flat app fields are compared by the maintained host bridge, not by a
    # fabricated copy of the expected effect configuration.
    try:
        readback = dict(read_settings(identity))
    except Exception:
        readback = None
    acknowledgement = attention.acknowledge_host(schedule, request_id=key + ":paused",
        observed=readback, expected_version=attention._read(schedule).version, **scope)
    return {**base, "outcome": acknowledgement.get("outcome"), "configuration": configuration,
            "prepared": prepared, "readback": readback, "acknowledgement": acknowledgement}
