"""Run one amendment campaign and append exact execution metadata."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "work/ott-03-template-amendment-receipt-20260914/execution-receipts.jsonl"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def main(label, output_name, installed, command):
    output = ROOT / "work/ott-03-template-amendment-receipt-20260914" / output_name
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    if installed:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(ROOT / "src")
    started = stamp()
    with output.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, text=True)
        return_code = process.wait()
    ended = stamp()
    text = output.read_text(encoding="utf-8")
    match = re.search(r"(\d+) passed", text)
    receipt = {
        "label": label,
        "model": "gpt-5.6-luna",
        "reasoning": "high",
        "cwd": str(ROOT),
        "write_mode": "isolated-checkout-owned-paths",
        "command": command,
        "environment": {"PYTHONPATH": "unset" if installed else str(ROOT / "src"), "PYTHONHOME": "unset"},
        "start": started,
        "end": ended,
        "process_id": process.pid,
        "session_id": None,
        "exit_code": return_code,
        "test_count": int(match.group(1)) if match else None,
        "output": str(output.relative_to(ROOT)),
    }
    with RECEIPTS.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    raise SystemExit(return_code)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        raise SystemExit("usage: run_receipt_amendment.py LABEL OUTPUT INSTALLED COMMAND...")
    main(sys.argv[1], sys.argv[2], sys.argv[3] == "installed", sys.argv[4:])
