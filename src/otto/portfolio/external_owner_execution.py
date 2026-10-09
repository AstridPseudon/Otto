"""Finite external orchestrator commands over a distinct protected host grant.

The host authenticates the external owner input; no native-process identity is
claimed. Launch and result association use existing assignments and Due records.
Authoring grants never authorize these operations.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Mapping
from herzchen.contracts import AuthenticatedActor, ResourceRef
from .execution_host import _atomic_json
from .occurrence_reads import digest, exact_due, handle, lookup, result_view, read_captured_artifact


class OwnerExecutionIngress:
    schema = "otto.owner-execution-grant.v1"
    fields = frozenset({"command", "operation", "request_key", "focus", "occurrence", "artifact_ref", "offset", "max_bytes", "timeout_seconds", "original_request_key"})

    def __init__(self, *, actor: AuthenticatedActor, owner_actor: AuthenticatedActor, directory: str | Path):
        if not isinstance(actor, AuthenticatedActor) or actor != owner_actor:
            raise PermissionError("execution ingress requires authenticated service owner")
        self.actor, self.directory = actor, Path(directory)
        self._grants, self._lock = set(), threading.Lock()

    def _checked(self, request):
        if not isinstance(request, Mapping) or request.get("command") != "owner-execution" or set(request) - self.fields:
            raise PermissionError("finite owner execution fields only; no identity, model, scope or allowance overrides")
        raw = json.dumps(dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > 16384:
            raise ValueError("bounded owner execution grant required")
        return json.loads(raw), raw

    def publish(self, envelope):
        if set(envelope) != {"schema", "request"} or envelope["schema"] != self.schema:
            raise PermissionError("distinct execution grant envelope required")
        request, raw = self._checked(envelope["request"])
        token = hashlib.sha256(b"otto-owner-execution-grant-v1\0" + raw).hexdigest()
        path, response = self.directory / ("request-" + token + ".json"), self.directory / ("response-" + token + ".json")
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists() and json.loads(path.read_text()) != request:
                raise RuntimeError("retained external execution request differs")
            self._grants.add(digest(request))
            if not path.exists() and not response.exists():
                _atomic_json(path, request)
        return {"outcome": "owner-execution-granted", "request_id": token, "request_path": str(path),
                "response_path": str(response), "canonical_effect_recorded": False, "provider_called": False}

    def authorize(self, request):
        self._checked(request)
        with self._lock:
            if digest(request) not in self._grants:
                raise PermissionError("external execution lacks exact protected owner input grant")
        return self.actor


def dispatch(service, request):
    if not callable(service.external_execution_authorizer):
        raise PermissionError("external execution capability is not installed")
    actor = service.external_execution_authorizer(request)
    owner, state, policy = service.server.owner, service.server.state, service.external_execution_policy
    if actor != owner.owner_actor:
        raise PermissionError("external execution requires authenticated owner")
    if (not isinstance(policy, Mapping) or set(policy) != {"root_assignment_ref", "generation", "project_ref", "task_ref", "task", "principal", "route", "model", "reasoning", "native_adapter", "max_launches", "worker_turn_allowance", "capacity_units", "max_depth", "operation_profile"}
            or policy["capacity_units"] != 1 or policy["max_depth"] != 1 or policy["max_launches"] != 1 or policy["operation_profile"] != "read_only_inspection"
            or type(policy["worker_turn_allowance"]) is not int or policy["worker_turn_allowance"] < 3):
        raise PermissionError("explicit finite owner execution policy is unavailable")
    root = owner.assignments.get(ResourceRef.from_dict(state["orchestrator_assignment_ref"]))
    if (root.ref.to_dict() != state["orchestrator_assignment_ref"] or root.principal != actor.actor
            or root.role != "orchestrator" or root.scope.kind != "wrk.portfolio" or root.status.value == "cancelled"
            or root.generation != policy["generation"] or root.ref.id != policy["root_assignment_ref"]["id"]):
        raise PermissionError("current external orchestrator is stale or foreign")
    binding = {"assignment_ref": policy["root_assignment_ref"], "generation": policy["generation"],
        "project_ref": policy["project_ref"], "task_ref": policy["task_ref"],
        "result_destination": {"assignment_ref": policy["root_assignment_ref"], "generation": policy["generation"]},
        "identity_origin": "authenticated external owner input capability", "native_process_identity_claimed": False}
    operation = request.get("operation")
    fields = {"command", "operation", "request_key"}
    if operation == "launch": fields |= {"focus"}
    elif operation == "lookup": fields |= {"original_request_key"}
    elif operation in {"follow", "result", "consume", "start-prepared"}: fields |= {"occurrence"}
    elif operation == "artifact": fields |= {"occurrence", "artifact_ref", "offset", "max_bytes"}
    else: raise ValueError("unsupported external execution operation")
    if set(request) != fields or not isinstance(request["request_key"], str) or not request["request_key"].strip():
        raise ValueError("exact finite operation fields and stable key required")
    common = {"schema": "otto.external-owner-execution.v1", "external_parent": binding,
              "principal": root.principal, "native_process_identity_claimed": False}
    scope = {"project_ref": policy["project_ref"], "task_ref": policy["task_ref"], "parent": None}
    if operation == "lookup":
        answer = lookup(service.server.due_port, scope=scope, request_key=request["original_request_key"])
        if answer["outcome"] == "found":
            due = exact_due(service.server.due_port, answer["occurrence"])
            if due["target"]["launch_request"].get("external_parent") != binding:
                raise PermissionError("occurrence belongs to another external result destination")
        return {**common, **answer}
    if operation == "launch":
        existing = lookup(service.server.due_port, scope=scope, request_key=request["request_key"])
        if existing["outcome"] != "found":
            if (root.ref.to_dict() != policy["root_assignment_ref"] or state["project_ref"] != policy["project_ref"]
                    or state["task_refs"].get(policy["task"]) != policy["task_ref"]):
                raise PermissionError("launch policy must pin current root/project/task")
            rows = service.server.due_port.list_due({"project_ref": policy["project_ref"]["id"], "role": "worker"})
            if (sum(bool(r["target"].get("launch_request", {}).get("external_parent")) for r in rows) >= policy["max_launches"]
                    or len(rows) + 1 > policy["worker_turn_allowance"]):
                raise PermissionError("finite external launch/child/return allowance exhausted")
            live = getattr(service.host.caller_binding_reader, "live_occurrence", None)
            if not callable(live): raise PermissionError("native capacity release reader unavailable")
            for row in service.server.due_port.list_due({"project_ref": policy["project_ref"]["id"]}):
                if row.get("role") in {"manager", "worker"} and (live(row["schedule_id"]) or row.get("in_flight_request") and row.get("host_evidence", {}).get("gateway_attempt")):
                    raise PermissionError("native capacity is occupied or uncertain")
            config = json.loads((service.run_path / "run.yaml").read_text())["roles"]["worker_" + policy["route"]]
            if config != {"model": policy["model"], "reasoning": policy["reasoning"]}:
                raise PermissionError("configured worker route differs from explicit host policy")
            app = service._execution(principal=policy["principal"], model=policy["model"], reasoning=policy["reasoning"], evidence_id="external-root-policy")
            if app.native_adapter_identity() != policy["native_adapter"]:
                raise PermissionError("installed native adapter differs")
        launch = {"command": "run-worker", "task": policy["task"], "route": policy["route"],
                  "principal": policy["principal"], "request_key": request["request_key"], "focus": request["focus"]}
        answer = service._submit_worker(launch, external_parent=binding, resource_assignment_ref=policy["root_assignment_ref"], read_only=True)
        return {**common, **answer}
    due = exact_due(service.server.due_port, request["occurrence"])
    if (due["target"].get("launch_request") or {}).get("external_parent") != binding:
        raise PermissionError("external occurrence/result destination is foreign")
    if operation == "start-prepared":
        # No new child, profile change, UNKNOWN replay or stopped/paused bypass.
        # This operation is only the existing start for an unattempted occurrence.
        if (due["stop_state"] != "active" or due["host_state"] == "paused"
                or due.get("delivery_state") != "ready"
                or (due.get("host_evidence") or {}).get("gateway_attempt") is not None
                or due.get("delivery_evidence") is not None or due.get("completion_evidence") is not None):
            raise PermissionError("only an exact unattempted prepared external occurrence can start")
        live = getattr(service.host.caller_binding_reader, "live_occurrence", None)
        if not callable(live) or any(live(row["schedule_id"]) for row in service.server.due_port.list_due({"project_ref": policy["project_ref"]["id"]})):
            raise PermissionError("native capacity is occupied or uncertain")
        app = service._execution(principal=due["recipient"], model=due["requested_model"],
            reasoning=due["requested_reasoning"], evidence_id=due["schedule_id"],
            selection=(due["target"].get("launch_request") or {}).get("selection"))
        validate_host = getattr(app.runtime.adapter, "validate_owner_host_composition", None)
        if callable(validate_host): validate_host(role="worker", profile=due["profile"])
        return {**common, **app.start(schedule_id=due["schedule_id"]),
                "recovery_operation": "start_same_unattempted_occurrence", "original_launch_preserved": True}
    if operation == "artifact":
        return {**common, **read_captured_artifact(due, artifact_ref=request["artifact_ref"], offset=request["offset"], max_bytes=request["max_bytes"])}
    answer = result_view(due)
    if operation == "follow": answer["wait"] = {"state": "snapshot-only", "detachable": True}
    if operation == "consume":
        if not answer["required_capture"]:
            return {**common, **answer, "outcome": "held", "reason": "required captured result unavailable"}
        evidence = {"schema": "otto.external-parent-consumption.v1", "external_parent": binding,
                    "child": handle(due), "delivery_identity": answer["delivery_identity"],
                    "result_sha256": digest(due["host_evidence"]["gateway_attempt"]["result"])}
        report = owner.assignments.command_port.append_report(root.ref, evidence, expected_generation=root.generation,
            logical_request_key="external-parent-consumed:" + digest([binding, evidence["delivery_identity"]]), actor=actor)
        answer.update(pure=False, effect="record_authenticated_external_parent_consumption", consumption_report_ref=report.ref.to_dict())
    return {**common, **answer}
