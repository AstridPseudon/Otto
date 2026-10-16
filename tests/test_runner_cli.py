"""otto run verbs against a real runner daemon on a unix socket, plus the Claude env strip."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import threading
import unittest

from herzchen.fleet.capacity import CapacityPolicy, CapacityPool
from herzchen.fleet.runner import ResultStore, Runner, RunnerServer
from otto import runner_cli
from otto.agents.claude_cli import ClaudeCliTransport, LauncherPin, VERSION, file_digest


class RunnerCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir="/tmp", prefix="rcli-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock = os.path.join(self.tmp, "r.sock")
        self.submitted = []
        self.store = ResultStore(os.path.join(self.tmp, "store"))
        self.runner = Runner(CapacityPool(CapacityPolicy(heavy_headroom=3)), self.store,
                             state_dir=os.path.join(self.tmp, "state"), resolve_commit=lambda cwd: "c1")
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.server = RunnerServer(self.runner, self.sock)
        self.serving = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.serving.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.serving.join, 5)
        self.addCleanup(self.server.shutdown)

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = runner_cli.main(["--socket", self.sock, *args])
        return code, json.loads(out.getvalue().splitlines()[-1])

    def submit(self, *command):
        code, payload = self.cli("submit", "--", *command)
        self.assertEqual(code, 0, payload)
        self.submitted.append(payload["run_id"])
        return payload["run_id"]

    def test_submit_then_await_returns_exit_code_and_record(self):
        run_id = self.submit("/bin/sh", "-c", "exit 7")
        code, payload = self.cli("await", run_id)
        self.assertEqual(code, 7)
        self.assertTrue(payload["done"])
        self.assertEqual(payload["record"]["run_id"], run_id)
        self.assertEqual(payload["record"]["state"], "settled")
        self.assertEqual(payload["record"]["exit_code"], 7)

    def test_submit_wait_returns_command_exit_code(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = runner_cli.main(["--socket", self.sock, "submit", "--wait", "--", "/bin/sh", "-c", "exit 7"])
        self.assertEqual(code, 7)
        submitted, awaited = (json.loads(line) for line in out.getvalue().splitlines())
        self.assertTrue(submitted["ok"])
        self.assertEqual(awaited["record"]["run_id"], submitted["run_id"])

    def test_await_unknown_run_is_nonzero_with_unknown_run_error(self):
        code, payload = self.cli("await", "run-nope")
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "unknown_run")

    def test_status_and_report_exit_zero_and_count_submits(self):
        self.submit("/bin/sh", "-c", "exit 0")
        self.submit("/bin/sh", "-c", "exit 3")
        for run_id in self.submitted:
            self.assertTrue(self.cli("await", run_id)[1]["done"])
        code, status = self.cli("status")
        self.assertEqual(code, 0)
        self.assertTrue(status["ok"])
        code, report = self.cli("report")
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["totals"]["runs"], 2)

    def test_unreachable_socket_exits_69(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = runner_cli.main(["--socket", self.sock + ".absent", "status"])
        self.assertEqual(code, 69)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_await_timeout_exits_3_and_other_run_still_finishes(self):
        sleeper = self.submit("/bin/sh", "-c", "sleep 5")
        code, payload = self.cli("await", sleeper, "--timeout", "0.2")
        self.assertEqual(code, 3)
        self.assertFalse(payload["done"])
        quick = self.submit("/bin/sh", "-c", "exit 0")
        code, payload = self.cli("await", quick, "--timeout", "10")
        self.assertEqual(code, 0)
        self.assertEqual(payload["record"]["state"], "settled")


class ClaudeEnvironmentStripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="otto-rcli-env-")
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name).resolve())

    def transport(self, extra_env=None):
        executable = str(Path(sys.executable).resolve())
        pin = LauncherPin(executable, executable, file_digest(Path(executable)), VERSION)
        scope = SimpleNamespace(workspace=self.root, state_root=self.root)
        return ClaudeCliTransport(pin, scope, model="gpt-test", reasoning="high", extra_env=extra_env)

    def test_heavy_lease_and_dir_from_os_environ_are_not_passed(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"OTTO_HEAVY_LEASE": "lease-1", "OTTO_HEAVY_DIR": "/tmp/heavy"}):
            env = self.transport().environment()
        self.assertNotIn("OTTO_HEAVY_LEASE", env)
        self.assertNotIn("OTTO_HEAVY_DIR", env)

    def test_heavy_extra_env_is_dropped_and_other_otto_keys_pass_through(self):
        env = self.transport({"OTTO_HEAVY_X": "1", "OTTO_KEEP": "2"}).environment()
        self.assertNotIn("OTTO_HEAVY_X", env)
        self.assertEqual(env["OTTO_KEEP"], "2")


if __name__ == "__main__":
    unittest.main()
