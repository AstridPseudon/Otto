"""The retained ``status`` and ``show`` routes preserve bounded owner read inputs."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import argparse
import json
from pathlib import Path
import unittest

from otto.portfolio import cli
from otto.hostctl.portfolio import OWNER_PORTFOLIO_COMMANDS, prepare_portfolio_request
from otto.hostctl.service import OwnerService


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
    def test_installed_parser_only_advertises_reachable_routes(self):
        commands = next(action.choices for action in cli.build_client_parser()._actions
                        if isinstance(action, argparse._SubParsersAction))
        owner_commands = {"save", "show", "read", "open", "release", "status", "retire"}
        self.assertEqual(set(commands), {"help", "ask", "wait"} | owner_commands)
        self.assertLessEqual(owner_commands, OWNER_PORTFOLIO_COMMANDS)
        help_text = cli.build_client_parser().format_help()
        for name in ("admit", "complete-task", "onboarding", "vision", "direction"):
            self.assertNotIn(name, commands)
            self.assertNotIn("    " + name + " ", help_text)

    def test_installed_help_is_local_without_a_portfolio(self):
        output = StringIO()
        with redirect_stdout(output):
            code = cli.client_main(["help"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["outcome"], "read")
        self.assertNotIn("admit", result["commands"])
        self.assertNotIn("complete-task", result["commands"])

    def test_guarded_effects_still_fail_at_parser_and_owner_authority(self):
        for command in ("admit", "complete-task"):
            with self.subTest(command=command):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    cli.build_client_parser().parse_args([command])
                request = {"command": "portfolio-operation", "args": {
                    "command": "portfolio", "sub": None,
                    "args": {"portfolio": "p", "portfolio_args": [command]},
                }}
                with self.assertRaises(PermissionError):
                    OwnerService._owner_command(object(), "owner", request, "token", Path("."))

    def test_operator_portfolio_admit_still_reaches_owner_refusal(self):
        request = argparse.Namespace(portfolio_args=["--portfolio", "p", "admit", "--task-ref", "{}"])
        prepare_portfolio_request(request)
        self.assertEqual(request.portfolio, "p")
        self.assertEqual(request.portfolio_args[0], "admit")

    def test_installed_parser_has_no_always_denied_admit_route(self):
        commands = next(action.choices for action in cli.build_parser()._actions
                        if isinstance(action, argparse._SubParsersAction))
        self.assertNotIn("admit", commands)
        self.assertIn("complete-task", commands)
        self.assertNotIn("complete-task", OWNER_PORTFOLIO_COMMANDS)

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
