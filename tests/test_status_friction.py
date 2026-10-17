import unittest
from unittest.mock import patch

from otto.portfolio import cli
from otto.portfolio.observability_views import ObservabilityViews


class RetainedReader:
    def __init__(self, rows):
        self.rows = rows
        self.kwargs = None

    def read(self, **kwargs):
        self.kwargs = kwargs
        return {
            "rows": self.rows,
            "projects": kwargs["projects"],
            "snapshot": {"snapshot_digest": "snapshot", "scope": {"projects": kwargs["projects"]}},
            "snapshot_digest": "snapshot",
            "next_cursor": None,
            "partial": False,
            "coverage": {"lag": 0},
        }


class StatusFrictionTests(unittest.TestCase):
    def test_status_friction_uses_authorized_retained_rows_and_marks_missing_metrics_unavailable(self):
        rows = [
            {"facet_id": "q", "facet_type": "question", "subject_ref": {"kind": "work.task", "id": "t1"},
             "summary": {"question": "Need a decision"}},
            {"facet_id": "r", "outcome": "refused", "subject_ref": {"kind": "work.task", "id": "t1"},
             "summary": {"next_action": "Use the supported route"}},
            {"facet_id": "rw", "outcome": "rework", "subject_ref": {"kind": "work.task", "id": "t2"}, "summary": {}},
            {"facet_id": "u", "subject_ref": {"kind": "work.task", "id": "t1"},
             "summary": {"unknown_effect": True}},
            {"facet_id": "wait", "subject_ref": {"kind": "work.task", "id": "t1"},
             "summary": {"awaiting_answer": True}},
            {"facet_id": "heavy", "subject_ref": {"kind": "work.task", "id": "t1"},
             "summary": {"heavy_seconds": 12}},
            {"facet_id": "accepted", "subject_ref": {"kind": "work.task", "id": "t1"},
             "summary": {"task_acceptance": "accepted", "tokens": 900}},
        ]
        reader = RetainedReader(rows)
        views = ObservabilityViews(reader)
        project = {"authority": "owner", "kind": "work.project", "id": "p"}
        grant = object()
        base = {"outcome": "read", "projects": [{"project_ref": project}]}
        args = cli.build_parser().parse_args(["status", "--friction"])
        with patch("otto.portfolio.status.portfolio_status", return_value=base):
            result = cli._status_command(args, object(), None, views, grant)

        friction = result["friction"]
        self.assertEqual(friction["counts"]["questions"], {"state": "known", "value": 1})
        self.assertEqual(friction["counts"]["refusals"]["value"], 1)
        self.assertEqual(friction["counts"]["next_actions"]["value"], 1)
        self.assertEqual(friction["counts"]["reworks"]["value"], 1)
        self.assertEqual(friction["counts"]["unknown_effects"]["value"], 1)
        self.assertEqual(friction["counts"]["answer_waits"]["value"], 1)
        self.assertEqual(friction["heavy_seconds"]["value"], 12)
        self.assertEqual(friction["tokens_per_accepted_task"]["value"], 900)
        self.assertEqual(reader.kwargs["grant"], grant)
        self.assertEqual(reader.kwargs["projects"], [project])
        self.assertEqual(reader.kwargs["limit"], 200)

    def test_inaccessible_or_incomplete_events_are_unavailable_not_zero(self):
        class DeniedViews:
            def read(self, *args, **kwargs):
                raise PermissionError("scope denied")

        args = cli.build_parser().parse_args(["status", "--friction"])
        with patch("otto.portfolio.status.portfolio_status", return_value={"outcome": "read", "projects": []}):
            result = cli._status_command(args, object(), None, DeniedViews(), object())
        friction = result["friction"]
        self.assertEqual(friction["coverage"], "partial-or-inaccessible")
        for item in friction["counts"].values():
            self.assertEqual(item, {"state": "unavailable", "value": None})
        self.assertIsNone(friction["heavy_seconds"]["value"])
        self.assertIsNone(friction["tokens_per_accepted_task"]["value"])


if __name__ == "__main__":
    unittest.main()
