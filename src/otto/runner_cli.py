"""CLI for submitting, observing and recovering fleet runner work."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from typing import Any, Optional

from herzchen.fleet.runner.client import RunnerClient, RunnerUnavailable

from .hostctl.config import otto_home

EXIT_USAGE = 2
EXIT_ERROR = 1
EXIT_UNREACHABLE = 69
EXIT_TIMED_OUT = 3


def default_socket() -> str:
    return os.environ.get("OTTO_RUNNER_SOCKET") or str(otto_home() / "runner.sock")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otto run", description="submit work and inspect runner lifecycle")
    parser.add_argument("--socket", default=None, help="runner socket (default $OTTO_RUNNER_SOCKET or <otto home>/runner.sock)")
    sub = parser.add_subparsers(dest="command")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--socket", default=argparse.SUPPRESS)
    submit = sub.add_parser("submit", parents=[shared], help="queue a command under the runner")
    submit.add_argument("--weight", type=int, default=1)
    submit.add_argument("--task", default="untasked")
    submit.add_argument("--purpose", default=None)
    submit.add_argument("--max-minutes", type=float, default=None)
    submit.add_argument("--request-id", default=None)
    submit.add_argument("--cwd", default=None)
    submit.add_argument("--wait", action="store_true")
    submit.add_argument("argv", nargs="+", metavar="CMD")
    await_ = sub.add_parser("await", parents=[shared], help="wait for a run and exit with its code")
    await_.add_argument("run_id")
    await_.add_argument("--timeout", type=float, default=None)
    status = sub.add_parser("status", parents=[shared], help="show capacity and run state")
    status.add_argument("run_id", nargs="?", default=None)
    report = sub.add_parser("report", parents=[shared], help="sum stored results per task")
    report.add_argument("--task", default=None)
    daemon = sub.add_parser("daemon", parents=[shared], help="run the runner daemon in the foreground")
    daemon.add_argument("--state-dir", required=True)
    daemon.add_argument("--capacity", type=int, default=None)
    daemon.add_argument("--forbid-root", action="append", default=[])
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return int(stop.code or 0)
    if args.command is None:
        parser.print_help()
        return EXIT_USAGE
    if args.command == "daemon":
        return _daemon(args)
    client = RunnerClient(args.socket or default_socket())
    try:
        if args.command == "submit":
            return _submit(args, client)
        if args.command == "await":
            response = client.call(_await_request(args.run_id, args.timeout))
            return _emit(response, _await_code(response))
        if args.command == "status":
            request: dict[str, Any] = {"op": "status"}
            if args.run_id is not None:
                request["run_id"] = args.run_id
            return _emit_ok(client.call(request))
        request = {"op": "report"}
        if args.task is not None:
            request["task"] = args.task
        return _emit_ok(client.call(request))
    except RunnerUnavailable as exc:
        return _emit({"ok": False, "error": "runner_unavailable", "detail": str(exc)}, EXIT_UNREACHABLE)


def _submit(args: argparse.Namespace, client: RunnerClient) -> int:
    request: dict[str, Any] = {"op": "submit", "argv": args.argv, "cwd": os.path.abspath(args.cwd or "."),
                               "weight": args.weight, "task": args.task}
    if args.purpose is not None:
        request["purpose"] = args.purpose
    if args.max_minutes is not None:
        request["max_seconds"] = args.max_minutes * 60
    request["request_id"] = args.request_id or uuid.uuid4().hex
    response = client.call(request)
    response.setdefault("request_id", request["request_id"])
    if not response.get("ok") or not args.wait:
        return _emit_ok(response)
    print(json.dumps(response, sort_keys=True))
    waited = client.call(_await_request(response["run_id"], None))
    return _emit(waited, _await_code(waited))


def _await_request(run_id: str, timeout: Optional[float]) -> dict[str, Any]:
    request: dict[str, Any] = {"op": "await", "run_id": run_id}
    if timeout is not None:
        request["timeout"] = timeout
    return request


def _await_code(response: dict[str, Any]) -> int:
    if not response.get("ok"):
        return EXIT_ERROR
    if not response.get("done"):
        return EXIT_TIMED_OUT
    code = response.get("exit_code")
    return code if isinstance(code, int) else EXIT_ERROR


def _daemon(args: argparse.Namespace) -> int:
    from herzchen.fleet.runner import server

    server_argv = ["--socket", args.socket or default_socket(), "--state-dir", args.state_dir]
    if args.capacity is not None:
        server_argv += ["--capacity", str(args.capacity)]
    for root in args.forbid_root:
        server_argv += ["--forbid-root", root]
    return int(server.main(server_argv) or 0)


def _emit_ok(response: dict[str, Any]) -> int:
    return _emit(response, 0 if response.get("ok") else EXIT_ERROR)


def _emit(response: dict[str, Any], code: int) -> int:
    print(json.dumps(response, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
