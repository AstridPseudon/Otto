"""Owner-side preparation for one canonical role occurrence.

This module composes the existing assignment and DueRecord command ports. It
does not own a scheduler, Store, provider, or second execution ledger.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from herzchen.contracts import ResourceRef


class OccurrencePreparationError(ValueError):
    """The requested occurrence cannot be joined to current owner state."""


_MODES = {
    ("invoke", "launch"): "fresh_bounded_worker",
    ("resume", "resume"): "continue_existing",
    ("resume", "callback"): "continue_existing",
}

OWNER_TIMEOUT_MAX_SECONDS = 1800


def commit_local_checkpoint(
    worktree: str | Path,
    paths: list[str] | tuple[str, ...],
    *,
    message: str,
) -> dict[str, Any]:
    """Create one owner-authorized local checkpoint without publication.

    Paths are explicit worktree-relative source paths.  Existing staged changes
    outside that set are rejected so an owner service cannot accidentally fold
    another worker's edits into the checkpoint.
    """

    root = Path(worktree).resolve()
    if not (root / ".git").is_dir():
        raise OccurrencePreparationError("local checkpoint requires a Git worktree")
    if not isinstance(message, str) or not message.strip() or len(message) > 240:
        raise OccurrencePreparationError("checkpoint message must be 1-240 characters")
    if not isinstance(paths, (list, tuple)) or not paths:
        raise OccurrencePreparationError("checkpoint paths must be a non-empty list")
    selected: list[str] = []
    for value in paths:
        if not isinstance(value, str) or not value.strip() or os.path.isabs(value):
            raise OccurrencePreparationError("checkpoint paths must be relative text")
        candidate = (root / value).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise OccurrencePreparationError("checkpoint path escapes the worktree") from exc
        relative = str(candidate.relative_to(root))
        if relative == ".git" or relative.startswith(".git/"):
            raise OccurrencePreparationError("checkpoint path cannot select Git metadata")
        if relative not in selected:
            selected.append(relative)

    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            check=check, timeout=30,
        )

    staged = [line for line in git("diff", "--cached", "--name-only").stdout.splitlines() if line]
    foreign = sorted(set(staged) - set(selected))
    if foreign:
        raise OccurrencePreparationError(
            "checkpoint has staged paths outside the request: " + ", ".join(foreign)
        )
    git("add", "--", *selected)
    staged_selected = [line for line in git("diff", "--cached", "--name-only", "--", *selected).stdout.splitlines() if line]
    if not staged_selected:
        return {"outcome": "replayed", "committed": False, "reason": "no selected changes"}
    committed = git(
        "-c", "user.name=Otto Owner", "-c", "user.email=otto-owner@localhost",
        "commit", "-m", message.strip(), "--", *selected,
    )
    head = git("rev-parse", "HEAD").stdout.strip()
    return {
        "outcome": "committed", "committed": True, "commit": head,
        "paths": staged_selected, "message": message.strip(),
        "stdout": committed.stdout.strip(),
    }


def validate_owner_timeout_seconds(requested: int) -> int:
    """Validate one ordinary host timeout before an occurrence is saved.

    The ordinary owner route has no extended-timeout exception.  Keeping this
    check at the preparation boundary prevents a Due from being committed only
    to fail later in the adapter or host constructor.
    """

    if (
        isinstance(requested, bool)
        or not isinstance(requested, int)
        or not 60 < requested <= OWNER_TIMEOUT_MAX_SECONDS
    ):
        raise OccurrencePreparationError(
            f"timeout_seconds must be between 61 and {OWNER_TIMEOUT_MAX_SECONDS}"
        )
    return requested


def _value(source: Any, name: str) -> Any:
    return source.get(name) if isinstance(source, Mapping) else getattr(source, name, None)


def _instant(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OccurrencePreparationError("continuation record has no finite timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OccurrencePreparationError("continuation timestamp is invalid") from exc


def _same_ref(left: Any, right: Any) -> bool:
    return (
        isinstance(left, Mapping)
        and isinstance(right, Mapping)
        and all(left.get(key) == right.get(key) for key in ("authority", "kind", "id"))
    )


def derive_manager_continuation_request(
    settled_due: Any, reports: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]
) -> dict[str, Any] | None:
    """Recover a manager's explicit next action from canonical reports.

    Navigation JSON may be absent after a crash.  A continuation exists only
    when a report from this exact settled manager occurrence requested it.
    """

    if not (
        _value(settled_due, "stop_state") == "completed"
        and _value(settled_due, "completion_state") == "succeeded"
        and _value(settled_due, "in_flight_request") is None
        and _value(settled_due, "delivery_state") == "returned"
    ):
        raise OccurrencePreparationError("manager occurrence is not a settled success")
    started = _instant(_value(settled_due, "anchor"))
    completed = _instant(_value(settled_due, "completed_at"))
    assignment_ref = _value(settled_due, "assignment_ref")
    candidates: list[tuple[datetime, str, Mapping[str, Any], Mapping[str, Any]]] = []
    for report in reports:
        value = report.get("value")
        ref = report.get("ref")
        if (
            report.get("kind") != "report"
            or not _same_ref(report.get("assignment"), assignment_ref)
            or not isinstance(value, Mapping)
            or value.get("schema") != "otto.manager-progress.v1"
            or value.get("continue_requested") is not True
            or not isinstance(ref, Mapping)
        ):
            continue
        recorded = _instant(value.get("recorded_at"))
        if started <= recorded <= completed:
            candidates.append((recorded, str(ref.get("id", "")), report, value))
    if not candidates:
        return None
    _, _, report, value = max(candidates, key=lambda item: (item[0], item[1]))
    result = _value(settled_due, "last_result")
    result = result if isinstance(result, Mapping) else {}
    return {
        "schema": "otto.manager-continuation-request.v1",
        "task_alias": value.get("task_alias"),
        "next_action": value.get("next_action"),
        "report_ref": dict(report["ref"]),
        "logical_request_key": value.get("logical_request_key") or "continue:" + str(report["ref"].get("id")),
        "requested_at": value.get("recorded_at"),
        "settled_schedule_id": _value(settled_due, "schedule_id"),
        "settled_turn_id": result.get("observed_turn_id"),
        "physical_session_id": result.get("physical_session_id"),
        "state": "ready",
    }


def read_project_progress_reports(reader: Any, project_ref: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read immutable manager progress through the owner's public event reader."""

    if not all(callable(getattr(reader, name, None)) for name in ("list_events", "get_record")):
        raise OccurrencePreparationError("owner event reader is unavailable")
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in reader.list_events():
        subject = getattr(event, "subject", None)
        if getattr(subject, "kind", None) != "wrk.report" or subject.id in seen:
            continue
        seen.add(subject.id)
        record = reader.get_record(subject)
        payload = getattr(record, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        value = payload.get("value")
        linked = value.get("project_ref") if isinstance(value, Mapping) else None
        if not _same_ref(linked, project_ref):
            continue
        ref = getattr(record, "ref", None)
        assignment = payload.get("assignment")
        if not isinstance(assignment, Mapping) or not hasattr(ref, "to_dict"):
            continue
        reports.append({
            "ref": ref.to_dict(), "assignment": dict(assignment),
            "kind": payload.get("observation_kind"), "value": dict(value),
        })
    return reports


def build_manager_callback_due(
    prior: Any,
    *,
    schedule_id: str,
    request_key: str,
    assignment_ref: Mapping[str, Any],
    guide_ref: Mapping[str, Any],
    mandate_ref: Mapping[str, Any],
    due_at: str,
    timeout_seconds: int,
) -> Any:
    """Derive the next same-session manager callback from a settled Due.

    The caller still commits and launches through the existing Due/role-runtime
    ports.  This function only performs the common state transition and keeps
    run-specific policy outside the execution layer.
    """

    if not (
        getattr(prior, "stop_state", None) == "completed"
        and getattr(prior, "completion_state", None) == "succeeded"
        and getattr(prior, "in_flight_request", None) is None
        and getattr(prior, "delivery_state", None) == "returned"
    ):
        raise OccurrencePreparationError("prior manager occurrence is not a settled success")
    target = getattr(prior, "target", None)
    result = getattr(prior, "last_result", None)
    session = result.get("physical_session_id") if isinstance(result, Mapping) else None
    if not isinstance(session, str) or not session.strip():
        raise OccurrencePreparationError("settled manager occurrence has no native session")
    if not isinstance(target, Mapping):
        raise OccurrencePreparationError("prior manager target is unavailable")
    timeout_seconds = validate_owner_timeout_seconds(timeout_seconds)
    next_target = dict(target)
    next_target.update({
        "assignment_ref": dict(assignment_ref),
        "mandate_ref": dict(mandate_ref),
        "native_id": session,
    })
    return replace(
        prior,
        schedule_id=schedule_id,
        instruction="Resume the same manager from current canonical status and continue ready work.",
        anchor=due_at,
        due_at=due_at,
        last_covered_slot=0,
        invocation_identity=request_key,
        in_flight_request=request_key,
        delivery_state="ready",
        assignment_ref=dict(assignment_ref),
        target=next_target,
        purpose="Canonical manager callback continuation",
        host_state="active",
        execution_mode="continue_existing",
        context_refs=(dict(guide_ref), dict(mandate_ref)),
        timeout_seconds=timeout_seconds,
        stop_state="active",
        last_completed_request=None,
        last_result=None,
        delivered_at=None,
        delivery_evidence=None,
        completed_at=None,
        completion_state="none",
        completion_evidence=None,
        host_evidence={},
    )


def prepare_current_assignment_occurrence(
    *, due_port: Any, assignments: Any, binding: Any, due: Any,
    assignment_ref: Mapping[str, Any], assignment_owner: str,
    operation: str, lifecycle: str, request_key: str,
) -> dict[str, Any]:
    """Create a Due on the adoption base, then reconcile it to current refs.

    Both committed stages are returned so a caller can distinguish a partial
    effect from a failure before any owner mutation.
    """

    if not isinstance(request_key, str) or not request_key.strip():
        raise OccurrencePreparationError("request_key is required")
    expected_mode = _MODES.get((operation, lifecycle))
    if expected_mode is None:
        raise OccurrencePreparationError("unsupported operation/lifecycle pair")
    if getattr(due, "execution_mode", None) != expected_mode:
        raise OccurrencePreparationError(
            "execution_mode must be " + expected_mode + " for " + operation + "/" + lifecycle
        )
    target = getattr(due, "target", None)
    if not isinstance(target, Mapping):
        raise OccurrencePreparationError("due target is unavailable")
    native_id = target.get("native_id")
    if expected_mode == "continue_existing" and not isinstance(native_id, str):
        raise OccurrencePreparationError("continue_existing requires target.native_id")
    if expected_mode != "continue_existing" and native_id is not None:
        raise OccurrencePreparationError("fresh occurrence cannot claim an existing native session")
    timeout_seconds = validate_owner_timeout_seconds(getattr(due, "timeout_seconds", None))

    try:
        current = assignments.get(ResourceRef.from_dict(assignment_ref))
        actor = binding.authenticated_actor(assignment_owner)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise OccurrencePreparationError("current assignment or owner actor is unavailable") from exc
    if actor.actor != assignment_owner:
        raise OccurrencePreparationError("authenticated actor differs from assignment owner")
    if assignment_owner not in {getattr(current, "manager", None), getattr(current, "principal", None)}:
        raise OccurrencePreparationError("resource adoption actor is not assignment owner")

    base_value = getattr(current, "payload", {}).get("resource_adoption_base_ref")
    base_ref = ResourceRef.from_dict(base_value) if isinstance(base_value, Mapping) else current.ref
    target_value = dict(target)
    target_value["assignment_ref"] = base_ref.to_dict()
    prepared = replace(due, assignment_ref=base_ref.to_dict(), target=target_value)
    created = due_port.save_due(
        due.schedule_id, prepared.to_dict(), request_id=request_key + ":create", expected_version=0,
    )
    result = {
        "outcome": "partial", "stage": "due_created", "schedule_id": due.schedule_id,
        "assignment_base_ref": base_ref.to_dict(), "assignment_current_ref": current.ref.to_dict(),
        "due_version": created["version"], "replay_key": request_key,
        "execution_mode": expected_mode, "actor": actor.actor,
        "timeout_seconds": timeout_seconds,
    }
    try:
        reconciled = due_port.reconcile_assignment_resources(
            due.schedule_id, assignment_ref=current.ref.to_dict(),
            expected_version=created["version"], request_id=request_key + ":resources",
        )
    except Exception as exc:
        return {
            **result, "error": {"code": type(exc).__name__, "message": str(exc)},
            "next_action": "inspect the named Due before retrying resource reconciliation",
        }
    return {
        **result, "outcome": "committed", "stage": "resources_reconciled",
        "due_version": reconciled["version"],
        "next_action": "invoke the admitted role against this exact occurrence",
    }


__all__ = [
    "OccurrencePreparationError", "OWNER_TIMEOUT_MAX_SECONDS", "build_manager_callback_due",
    "derive_manager_continuation_request",
    "prepare_current_assignment_occurrence", "read_project_progress_reports",
    "validate_owner_timeout_seconds",
]
