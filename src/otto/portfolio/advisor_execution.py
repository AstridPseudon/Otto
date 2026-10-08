"""Advisor delivery joined to maintained execution and existing allowance owner.

Policy supplies context/model/cadence and the adopted finite allowance. The
attention owner claims and settles scheduled occurrences; the role runtime owns
provider authorization/results. This module joins those public operations.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from otto.attention import DueRecord
from .advisor_delivery import AdvisorDeliveryLoop, AdvisorDeliveryPorts
from .execution import ExecutionApplication, _digest
from .execution_operations import OccurrencePreparationError, validate_owner_timeout_seconds


class AdvisorExecution:
    def __init__(self, *, execution: ExecutionApplication, ports: AdvisorDeliveryPorts | None = None,
                 allowance: Any, allowance_ref: Mapping[str, Any]) -> None:
        self.execution, self.allowance = execution, allowance
        self.allowance_ref = ResourceRef.from_dict(allowance_ref)
        self.loop = None if ports is None else AdvisorDeliveryLoop(replace(ports, role_delivery=self._deliver))

    def prepare_and_start(self, **request: Any) -> dict[str, Any]:
        """Use the same adopted allowance for an ordinary advisor launch/resume."""
        prepared = self.execution.prepare_role(role="project_advisor",
            allowance_ref=self.allowance_ref.to_dict(), **request)
        if prepared["outcome"] not in {"committed", "prepared", "replayed"}:
            return prepared
        schedule = prepared["schedule_id"]
        due = self.execution._read(schedule)
        raw = self._deliver({"schedule_id": schedule,
                             "request_id": due.in_flight_request or due.last_completed_request})
        return {**self.execution.recover(schedule_id=schedule), "runtime_result": dict(raw)}

    def prepare_scheduled(self, *, pairing: Any, schedule_id: str, task_ref: Mapping[str, Any],
                          mandate_ref: Mapping[str, Any], context_refs: tuple[Mapping[str, Any], ...],
                          prompt: str, model: str, reasoning: str, profile: str,
                          binding_schedule_id: str | None = None, timeout_seconds: int = 1200) -> dict[str, Any]:
        """Adopt runtime pins on an existing clean schedule before its claim.

        The schedule, cadence, covered slots, delivery anchor and allowance are
        preserved. The public adoption-base transition runs after attention
        claim and before gateway admission, exactly as ordinary execution does.
        """
        app = self.execution
        if self.loop is None:
            raise OccurrencePreparationError("scheduled advisor execution requires delivery ports")
        self.loop._current(pairing)
        assignment = app._current(pairing.advisor_ref, pairing.advisor_generation)
        current_value = app.due_port.read_due(schedule_id)
        if current_value is None:
            raise OccurrencePreparationError("advisor schedule is unavailable")
        current = DueRecord.from_dict(current_value)
        if (current.role != "project_advisor" or current.generation != assignment.generation
                or current.assignment_ref is None or current.assignment_ref["id"] != assignment.id
                or current.project_ref != pairing.project_ref["id"]
                or current.lifecycle_owner != app.actor):
            raise OccurrencePreparationError("advisor schedule is foreign or stale")
        if current.in_flight_request is not None or current.stop_state != "active":
            return {"outcome": "reconcile", "schedule_id": schedule_id,
                    "next_action": "inspect/reconcile the original occurrence before changing runtime pins"}
        from otto.attention import native_target_identity
        session = native_target_identity(pairing.advisor_conversation_ref)
        app._verify_native_binding(assignment, session, binding_schedule_id)
        validate_owner_timeout_seconds(timeout_seconds)
        base = assignment.payload.get("resource_adoption_base_ref") or assignment.ref.to_dict()
        target = {**dict(current.target or {}), "native_id": session, "host": "local",
                  "project_ref": dict(pairing.project_ref), "task_ref": dict(task_ref),
                  "assignment_ref": base, "mandate_ref": dict(mandate_ref),
                  "role": "project_advisor", "principal": assignment.principal,
                  "requested_model": model, "requested_reasoning": reasoning, "requested_profile": profile}
        desired = replace(current, instruction=prompt, profile=profile, manager_ref=app.actor,
            assignment_ref=base, target=target, execution_mode="continue_existing",
            allowance_ref=self.allowance_ref.to_dict(), requested_model=model, requested_reasoning=reasoning,
            context_refs=context_refs, result_owner=app.actor, timeout_seconds=timeout_seconds)
        # A deterministic config suffix makes a replay identical while avoiding
        # a stale configuration key. It never creates another schedule/slot.
        key = "advisor-runtime:" + _digest([schedule_id, target, context_refs, prompt, self.allowance_ref.to_dict()])
        desired = replace(desired, invocation_identity=current.invocation_identity.split(":runtime:")[0]
                          + ":runtime:" + key.split(":", 1)[1])
        if desired.to_dict() == current.to_dict():
            return {"outcome": "prepared", "schedule_id": schedule_id, "record": current.to_dict()}
        return self.loop.ports.attention.reconfigure(desired, request_id=key,
            expected_version=current.version, actor=app.actor)

    def _deliver(self, delivery: Mapping[str, Any]) -> Mapping[str, Any]:
        app = self.execution
        schedule_id, request_id = delivery["schedule_id"], delivery["request_id"]
        due = app._read(schedule_id)
        if request_id not in {due.in_flight_request, due.last_completed_request} or due.role != "project_advisor":
            raise OccurrencePreparationError("advisor claim is not current")
        # Resource adoption is a real owner join, never provided by the test or
        # duplicated in a run controller. Failure here has no provider effect.
        due = app._resources(due)
        if due.allowance_ref != self.allowance_ref.to_dict():
            raise OccurrencePreparationError("advisor occurrence allowance differs from its adopted pool")
        validate_host = getattr(app.runtime.adapter, "validate_owner_host_composition", None)
        if callable(validate_host):
            validate_host(role=due.role, profile=due.profile)
        actor = app.binding.authenticated_actor(app.actor)
        reservation = self.allowance.reserve(self.allowance_ref,
            "advisor-turn-" + _digest([schedule_id, request_id])[:28], 1,
            logical_request_key=request_id + ":reserve", actor=actor)
        try:
            result = app.start(schedule_id=schedule_id, settle=False)
        except Exception:
            self._settle(reservation, schedule_id, request_id, actor)
            raise
        self._settle(reservation, schedule_id, request_id, actor)
        return result

    def _settle(self, reservation: Any, schedule: str, request: str, actor: Any) -> None:
        # A reserve replay returns the original held snapshot. Settlement must
        # use current custody, including an uncertain reservation after restart.
        ref = reservation.ref
        reservation = self.allowance.get_reservation(ResourceRef(ref.authority, ref.kind, ref.id))
        if reservation is None:
            raise OccurrencePreparationError("advisor reservation is unavailable")
        status = reservation.status.value
        due = self.execution._read(schedule)
        attempt = (due.host_evidence or {}).get("gateway_attempt")
        result = attempt.get("result") if isinstance(attempt, Mapping) else None
        if isinstance(result, Mapping) and result.get("outcome") == "succeeded":
            if status == "consumed" and reservation.charged_units == 1:
                return
            self.allowance.settle(reservation, 1, logical_request_key=request + ":settle", actor=actor)
        elif attempt is not None:
            if status == "uncertain":
                return
            self.allowance.mark_uncertain(reservation, logical_request_key=request + ":uncertain", actor=actor)
        else:
            if status == "released":
                return
            self.allowance.release(reservation, logical_request_key=request + ":release", actor=actor)

    def wake_once(self, **request: Any) -> dict[str, Any]:
        if self.loop is None:
            raise OccurrencePreparationError("scheduled advisor execution requires delivery ports")
        return self.loop.wake_once(**request)

    def reconcile_allowance(self, *, schedule_id: str) -> dict[str, Any]:
        """Settle a retained reservation from owner result, without provider replay."""
        due = self.execution._read(schedule_id)
        request = due.in_flight_request or due.last_completed_request
        if not isinstance(request, str):
            raise OccurrencePreparationError("advisor occurrence has no recorded request")
        actor = self.execution.binding.authenticated_actor(self.execution.actor)
        reservation = self.allowance.reserve(self.allowance_ref,
            "advisor-turn-" + _digest([schedule_id, request])[:28], 1,
            logical_request_key=request + ":reserve", actor=actor)
        self._settle(reservation, schedule_id, request, actor)
        return {"outcome": "reconciled", "schedule_id": schedule_id, "provider_called": False}
