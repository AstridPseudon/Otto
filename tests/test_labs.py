"""Labs: isolated git clones of a line checkout, used by one worker at a time.

These tests target ``herzchen.fleet.labs`` (written in a later step). Until that module
exists the import below fails: that is the intended red run. Every test builds its own
line repo, fake venv and labs root under ``tmp_path``. No network, no model calls.

Sections:
  1. helpers and fixtures
  2. concurrent workers (test_two_workers_parallel)
  3. refused and clean removal (test_refuses_uncaptured_removal)
  4. sweep of orphan labs (test_sweep_commits_orphan)
  5. park and resume (test_park_resume_same_tree)
  6. create: shared deps, venv rewrite, refusals, crash cleanup
  7. ADAPTER TESTS (LAST SECTION): argv and fence checks. Details to be filled in from probe results.
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from herzchen.fleet.labs import LabError, LabFleet, LabRefused
from herzchen.fleet.hosts import ClaudeHost, CodexHost
from otto.portfolio.execution_operations import commit_local_checkpoint


# ---------------------------------------------------------------------------
# 1. helpers and fixtures
# ---------------------------------------------------------------------------

IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@t")

DIRTY_KINDS = ("modified", "untracked", "deleted", "staged-new", "staged-rename", "untracked-subdir")

# What a worker's dirty work looks like once it is committed (or parked) by a checkpoint.
# Maps dirty kind -> ({relative path: bytes that must be present}, [relative paths that must be absent]).
EXPECT_AFTER = {
    "modified": ({"src/pkg/mod.py": b"VALUE = 2\n"}, []),
    "untracked": ({"src/pkg/new.py": b"VALUE = 3\n"}, []),
    "deleted": ({}, ["src/pkg/mod.py"]),
    "staged-new": ({"src/pkg/staged.py": b"VALUE = 4\n"}, []),
    "staged-rename": ({"src/pkg/renamed.py": b"VALUE = 1\n"}, ["src/pkg/mod.py"]),
    "untracked-subdir": ({"src/pkg/sub/deeper/x.py": b"VALUE = 5\n"}, []),
}

FAKE_TOOL = """#!@LINE@/.venv/bin/python
import ast
import pathlib

root = pathlib.Path(__file__).parent.parent
finder = root / "lib" / "python3.11" / "site-packages" / "__editable___pkg_finder.py"
mapping = ast.literal_eval(finder.read_text().split("=", 1)[1].strip())
print(mapping["pkg"])
"""


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with a fixed identity and return stdout."""
    return subprocess.run(["git", "-C", str(repo), *IDENTITY, *args],
                          capture_output=True, text=True, check=True).stdout


def git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def ref_sha(repo: Path, ref: str) -> str | None:
    """The sha a ref resolves to in ``repo``, or None when it does not exist."""
    found = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref],
                           capture_output=True, text=True)
    return found.stdout.strip() or None


def snapshot(root: Path) -> dict:
    """Every entry under ``root`` except .git: files by bytes, symlinks by target (never followed), dirs by name."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(dirnames + filenames):
            if name == ".git":
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if os.path.islink(path):
                found[rel] = ("link", os.readlink(path))
            elif os.path.isdir(path):
                found[rel] = ("dir",)
            else:
                found[rel] = ("file", Path(path).read_bytes())
    return found


def digest(root: Path) -> str:
    """One hash over snapshot(root): byte-identical trees give equal digests."""
    return hashlib.sha256(repr(sorted(snapshot(root).items())).encode()).hexdigest()


def in_thread(fn) -> dict:
    """Run ``fn`` on another thread. Returns {"value": ...} on success or {"error": exc} on failure."""
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # the caller inspects what was raised
            outcome["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(60)
    assert not thread.is_alive(), "helper thread hung"
    return outcome


def commit_line(repo: Path, files: dict, message: str = "line change") -> None:
    """Write ``files`` into the line checkout and commit them (keeps the line clean)."""
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def build_line(root: Path) -> Path:
    """A tiny line repo with a fake venv (editable finder, .pth, shebang tool, activate) and node_modules."""
    line = root / "line"
    line.mkdir()
    git(line, "init", "-b", "main")
    (line / ".gitignore").write_text(".venv/\nnode_modules/\n")
    (line / "src" / "pkg").mkdir(parents=True)
    (line / "src" / "pkg" / "mod.py").write_text("VALUE = 1\n")
    (line / "README").write_text("line\n")
    git(line, "add", "-A")
    git(line, "commit", "-m", "init")

    venv = line / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    tool = venv / "bin" / "tool"
    tool.write_text(FAKE_TOOL.replace("@LINE@", str(line)))
    tool.chmod(0o755)
    (venv / "bin" / "activate").write_text(f"VIRTUAL_ENV={line}/.venv\nexport VIRTUAL_ENV\n")
    site = venv / "lib" / "python3.11" / "site-packages"
    site.mkdir(parents=True)
    (site / "__editable___pkg_finder.py").write_text(f"MAPPING = {{'pkg': '{line}/src/pkg'}}\n")
    (site / "__editable__.pkg.pth").write_text(f"{line}/src\n")

    (line / "node_modules" / "dep").mkdir(parents=True)
    (line / "node_modules" / "dep" / "index.js").write_text("module.exports = 1\n")
    return line


def make_dirty(kind: str, lab: Path) -> None:
    """Put one kind of uncommitted work into ``lab``. Each kind is what a worker can leave behind."""
    pkg = lab / "src" / "pkg"
    if kind == "modified":
        (pkg / "mod.py").write_text("VALUE = 2\n")
    elif kind == "untracked":
        (pkg / "new.py").write_text("VALUE = 3\n")
    elif kind == "deleted":
        (pkg / "mod.py").unlink()
    elif kind == "staged-new":
        (pkg / "staged.py").write_text("VALUE = 4\n")
        git(lab, "add", "src/pkg/staged.py")
    elif kind == "staged-rename":
        git(lab, "mv", "src/pkg/mod.py", "src/pkg/renamed.py")
    elif kind == "untracked-subdir":
        (pkg / "sub" / "deeper").mkdir(parents=True)
        (pkg / "sub" / "deeper" / "x.py").write_text("VALUE = 5\n")
    else:
        raise AssertionError("unknown dirty kind: " + kind)


def new_fleet(line: Path, labs_root: Path, checkpoint=commit_local_checkpoint, **kwargs) -> LabFleet:
    return LabFleet(repo=line, labs_root=labs_root, checkpoint=checkpoint, **kwargs)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Resolved base directory: /var is a symlink to /private/var on macOS, so compare resolved paths only."""
    return tmp_path.resolve()


@pytest.fixture
def line(root: Path) -> Path:
    return build_line(root)


@pytest.fixture
def labs_root(root: Path) -> Path:
    """Sibling of the line checkout. Not created up front: the fleet owns it."""
    return root / "labs"


# ---------------------------------------------------------------------------
# 2. concurrent workers
# ---------------------------------------------------------------------------

def test_two_workers_parallel(root, line, labs_root):
    """Two workers edit their own labs at the same time; a bystander lab and the line stay byte-identical."""
    commit_line(line, {**{f"src/pkg/t{i}.py": f"T = {i}\n" for i in range(25)},
                       **{f"src/pkg/del{i}.py": f"D = {i}\n" for i in range(5)}})
    fleet = new_fleet(line, labs_root)
    alpha = fleet.create("alpha")
    bravo = fleet.create("bravo")
    charlie = fleet.create("charlie")          # bystander: no worker ever touches it
    line_before = digest(line)
    charlie_before = snapshot(charlie.path)

    barrier = threading.Barrier(2)
    errors: list = []

    def work(name: str, tag: str) -> None:
        try:
            barrier.wait(30)
            pkg = fleet.get(name).path / "src" / "pkg"
            with fleet.writing(name):
                for i in range(25):                           # tracked edits
                    (pkg / f"t{i}.py").write_text(f"{tag} edit {i}\n")
                for i in range(20):                           # new files
                    (pkg / f"{tag}_new_{i}.py").write_text(f"{tag} new {i}\n")
                for i in range(5):                            # deletes
                    (pkg / f"del{i}.py").unlink()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=("alpha", "alpha")),
               threading.Thread(target=work, args=("bravo", "bravo"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []

    # The labs are siblings: neither is inside the other, or inside the line.
    for lab in (alpha, bravo, charlie):
        assert lab.path.parent == labs_root
        assert not lab.path.is_relative_to(line)
        assert not line.is_relative_to(lab.path)
    assert not alpha.path.is_relative_to(bravo.path)
    assert not bravo.path.is_relative_to(alpha.path)

    # The line checkout and the bystander lab did not change at all.
    assert digest(line) == line_before
    assert snapshot(charlie.path) == charlie_before

    # Each worker's lab shows only its own edits.
    for lab, tag, other in ((alpha, "alpha", "bravo"), (bravo, "bravo", "alpha")):
        files = snapshot(lab.path)
        for i in range(25):
            assert files[f"src/pkg/t{i}.py"] == ("file", f"{tag} edit {i}\n".encode())
        for i in range(20):
            assert files[f"src/pkg/{tag}_new_{i}.py"] == ("file", f"{tag} new {i}\n".encode())
        for i in range(5):
            assert f"src/pkg/del{i}.py" not in files
        assert not any(other in rel for rel in files)
        assert not any(other in line_text for line_text in lab.dirty())
        assert lab.branch == f"lab/{tag}"


# ---------------------------------------------------------------------------
# 3. removal: refuses dirty and leased labs, captures clean ones
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", DIRTY_KINDS)
def test_refuses_uncaptured_removal(line, labs_root, kind):
    """Dirty work is never discarded: remove refuses, and the lab and the line are untouched."""
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("w1")
    make_dirty(kind, lab.path)
    dirty_before = lab.dirty()
    files_before = snapshot(lab.path)
    assert dirty_before, "the " + kind + " edit must make the lab dirty"

    with pytest.raises(LabRefused):
        fleet.remove("w1")

    assert lab.path.is_dir()
    assert snapshot(lab.path) == files_before
    assert lab.dirty() == dirty_before
    assert ref_sha(line, "refs/labs/w1") is None
    assert git(line, "branch", "--list", "lab/*").strip() == ""


def test_refuses_removal_while_writer_holds_lease(line, labs_root):
    """A writer in another thread holds the lease: remove refuses even though the lab is clean."""
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("w1")
    with fleet.writing("w1"):
        outcome = in_thread(lambda: fleet.remove("w1"))
    assert isinstance(outcome.get("error"), LabRefused), outcome
    assert lab.path.is_dir()
    assert ref_sha(line, "refs/labs/w1") is None


def test_clean_remove_captures_ref_and_unlinks(line, labs_root):
    """A clean lab with new commits: HEAD is captured under refs/labs/<name>, then the directory goes."""
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("w1")
    git(lab.path, "commit", "--allow-empty", "-m", "lab work")
    head = lab.head()
    seen: list = []

    def before_unlink(path) -> None:
        seen.append((Path(path), Path(path).is_dir()))

    result = fleet.remove("w1", before_unlink=before_unlink)

    assert result.name == "w1"
    assert result.commit == head
    assert result.kept_ref is True
    assert seen == [(lab.path, True)]          # called once, while the directory still existed
    assert not lab.path.exists()
    assert ref_sha(line, "refs/labs/w1") == head


def test_clean_remove_merged_deletes_capture_ref(line, labs_root):
    """With merged_into naming a ref that contains HEAD, the capture ref is deleted afterwards."""
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("w2")
    git(lab.path, "commit", "--allow-empty", "-m", "lab work")
    head = lab.head()
    git(line, "fetch", str(lab.path), "lab/w2:refs/heads/landed")   # the work has landed in the line
    seen: list = []

    result = fleet.remove("w2", merged_into="landed",
                          before_unlink=lambda path: seen.append((Path(path), Path(path).is_dir())))

    assert result.commit == head
    assert result.kept_ref is False
    assert seen == [(lab.path, True)]
    assert not lab.path.exists()
    assert ref_sha(line, "refs/labs/w2") is None


# ---------------------------------------------------------------------------
# 4. sweep: orphan labs are parked, everything else is left alone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", DIRTY_KINDS)
def test_sweep_commits_orphan(root, line, labs_root, kind):
    """Orphan dirty work is committed and captured; a leased orphan and a non-orphan are untouched."""
    fleet = new_fleet(line, labs_root)
    orphan = fleet.create("orphan")
    make_dirty(kind, orphan.path)
    keep = fleet.create("keep")
    make_dirty("untracked", keep.path)
    busy = fleet.create("busy")
    make_dirty("untracked", busy.path)
    keep_before = (snapshot(keep.path), keep.dirty())
    busy_before = snapshot(busy.path)

    with fleet.writing("busy"):                    # a worker is still in this lab
        outcome = in_thread(lambda: fleet.sweep(lambda name: name in ("orphan", "busy")))
    assert "error" not in outcome, outcome.get("error")
    results = {result.name: result for result in outcome["value"]}

    assert "keep" not in results                   # non-orphans are not even considered
    assert results["orphan"].action == "parked"
    sha = ref_sha(line, "refs/labs/orphan")
    assert sha is not None
    assert results["orphan"].detail == sha
    assert results["busy"].action == "skipped-running"
    assert not orphan.path.exists()
    assert snapshot(busy.path) == busy_before
    assert (snapshot(keep.path), keep.dirty()) == keep_before

    present, absent = EXPECT_AFTER[kind]
    for rel, content in present.items():
        assert git_bytes(line, "show", f"refs/labs/orphan:{rel}") == content
    committed = git(line, "ls-tree", "-r", "--name-only", "refs/labs/orphan").splitlines()
    for rel in absent:
        assert rel not in committed

    resumed = fleet.resume("orphan")
    for rel, content in present.items():
        assert (resumed.path / rel).read_bytes() == content
    for rel in absent:
        assert not (resumed.path / rel).exists()
    assert resumed.branch == "lab/orphan"
    assert resumed.dirty() == []


def test_sweep_keeps_lab_when_symlink_escapes(root, line, labs_root):
    """A symlink pointing outside the lab makes the real checkpoint refuse: kept-error, every file intact."""
    outside = root / "outside.txt"
    outside.write_text("secret\n")
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("esc")
    (lab.path / "src" / "pkg" / "ok.py").write_text("OK = 1\n")
    os.symlink(outside, lab.path / "src" / "pkg" / "link.py")
    before = snapshot(lab.path)
    dirty_before = lab.dirty()

    results = {result.name: result for result in fleet.sweep(lambda name: name == "esc")}

    assert results["esc"].action == "kept-error"
    assert results["esc"].detail
    assert lab.path.is_dir()
    assert snapshot(lab.path) == before
    assert lab.dirty() == dirty_before
    assert ref_sha(line, "refs/labs/esc") is None
    assert outside.read_text() == "secret\n"


def test_sweep_keeps_lab_when_checkpoint_raises(root, line, labs_root):
    """A checkpoint that raises keeps the lab exactly as it was; sweep returns normally."""

    def failing(worktree, paths, *, message):
        raise RuntimeError("checkpoint exploded")

    fleet = new_fleet(line, labs_root, checkpoint=failing)
    lab = fleet.create("boom")
    make_dirty("untracked", lab.path)
    before = snapshot(lab.path)

    results = {result.name: result for result in fleet.sweep(lambda name: True)}

    assert results["boom"].action == "kept-error"
    assert snapshot(lab.path) == before
    assert ref_sha(line, "refs/labs/boom") is None


def test_sweep_keeps_lab_when_checkpoint_commits_nothing(root, line, labs_root):
    """A checkpoint that claims success but commits nothing leaves dirty work: the lab is never unlinked."""

    def lying(worktree, paths, *, message):
        return {"committed": False}

    fleet = new_fleet(line, labs_root, checkpoint=lying)
    lab = fleet.create("liar")
    make_dirty("modified", lab.path)
    make_dirty("untracked-subdir", lab.path)
    before = snapshot(lab.path)

    results = {result.name: result for result in fleet.sweep(lambda name: True)}

    assert results["liar"].action == "kept-error"
    assert lab.path.is_dir()
    assert snapshot(lab.path) == before
    assert lab.dirty()
    assert ref_sha(line, "refs/labs/liar") is None


# ---------------------------------------------------------------------------
# 5. park and resume
# ---------------------------------------------------------------------------

def test_park_resume_same_tree(root, line, labs_root):
    """Parking mixed dirty work and resuming it reproduces the same tree, contents, branch and deps."""
    commit_line(line, {"src/pkg/gone.py": "GONE = 1\n", "src/pkg/old.py": "OLD = 1\n"})
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("mix")
    pkg = lab.path / "src" / "pkg"
    (pkg / "mod.py").write_text("VALUE = 2\n")                       # modified
    (pkg / "new.py").write_text("NEW = 1\n")                         # untracked
    (pkg / "gone.py").unlink()                                       # deleted
    (pkg / "staged.py").write_text("STAGED = 1\n")                   # staged new
    git(lab.path, "add", "src/pkg/staged.py")
    git(lab.path, "mv", "src/pkg/old.py", "src/pkg/moved.py")        # staged rename
    (pkg / "sub" / "deeper").mkdir(parents=True)                     # file in a new untracked subdir
    (pkg / "sub" / "deeper" / "x.py").write_text("DEEP = 1\n")
    expected = {
        "src/pkg/mod.py": b"VALUE = 2\n",
        "src/pkg/new.py": b"NEW = 1\n",
        "src/pkg/staged.py": b"STAGED = 1\n",
        "src/pkg/moved.py": b"OLD = 1\n",
        "src/pkg/sub/deeper/x.py": b"DEEP = 1\n",
    }

    park = fleet.park("mix")

    assert park.name == "mix"
    assert park.committed is True
    assert not lab.path.exists()
    assert ref_sha(line, "refs/labs/mix") == park.commit
    assert git(line, "rev-parse", park.commit + "^{tree}").strip() == park.tree

    resumed = fleet.resume("mix")

    assert resumed.tree() == park.tree
    assert resumed.head() == park.commit
    assert resumed.branch == "lab/mix"
    assert git(resumed.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "lab/mix"
    for rel, content in expected.items():
        assert (resumed.path / rel).read_bytes() == content
    assert not (resumed.path / "src" / "pkg" / "gone.py").exists()
    assert not (resumed.path / "src" / "pkg" / "old.py").exists()
    assert (resumed.path / ".venv" / "bin" / "python").exists()
    assert (resumed.path / "node_modules" / "dep" / "index.js").is_file()
    activate = (resumed.path / ".venv" / "bin" / "activate").read_text()
    assert f"VIRTUAL_ENV={resumed.path}/.venv" in activate
    assert str(line) not in activate
    assert resumed.dirty() == []


def test_park_clean_lab_same_tree(root, line, labs_root):
    """A clean lab parks with committed False and resumes to the same tree."""
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("clean")
    head_before = lab.head()
    tree_before = lab.tree()

    park = fleet.park("clean")

    assert park.committed is False
    assert park.commit == head_before
    assert park.tree == tree_before
    assert not lab.path.exists()

    resumed = fleet.resume("clean")
    assert resumed.tree() == park.tree
    assert resumed.head() == park.commit


def test_park_and_resume_refusals(root, line, labs_root):
    """Parking twice, resuming without a capture, and resuming onto an existing directory are all refused."""
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("ref")
    make_dirty("untracked", lab.path)
    fleet.park("ref")

    with pytest.raises(LabRefused):
        fleet.park("ref")                                  # already parked: no lab to park
    with pytest.raises(LabRefused):
        fleet.resume("never-parked")                       # no refs/labs/never-parked

    (labs_root / "ref").mkdir()                            # something now sits where the lab would go
    with pytest.raises(LabRefused):
        fleet.resume("ref")
    (labs_root / "ref").rmdir()

    assert fleet.resume("ref").branch == "lab/ref"


def test_park_refused_while_writer_holds_lease(root, line, labs_root):
    fleet = new_fleet(line, labs_root)
    lab = fleet.create("lease")
    make_dirty("untracked", lab.path)
    before = snapshot(lab.path)

    with fleet.writing("lease"):
        outcome = in_thread(lambda: fleet.park("lease"))

    assert isinstance(outcome.get("error"), LabRefused), outcome
    assert lab.path.is_dir()
    assert snapshot(lab.path) == before
    assert ref_sha(line, "refs/labs/lease") is None


# ---------------------------------------------------------------------------
# 6. create
# ---------------------------------------------------------------------------

def test_create_clones_deps_and_rewrites_venv(root, line, labs_root):
    """Deps are APFS-cloned per lab, the venv names the lab not the line, and the line's venv is untouched."""
    fleet = new_fleet(line, labs_root)
    line_venv_before = snapshot(line / ".venv")

    lab = fleet.create("c1")

    assert lab.path == labs_root / "c1"
    assert lab.branch == "lab/c1"
    assert fleet.get("c1").path == lab.path
    assert "c1" in fleet.names()
    assert snapshot(line / ".venv") == line_venv_before

    # node_modules is a clone, not a shared directory.
    assert (lab.path / "node_modules" / "dep" / "index.js").read_text() == "module.exports = 1\n"
    (lab.path / "node_modules" / "dep" / "index.js").write_text("changed in the lab\n")
    assert (line / "node_modules" / "dep" / "index.js").read_text() == "module.exports = 1\n"

    # Editable finder and .pth name the lab.
    finder = (lab.path / ".venv" / "lib" / "python3.11" / "site-packages" / "__editable___pkg_finder.py").read_text()
    assert f"{lab.path}/src/pkg" in finder
    assert str(line) not in finder
    pth = (lab.path / ".venv" / "lib" / "python3.11" / "site-packages" / "__editable__.pkg.pth").read_text()
    assert f"{lab.path}/src" in pth
    assert str(line) not in pth

    # Shebang and activate name the lab.
    tool = (lab.path / ".venv" / "bin" / "tool").read_text()
    assert tool.splitlines()[0] == f"#!{lab.path}/.venv/bin/python"
    assert str(line) not in tool
    activate = (lab.path / ".venv" / "bin" / "activate").read_text()
    assert f"VIRTUAL_ENV={lab.path}/.venv" in activate
    assert str(line) not in activate

    # The rewritten tool runs and prints the lab's mapping path.
    run = subprocess.run([str(lab.path / ".venv" / "bin" / "tool")], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == f"{lab.path}/src/pkg"


def test_create_refuses_dirty_line(root, line, labs_root):
    fleet = new_fleet(line, labs_root)
    (line / "src" / "pkg" / "mod.py").write_text("VALUE = 9\n")          # tracked and modified

    with pytest.raises(LabRefused):
        fleet.create("d1")
    assert not (labs_root / "d1").exists()
    assert ref_sha(line, "refs/labs/d1") is None


@pytest.mark.parametrize("case", ["labs-inside-repo", "repo-inside-labs", "template-inside-labs"])
def test_constructor_refuses_nested_roots(root, line, case):
    labs_root = root / "labs"
    kwargs: dict = {}
    if case == "labs-inside-repo":
        labs_root = line / "labs"
    elif case == "repo-inside-labs":
        labs_root = root                                  # the line sits inside this root
    else:
        labs_root.mkdir()
        (labs_root / "tpl").mkdir()
        kwargs["template"] = labs_root / "tpl"

    with pytest.raises(LabRefused):
        new_fleet(line, labs_root, **kwargs)


@pytest.mark.parametrize("name", ["", "../x", ".hidden", "a/b"])
def test_create_refuses_bad_names(line, labs_root, name):
    fleet = new_fleet(line, labs_root)
    with pytest.raises(LabRefused):
        fleet.create(name)
    assert git(line, "branch", "--list", "lab/*").strip() == ""


def test_create_refuses_existing_name(line, labs_root):
    fleet = new_fleet(line, labs_root)
    first = fleet.create("c2")
    with pytest.raises(LabRefused):
        fleet.create("c2")
    assert first.path.is_dir()


def test_create_partial_failure_leaves_nothing(root, line, labs_root, monkeypatch):
    """A failure in the venv rewrite removes the half-made lab, its marker and its branch."""
    fleet = new_fleet(line, labs_root)

    def boom(*args, **kwargs):
        raise RuntimeError("venv rewrite failed")

    monkeypatch.setattr(fleet, "_rewrite_venv", boom)
    with pytest.raises((RuntimeError, LabError)):
        fleet.create("p1")

    assert not (labs_root / "p1").exists()
    assert not (labs_root / ".creating" / "p1").exists()
    assert git(line, "branch", "--list", "lab/*").strip() == ""
    assert ref_sha(line, "refs/labs/p1") is None

    # With the failure gone, a fresh fleet can create the same name.
    assert new_fleet(line, labs_root).create("p1").branch == "lab/p1"


def test_create_stale_marker_is_cleaned_by_next_create(root, line, labs_root):
    """A crashed create leaves .creating/<name> and a half directory: the next create of that name cleans both."""
    (labs_root / ".creating").mkdir(parents=True)
    (labs_root / ".creating" / "s1").write_text("crashed\n")
    leftover = labs_root / "s1"
    leftover.mkdir()
    (leftover / "junk.txt").write_text("half made\n")

    lab = new_fleet(line, labs_root).create("s1")

    assert lab.path == labs_root / "s1"
    assert not (lab.path / "junk.txt").exists()
    assert not (labs_root / ".creating" / "s1").exists()
    assert lab.branch == "lab/s1"
    assert lab.head()


def test_create_sigterm_cleans_up_and_raises(root, line, labs_root, monkeypatch):
    """SIGTERM during create (in the main thread): create removes the partial lab and raises LabError."""
    fleet = new_fleet(line, labs_root)

    def sigterm_now(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)

    class Unhandled(Exception):
        pass

    def guard(signum, frame):
        # If create installed no handler, this trips the test instead of killing the test run.
        raise Unhandled("create did not install a SIGTERM handler")

    monkeypatch.setattr(fleet, "_rewrite_venv", sigterm_now)
    previous = signal.signal(signal.SIGTERM, guard)
    try:
        with pytest.raises(LabError):
            fleet.create("t1")
    finally:
        signal.signal(signal.SIGTERM, previous)

    assert not (labs_root / "t1").exists()
    assert not (labs_root / ".creating" / "t1").exists()
    assert git(line, "branch", "--list", "lab/*").strip() == ""
    assert ref_sha(line, "refs/labs/t1") is None


# ---------------------------------------------------------------------------
# 7. ADAPTER TESTS (LAST SECTION)
#    Only the two argv and policy checks are written. Fill in the probe-derived details here later.
# ---------------------------------------------------------------------------

def test_codex_argv_confines_workspace_to_its_lab(root, line, labs_root):
    fleet = new_fleet(line, labs_root)
    alpha = fleet.create("alpha")
    bravo = fleet.create("bravo")
    host = CodexHost()

    def argv_for(lab):
        spec = lab.codex_turn_spec("codex", "gpt-x", "high", "do the work")
        assert spec.workspace == str(lab.path)
        assert spec.profile == "workspace-write"
        assert spec.writable_roots == ()
        return host.build_argv(spec, host.fence(spec).flags, ())

    argv_a = argv_for(alpha)
    argv_b = argv_for(bravo)

    assert argv_a[argv_a.index("-C") + 1] == str(alpha.path)
    assert argv_a[argv_a.index("-s") + 1] == "workspace-write"
    assert "--add-dir" not in argv_a
    assert argv_b[argv_b.index("-C") + 1] == str(bravo.path)
    assert argv_a[argv_a.index("-C") + 1] != argv_b[argv_b.index("-C") + 1]


def test_claude_policy_writes_only_under_its_lab(root, line, labs_root):
    fleet = new_fleet(line, labs_root)
    alpha = fleet.create("alpha")
    bravo = fleet.create("bravo")
    state = root / "state"
    spec = alpha.claude_turn_spec("claude", "model-x", "high", "do the work",
                                  state_root=str(state), tools=("Read", "Edit"),
                                  allowed_tools=("Read", "Edit", "Write"))
    assert spec.workspace == str(alpha.path)

    policy = ClaudeHost().make_fence(spec).policy
    write_roots = {root_text.strip('"') for root_text in
                   re.findall(r'\(allow file-write\* \(subpath ([^)]*)\)\)', policy)}

    assert str(alpha.path) in write_roots
    assert write_roots <= {str(alpha.path), str(state)}
    assert str(bravo.path) not in policy
    assert str(line) not in policy
