"""Ordinary judgment and finish composed over existing canonical owner APIs."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from herzchen.kernel.history import HISTORY_SCHEMA
from .local_assessment_policy import LocalAssessmentPolicy
from .owner_readers import json_value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _same_identity(left: Any, right: Any) -> bool:
    return (isinstance(left, Mapping) and isinstance(right, Mapping)
            and all(left.get(key) == right.get(key) for key in ("authority", "kind", "id")))


class ReviewInputSchemaError(ValueError):
    """Only the explicit pre-journal input validation boundary uses this type."""
    def __init__(self, field: str, message: str, *, allowed_values=None):
        super().__init__(message)
        self.refusal = {"outcome": "rejected", "effects_started": False,
            "provider_called": False, "retry_provider": False,
            "error": {"kind": "input", "code": "review_input_schema", "field": field,
                "message": message, "allowed_values": allowed_values},
            "next_action": "Correct this input using review-input; preserve the original request receipt. No review journal or assessment reservation was started."}


class ManagerJourneyCommands:
    """Trusted service composition; transport input cannot select an actor or pool."""

    def __init__(self, *, owner: Any, portfolio: Any, state: Mapping[str, Any], policy: Any = None,
                 due_port: Any = None, settle_execution: Any = None,
                 native_bodies: Any = None) -> None:
        self.owner, self.portfolio, self.state = owner, portfolio, state
        self.policy = policy
        self.due_port, self.settle_execution = due_port, settle_execution
        self.native_bodies = native_bodies  # Trusted owner composition, never request input.

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

    def _journal(self, key: str, stage: str, value: Any = None, *, adopted_history: bool = False) -> Any:
        if value is None and stage in {"review", "intent", "finish-intent"}:
            from completion_intent_selection import read_journal
            return read_journal(self, key, stage, adopted_history=adopted_history)
        actor = self._authorize()
        port = self.owner.assignments.command_port
        assignment = ResourceRef.from_dict(self.state["assignment_ref"])
        identity = "journey:" + key + ":" + stage
        reports = port.list_observations(assignment, kind="report")
        prior = next((report.value for report in reports
                      if report.value.get("logical_request_key") == identity), None)
        if prior is None and adopted_history and value is None and stage in {"review", "intent", "finish-intent"}:
            # A resource adoption revises the assignment, while an accepted
            # review remains pinned to the original generation. Resolve only
            # this exact immutable journal ID through authenticated adoption
            # events; never treat reassignment as continuation of acceptance.
            record_id = "report-" + hashlib.sha256((assignment.id + ":" + identity).encode()).hexdigest()[:28]
            record = self.owner.graph.reader.get_identity(ResourceRef(assignment.authority, "wrk.report", record_id))
            current = port.get(assignment)
            ancestors = self._adopted_assignment_refs(assignment)
            if (record is not None and record.payload.get("generation") == current.generation
                    and record.payload.get("observation_kind") == "report"
                    and ResourceRef.from_dict(record.payload["assignment"]) in ancestors):
                candidate = record.payload.get("value", {})
                if candidate.get("schema") == "otto.manager-journey.v1" and candidate.get("logical_request_key") == identity:
                    prior = candidate
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

    def _adopted_assignment_refs(self, assignment: ResourceRef) -> tuple[ResourceRef, ...]:
        """Exact same-generation resource-adoption lineage, never reassignment."""
        current = self.owner.assignments.command_port.get(assignment)
        refs = [assignment]
        events = {event.subject: event for event in self.owner.graph.reader.list_events(stream="assignment:" + assignment.id)
                  if event.event_type == "work.assignment.resources-adopted"}
        cursor = assignment
        while cursor in events:
            if len(refs) >= 32:
                raise PermissionError("completion adoption lineage exceeds finite bound")
            event = events[cursor]
            payload = event.effects.get("result_payload", {})
            base = payload.get("resource_adoption_base_ref")
            if (not isinstance(base, Mapping) or payload.get("generation") != current.generation
                    or payload.get("principal") != current.principal or payload.get("role") != "manager"
                    or payload.get("scope") != current.scope.to_dict()
                    or payload.get("manager") != current.payload.get("manager")
                    or event.actor.actor != (current.payload.get("manager") or current.principal)):
                break
            predecessor = ResourceRef.from_dict(base)
            if (predecessor.authority, predecessor.kind, predecessor.id) != (assignment.authority, assignment.kind, assignment.id) or predecessor in refs:
                break
            refs.append(predecessor)
            cursor = predecessor
        return tuple(refs)


    def _key(self, request: Mapping[str, Any]) -> str:
        key = request.get("request_key")
        if not isinstance(key, str) or not key.strip() or key != key.strip() or len(key) > 160:
            raise ValueError("request_key must be 1..160 exact characters")
        return key

    def author_tasks(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Manager decisions and pending work through the existing sheet; no dispatch.

        A review is evidence, never task or budget authority. The manager's
        report retains dispositions, then the typed batch retains its own
        receipt. Reusing the exact key can finish local alias readback after
        a committed batch without repeating canonical work.
        """
        self._authorize()
        if set(request) != {"command", "request_key", "base_revision", "review_ref", "dispositions", "tasks"}:
            raise ValueError("task authoring requires exact planning fields")
        key = self._key(request)
        original = self._journal(key, "planning-input")
        if original is not None and original != dict(request):
            raise ValueError("planning key was reused with changed input")
        review_ref = ResourceRef.from_dict(request["review_ref"])
        if review_ref.kind not in {"wrk.report", "wrk.result"} or not review_ref.revision:
            raise ValueError("review_ref must pin an existing report or result")
        record = self.owner.graph.reader.get_identity(review_ref)
        if record is None or record.ref != review_ref:
            raise PermissionError("review evidence is not the exact retained record")
        assignment = self.owner.assignments.command_port.get(record.payload["assignment"])
        project = ResourceRef.from_dict(self.state["project_ref"])
        scope = assignment.scope
        if scope.kind == "work.task":
            task = self.owner.graph.reader.get_identity(ResourceRef(scope.authority, scope.kind, scope.id))
            if task is None or task.ref != scope:
                raise PermissionError("review evidence task scope is missing or stale")
            scope = ResourceRef.from_dict(task.payload["project_ref"])
        if (scope.authority, scope.kind, scope.id) != (project.authority, project.kind, project.id):
            raise PermissionError("review evidence belongs to another project")
        dispositions, tasks = request["dispositions"], request["tasks"]
        if not isinstance(dispositions, list) or not dispositions or len(dispositions) > 32:
            raise ValueError("supply 1..32 explicit finding dispositions")
        seen = set()
        for item in dispositions:
            if not isinstance(item, Mapping) or set(item) - {"finding_id", "decision", "reason", "task", "route", "routing_rationale", "revisit"}:
                raise ValueError("unsupported finding disposition fields")
            finding = item.get("finding_id")
            if not isinstance(finding, str) or not finding.strip() or finding in seen:
                raise ValueError("finding IDs must be nonblank and unique")
            seen.add(finding)
            if item.get("decision") not in {"accept", "merge", "defer", "reject"} or not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise ValueError("each disposition requires a decision and reason")
            if item["decision"] in {"accept", "merge"}:
                if (not isinstance(item.get("task"), str) or not item["task"].strip()
                        or item.get("route") not in {"normal", "xhard"}
                        or not isinstance(item.get("routing_rationale"), str) or not item["routing_rationale"].strip()):
                    raise ValueError("accepted correction needs a task and independent normal/XHARD rationale")
            elif item["decision"] == "defer" and (not isinstance(item.get("revisit"), str) or not item["revisit"].strip()):
                raise ValueError("deferred finding needs its concrete revisit condition")
        if not isinstance(tasks, list) or len(tasks) > 32:
            raise ValueError("tasks must be a bounded typed sheet batch")
        sheet = self.portfolio.operations.sheet_port
        sheet.validate_edit({"tasks": tasks})  # Protected fields fail before journal or batch.
        keys = []
        for task in tasks:
            alias = task.get("id", task.get("alias"))
            if not isinstance(alias, str) or not alias.strip() or alias in keys:
                raise ValueError("each authored task needs one unique alias or existing ID")
            keys.append(alias)
            if task.get("lifecycle", "pending") != "pending" or task.get("withdraw"):
                raise ValueError("correction authoring only creates/edits pending work")
        for item in dispositions:
            if item["decision"] in {"accept", "merge"} and item["task"] not in set(keys) | set(self.state["task_refs"]):
                raise ValueError("accepted finding must name an existing or authored task")
        retained = self._journal(key, "planning-authored")
        if original is None and request["base_revision"] != project.revision:
            raise PermissionError("planning base does not match the current project")
        self._journal(key, "planning-input", dict(request))
        if retained is None:
            if tasks:
                result = self.portfolio.author_task_list(project, tasks, actor=self.state["manager"],
                    request_id="journey:" + key + ":tasks", base_revision=request["base_revision"])
                if result.get("outcome") != "authored":
                    return result  # Exact input is retained; no readiness or quota was granted.
            else:
                result = {"outcome": "authored", "project_ref": project.to_dict(), "task_refs": {}, "task_count": 0}
            retained = self._journal(key, "planning-authored", result)
        self.state["project_ref"] = retained["project_ref"]
        for alias, value in retained["task_refs"].items():
            current = self.owner.graph.reader.get_identity(ResourceRef.from_dict(value))
            if current is None or current.payload.get("project_ref", {}).get("id") != project.id:
                raise PermissionError("authored task readback is outside the current project")
            old = self.state["task_refs"].get(alias)
            if old is not None and old["id"] != current.ref.id:
                raise PermissionError("authored alias would replace an unrelated current task")
            # A typed edit may select the canonical ID instead of its local
            # alias. Refresh every existing alias of that exact identity;
            # retained worker/assignment pins remain untouched.
            for existing_alias, existing_ref in tuple(self.state["task_refs"].items()):
                if all(existing_ref[name] == current.ref.to_dict()[name] for name in ("authority", "kind", "id")):
                    self.state["task_refs"][existing_alias] = current.ref.to_dict()
            self.state["task_refs"][alias] = current.ref.to_dict()
        return {**retained, "dispositions": dispositions, "provider_called": False, "dispatch": False, "launch": False,
                "readiness_granted": False, "assessment_authority_granted": False,
                "next_action": "Inspect current task readiness and adopted scope before normal/XHARD run-worker. Missing acceptance scope, allowance or role-context adoption requires the existing owner setup path; task authoring grants none."}

    def _review_criteria(self, task_ref: Mapping[str, Any], policy: LocalAssessmentPolicy) -> dict[str, Any]:
        criteria = {criterion for task, criterion in policy.task_criterion_pairs
                    if task.to_dict() == task_ref}
        aliases = {name: ref for name, ref in self.state["criterion_refs"].items()
                   if ResourceRef.from_dict(ref) in criteria}
        if (not criteria or {ResourceRef.from_dict(ref) for ref in aliases.values()} != criteria
                or len(aliases) > 256 or any(not isinstance(name, str) or not name
                                            or len(name) > 256 for name in aliases)):
            raise PermissionError("configured criterion alias coverage is incomplete or exceeds the finite read contract; "
                                  "accountable owner must reconcile the policy mapping before review")
        return aliases

    @staticmethod
    def _inspection_schema() -> dict[str, Any]:
        return {"type": "object", "min_properties": 1,
                "example": {"observed": "Your substantive inspection of the exact retained candidate"},
                "authority": "input shape only; no verdict or review allowance"}

    @staticmethod
    def _judgment_schema() -> dict[str, Any]:
        return {"type": "object", "keys": "every configured criterion alias exactly once",
                "required_fields": ["verdict", "rationale", "evidence_refs"],
                "verdict_enum": ["PASS", "REWORK", "UNKNOWN"],
                "rationale": "nonblank assessment identifier without slash, backslash or NUL; substantive prose belongs in inspection",
                "example": {"CRITERION_ALIAS": {"verdict": "PASS", "rationale": "inspected-candidate",
                    "evidence_refs": [{"authority": "OWN_AUTHORITY", "kind": "wrk.result",
                        "id": "EXACT_CANDIDATE_ID", "revision": "EXACT_REVISION"}]}},
                "authority": "input shape only; PASS requires your independent favorable inspection"}

    def _review_policy(self, alias: str, *, validate_current: bool = True,
                       completed_task_ref: Mapping[str, Any] | None = None) -> LocalAssessmentPolicy:
        """Use an owner-issued task supplement without changing setup/base authority."""
        configured = self.policy or self.state["assessment_policy"]
        policy_state = self.state
        if completed_task_ref is not None:
            # Only review_task supplies this after _completed_finish proves the
            # exact committed predecessor. It is never a new assessment pin.
            policy_state = {**self.state, "task_refs": {**self.state["task_refs"], alias: completed_task_ref}}
        supplements = self.state.get("task_assessment_supplements", {})
        if not isinstance(supplements, Mapping) or len(supplements) > 64:
            raise PermissionError("trusted task assessment supplements are malformed")
        supplemental = supplements.get(alias)
        if supplemental is not None:
            if not isinstance(supplemental, Mapping) or set(supplemental) != {"policy", "binding"}:
                raise PermissionError("task assessment supplement requires exact policy/binding")
            base_policy = (LocalAssessmentPolicy.from_run_config(configured, state=policy_state)
                           if isinstance(configured, Mapping) else configured)
            configured = supplemental["policy"]
            policy = LocalAssessmentPolicy.from_run_config(configured, state=policy_state)
            binding = supplemental["binding"]
            current = self.owner.assignments.command_port.get(ResourceRef.from_dict(self.state["assignment_ref"]))
            from .operating_setup import authenticated_adoption_ancestor
            project = ResourceRef.from_dict(self.state["project_ref"])
            task = ResourceRef.from_dict(policy_state["task_refs"][alias])
            if (not isinstance(binding, Mapping)
                    or binding.get("project_ref") != project.to_dict()
                    or binding.get("task_ref") != task.to_dict()
                    or binding.get("generation") != current.generation
                    or binding.get("principal") != current.principal
                    or not isinstance(binding.get("assignment_ref"), Mapping)
                    or not authenticated_adoption_ancestor({"ref": current.ref.to_dict(),
                        "principal": current.principal, "role": current.role,
                        "generation": current.generation, "payload": current.payload},
                        binding["assignment_ref"], self.owner.graph.reader)
                    or any(member != task for member, _ in policy.task_criterion_pairs)
                    or set(policy.task_criterion_pairs) != {pair for pair in base_policy.task_criterion_pairs if pair[0] == task}
                    or binding.get("pool_ref") != policy.pool_ref.to_dict()
                    or binding.get("criterion_refs") != [criterion.to_dict() for _, criterion in policy.task_criterion_pairs]):
                raise PermissionError("task assessment supplement binding is stale or foreign")
            allocation_key = binding.get("allocation_key")
            receipt = self.owner.graph.reader.get_receipt(allocation_key) if isinstance(allocation_key, str) else None
            if (receipt is None or receipt.status.value != "committed"
                    or receipt.target.authority != policy.pool_ref.authority
                    or receipt.target.kind != policy.pool_ref.kind or receipt.target.id != policy.pool_ref.id):
                raise PermissionError("task assessment supplement lacks exact committed owner allocation")
            pool = self.owner.graph.reader.get_identity_bounded(policy.pool_ref, max_record_bytes=8192)["record"]
            if (pool is None or pool.payload.get("capacity_units") != policy.capacity_units
                    or pool.payload.get("cumulative_allowance_units") != policy.cumulative_allowance_units):
                raise PermissionError("task assessment supplement pool metadata differs")
        else:
            policy = (LocalAssessmentPolicy.from_run_config(configured, state=policy_state)
                      if isinstance(configured, Mapping) else configured)
        if validate_current:
            policy.validate_binding(ResourceRef.from_dict(self.state["project_ref"]),
                                    ResourceRef.from_dict(self.state["task_refs"][alias]), self.owner.graph.reader)
        return policy

    def _review_policy_pin(self, alias: str, policy: LocalAssessmentPolicy) -> Mapping[str, Any]:
        supplement = self.state.get("task_assessment_supplements", {}).get(alias)
        value = {"pool_ref": policy.pool_ref.to_dict(), "project_ref": policy.scope_project_ref.to_dict(),
                 "task_criterion_pairs": [{"task_ref": task.to_dict(), "criterion_ref": criterion.to_dict()}
                    for task, criterion in policy.task_criterion_pairs],
                 "purpose": policy.purpose, "local_only": policy.local_only,
                 "capacity_units": policy.capacity_units,
                 "cumulative_allowance_units": policy.cumulative_allowance_units,
                 "allocation_key": supplement["binding"]["allocation_key"] if supplement else None,
                 "source": "owner-issued-task-supplement" if supplement else "trusted-global-policy"}
        return {**value, "canonical_json_sha256": _digest(value)}

    def review_input(self, alias: str) -> Mapping[str, Any]:
        """Expose the exact retained worker observation, never an automatic PASS."""
        self._authorize()
        if alias not in self.state["task_refs"]:
            raise ValueError("unknown task alias; use a current configured task alias")
        task_ref = self.state["task_refs"][alias]
        task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(task_ref))
        if task is None or task.ref.to_dict() != task_ref:
            return self._completed_review_read(alias, task_ref, task,
                reason="current task completion read is unavailable at its exact retained revision")
        lifecycle = task.payload.get("lifecycle")
        if getattr(task, "lifecycle", None) is not None:
            lifecycle = getattr(task.lifecycle, "value", task.lifecycle)
        if lifecycle == "completed":
            # Completion is the authoritative historical anchor.  Do not
            # require a current policy map or worker pointer just to present
            # a committed completion, and never call it unjudged.
            return self._completed_review_read(alias, task_ref, task)
        policy = self._review_policy(alias)
        contract = {"assessment_policy_selection": self._review_policy_pin(alias, policy),
                    "criterion_aliases": self._review_criteria(self.state["task_refs"][alias], policy),
                    "inspection_schema": self._inspection_schema(), "judgment_schema": self._judgment_schema()}
        worker = (self.state.get("workers") or {}).get(alias)
        if not isinstance(worker, Mapping) or self.due_port is None:
            return {**contract, "outcome": "held", "provider_called": False,
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
            return {**contract, "outcome": "pending", "schedule_id": worker["schedule_id"], "provider_called": False,
                    "retry_provider": False, "reason": "inspect or settle this exact worker occurrence before judging it"}
        from .occurrence_reads import handle
        occurrence = handle(due)
        observations = []
        for item in self.owner.assignments.command_port.list_observations(assignment.ref, kind="result"):
            value = json_value(item.value)
            # Due and WRK store the same immutable native bodies as refs. Compare
            # their original semantic value through the issued Evidence reader;
            # retain the observation ref and do not rewrite either record.
            if self.native_bodies is not None and isinstance(value, Mapping):
                value = self.native_bodies.unpack_due(value)
            if value == result:
                observations.append(item)
        if len(observations) != 1:
            raise ValueError("retained worker result does not identify one exact canonical observation")
        ref = observations[0].ref.to_dict()
        task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(task_ref))
        return {**contract, "outcome": "read", "task_ref": task_ref, "task_outcome": task.payload.get("outcome"),
                "occurrence": occurrence,
                "schedule_id": worker["schedule_id"], "candidate_ref": ref, "source_refs": [ref], "evidence_refs": [ref],
                "worker_result_sha256": _digest(result), "observed_turn_id": result.get("observed_turn_id"),
                "physical_session_id": result.get("physical_session_id"), "provider_called": False,
                "acceptance": "unjudged retained worker result; inspect actual artifact paths/content and criterion before review-task",
                "next_action": "Use these exact refs for review-task after substantive inspection. Instruction GUIDE/MANDATE refs are context, not delivered artifact candidates. Preserve completed tasks, decisions and budget use; this read does not authorize another review or worker replay."}

    def _completed_review_read(self, alias: str, task_ref: Mapping[str, Any], task: Any,
                               reason: str | None = None) -> Mapping[str, Any]:
        """Present one exact retained completion without reopening assessment."""
        schemas = {"inspection_schema": self._inspection_schema(),
                   "judgment_schema": self._judgment_schema()}
        completion = task.payload.get("completion") if task is not None else None
        task_lifecycle = task.payload.get("lifecycle") if task is not None else None
        if getattr(task, "lifecycle", None) is not None:
            task_lifecycle = getattr(task.lifecycle, "value", task.lifecycle)
        base = {"outcome": "held" if reason else "read", "task": alias,
                "task_ref": task_ref, "task_lifecycle": task_lifecycle,
                "review_eligible": False, "provider_called": False,
                "assessment_policy_selection_availability": "unknown",
                "criterion_aliases_availability": "unknown", "criterion_aliases": {}, **schemas}
        if reason or not isinstance(completion, Mapping):
            return {**base, "completion": {"state": "unknown", "availability": "unknown"},
                    "reason": reason or "completed task has no retained completion mapping",
                    "next_action": "Preserve the historical task and reconcile its exact owner completion record."}
        try:
            current_task = ResourceRef.from_dict(task_ref)
            current_project = ResourceRef.from_dict(self.state["project_ref"])
            historical_task = ResourceRef.from_dict(completion["task_ref"])
            historical_project = ResourceRef.from_dict(completion["project_ref"])
            if ((historical_task.authority, historical_task.kind, historical_task.id)
                    != (current_task.authority, current_task.kind, current_task.id)):
                raise ValueError("completion task identity differs from the current task")
            if ((historical_project.authority, historical_project.kind, historical_project.id)
                    != (current_project.authority, current_project.kind, current_project.id)):
                raise ValueError("completion project identity differs from the current project")
            if (historical_task.kind != "work.task" or historical_project.kind != "work.project"
                    or not historical_task.revision or not historical_project.revision
                    or completion.get("task_revision") != historical_task.revision
                    or completion.get("project_revision") != historical_project.revision):
                raise ValueError("completion internal revision pins differ from their historical refs")
            if (completion.get("manager") != self.state["manager"]
                    or completion.get("generation") != self.state["manager_generation"]
                    or completion.get("disposition") not in {"accept", "accepted", "accepted-for-task", "approved", "complete", "completed", "verified"}):
                raise ValueError("completion manager epoch or accepted disposition differs")
            assignment_ref = completion.get("assignment_ref")
            if not isinstance(assignment_ref, Mapping):
                raise ValueError("completion assignment pin is unavailable")
            assignment = ResourceRef.from_dict(assignment_ref)
            current_assignment = ResourceRef.from_dict(self.state["assignment_ref"])
            if (assignment.kind != "wrk.assignment" or assignment.revision is None
                    or assignment.authority != current_assignment.authority
                    or (assignment.authority, assignment.kind, assignment.id) !=
                       (current_assignment.authority, current_assignment.kind, current_assignment.id)):
                raise ValueError("completion assignment pin is not exact current-owner history")
            key = completion.get("logical_request_key")
            receipt = self.owner.graph.reader.get_receipt(key) if isinstance(key, str) and key else None
            if (receipt is None or getattr(getattr(receipt, "status", None), "value", None) != "committed"
                    or receipt.operation != "work.revise" or receipt.target != historical_task
                    or receipt.result_ref != current_task):
                raise ValueError("completion lacks exact committed predecessor/current work.revise receipt")
            candidate = ResourceRef.from_dict(completion["candidate_ref"])
            if (candidate.kind not in {"wrk.result", "wrk.report", "dat.content.document"}
                    or candidate.revision is None or candidate.authority != current_project.authority):
                raise ValueError("completion candidate is not an exact supported current-owner pin")
            evidence_raw = completion.get("evidence_refs", ())
            gates_raw = completion.get("gate_refs", ())
            if (not isinstance(evidence_raw, (list, tuple)) or len(evidence_raw) > 256
                    or not isinstance(gates_raw, (list, tuple)) or len(gates_raw) > 256):
                raise ValueError("completion evidence or gate pins exceed the bounded read")
            evidence = [ResourceRef.from_dict(value) for value in evidence_raw]
            gates = [ResourceRef.from_dict(value) for value in gates_raw]
            if (any(ref.revision is None for ref in (*evidence, *gates))
                    or any(ref.authority != current_project.authority for ref in (*evidence, *gates))):
                raise ValueError("completion evidence and gates require exact current-owner revisions")
            optional_refs = {}
            for name in ("result_ref", "attempt_ref"):
                value = completion.get(name)
                if value is not None:
                    ref = ResourceRef.from_dict(value)
                    if ref.revision is None or ref.authority != current_project.authority:
                        raise ValueError("completion %s requires an exact current-owner revision" % name)
                    optional_refs[name] = ref.to_dict()
                else:
                    optional_refs[name] = None
            hashes = completion.get("evidence_hashes")
            if not isinstance(hashes, Mapping) or len(hashes) > 256:
                raise ValueError("completion evidence hashes are unavailable or exceed the bounded read")
            for hash_key, value in hashes.items():
                if (not isinstance(hash_key, str) or len(hash_key) > 512
                        or not isinstance(value, str) or len(value) != 64):
                    raise ValueError("completion evidence hash entry is malformed")

            candidate_record = None
            bounded_reader = getattr(self.owner.graph.reader, "get_identity_bounded", None)
            if callable(bounded_reader):
                bounded = bounded_reader(candidate, max_record_bytes=8192)
                if isinstance(bounded, Mapping) and bounded.get("state") == "available":
                    candidate_record = bounded.get("record")
                    if candidate_record is not None and candidate_record.ref != candidate:
                        raise ValueError("bounded completion candidate revision differs")
            if candidate_record is not None and candidate.kind in {"wrk.result", "wrk.report"}:
                value = candidate_record.payload.get("value") if isinstance(candidate_record.payload, Mapping) else None
                # Worker result custody is distinct from the accepting manager.
                # The committed completion receipt binds the exact candidate.
                if isinstance(value, Mapping) and (not _same_identity(value.get("task_ref"), historical_task.to_dict())
                        or not _same_identity(value.get("project_ref"), historical_project.to_dict())):
                    raise ValueError("completion candidate provenance does not match the retained task")
            receipt_view = {"status": receipt.status.value, "operation": receipt.operation,
                            "target": receipt.target.to_dict(), "result_ref": receipt.result_ref.to_dict()}
            detail = {"state": "recorded", "candidate_ref": candidate.to_dict(),
                      "result_ref": optional_refs["result_ref"], "attempt_ref": optional_refs["attempt_ref"],
                      "assignment_ref": assignment.to_dict(), "project_ref": historical_project.to_dict(),
                      "task_ref": historical_task.to_dict(), "current_task_ref": current_task.to_dict(),
                      "evidence_refs": [ref.to_dict() for ref in evidence],
                      "gate_refs": [ref.to_dict() for ref in gates], "evidence_hashes": dict(hashes),
                      "completion_receipt": receipt_view,
                      "historical_acceptance_verification": "unknown",
                      "completion_sha256": _digest(completion)}
            return {**base, "completion": detail, "candidate_ref": candidate.to_dict(),
                    "source_refs": [candidate.to_dict()], "evidence_refs": [ref.to_dict() for ref in evidence],
                    "acceptance": "recorded completion; historical acceptance verification is unknown without an exact scope read",
                    "next_action": "Preserve this completed task. Inspect bounded bindings if needed; review-task is not eligible for a new judgment."}
        except (KeyError, TypeError, ValueError, AttributeError):
            return {**base, "outcome": "held", "completion": {"state": "unknown", "availability": "unknown"},
                    "reason": "completed task completion provenance is malformed or unavailable",
                    "next_action": "Preserve the historical task and reconcile its exact owner completion record."}

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
        current_task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(self.state["task_refs"][alias]))
        current_lifecycle = (current_task.payload.get("lifecycle") if current_task is not None else None)
        if getattr(current_task, "lifecycle", None) is not None:
            current_lifecycle = getattr(current_task.lifecycle, "value", current_task.lifecycle)
        if current_lifecycle == "completed":
            # Read-only replay lookup is allowed for the exact previously
            # accepted key.  A new key must refuse before any journal,
            # assessment, reservation or provider effect can begin.
            replay_prior = self._journal(key, "intent", adopted_history=True)
            replay_review = self._journal(key, "review", adopted_history=True)
            if not (isinstance(replay_prior, Mapping)
                    and isinstance(replay_review, Mapping)
                    and replay_review.get("outcome") == "accepted"):
                raise PermissionError("completed task is not review-eligible; use a separately authorized corrective task")
        prior = (replay_prior if current_lifecycle == "completed" else
                 self._journal(key, "intent"))
        reviewed = (replay_review if current_lifecycle == "completed" else
                    self._journal(key, "review"))
        # A completed same-key review replay has no new assessment admission;
        # its original task revision remains immutable after completion.
        completed_task_ref = None
        if prior is not None and prior.get("task_ref") != self.state["task_refs"][alias]:
            self._committed_finish_for_review(alias, key, prior, reviewed)
            completed_task_ref = prior["task_ref"]
        policy = self._review_policy(alias, validate_current=reviewed is None, completed_task_ref=completed_task_ref)
        policy_pin = self._review_policy_pin(alias, policy)
        manifest = {"request": dict(request), "task_ref": self.state["task_refs"][alias],
                    "project_ref": self.state["project_ref"],
                    "assignment_ref": self.state["assignment_ref"],
                    "generation": self.state["manager_generation"], "assessment_policy_selection": policy_pin}
        if prior is not None:
            if prior["request"] != dict(request):
                raise ValueError("ordinary request key was reused with changed input")
            prior_policy = prior.get("assessment_policy_selection")
            if (prior_policy is not None and prior_policy != policy_pin
                    or prior_policy is None and policy_pin["source"] == "owner-issued-task-supplement"):
                raise PermissionError("original review key policy differs or has unknown provenance; use a distinct authorized correction judgment")
            manifest = prior
        if reviewed is None:
            commands = self.owner.manager_assessment(project_ref=manifest["project_ref"],
                task_ref=manifest["task_ref"], manager_assignment_ref=manifest["assignment_ref"],
                manager_actor=self.state["manager"], manager_generation=manifest["generation"],
                assessment_policy=policy)
            existing_scope = commands.required_scope(require=False)
            candidate = commands._ref(request.get("candidate_ref"), "candidate_ref")
            sources = commands._refs(request.get("source_refs"), "source_refs")
            judgments = request.get("judgments")
            aliases = self._review_criteria(manifest["task_ref"], policy)
            if not isinstance(judgments, Mapping) or set(judgments) != set(aliases):
                raise ReviewInputSchemaError("judgments", "input schema rejected before review effects: supply explicit judgment for every "
                    "configured task criterion; exact aliases: " + ", ".join(sorted(aliases)) +
                    ". Read review-input --task " + alias + " for their pinned refs")
            inspection = request.get("inspection")
            if not isinstance(inspection, Mapping) or not inspection:
                raise ReviewInputSchemaError("inspection", 'input schema rejected before review effects: inspection must be a nonempty JSON '
                    'object containing substantive observed evidence, for example {"observed":"your inspection"}; '
                    'a JSON string, array or empty object is not accepted')
            evidence = []
            for criterion_alias, judgment in judgments.items():
                if (not isinstance(judgment, Mapping)
                        or set(judgment) != {"verdict", "rationale", "evidence_refs"}
                        or judgment["verdict"] not in {"PASS", "REWORK", "UNKNOWN"}
                        or not isinstance(judgment["rationale"], str) or not judgment["rationale"].strip()):
                    raise ReviewInputSchemaError("judgments." + criterion_alias,
                        "each criterion requires exactly verdict, rationale and evidence_refs; verdict must be PASS, REWORK or UNKNOWN",
                        allowed_values=["PASS", "REWORK", "UNKNOWN"])
                evidence.extend(commands._refs(judgment["evidence_refs"], "evidence_refs"))
            evidence = list(dict.fromkeys(evidence))
            if self._instruction_document(candidate) or candidate not in evidence:
                raise ValueError("ordinary review requires the actual artifact/result candidate in evidence_refs; "
                    "GUIDE/MANDATE instruction documents cannot substitute for delivered work. "
                    "Use review-input --task to discover retained worker refs, then inspect the artifact and exact task outcome.")
            for judgment in judgments.values():
                if any(char in judgment["rationale"] for char in ("/", "\\", "\x00")):
                    raise ReviewInputSchemaError("judgments.rationale", "rationale is an assessment identifier: use nonblank text without slash, backslash or NUL; "
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
            completion = self.finish_task({"task": alias, "request_key": key + ":finish", "review_key": key})
            response = {**reviewed, "completion": completion}
            if completion.get("outcome") == "pending":
                response["next_action"] = ("Await owner settlement of existing completion intent "
                    + completion["completion_intent"] + "; do not create another finish-task key. Replay only the exact original request.")
            return response
        return {**reviewed, "task_completion_recorded": False,
                "next_action": "inspect or correct the evidence and submit new explicit judgment" if reviewed["outcome"] != "accepted"
                else "finish-task with this review_key"}

    def finish_task(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._authorize()
        key = self._key(request)
        if set(request) - {"command", "task", "request_key", "review_key"}:
            raise ValueError("unsupported task finish fields")
        if request.get("command", "finish-task") != "finish-task":
            raise ValueError("task finish command discriminator differs")
        prior = self._journal(key, "finish-intent", adopted_history=True)
        semantic = {k: v for k, v in request.items() if k != "command"}
        if prior is not None:
            if prior.get("command", "finish-task") != "finish-task":
                raise ValueError("retained task finish command discriminator differs")
            if {k: v for k, v in prior.items() if k != "command"} != semantic:
                raise ValueError("task finish request key was reused with changed input")
            # Preserve immutable legacy request bytes/digest; command merely
            # selects this public operation and is not a new business input.
            request = dict(prior)
        else:
            request = semantic
        reviewed = self._journal(request.get("review_key"), "review", adopted_history=True)
        manifest = self._journal(request.get("review_key"), "intent", adopted_history=True)
        if reviewed is None or manifest is None or reviewed["outcome"] != "accepted":
            raise ValueError("finish-task requires retained explicit accepted judgment")
        if manifest["request"]["task"] != request.get("task"):
            raise PermissionError("review belongs to another task")
        if (manifest["generation"] != self.state["manager_generation"]
                or any(manifest["assignment_ref"].get(k) != self.state["assignment_ref"].get(k) for k in ("authority", "kind", "id"))):
            raise PermissionError("accepted review task or manager generation changed")
        if prior is None:
            current_task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(self.state["task_refs"][request["task"]]))
            if current_task is not None and current_task.payload.get("lifecycle") == "completed":
                committed = self._committed_finish_for_review(request["task"], request["review_key"], manifest, reviewed)
                raise PermissionError("review already has a completion intent; replay exact request_key " + committed["committed_request_key"])
            # One review owns one completion intent. A new correlation key
            # cannot create a second intent while the original awaits native
            # settlement, including after a same-generation resource adoption.
            from completion_intent_selection import selected_reports
            records, _selection = selected_reports(self, aliases=(request["task"],), review_key=request["review_key"])
            for record in records:
                value = record.payload.get("value")
                if not isinstance(value, Mapping):
                    continue
                existing = value.get("content")
                if (value.get("schema") != "otto.manager-journey.v1"
                        or not isinstance(existing, Mapping)
                        or existing.get("review_key") != request["review_key"]
                        or not value.get("logical_request_key", "").endswith(":finish-intent")):
                    continue
                existing_key = self._key(existing)
                if (existing.get("task") != request["task"]
                        or value["logical_request_key"] != "journey:" + existing_key + ":finish-intent"
                        or self._journal(existing_key, "finish-intent", adopted_history=True) != existing):
                    raise PermissionError("existing completion intent provenance differs")
                raise PermissionError("review already has a completion intent; replay exact request_key " + existing_key)
        completion_project = self._completion_project(request, manifest, reviewed)
        if manifest["task_ref"] != self.state["task_refs"][request["task"]]:
            # Completion itself advances the task revision. A later worker
            # settlement revisits this retained finish intent, so only the
            # exact already-committed completion may cross that revision fence.
            # The owner completion API still verifies the original replay
            # digest; no new completion or native settlement is attempted.
            return self._committed_finish_for_review(request["task"], request["review_key"], manifest, reviewed)
        self._journal(key, "finish-intent", dict(request))
        settlement = self._native_settlement(reviewed)
        if settlement is not None:
            return {"outcome": "pending", "completion_intent": key, "settlement": settlement,
                    "retry_provider": False,
                    "next_action": "settle this retained native occurrence without resending; repeat this exact finish request"}
        if self.due_port is not None:
            active = [due for due in self.due_port.list_due({"project_ref": manifest["project_ref"]["id"]})
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
        result = self.portfolio.complete_task(completion_project, manifest["task_ref"],
            self.state["assignment_ref"], actor=self.state["manager"], request_id="journey:" + key,
            expected_generation=self.state["manager_generation"],
            expected_project_revision=completion_project["revision"],
            expected_task_revision=manifest["task_ref"]["revision"], disposition="accepted",
            evidence_refs=reviewed["evidence_refs"], evidence_hashes=reviewed["evidence_hashes"],
            gate_refs=reviewed["gate_refs"], candidate_ref=reviewed["candidate_ref"])
        if result.get("outcome") in {"completed", "replayed"}:
            return result
        return {"outcome": "pending", "completion_intent": key, "owner_result": result,
                "retry_provider": False,
                "next_action": "inspect completion prerequisites; settle retained native evidence if required; repeat this exact finish request"}

    def _completion_project(self, request: Mapping[str, Any], manifest: Mapping[str, Any],
                            reviewed: Mapping[str, Any], *, retain: bool = True) -> Mapping[str, Any]:
        """Retain a completion pin across same-root resource-only join refreshes.

        An accepted review stays immutable. Only WRK's authenticated supervision
        refresh plus the matching same-generation root resource adoption may
        bridge its project revision; task and manager fences remain unchanged.
        """
        original = ResourceRef.from_dict(manifest["project_ref"])
        key = request["request_key"]
        retained = self._journal(key, "finish-project-pin")
        proof = {"accepted_project_ref": original.to_dict(), "task_ref": manifest["task_ref"],
                 "assignment_ref": self.state["assignment_ref"], "generation": self.state["manager_generation"],
                 "manifest_sha256": _digest(manifest), "review_sha256": _digest(reviewed)}
        current = self.owner.graph.reader.get_identity(ResourceRef(original.authority, original.kind, original.id))
        if current is None:
            raise PermissionError("accepted completion project is missing")
        if retained is not None:
            if any(retained.get(k) != v for k, v in proof.items()):
                raise PermissionError("retained completion project proof changed")
            target = ResourceRef.from_dict(retained["project_ref"])
        else:
            # An exact committed task replay keeps its original completion pin,
            # even when project terminal bookkeeping advanced the project later.
            if manifest["task_ref"] != self.state["task_refs"][request["task"]]:
                return original.to_dict()
            target = current.ref
        prior_pin = None
        refresh_stage = None
        if retained is not None:
            if manifest["task_ref"] == self.state["task_refs"][request["task"]]:
                desired = current.ref
            else:
                task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(self.state["task_refs"][request["task"]]))
                completion = {} if task is None else task.payload.get("completion", {})
                desired = ResourceRef.from_dict(completion.get("project_ref", target.to_dict()))
            if desired != target:
                prior_pin = retained
                target = desired
                refresh_stage = "finish-project-pin-refresh:" + target.revision
                retained = self._journal(key, refresh_stage)
                if retained is not None and any(retained.get(k) != v for k, v in proof.items()):
                    raise PermissionError("retained completion project proof changed")
        if target == original:
            return original.to_dict()
        if (target.authority, target.kind, target.id) != (original.authority, original.kind, original.id):
            raise PermissionError("accepted completion project identity changed")
        events = self.owner.graph.reader.list_events(stream="work:" + original.id)
        transitions = {}
        for event in events:
            transitions.setdefault(event.subject, []).append(event)
        cursor, chain = target, []
        while cursor != original:
            matches = transitions.get(cursor, ())
            if len(matches) != 1 or len(chain) >= 32:
                raise PermissionError("completion project revision chain is missing or ambiguous")
            event = matches[0]
            effects = event.effects
            before = effects.get("from_assignment")
            after = effects.get("to_assignment")
            relation = effects.get("supervision", {})
            history = effects.get("history_summary")
            # FND reserves this capture field at the authoritative writer. It
            # carries history, never authorization for the completion bridge.
            allowed_effects = {"from_assignment", "to_assignment", "supervision", "root_resource_refresh"}
            if history is not None:
                if not isinstance(history, Mapping) or history.get("schema") != HISTORY_SCHEMA:
                    raise PermissionError("completion project history summary is invalid")
                allowed_effects.add("history_summary")
            if (event.event_type != "work.project.supervision-transferred"
                    or event.operation != "work.project.supervision.transfer"
                    or not isinstance(before, Mapping) or not isinstance(after, Mapping)
                    or any(before.get(k) != after.get(k) for k in ("authority", "kind", "id"))
                    or before == after or relation.get("assignment_ref") != after
                    or relation.get("project_ref") != cursor.to_dict()
                    or not event.actor.authenticated
                    or set(effects) - allowed_effects):
                raise PermissionError("completion project changed beyond same-root resource refresh")
            root_events = self.owner.graph.reader.list_events(stream="assignment:" + after["id"])
            adopted = [e for e in root_events if e.subject == ResourceRef.from_dict(after)
                       and e.event_type == "work.assignment.resources-adopted"]
            body = adopted[0].effects.get("result_payload", {}) if len(adopted) == 1 else {}
            if (len(adopted) != 1 or adopted[0].actor != event.actor
                    or body.get("resource_adoption_base_ref") != before
                    or body.get("role") != "orchestrator" or body.get("principal") != event.actor.actor
                    or body.get("generation") != relation.get("generation")
                    or body.get("scope") != relation.get("portfolio_ref")):
                raise PermissionError("completion project refresh has no exact root adoption proof")
            bases = [ref for ref in event.before_refs if
                     (ref.authority, ref.kind, ref.id) == (original.authority, original.kind, original.id)]
            if len(bases) != 1 or bases[0] == cursor or bases[0] in [x[0] for x in chain]:
                raise PermissionError("completion project predecessor is invalid")
            chain.append((cursor, event.event_id, adopted[0].event_id))
            cursor = bases[0]
        if manifest["task_ref"] == self.state["task_refs"][request["task"]]:
            task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(manifest["task_ref"]))
            if task is None or task.ref.to_dict() != manifest["task_ref"] or task.payload.get("lifecycle") == "completed":
                raise PermissionError("accepted completion task revision changed")
        proof.update(project_ref=target.to_dict(), event_ids=[x[1] for x in reversed(chain)],
                     root_adoption_event_ids=[x[2] for x in reversed(chain)])
        if prior_pin is not None:
            old_target = ResourceRef.from_dict(prior_pin["project_ref"])
            prefix = list(reversed(chain))
            positions = [index for index, item in enumerate(prefix) if item[0] == old_target]
            if (len(positions) != 1
                    or prior_pin.get("event_ids") != [x[1] for x in prefix[:positions[0] + 1]]
                    or prior_pin.get("root_adoption_event_ids") != [x[2] for x in prefix[:positions[0] + 1]]):
                raise PermissionError("retained completion project ancestry changed")
            # Every admitted transition above is the maintained supervision-only
            # transfer operation, which copies every non-supervision field.
            # Preserve the old proof; append this exact extension immutably.
            payload_digest = _digest({**current.payload,
                "metadata": {k: v for k, v in current.payload.get("metadata", {}).items()
                             if k != "otto_orchestrator"}})
            if manifest["task_ref"] != self.state["task_refs"][request["task"]]:
                # Exact committed completion replay pins its original semantics;
                # later project bookkeeping cannot rewrite this historical proof.
                # _completed_finish still verifies the canonical completion.
                if retained is None or not isinstance(retained.get("non_supervision_payload_sha256"), str):
                    raise PermissionError("committed completion refresh proof is missing")
                payload_digest = retained["non_supervision_payload_sha256"]
            proof.update(prior_pin_sha256=_digest(prior_pin),
                         non_supervision_payload_sha256=payload_digest)
        if retained is not None:
            if retained != proof:
                raise PermissionError("retained completion project ancestry changed")
        else:
            if current.ref != target or manifest["task_ref"] != self.state["task_refs"][request["task"]]:
                raise PermissionError("completion task or current project changed")
            if retain:
                self._journal(key, refresh_stage or "finish-project-pin", proof)
        return target.to_dict()

    def _committed_finish_for_review(self, alias: str, review_key: str,
                                    manifest: Mapping[str, Any], reviewed: Mapping[str, Any]) -> Mapping[str, Any]:
        """Prove the one canonical completion for this exact accepted review.

        Historical sibling intents may refer to that same completion, but they
        do not gain a new receipt, journal entry, assessment or debit.
        """
        record = self.owner.graph.reader.get_identity(ResourceRef.from_dict(self.state["task_refs"][alias]))
        completion = {} if record is None else record.payload.get("completion", {})
        logical_key = completion.get("logical_request_key") if isinstance(completion, Mapping) else None
        if not isinstance(logical_key, str) or not logical_key.startswith("journey:"):
            raise PermissionError("changed task revision requires exact committed completion replay")
        finish_key = logical_key[len("journey:"):]
        self._key({"request_key": finish_key})
        intent = self._journal(finish_key, "finish-intent", adopted_history=True)
        expected = {"task": alias, "request_key": finish_key, "review_key": review_key}
        if (not isinstance(reviewed, Mapping) or reviewed.get("outcome") != "accepted"
                or not isinstance(intent, Mapping)
                or intent.get("command", "finish-task") != "finish-task"
                or {k: v for k, v in intent.items() if k != "command"} != expected):
            raise PermissionError("changed task revision requires exact committed completion replay")
        verified = self._completed_finish(dict(intent), intent, manifest, reviewed)
        return {**verified, "committed_request_key": finish_key}


    def _completed_finish(self, request: Mapping[str, Any], prior: Any,
                          manifest: Mapping[str, Any], reviewed: Mapping[str, Any]) -> Mapping[str, Any]:
        """Verify the exact committed completion before a read-only replay."""
        current = ResourceRef.from_dict(self.state["task_refs"][request["task"]])
        original = ResourceRef.from_dict(manifest["task_ref"])
        record = self.owner.graph.reader.get_identity(current)
        key = "journey:" + request["request_key"]
        receipt = self.owner.graph.reader.get_receipt(key)
        completion = {} if record is None else record.payload.get("completion", {})
        if not isinstance(completion, Mapping):
            raise PermissionError("accepted review task or manager generation changed")
        try:
            historical_task = ResourceRef.from_dict(completion.get("task_ref"))
            historical_project = ResourceRef.from_dict(completion.get("project_ref"))
            completion_assignment = ResourceRef.from_dict(completion.get("assignment_ref"))
            current_assignment = ResourceRef.from_dict(self.state["assignment_ref"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermissionError("accepted review task or manager generation changed") from exc
        expected = {"logical_request_key": key, "manager": self.state["manager"],
                    "assignment_ref": completion_assignment.to_dict(),
                    "generation": completion.get("generation"),
                    "task_ref": historical_task.to_dict(), "task_revision": historical_task.revision,
                    "project_ref": historical_project.to_dict(), "project_revision": historical_project.revision,
                    "disposition": "accepted", "candidate_ref": reviewed["candidate_ref"],
                    "evidence_refs": reviewed["evidence_refs"], "evidence_hashes": reviewed["evidence_hashes"],
                    "gate_refs": reviewed["gate_refs"]}
        if (prior != dict(request) or record is None or record.ref != current
                or (current.authority, current.kind, current.id) != (original.authority, original.kind, original.id)
                or historical_task != original
                or (historical_project.authority, historical_project.kind, historical_project.id) !=
                   (ResourceRef.from_dict(self.state["project_ref"]).authority,
                    ResourceRef.from_dict(self.state["project_ref"]).kind,
                    ResourceRef.from_dict(self.state["project_ref"]).id)
                or (completion_assignment.authority, completion_assignment.kind, completion_assignment.id) !=
                   (current_assignment.authority, current_assignment.kind, current_assignment.id)
                or completion.get("generation") != self.state["manager_generation"]
                or completion.get("generation") != manifest.get("generation")
                or record.payload.get("lifecycle") != "completed"
                or any(completion.get(field) != value for field, value in expected.items())
                or receipt is None or receipt.status.value != "committed" or receipt.operation != "work.revise"
                or receipt.target != historical_task or receipt.result_ref != current):
            raise PermissionError("accepted review task or manager generation changed")
        return {"outcome": "replayed", "replayed": True, "task_ref": current.to_dict(),
                "assignment_ref": completion_assignment.to_dict(), "generation": completion.get("generation"),
                "completion": dict(completion), "receipt": receipt.to_dict()}

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
        due_records = [due for due in self.due_port.list_due({"project_ref": ResourceRef.from_dict(payload["project_ref"]).id})
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
        withdrawn = [task for task in tasks if task.lifecycle.value == "withdrawn"]
        withdrawn_refs = []
        if withdrawn:
            # Withdrawal is retained planning history, never task acceptance.
            # Only explicit current unused extras outside the original policy
            # may be omitted from completion inputs. Required obligations,
            # stale/foreign pins and any assignment use stay a closeout hold.
            policy = self.policy or self.state.get("assessment_policy")
            if isinstance(policy, Mapping):
                policy = LocalAssessmentPolicy.from_run_config(policy, state=self.state)
            if not isinstance(policy, LocalAssessmentPolicy) or (
                    policy.scope_project_ref.authority, policy.scope_project_ref.id) != (
                    project.ref.authority, project.ref.id):
                raise PermissionError("withdrawn planning history requires the bound original assessment policy")
            required = {task.id for task, _ in policy.task_criterion_pairs}
            pins = list(self.state["task_refs"].values())
            actual = {task.id for task in tasks}
            if not required.issubset(actual):
                raise PermissionError("project closeout is missing an original required task")
            reader = self.owner.store.consumer()
            project_executors = tuple(ref for role in ("worker", "executor")
                for ref in reader.find_identity_refs(kind="wrk.assignment", payload_matches={
                    ("scope", "authority"): project.ref.authority,
                    ("scope", "kind"): project.ref.kind, ("scope", "id"): project.ref.id,
                    ("role",): role}))
            for task in withdrawn:
                current = self.owner.graph.reader.get_identity(
                    ResourceRef(task.ref.authority, task.ref.kind, task.id))
                parent = task.payload.get("project_ref") or {}
                used = reader.find_identity_refs(kind="wrk.assignment", payload_matches={
                    ("scope", "authority"): task.ref.authority,
                    ("scope", "kind"): task.ref.kind, ("scope", "id"): task.id})
                if (task.id in required or current is None or current.ref != task.ref
                        or task.ref.to_dict() not in pins or task.payload.get("completion")
                        or used or project_executors or (parent.get("authority"), parent.get("kind"), parent.get("id")) != (
                            project.ref.authority, project.ref.kind, project.ref.id)):
                    return {"outcome": "held", "project_completion_recorded": False,
                            "reason": "withdrawn task is required, used, stale or not provably bound unused planning history; project executors make task use ambiguous",
                            "task_ref": task.ref.to_dict(), "provider_called": False}
                withdrawn_refs.append(task.ref.to_dict())
            tasks = tuple(task for task in tasks if task.lifecycle.value != "withdrawn")
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
        if withdrawn_refs:
            intent["withdrawn_unused_planning_refs"] = withdrawn_refs
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
            if withdrawn_refs:
                evidence["acceptance"]["withdrawn_unused_planning_refs"] = withdrawn_refs
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
