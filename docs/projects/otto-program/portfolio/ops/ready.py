"""Which program tasks can start now: not landed, every dep landed, not running, not parked.

    python3 ops/ready.py          one line per ready task, in tasklist order: TASK route est
    python3 ops/ready.py --all    also the blocked ones, with what each waits on

The manager runs this on every wake instead of carrying a queue in its state file: two of its
rewrites dropped ready tasks (DISPATCH, PERCH1FIX; 16 Oct). Landed = a `Land TASK` merge on
canon/main, or a line in ops/LANDED-PRIOR.txt, or a status cell that says skipped.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OTTO = Path.home() / "Developer" / "otto-claude-host" / "otto"
LABS = Path.home() / "Developer" / "otto-claude-host" / "labs"
PARKED = re.compile(r"\*\*Parked until after CUTOVER")


def rows():
    for line in (ROOT / "projects" / "program" / "tasklist.md").read_text().splitlines():
        cells = line.split("|")
        if len(cells) != 11:
            continue
        task = cells[1].strip()
        if not task or task in {"id", "---"} or set(task) <= {"-"}:
            continue
        deps = [d.strip() for d in cells[4].split(",") if d.strip() and d.strip() not in {"—", "-"}]
        yield task, cells[2].strip(), cells[3].strip(), deps, cells[5], cells[9].strip()


def landed():
    log = subprocess.run(["git", "-C", str(OTTO), "log", "--first-parent", "--format=%s", "canon/main"],
                         capture_output=True, text=True).stdout
    done = {m.group(1) for m in re.finditer(r"^Land ([A-Za-z0-9_-]+):", log, re.M)}
    prior = ROOT / "ops" / "LANDED-PRIOR.txt"
    if prior.exists():
        done |= {m.group(0) for m in re.finditer(r"^[A-Z][A-Za-z0-9_]*", prior.read_text(), re.M)}
    return done


def running():
    try:
        entries = json.loads((ROOT / "ops" / "workers.json").read_text())
    except (OSError, ValueError):
        return set()
    live = set()
    for e in entries:
        if isinstance(e.get("pid"), int) and alive(e["pid"]):
            live.add(e["task"])
    return live


def alive(pid):
    """Signal 0, not `ps`: Codex's sandbox refuses `ps`, and the manager runs there. A refused
    signal (EPERM) still means the process exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def waiting_to_land(task):
    """A lab with commits not on canon/main: finished work that only needs landing."""
    lab = LABS / task
    if not lab.is_dir():
        return False
    ahead = subprocess.run(["git", "-C", str(lab), "rev-list", "--count", "canon/main..HEAD"],
                           capture_output=True, text=True).stdout.strip()
    return ahead.isdigit() and int(ahead) > 0


def refused_since_commit(task):
    """The refusal reason when the task's last landing was refused (not for a D19) and its lab
    hasn't changed since, so its worker must fix it before it can land."""
    out = ROOT / "ops" / "runs" / task / "land.out"
    lab = LABS / task
    if not out.exists() or not lab.is_dir():
        return None
    results = [l for l in out.read_text(errors="replace").splitlines() if l.startswith("LAND RESULT:")]
    if not results or "refused" not in results[-1] or "d19" in results[-1]:
        return None
    if "another landing is running" in results[-1]:
        return None  # nothing wrong with the lab: it only waits its turn
    head_time = subprocess.run(["git", "-C", str(lab), "log", "-1", "--format=%ct"],
                               capture_output=True, text=True).stdout.strip()
    brief = lab / ".brief.md"
    changed = max(int(head_time) if head_time.isdigit() else 0, int(brief.stat().st_mtime) if brief.exists() else 0)
    if changed > out.stat().st_mtime:
        return None  # new work, or a narrowed check, since the refusal: it waits to land again
    return results[-1].split("refused", 1)[1].strip()[:90]


def main(argv):
    done, live = landed(), running()
    for task, route, est, deps, outcome, status in rows():
        if task in done or "skipped" in status or route in {"owner action"}:
            continue
        missing = [d for d in deps if d not in done]
        why = []
        refused = refused_since_commit(task)
        if task in live:
            why.append("running")
        elif refused:
            print(f"{task} {route} {est} RESUME: its landing was refused ({refused}); resume its worker with land.log")
            continue
        elif waiting_to_land(task):
            why.append("committed, waiting to land")
        if PARKED.search(outcome):
            why.append("parked")
        if missing:
            why.append("waits on " + ", ".join(missing))
        if not why:
            print(f"{task} {route} {est}")
        elif "--all" in argv:
            print(f"  {task} {route} {est}: {'; '.join(why)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
