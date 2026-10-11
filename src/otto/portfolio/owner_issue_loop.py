"""Production issue-loop composition using finite owner ports and current reads."""

from __future__ import annotations

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
        grant = getattr(self.operations, "project_read_grant", None)
        if grant is not None and not grant.allows(ref):
            raise IssueLoopError("issue project is outside the owner-issued project grant")
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
        if relation.get("schema") != "otto.orchestrator.supervision.v2":
            raise IssueLoopError("supervision relation has an unsupported schema")
        relation_project = relation.get("project_ref")
        if (not isinstance(relation_project, Mapping)
                or any(relation_project.get(key) != getattr(record.ref, key)
                       for key in ("authority", "kind", "id"))):
            raise IssueLoopError("supervision relation is outside the selected project")
        ref = relation.get("assignment_ref")
        if not isinstance(ref, Mapping) or ref.get("authority") != record.ref.authority:
            raise IssueLoopError("supervision assignment is foreign or unavailable")
        assignment = self.operations.assignments_port.get(ref)
        scope = _json_value(getattr(assignment, "scope", None))
        portfolio = relation.get("portfolio_ref")
        if (not isinstance(portfolio, Mapping) or not isinstance(scope, Mapping)
                or any(portfolio.get(key) != scope.get(key)
                       for key in ("authority", "kind", "id"))
                or scope.get("kind") != "wrk.portfolio"
                or relation.get("assignment_revision") != getattr(assignment.ref, "revision", None)):
            raise IssueLoopError("supervision assignment scope or revision is stale")
        if (assignment.role != "orchestrator" or not self.active(assignment)
                or assignment.generation != relation.get("generation")):
            raise IssueLoopError("project supervision is stale")
        return assignment

    def current_advisor(self, project: Mapping[str, Any]) -> Any:
        from .operating_setup import read_setup
        from .advisor_pairing import establish_pairing
        from otto.attention import DueRecord
        record = self.project(project)
        setup = read_setup(self.operations, _json_value(record.ref))
        if setup is None:
            raise IssueLoopError("advice requires an adopted explicit advisor policy")
        if setup["advisor_policy"]["mode"] == "disabled":
            raise IssueLoopError("advisor_disabled: " + setup["advisor_policy"]["reason"])
        dues = {}
        for role in ("manager", "project_advisor"):
            raw = self.due_port.read_due(setup["roles"][role])
            if not isinstance(raw, Mapping):
                raise IssueLoopError("advice role occurrence is unavailable")
            dues[role] = DueRecord.from_dict(raw)
        assignments = [_json_value(item) for item in
            self.operations.sheet_port.export(record.ref)["project"]["observed"].get("assignments", ())]
        pairing = establish_pairing(_json_value(record.ref), assignments,
            manager_conversation_ref={"host": dues["manager"].target["host"], "native_id": dues["manager"].target["native_id"]},
            advisor_conversation_ref={"host": dues["project_advisor"].target["host"], "native_id": dues["project_advisor"].target["native_id"]})
        advisor = self.operations.assignments_port.get(pairing.advisor_ref)
        for role, ref, generation in (("manager", pairing.manager_ref, pairing.manager_generation),
                                      ("project_advisor", pairing.advisor_ref, pairing.generation)):
            assignment = self.operations.assignments_port.get(ref)
            due = dues[role]
            if (_json_value(assignment.ref) != due.assignment_ref or generation != due.generation
                    or assignment.principal != due.recipient or not self.active(assignment)
                    or due.role != role or due.project_ref != record.ref.id
                    or any(due.target["project_ref"].get(k) != getattr(record.ref, k) for k in ("authority", "kind", "id"))
                    or self.conversation(project, assignment) != due.target["native_id"]):
                raise IssueLoopError("advice pairing or conversation is stale")
        if dues["project_advisor"].allowance_ref is None:
            raise IssueLoopError("advice requires its adopted execution allowance")
        return advisor

    def conversation(self, project: Mapping[str, Any], assignment: Any) -> str | None:
        from otto.attention import native_target_identity, DueRecord
        from .operating_setup import read_setup
        session = assignment.session
        if session is not None:
            return session if isinstance(session, str) else native_target_identity(session) if isinstance(session, Mapping) else None
        # S02 also accepts exact admitted host bindings for assignments whose
        # initial session field was absent. Never infer one from a role name.
        setup = read_setup(self.operations, _json_value(self.project(project).ref))
        schedule = setup["roles"].get(assignment.role) if setup else None
        raw = self.due_port.read_due(schedule) if schedule else None
        if not isinstance(raw, Mapping):
            return None
        due = DueRecord.from_dict(raw)
        from .operating_setup import verify_role_conversation, OperatingSetupError
        grant = getattr(self.operations, "project_read_grant", None)
        actor = getattr(getattr(grant, "principal", None), "actor", None)
        try:
            native, _ = verify_role_conversation(due=due, assignment={"ref": _json_value(assignment.ref), "principal": assignment.principal,
                    "generation": assignment.generation, "role": assignment.role, "payload": assignment.payload},
                project_ref=_json_value(self.project(project).ref), due_port=self.due_port, actor=actor,
                assignment_history_reader=getattr(self.operations, "_owner_reader", None))
        except OperatingSetupError as exc:
            raise IssueLoopError("admitted help conversation is stale or unverified: " + str(exc)) from exc
        return native

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
        # Project/task assignment observations retain old manager identities.
        # Exact project history also carries previous supervisor assignments.
        # Select their immutable streams before hydrating report/result bodies;
        # revision equality must NOT exclude pre-adoption observations.
        owner_reader = self.operations._owner_reader
        assignments = {}
        def remember(value):
            value = _json_value(value)
            if (isinstance(value, Mapping) and value.get("authority") == record.ref.authority
                    and value.get("kind") == "wrk.assignment" and isinstance(value.get("id"), str)):
                assignments[value["id"]] = value
        for row in (view["project"], *view["tasks"]):
            for assignment in row.get("observed", {}).get("assignments", ()):
                remember(assignment.get("ref"))
        relation = record.payload.get("metadata", {}).get("otto_orchestrator", {})
        if isinstance(relation, Mapping):
            remember(relation.get("assignment_ref"))
        for event in owner_reader.list_events(stream="work:" + record.ref.id, subjects=(record.ref,)):
            for ref in (*event.before_refs, *event.after_refs):
                remember(ref)
            for name in ("from_assignment", "to_assignment"):
                remember(event.effects.get(name))
        events = (event for ident in sorted(assignments) for kind in ("report", "result")
                  for event in owner_reader.list_events(stream=kind + ":" + ident))
        for event in events:
            if event.subject.kind not in {"wrk.report", "wrk.result"} or event.subject.id in seen:
                continue
            seen.add(event.subject.id)
            observation = owner_reader.get_record(event.subject)
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
        result = []
        for due in self.due_port.list_due({"project_ref": record.ref.id}):
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
    supervisor = readers.current_supervisor
    if callable(getattr(delivery, "current_supervisor", None)):
        # A host may explicitly issue a bound manual supervisor for a project
        # without autonomous orchestration. It still resolves a real assignment.
        def supervisor(project):
            current = readers.current_supervisor(project)
            return current if current is not None else delivery.current_supervisor(project)
    return IssueLoop(IssueLoopPorts(
        assignments=operations.assignments_port, due_records=due_port,
        authenticate=operations.binding.authenticated_actor,
        current_manager=readers.current_manager, current_supervisor=supervisor,
        current_facts=readers.facts, reports_for_project=readers.reports,
        due_records_for_project=readers.due_records, delivery=delivery, current_advisor=readers.current_advisor,
        recipient_conversation=readers.conversation,
    ))
