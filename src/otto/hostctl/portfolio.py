"""Portfolio commands executed by the single owner's authenticated lanes."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from herzchen.contracts import ResourceRef

from . import config as host_config
from .owner import HostSession

# The ONE set of portfolio subcommands the owner lane runs for a request that names --portfolio.
# The client's forward (prepare_portfolio_request) and the owner's check (service.py) both read it;
# anything else (admit, complete-task, an unnamed subcommand) is refused with PermissionError.
OWNER_PORTFOLIO_COMMANDS = frozenset({
    "save",          # client: ottoctl portfolio --portfolio P save FILE (STAGE1 F7); otto --portfolio P save FILE
    "show",          # client: ottoctl portfolio --portfolio P show ... (STAGE1 F7); otto --portfolio P show ...
    "read",          # client: ottoctl portfolio --portfolio P read ... (STAGE1 F7); otto --portfolio P read ...
    "open",          # client: otto --portfolio P open ... (A3FIX thin client; the owner's editor host runs it)
    "release",       # client: otto --portfolio P release --session-id ... (A3FIX thin client; parked-session release)
    "status",        # operator: ottoctl portfolio status --portfolio P (parser() below); client: otto --portfolio P status
    "documents",     # operator: ottoctl portfolio documents --portfolio P (parser() below)
    "retire",        # operator: ottoctl portfolio retire PATH --portfolio P (parser() below)
    "apply",         # operator: ottoctl portfolio apply --root R --portfolio P (parser() below)
    "gate",          # operator: ottoctl portfolio gate complete --portfolio P (parser() below)
    "prerequisite",  # operator: ottoctl portfolio prerequisite complete --portfolio P (parser() below)
})
# The project operations the owner lane runs; each is reached only through its `--portfolio` flag.
OWNER_PROJECT_OPERATIONS = frozenset({
    ("project", "activate"),      # ottoctl project activate --portfolio P (cli.py:90)
    ("project", "depend"),        # ottoctl project depend --portfolio P (cli.py:100)
    ("project", "dependencies"),  # ottoctl project dependencies --portfolio P (cli.py:100)
    ("project", "detach"),        # ottoctl project detach --portfolio P (cli.py:100)
})


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ottoctl portfolio")
    commands = result.add_subparsers(dest="operation", required=True)
    status = commands.add_parser("status", help="fast portfolio check-in")
    status.add_argument("--json", action="store_true", help="structured output (also the default)")
    documents = commands.add_parser("documents", help="read shared portfolio documents")
    documents.add_argument("--operation", dest="document_operation", choices=("list", "read"), default="list")
    documents.add_argument("--path")
    documents.add_argument("--revision", help="read a specific retained DAT revision")
    documents.add_argument("--root", help="select a registered file-mode root")
    documents.add_argument("--root-namespace", help="select an explicit registered root namespace")
    retire = commands.add_parser("retire", help="retire one shared path while preserving its DAT history")
    retire.add_argument("path")
    retire.add_argument("--root", help="select a registered file-mode root")
    retire.add_argument("--root-namespace", help="select an explicit registered root namespace")
    apply = commands.add_parser("apply", help="register and reconcile a file-mode portfolio root")
    apply.add_argument("--root", required=True)
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--json", action="store_true", help="emit the structured result")
    apply.add_argument("--detail", action="store_true", help="include per-project and gate details")
    apply.add_argument("--import-history")
    gate = commands.add_parser("gate", help="record evidence for a declared milestone")
    gate_sub = gate.add_subparsers(dest="gate_operation", required=True)
    complete = gate_sub.add_parser("complete")
    complete.add_argument("--project", required=True)
    complete.add_argument("--gate", required=True)
    complete.add_argument("--evidence", required=True)
    complete.add_argument("--portfolio", help="owner: select an admitted portfolio by id")
    prerequisite = commands.add_parser("prerequisite", help="record an external prerequisite")
    prerequisite_sub = prerequisite.add_subparsers(dest="prerequisite_operation", required=True)
    prerequisite_complete = prerequisite_sub.add_parser("complete")
    prerequisite_complete.add_argument("--project", required=True)
    prerequisite_complete.add_argument("--id", required=True)
    prerequisite_complete.add_argument("--evidence", required=True)
    prerequisite_complete.add_argument("--portfolio", help="owner: select an admitted portfolio by id")
    for command in (status, documents, retire, apply, gate, prerequisite):
        command.add_argument("--portfolio", help="owner: select an admitted portfolio by id")
    return result


def save_parser() -> argparse.ArgumentParser:
    """Parse a save forwarded to the owner lane; the owner binds an omitted actor."""
    result = argparse.ArgumentParser(prog="ottoctl portfolio save")
    result.add_argument("--portfolio", help="owner: select an admitted portfolio by id")
    result.add_argument("command", choices=("save",))
    result.add_argument("file")
    result.add_argument("--actor")
    result.add_argument("--request-id", default=None)
    result.add_argument("--format", choices=("json", "text"), default="json")
    return result


def _split_portfolio(tokens: list) -> tuple:
    """(portfolio, rest): an optional `--portfolio P` (or `--portfolio=P`) in front of the command, and the command."""
    if tokens[:1] == ["--portfolio"] and len(tokens) >= 2:
        return tokens[1], tokens[2:]
    if tokens[:1] and tokens[0].startswith("--portfolio="):
        return tokens[0].split("=", 1)[1], tokens[1:]
    return None, tokens


def prepare_portfolio_request(args: argparse.Namespace) -> None:
    """Validate a `portfolio` request here and name the owner lane when it names --portfolio.

    The owner refuses every subcommand outside OWNER_PORTFOLIO_COMMANDS, so a refused command
    named with --portfolio reaches the owner and is refused there, with nothing written.
    """
    if args.portfolio_args in (["--help"], ["-h"]):
        parser().parse_args(args.portfolio_args)
    portfolio, words = _split_portfolio(args.portfolio_args)
    command = words[0] if words else None
    if command == "admit" and portfolio is not None:
        # Keep the existing owner-lane PermissionError for this forbidden
        # operator forwarding request after retiring its dead portfolio parser.
        args.portfolio, args.portfolio_args = portfolio, words
        return
    if command in {"show", "read"}:
        # Validated here like any command, then sent to the owner lane with the portfolio named once, as save is.
        from otto.portfolio.cli import build_parser as portfolio_cli_parser
        portfolio_cli_parser().parse_args(words)
        args.portfolio, args.portfolio_args = portfolio, words
        return
    if command == "save":
        # The owner reads the save file, so its path is made absolute here.
        options = save_parser().parse_args(args.portfolio_args)
        forwarded = ["save", str(Path(options.file).absolute()), "--format", options.format]
        if options.actor is not None:
            forwarded += ["--actor", options.actor]
        if options.request_id is not None:
            forwarded += ["--request-id", options.request_id]
        args.portfolio = options.portfolio
        args.portfolio_args = forwarded
        return
    if command not in OWNER_PORTFOLIO_COMMANDS - {"save", "show", "read"}:
        if words:
            # Validate every forwarded command here, so --help and usage errors are answered by
            # the client and never parsed inside the shared owner.
            from otto.portfolio.cli import build_parser as portfolio_cli_parser
            portfolio_cli_parser().parse_args(words)
            if portfolio is not None:
                args.portfolio, args.portfolio_args = portfolio, words
        return
    options = parser().parse_args(words)
    args.portfolio, args.portfolio_args = portfolio or options.portfolio, words
    if options.operation in {"documents", "retire"} and options.root:
        # The owner service may have a different working directory from this
        # client. Carry the same canonical root used by apply's file ingestion.
        args.portfolio_document_root = str(Path(options.root).resolve())
    if options.operation == "apply":
        from .portfolio_apply import read_portfolio_root
        args.portfolio_bundle = read_portfolio_root(options.root, history_directory=options.import_history)


def _scope(session: HostSession, args: argparse.Namespace) -> ResourceRef:
    ref = ResourceRef.from_dict(session.host["portfolio_ref"])
    requested = getattr(args, "portfolio", None)
    if requested and requested != ref.id:
        raise PermissionError("a host may access only its own portfolio; use the service home's owner lane")
    return ref


def dependency_service(session: HostSession, args: argparse.Namespace) -> Any:
    from otto.portfolio.dependencies import PortfolioDependencies
    actor = (session.owner.owner_actor if getattr(args, "owner_authorized", False)
             else session.binding.authenticated_actor(session.host_principal()))
    return PortfolioDependencies(session.owner.graph, session.store.consumer(), actor=actor,
        owner_actor=session.owner.owner_actor, portfolio_ref=_scope(session, args))


def project_command(args: argparse.Namespace, operation: str) -> dict:
    from .cli import _home, _host, _resolve_project
    config = host_config.load(_home(args))
    with HostSession(config, host=_host(args, config)) as session:
        project = _resolve_project(session, args.project)
        dependencies = dependency_service(session, args)
        dependencies.authorize(project.ref)
        if operation == "dependencies":
            return {"outcome": "read", **dependencies.readiness(project.ref), "provider_called": False}
        if operation == "depend":
            upstream, separator, gate = args.on.partition("#")
            if not upstream or separator and not gate:
                raise ValueError("--on names a project, optionally followed by #gate-id-or-alias")
            prerequisite = _resolve_project(session, upstream)
            target = dependencies.resolve_prerequisite(prerequisite.ref, gate if separator else None)
            key = "portfolio-dependency:" + project.ref.id + ":" + str(project.version) + ":" + target.id
            result = dependencies.change(project.ref, target, request_id=key + (":remove" if args.remove else ":link"),
                                         remove=args.remove)
            return {**result, "readiness": dependencies.readiness(project.ref), "provider_called": False}
        if operation == "detach":
            from .portfolio_detach import detach_project
            return detach_project(session, project, args)
        raise ValueError("unknown portfolio project operation")


def portfolio_command(args: argparse.Namespace) -> dict:
    from .cli import _home, _host
    options = parser().parse_args(args.portfolio_args)
    config = host_config.load(_home(args))
    with HostSession(config, host=_host(args, config)) as session:
        portfolio = _scope(session, options)
        if options.operation == "status":
            from otto.portfolio.status import portfolio_status
            return portfolio_status(session, portfolio, service_status=getattr(args, "service_status", None),
                                    owner_authorized=getattr(args, "owner_authorized", False))
        from otto.portfolio.shared_documents import (document_namespace, portfolio_documents,
                                                   retire_portfolio_document)
        if getattr(args, "owner_authorized", False) and options.operation in {"documents", "retire"}:
            session.host = None
        if options.operation in {"documents", "retire"}:
            root = (getattr(args, "portfolio_document_root", None) or str(Path(options.root).resolve())) if options.root else None
            namespace = document_namespace(root=root, root_namespace=options.root_namespace)
            if options.operation == "retire":
                return retire_portfolio_document(session, portfolio, options.path, root_namespace=namespace)
            return portfolio_documents(session, portfolio, operation=options.document_operation, path=options.path,
                                       root_namespace=namespace,
                                       revision=options.revision)
        if options.operation == "apply":
            from .portfolio_apply import apply_portfolio
            return apply_portfolio(session, portfolio, getattr(args, "portfolio_bundle", None),
                                   dry_run=options.dry_run, import_history=bool(options.import_history))
        if options.operation in {"gate", "prerequisite"}:
            from .portfolio_apply import complete_gate
            if options.operation == "gate":
                return complete_gate(session, portfolio, project=options.project, gate=options.gate,
                                     evidence=options.evidence)
            return complete_gate(session, portfolio, project=options.project, gate=options.id,
                                 evidence=options.evidence, external_prerequisite=options.id)
        raise ValueError("unknown portfolio operation")
