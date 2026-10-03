#!/usr/bin/env python3
"""Thin client for the live owner-held Otto manager command port."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket

SOCKET = Path("/tmp/otto-project-advisor-manager-ops.sock")


def call(payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1300)
        client.connect(str(SOCKET))
        client.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        chunks = []
        while True:
            part = client.recv(65536)
            if not part:
                break
            chunks.append(part)
    return json.loads(b"".join(chunks))


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
    args = parser.parse_args()
    payload = vars(args)
    response = call(payload)
    print(json.dumps(response, indent=2, sort_keys=True))
    if response.get("outcome") not in {"ok", "committed", "replayed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
