"""ottoctl: the host-neutral Otto command.

ONE owner service holds the Store (``ottoctl service run``, the operator's
command). Every other command is a client request: ottoctl writes it into this
host's lane (its client home, ``OTTO_HOME``, default ~/.otto) and prints the
service's JSON response. A client never opens the Store and never reads
another host's folders; "is the owner busy?" is ``ottoctl service status``.

Local, no service: ``heavy [--purpose T] [--max-minutes N] [--no-wait] -- CMD`` runs CMD under
the machine's one heavy-job lease (renders, journeys, full test suites); ``heavy status``.

Operator commands (run against the service home): ``install`` (attach or
create the Store, before the service runs), ``service run``, ``service
admit-host`` (admits a host as its own principal) and ``service stop``.

Exit codes: 0 success, 1 error, 3 unavailable (no service, not admitted,
held). Reads never call a provider; writes are the supported owner
operations with stable request keys, so repeating a command replays it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Optional
from urllib.parse import quote

from . import config as host_config
from herzchen.contracts import ResourceRef

from .owner import HostSession, json_out

EXIT_OK, EXIT_ERROR, EXIT_UNAVAILABLE = 0, 1, 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ottoctl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", help="the Otto installation home (default: $OTTO_HOME or ~/.otto)")
    parser.add_argument("--host", choices=host_config.HOST_KINDS,
                        help="the admitted host this command acts for (default: $OTTO_HOST_KIND, or the only one)")
    parser.add_argument("--wait-seconds", type=float, default=900.0,
                        help="how long to wait for the owner service's response (the request stays retained)")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="record this machine's ONE Otto installation (its Store and owner)")
    install.add_argument("--store", required=True, help="the Store file (an existing owner's, or a new one with --create)")
    install.add_argument("--authority", required=True, help="the Store authority namespace")
    install.add_argument("--owner", required=True, help="the owner service principal that holds the Store")
    install.add_argument("--operator", required=True, help="the human operator principal, distinct from owner and hosts")
    install.add_argument("--credential-ref", required=True, help="the owner binding's credential label (no secret)")
    install.add_argument("--create", action="store_true", help="create a NEW Store (fresh machine or tests only)")
    host = sub.add_parser("host", help="inspect a joined host")
    host_sub = host.add_subparsers(dest="host_command", required=True)
    host_sub.add_parser("show", help="installation, Store custody, host principal and launcher pin (no provider call)")
    qualify = host_sub.add_parser("qualify-launcher", help="record one more exact launcher version as qualified")
    qualify.add_argument("--version", required=True)
    qualify.add_argument("--evidence", required=True, help="what was checked (fixtures, --help flags, ...)")
    portfolio = sub.add_parser("portfolio", help="Otto's portfolio CLI (onboarding, reads, help) with this owner bound",
                               add_help=False)
    portfolio.add_argument("portfolio_args", nargs=argparse.REMAINDER)

    sub.add_parser("whoami", help="the root orchestrator identity this host's owner binds (owner context)")
    sub.add_parser("effective-context", help="the root's adopted direction and resources (owner context)")
    sub.add_parser("projects", help="list this host's projects and lifecycles")

    project = sub.add_parser("project", help="register and read projects")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    register = project_sub.add_parser("register", help="register a Megado run bundle as a PENDING project")
    register.add_argument("--bundle", required=True, help="the run directory (northstar.md, agent_goal.md, run.json, ...)")
    register.add_argument("--manager-principal", help="manager principal (default <run_id>-manager)")
    register.add_argument("--worktree", help="the manager's workspace root (default: the run's control_root parent)")
    register.add_argument("--request-key", help="stable registration key (default register:<run_id>:v1)")
    register.add_argument("--plan-only", action="store_true", help="print what would be written; write nothing")
    history = project_sub.add_parser("import-history", help="keep a CLOSED run as history: its whole run dir as "
                                     "documents, withdrawn (never executed in Otto)")
    history.add_argument("--bundle", required=True, help="the closed run's directory")
    history.add_argument("--note", required=True, help="how and why the run closed (kept with the record)")
    status = project_sub.add_parser("status", help="one project's records: tasks, documents, roles, pools, schedules")
    status.add_argument("--project", required=True, help="project id or run id")
    activate = project_sub.add_parser("activate", help="ACTIVATION step 1: materialize tasks, roles, pools and paused "
                                      "checks from Otto's documents and prepare the manager (nothing starts)")
    activate.add_argument("--project", required=True, help="project id or run id")
    activate.add_argument("--manager-principal", help="manager principal (default <run_id>-manager)")
    activate.add_argument("--worktree", help="the manager's workspace root (default: the run's control_root parent)")
    activate.add_argument("--override-readiness", action="store_true")
    activate.add_argument("--reason", help="record why the orchestrator overrides unmet dependencies")
    activate.add_argument("--portfolio", help="owner lane: portfolio id")
    depend = project_sub.add_parser("depend", help="depend on a project or its gate in this portfolio")
    depend.add_argument("--project", required=True)
    depend.add_argument("--on", required=True, help="project id or run id, optionally #gate-id-or-alias")
    depend.add_argument("--remove", action="store_true")
    dependencies = project_sub.add_parser("dependencies", help="dependency satisfaction and computed readiness")
    dependencies.add_argument("--project", required=True)
    detach = project_sub.add_parser("detach", help="remove supervision and shared document associations")
    detach.add_argument("--project", required=True)
    for command in (depend, dependencies, detach):
        command.add_argument("--portfolio", help="owner lane: portfolio id")
    release = project_sub.add_parser("release-checkout", help="release this host's exact project checkout, preserving files/history; no activation")
    release.add_argument("--project", required=True)
    release.add_argument("--session-id", required=True, help="exact session returned by onboarding/open")
    release.add_argument("--request-key", required=True, help="stable logical request key")

    setup = sub.add_parser("operating-setup", help="read a project's operating setup readiness (pure read)")
    setup.add_argument("--project", required=True)
    setup.add_argument("--operation", choices=("read", "preview", "apply"), default="read",
                       help="read is pure; preview writes nothing; apply (ACTIVATION step) prepares the fresh "
                            "manager occurrence and adopts the setup document; nothing is started")

    admission = sub.add_parser("admission", help="dry-run role admission (no Due, no launch, no provider)")
    admission_sub = admission.add_subparsers(dest="admission_command", required=True)
    dry = admission_sub.add_parser("dry-run", help="check that a role would be admitted, writing nothing")
    dry.add_argument("--project", required=True)
    dry.add_argument("--role", choices=("manager",), default="manager")

    schedules = sub.add_parser("schedules", help="a project's Due records (orchestrator checks)")
    schedules.add_argument("--project", required=True)

    service = sub.add_parser("service", help="the ONE owner service: run (operator), admit a host, status, stop")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    run = service_sub.add_parser("run", help="OPERATOR: hold the Store and serve every host (foreground; "
                                 "starts no Due, calls no provider)")
    run.add_argument("--project", help="require this activated project to be composed at start (it is refused otherwise)")
    run.add_argument("--max-active-manager-turns", type=int, default=None,
                     help="refuse to start if this exceeds the capacity pool's manager limit; the pool, not this "
                          "flag, sets the limit (the onboarding wrapper still takes 3)")
    run.add_argument("--hold-dispatch", action="store_true",
                     help="serve status and retained reads only: settle nothing, admit nothing, call no provider")
    drain = service_sub.add_parser("drain", help="OPERATOR: drain one project's attached manager lanes")
    drain.add_argument("--project", required=True, help="project id or run id")
    admit = service_sub.add_parser("admit-host", help="OPERATOR: admit an agent CLI host as its OWN orchestrator "
                                   "principal and create its lane in its client home")
    admit.add_argument("--host", dest="admit_host", required=True, choices=host_config.HOST_KINDS)
    admit.add_argument("--client-home", help="the host's own OTTO_HOME (default: the service home)")
    admit.add_argument("--principal", help="the host's orchestrator principal (default <host>-orchestrator)")
    admit.add_argument("--launcher", help="absolute agent CLI launcher (default: the resolved `claude` on PATH, pinned)")
    admit.add_argument("--qualify-version", action="append", default=[],
                       help="additional exact launcher --version string qualified for the parser schema")
    admit.add_argument("--conversation", help="the orchestrator's native session id (default: a receipt mailbox)")
    revision_admit = service_sub.add_parser("admit", help="OPERATOR: admit one reviewed task revision after the owner checks local presence")
    revision_admit.add_argument("--task-ref", required=True, help="canonical work.task ResourceRef as JSON")
    revision_admit.add_argument("--revision", required=True, help="exact reviewed task revision")
    revision_admit.add_argument("--review-ref", required=True, help="exact approving review ResourceRef as JSON")
    revision_admit.add_argument("--request-key", required=True, help="stable admission request key")
    service_sub.add_parser("status", help="is the owner busy? holder, generation, heartbeat, attached project, "
                           "manager turn and in-flight requests (reads the published status only)")
    stop = service_sub.add_parser("stop", help="OPERATOR: ask the service to drain and close (writes its stop marker)")
    stop.add_argument("--reason", help="optional reason for closing, published in the service status closure block")
    stop.add_argument("--expected-return", help="optional expected return time or condition, published in status")
    request_status = sub.add_parser("request-status", help="read the service's response to one retained lane request")
    request_status.add_argument("--request-id", required=True)
    manager = sub.add_parser("manager", help="the manager command port (the orchestrator's owner-custody commands are "
                             "relayed through its lane; a launched manager uses its own lanes)", add_help=False)
    manager.add_argument("manager_args", nargs=argparse.REMAINDER)

    help_ = sub.add_parser("help", help="the orchestrator's side of manager escalations (owner lane)")
    help_sub = help_.add_subparsers(dest="help_command", required=True)
    help_read = help_sub.add_parser("read", help="retained help/advice requests for a project (via its service)")
    help_read.add_argument("--project", required=True)
    help_read.add_argument("--delivery-id")
    help_respond = help_sub.add_parser("respond", help="answer one escalation as this host's orchestrator")
    help_respond.add_argument("--project", required=True)
    help_respond.add_argument("--issue-id", required=True)
    help_respond.add_argument("--request-key", required=True)
    help_respond.add_argument("--response", required=True)
    help_respond.add_argument("--proposed-solution", required=True)
    help_respond.add_argument("--next-action", required=True)
    help_respond.add_argument("--authority-source", default="host orchestrator (oracle) ruling")

    skills = sub.add_parser("skills", help="install and identify Otto/Megado skill editions")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    which = skills_sub.add_parser("which", help="resolve a skill link chain, edition and drift")
    which.add_argument("name_or_path", help="a skill name under ~/.claude/skills, or a path")
    install = skills_sub.add_parser("install", help="install a stamped skill edition and optionally link it")
    install_source = install.add_mutually_exclusive_group(required=True)
    install_source.add_argument("--source", help="generic skill source directory (contains SKILL.md)")
    install_source.add_argument("--source-root", help="Otto checkout root for self-contained export mode")
    install.add_argument("--otto-self-contained", action="store_true",
                         help="package Otto's maintained skill and local reference closure")
    install.add_argument("--name", help="required for generic --source installs; Otto mode uses 'otto'")
    install.add_argument("--edition", required=True)
    install.add_argument("--commit", help="source commit identity")
    install.add_argument("--link", action="append", default=[], help="symlink path to point at the edition")
    return parser


def _home(args: argparse.Namespace) -> Path:
    return host_config.otto_home(args.home)


def _default_launcher() -> Optional[str]:
    import shutil
    found = shutil.which("claude")
    return os.path.abspath(found) if found else None


def _host(args: argparse.Namespace, config: Mapping[str, Any]) -> Mapping[str, Any]:
    return host_config.host(config, getattr(args, "host", None))


def _host_opt(args: argparse.Namespace, config: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    try:
        return _host(args, config)
    except host_config.HostConfigError:
        return None


def cmd_install(args: argparse.Namespace) -> Any:
    from .owner import attach_store, create_store
    home = _home(args)
    if host_config.config_path(home).exists():
        raise host_config.HostConfigError("Otto is already installed at " + str(home))
    config = host_config.new_installation(home, store_path=args.store, authority=args.authority,
        owner_actor=args.owner, credential_ref=args.credential_ref, python=str(Path(sys.executable).absolute()),
        operator_actor=args.operator)
    config = create_store(config) if args.create else attach_store(config)
    host_config.write(home, config)
    _receipt(home, "install", {"installation": config})
    return {"outcome": "created" if args.create else "attached", "home": str(home), "store": config["store"],
            "owner": config["owner"], "provider_called": False}


def cmd_host_show(args: argparse.Namespace) -> Any:
    from .adapters import launcher_check
    home = _home(args)
    config = host_config.load(home)
    entry = _host(args, config)
    checks = {}
    with HostSession(config, host=entry) as session:
        checks["store"] = {"ok": True, "domain_descriptor_digest": session.store.domain_descriptor_digest,
                           "writer_lock": "held for this command"}
        root = session.root_assignment()
        checks["host_root"] = {"assignment_ref": root.ref.to_dict(), "role": root.role, "principal": root.principal,
                               "scope_ref": root.scope.to_dict(), "generation": root.generation}
    if "claude-code" in entry.get("adapters", {}):
        checks["claude_launcher"] = launcher_check({"home": config["home"], "adapters": entry["adapters"]})
    import otto
    return {"outcome": "read", "home": str(home), "store": config["store"], "owner": config["owner"],
            "host": entry, "joined_hosts": sorted(config.get("hosts", {})),
            "package": {"otto": os.path.dirname(otto.__file__), "python": sys.executable},
            "checks": checks, "provider_called": False}


def cmd_host_qualify(args: argparse.Namespace) -> Any:
    from otto.agents.claude_cli import qualified_versions
    home = _home(args)
    config = host_config.load(home)
    entry = config["hosts"][_host(args, config)["kind"]]
    settings = entry.get("adapters", {}).get("claude-code")
    if settings is None:
        raise host_config.HostConfigError("this host declares no claude-code adapter")
    values = list(settings.get("qualified_versions") or [])
    if args.version not in values:
        values.append(args.version)
    qualified_versions(values)  # exact-format check before writing
    settings["qualified_versions"] = values
    settings.setdefault("qualification_evidence", []).append({"version": args.version, "evidence": args.evidence})
    host_config.write(home, config, replace=True)
    _receipt(home, "qualify-launcher", {"version": args.version, "evidence": args.evidence})
    return {"outcome": "recorded", "qualified_versions": values, "provider_called": False}


def _whoami(args: argparse.Namespace, operation: str) -> Any:
    """This host's own principal and its responsibility, read through the owner.

    A process the owner launched (a manager or worker) reads its identity from
    the caller socket (`ottoctl manager whoami`); this read is for the host's
    user-started orchestrator session, whose principal the installation names.
    """
    config = host_config.load(_home(args))
    entry = _host(args, config)
    with HostSession(config, host=entry) as session:
        root = session.root_assignment()
        common = {"schema": "otto.host-principal-context.v1", "identity_origin": "joined host registry, owner read",
                  "native_process_identity_claimed": False, "provider_called": False, "host": entry["kind"],
                  "principal": root.principal, "role": root.role, "assignment_ref": root.ref.to_dict(),
                  "generation": root.generation, "scope_ref": root.scope.to_dict(),
                  "owner": config["owner"]["actor"]}
        if operation == "whoami":
            return {**common, "outcome": "read", "read_only": True}
        surface = session.owner.direction_surface()
        subject = ResourceRef.from_dict(root.payload["responsibility_ref"])
        projects = [record.ref.to_dict() for record in _project_records(session)
                    if any(a.get("principal") == root.principal for a in _assignments(session, record))]
        return {**common, "outcome": "read", "read_only": True,
                "assignment_direction": surface.read(subject, assignment_ref=root.ref, generation=root.generation),
                "orchestrated_projects": projects}


def _assignments(session: HostSession, record: Any) -> list:
    view = session.owner.sheet.export(record.ref)
    observed = view.project.get("observed", {}) if hasattr(view, "project") else {}
    rows = []
    for item in observed.get("assignments") or ():
        ref = ResourceRef.from_dict(item["ref"])
        current = session.owner.assignments.get(ResourceRef(ref.authority, ref.kind, ref.id))
        rows.append({"role": current.role, "principal": current.principal,
                     "status": getattr(current.status, "value", current.status), "generation": current.generation,
                     "session": current.session, "ref": current.ref.to_dict()})
    return rows


def cmd_portfolio(args: argparse.Namespace) -> Any:
    """Otto's portfolio CLI with this owner's ports injected (one entry, no second CLI)."""
    from .portfolio import portfolio_command
    if getattr(args, "caller", None) == "otto":
        # The otto thin client: this owner runs the verb with its own portfolio, editor host and status session.
        from otto.portfolio.cli import owner_verb
        config = host_config.load(_home(args))
        entry = host_config.host(config, getattr(args, "host", None)) if config.get("hosts") else None
        project_ids = tuple(_flag_values(args.portfolio_args, "--project-ref"))
        with HostSession(config, host=entry, project_ids=project_ids) as session:
            return owner_verb(list(args.portfolio_args), session=session, home=_home(args))
    if args.portfolio_args and args.portfolio_args[0] in {
            "status", "documents", "retire", "apply", "gate", "prerequisite"}:
        return portfolio_command(args)
    import contextlib, io
    from otto.portfolio import cli as portfolio_cli
    from otto.portfolio.document_navigation import ProjectDocumentOperations
    config = host_config.load(_home(args))
    entry = host_config.host(config, getattr(args, "host", None)) if config.get("hosts") else None
    project_ids = tuple(_flag_values(args.portfolio_args, "--project-ref"))
    with HostSession(config, host=entry, project_ids=project_ids) as session:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = portfolio_cli.main(list(args.portfolio_args), portfolio=session.portfolio,
                                          bound_actor=(session.owner.owner_actor.actor if getattr(args, "owner_authorized", False)
                                                       else session.host_principal()))
        except SystemExit as exc:  # argparse usage or --help: an error reply, never an owner exit
            return {"outcome": "error", "error": {"code": "usage", "exit_code": exc.code,
                    "message": (out.getvalue() + err.getvalue()).strip()}, "provider_called": False}
        text = out.getvalue()
    try:
        value = json.loads(text)
    except ValueError:
        value = {"outcome": "read" if code == 0 else "error", "text": text}
    return value


def _flag_values(argv: list, flag: str) -> list:
    values = []
    for index, item in enumerate(argv):
        if item == flag and index + 1 < len(argv):
            try:
                values.append(json.loads(argv[index + 1])["id"])
            except (ValueError, KeyError, TypeError):
                pass
    return values


def _project_records(session: HostSession) -> list:
    records = session.owner.graph.list(kind="work.project")
    if session.host is None:
        return list(records)
    # The server derives the host identity from its private installed lane.
    root = session.root_assignment()
    portfolio = root.scope
    return [record for record in records if (
        ((record.payload.get('metadata') or {}).get('otto_orchestrator') or {}).get('portfolio_ref', {}).get('id') == portfolio.id
        and ((record.payload.get('metadata') or {}).get('otto_orchestrator') or {}).get('assignment_ref', {}).get('id') == root.ref.id)]


def _resolve_project(session: HostSession, value: str) -> Any:
    for record in _project_records(session):
        custom = ((record.payload.get("custom") or {}).get("otto_host_registration") or {})
        if value in {record.ref.id, custom.get("run_id")}:
            return record
    raise LookupError("no project " + value + " on this host (see ottoctl projects)")


def cmd_projects(args: argparse.Namespace) -> Any:
    config = host_config.load(_home(args))
    with HostSession(config, host=_host_opt(args, config)) as session:
        rows = []
        for record in _project_records(session):
            custom = ((record.payload.get("custom") or {}).get("otto_host_registration") or {})
            orchestrators = sorted({a["principal"] for a in _assignments(session, record) if a["role"] == "orchestrator"})
            rows.append({"project_ref": record.ref.to_dict(), "title": record.title,
                         "lifecycle": record.lifecycle.value, "run_id": custom.get("run_id"),
                         "mode": custom.get("mode"), "tasks": len(record.payload.get("tasks") or ()),
                         "orchestrators": orchestrators})
        return {"outcome": "read", "projects": rows, "provider_called": False}


def cmd_register(args: argparse.Namespace) -> Any:
    from otto.agents.host_profiles import profile as model_profile
    from .register import plan, register
    home = _home(args)
    config = host_config.load(home)
    bundle = _client_bundle(args)
    run = bundle["run"]
    run_id = run.get("run_id") or Path(bundle["root"]).name
    worktree = args.worktree or str(Path(run.get("control_root") or bundle["root"]).parents[2])
    entry = _host(args, config)
    computed = plan(bundle, profile=model_profile(entry["model_profile"]),
                    manager_principal=args.manager_principal or run_id + "-manager", worktree=worktree,
                    tool_entrypoint=str(home / "bin" / "ottoctl"))
    if args.plan_only:
        shown = dict(computed)
        shown["files"] = {name: len(text) for name, text in computed["files"].items()}
        return {"outcome": "plan", "plan": shown, "writes": False, "provider_called": False}
    with HostSession(config, host=entry) as session:
        receipt = register(session, computed, key=args.request_key)
    _receipt(home, "register-" + run_id, receipt)
    return {"outcome": "registered", **receipt,
            "next_action": "review the stored project documents; then "
                           "`ottoctl project activate --project " + run_id + "`"}


def cmd_import_history(args: argparse.Namespace) -> Any:
    from otto.agents.host_profiles import profile as model_profile
    from .register import import_history, plan
    home = _home(args)
    config = host_config.load(home)
    bundle = _client_bundle(args)
    run_id = bundle["run"].get("run_id") or Path(bundle["root"]).name
    prior_path = receipt_path(home, "history-" + run_id)
    try:
        prior = json.loads(prior_path.read_text())
    except (OSError, ValueError):
        prior = None
    if isinstance(prior, Mapping) and prior.get("outcome") == "imported_history" and prior.get("run_id") == run_id:
        return prior
    entry = _host(args, config)
    computed = plan(bundle, profile=model_profile(entry["model_profile"]), manager_principal=run_id + "-manager",
                    worktree=str(Path(bundle["root"]).parent), tool_entrypoint=str(home / "bin" / "ottoctl"))
    with HostSession(config, host=entry) as session:
        receipt = import_history(session, computed, note=args.note)
    _receipt(home, "history-" + run_id, receipt)
    return receipt


def _client_bundle(args: argparse.Namespace) -> dict:
    """The run files the CLIENT read and sent; the service never reads a host's run dir."""
    from .bundle import parse_files
    files = getattr(args, "bundle_files", None)
    if not isinstance(files, Mapping):
        raise ValueError("the request carries no run files; send it with `ottoctl project ... --bundle <run dir>`")
    parsed = parse_files(dict(files), raw_sha256=dict(getattr(args, "bundle_raw_sha256", None) or {}))
    parsed["root"] = args.bundle_root
    return parsed


def cmd_activate(args: argparse.Namespace) -> Any:
    """Materialize from Otto's stored documents, then adopt the operating setup (prepared, not started)."""
    from otto.agents.host_profiles import profile as model_profile
    from .register import materialize, plan, stored_bundle
    home = _home(args)
    config = host_config.load(home)
    entry = _host(args, config)
    with HostSession(config, host=entry) as session:
        record = _resolve_project(session, args.project)
    with HostSession(config, host=entry, project_ids=(record.ref.id,)) as session:
        record = session.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind, record.ref.id))
        from .portfolio import dependency_service
        readiness = dependency_service(session, args).activation_check(
            record.ref, override=getattr(args, "override_readiness", False),
            reason=getattr(args, "reason", None),
            request_id="activate-readiness:" + record.ref.id + ":" + str(record.version))
        if readiness.get("outcome") in {"blocked", "error"}:
            return readiness
        record = session.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind, record.ref.id))
        registration = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
        bundle = stored_bundle(session, record)
        run_id = registration.get("run_id") or record.ref.id
        worktree = args.worktree or str(Path(bundle["run"].get("control_root") or home).resolve().parents[2])
        computed = plan(bundle, profile=model_profile(entry["model_profile"]),
                        manager_principal=args.manager_principal or run_id + "-manager", worktree=worktree,
                        tool_entrypoint=str(home / "bin" / "ottoctl"))
        available = set((entry.get("adapters") or {}).keys())
        # Activation prepares only the manager. Optional worker/reviewer/
        # advisor slots retain their declarations and are fenced at their own
        # actual admission, rather than blocking unrelated manager preparation.
        unsupported = sorted({computed["manager"]["binding"].get("adapter")} - available)
        if unsupported:
            return {"outcome": "error", "error": {"code": "role_adapter_unavailable",
                    "message": "activation manager requires trusted adapter factory for: " + ", ".join(unsupported),
                    "adapters": unsupported}, "dispatch": False, "provider_called": False,
                    "readiness": readiness}
        receipt = materialize(session, record, computed)
    _receipt(home, "activate-" + run_id, receipt)
    args.operation = "apply"
    setup = _compose_setup(args)
    return {"outcome": "prepared", "activation": receipt, "readiness": readiness,
            "operating_setup": setup, "started": False,
            "next_action": "`ottoctl manager --project " + run_id + " start-manager "
                           "--schedule-id <operating_setup.setup.roles.manager>`"}


def cmd_release_checkout(args: argparse.Namespace) -> Any:
    """Own-host finite EDT release; no native-manager identity or takeover."""
    config = host_config.load(_home(args))
    host = _host_opt(args, config)
    if host is None:
        raise PermissionError("checkout release requires an admitted host")
    with HostSession(config, host=host) as session:
        record = _resolve_project(session, args.project)
    with HostSession(config, host=host, project_ids=(record.ref.id,)) as session:
        result = session.portfolio.release_project(record.ref.to_dict(),
            session_id=args.session_id, actor=session.host_principal(), request_id=args.request_key)
    return {**result, "provider_called": False}


def cmd_project_status(args: argparse.Namespace) -> Any:
    from herzchen.contracts import ResourceRef
    from herzchen.kernel import LimitService
    config = host_config.load(_home(args))
    with HostSession(config, host=_host_opt(args, config)) as session:
        record = _resolve_project(session, args.project)
    with HostSession(config, host=_host_opt(args, config), project_ids=(record.ref.id,)) as session:
        record = session.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind, record.ref.id))
        tasks = []
        for raw in record.payload.get("tasks") or ():
            ref = ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
            task = session.owner.graph.current(ResourceRef(ref.authority, ref.kind, ref.id))
            megado = (task.payload.get("custom") or {}).get("megado") or {}
            tasks.append({"id": task.payload.get("alias") or task.ref.id, "title": task.title,
                          "lifecycle": task.lifecycle.value, "route": megado.get("route"),
                          "phase": megado.get("phase"), "depends_on": len(task.payload.get("dependencies") or ())})
        view = session.owner.sheet.export(record.ref)
        observed = view.project.get("observed", {}) if hasattr(view, "project") else {}
        assignments = []
        for item in observed.get("assignments") or ():
            ref = ResourceRef.from_dict(item["ref"])
            current = session.owner.assignments.get(ResourceRef(ref.authority, ref.kind, ref.id))
            assignments.append({"role": current.role, "principal": current.principal,
                                "status": getattr(current.status, "value", current.status),
                                "generation": current.generation, "session": current.session,
                                "ref": current.ref.to_dict()})
        from herzchen.content.packets import ContextPacketService
        from herzchen.content import domain_contribution as content_contribution
        from otto.portfolio.documents import ProjectDocumentReader
        reader = ProjectDocumentReader(sheet_reader=session.owner.sheet, content_reader=session.owner.content,
            visibility_reader=ContextPacketService(session.store.domain_handler((content_contribution(),))))
        custom = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
        documents = []
        for row in reader.list_documents(record.ref.to_dict(), actor=_reader_actor(session))["documents"]:
            path = next((m.get("key") for m in row.get("memberships") or () if m.get("namespace") == "project.files"), None)
            stored = session.owner.content.read(ResourceRef.from_dict(row["current_revision_ref"]))["content"]
            digest = hashlib.sha256(stored.encode()).hexdigest() if isinstance(stored, str) else None
            documents.append({"path": path, "role": row["document"].get("role"),
                              "revision_ref": row["current_revision_ref"], "stored_text_sha256": digest})
        limits = LimitService(session.store)
        pools = []
        for pool_id in _pool_ids(session, record):
            pool = limits.get_pool(ResourceRef(record.ref.authority, "limit", pool_id))
            if pool is not None:
                pools.append({"pool": pool_id, "capacity_units": pool.capacity_units,
                              "cumulative_allowance_units": pool.cumulative_allowance_units,
                              "used": pool.cumulative_used_units, "held": pool.held_units,
                              "remaining": pool.remaining_allowance_units})
        dues = [{"schedule_id": due["schedule_id"], "role": due.get("role"), "purpose": due.get("purpose"),
                 "interval_seconds": due.get("interval_seconds"), "host_state": due.get("host_state"),
                 "stop_state": due.get("stop_state"), "execution_mode": due.get("execution_mode")}
                for due in session.due_port.list_due({"project_ref": record.ref.id})]
        return {"outcome": "read", "project_ref": record.ref.to_dict(), "title": record.title,
                "lifecycle": record.lifecycle.value, "registration": custom, "tasks": tasks,
                "assignments": assignments, "documents": documents, "allowances": pools, "schedules": dues,
                "provider_called": False}


def _reader_actor(session: HostSession) -> Any:
    """Documents are private to their authoring principal: read as the host when one is selected."""
    return session.binding.authenticated_actor(session.host["principal"]) if session.host else session.owner.owner_actor


def _pool_ids(session: HostSession, record: Any) -> list:
    """Pools registered for this project (receipt-recorded ids, owner-verified)."""
    home = Path(session.config["home"])
    custom = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
    receipt = receipt_path(home, "activate-" + str(custom.get("run_id")))
    try:
        steps = json.loads(receipt.read_text())["steps"]["allowances"]
    except (OSError, KeyError, ValueError):
        return []
    return [item["pool_ref"]["id"] for item in steps]


def _manager_handles(session: HostSession, record: Any) -> Mapping[str, Any]:
    home = Path(session.config["home"])
    custom = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
    path = receipt_path(home, "activate-" + str(custom.get("run_id")))
    if not path.exists():
        raise LookupError("project is a draft: roles exist only after `ottoctl project activate`")
    return json.loads(path.read_text())["steps"]["manager"]


def _manager_adapter(session: HostSession, config: Mapping[str, Any], manager: Mapping[str, Any]) -> Any:
    """The declared Claude composition for this project's manager (pins only, no launch)."""
    from herzchen.contracts import ResourceRef
    from .adapters import compose_claude
    mandate = session.owner.content.read(ResourceRef.from_dict(manager["mandate_ref"]))["content"]
    worktree = mandate["instruction_contract"]["authority"]["workspace_roots"][0]
    binding = manager["binding"]
    return compose_claude(config, worktree=worktree, model=binding["model"], reasoning=binding["reasoning"])


def _manager_setup(manager: Mapping[str, Any]) -> dict:
    from otto.portfolio.operating_composition import SCHEMA
    return {"schema": SCHEMA, "mode": "manual",
            "roles": {"manager": {"assignment_ref": manager["assignment_ref"], "generation": manager["generation"],
                                  "task_ref": manager["task_ref"], "mandate_ref": manager["mandate_ref"],
                                  "fresh_manager": True}},
            "advisor_policy": {"mode": "disabled", "reason": "The orchestrator's scheduled checks supervise"},
            "acceptance_tasks": []}


def cmd_operating_setup(args: argparse.Namespace) -> Any:
    from herzchen.contracts import ResourceRef
    if args.operation != "read":
        return _compose_setup(args)
    config = host_config.load(_home(args))
    with HostSession(config, host=_host_opt(args, config)) as session:
        record = _resolve_project(session, args.project)
    from otto.agents.claude_adapter import IDENTITY
    from .adapters import UnavailableAdapter
    with HostSession(config, host=_host_opt(args, config), project_ids=(record.ref.id,)) as session:
        composition = {"ok": True}
        try:
            adapter = _manager_adapter(session, config, _manager_handles(session, record))
        except Exception as exc:
            composition = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
            adapter = UnavailableAdapter(IDENTITY, composition["error"])
        app = session.execution_application(adapter, manager_actor=_manager_handles(session, record)["principal"])
        project = session.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind, record.ref.id))
        return {**app.read_operating_setup(project_ref=project.ref.to_dict()), "adapter_composition": composition,
                "provider_called": False}


def _compose_setup(args: argparse.Namespace) -> Any:
    from herzchen.contracts import ResourceRef
    config = host_config.load(_home(args))
    with HostSession(config, host=_host_opt(args, config)) as session:
        record = _resolve_project(session, args.project)
    with HostSession(config, host=_host_opt(args, config), project_ids=(record.ref.id,)) as session:
        manager = _manager_handles(session, record)
        app = session.execution_application(_manager_adapter(session, config, manager), manager_actor=manager["principal"])
        project = session.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind, record.ref.id))
        result = app.compose_operating_setup(project_ref=project.ref.to_dict(), operation=args.operation,
                                             setup=_manager_setup(manager),
                                             request_key="operating-setup:" + record.ref.id + ":v1")
        result = dict(result)
        result.setdefault("provider_called", False)
        result["started"] = False
        return result


def cmd_admission_dry_run(args: argparse.Namespace) -> Any:
    """Would the owner admit this project's manager now? Writes nothing."""
    from herzchen.contracts import ResourceRef
    from .adapters import adapter_selection, launcher_check
    config = host_config.load(_home(args))
    with HostSession(config, host=_host_opt(args, config)) as session:
        record = _resolve_project(session, args.project)
    checks: dict[str, Any] = {}
    with HostSession(config, host=_host_opt(args, config), project_ids=(record.ref.id,)) as session:
        manager = _manager_handles(session, record)
        binding = manager["binding"]
        project = session.owner.graph.current(ResourceRef(record.ref.authority, record.ref.kind, record.ref.id))
        checks["project"] = {"lifecycle": project.lifecycle.value, "ok": True,
                             "note": "pending by design; activation is a separate orchestrator step"}
        checks["selection"] = _check(lambda: adapter_selection(config).resolve(
            role={"adapter": binding["adapter"], "model": binding["model"], "reasoning": binding["reasoning"]}))
        checks["launcher"] = launcher_check(config)
        counts = session.store.consumer().snapshot_counts()
        try:
            adapter = _manager_adapter(session, config, manager)
            checks["composition"] = _check(lambda: (adapter.validate_owner_host_composition(
                role="manager", profile="workspace-write"), {"tools": adapter.pins()["tools"],
                "scope": adapter.manager_transport.scope.pin})[1])
            app = session.execution_application(adapter, manager_actor=manager["principal"])
            current = app.read_operating_setup(project_ref=project.ref.to_dict())
            if current.get("setup_ref"):
                # Activated (setup adopted, not started): read its readiness.
                readiness = current
            else:
                preview = app.compose_operating_setup(project_ref=project.ref.to_dict(), operation="preview",
                                                      setup=_manager_setup(manager), request_key="admission-dry-run")
                readiness = preview.get("readiness", {})
            role = (readiness.get("roles") or {}).get("manager") or {}
            checks["owner_admission"] = {"ok": bool(readiness.get("ready")), "state": readiness.get("state"),
                "blockers": readiness.get("blockers"), "execution": role.get("execution"),
                "conversation_binding_source": role.get("conversation_binding_source"),
                "role_introduction": (readiness.get("introductions") or {}).get("manager")}
        except Exception as exc:  # report, do not hide
            checks["owner_admission"] = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
        after = session.store.consumer().snapshot_counts()
        checks["inert"] = {"ok": after == counts, "store_counts_unchanged": after == counts}
    ok = all(item.get("ok") for item in checks.values() if isinstance(item, Mapping))
    return {"outcome": "would_admit" if ok else "blocked", "role": "manager", "principal": manager["principal"],
            "model": binding["model"], "reasoning": binding["reasoning"], "adapter": binding["adapter"],
            "checks": checks, "provider_called": False, "dispatch": False, "due_written": False}


def _check(callable_: Any) -> dict[str, Any]:
    try:
        return {"ok": True, "value": callable_()}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}


def cmd_schedules(args: argparse.Namespace) -> Any:
    config = host_config.load(_home(args))
    with HostSession(config, host=_host_opt(args, config)) as session:
        record = _resolve_project(session, args.project)
        return {"outcome": "read", "project_ref": record.ref.to_dict(),
                "schedules": list(session.due_port.list_due({"project_ref": record.ref.id})),
                "provider_called": False}


def cmd_skills_which(args: argparse.Namespace) -> Any:
    from .skills import which_skill
    target = args.name_or_path
    path = Path(target) if os.sep in target else Path.home() / ".claude" / "skills" / target
    return {"outcome": "read", **which_skill(str(path))}


def cmd_skills_install(args: argparse.Namespace) -> Any:
    from .skills import install_otto_skill_tree, install_skill_tree, link_skill
    home = _home(args)
    if args.otto_self_contained:
        if not args.source_root or args.source or args.name:
            raise ValueError("--otto-self-contained requires --source-root and does not accept --source or --name")
        name = "otto"
        manifest = install_otto_skill_tree(args.source_root, str(home / "skills"), edition=args.edition,
                                           source_commit=args.commit)
    else:
        if not args.source or args.source_root or not args.name:
            raise ValueError("generic skills install requires --source and --name")
        name = args.name
        manifest = install_skill_tree(args.source, str(home / "skills"), name=name, edition=args.edition,
                                      source_commit=args.commit)
    links = [link_skill(link, manifest["path"]) for link in args.link]
    _receipt(home, "skills-" + name + "-" + args.edition, {"manifest": manifest, "links": links})
    return {"outcome": "installed", "manifest": manifest, "links": links}


def cmd_service_run(args: argparse.Namespace) -> Any:
    """OPERATOR: hold the Store and serve every admitted host until stopped."""
    from .supervision import PRODUCT_COMPOSITION
    config = host_config.load(_home(args))
    selected = config.get('owner_composition')
    if selected and selected.get('kind') != PRODUCT_COMPOSITION:
        # The onboarding wrapper's installation; it retires at CUTOVER.
        from .supervision import run_installed_supervisor
        return run_installed_supervisor(config, requested_limit=args.max_active_manager_turns or 3)
    # The product start: the same owner the live start composes, so staging proves it.
    from .product_service import run_product_service
    return run_product_service(config, emit=lambda value: print(json_out(value), flush=True),
                               project=args.project, hold_dispatch=args.hold_dispatch,
                               requested_manager_limit=args.max_active_manager_turns)


def cmd_service_drain(args: argparse.Namespace) -> Any:
    from .service import owner_lane
    home = _home(args)
    host_config.load(home)
    return _await(owner_lane(home), {"command": "drain", "args": {"project": args.project}}, args.wait_seconds)


def cmd_service_admit(args: argparse.Namespace) -> Any:
    """OPERATOR: admit a host through the running service's owner lane."""
    from . import lanes
    from .service import owner_lane
    home = _home(args)
    host_config.load(home)  # only the service home's operator admits hosts
    launcher = args.launcher or (_default_launcher() if args.admit_host == "claude-code" else None)
    request = {"command": "admit-host", "args": {
        "host": args.admit_host, "client_home": str(Path(args.client_home).expanduser().absolute()) if args.client_home else None,
        "principal": args.principal, "launcher": launcher, "qualify_versions": list(args.qualify_version),
        "conversation": args.conversation}}
    return _await(owner_lane(home), request, args.wait_seconds)


def cmd_service_admit_revision(args: argparse.Namespace) -> Any:
    """Forward only revision selectors; the owner chooses the actor and proves presence."""
    from .service import owner_lane
    home = _home(args)
    host_config.load(home)
    request = {"command": "admit", "args": {
        "task_ref": json.loads(args.task_ref), "revision": args.revision,
        "review_ref": json.loads(args.review_ref), "request_key": args.request_key}}
    return _await(owner_lane(home), request, args.wait_seconds)


def cmd_service_status(args: argparse.Namespace) -> Any:
    """Is the owner busy? Read the status the service publishes (no Store access)."""
    from .service import read_status, status_path, with_lane_advice
    home = _home(args)
    if host_config.client_path(home).exists():
        entry = host_config.client_host(host_config.load_client(home), getattr(args, "host", None))
        status = with_lane_advice(read_status(Path(entry["status"])), lane="client",
                                  owner_actor=entry.get("owner_actor"))
        return {**status, "as_host": entry["kind"], "principal": entry["principal"]}
    host_config.load(home)
    return with_lane_advice(read_status(status_path(home)), lane="owner", service_home=home)


def cmd_service_stop(args: argparse.Namespace) -> Any:
    from .service import stop_marker
    home = _home(args)
    host_config.load(home)
    path = stop_marker(home)
    closure = {key: value.strip() for key, value in (("reason", getattr(args, "reason", None)),
                                                       ("expected_return", getattr(args, "expected_return", None)))
               if isinstance(value, str) and value.strip()}
    from datetime import datetime, timezone
    path.write_text(json.dumps({"requested_at": datetime.now(timezone.utc).isoformat(), **closure}, sort_keys=True) + "\n")
    os.chmod(path, 0o600)
    result = {"outcome": "stop_requested", "stop_marker": str(path),
              "next_action": "the service drains admitted work and closes; check `ottoctl service status`"}
    if closure:
        result["closure"] = closure
    return result


def cmd_request_status(args: argparse.Namespace) -> Any:
    from . import lanes
    entry = _client_entry(args)
    if not lanes.valid_token(args.request_id):
        raise ValueError("request ids are 32 lowercase hexadecimal characters")
    return lanes.wait(Path(entry["lane"]), args.request_id, timeout_seconds=0)


def _client_entry(args: argparse.Namespace) -> Mapping[str, Any]:
    home = _home(args)
    return host_config.client_host(host_config.load_client(home), getattr(args, "host", None))


def _await(lane: Path, request: Mapping[str, Any], wait_seconds: float,
           owner_actor: Optional[str] = None) -> Any:
    from . import lanes
    from .service import read_status, with_lane_advice
    status = read_status(lane / lanes.STATUS_FILE) if lane.name != "owner-lane" else read_status(
        lane.parent / "run" / "service.json")
    if status["outcome"] != "running":
        lane_kind = "owner" if lane.name == "owner-lane" else "client"
        advice = with_lane_advice(status, lane=lane_kind,
                                  owner_actor=owner_actor or (status.get("holder") or {}).get("owner_actor"),
                                  service_home=lane.parent if lane_kind == "owner" else None)
        return {"outcome": "unavailable", "provider_called": False,
                "error": {"code": "owner_service_not_running", "message": "no running owner service answers this lane "
                          "(status: " + status["outcome"] + "; " + advice.get("reason", status["outcome"]) + ")"},
                "service_status": {k: status.get(k) for k in
                                   ("outcome", "generation", "heartbeat_at", "holder", "closure", "reason")},
                "next_action": advice.get("next_action", "check `ottoctl service status`")}
    token = lanes.submit(lane, request)
    return lanes.wait(lane, token, timeout_seconds=wait_seconds)


def _lane_args(args: argparse.Namespace) -> dict:
    skip = {"command", "home", "host", "wait_seconds", "project_command", "admission_command", "host_command",
            "help_command", "service_command", "skills_command", "manager_args", "portfolio_args", "bundle"}
    return {key: value for key, value in vars(args).items() if key not in skip}


def _read_client_bundle(path: str) -> dict:
    from .bundle import read_bundle
    bundle = read_bundle(path)
    return {"bundle_files": bundle["files"], "bundle_raw_sha256": bundle["raw_sha256"], "bundle_root": bundle["root"]}


def client_request(args: argparse.Namespace, key: tuple) -> Any:
    """Send one host command to the owner service through this host's lane."""
    from .portfolio import prepare_portfolio_request
    from .service import owner_lane
    owner_portfolio = getattr(args, "portfolio", None)
    if key == ("portfolio", None):
        prepare_portfolio_request(args)
        owner_portfolio = getattr(args, "portfolio", None)
    owner_request = bool(owner_portfolio and host_config.config_path(_home(args)).exists()
                         and not getattr(args, "host", None))
    client = None if owner_request else _client_entry(args)
    lane = owner_lane(_home(args)) if owner_request else Path(client["lane"])
    command, sub = key
    body = _lane_args(args)
    if key in {("project", "register"), ("project", "import-history")}:
        body.update(_read_client_bundle(args.bundle))
    if key == ("portfolio", None):
        body["portfolio_args"] = list(args.portfolio_args)
    if key == ("manager", None):
        body = _manager_request(args.manager_args)
    request = {"schema": "otto.host-lane-request.v1", "command": command, "sub": sub, "args": body}
    if owner_request:
        request = {"command": "portfolio-operation", "args": request}
    result = _await(lane, request, args.wait_seconds, owner_actor=client.get("owner_actor") if client else None)
    return result


def _manager_request(argv: list) -> dict:
    """The orchestrator's owner-custody manager command, parsed client-side and relayed."""
    from .manager_client import build_parser
    values = vars(build_parser().parse_args(argv))
    values.pop("timeout_seconds", None)
    project = values.pop("project", None)
    return {"project": project, "request": values}


def _receipt(home: Path, name: str, value: Any) -> None:
    directory = home / "receipts"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_name = quote(str(name), safe="._-")
    path = directory / (safe_name + ".json")
    temporary = directory / ("." + safe_name + ".tmp")
    temporary.write_text(json_out(value) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def receipt_path(home: Path, name: str) -> Path:
    """Path for a receipt name that may contain a slash-bearing Megado run id."""
    return Path(home) / "receipts" / (quote(str(name), safe="._-") + ".json")


# Executed INSIDE the owner service for a host lane request (args.host = the lane's host).
def cmd_project_portfolio(args: argparse.Namespace) -> Any:
    from .portfolio import project_command
    return project_command(args, args.project_operation)


HOST_OPERATIONS = {
    ("host", "show"): cmd_host_show, ("host", "qualify-launcher"): cmd_host_qualify,
    ("whoami", None): lambda args: _whoami(args, "whoami"),
    ("effective-context", None): lambda args: _whoami(args, "effective-context"),
    ("portfolio", None): cmd_portfolio,
    ("projects", None): cmd_projects,
    ("project", "register"): cmd_register, ("project", "status"): cmd_project_status,
    ("project", "activate"): cmd_activate,
    ("project", "release-checkout"): cmd_release_checkout,
    ("project", "import-history"): cmd_import_history,
    ("project", "depend"): cmd_project_portfolio,
    ("project", "dependencies"): cmd_project_portfolio,
    ("project", "detach"): cmd_project_portfolio,
    ("operating-setup", None): cmd_operating_setup,
    ("admission", "dry-run"): cmd_admission_dry_run,
    ("schedules", None): cmd_schedules,
}
# Run by the invoking process itself (operator commands, local reads).
LOCAL_COMMANDS = {
    ("install", None): cmd_install,
    ("service", "run"): cmd_service_run, ("service", "admit-host"): cmd_service_admit,
    ("service", "admit"): cmd_service_admit_revision,
    ("service", "status"): cmd_service_status, ("service", "stop"): cmd_service_stop,
    ("service", "drain"): cmd_service_drain,
    ("request-status", None): cmd_request_status,
    ("skills", "which"): cmd_skills_which, ("skills", "install"): cmd_skills_install,
}
# Relayed by the service (to the attached project's manager lanes).
RELAYED_COMMANDS = {("manager", None), ("help", "read"), ("help", "respond")}


def _writer_busy() -> type:
    from herzchen.kernel.store import WriterBusyError
    return WriterBusyError


def _split_passthrough(argv: list) -> tuple:
    """`manager` and `portfolio` hand their remaining arguments to their own parsers verbatim."""
    for index, item in enumerate(argv):
        if item in {"manager", "portfolio"}:
            return argv[:index + 1], argv[index + 1:]
        if not item.startswith("-") and (index == 0 or argv[index - 1] not in {"--home", "--host", "--wait-seconds"}):
            break
    return argv, None


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["heavy"]:
        # The machine's one heavy-job lease: it runs a command and returns its exit code (not a JSON request).
        from .heavy import main as heavy_main
        return heavy_main(argv[1:])
    head, rest = _split_passthrough(argv)
    args = build_parser().parse_args(head)
    if rest is not None:
        setattr(args, "manager_args" if args.command == "manager" else "portfolio_args", rest)
    sub = (getattr(args, "host_command", None) or getattr(args, "project_command", None)
           or getattr(args, "admission_command", None) or getattr(args, "skills_command", None)
           or getattr(args, "service_command", None) or getattr(args, "help_command", None))
    key = (args.command, sub)
    launched = os.environ.get("OTTO_MANAGER_IPC") or os.environ.get("OTTO_CALLER_SOCKET")
    try:
        if key in LOCAL_COMMANDS:
            result = LOCAL_COMMANDS[key](args)
        elif key == ("manager", None) and launched:
            # A process the owner launched (the manager, or a worker) uses its own lanes.
            from .manager_client import run_launched
            result = run_launched(args.manager_args, os.environ)
        else:
            result = client_request(args, key)
    except _writer_busy() as exc:
        print(json_out({"outcome": "unavailable", "error": {"code": "owner_service_running", "message":
            "another owner process holds the Store (" + str(exc) + "); there is one owner service: talk to it "
            "(`ottoctl service status`), never open the Store beside it"}}))
        return EXIT_UNAVAILABLE
    except host_config.HostConfigError as exc:
        print(json_out({"outcome": "unavailable", "error": {"code": "host_unavailable", "message": str(exc)}}))
        return EXIT_UNAVAILABLE
    except Exception as exc:
        print(json_out({"outcome": "error", "error": {"code": type(exc).__name__, "message": str(exc)},
                        "provider_called": False}))
        return EXIT_ERROR
    if key == ("portfolio", None) and args.portfolio_args and args.portfolio_args[0] == "apply":
        from .portfolio import parser as portfolio_parser
        from .portfolio_apply import render_apply_summary
        apply_options = portfolio_parser().parse_args(args.portfolio_args)
        if (not apply_options.json and isinstance(result, Mapping)
                and result.get("outcome") in {"plan", "applied", "in_sync"}):
            print(render_apply_summary(result, detail=apply_options.detail))
        else:
            print(json_out(result))
    else:
        print(json_out(result))
    outcome = result.get("outcome") if isinstance(result, Mapping) else None
    if (key == ("service", "run") and outcome == "closed"
            and result.get("owner_exit_requested") is not True):
        return EXIT_ERROR
    return EXIT_UNAVAILABLE if outcome == "unavailable" else EXIT_ERROR if outcome in {
        "error", "blocked", "denied", "rejected"} else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
