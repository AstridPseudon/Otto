"""Strict-v2, resource-only Vision pack admission.

The pack contains declarations and guidance only.  This module validates the
selected managed bytes and exposes their immutable pins to the existing host;
it does not interpret pack code, create storage, or grant caller authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from herzchen.contracts import ResourceRef, canonical_json
from herzchen.packs.authoring import (
    ExecutionPin,
    ManagedPack,
    ManagedSourceIdentity,
    read_managed_pack,
)

from .vision import (
    DEFINITION_CONTRACT,
    HOST_CONTRACT,
    RESOURCE_PATH,
    SCHEMA,
)
from .vision_context import MAX_CONTEXT_EDGES, MAX_CONTEXT_JSON_BYTES, MAX_RENDERED_BYTES
from .vision_queries import MAX_MEMBERS, MAX_RESPONSE_BYTES, PRESETS


VISION_PACK_ID = "vision"
VISION_PACK_VERSION = "1.0.0"
VISION_SELECTION_SCHEMA = "vision.resource-selection.v1"
VISION_COMPATIBILITY_SCHEMA = "vision.compatibility.v1"


class VisionPackError(ValueError):
    """The selected managed Vision resources are not admissible."""


EXPECTED_RESOURCES = {
    RESOURCE_PATH: "vision_schema",
    "vocabulary.md": "vision_vocabulary",
    "presets.json": "vision_presets",
    "templates/product-area.md": "vision_template",
    "templates/repository-subsystem.md": "vision_template",
    "templates/cross-cutting-concept.md": "vision_template",
    "templates/design-decision.md": "vision_template",
    "skill/SKILL.md": "skill",
    "examples/frame.md": "vision_example",
    "role-guidance.md": "vision_role_guidance",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_resource(managed: ManagedPack, path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(managed.resource(path).content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionPackError(f"Vision resource is not valid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise VisionPackError(f"Vision resource must be a JSON object: {path}")
    return value


@dataclass(frozen=True)
class VisionResourcePin:
    path: str
    kind: str
    digest: str
    version: str
    source_ref: ResourceRef

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "digest": self.digest,
            "version": self.version,
            "source_ref": self.source_ref.to_dict(),
        }


@dataclass(frozen=True)
class VisionSelection:
    pack: "VisionResourcePack"
    resources: tuple[VisionResourcePin, ...]

    def __post_init__(self) -> None:
        expected = {item.path: item for item in self.pack.resources}
        if len(self.resources) != len(expected) or {item.path for item in self.resources} != set(expected):
            raise VisionPackError("Vision selection contains incomplete resource pins")
        for item in self.resources:
            if item != expected.get(item.path):
                raise VisionPackError(f"Vision selection contains a stale resource pin: {item.path}")

    @property
    def digest(self) -> str:
        return _digest([item.to_dict() for item in self.resources])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VISION_SELECTION_SCHEMA,
            "pack_id": self.pack.pack_id,
            "pack_version": self.pack.version,
            "host_contract": self.pack.host_contract,
            "source": self.pack.source.to_dict(),
            "resources": [item.to_dict() for item in self.resources],
            "selection_digest": self.digest,
        }


@dataclass(frozen=True)
class VisionResourcePack:
    """An owner-selected immutable resource view for the Vision host."""

    pack_id: str
    version: str
    source: ManagedSourceIdentity
    resources: tuple[VisionResourcePin, ...]
    host_contract: str = HOST_CONTRACT

    def __post_init__(self) -> None:
        if self.pack_id != VISION_PACK_ID or self.version != VISION_PACK_VERSION:
            raise VisionPackError("unsupported Vision pack identity or version")
        if self.host_contract != HOST_CONTRACT:
            raise VisionPackError("unsupported Vision host contract")
        if self.source.pack_id != self.pack_id:
            raise VisionPackError("Vision source identity belongs to another pack")
        paths = [item.path for item in self.resources]
        if set(paths) != set(EXPECTED_RESOURCES) or len(paths) != len(set(paths)):
            raise VisionPackError("Vision pack has incomplete or unknown resources")
        for item in self.resources:
            if EXPECTED_RESOURCES[item.path] != item.kind:
                raise VisionPackError(f"Vision resource kind mismatch: {item.path}")
            if item.source_ref != ResourceRef("managed-source", "managed_pack", self.pack_id, self.source.source_revision):
                raise VisionPackError(f"Vision resource source pin is foreign or stale: {item.path}")

    @classmethod
    def from_managed_pack(cls, managed: ManagedPack) -> "VisionResourcePack":
        if not isinstance(managed, ManagedPack):
            raise VisionPackError("Vision admission requires a ManagedPack from public discovery")
        if managed.pack_id != VISION_PACK_ID or managed.version != VISION_PACK_VERSION:
            raise VisionPackError("unsupported managed Vision pack")
        resources = {item.path: item for item in managed.resources}
        if set(resources) != set(EXPECTED_RESOURCES):
            raise VisionPackError("managed Vision resources are incomplete or contain unknown paths")
        for path, kind in EXPECTED_RESOURCES.items():
            if resources[path].kind != kind:
                raise VisionPackError(f"managed Vision resource kind mismatch: {path}")
        schema = _json_resource(managed, RESOURCE_PATH)
        if schema != DEFINITION_CONTRACT:
            raise VisionPackError("managed Vision schema pin has unsupported semantics")
        presets = _json_resource(managed, "presets.json")
        if presets.get("schema") != "vision.presets.v1" or presets.get("host_contract") != HOST_CONTRACT or presets.get("finite") is not True:
            raise VisionPackError("managed Vision presets are not finite or use the wrong host contract")
        names = tuple(item.get("name") for item in presets.get("presets", ()) if isinstance(item, Mapping))
        if names != PRESETS:
            raise VisionPackError("managed Vision preset order or vocabulary differs from the host")
        bounds = presets.get("bounds")
        if not isinstance(bounds, Mapping) or {
            "max_members": bounds.get("max_members"),
            "max_nodes": bounds.get("max_nodes"),
            "max_displayed_edges": bounds.get("max_displayed_edges"),
            "max_rendered_intent_bytes": bounds.get("max_rendered_intent_bytes"),
            "max_json_bytes": bounds.get("max_json_bytes"),
            "max_query_response_bytes": bounds.get("max_query_response_bytes"),
        } != {
            "max_members": MAX_MEMBERS,
            "max_nodes": MAX_MEMBERS + 1,
            "max_displayed_edges": MAX_CONTEXT_EDGES,
            "max_rendered_intent_bytes": MAX_RENDERED_BYTES,
            "max_json_bytes": MAX_CONTEXT_JSON_BYTES,
            "max_query_response_bytes": MAX_RESPONSE_BYTES,
        }:
            raise VisionPackError("managed Vision presets weaken or change a host bound")
        vocabulary = managed.resource("vocabulary.md").content.decode("utf-8")
        for term in ("navigation_parent", "members", "applies_to", "refines", "in_tension_with", "advisory"):
            if term not in vocabulary:
                raise VisionPackError(f"Vision vocabulary omits required term: {term}")
        for path in EXPECTED_RESOURCES:
            resource = resources[path]
            if not resource.content:
                raise VisionPackError(f"Vision resource is empty: {path}")
        pins = tuple(
            VisionResourcePin(item.path, item.kind, item.source_digest, managed.version, item.source_ref)
            for item in sorted(managed.resources, key=lambda item: item.path)
        )
        return cls(managed.pack_id, managed.version, managed.source, pins)

    @property
    def source_revision(self) -> str:
        return self.source.source_revision

    @property
    def digest(self) -> str:
        return _digest(self._base_dict())

    @property
    def definition_pin(self) -> ExecutionPin:
        item = next(pin for pin in self.resources if pin.path == RESOURCE_PATH)
        return ExecutionPin(f"{self.pack_id}/{item.path}", item.kind, self.source_revision, item.digest)

    def _base_dict(self) -> dict[str, Any]:
        return {
            "schema": VISION_SELECTION_SCHEMA,
            "pack_id": self.pack_id,
            "pack_version": self.version,
            "host_contract": self.host_contract,
            "source": self.source.to_dict(),
            "resources": [item.to_dict() for item in self.resources],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._base_dict(), "selection_digest": self.digest}

    def resource_bytes(self, path: str) -> bytes:
        pin = next((item for item in self.resources if item.path == path), None)
        if pin is None:
            raise VisionPackError(f"resource is not selected: {path}")
        resource_path = Path(self.source.pack_root) / path
        if resource_path.is_symlink() or not resource_path.is_file():
            raise VisionPackError(f"selected Vision resource is unavailable: {path}")
        content = resource_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != pin.digest:
            raise VisionPackError(f"selected Vision resource digest changed: {path}")
        return content

    def selection(self, *, guidance_enabled: bool = True) -> Mapping[str, Any]:
        return {
            "schema": VISION_SELECTION_SCHEMA,
            "pack_id": self.pack_id,
            "pack_version": self.version,
            "host_contract": self.host_contract,
            "source_revision": self.source_revision,
            "selection_digest": self.digest,
            "definition_pin": self.definition_pin.to_dict(),
            "resources": [item.to_dict() for item in self.resources],
            "guidance_enabled": guidance_enabled,
        }

    def select(self, adopted_pins: Optional[Sequence[Mapping[str, Any]]] = None) -> VisionSelection:
        pins = tuple(self.resources)
        if adopted_pins is not None:
            expected = {item.path: item for item in pins}
            supplied = []
            for raw in adopted_pins:
                if not isinstance(raw, Mapping) or raw.get("path") not in expected:
                    raise VisionPackError("adopted Vision resource pin is undeclared or malformed")
                item = expected[raw["path"]]
                if any(raw.get(field) != getattr(item, field) for field in ("kind", "digest", "version")):
                    raise VisionPackError(f"adopted Vision resource pin is stale: {item.path}")
                source = raw.get("source_ref")
                try:
                    source_ref = ResourceRef.from_dict(source) if isinstance(source, Mapping) else None
                except (KeyError, TypeError, ValueError) as exc:
                    raise VisionPackError(f"adopted Vision resource source pin is malformed: {item.path}") from exc
                if source_ref != item.source_ref:
                    raise VisionPackError(f"adopted Vision resource source pin is stale: {item.path}")
                supplied.append(item)
            pins = tuple(sorted(supplied, key=lambda item: item.path))
        return VisionSelection(self, pins)

    def compatibility(self) -> Mapping[str, Any]:
        return {
            "schema": VISION_COMPATIBILITY_SCHEMA,
            "current": self.selection(),
            "historical": "retained definitions remain readable only when their exact source/resource pins are available",
            "upgrade": "explicit adoption of a new pack revision; existing content and checkpoints are not rewritten",
            "unavailable_history": "return definition_unavailable rather than silently substituting the current definition",
            "guidance_disablement": {"new_guided_admission": False, "content_preserved": True, "history_preserved": True},
        }

    def disable_guidance(self) -> Mapping[str, Any]:
        return {
            "schema": "vision.guidance.v1",
            "outcome": "disabled",
            "guidance_enabled": False,
            "new_guided_admission": False,
            "content_preserved": True,
            "history_preserved": True,
            "checkpoint_citations_preserved": True,
        }


def load_vision_pack(
    project_root: str | Path | None = None,
    *,
    managed_pack: ManagedPack | None = None,
    discoverer: Any = None,
    loader: Any = None,
) -> VisionResourcePack:
    """Use the existing public managed discovery/loader boundary."""
    try:
        if managed_pack is None:
            managed = read_managed_pack(
                VISION_PACK_ID,
                project_root=project_root or Path(__file__).resolve().parents[3],
                discoverer=discoverer,
                loader=loader,
            )
        else:
            managed = managed_pack
        return VisionResourcePack.from_managed_pack(managed)
    except VisionPackError:
        raise
    except Exception as exc:
        raise VisionPackError(f"Vision managed pack is unavailable: {exc}") from exc


__all__ = [
    "EXPECTED_RESOURCES", "VISION_COMPATIBILITY_SCHEMA", "VISION_PACK_ID",
    "VISION_PACK_VERSION", "VISION_SELECTION_SCHEMA", "VisionPackError",
    "VisionResourcePack", "VisionResourcePin", "VisionSelection", "load_vision_pack",
]
