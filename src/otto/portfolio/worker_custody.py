"""Exact owner retirement of a terminal native capacity failure, without replay."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .execution import _digest
from .execution_operations import OccurrencePreparationError

SCHEMA = "otto.worker-capacity-custody-disposition.v1"
INITIALIZER_SCHEMA = "otto.worker-initializer-custody-disposition.v1"
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


def _initializer_diagnostics(stderr):
    if stderr == '':
        return 'empty'
    if isinstance(stderr,str) and len(stderr.encode()) <= 4096 and re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ERROR codex_core::session::session: failed to load skill /[^\n]+/SKILL\.md: missing YAML frontmatter delimited by ---\n',stderr):
        return 'codex.skill_loader_missing_frontmatter'
    return None


def _terminal(envelope, receipt, *, session, principal, operation, status, code, initializer_diagnostics=False):
    _require(envelope.get("fnd_receipt") == receipt and receipt.get("identity") == {
        "logical_agent_id": principal, "physical_session_id": session}, "native receipt identity differs")
    _require(all(envelope.get(k) == v for k, v in {
        "physical_session_id": session, "logical_agent_id": principal, "owner": principal,
        "transport_operation": operation, "status": status, "exit_status": code,
        "runner": "codex-cli", "result_ref": None,
        "timeout": None, "cancel": None}.items()), "native terminal envelope differs")
    _require(envelope.get('stderr')=='' or initializer_diagnostics and _initializer_diagnostics(envelope.get('stderr')) is not None,
        'native diagnostics are fatal, ambiguous or outside exact classified skill-loader scope')
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


def _native_terminal_trace(execution, session, initial_turn, work_turn, *, model=None, reasoning=None, profile=None):
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
    active, starts, terminal, metadata, contexts, inert_messages = set(), [], [], [], [], []
    for record in records:
        payload = record.get("payload") or {}
        kind, turn = record.get("type"), payload.get("turn_id")
        if kind == "session_meta":
            metadata.append(payload.get("id") or payload.get("session_id"))
        if kind == 'turn_context':
            contexts.append(payload)
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
                if item.get('type')=='UserMessage':
                    inert_messages.append(item.get('content'))
                _require(item.get("type") == "UserMessage" or turn == initial_turn
                    and item.get("type") == "AgentMessage" and item.get("content") == [
                        {"type": "Text", "text": "READY"}], "native task turn contains work or tool effects")
            else:
                _require(event in {"token_count", "thread_settings_applied"}, "unrecognized native effect evidence")
    _require(metadata == [session] and not active and starts == ([initial_turn] if work_turn is None else [initial_turn, work_turn])
        and len(terminal) == (1 if work_turn is None else 2) and terminal[0].get("last_agent_message") == "READY"
        and terminal[0].get("error") is None and (work_turn is None or terminal[1].get("last_agent_message") is None
        and terminal[1].get("error") == {"message": CAPACITY, "codex_error_info": "server_overloaded"}),
        "native trace does not prove latest terminal capacity-before-work without overlap")
    if work_turn is None:
        _require(len(contexts)==1 and contexts[0].get('turn_id')==initial_turn
            and contexts[0].get('model')==model
            and (contexts[0].get('collaboration_mode')or{}).get('settings',{}).get('reasoning_effort')==reasoning
            and (contexts[0].get('sandbox_policy')or{}).get('type')==profile
            and inert_messages==[[{'type':'text','text':'Initialize this session only. Do not read files, use tools, execute commands, or perform task work. Return READY.','text_elements':[]}]],
            'initializer native model/profile or exact inert owner request differs')
    return hashlib.sha256(raw).hexdigest()


def inspect_capacity_failed_worker(execution, *, schedule_id: str, _initializer_only=False, _due=None) -> dict[str, Any]:
    """Qualify trusted retained owner/native bytes; never infer success or retry."""
    due = _due or execution._read(schedule_id)
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
                           operation="invoke", status="succeeded", code=0, initializer_diagnostics=_initializer_only)
    if _initializer_only:
        _require(all(work.get(k) is None and work_receipt.get(k) is None for k in ('process_id','result_ref'))
            and work.get('command') is None and work.get('host_evidence') is None
            and work.get('delivery_state') == 'not_started' and work.get('unsupported_error') == 'recipient_context_unavailable'
            and work.get('reconciliation') == 'trusted recipient authorization is not exact'
            and work_receipt.get('unsupported_reason') == 'recipient_context_unavailable'
            and work_receipt.get('outcome') == 'unknown' and work_receipt.get('operation') == 'resume'
            and work.get('fnd_receipt') == work_receipt
            and work_receipt.get('identity') == {'logical_agent_id':due.recipient,'physical_session_id':session}
            and result.get('observed_turn_id') is None and result.get('task_bound_evidence') is None,
            'resume evidence does not prove exact rejection before process creation')
        initial = _events(init)
        _require(len(initial)==4 and initial[:2]==[{'type':'thread.started','thread_id':session},{'type':'turn.started'}]
            and initial[2]=={'type':'item.completed','item':{'id':'item_0','type':'agent_message','text':'READY'}}
            and initial[3].get('type')=='turn.completed' and set(initial[3]) <= {'type','usage'},
            'initialization is not terminal READY-only evidence')
        host=init.get('host_evidence')or{}
        _require(host.get('session_id')==session and host.get('session_created')is True
            and host.get('process_started')is True and host.get('invocation_turn_verified')is True
            and host.get('provenance')=='host_native_jsonl' and isinstance(host.get('turn_id'),str)
            and init.get('observed_model')==due.requested_model and init.get('observed_reasoning')==due.requested_reasoning,
            'initializer native identity/model evidence differs')
    else:
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
            or not (other_attempt.get("state") == "claimed" or (not _initializer_only or other_attempt) and other.get("stop_state") == "active"
                and other.get("in_flight_request") and other_attempt.get("state") != "result"),
            "another owner provider occurrence is in flight or admitted without terminal evidence")
    trace_sha = _native_terminal_trace(execution, session, init["host_evidence"]["turn_id"],
                                       None if _initializer_only else result["observed_turn_id"],
                                       model=due.requested_model,reasoning=due.requested_reasoning,profile=due.profile)
    return {"outcome": "qualified", "schedule_id": schedule_id, "due_version": due.version,
        "initializer_diagnostics_sha256": hashlib.sha256(init.get('stderr','').encode()).hexdigest(),
        "initializer_diagnostics_classification": _initializer_diagnostics(init.get('stderr')),
        "native_trace_sha256": trace_sha,
        "due_sha256": _digest(due.to_dict()), "unknown_result_sha256": _digest(result),
        "assignment_ref": due.assignment_ref, "generation": due.generation,
        "project_ref": due.target["project_ref"], "task_ref": due.target["task_ref"],
        "principal": due.recipient, "model": due.requested_model, "reasoning": due.requested_reasoning,
        "native_session_id": session, "native_turn_id": result["observed_turn_id"],
        "initialization_process_id": init["process_id"], "work_process_id": work.get("process_id"),
        "native_terminal_proved": True, "task_work_started": False,
        "historical_unknown_preserved": True, "provider_retry_allowed": False}


def release_capacity_failed_worker(execution, *, schedule_id: str, request_key: str,
                                   fresh_request_key: str, expected_due_sha256: str,
                                   expected_unknown_result_sha256: str, _initializer_only=False) -> dict[str, Any]:
    """Stop exact old custody and reserve one distinct normal-route occurrence."""
    for key in (request_key, fresh_request_key):
        _require(isinstance(key, str) and key == key.strip() and 0 < len(key) <= 160,
                 "release and fresh request keys must be exact nonblank text")
    due = execution._read(schedule_id)
    marker = (due.host_evidence or {}).get("worker_custody_release")
    if marker:
        receipt = retained_capacity_release(execution, due, _initializer_only=_initializer_only)
        _require(receipt["request_key"] == request_key
            and receipt["fresh_request_key"] == fresh_request_key
            and receipt["scope"]["due_sha256"] == expected_due_sha256
            and receipt["scope"]["unknown_result_sha256"] == expected_unknown_result_sha256,
            "release request changed after custody settlement")
        return {"outcome": "replayed", **marker, "provider_called": False}
    scope = inspect_capacity_failed_worker(execution, schedule_id=schedule_id, _initializer_only=_initializer_only)
    _require(scope["due_sha256"] == expected_due_sha256
        and scope["unknown_result_sha256"] == expected_unknown_result_sha256,
        "retained worker release pins are stale")
    _require(fresh_request_key != request_key
        and fresh_request_key + ":launch" != due.in_flight_request,
        "fresh admission must use a distinct request key")
    schema = INITIALIZER_SCHEMA if _initializer_only else SCHEMA
    body = {"schema": schema, "request_key": request_key, "fresh_request_key": fresh_request_key,
        "scope": scope, "route": "normal", "fresh_occurrence_limit": 1,
        "historical_unknown_preserved": True, "provider_retry_allowed": False,
        "before": {k: due.to_dict()[k] for k in ("stop_state", "completion_state", "in_flight_request")}}
    if _initializer_only:
        body['recovery_mode']='same-assignment-initialized-session'
        body['initializer_replay_allowed']=False
        body['initializer_provider_occurred']=True
    report = execution.assignments.append_report(ResourceRef.from_dict(due.assignment_ref), body,
        expected_generation=due.generation, logical_request_key=request_key,
        actor=execution.binding.authenticated_actor(execution.actor))
    _require(_digest(execution._read(schedule_id).to_dict()) == expected_due_sha256,
             "owner occurrence changed before custody stop")
    marker = {"schema": schema, "disposition_ref": report.ref.to_dict(),
        "fresh_request_key": fresh_request_key, "historical_unknown_preserved": True,
        "provider_retry_allowed": False}
    stopped = replace(due, stop_state="stopped", completion_state="unknown", in_flight_request=None,
                      host_evidence={**due.host_evidence, "worker_custody_release": marker})
    saved = execution.due_port.save_due(schedule_id, stopped.to_dict(),
        request_id=request_key + ":stop", expected_version=due.version)
    return {"outcome": "released", "schedule_id": schedule_id, "due_version": saved["version"],
            **marker, "provider_called": False, "task_completion_recorded": False}


def retained_capacity_release(execution, due, *, _initializer_only=False):
    """Read the canonical disposition and verify that only custody changed."""
    marker = (due.host_evidence or {}).get("worker_custody_release") or {}
    schema=INITIALIZER_SCHEMA if _initializer_only else SCHEMA
    _require(marker.get("schema") == schema and due.stop_state == "stopped"
        and due.completion_state == "unknown" and due.in_flight_request is None
        and execution.actor == due.lifecycle_owner, "worker has no owner-reconciled custody release")
    execution._current(due.assignment_ref, due.generation)
    rows = execution.assignments.list_observations(ResourceRef.from_dict(due.assignment_ref), kind="report")
    report = next((r for r in rows if r.ref.to_dict() == marker.get("disposition_ref")), None)
    _require(report is not None, "canonical worker custody disposition is missing")
    body = report.value
    scope = body.get("scope") or {}
    _require(body.get("schema") == schema and body.get("route") == "normal"
        and body.get("fresh_occurrence_limit") == 1
        and body.get("fresh_request_key") == marker.get("fresh_request_key"),
        "canonical custody disposition differs")
    before_host = {k: v for k, v in due.host_evidence.items() if k != "worker_custody_release"}
    before = replace(due, **body["before"], version=scope["due_version"], host_evidence=before_host)
    _require(_digest(before.to_dict()) == scope.get("due_sha256")
        and _digest(before_host["gateway_attempt"]["result"]) == scope.get("unknown_result_sha256"),
        "retired occurrence or historical UNKNOWN changed")
    if _initializer_only:
        reader=execution.portfolio.operations._owner_reader
        _require(body.get('recovery_mode')=='same-assignment-initialized-session'
            and body.get('initializer_replay_allowed')is False and body.get('initializer_provider_occurred')is True
            and any(e.operation=='work.report.append' and e.actor==execution.binding.authenticated_actor(execution.actor)
                for e in reader.list_events(subjects=(report.ref,))), 'initializer recovery lacks authenticated owner disposition')
        _require(inspect_capacity_failed_worker(execution,schedule_id=due.schedule_id,_initializer_only=True,_due=before)==scope,
            'retained initializer-only qualification changed')
    raw = before_host["gateway_attempt"]["result"]["raw_result"]
    _require(_native_terminal_trace(execution, scope["native_session_id"],
        raw["initialization_envelope"]["host_evidence"]["turn_id"], None if _initializer_only else scope["native_turn_id"],
        model=before.requested_model,reasoning=before.requested_reasoning,profile=before.profile)
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


def initialized_worker_continuity(execution, assignment, due, session, request_key):
    """Owner-only, one reserved delivery in the exact READY-initialized session."""
    body=retained_capacity_release(execution,due,_initializer_only=True)
    scope=body['scope']
    _require(request_key==body['fresh_request_key'] and assignment.ref.to_dict()==scope['assignment_ref']
        and assignment.generation==scope['generation'] and assignment.principal==scope['principal']
        and session==scope['native_session_id'],'initialized continuation differs from reserved exact identity/key')
    return body


def inspect_initialized_worker(execution, *, schedule_id):
    return inspect_capacity_failed_worker(execution,schedule_id=schedule_id,_initializer_only=True)


def release_initialized_worker(execution, **request):
    return release_capacity_failed_worker(execution,**request,_initializer_only=True)

# A precise Codex guard exception precedes every initializer/native binding.
# This does not generalize FAILED, absent sessions, or UNKNOWN into no effect.
PREINITIALIZATION_SCHEMA = 'otto.role-preinitialization-custody-disposition.v1'
DRAIN_PREINITIALIZATION_SCHEMA = 'otto.worker-drain-preinitialization-custody-disposition.v1'
DRAIN_PREINITIALIZATION_ERROR = {'code':'adapter_error','message':'execution host is draining; no new child may be admitted','operation':'invoke'}
PREINITIALIZATION_ERROR = {'code':'adapter_error','message':'owner workspace contract is unsupported before initialization','operation':'invoke'}

def inspect_preinitialization_role(execution, *, schedule_id, _due=None, _drain_worker=False):
    due=_due or execution._read(schedule_id)
    _require(execution.actor==due.lifecycle_owner==due.owner==due.manager_ref,
             'current lifecycle owner required')
    assignment=execution.assignments.get(ResourceRef.from_dict(due.assignment_ref))
    if _due is not None and assignment.ref.to_dict()!=due.assignment_ref:
        from .operating_setup import authenticated_adoption_ancestor
        _require(authenticated_adoption_ancestor({'ref':assignment.ref.to_dict(),
            'principal':assignment.principal,'role':assignment.role,'generation':assignment.generation,
            'payload':assignment.payload},due.assignment_ref,execution.portfolio.operations._owner_reader),
            'historical guard requires authenticated consecutive same-generation adoption')
        assignment=execution._current(assignment.ref.to_dict(),due.generation)
    else:
        assignment=execution._current(due.assignment_ref,due.generation)
    attempt=(due.host_evidence or {}).get('gateway_attempt') or {}
    result=attempt.get('result') or {}
    from otto.agents.herzchen_adapter import HerzchenCodexAdapter
    import inspect
    adapter=execution.runtime.adapter
    _require(isinstance(adapter,HerzchenCodexAdapter)
        and type(adapter)._invoke_owner_authorized is HerzchenCodexAdapter._invoke_owner_authorized,
        'only the maintained exact Codex preinitialization guard qualifies')
    role = 'worker' if _drain_worker else 'manager'
    mode = 'fresh_bounded_worker' if _drain_worker else 'fresh_manager'
    expected_error = DRAIN_PREINITIALIZATION_ERROR if _drain_worker else PREINITIALIZATION_ERROR
    if _drain_worker:
        from .execution_host import ExecutionHost
        _require(type(adapter).owner_transport_only is True, 'maintained transport-only Codex adapter required')
        guard = ExecutionHost.retain
    else:
        guard = HerzchenCodexAdapter._invoke_owner_authorized
    _require(due.role==role and assignment.role in ({'worker','executor'} if _drain_worker else {'manager'})
        and assignment.principal==due.recipient and (_due is not None or assignment.session is None)
        and due.execution_mode==mode and due.stop_state=='active'
        and due.completion_state=='none' and due.in_flight_request
        and not any(k in due.target for k in ('native_id','native_session_id','physical_session_id','native_binding')),
        'only an exact original fresh uninitialized occurrence qualifies')
    allowed={'assignment_ref','delivery_state','error','generation','logical_agent_id','logical_request_key',
        'native_session_id','observed_model','observed_reasoning','operation','outcome','owner','physical_session_id',
        'project_ref','replayed','request_fingerprint','requested_model','requested_profile','requested_reasoning',
        'resource_evidence','task_ref','timeout','unknown_reason'}
    _require(set(result)<=allowed and attempt.get('state')=='result'
        and result.get('outcome')=='failed' and result.get('operation')=='invoke'
        and result.get('error')==expected_error
        and result.get('unknown_reason')==expected_error['message']
        and result.get('delivery_state')=='unknown' and result.get('replayed') is False
        and result.get('timeout') is False
        and all(result.get(k) is None for k in ('physical_session_id','native_session_id','observed_model','observed_reasoning'))
        and all(attempt.get(k) is None for k in ('physical_session_id','delivery_authorization','delivery_admission','manager_acceptance')),
        'failed result is not exact guard-before-initializer evidence')
    for body in(attempt,result):
        _require(body.get('assignment_ref')==due.assignment_ref and body.get('generation')==due.generation
            and body.get('logical_request_key')==due.in_flight_request,'original canonical attempt binding differs')
    _require(result.get('logical_agent_id')==result.get('owner')==due.recipient
        and result.get('project_ref')==due.target['project_ref'] and result.get('task_ref')==due.target['task_ref']
        and result.get('requested_model')==due.requested_model and result.get('requested_reasoning')==due.requested_reasoning
        and result.get('requested_profile')==due.profile,'original role/project/task/model scope differs')
    brief=(result.get('resource_evidence') or {}).get('brief') or {}
    snapshot=(brief.get('context')or{}).get('canonical_snapshot')or{}
    _require(snapshot.get('native_session') is None and snapshot.get('assignment_ref')==due.assignment_ref
        and snapshot.get('generation')==due.generation and snapshot.get('task_ref')==due.target['task_ref'],
        'retained canonical fresh-role evidence differs')
    return {'schedule_id':schedule_id,'due_version':due.version,'due_sha256':_digest(due.to_dict()),
        'result_sha256':_digest(result),'assignment_ref':due.assignment_ref,'generation':due.generation,
        'project_ref':due.target['project_ref'],'task_ref':due.target['task_ref'],'principal':due.recipient,
        'guard_sha256':hashlib.sha256(inspect.getsource(guard).encode()).hexdigest(),
        **({'allowance_ref':due.allowance_ref,'role':'worker','model':due.requested_model,'reasoning':due.requested_reasoning,'profile':due.profile} if _drain_worker else {}),
        'initializer_occurred':False,'native_effect_occurred':False}

def retained_preinitialization_release(execution,due):
    marker=(due.host_evidence or{}).get('role_preinitialization_custody_release')or{}
    drain_worker = marker.get('schema') == DRAIN_PREINITIALIZATION_SCHEMA
    schema = DRAIN_PREINITIALIZATION_SCHEMA if drain_worker else PREINITIALIZATION_SCHEMA
    _require(marker.get('schema')==schema and due.stop_state=='stopped'
        and due.in_flight_request is None,'exact retired preinitialization custody required')
    reader=execution.portfolio.operations._owner_reader
    report=reader.get_record(ResourceRef.from_dict(marker['disposition_ref']))
    _require(report is not None and report.ref.to_dict()==marker['disposition_ref']
        and report.payload.get('record_type')=='work.observation'
        and report.payload.get('observation_kind')=='report'
        and report.payload.get('assignment')==due.assignment_ref
        and report.payload.get('generation')==due.generation,'canonical exact historical disposition missing')
    body=report.payload['value'];scope=body.get('scope')or{}
    _require(body.get('schema')==schema and body.get('fresh_occurrence_limit')==1
        and body.get('fresh_request_key')==marker.get('fresh_request_key') and body.get('provider_retry_allowed')is False,
        'canonical finite preinitialization disposition differs')
    host={k:v for k,v in due.host_evidence.items()if k!='role_preinitialization_custody_release'}
    before=replace(due,**body['before'],version=scope['due_version'],host_evidence=host)
    _require(inspect_preinitialization_role(execution,schedule_id=due.schedule_id,_due=before,_drain_worker=drain_worker)==scope,
        'original failed guard evidence changed')
    _require(any(e.operation=='work.report.append'and e.actor==execution.binding.authenticated_actor(execution.actor)
        for e in reader.list_events(subjects=(report.ref,))), 'disposition lacks authenticated lifecycle-owner event')
    return body

def release_preinitialization_role(execution,*,schedule_id,request_key,fresh_request_key,_drain_worker=False):
    _require(isinstance(request_key,str)and request_key.strip()==request_key and request_key
        and isinstance(fresh_request_key,str)and fresh_request_key.strip()==fresh_request_key and fresh_request_key!=request_key,
        'distinct finite exact disposition/delivery keys required')
    due=execution._read(schedule_id)
    if(due.host_evidence or{}).get('role_preinitialization_custody_release'):
        body=retained_preinitialization_release(execution,due)
        _require(body['request_key']==request_key and body['fresh_request_key']==fresh_request_key,'disposition replay input changed')
        return {'outcome':'replayed',**due.host_evidence['role_preinitialization_custody_release'],'provider_called':False}
    schema = DRAIN_PREINITIALIZATION_SCHEMA if _drain_worker else PREINITIALIZATION_SCHEMA
    scope=inspect_preinitialization_role(execution,schedule_id=schedule_id,_drain_worker=_drain_worker)
    body={'schema':schema,'request_key':request_key,'fresh_request_key':fresh_request_key,
        'scope':scope,'fresh_occurrence_limit':1,'provider_retry_allowed':False,'historical_failed_unknown_preserved':True,
        'before':{k:due.to_dict()[k]for k in('stop_state','completion_state','in_flight_request')}}
    current=execution._current(due.assignment_ref,due.generation)
    report=execution.assignments.append_report(current.ref,body,expected_generation=due.generation,
        logical_request_key=request_key,actor=execution.binding.authenticated_actor(execution.actor))
    _require(_digest(execution._read(schedule_id).to_dict())==scope['due_sha256'],'occurrence changed before exact custody retirement')
    marker={'schema':schema,'disposition_ref':report.ref.to_dict(),'fresh_request_key':fresh_request_key,'provider_retry_allowed':False}
    stopped=replace(due,stop_state='stopped',in_flight_request=None,
        host_evidence={**due.host_evidence,'role_preinitialization_custody_release':marker})
    execution.due_port.save_due(schedule_id,stopped.to_dict(),request_id=request_key+':stop',expected_version=due.version)
    return {'outcome':'released',**marker,'scope':scope,'provider_called':False}

def permits_preinitialization_role(execution,*,schedule_id,assignment,project_ref,task_ref,request_key):
    old=execution._read(schedule_id);body=retained_preinitialization_release(execution,old);scope=body['scope']
    role = 'worker' if body['schema'] == DRAIN_PREINITIALIZATION_SCHEMA else 'manager'
    _require(body['fresh_request_key']==request_key and old.role==role and assignment.role in ({'worker','executor'} if role=='worker' else {'manager'})
        and all(assignment.ref.to_dict()[k]==scope['assignment_ref'][k]for k in('authority','kind','id'))
        and assignment.generation==scope['generation'] and assignment.principal==scope['principal']
        and project_ref==scope['project_ref']and task_ref==scope['task_ref']and assignment.session is None,
        'recovery delivery is outside exact original role/project/task/generation')
    return {'original_schedule_id':schedule_id,'disposition_ref':old.host_evidence['role_preinitialization_custody_release']['disposition_ref'],'fresh_request_key':request_key,'original_result_sha256':scope['result_sha256']}


def retained_stopped_writer_conflict_release(execution, due):
    """Release this failed CLI's capacity, never the external writer's custody.

    A stop alone does not qualify. Exact terminal pre-session persistence
    failure plus authenticated original delivery proves this process started
    no turn. Current normal admission must still test the native writer lock.
    """
    _require(due.stop_state == 'stopped'
        and due.completion_state in {'none', 'unknown'} and due.role == 'manager'
        and execution.actor == due.lifecycle_owner == due.owner == due.manager_ref,
        'exact lifecycle-owner stopped manager required')
    current = execution.assignments.get(ResourceRef.from_dict(due.assignment_ref))
    _require(current.role == 'manager' and current.principal == due.recipient
        and current.generation == due.generation, 'current manager identity differs')
    execution._current(current.ref.to_dict(), due.generation)
    if current.ref.to_dict() != due.assignment_ref:
        from .operating_setup import authenticated_adoption_ancestor
        _require(authenticated_adoption_ancestor({'ref': current.ref.to_dict(),
            'principal': current.principal, 'role': current.role,
            'generation': current.generation, 'payload': current.payload},
            due.assignment_ref, execution.portfolio.operations._owner_reader),
            'historical failure requires consecutive authenticated resource adoptions')
    attempt = (due.host_evidence or {}).get('gateway_attempt') or {}
    result = attempt.get('result') or {}
    raw = result.get('raw_result') or {}
    auth = raw.get('owner_delivery_authorization') or {}
    work = raw.get('work_envelope') or {}; receipt = raw.get('work_receipt') or {}
    host = work.get('host_evidence') or {}; candidate = host.get('native_candidate') or {}
    session = result.get('physical_session_id')
    from otto.attention import native_target_identity
    _require(isinstance(session, str) and session and session == native_target_identity(due.target)
        and attempt.get('state') == 'result' and attempt.get('physical_session_id') == session
        and result.get('outcome') == 'unknown' and result.get('delivery_state') == 'unknown'
        and result.get('context_digest_verified') is False and result.get('observed_turn_id') is None
        and result.get('native_session_id') == session
        and (result.get('error') or {}).get('code') == 'authorized_result_unverified',
        'original exact failed native binding required')
    expected = {'assignment_ref': due.assignment_ref, 'generation': due.generation,
        'physical_session_id': session, 'project_ref': due.target['project_ref'],
        'task_ref': due.target['task_ref'], 'role': 'manager', 'principal': due.recipient,
        'lifecycle_owner': execution.actor, 'status': 'authorized'}
    _require(attempt.get('delivery_authorization') == auth
        and all(type(auth.get(k)) is type(v) and auth.get(k) == v for k, v in expected.items())
        and isinstance(auth.get('logical_request_key'), str) and auth['logical_request_key']
        and all(body.get('logical_request_key') == auth['logical_request_key']
            and body.get('assignment_ref') == due.assignment_ref
            and body.get('generation') == due.generation for body in (attempt, result))
        and result.get('project_ref') == due.target['project_ref']
        and result.get('task_ref') == due.target['task_ref']
        and result.get('logical_agent_id') == result.get('owner') == due.recipient,
        'original authenticated delivery scope differs')
    _require(due.in_flight_request is None or due.in_flight_request == auth['logical_request_key'],
        'retained in-flight token differs from exact terminal failed process')
    _require(raw.get('initialization_envelope') is None and raw.get('initialization_receipt') is None
        and raw.get('transport_operation') == 'resume' and raw.get('worker_content') == []
        and raw.get('task_bound_evidence') is None and work.get('stdout') == ''
        and work.get('fnd_receipt') == receipt and work.get('runner') == 'codex-cli'
        and work.get('status') == receipt.get('outcome') == 'failed'
        and work.get('exit_status') == 1 and work.get('transport_operation') == receipt.get('operation') == 'resume'
        and work.get('physical_session_id') == session
        and work.get('logical_agent_id') == work.get('owner') == due.recipient
        and isinstance(work.get('process_id'), str) and work['process_id'].isdigit()
        and receipt.get('process_id') == work['process_id']
        and receipt.get('identity') == {'logical_agent_id': due.recipient, 'physical_session_id': session}
        and work.get('timeout') is None and work.get('cancel') is None
        and work.get('result_ref') is None and receipt.get('result_ref') is None,
        'terminal failed CLI envelope differs')
    start, end = (datetime.fromisoformat(work[k].replace('Z', '+00:00'))
                  for k in ('started_at', 'ended_at'))
    _require(start.tzinfo is not None and end.tzinfo is not None and end >= start,
        'terminal CLI timestamps differ')
    stamp = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z'
    conflict = re.escape('thread-store conflict: thread ' + session + ' already has an active writer')
    diagnostic = (stamp + r' ERROR codex_core::session::session: failed to initialize thread persistence: ' + conflict
        + r'\n' + stamp + r' ERROR codex_core::session: Failed to create session: ' + conflict
        + r'\nError: thread/resume: thread/resume failed: thread ' + re.escape(session)
        + r' already has an active writer \(code -32600\)\n')
    _require(isinstance(work.get('stderr'), str) and len(work['stderr'].encode()) <= 4096
        and re.fullmatch(diagnostic, work['stderr']) is not None
        and host.get('session_id') == session and host.get('process_started') is True
        and host.get('session_created') is False and host.get('native_turn_started') is False
        and host.get('invocation_turn_verified') is False and host.get('turn_id') is None
        and host.get('provenance') == 'host_native_jsonl'
        and host.get('otto_host_turn_context') is None
        and candidate.get('capture_utf8_bytes') == 0 and candidate.get('capture_sha256') == hashlib.sha256(b'').hexdigest()
        and candidate.get('native_records') == [] and candidate.get('turn_id') is None
        and candidate.get('task_bound') is False and candidate.get('retry_allowed') is False
        and candidate.get('status') == 'unsupported',
        'exact persistence rejection before native turn required')
    return {'outcome': 'this-failed-process-capacity-released', 'schedule_id': due.schedule_id,
        'unknown_result_sha256': _digest(result), 'work_envelope_sha256': _digest(work),
        'original_UNKNOWN_preserved': True, 'external_writer_release_verified': False,
        'provider_retry_allowed': False}


def inspect_drain_preinitialization_worker(execution, *, schedule_id):
    """Exact retain-before-thread draining failure, not a generic absent session."""
    return inspect_preinitialization_role(execution,schedule_id=schedule_id,_drain_worker=True)

def release_drain_preinitialization_worker(execution, **request):
    return release_preinitialization_role(execution,**request,_drain_worker=True)
