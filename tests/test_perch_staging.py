"""PERCH0FIX: staging.sh's status, its recovery after a KILL, and its record of a refused start.

Each test starts the staging Otto from the lab's committed HEAD (OTTO_STAGING_REF), in a temporary staging root
that is never labs/_staging, and stops it again. They use the product's own status and the Store, not perch's.
"""
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "ops" / "bootstrap" / "staging.sh"
PY = "/opt/homebrew/bin/python3.11"


class StagingRootTests(unittest.TestCase):
    def setUp(self):
        # A short root under /tmp: under $TMPDIR the owner's socket path passes the 100-byte Unix limit
        # and staging refuses to start (as tests/test_staging_startup.py already does).
        self.tmp = Path(tempfile.mkdtemp(prefix="ps-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stage = self.tmp / "_staging"
        self.sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
                                  capture_output=True, check=True).stdout.strip()

    def stop_owner(self):
        pidfile = self.stage / "run" / "staging.pid"
        if not pidfile.exists():
            return
        pid = int(pidfile.read_text(encoding="utf-8").split()[0])
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail("staging process group %d survived SIGKILL" % pid)

    def start_staging(self):
        return self.staging("up")

    def assert_injected_exit_is_clean(self, error):
        r = self.start_staging()
        self.assertEqual(r.returncode, 0, r.log)
        pid = self.staging_pid()
        try:
            raise error
        except (AssertionError, subprocess.TimeoutExpired):
            self.doCleanups()
        with self.assertRaises(ProcessLookupError):
            os.killpg(pid, 0)
        self.assertFalse(self.tmp.exists(), "temporary root remained after owner exit")

    def staging(self, *args):
        if args and args[0] == "up":
            # Register before every start so failures and timeouts stop the process group.
            self.addCleanup(self.stop_owner)
        env = dict(
            os.environ, OTTO_STAGING_ROOT=str(self.stage), OTTO_REPO=str(ROOT), OTTO_PYTHON=PY,
            OTTO_STAGING_REF=self.sha, OTTO_STAGING_READY_SECONDS="60", OTTO_STAGING_STOP_SECONDS="30",
            LABS_DIR=str(self.tmp / "labs"), HOME=str(self.tmp / "home"),
        )
        for name in ("PYTHONPATH", "OTTO_HOME", "OTTO_HOST_KIND", "OTTO_MANAGER_IPC", "OTTO_CALLER_SOCKET"):
            env.pop(name, None)
        # Output goes to a file, not a pipe: a background process the start leaves behind must not hold the test.
        out = self.tmp / ("staging-%d.log" % len(list(self.tmp.glob("staging-*.log"))))
        with open(out, "w", encoding="utf-8") as handle:
            r = subprocess.run(["bash", str(STAGING), *args], env=env, stdin=subprocess.DEVNULL,
                               stdout=handle, stderr=subprocess.STDOUT, timeout=300)
        r.log = out.read_text(encoding="utf-8")
        return r

    def status(self):
        r = self.staging("status")
        self.assertEqual(r.returncode, 0, r.log)
        return json.loads(r.log)

    def staging_pid(self):
        return json.loads((self.stage / "run" / "staging.json").read_text(encoding="utf-8"))["pid"]

    def kill_group(self, pid):
        """SIGKILL the staging Otto's process group (its pgid is its pid), then wait until the leader is gone."""
        os.killpg(pid, signal.SIGKILL)
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.2)
        self.fail("the killed staging Otto (pid %d) is still there" % pid)

    def store_snapshot(self):
        """Row counts and integrity of the Store, opened read-only."""
        store = (self.stage / "store" / "staging.store").resolve()
        con = sqlite3.connect(store.as_uri() + "?mode=ro", uri=True)
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            rows = {name: con.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0] for name in names}
        finally:
            con.close()
        return integrity, rows


class StatusTests(StagingRootTests):
    def test_cleanup_after_forced_mid_test_failure(self):
        self.assert_injected_exit_is_clean(AssertionError("forced mid-test failure"))

    def test_cleanup_after_timeout(self):
        self.assert_injected_exit_is_clean(subprocess.TimeoutExpired("forced timeout", 0.01))

    def test_status_after_kill_is_stale(self):
        self.assertEqual(self.staging("up").returncode, 0)
        running = self.status()
        self.assertEqual(running["outcome"], "running")
        self.assertTrue(running["holder_alive"])
        self.kill_group(self.staging_pid())
        killed = self.status()
        # The file still says "serving"; the product's reading must not.
        self.assertEqual(killed["outcome"], "stale", killed)
        self.assertFalse(killed["holder_alive"], killed)


class RefusedStartTests(StagingRootTests):
    def test_refused_start_names_its_reason(self):
        self.assertEqual(self.staging("up").returncode, 0)
        pidfile = self.stage / "run" / "staging.pid"
        saved = pidfile.read_text(encoding="utf-8")
        pidfile.unlink()  # the wrapper no longer knows the running owner, so a second start is attempted
        try:
            r = self.staging("up")
        finally:
            pidfile.write_text(saved, encoding="utf-8")
        self.assertNotEqual(r.returncode, 0, r.log)
        record = json.loads((self.stage / "run" / "staging.refused.json").read_text(encoding="utf-8"))
        self.assertEqual(record["exit_code"], 3, record)
        self.assertEqual(record["error"]["code"], "owner_service_running", record)
        self.assertIn("owner_service_running", r.log)
        # The first owner is still the one serving.
        self.assertEqual(self.status()["outcome"], "running")


class RestartAfterKillTests(StagingRootTests):
    def test_restart_after_kill_keeps_store(self):
        self.assertEqual(self.staging("up").returncode, 0)
        generation = self.status()["generation"]
        integrity, rows = self.store_snapshot()
        self.assertEqual(integrity, "ok")
        self.kill_group(self.staging_pid())
        r = self.staging("up")
        self.assertEqual(r.returncode, 0, r.log)
        restarted = self.status()
        self.assertEqual(restarted["outcome"], "running", restarted)
        self.assertEqual(restarted["generation"], generation + 1, restarted)
        integrity_after, rows_after = self.store_snapshot()
        self.assertEqual(integrity_after, "ok")
        self.assertEqual(rows_after, rows)


if __name__ == "__main__":
    unittest.main()
