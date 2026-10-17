"""The manager journey of one activated project, inside the one owner service.

This generalizes, inside git, the composition a Codex run kept in an
out-of-git ``controller/operating_service.py``: an ``ExecutionHost`` serves
the project's manager command port and the maintained ``ManagerJourneyService``
handles its commands. ``otto.hostctl.service.OwnerService`` attaches it; it
shares the service's single command lock, so every Store write in the
process is serialized. Per project (``<home>/projects/<id>/``):

* ``manager-ipc/`` (0700): the manager's file lane, the one directory the
  manager's write fence admits. Commands that claim no caller identity
  (report, status, request-help, resolve-help, ...) travel here, served by
  the owner even during the manager's own turn. Owner custody requests that
  the orchestrator sends through its host lane are relayed here too.
* the native caller socket (``<home>/run/c-<hash>.sock``): identity-bearing
  commands (whoami, run-worker, project-documents, ...) from processes this
  owner launched, authenticated by kernel peer-PID ancestry.
* ``owner-grants/`` (0700, outside every launched role's fence): one grant per
  orchestrator reply the service forwarded. ``respond-help`` is accepted only
  with its grant, so the manager, which can write its lane, cannot answer
  its own escalation.

Attaching starts no Due and calls no provider. Only an explicit
``start-manager`` launches the prepared manager occurrence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from herzchen.contracts import ResourceRef, canonical_json

from .lanes import atomic_json, private_dir, read_private_json
from .owner import HostSession

STATE_SCHEMA = "otto.host-service-state.v1"
GRANT_SCHEMA = "otto.owner-reply-grant.v1"
# Finite reads a launched manager makes over the caller socket during its turn.
HOST_SOCKET_READS = frozenset({"project-documents"})


def socket_path(config: Mapping[str, Any], project_id: str) -> Path:
    digest = hashlib.sha256(project_id.encode()).hexdigest()[:12]
    path = Path(config["home"]) / "run" / ("c-" + digest + ".sock")
    if len(os.fsencode(path)) > 103:
        raise ValueError("the caller socket address exceeds the 103-byte Unix limit; use a shorter OTTO_HOME")
    return path


def project_runtime(config: Mapping[str, Any], project_id: str) -> dict[str, Path]:
    base = Path(config["home"]) / "projects" / project_id
    return {"base": base, "ipc": base / "manager-ipc", "grants": base / "owner-grants",
            "owner": base / "service-owner.json", "state": base / "service-state.json",
            "run_view": base / "run", "socket": socket_path(config, project_id)}


def _registration(config: Mapping[str, Any], run_id: str) -> Mapping[str, Any]:
    """The activation receipt: the roles, pools and checks materialized at activation."""
    from .cli import receipt_path
    path = receipt_path(Path(config["home"]), "activate-" + run_id)
    if not path.exists():
        raise LookupError("project " + run_id + " is not activated; run `ottoctl project activate` first")
    return json.loads(path.read_text())


def request_digest(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(request)).encode()).hexdigest()


class HostOwnerService:
    """The ``server`` object ManagerJourneyService expects, for one project."""

    def __init__(self, session: HostSession, record: Any, *, command_lock: Any = None,
                 adapter_factory: Optional[Callable[..., Any]] = None,
                 turn_admission: Optional[Callable[[], Any]] = None,
                 execution_host: Any = None,
                 worker_mcp_provider: Optional[Callable[[Mapping[str, Any]], Any]] = None,
                 worker_lab_provider: Optional[Callable[[Any, Any], Mapping[str, Any]]] = None,
                 worker_context_provider: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None) -> None:
        """``execution_host`` is the ONE shared host of a ProjectServices composition.

        Then this view owns no host, lane or socket of its own: it serves from
        the shared host's directory and socket, and the router (not this view)
        installs the host's handler and its native-caller ingress.
        """
        from otto.portfolio.execution_host import ExecutionHost
        from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress, managed_caller_binding
        self.session, self.config = session, session.config
        self.owner, self.due_port, self.binding, self.store = (session.owner, session.due_port,
                                                               session.binding, session.store)
        self.native_bodies = session.native_bodies
        self.home = Path(self.config["home"])
        registration = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
        self.run_id = registration.get("run_id") or record.ref.id
        self.paths = project_runtime(self.config, record.ref.id)
        shared = execution_host is not None
        if shared:
            self.paths.update(ipc=execution_host.directory, socket=execution_host.socket_path)
        for key in ("base", "grants") if shared else ("base", "ipc", "grants"):
            private_dir(self.paths[key])
        self.state_path = self.paths["state"]
        self.state = self._load_state(record, registration)
        # Escalations route to the project's accountable supervisor (the host
        # orchestrator, via its portfolio enrollment) and are retained for
        # receipt inspection; the orchestrator answers through its host lane.
        from otto.portfolio.help_delivery import BoundHelpDelivery
        from otto.portfolio.owner_issue_loop import OwnerIssueReaders
        self.help_delivery = BoundHelpDelivery(readers=OwnerIssueReaders(self.owner.consumer_operations(),
                                                                         self.due_port))
        self.portfolio = self.owner.portfolio(due_port=self.due_port, issue_delivery=self.help_delivery)
        # The run document is the owner's maintained policy source. Hydrate it
        # after help_delivery exists because _documents uses the accountable
        # project supervisor to read those canonical records.
        self._hydrate_assessment_policy(record)
        self._default_adapter_factory = adapter_factory is None
        self.adapter_factory = adapter_factory or self._host_adapter
        self.worker_mcp_provider = worker_mcp_provider
        self.worker_lab_provider = worker_lab_provider
        self.worker_context_provider = worker_context_provider
        self.turn_admission = turn_admission
        if shared:
            # The composition assigns the router's ingress once the router exists.
            self.native_callers, self.execution_host = None, execution_host
            return
        self.native_callers = NativeProcessCallerIngress(lambda authorization: managed_caller_binding(self, authorization))
        self.execution_host = ExecutionHost(directory=self.paths["ipc"], handler=self.handle,
            owner_path=self.paths["owner"], socket_path=self.paths["socket"],
            caller_binding_reader=self.native_callers, caller_context_resolver=self._caller_context,
            caller_authorizer=self._authorize_caller, owner_file_compatibility=True)
        self.execution_host.turn_admission = turn_admission
        if command_lock is not None:
            # One owner process, one custodian: lane operations and this
            # project's commands serialize on the same lock.
            self.execution_host._command_lock = command_lock
            self.execution_host.release_command_lock_during_wait = True

    # -- state ----------------------------------------------------------------
    def _load_state(self, record: Any, registration: Mapping[str, Any]) -> dict[str, Any]:
        """Retained service state, or a fresh projection of the owner records."""
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            if state.get("schema") != STATE_SCHEMA or state["project_ref"]["id"] != record.ref.id:
                raise RuntimeError("retained service state belongs to another project or schema")
            state["project_ref"] = self.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind,
                                                                   record.ref.id)).ref.to_dict()
            state.setdefault("run_id", self.run_id)
            state.setdefault("owner", self.owner.owner_actor.actor)
            return state
        receipt = _registration(self.config, self.run_id)["steps"]
        manager = receipt["manager"]
        assignment = self.owner.assignments.get(ResourceRef.from_dict(
            {k: manager["assignment_ref"][k] for k in ("authority", "kind", "id")}))
        task_refs = {}
        for raw in record.payload.get("tasks") or ():
            ref = ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
            task = self.owner.graph.current(ResourceRef(ref.authority, ref.kind, ref.id))
            task_refs[task.payload.get("alias") or task.ref.id] = task.ref.to_dict()
        binding = manager["binding"]
        return {"schema": STATE_SCHEMA, "authority": self.config["store"]["authority"], "run_id": self.run_id,
                "owner": self.owner.owner_actor.actor,
                "project_ref": record.ref.to_dict(), "task_refs": task_refs, "criterion_refs": {},
                "manager": manager["principal"], "assignment_ref": assignment.ref.to_dict(),
                "manager_generation": assignment.generation, "requested_model": binding["model"],
                "requested_reasoning": binding["reasoning"], "requested_profile": "workspace-write",
                "schedule_id": None, "workers": {},
                "advisor_policy": {"mode": "disabled", "reason": "The orchestrator's scheduled checks supervise"},
                "orchestrator_assignment_ref": (receipt.get("orchestrator") or {}).get("assignment_ref"),
                "external_execution_tool_entrypoint": None,
                "mandate_ref": manager["mandate_ref"], "source_bundle": registration.get("source_bundle")}

    def _save_state(self) -> None:
        atomic_json(self.state_path, self.state)

    def _canonical_assessment_policy(self, project_ref: ResourceRef) -> Optional[dict[str, Any]]:
        """Read the sole canonical run document's owner-declared policy."""
        run_documents = [row for row in self._documents(project_ref)
                         if row.get("path") in {"run.json", "run.yaml"}]
        if len(run_documents) > 1:
            raise RuntimeError("project has ambiguous run policy documents")
        if not run_documents:
            return None
        raw_run = run_documents[0]["text"]
        try:
            run = dict(raw_run) if isinstance(raw_run, Mapping) else json.loads(raw_run)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("canonical project run document is invalid JSON") from exc
        if not isinstance(run, Mapping):
            raise RuntimeError("canonical project run document must be an object")
        configured = run.get("assessment_accounting")
        if configured is None:
            return None
        if not isinstance(configured, Mapping):
            raise RuntimeError("canonical project assessment_accounting must be an object")
        return dict(configured)

    def assert_assessment_policy_current(self) -> None:
        """Refuse assessment if the canonical run policy changed after hydration.

        This check is read-only. It reads the current project document through
        the owner document reader and compares the declaration exactly with
        the policy already hydrated into trusted service state.
        """
        project_ref = ResourceRef.from_dict(self.state["project_ref"])
        current = self.owner.graph.reader.get_identity(
            ResourceRef(project_ref.authority, project_ref.kind, project_ref.id))
        if (current is None or (current.ref.authority, current.ref.kind, current.ref.id) !=
                (project_ref.authority, project_ref.kind, project_ref.id)):
            raise RuntimeError("assessment policy project is unavailable")
        configured = self._canonical_assessment_policy(current.ref)
        hydrated = self.state.get("assessment_policy")
        if not isinstance(hydrated, Mapping) or configured is None or dict(hydrated) != configured:
            raise RuntimeError("canonical project assessment policy changed after owner view hydration")

    def _hydrate_assessment_policy(self, record: Any) -> None:
        """Project the canonical run policy and owner-record criterion aliases.

        Alias names in assessment_accounting are only labels. Resolve them
        from current assessment scopes over this exact project or its linked
        tasks, using the criterion's source_alias or its exact record ID.
        Retained owner bindings may preserve current criterion refs across a
        completed task's revision change. Task acceptance prose is never a
        criterion source.
        """
        from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy

        project_ref = ResourceRef.from_dict(self.state["project_ref"])
        configured = self._canonical_assessment_policy(project_ref)
        if configured is None:
            self.state.pop("assessment_policy", None)
            self.state["criterion_refs"] = {}
            return

        from herzchen.domains.assessment import AssessmentModule
        from otto.portfolio.assessment import OttoAssessment

        pairs = configured.get("task_criterion_pairs")
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 256:
            raise RuntimeError("canonical project assessment policy exceeds the bounded task/criterion scope")
        requested_tasks: set[str] = set()
        configured_aliases: set[str] = set()
        for pair in pairs:
            if isinstance(pair, str) and pair.count("/") == 1:
                task_alias, criterion_alias = pair.split("/")
            elif isinstance(pair, Mapping) and set(pair) == {"task", "criterion"}:
                task_alias, criterion_alias = pair["task"], pair["criterion"]
            else:
                raise RuntimeError("canonical project assessment policy has an invalid task/criterion pair")
            if not all(isinstance(value, str) and value.strip() for value in (task_alias, criterion_alias)):
                raise RuntimeError("canonical project assessment policy has an empty task/criterion alias")
            requested_tasks.add(task_alias)
            configured_aliases.add(criterion_alias)

        current_project = self.owner.graph.reader.get_identity(
            ResourceRef(project_ref.authority, project_ref.kind, project_ref.id))
        if current_project is None or current_project.ref != project_ref:
            raise RuntimeError("assessment policy project pin is not the exact current project")
        linked_tasks: dict[str, dict[str, Any]] = {}
        if len(record.payload.get("tasks") or ()) > 4096:
            raise RuntimeError("project task links exceed the owner view bound")
        for raw in (record.payload.get("tasks") or ()):
            ref = ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
            current = self.owner.graph.reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
            if current is None:
                raise RuntimeError("project assessment task is no longer current")
            alias = current.payload.get("alias") or current.ref.id
            linked_tasks[alias] = current.ref.to_dict()
        prior_tasks = self.state.get("task_refs") or {}
        if linked_tasks:
            if set(linked_tasks) != set(prior_tasks):
                raise RuntimeError("assessment task aliases differ from the current project task links")
            for alias, current_ref in linked_tasks.items():
                prior_ref = ResourceRef.from_dict(prior_tasks[alias])
                if prior_ref.id != current_ref["id"]:
                    raise RuntimeError("assessment task alias was remapped to another owner record")
            # A retained view can outlive task revisions; refresh exact pins
            # from the current project links before resolving policy aliases.
            self.state["task_refs"] = linked_tasks

        actor = self.owner.binding.authenticated_actor(self.state["manager"])
        assessed = OttoAssessment(AssessmentModule(self.store, actor=actor,
            payload_resolver=self.owner.evidence_payload_resolver), actor)
        missing_tasks = requested_tasks - set(self.state["task_refs"])
        if missing_tasks:
            raise RuntimeError("assessment policy names a task outside the exact current project")
        parents = [project_ref]
        parents.extend(ResourceRef.from_dict(self.state["task_refs"][alias])
                       for alias in sorted(requested_tasks))
        aliases: dict[str, dict[str, Any]] = {}
        registered_aliases: set[str] = set()
        scoped_criteria: dict[tuple[str, str, str], ResourceRef] = {}
        for parent in parents:
            coverage = assessed.coverage(parent)
            scope_rows = coverage.get("scopes", ())
            if not isinstance(scope_rows, (list, tuple)) or len(scope_rows) > 256:
                raise RuntimeError("assessment scopes exceed the bounded owner view")
            for scope_row in scope_rows:
                scope = assessed.get_scope(scope_row["ref"])
                if (scope.parent_obligation_ref.authority, scope.parent_obligation_ref.kind,
                        scope.parent_obligation_ref.id) != (parent.authority, parent.kind, parent.id):
                    continue
                for ref in scope.criterion_refs:
                    if len(scoped_criteria) >= 256 and (ref.authority, ref.kind, ref.id) not in scoped_criteria:
                        raise RuntimeError("assessment criteria exceed the bounded owner view")
                    current = self.owner.graph.reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
                    if current is None or current.ref != ref:
                        raise RuntimeError("assessment scope contains a stale criterion")
                    scoped_criteria[(ref.authority, ref.kind, ref.id)] = ref
                    definition = current.payload.get("definition") or {}
                    alias = definition.get("source_alias") if isinstance(definition, Mapping) else None
                    # Reviewed activation may create owner criteria without a
                    # source_alias. Their canonical record id is usable only
                    # when the owner run document names that exact id.
                    if not isinstance(alias, str) or not alias.strip():
                        alias = ref.id if ref.id in configured_aliases else None
                    if alias is None:
                        continue
                    if alias in aliases and aliases[alias] != ref.to_dict():
                        # A task may already have an owner-declared criterion
                        # using the readable run alias. Activation creates its
                        # own uniquely identified criterion from the stored
                        # proof and marks its alias on the criterion record;
                        # that registered-run binding is authoritative for
                        # this canonical run policy.
                        registered_run_scope = (
                            getattr(scope, "protocol", None) == "otto-registered-run"
                            or (getattr(scope, "protocol", None) == "check-accepted"
                                and scope.policy.get("required_for_completion") is True
                                and scope.policy.get("acceptance_mode") == "check-accepted")
                        )
                        if registered_run_scope:
                            aliases[alias] = ref.to_dict()
                            registered_aliases.add(alias)
                        elif alias in registered_aliases:
                            continue
                        else:
                            raise RuntimeError("assessment criterion alias is ambiguous: " + alias)
                    else:
                        aliases[alias] = ref.to_dict()
                        if (getattr(scope, "protocol", None) == "otto-registered-run"
                                or (getattr(scope, "protocol", None) == "check-accepted"
                                    and scope.policy.get("required_for_completion") is True
                                    and scope.policy.get("acceptance_mode") == "check-accepted")):
                            registered_aliases.add(alias)

        # A retained alias may come from a prior canonical hydration for an
        # older criterion whose definition lacks source_alias. Preserve it
        # only when this run document still names the alias and its exact ref
        # remains current. This also survives a task revision after completion,
        # when the original scope remains pinned to the prior task revision.
        retained_criteria = self.state.get("criterion_refs") or {}
        if not isinstance(retained_criteria, Mapping):
            raise RuntimeError("retained assessment criterion aliases are malformed")
        for alias, raw_ref in retained_criteria.items():
            if alias not in configured_aliases:
                continue
            try:
                ref = ResourceRef.from_dict(raw_ref)
            except (TypeError, ValueError):
                continue
            identity = self.owner.graph.reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
            if identity is not None and identity.ref == ref:
                if alias in aliases and aliases[alias] != ref.to_dict():
                    raise RuntimeError("retained assessment criterion alias is ambiguous: " + str(alias))
                aliases[alias] = ref.to_dict()

        policy_state = {**self.state, "criterion_refs": aliases}
        try:
            policy = LocalAssessmentPolicy.from_run_config(configured, state=policy_state)
            for task_ref, _criterion_ref in policy.task_criterion_pairs:
                policy.validate_binding(project_ref, task_ref, self.owner.graph.reader)
        except Exception as exc:
            raise RuntimeError("canonical project assessment policy does not bind current owner records: " + str(exc)) from exc
        self.state["criterion_refs"] = aliases
        self.state["assessment_policy"] = dict(configured)

    # -- generated run view --------------------------------------------------------
    def render_run_view(self) -> Path:
        """Render a read-only-as-authority run view from Otto's records.

        The view holds each current project document (nested paths such as
        briefs/M1.md included) plus run.json, whose roles come from the
        adopted otto.role-configuration.v1 document. It is a generated view,
        never authoritative; editing it changes no owner record. The manager reads the canonical documents with
        ``ottoctl manager project-documents``.
        """
        project = ResourceRef.from_dict(self.state["project_ref"])
        view = private_dir(self.paths["run_view"])
        documents = {row["path"]: row["text"] for row in self._documents(project) if row["path"]}
        receipt = _registration(self.config, self.run_id)["steps"]
        configuration = self.owner.content.read(ResourceRef.from_dict(receipt["role_configuration"]))["content"]
        source = json.loads(documents.pop("run.json", None) or documents.pop("run.yaml", None) or "{}")
        source["roles"] = {slot: {"model": value["model"], "reasoning": value["reasoning"]}
                           for slot, value in configuration["roles"].items()}
        source["otto_generated_view"] = {"from": "otto records", "authority": "read-only projection",
                                         "role_configuration": receipt["role_configuration"],
                                         "note": "generated by the owner service; owner records are authoritative; edit through Otto"}
        for name, text in list(documents.items()) + [("run.json", json.dumps(source, indent=2, sort_keys=True) + "\n")]:
            parts = name.split("/")
            if not name or name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                continue
            target = view.joinpath(*parts)
            if len(parts) > 1:
                private_dir(target.parent)
            target.write_text(text if isinstance(text, str) else json.dumps(text, indent=2, sort_keys=True))
            os.chmod(target, 0o600)
        return view

    def _documents(self, project: ResourceRef) -> list[dict[str, Any]]:
        """The project's project.files documents, read as their maintainer.

        Registered documents are private to the host principal that authored
        them (Otto's folder rule), and that principal is the project's
        accountable supervisor. The owner discloses exactly these documents
        to the project's own bound manager; nothing outside project.files.
        """
        from herzchen.content import domain_contribution as content_contribution
        from herzchen.content.packets import ContextPacketService
        from otto.portfolio.documents import ProjectDocumentReader
        reader = ProjectDocumentReader(sheet_reader=self.owner.sheet, content_reader=self.owner.content,
            visibility_reader=ContextPacketService(self.store.domain_handler((content_contribution(),))))
        supervisor = self.help_delivery.readers.current_supervisor(project.to_dict())
        actor = self.binding.authenticated_actor(supervisor.principal) if supervisor else self.owner.owner_actor
        rows = []
        for row in reader.list_documents(project.to_dict(), actor=actor)["documents"]:
            path = next((m.get("key") for m in row.get("memberships") or () if m.get("namespace") == "project.files"), None)
            if path is None:
                continue
            content = self.owner.content.read(ResourceRef.from_dict(row["current_revision_ref"]))["content"]
            rows.append({"path": path, "role": (row.get("document") or {}).get("role"),
                         "revision_ref": row["current_revision_ref"], "text": content})
        return sorted(rows, key=lambda item: item["path"])

    # -- composition ------------------------------------------------------------
    def worktree(self) -> str:
        mandate = self.owner.content.read(ResourceRef.from_dict(self.state["mandate_ref"]))["content"]
        return mandate["instruction_contract"]["authority"]["workspace_roots"][0]

    def manager_launch(self) -> dict[str, Any]:
        """What a launched manager is given: its lane in the write fence, and where the lanes are."""
        return {"write_roots": (str(self.paths["ipc"]),),
                "env": {"OTTO_MANAGER_IPC": str(self.paths["ipc"]),
                        "OTTO_CALLER_SOCKET": str(self.paths["socket"]),
                        "OTTO_PROJECT": self.run_id}}

    def _claude_adapter(self, *, principal: str, model: str, reasoning: str, service: Any = None,
                        worker_mcp: Any = None, workspace: Optional[str] = None,
                        source: Optional[str] = None, roles: tuple = ("worker", "manager")) -> Any:
        from .adapters import compose_claude
        launch = self.manager_launch()
        manager_role = "manager" in roles
        return compose_claude(self.config, source=source or str(self.render_run_view()),
                              worktree=workspace or self.worktree(), model=model, reasoning=reasoning,
                              roles=roles, owner=principal,
                              native_caller_socket=str(self.paths["socket"]) if manager_role else None,
                              native_process_observer=self.native_callers.observe if manager_role else None,
                              manager_write_roots=launch["write_roots"] if manager_role else (),
                              manager_env=launch["env"] if manager_role else None,
                              worker_mcp=worker_mcp)

    def _host_adapter(self, *, principal: str, model: str, reasoning: str, service: Any = None,
                      worker_mcp: Any = None, workspace: Optional[str] = None,
                      source: Optional[str] = None, roles: tuple = ("worker", "manager")) -> Any:
        """Select only the adapter declared by this project's admitted host."""
        host = getattr(self.session, "host", None)
        kind = host.get("kind") if isinstance(host, Mapping) else None
        if kind not in ("claude-code", "codex") or (self.config.get("hosts") or {}).get(kind) != host:
            from .adapters import AdapterUnavailable
            raise AdapterUnavailable("project has no matching admitted host adapter")
        if kind == "claude-code":
            return self._claude_adapter(principal=principal, model=model, reasoning=reasoning,
                service=service, worker_mcp=worker_mcp, workspace=workspace, source=source, roles=roles)
        from .adapters import compose_codex
        manager_role = "manager" in roles
        launch = self.manager_launch() if manager_role else None
        return compose_codex(self.config, source=source or str(self.render_run_view()),
            worktree=workspace or self.worktree(), model=model, reasoning=reasoning,
            roles=roles, owner=principal,
            native_caller_socket=str(self.paths["socket"]) if manager_role else None,
            native_process_observer=self.native_callers.observe if manager_role else None,
            manager_write_roots=launch["write_roots"] if launch is not None else (),
            worker_mcp=worker_mcp)

    def _execution(self, *, principal: str, model: str, reasoning: str, evidence_id: str,
                   workspace: Optional[str] = None, **_: Any) -> Any:
        options = {"principal": principal, "model": model, "reasoning": reasoning, "service": self}
        due = None
        if self.worker_mcp_provider is not None:
            # evidence_id is an owner-internal schedule handle. Resolve the
            # exact Due first; principals and request fields cannot select a
            # worker grant. Manager/caller evidence ids do not produce grants.
            try:
                due = self.due_port.read_due(evidence_id)
            except (LookupError, KeyError):
                # The port's normal contract is None for an unknown schedule.
                # Some finite adapters signal that same condition by exception;
                # keep ordinary manager evidence labels working while letting
                # storage and validation failures propagate.
                due = None
            if (isinstance(due, Mapping) and due.get("schedule_id") == evidence_id
                    and due.get("role") == "worker"):
                assignment = due.get("assignment_ref")
                generation = due.get("generation")
                if (due.get("recipient") != principal
                        or not isinstance(assignment, Mapping) or not assignment.get("id")
                        or isinstance(generation, bool) or not isinstance(generation, int) or generation < 1):
                    raise PermissionError("worker Due does not bind this execution to its exact recipient and assignment")
                target = due.get("target")
                target_assignment = target.get("assignment_ref") if isinstance(target, Mapping) else None
                if target_assignment is not None and target_assignment != assignment:
                    raise PermissionError("worker Due target assignment differs from its exact binding")
                if self.worker_context_provider is None:
                    raise PermissionError("worker assignment has no owner lab resolver")
                context = self.worker_context_provider(due)
                assigned_workspace = context.get("workspace") if isinstance(context, Mapping) else None
                if not isinstance(assigned_workspace, str) or not assigned_workspace:
                    raise PermissionError("worker assignment has no owner lab workspace")
                if workspace is not None and os.path.realpath(workspace) != os.path.realpath(assigned_workspace):
                    raise PermissionError("worker workspace differs from its exact assignment lab")
                workspace = assigned_workspace
                worker_mcp = self.worker_mcp_provider(due)
                if worker_mcp is None:
                    raise PermissionError("worker assignment has no owner-issued worker_mcp grant")
                if self._default_adapter_factory:
                    options["worker_mcp"] = worker_mcp
                    options["roles"] = ("worker",)
                    options["source"] = assigned_workspace
                else:
                    import inspect
                    try:
                        accepts_grant = "worker_mcp" in inspect.signature(self.adapter_factory).parameters
                    except (TypeError, ValueError):
                        accepts_grant = False
                    if not accepts_grant:
                        raise TypeError("custom adapter_factory must explicitly accept worker_mcp for worker execution")
                    options["worker_mcp"] = worker_mcp
                options["workspace"] = workspace
            elif workspace is not None:
                if self.worker_lab_provider is None:
                    raise PermissionError("worker lab preparation is unavailable")
                # Pre-dispatch calls come only from the owner manager journey;
                # bind the requested path to the exact admitted project/task.
                task_ref = _.get("task_ref")
                project_ref = _.get("project_ref")
                if not isinstance(task_ref, (Mapping, ResourceRef)) or not isinstance(project_ref, (Mapping, ResourceRef)):
                    raise PermissionError("pre-dispatch worker workspace requires exact owner project and task references")
                context = self.worker_lab_provider(project_ref, task_ref)
                assigned_workspace = context.get("workspace") if isinstance(context, Mapping) else None
                if not isinstance(assigned_workspace, str) or os.path.realpath(workspace) != os.path.realpath(assigned_workspace):
                    raise PermissionError("worker workspace differs from the owner prepared task lab")
                options["workspace"] = assigned_workspace
                if self._default_adapter_factory:
                    options["roles"] = ("worker",)
                    options["source"] = assigned_workspace
            if principal != self.state.get("manager") and workspace is None:
                trusted_help_due = (isinstance(due, Mapping) and due.get("schedule_id") == evidence_id
                                    and due.get("role") in {"orchestrator", "project_advisor"})
                if trusted_help_due:
                    assignment_ref = due.get("assignment_ref")
                    generation = due.get("generation")
                    if (due.get("recipient") != principal or not isinstance(assignment_ref, Mapping)
                            or type(generation) is not int or generation < 1):
                        raise PermissionError("help Due does not bind this execution to its exact recipient and assignment")
                    assignment_value = self.owner.assignments.get(ResourceRef.from_dict(assignment_ref))
                    if (assignment_value.ref.to_dict() != dict(assignment_ref)
                            or assignment_value.generation != generation
                            or assignment_value.role != due.get("role")
                            or assignment_value.principal != principal):
                        raise PermissionError("help Due recipient assignment is stale or foreign")
                else:
                    raise PermissionError("non-manager execution requires an exact worker or retained help Due")
        adapter = self.adapter_factory(**options)
        # Workers and continuations are owned by the project's manager, as in
        # the Codex service; review input checks that exact linkage.
        return self.session.execution_application(adapter, manager_actor=self.state["manager"])

    def _caller_context(self, caller: Any) -> Any:
        due = self.due_port.read_due(caller.schedule_id)
        return self._execution(principal=caller.actor.actor, model=due["requested_model"],
                               reasoning=due["requested_reasoning"], evidence_id=caller.schedule_id).caller_context(caller)

    def _authorize_caller(self, context: Mapping[str, Any], request: Mapping[str, Any]) -> Any:
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        handler = self.execution_host.handler
        if not isinstance(handler, ManagerJourneyService):
            raise PermissionError("manager command authorization is not installed")
        return handler.authorize_caller(context, request)

    # -- host commands (the journey delegates unknown commands here) -----------
    def handle(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        command = request.get("command")
        if command == "report":
            return self._report(request)
        if command == "start-manager":
            return self._start_manager(request)
        if command == "project-documents":
            return self._project_documents(request)
        return {"outcome": "unavailable", "provider_called": False, "command": command,
                "reason": "not installed on this owner service; read `ottoctl manager --help`"}

    def _project_documents(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """The bound manager reads its own project's documents through Otto.

        list: every project.files document (path, role, revision, size).
        read: one document's current text by its project path.
        The project is bound by the service; the request names only a path.
        """
        from otto.portfolio.manager_journey_service import _CALLER
        caller = _CALLER.get()
        if caller is None or caller.get("role") != "manager" or caller.get("principal") != self.state["manager"]:
            raise PermissionError("project documents are read by the project's bound manager over its caller socket")
        request = {key: value for key, value in request.items() if value is not None}
        operation = request.get("operation", "list")
        allowed = {"list": {"command", "operation"}, "read": {"command", "operation", "path"}}
        if operation not in allowed or set(request) - allowed[operation] or (operation == "read" and not request.get("path")):
            raise ValueError("project-documents takes --operation list, or --operation read --path <project path>")
        from otto.portfolio.shared_documents import project_shared_documents
        project_ref = ResourceRef.from_dict(self.state["project_ref"])
        common = {"project_ref": self.state["project_ref"], "read_only": True, "provider_called": False,
                  "authority": "otto project.files (canonical after activation)"}
        if operation == "read" and request["path"].startswith("portfolio/"):
            return {**common, **project_shared_documents(self.owner, project_ref,
                operation="read", path=request["path"][len("portfolio/"):])}
        rows = self._documents(project_ref)
        if operation == "list":
            shared = project_shared_documents(self.owner, project_ref)
            return {**common, "outcome": "listed", "portfolio": [
                {**row, "path": "portfolio/" + row["path"]} for row in shared["documents"]], "documents": [
                {"path": row["path"], "role": row["role"], "revision_ref": row["revision_ref"],
                 "bytes": len(row["text"].encode()) if isinstance(row["text"], str) else None} for row in rows]}
        row = next((item for item in rows if item["path"] == request["path"]), None)
        if row is None:
            shared_read = project_shared_documents(self.owner, project_ref, operation="read", path=request["path"])
            if shared_read.get("outcome") == "read":
                return {**common, **shared_read}

            return {**common, "outcome": "unavailable", "path": request["path"],
                    "reason": "no such project document; list them with --operation list"}
        return {**common, "outcome": "read", "path": row["path"], "role": row["role"],
                "revision_ref": row["revision_ref"], "content": row["text"]}

    def _report(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        from datetime import datetime, timezone
        from otto.portfolio.owner_readers import json_value
        state, alias = self.state, request.get("task")
        if alias not in state["task_refs"]:
            raise ValueError("unknown current task")
        value = {"schema": "otto.manager-progress.v1", "project_ref": state["project_ref"], "task_alias": alias,
                 "task_ref": state["task_refs"][alias], "summary": request["summary"],
                 "next_action": request["next_action"], "continue_requested": request.get("continue_project") is True,
                 "logical_request_key": request["request_key"], "recorded_at": datetime.now(timezone.utc).isoformat()}
        result = self.owner.assignments.command_port.append_report(
            ResourceRef.from_dict(state["assignment_ref"]), value, expected_generation=state["manager_generation"],
            logical_request_key=request["request_key"], actor=self.binding.authenticated_actor(state["manager"]))
        return {"outcome": "committed", "report": json_value(result), "provider_called": False}

    def _start_manager(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Activation only: launch the prepared manager occurrence once."""
        if set(request) != {"command", "schedule_id"} or not request.get("schedule_id"):
            raise ValueError("start-manager requires exactly the prepared manager schedule_id")
        from otto.portfolio.operating_setup import read_setup
        setup = read_setup(self.portfolio.operations, self.state["project_ref"])
        if setup is None or setup["roles"].get("manager") != request["schedule_id"]:
            raise PermissionError("start-manager requires the adopted operating setup's manager occurrence")
        from otto.portfolio.manager_journey_service import manager_head, advance_manager_head, complete_manager_head
        expected_head = manager_head(self.state)
        app = self._execution(principal=self.state["manager"], model=self.state["requested_model"],
                              reasoning=self.state["requested_reasoning"], evidence_id="manager-initial")
        if not advance_manager_head(self.state, expected=expected_head,
                due=app._read(request["schedule_id"]), settled_anchor=expected_head):
            return {"outcome": "held", "reason": "manager head advanced before start",
                    "provider_called": False, "effects_started": False, "retry": False}
        self.state["schedule_id"] = request["schedule_id"]
        self._save_state()
        from otto.portfolio.owner_completion import after_owner

        def complete(result):
            due = self.due_port.read_due(request["schedule_id"]) or {}
            attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
            session = (attempt.get("result") or {}).get("physical_session_id") or attempt.get("physical_session_id")
            self.state["manager_launch"] = {"outcome": result.get("outcome"), "physical_session_id": session,
                                            "completion_state": due.get("completion_state")}
            if due.get("completion_state") == "succeeded" and isinstance(session, str):
                # The original invocation can settle after another retained head
                # has been selected. Preserve its result without moving that head.
                if complete_manager_head(self.state, schedule_id=due["schedule_id"], result=result):
                    self.state["manager_continuation"]["native_session_id"] = session
            self._save_state()
            return result

        return after_owner(app.start(schedule_id=request["schedule_id"]), complete)

    # -- the orchestrator's reply: owner-issued grants ---------------------------
    def grant_reply(self, token: str, request: Mapping[str, Any], principal: str) -> None:
        """Record that THIS forwarded request is the orchestrator's reply (service only)."""
        atomic_json(self.paths["grants"] / (token + ".json"),
                    {"schema": GRANT_SCHEMA, "token": token, "digest": request_digest(request), "principal": principal})

    def reply_authorizer(self) -> Callable[[Mapping[str, Any]], Any]:
        """respond-help is accepted only with the grant the service issued for its lane token.

        The manager can write its own lane but not the grants directory, so a
        manager-written reply (or a launched process on the socket) is refused.
        The responder is the granted principal, which must be the project's
        current accountable supervisor.
        """
        def authorize(request: Mapping[str, Any]) -> Any:
            from otto.portfolio.manager_journey_service import _CALLER
            if _CALLER.get() is not None:
                raise PermissionError("a launched process cannot answer an escalation")
            handle = self.execution_host.command_handle() or {}
            token = handle.get("request_id") if handle.get("transport") == "file-ipc" else None
            path = self.paths["grants"] / ((token or "missing") + ".json")
            grant = read_private_json(path) if token else None
            if grant is None or grant.get("digest") != request_digest(request):
                raise PermissionError("respond-help is accepted only from the orchestrator's host lane "
                                      "(`ottoctl help respond`)")
            supervisor = self.help_delivery.readers.current_supervisor(self.state["project_ref"])
            if supervisor is None or supervisor.principal != grant["principal"]:
                raise PermissionError("the reply's principal is not the project's accountable supervisor")
            path.unlink(missing_ok=True)
            return self.binding.authenticated_actor(grant["principal"])
        return authorize


def observe_schedules_factory(service: HostOwnerService) -> Callable[[str], Mapping[str, Any]]:
    owner_actor = service.session.actor.actor

    def observe(project_id: str) -> Mapping[str, Any]:
        rows = service.due_port.list_due()
        mine = [row for row in rows if row.get("project_ref") == project_id]
        owned = [row["schedule_id"] for row in mine if row.get("owner") == owner_actor
                 and row.get("interval_seconds") is not None and row.get("stop_state") != "completed"]
        return {"mode": "owned-schedule" if owned else "no-owned-schedule", "pm_owned_schedule_ids": owned,
                "unknown_ownership": any(row.get("owner") != owner_actor for row in mine
                                         if row.get("interval_seconds") is not None),
                "coverage": {"authority": service.config["store"]["authority"], "project_id": project_id,
                             "source": "complete public Due list", "record_count": len(rows)},
                "shared_records": [{"schedule_id": row["schedule_id"], "status": "preserved"}
                                   for row in rows if row["schedule_id"] not in owned]}
    return observe


def attach(session: HostSession, record: Any, *, command_lock: Any,
           adapter_factory: Optional[Callable[..., Any]] = None,
           turn_admission: Optional[Callable[[], Any]] = None) -> HostOwnerService:
    """Compose and start one activated project's manager lanes (no Due, no provider)."""
    from otto.portfolio.manager_journey_service import install_manager_journey_service
    service = HostOwnerService(session, record, command_lock=command_lock, adapter_factory=adapter_factory,
                               turn_admission=turn_admission)
    service._save_state()
    install_manager_journey_service(service, run_path=service.render_run_view(),
        workspace=service.worktree(), orchestrator_principal=session.actor.actor,
        observe_schedules=observe_schedules_factory(service),
        help_reply_authorizer=service.reply_authorizer())
    service.execution_host.start()
    return service
