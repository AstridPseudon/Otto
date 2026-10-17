"""Admission: the pin that says which task revision a reviewer approved.

An admission is a stamp in the ``work.admission`` metadata namespace of a task
record. It names the exact revision id that was admitted and the digest of the
reviewed content at that revision. The stamp rides on the existing ``work.revise``
port, so no new operation, resource kind or domain descriptor is needed.

The legacy stamp digest covers a narrow, stable subset of task fields. New stamps
also carry a full reviewer-visible digest so edits to any authored task field can
invalidate admission. Lifecycle, readiness, and the stamp itself are excluded.
Stamps without the full digest are not sufficient to admit reviewer-visible content.
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
BASIS_POLICY = "policy"

_CONTENT_KEYS = ("kind", "project_ref", "title", "name", "outcome", "fields", "parent", "dependencies")
_REVIEWED_CONTENT_KEYS = (
    "kind", "project_ref", "title", "name", "body", "instructions",
    "outcome", "acceptance", "fields", "parent", "dependencies", "custom",
    "metadata", "metadata_namespaces", "order", "alias", "aliases", "documents",
    "document_links",
)


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
    """Compare the complete reviewer-visible authored task content."""
    return reviewed_content_diff(reviewed, current)


def reviewed_content_diff(reviewed: Mapping[str, Any], current: Mapping[str, Any]) -> Dict[str, Any]:
    """Return field-level changes to authored task content since a review.

    The historic stamp digest intentionally remains narrower for compatibility.
    Admission comparisons include all reviewer-visible authored fields, while
    excluding lifecycle/readiness state and the admission stamp itself.
    """
    left, right = reviewed_content(reviewed), reviewed_content(current)
    return {
        key: {"reviewed": left[key], "current": right[key]}
        for key in _REVIEWED_CONTENT_KEYS if left[key] != right[key]
    }


def reviewed_content(payload: Mapping[str, Any]) -> Dict[str, Any]:
    result = {key: payload.get(key) for key in _REVIEWED_CONTENT_KEYS}
    namespaces = result.get("metadata_namespaces")
    if isinstance(namespaces, Mapping):
        result["metadata_namespaces"] = {
            key: value for key, value in namespaces.items() if key != NAMESPACE
        }
    elif "metadata_namespaces" not in payload:
        result["metadata_namespaces"] = {}
    return result


def reviewed_content_digest(payload: Mapping[str, Any]) -> str:
    text = json.dumps(reviewed_content(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def task_content_matches(writer: Any, pinned_ref: Any, current_payload: Mapping[str, Any],
                         *, current_ref: Any = None) -> bool:
    """Whether a retained task pin still describes the current authored content.

    Revision ids change for metadata-only writes such as admission. Resolve the
    exact retained revision and compare both the admission digest and the wider
    reviewer-visible digest, which includes authored metadata namespaces while
    excluding the admission stamp itself. The digests are always computed from
    the payloads; a caller-supplied stamp cannot make changed content match.
    """
    from herzchen.contracts import ResourceRef

    if not isinstance(pinned_ref, ResourceRef) or pinned_ref.kind != "work.task" or not pinned_ref.revision:
        return False
    if not isinstance(current_payload, Mapping):
        return False
    if (current_payload.get("kind") not in {None, "task", pinned_ref.kind}
            or current_payload.get("id", pinned_ref.id) != pinned_ref.id):
        return False
    if current_ref is not None:
        if (not isinstance(current_ref, ResourceRef)
                or (current_ref.authority, current_ref.kind, current_ref.id) !=
                   (pinned_ref.authority, pinned_ref.kind, pinned_ref.id)):
            return False
        # An exact current revision already is the pinned content. Historical
        # reads are needed only when a later revision must be compared.
        if current_ref == pinned_ref:
            return True
    if (current_payload.get("kind") not in {"task", pinned_ref.kind}
            or current_payload.get("id") != pinned_ref.id):
        return False
    writer_authority = getattr(writer, "authority", None)
    if writer_authority is not None and writer_authority != pinned_ref.authority:
        return False
    retained = writer.get_revision(pinned_ref)
    if retained is None or retained.ref != pinned_ref or retained.ref.kind != "work.task":
        return False
    return (content_digest(retained.payload) == content_digest(current_payload)
            and reviewed_content_digest(retained.payload) == reviewed_content_digest(current_payload))


def stamp_of(payload: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    namespaces = payload.get("metadata_namespaces")
    stamp = namespaces.get(NAMESPACE) if isinstance(namespaces, Mapping) else None
    return stamp if isinstance(stamp, Mapping) and stamp.get("revision") and stamp.get("digest") else None


def admitted_revision(payload: Mapping[str, Any]) -> Optional[str]:
    """The admitted revision when its stored content digests still match."""

    stamp = stamp_of(payload)
    if stamp is None or stamp["digest"] != content_digest(payload):
        return None
    if stamp.get("reviewed_digest") != reviewed_content_digest(payload):
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
    return {"revision": revision, "digest": content_digest(payload),
            "reviewed_digest": reviewed_content_digest(payload), "basis": BASIS_AUTHORING,
            "admitted_by": {"authority": authority, "actor": name}}


def review_stamp(revision: str, payload: Mapping[str, Any], actor: Any, review_ref: Any, disposition: str) -> Dict[str, Any]:
    authority, name = actor_pair(actor) or (None, None)
    return {"revision": revision, "digest": content_digest(payload),
            "reviewed_digest": reviewed_content_digest(payload), "basis": BASIS_REVIEW,
            "review_ref": review_ref.to_dict() if hasattr(review_ref, "to_dict") else review_ref,
            "disposition": disposition, "admitted_by": {"authority": authority, "actor": name}}


def policy_stamp(revision: str, payload: Mapping[str, Any], *, authority: str,
                 base_revision: str, decision_ref: Any) -> Dict[str, Any]:
    """Stamp a new task admitted by the project's current task-addition policy."""
    return {
        "revision": revision,
        "digest": content_digest(payload),
        "reviewed_digest": reviewed_content_digest(payload),
        "basis": BASIS_POLICY,
        "policy_evidence": {
            "authority": authority,
            "base_revision": base_revision,
            "decision_ref": decision_ref.to_dict() if hasattr(decision_ref, "to_dict") else decision_ref,
        },
    }
