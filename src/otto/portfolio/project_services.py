"""Fixed project views over one owner and its existing retained commands."""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .native_caller_ingress import managed_caller_binding


def _identity(ref: Mapping[str, Any]) -> tuple[str, str, str]:
    return tuple(ref[key] for key in ("authority", "kind", "id"))


class ProjectServices:
    """Owner-installed routing, never a caller-selected project capability.

    Compose each ManagerJourneyService with its own server view, state saver,
    adapter factory, run path and workspace. All views share one Store, Due
    port and ExecutionHost. Install before starting that host. Native routing
    comes from authenticated context; internal delivery from the original Due.
    Optional owner_route must authenticate a protected owner request/grant and
    return one installed key. A JSON project ID alone is not such a grant.
    """

    _retained = frozenset({"start-retained-worker", "start-retained-help",
        "manager-worker-result", "manager-task-settlement", "manager-help-result",
        "start-retained-child", "parent-child-result"})

    def __init__(self, services: Mapping[str, Any], *, owner_route: Any = None) -> None:
        if not services or len(services) > 16:
            raise ValueError("install between one and sixteen explicit project views")
        self.services = MappingProxyType(dict(services))
        first = next(iter(services.values()))
        self.host, self.due_port, self.store = first.host, first.server.due_port, first.server.store
        if self.host._threads or not self.host.bounded_transports:
            raise RuntimeError("install fixed project views on a closed bounded host")
        if owner_route is not None and not callable(owner_route):
            raise TypeError("owner routing must be a trusted authentication port")
        self.owner_route = owner_route
        projects, states, assignments = {}, set(), set()
        for key, service in services.items():
            if not isinstance(key, str) or not key:
                raise ValueError("project view keys must be nonempty text")
            server, state = service.server, service.server.state
            project = _identity(state["project_ref"])
            assignment = _identity(state["assignment_ref"])
            if (service.host is not self.host or server.due_port is not self.due_port
                    or server.store is not self.store
                    or server.owner.owner_actor != first.server.owner.owner_actor):
                raise ValueError("project views must share the same owner, Store, Due port and host")
            if project in projects or id(state) in states or assignment in assignments:
                raise ValueError("project, assignment and mutable state views must be distinct")
            projects[project] = service
            states.add(id(state)); assignments.add(assignment)
            service._fixed_project_binding = (project, state["manager"], assignment,
                state["manager_generation"], service.workspace, service.run_path)
        self._projects = MappingProxyType(projects)

    def _project(self, ref: Mapping[str, Any]) -> Any:
        service = self._projects.get(_identity(ref))
        if service is None:
            raise PermissionError("project has no owner-installed service view")
        self._check(service)
        return service

    @staticmethod
    def _check(service: Any) -> None:
        state = service.server.state
        current = (_identity(state["project_ref"]), state["manager"],
            _identity(state["assignment_ref"]), state["manager_generation"],
            service.workspace, service.run_path)
        if current != service._fixed_project_binding:
            raise PermissionError("project service binding changed; recompose at a closed owner boundary")

    def _due(self, schedule_id: str) -> tuple[Any, Mapping[str, Any]]:
        raw = self.due_port.read_due(schedule_id)
        if not isinstance(raw, Mapping) or not isinstance(raw.get("target"), Mapping):
            raise PermissionError("retained occurrence is unavailable")
        service = self._project(raw["target"]["project_ref"])
        if raw.get("project_ref") != service.server.state["project_ref"]["id"]:
            raise PermissionError("occurrence project and target disagree")
        from herzchen.contracts import ResourceRef
        assignment = service.server.owner.assignments.command_port.get(ResourceRef.from_dict(raw["assignment_ref"]))
        scope = assignment.scope
        if _identity(scope.to_dict()) == _identity(raw["target"]["task_ref"]):
            task = service.server.owner.graph.reader.get_identity(scope)
            scope = ResourceRef.from_dict(task.payload["project_ref"])
        if _identity(scope.to_dict()) != _identity(raw["target"]["project_ref"]):
            raise PermissionError("occurrence assignment belongs to another project")
        return service, raw

    def managed_server(self, authorization: Mapping[str, Any]) -> Any:
        return self._project(authorization["project_ref"]).server

    def managed_caller_binding(self, authorization: dict[str, Any]) -> Any:
        return managed_caller_binding(self.managed_server(authorization), authorization)

    def caller_context(self, binding: Any) -> Mapping[str, Any]:
        service, due = self._due(binding.schedule_id)
        app = service._execution(principal=binding.actor.actor, model=due["requested_model"],
            reasoning=due["requested_reasoning"], evidence_id="caller-" + binding.schedule_id)
        return app.caller_context(binding)

    def authorize_caller(self, context: Mapping[str, Any], request: Mapping[str, Any]) -> None:
        service = self._project(context["project_ref"])
        actual, _ = self._due(context["occurrence_ref"]["schedule_id"])
        if actual is not service:
            raise PermissionError("caller occurrence belongs to another project view")
        service.authorize_caller(context, request)

    def dispatch_bound(self, context: Mapping[str, Any], request: Mapping[str, Any]) -> Any:
        self.authorize_caller(context, request)
        return self._project(context["project_ref"]).dispatch_bound(context, request)

    def __call__(self, request: Mapping[str, Any]) -> Any:
        if request.get("command") in self._retained:
            service, _ = self._due(request["schedule_id"])
        elif self.owner_route is not None:
            key = self.owner_route(request)
            service = self.services.get(key)
            if service is None:
                raise PermissionError("authenticated owner target has no installed project view")
            self._check(service)
        else:
            raise PermissionError("unbound owner command requires an authenticated exact project target")
        return service(request)

    def reconcile_startup(self) -> Mapping[str, Any]:
        """Read/settle only current or retained handles before new admission."""
        if self.host._threads:
            raise RuntimeError("startup reconciliation requires closed owner custody")
        schedules = set()
        for service in self.services.values():
            schedules.update(service._known_schedule_ids(service.server.state))
        # Pending children may not be in a manager's compact current map. Their
        # existing exact retained files are the recovery handles; no history scan.
        files = list(self.host.directory.glob("request-*.json"))
        if len(files) > 128:
            raise ValueError("reconcile the bounded retained command set before admission")
        for path in files:
            request = json.loads(path.read_text())
            if request.get("command") in self._retained:
                schedules.add(request["schedule_id"])
        if len(schedules) > 128:
            raise ValueError("startup exceeds the bounded known occurrence set")
        rows = []
        for schedule in sorted(schedules):
            service, due = self._due(schedule)
            app = service._execution(principal=due["recipient"], model=due["requested_model"],
                reasoning=due["requested_reasoning"], evidence_id="startup-" + schedule,
                selection=(due["target"].get("launch_request") or {}).get("selection"))
            try:
                result = app.recover(schedule_id=schedule, execute=False)
            finally:
                self.host.restore_execution(app, app._read(schedule))
            rows.append({"schedule_id": schedule, "outcome": result["outcome"]})
        return {"outcome": "reconciled", "occurrences": rows,
                "capacity_holds": list(self.host._capacity_holds), "provider_called": False}

    def install(self) -> Mapping[str, Any]:
        result = self.reconcile_startup()
        self.host.handler = self
        self.host.caller_context_resolver = self.caller_context
        self.host.caller_authorizer = self.authorize_caller
        return result
