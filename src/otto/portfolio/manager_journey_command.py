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

    def review_input(self, alias: str) -> Mapping[str, Any]:
        """Expose the exact retained worker observation, never an automatic PASS."""
        self._authorize()
        worker = (self.state.get("workers") or {}).get(alias)
        if alias not in self.state["task_refs"] or not isinstance(worker, Mapping) or self.due_port is None:
            return {"outcome": "held", "provider_called": False,
                    "reason": "no retained worker handle for this task; admit actual candidate content through the owner"}
        due = self.due_port.read_due(worker["schedule_id"]) or {}
        result = ((due.get("host_evidence") or {}).get("gateway_attempt") or {}).get("result") or {}
        assignment = self.owner.assignments.command_port.get(ResourceRef.from_dict(worker["assignment_ref"]))
        task_ref = self.state["task_refs"][alias]
        same_identity = lambda a, b: isinstance(a, Mapping) and isinstance(b, Mapping) and all(
            a.get(key) == b.get(key) for key in ("authority", "kind", "id"))
        if (assignment.ref.to_dict() != worker["assignment_ref"]
                or assignment.principal != worker["principal"] or assignment.payload.get("manager") != self.state["manager"]
                or assignment.generation != worker["generation"] or due.get("assignment_ref") != worker["assignment_ref"]
                or due.get("generation") != worker["generation"]
                or not same_identity(result.get("task_ref"), task_ref)
                or not same_identity(result.get("project_ref"), self.state["project_ref"])):
            raise PermissionError("review input worker/task/project assignment binding differs")
        if (due.get("stop_state") != "completed" or due.get("completion_state") != "succeeded"
                or due.get("in_flight_request") is not None or result.get("outcome") != "succeeded"
                or result.get("context_digest_verified") is not True):
            return {"outcome": "pending", "schedule_id": worker["schedule_id"], "provider_called": False,
                    "retry_provider": False, "reason": "inspect or settle this exact worker occurrence before judging it"}
        observations = [item for item in self.owner.assignments.command_port.list_observations(assignment.ref, kind="result")
                        if json_value(item.value) == result]
        if len(observations) != 1:
            raise ValueError("retained worker result does not identify one exact canonical observation")
        ref = observations[0].ref.to_dict()
        task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(task_ref))
        return {"outcome": "read", "task_ref": task_ref, "task_outcome": task.payload.get("outcome"),
                "schedule_id": worker["schedule_id"], "candidate_ref": ref, "source_refs": [ref], "evidence_refs": [ref],
                "worker_result_sha256": _digest(result), "observed_turn_id": result.get("observed_turn_id"),
                "physical_session_id": result.get("physical_session_id"), "provider_called": False,
                "acceptance": "unjudged retained worker result; inspect actual artifact paths/content and criterion before review-task",
                "next_action": "Use these exact refs for review-task after substantive inspection. Instruction GUIDE/MANDATE refs are context, not delivered artifact candidates. Preserve completed tasks, decisions and budget use; this read does not authorize another review or worker replay."}

    def _instruction_document(self, ref: ResourceRef) -> bool:
        if ref.kind != "dat.content.document":
            return False
        value = self.owner.content.read(ref)
        content = value.get("content") or (value.get("revision") or {}).get("content") or {}
        document = value.get("document") or {}
        return (document.get("role") == "mandate" or isinstance(content, Mapping) and
                (content.get("schema") == "herzchen.instructions.v1" or "instruction_contract" in content))

    def _completed_task_corrections(self, project: Any, tasks: list[Any]) -> tuple[set[str], list[Mapping[str, Any]]]:
        """Validate owner-designated corrective obligations without rewriting PASS.

        Public sheet metadata names immutable owner SOURCE documents. A link
        alone is never acceptance: the corrective task must have genuinely
        completed against every designated criterion using its retained worker
        result. Old tasks, judgments and consumed allowance remain history.
        """
        refs = (project.payload.get("metadata") or {}).get("owner_task_corrections", [])
        if not isinstance(refs, list) or len(refs) > 16:
            raise ValueError("owner task corrections require at most 16 pinned SOURCE references")
        by_id = {task.ref.id: task for task in tasks}
        covered, evidence = set(), []
        same_identity = lambda a, b: all(a.get(key) == b.get(key) for key in ("authority", "kind", "id"))
        for raw in refs:
            ref = ResourceRef.from_dict(raw)
            value = self.owner.content.read(ref)
            metadata = self.owner.content.read(ResourceRef(ref.authority, ref.kind, ref.id))
            document, content = metadata.get("document") or {}, value.get("content") or {}
            author = (metadata.get("revision") or {}).get("author") or {}
            if (ref.kind != "dat.content.document" or not ref.revision
                    or json_value(metadata.get("current_revision")) != ref.to_dict()
                    or document.get("role") != "SOURCE" or document.get("maintainer") != self.state["owner"]
                    or author.get("actor") != self.state["owner"] or author.get("authenticated") is not True
                    or not same_identity(json_value(document.get("authoring_scope") or {}), project.ref.to_dict())
                    or content.get("schema") != "otto.completed-task-correction.v1"
                    or content.get("owner_actor") != self.state["owner"]
                    or not same_identity(content.get("project_ref") or {}, project.ref.to_dict())):
                raise PermissionError("task correction must be a current project-scoped immutable owner SOURCE")
            designated = ResourceRef.from_dict(content["corrective_task_ref"])
            corrective = by_id.get(designated.id)
            replaces, criteria = content.get("replaces"), content.get("criterion_refs")
            if (corrective is None or designated.authority != project.ref.authority or designated.kind != "work.task"
                    or not isinstance(replaces, list) or not replaces or len(replaces) > 16
                    or not isinstance(criteria, list) or not criteria
                    or _digest(corrective.payload.get("outcome")) != content.get("corrective_outcome_sha256")):
                raise ValueError("task correction has invalid corrective task/outcome/criterion coverage")
            old_ids = []
            required = []
            for item in replaces:
                old_ref = ResourceRef.from_dict(item["task_ref"])
                old = by_id.get(old_ref.id)
                completion = old.payload.get("completion") if old else None
                if (old is None or old.ref != old_ref or old_ref.id == designated.id
                        or old.lifecycle.value != "completed" or not isinstance(completion, Mapping)
                        or _digest(completion) != item.get("completion_sha256")
                        or json_value(completion.get("gate_refs")) != item.get("gate_refs")
                        or old_ref.id in covered or old_ref.id in old_ids):
                    raise ValueError("task correction does not pin distinct preserved completed obligations")
                actual_criteria = [json_value(self.owner.graph.reader.get_identity(ResourceRef.from_dict(gate)).payload["criterion_ref"])
                                   for gate in item["gate_refs"]]
                if item.get("criterion_refs") != actual_criteria:
                    raise ValueError("task correction does not cover the original accepted criterion obligations")
                required.extend(actual_criteria)
                old_ids.append(old_ref.id)
            if {json.dumps(item, sort_keys=True) for item in required} != {json.dumps(item, sort_keys=True) for item in criteria}:
                raise ValueError("corrective criteria must exactly cover the designated original obligations")
            completion = corrective.payload.get("completion")
            if corrective.lifecycle.value != "completed" or not isinstance(completion, Mapping):
                continue
            candidate = ResourceRef.from_dict(completion["candidate_ref"])
            payload = self.owner.graph.reader.get_identity(candidate).payload.get("value") or {}
            if (completion.get("task_ref") != designated.to_dict() or candidate.kind != "wrk.result"
                    or payload.get("outcome") != "succeeded" or payload.get("context_digest_verified") is not True
                    or payload.get("task_ref") != designated.to_dict()
                    or candidate.to_dict() not in json_value(completion.get("evidence_refs", []))
                    or completion.get("evidence_hashes", {}).get(candidate.kind + ":" + candidate.id + ":" + candidate.revision) != _digest(payload)
                    or self._native_settlement(completion) is not None):
                raise ValueError("corrective completion requires genuine exact settled worker candidate evidence")
            accepted = []
            for gate in completion["gate_refs"]:
                decision = self.owner.graph.reader.get_identity(ResourceRef.from_dict(gate)).payload
                result = self.owner.graph.reader.get_identity(ResourceRef.from_dict(decision["result_ref"])).payload
                if (decision.get("disposition") != "accept" or decision.get("candidate_ref") != candidate.to_dict()
                        or result.get("verdict") != "PASS" or result.get("candidate_ref") != candidate.to_dict()
                        or result.get("parent_obligation_ref") != designated.to_dict()):
                    raise ValueError("corrective acceptance does not bind the exact task/candidate")
                accepted.append(json_value(decision["criterion_ref"]))
            if {json.dumps(item, sort_keys=True) for item in accepted} != {json.dumps(item, sort_keys=True) for item in criteria}:
                raise ValueError("corrective completion lacks accepted coverage of every designated obligation")
            covered.update(old_ids)
            evidence.append({"correction_ref": ref.to_dict(), "correction_sha256": _digest(content),
                             "preserved_task_refs": [item["task_ref"] for item in replaces],
                             "corrective_task_ref": corrective.ref.to_dict(), "candidate_ref": candidate.to_dict(),
                             "gate_refs": json_value(completion["gate_refs"])})
        return covered, evidence

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
            existing_scope = commands.required_scope(require=False)
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
            if self._instruction_document(candidate) or candidate not in evidence:
                raise ValueError("ordinary review requires the actual artifact/result candidate in evidence_refs; "
                    "GUIDE/MANDATE instruction documents cannot substitute for delivered work. "
                    "Use review-input --task to discover retained worker refs, then inspect the artifact and exact task outcome.")
            for judgment in judgments.values():
                if any(char in judgment["rationale"] for char in ("/", "\\", "\x00")):
                    raise ValueError("rationale is an assessment identifier: use nonblank text without slash, backslash or NUL; "
                                     "put paths and substantive inspection prose in inspection")
            hashes = {}
            for ref in evidence:
                payload = commands._reader.get_identity(ref).payload
                digest = payload.get("content_digest")
                if ref.kind == "dat.content.document":
                    content = self.owner.content.read(ref)
                    if "content" in content:
                        digest = _digest(content["content"])
                # Both public observation kinds retain their immutable body in
                # value. Help replies/application reports are substantive
                # evidence alongside worker results, not instruction packets.
                if ref.kind in {"wrk.result", "wrk.report"} and isinstance(payload.get("value"), Mapping):
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
            scope = (existing_scope.ref.to_dict() if existing_scope is not None else
                execute("declare-scope", {"scope_ref": {
                    "authority": candidate.authority, "kind": "assessment.scope", "id": scope_id},
                    "criterion_refs": list(aliases.values()), "protocol": "ordinary-manager-judgment"}, "scope",
                    operation_key="journey-scope:" + scope_id))
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
        corrected, correction_evidence = self._completed_task_corrections(project, tasks)
        invalid = []
        for task in tasks:
            completion = task.payload["completion"]
            candidate = ResourceRef.from_dict(completion["candidate_ref"]) if completion.get("candidate_ref") else None
            if task.ref.id not in corrected and (candidate is None or self._instruction_document(candidate)
                    or candidate.to_dict() not in json_value(completion.get("evidence_refs", []))):
                invalid.append(task.ref.to_dict())
        if invalid:
            return {"outcome": "held", "project_completion_recorded": False, "provider_called": False,
                    "reason": "recorded task completion does not retain genuine artifact/result candidate evidence",
                    "task_refs": invalid,
                    "next_action": "Inspect review-input and the retained judgments/completion evidence. Preserve historical decisions and budget use; resolve the provenance/outcome discrepancy through an authorized owner correction before project acceptance. Do not blindly re-review or replay workers."}
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
            if correction_evidence:
                evidence["acceptance"]["completed_task_corrections"] = correction_evidence
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
