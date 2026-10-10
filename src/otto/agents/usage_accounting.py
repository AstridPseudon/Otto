"""Pure bounded accounting over admitted, retained Usage facts.

The caller supplies an authorized complete window from Events, with its fixed
append boundary. This module never reads heads, repairs evidence or launches
work. A partial window produces page totals only.
"""
from __future__ import annotations

from collections import defaultdict
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .usage_contract import ADAPTER_DESCRIPTORS, OBSERVATION_SCHEMA, METRIC_FIELDS, OBSERVATION_STATES, physical_span_identity

FACT_SCHEMA = "otto.usage-retained-fact.v1"
MAX_FACTS = 1024


def instant(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("qualified time must include a timezone")
    return stamp.astimezone(timezone.utc)


def ref_key(value: Any):
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(value.get(k), str) and value[k] for k in ("authority", "kind", "id")):
        return None
    return tuple(value[k] for k in ("authority", "kind", "id"))


def qualified_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate normalized metrics and physical identity, including exclusions."""
    value = deepcopy(dict(value))
    adapter = ADAPTER_DESCRIPTORS.get(value.get("adapter_id"))
    if value.get("schema") != OBSERVATION_SCHEMA or adapter is None:
        raise ValueError("selected qualified observation required")
    identity = value.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("exact physical span required")
    scope = identity.get("metric_scope")
    if scope == "cumulative":
        # Preserve an explicitly qualified cumulative fact without computing
        # deltas or making its numeric snapshot additive.
        scope_for_identity = "turn"
    else:
        scope_for_identity = scope
    expected = physical_span_identity(namespace=adapter["namespace"], metric_scope=scope_for_identity,
        session_id=identity.get("session_id"), turn_id=identity.get("turn_id"),
        invocation_id=identity.get("invocation_id"))
    if scope == "cumulative":
        from .usage_capture import digest
        expected = {**expected, "metric_scope": scope}
        expected["span_id"] = "usage-span-" + digest({k: v for k, v in expected.items() if k != "span_id"})
    environment = {k: adapter[k] for k in ("provider", "environment", "namespace")}
    if identity != expected or value.get("provider_environment") != environment:
        raise ValueError("physical namespace or identity differs from qualified adapter")
    usage = value.get("usage")
    if not isinstance(usage, Mapping) or usage.get("scope") != scope or usage.get("state") not in OBSERVATION_STATES:
        raise ValueError("metric scope differs from physical span")
    metrics = usage.get("metrics")
    if usage.get("state") in {"observed", "zero"}:
        if not isinstance(metrics, Mapping) or not metrics or set(metrics) - set(METRIC_FIELDS):
            raise ValueError("qualified metric components required")
        if any(type(v) is not int or v < 0 for v in metrics.values()):
            raise ValueError("usage counts must be nonnegative integers")
        if (usage["state"] == "zero") != all(v == 0 for v in metrics.values()):
            raise ValueError("zero state differs from metrics")
    elif metrics:
        raise ValueError("unqualified observations cannot contribute numbers")
    for carrier in ("observed", "requested"):
        metadata = value.get(carrier) or {}
        value[carrier] = {field: metadata.get(field) if isinstance(metadata.get(field), str)
            and metadata[field].strip() else None for field in ("model", "tier")}
    return value


def account_usage(facts: Sequence[Mapping[str, Any]], *, as_of: int,
                  authorized_projects: Sequence[Mapping[str, Any]],
                  from_at: str | None = None, to_at: str | None = None,
                  complete: bool = False) -> dict[str, Any]:
    """Fold immutable facts at one append boundary; groupings are alternate views.

    Shared facts need every participating project grant. Restricted shared facts
    expose only limited coverage, without identities, amounts or provenance.
    Missing components stay absent; output/reasoning and cached/input totals
    remain separate provider components, never an invented total token count.
    """
    if len(facts) > MAX_FACTS or type(as_of) is not int or as_of < 0:
        raise ValueError("bounded facts and append boundary required")
    if (from_at is None) != (to_at is None):
        raise ValueError("recorded period requires both bounds")
    start, end = (instant(from_at), instant(to_at)) if from_at else (None, None)
    if start is not None and end <= start:
        raise ValueError("recorded period must be nonempty")
    allowed = {ref_key(p) for p in authorized_projects}
    if None in allowed or any(k[1] != "work.project" for k in allowed):
        raise ValueError("authorized project identities required")
    spans = defaultdict(list)
    for raw in facts:
        if raw.get("schema") != FACT_SCHEMA:
            raise ValueError("only admitted retained facts enter totals")
        pos = raw.get("append_position")
        if type(pos) is not int or pos < 1:
            raise ValueError("authoritative append position required")
        if pos > as_of:
            continue
        item = deepcopy(dict(raw))
        item["observation"] = qualified_observation(item["observation"])
        if not item.get("first_qualified_recorded_at"):
            continue  # missing/invalid attempts have coverage but no spend anchor
        instant(item["first_qualified_recorded_at"])
        spans[item["observation"]["identity"]["span_id"]].append(item)
    rows, excluded, limited = [], [], 0
    totals = {}; groups = {name: {} for name in ("project", "task", "agent")}
    missing = sum(1 for f in facts if f.get("append_position", as_of + 1) <= as_of
        and ref_key(f.get("association", {}).get("project_ref")) in allowed
        and f.get("observation", {}).get("usage", {}).get("state") not in {"observed", "zero"})
    for span_id, items in sorted(spans.items()):
        items.sort(key=lambda i: i["append_position"])
        anchor = min((i["first_qualified_recorded_at"] for i in items), key=instant)
        if start is not None and not start <= instant(anchor) < end:
            continue
        projects = {ref_key(i.get("association", {}).get("project_ref")) for i in items}
        projects.discard(None)
        shared_count = max(i.get("shared_scope_count", 1) for i in items)
        if not projects or not projects.issubset(allowed) or shared_count > len(projects):
            limited += 1
            continue
        ref_id = lambda r: json.dumps(r, sort_keys=True, separators=(",", ":"))
        active = {ref_id(i["ref"]): i for i in items}
        # Only an admitted explicit predecessor reference can supersede a fact;
        # conflicting branches are preserved and excluded below.
        for item in items:
            predecessor = item.get("supersedes_ref")
            if predecessor is not None:
                basis = next((i for i in items if ref_id(i["ref"]) == ref_id(predecessor)), None)
                if basis is None:
                    raise ValueError("correction predecessor outside selected history; totals unavailable")
                basis_metrics = basis["observation"]["usage"].get("metrics") or {}
                for prior in items:
                    prior_metrics = prior["observation"]["usage"].get("metrics") or {}
                    if (prior["append_position"] < item["append_position"]
                            and prior.get("supersedes_ref") is None
                            and prior.get("association") == basis.get("association")
                            and prior_metrics and set(prior_metrics).issubset(basis_metrics)
                            and all(basis_metrics[k] == v for k, v in prior_metrics.items())):
                        active.pop(ref_id(prior["ref"]), None)
                active.pop(ref_id(predecessor), None)
        values = list(active.values())
        metrics = {}; conflicts = set()
        for item in values:
            for field, amount in (item["observation"]["usage"].get("metrics") or {}).items():
                if field in metrics and metrics[field] != amount:
                    conflicts.add(field)
                else:
                    metrics[field] = amount
        observed = {field: sorted({i["observation"].get("observed", {}).get(field) for i in values
            if i["observation"].get("observed", {}).get(field) is not None}) for field in ("model", "tier")}
        reason = None
        if conflicts or any(i["observation"]["usage"]["state"] == "conflict" for i in values):
            reason = "conflict"
        elif any(i["observation"]["identity"]["metric_scope"] == "cumulative" for i in values):
            reason = "cumulative-not-additive"
        elif any(i["observation"].get("population_scope", "self") != "self" for i in values):
            reason = "parent-child-scope-unproven"
        elif not metrics:
            reason = "metrics-unavailable"
        associations = [i.get("association", {}) for i in values]
        agents = {(ref_key(a.get("assignment_ref")), a.get("generation"), json.dumps(a.get("principal"), sort_keys=True)) for a in associations}
        tasks = {ref_key(a.get("task_ref")) for a in associations}; tasks.discard(None)
        historical = all(ref_key(a.get("assignment_ref")) and type(a.get("generation")) is int
            and a["generation"] > 0 and a.get("principal") for a in associations)
        if not historical:
            reason = reason or "attribution-unknown"
        shared = len(projects) > 1
        row = {"span_id": span_id, "identity": items[0]["observation"]["identity"],
            "first_qualified_recorded_at": anchor, "first_qualified_provenance": items[0].get("first_qualified_provenance"),
            "metrics": None if reason else metrics, "state": reason or ("shared-unallocated" if shared else "measured"),
            "attribution": {"project": "shared" if shared else "proven",
                "task": "shared" if len(tasks) > 1 else ("proven" if tasks and all(a.get("task_ref") for a in associations) else "unknown"),
                "agent": "shared" if len(agents) > 1 else ("proven" if historical else "unknown")},
            "associations": associations, "observed": {k: v[0] if len(v) == 1 else None for k, v in observed.items()},
            "model_tier_coverage": "conflict" if any(len(v) > 1 for v in observed.values()) else (
                "qualified" if observed["model"] else "unavailable"),
            "evidence_refs": [i["ref"] for i in items],
            "execution_time": items[0].get("execution_time"), "as_of": as_of}
        rows.append(row)
        if reason:
            excluded.append({"span_id": span_id, "reason": reason}); continue
        for field, amount in metrics.items(): totals[field] = totals.get(field, 0) + amount
        group_keys = {"project": None if shared else next(iter(projects)),
            "task": next(iter(tasks)) if not shared and len(tasks) == 1 and all(a.get("task_ref") for a in associations) else None,
            "agent": next(iter(agents)) if not shared and len(agents) == 1 else None}
        for name, key in group_keys.items():
            if key is None:
                excluded.append({"span_id": span_id, "group": name,
                    "reason": "shared-unallocated" if shared or name == "task" and len(tasks) > 1 or name == "agent" and len(agents) > 1 else "initializer-or-attribution-unknown"})
                continue
            encoded = repr(key)
            bucket = groups[name].setdefault(encoded, {"identity": key, "metrics": {}, "span_count": 0})
            bucket["span_count"] += 1
            for field, amount in metrics.items(): bucket["metrics"][field] = bucket["metrics"].get(field, 0) + amount
    return {"schema": "otto.usage-accounting.v1", "as_of": as_of, "spans": rows,
        "metrics": totals or None, "groups": {k: list(v.values()) for k, v in groups.items()},
        "exclusions": excluded, "coverage": {"totals": "exact-window" if complete else "page-only",
            "limited": limited, "missing_or_invalid_observations": missing,
            "measured_spans": sum(r["metrics"] is not None for r in rows), "unknown_is_zero": False}}
