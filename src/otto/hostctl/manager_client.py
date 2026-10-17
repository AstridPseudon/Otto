"""`ottoctl manager ...`: the manager command port.

Two callers use it:

* the orchestrator (a host client): its owner-custody commands (status,
  start-manager, read-help, manager-continue, command-status, ...) are parsed
  here and relayed by the owner service through the host's lane to the
  attached project's manager lane (see ``cli.client_request``);
* a process the owner launched (the manager, or a worker): it has
  OTTO_MANAGER_IPC and OTTO_CALLER_SOCKET in its environment. Identity-bearing
  commands (whoami, run-worker, project-documents, ...) go over the caller
  socket, where the owner authenticates it by kernel peer ancestry; every
  other command goes through its file lane, which its write fence admits and
  the owner serves even during the manager's own turn.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping
import uuid


def build_parser() -> argparse.ArgumentParser:
    from otto.portfolio.manager_journey_client import add_manager_journey_parsers
    parser = argparse.ArgumentParser(prog="ottoctl manager", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout-seconds", type=float, default=10.0,
                        help="bounded wait for a file-lane reply (the request stays durable)")
    parser.add_argument("--project", help="the orchestrator's target project (id or run id; default: the attached one)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="current canonical project/task/assignment projection")
    sub.add_parser("whoami", help="the bound caller, via the identity-bearing socket")
    sub.add_parser("effective-context", help="the bound caller's adopted context, via the socket")
    documents = sub.add_parser("project-documents", help="the bound manager reads its project's documents through Otto")
    documents.add_argument("--operation", choices=("list", "read"), default="list")
    documents.add_argument("--path", help="the project path to read, e.g. briefs/M1.md")
    lifecycle = sub.add_parser("project-lifecycle-read", help="read the current bound project lifecycle")
    lifecycle.add_argument("--task", required=True)
    report = sub.add_parser("report", help="append a canonical manager progress report")
    report.add_argument("--task", required=True)
    report.add_argument("--request-key", help=argparse.SUPPRESS)
    report.add_argument("--summary", required=True)
    report.add_argument("--next-action", required=True)
    report.add_argument("--continue-project", action="store_true")
    worker = sub.add_parser("run-worker", help="assign and launch one bounded worker for a task route")
    worker.add_argument("--task", required=True)
    worker.add_argument("--route", required=True, choices=["normal", "xhard"])
    worker.add_argument("--principal", required=True)
    worker.add_argument("--request-key", required=True)
    worker.add_argument("--focus", required=True)
    start = sub.add_parser("start-manager", help="ACTIVATION: launch the adopted manager occurrence (owner custody)")
    start.add_argument("--schedule-id", required=True)
    continuation = sub.add_parser("manager-continue", help="consume an explicit same-manager report")
    continuation.add_argument("--report-key", required=True)
    continuation.add_argument("--operation", default="prepare")
    continuation.add_argument("--new-report-key")
    add_manager_journey_parsers(sub)
    return parser


def socket_command(command: str) -> bool:
    from otto.portfolio.manager_journey_client import requires_native_caller
    from .serve import HOST_SOCKET_READS
    return requires_native_caller(command) or command in HOST_SOCKET_READS


def run_launched(argv: list[str], environ: Mapping[str, str]) -> Mapping[str, Any]:
    """A launched manager's or worker's command, over its own lanes."""
    from otto.portfolio.manager_journey_client import read_command_status, wait_command_response
    args = vars(build_parser().parse_args(argv))
    timeout = args.pop("timeout_seconds")
    args.pop("project", None)
    if args["command"] == "route":
        # The owner accepts only fields for the selected route operation.
        # Argparse exposes the inactive reroute/retry options as None, so omit
        # them from the identity-bearing caller request.
        args = {key: value for key, value in args.items() if value is not None}
    if args["command"] in {"report", "save", "answer", "route"}:
        # Logical keys are tool-owned. The transport has a separate retained
        # request handle, so the manager never invents or reuses owner keys.
        args["request_key"] = "manager-tool:" + uuid.uuid4().hex
    ipc = Path(environ.get("OTTO_MANAGER_IPC") or "")
    if args["command"] == "command-status":
        return read_command_status(ipc, args["request_id"]) or {
            "outcome": "unavailable", "terminal": False, "request_id": args["request_id"], "retry": False,
            "next_action": "no exact request or response is visible; inspect retained owner receipts before any replay"}
    if socket_command(args["command"]):
        caller_socket = environ.get("OTTO_CALLER_SOCKET")
        if not caller_socket:
            raise PermissionError(args["command"] + " is identity-bearing and needs the owner's caller socket")
        from otto.portfolio.caller_client import call
        return call(caller_socket, args)
    if ipc.name != "manager-ipc" or not ipc.is_dir():
        raise PermissionError("this process has no manager lane (OTTO_MANAGER_IPC)")
    from .lanes import submit
    token = submit(ipc, args, token=uuid.uuid4().hex)  # written aside, linked into place
    result = wait_command_response(ipc, token, timeout_seconds=timeout)
    return result if isinstance(result, Mapping) else {"outcome": "unknown", "request_id": token}
