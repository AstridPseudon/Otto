"""Run one bounded command and append an exact JSONL custody receipt."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


parser = argparse.ArgumentParser()
parser.add_argument("--label", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--receipt", required=True)
parser.add_argument("--cwd", required=True)
parser.add_argument("--model", default="gpt-5.6-luna")
parser.add_argument("--reasoning", default="high")
parser.add_argument("--write-mode", default="isolated-checkout-owned-paths")
parser.add_argument("--unset-python-path", action="store_true")
parser.add_argument("command", nargs=argparse.REMAINDER)
args = parser.parse_args()
command = list(args.command)
if command and command[0] == "--":
    command.pop(0)
if not command:
    raise SystemExit("a command is required after --")

environment = os.environ.copy()
if args.unset_python_path:
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
start = stamp()
with Path(args.output).open("w", encoding="utf-8") as stream:
    process = subprocess.Popen(command, cwd=args.cwd, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    record = {
        "format": "otto-execution-receipt/v1",
        "label": args.label,
        "command": command,
        "command_text": " ".join(command),
        "model": args.model,
        "reasoning": args.reasoning,
        "cwd": args.cwd,
        "write_mode": args.write_mode,
        "started": start,
        "process_id": process.pid,
        "session_id": None,
        "environment": {
            "PYTHONPATH": "unset" if args.unset_python_path else environment.get("PYTHONPATH"),
            "PYTHONHOME": "unset" if args.unset_python_path else environment.get("PYTHONHOME"),
        },
    }
    process.wait()
record["ended"] = stamp()
record["exit_code"] = process.returncode
with Path(args.receipt).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\n")
print(json.dumps(record, sort_keys=True))
raise SystemExit(process.returncode)
