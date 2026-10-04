"""Provider-free lifecycle receipt using the maintained callback/delivery guards."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from herzchen.contracts import ResourceRef
from otto.attention import DueRecord, DurableAttention, InMemoryDueRecordPort, RecordingAttentionPort
from .advisor_delivery import AdvisorDeliveryLoop, effect_followup_schedule_id
from .advisor_execution import AdvisorExecution
from .advisor_followup_command import advisor_followup_from_command


def exercise_advisor_lifecycle(
    *, request: Mapping[str, Any], pairing: Any, advisor_principal: str, actor: str,
    loop: AdvisorDeliveryLoop, allowance: Any, authenticate: Callable[[str], Any],
    read_settings: Callable[[str], Mapping[str, Any]],
    live_dispatch: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    """Read the paused live callback; project other lifecycle states only in memory.

    Active fixture admission uses existing AdvisorExecution and the owner's
    existing exhausted pool. Only fixture Due/resource joins are inert. A
    provider start capability is never supplied. No activation or pool reset.
    """
    schedule, decision, identity = request.get("schedule_id"), request.get("decision_id"), request.get("automation_id")
    if schedule != effect_followup_schedule_id(pairing.project_ref, decision):
        raise ValueError("exercise requires the existing project's decision schedule")
    original = loop.ports.attention._read(schedule)
    configuration = (original.target or {}).get("automation", {}) if original else {}
    if original is None or configuration.get("id") != identity:
        raise ValueError("exercise requires the existing adopted automation ID")
    settings = dict(read_settings(identity))
    fields = ("id", "kind", "name", "prompt", "rrule", "status", "targetThreadId", "notificationPolicy")
    if (original.host_state != "paused" or settings.get("status") != "PAUSED"
            or any(settings.get(field) != configuration.get(field) for field in fields)):
        raise ValueError("exercise requires exact persisted paused host readback")
    pool_ref = ResourceRef.from_dict(original.allowance_ref)
    pool = allowance.get_pool(pool_ref)
    if pool is None or pool.cumulative_used_units < pool.cumulative_allowance_units:
        raise ValueError("exercise requires the already exhausted adopted allowance")
    def pool_snapshot(value):
        return {"ref": value.ref.to_dict(), "capacity": value.capacity_units,
                "limit": value.cumulative_allowance_units, "used": value.cumulative_used_units,
                "held": value.held_units, "version": value.version}
    before_pool = pool_snapshot(pool)
    entered = []
    def compact_callback(value):
        # Readiness embeds the full retained Due history. Keep the admission
        # evidence and exact occurrence IDs without copying native transcripts.
        result = {key: value[key] for key in ("outcome", "schedule_id", "decision_id", "operation",
                  "dispatch_called", "provider_called", "reason", "retry", "error") if key in value}
        dispatch = value.get("dispatch")
        if isinstance(dispatch, Mapping):
            wake = dispatch.get("wake") or {}
            completion = dispatch.get("completion") or {}
            result["dispatch"] = {"outcome": dispatch.get("outcome"),
                "runtime_called": dispatch.get("runtime_called", False), "retry": dispatch.get("retry", False),
                "wake": {key: wake.get(key) for key in ("outcome", "request_id", "replayed", "readiness")},
                "completion": {"outcome": completion.get("outcome"),
                    "evidence": (completion.get("record") or {}).get("completion_evidence")}}
        return result
    def provider_start(**_kwargs):
        raise AssertionError("provider boundary: lifecycle exercise cannot start a provider")
    def command(read, dispatch):
        entered.append("advisor_followup_from_command:dispatch")
        return advisor_followup_from_command(
            request={"schedule_id": schedule, "decision_id": decision, "operation": "dispatch"},
            project_ref=pairing.project_ref, read_due=read, dispatch=dispatch)
    # Actual persisted PAUSED settings and the adopted owner record. Production
    # callback host guard returns before the real live dispatch callback.
    live = command(lambda key: loop.ports.attention._read(key).to_dict(), live_dispatch)
    rows = {}
    for name, stop, host in (("active", "active", "active"), ("paused", "active", "paused"),
                             ("stopped", "stopped", "active"), ("completed", "completed", "active")):
        value = original.to_dict()
        value.update(stop_state=stop, host_state=host, completion_state="none", in_flight_request=None,
                     last_covered_slot=-1, host_evidence=None, last_result=None,
                     completion_evidence=None, delivery_evidence=None, invocation_identity=original.invocation_identity + ":lifecycle-fixture-" + name, target={**value["target"], "automation": {
                         **configuration, "status": "PAUSED" if host == "paused" else "ACTIVE"}})
        memory = InMemoryDueRecordPort()
        memory.save_due(schedule, value, request_id="inert-lifecycle-" + name, expected_version=0)
        attention = DurableAttention(RecordingAttentionPort(), due_port=memory, host_mode="awaited")
        # Pairing was read by the live controller at callback entry. Fixture
        # restarts retain that same immutable identity snapshot; they do not
        # repeatedly scan native-history projections for fixture rows.
        ports = replace(loop.ports, attention=attention, current_pairing=lambda _project: pairing)
        # Explicit inert resource join. Production allowance reserve is still
        # reached with the real exhausted owner pool and authentic owner actor.
        app = SimpleNamespace(actor=actor, binding=SimpleNamespace(authenticated_actor=authenticate),
            _read=lambda key: DueRecord.from_dict(memory.read_due(key)),
            _resources=lambda due: due, start=provider_start)
        execution = AdvisorExecution(execution=app, ports=ports, allowance=allowance,
                                     allowance_ref=pool_ref.to_dict())
        def dispatch(*, schedule_id, decision_id):
            entered.append("AdvisorExecution.wake_once:" + name)
            result = execution.wake_once(pairing=pairing, schedule_id=schedule_id,
                advisor_principal=advisor_principal, lifecycle_owner=actor,
                reason="scheduled-effect-followup", request={"decision_id": decision_id})
            return {"outcome": result["outcome"], "dispatch": result, "provider_called": False}
        first = command(memory.read_due, dispatch)
        # Reconstruct the delivery composition from the retained fixture record.
        execution = AdvisorExecution(execution=app, ports=ports, allowance=allowance,
                                     allowance_ref=pool_ref.to_dict())
        recovered = command(memory.read_due, dispatch)
        rows[name] = {"fixture_scope": "inert Due/resource join; current owner pairing and real exhausted allowance",
                      "first_callback": compact_callback(first), "restart_callback": compact_callback(recovered),
                      "record": {key: memory.read_due(schedule).get(key) for key in
                          ("schedule_id", "version", "stop_state", "host_state", "completion_state",
                           "in_flight_request", "last_completed_request")},
                      "native_session": original.target.get("native_id") or original.target.get("physical_session_id")}
    after_pool = pool_snapshot(allowance.get_pool(pool_ref))
    if after_pool != before_pool or loop.ports.attention._read(schedule).to_dict() != original.to_dict():
        raise AssertionError("lifecycle exercise changed live owner custody")
    return {"schema": "otto.advisor-lifecycle-exercise.v1", "outcome": "read",
            "schedule_id": schedule, "decision_id": decision, "automation_id": identity,
            "persisted_settings": settings, "original_due_version": original.version,
            "live_callback": live, "inert_callback_scenarios": rows,
            "production_entries": entered, "allowance_before": before_pool, "allowance_after": after_pool,
            "provider_boundary": "no provider capability; active Due/resource joins are labelled inert",
            "automation_activated": False, "allowance_changed": False, "provider_called": False,
            "read_only_live_owner": True, "retry": False}
