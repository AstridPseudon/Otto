"""Portfolio commands executed by the single owner's authenticated lanes."""
from __future__ import annotations

import argparse
from typing import Any

from herzchen.contracts import ResourceRef

from . import config as host_config
from .owner import HostSession


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ottoctl portfolio")
    commands = result.add_subparsers(dest="operation", required=True)
    status = commands.add_parser("status", help="fast portfolio check-in")
    status.add_argument("--json", action="store_true", help="structured output (also the default)")
    documents = commands.add_parser("documents", help="read shared portfolio documents")
    documents.add_argument("--operation", dest="document_operation", choices=("list", "read"), default="list")
    documents.add_argument("--path")
    sync = commands.add_parser("sync-docs", help="sync UTF-8 portfolio files without overwriting Otto edits")
    sync.add_argument("--dir", required=True)
    apply = commands.add_parser("apply", help="register and reconcile a file-mode portfolio root")
    apply.add_argument("--root", required=True)
    apply.add_argument("--dry-run", action="store_true")
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
    for command in (status, documents, sync, apply, gate, prerequisite):
        command.add_argument("--portfolio", help="owner: select an admitted portfolio by id")
    return result


def prepare_portfolio_request(args: argparse.Namespace) -> None:
    if args.portfolio_args in (["--help"], ["-h"]):
        parser().parse_args(args.portfolio_args)
    if not args.portfolio_args or args.portfolio_args[0] not in {
            "status", "documents", "sync-docs", "apply", "gate", "prerequisite"}:
        return
    options = parser().parse_args(args.portfolio_args)
    args.portfolio = options.portfolio
    if options.operation == "sync-docs":
        from otto.portfolio.shared_documents import read_document_directory
        args.portfolio_bundle = read_document_directory(options.dir)
    elif options.operation == "apply":
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
        from otto.portfolio.shared_documents import portfolio_documents, sync_portfolio_documents
        if getattr(args, "owner_authorized", False) and options.operation in {"documents", "sync-docs"}:
            session.host = None
        if options.operation == "documents":
            return portfolio_documents(session, portfolio, operation=options.document_operation, path=options.path)
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
        bundle = getattr(args, "portfolio_bundle", None)
        if not isinstance(bundle, dict):
            raise ValueError("sync-docs requires UTF-8 files read and sent by the client")
        return sync_portfolio_documents(session, portfolio, bundle)
