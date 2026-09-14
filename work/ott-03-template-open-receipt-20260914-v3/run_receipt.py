"""Run one evidence command and append an exact JSONL execution receipt."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
RECEIPTS = EVIDENCE / "execution-receipts.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    if len(sys.argv) < 6 or sys.argv[4] != "--":
        raise SystemExit("usage: run_receipt.py LABEL MODE OUTPUT -- COMMAND [ARG ...]")
    label, mode, output_name = sys.argv[1:4]
    command = sys.argv[5:]
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    if mode == "source":
        env["PYTHONPATH"] = str(ROOT / "src")
    elif mode in {"installed", "build"}:
        env.pop("PYTHONPATH", None)
    else:
        raise SystemExit("MODE must be source, installed, or build")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    output_path = EVIDENCE / output_name
    start = utc_now()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output, _ = process.communicate()
    end = utc_now()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    match = re.search(r"(\d+) passed", output)
    receipt = {
        "label": label,
        "command": command,
        "command_text": shlex.join(command),
        "cwd": str(ROOT),
        "environment": {
            "PYTHONHOME": "unset",
            "PYTHONPATH": str(ROOT / "src") if mode == "source" else "unset",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "start": start,
        "end": end,
        "process_id": process.pid,
        "cli_session_id": 16241,
        "thread_id": "01a0a108-d716-7330-9451-724d610e117f",
        "return_code": process.returncode,
        "model": "gpt-5.6-sol",
        "reasoning": "high",
        "write_mode": "isolated-checkout-owned-paths",
        "output": str(output_path.relative_to(ROOT)),
        "test_count": int(match.group(1)) if match else None,
    }
    with RECEIPTS.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, sort_keys=True) + "\n")
    sys.stdout.write(output)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
