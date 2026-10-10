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
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from .usage_contract import (
    ADAPTER_DESCRIPTORS,
    CHARGEABLE_FIELDS,
    OBSERVATION_SCHEMA,
    METRIC_FIELDS,
    OBSERVATION_STATES,
    validate_rate_schedule,
    physical_span_identity,
)

FACT_SCHEMA = "otto.usage-retained-fact.v1"
MAX_FACTS = 1024
MONEY_SCHEMA = "otto.usage-money.v1"
PRICE_SCHEMA = "otto.usage-price-estimate.v1"


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


def _money_decimal(value: Any, field: str) -> Decimal | None:
    """Parse a monetary value without passing through binary floating point."""
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int) and type(value) is int:
        parsed = Decimal(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return None
    else:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _money_text(value: Decimal) -> str:
    """Return a stable decimal representation for JSON/readback contracts."""
    return format(value, "f")


def _provider_money(raw: Any) -> dict[str, Any] | None:
    """Normalize an optional provider monetary fact, never an estimate.

    Provider-reported usage estimates and billed receipts are intentionally
    retained as separate statuses.  A missing currency or amount is not
    repaired with the rate schedule and therefore remains unavailable.
    """
    if raw is None:
        return {"schema": MONEY_SCHEMA, "status": "missing", "amount": None,
                "currency": None, "reason": "provider did not report monetary usage"}
    if not isinstance(raw, Mapping):
        return {"schema": MONEY_SCHEMA, "status": "unavailable", "reason": "malformed provider money"}
    source = raw.get("source") or raw.get("provenance")
    source = deepcopy(dict(source)) if isinstance(source, Mapping) else None
    currency = raw.get("currency")
    amount = _money_decimal(raw.get("amount"), "amount")
    status = raw.get("status") or raw.get("kind")
    aliases = {
        "estimate": "usage_report_estimate",
        "usage-estimate": "usage_report_estimate",
        "usage-report-estimate": "usage_report_estimate",
        "usage_reported_estimate": "usage_report_estimate",
        "actual_billed": "billed",
        "billing": "billed",
    }
    status = aliases.get(status, status)
    if status in {"missing", "unavailable"}:
        result = {"schema": MONEY_SCHEMA, "status": status, "amount": None,
                  "currency": None, "reason": raw.get("reason") or "provider money unavailable"}
        for key in ("source", "capability", "metric_scope", "population_scope"):
            if raw.get(key) is not None:result[key] = deepcopy(raw[key])
        return result
    if status is None and amount is not None and isinstance(currency, str) and currency.strip():
        status = "zero" if amount == 0 else "usage_report_estimate"
    if status not in {"zero", "usage_report_estimate", "billed"}:
        return {"schema": MONEY_SCHEMA, "status": "unavailable", "reason": "provider money status is unavailable"}
    if (not isinstance(currency, str) or len(currency) != 3
            or not currency.isascii() or not currency.isupper() or not currency.isalpha()
            or amount is None):
        return {"schema": MONEY_SCHEMA, "status": "unavailable", "reason": "provider money lacks amount or currency"}
    if status == "billed" and not any(raw.get(key) is not None for key in ("receipt_ref", "billing_ref")):
        source_kind = source.get("kind") if isinstance(source, Mapping) else None
        if source_kind not in {"billing", "billing-receipt", "provider-billing-receipt"}:
            return {"schema": MONEY_SCHEMA, "status": "unavailable", "reason": "billed provenance is missing"}
    if status == "zero" and amount != 0:
        return {"schema": MONEY_SCHEMA, "status": "unavailable", "reason": "provider zero has nonzero amount"}
    result = {
        "schema": MONEY_SCHEMA,
        "status": status,
        "amount": _money_text(amount),
        "currency": currency.strip(),
        "provider": raw.get("provider"),
        "source": source,
    }
    for key in ("receipt_ref", "billing_ref", "usage_report_ref", "recorded_at", "metric_scope", "population_scope", "capability"):
        if raw.get(key) is not None:
            result[key] = deepcopy(raw[key])
    return result


def _consumption_time(item: Mapping[str, Any]) -> str | None:
    """Use only an explicitly retained qualified consumption timestamp."""
    for key in ("consumption_time", "execution_time"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            try:
                instant(value)
            except (TypeError, ValueError):
                continue
            return value
    return None


def _rate_entry(schedule: Mapping[str, Any], model: Any, tier: Any) -> tuple[str, Mapping[str, Any]] | None:
    if not isinstance(model, str) or not model.strip():
        return None
    tier = tier if isinstance(tier, str) and tier.strip() else "default"
    key = model.strip() + "/" + tier.strip()
    entry = schedule.get("entries", {}).get(key)
    return (key, entry) if isinstance(entry, Mapping) else None


def estimate_span_cost(row: Mapping[str, Any], *, rate_schedule: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Price one already-deduplicated accounting row with exact Decimal math.

    The function is deliberately pure.  It returns an honest unavailable
    result when attribution, model/tier, qualified consumption time, rate, or
    currency is absent.  ``reasoning_output_tokens`` is a subpartition of
    ``output_tokens`` and is never charged as an additional component.
    """
    schedule = validate_rate_schedule(rate_schedule)
    result: dict[str, Any] = {"schema": PRICE_SCHEMA, "status": "unavailable", "amount": None,
                              "currency": None, "reason": None, "coverage": "unpriced"}
    if row.get("state") not in {"measured", "zero"} or not isinstance(row.get("metrics"), Mapping):
        result["reason"] = row.get("state") or "metrics-unavailable"
        return result
    attribution = row.get("attribution")
    if not isinstance(attribution, Mapping) or any(attribution.get(name) not in {"proven", "shared", "unknown"} for name in ("project", "task", "agent")):
        result["reason"] = "attribution-unavailable"
        return result
    # Initializer overhead may be project/agent-attributed while its task is
    # intentionally unknown; it is still not a shared or unallocated span.
    if attribution.get("project") != "proven" or attribution.get("agent") != "proven" or attribution.get("task") == "shared":
        result["reason"] = "shared-or-unallocated"
        return result
    observed = row.get("observed") if isinstance(row.get("observed"), Mapping) else {}
    model = observed.get("model") or row.get("model")
    tier = observed.get("tier") or row.get("tier") or "default"
    entry_info = _rate_entry(schedule, model, tier)
    if entry_info is None:
        result["reason"] = "missing-model-or-rate"
        return result
    item = row.get("_source") if isinstance(row.get("_source"), Mapping) else row
    consumption_time = _consumption_time(item)
    if consumption_time is None:
        result["reason"] = "missing-qualified-consumption-time"
        return result
    metrics = dict(row["metrics"])
    namespace = row.get('identity',{}).get('namespace')
    codex_namespace = ADAPTER_DESCRIPTORS['codex-host']['namespace']
    partition = 'provider-exclusive-input-partitions'
    if namespace == codex_namespace and 'input_tokens' in metrics:
        total,cached = metrics['input_tokens'],metrics.get('cached_input_tokens')
        if type(total) is not int or type(cached) is not int or not 0 <= cached <= total:
            result['reason']='missing-or-invalid-codex-cache-partition'
            return result
        metrics['input_tokens']=total-cached
        partition='codex-total-input-minus-cached; cached priced once'
    components: dict[str, str] = {}
    amount = Decimal("0")
    for field in CHARGEABLE_FIELDS:
        if field not in metrics:
            continue
        count = metrics[field]
        if type(count) is not int or count < 0:
            result["reason"] = "invalid-metrics"
            return result
        rate = _money_decimal(entry_info[1].get(field), field)
        if rate is None:
            result["reason"] = "missing-rate"
            return result
        component = Decimal(count) * rate
        components[field] = _money_text(component)
        amount += component
    if not components:
        result["reason"] = "missing-metrics"
        return result
    effective = schedule.get("effective_period")
    period = effective if isinstance(effective, Mapping) else None
    if period is not None:
        start, finish = period.get("from"), period.get("to")
        if isinstance(start, str) and isinstance(finish, str):
            observed_time = instant(consumption_time)
            if not instant(start) <= observed_time <= instant(finish):
                result["reason"] = "rate-not-effective"
                return result
    result.update({
        "status": "estimated",
        "amount": _money_text(amount),
        "currency": schedule.get("currency"),
        "coverage": "measured-attributed",
        "model": model,
        "tier": tier,
        "consumption_time": consumption_time,
        "components": components,
        'input_partition_basis':partition,
        "rate_schedule": {
            "schedule_id": schedule["schedule_id"],
            "source": deepcopy(schedule["source"]),
            "effective_period": deepcopy(schedule.get("effective_period")),
            "currency": schedule["currency"],
            "formula": schedule["formula"],
        },
        "reasoning_additive": False,
    })
    return result


def _money_fingerprint(value: Mapping[str, Any]) -> str:
    # Transport/source aliases do not create competing monetary amounts.
    fields = ("status", "amount", "currency", "provider", "metric_scope",
              "population_scope", "receipt_ref", "billing_ref")
    return json.dumps({k: value.get(k) for k in fields}, sort_keys=True, separators=(",", ":"))


def _monetary_coverage(rows: Sequence[Mapping[str, Any]], *, complete: bool, missing: int = 0) -> dict[str, Any]:
    estimates = [r.get("price_estimate") for r in rows if isinstance(r.get("price_estimate"), Mapping)]
    priced = [r for r in estimates if r.get("status") == "estimated"]
    reasons = defaultdict(int)
    for estimate in estimates:
        if estimate.get("status") != "estimated":
            reasons[str(estimate.get("reason") or "unavailable")] += 1
    reported = [r.get("provider_reported_money") for r in rows if isinstance(r.get("provider_reported_money"), Mapping)]
    return {
        "query": "complete" if complete else "partial",
        "history": "as-of-append-boundary",
        "priced_spans": len(priced),
        "unpriced_spans": len(rows) - len(priced),
        "unpriced_reasons": dict(reasons),
        "provider_reported_spans": sum(m.get("status") in {"zero", "usage_report_estimate", "billed"} for m in reported),
        "provider_money_unavailable": sum(m.get("status") == "unavailable" for m in reported),
        "missing_or_invalid_observations": missing,
        "unknown_is_zero": False,
        "reported_and_estimated_are_separate": True,
    }


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
        provider_money_values = []
        for item in values:
            raw_money = next((carrier[key] for carrier, key in (
                (item, "provider_reported_money"), (item, "provider_money"),
                (item, "reported_money"), (item.get("observation", {}), "provider_reported_money"),
                (item.get("observation", {}), "provider_money"))
                if key in carrier and carrier[key] is not None), None)
            if raw_money is not None:
                provider_money_values.append(_provider_money(raw_money))
        usable_money = [item for item in provider_money_values
                        if isinstance(item, Mapping)
                        and item.get("status") in {"zero", "usage_report_estimate", "billed"}]
        money_conflict = len({_money_fingerprint(item) for item in usable_money}) > 1
        if money_conflict:
            reason = reason or "provider-money-conflict"
        provider_money = usable_money[0] if usable_money else (
            provider_money_values[0] if provider_money_values else {
                "schema": MONEY_SCHEMA, "status": "missing", "amount": None,
                "currency": None, "reason": "provider did not report monetary usage",
            })
        money_reason = reason
        if money_conflict:
            # Never choose one conflicting amount; retain all bounded facts.
            provider_money = {"schema": MONEY_SCHEMA, "status": "unavailable",
                "amount": None, "currency": None, "reason": "provider-money-conflict",
                "observations": provider_money_values}
        elif provider_money.get("metric_scope", "turn") not in {"turn", "invocation", "span"}:
            money_reason = money_reason or "provider-money-cumulative-not-additive"
        elif provider_money.get("population_scope", "self") != "self":
            money_reason = money_reason or "provider-money-population-unproven"
        if money_reason and not money_conflict:
            provider_money = {"schema": MONEY_SCHEMA, "status": "unavailable",
                "amount": None, "currency": None, "reason": money_reason,
                "observation": provider_money}
        consumption_time = next((_consumption_time(item) for item in values if _consumption_time(item)), None)
        if consumption_time is None:
            consumption_time = next((_consumption_time(item.get("observation", {}))
                                     for item in values if _consumption_time(item.get("observation", {}))), None)
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
            "execution_time": items[0].get("execution_time"), "consumption_time": consumption_time,
            "provider_reported_money": provider_money, "as_of": as_of}
        row["price_estimate"] = estimate_span_cost(row)
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
    pricing_rows = [r.get("price_estimate") for r in rows if isinstance(r.get("price_estimate"), Mapping)]
    priced = [r for r in pricing_rows if r.get("status") == "estimated"]
    priced_currencies = {r.get("currency") for r in priced if r.get("currency")}
    estimated_total = None
    if len(priced_currencies) == 1:
        estimated_total = _money_text(sum((Decimal(r["amount"]) for r in priced), Decimal("0")))
    pricing = {
        "schema": PRICE_SCHEMA,
        "status": "estimated" if priced else "unavailable",
        "amount": estimated_total,
        "currency": next(iter(priced_currencies)) if len(priced_currencies) == 1 else None,
        "span_count": len(priced),
        "separate_from_provider_reported": True,
    }
    reported = [r.get("provider_reported_money") for r in rows
                if isinstance(r.get("provider_reported_money"), Mapping)]
    provider_summary = {
        "schema": MONEY_SCHEMA,
        "observations": reported,
        "span_count": sum(m.get("status") in {"zero", "usage_report_estimate", "billed"} for m in reported),
        "statuses": sorted({m.get("status") for m in reported}),
        "amount": None,
        "currency": None,
        "missing_spans": sum(m.get("status") == "missing" for m in reported),
        "separate_from_estimate": True,
    }
    reported_currencies = {m.get("currency") for m in reported
                           if m.get("status") in {"zero", "usage_report_estimate", "billed"}}
    if len(reported_currencies) == 1:
        provider_summary["currency"] = next(iter(reported_currencies))
        provider_summary["amount"] = _money_text(sum((Decimal(m["amount"]) for m in reported
                                                       if m.get("currency") in reported_currencies), Decimal("0")))
    coverage = {"totals": "exact-window" if complete else "page-only",
        "limited": limited, "missing_or_invalid_observations": missing,
        "measured_spans": sum(r["metrics"] is not None for r in rows), "unknown_is_zero": False}
    coverage["monetary"] = {
        "query": "complete" if complete else "partial",
        "history": "as-of-append-boundary",
        "priced_spans": len(priced),
        "unpriced_spans": len(rows) - len(priced),
        "provider_reported_spans": provider_summary["span_count"],
        "provider_money_missing": provider_summary["missing_spans"],
        "provider_money_unavailable": sum(m.get("status") == "unavailable" for m in reported),
        "provider_money_exclusion_reasons": sorted({m["reason"] for m in reported
            if m.get("status") == "unavailable" and m.get("reason")}),
        "unknown_is_zero": False,
        "reported_and_estimated_are_separate": True,
    }
    return {"schema": "otto.usage-accounting.v1", "as_of": as_of, "spans": rows,
        "metrics": totals or None, "groups": {k: list(v.values()) for k, v in groups.items()},
        "exclusions": excluded, "pricing": pricing, "cost_estimate": pricing,
        "provider_reported": provider_summary, "monetary": {
            "provider_reported": provider_summary, "price_estimate": pricing,
            "reported_and_estimated_are_separate": True,
        }, "coverage": coverage}


estimate_usage_cost = estimate_span_cost
price_usage = estimate_span_cost
estimate_cost = estimate_span_cost
calculate_cost = estimate_span_cost
normalize_provider_money = _provider_money


__all__ = [
    "FACT_SCHEMA", "MONEY_SCHEMA", "PRICE_SCHEMA", "account_usage",
    "estimate_span_cost", "estimate_usage_cost", "price_usage", "estimate_cost", "calculate_cost",
    "normalize_provider_money", "qualified_observation",
]
