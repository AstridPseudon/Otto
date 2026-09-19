"""Read-only manager inbox and event reconciliation.

The inbox is a projection over the public Herzchen ProjectSheet and reader
ports.  It owns no records, queue, cursor store, acknowledgement or launch
path.  A cursor is an integrity checked client token; rebuilding the view after
restart therefore remains safe and repeatable.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Optional, Sequence


class InboxCursorError(ValueError):
    """The caller supplied a cursor outside this view's scope."""


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _safe(to_dict())
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return json.loads(to_json())
    if hasattr(value, "value"):
        return _safe(value.value)
    return str(value)


def _ref(value: Any) -> Optional[dict[str, Any]]:
    value = _safe(value)
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(value.get(key), str) and value.get(key).strip() for key in ("authority", "kind", "id")):
        return None
    if "revision" in value and value.get("revision") is not None and (not isinstance(value.get("revision"), str) or not value.get("revision", "").strip()):
        return None
    return {key: value[key] for key in ("authority", "kind", "id", "revision") if key in value}


def _identity(value: Any) -> Optional[tuple[str, str, str]]:
    ref = _ref(value)
    return None if ref is None else (ref["authority"], ref["kind"], ref["id"])


def _same_identity(left: Any, right: Any) -> bool:
    return _identity(left) == _identity(right) and _identity(left) is not None


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _scope_key(project: Mapping[str, Any]) -> str:
    ref = _ref(project.get("ref") or project.get("project_ref"))
    if ref is None:
        raise ValueError("project view has no durable reference")
    return ":".join((ref["authority"], ref["kind"], ref["id"]))


def _cursor_encode(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value["integrity"] = _digest(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(value: str, scope: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise InboxCursorError("cursor must be a non-empty token")
    try:
        raw = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor is not an object")
        integrity = payload.pop("integrity")
        if integrity != _digest(payload):
            raise ValueError("cursor integrity mismatch")
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise InboxCursorError("cursor is malformed") from exc
    if payload.get("format") != "otto.manager-inbox.cursor.v1" or payload.get("scope") != scope:
        raise InboxCursorError("cursor scope does not match this project")
    streams = payload.get("streams", {})
    if not isinstance(streams, Mapping):
        raise InboxCursorError("cursor streams are malformed")
    return payload


def _ref_values(value: Any) -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    if isinstance(value, Mapping):
        item = _identity(value)
        if item is not None:
            found.add(item)
        for child in value.values():
            found.update(_ref_values(child))
    elif isinstance(value, (tuple, list)):
        for child in value:
            found.update(_ref_values(child))
    return found


def _observation_items(view: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    project = view.get("project", {})
    if isinstance(project, Mapping):
        observed = project.get("observed", {})
        if isinstance(observed, Mapping):
            result.append({"owner": project, "observed": observed})
    for task in view.get("tasks", ()):
        if not isinstance(task, Mapping):
            continue
        observed = task.get("observed", {})
        if isinstance(observed, Mapping):
            result.append({"owner": task, "observed": observed})
    return result


def _attempt_payload(value: Any) -> Optional[dict[str, Any]]:
    """Find a captured attempt without promoting arbitrary nested reports.

    A manager verification often contains ``outcome`` and other words that
    look like an attempt.  Only the explicitly supported ``attempt`` and
    ``envelope`` containers, or a top-level capture value, are eligible.
    """
    value = _safe(value)
    if isinstance(value, Mapping):
        for key in ("attempt", "envelope"):
            candidate = value.get(key)
            if isinstance(candidate, Mapping) and _looks_like_attempt(candidate):
                return dict(candidate)
        if _looks_like_attempt(value):
            return dict(value)
    return None


_ATTEMPT_FIELDS = frozenset({
    "outcome", "status", "logical_request_key", "native_session_id",
    "physical_session_id", "native_handle_missing", "handle_state",
    "operation", "request_key", "worker_native_id",
})
_DISPOSITIONS = frozenset({
    "held", "unknown", "accepted", "accepted-for-task", "success",
    "succeeded", "failed", "failure", "rejected", "correction-needed",
})


def _looks_like_attempt(value: Mapping[str, Any]) -> bool:
    return bool(_ATTEMPT_FIELDS.intersection(value))


def _schema(value: Mapping[str, Any]) -> str:
    return str(value.get("schema", "")).strip().lower()


def _is_native_attachment(value: Mapping[str, Any]) -> bool:
    schema = _schema(value)
    outcome = str(value.get("outcome", "")).lower()
    return "native_attachment" in schema or value.get("native_attachment") is not None or outcome.startswith("native_worker_")


def _is_assessment(value: Mapping[str, Any]) -> bool:
    schema = _schema(value)
    kind = str(value.get("kind", "")).lower()
    return (
        "manager_verification" in schema
        or kind in {"manager-assessment", "manager_assessment", "assessment", "manager-completion", "manager_completion"}
        or isinstance(value.get("assessment"), Mapping)
    )


def _is_bookkeeping(value: Mapping[str, Any]) -> bool:
    schema = _schema(value)
    outcome = str(value.get("outcome", "")).lower()
    return (
        any(token in schema for token in ("hourly", "review", "reconciliation", "launch", "idle_handoff"))
        or outcome.startswith(("hourly_", "pilot_reconciled", "process_review_"))
    )


def _ref_string(value: Any, *, authority: Optional[str] = None, kind: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Normalize the compact ``id@revision`` refs used by report values."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        ident, sep, revision = text.rpartition("@")
        if not sep:
            ident, revision = text, None
        if not ident.strip() or (sep and not revision.strip()):
            return None
        candidate = {"authority": authority or "", "kind": kind or "", "id": ident.strip(), **({"revision": revision.strip()} if revision else {})}
        return _ref(candidate)
    return _ref(value)


def _exact_ref(left: Any, right: Any, *, require_revision: bool = True) -> bool:
    lref, rref = _ref(left), _ref(right)
    if lref is None or rref is None:
        return False
    if any(lref.get(key) != rref.get(key) for key in ("authority", "kind", "id")):
        return False
    if require_revision:
        return bool(lref.get("revision") and rref.get("revision") and lref.get("revision") == rref.get("revision"))
    return True


def _compatible_ref(left: Any, right: Any) -> bool:
    """Compare context refs while allowing intentionally unpinned legacy refs."""
    lref, rref = _ref(left), _ref(right)
    if lref is None or rref is None or _identity(lref) != _identity(rref):
        return False
    return not (lref.get("revision") and rref.get("revision") and lref.get("revision") != rref.get("revision"))


def _project_manager_scope_compatible(left: Any, right: Any) -> bool:
    """Match a persistent project manager by project identity.

    A manager assignment retains the project revision at which it was made.
    The owner completion path already treats the project authority/kind/id as
    the manager scope and checks the current project/task revisions separately
    before mutation.  Keep revision-sensitive matching for every other
    context, while allowing only a manager's project scope to follow that
    identity across revisions in this read projection.
    """
    lref, rref = _ref(left), _ref(right)
    if lref is None or rref is None:
        return False
    if lref.get("kind") == rref.get("kind") == "work.project":
        return _same_identity(lref, rref)
    return _compatible_ref(lref, rref)


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _evidence_validation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the shape of supplied evidence without dereferencing it."""
    supplied = False
    invalid: list[str] = []
    refs = value.get("evidence_refs")
    if "evidence_refs" in value:
        supplied = bool(refs)
        if refs not in (None, [], (), set()):
            if not isinstance(refs, (list, tuple, set)):
                invalid.append("evidence_refs_type")
            else:
                for index, item in enumerate(refs):
                    normalized = _ref(item)
                    if normalized is None or not isinstance(normalized.get("revision"), str) or not normalized.get("revision", "").strip():
                        invalid.append(f"evidence_refs[{index}]")
    hashes = value.get("evidence_hashes")
    if "evidence_hashes" in value:
        supplied = supplied or bool(hashes)
        if hashes not in (None, [], (), {}, set()):
            if isinstance(hashes, Mapping):
                for key, item in hashes.items():
                    if not isinstance(key, str) or not key.strip():
                        invalid.append("evidence_hashes_key")
                    if not isinstance(item, str) or not item.strip():
                        invalid.append(f"evidence_hashes[{key!r}]")
                    elif "sha256" in str(key).lower() and not _SHA256_RE.fullmatch(item.strip()):
                        invalid.append(f"evidence_hashes[{key!r}]_sha256")
            elif isinstance(hashes, (list, tuple, set)):
                for index, item in enumerate(hashes):
                    if not isinstance(item, str) or not item.strip():
                        invalid.append(f"evidence_hashes[{index}]")
            else:
                invalid.append("evidence_hashes_type")
    for key in ("result_evidence_sha256", "worker_result_evidence_sha256"):
        if key not in value:
            continue
        supplied = True
        item = value.get(key)
        if not isinstance(item, str) or not _SHA256_RE.fullmatch(item.strip()):
            invalid.append(key)
    return {"supplied": supplied, "valid": not invalid, "basis": bool(supplied and not invalid), "invalid": invalid}


def _evidence_basis(value: Mapping[str, Any]) -> bool:
    return bool(_evidence_validation(value)["basis"])


def _explicit_disposition(value: Mapping[str, Any]) -> Optional[str]:
    disposition = value.get("disposition")
    if isinstance(disposition, str) and disposition.strip().lower() in _DISPOSITIONS:
        return disposition.strip().lower()
    return None


def _status(attempt: Mapping[str, Any], observation: Mapping[str, Any]) -> tuple[str, bool]:
    raw = str(attempt.get("outcome", attempt.get("status", ""))).strip().lower()
    reason = " ".join(str(attempt.get(key, "")) for key in ("unknown_reason", "reconciliation", "error", "delivery_state")).lower()
    if bool(attempt.get("timeout")) or raw in {"timeout", "timed_out"} or "timeout" in reason:
        return "timeout", True
    if raw in {"lost_response", "lost-response", "lost"} or "lost" in reason:
        return "lost_response", True
    if raw in {"unknown", "undetermined", "unresolved", "crashed"} or (not raw and observation.get("observation_kind") in {"result", "report"}):
        return "unknown", True
    if raw in {"failed", "failure", "error", "rejected", "cancelled", "canceled"}:
        return "failure", True
    if raw in {"succeeded", "success", "completed", "complete", "returned"}:
        return "success", True
    if raw in {"running", "started", "dispatched", "queued", "in_flight"}:
        return "running", False
    return ("observed", False) if observation.get("observation_kind") == "dispatch" else ("unknown", True)


def _assessed(observation: Mapping[str, Any], attempt: Mapping[str, Any]) -> bool:
    """Return the legacy local assessment bit for an already joined record.

    ``assessed=true`` and pending completion objects are producer hints, not
    an owner assessment.  The reader sets this only after exact result,
    assignment and generation joins in ``derive_manager_inbox``.
    """
    value = observation.get("value", {})
    if not isinstance(value, Mapping):
        return False
    disposition = _explicit_disposition(value)
    return disposition is not None and _evidence_basis(value) and _exact_ref(value.get("result_ref"), attempt.get("result_ref"))


def _event_reconciliation(scope: str, events: Sequence[Mapping[str, Any]], cursor: Optional[str], limit: int) -> dict[str, Any]:
    streams: dict[str, list[dict[str, Any]]] = {}
    for raw in events:
        event = _safe(raw)
        if not isinstance(event, Mapping):
            continue
        stream = event.get("stream")
        sequence = event.get("sequence")
        if not isinstance(stream, str) or not isinstance(sequence, int):
            continue
        streams.setdefault(stream, []).append(dict(event))
    for values in streams.values():
        values.sort(key=lambda item: (int(item.get("sequence", 0)), str(item.get("event_id", ""))))
    prior: dict[str, Any] = {}
    status = "initial"
    if cursor is not None:
        prior = _cursor_decode(cursor, scope)
        status = "advanced"
    saved = prior.get("streams", {}) if isinstance(prior, Mapping) else {}
    gap = False
    changed: list[dict[str, Any]] = []
    current: dict[str, dict[str, Any]] = {}
    for stream, values in streams.items():
        max_sequence = int(values[-1]["sequence"]) if values else 0
        by_sequence = {int(item["sequence"]): item for item in values}
        previous = saved.get(stream, {}) if isinstance(saved, Mapping) else {}
        after = int(previous.get("sequence", 0)) if isinstance(previous, Mapping) else 0
        event_id = previous.get("event_id") if isinstance(previous, Mapping) else None
        if after and (after > max_sequence or by_sequence.get(after, {}).get("event_id") != event_id):
            gap = True
            after = 0
        changed.extend(item for item in values if int(item["sequence"]) > after)
        current[stream] = {"sequence": max_sequence, "event_id": by_sequence[max_sequence]["event_id"]} if max_sequence else {"sequence": 0, "event_id": None}
    if isinstance(saved, Mapping):
        for stream, previous in saved.items():
            if stream not in streams and isinstance(previous, Mapping) and int(previous.get("sequence", 0)) > 0:
                gap = True
    changed.sort(key=lambda item: (str(item.get("stream", "")), int(item.get("sequence", 0)), str(item.get("event_id", ""))))
    bounded = max(1, min(int(limit), 1000))
    page = changed[:bounded]
    if gap:
        status = "gap"
    advanced = dict(saved) if not gap else {}
    for event in page:
        stream = str(event["stream"])
        advanced[stream] = {"sequence": int(event["sequence"]), "event_id": event.get("event_id")}
    next_cursor = _cursor_encode({"format": "otto.manager-inbox.cursor.v1", "scope": scope, "streams": advanced})
    return {"status": status, "events": page, "event_ids": [item.get("event_id") for item in page if item.get("event_id")], "cursor": next_cursor, "has_more": len(changed) > len(page), "gap": gap, "watermarks": current}


def derive_manager_inbox(
    view: Mapping[str, Any],
    *,
    events: Sequence[Mapping[str, Any]] = (),
    cursor: Optional[str] = None,
    dependency_records: Optional[Mapping[tuple[str, str, str], Mapping[str, Any]]] = None,
    limit: int = 100,
    safety_scan: bool = True,
) -> dict[str, Any]:
    """Derive a manager snapshot from one public ProjectSheet view."""
    source = _safe(view)
    if not isinstance(source, Mapping):
        raise ValueError("project sheet reader returned a non-object")
    project = source.get("project")
    if not isinstance(project, Mapping):
        raise ValueError("project sheet reader returned no project")
    scope = _scope_key(project)
    project_ref = _ref(project.get("ref"))
    task_views = [item for item in source.get("tasks", ()) if isinstance(item, Mapping)]
    refs = _ref_values(source)
    relevant_events = []
    for event in events:
        event_refs = _ref_values(event)
        if not event_refs or refs.intersection(event_refs):
            relevant_events.append(_safe(event))
    reconciliation = _event_reconciliation(scope, relevant_events, cursor, limit)
    attempts: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    unknown: dict[str, Any] = {"project": [], "tasks": []}
    attachments: list[dict[str, Any]] = []
    bookkeeping: list[dict[str, Any]] = []
    verifications: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    unknown_reports: list[dict[str, Any]] = []
    pending_assessments: list[dict[str, Any]] = []

    def normalize_ref(value: Any, expected_kind: Optional[str] = None) -> Optional[dict[str, Any]]:
        if isinstance(value, str):
            return _ref_string(value, authority=(project_ref or {}).get("authority"), kind=expected_kind)
        return _ref(value)

    def observation_kind(record_kind: Any, payload: Mapping[str, Any]) -> str:
        value = str(payload.get("observation_kind", "")).strip().lower()
        if value:
            return value
        return {"dispatches": "dispatch", "results": "result", "reports": "report"}.get(str(record_kind), str(record_kind))

    for item in _observation_items(source):
        owner, observed = item["owner"], item["observed"]
        owner_ref = _ref(owner.get("ref"))
        for assignment in observed.get("assignments", ()) if isinstance(observed.get("assignments", ()), (list, tuple)) else ():
            if isinstance(assignment, Mapping):
                payload = assignment.get("payload", assignment)
                if isinstance(payload, Mapping):
                    bindings.append({"source_ref": _ref(assignment.get("ref")), "scope_ref": payload.get("scope"), "role": payload.get("role"), "principal": payload.get("principal"), "generation": payload.get("generation"), "status": payload.get("status"), "history": payload.get("history", [])})
        for kind in ("dispatches", "results", "reports"):
            values = observed.get(kind, ())
            if not isinstance(values, (list, tuple)):
                continue
            for record in values:
                if not isinstance(record, Mapping):
                    unknown["project" if owner_ref and owner_ref.get("kind") == "work.project" else "tasks"].append(_safe(record))
                    continue
                envelope = record.get("payload", record)
                payload = envelope
                if isinstance(payload, Mapping) and isinstance(payload.get("value"), Mapping) and not _looks_like_attempt(payload):
                    # Public ObservationRecord serializations use ``value``;
                    # older assignment reads expose the value directly.
                    payload = payload["value"]
                if not isinstance(payload, Mapping):
                    continue
                source_ref = _ref(record.get("ref"))
                assignment_ref = normalize_ref(record.get("assignment") or (envelope.get("assignment") if isinstance(envelope, Mapping) else None) or payload.get("assignment") or payload.get("assignment_ref"), "wrk.assignment")
                generation = record.get("generation", (envelope.get("generation") if isinstance(envelope, Mapping) else None) or payload.get("generation", payload.get("assignment_generation")))
                # Public task exports may omit the redundant project/task
                # fields from an observation.  The owner of that observation
                # is still durable context and is safe to use as a fallback.
                owner_task_ref = None
                if owner_ref and owner_ref.get("kind") == "work.task":
                    # The task row may already have advanced after a
                    # completion report.  Its authored reference preserves
                    # the pre-close revision carried by that report.
                    authored = owner.get("authored") if isinstance(owner.get("authored"), Mapping) else {}
                    authored_ref = _ref(authored.get("ref")) if isinstance(authored, Mapping) else None
                    owner_task_ref = authored_ref or owner_ref
                owner_project_ref = project_ref
                category = "attachment" if _is_native_attachment(payload) else "assessment" if _is_assessment(payload) else "bookkeeping" if _is_bookkeeping(payload) else "execution"
                obs_kind = observation_kind(kind, payload)
                if category == "attachment":
                    attachment = {
                        "source_ref": source_ref,
                        "assignment_ref": assignment_ref,
                        "generation": generation,
                        "scope_ref": normalize_ref(payload.get("project_ref") or payload.get("scope_ref"), "work.project") or owner_project_ref,
                        "task_ref": normalize_ref(payload.get("task_ref"), "work.task") or owner_task_ref,
                        "native_id": payload.get("worker_native_id") or payload.get("native_id") or payload.get("native_session_id"),
                        "native_session": payload.get("worker_native_session") or payload.get("native_session_id"),
                        "status": str(payload.get("outcome", payload.get("status", "observed"))).strip().lower() or "observed",
                        "value": _safe(payload),
                    }
                    attachments.append(attachment)
                    continue
                if category == "assessment":
                    pending_assessments.append({
                        "source_ref": source_ref,
                        "assignment_ref": assignment_ref,
                        "outer_assignment_ref": assignment_ref,
                        "generation": generation,
                        "outer_generation": generation,
                        "value": _safe(payload),
                        "scope_ref": normalize_ref(payload.get("project_ref") or payload.get("scope_ref"), "work.project") or owner_project_ref,
                        "task_ref": normalize_ref(payload.get("task_ref"), "work.task") or owner_task_ref,
                    })
                    continue
                if category == "bookkeeping":
                    state = "pending" if any(str(payload.get(key, "")).lower() in {"pending", "unknown", "queued"} for key in ("status", "review_report", "findings", "completion")) else "observed"
                    bookkeeping.append({
                        "source_ref": source_ref,
                        "assignment_ref": assignment_ref,
                        "generation": generation,
                        "status": state,
                        "schema": payload.get("schema"),
                        "outcome": payload.get("outcome"),
                        "correction_of_report_ref": normalize_ref(payload.get("correction_of_report_ref"), "wrk.report"),
                        "value": _safe(payload),
                    })
                    continue

                attempt = _attempt_payload(payload)
                if attempt is None and (kind == "results" or _schema(payload).endswith("worker.result.v1")):
                    # A typed worker result is an execution attempt even when
                    # its producer omitted the generic ``attempt`` envelope.
                    attempt = dict(payload)
                if attempt is None:
                    if kind == "dispatches":
                        attempt = {"outcome": "dispatched"}
                    elif kind == "reports":
                        unknown_report = {"source_ref": source_ref, "assignment_ref": assignment_ref, "generation": generation, "status": "unknown", "schema": payload.get("schema"), "outcome": payload.get("outcome"), "value": _safe(payload)}
                        unknown_reports.append(unknown_report)
                        # Preserve the raw ambiguous report in the read
                        # projection; attention alone would lose its audit
                        # value on a subsequent replay.
                        bookkeeping.append(unknown_report)
                        continue
                    else:
                        attempt = {"outcome": "unknown", "unrecognized": True}
                attempt = dict(attempt)
                result_ref = source_ref if kind == "results" or _schema(payload).endswith("worker.result.v1") else normalize_ref(attempt.get("result_ref"), "wrk.result")
                attempt_assignment = assignment_ref or normalize_ref(attempt.get("assignment_ref") or attempt.get("assignment"), "wrk.assignment")
                status, terminal = _status(attempt, {"observation_kind": obs_kind, "value": payload.get("value", {})})
                observation = {
                    "source_ref": source_ref,
                    "result_ref": result_ref,
                    "assignment_ref": attempt_assignment,
                    "generation": generation,
                    "assignment_generation": payload.get("assignment_generation", generation),
                    "scope_ref": normalize_ref(payload.get("project_ref") or payload.get("scope_ref"), "work.project") or owner_project_ref,
                    "task_ref": normalize_ref(payload.get("task_ref"), "work.task") or owner_task_ref,
                    "task_ref_derived": bool(payload.get("task_ref") is None and owner_task_ref is not None),
                    "observation_kind": obs_kind,
                    "status": status,
                    "terminal": terminal,
                    "assessed": False,
                    "assessment_recorded": False,
                    "attempt": _safe(attempt),
                    "native_id": attempt.get("worker_native_id") or attempt.get("native_id") or attempt.get("native_session_id") or attempt.get("physical_session_id"),
                    "native_handle_state": "vanished" if attempt.get("native_handle_missing") or attempt.get("handle_state") == "vanished" else "present" if attempt.get("native_session_id", attempt.get("physical_session_id")) else "unobserved",
                    "result_retained": bool(source_ref or payload.get("value") or result_ref),
                }
                attempts.append(observation)

    # Join native identity observations to the exact attempt scope.  Native
    # IDs alone are intentionally insufficient because they can recur across
    # projects or generations.
    for attachment in attachments:
        def optional_context_matches(left: Any, right: Any) -> bool:
            # Context is optional on legacy result records.  When both sides
            # provide it, identities must agree and pinned revisions may not
            # contradict each other.
            if left is None or right is None:
                return True
            return _compatible_ref(left, right)

        matches = [item for item in attempts if (
            _exact_ref(item.get("assignment_ref"), attachment.get("assignment_ref"))
            and item.get("generation") == attachment.get("generation")
            and optional_context_matches(item.get("scope_ref"), attachment.get("scope_ref"))
            and optional_context_matches(item.get("task_ref"), attachment.get("task_ref"))
        )]
        attachment["joined"] = bool(matches)
        for item in matches:
            native_id = attachment.get("native_id")
            if native_id:
                item["native_id"] = native_id
                item["native_id_source_ref"] = attachment.get("source_ref")
                item["native_identity_observed"] = True
                # Attachment proves identity, not current handle liveness.
                if item.get("native_handle_state") == "unobserved":
                    item["native_handle_state"] = "observed"

    # Normalize and validate manager verification/correction chains.  A
    # pending hourly/review record never enters this path, even if it carries
    # a result_ref and a completion object.
    assessment_nodes: list[dict[str, Any]] = []
    for raw in pending_assessments:
        value = raw["value"] if isinstance(raw.get("value"), Mapping) else {}
        completion = value.get("completion") if value.get("kind") in {"manager-completion", "manager_completion"} and isinstance(value.get("completion"), Mapping) else None
        target_value = completion if completion is not None else value
        # attempt_ref is an owner bookkeeping handle, not a worker result join key.
        result_ref = normalize_ref(target_value.get("result_ref") or target_value.get("worker_result_ref"), "wrk.result")
        worker_assignment_ref = normalize_ref(target_value.get("worker_assignment_ref"), "wrk.assignment")
        if completion is None and worker_assignment_ref is None:
            worker_assignment_ref = normalize_ref(target_value.get("assignment_ref"), "wrk.assignment") or raw.get("assignment_ref")
        worker_generation = target_value.get("worker_generation", target_value.get("result_generation"))
        if completion is None and worker_generation is None:
            worker_generation = target_value.get("assignment_generation", target_value.get("generation", raw.get("generation")))
        manager_assignment_ref = normalize_ref(target_value.get("manager_assignment_ref"), "wrk.assignment")
        if completion is not None:
            manager_assignment_ref = manager_assignment_ref or normalize_ref(target_value.get("assignment_ref"), "wrk.assignment") or raw.get("assignment_ref")
        manager_generation = target_value.get("manager_generation", target_value.get("generation", raw.get("generation")))
        target = next((item for item in attempts if (
            _exact_ref(item.get("result_ref") or item.get("source_ref"), result_ref)
            and (worker_assignment_ref is None or _exact_ref(item.get("assignment_ref"), worker_assignment_ref))
            and (worker_generation is None or item.get("generation") == worker_generation)
        )), None)
        disposition = _explicit_disposition(value) or _explicit_disposition(target_value)
        evidence_state = _evidence_validation(target_value)
        evidence = bool(evidence_state["basis"])
        target_match = target is not None
        scope_ref = normalize_ref(target_value.get("project_ref") or target_value.get("scope_ref"), "work.project") or raw.get("scope_ref")
        task_ref = normalize_ref(target_value.get("task_ref"), "work.task") or raw.get("task_ref")
        scope_match = scope_ref is None or _compatible_ref(scope_ref, project_ref)
        task_match = True
        if task_ref is not None:
            task_match = bool(
                target is not None
                and target.get("task_ref") is not None
                and (
                    _same_identity(target.get("task_ref"), task_ref)
                    if target.get("task_ref_derived")
                    else _compatible_ref(target.get("task_ref"), task_ref)
                )
            )
        outer_result_ref = normalize_ref(value.get("result_ref"), "wrk.result") if completion is not None else None
        outer_scope_ref = normalize_ref(value.get("project_ref") or value.get("scope_ref"), "work.project") if completion is not None else None
        outer_task_ref = normalize_ref(value.get("task_ref"), "work.task") if completion is not None else None
        manager_scope_conflict = bool(completion is not None and raw.get("assignment_ref") is not None and manager_assignment_ref is not None and not _exact_ref(raw.get("assignment_ref"), manager_assignment_ref))
        manager_generation_conflict = bool(completion is not None and raw.get("generation") is not None and manager_generation is not None and raw.get("generation") != manager_generation)
        target_claim_conflict = bool(completion is not None and outer_result_ref is not None and not _exact_ref(outer_result_ref, result_ref))
        target_claim_conflict = target_claim_conflict or bool(completion is not None and outer_scope_ref is not None and scope_ref is not None and not _compatible_ref(outer_scope_ref, scope_ref))
        target_claim_conflict = target_claim_conflict or bool(completion is not None and outer_task_ref is not None and task_ref is not None and not _compatible_ref(outer_task_ref, task_ref))
        correction_ref = normalize_ref(value.get("correction_of_report_ref"), "wrk.report")
        if correction_ref is None:
            correction_ref = normalize_ref(target_value.get("correction_of_report_ref"), "wrk.report")
        diagnostic_reasons: list[str] = []
        if result_ref is None:
            diagnostic_reasons.append("missing_or_malformed_result_ref")
        if not target_match:
            diagnostic_reasons.append("result_unmatched")
        if not scope_match:
            diagnostic_reasons.append("project_scope_mismatch")
        if not task_match:
            diagnostic_reasons.append("task_scope_mismatch")
        if not evidence_state["valid"]:
            diagnostic_reasons.append("invalid_evidence")
        if manager_scope_conflict:
            diagnostic_reasons.append("manager_scope_mismatch")
        if manager_generation_conflict:
            diagnostic_reasons.append("manager_generation_mismatch")
        if target_claim_conflict:
            diagnostic_reasons.append("nested_target_mismatch")
        node = {
            "source_ref": raw.get("source_ref"),
            "result_ref": result_ref,
            "assignment_ref": worker_assignment_ref,
            "generation": worker_generation,
            "manager_assignment_ref": manager_assignment_ref,
            "manager_generation": manager_generation,
            "manager": target_value.get("manager") if completion is not None else value.get("manager"),
            "completion": completion is not None,
            "disposition": disposition,
            "evidence_basis": evidence,
            "evidence_valid": bool(evidence_state["valid"]),
            "evidence_refs": _safe(target_value.get("evidence_refs")),
            "evidence_verification": "mismatch" if not evidence_state["valid"] else "unknown",
            "evidence_invalid": list(evidence_state["invalid"]),
            "target_match": target_match,
            "scope_match": scope_match,
            "task_match": task_match,
            "manager_scope_conflict": manager_scope_conflict,
            "manager_generation_conflict": manager_generation_conflict,
            "target_claim_conflict": target_claim_conflict,
            "valid": bool(target_match and scope_match and task_match and disposition and evidence and not manager_scope_conflict and not manager_generation_conflict and not target_claim_conflict),
            "correction_of_report_ref": correction_ref,
            "diagnostic_reasons": diagnostic_reasons,
            "value": value,
            "target": target,
        }
        if node["assignment_ref"] is None and target is not None:
            node["assignment_ref"] = target.get("assignment_ref")
        if node["generation"] is None and target is not None:
            node["generation"] = target.get("generation")
        # Keep the owner-produced manager binding separate from worker result
        # linkage.  A syntactically plausible manager claim is not authority;
        # authority is available only when the public assignment agrees on
        # identity, role, principal, scope and generation.
        node["manager_authority"] = "unknown"
        node["manager_binding_diagnostics"] = []
        if manager_assignment_ref is not None:
            assignment_candidates = [
                binding for binding in bindings
                if _exact_ref(binding.get("source_ref"), manager_assignment_ref)
            ]
            if not assignment_candidates:
                if bindings:
                    node["manager_authority"] = "mismatch"
                    node["manager_binding_diagnostics"].append("manager_assignment_not_bound")
            else:
                binding = assignment_candidates[0]
                if binding.get("role") != "manager":
                    node["manager_binding_diagnostics"].append("manager_role_mismatch")
                if manager_generation is not None and binding.get("generation") != manager_generation:
                    node["manager_binding_diagnostics"].append("manager_generation_mismatch")
                binding_scope = normalize_ref(binding.get("scope_ref"), "work.task")
                # A manager may be assigned to the evidenced task or to its
                # containing project.  Keep both verified claims available;
                # preferring task_ref would reject the valid project-scoped
                # assignment whenever a completion names both references.
                expected_scopes = [candidate for candidate in (task_ref, scope_ref) if candidate is not None]
                if binding_scope is not None and expected_scopes and not any(
                    _project_manager_scope_compatible(binding_scope, candidate)
                    if binding.get("role") == "manager" else _compatible_ref(binding_scope, candidate)
                    for candidate in expected_scopes
                ):
                    node["manager_binding_diagnostics"].append("manager_scope_mismatch")
                claimed_manager = node.get("manager")
                if claimed_manager is not None and binding.get("principal") is not None and claimed_manager != binding.get("principal"):
                    node["manager_binding_diagnostics"].append("manager_principal_mismatch")
                if node["manager_binding_diagnostics"]:
                    node["manager_authority"] = "mismatch"
                else:
                    node["manager_authority"] = "verified"
        if node["manager_authority"] == "mismatch":
            node["diagnostic_reasons"].extend(item for item in node["manager_binding_diagnostics"] if item not in node["diagnostic_reasons"])
            node["valid"] = False
        assessment_nodes.append(node)

    assessment_nodes.sort(key=lambda node: json.dumps(node.get("source_ref"), sort_keys=True))
    nodes_by_ref = {json.dumps(node.get("source_ref"), sort_keys=True): node for node in assessment_nodes if node.get("source_ref") is not None}
    successors: dict[str, list[dict[str, Any]]] = {}
    for node in assessment_nodes:
        parent_key = json.dumps(node.get("correction_of_report_ref"), sort_keys=True)
        if node.get("correction_of_report_ref") is not None:
            successors.setdefault(parent_key, []).append(node)
    for node in assessment_nodes:
        target = node.get("target")
        if target is None:
            continue
        target_key = json.dumps(target.get("result_ref") or target.get("source_ref"), sort_keys=True)
        siblings = [candidate for candidate in assessment_nodes if json.dumps(candidate.get("target", {}).get("result_ref") if candidate.get("target") else None, sort_keys=True) == target_key]
        conflict = False
        for parent_key, children in successors.items():
            if len(children) > 1 and any(child in siblings for child in children):
                conflict = True
        # A correction must name an observed predecessor in the same target
        # chain.  Cycles and missing predecessors are diagnostics, not guesses.
        if node.get("correction_of_report_ref") is not None:
            parent = nodes_by_ref.get(json.dumps(node.get("correction_of_report_ref"), sort_keys=True))
            if parent is None or parent not in siblings:
                conflict = True
            seen: set[str] = set()
            cursor_node = node
            while cursor_node.get("correction_of_report_ref") is not None:
                key = json.dumps(cursor_node.get("source_ref"), sort_keys=True)
                if key in seen:
                    conflict = True
                    break
                seen.add(key)
                parent = nodes_by_ref.get(json.dumps(cursor_node.get("correction_of_report_ref"), sort_keys=True))
                if parent is None:
                    break
                cursor_node = parent
        if not node.get("valid"):
            conflict = conflict or bool(node.get("diagnostic_reasons"))
        node["chain_conflict"] = conflict

    for target in attempts:
        related = [node for node in assessment_nodes if node.get("target") is target]
        if not related:
            continue
        # Invalid successors remain in history/diagnostics but do not displace
        # the last valid predecessor.  Multiple valid terminals remain a
        # conflict rather than being selected by input order.
        valid_related = [node for node in related if node.get("valid") and not node.get("chain_conflict")]
        terminal = [node for node in valid_related if not any(other.get("valid") and other.get("correction_of_report_ref") is not None and _exact_ref(other.get("correction_of_report_ref"), node.get("source_ref")) for other in valid_related)]
        current = terminal[0] if len(terminal) == 1 else None
        def chain_depth(item: Mapping[str, Any]) -> tuple[int, str]:
            depth = 0
            parent_ref = item.get("correction_of_report_ref")
            seen: set[str] = set()
            while parent_ref is not None and depth < len(related):
                key = json.dumps(parent_ref, sort_keys=True)
                if key in seen:
                    break
                seen.add(key)
                parent = next((candidate for candidate in related if _exact_ref(candidate.get("source_ref"), parent_ref)), None)
                if parent is None:
                    break
                depth += 1
                parent_ref = parent.get("correction_of_report_ref")
            return depth, json.dumps(item.get("source_ref"), sort_keys=True)

        history = [
            {
                "source_ref": node.get("source_ref"),
                "correction_of_report_ref": node.get("correction_of_report_ref"),
                "result_ref": node.get("result_ref"),
                "disposition": node.get("disposition"),
                "evidence_basis": node.get("evidence_basis"),
                "evidence_hashes": _safe(node.get("value", {}).get("evidence_hashes")) if isinstance(node.get("value"), Mapping) else None,
                "result_evidence_sha256": (node.get("value", {}).get("result_evidence_sha256") or node.get("value", {}).get("worker_result_evidence_sha256")) if isinstance(node.get("value"), Mapping) else None,
                "evidence_refs": node.get("evidence_refs"),
                "evidence_valid": node.get("evidence_valid"),
                "evidence_verification": node.get("evidence_verification"),
                "valid": node.get("valid"),
                "diagnostic_reasons": list(node.get("diagnostic_reasons", ())),
                "manager_assignment_ref": node.get("manager_assignment_ref"),
                "manager_generation": node.get("manager_generation"),
                "manager": node.get("manager"),
                "worker_assignment_ref": node.get("assignment_ref"),
                "worker_generation": node.get("generation"),
                "project_ref": node.get("scope_ref"),
                "task_ref": node.get("task_ref"),
                "manager_authority": node.get("manager_authority", "unknown"),
                "manager_binding_diagnostics": list(node.get("manager_binding_diagnostics", ())),
            }
            for node in sorted(related, key=chain_depth)
        ]
        has_invalid = any(not node.get("valid") for node in related)
        chain_conflict = bool(current is None or any(node.get("chain_conflict") for node in related) or has_invalid)
        manager_binding = bool(current is not None and current.get("manager_assignment_ref") is not None and any(
            item.get("role") == "manager"
            and _exact_ref(item.get("source_ref"), current.get("manager_assignment_ref"))
            and (current.get("manager_generation") is None or item.get("generation") == current.get("manager_generation"))
            for item in bindings
        ))
        provenance_node = current or next(
            (item for item in reversed(related) if item.get("manager_authority") != "unknown"),
            None,
        )
        verification = {
            "assessment_recorded": True,
            "current_ref": current.get("source_ref") if current is not None else None,
            "disposition": current.get("disposition") if current is not None else None,
            "evidence_basis": current.get("evidence_basis") if current is not None else False,
            "valid": bool(current is not None and current.get("valid")),
            "chain_conflict": chain_conflict,
            "manager_assignment_ref": provenance_node.get("manager_assignment_ref") if provenance_node is not None else None,
            "manager_generation": provenance_node.get("manager_generation") if provenance_node is not None else None,
            "manager": provenance_node.get("manager") if provenance_node is not None else None,
            "manager_authority": provenance_node.get("manager_authority", "unknown") if provenance_node is not None else "unknown",
            "evidence_verification": current.get("evidence_verification", "unknown") if current is not None else "unknown",
            "history": history,
            "remaining_obligations": _safe((current.get("value", {}) if current else {}).get("remaining_obligations", ())) if current else (),
        }
        target["verification"] = verification
        verifications.append({"source_ref": verification.get("current_ref"), "result_ref": target.get("result_ref"), **verification})
        if verification["valid"]:
            target["assessed"] = True
            target["assessment_recorded"] = True
            target["assessment_ref"] = verification["current_ref"]
            target["assessment_disposition"] = verification["disposition"]
            if verification["chain_conflict"]:
                attention.append({"key": "attention-" + sha256((scope + ":verification-conflict:" + json.dumps(target.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28], "reason": "verification_conflict", "status": target.get("status"), "source_ref": target.get("source_ref"), "assignment_ref": target.get("assignment_ref"), "generation": target.get("generation"), "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
            if verification.get("disposition") in {"accepted", "accepted-for-task", "success", "succeeded"} and (
                verification.get("manager_authority") != "verified"
                or verification.get("evidence_verification") != "verified"
            ):
                attention.append({
                    "key": "attention-" + sha256((scope + ":accepted-provenance:" + json.dumps(target.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28],
                    "reason": "accepted_assessment_requires_provenance",
                    "status": target.get("status"),
                    "source_ref": target.get("source_ref"),
                    "assignment_ref": target.get("assignment_ref"),
                    "generation": target.get("generation"),
                    "retry_allowed": False,
                    "acknowledged": False,
                    "dispatch": False,
                    "launch": False,
                })
        else:
            attention.append({"key": "attention-" + sha256((scope + ":verification-conflict:" + json.dumps(target.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28], "reason": "verification_conflict" if verification["chain_conflict"] else "verification_target_mismatch", "status": target.get("status"), "source_ref": target.get("source_ref"), "assignment_ref": target.get("assignment_ref"), "generation": target.get("generation"), "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})

    # Keep malformed or wrong-generation assessments visible even when they
    # cannot be joined to an exact attempt.  A valid predecessor may remain
    # current, but the rejected correction is never silently discarded.
    for node in assessment_nodes:
        if node.get("target") is not None:
            continue
        candidate = next((item for item in attempts if _exact_ref(item.get("result_ref") or item.get("source_ref"), node.get("result_ref"))), None)
        reason = "verification_target_mismatch" if candidate is not None else (node.get("diagnostic_reasons") or ["verification_unmatched"])[0]
        diagnostics.append({"source_ref": node.get("source_ref"), "result_ref": node.get("result_ref"), "category": "verification", "reason": reason, "reasons": list(node.get("diagnostic_reasons", ())), "value": _safe(node.get("value")), "assignment_ref": node.get("assignment_ref"), "generation": node.get("generation")})
        attention.append({"key": "attention-" + sha256((scope + ":verification-mismatch:" + json.dumps(node.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28], "reason": reason, "status": candidate.get("status") if candidate else "unknown", "source_ref": node.get("source_ref"), "assignment_ref": node.get("assignment_ref"), "generation": node.get("generation"), "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})


    for attachment in attachments:
        if not attachment.get("joined"):
            attention.append({"key": "attention-" + sha256((scope + ":attachment:" + json.dumps(attachment.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28], "reason": "native_attachment_without_exact_result", "status": attachment.get("status"), "source_ref": attachment.get("source_ref"), "assignment_ref": attachment.get("assignment_ref"), "generation": attachment.get("generation"), "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
    for report in unknown_reports:
        attention.append({"key": "attention-" + sha256((scope + ":unknown-report:" + json.dumps(report.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28], "reason": "unknown_report_shape", "status": "unknown", "source_ref": report.get("source_ref"), "assignment_ref": report.get("assignment_ref"), "generation": report.get("generation"), "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
    for observation in attempts:
        if not observation.get("terminal"):
            continue
        if not observation.get("assessed"):
            status = observation.get("status")
            reason = "unknown_attempt_blocks_retry" if status in {"unknown", "timeout", "lost_response"} else "manager_assessment_required"
            attempt = observation.get("attempt", {})
            if attempt.get("evidence_missing") or attempt.get("evidence_required") or attempt.get("evidence_refs") == [] or attempt.get("evidence_hashes") == {}:
                reason = "missing_evidence"
            key = "attention-" + sha256((scope + ":" + json.dumps(observation.get("source_ref"), sort_keys=True) + ":" + reason).encode()).hexdigest()[:28]
            attention.append({"key": key, "reason": reason, "status": status, "source_ref": observation["source_ref"], "assignment_ref": observation["assignment_ref"], "generation": observation["generation"], "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
        elif observation.get("assessment_disposition") in {"held", "unknown"} or observation.get("verification", {}).get("remaining_obligations"):
            key = "attention-" + sha256((scope + ":held:" + json.dumps(observation.get("source_ref"), sort_keys=True)).encode()).hexdigest()[:28]
            attention.append({"key": key, "reason": "held_assessment_requires_recovery", "status": observation.get("status"), "source_ref": observation["source_ref"], "assignment_ref": observation["assignment_ref"], "generation": observation["generation"], "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
    for item in _observation_items(source):
        owner, observed = item["owner"], item["observed"]
        owner_ref = _ref(owner.get("ref"))
        if not owner_ref or owner_ref.get("kind") != "work.task":
            continue
        authored = owner.get("authored", {}) if isinstance(owner.get("authored"), Mapping) else {}
        readiness = observed.get("readiness", {}) if isinstance(observed.get("readiness"), Mapping) else {}
        dependency_states = []
        stale = False
        task_identity = _identity(owner_ref)
        task_events = [event for event in relevant_events if task_identity in _ref_values(event)]
        task_created_at = min((str(event.get("recorded_at", "")) for event in task_events), default="")
        for dep in authored.get("dependencies", ()) if isinstance(authored.get("dependencies", ()), (list, tuple)) else ():
            dep_ref = _ref(dep)
            if dep_ref is None:
                continue
            current = None if dependency_records is None else dependency_records.get(_identity(dep_ref))
            current_ref = _ref(current.get("ref")) if isinstance(current, Mapping) else None
            expected_revision = dep_ref.get("revision")
            # Sheet authored dependency refs may intentionally be unpinned.
            # Event history gives the prerequisite revision visible when this
            # task was created without a projection row.
            if expected_revision is None and task_created_at:
                prior = [event for event in relevant_events if _identity(event.get("subject")) == _identity(dep_ref) and str(event.get("recorded_at", "")) <= task_created_at and _ref(event.get("subject")) is not None]
                if prior:
                    prior.sort(key=lambda event: str(event.get("recorded_at", "")))
                    expected_revision = _ref(prior[-1].get("subject")).get("revision")
                else:
                    # Batch-created tasks do not emit a child event.  A later
                    # prerequisite revision still retains its prior pinned ref
                    # in before_refs, enough to detect recomputation.
                    later = [event for event in relevant_events if _identity(event.get("subject")) == _identity(dep_ref) and _ref(event.get("subject")) is not None]
                    later.sort(key=lambda event: str(event.get("recorded_at", "")))
                    if later:
                        old = next((item for item in later[0].get("before_refs", ()) if _identity(item) == _identity(dep_ref)), None)
                        expected_revision = _ref(old).get("revision") if old is not None else None
            # ProjectSheet dependency links are intentionally identity-only.
            # The accepted owner refresh command records the exact observed
            # prerequisite revision in task metadata so a manager can clear a
            # stale historical pin through a durable, replay-safe operation.
            # Do not trust arbitrary metadata: require the typed marker and
            # keep the marker stale when the prerequisite has advanced again.
            metadata = authored.get("metadata", {}) if isinstance(authored.get("metadata"), Mapping) else {}
            refresh_markers = metadata.get("otto_dependency_refresh", ())
            if isinstance(refresh_markers, Mapping):
                refresh_markers = (refresh_markers,)
            if isinstance(refresh_markers, (list, tuple)):
                for marker in refresh_markers:
                    if not isinstance(marker, Mapping) or marker.get("source") != "otto.owner.dependency-refresh.v1":
                        continue
                    marker_ref = _ref(marker.get("ref"))
                    marker_revision = marker.get("revision")
                    if marker_ref is not None and _identity(marker_ref) == _identity(dep_ref) and isinstance(marker_revision, str) and current_ref is not None:
                        expected_revision = marker_revision
                        break
            changed = bool(expected_revision and current_ref and expected_revision != current_ref.get("revision"))
            stale = stale or changed
            dependency_states.append({"ref": dep_ref, "expected_revision": expected_revision, "observed_ref": current_ref, "revision_changed": changed, "lifecycle": current.get("lifecycle") if isinstance(current, Mapping) else None})
        tasks.append({"ref": owner_ref, "lifecycle": observed.get("lifecycle", authored.get("lifecycle")), "readiness": readiness, "eligibility": "recompute-needed" if stale else readiness.get("status", "unknown"), "stale": stale, "dependencies": dependency_states, "dispatch": False, "launch": False})
    task_refs = [item.get("ref") for item in tasks]
    by_scope_manager = [
        item for item in bindings
        if item.get("role") == "manager"
        and (
            _project_manager_scope_compatible(item.get("scope_ref"), project_ref)
            or any(_compatible_ref(item.get("scope_ref"), task_ref) for task_ref in task_refs)
        )
    ]
    if len(by_scope_manager) > 1:
        attention.append({"key": "attention-" + sha256((scope + ":competing-manager").encode()).hexdigest()[:28], "reason": "competing_manager_assignments", "source_ref": project_ref, "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
    if reconciliation["gap"]:
        attention.append({"key": "attention-" + sha256((scope + ":cursor-gap").encode()).hexdigest()[:28], "reason": "cursor_gap_requires_safety_scan", "source_ref": project_ref, "retry_allowed": False, "acknowledged": False, "dispatch": False, "launch": False})
    # A view is a read: do not collapse duplicate obligations by mutating a
    # record.  Deduplication is local and deterministic for this response.
    unique_attention = {item["key"]: item for item in attention}
    project_observed = project.get("observed", {}) if isinstance(project.get("observed"), Mapping) else {}
    decisions = list(source.get("decision_context", ()))
    if isinstance(project_observed.get("decision_context"), (list, tuple)):
        decisions.extend(project_observed["decision_context"])
    return {"outcome": "read", "schema": "otto.manager-inbox.v1", "scope": {"ref": project_ref, "key": scope, "parent": project.get("authored", {}).get("parent") if isinstance(project.get("authored"), Mapping) else None, "children": [{"ref": item.get("ref"), "parent": (item.get("authored", {}).get("parent") if isinstance(item.get("authored"), Mapping) else None) or project_ref} for item in task_views]}, "manager": {"assignments": by_scope_manager, "count": len(by_scope_manager), "all_scopes": [item for item in bindings if item.get("role") == "manager"]}, "tasks": tasks, "assignments": bindings, "attempts": attempts, "observations": attempts, "results": [item for item in attempts if item.get("observation_kind") == "result"], "reports": [item for item in attempts if item.get("observation_kind") == "report"], "attachments": attachments, "bookkeeping": bookkeeping, "verifications": verifications, "diagnostics": diagnostics, "attention": list(unique_attention.values()), "decisions": decisions, "readiness": _safe(source.get("readiness", project_observed.get("readiness", {}))), "dispatch": False, "launch": False, "acknowledged": False, "read_side_effects": False, "reconciliation": reconciliation, "safety_scan": {"performed": bool(safety_scan), "bounded": True, "limit": max(1, min(int(limit), 1000)), "source_refs": sorted(refs)}, "unknown": unknown, "source_refs": {"project": project_ref, "tasks": [_ref(item.get("ref")) for item in task_views if _ref(item.get("ref")) is not None], "attachments": [item.get("source_ref") for item in attachments], "bookkeeping": [item.get("source_ref") for item in bookkeeping], "verifications": [item.get("source_ref") for item in verifications if item.get("source_ref") is not None], "diagnostics": [item.get("source_ref") for item in diagnostics if item.get("source_ref") is not None]}}


__all__ = ["InboxCursorError", "derive_manager_inbox"]
