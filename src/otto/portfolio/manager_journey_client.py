"""Argument definitions shared with the existing owner-held command client."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


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
              "physical_session_id", "context_digest_verified", "request_key")
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
    return summary


def add_manager_journey_parsers(commands: Any) -> None:
    """Add intention-shaped operations without copying the existing transport."""
    status = commands.add_parser("command-status", help="read one retained transport handle without another send")
    status.add_argument("--request-id", required=True)
    review = commands.add_parser("review-task", help="record explicit criterion judgment and guarded task finish")
    review.add_argument("--task", required=True)
    review.add_argument("--request-key", required=True)
    review.add_argument("--candidate-ref", required=True, type=json.loads)
    review.add_argument("--source-ref", action="append", dest="source_refs", required=True, type=json.loads)
    review.add_argument("--judgments", required=True, type=json.loads,
                        help="criterion alias -> verdict, rationale, evidence_refs; every configured task criterion")
    review.add_argument("--inspection", required=True, type=json.loads, help="substantive observations, not an automatic verdict")
    review.add_argument("--review-only", action="store_false", dest="finish",
                        help="retain judgment without requesting task completion")
    finish = commands.add_parser("finish-task", help="finish a retained accepted review; never invoke the provider")
    finish.add_argument("--task", required=True)
    finish.add_argument("--request-key", required=True)
    finish.add_argument("--review-key", required=True)
    project = commands.add_parser("finish-project", help="close completed project tasks and read actual terminal settlement")
    project.add_argument("--request-key", required=True)
    project.add_argument("--dispositions", required=True, type=json.loads,
                         help="acceptance/publication/remote/runtime: qualified status and rationale")
    worker = commands.add_parser("worker-status", help="read or settle the retained worker handle; no provider retry")
    worker.add_argument("--task", required=True)
    worker.add_argument("--principal", required=True)
    worker.add_argument("--schedule-id", required=True)
