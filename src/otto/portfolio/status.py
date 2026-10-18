"""Fast owner-side portfolio projection from current records, never sheet exports.

The owner service supplies the already-open session. Per-kind field
projections use the kernel's bounded identity reader
(``project_identity_fields``): one read of current identities per kind, never
event history, no consumer SQL and no new persistence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional

from herzchen.contracts import ResourceRef


_MANAGER_FIELDS = {"project_id": ("scope", "id"), "principal": ("principal",), "generation": ("generation",),
                   "status": ("status",)}
_MANAGER_SCOPE = {("role",): "manager", ("scope", "kind"): "work.project"}
_DUE_FIELDS = ("project_ref", "schedule_id", "role", "stop_state", "in_flight_request", "delivered_at",
               "timeout_seconds", "allowance_ref", "accepted_checkins")


def _identity(value: Any) -> tuple:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return tuple((value or {}).get(key) for key in ("authority", "kind", "id"))


def _portfolio(session: Any, selected: Any) -> ResourceRef:
    own = (session.host or {}).get("portfolio_ref")
    if selected is None:
        selected = own
        if selected is None:
            choices = list((session.config.get("hosts") or {}).values())
            if len(choices) == 1:
                selected = choices[0]["portfolio_ref"]
    if isinstance(selected, str):
        selected = ResourceRef(session.store.authority, "wrk.portfolio", selected)
    elif isinstance(selected, Mapping):
        selected = ResourceRef.from_dict(selected)
    if not isinstance(selected, ResourceRef):
        raise ValueError("select a portfolio with --portfolio")
    if selected.authority != session.store.authority or selected.kind != "wrk.portfolio":
        raise PermissionError("portfolio scope is outside this owner")
    if own is not None and _identity(selected) != _identity(own):
        raise PermissionError("a host may read only its own portfolio")
    return selected


def _project_rows(store: Any, kind: str, scope: tuple, ids: list, fields: Mapping[str, tuple],
                  *, matches: Optional[Mapping[tuple, str]] = None,
                  choices: Optional[Mapping[tuple, tuple]] = None) -> list:
    """Named fields of one kind's current identities for these projects (kernel reader)."""
    reader = store.consumer() if hasattr(store, "consumer") else store
    return [dict(row) for row in reader.project_identity_fields(kind=kind, match_path=scope, match_values=ids,
            fields=fields, payload_matches=matches, payload_in=choices)]


def _json_file(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _stamp(value: Any) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (AttributeError, TypeError, ValueError):
        return None


def _manager(assignments: list, dues: list, service: Mapping[str, Any], project_id: str,
             now: datetime) -> dict:
    current = [item for item in assignments if item["status"] not in {"completed", "cancelled"}]
    attached = any(item.get("project_id") == project_id for item in
                   service.get("attached_projects", [service.get("attached_project") or {}]))
    heartbeat = service.get("heartbeat_at") if attached else None
    turns = service.get("manager_turns")
    queued = bool((turns or {}).get("queued_by_project", {}).get(project_id))
    active_turn = (project_id in turns.get("active_projects", ()) or queued) if turns is not None else (
        attached and bool(service.get("manager_turn_active")))
    running = active_turn or any(item["status"] == "in-flight" for item in current)
    manager_dues = [item for item in dues if item["role"] == "manager"]
    running = running or any(item["in_flight_request"] and item["stop_state"] == "active"
                             for item in manager_dues)
    stalled = []
    heartbeat_stamp = _stamp(heartbeat)
    if running and attached and heartbeat_stamp is not None:
        age = (now - heartbeat_stamp).total_seconds()
        if age > 3 * float(service.get("heartbeat_seconds") or 1) + 2 or service.get("state") == "closed":
            stalled.append("owner_heartbeat_stale")
    for due in manager_dues:
        delivered = _stamp(due["delivered_at"])
        if (due["in_flight_request"] and delivered and due["timeout_seconds"]
                and (now - delivered).total_seconds() > due["timeout_seconds"]):
            stalled.append("manager_turn_timeout")
    return {"state": "running" if running else "paused" if current else "none",
            "queued": queued,
            "assignments": [{key: item[key] for key in ("ref", "principal", "generation", "status")}
                            for item in current],
            "last_heartbeat": heartbeat, "heartbeat_source": "owner_service" if heartbeat else None,
            "stalled": bool(stalled), "stall_reasons": sorted(set(stalled))}


def manager_activity(store: Any, project_ref: Any, *,
                     service_status: Optional[Mapping[str, Any]] = None,
                     now: Optional[datetime] = None) -> dict:
    """Finite owner read for detach admission, including retained in-flight Due.

    A queued assignment can already own a running native turn. Both persisted
    occurrence state and the service's live observation therefore matter.
    """
    authority, kind, project_id = _identity(project_ref)
    if authority != store.authority or kind != "work.project":
        raise PermissionError("manager activity requires an owner-local project")
    assignments = _project_rows(store, "wrk.assignment", ("scope", "id"), [project_id],
                                 _MANAGER_FIELDS, matches=_MANAGER_SCOPE)
    dues = _project_rows(store, "otto.due-record", ("project_ref",), [project_id],
                         {key: (key,) for key in _DUE_FIELDS})
    return _manager(assignments, dues, service_status or {}, project_id, now or datetime.now(timezone.utc))


def portfolio_status(session: Any, portfolio_ref: Any = None, *,
                     service_status: Optional[Mapping[str, Any]] = None,
                     owner_authorized: bool = False,
                     now: Optional[datetime] = None,
                     labs: Any = None) -> dict[str, Any]:
    """Read a host's own portfolio, or an owner's explicitly selected portfolio.

    Call under the owner service command lock. Readiness is computed without
    persisting observations, so status never manufactures project activity.
    ``labs`` is an optional ``LabFleet``; its count is the lab count (``None``
    when no fleet is supplied). ``slot_kinds`` are the responsibility slots.
    """
    from otto.agents.host_profiles import SLOTS
    from .dependencies import PortfolioDependencies
    from .issue_loop import IssueLoop

    portfolio = _portfolio(session, portfolio_ref)
    now = now or datetime.now(timezone.utc)
    refs = session.store.find_identity_refs(kind="work.project", payload_matches={
        ("metadata", "otto_orchestrator", "portfolio_ref", "authority"): portfolio.authority,
        ("metadata", "otto_orchestrator", "portfolio_ref", "kind"): portfolio.kind,
        ("metadata", "otto_orchestrator", "portfolio_ref", "id"): portfolio.id})
    records = [session.store.get_identity(ref) for ref in refs]
    records = [record for record in records if _identity((record.payload.get("metadata") or {}).get(
        "otto_orchestrator", {}).get("project_ref")) == _identity(record.ref)]
    cache = {_identity(record.ref): record for record in records}
    ids = [record.ref.id for record in records]
    tasks = _project_rows(session.store, "work.task", ("project_ref", "id"), ids,
                          {"project_id": ("project_ref", "id"), "lifecycle": ("lifecycle",)})
    assignments = _project_rows(session.store, "wrk.assignment", ("scope", "id"), ids,
        _MANAGER_FIELDS, matches=_MANAGER_SCOPE)
    dues = _project_rows(session.store, "otto.due-record", ("project_ref",), ids,
                         {key: (key,) for key in _DUE_FIELDS})
    issue_fields = ("schema", "issue_id", "issue_version", "observed_at", "project_ref", "purpose", "problem",
                    "awaiting", "disposition", "origin_assignment_ref", "current_owner_ref", "origin", "overdue_identity")
    reports = _project_rows(session.store, "wrk.report", ("value", "project_ref", "id"), ids,
        {key: ("value", key) for key in issue_fields},
        choices={("value", "schema"): ("otto.issue.v1", "otto.issue.response.v1", "otto.issue.outcome.v1")})
    grouped = {name: defaultdict(list) for name in ("tasks", "assignments", "dues", "reports")}
    for name, rows, field in (("tasks", tasks, "project_id"), ("assignments", assignments, "project_id"),
                               ("dues", dues, "project_ref"), ("reports", reports, "project_ref")):
        for row in rows:
            project_id = row[field].get("id") if isinstance(row[field], Mapping) else row[field]
            grouped[name][project_id].append(row)
    service = service_status if service_status is not None else _json_file(
        Path(session.config["home"]) / "run" / "service.json")
    actor = (session.binding.authenticated_actor(session.host["principal"])
             if session.host and not owner_authorized else session.owner.owner_actor)
    dependencies = PortfolioDependencies(session.owner.graph, session.store.consumer(), actor=actor,
                                        owner_actor=session.owner.owner_actor, portfolio_ref=portfolio)
    limits = session.owner._limit_service
    projects, attention, all_pools = [], [], {}
    for record in records:
        pid = record.ref.id
        readiness = dependencies.readiness(record.ref, observe=False, cache=cache)
        supervised = dependencies.supervises(record.ref, cache=cache)
        project_dues = grouped["dues"][pid]
        manager = _manager(grouped["assignments"][pid], project_dues, service, pid, now)
        issue_reports = [{"ref": row["ref"], "value": {key: value for key, value in row.items()
                          if value is not None}} for row in grouped["reports"][pid]]
        issues = []
        for issue in IssueLoop.derive_issues(issue_reports):
            opened = issue["opened_record"]
            proved = (opened.get("origin") == "trusted_supervisor_observation"
                      and opened.get("problem") == "overdue_checkin"
                      and any(IssueLoop._due_proves(SimpleNamespace(**{**due,
                                  "accepted_checkins": due["accepted_checkins"] or ()}), opened.get("overdue_identity"))
                              for due in project_dues))
            if issue["state"] != "open" or proved:
                continue
            issues.append({key: issue[key] for key in ("issue_id", "purpose", "awaiting", "current_owner_ref")})
            issues[-1]["problem"] = opened.get("problem")
            if issue["awaiting"] == "orchestrator":
                attention.append({"project_ref": record.ref.to_dict(), "reason": "help_request", **issues[-1]})
        registration = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
        run_id = registration.get("run_id")
        valid_run_id = isinstance(run_id, str) and bool(run_id)
        if valid_run_id:
            from otto.hostctl.cli import receipt_path
            receipt = _json_file(receipt_path(Path(session.config["home"]), "activate-" + run_id))
        else:
            receipt = {}
        pool_refs = [item.get("pool_ref") for item in (receipt.get("steps") or {}).get("allowances", ())]
        pool_refs.extend(due["allowance_ref"] for due in project_dues if due["allowance_ref"])
        pools = {}
        for raw in pool_refs:
            if not isinstance(raw, Mapping) or raw.get("authority") != portfolio.authority or raw.get("kind") != "limit":
                continue
            ref = ResourceRef(raw["authority"], raw["kind"], raw["id"])
            pool = limits.get_pool(ref)
            if pool is not None:
                pools[ref.id] = {"ref": pool.ref.to_dict(), "capacity_units": pool.capacity_units,
                    "cumulative_allowance_units": pool.cumulative_allowance_units, "used": pool.cumulative_used_units,
                    "held": pool.held_units, "remaining": pool.remaining_allowance_units}
        all_pools.update(pools)
        stamps = [record.updated_at] + [row["updated_at"] for name in grouped for row in grouped[name][pid]]
        override = readiness.get("override")
        row = {"project_ref": record.ref.to_dict(), "title": record.payload.get("title"),
               "lifecycle": record.payload.get("lifecycle"), "supervised": supervised, "readiness": readiness,
               "retirement": record.payload.get("retirement"),
               "manager": manager, "task_counts": dict(Counter(item["lifecycle"] for item in grouped["tasks"][pid])),
               "open_help_requests": issues, "allowances": list(pools.values()),
               "last_activity_at": max(stamps), "readiness_override": override}
        projects.append(row)
        if readiness["ready"] and row["lifecycle"] in {"pending", "paused"}:
            attention.append({"project_ref": record.ref.to_dict(), "reason": "ready_not_active"})
        if override:
            attention.append({"project_ref": record.ref.to_dict(), "reason": "readiness_overridden", "override": override})
        if manager["stalled"]:
            attention.append({"project_ref": record.ref.to_dict(), "reason": "stalled_manager", "details": manager["stall_reasons"]})
    return {"outcome": "read", "schema": "otto.portfolio-status.v1", "portfolio_ref": portfolio.to_dict(),
            "projects": projects, "totals": {"projects": len(projects),
                "lifecycle": dict(Counter(row["lifecycle"] for row in projects)),
                "readiness": dict(Counter(row["readiness"]["status"] for row in projects)),
                "managers": dict(Counter(row["manager"]["state"] for row in projects)),
                "tasks": dict(Counter(item["lifecycle"] for item in tasks)),
                "open_help_requests": sum(len(row["open_help_requests"]) for row in projects),
                "allowances": {key: sum(pool[key] for pool in all_pools.values())
                               for key in ("cumulative_allowance_units", "used", "held", "remaining")}},
            "needs_orchestrator": attention, "observed_at": now.isoformat(), "read_only": True,
            "provider_called": False, "labs": {"count": None if labs is None else len(labs.names())},
            "slot_kinds": list(SLOTS)}
