"""Pure placement and peer-relationship policy for portfolio orchestrators.

This module is deliberately a read/decision layer over the existing owner
records.  It accepts the typed responsibility-assignment and project
supervision projections supplied by the owner, but it does not open a store,
write an assignment, or schedule a trigger.  The owner remains the only
place that can commit the result through its existing command ports.

The normal path is intentionally boring: a new project reuses the one
guarded default pointer.  A peer is only previewed/accepted when an existing
orchestrator explicitly requests it with a purpose, scope, and acknowledged
overlap warning.  Peer requests never contain a parent orchestrator, so this
slice cannot create a recursive hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


PLACEMENT_SCHEMA = "otto.portfolio.orchestrator-placement.v1"
_RETIRED_STATUSES = frozenset({"retired", "stopped", "cancelled", "completed"})


class OrchestratorPlacementError(ValueError):
    """Base error for an invalid, unsafe, or stale placement request."""


class ForeignAuthorityError(OrchestratorPlacementError):
    """A projected record does not belong to the selected owner authority."""


class StalePlacementError(OrchestratorPlacementError):
    """The caller did not make its decision against the current view."""


class RecursiveOrchestrationError(OrchestratorPlacementError):
    """An orchestrator was projected as subordinate to another orchestrator."""


class OverlapAcknowledgementRequired(OrchestratorPlacementError):
    """A deliberate peer request has overlap that was not acknowledged."""


class ExplicitPeerRequired(OrchestratorPlacementError):
    """The caller attempted to bypass the explicit peer path."""


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _payload(value: Any) -> Mapping[str, Any]:
    candidate = _field(value, "payload", {})
    return candidate if isinstance(candidate, Mapping) else {}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise OrchestratorPlacementError(f"{field} must be a non-blank string")
    return value.strip()


def _ref_parts(value: Any) -> Tuple[Optional[str], str, Optional[str]]:
    """Normalize a ResourceRef-like object without taking ownership of it."""

    if isinstance(value, str):
        return None, _text(value, "reference"), None
    authority = _field(value, "authority")
    identifier = _field(value, "id")
    revision = _field(value, "revision")
    if identifier is None and isinstance(value, Mapping):
        identifier = value.get("ref") or value.get("assignment_ref") or value.get("project_ref")
    if identifier is None and value is not None and not isinstance(value, (str, bytes)):
        identifier = str(value)
    if isinstance(identifier, Mapping) or (
        identifier is not None and not isinstance(identifier, (str, bytes)) and _field(identifier, "id") is not None
    ):
        nested = identifier
        authority = authority or _field(nested, "authority")
        revision = revision or _field(nested, "revision")
        identifier = _field(nested, "id")
    if identifier is None:
        raise OrchestratorPlacementError("reference is required")
    return (
        None if authority is None else _text(authority, "authority"),
        _text(str(identifier), "reference"),
        None if revision is None else _text(str(revision), "revision"),
    )


def _record_ref(value: Any, *names: str) -> Tuple[Optional[str], str, Optional[str]]:
    for name in names:
        candidate = _field(value, name)
        if candidate is not None:
            return _ref_parts(candidate)
    return _ref_parts(value)


def _same_ref(left: Any, right: Any) -> bool:
    return _record_ref(left)[1] == _record_ref(right)[1]


def _status(value: Any) -> str:
    candidate = _field(value, "status", "active")
    candidate = _field(candidate, "value", candidate)
    return str(candidate).strip().lower()


def _active(status: str) -> bool:
    return status not in _RETIRED_STATUSES


def _purpose_scope(value: Any) -> Tuple[str, str]:
    payload = _payload(value)
    purpose = _field(value, "purpose") or payload.get("purpose")
    scope = _field(value, "intended_scope") or _field(value, "scope_label") or payload.get("intended_scope") or payload.get("scope_label")
    if scope is None:
        raw_scope = _field(value, "scope") or payload.get("scope")
        scope = _field(raw_scope, "id") or raw_scope
    return (
        "" if purpose is None else str(purpose).strip(),
        "" if scope is None else str(scope).strip(),
    )


@dataclass(frozen=True)
class OrchestratorSummary:
    assignment_ref: str
    authority: str
    principal: Any
    status: str
    generation: int
    purpose: str
    intended_scope: str
    owned_project_refs: Tuple[str, ...]


@dataclass(frozen=True)
class Supervision:
    project_ref: str
    orchestrator_assignment_ref: str
    project_revision: Optional[str]


@dataclass(frozen=True)
class OrchestratorView:
    """A consistent owner read used by placement UX and guarded commands."""

    authority: str
    revision: str
    default_assignment_ref: Optional[str]
    orchestrators: Tuple[OrchestratorSummary, ...]
    supervision: Tuple[Supervision, ...]

    def orchestrator(self, assignment_ref: str) -> OrchestratorSummary:
        for item in self.orchestrators:
            if item.assignment_ref == assignment_ref:
                return item
        raise OrchestratorPlacementError("unknown orchestrator assignment")

    def supervisor_for(self, project_ref: str) -> Optional[str]:
        matches = [item.orchestrator_assignment_ref for item in self.supervision if item.project_ref == project_ref]
        if len(matches) > 1:
            raise OrchestratorPlacementError("project has more than one accountable orchestrator")
        return matches[0] if matches else None


@dataclass(frozen=True)
class PlacementDecision:
    action: str
    project_ref: str
    accountable_orchestrator_assignment_ref: str
    default_assignment_ref: str
    warning: Optional[str]


@dataclass(frozen=True)
class PeerPreview:
    action: str
    purpose: str
    intended_scope: str
    overlap_project_refs: Tuple[str, ...]
    overlap_warning: Optional[str]
    default_assignment_ref: Optional[str]
    recursive_hierarchy: bool = False


@dataclass(frozen=True)
class PeerRequest:
    action: str
    requested_by_assignment_ref: str
    purpose: str
    intended_scope: str
    overlap_project_refs: Tuple[str, ...]
    default_assignment_ref: Optional[str]
    accountable_supervisor_by_project: Tuple[Tuple[str, str], ...]
    recursive_hierarchy: bool = False


def build_orchestrator_view(
    *,
    authority: str,
    revision: Any,
    assignments: Iterable[Any],
    supervision: Iterable[Any] = (),
    default_assignment_ref: Any = None,
) -> OrchestratorView:
    """Derive the bounded UX view from existing assignments and relations.

    ``assignments`` are existing Herzchen ``ResponsibilityAssignment`` values
    (or their serialized projection).  ``supervision`` is the existing
    owner/project relation projection.  This function is intentionally pure;
    it is safe to use before a create/transfer command and on retries.
    """

    owner = _text(authority, "authority")
    view_revision = _text(str(revision), "revision")
    records = []
    seen_refs = set()
    for raw in assignments:
        record_authority, assignment_ref, _ = _record_ref(raw, "assignment_ref", "ref")
        if record_authority is not None and record_authority != owner:
            raise ForeignAuthorityError("orchestrator assignment belongs to another authority")
        if assignment_ref in seen_refs:
            raise OrchestratorPlacementError("duplicate orchestrator assignment in owner view")
        seen_refs.add(assignment_ref)
        role = str(_field(raw, "role", _payload(raw).get("role", ""))).strip().lower()
        if role != "orchestrator":
            continue
        parent = _field(raw, "parent_assignment_ref") or _field(raw, "supervisor_assignment_ref")
        parent = parent or _payload(raw).get("parent_assignment_ref") or _payload(raw).get("supervisor_assignment_ref")
        if parent is not None:
            raise RecursiveOrchestrationError("orchestrators cannot be subordinate to another assignment")
        status = _status(raw)
        purpose, intended_scope = _purpose_scope(raw)
        records.append(
            OrchestratorSummary(
                assignment_ref=assignment_ref,
                authority=owner,
                principal=_field(raw, "principal", _payload(raw).get("principal")),
                status=status,
                generation=int(_field(raw, "generation", _payload(raw).get("generation", 1))),
                purpose=purpose,
                intended_scope=intended_scope,
                owned_project_refs=(),
            )
        )

    if default_assignment_ref is None:
        pointer = None
    else:
        pointer_authority, pointer, _ = _record_ref(default_assignment_ref)
        if pointer_authority is not None and pointer_authority != owner:
            raise ForeignAuthorityError("default orchestrator pointer belongs to another authority")
    if pointer is not None:
        selected = next((item for item in records if item.assignment_ref == pointer), None)
        if selected is None:
            raise StalePlacementError("default orchestrator pointer is not a current orchestrator assignment")
        if not _active(selected.status):
            raise StalePlacementError("default orchestrator pointer names a retired assignment")

    projected = []
    seen_projects = set()
    owned = {item.assignment_ref: [] for item in records}
    for raw in supervision:
        record_authority = _field(raw, "authority")
        if record_authority is not None and record_authority != owner:
            raise ForeignAuthorityError("project supervision belongs to another authority")
        project_authority, project_ref, project_revision = _record_ref(raw, "project_ref", "project")
        if project_authority is not None and project_authority != owner:
            raise ForeignAuthorityError("supervised project belongs to another authority")
        supervisor_authority, supervisor_ref, _ = _record_ref(raw, "orchestrator_assignment_ref", "orchestrator_assignment", "supervisor")
        if supervisor_authority is not None and supervisor_authority != owner:
            raise ForeignAuthorityError("project supervisor belongs to another authority")
        if project_ref in seen_projects:
            raise OrchestratorPlacementError("project has more than one accountable orchestrator")
        if supervisor_ref not in owned:
            raise StalePlacementError("project points to an unknown or retired orchestrator assignment")
        supervisor = next(item for item in records if item.assignment_ref == supervisor_ref)
        if not _active(supervisor.status):
            raise StalePlacementError("project points to a retired orchestrator assignment")
        seen_projects.add(project_ref)
        projected.append(Supervision(project_ref, supervisor_ref, project_revision))
        owned[supervisor_ref].append(project_ref)

    normalized = tuple(
        OrchestratorSummary(
            item.assignment_ref,
            item.authority,
            item.principal,
            item.status,
            item.generation,
            item.purpose,
            item.intended_scope,
            tuple(sorted(owned[item.assignment_ref])),
        )
        for item in records
    )
    return OrchestratorView(owner, view_revision, pointer, normalized, tuple(projected))


def place_new_project(view: OrchestratorView, project_ref: Any, *, requested_assignment_ref: Any = None, explicit_peer: bool = False) -> PlacementDecision:
    """Choose the accountable supervisor without mutating the owner."""

    project_authority, project, _ = _record_ref(project_ref)
    if project_authority is not None and project_authority != view.authority:
        raise ForeignAuthorityError("project belongs to another authority")
    if view.default_assignment_ref is None:
        raise StalePlacementError("no eligible default orchestrator is configured")
    if requested_assignment_ref is None:
        target = view.default_assignment_ref
    else:
        target_authority, target, _ = _record_ref(requested_assignment_ref)
        if target_authority is not None and target_authority != view.authority:
            raise ForeignAuthorityError("requested orchestrator belongs to another authority")
    view.orchestrator(target)
    if target != view.default_assignment_ref and not explicit_peer:
        raise ExplicitPeerRequired("placing a project on a peer requires the explicit peer path")
    if not _active(view.orchestrator(target).status):
        raise StalePlacementError("requested orchestrator assignment is retired")
    return PlacementDecision(
        action="reuse-default" if target == view.default_assignment_ref else "place-on-explicit-peer",
        project_ref=project,
        accountable_orchestrator_assignment_ref=target,
        default_assignment_ref=view.default_assignment_ref,
        warning=None,
    )


def preview_peer_request(view: OrchestratorView, *, purpose: Any, intended_scope: Any, intended_project_refs: Sequence[Any] = ()) -> PeerPreview:
    """Build the exact warning shown before an exceptional peer request."""

    purpose_value = _text(purpose, "purpose")
    scope_value = _text(intended_scope, "intended_scope")
    refs_list = []
    for item in intended_project_refs:
        item_authority, item_ref, _ = _record_ref(item)
        if item_authority is not None and item_authority != view.authority:
            raise ForeignAuthorityError("intended project belongs to another authority")
        if item_ref not in refs_list:
            refs_list.append(item_ref)
    refs = tuple(refs_list)
    known = {item.project_ref for item in view.supervision}
    overlap = tuple(item for item in refs if item in known)
    warning = None
    if overlap:
        warning = "Existing project supervision overlaps: " + ", ".join(overlap) + ". Keep the current supervisor or transfer explicitly."
    return PeerPreview("request-explicit-peer", purpose_value, scope_value, overlap, warning, view.default_assignment_ref)


def guard_peer_request(
    view: OrchestratorView,
    *,
    requested_by_assignment_ref: Any,
    purpose: Any,
    intended_scope: Any,
    intended_project_refs: Sequence[Any] = (),
    expected_revision: Any,
    overlap_acknowledged: bool = False,
) -> PeerRequest:
    """Validate a deliberate peer relationship before an owner command.

    The returned request is a bounded command input, not a committed peer.
    The caller must still use the existing owner/assignment command port to
    register or bind any assignment.
    """

    if str(expected_revision) != view.revision:
        raise StalePlacementError("orchestrator view revision is stale")
    requester_authority, requester, _ = _record_ref(requested_by_assignment_ref)
    if requester_authority is not None and requester_authority != view.authority:
        raise ForeignAuthorityError("requesting orchestrator belongs to another authority")
    summary = view.orchestrator(requester)
    if not _active(summary.status):
        raise StalePlacementError("retired orchestrator cannot request a peer")
    preview = preview_peer_request(view, purpose=purpose, intended_scope=intended_scope, intended_project_refs=intended_project_refs)
    if preview.overlap_warning is not None and overlap_acknowledged is not True:
        raise OverlapAcknowledgementRequired(preview.overlap_warning)
    # A peer request has no parent and cannot silently change an existing
    # project's accountable supervisor.  Existing relations are carried as
    # evidence for a later explicit transfer command.
    accountable = tuple((item.project_ref, item.orchestrator_assignment_ref) for item in view.supervision if item.project_ref in preview.overlap_project_refs)
    return PeerRequest(
        action="peer-request-accepted",
        requested_by_assignment_ref=requester,
        purpose=preview.purpose,
        intended_scope=preview.intended_scope,
        overlap_project_refs=preview.overlap_project_refs,
        default_assignment_ref=view.default_assignment_ref,
        accountable_supervisor_by_project=accountable,
    )


__all__ = [
    "ExplicitPeerRequired",
    "ForeignAuthorityError",
    "OrchestratorPlacementError",
    "OrchestratorSummary",
    "OrchestratorView",
    "OverlapAcknowledgementRequired",
    "PeerPreview",
    "PeerRequest",
    "PlacementDecision",
    "RecursiveOrchestrationError",
    "StalePlacementError",
    "Supervision",
    "build_orchestrator_view",
    "guard_peer_request",
    "place_new_project",
    "preview_peer_request",
]
