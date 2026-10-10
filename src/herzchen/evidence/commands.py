"""Trusted FND-backed managed Evidence capture and representation resolver."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable, ContextManager, Mapping, Optional, Protocol, Sequence
import zipfile

from herzchen.command_ports import command_facade
from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    DomainContribution,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
)
from herzchen.content.model import ContentDocument, ContentRevision, revision_identity
from herzchen.content.model import CONTENT_SCHEMA_REVISION, DocumentAssociation, document_path
from herzchen.content.commands import ContentCommandHandler
from herzchen.contracts import ReferenceBinding
from herzchen.extensions.model import DefinitionCatalog

from .model import (
    ChangedInputError,
    EVIDENCE_DOMAIN_ID,
    EVIDENCE_ALIAS_NAMESPACE,
    EVIDENCE_CHECKOUT_SCHEMA,
    EVIDENCE_DOCUMENT_ROLE,
    EVIDENCE_HOST_CONTRACT,
    EVIDENCE_MANIFEST_KIND,
    EVIDENCE_MANAGED_KIND,
    EVIDENCE_SCHEMA_REVISION,
    EVIDENCE_STREAM_PREFIX,
    EvidenceAccessDeniedError,
    EvidenceBindingError,
    EvidenceCheckinError,
    EvidenceError,
    EvidencePackError,
    EvidencePathCollisionError,
    EvidenceResourcePack,
    EvidenceSelection,
    EvidenceUnavailableError,
    PublicationInterrupted,
    EVIDENCE_PROJECTION_DIR,
    load_evidence_pack,
    validate_manifest,
)


CAPTURE_OPERATION = "dat.evidence.capture"
VERSION_OPERATION = "dat.evidence.version"
CHECKIN_OPERATION = "dat.evidence.checkin"
CAPTURE_EVENT = "dat.evidence.captured"
VERSION_EVENT = "dat.evidence.versioned"
CHECKIN_EVENT = "dat.evidence.checked-in"
ANNOTATION_OPERATION = "dat.evidence.annotation"
EVIDENCE_LINK_OPERATION = "dat.evidence.alias.link"
EVIDENCE_UNLINK_OPERATION = "dat.evidence.alias.unlink"
EVIDENCE_MOVE_OPERATION = "dat.evidence.alias.move"

# A selected bundle is deliberately finite.  These are bounds on one export,
# not a general archive or synchronization protocol.
EVIDENCE_BUNDLE_MAX_ENTRIES = 100
EVIDENCE_BUNDLE_MAX_BYTES = 256 * 1024 * 1024
EVIDENCE_BUNDLE_MAX_MANIFEST_BYTES = 1024 * 1024


class FNDEvidenceWriter(Protocol):
    authority: str

    def transaction(self) -> ContextManager[Any]: ...
    def mutate(self, envelope: CommandEnvelope, **kwargs: Any) -> CommandReceipt: ...
    def put_identity(self, ref: ResourceRef, payload: Mapping[str, Any], **kwargs: Any) -> Any: ...
    def get_identity(self, ref: ResourceRef) -> Any: ...
    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]: ...
    def domain_handler(self, contributions: Sequence[DomainContribution]) -> Any: ...


def domain_contribution() -> DomainContribution:
    """Describe the shared managed-document seam; no new table or registry."""
    return DomainContribution(
        EVIDENCE_DOMAIN_ID,
        "1",
        "dat",
        (),
        (),
        (),
        (CAPTURE_OPERATION, VERSION_OPERATION, CHECKIN_OPERATION),
        (CAPTURE_EVENT, VERSION_EVENT, CHECKIN_EVENT),
        EVIDENCE_SCHEMA_REVISION,
        (
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "handler-required", "mutation-resource:dat.content.document",
            f"mutation-port:{EVIDENCE_SCHEMA_REVISION}|{CAPTURE_OPERATION}|dat.content.document|{CAPTURE_EVENT}",
            f"mutation-port:{EVIDENCE_SCHEMA_REVISION}|{VERSION_OPERATION}|dat.content.document|{VERSION_EVENT}",
            f"mutation-port:{EVIDENCE_SCHEMA_REVISION}|{CHECKIN_OPERATION}|dat.content.document|{CHECKIN_EVENT}",
        ),
    )


def register_evidence(store: Any) -> Any:
    """Register the Evidence descriptor through normal trusted composition."""
    return store.register_domain_handler((domain_contribution(),))


def _actor(value: Any) -> AuthenticatedActor:
    if not isinstance(value, AuthenticatedActor):
        raise EvidenceError("actor must be an authenticated AuthenticatedActor")
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _same_identity(left: ResourceRef, right: ResourceRef) -> bool:
    return (left.authority, left.kind, left.id) == (right.authority, right.kind, right.id)


def _json_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _format_for(data: bytes, requested: Optional[str]) -> str:
    if requested is not None:
        if not isinstance(requested, str) or not requested.strip():
            raise EvidenceError("format must be non-blank text")
        return requested
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    return "text/plain; charset=utf-8" if b"\x00" not in data else "application/octet-stream"


def _source_info(source: Any, *, source_digest: Optional[str], source_length: Optional[int], read: bool) -> tuple[bytes, dict[str, Any]]:
    """Read a source once, or return a cheap replay fingerprint."""
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        info = {"kind": "bytes", "digest": hashlib.sha256(data).hexdigest(), "length": len(data)}
        if source_digest is not None and source_digest.lower() != info["digest"]:
            raise ChangedInputError("supplied source digest does not match source bytes")
        if source_length is not None and source_length != len(data):
            raise ChangedInputError("supplied source length does not match source bytes")
        return data, info
    if isinstance(source, (str, os.PathLike, Path)):
        raw_path = Path(source).expanduser()
        if raw_path.is_symlink():
            raise EvidenceError("source path must be a regular file")
        path = raw_path.resolve()
        if not path.is_file():
            raise EvidenceError("source path must be a regular file")
        stat = path.stat()
        fingerprint = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "inode": getattr(stat, "st_ino", 0)}
        if not read:
            return b"", {"kind": "path", "path": str(path), "stat": fingerprint, "declared_digest": source_digest, "declared_length": source_length}
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if source_digest is not None and source_digest.lower() != digest:
            raise ChangedInputError("supplied source digest does not match source bytes")
        if source_length is not None and source_length != len(data):
            raise ChangedInputError("supplied source length does not match source bytes")
        return data, {"kind": "path", "path": str(path), "stat": fingerprint, "digest": digest, "length": len(data), "declared_digest": source_digest, "declared_length": source_length}
    if hasattr(source, "read"):
        if not read:
            raise ChangedInputError("file-like replay sources require source_digest and a stable source token")
        data = source.read()
        if not isinstance(data, (bytes, bytearray)):
            raise EvidenceError("binary source readers must return bytes")
        return _source_info(bytes(data), source_digest=source_digest, source_length=source_length, read=True)
    raise EvidenceError("source must be bytes, a regular file, or a binary reader")


class _EvidenceCommandHandlerEngine:
    """One finite owner command surface over shared DAT/FND identities."""

    def __init__(
        self,
        writer: Optional[FNDEvidenceWriter],
        payload_root: str | os.PathLike[str],
        *,
        pack: Optional[EvidenceResourcePack] = None,
        selection: Optional[EvidenceSelection] = None,
        adopted_pins: Optional[Sequence[Mapping[str, Any]]] = None,
        project_root: Optional[str | os.PathLike[str]] = None,
        authorize: Optional[Callable[[Mapping[str, Any], AuthenticatedActor, ResourceRef], bool]] = None,
    ) -> None:
        content_writer = writer
        if writer is not None and hasattr(writer, "domain_handler"):
            try:
                writer = writer.domain_handler((domain_contribution(),))
            except Exception:
                pass
        self.__writer = writer
        self.reader = None if writer is None else writer.consumer()
        # Evidence and DAT content are separate sealed domains.  Keep the
        # owner-issued writer for the existing content facade instead of
        # attempting a content mutation through the Evidence handler.
        self._content = None if content_writer is None else ContentCommandHandler(content_writer)
        self.payload_root = Path(payload_root).expanduser().resolve()
        self.payload_root.mkdir(parents=True, exist_ok=True)
        self._authorize = authorize
        self.pack = pack or load_evidence_pack(project_root=project_root)
        if selection is not None and adopted_pins is not None:
            raise EvidencePackError("provide either an Evidence selection or adopted resource pins, not both")
        self.selection = selection or self.pack.select(adopted_pins)
        if self.selection.pack is not self.pack and self.selection.pack.digest != self.pack.digest:
            raise EvidencePackError("selection does not belong to the selected pack")

    def _require_writer(self) -> FNDEvidenceWriter:
        if self.__writer is None:
            raise EvidenceError("FND-03 writer is required for Evidence commands")
        return self.__writer

    def _rooted(self, relative: str) -> Path:
        path = (self.payload_root / relative).resolve()
        if self.payload_root not in path.parents or path == self.payload_root:
            raise EvidenceError("managed payload location escaped its owner root")
        return path

    def _staging_paths(self, capture_id: str) -> tuple[Path, Path]:
        staging = self.payload_root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        return staging / f"{capture_id}.payload", staging / f"{capture_id}.json"

    @staticmethod
    def _checkout_root(root: str | os.PathLike[str], *, create: bool = False) -> Path:
        path = Path(root).expanduser()
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise EvidencePathCollisionError("evidence checkout root is not a real directory")
        elif create:
            path.mkdir(parents=True, exist_ok=True)
        else:
            raise EvidenceCheckinError("evidence checkout root does not exist")
        return path.resolve()

    @staticmethod
    def _checkout_path(root: Path, relative: str) -> Path:
        try:
            relative = document_path(relative)
        except Exception as exc:
            raise EvidenceCheckinError("evidence checkout path is not a safe relative path") from exc
        destination = root.joinpath(*relative.split("/"))
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                raise EvidencePathCollisionError("evidence checkout path contains a symlink")
        resolved = destination.resolve()
        if root not in resolved.parents:
            raise EvidenceCheckinError("evidence checkout path escaped its root")
        return destination

    def _projection(self, root: str | os.PathLike[str], *, project_ref: Optional[ResourceRef] = None, create: bool = False) -> tuple[Path, dict[str, Any]]:
        checkout = self._checkout_root(root, create=create)
        projection = checkout / EVIDENCE_PROJECTION_DIR
        if projection.exists():
            if projection.is_symlink() or not projection.is_dir():
                raise EvidencePathCollisionError("reserved evidence/ projection collides with an existing path")
        elif create:
            projection.mkdir()
        else:
            raise EvidenceCheckinError("reserved evidence/ projection is missing")
        marker_path = projection / ".checkout.json"
        if not marker_path.is_file() or marker_path.is_symlink():
            if marker_path.exists():
                raise EvidencePathCollisionError("evidence checkout marker collides with an existing path")
            if create:
                if any(projection.iterdir()):
                    raise EvidencePathCollisionError("existing evidence/ contents are not an Evidence checkout")
                return projection, {}
            raise EvidenceCheckinError("evidence checkout marker is missing")
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCheckinError("evidence checkout marker is unreadable") from exc
        if not isinstance(marker, dict) or marker.get("schema") != EVIDENCE_CHECKOUT_SCHEMA:
            raise EvidenceCheckinError("unsupported evidence checkout marker")
        if project_ref is not None and marker.get("project_ref") != project_ref.to_dict():
            raise EvidenceCheckinError("evidence checkout belongs to another project")
        return projection, marker

    def _association(self, project_ref: ResourceRef, alias: str) -> tuple[ResourceRef, Any]:
        try:
            alias = document_path(alias)
        except Exception as exc:
            raise EvidenceCheckinError("evidence alias must be a safe relative path") from exc
        if alias.casefold() == "project.json" or alias.split("/")[0].casefold() in {".otto", EVIDENCE_PROJECTION_DIR}:
            raise EvidencePathCollisionError("evidence alias collides with a reserved projection path")
        association = DocumentAssociation(
            ResourceRef(project_ref.authority, project_ref.kind, project_ref.id),
            EVIDENCE_ALIAS_NAMESPACE,
            alias,
            ReferenceBinding(ResourceRef(project_ref.authority, "dat.content.document", "placeholder"), "current"),
        )
        target = ResourceRef(project_ref.authority, "document-association", association.identity)
        return target, association

    @staticmethod
    def _typed_association(value: Any) -> Optional[DocumentAssociation]:
        if isinstance(value, DocumentAssociation):
            return value
        if isinstance(value, Mapping):
            try:
                return DocumentAssociation.from_dict(value)
            except (KeyError, TypeError, ValueError):
                return None
        return None

    def _content_context(self, operation: str, target: ResourceRef, actor: AuthenticatedActor, key: str,
                         payload: Mapping[str, Any], *, expected_revision: Optional[str] = None,
                         expected_version: Optional[int] = None) -> TransactionContext:
        context = TransactionContext(actor, key, "0" * 64, expected_revision=expected_revision, expected_version=expected_version)
        digest = canonical_request_digest(logical_request_key=key, operation=operation,
            schema_revision=CONTENT_SCHEMA_REVISION, target=target, actor=actor,
            payload=payload, context=context)
        return TransactionContext(actor, key, digest, expected_revision=expected_revision, expected_version=expected_version)

    def _alias_link(self, project_ref: ResourceRef, alias: str, pinned: ResourceRef, *, actor: AuthenticatedActor,
                    logical_request_key: str) -> Mapping[str, Any]:
        if pinned.revision is None:
            raise EvidenceCheckinError("evidence aliases must cite an exact revision")
        target, association = self._association(project_ref, alias)
        association = DocumentAssociation(association.subject, association.namespace, association.key,
                                          ReferenceBinding(pinned, "pinned"))
        existing = self._require_writer().get_identity(target)
        if existing is not None and existing.payload.get("active") is True:
            existing_assoc = self._typed_association(existing.payload.get("association"))
            if isinstance(existing_assoc, DocumentAssociation) and existing_assoc.document.ref == pinned:
                receipt = self._require_writer().get_receipt(logical_request_key)
                if receipt is not None:
                    return {"outcome": "replayed", "receipt": receipt, "association_ref": target,
                            "alias": alias, "citation": pinned}
            raise EvidencePathCollisionError("evidence alias already has an active citation")
        base = None if existing is None else existing.ref.revision
        payload = {"association": association}
        context = self._content_context("dat.content.link", target, actor, logical_request_key, payload,
                                         expected_revision=base, expected_version=0 if existing is None else existing.version)
        receipt = self._content.execute(self._content.build_link(context, association))
        return {"outcome": "linked", "receipt": receipt, "association_ref": receipt.result_ref,
                "alias": alias, "citation": pinned}

    def _alias_unlink(self, project_ref: ResourceRef, alias: str, *, actor: AuthenticatedActor,
                      logical_request_key: str) -> Mapping[str, Any]:
        target, _placeholder = self._association(project_ref, alias)
        existing = self._require_writer().get_identity(target)
        if existing is None or existing.payload.get("active") is not True:
            receipt = self._require_writer().get_receipt(logical_request_key)
            if receipt is not None:
                return {"outcome": "replayed", "receipt": receipt, "association_ref": target, "alias": alias}
            raise EvidenceCheckinError("evidence alias is not active")
        association = self._typed_association(existing.payload.get("association"))
        if association is None or association.document.mode != "pinned":
            raise EvidenceCheckinError("evidence alias does not carry an exact citation pin")
        payload = {"association": association, "preserve_document": True, "preserve_revisions": True}
        context = self._content_context("dat.content.unlink", target, actor, logical_request_key, payload,
                                         expected_revision=existing.ref.revision, expected_version=existing.version)
        receipt = self._content.execute(self._content.build_unlink(context, association))
        return {"outcome": "unlinked", "receipt": receipt, "association_ref": receipt.result_ref,
                "alias": alias, "citation": association.document.ref, "canonical_preserved": True}

    def _document(self, document_ref: ResourceRef) -> Any:
        writer = self._require_writer()
        record = writer.get_identity(ResourceRef(document_ref.authority, document_ref.kind, document_ref.id))
        return record

    def _validate_binding(self, value: Optional[ResourceRef], field: str, *, authority: str) -> Optional[ResourceRef]:
        if value is None:
            return None
        if value.authority != authority:
            raise EvidenceBindingError(f"{field} belongs to a foreign authority")
        writer = self._require_writer()
        current = writer.get_identity(ResourceRef(value.authority, value.kind, value.id))
        if current is None:
            raise EvidenceBindingError(f"{field} is not an admitted identity")
        if value.revision is not None and current.ref.revision != value.revision:
            raise EvidenceBindingError(f"{field} is not the current validated revision")
        return value

    def _validate_origin(self, project_ref: Any, task_ref: Any, attempt_ref: Any) -> dict[str, Any]:
        project = self._validate_binding(_ref(project_ref, "project_ref"), "project_ref", authority=self._require_writer().authority)
        if project is None:
            raise EvidenceBindingError("project_ref is required")
        if project.kind != "work.project":
            raise EvidenceBindingError("project_ref must identify a work.project")
        task = self._validate_binding(None if task_ref is None else _ref(task_ref, "task_ref"), "task_ref", authority=project.authority)
        attempt = self._validate_binding(None if attempt_ref is None else _ref(attempt_ref, "attempt_ref"), "attempt_ref", authority=project.authority)
        writer = self._require_writer()
        if task is not None:
            task_record = writer.get_identity(ResourceRef(task.authority, task.kind, task.id))
            payload = task_record.payload if task_record is not None else {}
            parent = payload.get("project_ref") or payload.get("parent")
            if isinstance(parent, Mapping) and not _same_identity(ResourceRef.from_dict(parent), project):
                raise EvidenceBindingError("task_ref does not belong to project_ref")
        if attempt is not None:
            attempt_record = writer.get_identity(ResourceRef(attempt.authority, attempt.kind, attempt.id))
            payload = attempt_record.payload if attempt_record is not None else {}
            stored_task = payload.get("task_ref")
            if task is not None and isinstance(stored_task, Mapping) and not _same_identity(ResourceRef.from_dict(stored_task), task):
                raise EvidenceBindingError("attempt_ref does not belong to task_ref")
            stored_project = payload.get("project_ref")
            if isinstance(stored_project, Mapping) and not _same_identity(ResourceRef.from_dict(stored_project), project):
                raise EvidenceBindingError("attempt_ref does not belong to project_ref")
        return {"project_ref": project.to_dict(), **({"task_ref": task.to_dict()} if task else {}), **({"attempt_ref": attempt.to_dict()} if attempt else {})}

    def _authorize_read(self, document: Mapping[str, Any], actor: AuthenticatedActor, ref: ResourceRef) -> None:
        if self._authorize is not None:
            if not self._authorize(document, actor, ref):
                raise EvidenceAccessDeniedError("document authorization denied the requested evidence reference")
            return
        if document.get("visibility") == "public":
            return
        if document.get("maintainer") == actor.actor and document.get("ref", {}).get("authority", actor.authority) == actor.authority:
            return
        raise EvidenceAccessDeniedError("document is outside the current evidence authorization boundary")

    def _source_for_stage(self, source: Any, stored: Mapping[str, Any], *, source_digest: Optional[str], source_length: Optional[int]) -> tuple[bytes, dict[str, Any]]:
        kind = stored.get("kind")
        if kind == "bytes" and isinstance(source, (bytes, bytearray)):
            data, info = _source_info(source, source_digest=source_digest, source_length=source_length, read=True)
            if info.get("digest") != stored.get("digest") or info.get("length") != stored.get("length"):
                raise ChangedInputError("replay source bytes differ from the staged capture")
            return b"", stored
        if kind == "path" and isinstance(source, (str, os.PathLike, Path)):
            _, info = _source_info(source, source_digest=source_digest, source_length=source_length, read=False)
            if info.get("path") != stored.get("path") or info.get("stat") != stored.get("stat"):
                raise ChangedInputError("replay source path changed after capture")
            if source_digest is not None and source_digest != stored.get("digest"):
                raise ChangedInputError("replay source digest differs from the staged capture")
            return b"", stored
        if kind == "bytes" and source is None:
            return b"", stored
        raise ChangedInputError("replay source shape differs from the staged capture")

    def _validate_replay_source(
        self,
        source: Any,
        manifest: Mapping[str, Any],
        *,
        source_digest: Optional[str],
        source_length: Optional[int],
    ) -> None:
        """Compare a retry with captured source identity without replaying capture."""
        capture = manifest.get("capture")
        stored = capture.get("source") if isinstance(capture, Mapping) else None
        if not isinstance(stored, Mapping):
            raise ChangedInputError("accepted Evidence capture has no replay source identity")
        self._source_for_stage(source, stored, source_digest=source_digest, source_length=source_length)

    def _capture_stage(
        self,
        source: Any,
        *,
        request_key: str,
        document_id: str,
        actor: AuthenticatedActor,
        source_digest: Optional[str],
        source_length: Optional[int],
        format: Optional[str],
        origin: Mapping[str, Any],
        attribution: Mapping[str, Any],
        provenance: Mapping[str, Any],
        operation: str,
        interrupt_at: Optional[str],
        phase_hook: Optional[Callable[[str], None]],
    ) -> tuple[dict[str, Any], Path, Path]:
        capture_id = hashlib.sha256((request_key + ":" + document_id + ":" + actor.actor).encode("utf-8")).hexdigest()[:32]
        payload_path, sidecar_path = self._staging_paths(capture_id)
        stored: Optional[dict[str, Any]] = None
        if sidecar_path.is_file():
            try:
                loaded = json.loads(sidecar_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    stored = loaded
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceError("staged Evidence metadata is unreadable") from exc
        if stored is not None:
            self._source_for_stage(source, stored["source"], source_digest=source_digest, source_length=source_length)
            if stored.get("request_key") != request_key or stored.get("document_id") != document_id or stored.get("actor") != actor.to_dict():
                raise ChangedInputError("replay request identity differs from the staged capture")
            manifest = stored.get("manifest")
            if not isinstance(manifest, dict):
                raise EvidenceError("staged Evidence manifest is malformed")
            location = manifest.get("storage", {}).get("location")
            if not isinstance(location, str):
                raise EvidenceError("staged Evidence manifest has no managed location")
            final_path = self._rooted(location)
            if not final_path.is_file() and payload_path.is_file():
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(payload_path, final_path)
            if not final_path.is_file():
                raise EvidenceUnavailableError("staged Evidence payload is missing; residue is not admitted")
            return manifest, payload_path, sidecar_path
        data, source_info = _source_info(source, source_digest=source_digest, source_length=source_length, read=True)
        digest = hashlib.sha256(data).hexdigest()
        if not payload_path.exists():
            payload_path.write_bytes(data)
        elif payload_path.read_bytes() != data:
            raise ChangedInputError("staged payload bytes differ from the requested capture")
        relative = str(Path("evidence") / f"{capture_id}.payload")
        final_path = self._rooted(relative)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            if final_path.stat().st_size != len(data) or hashlib.sha256(final_path.read_bytes()).hexdigest() != digest:
                raise EvidenceError("managed payload location already contains different bytes")
        else:
            os.replace(payload_path, final_path)
        data_format = _format_for(data, format)
        manifest = {
            "record_type": EVIDENCE_MANIFEST_KIND,
            "representation_version": "managed-bytes.v1",
            "byte_digest": digest,
            "byte_length": len(data),
            "format": data_format,
            "storage": {"kind": "managed-file", "location": relative, "availability": "staged"},
            "availability": "staged",
            "origin": dict(origin),
            "attribution": dict(attribution),
            "capture": {
                "request_key": request_key,
                "actor": actor.to_dict(),
                "operation": operation,
                "source": source_info,
                "format": data_format,
                "captured_at": _now(),
                "captured_digest": digest,
                "captured_length": len(data),
            },
            "provenance": dict(provenance),
            "resource_selection": self.selection.to_dict(),
        }
        validate_manifest(manifest)
        sidecar = {
            "request_key": request_key,
            "document_id": document_id,
            "actor": actor.to_dict(),
            "source": source_info,
            "manifest": manifest,
            "operation": operation,
        }
        sidecar_path.write_text(canonical_json(sidecar), encoding="utf-8")
        if phase_hook is not None:
            phase_hook("payload")
        if interrupt_at == "payload":
            raise PublicationInterrupted("payload publication interrupted; managed residue is staged but not admitted")
        return manifest, final_path, sidecar_path

    def _validate_admission(self, manifest: Mapping[str, Any], *, operation: str) -> None:
        if len(canonical_json(manifest).encode("utf-8")) > 32768:
            raise EvidenceError("managed metadata exceeds the 32768-byte admission bound")
        self.pack.validate_operation(operation)
        self.pack.catalog.role(EVIDENCE_DOCUMENT_ROLE).validate(manifest)
        validate_manifest(manifest)
        selected = manifest.get("resource_selection")
        if not isinstance(selected, Mapping) or selected.get("pack_id") != self.pack.pack_id or selected.get("host_contract") != EVIDENCE_HOST_CONTRACT:
            raise EvidencePackError("manifest was not selected by the admitted Evidence pack")
        expected_selection = self.selection.to_dict()
        if dict(selected) != expected_selection:
            raise EvidencePackError("manifest Evidence resource pins are stale or tampered")
        if operation not in {CAPTURE_OPERATION, VERSION_OPERATION, CHECKIN_OPERATION}:
            raise EvidenceError("unsupported Evidence admission operation")

    def _envelope(self, operation: str, target: ResourceRef, actor: AuthenticatedActor, key: str, payload: Mapping[str, Any], *, expected_revision: Optional[str], expected_version: int) -> CommandEnvelope:
        digest = canonical_request_digest(
            logical_request_key=key, operation=operation, schema_revision=EVIDENCE_SCHEMA_REVISION,
            target=target, actor=actor, payload=payload,
            expected_revision=expected_revision, expected_version=expected_version,
        )
        return CommandEnvelope(operation, EVIDENCE_SCHEMA_REVISION, target, TransactionContext(actor, key, digest, expected_revision, expected_version), payload)

    def _persist(self, *, operation: str, event_type: str, document: ContentDocument, revision: ContentRevision, key: str, actor: AuthenticatedActor, manifest: Mapping[str, Any], current: Any) -> CommandReceipt:
        writer = self._require_writer()
        target = document.ref
        payload = {"document": document, "revision": revision, "manifest": dict(manifest), "representation": "managed-bytes"}
        expected_revision = None if current is None else current.ref.revision
        expected_version = 0 if current is None else current.version
        envelope = self._envelope(operation, target, actor, key, payload, expected_revision=expected_revision, expected_version=expected_version)
        head_payload = {"record_type": "dat.content.document", "document": document, "current_revision": revision.ref}
        with writer.transaction() as transaction:
            receipt = writer.mutate(
                envelope,
                identity_payload=head_payload,
                event_type=event_type,
                result_ref=revision.ref,
                before_refs=() if current is None else (current.ref,),
                after_refs=(revision.ref,),
                effects={
                    "representation": "managed-bytes", "byte_digest": manifest["byte_digest"],
                    "byte_length": manifest["byte_length"], "availability": "admitted",
                    "resource_selection": self.selection.to_dict(),
                },
                stream=EVIDENCE_STREAM_PREFIX + document.ref.id,
                transaction=transaction,
            )
            revision_payload = {
                "record_type": "dat.content.revision", "document": document.ref,
                "revision": revision.revision, "parent_revision": revision.parent_revision,
                "content": dict(manifest), "content_digest": revision.content_digest,
                "author": actor, "initial": revision.initial,
            }
            writer.put_identity(revision_identity(document.ref, revision.revision), revision_payload, version=0, transaction=transaction)
            from herzchen.content.reads import metadata_identity, revision_metadata
            writer.put_identity(metadata_identity(revision.ref), revision_metadata(revision), version=0, transaction=transaction)
        return receipt

    def _result(self, receipt: CommandReceipt, *, document_ref: ResourceRef, manifest: Mapping[str, Any], operation: str, replayed: bool = False) -> Mapping[str, Any]:
        return {
            "outcome": "replayed" if replayed else "captured",
            "operation": operation,
            "replayed": replayed,
            "document_ref": document_ref,
            "revision_ref": receipt.result_ref,
            "manifest": dict(manifest),
            "receipt": receipt,
            "resource_selection": self.selection.to_dict(),
        }

    def _submit_or_version(
        self,
        source: Any,
        *,
        actor: AuthenticatedActor,
        logical_request_key: str,
        project_ref: Any,
        task_ref: Any,
        attempt_ref: Any,
        original_creator: str,
        maintainer: Optional[str],
        document_id: Optional[str],
        format: Optional[str],
        provenance: Optional[Mapping[str, Any]],
        source_digest: Optional[str],
        source_length: Optional[int],
        operation: str,
        interrupt_at: Optional[str],
        phase_hook: Optional[Callable[[str], None]],
        base_ref: Optional[ResourceRef] = None,
    ) -> Mapping[str, Any]:
        actor = _actor(actor)
        writer = self._require_writer()
        if not isinstance(logical_request_key, str) or not logical_request_key.strip():
            raise EvidenceError("logical_request_key is required")
        if not isinstance(original_creator, str) or not original_creator.strip():
            raise EvidenceError("original_creator is required")
        maintainer = maintainer or actor.actor
        origin = self._validate_origin(project_ref, task_ref, attempt_ref)
        if document_id is None:
            document_id = "evidence-" + hashlib.sha256(logical_request_key.encode("utf-8")).hexdigest()[:28]
        if not isinstance(document_id, str) or not document_id.strip() or "/" in document_id or "\\" in document_id:
            raise EvidenceError("document_id must be an opaque identifier")
        target = ResourceRef(writer.authority, "dat.content.document", document_id)
        prior = writer.get_receipt(logical_request_key)
        if prior is not None:
            if prior.result_ref is None:
                raise EvidenceError("replayed Evidence receipt has no result reference")
            prior_document = ResourceRef(
                prior.result_ref.authority, prior.result_ref.kind, prior.result_ref.id,
            )
            prior_revision = writer.get_identity(
                revision_identity(prior_document, prior.result_ref.revision)
            )
            if prior_revision is None:
                raise EvidenceUnavailableError("replayed Evidence revision is unavailable")
            prior_manifest = prior_revision.payload.get("content")
            if not isinstance(prior_manifest, Mapping):
                raise EvidenceError("replayed Evidence revision has no manifest")
            capture = prior_manifest.get("capture")
            if not isinstance(capture, Mapping) or capture.get("operation") != operation:
                raise ReplayConflictError("logical request key was reused for a different Evidence operation")
            if capture.get("actor") != actor.to_dict():
                raise ReplayConflictError("logical request key was reused by a different authenticated actor")
            if prior_manifest.get("origin") != self._validate_origin(project_ref, task_ref, attempt_ref):
                raise ReplayConflictError("logical request key was reused with changed origin bindings")
            prior_attribution = prior_manifest.get("attribution")
            if not isinstance(prior_attribution, Mapping):
                raise ReplayConflictError("accepted Evidence capture has no attribution")
            if prior_attribution.get("original_creator") != original_creator or prior_attribution.get("maintainer") != maintainer:
                raise ReplayConflictError("logical request key was reused with changed attribution")
            if format is not None and capture.get("format") != format:
                raise ReplayConflictError("logical request key was reused with changed format")
            if provenance is not None and prior_manifest.get("provenance") != dict(provenance):
                raise ReplayConflictError("logical request key was reused with changed provenance")
            self._validate_replay_source(source, prior_manifest, source_digest=source_digest, source_length=source_length)
            self._validate_admission(prior_manifest, operation=operation)
            self._remove_sidecar(self._staging_paths(
                hashlib.sha256((logical_request_key + ":" + document_id + ":" + actor.actor).encode("utf-8")).hexdigest()[:32]
            )[1])
            return self._result(prior, document_ref=target, manifest=prior_manifest, operation=operation, replayed=True)
        current = self._document(target)
        if operation == CAPTURE_OPERATION and current is not None:
            raise EvidenceError("managed Evidence document already exists; use version or checkin")
        if operation in {VERSION_OPERATION, CHECKIN_OPERATION}:
            if current is None:
                raise EvidenceError("version/checkin requires an existing Evidence document")
            current_document = current.payload.get("document")
            if not isinstance(current_document, Mapping) or current_document.get("role") != "evidence":
                raise EvidenceError("target document is not an Evidence document")
            if operation == CHECKIN_OPERATION and base_ref is not None and base_ref.revision != current.ref.revision:
                raise EvidenceError("checkin base revision is stale")
        attribution = {"original_creator": original_creator, "submitter": actor.to_dict(), "maintainer": maintainer}
        manifest, _payload_path, sidecar_path = self._capture_stage(
            source, request_key=logical_request_key, document_id=document_id, actor=actor,
            source_digest=source_digest, source_length=source_length, format=format,
            origin=origin, attribution=attribution, provenance=dict(provenance or {}),
            operation=operation, interrupt_at=interrupt_at, phase_hook=phase_hook,
        )
        manifest = dict(manifest)
        manifest["availability"] = "admitted"
        manifest["storage"] = dict(manifest["storage"], availability="admitted")
        self._validate_admission(manifest, operation=operation)
        payload = {"document_id": document_id, "operation": operation, "manifest": manifest, "base_revision": None if current is None else current.ref.revision}
        expected_revision = None if current is None else current.ref.revision
        expected_version = 0 if current is None else current.version
        envelope = self._envelope(operation, target, actor, logical_request_key, payload, expected_revision=expected_revision, expected_version=expected_version)
        if prior is not None:
            if prior.request_digest != envelope.context.request_digest:
                raise ReplayConflictError("logical request key was reused with changed Evidence input")
            if prior.result_ref is None:
                raise EvidenceError("replayed Evidence receipt has no result reference")
            self._remove_sidecar(sidecar_path)
            return self._result(prior, document_ref=target, manifest=manifest, operation=operation, replayed=True)
        if phase_hook is not None:
            phase_hook("manifest")
        if interrupt_at == "manifest":
            raise PublicationInterrupted("manifest publication interrupted; payload is durable residue but not admitted")
        if current is None:
            document = ContentDocument(target, "evidence", "private", "read", maintainer, writable=False)
            revision = ContentRevision(target, "rev-1", manifest, actor, initial=True)
            event_type = CAPTURE_EVENT
        else:
            raw_document = current.payload.get("document")
            document = ContentDocument.from_dict(raw_document)
            revision = ContentRevision(target, f"rev-{current.version + 1}", manifest, actor, parent_revision=current.ref.revision)
            event_type = VERSION_EVENT if operation == VERSION_OPERATION else CHECKIN_EVENT
        receipt = self._persist(operation=operation, event_type=event_type, document=document, revision=revision, key=logical_request_key, actor=actor, manifest=manifest, current=current)
        if phase_hook is not None:
            phase_hook("receipt")
        if interrupt_at == "receipt":
            raise PublicationInterrupted("receipt publication was interrupted after the FND commit; replay is safe")
        self._remove_sidecar(sidecar_path)
        return self._result(receipt, document_ref=target, manifest=manifest, operation=operation)

    @staticmethod
    def _remove_sidecar(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def submit(self, source: Any, *, actor: AuthenticatedActor, logical_request_key: str, project_ref: Any, task_ref: Any = None, attempt_ref: Any = None, original_creator: str, maintainer: Optional[str] = None, document_id: Optional[str] = None, format: Optional[str] = None, provenance: Optional[Mapping[str, Any]] = None, source_digest: Optional[str] = None, source_length: Optional[int] = None, interrupt_at: Optional[str] = None, phase_hook: Optional[Callable[[str], None]] = None) -> Mapping[str, Any]:
        return self._submit_or_version(source, actor=actor, logical_request_key=logical_request_key, project_ref=project_ref, task_ref=task_ref, attempt_ref=attempt_ref, original_creator=original_creator, maintainer=maintainer, document_id=document_id, format=format, provenance=provenance, source_digest=source_digest, source_length=source_length, operation=CAPTURE_OPERATION, interrupt_at=interrupt_at, phase_hook=phase_hook)

    def version(self, document_ref: Any, source: Any, *, actor: AuthenticatedActor, logical_request_key: str, project_ref: Any, task_ref: Any = None, attempt_ref: Any = None, original_creator: str, maintainer: Optional[str] = None, format: Optional[str] = None, provenance: Optional[Mapping[str, Any]] = None, source_digest: Optional[str] = None, source_length: Optional[int] = None, interrupt_at: Optional[str] = None, phase_hook: Optional[Callable[[str], None]] = None) -> Mapping[str, Any]:
        ref = _ref(document_ref, "document_ref")
        return self._submit_or_version(source, actor=actor, logical_request_key=logical_request_key, project_ref=project_ref, task_ref=task_ref, attempt_ref=attempt_ref, original_creator=original_creator, maintainer=maintainer, document_id=ref.id, format=format, provenance=provenance, source_digest=source_digest, source_length=source_length, operation=VERSION_OPERATION, interrupt_at=interrupt_at, phase_hook=phase_hook, base_ref=ref)

    def checkin(self, document_ref: Any, source: Any, *, base_revision: str, actor: AuthenticatedActor, logical_request_key: str, project_ref: Any, task_ref: Any = None, attempt_ref: Any = None, original_creator: str, maintainer: Optional[str] = None, format: Optional[str] = None, provenance: Optional[Mapping[str, Any]] = None, source_digest: Optional[str] = None, source_length: Optional[int] = None, interrupt_at: Optional[str] = None, phase_hook: Optional[Callable[[str], None]] = None) -> Mapping[str, Any]:
        ref = _ref(document_ref, "document_ref")
        if not isinstance(base_revision, str) or not base_revision.strip():
            raise EvidenceError("base_revision is required for checkin")
        return self._submit_or_version(source, actor=actor, logical_request_key=logical_request_key, project_ref=project_ref, task_ref=task_ref, attempt_ref=attempt_ref, original_creator=original_creator, maintainer=maintainer, document_id=ref.id, format=format, provenance=provenance, source_digest=source_digest, source_length=source_length, operation=CHECKIN_OPERATION, interrupt_at=interrupt_at, phase_hook=phase_hook, base_ref=ResourceRef(ref.authority, ref.kind, ref.id, base_revision))

    def checkout_evidence(self, project_ref: Any, *, checkout_root: str | os.PathLike[str], actor: AuthenticatedActor,
                          cursor: str = "", limit: int = 50, representation: Optional[str] = None,
                          format: Optional[str] = None, task_refs: Sequence[Any] = ()) -> Mapping[str, Any]:
        """Create/read only the lazy Evidence projection, never project.json or docs/."""
        actor = _actor(actor)
        project = _ref(project_ref, "project_ref")
        origin = self._validate_origin(project, None, None)
        projection, marker = self._projection(checkout_root, project_ref=project, create=True)
        if not marker:
            marker = {
                "schema": EVIDENCE_CHECKOUT_SCHEMA,
                "project_ref": project.to_dict(),
                "created_by": actor.to_dict(),
                "projection": EVIDENCE_PROJECTION_DIR + "/",
                "read_only": True,
                "docs_materialized": False,
                "project_json_materialized": False,
                "materialized": [],
            }
            (projection / ".checkout.json").write_text(canonical_json(marker), encoding="utf-8")
        page = self.list_evidence(project, actor=actor, representation=representation, format=format,
                                   cursor=cursor, limit=limit, task_refs=task_refs)
        index = {"schema": EVIDENCE_CHECKOUT_SCHEMA, "project_ref": origin["project_ref"], "page": page}
        (projection / ".index.json").write_text(canonical_json(index), encoding="utf-8")
        return {"outcome": "checked_out", "projection": EVIDENCE_PROJECTION_DIR + "/",
                "checkout_root": str(Path(checkout_root).expanduser().resolve()),
                "manifest": marker, "index": page, "read_only": True,
                "docs_materialized": False, "project_json_materialized": False,
                "execution": False, "dispatch": False}

    def materialize_evidence(self, reference: Any, *, checkout_root: str | os.PathLike[str], actor: AuthenticatedActor,
                             alias: Optional[str] = None) -> Mapping[str, Any]:
        """Copy one authorized exact pin into an Evidence checkout as a read-only file."""
        actor = _actor(actor)
        ref = _ref(reference, "reference")
        status = self.status(ref, actor=actor)
        if status.get("representation") != "managed" or status.get("availability") in {"missing", "corrupt", "purged", "staged"}:
            raise EvidenceUnavailableError("selected Evidence payload is unavailable")
        if ref.revision is None:
            ref = status["reference"]
        origin = status["manifest"].get("origin", {})
        project_value = origin.get("project_ref")
        project = _ref(project_value, "manifest.origin.project_ref")
        projection, marker = self._projection(checkout_root, project_ref=project, create=False)
        alias = alias or f"{ref.id}-{ref.revision}"
        try:
            alias = document_path(alias)
        except Exception as exc:
            raise EvidenceCheckinError("materialized Evidence alias is not a safe path") from exc
        if alias.casefold() == "project.json" or alias.split("/")[0].casefold() in {".otto", EVIDENCE_PROJECTION_DIR}:
            raise EvidencePathCollisionError("materialized Evidence path is reserved")
        destination = self._checkout_path(projection, alias)
        if destination.exists():
            raise EvidencePathCollisionError("selected Evidence destination already exists")
        if destination.parent != projection:
            destination.parent.mkdir(parents=True, exist_ok=True)
        source_path = self._rooted(status["manifest"]["storage"]["location"])
        if not source_path.is_file():
            raise EvidenceUnavailableError("selected Evidence payload is missing")
        digest = hashlib.sha256()
        length = 0
        try:
            with source_path.open("rb") as source, destination.open("xb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
        except Exception:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            raise
        manifest = status["manifest"]
        if length != manifest["byte_length"] or digest.hexdigest() != manifest["byte_digest"]:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            raise EvidenceUnavailableError("materialized Evidence bytes do not match the pinned manifest")
        destination.chmod(0o444)
        materialized = list(marker.get("materialized", ()))
        materialized.append({"path": str(destination.relative_to(projection)), "reference": ref.to_dict()})
        marker["materialized"] = materialized
        (projection / ".checkout.json").write_text(canonical_json(marker), encoding="utf-8")
        return {"outcome": "materialized", "path": str(destination), "read_only": True,
                "canonical_authority": "owner", "reference": ref, "manifest": dict(manifest),
                "provenance": {"project_ref": project, "canonical_transfer": False},
                "docs_materialized": False, "project_json_materialized": False}

    @staticmethod
    def _bundle_entry(value: Any, index: int) -> tuple[ResourceRef, Optional[str]]:
        """Decode one explicit selection without accepting caller paths as refs."""
        alias = None
        raw = value
        if isinstance(value, Mapping):
            raw = value.get("reference", value.get("ref"))
            alias = value.get("alias", value.get("path"))
            if alias is not None and not isinstance(alias, str):
                raise EvidenceCheckinError(f"bundle selection {index} alias must be text")
        try:
            ref = _ref(raw, f"bundle selection {index}.reference")
        except EvidenceBindingError:
            raise EvidenceCheckinError(f"bundle selection {index} has no valid reference") from None
        return ref, alias

    @staticmethod
    def _bundle_alias(ref: ResourceRef, alias: Optional[str]) -> str:
        if alias is None:
            # Keep names portable and independent of document identity syntax.
            token = hashlib.sha256(canonical_json(ref.to_dict()).encode("utf-8")).hexdigest()[:20]
            return f"evidence/{token}.payload"
        try:
            alias = document_path(alias)
        except Exception as exc:
            raise EvidenceCheckinError("bundle alias must be a safe relative path") from exc
        if alias.casefold() in {"manifest.json", ".bundle.json"}:
            raise EvidencePathCollisionError("bundle alias collides with its manifest")
        if alias.split("/")[0].casefold() in {".otto", EVIDENCE_PROJECTION_DIR}:
            raise EvidencePathCollisionError("bundle alias collides with a reserved bundle path")
        return f"evidence/{alias}"

    @staticmethod
    def _copy_verified_payload(source: Path, write: Callable[[bytes], None], *, expected_digest: str,
                               expected_length: int) -> tuple[int, str]:
        """Copy one managed object while verifying the exact pinned bytes."""
        if source.is_symlink() or not source.is_file():
            raise EvidenceUnavailableError("selected Evidence payload is unavailable")
        digest = hashlib.sha256()
        length = 0
        try:
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
        except (OSError, ValueError) as exc:
            raise EvidenceUnavailableError("selected Evidence payload could not be copied") from exc
        actual_digest = digest.hexdigest()
        if length != expected_length or actual_digest != expected_digest:
            raise EvidenceUnavailableError("selected Evidence payload changed during bundle copy")
        return length, actual_digest

    def bundle_evidence(self, project_ref: Any, selections: Optional[Sequence[Any]] = None,
                        output_path: Optional[str | os.PathLike[str]] = None, *,
                        actor: AuthenticatedActor, archive: bool = False,
                        references: Optional[Sequence[Any]] = None,
                        max_entries: int = EVIDENCE_BUNDLE_MAX_ENTRIES,
                        max_bytes: int = EVIDENCE_BUNDLE_MAX_BYTES) -> Mapping[str, Any]:
        """Export explicit authorized Evidence pins as one bounded bundle.

        The result is an ordinary authorized copy.  The canonical DAT/FND
        records remain authoritative, and the bundle never grants destination
        authority or revokes already-exported copies.
        """
        actor = _actor(actor)
        project = _ref(project_ref, "project_ref")
        self._validate_origin(project, None, None)
        if selections is None:
            selections = references
        if selections is None or isinstance(selections, (str, bytes)):
            raise EvidenceCheckinError("bundle selections must be an explicit finite sequence")
        if type(max_entries) is not int or not 1 <= max_entries <= EVIDENCE_BUNDLE_MAX_ENTRIES:
            raise EvidenceCheckinError("bundle max_entries is outside the supported bound")
        if type(max_bytes) is not int or not 1 <= max_bytes <= EVIDENCE_BUNDLE_MAX_BYTES:
            raise EvidenceCheckinError("bundle max_bytes is outside the supported bound")
        selected = list(selections)
        if not selected or len(selected) > max_entries:
            raise EvidenceCheckinError("bundle selection count is outside the supported bound")
        if output_path is None:
            raise EvidenceCheckinError("bundle output_path is required")

        output = Path(output_path).expanduser()
        if output.exists() or output.is_symlink():
            raise EvidencePathCollisionError("bundle output already exists")
        parent = output.parent.resolve()
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise EvidencePathCollisionError("bundle output parent is not a real directory")
        parent.mkdir(parents=True, exist_ok=True)

        candidates: list[tuple[ResourceRef, Optional[str]]] = [self._bundle_entry(value, index) for index, value in enumerate(selected)]
        inventory: dict[str, list[Mapping[str, Any]]] = {
            "included": [], "omitted": [], "unavailable": [], "purged": [],
        }
        used_refs: set[tuple[str, str, str, Optional[str]]] = set()
        used_paths: set[str] = {"manifest.json"}
        total_bytes = 0

        def requested_item(ref: ResourceRef, alias: Optional[str], **extra: Any) -> dict[str, Any]:
            item: dict[str, Any] = {"reference": ref.to_dict()}
            if alias is not None:
                item["requested_alias"] = alias
            item.update(extra)
            return item

        # Resolve metadata and current authorization before creating any copy.
        resolved: list[tuple[ResourceRef, str, Mapping[str, Any], Path]] = []
        for index, (requested, alias) in enumerate(candidates):
            key = (requested.authority, requested.kind, requested.id, requested.revision)
            if key in used_refs:
                raise EvidenceCheckinError(f"bundle selection {index} repeats an exact reference")
            used_refs.add(key)
            try:
                status = self.status(requested, actor=actor)
            except EvidenceAccessDeniedError:
                inventory["omitted"].append(requested_item(requested, alias, reason="not-authorized"))
                continue
            if status.get("representation") != "managed":
                inventory["omitted"].append(requested_item(requested, alias, reason="unmanaged-representation"))
                continue
            exact = status.get("reference")
            if not isinstance(exact, ResourceRef):
                exact = _ref(exact, f"bundle selection {index}.resolved_reference")
            manifest = status.get("manifest")
            if not isinstance(manifest, Mapping):
                inventory["unavailable"].append(requested_item(exact, alias, reason="manifest-unavailable"))
                continue
            availability = status.get("availability", manifest.get("availability"))
            item = requested_item(exact, alias, availability=availability, manifest=dict(manifest))
            if availability == "purged":
                inventory["purged"].append(item)
                continue
            if availability in {"missing", "corrupt", "staged"}:
                inventory["unavailable"].append(item)
                continue
            location = manifest.get("storage", {}).get("location")
            try:
                source = self._rooted(location)
                destination = self._bundle_alias(exact, alias)
            except (EvidenceError, TypeError) as exc:
                inventory["unavailable"].append(requested_item(exact, alias, reason="unsafe-managed-location"))
                continue
            if destination in used_paths:
                raise EvidencePathCollisionError("bundle selections resolve to a colliding path")
            used_paths.add(destination)
            length = manifest.get("byte_length")
            if type(length) is not int or length < 0:
                inventory["unavailable"].append(item | {"reason": "invalid-byte-length"})
                continue
            if length > max_bytes or total_bytes + length > max_bytes:
                inventory["omitted"].append(item | {"reason": "bundle-size-bound"})
                continue
            resolved.append((exact, destination, manifest, source))
            total_bytes += length

        # Build in a private sibling, then publish only the completed selected
        # directory/archive.  No existing output is overwritten.
        temp_path: Optional[Path] = None
        temp_dir: Optional[Path] = None
        try:
            if archive:
                fd, raw_path = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".zip", dir=str(parent))
                os.close(fd)
                temp_path = Path(raw_path)
                writer = zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True)
            else:
                temp_dir = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(parent)))
                (temp_dir / "evidence").mkdir()
                writer = None

            included: list[Mapping[str, Any]] = []
            for exact, destination, manifest, source in resolved:
                try:
                    if writer is not None:
                        with writer.open(destination, mode="w", force_zip64=True) as stream:
                            copied_length, copied_digest = self._copy_verified_payload(
                                source, stream.write, expected_digest=manifest["byte_digest"],
                                expected_length=manifest["byte_length"])
                    else:
                        target = temp_dir / destination
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as stream:
                            copied_length, copied_digest = self._copy_verified_payload(
                                source, stream.write, expected_digest=manifest["byte_digest"],
                                expected_length=manifest["byte_length"])
                        target.chmod(0o444)
                except EvidenceUnavailableError as exc:
                    inventory["unavailable"].append({
                        "reference": exact.to_dict(), "reason": str(exc), "manifest": dict(manifest),
                    })
                    continue
                included.append({
                    "reference": exact.to_dict(),
                    "path": destination,
                    "manifest": dict(manifest),
                    "provenance": {
                        "origin": dict(manifest.get("origin", {})),
                        "attribution": dict(manifest.get("attribution", {})),
                        "capture": dict(manifest.get("capture", {})),
                        "canonical_authority": "owner",
                    },
                    "byte_length": copied_length,
                    "byte_digest": copied_digest,
                })

            bundle_manifest: dict[str, Any] = {
                "schema": "dat.evidence.bundle.v1",
                "bundle_kind": "archive" if archive else "directory",
                "project_ref": project.to_dict(),
                "created_by": {"authority": actor.authority, "actor": actor.actor, "authenticated": True},
                "created_at": _now(),
                "canonical_authority": "owner",
                "canonical_transfer": False,
                "exported_copy_revocable": False,
                "selected": len(selected),
                "byte_limit": max_bytes,
                "included_bytes": sum(item["byte_length"] for item in included),
                "inventory": {
                    "included": included,
                    "omitted": inventory["omitted"],
                    "unavailable": inventory["unavailable"],
                    "purged": inventory["purged"],
                },
            }
            encoded_manifest = canonical_json(bundle_manifest).encode("utf-8")
            if len(encoded_manifest) > EVIDENCE_BUNDLE_MAX_MANIFEST_BYTES:
                raise EvidenceCheckinError("bundle manifest exceeds its metadata bound")
            if writer is not None:
                writer.writestr("manifest.json", encoded_manifest)
                writer.close()
                writer = None
            else:
                (temp_dir / "manifest.json").write_bytes(encoded_manifest)
            final_temp = temp_path if archive else temp_dir
            assert final_temp is not None
            os.replace(final_temp, output)
            temp_path = None
            temp_dir = None
            return {
                "outcome": "bundled",
                "path": str(output.resolve()),
                "manifest": bundle_manifest,
                "included": included,
                "omitted": inventory["omitted"],
                "unavailable": inventory["unavailable"],
                "purged": inventory["purged"],
                "canonical_authority": "owner",
                "canonical_transfer": False,
                "exported_copy_revocable": False,
            }
        finally:
            if writer is not None:
                writer.close()
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def cite_evidence(self, reference: Any, *, project_ref: Any, alias: str, actor: AuthenticatedActor,
                      logical_request_key: str) -> Mapping[str, Any]:
        """Create a mutable alias whose association permanently names an exact pin."""
        actor = _actor(actor)
        project = _ref(project_ref, "project_ref")
        self._validate_origin(project, None, None)
        ref = _ref(reference, "reference")
        status = self.status(ref, actor=actor)
        pinned = status["reference"]
        if pinned.revision is None:
            raise EvidenceCheckinError("citation requires a resolved exact revision")
        return self._alias_link(project, alias, pinned, actor=actor, logical_request_key=logical_request_key)

    def cite(self, reference: Any, *, project_ref: Any, alias: str, actor: AuthenticatedActor,
             logical_request_key: str) -> Mapping[str, Any]:
        return self.cite_evidence(reference, project_ref=project_ref, alias=alias, actor=actor,
                                  logical_request_key=logical_request_key)

    def unlink_alias(self, *, project_ref: Any, alias: str, actor: AuthenticatedActor,
                     logical_request_key: str) -> Mapping[str, Any]:
        actor = _actor(actor)
        project = _ref(project_ref, "project_ref")
        self._validate_origin(project, None, None)
        return self._alias_unlink(project, alias, actor=actor, logical_request_key=logical_request_key)

    def move_alias(self, *, project_ref: Any, from_alias: str, to_alias: str, actor: AuthenticatedActor,
                   logical_request_key: str, interrupt_at: Optional[str] = None) -> Mapping[str, Any]:
        """Move an alias without changing the exact pin held by the old citation."""
        actor = _actor(actor)
        project = _ref(project_ref, "project_ref")
        self._validate_origin(project, None, None)
        source_target, _placeholder = self._association(project, from_alias)
        source = self._require_writer().get_identity(source_target)
        if source is None or source.payload.get("active") is not True:
            raise EvidenceCheckinError("source Evidence alias is not active")
        association = self._typed_association(source.payload.get("association"))
        if association is None or association.document.mode != "pinned":
            raise EvidenceCheckinError("source Evidence alias is not pin-preserving")
        committed: list[Mapping[str, Any]] = []
        try:
            link = self._alias_link(project, to_alias, association.document.ref, actor=actor,
                                    logical_request_key=logical_request_key + ":link")
            committed.append({"phase": "link", "receipt": link.get("receipt")})
            if interrupt_at == "after-link":
                return {"outcome": "partial", "from_alias": from_alias, "to_alias": to_alias,
                        "citation": association.document.ref, "committed": committed,
                        "pending": {"operation": "move-alias", "request_key": logical_request_key,
                                    "from_alias": from_alias, "to_alias": to_alias},
                        "recovery": "Resume the same logical request key to unlink the old alias.",
                        "canonical_preserved": True}
            unlink = self._alias_unlink(project, from_alias, actor=actor,
                                        logical_request_key=logical_request_key + ":unlink")
            committed.append({"phase": "unlink", "receipt": unlink.get("receipt")})
            return {"outcome": "moved", "from_alias": from_alias, "to_alias": to_alias,
                    "citation": association.document.ref, "committed": committed,
                    "canonical_preserved": True}
        except EvidencePathCollisionError:
            raise
        except Exception as exc:
            return {"outcome": "partial", "from_alias": from_alias, "to_alias": to_alias,
                    "citation": association.document.ref, "committed": committed,
                    "pending": {"operation": "move-alias", "request_key": logical_request_key,
                                "from_alias": from_alias, "to_alias": to_alias},
                    "error": {"code": type(exc).__name__, "message": str(exc)},
                    "recovery": "Inspect child receipts and resume the same logical request key.",
                    "canonical_preserved": True}

    def annotate(self, document_ref: Any, annotation: Mapping[str, Any], *, actor: AuthenticatedActor,
                 logical_request_key: str, base_revision: Optional[str] = None) -> Mapping[str, Any]:
        """Append a separately versioned annotation while freezing capture facts and bytes."""
        actor = _actor(actor)
        if not isinstance(annotation, Mapping) or not annotation:
            raise EvidenceCheckinError("annotation must be a non-empty object")
        if set(annotation).intersection({"byte_digest", "byte_length", "format", "storage", "capture", "origin", "resource_selection"}):
            raise EvidenceCheckinError("annotation cannot overwrite immutable Evidence provenance")
        if len(canonical_json(annotation).encode("utf-8")) > 8192:
            raise EvidenceCheckinError("annotation exceeds its bounded metadata limit")
        ref = _ref(document_ref, "document_ref")
        status = self.status(ref, actor=actor)
        if status.get("representation") != "managed":
            raise EvidenceCheckinError("annotations require managed Evidence")
        current = self._document(ResourceRef(ref.authority, ref.kind, ref.id))
        if current is None:
            raise EvidenceUnavailableError("Evidence document is unavailable")
        current_ref = ResourceRef.from_dict(current.payload["current_revision"])
        if base_revision is not None and base_revision != current_ref.revision:
            raise EvidenceCheckinError("annotation base revision is stale")
        writer = self._require_writer()
        prior = writer.get_receipt(logical_request_key)
        if prior is not None:
            record = writer.get_identity(prior.result_ref) if prior.result_ref is not None else None
            manifest = {} if record is None else record.payload.get("content", {})
            return self._result(prior, document_ref=ResourceRef(ref.authority, ref.kind, ref.id),
                                manifest=manifest, operation=ANNOTATION_OPERATION, replayed=True)
        revision_record = writer.get_identity(revision_identity(ResourceRef(ref.authority, ref.kind, ref.id), current_ref.revision))
        if revision_record is None or not isinstance(revision_record.payload.get("content"), Mapping):
            raise EvidenceUnavailableError("current Evidence revision is unavailable")
        manifest = dict(revision_record.payload["content"])
        annotations = list(manifest.get("annotations", ()))
        annotations.append({"id": hashlib.sha256((logical_request_key + actor.actor).encode("utf-8")).hexdigest()[:24],
                            "author": actor.to_dict(), "created_at": _now(), "value": _safe(annotation)})
        manifest["annotations"] = annotations
        self._validate_admission(manifest, operation=CHECKIN_OPERATION)
        document = ContentDocument.from_dict(current.payload["document"])
        revision = ContentRevision(document.ref, f"rev-{int(current_ref.revision.split('-')[1]) + 1}", manifest,
                                   actor, parent_revision=current_ref.revision)
        receipt = self._persist(operation=CHECKIN_OPERATION, event_type=CHECKIN_EVENT, document=document,
                                revision=revision, key=logical_request_key, actor=actor, manifest=manifest,
                                current=current)
        return self._result(receipt, document_ref=document.ref, manifest=manifest,
                            operation=ANNOTATION_OPERATION)

    def checkin_evidence(self, *, action: str, actor: AuthenticatedActor, logical_request_key: str,
                         project_ref: Any, document_ref: Any = None, source: Any = None,
                         base_revision: Optional[str] = None, annotation: Optional[Mapping[str, Any]] = None,
                         alias: Optional[str] = None, from_alias: Optional[str] = None,
                         to_alias: Optional[str] = None, **kwargs: Any) -> Mapping[str, Any]:
        """Finite dispatcher for projection check-in actions; no action is inferred from local files."""
        action = action.replace("_", "-").lower() if isinstance(action, str) else ""
        if action in {"submit", "new-version", "version"}:
            if source is None:
                raise EvidenceCheckinError("submit/version check-in requires explicit source bytes")
            if action == "submit":
                return self.submit(source, actor=actor, logical_request_key=logical_request_key,
                                   project_ref=project_ref, **kwargs)
            if document_ref is None or base_revision is None:
                raise EvidenceCheckinError("new-version check-in requires document_ref and base_revision")
            current = self._document(_ref(document_ref, "document_ref"))
            if current is None or ResourceRef.from_dict(current.payload["current_revision"]).revision != base_revision:
                raise EvidenceCheckinError("new-version check-in base revision is stale")
            return self.version(document_ref, source, actor=actor, logical_request_key=logical_request_key,
                                project_ref=project_ref, **kwargs)
        if action == "annotation":
            if document_ref is None or annotation is None:
                raise EvidenceCheckinError("annotation check-in requires document_ref and annotation")
            return self.annotate(document_ref, annotation, actor=actor, logical_request_key=logical_request_key,
                                 base_revision=base_revision)
        if action in {"alias-move", "move-alias"}:
            if from_alias is None or to_alias is None:
                raise EvidenceCheckinError("alias move requires from_alias and to_alias")
            return self.move_alias(project_ref=project_ref, from_alias=from_alias, to_alias=to_alias,
                                   actor=actor, logical_request_key=logical_request_key,
                                   interrupt_at=kwargs.get("interrupt_at"))
        if action in {"unlink", "alias-unlink", "unlink-alias"}:
            if alias is None:
                raise EvidenceCheckinError("unlink requires alias")
            return self.unlink_alias(project_ref=project_ref, alias=alias, actor=actor,
                                     logical_request_key=logical_request_key)
        raise EvidenceCheckinError("unsupported Evidence check-in action")

    def status(self, reference: Any, *, actor: AuthenticatedActor, roles=(), scopes=()) -> Mapping[str, Any]:
        from herzchen.content.reads import document_metadata
        actor = _actor(actor)
        def check(document, caller, ref):
            if self._authorize is not None:
                self._authorize_read(document, caller, ref)
            else:
                from herzchen.content.reads import authorize
                authorize(document, caller, roles, scopes)
        try:
            status = dict(document_metadata(self.reader, reference, actor=actor,
                authorize_read=check, include_inline=True))
        except (PermissionError, EvidenceAccessDeniedError):
            raise EvidenceAccessDeniedError("document unavailable") from None
        if status["representation"] == "managed":
            manifest = status["manifest"]
            state = manifest["availability"]
            if state not in {"missing", "corrupt", "purged", "staged"}:
                path = self._rooted(manifest["storage"]["location"])
                try:
                    actual_length = path.stat().st_size if path.is_file() else None
                except OSError:
                    actual_length = None
                state = "missing" if actual_length is None else "corrupt" if actual_length != manifest["byte_length"] else "admitted"
            status["availability"] = state
            status["payload_verification"] = "not-revalidated"
        return status

    def list_metadata(self, project_ref: Any, *, actor: AuthenticatedActor, exact_role: str,
                      representation=None, format=None, cursor: str = "", limit: int = 50,
                      roles=(), task_refs=()) -> Mapping[str, Any]:
        from herzchen.content.reads import list_project_metadata
        return list_project_metadata(self.reader, project_ref, actor=_actor(actor), exact_role=exact_role,
            representation=representation, format=format, cursor=cursor, limit=limit, roles=roles,
            task_refs=task_refs, metadata_reader=lambda ref, scopes: self.status(ref, actor=actor, roles=roles, scopes=scopes))

    def list_evidence(self, project_ref: Any, *, actor: AuthenticatedActor, representation=None,
                      format=None, cursor: str = "", limit: int = 50, roles=(), task_refs=()) -> Mapping[str, Any]:
        # Evidence is a preset of the shared role query, never a second index.
        self.pack.validate_operation("dat.content.metadata.list")
        return self.list_metadata(project_ref, actor=actor, exact_role="evidence",
            representation=representation, format=format, cursor=cursor, limit=limit, roles=roles, task_refs=task_refs)

    def read_evidence(self, reference: Any, *, actor: AuthenticatedActor, offset: int = 0,
                      max_bytes: int = 65536, verify_full: bool = False, roles=(), scopes=()) -> Mapping[str, Any]:
        self.pack.validate_operation("dat.content.payload.read")
        status = self.status(reference, actor=actor, roles=roles, scopes=scopes)
        if status["document"].get("role") != "evidence":
            raise EvidenceAccessDeniedError("document unavailable")
        return self.resolve(reference, actor=actor, offset=offset, max_bytes=max_bytes,
                            verify_full=verify_full, roles=roles, scopes=scopes)

    def consumer_reference(self, reference: Any, *, actor: AuthenticatedActor, roles=(), scopes=()) -> Mapping[str, Any]:
        status = self.status(reference, actor=actor, roles=roles, scopes=scopes)
        return {"schema": "dat.content.consumer-reference.v1", "reference": status["reference"],
                "representation": status["representation"], "content_digest": status.get("content_digest"),
                "availability": status["availability"], "verification": status["verification"],
                "byte_digest": status.get("manifest", {}).get("byte_digest"),
                "byte_length": status.get("byte_length"), "format": status.get("format")}

    def resolve(self, reference: Any, *, actor: AuthenticatedActor, offset: int = 0, max_bytes: int = 65536, verify_full: bool = False, roles=(), scopes=()) -> Mapping[str, Any]:
        started = time.perf_counter()
        if type(offset) is not int or offset < 0 or type(max_bytes) is not int or not 0 <= max_bytes <= 65536:
            raise EvidenceError("offset must be non-negative and max_bytes must be 0..65536")
        status = self.status(reference, actor=actor, roles=roles, scopes=scopes)
        if status["representation"] != "managed":
            return status
        manifest = status["manifest"]
        if status["availability"] in {"missing", "corrupt", "purged", "staged"}:
            return {**status, "bytes": b"", "offset": offset, "next_offset": None}
        location = manifest.get("storage", {}).get("location")
        path = self._rooted(location)
        if not path.is_file():
            return {"representation": "managed", "reference": status["reference"], "manifest": manifest, "availability": "missing", "verification": "missing", "bytes": b"", "offset": offset, "next_offset": None}
        work = dict(status["io_work"])
        actual_digest = None
        full_verified = False
        if verify_full:
            digest = hashlib.sha256()
            total = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk); total += len(chunk)
            work["payload_bytes_read"] += total
            work["payload_bytes_hashed"] += total
            actual_digest = digest.hexdigest()
            full_verified = total == manifest["byte_length"] and actual_digest == manifest["byte_digest"]
            if not full_verified:
                return {"representation": "managed", "reference": status["reference"], "manifest": dict(manifest, availability="corrupt"), "availability": "corrupt", "verification": "full-mismatch", "bytes": b"", "offset": offset, "next_offset": None, "actual_digest": actual_digest, "actual_length": total, "io_work": dict(work, processing_seconds=time.perf_counter()-started)}
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(max_bytes)
        work["payload_bytes_read"] += len(data)
        work["processing_seconds"] = time.perf_counter() - started
        next_offset = offset + len(data) if offset + len(data) < manifest["byte_length"] else None
        return {"representation": "managed", "reference": status["reference"], "manifest": manifest, "availability": "verified" if full_verified else "admitted", "verification": "full-verified" if full_verified else "range-not-revalidated", "decoding": "raw-bytes", "io_work": work, "bytes": data, "offset": offset, "next_offset": next_offset, "actual_digest": actual_digest}

    def read_legacy_inline(self, reference: Any, *, actor: AuthenticatedActor, roles=(), scopes=()) -> Mapping[str, Any]:
        """Explicit historical detail hydration; never a routine status read."""
        status = self.status(reference, actor=actor, roles=roles, scopes=scopes)
        if status["representation"] == "managed":
            raise EvidenceError("managed bytes require the capped resolver")
        ref = status["reference"]
        record = self._require_writer().get_identity(revision_identity(ResourceRef(ref.authority, ref.kind, ref.id), ref.revision))
        content = record.payload["content"]
        size = len(canonical_json(content).encode())
        return {**status, "representation": "inline", "content": content,
                "verification": "legacy-inline", "io_work": {**status["io_work"],
                    "payload_bytes_parsed": size, "linear_historical_read": True}}


EvidenceCommandHandler = command_facade(_EvidenceCommandHandlerEngine, EVIDENCE_DOMAIN_ID)


__all__ = [
    "CAPTURE_EVENT", "CAPTURE_OPERATION", "CHECKIN_EVENT", "CHECKIN_OPERATION", "EvidenceCommandHandler",
    "FNDEvidenceWriter", "VERSION_EVENT", "VERSION_OPERATION", "domain_contribution", "register_evidence",
]
