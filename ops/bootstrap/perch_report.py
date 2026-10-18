"""PERCH's report: the Store's task timelines, the raw observations, the assertions and report.md.

perch.sh runs each part. Every subcommand reads or writes one run's raw folder, so a seeded fault
is a change to a file there and the checks are plain functions over it.
  stages    --project FILE                    the stage names in the canary project file
  tasks     --project FILE --stage S          the stage's task names, in order
  stage     --project FILE --stage S --key K  one value of a stage (a list prints a line each; a flag, true or false)
  portfolio --project FILE --stage S        the portfolio the stage's host is admitted with (<host>-portfolio)
  admission --raw DIR --project FILE --stage S   exit 1 unless raw/admission.json admitted the host and named its portfolio
  save-doc  --project FILE --stage S --name N [--ref-from RESPONSE] --out FILE   one of a stage's save documents
  field     --project FILE --key KEY          one top-level string of the project file (e.g. check)
  census    --out FILE [--stage-root DIR]     otto-related processes now (pid, pgid, etime, command)
  sample    --raw DIR --stage-root DIR --canary DIR [--status FILE]   one line for samples.jsonl
  snapshot  --canon DIR --labs DIR --out FILE  worktrees, lab branches and lab folders left over
  timeline  --src DIR --store FILE --authority A --out FILE   the Store's task timelines (herzchen)
  store     --store FILE --out FILE           the Store at rest: bytes, pages, freelist, integrity, rows per table
  at-rest   --stage-root DIR --out FILE       what the staging root holds after down: run files, sockets, holders
  seed      --raw DIR --fault KIND            a seeded fault in the observations (census, store, restart, typed,
                                              nothing, revision, stale, growth)
  note      --raw DIR --key K --value V       one fact of the run, into notes.json (JSON when it parses)
  init      --raw DIR ...                     config.json: the stage, the tasks and their expectations
  check     --raw DIR                         assertions.json; exit 1 on any failure
  render    --raw DIR --out FILE              report.md
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Otto's own processes are found by their stage root (the --home in their command line), not by name, so a
# scratch root is watched as well as the default one. ottoctl and otto.hostctl match every root, so they are gone.
CENSUS_MARKERS = ("_staging", "fake_worker", "perch-canary", "perch-fake-claude")
LEAK_MARKERS = ("_staging", "fake_worker", "perch-fake-claude")
# What `down` leaves in home/run: the published status (closed), the generation and the stop marker.
AT_REST_RUN = ("service.json", "generation", "service-stop")
LIFECYCLE = ("status-while-up", "status-after-kill-is-stale", "restart-after-kill-keeps-store",
             "status-after-stop", "refused-start-names-its-reason")
# Stage 1's save-through-socket scenario and the assertions it feeds. Each assertion reads the responses and
# Store snapshots the scenario wrote to raw/, and each has one seeded fault (seed --fault) that only it reads.
SAVE_SCENARIO = "save-through-socket"
STAGE1 = ("portfolio-admitted-before-saves", "canary-has-three-planned-tasks", "show-readback-available",
          "store-has-typed-tasks", "edit-is-persisted", "nothing-runs", "edit-makes-revision", "project-history-keeps-old-revision",
          "stale-save-refused", "store-growth-per-save")
STAGE2 = ("admit-and-dispatch-ran", "stage2-canary-valid", "stage2-review-document", "operator-presence-approved",
          "admitted-ready-dependency-order",
          "unadmitted-revision-refused", "metadata-only-write-runnable",
          "pool-and-manager-reserve-held", "owner-descriptors-bounded", "worker-kill-recovery",
          "stage2-store-snapshots", "stage2-census")
STAGE2_REVIEW_TEXT = "# Plan review\n\nThe PERCH stage-2 canary plan is approved for operator admission and dispatch on staging.\n"
# The events of a lab run: a save starts none of them.
RUN_EVENTS = ("lab-created", "turn", "done", "check-passed", "check-failed", "landed", "refused", "lab-deleted")
# The events a task must show, by how it ends. "lab-created" and "lab-deleted" are the lab's life;
# the rest are the worker's turns and the check's verdict; "landed" and "refused" close the task.
REQUIRED = {
    "landed": ("lab-created", "turn", "done", "check-passed", "landed", "lab-deleted"),
    "refused": ("lab-created", "turn", "done", "check-failed", "refused", "lab-deleted"),
    # Conflict refusal is stage 4's dedicated assertion; keep the shared task timeline complete either way.
    "conflict": ("lab-created", "turn", "done", "check-passed", "lab-deleted"),
}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def read_lines(path):
    path = Path(path)
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def ps_lines():
    out = subprocess.run(["ps", "-axww", "-o", "pid=,pgid=,etime=,command="], capture_output=True, text=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


# ---- stages, census, samples, leftovers -------------------------------------------------------

def cmd_stages(args):
    project = read_json(args.project)
    for stage in sorted(project["stages"], key=lambda s: (len(s), s)):
        print(stage)


def composefleet_landed(stage_root):
    """Recognize the landed owner/Herzchen composition by its implementation modules, not a label string."""
    source = Path(stage_root) / "tree" / "src"
    required = (
        source / "otto" / "hostctl" / "product_service.py",
        source / "otto" / "hostctl" / "fleet_landing.py",
        source / "herzchen" / "fleet" / "landing.py",
        source / "herzchen" / "domains" / "work" / "admission.py",
    )
    return all(path.is_file() for path in required)


def cmd_capability(args):
    print("true" if composefleet_landed(args.stage_root) else "false")


def cmd_tasks(args):
    for name in read_json(args.project)["stages"][args.stage]["tasks"]:
        print(name)


def cmd_stage(args):
    value = read_json(args.project)["stages"][args.stage].get(args.key)
    if isinstance(value, list):
        for item in value:
            print(item)
    elif isinstance(value, bool):
        print("true" if value else "false")
    else:
        print("" if value is None else json.dumps(value))


def cmd_stage2_bundle(args):
    """Materialize the disposable Megado source bundle consumed by project register."""
    project = read_json(args.project)
    stage = project.get("stages", {}).get("2", {})
    bundle = Path(args.out)
    bundle.mkdir(parents=True, exist_ok=True)
    tasks = stage.get("tasks", [])
    deps = stage.get("dependencies", {})
    repo = stage.get("repository", "toy")
    branch = stage.get("branch", "canon/main")
    rows = ["# Tasklist: perch-stage2", "", "## Dispatch canary",
            "| id | repo | branch | outcome | deps | route | proof |",
            "|---|---|---|---|---|---|---|"]
    for task in tasks:
        dependency = ", ".join(deps.get(task, [])) or "-"
        rows.append("| %s | %s | %s | Canary dispatch %s | %s | normal | accepted check passes |" %
                    (task, repo, branch, task, dependency))
    texts = {
        "northstar.md": "# PERCH stage 2\n\nProve owner dispatch on staging.\n",
        "agent_goal.md": "# Agent goal: perch-stage2\n\n## Objective\n\nDispatch three admitted canary tasks in dependency order.\n",
        "plan.md": "# Plan\n\nRegister, activate, admit, then observe owner dispatch.\n",
        "status.md": "# Status\n\nStaging canary.\n",
        "manager-brief.md": "# Manager brief\n\nDispatch ready admitted tasks from %s at %s and report any owner dispatch failure.\n" % (repo, branch),
        "tasklist.md": "\n".join(rows) + "\n",
        "reviews/plan-review.md": STAGE2_REVIEW_TEXT,
    }
    for name, content in texts.items():
        target = bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run = {"run_id": "perch-stage2", "mode": "planning_only",
           "roles": {"coordinator": {"model": "claude-haiku-5-5"},
                     "worker_normal": {"model": "claude-haiku-5-5"}},
           "assessment_accounting": stage.get("run_policy", {}).get("assessment_accounting")}
    (bundle / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(str(bundle))


def cmd_stage2_plan_save(args):
    """Give registered canary tasks typed checks and dispatch metadata before activation."""
    stage = read_json(args.project)["stages"]["2"]
    registration = read_json(args.registration)
    project_ref = registration.get("project_ref")
    if not isinstance(project_ref, dict) or project_ref.get("kind") != "work.project" or not project_ref.get("revision"):
        raise ValueError("registration did not return an exact project ref")
    repo, branch = stage["repository"], stage["branch"]
    tasks = []
    for alias in stage["tasks"]:
        tasks.append({
            "id": alias, "title": "Canary dispatch " + alias,
            "instructions": "Canary dispatch " + alias,
            "acceptance": "accepted check passes",
            "fields": {"check": {"argv": ["/usr/bin/true"]}},
            "dependencies": list(stage["dependencies"].get(alias, [])),
            "metadata_namespace": {"otto.plan": {"repo": repo, "branch": branch, "route": "normal"}},
            "custom": {"otto.plan": {"repo": repo, "branch": branch}},
        })
    value = {"project_ref": project_ref,
             "project": {"title": "perch-stage2", "outcome": "Dispatch three admitted canary tasks in dependency order."},
             "tasks": tasks}
    Path(args.out).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stage2_review_ref(status, activation, review_text):
    """Select the exact stored review document reported by the owner."""
    documents = status.get("documents") if isinstance(status, dict) else None
    matches = [row for row in documents or [] if row.get("path") == "reviews/plan-review.md"]
    if len(matches) != 1:
        raise ValueError("project status must contain exactly one stored reviews/plan-review.md")
    row = matches[0]
    expected = hashlib.sha256(review_text.encode("utf-8")).hexdigest()
    if row.get("stored_text_sha256") != expected:
        raise ValueError("stored plan review differs from the registered review document")
    ref = row.get("revision_ref")
    if (not isinstance(ref, dict) or ref.get("kind") != "dat.content.document"
            or not isinstance(ref.get("id"), str) or not ref["id"]
            or not isinstance(ref.get("revision"), str) or not ref["revision"].startswith("rev-")
            or not isinstance(ref.get("authority"), str) or not ref["authority"]):
        raise ValueError("plan review has no exact stored document revision")
    tasks = (((activation or {}).get("activation") or {}).get("steps") or {}).get("tasks") or {}
    refs = tasks.get("task_refs") or {}
    if not refs:
        raise ValueError("activation has no task references to compare with the review")
    if any(ref["kind"] == task.get("kind") or ref["id"] == task.get("id")
           for task in refs.values() if isinstance(task, dict)):
        raise ValueError("plan review must have a different kind and id from every task")
    return ref


def cmd_stage2_review_ref(args):
    status = read_json(args.status)
    activation = read_json(args.activation)
    review_text = (Path(args.bundle) / "reviews" / "plan-review.md").read_text(encoding="utf-8")
    print(json.dumps(stage2_review_ref(status, activation, review_text), separators=(",", ":")))


def stage2_admission_check(response, task_ref):
    if (not isinstance(task_ref, dict) or task_ref.get("kind") != "work.task"
            or any(not isinstance(task_ref.get(key), str) or not task_ref[key]
                   for key in ("authority", "id", "revision"))):
        raise ValueError("activation has no exact canary work task revision")
    if response.get("outcome") not in {"admitted", "already-admitted"}:
        raise ValueError("operator admission did not admit the task: " + repr(response))
    if response.get("admitted_revision") != task_ref.get("revision"):
        raise ValueError("operator admission did not pin the activated task revision")


def stage2_admission_held(response):
    return (isinstance(response, dict) and response.get("outcome") == "held"
            and response.get("reason") == "execution-changing operation requires a closed owner boundary"
            and response.get("effects_started") is False
            and response.get("provider_called") is False)


def cmd_stage2_admission_held(args):
    return 0 if stage2_admission_held(read_json(args.response, {}) or {}) else 1


def stage2_admission_request_id(response, expected=None):
    """Read one retained operator admission; a pending request is never resubmitted."""
    if not isinstance(response, dict):
        raise ValueError("operator admission request has no response object")
    if response.get("outcome") == "pending":
        request_id = response.get("request_id")
        if (response.get("terminal") is not False or not isinstance(request_id, str)
                or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id)):
            raise ValueError("operator admission has an invalid pending request receipt: " + repr(response))
        if expected is not None and request_id != expected:
            raise ValueError("operator admission changed its retained request id")
        return request_id
    if response.get("outcome") not in {"admitted", "already-admitted", "held", "error", "rejected"}:
        raise ValueError("operator admission request has no terminal result: " + repr(response))
    return None


def cmd_stage2_admission_request(args):
    print(stage2_admission_request_id(read_json(args.response, {}) or {}, args.expected_request_id) or "")


def stage2_owner_boundary_closed(status):
    if not isinstance(status, dict):
        return False
    capacity = status.get("native_capacity") or {}
    turns = status.get("manager_turns") or {}
    if not isinstance(capacity, dict) or not isinstance(turns, dict):
        return False
    active = capacity.get("active_or_uncertain")
    managers = turns.get("active")
    return (status.get("state") == "serving"
            and status.get("outcome") in {"running", "serving"}
            and type(active) is int and active == 0
            and capacity.get("holds") == []
            and type(managers) is int and managers == 0
            and status.get("manager_turn_active") is False)


def cmd_stage2_boundary_closed(args):
    return 0 if stage2_owner_boundary_closed(read_json(args.status, {}) or {}) else 1


def cmd_stage2_admission_check(args):
    stage2_admission_check(read_json(args.response, {}) or {}, json.loads(args.task_ref))


def stage2_dispatch_check(status, activation, admission, alias):
    task_refs = (((activation.get("activation") or {}).get("steps") or {}).get("tasks") or {}).get("task_refs") or {}
    expected = task_refs.get(alias) or {}
    stage2_admission_check(admission, expected)
    task = stage2_status_task(status, alias)
    dispatch = task["dispatch"]
    if dispatch["state"] not in {"launched", "landed"} and not (
            alias == "C" and dispatch["state"] == "unknown"):
        raise ValueError("owner has no retained launched dispatch for " + alias)
    if dispatch.get("reason") is not None and dispatch["state"] != "unknown":
        raise ValueError("owner dispatched %s with a failure reason: %s" % (alias, dispatch["reason"]))
    if task.get("repo") != "toy" or task.get("branch") != "canon/main":
        raise ValueError("owner dispatched %s outside the registered toy repository" % alias)
    return task


def cmd_stage2_dispatch_check(args):
    stage2_dispatch_check(read_json(args.status, {}) or {}, read_json(args.activation, {}) or {},
                          read_json(args.admission, {}) or {}, args.task)


def stage2_dispatch_request_id(status, expected=None):
    """Return the retained request to read again, or None for a completed status read."""
    if status.get("outcome") == "pending":
        request_id = status.get("request_id")
        if (status.get("terminal") is not False or not isinstance(request_id, str)
                or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id)):
            raise ValueError("project status has an invalid pending request receipt: " + repr(status))
        if expected is not None and request_id != expected:
            raise ValueError("project status changed its retained request id")
        return request_id
    if status.get("outcome") != "read":
        raise ValueError("project status request did not return a read: " + repr(status))
    return None


def cmd_stage2_dispatch_request(args):
    print(stage2_dispatch_request_id(read_json(args.status, {}) or {}, args.expected_request_id) or "")


def stage2_status_task(status, alias):
    if status.get("outcome") != "read" or not isinstance(status.get("tasks"), list):
        raise ValueError("staging project status lacks the product task dispatch state")
    matches = [task for task in status["tasks"] if isinstance(task, dict) and task.get("id") == alias]
    if len(matches) != 1 or not isinstance(matches[0].get("dispatch"), dict):
        raise ValueError("staging project status lacks one task dispatch state for " + alias)
    if (matches[0]["dispatch"].get("state") not in {"admitted", "launched", "landed", "failed", "unknown"}
            or "reason" not in matches[0]["dispatch"]):
        raise ValueError("staging project status has no recognized dispatch state for " + alias)
    return matches[0]


def stage2_dispatch_no_failure(status, alias):
    task = stage2_status_task(status, alias)
    state = task["dispatch"]["state"]
    if state == "failed" or (state == "unknown" and alias in {"A", "B"}):
        raise ValueError("owner automatic dispatch failed for %s: %s" %
                         (alias, task["dispatch"].get("reason") or "no reason retained"))


def cmd_stage2_dispatch_no_failure(args):
    stage2_dispatch_no_failure(read_json(args.status, {}) or {}, args.task)


def stage2_manager_start_failed(status):
    """Recognize a terminal failure retained for the stage-2 manager start."""
    if status.get("outcome") == "pending" or status.get("terminal") is False:
        return False
    failure_outcomes = {"error", "failed", "refused", "unavailable", "supervisor-failed"}
    if status.get("outcome") in failure_outcomes:
        return True
    for key in ("result", "summary"):
        result = status.get(key)
        if isinstance(result, dict) and result.get("outcome") in failure_outcomes:
            return True
    return False


def stage2_manager_start_state(status, expected_request_id):
    """Classify a retained manager start reply, bound to its original handle."""
    if not isinstance(status, dict):
        raise ValueError("retained manager start status is not an object")
    if status.get("request_id") != expected_request_id:
        raise ValueError("retained manager start status changed its request id")
    if status.get("outcome") == "pending" and status.get("terminal") is not True:
        return "pending"
    return "failure" if stage2_manager_start_failed(status) else "terminal"


def cmd_stage2_manager_start_failed(args):
    if stage2_manager_start_failed(read_json(args.status, {}) or {}):
        raise ValueError("retained manager start reached a terminal failure")


def cmd_stage2_manager_start_state(args):
    print(stage2_manager_start_state(read_json(args.status, {}) or {}, args.expected_request_id))


def stage2_task_complete(project_status, owner_status, alias):
    tasks = {row.get("id"): row for row in project_status.get("tasks") or []}
    held = (owner_status.get("native_capacity") or {}).get("active_or_uncertain")
    return tasks.get(alias, {}).get("lifecycle") == "completed" and type(held) is int and held == 0


def stage2_task_landed(project_status, alias):
    tasks = {row.get("id"): row for row in project_status.get("tasks") or []}
    return tasks.get(alias, {}).get("lifecycle") == "completed"


def cmd_stage2_task_complete(args):
    if not stage2_task_complete(read_json(args.project_status, {}) or {},
                                read_json(args.owner_status, {}) or {}, args.task):
        raise ValueError(args.task + " has not completed and released owner capacity")


def cmd_stage2_task_landed(args):
    if not stage2_task_landed(read_json(args.project_status, {}) or {}, args.task):
        raise ValueError(args.task + " has not completed")


def cmd_stage2_capacity_held(args):
    status = read_json(args.status, {}) or {}
    held = (status.get("native_capacity") or {}).get("active_or_uncertain")
    if type(held) is not int or held < 1:
        raise ValueError("staging owner does not report a held worker capacity slot")


def stage2_census_pids(path):
    result = []
    for line in read_lines(path):
        try:
            result.append(int(line.split(None, 1)[0]))
        except (ValueError, IndexError):
            continue
    return result


def stage2_kill_state(raw):
    raw = Path(raw)
    selected = read_json(raw / "stage2-killed-worker.json", {}) or {}
    killed, owner = selected.get("pid"), selected.get("owner_pid")
    before = read_json(raw / "stage2-capacity-before-kill.json", {}) or {}
    after = read_json(raw / "stage2-capacity-after-kill.json", {}) or {}
    before_pids = stage2_census_pids(raw / "stage2-census-before-kill.txt")
    after_pids = stage2_census_pids(raw / "stage2-census-after-kill.txt")
    held_before = (before.get("native_capacity") or {}).get("active_or_uncertain")
    held_after = (after.get("native_capacity") or {}).get("active_or_uncertain")
    return {
        "slot_released": (type(held_before) is int and type(held_after) is int
                          and held_before > held_after and type(killed) is int and killed in before_pids),
        "killed_worker_absent": type(killed) is int and killed in before_pids and killed not in after_pids,
        "unrelated_processes_alive": type(owner) is int and owner != killed
        and owner in before_pids and owner in after_pids,
        "killed_worker_pid": killed, "owner_pid": owner,
        "before_pids": before_pids, "after_pids": after_pids,
        "held_before": held_before, "held_after": held_after,
    }


def cmd_stage2_kill_check(args):
    state = stage2_kill_state(args.raw)
    if not all(state[key] for key in ("slot_released", "killed_worker_absent", "unrelated_processes_alive")):
        raise ValueError("owner worker kill has not released its slot and preserved the owner: " + repr(state))


def stage2_observations(raw):
    """Project real owner reads and Store snapshots into the stage-2 gate."""
    raw = Path(raw)
    activation = read_json(raw / "stage2-activation.json", {}) or {}
    current_activation = read_json(raw / "stage2-current-activation.json", activation) or activation
    config = read_json(raw / "config.json", {}) or {}
    tasks = config.get("stage2_tasks") or []
    records = []
    owner_reads = []
    for alias in tasks:
        status = read_json(raw / ("stage2-dispatch-" + alias + ".json"), {}) or {}
        admission = read_json(raw / ("stage2-metadata-only-C.json" if alias == "C" and
                                  (raw / "stage2-metadata-only-C.json").exists() else
                                  "stage2-admit-" + alias + ".json"), {}) or {}
        try:
            task = stage2_dispatch_check(status, current_activation if alias == "C" else activation,
                                         admission, alias)
            records.append({"alias": alias, "dispatch_state": task["dispatch"]["state"]})
        except (ValueError, KeyError):
            continue
        owner_reads.append(read_json(raw / ("stage2-owner-" + alias + ".json"), {}) or {})
    observed = {"dispatch": {"dispatched": [row["alias"] for row in records], "records": records}}
    if len(owner_reads) == 3:
        capacity = [row.get("native_capacity") or {} for row in owner_reads]
        manager = [row.get("manager_turns") or {} for row in owner_reads]
        if all(isinstance(row.get("active_or_uncertain"), int) for row in capacity) and all(
                isinstance(row.get("limit"), int) and isinstance(row.get("active"), int) for row in manager):
            observed["capacity"] = {
                "pool_peak": max(row["active_or_uncertain"] for row in capacity),
                "manager_reserve_remaining": min(row["limit"] - row["active"] for row in manager),
                "source": "staging service status after each retained worker dispatch"}
    before = read_json(raw / "stage2-store-before.json", {}) or {}
    after = read_json(raw / "stage2-store-after.json", {}) or {}
    store_events, matched, event_errors = stage2_event_evidence(raw, config)
    dispatch_in_store = sum((alias, "dispatch") in matched for alias in tasks)
    admitted = sorted(alias for task_id, alias in (store_events.get("tasks") or {}).items()
                      if alias in tasks and (store_events.get("revisions") or {}).get(task_id)
                      and (store_events["revisions"][task_id][-1] or {}).get("admitted_revision"))
    observed["store_snapshots"] = [
        {"integrity": before.get("integrity"), "rows": before.get("rows")},
        {"integrity": after.get("integrity"), "rows": after.get("rows"),
         "dispatch_events": dispatch_in_store, "admitted_tasks": admitted,
         "event_errors": event_errors}]
    if (raw / "stage2-killed-worker.json").exists():
        state = stage2_kill_state(raw)
        observed["worker_kill"] = {key: state[key] for key in
                                    ("slot_released", "killed_worker_absent", "unrelated_processes_alive",
                                     "held_before", "held_after")}
        observed["census"] = {"killed_worker_pid": state["killed_worker_pid"],
                              "after_pids": state["after_pids"],
                              "unrelated_started_pids": [state["owner_pid"]] if state["owner_pid"] else []}
    return observed


def cmd_stage2_observations(args):
    Path(args.raw, "stage2-observations.json").write_text(
        json.dumps(stage2_observations(args.raw), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stage2_owner_labs_snapshot(root):
    """List task labs and the contents of the owner's control directories."""
    root = Path(root)
    result = {"root": str(root), "exists": root.exists(), "entries": [], "labs": [],
              "controls": {}, "unexpected": []}
    if not root.exists():
        return result
    if not root.is_dir():
        result["unexpected"].append("root is not a directory")
        return result
    for namespace in sorted(root.iterdir()):
        result["entries"].append(namespace.name)
        if namespace.is_symlink() or not namespace.is_dir():
            result["unexpected"].append(namespace.name)
            continue
        for child in sorted(namespace.iterdir()):
            relative = str(child.relative_to(root))
            if child.is_symlink() or not child.is_dir():
                result["unexpected"].append(relative)
            elif child.name in {".creating", ".landed", ".locks"}:
                result["controls"][relative] = [
                    {"name": entry.name, "kind": ("symlink" if entry.is_symlink() else
                     "directory" if entry.is_dir() else "file" if entry.is_file() else "other")}
                    for entry in sorted(child.iterdir())]
            else:
                result["labs"].append(relative)
    return result


def stage2_owner_lab_evidence(raw):
    """Judge owner lab snapshots and describe the same evidence for the report."""
    mapped = (read_json(raw / "stage2-repository-map.json", {}) or {}).get("repositories", {}).get("toy")
    expected_root = str(mapped) + ".otto-labs" if isinstance(mapped, str) and mapped else None
    activation = read_json(raw / "stage2-activation.json", {}) or {}
    task_refs = (((activation.get("activation") or {}).get("steps") or {}).get("tasks") or {}).get("task_refs") or {}
    c_task_id = (task_refs.get("C") or {}).get("id")
    killed_marker = (read_json(raw / "stage2-killed-worker.json", {}) or {}).get("marker")
    final_status = read_json(raw / "stage2-dispatch-status.json", {}) or {}
    c_status = next((task for task in final_status.get("tasks") or []
                     if isinstance(task, dict) and task.get("id") == "C"), {})
    retained_c = None
    if (expected_root and c_task_id and isinstance(killed_marker, str)
            and Path(killed_marker).name == ".perch-worker-C.pid"
            and (c_status.get("dispatch") or {}).get("state") == "unknown"
            and c_status.get("lifecycle") == "pending"):
        try:
            relative = Path(killed_marker).parent.relative_to(expected_root)
            if (len(relative.parts) == 2 and relative.name == c_task_id
                    and all(part not in {".", ".."} for part in relative.parts)):
                retained_c = str(relative)
        except ValueError:
            pass

    failures, summary, retained = [], [], []
    for label, when in (("before", "before the first harness step"), ("after", "after down")):
        snapshot_name = "stage2-owner-labs-" + label + ".json"
        owner_labs = read_json(raw / snapshot_name, {}) or {}
        if (owner_labs.get("root") != expected_root or not isinstance(owner_labs.get("exists"), bool)
                or not isinstance(owner_labs.get("entries"), list)
                or not isinstance(owner_labs.get("labs"), list)
                or not isinstance(owner_labs.get("unexpected"), list)):
            failures.append("owner %s lab-root listing missing, incomplete or names another root" % label)
            summary.append("- owner lab root %s: snapshot missing or incomplete ([raw snapshot](raw/%s))"
                           % (when, snapshot_name))
            continue
        summary.append("- owner lab root %s: `%s` (%s; [raw snapshot](raw/%s))" % (
            when, expected_root, "present" if owner_labs["exists"] else "absent", snapshot_name))
        if not owner_labs["exists"] and (owner_labs["entries"] or owner_labs["labs"]
                                         or owner_labs["unexpected"] or owner_labs.get("controls")):
            failures.append("owner %s absent lab root has listed entries" % label)
        failures.extend("owner %s unexpected lab-root entry %s" % (label, name)
                        for name in owner_labs["unexpected"])
        task_labs = []
        for name in owner_labs["labs"]:
            if (not isinstance(name, str) or len(Path(name).parts) != 2
                    or any(part in {".", ".."} for part in Path(name).parts)):
                failures.append("owner %s invalid lab entry %r" % (label, name))
            elif Path(name).name in {".creating", ".landed", ".locks"}:
                failures.append("owner %s control directory %s was listed as a lab; its contents were not recorded"
                                % (label, name))
                summary.append("- owner control directory %s `%s`: contents not recorded" % (when, name))
            elif label == "after" and name == retained_c:
                retained.append("C %s" % name)
                task_labs.append("`%s` (expected retained C lab: worker killed; task pending, dispatch unknown)" % name)
            else:
                failures.append("owner %s lab %s" % (label, name))
                task_labs.append("`%s` (unexpected)" % name)
        summary.append("- owner task labs %s: %s" % (when, ", ".join(task_labs) or "none"))
        controls = owner_labs.get("controls")
        if not isinstance(controls, dict):
            if owner_labs["exists"]:
                failures.append("owner %s control directory contents not recorded" % label)
                summary.append("- owner control directory contents %s: not recorded" % when)
            else:
                summary.append("- owner control directories %s: none (root absent)" % when)
            controls = {}
        elif not controls:
            summary.append("- owner control directories %s: none" % when)
        for path, contents in sorted(controls.items()):
            parts = Path(path).parts if isinstance(path, str) else ()
            if (len(parts) != 2 or parts[0] not in owner_labs["entries"]
                    or parts[1] not in {".creating", ".landed", ".locks"}
                    or not isinstance(contents, list)):
                failures.append("owner %s invalid control directory %r" % (label, path))
                summary.append("- owner control directory %s: invalid entry %r" % (when, path))
                continue
            described = []
            for entry in contents:
                name = entry.get("name") if isinstance(entry, dict) else None
                kind = entry.get("kind") if isinstance(entry, dict) else None
                if (not isinstance(name, str) or not name or Path(name).name != name
                        or name in {".", ".."} or kind not in {"file", "directory", "symlink", "other"}):
                    failures.append("owner %s invalid control entry in %s: %r" % (label, path, entry))
                    described.append("invalid entry %r" % entry)
                    continue
                described.append("`%s` (%s)" % (name, kind))
                if parts[1] in {".creating", ".landed"}:
                    failures.append("owner %s stale %s marker %s/%s" % (label, parts[1], path, name))
                elif kind != "file" or not name.endswith(".lock") or name == ".lock":
                    failures.append("owner %s unexpected lock control entry %s/%s (%s)" % (
                        label, path, name, kind))
            summary.append("- owner control directory %s `%s`: %s" % (
                when, path, ", ".join(described) or "empty"))
    detail = ("no unexpected owner labs or stale control markers; retained recovery lab " + ", ".join(retained)
              if retained else "no owner task labs or stale control markers left")
    return failures, detail, summary


def cmd_stage2_owner_labs(args):
    Path(args.out).write_text(json.dumps(stage2_owner_labs_snapshot(args.root), sort_keys=True) + "\n",
                              encoding="utf-8")


def cmd_field(args):
    print(read_json(args.project)[args.key])


def cmd_portfolio(args):
    """The portfolio a stage's host is admitted with, printed for the saves to name."""
    print(portfolio_id(read_json(args.project)["stages"][args.stage]["host"]))


def cmd_admission(args):
    """Exit 0 when the owner admitted the stage's host and named its portfolio; 1 otherwise, with the reason on stderr."""
    failures = admission_failures(Path(args.raw), read_json(args.project)["stages"][args.stage].get("host"))
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


def cmd_save_doc(args):
    """One of a stage's save documents, with the project ref of an earlier save's response when it is an edit or a stale base."""
    document = read_json(args.project)["stages"][args.stage]["saves"][args.name]
    if args.ref_from:
        ref = (read_json(args.ref_from, {}) or {}).get("project_ref")
        if not ref:
            raise SystemExit("no project_ref in %s" % args.ref_from)
        document = dict(document, project_ref=ref)
    Path(args.out).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_census(args):
    mine = str(os.getpid())
    root = args.stage_root or ""
    groups_file = getattr(args, "groups_file", "")
    records = (read_json(groups_file, {}) or {}) if groups_file else {}
    pgids = {str(row.get("pgid")) for row in records.values()
             if isinstance(row, dict) and type(row.get("pgid")) is int and row["pgid"] > 0}
    # perch's own tools (this script, sampling or reporting) are not the Otto's processes.
    lines = [line for line in ps_lines() if line.split(None, 1)[0] != mine and "perch_report.py" not in line
             and ((root and root in line) or any(marker in line for marker in CENSUS_MARKERS)
                  or len(line.split(None, 2)) > 1 and line.split(None, 2)[1] in pgids)]
    Path(args.out).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return 1 if getattr(args, "fail_workers", False) and worker_processes(lines) else 0


def worker_processes(lines):
    """All known harness/fake-Claude workers, regardless of which staging root owns them."""
    return [line for line in lines if "fake_worker.py" in line or "perch-fake-claude" in line]


def recorded_groups_gone(records, lines):
    """Whether no process remains in any group named by the pre-down custody record."""
    pgids = {row.get("pgid") for row in records.values()
             if isinstance(row, dict) and type(row.get("pgid")) is int and row["pgid"] > 0}
    remaining = []
    for line in lines:
        fields = line.split(None, 2)
        if len(fields) >= 2:
            try:
                pgid = int(fields[1])
            except ValueError:
                continue
            if pgid in pgids:
                remaining.append(int(fields[0]))
    return not remaining, sorted(set(remaining))


def store_bytes(store):
    return sum(os.path.getsize(p) for p in (store, store + "-wal") if os.path.exists(p))


def read_status(path):
    """The staging status the sampler read with `staging.sh status`; a missing or half-written one reads as none."""
    if not path:
        return {}
    try:
        return read_json(path, {}) or {}
    except ValueError:
        return {}


def cmd_sample(args):
    raw = Path(args.raw)
    stage_root = Path(args.stage_root)
    disk = shutil.disk_usage(stage_root) if stage_root.exists() else None
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    stage = (read_json(Path(args.raw) / "config.json", {}) or {}).get("stage")
    units = ([line for line in ps_lines() if "fake_worker.py" in line and "--lab" in line and args.canary in line]
             if stage != "2" else None)
    status = read_status(args.status)
    line = {
        "at": now_iso(),
        "disk_free_kb": disk.free // 1024 if disk else None,
        "swap": swap,
        "pool_units": len(units) if units is not None else None,
        "store_bytes": store_bytes(str(stage_root / "store" / "staging.store")),
        "staging_state": status.get("outcome", "unavailable"),
        "staging_generation": status.get("generation"),
    }
    with open(raw / "samples.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def cmd_snapshot(args):
    canon, labs = Path(args.canon), Path(args.labs)
    found = []
    porcelain = subprocess.run(["git", "-C", str(canon), "worktree", "list", "--porcelain"],
                               capture_output=True, text=True).stdout
    for line in porcelain.splitlines():
        if line.startswith("worktree ") and Path(line[len("worktree "):]).resolve() != canon.resolve():
            found.append("worktree " + line[len("worktree "):])
    branches = subprocess.run(["git", "-C", str(canon), "branch", "--list", "lab/*", "--format=%(refname:short)"],
                              capture_output=True, text=True).stdout
    found += ["branch " + name for name in branches.split()]
    if labs.exists():
        found += ["lab-folder " + str(p) for p in sorted(labs.iterdir())]
    Path(args.out).write_text("".join(item + "\n" for item in found), encoding="utf-8")


# ---- the staging root at rest, and the Store at rest -------------------------------------------

def store_snapshot(store):
    """The Store's size, pages, integrity and rows per table, read through a read-only connection."""
    path = Path(store)
    if not path.exists():
        return {"error": "no Store file"}
    try:
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {
                "error": None, "bytes": store_bytes(store), "page_size": con.execute("PRAGMA page_size").fetchone()[0],
                "page_count": con.execute("PRAGMA page_count").fetchone()[0],
                "freelist_count": con.execute("PRAGMA freelist_count").fetchone()[0],
                "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
                "rows": {name: con.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0] for name in names},
            }
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return {"error": str(exc)}


def cmd_store(args):
    snapshot = store_snapshot(args.store)
    if args.admission:
        admission = read_json(args.admission, {}) or {}
        snapshot["admission_outcome"] = admission.get("outcome")
    if args.refs:
        refs_docs = [read_json(path, {}) or {} for path in args.refs]
        refs_doc = refs_docs[-1]
        refs = [ref for document in refs_docs for ref in
                (document.get("project_ref"), *(document.get("task_refs") or {}).values())]
        snapshot["records"] = {}
        try:
            con = sqlite3.connect(Path(args.store).resolve().as_uri() + "?mode=ro", uri=True)
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                key = "%s:%s@%s" % (ref.get("kind"), ref.get("id"), ref.get("revision"))
                row = con.execute("SELECT current_revision,payload_json FROM identities WHERE authority=? AND kind=? AND id=?",
                                  (ref.get("authority"), ref.get("kind"), ref.get("id"))).fetchone()
                payload = None
                if row and (not ref.get("revision") or row[0] == ref.get("revision")):
                    payload = json.loads(row[1])
                elif ref.get("revision"):
                    kept = con.execute("SELECT reference_json FROM record_references WHERE reference_key LIKE 'content:%' AND authority=? AND kind=? AND id=? AND revision=?",
                                       (ref.get("authority"), ref.get("kind"), ref.get("id"), ref.get("revision"))).fetchone()
                    if kept:
                        payload = json.loads(kept[0]).get("content")
                snapshot["records"][key] = {"ref": ref, "payload": payload} if payload is not None else None
                if ref.get("kind", "").endswith("project") and payload is not None:
                    current = con.execute("SELECT current_revision FROM identities WHERE authority=? AND kind=? AND id=?",
                                          (ref.get("authority"), ref.get("kind"), ref.get("id"))).fetchone()
                    snapshot["project_revision"] = current[0] if current else None
            snapshot["event_types"] = [row[0] for row in con.execute("SELECT event_type FROM events ORDER BY append_position")]
            con.close()
        except sqlite3.DatabaseError as exc:
            snapshot["records_error"] = str(exc)
    Path(args.out).write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_at_rest(args):
    root = Path(args.stage_root)
    run_dir = root / "home" / "run"
    error = None
    names = sorted(os.listdir(run_dir)) if run_dir.is_dir() else []
    service = read_json(run_dir / "service.json", None) if run_dir.is_dir() else None
    sockets = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if Path(dirpath, d) != root / "tree"]  # the tree is a checkout, not state
        sockets += [str(Path(dirpath, f)) for f in filenames if stat.S_ISSOCK(os.lstat(Path(dirpath, f)).st_mode)]
    holders = {}
    store_dir = root / "store"
    for path in sorted(store_dir.iterdir()) if store_dir.is_dir() else []:
        try:
            found = subprocess.run(["lsof", "-t", str(path)], capture_output=True, text=True)
            holders[path.name] = found.stdout.split()
        except OSError as exc:
            error = "lsof could not run: %s" % exc
    canary = root / "perch-canary"
    record = {"home_run": names, "service_state": (service or {}).get("state"), "sockets": sockets,
              "store_holders": holders, "perch_canary": sorted(os.listdir(canary)) if canary.is_dir() else [],
              "error": error}
    Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seeded_read(path):
    """The observation a stage-1 fault changes. A run without it has nothing to seed, so the fault is refused, not written."""
    value = read_json(path, None)
    if value is None:
        raise ValueError("no %s in this run to seed a fault into" % Path(path).name)
    return value


def seed(raw, kind):
    """A seeded fault in one observation of the run, so that the assertion which reads it must turn red."""
    raw = Path(raw)
    if kind == "conflict":
        path = raw / "events.tsv"
        lines = read_lines(path)
        kept = [line for line in lines if not ("\tlanding-conflict\t" in line)]
        if len(kept) == len(lines):
            raise ValueError("no landing-conflict event in this run to seed a conflict fault into")
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    elif kind == "owner":
        path = raw / "events.tsv"
        lines = read_lines(path)
        kept = [line for line in lines if "\towner-dispatch-launched\t" not in line]
        if len(kept) == len(lines):
            raise ValueError("no owner-dispatch-launched event in this run to seed an owner-path fault into")
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    elif kind == "census":
        (raw / "census.up.txt").write_text("", encoding="utf-8")
    elif kind == "store":
        timeline = read_json(raw / "timeline.json", {}) or {}
        config = read_json(raw / "config.json", {}) or {}
        if "store_events_min" in (config.get("store") or {}):
            tasks = timeline.get("work_tasks") or []
            if not tasks:
                raise ValueError("no stored work task to seed")
            tasks[0]["admitted_revision"] = None
        else:
            timeline["store_events"] = timeline.get("store_events", 0) + 1
        (raw / "timeline.json").write_text(json.dumps(timeline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "restart":
        snap = read_json(raw / "store-restarted.json", {}) or {}
        rows = snap.get("rows", {})
        table = next((name for name in sorted(rows) if rows[name] > 0), None)
        if table is None:
            raise ValueError("no table with rows to seed a restart fault into")
        rows[table] -= 1
        (raw / "store-restarted.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "typed":
        snap = seeded_read(raw / "store-after-edit.json")
        records = snap.get("records") or {}
        ids = {str(ref.get("id")) for ref in (seeded_read(raw / "save-edit.json").get("task_refs") or {}).values()
               if isinstance(ref, dict)}
        key = next((key for key in records if key.split(":", 1)[-1].split("@", 1)[0] in ids and records[key]), None)
        if key is None:
            raise ValueError("no typed task record in the Store snapshot")
        records[key]["ref"]["kind"] = ""
        (raw / "store-after-edit.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "canary":
        snap = seeded_read(raw / "store-after-create.json")
        records = snap.get("records") or {}
        ids = {str(ref.get("id")) for ref in (seeded_read(raw / "save-create.json").get("task_refs") or {}).values()
               if isinstance(ref, dict)}
        row = next((value for key, value in records.items() if key.split(":", 1)[-1].split("@", 1)[0] in ids and value), None)
        if not row:
            raise ValueError("no task record in the create Store snapshot")
        row["payload"].setdefault("metadata_namespaces", {})["otto.plan"] = {}
        (raw / "store-after-create.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "readback":
        snap = seeded_read(raw / "store-after-edit.json")
        snap["readback_available"] = False
        (raw / "store-after-edit.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "edit":
        snap = seeded_read(raw / "store-after-edit.json")
        refs = (seeded_read(raw / "save-edit.json").get("task_refs") or {})
        a_id = (refs.get("A") or {}).get("id")
        key = next((key for key in (snap.get("records") or {})
                    if key.split(":", 1)[-1].split("@", 1)[0] == str(a_id)), None)
        if key is None:
            raise ValueError("no edited A record in the Store snapshot")
        snap["records"][key]["payload"]["title"] = "corrupted title"
        (raw / "store-after-edit.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "nothing":
        snap = seeded_read(raw / "store-after-edit.json")
        snap.setdefault("event_types", []).append("work.dispatched")
        (raw / "store-after-edit.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "revision":
        snap = seeded_read(raw / "store-after-edit.json")
        snap["project_revision"] = (seeded_read(raw / "save-create.json").get("project_ref") or {}).get("revision")
        (raw / "store-after-edit.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "history":
        snap = seeded_read(raw / "store-after-edit.json")
        ref = (seeded_read(raw / "save-create.json").get("project_ref") or {})
        key = "%s:%s@%s" % (ref.get("kind"), ref.get("id"), ref.get("revision"))
        if key not in (snap.get("records") or {}):
            key = next((key for key in (snap.get("records") or {}) if key.endswith(":" + str(ref.get("id")) + "@" + str(ref.get("revision")))), None)
        if key is None:
            raise ValueError("no project history record in the edit Store snapshot")
        del snap["records"][key]
        (raw / "store-after-edit.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "stale":
        snap = seeded_read(raw / "store-after-stale.json")
        snap["stale_refused"] = False
        (raw / "store-after-stale.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "admit":
        snap = seeded_read(raw / "store-before-saves.json")
        snap["admission_outcome"] = "unavailable"
        (raw / "store-before-saves.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "growth":
        # The Store after the stale save holds one row more than after the edit, so a refused save appears to write.
        snap = seeded_read(raw / "store-after-stale.json")
        rows = snap.get("rows", {})
        table = next(iter(sorted(rows)), None)
        if table is None:
            raise ValueError("no table with rows to seed a growth fault into")
        rows[table] += 1
        (raw / "store-after-stale.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "stage2_canary":
        config = read_json(raw / "config.json", {}) or {}
        config["stage2_dependencies"] = {"B": []}
        (raw / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "stage2_scenario":
        notes = read_json(raw / "notes.json", {}) or {}
        notes["admit-and-dispatch"] = "skipped: seeded scenario omission"
        (raw / "notes.json").write_text(json.dumps(notes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "stage2_review":
        ref = seeded_read(raw / "stage2-review-ref.json")
        ref["id"] = "wrong-review-document"
        (raw / "stage2-review-ref.json").write_text(json.dumps(ref, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "admission_presence":
        path = raw / "stage2-operator-admission.jsonl"
        lines = [json.loads(line) for line in read_lines(path)]
        if not lines:
            raise ValueError("no operator admission log to seed")
        lines[0]["prover_result"] = "declined"
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    elif kind in {"admit_order", "unadmitted", "reserve"}:
        name = {"admit_order": "stage2-store-events.json",
                "unadmitted": "stage2-edited-C-no-launch.json",
                "reserve": "stage2-contention-owner.json"}[kind]
        value = seeded_read(raw / name)
        if kind == "admit_order":
            event = next((row for row in value.get("events") or [] if row.get("alias") == "C"
                          and row.get("event_type") == "work.assignment.dispatched"), None)
            if event is None:
                raise ValueError("no C Store dispatch to seed")
            event["recorded_at"] = "0001-01-01T00:00:00Z"
        elif kind == "unadmitted":
            event = next((row for row in value.get("tasks") or [] if row.get("id") == "C"), None)
            if event is None:
                raise ValueError("no edited C product status to seed")
            event["dispatch"]["state"] = "launched"
        else:
            value["manager_turn_active"] = False
        (raw / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind in {"worker_kill", "store_snapshot", "stage2_census"}:
        stage2 = read_json(raw / "stage2-observations.json", {}) or {}
        key = {"worker_kill": "worker_kill", "store_snapshot": "store_snapshots", "stage2_census": "census"}[kind]
        if key not in stage2:
            raise ValueError("no %s observation in this run to seed a fault into" % key)
        value = stage2[key]
        if kind == "store_snapshot" and value:
            value = value[-1]
        if kind == "worker_kill":
            value["slot_released"] = False
        elif kind == "store_snapshot":
            value["integrity"] = "corrupt"
        else:
            value["unrelated_started_pids"] = []
        (raw / "stage2-observations.json").write_text(json.dumps(stage2, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        raise ValueError("no seeded observation fault called %s" % kind)


def cmd_seed(args):
    seed(args.raw, args.fault)


def cmd_note(args):
    path = Path(args.raw, "notes.json")
    notes = read_json(path, {}) or {}
    try:
        notes[args.key] = json.loads(args.value)
    except ValueError:
        notes[args.key] = args.value
    path.write_text(json.dumps(notes, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---- the Store's timelines (herzchen's read) ---------------------------------------------------

def cmd_timeline(args):
    # The Store is opened the way the owner opens it: with the host's complete domain set (Herzchen
    # itself imports nothing from Otto; this bootstrap script may).
    sys.path.insert(0, args.src)
    from herzchen.domains.work.timeline import timelines
    from herzchen.kernel import Store
    from otto.hostctl.owner import host_domains

    result = {"store": args.store, "store_events": 0, "tasks": [], "work_tasks": [], "error": None}
    if not Path(args.store).exists():
        result["error"] = "no Store file"
    else:
        store = Store.open(args.store, authority=args.authority, expected_domains=host_domains())
        try:
            result["store_events"] = len(store.list_events())
            from herzchen.domains.work.admission import admitted_revision
            page = store.consumer().read_identity_page(kind="work.task", limit=100)
            if page["next_cursor"] is not None or page["held"]:
                raise ValueError("the Store has more than 100 or unreadable work tasks")
            for task in page["records"]:
                result["work_tasks"].append({"alias": task.payload.get("alias"),
                                             "id": task.ref.id,
                                             "admitted_revision": admitted_revision(task.payload)})
            assignment_page = store.consumer().read_identity_page(kind="wrk.assignment", limit=100)
            if assignment_page["next_cursor"] is not None or assignment_page["held"]:
                raise ValueError("the Store has more than 100 or unreadable assignments")
            assignment_scopes = {row.ref.id: row.payload.get("scope")
                                 for row in assignment_page["records"]}
            for timeline in timelines(store):
                scope = assignment_scopes.get(timeline.task_id)
                result["tasks"].append({
                    "task_id": timeline.task_id,
                    "scope_task_id": scope.get("id") if isinstance(scope, dict)
                                     and scope.get("kind") == "work.task" else None,
                    "complete": timeline.complete,
                    "gaps": [[g.stream, g.gap_from, g.gap_to] for g in timeline.gaps],
                    "events": [{"stream": e.stream, "sequence": e.sequence, "event_type": e.event_type,
                                "operation": e.operation, "recorded_at": e.recorded_at} for e in timeline.events],
                })
        finally:
            store.close()
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_init(args):
    project = read_json(args.project)
    stage = project["stages"][args.stage]
    # Stage 2 is driven through the staging owner; its task lifecycle is in stage2-observations.json,
    # not in the local fake-worker timeline used by stages 0 and 1.
    tasks = [] if args.stage == "2" else [{"name": name, "expect": project["tasks"][name]["expect"],
                                             "landing_conflict": project["tasks"][name].get("landing_conflict", False)}
                                            for name in stage["tasks"]]
    config = {
        "stage": args.stage, "fake": args.fake, "tasks": tasks,
        "check": "/usr/bin/true" if args.stage == "2" else project["check"], "stage_root": args.stage_root,
        "host": stage.get("host"),
        "pool_limit": stage.get("pool_limit", project["pool_limit"]), "manager_reserve": stage.get("manager_reserve"),
        "scenarios": stage.get("scenarios", []),
        "stage2_tasks": stage.get("tasks") if args.stage == "2" else None,
        "stage2_admitted": (stage.get("admission") or {}).get("admitted") if args.stage == "2" else None,
        "stage2_dependencies": stage.get("dependencies") if args.stage == "2" else None,
        "stage2_expected_completed": stage.get("expected_completed") if args.stage == "2" else None,
        "stage2_kill_task": stage.get("kill_task") if args.stage == "2" else None,
        "store": stage.get("store"), "faults": [f for f in args.faults.split(",") if f],
        "staging_restart": args.staging_restart, "staging_sha": args.staging_sha,
        "canon_main_sha": args.canon_main_sha, "started_at": args.started_at, "finished_at": now_iso(),
    }
    Path(args.raw, "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---- observations ------------------------------------------------------------------------------

def observed(raw):
    """Every observed event of the run: perch's own record and the worker's JSON lines, in time order."""
    events = []
    for line in read_lines(raw / "events.tsv"):
        at, task, kind, detail = (line.split("\t") + ["", "", "", ""])[:4]
        events.append({"at": at, "task": task, "kind": kind, "detail": detail, "source": "perch"})
    for path in sorted(raw.glob("worker-*.jsonl")):
        for line in read_lines(path):
            event = json.loads(line)
            detail = event.get("sha") or ("%s turns" % event["turns"] if "turns" in event else event.get("detail", ""))
            events.append({"at": event["at"], "task": event["task"], "kind": event["kind"], "detail": detail, "source": "worker"})
    return sorted(events, key=lambda e: e["at"])


def started_pids(raw):
    return {int(line.split("\t")[0]) for line in read_lines(raw / "started.tsv")}


def pids_of(lines):
    return {int(line.split(None, 1)[0]) for line in lines}


def leaks(raw, config):
    """Processes still running after down under this root, or any recorded worker group/known worker."""
    root = config.get("stage_root")
    lines = read_lines(raw / "census.after.txt")
    records = read_json(raw / "recorded-process-groups.json", {}) or {}
    gone, _remaining = recorded_groups_gone(records, lines)
    pgids = {row.get("pgid") for row in records.values()
             if isinstance(row, dict) and type(row.get("pgid")) is int and row["pgid"] > 0}
    leaked = [line for line in lines if (root and root in line)
              or (not root and any(m in line for m in LEAK_MARKERS))
              or line in worker_processes(lines)]
    if not gone:
        for line in lines:
            fields = line.split(None, 2)
            if len(fields) >= 2 and fields[1].isdigit() and int(fields[1]) in pgids and line not in leaked:
                leaked.append(line)
    return leaked


# ---- assertions --------------------------------------------------------------------------------

LIFECYCLE_OK = {
    "status-while-up": "running; the holder pid, the census, the generation and the Store authority agree",
    "status-after-kill-is-stale": "stale after the KILL, and the holder is not alive",
    "restart-after-kill-keeps-store": "running at generation +1 after the restart; integrity ok; row counts unchanged",
    "status-after-stop": "closed after down",
    "refused-start-names-its-reason": "the second start was refused with exit 3 and owner_service_running",
}


def lifecycle_failures(raw, notes):
    """The staging-lifecycle scenario's failures, by assertion name. perch.sh records each observation in raw/."""
    up = read_json(raw / "status-up.json", None)
    staged = read_json(raw / "staging-up.json", None)
    installed = read_json(raw / "installation.json", None)
    generation = read_lines(raw / "generation-up.txt")
    census = pids_of(read_lines(raw / "census.up.txt"))
    killed = read_json(raw / "status-killed.json", None)
    before = read_json(raw / "store-before-kill.json", None)
    restarted = read_json(raw / "status-restarted.json", None)
    after = read_json(raw / "store-restarted.json", None)
    stopped = read_json(raw / "status-stopped.json", None)
    refused = read_json(raw / "refused.json", None)
    found = {name: [] for name in LIFECYCLE}

    if up is None or staged is None:
        found["status-while-up"].append("the status or staging.json was not recorded while up")
    else:
        pid = staged.get("pid")
        holder_pid = (up.get("holder") or {}).get("pid")
        if up.get("outcome") != "running":
            found["status-while-up"].append("outcome %s while up, not running" % up.get("outcome"))
        if holder_pid != pid:
            found["status-while-up"].append("holder pid %s, but staging.json names %s" % (holder_pid, pid))
        if pid not in census:
            found["status-while-up"].append("pid %s is not in the census taken while up" % pid)
        if str(up.get("generation")) != (generation[0] if generation else None):
            found["status-while-up"].append("generation %s, but run/generation says %s"
                                            % (up.get("generation"), generation[0] if generation else None))
        authority = ((installed or {}).get("store") or {}).get("authority")
        if (up.get("store") or {}).get("authority") != authority:
            found["status-while-up"].append("store authority %s, but installation.json says %s"
                                            % ((up.get("store") or {}).get("authority"), authority))

    if killed is None:
        found["status-after-kill-is-stale"].append("no status was recorded after the KILL")
    else:
        if killed.get("outcome") != "stale":
            found["status-after-kill-is-stale"].append("outcome %s after the KILL, not stale" % killed.get("outcome"))
        if killed.get("holder_alive") is not False:
            found["status-after-kill-is-stale"].append("holder_alive is %s after the KILL" % killed.get("holder_alive"))

    if killed is None or before is None or restarted is None or after is None:
        found["restart-after-kill-keeps-store"].append("the status or Store before or after the KILL was not recorded")
    else:
        if notes.get("restart_after_kill_rc") != 0:
            found["restart-after-kill-keeps-store"].append("the start after the KILL exited %s" % notes.get("restart_after_kill_rc"))
        if restarted.get("outcome") != "running":
            found["restart-after-kill-keeps-store"].append("outcome %s after the restart, not running" % restarted.get("outcome"))
        expected = (killed.get("generation") or 0) + 1
        if restarted.get("generation") != expected:
            found["restart-after-kill-keeps-store"].append("generation %s after the restart, expected %s"
                                                           % (restarted.get("generation"), expected))
        if after.get("integrity") != "ok":
            found["restart-after-kill-keeps-store"].append("PRAGMA integrity_check says %s" % after.get("integrity"))
        if after.get("rows") != before.get("rows"):
            tables = sorted(set(before.get("rows", {})) | set(after.get("rows", {})))
            changed = ["%s %s -> %s" % (t, before["rows"].get(t), after["rows"].get(t)) for t in tables
                       if before["rows"].get(t) != after["rows"].get(t)]
            found["restart-after-kill-keeps-store"].append("row counts changed: " + "; ".join(changed))

    if stopped is None:
        found["status-after-stop"].append("no status was recorded after down")
    elif stopped.get("outcome") != "closed":
        found["status-after-stop"].append("outcome %s after down, not closed" % stopped.get("outcome"))

    if notes.get("refused_start_rc") in (None, 0):
        found["refused-start-names-its-reason"].append(
            "the second start was not refused (exit %s)" % notes.get("refused_start_rc"))
    if refused is None:
        found["refused-start-names-its-reason"].append("no refusal record: run/staging.refused.json is missing")
    else:
        if refused.get("exit_code") != 3:
            found["refused-start-names-its-reason"].append("refusal exit code %s, not 3" % refused.get("exit_code"))
        code = (refused.get("error") or {}).get("code")
        if code != "owner_service_running":
            found["refused-start-names-its-reason"].append("refusal error.code is %s, not owner_service_running" % code)
    return found


STAGE1_OK = {
    "portfolio-admitted-before-saves": "the owner admitted the stage's host, naming its portfolio, before the first save",
    "canary-has-three-planned-tasks": "the three-task create and edit fixtures satisfy the plan and dependency contract",
    "show-readback-available": "owner-lane show read-back returned all three persisted tasks",
    "store-has-typed-tasks": "the Store snapshot contains the three typed task records at their saved refs",
    "edit-is-persisted": "the Store's current task records contain the title, size and dependency edits",
    "nothing-runs": "every save reports dispatch and launch false, and no lab, worker or turn ran",
    "edit-makes-revision": "saving one edited task moved the project to a later revision",
    "project-history-keeps-old-revision": "the Store still reads the create revision after the edit",
    "stale-save-refused": "a save from the create's base is refused as stale_base with a diff",
    "store-growth-per-save": "the create and the edit each added rows, the stale save added none, none over the stage's limit",
}


def portfolio_id(host):
    """The portfolio the owner names for an admitted host: <kind>-portfolio (owner.py, where a host is admitted)."""
    return host + "-portfolio"


def admission_failures(raw, host):
    """Whether raw/admission.json, the owner's answer to admit-host, admitted HOST and named its portfolio."""
    admitted = read_json(raw / "admission.json", None)
    if admitted is None:
        return ["the admission was not recorded"]
    failures = []
    if admitted.get("outcome") not in ("admitted", "replayed"):
        failures.append("admit-host outcome is %s, not admitted" % admitted.get("outcome"))
    got = ((admitted.get("host") or {}).get("portfolio_ref") or {}).get("id")
    if host is None or got != portfolio_id(host):
        failures.append("the admitted portfolio is %s, the stage expects %s" % (got, portfolio_id(host) if host else None))
    return failures


def _store_rows(snapshot):
    return sum((snapshot or {}).get("rows", {}).values())


def stage1_failures(raw, config):
    """The save-through-socket scenario's failures, by assertion name. Each check reads only what its own fault touches."""
    created = read_json(raw / "save-create.json", None)
    edited = read_json(raw / "save-edit.json", None)
    stale = read_json(raw / "save-stale.json", None)
    snaps = {name: read_json(raw / ("store-%s.json" % name), None) for name in
             ("before-saves", "after-create", "after-edit", "after-stale")}
    limit = (config.get("store") or {}).get("rows_per_save_max")
    found = {name: [] for name in STAGE1}
    found["portfolio-admitted-before-saves"] = admission_failures(raw, config.get("host"))
    if (snaps.get("before-saves") or {}).get("admission_outcome") not in (None, "admitted", "replayed"):
        found["portfolio-admitted-before-saves"].append("Store snapshot says host admission outcome is unavailable")

    project = read_json(HERE / "canary" / "project.json", {}) or {}
    saves = (project.get("stages", {}).get("1", {}).get("saves") or {})
    create_tasks = {task.get("id"): task for task in (saves.get("create", {}).get("tasks") or [])}
    edit_tasks = {task.get("id"): task for task in (saves.get("edit", {}).get("tasks") or [])}
    failures = []
    if set(create_tasks) != {"A", "B", "C"}:
        failures.append("create fixture task ids are %s, expected A, B and C" % sorted(create_tasks))
    if create_tasks.get("B", {}).get("dependencies") != ["A"]:
        failures.append("create fixture does not declare B -> A")
    if edit_tasks.get("C", {}).get("dependencies") != ["B"]:
        failures.append("edit fixture does not declare C -> B")
    if create_tasks.get("A", {}).get("title") == edit_tasks.get("A", {}).get("title"):
        failures.append("edit fixture did not change A's title")
    if (create_tasks.get("B", {}).get("metadata_namespace", {}).get("otto.plan") or {}).get("size") == (edit_tasks.get("B", {}).get("metadata_namespace", {}).get("otto.plan") or {}).get("size"):
        failures.append("edit fixture did not change B's plan size")
    for alias, task in create_tasks.items():
        plan = (task.get("metadata_namespace") or {}).get("otto.plan") or {}
        if not all(k in plan for k in ("route", "size", "lines")):
            failures.append("create fixture task %s lacks otto.plan route, size or lines" % alias)
        if not task.get("acceptance"):
            failures.append("create fixture task %s lacks criteria" % alias)
    create_records = (snaps.get("after-create") or {}).get("records") or {}
    create_ids = {str(ref.get("id")) for ref in ((created or {}).get("task_refs") or {}).values() if isinstance(ref, dict)}
    persisted = [row for key, row in create_records.items() if key.split(":", 1)[-1].split("@", 1)[0] in create_ids and row]
    if len(persisted) != 3:
        failures.append("create Store snapshot has %d task records, expected 3" % len(persisted))
    persisted_by_alias = {(row.get("payload") or {}).get("alias"): row.get("payload") or {} for row in persisted}
    if set(persisted_by_alias) != {"A", "B", "C"}:
        failures.append("create Store records have aliases %s, expected A, B and C" % sorted(persisted_by_alias))
    create_ref_by_alias = {alias: ref for alias, ref in ((created or {}).get("task_refs") or {}).items()
                           if isinstance(ref, dict)}
    for row in persisted:
        payload = row.get("payload") or {}
        alias = payload.get("alias")
        metadata = (payload.get("metadata_namespaces") or {}).get("otto.plan") or {}
        if not all(key in metadata for key in ("route", "size", "lines")):
            failures.append("persisted task record lacks plan route, size or lines")
        if alias in create_tasks:
            expected = (create_tasks[alias].get("metadata_namespace") or {}).get("otto.plan") or {}
            if metadata != expected:
                failures.append("persisted task %s plan metadata differs from the create fixture" % alias)
            if payload.get("acceptance") != create_tasks[alias].get("acceptance"):
                failures.append("persisted task %s criteria differ from the create fixture" % alias)
    a_id = (create_ref_by_alias.get("A") or {}).get("id")
    b_dependencies = persisted_by_alias.get("B", {}).get("dependencies") or []
    if not any(isinstance(dep, dict) and dep.get("id") == a_id for dep in b_dependencies):
        failures.append("create Store does not persist B -> A")
    found["canary-has-three-planned-tasks"] = failures

    readback = read_json(raw / "read-back.json", None)
    rb_failures = []
    if ((snaps.get("after-edit") or {}).get("readback_available") is False
            or not isinstance(readback, dict) or readback.get("outcome") != "read"):
        rb_failures.append("owner-lane show read-back is unavailable or did not return read")
    else:
        tasks = readback.get("tasks") or []
        aliases = {str((row.get("authored") or {}).get("alias") or row.get("alias") or "") for row in tasks}
        if len(tasks) != 3 or not {"A", "B", "C"}.issubset(aliases):
            rb_failures.append("owner-lane show returned %d tasks with aliases %s" % (len(tasks), sorted(aliases)))
        if readback.get("dispatch") is not False or readback.get("launch") is not False:
            rb_failures.append("owner-lane show claims dispatch or launch")
    found["show-readback-available"] = rb_failures

    snapshot = snaps.get("after-edit") or {}
    records = snapshot.get("records") or {}
    typed_failures = []
    task_ids = {str(ref.get("id")) for ref in ((edited or {}).get("task_refs") or {}).values() if isinstance(ref, dict)}
    typed_rows = []
    for ref in ((edited or {}).get("task_refs") or {}).values():
        if not isinstance(ref, dict):
            continue
        prefix = "%s:%s@" % (ref.get("kind"), ref.get("id"))
        exact = prefix + str(ref.get("revision")) if ref.get("revision") else None
        record = records.get(exact) if exact else None
        if record is None and not ref.get("revision"):
            record = next((value for key, value in reversed(list(records.items())) if key.startswith(prefix)), None)
        if record:
            typed_rows.append(record)
    if len(typed_rows) != 3:
        typed_failures.append("Store snapshot has %d typed assignment records, expected 3" % len(typed_rows))
    if not all(all(str((entry.get("ref") or {}).get(field) or "").strip() for field in ("authority", "kind", "id"))
               for entry in typed_rows):
        typed_failures.append("Store snapshot contains an untyped task record")
    found["store-has-typed-tasks"] = typed_failures

    edit_failures = []
    edited_refs = (edited or {}).get("task_refs") or {}
    edited_by_alias = {alias: ref for alias, ref in edited_refs.items() if isinstance(ref, dict)}
    edited_records = {key.split(":", 1)[-1].split("@", 1)[0]: value for key, value in records.items()
                      if value and key.split(":", 1)[-1].split("@", 1)[0] in
                      {str(ref.get("id")) for ref in edited_by_alias.values()}}
    if len(edited_records) != 3:
        edit_failures.append("the Store snapshot has %d edited task records, expected 3" % len(edited_records))
    else:
        by_id = {ref.get("id"): alias for alias, ref in edited_by_alias.items()}
        by_alias = {}
        for record in edited_records.values():
            payload = record.get("payload") or {}
            by_alias[payload.get("alias")] = payload
        if (by_alias.get("A", {}).get("title") or by_alias.get("A", {}).get("name")) != edit_tasks.get("A", {}).get("title"):
            edit_failures.append("the Store does not contain A's edited title")
        bplan = (by_alias.get("B", {}).get("metadata_namespaces") or {}).get("otto.plan") or {}
        if bplan.get("size") != (edit_tasks.get("B", {}).get("metadata_namespace", {}).get("otto.plan") or {}).get("size"):
            edit_failures.append("the Store does not contain B's edited plan size")
        b_id = (edited_by_alias.get("B") or {}).get("id")
        a_id = (edited_by_alias.get("A") or {}).get("id")
        b_dependencies = (by_alias.get("B") or {}).get("dependencies") or []
        if not any(isinstance(dep, dict) and dep.get("id") == a_id for dep in b_dependencies):
            edit_failures.append("the Store no longer contains A -> B")
        c_dependencies = (by_alias.get("C") or {}).get("dependencies") or []
        if not any(isinstance(dep, dict) and dep.get("id") == b_id for dep in c_dependencies):
            edit_failures.append("the Store does not contain C -> B")
    found["edit-is-persisted"] = edit_failures

    for name, save in (("save-create", created), ("save-edit", edited), ("save-stale", stale)):
        if save is None:
            found["nothing-runs"].append("%s was not recorded" % name)
        elif save.get("dispatch") is not False or save.get("launch") is not False:
            found["nothing-runs"].append("%s says dispatch %s, launch %s; a save runs nothing"
                                         % (name, save.get("dispatch"), save.get("launch")))
    ran = sorted({"%s %s" % (e["task"], e["kind"]) for e in observed(raw) if e["kind"] in RUN_EVENTS})
    if ran:
        found["nothing-runs"].append("run events during the saves: " + ", ".join(ran))
    if pool_peak(raw):
        found["nothing-runs"].append("the pool peaked at %d workers during the saves" % pool_peak(raw))
    store_events = (snaps.get("after-edit") or {}).get("event_types") or []
    if any("dispatch" in str(event).lower() or "launch" in str(event).lower() for event in store_events):
        found["nothing-runs"].append("Store snapshot contains execution event types: " + ", ".join(map(str, store_events)))

    if created is None or edited is None:
        found["edit-makes-revision"].append("the create or the edit save was not recorded")
    else:
        if edited.get("outcome") != "saved":
            found["edit-makes-revision"].append("the edit save outcome is %s, not saved" % edited.get("outcome"))
        base = (created.get("project_ref") or {}).get("revision")
        new = (edited.get("project_ref") or {}).get("revision")
        # Revisions are opaque (rev-2, rev-3): the edit moved the project if it is at a different one than the create.
        if not new or new == base:
            found["edit-makes-revision"].append("the edit is at revision %s, the create's revision %s" % (new, base))
        snap_revision = (snaps.get("after-edit") or {}).get("project_revision", new)
        if snap_revision != new:
            found["edit-makes-revision"].append("Store project revision is %s, save reply says %s" % (snap_revision, new))

    history_failures = []
    old_revision = (created or {}).get("project_ref") or {}
    old_key = "%s:%s@%s" % (old_revision.get("kind"), old_revision.get("id"), old_revision.get("revision"))
    old_record = (snaps.get("after-edit") or {}).get("records", {}).get(old_key)
    if not old_record or not old_record.get("payload"):
        history_failures.append("Store snapshot cannot read the create project revision %s" % old_key)
    else:
        old_title = old_record["payload"].get("title") or old_record["payload"].get("name")
        if old_title != "Canary plan":
            history_failures.append("create revision project title is %s, not Canary plan" % old_title)
    found["project-history-keeps-old-revision"] = history_failures

    if stale is None:
        found["stale-save-refused"].append("the stale save was not recorded")
    else:
        if (snaps.get("after-stale") or {}).get("stale_refused") is False:
            found["stale-save-refused"].append("Store snapshot says the stale save was not refused")
        if stale.get("outcome") != "conflict":
            found["stale-save-refused"].append("the stale save outcome is %s, not conflict" % stale.get("outcome"))
        code = (stale.get("error") or {}).get("code")
        if code != "stale_base":
            found["stale-save-refused"].append("the stale save error.code is %s, not stale_base" % code)
        if not isinstance(stale.get("diff"), dict):
            found["stale-save-refused"].append("the stale save names no diff")

    if any(snap is None or snap.get("error") for snap in snaps.values()):
        broken = [name for name, snap in snaps.items() if snap is None or snap.get("error")]
        found["store-growth-per-save"].append("the Store was not read after: " + ", ".join(broken))
    else:
        before, after_create, after_edit, after_stale = (_store_rows(snaps[n]) for n in
                                                         ("before-saves", "after-create", "after-edit", "after-stale"))
        growth = {"create": after_create - before, "edit": after_edit - after_create, "stale": after_stale - after_edit}
        if growth["create"] <= 0:
            found["store-growth-per-save"].append("the create save added %d rows" % growth["create"])
        if growth["edit"] <= 0:
            found["store-growth-per-save"].append("the edit save added %d rows" % growth["edit"])
        if growth["stale"] != 0:
            found["store-growth-per-save"].append("the stale save added %d rows; a refused save adds none" % growth["stale"])
        for name, rows in growth.items():
            if limit is not None and rows > limit:
                found["store-growth-per-save"].append("the %s save added %d rows, the stage allows %d" % (name, rows, limit))
    return found


def stage2_event_evidence(raw, config):
    """Match direct Store events to the stage's admitted task identities."""
    data = read_json(raw / "stage2-store-events.json", {}) or {}
    tasks = config.get("stage2_tasks") or []
    refs = (((read_json(raw / "stage2-activation.json", {}) or {}).get("activation") or {})
            .get("steps") or {}).get("tasks") or {}
    refs = refs.get("task_refs") or {}
    failures = []
    selected = {}
    if data.get("error") or not isinstance(data.get("events"), list):
        failures.append("direct Store event read failed: " + str(data.get("error") or "missing events"))
    for alias in tasks:
        task_id = (refs.get(alias) or {}).get("id")
        if not task_id or (data.get("tasks") or {}).get(task_id) != alias:
            failures.append(alias + " has no exact work.task identity in the Store receipt")
            continue
        rows = [row for row in data.get("events") or [] if isinstance(row, dict)
                and row.get("task_id") == task_id and row.get("alias") == alias]
        dispatches = [row for row in rows if row.get("event_type") == "work.assignment.dispatched"
                      and row.get("assignment_id") and
                      row.get("stream") == "dispatch:" + row["assignment_id"] and
                      (data.get("assignments") or {}).get(row["assignment_id"]) == task_id]
        if len(dispatches) != 1:
            failures.append(alias + " missing one work.assignment.dispatched event")
        else:
            selected[(alias, "dispatch")] = dispatches[0]
        landed = [row for row in rows if row.get("event_type") == "work.result.appended"
                  and row.get("assignment_id") and
                  row.get("stream") == "result:" + row["assignment_id"] and
                  (row.get("value") or {}).get("lab_commit") and
                  ((row.get("value") or {}).get("task_ref") or {}).get("id") == task_id and
                  (row.get("value") or {}).get("assignment_id") == row["assignment_id"]]
        if len(landed) == 1:
            selected[(alias, "landing")] = landed[0]
        elif len(landed) > 1:
            failures.append(alias + " has more than one landing observation in its assignment stream")
        completed = [row for row in rows if row.get("event_type") == "work.revised"
                     and row.get("stream") == "work:" + task_id and
                     (row.get("subject") or {}).get("id") == task_id and
                     (row.get("effects") or {}).get("completion")]
        if len(completed) == 1:
            selected[(alias, "completion")] = completed[0]
        elif len(completed) > 1:
            failures.append(alias + " has more than one manager completion event in the Store")
    return data, selected, failures


def stage2_event_time(row):
    try:
        return datetime.datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def stage2_timeline_failures(raw, config):
    data, events, failures = stage2_event_evidence(raw, config)
    final_status = read_json(raw / "stage2-dispatch-status.json", None)
    status_tasks = final_status.get("tasks") if isinstance(final_status, dict) else None
    if not isinstance(status_tasks, list):
        completed = [alias for alias in config.get("stage2_expected_completed") or []
                     if events.get((alias, "completion")) is not None]
        failures.append("final product status snapshot missing; Store completion events retained for: "
                        + (", ".join(completed) or "none"))
        by_alias = None
    else:
        by_alias = {row.get("id"): row for row in status_tasks if isinstance(row, dict)}
    previous_completion_time = None
    for alias in config.get("stage2_expected_completed") or []:
        dispatch, landing, completion = (events.get((alias, kind)) for kind in
                                         ("dispatch", "landing", "completion"))
        if landing is None:
            failures.append(alias + " missing landing observation in its assignment stream")
        if completion is None:
            failures.append(alias + " missing manager completion event in the Store")
        else:
            body = (completion.get("effects") or {}).get("completion") or {}
            gates = body.get("gate_refs") or []
            evidence = body.get("evidence_refs") or []
            checked = body.get("assessment_gate_check") or {}
            actor = (completion.get("actor") or {}).get("actor")
            if (body.get("logical_request_key") != "journey:perch-stage2-review-" + alias + ":finish"
                    or actor != body.get("manager")
                    or not any(turn.get("native_turn_started") is True
                               and turn.get("recipient") == actor
                               and turn.get("generation") == body.get("generation")
                               and stage2_event_time(turn) is not None
                               and stage2_event_time(completion) is not None
                               and (previous_completion_time is None
                                    or previous_completion_time < stage2_event_time(turn))
                               and stage2_event_time(turn) < stage2_event_time(completion)
                               for turn in data.get("manager_turns") or [])):
                failures.append(alias + " completion lacks an owner-started manager turn and journey finish key")
            decisions = data.get("decisions") or {}
            cited = [decisions.get(gate.get("id")) for gate in gates if isinstance(gate, dict)]
            if (not gates or len(cited) != len(gates) or not evidence
                    or body.get("candidate_ref") not in evidence
                    or checked.get("evidence_verification") != "verified"
                    or checked.get("blockers") != []
                    or {json.dumps(ref, sort_keys=True) for ref in checked.get("accepted_decision_refs") or []}
                       != {json.dumps(ref, sort_keys=True) for ref in gates}
                    or any(not isinstance(decision, dict) or decision.get("ref") != gate
                           or (decision.get("payload") or {}).get("disposition") != "accept"
                           or (decision.get("payload") or {}).get("candidate_ref") != body.get("candidate_ref")
                           for decision, gate in zip(cited, gates))
                    or {json.dumps(ref, sort_keys=True) for decision in cited if isinstance(decision, dict)
                        for ref in (decision.get("payload") or {}).get("evidence_refs") or []}
                       != {json.dumps(ref, sort_keys=True) for ref in evidence}):
                failures.append(alias + " completion does not cite its accepted decision evidence")
        if dispatch and landing and completion:
            times = [stage2_event_time(row) for row in (dispatch, landing, completion)]
            if None in times or not times[0] < times[1] < times[2]:
                failures.append(alias + " dispatch, landing observation and completion are not in event order")
            if landing.get("assignment_id") != dispatch.get("assignment_id"):
                failures.append(alias + " landing observation belongs to another assignment")
        previous_completion_time = stage2_event_time(completion) if completion else None
        if by_alias is not None:
            status = by_alias.get(alias) or {}
            if status.get("lifecycle") != "completed" or (status.get("dispatch") or {}).get("state") != "landed":
                failures.append(alias + " has no landed and completed product status")
    owner_status = read_json(raw / "stage2-owner-status.json", None)
    holds = (owner_status.get("native_capacity") or {}).get("holds") if isinstance(owner_status, dict) else None
    if not isinstance(holds, list) or any(not isinstance(hold, dict)
            or not isinstance(hold.get("next_action"), str) or not hold["next_action"].strip()
            for hold in holds):
        failures.append("final owner capacity holds are missing or have no next action")
    return failures


def stage2_lsof_count(raw, label, expected_pid):
    lines = read_lines(raw / ("stage2-fds-" + label + ".txt"))
    if not lines or not lines[0].startswith("COMMAND "):
        return None
    if any(len(line.split()) < 2 or line.split()[1] != str(expected_pid) for line in lines[1:]):
        return None
    return len(lines) - 1


def stage2_failures(raw, config):
    """The admit-and-dispatch scenario is accepted only from recorded staging observations."""
    observations = read_json(raw / "stage2-observations.json", {}) or {}
    found = {name: [] for name in STAGE2}
    if read_json(raw / "notes.json", {}).get("admit-and-dispatch") != "ran":
        found["admit-and-dispatch-ran"].append("scenario did not run against staging COMPOSEFLEET")
    activation_record = read_json(raw / "stage2-activation.json", {}) or {}
    dispatch_record = read_json(raw / "stage2-dispatch-status.json", {}) or {}
    store_record = read_json(raw / "stage2-store-events.json", {}) or {}
    if (not (((activation_record.get("activation") or {}).get("steps") or {}).get("tasks") or {}).get("task_refs")
            or not dispatch_record.get("tasks") or not store_record.get("events")):
        found["admit-and-dispatch-ran"].append(
            "activation, final owner status or direct Store events are missing from the scenario")

    tasks = config.get("stage2_tasks", [])
    dependencies = config.get("stage2_dependencies", {})
    if len(tasks) != 3 or config.get("stage2_admitted") != tasks:
        found["stage2-canary-valid"].append("canary must admit exactly three tasks")
    if dependencies.get("A") != [] or dependencies.get("B") != [] or dependencies.get("C") != ["B"]:
        found["stage2-canary-valid"].append("A and B must be independently ready and C depend on B")
    if config.get("stage2_expected_completed") != ["A", "B"] or config.get("stage2_kill_task") != "C":
        found["stage2-canary-valid"].append("stage outcome declarations do not name the completed and killed tasks")

    save = read_json(raw / "stage2-plan-save.json", {}) or {}
    plan = read_json(raw / "stage2-plan-save.input.json", {}) or {}
    activation = read_json(raw / "stage2-activation.json", {}) or {}
    task_refs = (((activation.get("activation") or {}).get("steps") or {}).get("tasks") or {}).get("task_refs") or {}
    if save.get("outcome") != "saved" or set((save.get("task_refs") or {})) != set(tasks):
        found["stage2-canary-valid"].append("registered canary tasks were not saved through the owner portfolio")
    for task in plan.get("tasks") or []:
        alias = task.get("id")
        if (alias not in tasks or (task.get("fields") or {}).get("check") != {"argv": ["/usr/bin/true"]}
                or task.get("dependencies") != dependencies.get(alias)
                or (task.get("metadata_namespace") or {}).get("otto.plan") !=
                   {"repo": "toy", "branch": "canon/main", "route": "normal"}):
            found["stage2-canary-valid"].append("canary task lacks its typed check or dispatch plan: " + str(alias))
    if len(plan.get("tasks") or []) != len(tasks):
        found["stage2-canary-valid"].append("plan save does not name exactly three tasks")
    if any((save.get("task_refs") or {}).get(alias) != task_refs.get(alias) for alias in tasks):
        found["stage2-canary-valid"].append("activation did not retain the saved canary task revisions")
    status = read_json(raw / "stage2-project-status.json", {}) or {}
    status_tasks = status.get("tasks") or []
    if (status.get("outcome") != "read" or len(status_tasks) != len(tasks)
            or {row.get("id") for row in status_tasks if isinstance(row, dict)} != set(tasks)):
        found["stage2-canary-valid"].append("product project status did not read exactly three canary tasks")
    scopes = ((activation.get("activation") or {}).get("steps") or {}).get("assessment_scopes") or []
    if len(scopes) != len(tasks):
        found["stage2-canary-valid"].append("product activation did not declare three required task scopes")
    for alias in tasks:
        expected = task_refs.get(alias) or {}
        declared = [row for row in scopes if isinstance(row, dict) and row.get("task_ref") == expected]
        shown = [row for row in status_tasks if isinstance(row, dict) and row.get("id") == alias]
        scope = declared[0] if len(declared) == 1 else {}
        required = shown[0].get("required_assessment_scopes") if len(shown) == 1 else None
        if len(shown) == 1 and shown[0].get("depends_on") != len(dependencies.get(alias, [])):
            found["stage2-canary-valid"].append(alias + " has a different product dependency count")
        shown_scope = required[0] if isinstance(required, list) and len(required) == 1 \
            and isinstance(required[0], dict) else {}
        criterion_refs = scope.get("criterion_refs")
        criterion = criterion_refs[0] if isinstance(criterion_refs, list) and len(criterion_refs) == 1 \
            and isinstance(criterion_refs[0], dict) else {}
        if (len(declared) != 1 or not shown_scope
                or (scope.get("scope_ref") or {}).get("kind") != "assessment.scope"
                or not (scope.get("scope_ref") or {}).get("revision")
                or criterion.get("kind") != "assessment.criterion" or not criterion.get("revision")
                or shown_scope.get("ref") != scope.get("scope_ref")
                or shown_scope.get("criteria") != criterion_refs
                or shown_scope.get("criterion_definitions") != [{"id": criterion.get("id"),
                    "source_alias": "C-" + alias, "definition": "accepted check passes"}]):
            found["stage2-canary-valid"].append(alias + " lacks its product-declared required check criterion")
        admission = read_json(raw / ("stage2-admit-" + alias + ".json"), {}) or {}
        admitted_ref = admission.get("task_ref") or {}
        if (admission.get("outcome") not in {"admitted", "already-admitted"}
                or admission.get("admitted_revision") != expected.get("revision")
                or any(admitted_ref.get(key) != expected.get(key)
                       for key in ("authority", "kind", "id"))
                or not admitted_ref.get("revision")
                or admitted_ref.get("revision") == expected.get("revision")):
            found["stage2-canary-valid"].append(alias + " lacks its exact operator-admitted task revision")

    used_review = read_json(raw / "stage2-review-ref.json", {}) or {}
    try:
        expected_review = stage2_review_ref(status, activation, STAGE2_REVIEW_TEXT)
    except (ValueError, TypeError, AttributeError) as exc:
        expected_review = None
        found["stage2-review-document"].append(str(exc))
    if expected_review is not None and used_review != expected_review:
        found["stage2-review-document"].append("admission did not use the stored plan-review.md revision")
    try:
        admission_lines = [json.loads(line) for line in read_lines(raw / "stage2-operator-admission.jsonl")]
    except ValueError:
        admission_lines = []
        found["operator-presence-approved"].append("operator admission log is malformed")
    for task in tasks:
        task_ref = task_refs.get(task) or {}
        matches = [line for line in admission_lines if isinstance(line, dict) and line.get("task") == task_ref.get("id")]
        expected_count = 2 if task == "C" else 1
        if len(matches) != expected_count or any(line.get("prover_result") != "approved" for line in matches):
            found["operator-presence-approved"].append("%s admission log lacks %d approved prover_result records" % (task, expected_count))
        if expected_review is not None and (len(matches) != expected_count or
                                            any(line.get("review") != expected_review["id"] for line in matches)):
            found["stage2-review-document"].append("%s admission log does not name the stored plan review" % task)

    store_events, task_events, event_errors = stage2_event_evidence(raw, config)
    stored_rows = [row for row in store_events.get("events") or [] if isinstance(row, dict)]
    found["admitted-ready-dependency-order"].extend(event_errors)
    for name, prereqs in dependencies.items():
        for prereq in prereqs:
            dispatch = task_events.get((name, "dispatch"))
            completion = task_events.get((prereq, "completion"))
            if dispatch is None or completion is None:
                found["admitted-ready-dependency-order"].append(
                    "%s/%s lacks a Store dispatch or prerequisite completion event" % (name, prereq))
            elif (stage2_event_time(dispatch) is None or stage2_event_time(completion) is None or
                  stage2_event_time(dispatch) <= stage2_event_time(completion)):
                found["admitted-ready-dependency-order"].append(
                    "%s dispatched before prerequisite %s completed in the Store" % (name, prereq))

    edited = read_json(raw / "stage2-instruction-edit-C.json", {}) or {}
    edit_input = read_json(raw / "stage2-instruction-edit-C.input.json", {}) or {}
    no_launch = read_json(raw / "stage2-edited-C-no-launch.json", {}) or {}
    no_launch_owner = read_json(raw / "stage2-edited-C-owner.json", {}) or {}
    edited_ref = (edited.get("task_refs") or {}).get("C") or {}
    edited_project_id = (edited.get("project_ref") or {}).get("id")
    original_ref = task_refs.get("C") or {}
    edited_task = next((row for row in edit_input.get("tasks") or [] if row.get("id") == "C"), {})
    c_before = next((row for row in no_launch.get("tasks") or [] if row.get("id") == "C"), {})
    prereq_before = next((row for row in no_launch.get("tasks") or [] if row.get("id") == "B"), {})
    c_events = [row for row in stored_rows
                if row.get("task_id") == original_ref.get("id") and row.get("event_type") == "work.revised"
                and row.get("stream") == "work:" + str(original_ref.get("id"))]
    initial_admission = [row for row in c_events if ((((row.get("effects") or {}).get("result_payload") or {})
                         .get("metadata_namespaces") or {}).get("work.admission") or {}).get("revision") ==
                         original_ref.get("revision")]
    readmission = [row for row in c_events if ((((row.get("effects") or {}).get("result_payload") or {})
                   .get("metadata_namespaces") or {}).get("work.admission") or {}).get("revision") ==
                   edited_ref.get("revision")]
    edited_history = next((row for row in (store_events.get("revisions") or {}).get(edited_ref.get("id"), [])
                           if isinstance(row, dict) and row.get("revision") == edited_ref.get("revision")), {})
    instruction_edit = [row for row in stored_rows
                        if row.get("event_type") == "work.project-sheet.applied"
                        and edited_project_id and row.get("stream") == "work:" + edited_project_id
                        and (row.get("subject") or {}).get("id") == edited_project_id
                        and (row.get("subject") or {}).get("kind") == "work.project"
                        and any(ref.get("kind") == "work.task" and ref.get("id") == edited_ref.get("id")
                                and ref.get("revision") == edited_ref.get("revision")
                                for ref in (row.get("effects") or {}).get("child_refs") or []
                                if isinstance(ref, dict))
                        and any((facet.get("subject") or {}).get("id") == edited_ref.get("id")
                                and (facet.get("subject") or {}).get("revision") == edited_ref.get("revision")
                                and "instructions" in (facet.get("changed_fields") or [])
                                for facet in (((row.get("effects") or {}).get("history_summary") or {})
                                              .get("facets") or []) if isinstance(facet, dict))]
    idle_at = stage2_event_time({"recorded_at": no_launch_owner.get("projection_at")})
    b_completion = task_events.get(("B", "completion"))
    c_dispatch = task_events.get(("C", "dispatch"))
    if (edited.get("outcome") != "saved" or edited_ref.get("id") != original_ref.get("id")
            or edited_ref.get("revision") in (None, original_ref.get("revision"))
            or edited_task.get("instructions") != "Canary dispatch C (post-admission edit)"
            or prereq_before.get("lifecycle") != "completed"
            or (c_before.get("dispatch") or {}).get("state") != "admitted"
            or (c_before.get("dispatch") or {}).get("reason") != "readmission needed"
            or "instructions" not in (c_before.get("dispatch") or {}).get("changed_fields", [])
            or c_before.get("lifecycle") == "completed"
            or (no_launch_owner.get("native_capacity") or {}).get("active_or_uncertain") != 0
            or (no_launch_owner.get("manager_turns") or {}).get("active") != 0
            or len(initial_admission) != 1 or len(instruction_edit) != 1 or len(readmission) != 1
            or not edited_history or edited_history.get("admitted_revision") is not None or idle_at is None
            or b_completion is None or not stage2_event_time(b_completion)
            or not stage2_event_time(initial_admission[0]) or not stage2_event_time(instruction_edit[0])
            or not stage2_event_time(initial_admission[0]) < stage2_event_time(instruction_edit[0]) < idle_at
            or not stage2_event_time(b_completion) < idle_at
            or c_dispatch is None or not stage2_event_time(c_dispatch)
            or not stage2_event_time(readmission[0])
            or not idle_at < stage2_event_time(readmission[0]) < stage2_event_time(c_dispatch)):
        found["unadmitted-revision-refused"].append("C's edited instructions did not remain unlaunched after B completed")
    write = read_json(raw / "stage2-metadata-only-C.json", {}) or {}
    write_ref = write.get("task_ref") or {}
    revisions = (store_events.get("revisions") or {}).get(edited_ref.get("id"), [])
    by_revision = {row.get("revision"): row for row in revisions if isinstance(row, dict)}
    before_write, after_write = by_revision.get(edited_ref.get("revision"), {}), by_revision.get(write_ref.get("revision"), {})
    metadata_events = [row for row in stored_rows if row.get("task_id") == edited_ref.get("id")
                       and row.get("event_type") == "work.revised"
                       and ((((row.get("effects") or {}).get("result_payload") or {})
                            .get("metadata_namespaces") or {}).get("work.admission") or {})
                           .get("revision") == edited_ref.get("revision")]
    dispatch_c = task_events.get(("C", "dispatch"))
    negative_at = idle_at
    c_after = next((row for row in (read_json(raw / "stage2-dispatch-C-project.json", {}) or {}).get("tasks") or []
                    if row.get("id") == "C"), {})
    if (write.get("outcome") not in {"admitted", "already-admitted"}
            or write.get("admitted_revision") != edited_ref.get("revision")
            or write_ref.get("id") != edited_ref.get("id")
            or write_ref.get("revision") in (None, edited_ref.get("revision"))
            or not before_write or not after_write
            or before_write.get("reviewed_digest") != after_write.get("reviewed_digest")
            or before_write.get("instructions") != after_write.get("instructions")
            or after_write.get("admitted_revision") != edited_ref.get("revision")
            or (c_after.get("dispatch") or {}).get("state") != "launched"
            or len(metadata_events) != 1 or dispatch_c is None or negative_at is None
            or not stage2_event_time(metadata_events[0]) or not stage2_event_time(dispatch_c)
            or not negative_at < stage2_event_time(metadata_events[0]) < stage2_event_time(dispatch_c)):
        found["metadata-only-write-runnable"].append("C's metadata-only admission write did not preserve content and launch")

    installed = read_json(raw / "stage2-installation.json", {}) or {}
    owner = read_json(raw / "stage2-contention-owner.json", {}) or {}
    project = read_json(raw / "stage2-contention-project.json", {}) or {}
    pool = owner.get("native_capacity") or {}
    managers = owner.get("manager_turns") or {}
    ready = {row.get("id"): (row.get("dispatch") or {}).get("state") for row in project.get("tasks") or []}
    if ((installed.get("capacity") or {}).get("turn_units") != config.get("pool_limit") or
            (installed.get("capacity") or {}).get("manager_reserve") != config.get("manager_reserve") or
            pool.get("worker_limit") != config.get("pool_limit") or
            pool.get("active_or_uncertain") != 2 or managers.get("active") != 1 or
            owner.get("manager_turn_active") is not True or
            sorted(ready.get(alias) for alias in ("A", "B") if ready.get(alias)) != ["admitted", "launched"] or
            (read_json(raw / "stage2-manager-start.json", {}) or {}).get("outcome") in {None, "error", "refused"}):
        found["pool-and-manager-reserve-held"].append("configured worker limit, waiting second task or active manager reserve is absent")
    first_two = [(task_events.get((alias, "dispatch")), alias) for alias in ("A", "B")
                       if task_events.get((alias, "dispatch")) is not None]
    contention_at = stage2_event_time({"recorded_at": owner.get("projection_at")})
    if len(first_two) != 2:
        found["pool-and-manager-reserve-held"].append("two independent workers have no Store dispatch events")
    else:
        ordered = sorted(first_two, key=lambda pair: stage2_event_time(pair[0]) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
        first_done = task_events.get((ordered[0][1], "completion"))
        if first_done is None or not stage2_event_time(first_done) or not stage2_event_time(ordered[1][0]) or \
                stage2_event_time(ordered[1][0]) <= stage2_event_time(first_done):
            found["pool-and-manager-reserve-held"].append("second ready worker dispatched before first worker completed")
        admission_times = []
        for alias in ("A", "B"):
            task_id = (task_refs.get(alias) or {}).get("id")
            pin = (task_refs.get(alias) or {}).get("revision")
            stamps = [row for row in stored_rows
                      if row.get("task_id") == task_id and row.get("event_type") == "work.revised"
                      and ((((row.get("effects") or {}).get("result_payload") or {})
                           .get("metadata_namespaces") or {}).get("work.admission") or {}).get("revision") == pin]
            if len(stamps) != 1 or stage2_event_time(stamps[0]) is None:
                found["pool-and-manager-reserve-held"].append(alias + " has no exact admission Store event")
            else:
                admission_times.append(stage2_event_time(stamps[0]))
        if (len(admission_times) == 2 and (contention_at is None or first_done is None
                or stage2_event_time(first_done) is None
                or not max(admission_times) < contention_at < stage2_event_time(first_done))):
            found["pool-and-manager-reserve-held"].append("both ready tasks were not admitted before the manager contention read")

    owner_pid = read_lines(raw / "stage2-owner-pid.txt")
    pid = int(owner_pid[0]) if len(owner_pid) == 1 and owner_pid[0].isdigit() else None
    before_fd, after_fd = (stage2_lsof_count(raw, label, pid) for label in ("before", "after"))
    if pid is None or before_fd is None or after_fd is None or after_fd > before_fd + 3:
        found["owner-descriptors-bounded"].append("owner lsof descriptor count is missing or grew beyond +3")

    killed = observations.get("worker_kill") or {}
    if killed.get("slot_released") is not True or killed.get("killed_worker_absent") is not True:
        found["worker-kill-recovery"].append("killed worker slot was not released")
    if killed.get("unrelated_processes_alive") is not True:
        found["worker-kill-recovery"].append("worker recovery killed or lost an unrelated process")
    recovered = store_events.get("worker_recovery") or {}
    marker = recovered.get("marker") or {}
    if (recovered.get("stop_state") != "stopped"
            or recovered.get("completion_state") != "failed"
            or recovered.get("in_flight_request") is not None
            or marker.get("schema") != "otto.worker-gone-failed-disposition.v1"
            or marker.get("request_key") != "perch-stage2-recover-C"
            or (marker.get("disposition_ref") or {}).get("kind") != "wrk.report"):
        found["worker-kill-recovery"].append("C has no retained manager recovery disposition")

    snapshots = observations.get("store_snapshots") or []
    if len(snapshots) < 2 or any(s.get("integrity") != "ok" for s in snapshots):
        found["stage2-store-snapshots"].append("expected at least two readable, integrity-ok Store snapshots")
    else:
        final = snapshots[-1]
        if final.get("event_errors") or final.get("dispatch_events", 0) < 3 or final.get("admitted_tasks") != tasks:
            found["stage2-store-snapshots"].append("final Store snapshot does not contain three admitted tasks and dispatch events")

    census = observations.get("census") or {}
    if census.get("killed_worker_pid") in census.get("after_pids", []):
        found["stage2-census"].append("killed worker remains in the after census")
    if not census.get("unrelated_started_pids") or not set(census.get("unrelated_started_pids", [])).issubset(
            set(census.get("after_pids", []))):
        found["stage2-census"].append("census does not show unrelated started processes survived")
    return found


def assertions(raw):
    config = read_json(raw / "config.json", {}) or {}
    notes = read_json(raw / "notes.json", {}) or {}
    results = []

    def add(name, failures, ok_detail, skip=None):
        if skip:
            results.append({"name": name, "status": "skip", "detail": skip})
        else:
            results.append({"name": name, "status": "fail" if failures else "pass",
                            "detail": "; ".join(failures) if failures else ok_detail})

    add("staging-ready", [] if config.get("staging_restart") == 0
        else ["staging restart exited %s" % config.get("staging_restart")], "staging restart ready")

    leaked = leaks(raw, config)
    add("no-leaked-process", ["still running after down: " + line for line in leaked], "no process left after down")

    events = observed(raw)
    failures = []
    for task in config.get("tasks", []):
        kinds = {e["kind"] for e in events if e["task"] == task["name"]}
        missing = [k for k in REQUIRED[task["expect"]] if k not in kinds]
        if missing:
            failures.append("%s missing %s" % (task["name"], ", ".join(missing)))
    if config.get("stage") == "2":
        failures.extend(stage2_timeline_failures(raw, config))
    add("timeline-events", failures, "every task has its events")

    if config.get("stage") == "4":
        # A note saying that the scenario ran is not evidence. Require owner-side
        # admission and automatic dispatch observations for the happy canary task,
        # followed by its worker/check/landing lifecycle. Direct fake worktree runs
        # do not satisfy this owner-driven acceptance assertion.
        happy = next((task for task in config.get("tasks", []) if task.get("expect") == "landed"), None)
        owner_kinds = {e["kind"] for e in events if happy and e["task"] == happy["name"]}
        owner_required = {"owner-admitted", "owner-task-admitted", "owner-dispatch-launched",
                          "lab-created", "turn", "done", "check-passed", "landed", "lab-deleted"}
        add("owner-driven-canary", [] if owner_required <= owner_kinds else
            ["owner journey missing " + ", ".join(sorted(owner_required - owner_kinds))],
            "the owner admitted and automatically dispatched the canary through check, done, landing and lab deletion",
            skip=("fake worktree harness does not exercise owner admission or automatic dispatch"
                  if config.get("fake") else None))
        conflict_task = next((task for task in config.get("tasks", []) if task.get("landing_conflict")), None)
        kinds = [e["kind"] for e in events if conflict_task and e["task"] == conflict_task["name"]]
        expected = {"lab-created", "turn", "done", "check-passed", "landing-conflict", "refused", "lab-deleted"}
        add("landing-conflict-refused", [] if set(kinds) == expected and "landed" not in kinds else
            ["conflict task events %s; expected %s and no landed event" % (kinds, sorted(expected))],
            "the passing worker hit a merge conflict and landing was refused")
        add("landing-conflict-lab-deleted", [] if "lab-deleted" in kinds else
            ["conflict lab was not deleted"], "the conflict lab was removed after refusal")

    left = read_lines(raw / "leftovers.txt")
    if config.get("stage") == "2":
        owner_failures, lab_detail, _ = stage2_owner_lab_evidence(raw)
        left.extend(owner_failures)
    else:
        lab_detail = "no lab, lab branch or lab folder left"
    add("labs-left-behind", ["left: " + line for line in left], lab_detail)

    # Until stage 2 there is no product pool to read: this is the harness's own count of its fake workers.
    if config.get("stage") != "2":
        limit = config.get("pool_limit")
        peak = pool_units_peak(raw)
        add("harness-pool-within-limit", [] if limit is None or peak <= limit else ["peak %d units, limit %d" % (peak, limit)],
            "peak %s of limit %s" % (peak, limit))

    # The Store must hold what the stage says it holds, both ways, with no gap in a task's timeline; a read that
    # failed is not a match. A staging that did not start has no Store to read: staging-ready says so.
    expect = config.get("store")
    recorded = read_json(raw / "timeline.json", None)
    store_at_rest = read_json(raw / "store-at-rest.json", None)
    failures = []
    if expect is None:
        failures.append("the stage states no expected Store contents")
    if recorded is None:
        failures.append("the Store timeline was not recorded")
    elif recorded.get("error"):
        failures.append("the Store was not read: " + recorded["error"])
    else:
        if expect is not None:
            if "store_events_min" in expect:
                if recorded.get("store_events", 0) < expect["store_events_min"]:
                    failures.append("%s events in the Store, the stage requires at least %s" %
                                    (recorded.get("store_events"), expect["store_events_min"]))
                work_tasks = recorded.get("work_tasks") or []
                aliases = [task.get("alias") for task in work_tasks]
                if sorted(aliases) != sorted(expect["store_work_tasks"]):
                    failures.append("stored work tasks %s, expected exactly %s" % (aliases, expect["store_work_tasks"]))
                if any(not task.get("admitted_revision") for task in work_tasks):
                    failures.append("the Store contains a work task without an admitted revision")
                if len(recorded.get("tasks", [])) < expect["store_assignment_tasks_min"]:
                    failures.append("%d assignment tasks in the Store, expected at least %s" %
                                    (len(recorded.get("tasks", [])), expect["store_assignment_tasks_min"]))
            else:
                if recorded.get("store_events") != expect["store_events"]:
                    failures.append("%s events in the Store, the stage expects %s" % (recorded.get("store_events"), expect["store_events"]))
                if len(recorded.get("tasks", [])) != expect["store_tasks"]:
                    failures.append("%d tasks in the Store, the stage expects %s" % (len(recorded.get("tasks", [])), expect["store_tasks"]))
        for task in recorded.get("tasks", []):
            if not task["complete"]:
                failures.append("store timeline %s has gaps %s" % (task["task_id"], task["gaps"]))
    if store_at_rest is None:
        failures.append("the Store at rest was not recorded")
    elif store_at_rest.get("error"):
        failures.append("the Store at rest: " + store_at_rest["error"])
    elif expect is not None and "store_bytes_max" in expect and store_at_rest["bytes"] > expect["store_bytes_max"]:
        failures.append("the Store is %d bytes at rest, the stage allows %d" % (store_at_rest["bytes"], expect["store_bytes_max"]))
    elif expect is not None and "store_growth_max" in expect:
        baseline = read_json(raw / "stage2-store-before.json", {}) or {}
        if not isinstance(baseline.get("bytes"), int):
            failures.append("the Store baseline after activation was not recorded")
        elif store_at_rest["bytes"] - baseline["bytes"] > expect["store_growth_max"]:
            failures.append("the Store grew %d bytes after activation, limit %d" %
                            (store_at_rest["bytes"] - baseline["bytes"], expect["store_growth_max"]))
    skip = "skipped: staging did not start" if config.get("staging_restart") != 0 else None
    add("store-matches-stage", failures, "the Store contains the stage's admitted work tasks and assignment history",
        skip=skip)

    # Stage 2 keeps the operator audit log across restart/down. Other stages
    # retain their existing run-folder contract.
    rest = read_json(raw / "at-rest.json", None)
    failures = []
    allowed_run = AT_REST_RUN + (("operator-admission.jsonl",) if config.get("stage") == "2" else ())
    if rest is None:
        failures.append("the staging root was not checked after down")
    else:
        if rest.get("error"):
            failures.append("the staging root could not be read: " + rest["error"])
        failures += ["home/run holds %s, which down does not leave" % name
                     for name in rest.get("home_run", []) if name not in allowed_run]
        if rest.get("service_state") not in (None, "closed"):
            failures.append("service.json says %s after down" % rest.get("service_state"))
        failures += ["socket left behind: %s" % path for path in rest.get("sockets", [])]
        failures += ["%s is still held by pid %s" % (name, " ".join(pids))
                     for name, pids in sorted(rest.get("store_holders", {}).items()) if pids]
        failures += ["perch-canary/ still holds %s" % entry for entry in rest.get("perch_canary", [])]
    detail = "after down: home/run holds only service.json (closed), generation and service-stop"
    if config.get("stage") == "2":
        detail += ", and operator-admission.jsonl"
    detail += "; no socket, no Store holder, no canary scratch"
    add("staging-at-rest-clean", failures, detail)

    # The lifecycle scenario: its observations exist only when it ran; otherwise each of its checks is skipped, and says why.
    lifecycle = notes.get("staging-lifecycle")
    skip = None if lifecycle == "ran" else (lifecycle or "skipped: this stage has no staging-lifecycle scenario")
    found = {} if skip else lifecycle_failures(raw, notes)
    for name in LIFECYCLE:
        add(name, found.get(name, []), LIFECYCLE_OK[name], skip=skip)

    # Stage 1's save scenario: listed only by a stage that saves, so a stage without it keeps its report as it was.
    if SAVE_SCENARIO in notes:
        save_note = notes.get(SAVE_SCENARIO)
        skip = None if save_note == "ran" else (save_note or "skipped: the stage did not run its save scenario")
        found = {} if skip else stage1_failures(raw, config)
        for name in STAGE1:
            add(name, found.get(name, []), STAGE1_OK[name], skip=skip)
    if "admit-and-dispatch" in (config.get("scenarios") or []):
        found = stage2_failures(raw, config)
        add("admit-and-dispatch-ran", found["admit-and-dispatch-ran"],
            "staging COMPOSEFLEET dispatch scenario ran")
        for name in STAGE2[1:]:
            add(name, found.get(name, []), "staging observation matches the stage-2 contract")
    return results


def read_samples(raw):
    return [json.loads(line) for line in read_lines(raw / "samples.jsonl")]


def pool_peak(raw):
    """The most workers running at once, from perch's own +1/-1 marks (exact, unlike the samples)."""
    level = peak = 0
    for line in sorted(read_lines(raw / "pool.tsv"), key=lambda l: float(l.split("\t")[0])):
        level += int(line.split("\t")[1])
        peak = max(peak, level)
    return peak


def pool_units_peak(raw):
    return max([pool_peak(raw)] + [s["pool_units"] for s in read_samples(raw)])


def cmd_check(args):
    raw = Path(args.raw)
    results = assertions(raw)
    (raw / "assertions.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    label = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}
    for r in results:
        print("%-4s %-32s %s" % (label[r["status"]], r["name"], r["detail"]))
    return 1 if any(r["status"] == "fail" for r in results) else 0


# ---- report.md ---------------------------------------------------------------------------------

def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return out


def duration_rows(raw):
    rows = []
    samples = read_samples(raw)
    for line in read_lines(raw / "durations.tsv"):
        phase, task, start, seconds = (line.split("\t") + [""] * 4)[:4]
        before = [s for s in samples if s["at"] <= start] or samples[:1]
        at = before[-1] if before else {}
        rows.append([phase, task or "-", start, seconds, at.get("disk_free_kb", "-"), (at.get("swap") or "-")])
    return rows


def render_store(timeline):
    if timeline.get("error"):
        return ["Store: %s." % timeline["error"]]
    lines = ["Store: %d events; %d assignment task(s) in it." % (timeline["store_events"], len(timeline["tasks"]))]
    if not timeline["tasks"]:
        lines.append("No task (assignment stream) is in the Store: the canary drives no product task, so the"
                     " Store's admitted and dispatched events are absent. The lab, landed and lab-deleted events"
                     " are not Store events in the code; they come from perch and git (see the canary timelines).")
    for task in timeline["tasks"]:
        lines.append("")
        lines.append("Store task `%s` (complete: %s):" % (task["task_id"], task["complete"]))
        lines += table(["recorded", "stream", "seq", "event"],
                       [[e["recorded_at"], e["stream"], e["sequence"], e["event_type"]] for e in task["events"]])
    return lines


def spend_and_history(path):
    text = path.read_text(encoding="utf-8") if path.exists() else "(no report.sh output)"
    return text.rstrip()


def staging_lines(raw):
    notes = read_json(raw / "notes.json", {}) or {}
    rows = []
    for when, name in (("up", "status-up.json"), ("after the KILL", "status-killed.json"),
                       ("after the restart", "status-restarted.json"), ("after down", "status-stopped.json")):
        status = read_json(raw / name, None) or {}
        rows.append([when, status.get("outcome", "not recorded"), status.get("generation", "-"),
                     status.get("holder_alive", "-")])
    refused = read_json(raw / "refused.json", None)
    refusal = ("exit %s, error.code %s" % (refused.get("exit_code"), (refused.get("error") or {}).get("code"))
               if refused else "none")
    return table(["observed", "outcome", "generation", "holder alive"], rows) + [
        "",
        "- scenario: %s" % notes.get("staging-lifecycle", "not declared by this stage"),
        "- admit-and-dispatch scenario: %s" % notes.get("admit-and-dispatch", "not declared by this stage"),
        "- the start after the KILL exited %s" % notes.get("restart_after_kill_rc", "not run"),
        "- the second start exited %s; its refusal record: %s" % (notes.get("refused_start_rc", "not run"), refusal),
    ]


def stage2_admission_attempt_lines(raw):
    rows = []
    for task in ("A", "B", "C"):
        paths = sorted(raw.glob("stage2-admit-%s-attempt-*.json" % task),
                       key=lambda path: int(path.stem.rsplit("-", 1)[-1]))
        for path in paths:
            number = path.stem.rsplit("-", 1)[-1]
            key_path = path.with_suffix(".request-key")
            request_key = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else "missing"
            retained = raw / ("stage2-admit-%s-retained-%s.json" % (task, number))
            for label, receipt in ((number, path), (number + " retained", retained)):
                if not receipt.exists():
                    continue
                try:
                    response = read_json(receipt, {}) or {}
                except ValueError:
                    response = {"outcome": "unreadable receipt"}
                if not isinstance(response, dict):
                    response = {"outcome": "unreadable receipt"}
                rows.append([task, label, request_key, response.get("outcome", "missing"),
                             response.get("reason", ""), "[raw receipt](raw/%s)" % receipt.name])
    lines = table(["task", "attempt", "request key", "outcome", "reason", "evidence"], rows) if rows else ["(no admission attempts recorded)"]
    for task in ("A", "B", "C"):
        path = raw / ("stage2-admit-%s-boundary-status.json" % task)
        if path.exists():
            lines.append("- %s boundary status: [raw owner status](raw/%s)" % (task, path.name))
    return lines


def at_rest_lines(raw):
    snap = read_json(raw / "store-at-rest.json", None) or {}
    rest = read_json(raw / "at-rest.json", None) or {}
    if snap.get("error"):
        return ["Store: %s." % snap["error"]]
    lines = ["- Store file %s bytes; %s pages of %s bytes, %s free; integrity %s." % (
        snap.get("bytes", "?"), snap.get("page_count", "?"), snap.get("page_size", "?"),
        snap.get("freelist_count", "?"), snap.get("integrity", "?"))]
    lines += table(["table", "rows"], sorted((snap.get("rows") or {}).items()))
    lines.append("- home/run after down: %s (service.json says %s)"
                 % (", ".join(rest.get("home_run", [])) or "nothing", rest.get("service_state", "no service.json")))
    return lines


def cmd_render(args):
    raw = Path(args.raw)
    config = read_json(raw / "config.json", {}) or {}
    samples = read_samples(raw)
    events = observed(raw)
    timeline = read_json(raw / "timeline.json", {}) or {}
    results = read_json(raw / "assertions.json", []) or []
    before = pids_of(read_lines(raw / "census.before.txt"))
    after = pids_of(read_lines(raw / "census.after.txt"))
    started = started_pids(raw)
    out = ["# PERCH report: stage %s%s" % (config.get("stage", "?"), " (fake worker)" if config.get("fake") else ""), ""]
    out.append("- started %s, finished %s" % (config.get("started_at", "?"), config.get("finished_at", "?")))
    out.append("- staging tree sha %s; canon/main %s" % (config.get("staging_sha", "?"), config.get("canon_main_sha", "?")))
    out.append("- check per task: `%s`; pool limit %s" % (config.get("check", "?"), config.get("pool_limit", "?")))
    out.append("- faults seeded: %s" % (", ".join(config.get("faults", [])) or "none"))
    out.append("- the Otto and its Store are real; --fake uses a fake worker and also fakes operator presence; the staging Otto is"
               " down at the end, so the census after is a clean line." if config.get("fake") else "")
    out += ["", "## Assertions", ""]
    out += table(["assertion", "result", "detail"],
                 [[r["name"], r["status"], r["detail"]] for r in results]) if results else ["(not checked)"]
    out += ["", "## Staging lifecycle", ""] + staging_lines(raw)
    if config.get("stage") == "2":
        out += ["", "## Operator admission attempts", ""] + stage2_admission_attempt_lines(raw)
    out += ["", "## Task timelines", ""]
    for task in config.get("tasks", []):
        rows = [[e["at"], e["source"], e["kind"], e["detail"]] for e in events if e["task"] == task["name"]]
        out.append("### %s (expect %s)" % (task["name"], task["expect"]))
        out += table(["at", "source", "event", "detail"], rows) if rows else ["(no events)"]
        out.append("")
    out += ["Store timelines (herzchen read, after down):", ""] + render_store(timeline)
    out += ["", "## Process census", "",
            "- before: %d otto-related process(es); after: %d" % (len(before), len(after))]
    leaked = leaks(raw, config)
    if leaked:
        out.append("- leaks (still running after down):")
        out += ["    " + line for line in leaked]
    else:
        out.append("- leaks (still running after down): none")
    gone = sorted(before - after - started)
    out.append("- gone during the run without perch starting them (wrong-kill candidates): %s"
               % (", ".join(map(str, gone)) if gone else "none"))
    out += ["", "## Labs and scratch left over", ""]
    leftovers = read_lines(raw / "leftovers.txt")
    out += ["- harness leftovers: " + line for line in leftovers] or ["- harness leftovers: none"]
    if config.get("stage") == "2":
        _, _, owner_summary = stage2_owner_lab_evidence(raw)
        out += owner_summary
    if config.get("stage") != "2":
        out += ["", "## Pool units over time", ""]
        out.append("peak %d of limit %s (perch's marks; samples peak %d)" % (
            pool_units_peak(raw), config.get("pool_limit", "?"), max([s["pool_units"] for s in samples] or [0])))
        out += table(["at", "pool units", "staging state"],
                     [[s["at"], s["pool_units"], "%s (gen %s)" % (s["staging_state"], s["staging_generation"])]
                      for s in samples]) if samples else ["(no samples)"]
    out += ["", "## Staging at rest", ""] + at_rest_lines(raw)
    out += ["", "## Store growth", ""]
    if samples:
        first, last = samples[0]["store_bytes"], samples[-1]["store_bytes"]
        saves = sum(len(t["events"]) for t in timeline.get("tasks", []))
        out.append("- store file bytes %d -> %d (+%d); events in the Store %s" % (first, last, last - first,
                                                                                 timeline.get("store_events", 0)))
        out.append("- per save (Store event): %s" % ("%.0f bytes" % ((last - first) / saves) if saves else "no Store saves"))
    out += ["", "## Git history", "", "Product line (canon/main of the repo under test):", "", "```",
            spend_and_history(raw / "report-product.txt"), "```", "",
            "Canary line (toy repo):", "", "```", spend_and_history(raw / "report-canary.txt"), "```"]
    out += ["", "## Tokens and cost per task", "",
            "The canary's worker is fake: no model, so no tokens and no cost are recorded (see the spend section above).",
            "", "## Waits and durations", ""]
    out += table(["phase", "task", "started", "seconds", "disk free KB", "swap"], duration_rows(raw))
    Path(args.out).write_text("\n".join(out) + "\n", encoding="utf-8")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stages"); p.add_argument("--project", required=True); p.set_defaults(fn=cmd_stages)
    p = sub.add_parser("composefleet"); p.add_argument("--stage-root", required=True); p.set_defaults(fn=cmd_capability)
    p = sub.add_parser("tasks"); p.add_argument("--project", required=True); p.add_argument("--stage", required=True)
    p.set_defaults(fn=cmd_tasks)
    p = sub.add_parser("stage"); p.add_argument("--project", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--key", required=True); p.set_defaults(fn=cmd_stage)
    p = sub.add_parser("stage2-bundle"); p.add_argument("--project", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_stage2_bundle)
    p = sub.add_parser("stage2-plan-save")
    p.add_argument("--project", required=True); p.add_argument("--registration", required=True)
    p.add_argument("--out", required=True); p.set_defaults(fn=cmd_stage2_plan_save)
    p = sub.add_parser("stage2-review-ref")
    p.add_argument("--status", required=True); p.add_argument("--activation", required=True)
    p.add_argument("--bundle", required=True); p.set_defaults(fn=cmd_stage2_review_ref)
    p = sub.add_parser("stage2-admission-check")
    p.add_argument("--response", required=True); p.add_argument("--task-ref", required=True)
    p.set_defaults(fn=cmd_stage2_admission_check)
    p = sub.add_parser("stage2-admission-held")
    p.add_argument("--response", required=True); p.set_defaults(fn=cmd_stage2_admission_held)
    p = sub.add_parser("stage2-admission-request")
    p.add_argument("--response", required=True); p.add_argument("--expected-request-id")
    p.set_defaults(fn=cmd_stage2_admission_request)
    p = sub.add_parser("stage2-boundary-closed")
    p.add_argument("--status", required=True); p.set_defaults(fn=cmd_stage2_boundary_closed)
    p = sub.add_parser("stage2-dispatch-check")
    p.add_argument("--status", required=True); p.add_argument("--activation", required=True)
    p.add_argument("--admission", required=True); p.add_argument("--task", required=True)
    p.set_defaults(fn=cmd_stage2_dispatch_check)
    p = sub.add_parser("stage2-dispatch-request")
    p.add_argument("--status", required=True); p.add_argument("--expected-request-id")
    p.set_defaults(fn=cmd_stage2_dispatch_request)
    p = sub.add_parser("stage2-dispatch-no-failure")
    p.add_argument("--status", required=True); p.add_argument("--task", required=True)
    p.set_defaults(fn=cmd_stage2_dispatch_no_failure)
    p = sub.add_parser("stage2-manager-start-failed")
    p.add_argument("--status", required=True); p.set_defaults(fn=cmd_stage2_manager_start_failed)
    p = sub.add_parser("stage2-manager-start-state")
    p.add_argument("--status", required=True); p.add_argument("--expected-request-id", required=True)
    p.set_defaults(fn=cmd_stage2_manager_start_state)
    p = sub.add_parser("stage2-task-complete")
    p.add_argument("--project-status", required=True); p.add_argument("--owner-status", required=True)
    p.add_argument("--task", required=True); p.set_defaults(fn=cmd_stage2_task_complete)
    p = sub.add_parser("stage2-task-landed")
    p.add_argument("--project-status", required=True); p.add_argument("--task", required=True)
    p.set_defaults(fn=cmd_stage2_task_landed)
    p = sub.add_parser("stage2-capacity-held"); p.add_argument("--status", required=True)
    p.set_defaults(fn=cmd_stage2_capacity_held)
    p = sub.add_parser("stage2-observations"); p.add_argument("--raw", required=True)
    p.set_defaults(fn=cmd_stage2_observations)
    p = sub.add_parser("stage2-owner-labs")
    p.add_argument("--root", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_stage2_owner_labs)
    p = sub.add_parser("stage2-kill-check"); p.add_argument("--raw", required=True)
    p.set_defaults(fn=cmd_stage2_kill_check)
    p = sub.add_parser("field"); p.add_argument("--project", required=True); p.add_argument("--key", required=True)
    p.set_defaults(fn=cmd_field)
    p = sub.add_parser("portfolio"); p.add_argument("--project", required=True); p.add_argument("--stage", required=True)
    p.set_defaults(fn=cmd_portfolio)
    p = sub.add_parser("admission"); p.add_argument("--raw", required=True); p.add_argument("--project", required=True)
    p.add_argument("--stage", required=True); p.set_defaults(fn=cmd_admission)
    p = sub.add_parser("save-doc"); p.add_argument("--project", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--name", required=True); p.add_argument("--ref-from", default="")
    p.add_argument("--out", required=True); p.set_defaults(fn=cmd_save_doc)
    p = sub.add_parser("census"); p.add_argument("--out", required=True); p.add_argument("--stage-root", default="")
    p.add_argument("--groups-file", default=""); p.add_argument("--fail-workers", action="store_true")
    p.set_defaults(fn=cmd_census)
    p = sub.add_parser("sample")
    p.add_argument("--raw", required=True); p.add_argument("--stage-root", required=True)
    p.add_argument("--canary", required=True); p.add_argument("--status", default="")
    p.set_defaults(fn=cmd_sample)
    p = sub.add_parser("snapshot")
    p.add_argument("--canon", required=True); p.add_argument("--labs", required=True)
    p.add_argument("--out", required=True); p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser("store"); p.add_argument("--store", required=True); p.add_argument("--out", required=True)
    p.add_argument("--refs", action="append", default=[]); p.add_argument("--src", default=""); p.add_argument("--admission", default="")
    p.set_defaults(fn=cmd_store)
    p = sub.add_parser("at-rest"); p.add_argument("--stage-root", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_at_rest)
    p = sub.add_parser("seed"); p.add_argument("--raw", required=True); p.add_argument("--fault", required=True)
    p.set_defaults(fn=cmd_seed)
    p = sub.add_parser("note"); p.add_argument("--raw", required=True); p.add_argument("--key", required=True)
    p.add_argument("--value", required=True); p.set_defaults(fn=cmd_note)
    p = sub.add_parser("timeline")
    p.add_argument("--src", required=True); p.add_argument("--store", required=True)
    p.add_argument("--authority", required=True); p.add_argument("--out", required=True); p.set_defaults(fn=cmd_timeline)
    p = sub.add_parser("init")
    p.add_argument("--raw", required=True); p.add_argument("--project", required=True)
    p.add_argument("--stage", required=True); p.add_argument("--fake", action="store_true")
    p.add_argument("--faults", default=""); p.add_argument("--staging-restart", type=int, required=True)
    p.add_argument("--staging-sha", default="?"); p.add_argument("--canon-main-sha", default="?")
    p.add_argument("--started-at", default="?"); p.add_argument("--stage-root", default="")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("check"); p.add_argument("--raw", required=True); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("render"); p.add_argument("--raw", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_render)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
