"""Finite service joins for ordinary manager commands and retained workers."""
from __future__ import annotations

import hashlib
from contextvars import ContextVar
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from herzchen.contracts import ResourceRef

from .manager_journey_command import ManagerJourneyCommands
from .execution_operations import compact_project_status, read_project_progress_reports
from .owner_readers import json_value
from .manager_handoff import compose_manager_handoff
from .owner_completion import after_owner


_CALLER = ContextVar("otto_trusted_command_caller", default=None)

def manager_head(state: Mapping[str, Any]) -> str | None:
    return (state.get("manager_continuation") or {}).get("schedule_id") or state.get("schedule_id")


def advance_manager_head(state: dict[str, Any], *, expected: str, due: Any,
                         settled_anchor: str) -> bool:
    """Advance the pointer only from the head used to prepare this occurrence."""
    if manager_head(state) != expected:
        return False
    state["manager_continuation"] = {"schedule_id": due.schedule_id,
        "native_session_id": due.target.get("native_id"), "outcome": "prepared",
        "requested_continuation": {"settled_schedule_id": settled_anchor}}
    return True


def complete_manager_head(state: dict[str, Any], *, schedule_id: str,
                          result: Mapping[str, Any]) -> bool:
    """A completion describes its own Due; it cannot stamp a newer head."""
    if manager_head(state) != schedule_id:
        return False
    head = dict(state.get("manager_continuation") or {})
    head.update(schedule_id=schedule_id, outcome=result["outcome"])
    head["operational_disposition"] = {k: json_value(result[k]) for k in
        ("stage", "error", "reason", "next_action", "effects_started", "provider_called",
         "superseded_unattempted_schedule_id") if k in result}
    state["manager_continuation"] = head
    return True


def _run_config_name(run_path: Path) -> str:
    from .run_config import run_config_path
    return run_config_path(run_path).name


def compose_worker_operation(*, config: Mapping[str, Any], task: str, task_ref: Mapping[str, Any],
                             principal: str, model: str, reasoning: str, focus: str,
                             workspace: Path, run_path: Path, adapter: Any, leaf: bool = False) -> tuple[str, dict, dict]:
    """Owner policy selects capability; caller focus cannot grant authority."""
    operation = "implementation" if leaf else config.get("worker_operation_profiles", {}).get(task, "implementation")
    if operation not in {"implementation", "coordinating_implementation", "cold_manager_operation"}:
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
                  for name in ("agent_goal.md", "tasklist.md", _run_config_name(run_path), "owner-setup-guidance-20261005.md")]
                 + [{"label": "Megado skill", "path": str(workspace / "policy-staging/megado/skill/SKILL.md")},
                    {"label": "Otto skill index", "path": str(workspace / "src/otto/portfolio/skills/SKILL.md")},
                    {"label": "Otto recovery skill", "path": str(workspace / "src/otto/portfolio/skills/recovery/SKILL.md")}],
        "revision": "ordinary-worker-v1"}
    # Any adapter may declare itself a finite leaf (Claude Code does); the
    # identity check keeps the original Claude pin for retained policies.
    if (getattr(adapter, "leaf_only", False) is True
            or getattr(adapter, "adapter_identity", None) == "otto.adapter.claude-code-2.1.293.leaf.v1"):
        if operation != "implementation":
            raise ValueError("selected adapter is a finite leaf (" + str(getattr(adapter, "adapter_identity", "unnamed"))
                             + "); coordinating/manager operations are unqualified")
        contract["read_targets"] = [str(workspace)]
    if operation == "coordinating_implementation":
        contract["delegation"] = {"max_depth": 1, "result_consumption": "yield"}
        contract["allowed_operations"].append("canonical_child_commands")
        contract["authority"]["permitted_effects"].append("canonical_child_commands")
        brief.update(mandate="Coordinate bounded implementation through the authenticated owner child commands; retain integration responsibility and return evidence to the manager.")
        instruction += ("\nUse run-worker with a stable key only through authenticated native caller ingress. "
            "Retain the exact occurrence/start/command handles and use lookup-occurrence after a lost response. "
            "With capacity one, return/yield this turn after child preparation. The owner waits for your native release "
            "and resumes this exact parent for consume-result. Read child evidence and integrate; manager judgment "
            "remains required. The child is a finite leaf and cannot delegate. Never borrow manager credentials.")
        contract["bounded_operation"] = instruction
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
                 help_reply_authorizer: Any = None, authoring_authorizer: Any = None,
                 adapter_selection: Any = None, delegation_policy: Mapping[str, Any] | None = None,
                 external_execution_authorizer: Any = None, external_execution_policy: Mapping[str, Any] | None = None) -> None:
        self.server, self.host = server, host
        self._host_execution = server._execution
        self.run_path, self.workspace = Path(run_path).resolve(), Path(workspace).resolve()
        self.commands = ManagerJourneyCommands(owner=server.owner, portfolio=server.portfolio,
            state=server.state, policy=policy, due_port=server.due_port,
            settle_execution=self._settle_execution,
            native_bodies=getattr(server, "native_bodies", None))
        self.orchestrator_principal, self.observe_schedules = orchestrator_principal, observe_schedules
        self.help_reply_authorizer = help_reply_authorizer
        self.authoring_authorizer = authoring_authorizer
        self.adapter_selection = adapter_selection
        self.delegation_policy = None if delegation_policy is None else json_value(delegation_policy)
        self.external_execution_authorizer = external_execution_authorizer
        self.external_execution_policy = None if external_execution_policy is None else json_value(external_execution_policy)

    def _execution(self, **options: Any) -> Any:
        """Bind every execution path to the installed owner's assessment policy.

        Setup reads and provider admission must use the same authority. The
        host supplies adapters; neither transport nor setup JSON can choose
        assessment criteria or allowance.
        """
        from .local_assessment_policy import LocalAssessmentPolicy
        # Validate the same single declaration used by worker admission before
        # constructing a manager application/initializer, including callbacks
        # and effective-context reads. Do not guess between legacy/current files.
        if options.get("principal") == self.server.state.get("manager"):
            from .run_config import run_config_path
            run_config_path(self.run_path)
        selection = options.pop("selection", None)
        app = (self.adapter_selection.compose(selection, **{k: v for k, v in options.items() if k not in {"model", "reasoning"}})
               if selection is not None and self.adapter_selection is not None else self._host_execution(**options))
        if hasattr(self, "_fixed_project_binding"):
            from .project_services import ProjectServices
            ProjectServices._check(self)
            if (Path(app.runtime.adapter.worktree).resolve() != self.workspace
                    or Path(app.runtime.adapter.source).resolve() != self.run_path
                    or app.manager_actor != self.server.state["manager"]
                    or app.runtime.adapter.owner != options["principal"]
                    or app.actor != self.server.owner.owner_actor.actor
                    or app.due_port is not self.server.due_port
                    or app.assignments is not self.server.owner.assignments.command_port):
                raise PermissionError("adapter identity, workspace or owner ports differ from its fixed project view")
        if selection is not None and app.native_adapter_identity() != selection["identity"]:
            raise PermissionError("installed composition differs from retained adapter pins")
        policy = self.commands.policy or self.server.state.get("assessment_policy")
        if isinstance(policy, Mapping):
            policy = LocalAssessmentPolicy.from_run_config(policy, state=self.server.state)
        trusted = self.server.owner.role_runtime(due_port=self.server.due_port,
            adapter=app.runtime.adapter, assessment_policy=policy,
            native_result_verifier=app.runtime.native_result_verifier)
        app.runtime.acceptance_readiness = trusted.acceptance_readiness
        return app

    def _settle_execution(self, due: Mapping[str, Any]) -> Mapping[str, Any]:
        app = self._execution(principal=due["recipient"], model=due["requested_model"],
            reasoning=due["requested_reasoning"], evidence_id=due["schedule_id"],
            selection=(due["target"].get("launch_request") or {}).get("selection"))
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
        observed = [view.get("project", {}).get("observed", {})]
        observed.extend(task.get("observed", {}) for task in view.get("tasks", ()) if isinstance(task, Mapping))
        assignment_refs = [item["ref"] for projection in observed if isinstance(projection, Mapping)
                           for item in projection.get("assignments", ()) if isinstance(item, Mapping) and "ref" in item]
        reports = read_project_progress_reports(self.server.store.consumer(), project_ref,
                                               assignment_refs=assignment_refs)
        loop = self.server.portfolio._issue_loop()
        help_read = loop.read_issues(project_ref=project_ref) if loop is not None else {"issues": []}
        issues = help_read.get("issues", []) if isinstance(help_read, Mapping) else []
        occurrences = self._known_occurrences(state)
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
        operating_setup = self._operating_setup(state)
        handoff = self._handoff(view=view, status=status, operation=operation,
            operating_setup=operating_setup,
            occurrences=occurrences, help_issues=issues)
        return {
            "outcome": "ok", "project_ref": project_ref,
            "task_refs": state["task_refs"], "workers": state.get("workers", {}),
            "workers_state_basis": "retained launch snapshots; current execution is in handoff occurrences",
            "manager": state.get("manager"), "manager_assignment_ref": state.get("assignment_ref"),
            # Status is a bounded projection; the dedicated operating-setup
            # command remains the full role-introduction/readiness readback.
            "operating_setup": handoff["operating_setup"],
            "handoff": handoff,
            "status": status, **status,
        }

    def _known_occurrences(self, state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        """Read only exact handles already named by the current owner state."""
        rows = []
        for schedule_id in self._known_schedule_ids(state)[:128]:
            value = self.server.due_port.read_due(schedule_id)
            if isinstance(value, Mapping):
                rows.append(dict(value))
        return rows

    def _current_manager_schedule(self) -> str:
        """Select current owner-issued preparation without discarding effects."""
        state = self.server.state
        historical = (state.get("manager_continuation") or {}).get("schedule_id")
        for schedule in dict.fromkeys(filter(None, (historical, state.get("schedule_id")))):
            due = self.server.due_port.read_due(schedule)
            if not isinstance(due, Mapping):
                raise PermissionError("retained manager occurrence is missing")
            if (due.get("role") != "manager" or due.get("recipient") != state["manager"]
                    or tuple(due["target"]["project_ref"][k] for k in ("authority", "kind", "id"))
                    != tuple(state["project_ref"][k] for k in ("authority", "kind", "id"))
                    or tuple(due["assignment_ref"][k] for k in ("authority", "kind", "id"))
                    != tuple(state["assignment_ref"][k] for k in ("authority", "kind", "id"))
                    or due.get("generation") != state["manager_generation"]):
                raise PermissionError("retained manager occurrence is foreign")
            if due.get("assignment_ref") == state["assignment_ref"]:
                return schedule
            # Only a verified finalized success can be historical under a new
            # adopted BASE. UNKNOWN or unattempted stale intent is held.
            evidence = due.get("completion_evidence") or {}
            if (due.get("stop_state") != "completed" or due.get("completion_state") != "succeeded"
                    or due.get("in_flight_request") is not None
                    or evidence.get("schema") != "otto.role-result.v1"
                    or not evidence.get("result_digest")):
                raise PermissionError("stale manager effects require exact reconciliation")
        raise PermissionError("no current owner-issued manager occurrence")

    @staticmethod
    def _known_schedule_ids(state: Mapping[str, Any]) -> list[str]:
        """Share bounded locators without hydrating result payloads."""
        ids: list[str] = []
        for value in (state.get("schedule_id"), (state.get("manager_continuation") or {}).get("schedule_id")):
            if isinstance(value, str) and value and value not in ids:
                ids.append(value)
        for worker in (state.get("workers") or {}).values():
            if isinstance(worker, Mapping) and isinstance(worker.get("schedule_id"), str):
                if worker["schedule_id"] not in ids:
                    ids.append(worker["schedule_id"])
        for schedule in state.get("retired_manager_occurrences", ()):
            if isinstance(schedule, str) and schedule and schedule not in ids:
                ids.append(schedule)
        return ids

    def _operating_setup(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        """Read the adopted setup through the same owner-bound execution path."""

        try:
            app = self._execution(
                principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="operating-setup-status",
            )
            return app.read_operating_setup(project_ref=state["project_ref"])
        except Exception as exc:
            # Status remains a useful bounded read when setup is absent or the
            # older host has not exposed its setup reader yet.
            return {"outcome": "read", "state": "unknown", "ready": False,
                    "dispatch": False, "provider_called": False,
                    "reason": "operating setup readback unavailable",
                    "error": str(exc)[:512]}

    def _effective_context(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        """Prepare current instructions through the trusted owner readers."""
        target = operation.get("target") if isinstance(operation.get("target"), Mapping) else {}
        project_ref = target.get("project_ref") or self.server.state.get("project_ref")
        assignment_ref = operation.get("assignment_ref") or self.server.state.get("assignment_ref")
        mandate_ref = target.get("mandate_ref") or operation.get("mandate_ref")
        task_ref = target.get("task_ref")
        generation = operation.get("generation") or self.server.state.get("manager_generation")
        if not all(isinstance(value, Mapping) for value in (project_ref, assignment_ref, mandate_ref)):
            return {"state": "unknown", "reason": "current occurrence has no complete instruction refs"}
        if not isinstance(generation, int) or isinstance(generation, bool):
            return {"state": "unknown", "reason": "current assignment generation is unavailable"}
        try:
            from .operating_brief import prepare_canonical_operating_brief
            from .owner_readers import assignment_reader, mandate_reader, project_reader, task_reader
            operations = self.server.portfolio.operations
            kwargs: dict[str, Any] = {
                "role": "manager", "project_ref": project_ref,
                "assignment_ref": assignment_ref, "mandate_ref": mandate_ref,
                "expected_generation": generation,
                "project_reader": project_reader(operations, project_ref),
                "assignment_reader": assignment_reader(operations, assignment_ref),
                "mandate_reader": mandate_reader(operations, project_ref, mandate_ref),
                "resource_reader": operations.content_port,
                "direction_context_reader": getattr(operations, "direction_context_reader", None),
                "as_of": self._as_of(),
            }
            if isinstance(task_ref, Mapping):
                kwargs["task_ref"] = task_ref
                kwargs["task_reader"] = task_reader(operations, project_ref, task_ref)
            prepared = prepare_canonical_operating_brief(**kwargs)
            render = prepared.get("render") if isinstance(prepared.get("render"), Mapping) else {}
            base = prepared.get("base_resource") if isinstance(prepared.get("base_resource"), Mapping) else {}
            from .role_context import effective_context_projection, selected_configuration
            configuration = selected_configuration(prepared.get("supporting_context", []))
            tools = configuration["content"].get("tool_entrypoints", {}) if configuration else {}
            tool_entrypoint = tools.get("manager") if isinstance(tools, Mapping) else None
            if not isinstance(tool_entrypoint, str) or not tool_entrypoint.strip():
                tool_entrypoint = "python -m otto.portfolio.cli help --format text"
            effective = effective_context_projection(prepared, tool_entrypoint=tool_entrypoint)
            contract = prepared.get("mandate_instruction_contract")
            contract_view = None
            if isinstance(contract, Mapping):
                contract_view = {key: contract.get(key) for key in
                    ("source_ref", "task_ref", "assignment_ref", "generation", "dispatch_enabled")
                    if key in contract}
            role_instructions = render.get("role_instructions")
            instruction_preview = role_instructions[:2048] if isinstance(role_instructions, str) else None
            return {
                "state": "known", "role": prepared.get("role"),
                "generation": prepared.get("generation"),
                "source_refs": prepared.get("source_refs"),
                "base_resource": {key: base.get(key) for key in ("ref", "revision", "content_sha256") if key in base},
                "instruction_sha256": self._digest_text(role_instructions),
                "role_instructions": instruction_preview,
                "role_instructions_truncated": isinstance(role_instructions, str) and len(role_instructions) > len(instruction_preview or ""),
                "mandate_instruction_contract": contract_view,
                "direction_context": prepared.get("direction_context", []),
                **effective,
                "evidence_sha256": prepared.get("evidence_sha256"),
            }
        except Exception as exc:
            return {"state": "unknown", "reason": "current operating brief unavailable", "error": str(exc)[:512],
                    "source_refs": {"project": project_ref, "assignment": assignment_ref, "mandate": mandate_ref}}

    @staticmethod
    def _digest_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_of() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _budget(self) -> Mapping[str, Any]:
        configured = self.server.state.get("assessment_policy")
        if not isinstance(configured, Mapping):
            return {"state": "unknown", "reason": "owner assessment policy is unavailable"}
        try:
            from herzchen.contracts import ResourceRef
            from herzchen.kernel import LimitService
            pool_value = configured.get("pool_ref")
            if pool_value is None:
                pool_value = {"authority": self.server.state["authority"], "kind": "limit", "id": configured["pool_id"]}
            pool = LimitService(self.server.store).get_pool(ResourceRef.from_dict(pool_value))
            if pool is None:
                return {"state": "unknown", "pool_ref": pool_value, "reason": "owner limit pool is missing"}
            return {"state": "known", "pool_ref": pool.ref.to_dict(),
                    "capacity_units": pool.capacity_units,
                    "cumulative_allowance_units": pool.cumulative_allowance_units,
                    "held_units": pool.held_units,
                    "cumulative_used_units": pool.cumulative_used_units,
                    "available_capacity_units": pool.available_capacity_units,
                    "remaining_allowance_units": pool.remaining_allowance_units,
                    "local_only": configured.get("local_only") is True,
                    "source": "owner.limit.reader"}
        except Exception as exc:
            return {"state": "unknown", "reason": "owner limit read failed", "error": str(exc)[:512]}

    def _handoff(self, *, view: Mapping[str, Any], status: Mapping[str, Any],
                 operation: Mapping[str, Any], occurrences: Sequence[Mapping[str, Any]],
                 help_issues: Sequence[Mapping[str, Any]],
                 operating_setup: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        state = self.server.state
        project_ref = state["project_ref"]
        assignment = None
        try:
            from herzchen.contracts import ResourceRef
            current = self.server.owner.assignments.command_port.get(ResourceRef.from_dict(state["assignment_ref"]))
            assignment = self.server.portfolio.operations._assignment_dict(current)
        except Exception:
            assignment = {"ref": state.get("assignment_ref"), "principal": state.get("manager"),
                          "generation": state.get("manager_generation"), "role": "manager", "status": "unknown"}
        inventory = {"state": "unknown", "reason": "manager inventory unavailable"}
        try:
            raw_inventory = self.server.portfolio.manager_inventory(actor=state["owner"])
            if isinstance(raw_inventory, Mapping):
                matches = [item for item in raw_inventory.get("projects", [])
                           if isinstance(item, Mapping) and item.get("project_ref") == project_ref]
                inventory = {key: raw_inventory.get(key) for key in
                             ("outcome", "read_only", "native_observation", "historical_reuse") if key in raw_inventory}
                inventory["state"] = "known"
                inventory["project"] = matches[0] if matches else {"project_ref": project_ref, "state": "unknown"}
        except Exception as exc:
            inventory = {"state": "unknown", "reason": "manager inventory read failed", "error": str(exc)[:512]}
        inbox = {}
        try:
            inbox = self.server.portfolio.manager_inbox(project_ref, actor=state["owner"], limit=128, safety_scan=True)
        except Exception as exc:
            inbox = {"error": str(exc)[:512]}
        current_id = operation.get("schedule_id")
        current = next((item for item in occurrences if item.get("schedule_id") == current_id), operation)
        history = [item for item in occurrences if item.get("schedule_id") != current_id]
        return compose_manager_handoff(
            project_ref=project_ref, project=view.get("project"), assignment=assignment,
            assignment_ref=state.get("assignment_ref"), current_occurrence=current,
            historical_occurrences=history, effective_context=self._effective_context(operation),
            status=status, tasks=inbox.get("task_rows", inbox.get("tasks", [])) if isinstance(inbox, Mapping) else [],
            results=inbox.get("results", []) if isinstance(inbox, Mapping) else [],
            reports=inbox.get("reports", []) if isinstance(inbox, Mapping) else [],
            decisions=inbox.get("decisions", []) if isinstance(inbox, Mapping) else [],
            advisory_findings=(inbox.get("advisory_findings", inbox.get("advisory", ()))
                               if isinstance(inbox, Mapping) else []),
            operating_setup=operating_setup,
            help_state={"state": "known", "issues": list(help_issues)[:128]}, budget=self._budget(),
            inventory=inventory, as_of=self._as_of(),
        )

    def authorize_caller(self, context: Mapping[str, Any], request: Mapping[str, Any]) -> None:
        """A tool caller cannot inherit this service's single manager custody.

        Child/administrative targets remain command-specific and explicit.
        Operational reply grants keep their existing separate ingress.
        """
        state = self.server.state
        if request.get("command") == "operating-setup" and request.get("operation", "read") not in {"read", "preview"}:
            raise PermissionError("native setup callers may read or preview; setup mutations require owner custody")
        if getattr(self.host, "bounded_transports", False) and (
                request.get("command") in {"start-manager", "start-retained-worker", "start-retained-help",
                    "manager-worker-result", "manager-task-settlement", "manager-help-result",
                    "start-retained-child", "parent-child-result"}
                or request.get("command") == "manager-continue" and request.get("operation") == "dispatch"
                or request.get("command") == "operating-setup" and request.get("operation") == "activate"
                or request.get("command") == "execution-control" and request.get("operation") == "resume"):
            raise PermissionError("native callers prepare work and return; retained starts belong to the owner")
        if context.get("role") == "worker":
            from .worker_occurrences import authorize_worker
            authorize_worker(self, context, request)
            return
        self.commands._authorize()
        if (context.get("role") != "manager" or context.get("principal") != state["manager"]
                or context.get("assignment_ref") != state["assignment_ref"]
                or context.get("generation") != state["manager_generation"]):
            raise PermissionError("caller is not the current manager of this command service")

    def dispatch_bound(self, context: Mapping[str, Any], request: Mapping[str, Any]) -> Mapping[str, Any]:
        token = _CALLER.set(context)
        try:
            return self(request)
        finally:
            _CALLER.reset(token)

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        command = request.get("command")
        if command == "vision":
            installation = getattr(self.server, "vision", None)
            if installation is None:
                raise PermissionError("current owner Vision composition is not installed")
            context = _CALLER.get()
            if context is None:
                actor = self.authoring_authorizer(request)
                return self.server.document_editor.dispatch(request, actor=actor)
            self.authorize_caller(context, request)
            from .herzchen_binding import ProjectReadGrant
            from herzchen.content.model import DocumentAssociation
            from herzchen.content.vision_queries import vision_attachment_key
            from herzchen.contracts import ReferenceBinding
            project = ResourceRef.from_dict(self.server.state["project_ref"])
            actor = self.server.owner.binding.authenticated_actor(context["principal"])
            grant = ProjectReadGrant(actor, (project.id,), "current-Vision-manager", "v1")
            reader = self.server.owner.store.consumer()
            def membership(project_ref, document_ref, invoking_actor):
                if project_ref != project or invoking_actor != actor:
                    return False
                subject = ResourceRef(project.authority, project.kind, project.id)
                document = ResourceRef(document_ref.authority, document_ref.kind, document_ref.id)
                association = DocumentAssociation(subject, "project.documents", vision_attachment_key(document),
                                                  ReferenceBinding(document, "current"))
                row = reader.get_record(ResourceRef(project.authority, "document-association", association.identity))
                if row is None or row.payload.get("active") is not True:
                    return False
                return DocumentAssociation.from_dict(row.payload["association"]) == association
            return installation.agent_read(request, actor=actor, project_ref=project,
                                           grant=grant, membership_reader=membership)
        if command in {"lookup-occurrence", "follow-occurrence", "read-result", "read-artifact", "consume-result",
                       "start-retained-child", "parent-child-result"}:
            from .worker_occurrences import dispatch_occurrence
            return dispatch_occurrence(self, request, _CALLER.get())
        if command == "owner-execution":
            from .external_owner_execution import dispatch
            return dispatch(self, request)
        if command == "owner-context":
            return self._owner_context(request)
        if command == "execution-control":
            return self._execution_control(request)
        if command == "document-authoring":
            editor = getattr(self.server, "document_editor", None)
            if editor is None or not callable(self.authoring_authorizer):
                raise PermissionError("authenticated document editor host is not installed")
            return editor.dispatch(request, actor=self.authoring_authorizer(request))
        if command == "project-authoring":
            return self._project_authoring(request)
        if command == "project-queue":
            return self._project_queue(request)
        if command == "task-list-author":
            result = self.commands.author_tasks(request)
            self.server._save_state()
            return result
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
            current_id = self._current_manager_schedule()
            prepared = app.continue_manager_from_help(manager_schedule_id=current_id,
                report_ref=request["report_ref"], execute=False)
            if prepared.get("outcome") not in {"committed", "prepared", "replayed"}:
                return prepared
            if prepared["outcome"] == "replayed":
                return prepared  # An old reply never replaces the current manager handle.
            due = app._read(prepared["schedule_id"])
            if not advance_manager_head(state, expected=current_id, due=due, settled_anchor=current_id):
                return {**prepared, "outcome": "held", "reason": "manager head advanced after preparation",
                        "provider_called": False, "effects_started": False, "retry": False}
            self.server._save_state()
            result = app.recover(schedule_id=due.schedule_id, execute=True)
            def complete(result):
                if complete_manager_head(state, schedule_id=due.schedule_id, result=result):
                    self.server._save_state()
                result = self._finalize_manager_completion(result, app=app)
                return result
            return after_owner(result, complete)
        if command == "operating-setup":
            self.commands._authorize()
            if set(request) - {"command", "operation", "setup", "request_key", "expected_setup_ref"}:
                raise ValueError("operating setup cannot change the bound project or owner")
            state = self.server.state
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="operating-setup")
            operation = request.get("operation", "read")
            if operation in {"preview", "apply", "update"}:
                return app.compose_operating_setup(project_ref=state["project_ref"], operation=operation,
                    setup=request.get("setup"), request_key=request.get("request_key"),
                    expected_setup_ref=request.get("expected_setup_ref"))
            if request.get("expected_setup_ref") is not None:
                raise ValueError("expected_setup_ref belongs only to setup preview/update")
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
            def complete(result):
                if result.get("outcome") in {"succeeded", "replayed"}:
                    if complete_manager_head(state, schedule_id=due.schedule_id, result=result):
                        self.server._save_state()
                    result = self._finalize_manager_completion(result, app=app)
                return result
            return after_owner(result, complete)
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
            current_id = self._current_manager_schedule()
            app = self._execution(principal=state["manager"], model=state["requested_model"],
                reasoning=state["requested_reasoning"], evidence_id="manager-worker-result-" + worker["schedule_id"])
            result = app.continue_manager_from_worker(manager_schedule_id=current_id,
                worker_schedule_id=worker["schedule_id"], execute=True)
            def complete(result):
                if result.get("outcome") in {"succeeded", "replayed"}:
                    if advance_manager_head(state, expected=current_id,
                            due=app._read(result["schedule_id"]), settled_anchor=current_id):
                        complete_manager_head(state, schedule_id=result["schedule_id"], result=result)
                        self.server._save_state()
                    result = self._finalize_manager_completion(result, app=app)
                return result
            return after_owner(result, complete)
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
            return after_owner(result, lambda result: self._finalize_manager_completion(result, app=app))
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
                result = self._with_task_settlement_notification(result, app)
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
                reasoning=worker["reasoning"], evidence_id=worker["schedule_id"],
                selection=((self.server.due_port.read_due(worker["schedule_id"]) or {}).get("target", {}).get("launch_request") or {}).get("selection"))
            if command == "start-retained-worker":
                # The worker's original parent remains immutable historical evidence.
                # Resource adoption may advance that parent's assignment pins;
                # synchronize only the fixed view's current manager entrance.
                manager_schedule = self._current_manager_schedule()
                sync = getattr(app, "synchronize_manual_manager_occurrence", None)
                if callable(sync):
                    sync(schedule_id=manager_schedule)
            result = (app.start(schedule_id=worker["schedule_id"]) if command == "start-retained-worker" else
                      app.recover(schedule_id=worker["schedule_id"], execute=False))
            def complete(result):
                external_parent = ((self.server.due_port.read_due(worker["schedule_id"]) or {}).get("target", {}).get("launch_request") or {}).get("external_parent")
                if result.get("outcome") in {"succeeded", "replayed"} and external_parent is None:
                    result = self._settle_shared_completion(result, review_task=request["task"])
                    if result["completion_intents"]:
                        state = self.server.state
                        manager_app = self._execution(principal=state["manager"], model=state["requested_model"],
                            reasoning=state["requested_reasoning"], evidence_id="manager-task-settlement")
                        result = self._with_task_settlement_notification(result, manager_app)
                    if command == "start-retained-worker":
                        if self.host._closing and not getattr(self.host, "bounded_transports", False):
                            retained = {"outcome": "held", "provider_called": False,
                                "reason": "owner is draining; preserve worker result and prepare its manager continuation after restart"}
                        else:
                            retained = self.host.submit({"command": "manager-worker-result", "task": request["task"],
                                "principal": worker["principal"], "schedule_id": worker["schedule_id"]})
                        result = {**result, "manager_result_notification": retained}
                return result
            return after_owner(result, complete)
        return self.server.handle(request)

    def root_direction_client(self, request: Mapping[str, Any], root: Any) -> Mapping[str, Any]:
        """Trusted scoped-client handler after canonical policy verification.

        This is not a JSON dispatch command. The installed lane supplies the
        canonical root object; neither the payload nor a secondary root selects
        an owner actor or direction subject.
        """
        from .root_direction_client import RootDirectionAuthoring
        current = self.server.state['orchestrator_assignment_ref']
        if (root.ref.to_dict() != current or root.principal != self.server.owner.owner_actor.actor
                or root.role != 'orchestrator' or root.generation < 1):
            raise PermissionError('direction client is not the exact current host owner root')
        return RootDirectionAuthoring(self).call(request, root)

    def _owner_context(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Finite external owner capability; never native process identity.

        The host binds the root responsibility. Request JSON cannot choose a
        principal, PID, session, assignment or foreign direction subject.
        """
        if not callable(self.authoring_authorizer):
            raise PermissionError("external owner context ingress is not installed")
        actor = self.authoring_authorizer(request)
        owner = self.server.owner
        if actor != owner.owner_actor:
            raise PermissionError("owner context requires the authenticated service owner")
        return self._authenticated_owner_context(request, actor)

    def _authenticated_owner_context(self, request: Mapping[str, Any], actor: Any) -> Mapping[str, Any]:
        owner = self.server.owner
        if actor != owner.owner_actor:
            raise PermissionError("owner context requires the authenticated service owner")
        operation = request.get("operation")
        fields = {"command", "operation", "request_key"}
        if operation == "direction-draft":
            fields |= {"content", "expected_revision"}
        elif operation == "direction-adopt":
            fields |= {"document_ref", "expected_binding_ref"}
        elif operation == "direction-synchronize":
            fields |= {"document_ref", "expected_binding_ref", "handle"}
        elif operation == "events-read":
            fields |= {"handle"}
        elif operation not in {"whoami", "effective-context", "direction-read", "direction-history"}:
            raise ValueError("unsupported external owner context operation")
        if set(request) != fields:
            raise ValueError("owner context fields differ; identity and subject are host-bound")
        key = request.get("request_key")
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            raise ValueError("owner context requires an exact read correlation or mutation request key")
        root_ref = ResourceRef.from_dict(self.server.state["orchestrator_assignment_ref"])
        root = owner.assignments.get(root_ref)
        if (root.ref != root_ref or root.role != "orchestrator"
                or root.principal != actor.actor or root.scope.kind != "wrk.portfolio"
                or root.status.value == "cancelled"):
            raise PermissionError("current host root portfolio responsibility is stale or foreign")
        subject = ResourceRef.from_dict(root.payload["responsibility_ref"])
        surface = owner.direction_surface()
        common = {"schema": "otto.external-owner-context.v1",
                  "identity_origin": "authenticated external owner input capability",
                  "native_process_identity_claimed": False,
                  "native_delivery_verified": False, "provider_called": False,
                  "principal": root.principal, "role": root.role,
                  "assignment_ref": root.ref.to_dict(), "generation": root.generation,
                  "scope_ref": root.scope.to_dict(), "responsibility_ref": subject.to_dict()}
        if operation == "events-read":
            return {**common, "outcome": "read", "read_only": True,
                    **self._owner_events_read(request["handle"], actor, root)}
        if operation == "whoami":
            return {**common, "outcome": "read", "read_only": True,
                    "canonical_conversation": root.payload.get("session"),
                    "conversation_limit": "Canonical conversation metadata is not proof of the invoking desktop process."}
        if operation == "direction-history":
            return {**common, "history": surface.history(subject), "read_only": True, "outcome": "read"}
        if operation == "direction-draft":
            return {**common, "outcome": "drafted", "read_only": False,
                    "draft": surface.draft(subject, request["content"], logical_request_key=key,
                                           expected_revision=request["expected_revision"]),
                    "assignment_resources_refreshed": False}
        if operation == "direction-synchronize":
            handle = request["handle"]
            if (not isinstance(handle, Mapping) or set(handle) != {
                    "assignment_ref", "generation", "resources", "expected_default_ref", "projects"}
                    or any(handle["assignment_ref"].get(k) != root.ref.to_dict().get(k)
                           for k in ("authority", "kind", "id"))
                    or handle["generation"] != root.generation):
                raise PermissionError("synchronization handle is not the bound root")
            from .owner_bootstrap import PortfolioOwnerBootstrap
            scoped = PortfolioOwnerBootstrap(owner.store, binding=owner.binding,
                owner_actor=actor.actor, portfolio_ref=root.scope,
                main_assignment_ref=root.ref, expected_main_principal=actor.actor)
            result = scoped.synchronize_portfolio_direction(
                **handle, direction_ref=request["document_ref"],
                expected_binding_ref=request["expected_binding_ref"], logical_request_key=key)
            self.server.state["orchestrator_assignment_ref"] = result["assignment_ref"]
            if self.server.state.get("root_help_binding") is not None:
                self.server.state["root_help_binding"] = {**self.server.state["root_help_binding"],
                    "assignment_ref": result["assignment_ref"], "generation": result["generation"]}
            if "project_ref" in self.server.state:
                self._refresh_refs()
            else:self.server._save_state()
            return {**common, **result, "read_only": False,
                    "assignment_ref": result["assignment_ref"],
                    "runtime_requalification_required": True,
                    "next_action": "Retain these canonical receipts. Qualify current setup/manager locators at the normal closed adoption boundary before future provider work; historical Due stays immutable."}
        if operation == "direction-adopt":
            # Scope adoption is explicit. Refreshing BASE would advance the
            # root assignment and stale enrolled project joins. That separate
            # existing Work boundary must preserve all current enrollments.
            result = surface.update(subject, request["document_ref"], logical_request_key=key,
                                    expected_binding_ref=request["expected_binding_ref"])
            return {**common, "outcome": "scope-adopted", "read_only": False,
                    "adoption": result, "assignment_resources_refreshed": False,
                    "next_action": "At a closed owner boundary, adopt the revised direction in the root BASE through Work and refresh exact portfolio project joins. Scope adoption alone does not change assignment-effective instructions."}
        direction = surface.read(subject, assignment_ref=root.ref, generation=root.generation)
        scope_direction = surface.read(subject)
        if operation == "direction-read":
            return {**common, "outcome": "read", "read_only": True,
                    "assignment_direction": direction, "scope_direction": scope_direction}
        resources = []
        for adoption in root.payload.get("resource_adoptions", ()):
            pin = adoption["resource_ref"]
            resources.append({"ref": pin, "content": owner.content.read(ResourceRef.from_dict(pin))["content"],
                              "content_digest": adoption["content_digest"]})
        execution = {"state": "configured" if self.external_execution_policy else "unavailable",
            "policy": self.external_execution_policy,
            "tool_entrypoint": self.server.state.get("external_execution_tool_entrypoint"),
            "operations": ["launch", "lookup", "follow", "result", "artifact", "consume"],
            "authority": "distinct protected owner execution grant; authoring and native credentials do not grant it"}
        return {**common, "outcome": "read", "read_only": True,
                "external_execution": execution, "shared_role_resources": resources, "assignment_direction": direction,
                "scope_direction": scope_direction,
                "context_limit": "Canonical adopted root resources and direction only; this is not a native invocation or all-project context transcript."}

    def _owner_events_read(self, handle: Any, actor: Any, root: Any) -> Mapping[str, Any]:
        """Bind the existing public Events CLI/facade to this authenticated host.

        This operation never opens a Store or advances its projection. Scope
        and identity come from the current enrolled root, not request JSON.
        """
        from herzchen.kernel.project_history import ProjectHistoryGrant
        from .direction_context import read_direction_context
        from .observability_views import ObservabilityViews, VIEW_PRESETS
        from .cli import build_parser, _events_command, _render_text
        if not isinstance(handle, Mapping):
            raise ValueError("Events read handle must be an object")
        view = handle.get("view")
        common_fields = {"view", "format", "snapshot"}
        allowed = (common_fields | {"facet_id", "max_detail_bytes"} if view == "detail" else
                   common_fields | {"from_at", "to_at", "timezone_name", "active_during", "limit", "cursor", "filters"})
        if not isinstance(view, str) or view not in {*VIEW_PRESETS, "detail"} or set(handle) - allowed:
            raise ValueError("unsupported Events read fields; actor and project are host-bound")
        fmt = handle.get("format", "json")
        if not isinstance(fmt, str) or fmt not in {"json", "text"}:
            raise ValueError("Events read format must be json or text")
        limit = handle.get("limit", 1)
        max_bytes = handle.get("max_detail_bytes", 16384)
        if type(limit) is not int or not 1 <= limit <= 50 or type(max_bytes) is not int or not 1 <= max_bytes <= 65536:
            raise ValueError("Events read page/detail bounds are invalid")
        if view == "detail" and (not isinstance(handle.get("facet_id"), str)
                or not handle["facet_id"].strip() or not isinstance(handle.get("snapshot"), Mapping)):
            raise ValueError("Events detail requires exact facet_id and original snapshot")
        project = ResourceRef.from_dict(self.server.state["project_ref"])

        def current_grant() -> Any:
            current_ref = ResourceRef.from_dict(self.server.state["orchestrator_assignment_ref"])
            current = self.server.owner.assignments.get(current_ref)
            if (current_ref != root.ref or current.ref != root.ref or current.generation != root.generation
                    or current.principal != actor.actor or current.status.value == "cancelled"):
                raise PermissionError("Events root read responsibility changed")
            read_direction_context(self.server.owner.direction_bindings(), actor=actor,
                assignment_ref=current.ref, generation=current.generation, project_ref=project.to_dict())
            return ProjectHistoryGrant(actor, (project.id,), "authenticated-owner-events-host",
                hashlib.sha256(json.dumps({"root": current.ref.to_dict(), "generation": current.generation,
                    "project": {"authority": project.authority, "kind": project.kind, "id": project.id}},
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest())

        grant = current_grant()
        views = ObservabilityViews(self.server.owner.store.project_history_reader(grant_reader=current_grant))
        argv = ["events", view, "--actor", actor.actor, "--project-ref", json.dumps(project.to_dict()), "--format", fmt]
        if view == "detail":
            argv += ["--facet-id=" + handle["facet_id"], "--max-detail-bytes", str(max_bytes)]
        else:
            argv += ["--limit", str(limit)]
        for field, option in (("from_at", "--from"), ("to_at", "--to"), ("timezone_name", "--timezone"),
                              ("cursor", "--cursor"), ("snapshot", "--snapshot"),
                              ("filters", "--filters"), ("active_during", "--active-during")):
            if field in handle:
                value = handle[field]
                if field in {"snapshot", "filters", "active_during"}:
                    value = json.dumps(value)
                elif not isinstance(value, str) or not value.strip():
                    raise ValueError("Events " + field + " requires an exact nonempty string")
                argv += [option + "=" + value]
        result = _events_command(build_parser().parse_args(argv), views, grant)
        return {"project_ref": project.to_dict(), "events": result, "format": fmt,
                "rendered": _render_text(result) if fmt == "text" else json.dumps(result, sort_keys=True, indent=2),
                "writes": 0, "dispatch": False, "launch": False}

    def _reminder_ids(self) -> tuple[str, ...]:
        """Only owner composition supplies reminder IDs; request JSON cannot."""
        values = getattr(self.server, "reminder_schedule_ids", self.server.state.get("reminder_schedule_ids", ()))
        if (not isinstance(values, (list, tuple)) or len(values) > 128
                or any(not isinstance(x, str) or not x.strip() for x in values)):
            raise ValueError("owner reminder IDs must be a bounded explicit sequence")
        ids = tuple(dict.fromkeys(values))
        for sid in ids:
            due = self.server.due_port.read_due(sid)
            if due is not None and due.get("project_ref") != self.server.state["project_ref"]["id"]:
                raise PermissionError("owner reminder occurrence is outside the current project")
        return ids

    def _startup_recovery(self, app: Any, known: Any, *, execute: bool) -> Mapping[str, Any]:
        """Join native recovery with separately scoped host reminder readback.

        Reminder holds are explicit and do not suppress unrelated native
        diagnosis. No request can select host authority or reminder IDs.
        """
        ids = self._reminder_ids()
        attention = getattr(self.server, "reminder_attention", None)
        executor = getattr(self.server, "reminder_host_executor", None)
        if not ids or attention is None:
            result = app.recover_startup(schedule_ids=known, execute=execute) if app is not None else {
                "schema": "otto.owner-startup-recovery.v1", "outcome": "reconciled", "admission": "ready",
                "occurrences": [], "execute": execute, "provider_called": False, "dispatch": False, "launch": False}
            from otto.attention import DurableAttention
            reader = DurableAttention(None, due_port=self.server.due_port)
            reminder = {"schema": "otto.reminder-startup-reconciliation.v1",
                "outcome": "held" if ids else "not-configured",
                "admission": "held" if ids else "unavailable",
                "reason": "owner_reminder_bridge_unavailable" if ids else "no_owner_reminder_ids",
                "mapping_state": "configured" if ids else "unconfigured",
                "wake_state": "unknown", "canonical_schedule_ids": list(ids),
                "evaluate_due": False, "host_mutation": False,
                "rows": [{"schedule_id": sid, "status": reader.reminder_status(sid),
                          "bridge": {"outcome": "held", "reason": "owner_reminder_bridge_unavailable"}, "due": None} for sid in ids],
                "next_action": "Owner supplies exact known reminder IDs and authenticated readback/attention ports; no timer or wake is inferred."}
            return after_owner(result, lambda result: {**result, "reminder_reconciliation": reminder,
                    "reminder_admission": reminder["admission"]})
        if app is None:
            reminder = attention.startup_reconcile(ids, executor=executor, evaluate_due=True)
            return {"schema": "otto.owner-startup-recovery.v1", "outcome": "reconciled", "admission": "ready",
                "occurrences": [], "execute": execute, "provider_called": False, "dispatch": False, "launch": False,
                "reminder_reconciliation": reminder, "reminder_admission": reminder["admission"]}
        return app.recover_startup(schedule_ids=known, execute=execute,
            reminder_attention=attention, host_executor=executor,
            reminder_schedule_ids=ids, evaluate_due=True)

    def _execution_control(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Use current service bindings and existing Due/host recovery ports."""
        self.commands._authorize()
        if set(request) - {"command", "operation", "schedule_id", "request_key", "expected_version"}:
            raise ValueError("execution control cannot change the bound owner or assignment")
        operation = request.get("operation", "read")
        if operation not in {"read", "reminder-read", "recover", "stop", "resume", "startup", "drain"}:
            raise ValueError("unsupported execution control operation")
        if operation == "drain":
            if any(request.get(k) is not None for k in ("schedule_id", "request_key", "expected_version")):
                raise ValueError("drain takes no occurrence fields")
            return self.host.begin_drain()
        state = self.server.state
        known = []
        for value in (state.get("schedule_id"), (state.get("manager_continuation") or {}).get("schedule_id")):
            if isinstance(value, str) and value and value not in known:
                known.append(value)
        for worker in (state.get("workers") or {}).values():
            value = worker.get("schedule_id") if isinstance(worker, Mapping) else None
            if isinstance(value, str) and value and value not in known:
                known.append(value)
        if operation == "reminder-read":
            if request.get("request_key") is not None or request.get("expected_version") is not None:
                raise ValueError("reminder-read takes only an exact owner-known schedule")
            sid = request.get("schedule_id")
            if sid not in self._reminder_ids():
                raise PermissionError("reminder read requires an owner-known schedule")
            from otto.attention import DurableAttention
            reader = getattr(self.server, "reminder_attention", None) or DurableAttention(None, due_port=self.server.due_port)
            return {**reader.reminder_status(sid), "read_only": True, "provider_called": False,
                    "host_readback_available": getattr(self.server, "reminder_host_executor", None) is not None}
        if operation == "startup":
            if any(request.get(k) is not None for k in ("schedule_id", "request_key", "expected_version")):
                raise ValueError("startup recovery takes no occurrence or mutation fields")
            if not known:
                return self._startup_recovery(None, [], execute=False)
            # The retained Due record is authoritative for the execution
            # binding.  Older owner state projections may not repeat the
            # model fields, while the current manager projection does.
            seed = self.server.due_port.read_due(known[0])
            app = self._execution(principal=state.get("manager", seed["recipient"]),
                model=state.get("requested_model", seed["requested_model"]),
                reasoning=state.get("requested_reasoning", seed["requested_reasoning"]),
                evidence_id="execution-startup-recovery")
            return self._startup_recovery(app, known, execute=False)
        schedule = request.get("schedule_id")
        allowed = set(known)
        if not isinstance(schedule, str) or not schedule or schedule not in allowed:
            raise PermissionError("execution control requires a current retained occurrence")
        raw = self.server.due_port.read_due(schedule)
        project_id = state["project_ref"]["id"]
        project = raw.get("project_ref") if isinstance(raw, Mapping) else None
        if (project.get("id") if isinstance(project, Mapping) else project) != project_id:
            raise PermissionError("occurrence belongs to another project")
        app = self._execution(principal=raw["recipient"], model=raw["requested_model"],
            reasoning=raw["requested_reasoning"], evidence_id="execution-control-" + schedule,
            selection=(raw["target"].get("launch_request") or {}).get("selection"))
        due = app._read(schedule)  # Existing authenticated owner fence.
        if operation == "stop":
            from otto.attention import DurableAttention
            version, key = request.get("expected_version"), request.get("request_key")
            if (not isinstance(key, str) or not key.strip() or isinstance(version, bool)
                    or not isinstance(version, int) or version < 1):
                raise ValueError("stop requires request_key and exact expected_version")
            return DurableAttention(None, due_port=self.server.due_port).stop(schedule,
                request_id=key, expected_version=version, project_ref=due.project_ref,
                manager_ref=due.manager_ref, generation=due.generation, lifecycle_owner=app.actor)
        if request.get("request_key") is not None or request.get("expected_version") is not None:
            raise ValueError("read/recover/resume take only the exact schedule")
        if operation == "read":
            from .execution_operations import compact_operation_status
            return {"outcome": "read", **compact_operation_status(raw),
                    "occurrence": {key: raw.get(key) for key in ("schedule_id", "version",
                        "assignment_ref", "generation", "stop_state", "host_state",
                        "completion_state", "in_flight_request")}, "provider_called": False}
        # Read the retained projection before checking admission.  Only a
        # genuinely prepared occurrence needs the operating-setup gate; a
        # stopped, paused, active, or already-captured occurrence must remain
        # diagnosable/reconcilable even when admission is currently held.
        if operation == "resume" and due.role == "manager" \
                and app.recovery_status(schedule_id=schedule)["state"] == "prepared":
            readiness = app.read_operating_setup(project_ref=state["project_ref"])
            if not readiness.get("ready"):
                return {"outcome": "blocked", "readiness": readiness,
                        "provider_called": False, "startup_recovery": {
                            "schema": "otto.owner-startup-recovery.v1", "outcome": "held",
                            "admission": "held", "occurrences": [], "provider_called": False,
                            "dispatch": False, "launch": False}}
        # Explicit resume and ordinary recover share the startup reconciliation
        # path.  It settles captured/accepted work first and only then allows
        # the existing start operation to admit a new native turn.
        startup = self._startup_recovery(app, [schedule], execute=operation == "resume")
        def complete(startup):
            row = startup["occurrences"][0]
            reconciled = row["result"]
            # Preserve the existing operation contract for terminal/held outcomes.
            # The startup projection can remain held for a stopped or paused
            # occurrence, but that must not turn the established `stopped` or
            # `paused` response into a new generic startup-blocked result.  A
            # successful replay likewise represents the response being returned
            # by this very control call, even when the projection still records
            # a response/notification phase to reconcile on a later read.
            if operation == "resume" and reconciled.get("outcome") in {
                    "succeeded", "replayed", "stopped", "paused"}:
                return {**reconciled, "startup_recovery": startup}
            if operation == "resume" and reconciled.get("outcome") == "blocked":
                return {**reconciled, "startup_recovery": startup}
            if operation == "resume" and startup.get("admission") != "ready":
                return {"outcome": "held", "provider_called": False, "retry": False,
                        "reason": "startup recovery is holding this occurrence before native admission",
                        "startup_recovery": startup, "next_action": startup.get("next_action")}
            return {**reconciled, "startup_recovery": startup} if operation == "recover" else reconciled

        return after_owner(startup, complete)

    def _project_queue(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Exact owner input, on the same finite serialized authoring lane."""
        if not callable(self.authoring_authorizer):
            raise PermissionError("authenticated owner queue ingress is not installed")
        actor = self.authoring_authorizer(request)
        if actor != self.server.owner.owner_actor:
            raise PermissionError("queue requires the authenticated service owner")
        values = {k: v for k, v in request.items() if v is not None}
        operation = values.get("operation", "read")
        fields = {"read": {"command", "operation", "consumer"},
                  "seed": {"command", "operation", "request_key", "order", "rule"},
                  "after": {"command", "operation", "request_key", "order", "rule",
                            "expected_revision", "predecessor_ref", "project_ref"}}
        if operation not in fields or set(values) != fields[operation]:
            raise ValueError("queue requires exactly its finite operation fields")
        from .project_queue import ProjectQueue
        queue = ProjectQueue(self.server.owner.consumer_operations())
        if operation == "read":
            return queue.read(actor=actor.actor, consumer=values["consumer"])
        return queue.apply(actor=actor.actor, request_id=values["request_key"], operation=operation,
            **{k: v for k, v in values.items() if k not in {"command", "operation", "request_key"}})

    def _project_authoring(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Finite sibling authoring on the existing owner lane; never dispatch."""
        if not callable(self.authoring_authorizer):
            return {"outcome": "denied", "reason": "host owner authoring authentication is not installed", "provider_called": False}
        actor = self.authoring_authorizer(request)
        if actor != self.server.owner.owner_actor:
            raise PermissionError("project authoring requires the authenticated service owner")
        allowed = {"command", "operation", "request_key", "edit", "template", "template_parameters",
                   "project_ref", "project_json", "session_id", "files", "document_changes"}
        if set(request) - allowed:
            raise ValueError("project authoring cannot change the bound owner or choose an execution operation")
        values = {key: value for key, value in request.items() if value is not None}
        operation = values.get("operation", "read")
        if operation == "create":
            # The parser emits these optional fields as null, while direct
            # callers may omit them. Normalize both forms before the exact
            # operation-field check.
            values.setdefault("template", None)
            values.setdefault("template_parameters", None)
        common = {"command", "operation"}
        fields = {"create": {"request_key", "edit", "template", "template_parameters"}, "open": {"request_key", "project_ref"},
                  "check-in": {"request_key", "project_ref", "project_json", "session_id"}, "read": {"project_ref"},
                  "import-folder": {"request_key", "project_json", "files"},
                  "export-folder": {"request_key", "project_ref"},
                  "release": {"request_key", "project_ref", "session_id"}, "current-scope": set()}
        # A fresh transport correlation for an inert read does not create an
        # authoring request or mutation; old response files remain immutable.
        if operation in {"read", "current-scope"} and "request_key" in values:
            if not isinstance(values["request_key"], str) or not values["request_key"].strip():
                raise ValueError("read correlation key must be nonempty text")
            fields[operation].add("request_key")
        if operation == "check-in" and "document_changes" in values:
            fields["check-in"].add("document_changes")
        if operation not in fields or set(values) != common | fields[operation]:
            raise ValueError("project authoring requires exactly the fields for its selected operation")
        from .intake import OttoPortfolio
        portfolio = OttoPortfolio(self.server.owner.consumer_operations())
        options = {"actor": actor.actor, "request_id": values.get("request_key")}
        if operation == "current-scope":
            return {"outcome": "read", **self.server.owner.authoring.read_current_actor(actor), "provider_called": False}
        if operation == "release":
            return portfolio.release_project(values["project_ref"], session_id=values["session_id"], **options)
        if operation == "import-folder":
            return portfolio.import_folder(**options, project_json=values["project_json"], files=values["files"])
        if operation == "export-folder":
            return portfolio.export_folder(values["project_ref"], **options)
        if operation == "create":
            return portfolio.create_pending(**options, edit=values["edit"],
                template=values.get("template"), template_parameters=values.get("template_parameters"),
                open_project=False, orchestrated=False)
        if operation == "open":
            return portfolio.checkout_project(values["project_ref"], **options)
        if operation == "check-in":
            return portfolio.check_in_project(values["project_ref"], session_id=values["session_id"],
                project_json=values["project_json"], document_changes=values.get("document_changes"), **options)
        # Owner authentication issues an exact finite read grant for this
        # sibling. No persisted project roster or second writer is introduced.
        from .herzchen_binding import ProjectReadGrant
        ref = ResourceRef.from_dict(values["project_ref"])
        operations = self.server.owner.consumer_operations()
        grant = ProjectReadGrant(actor, (ref.id,), "host-owner-authoring", "v1")
        from .herzchen_binding import FiniteWorkOperations
        scoped = FiniteWorkOperations(port=operations.port, reader=self.server.owner.graph.reader,
            binding=self.server.owner.binding, project_read_grant=grant)
        return OttoPortfolio(scoped).read_pending(ref, actor=actor.actor)

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
        if self.host is None or (self.host._closing and not getattr(self.host, "bounded_transports", False)):
            return {**result, "continuation": {"outcome": "held", "provider_called": False,
                    "reason": "owner host must retain help continuation after restart", "retry": False}}
        current_id = (state.get("manager_continuation") or {}).get("schedule_id") or state["schedule_id"]
        if command == "resolve-help" and self._receiving_manager_application(current_id):
            # The current turn receives the canonical application below. A new
            # turn merely confirming its own application adds no decision.
            # Task settlement remains separate: a pending finish still wakes
            # the manager after native custody has actually settled.
            return {**result, "continuation": {"outcome": "observed-current-manager",
                "schedule_id": current_id, "report_ref": result["report_ref"],
                "provider_called": False, "retry": False, "continuation_required": False,
                "next_action": "Continue useful work in this admitted turn; the committed application is returned here."}}
        retained = self.host.submit({"command": "manager-help-result", "principal": state["manager"],
            "generation": state["manager_generation"], "schedule_id": current_id, "report_ref": result["report_ref"]})
        return {**result, "continuation": retained}

    def _receiving_manager_application(self, schedule_id: str) -> bool:
        """Require the exact live admitted manager before omitting a self-wake."""
        if self.host is None or self.host._closing or not self.host._external_waiting:
            return False
        state = self.server.state
        due = self.server.due_port.read_due(schedule_id)
        if not isinstance(due, Mapping):
            return False
        target = due.get("target") or {}
        attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
        admission, authorization = attempt.get("delivery_admission") or {}, attempt.get("delivery_authorization") or {}
        native = (state.get("manager_continuation") or {}).get("native_session_id")
        return (due.get("role") == "manager" and due.get("recipient") == state["manager"]
            and due.get("assignment_ref") == state["assignment_ref"]
            and due.get("generation") == state["manager_generation"]
            and due.get("project_ref") == state["project_ref"]["id"]
            and all((target.get("project_ref") or {}).get(key) == state["project_ref"].get(key)
                    for key in ("authority", "kind", "id"))
            and due.get("lifecycle_owner") == state["owner"] and due.get("manager_ref") == state["owner"]
            and due.get("stop_state") == "active" and due.get("completion_state") == "none"
            and bool(due.get("in_flight_request")) and not attempt.get("result")
            and isinstance(native, str) and bool(native) and target.get("native_id") == native
            and admission.get("native_turn_started") is True and admission.get("physical_session_id") == native
            and authorization.get("status") == "authorized" and authorization.get("physical_session_id") == native
            and authorization.get("assignment_ref") == due["assignment_ref"]
            and authorization.get("generation") == due["generation"]
            and authorization.get("project_ref") == target.get("project_ref")
            and authorization.get("task_ref") == target.get("task_ref")
            and authorization.get("role") == "manager" and authorization.get("principal") == state["manager"])

    def _settle_shared_completion(self, result: Mapping[str, Any], *, review_task: str | None = None,
                                  refresh: bool = True) -> Mapping[str, Any]:
        """Apply common settled-completion bookkeeping without changing entrance semantics.

        Native manager continuations and retained worker results share the
        accepted-finish settlement and current-ref refresh.  Only the worker
        entrance asks for review input, and its manager notification remains
        conditional on actual pending completion intents.
        """
        if result.get("outcome") not in {"succeeded", "replayed"}:
            return result
        settled = {**result, "completion_intents": self.commands.settle_completion_intents()}
        if refresh:
            self._refresh_refs()
        if review_task is not None:
            settled = {**settled, "review_input": self.commands.review_input(review_task)}
        return settled

    def _with_task_settlement_notification(self, result: Mapping[str, Any], app: Any) -> Mapping[str, Any]:
        """Append the existing same-manager destination to a settled result."""
        return {**result, "task_settlement_notification": self._retain_task_settlement(app)}

    def _finalize_manager_completion(self, result: Mapping[str, Any], *, app: Any) -> Mapping[str, Any]:
        """Finalize a manager continuation, retaining its existing wake semantics."""
        settled = self._settle_shared_completion(result)
        if settled.get("outcome") in {"succeeded", "replayed"}:
            # Manager continuations preserve their existing same-manager
            # continuation even when no accepted task finish is pending.
            return self._with_task_settlement_notification(settled, app)
        return settled

    def _retain_task_settlement(self, app: Any) -> Mapping[str, Any]:
        if self.host._closing and not getattr(self.host, "bounded_transports", False):
            return {"outcome": "held", "provider_called": False,
                    "reason": "owner is draining; preserve completion intents for same-manager closeout after restart"}
        state = self.server.state
        anchor = self._current_manager_schedule()
        prepared = app.continue_manager_after_tasks(manager_schedule_id=anchor, execute=False)
        if prepared.get("outcome") not in {"committed", "prepared"}:
            return prepared
        due = app._read(prepared["schedule_id"])
        if not advance_manager_head(state, expected=anchor, due=due, settled_anchor=anchor):
            return {**prepared, "outcome": "held", "reason": "manager head advanced after preparation",
                    "provider_called": False, "effects_started": False, "retry": False}
        state.update(schedule_id=due.schedule_id, logical_request_key=due.in_flight_request,
            manager_start_instruction=due.instruction)
        self.server._save_state()
        try:
            return self.host.submit({"command": "manager-task-settlement", "principal": state["manager"],
                                     "schedule_id": due.schedule_id})
        except RuntimeError as exc:
            # Preparation may outlive the initial drain check. The durable
            # callback and committed task remain valid; only admission failed.
            if (not self.host._closing or
                    str(exc) != "execution host is draining; no new worker may be admitted"):
                raise
            return {"outcome": "held", "provider_called": False,
                    "schedule_id": due.schedule_id, "callback_prepared": True,
                    "reason": "owner began draining after callback preparation; resume this exact callback after restart"}

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

    def _submit_worker(self, request: Mapping[str, Any], *, external_parent: Mapping[str, Any] | None = None,
                       resource_assignment_ref: Mapping[str, Any] | None = None, read_only: bool = False) -> Mapping[str, Any]:
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
        focus = request.get("focus")
        if not isinstance(focus, str) or not focus.strip() or len(focus) > 4000:
            # This validation precedes canonical lookup/preparation/allowance
            # effects. Classify this exact boundary, not arbitrary exceptions.
            return {"outcome": "rejected", "error": {"code": "worker_focus_length", "kind": "input",
                "message": "worker focus must describe 1..4000 characters of current intent"},
                "provider_called": False, "effects_started": False, "retry": False,
                "next_action": "Correct a new bounded intent with a distinct stable key. Pin the exact owned scope-manifest path and SHA instead of embedding a long file list; preserve this rejected receipt."}
        from .run_config import read_run_config
        try:
            config = read_run_config(self.run_path)
        except (ValueError, OSError) as exc:
            # This exact read is before lookup/preparation/allowance effects.
            # An arbitrary later exception must retain UNKNOWN semantics.
            return {"outcome": "rejected", "error": {"code": "run_config_declaration",
                "kind": "configuration", "message": str(exc)},
                "provider_called": False, "effects_started": False, "retry": False,
                "next_action": "Owner must reconcile the single adopted run declaration, preserving both original files and configuration semantics; then recover the identical request/key."}
        from .worker_occurrences import parent_for_caller, check_allowance
        from .occurrence_reads import lookup, handle, digest
        caller = _CALLER.get()
        manager_schedule = None
        if isinstance(caller, Mapping) and caller.get("role") == "manager":
            # Native identity uses the canonical occurrence_ref shape. Validate
            # it before any worker assignment so malformed context cannot leave
            # a prepared child without its exact result destination.
            manager_schedule = (caller.get("occurrence_ref") or {}).get("schedule_id")
            if not isinstance(manager_schedule, str) or not manager_schedule:
                raise PermissionError("manager caller has no exact authenticated occurrence")
        parent = parent_for_caller(self, caller) if caller and caller.get("role") == "worker" else None
        scope = {"project_ref": state["project_ref"], "task_ref": state["task_refs"][task], "parent": parent}
        historical = lookup(self.server.due_port, scope=scope, request_key=key, request_input=dict(request))
        if historical["outcome"] == "conflict":
            raise ValueError("project-wide worker key collides with changed intent or parent")
        if historical["outcome"] == "found":
            retained_due = self.server.due_port.read_due(historical["occurrence"]["schedule_id"])
            if (retained_due["target"].get("launch_request") or {}).get("external_parent") != external_parent:
                raise PermissionError("worker key belongs to another external responsibility")
            outcome = "replayed" if (retained_due["stop_state"] == "completed"
                and retained_due["completion_state"] == "succeeded") else "retained"
            return {**historical, "outcome": outcome, "retry_provider": False,
                    "next_action": "read the same occurrence; use explicit Recovery for incomplete stages"}
        if parent is not None:
            check_allowance(self)
        configured = config["roles"]["worker_" + route]
        selection = None
        if getattr(self, "adapter_selection", None) is not None:
            selection = self.adapter_selection.resolve(role=configured, defaults=config.get("defaults"), profile="workspace-write")
            model, reasoning = selection["model"], selection["reasoning"]
        else:
            if "adapter" in configured or "adapter" in config.get("defaults", {}):
                raise ValueError("named adapter selection requires the finite host composition; no fallback")
            model, reasoning = configured["model"], configured["reasoning"]
        if (not isinstance(model, str) or not model or any(char.isspace() for char in model)
                or reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}):
            raise ValueError("worker route model/reasoning configuration is invalid")
        previous = None if parent is not None else (state.get("workers") or {}).get(task)
        if isinstance(previous, Mapping):
            previous_app = self._execution(principal=previous["principal"], model=previous["model"],
                reasoning=previous["reasoning"], evidence_id=previous["schedule_id"],
                selection=((self.server.due_port.read_due(previous["schedule_id"]) or {}).get("target", {}).get("launch_request") or {}).get("selection"))
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
            evidence_id="worker-" + hashlib.sha256(key.encode()).hexdigest()[:20], selection=selection)
        instruction, contract, brief = compose_worker_operation(config=config, task=task, task_ref=task_ref,
            principal=principal, model=model, reasoning=reasoning, focus=focus,
            workspace=self.workspace, run_path=self.run_path, adapter=app.runtime.adapter, leaf=parent is not None or read_only)
        if read_only:
            contract["read_scope"] = "linked_context"
            contract["allowed_operations"] = ["read_project_context", "inspect_recorded_effect", "return_result"]
            contract["authority"].pop("effect_profile", None)
            contract["authority"].pop("workspace_roots", None)
            contract["authority"]["permitted_effects"] = ["read_delivered_context", "read_linked_sources", "return_result"]
            contract["authority"]["forbidden_effects"] += ["file_write", "dispatch", "review", "acceptance"]
            contract["bounded_operation"] = focus
            contract["objective"] = focus
            contract["acceptance_criteria"] = ["Return factual installed command and instruction evidence without verdicts or effects"]
            instruction = focus
            brief["mandate"] = "Inspect the delivered and linked installed instructions; return factual evidence only. Do not write files, dispatch, review, accept or spawn providers."
        coordinator_policy = None
        if contract.get("delegation") is not None:
            coordinator_policy = state.get("coordinator_launch_policy")
            required = {"task", "principal", "route", "model", "reasoning", "native_adapter", "capacity_units", "max_depth", "cumulative_allowance_units", "allocation_report_ref", "root_assignment_ref", "root_generation", "project_ref", "task_ref", "role_configuration_ref"}
            if (not isinstance(coordinator_policy, Mapping) or set(coordinator_policy) != required
                    or coordinator_policy["task"] != task or coordinator_policy["principal"] != principal
                    or coordinator_policy["root_assignment_ref"] != state["orchestrator_assignment_ref"]
                    or coordinator_policy["project_ref"] != state["project_ref"] or coordinator_policy["task_ref"] != task_ref
                    or coordinator_policy["role_configuration_ref"] != state.get("worker_role_configuration_ref")
                    or coordinator_policy["root_generation"] != 1
                    or coordinator_policy["route"] != route or coordinator_policy["model"] != model
                    or coordinator_policy["reasoning"] != reasoning or coordinator_policy["native_adapter"] != app.native_adapter_identity()
                    or coordinator_policy["capacity_units"] != 1 or coordinator_policy["max_depth"] != 1
                    or type(coordinator_policy["cumulative_allowance_units"]) is not int):
                raise PermissionError("coordinating operation needs its exact owner-issued finite policy")
            allocation = self.server.owner.graph.reader.get_identity(ResourceRef.from_dict(coordinator_policy["allocation_report_ref"]))
            expected = {k:v for k,v in coordinator_policy.items() if k != "allocation_report_ref"}
            if (allocation.payload["value"].get("schema") != "otto.owner-coordinator-launch-policy.v1"
                    or allocation.payload["value"].get("policy") != expected
                    or allocation.payload["assignment"] != state["orchestrator_assignment_ref"]
                    or allocation.payload["generation"] != coordinator_policy["root_generation"]
                    or not any(e.operation == "work.report.append" and e.actor == self.server.owner.owner_actor
                        for e in self.server.owner.graph.reader.list_events(subjects=(allocation.ref,)))):
                raise PermissionError("coordinating policy has no authentic current root allocation")
            from .worker_occurrences import worker_records
            if len(worker_records(self)) + 3 > coordinator_policy["cumulative_allowance_units"]:
                raise PermissionError("coordinator, finite child and return lack their configured remaining turns")
        from .resource_sync import resolve_assignment_attachments
        from .role_context import supporting_context, selected_configuration
        manager = self.server.owner.assignments.command_port.get(ResourceRef.from_dict(resource_assignment_ref or state["assignment_ref"]))
        attachments = resolve_assignment_attachments({"ref": manager.ref.to_dict(), "role": manager.role,
            "generation": manager.generation, "payload": manager.payload},
            self.server.owner.content.command_port, role=manager.role)
        bases = [item for item in attachments if item["required"]]
        if len(bases) != 1:
            raise ValueError("worker delegation requires exactly one current adopted manager BASE")
        from .direction_context import direction_inputs
        reader = getattr(self.server.portfolio.operations, "direction_context_reader", None)
        directions = [] if reader is None else reader(assignment_ref=manager.ref.to_dict(), generation=manager.generation,
            project_ref=state["project_ref"], task_ref=task_ref)
        sources = supporting_context(bases[0], self.server.owner.content.command_port,
            exact_direction_inputs=direction_inputs(directions))
        # A child consumes overall/project/task direction plus its own durable
        # responsibility, never the parent's responsibility-specific primary.
        parent_inputs = {tuple(scope["effective_ref"][key] for key in ("authority", "kind", "id"))
            for scope in directions if scope["kind"] == "responsibility"}
        shared_inputs = {tuple(item["ref"][key] for key in ("authority", "kind", "id"))
            for scope in directions if scope["kind"] != "responsibility" for item in scope["inputs"]}
        sources = [source for source in sources if
            tuple(source["ref"][key] for key in ("authority", "kind", "id")) not in parent_inputs - shared_inputs]
        role_configuration = state.get("worker_role_configuration_ref")
        if role_configuration is not None and not any(source["ref"] == role_configuration for source in sources):
            sources += supporting_context({"resource_ref": bases[0]["resource_ref"],
                "content": {"supporting_refs": [role_configuration]}}, self.server.owner.content.command_port)
        # Reject incompatible selections before creating any worker assignment.
        selected_configuration(sources)
        if selection is None:
            selection = {"identity": app.native_adapter_identity(), "adapter": "existing-owner-composition",
                         "model": model, "reasoning": reasoning,
                         "provenance": {"model": "project_role", "reasoning": "project_role", "adapter": "host_composition"},
                         "pins": {"supporting_resources": [{"ref": source["ref"], "sha256": source["content_sha256"]} for source in sources]}}
        launch_request = {"scope": scope, "input": dict(request), "selection": selection,
                          "fingerprint": digest([scope, dict(request), selection])}
        if external_parent is not None:
            launch_request["external_parent"] = json_value(external_parent)
            launch_request["fingerprint"] = digest([scope, dict(request), selection, external_parent])
        validate_host = getattr(app.runtime.adapter, "validate_owner_host_composition", None)
        if callable(validate_host):
            validate_host(role="worker", profile="read-only" if read_only else "workspace-write")
        prepared = app.assign_worker(project_ref=state["project_ref"], task_ref=task_ref,
            principal=principal, request_key=key, instructions=instruction, instruction_contract=contract,
            brief=brief, model=model, reasoning=reasoning, profile="read-only" if read_only else "workspace-write", timeout_seconds=1200,
            supporting_refs=[source["ref"] for source in sources], parent=parent, launch_request=launch_request)
        if prepared.get("outcome") not in {"committed", "prepared"}:
            previous = (state.get("workers") or {}).get(task) or {}
            return {**prepared, **{name: previous[name] for name in ("retained_handle", "response_path")
                                  if name in previous and previous.get("schedule_id") == prepared.get("schedule_id")},
                    "retry_provider": False}
        if parent is not None:
            retained = self.host.submit({"command": "start-retained-child", "schedule_id": prepared["schedule_id"]})
            due = app._read(prepared["schedule_id"])
            self.server.due_port.save_due(due.schedule_id, {**due.to_dict(), "host_evidence": {
                **(due.host_evidence or {}), "launch_handles": {"outer_command": (self.host.command_handle() if callable(getattr(self.host, "command_handle", None)) else None), "start": retained.get("retained_handle"), "callback": None}}},
                request_id=key + ":launch-handles", expected_version=due.version)
            return {**prepared, **retained, "outcome": "prepared", "occurrence": handle(app._read(due.schedule_id).to_dict()),
                    "selection": selection, "start": retained.get("retained_handle"), "callback": None,
                    "next_action": "yield this exact parent turn; the retained child starts only after verified settlement and native release"}
        if isinstance(previous, Mapping) and previous.get("schedule_id") != prepared["schedule_id"]:
            history = state.setdefault("worker_history", {}).setdefault(task, [])
            if not any(item.get("schedule_id") == previous["schedule_id"] for item in history):
                history.append(dict(previous))
        state.setdefault("workers", {})[task] = {**prepared, "principal": principal,
                                                 "model": model, "reasoning": reasoning,
                                                 "request_key": key, "submission": dict(request)}
        caller = _CALLER.get()
        if isinstance(caller, Mapping) and caller.get("role") == "manager":
            # The authenticated occurrence, never request JSON or old settled
            # state, selects the manager whose preparation admitted this child.
            state["workers"][task]["manager_schedule_id"] = manager_schedule
        if coordinator_policy is not None:
            self.delegation_policy = {"coordinators": [{"assignment_ref": prepared["assignment_ref"], "generation": prepared["generation"], "native_adapter": app.native_adapter_identity()}],
                "max_depth": 1, "capacity_units": 1, "cumulative_allowance_units": coordinator_policy["cumulative_allowance_units"]}
            state["delegation_policy"] = self.delegation_policy
        self.server._save_state()
        retained = self.host.submit({"command": "start-retained-worker", "task": task,
            "principal": principal, "schedule_id": prepared["schedule_id"]})
        state["workers"][task].update(retained)
        due = app._read(prepared["schedule_id"])
        self.server.due_port.save_due(due.schedule_id, {**due.to_dict(), "host_evidence": {
            **(due.host_evidence or {}), "launch_handles": {"outer_command": (self.host.command_handle() if callable(getattr(self.host, "command_handle", None)) else None), "start": retained.get("retained_handle"), "callback": None}}},
            request_id=key + ":launch-handles", expected_version=due.version)
        self.server._save_state()
        return {**prepared, **retained, "assignment_ref": prepared["assignment_ref"],
                "generation": prepared["generation"], "principal": principal, "task": task,
                "occurrence": handle(app._read(prepared["schedule_id"]).to_dict()),
                "start": retained.get("retained_handle"), "callback": None, "selection": selection}


def install_manager_journey_service(server: Any, *, run_path: str | Path, workspace: str | Path,
                                    policy: Any = None, orchestrator_principal: str | None = None,
                                    observe_schedules: Any = None,
                                    help_reply_authorizer: Any = None, authoring_authorizer: Any = None,
                                    adapter_selection: Any = None, delegation_policy: Mapping[str, Any] | None = None,
                                    external_execution_authorizer: Any = None, external_execution_policy: Mapping[str, Any] | None = None) -> ManagerJourneyService:
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

    authoring_authorizer is a separate optional host-owned caller boundary.
    It must authenticate the service owner's caller independently of JSON
    fields and return the bound owner actor. Omitting it disables sibling
    project authoring. This installs finite authoring in the same owner lane;
    it never admits a provider invocation or changes manager custody.
    """
    host = server.execution_host
    service = ManagerJourneyService(server=server, host=host, run_path=run_path,
        workspace=workspace, policy=policy, orchestrator_principal=orchestrator_principal,
        observe_schedules=observe_schedules, help_reply_authorizer=help_reply_authorizer,
        authoring_authorizer=authoring_authorizer, adapter_selection=adapter_selection,
        delegation_policy=delegation_policy, external_execution_authorizer=external_execution_authorizer,
        external_execution_policy=external_execution_policy)
    server._execution = service._execution
    host.handler = service
    return service
