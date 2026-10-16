"""Per-assignment tokens. A token resolves to exactly one grant (assignment, role); the book keeps only digests."""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass

__all__ = ["TokenError", "Grant", "TokenBook"]

_UNKNOWN = "unknown token"


class TokenError(Exception):
    """A token or grant was refused."""


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Grant:
    """What a token acts for. Frozen: nothing a caller holds can change it after issue."""

    assignment: str
    role: str

    def __post_init__(self) -> None:
        for field, value in (("assignment", self.assignment), ("role", self.role)):
            if not isinstance(value, str) or not value:
                raise TokenError(f"{field} must be a non-empty string")


class TokenBook:
    """Issues and resolves tokens. Thread-safe. Stores only sha256 digests, never the raw token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._grant_by_digest: dict[str, Grant] = {}
        self._digest_by_assignment: dict[str, str] = {}

    def issue(self, assignment: str, role: str) -> str:
        """Return a fresh token for the assignment. Any earlier live token for it is revoked first."""

        grant = Grant(assignment, role)
        token = secrets.token_urlsafe(32)
        digest = _digest(token)
        with self._lock:
            self._revoke_locked(grant.assignment)
            self._grant_by_digest[digest] = grant
            self._digest_by_assignment[grant.assignment] = digest
        return token

    def resolve(self, token: object) -> Grant:
        """Return the grant for a live token. Every refusal raises the same generic TokenError."""

        if not isinstance(token, str) or not token:
            raise TokenError(_UNKNOWN)
        digest = _digest(token)
        with self._lock:
            grant = self._grant_by_digest.get(digest)
        if grant is None:
            raise TokenError(_UNKNOWN)
        return grant

    def revoke(self, assignment: str) -> None:
        """Revoke the live token for the assignment, if any."""

        with self._lock:
            self._revoke_locked(assignment)

    def live(self) -> frozenset:
        """The assignment ids that currently hold a live token."""

        with self._lock:
            return frozenset(self._digest_by_assignment)

    def _revoke_locked(self, assignment: str) -> None:
        digest = self._digest_by_assignment.pop(assignment, None)
        if digest is not None:
            self._grant_by_digest.pop(digest, None)
