"""Agent harnesses behind one contract. Adding a harness is one ``HostKind`` implementation."""

from . import claude, codex
from .claude import ClaudeHost
from .codex import CodexHost
from .contract import (HostContractError, HostEvent, HostKind, HostRegistry, HostStream, LaunchPlan,
                       McpGrant, McpServer, ModelBinding, ModelPlan, NativeFlagFence, TurnResult, TurnSpec,
                       UnknownHostKind, WriteFence, recover_turn_scope, run_turn)

# The hosts this installation can drive. A kind that is not here is refused, never defaulted.
REGISTRY = HostRegistry(CodexHost(), ClaudeHost())


def get_host(kind):
    """The host that implements ``kind``; ``UnknownHostKind`` for anything else."""
    return REGISTRY.get(kind)


def known_kinds():
    return REGISTRY.kinds()


__all__ = [
    "REGISTRY", "ClaudeHost", "CodexHost", "HostContractError", "HostEvent", "HostKind", "HostRegistry",
    "HostStream", "LaunchPlan", "McpGrant", "McpServer", "ModelBinding", "ModelPlan", "NativeFlagFence", "TurnResult",
    "TurnSpec", "UnknownHostKind", "WriteFence", "claude", "codex", "get_host", "known_kinds",
    "recover_turn_scope", "run_turn",
]
