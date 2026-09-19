"""Bounded owner lifecycle integration over the existing host-effect seam.

This module connects finite project lifecycle requests to two existing
``DueRecord`` schedules.  It does not create a project store, scheduler, or
host transport.  The supplied :class:`~otto.attention.DurableAttention` owns
the records and the supplied callbacks represent the already-supported host
operation and persisted-settings readback.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from ..attention import DurableAttention, DueRecord
from ..host_bridge import DeterministicHostExecutor, HostEffect


class LifecycleIntegrationError(ValueError):
    """A lifecycle request is outside the configured owner boundary."""


_PROJECT_STATES = frozenset({"active", "closing", "blocked", "terminal"})


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise LifecycleIntegrationError(f"{field} must be non-blank text")
    return value.strip()


def _generation(value: Any, field: str = "generation") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LifecycleIntegrationError(f"{field} must be a positive integer")
    return value


def _copy(value: Any, field: str = "value") -> Any:
    import json

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise LifecycleIntegrationError(f"{field} must contain JSON values") from exc


class PortfolioLifecycleIntegration:
    """Route authorized project lifecycle requests through typed host effects.

    ``manager_schedule_id`` and ``portfolio_schedule_id`` identify existing
    owner records.  The manager schedule stays active while any project is
    active, closing, or blocked; the portfolio schedule is active only while
    at least one project is active.  A later activation therefore reconciles
    the paused portfolio schedule immediately through this entrypoint.

    The two actor strings are request authorities.  ``lifecycle_owner`` is the
    owner fence stored in both due records and can be replaced only through
    :meth:`rebind_owner`, which preserves the native schedule IDs.
    """

    def __init__(
        self,
        attention: DurableAttention,
        *,
        manager_schedule_id: str,
        portfolio_schedule_id: str,
        lifecycle_owner: str,
        manager_actor: str,
        orchestrator_actor: str,
        generation: int,
        orchestrator_binding: Mapping[str, Any],
        projects: Mapping[str, str],
        automation_update: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        read_settings: Callable[[HostEffect, Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        if not isinstance(attention, DurableAttention):
            raise TypeError("attention must be a DurableAttention")
        self.attention = attention
        self.manager_schedule_id = _text(manager_schedule_id, "manager_schedule_id")
        self.portfolio_schedule_id = _text(portfolio_schedule_id, "portfolio_schedule_id")
        if self.manager_schedule_id == self.portfolio_schedule_id:
            raise LifecycleIntegrationError("manager and portfolio schedules must be distinct")
        self._lifecycle_owner = _text(lifecycle_owner, "lifecycle_owner")
        self.manager_actor = _text(manager_actor, "manager_actor")
        self.orchestrator_actor = _text(orchestrator_actor, "orchestrator_actor")
        self._generation = _generation(generation)
        self.orchestrator_binding = self._validate_binding(orchestrator_binding, self._generation)
        if not isinstance(projects, Mapping):
            raise LifecycleIntegrationError("projects must be an object")
        self._projects: dict[str, str] = {}
        for project_id, state in projects.items():
            key = _text(project_id, "project_id")
            state_value = _text(state, f"projects[{key}]")
            if state_value not in _PROJECT_STATES:
                raise LifecycleIntegrationError(f"unsupported project state: {state_value}")
            self._projects[key] = state_value
        for schedule_id, role in (
            (self.manager_schedule_id, "manager"),
            (self.portfolio_schedule_id, "orchestrator"),
        ):
            record = self._record(schedule_id)
            if record is None:
                raise LifecycleIntegrationError(f"missing {role} schedule: {schedule_id}")
            if record.lifecycle_owner != self._lifecycle_owner:
                raise LifecycleIntegrationError(f"{role} schedule has a different lifecycle owner")
            if record.generation != self._generation:
                raise LifecycleIntegrationError(f"{role} schedule has a different generation")
            if record.role != role:
                raise LifecycleIntegrationError(f"{role} schedule role is not {role}")
        self._executor = DeterministicHostExecutor(
            automation_update,
            read_settings,
            self._acknowledge,
        )

    @staticmethod
    def _validate_binding(value: Mapping[str, Any], generation: int) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LifecycleIntegrationError("orchestrator_binding must be an object")
        binding = _copy(dict(value), "orchestrator_binding")
        if binding.get("role") != "orchestrator":
            raise LifecycleIntegrationError("orchestrator_binding.role must be orchestrator")
        _text(binding.get("native_id"), "orchestrator_binding.native_id")
        _text(binding.get("root_id"), "orchestrator_binding.root_id")
        if binding.get("generation") != generation:
            raise LifecycleIntegrationError("orchestrator binding generation is stale")
        if binding.get("status", "active") not in {"active", "qualified"}:
            raise LifecycleIntegrationError("orchestrator binding is not active")
        return binding

    def _record(self, schedule_id: str) -> Optional[DueRecord]:
        return self.attention._read(schedule_id)  # owner read, never a direct store access

    def _authorize(self, actor: str, allowed: str) -> None:
        if _text(actor, "actor") != allowed:
            raise LifecycleIntegrationError("foreign lifecycle authority")

    def _check_generation(self, generation: int) -> None:
        if _generation(generation) != self._generation:
            raise LifecycleIntegrationError("stale lifecycle generation")

    def _acknowledge(self, effect: HostEffect, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        record = self._record(effect.schedule_id)
        if record is None:
            return {"outcome": "unknown", "schedule_id": effect.schedule_id, "automatic_action": False}
        return self.attention.acknowledge_host(
            effect.schedule_id,
            request_id=effect.request_id,
            observed=observation,
            expected_version=record.version,
            actor=self._lifecycle_owner,
            project_ref=effect.project_ref,
            manager_ref=effect.manager_ref,
            generation=effect.generation,
        )

    def _run_schedule(self, schedule_id: str, *, request_id: str, desired_state: str) -> dict[str, Any]:
        record = self._record(schedule_id)
        if record is None:
            return {"outcome": "unknown", "schedule_id": schedule_id, "automatic_action": False}
        prepared = self.attention.prepare_host(
            schedule_id,
            request_id=request_id,
            expected_version=record.version,
            actor=self._lifecycle_owner,
            project_ref=record.project_ref,
            manager_ref=record.manager_ref,
            generation=self._generation,
            desired_state=desired_state,
        )
        if prepared.get("outcome") in {"unknown", "rejected"}:
            return {"schedule_id": schedule_id, "prepared": prepared, "outcome": prepared["outcome"]}
        effect = HostEffect.from_dict(prepared["effect"])
        receipt = self._executor.recover(effect) if prepared.get("outcome") == "replayed" else self._executor.execute(effect)
        return {
            "schedule_id": schedule_id,
            "desired_state": desired_state,
            "prepared": prepared,
            "receipt": receipt,
            "outcome": receipt.get("outcome"),
            "readback_exact": bool(receipt.get("readback", {}).get("readback_exact")),
            "acknowledgement": receipt.get("acknowledgement"),
        }

    def _desired_states(self) -> dict[str, str]:
        active = any(state == "active" for state in self._projects.values())
        manager_needed = active or any(state in {"closing", "blocked"} for state in self._projects.values())
        return {
            "manager": "active" if manager_needed else "paused",
            "portfolio": "active" if active else "paused",
        }

    def _reconcile(self, *, request_id: str, action: str, generation: int) -> dict[str, Any]:
        self._check_generation(generation)
        request = _text(request_id, "request_id")
        desired = self._desired_states()
        manager = self._run_schedule(self.manager_schedule_id, request_id=f"{request}:manager", desired_state=desired["manager"])
        portfolio = self._run_schedule(self.portfolio_schedule_id, request_id=f"{request}:portfolio", desired_state=desired["portfolio"])
        results = {"manager": manager, "portfolio": portfolio}
        outcomes = [item.get("outcome") for item in results.values()]
        if all(value in {"reconciled", "replayed"} for value in outcomes):
            outcome = "replayed" if all(value == "replayed" for value in outcomes) else "reconciled"
        else:
            outcome = "pending_host"
        return {
            "outcome": outcome,
            "action": action,
            "request_id": request,
            "generation": self._generation,
            "lifecycle_owner": self._lifecycle_owner,
            "projects": dict(self._projects),
            "active_project_ids": sorted(project_id for project_id, state in self._projects.items() if state == "active"),
            "closing_project_ids": sorted(project_id for project_id, state in self._projects.items() if state in {"closing", "blocked"}),
            "desired_states": desired,
            "schedules": results,
            "automatic_action": False,
        }

    def activate(self, project_id: str, *, request_id: str, actor: str, generation: int) -> dict[str, Any]:
        """Activate/resume a project and reconcile both schedules immediately."""

        self._check_generation(generation)
        operator = _text(actor, "actor")
        if operator not in {self.manager_actor, self.orchestrator_actor}:
            raise LifecycleIntegrationError("activation requires manager or orchestrator authority")
        project = _text(project_id, "project_id")
        self._projects[project] = "active"
        return self._reconcile(request_id=request_id, action="activate", generation=generation)

    def resume(self, project_id: str, *, request_id: str, actor: str, generation: int) -> dict[str, Any]:
        """Resume a project from zero-active state through the same path."""

        result = self.activate(project_id, request_id=request_id, actor=actor, generation=generation)
        result["action"] = "resume"
        return result

    def manager_close(self, project_id: str, *, request_id: str, actor: str, generation: int, blocked: bool = False) -> dict[str, Any]:
        """Record an authorized manager close request and reconcile schedules."""

        self._authorize(actor, self.manager_actor)
        self._check_generation(generation)
        project = _text(project_id, "project_id")
        if self._projects.get(project) not in {"active", "closing", "blocked"}:
            raise LifecycleIntegrationError("manager close requires an active or closing project")
        self._projects[project] = "blocked" if blocked else "closing"
        return self._reconcile(request_id=request_id, action="manager_close", generation=generation)

    def orchestrator_verify(self, *, actor: str, generation: int) -> dict[str, Any]:
        """Perform the independent orchestrator owner check without mutation."""

        self._authorize(actor, self.orchestrator_actor)
        self._check_generation(generation)
        return {
            "outcome": "verified",
            "generation": self._generation,
            "binding": _copy(self.orchestrator_binding),
            "projects": dict(self._projects),
            "manager_record": None if self._record(self.manager_schedule_id) is None else self._record(self.manager_schedule_id).to_dict(),
            "portfolio_record": None if self._record(self.portfolio_schedule_id) is None else self._record(self.portfolio_schedule_id).to_dict(),
            "automatic_action": False,
        }

    def reconcile(self, *, request_id: str, actor: str, generation: int) -> dict[str, Any]:
        """Retry persisted host effects without changing project lifecycle."""

        operator = _text(actor, "actor")
        if operator not in {self.manager_actor, self.orchestrator_actor}:
            raise LifecycleIntegrationError("reconciliation requires manager or orchestrator authority")
        return self._reconcile(request_id=request_id, action="reconcile", generation=generation)

    def orchestrator_terminal_close(self, project_id: str, *, request_id: str, actor: str, generation: int) -> dict[str, Any]:
        """Terminally close a manager-closing project under orchestrator authority."""

        self._authorize(actor, self.orchestrator_actor)
        self._check_generation(generation)
        project = _text(project_id, "project_id")
        if self._projects.get(project) != "closing":
            state = self._projects.get(project)
            if state == "blocked":
                return {"outcome": "held", "reason": "blocked project requires recovery before terminal close", "project_id": project, "generation": self._generation, "automatic_action": False}
            raise LifecycleIntegrationError("terminal close requires manager state closing")
        self._projects[project] = "terminal"
        return self._reconcile(request_id=request_id, action="orchestrator_terminal_close", generation=generation)

    def rebind_owner(self, *, request_id: str, actor: str, new_lifecycle_owner: str, generation: int) -> dict[str, Any]:
        """Replace both schedule owners while retaining their native IDs."""

        self._authorize(actor, self._lifecycle_owner)
        next_generation = _generation(generation)
        if next_generation <= self._generation:
            raise LifecycleIntegrationError("replacement generation must advance")
        new_owner = _text(new_lifecycle_owner, "new_lifecycle_owner")
        results = {}
        for schedule_id in (self.manager_schedule_id, self.portfolio_schedule_id):
            current = self._record(schedule_id)
            if current is None:
                return {"outcome": "unknown", "schedule_id": schedule_id, "automatic_action": False}
            desired = DueRecord.from_dict({
                **current.to_dict(),
                "invocation_identity": f"{current.invocation_identity}:generation-{next_generation}",
                "generation": next_generation,
                "lifecycle_owner": new_owner,
                "host_state": "unknown",
                "host_evidence": None,
            })
            results[schedule_id] = self.attention.reconfigure(
                desired,
                request_id=f"{_text(request_id, 'request_id')}:{schedule_id}",
                expected_version=current.version,
                actor=self._lifecycle_owner,
            )
            if results[schedule_id].get("outcome") not in {"reconfigured", "replayed"}:
                return {"outcome": "rejected", "results": results, "automatic_action": False}
        self._lifecycle_owner = new_owner
        self._generation = next_generation
        self.orchestrator_binding = {**self.orchestrator_binding, "generation": next_generation}
        return {"outcome": "rebound", "generation": next_generation, "lifecycle_owner": new_owner, "results": results, "automatic_action": False}


__all__ = ["LifecycleIntegrationError", "PortfolioLifecycleIntegration"]
