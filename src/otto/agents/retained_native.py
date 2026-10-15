"""Producer-side native body references: each host transcript is stored once.

A Due or result record keeps a small carrier (digest, byte length, media type,
origin) in place of every large native body; the body lives once, addressed by
its sha256, outside the Store's tables. Two backends hold the bytes:

* the Evidence owner (``RetainedNativeBodies(evidence, actor)``), which the
  Codex operating service composes; and
* ``FileBodyStore`` (``RetainedNativeBodies.on_files``), a private
  content-addressed directory that needs no Evidence pack, no schema change and
  no Astrid discovery. It is what the Otto host service composes.

Carriers say which backend holds them, so a reader built on either backend
resolves what it can and refuses the rest. No historical record is rewritten.
Issuing this capability is an explicit trusted host composition choice; legacy
ports retain their existing readers, and inline (pre-reference) bodies read
exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "otto.retained-native-body.v1"
MAX_BODY_BYTES = 64 * 1024 * 1024
# The file store has no per-body metadata rows to bound; a turn larger than any seen (34 MB) still saves.
FILE_MAX_BODY_BYTES = 256 * 1024 * 1024
INLINE_BYTES = 4096


FILE_STORE = "file"
MEDIA_TYPE = "application/json"


_PURGED = object()


class BodyPurged(ValueError):
    """The body was reclaimed with its project; the record keeps only the reference."""


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class FileBodyStore:
    """Content-addressed native bodies in a private directory, scoped per project.

    Layout: ``<root>/p-<project key>/<sha[:2]>/<sha256>`` holds the zlib-compressed
    canonical JSON bytes. ``put`` returns only after the bytes are fsynced and
    renamed into place and the containing directories are fsynced, so a record
    that references the digest can never commit before its body is durable. A
    crash between ``put`` and the record's commit leaves at worst an unreferenced
    file. Files are immutable; the same body is stored once per project.

    ``purge_project`` reclaims a project's bodies: a durable marker under
    ``<root>/purged/`` is written first, so a later read distinguishes a reclaimed
    body (``BodyPurged``) from a lost one.
    """

    def __init__(self, root: Any) -> None:
        self.root = Path(root)
        for path in (self.root, self.root / "purged"):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not os.path.isdir(self.root) or os.path.islink(self.root) or info.st_uid != os.geteuid():
            raise PermissionError("native body root must be a directory owned by this account")
        if info.st_mode & 0o077:
            os.chmod(self.root, 0o700)

    @staticmethod
    def project_key(project_ref: Mapping[str, Any]) -> str:
        identity = [project_ref.get("authority"), project_ref.get("kind"), project_ref.get("id")]
        return "p-" + hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()[:32]

    def _path(self, project_ref: Mapping[str, Any], sha: str) -> Path:
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("native body digest must be a lowercase sha256")
        return self.root / self.project_key(project_ref) / sha[:2] / sha

    def exists(self, project_ref: Mapping[str, Any], sha: str) -> bool:
        return self._path(project_ref, sha).is_file()

    def purged(self, project_ref: Mapping[str, Any]) -> bool:
        return (self.root / "purged" / self.project_key(project_ref)).exists()

    def put(self, project_ref: Mapping[str, Any], sha: str, raw: bytes) -> None:
        path = self._path(project_ref, sha)
        if path.is_file():
            return
        for directory in (path.parent.parent, path.parent):
            made = not directory.exists()
            directory.mkdir(mode=0o700, exist_ok=True)
            if made:
                _fsync_dir(directory.parent)
        fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(zlib.compress(raw, 1))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        _fsync_dir(path.parent)

    def get(self, project_ref: Mapping[str, Any], sha: str, length: int) -> bytes:
        path = self._path(project_ref, sha)
        try:
            stored = path.read_bytes()
        except FileNotFoundError:
            if self.purged(project_ref):
                raise BodyPurged("retained native body was reclaimed with its project") from None
            raise ValueError("retained native body unavailable") from None
        try:
            inflater = zlib.decompressobj()
            raw = inflater.decompress(stored, length + 1)     # never inflate past the declared size
        except zlib.error:
            raise ValueError("retained native body changed") from None
        if len(raw) != length or hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("retained native body changed")
        return raw

    def check(self, project_ref: Mapping[str, Any], sha: str) -> str:
        """``present`` or ``purged``; anything else raises. Reads no body bytes."""
        if self.exists(project_ref, sha):
            return "present"
        if self.purged(project_ref):
            return "purged"
        raise ValueError("retained native body unavailable")

    def inventory(self, project_ref: Mapping[str, Any]) -> dict[str, int]:
        directory = self.root / self.project_key(project_ref)
        files = bytes_ = 0
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_file() and not path.name.startswith(".tmp-"):
                    files += 1
                    bytes_ += path.stat().st_size
        return {"files": files, "bytes": bytes_}

    def entries(self, project_ref: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Every body file of one project: ``{"key": "p-<key>/<sha[:2]>/<sha>", "bytes": n}``."""
        key = self.project_key(project_ref)
        directory = self.root / key
        rows = []
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if path.is_file() and not path.name.startswith(".tmp-"):
                    rows.append({"key": str(path.relative_to(self.root)), "bytes": path.stat().st_size})
        return rows

    def purge_project(self, project_ref: Mapping[str, Any]) -> dict[str, Any]:
        """Delete every body of one project. Idempotent; records keep their carriers."""
        key = self.project_key(project_ref)
        before = self.inventory(project_ref)
        marker = self.root / "purged" / key
        descriptor = os.open(str(marker), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_dir(marker.parent)
        directory = self.root / key
        if directory.exists():
            doomed = self.root / "purged" / (key + ".deleting-" + str(time.time_ns()))
            os.replace(directory, doomed)
            _fsync_dir(self.root)
            shutil.rmtree(doomed)
        for stale in (self.root / "purged").glob(key + ".deleting-*"):
            shutil.rmtree(stale, ignore_errors=True)
        return {"project_key": key, "purged": True, **before}


class RetainedNativeBodies:
    def __init__(self, evidence: Any, actor: Any, *, files: "FileBodyStore | None" = None) -> None:
        if evidence is None and files is None:
            raise ValueError("a native body backend is required")
        self.evidence, self.actor, self.files = evidence, actor, files

    @classmethod
    def on_files(cls, root: Any, actor: Any) -> "RetainedNativeBodies":
        """Bodies in a private content-addressed directory (no Evidence pack)."""
        return cls(None, actor, files=FileBodyStore(root))

    def project_ref_dict(self, project_ref: Any) -> dict[str, Any]:
        from herzchen.contracts import ResourceRef
        project = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        return {"authority": project.authority, "kind": project.kind, "id": project.id}

    def purge_project(self, project_ref: Any) -> dict[str, Any]:
        if self.files is None:
            raise ValueError("this body capability has no file store to reclaim")
        from herzchen.contracts import ResourceRef
        project = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        return self.files.purge_project({"authority": project.authority, "kind": project.kind, "id": project.id})

    def retain(self, value: Any, *, project_ref: Any, task_ref: Any = None,
               attempt_ref: Any = None) -> dict[str, Any]:
        from herzchen.contracts import ResourceRef
        project = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        project_ref = ResourceRef(project.authority, project.kind, project.id).to_dict()
        task_ref = ResourceRef.from_dict(task_ref).to_dict() if isinstance(task_ref, Mapping) else task_ref
        attempt_ref = ResourceRef.from_dict(attempt_ref).to_dict() if isinstance(attempt_ref, Mapping) else attempt_ref
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > (FILE_MAX_BODY_BYTES if self.files is not None else MAX_BODY_BYTES):
            raise ValueError("native body exceeds bounded owner capture")
        sha = hashlib.sha256(raw).hexdigest()
        origin = {"project_ref": project_ref, **({"task_ref": task_ref} if task_ref else {}),
                  **({"attempt_ref": attempt_ref} if attempt_ref else {})}
        if self.files is not None:
            # Durable before the carrier exists, hence before any record names it.
            self.files.put(project_ref, sha, raw)
            return {"schema": SCHEMA, "store": FILE_STORE, "sha256": sha, "utf8_bytes": len(raw),
                    "media_type": MEDIA_TYPE, "origin": origin}
        scope = hashlib.sha256(json.dumps([project_ref, task_ref, attempt_ref],
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        saved = self.evidence.submit(raw, actor=self.actor,
            logical_request_key="native-body:" + scope + ":" + sha,
            project_ref=project_ref, task_ref=task_ref, attempt_ref=attempt_ref,
            original_creator=self.actor.actor, format="application/json",
            provenance={"producer": SCHEMA, "body_sha256": sha})
        pin = saved["revision_ref"]
        pin = pin.to_dict() if hasattr(pin, "to_dict") else dict(pin)
        return {"schema": SCHEMA, "ref": pin, "sha256": sha, "utf8_bytes": len(raw),
            "origin": {"project_ref": project_ref, **({"task_ref": task_ref} if task_ref else {}),
                **({"attempt_ref": attempt_ref} if attempt_ref else {})}}

    def _file_carrier(self, carrier: Mapping[str, Any], expected_origin: Any) -> Any:
        if (self.files is None or carrier.get("schema") != SCHEMA or type(carrier.get("utf8_bytes")) is not int
                or not 0 <= carrier["utf8_bytes"] <= FILE_MAX_BODY_BYTES or not isinstance(carrier.get("sha256"), str)):
            raise ValueError("invalid retained native body carrier")
        origin = carrier.get("origin")
        if not isinstance(origin, Mapping) or (expected_origin is not None and origin != expected_origin):
            raise ValueError("retained native body scope differs from exact occurrence")
        project = origin.get("project_ref")
        if not isinstance(project, Mapping):
            raise ValueError("retained native body carrier has no project")
        return project

    def _carrier_metadata(self, carrier: Mapping[str, Any], *, expected_origin: Any = None) -> Any:
        if carrier.get("schema") != SCHEMA or type(carrier.get("utf8_bytes")) is not int or not 0 <= carrier["utf8_bytes"] <= MAX_BODY_BYTES:
            raise ValueError("invalid retained native body carrier")
        ref = carrier.get("ref") or {}
        if ref.get("kind") != "dat.content.document" or not ref.get("revision"):
            raise ValueError("immutable Evidence pin required")
        origin = carrier.get("origin")
        if not isinstance(origin, Mapping) or (expected_origin is not None and origin != expected_origin):
            raise ValueError("retained native body scope differs from exact occurrence")
        status = self.evidence.status(ref, actor=self.actor)
        manifest = status.get("manifest") or {}
        if manifest.get("origin") != origin or manifest.get("provenance", {}).get("producer") != SCHEMA:
            raise ValueError("native carrier does not match owner-issued retained evidence")
        return ref, status

    def resolve(self, carrier: Mapping[str, Any], *, expected_origin: Any = None) -> Any:
        if carrier.get("store") == FILE_STORE:
            project = self._file_carrier(carrier, expected_origin)
            return json.loads(self.files.get(project, carrier["sha256"], carrier["utf8_bytes"]))
        ref, _status = self._carrier_metadata(carrier, expected_origin=expected_origin)
        chunks = []
        offset = 0
        while offset < carrier["utf8_bytes"]:
            result = self.evidence.read_evidence(ref, actor=self.actor, offset=offset,
                max_bytes=min(65536, carrier["utf8_bytes"] - offset))
            chunk = result.get("bytes")
            if not isinstance(chunk, bytes) or not chunk:
                raise ValueError("retained native body unavailable")
            chunks.append(chunk)
            offset += len(chunk)
        raw = b"".join(chunks)
        if len(raw) != carrier["utf8_bytes"] or hashlib.sha256(raw).hexdigest() != carrier["sha256"]:
            raise ValueError("retained native body changed")
        return json.loads(raw)

    def _origin(self, record):
        project = record.get("project_ref")
        if isinstance(project, str):
            project = {"authority": self.actor.authority, "kind": "work.project", "id": project}
        from herzchen.contracts import ResourceRef
        if isinstance(project, Mapping):
            selected = ResourceRef.from_dict(project)
            project = ResourceRef(selected.authority, selected.kind, selected.id).to_dict()
        task = record.get("task_ref") or (record.get("target") or {}).get("task_ref")
        attempt = record.get("assignment_ref")
        return {"project_ref": project, **({"task_ref": task} if task else {}),
            **({"attempt_ref": attempt} if attempt else {})}

    def pack_due(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Replace only native/evidence body fields, retaining typed status/identity."""
        origin = self._origin(record)
        scope = {"project_ref": origin["project_ref"], "task_ref": origin.get("task_ref"),
                 "attempt_ref": origin.get("attempt_ref")}
        # Source pins include the exact historical association in their own
        # body. Original-owner Evidence may validate foreign attention scope.
        def walk(value: Any, depth: int = 0, eligible: bool = False) -> Any:
            if depth > 32:
                raise ValueError("native envelope nesting exceeds bounds")
            if isinstance(value, Mapping):
                if value.get("schema") == SCHEMA:
                    if not value.get("inline_replacement"):
                        return dict(value)
                    if value.get("origin") != origin:
                        raise ValueError("foreign native body marker")
                    return dict(value)
                result = {key: walk(item, depth + 1, eligible or key in {
                    "raw_result", "transport_result", "task_bound_evidence", "resource_evidence",
                    "stdout", "stderr", "worker_content", "captured_artifacts"})
                    for key, item in value.items()}
            elif isinstance(value, list):
                result = [walk(item, depth + 1, eligible) for item in value]
            else:
                result = value
            # Factor large strings first, then any remaining structured body.
            # This avoids retaining duplicated native text inside a second blob
            # and also covers bodies made of many small fields/items.
            if eligible and isinstance(result, (str, Mapping, list)):
                size = len(json.dumps(result, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode())
                if size > INLINE_BYTES:
                    return {**self.retain(result, **scope), "inline_replacement": True}
            return result
        return walk(record)

    def unpack_due(self, record: Mapping[str, Any]) -> dict[str, Any]:
        origin = self._origin(record)
        def walk(value: Any, depth: int = 0) -> Any:
            if depth > 64:
                raise ValueError("retained native envelope nesting exceeds bounds")
            if isinstance(value, Mapping):
                if value.get("schema") == SCHEMA:
                    if value.get("inline_replacement") is True:
                        try:
                            return walk(self.resolve(value, expected_origin=origin), depth + 1)
                        except BodyPurged:
                            return _PURGED
                    return dict(value)
                found = ((key, walk(item, depth + 1)) for key, item in value.items())
                # A reclaimed body reads as an absent key, exactly as after clean-close.
                return {key: item for key, item in found if item is not _PURGED}
            if isinstance(value, list):
                return [None if item is _PURGED else item for item in (walk(item, depth + 1) for item in value)]
            return value
        return walk(record)

    def validate_due_metadata(self, record: Mapping[str, Any]) -> None:
        """Authenticate immutable carrier metadata without reading its bytes.

        This is not body verification. Normal resolve/unpack still validates
        the actual bytes before any caller consumes a native body.
        """
        origin = self._origin(record)
        def walk(value: Any, depth: int = 0) -> None:
            if depth > 64:
                raise ValueError("retained native envelope nesting exceeds bounds")
            if isinstance(value, Mapping):
                if value.get("schema") == SCHEMA:
                    if value.get("inline_replacement") is True and value.get("store") == FILE_STORE:
                        self.files.check(self._file_carrier(value, origin), value["sha256"])
                    elif value.get("inline_replacement") is True:
                        _ref, status = self._carrier_metadata(value, expected_origin=origin)
                        manifest = status.get("manifest") or {}
                        if (manifest.get("byte_digest") != value.get("sha256")
                                or manifest.get("byte_length") != value.get("utf8_bytes")
                                or status.get("availability") in {"missing", "corrupt", "purged", "staged", "pending-reclaim"}):
                            raise ValueError("retained native carrier metadata is unavailable or differs")
                    return
                for item in value.values():
                    walk(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    walk(item, depth + 1)
        walk(record)
