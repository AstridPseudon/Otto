"""Read/status/inspect-first command gateway for the neutral Otto surface."""
from __future__ import annotations

import argparse
import json
from typing import Any, Optional

from .agents import OttoGateway, Responsibility


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otto", description="thin neutral responsibility gateway")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("read", help="read current responsibility and binding state")
    sub.add_parser("status", help="show current binding status")
    sub.add_parser("dry-run", help="show an invocation plan without transport effects")
    inspect = sub.add_parser("inspect", help="inspect one logical responsibility")
    inspect.add_argument("logical_agent_id")
    inspect.add_argument("--owner", required=True)
    inspect.add_argument("--packet-digest", default="")
    inspect.add_argument("--physical-session-id")
    for operation in ("invoke", "resume", "send", "cancel", "wait"):
        command = sub.add_parser(operation, help=f"delegate {operation} to the injected adapter")
        command.add_argument("logical_agent_id")
        command.add_argument("--owner", required=True)
        command.add_argument("--packet-digest", default="")
        command.add_argument("--physical-session-id")
        command.add_argument("--request-ref", default=None)
    return parser


def main(argv: Optional[list[str]] = None, *, gateway: Optional[OttoGateway] = None) -> int:
    args = build_parser().parse_args(argv)
    gateway = gateway or OttoGateway(binding_available=False, authority_available=False)
    if args.command == "read":
        result: Any = gateway.read()
    elif args.command == "status":
        result = gateway.status()
    elif args.command == "dry-run":
        result = {"mode": "dry-run", "effects": "none", "route": "normal",
                  "requested_model": "gpt-5.6-luna", "requested_reasoning": "high",
                  "operations": ["invoke", "resume", "send", "inspect", "cancel", "wait"]}
    elif args.command == "inspect":
        result = gateway.inspect(Responsibility(args.owner, args.logical_agent_id, "inspect", args.packet_digest,
                                                physical_session_id=args.physical_session_id))
    else:
        responsibility = Responsibility(args.owner, args.logical_agent_id, args.command, args.packet_digest,
                                        physical_session_id=args.physical_session_id)
        result = gateway.operation(responsibility, args.request_ref)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
