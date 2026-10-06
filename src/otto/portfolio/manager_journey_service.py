"""Finite service joins for ordinary manager commands and retained workers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .manager_journey_command import ManagerJourneyCommands


def compose_worker_operation(*, config: Mapping[str, Any], task: str, task_ref: Mapping[str, Any],
                             principal: str, model: str, reasoning: str, focus: str,
                             workspace: Path, run_path: Path, adapter: Any) -> tuple[str, dict, dict]:
    """Owner policy selects capability; caller focus cannot grant authority."""
    operation = config.get("worker_operation_profiles", {}).get(task, "implementation")
    if operation not in {"implementation", "cold_manager_operation"}:
        raise ValueError("worker task operation profile is unsupported; owner must correct run policy before submission")
    if Path(adapter.worktree).resolve() != workspace:
        raise ValueError("worker adapter worktree differs from the delegated workspace")
    roots = list(dict.fromkeys([str(workspace),
        *(str(Path(root).resolve()) for root in adapter.writable_roots)]))
    instruction = (f"Implement only {task} in {workspace / 'src'}. "
        f"Use the current canonical task, linked run contract and {model} {reasoning}. "
        "Run focused verification and return exact changed paths, results and unresolved responsibilities. "
        "Do not accept your work, alter controller state, push, release, deploy or retry an unknown effect.\n\n"
        "Current manager invocation intent:\n" + focus.strip())
    contract = {"task_ref": task_ref, "objective": f"Implement the delegated {task} outcome",
        "bounded_operation": instruction,
        "allowed_operations": ["read_project_context", "edit_candidate_workspace", "run_focused_tests", "return_progress"],
        "acceptance_criteria": ["Complete the bounded source change and focused verification",
                                "Return changed paths, evidence and unresolved responsibility"],
        "authority": {"source": "canonical_owner", "owner_actor": principal,
            "gateway_claim_required": True, "owner_write": False, "dispatch": False,
            "effect_profile": "workspace-write-worker", "workspace_roots": roots,
            "permitted_effects": ["read_delivered_context", "read_linked_sources", "file_write_in_workspace", "return_result"],
            "forbidden_effects": ["owner_write", "publication", "package_adoption", "remote_push", "release", "deployment"]}}
    brief = {"role": "worker", "mandate": "Implement this bounded outcome directly; return evidence to the manager; do not delegate.",
        "user_constraints": ["Do not modify canonical state, controller runtime or historical effects"],
        "operational_constraints": ["Unknown-send fences remain binding; reconcile before any replay"],
        "priorities": [{"id": task.lower(), "text": focus.strip(), "status": "pending"}],
        "continuation": {"next_action": focus.strip()},
        "links": [{"label": name, "path": str(run_path / name)}
                  for name in ("agent_goal.md", "tasklist.md", "run.yaml", "owner-setup-guidance-20261005.md")]
                 + [{"label": "Megado skill", "path": str(workspace / "policy-staging/megado/skill/SKILL.md")}],
        "revision": "ordinary-worker-v1"}
    if operation == "cold_manager_operation":
        instruction = (f"Execute the authorized cold manager operation for {task} using the delivered run instructions and maintained installed client. "
            "Exercise the assigned journey directly, including substantive review and guarded acceptance of its delegated artifacts. "
            "Return actual installed receipts, native identities, unresolved responsibilities and blockers. "
            "Do not implement source repairs, change controller runtime, expand budgets, or retry unknown effects. "
            "Your parent manager judges this operator task; review/acceptance commands apply to the journey artifacts under the assigned scope.\n\n"
            "Current manager invocation intent:\n" + focus.strip())
        contract.update(objective=f"Execute the delegated {task} cold manager operation", bounded_operation=instruction,
            acceptance_criteria=["Exercise the assigned installed journey through maintained commands",
                                 "Return actual receipts and unresolved responsibility without source implementation"])
        contract["allowed_operations"].append("canonical_manager_commands")
        contract["authority"]["effect_profile"] = "workspace-write-manager"
        contract["authority"]["permitted_effects"].append("canonical_manager_commands")
        brief.update(mandate="Execute the prescribed cold manager operation directly through maintained commands; return installed evidence to the parent manager.",
                     user_constraints=["Use the prescribed maintained canonical manager commands; do not directly edit canonical owner records, controller runtime or historical effects"],
                     revision="ordinary-cold-manager-operation-v1")
    from .resource_sync import normalize_instruction_contract
    normalize_instruction_contract(contract)  # Reject invalid composition before assignment/initialization.
    return instruction, contract, brief


class ManagerJourneyService:
    """Wrap the maintained outer handler; the host still owns one Store lane."""

    def __init__(self, *, server: Any, host: Any, run_path: str | Path,
                 workspace: str | Path, policy: Any = None,
                 orchestrator_principal: str | None = None, observe_schedules: Any = None) -> None:
        self.server, self.host = server, host
        self.run_path, self.workspace = Path(run_path).resolve(), Path(workspace).resolve()
        self.commands = ManagerJourneyCommands(owner=server.owner, portfolio=server.portfolio,
            state=server.state, policy=policy, due_port=server.due_port,
            settle_execution=self._settle_execution)
        self.orchestrator_principal, self.observe_schedules = orchestrator_principal, observe_schedules

    def _settle_execution(self, due: Mapping[str, Any]) -> Mapping[str, Any]:
        app = self.server._execution(principal=due["recipient"], model=due["requested_model"],
            reasoning=due["requested_reasoning"], evidence_id=due["schedule_id"])
        return app.recover(schedule_id=due["schedule_id"], execute=False)

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        command = request.get("command")
        if command == "manager-worker-result":
            self.commands._authorize()
            state = self.server.state
            worker = (state.get("workers") or {}).get(request.get("task"))
            if (set(request) != {"command", "task", "principal", "schedule_id"}
                    or not isinstance(worker, Mapping) or worker.get("principal") != request.get("principal")
                    or worker.get("schedule_id") != request.get("schedule_id")):
                raise PermissionError("worker-result continuation handle is stale or foreign")
            current_id = (state.get("manager_continuation") or {}).get("schedule_id") or state["schedule_id"]
            app = self.server._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="manager-worker-result-" + worker["schedule_id"])
            result = app.continue_manager_from_worker(manager_schedule_id=current_id,
                worker_schedule_id=worker["schedule_id"], execute=True)
            if result.get("outcome") in {"succeeded", "replayed"}:
                state["manager_continuation"] = {"schedule_id": result["schedule_id"],
                    "native_session_id": app._read(result["schedule_id"]).target["native_id"],
                    "outcome": result["outcome"], "requested_continuation": {"settled_schedule_id": result["schedule_id"]}}
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
            return result
        if command == "project-lifecycle-read":
            # The operator is authorized by its exact manager assignment. The
            # finite owner read grant remains bound to the service issuer.
            self.commands._authorize()
            state = self.server.state
            alias = request.get("task", next(iter(state["task_refs"])))
            if alias not in state["task_refs"]:
                raise ValueError("lifecycle read requires a current task alias")
            pins = {"project_ref": state["project_ref"], "task_ref": state["task_refs"][alias],
                    "manager_ref": state["assignment_ref"]}
            if set(request) - {"command", "task", *pins} or any(
                    field in request and request[field] != pin for field, pin in pins.items()):
                raise ValueError("lifecycle read cannot change the bound project/task/manager")
            return self.server.portfolio.read_project_lifecycle(**pins, actor=state["owner"])
        if command == "manager-continue":
            from .manager_continuation_command import manager_continuation_from_command
            from .execution_operations import read_project_progress_reports
            self.commands._authorize()
            state = self.server.state
            metadata = state.get("manager_continuation") or {}
            current_id = metadata.get("schedule_id") or state["schedule_id"]
            current = self.server.due_port.read_due(current_id) or {}
            anchor = (current_id if current.get("completion_state") == "succeeded" else
                      (metadata.get("requested_continuation") or {}).get("settled_schedule_id"))
            if not isinstance(anchor, str):
                return {"outcome": "held", "provider_called": False, "retry": False,
                        "reason": "no retained successful same-manager anchor",
                        "current_schedule_id": current_id,
                        "next_action": "record the requested continuation report and return from the current native turn; the owner can consume it after settlement"}
            app = self.server._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="manager-explicit-continuation")
            result = manager_continuation_from_command(request=request, execution=app,
                anchor_schedule_id=anchor, current_schedule_id=current_id,
                task_refs=state["task_refs"], native_session_id=metadata.get("native_session_id"),
                read_reports=lambda: read_project_progress_reports(self.server.store.consumer(), state["project_ref"]),
                preserve_execution_binding=True)
            if result.get("outcome") in {"succeeded", "replayed"}:
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
            return result
        if command in {"review-task", "finish-task", "finish-project"}:
            operation = getattr(self.commands, command.replace("-", "_"))
            result = (operation(request, orchestrator_principal=self.orchestrator_principal,
                                observe_schedules=self.observe_schedules)
                      if command == "finish-project" else operation(request))
            self._refresh_refs()
            return result
        if command == "run-worker":
            return self._submit_worker(request)
        if command in {"worker-status", "start-retained-worker"}:
            self.commands._authorize()
            worker = (self.server.state.get("workers") or {}).get(request.get("task"))
            if (not isinstance(worker, Mapping) or worker.get("principal") != request.get("principal")
                    or worker.get("schedule_id") != request.get("schedule_id")):
                raise PermissionError("worker handle is stale or belongs to another recipient")
            app = self.server._execution(principal=worker["principal"], model=worker["model"],
                reasoning=worker["reasoning"], evidence_id=worker["schedule_id"])
            result = (app.start(schedule_id=worker["schedule_id"]) if command == "start-retained-worker" else
                      app.recover(schedule_id=worker["schedule_id"], execute=False))
            if result.get("outcome") in {"succeeded", "replayed"}:
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
                if command == "start-retained-worker":
                    if self.host._closing:
                        retained = {"outcome": "held", "provider_called": False,
                            "reason": "owner is draining; preserve worker result and prepare its manager continuation after restart"}
                    else:
                        retained = self.host.submit({"command": "manager-worker-result", "task": request["task"],
                            "principal": worker["principal"], "schedule_id": worker["schedule_id"]})
                    result = {**result, "manager_result_notification": retained}
            return result
        return self.server.handle(request)

    def _refresh_refs(self) -> None:
        from herzchen.contracts import ResourceRef
        state = self.server.state
        for field in ("project_ref",):
            ref = ResourceRef.from_dict(state[field])
            state[field] = self.server.owner.graph.reader.get_identity(
                ResourceRef(ref.authority, ref.kind, ref.id)).ref.to_dict()
        for alias, value in state["task_refs"].items():
            ref = ResourceRef.from_dict(value)
            state["task_refs"][alias] = self.server.owner.graph.reader.get_identity(
                ResourceRef(ref.authority, ref.kind, ref.id)).ref.to_dict()
        self.server._save_state()

    def _submit_worker(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.commands._authorize()
        if self.host._closing:
            return {"outcome": "held", "reason": "owner host is draining", "provider_called": False}
        if set(request) - {"command", "task", "route", "principal", "request_key", "focus"}:
            raise ValueError("unsupported worker submission fields")
        state = self.server.state
        task, route, principal = request.get("task"), request.get("route"), request.get("principal")
        key = self.commands._key(request)
        if task not in state["task_refs"] or route not in {"normal", "xhard"}:
            raise ValueError("worker requires a current task and configured route")
        if not isinstance(principal, str) or not principal.strip() or principal != principal.strip():
            raise ValueError("worker principal must be exact nonblank text")
        config = json.loads((self.run_path / "run.yaml").read_text())
        configured = config["roles"]["worker_" + route]
        model, reasoning = configured["model"], configured["reasoning"]
        if (not isinstance(model, str) or not model or any(char.isspace() for char in model)
                or reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}):
            raise ValueError("worker route model/reasoning configuration is invalid")
        focus = request.get("focus")
        if not isinstance(focus, str) or not focus.strip() or len(focus) > 4000:
            raise ValueError("worker focus must describe 1..4000 characters of current intent")
        previous = (state.get("workers") or {}).get(task)
        if isinstance(previous, Mapping):
            previous_app = self.server._execution(principal=previous["principal"], model=previous["model"],
                reasoning=previous["reasoning"], evidence_id=previous["schedule_id"])
            if previous.get("request_key") == key:
                if previous.get("submission") != dict(request):
                    raise ValueError("worker request key was reused with changed current intent")
                if previous["model"] != model or previous["reasoning"] != reasoning:
                    raise ValueError("current run policy differs from the retained worker; inspect its exact occurrence without resending")
                retained = previous_app.recover(schedule_id=previous["schedule_id"], execute=False)
                if retained.get("outcome") != "prepared":
                    return {**retained, **{name: previous[name] for name in ("retained_handle", "response_path")
                                         if name in previous}, "retry_provider": False}
            else:
                due = self.server.due_port.read_due(previous["schedule_id"])
                if not due or due.get("completion_state") != "succeeded":
                    return {"outcome": "held", "schedule_id": previous["schedule_id"],
                            "retained_handle": previous.get("retained_handle"), "provider_called": False,
                            "retry_provider": False,
                            "reason": "existing task worker is unstarted, active or uncertain; reconcile that occurrence before a new send"}
        task_ref = state["task_refs"][task]
        app = self.server._execution(principal=principal, model=model, reasoning=reasoning,
            evidence_id="worker-" + hashlib.sha256(key.encode()).hexdigest()[:20])
        instruction, contract, brief = compose_worker_operation(config=config, task=task, task_ref=task_ref,
            principal=principal, model=model, reasoning=reasoning, focus=focus,
            workspace=self.workspace, run_path=self.run_path, adapter=app.runtime.adapter)
        prepared = app.assign_worker(project_ref=state["project_ref"], task_ref=task_ref,
            principal=principal, request_key=key, instructions=instruction, instruction_contract=contract,
            brief=brief, model=model, reasoning=reasoning, timeout_seconds=1200)
        if prepared.get("outcome") not in {"committed", "prepared"}:
            previous = (state.get("workers") or {}).get(task) or {}
            return {**prepared, **{name: previous[name] for name in ("retained_handle", "response_path")
                                  if name in previous and previous.get("schedule_id") == prepared.get("schedule_id")},
                    "retry_provider": False}
        state.setdefault("workers", {})[task] = {**prepared, "principal": principal,
                                                 "model": model, "reasoning": reasoning,
                                                 "request_key": key, "submission": dict(request)}
        self.server._save_state()
        retained = self.host.submit({"command": "start-retained-worker", "task": task,
            "principal": principal, "schedule_id": prepared["schedule_id"]})
        state["workers"][task].update(retained)
        self.server._save_state()
        return {**prepared, **retained, "assignment_ref": prepared["assignment_ref"],
                "generation": prepared["generation"], "principal": principal, "task": task}


def install_manager_journey_service(server: Any, *, run_path: str | Path, workspace: str | Path,
                                    policy: Any = None, orchestrator_principal: str | None = None,
                                    observe_schedules: Any = None) -> ManagerJourneyService:
    """Owner adoption hook, called once after the existing server.start().

    The owner installs a tested source snapshot, adds this handler composition,
    and adds the matching client parsers. No live controller or canonical state
    is edited by a worker. Closeout capabilities must be deliberately supplied
    by that owner; missing capabilities return a precise held result.
    """
    host = server.execution_host
    service = ManagerJourneyService(server=server, host=host, run_path=run_path,
        workspace=workspace, policy=policy, orchestrator_principal=orchestrator_principal,
        observe_schedules=observe_schedules)
    host.handler = service
    return service
