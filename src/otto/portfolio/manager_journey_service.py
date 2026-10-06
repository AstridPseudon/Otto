"""Finite service joins for ordinary manager commands and retained workers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from herzchen.contracts import ResourceRef

from .manager_journey_command import ManagerJourneyCommands
from .execution_operations import compact_project_status, read_project_progress_reports
from .owner_readers import json_value


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
                 orchestrator_principal: str | None = None, observe_schedules: Any = None,
                 help_reply_authorizer: Any = None) -> None:
        self.server, self.host = server, host
        self._host_execution = server._execution
        self.run_path, self.workspace = Path(run_path).resolve(), Path(workspace).resolve()
        self.commands = ManagerJourneyCommands(owner=server.owner, portfolio=server.portfolio,
            state=server.state, policy=policy, due_port=server.due_port,
            settle_execution=self._settle_execution)
        self.orchestrator_principal, self.observe_schedules = orchestrator_principal, observe_schedules
        self.help_reply_authorizer = help_reply_authorizer

    def _execution(self, **options: Any) -> Any:
        """Bind every execution path to the installed owner's assessment policy.

        Setup reads and provider admission must use the same authority. The
        host supplies adapters; neither transport nor setup JSON can choose
        assessment criteria or allowance.
        """
        from .local_assessment_policy import LocalAssessmentPolicy
        app = self._host_execution(**options)
        policy = self.commands.policy or self.server.state.get("assessment_policy")
        if isinstance(policy, Mapping):
            policy = LocalAssessmentPolicy.from_run_config(policy, state=self.server.state)
        trusted = self.server.owner.role_runtime(due_port=self.server.due_port,
            adapter=app.runtime.adapter, assessment_policy=policy)
        app.runtime.acceptance_readiness = trusted.acceptance_readiness
        return app

    def _settle_execution(self, due: Mapping[str, Any]) -> Mapping[str, Any]:
        app = self._execution(principal=due["recipient"], model=due["requested_model"],
            reasoning=due["requested_reasoning"], evidence_id=due["schedule_id"])
        return app.recover(schedule_id=due["schedule_id"], execute=False)

    def _status(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Read one bounded current projection; status never dispatches or mutates."""

        self.commands._authorize()
        state = self.server.state
        project_ref = state["project_ref"]
        operations = self.server.portfolio.operations
        sheet = getattr(operations, "sheet_port", None)
        if not callable(getattr(sheet, "export", None)):
            # Preserve the host's existing finite read when the older owner
            # adapter has not installed the ProjectSheet read port yet.
            return self.server.handle(request)
        view = json_value(sheet.export(ResourceRef.from_dict(project_ref)))
        if not isinstance(view, Mapping):
            raise ValueError("current project status readback is not an object")
        reports = read_project_progress_reports(self.server.store.consumer(), project_ref)
        loop = self.server.portfolio._issue_loop()
        help_read = loop.read_issues(project_ref=project_ref) if loop is not None else {"issues": []}
        issues = help_read.get("issues", []) if isinstance(help_read, Mapping) else []
        occurrences = self.server.due_port.list_due()
        current_id = (state.get("manager_continuation") or {}).get("schedule_id") or state.get("schedule_id")
        operation = self.server.due_port.read_due(current_id) if current_id else None
        operation = dict(operation) if isinstance(operation, Mapping) else {}
        operation.setdefault("request_id", operation.get("in_flight_request") or operation.get("last_completed_request"))
        target = operation.get("target")
        if isinstance(target, Mapping):
            operation.setdefault("instruction_provenance", {
                key: target[key] for key in ("project_ref", "task_ref", "assignment_ref", "mandate_ref", "generation", "context_refs")
                if key in target
            })
        status = compact_project_status(
            view, task_refs=state["task_refs"], reports=reports, occurrences=occurrences,
            help_issues=issues, required_scope=state.get("required_scope"), operation=operation,
        )
        return {
            "outcome": "ok", "project_ref": project_ref,
            "task_refs": state["task_refs"], "workers": state.get("workers", {}),
            "manager": state.get("manager"), "manager_assignment_ref": state.get("assignment_ref"),
            "status": status, **status,
        }

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        command = request.get("command")
        if command == "status":
            return self._status(request)
        if command in {"request-help", "request-advice", "read-help", "respond-help", "resolve-help"}:
            return self._help(request)
        if command == "start-retained-help":
            self.commands._authorize()
            if set(request) != {"command", "principal", "schedule_id", "delivery_id"}:
                raise ValueError("retained help execution requires its exact delivery handle")
            loop = self.server.portfolio._issue_loop()
            reports = loop._issue_reports(self.server.state["project_ref"])
            receipt = next((r["value"].get("receipt") for r in reports if isinstance(r.get("value"), Mapping)
                and r["value"].get("schema") == "otto.issue.delivery.v1"
                and r["value"].get("delivery_id") == request["delivery_id"]
                and isinstance(r["value"].get("receipt"), Mapping)
                and r["value"]["receipt"].get("schedule_id") == request["schedule_id"]), None)
            if receipt is None:
                raise PermissionError("help execution has no retained owner delivery receipt")
            raw = self.server.due_port.read_due(request["schedule_id"])
            assignment = self.server.owner.assignments.command_port.get(receipt["recipient_assignment_ref"])
            current = loop._recipient(self.server.state["project_ref"], "advice" if assignment.role == "project_advisor" else "operational_help")
            if (current is None or json_value(current.ref) != receipt["recipient_assignment_ref"]
                    or assignment.principal != request["principal"] or assignment.generation != receipt["generation"]
                    or not isinstance(raw, Mapping) or raw["assignment_ref"] != receipt["recipient_assignment_ref"]
                    or raw["generation"] != receipt["generation"] or raw["target"].get("native_id") != receipt["conversation_id"]
                    or assignment.role not in {"orchestrator", "project_advisor"}):
                raise PermissionError("retained help recipient is stale")
            app = self._execution(principal=assignment.principal, model=raw["requested_model"],
                reasoning=raw["requested_reasoning"], evidence_id=request["schedule_id"])
            return app.recover(schedule_id=request["schedule_id"], execute=True)
        if command == "manager-help-result":
            self.commands._authorize()
            state = self.server.state
            if (set(request) != {"command", "principal", "schedule_id", "report_ref", "generation"}
                    or request["principal"] != state["manager"] or request["generation"] != state["manager_generation"]):
                raise PermissionError("help continuation recipient is stale or foreign")
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="manager-help-result")
            original = app._read(request["schedule_id"])
            if original.assignment_ref["id"] != state["assignment_ref"]["id"] or original.generation != request["generation"]:
                raise PermissionError("help continuation anchor is stale or foreign")
            current_id = (state.get("manager_continuation") or {}).get("schedule_id") or state["schedule_id"]
            prepared = app.continue_manager_from_help(manager_schedule_id=current_id,
                report_ref=request["report_ref"], execute=False)
            if prepared.get("outcome") not in {"committed", "prepared", "replayed"}:
                return prepared
            if prepared["outcome"] == "replayed":
                return prepared  # An old reply never replaces the current manager handle.
            due = app._read(prepared["schedule_id"])
            state["manager_continuation"] = {"schedule_id": due.schedule_id,
                "native_session_id": due.target["native_id"], "outcome": "prepared",
                "requested_continuation": {"settled_schedule_id": current_id}}
            self.server._save_state()
            result = app.recover(schedule_id=due.schedule_id, execute=True)
            state["manager_continuation"]["outcome"] = result["outcome"]
            self.server._save_state()
            return result
        if command == "operating-setup":
            self.commands._authorize()
            if set(request) - {"command", "operation", "setup", "request_key"}:
                raise ValueError("operating setup cannot change the bound project or owner")
            state = self.server.state
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="operating-setup")
            operation = request.get("operation", "read")
            if operation == "read":
                if request.get("setup") is not None or request.get("request_key") is not None:
                    raise ValueError("operating setup read takes no preparation fields")
                return app.read_operating_setup(project_ref=state["project_ref"])
            if operation == "prepare":
                return app.prepare_operating_setup(project_ref=state["project_ref"],
                    setup=request.get("setup"), request_key=request.get("request_key"))
            if operation == "activate":
                if request.get("setup") is not None or request.get("request_key") is not None:
                    raise ValueError("activate uses only the adopted setup")
                return app.activate_operating_setup(project_ref=state["project_ref"])
            raise ValueError("unknown operating setup operation")
        if command == "manager-task-settlement":
            self.commands._authorize()
            state = self.server.state
            if (set(request) != {"command", "principal", "schedule_id"}
                    or request["principal"] != state["manager"]
                    or request["schedule_id"] != (state.get("manager_continuation") or {}).get("schedule_id")):
                raise PermissionError("task-settlement continuation handle is stale or foreign")
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id=request["schedule_id"])
            due = app._read(request["schedule_id"])
            if not (due.host_evidence or {}).get("task_settlement_continuation"):
                raise PermissionError("task-settlement command requires its retained completion observation")
            result = app.recover(schedule_id=due.schedule_id, execute=True)
            if result.get("outcome") in {"succeeded", "replayed"}:
                state["manager_continuation"].update(outcome=result["outcome"],
                    requested_continuation={"settled_schedule_id": due.schedule_id})
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
                result = {**result, "task_settlement_notification": self._retain_task_settlement(app)}
            return result
        if command == "review-input":
            if set(request) != {"command", "task"}:
                raise ValueError("review-input requires only the current task alias")
            return self.commands.review_input(request["task"])
        if command == "manager-worker-result":
            self.commands._authorize()
            state = self.server.state
            worker = (state.get("workers") or {}).get(request.get("task"))
            if (set(request) != {"command", "task", "principal", "schedule_id"}
                    or not isinstance(worker, Mapping) or worker.get("principal") != request.get("principal")
                    or worker.get("schedule_id") != request.get("schedule_id")):
                raise PermissionError("worker-result continuation handle is stale or foreign")
            current_id = (state.get("manager_continuation") or {}).get("schedule_id") or state["schedule_id"]
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="manager-worker-result-" + worker["schedule_id"])
            result = app.continue_manager_from_worker(manager_schedule_id=current_id,
                worker_schedule_id=worker["schedule_id"], execute=True)
            if result.get("outcome") in {"succeeded", "replayed"}:
                state["manager_continuation"] = {"schedule_id": result["schedule_id"],
                    "native_session_id": app._read(result["schedule_id"]).target["native_id"],
                    "outcome": result["outcome"], "requested_continuation": {"settled_schedule_id": result["schedule_id"]}}
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
                result = {**result, "task_settlement_notification": self._retain_task_settlement(app)}
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
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="manager-explicit-continuation")
            result = manager_continuation_from_command(request=request, execution=app,
                anchor_schedule_id=anchor, current_schedule_id=current_id,
                task_refs=state["task_refs"], native_session_id=metadata.get("native_session_id"),
                read_reports=lambda: read_project_progress_reports(self.server.store.consumer(), state["project_ref"]),
                preserve_execution_binding=True)
            if result.get("outcome") in {"succeeded", "replayed"}:
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
                result = {**result, "task_settlement_notification": self._retain_task_settlement(app)}
            return result
        if command in {"review-task", "finish-task", "finish-project"}:
            operation = getattr(self.commands, command.replace("-", "_"))
            result = (operation(request, orchestrator_principal=self.orchestrator_principal,
                                observe_schedules=self.observe_schedules)
                      if command == "finish-project" else operation(request))
            self._refresh_refs()
            if command != "finish-project" and (result.get("outcome") in {"completed", "replayed"}
                    or (result.get("completion") or {}).get("outcome") in {"completed", "replayed"}):
                state = self.server.state
                app = self._execution(principal=state["manager"], model=state["requested_model"],
                    reasoning=state["requested_reasoning"], evidence_id="manager-task-settlement")
                result = {**result, "task_settlement_notification": self._retain_task_settlement(app)}
            return result
        if command == "run-worker":
            return self._submit_worker(request)
        if command in {"worker-status", "start-retained-worker"}:
            self.commands._authorize()
            worker = (self.server.state.get("workers") or {}).get(request.get("task"))
            if (not isinstance(worker, Mapping) or worker.get("principal") != request.get("principal")
                    or worker.get("schedule_id") != request.get("schedule_id")):
                raise PermissionError("worker handle is stale or belongs to another recipient")
            app = self._execution(principal=worker["principal"], model=worker["model"],
                reasoning=worker["reasoning"], evidence_id=worker["schedule_id"])
            result = (app.start(schedule_id=worker["schedule_id"]) if command == "start-retained-worker" else
                      app.recover(schedule_id=worker["schedule_id"], execute=False))
            if result.get("outcome") in {"succeeded", "replayed"}:
                result = {**result, "completion_intents": self.commands.settle_completion_intents()}
                self._refresh_refs()
                result = {**result, "review_input": self.commands.review_input(request["task"])}
                if result["completion_intents"]:
                    state = self.server.state
                    manager_app = self._execution(principal=state["manager"], model=state["requested_model"],
                        reasoning=state["requested_reasoning"], evidence_id="manager-task-settlement")
                    result = {**result, "task_settlement_notification": self._retain_task_settlement(manager_app)}
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

    def _help(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Manager operations and the host-bound recipient reply over IssueLoop."""
        self.commands._authorize()
        state, command = self.server.state, request["command"]
        portfolio = self.server.portfolio
        loop = portfolio._issue_loop()
        if loop is None:
            return {"outcome": "unavailable", "provider_called": False, "reason": "owner issue ports are not bound"}
        common = {"project_ref": state["project_ref"]}
        manager = {**common, "assignment_ref": state["assignment_ref"],
                   "generation": state["manager_generation"], "actor": state["manager"]}
        if command == "read-help":
            if set(request) - {"command", "delivery_id"}:
                raise ValueError("read-help cannot override its bound project or actor")
            if request.get("delivery_id"):
                return loop.recover_delivery(**common, delivery_id=request["delivery_id"])
            return portfolio.read_issues(**common)
        key = self.commands._key(request)
        if command in {"request-help", "request-advice"}:
            fields = {"issue_key", "problem", "evidence", "impact", "requested_decision", "return_condition"}
            if set(request) != {"command", "request_key", *fields}:
                raise ValueError("help request requires concise problem/evidence/impact/decision/return condition; no routing overrides")
            operation = portfolio.request_advice if command == "request-advice" else portfolio.request_help
            result = operation(**manager, **{field: request[field] for field in fields}, request_id=key)
            issue = next(i for i in loop.read_issues(**common)["issues"] if i["issue_id"] == result["issue_id"])
            # Opening or replaying a help request is not a response to consume.
            # The manager continuation is retained only after the authenticated
            # recipient has returned a response, or after the manager has
            # recorded its application through resolve-help. In particular, a
            # missing recipient must remain an unresolved routed issue rather
            # than becoming a malformed callback attempt.
            return {**result, "purpose": issue["purpose"], "resolution": issue["state"],
                    "recipient_assignment_ref": issue["current_owner_ref"], "independent_work": "continue"}
        if command == "respond-help":
            fields = {"issue_id", "authority_source", "response", "proposed_solution", "next_action"}
            if set(request) != {"command", "request_key", *fields}:
                raise ValueError("help response cannot choose its own actor or recipient")
            # Manager-accessible transport cannot impersonate its supervisor.
            # A host binds an independently authenticated recipient reply port.
            from herzchen.contracts import AuthenticatedActor
            if not callable(self.help_reply_authorizer):
                raise PermissionError("respond-help requires the host's authenticated recipient reply port")
            responder = self.help_reply_authorizer(dict(request))
            if (not isinstance(responder, AuthenticatedActor)
                    or responder.authority != self.server.owner.binding.authority
                    or responder.credential_ref != self.server.owner.binding.credential_ref):
                raise PermissionError("help reply lacks owner-issued recipient authentication")
            result = portfolio.respond_to_issue(**common, actor=responder.actor,
                **{field: request[field] for field in fields}, request_id=key)
        else:
            if set(request) != {"command", "request_key", "issue_id", "evidence", "next_action"}:
                raise ValueError("resolve-help requires application evidence and next action; no actor override")
            result = portfolio.resolve_help(**manager, issue_id=request["issue_id"], evidence=request["evidence"],
                next_action=request["next_action"], request_id=key)
        if self.host is None or self.host._closing:
            return {**result, "continuation": {"outcome": "held", "provider_called": False,
                    "reason": "owner host must retain help continuation after restart", "retry": False}}
        current_id = (state.get("manager_continuation") or {}).get("schedule_id") or state["schedule_id"]
        retained = self.host.submit({"command": "manager-help-result", "principal": state["manager"],
            "generation": state["manager_generation"], "schedule_id": current_id, "report_ref": result["report_ref"]})
        return {**result, "continuation": retained}

    def _retain_task_settlement(self, app: Any) -> Mapping[str, Any]:
        if self.host._closing:
            return {"outcome": "held", "provider_called": False,
                    "reason": "owner is draining; preserve completion intents for same-manager closeout after restart"}
        state = self.server.state
        anchor = (state.get("manager_continuation") or {}).get("schedule_id") or state["schedule_id"]
        prepared = app.continue_manager_after_tasks(manager_schedule_id=anchor, execute=False)
        if prepared.get("outcome") not in {"committed", "prepared"}:
            return prepared
        due = app._read(prepared["schedule_id"])
        state.update(schedule_id=due.schedule_id, logical_request_key=due.in_flight_request,
            manager_start_instruction=due.instruction,
            manager_continuation={"schedule_id": due.schedule_id, "native_session_id": due.target["native_id"],
                "outcome": "prepared", "requested_continuation": {"settled_schedule_id": anchor}})
        self.server._save_state()
        return self.host.submit({"command": "manager-task-settlement", "principal": state["manager"],
                                 "schedule_id": due.schedule_id})

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
            previous_app = self._execution(principal=previous["principal"], model=previous["model"],
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
                from .worker_custody import permits_fresh_worker
                released = (bool(due) and due.get("target", {}).get("task_ref") == state["task_refs"][task]
                    and permits_fresh_worker(previous_app, previous_app._read(previous["schedule_id"]),
                        request=request, model=model, reasoning=reasoning))
                if not due or (due.get("completion_state") != "succeeded" and not released):
                    return {"outcome": "held", "schedule_id": previous["schedule_id"],
                            "retained_handle": previous.get("retained_handle"), "provider_called": False,
                            "retry_provider": False,
                            "reason": "existing task worker is unstarted, active or uncertain; reconcile that occurrence before a new send"}
        task_ref = state["task_refs"][task]
        app = self._execution(principal=principal, model=model, reasoning=reasoning,
            evidence_id="worker-" + hashlib.sha256(key.encode()).hexdigest()[:20])
        instruction, contract, brief = compose_worker_operation(config=config, task=task, task_ref=task_ref,
            principal=principal, model=model, reasoning=reasoning, focus=focus,
            workspace=self.workspace, run_path=self.run_path, adapter=app.runtime.adapter)
        from .resource_sync import resolve_assignment_attachments
        from .role_context import supporting_context
        manager = self.server.owner.assignments.command_port.get(ResourceRef.from_dict(state["assignment_ref"]))
        attachments = resolve_assignment_attachments({"ref": manager.ref.to_dict(), "role": manager.role,
            "generation": manager.generation, "payload": manager.payload},
            self.server.owner.content.command_port, role="manager")
        bases = [item for item in attachments if item["required"]]
        if len(bases) != 1:
            raise ValueError("worker delegation requires exactly one current adopted manager BASE")
        sources = supporting_context(bases[0], self.server.owner.content.command_port)
        prepared = app.assign_worker(project_ref=state["project_ref"], task_ref=task_ref,
            principal=principal, request_key=key, instructions=instruction, instruction_contract=contract,
            brief=brief, model=model, reasoning=reasoning, timeout_seconds=1200,
            supporting_refs=[source["ref"] for source in sources])
        if prepared.get("outcome") not in {"committed", "prepared"}:
            previous = (state.get("workers") or {}).get(task) or {}
            return {**prepared, **{name: previous[name] for name in ("retained_handle", "response_path")
                                  if name in previous and previous.get("schedule_id") == prepared.get("schedule_id")},
                    "retry_provider": False}
        if isinstance(previous, Mapping) and previous.get("schedule_id") != prepared["schedule_id"]:
            history = state.setdefault("worker_history", {}).setdefault(task, [])
            if not any(item.get("schedule_id") == previous["schedule_id"] for item in history):
                history.append(dict(previous))
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
                                    observe_schedules: Any = None,
                                    help_reply_authorizer: Any = None) -> ManagerJourneyService:
    """Owner adoption hook, called once after the existing server.start().

    The owner installs a tested source snapshot, adds this handler composition,
    and adds the matching client parsers. No live controller or canonical state
    is edited by a worker. Closeout capabilities must be deliberately supplied
    by that owner; missing capabilities return a precise held result.

    help_reply_authorizer is an optional host-owned authentication port. It
    must authenticate the recipient's current project, assignment, generation
    and conversation independently of request fields. Omitting it disables
    respond-help. IssueLoop also checks the actor against the current recipient
    before recording the response or routing a continuation.
    """
    host = server.execution_host
    service = ManagerJourneyService(server=server, host=host, run_path=run_path,
        workspace=workspace, policy=policy, orchestrator_principal=orchestrator_principal,
        observe_schedules=observe_schedules, help_reply_authorizer=help_reply_authorizer)
    server._execution = service._execution
    host.handler = service
    return service
