"""Local Otto agent adapter package scaffold."""
from .gateway import (
    OPERATIONS,
    AttemptCapturePort,
    AttemptEnvelope,
    InMemoryAttemptCapture,
    DueRecordAttemptCapture,
    HerzchenAttemptCapture,
    OwnerDueRecordAttemptCapture,
    OttoGateway,
    Responsibility,
    MO02B_SLOT3_REQUEST_KEY,
    continue_admitted_occurrence,
    run_due_occurrence,
    run_scheduled_callback,
    error,
)
from .codex_cli import CodexCliAdapter, CodexCliAdapterError, LaunchUncertainError, normalize_codex_jsonl
from .orchestrator_route import (
    OrchestratorRouteError,
    invoke_canonical_assignment,
    prepare_canonical_assignment_role_brief,
    prepare_canonical_callback,
    compose_owner_resource_herzchen_adapter,
    invoke_assignment,
    prepare_assignment_role_brief,
)
from .herzchen_adapter import HerzchenAdapterError, HerzchenCodexAdapter, JsonlHostTurnContextReader

from .owner_runtime import CanonicalRoleRuntime, OwnerRoleRuntimeError

__all__ = [
    "HerzchenAttemptCapture", "OwnerDueRecordAttemptCapture",
    "invoke_canonical_assignment", "prepare_canonical_assignment_role_brief",
    "prepare_canonical_callback", "CanonicalRoleRuntime", "OwnerRoleRuntimeError",
    "OPERATIONS",
    "AttemptCapturePort",
    "AttemptEnvelope",
    "InMemoryAttemptCapture",
    "DueRecordAttemptCapture",
    "OttoGateway",
    "Responsibility",
    "MO02B_SLOT3_REQUEST_KEY",
    "continue_admitted_occurrence",
    "run_due_occurrence",
    "run_scheduled_callback",
    "error",
    "OrchestratorRouteError",
    "compose_owner_resource_herzchen_adapter",
    "invoke_assignment",
    "prepare_assignment_role_brief",
    "CodexCliAdapter",
    "CodexCliAdapterError",
    "LaunchUncertainError",
    "normalize_codex_jsonl",
    "HerzchenAdapterError",
    "HerzchenCodexAdapter",
    "JsonlHostTurnContextReader",
]
