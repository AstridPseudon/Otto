"""Owner lane for the portfolio command: only save, show and read reach the owner.

The lane tests run a real owner service over real lanes (HostctlFixture). A forged
client request for admit or complete-task is refused with PermissionError and
writes nothing; show and read travel through the owner lane as save does; and the
owner's project-history projection is caught up before it serves.
"""
import argparse
import json
import tempfile
from pathlib import Path

from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import WorkGraph, contributions
from herzchen.kernel.store import Store
from otto.hostctl import config as host_config, lanes
from otto.hostctl.owner import HostSession
from otto.hostctl.portfolio import prepare_portfolio_request
from otto.hostctl.service import owner_lane
from test_hostctl_cli import HostctlFixture

PORTFOLIO = "claude-code-portfolio"
OWNER = "otto-test-owner"


class OwnerLaneTests(HostctlFixture):
    def setUp(self):
        super().setUp()
        self._init()
        self._register()

    def _owner(self, callback):
        def run():
            config = host_config.load(Path(self.home))
            with HostSession(config, host=config["hosts"]["claude-code"]) as session:
                return callback(session)
        return self.owner_service.call(run)

    def _store_state(self):
        return self._owner(lambda session: tuple(session.store.connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(append_position), 0) FROM events").fetchone()))

    def _owner_request(self, portfolio_args):
        """A request sent straight to the owner lane, as a forged client would send it."""
        body = {"schema": lanes.REQUEST_SCHEMA, "command": "portfolio", "sub": None,
                "args": {"portfolio": PORTFOLIO, "portfolio_args": list(portfolio_args)}}
        lane = owner_lane(Path(self.home))
        token = lanes.submit(lane, {"command": "portfolio-operation", "args": body})
        return lanes.wait(lane, token, timeout_seconds=10)

    def test_admit_and_complete_task_are_refused_through_the_owner_lane_and_write_nothing(self):
        before = self._store_state()
        for portfolio_args in (["admit", "--task-ref", "{}", "--actor", OWNER],
                               ["complete-task", "--input-json", "{}"]):
            refused = self._owner_request(portfolio_args)
            self.assertEqual(refused["outcome"], "error", refused)
            self.assertEqual(refused["error"]["code"], "PermissionError", refused)
        self.assertEqual(self._store_state(), before)

    def test_show_through_the_owner_lane_returns_saved_tasks(self):
        save_file = Path(self.bundle).parent / "lane-plan.json"
        save_file.write_text(json.dumps({"project": {"title": "Lane plan", "outcome": "One route"},
                                         "tasks": [{"id": "t1", "title": "Plan t1", "instructions": "Do t1",
                                                    "acceptance": "Done t1"}]}))
        code, saved = self._ottoctl("portfolio", "--portfolio", PORTFOLIO, "save", str(save_file), "--actor", OWNER)
        self.assertEqual(code, 0, saved)
        code, shown = self._ottoctl("portfolio", "--portfolio", PORTFOLIO, "show", "project",
                                    "--project-ref", json.dumps(saved["project_ref"]), "--actor", OWNER)
        self.assertEqual(code, 0, shown)
        self.assertIn("Plan t1", json.dumps(shown))

    def test_read_with_the_portfolio_flag_in_front_reaches_the_owner(self):
        code, read = self._ottoctl("portfolio", "--portfolio", PORTFOLIO, "read", "no-such-project", "--actor", OWNER)
        self.assertNotEqual(read.get("error", {}).get("code"), "usage", read)

    def test_the_project_operations_stay_reachable_from_the_owner_lane(self):
        code, read = self._ottoctl("project", "dependencies", "--project", "demo-run", "--portfolio", PORTFOLIO)
        self.assertEqual(code, 0, read)
        self.assertNotEqual(read.get("error", {}).get("code"), "PermissionError", read)


class PortfolioForwardingTests(HostctlFixture):
    def test_show_and_read_forward_with_the_portfolio_named_once(self):
        for command in (["show", "project", "--project-ref", "{}", "--actor", OWNER], ["read", "demo", "--actor", OWNER]):
            args = argparse.Namespace(portfolio_args=["--portfolio", PORTFOLIO, *command])
            prepare_portfolio_request(args)
            self.assertEqual(args.portfolio, PORTFOLIO)
            self.assertEqual(args.portfolio_args, command)

    def test_show_and_read_accept_the_equals_form(self):
        args = argparse.Namespace(portfolio_args=["--portfolio=" + PORTFOLIO, "read", "demo", "--actor", OWNER])
        prepare_portfolio_request(args)
        self.assertEqual((args.portfolio, args.portfolio_args), (PORTFOLIO, ["read", "demo", "--actor", OWNER]))


class HistoryProjectionAtStartTests(HostctlFixture):
    def test_history_checkpoint_equals_the_last_append_position_at_rest(self):
        from otto.hostctl.product_service import start_history_projection
        with tempfile.TemporaryDirectory(prefix="owner-lane-history-") as directory:
            store = Store.create(Path(directory) / "events.sqlite", authority="owner")
            try:
                store.register_domain_handler(contributions(include_assignment_resources=True))
                graph = WorkGraph(store, actor=AuthenticatedActor("owner", "reader", "credential"))
                graph.create_project(title="History", logical_request_key="history-1")
                graph.create_project(title="History two", logical_request_key="history-2")
                start_history_projection(store)
                status = store.project_history_projection().status()
                self.assertTrue(status["covered"], status)
                self.assertGreater(status["checkpoint"], 0)
                self.assertEqual(status["checkpoint"], status["source_append_boundary"])
            finally:
                store.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
