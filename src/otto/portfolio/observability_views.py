"""Thin, read-only operator presets over the admitted Events reader.

The projection and authenticated reader remain the authority for scope,
snapshot, continuation, lag, and bounded detail.  This module only shapes
those rows for operators; it never opens a Store, backfills, executes
recovery, or invents usage/accounting facts.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


VIEW_PRESETS = (
    "overview",
    "timeline",
    "agents",
    "tasks-reviews",
    "blockers",
    "usage",
    "recovery",
)


class ObservabilityViewError(ValueError):
    """The supplied view or bounded operator request is invalid."""


def _json_value(value: Any) -> Any:
    """Convert tuples and light reader values without copying payload stores."""
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field(summary: Mapping[str, Any], *names: str) -> Any:
    for side in (summary, _mapping(summary.get("after")).get("fields", {}),
                 _mapping(summary.get("before")).get("fields", {})):
        if not isinstance(side, Mapping):
            continue
        for name in names:
            if name in side:
                return side[name]
    return None


def _actor(summary: Mapping[str, Any]) -> dict[str, Any]:
    value = _field(summary, "responsible_actor", "actor", "principal", "manager", "agent", "reporter")
    if value is None:
        value = _field(summary, "responsibility_ref")
    if value is None:
        return {"state": "unknown", "value": None, "reason": "no responsible actor was retained"}
    return {"state": "known", "value": _json_value(value), "reason": None}


def _state(summary: Mapping[str, Any], *names: str) -> dict[str, Any]:
    value = _field(summary, *names)
    if value is None:
        return {"state": "unknown", "value": None}
    return {"state": "known", "value": _json_value(value)}


def _semantic(row: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(row.get("summary"))
    detail = _mapping(row.get("detail"))
    combined = dict(summary)
    for key, value in detail.items():
        combined.setdefault(key, value)
    return {
        "responsible_actor": _actor(combined),
        "response": _state(combined, "response", "response_state", "delivery_state"),
        "application": _state(combined, "application", "application_state", "applied"),
        "native_result": _state(combined, "native_result", "native_result_ref", "result_ref", "native_terminal"),
        "task_acceptance": _state(combined, "task_acceptance", "manager_acceptance", "acceptance", "accepted"),
    }


def _row(row: Mapping[str, Any], view: str) -> dict[str, Any]:
    value = {key: _json_value(item) for key, item in row.items() if key != "detail"}
    value["semantic"] = _semantic(row)
    value["view"] = view
    return value


def _scope(result: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = _mapping(result.get("snapshot"))
    scope = _mapping(snapshot.get("scope"))
    projects = result.get("projects", scope.get("projects", ()))
    return {
        "authorized": True,
        "projects": _json_value(projects),
        "recorded_range": {
            "from": scope.get("from"),
            "to": scope.get("to"),
        },
        "active_during": _json_value(scope.get("active_during")),
        "filters": _json_value(scope.get("filters", {})),
    }


def _envelope(view: str, result: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    continuation = {
        "next_cursor": result.get("next_cursor"),
        "partial": bool(result.get("partial", False)),
        "has_more": result.get("next_cursor") is not None,
        "snapshot_digest": result.get("snapshot_digest"),
    }
    return {
        "outcome": "read",
        "schema": "otto.events.operator-view.v1",
        "view": view,
        "read_only": True,
        "dispatch": False,
        "launch": False,
        "scope": _scope(result),
        "coverage": _json_value(result.get("coverage", {})),
        "continuation": continuation,
        "snapshot": _json_value(result.get("snapshot")),
        "rows": [_row(row, view) for row in rows],
    }


def _usage_row(row: Mapping[str, Any]) -> dict[str, Any]:
    value = _row(row, "usage")
    summary = _mapping(row.get("summary"))
    usage = summary.get("usage")
    if isinstance(usage, Mapping):
        # Only retain explicitly qualified observations.  No totals, prices,
        # zero values, or accounting fields are derived here.
        value["metric_availability"] = {
            "state": "known" if usage.get("state") in {"known", "qualified", "available"} else "unavailable",
            "value": _json_value(usage.get("metrics")) if isinstance(usage.get("metrics"), Mapping) else None,
        }
    else:
        value["metric_availability"] = {"state": "unavailable", "value": None,
                                         "reason": "no qualified metric observation retained"}
    return value


def _reader_actor(grant: Any, actor: Any) -> Any:
    """Bridge the CLI's actor label to the already-admitted authenticated actor."""
    principal = getattr(grant, "principal", None)
    if isinstance(actor, str) and getattr(principal, "actor", None) == actor:
        return principal
    return actor


def _project_identity(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping) and all(isinstance(value.get(key), str) and value.get(key).strip()
                                          for key in ("authority", "kind", "id")):
        if value["kind"] != "work.project":
            raise ObservabilityViewError("project scope must contain work.project refs")
        return value["authority"], value["id"]
    raise ObservabilityViewError("project scope must contain canonical project refs")


class ObservabilityViews:
    """The seven D04 presets over one injected authenticated reader."""

    def __init__(self, reader: Any):
        if not callable(getattr(reader, "read", None)):
            raise TypeError("an authenticated Events reader is required")
        self.reader = reader

    def read(self, view: str, *, projects: Optional[Sequence[Any]] = None,
             from_at: Any = None, to_at: Any = None, timezone_name: Optional[str] = None,
             active_during: Optional[Sequence[Any]] = None, limit: int = 50,
             cursor: Optional[str] = None, snapshot: Optional[Mapping[str, Any]] = None,
             grant: Any = None, actor: Any = None,
             filters: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        if view not in VIEW_PRESETS:
            raise ObservabilityViewError("unsupported Events operator view")
        result = self.reader.read(
            projects=projects, from_at=from_at, to_at=to_at, timezone_name=timezone_name,
            active_during=active_during, limit=limit, cursor=cursor, snapshot=snapshot,
            grant=grant, actor=_reader_actor(grant, actor), filters=filters,
        )
        if not isinstance(result, Mapping):
            raise ObservabilityViewError("Events reader returned no bounded response")
        source_rows = [row for row in result.get("rows", ()) if isinstance(row, Mapping)]
        if view == "usage":
            value = _envelope(view, result, source_rows)
            attempt_rows = [row for row in source_rows
                            if row.get("facet_type") == "retained_attempt_or_result"
                            or isinstance(_mapping(row.get("summary")).get("usage"), Mapping)]
            value["usage"] = {
                "known_attempts": [_usage_row(row) for row in attempt_rows],
                "metric_availability": [
                    _usage_row(row)["metric_availability"] for row in attempt_rows
                ],
            }
            return value
        value = _envelope(view, result, source_rows)
        if view == "overview":
            value["attention"] = [{
                "subject_ref": row.get("subject_ref"),
                "facet_type": row.get("facet_type"),
                "responsible_actor": _semantic(row).get("responsible_actor"),
                "latest_verified_fact": row.get("summary"),
            } for row in source_rows]
            value["handoff"] = {
                "response_application": "retained facts are shown independently",
                "native_result_task_acceptance": "retained facts are shown independently",
                "unknowns_are_explicit": True,
            }
        elif view == "agents":
            value["agents"] = [{
                "subject_ref": row.get("subject_ref"),
                "role": row.get("role"),
                "responsible_actor": _semantic(row).get("responsible_actor"),
            } for row in source_rows]
        elif view == "tasks-reviews":
            value["task_reviews"] = [{
                "subject_ref": row.get("subject_ref"),
                "outcome": row.get("outcome"),
                "native_result": _semantic(row).get("native_result"),
                "task_acceptance": _semantic(row).get("task_acceptance"),
                "responsible_actor": _semantic(row).get("responsible_actor"),
            } for row in source_rows]
        elif view == "blockers":
            value["blockers"] = [{
                "subject_ref": row.get("subject_ref"),
                "state": row.get("outcome"),
                "responsible_actor": _semantic(row).get("responsible_actor"),
            } for row in source_rows]
        elif view == "recovery":
            value["recovery"] = [{
                "subject_ref": row.get("subject_ref"),
                "state": row.get("outcome"),
                "response": _semantic(row).get("response"),
                "application": _semantic(row).get("application"),
                "next_action": "inspect retained detail; this view never executes recovery",
            } for row in source_rows]
        return value

    def detail(self, facet_id: str, *, snapshot: Mapping[str, Any], projects: Optional[Sequence[Any]] = None,
               grant: Any = None, actor: Any = None, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        if not isinstance(facet_id, str) or not facet_id.strip():
            raise ObservabilityViewError("facet_id is required")
        if projects is not None:
            scope = snapshot.get("scope") if isinstance(snapshot, Mapping) else None
            scoped_projects = scope.get("projects") if isinstance(scope, Mapping) else None
            if not isinstance(scoped_projects, (tuple, list)):
                raise ObservabilityViewError("detail snapshot has no project scope")
            requested = tuple(_project_identity(item) for item in projects)
            normalized_snapshot = tuple(_project_identity({"authority": item[0], "kind": "work.project", "id": item[1]})
                                       if isinstance(item, (tuple, list)) and len(item) == 2 else _project_identity(item)
                                       for item in scoped_projects)
            if set(requested) != set(normalized_snapshot):
                raise ObservabilityViewError("detail project scope must match the original snapshot")
        result = self.reader.detail(facet_id, snapshot=snapshot, grant=grant,
                                    actor=_reader_actor(grant, actor), max_bytes=max_bytes)
        if not isinstance(result, Mapping):
            raise ObservabilityViewError("Events reader returned no bounded detail")
        summary = _mapping(result.get("summary"))
        return {
            "outcome": "read",
            "schema": "otto.events.operator-detail.v1",
            "view": "detail",
            "read_only": True,
            "dispatch": False,
            "launch": False,
            "scope": _scope({"snapshot": result.get("snapshot", snapshot), "projects": [result.get("project_ref")]}),
            "coverage": {"detail": "selected authorized facet", "bounded": True},
            "continuation": {"snapshot_digest": snapshot.get("snapshot_digest"), "next_cursor": None, "partial": False, "has_more": False},
            "facet_id": facet_id,
            "project_ref": _json_value(result.get("project_ref")),
            "summary": _json_value(summary),
            "semantic": _semantic({"summary": summary}),
            "detail_locator": _json_value(result.get("detail_locator")),
            "evidence": _json_value(result.get("evidence")),
            "bytes": _json_value(result.get("bytes")),
            "truncated": bool(result.get("truncated", False)),
            "io_work": _json_value(result.get("io_work", {})),
        }


__all__ = ["ObservabilityViewError", "ObservabilityViews", "VIEW_PRESETS"]
