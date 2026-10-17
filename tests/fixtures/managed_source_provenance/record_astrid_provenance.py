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


FIXTURE_ROOT = Path(__file__).resolve().parent / "checkout"
PACK_ROOT = FIXTURE_ROOT / "src/herzchen/packs/evidence_resource_pack"
AUTHORING_PATH = FIXTURE_ROOT / "src/herzchen/packs/authoring.py"
RECORD_PATH = Path(__file__).resolve().parent / "recorded_source.json"
REPOSITORY = "https://example.invalid/packparity.git"
FIXED_DATE = "2020-01-02T03:04:05+00:00"


def main() -> None:
    git_dir = FIXTURE_ROOT / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve().parents[3] / "src/herzchen/packs/authoring.py", AUTHORING_PATH)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Pack Parity Fixture",
        "GIT_AUTHOR_EMAIL": "pack-parity@example.invalid",
        "GIT_AUTHOR_DATE": FIXED_DATE,
        "GIT_COMMITTER_NAME": "Pack Parity Fixture",
        "GIT_COMMITTER_EMAIL": "pack-parity@example.invalid",
        "GIT_COMMITTER_DATE": FIXED_DATE,
    }
    try:
        subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=FIXTURE_ROOT, env=env, check=True)
        subprocess.run(["git", "add", "src/herzchen/packs/authoring.py",
                        "src/herzchen/packs/evidence_resource_pack"], cwd=FIXTURE_ROOT, env=env, check=True)
        subprocess.run(["git", "-c", "user.name=Pack Parity Fixture", "-c",
                        "user.email=pack-parity@example.invalid", "commit", "-qm", "recorded source fixture"],
                       cwd=FIXTURE_ROOT, env=env, check=True)
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=FIXTURE_ROOT, env=env,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        manifest_path = PACK_ROOT / "pack.yaml"
        state_record = {
            "pack_id": "evidence",
            "pack_root": str(PACK_ROOT.resolve()),
            "repository": REPOSITORY,
            "revision": revision,
            "pack_subpath": PACK_ROOT.relative_to(FIXTURE_ROOT).as_posix(),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "tree_sha256": _tree_digest(PACK_ROOT),
            "source_kind": "managed",
        }
        with tempfile.TemporaryDirectory(prefix="astrid-provenance-record-") as temporary:
            state_path = Path(temporary) / "pack-sources.json"
            state_path.write_text(json.dumps({
                "version": 1,
                "active": {"evidence": state_record},
                "cached": {},
                "disabled": [],
            }), encoding="utf-8")
            inventory = active_source_inventory(state_path=state_path)
        source = next(item for item in inventory.sources if item.pack_id == "evidence")
        recorded_source = source.to_dict()
        recorded_source["pack_root"] = Path(recorded_source["pack_root"]).relative_to(FIXTURE_ROOT).as_posix()
        RECORD_PATH.write_text(json.dumps({
            "recorded_by": "astrid.core.pack.source_setup.active_source_inventory",
            "astrid_commit": "f42eaa6d",
            "fixture_root": ".",
            "source": recorded_source,
            "manifest_path": (Path(recorded_source["pack_root"]) / "pack.yaml").as_posix(),
            "source_inventory_identity": inventory.identity,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(git_dir, ignore_errors=True)
        AUTHORING_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
