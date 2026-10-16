"""Admission: the pin that says which task revision a reviewer approved.

An admission is a stamp in the ``work.admission`` metadata namespace of a task
record. It names the exact revision id that was admitted and the digest of the
reviewed content at that revision. The stamp rides on the existing ``work.revise``
port, so no new operation, resource kind or domain descriptor is needed.

Content is what a reviewer reads: the title, name, outcome, fields, parent and
dependencies. Lifecycle, readiness, aliases and the stamp itself are not content,
so writing the stamp, or moving a task through its lifecycle, leaves it admitted.
Any other edit changes the digest and the stamp no longer matches: the record is
unadmitted until a reviewer admits the new revision, or the project's user makes
the edit, which admits it by being made.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from .model import WorkValidationError

NAMESPACE = "work.admission"
APPROVED = frozenset({"approved", "accept", "accepted", "pass", "passed"})
BASIS_REVIEW = "review"
BASIS_AUTHORING = "authoring"

_CONTENT_KEYS = ("kind", "project_ref", "title", "name", "outcome", "fields", "parent", "dependencies")


class TaskNotAdmittedError(WorkValidationError):
    """The task revision a caller would use is not the one a reviewer admitted."""


class AdmissionDiffError(WorkValidationError):
    """The reviewed revision and the current sheet differ; ``diff`` names each field."""

    def __init__(self, message: str, diff: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.diff = dict(diff)


def content(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: payload.get(key) for key in _CONTENT_KEYS}


def content_digest(payload: Mapping[str, Any]) -> str:
    text = json.dumps(content(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_diff(reviewed: Mapping[str, Any], current: Mapping[str, Any]) -> Dict[str, Any]:
    left, right = content(reviewed), content(current)
    return {key: {"reviewed": left[key], "current": right[key]} for key in _CONTENT_KEYS if left[key] != right[key]}


def stamp_of(payload: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    namespaces = payload.get("metadata_namespaces")
    stamp = namespaces.get(NAMESPACE) if isinstance(namespaces, Mapping) else None
    return stamp if isinstance(stamp, Mapping) and stamp.get("revision") and stamp.get("digest") else None


def admitted_revision(payload: Mapping[str, Any]) -> Optional[str]:
    """The admitted revision id when the current content is the admitted content, else None."""

    stamp = stamp_of(payload)
    if stamp is None or stamp["digest"] != content_digest(payload):
        return None
    return str(stamp["revision"])


def actor_pair(actor: Any) -> Optional[tuple]:
    if actor is None:
        return None
    if hasattr(actor, "to_dict"):
        actor = actor.to_dict()
    if isinstance(actor, Mapping):
        return (actor.get("authority"), actor.get("actor"))
    return (None, str(actor))


def is_user(project_payload: Optional[Mapping[str, Any]], actor: Any) -> bool:
    """The project's user is the actor that created the project; no one else writes by being the user."""

    if not isinstance(project_payload, Mapping) or actor is None:
        return False
    provenance = project_payload.get("provenance")
    creator = provenance.get("creator") if isinstance(provenance, Mapping) else None
    left, right = actor_pair(creator), actor_pair(actor)
    if left is None or right is None:
        return False
    if left[0] is None or right[0] is None:
        return left[1] == right[1]
    return left == right


def authoring_stamp(revision: str, payload: Mapping[str, Any], actor: Any) -> Dict[str, Any]:
    authority, name = actor_pair(actor) or (None, None)
    return {"revision": revision, "digest": content_digest(payload), "basis": BASIS_AUTHORING,
            "admitted_by": {"authority": authority, "actor": name}}


def review_stamp(revision: str, payload: Mapping[str, Any], actor: Any, review_ref: Any, disposition: str) -> Dict[str, Any]:
    authority, name = actor_pair(actor) or (None, None)
    return {"revision": revision, "digest": content_digest(payload), "basis": BASIS_REVIEW,
            "review_ref": review_ref.to_dict() if hasattr(review_ref, "to_dict") else review_ref,
            "disposition": disposition, "admitted_by": {"authority": authority, "actor": name}}
