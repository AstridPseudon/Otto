"""``otto admit``: pin the exact task revision a reviewer approved.

The mechanism is Herzchen's (``WorkGraph.admit``). This is only the owner's call into it, shared by
the ``admit`` verb and by reviewed activation. The user's own edits are admitted by being made, so
only an agent-written revision needs this.
"""

from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import AdmissionDiffError, TaskNotAdmittedError
from herzchen.domains.work.model import WorkError

SCHEMA = "otto.admit.v1"


def admit_revision(owner: Any, *, task_ref: Any, revision: str, review_ref: Any, request_key: str,
                   disposition: str = "approved") -> Mapping[str, Any]:
    """Admit ``revision`` of one task as the owner; raises Herzchen's refusals unchanged."""
    task = task_ref if isinstance(task_ref, ResourceRef) else ResourceRef.from_dict(task_ref)
    review = review_ref if isinstance(review_ref, ResourceRef) else ResourceRef.from_dict(review_ref)
    return owner.graph.admit(task, revision=revision, review_ref=review, disposition=disposition,
                             logical_request_key=request_key, actor=owner.owner_actor)


def admit_task(session: Any, *, task_ref: Any, revision: str, review_ref: Any, request_key: str,
               disposition: str = "approved") -> dict[str, Any]:
    """The verb's answer: the admission, or a refusal that says why (a changed sheet carries its diff)."""
    try:
        result = admit_revision(session.owner, task_ref=task_ref, revision=revision, review_ref=review_ref,
                                request_key=request_key, disposition=disposition)
    except AdmissionDiffError as exc:
        return {"outcome": "rejected", "schema": SCHEMA, "error": {"code": "sheet_changed", "message": str(exc), "diff": exc.diff}}
    except TaskNotAdmittedError as exc:
        return {"outcome": "rejected", "schema": SCHEMA, "error": {"code": "not_admitted", "message": str(exc)}}
    except WorkError as exc:
        return {"outcome": "error", "schema": SCHEMA, "error": {"code": "invalid_request", "message": str(exc)}}
    return {"outcome": result["outcome"], "schema": SCHEMA, "task_ref": result["task_ref"].to_dict(),
            "admitted_revision": result["admitted_revision"], "dispatch": False}
