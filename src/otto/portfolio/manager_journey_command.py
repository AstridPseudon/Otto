"""Ordinary judgment and finish composed over existing canonical owner APIs."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .local_assessment_policy import LocalAssessmentPolicy
from .owner_readers import json_value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class ManagerJourneyCommands:
    """Trusted service composition; transport input cannot select an actor or pool."""

    def __init__(self, *, owner: Any, portfolio: Any, state: Mapping[str, Any], policy: Any = None,
                 due_port: Any = None, settle_execution: Any = None) -> None:
        self.owner, self.portfolio, self.state = owner, portfolio, state
        self.policy = policy
        self.due_port, self.settle_execution = due_port, settle_execution

    def _authorize(self) -> Any:
        project = ResourceRef.from_dict(self.state["project_ref"])
        assignment = self.owner.assignments.command_port.get(
            ResourceRef.from_dict(self.state["assignment_ref"]))
        grant = self.owner.project_read_grant
        if (grant is None or grant.principal != self.owner.owner_actor or not grant.allows(project)
                or assignment.ref.to_dict() != self.state["assignment_ref"]
                or assignment.role != "manager" or assignment.principal != self.state["manager"]
                or assignment.generation != self.state["manager_generation"]
                or assignment.status.value == "cancelled"
                or (assignment.scope.authority, assignment.scope.kind, assignment.scope.id)
                != (project.authority, project.kind, project.id)):
            raise PermissionError("ordinary judgment requires the current bound manager")
        return self.owner.binding.authenticated_actor(self.state["manager"])

    def _journal(self, key: str, stage: str, value: Any = None) -> Any:
        actor = self._authorize()
        port = self.owner.assignments.command_port
        assignment = ResourceRef.from_dict(self.state["assignment_ref"])
        identity = "journey:" + key + ":" + stage
        reports = port.list_observations(assignment, kind="report")
        prior = next((report.value for report in reports
                      if report.value.get("logical_request_key") == identity), None)
        if prior is not None:
            if value is not None and prior["content"] != value:
                raise ValueError("ordinary request key was reused with changed input")
            return prior["content"]
        if value is None:
            return None
        port.append_report(assignment, {"schema": "otto.manager-journey.v1",
            "logical_request_key": identity, "content": value},
            expected_generation=self.state["manager_generation"],
            logical_request_key=identity, actor=actor)
        return value

    def _key(self, request: Mapping[str, Any]) -> str:
        key = request.get("request_key")
        if not isinstance(key, str) or not key.strip() or key != key.strip() or len(key) > 160:
            raise ValueError("request_key must be 1..160 exact characters")
        return key

    def review_task(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._authorize()
        key = self._key(request)
        allowed = {"command", "task", "request_key", "candidate_ref", "source_refs",
                   "judgments", "inspection", "finish"}
        if set(request) - allowed or type(request.get("finish", True)) is not bool:
            raise ValueError("unsupported ordinary review fields")
        alias = request.get("task")
        if alias not in self.state["task_refs"]:
            raise ValueError("unknown task alias")
        manifest = {"request": dict(request), "task_ref": self.state["task_refs"][alias],
                    "project_ref": self.state["project_ref"],
                    "assignment_ref": self.state["assignment_ref"],
                    "generation": self.state["manager_generation"]}
        prior = self._journal(key, "intent")
        if prior is not None:
            if prior["request"] != dict(request):
                raise ValueError("ordinary request key was reused with changed input")
            manifest = prior
        reviewed = self._journal(key, "review")
        if reviewed is None:
            policy = self.policy or self.state["assessment_policy"]
            if isinstance(policy, Mapping):
                policy = LocalAssessmentPolicy.from_run_config(policy, state=self.state)
            commands = self.owner.manager_assessment(project_ref=manifest["project_ref"],
                task_ref=manifest["task_ref"], manager_assignment_ref=manifest["assignment_ref"],
                manager_actor=self.state["manager"], manager_generation=manifest["generation"],
                assessment_policy=policy)
            candidate = commands._ref(request.get("candidate_ref"), "candidate_ref")
            sources = commands._refs(request.get("source_refs"), "source_refs")
            criteria = [criterion for task, criterion in policy.task_criterion_pairs
                        if task.to_dict() == manifest["task_ref"]]
            judgments = request.get("judgments")
            aliases = {alias: ref for alias, ref in self.state["criterion_refs"].items()
                       if ResourceRef.from_dict(ref) in criteria}
            if not isinstance(judgments, Mapping) or set(judgments) != set(aliases):
                raise ValueError("supply explicit judgment for every configured task criterion")
            inspection = request.get("inspection")
            if not isinstance(inspection, Mapping) or not inspection:
                raise ValueError("inspection must contain substantive observed evidence")
            evidence = []
            for criterion_alias, judgment in judgments.items():
                if (not isinstance(judgment, Mapping)
                        or set(judgment) != {"verdict", "rationale", "evidence_refs"}
                        or judgment["verdict"] not in {"PASS", "REWORK", "UNKNOWN"}
                        or not isinstance(judgment["rationale"], str) or not judgment["rationale"].strip()):
                    raise ValueError("each criterion requires verdict, rationale and genuine evidence_refs")
                evidence.extend(commands._refs(judgment["evidence_refs"], "evidence_refs"))
            evidence = list(dict.fromkeys(evidence))
            hashes = {}
            for ref in evidence:
                payload = commands._reader.get_identity(ref).payload
                digest = payload.get("content_digest")
                if ref.kind == "dat.content.document":
                    content = self.owner.content.read(ref)
                    if "content" in content:
                        digest = _digest(content["content"])
                if ref.kind == "wrk.result" and isinstance(payload.get("value"), Mapping):
                    digest = _digest(payload["value"])
                if not isinstance(digest, str) or len(digest) != 64:
                    raise ValueError("evidence has no retained content digest: " + ref.id)
                hashes[ref.kind + ":" + ref.id + ":" + ref.revision] = digest
            self._journal(key, "intent", manifest)
            self.owner.create_manager_assessment_pool(project_ref=manifest["project_ref"],
                task_ref=manifest["task_ref"], manager_assignment_ref=manifest["assignment_ref"],
                manager_actor=self.state["manager"], manager_generation=manifest["generation"],
                logical_request_key="journey-pool:" + policy.pool_ref.id, assessment_policy=policy)

            def execute(operation: str, arguments: Mapping[str, Any], suffix: str, operation_key: str | None = None) -> Any:
                return commands.execute({"operation": operation, "arguments": arguments,
                    "request_key": operation_key or "journey:" + key + ":" + suffix,
                    "expected_task_ref": manifest["task_ref"],
                    "expected_assignment_ref": manifest["assignment_ref"],
                    "expected_generation": manifest["generation"]})["ref"]

            scope_id = "ordinary-" + _digest([manifest["task_ref"], aliases])[:28]
            scope = execute("declare-scope", {"scope_ref": {
                "authority": candidate.authority, "kind": "assessment.scope", "id": scope_id},
                "criterion_refs": list(aliases.values()), "protocol": "ordinary-manager-judgment"}, "scope",
                operation_key="journey-scope:" + scope_id)
            packet = execute("freeze-input", {"scope_ref": scope, "candidate_ref": candidate.to_dict(),
                "criterion_refs": list(aliases.values()), "source_refs": [ref.to_dict() for ref in sources],
                "evidence_refs": [ref.to_dict() for ref in evidence], "packet": inspection}, "input")
            results, gates = [], []
            for criterion_alias, criterion in aliases.items():
                judgment = judgments[criterion_alias]
                common = {"scope_ref": scope, "candidate_ref": candidate.to_dict(), "criterion_ref": criterion}
                execute("select-candidate", {**common, "rationale": judgment["rationale"]},
                        criterion_alias + ":select")
                result = execute("assess", {**common, "input_ref": packet,
                    "verdict": judgment["verdict"], "limit_pool_ref": policy.pool_ref.to_dict(),
                    "protocol_result": {"inspection": inspection, "judgment": judgment}},
                    criterion_alias + ":assess")
                results.append(result)
                if judgment["verdict"] == "PASS":
                    gates.append(execute("accept", {"result_ref": result,
                        "candidate_ref": candidate.to_dict(), "criterion_ref": criterion,
                        "evidence_refs": judgment["evidence_refs"], "rationale": judgment["rationale"]},
                        criterion_alias + ":accept"))
            outcome = ("accepted" if len(gates) == len(aliases) else
                       "unknown" if any(value["verdict"] == "UNKNOWN" for value in judgments.values()) else "rework")
            reviewed = self._journal(key, "review", {"outcome": outcome,
                "candidate_ref": candidate.to_dict(), "result_refs": results, "gate_refs": gates,
                "evidence_refs": [ref.to_dict() for ref in evidence], "evidence_hashes": hashes,
                "provider_called": False, "accounting": "owner_local_bookkeeping"})
        if reviewed["outcome"] == "accepted" and request.get("finish", True):
            return {**reviewed, "completion": self.finish_task({"task": alias,
                "request_key": key + ":finish", "review_key": key})}
        return {**reviewed, "task_completion_recorded": False,
                "next_action": "inspect or correct the evidence and submit new explicit judgment" if reviewed["outcome"] != "accepted"
                else "finish-task with this review_key"}

    def finish_task(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._authorize()
        key = self._key(request)
        if set(request) - {"command", "task", "request_key", "review_key"}:
            raise ValueError("unsupported task finish fields")
        prior = self._journal(key, "finish-intent")
        if prior is not None and prior != dict(request):
            raise ValueError("task finish request key was reused with changed input")
        reviewed = self._journal(request.get("review_key"), "review")
        manifest = self._journal(request.get("review_key"), "intent")
        if reviewed is None or manifest is None or reviewed["outcome"] != "accepted":
            raise ValueError("finish-task requires retained explicit accepted judgment")
        if manifest["request"]["task"] != request.get("task"):
            raise PermissionError("review belongs to another task")
        self._journal(key, "finish-intent", dict(request))
        settlement = self._native_settlement(reviewed)
        if settlement is not None:
            return {"outcome": "pending", "completion_intent": key, "settlement": settlement,
                    "retry_provider": False,
                    "next_action": "settle this retained native occurrence without resending; repeat this exact finish request"}
        if self.due_port is not None:
            active = [due for due in self.due_port.list_due()
                if due.get("role") in {"manager", "worker"} and due.get("stop_state") == "active"
                and due.get("in_flight_request") is not None
                and ((due.get("host_evidence") or {}).get("gateway_attempt")) is not None
                and (due.get("role") == "worker" or (
                    (due.get("assignment_ref") or {}).get("id") == self.state["assignment_ref"]["id"]
                    and due.get("generation") == self.state["manager_generation"]))
                and (due.get("target") or {}).get("task_ref") == manifest["task_ref"]]
            if active:
                return {"outcome": "pending", "completion_intent": key,
                        "settlement_schedule_ids": [due["schedule_id"] for due in active],
                        "retry_provider": False,
                        "next_action": "await or reconcile these exact active role occurrences without resending; owner settlement fulfills the accepted completion intent"}
        result = self.portfolio.complete_task(manifest["project_ref"], manifest["task_ref"],
            self.state["assignment_ref"], actor=self.state["manager"], request_id="journey:" + key,
            expected_generation=self.state["manager_generation"],
            expected_project_revision=manifest["project_ref"]["revision"],
            expected_task_revision=manifest["task_ref"]["revision"], disposition="accepted",
            evidence_refs=reviewed["evidence_refs"], evidence_hashes=reviewed["evidence_hashes"],
            gate_refs=reviewed["gate_refs"], candidate_ref=reviewed["candidate_ref"])
        if result.get("outcome") in {"completed", "replayed"}:
            return result
        return {"outcome": "pending", "completion_intent": key, "owner_result": result,
                "retry_provider": False,
                "next_action": "inspect completion prerequisites; settle retained native evidence if required; repeat this exact finish request"}

    def settle_completion_intents(self) -> list[Mapping[str, Any]]:
        """Fulfill already accepted explicit finishes after native owner settlement."""
        self._authorize()
        assignment = ResourceRef.from_dict(self.state["assignment_ref"])
        reports = self.owner.assignments.command_port.list_observations(assignment, kind="report")
        results = []
        for report in reports:
            value = report.value
            if (value.get("schema") != "otto.manager-journey.v1"
                    or not value.get("logical_request_key", "").endswith(":finish-intent")):
                continue
            request = value["content"]
            manifest = self._journal(request["review_key"], "intent")
            if (manifest is None or manifest["assignment_ref"] != self.state["assignment_ref"]
                    or manifest["generation"] != self.state["manager_generation"]):
                continue
            results.append({"request_key": request["request_key"], "result": self.finish_task(request)})
        return results

    def _native_settlement(self, reviewed: Mapping[str, Any]) -> Any:
        candidate = ResourceRef.from_dict(reviewed["candidate_ref"])
        if candidate.kind != "wrk.result":
            return None
        payload = self.owner.graph.reader.get_identity(candidate).payload.get("value") or {}
        if self.due_port is None:
            return {"outcome": "held", "reason": "native settlement readback is not bound to this owner service"}
        due_records = [due for due in self.due_port.list_due()
            if (due.get("assignment_ref") or {}).get("id") == (payload.get("assignment_ref") or {}).get("id")
            and due.get("generation") == payload.get("generation")
            and payload.get("logical_request_key") in {due.get("in_flight_request"), due.get("last_completed_request")}
            and (due.get("target") or {}).get("task_ref") == payload.get("task_ref")
            and (due.get("target") or {}).get("project_ref") == payload.get("project_ref")]
        if len(due_records) != 1:
            return {"outcome": "held", "reason": "native evidence does not identify one exact owner occurrence"}
        due = due_records[0]
        if due.get("stop_state") == "completed" and due.get("completion_state") == "succeeded":
            return None
        result = ((due.get("host_evidence") or {}).get("gateway_attempt") or {}).get("result") or {}
        settled = None
        if result.get("outcome") == "succeeded" and callable(self.settle_execution):
            settled = self.settle_execution(due)
            due = self.due_port.read_due(due["schedule_id"])
            if due.get("stop_state") == "completed" and due.get("completion_state") == "succeeded":
                return None
        return {"outcome": "pending", "schedule_id": due["schedule_id"],
                "completion_state": due.get("completion_state"), "owner_settlement": settled,
                "retry_provider": False}

    def finish_project(self, request: Mapping[str, Any], *, orchestrator_principal: str | None = None,
                       observe_schedules: Any = None) -> Mapping[str, Any]:
        """Use the existing owner-delegated pending-project close, never task coercion.

        The service must explicitly bind an orchestrator and a read-only schedule
        observer. These are host capabilities, not transport arguments. Runtime
        uncertainty stays pending after the actual project lifecycle transition.
        """
        self._authorize()
        key = self._key(request)
        if set(request) - {"command", "request_key", "dispositions"}:
            raise ValueError("unsupported project finish fields")
        if not isinstance(orchestrator_principal, str) or not orchestrator_principal.strip() or not callable(observe_schedules):
            return {"outcome": "held", "project_completion_recorded": False,
                    "reason": "owner service must bind project closeout orchestrator and schedule observer",
                    "provider_called": False}
        project_ref = ResourceRef.from_dict(self.state["project_ref"])
        project = self.owner.graph.reader.get_identity(ResourceRef(project_ref.authority, project_ref.kind, project_ref.id))
        tasks = self.owner.graph.list(project=project.ref, kind="task")
        if not tasks or any(task.lifecycle.value != "completed" or not isinstance(task.payload.get("completion"), Mapping)
                            for task in tasks):
            return {"outcome": "held", "project_completion_recorded": False,
                    "reason": "all actual project tasks require committed completion evidence",
                    "provider_called": False}
        dispositions = request.get("dispositions")
        if not isinstance(dispositions, Mapping) or set(dispositions) != {"acceptance", "publication", "remote", "runtime"}:
            raise ValueError("supply acceptance/publication/remote/runtime dispositions")
        for name, disposition in dispositions.items():
            if (not isinstance(disposition, Mapping) or disposition.get("status") not in {"passed", "verified", "qualified"}
                    or not isinstance(disposition.get("rationale"), str) or not disposition["rationale"].strip()):
                raise ValueError(name + " requires a qualified disposition and substantive rationale")
        intent = {"request": dict(request), "orchestrator_principal": orchestrator_principal,
                  "task_refs": [task.ref.to_dict() for task in tasks]}
        self._journal(key, "project-intent", intent)
        lifecycle = self.owner.lifecycle.command_port
        effects = []

        def transition(action: str, **values: Any) -> Any:
            current = self.owner.graph.reader.get_identity(ResourceRef(project.ref.authority, project.ref.kind, project.ref.id))
            result = lifecycle.transition(current.ref, action=action,
                logical_request_key="journey:" + key + ":" + action,
                expected_project_revision=current.ref.revision, expected_project_version=current.version,
                generation=self.state["manager_generation"], manager_assignment=self.state["assignment_ref"],
                task_refs=intent["task_refs"], actor=self.owner.owner_actor, **values)
            effects.append(json_value(result))
            return result

        control = project.payload.get("lifecycle_control") or {}
        attribution = control.get("owner_attribution")
        if attribution is None:
            transition("pm-bind-existing", orchestrator_principal=orchestrator_principal,
                       owner_attribution={"orchestrator": {"principal": orchestrator_principal}})
            project = self.owner.graph.reader.get_identity(ResourceRef(project.ref.authority, project.ref.kind, project.ref.id))
            control = project.payload["lifecycle_control"]
            attribution = control["owner_attribution"]
        if attribution["orchestrator"]["principal"] != orchestrator_principal:
            raise PermissionError("project closeout orchestrator differs from the owner attribution")
        common = {"attribution_digest": attribution["digest"]}
        if project.payload.get("lifecycle") != "completed":
            if not control.get("close_request"):
                transition("pm-manager-close-request", **common)
            current = self.owner.graph.reader.get_identity(ResourceRef(project.ref.authority, project.ref.kind, project.ref.id))
            evidence = {"project_ref": current.ref.to_dict(), **dict(dispositions)}
            evidence["acceptance"] = {**dict(dispositions["acceptance"]), "task_refs": intent["task_refs"]}
            transition("pm-orchestrator-close", **common,
                orchestrator_assignment=attribution["orchestrator"]["assignment_ref"], evidence=evidence)
        observation = observe_schedules(project.ref.id)
        current = self.owner.graph.reader.get_identity(ResourceRef(project.ref.authority, project.ref.kind, project.ref.id))
        reconciled = (current.payload.get("lifecycle_control") or {}).get("reconciliation")
        if not isinstance(reconciled, Mapping) or reconciled.get("status") != "reconciled":
            settlement = transition("pm-reconcile-no-owned-schedule", **common,
                orchestrator_assignment=attribution["orchestrator"]["assignment_ref"],
                schedule_observation=observation)
            reconciled = (settlement.get("read") or {}).get("reconciliation")
        current = self.owner.graph.reader.get_identity(ResourceRef(project.ref.authority, project.ref.kind, project.ref.id))
        readback = json_value(lifecycle.read_current(current.ref))
        settled = isinstance(reconciled, Mapping) and reconciled.get("status") == "reconciled"
        return {"outcome": "completed" if settled and readback.get("lifecycle") == "completed" else "pending",
                "project_completion_recorded": readback.get("lifecycle") == "completed",
                "settlement_pending": not settled, "readback": readback, "effects": effects,
                "provider_called": False, "retry_provider": False}
