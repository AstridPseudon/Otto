"""Offline checks that pyproject.toml declares the console scripts and package discovery.

Stdlib only and Python 3.9 compatible: pyproject.toml is checked with plain text
matching rather than a TOML parser, so no tomllib import is needed.
"""

import os
import re
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PYPROJECT = os.path.join(REPO_ROOT, "pyproject.toml")
SRC = os.path.join(REPO_ROOT, "src")


def _read_pyproject():
    with open(PYPROJECT, encoding="utf-8") as handle:
        return handle.read()


def _section(text, header):
    """Return the body of a TOML table (lines until the next [table] header)."""
    match = re.search(r"^\[" + re.escape(header) + r"\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.text = _read_pyproject()

    def test_console_scripts_declared_with_exact_targets(self):
        scripts = _section(self.text, "project.scripts")
        self.assertRegex(scripts, r'(?m)^ottoctl\s*=\s*"otto\.hostctl\.cli:main"\s*$')
        self.assertRegex(scripts, r'(?m)^otto-gateway\s*=\s*"otto\.cli:main"\s*$')

    def test_package_discovery_uses_src_and_namespaces(self):
        find = _section(self.text, "tool.setuptools.packages.find")
        self.assertRegex(find, r'(?m)^where\s*=\s*\[\s*"src"\s*\]\s*$')
        self.assertRegex(find, r"(?m)^namespaces\s*=\s*true\s*$")

    def test_package_data_includes_md_and_json(self):
        data = _section(self.text, "tool.setuptools.package-data")
        self.assertRegex(data, r'"\*"\s*=\s*\[\s*"\*\.md"\s*,\s*"\*\.json"\s*\]')

    def test_requires_python_is_3_9_or_newer(self):
        self.assertRegex(self.text, r'(?m)^requires-python\s*=\s*">=3\.9"\s*$')

    def test_build_backend_is_setuptools(self):
        system = _section(self.text, "build-system")
        self.assertIn('build-backend = "setuptools.build_meta"', system)

    def test_every_python_directory_is_under_a_discoverable_top_package(self):
        # With namespaces=true setuptools discovers every directory under src/,
        # so the guard is that all .py code lives under herzchen/ or otto/.
        top_levels = set()
        python_dirs = []
        for dirpath, dirnames, filenames in os.walk(SRC):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            if any(name.endswith(".py") for name in filenames):
                rel = os.path.relpath(dirpath, SRC)
                python_dirs.append(rel)
                top_levels.add(rel.split(os.sep)[0])
        self.assertEqual(top_levels, {"herzchen", "otto"})
        self.assertIn(os.path.join("herzchen", "packs"), python_dirs)

    def test_packs_package_dir_is_present_without_init(self):
        packs = os.path.join(SRC, "herzchen", "packs")
        self.assertTrue(os.path.isdir(packs))
        self.assertTrue(
            any(name.endswith(".py") for name in os.listdir(packs)),
            "herzchen/packs should contain python modules",
        )


if __name__ == "__main__":
    unittest.main()
