"""Small, honest timing metadata for existing recovery receipts.

This module does not retain state.  A caller owns the receipt and may use a
same-process monotonic clock for durations while UTC values remain the only
portable phase observations.  Missing, offline, and discontinuous phases are
represented explicitly instead of being converted into elapsed time.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Callable, Mapping, Optional


SCHEMA = "otto.recovery-timing.v1"
PHASES = ("queued", "processing", "native", "terminal")


def _utc(value: Optional[datetime] = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stable_correlation_id(value: Any, *, fallback: Optional[str] = None) -> Optional[str]:
    """Select an existing logical identity; never mint a random correlation."""

    if isinstance(value, Mapping):
        for key in ("correlation_id", "logical_request_key", "request_key", "request_id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    for key in ("correlation_id", "logical_request_key", "request_key", "request_id"):
        candidate = getattr(value, key, None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return fallback.strip() if isinstance(fallback, str) and fallback.strip() else None


class ReceiptTiming:
    """Build phase observations for one existing logical receipt."""

    def __init__(self, correlation_id: str, *, utc_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic_clock: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be non-blank text")
        self.correlation_id = correlation_id.strip()
        self._utc_clock, self._monotonic_clock = utc_clock, monotonic_clock
        self._phases: dict[str, dict[str, Any]] = {}
        self._monotonic: dict[str, float] = {}
        self._gaps: list[dict[str, str]] = []
        self._last_utc: Optional[datetime] = None

    def observe(self, phase: str, *, at: Optional[datetime] = None) -> "ReceiptTiming":
        if phase not in PHASES:
            raise ValueError("unsupported recovery timing phase: " + str(phase))
        current = at or self._utc_clock()
        if not isinstance(current, datetime):
            raise TypeError("utc_clock must return datetime")
        parsed = current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        monotonic = float(self._monotonic_clock())
        if self._last_utc is not None and parsed < self._last_utc:
            self._gaps.append({"kind": "clock_discontinuity", "phase": phase,
                               "reason": "UTC observation moved backwards"})
        self._last_utc = parsed
        self._phases[phase] = {"state": "observed", "observed_at": _utc(parsed),
                               "clock": "utc", "same_process_monotonic": True}
        self._monotonic[phase] = monotonic
        return self

    def absent(self, phase: str, *, reason: str = "not_observed") -> "ReceiptTiming":
        if phase not in PHASES:
            raise ValueError("unsupported recovery timing phase: " + str(phase))
        self._phases.setdefault(phase, {"state": "absent", "observed_at": None,
                                        "reason": reason, "clock": "unavailable"})
        self._gaps.append({"kind": "absent", "phase": phase, "reason": reason})
        return self

    def offline(self, phase: str, *, reason: str = "host_or_provider_offline") -> "ReceiptTiming":
        if phase not in PHASES:
            raise ValueError("unsupported recovery timing phase: " + str(phase))
        self._phases[phase] = {"state": "offline", "observed_at": None,
                               "reason": reason, "clock": "unavailable"}
        self._gaps.append({"kind": "offline", "phase": phase, "reason": reason})
        return self

    def as_dict(self) -> dict[str, Any]:
        phases = {phase: dict(self._phases.get(phase, {
            "state": "absent", "observed_at": None, "reason": "not_observed",
            "clock": "unavailable",
        })) for phase in PHASES}
        durations: dict[str, Any] = {}
        ordered = [phase for phase in PHASES if phase in self._monotonic]
        for before, after in zip(ordered, ordered[1:]):
            elapsed = self._monotonic[after] - self._monotonic[before]
            if elapsed < 0:
                self._gaps.append({"kind": "clock_discontinuity", "phase": after,
                                   "reason": "monotonic observation moved backwards"})
                continue
            durations[f"{before}_to_{after}_seconds"] = round(elapsed, 6)
        return {"schema": SCHEMA, "correlation_id": self.correlation_id,
                "phases": phases, "durations": durations,
                "gaps": list(self._gaps)}


def timing_from_receipt(receipt: Any, *, fallback_correlation_id: Optional[str] = None) -> dict[str, Any]:
    """Project receipt fields into timing, preserving cross-process gaps."""

    raw = dict(receipt) if isinstance(receipt, Mapping) else {}
    correlation = stable_correlation_id(raw, fallback=fallback_correlation_id) or "unbound"
    existing = raw.get("receipt_timing") or raw.get("phase_timing")
    if isinstance(existing, Mapping) and existing.get("schema") == SCHEMA:
        result = dict(existing)
        phases = {phase: dict(item) for phase, item in (result.get("phases") or {}).items()
                  if isinstance(item, Mapping)}
        for phase, field in (("queued", "queued_at"), ("processing", "started_at"),
                             ("native", "native_started_at"), ("terminal", "ended_at")):
            if _parse(raw.get(field)) and phases.get(phase, {}).get("state") != "observed":
                phases[phase] = {"state": "observed", "observed_at": raw[field],
                                 "clock": "utc", "same_process_monotonic": False}
        result["phases"] = phases
        result.setdefault("durations", {})
        result.setdefault("gaps", [])
        if any(item.get("state") == "observed" for item in phases.values()) and not result["durations"]:
            result["gaps"].append({"kind": "offline", "phase": "duration",
                                   "reason": "monotonic observations were not retained across this receipt boundary"})
        return result
    timing = ReceiptTiming(correlation)
    if _parse(raw.get("queued_at")):
        timing._phases["queued"] = {"state": "observed", "observed_at": raw["queued_at"], "clock": "utc", "same_process_monotonic": False}
    else:
        timing.absent("queued", reason="queue_observation_not_retained")
    if _parse(raw.get("started_at")):
        timing._phases["processing"] = {"state": "observed", "observed_at": raw["started_at"], "clock": "utc", "same_process_monotonic": False}
    else:
        timing.absent("processing", reason="processing_observation_not_retained")
    if _parse(raw.get("native_started_at")):
        timing._phases["native"] = {"state": "observed", "observed_at": raw["native_started_at"], "clock": "utc", "same_process_monotonic": False}
    elif raw.get("delivery_state") in {"offline", "unknown"} or raw.get("outcome") in {"unknown", "unavailable"}:
        timing.offline("native")
    else:
        timing.absent("native", reason="native_observation_not_retained")
    if _parse(raw.get("ended_at")):
        timing._phases["terminal"] = {"state": "observed", "observed_at": raw["ended_at"], "clock": "utc", "same_process_monotonic": False}
    else:
        timing.absent("terminal", reason="terminal_observation_not_retained")
    result = timing.as_dict()
    if any(item.get("state") == "observed" for item in result["phases"].values()):
        result["gaps"].append({"kind": "offline", "phase": "duration",
                               "reason": "monotonic observations were not retained across this receipt boundary"})
    return result


def attach_receipt_timing(receipt: Mapping[str, Any], timing: Mapping[str, Any], *, correlation_id: Optional[str] = None) -> dict[str, Any]:
    """Add additive metadata to an existing receipt without changing its result."""

    value = dict(receipt)
    selected = correlation_id or stable_correlation_id(value)
    if selected is not None:
        value.setdefault("correlation_id", selected)
    value["receipt_timing"] = dict(timing)
    return value
