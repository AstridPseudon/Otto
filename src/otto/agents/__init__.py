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
from herzchen.fleet.hosts.codex import normalize_codex_jsonl
from herzchen.usage.contract import (
    CHARGEABLE_FIELDS,
    CONTRACT_SCHEMA as USAGE_CONTRACT_SCHEMA,
    OBSERVATION_SCHEMA as USAGE_OBSERVATION_SCHEMA,
    UsageContractError,
    adapter_descriptors,
    contract_definition as _contract_definition,
    fixture_catalog,
    normalize_usage_event,
    physical_span_identity,
    run_fixture_contract,
    validate_rate_schedule,
)
from herzchen.usage.accounting import (
    FACT_SCHEMA as USAGE_FACT_SCHEMA,
    MONEY_SCHEMA as USAGE_MONEY_SCHEMA,
    PRICE_SCHEMA as USAGE_PRICE_SCHEMA,
    account_usage,
    calculate_cost,
    estimate_cost,
    estimate_span_cost,
    estimate_usage_cost,
    normalize_provider_money,
    price_usage,
)
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
from .adapter_conformance import (
    SCHEMA as ADAPTER_CONTRACT_SCHEMA,
    AdapterContractError,
    AdapterConformanceFailure,
    AdapterSurface,
    BASELINE_SCHEMA,
    CLI_CONTRACT,
    ConformanceCase,
    ConformanceReport,
    bounded_result_view,
    capability_inventory,
    cli_contract,
    delivery_identity,
    d01_baseline_artifact,
    exact_lookup,
    normalize_pins,
    parent_binding,
    request_fingerprint,
    run_conformance,
    scope_identity,
    subtract_compatible_overlap,
    validate_caller_claims,
    validate_d01_baseline_artifact,
    validate_native_proof,
    validate_parent_binding,
)

from .claude_cli import ClaudeBindingError, ClaudeCliTransport, ClaudeStream, LauncherPin, MacWriteScope
from .claude_adapter import ClaudeWorkerAdapter, ClaudeNativeResultVerifier


def contract_definition():
    """Bind the shared usage contract to Otto's selected pack provenance."""

    return _contract_definition(
        selected_pack_ref={
            "authority": "otto-project-operating-setup-20261005-owner-v1",
            "id": "usage-bootstrap-20261010-v1-selected-pack",
            "kind": "dat.content.document",
            "revision": "rev-1",
        },
        selected_pack_root=(
            "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/"
            "otto-usage-cost-20261010/controller/selected-pack-source"
        ),
        source_root=(
            "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/"
            "otto-usage-cost-20261010/work/integration-owner"
        ),
        runtime_interpreter=(
            "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/"
            "Versions/3.9/bin/python3.9"
        ),
        runtime_command=(
            "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/"
            "Versions/3.9/bin/python3.9 /Users/hannahomalley/Documents/Codex/2026-09-13/"
            "can-x20/.otto/runs/otto-usage-cost-20261010/controller/manager_ctl.py"
        ),
    )

__all__ = [
    "ClaudeBindingError", "ClaudeCliTransport", "ClaudeStream", "LauncherPin", "MacWriteScope",
    "ClaudeWorkerAdapter", "ClaudeNativeResultVerifier",
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
    "normalize_codex_jsonl",
    "CHARGEABLE_FIELDS",
    "USAGE_CONTRACT_SCHEMA",
    "USAGE_OBSERVATION_SCHEMA",
    "UsageContractError",
    "adapter_descriptors",
    "contract_definition",
    "fixture_catalog",
    "normalize_usage_event",
    "physical_span_identity",
    "run_fixture_contract",
    "validate_rate_schedule",
    "USAGE_FACT_SCHEMA",
    "USAGE_MONEY_SCHEMA",
    "USAGE_PRICE_SCHEMA",
    "account_usage",
    "calculate_cost",
    "estimate_cost",
    "estimate_span_cost",
    "estimate_usage_cost",
    "normalize_provider_money",
    "price_usage",
    "HerzchenAdapterError",
    "HerzchenCodexAdapter",
    "JsonlHostTurnContextReader",
    "ADAPTER_CONTRACT_SCHEMA",
    "AdapterContractError",
    "AdapterConformanceFailure",
    "AdapterSurface",
    "BASELINE_SCHEMA",
    "CLI_CONTRACT",
    "ConformanceCase",
    "ConformanceReport",
    "bounded_result_view",
    "capability_inventory",
    "cli_contract",
    "delivery_identity",
    "d01_baseline_artifact",
    "exact_lookup",
    "normalize_pins",
    "parent_binding",
    "request_fingerprint",
    "run_conformance",
    "scope_identity",
    "subtract_compatible_overlap",
    "validate_caller_claims",
    "validate_d01_baseline_artifact",
    "validate_native_proof",
    "validate_parent_binding",
]
