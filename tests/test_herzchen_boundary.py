"""Herzchen imports nothing from Otto (D14: the fleet and the model import down only)."""

import ast
import os
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
