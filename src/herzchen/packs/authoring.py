"""Managed pack compatibility and content-only authoring.

Packs shipped in Herzchen's own source tree are admitted here without importing
Astrid. Explicit discovery/loader adapters remain available for external packs.
The authoring handler only snapshots admitted resource bytes through the
supplied FND store; it never creates a database or owns a second writer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence
from herzchen.command_ports import command_facade

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    PackResourceDescriptor,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.kernel import Store, Transaction


PACK_SCHEMA_REVISION = "pkg-05.managed-pack.v1"
MANAGED_PACK_KIND = "managed_pack"
MANAGED_PACK_STREAM = "managed-pack"
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_HEX = re.compile(r"^[0-9a-f]+$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _read_json_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_json_object_without_duplicate_keys
    )
    if not isinstance(value, dict):
        raise ValueError("pack manifest must be a JSON object")
    return value


def domain_contribution() -> DomainContribution:
    return DomainContribution(
        "herzchen.packs.authoring", "1", "pkg", (MANAGED_PACK_KIND,), (),
        ("pack.authoring",), ("pack.content.author",),
        ("managed_pack.content_authored",), PACK_SCHEMA_REVISION,
        (
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction", "handler-required",
            "mutation-port:" + PACK_SCHEMA_REVISION + "|pack.content.author|" + MANAGED_PACK_KIND + "|managed_pack.content_authored",
        ),
    )


class PackAuthoringError(ValueError):
    """Base error for managed pack admission and content authoring."""


class PackLoaderUnavailableError(PackAuthoringError):
    """Astrid's supported public loader/discovery API is unavailable."""


class PackProvenanceError(PackAuthoringError):
    """A managed pack is missing or has inconsistent source provenance."""


class PackPathError(PackAuthoringError):
    """A resource path is unsafe or not part of the admitted pack."""


class PackContentError(PackAuthoringError):
    """Resource content is not a JSON-safe authoring value."""


class PublicPackDiscoverer(Protocol):
    def __call__(self, *, project_root: str | Path) -> Sequence[Any]: ...


class PublicPackLoader(Protocol):
    def __call__(self, path: str | Path, *, expected_pack_id: str | None = None) -> Any: ...


@dataclass(frozen=True)
class ManagedSourceIdentity:
    """The identity attached by Astrid's verified managed-source inventory."""

    pack_id: str
    source_kind: str
    source_revision: str
    source_tree_sha256: str
    source_manifest_sha256: str
    source_inventory_identity: str
    pack_root: str
    manifest_path: str

    def __post_init__(self) -> None:
        for field in ("pack_id", "source_kind", "source_revision", "source_tree_sha256",
                      "source_manifest_sha256", "source_inventory_identity", "pack_root",
                      "manifest_path"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise PackProvenanceError(f"{field} must be non-blank")
        if self.source_kind != "managed":
            raise PackProvenanceError("managed pack provenance must have source_kind='managed'")
        for field in ("source_revision", "source_tree_sha256", "source_manifest_sha256",
                      "source_inventory_identity"):
            value = getattr(self, field).lower()
            if len(value) not in {40, 64} or _HEX.fullmatch(value) is None:
                raise PackProvenanceError(f"{field} must be a full immutable hex identity")
        root = Path(self.pack_root).expanduser()
        manifest = Path(self.manifest_path).expanduser()
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise PackProvenanceError("managed pack root must be an absolute non-symlink directory")
        if not manifest.is_absolute() or manifest.is_symlink() or not manifest.is_file():
            raise PackProvenanceError("managed manifest must be an absolute non-symlink file")
        if manifest.parent.resolve() != root.resolve() or manifest.name != "pack.yaml":
            raise PackProvenanceError("managed manifest must be pack.yaml in the managed pack root")

    def to_dict(self) -> dict[str, str]:
        return {
            "pack_id": self.pack_id,
            "source_kind": self.source_kind,
            "source_revision": self.source_revision,
            "source_tree_sha256": self.source_tree_sha256,
            "source_manifest_sha256": self.source_manifest_sha256,
            "source_inventory_identity": self.source_inventory_identity,
            "pack_root": self.pack_root,
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class ManagedResource:
    path: str
    kind: str
    content: bytes
    source_digest: str
    source_ref: ResourceRef

    def __post_init__(self) -> None:
        _validate_relative_path(self.path)
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise PackContentError("resource kind must be non-blank")
        if not isinstance(self.content, bytes):
            raise PackContentError("resource content must be bytes")
        digest = hashlib.sha256(self.content).hexdigest()
        if self.source_digest != digest:
            raise PackContentError(f"resource digest mismatch for {self.path}")


@dataclass(frozen=True)
class ExecutionPin:
    resource_id: str
    kind: str
    revision: str
    digest: str
    role: str | None = None
    model: str | None = None
    reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "resource_id": self.resource_id,
            "kind": self.kind,
            "revision": self.revision,
            "digest": self.digest,
        }
        for key, item in (("role", self.role), ("model", self.model), ("reasoning", self.reasoning)):
            if item is not None:
                value[key] = item
        return value


@dataclass(frozen=True)
class ManagedPack:
    pack_id: str
    version: str
    source: ManagedSourceIdentity
    manifest: Mapping[str, Any]
    resources: tuple[ManagedResource, ...]
    execution_pins: tuple[ExecutionPin, ...]
    review_profiles: tuple[str, ...]

    def resource(self, path: str) -> ManagedResource:
        for item in self.resources:
            if item.path == path:
                return item
        raise PackPathError(f"resource is not declared by pack: {path!r}")

    @property
    def resource_digests(self) -> Mapping[str, str]:
        return {item.path: item.source_digest for item in self.resources}

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "source": self.source.to_dict(),
            "manifest": dict(self.manifest),
            "resources": [
                {
                    "path": item.path,
                    "kind": item.kind,
                    "digest": item.source_digest,
                    "source_ref": item.source_ref.to_dict(),
                }
                for item in self.resources
            ],
            "execution_pins": [item.to_dict() for item in self.execution_pins],
            "review_profiles": list(self.review_profiles),
        }


@dataclass(frozen=True)
class CompatibilityDescription:
    pack_id: str
    current: Mapping[str, Any]
    historical: tuple[Mapping[str, Any], ...]
    aliases: tuple[Mapping[str, str], ...]
    migration_instructions: tuple[str, ...]
    execution: Mapping[str, Any]
    lesson_transfer: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "current": dict(self.current),
            "historical": [dict(item) for item in self.historical],
            "aliases": [dict(item) for item in self.aliases],
            "migration_instructions": list(self.migration_instructions),
            "execution": dict(self.execution),
            "lesson_transfer": dict(self.lesson_transfer),
        }


@dataclass(frozen=True)
class AuthoringResult:
    pack_id: str
    revision: str
    snapshot_ref: ResourceRef
    receipt: Any
    changed_paths: tuple[str, ...]
    content: Mapping[str, Mapping[str, Any]]
    execution_pins: tuple[Mapping[str, Any], ...]


def _validate_relative_path(path: Any) -> str:
    if not isinstance(path, str) or not _SAFE_PATH.fullmatch(path):
        raise PackPathError("resource paths must be safe POSIX-relative paths")
    if path == "pack.yaml" or any(part in {".", ".."} for part in path.split("/")):
        raise PackPathError(f"unsafe resource path: {path!r}")
    return path


def _validate_source_tree_path(path: Any) -> str:
    if (not isinstance(path, str) or not _SAFE_PATH.fullmatch(path)
            or any(part in {".", ".."} for part in path.split("/"))):
        raise PackPathError("managed source tree paths must be safe POSIX-relative paths")
    return path


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackProvenanceError("native managed packs require a verifiable Git source tree") from exc
    if result.returncode:
        raise PackProvenanceError("native managed packs require a verifiable Git source tree")
    return result.stdout.strip()


def _git_blob(root: Path, revision: str, name: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{revision}:{name}"],
            capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackProvenanceError("native managed source Git object could not be verified") from exc
    if result.returncode:
        raise PackProvenanceError("native managed source Git object could not be verified")
    return result.stdout


def _native_repository(repo_root: Path) -> str:
    """Choose the canonical upstream remote when present, then the checkout remote."""
    remotes = _git(repo_root, "remote").splitlines()
    for name in ("github", "origin", *remotes):
        if name in remotes:
            try:
                value = _git(repo_root, "remote", "get-url", name)
            except PackProvenanceError:
                continue
            if value:
                return value
    # A source archive or isolated fixture may have no configured remote. Keep
    # the inventory field concrete and stable for that checkout.
    return repo_root.resolve().as_uri()


def _native_tree(repo_root: Path, pack_root: Path) -> tuple[str, str, str]:
    """Verify the checkout against HEAD and return revision, tree digest, subpath."""
    if pack_root.is_symlink() or not pack_root.is_dir():
        raise PackProvenanceError("native managed pack root must be a real directory")
    for path in pack_root.rglob("*"):
        if path.is_symlink():
            raise PackProvenanceError(f"native managed pack contains a symlink: {path.relative_to(pack_root)}")
    revision = _git(repo_root, "rev-parse", "HEAD").lower()
    if len(revision) not in {40, 64} or _HEX.fullmatch(revision) is None:
        raise PackProvenanceError("native source revision is not a full Git object identity")
    try:
        subpath = pack_root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise PackProvenanceError("native managed pack must be inside the Herzchen source tree") from exc
    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all", "--", subpath)
    if status:
        raise PackProvenanceError(f"native managed source tree has uncommitted changes: {subpath}")

    tracked = _git(repo_root, "ls-files", "-z", "--", subpath).split("\0")
    digest = hashlib.sha256()
    files = 0
    root = pack_root.resolve()
    for name in sorted(item for item in tracked if item):
        path = repo_root / name
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if path.is_symlink() or not path.is_file():
            raise PackProvenanceError(f"native pack contains a non-regular file: {relative}")
        data = path.read_bytes()
        # Read the immutable Git object too. This catches tampering even if a
        # file's status is hidden by unusual index or worktree configuration.
        if _git_blob(repo_root, revision, name) != data:
            raise PackProvenanceError(f"native managed source differs from Git HEAD: {relative}")
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
        files += 1
    if files == 0:
        raise PackProvenanceError("native managed pack has no tracked source files")
    return revision, digest.hexdigest(), subpath


def _astrid_recorded_tree_digest(pack_root: Path) -> str:
    """Reproduce Astrid's source_setup._tree_digest path selection exactly.

    `_native_tree` separately validates the complete tracked tree against Git
    object bytes and a clean checkout, so the compatibility calculation can
    preserve even the reference's nested-root path behavior without weakening
    tamper refusal.
    """
    root = pack_root.resolve()
    try:
        git_root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
        tracked = _git(root, "ls-files", "-z").split("\0")
        paths: list[tuple[str, Path]] = []
        for item in tracked:
            if not item:
                continue
            path = git_root / item
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if path.is_file():
                paths.append((relative.as_posix(), path))
    except PackProvenanceError:
        paths = [
            (path.relative_to(root).as_posix(), path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.parts
        ]
    digest = hashlib.sha256()
    for relative_name, path in sorted(paths):
        relative = relative_name.encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _runtime_manifest_context(module_pack_root: Path) -> tuple[Path, Path, dict[str, Any]] | None:
    controller_root = module_pack_root.parents[2]
    source_root = controller_root / "runtime-source"
    if source_root.is_symlink():
        raise PackProvenanceError("installed runtime-source root must not be a symlink")
    if module_pack_root.resolve() != (source_root / "herzchen" / "packs").resolve():
        return None
    manifest_path = controller_root / "runtime-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PackProvenanceError("installed Herzchen packs require a pinned runtime-manifest.json")
    try:
        manifest = _read_json_manifest(manifest_path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackProvenanceError("installed runtime manifest is invalid") from exc
    revision = manifest.get("source_commit")
    pins = manifest.get("files")
    if (not isinstance(revision, str) or len(revision) not in {40, 64}
            or _HEX.fullmatch(revision.lower()) is None or not isinstance(pins, dict)):
        raise PackProvenanceError("installed runtime manifest has no full source pin")
    return controller_root, source_root, manifest


def _runtime_tree(
    source_root: Path, pack_root: Path, manifest: Mapping[str, Any]
) -> tuple[str, str, str]:
    revision = str(manifest["source_commit"]).lower()
    pins = manifest["files"]
    if not isinstance(pins, Mapping):
        raise PackProvenanceError("installed runtime manifest file pins are invalid")
    try:
        pack_relative = pack_root.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError as exc:
        raise PackProvenanceError("installed managed pack escapes runtime-source") from exc
    prefix = pack_relative + "/"
    if pack_root.is_symlink() or not pack_root.is_dir():
        raise PackProvenanceError("installed managed pack root is unavailable or symlinked")
    for path in pack_root.rglob("*"):
        if path.is_symlink():
            raise PackProvenanceError(f"installed managed pack contains a symlink: {path.relative_to(pack_root)}")
    files: dict[str, bytes] = {}
    for raw_name, raw_digest in pins.items():
        if not isinstance(raw_name, str) or not raw_name.startswith(prefix):
            continue
        relative = raw_name[len(prefix):]
        _validate_source_tree_path(relative)
        if (not isinstance(raw_digest, str) or len(raw_digest) != 64
                or _HEX.fullmatch(raw_digest.lower()) is None):
            raise PackProvenanceError(f"installed runtime manifest has an invalid file pin: {raw_name}")
        path = source_root / raw_name
        if path.is_symlink() or not path.is_file():
            raise PackProvenanceError(f"installed managed source file is unavailable: {raw_name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != raw_digest.lower():
            raise PackProvenanceError(f"installed managed source differs from runtime pin: {raw_name}")
        files[relative] = data
    actual_files = {
        path.relative_to(pack_root).as_posix()
        for path in pack_root.rglob("*") if path.is_file()
    }
    if actual_files != set(files):
        raise PackProvenanceError("installed managed pack files do not match the runtime manifest inventory")
    if not files:
        raise PackProvenanceError("installed runtime manifest does not pin this managed pack")
    digest = hashlib.sha256()
    for relative, data in sorted(files.items()):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return revision, digest.hexdigest(), pack_relative


def _runtime_pack_is_fully_pinned(source_root: Path, pack_root: Path, manifest: Mapping[str, Any]) -> bool:
    try:
        pack_relative = pack_root.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError:
        return False
    pins = manifest.get("files")
    if not isinstance(pins, Mapping):
        return False
    prefix = pack_relative + "/"
    pinned = {name[len(prefix):] for name in pins if isinstance(name, str) and name.startswith(prefix)}
    actual = {
        path.relative_to(pack_root).as_posix()
        for path in pack_root.rglob("*") if path.is_file() and not path.is_symlink()
    }
    return bool(actual) and actual == pinned


def _runtime_source_record(
    pack_id: str, pack_root: Path, manifest_digest: str,
    context: tuple[Path, Path, dict[str, Any]],
) -> ManagedSourceIdentity:
    controller_root, source_root, runtime_manifest = context
    revision, tree_digest, subpath = _runtime_tree(source_root, pack_root, runtime_manifest)
    module_path = Path(__file__).resolve()
    try:
        module_relative = module_path.relative_to(source_root.resolve()).as_posix()
    except ValueError as exc:
        raise PackProvenanceError("installed authoring module escapes runtime-source") from exc
    module_pin = runtime_manifest["files"].get(module_relative)
    if not isinstance(module_pin, str) or hashlib.sha256(module_path.read_bytes()).hexdigest() != module_pin.lower():
        raise PackProvenanceError("installed authoring module differs from runtime manifest pin")
    repository = "runtime-manifest:" + str(runtime_manifest["source_commit"])
    entries: list[dict[str, str]] = []
    for candidate in sorted(Path(__file__).resolve().parent.iterdir(), key=lambda item: item.name):
        candidate_manifest = candidate / "pack.yaml"
        if (candidate.is_symlink() or not candidate.is_dir() or not candidate_manifest.is_file()
                or not _runtime_pack_is_fully_pinned(source_root, candidate, runtime_manifest)):
            continue
        try:
            data = _read_json_manifest(candidate_manifest)
        except (OSError, UnicodeError, ValueError) as exc:
            raise PackProvenanceError(f"installed pack manifest is invalid: {candidate}") from exc
        candidate_id = data.get("id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise PackProvenanceError(f"installed pack has no valid ID: {candidate}")
        candidate_revision, candidate_tree, candidate_subpath = _runtime_tree(source_root, candidate, runtime_manifest)
        candidate_digest = hashlib.sha256(candidate_manifest.read_bytes()).hexdigest()
        entries.append({
            "pack_id": candidate_id,
            "pack_root": str(candidate.resolve()),
            "repository": repository,
            "revision": candidate_revision,
            "pack_subpath": candidate_subpath,
            "manifest_sha256": candidate_digest,
            "tree_sha256": candidate_tree,
            "source_kind": "managed",
        })
        if candidate.resolve() == pack_root.resolve() and (
            candidate_id != pack_id or candidate_digest != manifest_digest or candidate_tree != tree_digest
        ):
            raise PackProvenanceError("installed managed pack changed during source inventory")
    if not any(item["pack_id"] == pack_id and item["pack_root"] == str(pack_root.resolve()) for item in entries):
        raise PackProvenanceError(f"installed runtime manifest does not pin managed pack {pack_id!r}")
    if len({item["pack_id"] for item in entries}) != len(entries):
        raise PackProvenanceError("installed managed pack inventory contains duplicate IDs")
    inventory_identity = hashlib.sha256(
        json.dumps(sorted(entries, key=lambda item: item["pack_id"]), sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ManagedSourceIdentity(
        pack_id=pack_id,
        source_kind="managed",
        source_revision=revision,
        source_tree_sha256=tree_digest,
        source_manifest_sha256=manifest_digest,
        source_inventory_identity=inventory_identity,
        pack_root=str(pack_root.resolve()),
        manifest_path=str((pack_root / "pack.yaml").resolve()),
    )


def _native_source_record(pack_id: str, pack_root: Path, manifest_digest: str) -> ManagedSourceIdentity:
    module_pack_root = Path(__file__).resolve().parent
    repo_root = module_pack_root.parents[2]
    runtime_context = _runtime_manifest_context(module_pack_root)
    if runtime_context is not None:
        return _runtime_source_record(pack_id, pack_root, manifest_digest, runtime_context)
    expected_source_packs = repo_root / "src" / "herzchen" / "packs"
    if module_pack_root != expected_source_packs.resolve():
        raise PackProvenanceError("native pack loader is not running from Herzchen's source tree")
    revision, verified_tree_digest, _ = _native_tree(repo_root, pack_root)
    tree_digest = _astrid_recorded_tree_digest(pack_root)
    repository = _native_repository(repo_root)
    source_entries: list[dict[str, str]] = []
    matching_ids: set[str] = set()
    for candidate in sorted(module_pack_root.iterdir(), key=lambda item: item.name):
        candidate_manifest = candidate / "pack.yaml"
        if candidate.is_symlink() or not candidate.is_dir() or not candidate_manifest.is_file():
            continue
        try:
            candidate_data = _read_json_manifest(candidate_manifest)
        except (OSError, UnicodeError, ValueError) as exc:
            raise PackProvenanceError(f"native pack inventory contains an invalid manifest: {candidate}") from exc
        candidate_id = candidate_data.get("id") if isinstance(candidate_data, dict) else None
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise PackProvenanceError(f"native pack inventory contains a manifest without an ID: {candidate}")
        candidate_revision, candidate_verified_tree, candidate_subpath = _native_tree(repo_root, candidate)
        candidate_tree = _astrid_recorded_tree_digest(candidate)
        if candidate_revision != revision:
            raise PackProvenanceError("native packs resolved to different source revisions")
        candidate_manifest_digest = hashlib.sha256(candidate_manifest.read_bytes()).hexdigest()
        source_entries.append({
            "pack_id": candidate_id,
            "pack_root": str(candidate.resolve()),
            "repository": repository,
            "revision": candidate_revision,
            "pack_subpath": candidate_subpath,
            "manifest_sha256": candidate_manifest_digest,
            "tree_sha256": candidate_tree,
            "source_kind": "managed",
        })
        if candidate_id == pack_id and candidate.resolve() == pack_root.resolve():
            matching_ids.add(candidate_id)
            if candidate_manifest_digest != manifest_digest or candidate_verified_tree != verified_tree_digest:
                raise PackProvenanceError("native pack changed while its source inventory was built")
    if matching_ids != {pack_id} or len({item["pack_id"] for item in source_entries}) != len(source_entries):
        raise PackProvenanceError("native pack inventory has missing or duplicate pack identities")
    inventory_identity = _configured_inventory_identity(
        pack_id, pack_root, revision, tree_digest, manifest_digest, source_entries
    )
    return ManagedSourceIdentity(
        pack_id=pack_id,
        source_kind="managed",
        source_revision=revision,
        source_tree_sha256=tree_digest,
        source_manifest_sha256=manifest_digest,
        source_inventory_identity=inventory_identity,
        pack_root=str(pack_root.resolve()),
        manifest_path=str((pack_root / "pack.yaml").resolve()),
    )


def _configured_inventory_identity(
    pack_id: str,
    pack_root: Path,
    revision: str,
    tree_digest: str,
    manifest_digest: str,
    fallback_entries: list[dict[str, str]],
) -> str:
    """Use a configured Astrid inventory only when it names this exact root.

    This reads only an explicitly configured state path. It does not probe the
    user's default Astrid state location, and the native loader itself never
    imports Astrid.
    """
    raw_state_path = os.environ.get("ASTRID_SOURCE_STATE", "").strip()
    if not raw_state_path:
        entries = sorted(fallback_entries, key=lambda item: item["pack_id"])
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    state_candidate = Path(raw_state_path).expanduser()
    if state_candidate.is_symlink():
        raise PackProvenanceError("configured managed-source state must not be a symlink")
    state_path = state_candidate.resolve()
    if not state_path.is_file():
        raise PackProvenanceError("configured managed-source state is unavailable")
    try:
        state = _read_json_manifest(state_path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackProvenanceError("configured managed-source state is invalid") from exc
    if (type(state.get("version")) is not int or state["version"] != 1
            or not isinstance(state.get("active"), dict)
            or not isinstance(state.get("disabled", []), list)):
        raise PackProvenanceError("configured managed-source state has an invalid shape")
    disabled = {str(item) for item in state.get("disabled", [])}
    records: list[dict[str, str]] = []
    target: dict[str, str] | None = None
    for key, value in sorted(state["active"].items()):
        if key in disabled:
            continue
        required = ("pack_id", "pack_root", "repository", "revision", "pack_subpath",
                    "manifest_sha256", "tree_sha256")
        if (not isinstance(value, dict)
                or any(not isinstance(value.get(field), str) or not value[field] for field in required)):
            raise PackProvenanceError("configured managed-source record is incomplete")
        pack_root_value = Path(value["pack_root"]).expanduser()
        if not pack_root_value.is_absolute() or pack_root_value.is_symlink():
            raise PackProvenanceError("configured managed-source pack root must not be a symlink")
        pack_id_value = value["pack_id"].strip()
        revision_value = value["revision"].strip().lower()
        manifest_value = value["manifest_sha256"].strip().lower()
        tree_value = value["tree_sha256"].strip().lower()
        if (not pack_id_value or "/" in pack_id_value or "\\" in pack_id_value
                or pack_id_value.startswith(".") or len(revision_value) not in {40, 64}
                or _HEX.fullmatch(revision_value) is None
                or len(manifest_value) != 64 or _HEX.fullmatch(manifest_value) is None
                or len(tree_value) != 64 or _HEX.fullmatch(tree_value) is None):
            raise PackProvenanceError("configured managed-source record has invalid immutable identities")
        subpath_value = value["pack_subpath"].strip() or "."
        if (subpath_value != "." and (subpath_value.startswith("/") or "\\" in subpath_value
                                        or any(part in {"", ".", ".."} for part in subpath_value.split("/")))):
            raise PackProvenanceError("configured managed-source record has an unsafe pack_subpath")
        record = {
            "pack_id": pack_id_value,
            "pack_root": str(pack_root_value.resolve()),
            "repository": value["repository"].strip(),
            "revision": revision_value,
            "pack_subpath": subpath_value,
            "manifest_sha256": manifest_value,
            "tree_sha256": tree_value,
        }
        if not record["repository"]:
            raise PackProvenanceError("configured managed-source repository is blank")
        record["source_kind"] = "managed"
        if value["pack_id"] != key:
            raise PackProvenanceError("configured managed-source key does not match its pack ID")
        records.append(record)
        if (record["pack_id"] == pack_id
                and Path(record["pack_root"]).expanduser().resolve() == pack_root.resolve()):
            target = record
    if target is None:
        entries = sorted(fallback_entries, key=lambda item: item["pack_id"])
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    for record in records:
        _verify_configured_source_record(record)
    expected = {
        "revision": revision,
        "manifest_sha256": manifest_digest,
        "tree_sha256": tree_digest,
        "source_kind": "managed",
    }
    if any(target[field] != expected_value for field, expected_value in expected.items()):
        raise PackProvenanceError("configured managed-source record does not match native pack bytes")
    payload = json.dumps(sorted(records, key=lambda item: item["pack_id"]),
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_configured_source_record(record: Mapping[str, str]) -> None:
    """Verify one configured active source exactly as far as its record allows."""
    pack_root = Path(record["pack_root"])
    subpath = record["pack_subpath"]
    checkout = pack_root
    if subpath != ".":
        for _ in subpath.split("/"):
            checkout = checkout.parent
    if checkout.is_symlink() or not checkout.is_dir() or pack_root.is_symlink() or not pack_root.is_dir():
        raise PackProvenanceError("configured managed-source checkout is unavailable or symlinked")
    expected_root = checkout if subpath == "." else checkout.joinpath(*subpath.split("/"))
    if expected_root.resolve() != pack_root.resolve():
        raise PackProvenanceError("configured managed-source subpath does not resolve to its pack root")
    if _git(checkout, "rev-parse", "HEAD").lower() != record["revision"]:
        raise PackProvenanceError("configured managed-source revision differs from its checkout")
    if _git(checkout, "status", "--porcelain=v1", "--untracked-files=all"):
        raise PackProvenanceError("configured managed-source checkout has uncommitted changes")
    manifest_path = pack_root / "pack.yaml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PackProvenanceError("configured managed-source manifest is unavailable or symlinked")
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    revision, _verified_tree_digest, actual_subpath = _native_tree(checkout, pack_root)
    tree_digest = _astrid_recorded_tree_digest(pack_root)
    if (revision != record["revision"] or actual_subpath != record["pack_subpath"]
            or manifest_digest != record["manifest_sha256"]
            or tree_digest != record["tree_sha256"]):
        raise PackProvenanceError("configured managed-source digests do not match its checkout")


def _native_manifest(pack_root: Path, expected_pack_id: str) -> tuple[dict[str, Any], tuple[tuple[str, str, Path], ...]]:
    manifest_path = pack_root / "pack.yaml"
    if pack_root.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
        raise PackProvenanceError("native managed pack requires a regular pack.yaml")
    try:
        manifest = _read_json_manifest(manifest_path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackAuthoringError(f"native pack manifest is not valid JSON: {exc}") from exc
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 2:
        raise PackAuthoringError("native loader requires a v2 pack manifest")
    if "database" in manifest:
        raise PackAuthoringError("database contributions are forbidden in managed packs")
    if manifest.get("id") != expected_pack_id:
        raise PackAuthoringError("native pack manifest ID does not match the requested pack")
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise PackAuthoringError("native pack manifest requires a non-blank name")
    if not isinstance(manifest.get("version"), str) or not _VERSION.fullmatch(manifest["version"]):
        raise PackAuthoringError("native pack manifest requires a major.minor.patch version")
    declarations = manifest.get("resources")
    if not isinstance(declarations, list) or not declarations:
        raise PackContentError("native managed pack declares no resources")
    result: list[tuple[str, str, Path]] = []
    seen: set[str] = set()
    for declaration in declarations:
        if not isinstance(declaration, dict):
            raise PackAuthoringError("native resource declaration must be an object")
        path = _validate_relative_path(declaration.get("path"))
        kind = declaration.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise PackAuthoringError(f"native resource kind is invalid for {path}")
        if path in seen:
            raise PackContentError(f"duplicate resource path: {path}")
        seen.add(path)
        resolved = pack_root / path
        component = resolved
        while component == pack_root or pack_root in component.parents:
            if component.is_symlink():
                raise PackPathError(f"resource path contains a symlink: {path}")
            if component == pack_root:
                break
            component = component.parent
        if not resolved.is_file():
            raise PackPathError(f"resource is not a regular non-symlink file: {path}")
        try:
            resolved.resolve().relative_to(pack_root.resolve())
        except ValueError as exc:
            raise PackPathError(f"resource escapes the native pack root: {path}") from exc
        result.append((path, kind, resolved))
    return manifest, tuple(result)


def _read_native_managed_pack(pack_id: str, project_root: str | Path) -> ManagedPack:
    module_pack_root = Path(__file__).resolve().parent
    repo_root = module_pack_root.parents[2]
    supplied_root = Path(project_root).expanduser().resolve()
    if supplied_root != repo_root.resolve():
        raise PackProvenanceError("native managed packs are available only from this Herzchen checkout")
    candidates: list[Path] = []
    for child in sorted(module_pack_root.iterdir(), key=lambda item: item.name):
        if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "pack.yaml"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            value = _read_json_manifest(manifest_path)
        except (OSError, UnicodeError, ValueError) as exc:
            raise PackAuthoringError(f"native pack manifest is invalid: {manifest_path}") from exc
        if isinstance(value, dict) and value.get("id") == pack_id:
            candidates.append(child)
    if len(candidates) != 1:
        raise PackProvenanceError(f"expected one native managed source for {pack_id!r}, found {len(candidates)}")
    pack_root = candidates[0]
    manifest, declarations = _native_manifest(pack_root, pack_id)
    manifest_digest = hashlib.sha256((pack_root / "pack.yaml").read_bytes()).hexdigest()
    source = _native_source_record(pack_id, pack_root, manifest_digest)
    runtime_context = _runtime_manifest_context(module_pack_root)
    # Re-read admission after provenance calculation so a concurrent edit is
    # refused before any resource bytes enter the returned pack.
    current_manifest, current_declarations = _native_manifest(pack_root, pack_id)
    if current_manifest != manifest or current_declarations != declarations:
        raise PackProvenanceError("native managed pack changed during admission")
    resources: list[ManagedResource] = []
    for path, kind, resolved in declarations:
        content = resolved.read_bytes()
        if runtime_context is not None:
            _controller_root, source_root, runtime_manifest = runtime_context
            relative_to_source = resolved.resolve().relative_to(source_root.resolve()).as_posix()
            expected_digest = runtime_manifest["files"].get(relative_to_source)
            if not isinstance(expected_digest, str) or hashlib.sha256(content).hexdigest() != expected_digest.lower():
                raise PackProvenanceError(f"native managed resource differs from runtime manifest: {path}")
        else:
            relative_to_repo = resolved.resolve().relative_to(repo_root.resolve()).as_posix()
            if _git_blob(repo_root, source.source_revision, relative_to_repo) != content:
                raise PackProvenanceError(f"native managed resource differs from Git HEAD: {path}")
        resources.append(ManagedResource(
            path, kind, content, hashlib.sha256(content).hexdigest(),
            ResourceRef("astrid-managed", MANAGED_PACK_KIND, pack_id, source.source_revision),
        ))
    manifest_after_read = hashlib.sha256((pack_root / "pack.yaml").read_bytes()).hexdigest()
    source_after_read = _native_source_record(pack_id, pack_root, manifest_after_read)
    if (source_after_read.source_revision != source.source_revision
            or source_after_read.source_tree_sha256 != source.source_tree_sha256
            or source_after_read.source_manifest_sha256 != source.source_manifest_sha256
            or source_after_read.source_inventory_identity != source.source_inventory_identity):
        raise PackProvenanceError("native managed source changed while resource bytes were read")
    return ManagedPack(
        pack_id,
        manifest["version"],
        source,
        manifest,
        tuple(sorted(resources, key=lambda item: item.path)),
        _execution_pins(pack_id, source, resources),
        _review_profiles(manifest, resources),
    )


def _source_from_discovered(item: Any) -> ManagedSourceIdentity:
    entry = item.entry
    values = {
        "pack_id": item.id,
        "source_kind": item.source_kind,
        "source_revision": item.source_revision,
        "source_tree_sha256": item.source_tree_sha256,
        "source_manifest_sha256": item.source_manifest_sha256,
        "source_inventory_identity": item.source_inventory_identity,
        "pack_root": str(item.pack_dir.resolve()),
        "manifest_path": str((item.pack_dir / "pack.yaml").resolve()),
    }
    if any(not isinstance(values[name], str) or not values[name] for name in values):
        raise PackProvenanceError(f"managed source record for {item.id!r} is incomplete")
    if entry.manifest.sha256 != values["source_manifest_sha256"]:
        raise PackProvenanceError(f"manifest digest does not match managed source for {item.id!r}")
    return ManagedSourceIdentity(**values)


def _execution_pins(pack_id: str, source: ManagedSourceIdentity, resources: Iterable[ManagedResource]) -> tuple[ExecutionPin, ...]:
    pins: list[ExecutionPin] = []
    for item in resources:
        if item.kind not in {"work_protocol", "protocol_reference", "protocol_guidance", "skill"}:
            continue
        pins.append(ExecutionPin(
            resource_id=f"{pack_id}/{item.path}",
            kind=item.kind,
            revision=source.source_revision,
            digest=item.source_digest,
        ))
    return tuple(sorted(pins, key=lambda item: item.resource_id))


def read_managed_pack(
    pack_id: str,
    *,
    project_root: str | Path,
    discoverer: PublicPackDiscoverer | None = None,
    loader: PublicPackLoader | None = None,
) -> ManagedPack:
    """Read a bundled Herzchen pack, or an injected external managed source."""
    if not isinstance(pack_id, str) or not pack_id.strip():
        raise PackAuthoringError("pack_id must be non-blank")
    if (discoverer is None) != (loader is None):
        raise PackAuthoringError(
            "discoverer and loader must be supplied together; do not mix an admission adapter with the Astrid default"
        )
    if discoverer is None:
        return _read_native_managed_pack(pack_id, project_root)
    discover, load = discoverer, loader
    try:
        discovered = tuple(discover(project_root=project_root))
    except Exception as exc:  # normalize public-loader failures at this boundary
        raise PackAuthoringError(f"managed pack discovery failed for {pack_id!r}: {exc}") from exc
    candidates = [item for item in discovered if item.id == pack_id and item.source_kind == "managed"]
    if len(candidates) != 1:
        raise PackProvenanceError(
            f"expected one managed source for {pack_id!r}, found {len(candidates)}"
        )
    item = candidates[0]
    source = _source_from_discovered(item)
    try:
        loaded = load(source.manifest_path, expected_pack_id=pack_id)
    except Exception as exc:
        raise PackAuthoringError(f"public pack loader rejected {pack_id!r}: {exc}") from exc
    definition = item.entry.definition
    if loaded.id != pack_id or str(loaded.schema_version) != "2":
        raise PackAuthoringError("public loader returned a non-v2 or mismatched pack")
    resources: list[ManagedResource] = []
    seen: set[str] = set()
    for handle in item.entry.resource_handles:
        path = _validate_relative_path(handle.path)
        if path in seen:
            raise PackContentError(f"duplicate resource path: {path}")
        seen.add(path)
        if handle.resolved.is_symlink() or not handle.resolved.is_file():
            raise PackPathError(f"resource is not a regular non-symlink file: {path}")
        content = handle.resolved.read_bytes()
        kind = handle.kind.split(":", 1)[1] if ":" in handle.kind else handle.kind
        resources.append(ManagedResource(
            path, kind, content, handle.sha256,
            ResourceRef("astrid-managed", MANAGED_PACK_KIND, pack_id, source.source_revision),
        ))
    if not resources:
        raise PackContentError(f"managed pack {pack_id!r} declares no resources")
    return ManagedPack(
        pack_id,
        definition.version,
        source,
        definition.to_dict(),
        tuple(sorted(resources, key=lambda item: item.path)),
        _execution_pins(pack_id, source, resources),
        _review_profiles(definition.to_dict(), resources),
    )


def _review_profiles(manifest: Mapping[str, Any], resources: Iterable[ManagedResource]) -> tuple[str, ...]:
    profiles: set[str] = set()
    for item in resources:
        if item.kind != "work_protocol":
            continue
        try:
            value = json.loads(item.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for route in value.get("routes", {}).values():
            if isinstance(route, Mapping):
                profiles.update(str(key) for key in route)
    return tuple(sorted(profiles & {"normal", "xhard"}))


def describe_compatibility(pack: ManagedPack) -> CompatibilityDescription:
    """Return inspectable current/historical and execution-boundary facts."""
    current_resources = [
        {
            "id": f"{pack.pack_id}/{item.path}",
            "path": item.path,
            "kind": item.kind,
            "revision": pack.source.source_revision,
            "digest": item.source_digest,
        }
        for item in pack.resources
    ]
    aliases: list[dict[str, str]] = []
    migration: list[str] = [
        "Use canonical pack.yaml and schema_version 2; legacy/v1/alternate manifests remain rejected.",
        "Resolve resources by pack ID and declared relative path, never by an unbound folder-name guess.",
    ]
    if pack.pack_id == "scene_production":
        aliases.append({"old": "scene-production", "new": "scene_production", "kind": "pack_id"})
        migration.append("Map the historical scene-production directory to manifest ID scene_production in the managed inventory.")
    if pack.pack_id == "work_starters":
        aliases.append({"old": "work-starters", "new": "work_starters", "kind": "pack_id"})
        migration.append("Map the historical work-starters directory to manifest ID work_starters in the managed inventory.")
    if pack.pack_id == "megado":
        migration.append("Keep the maintained Megado skill and file-mode export byte-identical; adopt a new revision explicitly.")
    execution = {
        "pins": [item.to_dict() for item in pack.execution_pins],
        "profiles": list(pack.review_profiles),
        "normal_xhard_independent": True,
        "compulsory_stage_count": 1,
        "counter_reset": False,
        "new_specialist_recipe": "deferred:LATER-01",
    }
    lesson = {
        "origin_evidence": "tests/packs/test_protocol_resources.py::test_active_megado_skill_matches_file_mode_export_and_provenance",
        "adopted_resource": f"{pack.pack_id}/skill/SKILL.md@{pack.source.source_revision}",
        "tool_identity": "herzchen-contracts/pkg-05-public-reader",
        "retained_regression": "tests/packs/test_protocol_resources.py::test_shipped_skill_links_resolve_offline_inside_pack",
        "claim": "transfer mechanics only; no universal benefit or cadence/rights grant",
    }
    return CompatibilityDescription(
        pack.pack_id,
        {
            "manifest_schema": 2,
            "source": pack.source.to_dict(),
            "resources": current_resources,
        },
        (
            {"id": "pack-v1", "status": "rejected", "reason": "schema_version is not 2"},
            {"id": "alternate-manifest", "status": "rejected", "reason": "canonical filename must be pack.yaml"},
            {"id": "database-pack", "status": "rejected", "reason": "database contributions are forbidden"},
        ),
        tuple(aliases),
        tuple(migration),
        execution,
        lesson,
    )


def verify_skill_export(native_root: str | Path, file_export_root: str | Path) -> Mapping[str, Any]:
    """Prove byte identity and offline relative-link resolution for a skill export."""
    native = Path(native_root).expanduser().resolve()
    exported = Path(file_export_root).expanduser().resolve()
    if native.is_symlink() or exported.is_symlink() or not native.is_dir() or not exported.is_dir():
        raise PackPathError("skill roots must be existing non-symlink directories")
    native_files = sorted(path.relative_to(native).as_posix() for path in native.rglob("*") if path.is_file())
    export_files = sorted(path.relative_to(exported).as_posix() for path in exported.rglob("*") if path.is_file())
    if native_files != export_files:
        raise PackContentError("native skill and file-mode export file inventories differ")
    for relative in native_files:
        if (native / relative).read_bytes() != (exported / relative).read_bytes():
            raise PackContentError(f"skill export differs at {relative}")
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    links_checked = 0
    for source in native.rglob("*.md"):
        for target in link_re.findall(source.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.is_relative_to(native) or not resolved.is_file():
                raise PackPathError(f"offline skill link does not resolve: {source} -> {target}")
            links_checked += 1
    return {"files": native_files, "sha256": _tree_bytes_digest(native), "offline_relative_links": links_checked}


def _tree_bytes_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _digest_payload(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _content_record(item: ManagedResource, revision: str, content: bytes) -> dict[str, Any]:
    descriptor = PackResourceDescriptor(
        resource_id=item.path.replace("/", "."),
        kind=item.kind,
        revision=revision,
        source_ref=item.source_ref,
        digest=hashlib.sha256(content).hexdigest(),
        annotations={"path": item.path, "encoding": "base64"},
    )
    return {
        "descriptor": descriptor.to_dict(),
        "content_b64": base64.b64encode(content).decode("ascii"),
    }


def _decode_content(path: str, value: Mapping[str, Any]) -> bytes:
    try:
        content = base64.b64decode(value["content_b64"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise PackContentError(f"stored content is invalid for {path}") from exc
    descriptor = value.get("descriptor")
    if not isinstance(descriptor, Mapping) or descriptor.get("digest") != hashlib.sha256(content).hexdigest():
        raise PackContentError(f"stored descriptor digest mismatch for {path}")
    return content


class _ManagedPackAuthoringHandlerEngine:
    """Content-only managed pack handler over the injected FND store."""

    def __init__(self, store: Store) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        if hasattr(store, "domain_handler"):
            store = store.domain_handler((domain_contribution(),))
        self.__writer = store
        self.reader = store.consumer()

    def author(
        self,
        pack: ManagedPack,
        updates: Mapping[str, bytes | bytearray | str] | None = None,
        *,
        logical_request_key: str,
        actor: AuthenticatedActor,
        transaction: Transaction | None = None,
    ) -> AuthoringResult:
        if not isinstance(pack, ManagedPack):
            raise TypeError("pack must be a ManagedPack read through the public loader")
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        updates = dict(updates or {})
        declared = {item.path: item for item in pack.resources}
        for path in updates:
            _validate_relative_path(path)
            if path not in declared:
                raise PackPathError(f"authoring update is not an admitted resource: {path!r}")
        normalized_updates = {path: _coerce_content(value) for path, value in updates.items()}
        request_payload = {
            "pack": pack.to_dict(),
            "updates": {
                path: base64.b64encode(normalized_updates[path]).decode("ascii")
                for path in sorted(normalized_updates)
            },
        }
        current_ref = ResourceRef(self.__writer.authority, MANAGED_PACK_KIND, pack.pack_id)
        prior = self.__writer.get_receipt(logical_request_key)
        if prior is not None:
            replay_target = prior.target
            replay_version = 0
            if replay_target.revision is not None and replay_target.revision.startswith("rev-"):
                try:
                    replay_version = int(replay_target.revision.removeprefix("rev-"))
                except ValueError:
                    replay_version = None
            replay_digest = _digest_payload(request_payload)
            replay_envelope = CommandEnvelope(
                "pack.content.author", PACK_SCHEMA_REVISION, replay_target,
                TransactionContext(
                    actor, logical_request_key, replay_digest,
                    expected_revision=replay_target.revision,
                    expected_version=replay_version,
                ),
                request_payload,
            )
            receipt = self.__writer.mutate(
                replay_envelope, event_type="managed_pack.content_authored", result_ref=prior.result_ref,
                stream=f"{MANAGED_PACK_STREAM}:{pack.pack_id}", transaction=transaction,
            )
            current = self.__writer.get_identity(current_ref)
            if current is None:
                raise PackAuthoringError(f"managed pack replay lost its durable identity: {pack.pack_id!r}")
            event = next((item for item in self.__writer.list_events(stream=f"{MANAGED_PACK_STREAM}:{pack.pack_id}") if item.event_id in prior.event_ids), None)
            if event is None:
                raise PackAuthoringError(f"managed pack replay receipt has no event lineage: {pack.pack_id!r}")
            effects = event.effects
            return AuthoringResult(
                pack.pack_id, (prior.result_ref.revision if prior.result_ref else current.ref.revision) or "",
                prior.result_ref or current.ref, receipt, tuple(effects.get("changed_paths", ())),
                effects.get("content_snapshot", {}), tuple(effects.get("execution_pins", ())),
            )
        current = self.__writer.get_identity(current_ref)
        if current is not None:
            current_ref = current.ref
            current_payload = dict(current.payload)
            if current_payload.get("record_type") != MANAGED_PACK_KIND:
                raise PackContentError("managed pack identity has an unexpected record type")
            existing_resources = dict(current_payload.get("resources", {}))
        else:
            current_payload = {}
            existing_resources = {}
        next_revision = f"rev-{(current.version if current is not None else 0) + 1}"
        merged: dict[str, dict[str, Any]] = dict(existing_resources)
        for item in pack.resources:
            content = item.content
            if item.path in updates:
                content = normalized_updates[item.path]
            merged[item.path] = _content_record(item, next_revision, content)
        # Existing resources not present in a newer source remain untouched;
        # this is the unknown-sibling retention boundary.
        for path, record in merged.items():
            _validate_relative_path(path)
            if not isinstance(record, Mapping):
                raise PackContentError(f"stored sibling resource is invalid: {path}")
            _decode_content(path, record)
        execution_pins = tuple(item.to_dict() for item in pack.execution_pins)
        payload = {
            "record_type": MANAGED_PACK_KIND,
            "pack_id": pack.pack_id,
            "version": pack.version,
            "source": pack.source.to_dict(),
            "resources": {path: merged[path] for path in sorted(merged)},
            "execution_pins": list(execution_pins),
            "compatibility": describe_compatibility(pack).to_dict(),
        }
        if current is not None and current.payload == payload:
            return AuthoringResult(
                pack.pack_id, current.ref.revision or "", current.ref, None, (),
                payload["resources"], tuple(execution_pins),
            )
        digest = _digest_payload(request_payload)
        context = TransactionContext(
            actor,
            logical_request_key,
            digest,
            expected_revision=current_ref.revision if current is not None else None,
            expected_version=current.version if current is not None else 0,
        )
        target = current_ref if current is not None else ResourceRef(self.__writer.authority, MANAGED_PACK_KIND, pack.pack_id)
        envelope = CommandEnvelope("pack.content.author", PACK_SCHEMA_REVISION, target, context, request_payload)
        result_ref = ResourceRef(self.__writer.authority, MANAGED_PACK_KIND, pack.pack_id, next_revision)
        receipt = self.__writer.mutate(
            envelope,
            identity_payload=payload,
            event_type="managed_pack.content_authored",
            result_ref=result_ref,
            effects={
                "content_only": True,
                "changed_paths": sorted(updates),
                "content_snapshot": payload["resources"],
                "source": pack.source.to_dict(),
                "execution_pins": list(execution_pins),
            },
            stream=f"{MANAGED_PACK_STREAM}:{pack.pack_id}",
            transaction=transaction,
        )
        return AuthoringResult(
            pack.pack_id, result_ref.revision or "", result_ref, receipt,
            tuple(sorted(updates)), payload["resources"], tuple(execution_pins),
        )

    def read(self, pack_id: str, *, revision: str | None = None) -> Mapping[str, Any]:
        """Read the fresh adopted record or a retained pinned event snapshot."""
        current = self.__writer.get_identity(ResourceRef(self.__writer.authority, MANAGED_PACK_KIND, pack_id))
        if current is None:
            raise PackAuthoringError(f"managed pack is not adopted: {pack_id!r}")
        wanted = revision or current.ref.revision
        if wanted == current.ref.revision:
            return current.payload
        for event in self.__writer.list_events(stream=f"{MANAGED_PACK_STREAM}:{pack_id}"):
            if any(ref.revision == wanted for ref in event.after_refs):
                return {
                    "record_type": MANAGED_PACK_KIND,
                    "pack_id": pack_id,
                    "resources": event.effects["content_snapshot"],
                    "source": event.effects["source"],
                    "execution_pins": event.effects["execution_pins"],
                    "revision": wanted,
                }
        raise PackAuthoringError(f"pinned managed pack revision is unavailable: {wanted!r}")

    def lifecycle_handler(self, pack: ManagedPack, *, request_id: str) -> Any:
        """Return PKG content hooks for EDT's shared finish boundary."""
        from herzchen.authoring import CallableSemanticHandler, ValidationResult

        def updates(snapshot: Any) -> dict[str, bytes]:
            try:
                data = snapshot.file_bytes("pack-content.json")
            except (AttributeError, KeyError):
                data = snapshot.data
            payload = json.loads(data.decode("utf-8"))
            values = payload.get("updates") if isinstance(payload, Mapping) else None
            if not isinstance(values, Mapping):
                raise PackContentError("updates must be an object")
            declared = {item.path for item in pack.resources}
            result: dict[str, bytes] = {}
            for path, value in values.items():
                _validate_relative_path(path)
                if path not in declared:
                    raise PackPathError(f"authoring update is not an admitted resource: {path!r}")
                try:
                    result[path] = base64.b64decode(value, validate=True)
                except (TypeError, ValueError) as exc:
                    raise PackContentError(f"invalid base64 content for {path!r}") from exc
            return result

        def validate(snapshot: Any, checkout: Any, checkout_root: str) -> Any:
            try:
                updates(snapshot)
            except (PackAuthoringError, TypeError, ValueError, KeyError) as exc:
                return ValidationResult(False, str(exc))
            return ValidationResult(True)

        def apply(snapshot: Any, checkout: Any, tx: Any, writer: Any) -> Any:
            return self.author(
                pack, updates(snapshot), logical_request_key=request_id,
                actor=checkout.actor, transaction=tx,
            )

        return CallableSemanticHandler(validate, apply)

    def assign(self, pack: ManagedPack, *, logical_request_key: str, actor: AuthenticatedActor, transaction: Transaction | None = None) -> AuthoringResult:
        """Adopt the explicitly read revision while retaining prior pins."""
        return self.author(pack, logical_request_key=logical_request_key, actor=actor, transaction=transaction)


ManagedPackAuthoringHandler = command_facade(_ManagedPackAuthoringHandlerEngine, "herzchen.packs.authoring")


def _coerce_content(value: bytes | bytearray | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise PackContentError("content updates must be bytes or UTF-8 text")


__all__ = [
    "AuthoringResult", "CompatibilityDescription", "ExecutionPin", "ManagedPack",
    "ManagedPackAuthoringHandler", "ManagedResource", "ManagedSourceIdentity",
    "MANAGED_PACK_KIND", "PACK_SCHEMA_REVISION", "PackAuthoringError", "domain_contribution",
    "PackContentError", "PackLoaderUnavailableError", "PackPathError",
    "PackProvenanceError", "describe_compatibility", "read_managed_pack",
    "verify_skill_export",
]
