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

stage3_spec = importlib.util.spec_from_file_location("perch_stage3_report", BOOTSTRAP / "perch_stage3_report.py")
stage3_report = importlib.util.module_from_spec(stage3_spec)
stage3_spec.loader.exec_module(stage3_report)

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
            candidate = {"authority": "owner", "kind": "wrk.result", "id": "result-" + alias,
                         "revision": "rev-1"}
            gate = {"authority": "owner", "kind": "assessment.decision", "id": "decision-" + alias,
                    "revision": "rev-1"}
            events.append({"task_id": task_id, "alias": alias, "assignment_id": assignment_id,
                           "event_type": "work.result.appended", "stream": "result:" + assignment_id,
                           "recorded_at": "2026-10-17T10:00:%02dZ" % (when + 1),
                           "subject": {"kind": "wrk.result", "id": "result-" + alias}, "effects": {},
                           "value": {"lab_commit": "commit-" + alias, "task_ref": {"id": task_id},
                                     "assignment_id": assignment_id}})
            events.append({"task_id": task_id, "alias": alias, "assignment_id": None,
                           "event_type": "work.revised", "stream": "work:" + task_id,
                           "recorded_at": "2026-10-17T10:00:%02dZ" % (when + 2),
                           "actor": {"actor": "perch-stage2-manager"},
                           "subject": {"kind": "work.task", "id": task_id},
                           "effects": {"completion": {"disposition": "accepted",
                               "logical_request_key": "journey:perch-stage2-review-" + alias + ":finish",
                               "manager": "perch-stage2-manager", "generation": 1,
                               "candidate_ref": candidate, "gate_refs": [gate], "evidence_refs": [candidate],
                               "assessment_gate_check": {"evidence_verification": "verified",
                                   "blockers": [], "accepted_decision_refs": [gate]}}}, "value": None})
    events.append({"task_id": "task-C", "alias": "C", "assignment_id": None,
                   "event_type": "work.revised", "stream": "work:task-C",
                   "recorded_at": "2026-10-17T10:00:06.700000Z",
                   "subject": {"kind": "work.task", "id": "task-C"},
                   "effects": {"result_payload": {"metadata_namespaces": {"work.admission": {
                       "revision": "rev-C-edit"}}}}, "value": None})
    extra = {
        "stage2-store-events.json": {"error": None, "tasks": {"task-" + a: a for a in tasks},
            "assignments": {"assignment-" + a: "task-" + a for a in tasks},
            "manager_turns": [{"recipient": "perch-stage2-manager", "generation": 1,
                               "schedule_id": "manager-A", "native_turn_started": True,
                               "recorded_at": "2026-10-17T10:00:01Z"},
                              {"recipient": "perch-stage2-manager", "generation": 1,
                               "schedule_id": "manager-B", "native_turn_started": True,
                               "recorded_at": "2026-10-17T10:00:04Z"}],
            "decisions": {"decision-" + a: {"ref": {"authority": "owner", "kind": "assessment.decision",
                        "id": "decision-" + a, "revision": "rev-1"},
                        "payload": {"disposition": "accept",
                                    "candidate_ref": {"authority": "owner", "kind": "wrk.result",
                                                      "id": "result-" + a, "revision": "rev-1"},
                                    "evidence_refs": [{"authority": "owner", "kind": "wrk.result",
                                                       "id": "result-" + a, "revision": "rev-1"}]}}
                          for a in ("A", "B")},
            "worker_recovery": {"schedule_id": "worker-C", "stop_state": "stopped",
                "completion_state": "failed", "in_flight_request": None,
                "marker": {"schema": "otto.worker-gone-failed-disposition.v1",
                           "request_key": "perch-stage2-recover-C",
                           "disposition_ref": {"authority": "owner", "kind": "wrk.report",
                                               "id": "recovery-C", "revision": "rev-1"}}},
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
        "stage2-owner-status.json": {"native_capacity": {"holds": []}},
        "stage2-instruction-edit-C.input.json": {"tasks": [{"id": "C", "instructions":
            "Canary dispatch C (post-admission edit)"}]},
        "stage2-instruction-edit-C.json": {"outcome": "saved", "project_ref": {"id": "project-canary"}, "task_refs": {
            "C": {**task_refs["C"], "revision": "rev-C-edit"}}},
        "stage2-edited-C-no-launch.json": {"tasks": [
            {"id": "B", "lifecycle": "completed"},
            {"id": "C", "lifecycle": "pending", "dispatch": {"state": "admitted",
                "reason": "readmission needed", "changed_fields": ["instructions"]}}]},
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
                                          "labs": [], "controls": {}, "unexpected": [], "exists": False},
        "stage2-owner-labs-after.json": {"root": "/tmp/perch/canon.otto-labs", "entries": [],
                                         "labs": [], "controls": {}, "unexpected": [], "exists": True},
    }
    for name, value in extra.items():
        (raw / name).write_text(json.dumps(value), encoding="utf-8")
    (raw / "stage2-owner-pid.txt").write_text("123\n", encoding="utf-8")
    for label in ("before", "after"):
        (raw / ("stage2-fds-" + label + ".txt")).write_text(
            "COMMAND PID USER FD TYPE\n" + "".join("python 123 user %d txt\n" % n for n in range(5)),
            encoding="utf-8")
    return raw


def clean_stage3_owner_evidence(*, extra_check=False):
    """Normalized rows copied from owner lab, facade, Due, landing and verified runner sources."""
    aliases = ("A", "B", "C")
    checks = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))["stages"]["3"]["checks"]
    project_ref = {"authority": "owner", "kind": "work.project", "id": "project-3", "revision": "rev-project"}
    task_refs = {alias: {"authority": "owner", "kind": "work.task", "id": "task-" + alias,
                         "revision": "rev-task-" + alias} for alias in aliases}
    assignment_refs = {alias: {"authority": "owner", "kind": "wrk.assignment", "id": "assignment-" + alias,
                               "revision": "rev-assignment-" + alias} for alias in aliases}
    expected = {alias: {"task_ref": task_refs[alias], "assignment_ref": assignment_refs[alias],
                        "schedule_id": "due-" + alias, "check_argv": checks[alias]} for alias in aliases}
    labs, facade_calls, runners, landings, dues = [], [], [], [], []
    intervals = {"A": (100.0, 120.0), "B": (105.0, 125.0), "C": (130.0, 140.0)}
    for alias in aliases:
        run_id = "run-" + alias
        commit = (alias.lower() * 40)
        labs.append({"project_ref": project_ref, "task_ref": task_refs[alias],
                     "assignment_ref": assignment_refs[alias],
                     "started_at": "2026-10-18T10:00:00+00:00",
                     "ended_at": "2026-10-18T10:00:02+00:00",
                     "elapsed_seconds": 2.0, "path": "/owner/labs/" + alias, "apparent_bytes": 512,
                     "size_rule": "sum st_size of regular files recursively, including .git; symlinks excluded",
                     "lab_commit": commit})
        record = {"run_id": run_id, "seq": len(runners) + 1, "binding": "binding-" + alias,
                  "argv": checks[alias], "cwd": "/owner/labs/" + alias,
                  "commit": commit, "task": task_refs[alias]["id"], "purpose": "admitted task check", "units": 1,
                  "weight_requested": "heavy", "max_seconds": 30, "state": "settled",
                  "outcome": "exited", "exit_code": 0, "started_at": intervals[alias][0],
                  "settled_at": intervals[alias][1], "seal": "verified-seal-" + alias}
        # `verified` is copied only for a ResultStore.all_records() row, never inferred from a harness event.
        runners.append({"verified": True, "record": record})
        done_record = json.loads(json.dumps(record))
        done_record.update(run_id=run_id + "-done", seq=len(runners) + 1, binding="binding-" + alias + "-done",
                           started_at=150.0 + aliases.index(alias) * 10,
                           settled_at=152.0 + aliases.index(alias) * 10)
        runners.append({"verified": True, "record": done_record})
        receipt_bytes = json.dumps(done_record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
        facade_calls.extend([
            {"method": "task", "task_ref": task_refs[alias], "assignment_ref": assignment_refs[alias],
             "result": {"ok": True, "kind": "task", "result": {"task": alias}}},
            {"method": "check", "task_ref": task_refs[alias], "assignment_ref": assignment_refs[alias],
             "runner_run_id": run_id, "result": {"ok": True, "kind": "check",
                                                        "result": {"ok": True, "run_id": run_id, "commit": commit}}},
            {"method": "done", "task_ref": task_refs[alias], "assignment_ref": assignment_refs[alias],
             "runner_run_id": run_id + "-done", "result": {"ok": True, "kind": "done",
                                                                 "result": {"ok": True, "landed": True,
                                                                            "runner_run_id": run_id + "-done"}}},
        ])
        landings.append({"task_ref": task_refs[alias], "assignment_ref": assignment_refs[alias],
                         "lab_commit": commit, "runner_run_id": run_id + "-done",
                         "evidence": {"representation": "managed", "verification": "full-verified",
                                      "actual_digest": receipt_digest,
                                      "manifest": {"byte_digest": receipt_digest,
                                                   "byte_length": len(receipt_bytes)}}})
        dues.append({"schedule_id": "due-" + alias, "role": "worker",
                     "project_ref": project_ref["id"],
                     "target": {"project_ref": project_ref, "task_ref": task_refs[alias]},
                     "assignment_ref": assignment_refs[alias],
                     "requested_model": "claude-haiku-5-5", "completion_state": "succeeded",
                     "generation": 7, "stop_state": "completed",
                     "last_result": {"outcome": "succeeded", "observed_model": "claude-haiku-5-5"},
                     "host_evidence": {"gateway_attempt": {"state": "result", "generation": 7,
                                                              "assignment_ref": assignment_refs[alias]}}})
    if extra_check:
        record = json.loads(json.dumps(runners[0]["record"]))
        record.update(run_id="run-A2", seq=4, binding="binding-A2", started_at=110.0, settled_at=115.0)
        runners.append({"verified": True, "record": record})
        check = {"method": "check", "task_ref": task_refs["A"],
                 "assignment_ref": assignment_refs["A"], "runner_run_id": "run-A2",
                 "result": {"ok": True, "kind": "check", "result": {
                     "ok": True, "run_id": "run-A2", "commit": record["commit"]}}}
        done_index = next(i for i, call in enumerate(facade_calls)
                          if call["method"] == "done" and call["task_ref"] == task_refs["A"])
        facade_calls.insert(done_index, check)
    evidence = {"project_ref": project_ref, "labs": labs, "facade_calls": facade_calls,
                "runners": runners, "landings": landings, "dues": dues, "heavy_headroom": 3,
                "host_admission": {"outcome": "admitted", "host": {"adapters": {"claude-code": {
                    "launcher": "/opt/claude/bin/claude", "qualified_versions": ["2.1.0"]}}}}}
    return evidence, expected


def clean_stage3_raw(root):
    """Owner-shaped stage 3 sources for an all-pass stage-3 verdict fixture."""
    raw = Path(root)
    raw.mkdir(parents=True, exist_ok=True)
    evidence, expected = clean_stage3_owner_evidence()
    project = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))
    rows = []
    for alias, lab in zip("ABC", evidence["labs"]):
        creation_id = "creation-" + alias
        rows.append({"schema": "otto.owner-lab-creation.v1", "creation_record_id": creation_id,
                     **{key: lab[key] for key in ("project_ref", "task_ref", "started_at", "ended_at",
                                                   "elapsed_seconds", "path", "apparent_bytes", "size_rule")}})
        rows.append({"schema": "otto.owner-lab-assignment.v1", "creation_record_id": creation_id,
                     "project_ref": lab["project_ref"], "task_ref": lab["task_ref"],
                     "assignment_ref": lab["assignment_ref"], "schedule_id": expected[alias]["schedule_id"],
                     "generation": 7})
    runner_by_id = {r["record"]["run_id"]: r["record"] for r in evidence["runners"]}
    for call in evidence["facade_calls"]:
        method = call["method"]
        nested = {"ok": True}
        if method == "check":
            nested.update(run_id=call["runner_run_id"], commit=runner_by_id[call["runner_run_id"]]["commit"])
        elif method == "done":
            nested.update(landed=True, runner_run_id=call["runner_run_id"])
        rows.append({"schema": "otto.owner-facade-call.v1", "kind": method,
                     "operation": {"task": "effective-context", "check": "worker-check",
                                   "done": "worker-done"}[method],
                     "project_ref": evidence["project_ref"], "task_ref": call["task_ref"],
                     "assignment_ref": call["assignment_ref"],
                     "result": {"ok": True, "kind": method, "result": nested}})
    for landing in evidence["landings"]:
        rows.append({"schema": "otto.owner-landing-evidence.v1",
                     "project_ref": evidence["project_ref"], **landing})
    values = {
        "stage3-registration.json": {"project_ref": evidence["project_ref"]},
        "stage3-review-ref.json": {"authority": "owner", "kind": "dat.content.document",
                                    "id": "review-stage3", "revision": "rev-review"},
        "stage3-runner-records.json": {"records": [r["record"] for r in evidence["runners"]],
                                       "invalid_run_ids": [], "verification": "ResultStore.all_records"},
        "stage3-project-schedules.json": {"outcome": "read", "project_ref": evidence["project_ref"],
                                          "schedules": evidence["dues"]},
        "stage3-host-admission.json": evidence["host_admission"],
        "stage3-owner-status.json": {"outcome": "running", "native_capacity": {
            "worker_limit": 4, "heavy_limit": 3}},
        "stage3-installation.json": {"capacity": project["stages"]["3"]["capacity"]},
        "stage3-activation.json": {"activation": {"steps": {"tasks": {"task_refs": {
            alias: pin["task_ref"] for alias, pin in expected.items()}}}}},
        "stage3-project-status.json": {"outcome": "read", "tasks": [
            {"id": alias, "repo": "toy", "branch": "canon/main", "lifecycle": "completed",
             "dispatch": {"state": "landed"}}
            for alias in "ABC"]},
        "config.json": {"stage": "3", "fake": False, "staging_restart": 0},
        "notes.json": {"stage3-worker-mode": "real", "stage3-owner-route": "completed"},
        "timeline.json": {"error": None, "store_events": 6,
                          "work_tasks": [{"alias": alias, "admitted_revision": "rev-task-" + alias}
                                         for alias in "ABC"],
                          "tasks": [{"task_id": "assignment-" + alias, "complete": True, "gaps": []}
                                    for alias in "ABC"]},
        "stage3-store-events.json": {"error": None, "tasks": {
            "task-" + alias: alias for alias in "ABC"}},
        "stage3-store-before.json": {"error": None, "bytes": 1000},
        "stage3-store-after.json": {"error": None, "bytes": 2000},
        "store-at-rest.json": {"error": None, "bytes": 2000},
        "at-rest.json": {"error": None, "home_run": ["service.json", "generation", "service-stop",
                                                      "operator-admission.jsonl"],
                         "service_state": "closed", "sockets": [], "store_holders": {}},
    }
    for alias, pin in expected.items():
        values["stage3-admit-" + alias + ".json"] = {
            "outcome": "admitted", "admitted_revision": pin["task_ref"]["revision"],
            "task_ref": pin["task_ref"]}
    for name, value in values.items():
        (raw / name).write_text(json.dumps(value), encoding="utf-8")
    (raw / "stage3-owner-fleet-evidence.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    (raw / "stage3-owner-operator-admission.jsonl").write_text(
        "".join(json.dumps({"task": expected[alias]["task_ref"]["id"],
                            "revision": expected[alias]["task_ref"]["revision"],
                            "review": "review-stage3", "prover_result": "approved",
                            "outcome": "admitted"}) + "\n" for alias in "ABC"), encoding="utf-8")
    (raw / "leftovers.txt").write_text("", encoding="utf-8")
    return raw, project, rows, expected


def statuses(raw):
    return {r["name"]: r["status"] for r in perch_report.assertions(Path(raw))}


def seed_retained_stage2_owner_lab(raw):
    branch = "branch-key"
    task = branch + "/task-C"
    patch(raw, "stage2-owner-labs-after.json", lambda value: value.update(
        entries=[branch], labs=[task], controls={
            branch + "/.creating": [], branch + "/.landed": [],
            branch + "/.locks": [{"name": "task-A.lock", "kind": "file"},
                                   {"name": "task-C.lock", "kind": "file"}]}))
    (raw / "stage2-killed-worker.json").write_text(json.dumps({
        "pid": 101, "owner_pid": 202,
        "marker": "/tmp/perch/canon.otto-labs/" + task + "/.perch-worker-C.pid"}), encoding="utf-8")
    return task


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

    def test_stage_three_canary_declares_independent_work_and_typed_checks(self):
        project = json.loads((BOOTSTRAP / "canary" / "project.json").read_text(encoding="utf-8"))
        stage = project["stages"]["3"]
        self.assertEqual(stage["tasks"], ["A", "B", "C"])
        self.assertEqual((stage["repository"], stage["branch"]), ("toy", "canon/main"))
        self.assertEqual(stage["admission"]["admitted"], ["A", "B", "C"])
        self.assertEqual(stage["dependencies"], {"A": [], "B": [], "C": ["A", "B"]})
        self.assertEqual(stage["expected_completed"], ["A", "B", "C"])
        self.assertEqual(stage["store"]["store_work_tasks"], ["A", "B", "C"])
        self.assertEqual(stage["store"]["store_assignment_tasks_min"], 3)
        accounting = stage["run_policy"]["assessment_accounting"]
        self.assertEqual(accounting["scope_mode"], "check-accepted")
        self.assertEqual(accounting["pool_id"], "perch-stage3-checks")
        self.assertEqual(accounting["capacity_units"], 3)
        self.assertEqual(accounting["cumulative_allowance_units"], 9)
        self.assertEqual(accounting["task_criterion_pairs"], ["A/C-A", "B/C-B", "C/C-C"])
        self.assertIn("existing toy/mathx.py", stage["task_specs"]["A"]["instructions"])
        self.assertIn("native Edit tool", stage["task_specs"]["A"]["instructions"])
        self.assertIn("do not use Write", stage["task_specs"]["A"]["instructions"])
        self.assertIn("toy/labels.py", stage["task_specs"]["B"]["instructions"])
        self.assertIn("native Write tool", stage["task_specs"]["B"]["instructions"])
        self.assertIn("then use the native Edit tool", stage["task_specs"]["B"]["instructions"])
        self.assertIn("toy/summary.py", stage["task_specs"]["C"]["instructions"])
        self.assertEqual(set(stage["checks"]), {"A", "B", "C"})
        for alias, required in (("A", ("clamp(-1, 0, 5)",)),
                                ("B", ("label_case('  hello WORLD  ')",)),
                                ("C", ("clamp(9, 0, 5)", "label_case(' hello WORLD ')",
                                       "summary_line(9, 0, 5"))):
            with self.subTest(task=alias):
                argv = stage["checks"][alias]
                self.assertEqual(argv[:2], ["python3", "-c"])
                for behavior in required:
                    self.assertIn(behavior, argv[2])
                self.assertIn("assert", argv[2])
                self.assertNotEqual(argv, ["/usr/bin/true"])

    def test_stage_three_rejects_unknown_or_failed_owner_due_with_reason(self):
        task = {"authority": "owner", "kind": "work.task",
                "id": "task-A", "revision": "rev-A"}
        assignment = {"authority": "owner", "kind": "wrk.assignment",
                      "id": "assignment-A", "revision": "rev-A"}
        expected = {"A": {"task_ref": task, "assignment_ref": assignment,
                          "schedule_id": "due-A"}}
        completed = {
            "schedule_id": "due-A", "role": "worker",
            "target": {"task_ref": task}, "assignment_ref": assignment,
            "requested_model": "claude-haiku-5-5",
            "generation": 7,
            "completion_state": "succeeded", "stop_state": "completed",
            "last_result": {"outcome": "succeeded", "observed_model": "claude-haiku-5-5"},
            "host_evidence": {"gateway_attempt": {"state": "result", "generation": 7,
                                                     "assignment_ref": assignment}},
        }
        self.assertEqual(stage3_report.stage3_due_failures([completed], expected), [])

        for state in ("unknown", "failed"):
            with self.subTest(state=state):
                doctored = json.loads(json.dumps(completed))
                doctored["completion_state"] = state
                doctored["last_result"] = {
                    "outcome": state, "reason": "owner gateway lost the worker result"
                }
                failures = stage3_report.stage3_due_failures([doctored], expected)
                self.assertEqual(len(failures), 1)
                self.assertIn("A", failures[0])
                self.assertIn(state, failures[0])
                self.assertIn("owner gateway lost the worker result", failures[0])

    def test_stage_three_owner_completion_cli_distinguishes_complete_pending_and_terminal_failure(self):
        evidence, expected = clean_stage3_owner_evidence()
        task_refs = {alias: value["task_ref"] for alias, value in expected.items()}
        activation = {"activation": {"steps": {"tasks": {"task_refs": task_refs}}},
                      "operating_setup": {"setup": {"roles": {"manager": "manager-due"}}}}
        status = {"outcome": "read", "tasks": [
            {"id": alias, "lifecycle": "completed", "dispatch": {"state": "landed"}}
            for alias in ("A", "B", "C")]}
        schedules = {"outcome": "read", "schedules": evidence["dues"]}
        for alias, value in expected.items():
            (self.tmp / ("stage3-admit-" + alias + ".json")).write_text(json.dumps({
                "outcome": "admitted", "admitted_revision": value["task_ref"]["revision"],
                "task_ref": value["task_ref"]}), encoding="utf-8")
        status_path, schedules_path, activation_path = (self.tmp / "status.json", self.tmp / "schedules.json",
                                                       self.tmp / "activation.json")
        status_path.write_text(json.dumps(status), encoding="utf-8")
        schedules_path.write_text(json.dumps(schedules), encoding="utf-8")
        activation_path.write_text(json.dumps(activation), encoding="utf-8")
        command = [sys.executable, "-I", str(BOOTSTRAP / "perch_stage3_report.py"), "stage3-owner-complete",
                   "--status", str(status_path), "--schedules", str(schedules_path),
                   "--activation", str(activation_path), "--admissions", str(self.tmp)]

        def invoke():
            return subprocess.run(command, text=True, capture_output=True)

        self.assertEqual(invoke().returncode, 0)
        missing = schedules["schedules"].pop(0)
        schedules_path.write_text(json.dumps(schedules), encoding="utf-8")
        pending = invoke()
        self.assertEqual(pending.returncode, 1)
        self.assertIn("has no owner worker Due yet", pending.stdout)
        schedules["schedules"].insert(0, missing)
        schedules["schedules"][0]["completion_state"] = "pending"
        schedules["schedules"][0]["last_result"] = {"outcome": "pending"}
        schedules_path.write_text(json.dumps(schedules), encoding="utf-8")
        self.assertEqual(invoke().returncode, 1)
        schedules["schedules"][0]["completion_state"] = "unknown"
        schedules["schedules"][0]["last_result"] = {
            "outcome": "unknown", "reason": "owner gateway lost the worker result"}
        schedules_path.write_text(json.dumps(schedules), encoding="utf-8")
        failed = invoke()
        self.assertEqual(failed.returncode, 2)
        self.assertIn("owner gateway lost the worker result", failed.stdout + failed.stderr)

    def test_stage_three_owner_evidence_accepts_complete_owner_joins(self):
        evidence, expected = clean_stage3_owner_evidence()
        self.assertEqual(stage3_report.stage3_evidence_failures(evidence, expected), [])

    def test_stage_three_normalization_rejects_corrupt_raw_owner_lab_measurement(self):
        evidence, expected = clean_stage3_owner_evidence()
        raw = self.tmp / "stage3-normalize"
        raw.mkdir()
        rows = []
        for index, lab in enumerate(evidence["labs"]):
            creation_id = "creation-%s" % index
            rows.extend([
                {"schema": "otto.owner-lab-creation.v1", "creation_record_id": creation_id,
                 **{key: lab[key] for key in ("project_ref", "task_ref", "started_at", "ended_at",
                                               "elapsed_seconds", "path", "apparent_bytes", "size_rule")}},
                {"schema": "otto.owner-lab-assignment.v1", "creation_record_id": creation_id,
                 "project_ref": lab["project_ref"], "task_ref": lab["task_ref"],
                 "assignment_ref": lab["assignment_ref"], "schedule_id": expected["ABC"[index]]["schedule_id"],
                 "generation": 1},
            ])
        for call in evidence["facade_calls"]:
            rows.append({"schema": "otto.owner-facade-call.v1", "operation": "worker-" + call["method"],
                         "project_ref": evidence["project_ref"], "task_ref": call["task_ref"],
                         "assignment_ref": call["assignment_ref"],
                         "result": {**call["result"], "runner_run_id": call.get("runner_run_id")}})
        for landing in evidence["landings"]:
            rows.append({"schema": "otto.owner-landing-evidence.v1",
                         "project_ref": evidence["project_ref"], **landing})
        (raw / "stage3-runner-records.json").write_text(json.dumps({
            "records": [runner["record"] for runner in evidence["runners"]],
            "invalid_run_ids": [], "verification": "ResultStore.all_records"
        }), encoding="utf-8")
        (raw / "stage3-project-schedules.json").write_text(json.dumps({
            "project_ref": evidence["project_ref"], "schedules": evidence["dues"]}), encoding="utf-8")
        (raw / "stage3-registration.json").write_text(json.dumps({"project_ref": evidence["project_ref"]}),
                                                       encoding="utf-8")
        (raw / "stage3-host-admission.json").write_text(json.dumps(evidence["host_admission"]), encoding="utf-8")
        source = raw / "stage3-owner-fleet-evidence.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        normalized, failures = stage3_report.stage3_normalize_owner_records(raw, expected)
        self.assertEqual(failures, [], failures)
        # A zero byte measurement in an owner creation record must fail from the
        # copied source, after the same source passed without corruption.
        next(row for row in rows if row.get("schema") == "otto.owner-lab-creation.v1")["apparent_bytes"] = 0
        source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        normalized, failures = stage3_report.stage3_normalize_owner_records(raw, expected)
        self.assertEqual(len(normalized["labs"]), 3)
        self.assertTrue(failures)
        self.assertTrue(any("apparent_bytes" in failure or "measured" in failure for failure in failures),
                        failures)

    def test_stage_three_verdict_rows_fail_on_doctored_owner_sources(self):
        raw, project, rows, _expected = clean_stage3_raw(self.tmp / "stage3-verdict")

        def verdict():
            return {row["name"]: row for row in stage3_report._stage3_assertions(raw, project)}

        self.assertTrue(all(row["status"] == "pass" for row in verdict().values()), verdict())
        owner_path = raw / "stage3-owner-fleet-evidence.jsonl"

        def write_rows(value):
            owner_path.write_text("".join(json.dumps(row) + "\n" for row in value), encoding="utf-8")

        cases = (
            ("stage3-exact-owner-route", "notes.json", lambda v: v.update(**{"stage3-owner-route": "failed"})),
            ("stage3-exact-owner-route", "config.json", lambda v: v.update(fake=True)),
            ("stage3-exact-owner-route", "stage3-project-status.json", lambda v: v["tasks"][0].update(repo="other")),
            ("stage3-owner-labs", None, lambda v: next(r for r in v if r.get("schema") ==
                "otto.owner-lab-creation.v1").update(apparent_bytes=0)),
            ("stage3-facade-sequence", None, lambda v: v.__setitem__(slice(None), [r for r in v if not (
                r.get("schema") == "otto.owner-facade-call.v1" and r.get("kind") == "task"
                and r.get("task_ref", {}).get("id") == "task-A")])),
            ("stage3-runner-capacity", "stage3-runner-records.json", lambda v: v["records"][0].update(units=0)),
            ("stage3-runner-capacity", "stage3-owner-status.json", lambda v: v["native_capacity"].update(heavy_limit=1)),
            ("stage3-managed-landing", None, lambda v: next(r for r in v if r.get("schema") ==
                "otto.owner-landing-evidence.v1")["evidence"].update(actual_digest="0" * 64)),
            ("stage3-real-haiku", "stage3-project-schedules.json", lambda v: v["schedules"][0][
                "last_result"].update(observed_model="fake-claude")),
            ("stage3-exact-owner-route", "stage3-project-schedules.json", lambda v: v["schedules"][0][
                "target"]["project_ref"].update(id="another-project")),
            ("stage3-due-completion", "stage3-project-schedules.json", lambda v: v["schedules"][0].update(
                completion_state="unknown", last_result={"outcome": "unknown", "reason": "lost"})),
            ("stage3-store-and-at-rest", "timeline.json", lambda v: v["work_tasks"].pop()),
        )
        for name, file_name, doctor in cases:
            with self.subTest(assertion=name):
                write_rows(rows)
                path = raw / file_name if file_name else owner_path
                original = path.read_text(encoding="utf-8")
                value = json.loads(original) if file_name else json.loads(json.dumps(rows))
                doctor(value)
                path.write_text(json.dumps(value) if file_name else "".join(
                    json.dumps(row) + "\n" for row in value), encoding="utf-8")
                self.assertEqual(verdict()[name]["status"], "fail", name)
                path.write_text(original, encoding="utf-8")
                self.assertTrue(all(row["status"] == "pass" for row in verdict().values()), name)
        operator_path = raw / "stage3-owner-operator-admission.jsonl"
        original = operator_path.read_text(encoding="utf-8")
        owner_rows = [json.loads(line) for line in original.splitlines()]
        owner_rows[0]["prover_result"] = "unavailable"
        operator_path.write_text("".join(json.dumps(row) + "\n" for row in owner_rows), encoding="utf-8")
        self.assertEqual(verdict()["stage3-exact-owner-route"]["status"], "fail")
        operator_path.write_text(original, encoding="utf-8")
        self.assertTrue(all(row["status"] == "pass" for row in verdict().values()))

    def test_stage_three_joins_admitted_task_across_owner_revision_changes(self):
        raw, _project, rows, expected = clean_stage3_raw(self.tmp / "stage3-revisions")
        admitted_revision = expected["A"]["task_ref"]["revision"]
        activation = json.loads((raw / "stage3-activation.json").read_text(encoding="utf-8"))
        schedules_path = raw / "stage3-project-schedules.json"
        schedules = json.loads(schedules_path.read_text(encoding="utf-8"))
        schedules["schedules"][0]["target"]["task_ref"]["revision"] = "rev-after-admission"
        schedules["schedules"][0]["target"]["project_ref"]["revision"] = "rev-project-after-save"
        schedules_path.write_text(json.dumps(schedules), encoding="utf-8")
        for row in rows:
            if row.get("task_ref", {}).get("id") == "task-A":
                row["task_ref"]["revision"] = "rev-after-lifecycle"
            row["project_ref"]["revision"] = "rev-project-after-save"
        owner_path = raw / "stage3-owner-fleet-evidence.jsonl"
        owner_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        pins = stage3_report.stage3_expected(activation, raw, schedules)
        for alias, pin in pins.items():
            pin["check_argv"] = expected[alias]["check_argv"]
        self.assertEqual(pins["A"]["admitted_revision"], admitted_revision)
        self.assertEqual(pins["A"]["task_ref"]["revision"], "rev-after-admission")
        _, failures = stage3_report.stage3_normalize_owner_records(raw, pins, 3)
        self.assertEqual(failures, [])
        rows[0]["task_ref"]["id"] = "another-task"
        owner_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        _, failures = stage3_report.stage3_normalize_owner_records(raw, pins, 3)
        self.assertTrue(failures, "a different owner task identity cannot pass the lab join")

    def test_stage_three_report_cli_rejects_doctored_owner_receipt(self):
        raw, _project, _rows, _expected = clean_stage3_raw(self.tmp / "stage3-cli")
        command = [sys.executable, "-I", str(BOOTSTRAP / "perch_stage3_report.py"), "check",
                   "--raw", str(raw), "--project", str(BOOTSTRAP / "canary" / "project.json")]
        passed = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        source = raw / "stage3-runner-records.json"
        receipt = json.loads(source.read_text(encoding="utf-8"))
        receipt["invalid_run_ids"] = [receipt["records"][0]["run_id"]]
        source.write_text(json.dumps(receipt), encoding="utf-8")
        failed = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertIn("FAIL stage3-runner-capacity", failed.stdout)

    def test_stage_three_host_read_resolves_one_retained_owner_request(self):
        import re
        import shlex

        shell = PERCH.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^stage3_read_host\(\) \{[^\n]*\n.*?^\}\n", shell)
        self.assertIsNotNone(match)
        request_id = "a" * 32

        def run(doctored):
            raw = self.tmp / ("stage3-read-bad" if doctored else "stage3-read-good")
            raw.mkdir()
            pending = json.dumps({"outcome": "pending", "terminal": False, "request_id": request_id})
            answer = (json.dumps({"outcome": "pending", "terminal": False, "request_id": "b" * 32})
                      if doctored else json.dumps({"outcome": "read", "schedules": []}))
            script = "\n".join((
                "set -euo pipefail",
                "RAW=" + shlex.quote(str(raw)),
                "PY=" + shlex.quote(sys.executable),
                "REPORT_PY=" + shlex.quote(str(BOOTSTRAP / "perch_report.py")),
                "epoch_now() { date +%s; }",
                "stage2_owner_alive() { return 0; }",
                "sleep() { :; }",
                "stage2_host_client() {",
                '  printf "%s\\n" "$*" >> "$RAW/commands"',
                '  case "$*" in *request-status*) printf "%s\\n" ' + shlex.quote(answer) + " ;;",
                '    *) printf "%s\\n" ' + shlex.quote(pending) + " ;; esac",
                "}",
                match.group(),
                'stage3_read_host claude-code "$RAW/schedules.json" "$(( $(date +%s) + 30 ))" schedules --project perch-stage3',
            ))
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            return raw, result

        raw, passed = run(False)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertEqual(json.loads((raw / "schedules.json").read_text())["outcome"], "read")
        commands = (raw / "commands").read_text().splitlines()
        self.assertEqual(len(commands), 2)
        self.assertIn("request-status --request-id " + request_id, commands[1])
        raw, failed = run(True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((raw / "schedules.json").exists())

    def test_stage_three_owner_evidence_rejects_missing_or_unmeasured_labs(self):
        cases = (
            ("missing lab record", lambda evidence: evidence["labs"].pop()),
            ("zero apparent bytes", lambda evidence: evidence["labs"][0].update(apparent_bytes=0)),
            ("zero elapsed time", lambda evidence: evidence["labs"][0].update(elapsed_seconds=0)),
            ("missing size rule", lambda evidence: evidence["labs"][0].pop("size_rule")),
            ("reversed creation times", lambda evidence: evidence["labs"][0].update(
                started_at="2026-10-18T10:00:03+00:00")),
            ("lab bound to another assignment", lambda evidence: evidence["labs"][0].update(
                assignment_ref={"authority": "owner", "kind": "wrk.assignment", "id": "wrong",
                                "revision": "rev-wrong"})),
        )
        for label, doctor in cases:
            with self.subTest(label=label):
                evidence, expected = clean_stage3_owner_evidence()
                doctor(evidence)
                self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected), label)

    def test_stage_three_owner_evidence_requires_assignment_bound_facade_call_sequence(self):
        cases = (
            ("task call missing", lambda evidence: evidence["facade_calls"].pop(0)),
            ("check bound to other runner", lambda evidence: evidence["facade_calls"][1].update(
                runner_run_id="wrong-run")),
            ("done before check", lambda evidence: evidence["facade_calls"].__setitem__(
                slice(1, 3), list(reversed(evidence["facade_calls"][1:3])))),
            ("call bound to wrong assignment", lambda evidence: evidence["facade_calls"][0].update(
                assignment_ref={"authority": "owner", "kind": "wrk.assignment", "id": "wrong",
                                "revision": "rev-wrong"})),
            ("check response failed", lambda evidence: evidence["facade_calls"][1]["result"][
                "result"].update(ok=False)),
            ("done response did not land", lambda evidence: evidence["facade_calls"][2]["result"][
                "result"].update(landed=False)),
            ("facade response refused", lambda evidence: evidence["facade_calls"][0]["result"].update(ok=False)),
        )
        for label, doctor in cases:
            with self.subTest(label=label):
                evidence, expected = clean_stage3_owner_evidence()
                doctor(evidence)
                self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected), label)

    def test_stage_three_owner_evidence_requires_verified_successful_runner_and_overlap(self):
        cases = (
            ("runner missing for a check", lambda evidence: evidence["runners"].pop(0)),
            ("duplicate runner for a check", lambda evidence: evidence["runners"].append(
                json.loads(json.dumps(evidence["runners"][0])))),
            ("unverified runner", lambda evidence: evidence["runners"][0].update(verified=False)),
            ("wrong lab commit", lambda evidence: evidence["runners"][0]["record"].update(commit="f" * 40)),
            ("wrong typed check", lambda evidence: evidence["runners"][0]["record"].update(argv=["/usr/bin/true"])),
            ("runner did not settle successfully", lambda evidence: evidence["runners"][0]["record"].update(
                state="unknown", outcome="interrupted", exit_code=None)),
            ("no heavy units", lambda evidence: evidence["runners"][0]["record"].update(units=0)),
            ("overlap exceeds headroom", lambda evidence: evidence.update(heavy_headroom=1)),
            ("no overlapping heavy units", lambda evidence: evidence["runners"][2]["record"].update(
                started_at=120.0)),
        )
        for label, doctor in cases:
            with self.subTest(label=label):
                evidence, expected = clean_stage3_owner_evidence()
                doctor(evidence)
                self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected), label)

        evidence, expected = clean_stage3_owner_evidence(extra_check=True)
        self.assertEqual(stage3_report.stage3_evidence_failures(evidence, expected), [])
        late_check = evidence["facade_calls"].pop(2)
        evidence["facade_calls"].insert(3, late_check)
        self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected),
                        "a later check cannot appear after done")
        evidence, expected = clean_stage3_owner_evidence(extra_check=True)
        a_checks = [call for call in evidence["facade_calls"]
                    if call["method"] == "check" and call["task_ref"]["id"] == "task-A"]
        self.assertEqual(len(a_checks), 2)
        evidence["facade_calls"][next(i for i, call in enumerate(evidence["facade_calls"])
                                         if call is a_checks[1])]["runner_run_id"] = "run-A"
        self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected),
                        "two check calls cannot reuse the same runner receipt")

    def test_stage_three_owner_evidence_requires_full_managed_landing_receipt(self):
        cases = (
            ("wrong evidence digest", lambda evidence: evidence["landings"][0]["evidence"].update(
                actual_digest="0" * 64)),
            ("wrong manifest digest", lambda evidence: evidence["landings"][0]["evidence"]["manifest"].update(
                byte_digest="0" * 64)),
            ("wrong full length", lambda evidence: evidence["landings"][0]["evidence"]["manifest"].update(
                byte_length=1)),
            ("not fully verified", lambda evidence: evidence["landings"][0]["evidence"].update(
                verification="partial")),
            ("unmanaged representation", lambda evidence: evidence["landings"][0]["evidence"].update(
                representation="external")),
            ("landing points at another runner", lambda evidence: evidence["landings"][0].update(
                runner_run_id="wrong-run")),
            ("landing points at check runner instead of done runner",
             lambda evidence: evidence["landings"][0].update(runner_run_id="run-A")),
        )
        for label, doctor in cases:
            with self.subTest(label=label):
                evidence, expected = clean_stage3_owner_evidence()
                doctor(evidence)
                self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected), label)

    def test_stage_three_owner_evidence_requires_real_haiku_due_for_each_assignment(self):
        cases = (
            ("wrong worker model", lambda evidence: evidence["dues"][0].update(
                requested_model="fake-claude")),
            ("wrong observed model", lambda evidence: evidence["dues"][0]["last_result"].update(
                observed_model="fake-claude")),
            ("missing gateway result", lambda evidence: evidence["dues"][0]["host_evidence"].update(
                gateway_attempt={"state": "failed"})),
            ("wrong gateway generation", lambda evidence: evidence["dues"][0]["host_evidence"][
                "gateway_attempt"].update(generation=999)),
            ("gateway bound to another assignment", lambda evidence: evidence["dues"][0]["host_evidence"][
                "gateway_attempt"].update(assignment_ref={"authority": "owner", "kind": "wrk.assignment",
                                                            "id": "wrong", "revision": "wrong"})),
            ("due bound to another assignment", lambda evidence: evidence["dues"][0].update(
                assignment_ref={"authority": "owner", "kind": "wrk.assignment", "id": "wrong",
                                "revision": "rev-wrong"})),
            ("due missing", lambda evidence: evidence["dues"].pop()),
            ("fake pinned launcher", lambda evidence: evidence["host_admission"]["host"]["adapters"][
                "claude-code"].update(launcher="/tmp/fake-claude")),
            ("relative pinned launcher", lambda evidence: evidence["host_admission"]["host"]["adapters"][
                "claude-code"].update(launcher="claude")),
            ("missing qualified version", lambda evidence: evidence["host_admission"]["host"]["adapters"][
                "claude-code"].update(qualified_versions=[])),
        )
        for label, doctor in cases:
            with self.subTest(label=label):
                evidence, expected = clean_stage3_owner_evidence()
                doctor(evidence)
                self.assertTrue(stage3_report.stage3_evidence_failures(evidence, expected), label)

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
        self.assertFalse(hasattr(sock, "timeout"))
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
        self.assertEqual(got["admitted-ready-dependency-order"]["status"], "fail")

    def test_stage_two_note_without_owner_evidence_fails_closed(self):
        raw = clean_stage2_raw(self.tmp / "stage2-note-only")
        for path in raw.iterdir():
            if path.name not in {"config.json", "notes.json"}:
                path.unlink()
        got = {row["name"]: row["status"] for row in perch_report.assertions(raw)
               if row["name"] in perch_report.STAGE2}
        self.assertEqual(got, {name: "fail" for name in perch_report.STAGE2})

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
                expected = ({"admitted-ready-dependency-order", "unadmitted-revision-refused",
                             "metadata-only-write-runnable"} if fault == "admit_order" else {target})
                self.assertEqual({name for name, status in got.items() if status == "fail"}, expected, got)

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

    def test_stage_two_completion_requires_manager_turn_accepted_citations_and_resolved_holds(self):
        cases = (
            ("missing-manager", "stage2-store-events.json",
             lambda value: value.update(manager_turns=[])),
            ("direct-completion", "stage2-store-events.json",
             lambda value: next(row for row in value["events"] if row["alias"] == "A" and
                 (row.get("effects") or {}).get("completion"))["effects"]["completion"].update(
                     logical_request_key="perch-stage2-complete-A")),
            ("wrong-citation", "stage2-store-events.json",
             lambda value: next(row for row in value["events"] if row["alias"] == "B" and
                 (row.get("effects") or {}).get("completion"))["effects"]["completion"].update(evidence_refs=[])),
            ("unresolved-hold", "stage2-owner-status.json",
             lambda value: value["native_capacity"].update(holds=[{"schedule_id": "held-C"}])),
        )
        for label, file, mutate in cases:
            with self.subTest(label=label):
                raw = clean_stage2_raw(self.tmp / label)
                self.assertEqual(statuses(raw)["timeline-events"], "pass")
                patch(raw, file, mutate)
                self.assertEqual(statuses(raw)["timeline-events"], "fail")

    def test_stage_two_killed_worker_requires_retained_manager_disposition(self):
        raw = clean_stage2_raw(self.tmp / "missing-C-recovery")
        self.assertEqual(statuses(raw)["worker-kill-recovery"], "pass")
        patch(raw, "stage2-store-events.json", lambda value: value.update(worker_recovery=None))
        self.assertEqual(statuses(raw)["worker-kill-recovery"], "fail")
        shell = PERCH.read_text(encoding="utf-8")
        self.assertIn('stage2-boundary-closed --status "$RAW/stage2-recovery-owner.json"', shell)

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
        from herzchen.contracts import AuthenticatedActor
        from herzchen.domains.work import WorkGraph
        from herzchen.domains.work.batches import ProjectBatches
        from herzchen.kernel import Store
        from otto.hostctl import owner as owner_module

        store_path = self.tmp / "capture.store"
        store = Store.create(store_path, authority="owner")
        try:
            store.register_domain_handler(owner_module.host_domains())
            actor = AuthenticatedActor("owner", "host", "credential")
            graph = WorkGraph(store, actor=actor)
            project = graph.create_project(title="Canary", logical_request_key="capture-project")
            batches = ProjectBatches(store, actor=actor)
            for version, instructions in enumerate(("Original", "First edit", "Canary dispatch C (post-admission edit)"), 1):
                applied = batches.apply_project_sheet(project, {"tasks": [
                    {"id": "C", "title": "Canary dispatch C", "instructions": instructions}]},
                    logical_request_key="capture-sheet-" + str(version))
                project = applied.project
                task_ref = applied.mappings["C"]
                self.assertEqual(task_ref.revision, "rev-" + str(version))
        finally:
            store.close()

        receipt = evidence.capture(ROOT / "src", store_path, "owner")
        self.assertIsNone(receipt["error"])
        self.assertEqual(receipt["tasks"][task_ref.id], "C")
        captured_events = [row for row in receipt["events"] if row["event_type"] == "work.project-sheet.applied"
                           and any(ref.get("id") == task_ref.id and ref.get("revision") == "rev-3"
                                   for ref in row["effects"]["child_refs"])]
        self.assertEqual(len(captured_events), 1, receipt["events"])
        captured = captured_events[0]
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
            ("readmission-reason-missing", "unadmitted-revision-refused", "stage2-edited-C-no-launch.json",
             lambda value: value["tasks"][1]["dispatch"].update(reason=None)),
            ("readmission-field-missing", "unadmitted-revision-refused", "stage2-edited-C-no-launch.json",
             lambda value: value["tasks"][1]["dispatch"].update(changed_fields=[])),
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

    def test_stage_two_control_directories_are_recorded_and_stale_markers_fail(self):
        root = self.tmp / "control-tree" / "canon.otto-labs"
        namespace = root / "branch-key"
        for name in (".creating", ".landed", ".locks"):
            (namespace / name).mkdir(parents=True)
        (namespace / ".locks" / "task-A.lock").touch()
        snapshot = perch_report.stage2_owner_labs_snapshot(root)
        self.assertEqual(snapshot["labs"], [])
        self.assertEqual(snapshot["controls"]["branch-key/.creating"], [])
        self.assertEqual(snapshot["controls"]["branch-key/.locks"],
                         [{"name": "task-A.lock", "kind": "file"}])
        (namespace / ".creating" / "task-A").touch()
        self.assertEqual(perch_report.stage2_owner_labs_snapshot(root)["controls"]["branch-key/.creating"],
                         [{"name": "task-A", "kind": "file"}])
        for label, control, entry in (
            ("creating", ".creating", {"name": "task-A", "kind": "file"}),
            ("landed", ".landed", {"name": "task-B", "kind": "file"}),
            ("bad-lock", ".locks", {"name": "task-B", "kind": "file"}),
        ):
            with self.subTest(label=label):
                raw = clean_stage2_raw(self.tmp / label)
                seed_retained_stage2_owner_lab(raw)
                self.assertEqual(statuses(raw)["labs-left-behind"], "pass")
                patch(raw, "stage2-owner-labs-after.json", lambda value: value["controls"][
                    "branch-key/" + control].append(entry))
                detail = next(row["detail"] for row in perch_report.assertions(raw)
                              if row["name"] == "labs-left-behind")
                self.assertEqual(statuses(raw)["labs-left-behind"], "fail")
                self.assertIn(entry["name"], detail)
        raw = clean_stage2_raw(self.tmp / "missing-control-contents")
        seed_retained_stage2_owner_lab(raw)
        patch(raw, "stage2-owner-labs-after.json", lambda value: value.pop("controls"))
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

    def test_stage_two_waits_keep_polling_until_evidence_or_owner_exit(self):
        import re
        import shlex

        shell = PERCH.read_text(encoding="utf-8")
        functions = {}
        for name in ("stage2_owner_alive", "stage2_wait_marker", "stage2_wait_owner_capacity",
                     "stage2_capacity_turn"):
            match = re.search(r"(?ms)^" + name + r"\(\) \{[^\n]*\n.*?^\}\n", shell)
            self.assertIsNotNone(match, name)
            functions[name] = match.group()
        for name in ("stage2_wait_marker", "stage2_wait_owner_capacity", "stage2_capacity_turn"):
            self.assertIn("while :; do", functions[name])
            self.assertIn("sleep 0.25", functions[name])
            self.assertNotIn("deadline", functions[name])
            self.assertNotIn("date +%s", functions[name])

        cases = (
            ("stage2_wait_marker", "stage2_wait_marker worker-A", "worker-A PID marker"),
            ("stage2_wait_owner_capacity", 'stage2_wait_owner_capacity "$RAW/capacity.json" 2 1',
             "capacity status showed active=2 manager=1"),
            ("stage2_capacity_turn", "stage2_capacity_turn", "either ready worker A/B PID marker"),
        )
        for name, call, missing in cases:
            with self.subTest(wait=name):
                root = short_temp_root()
                self.addCleanup(shutil.rmtree, root, True)
                raw = root / "raw"
                raw.mkdir()
                (root / "canary").mkdir()
                (root / "staging" / "run").mkdir(parents=True)
                (root / "staging" / "run" / "staging.pid").write_text("4242\nrecorded start\n")
                (raw / "owner-live").touch()
                script = "\n".join((
                    "set -euo pipefail",
                    "RAW=" + shlex.quote(str(raw)),
                    "STAGE_ROOT=" + shlex.quote(str(root / "staging")),
                    "CANARY_DIR=" + shlex.quote(str(root / "canary")),
                    "CANARY=" + shlex.quote(str(BOOTSTRAP / "canary")),
                    "PY=" + shlex.quote(PY),
                    "REPORT_PY=" + shlex.quote(str(BOOTSTRAP / "perch_report.py")),
                    'ps() { [ -f "$RAW/owner-live" ] || return 0; case "$*" in',
                    '  *lstart=*) echo "recorded start" ;; *stat=*) echo S ;; esac; }',
                    'cold_client() { printf "%s\\n" \'{"native_capacity":{"active_or_uncertain":0},"manager_turns":{"active":0}}\'; }',
                    'sleep() { [ "$1" = 0.25 ] || exit 91;',
                    '  n=$(cat "$RAW/polls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$RAW/polls";',
                    '  [ "$n" -lt 3 ] || rm "$RAW/owner-live"; }',
                    functions["stage2_owner_alive"], functions[name], call,
                ))
                result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((raw / "polls").read_text(encoding="utf-8").strip(), "3")
                self.assertIn(missing, (raw / "stage2-setup-errors.txt").read_text(encoding="utf-8"))

    def test_deadline_absence_covers_all_stage_two_waits_and_fake_socket(self):
        import re

        shell = PERCH.read_text(encoding="utf-8")
        fake = (BOOTSTRAP / "perch_fake_claude.py").read_text(encoding="utf-8")
        function_pattern = r"(?ms)^(stage2_[A-Za-z0-9_]+)\(\) \{[^\n]*\n.*?^\}\n"
        matches = list(re.finditer(function_pattern, shell))
        waits = [(match.group(1), match.group()) for match in matches
                 if "while " in match.group() or "sleep " in match.group()]
        self.assertTrue(waits)

        def deadline_violations(shell_source, fake_source):
            pattern = r"\bdeadline\b|date\s+\+%s|\.settimeout\s*\("
            violations = []
            for match in re.finditer(function_pattern, shell_source):
                body = match.group()
                if ("while " in body or "sleep " in body) and re.search(pattern, body):
                    violations.append(match.group(1))
            if re.search(pattern, fake_source):
                violations.append("perch_fake_claude.py")
            return violations

        self.assertEqual(deadline_violations(shell, fake), [])
        for name, body in waits:
            with self.subTest(wait=name):
                doctored_shell = shell.replace(body, body[:-2] + "  # deadline=doctored\n}\n", 1)
                self.assertIn(name, deadline_violations(doctored_shell, fake))
        self.assertIn("perch_fake_claude.py", deadline_violations(
            shell, fake + "\nclient.settimeout(90)"))

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
                'stage2_owner_alive() { [ "${SEED_BOUNDARY_STUCK:-0}" != 1 ] || [ "$(cat "$RAW/status-calls" 2>/dev/null || echo 0)" -lt 3 ]; }',
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
                          "admit-C:perch-stage2-admit-C", "status-busy", "status-busy", "status-busy"])
        self.assertEqual(json.loads((raw / "stage2-admit-C.json").read_text())["outcome"], "held")
        self.assertFalse((raw / "stage2-admit-C-attempt-2.json").exists())
        self.assertIn("owner exited before", (raw / "stage2-setup-errors.txt").read_text())

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
                'stage2_owner_alive() { [ "${SEED_PENDING_STUCK:-0}" != 1 ] || [ "$(cat "$RAW/polls" 2>/dev/null || echo 0)" -lt 3 ]; }',
                "stage2_operator_request_status() {",
                '  case "$*" in',
                '    "$REQUEST_ID")',
                '      n=$(cat "$RAW/polls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$RAW/polls"',
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
                         ["admit-A", "admit-B", "admit-C", "request-status-B", "request-status-B",
                          "request-status-B"])
        self.assertIn("owner exited while retained admission request", (raw / "stage2-setup-errors.txt").read_text())
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
            "stage2_owner_alive() { :; }",
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

    def test_stage_two_manager_uses_installed_review_and_recovery_commands(self):
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        fake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fake)
        calls = []
        ref = {"authority": "owner", "kind": "wrk.result", "id": "result-A", "revision": "rev-1"}
        criterion = {"authority": "owner", "kind": "assessment.criterion", "id": "criterion-A", "revision": "rev-1"}
        pins = {"expected_due_sha256": "a" * 64, "expected_result_sha256": "b" * 64}

        def client(*words):
            calls.append(words)
            if words[:2] == ("review-input", "--task"):
                return ({"outcome": "read", "candidate_ref": ref, "source_refs": [ref],
                         "evidence_refs": [ref], "criterion_aliases": {"C-A": criterion},
                         "worker_result_sha256": "c" * 64, "task_outcome": "Canary dispatch A",
                         "observed_turn_id": "turn-A"} if words[2] == "A" else
                        {"outcome": "pending"})
            if words[0] == "review-task":
                return {"outcome": "accepted", "gate_refs": [{**criterion, "kind": "assessment.decision"}],
                        "completion": {"outcome": "pending", "completion_intent": "perch-A"}}
            if words[0] == "status":
                return {"outcome": "ok", "workers": {"C": {"schedule_id": "held-C"}}}
            if words[:2] == ("execution-control", "--operation") and words[2] == "read":
                return {"outcome": "read", "recovery": {"state": "held_failed",
                    "manager_gone_group_recovery": pins}}
            if words[:2] == ("execution-control", "--operation") and words[2] == "recover":
                return {"outcome": "settled", "manager_recovery": True,
                        "historical_result_preserved": True, "provider_called": False}
            self.fail("unexpected installed client command: " + repr(words))

        fake.scripted_manager_turn("A", client=client)
        self.assertEqual(calls[0], ("review-input", "--task", "A"))
        review = next(words for words in calls if words[0] == "review-task")
        self.assertEqual(json.loads(review[review.index("--candidate-ref") + 1]), ref)
        judgment = json.loads(review[review.index("--judgments") + 1])["C-A"]
        self.assertEqual(judgment["evidence_refs"], [ref])
        self.assertEqual(judgment["verdict"], "PASS")
        self.assertNotIn("complete-task", [words[0] for words in calls])

        def held_completion_client(*words):
            if words[0] == "review-task":
                return {"outcome": "accepted", "gate_refs": [{**criterion, "kind": "assessment.decision"}],
                        "completion": {"outcome": "held"}}
            return client(*words)

        with self.assertRaisesRegex(RuntimeError, "review or finish was refused"):
            fake.scripted_manager_turn("A", client=held_completion_client)

        calls.clear()
        fake.scripted_manager_turn("C", client=client)
        recovery = next(words for words in calls if words[0] == "execution-control" and
                        words[words.index("--operation") + 1] == "recover")
        self.assertIn(("--schedule-id", "held-C"), list(zip(recovery, recovery[1:])))
        self.assertIn(("--expected-due-sha256", "a" * 64), list(zip(recovery, recovery[1:])))
        self.assertIn(("--expected-result-sha256", "b" * 64), list(zip(recovery, recovery[1:])))
        first = True

        def delayed_group(*words):
            nonlocal first
            if words[0] == "execution-control" and words[words.index("--operation") + 1] == "recover" and first:
                first = False
                return {"outcome": "refused", "cause": "process_group_alive", "provider_called": False}
            return client(*words)

        self.assertEqual(fake.scripted_manager_turn("C", client=delayed_group), "pending")
        self.assertEqual(fake.scripted_manager_turn("C", client=delayed_group), "recovered")

    def test_fake_manager_uses_owner_introduced_installed_client(self):
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        fake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fake)
        temporary = short_temp_root()
        self.addCleanup(shutil.rmtree, temporary, True)
        entrypoint = temporary / "ottoctl"
        entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
        brief = {"operating_core": {"role": "manager",
                  "introduction": {"tool_entrypoint": str(entrypoint)}}}
        prompt = ('<otto-resource-brief sha256="' + "0" * 64 + '">\n'
                  + json.dumps(brief) + '\n</otto-resource-brief>')
        self.assertEqual(fake.manager_entrypoint(prompt), str(entrypoint))
        with mock_patch.object(fake.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout='{"outcome":"ok"}', stderr="")) as invoke:
            self.assertEqual(fake.installed_client(str(entrypoint), "status"), {"outcome": "ok"})
        self.assertEqual(invoke.call_args.args[0], [str(entrypoint), "manager", "status"])
        with self.assertRaisesRegex(ValueError, "installed client"):
            fake.manager_entrypoint(prompt.replace(str(entrypoint), str(temporary / "other")))

    def test_fake_manager_turns_wait_for_landing_then_yield_for_owner_settlement(self):
        spec = importlib.util.spec_from_file_location("perch_fake_claude", BOOTSTRAP / "perch_fake_claude.py")
        fake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fake)
        observed = {"A": 0, "B": 0, "C": 0}

        def turn(alias, *, client):
            observed[alias] += 1
            return {"A": ("pending", "reviewed", "completed"),
                    "B": ("pending", "reviewed", "completed"),
                    "C": ("pending", "recovered")}[alias][min(observed[alias] - 1,
                                                               2 if alias != "C" else 1)]

        with mock_patch.object(fake, "manager_entrypoint", return_value="/installed/ottoctl"), \
                mock_patch.object(fake, "scripted_manager_turn", side_effect=turn), \
                mock_patch.object(fake.time, "sleep", return_value=None):
            self.assertEqual(fake.manager_journey("owner brief"), "reviewed")
            self.assertEqual(observed, {"A": 2, "B": 0, "C": 0})
            self.assertEqual(fake.manager_journey("owner brief"), "reviewed")
            self.assertEqual(observed, {"A": 3, "B": 2, "C": 0})
            self.assertEqual(fake.manager_journey("owner brief"), "recovered")
            self.assertEqual(observed, {"A": 4, "B": 3, "C": 2})

    def test_stage_two_owner_does_not_install_completion_port_hook(self):
        source = (BOOTSTRAP / "perch_stage2_owner.py").read_text(encoding="utf-8")
        self.assertNotIn("install_fake_completion", source)
        self.assertNotIn("_OwnerExecutorPort.call", source)
        self.assertNotIn("complete_task(", source)


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

    def test_stage_two_leftovers_summary_shows_owner_snapshot_and_retained_C(self):
        raw = clean_stage2_raw(self.tmp / "owner-summary")
        retained = seed_retained_stage2_owner_lab(raw)
        (raw / "timeline.json").write_text(json.dumps({"error": "no Store file", "tasks": []}), encoding="utf-8")
        self.assertEqual(statuses(raw)["labs-left-behind"], "pass")
        out = self.tmp / "report.md"
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(out)))
        section = out.read_text(encoding="utf-8").split("## Labs and scratch left over\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("harness leftovers: none", section)
        self.assertIn("owner lab root before the first harness step", section)
        self.assertIn("owner lab root after down", section)
        self.assertIn(retained, section)
        self.assertIn("expected retained C lab: worker killed; task pending, dispatch unknown", section)
        self.assertIn("branch-key/.locks", section)
        self.assertIn("task-A.lock", section)
        patch(raw, "stage2-dispatch-status.json", lambda value: next(task for task in value["tasks"]
            if task["id"] == "C")["dispatch"].update(state="landed"))
        self.assertEqual(statuses(raw)["labs-left-behind"], "fail")
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(out)))
        section = out.read_text(encoding="utf-8").split("## Labs and scratch left over\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(retained + "` (unexpected)", section)
        self.assertNotIn("expected retained C lab", section)
        patch(raw, "stage2-dispatch-status.json", lambda value: next(task for task in value["tasks"]
            if task["id"] == "C")["dispatch"].update(state="unknown"))
        def old_snapshot(value):
            value["labs"].extend(["branch-key/.creating", "branch-key/.landed", "branch-key/.locks"])
            value.pop("controls")
        patch(raw, "stage2-owner-labs-after.json", old_snapshot)
        self.assertEqual(statuses(raw)["labs-left-behind"], "fail")
        perch_report.cmd_render(Namespace(raw=str(raw), out=str(out)))
        section = out.read_text(encoding="utf-8").split("## Labs and scratch left over\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(retained, section)
        self.assertIn("expected retained C lab", section)
        self.assertIn("branch-key/.creating`: contents not recorded", section)
        self.assertIn("owner task labs after down:", section)
        self.assertNotIn("branch-key/.creating` (unexpected)", section)

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
