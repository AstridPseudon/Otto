import hashlib
import builtins
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest

from herzchen.content.model import ContentDocument, ContentRevision, revision_identity
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from herzchen.evidence.model import (
    ChangedInputError,
    EvidencePackError,
    PublicationInterrupted,
    load_evidence_pack,
)
from herzchen.packs.authoring import PackAuthoringError, PackProvenanceError, read_managed_pack
from herzchen.kernel import Store
from unittest.mock import patch


def _public_pack_hooks():
    pack_root = Path(__file__).parents[1] / "src" / "herzchen" / "packs" / "evidence_resource_pack"
    resource_kinds = {
        "schemas/evidence.json": "evidence_schema",
        "policies/provenance.json": "evidence_policy",
        "presets/submit.json": "evidence_preset",
        "presets/version.json": "evidence_preset",
        "skill/SKILL.md": "skill",
        "templates/evidence.json": "evidence_template",
    }
    revision = "a" * 40
    manifest_digest = hashlib.sha256((pack_root / "pack.yaml").read_bytes()).hexdigest()
    definition = SimpleNamespace(
        version="1.0.0",
        to_dict=lambda: {"id": "evidence", "version": "1.0.0", "schema_version": 2},
    )
    handles = tuple(
        SimpleNamespace(
            path=path,
            kind=kind,
            resolved=pack_root / path,
            sha256=hashlib.sha256((pack_root / path).read_bytes()).hexdigest(),
        )
        for path, kind in resource_kinds.items()
    )
    discovered = SimpleNamespace(
        id="evidence",
        source_kind="managed",
        source_revision=revision,
        source_tree_sha256="b" * 64,
        source_manifest_sha256=manifest_digest,
        source_inventory_identity="c" * 64,
        pack_dir=pack_root,
        entry=SimpleNamespace(
            manifest=SimpleNamespace(sha256=manifest_digest),
            definition=definition,
            resource_handles=handles,
        ),
    )

    def discover(*, project_root):
        return (discovered,)

    def load(path, *, expected_pack_id=None):
        return SimpleNamespace(id="evidence", schema_version=2)

    return pack_root, discover, load


def _public_managed_pack():
    pack_root, discover, load = _public_pack_hooks()

    return read_managed_pack(
        "evidence",
        project_root=pack_root.parents[3],
        discoverer=discover,
        loader=load,
    )


def _copy_native_pack_tree(destination):
    """Build the source-tree shape used by the native pack discoverer."""
    source_root = Path(__file__).parents[1] / "src" / "herzchen"
    target_root = Path(destination) / "src" / "herzchen"
    (target_root / "packs").mkdir(parents=True)
    import shutil
    shutil.copy2(source_root / "packs" / "authoring.py", target_root / "packs" / "authoring.py")
    shutil.copytree(source_root / "packs" / "evidence_resource_pack",
                    target_root / "packs" / "evidence_resource_pack")
    repo_root = Path(destination)
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "remote", "add", "github", "https://example.invalid/packload.git"],
                   cwd=repo_root, check=True)
    subprocess.run(["git", "add", "src/herzchen/packs"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=PACKLOAD tests", "-c", "user.email=packload@example.invalid",
         "commit", "-qm", "fixture"],
        cwd=repo_root,
        check=True,
    )
    return target_root


def _prepare_recorded_provenance_checkout(fixture_root, *, loader_comment=None):
    """Materialize recorded pack bytes in one disposable, independently rooted checkout."""
    import shutil

    fixture_root = Path(fixture_root)
    pack_relative = Path("src/herzchen/packs/evidence_resource_pack")
    pack_root = fixture_root / pack_relative
    pack_root.parent.mkdir(parents=True)
    shutil.copytree(
        Path(__file__).parent / "fixtures/managed_source_provenance/immutable_pack",
        pack_root,
    )
    loader_path_hint = fixture_root / "src/herzchen/packs/authoring.py"
    loader_path_hint.parent.mkdir(parents=True, exist_ok=True)
    loader_path_hint.write_text("# loader location hint\n", encoding="utf-8")
    if loader_comment is not None:
        with loader_path_hint.open("a", encoding="utf-8") as stream:
            stream.write(f"# {loader_comment}\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Pack Parity Fixture",
        "GIT_AUTHOR_EMAIL": "pack-parity@example.invalid",
        "GIT_AUTHOR_DATE": "2020-01-02T03:04:05+00:00",
        "GIT_COMMITTER_NAME": "Pack Parity Fixture",
        "GIT_COMMITTER_EMAIL": "pack-parity@example.invalid",
        "GIT_COMMITTER_DATE": "2020-01-02T03:04:05+00:00",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=fixture_root, env=env, check=True)
    exclude = fixture_root / ".git/info/exclude"
    exclude.write_text("/src/herzchen/packs/authoring.py\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/herzchen/packs/evidence_resource_pack"],
        cwd=fixture_root, env=env, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=Pack Parity Fixture", "-c",
         "user.email=pack-parity@example.invalid", "commit", "-qm", "recorded source fixture"],
        cwd=fixture_root, env=env, check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=fixture_root, env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return fixture_root, loader_path_hint, revision


def _copy_installed_runtime_source(controller_root):
    """Build an installed controller tree authenticated by runtime-manifest.json."""
    import shutil

    source_root = Path(__file__).parents[1] / "src" / "herzchen"
    target_root = Path(controller_root) / "runtime-source" / "herzchen"
    packs_root = target_root / "packs"
    packs_root.mkdir(parents=True)
    shutil.copy2(source_root / "packs" / "authoring.py", packs_root / "authoring.py")
    shutil.copytree(source_root / "packs" / "evidence_resource_pack",
                    packs_root / "evidence_resource_pack")
    files = {}
    for path in sorted(packs_root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(target_root.parent).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    (Path(controller_root) / "runtime-manifest.json").write_text(json.dumps({
        "source_commit": "f1cf6354767b4d46ec933725ef5ceafeecd5152c",
        "files": files,
    }), encoding="utf-8")
    return target_root


class EvidenceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = Store.create(root / "owner.sqlite", authority="owner")
        register_evidence(self.store)
        self.actor = AuthenticatedActor("owner", "submitter", "credential")
        self.project = ResourceRef("owner", "work.project", "project")
        self.task = ResourceRef("owner", "work.task", "task")
        self.attempt = ResourceRef("owner", "work.attempt", "attempt")
        self.store.put_identity(self.project, {"record_type": "work.project", "title": "fixture"}, version=0)
        self.store.put_identity(
            self.task,
            {"record_type": "work.task", "project_ref": self.project, "title": "task"},
            version=0,
        )
        self.store.put_identity(
            self.attempt,
            {"record_type": "work.attempt", "project_ref": self.project, "task_ref": self.task},
            version=0,
        )
        pack_root, discover, loader = _public_pack_hooks()
        self.managed_pack = read_managed_pack(
            "evidence", project_root=pack_root.parents[3], discoverer=discover, loader=loader
        )
        self.pack = load_evidence_pack(
            project_root=pack_root.parents[3], discoverer=discover, loader=loader
        )
        self.handler = EvidenceCommandHandler(
            self.store,
            root / "managed",
            pack=self.pack,
            adopted_pins=[item.to_dict() for item in self.pack.resources],
        )

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def _submit(self, source, key, **kwargs):
        return self.handler.submit(
            source,
            actor=self.actor,
            logical_request_key=key,
            project_ref=self.project,
            task_ref=self.task,
            attempt_ref=self.attempt,
            original_creator="creator",
            **kwargs,
        )

    def test_otto_source_state_path_matches_explicit_and_default_astrid_locations(self):
        from otto.hostctl.owner import _managed_source_state_path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configured = root / "configured" / "pack-sources.json"
            state_home = root / "xdg-state"
            with patch.dict(os.environ, {
                "ASTRID_SOURCE_STATE": str(configured),
                "XDG_STATE_HOME": str(state_home),
            }):
                self.assertEqual(_managed_source_state_path(), configured.resolve())
            with patch.dict(os.environ, {
                "ASTRID_SOURCE_STATE": "",
                "XDG_STATE_HOME": str(state_home),
            }):
                self.assertEqual(
                    _managed_source_state_path(),
                    (state_home / "astrid" / "default" / "pack-sources.json").resolve(),
                )

    def test_text_binary_capture_bindings_resolution_and_replay_boundaries(self):
        text = ("line-0123456789\n" * 140_000).encode("utf-8")
        binary = bytes(range(256)) * 8_192
        text_result = self._submit(text, "text-capture")
        binary_result = self._submit(binary, "binary-capture", format="application/octet-stream")

        for result, source, expected_format in (
            (text_result, text, "text/plain; charset=utf-8"),
            (binary_result, binary, "application/octet-stream"),
        ):
            manifest = result["manifest"]
            self.assertEqual(manifest["byte_digest"], hashlib.sha256(source).hexdigest())
            self.assertEqual(manifest["byte_length"], len(source))
            self.assertEqual(manifest["format"], expected_format)
            self.assertEqual(manifest["origin"]["project_ref"], self.project.to_dict())
            self.assertEqual(manifest["origin"]["task_ref"], self.task.to_dict())
            self.assertEqual(manifest["origin"]["attempt_ref"], self.attempt.to_dict())
            self.assertEqual(manifest["attribution"]["original_creator"], "creator")
            self.assertEqual(manifest["attribution"]["submitter"], self.actor.to_dict())
            self.assertEqual(manifest["resource_selection"]["pack_id"], "evidence")
            bounded = self.handler.resolve(result["document_ref"], actor=self.actor, offset=17, max_bytes=31)
            self.assertEqual(bounded["bytes"], source[17:48])
            self.assertEqual(bounded["verification"], "range-not-revalidated")
            verified = self.handler.resolve(result["document_ref"], actor=self.actor, verify_full=True, max_bytes=0)
            self.assertEqual(verified["verification"], "full-verified")

        replay = self._submit(text, "text-capture")
        self.assertTrue(replay["replayed"])
        with self.assertRaises(ChangedInputError):
            self._submit(text + b"changed", "text-capture")

    def test_payload_manifest_and_receipt_interruption_recover_same_capture(self):
        source = b"payload-boundary" * 100_000
        for key, boundary in (("payload-boundary", "payload"), ("manifest-boundary", "manifest")):
            with self.assertRaises(PublicationInterrupted):
                self._submit(source, key, interrupt_at=boundary)
            staging = list((Path(self.directory.name) / "managed" / ".staging").glob("*.json"))
            self.assertTrue(staging, "interruption must leave inspectable staged metadata")
            recovered = self._submit(source, key)
            self.assertFalse(recovered["replayed"])
            self.assertEqual(recovered["manifest"]["byte_length"], len(source))

        with self.assertRaises(PublicationInterrupted):
            self._submit(source, "receipt-boundary", interrupt_at="receipt")
        recovered = self._submit(source, "receipt-boundary")
        self.assertTrue(recovered["replayed"])
        self.assertFalse(list((Path(self.directory.name) / "managed" / ".staging").glob("*.json")))

    def test_version_checkin_legacy_inline_and_pack_pin_admission(self):
        first = self._submit(b"v1", "version-base")
        second = self.handler.version(
            first["document_ref"], b"v2", actor=self.actor, logical_request_key="version-2",
            project_ref=self.project, original_creator="creator",
        )
        third = self.handler.checkin(
            first["document_ref"], b"v3", base_revision=second["revision_ref"].revision,
            actor=self.actor, logical_request_key="checkin-3", project_ref=self.project,
            original_creator="creator",
        )
        self.assertEqual(third["revision_ref"].revision, "rev-3")
        self.assertEqual(self.handler.status(first["document_ref"], actor=self.actor)["reference"].revision, "rev-3")

        legacy_ref = ResourceRef("owner", "dat.content.document", "legacy")
        legacy_head_ref = ResourceRef("owner", "dat.content.document", "legacy", "rev-1")
        legacy_doc = ContentDocument(legacy_ref, "evidence", "public", "read", "legacy-owner", writable=False)
        legacy_revision = ContentRevision(legacy_ref, "rev-1", {"legacy": "inline"}, self.actor, initial=True)
        self.store.put_identity(
            legacy_head_ref,
            {"record_type": "dat.content.document", "document": legacy_doc, "current_revision": legacy_revision.ref},
            version=1,
        )
        self.store.put_identity(
            revision_identity(legacy_ref, "rev-1"),
            {"record_type": "dat.content.revision", "document": legacy_ref, "revision": "rev-1", "content": legacy_revision.content, "author": self.actor},
            version=0,
        )
        inline = self.handler.status(legacy_ref, actor=self.actor)
        self.assertEqual(inline["representation"], "inline")
        self.assertEqual(inline["content"], {"legacy": "inline"})

        pack = self.pack
        self.assertEqual(len(pack.select().resources), 6)
        self.assertEqual(pack.source.source_inventory_identity, "c" * 64)
        self.assertEqual(pack.select().to_dict()["source"]["source_revision"], "a" * 40)
        pins = [item.to_dict() for item in pack.resources]
        pins[0]["digest"] = "0" * 64
        with self.assertRaises(EvidencePackError):
            pack.select(pins)

    def test_public_managed_discovery_rejects_unmanaged_and_incomplete_selection(self):
        managed = _public_managed_pack()
        pack = load_evidence_pack(managed_pack=managed)

        def discover_unmanaged(*, project_root):
            source = managed.source.to_dict()
            source["id"] = source.pop("pack_id")
            item = SimpleNamespace(**source, entry=SimpleNamespace())
            item.source_kind = "workspace"
            item.pack_dir = Path(managed.source.pack_root)
            return (item,)

        with self.assertRaises(PackProvenanceError):
            read_managed_pack(
                "evidence",
                project_root=Path(managed.source.pack_root).parents[3],
                discoverer=discover_unmanaged,
                loader=lambda *args, **kwargs: None,
            )

        incomplete = [item.to_dict() for item in pack.resources[:-1]]
        with self.assertRaises(EvidencePackError):
            pack.select(incomplete)

    def test_native_evidence_load_does_not_import_astrid(self):
        from herzchen.evidence.model import load_evidence_pack

        real_import = builtins.__import__

        def reject_astrid(name, *args, **kwargs):
            if name == "astrid" or name.startswith("astrid."):
                raise AssertionError("Herzchen attempted to import Astrid")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=reject_astrid):
            pack = load_evidence_pack(project_root=Path(__file__).parents[1])
        self.assertEqual(pack.pack_id, "evidence")
        self.assertEqual(pack.source.source_kind, "managed")
        self.assertEqual(len(pack.resources), 10)

    def test_installed_runtime_source_loads_without_astrid_and_rejects_tampering(self):
        from herzchen.evidence.model import load_evidence_pack
        from herzchen.packs import authoring

        with tempfile.TemporaryDirectory() as temporary:
            controller_root = Path(temporary)
            runtime_root = _copy_installed_runtime_source(controller_root)
            copied_authoring = runtime_root / "packs" / "authoring.py"
            resource = runtime_root / "packs" / "evidence_resource_pack" / "schemas" / "evidence.json"
            real_import = builtins.__import__

            def reject_astrid(name, *args, **kwargs):
                if name == "astrid" or name.startswith("astrid."):
                    raise AssertionError("Herzchen attempted to import Astrid")
                return real_import(name, *args, **kwargs)

            with patch.object(authoring, "__file__", str(copied_authoring)):
                with patch("builtins.__import__", side_effect=reject_astrid):
                    pack = load_evidence_pack(project_root=controller_root)
                self.assertEqual(pack.pack_id, "evidence")
                self.assertEqual(pack.source.source_revision, "f1cf6354767b4d46ec933725ef5ceafeecd5152c")

                resource.write_bytes(resource.read_bytes() + b" ")
                with self.assertRaises(EvidencePackError):
                    load_evidence_pack(project_root=controller_root)

    def test_native_source_provenance_matches_recorded_astrid_fixture_field_by_field(self):
        from herzchen.packs import authoring

        fixture_dir = Path(__file__).parent / "fixtures" / "managed_source_provenance"
        recording = json.loads((fixture_dir / "recorded_source.json").read_text(encoding="utf-8"))
        recorded_source = recording["source"]
        preimage_template = recording["source_inventory_preimage_template"]
        self.assertEqual(
            preimage_template,
            json.dumps(json.loads(preimage_template), sort_keys=True, separators=(",", ":")),
        )
        actual_records = []
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            for index, comment in enumerate((None, "loader-only comment change")):
                checkout = parent / f"checkout-{index}"
                repo_root, loader_path_hint, revision = _prepare_recorded_provenance_checkout(
                    checkout, loader_comment=comment
                )
                pack_root = repo_root / recorded_source["pack_root"]
                source_state_path = parent / f"pack-sources-{index}.json"
                state_record = {**recorded_source, "pack_root": str(pack_root.resolve())}
                source_state_path.write_text(json.dumps({
                    "version": 1,
                    "active": {recorded_source["pack_id"]: state_record},
                    "cached": {},
                    "disabled": [],
                }), encoding="utf-8")
                self.assertEqual(revision, recorded_source["revision"])
                with patch.object(authoring, "__file__", str(loader_path_hint)):
                    managed = read_managed_pack(
                        recorded_source["pack_id"], project_root=repo_root,
                        source_state_path=source_state_path,
                    )
                actual = managed.source.to_dict()
                expected = {
                    "pack_id": recorded_source["pack_id"],
                    "source_kind": recorded_source["source_kind"],
                    "source_revision": recorded_source["revision"],
                    "source_tree_sha256": recorded_source["tree_sha256"],
                    "source_manifest_sha256": recorded_source["manifest_sha256"],
                    "source_inventory_identity": hashlib.sha256(
                        preimage_template.replace(
                            json.dumps("<PACK_ROOT>"),
                            json.dumps(str(pack_root.resolve())),
                        ).encode("utf-8")
                    ).hexdigest(),
                    "pack_root": str(pack_root.resolve()),
                    "manifest_path": str((pack_root / "pack.yaml").resolve()),
                }
                self.assertEqual(actual, expected)
                if index == 0:
                    with loader_path_hint.open("a", encoding="utf-8") as stream:
                        stream.write("# loader-only comment change\n")
                    with patch.object(authoring, "__file__", str(loader_path_hint)):
                        after_comment = read_managed_pack(
                            recorded_source["pack_id"], project_root=repo_root,
                            source_state_path=source_state_path,
                        )
                    self.assertEqual(actual, after_comment.source.to_dict())
                actual_records.append(actual)

        self.assertNotEqual(actual_records[0]["pack_root"], actual_records[1]["pack_root"])
        self.assertNotEqual(
            actual_records[0]["source_inventory_identity"],
            actual_records[1]["source_inventory_identity"],
        )
        for field in ("source_revision", "source_tree_sha256", "source_manifest_sha256"):
            self.assertEqual(actual_records[0][field], actual_records[1][field])

    def test_recorded_provenance_checkout_cleanup_after_setup_and_assertion_failures(self):
        fixture_dir = Path(__file__).parent / "fixtures" / "managed_source_provenance"
        recording = json.loads((fixture_dir / "recorded_source.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            failed_setup = Path(temporary) / "failed-setup"
            run_git = subprocess.run

            def fail_after_repository_setup(command, *args, **kwargs):
                if command[:2] == ["git", "add"]:
                    raise OSError("forced setup failure after repository initialization")
                return run_git(command, *args, **kwargs)

            with self.assertRaises(OSError):
                with tempfile.TemporaryDirectory(dir=temporary) as checkout:
                    failed_setup = Path(checkout)
                    with patch("subprocess.run", side_effect=fail_after_repository_setup):
                        _prepare_recorded_provenance_checkout(failed_setup)
            self.assertFalse(failed_setup.exists())

            failed_assertion = Path(temporary) / "failed-assertion"
            with self.assertRaises(AssertionError):
                with tempfile.TemporaryDirectory(dir=temporary) as checkout:
                    failed_assertion = Path(checkout)
                    _prepare_recorded_provenance_checkout(failed_assertion)
                    self.assertEqual(recording["source"]["pack_id"], "forced assertion failure")
            self.assertFalse(failed_assertion.exists())

        self.assertFalse((fixture_dir / "checkout").exists())

    def test_native_loader_refuses_tampered_manifest_and_tree(self):
        from herzchen.packs import authoring

        with tempfile.TemporaryDirectory() as temporary:
            copied_herzchen = _copy_native_pack_tree(temporary)
            copied_pack = copied_herzchen / "packs" / "evidence_resource_pack"
            copied_authoring = copied_herzchen / "packs" / "authoring.py"
            with patch.object(authoring, "__file__", str(copied_authoring)):
                manifest = copied_pack / "pack.yaml"
                original = manifest.read_bytes()
                manifest.write_bytes(original + b"\n# tampered\n")
                with self.assertRaises(PackAuthoringError):
                    read_managed_pack("evidence", project_root=Path(temporary))
                manifest.write_bytes(original)

                resource = copied_pack / "schemas" / "evidence.json"
                original_resource = resource.read_bytes()
                resource.write_bytes(original_resource + b" ")
                with self.assertRaises(PackAuthoringError):
                    read_managed_pack("evidence", project_root=Path(temporary))


if __name__ == "__main__":
    unittest.main()
