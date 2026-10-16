"""Small manager entry over existing Otto portfolio owner ports.

The module owns no Store, project cache, scheduler, provider, or workflow state.
Callers inject the already constructed Otto and Herzchen ports. Bare module
execution remains explicitly unavailable for owner-bound operations until an
application supplies those dependencies.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Mapping, Optional, Sequence

from herzchen.authoring.sessions import InvalidSessionError

from .assessment import OttoAssessment
from .intake import OttoPortfolio, PortfolioError
from .operating_brief import OperatingBriefError, prepare_canonical_operating_brief
from .resource_sync import ResourceSyncError, resolve_assignment_attachments
from .observability_views import VIEW_PRESETS
from .show import open_session, show_project


TASK_VIEWS = ("all", "upcoming", "ready", "blocked", "in_progress", "completed")


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json", "text"), default="json", help="structured JSON or readable text with the full canonical response")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m otto.portfolio.cli",
        description="manager entry over injected canonical Otto and Herzchen ports",
        epilog=(
            "Inject an accepted OttoPortfolio at cli.main(argv, portfolio=...). "
            "Document commands also require the existing ProjectDocumentOperations facade via "
            "cli.main(..., document_operations=...). Assessment, gate, and operating-brief commands "
            "require their existing owner/read ports through cli.main(...). The module does not create an owner or Store."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    help_parser = sub.add_parser("help", help="show the manager entry contract")
    _add_format(help_parser)

    vision = sub.add_parser(
        "vision",
        help="run the finite Vision resource/authoring command envelope over injected host ports",
        description="Dispatch one {command:vision, operation, arguments, request_key?} envelope through an injected authenticated Vision surface.",
    )
    vision.add_argument("--request-json", required=True, help="Vision command envelope as a JSON object")
    _add_format(vision)

    save = sub.add_parser("save", help="save one project from a save file (template seed shape); a stale project_ref revision is refused with a diff")
    save.add_argument("file", help="JSON save file: project, tasks, criteria, plus project_ref to save an existing project")
    save.add_argument("--actor", required=True)
    save.add_argument("--request-id", default=None, help="logical request key (default: derived from the file's content)")
    _add_format(save)

    show = sub.add_parser("show", help="read one project or task; the output is the same on the Claude and Codex lanes")
    show_sub = show.add_subparsers(dest="show_command", required=True)
    show_project_parser = show_sub.add_parser("project", help="one project's row and its task rows")
    show_project_parser.add_argument("--project-ref", required=True, help="canonical project ResourceRef as JSON")
    show_project_parser.add_argument("--actor", required=True)
    show_project_parser.add_argument("--limit", type=int, default=100)
    _add_format(show_project_parser)
    show_task_parser = show_sub.add_parser("task", help="one task's detail")
    show_task_parser.add_argument("--project-ref", required=True, help="canonical project ResourceRef as JSON")
    show_task_parser.add_argument("--task-ref", required=True, help="canonical task ResourceRef as JSON")
    show_task_parser.add_argument("--actor", required=True)
    show_task_parser.add_argument("--limit", type=int, default=100)
    _add_format(show_task_parser)

    open_parser = sub.add_parser("open", help="open, autosave, finish or release one project document's authoring session through the owner editor")
    open_sub = open_parser.add_subparsers(dest="open_command", required=True)
    for step, step_help in (
        ("start", "open the authoring session and return its handle"),
        ("autosave", "save the editor buffer into the open session"),
        ("finish", "check the session in; a stale base is refused and changes nothing"),
        ("release", "close the open session by its handle without publishing"),
    ):
        step_parser = open_sub.add_parser(step, help=step_help)
        step_parser.add_argument("--project-ref", required=True, help="canonical project ResourceRef as JSON")
        step_parser.add_argument("--document-ref", required=True, help="canonical document ResourceRef as JSON")
        step_parser.add_argument("--request-key", required=True)
        if step == "start":
            step_parser.add_argument("--inactivity-seconds", type=float, default=None)
        else:
            step_parser.add_argument("--handle-json", required=True, help="the handle that open returned, as JSON")
        if step == "autosave":
            step_parser.add_argument("--buffer-json", required=True, help="the editor's current JSON content value")
        _add_format(step_parser)

    status = sub.add_parser("status", help="portfolio status: projects, tasks, pool, managers, lab count and slot kinds")
    status.add_argument("--portfolio-ref", help="canonical portfolio ResourceRef as JSON (default: this host's portfolio)")
    _add_format(status)

    create = sub.add_parser("create-pending", help="create an inert pending project (legacy command)")
    create.add_argument("--actor", required=True)
    create.add_argument("--request-id", required=True)
    create.add_argument("--edit-json", default="{}")
    create.add_argument("--template", default=None)
    create.add_argument("--open", action="store_true", dest="open_project")
    _add_format(create)

    onboarding = sub.add_parser(
        "onboarding", aliases=("draft",),
        help="discoverable inert title-plus-brief project workspace",
        description=(
            "Create, find, or reopen one pending title-plus-brief workspace. "
            "This route uses the injected owner authoring, DAT document, and EDT ports; "
            "it never creates tasks, roles, pools, schedules, or provider effects."
        ),
    )
    onboarding_sub = onboarding.add_subparsers(dest="onboarding_command", required=True)
    onboarding_create = onboarding_sub.add_parser("create", help="create an inert draft with brief.md")
    onboarding_create.add_argument("--actor", required=True)
    onboarding_create.add_argument("--request-id", required=True)
    onboarding_create.add_argument("--title", required=True)
    onboarding_create.add_argument("--brief", required=True)
    onboarding_create.add_argument("--supporting-files", help="JSON object of relative paths to UTF-8 text")
    onboarding_create.add_argument("--predecessor-ref", help="optional existing project ResourceRef JSON")
    onboarding_create.add_argument("--template", help="blank or a JSON work-template resource")
    onboarding_create.add_argument("--template-parameters", help="JSON parameters for the selected template")
    _add_format(onboarding_create)
    onboarding_find = onboarding_sub.add_parser("find", help="read one draft by its canonical project reference")
    onboarding_find.add_argument("--actor", required=True)
    onboarding_find.add_argument("--project-ref", required=True)
    _add_format(onboarding_find)
    onboarding_reopen = onboarding_sub.add_parser("reopen", help="reopen the same draft through the EDT projection")
    onboarding_reopen.add_argument("--actor", required=True)
    onboarding_reopen.add_argument("--request-id", required=True)
    onboarding_reopen.add_argument("--project-ref", required=True)
    _add_format(onboarding_reopen)

    read = sub.add_parser("read", help="read one durable pending-project reference (legacy command)")
    read.add_argument("project_id")
    read.add_argument("--actor", required=True)
    _add_format(read)

    listing = sub.add_parser("list", help="list pending projects (legacy lifecycle-filtered view)")
    listing.add_argument("--actor", required=True)
    _add_format(listing)

    inventory = sub.add_parser("inventory", help="read the existing manager inventory")
    inventory.add_argument("--actor", required=True)
    _add_format(inventory)

    projects = sub.add_parser("projects", help="list projects across visible lifecycle states")
    projects.add_argument("--actor", required=True)
    projects.add_argument("--parent-ref", help="canonical project ResourceRef as JSON")
    projects.add_argument("--limit", type=int, help="maximum projects in this owner page (1..1000)")
    projects.add_argument("--cursor", help="owner-issued continuation cursor")
    _add_format(projects)

    recovery = sub.add_parser(
        "find-and-continue",
        help="read a bounded project/checkout/session recovery join",
    )
    recovery.add_argument("--actor", required=True)
    recovery.add_argument("--project-ref", help="existing canonical project ResourceRef JSON")
    recovery.add_argument("--checkout-ref", help="existing retained authoring-scope ResourceRef JSON")
    recovery.add_argument("--session-id", help="existing retained session locator")
    recovery.add_argument("--limit", type=int, default=25)
    recovery.add_argument("--cursor")
    _add_format(recovery)

    events = sub.add_parser("events", help="read bounded retained Events operator views")
    events_sub = events.add_subparsers(dest="events_view", required=True)
    for view_name in VIEW_PRESETS:
        view_parser = events_sub.add_parser(view_name, help="read the authorized bounded %s view" % view_name)
        view_parser.add_argument("--actor", required=True)
        view_parser.add_argument("--project-ref", action="append", required=True,
                                 help="authorized work.project ResourceRef JSON; repeat for up to 32 projects")
        view_parser.add_argument("--from", dest="from_at")
        view_parser.add_argument("--to", dest="to_at")
        view_parser.add_argument("--timezone", dest="timezone_name")
        view_parser.add_argument("--active-during", help="JSON [from,to) range for authorized active discovery")
        view_parser.add_argument("--limit", type=int, default=50)
        view_parser.add_argument("--cursor")
        view_parser.add_argument("--snapshot", help="original snapshot JSON for continuation")
        view_parser.add_argument("--filters", help="supported role/outcome/facet_type filter JSON")
        _add_format(view_parser)
    detail = events_sub.add_parser("detail", help="read one selected authorized bounded history detail")
    detail.add_argument("--actor", required=True)
    detail.add_argument("--project-ref", action="append", required=True,
                        help="authorized work.project ResourceRef JSON; used to establish the grant scope")
    detail.add_argument("--facet-id", required=True)
    detail.add_argument("--snapshot", required=True, help="original snapshot JSON from an Events view")
    detail.add_argument("--max-detail-bytes", type=int, default=64 * 1024)
    _add_format(detail)

    overview = sub.add_parser("overview", help="read one project's overview and a task page")
    overview.add_argument("--actor", required=True)
    overview.add_argument("--project-ref", required=True, help="canonical project ResourceRef as JSON")
    overview.add_argument("--view", choices=TASK_VIEWS, default="all")
    overview.add_argument("--limit", type=int, default=100)
    overview.add_argument("--cursor")
    _add_format(overview)

    tasks = sub.add_parser("tasks", help="filter owner-backed tasks and preserve the continuation cursor")
    tasks.add_argument("--actor", required=True)
    tasks.add_argument("--view", choices=TASK_VIEWS, default="all")
    tasks.add_argument("--project-ref", help="canonical project ResourceRef as JSON")
    tasks.add_argument("--parent-ref", help="canonical parent project ResourceRef as JSON")
    tasks.add_argument("--limit", type=int, default=100)
    tasks.add_argument("--cursor")
    _add_format(tasks)

    task = sub.add_parser("task", help="read one task detail through owner pagination")
    task.add_argument("--actor", required=True)
    task.add_argument("--project-ref", required=True, help="canonical project ResourceRef as JSON")
    task.add_argument("--task-ref", required=True, help="canonical task ResourceRef as JSON")
    task.add_argument("--limit", type=int, default=1000, help="page size used while locating the task (1..1000)")
    _add_format(task)

    documents = sub.add_parser("documents", help="read canonical project documents and navigation")
    doc_sub = documents.add_subparsers(dest="document_command", required=True)

    doc_list = doc_sub.add_parser("list", help="list all visible project/task document memberships")
    _add_project_actor(doc_list)
    doc_list.add_argument("--role", action="append", default=[])
    doc_list.add_argument("--task-ref", action="append", default=[], help="optional task ResourceRef JSON; repeat to scope")
    _add_format(doc_list)

    doc_metadata = doc_sub.add_parser("metadata", help="bounded project/exact-role metadata page; empty pages may continue")
    _add_project_actor(doc_metadata)
    doc_metadata.add_argument("--exact-role", required=True)
    doc_metadata.add_argument("--representation", choices=("managed", "inline"))
    doc_metadata.add_argument("--content-format")
    doc_metadata.add_argument("--cursor", default="")
    doc_metadata.add_argument("--limit", type=int, default=50)
    doc_metadata.add_argument("--role", action="append", default=[])
    doc_metadata.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_metadata)

    doc_search = doc_sub.add_parser("search", help="search visible title, text, role, path alias, or task title")
    _add_project_actor(doc_search)
    doc_search.add_argument("--query", required=True)
    doc_search.add_argument("--limit", type=int, default=100)
    doc_search.add_argument("--role", action="append", default=[])
    doc_search.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_search)

    doc_read = doc_sub.add_parser("read", help="read one exact revision-pinned document")
    _add_project_actor(doc_read)
    doc_read.add_argument("--document-ref", required=True, help="exact revision-pinned document ResourceRef JSON")
    doc_read.add_argument("--role", action="append", default=[])
    doc_read.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_read)

    doc_link = doc_sub.add_parser("link", help="follow a preserved relative link")
    _add_project_actor(doc_link)
    doc_link.add_argument("--source-ref", required=True, help="canonical source document ResourceRef JSON")
    doc_link.add_argument("--href", required=True, help="preserved relative link text")
    doc_link.add_argument("--source-path", help="source association key when it has multiple aliases")
    doc_link.add_argument("--role", action="append", default=[])
    doc_link.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_link)

    doc_history = doc_sub.add_parser("history", help="list exact immutable revisions with the owner's continuation ref")
    _add_project_actor(doc_history)
    doc_history.add_argument("--document-ref", required=True)
    doc_history.add_argument("--limit", type=int, default=50)
    doc_history.add_argument("--start-revision-ref", help="exact continuation ResourceRef JSON")
    doc_history.add_argument("--role", action="append", default=[])
    doc_history.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_history)

    doc_bundle = doc_sub.add_parser("bundle", help="export selected readable current documents in memory")
    _add_project_actor(doc_bundle)
    doc_bundle.add_argument("--document-refs", required=True, help="JSON array of canonical document ResourceRefs")
    doc_bundle.add_argument("--role", action="append", default=[])
    doc_bundle.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_bundle)

    doc_diff = doc_sub.add_parser("diff", help="compare two exact authorized revisions")
    _add_project_actor(doc_diff)
    doc_diff.add_argument("--document-ref", required=True)
    doc_diff.add_argument("--older-revision-ref", required=True)
    doc_diff.add_argument("--newer-revision-ref", required=True)
    doc_diff.add_argument("--role", action="append", default=[])
    doc_diff.add_argument("--task-ref", action="append", default=[])
    _add_format(doc_diff)

    assessment = sub.add_parser("assessment-coverage", help="show exact scoped criterion coverage and correction lineage")
    assessment.add_argument("--parent-ref", required=True, help="canonical work.task parent obligation ResourceRef JSON")
    assessment.add_argument("--scope-ref", help="optional exact assessment.scope ResourceRef JSON")
    assessment.add_argument("--criterion-ref", help="optional exact criterion ResourceRef JSON")
    _add_format(assessment)

    gate = sub.add_parser("completion-gate", help="read the existing required-assessment completion blockers")
    gate.add_argument("--task-ref", required=True, help="canonical work.task ResourceRef JSON")
    gate.add_argument("--candidate-ref", help="exact candidate ResourceRef JSON")
    gate.add_argument("--gate-ref", action="append", default=[], help="exact accepted decision/evidence ResourceRef JSON; repeat to supply")
    _add_format(gate)

    complete = sub.add_parser("complete-task", help="request one existing owner-guarded task completion")
    complete.add_argument("--input-json", required=True, help="full OttoPortfolio.complete_task request, including actor, request id and current owner pins")
    _add_format(complete)

    advisor = sub.add_parser(
        "project-advisor-pair",
        help="read or create the one advisor assignment for an exact current manager",
    )
    advisor.add_argument("--actor", required=True)
    advisor.add_argument("--request-id", required=True)
    advisor.add_argument("--project-ref", required=True, help="exact current work.project ResourceRef JSON")
    advisor.add_argument("--manager-assignment-ref", required=True, help="exact current manager wrk.assignment ResourceRef JSON")
    advisor.add_argument("--manager-generation", required=True, type=int)
    advisor.add_argument("--advisor-principal", help="omit for a read-only current-pair lookup")
    advisor.add_argument("--pin", action="append", default=[], help="exact owner resource ref JSON; repeat to pin advisor inputs")
    _add_format(advisor)

    from .manager_journey_client import add_help_parsers
    for help_parser in add_help_parsers(sub):
        _add_project_actor(help_parser)
        if help_parser.prog.endswith(("request-help", "request-advice", "resolve-help")):
            help_parser.add_argument("--assignment-ref", required=True)
            help_parser.add_argument("--generation", type=int, required=True)
        _add_format(help_parser)

    brief = sub.add_parser("operating-brief", help="prepare the current manager brief from exact owner reads and adopted resources")
    brief.add_argument("--request-json", required=True, help="role, pinned project/task/assignment/mandate refs, generation and as-of time")
    _add_format(brief)

    direction = sub.add_parser("direction", help="read and explicitly author owner-bound direction")
    direction_sub = direction.add_subparsers(dest="direction_command", required=True)
    direction_read = direction_sub.add_parser("read", help="read latest, adopted and effective direction state")
    direction_read.add_argument("--actor", required=True)
    direction_read.add_argument("--subject-ref", required=True)
    direction_read.add_argument("--assignment-ref")
    direction_read.add_argument("--generation", type=int)
    _add_format(direction_read)
    direction_context = direction_sub.add_parser("effective-context", help="read attributed effective direction inputs")
    direction_context.add_argument("--actor", required=True)
    direction_context.add_argument("--assignment-ref", required=True)
    direction_context.add_argument("--generation", required=True, type=int)
    direction_context.add_argument("--project-ref", required=True)
    direction_context.add_argument("--task-ref")
    _add_format(direction_context)
    direction_whoami = direction_sub.add_parser("whoami", help="read trusted caller context")
    direction_whoami.add_argument("--actor", required=True)
    _add_format(direction_whoami)
    direction_bind = direction_sub.add_parser("initial-bind", help="bind an unbound responsibility to an owned direction document")
    direction_bind.add_argument("--actor", required=True)
    direction_bind.add_argument("--subject-ref", required=True)
    direction_bind.add_argument("--document-ref", required=True)
    direction_bind.add_argument("--request-key", required=True)
    _add_format(direction_bind)
    direction_draft = direction_sub.add_parser("draft", help="append direction content without adopting it")
    direction_draft.add_argument("--actor", required=True)
    direction_draft.add_argument("--subject-ref", required=True)
    direction_draft.add_argument("--content", required=True)
    direction_draft.add_argument("--request-key", required=True)
    direction_draft.add_argument("--expected-revision")
    _add_format(direction_draft)
    direction_update = direction_sub.add_parser("update", help="explicitly adopt one exact direction revision")
    direction_update.add_argument("--actor", required=True)
    direction_update.add_argument("--subject-ref", required=True)
    direction_update.add_argument("--revision-ref")
    direction_update.add_argument("--content")
    direction_update.add_argument("--binding-ref")
    direction_update.add_argument("--request-key", required=True)
    direction_update.add_argument("--expected-revision")
    direction_update.add_argument("--assignment-ref")
    direction_update.add_argument("--generation", type=int)
    direction_update.add_argument("--assignment-resources")
    direction_update.add_argument("--assignment-guard-ref")
    _add_format(direction_update)
    direction_history = direction_sub.add_parser("history", help="read immutable direction and adoption history")
    direction_history.add_argument("--actor", required=True)
    direction_history.add_argument("--subject-ref", required=True)
    _add_format(direction_history)
    direction_overview = direction_sub.add_parser("overview", help="read a bounded permission-scoped direction overview")
    direction_overview.add_argument("--actor", required=True)
    direction_overview.add_argument("--subjects", help="JSON array of existing canonical subject/inventory rows")
    direction_overview.add_argument("--limit", type=int, default=50)
    direction_overview.add_argument("--cursor")
    _add_format(direction_overview)
    return parser


def _add_project_actor(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor", required=True)
    parser.add_argument("--project-ref", required=True, help="canonical project ResourceRef as JSON")


def _parse_json(value: str, field: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"{field} must be valid JSON: {exc}") from exc


def _parse_json_or_name(value: Optional[str], field: str) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_ref(value: str, field: str, *, pinned: bool = False) -> dict[str, Any]:
    parsed = _parse_json(value, field)
    if not isinstance(parsed, Mapping) or any(not isinstance(parsed.get(key), str) or not parsed.get(key).strip() for key in ("authority", "kind", "id")):
        raise ValueError(f"{field} must be a canonical ResourceRef object with authority, kind, and id")
    ref = dict(parsed)
    if pinned and (not isinstance(ref.get("revision"), str) or not ref["revision"].strip()):
        raise ValueError(f"{field} must include an exact revision; use document history to select a revision")
    return ref


def _request_error(message: str, *, code: str = "invalid_request") -> dict[str, Any]:
    return {"outcome": "error", "schema": "otto.cli-error.v1", "error": {"code": code, "message": message}, "read_only": True}


def _docs_unavailable() -> dict[str, Any]:
    return {
        "outcome": "unavailable",
        "schema": "otto.document-surface.v1",
        "read_only": True,
        "dispatch": False,
        "launch": False,
        "error": {
            "code": "document_operations_unavailable",
            "message": "Inject the accepted ProjectDocumentOperations facade at cli.main(..., document_operations=...); this CLI does not construct Herzchen owners or a Store.",
        },
    }


def _surface_unavailable(schema: str, code: str, message: str) -> dict[str, Any]:
    return {
        "outcome": "unavailable", "schema": schema, "read_only": True,
        "dispatch": False, "launch": False,
        "error": {"code": code, "message": message},
    }


def _owner_mapping(value: Any, field: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return dict(result)
    raise ValueError(f"{field} owner reader returned no record")


def _request_ref(value: Any, field: str, *, pinned: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a canonical ResourceRef object")
    ref = dict(value)
    for key in ("authority", "kind", "id"):
        if not isinstance(ref.get(key), str) or not ref[key].strip():
            raise ValueError(f"{field}.{key} must be non-blank text")
    if pinned and (not isinstance(ref.get("revision"), str) or not ref["revision"].strip()):
        raise ValueError(f"{field}.revision must be an exact current revision")
    return ref


def _ref_matches(actual: Any, expected: Mapping[str, Any], field: str) -> bool:
    try:
        observed = _request_ref(actual, field)
    except ValueError:
        return False
    if any(observed.get(key) != expected.get(key) for key in ("authority", "kind", "id")):
        return False
    return "revision" not in expected or observed.get("revision") == expected.get("revision")


def _assessment_coverage_command(args: argparse.Namespace, assessment: Any) -> dict[str, Any]:
    if assessment is None or not callable(getattr(assessment, "coverage", None)):
        return _surface_unavailable(
            "otto.assessment-coverage.v1", "assessment_owner_unavailable",
            "Inject the accepted OttoAssessment facade at cli.main(..., assessment=...); the CLI does not construct an assessment owner or Store.",
        )
    parent = _parse_ref(args.parent_ref, "parent_ref")
    if parent.get("kind") != "work.task":
        raise ValueError("parent_ref must identify a work.task obligation")
    requested_scope = _parse_ref(args.scope_ref, "scope_ref") if args.scope_ref else None
    requested_criterion = _parse_ref(args.criterion_ref, "criterion_ref") if args.criterion_ref else None
    if requested_scope is not None and requested_scope.get("kind") != "assessment.scope":
        raise ValueError("scope_ref must identify an assessment.scope")
    try:
        source = assessment.coverage(parent)
    except Exception as exc:
        return {
            "outcome": "unknown", "schema": "otto.assessment-coverage.v1",
            "parent_obligation_ref": parent, "read_only": True, "writes": 0,
            "dispatch": False, "launch": False,
            "error": {"code": "assessment_read_failed", "message": str(exc)},
            "next_action": "refresh the parent ref and inspect the assessment owner response before making a coverage claim",
        }
    scopes = list(source.get("scopes", ()))
    coverage = list(source.get("coverage", ()))
    if requested_scope is not None:
        scopes = [row for row in scopes if _ref_matches(row.get("ref"), requested_scope, "scope.ref")]
        coverage = [row for row in coverage if _ref_matches(row.get("scope_ref"), requested_scope, "coverage.scope_ref")]
    if requested_criterion is not None:
        coverage = [row for row in coverage if _ref_matches(row.get("criterion_ref"), requested_criterion, "coverage.criterion_ref")]
    selected_result_ids = {
        _ref_identity(ref)
        for row in coverage
        for ref in row.get("result_refs", ())
    }
    result_rows = [row for row in source.get("results", ()) if _ref_identity(row.get("ref")) in selected_result_ids]
    result_ids = {_ref_identity(row.get("ref")) for row in result_rows}
    correction_rows = [row for row in source.get("corrections", ()) if _ref_identity(row.get("result_ref")) in result_ids]
    correction_ids = {_ref_identity(row.get("ref")) for row in correction_rows}
    decision_ids = {
        _ref_identity(ref)
        for row in result_rows
        for ref in row.get("decision_refs", ())
    }
    decision_ids.update(_ref_identity(row.get("decision_ref")) for row in correction_rows if row.get("decision_ref"))
    decisions = [row for row in source.get("decisions", ()) if _ref_identity(row.get("ref")) in decision_ids]
    complete = source.get("complete_scan") is True
    return {
        "outcome": "read" if complete else "partial",
        "schema": "otto.assessment-coverage.v1",
        "parent_obligation_ref": source.get("parent_obligation_ref", parent),
        "scope_count": len(scopes), "scopes": scopes, "coverage": coverage,
        "results": result_rows, "corrections": correction_rows, "decisions": decisions,
        "complete_scan": complete, "pagination": source.get("pagination"),
        "filters": {"scope_ref": requested_scope, "criterion_ref": requested_criterion},
        "read_only": True, "writes": 0, "dispatch": False, "launch": False,
    }


def _completion_gate_command(args: argparse.Namespace, completion_owner: Any) -> dict[str, Any]:
    schema = "otto.completion-gate.v1"
    method = getattr(completion_owner, "completion_blockers", None) if completion_owner is not None else None
    if not callable(method):
        return _surface_unavailable(
            schema, "completion_gate_owner_unavailable",
            "Inject the existing ResponsibilityAssignments completion_blockers read port at cli.main(..., completion_owner=...).",
        )
    task_ref = _parse_ref(args.task_ref, "task_ref")
    if task_ref.get("kind") != "work.task":
        raise ValueError("task_ref must identify a work.task")
    candidate = _parse_ref(args.candidate_ref, "candidate_ref") if args.candidate_ref else None
    gates = [_parse_ref(value, f"gate_ref[{index}]") for index, value in enumerate(args.gate_ref or ())]
    try:
        state = method(task_ref, candidate=candidate, gate_refs=tuple(gates))
    except Exception as exc:
        return {
            "outcome": "unknown", "schema": schema, "task_ref": task_ref,
            "candidate_ref": candidate, "gate_refs": gates,
            "read_only": True, "writes": 0, "dispatch": False, "launch": False,
            "error": {"code": "completion_gate_read_failed", "message": str(exc)},
            "next_action": "refresh the task and supplied evidence refs, then inspect the owner error",
        }
    if not isinstance(state, Mapping):
        return {
            "outcome": "unknown", "schema": schema, "task_ref": task_ref,
            "read_only": True, "writes": 0,
            "error": {"code": "malformed_completion_gate", "message": "owner returned no blocker object"},
        }
    blockers = list(state.get("blockers", ()))
    # No blockers is not a positive proof when required evidence was not verified.
    outcome = "blocked" if blockers else "clear"
    if not blockers and state.get("required") is True and state.get("evidence_verification") != "verified":
        outcome = "unknown"
    return {
        "outcome": outcome, "schema": schema,
        "task_ref": task_ref, "candidate_ref": candidate, "gate_refs": gates,
        "blockers": blockers, "owner_gate_state": dict(state),
        "read_only": True, "writes": 0, "dispatch": False, "launch": False,
    }


def _complete_task_command(
    args: argparse.Namespace,
    portfolio: Any,
    *,
    portfolio_injected: bool,
    bound_actor: Optional[str] = None,
) -> dict[str, Any]:
    schema = "otto.task-completion-request.v1"
    if not portfolio_injected or not callable(getattr(portfolio, "complete_task", None)):
        return _surface_unavailable(
            schema, "completion_owner_unavailable",
            "Inject the existing owner-bound OttoPortfolio at cli.main(..., portfolio=...) to request task completion.",
        )
    request = _parse_json(args.input_json, "input_json")
    if not isinstance(request, Mapping):
        raise ValueError("input_json must be an object")
    request = dict(request)
    if bound_actor is not None and request.get("actor") != bound_actor:
        return {
            "outcome": "denied", "schema": schema, "read_only": False,
            "dispatch": False, "launch": False,
            "error": {
                "code": "bound_actor_mismatch",
                "message": "completion request actor does not match the host-bound owner actor",
            },
        }
    required = (
        "project_ref", "task_ref", "assignment_ref", "actor", "request_id",
        "expected_generation", "expected_project_revision", "expected_task_revision",
        "disposition", "evidence_refs", "evidence_hashes", "gate_refs",
    )
    missing = [key for key in required if key not in request]
    if missing:
        raise ValueError("input_json is missing required owner completion fields: " + ", ".join(missing))
    project = _request_ref(request["project_ref"], "project_ref", pinned=True)
    task = _request_ref(request["task_ref"], "task_ref", pinned=True)
    assignment = _request_ref(request["assignment_ref"], "assignment_ref", pinned=True)
    if project["kind"] != "work.project" or task["kind"] != "work.task":
        raise ValueError("project_ref and task_ref must identify work.project and work.task records")
    if not isinstance(request["actor"], str) or not request["actor"].strip() or not isinstance(request["request_id"], str) or not request["request_id"].strip():
        raise ValueError("actor and request_id must be non-blank text")
    if not isinstance(request["expected_generation"], int) or isinstance(request["expected_generation"], bool) or request["expected_generation"] < 1:
        raise ValueError("expected_generation must be a positive integer")
    for key in ("expected_project_revision", "expected_task_revision", "disposition"):
        if not isinstance(request[key], str) or not request[key].strip():
            raise ValueError(f"{key} must be non-blank text")
    for key in ("evidence_refs", "gate_refs"):
        if isinstance(request[key], (str, bytes)) or not isinstance(request[key], Sequence):
            raise ValueError(f"{key} must be an array of ResourceRef objects")
        request[key] = [_request_ref(value, f"{key}[{index}]") for index, value in enumerate(request[key])]
    if not isinstance(request["evidence_hashes"], (Mapping, list, tuple)):
        raise ValueError("evidence_hashes must be an object or array")
    for key in ("candidate_ref", "result_ref", "attempt_ref"):
        if request.get(key) is not None:
            request[key] = _request_ref(request[key], key)
    request.update(project_ref=project, task_ref=task, assignment_ref=assignment)
    try:
        result = portfolio.complete_task(**request)
    except Exception as exc:
        return {
            "outcome": "error", "schema": schema, "read_only": False,
            "dispatch": False, "launch": False,
            "error": {"code": "completion_request_failed", "message": str(exc)},
        }
    if not isinstance(result, Mapping):
        return {
            "outcome": "error", "schema": schema, "read_only": False,
            "error": {"code": "malformed_completion_result", "message": "injected owner returned no completion result"},
        }
    return {
        **dict(result), "schema": schema, "read_only": False,
        "dispatch": False, "launch": False,
    }


def _local_bundle_state(context: Any) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        return {"state": "not_supplied", "publication": "not_observed", "adoption": "not_observed", "delivery": "not_observed"}
    return {
        "state": "local_prepublication_only",
        "bundle_identity": context.get("bundle_identity"),
        "bundle_digest": context.get("bundle_digest"),
        "publication": "not_performed",
        "adoption": "not_performed",
        "delivery": "not_performed",
        "target_readback": "not_performed",
        "evidence_ref": context.get("evidence_ref"),
    }


def _operating_brief_command(
    args: argparse.Namespace,
    readers: Any,
    staged_bundle_context: Any,
    *,
    reader_factory: Any = None,
) -> dict[str, Any]:
    schema = "otto.manager-operating-brief.v1"
    request = _parse_json(args.request_json, "request_json")
    if not isinstance(request, Mapping):
        raise ValueError("request_json must be an object")
    request = dict(request)
    role = request.get("role")
    if not isinstance(role, str) or role not in {"orchestrator", "manager", "worker", "project_advisor"}:
        raise ValueError("role must be orchestrator, manager, worker, or project_advisor")
    assignment_pin = _request_ref(request.get("assignment_ref"), "assignment_ref", pinned=True)
    if assignment_pin.get("kind") != "wrk.assignment":
        raise ValueError("assignment_ref must identify a wrk.assignment")
    generation = request.get("expected_generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValueError("expected_generation must be a positive integer")
    if not isinstance(request.get("as_of"), str) or not request["as_of"].strip():
        raise ValueError("as_of must be non-blank text")
    if readers is None and callable(reader_factory):
        try:
            readers = reader_factory(
                phase="assignment", request=request, assignment_ref=assignment_pin,
            )
        except Exception as exc:
            return {
                "outcome": "unknown", "schema": schema, "assignment_ref": assignment_pin,
                "read_only": True, "writes": 0,
                "error": {"code": "operating_brief_reader_factory_failed", "message": str(exc)},
            }
    if not isinstance(readers, Mapping):
        return _surface_unavailable(
            schema, "operating_brief_readers_unavailable",
            "Inject the existing project, assignment, mandate and resource readers at cli.main(..., operating_brief_readers=...).",
        )
    assignment_reader = readers.get("assignment_reader")
    resource_reader = readers.get("resource_reader")
    if not callable(assignment_reader) or resource_reader is None:
        return _surface_unavailable(
            schema, "operating_brief_assignment_reader_unavailable",
            "An explicit assignment_reader and canonical resource_reader are required to establish adoption state.",
        )
    identity_lookup = {key: assignment_pin[key] for key in ("authority", "kind", "id")}
    try:
        assignment = _owner_mapping(assignment_reader(identity_lookup), "assignment")
    except Exception as exc:
        return {
            "outcome": "unknown", "schema": schema, "assignment_ref": assignment_pin,
            "read_only": True, "writes": 0,
            "error": {"code": "assignment_read_failed", "message": str(exc)},
        }
    observed_ref = assignment.get("ref", assignment.get("assignment_ref"))
    if observed_ref is None and isinstance(assignment.get("payload"), Mapping):
        observed_ref = assignment["payload"].get("ref", assignment["payload"].get("assignment_ref"))
    if not _ref_matches(observed_ref, assignment_pin, "assignment.ref"):
        return {
            "outcome": "conflict", "schema": schema, "assignment_ref": assignment_pin,
            "current_assignment_ref": observed_ref, "read_only": True, "writes": 0,
            "next_action": "refresh the assignment revision and generation before preparing a brief",
        }
    payload = assignment.get("payload", assignment)
    if not isinstance(payload, Mapping):
        return {"outcome": "unknown", "schema": schema, "assignment_ref": assignment_pin,
                "read_only": True, "writes": 0,
                "error": {"code": "malformed_assignment", "message": "assignment payload is not an object"}}
    observed_generation = assignment.get("generation", payload.get("generation"))
    observed_role = assignment.get("role", payload.get("role"))
    if observed_generation != generation or (observed_role is not None and observed_role != role):
        return {
            "outcome": "conflict", "schema": schema, "assignment_ref": assignment_pin,
            "current_assignment_ref": observed_ref, "expected_generation": generation,
            "current_generation": observed_generation, "expected_role": role, "current_role": observed_role,
            "read_only": True, "writes": 0,
            "next_action": "refresh the assignment pin, generation and role from the owner",
        }
    try:
        attachments = resolve_assignment_attachments(assignment, resource_reader, role=role)
    except ResourceSyncError as exc:
        return {
            "outcome": "unknown", "schema": schema, "assignment_ref": assignment_pin,
            "read_only": True, "writes": 0,
            "local_bundle": _local_bundle_state(staged_bundle_context),
            "error": {"code": "adopted_resource_unresolved", "message": str(exc)},
            "next_action": "resolve the exact canonical adopted resource before preparing a role brief",
        }
    if not attachments:
        return {
            "outcome": "pending", "schema": schema,
            "assignment_ref": observed_ref, "role": role,
            "expected_generation": generation, "adopted_resources": [],
            "local_bundle": _local_bundle_state(staged_bundle_context),
            "operating_brief": None, "delivery_state": "not_prepared",
            "read_only": True, "writes": 0, "dispatch": False, "launch": False,
            "next_action": "adopt the exact published role BASE through the authorized owner path before brief preparation",
        }
    adopted_summary = [
        {key: item.get(key) for key in ("role", "responsibility_ref", "resource_ref", "resource_name", "adopted_revision", "bundle_digest", "export_manifest_digest", "required")}
        for item in attachments
    ]
    if callable(reader_factory):
        try:
            project_pin = _request_ref(request.get("project_ref"), "project_ref", pinned=True)
            mandate_pin = _request_ref(request.get("mandate_ref"), "mandate_ref", pinned=True)
            task_pin = _request_ref(request["task_ref"], "task_ref", pinned=True) if request.get("task_ref") is not None else None
            context_readers = reader_factory(
                phase="context", request=request, assignment_ref=assignment_pin,
                project_ref=project_pin, task_ref=task_pin, mandate_ref=mandate_pin,
            )
            if not isinstance(context_readers, Mapping):
                raise ValueError("context reader factory returned no reader mapping")
            readers = {**dict(readers), **dict(context_readers)}
        except Exception as exc:
            return {
                "outcome": "unknown", "schema": schema, "assignment_ref": observed_ref,
                "adopted_resources": adopted_summary, "read_only": True, "writes": 0,
                "error": {"code": "operating_brief_reader_factory_failed", "message": str(exc)},
            }
    required_readers = ("project_reader", "mandate_reader")
    if any(not callable(readers.get(key)) for key in required_readers):
        return {
            "outcome": "unavailable", "schema": schema, "assignment_ref": observed_ref,
            "adopted_resources": adopted_summary, "read_only": True, "writes": 0,
            "error": {"code": "operating_brief_context_readers_unavailable", "message": "project_reader and mandate_reader are required for canonical brief preparation"},
        }
    try:
        project_pin = _request_ref(request.get("project_ref"), "project_ref", pinned=True)
        mandate_pin = _request_ref(request.get("mandate_ref"), "mandate_ref", pinned=True)
        task_pin = _request_ref(request["task_ref"], "task_ref", pinned=True) if request.get("task_ref") is not None else None
        prepared = prepare_canonical_operating_brief(
            role=role, project_ref=project_pin, task_ref=task_pin,
            assignment_ref=assignment_pin, mandate_ref=mandate_pin,
            expected_generation=generation, as_of=request["as_of"],
            project_reader=readers["project_reader"], assignment_reader=assignment_reader,
            mandate_reader=readers["mandate_reader"], resource_reader=resource_reader,
            task_reader=readers.get("task_reader") if task_pin is not None else None,
            direction_context_reader=readers.get("direction_context_reader"),
        )
    except (OperatingBriefError, ResourceSyncError, ValueError, KeyError) as exc:
        return {
            "outcome": "unknown", "schema": schema, "assignment_ref": observed_ref,
            "adopted_resources": adopted_summary, "read_only": True, "writes": 0,
            "error": {"code": "operating_brief_preparation_failed", "message": str(exc)},
            "next_action": "refresh all project, task, assignment, mandate and adopted-resource pins before retrying",
        }
    return {
        "outcome": "prepared", "schema": schema,
        "assignment_ref": observed_ref, "adopted_resources": adopted_summary,
        "local_bundle": _local_bundle_state(staged_bundle_context),
        "operating_brief": prepared,
        "delivery_state": "prepared_not_delivered",
        "read_only": True, "writes": 0, "dispatch": False, "launch": False,
    }


def _ref_identity(ref: Any) -> tuple[Any, Any, Any]:
    if not isinstance(ref, Mapping):
        return None, None, None
    return ref.get("authority"), ref.get("kind"), ref.get("id")


def _task_detail(portfolio: Any, *, actor: str, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any], limit: int) -> dict[str, Any]:
    cursor = None
    seen: set[str] = set()
    pages_read = 0
    last: dict[str, Any] = {}
    for _ in range(10000):
        last = portfolio.list_work(actor=actor, view="all", project_ref=project_ref, cursor=cursor, limit=limit)
        pages_read += 1
        if last.get("outcome") not in {"listed", "partial"}:
            return last
        pagination = last.get("pagination", {}) if isinstance(last.get("pagination"), Mapping) else {}
        wanted = _ref_identity(task_ref)
        found = next((item for item in last.get("items", ()) if _ref_identity(item.get("ref")) == wanted), None)
        if found is not None:
            actual_ref = found.get("ref")
            if task_ref.get("revision") and isinstance(actual_ref, Mapping) and task_ref["revision"] != actual_ref.get("revision"):
                return {
                    "outcome": "conflict",
                    "schema": "otto.portfolio-task-detail.v1",
                    "project_ref": project_ref,
                    "requested_task_ref": task_ref,
                    "current_task_ref": actual_ref,
                    "reason": "requested task revision is stale",
                    "pagination": {**pagination, "pages_read": pages_read, "scan_complete": pagination.get("has_more") is not True},
                    "read_only": True,
                }
            return {
                "outcome": "read",
                "schema": "otto.portfolio-task-detail.v1",
                "project_ref": project_ref,
                "task": found,
                "project_overview": last.get("projects", []),
                "counts": last.get("counts", {}),
                "disjoint_counts": last.get("disjoint_counts", {}),
                "denominators": last.get("denominators", {}),
                "pagination": {**pagination, "pages_read": pages_read, "scan_complete": pagination.get("has_more") is not True},
                "read_only": True,
                "dispatch": False,
                "launch": False,
            }
        if pagination.get("has_more") is not True:
            if last.get("outcome") == "partial":
                return {
                    "outcome": "partial",
                    "schema": "otto.portfolio-task-detail.v1",
                    "project_ref": project_ref,
                    "task": None,
                    "pagination": {**pagination, "pages_read": pages_read, "scan_complete": False},
                    "unknown": last.get("unknown", {}),
                    "error": {"code": "task_lookup_incomplete", "message": "owner returned a partial task inventory; inspect unknown/project_read_errors before concluding the task is absent"},
                    "read_only": True,
                }
            return {
                "outcome": "not_found",
                "schema": "otto.portfolio-task-detail.v1",
                "project_ref": project_ref,
                "requested_task_ref": task_ref,
                "count": last.get("count"),
                "denominators": last.get("denominators", {}),
                "pagination": {**pagination, "pages_read": pages_read, "scan_complete": True},
                "read_only": True,
                "error": {"code": "task_not_found_in_project", "message": "task ref is not in this project's complete owner-backed inventory; refresh project/task refs or check project scope"},
            }
        next_cursor = pagination.get("cursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor or next_cursor in seen:
            return {
                "outcome": "unknown",
                "schema": "otto.portfolio-task-detail.v1",
                "project_ref": project_ref,
                "task": None,
                "pagination": {**pagination, "pages_read": pages_read, "scan_complete": False},
                "error": {"code": "task_pagination_stalled", "message": "owner pagination did not advance; retry from the project overview after inspecting the owner response"},
                "read_only": True,
            }
        seen.add(next_cursor)
        cursor = next_cursor
    return {
        "outcome": "unknown",
        "schema": "otto.portfolio-task-detail.v1",
        "project_ref": project_ref,
        "task": None,
        "pagination": {"pages_read": pages_read, "scan_complete": False, "cursor": cursor},
        "error": {"code": "task_page_limit_exceeded", "message": "task lookup reached 10000 pages without a complete owner inventory"},
        "read_only": True,
    }


def _render_text(result: Any) -> str:
    if not isinstance(result, Mapping):
        return str(result)
    outcome = str(result.get("outcome", "unknown"))
    schema = result.get("schema")
    headline = outcome.upper() + (f" — {schema}" if schema else "")
    lines = [headline]
    error = result.get("error")
    if isinstance(error, Mapping):
        reason = error.get("message") or error.get("code")
        if reason:
            lines.append(f"Reason: {reason}")
    pagination = result.get("pagination")
    if isinstance(pagination, Mapping):
        lines.append(
            "Pagination: "
            f"offset={pagination.get('offset', 'n/a')} "
            f"has_more={pagination.get('has_more', 'n/a')} "
            f"cursor={pagination.get('cursor', None)!r}"
        )
    if result.get("denominators"):
        lines.append("Denominators: " + json.dumps(result["denominators"], sort_keys=True))
    if isinstance(result.get("count"), int):
        lines.append(f"Count: {result['count']}")
    if isinstance(result.get("view"), str):
        lines.append(f"View: {result['view']}")
    if result.get("read_only") is True:
        lines.append(
            "Read-only: true "
            f"writes={result.get('writes', 'n/a')} "
            f"dispatch={result.get('dispatch', 'n/a')} "
            f"launch={result.get('launch', 'n/a')}"
        )
    task_rows = result.get("items")
    if not isinstance(task_rows, (list, tuple)):
        task = result.get("task")
        task_rows = (task,) if isinstance(task, Mapping) else ()
    task_rows = [
        row for row in task_rows
        if isinstance(row, Mapping)
        and isinstance(row.get("ref"), Mapping)
        and row["ref"].get("kind") == "work.task"
        and "derived_classification" in row
    ]
    if task_rows:
        def compact(value: Any) -> str:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

        lines.append(f"Task state rows (page): {len(task_rows)}")
        for row in task_rows:
            aliases = row.get("source_aliases", ())
            label = aliases[0] if isinstance(aliases, (list, tuple)) and aliases else row["ref"].get("id")
            lines.append(
                f"- task={compact(row.get('ref'))} alias={compact(label)} title={compact(row.get('title'))} "
                f"classification={compact(row.get('derived_classification'))} "
                f"views={compact(row.get('view_memberships', ()))} "
                f"lifecycle={compact(row.get('lifecycle', {'state': 'unknown', 'value': None}))} "
                f"readiness={compact(row.get('readiness', {'state': 'unknown', 'value': None}))} "
                f"applicability={compact(row.get('applicability', {'state': 'unknown'}))} "
                f"observation={compact(row.get('observation', {'state': 'unknown', 'known': False}))} "
                f"dependency_reasons={compact(row.get('dependency_reasons', ()))} "
                f"owner={compact(row.get('owner', {'state': 'unknown', 'value': None}))} "
                f"owner_assignments={compact(row.get('owner_assignments', ()))} "
                f"evidence_refs={compact(row.get('evidence_refs', ()))} "
                f"result_refs={compact(row.get('result_refs', ()))} "
                f"accepted_current_evidence={compact(row.get('accepted_current_evidence', {'state': 'unknown', 'value': None}))}"
            )
    lines.append("Canonical response:")
    lines.append(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return "\n".join(lines)


def _emit(result: Any, output_format: str) -> None:
    if output_format == "text":
        print(_render_text(result))
    else:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))


def main(
    argv: Optional[list[str]] = None,
    *,
    portfolio: Optional[OttoPortfolio] = None,
    document_operations: Any = None,
    assessment: Any = None,
    completion_owner: Any = None,
    operating_brief_readers: Any = None,
    operating_brief_reader_factory: Any = None,
    staged_bundle_context: Any = None,
    bound_actor: Optional[str] = None,
    direction_operations: Any = None,
    observability_views: Any = None,
    observability_grant: Any = None,
    vision_operations: Any = None,
    status_session: Any = None,
    labs: Any = None,
    editor_host: Any = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if bound_actor is not None:
        if not isinstance(bound_actor, str) or not bound_actor.strip():
            raise ValueError("bound_actor must be non-blank text")
        actor_selector = getattr(args, "actor", None)
        if actor_selector is not None and actor_selector != bound_actor:
            result = {
                "outcome": "denied", "schema": "otto.cli-error.v1", "read_only": True,
                "error": {
                    "code": "bound_actor_mismatch",
                    "message": "actor selector does not match the host-bound owner actor",
                },
            }
            _emit(result, getattr(args, "format", "json"))
            return _exit_code(result)
    portfolio_injected = portfolio is not None
    if portfolio is None:
        portfolio = OttoPortfolio()
    try:
        if args.command == "help":
            result: Any = {
                **portfolio.help(),
                "role_work_contract": {
                    "BASE": "one adopted role resource and version",
                    "CUSTOM": "bounded owner-adopted mandate or assignment",
                    "CURRENT_STATE": "generated from fresh canonical owner reads; facts do not grant authority",
                    "manager": "continues authorized ready work, accepts evidence, handles ordinary corrections, and avoids routine root pings",
                    "native_closure": "unsupported unless the host returns exact closure evidence",
                },
                "canonical_public_paths": {
                    "execution_application": "PortfolioOwnerBootstrap.execution_application -> ExecutionApplication",
                    "manager_current_work": "OttoPortfolio.read_work",
                    "project_inventory": "OttoPortfolio.list_projects",
                    "task_filters": "OttoPortfolio.list_work",
                    "recovery_discovery": "OttoPortfolio.find_and_continue (read-only; project or retained checkout/session locator required)",
                    "project_onboarding": "python -m otto.portfolio.cli onboarding {create,find,reopen} (title+brief, DAT brief membership, EDT projection)",
                    "project_onboarding_guide": "src/otto/portfolio/skills/project-onboarding.md (authenticated issued caller, inert authoring, canonical queue, reviewed activation and recovery)",
                    "authenticated_onboarding_entry": "python -m otto.portfolio.onboarding_bound_cli --connection HOST_ISSUED_PRIVATE_DESCRIPTOR --request-json JSON; no actor or Store selection",
                    "onboarding_authentication": "cli.main requires a host-injected portfolio/bound_actor; standalone generic portfolio CLI does not authenticate; production protected owner-authoring is a separate admitted route",
                    "current_role_discovery": "current role tool_entrypoint, exact installed whoami/effective-context and current setup/help destination",
                    "superseded_guidance": "historical proposal/folder/transition examples are evidence; use the selected onboarding guide and current owner reads",
                    "events_operator_views": "python -m otto.portfolio.cli events {overview,timeline,agents,tasks-reviews,blockers,usage,recovery} --project-ref REF_JSON",
                    "events_operator_detail": "python -m otto.portfolio.cli events detail --facet-id FACET_ID --snapshot SNAPSHOT_JSON",
                    "skills_index": "src/otto/portfolio/skills/SKILL.md (maintained Otto skill index)",
                    "recovery_skill": "src/otto/portfolio/skills/recovery/SKILL.md (inspect/resume/reassign/verify, including reminders)",
                    "task_detail": "python -m otto.portfolio.cli task --project-ref REF_JSON --task-ref REF_JSON",
                    "document_reader": "ProjectDocumentReader.list_documents/read_document/list_revisions",
                    "document_navigation": "ProjectDocumentOperations.search_documents/resolve_relative_link/export_bundle",
                    "assessment_coverage": "OttoAssessment.coverage",
                    "completion_gate": "ResponsibilityAssignments.completion_blockers",
                    "task_completion": "OttoPortfolio.complete_task -> existing work owner completion guard",
                    "project_advisor_pair": "OttoPortfolio.pair_project_advisor -> existing ProjectSheet and ResponsibilityAssignments ports",
                    "operating_brief": "resolve_assignment_attachments -> prepare_canonical_operating_brief",
                    "direction": "DirectionSurface read/effective-context/whoami/initial-bind/draft/update/history/overview",
                    "observability_views": "ObservabilityViews over the injected authenticated project-history reader",
                    "vision": "python -m otto.portfolio.cli vision --request-json '{\"command\":\"vision\",\"operation\":\"help\",\"arguments\":{}}' (requires injected VisionCommandSurface)",
                },
                "integration_state": {
                    "assessment_coverage": "available only when the accepted OttoAssessment facade is injected",
                    "completion_gate": "available only when the existing owner read port is injected; returned blockers are the owner predicate",
                    "task_completion": "available only through an explicitly injected owner-bound OttoPortfolio and full current request pins",
                    "project_advisor_pair": "available only through an explicitly injected owner-bound OttoPortfolio and exact current manager pins",
                    "operating_brief": "available only through injected canonical owner readers; local staged bundles are never treated as adopted resources",
                    "vision": "available only through an explicitly injected authenticated VisionCommandSurface; selected resources and operation pins are returned by the surface",
                },
                "cli_scope": "owner-backed reads, inert title+brief onboarding, finite authenticated Vision author/query/context/checkpoint operations, guarded task completion, and execution help; no provider launch or scheduler command",
                "document_injection": "Supply the accepted ProjectDocumentOperations instance through cli.main(argv, document_operations=...).",
                "assessment_injection": "Supply the accepted OttoAssessment facade through cli.main(argv, assessment=...).",
                "completion_gate_injection": "Supply the existing ResponsibilityAssignments owner through cli.main(argv, completion_owner=...).",
                "operating_brief_injection": "Supply explicit canonical owner callbacks/readers through cli.main(argv, operating_brief_readers=...).",
                "direction_injection": "Supply the owner-issued DirectionSurface through cli.main(argv, direction_operations=...).",
                "observability_injection": "Supply the authenticated ObservabilityViews and grant through cli.main(argv, observability_views=..., observability_grant=...).",
            }
        elif args.command in {"request-help", "request-advice", "read-help", "respond-help", "resolve-help"}:
            project = _parse_ref(args.project_ref, "project_ref")
            loop = portfolio._issue_loop()
            if loop is None:
                result = _surface_unavailable("otto.help.v1", "issue_ports_unavailable", "Host must bind the owner IssueLoop and delivery ports")
            elif args.command == "read-help":
                result = (loop.recover_delivery(project_ref=project, delivery_id=args.delivery_id) if args.delivery_id
                          else portfolio.read_issues(project_ref=project))
            else:
                request = {"project_ref": project, "actor": args.actor, "request_id": args.request_key}
                if args.command == "respond-help":
                    request.update({field: getattr(args, field) for field in
                        ("issue_id", "authority_source", "response", "proposed_solution", "next_action")})
                    result = portfolio.respond_to_issue(**request)
                else:
                    request.update(assignment_ref=_parse_ref(args.assignment_ref, "assignment_ref"), generation=args.generation)
                    if args.command == "resolve-help":
                        request.update(issue_id=args.issue_id, evidence=args.evidence, next_action=args.next_action)
                        result = portfolio.resolve_help(**request)
                    else:
                        request.update({field: getattr(args, field) for field in
                            ("issue_key", "problem", "evidence", "impact", "requested_decision", "return_condition")})
                        result = (portfolio.request_help if args.command == "request-help" else portfolio.request_advice)(**request)
        elif args.command in {"onboarding", "draft"}:
            try:
                if args.onboarding_command == "create":
                    supporting_files = _parse_json(args.supporting_files, "supporting_files") if args.supporting_files else None
                    predecessor = _parse_ref(args.predecessor_ref, "predecessor_ref") if args.predecessor_ref else None
                    parameters = _parse_json(args.template_parameters, "template_parameters") if args.template_parameters else None
                    result = portfolio.create_draft(
                        actor=args.actor, request_id=args.request_id, title=args.title, brief=args.brief,
                        supporting_files=supporting_files, predecessor_ref=predecessor,
                        template=_parse_json_or_name(args.template, "template"),
                        template_parameters=parameters,
                    )
                elif args.onboarding_command == "find":
                    result = portfolio.find_draft(actor=args.actor, project_ref=_parse_ref(args.project_ref, "project_ref"))
                else:
                    result = portfolio.reopen_draft(
                        actor=args.actor, request_id=args.request_id,
                        project_ref=_parse_ref(args.project_ref, "project_ref"),
                    )
            except (json.JSONDecodeError, PortfolioError, TypeError, ValueError) as exc:
                result = _request_error(str(exc))
        elif args.command == "save":
            try:
                with open(args.file, encoding="utf-8") as handle:
                    document = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                result = _request_error(str(exc))
            else:
                result = portfolio.save_project(document, actor=args.actor, request_id=args.request_id)
        elif args.command == "show":
            if args.show_command == "project":
                result = show_project(portfolio, actor=args.actor,
                                      project_ref=_parse_ref(args.project_ref, "project_ref"), limit=args.limit)
            else:
                project_ref = _parse_ref(args.project_ref, "project_ref")
                task_ref = _parse_ref(args.task_ref, "task_ref")
                if project_ref.get("kind") != "work.project" or task_ref.get("kind") != "work.task":
                    result = _request_error("show task requires a work.project ref and work.task ref")
                else:
                    result = _task_detail(portfolio, actor=args.actor, project_ref=project_ref,
                                          task_ref=task_ref, limit=args.limit)
        elif args.command == "open":
            if editor_host is None:
                result = _surface_unavailable(
                    "otto.open.v1", "editor_host_unavailable",
                    "Inject the owner's DocumentEditorHost at cli.main(..., editor_host=...).",
                )
            else:
                try:
                    result = open_session(editor_host, args)
                except PermissionError as exc:
                    result = _request_error(str(exc), code="denied")
                except InvalidSessionError as exc:
                    result = _request_error(str(exc), code="session_not_open")
        elif args.command == "status":
            result = _status_command(args, status_session, labs)
        elif args.command == "create-pending":
            try:
                edit = json.loads(args.edit_json)
                result = portfolio.create_pending(actor=args.actor, request_id=args.request_id, edit=edit,
                                                  template=args.template, open_project=args.open_project)
            except (json.JSONDecodeError, PortfolioError) as exc:
                result = {"outcome": "error", "error": {"code": "invalid_request", "message": str(exc)}}
        elif args.command == "read":
            result = portfolio.read_pending(args.project_id, actor=args.actor)
        elif args.command == "list":
            result = portfolio.list_pending(actor=args.actor)
        elif args.command == "inventory":
            result = portfolio.manager_inventory(actor=args.actor)
        elif args.command == "projects":
            parent = _parse_ref(args.parent_ref, "parent_ref") if args.parent_ref else None
            result = portfolio.list_projects(actor=args.actor, parent_ref=parent,
                                             cursor=args.cursor, limit=args.limit)
        elif args.command == "find-and-continue":
            result = portfolio.find_and_continue(
                actor=args.actor,
                project_ref=_parse_ref(args.project_ref, "project_ref") if args.project_ref else None,
                checkout_ref=_parse_ref(args.checkout_ref, "checkout_ref") if args.checkout_ref else None,
                session_id=args.session_id, cursor=args.cursor, limit=args.limit,
            )
        elif args.command == "events":
            result = _events_command(args, observability_views, observability_grant)
        elif args.command in {"overview", "tasks"}:
            project_ref = _parse_ref(args.project_ref, "project_ref") if args.project_ref else None
            parent_ref = _parse_ref(args.parent_ref, "parent_ref") if args.command == "tasks" and args.parent_ref else None
            if args.command == "overview" and project_ref is None:
                result = _request_error("overview requires a canonical project_ref", code="project_ref_required")
            else:
                result = portfolio.list_work(
                    actor=args.actor, view=getattr(args, "view", "all"),
                    project_ref=project_ref, parent_ref=parent_ref,
                    cursor=getattr(args, "cursor", None), limit=args.limit,
                )
        elif args.command == "task":
            project_ref = _parse_ref(args.project_ref, "project_ref")
            task_ref = _parse_ref(args.task_ref, "task_ref")
            if project_ref.get("kind") != "work.project" or task_ref.get("kind") != "work.task":
                result = _request_error("task detail requires a work.project ref and work.task ref")
            else:
                result = _task_detail(
                    portfolio, actor=args.actor, project_ref=project_ref,
                    task_ref=task_ref, limit=args.limit,
                )
        elif args.command == "assessment-coverage":
            result = _assessment_coverage_command(args, assessment)
        elif args.command == "completion-gate":
            result = _completion_gate_command(args, completion_owner)
        elif args.command == "complete-task":
            result = _complete_task_command(
                args, portfolio, portfolio_injected=portfolio_injected, bound_actor=bound_actor,
            )
        elif args.command == "project-advisor-pair":
            result = portfolio.pair_project_advisor(
                _parse_ref(args.project_ref, "project_ref"),
                _parse_ref(args.manager_assignment_ref, "manager_assignment_ref"),
                actor=args.actor,
                request_id=args.request_id,
                manager_generation=args.manager_generation,
                advisor_principal=args.advisor_principal,
                pins=tuple(_parse_ref(value, "pin") for value in args.pin),
            )
        elif args.command == "operating-brief":
            result = _operating_brief_command(
                args, operating_brief_readers, staged_bundle_context,
                reader_factory=operating_brief_reader_factory,
            )
        elif args.command == "direction":
            result = _direction_command(args, direction_operations)
        elif args.command == "vision":
            result = _vision_command(args, vision_operations)
        else:
            result = _document_command(args, document_operations or getattr(portfolio, "document_operations", None))
    except (ValueError, PortfolioError) as exc:
        result = _request_error(str(exc))
    _emit(result, getattr(args, "format", "json"))
    return _exit_code(result)


def _status_command(args: argparse.Namespace, session: Any, labs: Any) -> dict[str, Any]:
    if session is None:
        return _surface_unavailable(
            "otto.portfolio-status.v1", "status_session_unavailable",
            "Inject the owner session at cli.main(..., status_session=...).",
        )
    from .status import portfolio_status
    selected = _parse_ref(args.portfolio_ref, "portfolio_ref") if args.portfolio_ref else None
    return portfolio_status(session, selected, labs=labs)


def _events_command(args: argparse.Namespace, views: Any, grant: Any) -> dict[str, Any]:
    if views is None:
        return _surface_unavailable(
            "otto.events.operator-view.v1", "observability_views_unavailable",
            "Inject the authenticated ObservabilityViews facade at cli.main(..., observability_views=...).",
        )
    projects = tuple(_parse_ref(value, "project_ref") for value in args.project_ref)
    if args.events_view == "detail":
        snapshot = _parse_json(args.snapshot, "snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError("snapshot must be a JSON object")
        return views.detail(
            args.facet_id, snapshot=snapshot, projects=projects, grant=grant, actor=args.actor,
            max_bytes=args.max_detail_bytes,
        )
    active_during = None
    if args.active_during is not None:
        active_during = _parse_json(args.active_during, "active_during")
        if not isinstance(active_during, list) or len(active_during) != 2:
            raise ValueError("active_during must be a JSON [from,to) pair")
    snapshot = None if args.snapshot is None else _parse_json(args.snapshot, "snapshot")
    if snapshot is not None and not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a JSON object")
    filters = None if args.filters is None else _parse_json(args.filters, "filters")
    if filters is not None and not isinstance(filters, Mapping):
        raise ValueError("filters must be a JSON object")
    return views.read(
        args.events_view, projects=projects, from_at=args.from_at, to_at=args.to_at,
        timezone_name=args.timezone_name, active_during=active_during, limit=args.limit,
        cursor=args.cursor, snapshot=snapshot, grant=grant, actor=args.actor,
        filters=filters,
    )


def _direction_command(args: argparse.Namespace, operations: Any) -> dict[str, Any]:
    if operations is None:
        return _surface_unavailable(
            "otto.direction-surface.v1", "direction_operations_unavailable",
            "Inject the owner-issued DirectionSurface at cli.main(..., direction_operations=...).",
        )
    command = args.direction_command
    actor = args.actor
    if command == "read":
        kwargs = {"subject": _parse_ref(args.subject_ref, "subject_ref"), "actor": actor}
        if args.assignment_ref:
            kwargs["assignment_ref"] = _parse_ref(args.assignment_ref, "assignment_ref")
        if args.generation is not None:
            kwargs["generation"] = args.generation
        return operations.read(**kwargs)
    if command == "effective-context":
        return operations.effective_context(
            assignment_ref=_parse_ref(args.assignment_ref, "assignment_ref"),
            generation=args.generation, project_ref=_parse_ref(args.project_ref, "project_ref"),
            task_ref=_parse_ref(args.task_ref, "task_ref") if args.task_ref else None, actor=actor)
    if command == "whoami":
        return operations.whoami(actor=actor)
    if command == "initial-bind":
        return operations.initial_bind(
            _parse_ref(args.subject_ref, "subject_ref"), _parse_ref(args.document_ref, "document_ref"),
            logical_request_key=args.request_key, actor=actor)
    if command == "draft":
        content = _parse_json(args.content, "content")
        if not isinstance(content, Mapping):
            raise ValueError("content must be a JSON object")
        return operations.draft(_parse_ref(args.subject_ref, "subject_ref"), content,
                                logical_request_key=args.request_key,
                                expected_revision=args.expected_revision, actor=actor)
    if command == "update":
        content = None if args.content is None else _parse_json(args.content, "content")
        if content is not None and not isinstance(content, Mapping):
            raise ValueError("content must be a JSON object")
        resources = None if args.assignment_resources is None else _parse_json(args.assignment_resources, "assignment_resources")
        return operations.update(
            _parse_ref(args.subject_ref, "subject_ref"),
            _parse_ref(args.revision_ref, "revision_ref", pinned=True) if args.revision_ref else None,
            content=content,
            expected_binding_ref=_parse_ref(args.binding_ref, "binding_ref", pinned=True) if args.binding_ref else None,
            logical_request_key=args.request_key, expected_revision=args.expected_revision,
            assignment_ref=_parse_ref(args.assignment_ref, "assignment_ref") if args.assignment_ref else None,
            expected_generation=args.generation, assignment_resources=resources,
            # Assignment actor is host-bound and is intentionally not a CLI
            # identity selector; absent binding yields a recoverable partial.
            assignment_actor=None,
            expected_assignment_guard_ref=_parse_ref(args.assignment_guard_ref, "assignment_guard_ref", pinned=True) if args.assignment_guard_ref else None,
            actor=actor)
    if command == "history":
        return operations.history(_parse_ref(args.subject_ref, "subject_ref"), actor=actor)
    if command == "overview":
        subjects = None if args.subjects is None else _parse_json(args.subjects, "subjects")
        if subjects is not None and not isinstance(subjects, list):
            raise ValueError("subjects must be a JSON array")
        return operations.overview(subjects, actor=actor, limit=args.limit, cursor=args.cursor)
    return _request_error(f"unsupported direction command: {command}", code="unsupported_command")


def _vision_command(args: argparse.Namespace, operations: Any) -> dict[str, Any]:
    if operations is None or not callable(getattr(operations, "dispatch", None)):
        return _surface_unavailable(
            "vision.help.v1", "vision_operations_unavailable",
            "Inject the authenticated VisionCommandSurface at cli.main(..., vision_operations=...).",
        )
    request = _parse_json(args.request_json, "request_json")
    if not isinstance(request, Mapping):
        raise ValueError("request_json must be a JSON object")
    return operations.dispatch(request)


def _document_command(args: argparse.Namespace, document_operations: Any) -> dict[str, Any]:
    if document_operations is None:
        return _docs_unavailable()
    reader = getattr(document_operations, "document_reader", None)
    if reader is None:
        return _docs_unavailable()
    project = _parse_ref(args.project_ref, "project_ref")
    roles: Sequence[str] = tuple(getattr(args, "role", ()) or ())
    task_refs = tuple(_parse_ref(value, "task_ref") for value in (getattr(args, "task_ref", ()) or ()))
    command = args.document_command
    if command == "metadata":
        return reader.list_metadata(project, actor=args.actor, roles=roles, task_refs=task_refs,
            exact_role=args.exact_role, representation=args.representation, format=args.content_format,
            cursor=args.cursor, limit=args.limit)
    if command == "list":
        return reader.list_documents(project, actor=args.actor, roles=roles, task_refs=task_refs or None)
    if command == "search":
        # Each call scans one bounded window; page through the whole project.
        cursor, combined = 0, None
        while cursor is not None:
            page = document_operations.search_documents(
                project, args.query, actor=args.actor, roles=roles, task_refs=task_refs or None, limit=args.limit,
                cursor=cursor,
            )
            if page.get("outcome") != "listed":
                return page
            if combined is None:
                combined = dict(page)
            else:
                combined["matches"] = combined["matches"] + page["matches"]
            cursor = page.get("next_cursor")
        combined["matches"] = sorted(combined["matches"], key=lambda row: (
            row["document_ref"].get("id", ""), row["revision_ref"].get("revision", "")))
        combined["truncated"] = len(combined["matches"]) > args.limit
        combined["matches"] = combined["matches"][:args.limit]
        combined["count"] = len(combined["matches"])
        combined.pop("next_cursor", None)
        combined.pop("scanned", None)
        return combined
    if command == "read":
        ref = _parse_ref(args.document_ref, "document_ref", pinned=True)
        return reader.read_document(project, ref, actor=args.actor, roles=roles, task_refs=task_refs or None)
    if command == "link":
        source = _parse_ref(args.source_ref, "source_ref")
        return document_operations.resolve_relative_link(
            project, source, args.href, actor=args.actor, source_path=args.source_path,
            roles=roles, task_refs=task_refs or None,
        )
    if command == "history":
        document = _parse_ref(args.document_ref, "document_ref")
        start = _parse_ref(args.start_revision_ref, "start_revision_ref", pinned=True) if args.start_revision_ref else None
        return reader.list_revisions(
            project, document, actor=args.actor, roles=roles, task_refs=task_refs or None,
            limit=args.limit, start_revision_ref=start,
        )
    if command == "bundle":
        refs = _parse_json(args.document_refs, "document_refs")
        if not isinstance(refs, list):
            raise ValueError("document_refs must be a JSON array")
        refs = [_parse_ref(json.dumps(item), f"document_refs[{index}]") for index, item in enumerate(refs)]
        from .document_navigation import export_bundle_pages
        return export_bundle_pages(document_operations, project, refs, actor=args.actor, roles=roles,
                                   task_refs=task_refs or None)
    if command == "diff":
        document = _parse_ref(args.document_ref, "document_ref")
        older = _parse_ref(args.older_revision_ref, "older_revision_ref", pinned=True)
        newer = _parse_ref(args.newer_revision_ref, "newer_revision_ref", pinned=True)
        return document_operations.diff_revisions(
            project, document, older, newer, actor=args.actor, roles=roles, task_refs=task_refs or None,
        )
    return _request_error(f"unsupported document command: {command}", code="unsupported_command")


def _exit_code(result: Any) -> int:
    """Keep machine-readable output while surfacing incomplete/rejected states."""
    if not isinstance(result, Mapping):
        return 1
    outcome = result.get("outcome")
    if outcome in {"unsupported", "unavailable"}:
        return 3
    if outcome in {"error", "failed"}:
        return 1
    if outcome in {"unknown", "partial", "conflict", "denied", "rejected", "not_found", "blocked", "pending", "held"}:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
