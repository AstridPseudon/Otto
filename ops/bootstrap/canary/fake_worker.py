"""The PERCH canary's fake worker: real commits in a lab, no model, no provider.

It plays the turns a canary task's project file gives it, one commit per turn, and logs each turn
and the final "done" as a JSON line. It never leaves its lab and never touches another repository.
  fake_worker.py --lab LAB --task TASK --project FILE --events FILE [--hold]
--hold sleeps until stopped instead of finishing; perch uses it only for seeded faults.
Exit 0 when every turn committed; 2 when a turn's text to replace is not in the file.
"""
import argparse
import datetime
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

IDENTITY = ["-c", "user.name=perch-canary", "-c", "user.email=perch-canary@localhost"]


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(path, **event):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event, at=now()), sort_keys=True) + "\n")


def git(lab, *args):
    return subprocess.run(["git", "-C", str(lab), *IDENTITY, *args], check=True, capture_output=True, text=True).stdout


def apply(lab, turn):
    target = lab / turn["path"]
    text = target.read_text(encoding="utf-8")
    if "append" in turn:
        text += turn["append"]
    else:
        old, new = turn["replace"]
        if old not in text:
            raise LookupError("text to replace is not in %s" % turn["path"])
        text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lab", required=True, type=Path)
    parser.add_argument("--task", required=True)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args(argv)
    if args.hold:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        while True:
            time.sleep(1)
    task = json.loads(args.project.read_text(encoding="utf-8"))["tasks"][args.task]
    for number, turn in enumerate(task["turns"], start=1):
        try:
            apply(args.lab, turn)
        except LookupError as exc:
            log(args.events, kind="turn-failed", task=args.task, turn=number, detail=str(exc))
            return 2
        git(args.lab, "add", "-A")
        git(args.lab, "commit", "-q", "-m", "turn %d: %s" % (number, args.task))
        log(args.events, kind="turn", task=args.task, turn=number, sha=git(args.lab, "rev-parse", "--short", "HEAD").strip())
    log(args.events, kind="done", task=args.task, turns=len(task["turns"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
