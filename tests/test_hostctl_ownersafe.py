"""A client can never stop the shared owner (15 Oct 2026: a forwarded `--help` closed it)."""
import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from otto.hostctl import lanes
from otto.hostctl.portfolio import prepare_portfolio_request
from otto.hostctl.cli import _await
from otto.hostctl.service import OwnerService


def config(home):
    return {"home": str(home), "max_active_manager_turns": 3, "owner": {"actor": "owner"},
            "store": {"authority": "test", "domain_descriptor_digest": "digest"}, "hosts": {}}


class OwnerSafeTests(unittest.TestCase):
    def test_closed_owner_fails_client_fast_with_closure_and_restart_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            lane = lanes.private_dir(Path(directory) / "client-lane")
            lanes.atomic_json(lane / lanes.STATUS_FILE, {
                "state": "closed", "service_home": "/srv/otto",
                "holder": {"owner_actor": "Ada"},
                "closure": {"reason": "planned upgrade", "expected_return": "10 minutes"},
            })
            result = _await(lane, {"command": "whoami"}, 10, owner_actor="Ada")
            self.assertEqual(result["outcome"], "unavailable")
            self.assertEqual(result["service_status"]["closure"]["reason"], "planned upgrade")
            self.assertIn("planned upgrade", result["error"]["message"])
            self.assertIn("ottoctl --home", result["next_action"])

    def test_help_in_lane_request_never_stops_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory), poll_seconds=0)
            lanes.private_dir(Path(directory) / "run")  # where the owner publishes its status
            lane = lanes.private_dir(Path(directory) / "lane")
            token = lanes.submit(lane, {"command": "portfolio", "args": {
                "portfolio_args": ["onboarding", "create", "--help"]}})
            def handler(who, request, token, lane):
                raise SystemExit(0)  # what argparse does on --help
            service._poll(lane, "claude-code", handler)  # must return, not raise
            reply = lanes.read_private_json(lane / ("response-" + token + ".json"))
            self.assertEqual(reply["outcome"], "error")
            self.assertEqual(reply["error"]["code"], "SystemExit")

    def test_keyboard_interrupt_still_stops_the_operator_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OwnerService(config(directory), poll_seconds=0)
            lanes.private_dir(Path(directory) / "run")  # where the owner publishes its status
            lane = lanes.private_dir(Path(directory) / "lane")
            lanes.submit(lane, {"command": "whoami", "args": {}})
            def handler(who, request, token, lane):
                raise KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                service._poll(lane, "owner", handler)

    def test_forwarded_portfolio_help_is_answered_client_side(self):
        args = argparse.Namespace(portfolio_args=["onboarding", "create", "--help"])
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as raised:
            prepare_portfolio_request(args)
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--template", out.getvalue())

    def test_forwarded_portfolio_usage_error_is_caught_client_side(self):
        args = argparse.Namespace(portfolio_args=["onboarding", "create", "--title", "x"])  # --actor etc. missing
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            prepare_portfolio_request(args)
        self.assertEqual(raised.exception.code, 2)

    def test_valid_forwarded_command_passes_client_validation(self):
        args = argparse.Namespace(portfolio_args=["onboarding", "find", "--actor", "a", "--project-ref", "{}"])
        prepare_portfolio_request(args)  # no exit: forwarded as before


if __name__ == "__main__":
    unittest.main()
