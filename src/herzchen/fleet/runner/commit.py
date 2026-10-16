"""Commit identity of a work tree: its HEAD sha, plus a digest of uncommitted state when it is dirty."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess

_TIMEOUT_SECONDS = 30.0
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _git(cwd: str, *args: str) -> bytes | None:
    try:
        done = subprocess.run(["git", "-C", cwd, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def git_commit_identity(cwd: str) -> str | None:
    """``<sha>`` for a clean work tree, ``<sha>+dirty-<16 hex>`` otherwise, None when there is no commit."""
    cwd = os.fspath(cwd)
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.strip() != b"true":
        return None
    head = _git(cwd, "rev-parse", "--verify", "HEAD")
    if head is None:
        return None
    sha = head.decode("ascii", "replace").strip()
    if not _SHA.fullmatch(sha):
        return None
    status = _git(cwd, "status", "--porcelain=v1", "-z")
    if status is None:
        return None
    if not status:
        return sha
    diff = _git(cwd, "diff", "HEAD", "--binary")
    untracked = _git(cwd, "ls-files", "-o", "--exclude-standard", "-z")
    if diff is None or untracked is None:
        return None
    digest = hashlib.sha256(diff)
    for name in untracked.split(b"\0"):
        if not name:
            continue
        try:
            with open(os.path.join(cwd, os.fsdecode(name)), "rb") as handle:
                data = handle.read()
        except OSError:
            return None
        digest.update(name + b"\0" + data)
    return "%s+dirty-%s" % (sha, digest.hexdigest()[:16])
