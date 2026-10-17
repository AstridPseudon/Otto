"""Owner service admission of an exact reviewed task revision.

Herzchen's ``WorkGraph.admit`` enforces the project-user invariant. The owner
supplies its authenticated operator actor only after its local presence proof.
"""

from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import AdmissionDiffError, TaskNotAdmittedError
from herzchen.domains.work.model import WorkError

SCHEMA = "otto.admit.v1"


def admit_revision(owner: Any, *, task_ref: Any, revision: str, review_ref: Any, request_key: str, actor: Any,
                   disposition: str = "approved") -> Mapping[str, Any]:
    """Admit one revision as the explicitly supplied, owner-authenticated actor."""
    task = task_ref if isinstance(task_ref, ResourceRef) else ResourceRef.from_dict(task_ref)
    review = review_ref if isinstance(review_ref, ResourceRef) else ResourceRef.from_dict(review_ref)
    return owner.graph.admit(task, revision=revision, review_ref=review, disposition=disposition,
                             logical_request_key=request_key, actor=actor)


def admit_task(session: Any, *, task_ref: Any, revision: str, review_ref: Any, request_key: str, actor: Any,
               disposition: str = "approved") -> dict[str, Any]:
    """The verb's answer: the admission, or a refusal that says why (a changed sheet carries its diff)."""
    try:
        result = admit_revision(session.owner, task_ref=task_ref, revision=revision, review_ref=review_ref,
                                request_key=request_key, disposition=disposition, actor=actor)
    except AdmissionDiffError as exc:
        return {"outcome": "rejected", "schema": SCHEMA, "error": {"code": "sheet_changed", "message": str(exc), "diff": exc.diff}}
    except TaskNotAdmittedError as exc:
        return {"outcome": "rejected", "schema": SCHEMA, "error": {"code": "not_admitted", "message": str(exc)}}
    except WorkError as exc:
        return {"outcome": "error", "schema": SCHEMA, "error": {"code": "invalid_request", "message": str(exc)}}
    return {"outcome": result["outcome"], "schema": SCHEMA, "task_ref": result["task_ref"].to_dict(),
            "admitted_revision": result["admitted_revision"], "dispatch": False}
