"""Argument definitions shared with the existing owner-held command client."""
from __future__ import annotations

import json
from typing import Any


def add_manager_journey_parsers(commands: Any) -> None:
    """Add intention-shaped operations without copying the existing transport."""
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
