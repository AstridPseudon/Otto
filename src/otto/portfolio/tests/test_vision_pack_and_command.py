import hashlib
import json
from pathlib import Path

import pytest

from herzchen.content.vision_command import VisionCommandError, VisionCommandSurface
from herzchen.content.vision_pack import VisionResourcePack, load_vision_pack
from herzchen.contracts import ResourceRef
from herzchen.packs.authoring import ManagedPack, ManagedResource, ManagedSourceIdentity
from otto.portfolio import cli


ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = ROOT / "herzchen" / "packs" / "vision_resource_pack"


def managed_vision_pack() -> ManagedPack:
    manifest = PACK_ROOT / "pack.yaml"
    source = ManagedSourceIdentity(
        pack_id="vision",
        source_kind="managed",
        source_revision="a" * 40,
        source_tree_sha256="b" * 64,
        source_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        source_inventory_identity="c" * 64,
        pack_root=str(PACK_ROOT),
        manifest_path=str(manifest),
    )
    resources = []
    manifest_data = json.loads(manifest.read_text())
    for entry in manifest_data["resources"]:
        path = entry["path"]
        resource_ref = ResourceRef("astrid-managed", "managed_pack", "vision", source.source_revision)
        content = (PACK_ROOT / path).read_bytes()
        resources.append(ManagedResource(path, entry["kind"], content, hashlib.sha256(content).hexdigest(), resource_ref))
    return ManagedPack("vision", "1.0.0", source, manifest_data, tuple(resources), (), ())


class FakeAuthoring:
    def create(self, content, *, request_id):
        return {"request_id": request_id, "content": content}


class FakeQueries:
    def read(self, document_ref, *, project_ref=None):
        return {"schema": "vision.read.v1", "ref": document_ref, "project_ref": project_ref}


def test_strict_pack_admission_pins_all_resources_and_rechecks_bytes():
    pack = load_vision_pack(managed_pack=managed_vision_pack())
    assert pack.definition_pin.kind == "vision_schema"
    assert len(pack.resources) == 10
    assert pack.selection()["selection_digest"] == pack.digest
    assert pack.compatibility()["guidance_disablement"]["content_preserved"] is True
    assert pack.disable_guidance()["history_preserved"] is True
    assert json.loads(pack.resource_bytes("presets.json"))["finite"] is True


def test_finite_command_surface_rejects_actor_override_and_exposes_exact_pins():
    pack = VisionResourcePack.from_managed_pack(managed_vision_pack())
    surface = VisionCommandSurface(authoring=FakeAuthoring(), queries=FakeQueries(), pack=pack)
    help_result = surface.dispatch({"command": "vision", "operation": "help", "arguments": {}})
    assert help_result["operations"][-1] == "snapshot"
    assert help_result["resource_selection"]["definition_pin"]["digest"] == pack.definition_pin.digest
    with pytest.raises(VisionCommandError, match="actor override"):
        surface.dispatch({"command": "vision", "operation": "help", "actor": "spoof", "arguments": {}})
    with pytest.raises(VisionCommandError, match="request_key"):
        surface.dispatch({"command": "vision", "operation": "create", "arguments": {"content": {}}})


def test_main_cli_routes_only_through_injected_surface(capsys):
    class Surface:
        def dispatch(self, request):
            assert request["command"] == "vision"
            return {"schema": "vision.help.v1", "status": "ok", "provider_called": False}

    code = cli.main(
        ["vision", "--request-json", json.dumps({"command": "vision", "operation": "help", "arguments": {}})],
        vision_operations=Surface(),
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "vision.help.v1"
