"""Bounded optional usage observations at the selected native stream boundary.

The transport qualifies the schema; worker/tool text never enters this parser.
The owner supplies historical association and durable capture. This module owns
no storage, launch authority or accounting ledger.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Optional

from .usage_contract import ADAPTER_DESCRIPTORS, normalize_usage_event

MAX_LINE_BYTES = 256 * 1024
MAX_CAPTURE_BYTES = 2 * 1024 * 1024
MAX_OBSERVATIONS = 128
CAPTURE_SCHEMA = "otto.usage-capture.v1"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def optional_emit(callback: Any, observation: Mapping[str, Any]) -> bool:
    if not callable(callback):
        return False
    try:
        callback(dict(observation))
        return True
    except Exception:
        # Optional telemetry must never enter the authority/native-start error path.
        return False


class UsageStream:
    """One initializer/work stream with exact completion-local native identity."""

    def __init__(self, adapter_id: str, *, phase: str = "work",
                 session_id: Optional[str] = None, requested_model: Optional[str] = None,
                 requested_tier: Optional[str] = None, source_ref: Any = None,
                 on_usage: Optional[Callable[[Mapping[str, Any]], Any]] = None,
                 turn_resolver: Optional[Callable[[str], Optional[str]]] = None) -> None:
        if adapter_id not in ADAPTER_DESCRIPTORS or phase not in {"initializer", "work", "resume"}:
            raise ValueError("selected adapter and physical phase are required")
        self.adapter_id, self.phase, self.session_id = adapter_id, phase, session_id
        self.turn_id = None
        self.requested_model, self.requested_tier = requested_model, requested_tier
        self.observed_model = None
        self.source_ref, self.on_usage = source_ref, on_usage
        self.turn_resolver = turn_resolver
        self.observations: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._pending: dict[str, dict[str, Any]] = {}
        self.bytes = self.lines = self.invalid_lines = 0
        self.truncated = False

    def feed(self, raw: str | bytes) -> Optional[dict[str, Any]]:
        try:
            return self._feed(raw)
        except Exception:
            # Parser/diagnostic failures are optional, including malformed
            # deeply nested JSON and invalid text from an injected transport.
            self.invalid_lines += 1
            return None

    def _feed(self, raw: str | bytes) -> Optional[dict[str, Any]]:
        self.lines += 1
        # An oversized worker/native body does not consume the small metric
        # budget and suppress a later provider completion. Never parse it.
        if len(raw) > MAX_LINE_BYTES:
            self.truncated = True
            return None
        body = bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw.encode("utf-8")
        if len(body) > MAX_LINE_BYTES or self.bytes + len(body) > MAX_CAPTURE_BYTES:
            self.truncated = True
            return None
        self.bytes += len(body)
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate native key")
                    result[key] = value
                return result
            event = json.loads(body, object_pairs_hook=unique, parse_float=str,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError, TypeError):
            self.invalid_lines += 1
            return None
        if not isinstance(event, Mapping):
            self.invalid_lines += 1
            return None
        kind = event.get("type")
        if self.adapter_id.startswith("codex"):
            if kind == "thread.started":
                session = event.get("thread_id")
                if isinstance(session, str) and session.strip():
                    if self.session_id is not None and self.session_id != session:
                        self.invalid_lines += 1
                        return None
                    self.session_id = session
                if isinstance(event.get("model"), str):
                    self.observed_model = event["model"]
                return None
            if kind == "turn.started":
                turn = event.get("turn_id")
                self.turn_id = turn if isinstance(turn, str) and turn.strip() else None
                return None
            if kind != "turn.completed":
                return None
            turn = event.get("turn_id")
            if isinstance(turn, str) and turn.strip():
                self.turn_id = turn
            turn_id = self.turn_id
            if turn_id is None and self.session_id and callable(self.turn_resolver):
                try:
                    turn_id = self.turn_resolver(self.session_id)
                except Exception:
                    # Usage-only metadata resolution is optional. Admission
                    # remains the separate authority-critical callback.
                    turn_id = None
        else:
            if kind == "system" and event.get("subtype") == "init":
                self.session_id = event.get("session_id")
                self.observed_model = event.get("model")
                return None
            if kind == "user" and self.turn_id is None and event.get("session_id") == self.session_id and isinstance(event.get("uuid"), str):
                self.turn_id = event["uuid"]
                return None
            if kind != "result":
                return None
            if event.get("session_id") != self.session_id:
                self.invalid_lines += 1
                return None
            turn_id = self.turn_id or event.get("uuid")
        # Only selected host transports call feed. Native JSONL does not carry
        # Otto's schema label: supply the pinned transport descriptor here.
        qualified = {key: event[key] for key in (
            "type", "schema", "usage", "model", "tier", "partial", "truncated",
            "usage_complete", "conflict", "usage_state", "total_cost_usd") if key in event}
        qualified.setdefault("schema", ADAPTER_DESCRIPTORS[self.adapter_id]["native_schema"])
        try:
            observation = normalize_usage_event(qualified, adapter_id=self.adapter_id,
                session_id=self.session_id, turn_id=turn_id,
                requested_model=self.requested_model, requested_tier=self.requested_tier,
                observed_model=event.get("model") or self.observed_model,
                provenance={"adapter_id": self.adapter_id,
                    "native_schema": ADAPTER_DESCRIPTORS[self.adapter_id]["native_schema"],
                    "parser": CAPTURE_SCHEMA, "raw_line_sha256": hashlib.sha256(body).hexdigest(),
                    "raw_line_bytes": len(body), "source_ref": self.source_ref})
        except ValueError:
            # An unbound completion remains visible without an invented span.
            qualified.pop("usage", None)
            observation = normalize_usage_event(qualified, adapter_id=self.adapter_id,
                requested_model=self.requested_model)
            observation["usage"].update(state="missing", reason="exact native session/turn unavailable")
        observation["phase"] = self.phase
        # Missing explicit completion ID must not reuse the previous completion.
        self.turn_id = None
        identity = digest({"identity": observation["identity"], "usage": observation["usage"],
            "observed": observation["observed"], "money": observation.get("provider_reported_money"), "phase": self.phase})
        observation["observation_id"] = identity
        if identity in self._seen:
            return observation
        if len(self.observations) >= MAX_OBSERVATIONS:
            self.truncated = True
            return None
        self._seen.add(identity)
        self.observations.append(observation)
        emitted = {**observation, "native_source": body.decode("utf-8")}
        def emit_with_readback(item):
            captured = self.on_usage(item)
            if isinstance(captured, Mapping) and captured.get("observation_id") == identity:
                # Only optional owner metadata is added. Callback readback
                # cannot replace the parser's physical identity or metrics.
                for field in ("association", "first_qualified_recorded_at"):
                    if field in captured:
                        observation[field] = captured[field]
                pin = (captured.get("provenance") or {}).get("retained_source")
                if pin is not None:
                    observation["provenance"]["retained_source"] = pin
        if not callable(self.on_usage) or not optional_emit(emit_with_readback, emitted):
            self._pending[identity] = emitted
        return observation

    def snapshot(self) -> dict[str, Any]:
        # Failed optional callbacks may have an unknown durable effect. Terminal
        # inclusion carries the same observation; automatic callback resend is
        # deliberately suppressed until the owner reconciles its exact claim.
        return {"schema": CAPTURE_SCHEMA, "phase": self.phase,
            "observations": list(self.observations),
            "coverage": {"state": "truncated" if self.truncated else (
                "observed" if self.observations else "missing"),
                "invalid_lines": self.invalid_lines, "capture_bytes": min(self.bytes, MAX_CAPTURE_BYTES),
                "callback_pending": len(self._pending),
                "raw_payload": "retained" if self.observations and all(
                    item.get("provenance", {}).get("retained_source") for item in self.observations)
                    else ("locator-only" if self.source_ref is not None else "unavailable")}}


def compact_usage_capture(value: Any) -> dict[str, Any]:
    """Optional bounded status projection; failures cannot change execution."""
    try:
        summary = _compact_usage_capture(value)
        if len(json.dumps(summary, allow_nan=False).encode()) <= 16384:
            return summary
    except Exception:
        pass
    return {"schema": CAPTURE_SCHEMA + ".summary", "state": "unavailable",
            "reason": "invalid or oversized optional observation summary"}


def _compact_usage_capture(value: Any) -> dict[str, Any]:
    """Small status carrier, never a native-body or totals projection."""
    if not isinstance(value, Mapping):
        return {"schema": CAPTURE_SCHEMA + ".summary", "state": "missing", "span_count": 0,
                "reason": "no qualified observation carrier retained"}
    carriers = [value] if "observations" in value else [value.get("initializer"), value.get("work")]
    observations = [item for carrier in carriers if isinstance(carrier, Mapping)
        for item in carrier.get("observations", ())][:MAX_OBSERVATIONS]
    states = sorted({item.get("usage", {}).get("state", "missing") for item in observations})
    return {"schema": CAPTURE_SCHEMA + ".summary", "state": "measured" if any(state in {"zero", "observed"} for state in states) else "unavailable",
        "span_count": len({item["identity"]["span_id"] for item in observations if item.get("identity")}),
        "observation_count": len(observations), "metric_states": states,
        "source_inventory_complete": len(observations) <= 16,
        "sources": [{"observation_id": item.get("observation_id"), "identity": item.get("identity"),
            "phase": item.get("phase"), "source_ref": item.get("provenance", {}).get("retained_source")
                or item.get("provenance", {}).get("source_ref")} for item in observations[:16]],
        "coverage": [carrier.get("coverage") for carrier in carriers if isinstance(carrier, Mapping)]}
