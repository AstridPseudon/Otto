"""Small pure projections of existing Due/results; never recover or launch."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def worker_schedule(project: Mapping[str, Any], key: str) -> str:
    # Preserve the legacy project-wide key, including the original revision.
    return "worker-" + digest([project, key])[:28]


def handle(due: Mapping[str, Any]) -> dict[str, Any]:
    target = due["target"]
    return {"schedule_id": due["schedule_id"], "assignment_ref": due["assignment_ref"],
            "generation": due["generation"], "project_ref": target["project_ref"],
            "task_ref": target["task_ref"], "parent": target.get("parent")}


def exact_due(port: Any, occurrence: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(occurrence, Mapping) or set(occurrence) != {
            "schedule_id", "assignment_ref", "generation", "project_ref", "task_ref", "parent"}:
        raise ValueError("exact occurrence handle required")
    due = port.read_due(occurrence["schedule_id"])
    if due is None or handle(due) != dict(occurrence):
        raise PermissionError("occurrence handle is missing, foreign or changed")
    return due


def lookup(port: Any, *, scope: Mapping[str, Any], request_key: str,
           request_input: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if (not isinstance(scope, Mapping) or set(scope) != {"project_ref", "task_ref", "parent"}
            or not isinstance(request_key, str) or not request_key.strip()):
        raise ValueError("exact pinned scope and stable request key required")
    schedule = worker_schedule(scope["project_ref"], request_key)
    due = port.read_due(schedule)
    if due is None:
        return {"outcome": "missing", "pure": True, "retry": False,
                "next_action": "report the missing exact intent; do not invent a new key"}
    retained = due["target"].get("launch_request")
    if retained is None:
        return {"outcome": "unavailable", "pure": True, "schedule_id": schedule, "retry": False,
                "reason": "legacy occurrence has no exact launch projection; legacy reads remain available"}
    if retained["scope"] != dict(scope) or (request_input is not None and retained["input"] != dict(request_input)):
        return {"outcome": "conflict", "pure": True, "retry": False,
                "next_action": "inspect the original intent; changed input or parent cannot reuse this key"}
    return {"outcome": "found", "pure": True, "occurrence": handle(due),
            "selection": retained["selection"], "handles": (due.get("host_evidence") or {}).get("launch_handles", {}),
            "request_fingerprint": retained["fingerprint"], "retry": False}


def result_view(due: Mapping[str, Any]) -> dict[str, Any]:
    host = due.get("host_evidence") or {}
    attempt = host.get("gateway_attempt") or {}
    result = attempt.get("result") or {}
    evidence = result.get("task_bound_evidence") or {}
    answer = ((evidence.get("operation_result") or {}).get("output") or {}).get("final_answer") or {}
    summary = host.get("captured_result_summary") or {}
    verified = (attempt.get("state") == "result" and result.get("context_digest_verified") is True
                and result.get("assignment_ref") == due["assignment_ref"]
                and result.get("generation") == due["generation"]
                and result.get("task_ref") == due["target"]["task_ref"]
                and result.get("outcome") == "succeeded")
    # Newly admitted operations require the pinned canonical publication,
    # not merely native terminality or a parser's verified-context flag.
    if due["target"].get("launch_request") is not None:
        verified = (verified and summary.get("assignment_ref") == due["assignment_ref"]
                    and summary.get("generation") == due["generation"]
                    and summary.get("logical_request_key") == result.get("logical_request_key")
                    and summary.get("result_digest") == evidence.get("result_digest")
                    and (summary.get("result_ref") or {}).get("kind") == "wrk.result"
                    and bool((summary.get("result_ref") or {}).get("revision")))
    admission = attempt.get("delivery_admission") or {}
    return {"schema": "otto.occurrence-result.v1", "pure": True, "occurrence": handle(due),
        "selection": (due["target"].get("launch_request") or {}).get("selection", due["target"].get("execution_selection")),
        "freshness": {"basis": "current retained owner snapshot", "due_version": due["version"],
                      "last_verified_at": due.get("completed_at"), "history": "snapshot-only"},
        "outcome": result.get("outcome", "prepared" if not attempt else "unknown"),
        "useful_admission": admission.get("native_turn_started", False),
        "native_identity": {"adapter": due["target"].get("native_adapter"),
                            "session": result.get("physical_session_id", (attempt.get("delivery_authorization") or {}).get("physical_session_id"))},
        "native_terminal": result.get("delivery_state") in {"done", "completed", "failed"},
        "required_capture": verified,
        "occurrence_settlement": {"stop_state": due["stop_state"], "completion_state": due["completion_state"]},
        "parent_delivery": host.get("parent_consumption", {"state": "unconsumed", "next_actor": due["target"].get("parent")}),
        "task_acceptance": "unjudged; manager assessment required",
        "conclusion": summary.get("conclusion", answer.get("text", "")[:4096]) if verified else None,
        "conclusion_sha256": summary.get("conclusion_sha256", answer.get("text_sha256")) if verified else None,
        "verification": {"context_digest_verified": verified, "observed_turn_id": result.get("observed_turn_id")},
        "result_ref": summary.get("result_ref"),
        "artifacts": [{k: v for k, v in item.items() if k != "content_base64"}
                      for item in host.get("captured_artifacts", [])[:16]],
        "usage": summary.get("usage", {"state": "unavailable", "reason": "no qualified capture-time usage summary retained"}),
        "blockers": [] if verified else ["required conclusion/capture not yet verified"],
        "stop": {"requested": due["stop_state"] == "stopped", "owned_process_termination": "unverified"},
        "retry": False, "provider_called": False, "reconciled": False}


def read_captured_artifact(due: Mapping[str, Any], *, artifact_ref: Mapping[str, Any],
                           offset: int = 0, max_bytes: int = 4096) -> Mapping[str, Any]:
    """Read only owner-captured known bytes, never a response-supplied path."""
    if type(offset) is not int or offset < 0 or type(max_bytes) is not int or not 1 <= max_bytes <= 4096:
        raise ValueError("artifact range requires nonnegative offset and 1..4096 bytes")
    if not result_view(due)["required_capture"]:
        return {"outcome": "unavailable", "pure": True, "reason": "required result capture is unavailable"}
    if (not isinstance(artifact_ref, Mapping) or set(artifact_ref) != {"result_ref", "index", "sha256"}
            or type(artifact_ref["index"]) is not int or not 0 <= artifact_ref["index"] < 16):
        raise PermissionError("exact known captured artifact ref required")
    known = (due.get("host_evidence") or {}).get("captured_artifacts", [])
    matches = [item for item in known if item.get("ref") == dict(artifact_ref)]
    if len(matches) != 1:
        raise PermissionError("artifact is absent or belongs to another retained result")
    from otto.agents.claude_adapter import captured_artifact_bytes
    import base64
    body = captured_artifact_bytes(matches[0])
    part = body[offset:offset + max_bytes]
    return {"outcome": "available", "pure": True, "artifact_ref": dict(artifact_ref),
            "offset": offset, "bytes": len(part), "total_bytes": len(body),
            "content_base64": base64.b64encode(part).decode("ascii"), "eof": offset + len(part) >= len(body),
            "provider_called": False, "reconciled": False}
