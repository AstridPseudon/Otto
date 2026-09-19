"""Manager-led pending-project operations over canonical Herzchen work.

The portfolio package is deliberately a boundary.  It does not persist work,
create a second event engine, or start a host session.  A caller supplies the
accepted Herzchen work-operation port and receives its durable references and
receipts unchanged.
"""

from .intake import (
    ADMISSION_CHOICES,
    EDITABLE_FIELDS,
    PortfolioError,
    OttoPortfolio,
    HerzchenWorkOperations,
    unavailable_operations,
)
from .herzchen_binding import FiniteWorkOperations, HerzchenBindingConfig
from .owner_bootstrap import CreateAndOpenCommandPort, PortfolioOwnerBootstrap
from .inbox import InboxCursorError, derive_manager_inbox
from .execution_resume import ExecutionResumeError, execute_selected_packet, packet_digest
from .sense_check import SenseCheckError, hourly_sense_check
from .steady_state import SteadyStateError, build_manager_action_packet, fence_replacement
from .lifecycle import LifecycleIntegrationError, PortfolioLifecycleIntegration

__all__ = [
    "ADMISSION_CHOICES",
    "EDITABLE_FIELDS",
    "HerzchenWorkOperations",
    "HerzchenBindingConfig",
    "OttoPortfolio",
    "PortfolioError",
    "unavailable_operations",
    "FiniteWorkOperations",
    "CreateAndOpenCommandPort",
    "PortfolioOwnerBootstrap",
    "InboxCursorError",
    "derive_manager_inbox",
    "ExecutionResumeError",
    "execute_selected_packet",
    "packet_digest",
    "SenseCheckError",
    "hourly_sense_check",
    "SteadyStateError",
    "build_manager_action_packet",
    "fence_replacement",
    "LifecycleIntegrationError",
    "PortfolioLifecycleIntegration",
]
