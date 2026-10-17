"""Manager-led project authoring, current work and role preparation.

The portfolio package is deliberately a boundary.  It does not persist work,
create a second event engine, or start a host session.  A caller supplies the
accepted Herzchen work-operation port and receives its durable references and
receipts unchanged.
"""

from .intake import (
    ADMISSION_CHOICES,
    CurrentWork,
    EDITABLE_FIELDS,
    PortfolioError,
    OttoPortfolio,
    HerzchenWorkOperations,
    unavailable_operations,
)
from .issue_loop import IssueLoop, IssueLoopError, IssueLoopPorts
from .herzchen_binding import FiniteWorkOperations, HerzchenBindingConfig
from .owner_bootstrap import CreateAndOpenCommandPort, PortfolioOwnerBootstrap
from .inbox import InboxCursorError, derive_manager_inbox
from .operating_brief import (
    OperatingBrief,
    OperatingBriefAuthoringAdapter,
    OperatingBriefError,
    prepare_canonical_operating_brief,
    render_operating_brief,
)
from .execution_resume import ExecutionResumeError, execute_selected_packet, packet_digest
from .sense_check import SenseCheckError, hourly_sense_check
from .steady_state import SteadyStateError, build_manager_action_packet, fence_replacement
from .resource_sync import (
    DELIVERY_STATES,
    LIFECYCLES,
    ROLES,
    ResourceAttachment,
    ResourceSyncError,
    brief_resource_evidence,
    compose_role_brief,
    normalize_attachment,
    normalize_instruction_contract,
    normalize_role_attachments,
    resolve_role_resources,
    resolve_role_attachments,
    resolve_assignment_attachments,
    role_resource_pins,
    validate_resource_evidence,
)
from .manager_continuity import ManagerContinuity, ManagerContinuityError
from .execution_operations import (
    OccurrencePreparationError,
    build_manager_callback_due,
    prepare_current_assignment_occurrence,
)
from .advisor_pairing import (
    AdvisorPairing,
    AdvisorPairingError,
    conversation_for,
    establish_pairing,
    introductions,
    validate_recipient,
)
from .advisor_context import AdvisorContextError, build_advisor_context, choose_advisor_direction
from .advisor_delivery import (
    AdvisorDeliveryError,
    AdvisorDeliveryLoop,
    AdvisorDeliveryPorts,
    ExactSessionDelivery,
)
from .manager_inventory import ManagerInventoryError, ManagerInventoryReader
from .manager_handoff import ManagerHandoffError, compose_manager_handoff
from .lifecycle import LifecycleIntegrationError, PortfolioLifecycleIntegration
from .resource_drift import ResourceDriftError, apply_resource_sync_action, select_resource_sync_action
from .orchestrator_placement import (
    ExplicitPeerRequired,
    ForeignAuthorityError,
    OrchestratorPlacementError,
    OverlapAcknowledgementRequired,
    RecursiveOrchestrationError,
    StalePlacementError,
    build_orchestrator_view,
    guard_peer_request,
    place_new_project,
    preview_peer_request,
)
from .observability_contract import (
    CANDIDATE_ROOT,
    CLIENT_PIN,
    CONTEXT_PINS,
    CONTRACT_REVISION,
    CONTRACT_SCHEMA,
    EVENTS_READ_LIMITS,
    FIXTURE_INVENTORY,
    HISTORY_FACETS,
    HISTORICAL_FIELDS,
    LEGACY_GAP_RULES,
    ObservationRef,
    ObservabilityContractError,
    RESOURCE_PINS,
    RUNTIME_PIN,
    SOURCE_COMMIT,
    SOURCE_SEAMS,
    SourcePin,
    FixtureSpec,
    ReadLimits,
    contract_digest,
    contract_record,
)
from .observability_views import ObservabilityViewError, ObservabilityViews, VIEW_PRESETS
from .events_candidate_proof import CandidateProofError, PROOF_SCHEMA, run_candidate_journey


def __getattr__(name):
    """Provide the former role-table names as views over the versioned pack."""
    if name not in {"ROLE_OPERATING_CONTRACTS", "ROLE_CONTEXT_GUIDANCE"}:
        raise AttributeError(name)
    import json
    from pathlib import Path
    from herzchen.packs.authoring import read_managed_pack
    from otto.hostctl.owner import _managed_source_state_path

    source_root = Path(__file__).resolve().parents[2]
    project_root = source_root.parent
    pack = read_managed_pack("otto-roles", project_root=project_root,
        native_pack_root=source_root / "otto" / "packs",
        source_state_path=_managed_source_state_path())
    resource = next(item for item in pack.resources if item.path == "roles.json")
    content = json.loads(resource.content.decode("utf-8"))
    if name == "ROLE_CONTEXT_GUIDANCE":
        return {role: item["guidance"] for role, item in content["roles"].items()}
    from .operating_brief import _host_role_guidance
    return {role: item["responsibility"] + (_host_role_guidance(base_text=content["adapter_role_guidance"])
            if item.get("include_adapter_guidance") else "")
            for role, item in content["roles"].items()}

__all__ = [
    "ADMISSION_CHOICES",
    "CurrentWork",
    "EDITABLE_FIELDS",
    "HerzchenWorkOperations",
    "HerzchenBindingConfig",
    "OttoPortfolio",
    "PortfolioError",
    "unavailable_operations",
    "IssueLoop",
    "IssueLoopError",
    "IssueLoopPorts",
    "FiniteWorkOperations",
    "CreateAndOpenCommandPort",
    "PortfolioOwnerBootstrap",
    "InboxCursorError",
    "derive_manager_inbox",
    "OperatingBrief",
    "OperatingBriefAuthoringAdapter",
    "OperatingBriefError",
    "ROLE_CONTEXT_GUIDANCE",
    "ROLE_OPERATING_CONTRACTS",
    "prepare_canonical_operating_brief",
    "render_operating_brief",
    "ExecutionResumeError",
    "execute_selected_packet",
    "packet_digest",
    "SenseCheckError",
    "hourly_sense_check",
    "SteadyStateError",
    "build_manager_action_packet",
    "fence_replacement",
    "DELIVERY_STATES",
    "LIFECYCLES",
    "ROLES",
    "ResourceAttachment",
    "ResourceSyncError",
    "brief_resource_evidence",
    "compose_role_brief",
    "normalize_attachment",
    "normalize_instruction_contract",
    "normalize_role_attachments",
    "resolve_role_resources",
    "resolve_role_attachments",
    "resolve_assignment_attachments",
    "role_resource_pins",
    "validate_resource_evidence",
    "ManagerInventoryError",
    "ManagerInventoryReader",
    "ManagerHandoffError",
    "compose_manager_handoff",
    "ManagerContinuity",
    "ManagerContinuityError",
    "OccurrencePreparationError",
    "build_manager_callback_due",
    "prepare_current_assignment_occurrence",
    "AdvisorPairing",
    "AdvisorPairingError",
    "conversation_for",
    "establish_pairing",
    "introductions",
    "validate_recipient",
    "AdvisorContextError",
    "build_advisor_context",
    "choose_advisor_direction",
    "AdvisorDeliveryError",
    "AdvisorDeliveryLoop",
    "AdvisorDeliveryPorts",
    "ExactSessionDelivery",
    "LifecycleIntegrationError",
    "PortfolioLifecycleIntegration",
    "ResourceDriftError",
    "apply_resource_sync_action",
    "select_resource_sync_action",
    "ExplicitPeerRequired",
    "ForeignAuthorityError",
    "OrchestratorPlacementError",
    "OverlapAcknowledgementRequired",
    "RecursiveOrchestrationError",
    "StalePlacementError",
    "build_orchestrator_view",
    "guard_peer_request",
    "place_new_project",
    "preview_peer_request",
    "CANDIDATE_ROOT",
    "CLIENT_PIN",
    "CONTEXT_PINS",
    "CONTRACT_REVISION",
    "CONTRACT_SCHEMA",
    "EVENTS_READ_LIMITS",
    "FIXTURE_INVENTORY",
    "HISTORY_FACETS",
    "HISTORICAL_FIELDS",
    "LEGACY_GAP_RULES",
    "ObservationRef",
    "ObservabilityContractError",
    "RESOURCE_PINS",
    "RUNTIME_PIN",
    "SOURCE_COMMIT",
    "SOURCE_SEAMS",
    "SourcePin",
    "FixtureSpec",
    "ReadLimits",
    "contract_digest",
    "contract_record",
    "ObservabilityViewError",
    "ObservabilityViews",
    "VIEW_PRESETS",
    "CandidateProofError",
    "PROOF_SCHEMA",
    "run_candidate_journey",
]
