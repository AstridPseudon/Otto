"""Locate and read a run's single model/stage/budget declaration.

The file is JSON. New runs name it ``run.json``; runs created from the older
template keep ``run.yaml`` (JSON content, which is also valid YAML 1.2) and
are read unchanged. Two declarations in one run are refused rather than
guessed between.
"""
from __future__ import annotations

import json
import copy
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


def resolved_run_config(run_path: str | Path) -> Any:
    """Fill unbound template slots from the selected, pinned profile pack.

    Existing complete run declarations are returned as written. A partial
    declaration keeps each explicit project role binding authoritative.
    """
    run = read_run_config(run_path)
    from otto.agents.host_profiles import SLOTS, profile
    roles = run.get("roles") or {}
    if not isinstance(roles, dict):
        raise ValueError("run roles must be a mapping")
    if set(SLOTS).issubset(roles):
        return run
    name = run.get("model_profile")
    if not isinstance(name, str) or not name:
        raise ValueError("run with unbound roles must select a model profile")
    selected = profile(name)
    declared_pin = run.get("profile_pack")
    if declared_pin is not None and declared_pin != selected["pin"]:
        raise ValueError("run profile pack pin is stale or inconsistent")
    resolved = copy.deepcopy(selected["roles"])
    for slot, binding in roles.items():
        if slot not in resolved or not isinstance(binding, dict):
            raise ValueError("run has an invalid responsibility slot binding")
        resolved[slot].update(binding)
    return {**run, "roles": resolved, "profile_pack": copy.deepcopy(selected["pin"])}
