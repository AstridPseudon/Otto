"""Agent harnesses behind one contract. Adding a harness is one ``HostKind`` implementation."""

from . import claude, codex
from .claude import ClaudeHost
from .codex import CodexHost
from .contract import (SLOTS, HostContractError, HostEvent, HostKind, HostRegistry, HostStream, LaunchPlan,
                       McpGrant, McpServer, ModelBinding, NativeFlagFence, TurnResult, TurnSpec,
                       UnknownHostKind, WriteFence, run_turn)

# The hosts this installation can drive. A kind that is not here is refused, never defaulted.
REGISTRY = HostRegistry(CodexHost(), ClaudeHost())


def get_host(kind):
    """The host that implements ``kind``; ``UnknownHostKind`` for anything else."""
    return REGISTRY.get(kind)


def known_kinds():
    return REGISTRY.kinds()


__all__ = [
    "SLOTS", "REGISTRY", "ClaudeHost", "CodexHost", "HostContractError", "HostEvent", "HostKind", "HostRegistry",
    "HostStream", "LaunchPlan", "McpGrant", "McpServer", "ModelBinding", "NativeFlagFence", "TurnResult",
    "TurnSpec", "UnknownHostKind", "WriteFence", "claude", "codex", "get_host", "known_kinds", "run_turn",
]
