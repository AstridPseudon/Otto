"""Finite Vision command envelope over existing owner-composed ports."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from herzchen.contracts import ResourceRef

from .vision_pack import VisionResourcePack


VISION_OPERATIONS = (
    "help", "create", "read", "query", "reorganize", "context", "history", "attach", "snapshot",
)
MUTATING_OPERATIONS = frozenset({"create", "reorganize", "attach", "snapshot"})
_ALLOWED_ARGUMENTS = {
    "help": frozenset(),
    "create": frozenset({"content", "project_ref"}),
    "read": frozenset({"document_ref", "project_ref"}),
    "query": frozenset({"root_ref", "preset", "project_ref", "snapshot_ref", "limit", "after_key", "basis_digest", "arguments"}),
    "reorganize": frozenset({"document_ref", "changes"}),
    "context": frozenset({"root_ref", "focus_refs", "question", "repository_refs", "project_ref", "snapshot_ref", "implementation_context", "direction_context", "task_context"}),
    "history": frozenset({"document_ref", "before_revision", "limit", "project_ref"}),
    "attach": frozenset({"project_ref", "document_refs", "remove"}),
    "snapshot": frozenset({"scope", "label", "root_ref", "focus_refs", "document_ref", "input_refs", "project_ref", "allow_partial"}),
}


class VisionCommandError(ValueError):
    """A Vision request is outside the finite admitted command surface."""


def _wire(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if is_dataclass(value):
        return _wire(asdict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _wire(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    return value


class VisionCommandSurface:
    """Host-owned finite adapter; authentication remains in injected services."""

    def __init__(self, *, authoring: Any, queries: Any, pack: VisionResourcePack,
                 reorganizer: Any = None, attachment: Any = None) -> None:
        if authoring is None or queries is None or pack is None:
            raise TypeError("VisionCommandSurface requires authoring, query, and selected pack ports")
        self.authoring = authoring
        self.queries = queries
        self.pack = pack
        self.reorganizer = reorganizer
        self.attachment = attachment

    def dispatch(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(request, Mapping):
            raise VisionCommandError("Vision request must be an object")
        if request.get("command") != "vision":
            raise VisionCommandError("command must be 'vision'")
        if "actor" in request or "principal" in request or "credential" in request:
            raise VisionCommandError("actor override is forbidden; caller identity is host-bound")
        operation = request.get("operation")
        if operation not in VISION_OPERATIONS:
            raise VisionCommandError("unsupported Vision operation")
        arguments = request.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise VisionCommandError("arguments must be an object")
        unknown = set(arguments) - _ALLOWED_ARGUMENTS[operation]
        if unknown:
            raise VisionCommandError(f"unsupported arguments for {operation}: {sorted(unknown)}")
        request_key = request.get("request_key")
        if operation in MUTATING_OPERATIONS and (not isinstance(request_key, str) or not request_key.strip()):
            raise VisionCommandError(f"{operation} requires a nonempty top-level request_key")
        args = dict(arguments)
        if operation == "help":
            return self.help()
        if operation == "create":
            content = args.get("content")
            options = {"request_id": request_key}
            if args.get("project_ref") is not None:
                options["project_ref"] = args["project_ref"]
            result = self.authoring.create(content, **options)
            return {"schema": "vision.create.v1", "outcome": "created", **_wire(result), "resource_selection": self.pack.selection()}
        if operation == "read":
            return {**_wire(self.queries.read(args["document_ref"], project_ref=args.get("project_ref"))), "resource_selection": self.pack.selection()}
        if operation == "query":
            if "root_ref" not in args or "preset" not in args:
                raise VisionCommandError("query requires root_ref and preset")
            result = self.queries.query(
                args["root_ref"], args["preset"], project_ref=args.get("project_ref"),
                snapshot_ref=args.get("snapshot_ref"), limit=args.get("limit", 32),
                after_key=args.get("after_key"), basis_digest=args.get("basis_digest"),
                arguments=args.get("arguments"),
            )
            return {**_wire(result), "resource_selection": self.pack.selection()}
        if operation == "reorganize":
            if self.reorganizer is None:
                raise VisionCommandError("reorganization host port is unavailable")
            result = self.reorganizer.update(args["document_ref"], args["changes"], request_id=request_key)
            return {**_wire(result), "resource_selection": self.pack.selection()}
        if operation == "context":
            required = ("root_ref", "focus_refs", "question")
            if any(field not in args for field in required):
                raise VisionCommandError("context requires root_ref, focus_refs, and question")
            result = self.queries.context(**args)
            return {**_wire(result), "resource_selection": self.pack.selection()}
        if operation == "history":
            if "document_ref" not in args:
                raise VisionCommandError("history requires document_ref")
            result = self.queries.history(**args)
            return {**_wire(result), "resource_selection": self.pack.selection()}
        if operation == "attach":
            if self.attachment is None:
                raise VisionCommandError("attachment host port is unavailable")
            if "project_ref" not in args or "document_refs" not in args:
                raise VisionCommandError("attach requires project_ref and document_refs")
            result = self.attachment.apply(
                args["project_ref"], args["document_refs"], request_id=request_key,
                remove=bool(args.get("remove", False)),
            )
            return {**_wire(result), "resource_selection": self.pack.selection()}
        if operation == "snapshot":
            if "scope" not in args:
                raise VisionCommandError("snapshot requires scope")
            result = self.queries.snapshot(request_key=request_key, **args)
            return {**_wire(result), "resource_selection": self.pack.selection()}
        raise VisionCommandError("unsupported Vision operation")

    def help(self) -> Mapping[str, Any]:
        return {
            "schema": "vision.help.v1",
            "status": "ok",
            "operations": list(VISION_OPERATIONS),
            "read_only_operations": [name for name in VISION_OPERATIONS if name not in MUTATING_OPERATIONS],
            "request_shape": {"command": "vision", "operation": "...", "arguments": "object", "request_key": "required for mutations"},
            "resource_selection": self.pack.selection(),
            "compatibility": self.pack.compatibility(),
            "guidance_disablement": self.pack.disable_guidance(),
            "provider_called": False,
            "effects_started": False,
        }


__all__ = ["MUTATING_OPERATIONS", "VISION_OPERATIONS", "VisionCommandError", "VisionCommandSurface"]
