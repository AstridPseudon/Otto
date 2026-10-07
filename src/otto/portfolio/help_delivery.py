"""Host-owned delivery bindings over existing issue reports and role ports.

Receipt inspection is deliberately manual: persisting a report is neither a
chat notification nor a resolution. A host sender must return actual delivery
evidence for the exact assignment, generation and conversation it receives.
"""
from __future__ import annotations

from typing import Any, Mapping

from .issue_loop import IssueLoopError
from .owner_readers import json_value


class BoundHelpDelivery:
    """A finite host port; no scheduler, queue, database or execution allowance."""

    def __init__(self, *, readers: Any, send: Any = None, read_delivery: Any = None,
                 interim_supervision: Mapping[str, Any] | None = None) -> None:
        self.readers, self.sender, self.reader = readers, send, read_delivery
        self.interim = None if interim_supervision is None else json_value(interim_supervision)
        self.automatic = callable(send)
        if self.interim is not None:
            if (set(self.interim) != {"project_ref", "assignment_ref", "generation", "principal", "conversation_ref"}
                    or not isinstance(self.interim["generation"], int) or isinstance(self.interim["generation"], bool)
                    or self.interim["generation"] < 1):
                raise IssueLoopError("interim supervision requires exact owner-issued project, assignment, generation, principal and conversation")
            self.current_supervisor(self.interim["project_ref"])

    def current_supervisor(self, project: Mapping[str, Any]) -> Any:
        from otto.attention import native_target_identity
        if self.interim is None:
            return None
        binding = self.interim
        if any(project.get(k) != binding["project_ref"].get(k) for k in ("authority", "kind", "id")):
            raise IssueLoopError("interim supervision is outside its bound project")
        self.readers.project(project)
        assignment = self.readers.operations.assignments_port.get(binding["assignment_ref"])
        conversation = binding["conversation_ref"]
        if (json_value(assignment.ref) != binding["assignment_ref"] or assignment.generation != binding["generation"]
                or assignment.principal != binding["principal"] or assignment.role != "orchestrator"
                or not self.readers.active(assignment) or not isinstance(conversation, Mapping)
                or not isinstance(conversation.get("host"), str) or not conversation["host"].strip()
                or native_target_identity(conversation) is None
                or self.readers.conversation(project, assignment) != native_target_identity(conversation)):
            raise IssueLoopError("interim supervision assignment or actual conversation is stale")
        return assignment

    def describe(self, project: Mapping[str, Any]) -> dict[str, Any]:
        supervisor = self.readers.current_supervisor(project)
        if supervisor is None:
            supervisor = self.current_supervisor(project)
        if supervisor is None:
            raise IssueLoopError("accountable help recipient is missing")
        if self.interim is not None and json_value(supervisor.ref) != self.interim["assignment_ref"]:
            raise IssueLoopError("current supervisor differs from the interim binding")
        return {"mode": "automatic" if self.automatic else "receipt-inspection",
                "automatic": self.automatic, "assignment_ref": json_value(supervisor.ref),
                "generation": supervisor.generation, "principal": supervisor.principal,
                "conversation_ref": self.interim["conversation_ref"] if self.interim else supervisor.session,
                "source": "owner-issued host delivery binding"}

    def send(self, intent: Mapping[str, Any]) -> dict[str, Any]:
        project = intent["project_ref"]
        assignment = self.readers.operations.assignments_port.get(intent["recipient_assignment_ref"])
        if assignment.role == "manager":
            current = self.readers.current_manager(project)
        elif assignment.role == "project_advisor":
            current = self.readers.current_advisor(project)
        elif assignment.role == "orchestrator":
            current = self.readers.current_supervisor(project) or self.current_supervisor(project)
        else:
            raise IssueLoopError("help recipient role is unsupported")
        native = self.readers.conversation(project, assignment)
        if (current is None or json_value(current.ref) != intent["recipient_assignment_ref"]
                or assignment.generation != intent.get("recipient_generation")
                or assignment.principal != intent.get("recipient_principal")
                or native != intent.get("recipient_conversation") or not native):
            raise IssueLoopError("help delivery recipient or real conversation is stale")
        if self.sender is not None:
            return self.sender(dict(intent))
        if self.interim is None or assignment.role == "project_advisor":
            return {"state": "unsupported", "transport": "unbound", "retry": False}
        self.describe(project)
        return {"state": "pending", "transport": "receipt-inspection", "retry": False,
                "receipt": {"delivery_id": intent["delivery_id"], "report_ref": intent["message"]["report_ref"],
                            "recipient_assignment_ref": intent["recipient_assignment_ref"],
                            "generation": assignment.generation, "principal": assignment.principal,
                            "conversation_id": native, "notification_sent": False},
                "next_action": ("Manager reads the exact retained response and owner constraints, then records authorized application through resolve-help; independent ready work continues."
                    if assignment.role == "manager" and intent["message"].get("type") == "issue_response" else
                    "Accountable supervisor inspects the retained help report and returns respond-help; independent useful work continues.")}

    def read_delivery(self, delivery_id: str) -> Any:
        if callable(self.reader):
            return self.reader(delivery_id)
        return {"outcome": "pending", "transport": "receipt-inspection", "retry": False}


class ExecutionHelpDelivery(BoundHelpDelivery):
    """Retain exact role delivery on ExecutionHost and the existing runtime.

    The role's adopted occurrence supplies model, profile, context, native
    binding and allowance. An advice request grants no new execution budget.
    Manager replies use the service's same-manager help continuation instead
    of starting a second manager turn from the notification port.
    """

    def __init__(self, *, readers: Any, project_ref: Mapping[str, Any],
                 execution: Any, submit: Any, interim_supervision: Mapping[str, Any] | None = None) -> None:
        self.project_ref = json_value(project_ref)
        self.execution, self.submit = execution, submit
        readers.project(self.project_ref)
        if not callable(execution) or not callable(submit):
            raise IssueLoopError("automatic help requires owner execution and retained host submission ports")
        super().__init__(readers=readers, send=self._send, read_delivery=self._read_delivery,
                         interim_supervision=interim_supervision)

    def _send(self, intent: Mapping[str, Any]) -> dict[str, Any]:
        from otto.attention import DueRecord
        from .operating_setup import read_setup
        if any(intent["project_ref"].get(k) != self.project_ref.get(k) for k in ("authority", "kind", "id")):
            raise IssueLoopError("automatic help is outside its bound project")
        assignment = self.readers.operations.assignments_port.get(intent["recipient_assignment_ref"])
        if assignment.role == "manager":
            return {"state": "pending", "transport": "retained-manager-continuation", "retry": False}
        setup = read_setup(self.readers.operations, intent["project_ref"])
        if setup is None or assignment.role not in setup["roles"]:
            raise IssueLoopError("automatic help requires the current adopted role occurrence")
        prior = DueRecord.from_dict(self.readers.due_port.read_due(setup["roles"][assignment.role]))
        attempt = (prior.host_evidence or {}).get("gateway_attempt")
        if (prior.assignment_ref != intent["recipient_assignment_ref"] or prior.generation != assignment.generation
                or prior.target.get("native_id") != intent["recipient_conversation"]
                or prior.completion_state == "unknown"
                or attempt and (prior.stop_state != "completed" or prior.completion_state != "succeeded")):
            return {"state": "unknown", "transport": "retained-role-effect", "retry": False,
                    "reason": "reconcile the existing role effect before help delivery"}
        for raw in self.readers.due_port.list_due({"role": assignment.role, "recipient": assignment.principal}):
            if ((raw.get("assignment_ref") or {}).get("id") != assignment.ref.id
                    or raw.get("generation") != assignment.generation):
                continue
            attempted = (raw.get("host_evidence") or {}).get("gateway_attempt")
            if raw.get("completion_state") == "unknown" or attempted and raw.get("stop_state") != "completed":
                return {"state": "pending", "transport": "retained-role-effect", "retry": False,
                        "reason": "current recipient owns a retained turn; inspect the existing issue reports before another delivery"}
        app = self.execution(principal=assignment.principal, model=prior.requested_model,
            reasoning=prior.requested_reasoning, evidence_id=intent["delivery_id"])
        prepared = app.prepare_role(role=assignment.role, project_ref=prior.target["project_ref"],
            task_ref=prior.target["task_ref"], assignment_ref=prior.assignment_ref, generation=prior.generation,
            mandate_ref=prior.target["mandate_ref"], context_refs=prior.context_refs,
            request_key="help-delivery:" + intent["delivery_id"],
            instruction=("Read the current help/advice issue " + intent["issue_id"] + " and its retained report " +
                intent["message"]["report_ref"]["id"] + ". Return a scoped response through the authenticated recipient reply port. "
                "Advice is a suggestion; operational changes require your existing authority. Preserve budgets and unknown effects."),
            model=prior.requested_model, reasoning=prior.requested_reasoning, profile=prior.profile,
            native_session_id=intent["recipient_conversation"], binding_schedule_id=prior.schedule_id,
            allowance_ref=prior.allowance_ref, timeout_seconds=prior.timeout_seconds)
        if prepared.get("outcome") not in {"committed", "prepared", "replayed"}:
            return {"state": "unknown", "transport": "retained-role-effect", "receipt": prepared, "retry": False}
        retained = self.submit({"command": "start-retained-help", "principal": assignment.principal,
            "schedule_id": prepared["schedule_id"], "delivery_id": intent["delivery_id"]})
        return {"state": "prepared", "transport": "retained-role-execution", "retry": False,
                "receipt": {**dict(retained), "recipient_assignment_ref": prior.assignment_ref,
                            "generation": prior.generation, "conversation_id": intent["recipient_conversation"]}}

    def _read_delivery(self, delivery_id: str) -> dict[str, Any]:
        from .execution import _digest
        reports = self.readers.reports(self.project_ref)
        values = [r["value"] for r in reports if isinstance(r.get("value"), Mapping)
            and r["value"].get("schema") == "otto.issue.delivery.v1" and r["value"].get("delivery_id") == delivery_id]
        intent = next((v for v in values if v.get("state") == "intent"), None)
        if intent is None:
            return {"outcome": "unknown", "retry": False}
        receipt = next((v.get("receipt") for v in reversed(values) if isinstance(v.get("receipt"), Mapping)), None)
        schedule = receipt.get("schedule_id") if receipt else None
        if schedule is None and intent["message"]["type"] == "issue_response":
            ref = intent["recipient_assignment_ref"]
            key = "help-result:" + _digest([ref["id"], intent["recipient_generation"], intent["message"]["report_ref"]])
            schedule = "manager-help-callback-" + _digest(key)[:28]
        raw = self.readers.due_port.read_due(schedule) if schedule else None
        if not isinstance(raw, Mapping):
            return {"outcome": "pending", "retry": False, "transport": "retained-role-execution"}
        result = ((raw.get("host_evidence") or {}).get("gateway_attempt") or {}).get("result") or {}
        if (raw["assignment_ref"] != intent["recipient_assignment_ref"] or raw["generation"] != intent["recipient_generation"]
                or raw["target"].get("native_id") != intent["recipient_conversation"]):
            return {"outcome": "stale", "retry": False}
        sent = (raw["stop_state"] == "completed" and raw["completion_state"] == "succeeded"
                and result.get("context_digest_verified") is True
                and result.get("physical_session_id") == intent["recipient_conversation"])
        return {"outcome": "sent" if sent else "unknown" if raw["completion_state"] == "unknown" else "pending",
                "retry": False, "schedule_id": schedule, "transport": "retained-role-execution",
                "receipt": {"native_id": result.get("physical_session_id"), "turn_id": result.get("observed_turn_id"),
                            "context_digest_verified": result.get("context_digest_verified")}}
