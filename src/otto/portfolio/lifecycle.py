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
    active, closing, or blocked; the portfolio schedule remains active through
    closing and blocked verification so the orchestrator can finish the
    lifecycle. Both schedules pause only when every project is terminal.

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
        projects: Mapping[str, Mapping[str, Any]],
        automation_update: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        read_settings: Callable[[HostEffect, Mapping[str, Any]], Mapping[str, Any]],
        owner_operations: Any = None,
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
        self.owner_operations = owner_operations
        self.orchestrator_binding = self._validate_binding(orchestrator_binding, self._generation)
        if not isinstance(projects, Mapping):
            raise LifecycleIntegrationError("projects must be an object")
        self._projects: dict[str, str] = {}
        self._project_context: dict[str, dict[str, Any]] = {}
        for project_id, context in projects.items():
            key = _text(project_id, "project_id")
            if not isinstance(context, Mapping):
                raise LifecycleIntegrationError(f"projects[{key}] must include canonical refs and owner fence")
            state_value = _text(context.get("state"), f"projects[{key}].state")
            if state_value not in _PROJECT_STATES:
                raise LifecycleIntegrationError(f"unsupported project state: {state_value}")
            if self.owner_operations is None:
                project_ref = _text(context.get("project_ref"), f"projects[{key}].project_ref")
                task_ref = _text(context.get("task_ref"), f"projects[{key}].task_ref")
            else:
                project_ref = _copy(context.get("project_ref"), f"projects[{key}].project_ref")
                task_ref = _copy(context.get("task_ref"), f"projects[{key}].task_ref")
                if not isinstance(project_ref, Mapping) or not isinstance(task_ref, Mapping):
                    raise LifecycleIntegrationError(f"projects[{key}] canonical refs must be objects")
            owner = _text(context.get("lifecycle_owner", self._lifecycle_owner), f"projects[{key}].lifecycle_owner")
            if owner != self._lifecycle_owner:
                raise LifecycleIntegrationError(f"projects[{key}] has a different lifecycle owner")
            context_generation = _generation(context.get("generation", self._generation), f"projects[{key}].generation")
            if context_generation != self._generation:
                raise LifecycleIntegrationError(f"projects[{key}] has a different generation")
            self._projects[key] = state_value
            self._project_context[key] = {
                "project_ref": project_ref,
                "task_ref": task_ref,
                "lifecycle_owner": owner,
                "generation": context_generation,
                "manager_ref": _copy(context.get("manager_ref"), f"projects[{key}].manager_ref") if context.get("manager_ref") is not None else None,
            }
            if self.owner_operations is not None and self._project_context[key]["manager_ref"] is None:
                raise LifecycleIntegrationError(f"projects[{key}] must include manager_ref for canonical lifecycle ownership")
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

    @staticmethod
    def _same_ref(left: Any, right: Any) -> bool:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            return all(left.get(key) == right.get(key) for key in ("authority", "kind", "id", "revision"))
        return left == right

    def _project_guard(self, project_id: str, *, project_ref: Any, task_ref: Any, lifecycle_owner: str, generation: int) -> dict[str, Any]:
        project = _text(project_id, "project_id")
        context = self._project_context.get(project)
        if context is None:
            raise LifecycleIntegrationError("unknown project lifecycle identity")
        self._check_generation(generation)
        if _text(lifecycle_owner, "lifecycle_owner") != self._lifecycle_owner:
            raise LifecycleIntegrationError("foreign lifecycle owner")
        if self.owner_operations is not None:
            current = self._owner_read(project)
            if not self._same_ref(project_ref, current.get("project_ref")):
                raise LifecycleIntegrationError("stale project revision")
            if not self._same_ref(task_ref, current.get("task_ref")):
                raise LifecycleIntegrationError("stale task revision")
            return context
        if _text(project_ref, "project_ref") != context["project_ref"]:
            raise LifecycleIntegrationError("stale project revision")
        if _text(task_ref, "task_ref") != context["task_ref"]:
            raise LifecycleIntegrationError("stale task revision")
        return context

    @staticmethod
    def _revision(ref: Any, field: str) -> str:
        if isinstance(ref, Mapping):
            return _text(ref.get("revision"), field + ".revision")
        value = _text(ref, field)
        if "@" not in value:
            raise LifecycleIntegrationError(field + " must carry a pinned revision")
        return _text(value.rsplit("@", 1)[1], field + ".revision")

    def _owner_read(self, project_id: str) -> Mapping[str, Any]:
        if self.owner_operations is None:
            return {}
        context = self._project_context[project_id]
        value = self.owner_operations.read_project_lifecycle(
            context["project_ref"], context["task_ref"], context["manager_ref"], actor=self.manager_actor,
        )
        if not isinstance(value, Mapping) or value.get("outcome") != "read":
            raise LifecycleIntegrationError("canonical lifecycle read was not accepted")
        if value.get("generation") != self._generation:
            raise LifecycleIntegrationError("canonical manager generation is stale")
        return value

    def _owner_transition(self, project_id: str, *, request_id: str, intent: str, evidence: Mapping[str, Any]) -> None:
        """Use the public owner transition before updating Otto's cache.

        The cache remains only a projection for schedule reconciliation.  A
        configured canonical owner owns the current refs, lifecycle intent and
        transaction receipt.
        """

        if self.owner_operations is None:
            self._projects[project_id] = "terminal" if intent == "terminal" else intent
            return
        context = self._project_context[project_id]
        current = self._owner_read(project_id)
        project_ref = current.get("project_ref")
        task_ref = current.get("task_ref")
        manager_ref = current.get("manager_ref")
        value = self.owner_operations.transition_project_lifecycle(
            project_ref, task_ref, manager_ref,
            actor=self.manager_actor, request_id=request_id,
            expected_generation=current["generation"],
            expected_project_revision=self._revision(project_ref, "canonical project_ref"),
            expected_task_revision=self._revision(task_ref, "canonical task_ref"),
            intent=intent, evidence=evidence,
            obligation={"required_task": task_ref, "lifecycle_owner": self._lifecycle_owner},
        )
        if not isinstance(value, Mapping) or value.get("outcome") not in {"transitioned", "replayed"}:
            raise LifecycleIntegrationError("canonical lifecycle transition was not accepted")
        state = value.get("state")
        self._projects[project_id] = "terminal" if state == "completed" else intent
        context["project_ref"] = value.get("project_ref", project_ref)
        context["task_ref"] = value.get("task_ref", task_ref)
        context["manager_ref"] = value.get("manager_ref", manager_ref)

    def _owner_host_acknowledgement(self, project_id: str, result: dict[str, Any], *, request_id: str) -> None:
        """Attach the durable schedule/readback acknowledgement to its intent."""

        if self.owner_operations is None:
            return
        intent = self._projects[project_id]
        self._owner_transition(
            project_id, request_id=request_id + ":host-ack", intent=intent,
            evidence={"host_effects": _copy(result["schedules"], "host effects")},
        )
        result["project_context"] = _copy(self._project_context, "project_context")

    def _terminal_evidence(self, project_id: str, evidence: Mapping[str, Any], *, project_ref: str, task_ref: str, lifecycle_owner: str, generation: int) -> dict[str, Any]:
        if not isinstance(evidence, Mapping):
            raise LifecycleIntegrationError("terminal close requires evidence")
        self._project_guard(project_id, project_ref=project_ref, task_ref=task_ref, lifecycle_owner=lifecycle_owner, generation=generation)
        required = {
            "acceptance": "passed",
            "publication": "verified",
            "remote": "verified",
            "runtime": "qualified",
        }
        for key, outcome in required.items():
            item = evidence.get(key)
            if not isinstance(item, Mapping):
                raise LifecycleIntegrationError("terminal close requires acceptance, publication, remote and runtime evidence")
            try:
                _text(item.get("ref"), f"terminal evidence.{key}.ref")
            except LifecycleIntegrationError as exc:
                raise LifecycleIntegrationError("terminal close requires acceptance, publication, remote and runtime evidence") from exc
            if item.get("status") != outcome:
                raise LifecycleIntegrationError(f"terminal evidence {key} is not {outcome}")
        completion = evidence.get("task_completion")
        if not isinstance(completion, Mapping):
            raise LifecycleIntegrationError("terminal close requires completed task evidence")
        if completion.get("outcome") not in {"completed", "replayed"}:
            raise LifecycleIntegrationError("terminal close requires a completed task")
        if completion.get("project_ref") != project_ref or completion.get("task_ref") != task_ref:
            raise LifecycleIntegrationError("task completion is pinned to a stale project or task revision")
        receipt = completion.get("receipt")
        if not isinstance(receipt, Mapping) or not _text(receipt.get("logical_request_key"), "task completion receipt.logical_request_key"):
            raise LifecycleIntegrationError("terminal close requires a typed task completion receipt")
        if evidence.get("project_ref") != project_ref or evidence.get("task_ref") != task_ref:
            raise LifecycleIntegrationError("terminal evidence is pinned to a stale project or task revision")
        return _copy(dict(evidence), "terminal evidence")

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
        portfolio_needed = manager_needed
        return {
            "manager": "active" if manager_needed else "paused",
            "portfolio": "active" if portfolio_needed else "paused",
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
            "project_context": _copy(self._project_context, "project_context"),
            "active_project_ids": sorted(project_id for project_id, state in self._projects.items() if state == "active"),
            "closing_project_ids": sorted(project_id for project_id, state in self._projects.items() if state in {"closing", "blocked"}),
            "desired_states": desired,
            "schedules": results,
            "automatic_action": False,
        }

    def activate(self, project_id: str, *, request_id: str, actor: str, generation: int, project_ref: str, task_ref: str, lifecycle_owner: str) -> dict[str, Any]:
        """Activate/resume a project and reconcile both schedules immediately."""

        self._check_generation(generation)
        operator = _text(actor, "actor")
        if operator not in {self.manager_actor, self.orchestrator_actor}:
            raise LifecycleIntegrationError("activation requires manager or orchestrator authority")
        project = _text(project_id, "project_id")
        self._project_guard(project, project_ref=project_ref, task_ref=task_ref, lifecycle_owner=lifecycle_owner, generation=generation)
        self._owner_transition(project, request_id=request_id, intent="active", evidence={})
        result = self._reconcile(request_id=request_id, action="activate", generation=generation)
        self._owner_host_acknowledgement(project, result, request_id=request_id)
        return result

    def resume(self, project_id: str, *, request_id: str, actor: str, generation: int, project_ref: str, task_ref: str, lifecycle_owner: str) -> dict[str, Any]:
        """Resume a project from zero-active state through the same path."""

        result = self.activate(project_id, request_id=request_id, actor=actor, generation=generation, project_ref=project_ref, task_ref=task_ref, lifecycle_owner=lifecycle_owner)
        result["action"] = "resume"
        return result

    def manager_close(self, project_id: str, *, request_id: str, actor: str, generation: int, project_ref: str, task_ref: str, lifecycle_owner: str, blocked: bool = False) -> dict[str, Any]:
        """Record an authorized manager close request and reconcile schedules."""

        self._authorize(actor, self.manager_actor)
        self._check_generation(generation)
        project = _text(project_id, "project_id")
        self._project_guard(project, project_ref=project_ref, task_ref=task_ref, lifecycle_owner=lifecycle_owner, generation=generation)
        if self._projects.get(project) not in {"active", "closing", "blocked"}:
            raise LifecycleIntegrationError("manager close requires an active or closing project")
        self._owner_transition(project, request_id=request_id, intent="blocked" if blocked else "closing", evidence={})
        result = self._reconcile(request_id=request_id, action="manager_close", generation=generation)
        self._owner_host_acknowledgement(project, result, request_id=request_id)
        return result

    def orchestrator_verify(self, *, actor: str, generation: int) -> dict[str, Any]:
        """Perform the independent orchestrator owner check without mutation."""

        self._authorize(actor, self.orchestrator_actor)
        self._check_generation(generation)
        return {
            "outcome": "verified",
            "generation": self._generation,
            "binding": _copy(self.orchestrator_binding),
            "projects": dict(self._projects),
            "project_context": _copy(self._project_context, "project_context"),
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

    def orchestrator_terminal_close(self, project_id: str, *, request_id: str, actor: str, generation: int, project_ref: str, task_ref: str, lifecycle_owner: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
        """Terminally close a manager-closing project under orchestrator authority."""

        self._authorize(actor, self.orchestrator_actor)
        self._check_generation(generation)
        project = _text(project_id, "project_id")
        verified_evidence = self._terminal_evidence(project, evidence, project_ref=project_ref, task_ref=task_ref, lifecycle_owner=lifecycle_owner, generation=generation)
        if self._projects.get(project) != "closing":
            state = self._projects.get(project)
            if state == "blocked":
                return {"outcome": "held", "reason": "blocked project requires recovery before terminal close", "project_id": project, "generation": self._generation, "automatic_action": False}
            raise LifecycleIntegrationError("terminal close requires manager state closing")
        self._owner_transition(project, request_id=request_id, intent="terminal", evidence=verified_evidence)
        result = self._reconcile(request_id=request_id, action="orchestrator_terminal_close", generation=generation)
        result["terminal_evidence"] = verified_evidence
        self._owner_host_acknowledgement(project, result, request_id=request_id)
        return result

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
        for context in self._project_context.values():
            context["lifecycle_owner"] = new_owner
            context["generation"] = next_generation
        return {"outcome": "rebound", "generation": next_generation, "lifecycle_owner": new_owner, "results": results, "automatic_action": False}


__all__ = ["LifecycleIntegrationError", "PortfolioLifecycleIntegration"]
