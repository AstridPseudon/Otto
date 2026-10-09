"""Command-specific worker authority and capacity-one parent consumption.

All retention uses assignments, Due records and the existing owner command
lane. No caller-supplied identity, process path or provider flag is a grant.
"""
from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .occurrence_reads import digest, exact_due, handle, lookup, result_view


def identity(ref: Mapping[str, Any]) -> tuple:
    return tuple(ref.get(k) for k in ("authority", "kind", "id"))


def policy(service: Any) -> Mapping[str, Any]:
    value = service.delegation_policy
    if (not isinstance(value, Mapping) or set(value) != {"coordinators", "max_depth", "capacity_units", "cumulative_allowance_units"}
            or not isinstance(value["coordinators"], list) or not value["coordinators"]
            or any(type(value[k]) is not int or value[k] < 1 for k in
                   ("max_depth", "capacity_units", "cumulative_allowance_units"))
            or value["max_depth"] != 1 or value["capacity_units"] != 1):
        raise PermissionError("no qualified capacity-one finite coordinating-worker policy is installed")
    for coordinator in value["coordinators"]:
        if (not isinstance(coordinator, Mapping) or set(coordinator) != {"assignment_ref", "generation", "native_adapter"}
                or type(coordinator["generation"]) is not int or coordinator["generation"] < 1
                or not isinstance(coordinator["native_adapter"], str) or not coordinator["native_adapter"]
                or not isinstance(coordinator["assignment_ref"], Mapping)
                or coordinator["assignment_ref"].get("kind") != "wrk.assignment"
                or not coordinator["assignment_ref"].get("revision")):
            raise PermissionError("coordinator policy must pin an exact assignment/generation/adapter")
    # This is the host's explicitly qualified worker policy. Assessment
    # bookkeeping units are not worker-turn allowance and never grant it.
    # No policy is inferred from labels, user focus, or assessment budgets.
    return value


def qualified(configured: Mapping[str, Any], due: Any) -> bool:
    return {"assignment_ref": due.assignment_ref, "generation": due.generation,
            "native_adapter": due.target["native_adapter"]} in configured["coordinators"]


def current_parent_slot(service: Any, assignment: Mapping[str, Any], generation: int, schedule: str) -> bool:
    return any(slot.get("assignment_ref") == assignment and slot.get("generation") == generation
               and slot.get("schedule_id") == schedule
               for slot in (service.server.state.get("workers") or {}).values())


def parent_for_caller(service: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    configured = policy(service)
    app = service._execution(principal=context["principal"], model=service.server.state["requested_model"],
        reasoning=service.server.state["requested_reasoning"], evidence_id="worker-caller")
    due = app._read(context["occurrence_ref"]["schedule_id"])
    current = app._current(context["assignment_ref"], context["generation"])
    if (not qualified(configured, due) or due.role != "worker"
            or due.target.get("parent") is not None or current.payload.get("parent") is not None
            or due.stop_state != "active" or due.completion_state != "none"
            or due.host_state == "paused" or context["role"] != "worker"):
        raise PermissionError("worker is stale, a leaf, or has no finite delegation scope")
    from .owner_readers import mandate_reader
    mandate = mandate_reader(app.portfolio.operations, due.target["project_ref"],
        due.target["mandate_ref"])(dict(zip(("authority", "kind", "id"), identity(due.target["mandate_ref"]))))
    contract = mandate["payload"]["instruction_contract"]
    if (contract.get("delegation") != {"max_depth": 1, "result_consumption": "yield"}
            or "canonical_child_commands" not in contract.get("allowed_operations", ())
            or "canonical_child_commands" not in contract.get("authority", {}).get("permitted_effects", ())):
        raise PermissionError("worker has no adopted finite child-command mandate")
    if not current_parent_slot(service, current.ref.to_dict(), current.generation,
                               due.target.get("parent_anchor", due.schedule_id)):
        raise PermissionError("coordinator is not the live top-level worker")
    return {"assignment_ref": due.assignment_ref, "generation": due.generation,
            "occurrence_ref": {"schedule_id": due.schedule_id},
            "result_destination": {"assignment_ref": due.assignment_ref, "generation": due.generation,
                "schedule_id": due.schedule_id, "native_session_id": context["native_session"]["id"]}}


def authorize_worker(service: Any, context: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    state = service.server.state
    if identity(context["project_ref"]) != identity(state["project_ref"]):
        raise PermissionError("worker caller is outside this owner project")
    command = request.get("command")
    if command == "run-worker":
        parent_for_caller(service, context)
        task = state["task_refs"].get(request.get("task"))
        if task is None or identity(task) != identity(context["task_ref"]):
            raise PermissionError("child scope must remain within the coordinating assignment task")
    elif command not in {"lookup-occurrence", "follow-occurrence", "read-result", "read-artifact", "consume-result"}:
        raise PermissionError("worker command does not grant manager review, acceptance or administration")


def check_read(service: Any, context: Any, due: Mapping[str, Any]) -> None:
    if identity(due["target"]["project_ref"]) != identity(service.server.state["project_ref"]):
        raise PermissionError("foreign occurrence scope")
    if context is None or context["role"] == "manager":
        # None is the existing explicit owner-only compatibility lane.
        service.commands._authorize()
        return
    parent = due["target"].get("parent")
    caller_due = service.server.due_port.read_due(context["occurrence_ref"]["schedule_id"])
    destination = None if parent is None else parent["result_destination"]
    if (destination is None or caller_due is None
            or identity(destination["assignment_ref"]) != identity(context["assignment_ref"])
            or destination["generation"] != context["generation"]
            or destination["native_session_id"] != context["native_session"]["id"]
            or destination["schedule_id"] not in {caller_due["schedule_id"], caller_due["target"].get("parent_anchor")}):
        raise PermissionError("result belongs to another exact parent/destination")


def worker_records(service: Any) -> list[Mapping[str, Any]]:
    return list(service.server.due_port.list_due({"project_ref": service.server.state["project_ref"]["id"], "role": "worker"}))


def check_turn_allowance(service: Any) -> None:
    configured = policy(service)
    # Every worker turn intent, including a continuation and UNKNOWN, counts
    # against this existing configured bound. Reads/replay are not new turns.
    records = worker_records(service)
    launches = {row["schedule_id"] for row in records}
    if len(launches) >= configured["cumulative_allowance_units"]:
        raise PermissionError("configured worker allowance exhausted; retained intents and UNKNOWN count")


def check_allowance(service: Any) -> None:
    check_turn_allowance(service)
    # A coordinator yields once for one finite child, never queues recursive
    # copies while its parent turn occupies the only native worker slot.
    if any(row["target"].get("parent") and row["stop_state"] == "active" for row in worker_records(service)):
        raise PermissionError("an existing child intent is active or uncertain; reconcile it first")


def custody_live(service: Any, schedule: str) -> bool:
    reader = getattr(service.host.caller_binding_reader, "live_occurrence", None)
    if not callable(reader):
        raise PermissionError("native process release reader is unavailable; capacity cannot be inferred from settlement")
    return reader(schedule)


def pending(reason: str) -> dict[str, Any]:
    return {"outcome": "pending", "reason": reason, "provider_called": False,
            "effects_started": False, "retry": False}


def child_app(service: Any, due: Mapping[str, Any]) -> Any:
    return service._execution(principal=due["recipient"], model=due["requested_model"],
        reasoning=due["requested_reasoning"], evidence_id=due["schedule_id"],
        selection=(due["target"].get("launch_request") or {}).get("selection"))


def dispatch_occurrence(service: Any, request: Mapping[str, Any], context: Any) -> Mapping[str, Any]:
    command = request["command"]
    if command == "lookup-occurrence":
        if set(request) - {"command", "scope", "request_key", "request_input"}:
            raise ValueError("lookup accepts only exact scope/key/input")
        scope = request["scope"]
        if identity(scope["project_ref"]) != identity(service.server.state["project_ref"]):
            raise PermissionError("lookup scope belongs to another project")
        result = lookup(service.server.due_port, scope=scope, request_key=request["request_key"], request_input=request.get("request_input"))
        if result["outcome"] == "found":
            check_read(service, context, exact_due(service.server.due_port, result["occurrence"]))
        elif context and context["role"] == "worker":
            # Do not disclose foreign intent collisions to an unrelated leaf.
            parent = scope.get("parent") or {}
            if identity(parent.get("assignment_ref", {})) != identity(context["assignment_ref"]) or parent.get("generation") != context["generation"]:
                raise PermissionError("worker lookup requires its own original parent scope")
        return result
    if command == "read-artifact":
        if set(request) - {"command", "occurrence", "artifact_ref", "offset", "max_bytes"}:
            raise ValueError("artifact reads accept only known ref and bounded range")
        due = exact_due(service.server.due_port, request["occurrence"])
        check_read(service, context, due)
        from .occurrence_reads import read_captured_artifact
        return read_captured_artifact(due, artifact_ref=request["artifact_ref"],
            offset=request.get("offset", 0), max_bytes=request.get("max_bytes", 4096))
    if command in {"follow-occurrence", "read-result", "read-artifact", "consume-result"}:
        if set(request) - {"command", "occurrence", "timeout_seconds"}:
            raise ValueError("bounded occurrence handle required")
        timeout = request.get("timeout_seconds", 0)
        if type(timeout) not in {float, int} or not math.isfinite(timeout) or not 0 <= timeout <= 30:
            raise ValueError("follow timeout must be finite and bounded by 30 seconds")
        due = exact_due(service.server.due_port, request["occurrence"])
        check_read(service, context, due)
        result = result_view(due)
        if command == "follow-occurrence":
            result["wait"] = {"state": "snapshot-only", "timeout_seconds": timeout, "detachable": True}
        if command == "consume-result":
            if context is None or context["role"] != "worker":
                raise PermissionError("parent consumption requires an authenticated worker process")
            if not result["required_capture"]:
                return {**result, "outcome": "held", "reason": "required child result is not captured"}
            parent = due["target"]["parent"]
            if not current_parent_slot(service, parent["assignment_ref"], parent["generation"],
                                       parent["occurrence_ref"]["schedule_id"]):
                raise PermissionError("parent was replaced; consumption requires explicit reconciliation")
            result_sha256 = digest((due["host_evidence"]["gateway_attempt"])["result"])
            result_identity = result.get("delivery_identity") or result_sha256
            evidence = {"schema": "otto.parent-consumption.v1", "child": handle(due),
                        "result_sha256": result_sha256, "delivery_identity": result_identity,
                        "caller_assignment_ref": context["assignment_ref"], "caller_generation": context["generation"],
                        "caller_occurrence": context["occurrence_ref"], "native_session": context["native_session"]}
            key = "parent-consumed:" + digest([parent, result_identity])
            app = child_app(service, due)
            report = app.assignments.append_report(ResourceRef.from_dict(context["assignment_ref"]), evidence,
                expected_generation=context["generation"], logical_request_key=key, actor=service.server.binding.authenticated_actor(service.server.state["owner"]))
            receipt = {"state": "consumed", "report_ref": report.ref.to_dict(), "evidence": evidence}
            if (due.get("host_evidence") or {}).get("parent_consumption") != receipt:
                service.server.due_port.save_due(due["schedule_id"], {**due, "host_evidence": {
                    **due["host_evidence"], "parent_consumption": receipt}},
                    request_id=key + ":receipt", expected_version=due["version"])
            result = result_view(service.server.due_port.read_due(due["schedule_id"]))
            result.update(pure=False, effect="record_authenticated_parent_consumption")
        return result
    if set(request) != {"command", "schedule_id"} or context is not None:
        raise PermissionError("retained execution is an internal owner operation")
    service.commands._authorize()
    due = service.server.due_port.read_due(request["schedule_id"])
    if due is None or not due["target"].get("parent") or identity(due["target"]["project_ref"]) != identity(service.server.state["project_ref"]):
        raise PermissionError("retained child occurrence is missing or foreign")
    app = child_app(service, due)
    parent = due["target"]["parent"]
    anchor = app._read(parent["occurrence_ref"]["schedule_id"])
    current = app._current(parent["assignment_ref"], parent["generation"])
    if (not qualified(policy(service), anchor)
            or not current_parent_slot(service, parent["assignment_ref"], parent["generation"], anchor.schedule_id)):
        raise PermissionError("original parent is no longer authorized; explicit reconciliation required")
    if (anchor.stop_state != "completed" or anchor.completion_state != "succeeded" or anchor.in_flight_request is not None
            or custody_live(service, anchor.schedule_id)):
        return pending("exact parent must yield, settle and release native capacity before child execution")
    if command == "start-retained-child":
        for active in worker_records(service):
            if active["schedule_id"] == due["schedule_id"]:
                continue
            if custody_live(service, active["schedule_id"]) or (active["stop_state"] == "active"
                    and (active.get("host_evidence") or {}).get("gateway_attempt")):
                return pending("configured native worker capacity is occupied or uncertain")
        result = app.start(schedule_id=due["schedule_id"])
        if result.get("outcome") in {"succeeded", "replayed"}:
            retained = service.host.submit({"command": "parent-child-result", "schedule_id": due["schedule_id"]})
            fresh = app._read(due["schedule_id"])
            handles = {**(fresh.host_evidence or {}).get("launch_handles", {}), "callback": retained["retained_handle"]}
            if (fresh.host_evidence or {}).get("launch_handles") != handles:
                service.server.due_port.save_due(fresh.schedule_id, replace(fresh,
                    host_evidence={**(fresh.host_evidence or {}), "launch_handles": handles}).to_dict(),
                    request_id="child-callback:" + fresh.schedule_id, expected_version=fresh.version)
            return {**result, "parent_return": retained}
        return result
    if command == "parent-child-result":
        if custody_live(service, due["schedule_id"]):
            return pending("child native process has not released capacity")
        for active in worker_records(service):
            if custody_live(service, active["schedule_id"]) or (active["stop_state"] == "active"
                    and (active.get("host_evidence") or {}).get("gateway_attempt")):
                return pending("native worker capacity has not released for parent continuation")
        # This is the same deterministic continuation identity used by the
        # execution application. Only its first preparation consumes a turn.
        from .execution import _digest
        key = "parent-result:" + _digest([parent, due["schedule_id"],
            ((due.get("host_evidence") or {}).get("gateway_attempt") or {}).get("result")])
        import hashlib
        schedule = "parent-consume-" + hashlib.sha256(key.encode()).hexdigest()[:28]
        if service.server.due_port.read_due(schedule) is None:
            check_turn_allowance(service)
        parent_app = service._execution(principal=anchor.recipient, model=anchor.requested_model,
            reasoning=anchor.requested_reasoning, evidence_id=anchor.schedule_id,
            selection=(anchor.target.get("launch_request") or {}).get("selection"))
        return parent_app.continue_worker_from_child(parent_schedule_id=anchor.schedule_id, child_schedule_id=due["schedule_id"])
    raise ValueError("unknown occurrence operation")
