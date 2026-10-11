"""Install one finite Vision surface on existing owner ports and EDT custody.

Managed bytes and caller grants are supplied by trusted composition. This
module opens no Store, discovers no projects, and grants no provider authority.
"""
from typing import Any, Mapping

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.content.packets import ContextPacketService
from herzchen.content.packets import AccessDeniedError, UnresolvedReferenceError
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.content.vision import ManagedVisionDefinitions, VisionValidator
from herzchen.content.vision_authoring import VisionAuthoring
from herzchen.content.vision_command import VisionCommandSurface, MUTATING_OPERATIONS
from herzchen.content.vision_context import VisionContextService
from herzchen.content.vision_pack import load_vision_pack
from herzchen.content.vision_queries import VisionQueryService, VisionReorganizer, VisionAttachment
from herzchen.packs.authoring import ExecutionPin


class _VisionReads:
    """Compose the existing query and context ports without new authority."""

    def __init__(self, queries, *, actor, scopes=()):
        self.read = queries.read
        self.query = queries.query
        context = VisionContextService(queries, actor=actor, scopes=scopes)
        self.context = context.context
        self.history = context.history
        self.snapshot = context.snapshot


class OwnerVision:
    def __init__(self, *, owner: Any, editor: Any, managed_pack: Any,
                 expected_selection: Mapping[str, Any]):
        self.owner, self.editor = owner, editor
        self.pack = load_vision_pack(managed_pack=managed_pack)
        if dict(expected_selection) != self.pack.selection():
            raise PermissionError("Vision managed selection differs from the adopted exact pins")
        self.packets = ContextPacketService(owner.store)
        definitions = ManagedVisionDefinitions((managed_pack,), tuple(
            ExecutionPin("vision/" + resource.path, resource.kind,
                         managed_pack.source.source_revision, resource.source_digest)
            for resource in managed_pack.resources))
        self.validator = VisionValidator(definitions, target_reader=self._owner_target)
        if editor._buffers:
            raise RuntimeError("Vision composition requires the unused editor at owner startup")
        editor.authoring = DocumentAuthoringHandler(owner.store, authoring=editor.sessions,
                                                    vision_validator=self.validator)
        from .manager_application import ManagerApplication
        editor.operations = ManagerApplication.from_owner(owner, document_authoring=editor.authoring,
            idle_lifecycle=editor.lifecycle).document_operations
        self.authoring = VisionAuthoring(editor.authoring, owner.owner_actor)
        queries = VisionQueryService(self.packets, actor=owner.owner_actor)
        self.surface = VisionCommandSurface(authoring=self.authoring,
            queries=_VisionReads(queries, actor=owner.owner_actor), pack=self.pack,
            reorganizer=VisionReorganizer(editor.authoring, owner.owner_actor),
            attachment=VisionAttachment(owner.content, owner.owner_actor))
        editor.vision_operations = self.surface

    def _owner_target(self, ref, actor=None):
        try:
            return self.packets.resolve_reference(ref, actor=actor or self.owner.owner_actor)
        except (AccessDeniedError, UnresolvedReferenceError):
            return None

    def agent_read(self, request: Mapping[str, Any], *, actor: AuthenticatedActor,
                   project_ref: ResourceRef, grant: Any, membership_reader: Any):
        """Fresh authenticated project read; DAT visibility is never borrowed."""
        if not isinstance(actor, AuthenticatedActor) or actor.authority != self.owner.store.authority:
            raise PermissionError("Vision agent requires authenticated owner-local identity")
        if request.get("operation") in MUTATING_OPERATIONS:
            raise PermissionError("Vision agent read capability cannot mutate documents")
        arguments = dict(request.get("arguments", {}))
        if request.get("operation") != "help":
            supplied = ResourceRef.from_dict(arguments.get("project_ref", {}))
            if supplied != project_ref:
                raise PermissionError("Vision read requires the exact current authenticated project")
        queries = VisionQueryService(self.packets, actor=actor, scopes=(project_ref,),
            grant=grant, membership_reader=membership_reader)
        surface = VisionCommandSurface(authoring=object(),
            queries=_VisionReads(queries, actor=actor, scopes=(project_ref,)), pack=self.pack)
        return surface.dispatch(request)
