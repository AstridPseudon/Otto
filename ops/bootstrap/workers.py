#!/usr/bin/env python3.11
"""Bookkeeping for the bootstrap scripts: the running-worker ledger and per-task spend.

  workers.py times SECONDS                      print "STARTED DEADLINE" (UTC, ISO 8601)
  workers.py check  --file F --task T           exit 1 if T's worker is still alive
  workers.py add    --file F --task T --pid P --session S --model M --budget B \
                    --lab L --started ISO --deadline ISO
  workers.py remove --file F --task T           drop T's entry; exit 1 if its worker is alive
  workers.py list   --file F                    one line per recorded worker
  workers.py spend  --runs DIR                  cost per task, from DIR/*/worker.json

F is a JSON list, the manager's ops/workers.json. Writes take a lock and replace the file
atomically. Nothing here starts or signals a process, except that reading liveness is kill -0.
"""
import argparse
import datetime
import fcntl
import json
import os
import sys
from contextlib import contextmanager


@contextmanager
def locked(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save(path, entries):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cmd_times(args):
    now = datetime.datetime.now(datetime.timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    later = now + datetime.timedelta(seconds=int(args.seconds))
    print(now.strftime(fmt), later.strftime(fmt))
    return 0


def cmd_check(args):
    for entry in load(args.file):
        if entry["task"] == args.task and alive(entry["pid"]):
            print(f"worker for {args.task} is still running (pid {entry['pid']})", file=sys.stderr)
            return 1
    return 0


def cmd_add(args):
    with locked(args.file):
        entries = [e for e in load(args.file) if e["task"] != args.task]
        entries.append({
            "task": args.task,
            "pid": args.pid,
            "session_id": args.session,
            "model": args.model,
            "started": args.started,
            "deadline": args.deadline,
            "budget_usd": float(args.budget),
            "lab": args.lab,
            "pgid": args.pid,  # the worker leads its own process group
        })
        save(args.file, entries)
    return 0


def cmd_remove(args):
    with locked(args.file):
        entries = load(args.file)
        for entry in entries:
            if entry["task"] == args.task and alive(entry["pid"]):
                print(f"worker for {args.task} is still running (pid {entry['pid']})", file=sys.stderr)
                return 1
        kept = [e for e in entries if e["task"] != args.task]
        if len(kept) != len(entries):
            save(args.file, kept)
    return 0


def cmd_list(args):
    entries = load(args.file)
    if not entries:
        print("  (no workers recorded)")
    for e in entries:
        state = "running" if alive(e["pid"]) else "exited"
        print(f"  {e['task']:<14} {state:<8} pid {e['pid']:<7} {e['model']:<18} "
              f"started {e['started']}  deadline {e['deadline']}")
    return 0


def cmd_spend(args):
    rows, total = [], 0.0
    names = sorted(os.listdir(args.runs)) if os.path.isdir(args.runs) else []
    for name in names:
        path = os.path.join(args.runs, name, "worker.json")
        if not os.path.isfile(path):
            continue
        if os.path.getsize(path) == 0:
            rows.append((name, None, "no output yet"))
            continue
        try:
            with open(path) as f:
                result = json.load(f)
        except (ValueError, OSError):
            rows.append((name, None, "output not readable"))
            continue
        cost = result.get("total_cost_usd") if isinstance(result, dict) else None
        if isinstance(cost, (int, float)):
            total += cost
        state = "error" if isinstance(result, dict) and result.get("is_error") else "ok"
        rows.append((name, cost, state))
    if not rows:
        print("  (no runs recorded)")
    for name, cost, state in rows:
        amount = f"${cost:.4f}" if isinstance(cost, (int, float)) else "-"
        print(f"  {name:<14} {amount:>10}  {state}")
    if rows:
        print(f"  {'total':<14} {'$%.4f' % total:>10}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("times")
    p.add_argument("seconds")
    p.set_defaults(run=cmd_times)

    for name, run in (("check", cmd_check), ("remove", cmd_remove), ("list", cmd_list)):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True)
        if name != "list":
            p.add_argument("--task", required=True)
        p.set_defaults(run=run)

    p = sub.add_parser("add")
    p.add_argument("--file", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--budget", required=True)
    p.add_argument("--lab", required=True)
    p.add_argument("--started", required=True)
    p.add_argument("--deadline", required=True)
    p.set_defaults(run=cmd_add)

    p = sub.add_parser("spend")
    p.add_argument("--runs", required=True)
    p.set_defaults(run=cmd_spend)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
