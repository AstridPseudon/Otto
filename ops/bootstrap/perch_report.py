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
CENSUS_MARKERS = ("_staging", "fake_worker", "perch-canary")
LEAK_MARKERS = ("_staging", "fake_worker")
# What `down` leaves in home/run: the published status (closed), the generation and the stop marker.
AT_REST_RUN = ("service.json", "generation", "service-stop")
LIFECYCLE = ("status-while-up", "status-after-kill-is-stale", "restart-after-kill-keeps-store",
             "status-after-stop", "refused-start-names-its-reason")
# Stage 1's save-through-socket scenario and the assertions it feeds. Each assertion reads the responses and
# Store snapshots the scenario wrote to raw/, and each has one seeded fault (seed --fault) that only it reads.
SAVE_SCENARIO = "save-through-socket"
STAGE1 = ("portfolio-admitted-before-saves", "tasks-are-typed-records", "nothing-runs", "edit-makes-revision",
          "stale-save-refused", "store-growth-per-save")
# The events of a lab run: a save starts none of them.
RUN_EVENTS = ("lab-created", "turn", "done", "check-passed", "check-failed", "landed", "refused", "lab-deleted")
# The events a task must show, by how it ends. "lab-created" and "lab-deleted" are the lab's life;
# the rest are the worker's turns and the check's verdict; "landed" and "refused" close the task.
REQUIRED = {
    "landed": ("lab-created", "turn", "done", "check-passed", "landed", "lab-deleted"),
    "refused": ("lab-created", "turn", "done", "check-failed", "refused", "lab-deleted"),
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
    # perch's own tools (this script, sampling or reporting) are not the Otto's processes.
    lines = [line for line in ps_lines() if line.split(None, 1)[0] != mine and "perch_report.py" not in line
             and ((root and root in line) or any(marker in line for marker in CENSUS_MARKERS))]
    Path(args.out).write_text("".join(line + "\n" for line in lines), encoding="utf-8")


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
    units = [line for line in ps_lines() if "fake_worker.py" in line and "--lab" in line and args.canary in line]
    status = read_status(args.status)
    line = {
        "at": now_iso(),
        "disk_free_kb": disk.free // 1024 if disk else None,
        "swap": swap,
        "pool_units": len(units),
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
    Path(args.out).write_text(json.dumps(store_snapshot(args.store), indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    if kind == "census":
        (raw / "census.up.txt").write_text("", encoding="utf-8")
    elif kind == "store":
        timeline = read_json(raw / "timeline.json", {}) or {}
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
        # A task ref with no record type: the create save's first task is not a typed record.
        save = seeded_read(raw / "save-create.json")
        refs = save.get("task_refs") or {}
        if not refs:
            raise ValueError("no saved task refs to seed a typed-record fault into")
        next(iter(refs.values()))["type"] = ""
        (raw / "save-create.json").write_text(json.dumps(save, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "nothing":
        # The create save claims it dispatched a run.
        save = seeded_read(raw / "save-create.json")
        save["dispatch"] = True
        (raw / "save-create.json").write_text(json.dumps(save, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "revision":
        # The edit's project ref is the create's revision: the edit did not move the project.
        created = seeded_read(raw / "save-create.json")
        edited = seeded_read(raw / "save-edit.json")
        edited["project_ref"] = dict(edited.get("project_ref") or {}, revision=(created.get("project_ref") or {}).get("revision"))
        (raw / "save-edit.json").write_text(json.dumps(edited, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "admit":
        # The owner's answer to admit-host is an unavailable outcome: no portfolio was admitted before the saves.
        seeded_read(raw / "admission.json")
        (raw / "admission.json").write_text(json.dumps({"outcome": "unavailable"}) + "\n", encoding="utf-8")
    elif kind == "stale":
        # The save from the old base is reported as saved, not refused.
        stale = seeded_read(raw / "save-stale.json")
        stale["outcome"] = "saved"
        (raw / "save-stale.json").write_text(json.dumps(stale, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif kind == "growth":
        # The Store after the stale save holds one row more than after the edit, so a refused save appears to write.
        snap = seeded_read(raw / "store-after-stale.json")
        rows = snap.get("rows", {})
        table = next(iter(sorted(rows)), None)
        if table is None:
            raise ValueError("no table with rows to seed a growth fault into")
        rows[table] += 1
        (raw / "store-after-stale.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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

    result = {"store": args.store, "store_events": 0, "tasks": [], "error": None}
    if not Path(args.store).exists():
        result["error"] = "no Store file"
    else:
        store = Store.open(args.store, authority=args.authority, expected_domains=host_domains())
        try:
            result["store_events"] = len(store.list_events())
            for timeline in timelines(store):
                result["tasks"].append({
                    "task_id": timeline.task_id,
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
    tasks = [{"name": name, "expect": project["tasks"][name]["expect"]} for name in stage["tasks"]]
    config = {
        "stage": args.stage, "fake": args.fake, "tasks": tasks, "check": project["check"], "stage_root": args.stage_root,
        "host": stage.get("host"),
        "pool_limit": project["pool_limit"], "store": stage.get("store"), "faults": [f for f in args.faults.split(",") if f],
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
    """Processes still running after down that belong to this run: under its own stage root.

    Another run's Otto or worker is not this run's leak, so the census is matched on the root, not the marker.
    """
    root = config.get("stage_root")
    return [line for line in read_lines(raw / "census.after.txt")
            if (root and root in line) or (not root and any(m in line for m in LEAK_MARKERS))]


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
    "tasks-are-typed-records": "the created project's tasks are typed refs (authority, type, id), one record type",
    "nothing-runs": "every save reports dispatch and launch false, and no lab, worker or turn ran",
    "edit-makes-revision": "saving one edited task moved the project to a later revision",
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

    if created is None:
        found["tasks-are-typed-records"].append("the create save was not recorded")
    else:
        refs = created.get("task_refs") or {}
        if not refs:
            found["tasks-are-typed-records"].append("the create save recorded no task refs")
        types = set()
        for alias, ref in sorted(refs.items()):
            if not isinstance(ref, dict) or not all(str(ref.get(k) or "").strip() for k in ("authority", "type", "id")):
                found["tasks-are-typed-records"].append("task %s is not a typed ref (authority, type, id)" % alias)
            else:
                types.add(ref["type"])
        if len(types) > 1:
            found["tasks-are-typed-records"].append("the tasks have %d record types" % len(types))

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

    if stale is None:
        found["stale-save-refused"].append("the stale save was not recorded")
    else:
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
    add("timeline-events", failures, "every task has its events")

    left = read_lines(raw / "leftovers.txt")
    add("labs-left-behind", ["left: " + line for line in left], "no lab, lab branch or lab folder left")

    # Until stage 2 there is no product pool to read: this is the harness's own count of its fake workers.
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
    skip = "skipped: staging did not start" if config.get("staging_restart") != 0 else None
    add("store-matches-stage", failures, "%s events and %s tasks in the Store, as the stage expects"
        % (expect and expect["store_events"], expect and expect["store_tasks"]), skip=skip)

    # After down the staging root holds only what a closed Otto leaves: no socket, no Store holder, no canary scratch.
    rest = read_json(raw / "at-rest.json", None)
    failures = []
    if rest is None:
        failures.append("the staging root was not checked after down")
    else:
        if rest.get("error"):
            failures.append("the staging root could not be read: " + rest["error"])
        failures += ["home/run holds %s, which down does not leave" % name
                     for name in rest.get("home_run", []) if name not in AT_REST_RUN]
        if rest.get("service_state") not in (None, "closed"):
            failures.append("service.json says %s after down" % rest.get("service_state"))
        failures += ["socket left behind: %s" % path for path in rest.get("sockets", [])]
        failures += ["%s is still held by pid %s" % (name, " ".join(pids))
                     for name, pids in sorted(rest.get("store_holders", {}).items()) if pids]
        failures += ["perch-canary/ still holds %s" % entry for entry in rest.get("perch_canary", [])]
    add("staging-at-rest-clean", failures, "after down: home/run holds only service.json (closed), generation and "
        "service-stop; no socket, no Store holder, no canary scratch")

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
        "- the start after the KILL exited %s" % notes.get("restart_after_kill_rc", "not run"),
        "- the second start exited %s; its refusal record: %s" % (notes.get("refused_start_rc", "not run"), refusal),
    ]


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
    out.append("- the Otto and its Store are real; the worker is fake (commits only, no model); the staging Otto is"
               " down at the end, so the census after is a clean line." if config.get("fake") else "")
    out += ["", "## Assertions", ""]
    out += table(["assertion", "result", "detail"],
                 [[r["name"], r["status"], r["detail"]] for r in results]) if results else ["(not checked)"]
    out += ["", "## Staging lifecycle", ""] + staging_lines(raw)
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
    out += ["    " + line for line in read_lines(raw / "leftovers.txt")] or ["none"]
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
    p = sub.add_parser("tasks"); p.add_argument("--project", required=True); p.add_argument("--stage", required=True)
    p.set_defaults(fn=cmd_tasks)
    p = sub.add_parser("stage"); p.add_argument("--project", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--key", required=True); p.set_defaults(fn=cmd_stage)
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
    p.set_defaults(fn=cmd_census)
    p = sub.add_parser("sample")
    p.add_argument("--raw", required=True); p.add_argument("--stage-root", required=True)
    p.add_argument("--canary", required=True); p.add_argument("--status", default="")
    p.set_defaults(fn=cmd_sample)
    p = sub.add_parser("snapshot")
    p.add_argument("--canon", required=True); p.add_argument("--labs", required=True)
    p.add_argument("--out", required=True); p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser("store"); p.add_argument("--store", required=True); p.add_argument("--out", required=True)
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
