"""PERCH's report: the Store's task timelines, the raw observations, the assertions and report.md.

perch.sh runs each part. Every subcommand reads or writes one run's raw folder, so a seeded fault
is a change to a file there and the checks are plain functions over it.
  stages    --project FILE                    the stage names in the canary project file
  tasks     --project FILE --stage S          the stage's task names, in order
  field     --project FILE --key KEY          one top-level string of the project file (e.g. check)
  census    --out FILE                        otto-related processes now (pid, pgid, etime, command)
  sample    --raw DIR --stage-root DIR --canary DIR   one line for samples.jsonl
  snapshot  --canon DIR --labs DIR --out FILE  worktrees, lab branches and lab folders left over
  timeline  --src DIR --store FILE --authority A --out FILE   the Store's task timelines (herzchen)
  init      --raw DIR ...                     config.json: the stage, the tasks and their expectations
  check     --raw DIR                         assertions.json; exit 1 on any failure
  render    --raw DIR --out FILE              report.md
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENSUS_MARKERS = ("ottoctl", "otto.hostctl", "_staging", "fake_worker", "perch-canary")
LEAK_MARKERS = ("_staging", "fake_worker")
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
    for name in read_json(args.project)["stages"][args.stage]:
        print(name)


def cmd_field(args):
    print(read_json(args.project)[args.key])


def cmd_census(args):
    mine = str(os.getpid())
    # perch's own tools (this script, sampling or reporting) are not the Otto's processes.
    lines = [line for line in ps_lines() if line.split(None, 1)[0] != mine and "perch_report.py" not in line
             and any(marker in line for marker in CENSUS_MARKERS)]
    Path(args.out).write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def store_bytes(store):
    return sum(os.path.getsize(p) for p in (store, store + "-wal") if os.path.exists(p))


def cmd_sample(args):
    raw = Path(args.raw)
    stage_root = Path(args.stage_root)
    disk = shutil.disk_usage(stage_root) if stage_root.exists() else None
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    units = [line for line in ps_lines() if "fake_worker.py" in line and "--lab" in line and args.canary in line]
    service = read_json(stage_root / "home" / "run" / "service.json", {}) or {}
    line = {
        "at": now_iso(),
        "disk_free_kb": disk.free // 1024 if disk else None,
        "swap": swap,
        "pool_units": len(units),
        "store_bytes": store_bytes(str(stage_root / "store" / "staging.store")),
        "staging_state": service.get("state"),
        "staging_generation": service.get("generation"),
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
    tasks = [{"name": name, "expect": project["tasks"][name]["expect"]} for name in project["stages"][args.stage]]
    config = {
        "stage": args.stage, "fake": args.fake, "tasks": tasks, "check": project["check"], "stage_root": args.stage_root,
        "pool_limit": project["pool_limit"], "faults": [f for f in args.faults.split(",") if f],
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

def assertions(raw):
    config = read_json(raw / "config.json", {}) or {}
    results = []

    def add(name, failures, ok_detail):
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
    timeline = read_json(raw / "timeline.json", {}) or {}
    for task in timeline.get("tasks", []):
        if not task["complete"]:
            failures.append("store timeline %s has gaps %s" % (task["task_id"], task["gaps"]))
    if timeline.get("error"):
        failures.append("store timeline: " + timeline["error"])
    add("timeline-events", failures, "every task has its events; no Store gaps")

    left = read_lines(raw / "leftovers.txt")
    add("labs-left-behind", ["left: " + line for line in left], "no lab, lab branch or lab folder left")

    limit = config.get("pool_limit")
    peak = pool_units_peak(raw)
    add("pool-units-within-limit", [] if limit is None or peak <= limit else ["peak %d units, limit %d" % (peak, limit)],
        "peak %s of limit %s" % (peak, limit))
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
    for r in results:
        print("%-4s %-26s %s" % ("PASS" if r["status"] == "pass" else "FAIL", r["name"], r["detail"]))
    return 0 if all(r["status"] == "pass" for r in results) else 1


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
    p = sub.add_parser("field"); p.add_argument("--project", required=True); p.add_argument("--key", required=True)
    p.set_defaults(fn=cmd_field)
    p = sub.add_parser("census"); p.add_argument("--out", required=True); p.set_defaults(fn=cmd_census)
    p = sub.add_parser("sample")
    p.add_argument("--raw", required=True); p.add_argument("--stage-root", required=True)
    p.add_argument("--canary", required=True); p.set_defaults(fn=cmd_sample)
    p = sub.add_parser("snapshot")
    p.add_argument("--canon", required=True); p.add_argument("--labs", required=True)
    p.add_argument("--out", required=True); p.set_defaults(fn=cmd_snapshot)
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
