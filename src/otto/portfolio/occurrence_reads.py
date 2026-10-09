"""Small pure projections of existing Due/results; never recover or launch."""
from __future__ import annotations

import hashlib
import math
import json
from typing import Any, Mapping


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _bounded_text(value: Any, limit: int = 4096) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _bounded_ref(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = {key: value[key] for key in ("authority", "kind", "id", "revision") if key in value}
    if any(not isinstance(allowed.get(key), str) or not 0 < len(allowed[key]) <= 256
           for key in ("authority", "kind", "id")):
        return None
    if allowed.get("revision") is not None and (not isinstance(allowed["revision"], str)
            or not 0 < len(allowed["revision"]) <= 256):
        return None
    return allowed


def _delivery_identity(result_ref: Any, disposition_revision: Any) -> str | None:
    ref = _bounded_ref(result_ref)
    if ref is None or not isinstance(disposition_revision, (str, int)) or isinstance(disposition_revision, bool):
        return None
    return "delivery-" + digest({"result_ref": ref, "disposition_revision": disposition_revision})


def _artifact_projection(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    ref = item.get("ref")
    if not isinstance(ref, Mapping):
        return None
    result_ref = _bounded_ref(ref.get("result_ref"))
    if result_ref is None or type(ref.get("index")) is not int:
        return None
    return {
        "name": _bounded_text(item.get("name"), 512),
        "tool_use_id": _bounded_text(item.get("tool_use_id"), 256),
        "sha256": _bounded_text(item.get("sha256"), 128),
        "bytes": item.get("bytes") if type(item.get("bytes")) is int else None,
        "ref": {"result_ref": result_ref, "index": ref["index"],
                "sha256": _bounded_text(ref.get("sha256"), 128)},
        "availability": _bounded_text(item.get("availability"), 64),
        "source": _bounded_text(item.get("source"), 512),
    }


def _bounded_usage(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unavailable", "reason": "no qualified capture-time usage summary retained"}
    result: dict[str, Any] = {}
    for key in ("state", "reason", "source", "metric", "scope", "input_tokens", "output_tokens", "total_tokens"):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[key] = item[:512] if isinstance(item, str) else item
    metrics = value.get("metrics")
    if isinstance(metrics, Mapping):
        result["metrics"] = {key: item for key, item in metrics.items()
            if key in {"input_tokens", "output_tokens", "total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"}
            and type(item) in {int, float} and item >= 0 and math.isfinite(item)}
    return result or {"state": "unavailable", "reason": "usage summary was empty"}


def _parent_delivery_projection(value: Any, parent: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unconsumed", "next_actor": parent}
    result: dict[str, Any] = {
        "state": _bounded_text(value.get("state"), 64) or "unconsumed",
        "next_actor": value.get("next_actor") or parent,
    }
    for key in ("report_ref", "delivery_identity"):
        if key == "report_ref":
            ref = _bounded_ref(value.get(key))
            if ref is not None:
                result[key] = ref
        elif isinstance(value.get(key), str):
            result[key] = value[key][:256]
    if isinstance(value.get("evidence"), Mapping):
        evidence = value["evidence"]
        result["evidence"] = {
            key: evidence[key] for key in ("schema", "result_sha256", "delivery_identity")
            if isinstance(evidence.get(key), str) and len(evidence[key]) <= 256
        }
    return result


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
    raw_outcome = result.get("outcome")
    delivery_state = result.get("delivery_state")
    native_terminal = delivery_state in {"done", "completed", "failed"} and raw_outcome not in {"unknown", "undetermined"}
    disposition_captured = (attempt.get("state") == "result" and native_terminal
                            and raw_outcome not in {None, "succeeded"})
    if not attempt:
        public_outcome = "prepared"
    elif raw_outcome in {"unknown", "undetermined"} or delivery_state == "unknown":
        public_outcome = "unknown"
    elif raw_outcome in {"action-needed", "action_needed", "needs_action"}:
        public_outcome = "action-needed"
    elif raw_outcome in {"failed", "error"} or delivery_state == "failed":
        public_outcome = "failed"
    elif raw_outcome == "succeeded" and not verified:
        # Native terminality is an observation, not canonical result capture.
        public_outcome = "held"
    else:
        public_outcome = raw_outcome or "held"
    failure = result.get("native_failure") if isinstance(result.get("native_failure"), Mapping) else result.get("error")
    if not isinstance(failure, Mapping):
        failure = None
    conclusion = summary.get("conclusion") if verified else None
    if conclusion is None and verified:
        conclusion = answer.get("text")
    if conclusion is None and disposition_captured and failure is not None:
        conclusion = _bounded_text(failure.get("message") or failure.get("detail"))
    disposition_revision = (summary.get("result_ref") or {}).get("revision") if isinstance(summary, Mapping) else None
    if disposition_revision is None:
        disposition_revision = result.get("disposition_revision") or result.get("observed_turn_id")
    delivery_identity = _delivery_identity(summary.get("result_ref"), disposition_revision)
    blockers: list[str] = []
    if raw_outcome == "succeeded" and not verified:
        blockers.append("required conclusion/capture not yet verified")
    if public_outcome == "unknown":
        blockers.append(_bounded_text(result.get("unknown_reason"), 512) or "retained owner result requires reconciliation")
    if disposition_captured and not verified and public_outcome in {"failed", "action-needed"}:
        blockers.append("disposition is retained without a canonical successful result publication")
    parent = due["target"].get("parent")
    parent_delivery = _parent_delivery_projection(host.get("parent_consumption"), parent)
    return {"schema": "otto.occurrence-result.v1", "pure": True, "occurrence": handle(due),
        "selection": (due["target"].get("launch_request") or {}).get("selection", due["target"].get("execution_selection")),
        "freshness": {"basis": "current retained owner snapshot", "due_version": due["version"],
                      "last_verified_at": due.get("completed_at"),
                      "last_verified": {"at": due.get("completed_at"), "due_version": due["version"],
                                         "source": "owner_due_snapshot"},
                      "history": "snapshot-only"},
        "outcome": public_outcome,
        "native_outcome": raw_outcome,
        "useful_admission": admission.get("native_turn_started", False),
        "native_identity": {"adapter": due["target"].get("native_adapter"),
                            "session": result.get("physical_session_id", (attempt.get("delivery_authorization") or {}).get("physical_session_id"))},
        "native_terminal": native_terminal,
        "required_capture": verified,
        "disposition_captured": disposition_captured or verified,
        "occurrence_settlement": {"stop_state": due["stop_state"], "completion_state": due["completion_state"]},
        "parent_delivery": parent_delivery,
        "task_acceptance": "unjudged; manager assessment required",
        "conclusion": _bounded_text(conclusion),
        "conclusion_sha256": summary.get("conclusion_sha256", answer.get("text_sha256")) if verified else None,
        "verification": {"context_digest_verified": verified, "observed_turn_id": result.get("observed_turn_id"),
                         "capture_state": "verified" if verified else "retained-disposition" if disposition_captured else "unavailable"},
        "result_ref": _bounded_ref(summary.get("result_ref")),
        "delivery_identity": delivery_identity,
        "error": None if failure is None else {key: _bounded_text(failure.get(key), 512) for key in ("code", "message") if key in failure},
        "next_actor": result.get("next_actor") or (failure or {}).get("next_actor"),
        "artifacts": [projected for item in host.get("captured_artifacts", [])[:16]
                      if (projected := _artifact_projection(item)) is not None],
        "usage": _bounded_usage(summary.get("usage")),
        "blockers": blockers,
        "stop": {"requested": due["stop_state"] == "stopped", "observed": due["stop_state"],
                 "owned_process_termination": "unverified"},
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
        same_artifact = [item for item in known
                         if isinstance(item.get("ref"), Mapping)
                         and item["ref"].get("index") == artifact_ref.get("index")
                         and item["ref"].get("sha256") == artifact_ref.get("sha256")]
        return {"outcome": "unavailable", "pure": True,
                "reason": "artifact_foreign_ref" if same_artifact else "artifact_absent",
                "retry": False, "provider_called": False, "reconciled": False}
    from otto.agents.claude_adapter import captured_artifact_bytes
    import base64
    body = captured_artifact_bytes(matches[0])
    if hashlib.sha256(body).hexdigest() != artifact_ref["sha256"]:
        return {"outcome": "unavailable", "pure": True, "reason": "artifact_digest_mismatch",
                "retry": False, "provider_called": False, "reconciled": False}
    part = body[offset:offset + max_bytes]
    return {"outcome": "available", "pure": True, "artifact_ref": dict(artifact_ref),
            "offset": offset, "bytes": len(part), "total_bytes": len(body),
            "content_base64": base64.b64encode(part).decode("ascii"), "eof": offset + len(part) >= len(body),
            "provider_called": False, "reconciled": False}
