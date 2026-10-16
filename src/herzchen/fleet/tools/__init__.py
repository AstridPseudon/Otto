"""The product-neutral core of a worker tool facade: per-assignment tokens, a tool facade, and the rule that a worker's check is feedback, never acceptance.

Every tool name, server name, role name and owner operation is supplied by the caller.
"""

from .facade import AllowlistedPort, OwnerPort, ToolFacade
from .rules import (
    CHECK,
    DONE,
    KINDS,
    TASK,
    Acceptance,
    AcceptanceError,
    FeedbackLedger,
    ToolRuleError,
    ToolSpec,
)
from .server import FacadeServer, request
from .tokens import Grant, TokenBook, TokenError

__all__ = [
    "FacadeServer",
    "request",
    "TokenBook",
    "TokenError",
    "Grant",
    "ToolSpec",
    "ToolRuleError",
    "TASK",
    "CHECK",
    "DONE",
    "KINDS",
    "FeedbackLedger",
    "Acceptance",
    "AcceptanceError",
    "ToolFacade",
    "OwnerPort",
    "AllowlistedPort",
]
