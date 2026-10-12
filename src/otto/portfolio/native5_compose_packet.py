"""Bounded, sealed Native5 startup-packet bridge for the shared compose candidate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

PACKET_RELATIVE = Path("evidence/native-five-current-setup-result.json")
SEAL_RELATIVE = Path("evidence/native-five-current-setup-result.seal.json")
MAX_PACKET_BYTES = 512 * 1024


def _read_regular(path: Path, *, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PermissionError("Native5 startup packet and seal must be regular owner files")
    if path.stat().st_size > maximum:
        raise PermissionError("Native5 startup packet exceeds the finite read bound")
    raw = path.read_bytes()
    if len(raw) != path.stat().st_size or len(raw) > maximum:
        raise PermissionError("Native5 startup packet changed while being read")
    return raw


def write_packet_seal(controller: str | Path, packet_path: str | Path, result: Mapping[str, Any],
                      packet_sha256: str, *, write_json: Any) -> Path:
    """Write the fixed startup seal after the exact setup result is atomically saved."""
    root = Path(controller).resolve()
    packet = Path(packet_path).resolve()
    expected = (root / PACKET_RELATIVE).resolve()
    if packet != expected:
        raise PermissionError("only the fixed Native5 startup-result path can be sealed")
    state_map = result.get("native_five_state_map")
    if (not isinstance(state_map, Mapping)
            or result.get("manager_starts") != 0
            or result.get("provider_called") is not False
            or result.get("dispatch") is not False
            or result.get("activation") is not False):
        raise PermissionError("only provider-free, unstarted Native5 setup output can be sealed")
    seal = {"schema": "otto.native-five-closed-setup-seal.v1",
        "packet_sha256": packet_sha256, "source_commit": state_map.get("source_commit"),
        "root_assignment_ref": state_map.get("root_assignment_ref"),
        "root_generation": state_map.get("root_generation"),
        "project_ids": state_map.get("project_ids"), "sealed_by_uid": os.getuid(),
        "provider_called": False, "manager_starts": 0, "dispatch": False, "activation": False}
    if (not isinstance(packet_sha256, str) or len(packet_sha256) != 64
            or any(char not in "0123456789abcdef" for char in packet_sha256)):
        raise PermissionError("Native5 setup packet digest is malformed")
    seal_path = root / SEAL_RELATIVE
    write_json(seal_path, seal)
    return seal_path


def load_packet(controller: str | Path, *, manifest: Mapping[str, Any],
                main_state: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read and bind the one fixed, sealed setup packet; absent means no Native5."""
    from otto.portfolio.native5_shared_compose import FIVE_IDS

    root = Path(controller).resolve()
    path = root / PACKET_RELATIVE
    seal_path = root / SEAL_RELATIVE
    if not path.exists() and not seal_path.exists():
        return None
    packet_bytes = _read_regular(path, maximum=MAX_PACKET_BYTES)
    seal_bytes = _read_regular(seal_path, maximum=4096)
    try:
        result = json.loads(packet_bytes)
        seal = json.loads(seal_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermissionError("Native5 packet or seal is not bounded JSON") from exc
    state_map = result.get("native_five_state_map") if isinstance(result, dict) else None
    actual_sha = hashlib.sha256(packet_bytes).hexdigest()
    source_commit = manifest.get("source_commit")
    expected_root = main_state.get("orchestrator_assignment_ref")
    packet_root = state_map.get("root_assignment_ref") if isinstance(state_map, dict) else None
    def identity(ref: Any) -> tuple[Any, Any, Any] | None:
        if not isinstance(ref, Mapping):
            return None
        return (ref.get("authority"), ref.get("kind"), ref.get("id"))
    expected_generation = main_state.get("root_help_binding", {}).get("generation")
    project_ids = state_map.get("project_ids") if isinstance(state_map, dict) else None
    expected_project_ids = sorted(set(FIVE_IDS) | {
        row.get("project_ref", {}).get("id")
        for row in state_map.get("refreshed_existing_root_views", {}).values()
    }) if isinstance(state_map, dict) and isinstance(state_map.get("refreshed_existing_root_views"), Mapping) else []
    if (not isinstance(result, dict) or result.get("schema") != "otto.expanded-five-closed-setup-result.v1"
            or not isinstance(state_map, dict)
            or seal.get("schema") != "otto.native-five-closed-setup-seal.v1"
            or seal.get("packet_sha256") != actual_sha
            or seal.get("source_commit") != source_commit
            or state_map.get("source_commit") != source_commit
            # The setup packet is made after root synchronization, while the
            # four installed canonical-state files may still carry the prior
            # root revision. Bind identity/generation here; the owner-backed
            # merge performs the exact full-revision check before composition.
            or identity(packet_root) is None or identity(packet_root) != identity(expected_root)
            or state_map.get("root_generation") != expected_generation
            or seal.get("root_assignment_ref") != packet_root
            or seal.get("root_generation") != expected_generation
            or set(state_map.get("prepared_native_five_packets", {})) != set(FIVE_IDS)
            or not isinstance(project_ids, list) or project_ids != expected_project_ids
            or len(project_ids) != 9
            or result.get("manager_starts") != 0 or result.get("provider_called") is not False
            or result.get("dispatch") is not False or result.get("activation") is not False
            or result.get("manager_occurrences_prepared") is not True
            or seal.get("provider_called") is not False or seal.get("manager_starts") != 0
            or seal.get("dispatch") is not False or seal.get("activation") is not False
            or seal.get("sealed_by_uid") != os.getuid()
            or seal.get("project_ids") != project_ids):
        raise PermissionError("Native5 setup packet is stale, foreign, changed, or not a prepared-only result")
    states_by_project = state_map.get("states_by_project")
    controllers_by_project = state_map.get("controllers_by_project")
    if (not isinstance(states_by_project, dict) or not isinstance(controllers_by_project, dict)
            or not set(FIVE_IDS).issubset(states_by_project)
            or not set(FIVE_IDS).issubset(controllers_by_project)):
        raise PermissionError("Native5 packet lacks exact prepared state and controller projections")
    for ident in FIVE_IDS:
        state = states_by_project[ident]
        controller = controllers_by_project[ident]
        if (state.get("project_ref", {}).get("id") != ident
                or state.get("runtime_controller") != controller
                or state.get("source_path") != state.get("workspace")
                or not isinstance(controller, str) or not Path(controller).is_absolute()
                or not isinstance(state.get("workspace"), str)
                or not Path(state["workspace"]).is_absolute()):
            raise PermissionError("Native5 state/controller/workspace packet binding differs")
        workspace, controller_path = Path(state["workspace"]).resolve(), Path(controller).resolve()
        if (controller_path == workspace or workspace in controller_path.parents
                or controller_path in workspace.parents):
            raise PermissionError("owner controller path overlaps the native writable workspace")
    return {"result": result, "state_map": state_map, "packet_path": str(path),
        "packet_sha256": actual_sha, "seal_path": str(seal_path), "sealed": True,
        "provider_called": False, "manager_starts": 0, "dispatch": False, "activation": False}

