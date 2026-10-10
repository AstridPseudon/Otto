"""D03 projection, snapshot, grant and bounded-reader qualification."""

import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import WorkGraph, contributions
from herzchen.kernel import (
    ProjectHistoryGrant,
    SnapshotRefreshRequired,
    Store,
)
from herzchen.kernel.project_history import AuthorizationError


class ProjectHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(self.temp.name + "/events.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(contributions(include_assignment_resources=True))
        self.actor = AuthenticatedActor("owner", "reader", "credential")
        self.projection = self.store.configure_history_projection(batch_size=8)
        self.graph = WorkGraph(self.store, actor=self.actor)
        self.project = self.graph.create_project(title="Events", logical_request_key="project")
        self.grant = ProjectHistoryGrant(self.actor, (self.project.id,), "tests", "grant-1")
        self.reader = self.store.project_history_reader(grant=self.grant)

    def test_post_commit_projection_and_keyset_reader_are_bounded(self):
        with patch.object(self.store, "list_events", side_effect=AssertionError("reader hydrated source history")):
            page = self.reader.read(projects=[self.project.ref], limit=1)
        self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(page["io_work"]["rows_returned"], 1)
        self.assertEqual(page["coverage"]["lag"], 0)
        detail = self.reader.detail(page["rows"][0]["facet_id"], snapshot=page["snapshot"])
        self.assertLessEqual(detail["io_work"]["detail_bytes_read"], 64 * 1024)

    def test_fixed_snapshot_survives_late_facts_but_rebuild_invalidates_it(self):
        first = self.reader.read(projects=[self.project.ref], limit=50)
        self.graph.revise(self.project, title="Later", logical_request_key="later")
        old = self.reader.read(projects=[self.project.ref], snapshot=first["snapshot"], limit=50)
        current = self.reader.read(projects=[self.project.ref], limit=50)
        self.assertEqual(len(old["rows"]), 1)
        self.assertEqual(len(current["rows"]), 2)
        self.projection.rebuild(batch_size=1)
        with self.assertRaises(SnapshotRefreshRequired):
            self.reader.read(projects=[self.project.ref], snapshot=first["snapshot"], limit=50)

    def test_active_discovery_includes_authorized_active_project_without_events(self):
        other = self.graph.create_project(title="Other", logical_request_key="other")
        self.graph.set_lifecycle(self.project.ref, "active", logical_request_key="activate")
        grant = ProjectHistoryGrant(self.actor, (self.project.id, other.id), "tests", "grant-2")
        reader = self.store.project_history_reader(grant=grant)
        page = reader.read(projects=[self.project.ref, other.ref],
                           active_during=("2026-01-01", "2027-01-01"),
                           timezone_name="UTC", limit=50)
        matched = {item["id"] for item in page["matched_projects"]}
        self.assertIn(self.project.id, matched)
        self.assertNotIn(other.id, matched)

    def test_detail_rejects_a_facet_outside_the_snapshot_project_scope(self):
        other = self.graph.create_project(title="Other", logical_request_key="other")
        grant = ProjectHistoryGrant(self.actor, (self.project.id, other.id), "tests", "grant-2")
        reader = self.store.project_history_reader(grant=grant)
        scoped = reader.read(projects=[self.project.ref], limit=50)
        outside = reader.read(projects=[other.ref], limit=50)
        facet_id = outside["rows"][0]["facet_id"]

        with self.assertRaises(AuthorizationError):
            reader.detail(facet_id, snapshot=scoped["snapshot"])

    def test_old_snapshot_active_discovery_excludes_late_activation(self):
        other = self.graph.create_project(title="Other", logical_request_key="other")
        grant = ProjectHistoryGrant(self.actor, (self.project.id, other.id), "tests", "grant-2")
        reader = self.store.project_history_reader(grant=grant)
        initial = reader.read(
            projects=[self.project.ref, other.ref],
            active_during=("2026-01-01", "2027-01-01"),
            timezone_name="UTC",
            limit=50,
        )

        self.graph.set_lifecycle(other.ref, "active", logical_request_key="late-activation")
        current = reader.read(
            projects=[self.project.ref, other.ref],
            active_during=("2026-01-01", "2027-01-01"),
            timezone_name="UTC",
            limit=50,
        )
        old = reader.read(
            projects=[self.project.ref, other.ref],
            active_during=("2026-01-01", "2027-01-01"),
            timezone_name="UTC",
            snapshot=initial["snapshot"],
            limit=50,
        )

        self.assertIn(other.id, {item["id"] for item in current["matched_projects"]})
        self.assertNotIn(other.id, {item["id"] for item in old["matched_projects"]})

    def test_date_only_ranges_require_timezone_and_grant_revision_requires_refresh(self):
        with self.assertRaises(ValueError):
            self.reader.read(projects=[self.project.ref], from_at="2026-01-01", to_at="2026-01-02")
        first = self.reader.read(projects=[self.project.ref], limit=1)
        changed = ProjectHistoryGrant(self.actor, (self.project.id,), "tests", "grant-2")
        with self.assertRaises(SnapshotRefreshRequired):
            self.reader.read(projects=[self.project.ref], snapshot=first["snapshot"], grant=changed, limit=1)


if __name__ == "__main__":
    unittest.main()
