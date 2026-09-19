"""Bounded SUP-03 request-path integration over the typed host executor."""

from datetime import datetime, timezone

import pytest

from otto.attention import DueRecord, DurableAttention, InMemoryDueRecordPort, RecordingAttentionPort
from otto.host_bridge import automation_update_request
from otto.portfolio.lifecycle import LifecycleIntegrationError, PortfolioLifecycleIntegration


NOW = datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc)


def _record(schedule_id: str, *, role: str, target_id: str) -> DueRecord:
    return DueRecord(
        schedule_id=schedule_id,
        recipient=role,
        instruction=f"perform the {role} lifecycle check",
        profile="normal",
        anchor="2026-09-19T02:00:00Z",
        interval_seconds=3600,
        last_covered_slot=-1,
        invocation_identity=f"{role}-invocation-1",
        target={
            "host": "codex",
            "native_id": target_id,
            "automation_id": target_id,
            "targetThreadId": f"thread-{role}",
            "automation": {
                "name": f"otto-{role}-lifecycle",
                "kind": "heartbeat",
                "prompt": f"{role} lifecycle policy",
                "rrule": "RRULE:FREQ=HOURLY;INTERVAL=1",
                "status": "ACTIVE",
                "targetThreadId": f"thread-{role}",
                "notificationPolicy": "failed_runs_only",
            },
        },
        role=role,
        purpose=f"{role} lifecycle",
        message=f"{role} lifecycle policy",
        lifecycle_owner="owner-root",
        owner="owner-root",
        project_ref="project-root",
        manager_ref="manager-root",
        generation=2,
    )


class _Host:
    def __init__(self) -> None:
        self.settings = {}
        self.update_calls = []
        self.read_calls = []
        self.lost_reads = 0
        self.fail_pauses = False

    def update(self, request):
        self.update_calls.append(dict(request))
        if self.fail_pauses and request["status"] == "PAUSED":
            raise RuntimeError("pause unavailable")
        self.settings[request["id"]] = dict(request)
        return {"accepted": True, "id": request["id"]}

    def read(self, effect, _response):
        self.read_calls.append(effect.request_id)
        if self.lost_reads:
            self.lost_reads -= 1
            return {"schedule_id": effect.schedule_id, "state": "pending", "response_lost": True}
        expected = automation_update_request(effect)
        request = self.settings.get(expected["id"], expected)
        return {**request, "schedule_id": effect.schedule_id, "state": request["status"].lower()}


def _integration(projects=None, host=None, binding=None, attention=None):
    if attention is None:
        due = InMemoryDueRecordPort()
        attention = DurableAttention(RecordingAttentionPort(), due_port=due, host_mode="durable-host", clock=lambda: NOW)
        manager = _record("schedule-manager", role="manager", target_id="automation-manager")
        portfolio = _record("schedule-portfolio", role="orchestrator", target_id="automation-portfolio")
        assert attention.schedule(manager, request_id="schedule-manager")["outcome"] == "scheduled"
        assert attention.schedule(portfolio, request_id="schedule-portfolio")["outcome"] == "scheduled"
    else:
        due = attention.due_port
    host = host or _Host()
    raw_projects = projects or {"project-a": "active", "project-b": "active", "project-c": "terminal"}
    canonical_projects = {
        project_id: value if isinstance(value, dict) else {
            "state": value,
            "project_ref": f"{project_id}@rev-1",
            "task_ref": f"task-{project_id}@rev-1",
            "lifecycle_owner": "owner-root",
            "generation": 2,
        }
        for project_id, value in raw_projects.items()
    }
    integration = PortfolioLifecycleIntegration(
        attention,
        manager_schedule_id="schedule-manager",
        portfolio_schedule_id="schedule-portfolio",
        lifecycle_owner="owner-root",
        manager_actor="manager-actor",
        orchestrator_actor="orchestrator-actor",
        generation=2,
        orchestrator_binding=binding or {"role": "orchestrator", "native_id": "orch-native", "root_id": "root", "generation": 2, "status": "active"},
        projects=canonical_projects,
        automation_update=host.update,
        read_settings=host.read,
    )
    return integration, attention, due, host


def _guard(project_id):
    return {"project_ref": f"{project_id}@rev-1", "task_ref": f"task-{project_id}@rev-1", "lifecycle_owner": "owner-root"}


def _evidence(project_id):
    return {
        "project_ref": f"{project_id}@rev-1",
        "task_ref": f"task-{project_id}@rev-1",
        "acceptance": {"status": "passed", "ref": "acceptance-proof"},
        "publication": {"status": "verified", "ref": "publication-proof"},
        "remote": {"status": "verified", "ref": "remote-proof"},
        "runtime": {"status": "qualified", "ref": "runtime-proof"},
    }


def test_real_request_path_closes_two_projects_to_zero_then_resumes_same_ids():
    integration, attention, due, host = _integration()

    first = integration.activate("project-a", request_id="activate-a", actor="manager-actor", generation=2, **_guard("project-a"))
    assert first["outcome"] == "reconciled"
    assert first["desired_states"] == {"manager": "active", "portfolio": "active"}

    manager_close = integration.manager_close("project-a", request_id="close-a", actor="manager-actor", generation=2, **_guard("project-a"))
    assert manager_close["outcome"] == "reconciled"
    assert manager_close["closing_project_ids"] == ["project-a"]
    assert manager_close["desired_states"] == {"manager": "active", "portfolio": "active"}

    terminal_a = integration.orchestrator_terminal_close("project-a", request_id="terminal-a", actor="orchestrator-actor", generation=2, evidence=_evidence("project-a"), **_guard("project-a"))
    assert terminal_a["outcome"] == "reconciled"
    assert terminal_a["desired_states"] == {"manager": "active", "portfolio": "active"}

    integration.manager_close("project-b", request_id="close-b", actor="manager-actor", generation=2, **_guard("project-b"))
    zero = integration.orchestrator_terminal_close("project-b", request_id="terminal-b", actor="orchestrator-actor", generation=2, evidence=_evidence("project-b"), **_guard("project-b"))
    assert zero["outcome"] == "reconciled"
    assert zero["active_project_ids"] == []
    assert zero["desired_states"] == {"manager": "paused", "portfolio": "paused"}
    assert due.read_due("schedule-manager")["host_state"] == "paused"
    assert due.read_due("schedule-portfolio")["host_state"] == "paused"

    resumed = integration.resume("project-c", request_id="activate-c", actor="orchestrator-actor", generation=2, **_guard("project-c"))
    assert resumed["outcome"] == "reconciled"
    assert resumed["desired_states"] == {"manager": "active", "portfolio": "active"}
    assert due.read_due("schedule-manager")["target"]["native_id"] == "automation-manager"
    assert due.read_due("schedule-portfolio")["target"]["native_id"] == "automation-portfolio"
    assert due.read_due("schedule-manager")["purpose"] == "manager lifecycle"
    assert due.read_due("schedule-manager")["message"] == "manager lifecycle policy"
    assert due.read_due("schedule-manager")["interval_seconds"] == 3600
    assert {request["id"] for request in host.update_calls} == {"automation-manager", "automation-portfolio"}
    assert all(item["readback_exact"] for item in resumed["schedules"].values())
    assert all(item["acknowledgement"]["outcome"] == "reconciled" for item in resumed["schedules"].values())
    assert attention.capability["durable"] is True


def test_manager_and_orchestrator_authority_and_blocked_terminal_boundary():
    integration, _attention, due, _host = _integration({"project-a": "active"})
    with pytest.raises(LifecycleIntegrationError, match="foreign lifecycle authority"):
        integration.manager_close("project-a", request_id="foreign-close", actor="orchestrator-actor", generation=2, **_guard("project-a"))
    blocked = integration.manager_close("project-a", request_id="blocked-close", actor="manager-actor", generation=2, blocked=True, **_guard("project-a"))
    assert blocked["outcome"] == "reconciled"
    held = integration.orchestrator_terminal_close("project-a", request_id="blocked-terminal", actor="orchestrator-actor", generation=2, evidence=_evidence("project-a"), **_guard("project-a"))
    assert held["outcome"] == "held"
    assert due.read_due("schedule-portfolio")["host_state"] == "active"
    verified = integration.orchestrator_verify(actor="orchestrator-actor", generation=2)
    assert verified["outcome"] == "verified"
    assert verified["binding"]["native_id"] == "orch-native"
    assert verified["manager_record"]["generation"] == 2


def test_lost_response_replay_recovers_without_second_update():
    integration, _attention, due, host = _integration({"project-a": "active"})
    host.lost_reads = 2
    lost = integration.activate("project-a", request_id="lost-activate", actor="manager-actor", generation=2, **_guard("project-a"))
    assert lost["outcome"] == "pending_host"
    assert all(item["receipt"]["outcome"] == "response_lost" for item in lost["schedules"].values())
    calls_after_loss = len(host.update_calls)
    replay = integration.activate("project-a", request_id="lost-activate", actor="manager-actor", generation=2, **_guard("project-a"))
    assert replay["outcome"] == "reconciled"
    assert len(host.update_calls) == calls_after_loss
    assert all(item["receipt"]["replayed"] is True for item in replay["schedules"].values())
    assert all(item["readback_exact"] for item in replay["schedules"].values())
    assert due.read_due("schedule-manager")["host_state"] == "active"
    assert due.read_due("schedule-portfolio")["host_state"] == "active"

    restarted = _integration({"project-a": "active"}, host=host, attention=_attention)[0]
    restarted_replay = restarted.resume("project-a", request_id="lost-activate", actor="manager-actor", generation=2, **_guard("project-a"))
    assert restarted_replay["outcome"] == "reconciled"
    assert len(host.update_calls) == calls_after_loss


def test_failed_pause_is_pending_then_reconciles_with_a_new_owner_request():
    integration, _attention, due, host = _integration({"project-a": "active"})
    assert integration.activate("project-a", request_id="initial", actor="manager-actor", generation=2, **_guard("project-a"))["outcome"] == "reconciled"
    assert integration.manager_close("project-a", request_id="close", actor="manager-actor", generation=2, **_guard("project-a"))["outcome"] == "reconciled"
    host.fail_pauses = True
    failed = integration.orchestrator_terminal_close("project-a", request_id="terminal-fail", actor="orchestrator-actor", generation=2, evidence=_evidence("project-a"), **_guard("project-a"))
    assert failed["outcome"] == "pending_host"
    assert due.read_due("schedule-portfolio")["host_state"] == "failed"
    host.fail_pauses = False
    recovered = integration.reconcile(request_id="terminal-retry", actor="orchestrator-actor", generation=2)
    assert recovered["outcome"] == "reconciled"
    assert due.read_due("schedule-portfolio")["host_state"] == "paused"


def test_missing_binding_and_stale_request_are_rejected_before_lifecycle_mutation():
    with pytest.raises(LifecycleIntegrationError, match="orchestrator_binding"):
        _integration({"project-a": "active"}, binding={"role": "manager", "native_id": "wrong", "root_id": "root", "generation": 2})


def test_canonical_project_task_revision_and_owner_fences_reject_stale_requests():
    integration, _attention, _due, _host = _integration({"project-a": "active"})
    with pytest.raises(LifecycleIntegrationError, match="stale project revision"):
        integration.activate("project-a", request_id="stale-project", actor="manager-actor", generation=2, project_ref="project-a@rev-0", task_ref="task-project-a@rev-1", lifecycle_owner="owner-root")
    with pytest.raises(LifecycleIntegrationError, match="stale task revision"):
        integration.activate("project-a", request_id="stale-task", actor="manager-actor", generation=2, project_ref="project-a@rev-1", task_ref="task-project-a@rev-0", lifecycle_owner="owner-root")
    with pytest.raises(LifecycleIntegrationError, match="foreign lifecycle owner"):
        integration.activate("project-a", request_id="foreign-owner", actor="manager-actor", generation=2, project_ref="project-a@rev-1", task_ref="task-project-a@rev-1", lifecycle_owner="owner-other")


def test_terminal_close_requires_task_acceptance_publication_remote_and_runtime_evidence():
    integration, _attention, _due, _host = _integration({"project-a": "active"})
    integration.manager_close("project-a", request_id="close-for-evidence", actor="manager-actor", generation=2, **_guard("project-a"))
    with pytest.raises(LifecycleIntegrationError, match="acceptance, publication, remote and runtime"):
        integration.orchestrator_terminal_close("project-a", request_id="missing-evidence", actor="orchestrator-actor", generation=2, project_ref="project-a@rev-1", task_ref="task-project-a@rev-1", lifecycle_owner="owner-root", evidence={"acceptance": {"status": "passed"}})
    assert integration.orchestrator_verify(actor="orchestrator-actor", generation=2)["projects"]["project-a"] == "closing"


def test_rebind_fences_old_generation_and_owner_while_new_owner_reconciles():
    integration, attention, due, host = _integration({"project-a": "active"})
    pending = attention.prepare_host("schedule-manager", request_id="held-before-rebind", expected_version=1, actor="owner-root", generation=2)
    assert pending["outcome"] == "pending_host"
    effect = pending["effect"]
    rebound = integration.rebind_owner(request_id="rebind", actor="owner-root", new_lifecycle_owner="owner-next", generation=3)
    assert rebound["outcome"] == "rebound"
    stale = attention.acknowledge_host("schedule-manager", request_id=effect["request_id"], observed={"schedule_id": "schedule-manager", "state": "active", "configuration": effect["configuration"]}, expected_version=2, actor="owner-root", generation=2)
    assert stale["outcome"] == "rejected"
    assert stale["error"]["code"] == "foreign_authority"
    with pytest.raises(LifecycleIntegrationError, match="stale lifecycle generation"):
        integration.activate("project-a", request_id="old-generation", actor="manager-actor", generation=2, project_ref="project-a@rev-1", task_ref="task-project-a@rev-1", lifecycle_owner="owner-root")
    fresh = integration.activate("project-a", request_id="new-generation", actor="manager-actor", generation=3, project_ref="project-a@rev-1", task_ref="task-project-a@rev-1", lifecycle_owner="owner-next")
    assert fresh["outcome"] == "reconciled"
    assert due.read_due("schedule-manager")["lifecycle_owner"] == "owner-next"
    assert due.read_due("schedule-manager")["generation"] == 3
    assert host.update_calls[-1]["id"] == "automation-portfolio"
