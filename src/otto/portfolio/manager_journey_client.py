"""Argument definitions shared with the existing owner-held command client."""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
from typing import Any

FINISH_PROJECT_EXAMPLE = (
    "ottoctl finish-project --request-key local-project-close-v1 --dispositions '"
    '{"acceptance":{"status":"passed","rationale":"All actual tasks retain accepted candidates and committed completion"},'
    '"publication":{"status":"qualified","rationale":"Local artifact delivery; publication is not required"},'
    '"remote":{"status":"qualified","rationale":"Local delivery; remote push is not required"},'
    '"runtime":{"status":"qualified","rationale":"Owner retains bounded callbacks and reconciles project-owned schedules"}}'
    "'"
)

FINISH_PROJECT_HELP = """Use this guarded operation after all actual tasks have committed completion.
Choose dispositions that match observed facts; the example is not acceptance.

Example (copy as one shell command):
""" + FINISH_PROJECT_EXAMPLE + """

A pending reply retains the request handle. Use command-status --request-id HANDLE
to recover that exact reply; do not repeat the finish effect with another key.
If finish waits on your own manager turn, return so the owner can settle it.
Terminal transport alone is not project completion: inspect the retained response
for project_completion_recorded=true, settlement_pending=false, and a completed
readback with reconciliation.status=reconciled. A held/unknown result is not PASS.
project-lifecycle-read exposes the current canonical lifecycle without mutation.
No low-level lifecycle pins or controller-source inspection are needed.
"""


def read_command_status(directory: str | Path, request_id: str, *, pending_only: bool = False) -> Any:
    """Read the exact retained transport handle without sending another command."""
    if not isinstance(request_id, str) or not request_id or any(c not in "0123456789abcdef" for c in request_id):
        raise ValueError("request_id must be the exact hexadecimal transport handle")
    root = Path(directory)
    response = root / ("response-" + request_id + ".json")
    try:
        raw = response.read_bytes()
        if pending_only:
            return None  # call() will consume the terminal response on its next read.
        value = json.loads(raw)
        return {"outcome": value.get("outcome", "unavailable"), "terminal": True,
                "request_id": request_id, "response_path": str(response),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "response_utf8_bytes": len(raw), "retry": False,
                "summary": command_result_summary(value),
                "next_action": "Inspect the retained response artifact for full evidence; do not resend this terminal request."}
    except FileNotFoundError:
        pass
    try:
        pending = json.loads((root / ("pending-" + request_id + ".json")).read_text())
    except FileNotFoundError:
        return None
    if (pending.get("outcome") != "pending" or pending.get("request_id") != request_id
            or pending.get("request_retained") is not True or pending.get("response_path") != str(response)):
        raise ValueError("pending transport receipt differs from the exact request")
    return pending


def read_command_response(directory: str | Path, request_id: str) -> Any:
    """Consume the result semantically while preserving its evidence artifact.

    Ordinary small results retain their full refs and judgments. Large results
    expose the same bounded terminal view as command-status; the path/digest
    names the full bytes rather than embedding them into the next native turn.
    """
    status = read_command_status(directory, request_id)
    if status is None or status.get("terminal") is not True:
        return None
    if status["response_utf8_bytes"] <= 64 * 1024:
        return json.loads(Path(status["response_path"]).read_text())
    return status


def command_result_summary(value: Any) -> Any:
    """Bound native-facing status without copying transport or nested prose.

    The full response remains its immutable artifact. Only fixed, typed status
    fields cross this read surface; nested tool output cannot become status.
    """
    if not isinstance(value, dict):
        return {"outcome": "unavailable"}
    fields = ("outcome", "stage", "schedule_id", "principal", "generation",
              "provider_called", "retry_provider", "retry", "unknown_reason",
              "observed_model", "observed_reasoning", "observed_turn_id",
              "physical_session_id", "context_digest_verified", "request_key", "delivery_state",
              "model", "reasoning", "native_session_id", "retained_handle", "response_path",
              "version", "in_flight_request", "stop_state", "completion_state", "role", "status", "manager",
              "project_completion_recorded", "settlement_pending", "canonical_lifecycle", "blocked_operation")
    summary = {key: item for key in fields if key in value
               and isinstance((item := value[key]), (str, bool, int, type(None)))
               and (not isinstance(item, str) or len(item) <= 512)}
    for key in ("continuation", "result", "completion"):
        child = value.get(key)
        if isinstance(child, dict):
            # Two known status layers suffice for execution completion. Never
            # recurse into envelopes, raw results, commands or worker text.
            nested = {field: item for field in fields if field in child
                      and isinstance((item := child[field]), (str, bool, int, type(None)))
                      and (not isinstance(item, str) or len(item) <= 512)}
            if key == "continuation" and isinstance(child.get("result"), dict):
                nested["result"] = {field: item for field in fields if field in child["result"]
                    and isinstance((item := child["result"][field]), (str, bool, int, type(None)))
                    and (not isinstance(item, str) or len(item) <= 512)}
            summary[key] = nested
    def ref(item):
        keys = ("authority", "kind", "id", "revision")
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str)
                or len(item[key]) > 256 for key in keys[:3]):
            return None
        return {key: item[key] for key in keys if isinstance(item.get(key), str) and len(item[key]) <= 256}
    if ref(value.get("project_ref")):
        summary["project_ref"] = ref(value["project_ref"])
    for key in ("task_refs", "criteria"):
        items = value.get(key)
        if isinstance(items, dict):
            summary[key] = {name: ref(item) for name, item in list(items.items())[:64]
                            if isinstance(name, str) and len(name) <= 64 and ref(item)}
    for key in ("native_manager", "manager_assignment", "occurrence"):
        item = value.get(key)
        if isinstance(item, dict):
            summary[key] = {field: data for field in fields if field in item
                and isinstance((data := item[field]), (str, bool, int, type(None)))
                and (not isinstance(data, str) or len(data) <= 512)}
            for field in ("ref", "scope", "assignment_ref"):
                if ref(item.get(field)): summary[key][field] = ref(item[field])
    workers = value.get("workers")
    if isinstance(workers, dict):
        summary["workers"] = {}
        for name, worker in list(workers.items())[:64]:
            if not isinstance(name, str) or len(name) > 64 or not isinstance(worker, dict): continue
            summary["workers"][name] = {field: data for field in fields if field in worker
                and isinstance((data := worker[field]), (str, bool, int, type(None)))
                and (not isinstance(data, str) or len(data) <= 512)}
            for field in ("assignment_ref", "guide_ref", "mandate_ref"):
                if ref(worker.get(field)): summary["workers"][name][field] = ref(worker[field])
    review = value.get("review_input")
    if isinstance(review, dict):
        summary["review_input"] = {key: review[key] for key in ("outcome", "schedule_id", "worker_result_sha256", "observed_turn_id", "physical_session_id")
                                   if isinstance(review.get(key), str) and len(review[key]) <= 512}
        for key in ("candidate_ref", "task_ref"):
            if ref(review.get(key)): summary["review_input"][key] = ref(review[key])
        for key in ("source_refs", "evidence_refs"):
            if isinstance(review.get(key), list): summary["review_input"][key] = [ref(item) for item in review[key][:64] if ref(item)]
    status = value.get("status")
    if not isinstance(status, dict):
        status = value.get("operation_status")
    if isinstance(status, dict):
        status_fields = ("schema", "project_completion_recorded", "settlement_pending", "canonical_lifecycle",
                         "blocked_operation", "read_only", "dispatch", "launch", "agent_suggestion")
        summary["status"] = {key: status[key] for key in status_fields if key in status
                              and isinstance(status[key], (str, bool, int, type(None)))}
        for layer in ("transport_completion", "accepted_review", "task_settlement",
                      "canonical_project_completion", "current_required_scope", "pending_help",
                      "instruction_provenance", "supported_next_remedy"):
            item = status.get(layer)
            if not isinstance(item, dict):
                continue
            if layer in {"current_required_scope", "instruction_provenance"}:
                summary["status"][layer] = {"state": item.get("state"), "value": item.get("value"),
                                             "reason": item.get("reason")}
            elif layer == "pending_help":
                summary["status"][layer] = {key: item.get(key) for key in
                    ("state", "status", "issue_id", "purpose", "destination", "delivery_id", "resolution")
                    if key in item}
            else:
                summary["status"][layer] = {key: item[key] for key in
                    ("state", "completed", "settled", "schedule_id", "request_id", "project_completion_recorded",
                     "lifecycle", "reconciliation", "accepted", "supported", "operation", "command", "reason")
                    if key in item and isinstance(item[key], (str, bool, int, type(None), dict, list))}
    return summary


def _review_ref(value: str) -> Any:
    try:
        result = json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("supply one resource-ref JSON object") from exc
    if not isinstance(result, dict) or not all(isinstance(result.get(key), str) and result[key]
            for key in ("authority", "kind", "id", "revision")):
        raise argparse.ArgumentTypeError("supply one pinned resource-ref JSON object; repeat --source-ref for each source, not a JSON array")
    return result


def add_help_parsers(commands: Any) -> list[Any]:
    """Shared help operations; the owning surface supplies scope and actor."""
    parsers = []
    for name, purpose, recipient in (
        ("request-help", "operational blockage", "the current orchestrator/help destination"),
        ("request-advice", "project judgment; requires enabled advisor policy", "the current paired project advisor"),
    ):
        request = commands.add_parser(name, help="request " + purpose,
            description=("Send a bounded " + purpose + " request to " + recipient + ". Include the problem, impact, "
                         "evidence, requested decision and return condition. The exact current recipient and "
                         "retained delivery status are separate from resolution; continue independent useful work. "
                         "If the destination is missing, the request remains unresolved. Reconcile an unknown "
                         "delivery before any retry; do not resend blindly."))
        parsers.append(request)
        request.add_argument("--request-key", required=True)
        request.add_argument("--issue-key", required=True)
        for field in ("problem", "impact", "requested-decision", "return-condition"):
            request.add_argument("--" + field, required=True)
        request.add_argument("--evidence", required=True, type=json.loads)
    read = commands.add_parser("read-help", help="read help/advice disposition and exact delivery receipts without dispatch",
        description="Read the exact issue, recipient, destination and delivery receipt. A missing destination or unknown send is unresolved; this command does not resend or create a replacement role.")
    read.add_argument("--delivery-id", help="reconcile one retained delivery without resend")
    reply = commands.add_parser("respond-help", help="bound recipient returns a response; automatically retains same-manager continuation",
        description="Respond only from the current bound recipient. The response is advice or operational help, not automatic acceptance; the existing manager continuation is retained for the manager to inspect and act on.")
    reply.add_argument("--request-key", required=True)
    reply.add_argument("--issue-id", required=True)
    for field in ("authority-source", "response", "proposed-solution", "next-action"):
        reply.add_argument("--" + field, required=True)
    resolve = commands.add_parser("resolve-help", help="manager records applied response evidence and continues ready work",
        description="Record what the manager actually applied and the next action. Refresh current assignment/generation/conversation after role replacement; a retained or unknown delivery must be reconciled before continuation.")
    resolve.add_argument("--request-key", required=True)
    resolve.add_argument("--issue-id", required=True)
    resolve.add_argument("--evidence", required=True, type=json.loads)
    resolve.add_argument("--next-action", required=True)
    return [*parsers, read, reply, resolve]


def add_manager_journey_parsers(commands: Any) -> None:
    """Add intention-shaped operations without copying the existing transport."""
    add_help_parsers(commands)
    setup = commands.add_parser("operating-setup", help="read or prepare draft/ready/active setup; activate only after shared readiness",
        description=("Preparation validates existing role schedules, adopted BASE, conversations, execution contracts and "
                     "required acceptance scopes without provider work. The result distinguishes advice from operational "
                     "help, reports a missing destination or host-only/manual route, and names the current recovery path. "
                     "Autonomous mode requires a real help delivery port and explicit enabled/disabled advisor policy. "
                     "Manual mode remains explicitly supervised. Administrative project activation does not dispatch a manager."))
    setup.add_argument("--operation", choices=("read", "prepare", "activate"), default="read")
    setup.add_argument("--setup", type=json.loads, help="otto.operating-setup.v1 object: mode, roles (existing schedule IDs), advisor_policy, acceptance_tasks (exact refs)")
    setup.add_argument("--request-key", help="required for idempotent preparation; changed setup uses existing document authoring")
    status = commands.add_parser("command-status", help="read one retained transport handle without another send")
    status.add_argument("--request-id", required=True)
    inputs = commands.add_parser("review-input", help="read exact retained worker candidate/evidence refs without judging or sending work")
    inputs.add_argument("--task", required=True)
    review = commands.add_parser("review-task", help="record explicit criterion judgment and guarded task finish")
    review.add_argument("--task", required=True)
    review.add_argument("--request-key", required=True)
    review.add_argument("--candidate-ref", required=True, type=_review_ref, help="one pinned resource-ref object from review-input or admitted artifact content")
    review.add_argument("--source-ref", action="append", dest="source_refs", required=True, type=_review_ref,
                        help="one pinned object per flag; repeat this flag for additional sources")
    review.add_argument("--judgments", required=True, type=json.loads,
                        help="criterion alias -> verdict, rationale, evidence_refs; rationale is nonblank text without slash/backslash; put paths in inspection; include actual candidate in evidence_refs")
    review.add_argument("--inspection", required=True, type=json.loads, help="substantive observations, not an automatic verdict")
    review.add_argument("--review-only", action="store_false", dest="finish",
                        help="retain judgment without requesting task completion")
    finish = commands.add_parser("finish-task", help="finish a retained accepted review; never invoke the provider")
    finish.add_argument("--task", required=True)
    finish.add_argument("--request-key", required=True)
    finish.add_argument("--review-key", required=True)
    project = commands.add_parser("finish-project", help="close completed project tasks and read actual terminal settlement",
                                  description=FINISH_PROJECT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    project.add_argument("--request-key", required=True)
    project.add_argument("--dispositions", required=True, type=json.loads,
                         help="acceptance/publication/remote/runtime: qualified status and rationale")
    worker = commands.add_parser("worker-status", help="read or settle the retained worker handle; no provider retry")
    worker.add_argument("--task", required=True)
    worker.add_argument("--principal", required=True)
    worker.add_argument("--schedule-id", required=True)
