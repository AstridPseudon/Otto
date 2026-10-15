"""Staging Otto: ops/bootstrap/staging.sh started through the product CLI, from canon's own code.

What is proven: staging.sh checks out a commit (here the lab's HEAD, through OTTO_STAGING_REF) into
<tmp>/_staging/tree, creates an installation on an EMPTY Store under <tmp>/_staging, and starts
`ottoctl service run` from that tree's own src. The real OwnerService reports ready and stays
inert: no project attached, no Due started (dues_started 0), no provider called. Restart after a
SIGKILL, a clean stop with no leftover process, the tree moving to the pinned ref, wipe and the
live-folder refusal are checked on the same temporary folders.

Isolation: every test runs with OTTO_STAGING_ROOT, OTTO_REPO (the lab, read-only here), LABS_DIR
and HOME pointed into a temp folder named "stage-*"; the ottoctl wrapper always passes --home. The
only file outside the temp folder that is read is the live owner's lane status, read-only, and only
to assert that the staging authority and owner differ from it (skipped when absent).

What is not proven: that a project can be registered, activated or attached; that a host can be
admitted; that any agent CLI or model provider works; that the live owner's Store, sockets or
services are unaffected by anything but the read-only check; that a ref other than the lab's HEAD
starts. Tests that need new product code must be committed first: they run the committed HEAD.
"""
import json
import os
import pwd
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "ops" / "bootstrap" / "staging.sh"
PY = "/opt/homebrew/bin/python3.11"
AUTHORITY = "otto-staging-owner-v1"


def stats(*args):
    r = subprocess.run(["ps", "-o", "stat=", *args], capture_output=True, text=True)
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def alive(pid):
    # A zombie has exited and is only waiting to be reaped.
    return any(not s.startswith("Z") for s in stats("-p", str(pid)))


def group_has_members(pgid):
    return any(not s.startswith("Z") for s in stats("-g", str(pgid)))


def wait_until(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


class StagingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stage-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "_staging"
        self.tree = self.root / "tree"
        self.home = self.root / "home"
        self.store_dir = self.root / "store"
        self.store_file = self.store_dir / "staging.store"
        self.run = self.root / "run"
        self.pidfile = self.run / "staging.pid"
        self.log = self.run / "staging.log"
        self.staged = self.run / "staging.json"
        self.sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
                                  capture_output=True, check=True).stdout.strip()
        self.env = dict(
            os.environ, LABS_DIR=str(self.tmp / "labs"), OTTO_STAGING_ROOT=str(self.root),
            OTTO_REPO=str(ROOT), OTTO_PYTHON=PY, OTTO_STAGING_REF=self.sha,
            OTTO_STAGING_READY_SECONDS="60", OTTO_STAGING_STOP_SECONDS="30",
            HOME=str(self.tmp / "home"),
        )
        for name in ("OTTO_STAGING_ENTRY", "PYTHONPATH", "OTTO_HOME", "OTTO_HOST_KIND",
                     "OTTO_MANAGER_IPC", "OTTO_CALLER_SOCKET"):
            self.env.pop(name, None)
        self.started = set()
        # Cleanups run last-in first-out: teardown stops anything still running before rmtree removes the folder.
        self.addCleanup(self._teardown)

    def _teardown(self):
        r = self.stage("down")
        survivors = [pgid for pgid in self.started if group_has_members(pgid)]
        self.assertEqual(survivors, [], "process groups survived teardown")
        self.assertEqual(r.returncode, 0, "teardown down failed: " + r.stderr + r.stdout)

    def stage(self, verb, env=None):
        run_env = dict(self.env, **(env or {}))
        return subprocess.run(["bash", str(STAGING), verb], env=run_env, text=True,
                              capture_output=True, timeout=300)

    def pid(self):
        pid = int(self.pidfile.read_text().split()[0])
        self.started.add(pid)
        return pid

    def status_json(self):
        return json.loads(self.staged.read_text())

    def service_status(self):
        return json.loads((self.home / "run" / "service.json").read_text())

    def log_text(self):
        return self.log.read_text() if self.log.exists() else ""

    def diag(self, r):
        return r.stdout + r.stderr + self.log_text()[-3000:]

    def assert_nothing_left(self, pid):
        self.assertFalse(alive(pid), "staging process %d still alive" % pid)
        self.assertFalse(group_has_members(pid), "process group %d still has members" % pid)
        self.assertFalse(self.pidfile.exists(), "pidfile left behind")
        self.assertFalse(self.staged.exists(), "staging.json left behind")

    # Startup: the product entry point on an empty Store.

    def test_startup_on_empty_store(self):
        self.assertFalse(self.store_file.exists(), "a Store exists before the first start")
        r = self.stage("up")
        self.assertEqual(r.returncode, 0, self.diag(r))
        self.assertTrue(r.stdout.splitlines()[-1].startswith("up: pid "), r.stdout)
        self.assertIn("sha " + self.sha, r.stdout)
        pid = self.pid()
        self.assertTrue(alive(pid))
        status = self.status_json()
        self.assertEqual(status["sha"], self.sha)
        self.assertTrue(self.store_file.exists(), "the first start did not create the Store")
        self.assertTrue((self.home / "installation.json").exists())
        svc = self.service_status()
        self.assertEqual(svc["state"], "serving")
        self.assertEqual(svc["attached_projects"], [])
        self.assertFalse(svc["provider_called"])
        self.assertIn('"outcome": "ready"', self.log_text())
        self.assertIn('"dues_started": 0', self.log_text())

    def test_restart_after_kill_recovers(self):
        self.assertEqual(self.stage("up").returncode, 0)
        first = self.pid()
        generation = self.service_status()["generation"]
        os.killpg(first, signal.SIGKILL)
        self.assertTrue(wait_until(lambda: not group_has_members(first)), "killed group still has members")
        r = self.stage("up")
        self.assertEqual(r.returncode, 0, self.diag(r))
        second = self.pid()
        self.assertNotEqual(second, first)
        self.assertTrue(alive(second))
        svc = self.service_status()
        self.assertEqual(svc["state"], "serving")
        self.assertEqual(svc["generation"], generation + 1)
        self.assertEqual(self.stage("down").returncode, 0)

    def test_no_leftovers_after_stop(self):
        self.assertEqual(self.stage("up").returncode, 0)
        pid = self.pid()
        r = self.stage("down")
        self.assertEqual(r.returncode, 0, self.diag(r))
        self.assertFalse(alive(pid), "staging process %d still alive" % pid)
        self.assertFalse(group_has_members(pid), "process group %d still has members" % pid)
        self.assertFalse(self.pidfile.exists(), "pidfile left behind")
        self.assertFalse(self.staged.exists(), "staging.json left behind")
        self.assertEqual(self.service_status()["state"], "closed")

    def test_restart_moves_tree_to_ref(self):
        self.assertEqual(self.stage("up").returncode, 0)
        first = self.pid()
        r = self.stage("restart")
        self.assertEqual(r.returncode, 0, self.diag(r))
        second = self.pid()
        self.assertNotEqual(second, first)
        self.assertTrue(alive(second))
        self.assertFalse(alive(first), "restart left the previous process running")
        self.assertEqual(self.status_json()["sha"], self.sha)
        head = subprocess.run(["git", "-C", str(self.tree), "rev-parse", "HEAD"], text=True,
                              capture_output=True, check=True).stdout.strip()
        self.assertEqual(head, self.sha)
        self.assertEqual(self.stage("down").returncode, 0)

    def test_wipe_refused_while_running_then_empties(self):
        self.assertEqual(self.stage("up").returncode, 0)
        self.pid()
        r = self.stage("wipe")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(self.store_file.exists(), "wipe ran while the staging Otto was up")
        self.assertEqual(self.stage("down").returncode, 0)
        r = self.stage("wipe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.home.exists(), "wipe left the staging home")
        self.assertFalse(self.store_dir.exists(), "wipe left the staging Store")
        r = self.stage("up")
        self.assertEqual(r.returncode, 0, self.diag(r))
        self.assertTrue(self.store_file.exists(), "the next up did not create a fresh Store")
        self.assertEqual(self.stage("down").returncode, 0)

    # Isolation: the staging paths are inside the temp folder and differ from the live owner's.

    def test_staging_paths_differ_from_live(self):
        self.assertEqual(self.stage("up").returncode, 0)
        self.pid()
        status = self.status_json()
        live_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        live_dirs = [live_home / ".otto", live_home / ".codex", live_home / "Documents" / "Codex",
                     live_home / ".otto-clients"]
        for key in ("home", "store", "owner_lane", "status", "stop_file"):
            path = Path(status[key]).resolve()
            self.assertTrue(path.is_relative_to(self.tmp), "%s is outside the temp folder: %s" % (key, path))
            for live in live_dirs:
                self.assertFalse(path == live or live in path.parents,
                                 "%s is under the live folder %s" % (key, live))
        lane = live_home / ".otto-clients" / "claude-code" / "lanes" / "claude-code" / "status.json"
        if lane.exists():
            data = json.loads(lane.read_text())
            self.assertNotEqual((data.get("store") or {}).get("authority"), AUTHORITY)
            self.assertNotEqual((data.get("holder") or {}).get("owner_actor"), "otto-staging-owner")
        self.assertEqual(self.stage("down").returncode, 0)

    # Refusals and the shape of the script.

    def test_refuses_live_folders_without_writing(self):
        live = self.tmp / "home" / ".otto" / "staging"
        r = self.stage("up", env={"OTTO_STAGING_ROOT": str(live)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused: staging root", r.stderr)
        self.assertFalse(live.parent.exists(), "the refused root's parent was created")
        self.assertFalse(live.exists(), "the refused root was created")

    def test_no_live_path_in_script(self):
        text = STAGING.read_text()
        code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        code_text = "\n".join(code)
        self.assertNotIn("OTTO_HOME=", code_text, "OTTO_HOME is assigned in the script")
        self.assertNotIn("OTTO_STAGING_ENTRY", text)
        self.assertNotIn("shared_operating_service", text)
        start = text.index("ottoctl() {")
        body = text[start:text.index("\n}\n", start)]
        self.assertIn('--home "$HOME_DIR"', body, "the ottoctl wrapper does not pass --home")
        self.assertIn("-u OTTO_HOME", body, "the ottoctl wrapper does not clear OTTO_HOME")
        calls = [line for line in code if re.search(r"\bottoctl (install|service)\b", line)]
        self.assertGreaterEqual(len(calls), 3, "expected install, service run and service stop calls")
        for line in calls:
            self.assertNotIn("--home", line, "a call passes its own --home: " + line.strip())
        self.assertEqual(code_text.count("from otto.hostctl.cli import main"), 1,
                         "the product CLI is started somewhere other than the ottoctl wrapper")


if __name__ == "__main__":
    unittest.main()
