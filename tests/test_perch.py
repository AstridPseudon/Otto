"""PERCH: the assertions over a run's raw data fail on each seeded fault, the report renders, and a fake run is green.

The assertion kinds are checked on a clean raw folder (every one passes) and then with one seeded fault
each (only that assertion fails). The end-to-end test runs ops/bootstrap/perch.sh in a temp staging root,
with the lab's committed HEAD as the commit under test; it starts a real staging Otto and stops it.
"""
import importlib.util
import contextlib
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch as mock_patch

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


def clean_stage2_raw(root):
    """Stubs for the staging reads that stage-2 assertions consume."""
    raw = Path(root)
    raw.mkdir(parents=True, exist_ok=True)
    tasks = ("A", "B", "C")
    task_refs = {name: {"authority": "owner", "kind": "work.task", "id": "task-" + name,
                        "revision": "rev-" + name} for name in tasks}
    review_ref = {"authority": "owner", "kind": "dat.content.document",
                  "id": "plan-review-document", "revision": "rev-review"}
    documents = [{"path": "reviews/plan-review.md", "revision_ref": review_ref,
                  "stored_text_sha256": hashlib.sha256(perch_report.STAGE2_REVIEW_TEXT.encode()).hexdigest()}]
    plan_tasks = [{"id": name, "fields": {"check": {"argv": ["/usr/bin/true"]}},
                   "metadata_namespace": {"otto.plan": {"repo": "toy", "branch": "canon/main", "route": "normal"}}}
                  for name in tasks]
    criteria = {name: {"authority": "owner", "kind": "assessment.criterion",
                       "id": "criterion-" + name, "revision": "rev-1"} for name in tasks}
    scopes = {name: {"task_ref": {**task_refs[name], "revision": "rev-admitted-" + name},
                     "scope_ref": {"authority": "owner", "kind": "assessment.scope",
                                   "id": "scope-" + name, "revision": "rev-1"},
                     "criterion_ref": criteria[name]} for name in tasks}
    values = {
        "config.json": {"stage": "2", "scenarios": ["admit-and-dispatch"], "staging_restart": 0,
                        "tasks": [], "pool_limit": 2, "manager_reserve": 1,
                        "stage2_tasks": list(tasks), "stage2_admitted": list(tasks),
                        "stage2_dependencies": {"A": [], "B": ["A"], "C": ["B"]},
                        "stage2_unadmitted_revision": {"task": "C", "revision": "rev-unadmitted", "admitted": False}},
        "notes.json": {"admit-and-dispatch": "ran"},
        "stage2-project-status.json": {"documents": documents},
        "stage2-plan-save.input.json": {"tasks": plan_tasks},
        "stage2-plan-save.json": {"outcome": "saved", "task_refs": task_refs},
        "stage2-activation.json": {"activation": {"steps": {"tasks": {"task_refs": task_refs}}},
                                   "bootstrap_assessment": {"policy_scope_ref": {
                                       "authority": "owner", "kind": "assessment.scope",
                                       "id": "policy-scope", "revision": "rev-1"},
                                       "criterion_refs": criteria}},
        "stage2-review-ref.json": review_ref,
        "stage2-observations.json": {
            "dispatch": {"dispatched": list(tasks), "records": [
                {"alias": name, "admitted": True, "ready": True} for name in tasks]},
            "unadmitted_refusal": {"outcome": "refused", "reason": "unadmitted_revision",
                                     "task": "C", "revision": "rev-unadmitted"},
            "capacity": {"pool_peak": 2, "manager_reserve_remaining": 1},
            "worker_kill": {"slot_released": True, "killed_worker_absent": True,
                            "unrelated_processes_alive": True},
            "store_snapshots": [{"integrity": "ok"}, {"integrity": "ok", "dispatch_events": 3,
                                                   "admitted_tasks": list(tasks)}],
            "census": {"killed_worker_pid": 101, "after_pids": [202], "unrelated_started_pids": [202]},
        },
    }
    for name, value in values.items():
        (raw / name).write_text(json.dumps(value), encoding="utf-8")
    for name in tasks:
        (raw / ("stage2-admit-" + name + ".json")).write_text(json.dumps({
            "outcome": "admitted", "admitted_revision": task_refs[name]["revision"],
            "bootstrap_assessment": scopes[name]}), encoding="utf-8")
    log = [{"task": task_refs[name]["id"], "revision": task_refs[name]["revision"],
            "review": review_ref["id"], "prover_result": "approved", "outcome": "admitted"} for name in tasks]
    (raw / "stage2-operator-admission.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in log), encoding="utf-8")
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
        self.assertEqual(statuses(raw)["store-matches-stage"], "fail")
        self.assertEqual(statuses(raw)["timeline-events"], "pass", "a Store gap is the Store check's, not the event check's")
        detail = {r["name"]: r["detail"] for r in perch_report.assertions(raw)}["store-matches-stage"]
        self.assertIn("store timeline t1 has gaps", detail)

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

    def test_stage_two_at_rest_keeps_only_the_operator_audit_log(self):
        raw = clean_raw(self.tmp / "stage2-audit")
        patch(raw, "config.json", lambda value: value.update(stage="2"))
        patch(raw, "at-rest.json", lambda value: value["home_run"].append("operator-admission.jsonl"))
        self.assertEqual(statuses(raw)["staging-at-rest-clean"], "pass")
        self.assertIn("operator-admission.jsonl", next(row["detail"] for row in perch_report.assertions(raw)
                                                       if row["name"] == "staging-at-rest-clean"))
        patch(raw, "at-rest.json", lambda value: value["home_run"].append("unexpected.tmp"))
        self.assertEqual(statuses(raw)["staging-at-rest-clean"], "fail")
        for name, change in (
                ("socket", lambda value: value["sockets"].append("/x/home/run/stray.sock")),
                ("Store holder", lambda value: value["store_holders"].update({"staging.store": ["4242"]})),
                ("canary scratch", lambda value: value["perch_canary"].append("old-run"))):
            with self.subTest(name=name):
                other = clean_raw(self.tmp / ("stage2-audit-" + name.replace(" ", "-")))
                patch(other, "config.json", lambda value: value.update(stage="2"))
                patch(other, "at-rest.json", lambda value: value["home_run"].append("operator-admission.jsonl"))
                patch(other, "at-rest.json", change)
                self.assertEqual(statuses(other)["staging-at-rest-clean"], "fail")
        for stage in ("0", "1"):
            with self.subTest(stage=stage):
                other = clean_raw(self.tmp / ("stage-" + stage + "-audit"))
                patch(other, "config.json", lambda value: value.update(stage=stage))
                patch(other, "at-rest.json", lambda value: value["home_run"].append("operator-admission.jsonl"))
                self.assertEqual(statuses(other)["staging-at-rest-clean"], "fail")

    def test_a_lifecycle_that_did_not_run_is_skipped_and_says_why(self):
        raw = clean_raw(self.tmp / "raw")
        (raw / "notes.json").write_text(json.dumps({"staging-lifecycle": "skipped: staging did not start"}), encoding="utf-8")
        got = {r["name"]: r for r in perch_report.assertions(raw)}
        for name in LIFECYCLE:
            self.assertEqual(got[name]["status"], "skip", name)
            self.assertIn("staging did not start", got[name]["detail"])
        self.assertEqual(perch_report.cmd_check(Namespace(raw=str(raw))), 0, "a skipped check is not a red run")

    def test_stage_two_canary_declares_three_tasks_dependency_and_unadmitted_revision(self):
        project = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))
        stage = project["stages"]["2"]
        self.assertEqual(stage["tasks"], ["A", "B", "C"])
        self.assertEqual(stage["admission"]["admitted"], ["A", "B", "C"])
        self.assertEqual(stage["dependencies"]["B"], ["A"])
        self.assertTrue(stage["admission"]["unadmitted_revision"])
        self.assertEqual(stage["scenarios"], ["admit-and-dispatch"])
        policy = stage["run_policy"]["assessment_accounting"]
        self.assertEqual(policy["scope_mode"], "check-accepted")
        self.assertEqual(policy["task_criterion_pairs"], ["A/C-A", "B/C-B", "C/C-C"])

    def test_stage_two_bundle_maps_repository_branch_and_check_policy(self):
        project = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))
        stage = project["stages"]["2"]
        self.assertEqual((stage["repository"], stage["branch"]), ("toy", "canon/main"))
        out = self.tmp / "stage2-bundle"
        subprocess.run([sys.executable, "-I", str(BOOTSTRAP / "perch_report.py"), "stage2-bundle",
                        "--project", str(BOOTSTRAP / "canary" / "project.json"), "--out", str(out)], check=True)
        tasklist = (out / "tasklist.md").read_text(encoding="utf-8")
        self.assertIn("| A | toy | canon/main |", tasklist)
        self.assertIn("| B | toy | canon/main |", tasklist)
        self.assertIn("| C | toy | canon/main |", tasklist)
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["assessment_accounting"]["scope_mode"], "check-accepted")
        review = (out / "reviews" / "plan-review.md").read_text(encoding="utf-8")
        self.assertIn("plan is approved", review)

    def test_stage_two_review_ref_is_the_stored_document_revision(self):
        raw = clean_stage2_raw(self.tmp / "stage2-review")
        bundle = self.tmp / "bundle"
        (bundle / "reviews").mkdir(parents=True)
        (bundle / "reviews" / "plan-review.md").write_text(perch_report.STAGE2_REVIEW_TEXT, encoding="utf-8")
        command = [sys.executable, "-I", str(BOOTSTRAP / "perch_report.py"), "stage2-review-ref",
                   "--status", str(raw / "stage2-project-status.json"), "--activation",
                   str(raw / "stage2-activation.json"), "--bundle", str(bundle)]
        selected = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        self.assertEqual(selected, json.loads((raw / "stage2-review-ref.json").read_text(encoding="utf-8")))
        self.assertEqual(selected["kind"], "dat.content.document")
        task_refs = json.loads((raw / "stage2-activation.json").read_text(encoding="utf-8"))[
            "activation"]["steps"]["tasks"]["task_refs"]
        for task in task_refs.values():
            self.assertNotEqual(selected["kind"], task["kind"])
            self.assertNotEqual(selected["id"], task["id"])
        patch(raw, "stage2-project-status.json", lambda value: value["documents"][0]["revision_ref"].update(
            id="task-A"))
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("different kind and id", rejected.stderr)
        patch(raw, "stage2-project-status.json", lambda value: value["documents"][0].update(
            revision_ref={"authority": "owner", "kind": "work.task", "id": "task-A", "revision": "rev-A"}))
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("exact stored document revision", rejected.stderr)

    def test_stage_two_plan_save_carries_typed_checks_and_dispatch_metadata(self):
        registration = self.tmp / "registration.json"
        registration.write_text(json.dumps({"project_ref": {"authority": "owner", "kind": "work.project",
                              "id": "perch-stage2", "revision": "rev-3"}}), encoding="utf-8")
        out = self.tmp / "plan-save.json"
        perch_report.cmd_stage2_plan_save(Namespace(project=str(BOOTSTRAP / "canary" / "project.json"),
                                                    registration=str(registration), out=str(out)))
        saved = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([task["id"] for task in saved["tasks"]], ["A", "B", "C"])
        self.assertEqual([task["dependencies"] for task in saved["tasks"]], [[], ["A"], ["B"]])
        self.assertTrue(all(task["fields"]["check"]["argv"] == ["/usr/bin/true"] for task in saved["tasks"]))
        self.assertTrue(all(task["metadata_namespace"]["otto.plan"] ==
                            {"repo": "toy", "branch": "canon/main", "route": "normal"}
                            for task in saved["tasks"]))
        raw = clean_stage2_raw(self.tmp / "stage2-plan-fault")
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "pass")
        patch(raw, "stage2-plan-save.input.json", lambda value: value["tasks"][0]["fields"].pop("check"))
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "fail")

    def test_stage_two_scope_must_pin_the_post_admission_task_revision(self):
        raw = clean_stage2_raw(self.tmp / "stage2-scope-fault")
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "pass")
        activated = json.loads((raw / "stage2-activation.json").read_text(encoding="utf-8"))
        old = activated["activation"]["steps"]["tasks"]["task_refs"]["A"]["revision"]
        patch(raw, "stage2-admit-A.json", lambda value: value["bootstrap_assessment"]["task_ref"].update(
            revision=old))
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "fail")

    def test_stage_two_host_commands_use_the_admitted_client_home(self):
        """A cold host project call must select the admitted client, not owner home."""
        import re
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        match = re.search(r"(?ms)^stage2_host_client\(\) \{\n.*?^\}\n", shell)
        self.assertIsNotNone(match)
        fake_python = self.tmp / "python-stub"
        fake_python.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
        fake_python.chmod(0o755)
        base = "STAGE_ROOT=/staging; CANARY_DIR=/staging/perch-canary/test; PY=" + str(fake_python) + "\n"

        def home_argument(function):
            script = base + function + '\nstage2_host_client --host claude-code project status --project perch-stage2\n'
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
            args = result.stdout.splitlines()
            return args[args.index("--home") + 1]

        self.assertEqual(home_argument(match.group()), "/staging/perch-canary/test/client")
        # Seed the gate's original bug into this one function: the same
        # assertion must turn red when project commands target owner home.
        seeded = match.group().replace('"$CANARY_DIR/client"', '"$STAGE_ROOT/home"')
        self.assertNotEqual(home_argument(seeded), "/staging/perch-canary/test/client")

    def test_stage_two_repo_is_mapped_before_owner_composition(self):
        source = (BOOTSTRAP / "staging.sh").read_text(encoding="utf-8")
        begin = source.index('  if [ -n "${OTTO_STAGING_CANARY_REPO:-}" ]; then')
        end = source.index('  fi\n', begin) + len('  fi\n')
        mapping = source[begin:end]
        root = self.tmp / "staging"
        repo = root / "perch-canary" / "2-run" / "canon"
        (repo / ".git").mkdir(parents=True)
        log = self.tmp / "map.log"
        script = ("STAGE_ROOT=" + str(root) + "\nOTTO_STAGING_CANARY_REPO=" + str(repo)
                  + "\nLOG=" + str(log) + "\nottoctl() { printf '%s\\n' \"$*\" >> \"$LOG\"; }\n"
                  + "die() { exit 1; }\n" + mapping)
        self.assertEqual(subprocess.run(["bash", "-c", script], capture_output=True).returncode, 0)
        self.assertEqual(log.read_text(encoding="utf-8").strip(), "repo map --name toy --path " + str(repo))
        self.assertLess(source.index('ottoctl repo map --name toy'), source.index('  cd "$TREE"\n'))
        perch = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        run = perch[perch.index("run_stage() {"):]
        self.assertLess(run.index('make_canon; phase canary-setup'), run.index('restart_staging "$stage"'))

    def test_fake_claude_launcher_emits_worker_artifact_only_in_its_lab(self):
        launcher = BOOTSTRAP / "perch_fake_claude.py"
        self.assertEqual(subprocess.run([str(launcher), "--version"], capture_output=True,
                                        text=True, check=True).stdout.strip(),
                         "2.1.293 (Claude Code)")
        lab = self.tmp / "worker-lab"
        lab.mkdir()
        frame = {"message": {"content": [{"text": "Canary dispatch A"}]}}
        result = subprocess.run([str(launcher), "--model", "claude-haiku-5-5", "--tools", "Read,Write"],
                                input=json.dumps(frame) + "\n", cwd=lab, capture_output=True,
                                text=True, check=True)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([event["type"] for event in events],
                         ["system", "user", "assistant", "user", "result"])
        artifact = next(lab.glob("perch-worker-*.txt"))
        self.assertIn("worker artifact", artifact.read_text(encoding="utf-8"))

    def test_fake_claude_c_worker_exposes_exact_kill_target_in_its_lab(self):
        import contextlib
        import io
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        lab = self.tmp / "c-worker-lab"
        lab.mkdir()

        def stop_at_pause():
            raise RuntimeError("held for owner worker kill")

        frame = {"message": {"content": [{"text": "Canary dispatch C"}]}}
        original_cwd = os.getcwd()
        try:
            os.chdir(lab)
            with mock_patch.object(sys, "argv", ["perch-fake-claude", "--model", "claude-haiku-5-5",
                                                 "--tools", "Read,Write"]), \
                    mock_patch.object(sys, "stdin", io.StringIO(json.dumps(frame) + "\n")), \
                    mock_patch.object(launcher.signal, "pause", stop_at_pause), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "held for owner worker kill"):
                    launcher.main()
        finally:
            os.chdir(original_cwd)
        self.assertEqual((lab / ".perch-worker-C.pid").read_text(encoding="utf-8").strip(),
                         str(os.getpid()))

    def test_fake_claude_initializer_is_inert_and_useful_turn_submits_done(self):
        import contextlib
        import io
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        lab = self.tmp / "worker-stream-lab"
        lab.mkdir()
        args = ["perch-fake-claude", "--model", "claude-haiku-5-5", "--tools", "Read,Write",
                "--permission-mode", "dontAsk", "--mcp-config",
                json.dumps({"mcpServers": {"otto": {"command": PY, "args": []}}}),
                "--allowedTools", "Read", "Write", "mcp__otto__task", "mcp__otto__check", "mcp__otto__done"]
        original_cwd = os.getcwd()
        try:
            os.chdir(lab)
            def turn(prompt, done):
                frame = {"message": {"content": [{"text": prompt}]}}
                output = io.StringIO()
                with mock_patch.object(sys, "argv", args), mock_patch.object(sys, "stdin", io.StringIO(json.dumps(frame) + "\n")), \
                        mock_patch.object(launcher, "done_tool", done), contextlib.redirect_stdout(output):
                    rc = launcher.main()
                return rc, [json.loads(line) for line in output.getvalue().splitlines()]

            rc, events = turn("Initialize this session only. Do not use tools or do task work. Return READY.",
                              lambda _: self.fail("initializer called done"))
            self.assertEqual(rc, 0)
            self.assertEqual(events[-1]["result"], "READY")
            self.assertEqual([event["type"] for event in events], ["system", "user", "result"])
            rc, events = turn("Canary dispatch A", lambda _: {"ok": True, "result": {"landed": True}})
            self.assertEqual(rc, 0)
            self.assertEqual(events[0]["permissionMode"], "dontAsk")
            self.assertEqual(events[0]["mcp_servers"], ["otto"])
            self.assertIn("mcp__otto__done", events[0]["tools"])
            self.assertEqual([block["name"] for event in events if event["type"] == "assistant"
                              for block in event["message"]["content"]], ["Write", "mcp__otto__done"])
            self.assertTrue(any(lab.glob("perch-worker-*.txt")))
            def red(_):
                raise RuntimeError("seeded done refusal")
            with contextlib.redirect_stderr(io.StringIO()):
                rc, events = turn("Canary dispatch B", red)
            self.assertEqual(rc, 1)
            self.assertEqual(events[-1]["subtype"], "error_during_execution")
        finally:
            os.chdir(original_cwd)

    def test_fake_claude_done_uses_the_owner_granted_socket_and_token(self):
        import io
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        sent = []

        class SocketStub:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def settimeout(self, value):
                self.timeout = value

            def connect(self, value):
                self.address = value

            def sendall(self, value):
                sent.append(json.loads(value))

            def makefile(self, *args, **kwargs):
                return io.StringIO('{"ok":true,"result":{"landed":true}}\n')

        sock = SocketStub()
        config = {"mcpServers": {"otto": {"args": ["-m", "herzchen.fleet.tools.stdio_server",
                                                   "--socket", "/tmp/canary.sock",
                                                   "--token-env", "OTTO_WORKER_TOKEN"]}}}
        with mock_patch.object(launcher.socket, "socket", return_value=sock), \
                mock_patch.dict(os.environ, {"OTTO_WORKER_TOKEN": "exact-worker-token"}):
            result = launcher.done_tool(["--mcp-config", json.dumps(config)])
        self.assertEqual(sock.address, "/tmp/canary.sock")
        self.assertEqual(sock.timeout, 90)
        self.assertEqual(sent, [{"op": "call", "token": "exact-worker-token", "tool": "done",
                                 "args": {"summary": "PERCH stage-2 canary worker finished"}}])
        self.assertTrue(result["result"]["landed"])

    def test_stage_two_dispatch_projection_uses_retained_owner_reads(self):
        raw = clean_stage2_raw(self.tmp / "stage2-dispatch-reads")
        (raw / "stage2-observations.json").unlink()
        refs = json.loads((raw / "stage2-activation.json").read_text(encoding="utf-8"))[
            "activation"]["steps"]["tasks"]["task_refs"]
        for alias in ("A", "B", "C"):
            assignment = {"authority": "owner", "kind": "assignment", "id": "assignment-" + alias,
                          "revision": "rev-1"}
            (raw / ("stage2-admit-" + alias + ".json")).write_text(json.dumps(
                {"outcome": "admitted", "admitted_revision": refs[alias]["revision"]}), encoding="utf-8")
            (raw / ("stage2-dispatch-" + alias + ".json")).write_text(json.dumps({"workers": {
                alias: {"automatic": True, "automatic_revision": refs[alias]["revision"],
                        "assignment_ref": assignment, "schedule_id": "schedule-" + alias}}}), encoding="utf-8")
            lifecycle = {"A": "completed" if alias != "A" else "active",
                         "B": "completed" if alias == "C" else "active", "C": "active"}
            (raw / ("stage2-dispatch-" + alias + "-project.json")).write_text(json.dumps(
                {"tasks": [{"id": name, "lifecycle": state} for name, state in lifecycle.items()]}), encoding="utf-8")
            (raw / ("stage2-owner-" + alias + ".json")).write_text(json.dumps({
                "native_capacity": {"active_or_uncertain": 1},
                "manager_turns": {"active": 0, "limit": 6}}), encoding="utf-8")
        (raw / "stage2-unadmitted-request.json").write_text(json.dumps({
            "task_ref": {key: refs["C"][key] for key in ("authority", "kind", "id")},
            "revision": "rev-unadmitted"}), encoding="utf-8")
        (raw / "stage2-unadmitted-response.json").write_text(json.dumps({
            "outcome": "rejected", "error": {"code": "sheet_changed",
                                        "message": "reviewed revision rev-unadmitted is superseded"}}), encoding="utf-8")
        patch(raw, "notes.json", lambda value: value.update({"stage2-unadmitted-exit": 1}))
        for name in ("before", "after"):
            (raw / ("stage2-store-" + name + ".json")).write_text(json.dumps({
                "integrity": "ok", "rows": {"events": 6}}), encoding="utf-8")
        (raw / "timeline.json").write_text(json.dumps({
            "tasks": [{"task_id": "assignment-" + alias,
                       "events": [{"stream": "dispatch:assignment-" + alias,
                                   "event_type": "work.assignment.dispatched"}]}
                      for alias in ("A", "B", "C")],
            "work_tasks": [{"alias": alias, "admitted_revision": refs[alias]["revision"]}
                           for alias in ("A", "B", "C")]}), encoding="utf-8")
        projected = perch_report.stage2_observations(raw)
        self.assertEqual(projected["dispatch"]["dispatched"], ["A", "B", "C"])
        self.assertTrue(all(row["ready"] for row in projected["dispatch"]["records"]))
        self.assertEqual(projected["store_snapshots"][-1]["dispatch_events"], 3)
        self.assertEqual(projected["unadmitted_refusal"]["reason"], "unadmitted_revision")
        patch(raw, "stage2-dispatch-B.json", lambda value: value["workers"]["B"].update(automatic=False))
        red = perch_report.stage2_observations(raw)
        self.assertEqual(red["dispatch"]["dispatched"], ["A", "C"])
        self.assertLess(red["store_snapshots"][-1]["dispatch_events"], 3)

    def test_stage_two_kill_evidence_requires_slot_release_and_owner_survival(self):
        raw = self.tmp / "stage2-kill"
        raw.mkdir()
        (raw / "stage2-killed-worker.json").write_text(json.dumps({"pid": 101, "owner_pid": 202}), encoding="utf-8")
        (raw / "stage2-capacity-before-kill.json").write_text(json.dumps(
            {"native_capacity": {"active_or_uncertain": 2}}), encoding="utf-8")
        (raw / "stage2-capacity-after-kill.json").write_text(json.dumps(
            {"native_capacity": {"active_or_uncertain": 1}}), encoding="utf-8")
        (raw / "stage2-census-before-kill.txt").write_text("101 202 worker\n202 202 owner\n", encoding="utf-8")
        (raw / "stage2-census-after-kill.txt").write_text("202 202 owner\n", encoding="utf-8")
        state = perch_report.stage2_kill_state(raw)
        self.assertTrue(all(state[key] for key in
                            ("slot_released", "killed_worker_absent", "unrelated_processes_alive")))
        patch(raw, "stage2-capacity-after-kill.json", lambda value: value["native_capacity"].update(
            active_or_uncertain=2))
        self.assertFalse(perch_report.stage2_kill_state(raw)["slot_released"])

    def test_stage_two_store_requires_three_admitted_work_tasks_under_seeded_fault(self):
        raw = clean_stage2_raw(self.tmp / "stage2-store")
        stage = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))["stages"]["2"]
        patch(raw, "config.json", lambda value: value.update(store=stage["store"]))
        (raw / "timeline.json").write_text(json.dumps({
            "error": None, "store_events": 47,
            "tasks": [{"task_id": "assignment-" + alias, "complete": True, "gaps": []}
                      for alias in ("A", "B", "C")],
            "work_tasks": [{"alias": alias, "admitted_revision": "rev-" + alias}
                           for alias in ("A", "B", "C")]}), encoding="utf-8")
        (raw / "store-at-rest.json").write_text(json.dumps({"error": None, "bytes": 700000}), encoding="utf-8")
        (raw / "stage2-store-before.json").write_text(json.dumps({"bytes": 569344}), encoding="utf-8")
        self.assertEqual(statuses(raw)["store-matches-stage"], "pass")
        perch_report.seed(raw, "store")
        self.assertEqual(statuses(raw)["store-matches-stage"], "fail")

    def test_composefleet_detection_uses_landed_modules_not_a_marker_string(self):
        stage_root = self.tmp / "staging"
        self.assertFalse(perch_report.composefleet_landed(stage_root))
        source = stage_root / "tree" / "src"
        for relative in ("otto/hostctl/product_service.py", "otto/hostctl/fleet_landing.py",
                         "herzchen/fleet/landing.py", "herzchen/domains/work/admission.py"):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("module implementation\n", encoding="utf-8")
        self.assertTrue(perch_report.composefleet_landed(stage_root))

    def test_stage_two_scenario_setup_failure_is_explicit_and_gate_fails(self):
        raw = self.tmp / "raw-stage2-skip"
        raw.mkdir()
        (raw / "config.json").write_text(json.dumps({"stage": "2", "scenarios": ["admit-and-dispatch"],
                    "staging_restart": 0, "tasks": [], "pool_limit": 2, "manager_reserve": 1,
                    "stage2_tasks": ["A", "B", "C"], "stage2_admitted": ["A", "B", "C"],
                    "stage2_dependencies": {"A": [], "B": ["A"], "C": ["B"]},
                    "stage2_unadmitted_revision": {"task": "C", "revision": "rev-unadmitted", "admitted": False}}), encoding="utf-8")
        (raw / "notes.json").write_text(json.dumps({"admit-and-dispatch": "failed: COMPOSEFLEET prerequisites are absent from the staging tree"}), encoding="utf-8")
        got = {row["name"]: row for row in perch_report.assertions(raw)}
        self.assertEqual(got["admit-and-dispatch-ran"]["status"], "fail")
        self.assertIn("did not run", got["admit-and-dispatch-ran"]["detail"])
        self.assertIn("failed:", json.loads((raw / "notes.json").read_text(encoding="utf-8"))["admit-and-dispatch"])
        self.assertEqual(got["admitted-ready-dependency-order"]["status"], "skip")

    def test_stage_two_seeded_faults_fail_their_matching_assertions_only(self):
        cases = {
            "stage2_scenario": "admit-and-dispatch-ran",
            "stage2_canary": "stage2-canary-valid",
            "stage2_review": "stage2-review-document",
            "admission_presence": "operator-presence-approved",
            "admit_order": "admitted-ready-dependency-order",
            "unadmitted": "unadmitted-revision-refused",
            "reserve": "pool-and-manager-reserve-held",
            "worker_kill": "worker-kill-recovery",
            "store_snapshot": "stage2-store-snapshots",
            "stage2_census": "stage2-census",
        }
        for fault, target in cases.items():
            with self.subTest(fault=fault):
                raw = clean_stage2_raw(self.tmp / ("stage2-" + fault))
                green = {row["name"]: row["status"] for row in perch_report.assertions(raw)
                         if row["name"] in perch_report.STAGE2}
                self.assertEqual(green, {name: "pass" for name in perch_report.STAGE2}, green)
                subprocess.run([sys.executable, "-I", str(BOOTSTRAP / "perch_report.py"), "seed", "--raw", str(raw),
                                "--fault", fault], check=True)
                got = {row["name"]: row["status"] for row in perch_report.assertions(raw)
                       if row["name"] in perch_report.STAGE2}
                self.assertEqual(got[target], "fail", got)
                self.assertEqual({name for name, status in got.items() if status == "fail"}, {target}, got)


class FakePresenceLauncherTests(unittest.TestCase):
    def test_fake_owner_launcher_injects_approval_before_product_cli(self):
        spec = importlib.util.spec_from_file_location("perch_fake_presence", BOOTSTRAP / "perch_fake_presence.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        root = Path(tempfile.mkdtemp(prefix="perch-fake-launcher-")).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        home = root / "home"
        observed = []
        otto = ModuleType("otto"); otto.__path__ = []
        hostctl = ModuleType("otto.hostctl"); hostctl.__path__ = []
        presence = ModuleType("otto.hostctl.presence")
        presence.PresenceResult = lambda status: SimpleNamespace(status=status)
        presence.LocalAuthenticationProver = type("RealPresence", (), {})
        cli = ModuleType("otto.hostctl.cli")

        def cli_main(argv):
            observed.append((argv, presence.LocalAuthenticationProver().prove(
                reason="Admit task", timeout_seconds=30).status))
            return 0

        cli.main = cli_main
        otto.hostctl = hostctl
        hostctl.presence = presence
        hostctl.cli = cli
        modules = {"otto": otto, "otto.hostctl": hostctl,
                   "otto.hostctl.presence": presence, "otto.hostctl.cli": cli}
        args = ["--home", str(home), "service", "run"]
        with mock_patch.dict(sys.modules, modules), mock_patch.dict(os.environ, {
                "OTTO_STAGING_ROOT": str(root), "OTTO_STAGING_FAKE_PRESENCE": "1"}):
            self.assertEqual(launcher.main(args), 0)
            self.assertEqual(observed, [(args, "approved")])
            with self.assertRaises(SystemExit):
                launcher.main(["--home", str(home), "service", "status"])
        with mock_patch.dict(os.environ, {"OTTO_STAGING_ROOT": str(root), "OTTO_STAGING_FAKE_PRESENCE": "0"}):
            with self.assertRaises(SystemExit):
                launcher.main(args)


class Stage2OwnerBootstrapTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("perch_stage2_owner", BOOTSTRAP / "perch_stage2_owner.py")
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)

    def test_staging_scopes_are_declared_for_exact_tasks(self):
        calls = []

        class Ref:
            def __init__(self, value, kind=None, ident=None, revision=None):
                self.value = value if isinstance(value, dict) else {
                    "authority": value, "kind": kind, "id": ident, "revision": revision}
                self.authority = self.value.get("authority")
                self.kind = self.value["kind"]
                self.id = self.value.get("id")
                self.revision = self.value.get("revision")

            @classmethod
            def from_dict(cls, value):
                return cls(value)

            def to_dict(self):
                return self.value

        class Session:
            store = object()
            owner = SimpleNamespace(owner_actor=SimpleNamespace(actor="owner", authority="owner"),
                                    evidence_payload_resolver=object())

            class Graph:
                def current(self, ref):
                    if ref.kind == "work.task":
                        return SimpleNamespace(ref=Ref({"authority": "owner", "kind": "work.task",
                                                        "id": ref.id, "revision": "rev-admitted"}),
                                               payload={"alias": ref.id.split("-")[-1],
                                                        "project_ref": {"authority": "owner", "kind": "work.project",
                                                                        "id": "project", "revision": "rev-4"}})
                    return SimpleNamespace(ref=Ref({"authority": "owner", "kind": "work.project",
                                                    "id": "project", "revision": "rev-4"}),
                                           payload={"custom": {"otto_host_registration": {"run_id": "perch-stage2"}}})

            owner.graph = Graph()

            def __init__(self, config, host=None):
                self.host = host

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        class Assessment:
            def __init__(self, store, **kwargs):
                pass

            def declare_scope(self, key, **kwargs):
                calls.append((key, kwargs))
                aliases = ("A", "B", "C") if key == "perch-stage2-policy-criteria" else (key.rsplit("-", 1)[-1],)
                return SimpleNamespace(ref=Ref({"kind": "assessment.scope", "id": key, "revision": "rev-1"}),
                                       criterion_refs=[Ref({"kind": "assessment.criterion",
                                                            "id": "C-" + alias, "revision": "rev-1"})
                                                       for alias in aliases])

            def get_scope(self, ref):
                return SimpleNamespace(criterion_refs=[Ref({"kind": "assessment.criterion",
                                                          "id": "C-" + alias, "revision": "rev-1"})
                                                       for alias in ("A", "B", "C")])

        modules = {
            "herzchen": ModuleType("herzchen"),
            "herzchen.contracts": ModuleType("herzchen.contracts"),
            "herzchen.domains": ModuleType("herzchen.domains"),
            "herzchen.domains.assessment": ModuleType("herzchen.domains.assessment"),
            "otto": ModuleType("otto"),
            "otto.hostctl": ModuleType("otto.hostctl"),
            "otto.hostctl.owner": ModuleType("otto.hostctl.owner"),
        }
        modules["herzchen.contracts"].ResourceRef = Ref
        modules["herzchen.domains.assessment"].AssessmentModule = Assessment
        modules["otto.hostctl.owner"].HostSession = Session
        modules["otto.hostctl.owner"].service_store = lambda store: contextlib.nullcontext()
        refs = {name: {"authority": "owner", "kind": "work.task", "id": "task-" + name, "revision": "rev-1"}
                for name in ("A", "B", "C")}
        service = SimpleNamespace(config={"hosts": {"claude-code": {"principal": "canary"}}}, store=object())
        with mock_patch.dict(sys.modules, modules):
            result = self.launcher._seed_scopes(service, refs)
            self.assertEqual(set(result["criterion_refs"]), {"A", "B", "C"})
            self.assertEqual([row["source_alias"] for row in calls[0][1]["criteria"]],
                             ["C-A", "C-B", "C-C"])
            scoped = self.launcher._seed_admitted_scope(service, refs["A"])
            self.assertEqual(scoped["task_ref"]["revision"], "rev-admitted")
            self.assertEqual(scoped["criterion_ref"]["id"], "C-A")
            self.assertEqual(calls[1][1]["protocol"], "check-accepted")
            self.assertEqual(calls[1][1]["designated_approver"], "perch-stage2-manager")
            self.assertTrue(calls[1][1]["allow_no_review"])
            with self.assertRaisesRegex(RuntimeError, "exactly A, B and C"):
                self.launcher._seed_scopes(service, {"A": refs["A"]})

    def test_scope_setup_runs_between_activation_and_composed_view(self):
        order = []
        refs = {name: {"kind": "work.task", "id": "task-" + name, "revision": "rev-1"}
                for name in ("A", "B", "C")}

        class OwnerService:
            def _run_operation(self, handler, namespace, operation):
                order.append("activate")
                return {"outcome": "prepared", "activation": {"steps": {"tasks": {"task_refs": refs}}}}

            def _admit_revision(self, args):
                order.append("admit")
                return {"outcome": "admitted", "task_ref": args["task_ref"]}

        class ProjectOwnerService(OwnerService):
            def _run_operation(self, handler, namespace, operation):
                order.append("original")
                if operation == ("project", "status"):
                    return {"outcome": "read", "project_ref": {"id": "project"}}
                return {"outcome": "original"}

        project = ModuleType("otto.hostctl.project_service")
        project.ProjectOwnerService = ProjectOwnerService
        service = ModuleType("otto.hostctl.service")
        service.OwnerService = OwnerService
        modules = {"otto": ModuleType("otto"), "otto.hostctl": ModuleType("otto.hostctl"),
                   "otto.hostctl.project_service": project, "otto.hostctl.service": service}
        with mock_patch.dict(sys.modules, modules), mock_patch.object(self.launcher, "_seed_scopes",
                  side_effect=lambda _, value: order.append("scopes") or {"criterion_refs": {}}), \
                mock_patch.object(self.launcher, "_seed_admitted_scope",
                  side_effect=lambda _, value: order.append("task_scope") or {"task_ref": value}), \
                mock_patch.object(self.launcher, "_refresh_manager_setup",
                  side_effect=lambda _, value: order.append("manager_setup") or {"task_ref": value}):
            self.launcher.install_scope_setup()
            owner = ProjectOwnerService()
            owner._build_activated_view = lambda name: order.append("view")
            result = owner._run_operation(None, SimpleNamespace(project="perch-stage2"), ("project", "activate"))
            self.assertEqual(order, ["activate", "scopes", "view"])
            self.assertIn("bootstrap_assessment", result)
            admitted = owner._admit_revision({"task_ref": refs["A"]})
            self.assertEqual(order, ["activate", "scopes", "view", "admit", "task_scope", "manager_setup"])
            self.assertEqual(admitted["bootstrap_assessment"]["task_ref"], refs["A"])
            self.assertEqual(admitted["bootstrap_manager_setup"]["task_ref"], refs["A"])
            self.assertEqual(owner._run_operation(None, SimpleNamespace(project="other"),
                                                  ("project", "activate"))["outcome"], "original")
            owner.router = SimpleNamespace(services={"project": SimpleNamespace(server=SimpleNamespace(
                run_id="perch-stage2", state={"project_ref": {"id": "project"},
                                              "workers": {"A": {"automatic": True}},
                                              "automatic_dispatch_failures": {}}))})
            status = owner._run_operation(None, SimpleNamespace(project="perch-stage2"), ("project", "status"))
            self.assertTrue(status["workers"]["A"]["automatic"])
            self.assertEqual(status["automatic_dispatch_failures"], {})

    def test_project_status_exposes_retained_dispatch_without_manager_identity(self):
        import re
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        wait = re.search(r"(?ms)^stage2_wait_worker\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(wait)
        self.assertIn('project status --project perch-stage2', wait.group())
        self.assertNotIn('manager --project perch-stage2 status', wait.group())

        project_ref = {"authority": "owner", "kind": "work.project", "id": "project", "revision": "rev-1"}
        worker = {"A": {"automatic": True, "automatic_revision": "rev-1",
                        "assignment_ref": {"kind": "wrk.assignment", "id": "assignment-A"},
                        "schedule_id": "schedule-A"}}
        state = {"project_ref": project_ref, "workers": worker,
                 "automatic_dispatch_failures": {}}
        view = SimpleNamespace(server=SimpleNamespace(run_id="perch-stage2", state=state))
        owner = SimpleNamespace(router=SimpleNamespace(services={"project": view}))
        read = {"outcome": "read", "project_ref": project_ref}
        observed = self.launcher._status_with_dispatch(owner, read)
        self.assertEqual(observed["workers"], worker)
        self.assertEqual(observed["automatic_dispatch_failures"], {})
        worker["A"]["automatic"] = False
        self.assertTrue(observed["workers"]["A"]["automatic"])
        perch_report.stage2_dispatch_no_failure(observed, "A")
        # Seed the owner's retained pre-effect refusal. The wait turns red
        # with the actual reason instead of waiting on a protected command.
        observed["automatic_dispatch_failures"]["A"] = {"reason": "repo unavailable"}
        with self.assertRaisesRegex(ValueError, "repo unavailable"):
            perch_report.stage2_dispatch_no_failure(observed, "A")
        del observed["workers"]
        with self.assertRaisesRegex(ValueError, "lacks the owner's retained dispatch state"):
            perch_report.stage2_dispatch_no_failure(observed, "A")

    def test_admitted_task_rebinds_unstarted_manager_due_and_preserves_setup(self):
        from dataclasses import dataclass

        class Ref:
            def __init__(self, value, kind=None, ident=None, revision=None):
                self.value = value if isinstance(value, dict) else {
                    "authority": value, "kind": kind, "id": ident, "revision": revision}
                self.authority, self.kind = self.value["authority"], self.value["kind"]
                self.id, self.revision = self.value["id"], self.value["revision"]

            @classmethod
            def from_dict(cls, value):
                return cls(value)

            def to_dict(self):
                return self.value

            def __eq__(self, other):
                return isinstance(other, Ref) and self.value == other.value

        def ref(kind, ident, revision):
            return {"authority": "owner", "kind": kind, "id": ident, "revision": revision}

        task = ref("work.task", "task-A", "rev-2")
        project = ref("work.project", "project", "rev-5")
        assignment = ref("wrk.assignment", "manager", "rev-2")
        old_mandate = ref("dat.content.document", "old-mandate", "rev-1")
        new_mandate = ref("dat.content.document", "new-mandate", "rev-1")
        setup_ref = ref("dat.content.document", "setup", "rev-1")
        old_task = ref("work.task", "task-A", "rev-1")
        old_content = {"role": "manager", "task_ref": old_task,
                       "instruction_contract": {"task_ref": old_task, "authority": {"source": "canonical_owner"}}}
        events = []
        current_task = [task]

        class Graph:
            def current(self, value):
                if value.kind == "work.task":
                    return SimpleNamespace(ref=Ref(current_task[0]), payload={
                        "alias": "B" if current_task[0]["id"] == "task-B" else "A"})
                return SimpleNamespace(ref=Ref(project))

        due = {"old": {"role": "manager", "assignment_ref": assignment,
                       "execution_mode": "fresh_manager", "stop_state": "active",
                       "completion_state": "none", "host_evidence": {}, "version": 2,
                       "context_refs": [old_mandate],
                       "target": {"task_ref": old_task, "mandate_ref": old_mandate}}}

        @dataclass
        class StubDue:
            version: int
            target: dict
            context_refs: tuple

            @classmethod
            def from_dict(cls, value):
                return cls(value["version"], value["target"], tuple(value["context_refs"]))

            def to_dict(self):
                return {**due["old"], "version": self.version,
                        "target": self.target, "context_refs": self.context_refs}

        def save_due(schedule, value, *, request_id, expected_version):
            self.assertEqual(schedule, "old")
            self.assertEqual(expected_version, 2)
            events.append(("due", value, request_id))
            due[schedule] = {**value, "version": expected_version + 1}
            return due[schedule]

        class App:
            actor = "owner"
            runtime = object()

            def __init__(self):
                self.portfolio = SimpleNamespace(create_document=self.create_document)

            def read_operating_setup(self, *, project_ref):
                self.assert_project(project_ref)
                return {"setup_ref": setup_ref, "setup": {"mode": "manual", "roles": {"manager": "old"},
                        "advisor_policy": {"mode": "disabled", "reason": "manual"}, "acceptance_tasks": []}}

            def assert_project(self, value):
                if value != project:
                    raise AssertionError("wrong project")

            def create_document(self, project_ref, **kwargs):
                self.assert_project(project_ref)
                events.append(("mandate", kwargs))
                return {"record": {"payload": {"current_revision": new_mandate}}}

            def _document_revision(self, response, field):
                return response["record"]["payload"]["current_revision"]

        app = App()
        state = {"project_ref": project, "task_refs": {"A": old_task}, "manager": "manager",
                 "assignment_ref": assignment, "manager_generation": 1,
                 "requested_model": "claude-haiku-5-5", "requested_reasoning": "medium",
                 "schedule_id": None}
        owner = SimpleNamespace(graph=Graph(), content=SimpleNamespace(
            read=lambda value: {"content": old_content}))
        server = SimpleNamespace(run_id="perch-stage2", state=state, owner=owner,
                                 due_port=SimpleNamespace(read_due=lambda schedule: due.get(schedule),
                                                          save_due=save_due),
                                 _save_state=lambda: events.append(("saved", dict(state))))
        view = SimpleNamespace(server=server, _execution=lambda **kwargs: app)
        service = SimpleNamespace(router=SimpleNamespace(services={"project": view}))
        module = ModuleType("herzchen.contracts")
        module.ResourceRef = Ref
        attention = ModuleType("otto.attention")
        attention.DueRecord = StubDue
        operating = ModuleType("otto.portfolio.operating_setup")
        operating.evaluate_setup = lambda runtime, project_ref, setup: {
            "ready": due["old"]["target"]["task_ref"] == task, "blockers": []}
        with mock_patch.dict(sys.modules, {"herzchen": ModuleType("herzchen"),
                                          "herzchen.contracts": module,
                                          "otto": ModuleType("otto"),
                                          "otto.attention": attention,
                                          "otto.portfolio": ModuleType("otto.portfolio"),
                                          "otto.portfolio.operating_setup": operating}):
            updated = self.launcher._refresh_manager_setup(service, task)
            self.assertEqual(updated["outcome"], "rebound")
            self.assertEqual(updated["task_ref"], task)
            self.assertEqual(events[0][1]["content"]["task_ref"], task)
            self.assertEqual(events[0][1]["content"]["instruction_contract"]["task_ref"], task)
            self.assertEqual(old_content["task_ref"], old_task)
            self.assertEqual(events[1][0], "due")
            self.assertEqual(events[1][1]["target"]["task_ref"], task)
            self.assertEqual(events[1][1]["target"]["mandate_ref"], new_mandate)
            self.assertEqual(events[1][1]["context_refs"], (new_mandate,))
            self.assertEqual(updated["setup_ref"], setup_ref)
            self.assertIsNone(state["schedule_id"], "a prepared manager is not a started manager")
            self.assertEqual(state["mandate_ref"], new_mandate)
            self.assertEqual(events[-1][0], "saved")
            replay = self.launcher._refresh_manager_setup(service, task)
            self.assertEqual(replay["outcome"], "already-current")
            self.assertEqual([event[0] for event in events].count("due"), 1)
            state["schedule_id"] = "foreign-manager"
            before = len(events)
            with self.assertRaisesRegex(RuntimeError, "no exact adopted operating setup"):
                self.launcher._refresh_manager_setup(service, task)
            self.assertEqual(len(events), before)
            state["schedule_id"] = None
            # Admission of B does not move the manager off its selected A task.
            b_task = ref("work.task", "task-B", "rev-2")
            state["task_refs"]["B"] = ref("work.task", "task-B", "rev-1")
            current_task[0] = b_task
            before = len(events)
            self.assertIsNone(self.launcher._refresh_manager_setup(service, b_task))
            self.assertEqual(len(events), before)
            # Seed the gate's stale canonical task: setup must go red before
            # publishing another mandate or claiming a refreshed binding.
            current_task[0] = old_task
            before = len(events)
            with self.assertRaisesRegex(RuntimeError, "exact admitted task revision"):
                self.launcher._refresh_manager_setup(service, task)
            self.assertEqual(len(events), before)
            current_task[0] = task
            due["old"]["target"] = {"task_ref": old_task, "mandate_ref": old_mandate}
            due["old"]["host_evidence"] = {"gateway_attempt": {"state": "started"}}
            with self.assertRaisesRegex(RuntimeError, "already begun a native effect"):
                self.launcher._refresh_manager_setup(service, task)
            self.assertEqual(len(events), before)

    def test_real_due_port_rebind_is_ready_without_a_second_manager_occurrence(self):
        src = str(ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
            self.addCleanup(sys.path.remove, src)
        from tests.test_execution_application import ExecutionApplicationTests
        from otto.portfolio.operating_setup import evaluate_setup

        fixture = ExecutionApplicationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        manager, _, mandate = fixture.role_handles("manager", "manager", None)
        project = fixture.project.ref.to_dict()
        task = fixture.task.ref.to_dict()
        composition = {
            "schema": "otto.operating-composition.v1", "mode": "manual",
            "defaults": {"model": "gpt-test", "reasoning": "high"},
            "roles": {"manager": {"assignment_ref": manager.ref.to_dict(), "generation": 1,
                                  "task_ref": task, "mandate_ref": mandate, "fresh_manager": True}},
            "advisor_policy": {"mode": "disabled", "reason": "canary fixture"},
            "acceptance_tasks": [],
        }
        applied = fixture.app.compose_operating_setup(
            project_ref=project, operation="apply", setup=composition, request_key="canary-setup")
        self.assertEqual(applied["outcome"], "applied", applied)
        schedule = applied["setup"]["roles"]["manager"]
        admitted = fixture.owner.graph.revise(
            fixture.task.ref, title="Admitted canary task", logical_request_key="canary-admitted").ref.to_dict()
        graph = fixture.owner.graph
        observed = [task]

        class CanaryGraph:
            def current(self, ref):
                record = graph.current(ref)
                if ref.kind == "work.task":
                    return SimpleNamespace(ref=type(record.ref).from_dict(observed[0]),
                                           payload={"alias": "A"})
                return record

        state = {"project_ref": project, "task_refs": {"A": task}, "manager": "manager",
                 "assignment_ref": manager.ref.to_dict(), "manager_generation": 1,
                 "requested_model": "gpt-test", "requested_reasoning": "high", "schedule_id": None}
        saved = []
        server = SimpleNamespace(run_id="perch-stage2", state=state,
                                 owner=SimpleNamespace(graph=CanaryGraph(), content=fixture.owner.content),
                                 due_port=fixture.port, _save_state=lambda: saved.append(dict(state)))
        view = SimpleNamespace(server=server, _execution=lambda **kwargs: fixture.app)
        service = SimpleNamespace(router=SimpleNamespace(services={"project": view}))
        counts = fixture.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(RuntimeError, "exact admitted task revision"):
            self.launcher._refresh_manager_setup(service, admitted)
        self.assertEqual(fixture.store.consumer().snapshot_counts(), counts)
        observed[0] = admitted
        rebound = self.launcher._refresh_manager_setup(service, admitted)
        self.assertEqual(rebound["outcome"], "rebound")
        self.assertEqual(rebound["schedule_id"], schedule)
        self.assertIsNone(state["schedule_id"], "rebind must not claim a manager launch")
        self.assertEqual(rebound["setup_ref"], applied["setup_ref"])
        due = fixture.port.read_due(schedule)
        self.assertEqual(due["target"]["task_ref"], admitted)
        self.assertEqual(due["target"]["mandate_ref"], state["mandate_ref"])
        self.assertEqual(due["context_refs"].count(state["mandate_ref"]), 1)
        self.assertTrue(evaluate_setup(fixture.app.runtime, project, applied["setup"])["ready"])
        self.assertEqual(self.launcher._refresh_manager_setup(service, admitted)["outcome"], "already-current")
        self.assertEqual(len(saved), 2)
        started = fixture.app.start(schedule_id=schedule)
        self.assertEqual(started["outcome"], "succeeded", started)

    def test_stage_two_preserves_operator_log_and_copies_raw_evidence(self):
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        self.assertNotIn("stage2_cleanup_operator_log", shell)
        self.assertNotIn('rm -f "$STAGE_ROOT/home/run/operator-admission.jsonl"', shell)
        self.assertIn('cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-operator-admission.jsonl"',
                      shell)

    def test_real_stage_two_keeps_real_prover_and_fake_uses_stub(self):
        root = Path(tempfile.mkdtemp(prefix="perch-stage2-owner-"))
        self.addCleanup(shutil.rmtree, root, True)
        calls = []
        cli = ModuleType("otto.hostctl.cli")
        cli.main = lambda argv: calls.append(("real", argv)) or 0
        fake = ModuleType("perch_fake_presence")
        fake.main = lambda argv: calls.append(("fake", argv)) or 0
        modules = {"otto": ModuleType("otto"), "otto.hostctl": ModuleType("otto.hostctl"),
                   "otto.hostctl.cli": cli, "perch_fake_presence": fake}
        args = ["--home", str(root / "home"), "service", "run"]
        with mock_patch.dict(sys.modules, modules), mock_patch.object(self.launcher, "install_scope_setup") as setup, \
                mock_patch.object(self.launcher, "defer_fake_lab_cleanup") as defer, \
                mock_patch.object(self.launcher, "install_fake_completion") as complete:
            for mode in ("0", "1"):
                with mock_patch.dict(os.environ, {"OTTO_STAGING_ROOT": str(root),
                         "OTTO_STAGING_STAGE2_SETUP": "1", "OTTO_STAGING_FAKE_PRESENCE": mode}):
                    self.assertEqual(self.launcher.main(args), 0)
            self.assertEqual([item[0] for item in calls], ["real", "fake"])
            self.assertEqual(setup.call_count, 2)
            self.assertEqual(defer.call_count, 1)
            self.assertEqual(complete.call_count, 1)
            with mock_patch.dict(os.environ, {"OTTO_STAGING_ROOT": str(root),
                     "OTTO_STAGING_STAGE2_SETUP": "0", "OTTO_STAGING_FAKE_PRESENCE": "1"}):
                with self.assertRaises(SystemExit):
                    self.launcher.main(args)

    def test_fake_lab_cleanup_is_deferred_only_after_a_landing(self):
        root = Path(tempfile.mkdtemp(prefix="perch-stage2-lab-"))
        self.addCleanup(shutil.rmtree, root, True)
        canary_repo = root / "perch-canary" / "2-test" / "canon"
        other_repo = root / "other" / "canon"
        canary_repo.mkdir(parents=True)
        other_repo.mkdir(parents=True)
        calls = []

        class LabRefused(RuntimeError):
            pass

        class LabFleet:
            def __init__(self, repo):
                self.repo = repo

            def remove(self, name, merged_into=None, before_unlink=None):
                calls.append((name, merged_into))
                return "removed"

        labs = ModuleType("herzchen.fleet.labs")
        labs.LabFleet = LabFleet
        labs.LabRefused = LabRefused
        modules = {"herzchen": ModuleType("herzchen"), "herzchen.fleet": ModuleType("herzchen.fleet"),
                   "herzchen.fleet.labs": labs}
        with mock_patch.dict(sys.modules, modules):
            self.launcher.defer_fake_lab_cleanup(root)
            fleet = LabFleet(canary_repo)
            with self.assertRaisesRegex(LabRefused, "artifact capture"):
                fleet.remove("task-opaque-id", merged_into="commit")
            with self.assertRaisesRegex(LabRefused, "artifact capture"):
                fleet.remove("another-task", merged_into="commit")
            self.assertEqual(LabFleet(other_repo).remove("A", merged_into="commit"), "removed")
            self.assertEqual(fleet.remove("A"), "removed")
        self.assertEqual(calls, [("A", "commit"), ("A", None)])

    def test_fake_manager_completes_only_landed_canary_with_stored_acceptance(self):
        calls = []

        class Ref:
            def __init__(self, authority, kind, ident, revision=None):
                self.authority, self.kind, self.id, self.revision = authority, kind, ident, revision

            @classmethod
            def from_dict(cls, value):
                return cls(value["authority"], value["kind"], value["id"], value.get("revision"))

            def to_dict(self):
                return dict(authority=self.authority, kind=self.kind, id=self.id, revision=self.revision)

        candidate = Ref("owner", "wrk.result", "candidate-A", "rev-1")
        task_ref = Ref("owner", "work.task", "task-A", "rev-admitted")
        project_ref = Ref("owner", "work.project", "project", "rev-4")
        manager_ref = Ref("owner", "wrk.assignment", "manager", "rev-2")

        class Graph:
            def __init__(self):
                self.reader = self

            def get_identity(self, ref):
                if ref.kind == "wrk.result":
                    return SimpleNamespace(ref=candidate, payload={"value": {"sealed_run": "run-A"}})
                return self.current(ref)

            def current(self, ref):
                return SimpleNamespace(ref=task_ref if ref.kind == "work.task" else project_ref)

        class Assessment:
            def __init__(self, *args, **kwargs):
                pass

            def get_result(self, ref):
                self_ref = ref.to_dict()
                if self_ref["kind"] != "assessment.result":
                    raise ValueError("wrong result")
                return SimpleNamespace(candidate_ref=candidate)

        class Portfolio:
            outcome = "completed"

            def complete_task(self, project, task, manager, **kwargs):
                calls.append((project, task, manager, kwargs))
                return {"outcome": self.outcome, "task_ref": task}

        portfolio = Portfolio()
        owner = SimpleNamespace(graph=Graph(), owner_actor=object(), evidence_payload_resolver=object(),
                                assignments=SimpleNamespace(get=lambda ref: SimpleNamespace(ref=manager_ref)))
        server = SimpleNamespace(run_id="perch-stage2", owner=owner, store=object(), portfolio=portfolio,
                                 state={"assignment_ref": manager_ref.to_dict(), "manager": "perch-stage2-manager",
                                        "manager_generation": 1})
        view = SimpleNamespace(server=server, _refresh_refs=lambda: calls.append("refresh"))
        context = {"view": view, "task": SimpleNamespace(ref=task_ref, payload={"alias": "A"}),
                   "project_ref": project_ref.to_dict()}
        landing = {"landed": True,
                   "assessment_results": [Ref("owner", "assessment.result", "result-A", "rev-1").to_dict()],
                   "acceptances": [Ref("owner", "assessment.decision", "decision-A", "rev-1").to_dict()]}
        modules = {"herzchen": ModuleType("herzchen"), "herzchen.contracts": ModuleType("herzchen.contracts"),
                   "herzchen.domains": ModuleType("herzchen.domains"),
                   "herzchen.domains.assessment": ModuleType("herzchen.domains.assessment")}
        modules["herzchen.contracts"].ResourceRef = Ref
        modules["herzchen.domains.assessment"].AssessmentModule = Assessment
        with mock_patch.dict(sys.modules, modules):
            result = self.launcher.complete_landed_canary(context, landing)
            self.assertEqual(result["outcome"], "completed")
            self.assertEqual(calls[0][3]["gate_refs"], landing["acceptances"])
            self.assertEqual(calls[0][3]["candidate_ref"], candidate.to_dict())
            self.assertEqual(calls[0][3]["evidence_refs"], [candidate.to_dict()])
            self.assertEqual(calls[0][3]["actor"], "perch-stage2-manager")
            self.assertEqual(calls[1], "refresh")
            # Seed a refused owner completion. The fake manager must turn red.
            portfolio.outcome = "held"
            with self.assertRaisesRegex(RuntimeError, "manager completion refused"):
                self.launcher.complete_landed_canary(context, landing)
            self.assertEqual(len(calls), 3)
            context["task"] = SimpleNamespace(ref=task_ref, payload={"alias": "C"})
            self.assertIsNone(self.launcher.complete_landed_canary(context, landing))
            self.assertEqual(len(calls), 3)

    def test_task_lifecycle_wait_is_red_until_owner_completes(self):
        status = {"tasks": [{"id": "A", "lifecycle": "completed"}]}
        owner = {"native_capacity": {"active_or_uncertain": 0}}
        self.assertTrue(perch_report.stage2_task_complete(status, owner, "A"))
        status["tasks"][0]["lifecycle"] = "active"
        self.assertFalse(perch_report.stage2_task_complete(status, owner, "A"))

    def test_fake_completion_hook_runs_after_real_landing_and_preserves_refusal(self):
        order = []
        context = {"task": SimpleNamespace(payload={"alias": "A"})}

        class Port:
            def __init__(self):
                self.inner = SimpleNamespace(_assignment_context=lambda assignment: context)
                self.executor = lambda: lambda operation: operation()

            def call(self, operation, assignment, args, *, feedback):
                order.append("landing")
                return {"landed": args["landed"]}

        module = ModuleType("otto.hostctl.product_service")
        module._OwnerExecutorPort = Port
        modules = {"otto": ModuleType("otto"), "otto.hostctl": ModuleType("otto.hostctl"),
                   "otto.hostctl.product_service": module}
        with mock_patch.dict(sys.modules, modules), mock_patch.object(
                self.launcher, "complete_landed_canary", side_effect=lambda ctx, landing:
                order.append("completion") or {"outcome": "completed"}):
            self.launcher.install_fake_completion()
            port = Port()
            landed = port.call("worker-done", "assignment", {"landed": True}, feedback=False)
            self.assertEqual(landed["bootstrap_completion"]["outcome"], "completed")
            self.assertEqual(order, ["landing", "completion"])
            refused = port.call("worker-done", "assignment", {"landed": False}, feedback=False)
            self.assertEqual(refused, {"landed": False})
            self.assertEqual(order, ["landing", "completion", "landing"])


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
# event unrecorded; a staging that never came up has no Store to read, so its Store and lifecycle checks skip.
EXPECTED_RED = {
    "leak": {"no-leaked-process"},
    "lab": {"labs-left-behind", "timeline-events"},
    "pool": {"harness-pool-within-limit"},
    "timeline": {"timeline-events"},
    "staging": {"staging-ready"},
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

class PerchExitStatus(unittest.TestCase):
    """A fatal error inside perch.sh must not exit 0. On bash 3.2 the EXIT trap's last command
    replaced the status, so stage 1 died on an unbound variable, wrote no report and exited 0
    (16 Oct). A copy of the real script with an unset variable read right after the trap must fail."""

    def test_a_fatal_error_is_not_exit_0(self):
        text = PERCH.read_text()
        marker = "run_stage() {  # STAGE"  # inside a function, where bash 3.2 lost the status
        self.assertIn(marker, text)
        tmp = Path(tempfile.mkdtemp(prefix="perchexit-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        boot = tmp / "bootstrap"
        shutil.copytree(PERCH.parent, boot)  # perch.sh sources its siblings
        copy = boot / "perch.sh"
        copy.write_text(text.replace(marker, marker + '\n: "$PERCH_TEST_UNSET_VARIABLE"', 1))
        r = subprocess.run(["bash", str(copy), "1"], cwd=tmp, capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "PERCH_TEST_UNSET_VARIABLE"})
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.returncode, 70, r.stdout + r.stderr)  # the trap's verdict, not bash's 0
        self.assertIn("PERCH_TEST_UNSET_VARIABLE", r.stderr)

    def test_init_args_expand_when_empty(self):
        # Without --fake the array is empty; bash 3.2 under set -u calls "${a[@]}" unbound.
        self.assertIn('${INIT_ARGS[@]+"${INIT_ARGS[@]}"}', PERCH.read_text())
