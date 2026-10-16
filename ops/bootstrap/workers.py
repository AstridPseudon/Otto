#!/usr/bin/env python3.11
"""Bookkeeping for the bootstrap scripts: the running-worker ledger and per-task spend.

  workers.py times SECONDS                      print "STARTED DEADLINE" (UTC, ISO 8601)
  workers.py check  --file F --task T           exit 1 if T's worker is still alive
  workers.py add    --file F --task T --pid P --session S --model M --budget B \
                    --lab L --started ISO --deadline ISO
  workers.py remove --file F --task T           drop T's entry; exit 1 if its worker is alive
  workers.py list   --file F                    one line per recorded worker
  workers.py spend  --runs DIR                  per task: claude cost (last run file), codex tokens
  workers.py codex-session --events F --pid P  print the session id codex names in F
  workers.py wait   --file F --inbox R [--land-out P ...]
                    block until something needs the manager: a recorded worker exits, a
                    new "## Orchestrator" heading appears in R, or a P gets its LAND RESULT line;
                    print one line per reason. The manager's one way to wait.

F is a JSON list, the manager's ops/workers.json. Writes take a lock and replace the file
atomically. Nothing here starts or signals a process, except that reading liveness is kill -0.
"""
import argparse
import datetime
import fcntl
import json
import os
import sys
import time
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


def orchestrator_headings(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [line.rstrip("\n") for line in f if line.startswith("## Orchestrator")]


def land_result(path):
    if not os.path.exists(path):
        return None
    with open(path, errors="replace") as f:
        lines = [line.rstrip("\n") for line in f if line.startswith("LAND RESULT:")]
    return lines[-1] if lines else None


def cmd_wait(args):
    running = {e["task"]: e["pid"] for e in load(args.file) if alive(e["pid"])}
    seen = len(orchestrator_headings(args.inbox))
    landing = [p for p in args.land_out if land_result(p) is None]
    if not running and not landing:
        # Nothing of its own runs, so the manager is waiting on the orchestrator: wait on the inbox alone
        # (16 Oct: with an early return here, the manager wrote its own sleep-loop watcher instead).
        print("nothing running: no live worker and no landing in progress; waiting on the inbox only", flush=True)
    print(f"waiting on workers {sorted(running) or '-'}, landings {landing or '-'}, inbox {args.inbox}",
          file=sys.stderr, flush=True)
    while True:
        reasons = [f"worker exited: {task} (pid {pid})" for task, pid in sorted(running.items()) if not alive(pid)]
        reasons += [f"landing finished: {p}: {land_result(p)}" for p in landing if land_result(p) is not None]
        reasons += [f"orchestrator: {h}" for h in orchestrator_headings(args.inbox)[seen:]]
        if reasons:
            print("\n".join(reasons))
            return 0
        time.sleep(args.poll)


def cmd_list(args):
    entries = load(args.file)
    if not entries:
        print("  (no workers recorded)")
    for e in entries:
        state = "running" if alive(e["pid"]) else "exited"
        print(f"  {e['task']:<14} {state:<8} pid {e['pid']:<7} {e['model']:<18} "
              f"started {e['started']}  deadline {e['deadline']}")
    return 0


def _run_number(name):
    """worker.json is run 0; worker.N.json(l) is resume N of the same session."""
    middle = name.split(".")[1] if name.count(".") == 2 else "0"
    return int(middle) if middle.isdigit() else 0


def codex_usage(path):
    """Summed turn.completed usage of one Codex --json event file (each resume writes its own)."""
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    with open(path, errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "turn.completed":
                for key in total:
                    total[key] += int((event.get("usage") or {}).get(key) or 0)
    return total


def cmd_spend(args):
    """Per task: claude's cost is the LAST run file's total_cost_usd (a resumed session reports its
    running total, so the files must never be added up); codex's tokens are summed over its event files."""
    rows, total = [], 0.0
    names = sorted(os.listdir(args.runs)) if os.path.isdir(args.runs) else []
    for name in names:
        folder = os.path.join(args.runs, name)
        files = os.listdir(folder) if os.path.isdir(folder) else []
        claude = sorted((f for f in files if f.startswith("worker.") and f.endswith(".json")), key=_run_number)
        codex = sorted((f for f in files if f.startswith("worker.") and f.endswith(".jsonl")), key=_run_number)
        if claude:
            path = os.path.join(folder, claude[-1])
            label = name if len(claude) == 1 else f"{name} ({len(claude)} runs)"
            try:
                result = json.load(open(path)) if os.path.getsize(path) else None
            except (ValueError, OSError):
                result = None
            if result is None:
                rows.append((label, None, "no output (running, stopped or unreadable)"))
            else:
                cost = result.get("total_cost_usd") if isinstance(result, dict) else None
                if isinstance(cost, (int, float)):
                    total += cost
                rows.append((label, cost, "error" if isinstance(result, dict) and result.get("is_error") else "ok"))
        if codex:
            usage = [codex_usage(os.path.join(folder, f)) for f in codex]
            used = {key: sum(u[key] for u in usage) for key in usage[0]}
            rows.append((f"{name} (codex, {len(codex)} runs)", None,
                         "in %(input_tokens)d (cached %(cached_input_tokens)d), out %(output_tokens)d "
                         "(reasoning %(reasoning_output_tokens)d)" % used))
    if not rows:
        print("  (no runs recorded)")
    for name, cost, state in rows:
        amount = f"${cost:.4f}" if isinstance(cost, (int, float)) else "-"
        print(f"  {name:<14} {amount:>10}  {state}")
    if rows:
        print(f"  {'total (claude)':<14} {'$%.4f' % total:>10}")
    return 0


def cmd_codex_session(args):
    """Print the session id Codex names in its first event; fail if the process ends first."""
    while True:
        if os.path.exists(args.events):
            with open(args.events, errors="replace") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "thread.started" and event.get("thread_id"):
                        print(event["thread_id"])
                        return 0
        if not alive(args.pid):
            print(f"codex (pid {args.pid}) ended before naming a session", file=sys.stderr)
            return 1
        time.sleep(args.poll)


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

    p = sub.add_parser("wait")
    p.add_argument("--file", required=True)
    p.add_argument("--inbox", required=True)
    p.add_argument("--land-out", action="append", default=[])
    p.add_argument("--poll", type=float, default=15.0)
    p.set_defaults(run=cmd_wait)

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

    p = sub.add_parser("codex-session")
    p.add_argument("--events", required=True)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--poll", type=float, default=0.5)
    p.set_defaults(run=cmd_codex_session)

    p = sub.add_parser("spend")
    p.add_argument("--runs", required=True)
    p.set_defaults(run=cmd_spend)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
