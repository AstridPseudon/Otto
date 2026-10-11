"""The Megado run templates, the host model profiles and the run-file loader agree."""
import json
from pathlib import Path
import tempfile
import unittest

from otto.agents.host_profiles import PROFILES, SLOTS
from otto.portfolio.run_config import read_run_config, run_config_path

SKILL = Path(__file__).resolve().parents[1] / "policy-staging" / "megado" / "skill"


class TemplateTests(unittest.TestCase):
    def test_templates_are_json_and_match_the_host_profiles(self):
        for name, profile in (("run.json", "codex"), ("run.claude.json", "claude")):
            template = json.loads((SKILL / "templates" / name).read_text())
            self.assertEqual(set(template["roles"]), set(SLOTS), name)
            self.assertEqual(template["roles"], {slot: dict(PROFILES[profile]["roles"][slot]) for slot in SLOTS}, name)
        self.assertFalse((SKILL / "templates" / "run.yaml").exists())
        self.assertNotIn("model_profile", json.loads((SKILL / "templates" / "run.json").read_text()))

    def test_skill_carries_one_edition_marker_and_the_named_modes(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertEqual(sum(line.startswith("> <!-- otto-edition -->") for line in text.splitlines()), 1)
        self.assertIn("setup_not_activated", text)
        config = (SKILL / "references" / "run-config.md").read_text()
        self.assertIn("## Glossary", config)
        self.assertIn("0. Adopt work already in flight", (SKILL / "references" / "project-lifecycle.md").read_text())
        self.assertIn("Product acceptance is not a review stage",
                      (SKILL / "references" / "pragmatic-review.md").read_text())


class RunConfigLoaderTests(unittest.TestCase):
    def test_run_json_preferred_legacy_run_yaml_read_and_both_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(run_config_path(root).name, "run.yaml")
            (root / "run.yaml").write_text(json.dumps({"roles": {"worker_normal": {"model": "m", "reasoning": "high"}}}))
            self.assertEqual(read_run_config(root)["roles"]["worker_normal"]["model"], "m")
            (root / "run.json").write_text(json.dumps({"roles": {}}))
            with self.assertRaises(ValueError):
                read_run_config(root)
            (root / "run.yaml").unlink()
            self.assertEqual(run_config_path(root).name, "run.json")
            self.assertEqual(read_run_config(root), {"roles": {}})
            (root / "run.json").write_text("roles: {}\n")
            with self.assertRaisesRegex(ValueError, "must be JSON"):
                read_run_config(root)


if __name__ == "__main__":
    unittest.main()
