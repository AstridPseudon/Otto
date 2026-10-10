"""Pure D01 contract for qualified cross-adapter usage observations.

This module freezes the small Usage boundary shared by the two existing Codex
paths and the selected Claude mechanical fixture.  It deliberately owns no
Store, registry, scheduler, provider call, recovery operation, or public
projection.  Adapter launch/assignment/occurrence records remain the identity
authority; Evidence, Recovery, and Events remain the retained-source, custody,
and bounded-reader authorities.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence


CONTRACT_SCHEMA = "otto.usage-cost.contract.v1"
OBSERVATION_SCHEMA = CONTRACT_SCHEMA + ".observation.v1"
RATE_SCHEDULE_SCHEMA = CONTRACT_SCHEMA + ".rate-schedule.v1"
FIXTURE_SCHEMA = CONTRACT_SCHEMA + ".fixture.v1"
SOURCE_COMMIT = "47fe605668527bcd8a2dbac6f0bc15529023a675"
MODEL = "gpt-5.6-luna"
REASONING = "high"
PROFILE = "workspace-write"

SELECTED_PACK_REF = {
    "authority": "otto-project-operating-setup-20261005-owner-v1",
    "id": "usage-bootstrap-20261010-v1-selected-pack",
    "kind": "dat.content.document",
    "revision": "rev-1",
}
SELECTED_RESOURCE_ROOT = (
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/"
    "otto-usage-cost-20261010/controller/selected-pack-source"
)

METRIC_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
CHARGEABLE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)
OBSERVATION_STATES = frozenset({
    "observed", "zero", "missing", "empty", "invalid", "unsupported_schema",
    "partial", "truncated", "conflict",
})
METRIC_SCOPES = frozenset({"turn", "invocation", "span"})


class UsageContractError(ValueError):
    """A Usage contract value is malformed or outside the bounded contract."""


def _json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise UsageContractError("value must be finite JSON") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise UsageContractError(f"{field} must be non-blank text")
    return value.strip()


def _sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        _json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _ref(value: Any, field: str) -> dict[str, Any]:
    value = _json(value)
    if not isinstance(value, Mapping):
        raise UsageContractError(f"{field} must be a reference object")
    result = dict(value)
    for name in ("authority", "kind", "id"):
        _text(result.get(name), f"{field}.{name}")
    if result.get("revision") is not None:
        _text(result["revision"], f"{field}.revision")
    return result


def _descriptor(
    adapter_id: str,
    *,
    provider: str,
    environment: str,
    native_schema: str,
    event_type: str,
    fields: Mapping[str, str],
    mechanical: str,
    live: str,
    routes: Mapping[str, str],
    source_paths: Sequence[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "adapter_id": adapter_id,
        "provider": provider,
        "environment": environment,
        "namespace": provider + "/" + environment,
        "native_schema": native_schema,
        "event_type": event_type,
        "usage_fields": dict(fields),
        "coverage": {"mechanical": mechanical, "live": live},
        "routes": dict(routes),
        "source_paths": list(source_paths),
        "qualification_reason": reason,
        "usage_capability": "supported" if mechanical == "supported" else mechanical,
    }


ADAPTER_DESCRIPTORS = {
    "codex-direct": _descriptor(
        "codex-direct", provider="openai", environment="managed-codex-cli",
        native_schema="codex-cli-jsonl.turn-completed.v1", event_type="turn.completed",
        fields={name: name for name in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")},
        mechanical="supported", live="supported",
        routes={"invoke": "supported", "resume": "supported", "attach": "unsupported", "native_children": "unsupported"},
        source_paths=["src/otto/agents/codex_cli.py", "src/otto/agents/gateway.py", "src/otto/agents/owner_runtime.py"],
        reason="direct Codex JSONL and owner admission/assignment/occurrence path are existing supported seams",
    ),
    "codex-host": _descriptor(
        "codex-host", provider="openai", environment="managed-codex-cli",
        native_schema="codex-cli-jsonl.turn-completed.v1", event_type="turn.completed",
        fields={name: name for name in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")},
        mechanical="supported", live="supported",
        routes={"invoke": "supported", "resume": "supported", "attach": "unsupported", "native_children": "unsupported"},
        source_paths=["src/herzchen/adapters/host.py", "src/herzchen/adapters/receipt.py", "src/otto/agents/gateway.py"],
        reason="host binding observes the same qualified Codex turn shape and retains separate host evidence",
    ),
    "claude-code": _descriptor(
        "claude-code", provider="anthropic", environment="managed-claude-code-mechanical",
        native_schema="otto.claude-code-2.1.293.stream-json.v1", event_type="result",
        fields={
            "input_tokens": "input_tokens",
            "cached_input_tokens": "cache_read_input_tokens",
            "cache_creation_input_tokens": "cache_creation_input_tokens",
            "output_tokens": "output_tokens",
        },
        mechanical="supported", live="unverified",
        routes={"invoke": "mechanical-only", "resume": "unsupported", "attach": "unsupported", "native_children": "unsupported"},
        source_paths=["src/otto/agents/claude_cli.py", "src/otto/agents/claude_adapter.py"],
        reason="native fixtures and stream validation are covered; paid live Claude work is explicitly deferred",
    ),
}


PREDECESSOR_SEAMS = {
    "adapter_records": {
        "owner": "Adapter launch/assignment/occurrence records",
        "paths": ["src/otto/agents/adapter_conformance.py", "src/otto/agents/gateway.py"],
        "rule": "consume existing identity records; do not add a registry",
    },
    "evidence": {
        "owner": "Evidence immutable retained pins and bounded resolver/detail reads",
        "paths": ["src/herzchen/evidence/model.py", "src/herzchen/evidence/commands.py", "src/herzchen/packs/evidence_resource_pack"],
        "rule": "raw and compact retained evidence stay in Evidence; this module only references it",
    },
    "recovery": {
        "owner": "Recovery claim, custody, and exact-attempt reconciliation",
        "paths": ["src/herzchen/kernel/recovery.py", "src/otto/portfolio/recovery_discovery.py"],
        "rule": "no second recovery engine or replay path",
    },
    "events": {
        "owner": "Events source facets, append ordering, snapshot, and bounded detail readers",
        "paths": ["src/herzchen/kernel/history.py", "src/otto/portfolio/observability_contract.py", "src/otto/portfolio/observability_views.py"],
        "rule": "usage facts attach as typed facets; no second ledger or view store",
    },
}


PROVENANCE = {
    "source": {
        "commit": SOURCE_COMMIT,
        "workspace_role": "candidate-source",
        "root": "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-usage-cost-20261010/work/integration-owner",
    },
    "runtime": {
        "model": MODEL,
        "reasoning": REASONING,
        "profile": PROFILE,
        "adapter": "otto.usage.installed-codex-cli.v1",
        "interpreter": "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9",
        "command": "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9 /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-usage-cost-20261010/controller/manager_ctl.py",
    },
    "resource": {
        "selected_pack_ref": SELECTED_PACK_REF,
        "selected_pack_root": SELECTED_RESOURCE_ROOT,
        "pack_content_sha256": "6089b3dd22bf82d32d7b94ab23187a6db8fdf0357bd1d587a78ba2c13bc68846",
        "bundle_digest": "e8c2eb3fecb51961e99ee7740c1c04aba49989fdc84ea3fdd0f4808ec2e52826",
        "export_manifest_digest": "f4c6832bc44a8d31ea602b855cd54f4b152fc0893bca8e4ee4f79757549ff1c6",
        "resource_set_digest": "ad9b69547fbe0cdbfe56913804c1ad2248d933678e89e1de5b307f533d171c34",
    },
}


RATE_SCHEDULE = {
    "schema": RATE_SCHEDULE_SCHEMA,
    "schedule_id": "usage-d01-reviewed-static-fixture-v1",
    "status": "reviewed-static-fixture",
    "currency": "USD",
    "unit": "per_token",
    "effective_period": {"from": "2026-01-01T00:00:00Z", "to": "2026-12-31T23:59:59Z"},
    "source": {
        "kind": "candidate-review-input",
        "id": "usage-d01-reviewed-static-rate-basis",
        "note": "deterministic contract fixture; not an online price source or billing fact",
    },
    "formula": "sum(uncached input, cached input, cache creation input, output) * decimal rate; reasoning is an output subpartition",
    "reasoning_additive": False,
    "entries": {
        "gpt-5.6-luna/default": {
            "input_tokens": "0.00000300",
            "cached_input_tokens": "0.00000030",
            "cache_creation_input_tokens": "0.00000300",
            "output_tokens": "0.00001500",
        },
        "claude-sonnet-4-5/default": {
            "input_tokens": "0.00000300",
            "cached_input_tokens": "0.00000030",
            "cache_creation_input_tokens": "0.00000375",
            "output_tokens": "0.00001500",
        },
    },
}


def adapter_descriptors() -> dict[str, Any]:
    return deepcopy(ADAPTER_DESCRIPTORS)


def _rate(value: Any, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise UsageContractError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise UsageContractError(f"{field} is not a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise UsageContractError(f"{field} must be a finite nonnegative decimal")
    return parsed


def validate_rate_schedule(value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    schedule = deepcopy(RATE_SCHEDULE if value is None else _json(value))
    if schedule.get("schema") != RATE_SCHEDULE_SCHEMA:
        raise UsageContractError("unsupported rate schedule schema")
    _text(schedule.get("schedule_id"), "schedule_id")
    if schedule.get("currency") != "USD" or schedule.get("unit") != "per_token":
        raise UsageContractError("rate schedule currency/unit are not qualified")
    if schedule.get("reasoning_additive") is not False:
        raise UsageContractError("reasoning subset must not be charged twice")
    source = schedule.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "candidate-review-input":
        raise UsageContractError("rate schedule provenance is missing")
    entries = schedule.get("entries")
    if not isinstance(entries, Mapping) or not entries:
        raise UsageContractError("rate schedule has no model entries")
    for model_tier, entry in entries.items():
        _text(model_tier, "rate entry")
        if not isinstance(entry, Mapping) or set(entry) != set(CHARGEABLE_FIELDS):
            raise UsageContractError("rate entry must cover every chargeable partition")
        for field in CHARGEABLE_FIELDS:
            _rate(entry[field], f"{model_tier}.{field}")
    return schedule


def physical_span_identity(
    *,
    namespace: str,
    metric_scope: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
) -> dict[str, str]:
    """Return the non-additive identity of one measured physical span."""

    namespace = _text(namespace, "namespace")
    metric_scope = _text(metric_scope, "metric_scope")
    if metric_scope not in METRIC_SCOPES:
        raise UsageContractError("cumulative/session allocation is outside the D01 scope")
    session = None if session_id is None else _text(session_id, "session_id")
    turn = None if turn_id is None else _text(turn_id, "turn_id")
    invocation = None if invocation_id is None else _text(invocation_id, "invocation_id")
    if not ((session and turn) or invocation):
        raise UsageContractError("physical span needs session+turn or an authoritative invocation id")
    identity = {
        "namespace": namespace,
        "metric_scope": metric_scope,
        "session_id": session,
        "turn_id": turn,
        "invocation_id": invocation,
    }
    return {**identity, "span_id": "usage-span-" + _sha256(identity)}


def _state_for_usage(event: Mapping[str, Any], descriptor: Mapping[str, Any]) -> tuple[str, dict[str, int], Optional[str]]:
    if event.get("partial") is True or event.get("usage_complete") is False:
        return "partial", {}, "native event explicitly reports partial usage"
    if event.get("truncated") is True:
        return "truncated", {}, "native capture was explicitly truncated"
    if event.get("conflict") is True or event.get("usage_state") == "conflict":
        return "conflict", {}, "provider/native observations conflict"
    if "usage" not in event:
        return "missing", {}, "native event did not emit usage"
    raw = event.get("usage")
    if raw is None or raw == {}:
        return "empty", {}, "native usage object is empty"
    if not isinstance(raw, Mapping):
        return "invalid", {}, "native usage is not an object"
    fields = descriptor["usage_fields"]
    metrics: dict[str, int] = {}
    recognized = False
    for canonical, native in fields.items():
        if native not in raw:
            continue
        recognized = True
        value = raw[native]
        if type(value) is not int or value < 0:
            return "invalid", {}, f"{native} must be a nonnegative integer"
        metrics[canonical] = value
    if not recognized:
        return "invalid", {}, "native usage has no qualified metric fields"
    return ("zero" if all(value == 0 for value in metrics.values()) else "observed"), metrics, None


def normalize_usage_event(
    event: Mapping[str, Any],
    *,
    adapter_id: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
    metric_scope: str = "turn",
    requested_model: Optional[str] = None,
    requested_tier: Optional[str] = None,
    observed_model: Optional[str] = None,
    observed_tier: Optional[str] = None,
    provenance: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Normalize one already-retained native event; never infer usage."""

    if adapter_id not in ADAPTER_DESCRIPTORS:
        raise UsageContractError("unsupported adapter descriptor")
    if not isinstance(event, Mapping):
        raise UsageContractError("native event must be an object")
    descriptor = ADAPTER_DESCRIPTORS[adapter_id]
    event = _json(event)
    expected_schema = descriptor["native_schema"]
    expected_type = descriptor["event_type"]
    schema_present = "schema" in event
    schema_mismatch = schema_present and event.get("schema") != expected_schema
    type_mismatch = event.get("type") != expected_type
    if schema_mismatch or type_mismatch:
        state, metrics, reason = "unsupported_schema", {}, "event schema/type is outside the selected adapter descriptor"
    else:
        state, metrics, reason = _state_for_usage(event, descriptor)
        # A numeric observation, including an explicit zero, is qualified only
        # when the native event carries the exact descriptor schema.  Keep
        # schema-less missing/empty/malformed/partial/truncated/conflict
        # outcomes distinct rather than turning every incomplete event into a
        # schema error.
        if state in {"observed", "zero"} and not schema_present:
            state, metrics, reason = (
                "unsupported_schema",
                {},
                "numeric usage requires the exact selected adapter schema",
            )
    session = session_id or event.get("session_id") or event.get("thread_id")
    turn = turn_id or event.get("turn_id") or event.get("uuid")
    span = None
    if state not in {"missing", "empty", "invalid", "unsupported_schema", "partial", "truncated", "conflict"} or session or turn or invocation_id:
        try:
            span = physical_span_identity(namespace=descriptor["namespace"], metric_scope=metric_scope,
                                          session_id=session, turn_id=turn, invocation_id=invocation_id)
        except UsageContractError:
            if state not in {"missing", "empty", "invalid", "unsupported_schema", "partial", "truncated", "conflict"}:
                raise
    if provenance is None:
        provenance = {"native_schema": expected_schema, "adapter_id": adapter_id, "event_type": expected_type}
    provenance = _json(provenance)
    if not isinstance(provenance, Mapping):
        raise UsageContractError("provenance must be an object")
    result = {
        "schema": OBSERVATION_SCHEMA,
        "adapter_id": adapter_id,
        "capability": {
            "mechanical": descriptor["coverage"]["mechanical"],
            "live": descriptor["coverage"]["live"],
        },
        "provider_environment": {
            "provider": descriptor["provider"],
            "environment": descriptor["environment"],
            "namespace": descriptor["namespace"],
        },
        "identity": span,
        "requested": {"model": requested_model, "tier": requested_tier},
        "observed": {"model": observed_model or event.get("model"), "tier": observed_tier or event.get("tier")},
        "provenance": dict(provenance),
        "usage": {
            "state": state,
            "metrics": metrics or None,
            "scope": metric_scope,
            "reason": reason,
            "component_semantics": {
                "input_tokens": "uncached input partition when provider distinguishes it",
                "cached_input_tokens": "cached input partition; not added to uncached input",
                "cache_creation_input_tokens": "cache creation input partition; provider-specific and optional",
                "output_tokens": "provider-reported output total",
                "reasoning_output_tokens": "output subpartition for provenance; not additive by default",
                "cumulative": "not additive; unavailable for D01 totals",
                "descendants": "not included unless a disjoint physical span is proven",
            },
        },
        "limits": {
            "max_native_line_bytes": 256 * 1024,
            "max_capture_bytes": 2 * 1024 * 1024,
            "max_metric_fields": len(METRIC_FIELDS),
            "raw_payload": "retained by Evidence; this observation is a bounded summary",
        },
    }
    return result


def contract_definition() -> dict[str, Any]:
    """Return the immutable, JSON-safe D01 contract and predecessor map."""

    return {
        "schema": CONTRACT_SCHEMA,
        "revision": "usage-d01.v1",
        "provenance": deepcopy(PROVENANCE),
        "adapters": adapter_descriptors(),
        "metric_schema": {
            "scope": "per-turn or one authoritative invocation/span",
            "fields": list(METRIC_FIELDS),
            "accepted_values": "nonnegative JSON integers only; booleans, floats, text, negatives rejected",
            "statuses": sorted(OBSERVATION_STATES),
            "unknown_is_zero": False,
        },
        "identity": {
            "basis": "qualified provider/environment namespace + physical session/turn or authoritative invocation + metric scope",
            "aliases": ["adapter carrier", "request id", "provider/native event id", "retained report id"],
            "deduplication": "equivalent aliases coalesce; richer components do not create another charge",
        },
        "rates": validate_rate_schedule(),
        "unsupported_routes": [
            "provider billing facts and invoice APIs",
            "online rate fetch and invented FX",
            "cumulative delta/session allocation",
            "native child inventory and speculative shared splits",
            "paid Claude initialization, inference, or resume qualification",
        ],
        "predecessor_seams": deepcopy(PREDECESSOR_SEAMS),
    }


def fixture_catalog() -> dict[str, Any]:
    """Return native mechanical fixtures for both Codex paths and Claude."""

    codex_event = {
        "schema": ADAPTER_DESCRIPTORS["codex-direct"]["native_schema"],
        "type": "turn.completed", "thread_id": "codex-session-1", "turn_id": "codex-turn-1",
        "model": MODEL,
        "usage": {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30, "reasoning_output_tokens": 10},
    }
    return {
        "schema": FIXTURE_SCHEMA,
        "evidence_kind": "synthetic-mechanical-fixtures",
        "paid_provider_calls": False,
        "fixtures": {
            "codex-direct": {"event": deepcopy(codex_event), "expected_state": "observed"},
            "codex-host": {"event": deepcopy(codex_event), "expected_state": "observed"},
            "claude-code": {
                "event": {
                    "schema": ADAPTER_DESCRIPTORS["claude-code"]["native_schema"], "type": "result",
                    "session_id": "claude-session-1", "uuid": "claude-turn-1",
                    "usage": {"input_tokens": 100, "cache_read_input_tokens": 20,
                               "cache_creation_input_tokens": 5, "output_tokens": 30},
                },
                "expected_state": "observed",
            },
        },
        "negative_distinctions": {
            "missing": {"type": "turn.completed"},
            "empty": {"type": "turn.completed", "usage": {}},
            "zero": {
                "schema": ADAPTER_DESCRIPTORS["codex-direct"]["native_schema"],
                "type": "turn.completed", "usage": {"input_tokens": 0},
            },
            "malformed": {"type": "turn.completed", "usage": {"input_tokens": True}},
            "unsupported_schema": {"schema": "future.schema.v9", "type": "turn.completed", "usage": {"input_tokens": 1}},
            "partial": {"type": "turn.completed", "partial": True, "usage": {"input_tokens": 1}},
            "truncated": {"type": "turn.completed", "truncated": True, "usage": {"input_tokens": 1}},
            "conflict": {"type": "turn.completed", "conflict": True, "usage": {"input_tokens": 1}},
        },
    }


def run_fixture_contract() -> dict[str, Any]:
    """Run only the pure D01 fixture checks and classify their evidence."""

    catalog = fixture_catalog()
    passed: list[str] = []
    failures: list[dict[str, str]] = []
    for adapter_id, fixture in catalog["fixtures"].items():
        try:
            normalized = normalize_usage_event(fixture["event"], adapter_id=adapter_id)
            if normalized["usage"]["state"] != fixture["expected_state"]:
                raise UsageContractError("fixture state mismatch")
            if normalized["identity"] is None:
                raise UsageContractError("qualified fixture lacks physical span identity")
        except UsageContractError as exc:
            failures.append({"fixture": adapter_id, "message": str(exc)})
        else:
            passed.append(adapter_id)
    for name, event in catalog["negative_distinctions"].items():
        try:
            adapter_id = "claude-code" if name == "unsupported_schema" and event.get("schema", "").startswith("future") else "codex-direct"
            state = normalize_usage_event(event, adapter_id=adapter_id, session_id="negative-session", turn_id="negative-turn")["usage"]["state"]
            expected = "invalid" if name == "malformed" else name
            if state != expected:
                raise UsageContractError(f"expected {expected}, got {state}")
        except UsageContractError as exc:
            failures.append({"fixture": name, "message": str(exc)})
        else:
            passed.append(name)
    return {"schema": CONTRACT_SCHEMA + ".fixture-report.v1", "outcome": "passed" if not failures else "failed",
            "evidence_kind": catalog["evidence_kind"], "paid_provider_calls": False,
            "passed": passed, "failures": failures}


__all__ = [
    "CONTRACT_SCHEMA", "OBSERVATION_SCHEMA", "RATE_SCHEDULE_SCHEMA", "FIXTURE_SCHEMA",
    "SOURCE_COMMIT", "MODEL", "REASONING", "PROFILE", "METRIC_FIELDS", "CHARGEABLE_FIELDS",
    "OBSERVATION_STATES", "UsageContractError", "adapter_descriptors", "contract_definition",
    "fixture_catalog", "normalize_usage_event", "physical_span_identity", "validate_rate_schedule",
    "run_fixture_contract",
]
