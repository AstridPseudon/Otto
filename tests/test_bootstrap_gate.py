"""Scratch-repo tests for ops/bootstrap: the land.sh gate and run-task.sh --route.

Everything runs on temporary repos through the scripts' environment overrides; the heavy
launcher and `claude` are stubs. OTTO_BOOTSTRAP_DIR points the tests at another copy of the
scripts (used to show the tests failing against the old ones).
"""
import json
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

    def test_staging_runs_the_tested_commit(self):
        # STAGE0 F1: the gate passed OTTO_COMMIT, which nothing reads, so staging ran BASE. The stub perch
        # writes a report naming the sha it was given, as the real one does.
        perch = ("#!/bin/bash\nd=\"$PERCH_OUT/0/x\"; mkdir -p \"$d\"\n"
                 "echo \"- staging tree sha $OTTO_STAGING_REF; canon/main x\" > \"$d/report.md\"\n"
                 "echo \"perch: stage 0 report at $d/report.md\"\n")
        self.lab("T8", {"src/otto/extra.py": "X = 1\n", "ops/bootstrap/staging.sh": "", "ops/bootstrap/perch.sh": perch})
        sha = sh(["git", "rev-parse", "HEAD"], cwd=self.labs / "T8").stdout.strip()
        r = self.land("T8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("staging: perch --fake passed on", self.log("T8"))
        report = (self.repo / "ops/perch/0/x/report.md").read_text()  # kept in the main checkout, not the lab
        self.assertIn("staging tree sha " + sha[:7], report)

    def test_staging_on_another_commit_is_refused(self):
        perch = ("#!/bin/bash\nd=\"$PERCH_OUT/0/y\"; mkdir -p \"$d\"\n"
                 "echo \"- staging tree sha 0000000; canon/main x\" > \"$d/report.md\"\n"
                 "echo \"perch: stage 0 report at $d/report.md\"\n")
        self.lab("T8B", {"src/otto/extra.py": "X = 1\n", "ops/bootstrap/staging.sh": "", "ops/bootstrap/perch.sh": perch})
        self.assertRefused(self.land("T8B"), "T8B", "did not run the tested commit")

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


    def test_sweep_counts_the_checks_run_of_a_named_file(self):
        self.lab("T10", {"tests/test_named.py": "def test_ok():\n    assert True\n"},
                 brief_extra="")
        lab = self.labs / "T10"
        (lab / ".brief.md").write_text("**Title:** Do T10\nCheck command: `%s -m pytest -q tests/test_named.py`\n" % sys.executable)
        r = self.land("T10")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.log("T10")
        self.assertIn("sweep tests/test_named.py run 1/2: 0 failing (the check's run)", log)
        self.assertIn("sweep tests/test_named.py run 2/2", log)


class RunTaskCodex(Scratch):
    """--host codex: Luna or Sol in Codex's workspace-write sandbox; codex names the session; the
    launcher commits what the worker leaves, because the sandbox keeps .git read-only."""

    def run_codex(self, route, resume=None):
        task = "C" + route
        if resume is None:
            self.lab(task, {"note.txt": "x\n"})
        argv = self.tmp / ("codex-argv-" + route + ("-resume" if resume else ""))
        stub = self.bin / "codex"
        stub.write_text(
            '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s.tmp"\n'
            'echo \'{"type":"thread.started","thread_id":"thread-%s"}\'\n'
            'echo \'{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":4,"output_tokens":3}}\'\n'
            'echo made > made-by-worker.txt\nmv "%s.tmp" "%s"\n' % (argv, route, argv, argv))
        stub.chmod(0o755)
        args = ["bash", str(BOOT / "run-task.sh"), task, "--route", route, "--host", "codex", "--wall-seconds", "30"]
        if resume:
            msg = self.tmp / "msg.md"
            msg.write_text("go on\n")
            args += ["--resume", resume, "--message", str(msg)]
        r = sh(args, env=self.env, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lab = self.labs / task
        while sh(["git", "log", "-1", "--format=%s"], cwd=lab, env=self.env).stdout.strip().find("worker's changes") < 0:
            pass  # the launcher commits once the stub exits; only a hang fails
        return task, lab, argv.read_text().split("\n"), r.stdout

    def test_models_and_sandbox_by_route(self):
        for route, model, effort in (("normal", "gpt-6-luna", "high"), ("xhard", "gpt-6-sol", "xhigh")):
            _, _, argv, _ = self.run_codex(route)
            self.assertEqual(argv[:2], ["exec", "-m"])
            self.assertEqual(argv[2], model)
            self.assertIn('model_reasoning_effort="%s"' % effort, argv)
            self.assertIn('sandbox_mode="workspace-write"', argv)
            self.assertIn("sandbox_workspace_write.network_access=true", argv)  # Unix sockets need it
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
            self.assertTrue(any(a.startswith("sandbox_workspace_write.writable_roots=") for a in argv))

    def test_session_named_by_codex_and_work_committed(self):
        task, lab, _, out = self.run_codex("normal")
        self.assertIn("session thread-normal", out)
        ledger = json.loads((self.ops / "workers.json").read_text())
        self.assertEqual([e["session_id"] for e in ledger if e["task"] == task], ["thread-normal"])
        tracked = sh(["git", "ls-files"], cwd=lab, env=self.env).stdout.split()
        self.assertIn("made-by-worker.txt", tracked)
        self.assertNotIn(".brief.md", tracked)
        self.assertTrue((self.ops / "runs" / task / "worker.jsonl").exists())

    def test_resume_continues_the_session(self):
        task, _, _, _ = self.run_codex("normal")
        _, _, argv, _ = self.run_codex("normal", resume="thread-normal")
        self.assertEqual(argv[:2], ["exec", "resume"])
        self.assertEqual([a for a in argv if a][-2:], ["thread-normal", "-"])
        self.assertTrue((self.ops / "runs" / task / "worker.1.jsonl").exists())

    def test_commit_when_the_lab_ignores_the_brief(self):
        # Real labs ignore .brief.md; naming it in `git add` made git refuse the whole add (16 Oct).
        task = "Cignored"
        lab = self.lab(task, {".gitignore": ".brief.md\n", "note.txt": "x\n"})
        stub = self.bin / "codex"
        stub.write_text('#!/bin/sh\necho \'{"type":"thread.started","thread_id":"t-ign"}\'\necho made > made.txt\n')
        stub.chmod(0o755)
        r = sh(["bash", str(BOOT / "run-task.sh"), task, "--host", "codex", "--wall-seconds", "30"], env=self.env, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        while "made.txt" not in sh(["git", "ls-files"], cwd=lab, env=self.env).stdout.split():
            pass  # only a hang fails
        self.assertNotIn(".brief.md", sh(["git", "ls-files"], cwd=lab, env=self.env).stdout.split())

    def test_launch_holds_no_pipe_of_the_caller(self):
        # The manager loop read run-task.sh's output through a pipe; a detached worker that kept it open
        # blocked the loop until the worker ended (16 Oct). Here the worker blocks until released.
        task = "Cpipe"
        self.lab(task, {"note.txt": "x\n"})
        release = self.tmp / "release"
        stub = self.bin / "codex"
        stub.write_text('#!/bin/sh\necho \'{"type":"thread.started","thread_id":"t-pipe"}\'\n'
                        'while [ ! -e "%s" ] && [ -d "%s" ]; do sleep 0.2; done\n' % (release, self.tmp))
        stub.chmod(0o755)
        try:
            r = subprocess.run(["bash", str(BOOT / "run-task.sh"), task, "--host", "codex", "--wall-seconds", "60"],
                               env=self.env, capture_output=True, text=True)  # hangs here if a pipe is held
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            release.write_text("go")

    def test_program_default_host_file(self):
        (self.ops / "worker-host").write_text("codex\n")
        task = "Cdefault"
        self.lab(task, {"note.txt": "x\n"})
        stub = self.bin / "codex"
        stub.write_text('#!/bin/sh\necho \'{"type":"thread.started","thread_id":"t-default"}\'\n')
        stub.chmod(0o755)
        r = sh(["bash", str(BOOT / "run-task.sh"), task, "--wall-seconds", "30"], env=self.env, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("gpt-6-luna", r.stdout)


class GateExitPlugin(unittest.TestCase):
    """otto_gate_exit: a run that leaked a non-daemon thread still ends when pytest has reported,
    with pytest's status, and names the thread (16 Oct: a 53-minute hang after a 91 s run)."""

    def test_leaked_thread_does_not_hold_the_run(self):
        tmp = Path(tempfile.mkdtemp(prefix="gateexit-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "test_leak.py").write_text(textwrap.dedent("""
            import threading
            def test_leaks_and_fails():
                threading.Thread(target=threading.Event().wait, name="leaked-waiter").start()
                assert False
        """))
        env = dict(os.environ, PYTHONPATH=str(BOOT), PYTEST_ADDOPTS="-p otto_gate_exit")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_leak.py"],
                           cwd=tmp, env=env, capture_output=True, text=True)  # a hang here is the failure
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("leaked-waiter", r.stderr)
        self.assertIn("1 failed", r.stdout)


class WorkersSpend(unittest.TestCase):
    def test_claude_last_file_and_codex_tokens(self):
        runs = Path(tempfile.mkdtemp(prefix="spend-"))
        self.addCleanup(shutil.rmtree, runs, True)
        (runs / "A").mkdir()
        (runs / "A" / "worker.json").write_text(json.dumps({"total_cost_usd": 1.0}))
        (runs / "A" / "worker.1.json").write_text(json.dumps({"total_cost_usd": 2.5}))  # running total
        (runs / "B").mkdir()
        for name in ("worker.jsonl", "worker.1.jsonl"):
            (runs / "B" / name).write_text('{"type":"turn.completed","usage":{"input_tokens":10,'
                                            '"cached_input_tokens":4,"output_tokens":3}}\n')
        r = subprocess.run([sys.executable, "-I", str(BOOT / "workers.py"), "spend", "--runs", str(runs)],
                           capture_output=True, text=True, check=True)
        self.assertIn("$2.5000", r.stdout.split("total (claude)")[1])
        self.assertIn("in 20 (cached 8), out 6", r.stdout)


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
