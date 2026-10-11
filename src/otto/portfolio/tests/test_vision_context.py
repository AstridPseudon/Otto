"""D04 context, history, and ordinary DAT checkpoint proof."""
from copy import deepcopy
import json
import unittest

from herzchen.contracts import ReferenceBinding
from herzchen.content.vision_context import (
    MAX_CONTEXT_EDGES,
    MAX_CONTEXT_JSON_BYTES,
    MAX_CONTEXT_NODES,
    MAX_RENDERED_BYTES,
    VisionContextError,
    VisionContextService,
    VisionSnapshotUnavailable,
)
from herzchen.content.vision_queries import VisionQueryService, VisionReorganizer
from herzchen.domains.work import WorkModule, register_work
from otto.portfolio.fixtures.vision import PAGES
from otto.portfolio.tests import test_vision_authoring as d02


class VisionContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = d02.VisionAuthoringTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for name, *_ in PAGES:
            self.fixture.create(name)
        self.queries = VisionQueryService(self.fixture.packets, actor=self.fixture.actor)
        self.context = VisionContextService(self.queries, actor=self.fixture.actor)

    def test_selected_context_is_bounded_and_keeps_context_sources_separate(self):
        result = self.context.context(
            self.fixture.refs["frame"],
            [self.fixture.refs["offline"]],
            "How should disconnected edits remain recoverable?",
            implementation_context={"status": "observed", "items": [{"commit": "sync@abc"}]},
            direction_context={"status": "adopted", "ref": {"id": "direction-r1", "revision": "rev-1"}},
            task_context={"status": "authorized", "ref": {"id": "task-r1", "revision": "rev-1"}},
        )
        self.assertLessEqual(len(result["nodes"]), MAX_CONTEXT_NODES)
        self.assertLessEqual(len(result["edges"]), MAX_CONTEXT_EDGES)
        self.assertLessEqual(result["rendered_intent_bytes"], MAX_RENDERED_BYTES)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), MAX_CONTEXT_JSON_BYTES)
        self.assertEqual(result["nodes"][0]["revision_ref"]["revision"], self.fixture.head(self.fixture.refs["frame"])[0].revision)
        self.assertTrue(all("digest" in node and "inclusion_reason" in node for node in result["nodes"]))
        self.assertIn("implementation_context", result)
        self.assertIn("direction_context", result)
        self.assertIn("task_context", result)
        self.assertFalse(result["provider_called"])
        self.assertFalse(result["effects_started"])

    def test_history_defaults_to_latest_and_is_bounded(self):
        original = self.fixture.head(self.fixture.refs["offline"])[0]
        opened = self.fixture.authoring.open_owned(self.fixture.refs["offline"], self.fixture.actor, request_id="d04-history-open")
        changed = deepcopy(self.fixture.nodes["offline"])
        changed["title"] = "Recoverable disconnected work"
        self.fixture.authoring.finish(opened, draft={"content": changed}, request_id="d04-history-finish")
        history = self.context.history(self.fixture.refs["offline"])
        self.assertTrue(history["latest_only_default"])
        self.assertEqual(history["revisions"][0]["revision_ref"]["revision"], self.fixture.head(self.fixture.refs["offline"])[0].revision)
        self.assertEqual(history["revisions"][1]["revision_ref"], original.to_dict())
        with self.assertRaisesRegex(VisionContextError, "between 1 and 50"):
            self.context.history(self.fixture.refs["offline"], limit=51)

    def test_collection_checkpoint_is_idempotent_and_historical_after_reorganization(self):
        saved = self.context.save_snapshot(
            scope="collection", root_ref=self.fixture.refs["frame"], request_key="d04-collection", label="Frame baseline"
        )
        self.assertEqual(saved["outcome"], "created")
        self.assertTrue(saved["coverage"]["complete"])
        old_offline = next(item["ref"] for item in saved["manifest"] if item["ref"]["id"] == self.fixture.refs["offline"].id)
        replay = self.context.save_snapshot(
            scope="collection", root_ref=self.fixture.refs["frame"], request_key="d04-collection", label="Frame baseline"
        )
        self.assertEqual(replay["outcome"], "replayed")
        changed = VisionReorganizer(self.fixture.authoring, self.fixture.actor).update(
            self.fixture.refs["offline"],
            {"title": "Recoverable disconnected work", "navigation_parent": ReferenceBinding(self.fixture.refs["creation"], "current").to_dict()},
            request_id="d04-reorganize",
        )
        self.assertEqual(changed["outcome"], "updated")
        historical = self.context.context(
            self.fixture.refs["frame"], [self.fixture.refs["offline"]], "What was the original offline design?",
            snapshot_ref=saved["snapshot_ref"],
        )
        old_node = next(node for node in historical["nodes"] if node["ref"]["id"] == self.fixture.refs["offline"].id)
        self.assertEqual(old_node["revision_ref"], old_offline)
        self.assertNotEqual(old_node["title"], "Recoverable disconnected work")

    def test_document_root_checkpoint_keeps_children_live_and_packet_read_rechecks_access(self):
        saved = self.context.save_snapshot(
            scope="document", root_ref=self.fixture.refs["frame"], document_ref=self.fixture.refs["frame"],
            request_key="d04-root-only", label="Root only"
        )
        self.assertTrue(saved["coverage"]["complete"])
        self.assertEqual(len(saved["manifest"]), 1)
        current = self.fixture.head(self.fixture.refs["offline"])[1]
        current["title"] = "Current child title"
        opened = self.fixture.authoring.open_owned(self.fixture.refs["offline"], self.fixture.actor, request_id="d04-live-child-open")
        self.fixture.authoring.finish(opened, draft={"content": current}, request_id="d04-live-child-finish")
        context = self.context.context(
            self.fixture.refs["frame"], [self.fixture.refs["offline"]], "What is current?", snapshot_ref=saved["snapshot_ref"]
        )
        child = next(node for node in context["nodes"] if node["ref"]["id"] == self.fixture.refs["offline"].id)
        self.assertEqual(child["title"], "Current child title")
        read = self.context.read_snapshot(saved["snapshot_ref"])
        self.assertEqual(read["status"], "ok")

    def test_changed_same_key_is_replay_conflict_and_partial_save_is_explicit(self):
        self.context.save_snapshot(
            scope="decision", input_refs=[self.fixture.refs["offline"]], request_key="d04-decision", label="Decision"
        )
        with self.assertRaisesRegex(VisionContextError, "replay_conflict"):
            self.context.save_snapshot(
                scope="decision", input_refs=[self.fixture.refs["sync"]], request_key="d04-decision", label="Decision"
            )
        partial = self.context.save_snapshot(
            scope="collection", root_ref=self.fixture.refs["frame"], request_key="d04-partial", label="Partial", allow_partial=True
        )
        self.assertTrue(partial["coverage"]["complete"])
        self.assertFalse(partial["global_instant_claim"])

    def test_unavailable_collection_member_blocks_complete_packet_without_hidden_metadata(self):
        register_work(self.fixture.store)
        project = WorkModule(self.fixture.store, actor=self.fixture.actor).create_project(
            title="D04 scoped context", logical_request_key="d04-scoped-project"
        )
        visible = {self.fixture.refs["frame"].id, self.fixture.refs["offline"].id}

        def membership(project_ref, document_ref, actor):
            return document_ref.id in visible

        scoped_queries = VisionQueryService(
            self.fixture.packets,
            actor=self.fixture.actor,
            grant={"project_ids": [project.ref.id], "principal": self.fixture.actor},
            membership_reader=membership,
        )
        scoped = VisionContextService(scoped_queries, actor=self.fixture.actor)
        with self.assertRaisesRegex(VisionSnapshotUnavailable, "partial_coverage"):
            scoped.save_snapshot(scope="collection", root_ref=self.fixture.refs["frame"], project_ref=project.ref, request_key="d04-incomplete")
        partial = scoped.save_snapshot(
            scope="collection", root_ref=self.fixture.refs["frame"], project_ref=project.ref,
            request_key="d04-incomplete-partial", allow_partial=True
        )
        self.assertFalse(partial["coverage"]["complete"])
        self.assertTrue(partial["coverage"]["partial"])
        self.assertTrue(all(set(item) == {"code", "field"} for item in partial["coverage"]["omissions"]))


if __name__ == "__main__":
    unittest.main()
