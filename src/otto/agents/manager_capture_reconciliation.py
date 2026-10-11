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
