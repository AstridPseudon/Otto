"""Small trusted authoring composition; EDT owns every editor lifecycle.

This is an owner-composed helper, not a public ingress or write grant. V05 owns
installed finite CLI/caller admission. Node creation and roster inclusion remain
separate operations with separate receipts; inclusion never recreates a node.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from herzchen.contracts import AuthenticatedActor, ResourceRef, ReferenceBinding, ReplayConflictError, canonical_json
from .authoring import DocumentAuthoringHandler, DocumentMaterialisation, DocumentFinishResult, SchemaValidationError
from .model import ContentDocument


@dataclass(frozen=True)
class VisionCreationResult:
    document_ref: ResourceRef
    revision_ref: ResourceRef | None
    finish: DocumentFinishResult | None
    creation_receipt: Any = None
    root_inclusion: str = "not_requested"


@dataclass(frozen=True)
class VisionInclusionResult:
    document_ref: ResourceRef
    root_ref: ResourceRef
    root_finish: DocumentFinishResult
    inclusion_pending: bool


class VisionAuthoring:
    def __init__(self, authoring: DocumentAuthoringHandler, actor: AuthenticatedActor):
        self.authoring, self.actor = authoring, actor

    def create(
        self,
        content: Mapping[str, Any],
        *,
        request_id: str,
        project_ref: ResourceRef | Mapping[str, Any] | None = None,
    ) -> VisionCreationResult:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("creation requires a nonempty request key")
        scope = None
        if project_ref is not None:
            scope = (project_ref if isinstance(project_ref, ResourceRef)
                     else ResourceRef.from_dict(project_ref))
            if (scope.authority != self.actor.authority or scope.kind != "work.project"
                    or scope.revision is not None):
                raise ValueError("project_ref must be an unpinned local work.project")
        # DAT has opaque stable IDs. Titles, locators and root state are not
        # identity inputs. EDT's open and finish receipts bind the exact bytes.
        ref = self.creation_ref(request_id)
        document = ContentDocument(
            ref, "vision", "shared" if scope is not None else "private", "write",
            self.actor.actor, authoring_scope=scope,
        )
        draft = {"document": document, "content": content}
        # Validate before reserving; existing canonical metadata/pin wins.
        parsed = self.authoring.validate(draft, target=document)
        draft = parsed.to_dict()
        # EDT checks the original open digest, including authenticated actor
        # and complete initial bytes, before replaying a released reservation.
        material = self.authoring.materialise(document, self.actor, request_id=request_id + ":open",
            initial_content=draft, base_revision="initial")
        # Replay the original creation receipt, even after later edits or
        # released custody. Never reopen a released creation session to guess
        # whether it created another document.
        prior = self.authoring.reader.get_receipt(request_id + ":finish:document")
        if prior is not None:
            stored = self.authoring.read(prior.result_ref, self.actor)["content"]
            accepted = stored.get("content")
            if (prior.target != ref
                    or canonical_json(accepted) != canonical_json(parsed.content)):
                raise ReplayConflictError("creation request key was reused with changed content")
            return VisionCreationResult(ref, prior.result_ref, None, prior)
        if material.open_result.handle is None:
            raise SchemaValidationError(("custody_required: creation could not acquire its EDT session",))
        result = self.authoring.finish(material, request_id=request_id + ":finish", draft=draft)
        receipt = self.authoring.reader.get_receipt(request_id + ":finish:document")
        committed = result.finish.status in {"applied", "finished", "replayed", "already_finished"}
        return VisionCreationResult(ref, receipt.result_ref if committed and receipt is not None else None, result, receipt)

    def creation_ref(self, request_id: str) -> ResourceRef:
        """Deterministic creation handle; not evidence that creation succeeded."""
        identity = hashlib.sha256(canonical_json({"authority": self.actor.authority,
            "actor": self.actor.actor, "request_id": request_id}).encode()).hexdigest()[:32]
        return ResourceRef(self.actor.authority, "dat.content.document", "vision-" + identity)

    def include(self, created: ResourceRef, root: DocumentMaterialisation, *, request_id: str) -> VisionInclusionResult:
        if created.authority != self.actor.authority or created.kind != "dat.content.document" or created.revision is not None:
            raise ValueError("root inclusion requires the same created current document identity")
        # The caller retains the actual root capability and base. A stale root
        # returns the ordinary conflict and draft; the created ID stays valid.
        # Read the opened base, not a competing newer root. CAS then protects
        # exactly this proposed membership edit and preserves its draft.
        base = ResourceRef(root.target.authority, root.target.kind, root.target.id, root.handle.base_revision)
        current = self.authoring.read(base, self.actor)["content"].get("content")
        if not isinstance(current, Mapping) or current.get("kind") != "product" or not isinstance(current.get("members"), list):
            raise SchemaValidationError(("schema_invalid: inclusion requires a collection root",))
        content = dict(current)
        binding = ReferenceBinding(created, "current").to_dict()
        content["members"] = list(content["members"])
        if binding not in content["members"]:
            content["members"].append(binding)
        result = self.authoring.finish(root, request_id=request_id, draft={"content": content})
        committed = (result.finish.status in {"finished", "applied", "replayed", "already_finished"}
                     and result.finish.failure_status in {None, "checked_in", "cleanup_pending"})
        return VisionInclusionResult(created, root.target, result, not committed)
