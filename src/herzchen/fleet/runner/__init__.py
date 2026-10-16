"""Fleet runner: one admission queue for heavy commands, each run under custody, each result in a sealed store."""
from __future__ import annotations

from .admission import Entry, Holder, pick
from .client import RunnerClient, RunnerUnavailable
from .commit import git_commit_identity
from .runner import EXIT_UNKNOWN, Runner
from .server import RunnerServer
from .store import ResultStore, StoreError

__all__ = [
    "EXIT_UNKNOWN",
    "Entry",
    "Holder",
    "ResultStore",
    "Runner",
    "RunnerClient",
    "RunnerServer",
    "RunnerUnavailable",
    "StoreError",
    "git_commit_identity",
    "pick",
]
