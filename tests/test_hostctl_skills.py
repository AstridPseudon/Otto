from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest

try:
    from otto.hostctl import skills
except ImportError:  # fallback when the package __init__ is not importable yet
    _path = os.path.join(os.path.dirname(__file__), "..", "src", "otto", "hostctl", "skills.py")
    _spec = importlib.util.spec_from_file_location("otto_hostctl_skills", os.path.abspath(_path))
    skills = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(skills)

MARKER = skills.MARKER
SKILL_TEXT = (
    "---\nname: megado\ndescription: test\n---\n"
    "# Megado\n\n"
    f"{MARKER} Edition: unstamped source checkout. Replace me.\n\n"
    "Body text.\n"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_source(root: str, text: str = SKILL_TEXT) -> str:
    src = os.path.join(root, "source", "megado")
    os.makedirs(os.path.join(src, "references"))
    os.makedirs(os.path.join(src, "scripts"))
    os.makedirs(os.path.join(src, "__pycache__"))
    with open(os.path.join(src, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(src, "references", "a.md"), "w", encoding="utf-8") as fh:
        fh.write("reference A\n")
    with open(os.path.join(src, "scripts", "run.sh"), "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\necho hi\n")
    with open(os.path.join(src, ".DS_Store"), "wb") as fh:
        fh.write(b"junk")
    with open(os.path.join(src, "__pycache__", "x.pyc"), "wb") as fh:
        fh.write(b"junk")
    return src


class StampTests(unittest.TestCase):
    KW = dict(name="megado", edition="ed1", resolved_path="/p/ed1/megado",
              source_sha256="a" * 64, installed_at="2026-01-01T00:00:00Z")

    def test_replaces_existing_marker(self):
        out = skills.stamp_skill_text(SKILL_TEXT, **self.KW)
        lines = [ln for ln in out.splitlines() if ln.startswith(MARKER)]
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            lines[0],
            f"{MARKER} Edition: megado ed1 · installed 2026-01-01T00:00:00Z · "
            f"path /p/ed1/megado · source SKILL.md sha256 {'a' * 64}",
        )
        self.assertNotIn("unstamped", out)
        self.assertIn("Body text.", out)

    def test_inserts_below_title_when_absent(self):
        text = "---\nname: megado\n---\n# Megado\n\nBody.\n"
        out = skills.stamp_skill_text(text, **self.KW)
        lines = out.splitlines()
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[3], "# Megado")
        self.assertTrue(lines[4].startswith(MARKER))
        self.assertEqual(out.count(MARKER), 1)

    def test_inserts_at_top_without_front_matter_or_heading(self):
        out = skills.stamp_skill_text("Body only", **self.KW)
        self.assertTrue(out.splitlines()[0].startswith(MARKER))
        self.assertIn("Body only", out)

    def test_rejects_two_markers(self):
        text = f"# T\n{MARKER} one\n{MARKER} two\n"
        with self.assertRaises(skills.SkillInstallError):
            skills.stamp_skill_text(text, **self.KW)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.dest = os.path.join(self.root, "store")

    def tearDown(self):
        self._tmp.cleanup()

    def test_install_copies_stamps_and_writes_manifest(self):
        src = _make_source(self.root)
        m = skills.install_skill_tree(src, self.dest, name="megado", edition="ed1",
                                      source_commit="abc123", installed_at="2026-01-01T00:00:00Z")
        installed = os.path.join(self.dest, "ed1", "megado")
        self.assertEqual(m["schema"], "otto.skill-installation.v1")
        self.assertEqual(m["path"], os.path.realpath(installed))
        self.assertEqual(m["source_commit"], "abc123")
        self.assertFalse(m["replayed"])
        with open(os.path.join(src, "SKILL.md"), "rb") as fh:
            src_sha = _sha(fh.read())
        self.assertEqual(m["source_skill_sha256"], src_sha)
        self.assertEqual(sorted(m["files"]), ["SKILL.md", "references/a.md", "scripts/run.sh"])
        with open(os.path.join(installed, "SKILL.md"), "rb") as fh:
            installed_bytes = fh.read()
        self.assertIn(f"source SKILL.md sha256 {src_sha}".encode(), installed_bytes)
        self.assertNotIn(b"unstamped", installed_bytes)
        for rel, digest in m["files"].items():
            with open(os.path.join(installed, *rel.split("/")), "rb") as fh:
                self.assertEqual(_sha(fh.read()), digest)
        self.assertFalse(os.path.exists(os.path.join(installed, ".DS_Store")))
        self.assertFalse(os.path.exists(os.path.join(installed, "__pycache__")))
        with open(os.path.join(self.dest, "ed1", "installation-megado.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["files"], m["files"])

    def test_rejects_symlink_in_source(self):
        src = _make_source(self.root)
        os.symlink(os.path.join(src, "SKILL.md"), os.path.join(src, "link.md"))
        with self.assertRaises(skills.SkillInstallError):
            skills.install_skill_tree(src, self.dest, name="megado", edition="ed1")
        self.assertFalse(os.path.exists(os.path.join(self.dest, "ed1", "megado")))

    def test_replays_identical_install(self):
        src = _make_source(self.root)
        first = skills.install_skill_tree(src, self.dest, name="megado", edition="ed1",
                                          installed_at="2026-01-01T00:00:00Z")
        second = skills.install_skill_tree(src, self.dest, name="megado", edition="ed1",
                                           installed_at="2030-05-05T00:00:00Z")
        self.assertTrue(second["replayed"])
        self.assertEqual(second["installed_at"], first["installed_at"])
        self.assertEqual(second["files"], first["files"])

    def test_refuses_changed_reinstall_into_same_edition(self):
        src = _make_source(self.root)
        skills.install_skill_tree(src, self.dest, name="megado", edition="ed1")
        with open(os.path.join(src, "references", "a.md"), "w", encoding="utf-8") as fh:
            fh.write("changed\n")
        with self.assertRaises(skills.SkillInstallError):
            skills.install_skill_tree(src, self.dest, name="megado", edition="ed1")
        with open(os.path.join(self.dest, "ed1", "megado", "references", "a.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "reference A\n")


class LinkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_and_replaces_link(self):
        a = os.path.join(self.root, "a")
        b = os.path.join(self.root, "b")
        os.makedirs(a)
        os.makedirs(b)
        link = os.path.join(self.root, "host", "skills", "megado")
        r1 = skills.link_skill(link, a)
        self.assertIsNone(r1["previous"])
        self.assertEqual(os.path.realpath(link), os.path.realpath(a))
        r2 = skills.link_skill(link, b)
        self.assertEqual(r2["previous"], a)
        self.assertEqual(os.path.realpath(link), os.path.realpath(b))
        self.assertEqual(r2["target"], os.path.realpath(b))

    def test_refuses_real_directory(self):
        target = os.path.join(self.root, "t")
        os.makedirs(target)
        link = os.path.join(self.root, "megado")
        os.makedirs(link)
        with self.assertRaises(skills.SkillInstallError):
            skills.link_skill(link, target)
        self.assertTrue(os.path.isdir(link) and not os.path.islink(link))


class WhichAndDriftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.dest = os.path.join(self.root, "store")
        src = _make_source(self.root)
        self.manifest = skills.install_skill_tree(src, self.dest, name="megado", edition="ed1")
        self.installed = os.path.join(self.dest, "ed1", "megado")

    def tearDown(self):
        self._tmp.cleanup()

    def _two_hop_chain(self):
        hop1 = os.path.join(self.root, "host1", "megado")
        hop2 = os.path.join(self.root, "host2", "megado")
        os.makedirs(os.path.dirname(hop2))
        os.makedirs(os.path.dirname(hop1))
        os.symlink(self.installed, hop2)
        os.symlink(os.path.relpath(hop2, os.path.dirname(hop1)), hop1)
        return hop1, hop2

    def test_follows_two_hop_chain(self):
        hop1, hop2 = self._two_hop_chain()
        info = skills.which_skill(hop1)
        self.assertEqual(info["chain"], [os.path.abspath(hop1), os.path.abspath(hop2), self.installed])
        self.assertEqual(info["resolved"], os.path.realpath(self.installed))
        self.assertEqual(info["skill_md"], os.path.join(info["resolved"], "SKILL.md"))
        self.assertTrue(info["edition_line"].startswith(MARKER))
        self.assertTrue(info["stamped"])
        self.assertEqual(info["name"], "megado")
        self.assertEqual(info["edition"], "ed1")
        self.assertEqual(info["manifest"]["files"], self.manifest["files"])
        self.assertTrue(info["manifest_path_matches"])
        self.assertEqual(info["drift"], [])

    def test_drift_after_editing_installed_file(self):
        hop1, _ = self._two_hop_chain()
        with open(os.path.join(self.installed, "references", "a.md"), "a", encoding="utf-8") as fh:
            fh.write("edited after install\n")
        with open(os.path.join(self.installed, "extra.md"), "w", encoding="utf-8") as fh:
            fh.write("new\n")
        os.unlink(os.path.join(self.installed, "scripts", "run.sh"))
        info = skills.which_skill(hop1)
        self.assertEqual(info["drift"], ["extra.md", "references/a.md", "scripts/run.sh"])
        verdict = skills.verify_installation(os.path.join(self.dest, "ed1", "installation-megado.json"))
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["drift"], info["drift"])

    def test_clean_install_verifies_ok(self):
        verdict = skills.verify_installation(os.path.join(self.dest, "ed1", "installation-megado.json"))
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["drift"], [])


if __name__ == "__main__":
    unittest.main()
