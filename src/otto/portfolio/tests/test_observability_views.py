"""D04 operator presets remain a thin read-only adapter over the D03 reader."""

import unittest
import tempfile

from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import WorkGraph, contributions
from herzchen.kernel import ProjectHistoryGrant, Store
from otto.portfolio.observability_views import ObservabilityViewError, ObservabilityViews, VIEW_PRESETS


class Reader:
    def __init__(self):
        self.read_calls = []
        self.detail_calls = []
        self.snapshot = {
            "snapshot_digest": "snapshot-1",
            "scope": {
                "projects": (("owner", "project"),),
                "from": "2026-10-10T00:00:00Z",
                "to": "2026-10-11T00:00:00Z",
                "filters": {},
            },
        }

    def read(self, **kwargs):
        self.read_calls.append(kwargs)
        return {
            "rows": [{
                "facet_id": "facet-1",
                "subject_ref": {"authority": "owner", "kind": "work.task", "id": "task"},
                "facet_type": "retained_attempt_or_result",
                "role": "worker",
                "outcome": "completed",
                "summary": {
                    "after": {"fields": {"principal": "worker-1"}},
                    "response": "retained",
                    "application": "unknown",
                    "native_result": "captured",
                    "task_acceptance": "unknown",
                },
                "detail": {"evidence_refs": []},
            }],
            "projects": [{"authority": "owner", "kind": "work.project", "id": "project"}],
            "snapshot": self.snapshot,
            "snapshot_digest": "snapshot-1",
            "next_cursor": "cursor-2",
            "partial": False,
            "coverage": {"projection_generation": 1, "covered_append_position": 4, "lag": 0},
        }

    def detail(self, facet_id, **kwargs):
        self.detail_calls.append((facet_id, kwargs))
        return {
            "facet_id": facet_id,
            "project_ref": {"authority": "owner", "kind": "work.project", "id": "project"},
            "summary": {"response": "retained", "application": "unknown"},
            "detail_locator": {"evidence_refs": []},
            "evidence": None,
            "bytes": b"bounded",
            "truncated": False,
            "io_work": {"detail_bytes_read": 7},
        }


class ObservabilityViewsTests(unittest.TestCase):
    def setUp(self):
        self.reader = Reader()
        self.views = ObservabilityViews(self.reader)

    def test_every_preset_preserves_scope_coverage_and_keyset_continuation(self):
        for view in VIEW_PRESETS:
            with self.subTest(view=view):
                result = self.views.read(view, projects=[{"authority": "owner", "kind": "work.project", "id": "project"}], limit=1)
                self.assertEqual(result["scope"]["projects"][0]["id"], "project")
                self.assertEqual(result["coverage"]["covered_append_position"], 4)
                self.assertEqual(result["continuation"]["next_cursor"], "cursor-2")
                self.assertTrue(result["read_only"])

    def test_overview_and_detail_keep_response_application_and_result_acceptance_distinct(self):
        overview = self.views.read("overview", projects=[{"authority": "owner", "kind": "work.project", "id": "project"}])
        semantic = overview["rows"][0]["semantic"]
        self.assertEqual(semantic["response"]["value"], "retained")
        self.assertEqual(semantic["application"]["value"], "unknown")
        self.assertEqual(semantic["native_result"]["value"], "captured")
        self.assertEqual(semantic["task_acceptance"]["value"], "unknown")
        self.assertEqual(overview["rows"][0]["semantic"]["responsible_actor"]["value"], "worker-1")
        detail = self.views.detail("facet-1", snapshot=self.reader.snapshot)
        self.assertEqual(detail["semantic"]["application"]["value"], "unknown")
        self.assertEqual(self.reader.detail_calls[0][0], "facet-1")

    def test_usage_does_not_invent_accounting_cost_or_zero(self):
        result = self.views.read("usage", projects=[{"authority": "owner", "kind": "work.project", "id": "project"}])
        self.assertEqual(len(result["usage"]["known_attempts"]), 1)
        self.assertEqual(result["usage"]["metric_availability"][0]["state"], "unavailable")
        self.assertNotIn("total", result["usage"])
        self.assertNotIn("amount", result["usage"])
        self.assertNotIn("zero", result["usage"])

    def test_invalid_view_and_missing_detail_are_rejected_before_reader_work(self):
        with self.assertRaises(ObservabilityViewError):
            self.views.read("not-a-view")
        with self.assertRaises(ObservabilityViewError):
            self.views.detail("", snapshot=self.reader.snapshot)
        self.assertEqual(self.reader.read_calls, [])
        self.assertEqual(self.reader.detail_calls, [])

    def test_real_project_history_reader_is_reused_without_source_hydration(self):
        with tempfile.TemporaryDirectory(dir=".") as root:
            store = Store.create(root + "/events.sqlite", authority="owner")
            try:
                store.register_domain_handler(contributions(include_assignment_resources=True))
                actor = AuthenticatedActor("owner", "reader", "credential")
                store.configure_history_projection(batch_size=8)
                project = WorkGraph(store, actor=actor).create_project(title="Events", logical_request_key="d04-project")
                grant = ProjectHistoryGrant(actor, (project.id,), "tests", "grant-1")
                views = ObservabilityViews(store.project_history_reader(grant=grant))
                result = views.read("overview", projects=[project.ref], actor=actor, limit=1)
                self.assertEqual(result["coverage"]["lag"], 0)
                self.assertEqual(result["scope"]["projects"][0]["id"], project.id)
                detail = views.detail(result["rows"][0]["facet_id"], snapshot=result["snapshot"], actor=actor)
                self.assertTrue(detail["coverage"]["bounded"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
