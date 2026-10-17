"""Stage 3 owner-backed PERCH report helpers.

This module is deliberately separate from perch_report.py: stage 3 is accepted
only from durable owner records, never from the local fake-worker timeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import perch_report as base


def _same_ref(left: Any, right: Any) -> bool:
    return isinstance(left, Mapping) and isinstance(right, Mapping) and all(
        left.get(k) == right.get(k) for k in ("authority", "kind", "id", "revision"))


def _same_identity(left: Any, right: Any) -> bool:
    return isinstance(left, Mapping) and isinstance(right, Mapping) and all(
        isinstance(left.get(k), str) and left[k] and left[k] == right.get(k)
        for k in ("authority", "kind", "id"))


def _valid_ref(ref: Any, kind: str) -> bool:
    return (isinstance(ref, Mapping) and isinstance(ref.get("authority"), str) and ref.get("authority")
            and ref.get("kind") == kind
            and all(isinstance(ref.get(k), str) and ref[k] for k in ("id", "revision")))


def stage3_due_failures(dues, expected):
    failures = []
    rows = [row for row in dues if isinstance(row, Mapping)] if isinstance(dues, list) else []
    for alias, pin in expected.items():
        matches = [d for d in rows if d.get("schedule_id") == pin.get("schedule_id")
                   and _same_ref(d.get("assignment_ref"), pin.get("assignment_ref"))
                   and _same_ref((d.get("target") or {}).get("task_ref"), pin.get("task_ref"))]
        if len(matches) != 1:
            failures.append("%s owner Due matched %d records; expected exactly one" % (alias, len(matches)))
            continue
        due = matches[0]
        state = due.get("completion_state")
        raw_result = due.get("last_result")
        outcome = raw_result.get("outcome") if isinstance(raw_result, Mapping) else None
        if state != "succeeded" or due.get("stop_state") != "completed" or outcome != "succeeded":
            result = due.get("last_result") if isinstance(due.get("last_result"), Mapping) else {}
            err = result.get("error") if isinstance(result.get("error"), Mapping) else {}
            reason = result.get("reason") or result.get("detail") or err.get("message") or "no owner reason recorded"
            failures.append("%s owner Due is %s/%s (result %s): %s" %
                            (alias, state, due.get("stop_state"), outcome or "missing", reason))
    return failures


def stage3_evidence_failures(evidence, expected):
    failures = []
    if not isinstance(evidence, Mapping):
        return ["owner evidence is not an object"]
    aliases = list(expected)
    for key in ("labs", "facade_calls", "runners", "landings", "dues"):
        if not isinstance(evidence.get(key), list):
            failures.append("owner evidence %s is missing or malformed" % key)
    if failures:
        return failures
    labs, calls, runners = evidence["labs"], evidence["facade_calls"], evidence["runners"]
    landings, dues = evidence["landings"], evidence["dues"]
    admission = evidence.get("host_admission") if isinstance(evidence.get("host_admission"), Mapping) else {}
    host = admission.get("host") if isinstance(admission.get("host"), Mapping) else {}
    adapter = (host.get("adapters") or {}).get("claude-code") if isinstance(host.get("adapters"), Mapping) else None
    launcher = adapter.get("launcher") if isinstance(adapter, Mapping) else None
    qualified = adapter.get("qualified_versions") if isinstance(adapter, Mapping) else None
    if (admission.get("outcome") not in {"admitted", "replayed"} or not isinstance(launcher, str)
            or not launcher.startswith("/") or "fake" in launcher.lower()
            or not isinstance(qualified, list) or not qualified):
        failures.append("owner host admission lacks a real absolute pinned Claude launcher")
    runner_map = {r.get("record", {}).get("run_id"): r for r in runners
                  if isinstance(r, Mapping) and isinstance(r.get("record"), Mapping)}
    runner_ids = [r.get("record", {}).get("run_id") for r in runners
                  if isinstance(r, Mapping) and isinstance(r.get("record"), Mapping)]
    if len(runner_ids) != len(set(runner_ids)):
        failures.append("runner source contains duplicate run identities")
    for alias, pin in expected.items():
        task_ref, assignment_ref = pin.get("task_ref"), pin.get("assignment_ref")
        if not _valid_ref(task_ref, "work.task") or not _valid_ref(assignment_ref, "wrk.assignment"):
            failures.append("%s expected task/assignment refs are invalid" % alias)
            continue
        task_labs = [r for r in labs if isinstance(r, Mapping) and _same_identity(r.get("task_ref"), task_ref)
                     and _same_ref(r.get("assignment_ref"), assignment_ref)]
        if len(task_labs) != 1:
            failures.append("%s has %d owner lab creation records; expected one" % (alias, len(task_labs)))
        else:
            lab = task_labs[0]
            try:
                start = datetime.fromisoformat(lab["started_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(lab["ended_at"].replace("Z", "+00:00"))
                timed = end >= start
            except (AttributeError, KeyError, TypeError, ValueError):
                timed = False
            if (not isinstance(lab.get("path"), str) or not lab["path"]
                    or type(lab.get("apparent_bytes")) is not int or lab["apparent_bytes"] <= 0
                    or not isinstance(lab.get("elapsed_seconds"), (int, float)) or lab["elapsed_seconds"] <= 0
                    or not timed or ".git" not in str(lab.get("size_rule") or "")):
                failures.append("%s owner lab lacks path, positive size, measured elapsed time, timestamps or size rule" % alias)
        task_calls = [r for r in calls if isinstance(r, Mapping) and _same_identity(r.get("task_ref"), task_ref)
                      and _same_ref(r.get("assignment_ref"), assignment_ref)]
        methods = [r.get("method") for r in task_calls]
        if (methods[:1] != ["task"] or not methods or methods[-1] != "done"
                or methods.count("task") != 1 or methods.count("done") != 1):
            failures.append("%s facade calls must start with task and finish with done" % alias)
        checks = [r for r in task_calls if r.get("method") == "check"]
        done_at = methods.index("done") if "done" in methods else len(methods)
        if any(index <= 0 or index >= done_at for index, method in enumerate(methods) if method == "check"):
            failures.append("%s facade checks must follow task and precede done" % alias)
        if not checks:
            failures.append("%s has no authenticated facade check call" % alias)
        for call in task_calls:
            response = call.get("result") if isinstance(call.get("result"), Mapping) else {}
            result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
            method = call.get("method")
            if response.get("ok") is not True or response.get("kind") != method:
                failures.append("%s authenticated facade %s did not return success" % (alias, method))
            if method == "check" and (result.get("ok") is not True
                                      or result.get("run_id") != call.get("runner_run_id")):
                failures.append("%s authenticated facade check did not pass for its runner receipt" % alias)
            if method == "done" and (result.get("ok") is not True or result.get("landed") is not True
                                     or result.get("runner_run_id") != call.get("runner_run_id")):
                failures.append("%s authenticated facade done did not land its runner receipt" % alias)
        check_ids = [r.get("runner_run_id") for r in checks]
        if any(not x for x in check_ids) or len(set(check_ids)) != len(check_ids):
            failures.append("%s check calls lack distinct runner receipt identities" % alias)
        task_landings = [r for r in landings if isinstance(r, Mapping) and _same_identity(r.get("task_ref"), task_ref)
                         and _same_ref(r.get("assignment_ref"), assignment_ref)]
        if len(task_landings) != 1:
            failures.append("%s has %d landing evidence rows; expected one" % (alias, len(task_landings)))
        for check in checks:
            rid = check.get("runner_run_id")
            row = runner_map.get(rid)
            if row is None or row.get("verified") is not True:
                failures.append("%s check %s has no verified sealed runner record" % (alias, rid))
                continue
            rec = row["record"]
            if (rec.get("state") != "settled" or rec.get("outcome") != "exited" or rec.get("exit_code") != 0
                    or type(rec.get("units")) is not int or rec["units"] <= 0):
                failures.append("%s runner %s did not settle successfully with positive heavy units" % (alias, rid))
            if (rec.get("task") != task_ref.get("id") or rec.get("purpose") != "admitted task check"
                    or rec.get("argv") != pin.get("check_argv")):
                failures.append("%s runner %s did not execute its owner admitted typed check" % (alias, rid))
            nested_result = check.get("result", {}).get("result", {}) if isinstance(check.get("result"), Mapping) else {}
            check_commit = nested_result.get("commit") if isinstance(nested_result, Mapping) else None
            if len(task_labs) == 1 and rec.get("cwd") != task_labs[0].get("path"):
                failures.append("%s runner %s does not match the owner lab path" % (alias, rid))
            if check_commit and rec.get("commit") != check_commit:
                failures.append("%s runner %s commit differs from its facade check result" % (alias, rid))
            elif not check_commit and len(task_labs) == 1 and task_labs[0].get("lab_commit") \
                    and rec.get("commit") != task_labs[0].get("lab_commit"):
                failures.append("%s runner %s does not match the recorded lab commit" % (alias, rid))
            start, end = rec.get("started_at"), rec.get("settled_at")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
                failures.append("%s runner %s has invalid timing" % (alias, rid))
        for landing in task_landings:
            rid = landing.get("runner_run_id")
            row = runner_map.get(rid)
            done_calls = [call for call in task_calls if call.get("method") == "done"]
            done_ids = [call.get("runner_run_id") for call in done_calls]
            if rid not in done_ids or row is None or row.get("verified") is not True:
                failures.append("%s landing does not point to the verified runner receipt returned by done" % alias)
                continue
            rec = row.get("record", {})
            if (rec.get("state") != "settled" or rec.get("outcome") != "exited" or rec.get("exit_code") != 0
                    or type(rec.get("units")) is not int or rec["units"] <= 0
                    or not isinstance(rec.get("started_at"), (int, float))
                    or not isinstance(rec.get("settled_at"), (int, float))
                    or rec["settled_at"] < rec["started_at"]):
                failures.append("%s landing runner %s did not settle successfully with positive heavy units" % (alias, rid))
            if (rec.get("task") != task_ref.get("id") or rec.get("purpose") != "admitted task check"
                    or rec.get("argv") != pin.get("check_argv")):
                failures.append("%s landing runner %s did not execute its owner admitted typed check" % (alias, rid))
            if len(task_labs) == 1 and rec.get("cwd") != task_labs[0].get("path"):
                failures.append("%s landing runner %s does not match the owner lab path" % (alias, rid))
            ev = landing.get("evidence") if isinstance(landing.get("evidence"), Mapping) else {}
            manifest = ev.get("manifest") if isinstance(ev.get("manifest"), Mapping) else {}
            digest = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            length = len(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode())
            if (landing.get("lab_commit") != rec.get("commit") or ev.get("representation") != "managed"
                    or ev.get("verification") != "full-verified" or ev.get("actual_digest") != digest
                    or manifest.get("byte_digest") != digest or manifest.get("byte_length") != length):
                failures.append("%s landing does not retain the full verified managed runner receipt" % alias)
        due_matches = [d for d in dues if isinstance(d, Mapping) and d.get("schedule_id") == pin.get("schedule_id")
                       and _same_ref(d.get("assignment_ref"), assignment_ref)]
        if len(due_matches) != 1:
            failures.append("%s has %d owner worker Dues; expected one" % (alias, len(due_matches)))
        else:
            due = due_matches[0]
            host_evidence = due.get("host_evidence") if isinstance(due.get("host_evidence"), Mapping) else {}
            attempt = host_evidence.get("gateway_attempt") if isinstance(host_evidence.get("gateway_attempt"), Mapping) else {}
            result = due.get("last_result") if isinstance(due.get("last_result"), Mapping) else {}
            if (due.get("requested_model") != "claude-haiku-5-5"
                    or result.get("observed_model") != "claude-haiku-5-5"
                    or not isinstance(attempt, Mapping) or attempt.get("state") != "result"
                    or attempt.get("generation") != due.get("generation")
                    or not _same_ref(attempt.get("assignment_ref"), assignment_ref)):
                failures.append("%s worker Due lacks owner gateway evidence for requested and observed Haiku execution" % alias)
    # Check every verified runner's interval against all other checked units.
    checked = []
    used_run_ids = {call.get("runner_run_id") for call in calls if call.get("method") == "check"}
    used_run_ids.update(row.get("runner_run_id") for row in landings)
    for row in runners:
        rec = row.get("record") if isinstance(row, Mapping) else None
        if row.get("verified") is True and isinstance(rec, Mapping) and rec.get("run_id") in used_run_ids:
            checked.append((rec.get("started_at"), rec.get("settled_at"), rec.get("units"), rec.get("run_id")))
    headroom = evidence.get("heavy_headroom")
    valid = [item for item in checked if isinstance(item[0], (int, float))
             and isinstance(item[1], (int, float)) and type(item[2]) is int
             and item[2] > 0 and item[1] >= item[0]]
    for start, end, units, rid in valid:
        peak = sum(other[2] for other in valid if other[0] < end and other[1] > start)
        if type(headroom) is not int or headroom <= 0 or peak > headroom:
            failures.append("runner %s heavy overlap %s exceeds owner headroom %s" % (rid, peak, headroom))
            break
    if len(valid) > 1 and not any(
            a[0] < b[1] and b[0] < a[1] for i, a in enumerate(valid) for b in valid[i+1:]):
        failures.append("checked runner intervals have no positive heavy-unit overlap")
    return failures


def stage3_normalize_owner_records(raw_dir, expected, heavy_headroom=3):
    """Normalize copied durable records; return (evidence, failures)."""
    raw = Path(raw_dir)
    failures = []
    rows = []
    path = raw / "stage3-owner-fleet-evidence.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        failures.append("owner fleet evidence unavailable: " + str(exc))
    registration = base.read_json(raw / "stage3-registration.json", {}) or {}
    project_ref = registration.get("project_ref") if isinstance(registration, Mapping) else None
    if not _valid_ref(project_ref, "work.project"):
        failures.append("owner registration lacks an exact stage 3 project ref")
    labs_by_id, assignment_by_creation, facades, landings = {}, {}, [], []
    creation_ids, assignment_ids = [], []
    for row in rows:
        schema = row.get("schema") if isinstance(row, Mapping) else None
        if schema in {"otto.owner-lab-creation.v1", "otto.owner-lab-assignment.v1",
                      "otto.owner-facade-call.v1", "otto.owner-landing-evidence.v1"}:
            if not _same_identity(row.get("project_ref"), project_ref):
                failures.append("%s record is not bound to the registered stage 3 project" % schema)
        if schema == "otto.owner-lab-creation.v1":
            labs_by_id[row.get("creation_record_id")] = row
            creation_ids.append(row.get("creation_record_id"))
        elif schema == "otto.owner-lab-assignment.v1":
            assignment_by_creation[row.get("creation_record_id")] = row
            assignment_ids.append(row.get("creation_record_id"))
        elif schema == "otto.owner-facade-call.v1":
            facades.append(row)
        elif schema == "otto.owner-landing-evidence.v1":
            landings.append(row)
    if len(creation_ids) != len(set(creation_ids)) or len(assignment_ids) != len(set(assignment_ids)):
        failures.append("owner lab creation or assignment record identity is duplicated")
    if (len(creation_ids) != len(expected) or len(assignment_ids) != len(expected)
            or set(creation_ids) != set(assignment_ids)):
        failures.append("owner lab creation and assignment records do not pair one-to-one with A, B and C")
    labs = []
    for creation_id, bind in assignment_by_creation.items():
        created = labs_by_id.get(creation_id)
        if created:
            labs.append({**created, "assignment_ref": bind.get("assignment_ref"),
                         "schedule_id": bind.get("schedule_id"), "generation": bind.get("generation")})
    if len(labs) != len(expected):
        failures.append("owner lab creation/assignment joins: %d, expected %d" % (len(labs), len(expected)))
    calls = []
    for row in facades:
        result = row.get("result") if isinstance(row.get("result"), Mapping) else {}
        operation = row.get("operation")
        method = {"worker-task": "task", "worker-check": "check", "worker-done": "done"}.get(operation)
        if method is None:
            method = operation.removeprefix("worker-") if isinstance(operation, str) else ""
        nested = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        rid = (result.get("runner_run_id") or result.get("run_id") or nested.get("runner_run_id")
               or nested.get("run_id"))
        kind = row.get("kind")
        method = kind if kind in {"task", "check", "done"} else method
        calls.append({"method": method, "task_ref": row.get("task_ref"),
                      "assignment_ref": row.get("assignment_ref"), "runner_run_id": rid, "result": result})
    try:
        runner_doc = base.read_json(raw / "stage3-runner-records.json", {}) or {}
        if (runner_doc.get("error") or runner_doc.get("invalid_run_ids")
                or runner_doc.get("verification") != "ResultStore.all_records"):
            failures.append("runner source has error or invalid seals")
        runners = [{"verified": True, "record": row} if isinstance(row, Mapping) and "record" not in row else row
                   for row in (runner_doc.get("records") or [])]
    except Exception as exc:
        failures.append("runner records unavailable: " + str(exc)); runners = []
    schedules_doc = base.read_json(raw / "stage3-project-schedules.json", {}) or {}
    dues = [d for d in schedules_doc.get("schedules", []) if isinstance(d, Mapping)
            and d.get("role") == "worker"] if isinstance(schedules_doc, Mapping) else []
    if not isinstance(schedules_doc, Mapping) or schedules_doc.get("outcome") not in {"read", "ok", None}:
        failures.append("owner full schedule read is missing or failed")
    if not _same_identity(schedules_doc.get("project_ref"), project_ref):
        failures.append("owner full schedule read is for a different registered project")
    for due in dues:
        target = due.get("target") if isinstance(due.get("target"), Mapping) else {}
        if due.get("project_ref") != project_ref.get("id") or not _same_identity(target.get("project_ref"), project_ref):
            failures.append("worker Due %s is not bound to the registered stage 3 project" % due.get("schedule_id"))
    # Landing rows are emitted by the owner only after managed Evidence full verification.
    normalized_landings = []
    for row in landings:
        resolved = row.get("resolved_evidence") or row.get("evidence") or {}
        normalized_landings.append({**row, "evidence": resolved})
    landings = normalized_landings
    runner_rows = [r.get("record", {}) for r in runners if isinstance(r, Mapping)]
    for lab in labs:
        matching_landings = [r for r in landings if _same_identity(r.get("task_ref"), lab.get("task_ref"))
                             and _same_ref(r.get("assignment_ref"), lab.get("assignment_ref"))]
        if len(matching_landings) == 1:
            lab["lab_commit"] = matching_landings[0].get("lab_commit")
    if not landings:
        failures.append("owner landing evidence source is missing")
    host_admission = base.read_json(raw / "stage3-host-admission.json", {}) or {}
    evidence = {"labs": labs, "facade_calls": calls, "runners": runners, "landings": landings,
                "dues": dues, "heavy_headroom": heavy_headroom, "host_admission": host_admission,
                "project_ref": project_ref}
    failures.extend(stage3_evidence_failures(evidence, expected))
    return evidence, failures


def stage3_expected(activation, admissions, schedules):
    task_refs = (((activation or {}).get("activation") or {}).get("steps") or {}).get("tasks", {}).get("task_refs") or {}
    all_dues = (schedules or {}).get("schedules") or []
    expected = {}
    for alias, task_ref in task_refs.items():
        adm = base.read_json(Path(admissions) / ("stage3-admit-" + alias + ".json"), {}) or {}
        admitted_ref = adm.get("task_ref")
        same_task = _valid_ref(admitted_ref, "work.task") and _same_identity(admitted_ref, task_ref)
        if (adm.get("outcome") not in {"admitted", "already-admitted"}
                or adm.get("admitted_revision") != task_ref.get("revision") or not same_task):
            raise ValueError("%s lacks an exact admitted owner task receipt" % alias)
        matches = [d for d in all_dues if d.get("role") == "worker"
                   and _same_identity((d.get("target") or {}).get("task_ref"), task_ref)]
        if len(matches) > 1:
            raise ValueError("%s has multiple owner worker Dues" % alias)
        if len(matches) == 1:
            due = matches[0]
            expected[alias] = {"task_ref": (due.get("target") or {}).get("task_ref"),
                               "admitted_revision": task_ref.get("revision"),
                               "assignment_ref": due.get("assignment_ref"),
                               "schedule_id": due.get("schedule_id")}
    return expected


def cmd_stage3_owner_complete(args):
    try:
        status = base.read_json(args.status, {}) or {}
        schedules = base.read_json(args.schedules, {}) or {}
        activation = base.read_json(args.activation, {}) or {}
        expected = stage3_expected(activation, args.admissions, schedules)
        activated = (activation.get("activation") or {}).get("steps", {}).get("tasks", {}).get("task_refs", {})
        if not activated:
            raise ValueError("activation has no owner task references")
        status_tasks = {r.get("id"): r for r in status.get("tasks", []) if isinstance(r, Mapping)}
        pending = []
        pending.extend(alias + " has no owner worker Due yet" for alias in activated if alias not in expected)
        for alias, pin in expected.items():
            task = status_tasks.get(alias)
            if not task or task.get("lifecycle") != "completed" or (task.get("dispatch") or {}).get("state") != "landed":
                pending.append(alias + " task lifecycle is not completed and landed")
        due_fail = stage3_due_failures(schedules.get("schedules", []), expected)
        terminal = [f for f in due_fail if any(state in f for state in ("unknown", "failed", "interrupted"))]
        pending.extend(f for f in due_fail if f not in terminal)
        if terminal:
            print("\n".join(terminal)); return 2
        if pending:
            print("\n".join(pending)); return 1
        print("all activated tasks completed and owner worker Dues succeeded"); return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr); return 3


def cmd_stage3_bundle(args):
    project = base.read_json(args.project); stage = project["stages"]["3"]
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    rows = ["# Tasklist: perch-stage3", "", "## Owner canary", "| id | repo | branch | outcome | deps | route | proof |", "|---|---|---|---|---|---|---|"]
    for alias in stage["tasks"]:
        spec = stage["task_specs"][alias]
        rows.append("| %s | %s | %s | %s | %s | normal | %s |" %
                    (alias, stage["repository"], stage["branch"], spec["title"],
                     ", ".join(stage["dependencies"].get(alias, [])) or "-", spec["acceptance"]))
    texts = {"northstar.md": "# PERCH stage 3\n\nProve real owner dispatch, typed checks and verified landing.\n",
             "agent_goal.md": "# Agent goal: perch-stage3\n\n## Objective\n\nComplete three admitted owner tasks with real Haiku workers.\n",
             "plan.md": "# Plan\n\nRegister, activate, admit, dispatch, verify and complete the three owner tasks.\n",
             "status.md": "# Status\n\nOwner backed stage 3 canary.\n",
             "manager-brief.md": "# Manager brief\n\nReview owner evidence and complete each landed task only after all dependencies are satisfied. Report failures from the owner records.\n",
             "tasklist.md": "\n".join(rows)+"\n"}
    texts["reviews/plan-review.md"] = base.STAGE2_REVIEW_TEXT
    for alias, spec in stage["task_specs"].items():
        texts["tasks/%s.md" % alias] = "# %s\n\n%s\n\nAcceptance: %s\n" % (spec["title"], spec["instructions"], spec["acceptance"])
    for name, content in texts.items():
        path=out/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
    run={"run_id":"perch-stage3","mode":"planning_only","roles":{"coordinator":{"model":"claude-haiku-5-5"},"worker_normal":{"model":"claude-haiku-5-5"}},"assessment_accounting":stage.get("run_policy",{}).get("assessment_accounting")}
    (out/"run.json").write_text(json.dumps(run, indent=2)+"\n", encoding="utf-8")
    print(str(out))


def cmd_stage3_plan_save(args):
    project=base.read_json(args.project); stage=project["stages"]["3"]
    registration=base.read_json(args.registration,{}) or {}; project_ref=registration.get("project_ref")
    if not _valid_ref(project_ref,"work.project"): raise ValueError("registration did not return an exact project ref")
    tasks=[]
    for alias in stage["tasks"]:
        spec=stage["task_specs"][alias]
        tasks.append({"id":alias,"title":spec["title"],"instructions":spec["instructions"],"acceptance":spec["acceptance"],
                      "fields":{"check":{"argv":stage["checks"][alias]}},"dependencies":list(stage["dependencies"].get(alias,[])),
                      "metadata_namespace":{"otto.plan":{"repo":stage["repository"],"branch":stage["branch"],"route":"normal"}},
                      "custom":{"otto.plan":{"repo":stage["repository"],"branch":stage["branch"]}}})
    value={"project_ref":project_ref,"project":{"title":"perch-stage3","outcome":"Complete three real owner-dispatched canary tasks with verified typed checks."},"tasks":tasks}
    Path(args.out).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def cmd_init(args):
    project=base.read_json(args.project); stage=project["stages"][args.stage]
    config={"stage":args.stage,"fake":args.fake,"tasks":[],"check":"owner typed check","stage_root":args.stage_root,
            "host":stage.get("host"),"pool_limit":stage.get("pool_limit"),"manager_reserve":stage.get("manager_reserve"),
            "scenarios":stage.get("scenarios",[]),"stage3_tasks":stage.get("tasks"),"stage3_dependencies":stage.get("dependencies"),
            "store":stage.get("store"),"faults":[f for f in args.faults.split(",") if f],"staging_restart":args.staging_restart,
            "staging_sha":args.staging_sha,"canon_main_sha":args.canon_main_sha,"started_at":args.started_at,"finished_at":base.now_iso()}
    Path(args.raw).mkdir(parents=True,exist_ok=True)
    (Path(args.raw)/"config.json").write_text(json.dumps(config,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def _stage3_assertions(raw, project):
    config=base.read_json(raw/"config.json",{}) or {}; notes=base.read_json(raw/"notes.json",{}) or {}
    route_failures=[]
    if config.get("fake") or notes.get("stage3-worker-mode") != "real": route_failures.append("stage 3 requires a real, non-fake worker run")
    if notes.get("stage3-owner-route") != "completed": route_failures.append("owner stage 3 route did not complete")
    activation=base.read_json(raw/"stage3-activation.json",{}) or {}; schedules=base.read_json(raw/"stage3-project-schedules.json",{}) or {}
    grouped={"stage3-exact-owner-route":route_failures,"stage3-owner-labs":[],"stage3-facade-sequence":[],
             "stage3-runner-capacity":[],"stage3-managed-landing":[],"stage3-real-haiku":[],"stage3-due-completion":[]}
    store_failures=[]
    stage=project["stages"]["3"]; store_expect=stage.get("store") or {}
    timeline=base.read_json(raw/"timeline.json",None)
    store_events=base.read_json(raw/"stage3-store-events.json",None)
    before=base.read_json(raw/"stage3-store-before.json",None)
    after=base.read_json(raw/"stage3-store-after.json",None)
    if not isinstance(timeline,Mapping) or timeline.get("error"):
        store_failures.append("owner Store task timeline is missing or unreadable")
    else:
        if timeline.get("store_events",0)<store_expect.get("store_events_min",0):
            store_failures.append("Store has %s events; expected at least %s"%(timeline.get("store_events"),store_expect.get("store_events_min")))
        work=timeline.get("work_tasks") or []
        aliases=sorted(row.get("alias") for row in work if isinstance(row,Mapping))
        if aliases!=sorted(store_expect.get("store_work_tasks",[])):
            store_failures.append("Store work task aliases %s differ from expected %s"%(aliases,store_expect.get("store_work_tasks")))
        if len(timeline.get("tasks",[]))<store_expect.get("store_assignment_tasks_min",0):
            store_failures.append("Store has %d assignment task histories; expected at least %s"%(len(timeline.get("tasks",[])),store_expect.get("store_assignment_tasks_min")))
        for row in timeline.get("tasks",[]):
            if not row.get("complete") or row.get("gaps"):
                store_failures.append("Store assignment history %s has gaps %s"%(row.get("task_id"),row.get("gaps")))
        if any(not row.get("admitted_revision") for row in work):
            store_failures.append("Store has a task without its admitted revision")
    if not isinstance(store_events,Mapping) or store_events.get("error"):
        store_failures.append("owner Store event and assignment snapshot is unavailable")
    elif sorted((store_events.get("tasks") or {}).values())!=sorted(store_expect.get("store_work_tasks",[])):
        store_failures.append("owner Store event snapshot does not join exactly to A, B and C")
    for label,value in (("baseline",before),("after",after)):
        if not isinstance(value,Mapping) or value.get("error") or type(value.get("bytes")) is not int:
            store_failures.append("Store %s byte measurement is missing"%label)
    if isinstance(before,Mapping) and isinstance(after,Mapping) and type(before.get("bytes")) is int and type(after.get("bytes")) is int:
        growth=after["bytes"]-before["bytes"]
        if growth>store_expect.get("store_growth_max",0): store_failures.append("Store grew %d bytes, limit %s"%(growth,store_expect.get("store_growth_max")))
    rest=base.read_json(raw/"at-rest.json",None)
    if not isinstance(rest,Mapping) or rest.get("error"):
        store_failures.append("staging at-rest state is missing or unreadable")
    else:
        allowed= set(base.AT_REST_RUN)|{"operator-admission.jsonl"}
        unexpected=[name for name in rest.get("home_run",[]) if name not in allowed]
        if unexpected: store_failures.append("home/run has unexpected files: "+", ".join(unexpected))
        if rest.get("service_state") not in (None,"closed") or rest.get("sockets"):
            store_failures.append("staging service or socket remains after shutdown")
        if any(pids for pids in (rest.get("store_holders") or {}).values()):
            store_failures.append("staging Store still has open holders")
        if rest.get("perch_canary"):
            store_failures.append("staging still has disposable canary scratch after shutdown")
    at_rest_store=base.read_json(raw/"store-at-rest.json",None)
    if not isinstance(at_rest_store,Mapping) or at_rest_store.get("error") or type(at_rest_store.get("bytes")) is not int:
        store_failures.append("Store at-rest byte measurement is missing")
    elif isinstance(before,Mapping) and type(before.get("bytes")) is int:
        if at_rest_store["bytes"]-before["bytes"]>store_expect.get("store_growth_max",0):
            store_failures.append("Store at rest exceeds its growth bound")
    leftovers=base.read_lines(raw/"leftovers.txt")
    if leftovers:
        store_failures.extend("scratch remains: "+row for row in leftovers)
    store_assertion={"name":"stage3-store-and-at-rest","status":"fail" if store_failures else "pass",
                     "detail":"; ".join(store_failures) if store_failures else "owner Store contains admitted A/B/C histories and is within growth and shutdown bounds"}
    try:
        expected=stage3_expected(activation,raw,schedules)
        for alias, pin in expected.items():
            pin["check_argv"] = project["stages"]["3"]["checks"].get(alias)
        if len(expected)!=len(project["stages"]["3"]["tasks"]): grouped["stage3-due-completion"].append("exact admissions or worker Dues are missing")
        admission_log = []
        try:
            admission_log = [json.loads(line) for line in
                             (raw / "stage3-owner-operator-admission.jsonl").read_text(encoding="utf-8").splitlines()
                             if line.strip()]
        except (OSError, ValueError) as exc:
            grouped["stage3-exact-owner-route"].append("owner operator admission audit is missing or malformed: " + str(exc))
        review_ref = base.read_json(raw / "stage3-review-ref.json", {}) or {}
        for alias in project["stages"]["3"]["tasks"]:
            activated = (((activation.get("activation") or {}).get("steps") or {}).get("tasks") or {}).get("task_refs", {}).get(alias) or {}
            matching = [row for row in admission_log if isinstance(row, Mapping)
                        and row.get("task") == activated.get("id")]
            if (len(matching) != 1 or matching[0].get("revision") != activated.get("revision")
                    or matching[0].get("prover_result") != "approved"
                    or matching[0].get("outcome") not in {"admitted", "already-admitted"}
                    or matching[0].get("review") != review_ref.get("id") or not review_ref.get("id")):
                grouped["stage3-exact-owner-route"].append(
                    "%s lacks one approved owner operator admission for its activated revision and stored review" % alias)
        grouped["stage3-due-completion"].extend(stage3_due_failures(schedules.get("schedules",[]),expected))
        owner_status=base.read_json(raw/"stage3-owner-status.json",{}) or {}
        installed=base.read_json(raw/"stage3-installation.json",{}) or {}
        configured=project["stages"]["3"].get("capacity",{})
        owner_capacity=owner_status.get("native_capacity") if isinstance(owner_status.get("native_capacity"),Mapping) else {}
        if (owner_capacity.get("heavy_limit") != configured.get("heavy_headroom")
                or owner_capacity.get("worker_limit") != configured.get("turn_units")
                or installed.get("capacity") != configured):
            grouped["stage3-runner-capacity"].append("owner capacity projection or installation differs from stage 3 headroom")
        evidence, evidence_errors=stage3_normalize_owner_records(raw,expected,owner_capacity.get("heavy_limit"))
        for failure in evidence_errors:
            lower=failure.lower()
            if "lab" in lower: target="stage3-owner-labs"
            elif "facade" in lower or "authenticated" in lower: target="stage3-facade-sequence"
            elif "landing" in lower or "managed" in lower or "receipt" in lower: target="stage3-managed-landing"
            elif "runner" in lower or "heavy" in lower or "overlap" in lower or "check " in lower: target="stage3-runner-capacity"
            elif "haiku" in lower or "launcher" in lower or "model" in lower: target="stage3-real-haiku"
            else: target="stage3-exact-owner-route"
            grouped[target].append(failure)
        for due in evidence.get("dues", []):
            due_evidence=due.get("host_evidence") if isinstance(due.get("host_evidence"),Mapping) else {}
            attempt=due_evidence.get("gateway_attempt") if isinstance(due_evidence.get("gateway_attempt"),Mapping) else {}
            result=due.get("last_result") if isinstance(due.get("last_result"),Mapping) else {}
            if (due.get("requested_model")!="claude-haiku-5-5"
                    or result.get("observed_model")!="claude-haiku-5-5"
                    or not isinstance(attempt,Mapping) or attempt.get("state")!="result"
                    or attempt.get("generation")!=due.get("generation")
                    or not _same_ref(attempt.get("assignment_ref"),due.get("assignment_ref"))):
                grouped["stage3-real-haiku"].append("%s lacks exact requested and owner-observed Haiku model with gateway assignment evidence" % due.get("schedule_id"))
        status=base.read_json(raw/"stage3-project-status.json",{}) or {}
        task_rows={r.get("id"):r for r in status.get("tasks",[]) if isinstance(r,Mapping)}
        for alias in project["stages"]["3"]["tasks"]:
            row=task_rows.get(alias,{})
            if row.get("lifecycle")!="completed" or (row.get("dispatch") or {}).get("state")!="landed":
                grouped["stage3-due-completion"].append("%s owner project task is not completed and landed"%alias)
            if row.get("repo")!=stage.get("repository") or row.get("branch")!=stage.get("branch"):
                grouped["stage3-exact-owner-route"].append("%s owner project task is outside the registered toy line"%alias)
    except Exception as exc: grouped["stage3-exact-owner-route"].append("stage 3 owner join failed: "+str(exc))
    success={"stage3-exact-owner-route":"all three exact task admissions came from the owner and the run used real workers",
             "stage3-owner-labs":"one measured owner-created lab is bound to each task and assignment",
             "stage3-facade-sequence":"each owner assignment has its authenticated task, check and done call sequence",
             "stage3-runner-capacity":"every check resolves a verified passing sealed runner receipt within heavy-unit headroom",
             "stage3-managed-landing":"each landing retains the matching runner receipt as fully verified managed evidence",
             "stage3-real-haiku":"each worker Due proves requested and observed Haiku model, owner gateway assignment and pinned host launcher",
             "stage3-due-completion":"all three owner task lifecycles and exact worker Dues completed successfully"}
    return [{"name":name,"status":"fail" if values else "pass",
             "detail":"; ".join(dict.fromkeys(values)) if values else success[name]}
            for name,values in grouped.items()]+[store_assertion]


def cmd_check(args):
    raw=Path(args.raw); project=base.read_json(args.project)
    if (base.read_json(raw/"config.json",{}) or {}).get("stage")!="3":
        raise ValueError("stage3 report check requires stage 3 config")
    # Preserve useful base harness/staging checks but remove checks whose source is explicitly fake-local.
    results=base.assertions(raw)
    wrong={"timeline-events","labs-left-behind","harness-pool-within-limit","store-matches-stage","staging-at-rest-clean"}
    results=[r for r in results if r.get("name") not in wrong]
    results.extend(_stage3_assertions(raw,project))
    (raw/"assertions.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    labels={"pass":"PASS","fail":"FAIL","skip":"SKIP"}
    for r in results: print("%-4s %-32s %s"%(labels[r["status"]],r["name"],r["detail"]))
    return 1 if any(r.get("status")=="fail" for r in results) else 0


def cmd_render(args):
    raw=Path(args.raw); config=base.read_json(raw/"config.json",{}) or {}
    if config.get("stage")!="3": return base.cmd_render(args)
    results=base.read_json(raw/"assertions.json",[]) or []
    report=["# PERCH report: stage 3%s"%(" (fake worker)" if config.get("fake") else ""),"",
            "Stage 3 verdict uses copied owner records and exact task, assignment, Due, lab, facade, runner and landing joins.","",
            "## Assertions",""]
    report += base.table(["assertion","result","detail"],[[r["name"],r["status"],r["detail"]] for r in results])
    report += ["", "## Owner route", "", "- worker mode: %s"%((base.read_json(raw/"notes.json",{}) or {}).get("stage3-worker-mode","missing")),
            "- route: %s"%((base.read_json(raw/"notes.json",{}) or {}).get("stage3-owner-route","missing")),
            "- project status: raw/stage3-project-status.json", "- worker schedules: raw/stage3-project-schedules.json",
            "- copied owner evidence: raw/stage3-owner-fleet-evidence.jsonl", "- verified runner projection: raw/stage3-runner-records.json",""]
    schedules=base.read_json(raw/"stage3-project-schedules.json",{}) or {}
    dues=[d for d in schedules.get("schedules",[]) if isinstance(d,Mapping) and d.get("role")=="worker"]
    def _ref_id(value):
        return value.get("id") if isinstance(value,Mapping) else "-"
    def _due_reason(due):
        result=due.get("last_result") if isinstance(due.get("last_result"),Mapping) else {}
        error=result.get("error") if isinstance(result.get("error"),Mapping) else {}
        return result.get("reason") or error.get("message") or "-"
    report += ["", "## Owner task identities", ""]
    report += base.table(["task ref", "assignment ref", "schedule", "requested model", "completion", "stop", "reason"], [
        [_ref_id(((d.get("target") or {}).get("task_ref") if isinstance(d.get("target"),Mapping) else None)), _ref_id(d.get("assignment_ref")),
         d.get("schedule_id"), d.get("requested_model"), d.get("completion_state"), d.get("stop_state"),
         _due_reason(d)]
        for d in dues]) if dues else ["(no owner worker Dues recorded)"]
    owner_path=raw/"stage3-owner-fleet-evidence.jsonl"
    report += ["", "## Owner facade and landing receipts", ""]
    call_rows=[]; landing_rows=[]
    if owner_path.exists():
        try:
            for line in owner_path.read_text(encoding="utf-8").splitlines():
                row=json.loads(line)
                if row.get("schema")=="otto.owner-facade-call.v1":
                    result=row.get("result") if isinstance(row.get("result"),Mapping) else {}; nested=result.get("result") if isinstance(result.get("result"),Mapping) else {}
                    call_rows.append([_ref_id(row.get("task_ref")),_ref_id(row.get("assignment_ref")),
                                      row.get("kind"),nested.get("runner_run_id") or nested.get("run_id") or result.get("runner_run_id") or "-"])
                elif row.get("schema")=="otto.owner-landing-evidence.v1":
                    ev=row.get("evidence") if isinstance(row.get("evidence"),Mapping) else {}; manifest=ev.get("manifest") if isinstance(ev.get("manifest"),Mapping) else {}
                    landing_rows.append([_ref_id(row.get("task_ref")),_ref_id(row.get("assignment_ref")),
                                         row.get("runner_run_id"),ev.get("verification"),manifest.get("byte_digest"),manifest.get("byte_length")])
        except (ValueError,TypeError): report.append("Owner evidence file is malformed; see the failed owner assertions.")
    report += ["### Facade calls", ""]
    report += base.table(["task ref","assignment ref","call","runner run"],call_rows) if call_rows else ["(no facade calls recorded)"]
    report += ["", "### Landing evidence", ""]
    report += base.table(["task ref","assignment ref","runner run","verification","digest","bytes"],landing_rows) if landing_rows else ["(no landing evidence recorded)"]
    runner_doc=base.read_json(raw/"stage3-runner-records.json",{}) or {}
    runner_rows=runner_doc.get("records",[]) if isinstance(runner_doc,Mapping) else []
    report += ["", "### Verified runner receipts", ""]
    report += base.table(["run","commit","state","outcome","exit","units","started","settled"],[[
        r.get("run_id"),r.get("commit"),r.get("state"),r.get("outcome"),r.get("exit_code"),r.get("units"),r.get("started_at"),r.get("settled_at")]
        for r in runner_rows if isinstance(r,Mapping)]) if runner_rows else ["(no verified runner receipts recorded)"]
    Path(args.out).write_text("\n".join(report),encoding="utf-8")


def parser():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest="cmd",required=True)
    for name,fn in (("stage3-bundle",cmd_stage3_bundle),("stage3-plan-save",cmd_stage3_plan_save)):
        q=sub.add_parser(name); q.add_argument("--project",required=True); q.add_argument("--out",required=True)
        if name.endswith("plan-save"): q.add_argument("--registration",required=True)
        q.set_defaults(fn=fn)
    q=sub.add_parser("stage3-owner-complete")
    for flag in ("status","schedules","activation","admissions"): q.add_argument("--"+flag,required=True)
    q.set_defaults(fn=cmd_stage3_owner_complete)
    q=sub.add_parser("init"); q.add_argument("--raw",required=True); q.add_argument("--project",required=True); q.add_argument("--stage",required=True)
    q.add_argument("--fake",action="store_true"); q.add_argument("--faults",default=""); q.add_argument("--staging-restart",type=int,required=True)
    q.add_argument("--staging-sha",default="?"); q.add_argument("--canon-main-sha",default="?"); q.add_argument("--started-at",default="?"); q.add_argument("--stage-root",default=""); q.set_defaults(fn=cmd_init)
    q=sub.add_parser("check"); q.add_argument("--raw",required=True); q.add_argument("--project",required=True); q.set_defaults(fn=cmd_check)
    q=sub.add_parser("render"); q.add_argument("--raw",required=True); q.add_argument("--out",required=True); q.set_defaults(fn=cmd_render)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try: return args.fn(args) or 0
    except Exception as exc: print(str(exc),file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
