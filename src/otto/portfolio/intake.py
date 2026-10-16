"""Public OTT-03 intake facade.

This module validates the small product contract and delegates all durable
work to a supplied canonical Herzchen operation port.  The port is expected to
be the accepted work-record adapter (or a neutral fixture implementing the
same public call shape):

``execute(operation, payload, request_id=..., actor=...) -> Mapping``
``read(operation, payload, actor=...) -> Mapping``

No Otto-owned store is provided as a fallback.  An absent port is reported as
an explicit unsupported boundary so callers cannot mistake a local no-op for
durable work.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping, Optional, Protocol, Sequence, TypedDict

from .herzchen_binding import FiniteWorkOperations
from .inbox import WorkViewCursorError, decode_work_view_cursor, encode_work_view_cursor
from .issue_loop import IssueLoop
from .resource_sync import ResourceSyncError, normalize_role_attachments


ADMISSION_CHOICES = ("admit", "investigate", "merge", "park", "drop")
ONBOARDING_SCHEMA = "otto.portfolio.onboarding.v1"
ONBOARDING_BRIEF_PATH = "brief.md"
EDITABLE_FIELDS = frozenset(
    {
        "title",
        "outcome",
        "curator",
        "why_pending",
        "documents",
        "links",
        "revisit",
        "metadata",
        "custom",
    }
)
_PROTECTED_FIELDS = frozenset(
    {
        "id",
        "kind",
        "authority",
        "revision",
        "lifecycle",
        "state",
        "readiness",
        "manager",
        "manager_assignment",
        "executor",
        "parent",
        "tasklist",
        "tasks",
        "allowance",
        "budget",
        "session",
        "accepted_result",
        "dispatch",
        "admitted",
    }
)


class PortfolioError(ValueError):
    """A rejected public request that must have no canonical side effect."""


class WorkOperations(Protocol):
    """The public Herzchen work-operation port consumed by Otto."""

    def execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        ...

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        ...


class ProjectionValue(TypedDict):
    """A derived value with explicit provenance and uncertainty."""

    state: str
    value: Any
    source_refs: list[dict[str, Any]]
    reason: Optional[str]


class CurrentWork(TypedDict):
    """Typed read-only current-work projection over owner records."""

    outcome: str
    schema: str
    current_refs: dict[str, Any]
    scope: dict[str, Any]
    facts: dict[str, ProjectionValue]
    dependencies: list[dict[str, Any]]
    consumption: ProjectionValue
    closure: ProjectionValue
    unknown: list[Any]
    source_refs: dict[str, Any]
    read_side_effects: bool
    dispatch: bool
    launch: bool


def _json_copy(value: Any, *, field: str = "value") -> Any:
    """Return JSON data without allowing opaque Python objects into records."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise PortfolioError(f"{field} must be JSON-compatible") from exc


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or "\x00" in value:
        requirement = "a non-blank" if required else "text"
        raise PortfolioError(f"{field} must be {requirement} value")
    return value.strip() if required else value


def _ref(value: Any, field: str = "project_ref") -> dict[str, Any]:
    if isinstance(value, str):
        return {"id": _text(value, field)}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if not isinstance(value, Mapping):
        raise PortfolioError(f"{field} must be a durable reference object")
    result = _json_copy(dict(value), field=field)
    if not isinstance(result.get("id"), str) or not result["id"].strip():
        raise PortfolioError(f"{field}.id must be non-blank")
    return result


def _identity_ref(value: Any) -> Optional[tuple[str, str, str]]:
    ref = _ref(value) if isinstance(value, (str, Mapping)) or callable(getattr(value, "to_dict", None)) else None
    if ref is None or not all(isinstance(ref.get(key), str) and ref[key].strip() for key in ("authority", "kind", "id")):
        return None
    return ref["authority"], ref["kind"], ref["id"]


def _digest_json(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _onboarding_files(brief: str, supporting_files: Optional[Mapping[str, str]]) -> dict[str, str]:
    """Validate the small title-and-brief file set with the existing folder rules."""

    from .project_folder import validate_operation_files

    files = {ONBOARDING_BRIEF_PATH: brief}
    if supporting_files is not None:
        if not isinstance(supporting_files, Mapping):
            raise PortfolioError("supporting_files must be an object of relative paths to UTF-8 text")
        for path, content in supporting_files.items():
            if path == ONBOARDING_BRIEF_PATH:
                raise PortfolioError("supporting_files cannot replace the canonical brief.md")
            files[path] = content
    try:
        return validate_operation_files(files)
    except (TypeError, ValueError) as exc:
        raise PortfolioError(str(exc)) from exc


def _onboarding_locator(project_ref: Mapping[str, Any]) -> str:
    """Return a stable logical locator; EDT checkout paths are intentionally excluded."""

    authority = project_ref.get("authority")
    project_id = project_ref.get("id")
    if not isinstance(authority, str) or not authority.strip() or not isinstance(project_id, str) or not project_id.strip():
        raise PortfolioError("project_ref must contain authority and id for a stable workspace locator")
    return f"otto://{authority}/work.project/{project_id}"


def _onboarding_effects() -> dict[str, Any]:
    return {
        "lifecycle": "pending",
        "tasks": [],
        "roles": [],
        "pools": [],
        "schedules": [],
        "provider_calls": 0,
        "dispatch": False,
        "activation": False,
    }


def _edit(value: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PortfolioError("edit must be an object")
    result = _json_copy(dict(value), field="edit")
    if not isinstance(result, dict):
        raise PortfolioError("edit must be an object")
    for key in result:
        if not isinstance(key, str) or not key.strip():
            raise PortfolioError("edit field names must be non-blank text")
        if key in _PROTECTED_FIELDS:
            raise PortfolioError(f"protected field cannot be edited: {key}")
    for key in ("title", "outcome", "curator", "why_pending"):
        if key in result and not isinstance(result[key], str):
            raise PortfolioError(f"{key} must be text")
    return result


def _result(value: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "outcome": "error",
            "error": {"code": "malformed_canonical_result", "message": f"{operation} returned a non-object"},
        }
    return _json_copy(dict(value), field=f"{operation} result")


def unavailable_operations() -> "UnavailableWorkOperations":
    """Create an explicit no-binding port for CLI/readiness diagnostics."""

    return UnavailableWorkOperations()


class UnavailableWorkOperations:
    """No-op boundary used when the accepted Herzchen work binding is absent."""

    def execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        return {
            "outcome": "unavailable",
            "operation": operation,
            "error": {
                "code": "canonical_work_port_unavailable",
                "message": "accepted Herzchen work operations are not bound in this environment",
            },
        }

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        return self.execute(operation, payload, request_id="read-only", actor=actor)


class HerzchenWorkOperations(FiniteWorkOperations):
    """Finite accepted Herzchen command/read adapter consumed by Otto."""

    def __init__(
        self,
        *,
        port: Any,
        reader: Any,
        binding: Any,
        sheet_port: Any = None,
        content_port: Any = None,
        assignments_port: Any = None,
        authoring_port: Any = None,
        create_open_port: Any = None,
    ) -> None:
        from .herzchen_binding import HerzchenBindingConfig

        if not isinstance(binding, HerzchenBindingConfig):
            raise TypeError("binding must be HerzchenBindingConfig")
        super().__init__(
            port=port,
            reader=reader,
            binding=binding,
            sheet_port=sheet_port,
            content_port=content_port,
            assignments_port=assignments_port,
            authoring_port=authoring_port,
            create_open_port=create_open_port,
        )


class OttoPortfolio:
    """Manager-facing OTT-03 API over canonical Herzchen work records."""

    def __init__(self, operations: Optional[WorkOperations] = None, *, issue_loop: Optional[IssueLoop] = None,
                 document_operations: Any = None, due_port: Any = None,
                 occurrence_reader: Any = None) -> None:
        self.operations: WorkOperations = operations or unavailable_operations()
        self.__issue_loop = issue_loop
        self.document_operations = document_operations
        self.due_port = due_port
        self.occurrence_reader = occurrence_reader

    def _issue_loop(self) -> Optional[IssueLoop]:
        return self.__issue_loop

    def submit_checkin(self, **request: Any) -> dict[str, Any]:
        """Submit an occurrence-fenced manager check-in through AP-3 ports."""
        loop = self._issue_loop()
        if loop is None:
            return {"outcome": "unavailable", "operation": "work.manager.checkin",
                    "error": {"code": "checkin_ports_unavailable",
                              "message": "owner-backed assignment and DueRecord ports are not bound"}}
        return loop.submit_checkin(**request)

    def submit_issue(self, **request: Any) -> dict[str, Any]:
        loop = self._issue_loop()
        if loop is None:
            return {"outcome": "unavailable", "operation": "work.issue.submit",
                    "error": {"code": "issue_ports_unavailable",
                              "message": "owner-backed assignment and supervision ports are not bound"}}
        return loop.submit_issue(**request)

    def respond_to_issue(self, **request: Any) -> dict[str, Any]:
        loop = self._issue_loop()
        if loop is None:
            return {"outcome": "unavailable", "operation": "work.issue.respond",
                    "error": {"code": "issue_ports_unavailable",
                              "message": "owner-backed assignment and supervision ports are not bound"}}
        return loop.respond_to_issue(**request)

    def record_issue_outcome(self, **request: Any) -> dict[str, Any]:
        loop = self._issue_loop()
        if loop is None:
            return {"outcome": "unavailable", "operation": "work.issue.outcome",
                    "error": {"code": "issue_ports_unavailable",
                              "message": "owner-backed assignment and supervision ports are not bound"}}
        return loop.record_issue_outcome(**request)

    def read_issues(self, *, project_ref: Any) -> dict[str, Any]:
        loop = self._issue_loop()
        if loop is None:
            return {"outcome": "unavailable", "operation": "work.issue.read",
                    "issues": [], "read_side_effects": False}
        return loop.read_issues(project_ref=project_ref)

    def find_and_continue(self, *, actor: str, project_ref: Any = None,
                          checkout_ref: Any = None, session_id: Optional[str] = None,
                          cursor: Optional[str] = None, limit: int = 25,
                          native_observer: Any = None) -> dict[str, Any]:
        """Read one bounded recovery join through existing owner records.

        This is intentionally a read projection.  It reports the existing
        resume/replacement routes after custody resolution but never invokes
        them, selects one of multiple matches, or inspects arbitrary paths.
        """
        from .recovery_discovery import BoundedRecoveryDiscovery

        due_port = self.due_port
        if due_port is None:
            readers = getattr(self.__issue_loop, "readers", None)
            due_port = getattr(readers, "due_port", None)
        reader = BoundedRecoveryDiscovery(
            operations=self.operations,
            document_operations=self.document_operations,
            due_port=due_port,
            occurrence_reader=self.occurrence_reader,
        )
        return reader.read(actor=actor, project_ref=project_ref, checkout_ref=checkout_ref,
                           session_id=session_id, cursor=cursor, limit=limit,
                           native_observer=native_observer)

    recovery_inventory = find_and_continue
    read_recovery = find_and_continue

    def request_help(self, **request: Any) -> dict[str, Any]:
        return self.submit_issue(**request, purpose="operational_help")

    def request_advice(self, **request: Any) -> dict[str, Any]:
        return self.submit_issue(**request, purpose="advice")

    def resolve_help(self, **request: Any) -> dict[str, Any]:
        return self.record_issue_outcome(**request, disposition="resolved")

    @staticmethod
    def help() -> dict[str, Any]:
        return {
            "outcome": "available",
            "schema": "otto.portfolio-help.v1",
            "surface": "otto.portfolio",
            "purpose": "capture and explicitly admit pending projects through canonical work operations",
            "bootstrap": {
                "owner": "PortfolioOwnerBootstrap(store, binding=HerzchenBindingConfig(authority, credential_ref), owner_actor=actor)",
                "consumer": "OttoPortfolio(owner.consumer_operations())",
                "required_owner_registration": ["register_work(store)", "content.domain_contribution()", "register_authoring(store)"],
                "consumer_boundary": "finite serialized operations and reader only; no Store, DomainHandler, database path, SQL, callback, or generic writer",
                "restart": "close the owner Store and reopen it through the same owner bootstrap before restart/read evidence",
                "typed_task_batch": "use the finite operations.sheet_port.apply(project_ref, {tasks: [...]}, logical_request_key=..., actor=operations.binding.authenticated_actor(actor), base_revision=project_ref['revision']); read its returned project with batch.project.ref.to_dict()",
                "protected_pending_fields": "edit_pending rejects protected fields; a tasks-only edit authors inert pending tasks through the typed route; documents use their typed ports",
                "admission_frame": "admit requires non-blank outcome, recipient, route, and authority text; records a decision without launching, dispatching, reserving budget, or creating a session",
                "public_journey_example": "profiles/otto/ott06-public-journey.py contains a complete create/edit/read/replay/task-batch/admit/close-open/reopen sequence with every actor and request_id argument",
            },
            "operations": {
                "create_pending": "create a pending project; a qualified owner binding uses atomic default-orchestrator placement",
                "create_with_default_orchestrator": "explicitly require the owner-backed atomic default-orchestrator placement route",
                "create_and_open": "create_pending with open requested, using the blank starter by default or a selected template resource",
                "onboarding": "title plus brief create/find/reopen over pending Work, DAT brief membership and an EDT projection; stable project locator, no execution effects",
                "onboarding_required": "title and brief",
                "onboarding_optional": "supporting UTF-8 files, an existing predecessor reference, and an owner-adopted template with parameters",
                "onboarding_next_action": "reopen the stable project locator for EDT editing, then keep exploration, plan, and review as documents",
                "onboarding_guide": "src/otto/portfolio/skills/project-onboarding.md; installed title-plus-brief route, cold discovery journey, preflight and stale-document boundaries",
                "cold_discovery": "start at the installed help surface, use the exact role tool_entrypoint and owner binding, and never copy controller scripts or open Store",
                "current_role_discovery": "use the delivered role introduction plus whoami/effective-context when supported; read actual model/resource selection separately",
                "manager_root_discovery": "use the installed tool_entrypoint operating-setup --operation read and read-help for the current authenticated destination; missing or host-only routing stays explicit",
                "recovery_guidance": "src/otto/portfolio/skills/recovery/SKILL.md; reconcile the original handle before resume and preserve unknown effects",
                "setup_guidance": "docs/operating-setup-and-help.md; setup read is distinct from activation, dispatch and operational-help delivery",
                "closeout_guidance": "docs/manager-journey-commands.md; finish-project and project-lifecycle-read are distinct from transport success or review PASS",
                "superseded_guidance": "historical queued-transition/proposal/folder-format pages and controller-specific examples are retained evidence, not current route or queue authority",
                "preparation_preflight": "before effects resolve canonical scope/_digest, one actual runnable configuration, original candidate/source/evidence bindings, unique backup path and exact missing-stage resume; preserve malformed/refused proposals and immutable verdicts",
                "artifact_read_limit": "installed read-artifact accepts a bounded 1..4096-byte range; empty inventory is unavailable evidence, not success",
                "create_document": "create a typed canonical content document for a pending project",
                "link_document": "link a typed canonical document association to a project",
                "read_pending": "read one durable project reference",
                "list_pending": "list pending work records",
                "manager_inventory": "read-only project-scoped manager and native observation inventory",
                "edit_pending": "apply a validated sparse edit, preserving unknown fields",
                "reopen": "reopen(project_ref, actor=..., request_id=...); returns the same durable identity and exact-replays the same request without a new event",
                "revisit": "record attention/readiness only",
                "satisfied_prerequisite": "record attention/readiness only for a dependency change",
                "admit": "manager decision: admit, investigate, merge, park, or drop",
                "assign_roles": "bind one parent, optional orchestrator, one accountable manager, and bounded executor(s); role-keyed adopted resources are pinned through the canonical assignment port",
                "pair_project_advisor": "read or create the one project-scoped advisor assignment for an exact current manager; no host session, schedule, allowance, or delivery is created",
                "handoff": "fence a returned manager assignment reference and preserve identity, evidence, consumption, and parent obligation",
                "complete_task": "manager-only guarded task close; verifies current project/task/assignment pins, disposition, evidence hashes and gates before one owner transaction",
                "manager_inbox": "read one derived project/subproject scope with tasks, assignments, attempts, reports, decisions, attention and repeat-safe event cursor; read-only",
                "find_and_continue": "read one bounded project/retained-checkout/session join with explicit cardinality and held/ambiguous state; read-only",
                "submit_checkin": "append one current-manager report for a matching DueRecord occurrence, then recoverably acknowledge that occurrence",
                "submit_issue/respond_to_issue/record_issue_outcome": "append typed issue history over assignment reports; resolution requires application evidence",
            },
            "execution": {
                "composition": "PortfolioOwnerBootstrap.execution_application(...) -> ExecutionApplication",
                "manager": {
                    "prepare": "assign/adopt the current owner-pinned manager occurrence before any provider effect",
                    "start": "start one admitted occurrence and publish the durable result or unknown effect",
                    "continue": "continue_manager reuses the settled native session and canonical progress report",
                    "recover": "recover reconciles the exact occurrence before any retry; unknown effects remain fenced",
                },
                "advisor": {
                    "schedule": "AdvisorExecution.prepare_scheduled prepares the existing owner-bound Due",
                    "wake": "wake_once admits one current advisor occurrence after assignment/generation reconciliation",
                    "allowance": "reconcile_allowance settles the neutral owner allowance without replaying uncertain effects",
                },
                "host": {
                    "custody": "ExecutionHost retains admitted command/service custody across parent completion",
                    "lifecycle": "ExecutionHost reconciles the persisted trigger before pause, stop, or restart",
                },
                "operator_boundary": "This CLI does not construct an owner, Store, provider, scheduler, or native session; use the owner-bound controller/command surface for execution and this CLI for scoped reads, briefs, pairing, acceptance, and help.",
            },
            "operator_contract": {
                "working_entrypoint": "python -m otto.portfolio.cli help --format text",
                "owner_status_entrypoint": "manager_ctl.py status (through the already running owner command service)",
                "current_run_configuration": ".otto/runs/<run-id>/run.yaml, or its adopted native configuration record; this is the sole model/stage/budget authority",
                "complete_criterion_source": ".otto/runs/<run-id>/tasklist.md; read the exact criterion rows before interpreting status",
                "accessible_megado_skill": "policy-staging/megado/skill/SKILL.md and its linked execution/run-config/native-work references",
                "maintained_otto_skill_index": "src/otto/portfolio/skills/SKILL.md",
                "maintained_recovery_skill": "src/otto/portfolio/skills/recovery/SKILL.md",
                "evidence_skill": "not installed by this candidate",
                "status_semantics": {
                    "execution": "show committed dispatch/occurrence/result observations; absence is unknown, not failure",
                    "review_acceptance": "show review decisions and acceptance_exists separately from writes_performed",
                    "lifecycle": "show owner-read project/task lifecycle and current owner bindings",
                    "uncertainty": "retain historical uncertain effects and distinguish verifier limits, evidence mismatch, and unresolved live effects",
                    "suggestions": "reports and next_action values are timestamped observations/advice, not scheduler commands or acceptance",
                },
                "supported_read_operations": [
                    "python -m otto.portfolio.cli projects --actor ACTOR",
                    "python -m otto.portfolio.cli overview --actor ACTOR --project-ref REF_JSON",
                    "python -m otto.portfolio.cli task --actor ACTOR --project-ref PROJECT_REF_JSON --task-ref TASK_REF_JSON",
                    "python -m otto.portfolio.cli find-and-continue --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events overview --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events timeline --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events agents --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events tasks-reviews --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events blockers --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events usage --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli events recovery --actor ACTOR --project-ref PROJECT_REF_JSON",
                    "python -m otto.portfolio.cli assessment-coverage --parent-ref TASK_REF_JSON",
                    "python -m otto.portfolio.cli completion-gate --task-ref TASK_REF_JSON",
                ],
            },
            "resource_attachments": "assign_roles accepts role-keyed adopted resource descriptors; exact resource_ref revisions are persisted as canonical assignment pins and later brief evidence carries bundle/export/brief digests",
            "invariants": [
                "pending creation does not create a manager, tasklist, allowance, session, or accepted result",
                "revisit and prerequisite signals never activate or dispatch work",
                "same request_id is resolved by the canonical receipt/replay contract",
                "host launch/session/AST behavior is outside this surface and unavailable bindings fail explicitly",
            ],
        }

    def _request(self, request_id: str, actor: str) -> tuple[str, str]:
        return _text(request_id, "request_id"), _text(actor, "actor")

    def _execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        try:
            value = self.operations.execute(operation, _json_copy(dict(payload), field="payload"), request_id=request_id, actor=actor)
        except Exception as exc:  # canonical owner reports its own transaction/rejection details
            return {"outcome": "error", "error": {"code": "canonical_rejected", "message": str(exc), "operation": operation}}
        return _result(value, operation=operation)

    def _read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
        actor = _text(actor, "actor")
        try:
            value = self.operations.read(operation, _json_copy(dict(payload), field="payload"), actor=actor)
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "canonical_read_failed", "message": str(exc), "operation": operation}}
        return _result(value, operation=operation)

    def create_pending(
        self,
        *,
        actor: str,
        request_id: str,
        edit: Optional[Mapping[str, Any]] = None,
        template: Any = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
        open_project: bool = False,
        open: Optional[bool] = None,
        orchestrated: bool = False,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        if open is not None:
            if not isinstance(open, bool):
                raise PortfolioError("open must be boolean")
            open_project = open
        if not isinstance(open_project, bool):
            raise PortfolioError("open_project must be boolean")
        if not isinstance(orchestrated, bool):
            raise PortfolioError("orchestrated must be boolean")
        if orchestrated and open_project:
            raise PortfolioError("default-orchestrated creation does not support open_project")
        edit_value = _edit(edit)
        template_value = "blank" if template is None else _json_copy(template, field="template")
        if isinstance(template_value, str):
            _text(template_value, "template")
        elif not isinstance(template_value, Mapping):
            raise PortfolioError("template must be a name or object")
        if template_parameters is not None and not isinstance(template_parameters, Mapping):
            raise PortfolioError("template_parameters must be an object")
        if template_parameters is not None and not isinstance(template_value, Mapping):
            raise PortfolioError("template_parameters require a selected template object")
        payload = {"edit": edit_value, "template": template_value, "open": bool(open_project)}
        if template_parameters is not None:
            payload["template_parameters"] = _json_copy(
                dict(template_parameters), field="template_parameters"
            )
        return self._execute(
            "work.orchestrator.project.create" if orchestrated else "work.pending.create",
            payload,
            request_id=request_id,
            actor=actor,
        )

    def create_with_default_orchestrator(
        self,
        *,
        actor: str,
        request_id: str,
        edit: Optional[Mapping[str, Any]] = None,
        template: Any = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Use the owner-backed one-main/default placement route.

        This explicit route is retained as a named compatibility seam; a
        qualified owner binding also sends ordinary pending creation through
        the same atomic owner operation.
        """

        return self.create_pending(
            actor=actor,
            request_id=request_id,
            edit=edit,
            template=template,
            template_parameters=template_parameters,
            orchestrated=True,
        )

    def create_and_open(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["open_project"] = True
        return self.create_pending(**kwargs)

    @staticmethod
    def _onboarding_contract() -> dict[str, Any]:
        return {
            "schema": ONBOARDING_SCHEMA,
            "required_inputs": {"title": "non-blank text", "brief": "non-blank UTF-8 text"},
            "optional_inputs": {
                "supporting_files": "bounded relative-path to UTF-8 text object",
                "predecessor_ref": "existing project reference, retained as planning context only",
                "template": "owner-adopted blank or selected work template resource",
                "template_parameters": "parameters for the selected template only",
            },
            "defaults": {
                "template": "blank",
                "brief_path": ONBOARDING_BRIEF_PATH,
                "lifecycle": "pending",
                "tasks": [],
                "execution": "inert until explicit activation",
            },
            "next_action": "open the draft from its stable workspace locator, then add exploration or plan documents",
        }

    @staticmethod
    def _onboarding_binding_gap(result: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(result)
        error = value.get("error") if isinstance(value.get("error"), Mapping) else {}
        value.update({
            "schema": ONBOARDING_SCHEMA,
            "binding": {
                "state": "missing",
                "required": "authenticated owner-backed project authoring and DAT/EDT ports; find also requires a finite project-read grant",
                "route": "PortfolioOwnerBootstrap(...).consumer_operations()",
                "reason": error.get("message", "the accepted owner binding is not installed"),
            },
            "next_action": "bind the exact authenticated owner authoring route, then retry this local request; do not create a filesystem project",
            "effects": _onboarding_effects(),
        })
        return value

    def create_draft(
        self,
        *,
        actor: str,
        request_id: str,
        title: str,
        brief: str,
        supporting_files: Optional[Mapping[str, str]] = None,
        predecessor_ref: Any = None,
        template: Any = None,
        template_parameters: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create one inert title-and-brief package through existing owner ports.

        This is a finite composition, not a new persistence or workflow layer:
        create the pending Work project, create/link DAT files, then checkout the
        semantic ProjectSheet through EDT. Each child request has a stable suffix
        so a partial or lost local reply can be inspected and resumed exactly.
        """

        request_id, actor = self._request(request_id, actor)
        title = _text(title, "title")
        brief = _text(brief, "brief")
        files = _onboarding_files(brief, supporting_files)
        predecessor = None if predecessor_ref is None else _ref(predecessor_ref, "predecessor_ref")
        metadata = {
            "onboarding": {
                "schema": ONBOARDING_SCHEMA,
                "brief_path": ONBOARDING_BRIEF_PATH,
                "file_manifest_sha256": _digest_json(files),
                "predecessor_ref": predecessor,
            },
        }
        created = self.create_pending(
            actor=actor,
            request_id=request_id,
            edit={"title": title, "outcome": "", "metadata": metadata},
            template=template,
            template_parameters=template_parameters,
            open_project=False,
            orchestrated=False,
        )
        base = {**self._onboarding_contract(), "creation_route": "live_inert_owner_authoring",
                "generic_default_orchestrator": {"used": False, "available_via": "create_with_default_orchestrator"},
                "predecessor": {"ref": predecessor, "applied": False, "next_phase": "queue-after"},
                "effects": _onboarding_effects()}
        if created.get("outcome") in {"unavailable", "denied"}:
            return self._onboarding_binding_gap({**base, **created})
        project_ref = created.get("project_ref")
        if not isinstance(project_ref, Mapping):
            return {**base, **created, "schema": ONBOARDING_SCHEMA,
                    "outcome": "error",
                    "error": {"code": "missing_project_ref", "message": "owner creation returned no canonical project reference"},
                    "next_action": "inspect the retained create receipt before retrying; do not create a replacement project"}

        documents: list[dict[str, Any]] = []
        document_errors: list[dict[str, Any]] = []
        ordered_files = [(ONBOARDING_BRIEF_PATH, brief)] + [
            (path, content) for path, content in files.items() if path != ONBOARDING_BRIEF_PATH
        ]
        for index, (path, content) in enumerate(ordered_files):
            suffix = "brief" if path == ONBOARDING_BRIEF_PATH else f"supporting-{index}"
            document = self.create_document(
                project_ref,
                actor=actor,
                request_id=f"{request_id}:{suffix}:document",
                content=content,
                role="brief" if path == ONBOARDING_BRIEF_PATH else "supporting",
                visibility="private",
                access_mode="write",
            )
            if document.get("outcome") not in {"created", "replayed"}:
                document_errors.append({"path": path, "stage": "document", "result": document})
                continue
            document_ref = document.get("document_ref")
            if not isinstance(document_ref, Mapping):
                document_errors.append({"path": path, "stage": "document", "result": document,
                                        "error": {"code": "missing_document_ref", "message": "DAT create returned no document reference"}})
                continue
            link = self.link_document(
                project_ref,
                document_ref,
                actor=actor,
                request_id=f"{request_id}:{suffix}:link",
                namespace="project.files",
                key=path,
                # Associations are read/append references; write custody is
                # carried by the DAT document itself and the EDT projection.
                access_mode="read",
            )
            if link.get("outcome") not in {"linked", "replayed"}:
                document_errors.append({"path": path, "stage": "link", "result": link})
            documents.append({"path": path, "document": document, "link": link})

        opened = self.checkout_project(project_ref, actor=actor, request_id=request_id + ":workspace")
        if opened.get("outcome") in {"unavailable", "denied"}:
            return self._onboarding_binding_gap({**base, **created, "documents": documents,
                                                 "document_errors": document_errors, "open": opened})
        project = opened.get("project_ref", project_ref)
        locator = _onboarding_locator(project)
        result = {**base, **created, "schema": ONBOARDING_SCHEMA,
                  "outcome": "partial" if document_errors else "created",
                  "project_ref": project,
                  "workspace": {
                      "locator": locator,
                      "project_ref": project,
                      "session_id": opened.get("session_id"),
                      "projection": opened,
                      "physical_path": "session-scoped and not a stable project locator",
                  },
                  "documents": documents, "document_errors": document_errors, "open": opened}
        if document_errors:
            result["next_action"] = "inspect retained document receipts and resume the exact missing document/link steps; do not recreate the project"
        return result

    def find_draft(self, *, actor: str, project_ref: Any) -> dict[str, Any]:
        """Find one existing draft by canonical project identity, read-only."""

        actor = _text(actor, "actor")
        ref = _ref(project_ref, "project_ref")
        found = self.read_pending(ref, actor=actor)
        base = {**self._onboarding_contract(), "creation_route": "live_inert_owner_authoring",
                "generic_default_orchestrator": {"used": False, "available_via": "create_with_default_orchestrator"},
                "read_only": True, "writes": 0, "effects": _onboarding_effects()}
        if found.get("outcome") in {"unavailable", "denied"}:
            return self._onboarding_binding_gap({**base, **found})
        try:
            locator = _onboarding_locator(found.get("project_ref", ref))
        except PortfolioError:
            locator = _onboarding_locator(ref)
        return {**base, **found, "schema": ONBOARDING_SCHEMA, "workspace": {"locator": locator,
                "project_ref": found.get("project_ref", ref), "projection": None},
                "next_action": "use reopen with a fresh request key to obtain the current EDT projection"}

    def reopen_draft(self, *, actor: str, project_ref: Any, request_id: str) -> dict[str, Any]:
        """Open the same draft identity through the existing ProjectSheet/EDT port."""

        request_id, actor = self._request(request_id, actor)
        ref = _ref(project_ref, "project_ref")
        opened = self.checkout_project(ref, actor=actor, request_id=request_id)
        base = {**self._onboarding_contract(), "creation_route": "live_inert_owner_authoring",
                "generic_default_orchestrator": {"used": False, "available_via": "create_with_default_orchestrator"},
                "effects": _onboarding_effects()}
        if opened.get("outcome") in {"unavailable", "denied"}:
            return self._onboarding_binding_gap({**base, **opened})
        project = opened.get("project_ref", ref)
        return {**base, **opened, "schema": ONBOARDING_SCHEMA, "project_ref": project,
                "workspace": {"locator": _onboarding_locator(project), "project_ref": project,
                               "session_id": opened.get("session_id"), "projection": opened,
                               "physical_path": "session-scoped and not a stable project locator"},
                "next_action": "edit only through the returned EDT projection, then use the existing check-in/release operation"}

    # Explicit names used by the maintained onboarding entrypoint.
    onboarding_create = create_draft
    onboarding_find = find_draft
    onboarding_reopen = reopen_draft

    def create_document(
        self,
        project_ref: Any,
        *,
        actor: str,
        request_id: str,
        content: Any,
        role: str = "supporting",
        visibility: str = "private",
        access_mode: str = "read",
        document_id: Optional[str] = None,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.document.create",
            {
                "project_ref": _ref(project_ref),
                "content": _json_copy(content, field="content"),
                "role": _text(role, "role"),
                "visibility": _text(visibility, "visibility"),
                "access_mode": _text(access_mode, "access_mode"),
                "document_id": _text(document_id, "document_id") if document_id is not None else None,
            },
            request_id=request_id,
            actor=actor,
        )

    def link_document(
        self,
        project_ref: Any,
        document_ref: Any,
        *,
        actor: str,
        request_id: str,
        namespace: str = "project.documents",
        key: str = "document",
        access_mode: str = "read",
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.document.link",
            {
                "project_ref": _ref(project_ref),
                "document_ref": _ref(document_ref, "document_ref"),
                "namespace": _text(namespace, "namespace"),
                "key": _text(key, "key"),
                "access_mode": _text(access_mode, "access_mode"),
            },
            request_id=request_id,
            actor=actor,
        )

    def read_pending(self, project_ref: Any, *, actor: str) -> dict[str, Any]:
        return self._read("work.pending.read", {"project_ref": _ref(project_ref)}, actor=actor)

    def list_pending(self, *, actor: str, parent_ref: Any = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if parent_ref is not None:
            payload["parent_ref"] = _ref(parent_ref, "parent_ref")
        return self._read("work.pending.list", payload, actor=actor)

    def manager_inventory(self, *, actor: str, native_observer: Any = None) -> dict[str, Any]:
        """Read the project-scoped manager inventory without writes or sends."""

        reader = getattr(self.operations, "manager_inventory", None)
        if callable(reader):
            return reader(actor=actor, native_observer=native_observer)
        return {
            "outcome": "unavailable",
            "read_only": True,
            "writes": 0,
            "native_calls": 0,
            "projects": [],
            "excluded_completed": [],
            "error": {"code": "manager_inventory_unavailable", "message": "the finite owner binding does not expose manager inventory"},
        }

    def list_projects(self, *, actor: str, parent_ref: Any = None,
                      cursor: Optional[str] = None, limit: Optional[int] = None) -> dict[str, Any]:
        """Read the finite host-granted owner inventory without a raw-reader fallback."""
        actor = _text(actor, "actor")
        listing = getattr(self.operations, "list_projects", None)
        if not callable(listing):
            return {"outcome": "unavailable", "schema": "otto.portfolio-projects.v1",
                    "projects": [], "read_only": True,
                    "error": {"code": "owner_project_reader_unavailable",
                              "message": "finite project read port is unavailable"}}
        parent = None if parent_ref is None else _ref(parent_ref, "parent_ref")
        try:
            return dict(listing(actor=actor, parent_ref=parent, cursor=cursor, limit=limit))
        except (TypeError, ValueError):
            return {"outcome": "denied", "schema": "otto.portfolio-projects.v1",
                    "projects": [], "read_only": True,
                    "error": {"code": "project_scope_denied",
                              "message": "project read scope is unavailable"}}

    def list_work(
        self,
        *,
        actor: str,
        view: str = "all",
        project_ref: Any = None,
        parent_ref: Any = None,
        cursor: Optional[str] = None,
        limit: int = 100,
        safety_scan: bool = True,
    ) -> dict[str, Any]:
        """Read a scoped portfolio/task view from existing owner records.

        ``view`` filters are derived labels; the owner lifecycle, readiness,
        applicability and execution observations remain separate fields.
        """
        actor = _text(actor, "actor")
        views = {"all", "upcoming", "ready", "blocked", "in_progress", "completed"}
        if view not in views:
            raise PortfolioError(f"view must be one of {', '.join(sorted(views))}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise PortfolioError("limit must be between 1 and 1000")
        if cursor is not None and (not isinstance(cursor, str) or not cursor.strip()):
            raise PortfolioError("cursor must be non-blank text when supplied")
        if not isinstance(safety_scan, bool):
            raise PortfolioError("safety_scan must be boolean")

        binding = getattr(self.operations, "binding", None)
        authority = getattr(binding, "authority", None)
        requested_project = _ref(project_ref, "project_ref") if project_ref is not None else None
        requested_parent = _ref(parent_ref, "parent_ref") if parent_ref is not None else None
        for label, ref in (("project_ref", requested_project), ("parent_ref", requested_parent)):
            if ref is not None and (ref.get("authority") != authority or ref.get("kind") != "work.project"):
                return {"outcome": "denied", "schema": "otto.portfolio-work.v1", "view": view, "items": [], "projects": [], "read_only": True, "error": {"code": "project_scope_denied", "message": f"{label} is outside the configured owner authority"}}

        if requested_project is not None:
            admission = self.operations.read("work.project.read", {"project_ref": requested_project}, actor=actor)
            if admission.get("outcome") != "read":
                return {"outcome": admission.get("outcome", "denied"), "schema": "otto.portfolio-work.v1",
                        "view": view, "items": [], "projects": [], "read_only": True,
                        "error": admission.get("error", {"code": "project_scope_denied"})}
        inventory = self.list_projects(actor=actor, parent_ref=requested_parent)
        if inventory.get("outcome") not in {"listed", "partial"}:
            return {"outcome": inventory.get("outcome", "error"), "schema": "otto.portfolio-work.v1", "view": view, "items": [], "projects": [], "read_only": True, "error": inventory.get("error", {"code": "project_inventory_unavailable", "message": "owner project inventory could not be read"})}
        projects = [item for item in inventory.get("projects", ()) if isinstance(item, Mapping)]
        if requested_project is not None:
            wanted = _identity_ref(requested_project)
            projects = [item for item in projects if _identity_ref(item.get("project_ref")) == wanted]
            if not projects:
                return {"outcome": "denied", "schema": "otto.portfolio-work.v1", "view": view, "items": [], "projects": [], "read_only": True, "error": {"code": "project_not_visible", "message": "project is not present in the configured owner scope"}}
        projects.sort(key=lambda item: json.dumps(item.get("project_ref"), sort_keys=True))

        rows: list[dict[str, Any]] = []
        project_rows: list[dict[str, Any]] = []
        read_errors: list[dict[str, Any]] = []
        owner_pages = 0
        for project in projects:
            current_ref = project.get("project_ref")
            page_cursor = None
            seen_cursors: set[str] = set()
            final_inbox: Optional[dict[str, Any]] = None
            event_ids: list[str] = []
            complete = False
            for _page_number in range(10000):
                inbox = self.manager_inbox(current_ref, actor=actor, cursor=page_cursor, limit=limit, safety_scan=safety_scan)
                owner_pages += 1
                if inbox.get("outcome") != "read":
                    read_errors.append({"project_ref": current_ref, "error": inbox.get("error", {"code": "project_read_failed", "message": "ProjectSheet read did not succeed"})})
                    break
                final_inbox = inbox
                reconciliation = inbox.get("reconciliation") if isinstance(inbox.get("reconciliation"), Mapping) else {}
                for event_id in reconciliation.get("event_ids", ()) if isinstance(reconciliation.get("event_ids", ()), (list, tuple)) else ():
                    if isinstance(event_id, str) and event_id not in event_ids:
                        event_ids.append(event_id)
                if reconciliation.get("has_more") is not True:
                    complete = reconciliation.get("has_more") is False
                    break
                next_cursor = reconciliation.get("cursor")
                if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors or next_cursor == page_cursor:
                    read_errors.append({"project_ref": current_ref, "error": {"code": "owner_cursor_did_not_advance", "message": "owner event pagination did not produce a new cursor"}})
                    final_inbox = None
                    break
                seen_cursors.add(next_cursor)
                page_cursor = next_cursor
            if final_inbox is None:
                project_rows.append({"project_ref": current_ref, "lifecycle": project.get("lifecycle"), "state": "unavailable", "task_count": None, "read_pages": None})
                continue
            inbox_scope = final_inbox.get("scope", {}) if isinstance(final_inbox.get("scope"), Mapping) else {}
            actual_project = inbox_scope.get("ref")
            if _identity_ref(actual_project) != _identity_ref(current_ref):
                read_errors.append({"project_ref": current_ref, "error": {"code": "project_scope_mismatch", "message": "ProjectSheet returned a different project identity"}})
                project_rows.append({"project_ref": current_ref, "lifecycle": project.get("lifecycle"), "state": "unavailable", "task_count": None, "read_pages": None})
                continue
            task_rows = [dict(item) for item in final_inbox.get("task_rows", ()) if isinstance(item, Mapping)]
            project_rows.append({
                "project_ref": actual_project,
                "title": project.get("title"),
                "lifecycle": project.get("lifecycle", "unknown"),
                "parent_ref": project.get("parent_ref"),
                "manager_assignments": _json_copy((final_inbox.get("manager") or {}).get("assignments", ()), field="manager_assignments") if isinstance(final_inbox.get("manager"), Mapping) else [],
                "state": "read" if complete else "partial",
                "task_count": len(task_rows),
                "read_pages": len(seen_cursors) + 1,
                "event_ids_read": event_ids,
            })
            for row in task_rows:
                row["project_ref"] = actual_project
                lifecycle = row.get("lifecycle", {}).get("value") if isinstance(row.get("lifecycle"), Mapping) else None
                readiness = row.get("readiness", {}).get("value") if isinstance(row.get("readiness"), Mapping) else {}
                readiness = readiness if isinstance(readiness, Mapping) else {}
                observation = row.get("observation", {}) if isinstance(row.get("observation"), Mapping) else {}
                applicability = row.get("applicability", {}) if isinstance(row.get("applicability"), Mapping) else {}
                explicit_blockers = any(isinstance(readiness.get(key), (list, tuple)) and bool(readiness.get(key)) for key in ("blockers", "blocked_by", "blocking_reasons"))
                readiness_status = str(readiness.get("status", row.get("readiness", {}).get("eligibility", ""))).strip().lower().replace("-", "_")
                dependency_blocked = any(item.get("severity") == "blocking" for item in row.get("dependency_reasons", ()) if isinstance(item, Mapping))
                blocked = readiness_status in {"blocked", "blocked_by_dependency", "recompute_needed"} or explicit_blockers or dependency_blocked
                ready = readiness.get("ready") is True or readiness_status in {"ready", "eligible"}
                completed = isinstance(lifecycle, str) and lifecycle.lower() == "completed"
                withdrawn = isinstance(lifecycle, str) and lifecycle.lower() == "withdrawn"
                active = observation.get("state") == "active"
                not_applicable = applicability.get("state") == "not_applicable"
                memberships = ["all"]
                if not completed and not withdrawn and not active and not not_applicable:
                    memberships.append("upcoming")
                if ready and not blocked and not completed and not withdrawn and not active and not not_applicable:
                    memberships.append("ready")
                if blocked and not completed and not withdrawn and not active:
                    memberships.append("blocked")
                if active and not completed and not withdrawn:
                    memberships.append("in_progress")
                if completed:
                    memberships.append("completed")
                row["view_memberships"] = memberships
                if completed:
                    classification = "completed"
                elif active:
                    classification = "in_progress"
                elif withdrawn:
                    classification = "withdrawn"
                elif not_applicable:
                    classification = "not_applicable"
                elif applicability.get("state") in {"deferred", "conditional"}:
                    classification = applicability["state"]
                elif blocked:
                    classification = "blocked"
                elif "ready" in memberships:
                    classification = "ready"
                elif "upcoming" in memberships:
                    classification = "upcoming"
                else:
                    classification = "unknown"
                row["derived_classification"] = classification
                rows.append(row)

        rows.sort(key=lambda item: (json.dumps(item.get("project_ref"), sort_keys=True), tuple(item.get("source_aliases", ())), str((item.get("ref") or {}).get("id", ""))))
        selected = [row for row in rows if view in row.get("view_memberships", ())]
        counts = {name: sum(name in row.get("view_memberships", ()) for row in rows) for name in sorted(views)}
        classes = ("completed", "in_progress", "blocked", "ready", "deferred", "conditional", "not_applicable", "withdrawn", "upcoming", "unknown")
        disjoint_counts = {name: sum(row.get("derived_classification") == name for row in rows) for name in classes}
        # Imported canonical tasks and derived portions are disjoint;
        # older authored rows retain their alias-based source count.
        source_task_count = 0
        structural_child_count = 0
        for row in rows:
            authored = row.get("authored")
            metadata = authored.get("metadata") if isinstance(authored, Mapping) else None
            canonical = metadata.get("canonical_source_task") if isinstance(metadata, Mapping) else None
            if canonical is False:
                structural_child_count += 1
            elif canonical is True or (canonical is None and row.get("source_aliases")):
                source_task_count += 1
        denominators = {"source_tasks": source_task_count, "structural_children": structural_child_count, "source_aliases": sum(len(row.get("source_aliases", ())) for row in rows)}

        scope_value = {"authority": authority, "actor": actor, "view": view, "project_ref": requested_project, "parent_ref": requested_parent}
        scope_key = _digest_json(scope_value)
        snapshot = _digest_json(selected)
        offset = 0
        if cursor is not None:
            try:
                offset = decode_work_view_cursor(cursor, scope=scope_key, snapshot=snapshot)
            except WorkViewCursorError as exc:
                return {"outcome": "error", "schema": "otto.portfolio-work.v1", "view": view, "items": [], "projects": project_rows, "read_only": True, "error": {"code": "invalid_or_stale_cursor", "message": str(exc)}}
        page = selected[offset:offset + limit]
        next_offset = offset + len(page)
        has_more = next_offset < len(selected)
        next_cursor = encode_work_view_cursor(scope=scope_key, offset=next_offset, snapshot=snapshot) if has_more else None
        return {
            "outcome": "partial" if read_errors or inventory.get("outcome") == "partial" or any(item.get("state") == "partial" for item in project_rows) else "listed",
            "schema": "otto.portfolio-work.v1",
            "view": view,
            "scope": scope_value,
            "projects": project_rows,
            "items": page,
            "count": len(selected),
            "counts": counts,
            "disjoint_counts": disjoint_counts,
            "denominators": denominators,
            "pagination": {"limit": limit, "offset": offset, "has_more": has_more, "cursor": next_cursor, "owner_event_pages_read": owner_pages, "projects_in_inventory": len(projects), "snapshot_digest": snapshot},
            "read_only": True,
            "writes": 0,
            "dispatch": False,
            "launch": False,
            "unknown": {"inventory_issues": inventory.get("issues", []), "project_read_errors": read_errors, "actor_acl": inventory.get("actor_acl", "not_exposed_by_current_consumer_binding")},
        }

    def manager_inbox(
        self,
        project_ref: Any,
        *,
        actor: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        safety_scan: bool = True,
    ) -> dict[str, Any]:
        """Read one derived manager scope without acknowledging or dispatching."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise PortfolioError("limit must be between 1 and 1000")
        if cursor is not None and (not isinstance(cursor, str) or not cursor.strip()):
            raise PortfolioError("cursor must be non-blank text when supplied")
        if not isinstance(safety_scan, bool):
            raise PortfolioError("safety_scan must be boolean")
        payload: dict[str, Any] = {"project_ref": _ref(project_ref), "limit": limit, "safety_scan": safety_scan}
        if cursor is not None:
            payload["cursor"] = cursor
        return self._read("work.manager.inbox", payload, actor=actor)

    def author_task_list(
        self,
        project_ref: Any,
        tasks: Sequence[Mapping[str, Any]],
        *,
        actor: str,
        request_id: str,
        base_revision: Optional[str] = None,
    ) -> dict[str, Any]:
        """Apply a task batch through the existing typed ProjectSheet port."""
        request_id, actor = self._request(request_id, actor)
        project = _ref(project_ref)
        if isinstance(tasks, (str, bytes)) or not isinstance(tasks, Sequence):
            raise PortfolioError("tasks must be a sequence of task objects")
        task_values = _json_copy(list(tasks), field="tasks")
        if any(not isinstance(item, Mapping) for item in task_values):
            raise PortfolioError("each task must be an object")
        # Authored tasks are inert: they never dispatch.  Only activation
        # makes work runnable, so every caller of this route stays pending.
        if any(item.get("lifecycle", "pending") != "pending" or item.get("withdraw") for item in task_values):
            raise PortfolioError("tasks authored through the typed route must be inert: lifecycle pending and not withdrawn; activation alone starts work")
        revision = base_revision if base_revision is not None else project.get("revision")
        if not isinstance(revision, str) or not revision.strip():
            raise PortfolioError("task-list authoring requires the current project revision")
        sheet = getattr(self.operations, "sheet_port", None)
        binding = getattr(self.operations, "binding", None)
        apply = getattr(sheet, "apply", None)
        authenticate = getattr(binding, "authenticated_actor", None)
        if not callable(apply) or not callable(authenticate):
            return {"outcome": "unavailable", "operation": "work.tasklist.apply",
                    "error": {"code": "typed_project_sheet_unavailable",
                              "message": "canonical typed ProjectSheet authoring is not bound"}}
        try:
            from herzchen.contracts import ResourceRef

            batch = apply(
                ResourceRef.from_dict(project), {"tasks": task_values},
                logical_request_key=request_id, actor=authenticate(actor),
                base_revision=revision,
            )
            ref = getattr(getattr(batch, "project", None), "ref", None)
            receipt = getattr(batch, "receipt", None)
            return {"outcome": "authored", "project_ref": _json_copy(ref.to_dict() if hasattr(ref, "to_dict") else ref),
                    "replayed": bool(getattr(receipt, "replayed", False)),
                    "task_count": len(task_values),
                    "task_refs": {key: value.to_dict() for key, value in batch.mappings.items()},
                    "dispatch": False, "launch": False}
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "task_list_authoring_failed",
                                                        "message": str(exc), "operation": "work.tasklist.apply"}}

    def save_project(self, document: Any, *, actor: str, request_id: Optional[str] = None) -> dict[str, Any]:
        """Save one project from a save file (A2) through the work command lane.

        The file's project_ref carries the revision it was read at, which is the
        base the save applies to. Without a request_id the key is derived from the
        file, so the same file replays and a changed file is a new request.
        """
        from .save import SaveFileError, parse_save_file, save_request_key

        try:
            parsed = parse_save_file(document)
            key = request_id if request_id is not None else save_request_key(document)
        except SaveFileError as exc:
            return {"outcome": "error", "error": {"code": "invalid_save_file", "message": str(exc), "operation": "work.project.save"}}
        return self._execute("work.project.save", parsed, request_id=key, actor=actor)

    def read_work(
        self,
        project_ref: Any,
        *,
        actor: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        safety_scan: bool = True,
    ) -> CurrentWork:
        """Read current owner-backed work and label unsupported facts unknown.

        This is a projection over the same finite owner read used by
        ``manager_inbox``. It introduces no registry, cursor store, or writes.
        Authoring stays on this same facade through ``create_pending``,
        ``create_document``/``link_document``, and the typed ``sheet_port``.
        """
        inbox = self.manager_inbox(
            project_ref, actor=actor, cursor=cursor, limit=limit,
            safety_scan=safety_scan,
        )
        if inbox.get("outcome") != "read":
            return {
                "outcome": inbox.get("outcome", "unknown"),
                "schema": "otto.current-work.v1",
                "current_refs": {"project": _ref(project_ref)},
                "scope": {},
                "facts": {},
                "dependencies": [],
                "consumption": {"state": "unknown", "value": None, "source_refs": [],
                                "reason": "canonical current-work read did not succeed"},
                "closure": {"state": "unknown", "value": None, "source_refs": [],
                            "reason": "canonical current-work read did not succeed"},
                "unknown": list(inbox.get("unknown", ())),
                "source_refs": {},
                "read_side_effects": False,
                "dispatch": False,
                "launch": False,
            }

        tasks = [item for item in inbox.get("tasks", ()) if isinstance(item, Mapping)]
        assignments = [item for item in inbox.get("assignments", ()) if isinstance(item, Mapping)]
        attempts = [item for item in inbox.get("attempts", ()) if isinstance(item, Mapping)]
        attention = [item for item in inbox.get("attention", ()) if isinstance(item, Mapping)]
        decisions = list(inbox.get("decisions", ()))
        task_refs = [item.get("ref") for item in tasks if isinstance(item.get("ref"), Mapping)]
        assignment_refs = [item.get("ref") or item.get("assignment_ref") for item in assignments
                           if isinstance(item.get("ref") or item.get("assignment_ref"), Mapping)]

        def refs_for(items: Sequence[Any]) -> list[dict[str, Any]]:
            found = []
            for item in items:
                if isinstance(item, Mapping):
                    ref = item.get("source_ref") or item.get("ref")
                    if isinstance(ref, Mapping):
                        found.append(dict(ref))
            return found

        def fact(value: Any, refs: Sequence[Any], reason: Optional[str] = None) -> ProjectionValue:
            return {"state": "known", "value": value,
                    "source_refs": [dict(ref) for ref in refs if isinstance(ref, Mapping)],
                    "reason": reason}

        def unknown(reason: str) -> ProjectionValue:
            return {"state": "unknown", "value": None, "source_refs": [], "reason": reason}

        dependencies = [
            {"task_ref": task.get("ref"), **dict(dependency)}
            for task in tasks
            for dependency in task.get("dependencies", ())
            if isinstance(dependency, Mapping)
        ]
        project_identity = _ref(project_ref)
        current_refs = {
            "project": project_identity,
            "tasks": task_refs,
            "assignments": assignment_refs,
        }
        # Existing records expose bookkeeping and observations, but this read
        # surface has no typed allowance/consumption or accepted-closeout
        # result. State those facts as unknown instead of inferring from prose.
        projection = {
            "outcome": "read",
            "schema": "otto.current-work.v1",
            "current_refs": current_refs,
            "scope": dict(inbox.get("scope", {})),
            "facts": {
                "tasks": fact(tasks, refs_for(tasks)),
                "assignments": fact(assignments, refs_for(assignments)),
                "attempts": fact(attempts, refs_for(attempts)),
                "attention": fact(attention, refs_for(attention)),
                "decisions": fact(decisions, refs_for(decisions)),
            },
            "dependencies": dependencies,
            "consumption": unknown("owner inbox has no typed allowance consumption projection"),
            "closure": unknown("owner inbox has no accepted closeout projection"),
            "unknown": list(inbox.get("unknown", ())),
            "source_refs": dict(inbox.get("source_refs", {})),
            "read_side_effects": False,
            "dispatch": False,
            "launch": False,
        }
        if self._issue_loop() is not None:
            issue_view = self._issue_loop().read_issues(project_ref=project_identity)
            issue_rows = issue_view.get("issues", [])
            projection["issues"] = {
                "open": [item for item in issue_rows if item.get("state") == "open"],
                "resolved": [item for item in issue_rows if item.get("state") == "resolved"],
                "source": "assignment_reports",
            }
        return projection

    current_work = read_work

    read_manager_inbox = manager_inbox
    reconcile_inbox = manager_inbox

    def transition_project_lifecycle(
        self,
        project_ref: Any,
        task_ref: Any,
        manager_ref: Any,
        *,
        actor: str,
        request_id: str,
        expected_generation: int,
        expected_project_revision: str,
        expected_task_revision: str,
        intent: str,
        evidence: Mapping[str, Any],
        obligation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one finite owner lifecycle intent; no Otto state is written."""

        request_id, actor = self._request(request_id, actor)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
            raise PortfolioError("expected_generation must be a positive integer")
        if not isinstance(expected_project_revision, str) or not expected_project_revision.strip():
            raise PortfolioError("expected_project_revision is required")
        if not isinstance(expected_task_revision, str) or not expected_task_revision.strip():
            raise PortfolioError("expected_task_revision is required")
        if intent not in {"active", "closing", "blocked", "terminal"}:
            raise PortfolioError("unsupported project lifecycle intent")
        if not isinstance(evidence, Mapping) or not isinstance(obligation, Mapping):
            raise PortfolioError("lifecycle evidence and obligation must be objects")
        return self._execute(
            "work.project.lifecycle.transition",
            {
                "project_ref": _ref(project_ref), "task_ref": _ref(task_ref, "task_ref"),
                "manager_ref": _ref(manager_ref, "manager_ref"),
                "expected_generation": expected_generation,
                "expected_project_revision": expected_project_revision,
                "expected_task_revision": expected_task_revision,
                "intent": intent,
                "evidence": _json_copy(dict(evidence), field="evidence"),
                "obligation": _json_copy(dict(obligation), field="obligation"),
            },
            request_id=request_id, actor=actor,
        )

    def read_project_lifecycle(self, project_ref: Any, task_ref: Any, manager_ref: Any, *, actor: str) -> dict[str, Any]:
        """Read the owner lifecycle projection without a durable side effect."""

        return self._read(
            "work.project.lifecycle.read",
            {"project_ref": _ref(project_ref), "task_ref": _ref(task_ref, "task_ref"), "manager_ref": _ref(manager_ref, "manager_ref")},
            actor=actor,
        )

    def edit_pending(self, project_ref: Any, edit: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        if isinstance(edit, Mapping) and "tasks" in edit:
            # Inert pending tasks are the one task route on a draft: a tasks-only
            # edit goes through the typed ProjectSheet port, which refuses any
            # lifecycle that could run.  Mixing tasks with field edits is refused.
            if set(edit) != {"tasks"}:
                raise PortfolioError("a pending edit that carries tasks must carry only tasks; author them through the typed task route")
            return self.author_task_list(project_ref, edit["tasks"], actor=actor, request_id=request_id)
        return self._execute(
            "work.pending.edit",
            {"project_ref": _ref(project_ref), "edit": _edit(edit)},
            request_id=request_id,
            actor=actor,
        )

    def reopen(self, project_ref: Any, *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute("work.pending.open", {"project_ref": _ref(project_ref)}, request_id=request_id, actor=actor)

    def checkout_project(self, project_ref: Any, *, actor: str, request_id: str) -> dict[str, Any]:
        """Return editable project.json and an opaque EDT session; no activation."""
        request_id, actor = self._request(request_id, actor)
        return self._execute("work.project.checkout", {"project_ref": _ref(project_ref)}, request_id=request_id, actor=actor)

    def check_in_project(self, project_ref: Any, *, session_id: str, project_json: Mapping[str, Any],
                         actor: str, request_id: str, document_changes: Optional[Sequence[Mapping[str, Any]]] = None) -> dict[str, Any]:
        """Commit semantic project/task edits through the existing owner finish."""
        request_id, actor = self._request(request_id, actor)
        if document_changes is not None:
            return self._execute("work.project.folder-check-in", {"project_ref": _ref(project_ref),
                "session_id": _text(session_id, "session_id"), "project_json": dict(project_json),
                "document_changes": list(document_changes)}, request_id=request_id, actor=actor)
        return self._execute("work.project.check-in", {"project_ref": _ref(project_ref),
            "session_id": _text(session_id, "session_id"),
            "project_json": _json_copy(dict(project_json), field="project_json")}, request_id=request_id, actor=actor)

    def release_project(self, project_ref: Any, *, session_id: str, actor: str, request_id: str) -> dict[str, Any]:
        """Release checkout custody, retaining local files for explicit rebase."""
        return self._execute("work.project.folder-release", {"project_ref": _ref(project_ref),
            "session_id": _text(session_id, "session_id")}, request_id=request_id, actor=actor)

    def export_project(self, project_ref: Any, *, document_refs: Sequence[Any] = (),
                       association_refs: Sequence[Any] = (), actor: str, request_id: str) -> dict[str, Any]:
        """Export selected canonical records for a distinct owner transfer."""
        return self._execute("work.project.export", {"project_ref": _ref(project_ref),
            "document_refs": [_ref(ref) for ref in document_refs],
            "association_refs": [_ref(ref) for ref in association_refs]}, request_id=request_id, actor=actor)

    def import_project(self, snapshot: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        """Import a trusted source-owner export; raw files use import_folder."""
        return self._execute("work.project.import", {"snapshot": dict(snapshot)}, request_id=request_id, actor=actor)

    def import_folder(self, *, project_json: Mapping[str, Any], files: Mapping[str, str],
                      actor: str, request_id: str) -> dict[str, Any]:
        """Import explicit text files as target-owned pending documents; resumable."""
        return self._execute("work.project.folder-import", {"project_json": dict(project_json),
            "files": dict(files)}, request_id=request_id, actor=actor)

    def export_folder(self, project_ref: Any, *, actor: str, request_id: str) -> dict[str, Any]:
        """Export a raw text package; canonical transfer remains a separate API."""
        return self._execute("work.project.folder-export", {"project_ref": _ref(project_ref)},
            request_id=request_id, actor=actor)

    def revisit(self, project_ref: Any, revisit: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        if not isinstance(revisit, Mapping) or not revisit:
            raise PortfolioError("revisit must be a non-empty object")
        return self._execute(
            "work.pending.revisit",
            {"project_ref": _ref(project_ref), "revisit": _json_copy(dict(revisit), field="revisit"), "attention_only": True},
            request_id=request_id,
            actor=actor,
        )

    def satisfied_prerequisite(self, project_ref: Any, prerequisite_ref: Any, *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.pending.prerequisite-satisfied",
            {"project_ref": _ref(project_ref), "prerequisite_ref": _ref(prerequisite_ref, "prerequisite_ref"), "attention_only": True},
            request_id=request_id,
            actor=actor,
        )

    @staticmethod
    def _roles(roles: Mapping[str, Any], *, responsibility_ref: Any = None) -> dict[str, Any]:
        if not isinstance(roles, Mapping):
            raise PortfolioError("roles must be an object")
        parent = _ref(roles.get("parent"), "roles.parent")
        manager = _text(roles.get("manager"), "roles.manager")
        executor = roles.get("executor")
        if isinstance(executor, str):
            executor_value: Any = [_text(executor, "roles.executor")]
        elif isinstance(executor, Sequence) and not isinstance(executor, (str, bytes)):
            executor_value = [_text(value, "roles.executor") for value in executor]
            if not executor_value:
                raise PortfolioError("roles.executor must not be empty")
        else:
            raise PortfolioError("roles.executor must be text or a bounded list of text")
        if len(executor_value) > 8:
            raise PortfolioError("roles.executor exceeds the bounded executor limit")
        result = {"parent": parent, "manager": manager, "executor": executor_value}
        if "orchestrator" in roles:
            result["orchestrator"] = _text(roles["orchestrator"], "roles.orchestrator")
        if "project_advisor" in roles:
            result["project_advisor"] = _text(roles["project_advisor"], "roles.project_advisor")
        if "resources" in roles:
            raw_resources = roles["resources"]
            if responsibility_ref is not None and isinstance(raw_resources, Mapping):
                scope = _ref(responsibility_ref, "responsibility_ref")
                prepared_resources = {}
                for role, items in raw_resources.items():
                    candidates = [items] if isinstance(items, Mapping) else list(items) if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else [items]
                    prepared_resources[role] = []
                    for item in candidates:
                        if isinstance(item, Mapping):
                            item = dict(item)
                            if "responsibility_ref" in item and item["responsibility_ref"] != scope:
                                raise PortfolioError("resource responsibility_ref does not match the assignment scope")
                            item.setdefault("responsibility_ref", scope)
                        prepared_resources[role].append(item)
                raw_resources = prepared_resources
            try:
                result["resources"] = normalize_role_attachments(raw_resources)
            except ResourceSyncError as exc:
                raise PortfolioError(str(exc)) from exc
            if result["resources"].get("orchestrator") and not result.get("orchestrator"):
                raise PortfolioError("orchestrator resources require an explicit orchestrator principal")
            if result["resources"].get("project_advisor") and not result.get("project_advisor"):
                raise PortfolioError("project_advisor resources require an explicit project_advisor principal")
        if "profile" in roles:
            result["profile"] = _text(roles["profile"], "roles.profile")
        return result

    def admit(
        self,
        project_ref: Any,
        *,
        choice: str,
        frame: Mapping[str, Any],
        actor: str,
        request_id: str,
        roles: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        choice = _text(choice, "choice")
        if choice not in ADMISSION_CHOICES:
            raise PortfolioError("choice must be one of: " + ", ".join(ADMISSION_CHOICES))
        if not isinstance(frame, Mapping):
            raise PortfolioError("frame must be an object")
        frame_value = _json_copy(dict(frame), field="frame")
        for key in ("outcome", "recipient", "route", "authority"):
            _text(frame_value.get(key), f"frame.{key}")
        project_value = _ref(project_ref)
        payload: dict[str, Any] = {"project_ref": project_value, "choice": choice, "frame": frame_value}
        if roles is not None:
            payload["roles"] = self._roles(roles, responsibility_ref=project_value)
        return self._execute("work.pending.admission", payload, request_id=request_id, actor=actor)

    def assign_roles(self, project_ref: Any, roles: Mapping[str, Any], *, actor: str, request_id: str) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        return self._execute(
            "work.responsibility.assign",
            {"project_ref": _ref(project_ref), "roles": self._roles(roles, responsibility_ref=_ref(project_ref))},
            request_id=request_id,
            actor=actor,
        )

    def pair_project_advisor(
        self,
        project_ref: Any,
        manager_assignment_ref: Any,
        *,
        actor: str,
        request_id: str,
        manager_generation: int,
        advisor_principal: Optional[str] = None,
        pins: Sequence[Any] = (),
    ) -> dict[str, Any]:
        """Read the current pair, creating only a missing advisor assignment.

        Omitting ``advisor_principal`` makes this a read-only lookup.  Host
        conversation binding and all later effects use their ordinary ports.
        """

        request_id, actor = self._request(request_id, actor)
        if (isinstance(manager_generation, bool) or not isinstance(manager_generation, int)
                or manager_generation < 1):
            raise PortfolioError("manager_generation must be a positive integer")
        if advisor_principal is not None:
            advisor_principal = _text(advisor_principal, "advisor_principal")
        if isinstance(pins, (str, bytes)) or not isinstance(pins, Sequence):
            raise PortfolioError("pins must be an array")
        payload: dict[str, Any] = {
            "project_ref": _ref(project_ref),
            "manager_assignment_ref": _ref(manager_assignment_ref, "manager_assignment_ref"),
            "manager_generation": manager_generation,
            "pins": [_ref(value, "pins") for value in pins],
        }
        if advisor_principal is not None:
            payload["advisor_principal"] = advisor_principal
        return self._execute(
            "work.project-advisor.pair", payload, request_id=request_id, actor=actor,
        )

    def complete_task(
        self,
        project_ref: Any,
        task_ref: Any,
        assignment_ref: Any,
        *,
        actor: str,
        request_id: str,
        expected_generation: int,
        expected_project_revision: str,
        expected_task_revision: str,
        disposition: str,
        evidence_refs: Sequence[Any] = (),
        evidence_hashes: Any = (),
        gate_refs: Sequence[Any] = (),
        candidate_ref: Any = None,
        result_ref: Any = None,
        attempt_ref: Any = None,
        source_set_digest: Optional[str] = None,
    ) -> dict[str, Any]:
        """Request a manager-verified close through the existing owner path."""

        request_id, actor = self._request(request_id, actor)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
            raise PortfolioError("expected_generation must be a positive integer")
        if not isinstance(expected_project_revision, str) or not expected_project_revision.strip():
            raise PortfolioError("expected_project_revision is required")
        if not isinstance(expected_task_revision, str) or not expected_task_revision.strip():
            raise PortfolioError("expected_task_revision is required")
        if not isinstance(disposition, str) or not disposition.strip():
            raise PortfolioError("disposition is required")
        if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, (str, bytes)):
            raise PortfolioError("evidence_refs must be a list")
        if not isinstance(gate_refs, Sequence) or isinstance(gate_refs, (str, bytes)):
            raise PortfolioError("gate_refs must be a list")
        if isinstance(evidence_hashes, Mapping):
            # Empty evidence is sent to the owner as a held/unknown result so
            # callers can inspect the missing prerequisite without a mutation.
            hashes = _json_copy(dict(evidence_hashes), field="evidence_hashes")
        elif isinstance(evidence_hashes, Sequence) and not isinstance(evidence_hashes, (str, bytes)):
            # Empty evidence is sent to the owner as a held/unknown result.
            hashes = _json_copy(list(evidence_hashes), field="evidence_hashes")
        else:
            raise PortfolioError("evidence_hashes must be a non-empty mapping or list")
        payload = {
            "project_ref": _ref(project_ref),
            "task_ref": _ref(task_ref, "task_ref"),
            "assignment_ref": _ref(assignment_ref, "assignment_ref"),
            "expected_generation": expected_generation,
            "expected_project_revision": expected_project_revision,
            "expected_task_revision": expected_task_revision,
            "disposition": disposition.strip(),
            "evidence_refs": [_ref(value, "evidence_ref") for value in evidence_refs],
            "evidence_hashes": hashes,
            "gate_refs": [_ref(value, "gate_ref") for value in gate_refs],
        }
        for name, value in (("candidate_ref", candidate_ref), ("result_ref", result_ref), ("attempt_ref", attempt_ref)):
            if value is not None:
                payload[name] = _ref(value, name)
        if source_set_digest is not None:
            payload["source_set_digest"] = _text(source_set_digest, "source_set_digest")
        return self._execute("work.task.complete", payload, request_id=request_id, actor=actor)

    close_task = complete_task

    def handoff(
        self,
        project_ref: Any,
        *,
        from_manager: str,
        to_manager: str,
        evidence_refs: Sequence[Any],
        consumption_refs: Sequence[Any],
        parent_obligation: Any,
        actor: str,
        request_id: str,
        manager_assignment_ref: Any = None,
    ) -> dict[str, Any]:
        request_id, actor = self._request(request_id, actor)
        from_manager, to_manager = _text(from_manager, "from_manager"), _text(to_manager, "to_manager")
        if from_manager == to_manager:
            raise PortfolioError("handoff must name a replacement manager")
        if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, (str, bytes)) or not evidence_refs:
            raise PortfolioError("evidence_refs must be a non-empty list")
        if not isinstance(consumption_refs, Sequence) or isinstance(consumption_refs, (str, bytes)) or not consumption_refs:
            raise PortfolioError("consumption_refs must be a non-empty list")
        payload = {
            "project_ref": _ref(project_ref),
            "from_manager": from_manager,
            "to_manager": to_manager,
            "evidence_refs": [_ref(value, "evidence_ref") for value in evidence_refs],
            "consumption_refs": [_ref(value, "consumption_ref") for value in consumption_refs],
            "parent_obligation": _ref(parent_obligation, "parent_obligation"),
            "safe_handoff": True,
        }
        if manager_assignment_ref is not None:
            if not isinstance(manager_assignment_ref, Mapping):
                raise PortfolioError("manager_assignment_ref must be the typed reference returned by assign_roles")
            assignment_ref = _ref(manager_assignment_ref, "manager_assignment_ref")
            if assignment_ref.get("kind") != "wrk.assignment" or not isinstance(assignment_ref.get("authority"), str) or not assignment_ref["authority"].strip():
                raise PortfolioError("manager_assignment_ref.kind must be wrk.assignment")
            payload["manager_assignment_ref"] = assignment_ref
        return self._execute("work.responsibility.handoff", payload, request_id=request_id, actor=actor)


__all__ = [
    "ADMISSION_CHOICES",
    "EDITABLE_FIELDS",
    "HerzchenWorkOperations",
    "OttoPortfolio",
    "PortfolioError",
    "UnavailableWorkOperations",
    "unavailable_operations",
]
