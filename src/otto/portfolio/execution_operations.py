"""Owner-side preparation for one canonical role occurrence.

This module composes the existing assignment and DueRecord command ports. It
does not own a scheduler, Store, provider, or second execution ledger.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from herzchen.contracts import ResourceRef


class OccurrencePreparationError(ValueError):
    """The requested occurrence cannot be joined to current owner state."""


_MODES = {
    ("invoke", "launch"): "fresh_bounded_worker",
    ("resume", "resume"): "continue_existing",
    ("resume", "callback"): "continue_existing",
}

OWNER_TIMEOUT_MAX_SECONDS = 1800


def complete_task_from_command(
    portfolio: Any, *, request: Mapping[str, Any], project_ref: Mapping[str, Any],
    task_ref: Mapping[str, Any], manager_assignment_ref: Mapping[str, Any],
    manager_actor: str, manager_generation: int,
) -> Mapping[str, Any]:
    """Forward completion evidence to the existing guarded portfolio operation.

    The owner supplies current scope and manager pins. Command input supplies
    evidence only; this adapter neither accepts a worker result nor bypasses
    the public assessment/completion guards.
    """
    for field in ("evidence_refs", "gate_refs", "evidence_hashes"):
        if not isinstance(request.get(field), list) or not request[field]:
            raise ValueError(field + " must be a non-empty list")

    def completion_ref(value: Any) -> dict[str, Any]:
        return ResourceRef.from_dict(json.loads(value)).to_dict()

    try:
        evidence_refs = [completion_ref(value) for value in request["evidence_refs"]]
        gate_refs = [completion_ref(value) for value in request["gate_refs"]]
        evidence_hashes = dict(value.split("=", 1) for value in request["evidence_hashes"])
        optional = {
            name: completion_ref(request[name])
            for name in ("candidate_ref", "result_ref", "attempt_ref")
            if request.get(name) is not None
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("valid owner resource-ref JSON and label=sha256 hashes are required") from exc
    source_set_digest = request.get("source_set_digest")
    if source_set_digest is not None:
        if not isinstance(source_set_digest, str) or not source_set_digest.strip():
            raise ValueError("source_set_digest must be non-blank text")
        optional["source_set_digest"] = source_set_digest
    return portfolio.complete_task(
        project_ref, task_ref, manager_assignment_ref,
        actor=manager_actor, request_id=request.get("request_key"),
        expected_generation=manager_generation,
        expected_project_revision=project_ref["revision"],
        expected_task_revision=task_ref["revision"],
        disposition=request.get("disposition"), evidence_refs=evidence_refs,
        evidence_hashes=evidence_hashes, gate_refs=gate_refs, **optional,
    )


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
    git_metadata = root / ".git"
    # Linked worktrees intentionally expose .git as a file pointing at the
    # owning repository's worktree metadata.  Validate the actual Git
    # identity through Git rather than requiring an in-place .git directory;
    # the owner route must work for the maintained linked checkout as well as
    # for an ordinary repository.
    if git_metadata.is_symlink() or not (git_metadata.is_dir() or git_metadata.is_file()):
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

    identity = git("rev-parse", "--is-inside-work-tree")
    if identity.stdout.strip() != "true":
        raise OccurrencePreparationError("local checkpoint requires a Git worktree")

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


def manager_continuation_schedule_id(assignment_ref: Mapping[str, Any], report_key: str) -> str:
    """Canonical callback identity shared by preparation and owner disposition."""
    value = json.dumps([dict(assignment_ref), report_key], sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False).encode()
    return "manager-callback-" + hashlib.sha256(value).hexdigest()[:28]


def manager_worker_result_schedule_id(request_key: str) -> str:
    """Exact worker-result callback identity, before host locator refresh."""
    if not isinstance(request_key, str) or not request_key.startswith("worker-result:"):
        raise ValueError("worker-result request key required")
    value = json.dumps(request_key, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "manager-worker-callback-" + hashlib.sha256(value).hexdigest()[:28]


def _manager_report_context(report: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Carry bounded evidence from the exact durable report, without granting acceptance.

    Existing report callers can put reviewed source/result refs in summary.
    Owner API callers may also supply structured review/lifecycle refs. These
    stay attributed to this report; task completion still needs owner gates.
    """
    summary = value.get("summary")
    evidence = value.get("continuation_evidence")
    if summary is None and evidence is None:
        return None
    if summary is not None and (not isinstance(summary, str) or not summary.strip()):
        raise OccurrencePreparationError("manager report context summary must be non-blank text")
    if evidence is not None:
        if not isinstance(evidence, Mapping) or set(evidence) - {"accepted_review_refs", "lifecycle_evidence_refs"}:
            raise OccurrencePreparationError("manager continuation evidence fields are unsupported")
        for refs in evidence.values():
            if not isinstance(refs, list) or len(refs) > 16 or any(not isinstance(ref, (str, Mapping)) for ref in refs):
                raise OccurrencePreparationError("manager continuation evidence must contain bounded reference lists")
    context = {"schema": "otto.manager-continuation-report-context.v1", "report_ref": dict(report["ref"]),
               "logical_request_key": value.get("logical_request_key") or "continue:" + str(report["ref"].get("id")),
               "recorded_at": value.get("recorded_at"),
               "summary": summary, "continuation_evidence": evidence,
               "acceptance_authority": "ordinary owner task and assessment gates remain required"}
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 16384:
        raise OccurrencePreparationError("manager continuation evidence exceeds its bounded context size")
    return json.loads(encoded)


def derive_manager_continuation_request(
    settled_due: Any, reports: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *, report_key: str | None = None,
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
    if report_key is not None:
        if not isinstance(report_key, str) or not report_key.strip():
            raise OccurrencePreparationError("report_key must be non-blank text")
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
        explicit = (report_key is not None and value.get("logical_request_key") == report_key
                    and _same_ref(value.get("project_ref"), (_value(settled_due, "target") or {}).get("project_ref")))
        if (report_key is None and started <= recorded <= completed) or (explicit and recorded >= started):
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
        "explicit_service_request": report_key is not None,
        "report_context": _manager_report_context(report, value),
    }


def read_project_progress_reports(reader: Any, project_ref: Mapping[str, Any], *,
                                  assignment_refs: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Read immutable manager progress through the owner's public event reader."""

    if not all(callable(getattr(reader, name, None)) for name in ("list_events", "get_record")):
        raise OccurrencePreparationError("owner event reader is unavailable")
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    if assignment_refs is None:
        events = ((event, None) for event in reader.list_events())
    else:
        # The owner supplies all assignments from the selected canonical
        # ProjectSheet, including historical/project/task roles. Narrow the
        # existing immutable event reader before it hydrates native history.
        ids = []
        for assignment in assignment_refs:
            if (not isinstance(assignment, Mapping) or assignment.get("authority") != project_ref.get("authority")
                    or assignment.get("kind") != "wrk.assignment" or not isinstance(assignment.get("id"), str)
                    or not assignment["id"]):
                raise OccurrencePreparationError("progress report streams require exact local assignment references")
            if assignment["id"] not in ids:
                ids.append(assignment["id"])
        events = ((event, identity) for identity in sorted(ids) for event in reader.list_events(stream="report:" + identity))
    for event, stream_assignment in events:
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
        if stream_assignment is not None and (assignment.get("id") != stream_assignment
                or assignment.get("kind") != "wrk.assignment"
                or assignment.get("authority") != project_ref.get("authority")):
            continue
        reports.append({
            "ref": ref.to_dict(), "assignment": dict(assignment),
            "kind": payload.get("observation_kind"), "value": dict(value),
        })
    return reports


def _status_projection(value: Any, *, reason: str) -> dict[str, Any]:
    """Represent one status layer without treating absence as failure."""

    if value is None:
        return {"state": "unknown", "value": None, "reason": reason}
    return {"state": "known", "value": value, "reason": None}


def _transport_state(operation: Mapping[str, Any]) -> tuple[str, bool | None]:
    raw = operation.get("transport_completion")
    if isinstance(raw, Mapping):
        state = raw.get("state") or raw.get("status")
        completed = raw.get("completed")
        if isinstance(state, str):
            state = state.strip().lower()
            if state in {"completed", "complete", "returned", "sent", "succeeded"}:
                return "completed", True
            if state in {"pending", "prepared", "active", "in_flight"}:
                return "pending", False
            if state in {"unknown", "uncertain", "lost"}:
                return "unknown", None
        if type(completed) is bool:
            return ("completed" if completed else "pending"), completed
    state = operation.get("delivery_state")
    if state in {"returned", "sent", "succeeded", "completed"}:
        return "completed", True
    if state in {"ready", "pending", "prepared", "active", "in_flight"}:
        return "pending", False
    if state in {"unknown", "uncertain"} or operation.get("uncertain_live_effect") is True:
        return "unknown", None
    return "not_started", False


def _settlement_state(operation: Mapping[str, Any]) -> tuple[str, bool | None]:
    explicit = operation.get("task_settlement")
    if isinstance(explicit, Mapping):
        state = explicit.get("state") or explicit.get("status")
        settled = explicit.get("settled")
        if state in {"settled", "completed", "succeeded"} or settled is True:
            return "settled", True
        if state in {"pending", "active", "in_flight"} or settled is False:
            return "pending", False
        if state in {"unknown", "uncertain"}:
            return "unknown", None
    completion = operation.get("completion_state")
    if completion == "succeeded" and operation.get("stop_state", "completed") == "completed":
        return "settled", True
    if completion in {"none", "pending", "active"} or operation.get("stop_state") == "active":
        return "pending", False
    if completion in {"unknown", "uncertain"}:
        return "unknown", None
    return "not_started", False


def _canonical_completion(canonical_project: Mapping[str, Any] | None) -> dict[str, Any]:
    value = canonical_project if isinstance(canonical_project, Mapping) else {}
    lifecycle = value.get("lifecycle", value.get("state"))
    recorded = value.get("project_completion_recorded")
    if type(recorded) is not bool:
        recorded = None if lifecycle is None else lifecycle == "completed"
    reconciliation = value.get("reconciliation")
    reconciliation = dict(reconciliation) if isinstance(reconciliation, Mapping) else None
    if lifecycle == "completed":
        state = "completed" if recorded is True else "unknown" if recorded is None else "pending"
    elif lifecycle is None:
        state = "unknown"
    else:
        state = "in_progress"
    return {
        "state": state,
        "project_completion_recorded": recorded,
        "lifecycle": lifecycle,
        "project_close_ready": value.get("project_close_ready") is True,
        "reconciliation": reconciliation,
        "source_refs": list(value.get("source_refs", ())) if isinstance(value.get("source_refs"), list) else [],
    }


def _next_supported_remedy(
    operation: Mapping[str, Any], *,
    canonical_project: Mapping[str, Any],
    pending_help: Mapping[str, Any],
    blockers: list[Any],
) -> dict[str, Any]:
    """Return one executable command-shaped remedy, never a prose prohibition."""

    explicit = operation.get("supported_next_remedy") or operation.get("next_remedy")
    if isinstance(explicit, Mapping):
        return {**dict(explicit), "supported": explicit.get("supported", True)}
    if pending_help.get("status") in {"pending", "unknown", "unresolved"}:
        delivery_id = pending_help.get("delivery_id")
        if isinstance(delivery_id, str) and delivery_id:
            return {"supported": True, "operation": "read-help", "command": "read-help --delivery-id " + delivery_id,
                    "reason": "reconcile the retained help delivery before any retry"}
        return {"supported": True, "operation": "read-help", "command": "read-help",
                "reason": "read the current help destination and delivery state"}
    transport, _ = _transport_state(operation)
    if transport == "unknown":
        return {"supported": True, "operation": "status", "command": "status",
                "reason": "reconcile the exact retained operation before retrying"}
    settlement, _ = _settlement_state(operation)
    if settlement in {"pending", "unknown"}:
        schedule = operation.get("schedule_id")
        if isinstance(schedule, str) and schedule:
            role = operation.get("role")
            if role == "worker" and isinstance(operation.get("task"), str) and isinstance(operation.get("principal"), str):
                command = "worker-status --task {0} --principal {1} --schedule-id {2}".format(
                    operation["task"], operation["principal"], schedule)
            else:
                handle = operation.get("retained_handle")
                command = ("command-status --request-id " + handle
                    if isinstance(handle, str) and handle and all(c in "0123456789abcdef" for c in handle)
                    else "status")
            return {"supported": True, "operation": "reconcile-settlement", "command": command,
                    "reason": "settle the retained operation without a provider retry"}
    if blockers:
        return {"supported": False, "operation": "owner-blocked", "command": None,
                "reason": "current scoped blockers must be resolved by their owning operation"}
    if (canonical_project.get("project_completion_recorded") is not True
            and canonical_project.get("project_close_ready") is True):
        return {"supported": True, "operation": "finish-project", "command": "finish-project",
                "reason": "request guarded project close with current task evidence and dispositions"}
    return {"supported": True, "operation": "status", "command": "status",
            "reason": "read current canonical state"}


def compact_operation_status(
    operation: Mapping[str, Any] | None = None, *,
    accepted_review: Mapping[str, Any] | None = None,
    canonical_project: Mapping[str, Any] | None = None,
    required_scope: Any = None,
    blockers: list[Any] | tuple[Any, ...] = (),
    pending_help: Mapping[str, Any] | None = None,
    instruction_provenance: Mapping[str, Any] | None = None,
    supported_next_remedy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one operation into independently truthful status layers.

    Transport return, review acceptance, native task settlement, and canonical
    project completion are deliberately separate.  This is a read-only
    projection; it does not infer acceptance from transport or turn a
    recommendation into an owner restriction.
    """

    current = dict(operation) if isinstance(operation, Mapping) else {}
    transport_state, transport_completed = _transport_state(current)
    settlement_state, settled = _settlement_state(current)
    review = dict(accepted_review) if isinstance(accepted_review, Mapping) else {
        "state": "unknown", "accepted": None, "reason": "no accepted review readback was supplied"
    }
    project = _canonical_completion(canonical_project)
    scope = _status_projection(required_scope, reason="current required scope is not exposed")
    scoped_blockers = list(blockers) if isinstance(blockers, (list, tuple)) else []
    help_value = dict(pending_help) if isinstance(pending_help, Mapping) else {
        "state": "known", "status": "none", "destination": None
    }
    provenance = _status_projection(instruction_provenance, reason="instruction provenance is not exposed")
    remedy = dict(supported_next_remedy) if isinstance(supported_next_remedy, Mapping) else _next_supported_remedy(
        current, canonical_project=project, pending_help=help_value, blockers=scoped_blockers)
    return {
        "schema": "otto.operation-status.v1",
        "transport_completion": {"state": transport_state, "completed": transport_completed,
                                  "schedule_id": current.get("schedule_id"), "request_id": current.get("request_id")},
        "accepted_review": review,
        "task_settlement": {"state": settlement_state, "settled": settled,
                             "schedule_id": current.get("schedule_id")},
        "canonical_project_completion": project,
        "current_required_scope": scope,
        "blockers": scoped_blockers,
        "blocked_operation": bool(scoped_blockers),
        "pending_help": help_value,
        "instruction_provenance": provenance,
        "supported_next_remedy": remedy,
        "agent_suggestion": current.get("agent_suggestion"),
        "read_only": True,
        "dispatch": False,
        "launch": False,
    }


def compact_project_status(
    project_view: Mapping[str, Any],
    *,
    task_refs: Mapping[str, Mapping[str, Any]],
    reports: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    occurrences: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    help_issues: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    required_scope: Any = None,
    instruction_provenance: Mapping[str, Any] | None = None,
    operation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a useful read-only status without embedding raw receipts.

    The project sheet and Due records remain authoritative.  This projection
    keeps their current refs, lifecycle, latest manager report, review and
    acceptance observations, scoped blockers, and active or terminal native
    handles while leaving full receipts available by ref.  Historical
    occurrences are retained as compact observations so an uncertain effect
    cannot hide an unrelated accepted result.
    """

    if not isinstance(project_view, Mapping):
        raise OccurrencePreparationError("project view is unavailable")
    tasks = project_view.get("tasks")
    if not isinstance(tasks, list):
        raise OccurrencePreparationError("project view has no task list")

    alias_by_id = {
        str(ref.get("id")): alias
        for alias, ref in task_refs.items()
        if isinstance(alias, str) and isinstance(ref, Mapping) and ref.get("id")
    }
    report_by_alias: dict[str, Mapping[str, Any]] = {}
    for report in reports:
        value = report.get("value") if isinstance(report, Mapping) else None
        alias = value.get("task_alias") if isinstance(value, Mapping) else None
        if alias not in task_refs:
            continue
        current = report_by_alias.get(alias)
        current_value = current.get("value") if isinstance(current, Mapping) else {}
        if str(value.get("recorded_at", "")) >= str(current_value.get("recorded_at", "")):
            report_by_alias[alias] = report

    occurrences_by_alias: dict[str, list[Mapping[str, Any]]] = {}
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            continue
        if occurrence.get("role") == "manager":
            continue
        target = occurrence.get("target")
        task_ref = target.get("task_ref") if isinstance(target, Mapping) else None
        alias = alias_by_id.get(str(task_ref.get("id"))) if isinstance(task_ref, Mapping) else None
        if alias is None:
            continue
        occurrences_by_alias.setdefault(alias, []).append(occurrence)

    def occurrence_order(value: Mapping[str, Any]) -> tuple[str, str, int]:
        try:
            version = int(value.get("version", 0))
        except (TypeError, ValueError):
            version = 0
        return (
            str(value.get("completed_at") or value.get("delivered_at")
                or value.get("due_at") or value.get("anchor") or ""),
            str(value.get("schedule_id") or ""),
            version,
        )

    def compact_occurrence(value: Mapping[str, Any]) -> dict[str, Any]:
        last_result = value.get("last_result")
        last_result = last_result if isinstance(last_result, Mapping) else {}
        host_evidence = value.get("host_evidence")
        host_evidence = host_evidence if isinstance(host_evidence, Mapping) else {}
        host_attempt = host_evidence.get("gateway_attempt")
        host_attempt = host_attempt if isinstance(host_attempt, Mapping) else {}
        attempt_result = host_attempt.get("result")
        attempt_result = attempt_result if isinstance(attempt_result, Mapping) else {}
        return {
            "schedule_id": value.get("schedule_id"),
            "version": value.get("version"),
            "delivery_state": value.get("delivery_state"),
            "host_state": value.get("host_state"),
            "completion_state": value.get("completion_state"),
            "physical_session_id": (
                last_result.get("physical_session_id")
                or attempt_result.get("physical_session_id")
                or host_attempt.get("physical_session_id")
            ),
            "turn_id": last_result.get("observed_turn_id") or attempt_result.get("observed_turn_id"),
            "result": last_result or None,
            "uncertain_live_effect": (
                value.get("uncertain_live_effect") is True
                or value.get("delivery_state") in {"unknown", "uncertain"}
                or value.get("completion_state") in {"unknown", "uncertain"}
                or last_result.get("outcome") in {"unknown", "uncertain", "response_lost"}
            ),
        }

    def projection_value(value: Any, *, source_refs: list[Any], reason: str) -> dict[str, Any]:
        if value is None:
            return {"state": "unknown", "value": None, "source_refs": source_refs, "reason": reason}
        return {"state": "known", "value": value, "source_refs": source_refs, "reason": None}

    def accepted_decisions(decisions: Any) -> dict[str, Any]:
        if not isinstance(decisions, list):
            return projection_value(None, source_refs=[], reason="owner review decisions are not exposed")
        accepted = []
        refs = []
        for decision in decisions:
            if not isinstance(decision, Mapping):
                continue
            disposition = str(decision.get("disposition", decision.get("status", ""))).lower()
            if decision.get("accepted") is True or disposition in {"accept", "accepted", "accepted-for-task", "accepted-for-project"}:
                accepted.append(decision)
                if isinstance(decision.get("ref"), Mapping):
                    refs.append(dict(decision["ref"]))
        return projection_value(bool(accepted), source_refs=refs, reason="acceptance is an observed decision, not a write")

    def verification_state(task_occurrences: list[Mapping[str, Any]]) -> dict[str, Any]:
        flags = {"verifier_limit": None, "evidence_mismatch": None, "uncertain_live_effect": None}
        refs: list[dict[str, Any]] = []
        for occurrence in task_occurrences:
            compact = compact_occurrence(occurrence)
            result = compact.get("result") if isinstance(compact.get("result"), Mapping) else {}
            for source in (occurrence, result):
                if not isinstance(source, Mapping):
                    continue
                if source.get("verifier_limit") is True or source.get("evidence_verification") in {"unavailable", "unverified", "provisional"}:
                    flags["verifier_limit"] = True
                if source.get("evidence_mismatch") is True or source.get("evidence_verification") in {"mismatch", "mismatched"}:
                    flags["evidence_mismatch"] = True
                if source.get("uncertain_live_effect") is True:
                    flags["uncertain_live_effect"] = True
            if compact["uncertain_live_effect"]:
                flags["uncertain_live_effect"] = True
            if isinstance(occurrence.get("schedule_id"), str):
                refs.append({"schedule_id": occurrence["schedule_id"], "version": occurrence.get("version")})
        return {
            key: projection_value(value, source_refs=refs if value is not None else [],
                                  reason=("no explicit verifier observation" if value is None else None))
            for key, value in flags.items()
        }

    projected: dict[str, Any] = {}
    for item in tasks:
        if not isinstance(item, Mapping):
            continue
        ref = item.get("ref")
        alias = alias_by_id.get(str(ref.get("id"))) if isinstance(ref, Mapping) else None
        if alias is None:
            continue
        authored = item.get("authored") if isinstance(item.get("authored"), Mapping) else {}
        observed = item.get("observed") if isinstance(item.get("observed"), Mapping) else {}
        assignments = observed.get("assignments") if isinstance(observed.get("assignments"), list) else []
        assignment = assignments[-1] if assignments else None
        report = report_by_alias.get(alias)
        report_value = report.get("value") if isinstance(report, Mapping) else None
        task_occurrences = sorted(occurrences_by_alias.get(alias, []), key=occurrence_order)
        occurrence = task_occurrences[-1] if task_occurrences else None
        occurrence_view = None if occurrence is None else compact_occurrence(occurrence)
        decisions = observed.get("decisions")
        if not isinstance(decisions, list):
            decisions = None
        assignment_view = None if not isinstance(assignment, Mapping) else {
            "ref": assignment.get("ref"),
            "principal": (assignment.get("payload") or {}).get("principal"),
            "generation": (assignment.get("payload") or {}).get("generation"),
            "status": (assignment.get("payload") or {}).get("status"),
        }
        readiness = observed.get("readiness")
        readiness = readiness if isinstance(readiness, Mapping) else None
        blockers = [] if readiness is None else [
            {"source": "readiness", "code": key, "value": readiness.get(key)}
            for key in ("blockers", "blocked_by", "blocking_reasons")
            if readiness.get(key)
        ]
        dependencies = observed.get("dependencies", item.get("dependencies"))
        dependency_blockers = [
            dependency for dependency in (dependencies if isinstance(dependencies, list) else [])
            if isinstance(dependency, Mapping)
            and (dependency.get("blocked") is True
                 or dependency.get("severity") == "blocking"
                 or str(dependency.get("state", "")).lower() in {"blocked", "failed"})
        ]
        if dependency_blockers:
            blockers.append({"source": "dependencies", "value": dependency_blockers})
        task_lifecycle = observed.get("lifecycle", authored.get("lifecycle"))
        result_rows = observed.get("results") if isinstance(observed.get("results"), list) else None
        result_refs = [] if result_rows is None else [dict(row["ref"]) for row in result_rows if isinstance(row, Mapping) and isinstance(row.get("ref"), Mapping)]
        projected[alias] = {
            "ref": dict(ref),
            "title": authored.get("title") or authored.get("name"),
            "lifecycle": task_lifecycle,
            "readiness": readiness,
            "assignment": assignment_view,
            "owner": assignment_view,
            "blockers": blockers,
            "blockers_state": projection_value(
                blockers if readiness is not None or dependency_blockers else None, source_refs=[],
                reason=("owner readiness did not expose scoped blockers"
                        if readiness is None and not dependency_blockers else None),
            ),
            "latest_report": None if not isinstance(report, Mapping) else {
                "ref": report.get("ref"),
                "recorded_at": report_value.get("recorded_at"),
                "summary": report_value.get("summary"),
                "next_action": report_value.get("next_action"),
            },
            "occurrence": occurrence_view,
            "execution": {
                "occurrence": occurrence_view,
                "result_refs": result_refs,
                "result_state": projection_value(
                    result_refs, source_refs=result_refs,
                    reason="owner execution results are not exposed" if result_rows is None else None,
                ),
            },
            "review": {
                "decisions": [] if decisions is None else decisions,
                "acceptance_exists": accepted_decisions(decisions),
                "accepted_review": accepted_decisions(decisions),
            },
            "agent_suggestion": None if not isinstance(report_value, Mapping) else report_value.get("next_action"),
            "verification": verification_state(task_occurrences),
            "historical_occurrences": [compact_occurrence(row) for row in task_occurrences],
        }
    project = project_view.get("project")
    observed_project = project.get("observed") if isinstance(project, Mapping) else None
    observed_project = observed_project if isinstance(observed_project, Mapping) else {}
    project_assignments = observed_project.get("assignments")
    project_assignments = project_assignments if isinstance(project_assignments, list) else []
    project_owners = [
        {
            "ref": row.get("ref"),
            "principal": (row.get("payload") or {}).get("principal"),
            "role": (row.get("payload") or {}).get("role"),
            "generation": (row.get("payload") or {}).get("generation"),
            "status": (row.get("payload") or {}).get("status"),
        }
        for row in project_assignments if isinstance(row, Mapping)
    ]
    uncertain = [
        {"task_alias": alias, "occurrence": occurrence}
        for alias, row in projected.items()
        for occurrence in row.get("historical_occurrences", ())
        if occurrence.get("uncertain_live_effect") is True
    ]
    current_occurrences = [row for rows in occurrences_by_alias.values() for row in rows]
    current_occurrence = max(current_occurrences, key=occurrence_order) if current_occurrences else None
    current_alias = None
    if isinstance(operation, Mapping):
        target = operation.get("target")
        target_task = target.get("task_ref") if isinstance(target, Mapping) else operation.get("task_ref")
        if isinstance(target_task, Mapping):
            current_alias = alias_by_id.get(str(target_task.get("id")))
    if current_alias is None and current_occurrence is not None:
        target = current_occurrence.get("target")
        target_task = target.get("task_ref") if isinstance(target, Mapping) else None
        current_alias = alias_by_id.get(str(target_task.get("id"))) if isinstance(target_task, Mapping) else None
    current_row = projected.get(current_alias) if current_alias is not None else None
    if not isinstance(operation, Mapping):
        operation = current_occurrence
    operation = dict(operation) if isinstance(operation, Mapping) else {}
    if current_row is not None and not isinstance(operation.get("accepted_review"), Mapping):
        operation["accepted_review"] = current_row["review"]["accepted_review"]

    project_control = observed_project.get("lifecycle_control")
    project_control = project_control if isinstance(project_control, Mapping) else {}
    canonical_project = {
        "lifecycle": observed_project.get("lifecycle"),
        "project_completion_recorded": observed_project.get("project_completion_recorded"),
        "reconciliation": observed_project.get("reconciliation", project_control.get("reconciliation")),
        "source_refs": [project.get("ref")] if isinstance(project, Mapping) and isinstance(project.get("ref"), Mapping) else [],
    }
    if (not isinstance(canonical_project["project_completion_recorded"], bool)
            and canonical_project["lifecycle"] is not None):
        canonical_project["project_completion_recorded"] = canonical_project["lifecycle"] == "completed"
    if required_scope is None:
        required_scope = project_view.get("required_scope") or observed_project.get("required_scope")
    if required_scope is None:
        required_scope = {
            "task_aliases": list(task_refs),
            "task_refs": [dict(ref) for ref in task_refs.values() if isinstance(ref, Mapping)],
        }
    current_blockers: list[Any] = []
    project_readiness = observed_project.get("readiness")
    if isinstance(project_readiness, Mapping):
        for key in ("blockers", "blocked_by", "blocking_reasons"):
            if project_readiness.get(key):
                current_blockers.append({"source": "project.readiness", "code": key, "value": project_readiness[key]})
    if current_row is not None:
        current_blockers.extend(current_row.get("blockers", ()))
    if isinstance(operation.get("blockers"), list):
        current_blockers.extend(operation["blockers"])

    pending_help: dict[str, Any] = {"state": "known", "status": "none", "destination": None}
    open_help = [item for item in help_issues if isinstance(item, Mapping) and item.get("state") == "open"]
    if open_help:
        issue = open_help[-1]
        deliveries = issue.get("deliveries") if isinstance(issue.get("deliveries"), list) else []
        delivery = deliveries[-1] if deliveries and isinstance(deliveries[-1], Mapping) else {}
        pending_help = {
            "state": "known", "status": delivery.get("state") or issue.get("routing_state") or "pending",
            "issue_id": issue.get("issue_id"), "purpose": issue.get("purpose"),
            "destination": issue.get("current_owner_ref"), "delivery_id": delivery.get("delivery_id"),
            "resolution": issue.get("state"),
        }
    provenance = instruction_provenance
    if provenance is None:
        provenance = operation.get("instruction_provenance")
    if provenance is None:
        target = operation.get("target")
        if isinstance(target, Mapping):
            provenance = {key: target[key] for key in ("project_ref", "task_ref", "assignment_ref", "mandate_ref", "generation", "context_refs") if key in target}
    review = current_row["review"]["accepted_review"] if current_row is not None else _status_projection(None, reason="no current task review readback")
    operation_status = compact_operation_status(operation, accepted_review=review,
        canonical_project=canonical_project, required_scope=required_scope,
        blockers=current_blockers, pending_help=pending_help,
        instruction_provenance=provenance)
    reconciliation = canonical_project.get("reconciliation")
    settlement_pending = (None if not isinstance(reconciliation, Mapping)
                          else reconciliation.get("status") != "reconciled")
    return {
        "schema": "otto.project-status.v1",
        "project_ref": (project or {}).get("ref") if isinstance(project, Mapping) else None,
        "lifecycle": observed_project.get("lifecycle"),
        "readiness": observed_project.get("readiness"),
        "owners": project_owners,
        "tasks_lifecycle": {alias: row.get("lifecycle") for alias, row in projected.items()},
        "historical_uncertain_effects": uncertain,
        "operation_status": operation_status,
        "transport_completion": operation_status["transport_completion"],
        "accepted_review": operation_status["accepted_review"],
        "task_settlement": operation_status["task_settlement"],
        "canonical_project_completion": operation_status["canonical_project_completion"],
        "current_required_scope": operation_status["current_required_scope"],
        "blockers": current_blockers,
        "blocked_operation": bool(current_blockers),
        "pending_help": pending_help,
        "instruction_provenance": operation_status["instruction_provenance"],
        "agent_suggestion": None if current_row is None else current_row.get("agent_suggestion"),
        "project_completion_recorded": canonical_project["project_completion_recorded"],
        "settlement_pending": settlement_pending,
        "canonical_lifecycle": canonical_project.get("lifecycle"),
        "reconciliation": reconciliation,
        "supported_next_remedy": operation_status["supported_next_remedy"],
        "acceptance_exists": (
            True if any(row.get("review", {}).get("acceptance_exists", {}).get("value") is True for row in projected.values())
            else False if any(row.get("review", {}).get("acceptance_exists", {}).get("state") == "known" for row in projected.values())
            else None
        ),
        "writes_performed": 0,
        "read_only": True,
        "dispatch": False,
        "launch": False,
        "supported_operations": {
            "status": "read current owner-backed project/task/execution/review state",
            "assessment_coverage": "read scoped assessment results and accepted decisions when the assessment owner is injected",
            "completion_gate": "read provisional completion blockers; records no acceptance",
            "complete_task": "request guarded owner task completion with exact current refs and evidence",
            "project_lifecycle": "read or request a guarded lifecycle transition through the existing owner operation",
        },
        "tasks": projected,
    }


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
    native_adapter: str | None = None,
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
        # The prepared callback has no native admission of its own. Retain
        # the exact settled owner occurrence that authenticated this session.
        "native_binding": {"schedule_id": prior.schedule_id,
            "due_sha256": hashlib.sha256(json.dumps(prior.to_dict(), sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()},
    })
    if native_adapter is not None:
        if not isinstance(native_adapter, str) or not native_adapter.strip():
            raise OccurrencePreparationError("callback requires the current host adapter identity")
        # This is a distinct prospective occurrence. Historical target/admission
        # pins remain untouched; recovered callbacks retain their original route.
        next_target["native_adapter"] = native_adapter
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
    operation: str, lifecycle: str, request_key: str, portfolio: Any = None,
) -> dict[str, Any]:
    """Create a Due on the adoption base, then reconcile it to current refs.

    Both committed stages are returned so a caller can distinguish a partial
    effect from a failure before any owner mutation.
    """

    if not isinstance(request_key, str) or not request_key.strip():
        raise OccurrencePreparationError("request_key is required")
    expected_mode = _MODES.get((operation, lifecycle))
    if (operation, lifecycle) == ("invoke", "launch") and getattr(due, "role", None) == "manager":
        # This entrance is only the exact separately authorized delivery after
        # the retained guard-before-initializer disposition, never generic retry.
        proof = (getattr(due, "target", None) or {}).get("preinitialization_recovery") or {}
        old_value = due_port.read_due(proof.get("original_schedule_id", ""))
        marker = ((old_value or {}).get("host_evidence") or {}).get("role_preinitialization_custody_release") or {}
        report = None if portfolio is None or not proof.get("disposition_ref") else portfolio.operations._owner_reader.get_record(ResourceRef.from_dict(proof['disposition_ref']))
        report_value = {} if report is None else report.payload.get('value', {})
        scope = report_value.get("scope", {})
        from .worker_custody import PREINITIALIZATION_SCHEMA
        import hashlib, json
        old_result = (((old_value or {}).get("host_evidence") or {}).get("gateway_attempt") or {}).get("result")
        old_result_sha = hashlib.sha256(json.dumps(old_result, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        if (not old_value or report is None or marker.get("schema") != PREINITIALIZATION_SCHEMA
                or old_value.get("stop_state") != "stopped" or old_value.get("in_flight_request") is not None
                or old_value.get("lifecycle_owner") != due.lifecycle_owner
                or report.payload.get('record_type') != 'work.observation'
                or report.payload.get('observation_kind') != 'report'
                or report.payload.get('assignment') != old_value.get('assignment_ref')
                or report.payload.get('generation') != due.generation
                or report_value.get("schema") != PREINITIALIZATION_SCHEMA
                or report_value.get("fresh_occurrence_limit") != 1
                or report_value.get("provider_retry_allowed") is not False
                or old_result_sha != proof.get("original_result_sha256")
                or marker.get("disposition_ref") != proof.get("disposition_ref")
                or report_value.get("fresh_request_key") != proof.get("fresh_request_key")
                or proof.get("fresh_request_key") != request_key
                or scope.get("result_sha256") != proof.get("original_result_sha256")
                or scope.get("project_ref") != due.target.get("project_ref")
                or scope.get("task_ref") != due.target.get("task_ref")
                or scope.get("generation") != due.generation
                or any(scope.get("assignment_ref", {}).get(k) != assignment_ref.get(k)
                       for k in ("authority", "kind", "id"))):
            raise OccurrencePreparationError("manager launch lacks exact finite preinitialization disposition")
        expected_mode = "fresh_manager"
    if (operation, lifecycle) == ("invoke", "launch") and getattr(due, "role", None) in {
        "orchestrator", "project_advisor"
    }:
        expected_mode = "fresh_bounded_role"
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
    current_payload = getattr(current, "payload", {})
    current_manager = getattr(current, "manager", None)
    if current_manager is None and isinstance(current_payload, Mapping):
        current_manager = current_payload.get("manager")
    current_principal = getattr(current, "principal", None)
    if current_principal is None and isinstance(current_payload, Mapping):
        current_principal = current_payload.get("principal")
    if assignment_owner not in {current_manager, current_principal}:
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
    "compact_operation_status", "compact_project_status", "derive_manager_continuation_request", "manager_continuation_schedule_id",
    "complete_task_from_command",
    "prepare_current_assignment_occurrence", "read_project_progress_reports",
    "validate_owner_timeout_seconds",
]
