"""Presentation of one authenticated read; no owner port, query or new authority."""
from datetime import datetime, timezone
import hashlib
from typing import Any, Mapping

from herzchen.contracts import canonical_json

READS = ("whoami", "effective-context", "operating-setup", "review-input", "read-help")
_MAX_RESPONSE = 4 * 1024 * 1024
_MAX_PRESENTATION = 32 * 1024


def compact_read_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Translate only a read to the existing exact owner command, once."""
    if set(request) - {"command", "read", "task", "delivery_id"} or request.get("command") != "compact-read":
        raise ValueError("compact-read accepts only read, task or delivery-id; no caller/actor/project selectors")
    read = request.get("read")
    if read not in READS:
        raise ValueError("unsupported compact read")
    if read == "review-input":
        if set(request) != {"command", "read", "task"} or not isinstance(request["task"], str) or not request["task"]:
            raise ValueError("compact review-input requires one current task alias")
        return {"command": read, "task": request["task"]}
    if read == "read-help":
        if set(request) != {"command", "read", "delivery_id"} or not isinstance(request["delivery_id"], str) or not request["delivery_id"]:
            raise ValueError("compact read-help requires one exact delivery-id; it does not scan all issues")
        return {"command": read, "delivery_id": request["delivery_id"]}
    if set(request) != {"command", "read"}:
        raise ValueError("identity/setup compact reads take no task, delivery or caller selectors")
    return {"command": read, **({"operation": "read"} if read == "operating-setup" else {})}


def compact_read_response(value: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
    """Keep finite pins/status; name every excluded section and the full receipt.

    Freshness is the receipt of this one response, not a new canonical read.
    The digest names canonical JSON of the received response, not artifact bytes.
    Existing full readers and the host-retained response remain unchanged.
    """
    from .manager_journey_client import command_result_summary
    if operation not in READS or not isinstance(value, Mapping):
        raise ValueError("compact projection requires one supported read response")
    encoded = canonical_json(value).encode()
    if len(encoded) > _MAX_RESPONSE:
        raise ValueError("compact source response exceeds existing finite socket bound")
    availability = {}

    def finite(item: Any, path: str, depth: int = 0) -> Any:
        # Selected fields only. Never traverse omitted instructions/tool bodies.
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str) and len(item.encode()) <= 2048:
            return item
        if depth < 5 and isinstance(item, Mapping) and len(item) <= 256:
            projected = {}
            for name, child in item.items():
                if not isinstance(name, str) or len(name) > 256:
                    availability[path] = "invalid field name; use full receipt"
                    return None
                projected[name] = finite(child, path + "." + name, depth + 1)
            return projected
        if depth < 5 and isinstance(item, list) and len(item) <= 256:
            return [finite(child, path + "." + str(i), depth + 1) for i, child in enumerate(item)]
        availability[path] = "over-bound or unsupported value; use full receipt (not truncated)"
        return None

    def fields(item: Any, names: tuple[str, ...], path: str) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            availability[path] = "absent"
            return {}
        out = {name: finite(item[name], path + "." + name) for name in names if name in item}
        excluded = sorted(set(item) - set(names))
        if excluded:
            availability[path + ".excluded_fields"] = excluded
        return out

    summary = command_result_summary(dict(value))
    selected = fields(value, ("outcome", "schema", "state", "mode", "ready", "autonomous_ready",
        "execution_observed", "dispatch", "canonical_lifecycle", "capabilities", "provider_called",
        "effects_started", "retry", "next_action", "error", "message", "transport", "delivery_id",
        "issue_id", "report_ref", "report_sha256", "setup_ref", "project_ref", "roles", "source",
        "source_commit", "manifest_sha256", "content_sha256", "context_digest", "effective_context_digest",
        "observed_at", "projection_at", "heartbeat_at", "instruction_adoption",
        "help_destination", "blockers", "supported_application"), "response")
    identity = value.get("caller_context")
    selected["caller_context"] = fields(identity, ("schema", "source", "principal", "role",
        "responsibility_ref", "assignment_ref", "generation", "project_ref", "task_ref", "native_session",
        "occurrence_ref", "context_digest", "read_only", "authority", "read_effect_scope", "manager_worker_route"), "caller_context")
    directions = identity.get("direction_context") if isinstance(identity, Mapping) else None
    if isinstance(directions, list) and len(directions) <= 256:
        selected["direction_pins"] = [fields(row, ("source", "subject_ref", "assignment_ref", "generation",
            "binding_ref", "document_ref", "effective_ref", "assignment_adopted_ref", "scope_adopted_ref",
            "delivery_status", "delivered_ref", "latest_ref", "pending_scope_adoption", "pending_assignment_application",
            "content_sha256", "effective_context_digest",
            "read_only", "dispatch"), "direction." + str(i))
            for i, row in enumerate(directions)]
        for i, row in enumerate(directions):
            inputs = row.get("inputs") if isinstance(row, Mapping) else None
            if isinstance(inputs, list) and len(inputs) <= 256:
                selected["direction_pins"][i]["inputs"] = [fields(item, ("ref", "content_sha256", "source"),
                    "direction." + str(i) + ".input." + str(j)) for j, item in enumerate(inputs)]
            else:
                availability["direction." + str(i) + ".inputs"] = "absent" if inputs is None else "over-bound; use full receipt"
    else:
        availability["direction_pins"] = "absent" if directions is None else "over-bound; use full receipt"
    introductions = value.get("introductions")
    if isinstance(introductions, Mapping) and len(introductions) <= 32:
        selected["role_pins"] = {role: fields(intro, ("source", "principal", "role", "assignment_ref",
            "generation", "responsibility_ref", "mandate_ref", "base_resource", "supporting_refs",
            "tool_entrypoint", "tool_entrypoint_source", "conversation_id", "conversation_ref", "execution"), "role." + role)
            for role, intro in introductions.items() if isinstance(role, str)}
    report = value.get("retained_report")
    if report is not None:
        selected["retained_report"] = fields(report, ("schema", "issue_id", "logical_request_key",
            "recorded_at", "actor", "authority_source", "response", "proposed_solution", "next_action",
            "project_ref", "response_ref", "state"), "retained_report")
    for name in ("criterion_aliases", "criterion_aliases_availability", "inspection_schema", "candidate_ref",
                 "task_ref", "schedule_id", "source_refs", "evidence_refs", "worker_result_sha256"):
        if name in summary:
            selected[name] = summary[name]
    outer = value.get("outer_command")
    detail = fields(outer, ("transport", "request_id", "retained", "retention"), "outer_command")
    request_id = detail.get("request_id")
    if isinstance(request_id, str):
        detail["receipt_read"] = "command-status --request-id " + request_id
    detail["availability"] = "host retained response" if detail.get("retained") is True else "retention unconfirmed"
    result = {"schema": "otto.compact-authenticated-read.v1", "operation": operation,
        "outcome": value.get("outcome"), "projection": selected,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "freshness": "one received authenticated response; source timestamps/pins unchanged",
        "full_response": {**detail, "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
                          "canonical_json_bytes": len(encoded), "digest_serialization": "canonical-json",
                          "artifact_byte_hash": "not computed by this presentation"},
        "availability": availability,
        "availability_semantics": "absent, excluded or over-bound presentation fields do not establish absent authority or blockers; inspect the exact full receipt when needed",
        "authority": "presentation only; original authorization/effects/UNKNOWN remain unchanged"}
    if len(canonical_json(result).encode()) > _MAX_PRESENTATION:
        result["projection"] = summary
        result["availability"] = {"projection": "over-bound; use full retained receipt; no hidden clipping"}
        if len(canonical_json(result).encode()) > _MAX_PRESENTATION:
            result["projection"] = {"outcome": value.get("outcome")}
    return result
