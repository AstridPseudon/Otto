"""Operating-brief helpers and a narrow canonical-reader preparation seam.

Schema, diff, and render functions validate caller-supplied values. The
canonical preparation function reads through explicit injected owner-reader
ports, but does not authenticate a human, persist a brief, or schedule a
callback. Authentication, persistence, CAS, delivery, and retirement remain
in their existing owner and runtime paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from .resource_sync import ResourceSyncError, resolve_assignment_attachments, normalize_instruction_contract


SCHEMA_REVISION = "otto.operating-brief.v1"
SNAPSHOT_SCHEMA_REVISION = "otto.operating-snapshot.v1"
_ROLES = frozenset({"orchestrator", "manager", "worker", "project_advisor"})
_USER_FIELDS = ("mandate", "user_constraints")
_AGENT_FIELDS = ("priorities", "operational_constraints", "continuation", "links")
_ADAPTER_ROLE_BASE_GUIDANCE = (
    " For the maintained agent-adapter route, use the exact tool_entrypoint emitted by the current role "
    "introduction. The currently inspected installed prefix is "
    "`/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9 "
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-agent-adapter-conformance-20261009/"
    "controller/manager_ctl.py`; this is host evidence, not a borrowed identity or package-adoption claim. "
    "A manager/coordinating worker launches only through the authenticated owner route with "
    "`run-worker --task TASK --route normal|xhard --principal CHILD --request-key KEY --focus FOCUS`, "
    "then retains distinct outer command, start/transport and durable occurrence handles. Use pure "
    "`lookup-occurrence --scope SCOPE --request-key KEY --request-input ORIGINAL_INPUT`, "
    "`follow-occurrence --occurrence OCCURRENCE --timeout-seconds 2`, `read-result --occurrence OCCURRENCE`, "
    "and bounded `read-artifact --occurrence OCCURRENCE --artifact-ref REF --offset 0 --max-bytes 65536`; "
    "`consume-result --occurrence OCCURRENCE` is the authenticated parent receipt. After a lost reply, "
    "use exact `command-status --request-id HANDLE`, never a new key. Read original pins and reject changed "
    "input, foreign parent, ambiguity or missing scope. If the active parent turn blocks delivery, return/yield "
    "the retained handle and next action; never overlap parent turns, wait indefinitely, create hidden capacity, "
    "borrow manager credentials or redelegate an unchanged leaf brief. Resolve defaults as authorized override "
    "then project/role configuration then user default, and retain model/reasoning/adapter/resource provenance. "
    "`execution-control --operation read|recover|stop` applies only to the exact owned occurrence; recover may "
    "settle and stop fences the occurrence without proving native termination. A result is not task acceptance: "
    "separate useful admission, native terminality, required capture, settlement, parent delivery and assessment. "
    "Usage is observed, invalid or unavailable, never guessed as zero or money. Claude in this scope is mechanical "
    "only; do not perform or claim paid initialization/inference/resume. External-root launch remains a host gap."
)
ROLE_OPERATING_CONTRACTS = {
    "orchestrator": (
        "Own human-facing portfolio coordination: delegate concrete projects to their assigned managers, "
        "resolve cross-project dependencies and decisions that need the user, and verify accepted outcomes "
        "from canonical owner records. Managers own execution; the host owns installation, transport and "
        "any host-only action. Refresh state before planning, keep user mandate and constraints intact, "
        "and route mandate changes through the owner. Operational help is for a blocked route; advice is "
        "for project judgment and never becomes an owner prohibition. Inspect the exact current destination "
        "and retained receipt before continuing, replacing a role or reconciling an unknown effect."
        + _ADAPTER_ROLE_BASE_GUIDANCE
    ),
    "manager": (
        "Coordinate and independently advance assigned ready tasks through the supported worker operations, "
        "result review, acceptance evidence, and owner closeout under the adopted project policy. Follow its "
        "delegation and implementation responsibilities. When a supported route is blocked, request "
        "operational help and continue independent work. Ask for "
        "advice only for project judgment when the adopted advisor policy enables it. Refresh the canonical "
        "project, task, assignment and adopted resource context before acting; a continuation or replacement "
        "uses the current bindings. Delivery and resolution are separate, and an unknown outcome is never safe "
        "to retry without reconciling the exact retained effect. For criteria that explicitly require installed "
        "behavior, verify the current adopted source/runtime and preflight evidence before review or finish. "
        "If only host adoption, measurement, or setup is missing, request operational help with the evidence "
        "and return condition; an actual candidate defect remains an ordinary REWORK finding. "
        "Reconcile reviewer correction proposals against current evidence: accept, merge, defer with a revisit "
        "condition, or reject with a reason. Use task-list-author for pending canonical tasks and alias readback, "
        "then existing normal/XHARD run-worker only after current scope/readiness is satisfied. Task authoring "
        "grants no acceptance, execution or additional allowance; retain completed findings and prior debits."
        + _ADAPTER_ROLE_BASE_GUIDANCE
    ),
    "worker": (
        "Execute only the prescribed task within its current project, assignment, generation, resources, and "
        "acceptance scope. Refresh owner state before acting; return result, verification, changed artifacts, "
        "native identity, and unresolved responsibility through the manager's canonical result path. Do not "
        "accept your own work, expand scope or budget, create unassigned work, or message the orchestrator "
        "routinely. Propose necessary changes to the manager and wait when no authorized task action remains."
        + _ADAPTER_ROLE_BASE_GUIDANCE
    ),
    "project_advisor": (
        "Advise one assigned manager on that manager's project using current goals, acceptance criteria, "
        "messages, files, and prior conversation. Resume the same conversation, inspect actual evidence, "
        "and stay quiet when progress is healthy or unchanged. Advice is a bounded suggestion to the manager, "
        "not operational help, dispatch authority, or an owner prohibition. Choose one evidence-backed, "
        "shortest in-mandate direction; name requirement provenance and expected proof, and revise earlier "
        "advice when evidence requires it. Escalate only owner-only, cross-project, authority-gap, or uncertain "
        "effects, and reject stale pairing state before replying."
    ),
}


# Point-of-use guidance is delivered with every role introduction.  These are
# interaction rules, not a second authority or routing list; current
# assignments, conversations, schedules and run bindings remain canonical.
ROLE_CONTEXT_GUIDANCE = {
    "orchestrator": {
        "help": "Receive operational-help requests for blocked work; host transport and installation remain host-only actions.",
        "context": "Use the current project, assignment, generation, conversation and retained delivery receipt.",
        "continuation": "Continue only after the exact response is delivered and the current owner state is refreshed.",
        "recovery": "Missing destination, role replacement or unknown send requires owner-side reconciliation before retry.",
        "recovery_workflow": "Consult src/otto/portfolio/skills/recovery/SKILL.md for bounded find, inspect, resume, authorized reassignment and reminder continuity.",
    },
    "manager": {
        "help": "Use request-advice for project judgment and request-help for an operational blockage; include problem, impact, evidence, requested decision and return condition.",
        "context": "Refresh the current project, task, assignment, generation, mandate, adopted resources and conversation before acting.",
        "planning": "Reviewer reports propose correction tasks with independent normal/XHARD rationale. The manager records accept/merge/defer/reject and uses task-list-author with the pinned report/result, current project revision, typed pending tasks and exact request key. Reuse the key/input after partial progress. Missing scope/adoption/allowance requires existing owner setup before dispatch; never reopen completed work merely to file advice.",
        "installed_evidence": "For criteria that explicitly require installed behavior, verify the current adopted source/runtime and preflight evidence before review or finish. If only host adoption, measurement, or setup is missing, request operational help with the evidence and return condition; an actual candidate defect remains an ordinary REWORK finding.",
        "continuation": "Resolve an applied response with resolve-help; the retained same-manager continuation is the next action.",
        "recovery": "Read the exact delivery before retrying; unknown sends, missing destinations and replaced roles remain held until reconciled.",
        "recovery_workflow": "Consult src/otto/portfolio/skills/recovery/SKILL.md when a project, worker, session, command response or reminder is interrupted; use the maintained commands and retain the current assignment/generation.",
    },
    "worker": {
        "help": "Return implementation evidence through the assigned manager; do not create a new recipient or operational route.",
        "context": "Use only the delivered task, assignment, generation, workspace, resources and acceptance scope.",
        "continuation": "Return changed paths, verification and unresolved responsibility through the retained result path.",
        "recovery": "Do not replay an unknown effect or adopt a replacement role without a new owner-issued assignment.",
        "recovery_workflow": "Use the recovery skill through the assigned manager for diagnosis or resume; do not create a private recovery script or replacement state.",
    },
    "project_advisor": {
        "help": "Answer advice requests for project judgment; operational blockage belongs to the manager's help route.",
        "context": "Inspect the current goal, criteria, mandate, files, messages, open decisions and paired conversations.",
        "continuation": "Resume the pinned advisor conversation and revise earlier advice when new evidence changes the direction.",
        "recovery": "Reject stale pairing, missing context or unknown delivery; preserve the allowance and reconcile before resend.",
    },
}


class OperatingBriefError(ValueError):
    """A brief, diff or supplied snapshot violates the additive contract."""


def _json_copy(value: Any, field: str = "value") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise OperatingBriefError(f"{field} must be JSON-compatible") from exc


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not allow_empty and not value.strip()):
        requirement = "text" if allow_empty else "non-blank text"
        raise OperatingBriefError(f"{field} must be {requirement}")
    return value if allow_empty else value.strip()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatingBriefError(f"{field} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise OperatingBriefError(f"{field} keys must be text")
    return _json_copy(dict(value), field)


def _owner_mapping(value: Any, field: str) -> dict[str, Any]:
    """Normalize a value returned by an injected canonical owner read port."""

    if not isinstance(value, Mapping):
        to_dict = getattr(value, "to_dict", None)
        if not callable(to_dict):
            raise OperatingBriefError(f"{field} owner reader returned no record")
        value = to_dict()
    return _mapping(value, field)


def _pinned_ref(value: Any, field: str) -> dict[str, Any]:
    reference = _mapping(value, field)
    for key in ("authority", "kind", "id", "revision"):
        _text(reference.get(key), f"{field}.{key}")
    return {key: reference[key] for key in ("authority", "kind", "id", "revision")}


def _observed_ref(record: Mapping[str, Any], field: str) -> dict[str, Any]:
    raw = record.get("ref")
    if raw is None:
        raw = record.get("assignment_ref")
    return _pinned_ref(raw, f"{field}.ref")


def _require_exact_ref(actual: Any, expected: Mapping[str, Any], field: str) -> dict[str, Any]:
    observed = _pinned_ref(actual, field)
    if observed != dict(expected):
        raise OperatingBriefError(f"{field} does not match the pinned canonical reference")
    return observed


def _same_identity(actual: Any, expected: Mapping[str, Any], field: str) -> bool:
    observed = _pinned_ref(actual, field)
    return all(observed.get(key) == expected.get(key) for key in ("authority", "kind", "id"))


def _owner_payload(record: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    """Read the narrow normalized payload exposed by owner-reader adapters.

    This is an adapter contract, not a new persisted Otto record schema.
    """

    payload = record.get("payload", record)
    if not isinstance(payload, Mapping):
        raise OperatingBriefError(f"{field}.payload must be an object")
    return payload


def _state(record: Mapping[str, Any], field: str) -> str:
    payload = _owner_payload(record, field)
    raw = record.get("lifecycle", record.get("status", payload.get("lifecycle", payload.get("status"))))
    selected = _text(raw, f"{field}.state").lower()
    if selected not in {"active", "open", "in_progress", "pending", "ready", "queued", "in-flight", "reassigned"}:
        raise OperatingBriefError(f"{field} is not in an active state")
    return selected


def _string_list(value: Any, field: str) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OperatingBriefError(f"{field} must be a list of text")
    return tuple(_text(item, f"{field}[{index}]") for index, item in enumerate(value))


def _mapping_list(value: Any, field: str) -> Tuple[dict[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OperatingBriefError(f"{field} must be a list of objects")
    return tuple(_mapping(item, f"{field}[{index}]") for index, item in enumerate(value))


def _record_list(value: Any, field: str) -> Tuple[dict[str, Any], ...]:
    """Validate a bounded list of caller-supplied record objects."""

    return _mapping_list(value, field)


def _reference_identity(value: Any, field: str) -> tuple[tuple[str, Any], ...]:
    """Return the supplied canonical identity without trusting extra fields."""

    reference = _mapping(value, field)
    _text(reference.get("id"), f"{field}.id")
    return tuple((key, reference[key]) for key in ("authority", "kind", "id", "revision") if key in reference)


def _reference_matches(project_ref: Any, active_ref: Any, field: str) -> bool:
    """Match an observed ref against an explicitly supplied owner ref.

    The active ref is the caller's scope fence. Extra observed metadata is
    permitted, but every identity field present in that fence must match.
    """

    observed = dict(_reference_identity(project_ref, field))
    expected = dict(_reference_identity(active_ref, "active_manager_refs[]"))
    return all(observed.get(key) == value for key, value in expected.items())


def _priority_list(value: Any) -> Tuple[dict[str, Any], ...]:
    items = _mapping_list(value, "priorities")
    normalized = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        item_id = _text(item.get("id", f"priority-{index}"), f"priorities[{index}].id")
        if item_id in seen:
            raise OperatingBriefError("priorities must have unique ids")
        seen.add(item_id)
        text = _text(item.get("text", item.get("title")), f"priorities[{index}].text")
        status = _text(item.get("status", "pending"), f"priorities[{index}].status")
        normalized.append({"id": item_id, "text": text, "status": status, **{key: value for key, value in item.items() if key not in {"id", "text", "title", "status"}}})
    return tuple(normalized)


@dataclass(frozen=True)
class OperatingBrief:
    """The optional user brief plus agent-maintained operational fields."""

    role: str
    mandate: str
    user_constraints: Tuple[str, ...]
    priorities: Tuple[dict[str, Any], ...]
    operational_constraints: Tuple[str, ...]
    continuation: Optional[dict[str, Any]]
    links: Tuple[dict[str, Any], ...]
    revision: str = "initial"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, role: Optional[str] = None) -> "OperatingBrief":
        raw = _mapping(value, "brief")
        unknown = set(raw).difference({"schema_revision", "role", "mandate", "user_constraints", "priorities", "operational_constraints", "continuation", "links", "revision"})
        if unknown:
            raise OperatingBriefError("unknown brief fields: " + ", ".join(sorted(unknown)))
        declared_role = None if raw.get("role") is None else _text(raw.get("role"), "role").lower()
        requested_role = None if role is None else _text(role, "role").lower()
        if declared_role is not None and requested_role is not None and declared_role != requested_role:
            raise OperatingBriefError("brief role does not match the requested role")
        selected_role = requested_role or declared_role
        if selected_role is None:
            raise OperatingBriefError("role must be orchestrator, manager, worker, or project_advisor")
        if selected_role not in _ROLES:
            raise OperatingBriefError("role must be orchestrator, manager, worker, or project_advisor")
        schema = raw.get("schema_revision", SCHEMA_REVISION)
        if schema != SCHEMA_REVISION:
            raise OperatingBriefError("brief schema_revision is unsupported")
        continuation = raw.get("continuation")
        if continuation is not None:
            continuation = _mapping(continuation, "continuation")
        return cls(
            selected_role,
            _text(raw.get("mandate", ""), "mandate", allow_empty=True),
            _string_list(raw.get("user_constraints", ()), "user_constraints"),
            _priority_list(raw.get("priorities", ())),
            _string_list(raw.get("operational_constraints", ()), "operational_constraints"),
            continuation,
            _mapping_list(raw.get("links", ()), "links"),
            _text(raw.get("revision", "initial"), "revision"),
        )

    @classmethod
    def empty(cls, role: str, *, revision: str = "absent") -> "OperatingBrief":
        return cls.from_mapping({"schema_revision": SCHEMA_REVISION, "role": role, "revision": revision})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_revision": SCHEMA_REVISION,
            "role": self.role,
            "mandate": self.mandate,
            "user_constraints": list(self.user_constraints),
            "priorities": [_json_copy(item) for item in self.priorities],
            "operational_constraints": list(self.operational_constraints),
            "continuation": None if self.continuation is None else _json_copy(self.continuation),
            "links": [_json_copy(item) for item in self.links],
            "revision": self.revision,
        }


def brief_diff(base: OperatingBrief | Mapping[str, Any], proposed: OperatingBrief | Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable field diff without treating proposals as acceptance."""

    left = base if isinstance(base, OperatingBrief) else OperatingBrief.from_mapping(base)
    right = proposed if isinstance(proposed, OperatingBrief) else OperatingBrief.from_mapping(proposed, role=left.role)
    if left.role != right.role:
        raise OperatingBriefError("brief role cannot change")
    before, after = left.to_dict(), right.to_dict()
    changes = {field: {"before": before[field], "after": after[field]} for field in (*_USER_FIELDS, *_AGENT_FIELDS) if before[field] != after[field]}
    user_changes = {field: value for field, value in changes.items() if field in _USER_FIELDS}
    agent_changes = {field: value for field, value in changes.items() if field in _AGENT_FIELDS}
    return {
        "schema_revision": "otto.operating-brief.diff.v1",
        "role": left.role,
        "base_revision": left.revision,
        "proposed_revision": right.revision,
        "changes": changes,
        "user_changes": user_changes,
        "agent_changes": agent_changes,
        "requires_user_authority": bool(user_changes),
        "proposal_only": True,
        "diff_sha256": _digest({"role": left.role, "base_revision": left.revision, "proposed_revision": right.revision, "changes": changes}),
    }


def compose_owner_snapshot(
    *,
    projects: Sequence[Mapping[str, Any]],
    active_manager_refs: Sequence[Mapping[str, Any]],
    recent_completions: Sequence[Mapping[str, Any]] = (),
    returned_results: Sequence[Mapping[str, Any]] = (),
    blockers: Sequence[Mapping[str, Any]] = (),
    as_of: str,
    coverage_cursor: Optional[str] = None,
) -> dict[str, Any]:
    """Compose a bounded snapshot from explicit owner-shaped inputs.

    Ownership is supplied by the caller; this function never infers it from
    names, chat proximity or a global project list. Closed projects leave the
    active view but remain available in ``closures`` for history.
    """

    observed_at = _text(as_of, "as_of")
    active_refs = _record_list(active_manager_refs, "active_manager_refs")
    manager_keys = tuple(active_refs)
    project_records = _record_list(projects, "projects")
    active, closures = [], []
    for index, project in enumerate(project_records):
        owner_refs = [
            ("manager_ref", project.get("manager_ref")),
            ("assignment_ref", project.get("assignment_ref")),
        ]
        owner_refs = [(name, value) for name, value in owner_refs if value is not None]
        if not owner_refs:
            continue
        if not any(_reference_matches(value, active_ref, f"projects[{index}].{name}") for name, value in owner_refs for active_ref in manager_keys):
            continue
        lifecycle = _text(project.get("lifecycle", "pending"), f"projects[{index}].lifecycle").lower()
        if lifecycle in {"closed", "completed", "withdrawn"}:
            closures.append(project)
        else:
            active.append(project)
    completion_records = _record_list(recent_completions, "recent_completions")
    returned_records = _record_list(returned_results, "returned_results")
    blocker_records = _record_list(blockers, "blockers")
    body = {
        "schema_revision": SNAPSHOT_SCHEMA_REVISION,
        "as_of": observed_at,
        "coverage_cursor": None if coverage_cursor is None else _text(coverage_cursor, "coverage_cursor"),
        "active_projects": _json_copy(active),
        "closures": _json_copy(closures),
        "recent_accepted_completions": _json_copy(list(completion_records)),
        "returned_unaccepted_results": _json_copy(list(returned_records)),
        "blockers": _json_copy(list(blocker_records)),
        "active_manager_refs": _json_copy(list(active_refs)),
        "ownership_source": "explicit canonical manager/assignment refs supplied by caller",
    }
    body["snapshot_sha256"] = _digest(body)
    return body


def render_operating_brief(
    *,
    role: str,
    role_instructions: str,
    project_state: Mapping[str, Any],
    brief: Optional[OperatingBrief | Mapping[str, Any]] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    edit_recipe: Optional[Mapping[str, Any]] = None,
    as_of: str,
) -> dict[str, Any]:
    """Render a deterministic inline envelope with honest freshness metadata."""

    role_value = OperatingBrief.empty(role).role
    if brief is None:
        selected = OperatingBrief.empty(role_value)
    elif isinstance(brief, OperatingBrief):
        if brief.role != role_value:
            raise OperatingBriefError("brief role does not match the requested role")
        selected = brief
    else:
        selected = OperatingBrief.from_mapping(brief, role=role_value)
    instructions = _text(role_instructions, "role_instructions", allow_empty=True)
    state = _mapping(project_state, "project_state")
    rendered = {
        "schema_revision": "otto.operating-brief.render.v1",
        "role": selected.role,
        "brief_status": "absent_fallback" if brief is None else "present",
        "brief": selected.to_dict(),
        "role_instructions": instructions,
        "project_state": state,
        "snapshot": None if snapshot is None else _mapping(snapshot, "snapshot"),
        "edit_recipe": None if edit_recipe is None else _mapping(edit_recipe, "edit_recipe"),
        "freshness": {
            "as_of": _text(as_of, "as_of"),
            "source": "caller-supplied owner projection",
            "atomic_pre_delivery": False,
            "entry_refresh_required": True,
        },
    }
    rendered["render_sha256"] = _digest(rendered)
    return _json_copy(rendered)


def prepare_canonical_operating_brief(
    *,
    role: str,
    project_ref: Mapping[str, Any],
    assignment_ref: Mapping[str, Any],
    mandate_ref: Mapping[str, Any],
    expected_generation: int,
    project_reader: Callable[[Mapping[str, Any]], Any],
    assignment_reader: Callable[[Mapping[str, Any]], Any],
    mandate_reader: Callable[[Mapping[str, Any]], Any],
    resource_reader: Any,
    as_of: str,
    task_ref: Optional[Mapping[str, Any]] = None,
    task_reader: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    direction_context_reader: Any = None,
) -> dict[str, Any]:
    """Prepare a brief only from exact records returned by trusted owner readers.

    The readers are explicit trust boundaries supplied by the owner adapter;
    this function does not authenticate a human or create a persisted brief
    schema.  They return normalized mappings with a pinned ``ref`` and a
    ``payload`` (the payload may be omitted for top-level fields). All readers
    receive identity-only refs and resolve current state; this function
    compares returned revisions with the expected pins, including the
    currently adopted mandate record. The normalized mandate record carries
    ``role``, ``scope_ref``, active state, and the adopted ``brief``.
    Assignment records carry role, scope, generation, principal, and active
    state. Project/task records carry lifecycle state; task records also
    carry their exact parent ``project_ref``. The content revision inside
    ``brief`` remains independent from the owner record's CAS revision.

    All inputs are read twice and must remain byte-stable across preparation.
    This detects observed races but is not atomic pre-delivery; the caller
    still needs the owner operation's final revision/generation fence.
    """

    role_value = OperatingBrief.empty(role).role
    project_pin = _pinned_ref(project_ref, "project_ref")
    assignment_pin = _pinned_ref(assignment_ref, "assignment_ref")
    mandate_pin = _pinned_ref(mandate_ref, "mandate_ref")
    if (task_ref is None) != (task_reader is None):
        raise OperatingBriefError("task_ref and task_reader must be supplied together")
    task_pin = None if task_ref is None else _pinned_ref(task_ref, "task_ref")
    if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
        raise OperatingBriefError("expected_generation must be a positive integer")
    for name, reader in (("project_reader", project_reader), ("assignment_reader", assignment_reader), ("mandate_reader", mandate_reader)):
        if not callable(reader):
            raise OperatingBriefError(f"{name} must be a trusted owner reader")
    if task_reader is not None and not callable(task_reader):
        raise OperatingBriefError("task_reader must be a trusted owner reader")

    def read(
        reader: Callable[[Mapping[str, Any]], Any],
        ref: Mapping[str, Any],
        field: str,
        *,
        current: bool = False,
    ) -> dict[str, Any]:
        lookup_ref = {key: ref[key] for key in ("authority", "kind", "id")} if current else ref
        try:
            # Owner callbacks receive detached refs and cannot mutate the
            # expected pins retained for validation or evidence.
            return _owner_mapping(reader(_json_copy(lookup_ref, f"{field}.lookup_ref")), field)
        except OperatingBriefError:
            raise
        except Exception as exc:
            raise OperatingBriefError(f"{field} owner read failed") from exc

    project = read(project_reader, project_pin, "project", current=True)
    assignment = read(assignment_reader, assignment_pin, "assignment", current=True)
    mandate_record = read(mandate_reader, mandate_pin, "mandate", current=True)
    task = None if task_pin is None else read(task_reader, task_pin, "task", current=True)
    _require_exact_ref(_observed_ref(project, "project"), project_pin, "project")
    _require_exact_ref(_observed_ref(assignment, "assignment"), assignment_pin, "assignment")
    _require_exact_ref(_observed_ref(mandate_record, "mandate"), mandate_pin, "mandate")
    if task is not None and task_pin is not None:
        _require_exact_ref(_observed_ref(task, "task"), task_pin, "task")

    project_state = _state(project, "project")
    assignment_payload = _owner_payload(assignment, "assignment")
    mandate_payload = _owner_payload(mandate_record, "mandate")
    assignment_role = _text(assignment.get("role", assignment_payload.get("role")), "assignment.role").lower()
    # Match the existing runtime/role adapter alias without changing the owner record.
    if assignment_role == "executor":
        assignment_role = "worker"
    if assignment_role != role_value:
        raise OperatingBriefError("assignment role does not match the requested role")
    assignment_state = _state(assignment, "assignment")
    generation = assignment.get("generation", assignment_payload.get("generation"))
    if not isinstance(generation, int) or isinstance(generation, bool) or generation != expected_generation:
        raise OperatingBriefError("assignment generation is stale")
    principal = assignment.get("principal", assignment_payload.get("principal"))
    principal_valid = (
        isinstance(principal, str) and bool(principal.strip())
    ) or (
        isinstance(principal, Mapping)
        and isinstance(principal.get("id"), str)
        and bool(principal["id"].strip())
    )
    if not principal_valid:
        raise OperatingBriefError("assignment principal is missing")
    principal_value = _json_copy(principal, "assignment.principal")
    assignment_scope = assignment.get("scope_ref", assignment.get("scope", assignment_payload.get("scope_ref", assignment_payload.get("scope"))))
    scope_matches_project = _same_identity(assignment_scope, project_pin, "assignment.scope")
    scope_matches_task = task_pin is not None and _reference_matches(assignment_scope, task_pin, "assignment.scope")
    if not (scope_matches_project or scope_matches_task) and role_value == "orchestrator":
        # A portfolio orchestrator may be reused for several independent
        # projects, but only through the owner-authored supervision relation
        # on this exact project.  The relation is a join, not a broad grant:
        # it must pin the same portfolio-scoped assignment and generation.
        scope_value = _owner_payload(assignment).get("scope", assignment_scope)
        supervision = _owner_payload(project).get("metadata", {})
        supervision = supervision.get("otto_orchestrator") if isinstance(supervision, Mapping) else None
        relation_assignment = supervision.get("assignment_ref") if isinstance(supervision, Mapping) else None
        relation_portfolio = supervision.get("portfolio_ref") if isinstance(supervision, Mapping) else None
        relation_project = supervision.get("project_ref") if isinstance(supervision, Mapping) else None
        portfolio_scope = isinstance(scope_value, Mapping) and scope_value.get("kind") == "wrk.portfolio"
        exact_assignment = relation_assignment == assignment_pin if isinstance(relation_assignment, Mapping) else False
        exact_project = (
            isinstance(relation_project, Mapping)
            and _same_identity(relation_project, project_pin, "supervision.project_ref")
        )
        exact_portfolio = (
            portfolio_scope
            and isinstance(relation_portfolio, Mapping)
            and _same_identity(relation_portfolio, scope_value, "supervision.portfolio_ref")
        )
        if (
            isinstance(supervision, Mapping)
            and supervision.get("schema") == "otto.orchestrator.supervision.v2"
            and exact_assignment
            and exact_project
            and exact_portfolio
            and supervision.get("assignment_revision") == assignment_pin.get("revision")
            and supervision.get("generation") == expected_generation
        ):
            scope_matches_project = True
    if not (scope_matches_project or scope_matches_task):
        raise OperatingBriefError("assignment scope is outside the requested project/task")

    mandate_role = _text(mandate_record.get("role", mandate_payload.get("role")), "mandate.role").lower()
    if mandate_role != role_value:
        raise OperatingBriefError("mandate role does not match the requested role")
    mandate_state = _state(mandate_record, "mandate")
    mandate_scope = mandate_record.get("scope_ref", mandate_record.get("project_ref", mandate_payload.get("scope_ref", mandate_payload.get("project_ref"))))
    if not _same_identity(mandate_scope, project_pin, "mandate.scope_ref"):
        raise OperatingBriefError("mandate is not scoped to the requested project")
    raw_brief = mandate_record.get("brief", mandate_payload.get("brief"))
    if not isinstance(raw_brief, Mapping):
        raise OperatingBriefError("mandate record has no adopted brief")
    selected = OperatingBrief.from_mapping(raw_brief, role=role_value)
    try:
        attachments = resolve_assignment_attachments(assignment, resource_reader, role=role_value)
    except ResourceSyncError as exc:
        raise OperatingBriefError(f"adopted BASE resource could not be resolved: {exc}") from exc
    if len(attachments) != 1:
        raise OperatingBriefError("assignment must pin exactly one adopted BASE role resource")
    base = attachments[0]
    if base.get("required") is not True:
        raise OperatingBriefError("adopted BASE role resource must be required")
    from .role_context import RoleContextError, supporting_context
    from .direction_context import direction_inputs
    def read_directions() -> list[dict[str, Any]]:
        return [] if direction_context_reader is None else direction_context_reader(
            assignment_ref=assignment_pin, generation=expected_generation,
            project_ref=project_pin, task_ref=task_pin)
    try:
        directions = read_directions()
        sources = supporting_context(base, resource_reader, exact_direction_inputs=direction_inputs(directions))
    except ValueError as exc:
        raise OperatingBriefError(str(exc)) from exc
    base_content = base.get("content")
    if not isinstance(base_content, Mapping):
        raise OperatingBriefError("adopted BASE resource has no readable content")
    instruction_text = (base_content.get("instructions")
                        if base_content.get("schema") == "herzchen.instructions.v1"
                        else base_content.get("text"))
    if not isinstance(instruction_text, str) or not instruction_text.strip():
        raise OperatingBriefError("adopted BASE resource has no readable instruction text")

    task_state = None
    task_context = None
    if task is not None and task_pin is not None:
        task_payload = _owner_payload(task, "task")
        # A project manager remains accountable after completing its execution
        # task. Its exact active manager mandate must still authorize ordinary
        # management; workers and advisors cannot resume completed task work.
        completed_manager_task = (role_value == "manager" and scope_matches_project
            and task.get("lifecycle", task_payload.get("lifecycle")) == "completed"
            and isinstance(task_payload.get("completion"), Mapping)
            and isinstance(mandate_payload.get("instruction_contract"), Mapping))
        task_state = "completed" if completed_manager_task else _state(task, "task")
        task_project_ref = task.get("project_ref", task_payload.get("project_ref"))
        if not _same_identity(task_project_ref, project_pin, "task.project_ref"):
            raise OperatingBriefError("task is not a child of the requested project")
        task_context = {"ref": task_pin, "lifecycle": task_state, "payload": _json_copy(dict(task_payload), "task.payload")}

    project_context = {"ref": project_pin, "lifecycle": project_state, "payload": _json_copy(dict(_owner_payload(project, "project")), "project.payload")}
    snapshot = {
        "schema_revision": "otto.operating-context.v1",
        "project_ref": project_pin,
        "task_ref": task_pin,
        "assignment_ref": assignment_pin,
        "generation": generation,
        "principal": principal_value,
        "responsibility_ref": assignment_payload.get("responsibility_ref"),
        "native_session": assignment_payload.get("session"),
        "assignment_state": assignment_state,
        "mandate_ref": mandate_pin,
        "mandate_state": mandate_state,
        "project_state": project_state,
        "task_state": task_state,
        "as_of": _text(as_of, "as_of"),
    }
    rendered = render_operating_brief(
        role=role_value,
        role_instructions=instruction_text,
        project_state={"project": project_context, "task": task_context, "assignment": snapshot},
        brief=selected,
        snapshot=snapshot,
        as_of=as_of,
    )
    body = {
        "schema_revision": "otto.canonical-operating-brief-preparation.v1",
        "role": role_value,
        "source_refs": {"project": project_pin, "task": task_pin, "assignment": assignment_pin, "mandate": mandate_pin},
        "base_resource": {"ref": base["resource_ref"], "revision": base["adopted_revision"],
            "content": base_content, "content_sha256": _digest(base_content)},
        "generation": generation,
        "render": rendered,
        "supporting_context": sources,
        "direction_context": directions,
    }

    explicit = mandate_payload.get("instruction_contract")
    if explicit is not None:
        if (role_value not in {"worker", "manager", "orchestrator", "project_advisor"} or task_pin is None or mandate_state != "active"
                or mandate_payload.get("dispatch_enabled") is not True
                or mandate_payload.get("task_ref") != task_pin
                or mandate_payload.get("assignment_ref") != assignment_pin
                or type(mandate_payload.get("generation")) is not int
                or mandate_payload.get("generation") != expected_generation):
            raise OperatingBriefError("execution mandate lacks exact active role task/assignment/generation/dispatch scope")
        try:
            contract = normalize_instruction_contract(explicit)
        except ResourceSyncError as exc:
            raise OperatingBriefError("invalid execution mandate instruction contract: " + str(exc)) from exc
        principal_id = principal_value if isinstance(principal_value, str) else principal_value["id"]
        if (contract["task_ref"] != task_pin or contract["authority"]["source"] != "canonical_owner"
                or contract["authority"]["owner_actor"] != principal_id):
            raise OperatingBriefError("execution mandate contract conflicts with current owner/task")
        if role_value == "manager" and contract["authority"].get("effect_profile") != "workspace-write-manager":
            raise OperatingBriefError("manager execution mandate lacks exact workspace-write effect profile")
        if task_state == "completed" and "canonical_manager_commands" not in contract["allowed_operations"]:
            raise OperatingBriefError("completed task requires ordinary project manager command authority")
        if role_value in {"orchestrator", "project_advisor"} and contract["authority"].get("effect_profile") is not None:
            raise OperatingBriefError(role_value + " mandate cannot grant a workspace-write effect profile")
        body["mandate_instruction_contract"] = {
            "source_ref": mandate_pin, "task_ref": task_pin, "assignment_ref": assignment_pin,
            "generation": generation, "dispatch_enabled": True, "instruction_contract": contract,
        }

    fresh_project = read(project_reader, project_pin, "project", current=True)
    fresh_assignment = read(assignment_reader, assignment_pin, "assignment", current=True)
    fresh_mandate = read(mandate_reader, mandate_pin, "mandate", current=True)
    fresh_task = None if task_pin is None else read(task_reader, task_pin, "task", current=True)
    try:
        fresh_attachments = resolve_assignment_attachments(fresh_assignment, resource_reader, role=role_value)
        if len(fresh_attachments) != 1:
            raise OperatingBriefError("adopted BASE role resource changed during refresh")
        fresh_directions = read_directions()
        fresh_sources = supporting_context(fresh_attachments[0], resource_reader,
            exact_direction_inputs=direction_inputs(fresh_directions))
    except (ResourceSyncError, RoleContextError) as exc:
        raise OperatingBriefError(f"adopted BASE resource refresh failed: {exc}") from exc
    comparisons = [(project, fresh_project), (assignment, fresh_assignment), (mandate_record, fresh_mandate)]
    if task is not None and fresh_task is not None:
        comparisons.append((task, fresh_task))
    if (any(_digest(before) != _digest(after) for before, after in comparisons)
            or _digest(attachments) != _digest(fresh_attachments)
            or _digest(sources) != _digest(fresh_sources)):
        raise OperatingBriefError("canonical owner state changed while preparing the brief")
    if _digest(directions) != _digest(fresh_directions):
        raise OperatingBriefError("canonical direction changed while preparing the brief")
    body["evidence_sha256"] = _digest(body)
    return _json_copy(body, "prepared brief")


def json_envelope(value: Mapping[str, Any]) -> str:
    """Materialize one stable pretty JSON envelope for a generic document."""

    _mapping(value, "envelope")
    return json.dumps(_json_copy(dict(value)), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


@dataclass(frozen=True)
class OperatingBriefAuthoringAdapter:
    """Bind an agent-editable brief to the owner's existing semantic handler.

    The adapter deliberately receives the owner ``batches`` and ``lifecycle``
    ports from the caller.  It neither discovers those ports nor creates a
    replacement command path.  ``agent_draft`` is pure and rejects protected
    user fields; ``bind_handler`` and ``finish`` delegate to the supplied
    owner objects, where actor, scope, checkout, CAS and retirement checks
    remain enforced.
    """

    role: str
    batches: Any
    lifecycle: Any

    def __post_init__(self) -> None:
        normalized = OperatingBrief.empty(self.role).role
        object.__setattr__(self, "role", normalized)
        if not callable(getattr(self.batches, "lifecycle_handler", None)):
            raise OperatingBriefError("batches.lifecycle_handler must be callable")
        if not callable(getattr(self.lifecycle, "finish", None)):
            raise OperatingBriefError("lifecycle.finish must be callable")

    def agent_draft(
        self,
        *,
        role_instructions: str,
        project_state: Mapping[str, Any],
        brief: Optional[OperatingBrief | Mapping[str, Any]] = None,
        snapshot: Optional[Mapping[str, Any]] = None,
        edit_recipe: Optional[Mapping[str, Any]] = None,
        as_of: str,
    ) -> dict[str, Any]:
        """Render an agent proposal while keeping protected fields empty.

        A user-provided mandate or constraint must enter through the owner
        authority path.  Raising here prevents an agent-facing draft from
        masquerading as an accepted protected-field edit.
        """

        selected = OperatingBrief.empty(self.role) if brief is None else (
            brief if isinstance(brief, OperatingBrief) else OperatingBrief.from_mapping(brief, role=self.role)
        )
        if selected.role != self.role:
            raise OperatingBriefError("brief role does not match the adapter role")
        if selected.mandate or selected.user_constraints:
            raise OperatingBriefError("agent brief cannot edit protected user fields")
        return render_operating_brief(
            role=self.role,
            role_instructions=role_instructions,
            project_state=project_state,
            brief=None if brief is None else selected,
            snapshot=snapshot,
            edit_recipe=edit_recipe,
            as_of=as_of,
        )

    def bind_handler(self, project: Any, *, authoring: Any, handle: Any, request_id: str) -> Any:
        """Return the owner's existing project-sheet semantic handler."""

        return self.batches.lifecycle_handler(
            project,
            authoring=authoring,
            handle=handle,
            request_id=request_id,
        )

    def finish(
        self,
        target: Any,
        *,
        project: Any,
        authoring: Any,
        handle: Any,
        request_id: str,
        **kwargs: Any,
    ) -> Any:
        """Delegate one finish through the owner's shared lifecycle boundary."""

        handler = self.bind_handler(
            project,
            authoring=authoring,
            handle=handle,
            request_id=request_id,
        )
        return self.lifecycle.finish(
            target,
            request_id=request_id,
            handler=handler,
            **kwargs,
        )


__all__ = [
    "OperatingBrief",
    "OperatingBriefAuthoringAdapter",
    "OperatingBriefError",
    "ROLE_CONTEXT_GUIDANCE",
    "ROLE_OPERATING_CONTRACTS",
    "brief_diff",
    "compose_owner_snapshot",
    "json_envelope",
    "prepare_canonical_operating_brief",
    "render_operating_brief",
]
