"""Exact owner retirement of a terminal native capacity failure, without replay."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import hashlib
from pathlib import Path
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .execution import _digest
from .execution_operations import OccurrencePreparationError

SCHEMA = "otto.worker-capacity-custody-disposition.v1"
CAPACITY = "Selected model is at capacity. Please try a different model."


def _require(condition, message):
    if not condition:
        raise OccurrencePreparationError(message)


def _events(envelope):
    stdout = envelope.get("stdout")
    _require(isinstance(stdout, str) and len(stdout.encode()) <= 4096,
             "bounded retained native JSONL is required")
    try:
        return [json.loads(line) for line in stdout.splitlines() if line]
    except (TypeError, ValueError) as exc:
        raise OccurrencePreparationError("retained native JSONL is malformed") from exc


def _terminal(envelope, receipt, *, session, principal, operation, status, code):
    _require(envelope.get("fnd_receipt") == receipt and receipt.get("identity") == {
        "logical_agent_id": principal, "physical_session_id": session}, "native receipt identity differs")
    _require(all(envelope.get(k) == v for k, v in {
        "physical_session_id": session, "logical_agent_id": principal, "owner": principal,
        "transport_operation": operation, "status": status, "exit_status": code,
        "runner": "codex-cli", "stderr": "", "result_ref": None,
        "timeout": None, "cancel": None}.items()), "native terminal envelope differs")
    _require(receipt.get("operation") == operation and receipt.get("outcome") == status
        and receipt.get("process_id") == envelope.get("process_id")
        and isinstance(receipt.get("process_id"), str) and receipt["process_id"].isdigit()
        and receipt.get("result_ref") is None, "native terminal process receipt differs")
    try:
        start, end = (datetime.fromisoformat(envelope[k].replace("Z", "+00:00"))
                      for k in ("started_at", "ended_at"))
        _require(start.tzinfo is not None and end.tzinfo is not None and end >= start,
                 "native terminal timestamps are invalid")
    except (KeyError, TypeError, ValueError) as exc:
        raise OccurrencePreparationError("native terminal timestamps are missing") from exc
    return start, end


def _native_terminal_trace(execution, session, initial_turn, work_turn):
    reader = getattr(execution.runtime.adapter, "trusted_thread_reader", None)
    _require(callable(reader), "trusted exact native metadata reader is required")
    thread = (reader(session) or {}).get("thread") or {}
    _require(thread.get("id") == session and isinstance(thread.get("path"), str),
             "trusted native session metadata differs")
    raw = Path(thread["path"]).read_bytes()
    _require(len(raw) <= 2 * 1024 * 1024, "native retirement trace exceeds the bounded limit")
    try:
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except ValueError as exc:
        raise OccurrencePreparationError("trusted native trace is malformed") from exc
    active, starts, terminal, metadata = set(), [], [], []
    for record in records:
        payload = record.get("payload") or {}
        kind, turn = record.get("type"), payload.get("turn_id")
        if kind == "session_meta":
            metadata.append(payload.get("id") or payload.get("session_id"))
        _require(kind in {"session_meta", "event_msg", "response_item", "world_state",
                          "turn_context", "token_usage_record"}, "unrecognized native trace record")
        if kind == "response_item":
            _require(payload.get("type") == "message", "native trace contains task tool/effect records")
            if payload.get("role") == "assistant":
                _require(active == {initial_turn}
                    and payload.get("content") == [{"type": "output_text", "text": "READY"}],
                         "native trace contains task assistant work")
        if kind == "event_msg":
            event = payload.get("type")
            if event == "task_started":
                _require(not active and turn in {initial_turn, work_turn}, "native turn is active or foreign")
                active.add(turn); starts.append(turn)
            elif event in {"task_complete", "task_aborted"}:
                _require(event == "task_complete" and turn in active, "native terminal turn differs")
                active.remove(turn); terminal.append(payload)
            elif event == "item_completed":
                _require(turn in active and payload.get("thread_id") == session,
                         "native item belongs to a foreign turn")
                item = payload.get("item") or {}
                _require(item.get("type") == "UserMessage" or turn == initial_turn
                    and item.get("type") == "AgentMessage" and item.get("content") == [
                        {"type": "Text", "text": "READY"}], "native task turn contains work or tool effects")
            else:
                _require(event in {"token_count", "thread_settings_applied"}, "unrecognized native effect evidence")
    _require(metadata == [session] and not active and starts == [initial_turn, work_turn]
        and len(terminal) == 2 and terminal[0].get("last_agent_message") == "READY"
        and terminal[0].get("error") is None and terminal[1].get("last_agent_message") is None
        and terminal[1].get("error") == {"message": CAPACITY, "codex_error_info": "server_overloaded"},
        "native trace does not prove latest terminal capacity-before-work without overlap")
    return hashlib.sha256(raw).hexdigest()


def inspect_capacity_failed_worker(execution, *, schedule_id: str) -> dict[str, Any]:
    """Qualify trusted retained owner/native bytes; never infer success or retry."""
    due = execution._read(schedule_id)
    _require(execution.actor == due.lifecycle_owner == due.owner == due.manager_ref,
             "only the occurrence lifecycle owner may release custody")
    assignment = execution._current(due.assignment_ref, due.generation)
    attempt = (due.host_evidence or {}).get("gateway_attempt") or {}
    result = attempt.get("result") or {}
    raw = result.get("raw_result") or {}
    authorization = raw.get("owner_delivery_authorization") or {}
    session = result.get("physical_session_id")
    _require(due.role == "worker" and assignment.role in {"worker", "executor"}
        and assignment.principal == due.recipient
        and assignment.payload.get("manager") == execution.manager_actor
        and due.stop_state == "active" and due.completion_state == "none"
        and attempt.get("state") == "result" and isinstance(session, str) and session
        and attempt.get("physical_session_id") == session,
        "worker custody is not the current terminal owner attempt")
    for body in (attempt, result):
        _require(body.get("assignment_ref") == due.assignment_ref
            and body.get("generation") == due.generation
            and body.get("logical_request_key") == due.in_flight_request,
            "retained attempt request/assignment pins differ")
    _require(result.get("outcome") == "unknown" and result.get("delivery_state") == "unknown"
        and result.get("context_digest_verified") is False
        and (result.get("error") or {}).get("code") == "authorized_result_unverified"
        and result.get("logical_agent_id") == due.recipient
        and result.get("project_ref") == due.target["project_ref"]
        and result.get("task_ref") == due.target["task_ref"]
        and result.get("operation") == "invoke"
        and result.get("requested_model") == due.requested_model
        and result.get("requested_reasoning") == due.requested_reasoning
        and result.get("requested_profile") == due.profile
        and result.get("native_session_id") == session
        and raw.get("transport_operation") == "resume"
        and raw.get("worker_content") == [] and raw.get("task_bound_evidence") is None,
        "unknown retained result does not match the worker occurrence")
    expected = {"status": "authorized", "logical_request_key": due.in_flight_request,
        "physical_session_id": session, "project_ref": due.target["project_ref"],
        "task_ref": due.target["task_ref"], "assignment_ref": due.assignment_ref,
        "generation": due.generation, "role": "worker", "principal": due.recipient,
        "lifecycle_owner": execution.actor}
    _require(attempt.get("delivery_authorization") == authorization and all(
        type(authorization.get(k)) is type(v) and authorization.get(k) == v for k, v in expected.items()),
        "exact retained owner delivery authorization is missing")
    init, work = raw.get("initialization_envelope") or {}, raw.get("work_envelope") or {}
    init_receipt, work_receipt = raw.get("initialization_receipt") or {}, raw.get("work_receipt") or {}
    _, init_end = _terminal(init, init_receipt, session=session, principal=due.recipient,
                           operation="invoke", status="succeeded", code=0)
    work_start, _ = _terminal(work, work_receipt, session=session, principal=due.recipient,
                             operation="resume", status="failed", code=1)
    _require(init_end <= work_start and init["process_id"] != work["process_id"],
             "native initialization/work process order differs")
    initial, failed = _events(init), _events(work)
    _require(len(initial) == 4 and initial[:2] == [
        {"type": "thread.started", "thread_id": session}, {"type": "turn.started"}]
        and initial[2].get("type") == "item.completed"
        and initial[2].get("item") == {"id": "item_0", "type": "agent_message", "text": "READY"}
        and initial[3].get("type") == "turn.completed"
        and set(initial[3]) <= {"type", "usage"}, "initialization is not terminal READY-only native evidence")
    _require(failed == [{"type": "thread.started", "thread_id": session}, {"type": "turn.started"},
        {"type": "error", "message": CAPACITY}, {"type": "turn.failed", "error": {"message": CAPACITY}}],
        "exact capacity-before-work native terminal sequence is required")
    for envelope, created in ((init, True), (work, False)):
        host = envelope.get("host_evidence") or {}
        candidate = host.get("native_candidate") or {}
        _require(host.get("session_id") == session and host.get("process_started") is True
            and host.get("session_created") is created and host.get("invocation_turn_verified") is True
            and host.get("provenance") == "host_native_jsonl"
            and isinstance(host.get("turn_id"), str) and host["turn_id"]
            and candidate.get("task_bound") is False
            and candidate.get("status") == "unsupported" and candidate.get("retry_allowed") is False,
            "trusted native terminal evidence is incomplete")
    _require(work["host_evidence"]["turn_id"] == result.get("observed_turn_id")
        and raw.get("native_candidate") == work["host_evidence"]["native_candidate"]
        and raw["native_candidate"].get("native_records") == []
        and work_receipt.get("unsupported_reason") == "codex_execution_failed",
        "failed task turn candidate differs")
    for other in execution.due_port.list_due():
        other_attempt = (other.get("host_evidence") or {}).get("gateway_attempt") or {}
        _require(other.get("schedule_id") == schedule_id or other.get("project_ref") != due.project_ref
            or not (other_attempt.get("state") == "claimed" or other.get("stop_state") == "active"
                and other.get("in_flight_request") and other_attempt.get("state") != "result"),
            "another owner provider occurrence is in flight or admitted without terminal evidence")
    trace_sha = _native_terminal_trace(execution, session, init["host_evidence"]["turn_id"],
                                       result["observed_turn_id"])
    return {"outcome": "qualified", "schedule_id": schedule_id, "due_version": due.version,
        "native_trace_sha256": trace_sha,
        "due_sha256": _digest(due.to_dict()), "unknown_result_sha256": _digest(result),
        "assignment_ref": due.assignment_ref, "generation": due.generation,
        "project_ref": due.target["project_ref"], "task_ref": due.target["task_ref"],
        "principal": due.recipient, "model": due.requested_model, "reasoning": due.requested_reasoning,
        "native_session_id": session, "native_turn_id": result["observed_turn_id"],
        "initialization_process_id": init["process_id"], "work_process_id": work["process_id"],
        "native_terminal_proved": True, "task_work_started": False,
        "historical_unknown_preserved": True, "provider_retry_allowed": False}


def release_capacity_failed_worker(execution, *, schedule_id: str, request_key: str,
                                   fresh_request_key: str, expected_due_sha256: str,
                                   expected_unknown_result_sha256: str) -> dict[str, Any]:
    """Stop exact old custody and reserve one distinct normal-route occurrence."""
    for key in (request_key, fresh_request_key):
        _require(isinstance(key, str) and key == key.strip() and 0 < len(key) <= 160,
                 "release and fresh request keys must be exact nonblank text")
    due = execution._read(schedule_id)
    marker = (due.host_evidence or {}).get("worker_custody_release")
    if marker:
        receipt = retained_capacity_release(execution, due)
        _require(receipt["request_key"] == request_key
            and receipt["fresh_request_key"] == fresh_request_key
            and receipt["scope"]["due_sha256"] == expected_due_sha256
            and receipt["scope"]["unknown_result_sha256"] == expected_unknown_result_sha256,
            "release request changed after custody settlement")
        return {"outcome": "replayed", **marker, "provider_called": False}
    scope = inspect_capacity_failed_worker(execution, schedule_id=schedule_id)
    _require(scope["due_sha256"] == expected_due_sha256
        and scope["unknown_result_sha256"] == expected_unknown_result_sha256,
        "retained worker release pins are stale")
    _require(fresh_request_key != request_key
        and fresh_request_key + ":launch" != due.in_flight_request,
        "fresh admission must use a distinct request key")
    body = {"schema": SCHEMA, "request_key": request_key, "fresh_request_key": fresh_request_key,
        "scope": scope, "route": "normal", "fresh_occurrence_limit": 1,
        "historical_unknown_preserved": True, "provider_retry_allowed": False,
        "before": {k: due.to_dict()[k] for k in ("stop_state", "completion_state", "in_flight_request")}}
    report = execution.assignments.append_report(ResourceRef.from_dict(due.assignment_ref), body,
        expected_generation=due.generation, logical_request_key=request_key,
        actor=execution.binding.authenticated_actor(execution.actor))
    _require(_digest(execution._read(schedule_id).to_dict()) == expected_due_sha256,
             "owner occurrence changed before custody stop")
    marker = {"schema": SCHEMA, "disposition_ref": report.ref.to_dict(),
        "fresh_request_key": fresh_request_key, "historical_unknown_preserved": True,
        "provider_retry_allowed": False}
    stopped = replace(due, stop_state="stopped", completion_state="unknown", in_flight_request=None,
                      host_evidence={**due.host_evidence, "worker_custody_release": marker})
    saved = execution.due_port.save_due(schedule_id, stopped.to_dict(),
        request_id=request_key + ":stop", expected_version=due.version)
    return {"outcome": "released", "schedule_id": schedule_id, "due_version": saved["version"],
            **marker, "provider_called": False, "task_completion_recorded": False}


def retained_capacity_release(execution, due):
    """Read the canonical disposition and verify that only custody changed."""
    marker = (due.host_evidence or {}).get("worker_custody_release") or {}
    _require(marker.get("schema") == SCHEMA and due.stop_state == "stopped"
        and due.completion_state == "unknown" and due.in_flight_request is None
        and execution.actor == due.lifecycle_owner, "worker has no owner-reconciled custody release")
    execution._current(due.assignment_ref, due.generation)
    rows = execution.assignments.list_observations(ResourceRef.from_dict(due.assignment_ref), kind="report")
    report = next((r for r in rows if r.ref.to_dict() == marker.get("disposition_ref")), None)
    _require(report is not None, "canonical worker custody disposition is missing")
    body = report.value
    scope = body.get("scope") or {}
    _require(body.get("schema") == SCHEMA and body.get("route") == "normal"
        and body.get("fresh_occurrence_limit") == 1
        and body.get("fresh_request_key") == marker.get("fresh_request_key"),
        "canonical custody disposition differs")
    before_host = {k: v for k, v in due.host_evidence.items() if k != "worker_custody_release"}
    before = replace(due, **body["before"], version=scope["due_version"], host_evidence=before_host)
    _require(_digest(before.to_dict()) == scope.get("due_sha256")
        and _digest(before_host["gateway_attempt"]["result"]) == scope.get("unknown_result_sha256"),
        "retired occurrence or historical UNKNOWN changed")
    raw = before_host["gateway_attempt"]["result"]["raw_result"]
    _require(_native_terminal_trace(execution, scope["native_session_id"],
        raw["initialization_envelope"]["host_evidence"]["turn_id"], scope["native_turn_id"])
        == scope["native_trace_sha256"], "native session changed after custody disposition")
    return body


def permits_fresh_worker(execution, due, *, request, model, reasoning):
    try:
        body = retained_capacity_release(execution, due)
    except (ValueError, KeyError, TypeError):
        return False
    scope = body["scope"]
    return (request.get("request_key") == body["fresh_request_key"]
        and request.get("route") == body["route"]
        and request.get("principal") == scope["principal"]
        and model == scope["model"] and reasoning == scope["reasoning"])
