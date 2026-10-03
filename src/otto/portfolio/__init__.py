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
    ROLE_OPERATING_CONTRACTS,
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
from .execution_operations import OccurrencePreparationError, prepare_current_assignment_occurrence
from .advisor_pairing import (
    AdvisorPairing,
    AdvisorPairingError,
    conversation_for,
    establish_pairing,
    introductions,
    validate_recipient,
)
from .advisor_context import AdvisorContextError, build_advisor_context, choose_advisor_direction
from .manager_inventory import ManagerInventoryError, ManagerInventoryReader
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
    "ManagerContinuity",
    "ManagerContinuityError",
    "OccurrencePreparationError",
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
]
