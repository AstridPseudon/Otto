"""Staging Otto: ops/bootstrap/staging.sh and the production startup.

Two groups. Both run on temporary folders only; OTTO_STAGING_ROOT, OTTO_REPO and HOME are
pointed into the test's temp dir, so no Store, socket or log can land under the live owner's
folders.

- test_startup_* and test_restart_after_kill_recovers / test_no_leftovers_after_stop drive
  staging.sh against the production entry point, install/controller/shared_operating_service.py.
  They fail until that entry point can be rooted at the staging folder; staging.sh refuses to
  start it until then. The test file never imports that module: its import reads the live tree.
- test_mechanics_* use a stub entry point (OTTO_STAGING_ENTRY) to check the verbs on their own:
  tree sync, process-group stop, stale socket recovery, wipe guards, live-folder refusal. They
  prove the lifecycle, not that the production service starts.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "ops" / "bootstrap" / "staging.sh"

STUB_ENTRY = '''\
import json, os, signal, socket, sys, time
sock_path = os.environ["OTTO_STAGING_SOCKET"]
os.makedirs(os.environ["OTTO_STAGING_STORE"], exist_ok=True)
srv = socket.socket(socket.AF_UNIX)
srv.bind(sock_path)
srv.listen(1)
def stop(*_):
    srv.close()
    os.unlink(sock_path)
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
print(json.dumps({"outcome": "ready", "pid": os.getpid(), "provider_called": False}), flush=True)
while True:
    time.sleep(0.1)
'''


def stats(*args):
    r = subprocess.run(["ps", "-o", "stat=", *args], capture_output=True, text=True)
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def alive(pid):
    # A zombie has exited and is only waiting to be reaped.
    return any(not s.startswith("Z") for s in stats("-p", str(pid)))


def group_has_members(pgid):
    return any(not s.startswith("Z") for s in stats("-g", str(pgid)))


class StagingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stage-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "otto"
        self.root = self.tmp / "_staging"
        self.store = self.root / "store"
        self.run = self.root / "run"
        self.pidfile = self.run / "staging.pid"
        self.sock = self.run / "otto.sock"
        self.env = dict(
            os.environ, OTTO_REPO=str(self.repo), LABS_DIR=str(self.tmp / "labs"),
            OTTO_STAGING_ROOT=str(self.root), OTTO_PYTHON=sys.executable,
            OTTO_STAGING_READY_SECONDS="30", HOME=str(self.tmp / "home"),
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
        )
        self.env.pop("OTTO_STAGING_ENTRY", None)
        self.git("init", "-q", "-b", "canon/main", str(self.repo))
        self.commit("base.txt", "base\n")
        self.stub = self.tmp / "stub_entry.py"
        self.stub.write_text(STUB_ENTRY)
        # Cleanups run last-in first-out: down stops anything still running before rmtree removes the folder.
        self.addCleanup(self.stage, "down")

    def git(self, *args):
        return subprocess.run(["git", *args], env=self.env, text=True, capture_output=True, check=True)

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        self.git("-C", str(self.repo), "add", name)
        self.git("-C", str(self.repo), "commit", "-q", "-m", name)

    def stage(self, verb, entry=None, env=None):
        run_env = dict(self.env, **(env or {}))
        if entry is not None:
            run_env["OTTO_STAGING_ENTRY"] = str(entry)
        return subprocess.run(["bash", str(STAGING), verb], env=run_env, text=True, capture_output=True)

    def pid(self):
        return int(self.pidfile.read_text().split()[0])

    def store_is_empty(self):
        return not self.store.exists() or not any(self.store.iterdir())

    def assert_nothing_left(self, pid):
        self.assertFalse(alive(pid), "staging process %d still alive" % pid)
        self.assertFalse(group_has_members(pid), "process group %d still has members" % pid)
        self.assertFalse(self.pidfile.exists(), "pidfile left behind")
        self.assertFalse(self.sock.exists(), "socket left behind")

    # Startup proof: the production entry point. Red until it can be rooted at the staging folder.

    def test_startup_on_empty_store(self):
        r = self.stage("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(alive(self.pid()))
        self.assertTrue(self.store_is_empty(), "staging Store is not empty on first start")
        self.assertIn('"outcome": "ready"', (self.run / "staging.log").read_text())

    def test_restart_after_kill_recovers(self):
        self.assertEqual(self.stage("up").returncode, 0)
        first = self.pid()
        os.killpg(first, signal.SIGKILL)
        r = self.stage("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(alive(self.pid()))
        self.assertNotEqual(self.pid(), first)

    def test_no_leftovers_after_stop(self):
        self.assertEqual(self.stage("up").returncode, 0)
        pid = self.pid()
        r = self.stage("down")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_nothing_left(pid)

    # Mechanics: the verbs with a stub entry point. These do not prove production startup.

    def test_mechanics_down_leaves_nothing_behind(self):
        self.assertEqual(self.stage("up", entry=self.stub).returncode, 0)
        pid = self.pid()
        self.assertEqual(self.stage("down").returncode, 0)
        self.assert_nothing_left(pid)

    def test_mechanics_restart_moves_tree_to_canon_head(self):
        self.assertEqual(self.stage("up", entry=self.stub).returncode, 0)
        self.assertEqual(self.stage("down").returncode, 0)
        self.commit("new.txt", "new\n")
        r = self.stage("restart", entry=self.stub)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "tree" / "new.txt").exists())
        head = self.git("-C", str(self.root / "tree"), "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head, self.git("-C", str(self.repo), "rev-parse", "canon/main").stdout.strip())
        self.assertEqual(self.stage("down").returncode, 0)

    def test_mechanics_kill_leaves_stale_socket_and_up_recovers(self):
        self.assertEqual(self.stage("up", entry=self.stub).returncode, 0)
        first = self.pid()
        os.killpg(first, signal.SIGKILL)
        self.assertTrue(self.sock.exists(), "a killed run should leave its socket behind")
        r = self.stage("up", entry=self.stub)
        self.assertEqual(r.returncode, 0, r.stderr)
        second = self.pid()
        self.assertNotEqual(second, first)
        self.assertTrue(alive(second))
        self.assertEqual(self.stage("down").returncode, 0)
        self.assert_nothing_left(second)

    def test_mechanics_wipe_only_when_stopped(self):
        self.assertEqual(self.stage("up", entry=self.stub).returncode, 0)
        (self.store / "marker").write_text("x")
        r = self.stage("wipe")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.store / "marker").exists(), "wipe ran while the staging Otto was up")
        self.assertEqual(self.stage("down").returncode, 0)
        r = self.stage("wipe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.store.is_dir())
        self.assertTrue(self.store_is_empty())

    def test_mechanics_refuses_live_folders_without_writing(self):
        live = self.tmp / "home" / ".codex" / "staging"
        r = self.stage("up", entry=self.stub, env={"OTTO_STAGING_ROOT": str(live)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused: staging root", r.stderr)
        self.assertFalse(live.exists())

    def test_up_refuses_production_entry_without_writing(self):
        r = self.stage("up")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("shared_operating_service.py", r.stderr)
        self.assertFalse(self.run.exists())
        self.assertFalse(self.pidfile.exists())


if __name__ == "__main__":
    unittest.main()
