"""Production issue-loop composition using finite owner ports and current reads."""

from typing import Any, Mapping

from .herzchen_binding import _json_value
from .issue_loop import IssueLoop, IssueLoopError, IssueLoopPorts


class OwnerIssueReaders:
    """Read existing owner records; retain neither Store nor a second ledger."""

    def __init__(self, operations: Any, due_port: Any) -> None:
        self.operations = operations
        self.due_port = due_port

    def project(self, value: Mapping[str, Any]) -> Any:
        from herzchen.contracts import ResourceRef

        ref = ResourceRef.from_dict(dict(value))
        if ref.authority != self.operations.binding.authority or ref.kind != "work.project":
            raise IssueLoopError("issue scope must be an owner-local project")
        current = self.operations.reader.get_record(ResourceRef(ref.authority, ref.kind, ref.id))
        if current is None:
            raise IssueLoopError("issue project is unavailable")
        return current

    @staticmethod
    def active(assignment: Any) -> bool:
        status = getattr(assignment.status, "value", assignment.status)
        return status in {"queued", "reassigned", "in-flight", "active", "running", "assigned"}

    def current_manager(self, project: Mapping[str, Any]) -> Any:
        record = self.project(project)
        view = self.operations.sheet_port.export(record.ref)
        candidates = []
        for value in view["project"]["observed"].get("assignments", ()):
            if value.get("payload", {}).get("role") == "manager":
                assignment = self.operations.assignments_port.get(value["ref"])
                if self.active(assignment):
                    candidates.append(assignment)
        if len(candidates) != 1:
            raise IssueLoopError("project must have exactly one current manager")
        return candidates[0]

    def current_supervisor(self, project: Mapping[str, Any]) -> Any:
        record = self.project(project)
        relation = record.payload.get("metadata", {}).get("otto_orchestrator")
        if not isinstance(relation, Mapping):
            return None
        ref = relation.get("assignment_ref")
        if not isinstance(ref, Mapping) or ref.get("authority") != record.ref.authority:
            raise IssueLoopError("supervision assignment is foreign or unavailable")
        assignment = self.operations.assignments_port.get(ref)
        if (assignment.role != "orchestrator" or not self.active(assignment)
                or assignment.generation != relation.get("generation")):
            raise IssueLoopError("project supervision is stale")
        return assignment

    def facts(self, project: Mapping[str, Any], assignment: Any, actor: str) -> Mapping[str, Any]:
        from .intake import OttoPortfolio

        result = OttoPortfolio(self.operations).read_work(self.project(project).ref, actor=actor)
        if result.get("outcome") != "read":
            raise IssueLoopError("current owner work read failed")
        return result

    def reports(self, project: Mapping[str, Any]) -> list[dict[str, Any]]:
        record = self.project(project)
        view = self.operations.sheet_port.export(record.ref)
        scopes = {record.ref.id, *(item["ref"]["id"] for item in view["tasks"])}
        result = []
        seen = set()
        # Existing event subjects enumerate immutable reports across assignment
        # revisions and supervisor transfers; no parallel issue index is kept.
        for event in self.operations.reader.list_events():
            if event.subject.kind not in {"wrk.report", "wrk.result"} or event.subject.id in seen:
                continue
            seen.add(event.subject.id)
            observation = self.operations.reader.get_record(event.subject)
            if observation is None:
                continue
            payload = observation.payload
            value = payload.get("value")
            linked = value.get("project_ref") if isinstance(value, Mapping) else None
            if isinstance(linked, Mapping):
                belongs = all(linked.get(key) == getattr(record.ref, key) for key in ("authority", "kind", "id"))
            else:
                assignment = self.operations.assignments_port.get(payload["assignment"])
                belongs = assignment.scope.authority == record.ref.authority and assignment.scope.id in scopes
            if belongs:
                result.append({"ref": _json_value(observation.ref),
                    "assignment": _json_value(payload.get("assignment")),
                    "kind": payload.get("observation_kind"), "generation": payload.get("generation"),
                    "version": observation.version, "value": _json_value(value)})
        return result

    def due_records(self, project: Mapping[str, Any]) -> list[dict[str, Any]]:
        record = self.project(project)
        manager = self.current_manager(project)
        ids = {event.subject.id for event in self.operations.reader.list_events()
               if event.subject.kind == "otto.due-record"}
        result = []
        for schedule_id in sorted(ids):
            due = self.due_port.read_due(schedule_id)
            if (isinstance(due, Mapping) and due.get("project_ref") == record.ref.id
                    and due.get("role") == "manager" and due.get("manager_ref") == manager.ref.id
                    and due.get("generation") == manager.generation):
                result.append(dict(due))
        return result


def compose_owner_issue_loop(operations: Any, due_port: Any, *, delivery: Any = None) -> IssueLoop:
    """Bind the same finite assignment/reader/DueRecord capabilities as roles."""
    if not all(callable(getattr(due_port, name, None)) for name in ("read_due", "save_due")):
        raise TypeError("due_port must expose finite read_due/save_due")
    readers = OwnerIssueReaders(operations, due_port)
    return IssueLoop(IssueLoopPorts(
        assignments=operations.assignments_port, due_records=due_port,
        authenticate=operations.binding.authenticated_actor,
        current_manager=readers.current_manager, current_supervisor=readers.current_supervisor,
        current_facts=readers.facts, reports_for_project=readers.reports,
        due_records_for_project=readers.due_records, delivery=delivery,
    ))
