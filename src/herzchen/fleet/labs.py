"""Labs: isolated git clones of a line checkout, each used by one worker at a time.

A lab is a directory of its own under ``labs_root``: a full clone of the line (``git clone
--no-checkout``) on branch ``lab/<name>``, with the shared dependency directories APFS-cloned from
the template and the virtualenv rewritten to name the lab. Workers edit labs; the line checkout is
never written by a worker.

The caller owns the policy: when to park or sweep, which labs are orphans, which paths are exempt
from capture, and which checkpoint writes the commit. This module enforces the mechanics that keep
work safe. A lab directory is unlinked only after its dirty work has been committed through the
checkpoint, the lab has been re-checked clean, and its HEAD has been captured as
``refs/labs/<name>`` in the line. That is the same capture-before-unlink rule as
``herzchen.authoring.writer_lease``. A writer holds a shared flock on its lab for the whole of its
work; park, remove and sweep need the exclusive flock, so a lab with a live writer is never
unlinked.

Labs live outside the line checkout, as siblings of it, so the host's nested-workspace guard holds:
a lab never sits inside the tree it was cloned from. The constructor refuses any layout where that
would be true.
"""

from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import errno
import fcntl
import fnmatch
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from typing import Any, Callable, Iterator, Optional, Sequence

from .hosts.contract import TurnSpec


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SITE_FILES = ("__editable__*", "*.pth", "*.egg-link", "direct_url.json")
_GIT_TIMEOUT = 120
_COPY_TIMEOUT = 600


class LabError(RuntimeError):
    """A lab operation failed. Whatever it protected was kept."""


class LabRefused(LabError):
    """The lab, the line or the request does not admit this operation."""


class LabBusy(LabRefused):
    """The lab's lock is held: a writer is active, or another operation owns the lab."""


@dataclass(frozen=True)
class ParkResult:
    name: str
    commit: str
    tree: str
    committed: bool


@dataclass(frozen=True)
class RemoveResult:
    name: str
    commit: str
    kept_ref: bool


@dataclass(frozen=True)
class SweepResult:
    name: str
    action: str
    detail: str


def _run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(list(argv), capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise LabError("command timed out: " + " ".join(argv[:4])) from exc


def _git(repo: Path, *args: str) -> str:
    done = _run(["git", "-C", str(repo), *args], _GIT_TIMEOUT)
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise LabError("git %s failed in %s: %s" % (args[0], repo, detail))
    return done.stdout.decode("utf-8", "surrogateescape")


def _resolve(repo: Path, ref: str) -> Optional[str]:
    done = _run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref], _GIT_TIMEOUT)
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8").strip() or None


def _is_lab_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _within(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def _single_component(name: Any) -> bool:
    return (isinstance(name, str) and name not in ("", ".", "..")
            and "/" not in name and "\x00" not in name)


def _exempt_path(rel: str, exempt: Sequence[str]) -> bool:
    return any(rel == item or rel.startswith(item.rstrip("/") + "/") for item in exempt)


def _work(path: Path, exempt: Sequence[str]) -> list:
    """Dirty entries as (porcelain XY, every path git named, the paths not exempt).

    A rename or copy is two NUL-separated fields in ``-z`` output (new path, then origin); both are
    named so that the checkpoint stages both sides of the move.
    """
    fields = _git(path, "status", "--porcelain", "-z", "--untracked-files=all").split("\0")
    records = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry:
            continue
        code, paths = entry[:2], [entry[3:]]
        if "R" in code or "C" in code:
            if index < len(fields):
                paths.append(fields[index])
                index += 1
        kept = tuple(item for item in paths if not _exempt_path(item, exempt))
        if kept:
            records.append((code, tuple(paths), kept))
    return records


def _lines(records: list) -> list:
    return [code + " " + " <- ".join(paths) for code, paths, _kept in records]


def _paths_to_commit(records: list) -> list:
    paths: list = []
    for _code, _paths, kept in records:
        for item in kept:
            if item not in paths:
                paths.append(item)
    return paths


@dataclass(frozen=True)
class Lab:
    """One lab directory. ``exempt`` is the fleet's exempt list, applied by ``dirty()``."""

    name: str
    path: Path
    branch: str
    exempt: tuple = field(default=(), repr=False)

    def head(self) -> str:
        return _git(self.path, "rev-parse", "HEAD").strip()

    def tree(self) -> str:
        return _git(self.path, "rev-parse", "HEAD^{tree}").strip()

    def dirty(self) -> list:
        return _lines(_work(self.path, self.exempt))

    def codex_turn_spec(self, executable: str, model: str, reasoning: str, prompt: str) -> TurnSpec:
        return TurnSpec(executable=executable, workspace=str(self.path), prompt=prompt,
                        model=model, reasoning=reasoning, profile="workspace-write", writable_roots=())

    def claude_turn_spec(self, executable: str, model: str, reasoning: str, prompt: str,
                         state_root: str, tools: Sequence[str], allowed_tools: Sequence[str]) -> TurnSpec:
        return TurnSpec(executable=executable, workspace=str(self.path), prompt=prompt,
                        model=model, reasoning=reasoning, profile="workspace-write", writable_roots=(),
                        options={"tools": tuple(tools), "allowed_tools": tuple(allowed_tools),
                                 "state_root": state_root})


@contextmanager
def _raise_on_signals() -> Iterator[None]:
    """Turn SIGTERM and SIGINT into LabError while a build runs, so the build's cleanup runs.

    Signal handlers can only be installed from the main thread; elsewhere the build runs unguarded.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def interrupted(signum: int, frame: Any) -> None:
        raise LabError("interrupted by signal %d" % signum)

    previous = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, signal.SIG_DFL if handler is None else handler)


def _venv_files(venv: Path) -> list:
    """Regular files that may name the venv's location: bin/*, pyvenv.cfg, and site-packages hooks.

    Symlinked directories are never entered, so no write can leave the venv.
    """
    found = []
    for dirpath, _dirnames, filenames in os.walk(venv):
        here = Path(dirpath)
        parts = here.relative_to(venv).parts
        for name in filenames:
            candidate = here / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            in_site = (len(parts) >= 3 and parts[0] == "lib" and parts[2] == "site-packages"
                       and name != "RECORD" and any(fnmatch.fnmatchcase(name, pat) for pat in _SITE_FILES))
            if parts[:1] == ("bin",) or (parts == () and name == "pyvenv.cfg") or in_site:
                found.append(candidate)
    return found


def _rewrite_file(path: Path, old: bytes, new: bytes) -> None:
    """Replace the template's path with the lab's, atomically, and only for plain text."""
    data = path.read_bytes()
    if old not in data or b"\x00" in data:
        return
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".rewrite-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.replace(old, new))
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class LabFleet:
    """The labs under one ``labs_root``, cloned from ``repo`` (and shared deps from ``template``).

    ``checkpoint`` is called as ``checkpoint(worktree, paths, message=...)`` and is the only way a
    park commits. Its return value is not trusted: a lab is kept unless it is verifiably clean.
    """

    def __init__(self, repo: Any, labs_root: Any, *, checkpoint: Callable[..., Any],
                 template: Any = None, shared_dirs: Sequence[str] = (".venv", "node_modules"),
                 exempt: Sequence[str] = ()) -> None:
        self.repo = Path(repo).resolve()
        self.labs_root = Path(labs_root).resolve(strict=False)
        self.template = Path(template).resolve() if template is not None else self.repo
        for root in (self.repo, self.template):
            if _within(self.labs_root, root) or _within(root, self.labs_root):
                raise LabRefused("labs must sit outside the line and the template, and neither may sit inside labs")
        self.checkpoint = checkpoint
        self.shared_dirs = tuple(shared_dirs)
        if not all(_single_component(item) for item in self.shared_dirs):
            raise LabRefused("shared directories are single names inside the line")
        self.exempt = tuple(exempt)

    # -- reading ----------------------------------------------------------------------------------

    def names(self) -> list:
        if not self.labs_root.is_dir():
            return []
        return sorted(entry.name for entry in self.labs_root.iterdir()
                      if not entry.name.startswith(".") and _is_lab_dir(entry)
                      and not self._marker(entry.name).exists())

    def get(self, name: str) -> Lab:
        self._check_name(name)
        if self._marker(name).exists() or not _is_lab_dir(self.labs_root / name):
            raise LabRefused("no lab named %s" % name)
        return self._lab(name)

    @contextmanager
    def writing(self, name: str) -> Iterator[None]:
        """Hold the lab shared for the duration of one worker's writes. Refused while an exclusive holder exists."""
        with self._hold(name, fcntl.LOCK_SH, "lab %s is held by a writer or an operation" % name):
            yield

    # -- create and resume ------------------------------------------------------------------------

    def create(self, name: str, base: str = "HEAD") -> Lab:
        self._check_name(name)
        start = _resolve(self.repo, base + "^{commit}")
        if start is None:
            raise LabRefused("base %s does not name a commit in the line" % base)
        with self._hold(name, fcntl.LOCK_EX, "lab %s is busy" % name):
            path = self.labs_root / name
            if (path.exists() or path.is_symlink()) and not self._marker(name).exists():
                raise LabRefused("lab %s already exists" % name)
            if _resolve(self.repo, "refs/labs/" + name) is not None:
                raise LabRefused("refs/labs/%s is already parked; resume it or pick another name" % name)
            self._refuse_dirty(self.repo, "the line")
            if self.template != self.repo and self._is_worktree(self.template):
                self._refuse_dirty(self.template, "the template")
            self._discard_stale(name, path)
            self._populate(name, path, start)
        return self._lab(name)

    def resume(self, name: str) -> Lab:
        self._check_name(name)
        with self._hold(name, fcntl.LOCK_EX, "lab %s is busy" % name):
            path = self.labs_root / name
            if (path.exists() or path.is_symlink()) and not self._marker(name).exists():
                raise LabRefused("lab %s already exists" % name)
            start = _resolve(self.repo, "refs/labs/" + name + "^{commit}")
            if start is None:
                raise LabRefused("nothing is parked as %s" % name)
            self._discard_stale(name, path)
            self._populate(name, path, start)
        return self._lab(name)

    # -- park, remove, sweep ----------------------------------------------------------------------

    def park(self, name: str, before_unlink: Optional[Callable[[Path], Any]] = None) -> ParkResult:
        with self._hold(name, fcntl.LOCK_EX, "lab %s is held by a writer" % name):
            return self._park_locked(name, before_unlink)

    def remove(self, name: str, merged_into: Optional[str] = None,
               before_unlink: Optional[Callable[[Path], Any]] = None) -> RemoveResult:
        """Unlink a clean lab. Never commits: dirty work is refused, not checkpointed."""
        with self._hold(name, fcntl.LOCK_EX, "lab %s is held by a writer" % name):
            lab = self._existing(name)
            leftover = lab.dirty()
            if leftover:
                raise LabRefused("remove refuses: %s has uncommitted work: %s" % (name, "; ".join(leftover)))
            head = lab.head()
            self._capture(lab)
            merged = merged_into is not None and self._is_ancestor(head, merged_into)
            self._unlink(lab, before_unlink)
            if merged:
                _git(self.repo, "update-ref", "-d", "refs/labs/" + name)
            return RemoveResult(name, head, kept_ref=not merged)

    def sweep(self, is_orphan: Callable[[str], bool],
              before_unlink: Optional[Callable[[Path], Any]] = None) -> list:
        results = [self._sweep_one(name, is_orphan, before_unlink) for name in self.names()]
        return [result for result in results if result is not None]

    # -- internals --------------------------------------------------------------------------------

    def _check_name(self, name: Any) -> None:
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise LabRefused("lab name %r is not allowed: letters, digits, '.', '_' and '-', starting with a letter or digit" % (name,))

    def _marker(self, name: str) -> Path:
        return self.labs_root / ".creating" / name

    def _lab(self, name: str) -> Lab:
        return Lab(name, self.labs_root / name, "lab/" + name, self.exempt)

    def _existing(self, name: str) -> Lab:
        if self._marker(name).exists() or not _is_lab_dir(self.labs_root / name):
            raise LabRefused("no lab named %s to act on" % name)
        return self._lab(name)

    @contextmanager
    def _hold(self, name: str, operation: int, busy: str) -> Iterator[None]:
        """Flock the lab's lock file. The file is never deleted, so every holder locks the same inode."""
        self._check_name(name)
        locks = self.labs_root / ".locks"
        locks.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(locks / (name + ".lock"), flags, 0o600)
        try:
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EACCES):
                    raise LabBusy(busy) from exc
                raise LabError("lab lock could not be taken for %s" % name) from exc
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _is_worktree(self, path: Path) -> bool:
        done = _run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], _GIT_TIMEOUT)
        return done.returncode == 0 and done.stdout.decode("utf-8").strip() == "true"

    def _refuse_dirty(self, repo: Path, label: str) -> None:
        lines = [line for line in _git(repo, "status", "--porcelain").split("\n") if line]
        if lines:
            raise LabRefused("%s has uncommitted work; commit it before creating a lab: %s"
                             % (label, "; ".join(lines[:20])))

    def _discard_stale(self, name: str, path: Path) -> None:
        """A marker means a create or resume died mid-build. Nothing in that directory was ever handed out."""
        marker = self._marker(name)
        if not marker.exists():
            return
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        marker.unlink()

    def _populate(self, name: str, path: Path, start: str) -> None:
        marker = self._marker(name)
        with _raise_on_signals():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("creating\n")
            try:
                done = _run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout",
                             str(self.repo), str(path)], _GIT_TIMEOUT)
                if done.returncode != 0:
                    raise LabError("clone of the line failed: " + done.stderr.decode("utf-8", "replace").strip())
                _git(path, "checkout", "-q", "-b", "lab/" + name, start)
                self._copy_shared(path)
                self._rewrite_venv(path)
            except BaseException:
                shutil.rmtree(path, ignore_errors=True)
                marker.unlink(missing_ok=True)
                raise
            marker.unlink()

    def _copy_shared(self, path: Path) -> None:
        for item in self.shared_dirs:
            source = self.template / item
            if not os.path.lexists(source):
                continue
            target = path / item
            if os.path.lexists(target):
                raise LabError("shared directory %s is already present in the lab" % item)
            done = _run(["cp", "-c", "-R", str(source), str(target)], _COPY_TIMEOUT)
            if done.returncode != 0:
                raise LabError("APFS clone of %s failed: %s" % (item, done.stderr.decode("utf-8", "replace").strip()))

    def _rewrite_venv(self, path: Path) -> None:
        venv = path / ".venv"
        if not _is_lab_dir(venv):
            return
        old = os.path.realpath(self.template).encode("utf-8")
        new = os.path.realpath(path).encode("utf-8")
        if old == new:
            return
        for target in _venv_files(venv):
            _rewrite_file(target, old, new)

    def _park_locked(self, name: str, before_unlink: Optional[Callable[[Path], Any]]) -> ParkResult:
        lab = self._existing(name)
        # Unstage first: the working tree is untouched, so no work is lost, and a staged rename or
        # staged add becomes plain paths that the checkpoint can stage (``git add`` rejects the
        # origin of a staged rename, which exists neither on disk nor in the index).
        _git(lab.path, "reset", "-q")
        records = _work(lab.path, self.exempt)
        before = lab.head()
        paths = _paths_to_commit(records)
        if paths:
            self.checkpoint(str(lab.path), paths, message="park " + name)
        leftover = lab.dirty()
        if leftover:
            raise LabRefused("park of %s left uncommitted work: %s" % (name, "; ".join(leftover)))
        committed = lab.head() != before
        self._capture(lab)
        head = lab.head()
        tree = lab.tree()
        self._unlink(lab, before_unlink)
        return ParkResult(name, head, tree, committed)

    def _capture(self, lab: Lab) -> None:
        """Keep the lab's HEAD in the line before anything is unlinked. A failure here keeps the lab."""
        _git(self.repo, "fetch", "--no-tags", str(lab.path), "lab/%s:refs/labs/%s" % (lab.name, lab.name))
        captured = _resolve(self.repo, "refs/labs/" + lab.name)
        if captured is None or captured != lab.head():
            raise LabError("capture of %s did not verify: refs/labs/%s is not the lab HEAD" % (lab.name, lab.name))

    def _unlink(self, lab: Lab, before_unlink: Optional[Callable[[Path], Any]]) -> None:
        if before_unlink is not None:
            before_unlink(lab.path)
        shutil.rmtree(lab.path)

    def _is_ancestor(self, sha: str, ref: str) -> bool:
        done = _run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor", sha, ref], _GIT_TIMEOUT)
        if done.returncode == 0:
            return True
        if done.returncode == 1:
            return False
        raise LabError("merge-base failed for %s: %s" % (ref, done.stderr.decode("utf-8", "replace").strip()))

    def _sweep_one(self, name: str, is_orphan: Callable[[str], bool],
                   before_unlink: Optional[Callable[[Path], Any]]) -> Optional[SweepResult]:
        try:
            if not is_orphan(name):
                return None
            with self._hold(name, fcntl.LOCK_EX, "lab %s is held by a writer" % name):
                parked = self._park_locked(name, before_unlink)
        except LabBusy as exc:
            return SweepResult(name, "skipped-running", str(exc))
        except Exception as exc:
            return SweepResult(name, "kept-error", repr(exc))
        return SweepResult(name, "parked", parked.commit)
