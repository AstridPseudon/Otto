"""D03 bounded relationship-query and reorganization proof."""
from copy import deepcopy
import unittest

from herzchen.content.vision_queries import VisionAuthorizationError, VisionQueryService, VisionReorganizer
from herzchen.contracts import ReferenceBinding
from herzchen.content.vision_queries import VisionAttachment
from herzchen.domains.work import WorkModule, register_work
from otto.portfolio.fixtures.vision import PAGES
from otto.portfolio.tests import test_vision_authoring as d02


class VisionQueryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = d02.VisionAuthoringTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for name, *_ in PAGES:
            self.fixture.create(name)
        self.service = VisionQueryService(self.fixture.packets, actor=self.fixture.actor)

    def test_fixed_views_use_one_bounded_projection(self):
        root = self.fixture.refs["frame"]
        outline = self.service.query(root, "outline")
        self.assertEqual(outline["status"], "ok")
        self.assertEqual(len(outline["rows"]), 14)
        self.assertEqual(outline["coverage"]["authorized_nodes"], 14)
        self.assertFalse(outline["coverage"]["partial"])
        self.assertEqual(outline["metrics"]["event_scans"], 0)
        self.assertFalse(outline["metrics"]["project_history_scanned"])

        related = self.service.query(root, "related", node_ref=self.fixture.refs["offline"], direction="both")
        self.assertIn("refines", {row["relation"] for row in related["rows"]})
        self.assertIn("parent", {row["relation"] for row in related["rows"]})

        direct = self.service.query(root, "by_repository", repository_refs=[self.fixture.refs["desktop"]])
        outgoing = self.service.query(root, "repositories_for", node_ref=self.fixture.refs["offline"])
        inverse = self.service.query(root, "related", node_ref=self.fixture.refs["offline"], direction="in")
        audit = self.service.query(root, "audit")
        self.assertEqual(direct["status"], outgoing["status"])
        self.assertEqual(audit["rows"], [])
        for response in (direct, outgoing, inverse):
            metrics = response["metrics"]
            self.assertEqual(metrics["content_reads"], 14)
            self.assertEqual(metrics["metadata_reads"], 14)
            self.assertGreater(metrics["bytes_read"], 0)
            self.assertEqual(metrics["owner_round_trips"], 14)
            self.assertEqual(metrics["storage_round_trips"], 14)
            self.assertEqual(metrics["event_scans"], 0)
            self.assertFalse(metrics["project_history_scanned"])
            self.assertGreaterEqual(metrics["latency_ms"], 0)

        shared = self.service.query(root, "shared_concepts", repository_refs=[
            self.fixture.refs["desktop"], self.fixture.refs["sync"], self.fixture.refs["model"]])
        offline = next(row for row in shared["rows"] if row["title"] == "Offline")
        self.assertEqual(len(offline["matched_repository_refs"]), 3)

        search = self.service.query(root, "search", q="disconnected")
        self.assertEqual([row["title"] for row in search["rows"]], ["Desktop", "Offline"])

    def test_pagination_basis_and_cold_warm_measurements_are_explicit(self):
        root = self.fixture.refs["frame"]
        first = self.service.query(root, "outline", limit=3)
        self.assertEqual(first["metrics"]["read_class"], "cold")
        self.assertIsNotNone(first["next_after_key"])
        second = self.service.query(root, "outline", limit=3, after_key=first["next_after_key"])
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["metrics"]["read_class"], "warm")
        self.assertNotEqual(first["rows"][0]["key"], second["rows"][0]["key"])
        changed = self.service.query(root, "outline", limit=3, basis_digest="0" * 64)
        self.assertEqual(changed["status"], "basis_changed")
        self.assertFalse(changed["effects_started"])

    def test_reorganization_preserves_identity_permissions_and_old_exact_revision(self):
        offline = self.fixture.refs["offline"]
        old_revision, old_content = self.fixture.head(offline)
        result = VisionReorganizer(self.fixture.authoring, self.fixture.actor).update(
            offline,
            {"title": "Recoverable disconnected work",
             "navigation_parent": ReferenceBinding(self.fixture.refs["creation"], "current").to_dict()},
            request_id="d03-reparent",
        )
        self.assertEqual(result["outcome"], "updated")
        self.assertTrue(result["stable_id_preserved"])
        self.assertTrue(result["permissions_unchanged"])
        self.assertEqual(result["document_ref"]["id"], offline.id)
        self.assertEqual(self.fixture.packets.resolve_reference(old_revision, actor=self.fixture.actor)["content"], old_content)
        current = self.fixture.head(offline)[1]
        self.assertEqual(current["title"], "Recoverable disconnected work")
        self.assertEqual(current["navigation_parent"]["ref"]["id"], self.fixture.refs["creation"].id)

        plan = VisionReorganizer.collection_transfer_plan(self.fixture.refs["frame"], self.fixture.refs["creation"], offline)
        self.assertEqual([step["operation"] for step in plan["steps"]], ["include", "remove"])
        self.assertFalse(plan["writes_performed"])

    def test_project_grant_membership_and_revocation_are_non_disclosing(self):
        register_work(self.fixture.store)
        project = WorkModule(self.fixture.store, actor=self.fixture.actor).create_project(
            title="D03 query scope", logical_request_key="d03-query-scope"
        )
        visible = {self.fixture.refs["frame"].id, self.fixture.refs["offline"].id}

        def membership(project_ref, document_ref, actor):
            return document_ref.id in visible

        service = VisionQueryService(
            self.fixture.packets,
            actor=self.fixture.actor,
            grant={"project_ids": [project.ref.id], "principal": self.fixture.actor},
            membership_reader=membership,
        )
        partial = service.query(self.fixture.refs["frame"], "outline", project_ref=project.ref)
        self.assertTrue(partial["coverage"]["partial"])
        self.assertEqual(partial["coverage"]["authorized_nodes"], 2)
        self.assertTrue(all(set(item) == {"code", "field"} for item in partial["coverage"]["omissions"]))

        visible.clear()
        with self.assertRaisesRegex(VisionAuthorizationError, "document_unavailable"):
            service.query(self.fixture.refs["frame"], "outline", project_ref=project.ref)

    def test_optional_attachment_is_ordinary_and_never_changes_visibility(self):
        created = self.fixture.create("offline")
        register_work(self.fixture.store)
        project = WorkModule(self.fixture.store, actor=self.fixture.actor).create_project(
            title="D03 attachment", logical_request_key="d03-attachment"
        )
        result = VisionAttachment(self.fixture.content, self.fixture.actor).apply(
            project.ref, [created.document_ref], request_id="d03-attach"
        )
        self.assertEqual(result["outcome"], "attached")
        self.assertEqual(len(result["receipts"]), 1)
        self.assertFalse(result["visibility_changed"])
        removed = VisionAttachment(self.fixture.content, self.fixture.actor).apply(
            project.ref, [created.document_ref], request_id="d03-attach-remove", remove=True
        )
        self.assertEqual(removed["outcome"], "removed")
        self.assertFalse(removed["visibility_changed"])

    def test_alias_delegation_and_collection_transfer_keep_receipts_separate(self):
        class AliasPort:
            def move_alias(self, **kwargs):
                self.kwargs = kwargs
                return {"outcome": "moved", "canonical_preserved": True, "committed": ["link", "unlink"]}

        alias = VisionReorganizer(self.fixture.authoring, self.fixture.actor).move_alias(
            AliasPort(), project_ref=self.fixture.refs["frame"], from_alias="old", to_alias="new",
            request_id="d03-alias"
        )
        self.assertEqual(alias["operation"], "alias_move")
        self.assertTrue(alias["stable_id_preserved"])
        self.assertTrue(alias["permissions_unchanged"])

        target_content = deepcopy(self.fixture.nodes["frame"])
        target_content["title"] = "Transferred collection"
        target_content["members"] = []
        target = self.fixture.creator.create(target_content, request_id="frame-target")
        transfer = VisionReorganizer(self.fixture.authoring, self.fixture.actor).transfer_collection(
            self.fixture.refs["frame"], target.document_ref, self.fixture.refs["offline"],
            request_id="d03-transfer"
        )
        self.assertEqual(transfer["outcome"], "transferred")
        self.assertTrue(transfer["partial_receipts_are_truthful"])
        source_members = self.fixture.head(self.fixture.refs["frame"])[1]["members"]
        target_members = self.fixture.head(target.document_ref)[1]["members"]
        self.assertNotIn(self.fixture.refs["offline"].id, {ReferenceBinding.from_dict(item).ref.id for item in source_members})
        self.assertIn(self.fixture.refs["offline"].id, {ReferenceBinding.from_dict(item).ref.id for item in target_members})


if __name__ == "__main__":
    unittest.main()
