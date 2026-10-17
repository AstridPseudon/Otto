"""Herzchen imports nothing from Otto (D14: the fleet and the model import down only)."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERZCHEN = ROOT / "src" / "herzchen"


def _otto_imports(path: Path) -> list[str]:
    """Every absolute import of ``otto`` in the file, including imports inside functions."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        found.extend(name for name in names if name == "otto" or name.startswith("otto."))
    return found


OTTO_OR_MEGADO = re.compile(r"otto|megado", re.IGNORECASE)
PROVENANCE_BOUNDARY_TOKENS = re.compile(
    r"astrid|Documents/Codex|otto-project-operating-setup-20261005-owner-v1",
    re.IGNORECASE,
)


def _provenance_boundary_offenders(source_root: Path) -> dict[str, list[str]]:
    offenders = {}
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or "tests" in path.parts or path.suffix in {".pyc", ".sqlite"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        matches = sorted(set(match.group(0) for match in PROVENANCE_BOUNDARY_TOKENS.finditer(text)))
        if matches:
            offenders[str(path.relative_to(source_root))] = matches
    return offenders


def _docstring_ids(tree: ast.AST) -> set[int]:
    """ids of the docstring nodes: the leading string expression of a module, class or function body."""

    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _otto_names(path: Path) -> list[tuple[int, str]]:
    """(lineno, text) for every non-docstring string and every identifier that mentions otto or megado."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_ids(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append((node.lineno, node.value))
        elif isinstance(node, ast.Name):
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            found.append((node.lineno, node.attr))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append((node.lineno, node.name))
        elif isinstance(node, ast.arg):
            found.append((node.lineno, node.arg))
        elif isinstance(node, ast.keyword) and node.arg is not None:
            found.append((node.lineno, node.arg))
        elif isinstance(node, ast.alias):
            found.append((node.lineno, node.name))
            if node.asname:
                found.append((node.lineno, node.asname))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
    return [(lineno, text) for lineno, text in found if OTTO_OR_MEGADO.search(text)]


def test_herzchen_imports_no_otto():
    offenders = {}
    for path in sorted(HERZCHEN.rglob("*.py")):
        found = _otto_imports(path)
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert offenders == {}


@pytest.mark.parametrize("module", ["herzchen.domains.work.usage", "herzchen.adapters.host"])
def test_herzchen_import_loads_without_otto(module):
    code = (
        "import importlib, sys\n"
        f"importlib.import_module({module!r})\n"
        "loaded = sorted(m for m in sys.modules if m == 'otto' or m.startswith('otto.'))\n"
        "print(loaded)\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_fleet_carries_no_otto_or_megado_names():
    offenders = {}
    for path in sorted((HERZCHEN / "fleet").rglob("*.py")):
        for lineno, text in _otto_names(path):
            offenders.setdefault(f"{path.relative_to(ROOT)}:{lineno}", []).append(text[:80])
    assert offenders == {}


def test_managed_provenance_source_has_no_upstream_product_or_host_paths(tmp_path):
    assert _provenance_boundary_offenders(HERZCHEN) == {}

    doctored_source = tmp_path / "herzchen"
    doctored_source.mkdir()
    (doctored_source / "doctored.py").write_text(
        "RESOURCE_ROOT = '/workspace/Documents/Codex/source'\n", encoding="utf-8"
    )
    assert _provenance_boundary_offenders(doctored_source) == {
        "doctored.py": ["Documents/Codex"]
    }
