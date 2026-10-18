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

from astrid.core.pack import source_setup
from astrid.core.pack.source_setup import _tree_digest, active_source_inventory


FIXTURE_DIR = Path(__file__).resolve().parent
PACK_BYTES = FIXTURE_DIR / "immutable_pack"
RECORD_PATH = FIXTURE_DIR / "recorded_source.json"
REPOSITORY = "https://example.invalid/packparity.git"
FIXED_DATE = "2020-01-02T03:04:05+00:00"
PINNED_ASTRID_COMMIT = "f42eaa6db62d989fc869da7219d76493e932869c"
PACK_SUBPATH = "src/herzchen/packs/evidence_resource_pack"
PACK_ROOT_TOKEN = "<PACK_ROOT>"
ORIGINAL_MANIFEST_SHA256 = "ca177262ed1eb1c23f664bd20e970d315151f1aaef7ca9ddd76157147075cb94"
ORIGINAL_TREE_SHA256 = "0aa7039eed5eb5a9806a348bdbd6239286c50e29e0b3f5f7d97a3308ce8a9155"


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _inventory_preimage_for_root(template: str, pack_root: Path) -> str:
    return template.replace(json.dumps(PACK_ROOT_TOKEN), json.dumps(str(pack_root.resolve())))


def _verify_pinned_astrid_source() -> None:
    source_path = Path(source_setup.__file__).resolve()
    repo = subprocess.run(
        ["git", "-C", str(source_path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    pinned_source = subprocess.run(
        ["git", "-C", repo, "show", f"{PINNED_ASTRID_COMMIT}:astrid/core/pack/source_setup.py"],
        capture_output=True, check=True,
    ).stdout
    if source_path.read_bytes() != pinned_source:
        raise RuntimeError("loaded Astrid source_setup.py differs from the pinned implementation")


def _make_checkout(root: Path, temporary_root: Path) -> tuple[Path, Path, str, dict]:
    fixture_root = root
    pack_root = fixture_root / PACK_SUBPATH
    pack_root.parent.mkdir(parents=True)
    shutil.copytree(PACK_BYTES, pack_root)

    # The loader's source path is only a location hint. Keep its bytes out of
    # the managed-source commit and use the real pinned implementation in this process.
    loader_hint = fixture_root / "src/herzchen/packs/authoring.py"
    loader_hint.parent.mkdir(parents=True, exist_ok=True)
    loader_hint.write_text("# loader location hint\n", encoding="utf-8")

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
    subprocess.run(["git", "add", PACK_SUBPATH], cwd=fixture_root, env=env, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Pack Parity Fixture", "-c",
         "user.email=pack-parity@example.invalid", "commit", "-qm", "recorded source fixture"],
        cwd=fixture_root, env=env, check=True,
    )
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
        "pack_subpath": PACK_SUBPATH,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "tree_sha256": _tree_digest(pack_root),
        "source_kind": "managed",
    }
    state_path = temporary_root / f"{root.name}-pack-sources.json"
    state_path.write_text(_canonical_json({
        "version": 1,
        "active": {"evidence": state_record},
        "cached": {},
        "disabled": [],
    }), encoding="utf-8")
    inventory = active_source_inventory(state_path=state_path)
    return fixture_root, pack_root, revision, inventory


def main() -> None:
    _verify_pinned_astrid_source()
    with tempfile.TemporaryDirectory(prefix="astrid-provenance-record-") as temporary:
        temporary_root = Path(temporary)
        checkouts = []
        for index in range(2):
            checkout = temporary_root / f"checkout-{index}"
            checkout.mkdir()
            checkouts.append(_make_checkout(checkout, temporary_root))
        fixture_root, pack_root, revision, first_inventory = checkouts[0]
        _, second_pack_root, second_revision, second_inventory = checkouts[1]

        original = first_inventory.sources[0].to_dict()
        second = second_inventory.sources[0].to_dict()
        if revision != second_revision:
            raise RuntimeError("identical fixture bytes did not produce identical pack-only revisions")
        for field in ("pack_id", "repository", "revision", "pack_subpath", "manifest_sha256", "tree_sha256", "source_kind"):
            if original[field] != second[field]:
                raise RuntimeError(f"pinned Astrid source parity differs between roots for {field}")
        if original["manifest_sha256"] != ORIGINAL_MANIFEST_SHA256:
            raise RuntimeError("immutable fixture manifest digest changed")
        if original["tree_sha256"] != ORIGINAL_TREE_SHA256:
            raise RuntimeError("immutable fixture tree digest changed")

        template_record = dict(original)
        template_record["pack_root"] = PACK_ROOT_TOKEN
        preimage_template = _canonical_json([template_record])
        for pack_root, inventory in ((pack_root, first_inventory), (second_pack_root, second_inventory)):
            preimage = _inventory_preimage_for_root(preimage_template, pack_root)
            independently_hashed = hashlib.sha256(preimage.encode("utf-8")).hexdigest()
            if independently_hashed != inventory.identity:
                raise RuntimeError("canonical inventory preimage does not match pinned Astrid identity")

        recorded_source = dict(original)
        recorded_source["pack_root"] = PACK_SUBPATH
        RECORD_PATH.write_text(json.dumps({
            "recorded_by": "astrid.core.pack.source_setup.active_source_inventory",
            "astrid_commit": PINNED_ASTRID_COMMIT,
            "source": recorded_source,
            "manifest_path": (Path(PACK_SUBPATH) / "pack.yaml").as_posix(),
            "source_inventory_preimage_template": preimage_template,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
