"""Install, stamp, link and inspect agent skill directories.

An installed skill is a versioned copy of a source skill tree stamped with its
edition, resolved path and source digest. A manifest next to the edition
directory records the digest of every installed file so drift can be detected.
Only paths passed to these functions are touched.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

MARKER = "> <!-- otto-edition -->"
MANIFEST_SCHEMA = "otto.skill-installation.v1"
_MAX_HOPS = 40
_IGNORED_NAMES = {".DS_Store"}
_IGNORED_DIRS = {"__pycache__"}
_STAMP_RE = re.compile(
    r"^> <!-- otto-edition --> Edition: (\S+) (\S+) · installed (\S+) · path (.+) · "
    r"source SKILL\.md sha256 ([0-9a-f]{64})\s*$"
)


class SkillInstallError(ValueError):
    """Raised when a skill cannot be installed, linked or verified safely."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_component(value: str, what: str) -> None:
    if not value or value in (".", "..") or "/" in value or os.sep in value or "\x00" in value:
        raise SkillInstallError(f"invalid {what}: {value!r}")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_lines(text: str) -> List[str]:
    return text.splitlines(keepends=True)


def _insertion_point(lines: List[str]) -> int:
    """Index where a new stamp line goes: after front matter and the first '# ' heading."""
    start = 0
    if lines and lines[0].rstrip("\r\n") == "---":
        for j in range(1, len(lines)):
            if lines[j].rstrip("\r\n") == "---":
                start = j + 1
                break
    for j in range(start, len(lines)):
        if lines[j].startswith("# "):
            return j + 1
    return start


def stamp_skill_text(
    text: str,
    *,
    name: str,
    edition: str,
    resolved_path: str,
    source_sha256: str,
    installed_at: str,
) -> str:
    """Replace the single otto-edition marker line, or insert one below the title."""
    line = (
        f"{MARKER} Edition: {name} {edition} · installed {installed_at} · "
        f"path {resolved_path} · source SKILL.md sha256 {source_sha256}"
    )
    lines = _split_lines(text)
    marker_idx = [i for i, existing in enumerate(lines) if existing.startswith(MARKER)]
    if len(marker_idx) > 1:
        raise SkillInstallError(f"expected at most one otto-edition marker line, found {len(marker_idx)}")
    if marker_idx:
        i = marker_idx[0]
        newline = "\n"
        if lines[i].endswith("\r\n"):
            newline = "\r\n"
        lines[i] = line + newline
    else:
        at = _insertion_point(lines)
        if at > 0 and not lines[at - 1].endswith(("\n", "\r")):
            lines[at - 1] += "\n"
        lines.insert(at, line + "\n")
    return "".join(lines)


def _iter_tree(root: str) -> List[tuple]:
    """Return sorted (relpath, abspath) for files under root, skipping ignored entries."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
        for fname in filenames:
            if fname in _IGNORED_NAMES or fname.endswith(".pyc"):
                continue
            abspath = os.path.join(dirpath, fname)
            rel = os.path.relpath(abspath, root).replace(os.sep, "/")
            out.append((rel, abspath))
    out.sort()
    return out


def _assert_no_symlinks(root: str) -> None:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for entry in dirnames + filenames:
            full = os.path.join(dirpath, entry)
            if os.path.islink(full):
                raise SkillInstallError(f"symlink not allowed in skill source: {full}")


def _tree_hashes(root: str) -> Dict[str, str]:
    if not os.path.isdir(root):
        return {}
    result = {}
    for rel, abspath in _iter_tree(root):
        with open(abspath, "rb") as fh:
            result[rel] = _sha256_bytes(fh.read())
    return result


def _build_payload(
    source_files: List[tuple],
    *,
    name: str,
    edition: str,
    resolved: str,
    source_sha: str,
    installed_at: str,
) -> Dict[str, bytes]:
    payload: Dict[str, bytes] = {}
    for rel, abspath in source_files:
        with open(abspath, "rb") as fh:
            data = fh.read()
        if rel == "SKILL.md":
            stamped = stamp_skill_text(
                data.decode("utf-8"),
                name=name,
                edition=edition,
                resolved_path=resolved,
                source_sha256=source_sha,
                installed_at=installed_at,
            )
            data = stamped.encode("utf-8")
        payload[rel] = data
    return payload


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SkillInstallError(f"manifest is not a JSON object: {path}")
    return data


def _write_atomic(path: str, text: str) -> None:
    parent = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=f".{os.path.basename(path)}.tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def install_skill_tree(
    source_dir,
    dest_root,
    *,
    name: str,
    edition: str,
    source_commit: Optional[str] = None,
    installed_at: Optional[str] = None,
) -> dict:
    """Copy and stamp a skill tree into dest_root/edition/name and write its manifest.

    Re-running with identical files returns the existing manifest (replayed=True).
    A different payload for an existing edition raises SkillInstallError.
    """
    _check_component(name, "skill name")
    _check_component(edition, "edition")
    source = os.path.realpath(os.fspath(source_dir))
    if not os.path.isdir(source):
        raise SkillInstallError(f"source is not a directory: {source}")
    skill_md_src = os.path.join(source, "SKILL.md")
    if not os.path.isfile(skill_md_src) or os.path.islink(skill_md_src):
        raise SkillInstallError(f"source has no regular SKILL.md: {source}")
    _assert_no_symlinks(source)

    with open(skill_md_src, "rb") as fh:
        source_sha = _sha256_bytes(fh.read())
    source_files = _iter_tree(source)

    dest_root_abs = os.path.realpath(os.fspath(dest_root))
    edition_dir = os.path.join(dest_root_abs, edition)
    dest_dir = os.path.join(edition_dir, name)
    resolved = os.path.realpath(dest_dir)
    manifest_path = os.path.join(edition_dir, f"installation-{name}.json")

    if os.path.lexists(dest_dir):
        if not os.path.exists(manifest_path):
            raise SkillInstallError(f"destination exists without a manifest; refusing to overwrite: {dest_dir}")
        existing = _load_json(manifest_path)
        payload = _build_payload(
            source_files,
            name=name,
            edition=edition,
            resolved=resolved,
            source_sha=source_sha,
            installed_at=str(existing.get("installed_at")),
        )
        expected = {rel: _sha256_bytes(data) for rel, data in payload.items()}
        if _tree_hashes(dest_dir) != expected:
            raise SkillInstallError(
                f"edition already installed with different content; refusing to overwrite: {dest_dir}"
            )
        result = dict(existing)
        result["replayed"] = True
        return result

    if os.path.lexists(manifest_path):
        raise SkillInstallError(f"manifest exists without a destination directory: {manifest_path}")

    installed_at = installed_at or _now_utc()
    payload = _build_payload(
        source_files,
        name=name,
        edition=edition,
        resolved=resolved,
        source_sha=source_sha,
        installed_at=installed_at,
    )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "name": name,
        "edition": edition,
        "source_dir": source,
        "source_commit": source_commit,
        "installed_at": installed_at,
        "path": resolved,
        "source_skill_sha256": source_sha,
        "files": {rel: _sha256_bytes(data) for rel, data in sorted(payload.items())},
    }

    os.makedirs(edition_dir, exist_ok=True)
    staging = tempfile.mkdtemp(dir=edition_dir, prefix=f".{name}.tmp-")
    try:
        for rel, abspath in source_files:
            target = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(payload[rel])
            shutil.copymode(abspath, target)
        os.chmod(staging, 0o755)
        if os.path.lexists(dest_dir):
            raise SkillInstallError(f"destination appeared during install: {dest_dir}")
        os.rename(staging, dest_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    _write_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result = dict(manifest)
    result["replayed"] = False
    return result


def link_skill(link_path, target_dir) -> dict:
    """Atomically point link_path at target_dir. Refuses to replace a non-symlink."""
    link = os.path.abspath(os.fspath(link_path))
    target = os.path.realpath(os.fspath(target_dir))
    if not os.path.isdir(target):
        raise SkillInstallError(f"link target is not a directory: {target}")
    previous = None
    if os.path.islink(link):
        previous = os.readlink(link)
    elif os.path.lexists(link):
        raise SkillInstallError(f"refusing to replace non-symlink: {link}")
    parent = os.path.dirname(link)
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f".{os.path.basename(link)}.tmp-{uuid.uuid4().hex[:8]}")
    os.symlink(target, tmp)
    try:
        os.replace(tmp, link)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise
    return {"link": link, "target": target, "previous": previous}


def which_skill(path) -> dict:
    """Follow a skill path's symlink chain and report its edition and drift from the manifest."""
    start = os.path.abspath(os.fspath(path))
    chain = [start]
    current = start
    seen = {start}
    hops = 0
    while os.path.islink(current):
        hops += 1
        if hops > _MAX_HOPS:
            raise SkillInstallError(f"too many symlink hops starting at {path}")
        raw = os.readlink(current)
        nxt = raw if os.path.isabs(raw) else os.path.join(os.path.dirname(current), raw)
        if nxt in seen:
            raise SkillInstallError(f"symlink cycle at {nxt}")
        seen.add(nxt)
        chain.append(os.path.normpath(nxt))
        current = nxt

    resolved = os.path.realpath(current)
    if not os.path.isdir(resolved):
        raise SkillInstallError(f"skill path does not resolve to a directory: {resolved}")

    skill_md = os.path.join(resolved, "SKILL.md")
    skill_md_sha = None
    edition_line = None
    stamped = False
    if os.path.isfile(skill_md):
        with open(skill_md, "rb") as fh:
            raw_bytes = fh.read()
        skill_md_sha = _sha256_bytes(raw_bytes)
        markers = [ln.rstrip("\r\n") for ln in raw_bytes.decode("utf-8", "replace").splitlines()
                   if ln.startswith(MARKER)]
        if markers:
            edition_line = markers[0]
            stamped = len(markers) == 1 and _STAMP_RE.match(edition_line) is not None

    parent = os.path.dirname(resolved)
    edition = os.path.basename(parent)
    base = os.path.basename(resolved)
    manifest = None
    manifest_path = None
    path_matches = False
    for cand in sorted(glob.glob(os.path.join(parent, "installation-*.json"))):
        try:
            data = _load_json(cand)
        except (OSError, ValueError):
            continue
        if os.path.realpath(str(data.get("path", ""))) == resolved:
            manifest, manifest_path, path_matches = data, cand, True
            break
    if manifest is None:
        cand = os.path.join(parent, f"installation-{base}.json")
        if os.path.exists(cand):
            try:
                manifest, manifest_path = _load_json(cand), cand
            except (OSError, ValueError):
                manifest = None

    drift: List[str] = []
    name = base
    if manifest is not None:
        name = str(manifest.get("name", base))
        expected = manifest.get("files", {})
        actual = _tree_hashes(resolved)
        drift = sorted(
            {rel for rel, digest in expected.items() if actual.get(rel) != digest}
            | {rel for rel in actual if rel not in expected}
        )

    return {
        "path": str(path),
        "chain": chain,
        "resolved": resolved,
        "name": name,
        "edition": edition,
        "skill_md": skill_md,
        "skill_md_sha256": skill_md_sha,
        "edition_line": edition_line,
        "stamped": stamped,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_path_matches": path_matches,
        "drift": drift,
    }


def verify_installation(manifest_path) -> dict:
    """Compare files on disk under a manifest's path against its recorded digests."""
    manifest = _load_json(os.fspath(manifest_path))
    root = str(manifest.get("path", ""))
    expected = manifest.get("files", {})
    actual = _tree_hashes(root)
    drift = sorted(
        {rel for rel, digest in expected.items() if actual.get(rel) != digest}
        | {rel for rel in actual if rel not in expected}
    )
    return {"ok": not drift, "drift": drift, "path": root, "manifest": os.fspath(manifest_path)}
