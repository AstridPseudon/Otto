"""Fleet runner: one admission queue for heavy commands, each run under custody, each result in a sealed store."""
from __future__ import annotations

from .admission import Entry, Holder, pick
from .client import RunnerClient, RunnerUnavailable
from .commit import git_commit_identity
from .runner import EXIT_UNKNOWN, Runner
from .server import RunnerServer
from .session_resume import AskingSessionMismatch, require_asking_session
from .store import ResultStore, StoreError

__all__ = [
    "EXIT_UNKNOWN",
    "Entry",
    "Holder",
    "AskingSessionMismatch",
    "ResultStore",
    "Runner",
    "RunnerClient",
    "RunnerServer",
    "RunnerUnavailable",
    "StoreError",
    "git_commit_identity",
    "pick",
    "require_asking_session",
]
