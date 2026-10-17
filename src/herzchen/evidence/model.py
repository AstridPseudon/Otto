"""Shared managed-evidence values and the resource-only Evidence policy pack.

Evidence is a normal DAT content document whose revision content is a small
representation manifest.  Large bytes are deliberately outside the FND
receipt/event payload and are owned by the capture command through a managed
local file.  This module contains validation only; persistence stays in the
command adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from herzchen.contracts import ResourceRef, canonical_json
from herzchen.extensions.model import DefinitionCatalog, DocumentRoleDefinition, validate_json_schema
from herzchen.packs.authoring import ManagedPack, ManagedSourceIdentity, read_managed_pack


EVIDENCE_SCHEMA_REVISION = "dat.evidence.v1"
EVIDENCE_DOMAIN_ID = "herzchen.evidence"
EVIDENCE_OWNER = "dat"
EVIDENCE_DOCUMENT_ROLE = "evidence.managed"
EVIDENCE_PACK_ID = "evidence"
EVIDENCE_PACK_VERSION = "1.1.0"
EVIDENCE_HOST_CONTRACT = "herzchen.evidence.host.v1"
EVIDENCE_MANIFEST_KIND = "dat.evidence.manifest"
EVIDENCE_MANAGED_KIND = "evidence.submission"
EVIDENCE_STREAM_PREFIX = "evidence:"
EVIDENCE_ALIAS_NAMESPACE = "project.evidence"
EVIDENCE_PROJECTION_DIR = "evidence"
EVIDENCE_CHECKOUT_SCHEMA = "dat.evidence.checkout.v1"
EVIDENCE_LIFECYCLE_KIND = "dat.evidence.lifecycle"
EVIDENCE_TOMBSTONE_KIND = "dat.evidence.tombstone"
EVIDENCE_RECLAIM_PREVIEW_OPERATION = "dat.evidence.reclaim.preview"
EVIDENCE_RECLAIM_APPLY_OPERATION = "dat.evidence.reclaim.apply"
EVIDENCE_RECLAIM_PREVIEW_EVENT = "dat.evidence.reclaim.previewed"
EVIDENCE_RECLAIM_APPLY_EVENT = "dat.evidence.reclaim.applied"
EVIDENCE_TOMBSTONE_EVENT = "dat.evidence.payload.tombstoned"


class EvidenceError(ValueError):
    """Base error for managed-evidence validation and resolution."""


class EvidenceBindingError(EvidenceError):
    """Original project/task/attempt bindings are absent or inconsistent."""


class EvidencePackError(EvidenceError):
    """The selected Evidence resources are not an admissible strict-v2 pack."""


class EvidenceAccessDeniedError(EvidenceError):
    """The current document authorization does not permit a read."""


class EvidenceUnavailableError(EvidenceError):
    """A managed payload is missing, corrupt, or deliberately purged."""


class ChangedInputError(EvidenceError):
    """A replay request no longer names the originally captured source."""


class PublicationInterrupted(EvidenceError):
    """A deterministic publication boundary was interrupted."""


class EvidencePathCollisionError(EvidenceError):
    """A checkout projection or alias destination is already owned locally."""


class EvidenceCheckinError(EvidenceError):
    """An evidence projection check-in cannot be safely applied."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise EvidenceError(f"{field} must be non-blank text")
    return value


def _digest(value: Any, field: str = "digest") -> str:
    value = _text(value, field).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise EvidenceError(f"{field} must be a SHA-256 digest")
    return value


def _ref(value: Any, field: str) -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceBindingError(f"{field} is not a ResourceRef") from exc
    raise EvidenceBindingError(f"{field} is not a ResourceRef")


def _safe(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


EVIDENCE_MANIFEST_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "record_type": {"const": EVIDENCE_MANIFEST_KIND},
        "representation_version": {"const": "managed-bytes.v1"},
        "byte_digest": {"type": "string", "minLength": 64, "maxLength": 64},
        "byte_length": {"type": "integer", "minimum": 0},
        "format": {"type": "string", "minLength": 1},
        "storage": {"type": "object", "required": ("kind", "location"), "additionalProperties": True},
        "availability": {"type": "string", "enum": ("staged", "admitted", "verified", "missing", "corrupt", "purged")},
        "origin": {"type": "object", "required": ("project_ref",), "additionalProperties": True},
        "attribution": {"type": "object", "required": ("original_creator", "submitter", "maintainer"), "additionalProperties": True},
        "capture": {"type": "object", "required": ("request_key", "actor", "captured_digest", "captured_length"), "additionalProperties": True},
        "provenance": {"type": "object", "additionalProperties": True},
        "resource_selection": {"type": "object", "required": ("pack_id", "pack_version", "host_contract", "resources"), "additionalProperties": True},
    },
    "required": (
        "record_type", "representation_version", "byte_digest", "byte_length", "format",
        "storage", "availability", "origin", "attribution", "capture", "resource_selection",
    ),
    "additionalProperties": True,
}


EVIDENCE_ROLE = DocumentRoleDefinition(
    EVIDENCE_DOCUMENT_ROLE,
    "dat.content.document",
    "1",
    "Evidence content with an immutable managed byte representation and authenticated provenance.",
    EVIDENCE_MANIFEST_SCHEMA,
    {"doc_role": "evidence", "representation": "managed-bytes", "legacy_inline": "readable"},
)


def evidence_catalog(base: DefinitionCatalog | None = None) -> DefinitionCatalog:
    """Return the built-in catalog plus exactly one admitted Evidence role."""
    base = base or __import__("herzchen.extensions.model", fromlist=["DEFAULT_CATALOG"]).DEFAULT_CATALOG
    if any(role.role_id == EVIDENCE_DOCUMENT_ROLE for role in base.roles):
        return base
    return DefinitionCatalog(base.definitions, tuple(base.roles) + (EVIDENCE_ROLE,))


@dataclass(frozen=True)
class EvidenceResourcePin:
    path: str
    kind: str
    digest: str
    version: str = EVIDENCE_PACK_VERSION
    source_ref: Optional[ResourceRef] = None

    def __post_init__(self) -> None:
        _text(self.path, "resource path")
        _text(self.kind, "resource kind")
        _digest(self.digest, "resource digest")
        _text(self.version, "resource version")

    def to_dict(self) -> dict[str, str]:
        result: dict[str, Any] = {"path": self.path, "kind": self.kind, "digest": self.digest, "version": self.version}
        if self.source_ref is not None:
            result["source_ref"] = self.source_ref.to_dict()
        return result


@dataclass(frozen=True)
class EvidenceResourcePack:
    """A strict-v2, data-only pack selected by the trusted command path."""

    pack_id: str
    version: str
    source_root: str
    manifest_digest: str
    resources: Tuple[EvidenceResourcePin, ...]
    host_contract: str = EVIDENCE_HOST_CONTRACT
    catalog: DefinitionCatalog = evidence_catalog()
    source: Optional[ManagedSourceIdentity] = None

    def __post_init__(self) -> None:
        if self.pack_id != EVIDENCE_PACK_ID:
            raise EvidencePackError("selected pack is not the Evidence pack")
        if self.version not in {"1.0.0", EVIDENCE_PACK_VERSION}:
            raise EvidencePackError("unsupported Evidence pack version")
        _digest(self.manifest_digest, "pack manifest digest")
        _text(self.source_root, "pack source root")
        paths = [item.path for item in self.resources]
        if len(paths) != len(set(paths)):
            raise EvidencePackError("Evidence pack contains colliding resource paths")
        if self.catalog.role(EVIDENCE_DOCUMENT_ROLE) != EVIDENCE_ROLE:
            raise EvidencePackError("Evidence role was not admitted through DefinitionCatalog")
        if self.host_contract != EVIDENCE_HOST_CONTRACT:
            raise EvidencePackError("unsupported Evidence host contract")
        if self.source is None:
            raise EvidencePackError("Evidence pack admission requires a managed source identity")
        if self.source.pack_id != self.pack_id:
            raise EvidencePackError("managed source identity belongs to a different pack")
        if self.source.source_manifest_sha256 != self.manifest_digest:
            raise EvidencePackError("managed source manifest digest does not match the selected pack")
        for item in self.resources:
            if item.source_ref is None:
                raise EvidencePackError("managed resource is missing its source identity")
            if item.source_ref.authority != "managed-source" or item.source_ref.id != self.pack_id:
                raise EvidencePackError("managed resource source identity is foreign")
            if item.source_ref.revision != self.source.source_revision:
                raise EvidencePackError("managed resource source revision is stale")

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "pack_id": self.pack_id,
            "version": self.version,
            "source_root": self.source_root,
            "manifest_digest": self.manifest_digest,
            "host_contract": self.host_contract,
            "resources": [item.to_dict() for item in self.resources],
            "definition_catalog_digest": self.catalog.digest,
            "role": EVIDENCE_ROLE.to_dict(),
            "source": self.source.to_dict(),
        }

    @classmethod
    def from_managed_pack(cls, managed: ManagedPack) -> "EvidenceResourcePack":
        """Admit one real managed pack into the trusted Evidence command view."""
        if not isinstance(managed, ManagedPack):
            raise EvidencePackError("Evidence admission requires a ManagedPack from public discovery")
        if managed.pack_id != EVIDENCE_PACK_ID or managed.version not in {"1.0.0", EVIDENCE_PACK_VERSION}:
            raise EvidencePackError("unsupported managed Evidence pack")
        resources = {item.path: item for item in managed.resources}
        expected = {
            "schemas/evidence.json": "evidence_schema",
            "policies/provenance.json": "evidence_policy",
            "presets/submit.json": "evidence_preset",
            "presets/version.json": "evidence_preset",
            "skill/SKILL.md": "skill",
            "templates/evidence.json": "evidence_template",
        }
        if managed.version == EVIDENCE_PACK_VERSION:
            expected.update({
                "presets/list.json": "evidence_preset",
                "presets/read.json": "evidence_preset",
            })
            # Reclaim was added without invalidating already-adopted 1.1
            # readers.  A current pack advertises both finite lifecycle
            # presets; an older pinned 1.1 view remains readable but cannot
            # admit the new lifecycle operations.
            for path in ("presets/reclaim-preview.json", "presets/reclaim-apply.json"):
                if path in resources:
                    expected[path] = "evidence_preset"
        if set(resources) != set(expected):
            raise EvidencePackError("managed Evidence resources are incomplete or contain unknown paths")
        for path, kind in expected.items():
            if resources[path].kind != kind:
                raise EvidencePackError(f"managed Evidence resource kind mismatch: {path}")

        def read_json(path: str) -> Mapping[str, Any]:
            try:
                value = json.loads(resources[path].content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidencePackError(f"managed Evidence resource is not valid JSON: {path}") from exc
            if not isinstance(value, Mapping):
                raise EvidencePackError(f"managed Evidence resource must be a JSON object: {path}")
            return value

        schema = read_json("schemas/evidence.json")
        if schema.get("schema_revision") != EVIDENCE_SCHEMA_REVISION or schema.get("record_type") != EVIDENCE_MANIFEST_KIND:
            raise EvidencePackError("managed Evidence schema pin is unsupported")
        if schema.get("representation_version") != "managed-bytes.v1" or schema.get("legacy_inline_readable") is not True:
            raise EvidencePackError("managed Evidence schema compatibility is unsupported")
        policy = read_json("policies/provenance.json")
        required_operations = {"dat.evidence.capture", "dat.evidence.version", "dat.evidence.checkin"}
        if policy.get("host_contract") != EVIDENCE_HOST_CONTRACT or policy.get("document_role") != EVIDENCE_DOCUMENT_ROLE:
            raise EvidencePackError("managed Evidence policy pin is unsupported")
        if not required_operations.issubset(set(policy.get("managed_operations", ()) or ())):
            raise EvidencePackError("managed Evidence policy does not cover all trusted operations")
        if policy.get("policy_cannot_grant_actor_authority") is not True or policy.get("policy_cannot_overwrite_authenticated_facts") is not True:
            raise EvidencePackError("managed Evidence policy weakens authenticated authority")
        if policy.get("automatic_deletion") is True:
            raise EvidencePackError("managed Evidence policy cannot authorize automatic deletion")
        lifecycle_operations = set(policy.get("lifecycle_operations", ()) or ())
        if lifecycle_operations and lifecycle_operations != {
            EVIDENCE_RECLAIM_PREVIEW_OPERATION, EVIDENCE_RECLAIM_APPLY_OPERATION,
        }:
            raise EvidencePackError("managed Evidence lifecycle policy has unsupported operations")

        pins = tuple(
            EvidenceResourcePin(item.path, item.kind, item.source_digest, managed.version, item.source_ref)
            for item in sorted(managed.resources, key=lambda item: item.path)
        )
        pack = cls(
            managed.pack_id,
            managed.version,
            managed.source.pack_root,
            managed.source.source_manifest_sha256,
            pins,
            source=managed.source,
        )
        for operation in required_operations:
            pack.validate_operation(operation)
        return pack

    def resource_bytes(self, path: str) -> bytes:
        """Read one pinned data resource and recheck its immutable digest."""
        relative = Path(path)
        if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
            raise EvidencePackError("Evidence resource path is not safe")
        pin = next((item for item in self.resources if item.path == path), None)
        if pin is None:
            raise EvidencePackError(f"resource is not declared by the selected pack: {path}")
        resource_path = Path(self.source_root) / path
        if resource_path.is_symlink() or not resource_path.is_file():
            raise EvidencePackError(f"selected Evidence resource is unavailable: {path}")
        with resource_path.open("rb") as stream:
            content = stream.read(65537)
        if len(content) > 65536:
            raise EvidencePackError("Evidence policy resource exceeds its metadata bound")
        if hashlib.sha256(content).hexdigest() != pin.digest:
            raise EvidencePackError(f"selected Evidence resource digest changed: {path}")
        return content

    def validate_operation(self, operation: str) -> None:
        """Select the finite preset that admits an operation; resources remain data-only."""
        wanted = "dat.evidence.version" if operation == "dat.evidence.checkin" else operation
        for pin in self.resources:
            if pin.kind != "evidence_preset":
                continue
            try:
                preset = json.loads(self.resource_bytes(pin.path).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidencePackError(f"Evidence preset is not valid JSON: {pin.path}") from exc
            if (
                isinstance(preset, Mapping)
                and preset.get("operation") == wanted
                and preset.get("host_contract") == self.host_contract
                and preset.get("document_role") == EVIDENCE_DOCUMENT_ROLE
            ):
                if wanted in {"dat.content.metadata.list", "dat.content.payload.read"}:
                    if preset.get("canonical_role") != "evidence":
                        raise EvidencePackError("Evidence read preset must select the exact canonical role")
                    bound = "max_page" if wanted == "dat.content.metadata.list" else "max_bytes"
                    expected = 100 if bound == "max_page" else 65536
                    if type(preset.get(bound)) is not int or preset[bound] != expected:
                        raise EvidencePackError("Evidence read preset exceeds the shared finite bound")
                if wanted == EVIDENCE_RECLAIM_PREVIEW_OPERATION:
                    if (preset.get("automatic_deletion") is not False or
                            preset.get("requires_explicit_request") is not True or
                            preset.get("max_page") != 100):
                        raise EvidencePackError("Evidence reclaim preview preset weakens bounded explicit selection")
                if wanted == EVIDENCE_RECLAIM_APPLY_OPERATION:
                    if (preset.get("automatic_deletion") is not False or
                            preset.get("requires_explicit_request") is not True or
                            preset.get("revalidate_before_delete") is not True or
                            preset.get("max_batch") != 100):
                        raise EvidencePackError("Evidence reclaim apply preset weakens bounded revalidation")
                return
        raise EvidencePackError(f"Evidence pack has no validated preset for {operation}")

    def select(self, adopted_pins: Optional[Sequence[Mapping[str, Any]]] = None) -> "EvidenceSelection":
        pins = tuple(self.resources)
        if adopted_pins is not None:
            expected = {item.path: item for item in pins}
            supplied: list[EvidenceResourcePin] = []
            for raw in adopted_pins:
                if not isinstance(raw, Mapping):
                    raise EvidencePackError("adopted resource pins must be objects")
                path = raw.get("path")
                if path not in expected:
                    raise EvidencePackError("resource pin is not declared by the selected pack")
                supplied_source = raw.get("source_ref")
                if expected[path].source_ref is not None:
                    if not isinstance(supplied_source, Mapping):
                        raise EvidencePackError("adopted resource pin is missing its managed source ref")
                    try:
                        supplied_source = ResourceRef.from_dict(supplied_source)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise EvidencePackError("adopted resource pin has an invalid source ref") from exc
                item = EvidenceResourcePin(path, raw.get("kind", expected[path].kind), raw.get("digest", ""), raw.get("version", self.version), supplied_source)
                if (
                    item.digest != expected[path].digest
                    or item.kind != expected[path].kind
                    or item.version != self.version
                    or item.source_ref != expected[path].source_ref
                ):
                    raise EvidencePackError(f"resource pin does not match the selected pack: {path}")
                supplied.append(item)
            if {item.path for item in supplied} != set(expected):
                raise EvidencePackError("selected Evidence resource pins are incomplete")
            pins = tuple(sorted(supplied, key=lambda item: item.path))
        return EvidenceSelection(self, pins)


@dataclass(frozen=True)
class EvidenceSelection:
    pack: EvidenceResourcePack
    resources: Tuple[EvidenceResourcePin, ...]

    def __post_init__(self) -> None:
        if not self.resources:
            raise EvidencePackError("Evidence selection cannot be empty")
        if len({item.path for item in self.resources}) != len(self.resources):
            raise EvidencePackError("Evidence selection contains a resource collision")
        expected = {item.path: item for item in self.pack.resources}
        if {item.path for item in self.resources} != set(expected):
            raise EvidencePackError("Evidence selection contains incomplete resource pins")
        for item in self.resources:
            if item != expected[item.path]:
                raise EvidencePackError(f"Evidence selection contains a stale resource pin: {item.path}")

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        by_path = {item.path: item.to_dict() for item in self.resources}
        return {
            "pack_id": self.pack.pack_id,
            "pack_version": self.pack.version,
            "host_contract": self.pack.host_contract,
            "pack_manifest_digest": self.pack.manifest_digest,
            "source": self.pack.source.to_dict(),
            "resources": [item.to_dict() for item in self.resources],
            "adopted_resource_pins": {
                "schema": by_path["schemas/evidence.json"],
                "policy": by_path["policies/provenance.json"],
                "presets": {
                    "submit": by_path["presets/submit.json"],
                    "version": by_path["presets/version.json"],
                },
            },
            "selection_digest": hashlib.sha256(canonical_json([item.to_dict() for item in self.resources]).encode("utf-8")).hexdigest(),
        }


def load_evidence_pack(
    root: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
    managed_pack: ManagedPack | None = None,
    discoverer: Any = None,
    loader: Any = None,
) -> EvidenceResourcePack:
    """Resolve Evidence through the public managed-source discovery boundary."""
    if managed_pack is None:
        selected_project_root = project_root or root or Path(__file__).resolve().parents[3]
        try:
            managed_pack = read_managed_pack(
                EVIDENCE_PACK_ID,
                project_root=selected_project_root,
                discoverer=discoverer,
                loader=loader,
            )
        except Exception as exc:
            raise EvidencePackError("managed Evidence pack admission failed through the public loader") from exc
    try:
        return EvidenceResourcePack.from_managed_pack(managed_pack)
    except EvidencePackError:
        raise
    except Exception as exc:
        raise EvidencePackError("managed Evidence pack does not satisfy the admitted resource contract") from exc


def validate_manifest(value: Mapping[str, Any]) -> None:
    """Validate a managed manifest through the admitted Evidence role."""
    EVIDENCE_ROLE.validate(value)
    _digest(value["byte_digest"], "byte_digest")
    if value["capture"].get("captured_digest") != value["byte_digest"]:
        raise EvidenceError("capture digest does not match the representation digest")
    if value["capture"].get("captured_length") != value["byte_length"]:
        raise EvidenceError("capture length does not match the representation length")
    storage = value["storage"]
    if storage.get("kind") != "managed-file" or not isinstance(storage.get("location"), str):
        raise EvidenceError("managed evidence must use an owner-managed relative file")


__all__ = [
    "ChangedInputError", "EVIDENCE_ALIAS_NAMESPACE", "EVIDENCE_CHECKOUT_SCHEMA", "EVIDENCE_DOCUMENT_ROLE", "EVIDENCE_DOMAIN_ID", "EVIDENCE_HOST_CONTRACT",
    "EVIDENCE_LIFECYCLE_KIND", "EVIDENCE_RECLAIM_APPLY_EVENT", "EVIDENCE_RECLAIM_APPLY_OPERATION",
    "EVIDENCE_RECLAIM_PREVIEW_EVENT", "EVIDENCE_RECLAIM_PREVIEW_OPERATION", "EVIDENCE_TOMBSTONE_EVENT",
    "EVIDENCE_TOMBSTONE_KIND",
    "EVIDENCE_MANIFEST_KIND", "EVIDENCE_MANAGED_KIND", "EVIDENCE_PACK_ID", "EVIDENCE_PACK_VERSION",
    "EVIDENCE_PROJECTION_DIR", "EVIDENCE_ROLE", "EVIDENCE_SCHEMA_REVISION", "EvidenceAccessDeniedError", "EvidenceBindingError",
    "EvidenceCheckinError", "EvidenceError", "EvidencePackError", "EvidencePathCollisionError", "EvidenceResourcePack", "EvidenceResourcePin", "EvidenceSelection",
    "EvidenceUnavailableError", "PublicationInterrupted", "evidence_catalog", "load_evidence_pack",
    "validate_manifest",
]
