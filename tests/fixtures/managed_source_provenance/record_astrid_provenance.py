"""Record the fixture with Astrid's pinned managed-source loader.

Run with the Astrid checkout on PYTHONPATH:
    PYTHONPATH=/path/to/Astrid python3 tests/fixtures/managed_source_provenance/record_astrid_provenance.py
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from astrid.core.pack.source_setup import _tree_digest, active_source_inventory


RECORD_PATH = Path(__file__).resolve().parent / "recorded_source.json"
REPOSITORY = "https://example.invalid/packparity.git"
FIXED_DATE = "2020-01-02T03:04:05+00:00"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="astrid-provenance-record-") as temporary:
        temporary_root = Path(temporary)
        fixture_root = temporary_root / "checkout"
        fixture_root.mkdir()
        pack_root = fixture_root / "src/herzchen/packs/evidence_resource_pack"
        pack_root.parent.mkdir(parents=True)
        shutil.copytree(
            Path(__file__).resolve().parents[3] / "src/herzchen/packs/evidence_resource_pack",
            pack_root,
        )
        authoring_path = fixture_root / "src/herzchen/packs/authoring.py"
        authoring_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__).resolve().parents[3] / "src/herzchen/packs/authoring.py", authoring_path)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Pack Parity Fixture",
            "GIT_AUTHOR_EMAIL": "pack-parity@example.invalid",
            "GIT_AUTHOR_DATE": FIXED_DATE,
            "GIT_COMMITTER_NAME": "Pack Parity Fixture",
            "GIT_COMMITTER_EMAIL": "pack-parity@example.invalid",
            "GIT_COMMITTER_DATE": FIXED_DATE,
        }
        subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=fixture_root, env=env, check=True)
        (fixture_root / ".git/info/exclude").write_text(
            "/src/herzchen/packs/authoring.py\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "src/herzchen/packs/evidence_resource_pack"], cwd=fixture_root, env=env, check=True)
        subprocess.run(["git", "-c", "user.name=Pack Parity Fixture", "-c",
                        "user.email=pack-parity@example.invalid", "commit", "-qm", "recorded source fixture"],
                       cwd=fixture_root, env=env, check=True)
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=fixture_root, env=env,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        manifest_path = pack_root / "pack.yaml"
        state_record = {
            "pack_id": "evidence",
            "pack_root": str(pack_root.resolve()),
            "repository": REPOSITORY,
            "revision": revision,
            "pack_subpath": pack_root.relative_to(fixture_root).as_posix(),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "tree_sha256": _tree_digest(pack_root),
            "source_kind": "managed",
        }
        state_path = temporary_root / "pack-sources.json"
        state_path.write_text(json.dumps({
            "version": 1,
            "active": {"evidence": state_record},
            "cached": {},
            "disabled": [],
        }), encoding="utf-8")
        inventory = active_source_inventory(state_path=state_path)
        source = next(item for item in inventory.sources if item.pack_id == "evidence")
        recorded_source = source.to_dict()
        recorded_source["pack_root"] = pack_root.relative_to(fixture_root).as_posix()
        RECORD_PATH.write_text(json.dumps({
            "recorded_by": "astrid.core.pack.source_setup.active_source_inventory",
            "astrid_commit": "f42eaa6d",
            "source": recorded_source,
            "manifest_path": (Path(recorded_source["pack_root"]) / "pack.yaml").as_posix(),
            "inventory_identity_scope": "rooted; recomputed for each checkout",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
