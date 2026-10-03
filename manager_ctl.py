#!/usr/bin/env python3
"""Thin client for the live owner-held Otto manager command port."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import uuid

IPC = Path(__file__).resolve().parent.parent / "controller" / "manager-ipc"


def call(payload: dict) -> dict:
    token = uuid.uuid4().hex
    request = IPC / ("request-" + token + ".json")
    response = IPC / ("response-" + token + ".json")
    if not IPC.is_dir():
        raise RuntimeError("owner command channel is unavailable")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(request, flags, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    deadline = time.monotonic() + 1000
    while time.monotonic() < deadline:
        try:
            value = json.loads(response.read_text())
        except FileNotFoundError:
            time.sleep(0.1)
            continue
        response.unlink(missing_ok=True)
        return value
    raise TimeoutError("owner command response deadline expired; inspect status before retry")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="read current canonical project/task/assignment state")
    report = commands.add_parser("report", help="append a canonical manager progress report")
    report.add_argument("--task", required=True, choices=[f"PA0{i}" for i in range(1, 7)])
    report.add_argument("--summary", required=True)
    report.add_argument("--next-action", required=True)
    report.add_argument("--request-key", required=True)
    assign = commands.add_parser("assign-worker", help="create one canonical worker assignment and adopted task guide")
    assign.add_argument("--task", required=True, choices=[f"PA0{i}" for i in range(1, 7)])
    assign.add_argument("--principal", required=True)
    assign.add_argument("--route", required=True, choices=["normal", "xhard"])
    assign.add_argument("--request-key", required=True)
    run = commands.add_parser("run-worker", help="assign, launch, and collect one canonical bounded worker")
    run.add_argument("--task", required=True, choices=[f"PA0{i}" for i in range(1, 7)])
    run.add_argument("--principal", required=True)
    run.add_argument("--route", required=True, choices=["normal", "xhard"])
    run.add_argument("--request-key", required=True)
    resume = commands.add_parser("resume-worker", help="resume and collect one inspected interrupted worker")
    resume.add_argument("--task", required=True, choices=[f"PA0{i}" for i in range(1, 7)])
    resume.add_argument("--principal", required=True)
    resume.add_argument("--route", required=True, choices=["normal", "xhard"])
    resume.add_argument("--request-key", required=True)
    args = parser.parse_args()
    payload = vars(args)
    response = call(payload)
    print(json.dumps(response, indent=2, sort_keys=True))
    if response.get("outcome") not in {"ok", "committed", "replayed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
