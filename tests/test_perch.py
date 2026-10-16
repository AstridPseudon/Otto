"""PERCH: the assertions over a run's raw data fail on each seeded fault, the report renders, and a fake run is green.

The assertion kinds are checked on a clean raw folder (every one passes) and then with one seeded fault
each (only that assertion fails). The end-to-end test runs ops/bootstrap/perch.sh in a temp staging root,
with the lab's committed HEAD as the commit under test; it starts a real staging Otto and stops it.
"""
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "ops" / "bootstrap"
PERCH = BOOTSTRAP / "perch.sh"
PY = "/opt/homebrew/bin/python3.11"

spec = importlib.util.spec_from_file_location("perch_report", BOOTSTRAP / "perch_report.py")
perch_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perch_report)

NAMES = ("staging-ready", "no-leaked-process", "timeline-events", "labs-left-behind", "harness-pool-within-limit",
         "store-matches-stage", "staging-at-rest-clean", "status-while-up", "status-after-kill-is-stale",
         "restart-after-kill-keeps-store", "status-after-stop", "refused-start-names-its-reason")
LIFECYCLE = NAMES[-5:]


def clean_raw(root):
    """A raw folder for a green run: two canary tasks, one landed and one refused, with every event they need."""
    raw = Path(root)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "config.json").write_text(json.dumps({
        "stage": "0", "fake": True, "check": "check", "pool_limit": 1, "faults": [], "staging_restart": 0,
        "store": {"store_events": 0, "store_tasks": 0, "store_bytes_max": 262144},
        "staging_sha": "a" * 40, "canon_main_sha": "b" * 40, "started_at": "2026-10-16T10:00:00Z",
        "finished_at": "2026-10-16T10:05:00Z",
        "tasks": [{"name": "canary-add-sub", "expect": "landed"}, {"name": "canary-refused", "expect": "refused"}],
    }), encoding="utf-8")
    rows = [
        ("10:00:01", "canary-add-sub", "lab-created", "canon/main abc"),
        ("10:00:03", "canary-add-sub", "check-passed", "rc 0"),
        ("10:00:04", "canary-add-sub", "landed", "def"),
        ("10:00:05", "canary-add-sub", "lab-deleted", ""),
        ("10:01:01", "canary-refused", "lab-created", "canon/main def"),
        ("10:01:03", "canary-refused", "check-failed", "rc 1"),
        ("10:01:04", "canary-refused", "refused", "check rc 1"),
        ("10:01:05", "canary-refused", "lab-deleted", ""),
    ]
    (raw / "events.tsv").write_text("".join("2026-10-16T%sZ\t%s\t%s\t%s\n" % r for r in rows), encoding="utf-8")
    for task in ("canary-add-sub", "canary-refused"):
        turns = 2 if task == "canary-add-sub" else 1
        lines = [{"at": "2026-10-16T10:00:02Z", "kind": "turn", "task": task, "turn": 1, "sha": "c1"}]
        if turns == 2:
            lines.append({"at": "2026-10-16T10:00:02Z", "kind": "turn", "task": task, "turn": 2, "sha": "c2"})
        lines.append({"at": "2026-10-16T10:00:02Z", "kind": "done", "task": task, "turns": turns})
        (raw / ("worker-%s.jsonl" % task)).write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    (raw / "census.before.txt").write_text("", encoding="utf-8")
    (raw / "census.after.txt").write_text("", encoding="utf-8")
    (raw / "leftovers.txt").write_text("", encoding="utf-8")
    (raw / "started.tsv").write_text("", encoding="utf-8")
    (raw / "durations.tsv").write_text("worker\tcanary-add-sub\t2026-10-16T10:00:01Z\t2\n", encoding="utf-8")
    (raw / "samples.jsonl").write_text("".join(json.dumps({
        "at": "2026-10-16T10:00:0%dZ" % i, "disk_free_kb": 1000, "swap": "total = 0M", "pool_units": units,
        "store_bytes": 4096, "staging_state": "serving", "staging_generation": 1,
    }) + "\n" for i, units in enumerate([0, 1, 1])), encoding="utf-8")
    (raw / "timeline.json").write_text(json.dumps({"store_events": 0, "tasks": [], "error": None}), encoding="utf-8")
    for name in ("report-product.txt", "report-canary.txt"):
        (raw / name).write_text("landed on canon/main:\n  abc 2026-10-16 Land canary-add-sub\n", encoding="utf-8")
    # The staging-lifecycle scenario ran: a status while up, a KILL, a restart, a refused second start, a stop.
    store = {"error": None, "bytes": 139264, "page_size": 4096, "page_count": 34, "freelist_count": 0,
             "integrity": "ok", "rows": {"identities": 16, "store_metadata": 11}}
    for name, value in {
        "staging-up.json": {"pid": 4242, "sha": "a" * 40},
        "installation.json": {"store": {"authority": "otto-staging-owner-v1"}},
        "status-up.json": {"outcome": "running", "holder": {"pid": 4242}, "holder_alive": True, "generation": 1,
                           "store": {"authority": "otto-staging-owner-v1"}},
        "status-killed.json": {"outcome": "stale", "holder_alive": False, "generation": 1, "holder": {"pid": 4242}},
        "status-restarted.json": {"outcome": "running", "holder_alive": True, "generation": 2, "holder": {"pid": 4343}},
        "status-stopped.json": {"outcome": "closed", "generation": 2},
        "store-before-kill.json": store, "store-restarted.json": dict(store), "store-at-rest.json": dict(store),
        "refused.json": {"exit_code": 3, "at": "2026-10-16T10:02:00Z", "error": {"code": "owner_service_running"},
                         "entry": {"outcome": "unavailable", "error": {"code": "owner_service_running"}}, "log_tail": []},
        "at-rest.json": {"home_run": ["generation", "service-stop", "service.json"], "service_state": "closed",
                         "sockets": [], "store_holders": {"staging.store": [], "staging.store.fnd-owner.lock": []},
                         "perch_canary": [], "error": None},
    }.items():
        (raw / name).write_text(json.dumps(value), encoding="utf-8")
    (raw / "generation-up.txt").write_text("1\n", encoding="utf-8")
    (raw / "census.up.txt").write_text("4242 4242 0:03 /opt/homebrew/bin/python3.11 -c x --home /x/home\n", encoding="utf-8")
    (raw / "notes.json").write_text(json.dumps({"staging-lifecycle": "ran", "restart_after_kill_rc": 0,
                                                "refused_start_rc": 3}), encoding="utf-8")
    return raw


def statuses(raw):
    return {r["name"]: r["status"] for r in perch_report.assertions(Path(raw))}


def edit(raw, name, fn):
    path = Path(raw) / name
    path.write_text(fn(path.read_text(encoding="utf-8")), encoding="utf-8")


def patch(raw, name, fn):
    """Change one JSON observation of a run in place."""
    path = Path(raw) / name
    value = json.loads(path.read_text(encoding="utf-8"))
    fn(value)
    path.write_text(json.dumps(value), encoding="utf-8")


SEEDED_FAULTS = {
    "staging-ready": lambda raw: edit(raw, "config.json", lambda t: t.replace('"staging_restart": 0', '"staging_restart": 1')),
    "no-leaked-process": lambda raw: edit(
        raw, "census.after.txt", lambda t: t + "4242 4242 0:01 /opt/homebrew/bin/python3.11 -I /x/canary/fake_worker.py --lab /x/labs/t\n"),
    "timeline-events": lambda raw: edit(raw, "events.tsv", lambda t: "".join(
        line for line in t.splitlines(keepends=True) if "check-passed" not in line)),
    "labs-left-behind": lambda raw: edit(raw, "leftovers.txt", lambda t: t + "worktree /x/labs/canary-refused\n"),
    "harness-pool-within-limit": lambda raw: edit(raw, "samples.jsonl", lambda t: t.replace('"pool_units": 1', '"pool_units": 2')),
    "store-matches-stage": lambda raw: perch_report.seed(raw, "store"),
    "staging-at-rest-clean": lambda raw: patch(raw, "at-rest.json", lambda v: v["home_run"].append("c-leftover.sock")),
    "status-while-up": lambda raw: perch_report.seed(raw, "census"),
    "status-after-kill-is-stale": lambda raw: patch(raw, "status-killed.json", lambda v: v.update(outcome="serving", holder_alive=True)),
    "restart-after-kill-keeps-store": lambda raw: perch_report.seed(raw, "restart"),
    "status-after-stop": lambda raw: patch(raw, "status-stopped.json", lambda v: v.update(outcome="running")),
    "refused-start-names-its-reason": lambda raw: (Path(raw) / "refused.json").unlink(),
}


class AssertionKindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perch-raw-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_clean_run_passes_every_assertion(self):
        raw = clean_raw(self.tmp / "raw")
        self.assertEqual(statuses(raw), {name: "pass" for name in NAMES})
        self.assertEqual(perch_report.cmd_check(Namespace(raw=str(raw))), 0)
        self.assertTrue((raw / "assertions.json").exists())

    def test_each_kind_fails_on_its_seeded_fault_and_only_that(self):
        self.assertEqual(set(SEEDED_FAULTS), set(NAMES), "every assertion kind needs a seeded fault")
        for name in NAMES:
            with self.subTest(fault=name):
                raw = clean_raw(self.tmp / ("raw-" + name))
                SEEDED_FAULTS[name](raw)
                got = statuses(raw)
                self.assertEqual(got[name], "fail", got)
                self.assertEqual({k for k, v in got.items() if v == "fail"}, {name}, got)

    def test_a_missing_timeline_event_names_the_task_and_event(self):
        raw = clean_raw(self.tmp / "raw")
        SEEDED_FAULTS["timeline-events"](raw)
        detail = {r["name"]: r["detail"] for r in perch_report.assertions(raw)}["timeline-events"]
        self.assertIn("canary-add-sub missing check-passed", detail)

    def test_a_store_gap_fails_the_timeline_assertion(self):
        raw = clean_raw(self.tmp / "raw")
        (raw / "timeline.json").write_text(json.dumps({"store_events": 3, "error": None, "tasks": [{
            "task_id": "t1", "complete": False, "gaps": [["assignment:t1", 1, 1]], "events": []}]}), encoding="utf-8")
        self.assertEqual(statuses(raw)["timeline-events"], "fail")

    def test_a_failed_check_is_a_red_run_exit(self):
        raw = clean_raw(self.tmp / "raw")
        SEEDED_FAULTS["labs-left-behind"](raw)
        self.assertEqual(perch_report.cmd_check(Namespace(raw=str(raw))), 1)

    def test_store_matches_stage(self):
        raw = clean_raw(self.tmp / "raw")
        self.assertEqual(statuses(raw)["store-matches-stage"], "pass")
        cases = [
            ("an event the stage does not expect", "timeline.json", lambda v: v.update(store_events=1)),
            ("a task the stage does not expect", "timeline.json",
             lambda v: v.update(tasks=[{"task_id": "t1", "complete": True, "gaps": [], "events": []}])),
            ("a Store that could not be read", "timeline.json", lambda v: v.update(error="file is not a database")),
            ("a Store over the stage's size limit", "store-at-rest.json", lambda v: v.update(bytes=300000)),
            ("a stage that states no Store contents", "config.json", lambda v: v.pop("store")),
        ]
        for i, (label, name, fn) in enumerate(cases):
            with self.subTest(label):
                raw = clean_raw(self.tmp / ("store-%d" % i))
                patch(raw, name, fn)
                self.assertEqual(statuses(raw)["store-matches-stage"], "fail")

    def test_staging_at_rest_clean(self):
        raw = clean_raw(self.tmp / "raw")
        self.assertEqual(statuses(raw)["staging-at-rest-clean"], "pass")
        cases = [
            ("a file down does not leave", lambda v: v["home_run"].append("stop-marker.tmp")),
            ("a socket", lambda v: v["sockets"].append("/x/home/run/c-1.sock")),
            ("a Store holder", lambda v: v["store_holders"].update({"staging.store": ["4242"]})),
            ("a service still serving", lambda v: v.update(service_state="serving")),
            ("canary scratch", lambda v: v["perch_canary"].append("stage-0-1")),
        ]
        for i, (label, fn) in enumerate(cases):
            with self.subTest(label):
                raw = clean_raw(self.tmp / ("rest-%d" % i))
                patch(raw, "at-rest.json", fn)
                self.assertEqual(statuses(raw)["staging-at-rest-clean"], "fail")
        raw = clean_raw(self.tmp / "rest-missing")
        (raw / "at-rest.json").unlink()
        self.assertEqual(statuses(raw)["staging-at-rest-clean"], "fail", "an unchecked root must not pass")

    def test_a_lifecycle_that_did_not_run_is_skipped_and_says_why(self):
        raw = clean_raw(self.tmp / "raw")
        (raw / "notes.json").write_text(json.dumps({"staging-lifecycle": "skipped: staging did not start"}), encoding="utf-8")
        got = {r["name"]: r for r in perch_report.assertions(raw)}
        for name in LIFECYCLE:
            self.assertEqual(got[name]["status"], "skip", name)
            self.assertIn("staging did not start", got[name]["detail"])
        self.assertEqual(perch_report.cmd_check(Namespace(raw=str(raw))), 0, "a skipped check is not a red run")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perch-render-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_report_has_every_section_the_stage_review_reads(self):
        raw = clean_raw(self.tmp / "raw")
        perch_report.cmd_check(Namespace(raw=str(raw)))
        out = self.tmp / "report.md"
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(out)))
        text = out.read_text(encoding="utf-8")
        for heading in ("## Assertions", "## Task timelines", "## Process census", "## Labs and scratch left over",
                        "## Pool units over time", "## Store growth", "## Git history", "## Tokens and cost per task",
                        "## Waits and durations"):
            self.assertIn(heading, text)
        self.assertIn("### canary-add-sub (expect landed)", text)
        self.assertIn("| 2026-10-16T10:00:03Z | perch | check-passed | rc 0 |", text)
        self.assertIn("Land canary-add-sub", text)

    def test_the_census_names_a_leak_in_the_report(self):
        raw = clean_raw(self.tmp / "raw")
        SEEDED_FAULTS["no-leaked-process"](raw)
        out = self.tmp / "report.md"
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(out)))
        self.assertIn("fake_worker.py", out.read_text(encoding="utf-8"))


class StagingRootSnapshotTests(unittest.TestCase):
    """The Store at rest and the staging root after down, read from real files: a SQLite Store and a socket."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perch-rest-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_store_snapshot_counts_rows_and_checks_integrity(self):
        store = self.tmp / "staging.store"
        con = sqlite3.connect(store)
        con.execute("CREATE TABLE a (x INTEGER)")
        con.executemany("INSERT INTO a VALUES (?)", [(1,), (2,)])
        con.execute("CREATE TABLE b (y INTEGER)")
        con.commit()
        con.close()
        snap = perch_report.store_snapshot(str(store))
        self.assertIsNone(snap["error"])
        self.assertEqual(snap["integrity"], "ok")
        self.assertEqual(snap["rows"], {"a": 2, "b": 0})
        self.assertGreater(snap["bytes"], 0)

    def test_census_finds_a_process_by_its_stage_root(self):
        root = self.tmp / "scratch-stage-root"
        proc = subprocess.Popen([PY, "-c", "import time; time.sleep(60)", "--home", str(root)])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        found = self.tmp / "census.txt"
        perch_report.cmd_census(Namespace(out=str(found), stage_root=str(root)))
        self.assertIn(proc.pid, perch_report.pids_of(perch_report.read_lines(found)))
        perch_report.cmd_census(Namespace(out=str(found), stage_root=""))
        self.assertNotIn(proc.pid, perch_report.pids_of(perch_report.read_lines(found)),
                         "a root that is not given is not matched by its name")

    def test_store_snapshot_says_when_there_is_no_store(self):
        self.assertEqual(perch_report.store_snapshot(str(self.tmp / "none.store")), {"error": "no Store file"})

    def test_at_rest_names_what_down_left_behind(self):
        root = self.tmp / "_staging"
        (root / "home" / "run").mkdir(parents=True)
        (root / "home" / "run" / "service.json").write_text(json.dumps({"state": "closed"}), encoding="utf-8")
        (root / "home" / "run" / "generation").write_text("2\n", encoding="utf-8")
        (root / "store").mkdir()
        (root / "store" / "staging.store").write_text("", encoding="utf-8")
        (root / "tree").mkdir()
        sock = root / "home" / "run" / "c-1.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(str(sock))
        out = self.tmp / "at-rest.json"
        perch_report.cmd_at_rest(Namespace(stage_root=str(root), out=str(out)))
        rest = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rest["home_run"], ["c-1.sock", "generation", "service.json"])
        self.assertEqual(rest["service_state"], "closed")
        self.assertEqual(rest["sockets"], [str(sock)])
        self.assertEqual(rest["store_holders"], {"staging.store": []})
        self.assertEqual(rest["perch_canary"], [])
        self.assertIsNone(rest["error"])


class StoreTimelineSubcommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perch-store-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_missing_store_is_reported_not_invented(self):
        out = self.tmp / "timeline.json"
        perch_report.cmd_timeline(Namespace(src=str(ROOT / "src"), store=str(self.tmp / "none.store"),
                                            authority="owner", out=str(out)))
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["error"], "no Store file")
        self.assertEqual(data["tasks"], [])


def run_perch(tmp, sha, fault=""):
    """perch.sh 0 --fake in a temp folder, with the commit under test pinned to SHA. Returns (exit, log, report dir)."""
    env = dict(
        os.environ, OTTO_STAGING_ROOT=str(tmp / "_staging"), OTTO_REPO=str(ROOT), OTTO_PYTHON=PY,
        OTTO_STAGING_REF=sha, OTTO_STAGING_READY_SECONDS="60", OTTO_STAGING_STOP_SECONDS="30",
        PERCH_OUT=str(tmp / "perch"), LABS_DIR=str(tmp / "labs"), HOME=str(tmp / "home"), PERCH_FAULT=fault,
    )
    for name in ("PYTHONPATH", "OTTO_HOME", "OTTO_HOST_KIND", "OTTO_MANAGER_IPC", "OTTO_CALLER_SOCKET"):
        env.pop(name, None)
    # Output goes to a file, not a pipe: a background process the run leaves behind must not hold the test.
    log = tmp / "perch.log"
    with open(log, "w", encoding="utf-8") as out:
        try:
            r = subprocess.run(["bash", str(PERCH), "0", "--fake"], env=env, stdin=subprocess.DEVNULL, stdout=out,
                               stderr=subprocess.STDOUT, timeout=600)
        except subprocess.TimeoutExpired:
            return None, log.read_text(encoding="utf-8")[-4000:], None
    reports = list((tmp / "perch" / "0").glob("*/report.md"))
    return r.returncode, log.read_text(encoding="utf-8"), reports[0].parent if reports else None


def results_of(report_dir):
    return {a["name"]: a["status"] for a in json.loads((report_dir / "raw" / "assertions.json").read_text(encoding="utf-8"))}


class FakeRunTests(unittest.TestCase):
    """perch.sh 0 --fake in a temp staging root, with the lab's committed HEAD as the commit under test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perch-e2e-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
                                  capture_output=True, check=True).stdout.strip()

    def test_a_fake_run_is_green_and_writes_a_report(self):
        code, log, report_dir = run_perch(self.tmp, self.sha)
        self.assertIsNotNone(code, "perch.sh did not finish in 600 s; its log so far:\n" + log)
        restart_logs = list((self.tmp / "perch").glob("0/*/raw/staging-restart.log"))
        diag = restart_logs[0].read_text(encoding="utf-8")[-3000:] if restart_logs else "(no restart log)"
        self.assertEqual(code, 0, log + diag)
        self.assertIsNotNone(report_dir, log)
        self.assertTrue((report_dir / "report.md").exists())
        self.assertEqual(results_of(report_dir), {name: "pass" for name in NAMES})
        timeline = json.loads((report_dir / "raw" / "timeline.json").read_text(encoding="utf-8"))
        self.assertIsNone(timeline["error"])
        self.assertEqual(timeline["tasks"], [], "the fake run drives no product task")
        self.assertFalse((self.tmp / "_staging" / "perch-canary").exists() and
                         any((self.tmp / "_staging" / "perch-canary").iterdir()), "canary scratch left behind")


# The assertions each seeded fault turns red in a real run. A lab left behind also leaves its lab-deleted
# event unrecorded; a staging that never came up leaves no Store to read, and its lifecycle is skipped.
EXPECTED_RED = {
    "leak": {"no-leaked-process"},
    "lab": {"labs-left-behind", "timeline-events"},
    "pool": {"harness-pool-within-limit"},
    "timeline": {"timeline-events"},
    "staging": {"staging-ready", "timeline-events", "store-matches-stage"},
    "status": {"status-after-kill-is-stale"},
    "restart": {"restart-after-kill-keeps-store"},
    "refuse": {"refused-start-names-its-reason"},
    "store": {"store-matches-stage"},
    "atrest": {"staging-at-rest-clean"},
    "census": {"status-while-up"},
}


class SeededFaultRunTests(unittest.TestCase):
    """Each seeded fault, in a real run, turns exactly its assertion kind red and the report says so."""

    def test_each_seeded_fault_fails_its_assertion_kind(self):
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
                             capture_output=True, check=True).stdout.strip()
        for fault, red in EXPECTED_RED.items():
            with self.subTest(fault=fault):
                tmp = Path(tempfile.mkdtemp(prefix="perch-fault-")).resolve()
                self.addCleanup(shutil.rmtree, tmp, True)
                code, log, report_dir = run_perch(tmp, sha, fault)
                self.assertIsNotNone(code, "perch.sh did not finish in 600 s; its log so far:\n" + log)
                self.assertIsNotNone(report_dir, log)
                self.assertEqual(code, 1, log)
                got = results_of(report_dir)
                self.assertEqual({name for name, status in got.items() if status == "fail"}, red, got)
                self.assertIn("| fail |", (report_dir / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
