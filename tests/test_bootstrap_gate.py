"""Scratch-repo tests for ops/bootstrap: the land.sh gate and run-task.sh --route.

Everything runs on temporary repos through the scripts' environment overrides; the heavy
launcher and `claude` are stubs. OTTO_BOOTSTRAP_DIR points the tests at another copy of the
scripts (used to show the tests failing against the old ones).
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOT = Path(os.environ.get("OTTO_BOOTSTRAP_DIR") or ROOT / "ops" / "bootstrap")

GOOD_TEST = "from otto import mod\n\n\ndef test_f():\n    assert mod.f() == 1\n"
BOUNDARY = "def test_boundary():\n    assert True\n"


def sh(cmd, cwd=None, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if check and r.returncode:
        raise AssertionError("%s failed:\n%s%s" % (cmd, r.stdout, r.stderr))
    return r


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootgate-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.labs, self.ops = self.tmp / "otto", self.tmp / "labs", self.tmp / "ops"
        self.remote, self.baseline = self.tmp / "remote.git", self.tmp / "baseline"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.ops.mkdir()
        heavy = self.bin / "otto-heavy"
        heavy.write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
        heavy.chmod(0o755)
        self.env = dict(
            os.environ, OTTO_REPO=str(self.repo), LABS_DIR=str(self.labs), OPS_DIR=str(self.ops),
            OTTO_HEAVY=str(heavy), BASELINE_LAB=str(self.baseline), OTTO_PYTHON=sys.executable,
            OTTO_REMOTE="github", PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
        )
        sh(["git", "init", "-q", "-b", "canon/main", str(self.repo)])
        sh(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)])
        self.write(self.repo, "src/otto/__init__.py", "")
        self.write(self.repo, "src/otto/mod.py", "def f():\n    return 1\n")
        self.write(self.repo, "src/herzchen/__init__.py", "")
        self.write(self.repo, "tests/test_herzchen_boundary.py", BOUNDARY)
        self.write(self.repo, "tests/test_mod.py", GOOD_TEST)
        self.commit(self.repo, "base")
        sh(["git", "remote", "add", "github", str(self.remote)], cwd=self.repo)
        sh(["git", "push", "-q", "github", "canon/main:main"], cwd=self.repo, env=self.env)

    @staticmethod
    def write(root, rel, text):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, where, msg):
        sh(["git", "add", "-A"], cwd=where, env=self.env)
        sh(["git", "commit", "-q", "-m", msg], cwd=where, env=self.env)

    def head(self, ref="canon/main"):
        return sh(["git", "rev-parse", ref], cwd=self.repo).stdout.strip()

    def lab(self, task, files, brief_extra="", deleted=()):
        """Create a lab, write FILES ({rel: text}) and commit them, and write a brief."""
        sh(["bash", str(BOOT / "otto-lab.sh"), "create", task], env=self.env)
        lab = self.labs / task
        for rel, text in files.items():
            self.write(lab, rel, text)
        self.commit(lab, "work")
        (lab / ".brief.md").write_text("**Title:** Do %s\nCheck command: `true`\n%s\n" % (task, brief_extra))
        return lab

    def land(self, task, *args):
        r = sh(["bash", str(BOOT / "land.sh"), task, *args], env=self.env, check=False)
        # Every exit path ends with one LAND RESULT line that matches the exit code.
        lines = r.stdout.strip().splitlines()
        expected = {0: "landed", 4: "d19"}.get(r.returncode, "refused")
        self.assertTrue(lines and lines[-1].startswith("LAND RESULT: " + expected), r.stdout + r.stderr)
        if r.returncode == 0:
            self.assertIn("tested commit ", self.log(task))
        return r

    def log(self, task):
        return (self.ops / "runs" / task / "land.log").read_text()

    def assertRefused(self, r, task, text=""):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.head(), self.base, "canon/main moved")
        self.assertTrue((self.labs / task).exists())
        if text:
            self.assertIn(text, self.log(task) + r.stdout + r.stderr)

    @property
    def base(self):
        return self._base

    def start(self):
        self._base = self.head()


class LandGate(Scratch):
    def setUp(self):
        super().setUp()
        self.start()

    def test_passing_task_lands(self):
        self.lab("T1", {"src/otto/mod.py": "def f():\n    return 1\n\n\ndef g():\n    return 2\n",
                        "tests/test_mod.py": GOOD_TEST + "\n\ndef test_g():\n    assert mod.g() == 2\n"})
        r = self.land("T1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        parents = sh(["git", "rev-list", "--parents", "-1", "canon/main"], cwd=self.repo).stdout.split()
        self.assertEqual(len(parents), 3, "merged with --no-ff")
        self.assertEqual(self.head(), self.head("github/main"))
        self.assertEqual(sh(["git", "--git-dir", str(self.remote), "rev-parse", "main"]).stdout.strip(), self.head())
        self.assertFalse((self.labs / "T1").exists())
        self.assertEqual(sh(["git", "branch", "--list", "lab/T1"], cwd=self.repo).stdout.strip(), "")
        log = self.log("T1")
        for f in ("tests/test_mod.py", "tests/test_herzchen_boundary.py"):
            for n in (1, 2):
                self.assertIn("sweep %s run %d/2" % (f, n), log)
        self.assertFalse((self.ops / "land.lock").exists())
        self.assertIn("staging: skipped", log)
        self.assertIn("lines removed", log)

    def test_a_landing_stopped_by_a_signal_never_reports_landed(self):
        started = self.tmp / "check-started"
        check = "%s -c \"open('%s','w').close(); import time; time.sleep(600)\"" % (sys.executable, started)
        self.lab("T10", {"note.txt": "x\n"})
        proc = subprocess.Popen(["bash", str(BOOT / "land.sh"), "T10", "--check", check], env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        while not started.exists() and proc.poll() is None:  # wait for the check to start; only a hang fails
            pass
        if proc.poll() is not None:
            self.fail("land.sh ended before its check ran:\n" + "".join(proc.communicate()))
        os.killpg(proc.pid, signal.SIGTERM)
        out, err = proc.communicate()
        self.assertNotEqual(proc.returncode, 0, out + err)
        self.assertTrue(out.strip().splitlines()[-1].startswith("LAND RESULT: refused interrupted"), out + err)
        self.assertEqual(self.head(), self.base, "canon/main moved")
        self.assertFalse((self.ops / "land.lock").exists(), "the lock outlived the stopped landing")

    def test_a_failing_check_is_refused(self):
        self.lab("T11", {"note.txt": "x\n"})
        r = self.land("T11", "--check", "false")
        self.assertRefused(r, "T11", "the task's check failed: false")

    def test_new_failure_is_refused(self):
        self.lab("T2", {"src/otto/mod.py": "def f():\n    return 2\n"})
        r = self.land("T2")
        self.assertRefused(r, "T2", "NEW failure: tests/test_mod.py::test_f")

    def test_failure_also_on_base_is_pre_existing(self):
        self.write(self.repo, "tests/test_mod.py", GOOD_TEST + "\n\ndef test_bad():\n    assert False\n")
        self.commit(self.repo, "known failure")
        self.start()
        self.lab("T3", {"src/otto/mod.py": "def f():\n    return 1\n\n\ndef h():\n    return 3\n"})
        r = self.land("T3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pre-existing failure (also on BASE): tests/test_mod.py::test_bad", self.log("T3"))
        self.assertTrue(list((self.ops / ".baseline" / self.base).rglob("test_mod.py.txt")))

    def flaky_file(self, fail_on):
        """A test file whose Nth run in each tree (a counter per tree, kept outside it) fails when N is in
        fail_on[tree name]; the lab's tree is named after the task, BASE's is 'baseline'."""
        return ("import pathlib\nfrom otto import mod\n\nFAIL = %r\nP = pathlib.Path(%r) / ('count-' + "
                "pathlib.Path(__file__).resolve().parents[1].name)\n\n\ndef test_flaky():\n"
                "    n = int(P.read_text()) if P.exists() else 0\n    P.write_text(str(n + 1))\n"
                "    assert n not in FAIL.get(P.name[6:], ())\n" % (fail_on, str(self.tmp)))

    def flaky_lab(self, task, fail_on):
        self.write(self.repo, "tests/test_flaky.py", self.flaky_file(fail_on))
        self.commit(self.repo, "flaky test")
        self.start()
        self.lab(task, {"src/otto/mod.py": "def f():\n    return 1\n\n\ndef g():\n    return 2\n"})

    def test_a_flaky_failure_is_listed_not_refused(self):
        self.flaky_lab("T20", {"T20": {0}})
        r = self.land("T20")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("flaky, not reproduced: tests/test_flaky.py::test_flaky (lab 0/3, base 0/3", self.log("T20"))
        self.assertIn(" T20 tests/test_flaky.py::test_flaky lab 0/3 base 0/3", (self.ops / "flaky.txt").read_text())

    def test_a_failure_that_reproduces_alone_is_refused(self):
        self.flaky_lab("T21", {"T21": set(range(100))})
        self.assertRefused(self.land("T21"), "T21", "reproduced 3/3 alone, BASE 0/3")
        self.assertFalse((self.ops / "flaky.txt").exists())

    def test_a_failure_flaky_on_base_too_is_not_refused(self):
        # base run 0 is the cached baseline (passes); the BASE re-runs are runs 1-3, and run 1 fails
        self.flaky_lab("T22", {"T22": {0, 2, 3}, "baseline": {1}})
        r = self.land("T22")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("flaky on BASE too: tests/test_flaky.py::test_flaky (lab 2/3, base 1/3", self.log("T22"))
        self.assertIn(" T22 tests/test_flaky.py::test_flaky lab 2/3 base 1/3", (self.ops / "flaky.txt").read_text())

    def test_d19_exits_before_the_sweep(self):
        self.lab("T23", {"tests/test_mod.py": GOOD_TEST.replace("== 1", "!= 2")})
        self.assertEqual(self.land("T23").returncode, 4)
        self.assertNotIn("sweep", self.log("T23"))
        self.assertNotIn("check passed", self.log("T23"))

    def test_failing_output_is_kept(self):
        self.lab("T24", {"src/otto/mod.py": "def f():\n    return 2\n"})
        self.assertRefused(self.land("T24"), "T24")
        kept = self.ops / "runs" / "T24" / ".gate" / "fail-test_mod.py-run1.txt"
        self.assertIn("assert 2 == 1", kept.read_text())
        self.assertIn(str(kept), self.log("T24"))

    def test_changed_assertion_exits_4_then_d19_decides(self):
        changed = {"tests/test_mod.py": GOOD_TEST.replace("== 1", "!= 2")}
        self.lab("T4", changed)
        r = self.land("T4")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("D19: existing test expectations changed in tests/test_mod.py;", r.stderr)
        self.assertIn("ops/reviews/D19-T4.brief.md", r.stderr)
        self.assertEqual(self.head(), self.base)
        (self.tmp / "no.md").write_text("Review\nSEND BACK: too loose\n")
        self.assertRefused(self.land("T4", "--d19", str(self.tmp / "no.md")), "T4", "SEND BACK")
        (self.tmp / "yes.md").write_text("Review\nDecision: LAND\n")
        r = self.land("T4", "--d19", str(self.tmp / "yes.md"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(self.head(), self.base)

    def test_setup_line_change_does_not_trigger_d19(self):
        self.lab("T5", {"tests/test_mod.py": GOOD_TEST.replace("from otto import mod", "from otto import mod  # ok")})
        r = self.land("T5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_herzchen_layer_with_only_otto_code_is_refused(self):
        self.lab("T6", {"src/otto/extra.py": "X = 1\n"}, "**Layer:** Herzchen fleet (PLAN.md D14). Goes in src/herzchen.")
        self.assertRefused(self.land("T6"), "T6", "D14")

    def test_otto_layer_that_mentions_herzchen_is_not_refused(self):
        # EVWIRE and LANEFIX, 16 Oct: "Otto composition … nothing in src/herzchen" was read as a Herzchen layer.
        self.lab("T6B", {"src/otto/extra.py": "X = 1\n"}, "**Layer:** Otto composition (PLAN.md D14). Nothing in `src/herzchen`.")
        r = self.land("T6B")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("D14", self.log("T6B").split("placement:")[-1].split("\n", 1)[1])

    def test_staging_runs_the_tested_commits_scripts(self):
        # The step ran nothing after PERCH landed (-x on 100644 files). Now it runs the lab's own scripts.
        stub = "#!/bin/bash\necho \"$(basename \"$0\") $* $OTTO_COMMIT\" >> \"$OPS_DIR/staging-calls.txt\"\n"
        self.lab("T8", {"src/otto/extra.py": "X = 1\n", "ops/bootstrap/staging.sh": stub, "ops/bootstrap/perch.sh": stub})
        r = self.land("T8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = (self.ops / "staging-calls.txt").read_text().splitlines()
        self.assertEqual([c.split()[:2] for c in calls], [["staging.sh", "restart"], ["perch.sh", "all"]])
        self.assertIn("staging: restart and perch --fake passed", self.log("T8"))

    def test_missing_layer_only_logs(self):
        self.lab("T7", {"src/otto/extra.py": "X = 1\n"})
        r = self.land("T7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Layer: none", self.log("T7"))

    def test_remote_ahead_is_refused_before_merge(self):
        other = self.tmp / "other"
        sh(["git", "clone", "-q", str(self.remote), str(other)], env=self.env)
        self.write(other, "README", "x")
        self.commit(other, "remote only")
        sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=other, env=self.env)
        self.lab("T8", {"src/otto/extra.py": "X = 1\n"})
        self.assertRefused(self.land("T8"), "T8", "reconcile first")

    def test_added_regression_test_passing_on_base_warns(self):
        self.lab("T9", {"tests/test_new.py": "def test_ok():\n    assert True\n"})
        r = self.land("T9")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARN: tests/test_new.py passes on canon/main", self.log("T9"))


class RunTaskRoute(Scratch):
    def run_route(self, route, resume=False):
        task = "R" + route
        self.lab(task, {"note.txt": "x\n"})
        argv = self.tmp / ("argv-" + route)
        stub = self.bin / "claude"
        stub.write_text('#!/bin/sh\nprintf "%%s\\n" "$@" > "%s.tmp"\nmv "%s.tmp" "%s"\n' % (argv, argv, argv))
        stub.chmod(0o755)
        args = ["bash", str(BOOT / "run-task.sh"), task, "--route", route, "--wall-seconds", "5"]
        if resume:
            msg = self.tmp / "msg.md"
            msg.write_text("go on\n")
            args += ["--resume", "11111111-1111-1111-1111-111111111111", "--message", str(msg)]
        r = sh(args, env=self.env, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        while not argv.exists():  # the stub writes it when claude starts; only a hang fails
            pass
        return argv.read_text().split("\n")

    def check_xhard(self, argv):
        i = argv.index("--agents")
        self.assertIn('"haiku-worker"', argv[i + 1])
        tools = argv[argv.index("--allowedTools") + 1].split()
        self.assertEqual(tools[0], "Agent")

    def test_xhard_fresh(self):
        self.check_xhard(self.run_route("xhard"))

    def test_xhard_resume(self):
        self.check_xhard(self.run_route("xhard", resume=True))

    def test_normal_has_neither(self):
        argv = self.run_route("normal")
        self.assertNotIn("--agents", argv)
        self.assertNotIn("Agent", argv[argv.index("--allowedTools") + 1].split())

    def test_workers_cannot_schedule_themselves(self):
        for route in ("normal", "xhard"):
            argv = self.run_route(route)
            denied = argv[argv.index("--disallowedTools") + 1].split()
            self.assertIn("ScheduleWakeup", denied)
            self.assertIn("CronCreate", denied)
            self.assertIn("Monitor", denied)


class WorkersWait(unittest.TestCase):
    """workers.py wait returns on each thing the manager must act on, and says which."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootwait-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inbox = self.tmp / "requests.md"
        self.inbox.write_text("## Orchestrator old\nolder text\n## Manager ask\n")
        self.ledger = self.tmp / "workers.json"
        self.worker = subprocess.Popen(["sleep", "600"])
        self.addCleanup(self.stop_worker)
        self.ledger.write_text('[{"task": "T1", "pid": %d}]\n' % self.worker.pid)

    def stop_worker(self):
        if self.worker.poll() is None:
            self.worker.kill()
        self.worker.wait()

    def start(self, *extra):
        proc = subprocess.Popen([sys.executable, "-I", str(BOOT / "workers.py"), "wait", "--file", str(self.ledger),
                                 "--inbox", str(self.inbox), "--poll", "0.05", *extra],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIn("waiting on", proc.stderr.readline())  # armed; only a hang fails
        return proc

    def test_new_orchestrator_section_wakes_it(self):
        proc = self.start()
        with self.inbox.open("a") as f:
            f.write("## Manager another ask\n## Orchestrator 19:40Z: do X\n")
        out, _ = proc.communicate()
        self.assertEqual(out.strip(), "orchestrator: ## Orchestrator 19:40Z: do X")

    def test_worker_exit_wakes_it(self):
        proc = self.start()
        self.stop_worker()
        out, _ = proc.communicate()
        self.assertEqual(out.strip(), "worker exited: T1 (pid %d)" % self.worker.pid)

    def test_landing_result_wakes_it(self):
        land = self.tmp / "land.out"
        land.write_text("gate: sweeping\n")
        proc = self.start("--land-out", str(land))
        with land.open("a") as f:
            f.write("LAND RESULT: landed abc123\n")
        out, _ = proc.communicate()
        self.assertEqual(out.strip(), "landing finished: %s: LAND RESULT: landed abc123" % land)

    def test_with_nothing_running_it_waits_on_the_inbox(self):
        self.stop_worker()
        proc = self.start()
        with self.inbox.open("a") as f:
            f.write("## Orchestrator 04:40Z: disk is back\n")
        out, _ = proc.communicate()
        self.assertIn("waiting on the inbox only", out)
        self.assertIn("orchestrator: ## Orchestrator 04:40Z: disk is back", out)


if __name__ == "__main__":
    unittest.main()
