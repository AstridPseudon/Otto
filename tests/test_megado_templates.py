"""The Megado run templates, the host model profiles and the run-file loader agree."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from otto.agents.host_profiles import PROFILES, SLOTS
from otto.portfolio.run_config import read_run_config, run_config_path
from herzchen.packs.authoring import read_managed_pack
from herzchen.contracts import ResourceRef
from herzchen.domains.work import WorkGraph, contributions
from herzchen.kernel.store import Store
from herzchen.packs.templates import TemplateEngine, WorkTemplate

REPO = Path(__file__).resolve().parents[1]
PACK_ROOT = REPO / "src" / "otto" / "packs" / "megado"
SKILL = PACK_ROOT / "skill"


class TemplateTests(unittest.TestCase):
    def test_megado_is_a_complete_loadable_managed_pack(self):
        manifest = json.loads((PACK_ROOT / "pack.yaml").read_text())
        declared = {resource["path"] for resource in manifest["resources"]}
        for resource_path in declared:
            with self.subTest(resource=resource_path):
                self.assertTrue((PACK_ROOT / resource_path).is_file(), resource_path)
        self.assertIn("skill/SKILL.md", declared)
        self.assertIn("skill/templates/run.json", declared)
        self.assertIn("skill/templates/run.claude.json", declared)
        pack = read_managed_pack(
            "megado", project_root=REPO, native_pack_root=REPO / "src" / "otto" / "packs"
        )
        self.assertEqual(pack.pack_id, "megado")
        self.assertEqual({item.path for item in pack.resources}, declared)

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


    def test_domain_templates_load_and_instantiate_with_criteria_and_source_pin(self):
        declarations = {
            "engineering": {
                "engineering.code-task": {"focused pytest", "implementation behavior"},
            },
            "astrid": {
                "astrid.journey": {"journey continuity", "frame composition"},
                "astrid.film-edit": {"edit structure", "render review"},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            store = Store.create(Path(directory) / "owner.sqlite", authority="domain-template-test")
            self.addCleanup(store.close)
            store.register_domain_handler(contributions())
            with patch.dict(os.environ, {"HERZCHEN_IN_PROCESS_COMMAND_FALLBACK": "1"}):
                graph = WorkGraph(store)
                engine = TemplateEngine(store, graph=graph)
            for pack_id, templates in declarations.items():
                pack = read_managed_pack(
                    pack_id, project_root=REPO, native_pack_root=REPO / "src" / "otto" / "packs"
                )
                for template_id, expected_criteria in templates.items():
                    with self.subTest(pack=pack_id, template=template_id):
                        resource = next(
                            item for item in pack.resources
                            if item.kind == "work_template" and item.path.endswith(".json")
                            and json.loads(item.content).get("id") == template_id
                        )
                        raw = json.loads(resource.content)
                        self.assertEqual(raw["version"], "1.0.0")
                        source_pin = ResourceRef.from_dict(resource.source_ref.to_dict())
                        self.assertEqual(source_pin.authority, "managed-source")
                        self.assertEqual(source_pin.kind, "managed_pack")
                        self.assertEqual(source_pin.id, pack_id)
                        self.assertEqual(source_pin.revision, pack.source.source_revision)
                        template = WorkTemplate(
                            raw["id"], raw["version"], raw["parameters"], raw["seed"],
                            source_ref=source_pin,
                        )
                        result = engine.instantiate(
                            template, {"title": "Template proof", "outcome": "Create declared project"},
                            logical_request_key=f"{template_id}:instance",
                        )
                        project = graph.current(result.project)
                        self.assertEqual(project.kind.value, "project")
                        self.assertEqual(project.title, "Template proof")
                        self.assertEqual(project.payload["metadata"]["template_origin"]["revision"], "1.0.0")
                        criteria = [
                            item.title.lower()
                            for item in graph.list(project=project.ref)
                            if item.kind.value == "criterion"
                        ]
                        for expected in expected_criteria:
                            self.assertTrue(any(expected in title for title in criteria), (expected, criteria))


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
