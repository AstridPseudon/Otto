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


def short_temp_root():
    """Keep nested staging socket paths below macOS's UNIX-domain socket limit."""
    return Path(tempfile.mkdtemp(prefix="p-", dir="/private/tmp")).resolve()


def stage2_worker_prompt(alias, *, linked_task=""):
    brief = {"operating_core": {"role": "worker",
                                "priorities": [{"id": alias.lower(), "text": "Canary dispatch " + alias}]},
             "instruction_contract": {
        "objective": "Implement the delegated " + alias + " outcome",
        "task_ref": {"authority": "owner", "kind": "work.task", "id": "task-" + alias,
                     "revision": "rev-1"}},
             "context": {"project_state": {"tasklist": linked_task}}}
    return ('Verified owner context.\n<otto-resource-brief sha256="' + "0" * 64 + '">\n'
            + json.dumps(brief, sort_keys=True, separators=(",", ":"))
            + '\n</otto-resource-brief>\n')

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
                   "dependencies": ["B"] if name == "C" else [],
                   "metadata_namespace": {"otto.plan": {"repo": "toy", "branch": "canon/main", "route": "normal"}}}
                  for name in tasks]
    criteria = {name: {"authority": "owner", "kind": "assessment.criterion",
                       "id": "criterion-" + name, "revision": "rev-1"} for name in tasks}
    scopes = {name: {"task_ref": task_refs[name],
                     "scope_ref": {"authority": "owner", "kind": "assessment.scope",
                                   "id": "scope-" + name, "revision": "rev-1"},
                     "criterion_refs": [criteria[name]]} for name in tasks}
    status_tasks = [{"id": name, "repo": "toy", "branch": "canon/main",
                     "depends_on": 1 if name == "C" else 0,
                     "dispatch": {"state": "admitted", "reason": None},
                     "required_assessment_scopes": [{"ref": scopes[name]["scope_ref"],
                         "criteria": scopes[name]["criterion_refs"],
                         "criterion_definitions": [{"id": criteria[name]["id"],
                             "source_alias": "C-" + name, "definition": "accepted check passes"}]}]}
                    for name in tasks]
    values = {
        "config.json": {"stage": "2", "scenarios": ["admit-and-dispatch"], "staging_restart": 0,
                        "tasks": [], "pool_limit": 1, "manager_reserve": 1,
                        "stage2_tasks": list(tasks), "stage2_admitted": list(tasks),
                        "stage2_dependencies": {"A": [], "B": [], "C": ["B"]},
                        "stage2_expected_completed": ["A", "B"], "stage2_kill_task": "C"},
        "notes.json": {"admit-and-dispatch": "ran"},
        "stage2-project-status.json": {"outcome": "read", "documents": documents, "tasks": status_tasks},
        "stage2-plan-save.input.json": {"tasks": plan_tasks},
        "stage2-plan-save.json": {"outcome": "saved", "task_refs": task_refs},
        "stage2-activation.json": {"activation": {"steps": {"tasks": {"task_refs": task_refs},
                                         "assessment_scopes": list(scopes.values())}}},
        "stage2-review-ref.json": review_ref,
        "stage2-observations.json": {
            "dispatch": {"dispatched": list(tasks), "records": [
                {"alias": name, "admitted": True, "ready": True} for name in tasks]},
            "capacity": {"pool_peak": 1, "manager_reserve_remaining": 1},
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
            "task_ref": {**task_refs[name], "revision": "rev-admitted-" + name}}), encoding="utf-8")
    log = [{"task": task_refs[name]["id"], "revision": task_refs[name]["revision"],
            "review": review_ref["id"], "prover_result": "approved", "outcome": "admitted"} for name in tasks]
    log.append({"task": "task-C", "revision": "rev-C-edit", "review": review_ref["id"],
                "prover_result": "approved", "outcome": "admitted"})
    (raw / "stage2-operator-admission.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in log), encoding="utf-8")
    events = []
    for alias, tick in (("A", "00.300000"), ("B", "00.400000")):
        events.append({"task_id": "task-" + alias, "alias": alias, "assignment_id": None,
                       "event_type": "work.revised", "stream": "work:task-" + alias,
                       "recorded_at": "2026-10-17T10:00:" + tick + "Z",
                       "subject": {"kind": "work.task", "id": "task-" + alias},
                       "effects": {"result_payload": {"metadata_namespaces": {"work.admission": {
                           "revision": "rev-" + alias}}}}, "value": None})
    events.extend([
        {"task_id": "task-C", "alias": "C", "assignment_id": None,
         "event_type": "work.revised", "stream": "work:task-C",
         "recorded_at": "2026-10-17T10:00:00.100000Z",
         "subject": {"kind": "work.task", "id": "task-C"},
         "effects": {"result_payload": {"metadata_namespaces": {"work.admission": {
             "revision": "rev-C"}}}}, "value": None},
        {"task_id": None, "alias": None, "assignment_id": None,
         "event_type": "work.project-sheet.applied", "stream": "work:project-canary",
         "recorded_at": "2026-10-17T10:00:00.200000Z",
         "subject": {"kind": "work.project", "id": "project-canary"},
         "effects": {"child_refs": [{"kind": "work.task", "id": "task-C", "revision": "rev-C-edit"}],
                     "history_summary": {"facets": [{"subject": {"kind": "work.task", "id": "task-C",
                                                       "revision": "rev-C-edit"},
                                                    "changed_fields": ["instructions"]}]}},
         "value": None},
    ])
    for index, alias in enumerate(tasks):
        task_id, assignment_id = "task-" + alias, "assignment-" + alias
        when = 1 + index * 3
        events.append({"task_id": task_id, "alias": alias, "assignment_id": assignment_id,
                       "event_type": "work.assignment.dispatched", "stream": "dispatch:" + assignment_id,
                       "recorded_at": "2026-10-17T10:00:%02dZ" % when,
                       "subject": {"kind": "wrk.dispatch", "id": "dispatch-" + alias}, "effects": {}, "value": None})
        if alias != "C":
            events.append({"task_id": task_id, "alias": alias, "assignment_id": assignment_id,
                           "event_type": "work.result.appended", "stream": "result:" + assignment_id,
                           "recorded_at": "2026-10-17T10:00:%02dZ" % (when + 1),
                           "subject": {"kind": "wrk.result", "id": "result-" + alias}, "effects": {},
                           "value": {"lab_commit": "commit-" + alias, "task_ref": {"id": task_id},
                                     "assignment_id": assignment_id}})
            events.append({"task_id": task_id, "alias": alias, "assignment_id": None,
                           "event_type": "work.revised", "stream": "work:" + task_id,
                           "recorded_at": "2026-10-17T10:00:%02dZ" % (when + 2),
                           "subject": {"kind": "work.task", "id": task_id},
                           "effects": {"completion": {"disposition": "accepted"}}, "value": None})
    events.append({"task_id": "task-C", "alias": "C", "assignment_id": None,
                   "event_type": "work.revised", "stream": "work:task-C",
                   "recorded_at": "2026-10-17T10:00:06.700000Z",
                   "subject": {"kind": "work.task", "id": "task-C"},
                   "effects": {"result_payload": {"metadata_namespaces": {"work.admission": {
                       "revision": "rev-C-edit"}}}}, "value": None})
    extra = {
        "stage2-store-events.json": {"error": None, "tasks": {"task-" + a: a for a in tasks},
            "assignments": {"assignment-" + a: "task-" + a for a in tasks},
            "revisions": {"task-A": [{"revision": "rev-admitted-A", "admitted_revision": "rev-A"}],
                          "task-B": [{"revision": "rev-admitted-B", "admitted_revision": "rev-B"}],
                          "task-C": [
                {"revision": "rev-C", "instructions": "Canary dispatch C", "reviewed_digest": "old"},
                {"revision": "rev-C-edit", "instructions": "Canary dispatch C (post-admission edit)",
                 "reviewed_digest": "new"},
                {"revision": "rev-C-meta", "instructions": "Canary dispatch C (post-admission edit)",
                 "reviewed_digest": "new", "admitted_revision": "rev-C-edit"}]}, "events": events},
        "stage2-dispatch-status.json": {"tasks": [
            {"id": "A", "lifecycle": "completed", "dispatch": {"state": "landed"}},
            {"id": "B", "lifecycle": "completed", "dispatch": {"state": "landed"}},
            {"id": "C", "lifecycle": "pending", "dispatch": {"state": "unknown"}}]},
        "stage2-instruction-edit-C.input.json": {"tasks": [{"id": "C", "instructions":
            "Canary dispatch C (post-admission edit)"}]},
        "stage2-instruction-edit-C.json": {"outcome": "saved", "project_ref": {"id": "project-canary"}, "task_refs": {
            "C": {**task_refs["C"], "revision": "rev-C-edit"}}},
        "stage2-edited-C-no-launch.json": {"tasks": [
            {"id": "B", "lifecycle": "completed"},
            {"id": "C", "lifecycle": "pending", "dispatch": {"state": "admitted"}}]},
        "stage2-edited-C-owner.json": {"projection_at": "2026-10-17T10:00:06.500000Z",
                                        "native_capacity": {"active_or_uncertain": 0},
                                        "manager_turns": {"active": 0}},
        "stage2-metadata-only-C.json": {"outcome": "admitted", "admitted_revision": "rev-C-edit",
                                          "task_ref": {**task_refs["C"], "revision": "rev-C-meta"}},
        "stage2-dispatch-C-project.json": {"tasks": [{"id": "C", "dispatch": {"state": "launched"}}]},
        "stage2-installation.json": {"capacity": {"turn_units": 1, "manager_reserve": 1}},
        "stage2-contention-owner.json": {"projection_at": "2026-10-17T10:00:02.500000Z",
            "native_capacity": {"worker_limit": 1, "active_or_uncertain": 2},
            "manager_turns": {"active": 1}, "manager_turn_active": True},
        "stage2-contention-project.json": {"tasks": [{"id": "A", "dispatch": {"state": "launched"}},
                                                  {"id": "B", "dispatch": {"state": "admitted"}}]},
        "stage2-manager-start.json": {"outcome": "pending"},
        "stage2-repository-map.json": {"repositories": {"toy": "/tmp/perch/canon"}},
        "stage2-owner-labs-before.json": {"root": "/tmp/perch/canon.otto-labs", "entries": [],
                                          "labs": [], "unexpected": [], "exists": False},
        "stage2-owner-labs-after.json": {"root": "/tmp/perch/canon.otto-labs", "entries": [],
                                         "labs": [], "unexpected": [], "exists": True},
    }
    for name, value in extra.items():
        (raw / name).write_text(json.dumps(value), encoding="utf-8")
    (raw / "stage2-owner-pid.txt").write_text("123\n", encoding="utf-8")
    for label in ("before", "after"):
        (raw / ("stage2-fds-" + label + ".txt")).write_text(
            "COMMAND PID USER FD TYPE\n" + "".join("python 123 user %d txt\n" % n for n in range(5)),
            encoding="utf-8")
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
        self.tmp = short_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_canary_repo(self, name):
        canon = self.tmp / name / "canon"
        canon.mkdir(parents=True)
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        start = shell.index("make_canon() {")
        end = shell.index("\n}\n", start) + len("\n}")
        script = 'CANARY="$1"; CANON="$2"\n' + shell[start:end] + "\nmake_canon\n"
        subprocess.run(["bash", "-c", script, "--", str(BOOTSTRAP / "canary"), str(canon)],
                       check=True, capture_output=True, text=True)
        return canon

    def test_canary_first_commit_keeps_manager_marker_out_of_canon_status(self):
        canon = self.make_canary_repo("manager-marker")
        committed_ignore = subprocess.run(["git", "-C", str(canon), "show", "HEAD:.gitignore"],
                                          check=True, capture_output=True, text=True).stdout
        self.assertIn(".perch-*.pid\n", committed_ignore)
        marker = canon / ".perch-manager.pid"
        marker.write_text("4242\n", encoding="utf-8")
        status = subprocess.run(["git", "-C", str(canon), "status", "--porcelain"],
                                check=True, capture_output=True, text=True)
        self.assertEqual(status.stdout, "")

    def test_landed_canary_lab_commit_contains_no_worker_marker(self):
        canon = self.make_canary_repo("landed-marker")
        lab = canon.parent / "canon.otto-labs" / "branch-key" / "task-A"
        subprocess.run(["git", "-C", str(canon), "worktree", "add", "-q", "-b", "lab/A",
                        str(lab), "canon/main"], check=True, capture_output=True, text=True)
        marker = lab / ".perch-worker-A.pid"
        marker.write_text("4242\n", encoding="utf-8")
        (lab / "README.md").write_text("# landed canary change\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(lab), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(lab), "-c", "user.name=perch-canary",
                        "-c", "user.email=perch-canary@localhost", "commit", "-q", "-m", "Worker A"],
                       check=True, capture_output=True, text=True)
        lab_tree = subprocess.run(["git", "-C", str(lab), "ls-tree", "-r", "--name-only", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.splitlines()
        self.assertNotIn(marker.name, lab_tree)
        subprocess.run(["git", "-C", str(canon), "-c", "user.name=perch-canary",
                        "-c", "user.email=perch-canary@localhost", "merge", "-q", "--no-ff", "lab/A"],
                       check=True, capture_output=True, text=True)
        tree = subprocess.run(["git", "-C", str(canon), "ls-tree", "-r", "--name-only", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.splitlines()
        self.assertIn("README.md", tree)
        self.assertNotIn(marker.name, tree)

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

    def test_stage_two_canary_declares_two_ready_tasks_and_edited_c(self):
        project = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))
        stage = project["stages"]["2"]
        self.assertEqual(stage["tasks"], ["A", "B", "C"])
        self.assertEqual(stage["admission"]["admitted"], ["A", "B", "C"])
        self.assertEqual(stage["dependencies"], {"A": [], "B": [], "C": ["B"]})
        self.assertEqual(stage["expected_completed"], ["A", "B"])
        self.assertEqual(stage["kill_task"], "C")
        self.assertEqual(stage["scenarios"], ["admit-and-dispatch"])
        self.assertEqual(stage["capacity"], {"turn_units": 1, "manager_reserve": 1,
                                             "heavy_headroom": 1, "worker_floor": 1})
        self.assertEqual(stage["pool_limit"], stage["capacity"]["turn_units"])
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
        self.assertEqual([task["dependencies"] for task in saved["tasks"]], [[], [], ["B"]])
        self.assertTrue(all(task["fields"]["check"]["argv"] == ["/usr/bin/true"] for task in saved["tasks"]))
        self.assertTrue(all(task["metadata_namespace"]["otto.plan"] ==
                            {"repo": "toy", "branch": "canon/main", "route": "normal"}
                            for task in saved["tasks"]))
        raw = clean_stage2_raw(self.tmp / "stage2-plan-fault")
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "pass")
        patch(raw, "stage2-plan-save.input.json", lambda value: value["tasks"][0]["fields"].pop("check"))
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "fail")

    def test_stage_two_product_scope_and_operator_admission_keep_exact_task_pins(self):
        raw = clean_stage2_raw(self.tmp / "stage2-scope-fault")
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "pass")
        patch(raw, "stage2-activation.json", lambda value: value["activation"]["steps"][
            "assessment_scopes"][0]["task_ref"].update(id="another-task"))
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "fail")
        raw = clean_stage2_raw(self.tmp / "stage2-status-scope-fault")
        patch(raw, "stage2-project-status.json", lambda value: value["tasks"][0][
            "required_assessment_scopes"][0]["criteria"][0].update(id="another-criterion"))
        self.assertEqual(statuses(raw)["stage2-canary-valid"], "fail")
        raw = clean_stage2_raw(self.tmp / "stage2-admission-pin-fault")
        patch(raw, "stage2-admit-A.json", lambda value: value["task_ref"].update(id="another-task"))
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
        frame = {"message": {"content": [{"text": stage2_worker_prompt("A")}]}}
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

        frame = {"message": {"content": [{"text": stage2_worker_prompt("C")}]}}
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

    def test_fake_claude_owner_turns_hold_in_discoverable_labs_without_staging_env(self):
        import contextlib
        import io
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        canary = self.tmp / "perch-canary" / "2-20261017T184257Z"
        cases = (("A", canary / "canon.otto-labs" / "branch-key" / "task-A", ".perch-worker-A.pid"),
                 ("B", canary / "canon.otto-labs" / "branch-key" / "task-B", ".perch-worker-B.pid"),
                 ("manager", canary / "canon", ".perch-manager.pid"))
        original_cwd = os.getcwd()
        try:
            for role, cwd, marker_name in cases:
                with self.subTest(role=role):
                    cwd.mkdir(parents=True, exist_ok=True)
                    os.chdir(cwd)
                    prompt = ("Manager turn for perch-stage2" if role == "manager"
                              else stage2_worker_prompt(role))
                    frame = {"message": {"content": [{"text": prompt}]}}
                    argv = ["perch-fake-claude", "--model", "claude-haiku-5-5", "--tools", "Read,Write"]
                    with mock_patch.dict(os.environ, {}, clear=True), \
                            mock_patch.object(sys, "argv", argv), \
                            mock_patch.object(sys, "stdin", io.StringIO(json.dumps(frame) + "\n")), \
                            mock_patch.object(launcher.signal, "signal", lambda *_: None), \
                            mock_patch.object(launcher.signal, "pause", side_effect=RuntimeError("turn held")), \
                            contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(RuntimeError, "turn held"):
                            launcher.main()
                    marker = cwd / marker_name
                    self.assertEqual(marker.read_text(encoding="utf-8").strip(), str(os.getpid()))
                    found = subprocess.run(["find", str(canary), "-name", marker_name,
                                            "-print", "-quit"], check=True, capture_output=True,
                                           text=True)
                    self.assertEqual(found.stdout.strip(), str(marker))
        finally:
            os.chdir(original_cwd)

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
                        mock_patch.object(launcher, "done_tool", done), \
                        mock_patch.object(launcher.signal, "pause", lambda: self.fail("A/B entered C's kill hold")), \
                        contextlib.redirect_stdout(output):
                    rc = launcher.main()
                return rc, [json.loads(line) for line in output.getvalue().splitlines()]

            rc, events = turn("Initialize this session only. Do not use tools or do task work. Return READY.",
                              lambda _: self.fail("initializer called done"))
            self.assertEqual(rc, 0)
            self.assertEqual(events[-1]["result"], "READY")
            self.assertEqual([event["type"] for event in events], ["system", "user", "result"])
            prompt_a = stage2_worker_prompt("A", linked_task="Canary dispatch C")
            with mock_patch.object(launcher, "canary_alias",
                                   lambda prompt: "C" if "Canary dispatch C" in prompt else "A"):
                with self.assertRaisesRegex(AssertionError, "A/B entered C's kill hold"):
                    turn(prompt_a, lambda _: {"ok": True, "result": {"landed": True}})
            rc, events = turn(prompt_a, lambda _: {"ok": True, "result": {"landed": True}})
            self.assertEqual(rc, 0)
            self.assertEqual(events[0]["permissionMode"], "dontAsk")
            self.assertEqual(events[0]["mcp_servers"], ["otto"])
            self.assertIn("mcp__otto__done", events[0]["tools"])
            self.assertEqual([block["name"] for event in events if event["type"] == "assistant"
                              for block in event["message"]["content"]], ["Write", "mcp__otto__done"])
            with mock_patch.object(sys, "path", [str(ROOT / "src"), *sys.path]):
                from herzchen.fleet.hosts.claude import ClaudeStream
            parser = ClaudeStream(prompt=prompt_a, cwd=str(lab.resolve()),
                                  model="claude-haiku-5-5", tools=("Read", "Write"),
                                  mcp_servers=("otto",),
                                  mcp_tools=("mcp__otto__task", "mcp__otto__check", "mcp__otto__done"),
                                  permission_mode="dontAsk")
            for event in events:
                parser.feed(json.dumps(event).encode("utf-8"))
            self.assertEqual(parser.finish(rc)["outcome"], "succeeded")
            self.assertTrue(any(lab.glob("perch-worker-*.txt")))
            def red(_):
                raise RuntimeError("seeded done refusal: " + "x" * 2100)
            with contextlib.redirect_stderr(io.StringIO()):
                rc, events = turn(stage2_worker_prompt("B"), red)
            self.assertEqual(rc, 1)
            self.assertEqual(events[-1]["subtype"], "error_during_execution")
            self.assertTrue(events[-1]["is_error"])
            self.assertTrue(events[-1]["result"].startswith("seeded done refusal:"))
            self.assertEqual(len(events[-1]["result"]), 2000)
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
            (raw / ("stage2-admit-" + alias + ".json")).write_text(json.dumps(
                {"outcome": "admitted", "admitted_revision": refs[alias]["revision"]}), encoding="utf-8")
            (raw / ("stage2-dispatch-" + alias + ".json")).write_text(json.dumps({
                "outcome": "read", "tasks": [{"id": alias, "repo": "toy", "branch": "canon/main",
                    "dispatch": {"state": "launched", "reason": None}}]}), encoding="utf-8")
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
            "tasks": [{"task_id": "assignment-" + alias, "scope_task_id": refs[alias]["id"],
                       "events": [{"stream": "dispatch:assignment-" + alias,
                                   "event_type": "work.assignment.dispatched"}]}
                      for alias in ("A", "B", "C")],
            "work_tasks": [{"alias": alias, "admitted_revision": refs[alias]["revision"]}
                           for alias in ("A", "B", "C")]}), encoding="utf-8")
        (raw / "stage2-current-activation.json").write_text(json.dumps(
            {"activation": {"steps": {"tasks": {"task_refs": {
                **refs, "C": {**refs["C"], "revision": "rev-C-edit"}}}}}}), encoding="utf-8")
        projected = perch_report.stage2_observations(raw)
        self.assertEqual(projected["dispatch"]["dispatched"], ["A", "B", "C"])
        self.assertTrue(all(row["dispatch_state"] == "launched" for row in projected["dispatch"]["records"]))
        self.assertEqual(projected["store_snapshots"][-1]["dispatch_events"], 3)
        self.assertNotIn("unadmitted_refusal", projected)
        patch(raw, "stage2-dispatch-B.json", lambda value: value["tasks"][0]["dispatch"].update(
            state="failed", reason="repo unavailable"))
        red = perch_report.stage2_observations(raw)
        self.assertEqual(red["dispatch"]["dispatched"], ["A", "C"])
        self.assertEqual(red["store_snapshots"][-1]["dispatch_events"], 3)
        raw = clean_stage2_raw(self.tmp / "stage2-unlinked-store-dispatch")
        (raw / "stage2-observations.json").unlink()
        for alias in ("A", "B", "C"):
            (raw / ("stage2-dispatch-" + alias + ".json")).write_text(json.dumps({
                "outcome": "read", "tasks": [{"id": alias, "repo": "toy", "branch": "canon/main",
                    "dispatch": {"state": "launched", "reason": None}}]}), encoding="utf-8")
            (raw / ("stage2-dispatch-" + alias + "-project.json")).write_text(json.dumps({
                "tasks": [{"id": prereq, "lifecycle": "completed"} for prereq in ("A", "B")]}),
                encoding="utf-8")
        (raw / "timeline.json").write_text(json.dumps({"tasks": [{"task_id": "assignment-X",
            "scope_task_id": "unrelated-task", "events": [{"stream": "dispatch:assignment-X",
                "event_type": "work.assignment.dispatched"}]}]}), encoding="utf-8")
        self.assertEqual(perch_report.stage2_observations(raw)["store_snapshots"][-1]["dispatch_events"], 3)
        patch(raw, "stage2-store-events.json", lambda value: value.update(events=[
            row for row in value["events"] if not (row["alias"] == "B" and
                                                   row["event_type"] == "work.assignment.dispatched")]))
        self.assertEqual(perch_report.stage2_observations(raw)["store_snapshots"][-1]["dispatch_events"], 2)

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
                    "stage2_dependencies": {"A": [], "B": [], "C": ["B"]},
                    "stage2_expected_completed": ["A", "B"], "stage2_kill_task": "C"}), encoding="utf-8")
        (raw / "notes.json").write_text(json.dumps({"admit-and-dispatch": "failed: COMPOSEFLEET prerequisites are absent from the staging tree"}), encoding="utf-8")
        got = {row["name"]: row for row in perch_report.assertions(raw)}
        self.assertEqual(got["admit-and-dispatch-ran"]["status"], "fail")
        self.assertIn("did not run", got["admit-and-dispatch-ran"]["detail"])
        self.assertIn("failed:", json.loads((raw / "notes.json").read_text(encoding="utf-8"))["admit-and-dispatch"])
        self.assertEqual(got["admitted-ready-dependency-order"]["status"], "skip")

    def test_stage_two_report_names_real_check_and_fake_presence(self):
        raw = clean_stage2_raw(self.tmp / "stage2-report-contract")
        (raw / "timeline.json").write_text(json.dumps({"store_events": 0, "tasks": [], "error": None}),
                                           encoding="utf-8")
        perch_report.cmd_init(Namespace(
            raw=str(raw), project=str(BOOTSTRAP / "canary" / "project.json"), stage="2", fake=True,
            faults="", staging_restart=0, staging_sha="tree", canon_main_sha="canon",
            started_at="start", stage_root="/staging"))
        config = json.loads((raw / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["check"], "/usr/bin/true")
        result = {row["name"]: row for row in perch_report.assertions(raw)}
        self.assertNotIn("harness-pool-within-limit", result)

        report = self.tmp / "stage2-report.md"
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(report)))
        text = report.read_text(encoding="utf-8")
        self.assertIn("check per task: `/usr/bin/true`", text)
        self.assertIn("--fake uses a fake worker and also fakes operator presence", text)
        self.assertNotIn("## Pool units over time", text)

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
                if fault not in {"admit_order", "unadmitted", "reserve"}:
                    self.assertEqual({name for name, status in got.items() if status == "fail"}, {target}, got)

    def test_stage_two_direct_store_events_refuse_false_order_and_missing_timeline_events(self):
        cases = (
            ("early-dependent-dispatch", "admitted-ready-dependency-order", "stage2-store-events.json",
             lambda value: next(row for row in value["events"] if row["alias"] == "C"
                                and row["event_type"] == "work.assignment.dispatched").update(
                                    recorded_at="2026-10-17T10:00:05Z")),
            ("missing-dispatch", "timeline-events", "stage2-store-events.json",
             lambda value: value.update(events=[row for row in value["events"] if not (
                 row["alias"] == "A" and row["event_type"] == "work.assignment.dispatched")])),
            ("missing-landing", "timeline-events", "stage2-store-events.json",
             lambda value: value.update(events=[row for row in value["events"] if not (
                 row["alias"] == "A" and row["event_type"] == "work.result.appended")])),
            ("missing-completion", "timeline-events", "stage2-store-events.json",
             lambda value: value.update(events=[row for row in value["events"] if not (
                 row["alias"] == "B" and (row.get("effects") or {}).get("completion"))])),
            ("wrong-assignment", "timeline-events", "stage2-store-events.json",
             lambda value: next(row for row in value["events"] if row["alias"] == "A"
                                and row["event_type"] == "work.result.appended").update(
                                    assignment_id="assignment-B")),
        )
        for label, assertion, file, mutate in cases:
            with self.subTest(label=label):
                raw = clean_stage2_raw(self.tmp / label)
                self.assertEqual(statuses(raw)[assertion], "pass")
                patch(raw, file, mutate)
                self.assertEqual(statuses(raw)[assertion], "fail")
                if label.startswith("missing-"):
                    detail = next(row["detail"] for row in perch_report.assertions(raw)
                                  if row["name"] == assertion)
                    self.assertIn(label.split("-")[1], detail)

    def test_stage_two_missing_final_status_keeps_store_completion_observations(self):
        raw = clean_stage2_raw(self.tmp / "missing-final-status")
        (raw / "stage2-dispatch-status.json").unlink()
        failures = perch_report.stage2_timeline_failures(raw, json.loads((raw / "config.json").read_text()))
        self.assertTrue(any("final product status snapshot missing" in detail
                            and "A, B" in detail for detail in failures), failures)
        self.assertFalse(any("has no landed and completed product status" in detail for detail in failures), failures)
        patch(raw, "stage2-store-events.json", lambda value: value.update(events=[
            row for row in value["events"] if not (row.get("alias") == "A"
                                                    and row.get("event_type") == "work.result.appended")]))
        failures = perch_report.stage2_timeline_failures(raw, json.loads((raw / "config.json").read_text()))
        self.assertTrue(any("A missing landing observation" in detail for detail in failures), failures)

    def test_stage_two_instruction_edit_requires_exact_project_sheet_event(self):
        cases = (
            ("missing-sheet", lambda value: value.update(events=[row for row in value["events"]
                if row.get("event_type") != "work.project-sheet.applied"])),
            ("wrong-child-revision", lambda value: next(row for row in value["events"]
                if row.get("event_type") == "work.project-sheet.applied")["effects"]["child_refs"][0]
                .update(revision="rev-other")),
            ("wrong-project-stream", lambda value: next(row for row in value["events"]
                if row.get("event_type") == "work.project-sheet.applied").update(stream="work:other-project")),
            ("no-instruction-change", lambda value: next(row for row in value["events"]
                if row.get("event_type") == "work.project-sheet.applied")["effects"]["history_summary"]
                ["facets"][0].update(changed_fields=["title"])),
            ("early-C-dispatch", lambda value: next(row for row in value["events"]
                if row.get("alias") == "C" and row.get("event_type") == "work.assignment.dispatched")
                .update(recorded_at="2026-10-17T10:00:06.600000Z")),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                raw = clean_stage2_raw(self.tmp / label)
                self.assertEqual(statuses(raw)["unadmitted-revision-refused"], "pass")
                patch(raw, "stage2-store-events.json", mutate)
                self.assertEqual(statuses(raw)["unadmitted-revision-refused"], "fail")

    def test_stage_two_store_capture_keeps_project_sheet_child_and_changed_fields(self):
        spec = importlib.util.spec_from_file_location("perch_stage2_evidence", BOOTSTRAP / "perch_stage2_evidence.py")
        evidence = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evidence)
        sys.path.insert(0, str(ROOT / "src"))
        from herzchen.contracts import ResourceRef
        from herzchen.kernel import Store
        from otto.hostctl import owner as owner_module

        task_ref = ResourceRef("owner", "work.task", "task-C", "rev-3")
        task = SimpleNamespace(ref=task_ref, version=3,
                               payload={"alias": "C", "instructions": "Canary dispatch C (post-admission edit)"})
        sheet_event = SimpleNamespace(event_type="work.project-sheet.applied", stream="work:project-canary",
            recorded_at="2026-10-17T10:00:00.200000Z",
            subject=ResourceRef("owner", "work.project", "project-canary", "rev-5"),
            effects={"child_refs": [task_ref], "history_summary": {"facets": [
                {"subject": task_ref, "changed_fields": ["instructions"]}]}})

        class StoreStub:
            def consumer(self):
                return self

            def read_identity_page(self, *, kind, limit):
                return {"records": [task] if kind == "work.task" else [],
                        "next_cursor": None, "held": False}

            def get_revision(self, _ref):
                return task

            def list_events(self):
                return [sheet_event]

            def close(self):
                pass

        with mock_patch.object(Store, "open", return_value=StoreStub()), \
                mock_patch.object(owner_module, "host_domains", return_value=()):
            receipt = evidence.capture(ROOT / "src", "unused.store", "owner")
        self.assertEqual(len(receipt["events"]), 1)
        captured = receipt["events"][0]
        self.assertEqual(captured["event_type"], "work.project-sheet.applied")
        self.assertEqual(captured["effects"]["child_refs"][0]["revision"], "rev-3")
        self.assertEqual(captured["effects"]["history_summary"]["facets"][0]["changed_fields"],
                         ["instructions"])

    def test_stage_two_store_observation_runs_after_config_and_uses_matching_dispatches(self):
        source = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        init = source.index('"$REPORT_PY" init --raw "$RAW"')
        observe = source.index('"$REPORT_PY" stage2-observations --raw "$RAW"')
        seed = source.index('"$REPORT_PY" seed --raw "$RAW"')
        self.assertLess(init, observe)
        self.assertLess(observe, seed)
        raw = clean_stage2_raw(self.tmp / "store-observation-order")
        for label in ("before", "after"):
            (raw / ("stage2-store-" + label + ".json")).write_text(json.dumps({"integrity": "ok"}))
        final = perch_report.stage2_observations(raw)["store_snapshots"][-1]
        self.assertEqual(final["admitted_tasks"], ["A", "B", "C"])
        self.assertEqual(final["dispatch_events"], 3)
        perch_report.cmd_stage2_observations(Namespace(raw=str(raw)))
        self.assertEqual(statuses(raw)["stage2-store-snapshots"], "pass")
        patch(raw, "stage2-store-events.json", lambda value: value.update(events=[
            row for row in value["events"] if not (row.get("alias") == "B"
                                                    and row.get("event_type") == "work.assignment.dispatched")]))
        self.assertEqual(perch_report.stage2_observations(raw)["store_snapshots"][-1]["dispatch_events"], 2)
        perch_report.cmd_stage2_observations(Namespace(raw=str(raw)))
        self.assertEqual(statuses(raw)["stage2-store-snapshots"], "fail")

    def test_stage_two_product_evidence_refuses_false_capacity_edit_and_metadata_claims(self):
        cases = (
            ("serialized-plan", "stage2-canary-valid", "stage2-plan-save.input.json",
             lambda value: next(row for row in value["tasks"] if row["id"] == "B").update(
                 dependencies=["A"])),
            ("serialized-owner-task", "stage2-canary-valid", "stage2-project-status.json",
             lambda value: next(row for row in value["tasks"] if row["id"] == "B").update(
                 depends_on=1)),
            ("unapplied-installation", "pool-and-manager-reserve-held", "stage2-installation.json",
             lambda value: value["capacity"].update(turn_units=6)),
            ("second-worker-launched", "pool-and-manager-reserve-held", "stage2-contention-project.json",
             lambda value: value["tasks"][1]["dispatch"].update(state="launched")),
            ("manager-absent", "pool-and-manager-reserve-held", "stage2-contention-owner.json",
             lambda value: value.update(manager_turn_active=False)),
            ("early-second-worker", "pool-and-manager-reserve-held", "stage2-store-events.json",
             lambda value: next(row for row in value["events"] if row["alias"] == "B"
                                and row["event_type"] == "work.assignment.dispatched").update(
                                    recorded_at="2026-10-17T10:00:02Z")),
            ("missing-second-admission", "pool-and-manager-reserve-held", "stage2-store-events.json",
             lambda value: value.update(events=[row for row in value["events"] if not (
                 row["alias"] == "B" and row["event_type"] == "work.revised")])),
            ("edited-worker-launched", "unadmitted-revision-refused", "stage2-edited-C-no-launch.json",
             lambda value: value["tasks"][1]["dispatch"].update(state="launched")),
            ("no-instruction-edit", "unadmitted-revision-refused", "stage2-instruction-edit-C.input.json",
             lambda value: value["tasks"][0].update(instructions="Canary dispatch C")),
            ("changed-metadata-content", "metadata-only-write-runnable", "stage2-store-events.json",
             lambda value: value["revisions"]["task-C"][2].update(reviewed_digest="different")),
            ("missing-metadata-write", "metadata-only-write-runnable", "stage2-store-events.json",
             lambda value: value.update(events=[row for row in value["events"] if not (
                 row["alias"] == "C" and row["event_type"] == "work.revised")])),
            ("metadata-still-unlaunched", "metadata-only-write-runnable", "stage2-dispatch-C-project.json",
             lambda value: value["tasks"][0]["dispatch"].update(state="admitted")),
        )
        for label, assertion, file, mutate in cases:
            with self.subTest(label=label):
                raw = clean_stage2_raw(self.tmp / label)
                self.assertEqual(statuses(raw)[assertion], "pass")
                patch(raw, file, mutate)
                self.assertEqual(statuses(raw)[assertion], "fail")

    def test_stage_two_owner_lsof_and_lab_root_refuse_false_claims(self):
        for label, file, mutate, assertion in (
            ("descriptor-growth", "stage2-fds-after.txt",
             lambda value: value + "".join("python 123 user %d txt\n" % n for n in range(5, 9)),
             "owner-descriptors-bounded"),
            ("missing-lsof", "stage2-fds-before.txt", lambda _value: "",
             "owner-descriptors-bounded"),
            ("preexisting-owner-lab", "stage2-owner-labs-before.json",
             lambda value: value["labs"].append("branch-key/leftover"), "labs-left-behind"),
            ("remaining-owner-lab", "stage2-owner-labs-after.json",
             lambda value: value["labs"].append("branch-key/remaining"), "labs-left-behind"),
        ):
            with self.subTest(label=label):
                raw = clean_stage2_raw(self.tmp / label)
                self.assertEqual(statuses(raw)[assertion], "pass")
                if file.endswith(".txt"):
                    path = raw / file
                    path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
                else:
                    patch(raw, file, mutate)
                self.assertEqual(statuses(raw)[assertion], "fail")

    def test_stage_two_owner_lab_snapshot_lists_task_labs_and_retained_C_by_id(self):
        raw = clean_stage2_raw(self.tmp / "owner-labs")
        root = self.tmp / "owner-labs-tree" / "canon.otto-labs"
        before = perch_report.stage2_owner_labs_snapshot(root)
        namespace = root / "68006181e11fc5c4fd81"
        namespace.mkdir(parents=True)
        snapshot = raw / "owner-labs-cli.json"
        subprocess.run([PY, "-I", str(BOOTSTRAP / "perch_report.py"), "stage2-owner-labs",
                        "--root", str(root), "--out", str(snapshot)], check=True, capture_output=True)
        empty = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(empty["entries"], [namespace.name])
        self.assertEqual(empty["labs"], [])
        patch(raw, "stage2-repository-map.json", lambda value: value["repositories"].update(
            toy=str(root).removesuffix(".otto-labs")))
        (raw / "stage2-owner-labs-before.json").write_text(json.dumps(before))
        (raw / "stage2-owner-labs-after.json").write_text(json.dumps(empty))
        self.assertEqual(statuses(raw)["labs-left-behind"], "pass")
        unexpected = namespace / "task-A"
        unexpected.mkdir()
        (raw / "stage2-owner-labs-after.json").write_text(json.dumps(perch_report.stage2_owner_labs_snapshot(root)))
        detail = next(row["detail"] for row in perch_report.assertions(raw)
                      if row["name"] == "labs-left-behind")
        self.assertIn("task-A", detail)
        self.assertEqual(statuses(raw)["labs-left-behind"], "fail")
        unexpected.rmdir()
        retained = namespace / "task-C"
        retained.mkdir()
        (raw / "stage2-owner-labs-after.json").write_text(json.dumps(perch_report.stage2_owner_labs_snapshot(root)))
        (raw / "stage2-killed-worker.json").write_text(json.dumps({
            "pid": 101, "owner_pid": 202, "marker": str(retained / ".perch-worker-C.pid")}))
        self.assertEqual(statuses(raw)["labs-left-behind"], "pass")
        detail = next(row["detail"] for row in perch_report.assertions(raw)
                      if row["name"] == "labs-left-behind")
        self.assertIn("retained recovery lab C", detail)
        self.assertIn("task-C", detail)
        patch(raw, "stage2-dispatch-status.json", lambda value: next(task for task in value["tasks"]
            if task["id"] == "C")["dispatch"].update(state="landed"))
        self.assertEqual(statuses(raw)["labs-left-behind"], "fail")


class FakePresenceLauncherTests(unittest.TestCase):
    def test_fake_owner_launcher_injects_approval_before_product_cli(self):
        spec = importlib.util.spec_from_file_location("perch_fake_presence", BOOTSTRAP / "perch_fake_presence.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        root = short_temp_root()
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

    def test_fake_worker_has_native_entrypoint_and_executes_python_turn(self):
        root = short_temp_root()
        self.addCleanup(shutil.rmtree, root, True)
        launcher = root / "perch-fake-claude"
        shutil.copy2(BOOTSTRAP / "perch_fake_claude.py", root / "perch-fake-claude.py")
        built = subprocess.run(["/usr/bin/cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                                '-DPERCH_PYTHON="' + sys.executable + '"',
                                str(BOOTSTRAP / "perch_fake_claude_launcher.c"), "-o", str(launcher)],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(built.returncode, 0, built.stderr)
        version = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual((version.returncode, version.stdout.strip()), (0, "2.1.293 (Claude Code)"))
        initializer_prompt = "Initialize this session only. Do not use tools or do task work. Return READY."
        initializer_frame = {"message": {"content": [{"text": initializer_prompt}]}}
        initializer = subprocess.run([str(launcher), "--model", "claude-haiku-5-5", "--tools", ""],
                                     input=json.dumps(initializer_frame) + "\n", capture_output=True,
                                     text=True, cwd=root, timeout=10)
        self.assertEqual(initializer.returncode, 0, initializer.stderr)
        with mock_patch.object(sys, "path", [str(ROOT / "src"), *sys.path]):
            from herzchen.fleet.hosts.claude import ClaudeStream
        parser = ClaudeStream(prompt=initializer_prompt, cwd=str(root.resolve()), model="claude-haiku-5-5",
                              tools=(), phase="initializer")
        for line in initializer.stdout.splitlines():
            parser.feed(line.encode("utf-8"))
        self.assertEqual(parser.finish(initializer.returncode)["result"]["result"], "READY")
        frame = {"message": {"content": [{"text": stage2_worker_prompt("A")}]}}
        turn = subprocess.run([str(launcher), "--model", "claude-haiku-5-5", "--tools", "Read,Write"],
                              input=json.dumps(frame) + "\n", capture_output=True, text=True,
                              cwd=root, timeout=10)
        self.assertEqual(turn.returncode, 0, turn.stderr)
        self.assertEqual(json.loads(turn.stdout.splitlines()[-1])["subtype"], "success")
        self.assertEqual(len(list(root.glob("perch-worker-*.txt"))), 1)
        (root / "perch-fake-claude.py").unlink()
        missing = subprocess.run([str(launcher), "--model", "claude-haiku-5-5", "--tools", "Read,Write"],
                                 input=json.dumps(frame) + "\n", capture_output=True, text=True,
                                 cwd=root, timeout=10)
        self.assertNotEqual(missing.returncode, 0)

    def test_product_project_status_is_the_only_dispatch_read(self):
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        wait = __import__("re").search(r"(?ms)^stage2_wait_worker\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(wait)
        self.assertIn('project status --project perch-stage2', wait.group())
        self.assertNotIn('manager --project perch-stage2 status', wait.group())
        self.assertIn('stage2-task-landed', wait.group())
        self.assertIn('if [ "$task" = C ]; then', wait.group())
        self.assertIn('stage2_kill_worker || return $?', wait.group())
        self.assertNotIn('stage2_kill_worker || true', shell)
        source = (BOOTSTRAP / "perch_stage2_owner.py").read_text(encoding="utf-8")
        for removed in ("install_scope_setup", "_seed_scopes", "_seed_admitted_scope",
                        "_refresh_manager_setup", "_status_with_dispatch"):
            self.assertNotIn(removed, source)

        task_ref = {"authority": "owner", "kind": "work.task", "id": "task-A", "revision": "rev-1"}
        activation = {"activation": {"steps": {"tasks": {"task_refs": {"A": task_ref}}}}}
        admission = {"outcome": "admitted", "admitted_revision": "rev-1"}
        status = {"outcome": "read", "tasks": [{"id": "A", "repo": "toy", "branch": "canon/main",
                    "dispatch": {"state": "launched", "reason": None}}]}
        self.assertEqual(perch_report.stage2_dispatch_check(status, activation, admission, "A"),
                         status["tasks"][0])
        perch_report.stage2_dispatch_no_failure(status, "A")
        status["tasks"][0]["dispatch"] = {"state": "failed", "reason": "repo unavailable"}
        with self.assertRaisesRegex(ValueError, "repo unavailable"):
            perch_report.stage2_dispatch_no_failure(status, "A")
        with self.assertRaisesRegex(ValueError, "no retained launched dispatch"):
            perch_report.stage2_dispatch_check(status, activation, admission, "A")
        for alias in ("A", "B"):
            status["tasks"][0]["id"] = alias
            status["tasks"][0]["dispatch"] = {"state": "unknown", "reason": "worker was killed"}
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, "worker was killed"):
                perch_report.stage2_dispatch_no_failure(status, alias)

        status["tasks"][0]["id"] = "C"
        status["tasks"][0]["dispatch"] = {"state": "unknown", "reason": "worker was killed"}
        self.assertIs(perch_report.stage2_dispatch_no_failure(status, "C"), None)
        task_ref_c = {**task_ref, "id": "task-C"}
        activation_c = {"activation": {"steps": {"tasks": {"task_refs": {"C": task_ref_c}}}}}
        admission_c = {"outcome": "admitted", "admitted_revision": "rev-1"}
        self.assertEqual(perch_report.stage2_dispatch_check(status, activation_c, admission_c, "C"),
                         status["tasks"][0])
        private_only = {"outcome": "read", "workers": {"A": {"automatic": True}}}
        with self.assertRaisesRegex(ValueError, "lacks the product task dispatch state"):
            perch_report.stage2_dispatch_no_failure(private_only, "A")

    def test_c_dispatch_kills_held_c_before_waiting_for_empty_capacity(self):
        import re
        import shlex

        root = short_temp_root()
        self.addCleanup(shutil.rmtree, root, True)
        raw = root / "raw"
        raw.mkdir()
        fake_python = root / "python-stub"
        fake_python.write_text("#!/bin/sh\ncase \"$*\" in\n"
                               "  *stage2-dispatch-request*) exit 0 ;;\n"
                               "  *stage2-dispatch-no-failure*) exit 0 ;;\n"
                               "  *stage2-dispatch-check*) exit 0 ;;\n"
                               "  *stage2-task-landed*) exit 0 ;;\n"
                               "  *) echo unexpected report command: \"$*\" >&2; exit 90 ;;\n"
                               "esac\n", encoding="utf-8")
        fake_python.chmod(0o755)
        status = json.dumps({"outcome": "read", "tasks": [{"id": "C", "lifecycle": "active",
            "repo": "toy", "branch": "canon/main", "dispatch": {"state": "launched", "reason": None}}]})
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        wait = re.search(r"(?ms)^stage2_wait_worker\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(wait)
        script = "\n".join((
            "set -euo pipefail",
            "RAW=" + shlex.quote(str(raw)),
            "PY=" + shlex.quote(str(fake_python)),
            "REPORT_PY=unused",
            "sleep() { :; }",
            "stage2_host_client() { printf '%s\\n' " + shlex.quote(status) + "; }",
            "cold_client() { printf '%s\\n' '{\"native_capacity\":{\"active_or_uncertain\":1}}'; }",
            "stage2_kill_worker() { echo kill-C >> \"$RAW/order\"; }",
            wait.group(),
            "stage2_wait_worker claude-code C",
        ))
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((raw / "order").read_text(encoding="utf-8").splitlines(), ["kill-C"])

    def test_held_operator_admission_waits_for_owner_status_then_reuses_request_key(self):
        import re
        import shlex

        root = short_temp_root()
        self.addCleanup(shutil.rmtree, root, True)
        refs = {alias: {"authority": "owner", "kind": "work.task", "id": "task-" + alias,
                        "revision": "rev-" + alias} for alias in ("A", "B", "C")}
        shell = PERCH.read_text(encoding="utf-8")
        admit = re.search(r"(?ms)^stage2_admit_tasks\(\) \{[^\n]*\n.*?^\}\n", shell)
        dispatch = re.search(r"(?ms)^stage2_dispatch_tasks\(\) \{[^\n]*\n.*?^\}\n", shell)
        submit = re.search(r"(?ms)^stage2_submit_admission\(\) \{[^\n]*\n.*?^\}\n", shell)
        boundary = re.search(r"(?ms)^stage2_wait_admission_boundary\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(admit)
        self.assertIsNotNone(dispatch)
        self.assertIsNotNone(submit)
        self.assertIsNotNone(boundary)

        def run(seed_stuck=False):
            raw = root / ("stuck" if seed_stuck else "closed")
            raw.mkdir()
            (raw / "stage2-activation.json").write_text(json.dumps(
                {"activation": {"steps": {"tasks": {"task_refs": refs}}}}), encoding="utf-8")
            (raw / "stage2-review-ref.json").write_text(json.dumps(
                {"authority": "owner", "kind": "dat.content.document",
                 "id": "plan-review-document", "revision": "rev-review"}), encoding="utf-8")
            script = "\n".join((
                "set -uo pipefail",
                "RAW=" + shlex.quote(str(raw)),
                "CANARY=" + shlex.quote(str(BOOTSTRAP / "canary")),
                "PY=" + shlex.quote(sys.executable),
                "REPORT_PY=" + shlex.quote(str(BOOTSTRAP / "perch_report.py")),
                "sleep() { :; }",
                "date() {",
                '  if [ "${SEED_BOUNDARY_STUCK:-0}" != 1 ] || [ "$1" != +%s ]; then command date "$@"; return; fi',
                '  n=$(cat "$RAW/date-calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$RAW/date-calls"',
                '  case "$n" in 1|2|3) echo 1000 ;; 4) echo 1001 ;; *) echo 1180 ;; esac',
                "}",
                "cold_client() {",
                '  if [ "$*" = "service status" ]; then',
                '    n=$(cat "$RAW/status-calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$RAW/status-calls"',
                '    if [ "$n" = 1 ] || [ "${SEED_BOUNDARY_STUCK:-0}" = 1 ]; then',
                '      echo status-busy >> "$RAW/trace"',
                '      printf \'%s\\n\' \'{"state":"serving","outcome":"running","native_capacity":{"active_or_uncertain":1,"holds":[]},"manager_turns":{"active":1},"manager_turn_active":true}\'',
                '    else',
                '      echo status-closed >> "$RAW/trace"',
                '      printf \'%s\\n\' \'{"state":"serving","outcome":"running","native_capacity":{"active_or_uncertain":0,"holds":[]},"manager_turns":{"active":0},"manager_turn_active":false}\'',
                '    fi',
                '    return 0',
                '  fi',
                '  local alias',
                '  case "$*" in *task-A*) alias=A ;; *task-B*) alias=B ;; *task-C*) alias=C ;; *) return 31 ;; esac',
                '  case "$*" in *plan-review-document*rev-review*) ;; *) return 32 ;; esac',
                '  case "$*" in *"--request-key perch-stage2-admit-$alias"*) ;; *) return 33 ;; esac',
                '  echo "admit-$alias:perch-stage2-admit-$alias" >> "$RAW/trace"',
                '  if [ "$alias" = C ] && [ ! -f "$RAW/c-held" ]; then',
                '    : > "$RAW/c-held"',
                '    printf \'%s\\n\' \'{"outcome":"held","reason":"execution-changing operation requires a closed owner boundary","retry":false,"effects_started":false,"provider_called":false}\'',
                '    return 0',
                '  fi',
                '  printf \'{"outcome":"admitted","admitted_revision":"rev-%s"}\\n\' "$alias"',
                "}",
                "stage2_wait_worker() {",
                '  for alias in A B C; do [ -f "$RAW/stage2-admit-$alias.json" ] || return 34; done',
                '  echo "wait-$2" >> "$RAW/trace"',
                "}",
                boundary.group(),
                submit.group(),
                admit.group(),
                dispatch.group(),
                "stage2_admit_tasks && stage2_dispatch_tasks",
            ))
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                    env={**os.environ, "SEED_BOUNDARY_STUCK": "1" if seed_stuck else "0"},
                                    timeout=30)
            return raw, result

        raw, result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((raw / "trace").read_text(encoding="utf-8").splitlines(),
                         ["admit-A:perch-stage2-admit-A", "admit-B:perch-stage2-admit-B",
                          "admit-C:perch-stage2-admit-C", "status-busy", "status-closed",
                          "admit-C:perch-stage2-admit-C", "wait-A", "wait-B", "wait-C"])
        self.assertEqual(json.loads((raw / "stage2-admit-C-attempt-1.json").read_text())["outcome"], "held")
        self.assertEqual(json.loads((raw / "stage2-admit-C-attempt-2.json").read_text())["outcome"], "admitted")
        self.assertEqual((raw / "stage2-admit-C-attempt-1.request-key").read_text(),
                         (raw / "stage2-admit-C-attempt-2.request-key").read_text())
        self.assertEqual(json.loads((raw / "stage2-admit-C.json").read_text())["outcome"], "admitted")
        raw, result = run(seed_stuck=True)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual((raw / "trace").read_text(encoding="utf-8").splitlines(),
                         ["admit-A:perch-stage2-admit-A", "admit-B:perch-stage2-admit-B",
                          "admit-C:perch-stage2-admit-C", "status-busy"])
        self.assertEqual(json.loads((raw / "stage2-admit-C.json").read_text())["outcome"], "held")
        self.assertFalse((raw / "stage2-admit-C-attempt-2.json").exists())
        self.assertIn("boundary stayed open", (raw / "stage2-setup-errors.txt").read_text())

    def test_only_pre_effect_boundary_hold_can_be_retried(self):
        held = {"outcome": "held", "reason": "execution-changing operation requires a closed owner boundary",
                "effects_started": False, "provider_called": False}
        self.assertTrue(perch_report.stage2_admission_held(held))
        for changed in ({"effects_started": True}, {"provider_called": True},
                        {"reason": "other hold"}, {"outcome": "pending"}):
            self.assertFalse(perch_report.stage2_admission_held({**held, **changed}))
        closed = {"state": "serving", "outcome": "running", "native_capacity": {
            "active_or_uncertain": 0, "holds": []}, "manager_turns": {"active": 0},
            "manager_turn_active": False}
        self.assertTrue(perch_report.stage2_owner_boundary_closed(closed))
        self.assertFalse(perch_report.stage2_owner_boundary_closed({**closed,
            "native_capacity": {"active_or_uncertain": 1, "holds": []}}))
        self.assertFalse(perch_report.stage2_owner_boundary_closed({**closed,
            "native_capacity": {"active_or_uncertain": 0, "holds": ["task-A"]}}))
        self.assertFalse(perch_report.stage2_owner_boundary_closed({**closed,
            "native_capacity": {"active_or_uncertain": False, "holds": []}}))

    def test_pending_operator_admission_reads_one_retained_request_without_resending(self):
        import re
        import shlex

        root = short_temp_root()
        self.addCleanup(shutil.rmtree, root, True)
        refs = {alias: {"authority": "owner", "kind": "work.task", "id": "task-" + alias,
                        "revision": "rev-" + alias} for alias in ("A", "B", "C")}
        request_id = "a0ebbb3fece74d328ad1d290385a13ae"
        shell = PERCH.read_text(encoding="utf-8")
        admit = re.search(r"(?ms)^stage2_admit_tasks\(\) \{[^\n]*\n.*?^\}\n", shell)
        dispatch = re.search(r"(?ms)^stage2_dispatch_tasks\(\) \{[^\n]*\n.*?^\}\n", shell)
        submit = re.search(r"(?ms)^stage2_submit_admission\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(admit)
        self.assertIsNotNone(dispatch)
        self.assertIsNotNone(submit)

        def run(seed_bad_id=False, seed_stuck=False):
            raw = root / ("bad-id" if seed_bad_id else "stuck" if seed_stuck else "terminal")
            raw.mkdir()
            (raw / "stage2-activation.json").write_text(json.dumps(
                {"activation": {"steps": {"tasks": {"task_refs": refs}}}}), encoding="utf-8")
            (raw / "stage2-review-ref.json").write_text(json.dumps(
                {"authority": "owner", "kind": "dat.content.document",
                 "id": "plan-review-document", "revision": "rev-review"}), encoding="utf-8")
            script = "\n".join((
                "set -uo pipefail",
                "RAW=" + shlex.quote(str(raw)),
                "CANARY=" + shlex.quote(str(BOOTSTRAP / "canary")),
                "PY=" + shlex.quote(sys.executable),
                "REPORT_PY=" + shlex.quote(str(BOOTSTRAP / "perch_report.py")),
                "REQUEST_ID=" + shlex.quote(request_id),
                "sleep() { :; }",
                "date() {",
                '  if [ "${SEED_PENDING_STUCK:-0}" != 1 ] || [ "$1" != +%s ]; then command date "$@"; return; fi',
                '  n=$(cat "$RAW/date-calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$RAW/date-calls"',
                '  case "$n" in 1|2|3) echo 1000 ;; 4) echo 1001 ;; *) echo 1180 ;; esac',
                "}",
                "stage2_operator_request_status() {",
                '  case "$*" in',
                '    "$REQUEST_ID")',
                '      echo request-status-B >> "$RAW/trace"',
                '      if [ "${SEED_BAD_REQUEST_ID:-0}" = 1 ]; then',
                '        printf \'%s\\n\' \'{"outcome":"pending","request_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","terminal":false}\'',
                '      elif [ "${SEED_PENDING_STUCK:-0}" = 1 ]; then',
                '        printf \'{"outcome":"pending","request_id":"%s","terminal":false}\\n\' "$REQUEST_ID"',
                '      elif [ ! -f "$RAW/polled" ]; then',
                '        : > "$RAW/polled"',
                '        printf \'{"outcome":"pending","request_id":"%s","terminal":false}\\n\' "$REQUEST_ID"',
                '      else',
                '        printf \'%s\\n\' \'{"outcome":"admitted","admitted_revision":"rev-B"}\'',
                '      fi; return 0 ;;',
                '    *) echo "unexpected retained request: $*" >&2; return 31 ;;',
                '  esac',
                "}",
                "cold_client() {",
                '  case "$*" in',
                '    *"--wait-seconds 0 service admit"*) ;;',
                '    *) echo "unexpected operator command: $*" >&2; return 31 ;;',
                '  esac',
                '  local alias',
                '  case "$*" in *task-A*) alias=A ;; *task-B*) alias=B ;; *task-C*) alias=C ;; *) return 32 ;; esac',
                '  case "$*" in *plan-review-document*rev-review*) ;; *) return 33 ;; esac',
                '  case "$*" in *"--request-key perch-stage2-admit-$alias"*) ;; *) return 34 ;; esac',
                '  echo "admit-$alias" >> "$RAW/trace"',
                '  if [ "$alias" = B ]; then',
                '    printf \'{"outcome":"pending","request_id":"%s","terminal":false}\\n\' "$REQUEST_ID"',
                '  else',
                '    printf \'{"outcome":"admitted","admitted_revision":"rev-%s"}\\n\' "$alias"',
                '  fi',
                "}",
                "stage2_wait_admission_boundary() { return 95; }",
                "stage2_wait_worker() {",
                '  for alias in A B C; do [ -f "$RAW/stage2-admit-$alias.json" ] || return 35; done',
                '  echo "wait-$2" >> "$RAW/trace"',
                "}",
                submit.group(),
                admit.group(),
                dispatch.group(),
                "stage2_admit_tasks && stage2_dispatch_tasks",
            ))
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                    env={**os.environ, "SEED_BAD_REQUEST_ID": "1" if seed_bad_id else "0",
                                         "SEED_PENDING_STUCK": "1" if seed_stuck else "0"},
                                    timeout=30)
            return raw, result

        raw, result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((raw / "trace").read_text(encoding="utf-8").splitlines(),
                         ["admit-A", "admit-B", "admit-C", "request-status-B", "request-status-B",
                          "wait-A", "wait-B", "wait-C"])
        self.assertEqual(json.loads((raw / "stage2-admit-B-attempt-1.json").read_text())["outcome"], "pending")
        self.assertEqual(json.loads((raw / "stage2-admit-B-retained-1.json").read_text())["outcome"], "admitted")
        self.assertEqual(json.loads((raw / "stage2-admit-B.json").read_text())["admitted_revision"], "rev-B")
        raw, result = run(seed_bad_id=True)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual((raw / "trace").read_text(encoding="utf-8").splitlines(),
                         ["admit-A", "admit-B", "admit-C", "request-status-B"])
        self.assertIn("changed its retained request id", (raw / "stage2-setup-errors.txt").read_text())
        self.assertTrue((raw / "stage2-admit-C-attempt-1.json").exists())
        raw, result = run(seed_stuck=True)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual((raw / "trace").read_text(encoding="utf-8").splitlines(),
                         ["admit-A", "admit-B", "admit-C", "request-status-B"])
        self.assertIn("stayed pending", (raw / "stage2-setup-errors.txt").read_text())
        self.assertFalse((raw / "stage2-admit-B-attempt-2.json").exists())

    def test_operator_retained_read_uses_the_admission_owner_lane(self):
        import re
        import shlex

        root = short_temp_root()
        self.addCleanup(shutil.rmtree, root, True)
        owner_lane = root / "home" / "owner-lane"
        host_lane = root / "perch-canary" / "client" / "lanes" / "claude-code"
        (root / "tree").mkdir()
        (root / "tree" / "src").symlink_to(ROOT / "src", target_is_directory=True)
        owner_lane.mkdir(parents=True)
        host_lane.mkdir(parents=True)
        request_id = "a0ebbb3fece74d328ad1d290385a13ae"
        owner_response = owner_lane / ("response-" + request_id + ".json")
        owner_response.write_text('{"outcome":"admitted","admitted_revision":"rev-A"}\n',
                                  encoding="utf-8")
        owner_response.chmod(0o600)
        (host_lane / ("response-" + request_id + ".json")).write_text(
            '{"outcome":"held","reason":"wrong host lane"}\n', encoding="utf-8")
        shell = PERCH.read_text(encoding="utf-8")
        helper = re.search(r"(?ms)^stage2_operator_request_status\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(helper)
        script = "\n".join((
            "STAGE_ROOT=" + shlex.quote(str(root)),
            "PY=" + shlex.quote(sys.executable),
            "PATH=" + shlex.quote(os.environ["PATH"]),
            "HOME=" + shlex.quote(os.environ["HOME"]),
            helper.group(),
            "stage2_operator_request_status " + request_id,
        ))
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"outcome": "admitted", "admitted_revision": "rev-A"})

    def test_pending_admission_requires_a_valid_request_receipt(self):
        pending = {"outcome": "pending", "request_id": "a" * 32, "terminal": False}
        self.assertEqual(perch_report.stage2_admission_request_id(pending), "a" * 32)
        self.assertIsNone(perch_report.stage2_admission_request_id({"outcome": "admitted"}))
        with self.assertRaisesRegex(ValueError, "invalid pending request receipt"):
            perch_report.stage2_admission_request_id({**pending, "terminal": True})
        with self.assertRaisesRegex(ValueError, "changed its retained request id"):
            perch_report.stage2_admission_request_id(pending, expected="b" * 32)

    def test_dispatch_poll_resolves_one_pending_request_before_read(self):
        import re
        import shlex

        root = short_temp_root()
        self.addCleanup(shutil.rmtree, root, True)
        raw = clean_stage2_raw(root / "pending-dispatch")
        request_id = "a0ebbb3fece74d328ad1d290385a13ae"
        pending = {"outcome": "pending", "request_id": request_id, "terminal": False,
                   "service_state": "processing"}
        (raw / "pending.json").write_text(json.dumps(pending), encoding="utf-8")
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        wait = re.search(r"(?ms)^stage2_wait_worker\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(wait)
        script = "\n".join((
            "set -euo pipefail",
            "RAW=" + shlex.quote(str(raw)),
            "PY=" + shlex.quote(sys.executable),
            "REPORT_PY=" + shlex.quote(str(BOOTSTRAP / "perch_report.py")),
            "REQUEST_ID=" + shlex.quote(request_id),
            "stage2_host_client() {",
            '  case "$*" in',
            '    *"--wait-seconds 0 project status --project perch-stage2")',
            '      if [ -e "$RAW/project-called" ]; then echo "resubmitted status" >&2; return 91; fi',
            '      : > "$RAW/project-called"; cat "$RAW/pending.json" ;;',
            '    *"request-status --request-id $REQUEST_ID")',
            '      if [ -e "$RAW/request-called" ]; then cat "$RAW/read.json";',
            '      else : > "$RAW/request-called"; cat "$RAW/pending.json"; fi ;;',
            '    *) echo "unexpected host command: $*" >&2; return 92 ;;',
            '  esac',
            '}',
            "cold_client() { printf '%s\\n' '{\"native_capacity\":{\"active_or_uncertain\":1}}'; }",
            "stage2_kill_worker() { :; }",
            "sleep() { :; }",
            wait.group(),
            "stage2_wait_worker claude-code C",
        ))

        def run_with(response):
            for name in ("project-called", "request-called"):
                (raw / name).unlink(missing_ok=True)
            (raw / "read.json").write_text(json.dumps(response), encoding="utf-8")
            return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)

        read = {"outcome": "read", "tasks": [{"id": "C", "repo": "toy", "branch": "canon/main",
                "dispatch": {"state": "launched", "reason": None}}]}
        result = run_with(read)
        self.assertEqual(result.returncode, 0, result.stderr + (raw / "stage2-setup-errors.txt").read_text())
        self.assertTrue((raw / "request-called").exists())
        self.assertEqual(json.loads((raw / "stage2-dispatch-C.json").read_text()), read)
        self.assertEqual(json.loads((raw / "stage2-dispatch-C-pending.json").read_text()), pending)
        with self.assertRaisesRegex(ValueError, "changed its retained request id"):
            perch_report.stage2_dispatch_request_id(
                {**pending, "request_id": "b" * 32}, expected=request_id)
        result = run_with({"outcome": "error", "error": {"message": "seeded status error"}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("seeded status error", (raw / "stage2-setup-errors.txt").read_text())

    def test_stage_two_preserves_operator_log_and_copies_raw_evidence(self):
        shell = (BOOTSTRAP / "perch.sh").read_text(encoding="utf-8")
        self.assertNotIn("stage2_cleanup_operator_log", shell)
        self.assertNotIn('rm -f "$STAGE_ROOT/home/run/operator-admission.jsonl"', shell)
        self.assertIn('cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-operator-admission.jsonl"',
                      shell)

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
        evidence = Ref("owner", "dat.content.document", "runner-receipt-A", "rev-evidence")
        evidence_digest = "d" * 64
        with mock_patch.object(sys, "path", [str(ROOT / "src"), *sys.path]):
            from herzchen.domains.assessment.model import AssessmentResult, Invocation, Verdict

        assessed_result = AssessmentResult(
            ref=Ref("owner", "assessment.result", "result-A", "rev-1"),
            scope_ref=Ref("owner", "assessment.scope", "scope-A", "rev-1"),
            parent_obligation_ref=Ref("owner", "work.obligation", "obligation-A", "rev-1"),
            criterion_ref=Ref("owner", "assessment.criterion", "criterion-A", "rev-1"),
            candidate_ref=candidate,
            input_packet_ref=Ref("owner", "assessment.input", "input-A", "rev-1"),
            verdict=Verdict.PASS,
            guidance={},
            protocol_result={},
            invocation=Invocation(
                ref=Ref("owner", "assessment.invocation", "invocation-A", "rev-1"),
                operation_ref=Ref("owner", "assessment.operation", "operation-A", "rev-1"),
                reservation_ref=Ref("owner", "resource.reservation", "reservation-A", "rev-1"),
                route="test", role="fleet-check", state="completed", declared_units=1,
                actual_units=1, result={}, version=1, payload={}),
            findings=(),
            correction_refs=(),
            version=1,
            payload={"evidence_refs": [evidence.to_dict()]},
        )
        self.assertIsInstance(assessed_result, AssessmentResult)
        self.assertFalse(hasattr(assessed_result, "evidence_refs"))
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
                return assessed_result

            def get_decision(self, ref):
                if ref.kind != "assessment.decision":
                    raise ValueError("wrong decision")
                return SimpleNamespace(evidence_refs=(evidence,), payload={"evidence_digests": (
                    {"ref": evidence.to_dict(), "digest": evidence_digest},)})

        class Portfolio:
            outcome = "completed"

            def complete_task(self, project, task, manager, **kwargs):
                calls.append((project, task, manager, kwargs))
                return {"outcome": self.outcome, "task_ref": task}

        portfolio = Portfolio()
        owner = SimpleNamespace(graph=Graph(), owner_actor=object(), evidence_payload_resolver=SimpleNamespace(),
                                binding=SimpleNamespace(authenticated_actor=lambda actor: ("authenticated", actor)),
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
            self.assertEqual(calls[0][3]["evidence_refs"], [evidence.to_dict()])
            self.assertEqual(calls[0][3]["evidence_hashes"], {
                "dat.content.document:runner-receipt-A:rev-evidence": evidence_digest})
            self.assertEqual(calls[0][3]["actor"], "perch-stage2-manager")
            self.assertEqual(calls[1], "refresh")
            context["task"] = SimpleNamespace(ref=task_ref, payload={"alias": "B"})
            completed_b = self.launcher.complete_landed_canary(context, landing)
            self.assertEqual(completed_b["outcome"], "completed")
            # Seed a refused owner completion. The fake manager must turn red.
            portfolio.outcome = "held"
            with self.assertRaisesRegex(RuntimeError, "manager completion refused"):
                context["task"] = SimpleNamespace(ref=task_ref, payload={"alias": "B"})
                self.launcher.complete_landed_canary(context, landing)
            self.assertEqual(len(calls), 5)
            portfolio.outcome = "completed"
            context["task"] = SimpleNamespace(ref=task_ref, payload={"alias": "C"})
            completed_c = self.launcher.complete_landed_canary(context, landing)
            self.assertEqual(completed_c["outcome"], "completed")
            self.assertEqual(len(calls), 7)
            self.assertEqual([calls[index][3]["request_id"] for index in (0, 2, 5)],
                             ["perch-stage2-complete-A", "perch-stage2-complete-B",
                              "perch-stage2-complete-C"])

    def test_task_lifecycle_wait_is_red_until_owner_completes(self):
        status = {"tasks": [{"id": "A", "lifecycle": "completed"}]}
        owner = {"native_capacity": {"active_or_uncertain": 0}}
        self.assertTrue(perch_report.stage2_task_complete(status, owner, "A"))
        self.assertTrue(perch_report.stage2_task_landed(status, "A"))
        owner["native_capacity"]["active_or_uncertain"] = 1
        self.assertFalse(perch_report.stage2_task_complete(status, owner, "A"))
        self.assertTrue(perch_report.stage2_task_landed(status, "A"))
        status["tasks"][0]["lifecycle"] = "active"
        self.assertFalse(perch_report.stage2_task_complete(status, owner, "A"))
        self.assertFalse(perch_report.stage2_task_landed(status, "A"))

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
        self.tmp = short_temp_root()
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

    def test_stage_two_report_records_held_receipt_and_same_key_retry(self):
        raw = clean_raw(self.tmp / "raw")
        patch(raw, "config.json", lambda value: value.update(stage="2"))
        (raw / "stage2-admit-B-attempt-1.json").write_text(json.dumps({
            "outcome": "pending", "request_id": "a" * 32, "terminal": False}), encoding="utf-8")
        (raw / "stage2-admit-B-attempt-1.request-key").write_text(
            "perch-stage2-admit-B\n", encoding="utf-8")
        (raw / "stage2-admit-B-retained-1.json").write_text(json.dumps({
            "outcome": "admitted", "admitted_revision": "rev-B"}), encoding="utf-8")
        for number, response in ((1, {"outcome": "held", "reason":
                "execution-changing operation requires a closed owner boundary"}),
                                 (2, {"outcome": "admitted", "admitted_revision": "rev-C"})):
            prefix = raw / ("stage2-admit-C-attempt-%s" % number)
            prefix.with_suffix(".json").write_text(json.dumps(response), encoding="utf-8")
            prefix.with_suffix(".request-key").write_text("perch-stage2-admit-C\n", encoding="utf-8")
        (raw / "stage2-admit-C-boundary-status.json").write_text(json.dumps({
            "state": "serving", "native_capacity": {"active_or_uncertain": 0, "holds": []}}), encoding="utf-8")
        out = self.tmp / "report.md"
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(out)))
        report = out.read_text(encoding="utf-8")
        self.assertIn("## Operator admission attempts", report)
        self.assertIn("| B | 1 | perch-stage2-admit-B | pending |", report)
        self.assertIn("| B | 1 retained | perch-stage2-admit-B | admitted |", report)
        self.assertIn("| C | 1 | perch-stage2-admit-C | held |", report)
        self.assertIn("| C | 2 | perch-stage2-admit-C | admitted |", report)
        self.assertIn("[raw receipt](raw/stage2-admit-C-attempt-1.json)", report)
        self.assertIn("[raw owner status](raw/stage2-admit-C-boundary-status.json)", report)


class StagingRootSnapshotTests(unittest.TestCase):
    """The Store at rest and the staging root after down, read from real files: a SQLite Store and a socket."""

    def setUp(self):
        self.tmp = short_temp_root()
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

    def test_start_census_rejects_worker_processes_from_any_staging_root(self):
        lines = [
            "101 101 0:01 /tmp/labs/_staging-a/tree/src/fake_worker.py --lab /tmp/a",
            "202 202 0:01 /tmp/labs/_staging-b/perch-canary/perch-fake-claude --model test",
            "303 303 0:01 /usr/bin/python unrelated.py",
        ]
        self.assertEqual(perch_report.worker_processes(lines), lines[:2])

    def test_down_confirms_all_previously_recorded_worker_groups_are_gone(self):
        records = {"one": {"pid": 101, "pgid": 101, "birth": [1, 2]},
                   "two": {"pid": 202, "pgid": 202, "birth": [3, 4]}}
        self.assertTrue(perch_report.recorded_groups_gone(records, ["303 303 0:01 unrelated"])[0])
        gone, remaining = perch_report.recorded_groups_gone(
            records, ["303 101 0:01 unrelated", "202 202 0:01 /tmp/_staging/perch-fake-claude"])
        self.assertFalse(gone)
        self.assertEqual(remaining, [202, 303])

    def test_forced_staging_down_helper_kills_recorded_fake_worker(self):
        from otto.portfolio.execution_host import _process_start_identity
        root = self.tmp / 'forced-down'
        root.mkdir()
        worker = subprocess.Popen([PY, str(BOOTSTRAP / 'canary' / 'fake_worker.py'),
                                   '--lab', str(root), '--task', 'held', '--project', str(root / 'unused.json'),
                                   '--events', str(root / 'events.jsonl'), '--hold'], start_new_session=True)
        self.addCleanup(lambda: (worker.poll() is None and os.killpg(worker.pid, 9), worker.wait()))
        records = root / 'home' / 'shared-host' / 'capacity-process-groups.json'
        records.parent.mkdir(parents=True)
        records.write_text(json.dumps({'held': {'pid': worker.pid, 'pgid': worker.pid,
            'birth': _process_start_identity(worker.pid)['birth']}}), encoding='utf-8')

        source = (BOOTSTRAP / 'staging.sh').read_text(encoding='utf-8')
        begin = source.index('terminate_recorded_worker_groups() {')
        end = source.index('\n}\n', begin) + len('\n}\n')
        helper = source[begin:end]
        env = {**os.environ, 'PY': PY, 'TREE': str(ROOT), 'HOME_DIR': str(root / 'home')}
        result = subprocess.run(['bash', '-c', helper + '\nterminate_recorded_worker_groups'],
                                env=env, capture_output=True, text=True, check=True)
        self.assertIn('down: killed recorded worker group %s (held)' % worker.pid, result.stdout)
        self.assertLess(worker.wait(timeout=2), 0)

        down = source[source.index('down() {'):source.index('\n}\n', source.index('down() {'))]
        self.assertLess(down.index('stop_group "$pid"'), down.index('terminate_recorded_worker_groups'))

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
        self.tmp = short_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_missing_store_is_reported_not_invented(self):
        out = self.tmp / "timeline.json"
        perch_report.cmd_timeline(Namespace(src=str(ROOT / "src"), store=str(self.tmp / "none.store"),
                                            authority="owner", out=str(out)))
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["error"], "no Store file")
        self.assertEqual(data["tasks"], [])


def run_perch(tmp, sha, fault="", stage="0"):
    """perch.sh STAGE --fake in a temp folder, with the commit under test pinned to SHA."""
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
            r = subprocess.run(["bash", str(PERCH), stage, "--fake"], env=env, stdin=subprocess.DEVNULL, stdout=out,
                               stderr=subprocess.STDOUT, timeout=600)
        except subprocess.TimeoutExpired:
            return None, log.read_text(encoding="utf-8")[-4000:], None
    reports = list((tmp / "perch" / stage).glob("*/report.md"))
    return r.returncode, log.read_text(encoding="utf-8"), reports[0].parent if reports else None


def results_of(report_dir):
    return {a["name"]: a["status"] for a in json.loads((report_dir / "raw" / "assertions.json").read_text(encoding="utf-8"))}


class FakeRunTests(unittest.TestCase):
    """perch.sh 0 --fake in a temp staging root, with the lab's committed HEAD as the commit under test."""

    def setUp(self):
        self.tmp = short_temp_root()
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

    def test_stage4_fake_run_lands_happy_path_refuses_conflict_and_deletes_labs(self):
        code, log, report_dir = run_perch(self.tmp, self.sha, stage="4")
        self.assertIsNotNone(code, "stage 4 fake perch did not finish; log tail:\n" + log)
        self.assertEqual(code, 0, log)
        self.assertIsNotNone(report_dir, log)
        got = results_of(report_dir)
        self.assertEqual(got["landing-conflict-refused"], "pass", got)
        self.assertEqual(got["landing-conflict-lab-deleted"], "pass", got)
        self.assertTrue(all(got[name] == "pass" for name in NAMES[:7]), got)

    def test_stage4_seeded_missing_conflict_turns_its_assertion_red(self):
        code, log, report_dir = run_perch(self.tmp, self.sha, "conflict", stage="4")
        self.assertIsNotNone(code, "stage 4 seeded-fault perch did not finish; log tail:\n" + log)
        self.assertEqual(code, 1, log)
        got = results_of(report_dir)
        self.assertEqual({name for name, status in got.items() if status == "fail"},
                         {"landing-conflict-refused"}, got)


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
                tmp = short_temp_root()
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
        tmp = short_temp_root()
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
