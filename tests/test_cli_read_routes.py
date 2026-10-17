"""The retained ``status`` and ``show`` routes preserve bounded owner read inputs."""

from contextlib import redirect_stdout
from io import StringIO
import json
import unittest

from otto.portfolio import cli


PROJECT = {"authority": "owner", "kind": "work.project", "id": "p1", "revision": "r1"}
TASK = {"authority": "owner", "kind": "work.task", "id": "t1", "revision": "r1"}


class Portfolio:
    def __init__(self):
        self.calls = []

    def list_work(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "outcome": "listed", "projects": [{"project_ref": PROJECT, "title": "P"}],
            "items": [{"ref": TASK, "project_ref": PROJECT, "title": "T"}], "counts": {"pending": 1},
            "pagination": {"has_more": True, "cursor": "next-page"},
        }


class Views:
    def __init__(self):
        self.calls = []

    def read(self, view, **kwargs):
        self.calls.append((view, kwargs))
        return {"outcome": "listed", "rows": [], "next_cursor": "next-history"}


class RetainedReadRouteTests(unittest.TestCase):
    def run_cli(self, argv, **kwargs):
        output = StringIO()
        with redirect_stdout(output):
            code = cli.main(argv, **kwargs)
        return code, json.loads(output.getvalue())

    def test_show_project_preserves_actor_scope_page_size_and_cursor(self):
        portfolio = Portfolio()
        code, result = self.run_cli(
            ["show", "project", "--actor", "reader", "--project-ref", json.dumps(PROJECT),
             "--limit", "1", "--cursor", "start"], portfolio=portfolio,
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(result["tasks"], [{"ref": TASK, "project_ref": PROJECT, "title": "T"}])
        self.assertEqual(result["pagination"]["cursor"], "next-page")
        self.assertEqual(portfolio.calls, [{"actor": "reader", "view": "all", "project_ref": PROJECT,
                                            "cursor": "start", "limit": 1}])

    def test_show_tasks_and_task_keep_existing_owner_pagination(self):
        portfolio = Portfolio()
        code, result = self.run_cli(
            ["show", "tasks", "--actor", "reader", "--project-ref", json.dumps(PROJECT),
             "--limit", "1", "--cursor", "task-page"], portfolio=portfolio,
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(result["pagination"]["cursor"], "next-page")
        self.assertEqual(portfolio.calls[-1], {"actor": "reader", "view": "all", "project_ref": PROJECT,
                                               "parent_ref": None, "cursor": "task-page", "limit": 1})

        code, detail = self.run_cli(
            ["show", "task", "--actor", "reader", "--project-ref", json.dumps(PROJECT),
             "--task-ref", json.dumps(TASK), "--limit", "1"], portfolio=portfolio,
        )
        self.assertEqual(code, 0, detail)
        self.assertEqual(detail["task"]["ref"], TASK)
        self.assertEqual(portfolio.calls[-1]["project_ref"], PROJECT)

    def test_show_history_preserves_authenticated_bounded_read_parameters(self):
        views = Views()
        grant = object()
        code, result = self.run_cli(
            ["show", "history", "overview", "--actor", "reader", "--project-ref", json.dumps(PROJECT),
             "--limit", "2", "--cursor", "history-page"],
            observability_views=views, observability_grant=grant,
        )
        self.assertEqual(code, 0, result)
        view, kwargs = views.calls[0]
        self.assertEqual(view, "overview")
        self.assertEqual(kwargs["projects"][0], PROJECT)
        self.assertIs(kwargs["grant"], grant)
        self.assertEqual(kwargs["actor"], "reader")
        self.assertEqual(kwargs["limit"], 2)
        self.assertEqual(kwargs["cursor"], "history-page")
        self.assertEqual(result["next_cursor"], "next-history")


if __name__ == "__main__":
    unittest.main()
