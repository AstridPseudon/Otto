"""Focused SUP-02 owner-fence and deterministic host executor proofs."""

from datetime import datetime, timezone
import json

import pytest

from otto.attention import DueRecord, DurableAttention, InMemoryDueRecordPort, RecordingAttentionPort, RecordingHostTriggerPort
from otto.host_bridge import (
    DeterministicHostExecutor,
    HostBridgeError,
    HostEffect,
    SerializedAutomationUpdateAdapter,
    automation_update_request,
    configuration_fingerprint,
    readback_matches,
)


NOW = datetime(2026, 9, 18, 19, 0, tzinfo=timezone.utc)


def _record(
    schedule_id="sup02-bridge", *, identity="invocation-1", generation=2,
    target_id="automation-01", role="manager", purpose="hourly-sense-check",
    message="owner context", target_thread_id="thread-manager-01",
    recipient="project-manager", owner="owner-01",
):
    return DueRecord(
        schedule_id=schedule_id, recipient=recipient,
        instruction="perform the bounded manager check", profile="normal",
        anchor="2026-09-18T18:00:00Z", due_at="2026-09-18T18:30:00Z",
        last_covered_slot=-1, invocation_identity=identity,
        target={
            "host": "codex", "native_id": target_id, "automation_id": target_id,
            "targetThreadId": target_thread_id,
            "automation": {
                "name": "otto-sup02-test", "kind": "heartbeat",
                "prompt": message,
                "rrule": "RRULE:FREQ=HOURLY;INTERVAL=1", "status": "ACTIVE",
                "targetThreadId": target_thread_id,
                "notificationPolicy": "failed_runs_only",
            },
        }, role=role,
        purpose=purpose, message=message,
        lifecycle_owner=owner, owner=owner, project_ref="project-01",
        manager_ref="manager-01", generation=generation,
    )


def _scheduler(record=None, *, host_port=None):
    due = InMemoryDueRecordPort()
    scheduler = DurableAttention(RecordingAttentionPort(), due_port=due, host_port=host_port, host_mode="durable-host", clock=lambda: NOW)
    record = record or _record()
    assert scheduler.schedule(record, request_id="schedule")["outcome"] == "scheduled"
    return scheduler, due, record


def test_owner_fences_foreign_scope_and_stale_version_before_any_host_call():
    scheduler, due, record = _scheduler()
    calls = []
    stale = scheduler.prepare_host(record.schedule_id, request_id="effect-1", expected_version=99, actor="owner-01")
    assert stale["outcome"] == "rejected"
    assert stale["error"]["code"] == "stale_version"
    foreign = scheduler.prepare_host(record.schedule_id, request_id="effect-2", expected_version=1, actor="other-owner")
    assert foreign["error"]["code"] == "foreign_authority"
    assert calls == []
    assert due.read_due(record.schedule_id)["host_state"] == "unknown"


def test_automation_update_request_emits_complete_typed_configuration():
    scheduler, _due, record = _scheduler()
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-fields", expected_version=1, actor="owner-01")
    request = automation_update_request(HostEffect.from_dict(prepared["effect"]))
    assert request == {
        "operation": "automation_update", "mode": "update", "id": "automation-01",
        "name": "otto-sup02-test", "kind": "heartbeat",
        "prompt": "owner context",
        "rrule": "RRULE:FREQ=HOURLY;INTERVAL=1", "status": "ACTIVE",
        "targetThreadId": "thread-manager-01", "notificationPolicy": "failed_runs_only",
    }


def test_pause_effect_maps_status_to_paused_while_preserving_configuration():
    scheduler, _due, record = _scheduler(_record(schedule_id="pause"))
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-pause", expected_version=1, actor="owner-01", desired_state="paused")
    request = automation_update_request(HostEffect.from_dict(prepared["effect"]))
    assert request["id"] == "automation-01"
    assert request["status"] == "PAUSED"
    assert request["name"] == "otto-sup02-test"
    assert request["targetThreadId"] == "thread-manager-01"


def test_readback_helper_accepts_complete_top_level_persisted_settings():
    scheduler, _due, record = _scheduler(_record(schedule_id="top-level"))
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-top-level", expected_version=1, actor="owner-01")
    effect = HostEffect.from_dict(prepared["effect"])
    request = automation_update_request(effect)
    exact, evidence = readback_matches(effect, {**request, "state": "active"})
    assert exact is True
    assert evidence["code"] == "exact_readback"


def test_automation_update_request_rejects_missing_and_ambiguous_fields():
    scheduler, _due, record = _scheduler(_record(schedule_id="fields"))
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-fields", expected_version=1, actor="owner-01")
    payload = dict(prepared["effect"])
    config = dict(payload["configuration"])
    target = dict(config["target"])
    automation = dict(target["automation"])
    automation.pop("rrule")
    target["automation"] = automation
    config["target"] = target
    payload["configuration"] = config
    payload["configuration_sha256"] = configuration_fingerprint(config)
    with pytest.raises(HostBridgeError, match="rrule"):
        automation_update_request(HostEffect.from_dict(payload))

    config = dict(prepared["effect"]["configuration"])
    target = dict(config["target"])
    target["target_thread_id"] = "different-thread"
    config["target"] = target
    payload["configuration"] = config
    payload["configuration_sha256"] = configuration_fingerprint(config)
    with pytest.raises(HostBridgeError, match="conflicting aliases"):
        automation_update_request(HostEffect.from_dict(payload))


def test_serialized_adapter_is_the_sole_source_of_app_tool_arguments():
    scheduler, _due, record = _scheduler()
    prepared = scheduler.prepare_host(record.schedule_id, request_id="serialized-effect", expected_version=1, actor="owner-01")
    effect = HostEffect.from_dict(prepared["effect"])
    calls = []

    def app_call(request):
        calls.append(dict(request))
        return {"accepted": True}

    adapter = SerializedAutomationUpdateAdapter(app_call)
    result = adapter.execute(json.dumps(effect.to_dict(), sort_keys=True))
    assert result["request"] == automation_update_request(effect)
    assert calls == [result["request"]]
    assert set(calls[0]) == {"operation", "mode", "id", "name", "kind", "prompt", "rrule", "status", "targetThreadId", "notificationPolicy"}

    hand_edited = effect.to_dict()
    hand_edited["targetThreadId"] = "manual-transcription"
    with pytest.raises(HostBridgeError, match="untrusted app fields"):
        adapter.execute(hand_edited)
    assert len(calls) == 1


def test_executor_requires_exact_readback_and_acknowledges_once_on_replay():
    scheduler, due, record = _scheduler()
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-1", expected_version=1, actor="owner-01")
    assert prepared["outcome"] == "pending_host"
    effect = prepared["effect"]
    update_calls, read_calls, ack_calls = [], [], []

    def update(request):
        update_calls.append(dict(request))
        return {"accepted": True}

    def read(effect_value, response):
        read_calls.append(response)
        return {"schedule_id": effect_value.schedule_id, "state": "active", "configuration": dict(effect_value.configuration)}

    def acknowledge(effect_value, observation):
        ack_calls.append(observation)
        current = due.read_due(record.schedule_id)
        return scheduler.acknowledge_host(record.schedule_id, request_id=effect_value.request_id, observed=observation, expected_version=current["version"], actor="owner-01")

    executor = DeterministicHostExecutor(update, read, acknowledge)
    first = executor.execute(HostEffect.from_dict(effect))
    replay = executor.execute(HostEffect.from_dict(effect))
    assert first["outcome"] == "reconciled"
    assert first["readback"]["readback_exact"] is True
    assert replay["replayed"] is True
    assert len(update_calls) == len(read_calls) == len(ack_calls) == 1
    assert update_calls[0] == automation_update_request(HostEffect.from_dict(effect))
    assert due.read_due(record.schedule_id)["host_state"] == "active"


def test_host_failure_and_response_loss_remain_unsettled_and_retryable_by_readback():
    scheduler, due, record = _scheduler(_record(schedule_id="failure"))
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-fail", expected_version=1, actor="owner-01")
    effect = HostEffect.from_dict(prepared["effect"])

    def failed_update(_request):
        raise RuntimeError("tool host unavailable")

    def ack(effect_value, observation):
        current = due.read_due(record.schedule_id)
        return scheduler.acknowledge_host(record.schedule_id, request_id=effect_value.request_id, observed=observation, expected_version=current["version"], actor="owner-01")

    failure = DeterministicHostExecutor(failed_update, lambda _effect, _response: {}, ack).execute(effect)
    assert failure["outcome"] == "host_failure"
    assert due.read_due(record.schedule_id)["host_state"] == "failed"

    scheduler2, due2, record2 = _scheduler(_record(schedule_id="lost"))
    prepared2 = scheduler2.prepare_host(record2.schedule_id, request_id="effect-lost", expected_version=1, actor="owner-01")
    effect2 = HostEffect.from_dict(prepared2["effect"])
    updates = []

    def update2(request):
        updates.append(request)
        return {"accepted": True}

    def ack2(effect_value, observation):
        current = due2.read_due(record2.schedule_id)
        return scheduler2.acknowledge_host(record2.schedule_id, request_id=effect_value.request_id, observed=observation, expected_version=current["version"], actor="owner-01")

    read_attempts = []

    def read2(effect_value, _response):
        read_attempts.append(True)
        if len(read_attempts) == 1:
            raise RuntimeError("readback lost")
        return {"schedule_id": effect_value.schedule_id, "state": "active", "configuration": dict(effect_value.configuration)}

    executor2 = DeterministicHostExecutor(update2, read2, ack2)
    lost = executor2.execute(effect2)
    assert lost["outcome"] == "response_lost"
    assert lost["readback"]["response_lost"] is True
    assert lost["acknowledgement"]["outcome"] == "pending"
    assert due2.read_due(record2.schedule_id)["host_state"] == "pending"
    assert len(updates) == 1
    recovered = executor2.execute(effect2)
    assert recovered["outcome"] == "reconciled"
    assert len(updates) == 1


def test_mismatched_persisted_configuration_cannot_claim_active():
    scheduler, due, record = _scheduler(_record(schedule_id="mismatch"))
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-mismatch", expected_version=1, actor="owner-01")
    effect = HostEffect.from_dict(prepared["effect"])
    acknowledgements = []

    def acknowledge(effect_value, observation):
        acknowledgements.append(observation)
        current = due.read_due(record.schedule_id)
        return scheduler.acknowledge_host(record.schedule_id, request_id=effect_value.request_id, observed=observation, expected_version=current["version"], actor="owner-01")

    receipt = DeterministicHostExecutor(
        lambda _request: {"accepted": True},
        lambda effect_value, _response: {"schedule_id": effect_value.schedule_id, "state": "active", "configuration": {**dict(effect_value.configuration), "message": "tampered"}},
        acknowledge,
    ).execute(effect)
    assert receipt["outcome"] == "readback_mismatch"
    assert receipt["readback"]["readback_exact"] is False
    assert due.read_due(record.schedule_id)["host_state"] == "pending"
    assert acknowledgements


def test_owner_change_during_effect_rejects_stale_ack_without_claiming_active():
    scheduler, due, record = _scheduler(_record(schedule_id="race"))
    prepared = scheduler.prepare_host(record.schedule_id, request_id="effect-race", expected_version=1, actor="owner-01")
    effect = HostEffect.from_dict(prepared["effect"])
    # Simulate a fresh owner revision arriving while the tool call is in flight.
    changed = _record(schedule_id="race", identity="invocation-2", target_id="automation-02")
    changed_result = scheduler.reconfigure(changed, request_id="rebind", expected_version=2, actor="owner-01")
    assert changed_result["outcome"] == "reconfigured"
    stale_ack = scheduler.acknowledge_host(
        record.schedule_id, request_id=effect.request_id,
        observed={"schedule_id": record.schedule_id, "state": "active", "configuration": dict(effect.configuration)},
        expected_version=2, actor="owner-01",
    )
    assert stale_ack["outcome"] == "rejected"
    assert stale_ack["error"]["code"] == "stale_version"
    assert due.read_due(record.schedule_id)["host_state"] == "unknown"


class _LifecycleTool:
    """Deterministic app callback fixture keyed by one native automation ID."""

    def __init__(self):
        self.updates = []
        self.readbacks = []
        self.settings = {}
        self.active_ids = set()

    def update(self, request):
        self.updates.append(dict(request))
        automation_id = request["id"]
        self.settings[automation_id] = dict(request)
        if request["status"] == "ACTIVE":
            self.active_ids.add(automation_id)
        else:
            self.active_ids.discard(automation_id)
        return {"accepted": True, "id": automation_id}

    def read(self, effect, response):
        self.readbacks.append({"effect": effect, "response": response})
        request = self.settings.get(effect.configuration["target"]["automation_id"])
        if request is None:
            return {"schedule_id": effect.schedule_id, "state": "unknown", "response_lost": True}
        return {
            "schedule_id": effect.schedule_id,
            "state": request["status"].lower(),
            "configuration": dict(effect.configuration),
        }


@pytest.mark.parametrize(
    ("role", "purpose", "message", "target_id", "target_thread_id", "recipient"),
    [
        ("manager", "hourly-sense-check", "manager lifecycle", "automation-shared-manager", "thread-shared-manager", "project-manager"),
        ("orchestrator", "portfolio-reconcile", "orchestrator lifecycle", "automation-shared-orchestrator", "thread-shared-orchestrator", "portfolio-orchestrator"),
    ],
)
def test_same_id_lifecycle_pauses_to_zero_then_rebinds_one_authorized_owner(
    role, purpose, message, target_id, target_thread_id, recipient,
):
    scheduler, due, record = _scheduler(_record(
        schedule_id="lifecycle-" + role, role=role, purpose=purpose,
        message=message, target_id=target_id, target_thread_id=target_thread_id,
        recipient=recipient,
    ))
    tool = _LifecycleTool()
    ack_calls = []

    def acknowledge(effect, observation):
        ack_calls.append(observation)
        current = due.read_due(record.schedule_id)
        return scheduler.acknowledge_host(
            record.schedule_id, request_id=effect.request_id, observed=observation,
            expected_version=current["version"], actor=effect.lifecycle_owner,
            project_ref=effect.project_ref, manager_ref=effect.manager_ref,
            generation=effect.generation,
        )

    executor = DeterministicHostExecutor(tool.update, tool.read, acknowledge)
    initial = scheduler.prepare_host(record.schedule_id, request_id="lifecycle-active", expected_version=1, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2)
    active_effect = HostEffect.from_dict(initial["effect"])
    active = executor.execute(active_effect)
    assert active["outcome"] == "reconciled"
    assert tool.active_ids == {target_id}
    assert len(tool.updates) == len(tool.readbacks) == len(ack_calls) == 1

    current_version = due.read_due(record.schedule_id)["version"]
    paused = scheduler.prepare_host(record.schedule_id, request_id="lifecycle-paused", expected_version=current_version, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2, desired_state="paused")
    paused_effect = HostEffect.from_dict(paused["effect"])
    paused_result = executor.execute(paused_effect)
    assert paused_result["outcome"] == "reconciled"
    assert tool.active_ids == set()
    assert len(tool.updates) == len(tool.readbacks) == len(ack_calls) == 2
    assert tool.updates[0]["id"] == tool.updates[1]["id"] == target_id
    assert tool.updates[1]["status"] == "PAUSED"

    rebound = _record(
        schedule_id=record.schedule_id, identity="invocation-new", generation=3,
        target_id=target_id, role=role, purpose=purpose, message=message,
        target_thread_id=target_thread_id, recipient=recipient, owner="owner-02",
    )
    current_version = due.read_due(record.schedule_id)["version"]
    reconfigured = scheduler.reconfigure(rebound, request_id="lifecycle-rebind", expected_version=current_version, actor="owner-01")
    assert reconfigured["outcome"] == "reconfigured"
    assert reconfigured["record"]["target"]["automation_id"] == target_id
    stale_owner = scheduler.prepare_host(record.schedule_id, request_id="stale-owner", expected_version=reconfigured["record"]["version"], actor="owner-01", generation=2)
    stale_generation = scheduler.prepare_host(record.schedule_id, request_id="stale-generation", expected_version=reconfigured["record"]["version"], actor="owner-02", generation=2)
    assert stale_owner["error"]["code"] == "foreign_authority"
    assert stale_generation["error"]["code"] == "stale_generation"
    assert len(tool.updates) == 2

    current_version = due.read_due(record.schedule_id)["version"]
    rebound_prepared = scheduler.prepare_host(record.schedule_id, request_id="lifecycle-rebound-active", expected_version=current_version, actor="owner-02", generation=3, project_ref="project-01", manager_ref="manager-01")
    rebound_effect = HostEffect.from_dict(rebound_prepared["effect"])
    rebound_result = executor.execute(rebound_effect)
    assert rebound_result["outcome"] == "reconciled"
    assert tool.active_ids == {target_id}
    assert len(tool.updates) == len(tool.readbacks) == len(ack_calls) == 3
    assert tool.updates[-1]["id"] == target_id
    assert tool.updates[-1]["status"] == "ACTIVE"

    current_version = due.read_due(record.schedule_id)["version"]
    replay_prepare = scheduler.prepare_host(record.schedule_id, request_id="lifecycle-rebound-active", expected_version=current_version, actor="owner-02", generation=3, project_ref="project-01", manager_ref="manager-01")
    replay_effect = HostEffect.from_dict(replay_prepare["effect"])
    replay_result = executor.execute(replay_effect)
    assert replay_prepare["outcome"] == "replayed"
    assert replay_result["replayed"] is True
    assert len(tool.updates) == len(tool.readbacks) == len(ack_calls) == 3
    assert due.read_due(record.schedule_id)["version"] == current_version


@pytest.mark.parametrize(
    ("role", "purpose", "message", "target_id", "target_thread_id", "recipient"),
    [
        ("manager", "hourly-sense-check", "manager owner context", "automation-manager", "thread-manager", "project-manager"),
        ("orchestrator", "portfolio-reconcile", "orchestrator owner context", "automation-orchestrator", "thread-orchestrator", "portfolio-orchestrator"),
    ],
)
def test_manager_and_orchestrator_role_schedules_share_lifecycle_fences(
    role, purpose, message, target_id, target_thread_id, recipient,
):
    host = RecordingHostTriggerPort()
    scheduler, due, record = _scheduler(_record(
        schedule_id="role-" + role, role=role, purpose=purpose, message=message,
        target_id=target_id, target_thread_id=target_thread_id, recipient=recipient,
    ), host_port=host)
    base_version = due.read_due(record.schedule_id)["version"]
    rejected = [
        scheduler.prepare_host(record.schedule_id, request_id="stale", expected_version=base_version + 1, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2),
        scheduler.prepare_host(record.schedule_id, request_id="foreign", expected_version=base_version, actor="foreign-owner", project_ref="project-01", manager_ref="manager-01", generation=2),
        scheduler.prepare_host(record.schedule_id, request_id="scope", expected_version=base_version, actor="owner-01", project_ref="other-project", manager_ref="manager-01", generation=2),
        scheduler.prepare_host(record.schedule_id, request_id="generation", expected_version=base_version, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=1),
    ]
    assert [result["error"]["code"] for result in rejected] == ["stale_version", "foreign_authority", "scope_mismatch", "stale_generation"]
    blocked_reconcile = scheduler.reconcile_host(record.schedule_id, request_id="blocked-host", expected_version=base_version + 1, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2)
    assert blocked_reconcile["error"]["code"] == "stale_version"
    assert host.requests == []
    assert due.read_due(record.schedule_id)["version"] == base_version
    prepared = scheduler.prepare_host(
        record.schedule_id, request_id="role-effect", expected_version=base_version,
        actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2,
    )
    assert prepared["outcome"] == "pending_host"
    effect = HostEffect.from_dict(prepared["effect"])
    assert effect.lifecycle_owner == "owner-01"
    assert effect.project_ref == "project-01"
    assert effect.manager_ref == "manager-01"
    assert effect.generation == 2
    assert effect.owner_version == base_version
    assert effect.configuration["purpose"] == purpose
    assert effect.configuration["message"] == message
    replay = scheduler.prepare_host(
        record.schedule_id, request_id="role-effect", expected_version=base_version + 1,
        actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2,
    )
    assert replay["outcome"] == "replayed"
    assert due.read_due(record.schedule_id)["version"] == base_version + 1

    active_ack = scheduler.acknowledge_host(
        record.schedule_id, request_id=effect.request_id,
        observed={"schedule_id": record.schedule_id, "state": "active", "configuration": dict(effect.configuration)},
        expected_version=base_version + 1, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2,
    )
    assert active_ack["outcome"] == "reconciled"
    paused = scheduler.prepare_host(
        record.schedule_id, request_id="role-pause", expected_version=base_version + 2,
        actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2,
        desired_state="paused",
    )
    assert paused["outcome"] == "pending_host"
    paused_effect = HostEffect.from_dict(paused["effect"])
    assert paused_effect.configuration["target"]["automation"]["status"] == "PAUSED"
    paused_ack = scheduler.acknowledge_host(
        record.schedule_id, request_id=paused_effect.request_id,
        observed={"schedule_id": record.schedule_id, "state": "paused", "configuration": dict(paused_effect.configuration)},
        expected_version=base_version + 3, actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2,
    )
    assert paused_ack["outcome"] == "reconciled"
    paused_replay = scheduler.prepare_host(
        record.schedule_id, request_id="role-pause", expected_version=base_version + 4,
        actor="owner-01", project_ref="project-01", manager_ref="manager-01", generation=2,
        desired_state="paused",
    )
    assert paused_replay["outcome"] == "replayed"
    assert due.read_due(record.schedule_id)["version"] == base_version + 4
