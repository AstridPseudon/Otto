"""Small help/diagnostic CLI for the public OTT-03 portfolio surface."""

from __future__ import annotations

import argparse
import json
from typing import Any, Optional

from .intake import OttoPortfolio, PortfolioError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m otto.portfolio.cli", description="canonical Otto pending-project intake")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("help", help="show the manager-facing intake contract")
    create = sub.add_parser("create-pending", help="create an inert pending project")
    create.add_argument("--actor", required=True)
    create.add_argument("--request-id", required=True)
    create.add_argument("--edit-json", default="{}")
    create.add_argument("--template", default=None)
    create.add_argument("--open", action="store_true", dest="open_project")
    read = sub.add_parser("read", help="read one durable project reference")
    read.add_argument("project_id")
    read.add_argument("--actor", required=True)
    listing = sub.add_parser("list", help="list pending projects")
    listing.add_argument("--actor", required=True)
    return parser


def main(argv: Optional[list[str]] = None, *, portfolio: Optional[OttoPortfolio] = None) -> int:
    args = build_parser().parse_args(argv)
    portfolio = portfolio or OttoPortfolio()
    if args.command == "help":
        result: Any = portfolio.help()
    elif args.command == "create-pending":
        try:
            edit = json.loads(args.edit_json)
            result = portfolio.create_pending(actor=args.actor, request_id=args.request_id, edit=edit,
                                              template=args.template, open_project=args.open_project)
        except (json.JSONDecodeError, PortfolioError) as exc:
            result = {"outcome": "error", "error": {"code": "invalid_request", "message": str(exc)}}
    elif args.command == "read":
        result = portfolio.read_pending(args.project_id, actor=args.actor)
    else:
        result = portfolio.list_pending(actor=args.actor)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
