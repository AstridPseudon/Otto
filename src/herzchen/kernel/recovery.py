"""Neutral recovery, snapshot, cursor, and persisted interval mechanics.

FND-05 deliberately builds on the FND-03/FND-04 owner.  Recovery records are
ordinary identities and every state change goes through :meth:`Store.mutate`;
snapshots contain a consistent SQLite backup plus authenticated references to
the external bytes needed by a host.  This module does not execute external
operations and does not own a second event log or database connection.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sqlite3
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    EventCursor,
    EventEnvelope,
    ResourceRef,
    TransactionContext,
    canonical_json,
)

from .schema import COMPOSITION, SCHEMA_FINGERPRINT, SCHEMA_REVISION, SUPPORTED_SCHEMAS
from .store import Store, StoreError, TargetMismatchError, Transaction, VersionConflictError


SNAPSHOT_FORMAT = "fnd-05.snapshot.v1"
CURSOR_FORMAT = "fnd-05.cursor.v1"
RECOVERY_KIND = "runtime-epoch"
RECOVERY_SCHEMA_REVISION = "fnd-05.recovery.v1"
INTERVAL_KIND = "attention-interval"
INTERVAL_SCHEMA_REVISION = "fnd-05.interval.v1"


class RecoveryError(StoreError):
    """Base error for neutral recovery and attention state."""


class SnapshotError(RecoveryError):
    """Snapshot creation or manifest validation failed."""


class SnapshotValidationError(SnapshotError):
    """A snapshot or restore candidate failed an integrity/expectation check."""


class RestoreActivationError(SnapshotError):
    """A verified candidate could not be activated without overwriting data."""


class CursorError(RecoveryError):
    """A bounded event cursor is malformed, out of scope, or expired."""


class CursorMalformedError(CursorError):
    """The opaque cursor cannot be decoded or fails its integrity digest."""


class CursorScopeError(CursorError):
    """The cursor does not match the requested authority, stream, or filter."""


class CursorExpiredError(CursorError):
    """The caller must establish a fresh cursor because this one expired."""


class StaleTokenError(RecoveryError):
    """A runtime/session token no longer authorizes a durable settlement."""


class UnknownTokenError(RecoveryError):
    """A token was not found in the durable recovery state."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError("invalid persisted timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _ref_dict(value: ResourceRef) -> dict[str, Any]:
    if not isinstance(value, ResourceRef):
        raise TypeError("identity must be a ResourceRef")
    return value.to_dict()


def _ref(value: Mapping[str, Any]) -> ResourceRef:
    try:
        return ResourceRef.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError("invalid persisted resource reference") from exc


def _directory_identity(path: Path, error_type: type[SnapshotError] = RestoreActivationError) -> Tuple[int, int]:
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise error_type("required parent directory is missing: {}".format(path)) from exc
    if stat.S_ISLNK(info.st_mode):
        raise error_type("refusing to follow symlink directory: {}".format(path))
    if not stat.S_ISDIR(info.st_mode):
        raise error_type("required parent is not a directory: {}".format(path))
    return info.st_dev, info.st_ino


def _prepare_parent(path: Path, error_type: type[SnapshotError] = RestoreActivationError) -> Tuple[int, int]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    missing = []
    current = absolute.parent
    while True:
        try:
            os.lstat(current)
            _directory_identity(current, error_type)
            break
        except FileNotFoundError:
            missing.append(current)
            if current.parent == current:
                raise error_type("filesystem root is unavailable: {}".format(current))
            current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _directory_identity(directory, error_type)
    return _directory_identity(absolute.parent, error_type)


def _assert_directory_identity(path: Path, expected: Tuple[int, int], error_type: type[SnapshotError] = RestoreActivationError) -> None:
    if _directory_identity(path, error_type) != expected:
        raise error_type("directory identity changed during recovery: {}".format(path))


def _ensure_unused(path: Path, error_type: type[SnapshotError] = RestoreActivationError) -> Tuple[int, int]:
    parent_identity = _prepare_parent(path, error_type)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return parent_identity
    if stat.S_ISLNK(info.st_mode):
        raise error_type("restore root is an existing or dangling symlink: {}".format(path))
    raise error_type("restore root already exists; refusing to overwrite it: {}".format(path))


def _regular_file_stat(path: Path, error_type: type[SnapshotError] = SnapshotError) -> os.stat_result:
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise error_type("required regular file is missing: {}".format(path)) from exc
    if stat.S_ISLNK(info.st_mode):
        raise error_type("refusing to follow symlink file: {}".format(path))
    if not stat.S_ISREG(info.st_mode):
        raise error_type("required path is not a regular file: {}".format(path))
    return info


def _file_digest(path: Path, error_type: type[SnapshotError] = SnapshotError) -> str:
    _regular_file_stat(path, error_type)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_file_state(path: Path, error_type: type[SnapshotError] = SnapshotError) -> dict[str, Any]:
    before = _regular_file_stat(path, error_type)
    digest = _file_digest(path, error_type)
    after = _regular_file_stat(path, error_type)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise error_type("file changed while being read: {}".format(path))
    return {
        "device": int(after.st_dev), "inode": int(after.st_ino), "size": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns), "digest": digest,
    }


def _same_file_state(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("device", "inode", "size", "mtime_ns", "digest"))


def _sidecar_states(database: Path, error_type: type[SnapshotError] = SnapshotError) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for suffix in ("-journal", "-wal", "-shm"):
        path = Path(str(database) + suffix)
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        states[suffix] = _stable_file_state(path, error_type)
    return states


def _create_root(path: Path, parent_identity: Tuple[int, int], error_type: type[SnapshotError] = RestoreActivationError) -> Tuple[int, int]:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise error_type("restore root appeared during creation: {}".format(path)) from exc
    _assert_directory_identity(path.parent, parent_identity, error_type)
    return _directory_identity(path, error_type)


def _ensure_directory(path: Path, parent_identity: Tuple[int, int], error_type: type[SnapshotError] = RestoreActivationError) -> Tuple[int, int]:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise error_type("directory appeared during creation: {}".format(path)) from exc
    else:
        if stat.S_ISLNK(info.st_mode):
            raise error_type("refusing to follow symlink directory: {}".format(path))
        if not stat.S_ISDIR(info.st_mode):
            raise error_type("required path is not a directory: {}".format(path))
    _assert_directory_identity(path.parent, parent_identity, error_type)
    return _directory_identity(path, error_type)


def _copy_exact(source: Path, target: Path, error_type: type[SnapshotError] = SnapshotError) -> str:
    _regular_file_stat(source, error_type)
    _prepare_parent(target, error_type)
    try:
        existing = os.lstat(target)
    except FileNotFoundError:
        existing = None
    if existing is not None and stat.S_ISLNK(existing.st_mode):
        raise error_type("refusing to overwrite symlink: {}".format(target))
    with source.open("rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(str(source), str(target), follow_symlinks=False)
    return _sha256_bytes(target.read_bytes())


@dataclass(frozen=True)
class SnapshotManifest:
    """The authenticated description of one consistent common-state snapshot."""

    snapshot_id: str
    store_authority: str
    source_identity: ResourceRef
    realm_identity: ResourceRef
    schema_revision: str
    schema_fingerprint: str
    composition: Tuple[str, ...]
    composition_digest: str
    database_digest: str
    database_size: int
    journal_files: Tuple[Mapping[str, Any], ...]
    event_watermarks: Mapping[str, int]
    external_objects: Tuple[Mapping[str, Any], ...]
    domain_descriptors: Tuple[Mapping[str, Any], ...]
    cursors: Tuple[Mapping[str, Any], ...]
    created_at: str
    manifest_digest: str
    format_revision: str = SNAPSHOT_FORMAT
    read_proof: Optional[Mapping[str, Any]] = None

    def _body(self) -> dict[str, Any]:
        return {
            "format_revision": self.format_revision,
            "snapshot_id": self.snapshot_id,
            "store_authority": self.store_authority,
            "source_identity": self.source_identity.to_dict(),
            "realm_identity": self.realm_identity.to_dict(),
            "schema_revision": self.schema_revision,
            "schema_fingerprint": self.schema_fingerprint,
            "composition": list(self.composition),
            "composition_digest": self.composition_digest,
            "database_digest": self.database_digest,
            "database_size": self.database_size,
            "journal_files": [dict(item) for item in self.journal_files],
            "event_watermarks": dict(self.event_watermarks),
            "external_objects": [dict(item) for item in self.external_objects],
            "domain_descriptors": [dict(item) for item in self.domain_descriptors],
            "cursors": [dict(item) for item in self.cursors],
            "created_at": self.created_at,
            "read_proof": dict(self.read_proof or {}),
        }

    def to_dict(self) -> dict[str, Any]:
        return dict(self._body(), manifest_digest=self.manifest_digest)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotManifest":
        if not isinstance(value, Mapping):
            raise SnapshotValidationError("snapshot manifest must be an object")
        try:
            body = dict(value)
            digest = body.pop("manifest_digest")
            had_read_proof = "read_proof" in body
            manifest = cls(
                str(body["snapshot_id"]), str(body["store_authority"]), _ref(body["source_identity"]),
                _ref(body["realm_identity"]), str(body["schema_revision"]), str(body["schema_fingerprint"]),
                tuple(str(item) for item in body["composition"]), str(body["composition_digest"]),
                str(body["database_digest"]), int(body["database_size"]),
                tuple(dict(item) for item in body.get("journal_files", [])),
                {str(key): int(number) for key, number in dict(body.get("event_watermarks", {})).items()},
                tuple(dict(item) for item in body.get("external_objects", [])),
                tuple(dict(item) for item in body.get("domain_descriptors", [])),
                tuple(dict(item) for item in body.get("cursors", [])), str(body["created_at"]), str(digest),
                str(body.get("format_revision", SNAPSHOT_FORMAT)),
                dict(body.get("read_proof", {})) if had_read_proof else None,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SnapshotValidationError("snapshot manifest is incomplete") from exc
        if manifest.format_revision != SNAPSHOT_FORMAT:
            raise SnapshotValidationError("unsupported snapshot format")
        body_for_digest = manifest._body()
        if manifest.read_proof is None:
            body_for_digest.pop("read_proof", None)
        if manifest.manifest_digest != _sha256_json(body_for_digest):
            raise SnapshotValidationError("snapshot manifest digest mismatch")
        return manifest


@dataclass(frozen=True)
class RestoreCandidate:
    root: Path
    database_path: Path
    manifest: SnapshotManifest
    object_paths: Tuple[Path, ...] = ()

    @property
    def path(self) -> Path:
        return self.root

    def __fspath__(self) -> str:
        return os.fspath(self.root)


@dataclass(frozen=True)
class RestoreResult:
    candidate: RestoreCandidate
    activated_root: Optional[Path]


def _composition_digest(composition: Sequence[str]) -> str:
    return _sha256_json(list(composition))


def _manifest_at(root: Path) -> SnapshotManifest:
    try:
        _regular_file_stat(root / "manifest.json", SnapshotValidationError)
        with (root / "manifest.json").open("r", encoding="utf-8") as handle:
            return SnapshotManifest.from_dict(json.load(handle))
    except FileNotFoundError as exc:
        raise SnapshotValidationError("snapshot manifest is missing") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotValidationError("snapshot manifest is not valid JSON") from exc


def _validate_expectations(
    manifest: SnapshotManifest,
    *,
    expected_source_identity: ResourceRef,
    expected_realm_identity: ResourceRef,
    expected_authority: str,
    expected_composition: Sequence[str],
    expected_composition_digest: str,
    expected_schema_fingerprint: str,
) -> None:
    if not isinstance(expected_source_identity, ResourceRef) or not isinstance(expected_realm_identity, ResourceRef):
        raise TypeError("source and realm expectations must be ResourceRef values")
    if manifest.store_authority != expected_authority:
        raise SnapshotValidationError("snapshot authority does not match caller expectation")
    if manifest.source_identity != expected_source_identity or manifest.realm_identity != expected_realm_identity:
        raise SnapshotValidationError("snapshot source/realm identity does not match caller expectation")
    expected = tuple(sorted(expected_composition))
    if tuple(manifest.composition) != expected:
        raise SnapshotValidationError("snapshot composition does not match caller expectation")
    if manifest.composition_digest != expected_composition_digest or expected_composition_digest != _composition_digest(expected):
        raise SnapshotValidationError("snapshot composition digest does not match caller expectation")
    admitted = SUPPORTED_SCHEMAS.get(manifest.schema_revision)
    if (admitted is None or tuple(sorted(admitted[0])) != expected or
        manifest.schema_fingerprint != admitted[1] or manifest.schema_fingerprint != expected_schema_fingerprint):
        raise SnapshotValidationError("snapshot schema identity does not match caller expectation")


def _identity_read(identity: Any) -> Optional[dict[str, Any]]:
    if identity is None:
        return None
    return {
        "ref": identity.ref.to_dict(), "version": int(identity.version), "payload": dict(identity.payload),
        "edit_token": identity.edit_token, "created_at": identity.created_at, "updated_at": identity.updated_at,
    }


def _public_read_proof(store: Store, events: Sequence[EventEnvelope]) -> dict[str, Any]:
    refs: dict[str, ResourceRef] = {}
    for event in events:
        for ref in (event.subject,) + tuple(event.before_refs) + tuple(event.after_refs):
            refs[ref.to_json()] = ref
    receipt_keys = tuple(str(row[0]) for row in store.connection.execute("SELECT logical_request_key FROM command_receipts ORDER BY logical_request_key").fetchall())
    receipts = []
    for key in receipt_keys:
        receipt = store.get_receipt(key)
        if receipt is None:
            raise SnapshotError("receipt disappeared during snapshot read proof")
        receipts.append({"logical_request_key": key, "receipt": receipt.to_dict()})
        for ref in (receipt.target,) + (() if receipt.result_ref is None else (receipt.result_ref,)):
            refs[ref.to_json()] = ref
    ordered_refs = tuple(refs[key] for key in sorted(refs))
    identities = []
    references = []
    for ref in ordered_refs:
        identities.append({"ref": ref.to_dict(), "identity": _identity_read(store.get_identity(ref))})
        reference = store.get_reference(ref)
        references.append({"ref": ref.to_dict(), "reference": None if reference is None else reference.to_dict()})
    return {
        "events": [event.to_dict() for event in events],
        "receipts": receipts,
        "identities": identities,
        "references": references,
    }


def _verify_public_read_proof(store: Store, proof: Optional[Mapping[str, Any]]) -> None:
    if not isinstance(proof, Mapping) or set(proof) != {"events", "receipts", "identities", "references"}:
        raise SnapshotValidationError("snapshot public read proof is missing or malformed")
    actual_events = [event.to_dict() for event in store.list_events()]
    if actual_events != list(proof["events"]):
        raise SnapshotValidationError("restored event read proof does not match the captured state")
    for item in proof["receipts"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("logical_request_key"), str):
            raise SnapshotValidationError("snapshot receipt read proof is malformed")
        actual = store.get_receipt(item["logical_request_key"])
        if actual is None or actual.to_dict() != item.get("receipt"):
            raise SnapshotValidationError("restored receipt read proof does not match the captured state")
    for item in proof["identities"]:
        if not isinstance(item, Mapping):
            raise SnapshotValidationError("snapshot identity read proof is malformed")
        ref = _ref(item.get("ref", {}))
        if _identity_read(store.get_identity(ref)) != item.get("identity"):
            raise SnapshotValidationError("restored identity read proof does not match the captured state")
    for item in proof["references"]:
        if not isinstance(item, Mapping):
            raise SnapshotValidationError("snapshot reference read proof is malformed")
        ref = _ref(item.get("ref", {}))
        actual = store.get_reference(ref)
        actual_value = None if actual is None else actual.to_dict()
        if actual_value != item.get("reference"):
            raise SnapshotValidationError("restored reference read proof does not match the captured state")


def create_snapshot(
    store: Store,
    root: Union[os.PathLike, str],
    *,
    source_identity: ResourceRef,
    realm_identity: ResourceRef,
    external_refs: Sequence[ResourceRef] = (),
    object_files: Optional[Mapping[Union[str, ResourceRef], Union[os.PathLike, str, bytes, bytearray]]] = None,
    cursors: Sequence[EventCursor] = (),
    snapshot_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> SnapshotManifest:
    """Create a consistent snapshot without opening a second Store writer.

    ``object_files`` is optional host-owned CAS evidence.  A string/path value
    is copied byte-for-byte; bytes are materialised into the snapshot.  Plain
    ``external_refs`` remain references when their bytes are not in scope.
    """
    if not isinstance(store, Store):
        raise TypeError("store must be a Store")
    if store.path == ":memory:":
        raise SnapshotError("durable snapshots require a file-backed Store")
    if not isinstance(source_identity, ResourceRef) or not isinstance(realm_identity, ResourceRef):
        raise TypeError("source_identity and realm_identity must be ResourceRef values")
    root_path = Path(root)
    parent_identity = _ensure_unused(root_path, SnapshotError)
    root_identity = _create_root(root_path, parent_identity, SnapshotError)
    database_path = root_path / "database.sqlite3"
    try:
        with store._transaction_lock:
            if store.connection.in_transaction:
                raise SnapshotError("snapshot cannot start inside an active Store transaction")
            events = store.list_events()
            event_watermarks: dict[str, int] = {}
            for event in events:
                event_watermarks[event.stream] = max(event_watermarks.get(event.stream, 0), event.sequence)
            read_proof = _public_read_proof(store, events)
            cursor_dicts = []
            for cursor in cursors:
                if not isinstance(cursor, EventCursor):
                    raise TypeError("cursors must contain EventCursor values")
                if cursor.authority != store.authority:
                    raise SnapshotValidationError("cursor authority does not match the Store")
                cursor_dicts.append(cursor.to_dict())
            composition = tuple(sorted(COMPOSITION))
            created_at = _iso(now or _utc_now())
            domain_descriptors = [descriptor.to_dict() for descriptor in store.registered_domains()]
            source = Path(store.path)
            source_before = _regular_file_stat(source)
            journal_mode_row = store.connection.execute("PRAGMA journal_mode").fetchone()
            journal_mode = str(journal_mode_row[0]).lower() if journal_mode_row else ""
            if journal_mode == "wal":
                try:
                    checkpoint = store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    mode_after = str(store.connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                except sqlite3.Error as exc:
                    raise SnapshotError("WAL checkpoint failed") from exc
                if not checkpoint or int(checkpoint[0]) != 0 or mode_after != "wal":
                    raise SnapshotError("WAL checkpoint was busy or unstable")
            if store.connection.in_transaction:
                raise SnapshotError("snapshot checkpoint left an active Store transaction")
            source_baseline = _regular_file_stat(source)
            if (source_before.st_dev, source_before.st_ino) != (source_baseline.st_dev, source_baseline.st_ino):
                raise SnapshotError("source database identity changed during checkpoint")
            sidecar_baseline = _sidecar_states(source)
            _assert_directory_identity(root_path, root_identity, SnapshotError)
            _copy_exact(source, database_path)
            database_digest = _sha256_bytes(database_path.read_bytes())
            source_final = _stable_file_state(source)
            if (source_final["device"], source_final["inode"], source_final["size"], source_final["mtime_ns"]) != (source_baseline.st_dev, source_baseline.st_ino, source_baseline.st_size, source_baseline.st_mtime_ns) or source_final["digest"] != database_digest:
                raise SnapshotError("source database changed during snapshot capture")
            journal_files = []
            for suffix, state in sidecar_baseline.items():
                _assert_directory_identity(root_path, root_identity, SnapshotError)
                destination_sidecar = root_path / "journal-evidence" / ("database.sqlite3" + suffix)
                _copy_exact(Path(str(source) + suffix), destination_sidecar)
                journal_files.append(dict({"name": suffix}, **state))
            if sidecar_baseline != _sidecar_states(source):
                raise SnapshotError("journal/WAL sidecar changed during snapshot capture")

            external_objects = []
            for ref in external_refs:
                if not isinstance(ref, ResourceRef):
                    raise TypeError("external_refs must contain ResourceRef values")
                external_objects.append({"ref": ref.to_dict(), "digest": None, "size": None})
            for key, value in (object_files or {}).items():
                ref_value = key.to_dict() if isinstance(key, ResourceRef) else {"authority": "external", "kind": "object", "id": str(key), "revision": None}
                object_root = root_path / "objects"
                _ensure_directory(object_root, root_identity, SnapshotError)
                if isinstance(value, (bytes, bytearray)):
                    data = bytes(value)
                    digest = _sha256_bytes(data)
                    output = object_root / digest
                    with output.open("xb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    object_state = {"size": len(data)}
                else:
                    input_path = Path(value)
                    input_state = _stable_file_state(input_path)
                    digest = str(input_state["digest"])
                    output = object_root / digest
                    _copy_exact(input_path, output)
                    final_state = _stable_file_state(input_path)
                    if not _same_file_state(input_state, final_state):
                        raise SnapshotError("external object changed during snapshot capture: {}".format(input_path))
                    object_state = {key: input_state[key] for key in ("device", "inode", "mtime_ns", "size")}
                external_objects.append(dict({"ref": ref_value, "digest": digest, "size": output.stat().st_size, "path": "objects/" + digest}, **object_state))
        manifest_without_digest = {
            "format_revision": SNAPSHOT_FORMAT,
            "snapshot_id": snapshot_id or hashlib.sha256((created_at + database_digest).encode("utf-8")).hexdigest()[:24],
            "store_authority": store.authority,
            "source_identity": source_identity.to_dict(),
            "realm_identity": realm_identity.to_dict(),
            "schema_revision": SCHEMA_REVISION,
            "schema_fingerprint": SCHEMA_FINGERPRINT,
            "composition": list(composition),
            "composition_digest": _composition_digest(composition),
            "database_digest": database_digest,
            "database_size": database_path.stat().st_size,
            "journal_files": journal_files,
            "event_watermarks": event_watermarks,
            "external_objects": external_objects,
            "domain_descriptors": domain_descriptors,
            "cursors": cursor_dicts,
            "created_at": created_at,
            "read_proof": read_proof,
        }
        manifest = SnapshotManifest(
            manifest_without_digest["snapshot_id"], store.authority, source_identity, realm_identity,
            SCHEMA_REVISION, SCHEMA_FINGERPRINT, composition, manifest_without_digest["composition_digest"],
            database_digest, database_path.stat().st_size, tuple(journal_files), event_watermarks,
            tuple(external_objects), tuple(domain_descriptors), tuple(cursor_dicts), created_at, _sha256_json(manifest_without_digest),
            read_proof=read_proof,
        )
        _assert_directory_identity(root_path, root_identity, SnapshotError)
        with (root_path / "manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest.to_dict(), handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        return manifest
    except BaseException:
        # The partially written snapshot remains available for diagnosis; no
        # caller data is removed or repaired after an interrupted capture.
        raise


def verify_restore_candidate(
    snapshot_root: Union[os.PathLike, str],
    candidate_root: Union[os.PathLike, str],
    *,
    expected_source_identity: ResourceRef,
    expected_realm_identity: ResourceRef,
    expected_authority: str,
    expected_composition: Sequence[str],
    expected_composition_digest: str,
    expected_schema_fingerprint: str = SCHEMA_FINGERPRINT,
) -> RestoreCandidate:
    """Verify a snapshot in a fresh root, leaving failures inspectable."""
    snapshot = Path(snapshot_root)
    candidate = Path(candidate_root)
    snapshot_identity = _directory_identity(snapshot, SnapshotValidationError)
    manifest = _manifest_at(snapshot)
    _validate_expectations(
        manifest,
        expected_source_identity=expected_source_identity,
        expected_realm_identity=expected_realm_identity,
        expected_authority=expected_authority,
        expected_composition=expected_composition,
        expected_composition_digest=expected_composition_digest,
        expected_schema_fingerprint=expected_schema_fingerprint,
    )
    candidate_parent_identity = _ensure_unused(candidate, RestoreActivationError)
    candidate.mkdir(mode=0o700)
    candidate_identity = _directory_identity(candidate, RestoreActivationError)
    _assert_directory_identity(candidate.parent, candidate_parent_identity, RestoreActivationError)
    source_db = snapshot / "database.sqlite3"
    source_state = _stable_file_state(source_db, SnapshotValidationError)
    if source_state["size"] != manifest.database_size or source_state["digest"] != manifest.database_digest:
        raise SnapshotValidationError("snapshot database bytes/digest do not match the manifest")
    candidate_db = candidate / "database.sqlite3"
    _assert_directory_identity(candidate, candidate_identity, RestoreActivationError)
    _copy_exact(source_db, candidate_db, SnapshotValidationError)
    object_paths = []
    for item in manifest.external_objects:
        digest = item.get("digest")
        relative = item.get("path")
        if digest is None or relative is None:
            continue
        if relative != "objects/" + str(digest):
            raise SnapshotValidationError("external object path is invalid")
        source_object = snapshot / str(relative)
        object_state = _stable_file_state(source_object, SnapshotValidationError)
        if object_state["size"] != int(item.get("size", -1)) or object_state["digest"] != digest:
            raise SnapshotValidationError("external object bytes/digest do not match the manifest")
        destination_object = candidate / "objects" / str(digest)
        _assert_directory_identity(candidate, candidate_identity, RestoreActivationError)
        _copy_exact(source_object, destination_object, SnapshotValidationError)
        object_paths.append(destination_object)

    for item in manifest.journal_files:
        name = item.get("name")
        if name not in ("-journal", "-wal", "-shm"):
            raise SnapshotValidationError("snapshot journal descriptor is invalid")
        journal = snapshot / "journal-evidence" / ("database.sqlite3" + str(name))
        journal_state = _stable_file_state(journal, SnapshotValidationError)
        if int(item.get("size", -1)) != journal_state["size"] or journal_state["digest"] != item.get("digest"):
            raise SnapshotValidationError("snapshot journal bytes/digest do not match the manifest")
        _assert_directory_identity(candidate, candidate_identity, RestoreActivationError)
        _copy_exact(journal, candidate / "journal-evidence" / ("database.sqlite3" + str(name)), SnapshotValidationError)

    # Read-only admission verifies either supported exact composition and
    # performs no migration or repair.
    try:
        domains = tuple(DomainContribution.from_dict(item) for item in manifest.domain_descriptors)
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError("snapshot domain descriptor is invalid") from exc
    _assert_directory_identity(snapshot, snapshot_identity, SnapshotValidationError)
    _assert_directory_identity(candidate.parent, candidate_parent_identity, RestoreActivationError)
    _assert_directory_identity(candidate, candidate_identity, RestoreActivationError)
    _regular_file_stat(candidate_db, SnapshotValidationError)
    checked = Store.open_readonly(candidate_db, authority=expected_authority, expected_domains=domains)
    try:
        _verify_public_read_proof(checked, manifest.read_proof)
    finally:
        checked.close()
    _assert_directory_identity(candidate.parent, candidate_parent_identity, RestoreActivationError)
    _assert_directory_identity(candidate, candidate_identity, RestoreActivationError)
    with (candidate / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest.to_dict(), handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    return RestoreCandidate(candidate, candidate_db, manifest, tuple(object_paths))


def restore_snapshot(
    snapshot_root: Union[os.PathLike, str],
    target_root: Union[os.PathLike, str],
    *,
    expected_source_identity: ResourceRef,
    expected_realm_identity: ResourceRef,
    expected_authority: str,
    expected_composition: Sequence[str],
    expected_composition_digest: str,
    expected_schema_fingerprint: str = SCHEMA_FINGERPRINT,
    candidate_root: Optional[Union[os.PathLike, str]] = None,
) -> RestoreResult:
    """Verify into an unused candidate, then atomically activate if possible."""
    target = Path(target_root)
    candidate_path = Path(candidate_root) if candidate_root is not None else target.with_name(target.name + ".restore-candidate")
    target_parent_identity = _prepare_parent(target, RestoreActivationError)
    candidate = verify_restore_candidate(
        snapshot_root, candidate_path,
        expected_source_identity=expected_source_identity,
        expected_realm_identity=expected_realm_identity,
        expected_authority=expected_authority,
        expected_composition=expected_composition,
        expected_composition_digest=expected_composition_digest,
        expected_schema_fingerprint=expected_schema_fingerprint,
    )
    _assert_directory_identity(target.parent, target_parent_identity, RestoreActivationError)
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        raise RestoreActivationError("activation target exists; preserved it and left candidate for inspection: {}".format(target))
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise RestoreActivationError("activation target appeared; preserved it and left candidate for inspection: {}".format(target)) from exc
    reserved_target_identity = _directory_identity(target, RestoreActivationError)
    try:
        _assert_directory_identity(target.parent, target_parent_identity, RestoreActivationError)
        _assert_directory_identity(target, reserved_target_identity, RestoreActivationError)
        os.replace(str(candidate.root), str(target))
    except BaseException:
        try:
            _assert_directory_identity(target, reserved_target_identity, RestoreActivationError)
            target.rmdir()
        except BaseException:
            pass
        raise
    return RestoreResult(candidate, target)


@dataclass(frozen=True)
class EventFilter:
    """Explicit, serialisable visibility/filter shape for one stream."""

    event_types: Tuple[str, ...] = ()
    visibility: Tuple[str, ...] = ("public",)
    subject: Optional[ResourceRef] = None
    operation: Optional[str] = None

    def __post_init__(self) -> None:
        types = (self.event_types,) if isinstance(self.event_types, str) else tuple(self.event_types)
        visibility = (self.visibility,) if isinstance(self.visibility, str) else tuple(self.visibility)
        if types != tuple(sorted(set(types))) or any(not isinstance(item, str) or not item.strip() for item in types):
            raise CursorScopeError("event_types must be a sorted unique tuple of non-blank strings")
        if not visibility or visibility != tuple(sorted(set(visibility))) or any(not isinstance(item, str) or not item.strip() for item in visibility):
            raise CursorScopeError("visibility must be a sorted non-empty tuple of non-blank strings")
        if self.subject is not None and not isinstance(self.subject, ResourceRef):
            raise TypeError("subject must be a ResourceRef")
        if self.operation is not None and (not isinstance(self.operation, str) or not self.operation.strip()):
            raise CursorScopeError("operation must be a non-blank string")
        object.__setattr__(self, "event_types", types)
        object.__setattr__(self, "visibility", visibility)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_types": list(self.event_types),
            "visibility": list(self.visibility),
            "subject": None if self.subject is None else self.subject.to_dict(),
            "operation": self.operation,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class EventPage:
    events: Tuple[EventEnvelope, ...]
    cursor: str
    next_cursor: Optional[str]
    status: str = "ok"
    gap_from: Optional[int] = None
    gap_to: Optional[int] = None
    watermark: int = 0

    @property
    def complete(self) -> bool:
        return self.next_cursor is None and self.status == "ok"


def _token_encode(payload: Mapping[str, Any]) -> str:
    body = canonical_json(dict(payload)).encode("utf-8")
    envelope = dict(payload, integrity=_sha256_bytes(body))
    encoded = base64.urlsafe_b64encode(canonical_json(envelope).encode("utf-8")).decode("ascii").rstrip("=")
    return encoded


def _token_decode(token: str) -> dict[str, Any]:
    if not isinstance(token, str) or not token:
        raise CursorMalformedError("cursor must be a non-empty opaque string")
    try:
        padded = token + "=" * (-len(token) % 4)
        envelope = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        integrity = envelope.pop("integrity")
        if integrity != _sha256_bytes(canonical_json(envelope).encode("utf-8")):
            raise CursorMalformedError("cursor integrity digest mismatch")
        return envelope
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise CursorMalformedError("cursor is malformed") from exc


class EventCursorReader:
    """Bounded keyset reads from the one authoritative Store event stream."""

    def __init__(self, store: Store, *, cursor_ttl_seconds: int = 3600, clock: Optional[Callable[[], datetime]] = None) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be a Store")
        if isinstance(cursor_ttl_seconds, bool) or not isinstance(cursor_ttl_seconds, int) or cursor_ttl_seconds <= 0:
            raise ValueError("cursor_ttl_seconds must be a positive integer")
        self.store = store
        self.cursor_ttl_seconds = cursor_ttl_seconds
        self.clock = clock or _utc_now

    def _shape(self, stream: str, event_filter: EventFilter, limit: int) -> dict[str, Any]:
        if not isinstance(stream, str) or not stream.strip():
            raise CursorScopeError("stream must be a non-blank string")
        if not isinstance(event_filter, EventFilter):
            raise TypeError("event_filter must be EventFilter")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if event_filter.subject is not None and event_filter.subject.authority != self.store.authority:
            raise CursorScopeError("subject authority does not match the Store")
        # Page size is a read bound, not cursor scope.  Consumers may choose a
        # different bound after a restart without changing visibility shape.
        return {"stream": stream, "filter": event_filter.to_dict(), "filter_digest": event_filter.digest}

    def _new_cursor(self, shape: Mapping[str, Any], after_sequence: int, after_event_id: Optional[str], watermark: int) -> str:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        payload = {
            "format_revision": CURSOR_FORMAT,
            "authority": self.store.authority,
            "stream": shape["stream"],
            "filter": shape["filter"],
            "filter_digest": shape["filter_digest"],
            "after_sequence": after_sequence,
            "after_event_id": after_event_id,
            "watermark": watermark,
            "expires_at": _iso(now + timedelta(seconds=self.cursor_ttl_seconds)),
        }
        return _token_encode(payload)

    def _decode_cursor(self, token: str, shape: Mapping[str, Any]) -> Tuple[int, Optional[str], int]:
        payload = _token_decode(token)
        if payload.get("format_revision") != CURSOR_FORMAT:
            raise CursorMalformedError("unsupported cursor format")
        if payload.get("authority") != self.store.authority or payload.get("stream") != shape["stream"]:
            raise CursorScopeError("cursor authority or stream does not match the request")
        if payload.get("filter_digest") != shape["filter_digest"] or payload.get("filter") != shape["filter"]:
            raise CursorScopeError("cursor filter/visibility shape does not match the request")
        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, str):
            raise CursorMalformedError("cursor expiry is invalid")
        try:
            current = self.clock()
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            expired = current.astimezone(timezone.utc) >= _parse_iso(expires_at)
        except SnapshotValidationError as exc:
            raise CursorMalformedError("cursor expiry is invalid") from exc
        if expired:
            raise CursorExpiredError("cursor has expired")
        after = payload.get("after_sequence")
        watermark = payload.get("watermark")
        if isinstance(after, bool) or not isinstance(after, int) or after < 0 or isinstance(watermark, bool) or not isinstance(watermark, int) or watermark < after:
            raise CursorMalformedError("cursor sequence watermark is invalid")
        event_id = payload.get("after_event_id")
        if event_id is not None and not isinstance(event_id, str):
            raise CursorMalformedError("cursor event identity is invalid")
        return after, event_id, watermark

    def page(
        self,
        stream: str,
        *,
        cursor: Optional[str] = None,
        event_filter: Optional[EventFilter] = None,
        limit: int = 100,
    ) -> EventPage:
        event_filter = event_filter or EventFilter()
        shape = self._shape(stream, event_filter, limit)
        if cursor is None:
            after_sequence, after_event_id = 0, None
        else:
            after_sequence, after_event_id, _ = self._decode_cursor(cursor, shape)
        connection = self.store.connection
        if after_event_id is not None:
            identity_row = connection.execute(
                "SELECT event_id FROM events WHERE store_authority = ? AND stream = ? AND sequence = ?",
                (self.store.authority, stream, after_sequence),
            ).fetchone()
            if identity_row is not None and identity_row[0] != after_event_id:
                raise CursorScopeError("cursor event identity does not match the authoritative stream")
        max_row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE store_authority = ? AND stream = ?",
            (self.store.authority, stream),
        ).fetchone()
        watermark = int(max_row[0] if max_row else 0)
        where = ["store_authority = ?", "stream = ?", "sequence > ?", "sequence <= ?"]
        params: list[Any] = [self.store.authority, stream, after_sequence, watermark]
        if event_filter.event_types:
            where.append("event_type IN ({})".format(",".join("?" for _ in event_filter.event_types)))
            params.extend(event_filter.event_types)
        if event_filter.subject is not None:
            where.extend(["subject_authority = ?", "subject_kind = ?", "subject_id = ?"])
            params.extend([event_filter.subject.authority, event_filter.subject.kind, event_filter.subject.id])
        if event_filter.operation is not None:
            where.append("operation = ?")
            params.append(event_filter.operation)
        visibility_terms = ",".join("?" for _ in event_filter.visibility)
        where.append("COALESCE(json_extract(effects_json, '$.visibility'), 'public') IN ({})".format(visibility_terms))
        params.extend(event_filter.visibility)
        rows = connection.execute(
            "SELECT * FROM events WHERE " + " AND ".join(where) + " ORDER BY sequence ASC LIMIT ?",
            tuple(params + [limit + 1]),
        ).fetchall()
        # A visibility filter must not turn deliberately hidden events into a
        # false sequence gap.  Gap detection is against the authoritative
        # stream; the returned rows are the caller's accessible projection.
        raw_first = connection.execute(
            "SELECT MIN(sequence) FROM events WHERE store_authority = ? AND stream = ? AND sequence > ? AND sequence <= ?",
            (self.store.authority, stream, after_sequence, watermark),
        ).fetchone()[0]
        status = "ok"
        gap_from = gap_to = None
        if raw_first is not None and int(raw_first) > after_sequence + 1:
            status = "gap"
            gap_from, gap_to = after_sequence + 1, int(raw_first) - 1
        selected = rows[:limit]
        event_values = tuple(self.store._event_from_row(row) for row in selected)
        last_sequence = event_values[-1].sequence if event_values else after_sequence
        last_event_id = event_values[-1].event_id if event_values else after_event_id
        post_cursor = self._new_cursor(shape, last_sequence, last_event_id, watermark)
        next_cursor = post_cursor if len(rows) > limit else None
        return EventPage(event_values, post_cursor, next_cursor, status, gap_from, gap_to, watermark)

    def catch_up(self, stream: str, *, cursor: Optional[str] = None, event_filter: Optional[EventFilter] = None, limit: int = 100) -> EventPage:
        """Alias emphasizing restart/disconnect recovery semantics."""
        return self.page(stream, cursor=cursor, event_filter=event_filter, limit=limit)


@dataclass(frozen=True)
class RecoveryToken:
    source_identity: ResourceRef
    realm_identity: ResourceRef
    authority: str
    epoch: int
    fence: int
    token: str
    operation_ref: ResourceRef
    status: str = "active"
    result_ref: Optional[ResourceRef] = None
    result: Mapping[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identity": self.source_identity.to_dict(), "realm_identity": self.realm_identity.to_dict(),
            "authority": self.authority, "epoch": self.epoch, "fence": self.fence, "token": self.token,
            "operation_ref": self.operation_ref.to_dict(), "status": self.status,
            "result_ref": None if self.result_ref is None else self.result_ref.to_dict(),
            "result": dict(self.result or {}),
        }


@dataclass(frozen=True)
class EpochState:
    source_identity: ResourceRef
    realm_identity: ResourceRef
    authority: str
    epoch: int
    tokens: Tuple[RecoveryToken, ...]
    version: int
    current_revision: Optional[str]


@dataclass(frozen=True)
class SettlementRecord:
    operation_ref: ResourceRef
    token: RecoveryToken
    result_ref: Optional[ResourceRef]
    result: Mapping[str, Any]


def _default_actor(actor: Optional[AuthenticatedActor]) -> AuthenticatedActor:
    return actor or AuthenticatedActor("neutral-kernel", "recovery", "recovery")


class RecoveryManager:
    """Atomically advance epochs and fence stale runtime/session tokens."""

    def __init__(self, store: Store, source_identity: ResourceRef, realm_identity: ResourceRef, *, actor: Optional[AuthenticatedActor] = None, clock: Optional[Callable[[], datetime]] = None) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be a Store")
        if not isinstance(source_identity, ResourceRef) or not isinstance(realm_identity, ResourceRef):
            raise TypeError("source_identity and realm_identity must be ResourceRef values")
        self.store = store
        self.source_identity = source_identity
        self.realm_identity = realm_identity
        self.actor = _default_actor(actor)
        self.clock = clock or _utc_now
        self.state_ref = ResourceRef(store.authority, RECOVERY_KIND, realm_identity.id)

    def _state(self) -> Optional[EpochState]:
        identity = self.store.get_identity(self.state_ref)
        return None if identity is None else self._state_from_identity(identity)

    def _state_from_identity(self, identity: Any) -> EpochState:
        payload = identity.payload
        if payload.get("record_type") != RECOVERY_KIND:
            raise RecoveryError("recovery identity is not an admitted epoch record")
        source = _ref(payload["source_identity"])
        realm = _ref(payload["realm_identity"])
        if source != self.source_identity or realm != self.realm_identity:
            raise TargetMismatchError("recovery source/realm identity does not match this manager")
        tokens = tuple(self._token_from_dict(item) for item in payload.get("tokens", []))
        return EpochState(source, realm, payload["authority"], int(payload["epoch"]), tokens, int(identity.version), identity.ref.revision)

    def _token_from_dict(self, value: Mapping[str, Any]) -> RecoveryToken:
        result_ref = value.get("result_ref")
        return RecoveryToken(_ref(value["source_identity"]), _ref(value["realm_identity"]), str(value["authority"]), int(value["epoch"]), int(value["fence"]), str(value["token"]), _ref(value["operation_ref"]), str(value.get("status", "active")), _ref(result_ref) if result_ref else None, dict(value.get("result", {})))

    def _payload(self, epoch: int, tokens: Iterable[RecoveryToken]) -> dict[str, Any]:
        return {
            "record_type": RECOVERY_KIND, "schema_revision": RECOVERY_SCHEMA_REVISION,
            "source_identity": self.source_identity.to_dict(), "realm_identity": self.realm_identity.to_dict(),
            "authority": self.store.authority, "epoch": epoch, "tokens": [token.to_dict() for token in tokens],
        }

    def _write_state(self, previous: Optional[EpochState], payload: Mapping[str, Any], *, request_key: str, transaction: Optional[Transaction] = None) -> EpochState:
        version = 0 if previous is None else previous.version
        target = self.state_ref if previous is None else ResourceRef(self.store.authority, RECOVERY_KIND, self.realm_identity.id, previous.current_revision)
        digest = _sha256_json({"request_key": request_key, "payload": dict(payload)})
        envelope = CommandEnvelope(
            "recovery.state", RECOVERY_SCHEMA_REVISION, target,
            TransactionContext(self.actor, request_key, digest, expected_revision=previous.current_revision if previous else None, expected_version=version),
            dict(payload),
        )
        self.store.mutate(
            envelope, event_type="recovery.state.changed",
            result_ref=ResourceRef(self.store.authority, RECOVERY_KIND, self.realm_identity.id, "rev-{}".format(version + 1)),
            effects={"record_type": RECOVERY_KIND, "epoch": payload["epoch"], "tokens": payload["tokens"], "source_identity": payload["source_identity"], "realm_identity": payload["realm_identity"], "version": version + 1},
            stream="recovery:" + self.realm_identity.id, transaction=transaction,
        )
        identity = self.store.get_identity(self.state_ref)
        if identity is None:
            raise RecoveryError("recovery state did not persist")
        return self._state_from_identity(identity)

    def begin_epoch(self, boot_token: str, *, request_key: Optional[str] = None) -> EpochState:
        if not isinstance(boot_token, str) or not boot_token.strip():
            raise RecoveryError("boot_token is required")
        previous = self._state()
        epoch = 1 if previous is None else previous.epoch + 1
        retired = tuple(RecoveryToken(token.source_identity, token.realm_identity, token.authority, token.epoch, token.fence, token.token, token.operation_ref, "retired", token.result_ref, token.result) for token in (previous.tokens if previous else ()))
        key = request_key or "recovery:epoch:{}".format(boot_token)
        return self._write_state(previous, self._payload(epoch, retired), request_key=key)

    def current(self) -> Optional[EpochState]:
        return self._state()

    def issue_token(self, operation_ref: ResourceRef, *, token: Optional[str] = None, request_key: Optional[str] = None) -> RecoveryToken:
        if not isinstance(operation_ref, ResourceRef):
            raise TypeError("operation_ref must be a ResourceRef")
        state = self._state()
        if state is None:
            raise RecoveryError("begin_epoch must precede token issuance")
        active_fences = [item.fence for item in state.tokens]
        value = token or hashlib.sha256((self.realm_identity.to_json() + operation_ref.to_json() + str(state.epoch) + str(max(active_fences or [0]) + 1)).encode("utf-8")).hexdigest()
        issued = RecoveryToken(self.source_identity, self.realm_identity, self.store.authority, state.epoch, max(active_fences or [0]) + 1, value, operation_ref)
        updated = state.tokens + (issued,)
        next_state = self._write_state(state, self._payload(state.epoch, updated), request_key=request_key or "recovery:token:{}".format(value))
        return next(item for item in next_state.tokens if item.token == value)

    def retire_token(self, token: RecoveryToken, *, request_key: Optional[str] = None) -> RecoveryToken:
        self.validate_token(token)
        state = self._state()
        assert state is not None
        updated = tuple(RecoveryToken(item.source_identity, item.realm_identity, item.authority, item.epoch, item.fence, item.token, item.operation_ref, "retired" if item.token == token.token else item.status, item.result_ref, item.result) for item in state.tokens)
        next_state = self._write_state(state, self._payload(state.epoch, updated), request_key=request_key or "recovery:retire:{}".format(token.token))
        return next(item for item in next_state.tokens if item.token == token.token)

    def validate_token(self, token: RecoveryToken) -> RecoveryToken:
        if not isinstance(token, RecoveryToken):
            raise TypeError("token must be RecoveryToken")
        state = self._state()
        if state is None:
            raise StaleTokenError("no active recovery epoch")
        found = next((item for item in state.tokens if item.token == token.token), None)
        if found is None:
            raise UnknownTokenError("token is not retained in durable recovery state")
        if found != token or found.status != "active" or found.epoch != state.epoch or found.authority != self.store.authority:
            raise StaleTokenError("token is retired or belongs to an older recovery epoch")
        return found

    def settle(
        self,
        token: RecoveryToken,
        *,
        logical_request_key: str,
        result_ref: Optional[ResourceRef] = None,
        result: Optional[Mapping[str, Any]] = None,
        apply: Optional[Callable[[], Any]] = None,
    ) -> SettlementRecord:
        """Validate the fence before invoking an optional external mutation.

        ``apply`` is an adapter/CAS hook.  A stale token raises before it is
        called.  The hook's outcome is not treated as exactly-once execution;
        the durable settlement below is the common observable record.
        """
        if not isinstance(logical_request_key, str) or not logical_request_key.strip():
            raise RecoveryError("logical_request_key is required")
        if result_ref is not None and not isinstance(result_ref, ResourceRef):
            raise TypeError("result_ref must be a ResourceRef")
        result_value = dict(result or {})
        with self.store.transaction() as tx:
            state = self._state()
            if state is None:
                raise StaleTokenError("no active recovery epoch")
            found = next((item for item in state.tokens if item.token == token.token), None)
            if found is None:
                raise UnknownTokenError("token is not retained in durable recovery state")
            if found != token or found.status != "active" or found.epoch != state.epoch:
                raise StaleTokenError("stale settlement rejected before result mutation")
            if apply is not None:
                apply()
            updated = tuple(RecoveryToken(item.source_identity, item.realm_identity, item.authority, item.epoch, item.fence, item.token, item.operation_ref, "settled" if item.token == token.token else item.status, result_ref if item.token == token.token else item.result_ref, result_value if item.token == token.token else item.result) for item in state.tokens)
            committed_state = self._write_state(state, self._payload(state.epoch, updated), request_key=logical_request_key, transaction=tx)
            committed_token = next(item for item in committed_state.tokens if item.token == token.token)
            return SettlementRecord(committed_token.operation_ref, committed_token, result_ref, result_value)

    def retain_unknown_operation(self, operation_ref: ResourceRef, details: Optional[Mapping[str, Any]] = None) -> Any:
        if not isinstance(operation_ref, ResourceRef):
            raise TypeError("operation_ref must be a ResourceRef")
        if operation_ref.authority != self.store.authority:
            raise TargetMismatchError("unknown operation must belong to this Store authority")
        payload = {"record_type": "unknown-operation", "schema_revision": RECOVERY_SCHEMA_REVISION, "operation_ref": operation_ref.to_dict(), "details": dict(details or {})}
        existing = self.store.get_identity(ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id))
        if existing is not None:
            return existing
        key = "recovery:unknown:{}".format(operation_ref.id)
        digest = _sha256_json(payload)
        envelope = CommandEnvelope("recovery.retain_unknown", RECOVERY_SCHEMA_REVISION, ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id), TransactionContext(self.actor, key, digest, expected_version=0), payload)
        self.store.mutate(envelope, event_type="recovery.operation.unknown", result_ref=ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id, "rev-1"), effects=payload, stream="recovery:" + self.realm_identity.id)
        return self.store.get_identity(ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id))


@dataclass(frozen=True)
class IntervalState:
    interval_ref: ResourceRef
    interval_seconds: int
    anchor: str
    last_slot: int
    in_flight: Optional[str]
    version: int
    current_revision: Optional[str]


@dataclass(frozen=True)
class IntervalDecision:
    due: bool
    request_id: Optional[str]
    missed_intervals: int
    in_flight: bool
    state: IntervalState


class IntervalController:
    """Persisted arbitrary interval gate with coalescing and one in-flight request."""

    def __init__(self, store: Store, interval_ref: ResourceRef, interval_seconds: int, *, actor: Optional[AuthenticatedActor] = None, clock: Optional[Callable[[], datetime]] = None) -> None:
        if not isinstance(store, Store) or not isinstance(interval_ref, ResourceRef):
            raise TypeError("store and interval_ref are required")
        if interval_ref.authority != store.authority or interval_ref.kind != INTERVAL_KIND or interval_ref.revision is not None:
            raise TargetMismatchError("interval_ref must be an unpinned attention-interval identity in this Store")
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive integer")
        self.store = store
        self.interval_ref = interval_ref
        self.interval_seconds = interval_seconds
        self.actor = _default_actor(actor)
        self.clock = clock or _utc_now

    def _from_identity(self, identity: Any) -> IntervalState:
        payload = identity.payload
        if payload.get("record_type") != INTERVAL_KIND or int(payload["interval_seconds"]) != self.interval_seconds:
            raise RecoveryError("persisted interval configuration does not match this controller")
        return IntervalState(self.interval_ref, self.interval_seconds, str(payload["anchor"]), int(payload["last_slot"]), payload.get("in_flight"), int(identity.version), identity.ref.revision)

    def state(self) -> Optional[IntervalState]:
        identity = self.store.get_identity(self.interval_ref)
        return None if identity is None else self._from_identity(identity)

    def _payload(self, anchor: str, last_slot: int, in_flight: Optional[str]) -> dict[str, Any]:
        return {"record_type": INTERVAL_KIND, "schema_revision": INTERVAL_SCHEMA_REVISION, "interval_seconds": self.interval_seconds, "anchor": anchor, "last_slot": last_slot, "in_flight": in_flight}

    def _write(self, prior: Optional[IntervalState], payload: Mapping[str, Any], key: str) -> IntervalState:
        version = 0 if prior is None else prior.version
        target = self.interval_ref if prior is None else ResourceRef(self.store.authority, INTERVAL_KIND, self.interval_ref.id, prior.current_revision)
        digest = _sha256_json({"key": key, "payload": dict(payload)})
        envelope = CommandEnvelope("attention.interval", INTERVAL_SCHEMA_REVISION, target, TransactionContext(self.actor, key, digest, expected_revision=prior.current_revision if prior else None, expected_version=version), dict(payload))
        self.store.mutate(envelope, event_type="attention.interval.changed", result_ref=ResourceRef(self.store.authority, INTERVAL_KIND, self.interval_ref.id, "rev-{}".format(version + 1)), effects={**payload, "version": version + 1}, stream="attention:" + self.interval_ref.id)
        identity = self.store.get_identity(self.interval_ref)
        if identity is None:
            raise RecoveryError("interval state did not persist")
        return self._from_identity(identity)

    def start(self, *, anchor: Optional[datetime] = None, request_key: str = "attention.interval.start") -> IntervalState:
        prior = self.state()
        if prior is not None:
            return prior
        initial = anchor or self.clock()
        return self._write(None, self._payload(_iso(initial), 0, None), request_key)

    def poll(self, *, now: Optional[datetime] = None) -> IntervalDecision:
        state = self.state() or self.start()
        current = now or self.clock()
        elapsed = (current.astimezone(timezone.utc) - _parse_iso(state.anchor)).total_seconds()
        slot = int(elapsed // self.interval_seconds)
        if slot <= state.last_slot:
            return IntervalDecision(False, state.in_flight, 0, state.in_flight is not None, state)
        if state.in_flight is not None:
            return IntervalDecision(True, state.in_flight, max(0, slot - state.last_slot - 1), True, state)
        request_id = hashlib.sha256((self.interval_ref.to_json() + ":" + str(slot)).encode("utf-8")).hexdigest()
        try:
            next_state = self._write(state, self._payload(state.anchor, slot, request_id), "attention.interval.request:{}".format(request_id))
        except VersionConflictError:
            current = self.state() or self.start()
            return IntervalDecision(current.in_flight is not None, current.in_flight, 0, current.in_flight is not None, current)
        return IntervalDecision(True, request_id, max(0, slot - state.last_slot - 1), False, next_state)

    def complete(self, request_id: str) -> IntervalState:
        if not isinstance(request_id, str) or not request_id.strip():
            raise RecoveryError("request_id is required")
        state = self.state() or self.start()
        if state.in_flight is None:
            return state
        if state.in_flight != request_id:
            # A late/duplicate host acknowledgement is a harmless hint.  It
            # must not clear or replace the request that is actually in flight.
            return state
        return self._write(state, self._payload(state.anchor, state.last_slot, None), "attention.interval.complete:{}".format(request_id))


__all__ = [
    "SNAPSHOT_FORMAT", "CURSOR_FORMAT", "RECOVERY_KIND", "INTERVAL_KIND",
    "RecoveryError", "SnapshotError", "SnapshotValidationError", "RestoreActivationError",
    "CursorError", "CursorMalformedError", "CursorScopeError", "CursorExpiredError",
    "StaleTokenError", "UnknownTokenError", "SnapshotManifest", "RestoreCandidate", "RestoreResult",
    "create_snapshot", "verify_restore_candidate", "restore_snapshot", "EventFilter", "EventPage", "EventCursorReader",
    "RecoveryToken", "EpochState", "SettlementRecord", "RecoveryManager", "IntervalState", "IntervalDecision", "IntervalController",
]


# Closed-owner migration custody is the same durable writer boundary used by
# Recovery and Store. It is not a boolean supplied by a pack/client.
from contextlib import contextmanager

_CLOSED_OWNER_CUSTODY_TOKEN = object()


class ClosedOwnerCustody:
    """An active exclusive lock on a closed durable owner installation."""
    def __init__(self, path, authority, connection, domains, schema_revision, *, _token=None):
        if _token is not _CLOSED_OWNER_CUSTODY_TOKEN:
            raise SnapshotError("closed-owner custody is acquired through Recovery's maintained context")
        self.path, self.authority, self.connection = path, authority, connection
        self.domains, self.schema_revision = domains, schema_revision
        self._active = True
        self.source_file_state = _stable_file_state(path)

    def require_active(self):
        if not self._active:
            raise SnapshotError("closed-owner custody is no longer active")


@contextmanager
def closed_owner_custody(path, *, authority, expected_domains=()):
    """Fence existing owners, verify exact schema and settle SQLite sidecars.

    The host must stop its service before entry. The actual Store lock enforces
    that condition; a live owner causes WriterBusyError before any copying.
    Domain/provider work is never invoked by custody or migration.
    """
    from .schema import SUPPORTED_SCHEMAS
    path = Path(os.path.abspath(os.fspath(path)))
    _regular_file_stat(path)
    parent = _directory_identity(path.parent)
    lock_fd = Store._acquire_lock(str(path))
    connection, custody = None, None
    try:
        _assert_directory_identity(path.parent, parent)
        connection = Store._connect(str(path))
        metadata = dict(connection.execute("SELECT key, value FROM store_metadata"))
        revision = metadata.get("schema_revision")
        if revision not in SUPPORTED_SCHEMAS:
            raise SnapshotValidationError("closed owner has an unsupported composition")
        domains = Store._verify(connection, authority, expected_domains, schema_revision=revision)
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SnapshotValidationError("closed owner failed SQLite integrity verification")
        # Use Recovery's established stable checkpoint boundary before backup
        # or filesystem switch. Never carry a stale WAL across replacement.
        if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint[0] != 0:
                raise SnapshotError("closed-owner WAL checkpoint is busy")
        if str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower() != "delete":
            raise SnapshotError("closed owner could not settle journal mode")
        custody = ClosedOwnerCustody(path, authority, connection, tuple(domains.values()), revision,
                                    _token=_CLOSED_OWNER_CUSTODY_TOKEN)
        yield custody
    finally:
        if custody is not None:
            custody._active = False
            # Switch replaces the connection while retaining the same custody.
            custody.connection.close()
        elif connection is not None:
            connection.close()
        Store._release_lock(lock_fd)


def backup_closed_owner(custody, target, *, progress=None):
    """Consistent Recovery backup under exclusive closed-owner custody."""
    if not isinstance(custody, ClosedOwnerCustody):
        raise TypeError("backup requires Recovery closed-owner custody")
    custody.require_active()
    target = Path(target)
    _ensure_unused(target, SnapshotError)
    destination = sqlite3.connect(str(target))
    try:
        custody.connection.backup(destination, pages=128, progress=progress)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SnapshotValidationError("closed-owner backup failed integrity check")
    finally:
        destination.close()
    with target.open("rb") as handle:
        os.fsync(handle.fileno())
    return _file_digest(target)


def storage_diagnostics_closed_owner(custody, *, group_limit=32, progress=None):
    """Bounded aggregate storage accounting; no payload values or JSON hydration.

    Trusted maintenance only. Custody settles SQLite sidecars before inspection;
    these queries never modify records or reclaim pages. dbstat allocation is
    logical SQLite page ownership, not unique physical CoW block allocation.
    """
    if not isinstance(custody, ClosedOwnerCustody):
        raise TypeError("diagnostics require Recovery closed-owner custody")
    custody.require_active()
    if type(group_limit) is not int or not 1 <= group_limit <= 64:
        raise ValueError("diagnostic group limit must be 1..64")
    conn = custody.connection
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    if progress:
        progress({"phase":"pages", "source_bytes":_regular_file_stat(custody.path).st_size,
                  "page_size":page_size,"page_count":pages,"freelist_pages":free_pages,
                  "freelist_bytes":free_pages*page_size})
    tables = tuple(row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
    def quoted(name):
        return '"' + name.replace('"', '""') + '"'
    sizes = []
    for table in tables:
        columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(" + quoted(table) + ")"))
        large = tuple(name for name in columns if name.endswith("_json"))
        expressions = ["count(*)"]
        for name in large:
            expr = "length(CAST(" + quoted(name) + " AS BLOB))"
            expressions += ["coalesce(sum(" + expr + "),0)", "coalesce(max(" + expr + "),0)",
                            "coalesce(sum(" + expr + ">=1048576),0)"]
        row = conn.execute("SELECT " + ",".join(expressions) + " FROM " + quoted(table)).fetchone()
        sizes.append({"table": table, "rows": row[0], "json_columns": [
            {"column": name, "bytes": row[1+3*i], "max_bytes": row[2+3*i],
             "rows_at_least_1MiB": row[3+3*i]} for i, name in enumerate(large)]})
        if progress:
            progress({"phase":"table", **sizes[-1]})
    groups = {}
    for table, label, payload in (("identities", "kind", "payload_json"), ("events", "event_type", "effects_json")):
        count = conn.execute("SELECT count(DISTINCT " + label + ") FROM " + table).fetchone()[0]
        rows = conn.execute("SELECT " + label + ",count(*),sum(length(CAST(" + payload +
            " AS BLOB))),max(length(CAST(" + payload + " AS BLOB))) FROM " + table +
            " GROUP BY " + label + " ORDER BY 3 DESC," + label + " LIMIT ?", (group_limit,))
        groups[table] = {"total_groups": count, "truncated": count > group_limit, "groups": [
            {"kind": row[0], "rows": row[1], "payload_bytes": row[2], "max_payload_bytes": row[3]} for row in rows]}
    try:
        objects = [{"name": r[0], "pages": r[1], "allocated_bytes": r[2],
                    "payload_bytes": r[3], "unused_bytes": r[4]} for r in conn.execute(
            "SELECT name,count(*),sum(pgsize),sum(payload),sum(unused) FROM dbstat GROUP BY name ORDER BY 3 DESC LIMIT 65")]
        allocation = {"state": "available", "objects": objects[:64], "truncated":len(objects)>64}
    except sqlite3.OperationalError as error:
        allocation = {"state": "unavailable", "reason": str(error)}
    if progress:
        progress({"phase":"allocation", **allocation})
    state = _regular_file_stat(custody.path)
    return {"schema": "fnd.closed-owner-storage-diagnostics.v1", "schema_revision": custody.schema_revision,
            "source": str(custody.path), "source_bytes": state.st_size,
            "file_allocated_bytes": state.st_blocks * 512, "page_size": page_size,
            "page_count": pages, "freelist_pages": free_pages, "freelist_bytes": free_pages * page_size,
            "tables": sizes, "payload_groups": groups, "page_allocation": allocation,
            "payload_content_returned": False, "records_modified": False,
            "physical_unique_CoW_bytes": "unavailable", "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0]}


def _clonefile(source, target):
    """Darwin's explicit independent CoW clone; never hardlink or copy fallback."""
    import ctypes
    import sys
    if sys.platform != 'darwin':
        raise SnapshotError('independent clonefile is unavailable on this platform')
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    try:
        call = libc.clonefile
    except AttributeError as error:
        raise SnapshotError('independent clonefile is unavailable') from error
    call.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
    call.restype = ctypes.c_int
    if call(os.fsencode(source), os.fsencode(target), 0x0001) != 0:
        number = ctypes.get_errno()
        raise SnapshotError('independent clonefile refused: ' + os.strerror(number))


_CLONE_QUALIFICATION_TOKEN = object()


class FilesystemCloneQualification:
    """Ephemeral proof of successful independent clone semantics on one directory."""
    def __init__(self, parent, identity, evidence, *, _token=None):
        if _token is not _CLONE_QUALIFICATION_TOKEN:
            raise SnapshotError('clone qualification must use maintained filesystem probe')
        self.parent, self.identity, self.evidence = parent, identity, evidence

    def require_directory(self, parent):
        if Path(parent).absolute() != self.parent:
            raise SnapshotError('clone qualification belongs to another directory')
        _assert_directory_identity(self.parent, self.identity)


def qualify_clone_filesystem(parent):
    """Small disposable filesystem probe; no Store access or deployment effect.

    clonefile success attests CoW support. st_blocks reports file allocation,
    not unique shared blocks; free-space deltas are observations, not guarantees.
    """
    import tempfile
    parent = Path(parent).absolute()
    identity = _directory_identity(parent)
    free_before = shutil.disk_usage(parent).free
    with tempfile.TemporaryDirectory(prefix='.fnd-clone-probe-', dir=parent) as folder:
        source, target = Path(folder)/'source', Path(folder)/'clone'
        with source.open('wb') as handle:
            handle.write(os.urandom(65536))
            handle.flush(); os.fsync(handle.fileno())
        _clonefile(source, target)
        a, b = _regular_file_stat(source), _regular_file_stat(target)
        if a.st_dev != b.st_dev or a.st_ino == b.st_ino or b.st_nlink != 1:
            raise SnapshotError('clone is not an independent file on the same filesystem')
        before = _file_digest(source)
        if _file_digest(target) != before:
            raise SnapshotError('clone probe bytes differ')
        with target.open('r+b') as handle:
            handle.write(b'independent clone probe'); handle.flush(); os.fsync(handle.fileno())
        if _file_digest(source) != before or _file_digest(target) == before:
            raise SnapshotError('clone probe write aliases source')
        _fsync_directory(Path(folder))
        free_during = shutil.disk_usage(parent).free
        evidence = {'method':'darwin-clonefile', 'independent_inode':True,
                    'independent_write_verified':True, 'probe_bytes':65536,
                    'source_allocated_bytes':a.st_blocks*512, 'clone_allocated_bytes':b.st_blocks*512,
                    'free_bytes_before':free_before, 'free_bytes_during':free_during,
                    'unique_shared_allocation':'not measurable through st_blocks', 'full_copy_fallback':False}
    _fsync_directory(parent)
    _assert_directory_identity(parent, identity)
    return FilesystemCloneQualification(parent, identity, evidence, _token=_CLONE_QUALIFICATION_TOKEN)


def _fsync_directory(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def clone_closed_owner(custody, target, *, qualification):
    """Durable independent backup clone after Recovery's settled SQLite boundary."""
    if not isinstance(custody, ClosedOwnerCustody):
        raise TypeError('clone requires actual Recovery closed-owner custody')
    custody.require_active()
    if not isinstance(qualification, FilesystemCloneQualification):
        raise SnapshotError('clone requires maintained filesystem qualification')
    target = Path(target).absolute()
    qualification.require_directory(custody.path.parent)
    if target.parent != custody.path.parent:
        raise SnapshotError('clone backup must share the qualified source directory')
    _ensure_unused(target, SnapshotError)
    if str(custody.connection.execute('PRAGMA journal_mode').fetchone()[0]).lower() != 'delete':
        raise SnapshotError('clone requires settled DELETE journaling')
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(custody.path)+suffix)
        if sidecar.exists() and _regular_file_stat(sidecar).st_size:
            raise SnapshotError('clone source has an unsettled SQLite sidecar')
    before = _stable_file_state(custody.path)
    if not _same_file_state(before, custody.source_file_state):
        raise SnapshotError('clone source changed under closed custody')
    _clonefile(custody.path, target)
    a, b = _regular_file_stat(custody.path), _regular_file_stat(target)
    if a.st_dev != b.st_dev or a.st_ino == b.st_ino or b.st_nlink != 1 or a.st_size != b.st_size:
        raise SnapshotError('clone backup is not an exact independent file')
    if _file_digest(target) != before['digest']:
        raise SnapshotError('clone backup bytes differ from settled source')
    with target.open('rb') as handle:
        os.fsync(handle.fileno())
    _fsync_directory(target.parent)
    if not _same_file_state(_stable_file_state(custody.path), before):
        raise SnapshotError('clone source changed during backup')
    return {'method':'darwin-clonefile', 'source_bytes':a.st_size,
            'backup_allocated_bytes':b.st_blocks*512, 'independent_inode':True,
            'source_digest':before['digest'], 'backup_digest_verified':True,
            'full_copy_fallback':False, 'qualification':qualification.evidence}
