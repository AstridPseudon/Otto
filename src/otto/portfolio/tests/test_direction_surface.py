"""D05 bounded direction projections over the existing owner capabilities."""
from dataclasses import replace
import contextlib
import io
import json
import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.direction import owner_direction_subject
from otto.portfolio.direction_surface import DirectionSurface
from otto.portfolio import cli

from . import test_direction_bindings as fixtures


class DirectionSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.DirectionBindingsTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.surface = DirectionSurface(self.f.directions, actor=self.f.actor)

    def bind_and_adopt(self):
        bound = self.f.bind()
        adopted = self.f.directions.adopt(
            self.f.subject, replace(self.f.document.ref, revision="rev-1"),
            expected_binding_ref=bound["binding_ref"], actor=self.f.actor,
            logical_request_key="surface-adopt",
        )
        return bound, adopted

    def test_read_distinguishes_unbound_pending_and_effective(self):
        unbound = self.surface.read(self.f.subject)
        self.assertEqual(unbound["state"], "unbound")
        self.assertEqual(unbound["next_action"], "initial-bind an owned direction document")

        self.f.bind()
        pending = self.surface.read(self.f.subject)
        self.assertEqual(pending["outcome"], "pending")
        self.assertEqual(pending["error"]["code"], "unadopted_direction")
        self.assertIn("adopt", pending["next_action"])

        self.bind_and_adopt()
        effective = self.surface.read(self.f.subject)
        self.assertEqual(effective["state"], "effective")
        self.assertEqual(effective["latest_ref"]["revision"], "rev-1")
        self.assertEqual(effective["scope_adopted_ref"]["revision"], "rev-1")
        self.assertIsNone(effective["delivered_ref"])
        self.assertEqual(effective["delivery_status"], "not_inspected")

    def test_draft_update_and_history_keep_latest_separate_from_adoption(self):
        self.bind_and_adopt()
        draft = self.surface.draft(
            self.f.subject, {"text": "Draft only"}, logical_request_key="surface-draft",
            expected_revision="rev-1",
        )
        self.assertFalse(draft["adopted"])
        read = self.surface.read(self.f.subject)
        self.assertTrue(read["pending_scope_adoption"])
        self.assertNotEqual(read["latest_ref"], read["scope_adopted_ref"])

        updated = self.surface.update(
            self.f.subject, draft["revision_ref"],
            logical_request_key="surface-update",
        )
        self.assertEqual(updated["outcome"], "updated")
        history = self.surface.history(self.f.subject)
        self.assertEqual([item["ref"]["revision"] for item in history["revisions"]],
                         ["rev-1", draft["revision_ref"]["revision"]])
        self.assertEqual(len(history["scope_adoptions"]), 2)
        self.assertEqual(history["occurrence_evidence"], [])
        self.assertTrue(history["history_limitations"])

        delivered = DirectionSurface(
            self.f.directions, actor=self.f.actor,
            occurrence_reader=lambda **kwargs: [{"schedule_id": "occ-1", "delivery_status": "delivered"}],
        ).history(self.f.subject)
        self.assertEqual(delivered["occurrence_evidence"][0]["schedule_id"], "occ-1")
        self.assertEqual(delivered["history_limitations"], [])

    def test_effective_context_is_attributed_and_whoami_requires_trusted_binding(self):
        calls = []
        context = [{"kind": "owner", "effective_ref": {"authority": "a", "kind": "dat.content.document", "id": "overall", "revision": "rev-1"},
                    "inputs": [{"ref": {"authority": "a", "kind": "dat.content.document", "id": "overall", "revision": "rev-1"}, "content_sha256": "x"}]}]
        surface = DirectionSurface(self.f.directions, actor=self.f.actor,
                                   context_reader=lambda **kwargs: calls.append(kwargs) or context)
        result = surface.effective_context(
            assignment_ref=self.f.assignment.ref, generation=1,
            project_ref=self.f.project.ref, task_ref=self.f.task.ref,
        )
        self.assertEqual(result["outcome"], "read")
        self.assertEqual(result["direction_context"], context)
        self.assertEqual(result["inputs"], context[0]["inputs"])
        self.assertEqual(calls[0]["generation"], 1)
        whoami = surface.whoami()
        self.assertEqual(whoami["outcome"], "unavailable")
        self.assertEqual(whoami["error"]["code"], "caller_context_unavailable")

    def test_overview_is_bounded_permission_scoped_and_includes_supplied_history_rows(self):
        self.bind_and_adopt()
        other = self.f.owner.graph.create_project(title="Other", logical_request_key="other-project")
        subjects = [
            {"subject_ref": self.f.subject.to_dict(), "project_ref": self.f.project.ref.to_dict(), "status": "active"},
            {"subject_ref": owner_direction_subject(self.f.actor.authority).to_dict(), "status": "retired"},
            {"subject_ref": other.ref.to_dict(), "project_ref": other.ref.to_dict(), "status": "completed"},
        ]
        surface = DirectionSurface(
            self.f.directions, actor=self.f.actor,
            allowed_project=lambda ref: ref.id == self.f.project.id,
        )
        page = surface.overview(subjects, limit=1)
        self.assertEqual(page["outcome"], "listed")
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["total"], 2)  # current responsibility plus owner-wide retired row
        self.assertTrue(page["pagination"]["has_more"])
        next_page = surface.overview(subjects, limit=1, cursor=page["pagination"]["cursor"])
        self.assertEqual(next_page["count"], 1)
        self.assertTrue(any(row["historical"] for row in page["items"] + next_page["items"]))
        self.assertEqual(page["inventory_basis"], "existing owner-provided canonical subjects; no roster created")

    def test_cli_exposes_direction_family_and_reports_missing_owner_surface(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main([
                "direction", "read", "--actor", self.f.actor.actor,
                "--subject-ref", json.dumps(self.f.subject.to_dict()),
            ], direction_operations=self.surface)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "unbound")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main(["direction", "whoami", "--actor", "owner"])
        self.assertEqual(status, 3)
        missing = json.loads(output.getvalue())
        self.assertEqual(missing["error"]["code"], "direction_operations_unavailable")


if __name__ == "__main__":
    unittest.main()
