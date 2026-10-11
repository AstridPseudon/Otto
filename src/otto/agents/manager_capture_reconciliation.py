"""Trusted terminal reparse for one lost manager resume-admission capture."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from herzchen.contracts import HostIdentity, HostOperation, HostRequest, ResourceRef
from herzchen.adapters.host import _native_host_context
from otto.portfolio.owner_readers import OwnerRoleRuntimeError, json_value


def digest(value):
    return hashlib.sha256(json.dumps(json_value(value), ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require(value, reason):
    if not value:
        raise OwnerRoleRuntimeError(reason)


def reconcile_missing_manager_capture(runtime, *, schedule_id,
                                      expected_claim_sha256, validate_only=False):
    """Read the exact admitted native turn; never retry a claimed delivery.

    The original transport exit is unavailable after owner loss. Successful
    native terminal evidence is separate from that transport uncertainty and
    from substantive task acceptance. The complete original claim is retained.
    """
    due = runtime.due_port.read_due(schedule_id) or {}
    attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
    proof = attempt.get("missing_capture_reconciliation") or {}
    retained_proof = proof.get("schema") == "otto.missing-manager-capture-reconciliation.v1"
    if retained_proof:
        require(proof.get("source_claim_sha256") == expected_claim_sha256
                and proof.get("resolver") == runtime.actor
                and digest(proof.get("source_claim")) == expected_claim_sha256,
                "retained missing-capture reconciliation differs")
        if attempt.get("state") == "result":
            require(digest(attempt.get("result")) == proof.get("result_sha256"),
                    "retained reconciled result changed")
            return {"outcome": "reconciled", "replayed": True, "provider_called": False,
                    "reconciliation": proof}
        require({k: v for k, v in attempt.items() if k != "missing_capture_reconciliation"}
                == proof["source_claim"], "pending reconciliation changed original claim")
        attempt = proof["source_claim"]
    require(due.get("role") == "manager" and attempt.get("state") == "claimed"
            and attempt.get("result") is None and digest(attempt) == expected_claim_sha256
            and attempt.get("logical_request_key") == due.get("in_flight_request"),
            "not the exact unresolved manager claim")
    authorization = attempt.get("delivery_authorization") or {}
    admission = attempt.get("delivery_admission") or {}
    session = attempt.get("physical_session_id")
    turn = admission.get("observed_turn_id")
    require(isinstance(session, str) and session and isinstance(turn, str) and turn
            and admission.get("schema") == "otto.owner-host-delivery-admission.v1"
            and admission.get("state") == "turn_started"
            and admission.get("native_turn_started") is True
            and admission.get("physical_session_id") == session
            and authorization.get("physical_session_id") == session,
            "exact owner-recorded native admission is required")
    _, _, capture = runtime._binding(role="manager", project_ref=authorization["project_ref"],
        task_ref=authorization["task_ref"], assignment_ref=authorization["assignment_ref"],
        mandate_ref=due["target"]["mandate_ref"], schedule_id=schedule_id,
        logical_request_key=attempt["logical_request_key"], expected_generation=due["generation"])
    record = capture._record()
    require(callable(capture.completed_scope_validator) and not capture.completed_scope_validator()
            and not capture._scope_error(record, capture.assignment_ref, capture.generation,
                                         attempt["logical_request_key"]),
            "current exact manager custody is required")
    expected = {"status": "authorized", "physical_session_id": session,
        "logical_request_key": attempt["logical_request_key"], "project_ref": capture.project_ref,
        "task_ref": capture.task_ref, "assignment_ref": capture.assignment_ref,
        "generation": capture.generation, "role": "manager", "principal": capture.principal,
        "lifecycle_owner": runtime.actor}
    require(all(authorization.get(k) == v for k, v in expected.items())
            and attempt.get("assignment_ref") == capture.assignment_ref
            and attempt.get("generation") == capture.generation,
            "retained claim and authorization differ")
    reader = getattr(runtime.adapter, "trusted_thread_reader", None)
    require(callable(reader), "trusted exact-session native reader is required")
    thread = (reader(session) or {}).get("thread") or {}
    require(thread.get("id") == session and isinstance(thread.get("path"), str),
            "trusted native session metadata differs")
    fd = os.open(thread["path"], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode), "native trace is not a regular file")
        header = stream.readline(1024 * 1024 + 1)
        require(header.endswith(b"\n") and len(header) <= 1024 * 1024,
                "native session header exceeds bounded input")
        start = max(len(header), metadata.st_size - 32 * 1024 * 1024)
        stream.seek(start); tail = stream.read(32 * 1024 * 1024 + 1)
    require(len(tail) <= 32 * 1024 * 1024 and tail.endswith(b"\n"),
            "native terminal tail is unavailable or incomplete")
    if start > len(header): tail = tail.split(b"\n", 1)[-1]
    lines = [header.decode()] + [v.decode() for v in tail.splitlines() if v]
    events = [json.loads(line) for line in lines]
    require(events[0].get("type") == "session_meta"
            and (events[0].get("payload", {}).get("id")
                 or events[0].get("payload", {}).get("session_id")) == session,
            "native file header identifies a different session")
    active, starts, ends, user_texts = set(), [], [], []
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") != "event_msg": continue
        kind, ident = payload.get("type"), payload.get("turn_id")
        if kind == "task_started":
            active.add(ident)
            if ident == turn: starts.append(payload)
        elif kind in {"task_complete", "task_aborted"}:
            active.discard(ident)
            if ident == turn: ends.append(payload)
        elif (ident == turn and kind == "item_completed"
              and payload.get("item", {}).get("type") == "UserMessage"):
            user_texts.append("\n".join(v.get("text", "")
                for v in payload["item"].get("content", []) if v.get("type") in {"text", "Text"}))
    require(not active and len(starts) == len(ends) == len(user_texts) == 1
            and ends[0].get("type") == "task_complete" and ends[0].get("error") is None
            and starts[0].get("started_at", -1) <= ends[0].get("completed_at", -1),
            "exact admitted native turn is missing, repeated, aborted or still active")
    observed = datetime.fromisoformat(admission["observed_at"].replace("Z", "+00:00"))
    require(observed.tzinfo is not None
            and abs(starts[0]["started_at"] - observed.timestamp()) <= 1,
            "native start differs from retained owner admission")
    text = user_texts[0]
    blocks = re.findall(r'<otto-resource-brief sha256="([a-f0-9]{64})">\s*(.*?)\s*</otto-resource-brief>', text, re.S)
    requests = re.findall(r'<otto-invocation-request[^>]*sha256="([a-f0-9]{64})">\s*(.*?)\s*</otto-invocation-request>', text, re.S)
    require(len(blocks) == len(requests) == 1, "exact delivered brief and invocation are required")
    brief, invocation = json.loads(blocks[0][1]), json.loads(requests[0][1])
    launch = invocation.get("launch_context") or {}
    # render_verified_invocation validates/renders request.prompt through _text,
    # whose canonical model-visible form strips outer whitespace only.
    prompt = (due["instruction"] + ("\n" + due["message"] if due.get("message") is not None else "")).strip()
    require(digest(brief) == blocks[0][0] == authorization.get("brief_sha256")
            and brief.get("instruction_contract") == capture.manager_command_contract
            and digest(invocation) == requests[0][0]
            and invocation.get("schema") == "otto.owner-invocation-request.v1"
            and invocation.get("logical_request_key") == attempt["logical_request_key"]
            and invocation.get("prompt") == prompt
            and launch.get("assignment_ref") == capture.assignment_ref
            and launch.get("generation") == capture.generation
            and launch.get("principal") == capture.principal and launch.get("role") == "manager"
            and launch.get("occurrence_ref") == {"schedule_id": schedule_id,
                                                "logical_request_key": attempt["logical_request_key"]}
            and (launch.get("native_session") or {}).get("adapter") == due["target"].get("native_adapter")
            and (launch.get("native_session") or {}).get("fresh_binding") is (due.get("execution_mode") == "fresh_manager")
            and (launch.get("native_session") or {}).get("id") == (None if due.get("execution_mode") == "fresh_manager" else session),
            "delivered immutable brief, request or current mandate differs")
    selected = [line for line, event in zip(lines, events)
                if event.get("type") == "session_meta" or (event.get("payload") or {}).get("turn_id") == turn]
    logical = capture.principal if isinstance(capture.principal, str) else capture.principal["id"]
    host_request = HostRequest(HostOperation.RESUME, HostIdentity(logical, session),
                              ResourceRef.from_dict(capture.task_ref), due["profile"])
    context = _native_host_context(selected, request=host_request, session_id=session,
        turn_id=turn, delivered_brief=brief, delivered_authorization=authorization)
    parsed = runtime.native_result_verifier.observe_context(context, expected_session_id=session,
        expected_turn_id=turn, expected_profile=due["profile"],
        expected_read_targets=brief["instruction_contract"].get("read_targets"),
        expected_read_scope=brief["instruction_contract"].get("read_scope"))
    require(parsed["model"] == due["requested_model"] and parsed["reasoning"] == due["requested_reasoning"],
            "actual native model or reasoning differs")
    from .gateway import AttemptEnvelope
    from otto.portfolio.resource_sync import brief_resource_evidence
    resource = brief_resource_evidence({**brief, "brief_sha256": digest(brief)},
                                      delivery_state="completed", native_identity=session)
    result = AttemptEnvelope(attempt["logical_request_key"], logical, capture.project_ref,
        capture.task_ref, capture.assignment_ref, capture.generation,
        "invoke" if launch["native_session"].get("fresh_binding") else "resume",
        due["profile"], due["requested_model"], due["requested_reasoning"], logical, session,
        parsed["model"], parsed["reasoning"], "done", "succeeded",
        request_fingerprint=attempt["request_fingerprint"], resource_evidence=resource).to_dict()
    result.update(observed_turn_id=turn, observed_profile=parsed["observed_profile"],
        observed_context_digest=parsed["context_digest"], context_digest_verified=True,
        task_bound_evidence=parsed["task_bound_evidence"], worker_content=parsed["worker_content"],
        raw_result={"transport_outcome": "unavailable_after_owner_interruption",
            "original_transport_exit_status": None, "owner_delivery_authorization": authorization,
            "work_envelope": {"exit_status": None, "host_evidence": {"otto_host_turn_context": context}}})
    capture.validate_completed_manager_result(result)
    proof = {"schema": "otto.missing-manager-capture-reconciliation.v1", "resolver": runtime.actor,
        "effect": "trusted_admitted_terminal_capture_no_provider_replay",
        "source_claim": deepcopy(attempt), "source_claim_sha256": expected_claim_sha256,
        "result_sha256": digest(result), "physical_session_id": session, "observed_turn_id": turn,
        "native_file_identity": [metadata.st_dev, metadata.st_ino],
        "trace_sha256": hashlib.sha256("\n".join(selected).encode()).hexdigest(),
        "original_transport_exit_status": None, "native_terminal_observed": True}
    if validate_only:
        return {"outcome": "qualified", "provider_called": False, "store_mutated": False,
                "reconciliation": proof}
    current = capture._attempt(capture._record())
    if retained_proof:
        require(current.get("missing_capture_reconciliation") == proof,
                "pending native capture proof changed during read")
        require(digest({k: v for k, v in current.items() if k != "missing_capture_reconciliation"})
                == expected_claim_sha256, "original claim changed during trusted native read")
    else:
        require(digest(current) == expected_claim_sha256,
                "original claim changed during trusted native read")
    # Keep the claim and provenance in the same existing CAS-backed attempt.
    if not retained_proof:
        capture._save(capture._record(), {**attempt, "missing_capture_reconciliation": proof},
                      "otto-missing-capture-proof:" + attempt["logical_request_key"] + ":" + expected_claim_sha256)
    capture.record(result)
    return {"outcome": "reconciled", "provider_called": False, "reconciliation": proof}


def completed_resume_admission(attempt, lifecycle_owner):
    """Project a verified terminal reparse, never the missing live callback."""
    proof = attempt.get("delivery_admission_reconciliation") or {}
    result = attempt.get("result") or {}
    source = proof.get("source_unknown") or {}
    if (proof.get("schema") != "otto.completed-resume-capture-reconciliation.v1"
            or proof.get("resolver") != lifecycle_owner
            or proof.get("effect") != "trusted_completed_resume_no_provider_replay"
            or proof.get("source_unknown_sha256") != digest(source)
            or source.get("operation") != "resume" or source.get("outcome") != "unknown"
            or proof.get("replacement_sha256") != digest(result)
            or result.get("outcome") != "succeeded" or result.get("context_digest_verified") is not True
            or result.get("delivery_state") != "done"
            or proof.get("native_turn_started") is not True
            or proof.get("physical_session_id") != result.get("physical_session_id")
            or proof.get("observed_turn_id") != result.get("observed_turn_id")):
        return {}
    return {"physical_session_id": result["physical_session_id"],
            "observed_turn_id": result["observed_turn_id"], "native_turn_started": True,
            "origin": "trusted_completed_resume_reparse", "original_live_admission": False}


def reconcile_completed_resume_capture(runtime, *, schedule_id,
                                      expected_unknown_sha256, validate_only=False):
    due = runtime.due_port.read_due(schedule_id) or {}
    attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
    prior = attempt.get("result") or {}
    proof = attempt.get("delivery_admission_reconciliation") or {}
    require(due.get("role") == "manager" and prior.get("operation") == "resume",
            "only an exact manager resume may reconcile capture")
    _, _, capture = runtime._binding(role="manager", project_ref=prior["project_ref"],
        task_ref=prior["task_ref"], assignment_ref=prior["assignment_ref"],
        mandate_ref=due["target"]["mandate_ref"], schedule_id=schedule_id,
        logical_request_key=prior["logical_request_key"], expected_generation=prior["generation"],
        allow_settled_publication=(proof.get("schema") == "otto.completed-resume-capture-reconciliation.v1"
            and proof.get("source_unknown_sha256") == expected_unknown_sha256
            and prior.get("outcome") == "succeeded"))
    require(callable(capture.completed_scope_validator) and not capture.completed_scope_validator(),
            "current exact manager assignment and mandate are required")
    if (proof.get("schema") == "otto.completed-resume-capture-reconciliation.v1"
            and proof.get("source_unknown_sha256") == expected_unknown_sha256
            and prior.get("outcome") == "succeeded"):
        if not capture.settled_publication:
            capture.validate_completed_manager_result(prior)
        require(digest(prior) == proof.get("replacement_sha256"), "reconciled result changed")
        return {"outcome": "reconciled", "replayed": True, "provider_called": False,
                "admission_reconciliation": proof}
    record = capture._record()
    require(attempt.get("state") == "result" and prior.get("outcome") == "unknown"
        and prior.get("delivery_state") == "unknown" and not prior.get("context_digest_verified")
        and prior.get("observed_turn_id") is None and attempt.get("delivery_admission") is None
        and digest(prior) == expected_unknown_sha256
        and prior.get("logical_request_key") == due.get("in_flight_request")
        and not capture._scope_error(record, capture.assignment_ref, capture.generation,
                                   prior["logical_request_key"]),
        "not the exact retained missing resume-admission capture")
    raw = prior.get("raw_result") or {}
    work = raw.get("work_envelope") or {}
    receipt = raw.get("work_receipt") or {}
    authorization = attempt.get("delivery_authorization") or {}
    session = prior.get("physical_session_id")
    require(isinstance(session, str) and session and prior.get("native_session_id") == session
        and due["target"].get("native_id") == session
        and raw.get("initialization_receipt") is None and raw.get("initialization_envelope") is None
        and raw.get("transport_operation") == "resume"
        and work.get("stderr") == "native turn-start capture failed"
        and work.get("delivery_state") == "unknown" and work.get("exit_status") is None
        and receipt.get("operation") == "resume" and receipt.get("outcome") == "failed"
        and receipt.get("unsupported_reason") == "codex_launcher_os_error"
        and receipt.get("identity") == {"logical_agent_id": prior["logical_agent_id"],
                                        "physical_session_id": session}
        and raw.get("owner_delivery_authorization") == authorization,
        "resume transport diagnostic or original native custody differs")
    brief = prior["resource_evidence"]["brief"]
    expected = {"status": "authorized", "physical_session_id": session,
        "logical_request_key": prior["logical_request_key"], "project_ref": capture.project_ref,
        "task_ref": capture.task_ref, "assignment_ref": capture.assignment_ref,
        "generation": capture.generation, "role": "manager", "principal": capture.principal,
        "lifecycle_owner": runtime.actor, "brief_sha256": digest(brief)}
    require(all(authorization.get(k) == v for k, v in expected.items())
        and brief["instruction_contract"] == capture.manager_command_contract
        and prior["resource_evidence"]["brief_sha256"] == digest(brief)
        and prior["requested_profile"] == due["profile"]
        and prior["requested_model"] == due["requested_model"]
        and prior["requested_reasoning"] == due["requested_reasoning"],
        "retained authorization, brief or exact current contract differs")
    reader = getattr(runtime.adapter, "trusted_thread_reader", None)
    require(callable(reader), "trusted exact-session native metadata reader is required")
    thread = (reader(session) or {}).get("thread") or {}
    require(thread.get("id") == session and isinstance(thread.get("path"), str),
            "trusted native session metadata differs")
    fd = os.open(thread["path"], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode), "native trace is not a regular file")
        header = stream.readline(1024 * 1024 + 1)
        require(header.endswith(b"\n") and len(header) <= 1024 * 1024,
                "native session header exceeds bounded input")
        start = max(len(header), metadata.st_size - 32 * 1024 * 1024)
        stream.seek(start)
        tail = stream.read(32 * 1024 * 1024 + 1)
    require(len(tail) <= 32 * 1024 * 1024 and tail.endswith(b"\n"),
            "native terminal tail is unavailable or incomplete")
    if start > len(header):
        tail = tail.split(b"\n", 1)[-1]
    lines = [header.decode()] + [v.decode() for v in tail.splitlines() if v]
    events = [json.loads(line) for line in lines]
    require(events[0].get("type") == "session_meta"
        and (events[0].get("payload", {}).get("id")
             or events[0].get("payload", {}).get("session_id")) == session,
        "native file header identifies a different session")
    began = datetime.fromisoformat(work["started_at"].replace("Z", "+00:00"))
    ended = datetime.fromisoformat(work["ended_at"].replace("Z", "+00:00"))
    require(began.tzinfo is not None and ended >= began, "retained transport times differ")
    active, starts, ends, candidates = set(), {}, {}, []
    wanted_prompt = due["instruction"] + ("\n" + due["message"] if due.get("message") is not None else "")
    for event in events:
        p = event.get("payload") or {}; turn = p.get("turn_id")
        if event.get("type") != "event_msg":
            continue
        if p.get("type") == "task_started":
            active.add(turn); starts.setdefault(turn, []).append(p)
        elif p.get("type") in {"task_complete", "task_aborted"}:
            active.discard(turn); ends.setdefault(turn, []).append(p)
        elif p.get("type") == "item_completed" and p.get("item", {}).get("type") == "UserMessage":
            text = "\n".join(v.get("text", "") for v in p["item"].get("content", [])
                             if v.get("type") in {"text", "Text"})
            matches = re.findall(r'<otto-invocation-request[^>]*sha256="([a-f0-9]{64})">\s*(.*?)\s*</otto-invocation-request>', text, re.S)
            for hashed, body in matches:
                request = json.loads(body); context = request.get("launch_context") or {}
                if (request.get("logical_request_key") == prior["logical_request_key"]
                        and request.get("prompt") == wanted_prompt and digest(request) == hashed
                        and context.get("assignment_ref") == capture.assignment_ref
                        and context.get("generation") == capture.generation
                        and context.get("principal") == capture.principal and context.get("role") == "manager"
                        and context.get("occurrence_ref") == {"schedule_id": schedule_id,
                            "logical_request_key": prior["logical_request_key"]}
                        and (context.get("native_session") or {}).get("id") == session):
                    candidates.append(turn)
    require(not active and len(candidates) == 1, "exact native resume is missing, repeated or still active")
    turn = candidates[0]
    require(len(starts.get(turn, [])) == len(ends.get(turn, [])) == 1
        and ends[turn][0].get("type") == "task_complete" and ends[turn][0].get("error") is None
        and began.timestamp() - 1 <= starts[turn][0].get("started_at", -1)
        <= ends[turn][0].get("completed_at", -1) <= ended.timestamp() + 1,
        "native turn is not exact successful terminal work within retained transport")
    selected = [line for line, event in zip(lines, events)
                if event.get("type") == "session_meta" or (event.get("payload") or {}).get("turn_id") == turn]
    host_request = HostRequest(HostOperation.RESUME, HostIdentity(prior["logical_agent_id"], session),
        ResourceRef.from_dict(prior["task_ref"]), prior["requested_profile"])
    context = _native_host_context(selected, request=host_request, session_id=session,
        turn_id=turn, delivered_brief=brief, delivered_authorization=authorization)
    parsed = runtime.native_result_verifier.observe_context(context, expected_session_id=session,
        expected_turn_id=turn, expected_profile=prior["requested_profile"],
        expected_read_targets=brief["instruction_contract"].get("read_targets"),
        expected_read_scope=brief["instruction_contract"].get("read_scope"))
    require(parsed["model"] == prior["requested_model"] and parsed["reasoning"] == prior["requested_reasoning"],
            "actual native model or reasoning differs")
    replacement = deepcopy(prior)
    replacement.update(outcome="succeeded", delivery_state="done", unknown_reason=None, error=None,
        observed_turn_id=turn, observed_model=parsed["model"], observed_reasoning=parsed["reasoning"],
        observed_profile=parsed["observed_profile"], observed_context_digest=parsed["context_digest"],
        context_digest_verified=True, task_bound_evidence=parsed["task_bound_evidence"],
        worker_content=parsed["worker_content"])
    # Keep every original failed receipt/transport byte; add only trusted reparse.
    replacement["raw_result"]["work_envelope"]["host_evidence"] = {"otto_host_turn_context": context}
    proof = {"schema": "otto.completed-resume-capture-reconciliation.v1", "resolver": runtime.actor,
        "effect": "trusted_completed_resume_no_provider_replay", "source_unknown": deepcopy(prior),
        "source_unknown_sha256": digest(prior), "replacement_sha256": digest(replacement),
        "physical_session_id": session, "observed_turn_id": turn, "native_turn_started": True,
        "native_file_identity": [metadata.st_dev, metadata.st_ino],
        "trace_sha256": hashlib.sha256("\n".join(selected).encode()).hexdigest(),
        "original_transport_outcome": "failed", "original_admission_claimed": False}
    require(not capture.completed_scope_validator(), "current manager custody changed during native read")
    if validate_only:
        return {"outcome": "qualified", "provider_called": False, "store_mutated": False,
                "admission_reconciliation": proof}
    capture._save(record, {**attempt, "delivery_admission_reconciliation": proof},
        "otto-resume-capture-reconcile:" + prior["logical_request_key"] + ":" + expected_unknown_sha256)
    capture.validate_completed_manager_result(replacement)
    reconciled = capture.reconcile_unknown_result(prior["logical_request_key"], replacement,
        resolver=runtime.actor, trace_sha256=proof["trace_sha256"],
        parser_revision="otto.completed-resume-capture.v1")
    return {"outcome": "reconciled", "provider_called": False,
            "admission_reconciliation": proof, "result_reconciliation": reconciled["reconciliation"]}
