"""Read-only parser for a Megado file-mode run bundle.

A bundle is a run directory holding northstar.md, agent_goal.md, plan.md,
tasklist.md, status.md and exactly one of run.json / run.yaml (JSON content).
The WHOLE directory is the project's record: every other regular UTF-8 text
file, top level or nested (briefs/M1.md, reviews/astra-high-timing.md,
archive/...), becomes one project document at its "/"-separated relative
path. Dotfiles are skipped; symlinks, binary files and nesting deeper than
MAX_DEPTH are refused rather than silently left out. Nothing here writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

REQUIRED_FILES = ("northstar.md", "agent_goal.md", "plan.md", "tasklist.md", "status.md")
RUN_FILES = ("run.json", "run.yaml")
MAX_DEPTH = 4  # e.g. reviews/round-2/astra/x.md
EMPTY_DEPS = {"", "-", "—", "–"}  # "", hyphen, em dash, en dash

_SEP_RE = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_PAREN_RE = re.compile(r"\([^)]*\)")
_DEP_SPLIT_RE = re.compile(r",|;|\band\b", re.IGNORECASE)
_SLASH_RE = re.compile(r"^([A-Za-z]+-)(\d+)/(\d+)$")
_SENTENCE_END_RE = re.compile(r"\.(?=\s|$)")


class BundleError(ValueError):
    """Raised when a run bundle or its tasklist is malformed."""


def _bundle_names(root: Path, prefix: str = "", depth: int = 0) -> list:
    """Every regular file (no dotfiles), nested up to MAX_DEPTH; symlinks refused."""
    names = []
    with os.scandir(root) as it:
        entries = sorted(it, key=lambda e: e.name)
    for entry in entries:
        name = entry.name
        if name.startswith("."):
            continue
        mode = os.lstat(entry.path).st_mode
        relative = prefix + name
        if stat.S_ISLNK(mode):
            raise BundleError(f"refusing symlinked bundle entry: {relative}")
        if stat.S_ISDIR(mode):
            if depth >= MAX_DEPTH:
                raise BundleError(f"{relative}/ nests deeper than {MAX_DEPTH} levels; flatten it")
            names.extend(_bundle_names(Path(entry.path), relative + "/", depth + 1))
            continue
        if stat.S_ISREG(mode):
            names.append(relative)
    return names


def read_bundle(path, *, max_files: int | None = None, max_file_bytes: int = 10 << 20) -> dict:
    """Return {"root", "files", "raw_sha256", "run", "run_file", "tasks", "phases"}.

    Reads regular *.md files (top level and nested, e.g. briefs/M1.md) plus
    run.json / run.yaml. Symlinks are rejected. raw_sha256 is the sha256 of
    the exact bytes on disk. Keys are "/"-separated relative paths.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        raise BundleError(f"not a directory: {root}")

    names = _bundle_names(root)

    present = set(names)
    missing = [n for n in REQUIRED_FILES if n not in present]
    if missing:
        raise BundleError(f"bundle {root} is missing required file(s): {', '.join(missing)}")
    run_names = [n for n in RUN_FILES if n in present]
    if not run_names:
        raise BundleError(f"bundle {root} has no run file (need exactly one of run.json or run.yaml)")
    if len(run_names) > 1:
        raise BundleError(f"bundle {root} has both run.json and run.yaml; keep exactly one")
    run_file = run_names[0]

    if max_files is not None and len(names) > max_files:
        raise BundleError(f"bundle has {len(names)} files, more than max_files={max_files}")

    files: dict = {}
    raw_sha256: dict = {}
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    for name in names:
        fp = root.joinpath(*name.split("/"))
        st = os.lstat(fp)
        if stat.S_ISLNK(st.st_mode):
            raise BundleError(f"refusing symlinked bundle file: {name}")
        if st.st_size > max_file_bytes:
            raise BundleError(f"{name} is {st.st_size} bytes, more than max_file_bytes={max_file_bytes}")
        fd = os.open(fp, os.O_RDONLY | nofollow)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(max_file_bytes + 1)
        if len(data) > max_file_bytes:
            raise BundleError(f"{name} grew past max_file_bytes={max_file_bytes} while reading")
        raw_sha256[name] = hashlib.sha256(data).hexdigest()
        try:
            files[name] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BundleError(f"{name} is not valid UTF-8: {exc}") from None

    return {"root": str(root), **parse_files(files, raw_sha256=raw_sha256)}


def parse_files(files: dict, *, raw_sha256: dict = None) -> dict:
    """Parse an in-memory bundle (for example Otto's stored copies of a run's files).

    Used at activation, when Otto is the authority and the plan is read from
    its own documents rather than from the run directory.
    """
    missing = [n for n in REQUIRED_FILES if n not in files]
    if missing:
        raise BundleError("bundle is missing required file(s): " + ", ".join(missing))
    run_names = [n for n in RUN_FILES if n in files]
    if len(run_names) != 1:
        raise BundleError("bundle needs exactly one of run.json or run.yaml")
    run_file = run_names[0]
    if raw_sha256 is None:
        raw_sha256 = {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in files.items()}
    try:
        run = json.loads(files[run_file])
    except ValueError as exc:
        raise BundleError(f"{run_file} must contain JSON (despite the extension): {exc}") from None
    if not isinstance(run, dict):
        raise BundleError(f"{run_file} must contain a JSON object")
    if "otto_generated_view" in run:
        raise BundleError("generated run view is a read-only projection, not a source bundle")

    headings, tables = _scan_tables(files["tasklist.md"])
    tasks = _build_tasks(tables)
    phases = _group_phases(headings, tasks)

    return {
        "files": dict(files),
        "raw_sha256": dict(raw_sha256),
        "run": run,
        "run_file": run_file,
        "tasks": tasks,
        "phases": phases,
    }


def parse_tasklist(markdown: str) -> list[dict]:
    """Parse every markdown table that has an ``id`` column into task dicts.

    Tables are taken from wherever they sit; the ``phase`` of a task is the text
    of the most recent ``## `` heading above its table.
    """
    _headings, tables = _scan_tables(markdown)
    return _build_tasks(tables)


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT_RE.split(s)]


def _scan_tables(markdown: str):
    """Return (ordered phase headings, [(phase, rows)]) for tables with an id column."""
    headings: list = []
    tables: list = []
    phase = None
    lines = markdown.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if line.startswith("## "):
            phase = line[3:].strip()
            headings.append(phase)
            i += 1
            continue
        if not line.startswith("|"):
            i += 1
            continue
        block = []
        while i < n and lines[i].strip().startswith("|"):
            block.append((i + 1, lines[i].strip()))
            i += 1
        header = [c.lower().strip("* ") for c in _split_row(block[0][1])]
        if "id" not in header or "outcome" not in header:
            continue  # not a task table (e.g. a dispatch log keyed by id without outcomes)
        if len(block) < 2 or not _SEP_RE.match(block[1][1]):
            raise BundleError(
                f"tasklist.md line {block[0][0]}: table with an 'id' column has no |---| separator row"
            )
        rows = []
        for lineno, text in block[2:]:
            cells = _split_row(text)
            if len(cells) != len(header):
                raise BundleError(
                    f"tasklist.md line {lineno}: {len(cells)} cells, header has {len(header)}"
                )
            rows.append((lineno, dict(zip(header, cells))))
        tables.append((phase, rows))
    return headings, tables


def _clean_id(cell: str) -> str:
    return re.sub(r"^\*\*|\*\*$", "", cell.strip()).strip()


def _build_tasks(tables) -> list[dict]:
    # Pass 1: collect every row and every id (deps may point forward).
    rows = []
    first_line: dict = {}
    for phase, trows in tables:
        for lineno, cells in trows:
            tid = _clean_id(cells.get("id", ""))
            if not tid:
                continue
            if tid in first_line:
                raise BundleError(
                    f"tasklist.md line {lineno}: duplicate task id {tid!r} "
                    f"(first defined at line {first_line[tid]})"
                )
            first_line[tid] = lineno
            rows.append((phase, cells))
    known = set(first_line)
    # Pass 2: build task dicts.
    return [_make_task(phase, cells, known) for phase, cells in rows]


def _make_task(phase, cells: dict, known: set) -> dict:
    cells = dict(cells)
    for alias, canonical in (("acceptance evidence", "proof"),
                             ("deps (accepted milestones)", "deps"), ("executor", "who")):
        if alias in cells and canonical not in cells:
            cells[canonical] = cells[alias]
    tid = _clean_id(cells.get("id", ""))
    deps_text = cells["deps"].strip() if "deps" in cells else None
    route_text = cells["route"].strip() if "route" in cells else None
    return {
        "id": tid,
        "phase": phase,
        "outcome": cells.get("outcome", "").strip(),
        "title": _title(cells.get("outcome", "")),
        "deps": _parse_deps(deps_text, known),
        "deps_text": deps_text,
        "route": _route(route_text),
        "route_text": route_text,
        "repo": cells["repo"].strip() if "repo" in cells else None,
        "branch": cells["branch"].strip() if "branch" in cells else None,
        "proof": cells["proof"].strip() if "proof" in cells else None,
        "who": cells["who"].strip() if "who" in cells else None,
        "columns": {k: v.strip() for k, v in cells.items()},
    }


def _title(outcome: str) -> str:
    text = outcome.replace("**", "").replace("*", "").replace("`", "")
    cut = len(text)
    idx = text.find(": ")
    if idx >= 0:
        cut = min(cut, idx)
    m = _SENTENCE_END_RE.search(text)
    if m:
        cut = min(cut, m.start())
    return text[:cut][:120].strip()


def _parse_deps(text, known: set) -> list:
    """Return the task ids in ``text`` that exactly match a defined id.

    Parenthetical notes are dropped and the rest is split on commas, semicolons
    and the word "and". ``PT-1/2`` expands to PT-1 and PT-2. Ranges such as
    ``K1–K3`` and free-text tokens are not expanded; they stay only in deps_text.
    """
    if text is None or text in EMPTY_DEPS:
        return []
    out: list = []
    for raw in _DEP_SPLIT_RE.split(_PAREN_RE.sub(" ", text)):
        token = raw.strip().strip("*`").strip()
        if token in known:
            candidates = [token]
        else:
            m = _SLASH_RE.match(token)
            candidates = [m.group(1) + m.group(2), m.group(1) + m.group(3)] if m else []
        for cand in candidates:
            if cand in known and cand not in out:
                out.append(cand)
    return out


def _route(route_text):
    if route_text is None:
        return None
    low = route_text.replace("*", "").lower()
    if "xhard" in low:
        return "xhard"
    if "normal" in low:
        return "normal"
    return None


def _group_phases(headings: list, tasks: list) -> list:
    order: list = []
    if any(t["phase"] is None for t in tasks):
        order.append(None)
    for h in headings:
        if h not in order:
            order.append(h)
    return [
        {"heading": h, "task_ids": [t["id"] for t in tasks if t["phase"] == h]}
        for h in order
    ]
