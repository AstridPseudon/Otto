"""Locate and read a run's single model/stage/budget declaration.

The file is JSON. New runs name it ``run.json``; runs created from the older
template keep ``run.yaml`` (JSON content, which is also valid YAML 1.2) and
are read unchanged. Two declarations in one run are refused rather than
guessed between.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAMES = ("run.json", "run.yaml")


def run_config_path(run_path: str | Path) -> Path:
    root = Path(run_path)
    present = [root / name for name in NAMES if (root / name).is_file()]
    if len(present) > 1:
        raise ValueError("run declares both run.json and run.yaml; keep exactly one")
    # Absent: report the legacy name so existing error text and links hold.
    return present[0] if present else root / "run.yaml"


def read_run_config(run_path: str | Path) -> Any:
    path = run_config_path(run_path)
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(path.name + " must be JSON: " + str(exc)) from exc
