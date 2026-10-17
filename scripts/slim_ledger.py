"""Generate the reproducible SLIM module, entrypoint, and surface ledger."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "src/otto/portfolio"
CONTROLLER = ROOT / "install/controller"
BASELINE_LINES = 47_920
BASELINE_MODULES = 99
BASELINE_REVISION = "163925e"
DELETION_TARGET = 11_980


def _python_files(path: Path, *, top_level: bool = True) -> list[Path]:
    files = sorted(path.glob("*.py") if top_level else path.rglob("*.py"))
    return [p for p in files if p.is_file()]


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def current_portfolio_totals() -> tuple[int, int]:
    """Return the current checkout's top-level portfolio line and file counts."""
    files = _python_files(PORTFOLIO)
    return sum(_lines(path) for path in files), len(files)


def _reference_index(files: list[Path], module_names: list[str]) -> dict[str, tuple[list[str], list[str]]]:
    """Index AST imports and conservative literal/module-qualified references."""
    imports = {name: set() for name in module_names}
    dynamic = {name: set() for name in module_names}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                    for target in module_names:
                        if any(name == target or name.startswith(target + ".") for name in imported_names):
                            imports[target].add(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        importer_parts = path.relative_to(ROOT).with_suffix("").parts
                        if importer_parts and importer_parts[0] == "src":
                            importer_parts = importer_parts[1:]
                        importer_parts = importer_parts[:-1]
                        package_parts = importer_parts[: max(0, len(importer_parts) - node.level + 1)]
                        imported_parts = package_parts + tuple((node.module or "").split(".")) if node.module else package_parts
                        imported_module = ".".join(imported_parts)
                        for target in module_names:
                            if imported_module == target or (not node.module and any(".".join(imported_parts + (alias.name,)) == target for alias in node.names)):
                                imports[target].add(f"{rel}:{node.lineno}")
                    else:
                        imported = node.module or ""
                        for target in module_names:
                            if imported == target or imported.startswith(target + "."):
                                imports[target].add(f"{rel}:{node.lineno}")
        # Capture importlib/__import__ string targets, module-qualified attribute
        # use, and commands/configuration that AST imports cannot see.
        for line_no, line in enumerate(text.splitlines(), 1):
            for target in module_names:
                stem = target.rsplit(".", 1)[-1]
                if target in line or f"{stem}.py" in line:
                    dynamic[target].add(f"{rel}:{line_no}")
    return {name: (sorted(imports[name]), sorted(dynamic[name])) for name in module_names}


def _all_source_files() -> list[Path]:
    ignored = {".git", ".worktrees", ".venv", "__pycache__"}
    return [
        p for p in ROOT.rglob("*.py")
        if not any(part in ignored for part in p.relative_to(ROOT).parts)
        and p.relative_to(ROOT).as_posix() not in {"scripts/slim_ledger.py", "tests/test_slim_ledger.py"}
    ]


def _parser_verbs() -> list[str]:
    tree = ast.parse((PORTFOLIO / "cli.py").read_text(encoding="utf-8"))
    build_parser = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build_parser")
    verbs = []
    for node in ast.walk(build_parser):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_parser" and isinstance(node.func.value, ast.Name) and node.func.value.id == "sub" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            verbs.append(node.args[0].value)
    return sorted(set(verbs))


def _brief_rows() -> list[tuple[str, int, int]]:
    paths = [ROOT / ".project/manager-brief.md"] + sorted((PORTFOLIO / "skills").rglob("*.md"))
    rows = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # Deterministic lexical token estimate (whitespace-delimited words and
        # punctuation); it is explicitly an estimate, not a model tokenizer.
        tokens = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
        rows.append((path.relative_to(ROOT).as_posix(), len(text.split()), len(tokens)))
    return rows


def generate() -> str:
    portfolio = _python_files(PORTFOLIO)
    controller = _python_files(CONTROLLER)
    all_files = _all_source_files()
    tests = [p for p in all_files if "/tests/" in p.as_posix() or p.name.startswith("test_")]
    production = [p for p in all_files if p not in tests]
    module_names = ["otto.portfolio." + p.stem for p in portfolio] + ["install.controller." + p.stem for p in controller]
    prod_index = _reference_index(production, module_names)
    test_index = _reference_index(tests, module_names)
    rows = []
    for path in portfolio + controller:
        module = ("otto.portfolio." + path.stem) if path.parent == PORTFOLIO else ("install.controller." + path.stem)
        prod_imports, prod_dynamic = prod_index[module]
        test_imports, test_dynamic = test_index[module]
        rows.append((path.relative_to(ROOT).as_posix(), _lines(path), prod_imports, test_imports, prod_dynamic, test_dynamic))

    current_lines, current_modules = current_portfolio_totals()
    controller_total = sum(row[1] for row in rows if row[0].startswith("install/controller/"))
    row_index = {Path(row[0]).name: row for row in rows if row[0].startswith("src/otto/portfolio/")}
    out = [
        "# SLIM module and entrypoint ledger",
        "",
        "Generated by `python scripts/slim_ledger.py`; regenerate after each merged task.",
        "",
        f"- Immutable baseline at `{BASELINE_REVISION}`: **{BASELINE_LINES:,} lines** across **{BASELINE_MODULES} top-level modules** in `src/otto/portfolio`.",
        f"- Current checkout top-level portfolio: **{current_lines:,} lines** across **{current_modules} modules**; line delta from baseline: **{BASELINE_LINES - current_lines:+,}** (baseline minus current).",
        f"- Controller Python: **{controller_total:,} lines** across **{len(controller)} files**. `install/build_manifest.py` is a separate packaging entrypoint (96 lines).",
        f"- Net deletion threshold: **{DELETION_TARGET:,} lines** (25% of baseline). Candidate gross sizes do not count as achieved deletion.",
        "- Importer columns separate production and tests. AST import sites include line numbers; literal module-name/source-filename mentions are listed separately as dynamic-reference leads (some may be documentation). No hit means no statically found site, not proof against runtime-generated names.",
        "- Brief tokens use a reproducible lexical estimate (word/punctuation pieces), not a model tokenizer.",
        "",
        "## Exposed `otto` verbs",
        "",
        "`pyproject.toml` declares `otto = otto.portfolio.cli:client_main`. Direct root commands from `build_parser()` in `cli.py`: " + ", ".join(f"`{v}`" for v in _parser_verbs()) + ". Nested parser actions are represented in their defining source but are not duplicated here.",
        "",
        "## Module inventory",
        "",
        "| file | lines | production importers | test importers | dynamic production refs | dynamic test refs |",
        "|---|---:|---|---|---|---|",
    ]
    for file, lines, prod, test, pdyn, tdyn in rows:
        fmt = lambda refs: ", ".join(f"`{r}`" for r in refs) or "—"
        out.append(f"| `{file}` | {lines} | {fmt(prod)} | {fmt(test)} | {fmt(pdyn)} | {fmt(tdyn)} |")
    out += ["", "## Manager and worker tools, refusals, and brief sizes", ""]
    out += ["- Manager/worker command entrypoints: `otto` parser verbs above; `manager_ctl.py` commands are listed below as literal subparser names."]
    manager_commands = sorted(set(re.findall(r"add_parser\(\s*['\"]([^'\"]+)", (ROOT / "manager_ctl.py").read_text(encoding="utf-8"))))
    out.append("- `manager_ctl.py`: " + ", ".join(f"`{v}`" for v in manager_commands) + ".")
    refusals = []
    refusal_codes: set[str] = set()
    for path in _python_files(PORTFOLIO):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if '"next_action"' in line or "'next_action'" in line:
                refusals.append(f"`{path.relative_to(ROOT).as_posix()}:{lineno}`")
            refusal_codes.update(re.findall(r"['\"]code['\"]\s*:\s*['\"]([a-z][a-z0-9_]+)['\"]", line))
    refusal_files = sorted({ref.split(":", 1)[0] for ref in refusals})
    out.append(f"- `next_action` refusal/recovery sites: **{len(refusals)}** across **{len(refusal_files)} modules**; locations are searchable in source and each module is listed in the inventory.")
    out.append(f"- Structured refusal/error codes: **{len(refusal_codes)} distinct literal codes**; see the source locations in the module inventory and `error` response branches.")
    out.append("- Role tool and guidance surfaces: `src/otto/portfolio/skills/references/manager.md`, `worker.md`, `orchestrator.md`, and `observability.md`; count their documented tools alongside the CLI verbs above before any UX deletion.")
    out += ["", "| brief/document | words | lexical token estimate |", "|---|---:|---:|"]
    for file, words, tokens in _brief_rows():
        out.append(f"| `{file}` | {words} | {tokens} |")
    out += ["", "## SL9 measured deletion candidates", "", "Candidates below avoid files already owned by PROGRAM DELETE and are not counted as savings until behavior, importers, dynamic refs, and CLI routes are retired and the diff is measured.", ""]
    candidates = [
        ("orchestrator_placement.py", "package export and runtime/command references must be checked before retirement"),
        ("manager_journey_command.py", "assess adapter overlap with the retained manager service before removal"),
        ("manager_journey_service.py", "core manager route; remove only proven duplicate methods with parity checks"),
        ("retention_owner_read.py", "compare with retained projections before consolidation"),
        ("document_navigation.py", "owner backed editor behavior and custody must remain covered"),
        ("document_editor_host.py", "owner backed editor behavior and custody must remain covered"),
        ("manager_inventory.py", "inventory projection overlap candidate"),
    ]
    out += ["| candidate | current lines | production import sites / files | test import sites / files | rationale |", "|---|---:|---:|---:|---|"]
    for filename, rationale in candidates:
        row = row_index.get(filename)
        if row is None:
            continue
        file, lines, prod, test, pdyn, tdyn = row
        prod_files = len({ref.rsplit(":", 1)[0] for ref in prod})
        test_files = len({ref.rsplit(":", 1)[0] for ref in test})
        out.append(f"| `{file}` | {lines} | {len(prod)} / {prod_files} | {len(test)} / {test_files} | {rationale} |")
    out += ["", "The candidate gross total is not a deletion estimate: some candidates are already covered by SL1/3/4/5, and shared code must be retained. SL9 must remove overlap before adding candidates and measure net lines from `163925e`.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    print(generate(), end="")
